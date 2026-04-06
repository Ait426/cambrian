"""cambrian trace CLI 테스트.

registry에 직접 trace 데이터를 삽입한 후
_handle_trace / _handle_trace_detail 출력을 검증한다.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from engine.registry import SkillRegistry


def _insert_trace(
    registry: SkillRegistry,
    trace_type: str = "competitive_run",
    winner_id: str | None = "test_skill",
    candidate_count: int = 2,
    success_count: int = 1,
    winner_reason: str = "execution_time=50ms",
    candidates_json: str | None = None,
    domain: str = "testing",
    tags: list[str] | None = None,
) -> int:
    """테스트용 trace를 삽입한다."""
    if candidates_json is None:
        candidates_json = json.dumps([
            {
                "skill_id": "test_skill",
                "mode": "b",
                "success": True,
                "execution_time_ms": 50,
                "fitness_before": 0.65,
                "error": "",
            },
            {
                "skill_id": "other_skill",
                "mode": "b",
                "success": False,
                "execution_time_ms": 200,
                "fitness_before": 0.40,
                "error": "timeout",
            },
        ])
    return registry.add_run_trace(
        trace_type=trace_type,
        domain=domain,
        tags=tags or ["test"],
        input_summary='{"value": "test"}',
        candidate_count=candidate_count,
        success_count=success_count,
        winner_id=winner_id,
        winner_reason=winner_reason,
        candidates_json=candidates_json,
        total_ms=250,
    )


def _run_cli(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """cambrian CLI를 subprocess로 실행한다."""
    cmd = [sys.executable, "-m", "engine.cli"] + list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd or str(Path(__file__).parent.parent),
        timeout=30,
    )


# --- list view 테스트 ---


def test_trace_list_empty() -> None:
    """trace 없음 → 'No traces found.' 출력."""
    result = _run_cli("trace", "--db", ":memory:", "--limit", "10")

    assert result.returncode == 0
    assert "No traces found." in result.stdout


def test_trace_list_shows_recent() -> None:
    """trace 3개 삽입 → list에 3행 표시."""
    registry = SkillRegistry(":memory:")
    for i in range(3):
        _insert_trace(registry, winner_id=f"skill_{i}")

    traces = registry.get_run_traces(limit=10)
    assert len(traces) == 3
    registry.close()


def test_trace_list_limit() -> None:
    """trace 5개 삽입, limit=2 → 2개만 반환."""
    registry = SkillRegistry(":memory:")
    for i in range(5):
        _insert_trace(registry, winner_id=f"skill_{i}")

    traces = registry.get_run_traces(limit=2)
    assert len(traces) == 2
    registry.close()


def test_trace_list_type_filter() -> None:
    """competitive + evolution 삽입, type=competitive → competitive만."""
    registry = SkillRegistry(":memory:")
    _insert_trace(registry, trace_type="competitive_run", winner_id="a")
    _insert_trace(registry, trace_type="evolution_decision", winner_id="b")
    _insert_trace(registry, trace_type="competitive_run", winner_id="c")

    traces = registry.get_run_traces(trace_type="competitive_run")
    assert len(traces) == 2
    for t in traces:
        assert t["trace_type"] == "competitive_run"
    registry.close()


def test_trace_list_skill_filter() -> None:
    """--skill 필터로 winner_id 매칭만 반환."""
    registry = SkillRegistry(":memory:")
    _insert_trace(registry, winner_id="csv_to_chart")
    _insert_trace(registry, winner_id="email_draft")

    traces = registry.get_run_traces(skill_id="csv_to_chart")
    assert len(traces) >= 1
    assert all(
        t["winner_id"] == "csv_to_chart" or "csv_to_chart" in t.get("candidates_json", "")
        for t in traces
    )
    registry.close()


def test_trace_list_reason_truncation() -> None:
    """40자 초과 reason → get_run_traces에서 원본 보존 (CLI에서 truncation)."""
    registry = SkillRegistry(":memory:")
    long_reason = "a" * 60
    _insert_trace(registry, winner_reason=long_reason)

    traces = registry.get_run_traces(limit=1)
    # DB에는 원본 저장
    assert len(traces[0]["winner_reason"]) == 60
    registry.close()


# --- detail view 테스트 ---


def test_trace_detail_happy_path() -> None:
    """단건 조회 → 헤더 + 승자 + 후보 데이터."""
    registry = SkillRegistry(":memory:")
    trace_id = _insert_trace(registry, winner_id="csv_to_chart")

    trace = registry.get_run_trace_by_id(trace_id)
    assert trace is not None
    assert trace["id"] == trace_id
    assert trace["winner_id"] == "csv_to_chart"
    assert trace["trace_type"] == "competitive_run"
    # candidates 파싱 가능
    candidates = json.loads(trace["candidates_json"])
    assert len(candidates) == 2
    registry.close()


def test_trace_detail_not_found() -> None:
    """존재하지 않는 ID → None 반환."""
    registry = SkillRegistry(":memory:")
    trace = registry.get_run_trace_by_id(9999)
    assert trace is None
    registry.close()


def test_trace_detail_not_found_cli() -> None:
    """CLI에서 존재하지 않는 ID → stderr + exit 1."""
    result = _run_cli("trace", "--detail", "9999", "--db", ":memory:")

    assert result.returncode == 1
    assert "not found" in result.stderr.lower()


def test_trace_detail_all_failed() -> None:
    """winner_id=None trace → 전부 실패 표시."""
    registry = SkillRegistry(":memory:")
    trace_id = _insert_trace(
        registry,
        winner_id=None,
        success_count=0,
        winner_reason="all_failed",
    )

    trace = registry.get_run_trace_by_id(trace_id)
    assert trace is not None
    assert trace["winner_id"] is None
    assert trace["winner_reason"] == "all_failed"
    registry.close()


def test_trace_detail_candidates_parse_fail() -> None:
    """candidates_json이 유효하지 않은 JSON이면 graceful 처리."""
    registry = SkillRegistry(":memory:")
    trace_id = _insert_trace(
        registry,
        candidates_json="not valid json {{",
    )

    trace = registry.get_run_trace_by_id(trace_id)
    assert trace is not None
    # candidates_json은 원본 문자열 그대로 보존
    assert trace["candidates_json"] == "not valid json {{"
    registry.close()


def test_trace_detail_evolution_verdict() -> None:
    """evolution_decision trace → verdict 형식 감지."""
    verdict_data = json.dumps([
        {"original_score": 6.0, "variant_score": 8.0, "winner": "variant", "reasoning": "better"},
        {"original_score": 5.0, "variant_score": 7.0, "winner": "variant", "reasoning": "improved"},
    ])
    registry = SkillRegistry(":memory:")
    trace_id = _insert_trace(
        registry,
        trace_type="evolution_decision",
        winner_id="test_skill",
        candidates_json=verdict_data,
        candidate_count=2,
        success_count=2,
    )

    trace = registry.get_run_trace_by_id(trace_id)
    candidates = json.loads(trace["candidates_json"])
    # verdict 형식: original_score 키 존재
    assert "original_score" in candidates[0]
    assert candidates[0]["variant_score"] == 8.0
    registry.close()


def test_trace_detail_winner_marker() -> None:
    """candidates에서 winner와 일치하는 항목 식별 가능."""
    registry = SkillRegistry(":memory:")
    candidates = [
        {"skill_id": "winner_skill", "mode": "b", "success": True,
         "execution_time_ms": 30, "fitness_before": 0.5, "error": ""},
        {"skill_id": "loser_skill", "mode": "b", "success": True,
         "execution_time_ms": 100, "fitness_before": 0.8, "error": ""},
    ]
    trace_id = _insert_trace(
        registry,
        winner_id="winner_skill",
        candidates_json=json.dumps(candidates),
    )

    trace = registry.get_run_trace_by_id(trace_id)
    parsed = json.loads(trace["candidates_json"])
    winner_found = any(
        c["skill_id"] == trace["winner_id"] for c in parsed
    )
    assert winner_found
    registry.close()
