"""템플릿 라이브러리 운영 결정을 추천/부트스트랩용 policy overlay로 파생한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_library_decisions import (
    TemplateLibraryDecision,
    TemplateLibraryDecisionStore,
    default_template_library_decisions_path,
)
from engine.project_templates import HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
POLICY_KINDS = {"promote", "keep", "backup", "watch", "retire", "clear"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
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


def default_template_library_policy_overlay_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "library_policy_overlay.yaml"


@dataclass
class TemplateLibraryPolicyDecision:
    decision_id: str
    decision_kind: str
    template_name: str
    title: str
    summary: str
    source_ref: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateLibraryPolicyOverlay:
    schema_version: str
    generated_at: str
    promoted_templates: list[str]
    kept_templates: list[str]
    backup_templates: list[str]
    watched_templates: list[str]
    retired_templates: list[str]
    accepted_decisions: list[TemplateLibraryPolicyDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "promoted_templates": list(self.promoted_templates),
            "kept_templates": list(self.kept_templates),
            "backup_templates": list(self.backup_templates),
            "watched_templates": list(self.watched_templates),
            "retired_templates": list(self.retired_templates),
            "accepted_decisions": [decision.to_dict() for decision in self.accepted_decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateLibraryPolicyOverlayBuilder:
    """library_decisions.yaml의 latest decision만 정책 overlay로 변환한다."""

    def build(self, project_root: Path) -> TemplateLibraryPolicyOverlay:
        root = Path(project_root).resolve()
        model = TemplateLibraryDecisionStore().load(default_template_library_decisions_path(root))
        latest_by_template: dict[str, TemplateLibraryDecision] = {}
        for decision in model.decisions:
            if decision.decision_kind in POLICY_KINDS:
                latest_by_template[_slug(decision.template_name)] = decision
        existing_templates = _template_slugs(root)
        warnings = list(model.warnings)
        errors = list(model.errors)
        promoted: list[str] = []
        kept: list[str] = []
        backup: list[str] = []
        watched: list[str] = []
        retired: list[str] = []
        accepted: list[TemplateLibraryPolicyDecision] = []
        for slug, decision in latest_by_template.items():
            if decision.decision_kind == "clear":
                continue
            decision_warnings = list(decision.warnings)
            if existing_templates and slug not in existing_templates:
                warning = f"template library decision references missing template: {decision.template_name}"
                warnings.append(warning)
                decision_warnings.append(warning)
            policy_decision = TemplateLibraryPolicyDecision(
                decision_id=decision.decision_id,
                decision_kind=decision.decision_kind,
                template_name=decision.template_name,
                title=decision.title,
                summary=decision.summary,
                source_ref=decision.source_ref,
                warnings=_dedupe(decision_warnings),
            )
            accepted.append(policy_decision)
            if decision.decision_kind == "promote":
                promoted.append(decision.template_name)
            elif decision.decision_kind == "keep":
                kept.append(decision.template_name)
            elif decision.decision_kind == "backup":
                backup.append(decision.template_name)
            elif decision.decision_kind == "watch":
                watched.append(decision.template_name)
            elif decision.decision_kind == "retire":
                retired.append(decision.template_name)
        return TemplateLibraryPolicyOverlay(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            promoted_templates=_dedupe(promoted),
            kept_templates=_dedupe(kept),
            backup_templates=_dedupe(backup),
            watched_templates=_dedupe(watched),
            retired_templates=_dedupe(retired),
            accepted_decisions=accepted,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )


class TemplateLibraryPolicyStore:
    def save(self, overlay: TemplateLibraryPolicyOverlay, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), overlay.to_dict())

    def load(self, path: Path) -> TemplateLibraryPolicyOverlay:
        payload = _load_yaml(Path(path).resolve())
        return TemplateLibraryPolicyOverlay(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            promoted_templates=[str(value) for value in payload.get("promoted_templates", []) if value],
            kept_templates=[str(value) for value in payload.get("kept_templates", []) if value],
            backup_templates=[str(value) for value in payload.get("backup_templates", []) if value],
            watched_templates=[str(value) for value in payload.get("watched_templates", []) if value],
            retired_templates=[str(value) for value in payload.get("retired_templates", []) if value],
            accepted_decisions=[
                TemplateLibraryPolicyDecision(
                    decision_id=str(item.get("decision_id", "")),
                    decision_kind=str(item.get("decision_kind", "")),
                    template_name=str(item.get("template_name", "")),
                    title=str(item.get("title", "")),
                    summary=str(item.get("summary", "")),
                    source_ref=str(item.get("source_ref")) if item.get("source_ref") is not None else None,
                    warnings=[str(value) for value in item.get("warnings", []) if value],
                )
                for item in payload.get("accepted_decisions", []) or []
                if isinstance(item, dict)
            ],
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


def build_and_save_template_library_policy_overlay(project_root: Path) -> tuple[TemplateLibraryPolicyOverlay, Path]:
    root = Path(project_root).resolve()
    overlay = TemplateLibraryPolicyOverlayBuilder().build(root)
    path = TemplateLibraryPolicyStore().save(overlay, default_template_library_policy_overlay_path(root))
    return overlay, path


def load_or_build_template_library_policy_overlay(
    project_root: Path,
    *,
    save: bool = False,
) -> TemplateLibraryPolicyOverlay:
    root = Path(project_root).resolve()
    path = default_template_library_policy_overlay_path(root)
    if path.exists() and not save:
        try:
            return TemplateLibraryPolicyStore().load(path)
        except Exception as exc:
            logger.warning("template library policy overlay load failed: %s", exc)
    if save:
        overlay, _ = build_and_save_template_library_policy_overlay(root)
        return overlay
    return TemplateLibraryPolicyOverlayBuilder().build(root)


def template_library_policy_by_template(
    overlay: TemplateLibraryPolicyOverlay,
) -> dict[str, TemplateLibraryPolicyDecision]:
    return {
        _slug(decision.template_name): decision
        for decision in overlay.accepted_decisions
        if decision.decision_kind in POLICY_KINDS and decision.decision_kind != "clear"
    }


def template_library_policy_for_template(
    overlay: TemplateLibraryPolicyOverlay,
    template_name: str,
) -> TemplateLibraryPolicyDecision | None:
    return template_library_policy_by_template(overlay).get(_slug(template_name))


def template_library_policy_context(
    project_root: Path,
    overlay: TemplateLibraryPolicyOverlay,
    overlay_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    target = overlay_path or default_template_library_policy_overlay_path(root)
    hints: list[str] = []
    hints.extend([f"{name} is promoted in the local library" for name in overlay.promoted_templates])
    hints.extend([f"{name} is kept in the local library" for name in overlay.kept_templates])
    hints.extend([f"{name} is kept as backup" for name in overlay.backup_templates])
    hints.extend([f"{name} is under watch" for name in overlay.watched_templates])
    hints.extend([f"{name} is retired from default recommendations" for name in overlay.retired_templates])
    return {
        "enabled": True,
        "overlay_ref": _relative_to_project(target, root),
        "promoted_templates": list(overlay.promoted_templates),
        "kept_templates": list(overlay.kept_templates),
        "backup_templates": list(overlay.backup_templates),
        "watched_templates": list(overlay.watched_templates),
        "retired_templates": list(overlay.retired_templates),
        "applied_hints": _dedupe(hints),
    }


def load_template_library_policy_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    try:
        overlay = load_or_build_template_library_policy_overlay(root, save=True)
    except Exception as exc:
        logger.warning("template library policy summary failed: %s", exc)
        return {"warnings": [f"template library policy failed: {exc}"]}
    summary: dict[str, Any] = {
        "promoted": list(overlay.promoted_templates),
        "kept": list(overlay.kept_templates),
        "backup": list(overlay.backup_templates),
        "watch": list(overlay.watched_templates),
        "retire": list(overlay.retired_templates),
        "decision_count": len(overlay.accepted_decisions),
        "overlay_ref": _relative_to_project(default_template_library_policy_overlay_path(root), root),
        "warnings": list(overlay.warnings),
        "errors": list(overlay.errors),
    }
    if template_name:
        decision = template_library_policy_for_template(overlay, template_name)
        summary["template_name"] = template_name
        summary["standing"] = decision.decision_kind if decision else None
        summary["decision_id"] = decision.decision_id if decision else None
    return summary


def render_template_library_policy_summary(summary: dict[str, Any]) -> str:
    lines = ["Template library policy:"]
    rows = [
        ("promoted", "promoted"),
        ("kept", "kept"),
        ("backup", "backup"),
        ("watch", "watch"),
        ("retire", "retire"),
    ]
    has_any = False
    for label, key in rows:
        names = [str(value) for value in summary.get(key, []) if value]
        if names:
            has_any = True
            lines.append(f"  {label:<8}: {', '.join(names[:3])}")
    standing = summary.get("standing")
    template_name = summary.get("template_name")
    if template_name and standing:
        has_any = True
        lines.append(f"  standing: {template_name} ({standing})")
    if not has_any:
        lines.append("  no active library policy")
    warnings = [str(value) for value in summary.get("warnings", []) if value]
    if warnings:
        lines.extend(["", "Policy warnings:"])
        lines.extend([f"  - {warning}" for warning in warnings[:3]])
    return "\n".join(lines)


def _template_slugs(project_root: Path) -> set[str]:
    try:
        model = HarnessTemplateStore().load(default_templates_path(project_root))
    except Exception as exc:
        logger.warning("template store load for library policy failed: %s", exc)
        return set()
    return {_slug(template.name) for template in model.templates}
