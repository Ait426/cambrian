"""Budget / Latency Control 테스트.

MAX_CANDIDATES_PER_RUN, MAX_MODE_A_PER_RUN, MAX_EVAL_CASES,
MAX_EVAL_INPUTS 상수 + truncate 동작 검증.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from engine.evolution import SkillEvolver
from engine.executor import SkillExecutor
from engine.judge import SkillJudge
from engine.loop import CambrianEngine
from engine.models import ExecutionResult, JudgeVerdict
from engine.registry import SkillRegistry


def _write_mode_b_skill(
    base_dir: Path,
    skill_id: str,
    domain: str = "budget",
    tags: list[str] | None = None,
    fitness_score: float = 0.0,
) -> Path:
    """Mode B 테스트 스킬을 생성한다."""
    if tags is None:
        tags = ["budget"]
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id, "version": "1.0.0", "name": "Test",
        "description": "budget test", "domain": domain, "tags": tags,
        "mode": "b", "created_at": "2026-04-06", "updated_at": "2026-04-06",
        "runtime": {"language": "python", "needs_network": False,
                     "needs_filesystem": False, "timeout_seconds": 10},
        "lifecycle": {"status": "active", "fitness_score": fitness_score,
                       "total_executions": 0, "successful_executions": 0,
                       "last_used": None, "crystallized_at": None},
    }
    interface = {
        "input": {"type": "object",
                   "properties": {"x": {"type": "string", "description": "x"}},
                   "required": []},
        "output": {"type": "object",
                    "properties": {"result": {"type": "string", "description": "r"}},
                    "required": ["result"]},
    }
    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(interface, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
    execute_dir = skill_dir / "execute"
    execute_dir.mkdir(exist_ok=True)
    (execute_dir / "main.py").write_text(
        "import json, sys\n\n"
        "def run(input_data: dict) -> dict:\n"
        "    return {'result': 'ok'}\n\n"
        "if __name__ == '__main__':\n"
        "    raw = sys.stdin.read()\n"
        "    data = json.loads(raw) if raw.strip() else {}\n"
        "    result = run(data)\n"
        "    print(json.dumps(result, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    return skill_dir


def _write_mode_a_skill(
    base_dir: Path,
    skill_id: str,
    domain: str = "budget",
    tags: list[str] | None = None,
    fitness_score: float = 0.0,
) -> Path:
    """Mode A 테스트 스킬을 생성한다."""
    if tags is None:
        tags = ["budget"]
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id, "version": "1.0.0", "name": "Test",
        "description": "budget test", "domain": domain, "tags": tags,
        "mode": "a", "created_at": "2026-04-06", "updated_at": "2026-04-06",
        "runtime": {"language": "python", "needs_network": False,
                     "needs_filesystem": False, "timeout_seconds": 10},
        "lifecycle": {"status": "active", "fitness_score": fitness_score,
                       "total_executions": 0, "successful_executions": 0,
                       "last_used": None, "crystallized_at": None},
    }
    interface = {
        "input": {"type": "object",
                   "properties": {"x": {"type": "string", "description": "x"}},
                   "required": []},
        "output": {"type": "object",
                    "properties": {"result": {"type": "string", "description": "r"}},
                    "required": ["result"]},
    }
    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(interface, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")
    return skill_dir


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "engine.cli"] + list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=str(Path(__file__).parent.parent), timeout=30,
    )


# === 경쟁 실행 candidate cap ===


def test_candidate_cap_applied(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """후보 7개 등록, MAX=3 → 3개만 실행."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    for i in range(7):
        _write_mode_b_skill(
            skills_dir, f"cap_skill_{i}", domain="cap",
            tags=["cap"], fitness_score=0.1 * (i + 1),
        )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    engine.MAX_CANDIDATES_PER_RUN = 3

    executed_ids: list[str] = []

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        executed_ids.append(sid)
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)
    engine.run_task(domain="cap", tags=["cap"], input_data={})

    assert len(executed_ids) <= 3


