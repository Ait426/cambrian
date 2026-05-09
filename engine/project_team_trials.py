"""프로젝트 team preset shadow trial 지원 모듈."""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_agent_router import HarnessAwareAgentRouter
from engine.project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from engine.project_harness import HarnessProfileStore, default_harness_profile_path
from engine.project_harness_policy import load_or_build_policy_overlay
from engine.project_router import ProjectSkillRouter
from engine.project_teams import TeamPreset, TeamPresetStore, default_team_presets_path

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    """파일명에 사용할 UTC timestamp를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def _slug(value: str) -> str:
    """사람이 준 이름을 파일명에 안전한 토큰으로 변환한다."""
    lowered = str(value or "").strip().lower()
    token = "".join(ch if ch.isalnum() else "-" for ch in lowered)
    return "-".join(part for part in token.split("-") if part) or "team"


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


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML 파일을 dict로 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML 최상위 값은 dict여야 합니다: {path}")
    return payload


def default_team_trials_dir(project_root: Path) -> Path:
    """team trial report 기본 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "team_trials"


def default_team_trial_path(project_root: Path, report: "TeamTrialReport") -> Path:
    """team trial report 기본 저장 경로를 반환한다."""
    token = str(report.trial_id).split("-")[-1] or uuid.uuid4().hex[:6]
    return default_team_trials_dir(project_root) / f"team_trial_{_timestamp()}_{_slug(report.shadow_team_id)}_{token}.yaml"


