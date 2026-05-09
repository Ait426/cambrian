"""프로젝트별 agent team preset 저장소."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_agent_router import HarnessAwareAgentRouter
from engine.project_agent_transfer import update_imported_agent_local_status
from engine.project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from engine.project_harness import HarnessProfileStore, default_harness_profile_path
from engine.project_harness_policy import load_or_build_policy_overlay, policy_hints

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


def _slug(value: str) -> str:
    """사람이 준 팀 이름을 안전한 id로 변환한다."""
    lowered = str(value or "").strip().lower()
    token = "".join(ch if ch.isalnum() else "-" for ch in lowered)
    return "-".join(part for part in token.split("-") if part) or "team"


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_team_presets_path(project_root: Path) -> Path:
    """team preset 기본 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "teams.yaml"


@dataclass
class TeamPreset:
    """재사용 가능한 agent 팀 구성."""

    schema_version: str
    team_id: str
    name: str
    created_at: str
    updated_at: str | None
    description: str | None
    project_name: str | None
    harness_id: str | None
    lead_agent_id: str | None
    supporting_agent_ids: list[str]
    members: list[str]
    tags: list[str] = field(default_factory=list)
    source_decision_refs: list[str] = field(default_factory=list)
    source_dispatch_refs: list[str] = field(default_factory=list)
    fit_hints: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class TeamPresetStoreModel:
    """team preset YAML 모델."""

    schema_version: str
    updated_at: str
    active_team_id: str | None
    teams: list[TeamPreset]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "active_team_id": self.active_team_id,
            "teams": [team.to_dict() for team in self.teams],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TeamPresetStore:
    """team preset 저장소."""

    def load(self, path: Path) -> TeamPresetStoreModel:
        """저장된 team preset 모델을 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return TeamPresetStoreModel(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                active_team_id=None,
                teams=[],
            )
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        teams: list[TeamPreset] = []
        for item in payload.get("teams", []) or []:
            if not isinstance(item, dict):
                continue
            teams.append(
                TeamPreset(
                    schema_version=str(item.get("schema_version", SCHEMA_VERSION)),
                    team_id=str(item.get("team_id", "")),
                    name=str(item.get("name", "")),
                    created_at=str(item.get("created_at", "")),
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
            )
        return TeamPresetStoreModel(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            active_team_id=str(payload.get("active_team_id")) if payload.get("active_team_id") is not None else None,
            teams=teams,
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )

    def save(self, model: TeamPresetStoreModel, path: Path) -> Path:
        """team preset 모델을 YAML로 저장한다."""
        target = Path(path).resolve()
        model.updated_at = _now()
        _atomic_write_text(target, yaml.safe_dump(model.to_dict(), allow_unicode=True, sort_keys=False))
        return target

    def add(self, path: Path, preset: TeamPreset) -> Path:
        """새 team preset을 추가한다. 중복 이름/id는 차단한다."""
        model = self.load(path)
        for team in model.teams:
            if team.team_id == preset.team_id or team.name == preset.name:
                raise ValueError(f"team already exists: {preset.name}")
        model.teams.append(preset)
        model.active_team_id = preset.team_id
        return self.save(model, path)

    def find(self, model: TeamPresetStoreModel, name_or_id: str) -> TeamPreset:
        """team 이름 또는 id로 preset을 찾는다."""
        wanted = str(name_or_id or "").strip()
        wanted_id = _slug(wanted)
        for team in model.teams:
            if team.name == wanted or team.team_id == wanted or team.team_id == wanted_id:
                return team
        raise KeyError(wanted)


class TeamPresetBuilder:
    """현재 하네스 상태에서 team preset을 만든다."""

    def from_current_harness(
        self,
        project_root: Path,
        name: str,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> TeamPreset:
        """현재 active_agents 조합을 team preset으로 저장 가능한 객체로 만든다."""
        root = Path(project_root).resolve()
        profile_path = default_harness_profile_path(root)
        if not profile_path.exists():
            raise FileNotFoundError("harness profile not found")
        profile = HarnessProfileStore().load(profile_path)
        members = _dedupe(list(profile.active_agents))
        if not members:
            raise ValueError("no active agents to save as a team")
        lead = members[0]
        support = [agent_id for agent_id in members[1:] if agent_id != lead]
        overlay = load_or_build_policy_overlay(root)
        decision_refs: list[str] = []
        if (root / ".cambrian" / "agents" / "staffing_decisions.yaml").exists():
            decision_refs.append(".cambrian/agents/staffing_decisions.yaml")
        if (root / ".cambrian" / "harness" / "decisions.yaml").exists():
            decision_refs.append(".cambrian/harness/decisions.yaml")
        dispatch_refs: list[str] = []
        if (root / ".cambrian" / "agents" / "dispatch_board.yaml").exists():
            dispatch_refs.append(".cambrian/agents/dispatch_board.yaml")
        fit_hints = _dedupe(
            [
                f"default team for {', '.join(profile.primary_use_cases)}" if profile.primary_use_cases else "",
                *policy_hints(overlay),
            ]
        )
        return TeamPreset(
            schema_version=SCHEMA_VERSION,
            team_id=_slug(name),
            name=str(name).strip(),
            created_at=_now(),
            updated_at=None,
            description=str(description).strip() if description else None,
            project_name=profile.project_name,
            harness_id=profile.harness_id,
            lead_agent_id=lead,
            supporting_agent_ids=support,
            members=members,
            tags=_dedupe(list(tags or [])),
            source_decision_refs=decision_refs,
            source_dispatch_refs=dispatch_refs,
            fit_hints=fit_hints[:5],
            warnings=[],
            errors=[],
        )


class TeamRecommendationBuilder:
    """request-aware team preset 추천기."""

    def recommend(self, project_root: Path, request: str | None = None) -> dict[str, Any]:
        """저장된 팀 중 현재 요청에 가장 맞는 팀을 추천한다."""
        root = Path(project_root).resolve()
        model = TeamPresetStore().load(default_team_presets_path(root))
        if not model.teams:
            return {
                "request": request,
                "best_team": None,
                "recommendations": [],
                "decision_summary": {},
                "warnings": ["no saved team presets"],
                "next_actions": ["cambrian team save auth-bug-team"],
            }
        route_by_agent: dict[str, Any] = {}
        if request:
            try:
                routed = HarnessAwareAgentRouter().route(str(request), root)
                route_by_agent = {route.agent_id: route for route in routed.routes}
            except Exception:
                route_by_agent = {}
        overlay = load_or_build_policy_overlay(root)
        recent_trial: dict[str, Any] = {}
        try:
            from engine.project_team_trials import load_recent_team_trial_summary

            recent_trial = load_recent_team_trial_summary(root)
        except Exception:
            recent_trial = {}
        decision_summary: dict[str, Any] = {}
        try:
            from engine.project_team_decisions import load_team_decision_summary

            decision_summary = load_team_decision_summary(root)
        except Exception:
            decision_summary = {}
        team_policy_overlay: Any | None = None
        try:
            from engine.project_team_policy import load_or_build_team_policy_overlay

            team_policy_overlay = load_or_build_team_policy_overlay(root)
        except Exception:
            team_policy_overlay = None
        preferred_team_ids: set[str] = set()
        preferred_team_reason = "active improvement intervention prefers this team"
        try:
            from engine.project_improvement_interventions import effective_intervention_preferences

            intervention_summary = effective_intervention_preferences(root)
            if intervention_summary:
                preferred_team_ids = {
                    str(value).lower()
                    for value in intervention_summary.get("preferred_team_ids", [])
                    if value
                }
                if intervention_summary.get("has_kept") and not intervention_summary.get("has_active"):
                    preferred_team_reason = "kept improvement prefers this team"
        except Exception:
            preferred_team_ids = set()
        recommendations: list[dict[str, Any]] = []
        for team in model.teams:
            score, reasons, warnings = self._score_team(
                team,
                route_by_agent,
                overlay,
                model.active_team_id,
                recent_trial,
                decision_summary,
                team_policy_overlay,
            )
            if preferred_team_ids and (
                str(team.team_id).lower() in preferred_team_ids
                or str(team.name).lower() in preferred_team_ids
            ):
                score = min(1.0, score + 0.05)
                reasons = _dedupe([*reasons, preferred_team_reason])
            recommendations.append(
                {
                    "team_id": team.team_id,
                    "name": team.name,
                    "score": round(score, 4),
                    "lead_agent_id": team.lead_agent_id,
                    "supporting_agent_ids": list(team.supporting_agent_ids),
                    "members": list(team.members),
                    "reasons": reasons,
                    "warnings": warnings,
                }
            )
        recommendations.sort(key=lambda item: (-float(item["score"]), str(item["team_id"])))
        best = recommendations[0] if recommendations else None
        return {
            "request": request,
            "best_team": best,
            "recommendations": recommendations,
            "decision_summary": decision_summary,
            "warnings": [],
            "next_actions": [f"cambrian team apply {best['name']}"] if best else ["cambrian team list"],
        }

    def _score_team(
        self,
        team: TeamPreset,
        route_by_agent: dict[str, Any],
        overlay: Any,
        active_team_id: str | None,
        recent_trial: dict[str, Any] | None = None,
        decision_summary: dict[str, Any] | None = None,
        team_policy_overlay: Any | None = None,
    ) -> tuple[float, list[str], list[str]]:
        score = 0.0
        reasons: list[str] = []
        warnings: list[str] = []
        lead_route = route_by_agent.get(team.lead_agent_id or "")
        if lead_route is not None:
            score += float(lead_route.score) * 0.55
            reasons.extend(list(lead_route.reasons[:2]))
        support_scores: list[float] = []
        for agent_id in team.supporting_agent_ids:
            route = route_by_agent.get(agent_id)
            if route is not None:
                support_scores.append(float(route.score))
        if support_scores:
            score += (sum(support_scores) / len(support_scores)) * 0.25
        roles = {route_by_agent.get(agent_id).role_id for agent_id in team.members if route_by_agent.get(agent_id) is not None}
        if {"bug_fix", "regression_test", "review"}.issubset(roles):
            score += 0.15
            reasons.append("team covers bug fix, test, and review roles")
        preferred_leads = set(getattr(overlay, "preferred_lead_agents", []) or [])
        preferred_support = set(getattr(overlay, "preferred_support_agents", []) or [])
        if team.lead_agent_id in preferred_leads:
            score += 0.08
            reasons.append("accepted policy prefers this lead")
        if preferred_support.intersection(team.supporting_agent_ids):
            score += 0.06
            reasons.append("accepted policy prefers one or more support agents")
        if active_team_id and team.team_id == active_team_id:
            score += 0.04
            reasons.append("team is currently active")
        trial = dict(recent_trial or {})
        trial_result = str(trial.get("result", "") or "")
        if trial.get("shadow_team_id") == team.team_id and trial_result in {"shadow_stronger", "comparable"}:
            score += 0.05 if trial_result == "shadow_stronger" else 0.03
            reasons.append(f"recent team trial result: {trial_result}")
        elif trial.get("current_team_id") == team.team_id and trial_result in {"current_stronger", "comparable"}:
            score += 0.04 if trial_result == "current_stronger" else 0.02
            reasons.append(f"recent team trial result: {trial_result}")
        decision_reason = None
        try:
            from engine.project_team_decisions import team_decision_reason

            decision_reason = team_decision_reason(team.team_id, dict(decision_summary or {}))
        except Exception:
            decision_reason = None
        if decision_reason:
            reasons.append(decision_reason)
            if "active team" in decision_reason:
                score += 0.04
            elif "backup team" in decision_reason:
                score += 0.02
            elif "dismissed" in decision_reason:
                warnings.append("team was previously dismissed")
        if team_policy_overlay is not None:
            current_id = getattr(team_policy_overlay, "current_team_id", None)
            current_name = getattr(team_policy_overlay, "current_team_name", None)
            backup_teams = set(getattr(team_policy_overlay, "backup_teams", []) or [])
            watched_teams = set(getattr(team_policy_overlay, "watched_teams", []) or [])
            if team.team_id == current_id or team.name == current_name:
                score += 0.05
                reasons.append("accepted team policy marks this as the current team")
            if team.team_id in backup_teams or team.name in backup_teams:
                score += 0.02
                reasons.append("accepted team policy keeps this as backup")
            if team.team_id in watched_teams or team.name in watched_teams:
                reasons.append("accepted team policy is watching this team")
        for hint in team.fit_hints[:2]:
            reasons.append(hint)
        if not route_by_agent:
            score += 0.1
            reasons.append("saved team preset is available")
        return min(1.0, score), _dedupe(reasons) or ["saved team preset matches current harness"], _dedupe(warnings)


def apply_team_preset(project_root: Path, team_name: str) -> tuple[TeamPreset, TeamPresetStoreModel, list[str]]:
    """team preset을 현재 active_agents 상태에 안전하게 적용한다."""
    root = Path(project_root).resolve()
    profile_path = default_harness_profile_path(root)
    registry_path = default_agent_registry_path(root)
    teams_path = default_team_presets_path(root)
    if not profile_path.exists() or not registry_path.exists():
        raise FileNotFoundError("harness profile or agent registry not found")
    store = TeamPresetStore()
    model = store.load(teams_path)
    team = store.find(model, team_name)
    profile_store = HarnessProfileStore()
    registry_store = AgentRegistryStore()
    profile = profile_store.load(profile_path)
    registry = AgentRegistryBuilder().build(root, harness=profile)
    agents_by_id = {agent.agent_id: agent for agent in registry.agents}
    warnings: list[str] = []
    for agent_id in team.members:
        agent = agents_by_id.get(agent_id)
        if agent is None:
            raise KeyError(agent_id)
        compatibility = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else ""
        if agent.source_kind == "imported" and compatibility == "blocked":
            raise ValueError(f"team member compatibility is blocked: {agent_id}")
        if agent.source_kind == "imported" and compatibility in {"weak", "partial"}:
            warnings.append(f"team member has {compatibility} compatibility: {agent_id}")
    members = _dedupe(team.members)
    profile.active_agents = members
    for agent in registry.agents:
        agent.status = "equipped" if agent.agent_id in members else "available"
        if agent.source_kind == "imported":
            update_imported_agent_local_status(root, agent.agent_id, "equipped" if agent.agent_id in members else "imported")
    registry_store.save(registry, registry_path)
    profile_store.save(profile, profile_path)
    model.active_team_id = team.team_id
    store.save(model, teams_path)
    return team, model, warnings


def load_team_summary(project_root: Path, request: str | None = None) -> dict[str, Any]:
    """status/do용 team 요약을 로드한다."""
    root = Path(project_root).resolve()
    model = TeamPresetStore().load(default_team_presets_path(root))
    active = next((team for team in model.teams if team.team_id == model.active_team_id), None)
    recommendation = TeamRecommendationBuilder().recommend(root, request=request) if model.teams else {}
    decision_summary: dict[str, Any] = {}
    try:
        from engine.project_team_decisions import load_team_decision_summary

        decision_summary = load_team_decision_summary(root)
    except Exception:
        decision_summary = {}
    policy_summary: dict[str, Any] = {}
    try:
        from engine.project_team_policy import load_or_build_team_policy_overlay, team_policy_hints

        overlay = load_or_build_team_policy_overlay(root)
        policy_summary = {
            "current_team_id": overlay.current_team_id,
            "current_team_name": overlay.current_team_name,
            "kept_teams": list(overlay.kept_teams),
            "backup_teams": list(overlay.backup_teams),
            "watched_teams": list(overlay.watched_teams),
            "hints": team_policy_hints(overlay),
            "warnings": list(overlay.warnings),
        }
    except Exception:
        policy_summary = {}
    return {
        "active_team_id": model.active_team_id,
        "active_team": active.to_dict() if active else None,
        "teams_count": len(model.teams),
        "best_team": recommendation.get("best_team") if isinstance(recommendation, dict) else None,
        "decision_summary": decision_summary,
        "policy_summary": policy_summary,
        "warnings": list(recommendation.get("warnings", [])) if isinstance(recommendation, dict) else [],
    }


def render_team_list(model: TeamPresetStoreModel) -> str:
    """team list 출력을 렌더링한다."""
    lines = ["Teams", "==================================================", "", "Active:"]
    active = next((team for team in model.teams if team.team_id == model.active_team_id), None)
    if active is None:
        lines.append("  none")
    else:
        lines.extend(_team_brief_lines(active, prefix="  "))
    lines.extend(["", "Saved:"])
    if not model.teams:
        lines.append("  none")
    for team in model.teams:
        lines.extend(_team_brief_lines(team, prefix="  "))
    return "\n".join(lines)


def _team_brief_lines(team: TeamPreset, prefix: str = "") -> list[str]:
    support = ", ".join(team.supporting_agent_ids) if team.supporting_agent_ids else "none"
    return [
        f"{prefix}{team.name}",
        f"{prefix}  lead   : {team.lead_agent_id or 'none'}",
        f"{prefix}  support: {support}",
    ]


def render_team_show(
    team: TeamPreset,
    decision_summary: dict[str, Any] | None = None,
    policy_role: str | None = None,
) -> str:
    """team preset 상세 출력을 렌더링한다."""
    lines = [
        "Team Preset",
        "==================================================",
        "",
        "Team:",
        f"  name : {team.name}",
        f"  id   : {team.team_id}",
        f"  desc : {team.description or '(none)'}",
        "",
        "Composition:",
        f"  lead   : {team.lead_agent_id or 'none'}",
        f"  support: {', '.join(team.supporting_agent_ids) if team.supporting_agent_ids else 'none'}",
        f"  members: {', '.join(team.members) if team.members else 'none'}",
    ]
    if team.tags:
        lines.extend(["", "Tags:"])
        lines.extend([f"  - {tag}" for tag in team.tags])
    if team.fit_hints:
        lines.extend(["", "Fit hints:"])
        lines.extend([f"  - {hint}" for hint in team.fit_hints])
    if policy_role:
        lines.extend(["", "Policy role:", f"  {policy_role}"])
    summary = dict(decision_summary or {})
    decisions = [
        item
        for item in summary.get("decisions", [])
        if isinstance(item, dict)
        and (item.get("target_team_id") == team.team_id or item.get("target_team_name") == team.name)
    ]
    if decisions:
        lines.extend(["", "Decisions:"])
        for item in decisions[-5:]:
            lines.append(f"  - {item.get('status')} {item.get('decision_kind')}")
    return "\n".join(lines)


def render_team_recommendation(result: dict[str, Any]) -> str:
    """team recommend 출력을 렌더링한다."""
    lines = [
        "Team Recommendation",
        "==================================================",
    ]
    if result.get("request"):
        lines.extend(["", "Request:", f"  {result['request']}"])
    best = result.get("best_team")
    if not best:
        lines.extend(["", "Best team:", "  none"])
    else:
        lines.extend(["", "Best team:", f"  {best.get('name')}"])
        reasons = list(best.get("reasons", [])) if isinstance(best, dict) else []
        if reasons:
            lines.extend(["", "Why:"])
            lines.extend([f"  - {reason}" for reason in reasons[:4]])
    if result.get("next_actions"):
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in result.get("next_actions", [])])
    return "\n".join(lines)
