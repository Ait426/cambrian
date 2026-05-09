"""vNext pack release candidate와 명시적 local release closure."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.project_pack_authoring import (
    PackBuilder,
    PackLocalPublisher,
    load_pack_draft,
    resolve_draft_path,
)
from engine.project_pack_derivatives import PackDerivativeStore, PackDerivativeWorkspace
from engine.project_pack_install import SCHEMA_VERSION, _as_dict, _as_list, _load_yaml, _now, _relative, _save_yaml
from engine.project_pack_release import PackReleaseChecker, save_pack_release_report
from engine.project_pack_vnext_workbench import (
    PackVNextWorkbench,
    latest_pack_vnext_workbench,
)

logger = logging.getLogger(__name__)


@dataclass
class PackReleaseCandidate:
    """vNext pack local release 전 freeze snapshot."""

    schema_version: str
    rc_id: str
    created_at: str
    updated_at: str | None
    source_pack_ref: str | None
    source_pack_id: str | None
    source_version: str | None
    target_pack_id: str
    target_pack_name: str | None
    target_version: str | None
    namespace: str | None
    draft_ref: str | None
    derivative_plan_ref: str | None
    derivative_workspace_ref: str | None
    workbench_ref: str | None
    manifest_ref: str | None
    manifest_sha256: str | None
    build_report_ref: str | None
    release_check_ref: str | None
    proof_export_ref: str | None
    workorder_summary: dict[str, Any] = field(default_factory=dict)
    accepted_improvement_refs: list[str] = field(default_factory=list)
    completed_workorder_refs: list[str] = field(default_factory=list)
    unresolved_workorder_refs: list[str] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)
    known_limits: list[str] = field(default_factory=list)
    release_notes: list[str] = field(default_factory=list)
    maturity: str | None = None
    proof_status: str | None = None
    status: str = "candidate"
    safe_to_release_local: bool = False
    requires_confirm: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackLocalReleaseRecord:
    """release-local preview/confirm 결과."""

    schema_version: str
    release_id: str
    created_at: str
    rc_ref: str
    source_pack_ref: str | None
    target_pack_ref: str
    target_pack_id: str
    target_version: str | None
    namespace: str | None
    manifest_ref: str | None
    manifest_sha256: str | None
    catalog_ref: str | None
    publish_record_ref: str | None
    previous_pack_status: str | None
    new_pack_status: str | None
    status: str
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        return asdict(self)


class PackReleaseCandidateBuilder:
    """vNext draft/workspace를 local release candidate로 freeze한다."""

    def build(
        self,
        project_root: Path,
        draft_or_workspace_ref: str,
        allow_unresolved: bool = False,
    ) -> PackReleaseCandidate:
        """draft/workspace를 검사하고 release candidate artifact를 만든다."""
        root = Path(project_root).resolve()
        draft_path, workspace_ref = _resolve_draft_or_workspace(root, draft_or_workspace_ref)
        draft = load_pack_draft(draft_path)
        derivative = _as_dict(draft.derivative)
        plan_ref = str(derivative.get("source_plan_ref") or "").strip() or None
        source_pack_ref = str(derivative.get("source_pack_ref") or "").strip() or None
        accepted_refs = _as_list(derivative.get("accepted_improvements"))
        workbench = _latest_workbench_for_candidate(root, draft.pack_id, source_pack_ref, plan_ref)
        workbench_ref = _workbench_ref(root, workbench)
        summary = _workorder_summary(workbench)
        unresolved_orders = _unresolved_required_orders(workbench)
        completed_orders = _completed_orders(workbench)
        warnings: list[str] = []
        errors: list[str] = []
        if workbench is None:
            warnings.append("vNext workbench was not found for this derivative draft")
        if unresolved_orders and not allow_unresolved:
            errors.append("required vNext workorders are unresolved")
        manifest_ref = None
        manifest_sha256 = None
        build_report_ref = None
        release_check_ref = None
        maturity = None
        proof_status = None
        proof_export_ref = _latest_proof_export_ref(root, draft.pack_id) or _latest_proof_export_ref(root, source_pack_ref)
        if not errors or allow_unresolved:
            out_path = root / "packs" / "generated" / f"{_slug(draft.pack_id, 'pack')}.cambrian-pack.yaml"
            build = PackBuilder().build(root, draft_path, out_path=out_path)
            build_report_ref = build.saved_ref
            if build.status != "built":
                errors.extend(build.errors or ["pack build failed"])
            manifest_ref = build.manifest_ref
            manifest_sha256 = build.manifest_sha256
            if manifest_ref:
                release = PackReleaseChecker().check(root, str(root / manifest_ref))
                release_check_ref = save_pack_release_report(root, release)
                maturity = release.maturity
                proof_status = release.proof_summary.proof_status
                warnings.extend(release.warnings)
                errors.extend(release.errors)
                if not release.safe_to_publish:
                    errors.append("release-check is not safe to publish")
        status = _candidate_status(errors, unresolved_orders, allow_unresolved)
        safe_to_release = status == "release_ready" and bool(manifest_ref and manifest_sha256)
        if allow_unresolved and unresolved_orders:
            warnings.append("unresolved required workorders allowed; candidate is not safe for local release")
        rc = PackReleaseCandidate(
            schema_version=SCHEMA_VERSION,
            rc_id=f"pack-rc-{_slug(draft.pack_id)}-{_stamp()}",
            created_at=_now(),
            updated_at=None,
            source_pack_ref=source_pack_ref,
            source_pack_id=_plain_pack_id(source_pack_ref) if source_pack_ref else None,
            source_version=None,
            target_pack_id=draft.pack_id,
            target_pack_name=draft.pack_name,
            target_version=draft.version,
            namespace=None,
            draft_ref=_relative(draft_path, root),
            derivative_plan_ref=plan_ref,
            derivative_workspace_ref=workspace_ref,
            workbench_ref=workbench_ref,
            manifest_ref=manifest_ref,
            manifest_sha256=manifest_sha256,
            build_report_ref=build_report_ref,
            release_check_ref=release_check_ref,
            proof_export_ref=proof_export_ref,
            workorder_summary=summary,
            accepted_improvement_refs=accepted_refs,
            completed_workorder_refs=[order.workorder_id for order in completed_orders],
            unresolved_workorder_refs=[order.workorder_id for order in unresolved_orders],
            changelog=_changelog(completed_orders),
            known_limits=_known_limits(completed_orders, warnings),
            release_notes=_release_notes(draft.pack_id, source_pack_ref, completed_orders, unresolved_orders),
            maturity=maturity,
            proof_status=proof_status,
            status=status,
            safe_to_release_local=safe_to_release,
            requires_confirm=True,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )
        return rc


class PackLocalReleaser:
    """release candidate를 명시적으로 local catalog에 release한다."""

    def release(
        self,
        project_root: Path,
        rc_ref: str,
        confirm: bool = False,
        supersede_previous: bool = True,
    ) -> PackLocalReleaseRecord:
        """publish-local 경로를 재사용해 RC를 local catalog에 release한다."""
        root = Path(project_root).resolve()
        rc_path = resolve_pack_rc_path(root, rc_ref)
        rc = PackReleaseCandidateStore().load_rc(rc_path)
        warnings = list(rc.warnings)
        errors = list(rc.errors)
        publish_ref = None
        catalog_ref = _relative(_catalog_path(root), root)
        status = "preview"
        new_status = None
        if not rc.safe_to_release_local:
            errors.append("release candidate is not safe for local release")
            status = "blocked"
        elif not rc.manifest_ref:
            errors.append("release candidate has no manifest")
            status = "blocked"
        else:
            publish = PackLocalPublisher().publish(
                root,
                root / rc.manifest_ref,
                confirm=confirm,
                catalog_path=_catalog_path(root),
                release_check_path=(root / rc.release_check_ref) if rc.release_check_ref else None,
            )
            warnings.extend(publish.warnings)
            errors.extend(publish.errors)
            publish_ref = publish.saved_ref
            catalog_ref = publish.catalog_ref
            new_status = publish.status
            if publish.status == "published":
                status = "released"
                rc.status = "released"
                rc.updated_at = _now()
                PackReleaseCandidateStore().save_rc(rc, rc_path)
            elif publish.status == "blocked":
                status = "blocked"
            else:
                status = "preview"
        previous_status = "superseded_recorded" if supersede_previous and rc.source_pack_ref and status in {"preview", "released"} else None
        record = PackLocalReleaseRecord(
            schema_version=SCHEMA_VERSION,
            release_id=f"pack-local-release-{_slug(rc.target_pack_id)}-{_stamp()}",
            created_at=_now(),
            rc_ref=_relative(rc_path, root),
            source_pack_ref=rc.source_pack_ref,
            target_pack_ref=_target_pack_ref(rc),
            target_pack_id=rc.target_pack_id,
            target_version=rc.target_version,
            namespace=rc.namespace,
            manifest_ref=rc.manifest_ref,
            manifest_sha256=rc.manifest_sha256,
            catalog_ref=catalog_ref,
            publish_record_ref=publish_ref,
            previous_pack_status=previous_status,
            new_pack_status=new_status,
            status=status,
            summary=_release_summary(rc, status),
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )
        return record


class PackReleaseCandidateStore:
    """release candidate/local release record 저장소."""

    def save_rc(self, rc: PackReleaseCandidate, path: Path) -> Path:
        """release candidate를 YAML로 저장한다."""
        return _save_yaml(Path(path).resolve(), rc.to_dict())

    def load_rc(self, path: Path) -> PackReleaseCandidate:
        """release candidate를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack release candidate not found: {path}")
        return _rc_from_dict(payload)

    def save_release(self, record: PackLocalReleaseRecord, path: Path) -> Path:
        """local release record를 YAML로 저장한다."""
        return _save_yaml(Path(path).resolve(), record.to_dict())

    def load_release(self, path: Path) -> PackLocalReleaseRecord:
        """local release record를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack local release record not found: {path}")
        return _release_from_dict(payload)


def default_pack_release_candidates_dir(project_root: Path) -> Path:
    """RC 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "releases" / "candidates"


def default_pack_local_releases_dir(project_root: Path) -> Path:
    """local release record 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "releases" / "local"


def default_pack_release_latest_rc_path(project_root: Path) -> Path:
    """latest RC pointer 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "releases" / "latest_rc.yaml"


def default_pack_release_latest_local_path(project_root: Path) -> Path:
    """latest local release pointer 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "releases" / "latest_local.yaml"


def default_pack_rc_path(project_root: Path, rc: PackReleaseCandidate) -> Path:
    """RC 기본 저장 경로를 반환한다."""
    return default_pack_release_candidates_dir(project_root) / f"rc_{_slug(rc.target_pack_id)}_{_stamp()}.yaml"


def default_pack_local_release_path(project_root: Path, record: PackLocalReleaseRecord) -> Path:
    """local release record 기본 저장 경로를 반환한다."""
    return default_pack_local_releases_dir(project_root) / f"release_{_slug(record.target_pack_id)}_{_stamp()}.yaml"


def save_pack_rc(project_root: Path, rc: PackReleaseCandidate) -> str:
    """RC를 기본 위치에 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    store = PackReleaseCandidateStore()
    path = store.save_rc(rc, default_pack_rc_path(root, rc))
    try:
        store.save_rc(rc, default_pack_release_latest_rc_path(root))
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest pack RC save failed: %s", exc)
    return _relative(path, root)


