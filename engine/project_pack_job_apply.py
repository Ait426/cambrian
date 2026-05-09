"""Pack job apply와 adoption closure를 기존 patch apply 경로에 연결한다."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_do import DoSession, DoSessionStore
from engine.project_pack_activation import context_for_installed_pack
from engine.project_pack_install import SCHEMA_VERSION, _as_list, _load_yaml, _now, _relative, _save_yaml, _slug, _stamp
from engine.project_pack_jobs import (
    PackJob,
    PackJobNextBuilder,
    PackJobStore,
    default_pack_job_path,
    default_pack_jobs_dir,
    resolve_pack_job_path,
)
from engine.project_pack_usage import safe_record_pack_usage_from_context
from engine.project_patch_apply import PatchApplier, PatchApplyResult, PatchApplyValidator

logger = logging.getLogger(__name__)


@dataclass
class PackJobApplyPreview:
    """Pack job apply preview 결과."""

    schema_version: str
    preview_id: str
    generated_at: str
    job_id: str
    job_ref: str
    pack_id: str
    proposal_ref: str | None
    patch_intent_ref: str | None
    session_ref: str | None
    target_paths: list[str]
    test_command: str | None
    safe_to_apply: bool
    requires_confirm: bool
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackJobApplyRecord:
    """Pack job confirmed apply 결과."""

    schema_version: str
    apply_id: str
    created_at: str
    job_id: str
    job_ref: str
    pack_id: str
    proposal_ref: str | None
    patch_intent_ref: str | None
    session_ref: str | None
    status: str
    apply_ref: str | None
    tests_run: bool | None
    tests_passed: bool | None
    regression_free_apply: bool | None
    changed_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackJobAdoptionRecord:
    """Pack job pack-level adoption decision."""

    schema_version: str
    adoption_id: str
    created_at: str
    job_id: str
    job_ref: str
    pack_id: str
    proposal_ref: str | None
    apply_record_ref: str | None
    decision: str
    reason: str | None
    adoption_succeeded: bool | None
    regression_free_apply: bool | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PackJobApplyHandler:
    """Validated pack job proposal의 preview/apply를 처리한다."""

    def preview(self, project_root: Path, job_ref: str) -> PackJobApplyPreview:
        """소스 수정 없이 apply 가능 여부만 점검한다."""
        root, job, job_path = _load_job(project_root, job_ref)
        job_file_ref = _relative(default_pack_job_path(root, job), root)
        proposal_path, proposal_ref = _resolve_job_proposal(root, job)
        errors = _apply_readiness_errors(job, proposal_path)
        safe_to_apply = False
        target_paths: list[str] = []
        test_command: str | None = None
        warnings: list[str] = []

        if not errors and proposal_path is not None:
            valid, reasons, context = PatchApplyValidator(adoptions_dir=root / ".cambrian" / "adoptions").validate(
                proposal_path=proposal_path,
                project_root=root,
                require_validated=True,
            )
            safe_to_apply = bool(valid)
            errors.extend(reasons)
            target_path = context.get("target_path")
            if target_path:
                target_paths.append(str(target_path))
            tests = [str(item) for item in context.get("related_tests", []) if item]
            if tests:
                test_command = "pytest " + " ".join(tests)
            context_warnings = context.get("warnings")
            if isinstance(context_warnings, list):
                warnings.extend(str(item) for item in context_warnings if item)

        preview = PackJobApplyPreview(
            schema_version=SCHEMA_VERSION,
            preview_id=f"preview-{_slug(job.job_id, 'job')}-{_stamp()}",
            generated_at=_now(),
            job_id=job.job_id,
            job_ref=job_file_ref,
            pack_id=job.pack_id,
            proposal_ref=proposal_ref,
            patch_intent_ref=job.linked_patch_intent_ref,
            session_ref=job.linked_session_ref or job.linked_session_id,
            target_paths=target_paths,
            test_command=test_command,
            safe_to_apply=safe_to_apply,
            requires_confirm=True,
            summary=_preview_summary(safe_to_apply, target_paths),
            warnings=warnings,
            errors=errors,
        )
        saved = _save_preview(root, preview)
        if safe_to_apply:
            job.apply_status = "previewed"
            job.final_status = job.final_status or "validated"
            job.next_command = f"cambrian pack job-apply {job.job_id} --confirm"
        else:
            job.apply_status = "blocked"
            job.next_command = f"cambrian pack job-validate {job.job_id}"
        job.next_actions = PackJobNextBuilder().build(root, job)
        job.updated_at = _now()
        if errors:
            job.errors = _dedupe([*job.errors, *errors])
        if warnings:
            job.warnings = _dedupe([*job.warnings, *warnings])
        _save_job(root, job, job_path)
        logger.info("pack job apply preview saved: %s", saved)
        return preview

    def apply(self, project_root: Path, job_ref: str, confirm: bool = False) -> PackJobApplyRecord:
        """--confirm이 있을 때만 기존 PatchApplier로 실제 apply를 수행한다."""
        root, job, job_path = _load_job(project_root, job_ref)
        job_file_ref = _relative(default_pack_job_path(root, job), root)
        if not confirm:
            preview = self.preview(root, job_ref)
            return PackJobApplyRecord(
                schema_version=SCHEMA_VERSION,
                apply_id=f"apply-{_slug(job.job_id, 'job')}-{_stamp()}",
                created_at=_now(),
                job_id=job.job_id,
                job_ref=job_file_ref,
                pack_id=job.pack_id,
                proposal_ref=preview.proposal_ref,
                patch_intent_ref=job.linked_patch_intent_ref,
                session_ref=job.linked_session_ref or job.linked_session_id,
                status="preview_only",
                apply_ref=None,
                tests_run=None,
                tests_passed=None,
                regression_free_apply=None,
                changed_paths=[],
                warnings=["source mutation requires --confirm"],
                errors=list(preview.errors),
            )

        proposal_path, proposal_ref = _resolve_job_proposal(root, job)
        errors = _apply_readiness_errors(job, proposal_path)
        if errors:
            record = _apply_record_from_block(root, job, job_file_ref, proposal_ref, errors)
            saved_ref = _save_apply_record(root, record)
            _mark_apply_blocked(root, job, job_path, record, saved_ref)
            return record

        assert proposal_path is not None
        result = PatchApplier().apply(
            proposal_path=proposal_path,
            project_root=root,
            adoptions_dir=root / ".cambrian" / "adoptions",
            reason=_apply_reason(job),
            dry_run=False,
        )
        record = _apply_record_from_result(root, job, job_file_ref, proposal_ref, result)
        saved_ref = _save_apply_record(root, record)
        _apply_result_to_job(root, job, job_path, record, saved_ref, result)
        return record


class PackJobAdoptionHandler:
    """Pack job 결과를 accepted/rejected/skipped로 명시 closure한다."""

    def adopt(
        self,
        project_root: Path,
        job_ref: str,
        decision: str,
        reason: str | None = None,
    ) -> PackJobAdoptionRecord:
        """Pack-level adoption decision을 기록한다."""
        root, job, job_path = _load_job(project_root, job_ref)
        normalized = str(decision or "").strip().lower()
        if normalized not in {"accepted", "rejected", "skipped"}:
            raise ValueError("decision must be accepted, rejected, or skipped")
        errors = _adoption_errors(job, normalized)
        warnings: list[str] = []
        if normalized == "accepted" and job.apply_status != "applied":
            warnings.append("accepted without confirmed pack job apply; recorded as accepted proposal evidence")
        if normalized in {"accepted", "rejected"} and not str(reason or "").strip():
            warnings.append("adoption reason is recommended for useful pack proof")

        succeeded = True if normalized == "accepted" else False if normalized == "rejected" else None
        regression_free = _bool_or_none(job.final_outcome_snapshot.get("regression_free_apply"))
        record = PackJobAdoptionRecord(
            schema_version=SCHEMA_VERSION,
            adoption_id=f"adoption-{_slug(job.job_id, 'job')}-{_stamp()}",
            created_at=_now(),
            job_id=job.job_id,
            job_ref=_relative(default_pack_job_path(root, job), root),
            pack_id=job.pack_id,
            proposal_ref=job.linked_proposal_ref,
            apply_record_ref=job.linked_apply_record_ref,
            decision=normalized,
            reason=str(reason).strip() if reason else None,
            adoption_succeeded=succeeded,
            regression_free_apply=regression_free,
            warnings=warnings,
            errors=errors,
        )
        saved_ref = _save_adoption_record(root, record)
        _adoption_to_job(root, job, job_path, record, saved_ref)
        return record


def default_apply_previews_dir(project_root: Path) -> Path:
    return default_pack_jobs_dir(project_root) / "apply_previews"


def default_apply_records_dir(project_root: Path) -> Path:
    return default_pack_jobs_dir(project_root) / "apply_records"


def default_job_adoptions_dir(project_root: Path) -> Path:
    return default_pack_jobs_dir(project_root) / "adoptions"


def render_pack_job_apply_preview(preview: PackJobApplyPreview) -> str:
    """Apply preview를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Job Apply Preview",
        "==================================================",
        "",
        "Job:",
        f"  {preview.job_id}",
        "",
        "Status:",
        "  ready to apply with confirmation" if preview.safe_to_apply else "  blocked",
    ]
    if preview.target_paths:
        lines.extend(["", "Target:"])
        lines.extend([f"  {item}" for item in preview.target_paths])
    if preview.test_command:
        lines.extend(["", "Tests:", f"  {preview.test_command}"])
    if preview.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in preview.errors])
    if preview.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in preview.warnings])
    lines.extend(["", "This will modify project source only if you run:", "", f"  cambrian pack job-apply {preview.job_id} --confirm"])
    return "\n".join(lines)


def render_pack_job_apply_record(record: PackJobApplyRecord) -> str:
    """Confirmed apply 결과를 사람이 읽기 좋게 렌더링한다."""
    title = "Pack Job Applied" if record.status == "applied" else "Pack Job Apply Blocked"
    lines = [
        title,
        "==================================================",
        "",
        "Job:",
        f"  {record.job_id}",
        "",
        "Status:",
        f"  {record.status}",
    ]
    if record.changed_paths:
        lines.extend(["", "Changed:"])
        lines.extend([f"  {item}" for item in record.changed_paths])
    if record.tests_run is not None:
        lines.extend(["", "Tests:", f"  {'passed' if record.tests_passed else 'failed'}"])
    if record.apply_ref:
        lines.extend(["", "Apply record:", f"  {record.apply_ref}"])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    lines.extend(["", "Next:", f'  cambrian pack job-adopt {record.job_id} --accepted --reason "validated and applied cleanly"'])
    return "\n".join(lines)


def render_pack_job_adoption_record(record: PackJobAdoptionRecord) -> str:
    """Adoption decision 결과를 렌더링한다."""
    lines = [
        "Pack Job Adoption Recorded",
        "==================================================",
        "",
        "Job:",
        f"  {record.job_id}",
        "",
        "Decision:",
        f"  {record.decision}",
        "",
        "Pack outcome updated:",
        f"  {record.pack_id}",
    ]
    if record.reason:
        lines.extend(["", "Reason:", f"  {record.reason}"])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    lines.extend([
        "",
        "Next:",
        f"  cambrian pack job-retro {record.job_id}",
        f"  cambrian pack proof {record.pack_id}",
    ])
    return "\n".join(lines)


