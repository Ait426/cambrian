"""Pack job reply ingest와 validation handoff를 기존 bridge/continue 흐름에 연결한다."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_bridge_fastpath import BridgeFastPathCoordinator, BridgeFastPathRecord
from engine.project_continue import ProjectDoContinuationRunner
from engine.project_do import DoSession, DoSessionStore
from engine.project_pack_activation import context_for_installed_pack
from engine.project_pack_install import SCHEMA_VERSION, _as_list, _now, _relative, _save_yaml, _slug
from engine.project_pack_jobs import (
    PackJob,
    PackJobNextBuilder,
    PackJobStore,
    default_pack_job_path,
    resolve_pack_job_path,
)
from engine.project_pack_usage import safe_record_pack_usage_from_context

logger = logging.getLogger(__name__)


@dataclass
class PackJobReplyResult:
    """AI reply를 pack job에 붙인 결과."""

    schema_version: str
    generated_at: str
    job_id: str
    job_ref: str
    pack_id: str
    reply_kind: str | None
    bridge_reply_ref: str | None
    bridge_review_ref: str | None
    bridge_handoff_ref: str | None
    materialization_ref: str | None
    context_hint_ref: str | None
    checklist_ref: str | None
    patch_intent_ref: str | None
    session_ref: str | None
    status: str
    next_command: str | None
    next_actions: list[str]
    reply_contract_status: str = "unknown"
    reply_file_ref: str | None = None
    request_packet_ref: str | None = None
    patch_candidate_accepted: bool = False
    patch_applied: bool = False
    source_code_modified: bool = False
    ai_provider_called: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        payload = asdict(self)
        payload["ok"] = self.status not in {"blocked", "failed"}
        payload["next_commands"] = list(self.next_actions)
        return payload


@dataclass
class PackJobValidationResult:
    """Pack job validation handoff 결과."""

    schema_version: str
    generated_at: str
    job_id: str
    job_ref: str
    pack_id: str
    session_id: str | None
    session_ref: str | None
    proposal_ref: str | None
    validation_status: str
    outcome_snapshot: dict[str, Any]
    next_command: str | None
    next_actions: list[str]
    validation_contract_status: str = "unknown"
    trust_gate_status: str = "unknown"
    checked_artifacts: list[str] = field(default_factory=list)
    unchecked_items: list[str] = field(default_factory=list)
    validation_commands: list[str] = field(default_factory=list)
    manual_validation_required: bool = False
    evidence_ref: str | None = None
    request_packet_ref: str | None = None
    reply_file_ref: str | None = None
    patch_intent_ref: str | None = None
    patch_applied: bool = False
    source_code_modified: bool = False
    ai_provider_called: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        payload = asdict(self)
        payload["ok"] = self.validation_status == "validated" and self.trust_gate_status == "passed"
        payload["next_commands"] = list(self.next_actions)
        return payload


class PackJobReplyHandler:
    """Pack job에 AI reply를 붙이고 bridge fast path로 라우팅한다."""

    def paste(self, project_root: Path, job_ref: str, text: str) -> PackJobReplyResult:
        """stdin 텍스트 reply를 pack job에 붙인다."""
        reply_text = str(text or "").strip()
        if not reply_text:
            raise ValueError("AI reply text is required on stdin")
        root, job, job_path = _load_job(project_root, job_ref)
        record = BridgeFastPathCoordinator().run_text(
            root,
            reply_text,
            packet_ref=job.linked_bridge_packet_ref,
            session_ref=job.linked_session_id,
        )
        return _apply_fastpath_record(root, job, job_path, record, surface_kind="pack_job_paste")

    def ingest(self, project_root: Path, job_ref: str, reply_file: Path) -> PackJobReplyResult:
        """파일 reply를 pack job에 붙인다."""
        root, job, job_path = _load_job(project_root, job_ref)
        record = BridgeFastPathCoordinator().run_file(
            root,
            Path(reply_file),
            packet_ref=job.linked_bridge_packet_ref,
            session_ref=job.linked_session_id,
        )
        return _apply_fastpath_record(root, job, job_path, record, surface_kind="pack_job_ingest")


class PackJobValidator:
    """validation-ready pack job을 continue --validate 경로로 이어준다."""

    def validate(self, project_root: Path, job_ref: str) -> PackJobValidationResult:
        """Pack job을 validated proposal까지 이어간다. apply/adoption은 수행하지 않는다."""
        root, job, job_path = _load_job(project_root, job_ref)
        job_file_ref = _relative(default_pack_job_path(root, job), root)
        if job.status == "validated":
            return _validation_result(root, job, job_file_ref, "validated", [])
        if job.pack_kind == "custom_harness" or job.pack_id.startswith("custom-"):
            return _validate_custom_harness_job(root, job, job_path, job_file_ref)
        if job.pack_id == "typescript-jest-auth-core":
            return _validate_typescript_jest_job(root, job, job_path, job_file_ref)
        blockers = _validation_blockers(job)
        if blockers:
            job.validation_status = "not_ready"
            job.status = "blocked"
            job.errors = _dedupe([*job.errors, *blockers])
            job.next_command = f"cambrian pack job-paste {job.job_id}"
            job.next_actions = PackJobNextBuilder().build(root, job)
            _save_job(root, job, job_path)
            return _validation_result(root, job, job_file_ref, "not_ready", blockers)

        _enrich_session_metrics(root, job)
        continued = ProjectDoContinuationRunner().run(
            root,
            {
                "session": job.linked_session_id or job.linked_session_ref,
                "validate": True,
            },
        )
        _normalize_returned_session_metrics(root, job, continued)
        _attach_session_to_job(job, continued)
        job.linked_proposal_ref = _proposal_ref(continued)
        job.outcome_snapshot = _outcome_snapshot(continued)
        if continued.current_stage == "patch_proposal_validated":
            job.status = "validated"
            job.validation_status = "validated"
            job.final_status = job.final_status or "validated"
            job.completed_at = _now()
            job.next_command = f"cambrian pack job-apply {job.job_id}"
        elif continued.status == "blocked":
            job.status = "blocked"
            job.validation_status = "blocked"
            job.next_command = f"cambrian pack job-show {job.job_id}"
        else:
            job.status = "validation_ready"
            job.validation_status = "failed"
            job.next_command = f"cambrian pack job-validate {job.job_id}"
        job.next_actions = PackJobNextBuilder().build(root, job)
        event_ref = _record_job_usage(root, job, surface_kind="pack_job_validate")
        if event_ref:
            job.usage_event_ref = event_ref
        _save_job(root, job, job_path)
        return _validation_result(root, job, job_file_ref, job.validation_status or "failed", list(continued.warnings))


def render_pack_job_reply_result(result: PackJobReplyResult) -> str:
    """pack job reply 결과를 사람이 읽기 좋게 렌더링한다."""
    title = "Pack Job Reply Routed" if result.status not in {"blocked", "failed"} else "Pack Job Reply Blocked"
    lines = [
        title,
        "==================================================",
        "",
        "Job:",
        f"  {result.job_id}",
        "",
        "Reply kind:",
        f"  {result.reply_kind or 'unknown'}",
        "",
        "Status:",
        f"  {result.status}",
    ]
    created = [
        ("reply", result.bridge_reply_ref),
        ("review", result.bridge_review_ref),
        ("handoff", result.bridge_handoff_ref),
        ("patch intent", result.patch_intent_ref),
        ("session", result.session_ref),
        ("materialization", result.materialization_ref),
        ("context hint", result.context_hint_ref),
        ("checklist", result.checklist_ref),
    ]
    present = [(label, ref) for label, ref in created if ref]
    if present:
        lines.extend(["", "Created:"])
        lines.extend([f"  {label:<15}: {ref}" for label, ref in present])
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    lines.extend(
        [
            "",
            "Safety:",
            f"  AI provider called: {str(result.ai_provider_called).lower()}",
            f"  Source code modified: {str(result.source_code_modified).lower()}",
            f"  Patch applied: {str(result.patch_applied).lower()}",
        ]
    )
    lines.extend(["", "Next:"])
    lines.extend([f"  {item}" for item in result.next_actions] or ["  inspect the job"])
    return "\n".join(lines)


def render_pack_job_validation_result(result: PackJobValidationResult) -> str:
    """pack job validation 결과를 사람이 읽기 좋게 렌더링한다."""
    title = "Pack Job Validation" if result.validation_status == "validated" else "Pack Job Validation Blocked"
    lines = [
        title,
        "==================================================",
        "",
        "Job:",
        f"  {result.job_id}",
        "",
        "Status:",
        f"  {result.validation_status}",
    ]
    if result.proposal_ref:
        lines.extend(["", "Proposal:", f"  {result.proposal_ref}"])
    if result.outcome_snapshot:
        lines.extend(["", "Outcome:"])
        for key, value in result.outcome_snapshot.items():
            lines.append(f"  {key}: {value}")
    lines.extend(
        [
            "",
            "Trust gate:",
            f"  status: {result.trust_gate_status}",
            f"  contract: {result.validation_contract_status}",
            f"  manual_validation_required: {result.manual_validation_required}",
        ]
    )
    if result.validation_commands:
        lines.extend(["", "Validation commands:"])
        lines.extend([f"  - {item}" for item in result.validation_commands])
    if result.checked_artifacts:
        lines.extend(["", "Checked artifacts:"])
        lines.extend([f"  - {item}" for item in result.checked_artifacts])
    if result.unchecked_items:
        lines.extend(["", "Unchecked items:"])
        lines.extend([f"  - {item}" for item in result.unchecked_items])
    if result.evidence_ref:
        lines.extend(["", "Evidence:", f"  {result.evidence_ref}"])
    lines.extend(
        [
            "",
            "Safety:",
            f"  patch_applied: {result.patch_applied}",
            f"  source_code_modified: {result.source_code_modified}",
            f"  ai_provider_called: {result.ai_provider_called}",
        ]
    )
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    lines.extend(["", "Next:"])
    lines.extend([f"  {item}" for item in result.next_actions] or ["  inspect the job"])
    return "\n".join(lines)


def _load_job(project_root: Path, job_ref: str) -> tuple[Path, PackJob, Path]:
    root = Path(project_root).resolve()
    job_path = resolve_pack_job_path(root, job_ref)
    job = PackJobStore().load(job_path)
    return root, job, default_pack_job_path(root, job)


def _apply_fastpath_record(
    root: Path,
    job: PackJob,
    job_path: Path,
    record: BridgeFastPathRecord,
    *,
    surface_kind: str,
) -> PackJobReplyResult:
    job.reply_kind = record.response_kind
    job.linked_bridge_reply_ref = record.reply_ref
    job.linked_bridge_review_ref = record.review_ref
    job.linked_bridge_handoff_ref = record.handoff_ref
    job.linked_materialization_ref = record.materialization_ref
    job.linked_context_hint_ref = record.context_hint_ref
    job.linked_checklist_ref = record.checklist_ref
    job.linked_patch_intent_ref = record.patch_intent_ref
    job.linked_session_id = record.linked_session_id or job.linked_session_id
    job.linked_session_ref = record.linked_session_ref or job.linked_session_ref
    job.updated_at = _now()
    job.warnings = _dedupe([*job.warnings, *record.warnings])
    job.errors = _dedupe([*job.errors, *record.errors])

    if record.status == "session_linked" and record.patch_intent_ref:
        job.status = "validation_ready"
        job.validation_status = "ready"
        job.next_command = f"cambrian pack job-validate {job.job_id}"
    elif record.status == "materialized" and record.checklist_ref:
        job.status = "checklist_ready"
        job.validation_status = "not_ready"
        job.next_command = record.next_command or f"cambrian bridge checklist-show {Path(record.checklist_ref).stem}"
    elif record.status == "materialized":
        job.status = "materialized"
        job.validation_status = "not_ready"
        job.next_command = record.next_command or f"cambrian pack job-show {job.job_id}"
    else:
        job.status = "blocked"
        job.validation_status = "blocked"
        job.next_command = f"cambrian pack job-show {job.job_id}"
    job.next_actions = PackJobNextBuilder().build(root, job)
    _prefer_ai_company_job_commands(job)
    if job.linked_session_ref:
        _enrich_session_metrics(root, job)
    event_ref = _record_job_usage(root, job, surface_kind=surface_kind)
    if event_ref:
        job.usage_event_ref = event_ref
    saved_path = _save_job(root, job, job_path)
    return PackJobReplyResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        job_id=job.job_id,
        job_ref=_relative(saved_path, root),
        pack_id=job.pack_id,
        reply_kind=job.reply_kind,
        bridge_reply_ref=job.linked_bridge_reply_ref,
        bridge_review_ref=job.linked_bridge_review_ref,
        bridge_handoff_ref=job.linked_bridge_handoff_ref,
        materialization_ref=job.linked_materialization_ref,
        context_hint_ref=job.linked_context_hint_ref,
        checklist_ref=job.linked_checklist_ref,
        patch_intent_ref=job.linked_patch_intent_ref,
        session_ref=job.linked_session_ref,
        status=job.status,
        next_command=job.next_command,
        next_actions=list(job.next_actions),
        reply_contract_status=_reply_contract_status(record, job),
        reply_file_ref=record.reply_ref,
        request_packet_ref=job.linked_bridge_packet_ref,
        patch_candidate_accepted=bool(record.response_kind == "patch_candidate" and record.patch_intent_ref),
        patch_applied=False,
        source_code_modified=False,
        ai_provider_called=False,
        warnings=list(job.warnings),
        errors=list(job.errors),
    )


def _validation_blockers(job: PackJob) -> list[str]:
    blockers: list[str] = []
    if job.status not in {"validation_ready"}:
        blockers.append("pack job is not validation-ready")
    if job.reply_kind != "patch_candidate":
        blockers.append("no patch candidate reply has been routed yet")
    if not job.linked_session_id and not job.linked_session_ref:
        blockers.append("linked do session is missing")
    if not job.linked_patch_intent_ref:
        blockers.append("patch intent handoff is missing")
    return _dedupe(blockers)


def _reply_contract_status(record: BridgeFastPathRecord, job: PackJob) -> str:
    if record.status in {"blocked", "failed"} or job.status == "blocked":
        return "blocked"
    if record.response_kind == "patch_candidate" and record.patch_intent_ref:
        return "accepted_patch_candidate"
    if record.response_kind in {"analysis", "plan", "review"}:
        return f"accepted_{record.response_kind}"
    return "accepted"


def _prefer_ai_company_job_commands(job: PackJob) -> None:
    if not (job.pack_kind == "custom_harness" or job.pack_id.startswith("custom-")):
        return
    if job.next_command:
        job.next_command = _to_ai_company_job_command(job.next_command)
    job.next_actions = [_to_ai_company_job_command(action) for action in job.next_actions]


def _to_ai_company_job_command(command: str) -> str:
    text = str(command or "")
    replacements = {
        "cambrian pack job-validate ": "cambrian job validate ",
        "cambrian pack job-ingest ": "cambrian job ingest ",
        "cambrian pack job-paste ": "cambrian job paste ",
    }
    for old, new in replacements.items():
        if text.startswith(old):
            return text.replace(old, new, 1)
    return text


def _validate_typescript_jest_job(root: Path, job: PackJob, job_path: Path, job_file_ref: str) -> PackJobValidationResult:
    blockers = _validation_blockers(job)
    test_command = _typescript_jest_test_command(root)
    if blockers:
        job.validation_status = "not_ready"
        job.status = "blocked"
        job.errors = _dedupe([*job.errors, *blockers])
        job.next_command = f"cambrian job ingest {job.job_id} ai_reply_patch_candidate.yaml"
        job.next_actions = [
            f"cambrian job ingest {job.job_id} ai_reply_patch_candidate.yaml",
            f"cambrian job validate {job.job_id}",
        ]
        _save_job(root, job, job_path)
        return _validation_result(root, job, job_file_ref, "not_ready", blockers)

    job.validation_status = "not_ready"
    job.status = "blocked"
    job.outcome_snapshot = {
        "validation_lane": "typescript + jest",
        "pytest_invoked": False,
        "test_command": test_command,
        "manual_validation_required": True,
    }
    if test_command:
        message = (
            "Jest validation lane selected. Automatic Jest execution is not enabled in this RC; "
            f"run `{test_command}` and record the result."
        )
        job.warnings = _dedupe([*job.warnings, message])
        job.next_command = test_command
        job.next_actions = [test_command, f"cambrian pack job-show {job.job_id}"]
        _save_job(root, job, job_path)
        return _validation_result(root, job, job_file_ref, "not_ready", [message])

    message = "Jest validation lane selected, but no package.json Jest test command was found."
    job.errors = _dedupe([*job.errors, message])
    job.next_command = f"cambrian pack job-show {job.job_id}"
    job.next_actions = [
        "Add or expose a Jest test command such as `npm test` or `npx jest`.",
        f"cambrian pack job-show {job.job_id}",
    ]
    _save_job(root, job, job_path)
    return _validation_result(root, job, job_file_ref, "not_ready", [message])


def _validate_custom_harness_job(root: Path, job: PackJob, job_path: Path, job_file_ref: str) -> PackJobValidationResult:
    blockers = _validation_blockers(job)
    try:
        from engine.project_custom_harness import load_custom_validation

        validation = load_custom_validation(root)
    except (FileNotFoundError, ValueError):
        validation = {}
    test_commands = validation.get("test_commands", []) if isinstance(validation.get("test_commands"), list) else []
    if blockers:
        job.validation_status = "not_ready"
        job.status = "blocked"
        job.errors = _dedupe([*job.errors, *blockers])
        job.next_command = f"cambrian job ingest {job.job_id} ai_reply_patch_candidate.yaml"
        job.next_actions = [
            f"cambrian job ingest {job.job_id} ai_reply_patch_candidate.yaml",
            f"cambrian job validate {job.job_id}",
        ]
        _save_job(root, job, job_path)
        return _validation_result(root, job, job_file_ref, "not_ready", blockers)

    job.validation_status = "not_ready"
    job.status = "blocked"
    job.outcome_snapshot = {
        "validation_lane": "custom harness",
        "auto_apply": False,
        "test_commands": test_commands,
        "manual_validation_required": True,
    }
    message = "Custom harness validation requires manual command execution in this RC."
    if test_commands:
        message = f"Run validation command manually: {test_commands[0]}"
        job.next_command = str(test_commands[0])
        job.next_actions = [str(command) for command in test_commands]
    else:
        job.next_command = f"cambrian job validate {job.job_id}"
        job.next_actions = [f"cambrian job validate {job.job_id}"]
    job.warnings = _dedupe([*job.warnings, message])
    _save_job(root, job, job_path)
    return _validation_result(root, job, job_file_ref, "not_ready", [message])


def _typescript_jest_test_command(root: Path) -> str | None:
    for package_json in sorted(root.rglob("package.json")):
        try:
            rel_parts = package_json.relative_to(root).parts
        except ValueError:
            continue
        if any(part in {".cambrian", "node_modules", "dist", "build"} for part in rel_parts):
            continue
        try:
            text = package_json.read_text(encoding="utf-8", errors="ignore")
            payload = yaml.safe_load(text)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("package.json read skipped for Jest validation lane: %s (%s)", package_json, exc)
            continue
        if not isinstance(payload, dict):
            continue
        scripts = payload.get("scripts") if isinstance(payload.get("scripts"), dict) else {}
        test_script = str(scripts.get("test") or "").strip().lower()
        if "jest" not in text.lower() and "jest" not in test_script:
            continue
        parent = package_json.parent
        try:
            rel_parent = parent.relative_to(root)
        except ValueError:
            rel_parent = Path(".")
        rel_text = str(rel_parent).replace("\\", "/")
        if test_script:
            return "npm test" if rel_text == "." else f"npm test --prefix {rel_text}"
        return "npx jest" if rel_text == "." else f"npx jest {rel_text}"
    return None


def _attach_session_to_job(job: PackJob, session: DoSession) -> None:
    job.linked_session_id = session.session_id
    job.linked_session_ref = session.artifacts.get("session_path") or session.artifact_path


def _proposal_ref(session: DoSession) -> str | None:
    value = session.artifacts.get("patch_proposal_path") if isinstance(session.artifacts, dict) else None
    return str(value) if value else None


def _outcome_snapshot(session: DoSession) -> dict[str, Any]:
    metrics = session.metrics_context if isinstance(session.metrics_context, dict) else {}
    results = metrics.get("results") if isinstance(metrics.get("results"), dict) else {}
    human = metrics.get("human_interventions") if isinstance(metrics.get("human_interventions"), dict) else {}
    validated = _bool_or_none(results.get("validated_proposal"))
    if validated is None:
        validated = session.current_stage == "patch_proposal_validated"
    adopted = _bool_or_none(results.get("adoption_succeeded"))
    apply_passed = _bool_or_none(results.get("apply_tests_passed"))
    human_intervention = any(
        _bool_or_none(value) is True
        for key, value in human.items()
        if str(key) != "bridge_paste_fastpath"
    )
    validation_autonomy = True if validated and not human_intervention else False if validated else None
    return {
        "validated_proposal": validated,
        "adoption_succeeded": adopted,
        "regression_free_apply": True if adopted and apply_passed is True else False if adopted and apply_passed is False else None,
        "human_intervention": human_intervention if validated is not None else None,
        "validation_autonomy": validation_autonomy,
        "duration_seconds": _duration_seconds(metrics),
    }


def _duration_seconds(metrics: dict[str, Any]) -> float | None:
    milestones = metrics.get("milestones") if isinstance(metrics.get("milestones"), dict) else {}
    start = _parse_time(milestones.get("request_started_at"))
    end = _parse_time(milestones.get("proposal_validated_at"))
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    raw = str(value)
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _enrich_session_metrics(root: Path, job: PackJob) -> None:
    session_ref = job.linked_session_ref or job.linked_session_id
    if not session_ref:
        return
    store = DoSessionStore()
    try:
        session_path = store.resolve_path(root, job.linked_session_id or session_ref)
        session = store.load(session_path)
    except Exception as exc:
        logger.warning("pack job session metrics update failed: %s", exc)
        return
    metrics = session.metrics_context if isinstance(session.metrics_context, dict) else {}
    metrics.update(
        {
            "active_pack_id": job.pack_id,
            "active_pack_ref": job.pack_ref,
            "active_pack_namespace": job.namespace,
            "active_pack_version": job.version,
            "active_pack_lane": job.lane_id,
            "pack_job_id": job.job_id,
            "pack_job_ref": _relative(default_pack_job_path(root, job), root),
            "pack_reply_kind": job.reply_kind,
        }
    )
    reused = metrics.setdefault("reused_context", {})
    if isinstance(reused, dict):
        reused["pack"] = True
        reused["bridge"] = True
    human = metrics.setdefault("human_interventions", {})
    if isinstance(human, dict):
        human["bridge_paste_fastpath"] = True
        human["bridge_manual_ingest"] = False
    session.metrics_context = metrics
    if isinstance(session.bridge_context, dict):
        session.bridge_context["pack_job_id"] = job.job_id
        session.bridge_context["pack_job_ref"] = _relative(default_pack_job_path(root, job), root)
    store.save(root, session)


def _normalize_returned_session_metrics(root: Path, job: PackJob, session: DoSession) -> None:
    metrics = session.metrics_context if isinstance(session.metrics_context, dict) else {}
    metrics.update(
        {
            "active_pack_id": job.pack_id,
            "active_pack_ref": job.pack_ref,
            "active_pack_namespace": job.namespace,
            "active_pack_version": job.version,
            "active_pack_lane": job.lane_id,
            "pack_job_id": job.job_id,
            "pack_job_ref": _relative(default_pack_job_path(root, job), root),
            "pack_reply_kind": job.reply_kind,
        }
    )
    reused = metrics.setdefault("reused_context", {})
    if isinstance(reused, dict):
        reused["pack"] = True
        reused["bridge"] = True
    human = metrics.setdefault("human_interventions", {})
    if isinstance(human, dict):
        human["bridge_paste_fastpath"] = True
        human["bridge_manual_ingest"] = False
    session.metrics_context = metrics
    DoSessionStore().save(root, session)


def _record_job_usage(root: Path, job: PackJob, *, surface_kind: str) -> str | None:
    try:
        context = context_for_installed_pack(root, job.pack_id)
    except Exception as exc:
        logger.warning("pack job usage context load failed: %s", exc)
        return None
    event_path = safe_record_pack_usage_from_context(
        root,
        context,
        event_kind="used",
        surface_kind=surface_kind,
        request=job.request,
        request_class=job.request_class,
        linked_session_id=job.linked_session_id,
        linked_session_ref=job.linked_session_ref,
        linked_request_ref=_relative(default_pack_job_path(root, job), root),
        linked_bridge_packet_ref=job.linked_bridge_packet_ref,
        linked_bridge_reply_ref=job.linked_bridge_reply_ref,
        summary=f"pack job {surface_kind}: {job.job_id}",
    )
    return _relative(event_path, root) if event_path is not None else None


def _save_job(root: Path, job: PackJob, job_path: Path) -> Path:
    job.updated_at = _now()
    return PackJobStore().save(job, default_pack_job_path(root, job) if job_path.name == "latest.yaml" else job_path)


def _validation_result(
    root: Path,
    job: PackJob,
    job_ref: str,
    status: str,
    warnings: list[str],
) -> PackJobValidationResult:
    generated_at = _now()
    merged_warnings = _dedupe([*warnings, *job.warnings])
    errors = list(job.errors)
    next_actions = PackJobNextBuilder().build(root, job)
    next_actions = _validation_next_actions(job, next_actions)
    validation_commands = _validation_commands(job, next_actions)
    manual_required = _manual_validation_required(job, status, validation_commands)
    contract_status = _validation_contract_status(status, manual_required, errors)
    trust_gate_status = _trust_gate_status(status, manual_required, errors)
    checked_artifacts = _checked_validation_artifacts(root, job, job_ref)
    unchecked_items = _unchecked_validation_items(status, manual_required, validation_commands, errors)
    evidence_ref = _save_validation_evidence(
        root,
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "job_id": job.job_id,
            "job_ref": job_ref,
            "pack_id": job.pack_id,
            "validation_status": status,
            "validation_contract_status": contract_status,
            "trust_gate_status": trust_gate_status,
            "checked_artifacts": checked_artifacts,
            "unchecked_items": unchecked_items,
            "validation_commands": validation_commands,
            "manual_validation_required": manual_required,
            "request_packet_ref": job.linked_bridge_packet_ref,
            "reply_file_ref": job.linked_bridge_reply_ref,
            "patch_intent_ref": job.linked_patch_intent_ref,
            "proposal_ref": job.linked_proposal_ref,
            "outcome_snapshot": dict(job.outcome_snapshot),
            "warnings": merged_warnings,
            "errors": errors,
            "patch_applied": False,
            "source_code_modified": False,
            "ai_provider_called": False,
        },
    )
    return PackJobValidationResult(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        job_id=job.job_id,
        job_ref=job_ref,
        pack_id=job.pack_id,
        session_id=job.linked_session_id,
        session_ref=job.linked_session_ref,
        proposal_ref=job.linked_proposal_ref,
        validation_status=status,
        outcome_snapshot=dict(job.outcome_snapshot),
        next_command=job.next_command,
        next_actions=next_actions,
        validation_contract_status=contract_status,
        trust_gate_status=trust_gate_status,
        checked_artifacts=checked_artifacts,
        unchecked_items=unchecked_items,
        validation_commands=validation_commands,
        manual_validation_required=manual_required,
        evidence_ref=evidence_ref,
        request_packet_ref=job.linked_bridge_packet_ref,
        reply_file_ref=job.linked_bridge_reply_ref,
        patch_intent_ref=job.linked_patch_intent_ref,
        patch_applied=False,
        source_code_modified=False,
        ai_provider_called=False,
        warnings=merged_warnings,
        errors=errors,
    )


def _validation_next_actions(job: PackJob, next_actions: list[str]) -> list[str]:
    actions = list(next_actions)
    if _manual_validation_required(job, job.validation_status or "not_ready", _validation_commands(job, actions)):
        actions.append(f'cambrian job complete {job.job_id} --outcome partial --notes "manual validation result"')
    return _dedupe(actions)


def _validation_commands(job: PackJob, next_actions: list[str]) -> list[str]:
    snapshot = job.outcome_snapshot if isinstance(job.outcome_snapshot, dict) else {}
    commands: list[str] = []
    commands.extend(_as_list(snapshot.get("test_commands")))
    commands.extend(_as_list(snapshot.get("test_command")))
    commands.extend(_as_list(snapshot.get("validation_commands")))
    for action in next_actions:
        text = str(action or "").strip()
        if text.startswith(("npm ", "npx ", "python ", "python -m ", "pytest", "uv ", "pnpm ", "yarn ")):
            commands.append(text)
    return _dedupe(commands)


def _manual_validation_required(job: PackJob, status: str, validation_commands: list[str]) -> bool:
    snapshot = job.outcome_snapshot if isinstance(job.outcome_snapshot, dict) else {}
    if _bool_or_none(snapshot.get("manual_validation_required")) is True:
        return True
    return status == "not_ready" and bool(validation_commands) and not job.errors


def _validation_contract_status(status: str, manual_required: bool, errors: list[str]) -> str:
    if status == "validated":
        return "validated"
    if manual_required:
        return "manual_validation_required"
    if errors or status in {"blocked", "failed"}:
        return "blocked"
    return "not_ready"


def _trust_gate_status(status: str, manual_required: bool, errors: list[str]) -> str:
    if status == "validated":
        return "passed"
    if manual_required:
        return "manual_required"
    if errors or status in {"blocked", "failed", "not_ready"}:
        return "blocked"
    return "unknown"


def _checked_validation_artifacts(root: Path, job: PackJob, job_ref: str) -> list[str]:
    source_reply_ref = _source_reply_ref_from_bridge_reply(root, job)
    return _dedupe(
        [
            job_ref,
            job.linked_bridge_packet_ref or "",
            job.linked_bridge_reply_ref or "",
            source_reply_ref or "",
            job.linked_bridge_review_ref or "",
            job.linked_bridge_handoff_ref or "",
            job.linked_patch_intent_ref or "",
            job.linked_session_ref or "",
            job.linked_proposal_ref or "",
        ]
    )


def _source_reply_ref_from_bridge_reply(root: Path, job: PackJob) -> str | None:
    if not job.linked_bridge_reply_ref:
        return None
    reply_path = Path(job.linked_bridge_reply_ref)
    if not reply_path.is_absolute():
        reply_path = Path(root).resolve() / reply_path
    payload = _load_yaml(reply_path)
    source = payload.get("source_reply_path")
    return str(source) if source else None


def _unchecked_validation_items(
    status: str,
    manual_required: bool,
    validation_commands: list[str],
    errors: list[str],
) -> list[str]:
    items: list[str] = []
    if manual_required:
        items.append("Cambrian did not execute validation commands automatically")
    if validation_commands and status != "validated":
        items.append("Human must run validation commands and record the outcome")
    if status != "validated":
        items.append("Patch proposal was not applied to source code")
    if errors:
        items.extend(errors)
    return _dedupe(items)


def _save_validation_evidence(root: Path, payload: dict[str, Any]) -> str:
    evidence_dir = Path(root).resolve() / ".cambrian" / "evidence" / "validation"
    evidence_path = evidence_dir / f"{_slug(str(payload.get('job_id') or 'job'), 'job')}.yaml"
    _save_yaml(evidence_path, payload)
    return _relative(evidence_path, root)


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "passed", "pass", "ok"}:
        return True
    if text in {"0", "false", "no", "failed", "fail", "blocked"}:
        return False
    return None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in _as_list(items):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("pack job reply artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}
