"""프로젝트 기억을 스킬 추천에 반영하는 조정기."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from engine.project_memory import (
    ProjectMemoryStore,
    default_memory_overrides_path,
    memory_override_counts,
    merge_memory_overrides,
)
from engine.project_memory_hygiene import default_memory_hygiene_path, hygiene_index, load_memory_hygiene
from engine.project_memory_overrides import load_memory_overrides

logger = logging.getLogger(__name__)


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "before",
    "after",
    "into",
    "from",
    "your",
    "need",
    "needs",
    "should",
    "would",
    "will",
    "have",
    "has",
    "are",
    "fix",
    "해",
}

_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "로그인": ("login", "auth"),
    "login": ("로그인", "auth"),
    "인증": ("auth", "login"),
    "auth": ("인증", "login"),
    "에러": ("error", "bug"),
    "오류": ("error", "bug"),
    "error": ("에러", "bug"),
    "버그": ("bug", "fix"),
    "bug": ("버그", "fix"),
    "수정": ("fix", "patch"),
    "patch": ("수정",),
    "테스트": ("test", "tests", "pytest"),
    "test": ("테스트", "tests", "pytest"),
    "테스트생성": ("test_generation", "tests"),
    "리팩터링": ("refactor", "small_refactor"),
    "refactor": ("리팩터링", "small_refactor"),
    "문서": ("docs", "documentation", "readme"),
    "docs": ("문서", "documentation", "readme"),
}

_INTENT_SKILL_MAP = {
    "bug_fix": "bug_fix",
    "test_generation": "test_generation",
    "small_refactor": "small_refactor",
    "docs_update": "docs_update",
    "review_candidate": "review_candidate",
}


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _extract_tokens(text: str) -> list[str]:
    """단순 토큰 목록을 만든다."""
    raw_tokens = re.findall(r"[a-z0-9_./-]+|[가-힣]+", str(text or "").lower())
    return [
        token
        for token in raw_tokens
        if len(token) >= 2 and token not in _STOPWORDS
    ]


def _expand_tokens(tokens: list[str]) -> list[str]:
    """기본 토큰에 간단한 별칭을 추가한다."""
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(_TOKEN_ALIASES.get(token, ()))
    return _dedupe(expanded)


def _kind_matches_intent(kind: str, intent_type: str) -> bool:
    """lesson kind와 intent의 느슨한 연관성을 판단한다."""
    if kind == "test_practice":
        return intent_type in {"bug_fix", "test_generation", "small_refactor"}
    if kind in {"avoid_pattern", "risk_warning", "missing_evidence"}:
        return intent_type in {"bug_fix", "small_refactor", "review_candidate"}
    if kind in {"successful_pattern", "adoption_reason"}:
        return intent_type in _INTENT_SKILL_MAP
    if kind == "next_action":
        return True
    return False


def _extract_test_paths(text: str) -> list[str]:
    """lesson 문장에서 테스트 경로 후보를 찾는다."""
    return _dedupe(re.findall(r"(tests/[A-Za-z0-9_./-]+\.py)", str(text or "")))


def _ensure_skill_ids(available_skills: Any) -> set[str]:
    """입력 형태와 무관하게 사용 가능한 스킬 ID 집합을 만든다."""
    if isinstance(available_skills, set):
        return {str(item) for item in available_skills if item}
    if isinstance(available_skills, dict):
        values = available_skills.get("recommended_skills", [])
        collected = {
            str(item.get("id"))
            for item in values
            if isinstance(item, dict) and item.get("id")
        }
        collected.update(
            str(item)
            for item in available_skills.get("selection", {}).get("default", [])
            if item
        )
        return collected
    return {str(item) for item in available_skills or [] if item}


@dataclass
class RelevantLesson:
    """현재 요청과 겹치는 lesson."""

    lesson_id: str
    kind: str
    text: str
    confidence: float
    matched_terms: list[str]
    reason: str
    source_refs: list[str]
    tags: list[str]
    pinned: bool = False
    suppressed: bool = False
    human_note: str | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class MemorySkillAdjustment:
    """프로젝트 기억으로 인한 스킬 점수 조정."""

    skill_id: str
    delta: float
    reason: str
    lesson_ids: list[str]

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class MemoryRoutingContext:
    """메모리 기반 라우팅 보조 컨텍스트."""

    enabled: bool
    lessons_path: str | None
    overrides_path: str | None
    relevant_lessons: list[RelevantLesson]
    skill_adjustments: list[MemorySkillAdjustment]
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    omitted: dict = field(default_factory=dict)
    hygiene: dict = field(default_factory=dict)
    reason: str | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "enabled": self.enabled,
            "lessons_path": self.lessons_path,
            "overrides_path": self.overrides_path,
            "relevant_lessons": [item.to_dict() for item in self.relevant_lessons],
            "skill_adjustments": [item.to_dict() for item in self.skill_adjustments],
            "warnings": list(self.warnings),
            "next_actions": list(self.next_actions),
            "omitted": dict(self.omitted),
            "hygiene": dict(self.hygiene),
            "reason": self.reason,
        }


class MemoryAwareSkillTuner:
    """프로젝트 기억을 읽어 스킬 추천을 미세 조정한다."""

    def build_context(
        self,
        user_request: str,
        lessons_path: Path | None,
        available_skills: Any,
        *,
        intent_type: str = "unknown",
        limit: int = 5,
    ) -> MemoryRoutingContext:
        """관련 lesson과 스킬 조정 컨텍스트를 만든다."""
        available_skill_ids = _ensure_skill_ids(available_skills)
        if lessons_path is None:
            return MemoryRoutingContext(
                enabled=False,
                lessons_path=None,
                overrides_path=None,
                relevant_lessons=[],
                skill_adjustments=[],
                omitted={"suppressed_count": 0},
                reason="no lessons path configured",
            )

        lessons_file = Path(lessons_path).resolve()
        if not lessons_file.exists():
            return MemoryRoutingContext(
                enabled=False,
                lessons_path=str(lessons_file),
                overrides_path=str(default_memory_overrides_path(lessons_file.parents[2])),
                relevant_lessons=[],
                skill_adjustments=[],
                omitted={"suppressed_count": 0},
                reason="no lessons.yaml found",
            )

        project_root = lessons_file.parents[2]
        overrides_path = default_memory_overrides_path(project_root)
        hygiene_path = default_memory_hygiene_path(project_root)
        try:
            memory = ProjectMemoryStore().load(lessons_file)
            overrides = load_memory_overrides(project_root)
            memory = merge_memory_overrides(memory, overrides)
        except (OSError, ValueError) as exc:
            logger.warning("project memory load failed: %s (%s)", lessons_file, exc)
            return MemoryRoutingContext(
                enabled=False,
                lessons_path=str(lessons_file),
                overrides_path=str(overrides_path),
                relevant_lessons=[],
                skill_adjustments=[],
                warnings=[f"프로젝트 기억을 읽지 못했습니다: {lessons_file}"],
                omitted={"suppressed_count": 0},
                reason="memory load failed",
            )

        counts = memory_override_counts(memory)
        hygiene_report = load_memory_hygiene(project_root)
        hygiene_map = hygiene_index(hygiene_report) if hygiene_report is not None else {}
        omitted_due_to_hygiene: list[dict] = []
        request_tokens = set(_expand_tokens(_extract_tokens(user_request)))
        if not request_tokens:
            return MemoryRoutingContext(
                enabled=True,
                lessons_path=str(lessons_file),
                overrides_path=str(overrides_path),
                relevant_lessons=[],
                skill_adjustments=[],
                omitted={"suppressed_count": counts["suppressed"]},
                hygiene={
                    "enabled": hygiene_report is not None,
                    "hygiene_path": str(hygiene_path),
                    "omitted_due_to_hygiene": [],
                },
                reason="request tokens were empty",
            )

        ranked: list[tuple[float, RelevantLesson]] = []
        for lesson in memory.lessons:
            if lesson.status != "active":
                continue
            lesson_text_tokens = set(_expand_tokens(_extract_tokens(lesson.text)))
            lesson_tag_tokens = set(_expand_tokens([str(item) for item in lesson.tags]))
            tag_matches = sorted(request_tokens & lesson_tag_tokens)
            text_matches = sorted(request_tokens & lesson_text_tokens)
            matched_terms = _dedupe([*tag_matches, *text_matches])
            if not matched_terms:
                continue

            hygiene_item = hygiene_map.get(lesson.lesson_id)
            if hygiene_item is not None and hygiene_item.status in {"stale", "orphaned", "conflicting"}:
                omitted_due_to_hygiene.append(
                    {
                        "lesson_id": lesson.lesson_id,
                        "status": hygiene_item.status,
                        "reason": hygiene_item.reasons[0] if hygiene_item.reasons else "needs review",
                    }
                )
                continue

            score = 0.0
            if tag_matches:
                score += 0.35
            if text_matches:
                score += 0.25
            if _kind_matches_intent(lesson.kind, intent_type):
                score += 0.20
            score += float(lesson.confidence) * 0.20
            if hygiene_item is not None and hygiene_item.status == "watch":
                score -= 0.05
            score = min(score, 1.0)
            if score < 0.25:
                continue

            reason_parts: list[str] = []
            if tag_matches:
                reason_parts.append(f"tag matched: {', '.join(tag_matches[:2])}")
            if text_matches:
                reason_parts.append(f"text matched: {', '.join(text_matches[:2])}")
            if _kind_matches_intent(lesson.kind, intent_type):
                reason_parts.append(f"{lesson.kind} matched {intent_type}")
            if hygiene_item is not None and hygiene_item.status == "watch":
                reason_parts.append("needs review")

            ranked.append(
                (
                    score,
                    RelevantLesson(
                        lesson_id=lesson.lesson_id,
                        kind=lesson.kind,
                        text=lesson.text,
                        confidence=float(lesson.confidence),
                        matched_terms=matched_terms,
                        reason="; ".join(reason_parts) or f"matched request term: {matched_terms[0]}",
                        source_refs=list(lesson.source_refs),
                        tags=list(lesson.tags),
                        pinned=lesson.pinned,
                        suppressed=lesson.suppressed,
                        human_note=lesson.human_note,
                    ),
                )
            )

        ranked.sort(
            key=lambda item: (
                0 if item[1].pinned else 1,
                -item[0],
                -item[1].confidence,
                item[1].lesson_id,
            )
        )
        relevant_lessons = [item[1] for item in ranked[: max(1, limit)]]
        adjustments, warnings, next_actions = self._build_adjustments(
            relevant_lessons=relevant_lessons,
            available_skill_ids=available_skill_ids,
            intent_type=intent_type,
        )
        return MemoryRoutingContext(
            enabled=True,
            lessons_path=str(lessons_file),
            overrides_path=str(overrides_path),
            relevant_lessons=relevant_lessons,
            skill_adjustments=adjustments,
            warnings=_dedupe([
                *warnings,
                *[
                    f"Remembered lesson needs review: {item.text}"
                    for item in relevant_lessons
                    if "needs review" in item.reason
                ],
            ]),
            next_actions=next_actions,
            omitted={"suppressed_count": counts["suppressed"]},
            hygiene={
                "enabled": hygiene_report is not None,
                "hygiene_path": str(hygiene_path),
                "omitted_due_to_hygiene": omitted_due_to_hygiene,
            },
            reason=None,
        )

    def apply_adjustments(
        self,
        base_routes: list[object],
        memory_context: MemoryRoutingContext,
        *,
        route_factory: Callable[..., object] | None = None,
    ) -> list[object]:
        """기존 라우팅 결과에 메모리 점수 조정을 반영한다."""
        if not memory_context.enabled or not memory_context.skill_adjustments:
            return list(base_routes)

        route_factory = route_factory or (base_routes[0].__class__ if base_routes else None)
        adjustment_map: dict[str, dict[str, Any]] = {}
        for item in memory_context.skill_adjustments:
            bucket = adjustment_map.setdefault(
                item.skill_id,
                {"delta": 0.0, "reasons": [], "lesson_ids": []},
            )
            bucket["delta"] += float(item.delta)
            bucket["reasons"].append(item.reason)
            bucket["lesson_ids"].extend(item.lesson_ids)

        adjusted_routes: list[object] = []
        seen_skill_ids: set[str] = set()
        for route in base_routes:
            skill_id = str(getattr(route, "skill_id"))
            seen_skill_ids.add(skill_id)
            bucket = adjustment_map.get(skill_id, {})
            delta = float(bucket.get("delta", 0.0))
            reasons = _dedupe([str(item) for item in bucket.get("reasons", []) if item])
            reason_text = str(getattr(route, "reason", ""))
            if reasons:
                memory_reason = "; ".join(reasons[:2])
                reason_text = f"{reason_text}; adjusted by project memory: {memory_reason}"
            adjusted_routes.append(
                route_factory(
                    skill_id=skill_id,
                    score=max(0.05, round(float(getattr(route, "score", 0.0)) + delta, 2)),
                    reason=reason_text,
                )
            )

        for skill_id, bucket in adjustment_map.items():
            if skill_id in seen_skill_ids or float(bucket.get("delta", 0.0)) <= 0.0:
                continue
            if route_factory is None:
                continue
            memory_reason = "; ".join(_dedupe([str(item) for item in bucket.get("reasons", []) if item])[:2])
            adjusted_routes.append(
                route_factory(
                    skill_id=skill_id,
                    score=max(0.1, round(0.42 + float(bucket["delta"]), 2)),
                    reason=f"added by project memory: {memory_reason}",
                )
            )

        adjusted_routes.sort(
            key=lambda item: (-float(getattr(item, "score", 0.0)), str(getattr(item, "skill_id", "")))
        )
        return adjusted_routes

    @staticmethod
    def _build_adjustments(
        *,
        relevant_lessons: list[RelevantLesson],
        available_skill_ids: set[str],
        intent_type: str,
    ) -> tuple[list[MemorySkillAdjustment], list[str], list[str]]:
        """lesson kind를 스킬 조정과 안내 문구로 변환한다."""
        adjustments: dict[str, MemorySkillAdjustment] = {}
        warnings: list[str] = []
        next_actions: list[str] = []
        primary_skill = _INTENT_SKILL_MAP.get(intent_type)

        def add_adjustment(skill_id: str, delta: float, reason: str, lesson_id: str) -> None:
            if skill_id not in available_skill_ids:
                warnings.append(f"프로젝트 기억이 '{skill_id}' 스킬을 추천했지만 현재 설정에 없습니다.")
                return
            if skill_id not in adjustments:
                adjustments[skill_id] = MemorySkillAdjustment(
                    skill_id=skill_id,
                    delta=round(delta, 2),
                    reason=reason,
                    lesson_ids=[lesson_id],
                )
                return
            current = adjustments[skill_id]
            current.delta = round(current.delta + delta, 2)
            current.lesson_ids = _dedupe([*current.lesson_ids, lesson_id])
            current.reason = reason

        for lesson in relevant_lessons:
            lowered = lesson.text.lower()
            if lesson.kind == "test_practice":
                add_adjustment(
                    "regression_test",
                    0.30,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                add_adjustment(
                    "test_generation",
                    0.10,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                for test_path in _extract_test_paths(lesson.text):
                    next_actions.append(f"Include {test_path} before patch validation.")
            elif lesson.kind == "avoid_pattern":
                add_adjustment(
                    "review_candidate",
                    0.20,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                add_adjustment(
                    "regression_test",
                    0.10,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                warnings.append(f"Remembered risk: {lesson.text}")
                if "refactor" in lowered or "리팩터링" in lowered:
                    add_adjustment(
                        "small_refactor",
                        -0.10,
                        f"{lesson.text}",
                        lesson.lesson_id,
                    )
            elif lesson.kind == "successful_pattern":
                if primary_skill:
                    add_adjustment(
                        primary_skill,
                        0.15,
                        f"{lesson.text}",
                        lesson.lesson_id,
                    )
                add_adjustment(
                    "review_candidate",
                    0.05,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
            elif lesson.kind == "missing_evidence":
                add_adjustment(
                    "regression_test",
                    0.15,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                add_adjustment(
                    "review_candidate",
                    0.10,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                next_actions.append(f"Collect missing evidence before proceeding: {lesson.text}")
            elif lesson.kind == "adoption_reason":
                if primary_skill:
                    add_adjustment(
                        primary_skill,
                        0.10,
                        f"{lesson.text}",
                        lesson.lesson_id,
                    )
            elif lesson.kind == "risk_warning":
                add_adjustment(
                    "review_candidate",
                    0.20,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                add_adjustment(
                    "regression_test",
                    0.10,
                    f"{lesson.text}",
                    lesson.lesson_id,
                )
                warnings.append(f"Remembered risk: {lesson.text}")
            elif lesson.kind == "next_action":
                next_actions.append(lesson.text)

        return (
            sorted(adjustments.values(), key=lambda item: (-item.delta, item.skill_id)),
            _dedupe(warnings)[:5],
            _dedupe(next_actions)[:5],
        )


def render_memory_recommendation(
    *,
    user_request: str,
    relevant_lessons: list[dict],
    routes: list[dict],
    next_actions: list[str],
) -> str:
    """memory recommend 결과를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Memory-aware recommendation",
        "==================================================",
        "",
        "Request:",
        f"  {user_request}",
        "",
        "Relevant lessons:",
    ]
    if relevant_lessons:
        for index, lesson in enumerate(relevant_lessons, start=1):
            lines.append(f"  {index}. {lesson.get('text')}")
            lines.append(f"     why: {lesson.get('reason') or 'matched project memory'}")
    else:
        lines.append("  none")

    lines.extend(["", "Recommended skills:"])
    if routes:
        for route in routes:
            reason = str(route.get("reason", ""))
            if "project memory" in reason:
                lines.append(
                    f"  - {route.get('skill_id')}  ({reason})"
                )
            else:
                lines.append(f"  - {route.get('skill_id')}")
    else:
        lines.append("  - none")

    lines.extend(["", "Next:"])
    for action in next_actions or [f'cambrian do "{user_request}"']:
        lines.append(f"  {action}" if str(action).startswith("cambrian ") else f"  - {action}")
    return "\n".join(lines)
