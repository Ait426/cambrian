"""Pack readiness repair와 guided setup plan."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_activation import (
    PackActivator,
    PackNextGuideBuilder,
    current_active_pack,
    save_pack_next_guide,
)
from engine.project_pack_install import SCHEMA_VERSION, _as_list, _load_yaml, _now, _relative, _save_yaml, _slug, _stamp
from engine.project_pack_readiness import (
    PackReadinessBuilder,
    PackReadinessCheck,
    PackReadinessReport,
    latest_pack_readiness,
    save_pack_readiness_report,
)

logger = logging.getLogger(__name__)


@dataclass
class PackSetupStep:
    """Setup plan 안의 단일 checklist step."""

    step_id: str
    title: str
    action_kind: str
    status: str
    command: str | None
    reason: str
    safety_note: str | None
    source_check_id: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        return asdict(self)


@dataclass
class PackSetupPlan:
    """Readiness report를 행동 가능한 setup checklist로 바꾼 결과."""

    schema_version: str
    plan_id: str
    generated_at: str
    pack_ref: str | None
    pack_id: str | None
    pack_name: str | None
    namespace: str | None
    version: str | None
    source_readiness_ref: str | None
    readiness_status: str | None
    fit_status: str | None
    steps: list[PackSetupStep]
    safe_apply_available: bool
    blocked: bool
    summary: list[str]
    next_actions: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


@dataclass
class PackSetupRun:
    """Setup plan의 safe Cambrian-state step 적용 결과."""

    schema_version: str
    run_id: str
    created_at: str
    plan_ref: str
    pack_ref: str | None
    pack_id: str | None
    applied_steps: list[str]
    skipped_steps: list[str]
    blocked_steps: list[str]
    status: str
    resulting_readiness_ref: str | None
    resulting_next_guide_ref: str | None
    summary: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        return asdict(self)


def default_setup_plans_dir(project_root: Path) -> Path:
    """setup plan 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "setup_plans"


def default_setup_runs_dir(project_root: Path) -> Path:
    """setup run 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "setup_runs"


def default_setup_plan_path(project_root: Path, plan: PackSetupPlan) -> Path:
    """setup plan 기본 저장 경로를 반환한다."""
    pack_id = plan.pack_id or "no-pack"
    return default_setup_plans_dir(project_root) / f"setup_{_slug(pack_id, 'pack')}_{_stamp()}.yaml"


def default_setup_run_path(project_root: Path, run: PackSetupRun) -> Path:
    """setup run 기본 저장 경로를 반환한다."""
    pack_id = run.pack_id or "no-pack"
    return default_setup_runs_dir(project_root) / f"setup_run_{_slug(pack_id, 'pack')}_{_stamp()}.yaml"


def latest_setup_plan_path(project_root: Path) -> Path:
    """latest setup plan 경로를 반환한다."""
    return default_setup_plans_dir(project_root) / "latest.yaml"


def latest_setup_run_path(project_root: Path) -> Path:
    """latest setup run 경로를 반환한다."""
    return default_setup_runs_dir(project_root) / "latest.yaml"


class PackSetupStore:
    """Pack setup plan/run 저장소."""

    def save_plan(self, plan: PackSetupPlan, path: Path) -> Path:
        """setup plan을 저장하고 latest pointer를 갱신한다."""
        target = Path(path).resolve()
        project_root = _project_root_from_setup_path(target)
        plan.saved_ref = _relative(target, project_root)
        _save_yaml(target, plan.to_dict())
        if target.name != "latest.yaml":
            latest_payload = plan.to_dict()
            latest_payload["saved_ref"] = plan.saved_ref
            _save_yaml(latest_setup_plan_path(project_root), latest_payload)
        return target

    def load_plan(self, path: Path) -> PackSetupPlan:
        """setup plan을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"setup plan not found: {path}")
        return _plan_from_dict(payload)

    def save_run(self, run: PackSetupRun, path: Path) -> Path:
        """setup run을 저장하고 latest pointer를 갱신한다."""
        target = Path(path).resolve()
        project_root = _project_root_from_setup_path(target)
        run.saved_ref = _relative(target, project_root)
        _save_yaml(target, run.to_dict())
        if target.name != "latest.yaml":
            latest_payload = run.to_dict()
            latest_payload["saved_ref"] = run.saved_ref
            _save_yaml(latest_setup_run_path(project_root), latest_payload)
        return target


