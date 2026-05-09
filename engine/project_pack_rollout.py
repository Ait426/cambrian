"""Pack local release rollout과 안전한 업그레이드 경로."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_activation import PackActivator, current_active_pack
from engine.project_pack_catalog import PackCatalogEntry, PackCatalogResolver, PackCatalogStore, default_pack_catalog_path
from engine.project_pack_install import (
    SCHEMA_VERSION,
    InstalledPackRecord,
    InstalledPackStore,
    PackManifest,
    PackManifestLoader,
    default_installed_packs_path,
    _as_dict,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)
from engine.project_pack_install import PackInstaller
from engine.project_pack_readiness import PackReadinessBuilder
from engine.project_pack_release_candidate import (
    PackLocalReleaseRecord,
    PackReleaseCandidate,
    PackReleaseCandidateStore,
    default_pack_local_releases_dir,
    latest_pack_local_release,
    latest_pack_rc,
)

logger = logging.getLogger(__name__)


@dataclass
class PackRolloutStep:
    """Rollout에서 사람이 검토하거나 명시 실행할 단일 단계."""

    step_id: str
    title: str
    action_kind: str
    status: str
    command: str | None
    requires_confirm: bool
    reason: str
    safety_note: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackRolloutPlan:
    """새 local release를 현재 프로젝트에 도입할지 판단하는 계획."""

    schema_version: str
    rollout_id: str
    generated_at: str
    updated_at: str | None
    new_pack_ref: str
    new_pack_id: str
    new_pack_name: str | None
    new_version: str | None
    namespace: str | None
    previous_pack_ref: str | None
    previous_pack_id: str | None
    previous_version: str | None
    current_active_pack_ref: str | None
    current_active_pack_id: str | None
    local_release_ref: str | None
    release_candidate_ref: str | None
    new_pack_installed: bool
    new_pack_active: bool
    previous_pack_installed: bool
    previous_pack_active: bool
    proof_comparison: dict[str, Any] = field(default_factory=dict)
    readiness_summary: dict[str, Any] = field(default_factory=dict)
    changelog: list[str] = field(default_factory=list)
    known_limits: list[str] = field(default_factory=list)
    rollout_recommendation: str = "install_only"
    steps: list[PackRolloutStep] = field(default_factory=list)
    rollback_hint: str | None = None
    status: str = "planned"
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


@dataclass
class PackRolloutApplyRecord:
    """rollout-apply preview/confirm 실행 기록."""

    schema_version: str
    apply_id: str
    created_at: str
    rollout_ref: str
    new_pack_ref: str
    previous_pack_ref: str | None
    confirm: bool
    install_requested: bool
    activate_requested: bool
    mark_old_backup: bool
    applied_steps: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
    blocked_steps: list[str] = field(default_factory=list)
    status: str = "preview"
    resulting_active_pack_ref: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        return asdict(self)


class PackRolloutPlanner:
    """새 pack release의 안전 rollout plan을 만든다."""

    def build(self, project_root: Path, new_pack_ref: str) -> PackRolloutPlan:
        """새 release와 현재 프로젝트 상태를 비교해 rollout plan을 만든다."""
        root = Path(project_root).resolve()
        requested_ref = str(new_pack_ref or "").strip()
        rollout_id = f"pack-rollout-{_slug(_plain_pack_id(requested_ref), 'pack')}-{_stamp()}"
        warnings: list[str] = []
        errors: list[str] = []
        resolved = _resolve_new_pack(root, requested_ref, warnings, errors)
        active = current_active_pack(root)
        if resolved is None:
            plan = _blocked_plan(root, rollout_id, requested_ref, active, errors or [f"new pack not found: {requested_ref}"])
            return plan

        manifest: PackManifest = resolved["manifest"]
        release: PackLocalReleaseRecord | None = resolved.get("local_release")
        rc: PackReleaseCandidate | None = resolved.get("release_candidate")
        new_record = _find_installed(root, manifest.pack_id)
        previous_ref = _previous_ref(root, manifest, release, rc, active)
        previous_record = _find_installed(root, previous_ref) if previous_ref else None
        current_active_id = active.pack_id if active is not None and active.status == "active" else None
        new_active = bool(current_active_id and _pack_matches(manifest.pack_id, current_active_id))
        previous_active = bool(previous_record and current_active_id and _pack_matches(previous_record.pack_id, current_active_id))
        readiness = _readiness_summary(root, manifest.pack_id, warnings)
        proof = _proof_comparison(root, previous_record, manifest.pack_id, release, rc)
        changelog = _changelog(release, rc)
        known_limits = _known_limits(manifest, release, rc)
        recommendation = _recommendation(
            manifest.pack_id,
            new_record,
            new_active,
            previous_active,
            release,
            rc,
            readiness,
            warnings,
        )
        status = "blocked" if recommendation == "blocked" else "planned"
        if status == "blocked" and not errors:
            errors.append("rollout is blocked by release/readiness state")
        rollback_hint = _rollback_hint(previous_record, previous_ref, new_active, recommendation)
        steps = _rollout_steps(
            rollout_id,
            manifest.pack_id,
            previous_record,
            bool(new_record),
            new_active,
            recommendation,
        )
        summary = _summary_lines(manifest.pack_id, current_active_id, recommendation, release, rc, readiness)
        next_actions = _next_actions(rollout_id, recommendation, bool(new_record), new_active)
        return PackRolloutPlan(
            schema_version=SCHEMA_VERSION,
            rollout_id=rollout_id,
            generated_at=_now(),
            updated_at=None,
            new_pack_ref=_target_pack_ref(manifest),
            new_pack_id=manifest.pack_id,
            new_pack_name=manifest.pack_name,
            new_version=manifest.version,
            namespace=manifest.namespace,
            previous_pack_ref=_record_ref(previous_record) if previous_record else previous_ref,
            previous_pack_id=previous_record.pack_id if previous_record else _plain_pack_id(previous_ref),
            previous_version=previous_record.version if previous_record else None,
            current_active_pack_ref=active.pack_ref if active is not None else None,
            current_active_pack_id=current_active_id,
            local_release_ref=_release_ref(root, release),
            release_candidate_ref=_rc_ref(root, rc),
            new_pack_installed=bool(new_record and new_record.status != "uninstalled"),
            new_pack_active=new_active,
            previous_pack_installed=bool(previous_record and previous_record.status != "uninstalled"),
            previous_pack_active=previous_active,
            proof_comparison=proof,
            readiness_summary=readiness,
            changelog=changelog,
            known_limits=known_limits,
            rollout_recommendation=recommendation,
            steps=steps,
            rollback_hint=rollback_hint,
            status=status,
            summary=summary,
            next_actions=next_actions,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )


class PackRolloutApplier:
    """rollout plan의 안전한 Cambrian-state 단계만 명시 적용한다."""

    def apply(
        self,
        project_root: Path,
        rollout_ref: str,
        confirm: bool = False,
        install: bool = False,
        activate: bool = False,
        mark_old_backup: bool = False,
    ) -> PackRolloutApplyRecord:
        """설치/활성화는 confirm이 있을 때만 기존 경로로 실행한다."""
        root = Path(project_root).resolve()
        plan_path = resolve_pack_rollout_path(root, rollout_ref)
        store = PackRolloutStore()
        plan = store.load_plan(plan_path)
        warnings = list(plan.warnings)
        errors = list(plan.errors)
        applied: list[str] = []
        skipped: list[str] = []
        blocked: list[str] = []
        if not confirm:
            status = "preview"
            skipped = _requested_step_ids(install, activate, mark_old_backup)
            active = current_active_pack(root)
            return _apply_record(root, plan_path, plan, confirm, install, activate, mark_old_backup, applied, skipped, blocked, status, active, warnings, errors)

        if plan.status == "blocked":
            blocked.append("rollout_blocked")
            errors.append("rollout plan is blocked")
            active = current_active_pack(root)
            return _apply_record(root, plan_path, plan, confirm, install, activate, mark_old_backup, applied, skipped, blocked, "blocked", active, warnings, errors)

        installed = _find_installed(root, plan.new_pack_id)
        if install:
            if installed is not None and installed.status != "uninstalled":
                skipped.append("install_new_pack")
            else:
                manifest_path = _manifest_path_for_plan(root, plan)
                if manifest_path is None:
                    blocked.append("install_new_pack")
                    errors.append("new pack manifest was not found for rollout install")
                else:
                    try:
                        install_plan = PackInstaller().install(
                            root,
                            manifest_path,
                            source_kind_override="local_rollout",
                            source_ref_override=plan.local_release_ref or plan.release_candidate_ref or plan.new_pack_ref,
                            expected_sha256=_manifest_sha_for_plan(root, plan),
                            trust_level_override="local",
                        )
                        if install_plan.safe_to_install:
                            applied.append("install_new_pack")
                            installed = _find_installed(root, plan.new_pack_id)
                        else:
                            blocked.append("install_new_pack")
                            errors.extend(install_plan.errors or ["install plan is not safe"])
                    except (FileNotFoundError, ValueError, KeyError) as exc:
                        logger.warning("pack rollout install failed: %s", exc)
                        blocked.append("install_new_pack")
                        errors.append(str(exc))
        elif not install and activate:
            installed = _find_installed(root, plan.new_pack_id)

        if activate:
            installed = installed or _find_installed(root, plan.new_pack_id)
            if installed is None or installed.status == "uninstalled":
                blocked.append("activate_new_pack")
                errors.append("new pack must be installed before activation")
            else:
                try:
                    PackActivator().activate(root, plan.new_pack_id)
                    applied.append("activate_new_pack")
                except (KeyError, ValueError, FileNotFoundError) as exc:
                    logger.warning("pack rollout activation failed: %s", exc)
                    blocked.append("activate_new_pack")
                    errors.append(str(exc))
        if mark_old_backup:
            applied.append("mark_old_backup")
            warnings.append("old pack backup/supersede marker is recorded in rollout run only; old pack is preserved")

        active = current_active_pack(root)
        if blocked and applied:
            status = "partial"
        elif blocked:
            status = "blocked"
        elif applied:
            status = "applied"
        else:
            status = "preview"
        _update_plan_after_apply(root, plan, active, status, applied, skipped, blocked)
        store.save_plan(plan, plan_path)
        return _apply_record(root, plan_path, plan, confirm, install, activate, mark_old_backup, applied, skipped, blocked, status, active, warnings, errors)


class PackRolloutStore:
    """rollout plan/run artifact 저장소."""

    def save_plan(self, plan: PackRolloutPlan, path: Path) -> Path:
        """rollout plan을 저장한다."""
        return _save_yaml(Path(path).resolve(), plan.to_dict())

    def load_plan(self, path: Path) -> PackRolloutPlan:
        """rollout plan을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack rollout plan not found: {path}")
        return _plan_from_dict(payload)

    def save_apply_record(self, record: PackRolloutApplyRecord, path: Path) -> Path:
        """rollout apply run을 저장한다."""
        return _save_yaml(Path(path).resolve(), record.to_dict())

    def load_apply_record(self, path: Path) -> PackRolloutApplyRecord:
        """rollout apply run을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack rollout apply record not found: {path}")
        return _apply_from_dict(payload)


def default_pack_rollout_plans_dir(project_root: Path) -> Path:
    """rollout plan 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "rollouts" / "plans"


