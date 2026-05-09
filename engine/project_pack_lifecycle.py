"""Pack diff/update/uninstall lifecycle 관리."""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_catalog import (
    PackCatalogResolver,
    default_pack_catalog_path,
    load_default_catalog,
    local_catalog_source_ref,
)
from engine.project_pack_install import (
    SCHEMA_VERSION,
    InstalledPackRecord,
    InstalledPackStore,
    PackInstaller,
    PackManifest,
    PackManifestLoader,
    default_agent_registry_path,
    default_benchmark_worksets_dir,
    default_install_dir,
    default_installed_packs_path,
    default_lane_playbook_path,
    default_team_presets_path,
    default_templates_path,
    _canonical,
    _digest_payload,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)

logger = logging.getLogger(__name__)


@dataclass
class PackDiffEntry:
    """Pack artifact 단위 diff 항목."""

    artifact_kind: str
    artifact_name: str
    change_kind: str
    current_ref: str | None
    incoming_ref: str | None
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackDiffReport:
    """Installed pack과 incoming manifest의 diff report."""

    schema_version: str
    report_id: str
    generated_at: str
    pack_id: str
    pack_name: str | None
    current_version: str | None
    incoming_version: str | None
    current_sha256: str | None
    incoming_sha256: str | None
    digest_changed: bool | None
    source_kind: str | None
    current_manifest_ref: str | None
    incoming_manifest_ref: str | None
    entries: list[PackDiffEntry]
    summary: dict[str, Any]
    safe_to_update: bool
    requires_confirm: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["entries"] = [entry.to_dict() for entry in self.entries]
        return payload


@dataclass
class PackUpdateRecord:
    """Pack update 실행 기록."""

    schema_version: str
    update_id: str
    created_at: str
    pack_id: str
    pack_name: str | None
    previous_version: str | None
    new_version: str | None
    previous_manifest_sha256: str | None
    incoming_manifest_sha256: str | None
    diff_ref: str | None
    incoming_manifest_ref: str | None
    status: str
    updated_artifacts: dict[str, Any]
    protected_artifacts: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackUninstallPlan:
    """Pack uninstall preview plan."""

    schema_version: str
    plan_id: str
    generated_at: str
    pack_id: str
    pack_name: str | None
    removable_artifacts: dict[str, Any]
    protected_artifacts: dict[str, Any]
    blocking_references: dict[str, Any]
    historical_artifacts_kept: dict[str, Any]
    safe_to_uninstall: bool
    requires_confirm: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackUninstallRecord:
    """Pack uninstall 실행 기록."""

    schema_version: str
    uninstall_id: str
    created_at: str
    pack_id: str
    pack_name: str | None
    plan_ref: str | None
    status: str
    removed_artifacts: dict[str, Any]
    protected_artifacts: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


def default_pack_diffs_dir(project_root: Path) -> Path:
    """Pack diff report 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "diffs"


def default_pack_updates_dir(project_root: Path) -> Path:
    """Pack update record 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "updates"


def default_pack_uninstall_plans_dir(project_root: Path) -> Path:
    """Pack uninstall plan 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "uninstall_plans"


def default_pack_uninstalls_dir(project_root: Path) -> Path:
    """Pack uninstall record 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "uninstalls"


class PackDiffBuilder:
    """Installed pack과 incoming manifest의 차이를 만든다."""

    def build(self, project_root: Path, pack_id: str, incoming_manifest_path: Path | None = None) -> PackDiffReport:
        """pack diff report를 생성한다."""
        root = Path(project_root).resolve()
        record = _installed_pack(root, pack_id)
        current_manifest_path = _resolve_manifest_ref(root, record.latest_manifest_ref or record.manifest_ref)
        if current_manifest_path is None or not current_manifest_path.exists():
            return _diff_error_report(
                record,
                f"installed manifest copy not found: {record.latest_manifest_ref or record.manifest_ref or 'missing'}",
            )

        current_manifest = PackManifestLoader().load(current_manifest_path)
        incoming_path, incoming_manifest, source_kind = _incoming_manifest(root, record.pack_id, incoming_manifest_path)
        from engine.project_pack_trust import PackIntegrityHasher

        current_integrity = PackIntegrityHasher().hash_file(current_manifest_path)
        incoming_integrity = PackIntegrityHasher().hash_file(incoming_path)
        entries = _diff_manifests(current_manifest, incoming_manifest)
        warnings: list[str] = []
        errors: list[str] = []
        if incoming_manifest.pack_id != record.pack_id:
            errors.append(f"incoming manifest pack_id differs: {incoming_manifest.pack_id}")
        entries.extend(_library_conflicts(root, record.pack_id, current_manifest, incoming_manifest))
        summary = _diff_summary(entries)
        errors.extend(_entry_errors(entries))
        safe = not errors and summary["conflict_count"] == 0
        return PackDiffReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"diff-{_slug(record.pack_id)}-{_stamp()}",
            generated_at=_now(),
            pack_id=record.pack_id,
            pack_name=record.pack_name,
            current_version=current_manifest.version or record.version,
            incoming_version=incoming_manifest.version,
            current_sha256=current_integrity.sha256 or None,
            incoming_sha256=incoming_integrity.sha256 or None,
            digest_changed=current_integrity.sha256 != incoming_integrity.sha256,
            source_kind=source_kind,
            current_manifest_ref=_relative(current_manifest_path, root),
            incoming_manifest_ref=_relative(incoming_path, root),
            entries=entries,
            summary=summary,
            safe_to_update=safe,
            requires_confirm=True,
            warnings=warnings,
            errors=errors,
        )


