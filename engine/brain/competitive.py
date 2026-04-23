"""Cambrian Harness Brain Competitive Generation V1."""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.brain.adapters.executor_v1 import ExecutorV1
from engine.brain.adapters.reviewer_v1 import ReviewerV1
from engine.brain.adapters.tester_v1 import TesterV1
from engine.brain.feedback_context import FeedbackContextLoader
from engine.brain.hypothesis import HypothesisEvaluator
from engine.brain.models import RunState, TaskSpec, WorkItem

logger = logging.getLogger(__name__)


VARIANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _unique(values: list[str]) -> list[str]:
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


@dataclass
class VariantResult:
    """개별 variant 실행 결과."""

    variant_id: str
    label: str | None
    description: str | None
    status: str
    workspace_path: str
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    tests_executed: list[str] = field(default_factory=list)
    test_exit_code: int = -1
    test_results: dict = field(default_factory=dict)
    reviewer_passed: bool | None = None
    reviewer_conclusion: str = ""
    hypothesis_status: str | None = None
    warnings: list[str] = field(default_factory=list)
    excluded_from_winner: bool = False
    constraint_reasons: list[str] = field(default_factory=list)
    pressure_excluded_from_winner: bool = False
    pressure_reasons: list[str] = field(default_factory=list)
    score_summary: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON 직렬화용 dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "VariantResult":
        """dict에서 VariantResult를 복원한다."""
        return cls(
            variant_id=str(data.get("variant_id", "")),
            label=str(data["label"]) if data.get("label") is not None else None,
            description=(
                str(data["description"])
                if data.get("description") is not None
                else None
            ),
            status=str(data.get("status", "error")),
            workspace_path=str(data.get("workspace_path", "")),
            files_created=list(data.get("files_created") or []),
            files_modified=list(data.get("files_modified") or []),
            tests_executed=list(data.get("tests_executed") or []),
            test_exit_code=int(data.get("test_exit_code", -1) or -1),
            test_results=dict(data.get("test_results") or {}),
            reviewer_passed=(
                bool(data["reviewer_passed"])
                if data.get("reviewer_passed") is not None
                else None
            ),
            reviewer_conclusion=str(data.get("reviewer_conclusion", "")),
            hypothesis_status=(
                str(data["hypothesis_status"])
                if data.get("hypothesis_status") is not None
                else None
            ),
            warnings=list(data.get("warnings") or []),
            excluded_from_winner=bool(data.get("excluded_from_winner", False)),
            constraint_reasons=list(data.get("constraint_reasons") or []),
            pressure_excluded_from_winner=bool(
                data.get("pressure_excluded_from_winner", False)
            ),
            pressure_reasons=list(data.get("pressure_reasons") or []),
            score_summary=dict(data.get("score_summary") or {}),
            errors=list(data.get("errors") or []),
        )