def default_pack_rollout_runs_dir(project_root: Path) -> Path:
    """rollout run 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "rollouts" / "runs"


def default_pack_rollout_latest_path(project_root: Path) -> Path:
    """latest rollout plan pointer 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "rollouts" / "latest.yaml"


def default_pack_rollout_path(project_root: Path, plan: PackRolloutPlan) -> Path:
    """rollout plan 기본 저장 경로를 반환한다."""
    return default_pack_rollout_plans_dir(project_root) / f"rollout_{_slug(plan.new_pack_id)}_{_stamp()}.yaml"


def default_pack_rollout_run_path(project_root: Path, record: PackRolloutApplyRecord) -> Path:
    """rollout apply run 기본 저장 경로를 반환한다."""
    return default_pack_rollout_runs_dir(project_root) / f"rollout_run_{_slug(record.new_pack_ref)}_{_stamp()}.yaml"


def save_pack_rollout_plan(project_root: Path, plan: PackRolloutPlan) -> str:
    """rollout plan을 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    store = PackRolloutStore()
    path = store.save_plan(plan, default_pack_rollout_path(root, plan))
    try:
        store.save_plan(plan, default_pack_rollout_latest_path(root))
    except Exception as exc:  # noqa: BLE001 - latest pointer 실패는 plan 생성을 막지 않는다.
        logger.warning("latest rollout save failed: %s", exc)
    return _relative(path, root)


def save_pack_rollout_apply_record(project_root: Path, record: PackRolloutApplyRecord) -> str:
    """rollout apply run을 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = PackRolloutStore().save_apply_record(record, default_pack_rollout_run_path(root, record))
    return _relative(path, root)


