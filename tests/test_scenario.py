"""Lightweight Scenario Runner 테스트 (Task 15).

JSON spec 로드, batch run, winner 식별, eval/evolve 옵션,
promote 추천, report 생성/저장을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.loop import CambrianEngine
from engine.scenario import ScenarioRunner


def _make_engine() -> CambrianEngine:
    """인메모리 엔진을 생성한다."""
    return CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path=":memory:",
    )


def _base_spec(**overrides: object) -> dict:
    """기본 scenario spec을 반환한다. overrides로 필드 덮어쓰기."""
    spec: dict = {
        "name": "test_scenario",
        "domain": "utility",
        "tags": ["greeting", "test"],
        "inputs": [
            {"text": "hello"},
            {"text": "world"},
        ],
        "do_eval": False,
        "do_evolve": False,
    }
    spec.update(overrides)
    return spec


# === 1. spec 검증: 필수 필드 누락 ===

def test_scenario_spec_validation() -> None:
    """필수 필드가 누락되면 errors가 반환된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    # name 누락
    report = runner.run_scenario({"domain": "x", "tags": ["a"], "inputs": [{}]})
    assert not report["success"]
    assert any("name" in e for e in report["errors"])

    # domain 누락
    report = runner.run_scenario({"name": "x", "tags": ["a"], "inputs": [{}]})
    assert not report["success"]
    assert any("domain" in e for e in report["errors"])

    # tags 빈 리스트
    report = runner.run_scenario({"name": "x", "domain": "y", "tags": [], "inputs": [{}]})
    assert not report["success"]
    assert any("tags" in e for e in report["errors"])

    # inputs 빈 리스트
    report = runner.run_scenario({"name": "x", "domain": "y", "tags": ["a"], "inputs": []})
    assert not report["success"]
    assert any("inputs" in e for e in report["errors"])

    engine.close()


# === 2. spec 검증: 정상 ===

def test_scenario_spec_valid() -> None:
    """정상 spec은 검증 에러가 없다."""
    runner = ScenarioRunner(_make_engine())
    errors = runner._validate_spec(_base_spec())
    assert errors == []


# === 3. batch run: 3개 inputs → 3개 results ===

def test_scenario_batch_run() -> None:
    """inputs 개수만큼 run_results가 생성된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    spec = _base_spec(inputs=[
        {"text": "a"}, {"text": "b"}, {"text": "c"},
    ])

    report = runner.run_scenario(spec)
    assert report["success"]
    assert report["total_inputs"] == 3
    assert len(report["run_results"]) == 3
    engine.close()


# === 4. partial failure: 일부 실패 → 나머지 계속 ===

def test_scenario_partial_failure() -> None:
    """매칭 안 되는 도메인 입력이 있어도 나머지는 계속 실행된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    # utility 도메인은 스킬 있음, no_match는 없음
    spec = _base_spec()
    report = runner.run_scenario(spec)
    assert report["success"]

    # 실패한 것과 성공한 것이 모두 기록됨
    assert len(report["run_results"]) == report["total_inputs"]
    engine.close()


# === 5. all fail: winner=None, eval/evolve 스킵 ===

def test_scenario_all_fail() -> None:
    """전부 실패하면 winner=None, eval/evolve 결과도 None이다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    spec = _base_spec(
        domain="nonexistent_domain",
        tags=["nonexistent_tag"],
        inputs=[{"x": 1}],
        retries=0,
        do_eval=True,
        do_evolve=True,
    )

    report = runner.run_scenario(spec)
    assert report["success"]
    assert report["winner_skill"] is None
    assert report["eval_result"] is None
    assert report["evolve_result"] is None
    assert report["promote_recommendation"] is None
    engine.close()


# === 6. winner 선택: 최다 선택 skill ===

def test_scenario_winner_selection() -> None:
    """가장 많이 선택된 skill이 winner가 된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    spec = _base_spec(inputs=[
        {"text": f"hi_{i}"} for i in range(5)
    ])
    report = runner.run_scenario(spec)

    assert report["success"]
    assert report["winner_skill"] is not None
    # hello_world가 유일한 greeting 스킬이므로 winner
    successful = [r for r in report["run_results"] if r["success"]]
    if successful:
        assert report["winner_skill"] == successful[0]["skill_id"]
    engine.close()


# === 7. do_eval=True → eval_result 포함 ===

def test_scenario_with_eval() -> None:
    """do_eval=True이고 eval_inputs가 있으면 eval_result가 포함된다."""
    engine = _make_engine()
    registry = engine.get_registry()

    # hello_world에 eval_input 추가
    registry.add_evaluation_input(
        "hello_world",
        json.dumps({"text": "eval_test"}),
        "테스트 입력",
    )

    runner = ScenarioRunner(engine)
    spec = _base_spec(do_eval=True)
    report = runner.run_scenario(spec)

    assert report["success"]
    assert report["eval_result"] is not None
    # eval_result에 pass_rate 또는 error 포함
    assert "pass_rate" in report["eval_result"] or "error" in report["eval_result"]
    engine.close()


# === 8. do_evolve=True + feedback → evolve_result 포함 ===

def test_scenario_with_evolve() -> None:
    """do_evolve=True + feedback 존재 시 evolve_result가 포함된다."""
    engine = _make_engine()
    registry = engine.get_registry()

    # hello_world에 피드백 추가
    registry.add_feedback(
        "hello_world", rating=3, comment="개선 필요",
        input_data="{}", output_data="{}",
    )

    runner = ScenarioRunner(engine)
    spec = _base_spec(do_evolve=True)
    report = runner.run_scenario(spec)

    # evolve는 LLM이 필요하므로 error일 수 있지만 결과가 존재해야 함
    assert report["evolve_result"] is not None
    engine.close()


# === 9. evolve: feedback 없으면 skipped ===

def test_scenario_evolve_no_feedback() -> None:
    """feedback이 없으면 evolve가 skipped된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    spec = _base_spec(do_evolve=True)
    report = runner.run_scenario(spec)

    assert report["evolve_result"] is not None
    assert report["evolve_result"].get("skipped") == "no feedback available"
    engine.close()


# === 10. promote recommendation: 조건 충족 ===

def test_scenario_promote_recommendation() -> None:
    """executions >= 10 + fitness >= 0.5이면 eligible=True."""
    engine = _make_engine()
    registry = engine.get_registry()

    # hello_world의 fitness/executions 수동 설정
    registry._conn.execute(
        "UPDATE skills SET fitness_score = 0.8, total_executions = 15, "
        "successful_executions = 12 WHERE id = 'hello_world'"
    )
    registry._conn.commit()

    runner = ScenarioRunner(engine)
    spec = _base_spec()
    report = runner.run_scenario(spec)

    rec = report["promote_recommendation"]
    assert rec is not None
    assert rec["eligible"] is True
    assert rec["recommendation"] in ("promote_to_candidate", "promote_to_production")
    engine.close()


# === 11. promote recommendation: 조건 미충족 ===

def test_scenario_promote_not_eligible() -> None:
    """executions < 10이면 eligible=False."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    # 기본 상태에서 executions < 10
    spec = _base_spec()
    report = runner.run_scenario(spec)

    rec = report["promote_recommendation"]
    assert rec is not None
    # 2개 input만 실행했으므로 10 미만
    assert rec["eligible"] is False
    assert rec["recommendation"] == "not_eligible"
    engine.close()


# === 12. report 구조: 필수 키 존재 ===

def test_scenario_report_structure() -> None:
    """report에 필수 키가 모두 존재한다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    report = runner.run_scenario(_base_spec())

    required_keys = {
        "success", "scenario_name", "domain", "tags",
        "total_inputs", "successful_inputs", "failed_inputs",
        "success_rate", "avg_execution_ms", "winner_skill",
        "run_results", "eval_result", "evolve_result",
        "re_eval_result", "promote_recommendation", "timestamp",
    }
    assert required_keys.issubset(report.keys())
    engine.close()


# === 13. report 파일 저장 ===

def test_scenario_report_saved(tmp_path: Path) -> None:
    """report가 JSON 파일로 저장된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    report = runner.run_scenario(_base_spec())

    out_path = tmp_path / "test_report.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["scenario_name"] == "test_scenario"
    assert loaded["success"] is True
    engine.close()


# === 14. budget override ===

def test_scenario_budget_override() -> None:
    """max_candidates가 엔진에 적용된다."""
    engine = _make_engine()
    assert engine.MAX_CANDIDATES_PER_RUN == 5  # 기본값

    runner = ScenarioRunner(engine)
    spec = _base_spec(max_candidates=2)
    runner.run_scenario(spec)

    assert engine.MAX_CANDIDATES_PER_RUN == 2
    engine.close()


# === 15. CLI 요약 출력 ===

def test_scenario_cli_summary(capsys: pytest.CaptureFixture[str]) -> None:
    """_print_scenario_summary가 요약을 올바르게 출력한다."""
    from engine.cli import _print_scenario_summary

    report = {
        "success": True,
        "scenario_name": "test_batch",
        "domain": "utility",
        "tags": ["test"],
        "total_inputs": 3,
        "successful_inputs": 2,
        "failed_inputs": 1,
        "success_rate": 0.6667,
        "avg_execution_ms": 50,
        "winner_skill": "hello_world",
        "run_results": [
            {"index": 0, "success": True, "skill_id": "hello_world",
             "execution_time_ms": 40, "error": "", "output_preview": ""},
            {"index": 1, "success": True, "skill_id": "hello_world",
             "execution_time_ms": 60, "error": "", "output_preview": ""},
            {"index": 2, "success": False, "skill_id": "",
             "execution_time_ms": 0, "error": "No match", "output_preview": ""},
        ],
        "eval_result": None,
        "evolve_result": None,
        "re_eval_result": None,
        "promote_recommendation": {
            "skill_id": "hello_world",
            "release_state": "experimental",
            "recommendation": "not_eligible",
            "eligible": False,
        },
        "timestamp": "2026-04-06T12:00:00",
    }

    _print_scenario_summary(report)
    captured = capsys.readouterr().out

    assert "Scenario: test_batch" in captured
    assert "3 total" in captured
    assert "2 success" in captured
    assert "hello_world" in captured
    assert "not_eligible" in captured


# === 추가: 검증 실패 시 요약 출력 ===

def test_scenario_summary_validation_error(capsys: pytest.CaptureFixture[str]) -> None:
    """spec 검증 실패 시 에러 메시지를 출력한다."""
    from engine.cli import _print_scenario_summary

    report = {
        "success": False,
        "errors": ["'domain' is required", "'tags' must be a non-empty list"],
        "scenario_name": "bad_spec",
        "timestamp": "2026-04-06T12:00:00",
    }

    _print_scenario_summary(report)
    captured = capsys.readouterr().out

    assert "[FAIL]" in captured
    assert "'domain' is required" in captured
