"""프로젝트 사이에서 하네스 템플릿을 내보내고 가져오는 로컬 전송 계층."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_templates import (
    HarnessTemplate,
    HarnessTemplateStore,
    default_templates_path,
)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _slug(value: str) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_template_exports_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "exports"


def default_template_imported_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "imported"


def imported_template_record_path(project_root: Path, template_name: str) -> Path:
    return default_template_imported_dir(project_root) / f"{_slug(template_name)}.yaml"


@dataclass
class ExportedHarnessTemplate:
    schema_version: str
    exported_at: str
    export_id: str
    name: str
    template_id: str
    template_kind: str
    source_project_name: str | None
    source_harness_id: str | None
    description: str | None
    tags: list[str]
    project_defaults: dict[str, Any]
    safety_defaults: dict[str, Any]
    agent_defaults: dict[str, Any]
    team_defaults: dict[str, Any]
    policy_defaults: dict[str, Any]
    fit_hints: list[str]
    source_refs: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImportedTemplateRecord:
    imported_at: str
    import_id: str
    name: str
    template_id: str | None
    template_kind: str | None
    source_export_path: str
    source_project_name: str | None
    source_harness_id: str | None
    source_kind: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HarnessTemplateExporter:
    def export(self, project_root: Path, template_name: str, out_path: Path | None = None) -> Path:
        root = Path(project_root).resolve()
        store = HarnessTemplateStore()
        model = store.load(default_templates_path(root))
        template = store.find(model, template_name)
        exported = _exported_from_template(root, template)
        target = Path(out_path).resolve() if out_path is not None else (
            default_template_exports_dir(root) / f"{_slug(template.name)}_{_stamp()}.yaml"
        )
        return _save_yaml(target, exported.to_dict())


class HarnessTemplateImporter:
    def import_template(
        self,
        project_root: Path,
        template_path: Path,
        as_name: str | None = None,
    ) -> ImportedTemplateRecord:
        root = Path(project_root).resolve()
        source_path = Path(template_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(str(source_path))
        exported = _exported_from_dict(_load_yaml(source_path))
        store = HarnessTemplateStore()
        store_path = default_templates_path(root)
        model = store.load(store_path)
        target_name = str(as_name or exported.name).strip()
        if not target_name:
            raise ValueError("template import requires a target name")
        target_id = exported.template_id if target_name == exported.name else _slug(target_name)
        _ensure_no_conflict(model.templates, target_name, target_id)
        record = ImportedTemplateRecord(
            imported_at=_now(),
            import_id=f"template-import-{_stamp()}-{_slug(target_name)[:12]}",
            name=target_name,
            template_id=target_id,
            template_kind=exported.template_kind,
            source_export_path=str(source_path),
            source_project_name=exported.source_project_name,
            source_harness_id=exported.source_harness_id,
            source_kind="imported",
        )
        imported_ref = imported_template_record_path(root, target_name)
        origin_ref = _relative_to_project(imported_ref, root)
        imported_template = HarnessTemplate(
            schema_version=SCHEMA_VERSION,
            template_id=target_id,
            name=target_name,
            created_at=_now(),
            updated_at=None,
            description=exported.description,
            source_project_name=exported.source_project_name,
            source_harness_id=exported.source_harness_id,
            template_kind=exported.template_kind,
            tags=list(exported.tags),
            project_defaults=dict(exported.project_defaults),
            safety_defaults=dict(exported.safety_defaults),
            agent_defaults=dict(exported.agent_defaults),
            team_defaults=dict(exported.team_defaults),
            policy_defaults=dict(exported.policy_defaults),
            fit_hints=list(exported.fit_hints),
            warnings=list(exported.warnings),
            errors=list(exported.errors),
            source_kind="imported",
            source_origin={
                "source_project_name": exported.source_project_name,
                "source_harness_id": exported.source_harness_id,
                "source_export_path": str(source_path),
                "source_export_ref": origin_ref,
                "import_id": record.import_id,
            },
        )
        _save_yaml(
            imported_ref,
            {
                "schema_version": SCHEMA_VERSION,
                "record": record.to_dict(),
                "template": imported_template.to_dict(),
                "exported_template": exported.to_dict(),
            },
        )
        model.templates.append(imported_template)
        store.save(model, store_path)
        return record


def _exported_from_template(root: Path, template: HarnessTemplate) -> ExportedHarnessTemplate:
    return ExportedHarnessTemplate(
        schema_version=SCHEMA_VERSION,
        exported_at=_now(),
        export_id=f"template-export-{_stamp()}-{_slug(template.name)[:12]}",
        name=template.name,
        template_id=template.template_id,
        template_kind=template.template_kind,
        source_project_name=template.source_project_name,
        source_harness_id=template.source_harness_id,
        description=template.description,
        tags=list(template.tags),
        project_defaults=dict(template.project_defaults),
        safety_defaults=dict(template.safety_defaults),
        agent_defaults=dict(template.agent_defaults),
        team_defaults=dict(template.team_defaults),
        policy_defaults=dict(template.policy_defaults),
        fit_hints=list(template.fit_hints),
        source_refs={
            "template_store": _relative_to_project(default_templates_path(root), root),
            "source_kind": template.source_kind,
            "source_origin": dict(template.source_origin),
        },
        warnings=list(template.warnings),
        errors=list(template.errors),
    )


def _exported_from_dict(payload: dict[str, Any]) -> ExportedHarnessTemplate:
    required = [
        "name",
        "template_id",
        "template_kind",
        "project_defaults",
        "safety_defaults",
        "agent_defaults",
        "team_defaults",
        "policy_defaults",
    ]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"invalid template export, missing: {', '.join(missing)}")
    return ExportedHarnessTemplate(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        exported_at=str(payload.get("exported_at", "")),
        export_id=str(payload.get("export_id", "")),
        name=str(payload.get("name", "")),
        template_id=str(payload.get("template_id", "")),
        template_kind=str(payload.get("template_kind", "harness")),
        source_project_name=(
            str(payload.get("source_project_name"))
            if payload.get("source_project_name") is not None
            else None
        ),
        source_harness_id=(
            str(payload.get("source_harness_id"))
            if payload.get("source_harness_id") is not None
            else None
        ),
        description=str(payload.get("description")) if payload.get("description") is not None else None,
        tags=[str(value) for value in payload.get("tags", []) if value],
        project_defaults=dict(payload.get("project_defaults", {}) if isinstance(payload.get("project_defaults"), dict) else {}),
        safety_defaults=dict(payload.get("safety_defaults", {}) if isinstance(payload.get("safety_defaults"), dict) else {}),
        agent_defaults=dict(payload.get("agent_defaults", {}) if isinstance(payload.get("agent_defaults"), dict) else {}),
        team_defaults=dict(payload.get("team_defaults", {}) if isinstance(payload.get("team_defaults"), dict) else {}),
        policy_defaults=dict(payload.get("policy_defaults", {}) if isinstance(payload.get("policy_defaults"), dict) else {}),
        fit_hints=[str(value) for value in payload.get("fit_hints", []) if value],
        source_refs=dict(payload.get("source_refs", {}) if isinstance(payload.get("source_refs"), dict) else {}),
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )


def _ensure_no_conflict(templates: list[HarnessTemplate], target_name: str, target_id: str) -> None:
    for template in templates:
        if template.name == target_name:
            raise ValueError(f"template name already exists: {target_name}. Use --as <new-name> to import under a new name.")
        if template.template_id == target_id:
            raise ValueError(f"template id already exists: {target_id}. Use --as <new-name> to import under a new name.")


def render_template_export(path: Path, payload: dict[str, Any]) -> str:
    return "\n".join([
        "Template exported.",
        "",
        "Template:",
        f"  {payload.get('name') or 'unknown'}",
        "",
        "Source project:",
        f"  {payload.get('source_project_name') or 'unknown'}",
        "",
        "Saved:",
        f"  {path}",
    ])


def render_template_import(record: ImportedTemplateRecord, imported_path: Path, project_root: Path) -> str:
    imported_ref = _relative_to_project(imported_path, project_root)
    return "\n".join([
        "Template imported.",
        "",
        "Template:",
        f"  {record.name}",
        "",
        "Source project:",
        f"  {record.source_project_name or 'unknown'}",
        "",
        "Saved:",
        f"  {imported_ref}",
        "",
        "Next:",
        f"  cambrian template show {record.name}",
        "  cambrian template recommend",
    ])