def _load_job(project_root: Path, job_ref: str) -> tuple[Path, PackJob, Path]:
    root = Path(project_root).resolve()
    job_path = resolve_pack_job_path(root, job_ref)
    return root, PackJobStore().load(job_path), job_path


def _resolve_job_proposal(root: Path, job: PackJob) -> tuple[Path | None, str | None]:
    ref = job.linked_proposal_ref
    if ref:
        path = _resolve_ref(root, ref)
        if path.exists():
            return path, _relative(path, root)
    session = _load_session(root, job)
    if session is not None:
        proposal_ref = session.artifacts.get("patch_proposal_path")
        if proposal_ref:
            path = _resolve_ref(root, str(proposal_ref))
            if path.exists():
                job.linked_proposal_ref = _relative(path, root)
                return path, job.linked_proposal_ref
    return None, ref


def _apply_readiness_errors(job: PackJob, proposal_path: Path | None) -> list[str]:
    errors: list[str] = []
    if job.adoption_status in {"accepted", "rejected", "skipped"}:
        errors.append(f"pack job adoption is already {job.adoption_status}")
    if job.apply_status == "applied":
        errors.append("pack job is already applied")
    if job.validation_status != "validated" and job.status != "validated":
        errors.append("no validated proposal is linked")
    if not job.linked_proposal_ref and proposal_path is None:
        errors.append("proposal ref is missing")
    if proposal_path is None or not proposal_path.exists():
        errors.append("proposal file not found")
    return _dedupe(errors)


def _adoption_errors(job: PackJob, decision: str) -> list[str]:
    errors: list[str] = []
    if decision == "accepted" and job.validation_status != "validated" and job.status not in {"validated", "applied"}:
        errors.append("accepted decision requires a validated proposal or applied job")
    if job.adoption_status in {"accepted", "rejected", "skipped"}:
        errors.append(f"pack job adoption is already {job.adoption_status}")
    return _dedupe(errors)


def _apply_record_from_block(root: Path, job: PackJob, job_ref: str, proposal_ref: str | None, errors: list[str]) -> PackJobApplyRecord:
    return PackJobApplyRecord(
        schema_version=SCHEMA_VERSION,
        apply_id=f"apply-{_slug(job.job_id, 'job')}-{_stamp()}",
        created_at=_now(),
        job_id=job.job_id,
        job_ref=job_ref,
        pack_id=job.pack_id,
        proposal_ref=proposal_ref,
        patch_intent_ref=job.linked_patch_intent_ref,
        session_ref=job.linked_session_ref or job.linked_session_id,
        status="blocked",
        apply_ref=None,
        tests_run=None,
        tests_passed=None,
        regression_free_apply=None,
        changed_paths=[],
        errors=errors,
    )


def _apply_record_from_result(root: Path, job: PackJob, job_ref: str, proposal_ref: str | None, result: PatchApplyResult) -> PackJobApplyRecord:
    tests = result.post_apply_tests if isinstance(result.post_apply_tests, dict) else None
    tests_passed = _post_apply_passed(tests) if tests is not None else None
    status = "applied" if result.status in {"applied", "duplicate"} else "blocked" if result.status == "blocked" else "failed"
    changed_paths = [str(item.get("target_path")) for item in result.applied_files if isinstance(item, dict) and item.get("target_path")]
    warnings = list(result.warnings)
    if result.status == "duplicate":
        warnings.append("proposal was already applied through the lower-level apply path")
    if result.status == "applied":
        warnings.append("lower-level patch apply record was created; pack-level adoption still requires job-adopt")
    return PackJobApplyRecord(
        schema_version=SCHEMA_VERSION,
        apply_id=f"apply-{_slug(job.job_id, 'job')}-{_stamp()}",
        created_at=_now(),
        job_id=job.job_id,
        job_ref=job_ref,
        pack_id=job.pack_id,
        proposal_ref=proposal_ref,
        patch_intent_ref=job.linked_patch_intent_ref,
        session_ref=job.linked_session_ref or job.linked_session_id,
        status=status,
        apply_ref=result.adoption_record_path,
        tests_run=tests is not None,
        tests_passed=tests_passed,
        regression_free_apply=True if status == "applied" and tests_passed is True else False if status == "failed" or tests_passed is False else None,
        changed_paths=changed_paths,
        warnings=warnings,
        errors=[*list(result.errors), *list(result.reasons if result.status != "applied" else [])],
    )


def _save_preview(root: Path, preview: PackJobApplyPreview) -> str:
    path = default_apply_previews_dir(root) / f"{preview.preview_id}.yaml"
    _save_yaml(path, preview.to_dict())
    return _relative(path, root)


def _save_apply_record(root: Path, record: PackJobApplyRecord) -> str:
    path = default_apply_records_dir(root) / f"{record.apply_id}.yaml"
    _save_yaml(path, record.to_dict())
    return _relative(path, root)


def _save_adoption_record(root: Path, record: PackJobAdoptionRecord) -> str:
    path = default_job_adoptions_dir(root) / f"{record.adoption_id}.yaml"
    _save_yaml(path, record.to_dict())
    return _relative(path, root)