@dataclass
class CompetitiveGenerationResult:
    """competitive generation 전체 결과."""

    enabled: bool
    status: str
    variants: list[VariantResult] = field(default_factory=list)
    winner_variant_id: str | None = None
    selection_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON 직렬화용 dict."""
        return {
            "enabled": self.enabled,
            "status": self.status,
            "variants": [variant.to_dict() for variant in self.variants],
            "winner_variant_id": self.winner_variant_id,
            "selection_reason": self.selection_reason,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class CompetitiveGenerationRunner:
    """격리 workspace에서 variant를 순차 실행하고 winner를 선택한다."""

    DEFAULT_MAX_VARIANTS: int = 3
    HARD_MAX_VARIANTS: int = 5
    _IGNORED_NAMES: frozenset[str] = frozenset(
        {".git", ".cambrian", "__pycache__", ".pytest_cache"}
    )

    def __init__(self) -> None:
        """초기화."""
        self._hypothesis = HypothesisEvaluator()

    def run(
        self,
        spec: TaskSpec,
        run_dir: Path,
        project_root: Path,
        core_bridge: dict | None = None,
    ) -> CompetitiveGenerationResult:
        """competitive generation을 실행한다."""
        config = spec.competitive
        if not isinstance(config, dict) or not bool(config.get("enabled", False)):
            return CompetitiveGenerationResult(
                enabled=False,
                status="skipped",
                variants=[],
                winner_variant_id=None,
                selection_reason="competitive generation disabled",
                warnings=[],
                errors=[],
            )

        normalized, errors = self._normalize_config(config)
        if errors:
            return CompetitiveGenerationResult(
                enabled=True,
                status="failure",
                variants=[],
                winner_variant_id=None,
                selection_reason="competitive configuration invalid",
                warnings=[],
                errors=errors,
            )

        feedback_context = FeedbackContextLoader().load_from_spec(spec, project_root)
        refinement = (
            dict(spec.hypothesis_refinement)
            if isinstance(spec.hypothesis_refinement, dict)
            else {}
        )
        effective_hypothesis = self._resolve_effective_hypothesis(
            spec,
            feedback_context,
            refinement,
        )
        selection_pressure = (
            dict(spec.selection_pressure)
            if isinstance(spec.selection_pressure, dict)
            else {}
        )
        (
            constraint_map,
            warned_variant_ids,
            competitive_warnings,
        ) = self._resolve_run_constraints(
            normalized["variants"],
            feedback_context,
            selection_pressure,
            refinement,
        )

        variants_dir = run_dir / "variants"
        variants_dir.mkdir(parents=True, exist_ok=True)

        results: list[VariantResult] = []
        for variant in normalized["variants"]:
            result_path = variants_dir / variant["id"] / "result.json"
            existing = self._load_result(result_path)
            if existing is not None:
                existing.score_summary = dict(existing.score_summary)
                existing.score_summary["result_source"] = "reused"
                self._apply_winner_constraints(
                    existing,
                    constraint_map,
                    warned_variant_ids,
                )
                results.append(existing)
                continue

            result = self._run_variant(
                spec=spec,
                variant=variant,
                variants_dir=variants_dir,
                project_root=project_root.resolve(),
                copy_paths=normalized["copy_paths"],
                core_bridge=core_bridge,
                effective_hypothesis=effective_hypothesis,
                constraint_map=constraint_map,
                warned_variant_ids=warned_variant_ids,
            )
            self._save_result(result_path, result)
            results.append(result)

        status, winner_id, reason = self._select_winner(results)
        return CompetitiveGenerationResult(
            enabled=True,
            status=status,
            variants=results,
            winner_variant_id=winner_id,
            selection_reason=reason,
            warnings=competitive_warnings,
            errors=[],
        )

    def _normalize_config(self, config: dict) -> tuple[dict, list[str]]:
        """competitive config를 검증하고 정규화한다."""
        errors: list[str] = []

        max_variants = config.get("max_variants", self.DEFAULT_MAX_VARIANTS)
        if not isinstance(max_variants, int):
            errors.append("competitive.max_variants must be an integer")
            max_variants = self.DEFAULT_MAX_VARIANTS
        if isinstance(max_variants, int) and max_variants > self.HARD_MAX_VARIANTS:
            errors.append(
                f"competitive.max_variants must be <= {self.HARD_MAX_VARIANTS}"
            )

        copy_paths_raw = config.get("copy_paths") or []
        if not isinstance(copy_paths_raw, list):
            errors.append("competitive.copy_paths must be a list")
            copy_paths_raw = []

        copy_paths: list[str] = []
        for raw_path in copy_paths_raw:
            if not isinstance(raw_path, str) or not raw_path.strip():
                errors.append("competitive.copy_paths entries must be non-empty strings")
                continue
            try:
                copy_paths.append(self._validate_relative_path(raw_path))
            except ValueError as exc:
                errors.append(str(exc))

        variants_raw = config.get("variants")
        if not isinstance(variants_raw, list):
            errors.append("competitive.variants must be a list")
            variants_raw = []

        if len(variants_raw) < 2:
            errors.append("competitive.variants must define at least 2 variants")
        if isinstance(max_variants, int) and len(variants_raw) > max_variants:
            errors.append(
                "competitive.variants exceeds configured max_variants"
            )

        seen_ids: set[str] = set()
        normalized_variants: list[dict] = []
        for index, variant in enumerate(variants_raw, start=1):
            if not isinstance(variant, dict):
                errors.append(f"competitive.variants[{index}] must be an object")
                continue

            variant_id = variant.get("id")
            if not isinstance(variant_id, str) or not variant_id.strip():
                errors.append(f"competitive.variants[{index}].id is required")
                continue
            if not VARIANT_ID_PATTERN.fullmatch(variant_id):
                errors.append(
                    f"competitive variant id must match {VARIANT_ID_PATTERN.pattern}: "
                    f"{variant_id}"
                )
                continue
            if variant_id in seen_ids:
                errors.append(f"duplicate competitive variant id: {variant_id}")
                continue
            seen_ids.add(variant_id)

            actions = variant.get("actions")
            if not isinstance(actions, list) or not actions:
                errors.append(
                    f"competitive variant '{variant_id}' must define actions"
                )
                continue

            normalized_actions: list[dict] = []
            invalid_action = False
            for action_index, action in enumerate(actions, start=1):
                if not isinstance(action, dict):
                    errors.append(
                        "competitive variant "
                        f"'{variant_id}' action {action_index} must be an object"
                    )
                    invalid_action = True
                    break
                normalized_actions.append(dict(action))
            if invalid_action:
                continue

            normalized_variants.append(
                {
                    "id": variant_id,
                    "label": (
                        str(variant["label"])
                        if variant.get("label") is not None
                        else None
                    ),
                    "description": (
                        str(variant["description"])
                        if variant.get("description") is not None
                        else None
                    ),
                    "actions": normalized_actions,
                }
            )

        return (
            {
                "enabled": True,
                "max_variants": max_variants,
                "copy_paths": copy_paths,
                "variants": normalized_variants,
            },
            errors,
        )

    def _run_variant(
        self,
        spec: TaskSpec,
        variant: dict,
        variants_dir: Path,
        project_root: Path,
        copy_paths: list[str],
        core_bridge: dict | None,
        effective_hypothesis: dict | None,
        constraint_map: dict[str, list[str]],
        warned_variant_ids: set[str],
    ) -> VariantResult:
        """개별 variant를 격리 workspace에서 실행한다."""
        variant_id = str(variant["id"])
        variant_dir = variants_dir / variant_id
        workspace_path = variant_dir / "workspace"

        try:
            self._prepare_workspace(workspace_path, variant_dir)
            self._copy_seed_paths(
                project_root=project_root,
                workspace_path=workspace_path,
                copy_paths=copy_paths,
            )
        except Exception as exc:
            logger.exception("competitive workspace setup failed: %s", variant_id)
            return VariantResult(
                variant_id=variant_id,
                label=variant.get("label"),
                description=variant.get("description"),
                status="failure",
                workspace_path=str(workspace_path),
                score_summary={"result_source": "executed", "eligible": False},
                errors=[str(exc)],
            )

        work_items: list[WorkItem] = []
        executor_results = []
        executor = ExecutorV1(workspace_path)
        for index, action in enumerate(variant["actions"], start=1):
            work_item = WorkItem(
                item_id=f"{variant_id}-work-{index:03d}",
                description=self._describe_action(variant_id, index, action),
                status="pending",
                assigned_role="executor",
                action=action,
            )
            work_items.append(work_item)
            executor_results.append(executor.execute(work_item))

        variant_spec = TaskSpec(
            task_id=f"{spec.task_id}:{variant_id}",
            goal=spec.goal,
            scope=[item.description for item in work_items],
            non_goals=list(spec.non_goals),
            acceptance_criteria=list(spec.acceptance_criteria),
            related_files=list(spec.related_files),
            related_tests=list(spec.related_tests),
            output_paths=list(spec.output_paths),
            core_refs=dict(spec.core_refs) if spec.core_refs else None,
            generation_seed=(
                dict(spec.generation_seed)
                if isinstance(spec.generation_seed, dict)
                else None
            ),
            feedback_refs=list(spec.feedback_refs) if spec.feedback_refs else None,
            hypothesis=dict(effective_hypothesis) if effective_hypothesis else None,
            competitive=None,
            actions=None,
        )
        state = RunState(
            run_id=f"{spec.task_id}:{variant_id}",
            task_spec=variant_spec,
            work_items=work_items,
            step_results=list(executor_results),
            core_bridge=core_bridge,
        )

        tester = TesterV1(workspace_path)
        tester_step, test_detail = tester.run_tests(state)
        state.step_results.append(tester_step)

        reviewer = ReviewerV1(workspace_path)
        reviewer_step, verdict = reviewer.review(state)
        state.step_results.append(reviewer_step)

        files_created = self._collect_paths(executor_results, "write_file")
        files_modified = self._collect_paths(executor_results, "patch_file")
        mini_report = {
            "run_id": f"{spec.task_id}:{variant_id}",
            "task_id": spec.task_id,
            "status": state.status,
            "test_results": {
                "passed": test_detail.passed,
                "failed": test_detail.failed,
                "skipped": test_detail.skipped,
            },
            "core_bridge": core_bridge,
            "provenance_handoff": {
                "files_created": files_created,
                "files_modified": files_modified,
                "tests_executed": list(spec.related_tests or []),
                "test_exit_code": test_detail.exit_code,
                "reviewer_passed": verdict.passed,
                "reviewer_conclusion": verdict.conclusion,
                "adoption_ready": bool(
                    verdict.passed and test_detail.exit_code in (0, 5)
                ),
                "stable_ref": f"{spec.task_id}:{variant_id}",
            },
        }

        if effective_hypothesis:
            hypothesis = self._hypothesis.evaluate(effective_hypothesis, mini_report)
            hypothesis_status = hypothesis.status
        else:
            hypothesis_status = "skipped"

        all_done = all(item.status == "done" for item in work_items)
        variant_status = (
            "success"
            if verdict.passed and all_done and test_detail.failed == 0
            else "failure"
        )
        errors = []
        for step in executor_results:
            errors.extend(step.errors)
        errors.extend(tester_step.errors)
        errors.extend(reviewer_step.errors)

        changed_file_count = len(files_created) + len(files_modified)
        score_summary = {
            "result_source": "executed",
            "eligible": self._is_eligible(
                variant_status,
                verdict.passed,
                test_detail.failed,
                hypothesis_status,
            ),
            "changed_file_count": changed_file_count,
            "passed": test_detail.passed,
            "failed": test_detail.failed,
            "skipped": test_detail.skipped,
        }

        result = VariantResult(
            variant_id=variant_id,
            label=variant.get("label"),
            description=variant.get("description"),
            status=variant_status,
            workspace_path=str(workspace_path),
            files_created=files_created,
            files_modified=files_modified,
            tests_executed=list(spec.related_tests or []),
            test_exit_code=test_detail.exit_code,
            test_results=mini_report["test_results"],
            reviewer_passed=verdict.passed,
            reviewer_conclusion=verdict.conclusion,
            hypothesis_status=hypothesis_status,
            score_summary=score_summary,
            errors=errors,
        )
        self._apply_winner_constraints(
            result,
            constraint_map,
            warned_variant_ids,
        )
        return result

    def _select_winner(
        self,
        variants: list[VariantResult],
    ) -> tuple[str, str | None, str]:
        """winner를 선택한다."""
        eligible = [
            variant
            for variant in variants
            if not variant.excluded_from_winner
            if self._is_eligible(
                variant.status,
                variant.reviewer_passed,
                self._get_failed_count(variant),
                variant.hypothesis_status,
            )
        ]
        if not eligible:
            if variants and all(variant.excluded_from_winner for variant in variants):
                return (
                    "no_winner",
                    None,
                    "no winner: all variants were excluded by generation constraints",
                )
            return (
                "no_winner",
                None,
                "no winner: all variants failed tests, review, hypothesis checks, or generation constraints",
            )

        eligible.sort(key=self._winner_sort_key)
        winner = eligible[0]
        return (
            "success",
            winner.variant_id,
            (
                f"{winner.variant_id} selected: "
                f"{winner.hypothesis_status or 'skipped'} hypothesis, "
                f"{winner.test_results.get('passed', 0)} passed, "
                f"{winner.test_results.get('failed', 0)} failed"
            ),
        )

    @staticmethod
    def _resolve_effective_hypothesis(
        spec: TaskSpec,
        feedback_context,
        refinement: dict,
    ) -> dict | None:
        """TaskSpec 또는 generation seed에서 실제 평가용 가설을 정한다."""
        if isinstance(spec.hypothesis, dict):
            return dict(spec.hypothesis)
        refined_hypothesis = refinement.get("refined_hypothesis")
        if isinstance(refined_hypothesis, dict):
            hypothesis = dict(refined_hypothesis)
            hypothesis.setdefault("id", "refinement-hypothesis")
            return hypothesis
        if isinstance(feedback_context.hypothesis_seed, dict):
            hypothesis = dict(feedback_context.hypothesis_seed)
            hypothesis.setdefault("id", "seed-hypothesis")
            return hypothesis
        return None

    @staticmethod
    def _resolve_run_constraints(
        variants: list[dict],
        feedback_context,
        selection_pressure: dict,
        refinement: dict,
    ) -> tuple[dict[str, list[str]], set[str], list[str]]:
        """generation seed와 selection pressure에서 deterministic constraint를 추출한다."""
        warnings: list[str] = []
        blocked_reasons: dict[str, list[str]] = {}
        warned_variant_ids: set[str] = set()
        competitive_seed = (
            dict(feedback_context.competitive_seed)
            if isinstance(feedback_context.competitive_seed, dict)
            else {}
        )

        raw_avoid_ids = competitive_seed.get("avoid_variant_ids")
        if raw_avoid_ids is not None:
            if isinstance(raw_avoid_ids, list):
                for item in raw_avoid_ids:
                    variant_id = str(item).strip()
                    if not variant_id:
                        continue
                    blocked_reasons.setdefault(variant_id, []).append(
                        "blocked by generation seed avoid_variant_ids"
                    )
            else:
                warnings.append(
                    "generation_seed.competitive_seed.avoid_variant_ids must be a list"
                )

        recommended_variant_count = competitive_seed.get("recommended_variant_count")
        if recommended_variant_count is not None:
            try:
                expected_count = int(recommended_variant_count)
            except (TypeError, ValueError):
                warnings.append(
                    "generation_seed.competitive_seed.recommended_variant_count must be an integer"
                )
            else:
                actual_count = len(variants)
                if actual_count != expected_count:
                    warnings.append(
                        "generation seed recommends "
                        f"{expected_count} variants, but current run defines {actual_count}"
                    )

        raw_blocked_variant_ids = selection_pressure.get("blocked_variant_ids")
        if raw_blocked_variant_ids is not None:
            if isinstance(raw_blocked_variant_ids, list):
                for item in raw_blocked_variant_ids:
                    variant_id = str(item).strip()
                    if not variant_id:
                        continue
                    blocked_reasons.setdefault(variant_id, []).append(
                        "blocked by selection pressure blocked_variant_ids"
                    )
            else:
                warnings.append("selection_pressure.blocked_variant_ids must be a list")

        raw_warned_variant_ids = selection_pressure.get("warned_variant_ids")
        if raw_warned_variant_ids is not None:
            if isinstance(raw_warned_variant_ids, list):
                warned_variant_ids.update(
                    str(item).strip()
                    for item in raw_warned_variant_ids
                    if str(item).strip()
                )
            else:
                warnings.append("selection_pressure.warned_variant_ids must be a list")

        recommended_variant_count = selection_pressure.get("recommended_variant_count")
        if recommended_variant_count is not None:
            try:
                expected_count = int(recommended_variant_count)
            except (TypeError, ValueError):
                warnings.append(
                    "selection_pressure.recommended_variant_count must be an integer"
                )
            else:
                actual_count = len(variants)
                if actual_count != expected_count:
                    warnings.append(
                        "selection pressure recommends "
                        f"{expected_count} variants, but current run defines {actual_count}"
                    )

        refinement_constraints = (
            dict(refinement.get("constraints") or {})
            if isinstance(refinement.get("constraints"), dict)
            else {}
        )
        raw_refinement_blocked = refinement_constraints.get("blocked_variant_ids")
        if raw_refinement_blocked is not None:
            if isinstance(raw_refinement_blocked, list):
                for item in raw_refinement_blocked:
                    variant_id = str(item).strip()
                    if not variant_id:
                        continue
                    blocked_reasons.setdefault(variant_id, []).append(
                        "blocked by hypothesis refinement blocked_variant_ids"
                    )
            else:
                warnings.append(
                    "hypothesis_refinement.constraints.blocked_variant_ids must be a list"
                )

        raw_refinement_warned = refinement_constraints.get("warned_variant_ids")
        if raw_refinement_warned is not None:
            if isinstance(raw_refinement_warned, list):
                warned_variant_ids.update(
                    str(item).strip()
                    for item in raw_refinement_warned
                    if str(item).strip()
                )
            else:
                warnings.append(
                    "hypothesis_refinement.constraints.warned_variant_ids must be a list"
                )

        recommended_variant_count = refinement_constraints.get("recommended_variant_count")
        if recommended_variant_count is not None:
            try:
                expected_count = int(recommended_variant_count)
            except (TypeError, ValueError):
                warnings.append(
                    "hypothesis_refinement.constraints.recommended_variant_count must be an integer"
                )
            else:
                actual_count = len(variants)
                if actual_count != expected_count:
                    warnings.append(
                        "hypothesis refinement recommends "
                        f"{expected_count} variants, but current run defines {actual_count}"
                    )

        return (
            {variant_id: _unique(reasons) for variant_id, reasons in blocked_reasons.items()},
            warned_variant_ids,
            _unique(warnings),
        )

    @staticmethod
    def _apply_winner_constraints(
        result: VariantResult,
        constraint_map: dict[str, list[str]],
        warned_variant_ids: set[str],
    ) -> None:
        """winner 후보 제외 규칙을 variant 결과에 반영한다."""
        reasons = list(result.constraint_reasons)
        warnings = list(result.warnings)
        pressure_reasons = list(result.pressure_reasons)
        blocked_reasons = list(constraint_map.get(result.variant_id) or [])
        if blocked_reasons:
            result.excluded_from_winner = True
            for reason in blocked_reasons:
                if reason not in reasons:
                    reasons.append(reason)
                if reason not in warnings:
                    warnings.append(reason)
                if "selection pressure" in reason:
                    result.pressure_excluded_from_winner = True
                    if reason not in pressure_reasons:
                        pressure_reasons.append(reason)
        if result.variant_id in warned_variant_ids:
            warning = "warned by selection pressure warned_variant_ids"
            if warning not in warnings:
                warnings.append(warning)
        result.constraint_reasons = reasons
        result.warnings = warnings
        result.pressure_reasons = pressure_reasons
        result.score_summary = dict(result.score_summary)
        result.score_summary["eligible"] = (
            bool(result.score_summary.get("eligible", False))
            and not result.excluded_from_winner
        )

    @staticmethod
    def _winner_sort_key(variant: VariantResult) -> tuple:
        """winner tie-break용 정렬 키."""
        hypothesis_rank_map = {
            "supported": 0,
            "skipped": 1,
            "inconclusive": 2,
            "unavailable": 3,
            None: 4,
        }
        hypothesis_rank = hypothesis_rank_map.get(variant.hypothesis_status, 5)
        changed_file_count = (
            len(variant.files_created) + len(variant.files_modified)
        )
        return (
            hypothesis_rank,
            int(variant.test_results.get("failed", 0) or 0),
            -int(variant.test_results.get("passed", 0) or 0),
            changed_file_count,
            variant.variant_id,
        )

    @staticmethod
    def _is_eligible(
        status: str,
        reviewer_passed: bool | None,
        failed_count: int,
        hypothesis_status: str | None,
    ) -> bool:
        """winner 후보 적격 여부."""
        if status != "success":
            return False
        if reviewer_passed is not True:
            return False
        if failed_count != 0:
            return False
        return hypothesis_status not in {"contradicted", "error"}

    @staticmethod
    def _get_failed_count(variant: VariantResult) -> int:
        """variant의 failed test 수."""
        try:
            return int(variant.test_results.get("failed", 0) or 0)
        except (AttributeError, TypeError, ValueError):
            return 0

    @staticmethod
    def _describe_action(variant_id: str, index: int, action: dict) -> str:
        """액션 설명 문자열."""
        action_type = str(action.get("type", "unknown"))
        target_path = str(action.get("target_path", ""))
        return f"{variant_id} action {index}: {action_type} {target_path}".strip()

    @staticmethod
    def _collect_paths(executor_results: list, action_type: str) -> list[str]:
        """executor 결과에서 파일 경로를 모은다."""
        paths: list[str] = []
        seen: set[str] = set()
        for step in executor_results:
            details = step.details or {}
            if details.get("action_type") != action_type:
                continue
            if step.status != "success":
                continue
            for artifact in step.artifacts:
                if artifact not in seen:
                    seen.add(artifact)
                    paths.append(artifact)
        return paths

    def _prepare_workspace(self, workspace_path: Path, variant_dir: Path) -> None:
        """variant workspace를 초기화한다."""
        if workspace_path.exists():
            resolved_workspace = workspace_path.resolve()
            resolved_variant_dir = variant_dir.resolve()
            try:
                resolved_workspace.relative_to(resolved_variant_dir)
            except ValueError as exc:
                raise ValueError(
                    f"unsafe workspace path: {resolved_workspace}"
                ) from exc
            shutil.rmtree(resolved_workspace)
        workspace_path.mkdir(parents=True, exist_ok=True)

    def _copy_seed_paths(
        self,
        project_root: Path,
        workspace_path: Path,
        copy_paths: list[str],
    ) -> None:
        """copy_paths를 variant workspace로 복사한다."""
        for raw_path in copy_paths:
            rel_path = Path(raw_path)
            source = (project_root / rel_path).resolve()
            if not source.exists():
                raise FileNotFoundError(f"competitive.copy_paths source not found: {raw_path}")
            try:
                source.relative_to(project_root)
            except ValueError as exc:
                raise ValueError(
                    f"competitive.copy_paths escaped project root: {raw_path}"
                ) from exc

            target = workspace_path / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(
                    source,
                    target,
                    dirs_exist_ok=True,
                    ignore=self._ignore_copy_names,
                )
            else:
                shutil.copy2(source, target)

    def _ignore_copy_names(
        self,
        _directory: str,
        names: list[str],
    ) -> list[str]:
        """복사에서 제외할 이름 목록."""
        return [name for name in names if name in self._IGNORED_NAMES]

    @staticmethod
    def _validate_relative_path(raw_path: str) -> str:
        """project_root 기준 상대 경로만 허용한다."""
        path = Path(raw_path)
        if path.is_absolute():
            raise ValueError(
                f"competitive.copy_paths must be relative: {raw_path}"
            )
        if ".." in path.parts:
            raise ValueError(
                f"competitive.copy_paths cannot contain '..': {raw_path}"
            )
        return raw_path

    @staticmethod
    def _load_result(result_path: Path) -> VariantResult | None:
        """기존 variant 결과가 있으면 재사용한다."""
        if not result_path.exists():
            return None
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("competitive result reuse skipped: %s", result_path)
            return None
        if not isinstance(data, dict):
            return None
        try:
            return VariantResult.from_dict(data)
        except Exception:
            logger.warning("competitive result reuse parse failed: %s", result_path)
            return None

    @staticmethod
    def _save_result(result_path: Path, result: VariantResult) -> None:
        """variant 결과를 저장한다."""
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
