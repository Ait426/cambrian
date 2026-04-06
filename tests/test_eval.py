"""cambrian eval 평가 레이어 테스트.

evaluate() 메서드 + eval report + snapshot CRUD 검증.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from engine.exceptions import SkillNotFoundError
from engine.loop import CambrianEngine
from engine.models import ExecutionResult
from engine.registry import SkillRegistry


def _write_eval_skill(
    base_dir: Path,
    skill_id: str = "eval_skill",
    result_value: str = "ok",
    should_fail: bool = False,
) -> Path:
    """eval 테스트용 Mode B 스킬 디렉토리를 생성한다."""
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": "Eval Test",
        "description": "eval test skill",
        "domain": "testing",
        "tags": ["eval"],
        "mode": "b",
        "created_at": "2026-04-06",
        "updated_at": "2026-04-06",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 10,
        },
        "lifecycle": {
            "status": "active",
            "fitness_score": 0.5,
            "total_executions": 0,
            "successful_executions": 0,
            "last_used": None,
            "crystallized_at": None,
        },
    }
    interface = {
        "input": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "입력"}},
            "required": [],
        },
        "output": {
            "type": "object",
            "properties": {"result": {"type": "string", "description": "결과"}},
            "required": ["result"],
        },
    }

    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(interface, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")

    execute_dir = skill_dir / "execute"
    execute_dir.mkdir(exist_ok=True)
    if should_fail:
        body = (
            "import json, sys\n\n"
            "def run(input_data: dict) -> dict:\n"
            "    raise RuntimeError('boom')\n\n"
            "if __name__ == '__main__':\n"
            "    raw = sys.stdin.read()\n"
            "    data = json.loads(raw) if raw.strip() else {}\n"
            "    result = run(data)\n"
            "    print(json.dumps(result, ensure_ascii=False))\n"
        )
    else:
        body = (
            "import json, sys\n\n"
            "def run(input_data: dict) -> dict:\n"
            f"    return {{'result': '{result_value}'}}\n\n"
            "if __name__ == '__main__':\n"
            "    raw = sys.stdin.read()\n"
            "    data = json.loads(raw) if raw.strip() else {}\n"
            "    result = run(data)\n"
            "    print(json.dumps(result, ensure_ascii=False))\n"
        )
    (execute_dir / "main.py").write_text(body, encoding="utf-8")
    return skill_dir


@pytest.fixture
def eval_engine(schemas_dir: Path, tmp_path: Path) -> CambrianEngine:
    """eval 테스트용 엔진 (Mode B 스킬 + eval inputs 3개)."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_eval_skill(skills_dir, "eval_skill")

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    registry = engine.get_registry()
    registry.add_evaluation_input("eval_skill", '{"x": "a"}', "입력 A")
    registry.add_evaluation_input("eval_skill", '{"x": "b"}', "입력 B")
    registry.add_evaluation_input("eval_skill", '{"x": "c"}', "입력 C")
    return engine


# === evaluate() 테스트 ===


def test_eval_happy_path(eval_engine: CambrianEngine) -> None:
    """replay set 3개 → eval → snapshot 저장 + pass_rate 정확."""
    result = eval_engine.evaluate("eval_skill")

    assert result["skill_id"] == "eval_skill"
    assert result["input_count"] == 3
    assert result["pass_count"] == 3
    assert result["pass_rate"] == 1.0
    assert result["snapshot_id"] > 0
    assert result["verdict"] == "baseline"


