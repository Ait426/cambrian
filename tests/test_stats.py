"""cambrian stats 운영 요약 테스트.

registry 집계 메서드 테스트 + CLI 출력 검증.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.models import (
    EvolutionRecord,
    ExecutionResult,
    Skill,
    SkillLifecycle,
    SkillRuntime,
)
from engine.registry import SkillRegistry


def _make_skill(
    skill_id: str, domain: str = "testing", status: str = "active",
    fitness: float = 0.0,
) -> Skill:
    """테스트용 Skill 객체를 생성한다."""
    return Skill(
        id=skill_id, version="1.0.0", name=f"Test {skill_id}",
        description="test", domain=domain, tags=["test"], mode="a",
        runtime=SkillRuntime(language="python"),
        lifecycle=SkillLifecycle(status=status, fitness_score=fitness),
        skill_path=Path(f"/tmp/{skill_id}"),
    )


def _insert_trace(
    registry: SkillRegistry,
    trace_type: str = "competitive_run",
    winner_id: str | None = "skill_a",
    candidates_json: str | None = None,
) -> int:
    """테스트용 trace를 삽입한다."""
    if candidates_json is None:
        candidates_json = json.dumps([
            {"skill_id": "skill_a", "mode": "b", "success": True,
             "execution_time_ms": 50, "fitness_before": 0.5, "error": ""},
            {"skill_id": "skill_b", "mode": "b", "success": False,
             "execution_time_ms": 200, "fitness_before": 0.3, "error": "crash"},
        ])
    return registry.add_run_trace(
        trace_type=trace_type, domain="testing", tags=["test"],
        input_summary="{}", candidate_count=2, success_count=1,
        winner_id=winner_id, winner_reason="test",
        candidates_json=candidates_json, total_ms=250,
    )


def _insert_evolution(
    registry: SkillRegistry, skill_id: str, adopted: bool,
    parent_fitness: float = 0.5, child_fitness: float = 0.7,
) -> int:
    """테스트용 진화 기록을 삽입한다."""
    record = EvolutionRecord(
        id=0, skill_id=skill_id,
        parent_skill_md="# Parent", child_skill_md="# Child",
        parent_fitness=parent_fitness, child_fitness=child_fitness,
        adopted=adopted, mutation_summary="test",
        feedback_ids="[]",
        created_at=datetime.now(timezone.utc).isoformat(),
        judge_reasoning="test",
    )
    return registry.add_evolution_record(record)


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """cambrian CLI를 subprocess로 실행한다."""
    cmd = [sys.executable, "-m", "engine.cli"] + list(args)
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        cwd=str(Path(__file__).parent.parent), timeout=30,
    )


# === 글로벌 stats 테스트 ===


def test_global_stats_basic() -> None:
    """스킬 3개 등록 → total/status 카운트 포함."""
    result = _run_cli("stats", "--db", ":memory:")

    assert result.returncode == 0
    assert "Cambrian Engine Stats" in result.stdout


def test_global_stats_top_performers() -> None:
    """fitness 순 상위 표시."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("top_a", fitness=0.9, status="active"))
    registry.register(_make_skill("top_b", fitness=0.5, status="active"))
    registry.register(_make_skill("top_c", fitness=0.1, status="active"))

    skills = registry.list_all()
    top = sorted(skills, key=lambda s: s["fitness_score"], reverse=True)
    assert top[0]["id"] == "top_a"
    assert top[1]["id"] == "top_b"
    registry.close()


def test_global_stats_no_traces() -> None:
    """run_traces 없을 때 에러 없이 동작."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("no_trace"))

    # trace 없어도 집계 메서드가 에러 없이 동작
    traces = registry.get_run_traces(limit=10)
    assert len(traces) == 0
    registry.close()


def test_global_stats_with_evolution() -> None:
    """evolution 2건 → adopted/discarded 카운트."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("evo_skill"))
    _insert_evolution(registry, "evo_skill", adopted=True)
    _insert_evolution(registry, "evo_skill", adopted=False)

    cursor = registry._conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN adopted=1 THEN 1 ELSE 0 END) as adopted "
        "FROM evolution_history"
    )
    row = cursor.fetchone()
    assert row["total"] == 2
    assert row["adopted"] == 1
    registry.close()


