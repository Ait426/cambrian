"""Policy Threshold 외부화 테스트 (Task 25).

decision/promotion/validation threshold의 policy 참조,
merge deep merge, precedence, 기존 동작 보존을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.policy import CambrianPolicy


# === T1: 구형 policy (신규 섹션 없음) → DEFAULT 유지 ===

def test_old_policy_fallback(tmp_path: Path) -> None:
    """신규 섹션 없는 구형 policy → default fallback."""
    old = {"budget": {"max_candidates_per_run": 3}}
    (tmp_path / "old.json").write_text(json.dumps(old), encoding="utf-8")
    policy = CambrianPolicy(tmp_path / "old.json")

    # 신규 섹션은 default
    assert policy.watch_degradation_pct == 0.05
    assert policy.regressed_degradation_pct == 0.15
    assert policy.promotion_min_success_rate == 0.70
    assert policy.fitness_tolerance_pct == 0.05


# === T2: validation.watch만 override → regressed는 default ===

def test_partial_validation_override(tmp_path: Path) -> None:
    """watch만 override, regressed는 default."""
    custom = {"validation": {"watch_degradation_pct": 0.10}}
    (tmp_path / "p.json").write_text(json.dumps(custom), encoding="utf-8")
    policy = CambrianPolicy(tmp_path / "p.json")

    assert policy.watch_degradation_pct == 0.10
    assert policy.regressed_degradation_pct == 0.15  # default


# === T3: 전체 섹션 override ===

def test_full_section_override(tmp_path: Path) -> None:
    """3개 섹션 전체 override."""
    custom = {
        "decision": {"fitness_tolerance_pct": 0.01, "latency_tolerance_pct": 0.20},
        "promotion": {"min_success_rate": 0.90, "min_eval_pass_rate": 0.80},
        "validation": {"watch_degradation_pct": 0.02, "regressed_degradation_pct": 0.08},
    }
    (tmp_path / "p.json").write_text(json.dumps(custom), encoding="utf-8")
    policy = CambrianPolicy(tmp_path / "p.json")

    assert policy.fitness_tolerance_pct == 0.01
    assert policy.latency_tolerance_pct == 0.20
    assert policy.promotion_min_success_rate == 0.90
    assert policy.promotion_min_eval_pass_rate == 0.80
    assert policy.watch_degradation_pct == 0.02
    assert policy.regressed_degradation_pct == 0.08


# === T4: precedence (to_dict에 반영 확인) ===

def test_precedence_reflects_in_to_dict(tmp_path: Path) -> None:
    """policy 파일 값이 to_dict에 반영된다."""
    custom = {"promotion": {"min_success_rate": 0.99}}
    (tmp_path / "p.json").write_text(json.dumps(custom), encoding="utf-8")
    policy = CambrianPolicy(tmp_path / "p.json")
    d = policy.to_dict()

    assert d["promotion"]["min_success_rate"] == 0.99
    assert d["promotion"]["min_eval_pass_rate"] == 0.60  # default


# === T5: compute_verdict policy=None → default threshold ===

def test_verdict_default_threshold() -> None:
    """policy=None → default threshold 사용."""
    from engine.validation import compute_verdict
    result = compute_verdict(
        {"score": 1.0}, {"score": 0.88},
        policy=None,
    )
    # 12% 하락: watch (5%~15%)
    assert result["verdict"] == "watch"
    assert result["applied_thresholds"]["regressed_degradation_pct"] == 0.15


# === T6: policy regressed_degradation_pct=0.05 → 5% 하락으로 regressed ===

def test_verdict_policy_strict() -> None:
    """regressed 임계값을 0.05로 낮추면 8% 하락이 regressed."""
    from engine.validation import compute_verdict
    strict_policy = {"validation": {"regressed_degradation_pct": 0.05, "watch_degradation_pct": 0.02}}
    result = compute_verdict(
        {"score": 1.0}, {"score": 0.92},
        policy=strict_policy,
    )
    assert result["verdict"] == "regressed"


# === T7: conservative vs aggressive policy → verdict 다름 ===

def test_conservative_vs_aggressive_verdict() -> None:
    """보수적 vs 공격적 policy → 동일 입력에 다른 verdict."""
    from engine.validation import compute_verdict

    conservative = {"validation": {"watch_degradation_pct": 0.02, "regressed_degradation_pct": 0.05}}
    aggressive = {"validation": {"watch_degradation_pct": 0.20, "regressed_degradation_pct": 0.40}}

    # 10% 하락
    basis = {"score": 1.0}
    fresh = {"score": 0.90}

    con_result = compute_verdict(basis, fresh, policy=conservative)
    agg_result = compute_verdict(basis, fresh, policy=aggressive)

    assert con_result["verdict"] == "regressed"  # 10% > 5%
    assert agg_result["verdict"] == "healthy"    # 10% < 20%


# === T8: promotion gate min_success_rate=0.9 → 0.8 차단 ===

def test_promotion_gate_strict() -> None:
    """min_success_rate=0.9 → 0.8 성공률 차단."""
    from engine.decision import MatrixDecider

    decider = MatrixDecider()
    champion = {"success_rate": 0.8, "eval_pass_rate": 0.8, "policy_path": "x"}
    strict = {"promotion": {"min_success_rate": 0.9, "min_eval_pass_rate": 0.6}}

    result = decider._evaluate_promotion_gate(champion, policy=strict)
    assert result["recommend_promote"] is False
    assert "0.90" in result["reason"] or "0.9" in result["reason"]


# === T9: promotion gate min_success_rate=0.5 → 0.8 통과 ===

def test_promotion_gate_lenient() -> None:
    """min_success_rate=0.5 → 0.8 통과."""
    from engine.decision import MatrixDecider

    decider = MatrixDecider()
    champion = {"success_rate": 0.8, "eval_pass_rate": 0.8, "policy_path": "x"}
    lenient = {"promotion": {"min_success_rate": 0.5, "min_eval_pass_rate": 0.5}}

    result = decider._evaluate_promotion_gate(champion, policy=lenient)
    assert result["recommend_promote"] is True


# === T10: decision fitness_tolerance_pct (구조 확인) ===

def test_decision_tolerance_in_policy() -> None:
    """policy에 decision 섹션이 포함된다."""
    policy = CambrianPolicy()
    assert policy.fitness_tolerance_pct == 0.05
    assert policy.latency_tolerance_pct == 0.10

    d = policy.to_dict()
    assert "decision" in d
    assert d["decision"]["fitness_tolerance_pct"] == 0.05


# === T11: validation record에 applied_thresholds ===

def test_verdict_has_applied_thresholds() -> None:
    """compute_verdict 결과에 applied_thresholds 필드 포함."""
    from engine.validation import compute_verdict
    result = compute_verdict({"score": 0.8}, {"score": 0.7})
    assert "applied_thresholds" in result
    assert "watch_degradation_pct" in result["applied_thresholds"]
    assert "regressed_degradation_pct" in result["applied_thresholds"]


# === T12: resolved policy에 신규 섹션 포함 ===

def test_resolved_policy_has_all_sections() -> None:
    """to_dict()에 decision/promotion/validation 섹션 포함."""
    policy = CambrianPolicy()
    d = policy.to_dict()
    assert "decision" in d
    assert "promotion" in d
    assert "validation" in d
    assert d["validation"]["watch_degradation_pct"] == 0.05


# === T13: CLI smoke — 기존 동작 유지 확인 ===

def test_default_policy_backward_compatible() -> None:
    """DEFAULT_POLICY가 기존 필드를 보존한다."""
    policy = CambrianPolicy()
    # 기존 Task 16 필드
    assert policy.max_candidates_per_run == 5
    assert policy.promote_min_executions == 10
    assert policy.adoption_margin == 0.5
    # 신규 필드
    assert policy.watch_degradation_pct == 0.05


# === T14: inconclusive도 applied_thresholds 포함 ===

def test_inconclusive_has_thresholds() -> None:
    """inconclusive verdict도 applied_thresholds를 포함한다."""
    from engine.validation import compute_verdict
    result = compute_verdict({}, {})
    assert result["verdict"] == "inconclusive"
    assert "applied_thresholds" in result


# === T15: 경계값: watch_threshold 정확히 → watch ===

def test_boundary_watch() -> None:
    """delta == watch_threshold → watch 판정."""
    from engine.validation import compute_verdict
    # 정확히 5% 하락
    result = compute_verdict(
        {"score": 1.0}, {"score": 0.95},
        policy={"validation": {"watch_degradation_pct": 0.05, "regressed_degradation_pct": 0.15}},
    )
    assert result["verdict"] == "watch"


# === T16: 경계값: regressed_threshold 정확히 → regressed ===

def test_boundary_regressed() -> None:
    """delta == regressed_threshold → regressed 판정."""
    from engine.validation import compute_verdict
    # 정확히 15% 하락
    result = compute_verdict(
        {"score": 1.0}, {"score": 0.85},
        policy={"validation": {"watch_degradation_pct": 0.05, "regressed_degradation_pct": 0.15}},
    )
    assert result["verdict"] == "regressed"