class PackSetupPlanner:
    """Readiness report를 setup checklist로 변환한다."""

    def build(self, project_root: Path, pack_ref: str | None = None) -> PackSetupPlan:
        """pack setup plan을 만든다."""
        root = Path(project_root).resolve()
        report = _readiness_source(root, pack_ref)
        steps = _steps_from_readiness(report)
        safe_apply_available = any(step.action_kind in {"safe_auto_fix", "safe_cambrian_state_fix"} and step.status == "todo" for step in steps)
        blocked = any(step.action_kind == "unsupported" or step.status == "blocked" for step in steps)
        user_actions = [step for step in steps if step.action_kind == "user_action_required" and step.status == "todo"]
        warnings = _dedupe([item for step in steps for item in step.warnings])
        errors = _dedupe([item for step in steps for item in step.errors])
        summary = [
            f"readiness: {report.readiness_status}",
            f"safe fixes: {sum(1 for step in steps if step.action_kind in {'safe_auto_fix', 'safe_cambrian_state_fix'})}",
            f"user actions: {len(user_actions)}",
        ]
        next_actions = _plan_next_actions(report, safe_apply_available, user_actions, blocked)
        return PackSetupPlan(
            schema_version=SCHEMA_VERSION,
            plan_id=f"setup-{_slug(report.pack_id, 'pack')}-{_stamp()}",
            generated_at=_now(),
            pack_ref=report.pack_ref,
            pack_id=report.pack_id,
            pack_name=report.pack_name,
            namespace=report.namespace,
            version=report.version,
            source_readiness_ref=report.saved_ref,
            readiness_status=report.readiness_status,
            fit_status=report.fit_status,
            steps=steps,
            safe_apply_available=safe_apply_available,
            blocked=blocked,
            summary=summary,
            next_actions=next_actions,
            warnings=warnings,
            errors=errors,
        )


class PackSetupApplier:
    """Setup plan의 safe Cambrian-state step만 적용한다."""

    def apply(self, project_root: Path, plan_path: Path) -> PackSetupRun:
        """safe_auto_fix와 safe_cambrian_state_fix만 적용한다."""
        root = Path(project_root).resolve()
        resolved_plan_path = resolve_pack_setup_plan_path(root, str(plan_path))
        plan = PackSetupStore().load_plan(resolved_plan_path)
        applied_steps: list[str] = []
        skipped_steps: list[str] = []
        blocked_steps: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []
        resulting_readiness_ref: str | None = None
        resulting_next_guide_ref: str | None = None

        for step in plan.steps:
            if step.action_kind not in {"safe_auto_fix", "safe_cambrian_state_fix"}:
                if step.action_kind == "unsupported":
                    blocked_steps.append(step.step_id)
                elif step.action_kind == "user_action_required":
                    skipped_steps.append(step.step_id)
                    warnings.append(f"skipped user action required: {step.title}")
                continue
            try:
                if step.step_id == "activate_pack_context":
                    if not plan.pack_id:
                        raise ValueError("pack id is required for activation")
                    PackActivator().activate(root, plan.pack_id)
                    applied_steps.append(step.step_id)
                elif step.step_id == "refresh_next_guide":
                    guide = PackNextGuideBuilder().build(root, plan.pack_id)
                    resulting_next_guide_ref = _relative(save_pack_next_guide(root, guide), root)
                    applied_steps.append(step.step_id)
                elif step.step_id == "refresh_readiness_report":
                    if not plan.pack_id:
                        raise ValueError("pack id is required for readiness refresh")
                    readiness = PackReadinessBuilder().build(root, plan.pack_id)
                    resulting_readiness_ref = save_pack_readiness_report(root, readiness)
                    applied_steps.append(step.step_id)
                else:
                    skipped_steps.append(step.step_id)
                    warnings.append(f"safe step has no V1 applier: {step.step_id}")
            except Exception as exc:
                blocked_steps.append(step.step_id)
                errors.append(f"{step.step_id} failed: {exc}")
                logger.warning("pack setup step failed: %s (%s)", step.step_id, exc)

        if resulting_readiness_ref is None and plan.pack_id and applied_steps:
            try:
                readiness = PackReadinessBuilder().build(root, plan.pack_id)
                resulting_readiness_ref = save_pack_readiness_report(root, readiness)
            except Exception as exc:
                warnings.append(f"readiness refresh after setup failed: {exc}")
                logger.warning("pack setup readiness refresh failed: %s", exc)

        status = _run_status(applied_steps, skipped_steps, blocked_steps, errors)
        run = PackSetupRun(
            schema_version=SCHEMA_VERSION,
            run_id=f"setup-run-{_slug(plan.pack_id, 'pack')}-{_stamp()}",
            created_at=_now(),
            plan_ref=_relative(resolved_plan_path, root),
            pack_ref=plan.pack_ref,
            pack_id=plan.pack_id,
            applied_steps=applied_steps,
            skipped_steps=skipped_steps,
            blocked_steps=blocked_steps,
            status=status,
            resulting_readiness_ref=resulting_readiness_ref,
            resulting_next_guide_ref=resulting_next_guide_ref,
            summary=_run_summary(applied_steps, skipped_steps, blocked_steps),
            warnings=_dedupe([*warnings, *plan.warnings]),
            errors=_dedupe([*errors, *(plan.errors if status in {"blocked", "failed"} else [])]),
        )
        PackSetupStore().save_run(run, default_setup_run_path(root, run))
        return run