def test_eval_no_inputs(schemas_dir: Path, tmp_path: Path) -> None:
    """evaluation_inputs 없음 → RuntimeError."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_eval_skill(skills_dir, "no_input_skill")

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    with pytest.raises(RuntimeError, match="No evaluation inputs"):
        engine.evaluate("no_input_skill")


def test_eval_skill_not_found(eval_engine: CambrianEngine) -> None:
    """미존재 skill → SkillNotFoundError."""
    with pytest.raises(SkillNotFoundError):
        eval_engine.evaluate("nonexistent_xyz")


def test_eval_partial_failure(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3개 중 1개 실패 → pass_rate ≈ 66.7%."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_eval_skill(skills_dir, "partial_skill")

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    registry = engine.get_registry()
    registry.add_evaluation_input("partial_skill", '{"x": "a"}', "A")
    registry.add_evaluation_input("partial_skill", '{"x": "b"}', "B")
    registry.add_evaluation_input("partial_skill", '{"x": "c"}', "C")

    call_count = {"n": 0}

    def fake_execute(skill, input_data):
        call_count["n"] += 1
        sid = getattr(skill, "id")
        if call_count["n"] == 2:
            return ExecutionResult(
                skill_id=sid, success=False, error="boom",
                execution_time_ms=10, mode="b",
            )
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.evaluate("partial_skill")
    assert result["pass_count"] == 2
    assert result["fail_count"] == 1
    assert abs(result["pass_rate"] - 0.6667) < 0.01


def test_eval_all_pass(eval_engine: CambrianEngine) -> None:
    """전부 성공 → pass_rate = 100%."""
    result = eval_engine.evaluate("eval_skill")
    assert result["pass_rate"] == 1.0
    assert result["fail_count"] == 0


def test_eval_all_fail(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전부 실패 → pass_rate = 0%, avg_time = 0."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_eval_skill(skills_dir, "fail_skill")

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    engine.get_registry().add_evaluation_input("fail_skill", '{"x": "a"}', "A")

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=False, error="crash",
            execution_time_ms=0, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.evaluate("fail_skill")
    assert result["pass_rate"] == 0.0
    assert result["avg_time_ms"] == 0


def test_eval_avg_time_success_only(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실패 입력의 시간은 avg에 미포함."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_eval_skill(skills_dir, "time_skill")

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    registry = engine.get_registry()
    registry.add_evaluation_input("time_skill", '{"x": "a"}', "A")
    registry.add_evaluation_input("time_skill", '{"x": "b"}', "B")

    call_count = {"n": 0}

    def fake_execute(skill, input_data):
        call_count["n"] += 1
        sid = getattr(skill, "id")
        if call_count["n"] == 1:
            return ExecutionResult(
                skill_id=sid, success=True, output={"result": "ok"},
                execution_time_ms=100, mode="b",
            )
        return ExecutionResult(
            skill_id=sid, success=False, error="fail",
            execution_time_ms=500, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.evaluate("time_skill")
    # 성공 1건(100ms)만 avg 계산
    assert result["avg_time_ms"] == 100


# === verdict 테스트 ===


def test_eval_verdict_baseline(eval_engine: CambrianEngine) -> None:
    """첫 eval → verdict = 'baseline'."""
    result = eval_engine.evaluate("eval_skill")
    assert result["verdict"] == "baseline"
    assert result["delta"] is None


def test_eval_verdict_improving(
    eval_engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2nd eval, pass_rate 상승 → 'improving'."""
    # 1st eval: 1/3 pass (monkeypatch)
    call_count = {"n": 0}

    def fake_fail_mostly(skill, input_data):
        call_count["n"] += 1
        sid = getattr(skill, "id")
        if call_count["n"] <= 1:
            return ExecutionResult(
                skill_id=sid, success=True, output={"result": "ok"},
                execution_time_ms=100, mode="b",
            )
        return ExecutionResult(
            skill_id=sid, success=False, error="fail",
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(eval_engine._executor, "execute", fake_fail_mostly)
    eval_engine.evaluate("eval_skill")

    # 2nd eval: 3/3 pass (원래 스킬)
    monkeypatch.undo()
    result = eval_engine.evaluate("eval_skill")

    assert result["verdict"] == "improving"
    assert result["delta"]["pass_rate"] > 0


def test_eval_verdict_regression(
    eval_engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2nd eval, pass_rate 하락 → 'regression'."""
    # 1st eval: 3/3 pass (원래 스킬)
    eval_engine.evaluate("eval_skill")

    # 2nd eval: 1/3 pass
    call_count = {"n": 0}

    def fake_fail_mostly(skill, input_data):
        call_count["n"] += 1
        sid = getattr(skill, "id")
        if call_count["n"] <= 1:
            return ExecutionResult(
                skill_id=sid, success=True, output={"result": "ok"},
                execution_time_ms=100, mode="b",
            )
        return ExecutionResult(
            skill_id=sid, success=False, error="fail",
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(eval_engine._executor, "execute", fake_fail_mostly)
    result = eval_engine.evaluate("eval_skill")

    assert result["verdict"] == "regression"
    assert result["delta"]["pass_rate"] < 0


def test_eval_verdict_stable(
    eval_engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2nd eval, 변화 없음 → 'stable'."""
    # 실행 시간을 고정하여 deterministic하게 만듦
    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=100, mode="b",
        )

    monkeypatch.setattr(eval_engine._executor, "execute", fake_execute)

    eval_engine.evaluate("eval_skill")
    result = eval_engine.evaluate("eval_skill")

    assert result["verdict"] == "stable"


# === report 테스트 ===


def test_eval_report_trend(eval_engine: CambrianEngine) -> None:
    """5개 스냅샷 → trend 계산."""
    for _ in range(5):
        eval_engine.evaluate("eval_skill")

    report = eval_engine.get_eval_report("eval_skill", limit=5)
    assert report["total_snapshots"] == 5
    assert report["trend"] in ("improving", "stable", "declining", "insufficient_data")


def test_eval_report_empty(eval_engine: CambrianEngine) -> None:
    """스냅샷 없음 → no_data."""
    report = eval_engine.get_eval_report("eval_skill", limit=5)
    assert report["trend"] == "no_data"
    assert len(report["snapshots"]) == 0


# === detail / snapshot 테스트 ===


def test_eval_detail_happy_path(eval_engine: CambrianEngine) -> None:
    """snapshot 조회 → 입력별 결과 존재."""
    result = eval_engine.evaluate("eval_skill")
    snapshot = eval_engine.get_registry().get_evaluation_snapshot_by_id(
        result["snapshot_id"]
    )

    assert snapshot is not None
    assert snapshot["skill_id"] == "eval_skill"
    results = json.loads(snapshot["results_json"])
    assert len(results) == 3


def test_eval_detail_not_found(eval_engine: CambrianEngine) -> None:
    """미존재 snapshot → None."""
    snapshot = eval_engine.get_registry().get_evaluation_snapshot_by_id(9999)
    assert snapshot is None


def test_eval_snapshot_stored(eval_engine: CambrianEngine) -> None:
    """eval 실행 후 registry.get_evaluation_snapshots() → 1행."""
    eval_engine.evaluate("eval_skill")

    snapshots = eval_engine.get_registry().get_evaluation_snapshots("eval_skill")
    assert len(snapshots) == 1
    assert snapshots[0]["pass_count"] == 3
    assert snapshots[0]["input_count"] == 3
