"""Cambrian Harness Brain 최종 보고서 생성."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from engine.brain.feedback_context import FeedbackContextLoader
from engine.brain.hypothesis import HypothesisEvaluator
from engine.brain.models import RunState, StepResult

logger = logging.getLogger(__name__)


def _iter_steps(state: RunState, role: str):
    """state.step_results에서 특정 role만 순회한다."""
    for step in state.step_results:
        if step.role == role:
            yield step


def _find_last_step(state: RunState, role: str) -> StepResult | None:
    """특정 role의 마지막 step을 반환한다."""
    last: StepResult | None = None
    for step in _iter_steps(state, role):
        last = step
    return last


def _collect_files_created(state: RunState) -> list[str]:
    """executor write_file 결과물 경로를 모은다."""
    paths: list[str] = []
    seen: set[str] = set()
    for step in _iter_steps(state, "executor"):
        details = step.details or {}
        if details.get("action_type") != "write_file":
            continue
        if step.status != "success":
            continue
        for artifact in step.artifacts:
            if artifact not in seen:
                seen.add(artifact)
                paths.append(artifact)
    return paths


def _collect_files_modified(state: RunState) -> list[str]:
    """executor patch_file 결과물 경로를 모은다."""
    paths: list[str] = []
    seen: set[str] = set()
    for step in _iter_steps(state, "executor"):
        details = step.details or {}
        if details.get("action_type") != "patch_file":
            continue
        if step.status != "success":
            continue
        for artifact in step.artifacts:
            if artifact not in seen:
                seen.add(artifact)
                paths.append(artifact)
    return paths


def _get_last_test_exit_code(state: RunState) -> int:
    """가장 최근 tester details.exit_code를 반환한다."""
    step = _find_last_step(state, "tester")
    if step is None or step.details is None:
        return -1
    try:
        return int(step.details.get("exit_code", -1))
    except (TypeError, ValueError):
        return -1


def _get_reviewer_passed(state: RunState) -> bool:
    """가장 최근 reviewer details.passed를 반환한다."""
    step = _find_last_step(state, "reviewer")
    if step is None or step.details is None:
        return False
    return bool(step.details.get("passed", False))


def _get_reviewer_conclusion(state: RunState) -> str:
    """가장 최근 reviewer details.conclusion을 반환한다."""
    step = _find_last_step(state, "reviewer")
    if step is None or step.details is None:
        return ""
    return str(step.details.get("conclusion", ""))


def _resolve_core_ref_path(
    raw_path: str,
    workspace: str | Path | None = None,
) -> Path:
    """core ref 경로를 workspace 기준 절대 경로로 해석한다."""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    base_dir = Path(workspace) if workspace is not None else Path.cwd()
    return (base_dir / path).resolve()


def _summarize_scenario_report(payload: dict) -> dict:
    """scenario report 핵심 요약을 만든다."""
    promote = payload.get("promote_recommendation")
    recommend_value = None
    if isinstance(promote, dict):
        recommend_value = promote.get("recommendation")
    elif promote is not None:
        recommend_value = str(promote)

    return {
        "scenario_name": str(payload.get("scenario_name", "")),
        "success": bool(payload.get("success", False)),
        "success_rate": payload.get("success_rate"),
        "total_inputs": payload.get("total_inputs"),
        "successful_inputs": payload.get("successful_inputs"),
        "failed_inputs": payload.get("failed_inputs"),
        "avg_execution_ms": payload.get("avg_execution_ms"),
        "winner_skill": payload.get("winner_skill"),
        "promote_recommendation": recommend_value,
    }


def _summarize_matrix_summary(payload: dict) -> dict:
    """matrix summary 핵심 요약을 만든다."""
    profiles = payload.get("profiles") or []
    improved = 0
    mixed = 0
    regressed = 0
    blocked = 0
    for profile in profiles:
        verdict = profile.get("verdict_vs_baseline")
        if verdict == "improved":
            improved += 1
        elif verdict == "mixed":
            mixed += 1
        elif verdict == "regressed":
            regressed += 1
        elif verdict == "error":
            blocked += 1

    return {
        "scenario_name": str(payload.get("scenario_name", "")),
        "baseline_policy": str(payload.get("baseline_policy", "")),
        "overall_verdict": str(payload.get("overall_verdict", "")),
        "profile_count": len(profiles),
        "baseline_profile_count": sum(
            1 for profile in profiles if profile.get("is_baseline")
        ),
        "improved_count": improved,
        "mixed_count": mixed,
        "regressed_count": regressed,
        "blocked_count": blocked,
    }


def _summarize_decision_report(payload: dict) -> dict:
    """decision report 핵심 요약을 만든다."""
    champion = payload.get("champion") or {}
    if not isinstance(champion, dict):
        champion = {}
    promotion = payload.get("promotion") or {}
    if not isinstance(promotion, dict):
        promotion = {}

    return {
        "scenario_name": str(payload.get("scenario_name", "")),
        "baseline_policy": str(payload.get("baseline_policy", "")),
        "baseline_decision": str(payload.get("baseline_decision", "")),
        "champion_policy": champion.get("policy_path"),
        "champion_success_rate": champion.get("success_rate"),
        "champion_eval_pass_rate": champion.get("eval_pass_rate"),
        "recommend_promote": bool(
            promotion.get("recommend_promote", False)
        ),
        "promotion_reason": str(promotion.get("reason", "")),
    }


def _summarize_generic_artifact(payload: dict) -> dict:
    """알 수 없는 artifact는 안전한 메타 정보만 남긴다."""
    keys = sorted(str(key) for key in payload.keys())
    return {
        "top_level_keys": keys,
        "top_level_key_count": len(keys),
    }


def _infer_artifact_type(ref_name: str) -> str:
    """ref 이름에서 artifact 타입을 추론한다."""
    normalized = ref_name.lower()
    if "decision" in normalized:
        return "decision_report"
    if "matrix" in normalized:
        return "matrix_summary"
    if "scenario" in normalized:
        return "scenario_report"
    return "generic_json"


def _summarize_artifact(ref_name: str, payload: dict) -> dict:
    """artifact 타입에 맞는 summary를 만든다."""
    artifact_type = _infer_artifact_type(ref_name)
    if artifact_type == "scenario_report":
        return _summarize_scenario_report(payload)
    if artifact_type == "matrix_summary":
        return _summarize_matrix_summary(payload)
    if artifact_type == "decision_report":
        return _summarize_decision_report(payload)
    return _summarize_generic_artifact(payload)


def build_core_bridge_summary(
    core_refs: dict[str, str] | None,
    workspace: str | Path | None = None,
) -> dict | None:
    """read-only core artifact 요약을 만든다."""
    if not core_refs:
        return None

    artifacts: list[dict] = []
    loaded_count = 0
    missing_count = 0
    invalid_count = 0

    for ref_name, raw_path in core_refs.items():
        resolved_path = _resolve_core_ref_path(raw_path, workspace=workspace)
        artifact_type = _infer_artifact_type(ref_name)
        entry = {
            "ref_name": ref_name,
            "artifact_type": artifact_type,
            "path": raw_path,
            "resolved_path": str(resolved_path),
            "status": "loaded",
            "summary": None,
            "errors": [],
        }

        if not resolved_path.exists():
            message = f"core artifact not found: {resolved_path}"
            entry["status"] = "missing"
            entry["errors"].append(message)
            missing_count += 1
            logger.warning(message)
            artifacts.append(entry)
            continue

        try:
            payload = json.loads(resolved_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            message = f"core artifact JSON parse failed: {resolved_path} ({exc})"
            entry["status"] = "invalid"
            entry["errors"].append(message)
            invalid_count += 1
            logger.warning(message)
            artifacts.append(entry)
            continue
        except OSError as exc:
            message = f"core artifact read failed: {resolved_path} ({exc})"
            entry["status"] = "invalid"
            entry["errors"].append(message)
            invalid_count += 1
            logger.warning(message)
            artifacts.append(entry)
            continue

        if not isinstance(payload, dict):
            message = f"core artifact must be a JSON object: {resolved_path}"
            entry["status"] = "invalid"
            entry["errors"].append(message)
            invalid_count += 1
            logger.warning(message)
            artifacts.append(entry)
            continue

        entry["summary"] = _summarize_artifact(ref_name, payload)
        loaded_count += 1
        artifacts.append(entry)

    return {
        "read_only": True,
        "artifact_count": len(artifacts),
        "loaded_count": loaded_count,
        "missing_count": missing_count,
        "invalid_count": invalid_count,
        "artifacts": artifacts,
    }


def _append_unique_actions(
    base_actions: list[str],
    extra_actions: list[str],
) -> list[str]:
    """next_actions를 중복 없이 합친다."""
    merged = list(base_actions)
    for action in extra_actions:
        if action and action not in merged:
            merged.append(action)
    return merged


def _coerce_int(value: object, default: int = 0) -> int:
    """정수 변환 보조 함수."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_standard_changes_summary(state: RunState) -> list[str]:
    """기존 단일 run 변경 요약."""
    return [
        work_item.description
        for work_item in state.work_items
        if work_item.status == "done"
    ]