def save_pack_setup_plan(project_root: Path, plan: PackSetupPlan) -> str:
    """setup plan을 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = default_setup_plan_path(root, plan)
    PackSetupStore().save_plan(plan, path)
    return plan.saved_ref or _relative(path, root)


def latest_pack_setup_plan(project_root: Path, pack_ref: str | None = None) -> PackSetupPlan | None:
    """latest setup plan을 반환한다."""
    root = Path(project_root).resolve()
    candidates: list[Path] = []
    latest = latest_setup_plan_path(root)
    if latest.exists():
        candidates.append(latest)
    plans_dir = default_setup_plans_dir(root)
    if plans_dir.exists():
        candidates.extend(sorted(plans_dir.glob("setup_*.yaml"), reverse=True))
    wanted = _pack_id_from_ref(pack_ref) if pack_ref else None
    for path in candidates:
        try:
            plan = PackSetupStore().load_plan(path)
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            logger.warning("setup plan load skipped: %s (%s)", path, exc)
            continue
        if wanted is None or plan.pack_id == wanted:
            return plan
    return None


def resolve_pack_setup_plan_path(project_root: Path, ref: str) -> Path:
    """setup plan id 또는 path를 실제 파일 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = str(ref).strip()
    direct = Path(raw)
    if direct.exists():
        return direct.resolve()
    if not direct.is_absolute() and (root / direct).exists():
        return (root / direct).resolve()
    if raw == "latest":
        latest = latest_setup_plan_path(root)
        if latest.exists():
            return latest.resolve()
    plans_dir = default_setup_plans_dir(root)
    if plans_dir.exists():
        for path in sorted(plans_dir.glob("*.yaml"), reverse=True):
            try:
                plan = PackSetupStore().load_plan(path)
            except (FileNotFoundError, ValueError, yaml.YAMLError):
                continue
            if raw in {plan.plan_id, path.name, path.stem, plan.saved_ref}:
                return path.resolve()
    raise FileNotFoundError(f"setup plan not found: {ref}")