def resolve_team_trial_path(project_root: Path, trial_ref: str) -> Path:
    """trial id 또는 경로를 안전하게 `.cambrian/agents/team_trials/` 내부 파일로 해석한다."""
    root = Path(project_root).resolve()
    trials_dir = default_team_trials_dir(root).resolve()
    raw = Path(str(trial_ref or "").strip())
    candidates: list[Path] = []
    if raw.suffix:
        candidates.append((root / raw).resolve() if not raw.is_absolute() else raw.resolve())
    else:
        candidates.extend(sorted(trials_dir.glob(f"*{raw}*.yaml"), reverse=True))
        candidates.extend(sorted(trials_dir.glob(f"*{_slug(str(trial_ref))}*.yaml"), reverse=True))
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(trials_dir)
        except ValueError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    wanted = str(trial_ref or "").strip()
    for candidate in sorted(trials_dir.glob("team_trial_*.yaml"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            payload = _load_yaml(candidate)
        except Exception:
            continue
        if str(payload.get("trial_id", "")) == wanted:
            return candidate.resolve()
    raise FileNotFoundError(str(trial_ref))


@dataclass
class TeamTrialStep:
    """team trial의 안전한 비교 단계."""

    kind: str
    status: str
    summary: str
    artifact_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class TeamTrialReport:
    """current team과 shadow team 비교 report."""

    schema_version: str
    generated_at: str
    trial_id: str
    project_name: str | None
    harness_id: str | None
    request: str
    request_intent: str | None
    current_team_id: str | None
    current_team_members: list[str]
    shadow_team_id: str
    shadow_team_members: list[str]
    status: str
    steps: list[TeamTrialStep]
    comparison: dict[str, Any]
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "trial_id": self.trial_id,
            "project_name": self.project_name,
            "harness_id": self.harness_id,
            "request": self.request,
            "request_intent": self.request_intent,
            "current_team_id": self.current_team_id,
            "current_team_members": list(self.current_team_members),
            "shadow_team_id": self.shadow_team_id,
            "shadow_team_members": list(self.shadow_team_members),
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "comparison": dict(self.comparison),
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "saved_path": self.saved_path,
        }


class TeamTrialStore:
    """team trial report 저장소."""

    def save(self, report: TeamTrialReport, path: Path) -> Path:
        """report를 YAML 파일로 저장한다."""
        target = Path(path).resolve()
        report.saved_path = _relative_to_project(target, target.parents[3] if len(target.parents) > 3 else target.parent)
        _atomic_write_text(target, yaml.safe_dump(report.to_dict(), allow_unicode=True, sort_keys=False))
        return target

    def load(self, path: Path) -> TeamTrialReport:
        """YAML 파일에서 team trial report를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        return TeamTrialReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            trial_id=str(payload.get("trial_id", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            request=str(payload.get("request", "")),
            request_intent=str(payload.get("request_intent")) if payload.get("request_intent") is not None else None,
            current_team_id=str(payload.get("current_team_id")) if payload.get("current_team_id") is not None else None,
            current_team_members=[str(value) for value in payload.get("current_team_members", []) if value],
            shadow_team_id=str(payload.get("shadow_team_id", "")),
            shadow_team_members=[str(value) for value in payload.get("shadow_team_members", []) if value],
            status=str(payload.get("status", "failed")),
            steps=[
                TeamTrialStep(
                    kind=str(item.get("kind", "")),
                    status=str(item.get("status", "")),
                    summary=str(item.get("summary", "")),
                    artifact_refs=[str(value) for value in item.get("artifact_refs", []) if value],
                    warnings=[str(value) for value in item.get("warnings", []) if value],
                )
                for item in payload.get("steps", []) or []
                if isinstance(item, dict)
            ],
            comparison=dict(payload.get("comparison", {}) if isinstance(payload.get("comparison"), dict) else {}),
            next_actions=[str(value) for value in payload.get("next_actions", []) if value],
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
            saved_path=str(payload.get("saved_path")) if payload.get("saved_path") is not None else None,
        )


class TeamTrialRunner:
    """저장된 team preset을 shadow team으로 안전하게 시험 비교한다."""

    def run(
        self,
        project_root: Path,
        shadow_team_name: str,
        request: str,
        current_team_name: str | None = None,
    ) -> TeamTrialReport:
        """current active team과 shadow team preset을 같은 요청 기준으로 비교한다."""
        root = Path(project_root).resolve()
        store = TeamPresetStore()
        model = store.load(default_team_presets_path(root))
        shadow_team = store.find(model, shadow_team_name)
        current_team = self._resolve_current_team(store, model, current_team_name)
        harness = self._load_harness(root)
        intent_type = self._request_intent(root, request)
        route_by_agent = self._route_by_agent(root, request)
        overlay = load_or_build_policy_overlay(root)
        decision_summary: dict[str, Any] = {}
        try:
            from engine.project_team_decisions import load_team_decision_summary

            decision_summary = load_team_decision_summary(root)
        except Exception:
            decision_summary = {}

        blocked = self._blocked_team_members(root, shadow_team)
        if blocked:
            return self._blocked_report(
                harness=harness,
                request=request,
                intent_type=intent_type,
                current_team=current_team,
                shadow_team=shadow_team,
                errors=blocked,
            )

        current_score, current_reasons, current_warnings = self._score_team(
            current_team,
            route_by_agent,
            overlay,
            decision_summary,
            is_current=True,
        )
        shadow_score, shadow_reasons, shadow_warnings = self._score_team(
            shadow_team,
            route_by_agent,
            overlay,
            decision_summary,
            is_current=False,
        )
        result = self._result(current_score, shadow_score, current_team, shadow_team)
        reasons = self._comparison_reasons(
            result=result,
            current_team=current_team,
            shadow_team=shadow_team,
            current_reasons=current_reasons,
            shadow_reasons=shadow_reasons,
        )
        steps = self._steps(shadow_team, shadow_score, harness)
        return TeamTrialReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            trial_id=f"team-trial-{uuid.uuid4().hex[:8]}",
            project_name=getattr(harness, "project_name", None),
            harness_id=getattr(harness, "harness_id", None),
            request=str(request),
            request_intent=intent_type,
            current_team_id=current_team.team_id if current_team else None,
            current_team_members=list(current_team.members) if current_team else [],
            shadow_team_id=shadow_team.team_id,
            shadow_team_members=list(shadow_team.members),
            status="completed",
            steps=steps,
            comparison={
                "current_summary": self._summary(current_team, current_score, current_reasons),
                "shadow_summary": self._summary(shadow_team, shadow_score, shadow_reasons),
                "result": result,
                "reasons": reasons,
            },
            next_actions=[
                f"cambrian team show {shadow_team.name}",
                f"cambrian team apply {shadow_team.name}",
            ],
            warnings=_dedupe(current_warnings + shadow_warnings),
            errors=[],
        )

    @staticmethod
    def _resolve_current_team(
        store: TeamPresetStore,
        model: Any,
        current_team_name: str | None,
    ) -> TeamPreset | None:
        if current_team_name:
            return store.find(model, current_team_name)
        if model.active_team_id:
            try:
                return store.find(model, str(model.active_team_id))
            except KeyError:
                return None
        return None

    @staticmethod
    def _load_harness(root: Path) -> Any | None:
        harness_path = default_harness_profile_path(root)
        if harness_path.exists():
            return HarnessProfileStore().load(harness_path)
        return None

    @staticmethod
    def _request_intent(root: Path, request: str) -> str | None:
        cambrian_dir = root / ".cambrian"
        try:
            routed = ProjectSkillRouter().route(
                user_request=str(request),
                project_config=_load_yaml(cambrian_dir / "project.yaml"),
                rules=_load_yaml(cambrian_dir / "rules.yaml"),
                skills=_load_yaml(cambrian_dir / "skills.yaml"),
                profile=_load_yaml(cambrian_dir / "profile.yaml"),
                explicit_options={"project_root": str(root)},
            )
            return str(routed.intent_type)
        except Exception:
            return None

    @staticmethod
    def _route_by_agent(root: Path, request: str) -> dict[str, Any]:
        try:
            routed = HarnessAwareAgentRouter().route(str(request), root)
        except Exception:
            return {}
        return {route.agent_id: route for route in routed.routes}

    @staticmethod
    def _blocked_team_members(root: Path, team: TeamPreset) -> list[str]:
        registry_path = default_agent_registry_path(root)
        harness = TeamTrialRunner._load_harness(root)
        registry = AgentRegistryStore().load(registry_path) if registry_path.exists() else AgentRegistryBuilder().build(root, harness=harness)
        agents_by_id = {agent.agent_id: agent for agent in registry.agents}
        errors: list[str] = []
        for agent_id in team.members:
            agent = agents_by_id.get(agent_id)
            if agent is None:
                errors.append(f"missing team member agent: {agent_id}")
                continue
            compatibility = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else ""
            if agent.source_kind == "imported" and compatibility == "blocked":
                errors.append(f"team member compatibility is blocked: {agent_id}")
        return errors

    @staticmethod
    def _blocked_report(
        *,
        harness: Any | None,
        request: str,
        intent_type: str | None,
        current_team: TeamPreset | None,
        shadow_team: TeamPreset,
        errors: list[str],
    ) -> TeamTrialReport:
        return TeamTrialReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            trial_id=f"team-trial-{uuid.uuid4().hex[:8]}",
            project_name=getattr(harness, "project_name", None),
            harness_id=getattr(harness, "harness_id", None),
            request=str(request),
            request_intent=intent_type,
            current_team_id=current_team.team_id if current_team else None,
            current_team_members=list(current_team.members) if current_team else [],
            shadow_team_id=shadow_team.team_id,
            shadow_team_members=list(shadow_team.members),
            status="blocked",
            steps=[
                TeamTrialStep(
                    kind="routing",
                    status="blocked",
                    summary="Shadow team cannot be trialed safely.",
                    warnings=list(errors),
                )
            ],
            comparison={
                "current_summary": TeamTrialRunner._summary(current_team, 0.0, []),
                "shadow_summary": TeamTrialRunner._summary(shadow_team, 0.0, []),
                "result": "inconclusive",
                "reasons": list(errors),
            },
            next_actions=[f"cambrian team show {shadow_team.name}"],
            warnings=list(errors),
            errors=list(errors),
        )

    @staticmethod
    def _score_team(
        team: TeamPreset | None,
        route_by_agent: dict[str, Any],
        overlay: Any,
        decision_summary: dict[str, Any],
        *,
        is_current: bool,
    ) -> tuple[float, list[str], list[str]]:
        if team is None:
            return 0.0, ["no current active team is set"], []
        score = 0.0
        reasons: list[str] = []
        warnings: list[str] = []
        lead_route = route_by_agent.get(team.lead_agent_id or "")
        if lead_route is not None:
            score += float(lead_route.score) * 0.52
            reasons.append(f"{team.lead_agent_id} fits the request as lead")
        support_scores: list[float] = []
        roles: set[str] = set()
        for agent_id in team.members:
            route = route_by_agent.get(agent_id)
            if route is None:
                continue
            roles.add(str(route.role_id))
            if agent_id != team.lead_agent_id:
                support_scores.append(float(route.score))
        if support_scores:
            score += (sum(support_scores) / len(support_scores)) * 0.25
            reasons.append("supporting members have request fit")
        if {"bug_fix", "regression_test", "review"}.issubset(roles):
            score += 0.15
            reasons.append("team covers bug fix, test, and review")
        elif "regression_test" in roles and "review" in roles:
            score += 0.10
            reasons.append("team has strong validation and review coverage")
        preferred_leads = set(getattr(overlay, "preferred_lead_agents", []) or [])
        preferred_support = set(getattr(overlay, "preferred_support_agents", []) or [])
        if team.lead_agent_id in preferred_leads:
            score += 0.07
            reasons.append("accepted policy prefers this lead")
        if preferred_support.intersection(team.supporting_agent_ids):
            score += 0.06
            reasons.append("accepted policy prefers this support mix")
        if bool(getattr(overlay, "increase_review_support", False)) and "review" in roles:
            score += 0.05
            reasons.append("team aligns with review-support policy")
        if bool(getattr(overlay, "test_first_practice", False)) and "regression_test" in roles:
            score += 0.05
            reasons.append("team aligns with test-first policy")
        if is_current:
            score += 0.04
            reasons.append("team is currently active")
        decision_reason = None
        try:
            from engine.project_team_decisions import team_decision_reason

            decision_reason = team_decision_reason(team.team_id, decision_summary)
        except Exception:
            decision_reason = None
        if decision_reason:
            reasons.append(decision_reason)
            if "active team" in decision_reason:
                score += 0.03
            elif "backup team" in decision_reason:
                score += 0.02
        for warning in team.warnings[:2]:
            warnings.append(warning)
        for hint in team.fit_hints[:2]:
            reasons.append(hint)
        if not route_by_agent:
            score += 0.10
            reasons.append("saved team preset is available")
        return min(1.0, round(score, 4)), _dedupe(reasons), _dedupe(warnings)

    @staticmethod
    def _result(
        current_score: float,
        shadow_score: float,
        current_team: TeamPreset | None,
        shadow_team: TeamPreset,
    ) -> str:
        if current_team is None and shadow_team.members:
            return "shadow_stronger"
        diff = shadow_score - current_score
        if diff >= 0.12:
            return "shadow_stronger"
        if diff <= -0.12:
            return "current_stronger"
        if max(current_score, shadow_score) <= 0.15:
            return "inconclusive"
        return "comparable"

    @staticmethod
    def _comparison_reasons(
        *,
        result: str,
        current_team: TeamPreset | None,
        shadow_team: TeamPreset,
        current_reasons: list[str],
        shadow_reasons: list[str],
    ) -> list[str]:
        reasons: list[str] = []
        if result == "shadow_stronger":
            reasons.append(f"{shadow_team.name} shows stronger fit for this request")
        elif result == "current_stronger" and current_team is not None:
            reasons.append(f"{current_team.name} still has stronger fit for this request")
        elif result == "comparable":
            reasons.append("both teams have meaningful fit under the current harness")
        else:
            reasons.append("team evidence is not strong enough for a clear staffing call")
        reasons.extend([f"shadow: {reason}" for reason in shadow_reasons[:2]])
        reasons.extend([f"current: {reason}" for reason in current_reasons[:2]])
        return _dedupe(reasons)

    @staticmethod
    def _steps(team: TeamPreset, shadow_score: float, harness: Any | None) -> list[TeamTrialStep]:
        roles = set(team.members)
        has_test_agent = "regression-test-agent" in roles or "patch-validation-agent" in roles
        test_command = getattr(harness, "test_command", None) if harness is not None else None
        return [
            TeamTrialStep(
                kind="routing",
                status="success" if shadow_score > 0.0 else "skipped",
                summary="Shadow team routing was compared against the current team.",
            ),
            TeamTrialStep(
                kind="diagnose",
                status="success" if shadow_score >= 0.20 else "skipped",
                summary="Diagnose feasibility was estimated from team lead and support fit.",
            ),
            TeamTrialStep(
                kind="patch_proposal",
                status="success" if shadow_score >= 0.35 else "skipped",
                summary="Patch proposal feasibility was estimated without applying changes.",
            ),
            TeamTrialStep(
                kind="validation",
                status="success" if has_test_agent and test_command else "skipped",
                summary="Validation suitability checked in shadow mode; no apply or adoption was run.",
            ),
        ]

    @staticmethod
    def _summary(team: TeamPreset | None, score: float, reasons: list[str]) -> dict[str, Any]:
        if team is None:
            return {
                "team_id": None,
                "name": None,
                "members": [],
                "score": round(score, 4),
                "fit": "none",
                "reasons": list(reasons),
            }
        fit = "strong" if score >= 0.65 else "partial" if score >= 0.35 else "weak"
        return {
            "team_id": team.team_id,
            "name": team.name,
            "members": list(team.members),
            "score": round(score, 4),
            "fit": fit,
            "reasons": list(reasons),
        }


def load_recent_team_trial_summary(project_root: Path) -> dict[str, Any]:
    """가장 최근 team trial 요약을 반환한다."""
    trials_dir = default_team_trials_dir(project_root)
    candidates = sorted(trials_dir.glob("team_trial_*.yaml"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return {}
    report = TeamTrialStore().load(candidates[0])
    result = str(report.comparison.get("result", "inconclusive") if isinstance(report.comparison, dict) else "inconclusive")
    return {
        "trial_id": report.trial_id,
        "path": _relative_to_project(candidates[0], Path(project_root).resolve()),
        "request": report.request,
        "current_team_id": report.current_team_id,
        "shadow_team_id": report.shadow_team_id,
        "status": report.status,
        "result": result,
        "reasons": list(report.comparison.get("reasons", []) if isinstance(report.comparison, dict) else [])[:3],
    }


def render_team_trial(report: TeamTrialReport) -> str:
    """team trial report를 사람이 읽기 좋게 렌더링한다."""
    result = str(report.comparison.get("result", "inconclusive") if isinstance(report.comparison, dict) else "inconclusive")
    lines = [
        "Team Trial",
        "==================================================",
        "",
        "Request:",
        f"  {report.request}",
        "",
        "Current team:",
        f"  {report.current_team_id or 'none'}",
        "",
        "Shadow team:",
        f"  {report.shadow_team_id}",
        "",
        "Result:",
        f"  {result}",
    ]
    reasons = list(report.comparison.get("reasons", []) if isinstance(report.comparison, dict) else [])
    if reasons:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {reason}" for reason in reasons[:5]])
    if report.steps:
        lines.extend(["", "Steps:"])
        for step in report.steps:
            lines.append(f"  - {step.kind}: {step.status}")
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in report.next_actions])
    if report.saved_path:
        lines.extend(["", "Saved:", f"  {report.saved_path}"])
    return "\n".join(lines)


def team_trial_to_json(report: TeamTrialReport) -> dict[str, Any]:
    """team trial JSON payload를 반환한다."""
    return report.to_dict()
