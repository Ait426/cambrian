"""Cambrian 스킬 벤치마크 러너."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from engine.executor import SkillExecutor
from engine.loader import SkillLoader
from engine.models import BenchmarkEntry, BenchmarkReport

logger = logging.getLogger(__name__)


class SkillBenchmark:
    """Runs all candidates on the same input and ranks the results."""

    def __init__(self, loader: SkillLoader, executor: SkillExecutor) -> None:
        """Initializes the benchmark runner.

        Args:
            loader: Skill loader instance.
            executor: Skill executor instance.
        """
        self._loader = loader
        self._executor = executor

    def run(
        self,
        candidates: list[dict],
        input_data: dict,
        domain: str,
        tags: list[str],
    ) -> BenchmarkReport:
        """Executes all candidates and returns a ranked report.

        Args:
            candidates: Registry search results.
            input_data: Shared execution input.
            domain: Requested domain.
            tags: Requested tags.

        Returns:
            Benchmark report.
        """
        entries: list[BenchmarkEntry] = []

        for candidate in candidates:
            skill_path = str(candidate["skill_path"])
            skill_id = str(candidate["id"])
            fitness_score = float(candidate.get("fitness_score", 0.0))

            try:
                skill = self._loader.load(skill_path)
                result = self._executor.execute(skill, input_data)
                entry = BenchmarkEntry(
                    skill_id=skill_id,
                    success=result.success,
                    output=result.output,
                    error=result.error,
                    execution_time_ms=result.execution_time_ms,
                    fitness_score=fitness_score,
                    mode=result.mode,
                )
            except Exception as exc:  # pragma: no cover
                logger.exception("Benchmark candidate failed skill_id=%s", skill_id)
                entry = BenchmarkEntry(
                    skill_id=skill_id,
                    success=False,
                    output=None,
                    error=str(exc),
                    execution_time_ms=0,
                    fitness_score=fitness_score,
                    mode="unknown",
                )

            entries.append(entry)

        ranked_entries = self._rank(entries)
        best_skill_id = (
            ranked_entries[0].skill_id
            if ranked_entries and ranked_entries[0].success
            else None
        )
        return BenchmarkReport(
            entries=ranked_entries,
            best_skill_id=best_skill_id,
            total_candidates=len(candidates),
            successful_count=sum(1 for entry in ranked_entries if entry.success),
            domain=domain,
            tags=tags,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _rank(self, entries: list[BenchmarkEntry]) -> list[BenchmarkEntry]:
        """Sorts benchmark entries and assigns rank values.

        Args:
            entries: Unsorted benchmark entries.

        Returns:
            Sorted benchmark entries with rank populated.
        """
        ranked_entries = sorted(
            entries,
            key=lambda entry: (
                not entry.success,
                -entry.fitness_score,
                entry.execution_time_ms,
            ),
        )

        for index, entry in enumerate(ranked_entries, start=1):
            entry.rank = index

        return ranked_entries