def save_pack_local_release(project_root: Path, record: PackLocalReleaseRecord) -> str:
    """local release record를 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    store = PackReleaseCandidateStore()
    path = store.save_release(record, default_pack_local_release_path(root, record))
    try:
        store.save_release(record, default_pack_release_latest_local_path(root))
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest local release save failed: %s", exc)
    return _relative(path, root)


def resolve_pack_rc_path(project_root: Path, rc_ref: str) -> Path:
    """RC id/path/latest를 실제 파일 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw_ref = str(rc_ref or "").strip()
    if not raw_ref:
        raise FileNotFoundError("pack RC ref is required")
    if raw_ref == "latest":
        latest = default_pack_release_latest_rc_path(root)
        if latest.exists():
            return latest.resolve()
    raw = Path(raw_ref)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend(
            [
                root / raw,
                default_pack_release_candidates_dir(root) / raw,
                default_pack_release_candidates_dir(root) / f"{raw}.yaml",
                default_pack_release_candidates_dir(root) / f"{_slug(raw_ref)}.yaml",
            ]
        )
    for path in candidates:
        if path.exists():
            return path.resolve()
    rc_dir = default_pack_release_candidates_dir(root)
    if rc_dir.exists():
        for path in sorted(rc_dir.glob("rc_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = _load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("RC resolve skipped: %s", exc)
                continue
            if str(payload.get("rc_id") or "") == raw_ref:
                return path.resolve()
    raise FileNotFoundError(f"pack release candidate not found: {rc_ref}")


def latest_pack_rc(project_root: Path, pack_ref: str | None = None) -> PackReleaseCandidate | None:
    """pack에 해당하는 최신 RC를 찾는다."""
    root = Path(project_root).resolve()
    store = PackReleaseCandidateStore()
    candidates: list[Path] = []
    rc_dir = default_pack_release_candidates_dir(root)
    if rc_dir.exists():
        candidates.extend(sorted(rc_dir.glob("rc_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
    latest = default_pack_release_latest_rc_path(root)
    if latest.exists():
        candidates.append(latest)
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            rc = store.load_rc(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("RC load skipped: %s", exc)
            continue
        if pack_ref is None or _rc_matches(rc, pack_ref):
            return rc
    return None


def latest_pack_local_release(project_root: Path, pack_ref: str | None = None) -> PackLocalReleaseRecord | None:
    """pack에 해당하는 최신 local release record를 찾는다."""
    root = Path(project_root).resolve()
    store = PackReleaseCandidateStore()
    candidates: list[Path] = []
    release_dir = default_pack_local_releases_dir(root)
    if release_dir.exists():
        candidates.extend(sorted(release_dir.glob("release_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
    latest = default_pack_release_latest_local_path(root)
    if latest.exists():
        candidates.append(latest)
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            record = store.load_release(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("local release load skipped: %s", exc)
            continue
        if pack_ref is None or _pack_matches(record.target_pack_id, pack_ref) or _pack_matches(record.source_pack_ref, pack_ref):
            return record
    return None


def release_check_target_from_rc(project_root: Path, target: str) -> str:
    """release-check 입력이 RC이면 연결된 manifest ref로 바꾼다."""
    try:
        rc_path = resolve_pack_rc_path(project_root, target)
    except FileNotFoundError:
        return target
    rc = PackReleaseCandidateStore().load_rc(rc_path)
    return rc.manifest_ref or target


def render_pack_rc(rc: PackReleaseCandidate) -> str:
    """RC 상세를 렌더링한다."""
    lines = [
        "Pack Release Candidate",
        "==================================================",
        "",
        "Target:",
        f"  {rc.target_pack_id}",
        "",
        "Status:",
        f"  {rc.status}",
        "",
        "Workorders:",
        f"  required done: {rc.workorder_summary.get('required_done', 0)} / {rc.workorder_summary.get('required_total', 0)}",
        f"  required open: {rc.workorder_summary.get('required_open', 0)}",
        f"  skipped required: {rc.workorder_summary.get('skipped_required', 0)}",
        "",
        "Manifest:",
        f"  {rc.manifest_ref or 'none'}",
        "",
        "Release local:",
        f"  {'safe' if rc.safe_to_release_local else 'not safe'}",
    ]
    if rc.changelog:
        lines.extend(["", "Changelog:"])
        lines.extend([f"  - {item}" for item in rc.changelog])
    if rc.release_notes:
        lines.extend(["", "Release notes:"])
        lines.extend([f"  - {item}" for item in rc.release_notes])
    if rc.safe_to_release_local:
        lines.extend(["", "Next:", f"  cambrian pack release-local {rc.rc_id}"])
    if rc.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in rc.warnings])
    if rc.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in rc.errors])
    return "\n".join(lines)


def render_pack_local_release(record: PackLocalReleaseRecord, confirm: bool) -> str:
    """release-local 결과를 렌더링한다."""
    title = "Pack Released Locally" if record.status == "released" else "Pack Local Release Preview"
    if record.status == "blocked":
        title = "Pack Local Release Blocked"
    lines = [
        title,
        "==================================================",
        "",
        "Target:",
        f"  {record.target_pack_id}",
        "",
        "Catalog:",
        f"  {record.catalog_ref or 'none'}",
        "",
        "Manifest:",
        f"  {record.manifest_ref or 'none'}",
    ]
    if record.previous_pack_status:
        lines.extend(["", "Previous pack:", f"  {record.source_pack_ref or 'unknown'}", f"  action: {record.previous_pack_status}"])
    if not confirm and record.status == "preview":
        lines.extend(["", "Run with --confirm to release locally."])
    if record.status == "released":
        lines.extend(["", "Install:", f"  cambrian install pack {record.target_pack_id}"])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    return "\n".join(lines)


def render_pack_rc_compact(rc: PackReleaseCandidate | None, release: PackLocalReleaseRecord | None = None) -> str:
    """pack show용 compact RC/release 요약."""
    lines: list[str] = []
    if rc is not None:
        lines.extend(
            [
                "Pack RC:",
                f"  target: {rc.target_pack_id}",
                f"  status: {rc.status}",
                f"  release local: {'safe' if rc.safe_to_release_local else 'not safe'}",
            ]
        )
    if release is not None:
        lines.extend(
            [
                "Pack local release:",
                f"  target: {release.target_pack_id}",
                f"  status: {release.status}",
            ]
        )
    return "\n".join(lines)


def render_status_pack_rc(rc: PackReleaseCandidate | None, release: PackLocalReleaseRecord | None = None) -> str:
    """status용 RC/release 요약."""
    if release is not None and release.status == "released":
        return "\n".join(["Pack release:", f"  {release.target_pack_id} available locally"])
    if rc is not None and rc.safe_to_release_local and rc.status == "release_ready":
        return "\n".join(["Pack RC:", f"  {rc.target_pack_id} ready for local release", f"  next: cambrian pack release-local {rc.rc_id}"])
    return ""


def _resolve_draft_or_workspace(root: Path, ref: str) -> tuple[Path, str | None]:
    raw = Path(str(ref))
    candidates = [raw if raw.is_absolute() else root / raw]
    for candidate in candidates:
        if candidate.exists():
            payload = _load_yaml(candidate)
            if payload.get("workspace_id") and payload.get("draft_ref"):
                return (root / str(payload.get("draft_ref"))).resolve(), _relative(candidate, root)
            if payload.get("draft_id"):
                return candidate.resolve(), None
    try:
        draft = resolve_draft_path(root, ref)
        return draft, None
    except Exception as draft_exc:
        workspace = _resolve_derivative_workspace(root, ref)
        if workspace is None or not workspace.draft_ref:
            raise FileNotFoundError(f"pack draft/workspace not found: {ref}") from draft_exc
        return (root / workspace.draft_ref).resolve(), workspace.source_plan_ref


def _resolve_derivative_workspace(root: Path, ref: str) -> PackDerivativeWorkspace | None:
    raw = Path(str(ref))
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        workspaces = root / ".cambrian" / "packs" / "derivatives" / "workspaces"
        candidates.extend([root / raw, workspaces / raw, workspaces / f"{raw}.yaml"])
    store = PackDerivativeStore()
    for path in candidates:
        if path.exists():
            return store.load_workspace(path)
    workspaces = root / ".cambrian" / "packs" / "derivatives" / "workspaces"
    if workspaces.exists():
        for path in sorted(workspaces.glob("workspace_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            payload = _load_yaml(path)
            if str(payload.get("workspace_id") or "") == str(ref):
                return store.load_workspace(path)
    return None


def _latest_workbench_for_candidate(root: Path, target_pack_id: str, source_pack_ref: str | None, plan_ref: str | None) -> PackVNextWorkbench | None:
    for ref in [source_pack_ref, target_pack_id]:
        if ref:
            workbench = latest_pack_vnext_workbench(root, ref)
            if workbench is not None and (not plan_ref or _ref_matches(workbench.derivative_plan_ref, plan_ref)):
                return workbench
    return latest_pack_vnext_workbench(root)


def _workbench_ref(root: Path, workbench: PackVNextWorkbench | None) -> str | None:
    if workbench is None:
        return None
    workbenches = root / ".cambrian" / "packs" / "vnext" / "workbenches"
    if workbenches.exists():
        for path in sorted(workbenches.glob("workbench_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            payload = _load_yaml(path)
            if str(payload.get("workbench_id") or "") == workbench.workbench_id:
                return _relative(path, root)
    return workbench.workbench_id


def _workorder_summary(workbench: PackVNextWorkbench | None) -> dict[str, Any]:
    orders = list(workbench.workorders if workbench else [])
    required = [order for order in orders if order.required]
    return {
        "required_total": len(required),
        "required_done": len([order for order in required if order.status == "done"]),
        "required_open": len([order for order in required if order.status in {"open", "blocked"}]),
        "optional_open": len([order for order in orders if not order.required and order.status == "open"]),
        "skipped_required": len([order for order in required if order.status == "skipped"]),
    }


def _unresolved_required_orders(workbench: PackVNextWorkbench | None) -> list[Any]:
    if workbench is None:
        return []
    return [order for order in workbench.workorders if order.required and order.status in {"open", "blocked", "skipped"}]


def _completed_orders(workbench: PackVNextWorkbench | None) -> list[Any]:
    if workbench is None:
        return []
    return [order for order in workbench.workorders if order.status == "done"]


def _candidate_status(errors: list[str], unresolved_orders: list[Any], allow_unresolved: bool) -> str:
    if errors and not (allow_unresolved and unresolved_orders and errors == ["required vNext workorders are unresolved"]):
        return "blocked"
    if unresolved_orders:
        return "candidate" if allow_unresolved else "blocked"
    return "release_ready" if not errors else "blocked"


def _changelog(completed_orders: list[Any]) -> list[str]:
    return _dedupe([f"{order.title} ({order.kind})" for order in completed_orders])


def _known_limits(completed_orders: list[Any], warnings: list[str]) -> list[str]:
    limits = [order.completion_note for order in completed_orders if order.kind == "known_limits_update" and order.completion_note]
    return _dedupe([*limits, *[item for item in warnings if "known limit" in str(item).lower()]])


def _release_notes(target_pack_id: str, source_pack_ref: str | None, completed_orders: list[Any], unresolved_orders: list[Any]) -> list[str]:
    notes = [f"{target_pack_id} is a local vNext release candidate"]
    if source_pack_ref:
        notes.append(f"lineage source: {source_pack_ref}")
    notes.append(f"completed workorders: {len(completed_orders)}")
    if unresolved_orders:
        notes.append(f"unresolved required workorders: {len(unresolved_orders)}")
    return notes


def _latest_proof_export_ref(root: Path, pack_ref: str | None) -> str | None:
    if not pack_ref:
        return None
    try:
        from engine.project_pack_proof_export import latest_pack_proof_export

        export = latest_pack_proof_export(root, pack_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning("proof export lookup for RC failed: %s", exc)
        return None
    if export is None:
        return None
    return export.public_ref or export.saved_ref or export.export_id


def _catalog_path(root: Path) -> Path:
    return Path(root).resolve() / "packs" / "catalog.yaml"


def _target_pack_ref(rc: PackReleaseCandidate) -> str:
    return f"{rc.target_pack_id}@{rc.target_version}" if rc.target_version else rc.target_pack_id


def _release_summary(rc: PackReleaseCandidate, status: str) -> list[str]:
    return [
        f"target={rc.target_pack_id}",
        f"status={status}",
        f"source={rc.source_pack_ref or 'none'}",
        f"manifest={rc.manifest_ref or 'none'}",
    ]


def _rc_from_dict(payload: dict[str, Any]) -> PackReleaseCandidate:
    return PackReleaseCandidate(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        rc_id=str(payload.get("rc_id") or f"pack-rc-{_stamp()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        source_pack_ref=str(payload.get("source_pack_ref")) if payload.get("source_pack_ref") is not None else None,
        source_pack_id=str(payload.get("source_pack_id")) if payload.get("source_pack_id") is not None else None,
        source_version=str(payload.get("source_version")) if payload.get("source_version") is not None else None,
        target_pack_id=str(payload.get("target_pack_id") or "unknown-pack"),
        target_pack_name=str(payload.get("target_pack_name")) if payload.get("target_pack_name") is not None else None,
        target_version=str(payload.get("target_version")) if payload.get("target_version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        draft_ref=str(payload.get("draft_ref")) if payload.get("draft_ref") is not None else None,
        derivative_plan_ref=str(payload.get("derivative_plan_ref")) if payload.get("derivative_plan_ref") is not None else None,
        derivative_workspace_ref=str(payload.get("derivative_workspace_ref")) if payload.get("derivative_workspace_ref") is not None else None,
        workbench_ref=str(payload.get("workbench_ref")) if payload.get("workbench_ref") is not None else None,
        manifest_ref=str(payload.get("manifest_ref")) if payload.get("manifest_ref") is not None else None,
        manifest_sha256=str(payload.get("manifest_sha256")) if payload.get("manifest_sha256") is not None else None,
        build_report_ref=str(payload.get("build_report_ref")) if payload.get("build_report_ref") is not None else None,
        release_check_ref=str(payload.get("release_check_ref")) if payload.get("release_check_ref") is not None else None,
        proof_export_ref=str(payload.get("proof_export_ref")) if payload.get("proof_export_ref") is not None else None,
        workorder_summary=_as_dict(payload.get("workorder_summary")),
        accepted_improvement_refs=_as_list(payload.get("accepted_improvement_refs")),
        completed_workorder_refs=_as_list(payload.get("completed_workorder_refs")),
        unresolved_workorder_refs=_as_list(payload.get("unresolved_workorder_refs")),
        changelog=_as_list(payload.get("changelog")),
        known_limits=_as_list(payload.get("known_limits")),
        release_notes=_as_list(payload.get("release_notes")),
        maturity=str(payload.get("maturity")) if payload.get("maturity") is not None else None,
        proof_status=str(payload.get("proof_status")) if payload.get("proof_status") is not None else None,
        status=str(payload.get("status") or "candidate"),
        safe_to_release_local=bool(payload.get("safe_to_release_local")),
        requires_confirm=bool(payload.get("requires_confirm", True)),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _release_from_dict(payload: dict[str, Any]) -> PackLocalReleaseRecord:
    return PackLocalReleaseRecord(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        release_id=str(payload.get("release_id") or f"pack-local-release-{_stamp()}"),
        created_at=str(payload.get("created_at") or _now()),
        rc_ref=str(payload.get("rc_ref") or ""),
        source_pack_ref=str(payload.get("source_pack_ref")) if payload.get("source_pack_ref") is not None else None,
        target_pack_ref=str(payload.get("target_pack_ref") or payload.get("target_pack_id") or "unknown-pack"),
        target_pack_id=str(payload.get("target_pack_id") or "unknown-pack"),
        target_version=str(payload.get("target_version")) if payload.get("target_version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        manifest_ref=str(payload.get("manifest_ref")) if payload.get("manifest_ref") is not None else None,
        manifest_sha256=str(payload.get("manifest_sha256")) if payload.get("manifest_sha256") is not None else None,
        catalog_ref=str(payload.get("catalog_ref")) if payload.get("catalog_ref") is not None else None,
        publish_record_ref=str(payload.get("publish_record_ref")) if payload.get("publish_record_ref") is not None else None,
        previous_pack_status=str(payload.get("previous_pack_status")) if payload.get("previous_pack_status") is not None else None,
        new_pack_status=str(payload.get("new_pack_status")) if payload.get("new_pack_status") is not None else None,
        status=str(payload.get("status") or "preview"),
        summary=_as_list(payload.get("summary")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _rc_matches(rc: PackReleaseCandidate, pack_ref: str) -> bool:
    return _pack_matches(rc.target_pack_id, pack_ref) or _pack_matches(rc.source_pack_id, pack_ref) or _pack_matches(rc.source_pack_ref, pack_ref)


def _pack_matches(value: str | None, pack_ref: str | None) -> bool:
    if not pack_ref:
        return True
    raw_plain = _plain_pack_id(value)
    ref_plain = _plain_pack_id(pack_ref)
    return raw_plain == ref_plain or _local_pack_base(raw_plain) == _local_pack_base(ref_plain) or str(value or "") == str(pack_ref or "")


def _plain_pack_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split("@", 1)[0].split("/", 1)[-1]


def _local_pack_base(value: str) -> str:
    raw = str(value or "").strip()
    for suffix in ("-local", "_local"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)]
    return raw


def _ref_matches(candidate: str | None, expected: str | None) -> bool:
    raw = str(candidate or "").replace("\\", "/")
    wanted = str(expected or "").replace("\\", "/")
    return bool(raw and wanted and (raw == wanted or raw.endswith(wanted)))


def _slug(value: Any, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _stamp() -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", _now()).strip("_")[:15]


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