def _mark_apply_blocked(root: Path, job: PackJob, job_path: Path, record: PackJobApplyRecord, saved_ref: str) -> None:
    job.linked_apply_record_ref = saved_ref
    job.apply_status = "blocked"
    if job.adoption_status not in {"accepted", "rejected", "skipped"}:
        job.final_status = "blocked"
        job.status = "blocked"
    job.next_command = f"cambrian pack job-show {job.job_id}"
    job.errors = _dedupe([*job.errors, *record.errors])
    job.next_actions = PackJobNextBuilder().build(root, job)
    _save_job(root, job, job_path)


def _apply_result_to_job(root: Path, job: PackJob, job_path: Path, record: PackJobApplyRecord, saved_ref: str, result: PatchApplyResult) -> None:
    job.linked_apply_record_ref = saved_ref
    job.apply_status = record.status
    if record.status == "applied":
        job.status = "applied"
        job.final_status = "applied"
        job.next_command = f'cambrian pack job-adopt {job.job_id} --accepted --reason "validated and applied cleanly"'
    else:
        job.status = record.status
        job.final_status = record.status
        job.next_command = f"cambrian pack job-show {job.job_id}"
    job.final_outcome_snapshot = _merge_final_outcome(
        job,
        applied=record.status == "applied",
        regression_free_apply=record.regression_free_apply,
    )
    job.warnings = _dedupe([*job.warnings, *record.warnings])
    job.errors = _dedupe([*job.errors, *record.errors])
    job.next_actions = PackJobNextBuilder().build(root, job)
    _update_session_after_apply(root, job, record, result)
    event_ref = _record_job_usage(root, job, surface_kind="pack_job_apply")
    if event_ref:
        job.usage_event_ref = event_ref
    _save_job(root, job, job_path)


def _adoption_to_job(root: Path, job: PackJob, job_path: Path, record: PackJobAdoptionRecord, saved_ref: str) -> None:
    job.linked_adoption_record_ref = saved_ref
    job.adoption_status = record.decision
    if record.decision == "accepted":
        job.status = "adopted"
        job.final_status = "adopted"
    elif record.decision == "rejected":
        job.status = "rejected"
        job.final_status = "rejected"
    else:
        job.status = "closed"
        job.final_status = "closed"
    job.closed_at = _now()
    job.final_outcome_snapshot = _merge_final_outcome(
        job,
        adoption_succeeded=record.adoption_succeeded,
        regression_free_apply=record.regression_free_apply,
        adoption_reason=record.reason if record.decision == "accepted" else None,
        rejection_reason=record.reason if record.decision == "rejected" else None,
    )
    job.warnings = _dedupe([*job.warnings, *record.warnings])
    job.errors = _dedupe([*job.errors, *record.errors])
    job.next_command = f"cambrian pack proof {job.pack_id}"
    job.next_actions = PackJobNextBuilder().build(root, job)
    _update_session_after_adoption(root, job, record)
    event_ref = _record_job_usage(root, job, surface_kind="pack_job_adopt")
    if event_ref:
        job.usage_event_ref = event_ref
    _save_job(root, job, job_path)


