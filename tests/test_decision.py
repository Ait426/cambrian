"""Champion/Challenger Decision 테스트 (Task 19).

MatrixDecider의 role 부여, champion 선정, promotion gate,
baseline decision을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.decision import MatrixDecider


def _make_profile(
    policy: str,
    is_baseline: bool = False,
    verdict: str | None = None,
    success_rate: float = 0.8,
    eval_pass_rate: float | None = None,
    avg_ms: int = 100,
    promote_rec: str | None = None,
) -> dict:
    """테스트용 profile dict."""
    return {
        "policy_path": policy,
        "policy_hash": "",
        "is_baseline": is_baseline,
        "snapshot_file": f"{'baseline' if is_baseline else 'profile'}__{Path(policy).stem}.json",
        "success_rate": success_rate,
        "eval_pass_rate": eval_pass_rate,
        "avg_execution_ms": avg_ms,
        "winner_skill": "test_skill",
        "promote_recommendation": promote_rec,
        "verdict_vs_baseline": verdict,
    }


def _make_summary(*profiles: dict, baseline_policy: str = "base.json") -> dict:
    """테스트용 matrix summary dict."""
    return {
        "_matrix_version": "1.0.0",
        "scenario_name": "test",
        "baseline_policy": baseline_policy,
        "profiles": list(profiles),
        "overall_verdict": "",
    }


# === 1. improved 1개 → champion ===

def test_single_improved_is_champion() -> None:
    """improved 1개 → champion으로 선정된다."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("better.json", verdict="improved", success_rate=0.9),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"] is not None
    assert decision["champion"]["policy_path"] == "better.json"


# === 2. improved 2개 → success_rate 높은 쪽 ===

def test_multiple_improved_tiebreak() -> None:
    """improved 2개 → success_rate 높은 쪽이 champion."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="improved", success_rate=0.7),
        _make_profile("b.json", verdict="improved", success_rate=0.9),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"]["policy_path"] == "b.json"


# === 3. success_rate 동점 → eval_pass_rate로 ===

def test_tiebreak_eval_pass_rate() -> None:
    """success_rate 동점 시 eval_pass_rate로 결정."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="improved", success_rate=0.8, eval_pass_rate=0.6),
        _make_profile("b.json", verdict="improved", success_rate=0.8, eval_pass_rate=0.9),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"]["policy_path"] == "b.json"


# === 4. success_rate + eval 동점 → avg_ms 낮은 쪽 ===

def test_tiebreak_avg_ms() -> None:
    """success_rate + eval 동점 시 avg_ms 낮은 쪽."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="improved", success_rate=0.8, eval_pass_rate=0.8, avg_ms=200),
        _make_profile("b.json", verdict="improved", success_rate=0.8, eval_pass_rate=0.8, avg_ms=100),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"]["policy_path"] == "b.json"


# === 5. 전부 equivalent → keep_baseline ===

def test_all_equivalent_keep_baseline() -> None:
    """전부 equivalent → champion 없음, keep_baseline."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="equivalent"),
        _make_profile("b.json", verdict="equivalent"),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"] is None
    assert decision["baseline_decision"] == "keep_baseline"


# === 6. 전부 regressed → keep_baseline ===

def test_all_regressed_keep_baseline() -> None:
    """전부 regressed → keep_baseline."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="regressed"),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"] is None
    assert decision["baseline_decision"] == "keep_baseline"


# === 7. mixed + equivalent만 → champion 없음 ===

def test_mixed_no_champion() -> None:
    """mixed + equivalent만 → champion 없음."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="mixed"),
        _make_profile("b.json", verdict="equivalent"),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"] is None


# === 8. champion gate 통과 ===

def test_champion_gate_pass() -> None:
    """success_rate >= 0.5 + eval >= 0.5 → recommend=True."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("good.json", verdict="improved", success_rate=0.8, eval_pass_rate=0.7),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["promotion"]["recommend_promote"] is True


# === 9. champion gate 실패: success_rate ===

def test_champion_gate_fail_success() -> None:
    """success_rate < 0.5 → recommend=False."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("weak.json", verdict="improved", success_rate=0.3),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["promotion"]["recommend_promote"] is False
    assert "success_rate" in decision["promotion"]["reason"]


# === 10. champion gate 실패: eval ===

