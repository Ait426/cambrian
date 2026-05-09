"""Cambrian 프로젝트용 dispatch board 계산."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_agent_history import AgentPassportHistoryStore, default_agent_passport_path
from engine.project_agent_router import AgentRoute, HarnessAwareAgentRouter
from engine.project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from engine.project_harness import HarnessProfileBuilder, HarnessProfileStore, default_harness_profile_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
_BOARD_TEAM_LIMIT = 3
_BOARD_HIRE_LIMIT = 2
_BOARD_FIRE_LIMIT = 2
_REQUEST_SUPPORT_LIMIT = 2

_USE_CASE_SAMPLES: dict[str, tuple[str, ...]] = {
    "bug_fix": ("fix a small bug", "fix the login bug"),
    "small_refactor": ("clean up a small function",),
    "docs_update": ("update the project docs",),
    "review_candidate": ("review the safer path",),
    "context_scan": ("find the files related to this task",),
    "diagnose": ("diagnose the likely root cause",),
    "patch_proposal": ("prepare a small patch proposal",),
    "patch_validation": ("validate a proposed patch",),
}


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


def _clamp_score(value: float) -> float:
    """점수를 0~1 사이로 제한한다."""
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return round(float(value), 4)


def default_dispatch_board_path(project_root: Path) -> Path:
    """기본 dispatch board 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "dispatch_board.yaml"


@dataclass
class DispatchCandidate:
    """현재 하네스에 대한 agent 배치 후보."""

    agent_id: str
    role_id: str
    source_kind: str
    current_status: str
    compatibility_status: str | None
    score: float
    recommendation: str
    reasons: list[str]
    warnings: list[str]
    tags: list[str]
    project_fit: dict

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class DispatchBoard:
    """현재 프로젝트 하네스 기준 dispatch 추천 보드."""

    schema_version: str
    generated_at: str
    project_name: str | None
    harness_id: str | None
    mode: str
    request: str | None
    candidates: list[DispatchCandidate]
    top_team: list[str]
    top_hire: list[str]
    top_fire: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload


class DispatchBoardStore:
    """Dispatch board 저장/로드."""

    def save(self, board: DispatchBoard, path: Path) -> Path:
        """board를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(board.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> DispatchBoard:
        """저장된 board를 불러온다."""
        payload = yaml.safe_load(Path(path).resolve().read_text(encoding="utf-8")) or {}
        return DispatchBoard(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            mode=str(payload.get("mode", "board")),
            request=str(payload.get("request")) if payload.get("request") is not None else None,
            candidates=[
                DispatchCandidate(
                    agent_id=str(item.get("agent_id", "")),
                    role_id=str(item.get("role_id", "")),
                    source_kind=str(item.get("source_kind", "")),
                    current_status=str(item.get("current_status", "")),
                    compatibility_status=str(item.get("compatibility_status")) if item.get("compatibility_status") is not None else None,
                    score=float(item.get("score", 0.0) or 0.0),
                    recommendation=str(item.get("recommendation", "consider")),
                    reasons=[str(reason) for reason in item.get("reasons", []) if reason],
                    warnings=[str(warning) for warning in item.get("warnings", []) if warning],
                    tags=[str(tag) for tag in item.get("tags", []) if tag],
                    project_fit=dict(item.get("project_fit", {})) if isinstance(item.get("project_fit"), dict) else {},
                )
                for item in payload.get("candidates", [])
                if isinstance(item, dict)
            ],
            top_team=[str(item) for item in payload.get("top_team", []) if item],
            top_hire=[str(item) for item in payload.get("top_hire", []) if item],
            top_fire=[str(item) for item in payload.get("top_fire", []) if item],
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
            next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        )


class DispatchBoardBuilder:
    """현재 하네스 기준 dispatch board를 계산한다."""

    def build(self, project_root: Path, request: str | None = None) -> DispatchBoard:
        """board 모드 또는 request 모드 dispatch 추천을 만든다."""
        root = Path(project_root).resolve()
        harness = self._load_harness(root)
        registry = self._load_registry(root, harness)
        router = HarnessAwareAgentRouter()
        warnings: list[str] = []
        errors: list[str] = []

        if request:
            route_context = router.route(str(request), root)
            candidates = self._build_request_candidates(root, route_context.routes)
            top_team = []
            if route_context.lead_agent_id:
                top_team.append(route_context.lead_agent_id)
            top_team.extend(route_context.supporting_agent_ids[:_REQUEST_SUPPORT_LIMIT])
            top_hire = [item.agent_id for item in candidates if item.recommendation == "hire"][:_BOARD_HIRE_LIMIT]
            top_fire = [item.agent_id for item in candidates if item.recommendation == "fire"][:_BOARD_FIRE_LIMIT]
            warnings.extend(route_context.warnings)
            next_actions = []
            if top_hire:
                next_actions.append(f"cambrian agent hire {top_hire[0]}")
            return DispatchBoard(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                project_name=harness.project_name,
                harness_id=harness.harness_id,
                mode="request",
                request=str(request),
                candidates=candidates,
                top_team=_dedupe(top_team),
                top_hire=top_hire,
                top_fire=top_fire,
                warnings=_dedupe(warnings),
                errors=errors,
                next_actions=next_actions,
            )

        sample_requests = self._sample_requests(harness.primary_use_cases)
        aggregate: dict[str, dict] = {}
        for sample in sample_requests:
            route_context = router.route(sample, root)
            for route in route_context.routes:
                entry = aggregate.setdefault(
                    route.agent_id,
                    {
                        "route": route,
                        "score_total": 0.0,
                        "seen": 0,
                        "reasons": [],
                        "warnings": [],
                    },
                )
                entry["route"] = route
                entry["score_total"] += float(route.score)
                entry["seen"] += 1
                entry["reasons"].extend(route.reasons)
                entry["warnings"].extend(route.warnings)
            warnings.extend(route_context.warnings)

        candidates: list[DispatchCandidate] = []
        for agent in registry.agents:
            aggregate_entry = aggregate.get(agent.agent_id)
            compatibility_status = None
            average_score = 0.0
            reasons: list[str] = []
            route_warnings: list[str] = []
            if aggregate_entry is not None:
                route = aggregate_entry["route"]
                compatibility_status = route.compatibility_status
                seen = max(1, int(aggregate_entry["seen"]))
                average_score = float(aggregate_entry["score_total"]) / seen
                reasons.extend(list(aggregate_entry["reasons"]))
                route_warnings.extend(list(aggregate_entry["warnings"]))
            else:
                compatibility_status = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else None

            history = self._load_history_summary(root, agent.agent_id)
            review_summary = self._load_review_summary(root, agent.agent_id)
            if review_summary.get("recent_positive"):
                average_score += 0.05
            if review_summary.get("recent_cautions"):
                average_score -= 0.05
            recommendation = self._recommend_board_candidate(
                agent=agent,
                harness=harness,
                average_score=average_score,
                compatibility_status=compatibility_status,
                history=history,
                review_summary=review_summary,
            )
            reasons.extend(
                self._board_reasons(
                    agent=agent,
                    harness=harness,
                    compatibility_status=compatibility_status,
                    history=history,
                    review_summary=review_summary,
                    recommendation=recommendation,
                )
            )
            project_fit = {
                "harness_fit": round(min(1.0, average_score + (0.1 if agent.agent_id in harness.recommended_agent_roles else 0.0)), 4),
                "memory_fit": 1.0 if agent.agent_id in harness.recommended_agent_roles else 0.0,
                "local_history_fit": round(min(1.0, float(history.get("adoptions", 0)) * 0.2 + float(history.get("diagnoses", 0)) * 0.05), 4),
                "request_fit": None,
            }
            candidates.append(
                DispatchCandidate(
                    agent_id=agent.agent_id,
                    role_id=agent.role_id,
                    source_kind=agent.source_kind,
                    current_status=agent.status,
                    compatibility_status=compatibility_status or None,
                    score=_clamp_score(average_score + (0.05 if agent.status == "equipped" else 0.0)),
                    recommendation=recommendation,
                    reasons=_dedupe(reasons),
                    warnings=_dedupe(route_warnings),
                    tags=list(agent.tags),
                    project_fit=project_fit,
                )
            )

        candidates.sort(key=lambda item: (-item.score, item.agent_id))
        top_team = [item.agent_id for item in candidates if item.recommendation in {"keep", "hire"}][: _BOARD_TEAM_LIMIT]
        top_hire = [item.agent_id for item in candidates if item.recommendation == "hire"][:_BOARD_HIRE_LIMIT]
        top_fire = [item.agent_id for item in candidates if item.recommendation == "fire"][:_BOARD_FIRE_LIMIT]
        next_actions: list[str] = []
        if top_hire:
            next_actions.append(f"cambrian agent hire {top_hire[0]}")
        if top_fire:
            next_actions.append(f"cambrian agent fire {top_fire[0]}")
        return DispatchBoard(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            project_name=harness.project_name,
            harness_id=harness.harness_id,
            mode="board",
            request=None,
            candidates=candidates,
            top_team=top_team,
            top_hire=top_hire,
            top_fire=top_fire,
            warnings=_dedupe(warnings),
            errors=errors,
            next_actions=next_actions,
        )

    def _load_harness(self, root: Path):
        path = default_harness_profile_path(root)
        if path.exists():
            return HarnessProfileStore().load(path)
        return HarnessProfileBuilder().build(root)

    def _load_registry(self, root: Path, harness):
        path = default_agent_registry_path(root)
        if path.exists():
            return AgentRegistryStore().load(path)
        return AgentRegistryBuilder().build(root, harness=harness)

    def _sample_requests(self, primary_use_cases: list[str]) -> list[str]:
        requests: list[str] = []
        for use_case in primary_use_cases:
            requests.extend(_USE_CASE_SAMPLES.get(str(use_case), ()))
        if not requests:
            requests.extend(_USE_CASE_SAMPLES["bug_fix"])
        return _dedupe(requests)

    def _load_history_summary(self, root: Path, agent_id: str) -> dict:
        path = default_agent_passport_path(root, agent_id)
        if not path.exists():
            return {}
        try:
            history = AgentPassportHistoryStore().load(path)
        except Exception as exc:
            logger.warning("agent passport history load failed: %s (%s)", path, exc)
            return {}
        return {
            "adoptions": int(history.totals.get("adoptions", 0) or 0),
            "diagnoses": int(history.totals.get("diagnoses", 0) or 0),
            "validations_passed": int(history.totals.get("validations_passed", 0) or 0),
            "validations_failed": int(history.totals.get("validations_failed", 0) or 0),
            "recent_wins": list(history.recent_wins[:2]),
            "recent_risks": list(history.recent_risks[:2]),
        }

    def _load_review_summary(self, root: Path, agent_id: str) -> dict:
        try:
            from engine.project_agent_reviews import load_agent_review_summary
        except Exception as exc:
            logger.warning("agent review helper unavailable: %s", exc)
            return {}
        try:
            return load_agent_review_summary(root, agent_id).to_dict()
        except Exception as exc:
            logger.warning("agent review summary load failed: %s (%s)", agent_id, exc)
            return {}

    def _recommend_board_candidate(self, *, agent, harness, average_score: float, compatibility_status: str | None, history: dict, review_summary: dict) -> str:
        if agent.source_kind == "imported" and compatibility_status == "blocked":
            return "blocked"
        if agent.status == "equipped":
            if average_score >= 0.45 or agent.agent_id in harness.recommended_agent_roles:
                return "keep"
            if int(review_summary.get("strong", 0) or 0) + int(review_summary.get("good", 0) or 0) > int(review_summary.get("weak", 0) or 0):
                return "consider"
            if history.get("adoptions", 0) or history.get("diagnoses", 0):
                return "consider"
            return "fire"
        if average_score >= 0.55:
            return "hire"
        if average_score >= 0.25:
            return "consider"
        if agent.source_kind == "imported" and compatibility_status == "blocked":
            return "blocked"
        return "consider"

    def _board_reasons(self, *, agent, harness, compatibility_status: str | None, history: dict, review_summary: dict, recommendation: str) -> list[str]:
        reasons: list[str] = []
        if agent.agent_id in harness.recommended_agent_roles:
            reasons.append("현재 하네스 추천 역할에 포함됩니다")
        if agent.status == "equipped":
            reasons.append("현재 하네스에 이미 장착되어 있습니다")
        if history.get("adoptions", 0):
            reasons.append(f"이 프로젝트에서 adoption 성공 {history['adoptions']}건이 있습니다")
        elif history.get("diagnoses", 0):
            reasons.append(f"이 프로젝트에서 진단 기록 {history['diagnoses']}건이 있습니다")
        if history.get("validations_failed", 0):
            reasons.append(f"최근 validation 실패 {history['validations_failed']}건을 함께 봐야 합니다")
        if agent.source_kind == "imported":
            if compatibility_status == "good":
                reasons.append("현재 하네스와 compatibility가 좋습니다")
            elif compatibility_status == "partial":
                reasons.append("현재 하네스와 compatibility가 부분적으로 맞습니다")
            elif compatibility_status == "weak":
                reasons.append("현재 하네스와 compatibility가 약해 보조 후보로 적합합니다")
            elif compatibility_status == "blocked":
                reasons.append("현재 하네스와 compatibility가 막혀 있어 장착할 수 없습니다")
        if review_summary.get("recent_positive"):
            reasons.append("recent project review was positive")
        if review_summary.get("recent_cautions"):
            reasons.append("recent project review suggests caution")
        if recommendation == "fire":
            reasons.append("현재 하네스 초점과 최근 활동 기준으로 우선순위가 낮습니다")
        return _dedupe(reasons)

    def _build_request_candidates(self, root: Path, routes: list[AgentRoute]) -> list[DispatchCandidate]:
        candidates: list[DispatchCandidate] = []
        route_by_id = {route.agent_id: route for route in routes}
        try:
            from engine.project_agent_trials import load_recent_agent_trial_summary

            recent_trial = load_recent_agent_trial_summary(root)
        except Exception as exc:
            logger.warning("recent trial summary load failed: %s", exc)
            recent_trial = None
        for route in routes:
            history = self._load_history_summary(root, route.agent_id)
            review_summary = self._load_review_summary(root, route.agent_id)
            adjusted_score = float(route.score)
            if review_summary.get("recent_positive"):
                adjusted_score += 0.05
            if review_summary.get("recent_cautions"):
                adjusted_score -= 0.05
            trial_reasons: list[str] = []
            trial_warnings: list[str] = []
            if isinstance(recent_trial, dict) and recent_trial.get("shadow_agent_id") == route.agent_id:
                trial_result = str(recent_trial.get("result", "") or "unknown")
                trial_reasons.append(f"recent shadow trial result: {trial_result}")
                if trial_result in {"shadow_stronger", "comparable"}:
                    adjusted_score += 0.03
                elif trial_result == "lead_stronger":
                    trial_warnings.append("recent shadow trial favored the current lead")
            recommendation = "consider"
            if route.compatibility_status == "blocked":
                recommendation = "blocked"
            elif route.status == "equipped" and adjusted_score >= 0.45:
                recommendation = "keep"
            elif route.status != "equipped" and adjusted_score >= 0.55:
                recommendation = "hire"
            elif adjusted_score < 0.2 and route.status == "equipped":
                recommendation = "fire"
            candidates.append(
                DispatchCandidate(
                    agent_id=route.agent_id,
                    role_id=route.role_id,
                    source_kind=route.source_kind,
                    current_status=route.status,
                    compatibility_status=route.compatibility_status,
                    score=_clamp_score(adjusted_score),
                    recommendation=recommendation,
                    reasons=_dedupe(
                        trial_reasons
                        + list(route.reasons)
                        + list(history.get("recent_wins", []))
                        + (["recent project review was positive"] if review_summary.get("recent_positive") else [])
                    ),
                    warnings=_dedupe(
                        list(route.warnings)
                        + list(history.get("recent_risks", []))
                        + (["recent project review suggests caution"] if review_summary.get("recent_cautions") else [])
                        + trial_warnings
                    ),
                    tags=list(route.tags),
                    project_fit={
                        "harness_fit": _clamp_score(adjusted_score),
                        "memory_fit": 0.0,
                        "local_history_fit": round(min(1.0, float(history.get("adoptions", 0)) * 0.2), 4),
                        "request_fit": _clamp_score(adjusted_score),
                    },
                )
            )
        candidates.sort(key=lambda item: (-item.score, item.agent_id))
        return candidates


def render_dispatch_board(board: DispatchBoard) -> str:
    """Dispatch board를 사람이 읽기 쉬운 텍스트로 렌더링한다."""
    title = "Dispatch Recommendation" if board.mode == "request" else "Dispatch Board"
    lines = [
        title,
        "==================================================",
        "",
        "Harness:",
        f"  {board.project_name or '(unknown project)'}",
    ]
    if board.request:
        lines.extend(["", "Request:", f"  {board.request}"])
    if board.top_team:
        label = "Lead / support" if board.mode == "request" else "Best current team"
        lines.extend(["", f"{label}:"])
        for agent_id in board.top_team:
            lines.append(f"  - {agent_id}")
    if board.top_hire:
        lines.extend(["", "Strong hire candidates:"])
        for agent_id in board.top_hire:
            candidate = next((item for item in board.candidates if item.agent_id == agent_id), None)
            lines.append(f"  - {agent_id}")
            if candidate is not None and candidate.reasons:
                lines.append(f"    why: {candidate.reasons[0]}")
    if board.top_fire:
        lines.extend(["", "Possible removals:"])
        for agent_id in board.top_fire:
            candidate = next((item for item in board.candidates if item.agent_id == agent_id), None)
            lines.append(f"  - {agent_id}")
            if candidate is not None and candidate.reasons:
                lines.append(f"    why: {candidate.reasons[-1]}")
    if board.next_actions:
        lines.extend(["", "Next:"])
        for action in board.next_actions:
            lines.append(f"  {action}")
    return "\n".join(lines)
