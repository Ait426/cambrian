"""Cambrian 스냅샷 비교 도구.

두 scenario 실행 snapshot을 비교하여
지표 차이와 verdict를 생성한다.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SnapshotComparer:
    """두 snapshot JSON을 비교하여 요약을 생성한다."""

    def compare(self, snapshot_a: dict, snapshot_b: dict) -> dict:
        """두 snapshot을 비교한다.

        Args:
            snapshot_a: 기준 snapshot (A)
            snapshot_b: 비교 대상 snapshot (B)

        Returns:
            비교 결과 dict (deltas, verdict, summary 포함)
        """
        # 컨텍스트 정보 추출
        ctx_a = snapshot_a.get("_context", {})
        ctx_b = snapshot_b.get("_context", {})

        if not ctx_a:
            logger.warning("Snapshot A에 _context 없음 (구버전 report)")
        if not ctx_b:
            logger.warning("Snapshot B에 _context 없음 (구버전 report)")

        # 메트릭 추출 + 비교
        metrics_a = self._extract_metrics(snapshot_a)
        metrics_b = self._extract_metrics(snapshot_b)
        deltas = self._compute_deltas(metrics_a, metrics_b)
        verdict = self._determine_verdict(deltas)

        summary = self._build_summary(verdict, deltas)

        return {
            "snapshot_a": {
                "scenario_name": snapshot_a.get("scenario_name", ""),
                "scenario_hash": ctx_a.get("scenario_hash", ""),
                "policy_source": ctx_a.get("policy_source", "unknown"),
                "policy_hash": ctx_a.get("policy_hash", ""),
                "timestamp": ctx_a.get("timestamp", snapshot_a.get("timestamp", "")),
                "notes": ctx_a.get("notes", ""),
            },
            "snapshot_b": {
                "scenario_name": snapshot_b.get("scenario_name", ""),
                "scenario_hash": ctx_b.get("scenario_hash", ""),
                "policy_source": ctx_b.get("policy_source", "unknown"),
                "policy_hash": ctx_b.get("policy_hash", ""),
                "timestamp": ctx_b.get("timestamp", snapshot_b.get("timestamp", "")),
                "notes": ctx_b.get("notes", ""),
            },
            "metrics_a": metrics_a,
            "metrics_b": metrics_b,
            "deltas": deltas,
            "verdict": verdict,
            "summary": summary,
        }

    def _extract_metrics(self, snapshot: dict) -> dict:
        """snapshot에서 비교 가능한 핵심 지표를 추출한다.

        Args:
            snapshot: scenario run report dict

        Returns:
            핵심 지표 dict
        """
        return {
            "total_inputs": snapshot.get("total_inputs", 0),
            "successful_inputs": snapshot.get("successful_inputs", 0),
            "success_rate": snapshot.get("success_rate", 0.0),
            "avg_execution_ms": snapshot.get("avg_execution_ms", 0),
            "winner_skill": snapshot.get("winner_skill"),
            "eval_pass_rate": self._safe_nested(
                snapshot, "eval_result", "pass_rate",
            ),
            "eval_verdict": self._safe_nested(
                snapshot, "eval_result", "verdict",
            ),
            "promote_eligible": self._safe_nested(
                snapshot, "promote_recommendation", "eligible",
            ),
            "promote_recommendation": self._safe_nested(
                snapshot, "promote_recommendation", "recommendation",
            ),
            "evolve_adopted": self._safe_nested(
                snapshot, "evolve_result", "adopted",
            ),
        }

    def _safe_nested(self, d: dict, *keys: str) -> Any:
        """중첩 dict에서 안전하게 값을 추출한다.

        Args:
            d: 대상 dict
            *keys: 순차 접근할 키들

        Returns:
            값 또는 None
        """
        current: Any = d
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _compute_deltas(self, a: dict, b: dict) -> dict:
        """두 metrics의 수치 차이를 계산한다.

        Args:
            a: metrics A
            b: metrics B

        Returns:
            각 지표별 {a, b, diff} 또는 {a, b, changed}
        """
        deltas: dict = {}

        # 수치 지표
        for key in (
            "total_inputs", "successful_inputs",
            "success_rate", "avg_execution_ms",
        ):
            va = a.get(key, 0) or 0
            vb = b.get(key, 0) or 0
            deltas[key] = {"a": va, "b": vb, "diff": round(vb - va, 4)}

        # eval_pass_rate
        epa = a.get("eval_pass_rate") or 0
        epb = b.get("eval_pass_rate") or 0
        deltas["eval_pass_rate"] = {
            "a": epa, "b": epb, "diff": round(epb - epa, 4),
        }

        # 범주형 변화
        for key in ("winner_skill", "promote_recommendation", "eval_verdict"):
            deltas[key] = {
                "a": a.get(key),
                "b": b.get(key),
                "changed": a.get(key) != b.get(key),
            }

        return deltas

    def _determine_verdict(self, deltas: dict) -> str:
        """전체 비교 판정을 결정한다.

        B가 A보다 나은 방향: success_rate↑, eval_pass_rate↑, avg_execution_ms↓.

        Args:
            deltas: _compute_deltas() 결과

        Returns:
            'a_better' | 'b_better' | 'equivalent' | 'mixed'
        """
        b_better = 0
        a_better = 0

        sr_diff = deltas["success_rate"]["diff"]
        if sr_diff > 0:
            b_better += 1
        elif sr_diff < 0:
            a_better += 1

        ep_diff = deltas["eval_pass_rate"]["diff"]
        if ep_diff > 0:
            b_better += 1
        elif ep_diff < 0:
            a_better += 1

        ms_diff = deltas["avg_execution_ms"]["diff"]
        if ms_diff < 0:
            b_better += 1
        elif ms_diff > 0:
            a_better += 1

        if b_better > a_better:
            return "b_better"
        if a_better > b_better:
            return "a_better"
        if b_better == 0 and a_better == 0:
            return "equivalent"
        return "mixed"

    def _build_summary(self, verdict: str, deltas: dict) -> str:
        """사람이 읽을 수 있는 1줄 요약을 생성한다.

        Args:
            verdict: 판정 결과
            deltas: 차이 dict

        Returns:
            요약 문자열
        """
        labels = {
            "a_better": "A가 우세",
            "b_better": "B가 우세",
            "equivalent": "동등",
            "mixed": "혼합 (지표별 상이)",
        }
        return labels.get(verdict, verdict)

    def format_comparison(self, comparison: dict) -> str:
        """비교 결과를 사람이 읽기 좋은 문자열로 포맷한다.

        Args:
            comparison: compare() 결과

        Returns:
            포맷된 문자열
        """
        lines: list[str] = []
        sa = comparison["snapshot_a"]
        sb = comparison["snapshot_b"]
        deltas = comparison["deltas"]
        verdict = comparison["verdict"]

        lines.append("Snapshot Comparison")
        lines.append("═" * 50)

        # A 정보
        lines.append(f"\nA: {sa['policy_source']} ({sa['timestamp'][:16]})")
        lines.append(
            f"   scenario: {sa['scenario_name']} [{sa['scenario_hash']}]"
        )

        # B 정보
        same_scenario = sa["scenario_hash"] == sb["scenario_hash"]
        lines.append(f"\nB: {sb['policy_source']} ({sb['timestamp'][:16]})")
        same_mark = "  ← same" if (same_scenario and sa["scenario_hash"]) else ""
        lines.append(
            f"   scenario: {sb['scenario_name']} [{sb['scenario_hash']}]{same_mark}"
        )

        # 지표 비교 테이블
        lines.append("")
        lines.append("─" * 50)
        lines.append("Metric Comparison")
        lines.append("─" * 50)
        lines.append(f"{'METRIC':<22} {'A':>10} {'B':>10} {'DIFF':>10}")

        # success_rate
        sr = deltas["success_rate"]
        arrow = self._diff_arrow(sr["diff"], higher_better=True)
        lines.append(
            f"{'success_rate':<22} {sr['a']*100:>9.1f}% {sr['b']*100:>9.1f}% "
            f"{sr['diff']*100:>+9.1f}% {arrow}"
        )

        # eval_pass_rate
        ep = deltas["eval_pass_rate"]
        arrow = self._diff_arrow(ep["diff"], higher_better=True)
        lines.append(
            f"{'eval_pass_rate':<22} {ep['a']*100:>9.1f}% {ep['b']*100:>9.1f}% "
            f"{ep['diff']*100:>+9.1f}% {arrow}"
        )

        # avg_execution_ms
        ms = deltas["avg_execution_ms"]
        arrow = self._diff_arrow(ms["diff"], higher_better=False)
        lines.append(
            f"{'avg_execution_ms':<22} {ms['a']:>8}ms {ms['b']:>8}ms "
            f"{ms['diff']:>+8}ms {arrow}"
        )

        # winner_skill
        ws = deltas["winner_skill"]
        ws_status = "(same)" if not ws["changed"] else "(changed)"
        lines.append(
            f"{'winner_skill':<22} {str(ws['a'] or '-'):>10} "
            f"{str(ws['b'] or '-'):>10} {ws_status:>10}"
        )

        # promote_recommendation
        pr = deltas["promote_recommendation"]
        pr_status = "(same)" if not pr["changed"] else "(changed)"
        lines.append(
            f"{'promote':<22} {str(pr['a'] or '-'):>10} "
            f"{str(pr['b'] or '-'):>10} {pr_status:>10}"
        )

        # Verdict
        lines.append("")
        lines.append("─" * 50)
        lines.append(f"Verdict: {verdict} ({comparison['summary']})")
        lines.append("")
        lines.append(
            "Note: LLM-based operations are nondeterministic."
        )

        return "\n".join(lines)

    @staticmethod
    def _diff_arrow(diff: float, *, higher_better: bool) -> str:
        """차이 방향에 따라 화살표를 반환한다.

        Args:
            diff: B - A 차이값
            higher_better: True면 증가가 개선

        Returns:
            '↑' (개선), '↓' (악화), '' (동일)
        """
        if diff == 0:
            return ""
        if higher_better:
            return "↑" if diff > 0 else "↓"
        return "↑" if diff < 0 else "↓"
