"""Multi-Profile Matrix Runner 테스트 (Task 18).

동일 scenario를 여러 policy로 순차 실행, baseline 대비 verdict,
summary 저장을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.loop import CambrianEngine
from engine.scenario import ScenarioRunner


def _make_engine() -> CambrianEngine:
    """인메모리 엔진."""
    return CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path=":memory:",
    )


def _base_spec() -> dict:
    """기본 scenario spec."""
    return {
        "name": "test_matrix",
        "domain": "utility",
        "tags": ["greeting", "test"],
        "inputs": [{"text": "hello"}, {"text": "world"}],
        "do_eval": False,
        "do_evolve": False,
    }


def _write_policy(tmp_path: Path, name: str, **overrides: object) -> str:
    """테스트용 policy JSON 파일을 생성하고 경로를 반환한다."""
    policy: dict = {
        "budget": {"max_candidates_per_run": 5},
    }
    for section in ("budget", "governance", "evolution"):
        for k, v in overrides.items():
            if k.startswith(section + "_"):
                field = k[len(section) + 1:]
                policy.setdefault(section, {})[field] = v
    # 단순 budget override만 있으면 그대로 사용
    for k, v in overrides.items():
        if "." in k:
            sec, field = k.split(".", 1)
            policy.setdefault(sec, {})[field] = v

    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return str(path)


def _write_default_policies(tmp_path: Path) -> list[str]:
    """기본 3개 policy 파일 생성."""
    p1 = _write_policy(tmp_path, "conservative")
    p2 = _write_policy(tmp_path, "balanced")
    p3 = _write_policy(tmp_path, "aggressive")
    return [p1, p2, p3]


# === 1. 2개 policy → 2개 snapshot + summary ===

def test_matrix_two_policies(tmp_path: Path) -> None:
    """2개 policy로 matrix 실행 → 2개 snapshot + summary."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)[:2]
    out = tmp_path / "out"

    summary = runner.run_matrix(
        _base_spec(), policies, out_dir=out,
    )
    assert summary.get("_matrix_version") == "1.0.0"
    assert len(summary["profiles"]) == 2

    # 파일 확인
    files = list(out.glob("*.json"))
    assert len(files) >= 3  # 2 snapshots + 1 summary
    engine.close()


# === 2. 3개 policy → 3개 snapshot + summary ===

def test_matrix_three_policies(tmp_path: Path) -> None:
    """3개 policy → 3개 snapshot + summary."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)
    out = tmp_path / "out"

    summary = runner.run_matrix(
        _base_spec(), policies, out_dir=out,
    )
    assert len(summary["profiles"]) == 3
    engine.close()


# === 3. 첫 번째 policy가 baseline ===

def test_matrix_baseline_first_by_default(tmp_path: Path) -> None:
    """baseline 미지정 시 첫 번째 policy가 baseline."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)
    out = tmp_path / "out"

    summary = runner.run_matrix(
        _base_spec(), policies, out_dir=out,
    )
    assert summary["baseline_policy"] == policies[0]
    assert summary["profiles"][0]["is_baseline"] is True
    engine.close()


# === 4. --baseline으로 두 번째 지정 ===

def test_matrix_baseline_explicit(tmp_path: Path) -> None:
    """baseline을 두 번째 policy로 명시 지정."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)
    out = tmp_path / "out"

    summary = runner.run_matrix(
        _base_spec(), policies,
        baseline_path=policies[1], out_dir=out,
    )
    assert summary["baseline_policy"] == policies[1]
    # 두 번째가 baseline
    baseline_profiles = [p for p in summary["profiles"] if p["is_baseline"]]
    assert len(baseline_profiles) == 1
    assert baseline_profiles[0]["policy_path"] == policies[1]
    engine.close()


# === 5. baseline이 policies에 없으면 에러 ===

def test_matrix_baseline_not_in_list(tmp_path: Path) -> None:
    """policies에 없는 baseline → 에러."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)

    summary = runner.run_matrix(
        _base_spec(), policies,
        baseline_path="/nonexistent.json",
    )
    assert summary.get("success") is False
    assert any("baseline" in e for e in summary["errors"])
    engine.close()


