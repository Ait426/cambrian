"""Cambrian matrix decision engine.

matrix summary를 입력으로 champion 선정 + promotion 추천을 산출한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MatrixDecider:
    """matrix summary에서 champion/challenger 판정 + promotion 추천을 산출한다."""

    PROMOTE_MIN_SUCCESS_RATE: float = 0.5
    PROMOTE_MIN_EVAL_PASS_RATE: float = 0.5

    def decide(self, matrix_summary: dict) -> dict:
        """matrix summary를 분석하여 decision report를 반환한다.

        Args:
            matrix_summary: run_matrix() 결과 또는 _matrix_summary.json 내용

        Returns:
            decision report dict

        Raises:
            ValueError: summary 포맷이 유효하지 않을 때
        """
        profiles = matrix_summary.get("profiles")
        if not profiles or not isinstance(profiles, list):
            raise ValueError("Invalid matrix summary: 'profiles' is missing or empty")

        baselines = [p for p in profiles if p.get("is_baseline")]
        if not baselines:
            raise ValueError("Invalid matrix summary: no baseline found")

        # 1. role 부여
        profiles_with_roles = self._assign_roles(profiles)

        # 2. challenger 추출
        challengers = [
            p for p in profiles_with_roles if p["role"] == "challenger"
        ]

        # 3. champion 선정
        champion = self._select_champion(challengers)

        # 4. champion의 role을 "champion"으로 변경
        if champion is not None:
            for p in profiles_with_roles:
                if p["policy_path"] == champion["policy_path"] and p["role"] == "challenger":
                    p["role"] = "champion"
                    break

        # 5. promotion gate
        promotion = self._evaluate_promotion_gate(champion)

        # 6. baseline decision
        baseline_decision = self._determine_baseline_decision(champion)

        # 7. report 조립
        champion_info = None
        if champion is not None:
            champion_info = {
                "policy_path": champion["policy_path"],
                "success_rate": champion.get("success_rate", 0.0),
                "eval_pass_rate": champion.get("eval_pass_rate"),
                "avg_execution_ms": champion.get("avg_execution_ms", 0),
                "selection_reason": champion.get("_selection_reason", ""),
            }

        return {
            "_decision_version": "1.0.0",
            "matrix_summary_path": "",
            "scenario_name": matrix_summary.get("scenario_name", ""),
            "baseline_policy": matrix_summary.get("baseline_policy", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "profiles": profiles_with_roles,
            "champion": champion_info,
            "baseline_decision": baseline_decision,
            "promotion": promotion,
        }

    def _assign_roles(self, profiles: list[dict]) -> list[dict]:
        """각 profile에 role을 부여한다.

        Args:
            profiles: matrix summary의 profiles 리스트

        Returns:
            role이 추가된 profiles 리스트 (원본 수정 없이 복사)
        """
        result: list[dict] = []
        for p in profiles:
            entry = dict(p)
            if entry.get("is_baseline"):
                entry["role"] = "baseline"
            else:
                verdict = entry.get("verdict_vs_baseline")
                role_map = {
                    "improved": "challenger",
                    "equivalent": "equivalent",
                    "regressed": "regressed",
                    "mixed": "mixed",
                    "error": "blocked",
                }
                entry["role"] = role_map.get(verdict, "blocked")
            result.append(entry)
        return result

    def _select_champion(self, challengers: list[dict]) -> dict | None:
        """challenger들 중 champion 1개를 선정한다.

        선정 규칙 (순차 tie-break):
        1차: success_rate 내림차순
        2차: eval_pass_rate 내림차순
        3차: avg_execution_ms 오름차순

        Args:
            challengers: role='challenger'인 profile 리스트

        Returns:
            선정된 champion dict 또는 None
        """
        if not challengers:
            return None

        selected = min(
            challengers,
            key=lambda p: (
                -(p.get("success_rate") or 0),
                -(p.get("eval_pass_rate") or 0),
                (p.get("avg_execution_ms") or 999999),
            ),
        )

        sr = selected.get("success_rate") or 0
        epr = selected.get("eval_pass_rate")
        ms = selected.get("avg_execution_ms") or 0
        epr_str = f"{epr:.2f}" if epr is not None else "N/A"
        selected["_selection_reason"] = (
            f"Selected by ranking: success_rate={sr:.2f}, "
            f"eval_pass_rate={epr_str}, avg_ms={ms}ms"
        )
        return selected

    def _evaluate_promotion_gate(self, champion: dict | None) -> dict:
        """champion의 promotion gate를 평가한다.

        Args:
            champion: 선정된 champion 또는 None

        Returns:
            promotion recommendation dict
        """
        if champion is None:
            return {
                "recommend_promote": False,
                "recommended_policy": None,
                "reason": "No champion found — keep baseline",
            }

        sr = champion.get("success_rate") or 0
        epr = champion.get("eval_pass_rate")
        policy = champion.get("policy_path", "")

        if sr < self.PROMOTE_MIN_SUCCESS_RATE:
            return {
                "recommend_promote": False,
                "recommended_policy": policy,
                "reason": (
                    f"Champion success_rate {sr:.2f} "
                    f"below threshold {self.PROMOTE_MIN_SUCCESS_RATE}"
                ),
            }

        if epr is not None and epr < self.PROMOTE_MIN_EVAL_PASS_RATE:
            return {
                "recommend_promote": False,
                "recommended_policy": policy,
                "reason": (
                    f"Champion eval_pass_rate {epr:.2f} "
                    f"below threshold {self.PROMOTE_MIN_EVAL_PASS_RATE}"
                ),
            }

        epr_str = f"{epr:.2f}" if epr is not None else "N/A"
        return {
            "recommend_promote": True,
            "recommended_policy": policy,
            "reason": (
                f"Champion passed all gates "
                f"(success_rate={sr:.2f}, eval_pass_rate={epr_str})"
            ),
        }

    def _determine_baseline_decision(self, champion: dict | None) -> str:
        """baseline 유지/교체 판정을 결정한다.

        Args:
            champion: 선정된 champion 또는 None

        Returns:
            'replace_with_champion' 또는 'keep_baseline'
        """
        if champion is not None:
            return "replace_with_champion"
        return "keep_baseline"