def render_pack_setup_plan(plan: PackSetupPlan) -> str:
    """setup plan을 사람에게 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Setup Plan",
        "==================================================",
        "",
        "Pack:",
        f"  {plan.pack_ref or plan.pack_id or 'none'}",
        "",
        "Readiness:",
        f"  {plan.readiness_status or 'unknown'}",
        "",
        "Fit:",
        f"  {plan.fit_status or 'unknown'}",
    ]
    groups = [
        ("Safe Cambrian fixes", {"safe_auto_fix", "safe_cambrian_state_fix"}),
        ("User actions required", {"user_action_required"}),
        ("Unsupported", {"unsupported"}),
        ("Informational", {"informational"}),
    ]
    for title, kinds in groups:
        selected = [step for step in plan.steps if step.action_kind in kinds]
        if not selected:
            continue
        lines.extend(["", f"{title}:"])
        for index, step in enumerate(selected, start=1):
            lines.append(f"  {index}. {step.title}")
            lines.append(f"     status: {step.status}")
            if step.command:
                lines.append(f"     command: {step.command}")
            lines.append(f"     reason: {step.reason}")
            if step.safety_note:
                lines.append(f"     safety: {step.safety_note}")
    if plan.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in plan.next_actions])
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in plan.warnings])
    if plan.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in plan.errors])
    if plan.saved_ref:
        lines.extend(["", "Saved:", f"  {plan.saved_ref}"])
    return "\n".join(lines)


def render_pack_setup_run(run: PackSetupRun) -> str:
    """setup apply 결과를 렌더링한다."""
    lines = [
        "Pack setup applied.",
        "",
        "Status:",
        f"  {run.status}",
    ]
    if run.applied_steps:
        lines.extend(["", "Applied:"])
        lines.extend([f"  - {item}" for item in run.applied_steps])
    if run.skipped_steps:
        lines.extend(["", "Skipped:"])
        lines.extend([f"  - {item}" for item in run.skipped_steps])
    if run.blocked_steps:
        lines.extend(["", "Blocked:"])
        lines.extend([f"  - {item}" for item in run.blocked_steps])
    if run.resulting_readiness_ref:
        lines.extend(["", "Readiness:", f"  {run.resulting_readiness_ref}"])
    if run.resulting_next_guide_ref:
        lines.extend(["", "Next guide:", f"  {run.resulting_next_guide_ref}"])
    if run.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in run.warnings])
    if run.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in run.errors])
    lines.extend(["", "Next:", f"  cambrian pack doctor {run.pack_id or ''}".rstrip()])
    return "\n".join(lines)


def render_pack_setup_compact(plan: PackSetupPlan | None) -> str:
    """status/doctor/next에 붙일 compact setup summary."""
    if plan is None:
        return ""
    unresolved = [
        step
        for step in plan.steps
        if step.status in {"todo", "blocked"} and step.action_kind in {"user_action_required", "unsupported"}
    ]
    safe = [
        step
        for step in plan.steps
        if step.status == "todo" and step.action_kind in {"safe_auto_fix", "safe_cambrian_state_fix"}
    ]
    if not unresolved and not safe:
        return ""
    lines = [
        "",
        "Pack setup:",
        f"  unresolved user actions: {len(unresolved)}",
        f"  safe fixes available: {len(safe)}",
    ]
    if plan.saved_ref:
        lines.append(f"  plan: cambrian pack setup-show {plan.saved_ref}")
    elif plan.pack_id:
        lines.append(f"  next: cambrian pack setup {plan.pack_id}")
    return "\n".join(lines)


def render_pack_setup_prompt(report: PackReadinessReport) -> str:
    """setup plan이 없을 때 doctor/next에 붙이는 안내."""
    if report.readiness_status == "ready":
        return ""
    pack = report.pack_id or "PACK_ID"
    return "\n".join(["", "Setup:", f"  cambrian pack setup {pack}"])


def _readiness_source(root: Path, pack_ref: str | None) -> PackReadinessReport:
    try:
        report = PackReadinessBuilder().build(root, pack_ref)
    except KeyError:
        latest = latest_pack_readiness(root, pack_ref)
        if latest is not None:
            return latest
        raise
    save_pack_readiness_report(root, report)
    return report


def _steps_from_readiness(report: PackReadinessReport) -> list[PackSetupStep]:
    steps: list[PackSetupStep] = []
    for check in report.checks:
        mapped = _step_from_check(report, check)
        if mapped is not None:
            steps.append(mapped)
    if report.installed and not report.active:
        steps.append(
            PackSetupStep(
                step_id="activate_pack_context",
                title="Activate pack context",
                action_kind="safe_cambrian_state_fix",
                status="todo",
                command=f"cambrian pack activate {report.pack_id}",
                reason="pack is installed but not selected as the current soft work context",
                safety_note="This only writes active_pack.yaml. It does not apply templates or mutate source code.",
                source_check_id="installed_state",
            )
        )
    if report.installed and report.pack_id:
        steps.append(
            PackSetupStep(
                step_id="refresh_next_guide",
                title="Refresh first-job next guide",
                action_kind="safe_auto_fix",
                status="todo",
                command=f"cambrian pack next {report.pack_id}",
                reason="first-job commands can be regenerated from installed pack metadata",
                safety_note="This only writes a derived Cambrian guide artifact.",
                source_check_id="first_job_ready",
            )
        )
        steps.append(
            PackSetupStep(
                step_id="refresh_readiness_report",
                title="Rebuild readiness report",
                action_kind="safe_auto_fix",
                status="todo",
                command=f"cambrian pack doctor {report.pack_id} --save",
                reason="after setup, readiness should be refreshed for provenance",
                safety_note="This only writes `.cambrian/packs/readiness/` metadata.",
                source_check_id=None,
            )
        )
    if report.readiness_status == "ready":
        steps.append(
            PackSetupStep(
                step_id="start_first_job",
                title="Start first job",
                action_kind="informational",
                status="todo",
                command=_first_job_command(report),
                reason="pack appears ready enough for first-job guidance",
                safety_note="This is a suggested next command only; setup-apply will not run it.",
                source_check_id="first_job_ready",
            )
        )
    return _dedupe_steps(steps)


def _step_from_check(report: PackReadinessReport, check: PackReadinessCheck) -> PackSetupStep | None:
    if check.check_id == "installed_state" and check.status == "fail":
        return PackSetupStep(
            step_id="install_pack",
            title="Install pack",
            action_kind="user_action_required",
            status="todo",
            command=_first_command(check) or f"cambrian install pack {report.pack_id}",
            reason="pack must be installed before activation or first job",
            safety_note="setup-apply will not install packs automatically.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "integrity_state" and check.status in {"fail", "warn"}:
        return PackSetupStep(
            step_id="verify_install_integrity",
            title="Verify installed pack integrity",
            action_kind="user_action_required" if check.status == "fail" else "informational",
            status="todo" if check.status == "fail" else "skipped",
            command=_first_command(check) or f"cambrian install verify {report.pack_id}",
            reason=check.summary,
            safety_note="setup-apply does not rewrite manifests or lockfiles for integrity failures.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "artifact_refs" and check.status == "fail":
        return PackSetupStep(
            step_id="repair_missing_pack_artifacts",
            title="Repair missing installed artifacts",
            action_kind="user_action_required",
            status="todo",
            command="cambrian install doctor",
            reason="installed worker/team/template/benchmark refs must exist before first job",
            safety_note="setup-apply will not create fake missing artifacts.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id in {"project_stack_fit", "test_framework_fit"} and check.status == "fail":
        return PackSetupStep(
            step_id=f"unsupported_{check.check_id}",
            title=check.title,
            action_kind="unsupported",
            status="blocked",
            command="cambrian pack recommend",
            reason=check.summary,
            safety_note="Cambrian will not rewrite the project stack or install dependencies automatically.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "test_framework_fit" and check.status == "warn":
        return PackSetupStep(
            step_id="configure_test_framework",
            title="Confirm or configure pytest",
            action_kind="user_action_required",
            status="todo",
            command=None,
            reason="pytest was not detected; validation confidence may be lower",
            safety_note="Cambrian will not install pytest or edit project files automatically.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "project_stack_fit" and check.status == "warn":
        return PackSetupStep(
            step_id="confirm_project_stack",
            title="Confirm project stack",
            action_kind="user_action_required",
            status="todo",
            command=None,
            reason="project stack could not be detected from local markers",
            safety_note="Cambrian will not create pyproject/setup/source files automatically.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "strongest_lane_fit" and check.status == "warn":
        return PackSetupStep(
            step_id="review_lane_fit",
            title="Review lane fit",
            action_kind="informational",
            status="todo",
            command="cambrian pack recommend",
            reason=check.summary,
            safety_note="Outside-lane work is allowed, but expectations should be lowered.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "first_job_ready" and check.status in {"fail", "warn"}:
        return PackSetupStep(
            step_id="prepare_first_job_context",
            title="Prepare first-job context",
            action_kind="safe_auto_fix" if report.installed else "user_action_required",
            status="todo",
            command=f"cambrian pack next {report.pack_id}" if report.installed else f"cambrian install pack {report.pack_id}",
            reason=check.summary,
            safety_note="This only regenerates Cambrian guidance when installed; it does not apply templates.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "proof_available" and check.status == "warn":
        command = f"cambrian benchmark proof {report.default_workset}" if report.default_workset else None
        return PackSetupStep(
            step_id="optional_proof",
            title="Optional local proof",
            action_kind="informational",
            status="todo",
            command=command,
            reason="proof is not required for first job, but helps evaluate pack quality",
            safety_note="setup-apply will not execute benchmark replay or proof commands.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    if check.check_id == "known_limits" and check.status == "warn":
        return PackSetupStep(
            step_id="review_known_limits",
            title="Review known limits",
            action_kind="informational",
            status="todo",
            command=None,
            reason=check.summary,
            safety_note="Known limits are guidance only.",
            source_check_id=check.check_id,
            warnings=list(check.warnings),
            errors=list(check.errors),
        )
    return None


def _plan_next_actions(
    report: PackReadinessReport,
    safe_apply_available: bool,
    user_actions: list[PackSetupStep],
    blocked: bool,
) -> list[str]:
    actions: list[str] = []
    if safe_apply_available:
        actions.append(f"cambrian pack setup-apply setup-{_slug(report.pack_id, 'pack')}-...")
    actions.extend([step.command for step in user_actions if step.command])
    if blocked and not actions:
        actions.append("cambrian pack recommend")
    if report.readiness_status == "ready":
        actions.extend([f"cambrian pack activate {report.pack_id}", "cambrian pack next"])
    return _dedupe([item for item in actions if item])


def _first_command(check: PackReadinessCheck) -> str | None:
    return check.next_actions[0] if check.next_actions else None


def _first_job_command(report: PackReadinessReport) -> str:
    request = report.recommended_request_examples[0] if report.recommended_request_examples else "로그인 에러 수정해"
    return f'cambrian bridge prepare "{request}"'


def _dedupe_steps(steps: list[PackSetupStep]) -> list[PackSetupStep]:
    seen: set[str] = set()
    unique: list[PackSetupStep] = []
    for step in steps:
        if step.step_id in seen:
            continue
        seen.add(step.step_id)
        unique.append(step)
    return unique


def _run_status(applied: list[str], skipped: list[str], blocked: list[str], errors: list[str]) -> str:
    if errors:
        return "failed"
    if blocked and not applied:
        return "blocked"
    if blocked or skipped:
        return "partial"
    return "applied"


def _run_summary(applied: list[str], skipped: list[str], blocked: list[str]) -> list[str]:
    return [
        f"applied: {len(applied)}",
        f"skipped: {len(skipped)}",
        f"blocked: {len(blocked)}",
    ]


def _plan_from_dict(payload: dict[str, Any]) -> PackSetupPlan:
    return PackSetupPlan(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        plan_id=str(payload.get("plan_id") or ""),
        generated_at=str(payload.get("generated_at") or _now()),
        pack_ref=str(payload.get("pack_ref")) if payload.get("pack_ref") is not None else None,
        pack_id=str(payload.get("pack_id")) if payload.get("pack_id") is not None else None,
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        source_readiness_ref=str(payload.get("source_readiness_ref")) if payload.get("source_readiness_ref") is not None else None,
        readiness_status=str(payload.get("readiness_status")) if payload.get("readiness_status") is not None else None,
        fit_status=str(payload.get("fit_status")) if payload.get("fit_status") is not None else None,
        steps=[
            PackSetupStep(
                step_id=str(item.get("step_id") or ""),
                title=str(item.get("title") or ""),
                action_kind=str(item.get("action_kind") or "informational"),
                status=str(item.get("status") or "todo"),
                command=str(item.get("command")) if item.get("command") is not None else None,
                reason=str(item.get("reason") or ""),
                safety_note=str(item.get("safety_note")) if item.get("safety_note") is not None else None,
                source_check_id=str(item.get("source_check_id")) if item.get("source_check_id") is not None else None,
                warnings=_as_list(item.get("warnings")),
                errors=_as_list(item.get("errors")),
            )
            for item in payload.get("steps", []) or []
            if isinstance(item, dict)
        ],
        safe_apply_available=bool(payload.get("safe_apply_available", False)),
        blocked=bool(payload.get("blocked", False)),
        summary=_as_list(payload.get("summary")),
        next_actions=_as_list(payload.get("next_actions")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else None,
    )


def _pack_id_from_ref(pack_ref: str | None) -> str | None:
    if not pack_ref:
        return None
    raw = str(pack_ref).strip()
    if "/" in raw:
        raw = raw.rsplit("/", 1)[1]
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    return raw or None


def _project_root_from_setup_path(path: Path) -> Path:
    parts = list(path.resolve().parts)
    if ".cambrian" in parts:
        return Path(*parts[: parts.index(".cambrian")])
    return path.resolve().parent


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