def test_champion_gate_fail_eval() -> None:
    """eval_pass_rate < 0.5 → recommend=False."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("bad_eval.json", verdict="improved", success_rate=0.8, eval_pass_rate=0.3),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["promotion"]["recommend_promote"] is False
    assert "eval_pass_rate" in decision["promotion"]["reason"]


# === 11. eval=None → eval gate 스킵 ===

def test_champion_gate_no_eval() -> None:
    """eval=None이면 eval gate를 스킵하고 success만으로 판정."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("no_eval.json", verdict="improved", success_rate=0.7, eval_pass_rate=None),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["promotion"]["recommend_promote"] is True


# === 12. error profile → blocked ===

def test_error_profile_blocked() -> None:
    """verdict=error → role=blocked."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("err.json", verdict="error"),
    )
    decision = MatrixDecider().decide(summary)
    err_profile = [p for p in decision["profiles"] if p["policy_path"] == "err.json"]
    assert err_profile[0]["role"] == "blocked"


# === 13. decision report 구조 ===

def test_decision_report_structure() -> None:
    """decision report에 필수 키가 전부 존재한다."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="improved"),
    )
    decision = MatrixDecider().decide(summary)
    required = {
        "_decision_version", "matrix_summary_path", "scenario_name",
        "baseline_policy", "timestamp", "profiles",
        "champion", "baseline_decision", "promotion",
    }
    assert required.issubset(decision.keys())


# === 14. profiles 없음 → 에러 ===

def test_invalid_summary_no_profiles() -> None:
    """profiles 없음 → ValueError."""
    with pytest.raises(ValueError, match="profiles"):
        MatrixDecider().decide({"scenario_name": "test"})


# === 15. baseline 없음 → 에러 ===

def test_invalid_summary_no_baseline() -> None:
    """baseline이 없는 summary → ValueError."""
    summary = {
        "profiles": [
            _make_profile("a.json", verdict="improved"),
        ],
    }
    with pytest.raises(ValueError, match="baseline"):
        MatrixDecider().decide(summary)


# === 16. champion 있음 → replace_with_champion ===

def test_replace_with_champion_decision() -> None:
    """champion 있음 → baseline_decision = replace_with_champion."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("champ.json", verdict="improved"),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["baseline_decision"] == "replace_with_champion"


# === 17. champion role이 profiles에서 변경됨 ===

def test_champion_role_in_profiles() -> None:
    """champion의 role이 'champion'으로 변경된다."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("champ.json", verdict="improved"),
    )
    decision = MatrixDecider().decide(summary)
    champ_profiles = [p for p in decision["profiles"] if p["policy_path"] == "champ.json"]
    assert champ_profiles[0]["role"] == "champion"


# === 18. selection_reason 존재 ===

def test_selection_reason_present() -> None:
    """champion.selection_reason이 비어있지 않다."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="improved"),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["champion"]["selection_reason"]
    assert len(decision["champion"]["selection_reason"]) > 0


# === 19. promotion reason 존재 ===

def test_promotion_reason_present() -> None:
    """promotion.reason이 비어있지 않다."""
    summary = _make_summary(
        _make_profile("base.json", is_baseline=True),
        _make_profile("a.json", verdict="improved"),
    )
    decision = MatrixDecider().decide(summary)
    assert decision["promotion"]["reason"]
    assert len(decision["promotion"]["reason"]) > 0


# === 20. CLI 출력 ===

def test_cli_happy_path(capsys: pytest.CaptureFixture[str]) -> None:
    """_print_decision_report가 요약을 출력한다."""
    from engine.cli import _print_decision_report

    decision = {
        "scenario_name": "test",
        "baseline_policy": "base.json",
        "profiles": [
            {
                "policy_path": "base.json",
                "role": "baseline",
                "success_rate": 0.6,
                "eval_pass_rate": None,
                "avg_execution_ms": 200,
                "verdict_vs_baseline": None,
            },
            {
                "policy_path": "better.json",
                "role": "champion",
                "success_rate": 0.9,
                "eval_pass_rate": 0.8,
                "avg_execution_ms": 100,
                "verdict_vs_baseline": "improved",
            },
        ],
        "champion": {
            "policy_path": "better.json",
            "success_rate": 0.9,
            "eval_pass_rate": 0.8,
            "avg_execution_ms": 100,
            "selection_reason": "Selected by ranking",
        },
        "baseline_decision": "replace_with_champion",
        "promotion": {
            "recommend_promote": True,
            "recommended_policy": "better.json",
            "reason": "Champion passed all gates",
        },
    }

    _print_decision_report(decision)
    captured = capsys.readouterr().out

    assert "Matrix Decision:" in captured
    assert "champion" in captured.lower()
    assert "RECOMMEND" in captured
    assert "better" in captured