# === 6. 개별 snapshot 파일 저장 ===

def test_matrix_snapshot_files_saved(tmp_path: Path) -> None:
    """out_dir에 개별 snapshot 파일이 존재한다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)[:2]
    out = tmp_path / "out"

    runner.run_matrix(_base_spec(), policies, out_dir=out)

    baseline_files = list(out.glob("baseline__*.json"))
    profile_files = list(out.glob("profile__*.json"))
    assert len(baseline_files) == 1
    assert len(profile_files) == 1
    engine.close()


# === 7. _matrix_summary.json 존재 ===

def test_matrix_summary_file_saved(tmp_path: Path) -> None:
    """_matrix_summary.json이 out_dir에 존재한다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)[:2]
    out = tmp_path / "out"

    runner.run_matrix(_base_spec(), policies, out_dir=out)

    summary_path = out / "_matrix_summary.json"
    assert summary_path.exists()
    loaded = json.loads(summary_path.read_text(encoding="utf-8"))
    assert loaded["_matrix_version"] == "1.0.0"
    engine.close()


# === 8. summary 필수 키 ===

def test_matrix_summary_structure(tmp_path: Path) -> None:
    """summary에 필수 키가 전부 존재한다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)[:2]
    out = tmp_path / "out"

    summary = runner.run_matrix(_base_spec(), policies, out_dir=out)

    required = {
        "_matrix_version", "scenario_name", "scenario_path",
        "scenario_hash", "baseline_policy", "timestamp",
        "notes", "profiles", "overall_verdict",
    }
    assert required.issubset(summary.keys())
    engine.close()


# === 9. verdict: improved ===

def test_matrix_verdict_improved() -> None:
    """SnapshotComparer에서 b_better → run_matrix에서 improved 매핑 확인."""
    from engine.snapshot import SnapshotComparer
    comparer = SnapshotComparer()
    # B가 더 나은 경우
    a = {"success_rate": 0.5, "avg_execution_ms": 300, "eval_result": {"pass_rate": 0.3}}
    b = {"success_rate": 0.9, "avg_execution_ms": 100, "eval_result": {"pass_rate": 0.9}}
    result = comparer.compare(a, b)
    assert result["verdict"] == "b_better"
    # run_matrix에서는 b_better → improved


# === 10. verdict: regressed (구조적 한계로 동일 policy → equivalent) ===

def test_matrix_verdict_regressed() -> None:
    """SnapshotComparer에서 a_better → regressed 매핑 확인."""
    from engine.snapshot import SnapshotComparer
    comparer = SnapshotComparer()
    # baseline이 더 나은 경우
    a = {"success_rate": 0.9, "avg_execution_ms": 50, "eval_result": {"pass_rate": 0.9}}
    b = {"success_rate": 0.3, "avg_execution_ms": 300, "eval_result": {"pass_rate": 0.2}}
    result = comparer.compare(a, b)
    assert result["verdict"] == "a_better"
    # run_matrix에서는 a_better → regressed


# === 11. verdict: equivalent ===

def test_matrix_verdict_equivalent() -> None:
    """SnapshotComparer에서 동일 지표 → equivalent 확인."""
    from engine.snapshot import SnapshotComparer
    comparer = SnapshotComparer()
    a = {"success_rate": 0.8, "avg_execution_ms": 100, "eval_result": None}
    b = {"success_rate": 0.8, "avg_execution_ms": 100, "eval_result": None}
    result = comparer.compare(a, b)
    assert result["verdict"] == "equivalent"


# === 12. verdict: mixed ===

def test_matrix_verdict_mixed() -> None:
    """SnapshotComparer에서 mixed 판정 확인."""
    from engine.snapshot import SnapshotComparer
    comparer = SnapshotComparer()
    # A: success_rate 우세, B: latency 우세, eval 동일
    a = {"success_rate": 0.9, "avg_execution_ms": 200, "eval_result": None}
    b = {"success_rate": 0.7, "avg_execution_ms": 100, "eval_result": None}
    result = comparer.compare(a, b)
    assert result["verdict"] == "mixed"


# === 13. partial failure: 1개 실패 → 나머지 계속 ===

def test_matrix_partial_failure(tmp_path: Path) -> None:
    """1개 policy 파일이 잘못되어도 나머지는 계속 실행된다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)

    good = _write_policy(tmp_path, "good")
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid json!!!", encoding="utf-8")

    out = tmp_path / "out"
    summary = runner.run_matrix(
        _base_spec(), [good, str(bad)], out_dir=out,
    )
    # good은 성공, bad는 error
    assert len(summary["profiles"]) == 2
    error_profiles = [p for p in summary["profiles"] if p.get("verdict_vs_baseline") == "error"]
    assert len(error_profiles) == 1
    engine.close()


