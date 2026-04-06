"""Cambrian 경량 시나리오 러너.

JSON spec 파일 1개로 batch run → eval → evolve → promote 추천을
한 사이클로 실행하고 JSON report를 생성한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import platform
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.loop import CambrianEngine

logger = logging.getLogger(__name__)


def _compute_hash(content: str) -> str:
    """문자열의 SHA-256 해시를 계산한다 (앞 16자).

    Args:
        content: 해시할 문자열

    Returns:
        'sha256:' 접두사 + 16자 hex
    """
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class ScenarioRunner:
    """JSON spec 기반 시나리오 실행기."""

    def __init__(self, engine: CambrianEngine) -> None:
        """ScenarioRunner를 초기화한다.

        Args:
            engine: CambrianEngine 인스턴스
        """
        self._engine = engine

    def run_scenario(
        self,
        spec: dict,
        scenario_path: str = "",
        notes: str = "",
    ) -> dict:
        """scenario spec을 실행하고 report를 반환한다.

        Args:
            spec: scenario JSON spec dict
            scenario_path: spec 파일 경로 (snapshot 컨텍스트용)
            notes: 실험 메모

        Returns:
            실행 결과 report dict
        """
        # 1. spec 검증
        errors = self._validate_spec(spec)
        if errors:
            return {
                "success": False,
                "errors": errors,
                "scenario_name": spec.get("name", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # 2. budget override
        if spec.get("max_candidates") is not None:
            self._engine.MAX_CANDIDATES_PER_RUN = max(1, spec["max_candidates"])

        # 3. batch run
        run_results = self._run_inputs(spec)

        # 4. winner 식별
        winner_id = self._find_winner_skill(run_results)

        # 5. optional eval
        eval_result = None
        if spec.get("do_eval") and winner_id:
            try:
                eval_result = self._engine.evaluate(winner_id)
            except Exception as exc:
                eval_result = {"error": str(exc)}

        # 6. optional evolve
        evolve_result = None
        if spec.get("do_evolve") and winner_id:
            try:
                feedback_list = self._engine.get_registry().get_feedback(
                    winner_id, limit=5,
                )
                if feedback_list:
                    first_input = spec["inputs"][0]
                    record = self._engine.evolve(winner_id, first_input)
                    evolve_result = {
                        "adopted": record.adopted,
                        "parent_fitness": record.parent_fitness,
                        "child_fitness": record.child_fitness,
                    }
                else:
                    evolve_result = {"skipped": "no feedback available"}
            except Exception as exc:
                evolve_result = {"error": str(exc)}

        # 7. optional re-eval (evolve 채택 시)
        re_eval_result = None
        if (
            spec.get("do_eval")
            and spec.get("do_evolve")
            and winner_id
            and evolve_result
            and evolve_result.get("adopted")
        ):
            try:
                re_eval_result = self._engine.evaluate(winner_id)
            except Exception as exc:
                re_eval_result = {"error": str(exc)}

        # 8. promote recommendation
        recommendation = None
        if winner_id:
            recommendation = self._calculate_promote_recommendation(winner_id)

        # 9. report 조립
        return self._build_report(
            spec, run_results, eval_result,
            evolve_result, re_eval_result, recommendation,
            scenario_path=scenario_path,
            notes=notes,
        )

    def _validate_spec(self, spec: dict) -> list[str]:
        """spec의 필수 필드를 검증한다.

        Args:
            spec: 검증할 spec dict

        Returns:
            에러 메시지 리스트. 비어있으면 유효.
        """
        errors: list[str] = []

        if not spec.get("name"):
            errors.append("'name' is required")
        if not spec.get("domain"):
            errors.append("'domain' is required")

        tags = spec.get("tags")
        if not tags or not isinstance(tags, list) or len(tags) == 0:
            errors.append("'tags' must be a non-empty list")

        inputs = spec.get("inputs")
        if not inputs or not isinstance(inputs, list) or len(inputs) == 0:
            errors.append("'inputs' must be a non-empty list")
        elif not all(isinstance(item, dict) for item in inputs):
            errors.append("all items in 'inputs' must be dicts")

        return errors

    def _run_inputs(self, spec: dict) -> list[dict]:
        """inputs를 순차 실행하고 각 결과를 수집한다.

        Args:
            spec: scenario spec dict

        Returns:
            각 입력별 실행 결과 리스트
        """
        results: list[dict] = []
        for i, input_data in enumerate(spec["inputs"]):
            try:
                result = self._engine.run_task(
                    domain=spec["domain"],
                    tags=spec["tags"],
                    input_data=input_data,
                    max_retries=spec.get("retries", 3),
                )
                results.append({
                    "index": i,
                    "success": result.success,
                    "skill_id": result.skill_id,
                    "execution_time_ms": result.execution_time_ms,
                    "error": result.error if not result.success else "",
                    "output_preview": (
                        json.dumps(result.output, ensure_ascii=False)[:200]
                        if result.output else ""
                    ),
                })
            except Exception as exc:
                logger.warning("Scenario input #%d 실행 실패: %s", i, exc)
                results.append({
                    "index": i,
                    "success": False,
                    "skill_id": "",
                    "execution_time_ms": 0,
                    "error": str(exc),
                    "output_preview": "",
                })
        return results

    def _find_winner_skill(self, run_results: list[dict]) -> str | None:
        """성공한 실행에서 가장 많이 선택된 skill_id를 반환한다.

        Args:
            run_results: _run_inputs() 결과

        Returns:
            최다 선택 skill_id 또는 None
        """
        successful = [
            r["skill_id"] for r in run_results
            if r["success"] and r["skill_id"]
        ]
        if not successful:
            return None
        counter = Counter(successful)
        return counter.most_common(1)[0][0]

    def _calculate_promote_recommendation(self, winner_id: str) -> dict:
        """winner skill의 promotion 적격 여부를 판단한다.

        Args:
            winner_id: 평가 대상 스킬 ID

        Returns:
            추천 정보 dict
        """
        try:
            skill_data = self._engine.get_registry().get(winner_id)
            release_state = skill_data.get("release_state", "experimental")
            fitness = skill_data["fitness_score"]
            executions = skill_data["total_executions"]
            success_rate = (
                skill_data["successful_executions"] / executions
                if executions > 0 else 0.0
            )

            eligible = (
                executions >= 10
                and fitness >= 0.5
                and release_state in ("experimental", "candidate")
            )

            if release_state == "experimental" and eligible:
                recommendation = "promote_to_candidate"
            elif release_state == "candidate" and eligible:
                recommendation = "promote_to_production"
            else:
                recommendation = "not_eligible"

            return {
                "skill_id": winner_id,
                "release_state": release_state,
                "fitness": fitness,
                "executions": executions,
                "success_rate": round(success_rate, 4),
                "eligible": eligible,
                "recommendation": recommendation,
            }
        except Exception:
            return {
                "skill_id": winner_id,
                "recommendation": "unknown",
                "eligible": False,
            }

    def _build_report(
        self,
        spec: dict,
        run_results: list[dict],
        eval_result: dict | None,
        evolve_result: dict | None,
        re_eval_result: dict | None,
        recommendation: dict | None,
        scenario_path: str = "",
        notes: str = "",
    ) -> dict:
        """최종 report dict를 조립한다 (snapshot 컨텍스트 포함).

        Args:
            spec: scenario spec
            run_results: batch 실행 결과
            eval_result: eval 결과 (None이면 미실행)
            evolve_result: evolve 결과 (None이면 미실행)
            re_eval_result: re-eval 결과 (None이면 미실행)
            recommendation: promote 추천 (None이면 winner 없음)
            scenario_path: spec 파일 경로
            notes: 실험 메모

        Returns:
            완성된 report dict (snapshot 컨텍스트 포함)
        """
        total = len(run_results)
        successes = sum(1 for r in run_results if r["success"])
        success_times = [
            r["execution_time_ms"] for r in run_results if r["success"]
        ]
        avg_time = (
            sum(success_times) // len(success_times) if success_times else 0
        )

        # snapshot 컨텍스트
        policy = self._engine.get_policy()
        resolved_policy = policy.to_dict()
        scenario_hash = _compute_hash(
            json.dumps(spec, sort_keys=True, ensure_ascii=False)
        )
        policy_hash = _compute_hash(
            json.dumps(resolved_policy, sort_keys=True, ensure_ascii=False)
        )

        return {
            "_snapshot_version": "1.0.0",
            "_context": {
                "scenario_path": (
                    str(Path(scenario_path).resolve()) if scenario_path else ""
                ),
                "scenario_hash": scenario_hash,
                "policy_source": policy.policy_source,
                "policy_hash": policy_hash,
                "resolved_policy": resolved_policy,
                "run_options": {
                    "do_eval": spec.get("do_eval", False),
                    "do_evolve": spec.get("do_evolve", False),
                    "max_candidates_override": spec.get("max_candidates"),
                    "retries": spec.get("retries", 3),
                },
                "engine_version": "0.3.0",
                "python_version": platform.python_version(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "notes": notes,
            },
            "_reproducibility_notice": (
                "Snapshot preserves execution context for comparison. "
                "LLM-based operations (Mode A, evolve, judge) are "
                "nondeterministic; identical inputs may produce different "
                "outputs across runs."
            ),
            "success": True,
            "scenario_name": spec["name"],
            "domain": spec["domain"],
            "tags": spec["tags"],
            "total_inputs": total,
            "successful_inputs": successes,
            "failed_inputs": total - successes,
            "success_rate": round(successes / max(total, 1), 4),
            "avg_execution_ms": avg_time,
            "winner_skill": self._find_winner_skill(run_results),
            "run_results": run_results,
            "eval_result": eval_result,
            "evolve_result": evolve_result,
            "re_eval_result": re_eval_result,
            "promote_recommendation": recommendation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def run_matrix(
        self,
        spec: dict,
        policy_paths: list[str],
        baseline_path: str | None = None,
        scenario_path: str = "",
        notes: str = "",
        out_dir: Path | None = None,
    ) -> dict:
        """동일 spec을 여러 policy로 순차 실행하고 비교 요약을 반환한다.

        Args:
            spec: scenario JSON spec dict
            policy_paths: policy 파일 경로 목록
            baseline_path: baseline policy 경로 (None이면 첫 번째)
            scenario_path: spec 파일 경로 (snapshot용)
            notes: 실험 메모
            out_dir: 결과 저장 디렉토리 (None이면 자동 생성)

        Returns:
            matrix summary dict
        """
        from engine.policy import CambrianPolicy
        from engine.snapshot import SnapshotComparer

        # 1. spec 검증
        errors = self._validate_spec(spec)
        if errors:
            return {"success": False, "errors": errors}

        # 2. baseline 결정
        if baseline_path is None:
            baseline_path = policy_paths[0]
        if baseline_path not in policy_paths:
            return {
                "success": False,
                "errors": [
                    f"baseline '{baseline_path}' is not in policies list"
                ],
            }

        # 3. out_dir 결정
        if out_dir is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_dir = Path("matrix_runs") / f"{spec.get('name', 'matrix')}_{ts}"
        else:
            out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 4. 각 policy 순차 실행
        profiles: list[dict] = []
        snapshots: dict[str, dict] = {}

        for policy_path in policy_paths:
            is_baseline = (policy_path == baseline_path)
            policy_name = Path(policy_path).stem

            try:
                policy = CambrianPolicy(policy_path)

                # engine에 policy 적용
                self._engine.MAX_CANDIDATES_PER_RUN = policy.max_candidates_per_run
                self._engine.MAX_MODE_A_PER_RUN = policy.max_mode_a_per_run
                self._engine.MAX_EVAL_CASES = policy.max_eval_cases
                self._engine._policy = policy

                # scenario 실행
                snapshot = self.run_scenario(spec, scenario_path, notes)

                # 개별 snapshot 저장
                prefix = "baseline__" if is_baseline else "profile__"
                snap_file = f"{prefix}{policy_name}.json"
                snap_path = out_dir / snap_file
                snap_path.write_text(
                    json.dumps(snapshot, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                snapshots[policy_path] = snapshot
                profiles.append({
                    "policy_path": policy_path,
                    "policy_hash": snapshot.get("_context", {}).get(
                        "policy_hash", ""
                    ),
                    "is_baseline": is_baseline,
                    "snapshot_file": snap_file,
                    "success_rate": snapshot.get("success_rate", 0.0),
                    "eval_pass_rate": (
                        snapshot.get("eval_result", {}) or {}
                    ).get("pass_rate"),
                    "avg_execution_ms": snapshot.get("avg_execution_ms", 0),
                    "winner_skill": snapshot.get("winner_skill"),
                    "promote_recommendation": (
                        snapshot.get("promote_recommendation", {}) or {}
                    ).get("recommendation"),
                    "verdict_vs_baseline": None,
                })
            except Exception as exc:
                logger.warning("Policy '%s' 실행 실패: %s", policy_path, exc)
                prefix = "baseline__" if is_baseline else "profile__"
                snap_file = f"{prefix}{policy_name}.json"
                profiles.append({
                    "policy_path": policy_path,
                    "policy_hash": "",
                    "is_baseline": is_baseline,
                    "snapshot_file": snap_file,
                    "success_rate": 0.0,
                    "eval_pass_rate": None,
                    "avg_execution_ms": 0,
                    "winner_skill": None,
                    "promote_recommendation": None,
                    "verdict_vs_baseline": "error",
                })

        # 5. baseline 대비 verdict 계산
        baseline_snapshot = snapshots.get(baseline_path)
        if baseline_snapshot:
            comparer = SnapshotComparer()
            for profile in profiles:
                if profile["is_baseline"]:
                    continue
                if profile["verdict_vs_baseline"] == "error":
                    continue

                other_snapshot = snapshots.get(profile["policy_path"])
                if other_snapshot:
                    result = comparer.compare(baseline_snapshot, other_snapshot)
                    raw_verdict = result["verdict"]
                    # verdict 매핑: b_better→improved, a_better→regressed
                    verdict_map = {
                        "b_better": "improved",
                        "a_better": "regressed",
                        "equivalent": "equivalent",
                        "mixed": "mixed",
                    }
                    profile["verdict_vs_baseline"] = verdict_map.get(
                        raw_verdict, raw_verdict
                    )

        # 6. overall verdict
        verdict_counts = {"improved": 0, "regressed": 0, "mixed": 0, "equivalent": 0, "error": 0}
        for p in profiles:
            v = p.get("verdict_vs_baseline")
            if v and v in verdict_counts:
                verdict_counts[v] += 1
        overall = (
            f"{verdict_counts['improved']} improved, "
            f"{verdict_counts['mixed']} mixed, "
            f"{verdict_counts['regressed']} regressed"
        )

        # 7. summary 조립
        scenario_hash = _compute_hash(
            json.dumps(spec, sort_keys=True, ensure_ascii=False)
        )
        summary = {
            "_matrix_version": "1.0.0",
            "scenario_name": spec.get("name", ""),
            "scenario_path": (
                str(Path(scenario_path).resolve()) if scenario_path else ""
            ),
            "scenario_hash": scenario_hash,
            "baseline_policy": baseline_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
            "profiles": profiles,
            "overall_verdict": overall,
        }

        # summary 저장
        summary_path = out_dir / "_matrix_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return summary