def test_global_stats_recent_activity() -> None:
    """trace + evolution + feedback → Recent Activity 정확."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("act_skill"))

    _insert_trace(registry, winner_id="act_skill")
    _insert_trace(registry, winner_id="act_skill")
    _insert_evolution(registry, "act_skill", adopted=True)
    registry.add_feedback("act_skill", 4, "good", "{}", "{}")

    comp = registry.get_run_traces(trace_type="competitive_run")
    assert len(comp) == 2

    cursor = registry._conn.execute(
        "SELECT COUNT(*) as cnt, AVG(rating) as avg_r FROM feedback"
    )
    fb = cursor.fetchone()
    assert fb["cnt"] == 1
    assert fb["avg_r"] == 4.0
    registry.close()


# === 스킬별 stats 테스트 ===


def test_skill_stats_happy_path() -> None:
    """--skill 지정 → 전 섹션 출력."""
    result = _run_cli("stats", "--skill", "hello_world", "--db", ":memory:")

    assert result.returncode == 0
    assert "Skill Stats: hello_world" in result.stdout
    assert "Identity:" in result.stdout
    assert "Performance:" in result.stdout
    assert "Competitive Runs" in result.stdout
    assert "Evolution:" in result.stdout
    assert "Safety:" in result.stdout


def test_skill_stats_not_found() -> None:
    """미존재 스킬 → stderr + exit 1."""
    result = _run_cli("stats", "--skill", "nonexistent_xyz", "--db", ":memory:")

    assert result.returncode == 1
    assert "not found" in result.stderr.lower()


def test_skill_stats_no_executions() -> None:
    """total_executions=0 → success rate N/A."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("no_exec"))

    skill = registry.get("no_exec")
    assert skill["total_executions"] == 0
    registry.close()


def test_skill_stats_no_traces() -> None:
    """trace 없음 → participated=0."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("no_trace_skill"))

    stats = registry.get_skill_trace_stats("no_trace_skill")
    assert stats["participated"] == 0
    assert stats["won"] == 0
    assert stats["win_rate"] == 0.0
    registry.close()


def test_skill_stats_no_evolution() -> None:
    """evolution 없음 → total_evolutions=0."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("no_evo"))

    stats = registry.get_skill_evolution_stats("no_evo")
    assert stats["total_evolutions"] == 0
    assert stats["adoption_rate"] == 0.0
    assert stats["last_evolution_adopted"] is None
    registry.close()


def test_skill_stats_no_feedback() -> None:
    """feedback 없음 → 빈 리스트."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("no_fb"))

    fb = registry.get_feedback("no_fb")
    assert len(fb) == 0
    registry.close()


# === 집계 메서드 단위 테스트 ===


def test_skill_trace_stats_participated() -> None:
    """run_traces에 해당 skill 포함 → participated 카운트 정확."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("skill_a"))

    _insert_trace(registry, winner_id="skill_a")
    _insert_trace(registry, winner_id="skill_b")  # skill_a는 candidates에 포함
    _insert_trace(registry, winner_id="skill_a")

    stats = registry.get_skill_trace_stats("skill_a")
    assert stats["participated"] == 3  # 3개 trace 모두 candidates에 skill_a 포함
    assert stats["won"] == 2
    registry.close()


def test_skill_trace_stats_win_rate() -> None:
    """winner_id 매칭 → win_rate 계산 정확."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("rate_skill"))

    # 4회 참여, 3회 승리
    for i in range(4):
        winner = "rate_skill" if i < 3 else "other"
        candidates = json.dumps([
            {"skill_id": "rate_skill", "mode": "b", "success": True,
             "execution_time_ms": 50, "fitness_before": 0.5, "error": ""},
        ])
        _insert_trace(registry, winner_id=winner, candidates_json=candidates)

    stats = registry.get_skill_trace_stats("rate_skill")
    assert stats["participated"] == 4
    assert stats["won"] == 3
    assert abs(stats["win_rate"] - 0.75) < 0.01
    registry.close()


def test_skill_evolution_stats() -> None:
    """adopted 3, discarded 2 → adoption_rate = 0.6."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("evo_stats"))

    for _ in range(3):
        _insert_evolution(registry, "evo_stats", adopted=True)
    for _ in range(2):
        _insert_evolution(registry, "evo_stats", adopted=False)

    stats = registry.get_skill_evolution_stats("evo_stats")
    assert stats["total_evolutions"] == 5
    assert stats["adopted_count"] == 3
    assert stats["discarded_count"] == 2
    assert abs(stats["adoption_rate"] - 0.6) < 0.01
    registry.close()


def test_skill_rollback_count() -> None:
    """auto_rollback 2건 → count = 2."""
    registry = SkillRegistry(":memory:")
    registry.register(_make_skill("rb_skill"))

    # auto_rollback trace에 skill_id가 winner_reason에 포함
    registry.add_run_trace(
        trace_type="auto_rollback", domain="", tags=[],
        input_summary="", candidate_count=0, success_count=0,
        winner_id=None,
        winner_reason="fitness=0.15 < 0.2, rolled back rb_skill record #1",
        candidates_json="[]", total_ms=0,
    )
    registry.add_run_trace(
        trace_type="auto_rollback", domain="", tags=[],
        input_summary="", candidate_count=0, success_count=0,
        winner_id=None,
        winner_reason="fitness=0.10 < 0.2, rolled back rb_skill record #2",
        candidates_json="[]", total_ms=0,
    )

    count = registry.get_skill_rollback_count("rb_skill")
    assert count == 2
    registry.close()
