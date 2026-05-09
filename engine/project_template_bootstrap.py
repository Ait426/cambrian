"""템플릿 기반 프로젝트 bootstrap provenance와 안전한 기본값 주입."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from engine.project_harness import HarnessProfileBuilder, HarnessProfileStore, default_harness_profile_path
from engine.project_harness_decisions import (
    HarnessDecision,
    HarnessDecisionStore,
    default_harness_decisions_path,
)
from engine.project_harness_policy import (
    build_and_save_policy_overlay,
)
from engine.project_team_decisions import (
    TeamDecision,
    TeamDecisionStore,
    default_team_decisions_path,
)
from engine.project_team_policy import build_and_save_team_policy_overlay
from engine.project_teams import TeamPreset, TeamPresetStore, default_team_presets_path
from engine.project_templates import (
    HarnessTemplate,
    HarnessTemplateStore,
    default_current_template_path,
    default_templates_path,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일/ID에 쓰기 좋은 UTC timestamp를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _atomic_write_text(path: Path, content: str) -> None:
    """텍스트 파일을 원자적으로 저장한다."""
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
    """YAML 파일을 dict로 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """dict payload를 YAML로 저장한다."""
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _as_list(value: Any) -> list[str]:
    """문자열/리스트 기본값을 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        joined = "".join(items)
        if items and all(len(item) == 1 for item in items) and joined in {"python", "pytest"}:
            return [joined]
        return items
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


def _slug(value: str) -> str:
    """사람이 읽는 이름을 안전한 id 토큰으로 바꾼다."""
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def default_template_bootstrap_path(project_root: Path) -> Path:
    """템플릿 bootstrap provenance 기본 저장 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "bootstrap_record.yaml"


@dataclass
class TemplateBootstrapRecord:
    """init --template로 적용한 bootstrap provenance."""

    schema_version: str
    bootstrap_id: str
    created_at: str
    template_name: str
    template_id: str | None
    template_kind: str | None
    project_name: str | None
    workspace: str
    applied_defaults: dict[str, Any]
    source_template_ref: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class TemplateBootstrapBuilder:
    """템플릿에서 init bootstrap record를 만든다."""

    def build(self, project_root: Path, template_name: str) -> TemplateBootstrapRecord:
        """템플릿 기본값 snapshot을 provenance record로 만든다."""
        root = Path(project_root).resolve()
        template = load_template_for_bootstrap(root, template_name)
        project_name = _project_name(root)
        bootstrap_choice = _load_bootstrap_choice(root)
        applied_defaults = {
            "project_defaults": dict(template.project_defaults),
            "safety_defaults": dict(template.safety_defaults),
            "agent_defaults": dict(template.agent_defaults),
            "team_defaults": dict(template.team_defaults),
            "policy_defaults": dict(template.policy_defaults),
        }
        if bootstrap_choice:
            applied_defaults["bootstrap_choice"] = bootstrap_choice
        return TemplateBootstrapRecord(
            schema_version=SCHEMA_VERSION,
            bootstrap_id=f"template-bootstrap-{_stamp()}-{_slug(template.name)[:12]}",
            created_at=_now(),
            template_name=template.name,
            template_id=template.template_id,
            template_kind=template.template_kind,
            project_name=project_name,
            workspace=str(root),
            applied_defaults=applied_defaults,
            source_template_ref=_relative_to_project(default_templates_path(root), root),
        )


class TemplateBootstrapStore:
    """템플릿 bootstrap provenance 저장소."""

    def save(self, record: TemplateBootstrapRecord, path: Path) -> Path:
        """record를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(target, yaml.safe_dump(record.to_dict(), allow_unicode=True, sort_keys=False))
        return target

    def load(self, path: Path) -> TemplateBootstrapRecord:
        """저장된 bootstrap record를 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        return TemplateBootstrapRecord(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            bootstrap_id=str(payload.get("bootstrap_id", "")),
            created_at=str(payload.get("created_at", "")),
            template_name=str(payload.get("template_name", "")),
            template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
            template_kind=str(payload.get("template_kind")) if payload.get("template_kind") is not None else None,
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            workspace=str(payload.get("workspace", "")),
            applied_defaults=dict(payload.get("applied_defaults", {}) if isinstance(payload.get("applied_defaults"), dict) else {}),
            source_template_ref=(
                str(payload.get("source_template_ref"))
                if payload.get("source_template_ref") is not None
                else None
            ),
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


def load_template_for_bootstrap(project_root: Path, template_name: str) -> HarnessTemplate:
    """현재 로컬 template store에서 bootstrap 대상 template를 찾는다."""
    root = Path(project_root).resolve()
    store = HarnessTemplateStore()
    model = store.load(default_templates_path(root))
    return store.find(model, template_name)


def template_init_defaults(project_root: Path, template_name: str) -> dict[str, Any]:
    """init CLI에 주입할 template default 값을 만든다."""
    template = load_template_for_bootstrap(Path(project_root), template_name)
    project_defaults = dict(template.project_defaults)
    return {
        "project_type": project_defaults.get("project_type"),
        "stack": _as_list(project_defaults.get("stack")),
        "test_command": project_defaults.get("test_command"),
        "primary_use_cases": _as_list(project_defaults.get("primary_use_cases")),
        "mode": project_defaults.get("mode"),
    }


def apply_template_bootstrap(project_root: Path, template_name: str) -> dict[str, Any]:
    """초기화 직후 template defaults를 .cambrian 운영 artifact에 반영한다."""
    root = Path(project_root).resolve()
    if not (root / ".cambrian" / "project.yaml").exists():
        raise FileNotFoundError("Cambrian project mode is not initialized")
    template = load_template_for_bootstrap(root, template_name)
    warnings: list[str] = []
    updated_paths: list[str] = []

    updated_paths.extend(_apply_project_defaults(root, template))
    updated_paths.extend(_apply_profile_defaults(root, template))
    updated_paths.extend(_apply_harness_defaults(root, template, warnings))
    updated_paths.extend(_apply_team_defaults(root, template, warnings))
    updated_paths.extend(_seed_harness_policy_decisions(root, template))
    updated_paths.extend(_seed_team_decisions(root, template))

    try:
        _policy_overlay, policy_path = build_and_save_policy_overlay(root)
        updated_paths.append(_relative_to_project(policy_path, root))
    except Exception as exc:
        logger.warning("template bootstrap policy overlay build failed: %s", exc)
        warnings.append(f"policy overlay build failed: {exc}")
    try:
        _team_overlay, team_policy_path = build_and_save_team_policy_overlay(root)
        updated_paths.append(_relative_to_project(team_policy_path, root))
    except Exception as exc:
        logger.warning("template bootstrap team policy overlay build failed: %s", exc)
        warnings.append(f"team policy overlay build failed: {exc}")

    current_path = _save_current_template(root, template)
    updated_paths.append(_relative_to_project(current_path, root))

    record = TemplateBootstrapBuilder().build(root, template.name)
    record.warnings.extend(warnings)
    record_path = TemplateBootstrapStore().save(record, default_template_bootstrap_path(root))
    updated_paths.append(_relative_to_project(record_path, root))
    try:
        from engine.project_template_canary_ledger import record_canary_template_bootstrap

        record_canary_template_bootstrap(root, template.name, source_ref=_relative_to_project(record_path, root))
    except Exception as exc:
        logger.warning("canary template bootstrap ledger event failed: %s", exc)

    _mark_template_active(root, template)
    updated_paths.append(_relative_to_project(default_templates_path(root), root))

    return {
        "status": "bootstrapped",
        "template": template.to_dict(),
        "bootstrap_record": record.to_dict(),
        "bootstrap_record_path": _relative_to_project(record_path, root),
        "current_template_path": _relative_to_project(default_current_template_path(root), root),
        "updated_paths": _dedupe(updated_paths),
        "warnings": warnings,
    }


def load_template_bootstrap(project_root: Path) -> dict[str, Any]:
    """저장된 bootstrap record를 가볍게 dict로 읽는다."""
    path = default_template_bootstrap_path(project_root)
    if not path.exists():
        return {}
    try:
        return TemplateBootstrapStore().load(path).to_dict()
    except Exception as exc:
        logger.warning("template bootstrap record load failed: %s", exc)
        return {"warnings": [f"template bootstrap record load failed: {exc}"]}


def _load_bootstrap_choice(project_root: Path) -> dict[str, Any]:
    """선택 provenance를 bootstrap record에 snapshot으로 포함한다."""
    try:
        from engine.project_template_bootstrap_select import load_template_bootstrap_choice

        choice = load_template_bootstrap_choice(project_root)
    except Exception as exc:
        logger.warning("template bootstrap choice snapshot failed: %s", exc)
        return {"warnings": [f"template bootstrap choice snapshot failed: {exc}"]}
    return choice if isinstance(choice, dict) else {}


def render_template_bootstrap_summary(record: dict[str, Any]) -> str:
    """bootstrap origin을 사람이 읽기 좋게 렌더링한다."""
    if not record:
        return "Template origin:\n  none"
    template_name = record.get("template_name") or "unknown"
    lines = [
        "Template origin:",
        f"  {template_name} (bootstrap)",
    ]
    choice = (
        record.get("applied_defaults", {}).get("bootstrap_choice", {})
        if isinstance(record.get("applied_defaults"), dict)
        else {}
    )
    if isinstance(choice, dict) and choice.get("selection_mode"):
        mode = str(choice.get("selection_mode"))
        label = {
            "recommended": "recommended template",
            "explicit": "explicit template",
            "manual_choice": "manual choice",
            "skipped": "skipped",
        }.get(mode, mode)
        lines.append(f"  selected via {label}")
    return "\n".join(lines)


def render_template_bootstrap_apply(result: dict[str, Any]) -> str:
    """init --template 적용 결과를 사람이 읽기 좋게 렌더링한다."""
    template = result.get("template", {}) if isinstance(result.get("template"), dict) else {}
    lines = [
        "Template bootstrap applied.",
        "",
        "Template:",
        f"  {template.get('name') or 'unknown'}",
        "",
        "Recorded:",
        f"  {result.get('bootstrap_record_path')}",
    ]
    warnings = [str(value) for value in result.get("warnings", []) if value]
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in warnings])
    return "\n".join(lines)


def render_initialized_template_block(template_name: str) -> str:
    """이미 초기화된 프로젝트에서 init --template를 막을 때 안내 문구."""
    return "\n".join([
        "Cambrian is already fitted to this project.",
        "",
        "Use:",
        f"  cambrian template diff {template_name}",
        f"  cambrian template review {template_name}",
        f"  cambrian template accept {template_name}",
        f"  cambrian template apply {template_name}",
    ])


def _project_name(root: Path) -> str:
    project_path = root / ".cambrian" / "project.yaml"
    if not project_path.exists():
        return root.name
    try:
        payload = _load_yaml(project_path)
    except Exception:
        return root.name
    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    return str(project.get("name") or root.name)


def _apply_project_defaults(root: Path, template: HarnessTemplate) -> list[str]:
    project_path = root / ".cambrian" / "project.yaml"
    payload = _load_yaml(project_path)
    defaults = dict(template.project_defaults)
    project = payload.setdefault("project", {})
    if isinstance(project, dict):
        if not project.get("type"):
            project["type"] = defaults.get("project_type") or project.get("type")
        if not project.get("stack"):
            project["stack"] = _as_list(defaults.get("stack"))
    test = payload.setdefault("test", {})
    if isinstance(test, dict) and not test.get("command"):
        test["command"] = defaults.get("test_command")
    ai_work = payload.setdefault("ai_work", {})
    if isinstance(ai_work, dict) and not ai_work.get("primary_use_cases"):
        ai_work["primary_use_cases"] = list(defaults.get("primary_use_cases", []) or [])
    safety = payload.setdefault("safety", {})
    if isinstance(safety, dict):
        safety.update({key: value for key, value in template.safety_defaults.items() if key not in safety})
    _save_yaml(project_path, payload)
    return [_relative_to_project(project_path, root)]


def _apply_profile_defaults(root: Path, template: HarnessTemplate) -> list[str]:
    profile_path = root / ".cambrian" / "profile.yaml"
    payload = _load_yaml(profile_path)
    mode = template.project_defaults.get("mode")
    if mode and (not payload.get("mode") or payload.get("mode") == "balanced"):
        payload["mode"] = mode
    origin = payload.setdefault("template_origin", {})
    if isinstance(origin, dict):
        origin.update(
            {
                "template_id": template.template_id,
                "name": template.name,
                "origin": "bootstrap",
                "bootstrapped_at": _now(),
            }
        )
    _save_yaml(profile_path, payload)
    return [_relative_to_project(profile_path, root)]


def _apply_harness_defaults(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[str]:
    harness_path = default_harness_profile_path(root)
    if harness_path.exists():
        harness = HarnessProfileStore().load(harness_path)
    else:
        harness = HarnessProfileBuilder().build(root)
    defaults = dict(template.project_defaults)
    harness.project_type = defaults.get("project_type") or harness.project_type
    stack = _as_list(defaults.get("stack"))
    if stack:
        harness.stack = stack
    harness.test_command = defaults.get("test_command") or harness.test_command
    harness.mode = defaults.get("mode") or harness.mode
    use_cases = _as_list(defaults.get("primary_use_cases"))
    if use_cases:
        harness.primary_use_cases = use_cases
    if template.safety_defaults:
        harness.safety = dict(template.safety_defaults)
    active_agents = [str(item) for item in template.agent_defaults.get("active_agents", []) if item]
    if active_agents:
        present = _present_agent_ids(root, harness)
        filtered = [agent_id for agent_id in active_agents if agent_id in present]
        missing = [agent_id for agent_id in active_agents if agent_id not in present]
        if missing:
            warnings.append(f"template agents missing in this project: {', '.join(missing)}")
        if filtered:
            harness.active_agents = _dedupe(filtered)
    HarnessProfileStore().save(harness, harness_path)
    _refresh_registry_status(root, harness, warnings)
    return [
        _relative_to_project(harness_path, root),
        _relative_to_project(default_agent_registry_path(root), root),
    ]


def _apply_team_defaults(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[str]:
    saved_teams = [
        item
        for item in template.team_defaults.get("saved_teams", []) or []
        if isinstance(item, dict)
    ]
    if not saved_teams:
        return []
    teams_path = default_team_presets_path(root)
    store = TeamPresetStore()
    model = store.load(teams_path)
    existing_ids = {team.team_id for team in model.teams}
    existing_names = {team.name for team in model.teams}
    for item in saved_teams:
        team = _team_from_dict(item)
        if team.team_id in existing_ids or team.name in existing_names:
            continue
        model.teams.append(team)
        existing_ids.add(team.team_id)
        existing_names.add(team.name)
    active_team_id = str(template.team_defaults.get("active_team_id") or "").strip()
    if active_team_id:
        if any(team.team_id == active_team_id for team in model.teams):
            model.active_team_id = active_team_id
        else:
            warnings.append(f"template active team missing after bootstrap: {active_team_id}")
    store.save(model, teams_path)
    return [_relative_to_project(teams_path, root)]


def _seed_harness_policy_decisions(root: Path, template: HarnessTemplate) -> list[str]:
    policy = dict(template.policy_defaults)
    decision_specs: list[tuple[str, str | None, str]] = []
    for key in (
        "strengthen_test_practice",
        "narrow_change_scope",
        "increase_review_support",
        "caution_memory_review",
        "note_followup",
    ):
        if policy.get(key):
            decision_specs.append((key, None, key.replace("_", " ")))
    for focus in [str(item) for item in policy.get("promote_request_focus", []) if item]:
        decision_specs.append(("promote_request_focus", focus, f"promote request focus: {focus}"))
    for agent_id in [str(item) for item in template.agent_defaults.get("preferred_lead_agents", []) if item]:
        decision_specs.append(("prefer_lead", agent_id, f"prefer lead agent {agent_id}"))
    for agent_id in [str(item) for item in template.agent_defaults.get("preferred_support_agents", []) if item]:
        decision_specs.append(("prefer_support", agent_id, f"prefer support agent {agent_id}"))
    for agent_id in [str(item) for item in template.agent_defaults.get("backup_agents", []) if item]:
        decision_specs.append(("keep_as_backup", agent_id, f"keep {agent_id} as backup"))
    for agent_id in [str(item) for item in template.agent_defaults.get("watched_agents", []) if item]:
        decision_specs.append(("watch_candidate", agent_id, f"watch candidate {agent_id}"))
    if not decision_specs:
        return []
    store = HarnessDecisionStore()
    path = default_harness_decisions_path(root)
    for kind, target, title in decision_specs:
        suggestion_key = f"template-bootstrap-{template.template_id}-{kind}-{target or 'none'}"
        store.add(
            path,
            HarnessDecision(
                decision_id=f"decision-{_stamp()}-{_slug(kind)[:12]}",
                suggestion_id=suggestion_key,
                created_at=_now(),
                updated_at=None,
                status="accepted",
                kind=kind,
                target=target,
                title=title,
                summary=f"Seeded from template bootstrap: {template.name}",
                resolution="accepted through init --template bootstrap",
                source_report_ref=".cambrian/templates/bootstrap_record.yaml",
                evidence_refs=[".cambrian/templates/templates.yaml"],
                operational_effect={"type": "none", "applied": False, "details": {}},
                tags=["template_bootstrap"],
                warnings=[],
                errors=[],
            ),
        )
    return [_relative_to_project(path, root)]


def _seed_team_decisions(root: Path, template: HarnessTemplate) -> list[str]:
    team_defaults = dict(template.team_defaults)
    active_team_id = str(team_defaults.get("active_team_id") or "").strip()
    active_team_name = str(team_defaults.get("active_team_name") or active_team_id).strip() or None
    specs: list[tuple[str, str, str | None]] = []
    if active_team_id:
        specs.append(("apply_team", active_team_id, active_team_name))
    for name in [str(item) for item in team_defaults.get("backup_teams", []) if item]:
        specs.append(("keep_as_backup", _slug(name), name))
    for name in [str(item) for item in team_defaults.get("watched_teams", []) if item]:
        specs.append(("watch_team", _slug(name), name))
    if not specs:
        return []
    store = TeamDecisionStore()
    path = default_team_decisions_path(root)
    model = store.load(path)
    existing = {
        (decision.status, decision.decision_kind, decision.target_team_id)
        for decision in model.decisions
    }
    for kind, team_id, team_name in specs:
        if ("accepted", kind, team_id) in existing:
            continue
        model.decisions.append(
            TeamDecision(
                decision_id=f"team-decision-{_stamp()}-{_slug(team_id)[:12]}",
                created_at=_now(),
                updated_at=None,
                status="accepted",
                decision_kind=kind,
                target_team_id=team_id,
                target_team_name=team_name,
                title=f"{kind} {team_name or team_id}",
                summary=f"Seeded from template bootstrap: {template.name}",
                resolution="accepted through init --template bootstrap",
                source_ref=".cambrian/templates/bootstrap_record.yaml",
                source_type="template_bootstrap",
                evidence_refs=[".cambrian/templates/templates.yaml"],
                operational_effect={
                    "type": "template_bootstrap",
                    "applied": kind == "apply_team",
                    "details": {"template": template.name},
                },
                warnings=[],
                errors=[],
            )
        )
        if kind == "apply_team":
            model.active_decision_team_id = team_id
    store.save(model, path)
    return [_relative_to_project(path, root)]


def _save_current_template(root: Path, template: HarnessTemplate) -> Path:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "bootstrapped_at": _now(),
        "origin": "bootstrap",
        "template_id": template.template_id,
        "name": template.name,
        "source_project_name": template.source_project_name,
        "source_harness_id": template.source_harness_id,
        "template_ref": _relative_to_project(default_templates_path(root), root),
        "template_kind": template.template_kind,
        "source_kind": template.source_kind,
        "source_origin": dict(template.source_origin),
        "template_selection_source": "bootstrap_selection",
    }
    return _save_yaml(default_current_template_path(root), payload)


def _mark_template_active(root: Path, template: HarnessTemplate) -> None:
    path = default_templates_path(root)
    store = HarnessTemplateStore()
    try:
        model = store.load(path)
    except Exception as exc:
        logger.warning("template store active marker failed: %s", exc)
        return
    model.active_template_name = template.name
    store.save(model, path)


def _present_agent_ids(root: Path, harness: Any) -> set[str]:
    registry_path = default_agent_registry_path(root)
    if registry_path.exists():
        registry = AgentRegistryStore().load(registry_path)
    else:
        registry = AgentRegistryBuilder().build(root, harness=harness)
        AgentRegistryStore().save(registry, registry_path)
    return {agent.agent_id for agent in registry.agents}


def _refresh_registry_status(root: Path, harness: Any, warnings: list[str]) -> None:
    try:
        registry = AgentRegistryBuilder().build(root, harness=harness)
        active = set(harness.active_agents)
        for agent in registry.agents:
            agent.status = "equipped" if agent.agent_id in active else "available"
        AgentRegistryStore().save(registry, default_agent_registry_path(root))
    except Exception as exc:
        logger.warning("template bootstrap registry refresh failed: %s", exc)
        warnings.append(f"agent registry refresh failed: {exc}")


def _team_from_dict(item: dict[str, Any]) -> TeamPreset:
    return TeamPreset(
        schema_version=str(item.get("schema_version", SCHEMA_VERSION)),
        team_id=str(item.get("team_id", "")),
        name=str(item.get("name", "")),
        created_at=str(item.get("created_at", _now())),
        updated_at=str(item.get("updated_at")) if item.get("updated_at") is not None else None,
        description=str(item.get("description")) if item.get("description") is not None else None,
        project_name=str(item.get("project_name")) if item.get("project_name") is not None else None,
        harness_id=str(item.get("harness_id")) if item.get("harness_id") is not None else None,
        lead_agent_id=str(item.get("lead_agent_id")) if item.get("lead_agent_id") is not None else None,
        supporting_agent_ids=[str(value) for value in item.get("supporting_agent_ids", []) if value],
        members=[str(value) for value in item.get("members", []) if value],
        tags=[str(value) for value in item.get("tags", []) if value],
        source_decision_refs=[str(value) for value in item.get("source_decision_refs", []) if value],
        source_dispatch_refs=[str(value) for value in item.get("source_dispatch_refs", []) if value],
        fit_hints=[str(value) for value in item.get("fit_hints", []) if value],
        warnings=[str(value) for value in item.get("warnings", []) if value],
        errors=[str(value) for value in item.get("errors", []) if value],
    )
