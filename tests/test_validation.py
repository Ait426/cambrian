"""Baseline Revalidation / Regression Watch 테스트 (Task 23).

load_comparison_basis, compute_verdict, save_validation_record,
CLI adoption validate를 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.validation import (
    ValidationError,
    compute_verdict,
    load_comparison_basis,
    run_fresh_validation,
    save_validation_record,
)


# === T1: eval_snapshot_path → source="eval_snapshot" ===

def test_basis_eval_snapshot(tmp_path: Path) -> None:
    """eval_snapshot_path가 유효하면 source=eval_snapshot."""
    snap = {"success_rate": 0.8, "avg_execution_ms": 100}
    snap_file = tmp_path / "snap.json"
    snap_file.write_text(json.dumps(snap), encoding="utf-8")

    adoption = {"eval_snapshot_path": str(snap_file)}
    result = load_comparison_basis(adoption, str(tmp_path))

    assert result["source"] == "eval_snapshot"
    assert result["basis_metrics"]["success_rate"] == 0.8


# === T2: eval_snapshot 없고 decision_ref 유효 ===

def test_basis_decision_ref(tmp_path: Path) -> None:
    """eval_snapshot 없고 decision_ref가 유효하면 source=decision_ref."""
    decision = {
        "champion": {
            "success_rate": 0.9,
            "eval_pass_rate": 0.85,
            "avg_execution_ms": 150,
        },
    }
    dec_file = tmp_path / "decision.json"
    dec_file.write_text(json.dumps(decision), encoding="utf-8")

    adoption = {"decision_ref": str(dec_file)}
    result = load_comparison_basis(adoption, str(tmp_path))

    assert result["source"] == "decision_ref"
    assert result["basis_metrics"]["success_rate"] == 0.9


# === T3: 둘 다 없고 inline metrics 있음 ===

def test_basis_inline_metrics() -> None:
    """eval_snapshot/decision 없고 inline metrics가 있으면 source=inline_metrics."""
    adoption = {"metrics": {"score": 0.75, "latency_ms": 200}}
    result = load_comparison_basis(adoption)

    assert result["source"] == "inline_metrics"
    assert result["basis_metrics"]["score"] == 0.75


# === T4: 아무것도 없음 → source="none" ===

def test_basis_none() -> None:
    """아무런 basis가 없으면 source=none."""
    adoption = {"skill_id": "test"}
    result = load_comparison_basis(adoption)

    assert result["source"] == "none"
    assert result["basis_metrics"] == {}


# === T5: basis_metrics={} → inconclusive ===

def test_verdict_inconclusive_no_basis() -> None:
    """basis_metrics가 비면 inconclusive."""
    result = compute_verdict({}, {"score": 0.8})
    assert result["verdict"] == "inconclusive"


# === T6: 20% 하락 → regressed ===

def test_verdict_regressed() -> None:
    """20% 하락 → regressed."""
    result = compute_verdict(
        {"score": 1.0},
        {"score": 0.75},
        regression_threshold=0.15,
    )
    assert result["verdict"] == "regressed"
    assert result["recommended_action"] == "consider-rollback"


# === T7: 8% 하락 → watch ===

def test_verdict_watch() -> None:
    """8% 하락 → watch."""
    result = compute_verdict(
        {"score": 1.0},
        {"score": 0.92},
        regression_threshold=0.15,
        watch_threshold=0.05,
    )
    assert result["verdict"] == "watch"
    assert result["recommended_action"] == "re-experiment"


# === T8: 2% 하락 → healthy ===

def test_verdict_healthy() -> None:
    """2% 하락 → healthy."""
    result = compute_verdict(
        {"score": 1.0},
        {"score": 0.98},
        regression_threshold=0.15,
        watch_threshold=0.05,
    )
    assert result["verdict"] == "healthy"
    assert result["recommended_action"] == "maintain"


# === T9: save_validation_record → 파일 생성 ===

def test_save_validation_record(tmp_path: Path) -> None:
    """validation record가 파일로 생성되고 JSON 파싱 가능."""
    record = {
        "schema_version": "1.0",
        "skill_name": "test_skill",
        "verdict": "healthy",
    }

    path = save_validation_record(record, str(tmp_path / "validations"))
    assert Path(path).exists()

    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    assert loaded["verdict"] == "healthy"


# === T10: run_fresh_validation → 실패 시 ValidationError ===

def test_fresh_validation_no_spec() -> None:
    """spec 경로 없으면 ValidationError."""
    with pytest.raises(ValidationError, match="찾을 수 없음"):
        run_fresh_validation(None, None, "test", engine=None)


# === T11: CLI smoke — healthy (compute_verdict 직접 테스트) ===

def test_cli_healthy_verdict() -> None:
    """healthy verdict가 올바르게 산출된다."""
    result = compute_verdict(
        {"success_rate": 0.8, "eval_pass_rate": 0.7},
        {"success_rate": 0.79, "eval_pass_rate": 0.69},
    )
    assert result["verdict"] == "healthy"


# === T12: missing adoption → basis=none ===

def test_missing_adoption_fields() -> None:
    """adoption에 아무 참조 없으면 basis source=none."""
    result = load_comparison_basis({})
    assert result["source"] == "none"


# === T13: RollbackError is Exception ===

def test_validation_error_is_exception() -> None:
    """ValidationError가 Exception 하위 클래스다."""
    assert issubclass(ValidationError, Exception)


# === T14: --spec override ===

def test_spec_override_used(tmp_path: Path) -> None:
    """spec_override가 제공되면 scenario_ref 대신 사용된다."""
    # spec 파일 생성
    spec = {
        "name": "override_test",
        "domain": "utility",
        "tags": ["test"],
        "inputs": [{"text": "hello"}],
    }
    spec_file = tmp_path / "override.json"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")

    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
    )

    result = run_fresh_validation(
        scenario_ref=None,
        spec_override=str(spec_file),
        skill_name="hello_world",
        engine=engine,
    )
    assert "fresh_metrics" in result
    assert result["run_id"].startswith("reval-")
    engine.close()


# === T15: threshold override ===

def test_threshold_override() -> None:
    """regression_threshold를 0.05로 낮추면 watch→regressed 전환."""
    # 8% 하락: 기본(0.15) → healthy/watch, threshold=0.05 → regressed
    result_default = compute_verdict(
        {"score": 1.0}, {"score": 0.92},
        regression_threshold=0.15,
    )
    result_strict = compute_verdict(
        {"score": 1.0}, {"score": 0.92},
        regression_threshold=0.05,
    )
    assert result_default["verdict"] in ("watch", "healthy")
    assert result_strict["verdict"] == "regressed"


# === T16: inconclusive 시 recommended_action ===

def test_inconclusive_recommended_action() -> None:
    """inconclusive → recommended_action=investigate."""
    result = compute_verdict({}, {})
    assert result["verdict"] == "inconclusive"
    assert result["recommended_action"] == "investigate"


# === T17: record에 recommended_action 포함 ===

def test_record_has_recommended_action(tmp_path: Path) -> None:
    """저장된 record에 recommended_action이 포함된다."""
    record = {
        "schema_version": "1.0",
        "skill_name": "test",
        "verdict": "watch",
        "recommended_action": "re-experiment",
    }
    path = save_validation_record(record, str(tmp_path / "val"))
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    assert "recommended_action" in loaded
    assert loaded["recommended_action"] == "re-experiment"


# === T18: latency 증가는 worse ===

def test_latency_increase_is_worse() -> None:
    """avg_execution_ms 증가는 악화 방향."""
    result = compute_verdict(
        {"avg_execution_ms": 100},
        {"avg_execution_ms": 200},
        regression_threshold=0.15,
    )
    deltas = result["metric_deltas"]["avg_execution_ms"]
    assert deltas["direction"] == "worse"
    assert result["verdict"] == "regressed"