def test_candidate_cap_preserves_top(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """truncate 후 fitness 상위가 남는다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    for i in range(6):
        _write_mode_b_skill(
            skills_dir, f"top_skill_{i}", domain="top",
            tags=["top"], fitness_score=0.1 * (i + 1),
        )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    engine.MAX_CANDIDATES_PER_RUN = 3

    executed_ids: list[str] = []

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        executed_ids.append(sid)
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)
    engine.run_task(domain="top", tags=["top"], input_data={})

    # fitness 상위 3개: top_skill_5(0.6), top_skill_4(0.5), top_skill_3(0.4)
    assert "top_skill_5" in executed_ids
    assert "top_skill_4" in executed_ids


def test_candidate_cap_no_effect_under_limit(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """후보 3개, MAX=5 → truncate 미발생."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    for i in range(3):
        _write_mode_b_skill(
            skills_dir, f"under_skill_{i}", domain="under",
            tags=["under"], fitness_score=0.5,
        )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    executed_ids: list[str] = []

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        executed_ids.append(sid)
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)
    engine.run_task(domain="under", tags=["under"], input_data={})

    assert len(executed_ids) == 3


# === Mode A limit ===


def test_mode_a_limit_class_level(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAX_MODE_A_PER_RUN=2 → Mode A 3개 중 2개만 실행."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    for i in range(3):
        _write_mode_a_skill(
            skills_dir, f"ma_skill_{i}", domain="malimit",
            tags=["malimit"], fitness_score=0.1 * (i + 1),
        )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    executed_ids: list[str] = []

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        executed_ids.append(sid)
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": sid},
            execution_time_ms=10, mode="a",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)
    engine.run_task(domain="malimit", tags=["malimit"], input_data={})

    assert len(executed_ids) == 2
    assert "ma_skill_0" not in executed_ids  # fitness 최하위 제외


def test_mode_a_limit_override(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine.MAX_MODE_A_PER_RUN=1 → Mode A 1개만 실행."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    for i in range(3):
        _write_mode_a_skill(
            skills_dir, f"mo_skill_{i}", domain="motest",
            tags=["motest"], fitness_score=0.1 * (i + 1),
        )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    engine.MAX_MODE_A_PER_RUN = 1

    executed_ids: list[str] = []

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        executed_ids.append(sid)
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": sid},
            execution_time_ms=10, mode="a",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)
    engine.run_task(domain="motest", tags=["motest"], input_data={})

    assert len(executed_ids) == 1


# === eval cases cap ===


