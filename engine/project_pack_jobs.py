"""Pack-first job start와 worker handoff artifact."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_bridge import (
    ProjectBridgeBuilder,
    ProjectBridgeStore,
    default_bridge_packet_path,
    render_bridge_packet,
)
from engine.project_pack_activation import (
    ActivePackContext,
    context_for_installed_pack,
    current_active_pack,
    pack_context_bridge_payload,
)
from engine.project_pack_install import SCHEMA_VERSION, _as_list, _load_yaml, _now, _relative, _save_yaml, _slug, _stamp
from engine.project_pack_readiness import PackReadinessBuilder, PackReadinessReport, save_pack_readiness_report
from engine.project_pack_setup import latest_pack_setup_plan
from engine.project_pack_usage import safe_record_pack_usage_from_context

logger = logging.getLogger(__name__)


@dataclass
class PackJob:
    """Pack에 맡긴 단일 first-job handoff 기록."""

    schema_version: str
    job_id: str
    created_at: str
    updated_at: str | None
    pack_ref: str
    pack_id: str
    pack_name: str | None
    pack_kind: str | None
    namespace: str | None
    version: str | None
    request: str
    request_class: str | None
    lane_id: str | None
    lane_label: str | None
    readiness_status: str | None
    readiness_ref: str | None
    setup_plan_ref: str | None
    entry_mode: str
    linked_bridge_packet_ref: str | None
    linked_session_id: str | None
    linked_session_ref: str | None
    linked_request_ref: str | None
    active_team: str | None
    active_template: str | None
    active_workset: str | None
    status: str
    next_command: str | None
    next_actions: list[str]
    usage_event_ref: str | None
    linked_bridge_reply_ref: str | None = None
    linked_bridge_review_ref: str | None = None
    linked_bridge_handoff_ref: str | None = None
    linked_materialization_ref: str | None = None
    linked_context_hint_ref: str | None = None
    linked_checklist_ref: str | None = None
    linked_patch_intent_ref: str | None = None
    linked_proposal_ref: str | None = None
    reply_kind: str | None = None
    validation_status: str | None = None
    outcome_snapshot: dict[str, Any] = field(default_factory=dict)
    completed_at: str | None = None
    linked_apply_record_ref: str | None = None
    linked_adoption_record_ref: str | None = None
    apply_status: str | None = None
    adoption_status: str | None = None
    final_status: str | None = None
    final_outcome_snapshot: dict[str, Any] = field(default_factory=dict)
    closed_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        return asdict(self)


@dataclass
class PackJobStartResult:
    """pack start 결과."""

    schema_version: str
    generated_at: str
    job: PackJob
    human_summary: list[str]
    packet_preview: str | None
    next_actions: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        payload = asdict(self)
        payload["job"] = self.job.to_dict()
        return payload


def default_pack_jobs_dir(project_root: Path) -> Path:
    """pack job 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "jobs"


def default_pack_job_path(project_root: Path, job: PackJob) -> Path:
    """pack job 기본 저장 경로를 반환한다."""
    return default_pack_jobs_dir(project_root) / f"{_slug(job.job_id, 'job')}.yaml"


def latest_pack_job_path(project_root: Path) -> Path:
    """latest pack job 경로를 반환한다."""
    return default_pack_jobs_dir(project_root) / "latest.yaml"