def _merge_final_outcome(
    job: PackJob,
    *,
    applied: bool | None = None,
    adoption_succeeded: bool | None = None,
    regression_free_apply: bool | None = None,
    adoption_reason: str | None = None,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    snapshot = dict(job.final_outcome_snapshot or {})
    snapshot.setdefault("validated_proposal", (job.outcome_snapshot or {}).get("validated_proposal", job.validation_status == "validated"))
    snapshot.setdefault("human_intervention", (job.outcome_snapshot or {}).get("human_intervention"))
    snapshot.setdefault("validation_autonomy", (job.outcome_snapshot or {}).get("validation_autonomy"))
    snapshot.setdefault("duration_seconds", (job.outcome_snapshot or {}).get("duration_seconds"))
    if applied is not None:
        snapshot["applied"] = applied
    if adoption_succeeded is not None or "adoption_succeeded" not in snapshot:
        snapshot["adoption_succeeded"] = adoption_succeeded
    if regression_free_apply is not None:
        snapshot["regression_free_apply"] = regression_free_apply
    if adoption_reason:
        snapshot["adoption_reason"] = adoption_reason
    if rejection_reason:
        snapshot["rejection_reason"] = rejection_reason
    return snapshot


def _update_session_after_apply(root: Path, job: PackJob, record: PackJobApplyRecord, result: PatchApplyResult) -> None:
    session = _load_session(root, job)
    if session is None:
        return
    metrics = _metrics(session)
    results = metrics.setdefault("results", {})
    if isinstance(results, dict):
        results["validated_proposal"] = True
        results["applied"] = record.status == "applied"
        if record.tests_passed is not None:
            results["apply_tests_passed"] = record.tests_passed
        if record.regression_free_apply is not None:
            results["regression_free_apply"] = record.regression_free_apply
    milestones = metrics.setdefault("milestones", {})
    if isinstance(milestones, dict):
        milestones["applied_at"] = record.created_at
    session.metrics_context = metrics
    session.artifacts["pack_job_apply_record_path"] = record.apply_id
    if result.adoption_record_path:
        session.artifacts["adoption_record_path"] = result.adoption_record_path
    session.current_stage = "patch_proposal_validated"
    session.status = "patch_proposal_validated"
    DoSessionStore().save(root, session)


def _update_session_after_adoption(root: Path, job: PackJob, record: PackJobAdoptionRecord) -> None:
    session = _load_session(root, job)
    if session is None:
        return
    metrics = _metrics(session)
    results = metrics.setdefault("results", {})
    if isinstance(results, dict):
        results["validated_proposal"] = job.validation_status == "validated" or job.status in {"applied", "adopted", "rejected", "closed"}
        results["adoption_succeeded"] = record.adoption_succeeded
        if record.regression_free_apply is not None:
            results["regression_free_apply"] = record.regression_free_apply
    milestones = metrics.setdefault("milestones", {})
    if isinstance(milestones, dict):
        milestones["adoption_decided_at"] = record.created_at
    session.metrics_context = metrics
    if record.decision == "accepted":
        session.status = "adopted"
        session.current_stage = "adopted"
    else:
        session.status = "closed"
        session.current_stage = "closed"
    session.artifacts["pack_job_adoption_record_path"] = record.adoption_id
    DoSessionStore().save(root, session)


def _metrics(session: DoSession) -> dict[str, Any]:
    metrics = dict(session.metrics_context or {})
    metrics["pack_job_id"] = metrics.get("pack_job_id")
    return metrics


def _load_session(root: Path, job: PackJob) -> DoSession | None:
    session_ref = job.linked_session_ref or job.linked_session_id
    if not session_ref:
        return None
    try:
        path = DoSessionStore().resolve_path(root, session_ref)
        return DoSessionStore().load(path)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        logger.warning("pack job session load skipped: %s", exc)
        return None


def _record_job_usage(root: Path, job: PackJob, *, surface_kind: str) -> str | None:
    try:
        try:
            context = context_for_installed_pack(root, job.pack_id)
        except Exception:
            context = context_for_installed_pack(root, job.pack_ref or job.pack_id)
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
            summary=f"active pack used in {surface_kind}",
        )
        return _relative(event_path, root) if event_path is not None else None
    except Exception as exc:
        logger.warning("pack job usage event failed: %s", exc)
        return None


def _save_job(root: Path, job: PackJob, job_path: Path) -> Path:
    job.updated_at = _now()
    return PackJobStore().save(job, default_pack_job_path(root, job) if job_path.name == "latest.yaml" else job_path)


def _resolve_ref(root: Path, ref: str) -> Path:
    path = Path(str(ref))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        logger.exception("pack job apply artifact load failed: %s", path)
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_reason(job: PackJob) -> str:
    request = str(job.request or "").strip()
    return f"pack job apply: {request or job.job_id}"


def _preview_summary(safe_to_apply: bool, target_paths: list[str]) -> list[str]:
    if safe_to_apply:
        return ["validated proposal is ready for explicit --confirm apply", *[f"target={path}" for path in target_paths]]
    return ["pack job is not ready for apply"]


def _post_apply_passed(tests: dict[str, Any] | None) -> bool:
    if not isinstance(tests, dict):
        return False
    try:
        exit_code = int(tests.get("exit_code", -1) if tests.get("exit_code") is not None else -1)
        failed = int(tests.get("failed", 0) if tests.get("failed") is not None else 0)
    except (TypeError, ValueError):
        return False
    return exit_code == 0 and failed == 0


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "accepted", "applied", "passed"}:
        return True
    if text in {"0", "false", "no", "rejected", "failed", "blocked"}:
        return False
    return None


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
