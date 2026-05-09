"""Cambrian 프로젝트 에이전트 레지스트리."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_harness import (
    HarnessProfile,
    HarnessProfileBuilder,
    HarnessProfileStore,
    default_harness_profile_path,
)
from engine.project_memory import load_project_memory
from engine.project_router import ProjectSkillRouter

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
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


def default_agent_registry_path(project_root: Path) -> Path:
    """기본 agent registry 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "registry.yaml"


@dataclass
class AgentPassport:
    """현재 프로젝트에서 사용할 수 있는 에이전트 작업자 카드."""

    schema_version: str
    agent_id: str
    role_id: str
    label: str
    description: str
    strengths: list[str]
    risks: list[str]
    preferred_signals: list[str]
    required_harness_conditions: list[str]
    blocked_conditions: list[str]
    source_kind: str
    status: str
    project_fit_notes: list[str]
    stats: dict
    tags: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class AgentRegistry:
    """현재 프로젝트용 에이전트 레지스트리."""

    schema_version: str
    generated_at: str
    harness_id: str | None
    agents: list[AgentPassport]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "harness_id": self.harness_id,
            "agents": [agent.to_dict() for agent in self.agents],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class AgentRegistryStore:
    """agent registry 저장/로드 도구."""

    def save(self, registry: AgentRegistry, path: Path) -> Path:
        """레지스트리를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(registry.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> AgentRegistry:
        """저장된 레지스트리를 로드한다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("agent registry YAML 최상위는 dict여야 합니다.")
        raw_agents = payload.get("agents", [])
        agents: list[AgentPassport] = []
        if isinstance(raw_agents, list):
            for item in raw_agents:
                if not isinstance(item, dict):
                    continue
                agents.append(
                    AgentPassport(
                        schema_version=str(item.get("schema_version", SCHEMA_VERSION)),
                        agent_id=str(item.get("agent_id", "")),
                        role_id=str(item.get("role_id", "")),
                        label=str(item.get("label", "")),
                        description=str(item.get("description", "")),
                        strengths=[str(value) for value in item.get("strengths", []) if value],
                        risks=[str(value) for value in item.get("risks", []) if value],
                        preferred_signals=[str(value) for value in item.get("preferred_signals", []) if value],
                        required_harness_conditions=[str(value) for value in item.get("required_harness_conditions", []) if value],
                        blocked_conditions=[str(value) for value in item.get("blocked_conditions", []) if value],
                        source_kind=str(item.get("source_kind", "built_in")),
                        status=str(item.get("status", "available")),
                        project_fit_notes=[str(value) for value in item.get("project_fit_notes", []) if value],
                        stats=dict(item.get("stats", {})) if isinstance(item.get("stats"), dict) else {},
                        tags=[str(value) for value in item.get("tags", []) if value],
                        warnings=[str(value) for value in item.get("warnings", []) if value],
                    )
                )
        return AgentRegistry(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            agents=agents,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


class AgentRegistryBuilder:
    """하네스 기반 built-in agent registry를 만든다."""

    _BUILT_INS: tuple[dict, ...] = (
        {
            "agent_id": "bug-fix-agent",
            "role_id": "bug_fix",
            "label": "Bug Fix Agent",
            "description": "작은 결함을 좁은 범위의 변경으로 수정하는 작업자입니다.",
            "strengths": ["small defect correction", "targeted code changes"],
            "risks": ["can drift into broad refactor if context is weak"],
            "preferred_signals": ["bug_fix", "failing tests"],
            "required_harness_conditions": ["explicit apply", "test command available"],
            "blocked_conditions": ["no source selected"],
            "tags": ["bug", "patch", "guided"],
        },
        {
            "agent_id": "regression-test-agent",
            "role_id": "regression_test",
            "label": "Regression Test Agent",
            "description": "관련 테스트를 고르고 적용 전 안전 검증을 강화하는 작업자입니다.",
            "strengths": ["related test selection", "safety before apply"],
            "risks": ["limited value when no tests exist"],
            "preferred_signals": ["test_practice", "failing tests"],
            "required_harness_conditions": ["test command available"],
            "blocked_conditions": ["no test command"],
            "tags": ["tests", "validation", "safety"],
        },
        {
            "agent_id": "review-agent",
            "role_id": "review",
            "label": "Review Agent",
            "description": "위험 신호를 먼저 보고 더 안전한 경로를 고르는 작업자입니다.",
            "strengths": ["safer path selection", "risk checks"],
            "risks": ["may slow down fast-path changes"],
            "preferred_signals": ["avoid_pattern", "risk_warning"],
            "required_harness_conditions": ["explicit apply"],
            "blocked_conditions": [],
            "tags": ["review", "risk", "safety"],
        },
        {
            "agent_id": "small-refactor-agent",
            "role_id": "small_refactor",
            "label": "Small Refactor Agent",
            "description": "작은 구조 개선을 국소적으로 다루는 작업자입니다.",
            "strengths": ["small refactor", "readability improvements"],
            "risks": ["can overreach without tests"],
            "preferred_signals": ["small_refactor", "cleanup"],
            "required_harness_conditions": ["explicit apply"],
            "blocked_conditions": ["broad refactor request"],
            "tags": ["refactor", "cleanup"],
        },
        {
            "agent_id": "docs-update-agent",
            "role_id": "docs_update",
            "label": "Docs Update Agent",
            "description": "온보딩과 명령 설명을 문서로 정리하는 작업자입니다.",
            "strengths": ["docs updates", "copy alignment"],
            "risks": ["can drift from real CLI if unchecked"],
            "preferred_signals": ["docs_update", "help polish"],
            "required_harness_conditions": ["preserve source artifacts"],
            "blocked_conditions": [],
            "tags": ["docs", "copy", "onboarding"],
        },
        {
            "agent_id": "context-scan-agent",
            "role_id": "context_scan",
            "label": "Context Scan Agent",
            "description": "관련 파일과 테스트 단서를 먼저 모아주는 작업자입니다.",
            "strengths": ["context scan", "related file hints"],
            "risks": ["only as good as project signals"],
            "preferred_signals": ["needs_context", "source choice"],
            "required_harness_conditions": ["preserve source artifacts"],
            "blocked_conditions": [],
            "tags": ["context", "scan", "triage"],
        },
        {
            "agent_id": "diagnose-agent",
            "role_id": "diagnose",
            "label": "Diagnose Agent",
            "description": "수정 전에 진단과 재현 신호를 모으는 작업자입니다.",
            "strengths": ["diagnose safely", "evidence gathering"],
            "risks": ["stops early when context is missing"],
            "preferred_signals": ["diagnose", "report"],
            "required_harness_conditions": ["explicit apply"],
            "blocked_conditions": [],
            "tags": ["diagnose", "evidence"],
        },
        {
            "agent_id": "patch-proposal-agent",
            "role_id": "patch_proposal",
            "label": "Patch Proposal Agent",
            "description": "명시된 intent를 바탕으로 patch proposal을 준비하는 작업자입니다.",
            "strengths": ["patch proposal drafting", "targeted diffs"],
            "risks": ["proposal can be weak without validation"],
            "preferred_signals": ["patch_proposal_ready", "targeted change"],
            "required_harness_conditions": ["explicit apply"],
            "blocked_conditions": ["no selected source"],
            "tags": ["patch", "proposal"],
        },
        {
            "agent_id": "patch-validation-agent",
            "role_id": "patch_validation",
            "label": "Patch Validation Agent",
            "description": "patch proposal을 적용 전에 검증하는 작업자입니다.",
            "strengths": ["validation before apply", "test gating"],
            "risks": ["limited when tests are missing"],
            "preferred_signals": ["patch_proposal_validated", "validation"],
            "required_harness_conditions": ["explicit apply", "test command available"],
            "blocked_conditions": ["no test command"],
            "tags": ["patch", "validation", "safety"],
        },
    )

    def build(self, project_root: Path, harness: HarnessProfile | None = None) -> AgentRegistry:
        """현재 프로젝트 기준 agent registry를 생성한다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        profile = harness or self._load_or_build_harness(root, warnings, errors)
        active_agents = set(profile.active_agents if profile is not None else [])
        recommended_agents = set(profile.recommended_agent_roles if profile is not None else [])
        memory = load_project_memory(root)
        memory_text = " ".join(
            lesson.text.lower()
            for lesson in (memory.lessons if memory is not None else [])
            if getattr(lesson, "text", "")
        )
        agents: list[AgentPassport] = []
        for template in self._BUILT_INS:
            agent_id = str(template["agent_id"])
            status = "equipped" if agent_id in active_agents else "available"
            project_fit_notes = self._build_fit_notes(agent_id, profile, memory_text)
            stats = {
                "recommendations": 1 if agent_id in recommended_agents else 0,
                "equips": 1 if agent_id in active_agents else 0,
                "sessions_seen": 0,
                "adoptions_linked": 0,
            }
            agents.append(
                AgentPassport(
                    schema_version=SCHEMA_VERSION,
                    agent_id=agent_id,
                    role_id=str(template["role_id"]),
                    label=str(template["label"]),
                    description=str(template["description"]),
                    strengths=list(template["strengths"]),
                    risks=list(template["risks"]),
                    preferred_signals=list(template["preferred_signals"]),
                    required_harness_conditions=list(template["required_harness_conditions"]),
                    blocked_conditions=list(template["blocked_conditions"]),
                    source_kind="built_in",
                    status=status,
                    project_fit_notes=project_fit_notes,
                    stats=stats,
                    tags=list(template["tags"]),
                    warnings=[],
                )
            )
        imported_agents, imported_warnings = self._load_imported_agents(
            root,
            active_agents,
            {agent.agent_id for agent in agents},
        )
        agents.extend(imported_agents)
        warnings.extend(imported_warnings)
        return AgentRegistry(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            harness_id=profile.harness_id if profile is not None else None,
            agents=agents,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    @staticmethod
    def recommend(
        request: str,
        *,
        project_root: Path,
        harness: HarnessProfile | None = None,
        registry: AgentRegistry | None = None,
    ) -> list[dict]:
        """현재 요청과 하네스 기준 top agent 추천을 계산한다."""
        root = Path(project_root).resolve()
        profile = harness
        if profile is None and default_harness_profile_path(root).exists():
            profile = HarnessProfileStore().load(default_harness_profile_path(root))
        if profile is None:
            profile = HarnessProfileBuilder().build(root)

        current_registry = registry
        if current_registry is None and default_agent_registry_path(root).exists():
            current_registry = AgentRegistryStore().load(default_agent_registry_path(root))
        if current_registry is None:
            current_registry = AgentRegistryBuilder().build(root, harness=profile)

        project_payload = yaml.safe_load((root / ".cambrian" / "project.yaml").read_text(encoding="utf-8"))
        rules_payload = yaml.safe_load((root / ".cambrian" / "rules.yaml").read_text(encoding="utf-8"))
        skills_payload = yaml.safe_load((root / ".cambrian" / "skills.yaml").read_text(encoding="utf-8"))
        profile_payload = yaml.safe_load((root / ".cambrian" / "profile.yaml").read_text(encoding="utf-8"))
        intent = ProjectSkillRouter().route(
            user_request=str(request),
            project_config=project_payload,
            rules=rules_payload,
            skills=skills_payload,
            profile=profile_payload,
            explicit_options={"project_root": str(root)},
        )
        preferred_signal = str(intent.intent_type)
        memory = load_project_memory(root)
        memory_text = " ".join(
            lesson.text.lower()
            for lesson in (memory.lessons if memory is not None else [])
            if getattr(lesson, "text", "")
        )
        history_store = None
        history_path_for = None
        review_summary_for = None
        try:
            from engine.project_agent_history import (
                AgentPassportHistoryStore,
                default_agent_passport_path,
            )

            history_store = AgentPassportHistoryStore()
            history_path_for = default_agent_passport_path
        except Exception as exc:
            logger.warning("agent passport history load helper unavailable: %s", exc)
        try:
            from engine.project_agent_reviews import load_agent_review_summary

            review_summary_for = load_agent_review_summary
        except Exception as exc:
            logger.warning("agent review helper unavailable: %s", exc)
        recommendations: list[dict] = []
        for agent in current_registry.agents:
            score = 0
            reasons: list[str] = []
            compatibility_status = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else ""
            if preferred_signal in agent.preferred_signals:
                score += 4
                reasons.append(f"{preferred_signal} 요청과 맞습니다")
            if agent.agent_id in profile.recommended_agent_roles:
                score += 1
                reasons.append("현재 하네스 추천 목록에 있습니다")
            if agent.agent_id in profile.active_agents:
                score += 2
                reasons.append("현재 하네스에 장착되어 있습니다")
            if preferred_signal == "bug_fix":
                if agent.agent_id == "bug-fix-agent":
                    score += 3
                    reasons.append("bug fix 요청의 주 작업자입니다")
                elif agent.agent_id == "regression-test-agent":
                    score += 2
                    reasons.append("bug fix 흐름에서 관련 테스트 검증이 중요합니다")
                elif agent.agent_id == "review-agent":
                    score += 1
                    reasons.append("위험 신호를 함께 보는 편이 안전합니다")
            if preferred_signal == "docs_update":
                if agent.agent_id == "docs-update-agent":
                    score += 3
                    reasons.append("docs update 요청의 주 작업자입니다")
                elif agent.agent_id == "review-agent":
                    score += 1
                    reasons.append("문서와 실제 흐름의 드리프트 점검이 필요합니다")
            if preferred_signal == "small_refactor":
                if agent.agent_id == "small-refactor-agent":
                    score += 3
                    reasons.append("small refactor 요청과 직접 맞습니다")
                elif agent.agent_id == "review-agent":
                    score += 1
                    reasons.append("작은 구조 변경도 안전 검토가 필요합니다")
            if "test" in memory_text and agent.agent_id == "regression-test-agent":
                score += 2
                reasons.append("프로젝트 메모리가 테스트 우선 흐름을 강조합니다")
            if profile.notes_summary.get("high_open_count", 0) and agent.agent_id == "review-agent":
                score += 2
                reasons.append("열린 high note가 있어 review 신호가 강합니다")
            if agent.source_kind == "imported":
                score += 1
                reasons.append("다른 프로젝트에서 가져온 작업자 후보입니다")
                if compatibility_status == "good":
                    score += 2
                    reasons.append("현재 harness와 compatibility가 좋습니다")
                elif compatibility_status == "partial":
                    score += 1
                    reasons.append("현재 harness와 compatibility가 부분적으로 맞습니다")
                elif compatibility_status == "weak":
                    reasons.append("현재 harness와 compatibility가 약해 주의가 필요합니다")
                elif compatibility_status == "blocked":
                    score -= 3
                    reasons.append("현재 harness와 compatibility가 막혀 장착 전 검토가 필요합니다")
            if history_store is not None and history_path_for is not None:
                history_path = history_path_for(root, agent.agent_id)
                if history_path.exists():
                    try:
                        history = history_store.load(history_path)
                    except Exception as exc:
                        logger.warning("agent passport history load failed: %s (%s)", history_path, exc)
                    else:
                        adoptions = int(history.totals.get("adoptions", 0) or 0)
                        validations_failed = int(history.totals.get("validations_failed", 0) or 0)
                        diagnoses = int(history.totals.get("diagnoses", 0) or 0)
                        if adoptions > 0:
                            score += min(adoptions, 2)
                            reasons.append(f"이 하네스에서 adoption 성공 {adoptions}건 기록이 있습니다")
                        elif diagnoses > 0 and agent.status == "equipped":
                            score += 1
                            reasons.append(f"이 프로젝트에서 진단 기록 {diagnoses}건이 있습니다")
                        if validations_failed > 0:
                            reasons.append(f"최근 validation 실패 {validations_failed}건은 주의가 필요합니다")
            if review_summary_for is not None:
                try:
                    review_summary = review_summary_for(root, agent.agent_id)
                except Exception as exc:
                    logger.warning("agent review summary load failed: %s (%s)", agent.agent_id, exc)
                else:
                    if review_summary.recent_positive:
                        score += 1
                        reasons.append("recent project review was positive")
                    if review_summary.recent_cautions:
                        score -= 1
                        reasons.append("recent project review suggests caution")
            recommendations.append(
                {
                    "agent_id": agent.agent_id,
                    "label": agent.label,
                    "score": score,
                    "why": _dedupe(reasons) or ["현재 하네스에서 사용 가능한 작업자입니다"],
                    "status": agent.status,
                }
            )
        recommendations.sort(key=lambda item: (-int(item["score"]), str(item["agent_id"])))
        return recommendations

    @staticmethod
    def equip(registry: AgentRegistry, harness: HarnessProfile, agent_id: str) -> tuple[AgentRegistry, HarnessProfile]:
        """에이전트를 현재 하네스에 장착한다."""
        target = agent_id.strip()
        matched = False
        for agent in registry.agents:
            if agent.agent_id != target:
                continue
            matched = True
            compatibility_status = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else ""
            if agent.source_kind == "imported" and compatibility_status == "blocked":
                raise ValueError(f"imported agent compatibility is blocked: {target}")
            agent.status = "equipped"
        if not matched:
            raise KeyError(target)
        harness.active_agents = _dedupe([*harness.active_agents, target])
        return registry, harness

    @staticmethod
    def unequip(registry: AgentRegistry, harness: HarnessProfile, agent_id: str) -> tuple[AgentRegistry, HarnessProfile]:
        """에이전트를 현재 하네스에서 해제한다."""
        target = agent_id.strip()
        matched = False
        for agent in registry.agents:
            if agent.agent_id != target:
                continue
            matched = True
            agent.status = "available"
        if not matched:
            raise KeyError(target)
        harness.active_agents = [item for item in harness.active_agents if item != target]
        return registry, harness

    @staticmethod
    def _build_fit_notes(agent_id: str, harness: HarnessProfile | None, memory_text: str) -> list[str]:
        """하네스와 메모리를 기반으로 간단한 적합 메모를 만든다."""
        if harness is None:
            return []
        notes: list[str] = []
        if agent_id in harness.recommended_agent_roles:
            notes.append("현재 하네스가 이 역할을 기본 추천합니다")
        if harness.test_command and agent_id in {"regression-test-agent", "patch-validation-agent"}:
            notes.append("테스트 명령이 있어 검증 흐름과 잘 맞습니다")
        if "auth" in memory_text and agent_id in {"bug-fix-agent", "review-agent"}:
            notes.append("프로젝트 메모리에 auth 관련 신호가 있습니다")
        if harness.notes_summary.get("high_open_count", 0) and agent_id == "review-agent":
            notes.append("열린 high note가 있어 review 강화가 필요합니다")
        return _dedupe(notes)

    @staticmethod
    def _load_or_build_harness(
        project_root: Path,
        warnings: list[str],
        errors: list[str],
    ) -> HarnessProfile | None:
        """저장된 하네스가 있으면 읽고, 없으면 즉석에서 만든다."""
        path = default_harness_profile_path(project_root)
        try:
            if path.exists():
                return HarnessProfileStore().load(path)
            return HarnessProfileBuilder().build(project_root)
        except Exception as exc:
            message = f"harness load failed: {exc}"
            logger.warning(message)
            warnings.append(message)
            errors.append(message)
            return None

    @staticmethod
    def _load_imported_agents(
        project_root: Path,
        active_agents: set[str],
        existing_ids: set[str],
    ) -> tuple[list[AgentPassport], list[str]]:
        """imported agent 문서를 registry용 passport로 불러온다."""
        warnings: list[str] = []
        try:
            from engine.project_agent_transfer import (
                build_imported_agent_passport,
                load_imported_agent_documents,
            )
        except Exception as exc:
            logger.warning("imported agent helper unavailable: %s", exc)
            return [], [f"imported agent helper unavailable: {exc}"]

        agents: list[AgentPassport] = []
        for document in load_imported_agent_documents(project_root):
            try:
                imported = build_imported_agent_passport(document)
            except Exception as exc:
                path = str(document.get("__path__", "(unknown)"))
                logger.warning("imported agent load failed: %s (%s)", path, exc)
                warnings.append(f"imported agent load failed: {path}")
                continue
            if imported.agent_id in existing_ids:
                path = str(document.get("__path__", "(unknown)"))
                warnings.append(f"imported agent id conflicts with existing registry entry: {imported.agent_id} ({path})")
                continue
            if imported.agent_id in active_agents:
                imported.status = "equipped"
            existing_ids.add(imported.agent_id)
            agents.append(imported)
        return agents, warnings


def render_harness_profile(profile: HarnessProfile) -> str:
    """하네스 프로필을 사람용 텍스트로 렌더링한다."""
    lines = [
        "Cambrian Harness",
        "==================================================",
        "",
        "Project:",
        f"  name : {profile.project_name or '(unknown)'}",
        f"  type : {profile.project_type or '(unknown)'}",
        f"  root : {profile.root}",
        "",
        "Harness:",
        f"  mode       : {profile.mode or 'balanced'}",
        f"  stack      : {', '.join(profile.stack) or 'none yet'}",
        f"  test cmd   : {profile.test_command or 'none yet'}",
        f"  protect    : {', '.join(profile.protect_paths) or 'none'}",
        f"  use cases  : {', '.join(profile.primary_use_cases) or 'none yet'}",
        "",
        "Active agents:",
    ]
    for agent_id in profile.active_agents:
        lines.append(f"  - {agent_id}")
    if not profile.active_agents:
        lines.append("  - none")
    lines.extend(["", "Recommended roles:"])
    for agent_id in profile.recommended_agent_roles:
        lines.append(f"  - {agent_id}")
    if not profile.recommended_agent_roles:
        lines.append("  - none")
    return "\n".join(lines)


def render_harness_doctor(result: dict) -> str:
    """하네스 doctor 결과를 사람용 텍스트로 렌더링한다."""
    lines = [
        "Harness Doctor",
        "==================================================",
        "",
        "Harness:",
        f"  {'present' if result.get('present', False) else 'missing'}",
        "",
        "Profile sources:",
    ]
    for item in result.get("sources", []):
        lines.append(f"  {item}")
    lines.extend(
        [
            "",
            "Agents:",
            f"  {result.get('equipped_count', 0)} equipped",
            f"  {result.get('missing_agents', 0)} missing",
            f"  {result.get('imported_count', 0)} imported",
            f"  {result.get('blocked_compatibility_equipped', 0)} blocked compatibility",
            "",
            "Status:",
            f"  {result.get('status', 'unknown')}",
        ]
    )
    warnings = list(result.get("warnings", []))
    if warnings:
        lines.extend(["", "Warnings:"])
        for item in warnings:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def _history_suffix(history: dict | None) -> str:
    """agent history totals를 짧게 붙인다."""
    if not isinstance(history, dict):
        return ""
    totals = history.get("totals", {}) if isinstance(history.get("totals"), dict) else history
    adoptions = int(totals.get("adoptions", 0) or 0)
    diagnoses = int(totals.get("diagnoses", 0) or 0)
    validations = int(totals.get("validations_passed", 0) or 0)
    parts: list[str] = []
    if adoptions:
        parts.append(f"{adoptions} adoption")
    if diagnoses:
        parts.append(f"{diagnoses} diagnose")
    if validations:
        parts.append(f"{validations} validation")
    if not parts:
        return ""
    return f" ({', '.join(parts)})"


def render_agent_list(registry: AgentRegistry, history_by_agent: dict[str, dict] | None = None) -> str:
    """에이전트 목록을 사람용 텍스트로 렌더링한다."""
    equipped = [agent.agent_id for agent in registry.agents if agent.status == "equipped"]
    available = [agent.agent_id for agent in registry.agents if agent.status != "equipped"]
    lines = [
        "Agents",
        "==================================================",
        "",
        "Equipped:",
    ]
    if equipped:
        for agent_id in equipped:
            history = history_by_agent.get(agent_id) if isinstance(history_by_agent, dict) else None
            agent = next((item for item in registry.agents if item.agent_id == agent_id), None)
            imported_tag = ""
            if agent is not None and agent.source_kind == "imported":
                compatibility = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else ""
                imported_tag = f" [imported{', compatibility: ' + compatibility if compatibility else ''}]"
            lines.append(f"  - {agent_id}{imported_tag}{_history_suffix(history)}")
    else:
        lines.append("  - none")
    lines.extend(["", "Available:"])
    if available:
        for agent_id in available:
            history = history_by_agent.get(agent_id) if isinstance(history_by_agent, dict) else None
            agent = next((item for item in registry.agents if item.agent_id == agent_id), None)
            imported_tag = ""
            if agent is not None and agent.source_kind == "imported":
                compatibility = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else ""
                imported_tag = f" [imported{', compatibility: ' + compatibility if compatibility else ''}]"
            lines.append(f"  - {agent_id}{imported_tag}{_history_suffix(history)}")
    else:
        lines.append("  - none")
    return "\n".join(lines)


def render_agent_show(
    agent: AgentPassport,
    history: dict | None = None,
    review_summary: dict | None = None,
    staffing_summary: dict | None = None,
) -> str:
    """에이전트 상세를 사람용 텍스트로 렌더링한다."""
    lines = [
        "Agent Passport",
        "==================================================",
        "",
        "Agent:",
        f"  id          : {agent.agent_id}",
        f"  label       : {agent.label}",
        f"  role        : {agent.role_id}",
        f"  status      : {agent.status}",
        f"  source kind : {agent.source_kind}",
        f"  description : {agent.description}",
        "",
        "Strengths:",
    ]
    for item in agent.strengths:
        lines.append(f"  - {item}")
    lines.extend(["", "Risks:"])
    for item in agent.risks:
        lines.append(f"  - {item}")
    lines.extend(["", "Required harness conditions:"])
    for item in agent.required_harness_conditions:
        lines.append(f"  - {item}")
    lines.extend(["", "Fit notes:"])
    if agent.project_fit_notes:
        for item in agent.project_fit_notes:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none yet")
    lines.extend(["", "Tags:"])
    for item in agent.tags:
        lines.append(f"  - {item}")
    if agent.source_kind == "imported" and isinstance(agent.stats, dict):
        lines.extend(
            [
                "",
                "Imported:",
                f"  source project : {agent.stats.get('source_project_name') or '(unknown)'}",
                f"  compatibility  : {agent.stats.get('compatibility_status') or 'unknown'}",
            ]
        )
        compatibility_reasons = list(agent.stats.get("compatibility_reasons", [])) if isinstance(agent.stats.get("compatibility_reasons"), list) else []
        if compatibility_reasons:
            lines.extend(["", "Compatibility reasons:"])
            for item in compatibility_reasons[:4]:
                lines.append(f"  - {item}")
    if isinstance(history, dict):
        totals = history.get("totals", {}) if isinstance(history.get("totals"), dict) else history
        lines.extend([
            "",
            "History:",
            f"  sessions seen : {int(totals.get('sessions_seen', 0) or 0)}",
            f"  adoptions     : {int(totals.get('adoptions', 0) or 0)}",
        ])
        recent_win = list(history.get("recent_wins", [])) if isinstance(history.get("recent_wins"), list) else []
        fit_hints = list(history.get("fit_hints", [])) if isinstance(history.get("fit_hints"), list) else []
        if recent_win:
            lines.extend(["", "Recent win:"])
            lines.append(f"  {recent_win[0]}")
        if fit_hints:
            lines.extend(["", "Fit hints:"])
            for item in fit_hints[:3]:
                lines.append(f"  - {item}")
    if isinstance(review_summary, dict) and int(review_summary.get("total", 0) or 0) > 0:
        lines.extend([
            "",
            "Review summary:",
            f"  strong : {int(review_summary.get('strong', 0) or 0)}",
            f"  good   : {int(review_summary.get('good', 0) or 0)}",
            f"  mixed  : {int(review_summary.get('mixed', 0) or 0)}",
            f"  weak   : {int(review_summary.get('weak', 0) or 0)}",
        ])
        recent_cautions = list(review_summary.get("recent_cautions", [])) if isinstance(review_summary.get("recent_cautions"), list) else []
        if recent_cautions:
            lines.extend(["", "Recent cautions:"])
            for item in recent_cautions[:3]:
                lines.append(f"  - {item}")
    if isinstance(staffing_summary, dict) and (
        int(staffing_summary.get("accepted", 0) or 0) > 0
        or int(staffing_summary.get("dismissed", 0) or 0) > 0
    ):
        lines.extend(
            [
                "",
                "Staffing decisions:",
                f"  accepted : {int(staffing_summary.get('accepted', 0) or 0)}",
                f"  dismissed: {int(staffing_summary.get('dismissed', 0) or 0)}",
            ]
        )
        latest = str(staffing_summary.get("latest", "") or "")
        if latest:
            lines.append(f"  latest   : {latest}")
    return "\n".join(lines)


def render_agent_recommendation(request: str, recommendations: list[dict]) -> str:
    """에이전트 추천 결과를 사람용 텍스트로 렌더링한다."""
    lines = [
        "Agent recommendation",
        "==================================================",
        "",
        "Request:",
        f"  {request}",
        "",
        "Best fit:",
    ]
    if not recommendations:
        lines.append("  none")
        return "\n".join(lines)
    for index, item in enumerate(recommendations[:3], start=1):
        why = list(item.get("why", []))
        lines.append(f"  {index}. {item.get('agent_id')}")
        if why:
            lines.append(f"     why: {why[0]}")
    return "\n".join(lines)