def _build_standard_remaining_risks(state: RunState) -> list[str]:
    """기존 단일 run 위험 요약."""
    return [
        f"[{work_item.status}] {work_item.description}"
        for work_item in state.work_items
        if work_item.status in ("failed", "pending", "in_progress")
    ]


def _build_standard_test_results(state: RunState) -> dict:
    """기존 단일 run 테스트 요약."""
    passed = 0
    failed = 0
    skipped = 0
    for step in _iter_steps(state, "tester"):
        details = step.details or {}
        if details:
            passed += _coerce_int(details.get("passed", 0))
            failed += _coerce_int(details.get("failed", 0))
            skipped += _coerce_int(details.get("skipped", 0))
        else:
            if step.status == "success":
                passed += 1
            elif step.status == "failure":
                failed += 1
            elif step.status == "skipped":
                skipped += 1
    return {
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def _build_diagnostics(
    state: RunState,
    test_results: dict,
) -> dict:
    """읽기 전용 diagnose-only 실행 결과를 report용으로 요약한다."""
    inspected_files: list[dict] = []
    for step in _iter_steps(state, "executor"):
        details = step.details or {}
        action_name = details.get("action") or details.get("action_type")
        if action_name != "inspect_files":
            continue
        for item in details.get("inspected_files", []) or []:
            if not isinstance(item, dict):
                continue
            inspected_files.append(
                {
                    "path": item.get("path"),
                    "sha256": item.get("sha256"),
                    "size_bytes": item.get("size_bytes"),
                    "truncated": bool(item.get("truncated", False)),
                }
            )

    if not inspected_files:
        return {
            "enabled": False,
        }

    related_tests = list(state.task_spec.related_tests or [])
    next_actions: list[str] = []
    if inspected_files and inspected_files[0].get("path"):
        next_actions.append(
            f"Prepare a patch against {inspected_files[0]['path']}"
        )

    failed = _coerce_int(test_results.get("failed", 0))
    passed = _coerce_int(test_results.get("passed", 0))
    if failed > 0:
        next_actions.append("Use failing test output as evidence")
    elif related_tests and passed > 0:
        next_actions.append("Use passing test output as baseline evidence")

    return {
        "enabled": True,
        "mode": "read_only",
        "inspected_files": inspected_files,
        "related_tests": related_tests,
        "test_results": {
            "passed": passed,
            "failed": failed,
            "skipped": _coerce_int(test_results.get("skipped", 0)),
        },
        "next_actions": next_actions,
    }


def _build_standard_next_actions(
    state: RunState,
    remaining_risks: list[str],
) -> list[str]:
    """기존 단일 run next_actions."""
    next_actions: list[str] = []
    last_reviewer = _find_last_step(state, "reviewer")
    if last_reviewer and last_reviewer.details:
        for action in last_reviewer.details.get("next_actions", []) or []:
            if action and action not in next_actions:
                next_actions.append(str(action))

    if remaining_risks and not any("retry" in action for action in next_actions):
        next_actions.append(
            f"미완료 위험 {len(remaining_risks)}건 재확인 필요"
        )
        failed_ids = [
            work_item.item_id
            for work_item in state.work_items
            if work_item.status == "failed"
        ]
        if failed_ids:
            next_actions.append(
                f"failed 항목 재시도: {', '.join(failed_ids)}"
            )
    if state.termination_reason == "max_iterations":
        next_actions.append(
            "max_iterations 도달: resume 또는 원인 분석 필요"
        )
    return next_actions


def _build_standard_provenance_handoff(state: RunState) -> dict:
    """기존 단일 run provenance_handoff."""
    test_exit_code = _get_last_test_exit_code(state)
    reviewer_passed = _get_reviewer_passed(state)
    test_ok = test_exit_code in (0, 5)
    adoption_ready = bool(reviewer_passed and test_ok)

    return {
        "run_id": state.run_id,
        "task_spec_path": f".cambrian/brain/runs/{state.run_id}/task_spec.yaml",
        "run_state_path": f".cambrian/brain/runs/{state.run_id}/run_state.json",
        "iteration_logs_dir": f".cambrian/brain/runs/{state.run_id}/iterations/",
        "report_path": f".cambrian/brain/runs/{state.run_id}/report.json",
        "files_created": _collect_files_created(state),
        "files_modified": _collect_files_modified(state),
        "tests_executed": list(state.task_spec.related_tests or []),
        "test_exit_code": test_exit_code,
        "reviewer_passed": reviewer_passed,
        "reviewer_conclusion": _get_reviewer_conclusion(state),
        "adoption_ready": adoption_ready,
        "stable_ref": state.run_id,
    }


def _get_competitive_generation(state: RunState) -> dict:
    """competitive generation section을 반환한다."""
    if not isinstance(state.competitive_generation, dict):
        return {
            "enabled": False,
            "status": "skipped",
        }
    enabled = bool(state.competitive_generation.get("enabled", False))
    if not enabled:
        return {
            "enabled": False,
            "status": str(state.competitive_generation.get("status", "skipped")),
        }
    return dict(state.competitive_generation)


def _get_competitive_winner(competitive: dict) -> dict | None:
    """winner variant dict를 찾는다."""
    winner_id = competitive.get("winner_variant_id")
    if not winner_id:
        return None
    for variant in competitive.get("variants", []) or []:
        if isinstance(variant, dict) and variant.get("variant_id") == winner_id:
            return variant
    return None


def _build_competitive_changes_summary(competitive: dict) -> list[str]:
    """competitive run 변경 요약."""
    winner = _get_competitive_winner(competitive)
    if winner is None:
        if competitive.get("status") == "failure":
            return ["competitive generation failed before winner selection"]
        return ["competitive generation completed without winner"]

    summary = [f"winner selected: {winner['variant_id']}"]
    for path in winner.get("files_created", []) or []:
        summary.append(f"created: {path}")
    for path in winner.get("files_modified", []) or []:
        summary.append(f"modified: {path}")
    return summary


def _build_competitive_remaining_risks(competitive: dict) -> list[str]:
    """competitive run 위험 요약."""
    risks: list[str] = []
    winner_id = competitive.get("winner_variant_id")

    if competitive.get("status") in {"no_winner", "failure"}:
        risks.append(str(competitive.get("selection_reason") or "no eligible winner"))

    for error in competitive.get("errors", []) or []:
        risks.append(f"[competitive] {error}")
    for warning in competitive.get("warnings", []) or []:
        risks.append(f"[competitive] {warning}")

    for variant in competitive.get("variants", []) or []:
        if not isinstance(variant, dict):
            continue
        variant_id = str(variant.get("variant_id", "unknown"))
        if winner_id and variant_id == winner_id:
            continue
        if variant.get("status") != "success":
            risks.append(f"[{variant_id}] status={variant.get('status')}")
        if variant.get("hypothesis_status") == "contradicted":
            risks.append(f"[{variant_id}] hypothesis contradicted")
        for warning in variant.get("warnings", []) or []:
            risks.append(f"[{variant_id}] {warning}")
        for error in variant.get("errors", []) or []:
            risks.append(f"[{variant_id}] {error}")
    return risks


def _build_competitive_test_results(competitive: dict) -> dict:
    """winner 기준 테스트 요약."""
    winner = _get_competitive_winner(competitive)
    if winner is None:
        return {"passed": 0, "failed": 0, "skipped": 0}
    test_results = winner.get("test_results")
    if not isinstance(test_results, dict):
        return {"passed": 0, "failed": 0, "skipped": 0}
    return {
        "passed": _coerce_int(test_results.get("passed", 0)),
        "failed": _coerce_int(test_results.get("failed", 0)),
        "skipped": _coerce_int(test_results.get("skipped", 0)),
    }


def _build_competitive_reviewer_conclusion(competitive: dict) -> str:
    """winner 또는 selection reason 기반 reviewer 결론."""
    winner = _get_competitive_winner(competitive)
    if winner is not None:
        conclusion = str(winner.get("reviewer_conclusion") or "")
        if conclusion:
            return conclusion
    return str(competitive.get("selection_reason", ""))


def _build_competitive_next_actions(competitive: dict) -> list[str]:
    """competitive run next_actions."""
    if not competitive.get("enabled", False):
        return []
    if competitive.get("status") == "success":
        return [
            "Review winner variant before adoption",
            "Consider promoting winner variant through adoption workflow",
        ]
    if competitive.get("status") in {"no_winner", "failure"}:
        return [
            "Competitive generation found no eligible winner",
            "Inspect failed variants and revise hypothesis or actions",
            "Use variant result errors as input for next generation",
        ]
    return []


def _build_competitive_provenance_handoff(
    state: RunState,
    competitive: dict,
) -> dict:
    """winner 기준 provenance_handoff를 만든다."""
    winner = _get_competitive_winner(competitive)
    if winner is None:
        return {
            "run_id": state.run_id,
            "task_spec_path": f".cambrian/brain/runs/{state.run_id}/task_spec.yaml",
            "run_state_path": f".cambrian/brain/runs/{state.run_id}/run_state.json",
            "iteration_logs_dir": f".cambrian/brain/runs/{state.run_id}/iterations/",
            "report_path": f".cambrian/brain/runs/{state.run_id}/report.json",
            "files_created": [],
            "files_modified": [],
            "tests_executed": list(state.task_spec.related_tests or []),
            "test_exit_code": -1,
            "reviewer_passed": False,
            "reviewer_conclusion": str(
                competitive.get("selection_reason", "")
            ),
            "adoption_ready": False,
            "stable_ref": state.run_id,
        }

    winner_tests = winner.get("test_results")
    if not isinstance(winner_tests, dict):
        winner_tests = {}
    default_exit_code = 0 if _coerce_int(winner_tests.get("failed", 0)) == 0 else 1
    test_exit_code = _coerce_int(
        winner.get("test_exit_code"),
        default=default_exit_code,
    )
    reviewer_passed = bool(winner.get("reviewer_passed", False))
    test_ok = test_exit_code in (0, 5)

    return {
        "run_id": state.run_id,
        "task_spec_path": f".cambrian/brain/runs/{state.run_id}/task_spec.yaml",
        "run_state_path": f".cambrian/brain/runs/{state.run_id}/run_state.json",
        "iteration_logs_dir": f".cambrian/brain/runs/{state.run_id}/iterations/",
        "report_path": f".cambrian/brain/runs/{state.run_id}/report.json",
        "files_created": list(winner.get("files_created") or []),
        "files_modified": list(winner.get("files_modified") or []),
        "tests_executed": list(
            winner.get("tests_executed") or state.task_spec.related_tests or []
        ),
        "test_exit_code": test_exit_code,
        "reviewer_passed": reviewer_passed,
        "reviewer_conclusion": str(winner.get("reviewer_conclusion") or ""),
        "adoption_ready": bool(reviewer_passed and test_ok),
        "stable_ref": state.run_id,
    }


def generate_report(state: RunState) -> dict:
    """RunState에서 최종 report dict를 생성한다."""
    competitive = _get_competitive_generation(state)
    feedback_context = FeedbackContextLoader().load_from_spec(
        state.task_spec,
        Path.cwd(),
    )
    if competitive.get("enabled", False):
        changes_summary = _build_competitive_changes_summary(competitive)
        remaining_risks = _build_competitive_remaining_risks(competitive)
        test_results = _build_competitive_test_results(competitive)
        reviewer_conclusion = _build_competitive_reviewer_conclusion(competitive)
        next_actions = _build_competitive_next_actions(competitive)
        provenance_handoff = _build_competitive_provenance_handoff(
            state,
            competitive,
        )
    else:
        changes_summary = _build_standard_changes_summary(state)
        remaining_risks = _build_standard_remaining_risks(state)
        test_results = _build_standard_test_results(state)
        reviewer_conclusion = _get_reviewer_conclusion(state)
        next_actions = _build_standard_next_actions(state, remaining_risks)
        provenance_handoff = _build_standard_provenance_handoff(state)

    report = {
        "run_id": state.run_id,
        "task_id": state.task_spec.task_id,
        "status": state.status,
        "changes_summary": changes_summary,
        "test_results": test_results,
        "remaining_risks": remaining_risks,
        "next_actions": next_actions,
        "total_iterations": state.current_iteration,
        "termination_reason": state.termination_reason,
        "started_at": state.started_at,
        "finished_at": state.finished_at,
        "provenance_ref": state.run_id,
        "reviewer_conclusion": reviewer_conclusion,
        "core_bridge": state.core_bridge,
        "competitive_generation": competitive,
        "provenance_handoff": provenance_handoff,
        "feedback_context": {
            "enabled": feedback_context.enabled,
        },
        "selection_pressure_context": {
            "enabled": False,
        },
        "hypothesis_refinement_context": {
            "enabled": False,
        },
    }
    diagnostics = _build_diagnostics(state, test_results)
    report["diagnostics"] = diagnostics
    if diagnostics.get("enabled"):
        report["next_actions"] = _append_unique_actions(
            report["next_actions"],
            list(diagnostics.get("next_actions", [])),
        )

    refinement = (
        dict(state.task_spec.hypothesis_refinement)
        if isinstance(state.task_spec.hypothesis_refinement, dict)
        else {}
    )
    refined_hypothesis = (
        dict(refinement.get("refined_hypothesis") or {})
        if isinstance(refinement.get("refined_hypothesis"), dict)
        else None
    )
    effective_hypothesis = state.task_spec.hypothesis
    hypothesis_source = "task_spec" if effective_hypothesis else None
    refinement_hypothesis_applied = False
    hypothesis_seed_applied = False
    if effective_hypothesis is None and refined_hypothesis is not None:
        effective_hypothesis = dict(refined_hypothesis)
        effective_hypothesis.setdefault("id", "refinement-hypothesis")
        hypothesis_source = "refinement"
        refinement_hypothesis_applied = True
    if effective_hypothesis is None and isinstance(feedback_context.hypothesis_seed, dict):
        effective_hypothesis = dict(feedback_context.hypothesis_seed)
        effective_hypothesis.setdefault("id", "seed-hypothesis")
        hypothesis_source = "generation_seed"
        hypothesis_seed_applied = True

    if feedback_context.enabled:
        report["feedback_context"] = {
            "enabled": True,
            "source_seed_path": feedback_context.source_seed_path,
            "source_feedback_refs": list(feedback_context.source_feedback_refs),
            "previous_outcome": feedback_context.previous_outcome,
            "lessons": {
                "keep": list(feedback_context.lessons_keep),
                "avoid": list(feedback_context.lessons_avoid),
                "missing_evidence": list(feedback_context.missing_evidence),
            },
            "suggested_next_actions": list(feedback_context.suggested_next_actions),
            "hypothesis_seed_applied": hypothesis_seed_applied,
            "competitive_seed_applied": bool(feedback_context.competitive_seed),
            "warnings": list(feedback_context.warnings),
            "errors": list(feedback_context.errors),
        }

    selection_pressure = (
        dict(state.task_spec.selection_pressure)
        if isinstance(state.task_spec.selection_pressure, dict)
        else {}
    )
    if selection_pressure:
        report["selection_pressure_context"] = {
            "enabled": True,
            "source_pressure_path": str(
                selection_pressure.get("source_pressure_path")
                or selection_pressure.get("_source_pressure_path")
                or ""
            )
            or None,
            "pressure_id": str(selection_pressure.get("pressure_id") or "") or None,
            "blocked_variant_ids": list(
                selection_pressure.get("blocked_variant_ids") or []
            ),
            "warned_variant_ids": list(
                selection_pressure.get("warned_variant_ids") or []
            ),
            "recommended_variant_count": selection_pressure.get(
                "recommended_variant_count"
            ),
            "risk_flags": list(selection_pressure.get("risk_flags") or []),
            "keep_patterns": list(selection_pressure.get("keep_patterns") or []),
            "avoid_patterns": list(selection_pressure.get("avoid_patterns") or []),
            "warnings": list(selection_pressure.get("warnings") or []),
            "errors": list(selection_pressure.get("errors") or []),
        }

    if refinement:
        report["hypothesis_refinement_context"] = {
            "enabled": True,
            "source_refinement_path": str(
                refinement.get("source_refinement_path")
                or refinement.get("source_refinement")
                or ""
            )
            or None,
            "refinement_id": str(refinement.get("refinement_id") or "") or None,
            "status": str(refinement.get("status") or "needs_review"),
            "hypothesis_applied": refinement_hypothesis_applied,
            "hypothesis_source": "refinement" if refinement_hypothesis_applied else "task_spec",
            "constraints_applied": dict(refinement.get("constraints") or {}),
            "required_evidence": list(refinement.get("required_evidence") or []),
            "warnings": list(refinement.get("warnings") or []),
            "errors": list(refinement.get("errors") or []),
        }

    hypothesis_evaluation = HypothesisEvaluator().evaluate(
        effective_hypothesis,
        report,
    )
    hypothesis_payload = hypothesis_evaluation.to_dict()
    hypothesis_payload["source"] = hypothesis_source or "none"
    report["hypothesis_evaluation"] = hypothesis_payload
    report["next_actions"] = _append_unique_actions(
        report["next_actions"],
        hypothesis_evaluation.next_actions,
    )
    previous_outcome = feedback_context.previous_outcome or {}
    previous_outcome_type = str(previous_outcome.get("outcome", "") or "")
    feedback_actions: list[str] = []
    if previous_outcome_type in ("failure", "no_winner", "inconclusive"):
        feedback_actions.extend(feedback_context.suggested_next_actions)
    for evidence in feedback_context.missing_evidence:
        feedback_actions.append(f"Feedback seed missing evidence: {evidence}")
    for warning in competitive.get("warnings", []) or []:
        feedback_actions.append(f"Feedback seed warning: {warning}")
    if competitive.get("enabled", False):
        for variant in competitive.get("variants", []) or []:
            if not isinstance(variant, dict):
                continue
            if bool(variant.get("excluded_from_winner", False)):
                feedback_actions.append(
                    "Variant "
                    f"{variant.get('variant_id')} was excluded from winner selection "
                    "due to generation constraints"
                )
    pressure_context = report.get("selection_pressure_context") or {}
    if pressure_context.get("enabled"):
        for risk_flag in pressure_context.get("risk_flags", []) or []:
            feedback_actions.append(f"Selection pressure risk: {risk_flag}")
        for warning in pressure_context.get("warnings", []) or []:
            feedback_actions.append(f"Selection pressure warning: {warning}")
        for error in pressure_context.get("errors", []) or []:
            feedback_actions.append(f"Selection pressure error: {error}")
        recommended_variant_count = pressure_context.get("recommended_variant_count")
        actual_variants = len(competitive.get("variants", []) or [])
        if recommended_variant_count is not None and actual_variants:
            try:
                expected_variant_count = int(recommended_variant_count)
            except (TypeError, ValueError):
                expected_variant_count = None
            if (
                expected_variant_count is not None
                and actual_variants != expected_variant_count
            ):
                feedback_actions.append(
                    "Selection pressure recommends "
                    f"{expected_variant_count} variants, but current run has {actual_variants}."
                )
    refinement_context = report.get("hypothesis_refinement_context") or {}
    if refinement_context.get("enabled"):
        if refinement_context.get("status") in {"needs_review", "inconclusive"}:
            feedback_actions.append(
                f"Refined hypothesis needs attention: {refinement_context.get('status')}"
            )
        for evidence in refinement_context.get("required_evidence", []) or []:
            feedback_actions.append(
                f"Refined hypothesis requires evidence: {evidence}"
            )
        constraints_applied = refinement_context.get("constraints_applied") or {}
        for risk_flag in constraints_applied.get("risk_flags", []) or []:
            feedback_actions.append(f"Refinement risk flag: {risk_flag}")
    report["next_actions"] = _append_unique_actions(
        report["next_actions"],
        feedback_actions,
    )
    return report
