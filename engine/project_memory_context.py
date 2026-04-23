"""Cambrian 프로젝트 기억을 context/clarification 추천에 반영하는 도우미."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.project_memory import default_memory_path, load_project_memory
from engine.project_memory_hygiene import default_memory_hygiene_path, hygiene_index, load_memory_hygiene
from engine.project_memory_overrides import default_memory_overrides_path
from engine.project_memory_router import _expand_tokens, _extract_tokens

logger = logging.getLogger(__name__)


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


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _extract_file_paths(text: str) -> list[str]:
    """lesson 문장 안에서 파일 경로 후보를 추출한다."""
    return _dedupe(
        re.findall(
            r"((?:tests|src|docs|config|configs)/[A-Za-z0-9_./-]+\.(?:py|ts|tsx|js|jsx|md|ya?ml|json|toml))",
            str(text or ""),
        )
    )


def _candidate_tokens(path: str) -> set[str]:
    """후보 경로에서 비교용 토큰을 추출한다."""
    lowered = str(path or "").replace("\\", "/").lower()
    tokens = set(_expand_tokens(_extract_tokens(lowered)))
    parts = [part for part in lowered.split("/") if part]
    tokens.update(parts)
    stem = Path(lowered).stem
    if stem:
        tokens.add(stem)
        tokens.add(stem.replace("test_", ""))
    return {token for token in tokens if token}


def _match_path(candidate_path: str, referenced_paths: list[str]) -> bool:
    """후보 경로와 lesson이 가리키는 경로가 비슷한지 확인한다."""
    normalized = str(candidate_path or "").replace("\\", "/").lower()
    base_name = Path(normalized).name
    for ref in referenced_paths:
        ref_normalized = str(ref or "").replace("\\", "/").lower()
        if not ref_normalized:
            continue
        if normalized == ref_normalized:
            return True
        if base_name and base_name == Path(ref_normalized).name:
            return True
        if ref_normalized in normalized or normalized in ref_normalized:
            return True
    return False


@dataclass
class MemoryCandidateHint:
    """개별 context 후보에 대한 memory 힌트."""

    candidate_path: str
    candidate_kind: str
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
class MemoryContextGuidance:
    """context scan에 붙일 memory guidance."""

    enabled: bool
    lessons_path: str | None
    overrides_path: str | None
    hygiene_path: str | None
    relevant_lessons: list[dict] = field(default_factory=list)
    candidate_hints: list[MemoryCandidateHint] = field(default_factory=list)
    suggested_tests: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    omitted: dict = field(default_factory=dict)
    reason: str | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "enabled": self.enabled,
            "lessons_path": self.lessons_path,
            "overrides_path": self.overrides_path,
            "hygiene_path": self.hygiene_path,
            "relevant_lessons": list(self.relevant_lessons),
            "candidate_hints": [item.to_dict() for item in self.candidate_hints],
            "suggested_tests": list(self.suggested_tests),
            "warnings": list(self.warnings),
            "next_actions": list(self.next_actions),
            "omitted": dict(self.omitted),
            "reason": self.reason,
            "remembered": [
                str(item.get("text"))
                for item in self.relevant_lessons
                if isinstance(item, dict) and item.get("text")
            ][:3],
        }


class MemoryContextAdvisor:
    """프로젝트 기억을 바탕으로 context 후보를 보강한다."""

    def build_guidance(
        self,
        user_request: str,
        context_scan_result: dict,
        project_root: Path,
        lessons_path: Path | None = None,
        overrides_path: Path | None = None,
        hygiene_path: Path | None = None,
    ) -> MemoryContextGuidance:
        """context 후보와 관련된 project memory guidance를 만든다."""
        root = Path(project_root).resolve()
        lessons_file = Path(lessons_path).resolve() if lessons_path is not None else default_memory_path(root)
        overrides_file = Path(overrides_path).resolve() if overrides_path is not None else default_memory_overrides_path(root)
        hygiene_file = Path(hygiene_path).resolve() if hygiene_path is not None else default_memory_hygiene_path(root)
        memory = load_project_memory(root)
        if memory is None:
            return MemoryContextGuidance(
                enabled=False,
                lessons_path=_relative(lessons_file, root),
                overrides_path=_relative(overrides_file, root),
                hygiene_path=_relative(hygiene_file, root),
                reason="no lessons.yaml found",
            )

        hygiene_report = load_memory_hygiene(root)
        hygiene_map = hygiene_index(hygiene_report) if hygiene_report is not None else {}
        request_tokens = set(_expand_tokens(_extract_tokens(user_request)))
        if not request_tokens:
            return MemoryContextGuidance(
                enabled=True,
                lessons_path=_relative(lessons_file, root),
                overrides_path=_relative(overrides_file, root),
                hygiene_path=_relative(hygiene_file, root),
                reason="request tokens were empty",
                omitted={
                    "suppressed_count": len([item for item in memory.lessons if item.suppressed]),
                    "stale_count": 0,
                    "conflicting_count": 0,
                    "orphaned_count": 0,
                },
            )

        source_candidates = [
            item for item in list(context_scan_result.get("suggested_sources", []))
            if isinstance(item, dict)
        ]
        test_candidates = [
            item for item in list(context_scan_result.get("suggested_tests", []))
            if isinstance(item, dict)
        ]
        candidate_tokens = {
            str(item.get("path", "")): _candidate_tokens(str(item.get("path", "")))
            for item in [*source_candidates, *test_candidates]
            if item.get("path")
        }

        relevant_lessons: list[dict] = []
        candidate_hints: list[MemoryCandidateHint] = []
        warnings: list[str] = []
        next_actions: list[str] = []
        suggested_tests: list[str] = []
        omitted = {
            "suppressed_count": 0,
            "stale_count": 0,
            "conflicting_count": 0,
            "orphaned_count": 0,
        }

        ranked_lessons: list[tuple[float, dict]] = []
        for lesson in memory.lessons:
            if lesson.suppressed:
                omitted["suppressed_count"] += 1
                continue

            hygiene_item = hygiene_map.get(lesson.lesson_id)
            hygiene_status = hygiene_item.status if hygiene_item is not None else None
            if hygiene_status in {"stale", "conflicting", "orphaned"}:
                omitted[f"{hygiene_status}_count"] += 1
                continue

            lesson_tokens = set(_expand_tokens(list(lesson.tags) + _extract_tokens(lesson.text)))
            request_matches = sorted(request_tokens & lesson_tokens)
            referenced_paths = _extract_file_paths(lesson.text)
            candidate_matches: list[str] = []
            for path, tokens in candidate_tokens.items():
                if request_matches and (tokens & lesson_tokens or _match_path(path, referenced_paths)):
                    candidate_matches.append(path)

            if not request_matches and not candidate_matches:
                continue

            score = 0.0
            if request_matches:
                score += 0.30
            if candidate_matches:
                score += 0.25
            score += min(float(lesson.confidence) * 0.20, 0.20)
            if lesson.pinned:
                score += 0.05
            if score < 0.25:
                continue

            reason_parts: list[str] = []
            if request_matches:
                reason_parts.append(f"matched request term: {request_matches[0]}")
            if candidate_matches:
                reason_parts.append(f"matched candidate: {candidate_matches[0]}")
            if hygiene_status == "watch":
                reason_parts.append("review recommended")

            ranked_lessons.append(
                (
                    score,
                    {
                        "lesson_id": lesson.lesson_id,
                        "text": lesson.text,
                        "kind": lesson.kind,
                        "pinned": lesson.pinned,
                        "suppressed": lesson.suppressed,
                        "human_note": lesson.human_note,
                        "hygiene_status": hygiene_status or "fresh",
                        "reason": "; ".join(reason_parts) or "matched project memory",
                        "tags": list(lesson.tags),
                        "source_refs": list(lesson.source_refs),
                    },
                )
            )

        ranked_lessons.sort(
            key=lambda item: (
                0 if item[1].get("pinned") else 1,
                -item[0],
                item[1].get("lesson_id", ""),
            )
        )
        relevant_lessons = [item[1] for item in ranked_lessons[:5]]

        for lesson in relevant_lessons:
            lesson_id = str(lesson.get("lesson_id", ""))
            lesson_text = str(lesson.get("text", ""))
            lesson_kind = str(lesson.get("kind", ""))
            lesson_tokens = set(_expand_tokens(list(lesson.get("tags", [])) + _extract_tokens(lesson_text)))
            referenced_paths = _extract_file_paths(lesson_text)
            hygiene_status = str(lesson.get("hygiene_status", "fresh"))
            is_pinned = bool(lesson.get("pinned", False))

            if hygiene_status == "watch":
                warnings.append(f"기억 검토 필요: {lesson_text}")

            if lesson_kind == "test_practice":
                matched_test = False
                for candidate in test_candidates:
                    candidate_path = str(candidate.get("path", ""))
                    if not candidate_path:
                        continue
                    if _match_path(candidate_path, referenced_paths) or candidate_tokens.get(candidate_path, set()) & lesson_tokens:
                        delta = 0.25 + (0.05 if is_pinned and hygiene_status == "fresh" else 0.0)
                        candidate_hints.append(
                            MemoryCandidateHint(
                                candidate_path=candidate_path,
                                candidate_kind="test",
                                lesson_id=lesson_id,
                                lesson_text=lesson_text,
                                effect="boost",
                                delta=round(delta, 2),
                                reason="project memory recommends this test for related changes",
                                pinned=is_pinned,
                                hygiene_status=hygiene_status,
                            )
                        )
                        matched_test = True
                if not matched_test:
                    for test_path in referenced_paths:
                        if test_path.startswith("tests/"):
                            suggested_tests.append(test_path)
                            next_actions.append(f"Use --test {test_path} for related work.")

            elif lesson_kind == "successful_pattern":
                for candidate in source_candidates:
                    candidate_path = str(candidate.get("path", ""))
                    if not candidate_path:
                        continue
                    if _match_path(candidate_path, referenced_paths) or candidate_tokens.get(candidate_path, set()) & lesson_tokens:
                        delta = 0.10 + (0.05 if is_pinned and hygiene_status == "fresh" else 0.0)
                        candidate_hints.append(
                            MemoryCandidateHint(
                                candidate_path=candidate_path,
                                candidate_kind="source",
                                lesson_id=lesson_id,
                                lesson_text=lesson_text,
                                effect="boost",
                                delta=round(delta, 2),
                                reason="similar successful pattern was remembered",
                                pinned=is_pinned,
                                hygiene_status=hygiene_status,
                            )
                        )

            elif lesson_kind == "avoid_pattern":
                for candidate in source_candidates:
                    candidate_path = str(candidate.get("path", ""))
                    if not candidate_path:
                        continue
                    if _match_path(candidate_path, referenced_paths) or candidate_tokens.get(candidate_path, set()) & lesson_tokens:
                        candidate_hints.append(
                            MemoryCandidateHint(
                                candidate_path=candidate_path,
                                candidate_kind="source",
                                lesson_id=lesson_id,
                                lesson_text=lesson_text,
                                effect="warn",
                                delta=0.0,
                                reason="previous similar approach was risky",
                                pinned=is_pinned,
                                hygiene_status=hygiene_status,
                            )
                        )
                        warnings.append(lesson_text)

            elif lesson_kind == "risk_warning":
                warnings.append(lesson_text)

            elif lesson_kind == "missing_evidence":
                next_actions.append("Collect missing evidence before patching.")

        return MemoryContextGuidance(
            enabled=True,
            lessons_path=_relative(lessons_file, root),
            overrides_path=_relative(overrides_file, root),
            hygiene_path=_relative(hygiene_file, root),
            relevant_lessons=relevant_lessons,
            candidate_hints=candidate_hints,
            suggested_tests=_dedupe(suggested_tests),
            warnings=_dedupe(warnings)[:5],
            next_actions=_dedupe(next_actions)[:5],
            omitted=omitted,
        )

    def apply_to_context_candidates(
        self,
        context_scan_result: dict,
        guidance: MemoryContextGuidance,
    ) -> dict:
        """context candidate dict에 memory guidance를 반영한다."""
        payload = dict(context_scan_result)
        sources = [
            dict(item) for item in list(payload.get("suggested_sources", []))
            if isinstance(item, dict)
        ]
        tests = [
            dict(item) for item in list(payload.get("suggested_tests", []))
            if isinstance(item, dict)
        ]
        candidate_map = {
            ("source", str(item.get("path", ""))): item
            for item in sources
            if item.get("path")
        }
        candidate_map.update(
            {
                ("test", str(item.get("path", ""))): item
                for item in tests
                if item.get("path")
            }
        )

        for hint in guidance.candidate_hints:
            key = (hint.candidate_kind, hint.candidate_path)
            candidate = candidate_map.get(key)
            if candidate is None:
                continue
            reasons = list(candidate.get("reasons", []))
            lesson_ids = list(candidate.get("memory_lesson_ids", []))
            if hint.effect == "boost":
                current = float(candidate.get("score", 0.0) or 0.0)
                candidate["score"] = round(min(current + hint.delta, 1.0), 2)
                candidate["memory_boosted"] = True
            elif hint.effect == "warn":
                candidate["memory_warning"] = True
            reasons.append(f"boosted by project memory: {hint.reason}" if hint.effect == "boost" else f"project memory warning: {hint.reason}")
            candidate["reasons"] = _dedupe(reasons)
            candidate["why"] = "; ".join(candidate["reasons"])
            candidate["memory_lesson_ids"] = _dedupe([*lesson_ids, hint.lesson_id])

        sources.sort(key=lambda item: (-float(item.get("score", 0.0) or 0.0), str(item.get("path", ""))))
        tests.sort(key=lambda item: (-float(item.get("score", 0.0) or 0.0), str(item.get("path", ""))))
        payload["suggested_sources"] = sources
        payload["suggested_tests"] = tests
        payload["source_candidates"] = sources
        payload["test_candidates"] = tests
        payload["top_source"] = str(sources[0].get("path", "")) if sources else None
        payload["top_test"] = str(tests[0].get("path", "")) if tests else None
        payload["warnings"] = _dedupe([
            *[str(item) for item in payload.get("warnings", []) if item],
            *guidance.warnings,
        ])
        payload["next_actions"] = _dedupe([
            *guidance.next_actions,
            *[str(item) for item in payload.get("next_actions", []) if item],
        ])
        payload["memory_guidance"] = guidance.to_dict()
        return payload