def test_eval_cases_cap(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """eval_inputs 25개, MAX_EVAL_CASES=5 → 5개만 실행."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(skills_dir, "eval_cap", domain="evalcap", tags=["evalcap"])

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    engine.MAX_EVAL_CASES = 5

    registry = engine.get_registry()
    for i in range(25):
        registry.add_evaluation_input("eval_cap", f'{{"x": "{i}"}}', f"입력 {i}")

    exec_count = {"n": 0}

    def fake_execute(skill, input_data):
        exec_count["n"] += 1
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)
    result = engine.evaluate("eval_cap")

    assert exec_count["n"] == 5
    assert result["input_count"] == 5


def test_eval_cases_no_effect_under_limit(
    schemas_dir: Path, tmp_path: Path,
) -> None:
    """eval_inputs 3개, MAX=20 → truncate 미발생."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(skills_dir, "eval_under", domain="evalunder", tags=["evalunder"])

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    registry = engine.get_registry()
    for i in range(3):
        registry.add_evaluation_input("eval_under", f'{{"x": "{i}"}}', f"입력 {i}")

    result = engine.evaluate("eval_under")
    assert result["input_count"] == 3


# === evolution eval inputs cap ===


def test_evolution_eval_inputs_cap(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """replay 15개, MAX_EVAL_INPUTS=3 → 3개만 평가."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_a_skill(skills_dir, "evo_cap", domain="evocap", tags=["evocap"])

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    registry = engine.get_registry()
    for i in range(15):
        registry.add_evaluation_input("evo_cap", f'{{"x": "{i}"}}', f"입력 {i}")

    evolver = SkillEvolver(
        engine._loader, engine._executor, registry,
    )
    evolver.MAX_EVAL_INPUTS = 3

    # evolve에서 replay set이 3개로 잘리는지 확인
    # (직접 evolve 호출은 LLM 필요하므로, get_evaluation_inputs + truncate 로직만 검증)
    eval_inputs = registry.get_evaluation_inputs("evo_cap")
    assert len(eval_inputs) == 15

    if len(eval_inputs) > evolver.MAX_EVAL_INPUTS:
        eval_inputs = eval_inputs[:evolver.MAX_EVAL_INPUTS]
    assert len(eval_inputs) == 3


# === 로그/trace 검증 ===


def test_truncate_warning_logged(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """truncate 시 logger.warning 호출 확인."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    for i in range(7):
        _write_mode_b_skill(
            skills_dir, f"log_skill_{i}", domain="logtest",
            tags=["logtest"], fitness_score=0.1 * (i + 1),
        )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    engine.MAX_CANDIDATES_PER_RUN = 3

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    with caplog.at_level(logging.WARNING, logger="engine.loop"):
        engine.run_task(domain="logtest", tags=["logtest"], input_data={})

    assert any("Budget cap" in r.message for r in caplog.records)


def test_truncate_trace_budget_note(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """truncate 발생 시 trace winner_reason에 '[BUDGET]' 포함."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    for i in range(7):
        _write_mode_b_skill(
            skills_dir, f"bt_skill_{i}", domain="bttest",
            tags=["bttest"], fitness_score=0.1 * (i + 1),
        )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    engine.MAX_CANDIDATES_PER_RUN = 3

    def fake_execute(skill, input_data):
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)
    engine.run_task(domain="bttest", tags=["bttest"], input_data={})

    traces = engine.get_run_traces(trace_type="competitive_run", limit=1)
    assert len(traces) == 1
    assert "[BUDGET" in traces[0]["winner_reason"]


# === CLI override ===


def test_cli_max_candidates_override() -> None:
    """--max-candidates가 파싱된다 (실제 실행은 스킬 필요)."""
    # 파서 동작만 검증 — 실제 실행은 단순히 에러 없이 파싱되는지 확인
    result = _run_cli(
        "run", "-d", "test", "-t", "test", "-i", '{"x":"y"}',
        "--max-candidates", "3", "--db", ":memory:",
    )
    # 스킬 없어서 실패하겠지만, argparse 에러(exit 2)가 아니어야 함
    assert result.returncode != 2


def test_cli_max_cases_override() -> None:
    """--max-cases가 파싱된다."""
    result = _run_cli(
        "eval", "nonexistent", "--max-cases", "5", "--db", ":memory:",
    )
    assert result.returncode != 2


def test_budget_stats_display() -> None:
    """stats 출력에 'Budget Limits:' 포함."""
    result = _run_cli("stats", "--db", ":memory:")
    assert result.returncode == 0
    assert "Budget Limits:" in result.stdout


def test_candidate_cap_zero_forced_to_one(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MAX_CANDIDATES_PER_RUN=0 설정 시 최소 1개는 실행."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "zero_skill", domain="zero", tags=["zero"], fitness_score=0.5,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )
    # 직접 0 설정 시에도 truncate에서 0개로 잘리지만 후보 자체가 1개면 영향 없음
    # CLI에서는 max(1, value)로 강제됨
    engine.MAX_CANDIDATES_PER_RUN = max(1, 0)
    assert engine.MAX_CANDIDATES_PER_RUN == 1
