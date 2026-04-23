"""Seeded next generation용 feedback context 로더."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from engine.brain.models import TaskSpec


def _unique_strings(values: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalize_string_list(value: object) -> list[str]:
    """문자열 또는 리스트 입력을 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, str):
        return _unique_strings([value])
    if isinstance(value, list):
        return _unique_strings([str(item) for item in value])
    return _unique_strings([str(value)])


@dataclass
class FeedbackContext:
    """다음 brain run에 주입되는 seed 기반 문맥."""

    enabled: bool
    source_seed_path: str | None = None
    source_feedback_refs: list[str] = field(default_factory=list)
    previous_outcome: dict | None = None
    lessons_keep: list[str] = field(default_factory=list)
    lessons_avoid: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    suggested_next_actions: list[str] = field(default_factory=list)
    hypothesis_seed: dict | None = None
    competitive_seed: dict | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """report 저장용 dict."""
        return asdict(self)


class FeedbackContextLoader:
    """TaskSpec에 내장된 generation seed를 읽어 문맥으로 정규화한다."""

    def load_seed_file(self, path: Path) -> dict:
        """seed YAML 파일을 로드한다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise ValueError("generation seed YAML 최상위는 dict여야 한다")
        return dict(payload)

    def load_from_spec(
        self,
        spec: TaskSpec,
        project_root: Path,
    ) -> FeedbackContext:
        """TaskSpec에서 feedback context를 복원한다."""
        del project_root
        raw_seed = spec.generation_seed
        raw_feedback_refs = spec.feedback_refs

        if raw_seed is None and raw_feedback_refs is None:
            return FeedbackContext(enabled=False)

        warnings: list[str] = []
        errors: list[str] = []

        if raw_seed is None:
            seed = {}
        elif isinstance(raw_seed, dict):
            seed = dict(raw_seed)
        else:
            seed = {}
            errors.append(
                f"generation_seed must be a dict, got {type(raw_seed).__name__}"
            )

        feedback_refs = _normalize_string_list(raw_feedback_refs)
        source_feedback_ref = seed.get("source_feedback_ref")
        if source_feedback_ref is not None:
            feedback_refs = _unique_strings(
                feedback_refs + _normalize_string_list(source_feedback_ref)
            )

        source_seed_path = seed.get("source_seed_path") or seed.get("_source_seed_path")
        if source_seed_path is not None:
            source_seed_path = str(source_seed_path)

        previous_outcome = seed.get("previous_outcome")
        if previous_outcome is not None and not isinstance(previous_outcome, dict):
            warnings.append("generation_seed.previous_outcome must be a dict")
            previous_outcome = None
        elif isinstance(previous_outcome, dict):
            previous_outcome = dict(previous_outcome)

        lessons = seed.get("lessons")
        if lessons is None:
            lessons = {}
        elif not isinstance(lessons, dict):
            warnings.append("generation_seed.lessons must be a dict")
            lessons = {}

        suggested_next_actions = _normalize_string_list(
            seed.get("suggested_next_actions")
        )

        hypothesis_seed = seed.get("hypothesis_seed")
        if hypothesis_seed is not None and not isinstance(hypothesis_seed, dict):
            warnings.append("generation_seed.hypothesis_seed must be a dict")
            hypothesis_seed = None
        elif isinstance(hypothesis_seed, dict):
            hypothesis_seed = dict(hypothesis_seed)

        competitive_seed = seed.get("competitive_seed")
        if competitive_seed is not None and not isinstance(competitive_seed, dict):
            warnings.append("generation_seed.competitive_seed must be a dict")
            competitive_seed = None
        elif isinstance(competitive_seed, dict):
            competitive_seed = dict(competitive_seed)

        return FeedbackContext(
            enabled=True,
            source_seed_path=source_seed_path,
            source_feedback_refs=feedback_refs,
            previous_outcome=previous_outcome,
            lessons_keep=_normalize_string_list(lessons.get("keep")),
            lessons_avoid=_normalize_string_list(lessons.get("avoid")),
            missing_evidence=_normalize_string_list(
                lessons.get("missing_evidence")
            ),
            suggested_next_actions=suggested_next_actions,
            hypothesis_seed=hypothesis_seed,
            competitive_seed=competitive_seed,
            warnings=_unique_strings(warnings),
            errors=_unique_strings(errors),
        )