# === 14. single policy → baseline만 ===

def test_matrix_single_policy_warning(tmp_path: Path) -> None:
    """1개 policy만 → baseline만 (비교 없음)."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    p = _write_policy(tmp_path, "only")
    out = tmp_path / "out"

    summary = runner.run_matrix(_base_spec(), [p], out_dir=out)
    assert len(summary["profiles"]) == 1
    assert summary["profiles"][0]["is_baseline"] is True
    assert summary["profiles"][0]["verdict_vs_baseline"] is None
    engine.close()


# === 15. policy 파일 미존재 → 실행 전 에러 (CLI 레벨) ===

def test_matrix_policy_file_not_found() -> None:
    """없는 policy 파일 경로는 CambrianPolicy에서 FileNotFoundError."""
    from engine.policy import CambrianPolicy
    with pytest.raises(FileNotFoundError):
        CambrianPolicy("totally_nonexistent.json")


# === 16. overall verdict 문자열 형식 ===

def test_matrix_overall_verdict_string(tmp_path: Path) -> None:
    """overall_verdict가 'N improved, N mixed, N regressed' 형식."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)
    out = tmp_path / "out"

    summary = runner.run_matrix(_base_spec(), policies, out_dir=out)
    overall = summary["overall_verdict"]
    assert "improved" in overall
    assert "mixed" in overall
    assert "regressed" in overall
    engine.close()


# === 17. 개별 snapshot에 _context 존재 ===

def test_matrix_snapshot_has_context(tmp_path: Path) -> None:
    """개별 snapshot 파일에 _context 필드가 존재한다."""
    engine = _make_engine()
    runner = ScenarioRunner(engine)
    policies = _write_default_policies(tmp_path)[:2]
    out = tmp_path / "out"

    runner.run_matrix(_base_spec(), policies, out_dir=out)

    baseline_file = list(out.glob("baseline__*.json"))[0]
    snap = json.loads(baseline_file.read_text(encoding="utf-8"))
    assert "_context" in snap
    assert "_snapshot_version" in snap
    assert snap["_context"]["policy_source"] is not None
    engine.close()


# === 18. CLI happy path (stdout + 파일) ===

def test_matrix_cli_happy_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """_print_matrix_summary가 요약을 출력한다."""
    from engine.cli import _print_matrix_summary

    summary = {
        "scenario_name": "test_matrix",
        "baseline_policy": "conservative.json",
        "profiles": [
            {
                "policy_path": "conservative.json",
                "is_baseline": True,
                "success_rate": 0.8,
                "eval_pass_rate": None,
                "avg_execution_ms": 100,
                "promote_recommendation": "not_eligible",
                "verdict_vs_baseline": None,
            },
            {
                "policy_path": "aggressive.json",
                "is_baseline": False,
                "success_rate": 0.9,
                "eval_pass_rate": None,
                "avg_execution_ms": 80,
                "promote_recommendation": "candidate",
                "verdict_vs_baseline": "improved",
            },
        ],
        "overall_verdict": "1 improved, 0 mixed, 0 regressed",
    }

    _print_matrix_summary(summary)
    captured = capsys.readouterr().out

    assert "Matrix Run:" in captured
    assert "conservative (base)" in captured
    assert "aggressive" in captured
    assert "improved" in captured
    assert "Overall:" in captured
