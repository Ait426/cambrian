"""템플릿 라이브러리 운영 결정을 로컬 artifact로 관리한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_templates import HarnessTemplate, HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
DECISION_KINDS = {"promote", "keep", "backup", "watch", "retire", "clear"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _slug(value: str | None) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


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


def default_template_library_decisions_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "library_decisions.yaml"


def default_template_library_board_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "library_board.yaml"


def default_template_passport_path(project_root: Path, template_name: str) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "passports" / f"{_slug(template_name)}.yaml"


@dataclass
class TemplateLibraryDecision:
    decision_id: str
    created_at: str
    updated_at: str | None
    decision_kind: str
    template_name: str
    template_id: str | None
    source_kind: str | None
    title: str
    summary: str
    resolution: str | None
    source_ref: str | None
    source_type: str | None
    evidence_refs: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateLibraryDecisionStoreModel:
    schema_version: str
    updated_at: str
    decisions: list[TemplateLibraryDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateLibraryDecisionStore:
    def load(self, path: Path) -> TemplateLibraryDecisionStoreModel:
        target = Path(path).resolve()
        if not target.exists():
            return TemplateLibraryDecisionStoreModel(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                decisions=[],
            )
        payload = _load_yaml(target)
        decisions = [
            _decision_from_dict(item)
            for item in payload.get("decisions", []) or []
            if isinstance(item, dict)
        ]
        return TemplateLibraryDecisionStoreModel(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            decisions=decisions,
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )

    def save(self, path: Path, model: TemplateLibraryDecisionStoreModel) -> Path:
        model.updated_at = _now()
        return _save_yaml(Path(path).resolve(), model.to_dict())

    def add(self, path: Path, decision: TemplateLibraryDecision) -> Path:
        model = self.load(path)
        model.decisions.append(decision)
        return self.save(path, model)


def build_template_library_decision(
    project_root: Path,
    template_name: str,
    decision_kind: str,
    *,
    source_ref: str | None = None,
    resolution: str | None = None,
) -> TemplateLibraryDecision:
    kind = str(decision_kind or "").strip()
    if kind not in DECISION_KINDS:
        raise ValueError(f"unsupported template library decision: {kind}")
    root = Path(project_root).resolve()
    template = _require_template(root, template_name)
    source_type, source_path, evidence_refs, warnings = _find_source(root, template, source_ref)
    title = f"{kind} {template.name}"
    summary = _decision_summary(kind, template.name)
    return TemplateLibraryDecision(
        decision_id=f"template-library-decision-{_timestamp()}-{_slug(template.name)}",
        created_at=_now(),
        updated_at=None,
        decision_kind=kind,
        template_name=template.name,
        template_id=template.template_id,
        source_kind=template.source_kind,
        title=title,
        summary=summary,
        resolution=resolution,
        source_ref=source_path,
        source_type=source_type,
        evidence_refs=_dedupe(evidence_refs),
        warnings=_dedupe(warnings),
        errors=[],
    )


def current_library_decision_by_template(project_root: Path) -> dict[str, TemplateLibraryDecision]:
    model = TemplateLibraryDecisionStore().load(default_template_library_decisions_path(project_root))
    current: dict[str, TemplateLibraryDecision] = {}
    for decision in model.decisions:
        current[_slug(decision.template_name)] = decision
    return current


def load_template_library_decision_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    model = TemplateLibraryDecisionStore().load(default_template_library_decisions_path(root))
    decisions = list(model.decisions)
    if template_name:
        wanted = _slug(template_name)
        decisions = [decision for decision in decisions if _slug(decision.template_name) == wanted]
    latest_by_template: dict[str, TemplateLibraryDecision] = {}
    for decision in decisions:
        latest_by_template[_slug(decision.template_name)] = decision
    current = list(latest_by_template.values())
    by_kind: dict[str, list[str]] = {kind: [] for kind in DECISION_KINDS}
    for decision in current:
        by_kind.setdefault(decision.decision_kind, []).append(decision.template_name)
    latest = decisions[-1] if decisions else None
    return {
        "total": len(decisions),
        "current_count": len(current),
        "promoted": by_kind.get("promote", []),
        "kept": by_kind.get("keep", []),
        "backup": by_kind.get("backup", []),
        "watch": by_kind.get("watch", []),
        "retire": by_kind.get("retire", []),
        "latest_kind": latest.decision_kind if latest else None,
        "latest_template": latest.template_name if latest else None,
        "decisions_path": _relative_to_project(default_template_library_decisions_path(root), root),
    }


def render_template_library_decision(decision: TemplateLibraryDecision, recorded_path: str) -> str:
    action = {
        "promote": "promoted",
        "keep": "kept",
        "backup": "marked as backup",
        "watch": "marked for watch",
        "retire": "retired",
        "clear": "cleared",
    }.get(decision.decision_kind, decision.decision_kind)
    lines = [
        f"Template {action}.",
        "",
        "Template:",
        f"  {decision.template_name}",
        "",
        "Meaning:",
        f"  {decision.summary}",
    ]
    if decision.resolution:
        lines.extend(["", "Resolution:", f"  {decision.resolution}"])
    if decision.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in decision.warnings])
    lines.extend(["", "Recorded:", f"  {recorded_path}"])
    return "\n".join(lines)


def render_template_library_decisions(model: TemplateLibraryDecisionStoreModel) -> str:
    latest_by_template: dict[str, TemplateLibraryDecision] = {}
    for decision in model.decisions:
        latest_by_template[_slug(decision.template_name)] = decision
    by_kind: dict[str, list[str]] = {kind: [] for kind in DECISION_KINDS}
    for decision in latest_by_template.values():
        by_kind.setdefault(decision.decision_kind, []).append(decision.template_name)
    lines = ["Template Library Decisions", "=================================================="]
    sections = [
        ("Promoted:", "promote"),
        ("Kept:", "keep"),
        ("Backup:", "backup"),
        ("Watch:", "watch"),
        ("Retire:", "retire"),
        ("Cleared:", "clear"),
    ]
    for title, kind in sections:
        lines.extend(["", title])
        names = by_kind.get(kind, [])
        if names:
            lines.extend([f"  - {name}" for name in names])
        else:
            lines.append("  none")
    return "\n".join(lines)


def render_template_library_decision_summary(summary: dict[str, Any]) -> str:
    lines = ["Template library decisions:"]
    mapping = [
        ("promoted", "promoted"),
        ("backup", "backup"),
        ("watch", "watch"),
        ("retire", "retire"),
        ("clear", "clear"),
    ]
    has_any = False
    for label, key in mapping:
        names = [str(value) for value in summary.get(key, []) if value]
        if names:
            has_any = True
            lines.append(f"  {label:<8}: {', '.join(names[:3])}")
    if not has_any:
        lines.append("  none")
    latest_template = summary.get("latest_template")
    latest_kind = summary.get("latest_kind")
    if latest_template and latest_kind:
        lines.append(f"  latest  : {latest_template} ({latest_kind})")
    return "\n".join(lines)


def _require_template(root: Path, template_name: str) -> HarnessTemplate:
    model = HarnessTemplateStore().load(default_templates_path(root))
    return HarnessTemplateStore().find(model, template_name)


def _find_source(
    root: Path,
    template: HarnessTemplate,
    explicit_source: str | None,
) -> tuple[str | None, str | None, list[str], list[str]]:
    warnings: list[str] = []
    evidence_refs: list[str] = []
    if explicit_source:
        source_path = Path(explicit_source)
        if not source_path.is_absolute():
            source_path = root / source_path
        if not source_path.exists():
            warnings.append(f"explicit source not found: {explicit_source}")
        source_ref = _relative_to_project(source_path, root)
        evidence_refs.append(source_ref)
        return "standalone" if not source_path.exists() else _source_type_from_path(source_path), source_ref, evidence_refs, warnings
    board_path = default_template_library_board_path(root)
    if _board_mentions_template(board_path, template.name):
        source_ref = _relative_to_project(board_path, root)
        evidence_refs.append(source_ref)
        return "library_board", source_ref, evidence_refs, warnings
    passport_path = default_template_passport_path(root, template.name)
    if passport_path.exists():
        source_ref = _relative_to_project(passport_path, root)
        evidence_refs.append(source_ref)
        return "template_history", source_ref, evidence_refs, warnings
    warnings.append("library decision recorded without saved board or history evidence")
    return "standalone", None, evidence_refs, warnings


def _board_mentions_template(path: Path, template_name: str) -> bool:
    if not path.exists():
        return False
    try:
        payload = _load_yaml(path)
    except Exception as exc:
        logger.warning("library board source load failed: %s", exc)
        return False
    wanted = _slug(template_name)
    for item in payload.get("entries", []) or []:
        if isinstance(item, dict) and _slug(str(item.get("template_name", ""))) == wanted:
            return True
    for key in ("preferred_templates", "strong_alternatives", "promising_imported", "watch_templates", "retire_candidates"):
        if any(_slug(str(value)) == wanted for value in payload.get(key, []) or []):
            return True
    return False


def _source_type_from_path(path: Path) -> str:
    name = path.name.lower()
    if name == "library_board.yaml":
        return "library_board"
    if "passport" in str(path).lower():
        return "template_history"
    return "standalone"


def _decision_summary(kind: str, template_name: str) -> str:
    return {
        "promote": f"{template_name} will get a small preferred-library bias when future fits are close.",
        "keep": f"{template_name} stays trusted in the local template library.",
        "backup": f"{template_name} will be surfaced as a fallback or strong alternative when fits are close.",
        "watch": f"{template_name} remains visible but monitored with caution.",
        "retire": f"{template_name} stays in the library, but is de-emphasized as a preferred choice.",
        "clear": f"{template_name} returns to neutral library standing.",
    }.get(kind, f"{template_name} library standing recorded as {kind}.")


def _decision_from_dict(payload: dict[str, Any]) -> TemplateLibraryDecision:
    return TemplateLibraryDecision(
        decision_id=str(payload.get("decision_id", "")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        decision_kind=str(payload.get("decision_kind", "")),
        template_name=str(payload.get("template_name", "")),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        title=str(payload.get("title", "")),
        summary=str(payload.get("summary", "")),
        resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
        source_ref=str(payload.get("source_ref")) if payload.get("source_ref") is not None else None,
        source_type=str(payload.get("source_type")) if payload.get("source_type") is not None else None,
        evidence_refs=[str(value) for value in payload.get("evidence_refs", []) if value],
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )
