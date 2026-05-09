"""현재 하네스 상태와 저장된 템플릿의 bootstrap 차이를 비교한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_templates import (
    HarnessTemplate,
    HarnessTemplateStore,
    default_current_template_path,
    default_templates_path,
    load_current_template,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    """diff report를 안전하게 저장한다."""
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
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


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


def _normalize_value(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, tuple | set):
        return sorted(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return {str(key): _normalize_value(inner) for key, inner in sorted(value.items())}
    if value is None:
        return None
    if isinstance(value, bool | int | float):
        return value
    text = str(value).strip()
    return text or None


def _is_empty(value: Any) -> bool:
    normalized = _normalize_value(value)
    return normalized is None or normalized == [] or normalized == {}


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_template_diff_path(project_root: Path) -> Path:
    """템플릿 diff report 기본 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "diff_report.yaml"


@dataclass
class TemplateDiffEntry:
    """템플릿과 현재 프로젝트의 단일 차이 항목."""

    section: str
    key: str
    status: str
    current_value: Any | None
    template_value: Any | None
    summary: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateDiffReport:
    """템플릿 적용 전 preview report."""

    schema_version: str
    generated_at: str
    report_id: str
    project_name: str | None
    current_template_name: str | None
    target_template_name: str
    mode: str
    entries: list[TemplateDiffEntry]
    summary: dict[str, Any]
    safe_to_apply: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "report_id": self.report_id,
            "project_name": self.project_name,
            "current_template_name": self.current_template_name,
            "target_template_name": self.target_template_name,
            "mode": self.mode,
            "entries": [entry.to_dict() for entry in self.entries],
            "summary": dict(self.summary),
            "safe_to_apply": bool(self.safe_to_apply),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "next_actions": list(self.next_actions),
        }


class TemplateDiffBuilder:
    """현재 bootstrap state와 target template를 비교한다."""

    def build(self, project_root: Path, template_name: str) -> TemplateDiffReport:
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        store = HarnessTemplateStore()
        model = store.load(default_templates_path(root))
        try:
            template = store.find(model, template_name)
        except KeyError as exc:
            raise KeyError(str(exc.args[0])) from exc

        current = _collect_current_defaults(root, warnings)
        current_template = load_current_template(root)
        current_template_name = str(current_template.get("name") or "").strip() or None
        if not current_template_name:
            mode = "no_current_template"
        elif current_template_name == template.name:
            mode = "compare_current"
        else:
            mode = "compare_candidate"

        entries: list[TemplateDiffEntry] = []
        entries.extend(_compare_section("project_defaults", current["project_defaults"], template.project_defaults))
        entries.extend(_compare_section("safety_defaults", current["safety_defaults"], template.safety_defaults))
        entries.extend(_compare_section("agent_defaults", current["agent_defaults"], template.agent_defaults))
        entries.extend(_compare_section("team_defaults", current["team_defaults"], template.team_defaults))
        entries.extend(_compare_section("policy_defaults", current["policy_defaults"], template.policy_defaults))

        summary = _summarize_entries(entries)
        initialized = (root / ".cambrian" / "project.yaml").exists()
        if not initialized:
            warnings.append("template apply currently expects an initialized Cambrian project")
        safe_to_apply = bool(initialized and not errors)
        return TemplateDiffReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            report_id=f"template-diff-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            project_name=current.get("project_name") or root.name,
            current_template_name=current_template_name,
            target_template_name=template.name,
            mode=mode,
            entries=entries,
            summary=summary,
            safe_to_apply=safe_to_apply,
            warnings=_dedupe(warnings),
            errors=errors,
            next_actions=[
                f"cambrian template review {template.name}",
                f"cambrian template accept {template.name}",
                f"cambrian template apply {template.name}",
                f"cambrian template show {template.name}",
            ],
        )


class TemplateDiffStore:
    """템플릿 diff report 저장소."""

    def save(self, report: TemplateDiffReport, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), report.to_dict())

    def load(self, path: Path) -> TemplateDiffReport:
        payload = _load_yaml(Path(path).resolve())
        entries = [
            TemplateDiffEntry(
                section=str(item.get("section", "")),
                key=str(item.get("key", "")),
                status=str(item.get("status", "")),
                current_value=item.get("current_value"),
                template_value=item.get("template_value"),
                summary=str(item.get("summary", "")),
                warnings=[str(value) for value in item.get("warnings", []) if value],
            )
            for item in payload.get("entries", []) or []
            if isinstance(item, dict)
        ]
        return TemplateDiffReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            report_id=str(payload.get("report_id", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            current_template_name=(
                str(payload.get("current_template_name"))
                if payload.get("current_template_name") is not None
                else None
            ),
            target_template_name=str(payload.get("target_template_name", "")),
            mode=str(payload.get("mode", "no_current_template")),
            entries=entries,
            summary=dict(payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}),
            safe_to_apply=bool(payload.get("safe_to_apply", False)),
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
            next_actions=[str(value) for value in payload.get("next_actions", []) if value],
        )


def render_template_diff(report: TemplateDiffReport) -> str:
    """diff report를 사람이 읽는 preview로 렌더링한다."""
    changed_entries = [
        entry
        for entry in report.entries
        if entry.status in {"changed", "missing_in_project"}
    ]
    same_entries = [entry for entry in report.entries if entry.status == "same"]
    project_specific = [
        entry
        for entry in report.entries
        if entry.status in {"missing_in_template", "extra_in_project"}
    ]
    lines = [
        "Template Diff",
        "==================================================",
        "",
        "Template:",
        f"  {report.target_template_name}",
        "",
        "Current template:",
        f"  {report.current_template_name or 'none'}",
    ]
    lines.extend(["", "Would change:"])
    if changed_entries:
        lines.extend([f"  - {entry.summary}" for entry in changed_entries[:10]])
    else:
        lines.append("  - nothing significant in bootstrap defaults")
    if same_entries:
        lines.extend(["", "Would keep:"])
        lines.extend([f"  - {entry.summary}" for entry in same_entries[:8]])
    if project_specific:
        lines.extend(["", "Project-specific values not in template:"])
        lines.extend([f"  - {entry.summary}" for entry in project_specific[:8]])
    lines.extend([
        "",
        "No live state copied:",
        "  - notes",
        "  - lessons",
        "  - sessions",
        "  - adoption history",
    ])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings[:5]])
    lines.extend(["", "Safe to apply preview:", f"  {'yes' if report.safe_to_apply else 'no'}"])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in report.next_actions[:3]])
    return "\n".join(lines)


def _collect_current_defaults(root: Path, warnings: list[str]) -> dict[str, Any]:
    project_defaults = {
        "project_type": None,
        "stack": [],
        "test_command": None,
        "mode": None,
        "primary_use_cases": [],
    }
    safety_defaults: dict[str, Any] = {}
    agent_defaults = {
        "active_agents": [],
        "preferred_lead_agents": [],
        "preferred_support_agents": [],
    }
    team_defaults = {
        "active_team_id": None,
        "backup_teams": [],
        "watched_teams": [],
    }
    policy_defaults = {
        "test_first_practice": False,
        "narrow_change_scope": False,
        "increase_review_support": False,
        "promote_request_focus": [],
    }
    project_name = root.name

    project_path = root / ".cambrian" / "project.yaml"
    if project_path.exists():
        try:
            payload = _load_yaml(project_path)
            project_meta = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
            test_meta = payload.get("test", {}) if isinstance(payload.get("test"), dict) else {}
            ai_work = payload.get("ai_work", {}) if isinstance(payload.get("ai_work"), dict) else {}
            project_name = project_meta.get("name") or project_name
            project_defaults["project_type"] = project_meta.get("type") or project_defaults["project_type"]
            project_defaults["stack"] = _dedupe(_as_list(project_meta.get("stack")) + _as_list(project_defaults["stack"]))
            project_defaults["test_command"] = test_meta.get("command") or project_defaults["test_command"]
            project_defaults["primary_use_cases"] = _dedupe(_as_list(ai_work.get("primary_use_cases")))
        except Exception as exc:
            logger.warning("project defaults diff load failed: %s", exc)
            warnings.append(f"project defaults diff load failed: {exc}")

    profile_path = root / ".cambrian" / "profile.yaml"
    if profile_path.exists():
        try:
            profile = _load_yaml(profile_path)
            project_defaults["mode"] = profile.get("mode") or project_defaults["mode"]
        except Exception as exc:
            warnings.append(f"profile defaults diff load failed: {exc}")

    harness_path = root / ".cambrian" / "harness" / "profile.yaml"
    if harness_path.exists():
        try:
            harness = _load_yaml(harness_path)
            project_name = harness.get("project_name") or project_name
            project_defaults["project_type"] = harness.get("project_type") or project_defaults["project_type"]
            project_defaults["stack"] = _dedupe(_as_list(project_defaults["stack"]) + _as_list(harness.get("stack")))
            project_defaults["test_command"] = harness.get("test_command") or project_defaults["test_command"]
            project_defaults["mode"] = harness.get("mode") or project_defaults["mode"]
            project_defaults["primary_use_cases"] = _dedupe(_as_list(project_defaults["primary_use_cases"]) + _as_list(harness.get("primary_use_cases")))
            safety_defaults = dict(harness.get("safety", {}) if isinstance(harness.get("safety"), dict) else {})
            agent_defaults["active_agents"] = _dedupe(_as_list(harness.get("active_agents")))
        except Exception as exc:
            logger.warning("harness defaults diff load failed: %s", exc)
            warnings.append(f"harness defaults diff load failed: {exc}")

    policy_path = root / ".cambrian" / "harness" / "policy_overlay.yaml"
    if policy_path.exists():
        try:
            policy = _load_yaml(policy_path)
            agent_defaults["preferred_lead_agents"] = _dedupe(_as_list(policy.get("preferred_lead_agents")))
            agent_defaults["preferred_support_agents"] = _dedupe(_as_list(policy.get("preferred_support_agents")))
            policy_defaults["test_first_practice"] = bool(policy.get("test_first_practice"))
            policy_defaults["narrow_change_scope"] = bool(policy.get("narrow_change_scope"))
            policy_defaults["increase_review_support"] = bool(policy.get("increase_review_support"))
            policy_defaults["promote_request_focus"] = _dedupe(_as_list(policy.get("promote_request_focus")))
        except Exception as exc:
            warnings.append(f"harness policy diff load failed: {exc}")

    teams_path = root / ".cambrian" / "agents" / "teams.yaml"
    if teams_path.exists():
        try:
            teams = _load_yaml(teams_path)
            team_defaults["active_team_id"] = teams.get("active_team_id") or team_defaults["active_team_id"]
        except Exception as exc:
            warnings.append(f"team defaults diff load failed: {exc}")

    team_policy_path = root / ".cambrian" / "agents" / "team_policy_overlay.yaml"
    if team_policy_path.exists():
        try:
            team_policy = _load_yaml(team_policy_path)
            team_defaults["active_team_id"] = team_policy.get("current_team_id") or team_defaults["active_team_id"]
            team_defaults["backup_teams"] = _dedupe(_as_list(team_policy.get("backup_teams")))
            team_defaults["watched_teams"] = _dedupe(_as_list(team_policy.get("watched_teams")))
        except Exception as exc:
            warnings.append(f"team policy diff load failed: {exc}")

    return {
        "project_name": project_name,
        "project_defaults": project_defaults,
        "safety_defaults": safety_defaults,
        "agent_defaults": agent_defaults,
        "team_defaults": team_defaults,
        "policy_defaults": policy_defaults,
    }


def _compare_section(section: str, current: dict[str, Any], template: dict[str, Any]) -> list[TemplateDiffEntry]:
    keys = sorted(set(current.keys()) | set(template.keys()))
    entries: list[TemplateDiffEntry] = []
    for key in keys:
        current_value = _normalize_value(current.get(key))
        template_value = _normalize_value(template.get(key))
        status = _entry_status(current_value, template_value)
        entries.append(
            TemplateDiffEntry(
                section=section,
                key=key,
                status=status,
                current_value=current_value,
                template_value=template_value,
                summary=_entry_summary(section, key, status, current_value, template_value),
                warnings=[],
            )
        )
    return entries


def _entry_status(current_value: Any, template_value: Any) -> str:
    current_empty = _is_empty(current_value)
    template_empty = _is_empty(template_value)
    if current_empty and template_empty:
        return "same"
    if current_empty and not template_empty:
        return "missing_in_project"
    if not current_empty and template_empty:
        return "missing_in_template"
    if current_value == template_value:
        return "same"
    return "changed"


def _entry_summary(section: str, key: str, status: str, current_value: Any, template_value: Any) -> str:
    label = f"{section}.{key}".replace("_defaults", "")
    if status == "same":
        return f"{label} stays {_format_value(current_value)}"
    if status == "changed":
        return f"{label} changes from {_format_value(current_value)} to {_format_value(template_value)}"
    if status == "missing_in_project":
        return f"{label} would be set to {_format_value(template_value)}"
    if status == "missing_in_template":
        return f"{label} is project-specific now ({_format_value(current_value)})"
    return f"{label} differs"


def _format_value(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    if isinstance(value, dict):
        return ", ".join(f"{key}={inner}" for key, inner in value.items()) or "none"
    return str(value)


def _summarize_entries(entries: list[TemplateDiffEntry]) -> dict[str, Any]:
    statuses = ["same", "changed", "missing_in_project", "missing_in_template", "extra_in_project"]
    summary = {f"{status}_count": 0 for status in statuses}
    for entry in entries:
        key = f"{entry.status}_count"
        summary[key] = int(summary.get(key, 0) or 0) + 1
    summary["total_entries"] = len(entries)
    return summary
