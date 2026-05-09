"""Cambrian 하네스 기반 에이전트 라우터."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_agent_history import (
    AgentPassportHistoryStore,
    default_agent_passport_path,
)
from engine.project_agents import (
    AgentPassport,
    AgentRegistry,
    AgentRegistryBuilder,
    AgentRegistryStore,
    default_agent_registry_path,
)
from engine.project_harness import (
    HarnessProfile,
    HarnessProfileBuilder,
    HarnessProfileStore,
    default_harness_profile_path,
)
from engine.project_router import ProjectSkillRouter

logger = logging.getLogger(__name__)


def _clamp_score(score: float) -> float:
    """점수를 0.0~1.0 범위로 제한한다."""
    return max(0.0, min(1.0, round(score, 4)))


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


def _load_yaml(path: Path) -> dict:
    """YAML 문서를 dict로 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML 최상위는 dict여야 합니다: {path}")
    return payload


@dataclass
class AgentRoute:
    """단일 에이전트 후보의 라우팅 점수와 이유."""

    agent_id: str
    role_id: str
    source_kind: str
    status: str
    compatibility_status: str | None
    score: float
    reasons: list[str]
    warnings: list[str]
    tags: list[str]

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class AgentRoutingContext:
    """하네스 기반 에이전트 라우팅 결과."""

    enabled: bool
    harness_ref: str | None
    registry_ref: str | None
    memory_ref: str | None
    lead_agent_id: str | None
    supporting_agent_ids: list[str]
    routes: list[AgentRoute]
    selected_via: str
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "enabled": self.enabled,
            "harness_ref": self.harness_ref,
            "registry_ref": self.registry_ref,
            "memory_ref": self.memory_ref,
            "lead_agent_id": self.lead_agent_id,
            "supporting_agent_ids": list(self.supporting_agent_ids),
            "routes": [item.to_dict() for item in self.routes],
            "selected_via": self.selected_via,
            "warnings": list(self.warnings),
            "next_actions": list(self.next_actions),
        }