def resolve_pack_rollout_path(project_root: Path, rollout_ref: str) -> Path:
    """rollout id/path/latest를 실제 파일 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw_ref = str(rollout_ref or "").strip()
    if not raw_ref:
        raise FileNotFoundError("pack rollout ref is required")
    if raw_ref == "latest" and default_pack_rollout_latest_path(root).exists():
        return default_pack_rollout_latest_path(root).resolve()
    raw = Path(raw_ref)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend(
            [
                root / raw,
                default_pack_rollout_plans_dir(root) / raw,
                default_pack_rollout_plans_dir(root) / f"{raw}.yaml",
                default_pack_rollout_plans_dir(root) / f"{_slug(raw_ref)}.yaml",
            ]
        )
    for path in candidates:
        if path.exists():
            return path.resolve()
    plans_dir = default_pack_rollout_plans_dir(root)
    if plans_dir.exists():
        for path in sorted(plans_dir.glob("rollout_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = _load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("rollout resolve skipped: %s", exc)
                continue
            if str(payload.get("rollout_id") or "") == raw_ref:
                return path.resolve()
    raise FileNotFoundError(f"pack rollout plan not found: {rollout_ref}")


def latest_pack_rollout(project_root: Path, pack_ref: str | None = None) -> PackRolloutPlan | None:
    """특정 pack 또는 전체 최신 rollout plan을 반환한다."""
    root = Path(project_root).resolve()
    plans_dir = default_pack_rollout_plans_dir(root)
    candidates: list[Path] = []
    if plans_dir.exists():
        candidates.extend(sorted(plans_dir.glob("rollout_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
    latest = default_pack_rollout_latest_path(root)
    if latest.exists():
        candidates.append(latest)
    seen: set[str] = set()
    store = PackRolloutStore()
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            plan = store.load_plan(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rollout load skipped: %s", exc)
            continue
        if pack_ref is None or _plan_matches(plan, pack_ref):
            return plan
    return None


def render_pack_rollout_plan(plan: PackRolloutPlan) -> str:
    """rollout plan을 콘솔 출력용으로 렌더링한다."""
    lines = [
        "Pack Rollout Plan",
        "==================================================",
        "",
        "New release:",
        f"  {_pack_version_text(plan.new_pack_id, plan.new_version)}",
        "",
        "Current active:",
        f"  {_pack_version_text(plan.current_active_pack_id, None)}",
        "",
        "Previous pack:",
        f"  {_pack_version_text(plan.previous_pack_id, plan.previous_version)}",
        "",
        "Recommendation:",
        f"  {plan.rollout_recommendation}",
    ]
    if plan.summary:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {item}" for item in plan.summary])
    if plan.changelog:
        lines.extend(["", "Changelog:"])
        lines.extend([f"  - {item}" for item in plan.changelog])
    if plan.readiness_summary:
        lines.extend(["", "Readiness:"])
        lines.append(f"  new      : {plan.readiness_summary.get('new_status', 'unknown')}")
        if plan.readiness_summary.get("previous_status"):
            lines.append(f"  previous : {plan.readiness_summary.get('previous_status')}")
    if plan.steps:
        lines.extend(["", "Steps:"])
        for step in plan.steps:
            lines.append(f"  - {step.title} [{step.status}]")
            if step.command:
                lines.append(f"    command: {step.command}")
    if plan.rollback_hint:
        lines.extend(["", "Rollback:", f"  {plan.rollback_hint}"])
    if plan.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in plan.next_actions])
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in plan.warnings])
    if plan.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in plan.errors])
    return "\n".join(lines)


def render_pack_rollout_apply_record(record: PackRolloutApplyRecord) -> str:
    """rollout-apply 결과를 렌더링한다."""
    title = "Pack Rollout Preview"
    if record.status == "applied":
        title = "Pack Rollout Applied"
    elif record.status == "partial":
        title = "Pack Rollout Partially Applied"
    elif record.status == "blocked":
        title = "Pack Rollout Blocked"
    lines = [
        title,
        "==================================================",
        "",
        "Rollout:",
        f"  {record.rollout_ref}",
        "",
        "New pack:",
        f"  {record.new_pack_ref}",
        "",
        "Requested:",
        f"  install : {str(record.install_requested).lower()}",
        f"  activate: {str(record.activate_requested).lower()}",
        f"  confirm : {str(record.confirm).lower()}",
    ]
    if record.applied_steps:
        lines.extend(["", "Applied steps:"])
        lines.extend([f"  - {item}" for item in record.applied_steps])
    if record.skipped_steps:
        lines.extend(["", "Skipped steps:"])
        lines.extend([f"  - {item}" for item in record.skipped_steps])
    if record.blocked_steps:
        lines.extend(["", "Blocked steps:"])
        lines.extend([f"  - {item}" for item in record.blocked_steps])
    if record.resulting_active_pack_ref:
        lines.extend(["", "Active pack:", f"  {record.resulting_active_pack_ref}"])
    if not record.confirm:
        lines.extend(["", "Preview only:", "  실제 install/activate는 --confirm이 필요합니다."])
    if record.previous_pack_ref and record.activate_requested:
        lines.extend(["", "Rollback:", f"  cambrian pack activate {_plain_pack_id(record.previous_pack_ref)}"])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    return "\n".join(lines)


def render_pack_rollout_compact(plan: PackRolloutPlan | None) -> str:
    """pack show용 rollout compact 요약."""
    if plan is None:
        return ""
    return "\n".join(
        [
            "",
            "Rollout:",
            f"  {plan.new_pack_id} -> {plan.status}",
            f"  recommendation: {plan.rollout_recommendation}",
            f"  next: cambrian pack rollout-show {plan.rollout_id}",
        ]
    )


def render_status_pack_rollout(plan: PackRolloutPlan | None) -> str:
    """status용 rollout 요약."""
    if plan is None:
        return ""
    if plan.status == "applied" or plan.new_pack_active:
        return "\n".join(["Pack rollout:", f"  {plan.new_pack_id} applied"])
    if plan.status == "blocked":
        return "\n".join(["Pack rollout:", f"  {plan.new_pack_id} blocked"])
    return "\n".join(["Pack rollout:", f"  {plan.new_pack_id} available", f"  next: cambrian pack rollout-show {plan.rollout_id}"])


def render_pack_upgrade_available(release: PackLocalReleaseRecord | None, active_pack_id: str | None) -> str:
    """active pack 화면에 붙일 새 release 안내."""
    if release is None or release.status != "released":
        return ""
    if active_pack_id and _pack_matches(release.target_pack_id, active_pack_id):
        return ""
    if active_pack_id and release.source_pack_ref and not _pack_matches(release.source_pack_ref, active_pack_id):
        return ""
    return "\n".join(
        [
            "",
            "Upgrade available:",
            f"  {release.target_pack_id}",
            f"  next: cambrian pack rollout {release.target_pack_id}",
        ]
    )


def _resolve_new_pack(root: Path, pack_ref: str, warnings: list[str], errors: list[str]) -> dict[str, Any] | None:
    release = latest_pack_local_release(root, pack_ref)
    if release is not None and _pack_matches(release.target_pack_id, pack_ref):
        manifest = _load_manifest(root, release.manifest_ref)
        if manifest is not None:
            rc = _rc_from_release(root, release)
            return {"manifest": manifest, "manifest_ref": release.manifest_ref, "manifest_sha256": release.manifest_sha256, "local_release": release, "release_candidate": rc}
    catalog_resolved = _resolve_from_catalog(root, pack_ref)
    if catalog_resolved is not None:
        return catalog_resolved
    record = _find_installed(root, pack_ref)
    if record is not None and record.latest_manifest_ref:
        manifest = _load_manifest(root, record.latest_manifest_ref)
        if manifest is not None:
            return {"manifest": manifest, "manifest_ref": record.latest_manifest_ref, "manifest_sha256": record.manifest_sha256, "installed_record": record}
    rc = latest_pack_rc(root, pack_ref)
    if rc is not None and rc.manifest_ref:
        manifest = _load_manifest(root, rc.manifest_ref)
        if manifest is not None:
            return {"manifest": manifest, "manifest_ref": rc.manifest_ref, "manifest_sha256": rc.manifest_sha256, "release_candidate": rc}
    errors.append(f"new pack release not found: {pack_ref}")
    return None


def _resolve_from_catalog(root: Path, pack_ref: str) -> dict[str, Any] | None:
    resolver = PackCatalogResolver()
    for catalog_root in [root, Path(__file__).resolve().parents[1]]:
        catalog_path = default_pack_catalog_path(catalog_root)
        if not catalog_path.exists():
            continue
        catalog = PackCatalogStore().load(catalog_path)
        try:
            entry = resolver.find_entry(catalog, _plain_pack_id(pack_ref))
        except KeyError:
            continue
        manifest_path = resolver.resolve_manifest_path(catalog_root, entry)
        manifest = PackManifestLoader().load(manifest_path)
        return {
            "manifest": manifest,
            "manifest_ref": _relative(manifest_path, root),
            "manifest_sha256": entry.manifest_sha256,
            "catalog_entry": entry,
        }
    return None


def _load_manifest(root: Path, manifest_ref: str | None) -> PackManifest | None:
    if not manifest_ref:
        return None
    path = Path(str(manifest_ref))
    if not path.is_absolute():
        path = root / path
    try:
        return PackManifestLoader().load(path)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("rollout manifest load failed: %s", exc)
        return None


def _manifest_path_for_plan(root: Path, plan: PackRolloutPlan) -> Path | None:
    release = latest_pack_local_release(root, plan.new_pack_id)
    manifest_ref = release.manifest_ref if release is not None and release.manifest_ref else None
    if not manifest_ref:
        resolved = _resolve_from_catalog(root, plan.new_pack_id)
        manifest_ref = resolved.get("manifest_ref") if resolved else None
    if not manifest_ref:
        rc = latest_pack_rc(root, plan.new_pack_id)
        manifest_ref = rc.manifest_ref if rc is not None else None
    if not manifest_ref:
        return None
    path = Path(str(manifest_ref))
    return path if path.is_absolute() else (root / path).resolve()


def _manifest_sha_for_plan(root: Path, plan: PackRolloutPlan) -> str | None:
    release = latest_pack_local_release(root, plan.new_pack_id)
    if release is not None and release.manifest_sha256:
        return release.manifest_sha256
    rc = latest_pack_rc(root, plan.new_pack_id)
    if rc is not None and rc.manifest_sha256:
        return rc.manifest_sha256
    resolved = _resolve_from_catalog(root, plan.new_pack_id)
    return str(resolved.get("manifest_sha256")) if resolved and resolved.get("manifest_sha256") else None


def _previous_ref(
    root: Path,
    manifest: PackManifest,
    release: PackLocalReleaseRecord | None,
    rc: PackReleaseCandidate | None,
    active: Any | None,
) -> str | None:
    if release is not None and release.source_pack_ref:
        return release.source_pack_ref
    if rc is not None and rc.source_pack_ref:
        return rc.source_pack_ref
    derivative = _as_dict(_load_manifest_payload(root, manifest).get("derivative"))
    if derivative.get("source_pack_ref"):
        return str(derivative.get("source_pack_ref"))
    if active is not None and _same_family(active.pack_id, manifest.pack_id):
        return active.pack_id
    return None


def _load_manifest_payload(root: Path, manifest: PackManifest) -> dict[str, Any]:
    for ref in [manifest.source.get("origin_ref") if manifest.source else None, manifest.source.get("path") if manifest.source else None]:
        if not ref:
            continue
        path = Path(str(ref))
        if not path.is_absolute():
            path = root / path
        if path.exists():
            try:
                return _load_yaml(path)
            except ValueError as exc:
                logger.warning("rollout manifest payload load failed: %s", exc)
    return {}


def _readiness_summary(root: Path, new_pack_id: str, warnings: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"new_status": "unknown", "previous_status": None}
    try:
        report = PackReadinessBuilder().build(root, new_pack_id)
        summary["new_status"] = report.readiness_status
        summary["new_fit"] = report.fit_status
        summary["new_installed"] = report.installed
    except Exception as exc:  # noqa: BLE001 - rollout은 readiness가 없어도 install-only 안내 가능해야 한다.
        logger.warning("rollout readiness lookup failed: %s", exc)
        warnings.append("new pack readiness is unknown")
    return summary


def _proof_comparison(
    root: Path,
    previous_record: InstalledPackRecord | None,
    new_pack_id: str,
    release: PackLocalReleaseRecord | None,
    rc: PackReleaseCandidate | None,
) -> dict[str, Any]:
    comparison: dict[str, Any] = {
        "previous_pack_id": previous_record.pack_id if previous_record else None,
        "new_pack_id": new_pack_id,
        "new_has_local_outcomes": False,
        "notes": [],
    }
    try:
        from engine.project_pack_proof import latest_pack_proof_card

        previous_proof = latest_pack_proof_card(root, previous_record.pack_id) if previous_record else None
        new_proof = latest_pack_proof_card(root, new_pack_id)
        comparison["previous_verdict"] = getattr(previous_proof, "reputation_verdict", None)
        comparison["new_verdict"] = getattr(new_proof, "reputation_verdict", None)
        comparison["new_has_local_outcomes"] = bool(new_proof and int(getattr(new_proof, "outcome_linked_count", 0) or 0) > 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rollout proof lookup failed: %s", exc)
        comparison["notes"].append("proof comparison unavailable")
    if not comparison.get("new_has_local_outcomes"):
        comparison["notes"].append("new pack has no local outcomes yet; rollout uses release/workorder evidence")
    if release is not None:
        comparison["local_release_status"] = release.status
    if rc is not None:
        comparison["release_candidate_status"] = rc.status
        comparison["release_candidate_safe"] = rc.safe_to_release_local
    return comparison


def _changelog(release: PackLocalReleaseRecord | None, rc: PackReleaseCandidate | None) -> list[str]:
    if rc is not None and rc.changelog:
        return list(rc.changelog)
    if release is not None:
        return list(release.summary)
    return []


def _known_limits(manifest: PackManifest, release: PackLocalReleaseRecord | None, rc: PackReleaseCandidate | None) -> list[str]:
    limits = list(manifest.warnings)
    if rc is not None:
        limits.extend(rc.known_limits)
        limits.extend(rc.warnings)
    if release is not None:
        limits.extend(release.warnings)
    return _dedupe(limits)


def _recommendation(
    new_pack_id: str,
    new_record: InstalledPackRecord | None,
    new_active: bool,
    previous_active: bool,
    release: PackLocalReleaseRecord | None,
    rc: PackReleaseCandidate | None,
    readiness: dict[str, Any],
    warnings: list[str],
) -> str:
    if new_active:
        return "already_active"
    if release is None and rc is None and new_record is None:
        return "blocked"
    if rc is not None and rc.status == "candidate" and not rc.safe_to_release_local:
        return "wait"
    if release is not None and release.status not in {"released", "preview"}:
        return "blocked"
    readiness_status = str(readiness.get("new_status") or "unknown")
    if readiness_status in {"unsupported"}:
        return "blocked"
    if new_record is None and previous_active and release is not None and release.status == "released":
        if readiness_status in {"ready", "partial", "blocked", "unknown"}:
            return "install_and_activate"
    if new_record is None:
        return "install_only" if readiness_status in {"unknown", "partial", "blocked"} else "wait"
    if previous_active and readiness_status in {"ready", "partial", "unknown"}:
        return "install_and_activate"
    if warnings:
        return "wait"
    return "install_only"


def _rollout_steps(
    rollout_id: str,
    new_pack_id: str,
    previous_record: InstalledPackRecord | None,
    new_installed: bool,
    new_active: bool,
    recommendation: str,
) -> list[PackRolloutStep]:
    steps = [
        PackRolloutStep(
            step_id="install_new_pack",
            title="Install new pack",
            action_kind="install_new_pack",
            status="done" if new_installed else ("blocked" if recommendation == "blocked" else "todo"),
            command=f"cambrian pack rollout-apply {rollout_id} --confirm --install",
            requires_confirm=True,
            reason="새 local release를 현재 프로젝트 `.cambrian` install state에 추가합니다.",
            safety_note="source code는 수정하지 않고 pack install state만 갱신합니다.",
        ),
        PackRolloutStep(
            step_id="doctor_new_pack",
            title="Run pack doctor for new pack",
            action_kind="doctor_new_pack",
            status="todo" if not new_active else "done",
            command=f"cambrian pack doctor {new_pack_id} --save",
            requires_confirm=False,
            reason="활성화 전에 project fit/readiness를 다시 확인합니다.",
            safety_note="read-only doctor artifact만 생성합니다.",
        ),
        PackRolloutStep(
            step_id="activate_new_pack",
            title="Activate new pack explicitly",
            action_kind="activate_new_pack",
            status="done" if new_active else ("blocked" if recommendation in {"blocked", "wait"} else "todo"),
            command=f"cambrian pack rollout-apply {rollout_id} --confirm --activate",
            requires_confirm=True,
            reason="사용자가 승인할 때만 active pack을 새 pack으로 바꿉니다.",
            safety_note="old pack은 uninstall하지 않고 rollback 후보로 보존합니다.",
        ),
    ]
    if previous_record is not None:
        steps.append(
            PackRolloutStep(
                step_id="mark_old_backup",
                title="Record old pack as rollback candidate",
                action_kind="mark_old_backup",
                status="todo",
                command=f"cambrian pack rollout-apply {rollout_id} --confirm --mark-old-backup",
                requires_confirm=True,
                reason="이전 pack을 rollback baseline으로 명시 기록합니다.",
                safety_note="old pack을 삭제하거나 비활성화하지 않습니다.",
            )
        )
    return steps


def _summary_lines(
    new_pack_id: str,
    current_active_id: str | None,
    recommendation: str,
    release: PackLocalReleaseRecord | None,
    rc: PackReleaseCandidate | None,
    readiness: dict[str, Any],
) -> list[str]:
    lines = []
    if release is not None and release.status == "released":
        lines.append("local release is available")
    if rc is not None and rc.status == "release_ready":
        lines.append("release candidate passed local release gates")
    if current_active_id:
        lines.append(f"current active pack is {current_active_id}")
    if readiness.get("new_status"):
        lines.append(f"new pack readiness is {readiness.get('new_status')}")
    if recommendation == "install_and_activate":
        lines.append("recommended path is explicit install followed by explicit activation")
    if recommendation == "wait":
        lines.append("wait before activation because proof/readiness evidence is not strong enough")
    if recommendation == "already_active":
        lines.append(f"{new_pack_id} is already active")
    return lines


def _next_actions(rollout_id: str, recommendation: str, new_installed: bool, new_active: bool) -> list[str]:
    if recommendation == "blocked":
        return [f"cambrian pack rollout-show {rollout_id}"]
    if new_active or recommendation == "already_active":
        return [f"cambrian pack active", f"cambrian pack proof latest"]
    if recommendation == "install_and_activate":
        if new_installed:
            return [f"cambrian pack rollout-apply {rollout_id} --confirm --activate"]
        return [f"cambrian pack rollout-apply {rollout_id} --confirm --install --activate"]
    if recommendation == "install_only":
        return [f"cambrian pack rollout-apply {rollout_id} --confirm --install", f"cambrian pack doctor <new-pack> --save"]
    return [f"cambrian pack rollout-show {rollout_id}"]


def _rollback_hint(previous_record: InstalledPackRecord | None, previous_ref: str | None, new_active: bool, recommendation: str) -> str:
    if previous_record is not None:
        return f"cambrian pack activate {previous_record.pack_id}"
    if recommendation in {"install_only", "wait"} and not new_active:
        return "no runtime switch is planned; old pack remains active"
    if previous_ref:
        return f"install previous pack from catalog if needed: {previous_ref}"
    return "old pack remains installed if it was installed before rollout"


def _apply_record(
    root: Path,
    plan_path: Path,
    plan: PackRolloutPlan,
    confirm: bool,
    install: bool,
    activate: bool,
    mark_old_backup: bool,
    applied: list[str],
    skipped: list[str],
    blocked: list[str],
    status: str,
    active: Any | None,
    warnings: list[str],
    errors: list[str],
) -> PackRolloutApplyRecord:
    return PackRolloutApplyRecord(
        schema_version=SCHEMA_VERSION,
        apply_id=f"pack-rollout-run-{_slug(plan.new_pack_id)}-{_stamp()}",
        created_at=_now(),
        rollout_ref=_relative(plan_path, root),
        new_pack_ref=plan.new_pack_ref,
        previous_pack_ref=plan.previous_pack_ref,
        confirm=confirm,
        install_requested=install,
        activate_requested=activate,
        mark_old_backup=mark_old_backup,
        applied_steps=_dedupe(applied),
        skipped_steps=_dedupe(skipped),
        blocked_steps=_dedupe(blocked),
        status=status,
        resulting_active_pack_ref=(active.pack_ref or active.pack_id) if active is not None else None,
        warnings=_dedupe(warnings),
        errors=_dedupe(errors),
    )


def _update_plan_after_apply(
    root: Path,
    plan: PackRolloutPlan,
    active: Any | None,
    status: str,
    applied: list[str],
    skipped: list[str],
    blocked: list[str],
) -> None:
    plan.updated_at = _now()
    plan.status = "applied" if status == "applied" else ("partially_applied" if status == "partial" else status)
    plan.new_pack_installed = _find_installed(root, plan.new_pack_id) is not None
    plan.current_active_pack_ref = (active.pack_ref or active.pack_id) if active is not None else plan.current_active_pack_ref
    plan.current_active_pack_id = active.pack_id if active is not None else plan.current_active_pack_id
    plan.new_pack_active = bool(active is not None and _pack_matches(active.pack_id, plan.new_pack_id))
    for step in plan.steps:
        if step.step_id in applied:
            step.status = "done"
        elif step.step_id in skipped:
            step.status = "skipped"
        elif step.step_id in blocked:
            step.status = "blocked"


def _requested_step_ids(install: bool, activate: bool, mark_old_backup: bool) -> list[str]:
    ids = []
    if install:
        ids.append("install_new_pack")
    if activate:
        ids.append("activate_new_pack")
    if mark_old_backup:
        ids.append("mark_old_backup")
    return ids


def _find_installed(root: Path, pack_ref: str | None) -> InstalledPackRecord | None:
    if not pack_ref:
        return None
    index = InstalledPackStore().load(default_installed_packs_path(root))
    try:
        record = InstalledPackStore().find(index, _plain_pack_id(pack_ref))
    except KeyError:
        return None
    return record if record.status != "uninstalled" else None


def _blocked_plan(root: Path, rollout_id: str, new_pack_ref: str, active: Any | None, errors: list[str]) -> PackRolloutPlan:
    step = PackRolloutStep(
        step_id="new_pack_missing",
        title="Resolve new pack",
        action_kind="blocked",
        status="blocked",
        command=f"cambrian pack list",
        requires_confirm=False,
        reason="새 pack release를 local catalog/install state에서 찾지 못했습니다.",
        safety_note="rollout은 pack을 찾기 전에는 아무 상태도 변경하지 않습니다.",
        errors=list(errors),
    )
    return PackRolloutPlan(
        schema_version=SCHEMA_VERSION,
        rollout_id=rollout_id,
        generated_at=_now(),
        updated_at=None,
        new_pack_ref=new_pack_ref,
        new_pack_id=_plain_pack_id(new_pack_ref) or new_pack_ref,
        new_pack_name=None,
        new_version=None,
        namespace=None,
        previous_pack_ref=None,
        previous_pack_id=None,
        previous_version=None,
        current_active_pack_ref=active.pack_ref if active is not None else None,
        current_active_pack_id=active.pack_id if active is not None else None,
        local_release_ref=None,
        release_candidate_ref=None,
        new_pack_installed=False,
        new_pack_active=False,
        previous_pack_installed=False,
        previous_pack_active=False,
        proof_comparison={"notes": ["new pack not found"]},
        readiness_summary={"new_status": "unknown"},
        rollout_recommendation="blocked",
        steps=[step],
        rollback_hint="no runtime switch is planned; old pack remains active",
        status="blocked",
        summary=["new pack release was not found"],
        next_actions=["cambrian pack list"],
        errors=_dedupe(errors),
    )


def _rc_from_release(root: Path, release: PackLocalReleaseRecord | None) -> PackReleaseCandidate | None:
    if release is None or not release.rc_ref:
        return None
    try:
        rc_path = Path(release.rc_ref)
        if not rc_path.is_absolute():
            rc_path = root / rc_path
        return PackReleaseCandidateStore().load_rc(rc_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rollout RC lookup from release failed: %s", exc)
        return latest_pack_rc(root, release.target_pack_id)


def _release_ref(root: Path, release: PackLocalReleaseRecord | None) -> str | None:
    if release is None:
        return None
    releases_dir = default_pack_local_releases_dir(root)
    if releases_dir.exists():
        for path in sorted(releases_dir.glob("release_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = _load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("rollout release ref lookup skipped: %s", exc)
                continue
            if str(payload.get("release_id") or "") == release.release_id:
                return _relative(path, root)
    return release.release_id


def _rc_ref(root: Path, rc: PackReleaseCandidate | None) -> str | None:
    if rc is None:
        return None
    candidates_dir = root / ".cambrian" / "packs" / "releases" / "candidates"
    if candidates_dir.exists():
        for path in sorted(candidates_dir.glob("rc_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = _load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("rollout RC ref lookup skipped: %s", exc)
                continue
            if str(payload.get("rc_id") or "") == rc.rc_id:
                return _relative(path, root)
    return rc.rc_id


def _record_ref(record: InstalledPackRecord | None) -> str | None:
    if record is None:
        return None
    return f"{record.pack_id}@{record.version}" if record.version else record.pack_id


def _target_pack_ref(manifest: PackManifest) -> str:
    base = f"{manifest.namespace}/{manifest.pack_id}" if manifest.namespace else manifest.pack_id
    return f"{base}@{manifest.version}" if manifest.version else base


def _plain_pack_id(pack_ref: str | None) -> str | None:
    text = str(pack_ref or "").strip()
    if not text:
        return None
    text = text.split("#", 1)[0]
    text = text.rsplit("/", 1)[-1]
    return text.split("@", 1)[0]


def _pack_matches(candidate: str | None, ref: str | None) -> bool:
    if not candidate or not ref:
        return False
    return _plain_pack_id(candidate) == _plain_pack_id(ref)


def _same_family(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    left_id = _plain_pack_id(left) or ""
    right_id = _plain_pack_id(right) or ""
    return left_id == right_id or right_id.startswith(f"{left_id}-") or left_id.startswith(f"{right_id}-")


def _plan_matches(plan: PackRolloutPlan, pack_ref: str) -> bool:
    targets = [
        plan.new_pack_id,
        plan.new_pack_ref,
        plan.previous_pack_id,
        plan.previous_pack_ref,
        plan.current_active_pack_id,
        plan.current_active_pack_ref,
    ]
    return any(_pack_matches(item, pack_ref) for item in targets if item)


def _pack_version_text(pack_id: str | None, version: str | None) -> str:
    if not pack_id:
        return "none"
    return f"{pack_id}@{version}" if version else pack_id


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _step_from_dict(payload: dict[str, Any]) -> PackRolloutStep:
    return PackRolloutStep(
        step_id=str(payload.get("step_id") or ""),
        title=str(payload.get("title") or ""),
        action_kind=str(payload.get("action_kind") or "informational"),
        status=str(payload.get("status") or "todo"),
        command=str(payload.get("command")) if payload.get("command") is not None else None,
        requires_confirm=bool(payload.get("requires_confirm", False)),
        reason=str(payload.get("reason") or ""),
        safety_note=str(payload.get("safety_note")) if payload.get("safety_note") is not None else None,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _plan_from_dict(payload: dict[str, Any]) -> PackRolloutPlan:
    return PackRolloutPlan(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        rollout_id=str(payload.get("rollout_id") or ""),
        generated_at=str(payload.get("generated_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        new_pack_ref=str(payload.get("new_pack_ref") or ""),
        new_pack_id=str(payload.get("new_pack_id") or ""),
        new_pack_name=str(payload.get("new_pack_name")) if payload.get("new_pack_name") is not None else None,
        new_version=str(payload.get("new_version")) if payload.get("new_version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        previous_pack_ref=str(payload.get("previous_pack_ref")) if payload.get("previous_pack_ref") is not None else None,
        previous_pack_id=str(payload.get("previous_pack_id")) if payload.get("previous_pack_id") is not None else None,
        previous_version=str(payload.get("previous_version")) if payload.get("previous_version") is not None else None,
        current_active_pack_ref=str(payload.get("current_active_pack_ref")) if payload.get("current_active_pack_ref") is not None else None,
        current_active_pack_id=str(payload.get("current_active_pack_id")) if payload.get("current_active_pack_id") is not None else None,
        local_release_ref=str(payload.get("local_release_ref")) if payload.get("local_release_ref") is not None else None,
        release_candidate_ref=str(payload.get("release_candidate_ref")) if payload.get("release_candidate_ref") is not None else None,
        new_pack_installed=bool(payload.get("new_pack_installed", False)),
        new_pack_active=bool(payload.get("new_pack_active", False)),
        previous_pack_installed=bool(payload.get("previous_pack_installed", False)),
        previous_pack_active=bool(payload.get("previous_pack_active", False)),
        proof_comparison=_as_dict(payload.get("proof_comparison")),
        readiness_summary=_as_dict(payload.get("readiness_summary")),
        changelog=_as_list(payload.get("changelog")),
        known_limits=_as_list(payload.get("known_limits")),
        rollout_recommendation=str(payload.get("rollout_recommendation") or "install_only"),
        steps=[_step_from_dict(item) for item in payload.get("steps", []) or [] if isinstance(item, dict)],
        rollback_hint=str(payload.get("rollback_hint")) if payload.get("rollback_hint") is not None else None,
        status=str(payload.get("status") or "planned"),
        summary=_as_list(payload.get("summary")),
        next_actions=_as_list(payload.get("next_actions")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _apply_from_dict(payload: dict[str, Any]) -> PackRolloutApplyRecord:
    return PackRolloutApplyRecord(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        apply_id=str(payload.get("apply_id") or ""),
        created_at=str(payload.get("created_at") or _now()),
        rollout_ref=str(payload.get("rollout_ref") or ""),
        new_pack_ref=str(payload.get("new_pack_ref") or ""),
        previous_pack_ref=str(payload.get("previous_pack_ref")) if payload.get("previous_pack_ref") is not None else None,
        confirm=bool(payload.get("confirm", False)),
        install_requested=bool(payload.get("install_requested", False)),
        activate_requested=bool(payload.get("activate_requested", False)),
        mark_old_backup=bool(payload.get("mark_old_backup", False)),
        applied_steps=_as_list(payload.get("applied_steps")),
        skipped_steps=_as_list(payload.get("skipped_steps")),
        blocked_steps=_as_list(payload.get("blocked_steps")),
        status=str(payload.get("status") or "preview"),
        resulting_active_pack_ref=str(payload.get("resulting_active_pack_ref")) if payload.get("resulting_active_pack_ref") is not None else None,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )
