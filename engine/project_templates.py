"""프로젝트 하네스와 팀 구성을 재사용 가능한 템플릿으로 관리한다."""

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
from engine.project_harness_policy import (
    build_and_save_policy_overlay,
    load_or_build_policy_overlay,
    policy_hints,
)
from engine.project_team_decisions import (
    TeamDecision,
    TeamDecisionStore,
    default_team_decisions_path,
)
from engine.project_team_policy import (
    build_and_save_team_policy_overlay,
    load_or_build_team_policy_overlay,
    team_policy_hints,
)
from engine.project_teams import (
    TeamPreset,
    TeamPresetStore,
    default_team_presets_path,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


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
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """dict payload를 YAML로 저장한다."""
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복 문자열을 제거한다."""
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
    """문자열/리스트 값을 문자열 리스트로 정규화한다."""
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
    """사람이 정한 이름을 안전한 id로 바꾼다."""
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_templates_path(project_root: Path) -> Path:
    """템플릿 store 기본 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "templates.yaml"


def default_current_template_path(project_root: Path) -> Path:
    """현재 적용된 템플릿 snapshot 기본 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "current_template.yaml"


@dataclass
class HarnessTemplate:
    """재사용 가능한 하네스/팀/policy bootstrap 템플릿."""

    schema_version: str
    template_id: str
    name: str
    created_at: str
    updated_at: str | None
    description: str | None
    source_project_name: str | None
    source_harness_id: str | None
    template_kind: str
    tags: list[str]
    project_defaults: dict[str, Any]
    safety_defaults: dict[str, Any]
    agent_defaults: dict[str, Any]
    team_defaults: dict[str, Any]
    policy_defaults: dict[str, Any]
    fit_hints: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_kind: str = "local"
    source_origin: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class TemplateStoreModel:
    """템플릿 store YAML 모델."""

    schema_version: str
    updated_at: str
    active_template_name: str | None
    templates: list[HarnessTemplate]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "active_template_name": self.active_template_name,
            "templates": [template.to_dict() for template in self.templates],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class HarnessTemplateStore:
    """하네스 템플릿 저장소."""

    def load(self, path: Path) -> TemplateStoreModel:
        """저장된 템플릿 store를 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return TemplateStoreModel(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                active_template_name=None,
                templates=[],
            )
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("template store YAML top level must be a mapping")
        templates: list[HarnessTemplate] = []
        for item in payload.get("templates", []) or []:
            if not isinstance(item, dict):
                continue
            templates.append(_template_from_dict(item))
        return TemplateStoreModel(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            active_template_name=(
                str(payload.get("active_template_name"))
                if payload.get("active_template_name") is not None
                else None
            ),
            templates=templates,
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )

    def save(self, model: TemplateStoreModel, path: Path) -> Path:
        """템플릿 store를 YAML로 저장한다."""
        target = Path(path).resolve()
        model.updated_at = _now()
        return _save_yaml(target, model.to_dict())

    def add(self, path: Path, template: HarnessTemplate) -> Path:
        """새 템플릿을 추가한다. 같은 이름/id는 차단한다."""
        model = self.load(path)
        for existing in model.templates:
            if existing.name == template.name or existing.template_id == template.template_id:
                raise ValueError(f"template already exists: {template.name}")
        model.templates.append(template)
        return self.save(model, path)

    def find(self, model: TemplateStoreModel, name_or_id: str) -> HarnessTemplate:
        """템플릿 이름 또는 id로 템플릿을 찾는다."""
        wanted = str(name_or_id or "").strip()
        wanted_id = _slug(wanted)
        for template in model.templates:
            if template.name == wanted or template.template_id == wanted or template.template_id == wanted_id:
                return template
        raise KeyError(wanted)


class HarnessTemplateBuilder:
    """현재 프로젝트 operating setup에서 템플릿을 만든다."""

    def from_current_project(
        self,
        project_root: Path,
        name: str,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> HarnessTemplate:
        """현재 harness/team/policy snapshot을 reusable template으로 압축한다."""
        root = Path(project_root).resolve()
        harness_path = default_harness_profile_path(root)
        if not harness_path.exists():
            raise FileNotFoundError("harness profile not found")
        harness = HarnessProfileStore().load(harness_path)
        harness_policy = load_or_build_policy_overlay(root)
        team_model = TeamPresetStore().load(default_team_presets_path(root))
        active_team = next((team for team in team_model.teams if team.team_id == team_model.active_team_id), None)
        team_policy = load_or_build_team_policy_overlay(root)
        template_kind = "team_based" if active_team is not None or team_policy.current_team_id else "harness"
        project_defaults = {
            "project_type": harness.project_type,
            "stack": _as_list(harness.stack),
            "test_command": harness.test_command,
            "mode": harness.mode,
            "primary_use_cases": list(harness.primary_use_cases),
        }
        agent_defaults = {
            "active_agents": list(harness.active_agents),
            "preferred_lead_agents": list(harness_policy.preferred_lead_agents),
            "preferred_support_agents": list(harness_policy.preferred_support_agents),
            "backup_agents": list(harness_policy.backup_agents),
            "watched_agents": list(harness_policy.watched_agents),
        }
        team_defaults = {
            "active_team_id": team_model.active_team_id,
            "active_team_name": active_team.name if active_team else team_policy.current_team_name,
            "active_team": active_team.to_dict() if active_team else None,
            "backup_teams": list(team_policy.backup_teams),
            "watched_teams": list(team_policy.watched_teams),
            "saved_teams": [team.to_dict() for team in team_model.teams],
        }
        policy_defaults = {
            "test_first_practice": bool(harness_policy.test_first_practice),
            "narrow_change_scope": bool(harness_policy.narrow_change_scope),
            "increase_review_support": bool(harness_policy.increase_review_support),
            "promote_request_focus": list(harness_policy.promote_request_focus),
            "caution_memory_review": bool(harness_policy.caution_memory_review),
            "note_followup": bool(harness_policy.note_followup),
            "team_policy_hints": team_policy_hints(team_policy),
        }
        fit_hints = _dedupe(
            [
                f"good starting point for {', '.join(harness.primary_use_cases)}"
                if harness.primary_use_cases
                else "",
                f"default team: {active_team.name}" if active_team else "",
                *policy_hints(harness_policy),
                *team_policy_hints(team_policy),
            ]
        )
        return HarnessTemplate(
            schema_version=SCHEMA_VERSION,
            template_id=_slug(name),
            name=str(name).strip(),
            created_at=_now(),
            updated_at=None,
            description=str(description).strip() if description else None,
            source_project_name=harness.project_name,
            source_harness_id=harness.harness_id,
            template_kind=template_kind,
            tags=_dedupe(list(tags or [])),
            project_defaults=project_defaults,
            safety_defaults=dict(harness.safety),
            agent_defaults=agent_defaults,
            team_defaults=team_defaults,
            policy_defaults=policy_defaults,
            fit_hints=fit_hints[:8],
        )


class HarnessTemplateApplier:
    """저장된 템플릿을 현재 프로젝트의 안전한 bootstrap 값으로 적용한다."""

    def apply(self, project_root: Path, template_name: str, force: bool = False) -> dict[str, Any]:
        """템플릿을 현재 프로젝트의 .cambrian operating config에 적용한다."""
        root = Path(project_root).resolve()
        if not (root / ".cambrian" / "project.yaml").exists():
            raise FileNotFoundError("Cambrian project mode is not initialized")
        store = HarnessTemplateStore()
        templates_path = default_templates_path(root)
        model = store.load(templates_path)
        template = store.find(model, template_name)
        current = load_current_template(root)
        if current and current.get("name") != template.name and not force:
            raise ValueError(
                f"template already applied: {current.get('name')}. Use --force to replace the template origin."
            )
        warnings: list[str] = []
        updated_paths: list[str] = []
        updated_paths.extend(self._apply_project_defaults(root, template, force))
        updated_paths.extend(self._apply_profile_defaults(root, template, force))
        updated_paths.extend(self._apply_harness_defaults(root, template, warnings))
        updated_paths.extend(self._apply_team_defaults(root, template, force, warnings))
        self._save_current_template(root, template)
        updated_paths.append(_relative_to_project(default_current_template_path(root), root))
        model.active_template_name = template.name
        store.save(model, templates_path)
        updated_paths.append(_relative_to_project(templates_path, root))
        try:
            from engine.project_template_canary_ledger import record_canary_template_apply

            record_canary_template_apply(
                root,
                template.name,
                source_ref=_relative_to_project(default_current_template_path(root), root),
            )
        except Exception as exc:
            logger.warning("canary template apply ledger event failed: %s", exc)
        return {
            "status": "applied",
            "template": template.to_dict(),
            "current_template": load_current_template(root),
            "updated_paths": _dedupe(updated_paths),
            "warnings": warnings,
        }

    @staticmethod
    def _apply_project_defaults(root: Path, template: HarnessTemplate, force: bool) -> list[str]:
        project_path = root / ".cambrian" / "project.yaml"
        payload = _load_yaml(project_path)
        project_meta = payload.setdefault("project", {})
        if isinstance(project_meta, dict):
            if force or not project_meta.get("type"):
                project_meta["type"] = template.project_defaults.get("project_type")
            if force or not project_meta.get("stack"):
                project_meta["stack"] = _as_list(template.project_defaults.get("stack"))
        test_meta = payload.setdefault("test", {})
        if isinstance(test_meta, dict) and (force or not test_meta.get("command")):
            test_meta["command"] = template.project_defaults.get("test_command")
        ai_work = payload.setdefault("ai_work", {})
        if isinstance(ai_work, dict) and (force or not ai_work.get("primary_use_cases")):
            ai_work["primary_use_cases"] = list(template.project_defaults.get("primary_use_cases", []) or [])
        _save_yaml(project_path, payload)
        return [_relative_to_project(project_path, root)]

    @staticmethod
    def _apply_profile_defaults(root: Path, template: HarnessTemplate, force: bool) -> list[str]:
        profile_path = root / ".cambrian" / "profile.yaml"
        payload = _load_yaml(profile_path)
        if force or not payload.get("mode"):
            payload["mode"] = template.project_defaults.get("mode") or payload.get("mode") or "balanced"
        template_origin = payload.setdefault("template_origin", {})
        if isinstance(template_origin, dict):
            template_origin.update(
                {
                    "template_id": template.template_id,
                    "name": template.name,
                    "applied_at": _now(),
                }
            )
        _save_yaml(profile_path, payload)
        return [_relative_to_project(profile_path, root)]

    @staticmethod
    def _apply_harness_defaults(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[str]:
        harness_path = default_harness_profile_path(root)
        if harness_path.exists():
            harness = HarnessProfileStore().load(harness_path)
        else:
            harness = HarnessProfileBuilder().build(root)
        harness.project_type = template.project_defaults.get("project_type")
        harness.stack = _as_list(template.project_defaults.get("stack"))
        harness.test_command = template.project_defaults.get("test_command")
        harness.mode = template.project_defaults.get("mode")
        harness.primary_use_cases = [
            str(item)
            for item in template.project_defaults.get("primary_use_cases", [])
            if item
        ]
        harness.safety = dict(template.safety_defaults)
        active_agents = [
            str(item)
            for item in template.agent_defaults.get("active_agents", [])
            if item
        ]
        present_agents = _present_agent_ids(root, harness)
        filtered_agents = [agent_id for agent_id in active_agents if agent_id in present_agents]
        missing_agents = [agent_id for agent_id in active_agents if agent_id not in present_agents]
        if missing_agents:
            warnings.append(f"template agents missing in this project: {', '.join(missing_agents)}")
        if filtered_agents:
            harness.active_agents = _dedupe(filtered_agents)
        HarnessProfileStore().save(harness, harness_path)
        _refresh_registry_status(root, harness, warnings)
        return [
            _relative_to_project(harness_path, root),
            _relative_to_project(default_agent_registry_path(root), root),
        ]

    @staticmethod
    def _apply_team_defaults(
        root: Path,
        template: HarnessTemplate,
        force: bool,
        warnings: list[str],
    ) -> list[str]:
        team_defaults = dict(template.team_defaults)
        saved_teams = [item for item in team_defaults.get("saved_teams", []) if isinstance(item, dict)]
        if not saved_teams:
            return []
        store = TeamPresetStore()
        teams_path = default_team_presets_path(root)
        model = store.load(teams_path)
        existing_ids = {team.team_id for team in model.teams}
        existing_names = {team.name for team in model.teams}
        for item in saved_teams:
            team = _team_from_dict(item)
            if team.team_id in existing_ids or team.name in existing_names:
                if force:
                    model.teams = [
                        existing
                        for existing in model.teams
                        if existing.team_id != team.team_id and existing.name != team.name
                    ]
                    model.teams.append(team)
                continue
            model.teams.append(team)
        active_team_id = str(team_defaults.get("active_team_id") or "").strip()
        if active_team_id:
            if any(team.team_id == active_team_id for team in model.teams):
                model.active_team_id = active_team_id
                _append_team_template_decisions(root, template, warnings)
            else:
                warnings.append(f"template active team missing after apply: {active_team_id}")
        store.save(model, teams_path)
        try:
            build_and_save_team_policy_overlay(root)
        except Exception as exc:
            logger.warning("team policy overlay build failed: %s", exc)
            warnings.append(f"team policy overlay build failed: {exc}")
        try:
            build_and_save_policy_overlay(root)
        except Exception as exc:
            logger.warning("harness policy overlay build failed: %s", exc)
            warnings.append(f"harness policy overlay build failed: {exc}")
        return [
            _relative_to_project(teams_path, root),
            _relative_to_project(default_team_decisions_path(root), root),
        ]

    @staticmethod
    def _save_current_template(root: Path, template: HarnessTemplate) -> Path:
        current_path = default_current_template_path(root)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "applied_at": _now(),
            "template_id": template.template_id,
            "name": template.name,
            "source_project_name": template.source_project_name,
            "source_harness_id": template.source_harness_id,
            "template_ref": _relative_to_project(default_templates_path(root), root),
            "template_kind": template.template_kind,
            "source_kind": template.source_kind,
            "source_origin": dict(template.source_origin),
            "template_selection_source": "template_apply",
        }
        return _save_yaml(current_path, payload)


def _template_from_dict(item: dict[str, Any]) -> HarnessTemplate:
    return HarnessTemplate(
        schema_version=str(item.get("schema_version", SCHEMA_VERSION)),
        template_id=str(item.get("template_id", "")),
        name=str(item.get("name", "")),
        created_at=str(item.get("created_at", "")),
        updated_at=str(item.get("updated_at")) if item.get("updated_at") is not None else None,
        description=str(item.get("description")) if item.get("description") is not None else None,
        source_project_name=(
            str(item.get("source_project_name"))
            if item.get("source_project_name") is not None
            else None
        ),
        source_harness_id=(
            str(item.get("source_harness_id"))
            if item.get("source_harness_id") is not None
            else None
        ),
        template_kind=str(item.get("template_kind", "harness")),
        tags=[str(value) for value in item.get("tags", []) if value],
        project_defaults=dict(item.get("project_defaults", {}) if isinstance(item.get("project_defaults"), dict) else {}),
        safety_defaults=dict(item.get("safety_defaults", {}) if isinstance(item.get("safety_defaults"), dict) else {}),
        agent_defaults=dict(item.get("agent_defaults", {}) if isinstance(item.get("agent_defaults"), dict) else {}),
        team_defaults=dict(item.get("team_defaults", {}) if isinstance(item.get("team_defaults"), dict) else {}),
        policy_defaults=dict(item.get("policy_defaults", {}) if isinstance(item.get("policy_defaults"), dict) else {}),
        fit_hints=[str(value) for value in item.get("fit_hints", []) if value],
        warnings=[str(value) for value in item.get("warnings", []) if value],
        errors=[str(value) for value in item.get("errors", []) if value],
        source_kind=str(item.get("source_kind", "local") or "local"),
        source_origin=dict(item.get("source_origin", {}) if isinstance(item.get("source_origin"), dict) else {}),
    )


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


def _present_agent_ids(root: Path, harness) -> set[str]:
    registry_path = default_agent_registry_path(root)
    if registry_path.exists():
        registry = AgentRegistryStore().load(registry_path)
    else:
        registry = AgentRegistryBuilder().build(root, harness=harness)
        AgentRegistryStore().save(registry, registry_path)
    return {agent.agent_id for agent in registry.agents}


def _refresh_registry_status(root: Path, harness, warnings: list[str]) -> None:
    registry_path = default_agent_registry_path(root)
    try:
        registry = AgentRegistryBuilder().build(root, harness=harness)
        active = set(harness.active_agents)
        for agent in registry.agents:
            agent.status = "equipped" if agent.agent_id in active else "available"
        AgentRegistryStore().save(registry, registry_path)
    except Exception as exc:
        logger.warning("agent registry refresh failed: %s", exc)
        warnings.append(f"agent registry refresh failed: {exc}")


def _append_team_template_decisions(root: Path, template: HarnessTemplate, warnings: list[str]) -> None:
    team_defaults = dict(template.team_defaults)
    active_team_id = str(team_defaults.get("active_team_id") or "").strip()
    active_team_name = str(team_defaults.get("active_team_name") or active_team_id).strip() or None
    if not active_team_id:
        return
    decisions_path = default_team_decisions_path(root)
    store = TeamDecisionStore()
    model = store.load(decisions_path)
    existing = {
        (decision.status, decision.decision_kind, decision.target_team_id)
        for decision in model.decisions
    }
    new_decisions: list[TeamDecision] = []
    if ("accepted", "apply_team", active_team_id) not in existing:
        new_decisions.append(
            _build_template_team_decision(
                decision_kind="apply_team",
                team_id=active_team_id,
                team_name=active_team_name,
                template=template,
                operational_effect={"type": "template_apply", "applied": True, "details": {"template": template.name}},
            )
        )
    for backup in [str(value) for value in team_defaults.get("backup_teams", []) if value]:
        team_id = _slug(backup)
        if ("accepted", "keep_as_backup", team_id) not in existing:
            new_decisions.append(
                _build_template_team_decision(
                    decision_kind="keep_as_backup",
                    team_id=team_id,
                    team_name=backup,
                    template=template,
                    operational_effect={"type": "none", "applied": False, "details": {}},
                )
            )
    for watched in [str(value) for value in team_defaults.get("watched_teams", []) if value]:
        team_id = _slug(watched)
        if ("accepted", "watch_team", team_id) not in existing:
            new_decisions.append(
                _build_template_team_decision(
                    decision_kind="watch_team",
                    team_id=team_id,
                    team_name=watched,
                    template=template,
                    operational_effect={"type": "none", "applied": False, "details": {}},
                )
            )
    if not new_decisions:
        return
    model.decisions.extend(new_decisions)
    model.active_decision_team_id = active_team_id
    store.save(model, decisions_path)
    warnings.append("team decisions were seeded from template defaults")


def _build_template_team_decision(
    *,
    decision_kind: str,
    team_id: str,
    team_name: str | None,
    template: HarnessTemplate,
    operational_effect: dict[str, Any],
) -> TeamDecision:
    return TeamDecision(
        decision_id=f"team-decision-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_slug(team_id)[:12]}",
        created_at=_now(),
        updated_at=None,
        status="accepted",
        decision_kind=decision_kind,
        target_team_id=team_id,
        target_team_name=team_name,
        title=f"{decision_kind} {team_name or team_id}",
        summary=f"Seeded from template {template.name}",
        resolution="accepted through template apply",
        source_ref=".cambrian/templates/current_template.yaml",
        source_type="template",
        evidence_refs=[".cambrian/templates/templates.yaml"],
        operational_effect=operational_effect,
        warnings=[],
        errors=[],
    )


def load_current_template(project_root: Path) -> dict[str, Any]:
    """현재 적용된 템플릿 snapshot을 읽는다."""
    path = default_current_template_path(project_root)
    if not path.exists():
        return {}
    try:
        return _load_yaml(path)
    except Exception as exc:
        logger.warning("current template load failed: %s", exc)
        return {"warnings": [f"current template load failed: {exc}"]}


def template_context(project_root: Path) -> dict[str, Any]:
    """request/session artifact에 넣을 템플릿 context snapshot을 만든다."""
    root = Path(project_root).resolve()
    current = load_current_template(root)
    if not current:
        return {"enabled": False, "applied_hints": []}
    canary_stage_id = None
    try:
        from engine.project_template_canary import active_canary_stage

        stage = active_canary_stage(root)
        if stage is not None and _slug(stage.candidate_template_name) == _slug(str(current.get("name") or "")):
            canary_stage_id = stage.stage_id
    except Exception as exc:
        logger.warning("template canary context load failed: %s", exc)
    hints = [f"{current.get('name')} is the active harness template"] if current.get("name") else []
    return {
        "enabled": True,
        "template_id": current.get("template_id"),
        "name": current.get("name"),
        "template_name": current.get("name"),
        "template_kind": current.get("template_kind"),
        "origin": current.get("origin") or ("bootstrap" if current.get("bootstrapped_at") else "apply"),
        "template_selection_source": current.get("template_selection_source")
        or ("bootstrap_selection" if current.get("bootstrapped_at") else "template_apply"),
        "canary_stage_id": canary_stage_id,
        "source_kind": current.get("source_kind") or "local",
        "source_origin": current.get("source_origin") if isinstance(current.get("source_origin"), dict) else {},
        "source_project_name": current.get("source_project_name"),
        "source_harness_id": current.get("source_harness_id"),
        "current_template_ref": _relative_to_project(default_current_template_path(root), root),
        "applied_hints": hints,
        "warnings": list(current.get("warnings", []) if isinstance(current.get("warnings"), list) else []),
    }


def render_template_list(model: TemplateStoreModel) -> str:
    """템플릿 목록 출력을 렌더링한다."""
    lines = ["Harness Templates", "==================================================", "", "Templates:"]
    if not model.templates:
        lines.append("  none")
    local_templates = [template for template in model.templates if template.source_kind != "imported"]
    imported_templates = [template for template in model.templates if template.source_kind == "imported"]
    if local_templates:
        lines.extend(["", "Local:"])
        for template in local_templates:
            focus = ", ".join(template.project_defaults.get("primary_use_cases", []) or []) or "none"
            lines.extend([
                f"  - {template.name}",
                f"    kind : {template.template_kind}",
                f"    focus: {focus}",
            ])
    if imported_templates:
        lines.extend(["", "Imported:"])
        for template in imported_templates:
            focus = ", ".join(template.project_defaults.get("primary_use_cases", []) or []) or "none"
            source = template.source_origin.get("source_project_name") or template.source_project_name or "unknown"
            lines.extend([
                f"  - {template.name}",
                f"    kind : {template.template_kind}",
                f"    focus: {focus}",
                f"    from : {source}",
            ])
    if model.active_template_name:
        lines.extend(["", "Current:", f"  {model.active_template_name}"])
    return "\n".join(lines)


def render_template_show(template: HarnessTemplate) -> str:
    """템플릿 상세 출력을 렌더링한다."""
    lines = [
        "Harness Template",
        "==================================================",
        "",
        "Template:",
        f"  name : {template.name}",
        f"  id   : {template.template_id}",
        f"  kind : {template.template_kind}",
        f"  desc : {template.description or '(none)'}",
        "",
        "Source:",
        "  kind : imported" if template.source_kind == "imported" else "  kind : local",
        "",
        "Project defaults:",
        f"  type : {template.project_defaults.get('project_type') or 'unknown'}",
        f"  stack: {', '.join(template.project_defaults.get('stack', []) or []) or 'none'}",
        f"  tests: {template.project_defaults.get('test_command') or 'none'}",
        f"  focus: {', '.join(template.project_defaults.get('primary_use_cases', []) or []) or 'none'}",
        "",
        "Agent defaults:",
        f"  active : {', '.join(template.agent_defaults.get('active_agents', []) or []) or 'none'}",
        f"  lead   : {', '.join(template.agent_defaults.get('preferred_lead_agents', []) or []) or 'none'}",
        f"  support: {', '.join(template.agent_defaults.get('preferred_support_agents', []) or []) or 'none'}",
        "",
        "Team defaults:",
        f"  active : {template.team_defaults.get('active_team_name') or template.team_defaults.get('active_team_id') or 'none'}",
        f"  backup : {', '.join(template.team_defaults.get('backup_teams', []) or []) or 'none'}",
        f"  watch  : {', '.join(template.team_defaults.get('watched_teams', []) or []) or 'none'}",
    ]
    if template.source_kind == "imported":
        source = template.source_origin.get("source_project_name") or template.source_project_name or "unknown"
        source_lines = [
            f"  from : {source}",
        ]
        if template.source_origin.get("source_export_ref"):
            source_lines.append(f"  ref  : {template.source_origin.get('source_export_ref')}")
        insert_at = lines.index("Project defaults:") - 1
        lines[insert_at:insert_at] = source_lines
    policy_flags = [
        key
        for key in ("test_first_practice", "narrow_change_scope", "increase_review_support")
        if template.policy_defaults.get(key)
    ]
    if policy_flags:
        lines.extend(["", "Policy defaults:"])
        lines.extend([f"  - {flag.replace('_', '-')}" for flag in policy_flags])
    if template.fit_hints:
        lines.extend(["", "Fit hints:"])
        lines.extend([f"  - {hint}" for hint in template.fit_hints[:6]])
    return "\n".join(lines)


def render_template_apply(result: dict[str, Any]) -> str:
    """템플릿 apply 결과를 사람이 읽기 좋게 렌더링한다."""
    template = result.get("template", {}) if isinstance(result.get("template"), dict) else {}
    lines = [
        "Harness template applied.",
        "",
        "Template:",
        f"  {template.get('name') or '(unknown)'}",
        "",
        "Updated:",
    ]
    for path in result.get("updated_paths", []) or []:
        lines.append(f"  - {path}")
    warnings = [str(value) for value in result.get("warnings", []) if value]
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in warnings])
    return "\n".join(lines)


def render_current_template_summary(current: dict[str, Any]) -> str:
    """현재 적용 템플릿 요약을 렌더링한다."""
    if not current:
        return "Harness template:\n  none applied"
    origin = current.get("origin") or ("bootstrap" if current.get("bootstrapped_at") else "apply")
    source_kind = current.get("source_kind") or "local"
    source_origin = current.get("source_origin") if isinstance(current.get("source_origin"), dict) else {}
    source_project = source_origin.get("source_project_name") or current.get("source_project_name") or "unknown"
    return "\n".join([
        "Harness template:",
        f"  current : {current.get('name') or 'unknown'}",
        f"  origin  : {origin}",
        f"  source  : {source_kind} from {source_project}" if source_kind == "imported" else f"  source  : {source_project}",
    ])
