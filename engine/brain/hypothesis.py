"""Cambrian Harness Brain 가설 평가기.

Task 31에서는 사람이 제공한 hypothesis를 brain report와 대조해
supported / contradicted / inconclusive / skipped / error로 평가한다.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HypothesisCheck:
    """개별 가설 체크 결과."""

    name: str
    status: str
    expected: Any
    observed: Any
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HypothesisEvaluation:
    """가설 전체 평가 결과."""

    enabled: bool
    hypothesis_id: str | None
    statement: str | None
    status: str
    checks: list[HypothesisCheck] = field(default_factory=list)
    reason: str = ""
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["checks"] = [check.to_dict() for check in self.checks]
        return data


class HypothesisEvaluator:
    """rule-based hypothesis evaluator."""

    def evaluate(
        self,
        hypothesis: dict | None,
        report: dict,
    ) -> HypothesisEvaluation:
        """가설과 report를 비교해 평가한다."""
        if not hypothesis:
            return HypothesisEvaluation(
                enabled=False,
                hypothesis_id=None,
                statement=None,
                status="skipped",
                checks=[],
                reason="no hypothesis provided",
                next_actions=[],
            )

        try:
            if not isinstance(hypothesis, dict):
                raise ValueError("hypothesis must be a dict")

            predicts = hypothesis.get("predicts")
            if not isinstance(predicts, dict) or not predicts:
                raise ValueError("hypothesis.predicts must be a non-empty dict")

            checks: list[HypothesisCheck] = []
            checks.extend(self._evaluate_tests(predicts.get("tests"), report))
            checks.extend(self._evaluate_files(predicts.get("files"), report))
            checks.extend(
                self._evaluate_core_bridge(predicts.get("core_bridge"), report)
            )

            if not checks:
                raise ValueError("hypothesis.predicts has no supported sections")

            failed_count = sum(1 for check in checks if check.status == "failed")
            inconclusive_count = sum(
                1 for check in checks if check.status == "inconclusive"
            )

            if failed_count > 0:
                return HypothesisEvaluation(
                    enabled=True,
                    hypothesis_id=self._string_or_none(hypothesis.get("id")),
                    statement=self._string_or_none(hypothesis.get("statement")),
                    status="contradicted",
                    checks=checks,
                    reason=f"{failed_count} hypothesis check failed",
                    next_actions=[
                        "Hypothesis contradicted: inspect failed checks",
                        "Use failed checks as input for next generation",
                    ],
                )

            if inconclusive_count > 0:
                return HypothesisEvaluation(
                    enabled=True,
                    hypothesis_id=self._string_or_none(hypothesis.get("id")),
                    statement=self._string_or_none(hypothesis.get("statement")),
                    status="inconclusive",
                    checks=checks,
                    reason=(
                        f"{inconclusive_count} hypothesis check lacked sufficient evidence"
                    ),
                    next_actions=[
                        "Hypothesis inconclusive: collect missing evidence",
                        "Ensure tests/core_bridge/report evidence is available",
                    ],
                )

            return HypothesisEvaluation(
                enabled=True,
                hypothesis_id=self._string_or_none(hypothesis.get("id")),
                statement=self._string_or_none(hypothesis.get("statement")),
                status="supported",
                checks=checks,
                reason="all hypothesis checks passed",
                next_actions=[],
            )

        except Exception as exc:
            logger.exception("hypothesis evaluation failed")
            return HypothesisEvaluation(
                enabled=True,
                hypothesis_id=self._string_or_none(
                    hypothesis.get("id") if isinstance(hypothesis, dict) else None
                ),
                statement=self._string_or_none(
                    hypothesis.get("statement")
                    if isinstance(hypothesis, dict)
                    else None
                ),
                status="error",
                checks=[],
                reason=str(exc),
                next_actions=[
                    "Fix hypothesis schema before next run",
                ],
            )

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    def _evaluate_tests(
        self,
        tests_predicts: dict | None,
        report: dict,
    ) -> list[HypothesisCheck]:
        if tests_predicts is None:
            return []
        if not isinstance(tests_predicts, dict):
            raise ValueError("hypothesis.predicts.tests must be a dict")

        test_results = report.get("test_results")
        checks: list[HypothesisCheck] = []
        checks.extend(
            self._threshold_check(
                section="tests",
                field_name="passed_min",
                expected=tests_predicts.get("passed_min"),
                observed_source=test_results,
                observed_key="passed",
                comparator="min",
            )
        )
        checks.extend(
            self._threshold_check(
                section="tests",
                field_name="failed_max",
                expected=tests_predicts.get("failed_max"),
                observed_source=test_results,
                observed_key="failed",
                comparator="max",
            )
        )
        checks.extend(
            self._threshold_check(
                section="tests",
                field_name="skipped_max",
                expected=tests_predicts.get("skipped_max"),
                observed_source=test_results,
                observed_key="skipped",
                comparator="max",
            )
        )
        return checks

    def _evaluate_files(
        self,
        files_predicts: dict | None,
        report: dict,
    ) -> list[HypothesisCheck]:
        if files_predicts is None:
            return []
        if not isinstance(files_predicts, dict):
            raise ValueError("hypothesis.predicts.files must be a dict")

        created_files, modified_files = self._extract_file_evidence(report)
        checks: list[HypothesisCheck] = []

        checks.extend(
            self._contains_checks(
                name_prefix="files.created_contains",
                expected_paths=files_predicts.get("created_contains"),
                observed_paths=created_files,
            )
        )
        checks.extend(
            self._contains_checks(
                name_prefix="files.modified_contains",
                expected_paths=files_predicts.get("modified_contains"),
                observed_paths=modified_files,
            )
        )
        return checks

    def _evaluate_core_bridge(
        self,
        bridge_predicts: dict | None,
        report: dict,
    ) -> list[HypothesisCheck]:
        if bridge_predicts is None:
            return []
        if not isinstance(bridge_predicts, dict):
            raise ValueError("hypothesis.predicts.core_bridge must be a dict")

        summary = self._extract_core_bridge_summary(report)
        checks: list[HypothesisCheck] = []
        checks.extend(
            self._equality_check(
                name="core_bridge.baseline_decision",
                expected=bridge_predicts.get("baseline_decision"),
                observed_source=summary,
                observed_key="baseline_decision",
            )
        )
        checks.extend(
            self._equality_check(
                name="core_bridge.recommend_promote",
                expected=bridge_predicts.get("recommend_promote"),
                observed_source=summary,
                observed_key="recommend_promote",
            )
        )

        champion_expected = None
        champion_name = None
        if "champion_profile" in bridge_predicts:
            champion_expected = bridge_predicts.get("champion_profile")
            champion_name = "core_bridge.champion_profile"
        elif "champion_policy" in bridge_predicts:
            champion_expected = bridge_predicts.get("champion_policy")
            champion_name = "core_bridge.champion_policy"

        if champion_name is not None:
            checks.extend(
                self._equality_check(
                    name=champion_name,
                    expected=champion_expected,
                    observed_source=summary,
                    observed_key="champion_policy",
                )
            )
        return checks

    def _threshold_check(
        self,
        section: str,
        field_name: str,
        expected: Any,
        observed_source: Any,
        observed_key: str,
        comparator: str,
    ) -> list[HypothesisCheck]:
        if expected is None:
            return []

        if not isinstance(expected, (int, float)):
            raise ValueError(f"{section}.{field_name} must be numeric")

        if not isinstance(observed_source, dict):
            return [
                HypothesisCheck(
                    name=f"{section}.{field_name}",
                    status="inconclusive",
                    expected=expected,
                    observed=None,
                    reason=f"{section} evidence is unavailable",
                ),
            ]

        observed = observed_source.get(observed_key)
        if not isinstance(observed, (int, float)):
            return [
                HypothesisCheck(
                    name=f"{section}.{field_name}",
                    status="inconclusive",
                    expected=expected,
                    observed=observed,
                    reason=f"{section}.{observed_key} evidence is unavailable",
                ),
            ]

        if comparator == "min":
            if observed >= expected:
                return [
                    HypothesisCheck(
                        name=f"{section}.{field_name}",
                        status="passed",
                        expected=expected,
                        observed=observed,
                        reason=(
                            f"observed {observed_key}={observed} >= "
                            f"expected minimum={expected}"
                        ),
                    ),
                ]
            return [
                HypothesisCheck(
                    name=f"{section}.{field_name}",
                    status="failed",
                    expected=expected,
                    observed=observed,
                    reason=(
                        f"observed {observed_key}={observed} < "
                        f"expected minimum={expected}"
                    ),
                ),
            ]

        if observed <= expected:
            return [
                HypothesisCheck(
                    name=f"{section}.{field_name}",
                    status="passed",
                    expected=expected,
                    observed=observed,
                    reason=(
                        f"observed {observed_key}={observed} <= "
                        f"expected maximum={expected}"
                    ),
                ),
            ]
        return [
            HypothesisCheck(
                name=f"{section}.{field_name}",
                status="failed",
                expected=expected,
                observed=observed,
                reason=(
                    f"observed {observed_key}={observed} > "
                    f"expected maximum={expected}"
                ),
            ),
        ]

    def _contains_checks(
        self,
        name_prefix: str,
        expected_paths: Any,
        observed_paths: list[str] | None,
    ) -> list[HypothesisCheck]:
        if expected_paths is None:
            return []
        if not isinstance(expected_paths, list):
            raise ValueError(f"{name_prefix} must be a list")

        checks: list[HypothesisCheck] = []
        for expected_path in expected_paths:
            if observed_paths is None:
                checks.append(
                    HypothesisCheck(
                        name=f"{name_prefix}:{expected_path}",
                        status="inconclusive",
                        expected=expected_path,
                        observed=None,
                        reason=f"{name_prefix} evidence is unavailable",
                    )
                )
                continue

            if expected_path in observed_paths:
                checks.append(
                    HypothesisCheck(
                        name=f"{name_prefix}:{expected_path}",
                        status="passed",
                        expected=expected_path,
                        observed=list(observed_paths),
                        reason=f"observed evidence contains {expected_path}",
                    )
                )
            else:
                checks.append(
                    HypothesisCheck(
                        name=f"{name_prefix}:{expected_path}",
                        status="failed",
                        expected=expected_path,
                        observed=list(observed_paths),
                        reason=f"observed evidence does not contain {expected_path}",
                    )
                )
        return checks

    def _equality_check(
        self,
        name: str,
        expected: Any,
        observed_source: Any,
        observed_key: str,
    ) -> list[HypothesisCheck]:
        if expected is None:
            return []

        if not isinstance(observed_source, dict):
            return [
                HypothesisCheck(
                    name=name,
                    status="inconclusive",
                    expected=expected,
                    observed=None,
                    reason="core_bridge summary is unavailable",
                ),
            ]

        observed = observed_source.get(observed_key)
        if observed is None:
            return [
                HypothesisCheck(
                    name=name,
                    status="inconclusive",
                    expected=expected,
                    observed=None,
                    reason=f"core_bridge.{observed_key} evidence is unavailable",
                ),
            ]

        if observed == expected:
            return [
                HypothesisCheck(
                    name=name,
                    status="passed",
                    expected=expected,
                    observed=observed,
                    reason=f"observed {observed_key} matches expected value",
                ),
            ]
        return [
            HypothesisCheck(
                name=name,
                status="failed",
                expected=expected,
                observed=observed,
                reason=f"observed {observed_key} does not match expected value",
            ),
        ]

    def _extract_file_evidence(
        self,
        report: dict,
    ) -> tuple[list[str] | None, list[str] | None]:
        provenance = report.get("provenance_handoff")
        if isinstance(provenance, dict):
            created = provenance.get("files_created")
            modified = provenance.get("files_modified")
            if isinstance(created, list) or isinstance(modified, list):
                return (
                    list(created) if isinstance(created, list) else None,
                    list(modified) if isinstance(modified, list) else None,
                )

        created_fallback = report.get("files_created")
        modified_fallback = report.get("files_modified")
        if isinstance(created_fallback, list) or isinstance(modified_fallback, list):
            return (
                list(created_fallback) if isinstance(created_fallback, list) else None,
                list(modified_fallback)
                if isinstance(modified_fallback, list)
                else None,
            )

        return None, None

    def _extract_core_bridge_summary(self, report: dict) -> dict | None:
        bridge = report.get("core_bridge")
        if not isinstance(bridge, dict):
            return None

        direct_keys = {"baseline_decision", "recommend_promote", "champion_policy"}
        if any(key in bridge for key in direct_keys):
            return bridge

        artifacts = bridge.get("artifacts")
        if not isinstance(artifacts, list):
            return None

        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            summary = artifact.get("summary")
            if not isinstance(summary, dict):
                continue
            if any(key in summary for key in direct_keys):
                return summary
        return None
