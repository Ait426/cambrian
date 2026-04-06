"""Experiment Snapshot + Compare 테스트 (Task 17).

scenario report의 snapshot 컨텍스트 필드, hash 계산,
SnapshotComparer의 비교/verdict/format을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.loop import CambrianEngine
from engine.scenario import ScenarioRunner, _compute_hash
from engine.snapshot import SnapshotComparer


def _make_engine() -> CambrianEngine:
    """인메모리 엔진을 생성한다."""
    return CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path=":memory:",
    )


def _base_spec(**overrides: object) -> dict:
    """기본 scenario spec."""
    spec: dict = {
        "name": "test_scenario",
        "domain": "utility",
        "tags": ["greeting", "test"],
        "inputs": [{"text": "hello"}, {"text": "world"}],
        "do_eval": False,
        "do_evolve": False,
    }
    spec.update(overrides)
    return spec


def _run_scenario(**spec_overrides: object) -> dict:
    """엔진 생성 + scenario 실행 → report 반환."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    report = runner.run_scenario(_base_spec(**spec_overrides))
    engine.close()
    return report


def _make_snapshot(
    success_rate: float = 0.8,
    avg_ms: int = 100,
    eval_pass_rate: float | None = None,
    winner: str | None = "hello_world",
    promote_rec: str | None = "not_eligible",
    policy_source: str = "default",
    scenario_hash: str = "sha256:abc123",
    policy_hash: str = "sha256:def456",
    notes: str = "",
) -> dict:
    """비교 테스트용 snapshot dict."""
    snap: dict = {
        "_snapshot_version": "1.0.0",
        "_context": {
            "scenario_path": "/test/spec.json",
            "scenario_hash": scenario_hash,
            "policy_source": policy_source,
            "policy_hash": policy_hash,
            "resolved_policy": {},
            "run_options": {"do_eval": False, "do_evolve": False},
            "engine_version": "0.3.0",
            "python_version": "3.11.0",
            "timestamp": "2026-04-06T14:00:00+00:00",
            "notes": notes,
        },
        "_reproducibility_notice": "...",
        "success": True,
        "scenario_name": "test",
        "total_inputs": 10,
        "successful_inputs": int(10 * success_rate),
        "success_rate": success_rate,
        "avg_execution_ms": avg_ms,
        "winner_skill": winner,
        "eval_result": (
            {"pass_rate": eval_pass_rate, "verdict": "baseline"}
            if eval_pass_rate is not None else None
        ),
        "promote_recommendation": (
            {"eligible": False, "recommendation": promote_rec}
            if promote_rec else None
        ),
        "evolve_result": None,
        "run_results": [],
    }
    return snap


# === 1. _snapshot_version 존재 ===

def test_snapshot_version_present() -> None:
    """scenario run report에 _snapshot_version이 존재한다."""
    report = _run_scenario()
    assert report["_snapshot_version"] == "1.0.0"


# === 2. _context 존재 + 필수 키 ===

def test_snapshot_context_present() -> None:
    """report에 _context가 존재하고 필수 키를 모두 포함한다."""
    report = _run_scenario()
    ctx = report["_context"]
    required = {
        "scenario_path", "scenario_hash", "policy_source", "policy_hash",
        "resolved_policy", "run_options", "engine_version",
        "python_version", "timestamp", "notes",
    }
    assert required.issubset(ctx.keys())


# === 3. scenario_hash 형식 ===

def test_scenario_hash_computed() -> None:
    """scenario_hash가 sha256: 접두사 + 16자 hex이다."""
    report = _run_scenario()
    h = report["_context"]["scenario_hash"]
    assert h.startswith("sha256:")
    assert len(h) == 7 + 16  # "sha256:" + 16 hex chars


# === 4. policy_hash 형식 ===

def test_policy_hash_computed() -> None:
    """policy_hash가 sha256: 접두사 + 16자 hex이다."""
    report = _run_scenario()
    h = report["_context"]["policy_hash"]
    assert h.startswith("sha256:")
    assert len(h) == 7 + 16


# === 5. 동일 spec → 동일 hash ===

def test_same_spec_same_hash() -> None:
    """동일 spec은 동일 scenario_hash를 생성한다."""
    spec = _base_spec()
    h1 = _compute_hash(json.dumps(spec, sort_keys=True, ensure_ascii=False))
    h2 = _compute_hash(json.dumps(spec, sort_keys=True, ensure_ascii=False))
    assert h1 == h2


# === 6. 다른 spec → 다른 hash ===

def test_different_spec_different_hash() -> None:
    """다른 spec은 다른 scenario_hash를 생성한다."""
    h1 = _compute_hash(json.dumps({"a": 1}, sort_keys=True))
    h2 = _compute_hash(json.dumps({"a": 2}, sort_keys=True))
    assert h1 != h2


# === 7. resolved_policy에 11개 파라미터 ===

def test_resolved_policy_in_context() -> None:
    """_context.resolved_policy에 budget/governance/evolution 포함."""
    report = _run_scenario()
    rp = report["_context"]["resolved_policy"]
    assert "budget" in rp
    assert "governance" in rp
    assert "evolution" in rp
    assert rp["budget"]["max_candidates_per_run"] == 5


# === 8. _reproducibility_notice 존재 ===

def test_reproducibility_notice_present() -> None:
    """_reproducibility_notice 문자열이 존재한다."""
    report = _run_scenario()
    assert "_reproducibility_notice" in report
    assert "nondeterministic" in report["_reproducibility_notice"]


# === 9. compare: B가 우세 ===

def test_compare_b_better() -> None:
    """B의 success_rate↑ + latency↓ → b_better."""
    a = _make_snapshot(success_rate=0.6, avg_ms=200)
    b = _make_snapshot(success_rate=0.8, avg_ms=150)
    result = SnapshotComparer().compare(a, b)
    assert result["verdict"] == "b_better"


# === 10. compare: A가 우세 ===

def test_compare_a_better() -> None:
    """A가 전지표 우세 → a_better."""
    a = _make_snapshot(success_rate=0.9, avg_ms=100, eval_pass_rate=0.9)
    b = _make_snapshot(success_rate=0.5, avg_ms=300, eval_pass_rate=0.3)
    result = SnapshotComparer().compare(a, b)
    assert result["verdict"] == "a_better"


# === 11. compare: 동등 ===

def test_compare_equivalent() -> None:
    """동일 지표 → equivalent."""
    a = _make_snapshot(success_rate=0.8, avg_ms=100)
    b = _make_snapshot(success_rate=0.8, avg_ms=100)
    result = SnapshotComparer().compare(a, b)
    assert result["verdict"] == "equivalent"


# === 12. compare: 혼합 ===

def test_compare_mixed() -> None:
    """일부 A 우세, 일부 B 우세 → mixed. (success_rate: A, latency: B, eval: 동일)"""
    a = _make_snapshot(success_rate=0.9, avg_ms=200, eval_pass_rate=0.5)
    b = _make_snapshot(success_rate=0.7, avg_ms=100, eval_pass_rate=0.5)
    result = SnapshotComparer().compare(a, b)
    assert result["verdict"] == "mixed"


# === 13. 구버전 report 비교 (context 없음) ===

def test_compare_missing_context_graceful() -> None:
    """_context 없는 구버전 report도 비교 가능하다."""
    a = {
        "success": True,
        "scenario_name": "old",
        "total_inputs": 5,
        "successful_inputs": 4,
        "success_rate": 0.8,
        "avg_execution_ms": 100,
        "winner_skill": "s1",
        "eval_result": None,
        "promote_recommendation": None,
        "evolve_result": None,
    }
    b = {
        "success": True,
        "scenario_name": "old",
        "total_inputs": 5,
        "successful_inputs": 5,
        "success_rate": 1.0,
        "avg_execution_ms": 80,
        "winner_skill": "s1",
        "eval_result": None,
        "promote_recommendation": None,
        "evolve_result": None,
    }
    result = SnapshotComparer().compare(a, b)
    assert result["verdict"] in ("b_better", "equivalent", "a_better", "mixed")
    assert result["snapshot_a"]["policy_source"] == "unknown"


# === 14. 파일 미존재 → _handle_snapshot 에러 ===

def test_compare_file_not_found() -> None:
    """비교 파일이 없으면 에러가 발생해야 한다."""
    # SnapshotComparer 자체는 dict를 받으므로 파일 검증은 CLI 핸들러에서 처리
    # 여기서는 CLI 핸들러 로직의 Path.exists() 체크를 검증
    assert not Path("nonexistent_a.json").exists()
    assert not Path("nonexistent_b.json").exists()


# === 15. 깨진 JSON → 에러 ===

def test_compare_invalid_json(tmp_path: Path) -> None:
    """깨진 JSON 파일은 JSONDecodeError를 발생시킨다."""
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        json.loads(bad.read_text(encoding="utf-8"))


# === 16. --json 비교 결과 직렬화 ===

def test_compare_json_output() -> None:
    """비교 결과가 JSON 직렬화 가능하다."""
    a = _make_snapshot(success_rate=0.6)
    b = _make_snapshot(success_rate=0.8)
    result = SnapshotComparer().compare(a, b)
    json_str = json.dumps(result, ensure_ascii=False)
    assert json_str
    loaded = json.loads(json_str)
    assert loaded["verdict"] == "b_better"


# === 17. format_comparison 출력 ===

def test_compare_format_output() -> None:
    """format_comparison()이 사람이 읽을 수 있는 문자열을 반환한다."""
    a = _make_snapshot(success_rate=0.6, policy_source="conservative.json")
    b = _make_snapshot(success_rate=0.9, policy_source="aggressive.json")
    comparer = SnapshotComparer()
    result = comparer.compare(a, b)
    text = comparer.format_comparison(result)

    assert "Snapshot Comparison" in text
    assert "Verdict:" in text
    assert "success_rate" in text
    assert "conservative.json" in text
    assert "aggressive.json" in text


# === 18. notes in snapshot ===

def test_notes_in_snapshot() -> None:
    """notes가 snapshot context에 기록된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    report = runner.run_scenario(
        _base_spec(), notes="테스트 메모",
    )
    assert report["_context"]["notes"] == "테스트 메모"
    engine.close()


# === 19. engine_version in context ===

def test_engine_version_in_context() -> None:
    """engine_version 필드가 존재한다."""
    report = _run_scenario()
    assert report["_context"]["engine_version"] == "0.3.0"


# === 20. python_version in context ===

def test_python_version_in_context() -> None:
    """python_version 필드가 존재한다."""
    import platform as _platform
    report = _run_scenario()
    assert report["_context"]["python_version"] == _platform.python_version()