class PackJobStore:
    """Pack job 저장소."""

    def save(self, job: PackJob, path: Path) -> Path:
        """job을 저장하고 latest pointer를 갱신한다."""
        target = Path(path).resolve()
        project_root = _project_root_from_job_path(target)
        _save_yaml(target, job.to_dict())
        if target.name != "latest.yaml":
            _save_yaml(latest_pack_job_path(project_root), job.to_dict())
        return target

    def load(self, path: Path) -> PackJob:
        """job을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack job not found: {path}")
        return _job_from_dict(payload)

    def list(self, jobs_dir: Path, pack_id: str | None = None) -> list[PackJob]:
        """저장된 pack job 목록을 반환한다."""
        target = Path(jobs_dir).resolve()
        if not target.exists():
            return []
        jobs: list[PackJob] = []
        for path in sorted(target.glob("job_*.yaml"), reverse=True):
            try:
                job = self.load(path)
            except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
                logger.warning("pack job load skipped: %s (%s)", path, exc)
                continue
            if pack_id and not _pack_matches(job, pack_id):
                continue
            jobs.append(job)
        return jobs


class PackJobNextBuilder:
    """Pack job의 다음 명령을 계산한다."""

    def build(self, project_root: Path, job: PackJob) -> list[str]:
        """job 상태 기준 next action 목록을 반환한다."""
        if job.adoption_status in {"accepted", "rejected", "skipped"} or job.final_status in {"adopted", "rejected", "closed"}:
            return [
                job.next_command or f"cambrian pack proof {job.pack_id}",
                f"cambrian pack job-show {job.job_id}",
            ]
        if job.status == "applied" or job.apply_status == "applied" or job.final_status == "applied":
            return [
                job.next_command or f'cambrian pack job-adopt {job.job_id} --accepted --reason "validated and applied cleanly"',
                f"cambrian pack job-show {job.job_id}",
            ]
        if job.apply_status == "previewed":
            return [
                job.next_command or f"cambrian pack job-apply {job.job_id} --confirm",
                f"cambrian pack job-show {job.job_id}",
            ]
        if job.status == "validated" or job.validation_status == "validated" or job.final_status == "validated":
            return [
                f"cambrian pack job-apply {job.job_id}",
                f"cambrian pack job-show {job.job_id}",
            ]
        if job.status == "waiting_for_ai_reply" and job.linked_bridge_packet_ref:
            return [
                job.next_command or f"cambrian pack job-paste {job.job_id}",
                f"cambrian bridge paste --packet {job.linked_bridge_packet_ref}",
                f"cambrian pack job-show {job.job_id}",
            ]
        if job.status == "validation_ready":
            return [
                job.next_command or f"cambrian pack job-validate {job.job_id}",
                f"cambrian pack job-show {job.job_id}",
            ]
        if job.status == "checklist_ready":
            actions = [job.next_command] if job.next_command else []
            if job.linked_checklist_ref:
                actions.append(f"cambrian bridge checklist-show {Path(job.linked_checklist_ref).stem}")
            actions.append(f"cambrian pack job-show {job.job_id}")
            return _dedupe(actions)
        if job.status == "materialized":
            actions = [job.next_command] if job.next_command else []
            if job.linked_materialization_ref:
                actions.append(f"cambrian bridge materialize-show {Path(job.linked_materialization_ref).stem}")
            actions.append(f"cambrian pack job-show {job.job_id}")
            return _dedupe(actions)
        if job.status == "blocked":
            actions = [*job.next_actions]
            if not actions and job.pack_id:
                actions.append(f"cambrian pack setup {job.pack_id}")
            return actions
        return list(job.next_actions)


class PackJobStarter:
    """Pack-first job handoff를 시작한다."""

    def start(
        self,
        project_root: Path,
        request: str,
        pack_ref: str | None = None,
        mode: str = "bridge_prepare",
    ) -> PackJobStartResult:
        """active 또는 명시 pack으로 first-job handoff를 만든다."""
        root = Path(project_root).resolve()
        request_text = str(request or "").strip()
        if not request_text:
            raise ValueError("request is required")
        context = _resolve_context(root, pack_ref)
        readiness = PackReadinessBuilder().build(root, context.pack_id)
        readiness_ref = save_pack_readiness_report(root, readiness)
        setup_plan = latest_pack_setup_plan(root, context.pack_id)
        setup_ref = setup_plan.saved_ref if setup_plan is not None else None
        if readiness.readiness_status in {"blocked", "unsupported"}:
            job = _blocked_job(root, context, request_text, readiness, setup_ref, mode)
            return PackJobStartResult(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                job=job,
                human_summary=[f"pack start blocked: {readiness.readiness_status}"],
                packet_preview=None,
                next_actions=list(job.next_actions),
                warnings=list(readiness.warnings),
                errors=list(readiness.errors),
            )
        if mode not in {"bridge", "bridge_prepare"}:
            job = _blocked_job(root, context, request_text, readiness, setup_ref, mode)
            job.status = "blocked"
            job.errors.append(f"pack start mode is not implemented in V1: {mode}")
            job.next_actions = ["cambrian pack start --mode bridge \"<request>\""]
            return PackJobStartResult(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                job=job,
                human_summary=[f"mode blocked: {mode}"],
                packet_preview=None,
                next_actions=list(job.next_actions),
                warnings=list(readiness.warnings),
                errors=list(job.errors),
            )
        return self._start_bridge(root, context, readiness, readiness_ref, setup_ref, request_text)

    def _start_bridge(
        self,
        root: Path,
        context: ActivePackContext,
        readiness: PackReadinessReport,
        readiness_ref: str,
        setup_ref: str | None,
        request: str,
    ) -> PackJobStartResult:
        job_id = f"job-{_slug(context.pack_id, 'pack')}-{_stamp()}"
        job_ref_hint = f".cambrian/packs/jobs/{job_id}.yaml"
        bridge_context = pack_context_bridge_payload(context)
        bridge_context["pack_job_id"] = job_id
        bridge_context["pack_job_ref"] = job_ref_hint
        packet = ProjectBridgeBuilder().build_packet(
            root,
            request,
            active_pack_context_override=bridge_context,
        )
        packet_path = ProjectBridgeStore().save_packet(packet, default_bridge_packet_path(root, packet))
        packet_ref = _relative(packet_path, root)
        next_command = f"cambrian pack job-paste {job_id}"
        warnings = _job_warnings(readiness, context, request)
        job = PackJob(
            schema_version=SCHEMA_VERSION,
            job_id=job_id,
            created_at=_now(),
            updated_at=None,
            pack_ref=context.pack_ref,
            pack_id=context.pack_id,
            pack_name=context.pack_name,
            pack_kind=context.pack_kind,
            namespace=context.namespace,
            version=context.version,
            request=request,
            request_class=packet.request_intent,
            lane_id=context.lane_id,
            lane_label=context.lane_label,
            readiness_status=readiness.readiness_status,
            readiness_ref=readiness_ref,
            setup_plan_ref=setup_ref,
            entry_mode="bridge_prepare",
            linked_bridge_packet_ref=packet_ref,
            linked_session_id=None,
            linked_session_ref=None,
            linked_request_ref=None,
            active_team=context.default_team,
            active_template=context.default_template,
            active_workset=context.default_workset,
            status="waiting_for_ai_reply",
            next_command=next_command,
            next_actions=[
                "Paste the packet into your AI.",
                next_command,
            ],
            usage_event_ref=None,
            outcome_snapshot={
                "harness_id": context.pack_id,
                "selected_agents": list(context.workers),
                "selected_skills": [],
                "dispatch_reason": "Selected from installed pack context.",
                "change_policy": "proposal_only",
                "contract_template_kind": context.contract_template_kind,
                "validation_criteria": list(context.validation_criteria),
                "forbidden_actions": list(context.forbidden_actions),
                "approval_required_actions": list(context.approval_required_actions),
                "validation_commands": [],
            },
            warnings=warnings,
            errors=[],
        )
        job_path = PackJobStore().save(job, default_pack_job_path(root, job))
        job_ref = _relative(job_path, root)
        event_ref = safe_record_pack_usage_from_context(
            root,
            context,
            event_kind="used",
            surface_kind="pack_start",
            request=request,
            request_class=packet.request_intent,
            linked_bridge_packet_ref=packet_ref,
            linked_request_ref=job_ref,
            summary=f"pack job started: {job_id}",
        )
        job.usage_event_ref = _relative(event_ref, root) if event_ref is not None else None
        proof_paths = _refresh_local_proof(root, context.pack_id)
        if proof_paths:
            job.outcome_snapshot["proof_ref"] = proof_paths.get("yaml")
            job.outcome_snapshot["proof_markdown_ref"] = proof_paths.get("md")
        job.next_actions.append(f"cambrian pack job-show {job.job_id}")
        PackJobStore().save(job, job_path)
        return PackJobStartResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            job=job,
            human_summary=[
                f"pack job started for {context.pack_id}",
                "AI provider was not called.",
                "Source code was not modified.",
            ],
            packet_preview=render_bridge_packet(packet),
            next_actions=PackJobNextBuilder().build(root, job),
            warnings=warnings,
            errors=[],
        )


def resolve_pack_job_path(project_root: Path, ref: str) -> Path:
    """job id 또는 path를 실제 job 파일로 해석한다."""
    root = Path(project_root).resolve()
    raw = str(ref).strip()
    direct = Path(raw)
    if direct.exists():
        return direct.resolve()
    if not direct.is_absolute() and (root / direct).exists():
        return (root / direct).resolve()
    if raw == "latest":
        latest = latest_pack_job_path(root)
        if latest.exists():
            return latest.resolve()
    jobs_dir = default_pack_jobs_dir(root)
    if jobs_dir.exists():
        for path in sorted(jobs_dir.glob("*.yaml"), reverse=True):
            try:
                job = PackJobStore().load(path)
            except (FileNotFoundError, ValueError, yaml.YAMLError):
                continue
            if raw in {job.job_id, path.name, path.stem}:
                return path.resolve()
    raise FileNotFoundError(f"pack job not found: {ref}")


def render_pack_job_started(result: PackJobStartResult) -> str:
    """pack start 결과를 렌더링한다."""
    job = result.job
    lines = [
        "Pack Job Started" if job.status != "blocked" else "Pack Job Blocked",
        "==================================================",
        "",
        "Pack:",
        f"  {job.pack_ref}",
        "",
        "Request:",
        f"  {job.request}",
        "",
        "Readiness:",
        f"  {job.readiness_status or 'unknown'}",
    ]
    if job.linked_bridge_packet_ref:
        lines.extend(["", "Created:", f"  bridge packet {job.linked_bridge_packet_ref}"])
    if result.packet_preview:
        lines.extend(["", "Packet preview:", result.packet_preview])
    if result.next_actions:
        lines.extend(["", "Next:"])
        for index, action in enumerate(result.next_actions, start=1):
            lines.append(f"  {index}. {action}")
    lines.extend(["", "Job:", f"  {job.job_id}"])
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    return "\n".join(lines)


def render_pack_jobs(jobs: list[PackJob], *, limit: int = 20) -> str:
    """pack jobs 목록을 렌더링한다."""
    lines = [
        "Pack Jobs",
        "==================================================",
        "",
        "Recent:",
    ]
    selected = jobs[:limit]
    if not selected:
        lines.append("  none")
        return "\n".join(lines)
    for index, job in enumerate(selected, start=1):
        lines.append(f"  {index}. {job.job_id}")
        lines.append(f"     pack   : {job.pack_id}")
        lines.append(f"     status : {job.status}")
        lines.append(f"     request: {_shorten(job.request)}")
        if job.next_command:
            lines.append(f"     next   : {job.next_command}")
    return "\n".join(lines)


def render_pack_job(job: PackJob) -> str:
    """pack job 상세를 렌더링한다."""
    lines = [
        "Pack Job",
        "==================================================",
        "",
        "Job:",
        f"  {job.job_id}",
        "",
        "Pack:",
        f"  {job.pack_ref}",
        "",
        "Request:",
        f"  {job.request}",
        "",
        "Status:",
        f"  {job.status}",
        "",
        "Readiness:",
        f"  {job.readiness_status or 'unknown'}",
    ]
    if job.linked_bridge_packet_ref:
        lines.extend(["", "Bridge packet:", f"  {job.linked_bridge_packet_ref}"])
    if job.reply_kind:
        lines.extend(["", "Reply kind:", f"  {job.reply_kind}"])
    bridge_refs = [
        ("reply", job.linked_bridge_reply_ref),
        ("review", job.linked_bridge_review_ref),
        ("handoff", job.linked_bridge_handoff_ref),
        ("materialization", job.linked_materialization_ref),
        ("context hint", job.linked_context_hint_ref),
        ("checklist", job.linked_checklist_ref),
    ]
    present_bridge_refs = [(label, ref) for label, ref in bridge_refs if ref]
    if present_bridge_refs:
        lines.extend(["", "Bridge refs:"])
        lines.extend([f"  {label:<15}: {ref}" for label, ref in present_bridge_refs])
    if job.linked_patch_intent_ref:
        lines.extend(["", "Patch intent:", f"  {job.linked_patch_intent_ref}"])
    if job.linked_session_ref or job.linked_session_id:
        lines.extend(["", "Session:", f"  {job.linked_session_id or job.linked_session_ref}"])
        if job.linked_session_ref:
            lines.append(f"  ref: {job.linked_session_ref}")
    if job.linked_proposal_ref:
        lines.extend(["", "Proposal:", f"  {job.linked_proposal_ref}"])
    if job.validation_status:
        lines.extend(["", "Validation:", f"  {job.validation_status}"])
    if job.apply_status or job.linked_apply_record_ref:
        lines.extend(["", "Apply:"])
        if job.apply_status:
            lines.append(f"  status: {job.apply_status}")
        if job.linked_apply_record_ref:
            lines.append(f"  ref: {job.linked_apply_record_ref}")
    if job.adoption_status or job.linked_adoption_record_ref:
        lines.extend(["", "Adoption:"])
        if job.adoption_status:
            lines.append(f"  status: {job.adoption_status}")
        if job.linked_adoption_record_ref:
            lines.append(f"  ref: {job.linked_adoption_record_ref}")
    if job.final_status:
        lines.extend(["", "Final status:", f"  {job.final_status}"])
    if job.outcome_snapshot:
        lines.extend(["", "Outcome snapshot:"])
        for key in [
            "validated_proposal",
            "adoption_succeeded",
            "regression_free_apply",
            "human_intervention",
            "validation_autonomy",
            "duration_seconds",
        ]:
            if key in job.outcome_snapshot:
                lines.append(f"  {key}: {job.outcome_snapshot.get(key)}")
        validation_criteria = _as_list(job.outcome_snapshot.get("validation_criteria"))
        validation_criteria_status = str(job.outcome_snapshot.get("validation_criteria_status") or "").strip()
        manual_contract_review = (
            dict(job.outcome_snapshot.get("manual_contract_review"))
            if isinstance(job.outcome_snapshot.get("manual_contract_review"), dict)
            else {}
        )
        if validation_criteria or validation_criteria_status or manual_contract_review:
            lines.extend(["", "Contract criteria:"])
            lines.append(f"  status: {validation_criteria_status or 'pending_review'}")
            lines.append(f"  count: {len(validation_criteria)}")
            if manual_contract_review:
                reviewer = str(manual_contract_review.get("reviewer") or "").strip()
                notes = str(manual_contract_review.get("notes") or "").strip()
                if reviewer:
                    lines.append(f"  reviewer: {reviewer}")
                if notes:
                    lines.append(f"  notes: {notes}")
    if job.final_outcome_snapshot:
        lines.extend(["", "Final outcome snapshot:"])
        for key in [
            "validated_proposal",
            "applied",
            "adoption_succeeded",
            "regression_free_apply",
            "human_intervention",
            "validation_autonomy",
            "duration_seconds",
            "rejection_reason",
            "adoption_reason",
        ]:
            if key in job.final_outcome_snapshot:
                lines.append(f"  {key}: {job.final_outcome_snapshot.get(key)}")
    if job.setup_plan_ref:
        lines.extend(["", "Setup plan:", f"  {job.setup_plan_ref}"])
    if job.next_actions:
        lines.extend(["", "Next actions:"])
        lines.extend([f"  - {item}" for item in job.next_actions])
    if job.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in job.warnings])
    if job.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in job.errors])
    return "\n".join(lines)


def render_pack_job_next(job: PackJob, actions: list[str]) -> str:
    """pack job next command를 렌더링한다."""
    lines = [
        "Pack Job Next",
        "==================================================",
        "",
        "Job:",
        f"  {job.job_id}",
        "",
        "Next:",
    ]
    lines.extend([f"  {item}" for item in actions] or ["  none"])
    return "\n".join(lines)


def latest_pack_job(project_root: Path) -> PackJob | None:
    """latest pack job을 로드한다."""
    path = latest_pack_job_path(project_root)
    if not path.exists():
        return None
    try:
        return PackJobStore().load(path)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        logger.warning("latest pack job load failed: %s", exc)
        return None


def render_status_latest_pack_job(job: PackJob | None) -> str:
    """status 화면에 붙일 latest pack job compact summary를 만든다."""
    if job is None:
        return ""
    lines = [
        "",
        "Latest pack job:",
        f"  {job.pack_id} -> {job.status}",
    ]
    if job.next_command:
        lines.append(f"  next: {job.next_command}")
    elif job.apply_status == "applied":
        lines.append(f"  next: cambrian pack job-adopt {job.job_id} --accepted --reason \"validated and applied cleanly\"")
    elif job.status == "validated":
        lines.append(f"  next: cambrian pack job-apply {job.job_id}")
    return "\n".join(lines)


def _resolve_context(root: Path, pack_ref: str | None) -> ActivePackContext:
    if pack_ref:
        return context_for_installed_pack(root, pack_ref)
    context = current_active_pack(root)
    if context is not None:
        return context
    raise KeyError(
        "No active pack is selected.\n\nUse:\n  cambrian pack recommend\n  cambrian pack activate auth-bug-core\nor:\n  cambrian pack start --pack auth-bug-core \"로그인 에러 수정해\""
    )


def _blocked_job(
    root: Path,
    context: ActivePackContext,
    request: str,
    readiness: PackReadinessReport,
    setup_ref: str | None,
    mode: str,
) -> PackJob:
    return PackJob(
        schema_version=SCHEMA_VERSION,
        job_id=f"job-{_slug(context.pack_id, 'pack')}-{_stamp()}",
        created_at=_now(),
        updated_at=None,
        pack_ref=context.pack_ref,
        pack_id=context.pack_id,
        pack_name=context.pack_name,
        pack_kind=context.pack_kind,
        namespace=context.namespace,
        version=context.version,
        request=request,
        request_class=None,
        lane_id=context.lane_id,
        lane_label=context.lane_label,
        readiness_status=readiness.readiness_status,
        readiness_ref=readiness.saved_ref,
        setup_plan_ref=setup_ref,
        entry_mode=mode,
        linked_bridge_packet_ref=None,
        linked_session_id=None,
        linked_session_ref=None,
        linked_request_ref=None,
        active_team=context.default_team,
        active_template=context.default_template,
        active_workset=context.default_workset,
        status="blocked",
        next_command=None,
        next_actions=_blocked_next_actions(root, context, readiness),
        usage_event_ref=None,
        warnings=list(readiness.warnings),
        errors=list(readiness.errors),
    )


def _blocked_next_actions(root: Path, context: ActivePackContext, readiness: PackReadinessReport) -> list[str]:
    if readiness.readiness_status == "unsupported":
        return ["cambrian pack recommend"]
    actions = list(readiness.next_actions)
    if latest_pack_setup_plan(root, context.pack_id) is not None:
        actions.insert(0, "cambrian pack setup-show latest")
    else:
        actions.insert(0, f"cambrian pack setup {context.pack_id}")
    return _dedupe(actions)


def _job_warnings(readiness: PackReadinessReport, context: ActivePackContext, request: str) -> list[str]:
    warnings = list(readiness.warnings)
    if readiness.readiness_status in {"partial", "unknown"}:
        warnings.append(f"readiness is {readiness.readiness_status}; proceed with caution")
    if context.pack_id == "auth-bug-core":
        warnings.append("This pack is strongest for narrow auth/login bug fixes, not broad refactors.")
        text = request.lower()
        if not any(token in text for token in ["auth", "login", "로그인", "username", "account"]):
            warnings.append("Request may be outside auth/login lane; validated proposal quality may be lower.")
    return _dedupe(warnings)


def _refresh_local_proof(root: Path, pack_ref: str) -> dict[str, str]:
    try:
        from engine.project_pack_proof import PackProofBuilder, save_pack_proof_card

        card = PackProofBuilder().build(root, pack_ref)
        return save_pack_proof_card(root, card, format_kind="both")
    except Exception as exc:
        logger.warning("pack job proof refresh failed: %s", exc)
        return {}


def _job_from_dict(payload: dict[str, Any]) -> PackJob:
    return PackJob(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        job_id=str(payload.get("job_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        pack_ref=str(payload.get("pack_ref") or ""),
        pack_id=str(payload.get("pack_id") or ""),
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        pack_kind=str(payload.get("pack_kind")) if payload.get("pack_kind") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        request=str(payload.get("request") or ""),
        request_class=str(payload.get("request_class")) if payload.get("request_class") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        readiness_status=str(payload.get("readiness_status")) if payload.get("readiness_status") is not None else None,
        readiness_ref=str(payload.get("readiness_ref")) if payload.get("readiness_ref") is not None else None,
        setup_plan_ref=str(payload.get("setup_plan_ref")) if payload.get("setup_plan_ref") is not None else None,
        entry_mode=str(payload.get("entry_mode") or "bridge_prepare"),
        linked_bridge_packet_ref=str(payload.get("linked_bridge_packet_ref")) if payload.get("linked_bridge_packet_ref") is not None else None,
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_session_ref=str(payload.get("linked_session_ref")) if payload.get("linked_session_ref") is not None else None,
        linked_request_ref=str(payload.get("linked_request_ref")) if payload.get("linked_request_ref") is not None else None,
        active_team=str(payload.get("active_team")) if payload.get("active_team") is not None else None,
        active_template=str(payload.get("active_template")) if payload.get("active_template") is not None else None,
        active_workset=str(payload.get("active_workset")) if payload.get("active_workset") is not None else None,
        status=str(payload.get("status") or "started"),
        next_command=str(payload.get("next_command")) if payload.get("next_command") is not None else None,
        next_actions=_as_list(payload.get("next_actions")),
        usage_event_ref=str(payload.get("usage_event_ref")) if payload.get("usage_event_ref") is not None else None,
        linked_bridge_reply_ref=str(payload.get("linked_bridge_reply_ref")) if payload.get("linked_bridge_reply_ref") is not None else None,
        linked_bridge_review_ref=str(payload.get("linked_bridge_review_ref")) if payload.get("linked_bridge_review_ref") is not None else None,
        linked_bridge_handoff_ref=str(payload.get("linked_bridge_handoff_ref")) if payload.get("linked_bridge_handoff_ref") is not None else None,
        linked_materialization_ref=str(payload.get("linked_materialization_ref")) if payload.get("linked_materialization_ref") is not None else None,
        linked_context_hint_ref=str(payload.get("linked_context_hint_ref")) if payload.get("linked_context_hint_ref") is not None else None,
        linked_checklist_ref=str(payload.get("linked_checklist_ref")) if payload.get("linked_checklist_ref") is not None else None,
        linked_patch_intent_ref=str(payload.get("linked_patch_intent_ref")) if payload.get("linked_patch_intent_ref") is not None else None,
        linked_proposal_ref=str(payload.get("linked_proposal_ref")) if payload.get("linked_proposal_ref") is not None else None,
        reply_kind=str(payload.get("reply_kind")) if payload.get("reply_kind") is not None else None,
        validation_status=str(payload.get("validation_status")) if payload.get("validation_status") is not None else None,
        outcome_snapshot=dict(payload.get("outcome_snapshot", {})) if isinstance(payload.get("outcome_snapshot"), dict) else {},
        completed_at=str(payload.get("completed_at")) if payload.get("completed_at") is not None else None,
        linked_apply_record_ref=str(payload.get("linked_apply_record_ref")) if payload.get("linked_apply_record_ref") is not None else None,
        linked_adoption_record_ref=str(payload.get("linked_adoption_record_ref")) if payload.get("linked_adoption_record_ref") is not None else None,
        apply_status=str(payload.get("apply_status")) if payload.get("apply_status") is not None else None,
        adoption_status=str(payload.get("adoption_status")) if payload.get("adoption_status") is not None else None,
        final_status=str(payload.get("final_status")) if payload.get("final_status") is not None else None,
        final_outcome_snapshot=dict(payload.get("final_outcome_snapshot", {})) if isinstance(payload.get("final_outcome_snapshot"), dict) else {},
        closed_at=str(payload.get("closed_at")) if payload.get("closed_at") is not None else None,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _pack_matches(job: PackJob, ref: str) -> bool:
    raw = str(ref or "").strip()
    if not raw:
        return True
    candidates = {
        job.pack_id,
        job.pack_ref,
        f"{job.namespace}/{job.pack_id}" if job.namespace else job.pack_id,
        f"{job.pack_id}@{job.version}" if job.version else job.pack_id,
    }
    return raw in candidates


def _project_root_from_job_path(path: Path) -> Path:
    parts = list(path.resolve().parts)
    if ".cambrian" in parts:
        return Path(*parts[: parts.index(".cambrian")])
    return path.resolve().parent


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _shorten(text: str, limit: int = 80) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
