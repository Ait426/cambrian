"""프로젝트 기억을 patch intent 후보 추천에 반영하는 도우미."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from engine.project_memory import ProjectMemory, ProjectLesson, load_project_memory
from engine.project_memory_hygiene import default_memory_hygiene_path, hygiene_index, load_memory_hygiene
from engine.project_memory_overrides import default_memory_overrides_path
from engine.project_memory_router import _dedupe, _expand_tokens, _extract_test_paths, _extract_tokens


@dataclass
class MemoryOldTextHint:
    """old_text 후보에 붙는 기억 기반 힌트."""

    candidate_id: str
    lesson_id: str
    lesson_text: str
    effect: str
    delta: float
    reason: str
    pinned: bool
    hygiene_status: str | None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class PatchIntentMemoryGuidance:
    """patch intent 단계에서 사용하는 기억 가이드."""

    enabled: bool
    lessons_path: str | None
    overrides_path: str | None
    hygiene_path: str | None
    remembered: list[dict]
    old_text_hints: list[MemoryOldTextHint]
    suggested_tests: list[str]
    warnings: list[str]
    next_actions: list[str]
    omitted: dict

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "enabled": self.enabled,
            "lessons_path": self.lessons_path,
            "overrides_path": self.overrides_path,
            "hygiene_path": self.hygiene_path,
            "remembered": list(self.remembered),
            "old_text_hints": [item.to_dict() for item in self.old_text_hints],
            "suggested_tests": list(self.suggested_tests),
            "warnings": list(self.warnings),
            "next_actions": list(self.next_actions),
            "omitted": dict(self.omitted),
        }


class MemoryPatchIntentAdvisor:
    """patch intent 후보에 기억 기반 힌트를 붙인다."""

    def build_guidance(
        self,
        user_request: str | None,
        target_path: str | None,
        related_tests: list[str],
        old_text_candidates: list[dict],
        project_root: Path,
        lessons_path: Path | None = None,
        overrides_path: Path | None = None,
        hygiene_path: Path | None = None,
    ) -> PatchIntentMemoryGuidance:
        """patch intent 단계용 memory guidance를 만든다."""
        root = Path(project_root).resolve()
        lessons_file = Path(lessons_path).resolve() if lessons_path is not None else root / ".cambrian" / "memory" / "lessons.yaml"
        overrides_file = Path(overrides_path).resolve() if overrides_path is not None else default_memory_overrides_path(root)
        hygiene_file = Path(hygiene_path).resolve() if hygiene_path is not None else default_memory_hygiene_path(root)

        if not lessons_file.exists():
            return PatchIntentMemoryGuidance(
                enabled=False,
                lessons_path=str(lessons_file),
                overrides_path=str(overrides_file),
                hygiene_path=str(hygiene_file),
                remembered=[],
                old_text_hints=[],
                suggested_tests=[],
                warnings=[],
                next_actions=[],
                omitted={
                    "suppressed_count": 0,
                    "stale_count": 0,
                    "conflicting_count": 0,
                    "orphaned_count": 0,
                },
            )

        memory = load_project_memory(root)
        if memory is None:
            return PatchIntentMemoryGuidance(
                enabled=False,
                lessons_path=str(lessons_file),
                overrides_path=str(overrides_file),
                hygiene_path=str(hygiene_file),
                remembered=[],
                old_text_hints=[],
                suggested_tests=[],
                warnings=["프로젝트 기억을 읽지 못했습니다."],
                next_actions=[],
                omitted={
                    "suppressed_count": 0,
                    "stale_count": 0,
                    "conflicting_count": 0,
                    "orphaned_count": 0,
                },
            )

        hygiene = load_memory_hygiene(root)
        hygiene_map = hygiene_index(hygiene) if hygiene is not None else {}
        relevant, omitted = self._select_relevant_lessons(
            memory=memory,
            hygiene_map=hygiene_map,
            user_request=user_request,
            target_path=target_path,
            related_tests=related_tests,
            old_text_candidates=old_text_candidates,
        )

        hints: list[MemoryOldTextHint] = []
        warnings: list[str] = []
        next_actions: list[str] = []
        suggested_tests: list[str] = []

        for lesson in relevant:
            lesson_reason = self._lesson_reason(lesson, target_path, related_tests)
            if lesson.kind == "test_practice":
                tests = _dedupe([*related_tests, *_extract_test_paths(lesson.text)])
                for test_path in tests:
                    if test_path:
                        suggested_tests.append(test_path)
                if tests:
                    next_actions.append(f"{tests[0]} 테스트를 함께 유지하세요.")
            elif lesson.kind in {"avoid_pattern", "risk_warning"}:
                warnings.append(lesson.text)
            elif lesson.kind == "missing_evidence":
                next_actions.append("이 패치를 제안하기 전에 부족한 근거를 먼저 확인하세요.")

            for candidate in old_text_candidates:
                candidate_id = str(candidate.get("id", ""))
                candidate_text = str(candidate.get("text", ""))
                match_score = self._candidate_match_score(
                    lesson=lesson,
                    target_path=target_path,
                    related_tests=related_tests,
                    candidate_text=candidate_text,
                )
                if match_score <= 0:
                    continue

                effect = "warn"
                delta = 0.0
                reason = lesson_reason

                if lesson.kind == "successful_pattern":
                    effect = "boost"
                    delta = 0.10 + (0.05 if lesson.pinned else 0.0)
                    reason = "비슷한 성공 패턴이 프로젝트 기억에 남아 있습니다."
                elif lesson.kind == "adoption_reason":
                    effect = "boost"
                    delta = 0.05 + (0.05 if lesson.pinned else 0.0)
                    reason = "이전 채택 이유와 비슷한 수정 맥락입니다."
                elif lesson.kind == "avoid_pattern":
                    effect = "warn"
                    delta = -0.05
                    reason = "비슷한 접근이 예전에 위험했습니다. 작은 수정으로 유지하는 편이 안전합니다."
                elif lesson.kind == "risk_warning":
                    effect = "warn"
                    delta = 0.0
                    reason = "비슷한 변경에서 위험 신호가 기록돼 있습니다."
                elif lesson.kind == "test_practice":
                    effect = "warn"
                    delta = 0.0
                    reason = "이 유형의 수정에서는 관련 테스트를 함께 확인해야 했습니다."
                elif lesson.kind == "missing_evidence":
                    effect = "warn"
                    delta = 0.0
                    reason = "이전에는 근거 부족으로 판단이 흔들렸습니다."

                hints.append(
                    MemoryOldTextHint(
                        candidate_id=candidate_id,
                        lesson_id=lesson.lesson_id,
                        lesson_text=lesson.text,
                        effect=effect,
                        delta=delta,
                        reason=reason,
                        pinned=lesson.pinned,
                        hygiene_status="fresh",
                    )
                )

        remembered = [
            {
                "lesson_id": lesson.lesson_id,
                "text": lesson.text,
                "kind": lesson.kind,
                "pinned": lesson.pinned,
                "hygiene_status": "fresh",
                "reason": self._lesson_reason(lesson, target_path, related_tests),
            }
            for lesson in relevant[:3]
        ]
        return PatchIntentMemoryGuidance(
            enabled=True,
            lessons_path=str(lessons_file),
            overrides_path=str(overrides_file),
            hygiene_path=str(hygiene_file),
            remembered=remembered,
            old_text_hints=hints,
            suggested_tests=_dedupe(suggested_tests),
            warnings=_dedupe(warnings),
            next_actions=_dedupe(next_actions),
            omitted=omitted,
        )

    def apply_to_old_text_candidates(
        self,
        candidates: list[dict],
        guidance: PatchIntentMemoryGuidance,
    ) -> list[dict]:
        """old_text 후보에 기억 기반 점수와 설명을 덧붙인다."""
        hints_by_candidate: dict[str, list[MemoryOldTextHint]] = {}
        for hint in guidance.old_text_hints:
            hints_by_candidate.setdefault(hint.candidate_id, []).append(hint)

        updated: list[dict] = []
        for candidate in candidates:
            payload = dict(candidate)
            candidate_id = str(payload.get("id", ""))
            hints = hints_by_candidate.get(candidate_id, [])
            memory_reasons: list[str] = []
            memory_warnings: list[str] = []
            confidence = float(payload.get("confidence", 0.0) or 0.0)
            boosted = False
            for hint in hints:
                if hint.effect == "boost":
                    confidence = min(1.0, confidence + hint.delta)
                    boosted = True
                    memory_reasons.append(hint.reason)
                elif hint.effect == "warn":
                    memory_warnings.append(hint.reason)
            payload["confidence"] = round(confidence, 4)
            payload["memory_boosted"] = boosted
            payload["memory_reasons"] = _dedupe(memory_reasons)
            payload["memory_warnings"] = _dedupe(memory_warnings)
            updated.append(payload)

        updated.sort(
            key=lambda item: (
                0 if item.get("memory_boosted") else 1,
                -float(item.get("confidence", 0.0) or 0.0),
                str(item.get("id", "")),
            )
        )
        return updated

    def _select_relevant_lessons(
        self,
        *,
        memory: ProjectMemory,
        hygiene_map: dict[str, object],
        user_request: str | None,
        target_path: str | None,
        related_tests: list[str],
        old_text_candidates: list[dict],
    ) -> tuple[list[ProjectLesson], dict]:
        request_tokens = set(_expand_tokens(_extract_tokens(user_request or "")))
        target_tokens = set(_expand_tokens(_extract_tokens(target_path or "")))
        test_tokens = set()
        for item in related_tests:
            test_tokens.update(_expand_tokens(_extract_tokens(item)))
        candidate_tokens = set()
        for candidate in old_text_candidates:
            candidate_tokens.update(_expand_tokens(_extract_tokens(str(candidate.get("text", "")))))

        relevant: list[tuple[float, ProjectLesson]] = []
        omitted = {
            "suppressed_count": 0,
            "stale_count": 0,
            "conflicting_count": 0,
            "orphaned_count": 0,
        }

        for lesson in memory.lessons:
            hygiene_item = hygiene_map.get(lesson.lesson_id)
            hygiene_status = getattr(hygiene_item, "status", None)
            if lesson.suppressed or hygiene_status == "suppressed":
                omitted["suppressed_count"] += 1
                continue
            if hygiene_status in {"stale", "conflicting", "orphaned"}:
                omitted[f"{hygiene_status}_count"] += 1
                continue
            if hygiene_status == "watch":
                continue

            lesson_tokens = set(_expand_tokens(_extract_tokens(lesson.text)))
            tag_tokens = set(_expand_tokens([str(tag) for tag in lesson.tags]))
            matched = (
                request_tokens & lesson_tokens
                or request_tokens & tag_tokens
                or target_tokens & lesson_tokens
                or target_tokens & tag_tokens
                or test_tokens & lesson_tokens
                or test_tokens & tag_tokens
                or candidate_tokens & lesson_tokens
            )
            if not matched:
                extracted_tests = set(_extract_test_paths(lesson.text))
                if extracted_tests.intersection(set(related_tests)):
                    matched = extracted_tests
            if not matched:
                continue

            score = len(matched) * 0.2 + float(lesson.confidence) * 0.3 + (0.05 if lesson.pinned else 0.0)
            relevant.append((score, lesson))

        relevant.sort(
            key=lambda item: (
                0 if item[1].pinned else 1,
                -item[0],
                -item[1].confidence,
                item[1].lesson_id,
            )
        )
        return [item[1] for item in relevant[:5]], omitted

    def _candidate_match_score(
        self,
        *,
        lesson: ProjectLesson,
        target_path: str | None,
        related_tests: list[str],
        candidate_text: str,
    ) -> float:
        lesson_tokens = set(_expand_tokens(_extract_tokens(lesson.text)))
        lesson_tags = set(_expand_tokens([str(tag) for tag in lesson.tags]))
        candidate_tokens = set(_expand_tokens(_extract_tokens(candidate_text)))
        target_tokens = set(_expand_tokens(_extract_tokens(target_path or "")))
        test_tokens = set()
        for item in related_tests:
            test_tokens.update(_expand_tokens(_extract_tokens(item)))

        score = 0.0
        if candidate_tokens & lesson_tokens:
            score += 0.4
        if candidate_tokens & lesson_tags:
            score += 0.2
        if target_tokens & lesson_tokens or target_tokens & lesson_tags:
            score += 0.2
        if test_tokens & lesson_tokens or test_tokens & lesson_tags:
            score += 0.2
        return score

    def _lesson_reason(
        self,
        lesson: ProjectLesson,
        target_path: str | None,
        related_tests: list[str],
    ) -> str:
        if lesson.kind == "test_practice":
            tests = _dedupe([*related_tests, *_extract_test_paths(lesson.text)])
            if tests:
                return f"프로젝트 기억상 {tests[0]} 테스트를 함께 보는 편이 안전했습니다."
            return "프로젝트 기억상 관련 테스트를 함께 확인하는 편이 안전했습니다."
        if lesson.kind == "successful_pattern":
            return "비슷한 수정이 이전에 성공적으로 채택된 패턴과 가깝습니다."
        if lesson.kind == "avoid_pattern":
            return "비슷한 접근이 예전에 위험했던 기록이 있습니다."
        if lesson.kind == "risk_warning":
            return "비슷한 변경에서 위험 신호가 남아 있습니다."
        if lesson.kind == "missing_evidence":
            return "이전에는 근거 부족이 반복됐습니다."
        if lesson.kind == "adoption_reason":
            return f"{target_path or '현재 대상'}에서 이전 채택 이유와 겹치는 맥락이 있습니다."
        return lesson.text