class HarnessAwareAgentRouter:
    """하네스, 메모리, 로컬 경력을 함께 보는 에이전트 라우터."""

    _ROLE_INTENT_WEIGHTS: dict[str, dict[str, float]] = {
        "bug_fix": {"bug_fix": 0.35},
        "regression_test": {"bug_fix": 0.16, "test_generation": 0.35, "small_refactor": 0.08},
        "review": {"review_candidate": 0.35, "bug_fix": 0.12, "small_refactor": 0.12, "docs_update": 0.08},
        "small_refactor": {"small_refactor": 0.35, "bug_fix": 0.10},
        "docs_update": {"docs_update": 0.35},
        "context_scan": {"unknown": 0.08, "bug_fix": 0.05, "small_refactor": 0.05},
        "diagnose": {"bug_fix": 0.10, "small_refactor": 0.08, "review_candidate": 0.08},
        "patch_proposal": {"bug_fix": 0.12, "small_refactor": 0.12},
        "patch_validation": {"bug_fix": 0.10, "small_refactor": 0.08, "docs_update": 0.04},
    }

    _ROLE_SUPPORT_BONUS: dict[str, tuple[str, ...]] = {
        "bug_fix": ("regression_test", "review"),
        "small_refactor": ("review", "regression_test"),
        "docs_update": ("review",),
        "review": ("regression_test",),
    }

    def route(
        self,
        user_request: str,
        project_root: Path,
        explicit_agent_id: str | None = None,
        prior_session_agent_context: dict | None = None,
    ) -> AgentRoutingContext:
        """현재 요청에 가장 잘 맞는 lead/supporting agent를 고른다."""
        root = Path(project_root).resolve()
        harness, harness_ref = self._load_harness(root)
        registry, registry_ref = self._load_registry(root, harness)
        intent = self._route_intent(root, user_request)
        policy_overlay = self._load_policy_overlay(root)
        memory_ref = ".cambrian/memory/lessons.yaml" if (root / ".cambrian" / "memory" / "lessons.yaml").exists() else None
        routes, blocked_routes, warnings = self._build_routes(
            registry=registry,
            harness=harness,
            user_request=user_request,
            intent_type=str(intent.intent_type),
            memory_context=dict(intent.memory_context or {}),
            policy_overlay=policy_overlay,
        )

        explicit_id = str(explicit_agent_id or "").strip() or None
        prior_context = dict(prior_session_agent_context or {})
        selected_via = "auto"

        if explicit_id:
            selected_via = "explicit_agent"
            explicit_route = next((item for item in routes if item.agent_id == explicit_id), None)
            if explicit_route is None:
                blocked_route = blocked_routes.get(explicit_id)
                if blocked_route is not None:
                    reason = blocked_route.warnings[0] if blocked_route.warnings else "선택한 agent는 현재 하네스와 맞지 않습니다."
                    raise ValueError(reason)
                raise KeyError(explicit_id)
            if explicit_route.compatibility_status == "blocked":
                raise ValueError(f"선택한 agent는 현재 하네스와 호환되지 않습니다: {explicit_id}")
            if explicit_route.compatibility_status in {"weak", "partial"}:
                warnings.append(f"{explicit_id} 는 현재 하네스와 완전히 맞지 않을 수 있습니다.")
            ordered_routes = self._prioritize_explicit(explicit_route, routes)
        elif prior_context.get("lead_agent_id"):
            carry_id = str(prior_context.get("lead_agent_id"))
            carry_route = next((item for item in routes if item.agent_id == carry_id), None)
            if carry_route is not None:
                selected_via = "session_carryover"
                ordered_routes = self._prioritize_explicit(carry_route, routes)
            else:
                ordered_routes = routes
        else:
            ordered_routes = routes

        lead = ordered_routes[0] if ordered_routes else None
        supporting = self._select_supporting_agents(
            lead=lead,
            routes=ordered_routes,
            prior_context=prior_context,
            policy_overlay=policy_overlay,
        )
        if lead is None:
            warnings.append("사용 가능한 agent 후보를 찾지 못했습니다.")

        return AgentRoutingContext(
            enabled=True,
            harness_ref=harness_ref,
            registry_ref=registry_ref,
            memory_ref=memory_ref,
            lead_agent_id=lead.agent_id if lead is not None else None,
            supporting_agent_ids=[item.agent_id for item in supporting],
            routes=ordered_routes,
            selected_via=selected_via,
            warnings=_dedupe(warnings),
            next_actions=[],
        )

    def _load_harness(self, root: Path) -> tuple[HarnessProfile, str | None]:
        """현재 프로젝트 하네스를 읽거나 즉석에서 계산한다."""
        harness_path = default_harness_profile_path(root)
        if harness_path.exists():
            return HarnessProfileStore().load(harness_path), ".cambrian/harness/profile.yaml"
        return HarnessProfileBuilder().build(root), None

    def _load_registry(self, root: Path, harness: HarnessProfile) -> tuple[AgentRegistry, str | None]:
        """현재 프로젝트 에이전트 레지스트리를 읽거나 즉석에서 계산한다."""
        registry_path = default_agent_registry_path(root)
        if registry_path.exists():
            return AgentRegistryStore().load(registry_path), ".cambrian/agents/registry.yaml"
        return AgentRegistryBuilder().build(root, harness=harness), None

    @staticmethod
    def _load_policy_overlay(root: Path) -> Any | None:
        """accepted policy overlay를 읽는다. 실패하면 routing은 기존 방식으로 계속한다."""
        try:
            from engine.project_harness_policy import load_or_build_policy_overlay

            return load_or_build_policy_overlay(root)
        except Exception as exc:
            logger.warning("harness policy overlay load failed: %s", exc)
            return None

    def _route_intent(self, root: Path, user_request: str):
        """기존 skill router로 request intent를 계산한다."""
        cambrian_dir = root / ".cambrian"
        return ProjectSkillRouter().route(
            user_request=str(user_request),
            project_config=_load_yaml(cambrian_dir / "project.yaml"),
            rules=_load_yaml(cambrian_dir / "rules.yaml"),
            skills=_load_yaml(cambrian_dir / "skills.yaml"),
            profile=_load_yaml(cambrian_dir / "profile.yaml"),
            explicit_options={"project_root": str(root)},
        )

    def _build_routes(
        self,
        *,
        registry: AgentRegistry,
        harness: HarnessProfile,
        user_request: str,
        intent_type: str,
        memory_context: dict,
        policy_overlay: Any | None = None,
    ) -> tuple[list[AgentRoute], dict[str, AgentRoute], list[str]]:
        """각 agent에 대한 점수와 이유를 계산한다."""
        routes: list[AgentRoute] = []
        blocked: dict[str, AgentRoute] = {}
        warnings: list[str] = []
        for agent in registry.agents:
            route = self._score_agent(
                agent=agent,
                harness=harness,
                user_request=user_request,
                intent_type=intent_type,
                memory_context=memory_context,
                policy_overlay=policy_overlay,
            )
            if route.compatibility_status == "blocked":
                blocked[route.agent_id] = route
                warnings.extend(route.warnings)
                continue
            routes.append(route)
        routes.sort(key=lambda item: (-item.score, item.agent_id))
        return routes, blocked, _dedupe(warnings)

    def _score_agent(
        self,
        *,
        agent: AgentPassport,
        harness: HarnessProfile,
        user_request: str,
        intent_type: str,
        memory_context: dict,
        policy_overlay: Any | None = None,
    ) -> AgentRoute:
        """단일 agent의 점수를 계산한다."""
        score = 0.0
        reasons: list[str] = []
        warnings: list[str] = []
        lowered_request = str(user_request).lower()
        compatibility_status = self._compatibility_status(agent)

        role_weights = self._ROLE_INTENT_WEIGHTS.get(agent.role_id, {})
        if intent_type in role_weights:
            score += role_weights[intent_type]
            reasons.append(f"request matches {intent_type}")

        if agent.role_id in {item.lower() for item in harness.primary_use_cases} or agent.agent_id in harness.recommended_agent_roles:
            score += 0.20
            reasons.append("current harness focus matches")

        if agent.agent_id in harness.active_agents or agent.status == "equipped":
            score += 0.15
            reasons.append("agent is already equipped in this harness")

        relevant_lessons = list(memory_context.get("relevant_lessons", [])) if isinstance(memory_context, dict) else []
        lesson_text = " ".join(
            str(item.get("text", "")).lower()
            for item in relevant_lessons
            if isinstance(item, dict)
        )
        if lesson_text:
            if "test" in lesson_text and agent.role_id in {"regression_test", "patch_validation"}:
                score += 0.10
                reasons.append("project memory emphasizes tests")
            if any(keyword in lesson_text for keyword in ("risk", "avoid", "careful", "warning")) and agent.role_id == "review":
                score += 0.10
                reasons.append("project memory recommends caution")
            if any(keyword in lowered_request for keyword in ("login", "auth", "인증", "로그인")) and agent.role_id in {"bug_fix", "review"}:
                score += 0.05
                reasons.append("prior auth/login signals match this request")

        history = self._load_history(Path(harness.root), agent.agent_id)
        if history is not None:
            adoptions = int(history.totals.get("adoptions", 0) or 0)
            validations_passed = int(history.totals.get("validations_passed", 0) or 0)
            validations_failed = int(history.totals.get("validations_failed", 0) or 0)
            if adoptions > 0:
                score += 0.15
                reasons.append(f"has {adoptions} successful adoptions in this harness")
            if validations_passed > 0:
                score += 0.10
                reasons.append(f"has {validations_passed} recent validation passes")
            if validations_failed > 0:
                score -= 0.10
                warnings.append(f"{agent.agent_id} has {validations_failed} recent validation failures")
            if list(history.recent_risks):
                warnings.append(history.recent_risks[0])

        if compatibility_status == "good":
            score += 0.15
            reasons.append("compatibility with this harness is good")
        elif compatibility_status == "partial":
            score += 0.05
            reasons.append("compatibility with this harness is partial")
        elif compatibility_status == "weak":
            score -= 0.05
            warnings.append(f"{agent.agent_id} has weak compatibility with this harness")
        elif compatibility_status == "blocked":
            warnings.append(f"{agent.agent_id} is blocked by harness compatibility")

        if agent.source_kind == "imported":
            reasons.append("imported passport is available for this harness")

        if not harness.test_command and "test command available" in {item.lower() for item in agent.required_harness_conditions}:
            score -= 0.10
            warnings.append("current harness does not have a test command")

        if policy_overlay is not None:
            preferred_leads = set(getattr(policy_overlay, "preferred_lead_agents", []) or [])
            preferred_support = set(getattr(policy_overlay, "preferred_support_agents", []) or [])
            watched_agents = set(getattr(policy_overlay, "watched_agents", []) or [])
            promoted_focus = set(getattr(policy_overlay, "promote_request_focus", []) or [])
            if agent.agent_id in preferred_leads:
                score += 0.07
                reasons.append("accepted policy prefers this lead agent")
            if agent.agent_id in preferred_support:
                score += 0.04
                reasons.append("accepted policy prefers this support agent")
            if bool(getattr(policy_overlay, "increase_review_support", False)) and agent.role_id == "review":
                score += 0.05
                reasons.append("accepted policy prefers review support")
            if intent_type in promoted_focus or agent.role_id in promoted_focus:
                score += 0.03
                reasons.append("accepted policy promotes this request focus")
            if agent.agent_id in watched_agents:
                warnings.append("accepted policy marks this agent as a watch candidate")

        return AgentRoute(
            agent_id=agent.agent_id,
            role_id=agent.role_id,
            source_kind=agent.source_kind,
            status=agent.status,
            compatibility_status=compatibility_status,
            score=_clamp_score(score),
            reasons=_dedupe(reasons) or ["available for this harness"],
            warnings=_dedupe(warnings),
            tags=list(agent.tags),
        )

    @staticmethod
    def _compatibility_status(agent: AgentPassport) -> str | None:
        """agent 호환성 상태를 정규화한다."""
        if agent.source_kind != "imported":
            return None
        if not isinstance(agent.stats, dict):
            return None
        raw = str(agent.stats.get("compatibility_status", "")).strip().lower()
        return raw or None

    @staticmethod
    def _prioritize_explicit(explicit_route: AgentRoute, routes: list[AgentRoute]) -> list[AgentRoute]:
        """명시적으로 선택된 agent를 선두로 올린다."""
        ordered = [explicit_route]
        ordered.extend(item for item in routes if item.agent_id != explicit_route.agent_id)
        return ordered

    def _select_supporting_agents(
        self,
        *,
        lead: AgentRoute | None,
        routes: list[AgentRoute],
        prior_context: dict,
        policy_overlay: Any | None = None,
    ) -> list[AgentRoute]:
        """lead를 보조할 supporting agent를 최대 2개 고른다."""
        if lead is None:
            return []
        preferred_ids = [
            str(item)
            for item in prior_context.get("supporting_agent_ids", [])
            if item
        ]
        if policy_overlay is not None:
            preferred_ids = _dedupe([
                *preferred_ids,
                *[str(item) for item in getattr(policy_overlay, "preferred_support_agents", []) if item],
            ])
        remainder = [item for item in routes if item.agent_id != lead.agent_id]
        boosted: list[tuple[float, AgentRoute]] = []
        preferred_roles = self._ROLE_SUPPORT_BONUS.get(lead.role_id, ())
        for route in remainder:
            score = route.score
            if route.agent_id in preferred_ids:
                score += 0.20
            if route.role_id in preferred_roles:
                score += 0.10
            if policy_overlay is not None and bool(getattr(policy_overlay, "increase_review_support", False)) and route.role_id == "review":
                score += 0.10
            boosted.append((score, route))
        boosted.sort(key=lambda item: (-item[0], item[1].agent_id))
        selected: list[AgentRoute] = []
        seen_roles: set[str] = set()
        for _, route in boosted:
            if route.score < 0.15:
                continue
            if route.role_id == lead.role_id:
                continue
            if route.role_id in seen_roles:
                continue
            selected.append(route)
            seen_roles.add(route.role_id)
            if len(selected) >= 2:
                break
        return selected

    @staticmethod
    def _load_history(project_root: Path, agent_id: str):
        """로컬 passport history를 읽는다."""
        history_path = default_agent_passport_path(project_root, agent_id)
        if not history_path.exists():
            return None
        try:
            return AgentPassportHistoryStore().load(history_path)
        except Exception as exc:
            logger.warning("agent history load failed: %s (%s)", history_path, exc)
            return None
