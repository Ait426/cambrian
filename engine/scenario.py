"""Cambrian 경량 시나리오 러너.

JSON spec 파일 1개로 batch run → eval → evolve → promote 추천을
한 사이클로 실행하고 JSON report를 생성한다.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.loop import CambrianEngine

logger = logging.getLogger(__name__)


class ScenarioRunner:
    """JSON spec 기반 시나리오 실행기."""

    def __init__(self, engine: CambrianEngine) -> None:
        """ScenarioRunner를 초기화한다.

        Args:
            engine: CambrianEngine 인스턴스
        """
        self._engine = engine

    def run_scenario(self, spec: dict) -> dict:
        """scenario spec을 실행하고 report를 반환한다.

        Args:
            spec: scenario JSON spec dict

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
    ) -> dict:
        """최종 report dict를 조립한다.

        Args:
            spec: scenario spec
            run_results: batch 실행 결과
            eval_result: eval 결과 (None이면 미실행)
            evolve_result: evolve 결과 (None이면 미실행)
            re_eval_result: re-eval 결과 (None이면 미실행)
            recommendation: promote 추천 (None이면 winner 없음)

        Returns:
            완성된 report dict
        """
        total = len(run_results)
        successes = sum(1 for r in run_results if r["success"])
        success_times = [
            r["execution_time_ms"] for r in run_results if r["success"]
        ]
        avg_time = (
            sum(success_times) // len(success_times) if success_times else 0
        )

        return {
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