class PackUpdater:
    """Installed pack update 실행기."""

    def update(
        self,
        project_root: Path,
        pack_id: str,
        incoming_manifest_path: Path | None = None,
        confirm: bool = False,
        require_trusted: bool = False,
    ) -> PackUpdateRecord:
        """diff를 기반으로 pack update를 실행한다."""
        root = Path(project_root).resolve()
        diff = PackDiffBuilder().build(root, pack_id, incoming_manifest_path)
        diff_ref = save_pack_diff(root, diff)
        update_id = f"update-{_slug(pack_id)}-{_stamp()}"
        protected = _protected_from_diff(diff)
        if not confirm:
            return PackUpdateRecord(
                schema_version=SCHEMA_VERSION,
                update_id=update_id,
                created_at=_now(),
                pack_id=diff.pack_id,
                pack_name=diff.pack_name,
                previous_version=diff.current_version,
                new_version=diff.incoming_version,
                previous_manifest_sha256=diff.current_sha256,
                incoming_manifest_sha256=diff.incoming_sha256,
                diff_ref=diff_ref,
                incoming_manifest_ref=diff.incoming_manifest_ref,
                status="blocked",
                updated_artifacts={},
                protected_artifacts=protected,
                warnings=[*diff.warnings, "update requires --confirm"],
                errors=list(diff.errors),
            )
        if not diff.safe_to_update:
            record = PackUpdateRecord(
                schema_version=SCHEMA_VERSION,
                update_id=update_id,
                created_at=_now(),
                pack_id=diff.pack_id,
                pack_name=diff.pack_name,
                previous_version=diff.current_version,
                new_version=diff.incoming_version,
                previous_manifest_sha256=diff.current_sha256,
                incoming_manifest_sha256=diff.incoming_sha256,
                diff_ref=diff_ref,
                incoming_manifest_ref=diff.incoming_manifest_ref,
                status="blocked",
                updated_artifacts={},
                protected_artifacts=protected,
                warnings=list(diff.warnings),
                errors=list(diff.errors) or ["diff is not safe to update"],
            )
            record.saved_ref = save_pack_update(root, record)
            return record

        incoming_path = _resolve_manifest_ref(root, diff.incoming_manifest_ref)
        if incoming_path is None:
            raise FileNotFoundError("incoming manifest path missing")
        source_kind = "manifest_update"
        source_ref = _relative(incoming_path, root)
        expected_sha256 = None
        trust_level = None
        if diff.source_kind == "local_catalog":
            repo_root = Path(__file__).resolve().parents[1]
            catalog = load_default_catalog(repo_root)
            entry = PackCatalogResolver().find_entry(catalog, diff.pack_id)
            source_kind = "local_catalog"
            source_ref = local_catalog_source_ref(repo_root, entry)
            expected_sha256 = entry.manifest_sha256
            trust_level = entry.trust_level
        plan = PackInstaller().install(
            root,
            incoming_path,
            dry_run=False,
            source_kind_override=source_kind,
            source_ref_override=source_ref,
            allow_update=True,
            expected_sha256=expected_sha256,
            require_trusted=require_trusted,
            trust_level_override=trust_level,
        )
        status = "updated" if plan.safe_to_install else "failed"
        update_record = PackUpdateRecord(
            schema_version=SCHEMA_VERSION,
            update_id=update_id,
            created_at=_now(),
            pack_id=diff.pack_id,
            pack_name=diff.pack_name,
            previous_version=diff.current_version,
            new_version=diff.incoming_version,
            previous_manifest_sha256=diff.current_sha256,
            incoming_manifest_sha256=diff.incoming_sha256,
            diff_ref=diff_ref,
            incoming_manifest_ref=diff.incoming_manifest_ref,
            status=status,
            updated_artifacts=plan.target_artifacts,
            protected_artifacts=protected,
            warnings=[*diff.warnings, *plan.warnings],
            errors=[*diff.errors, *plan.errors, *plan.conflicts],
        )
        update_record.saved_ref = save_pack_update(root, update_record)
        _mark_pack_updated(root, diff.pack_id, update_record)
        return update_record


class PackUninstallPlanner:
    """Installed pack uninstall plan builder."""

    def build_plan(self, project_root: Path, pack_id: str) -> PackUninstallPlan:
        """pack 제거 preview plan을 만든다."""
        root = Path(project_root).resolve()
        record = _installed_pack(root, pack_id)
        artifacts = _copy_artifacts(record.installed_artifacts)
        blocking = _blocking_references(root, record)
        protected = _protected_uninstall_artifacts(root, record, blocking)
        removable = _subtract_artifacts(artifacts, protected)
        history = _historical_artifacts(root, record)
        warnings = ["uninstall keeps manifest history and historical evidence"]
        safe = not any(blocking.values())
        return PackUninstallPlan(
            schema_version=SCHEMA_VERSION,
            plan_id=f"uninstall-plan-{_slug(record.pack_id)}-{_stamp()}",
            generated_at=_now(),
            pack_id=record.pack_id,
            pack_name=record.pack_name,
            removable_artifacts=removable,
            protected_artifacts=protected,
            blocking_references=blocking,
            historical_artifacts_kept=history,
            safe_to_uninstall=safe,
            requires_confirm=True,
            warnings=warnings,
            errors=[] if safe else ["blocking references require --force or cleanup before uninstall"],
        )


class PackUninstaller:
    """Installed pack 제거 실행기."""

    def uninstall(
        self,
        project_root: Path,
        pack_id: str,
        confirm: bool = False,
        force: bool = False,
    ) -> PackUninstallRecord:
        """preview-first uninstall을 실행한다."""
        root = Path(project_root).resolve()
        plan = PackUninstallPlanner().build_plan(root, pack_id)
        plan_ref = save_pack_uninstall_plan(root, plan)
        uninstall_id = f"uninstall-{_slug(plan.pack_id)}-{_stamp()}"
        if not confirm:
            return PackUninstallRecord(
                schema_version=SCHEMA_VERSION,
                uninstall_id=uninstall_id,
                created_at=_now(),
                pack_id=plan.pack_id,
                pack_name=plan.pack_name,
                plan_ref=plan_ref,
                status="blocked",
                removed_artifacts={},
                protected_artifacts=plan.protected_artifacts,
                warnings=[*plan.warnings, "uninstall requires --confirm"],
                errors=list(plan.errors),
            )
        if not plan.safe_to_uninstall and not force:
            record = PackUninstallRecord(
                schema_version=SCHEMA_VERSION,
                uninstall_id=uninstall_id,
                created_at=_now(),
                pack_id=plan.pack_id,
                pack_name=plan.pack_name,
                plan_ref=plan_ref,
                status="blocked",
                removed_artifacts={},
                protected_artifacts=plan.protected_artifacts,
                warnings=list(plan.warnings),
                errors=list(plan.errors),
            )
            record.saved_ref = save_pack_uninstall(root, record)
            return record
        removed = _remove_removable_artifacts(root, plan.pack_id, plan.removable_artifacts)
        record = PackUninstallRecord(
            schema_version=SCHEMA_VERSION,
            uninstall_id=uninstall_id,
            created_at=_now(),
            pack_id=plan.pack_id,
            pack_name=plan.pack_name,
            plan_ref=plan_ref,
            status="uninstalled",
            removed_artifacts=removed,
            protected_artifacts=plan.protected_artifacts,
            warnings=list(plan.warnings),
            errors=[],
        )
        record.saved_ref = save_pack_uninstall(root, record)
        _mark_pack_uninstalled(root, plan.pack_id, record)
        return record


def save_pack_diff(project_root: Path, report: PackDiffReport) -> str:
    """diff report를 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = default_pack_diffs_dir(root) / f"diff_{_slug(report.pack_id)}_{_stamp()}.yaml"
    report.saved_ref = _relative(path, root)
    _save_yaml(path, report.to_dict())
    return report.saved_ref


def save_pack_update(project_root: Path, record: PackUpdateRecord) -> str:
    """update record를 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = default_pack_updates_dir(root) / f"update_{_slug(record.pack_id)}_{_stamp()}.yaml"
    record.saved_ref = _relative(path, root)
    _save_yaml(path, record.to_dict())
    return record.saved_ref


def save_pack_uninstall_plan(project_root: Path, plan: PackUninstallPlan) -> str:
    """uninstall plan을 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = default_pack_uninstall_plans_dir(root) / f"uninstall_plan_{_slug(plan.pack_id)}_{_stamp()}.yaml"
    plan.saved_ref = _relative(path, root)
    _save_yaml(path, plan.to_dict())
    return plan.saved_ref


def save_pack_uninstall(project_root: Path, record: PackUninstallRecord) -> str:
    """uninstall record를 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = default_pack_uninstalls_dir(root) / f"uninstall_{_slug(record.pack_id)}_{_stamp()}.yaml"
    record.saved_ref = _relative(path, root)
    _save_yaml(path, record.to_dict())
    return record.saved_ref


def render_pack_diff(report: PackDiffReport) -> str:
    """diff report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Diff",
        "==================================================",
        "",
        "Pack:",
        f"  {report.pack_id}",
        "",
        "Current:",
        f"  {report.current_version or 'none'}",
        "",
        "Incoming:",
        f"  {report.incoming_version or 'none'}",
        "",
        "Integrity:",
        f"  current sha256 : {report.current_sha256 or 'unknown'}",
        f"  incoming sha256: {report.incoming_sha256 or 'unknown'}",
        f"  changed        : {str(report.digest_changed).lower() if report.digest_changed is not None else 'unknown'}",
        "",
        "Changes:",
    ]
    if not report.entries:
        lines.append("  none")
    for entry in report.entries:
        marker = {
            "added": "+",
            "removed": "-",
            "changed": "~",
            "unchanged": "=",
            "conflict": "!",
            "protected": "#",
        }.get(entry.change_kind, "?")
        lines.append(f"  {marker} {entry.artifact_kind}: {entry.artifact_name} ({entry.change_kind})")
        lines.append(f"    {entry.summary}")
    lines.extend(
        [
            "",
            "Summary:",
            f"  added    : {report.summary.get('added_count', 0)}",
            f"  changed  : {report.summary.get('changed_count', 0)}",
            f"  removed  : {report.summary.get('removed_count', 0)}",
            f"  protected: {report.summary.get('protected_count', 0)}",
            f"  conflicts: {report.summary.get('conflict_count', 0)}",
            "",
            "Result:",
            f"  safe_to_update: {str(report.safe_to_update).lower()}",
        ]
    )
    if report.saved_ref:
        lines.extend(["", "Saved:", f"  {report.saved_ref}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def render_pack_update(record: PackUpdateRecord) -> str:
    """update record를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Update",
        "==================================================",
        "",
        "Pack:",
        f"  {record.pack_id}",
        "",
        "Version:",
        f"  {record.previous_version or 'none'} -> {record.new_version or 'none'}",
        "",
        "Integrity:",
        f"  previous sha256: {record.previous_manifest_sha256 or 'unknown'}",
        f"  incoming sha256: {record.incoming_manifest_sha256 or 'unknown'}",
        "",
        "Status:",
        f"  {record.status}",
    ]
    if record.diff_ref:
        lines.extend(["", "Diff:", f"  {record.diff_ref}"])
    if record.saved_ref:
        lines.extend(["", "Saved:", f"  {record.saved_ref}"])
    if record.protected_artifacts:
        lines.extend(["", "Protected:"])
        lines.extend(_render_artifact_map(record.protected_artifacts))
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    return "\n".join(lines)


def render_uninstall_plan(plan: PackUninstallPlan) -> str:
    """uninstall plan을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Uninstall Plan",
        "==================================================",
        "",
        "Pack:",
        f"  {plan.pack_id}",
        "",
        "Safety:",
        f"  safe_to_uninstall: {str(plan.safe_to_uninstall).lower()}",
        f"  requires_confirm : {str(plan.requires_confirm).lower()}",
        "",
        "Removable:",
    ]
    lines.extend(_render_artifact_map(plan.removable_artifacts) or ["  none"])
    lines.extend(["", "Protected:"])
    lines.extend(_render_artifact_map(plan.protected_artifacts) or ["  none"])
    lines.extend(["", "Blocking references:"])
    lines.extend(_render_artifact_map(plan.blocking_references) or ["  none"])
    if plan.saved_ref:
        lines.extend(["", "Saved:", f"  {plan.saved_ref}"])
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in plan.warnings])
    if plan.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in plan.errors])
    return "\n".join(lines)


def render_uninstall_record(record: PackUninstallRecord) -> str:
    """uninstall record를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Uninstall",
        "==================================================",
        "",
        "Pack:",
        f"  {record.pack_id}",
        "",
        "Status:",
        f"  {record.status}",
        "",
        "Removed:",
    ]
    lines.extend(_render_artifact_map(record.removed_artifacts) or ["  none"])
    lines.extend(["", "Protected:"])
    lines.extend(_render_artifact_map(record.protected_artifacts) or ["  none"])
    if record.plan_ref:
        lines.extend(["", "Plan:", f"  {record.plan_ref}"])
    if record.saved_ref:
        lines.extend(["", "Saved:", f"  {record.saved_ref}"])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    return "\n".join(lines)


def _installed_pack(root: Path, pack_id: str) -> InstalledPackRecord:
    store = InstalledPackStore()
    index = store.load(default_installed_packs_path(root))
    record = store.find(index, pack_id)
    if record.status == "uninstalled":
        raise KeyError(f"{pack_id} is uninstalled")
    return record


def _resolve_manifest_ref(root: Path, manifest_ref: str | None) -> Path | None:
    if not manifest_ref:
        return None
    candidate = Path(manifest_ref)
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path(root).resolve() / candidate).resolve()


def _incoming_manifest(root: Path, pack_id: str, incoming_manifest_path: Path | None) -> tuple[Path, PackManifest, str]:
    if incoming_manifest_path is not None:
        path = Path(incoming_manifest_path).resolve()
        return path, PackManifestLoader().load(path), "manifest"
    repo_root = Path(__file__).resolve().parents[1]
    catalog = load_default_catalog(repo_root)
    if catalog.errors:
        raise ValueError(catalog.errors[0])
    entry = PackCatalogResolver().find_entry(catalog, pack_id)
    path = PackCatalogResolver().resolve_manifest_path(repo_root, entry)
    return path, PackManifestLoader().load(path), "local_catalog"


def _diff_manifests(current: PackManifest, incoming: PackManifest) -> list[PackDiffEntry]:
    entries: list[PackDiffEntry] = []
    specs = [
        ("worker", _manifest_items(current.workers, "id", "agent_id"), _manifest_items(incoming.workers, "id", "agent_id")),
        ("team", _manifest_items(current.teams, "name", "team_id"), _manifest_items(incoming.teams, "name", "team_id")),
        ("template", _manifest_items(current.templates, "name", "template_id"), _manifest_items(incoming.templates, "name", "template_id")),
        ("benchmark", _manifest_items(current.benchmarks, "name", "workset_id"), _manifest_items(incoming.benchmarks, "name", "workset_id")),
    ]
    for kind, current_items, incoming_items in specs:
        names = sorted(set(current_items) | set(incoming_items))
        for name in names:
            current_item = current_items.get(name)
            incoming_item = incoming_items.get(name)
            entries.append(_diff_entry(kind, name, current_item, incoming_item))
    if current.lane or incoming.lane:
        lane_name = str((incoming.lane or current.lane or {}).get("lane_id") or "lane")
        entries.append(_diff_entry("lane", lane_name, current.lane, incoming.lane))
    entries.append(_diff_entry("compatibility", "compatibility", current.compatibility, incoming.compatibility))
    entries.append(_diff_entry("policy", "policies", {"policies": current.policies}, {"policies": incoming.policies}))
    return entries


def _manifest_items(items: list[dict[str, Any]], primary: str, fallback: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        name = str(item.get(primary) or item.get(fallback) or "").strip()
        if name:
            result[name] = dict(item)
    return result


def _diff_entry(
    kind: str,
    name: str,
    current_item: dict[str, Any] | None,
    incoming_item: dict[str, Any] | None,
) -> PackDiffEntry:
    if current_item is None:
        return PackDiffEntry(kind, name, "added", None, name, "incoming manifest adds this artifact")
    if incoming_item is None:
        return PackDiffEntry(kind, name, "removed", name, None, "incoming manifest removes this artifact")
    if _canonical(current_item) == _canonical(incoming_item):
        return PackDiffEntry(kind, name, "unchanged", name, name, "artifact is unchanged")
    return PackDiffEntry(kind, name, "changed", name, name, "artifact content changed")


def _library_conflicts(
    root: Path,
    pack_id: str,
    current_manifest: PackManifest,
    incoming_manifest: PackManifest,
) -> list[PackDiffEntry]:
    entries: list[PackDiffEntry] = []
    entries.extend(_template_conflicts(root, pack_id, current_manifest, incoming_manifest))
    worker_names = set(_manifest_items([*current_manifest.workers, *incoming_manifest.workers], "id", "agent_id"))
    team_names = set(_manifest_items([*current_manifest.teams, *incoming_manifest.teams], "name", "team_id"))
    entries.extend(_simple_library_conflicts(root, pack_id, "worker", default_agent_registry_path(root), "agents", "agent_id", worker_names))
    entries.extend(_simple_library_conflicts(root, pack_id, "team", default_team_presets_path(root), "teams", "name", team_names))
    return entries


def _simple_library_conflicts(
    root: Path,
    pack_id: str,
    kind: str,
    path: Path,
    list_key: str,
    key: str,
    target_names: set[str],
) -> list[PackDiffEntry]:
    payload = _load_yaml(path)
    entries: list[PackDiffEntry] = []
    for item in payload.get(list_key, []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("source_pack_id") == pack_id or str(item.get("source_kind") or "") == "installed":
            continue
        name = str(item.get(key) or item.get("team_id") or "")
        if name not in target_names:
            continue
        if name:
            entries.append(
                PackDiffEntry(
                    kind,
                    name,
                    "conflict",
                    _relative(path, root),
                    None,
                    f"local {kind} with same library namespace is not pack-owned",
                    errors=[f"{kind} is not owned by pack {pack_id}: {name}"],
                )
            )
    return entries


def _template_conflicts(
    root: Path,
    pack_id: str,
    current_manifest: PackManifest,
    incoming_manifest: PackManifest,
) -> list[PackDiffEntry]:
    payload = _load_yaml(default_templates_path(root))
    pack_template_names = {
        str(item.get("name") or item.get("template_id") or "")
        for item in [*current_manifest.templates, *incoming_manifest.templates]
        if isinstance(item, dict)
    }
    entries: list[PackDiffEntry] = []
    for item in payload.get("templates", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("template_id") or "")
        source_kind = str(item.get("source_kind") or "")
        source_origin = item.get("source_origin") if isinstance(item.get("source_origin"), dict) else {}
        if source_kind in {"local_derivative", "local", "evolved"} and _is_template_derivative(item, pack_id, pack_template_names):
            entries.append(
                PackDiffEntry(
                    "template",
                    name,
                    "protected",
                    _relative(default_templates_path(root), root),
                    None,
                    "local derivative/evolved template is protected from update",
                    warnings=[f"protected local derivative: {name}"],
                )
            )
            continue
        if name in pack_template_names and item.get("source_pack_id") != pack_id and source_origin.get("source_pack_id") != pack_id:
            entries.append(
                PackDiffEntry(
                    "template",
                    name,
                    "conflict",
                    _relative(default_templates_path(root), root),
                    None,
                    "template name exists but is not owned by this installed pack",
                    errors=[f"template is not owned by pack {pack_id}: {name}"],
                )
            )
    return entries


def _is_template_derivative(item: dict[str, Any], pack_id: str, pack_template_names: set[str]) -> bool:
    source_origin = item.get("source_origin") if isinstance(item.get("source_origin"), dict) else {}
    lineage = item.get("lineage") if isinstance(item.get("lineage"), dict) else {}
    parent = str(item.get("parent_template") or lineage.get("parent_template") or "")
    root = str(lineage.get("root_template") or "")
    name = str(item.get("name") or "")
    if source_origin.get("source_pack_id") == pack_id or item.get("source_pack_id") == pack_id:
        return True
    if parent in pack_template_names or root in pack_template_names:
        return True
    return any(name.startswith(f"{template_name}-") for template_name in pack_template_names if template_name)


def _diff_summary(entries: list[PackDiffEntry]) -> dict[str, int]:
    result = {
        "added_count": 0,
        "removed_count": 0,
        "changed_count": 0,
        "unchanged_count": 0,
        "conflict_count": 0,
        "protected_count": 0,
    }
    for entry in entries:
        key = f"{entry.change_kind}_count"
        if key in result:
            result[key] += 1
    return result


def _entry_errors(entries: list[PackDiffEntry]) -> list[str]:
    errors: list[str] = []
    for entry in entries:
        errors.extend(entry.errors)
    return _dedupe(errors)


def _diff_error_report(record: InstalledPackRecord, error: str) -> PackDiffReport:
    return PackDiffReport(
        schema_version=SCHEMA_VERSION,
        report_id=f"diff-{_slug(record.pack_id)}-{_stamp()}",
        generated_at=_now(),
        pack_id=record.pack_id,
        pack_name=record.pack_name,
        current_version=record.version,
        incoming_version=None,
        current_sha256=record.manifest_sha256,
        incoming_sha256=None,
        digest_changed=None,
        source_kind=None,
        current_manifest_ref=record.latest_manifest_ref or record.manifest_ref,
        incoming_manifest_ref=None,
        entries=[],
        summary=_diff_summary([]),
        safe_to_update=False,
        requires_confirm=True,
        errors=[error],
    )


def _protected_from_diff(diff: PackDiffReport) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for entry in diff.entries:
        if entry.change_kind != "protected":
            continue
        result.setdefault(entry.artifact_kind, []).append(entry.artifact_name)
    return result


def _mark_pack_updated(root: Path, pack_id: str, update: PackUpdateRecord) -> None:
    store = InstalledPackStore()
    path = default_installed_packs_path(root)
    index = store.load(path)
    for record in index.packs:
        if record.pack_id != pack_id:
            continue
        record.status = "updated"
        record.updated_at = update.created_at
        if update.incoming_manifest_ref:
            if update.incoming_manifest_ref not in record.manifest_history:
                record.manifest_history.append(update.incoming_manifest_ref)
        if update.saved_ref and update.saved_ref not in record.update_history:
            record.update_history.append(update.saved_ref)
        break
    store.save(path, index)


def _mark_pack_uninstalled(root: Path, pack_id: str, uninstall: PackUninstallRecord) -> None:
    store = InstalledPackStore()
    path = default_installed_packs_path(root)
    index = store.load(path)
    for record in index.packs:
        if record.pack_id != pack_id:
            continue
        record.status = "uninstalled"
        record.uninstalled_at = uninstall.created_at
        record.uninstall_ref = uninstall.saved_ref
        break
    store.save(path, index)


def _copy_artifacts(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _blocking_references(root: Path, record: InstalledPackRecord) -> dict[str, Any]:
    artifacts = record.installed_artifacts
    templates = {str(item) for item in artifacts.get("templates", []) or []}
    teams = {str(item) for item in artifacts.get("teams", []) or []}
    worksets = {str(item) for item in artifacts.get("benchmarks", []) or []}
    blocking: dict[str, Any] = {
        "current_template": [],
        "active_team": [],
        "lane_default": [],
        "active_canary": [],
        "benchmark_history": [],
    }
    current_template_path = root / ".cambrian" / "templates" / "current_template.yaml"
    current_payload = _load_yaml(current_template_path)
    current_text = yaml.safe_dump(current_payload, allow_unicode=True, sort_keys=False) if current_payload else ""
    for template in templates:
        if template and template in current_text:
            blocking["current_template"].append(template)
    teams_payload = _load_yaml(default_team_presets_path(root))
    active_team = str(teams_payload.get("active_team_id") or "")
    if active_team in teams:
        blocking["active_team"].append(active_team)
    lane = _load_yaml(default_lane_playbook_path(root))
    for key in ("default_template_name", "stable_default_template", "default_template"):
        value = str(lane.get(key) or "")
        if value in templates:
            blocking["lane_default"].append(value)
    canary = str(lane.get("canary_template_name") or lane.get("active_canary_template") or "")
    if canary in templates:
        blocking["active_canary"].append(canary)
    if _has_benchmark_history(root, worksets):
        blocking["benchmark_history"].extend(sorted(worksets))
    return {key: value for key, value in blocking.items() if value}


def _has_benchmark_history(root: Path, worksets: set[str]) -> bool:
    if not worksets:
        return False
    benchmark_root = root / ".cambrian" / "benchmarks"
    history_dirs = ["proof", "results", "reports", "compares", "replays", "workset_replays", "autonomy_boards"]
    for folder in history_dirs:
        path = benchmark_root / folder
        if path.exists() and any(path.rglob("*")):
            return True
    return False


def _protected_uninstall_artifacts(
    root: Path,
    record: InstalledPackRecord,
    blocking: dict[str, Any],
) -> dict[str, Any]:
    protected: dict[str, Any] = {"local_derivatives": _local_derivatives(root, record)}
    if blocking.get("current_template") or blocking.get("lane_default") or blocking.get("active_canary"):
        protected["templates"] = list(record.installed_artifacts.get("templates", []) or [])
    if blocking.get("active_team"):
        protected["teams"] = list(record.installed_artifacts.get("teams", []) or [])
    if blocking.get("benchmark_history"):
        protected["benchmarks"] = list(record.installed_artifacts.get("benchmarks", []) or [])
    return {key: value for key, value in protected.items() if value}


def _local_derivatives(root: Path, record: InstalledPackRecord) -> list[str]:
    payload = _load_yaml(default_templates_path(root))
    pack_template_names = {str(item) for item in record.installed_artifacts.get("templates", []) or []}
    derivatives: list[str] = []
    for item in payload.get("templates", []) or []:
        if not isinstance(item, dict):
            continue
        source_kind = str(item.get("source_kind") or "")
        if source_kind not in {"local", "local_derivative", "evolved"}:
            continue
        if _is_template_derivative(item, record.pack_id, pack_template_names):
            derivatives.append(str(item.get("name") or item.get("template_id") or "unknown"))
    return _dedupe(derivatives)


def _subtract_artifacts(artifacts: dict[str, Any], protected: dict[str, Any]) -> dict[str, Any]:
    result = _copy_artifacts(artifacts)
    for key, values in protected.items():
        if key == "local_derivatives":
            continue
        blocked = {str(item) for item in values or []}
        current = result.get(key, [])
        if isinstance(current, list):
            result[key] = [item for item in current if str(item) not in blocked]
        elif str(current) in blocked:
            result[key] = None
    return result


def _historical_artifacts(root: Path, record: InstalledPackRecord) -> dict[str, Any]:
    return {
        "manifest_history": list(record.manifest_history),
        "metrics": _path_exists(root / ".cambrian" / "metrics"),
        "benchmark_history": _path_exists(root / ".cambrian" / "benchmarks"),
        "sessions": _path_exists(root / ".cambrian" / "sessions"),
        "requests": _path_exists(root / ".cambrian" / "requests"),
        "proposals": _path_exists(root / ".cambrian" / "proposals"),
    }


def _path_exists(path: Path) -> bool:
    return path.exists() and any(path.rglob("*")) if path.is_dir() else path.exists()


def _remove_removable_artifacts(root: Path, pack_id: str, removable: dict[str, Any]) -> dict[str, Any]:
    removed: dict[str, Any] = {}
    removed["agents"] = _remove_list_entries(default_agent_registry_path(root), "agents", "agent_id", removable.get("agents", []), pack_id)
    removed["teams"] = _remove_list_entries(default_team_presets_path(root), "teams", "name", removable.get("teams", []), pack_id)
    removed["templates"] = _remove_list_entries(default_templates_path(root), "templates", "name", removable.get("templates", []), pack_id)
    removed["benchmarks"] = _remove_worksets(root, removable.get("benchmarks", []), pack_id)
    removed["lane"] = _remove_lane_pack(root, pack_id)
    return {key: value for key, value in removed.items() if value}


def _remove_list_entries(path: Path, list_key: str, name_key: str, names: Any, pack_id: str) -> list[str]:
    wanted = {str(item) for item in names or []}
    if not wanted:
        return []
    payload = _load_yaml(path)
    items = list(payload.get(list_key, []) if isinstance(payload.get(list_key), list) else [])
    kept: list[dict[str, Any]] = []
    removed: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        name = str(item.get(name_key) or item.get("team_id") or item.get("template_id") or "")
        if name in wanted and item.get("source_pack_id") == pack_id:
            removed.append(name)
            continue
        kept.append(item)
    if removed:
        payload[list_key] = kept
        if "updated_at" in payload:
            payload["updated_at"] = _now()
        _save_yaml(path, payload)
    return removed


def _remove_worksets(root: Path, names: Any, pack_id: str) -> list[str]:
    removed: list[str] = []
    for name in names or []:
        path = default_benchmark_worksets_dir(root) / f"workset_{_slug(str(name), 'workset')}.yaml"
        payload = _load_yaml(path)
        if payload.get("source_pack_id") != pack_id:
            continue
        try:
            path.unlink()
            removed.append(str(name))
        except OSError as exc:
            logger.warning("pack uninstall workset removal failed: %s (%s)", path, exc)
    return removed


def _remove_lane_pack(root: Path, pack_id: str) -> list[str]:
    path = default_lane_playbook_path(root)
    payload = _load_yaml(path)
    installed = list(payload.get("installed_lane_packs", []) if isinstance(payload.get("installed_lane_packs"), list) else [])
    kept = [item for item in installed if not (isinstance(item, dict) and item.get("pack_id") == pack_id)]
    if len(kept) == len(installed):
        return []
    payload["installed_lane_packs"] = kept
    payload["updated_at"] = _now()
    _save_yaml(path, payload)
    return [pack_id]


def _render_artifact_map(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, value in payload.items():
        if value in (None, [], {}, ""):
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) or "none"
        elif isinstance(value, dict):
            rendered = ", ".join(f"{subkey}={subvalue}" for subkey, subvalue in value.items() if subvalue) or "none"
        else:
            rendered = str(value)
        lines.append(f"  {key}: {rendered}")
    return lines


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
