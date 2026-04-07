"""Pilot Outcome / KPI 테스트 (Task 14).

실행 결과에 대한 사람의 사용 판정(outcome) 기록,
파일럿 KPI 집계, CLI 동작을 검증한다.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engine.exceptions import SkillNotFoundError
from engine.models import Skill, SkillLifecycle, SkillRuntime
from engine.registry import SkillRegistry


def _make_skill(skill_id: str = "test_skill") -> Skill:
    """테스트용 최소 Skill 객체를 생성한다."""
    return Skill(
        id=skill_id,
        version="1.0.0",
        name="Test Skill",
        description="A test skill",
        domain="testing",
        tags=["test"],
        mode="b",
        runtime=SkillRuntime(language="python"),
        lifecycle=SkillLifecycle(),
        skill_path=Path("."),
    )


def _make_registry_with_skills(*skill_ids: str) -> SkillRegistry:
    """스킬이 등록된 인메모리 레지스트리를 반환한다."""
    registry = SkillRegistry(":memory:")
    for sid in skill_ids:
        registry.register(_make_skill(sid))
    return registry


# === 1. approved 저장 + 조회 ===

def test_add_outcome_approved() -> None:
    """approved outcome을 저장하고 조회할 수 있다."""
    registry = _make_registry_with_skills("skill_a")

    oid = registry.add_outcome(
        skill_id="skill_a",
        verdict="approved",
        domain="testing",
    )
    assert oid > 0

    outcomes = registry.get_outcomes(skill_id="skill_a")
    assert len(outcomes) == 1
    assert outcomes[0]["verdict"] == "approved"
    assert outcomes[0]["skill_id"] == "skill_a"
    registry.close()


# === 2. 4가지 verdict 모두 저장 ===

def test_add_outcome_all_verdicts() -> None:
    """approved, edited, rejected, redo 모두 저장 가능하다."""
    registry = _make_registry_with_skills("skill_a")

    for v in ("approved", "edited", "rejected", "redo"):
        oid = registry.add_outcome(skill_id="skill_a", verdict=v)
        assert oid > 0

    outcomes = registry.get_outcomes(skill_id="skill_a")
    assert len(outcomes) == 4
    verdicts = {o["verdict"] for o in outcomes}
    assert verdicts == {"approved", "edited", "rejected", "redo"}
    registry.close()


# === 3. run_trace_id 연결 ===

def test_add_outcome_with_trace() -> None:
    """run_trace_id를 연결하여 저장할 수 있다."""
    registry = _make_registry_with_skills("skill_a")

    oid = registry.add_outcome(
        skill_id="skill_a",
        verdict="approved",
        run_trace_id=42,
    )

    outcomes = registry.get_outcomes()
    assert outcomes[0]["run_trace_id"] == 42
    registry.close()


# === 4. human_note 저장 ===

def test_add_outcome_with_note() -> None:
    """human_note를 저장하고 조회할 수 있다."""
    registry = _make_registry_with_skills("skill_a")

    registry.add_outcome(
        skill_id="skill_a",
        verdict="edited",
        human_note="숫자 포맷 수정함",
    )

    outcomes = registry.get_outcomes()
    assert outcomes[0]["human_note"] == "숫자 포맷 수정함"
    registry.close()


# === 5. 잘못된 verdict → ValueError ===

def test_add_outcome_invalid_verdict() -> None:
    """유효하지 않은 verdict는 ValueError를 발생시킨다."""
    registry = _make_registry_with_skills("skill_a")

    with pytest.raises(ValueError, match="Invalid verdict"):
        registry.add_outcome(skill_id="skill_a", verdict="unknown")
    registry.close()


# === 6. 미존재 skill → SkillNotFoundError ===

def test_add_outcome_skill_not_found() -> None:
    """record_outcome에서 미존재 스킬은 SkillNotFoundError."""
    from engine.loop import CambrianEngine

    engine = CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path=":memory:",
    )

    with pytest.raises(SkillNotFoundError):
        engine.record_outcome(
            skill_id="nonexistent_skill",
            verdict="approved",
        )
    engine.close()


# === 7. skill_id 필터 ===

def test_get_outcomes_skill_filter() -> None:
    """skill_id로 필터링하면 해당 스킬만 반환된다."""
    registry = _make_registry_with_skills("skill_a", "skill_b")

    registry.add_outcome(skill_id="skill_a", verdict="approved")
    registry.add_outcome(skill_id="skill_b", verdict="rejected")
    registry.add_outcome(skill_id="skill_a", verdict="edited")

    outcomes_a = registry.get_outcomes(skill_id="skill_a")
    assert len(outcomes_a) == 2
    assert all(o["skill_id"] == "skill_a" for o in outcomes_a)
    registry.close()


# === 8. verdict 필터 ===

def test_get_outcomes_verdict_filter() -> None:
    """verdict로 필터링하면 해당 verdict만 반환된다."""
    registry = _make_registry_with_skills("skill_a")

    registry.add_outcome(skill_id="skill_a", verdict="approved")
    registry.add_outcome(skill_id="skill_a", verdict="rejected")
    registry.add_outcome(skill_id="skill_a", verdict="approved")

    approved = registry.get_outcomes(verdict="approved")
    assert len(approved) == 2
    assert all(o["verdict"] == "approved" for o in approved)
    registry.close()


# === 9. KPI 계산 정확 ===

def test_pilot_kpi_calculation() -> None:
    """10개 outcome에 대해 5개 KPI가 정확히 계산된다."""
    registry = _make_registry_with_skills("skill_a")

    # 6 approved, 2 edited, 1 rejected, 1 redo = 10 total
    for _ in range(6):
        registry.add_outcome(skill_id="skill_a", verdict="approved")
    for _ in range(2):
        registry.add_outcome(skill_id="skill_a", verdict="edited")
    registry.add_outcome(skill_id="skill_a", verdict="rejected")
    registry.add_outcome(skill_id="skill_a", verdict="redo")

    kpi = registry.get_pilot_kpi()
    assert kpi["total"] == 10
    assert kpi["approved"] == 6
    assert kpi["edited"] == 2
    assert kpi["rejected"] == 1
    assert kpi["redo"] == 1
    assert kpi["acceptance_rate"] == 0.6
    assert kpi["edit_rate"] == 0.2
    assert kpi["reject_rate"] == 0.1
    assert kpi["redo_rate"] == 0.1
    assert kpi["net_useful_rate"] == 0.8  # (6+2)/10
    registry.close()


# === 10. outcome 없음 → rate 0.0 ===

def test_pilot_kpi_empty() -> None:
    """outcome이 없으면 total=0, 모든 rate=0.0이다."""
    registry = SkillRegistry(":memory:")

    kpi = registry.get_pilot_kpi()
    assert kpi["total"] == 0
    assert kpi["acceptance_rate"] == 0.0
    assert kpi["net_useful_rate"] == 0.0
    registry.close()


# === 11. days 필터 ===

def test_pilot_kpi_days_filter() -> None:
    """days 필터가 최근 N일만 집계한다."""
    registry = _make_registry_with_skills("skill_a")

    # 최근 outcome
    registry.add_outcome(skill_id="skill_a", verdict="approved")

    # 오래된 outcome (수동 INSERT)
    old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    registry._conn.execute(
        """
        INSERT INTO outcomes (skill_id, domain, verdict, human_note, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("skill_a", "testing", "rejected", "", old_date),
    )
    registry._conn.commit()

    # 전체: 2개
    kpi_all = registry.get_pilot_kpi()
    assert kpi_all["total"] == 2

    # 최근 7일: 1개 (approved만)
    kpi_7d = registry.get_pilot_kpi(days=7)
    assert kpi_7d["total"] == 1
    assert kpi_7d["approved"] == 1
    registry.close()


# === 12. skill_id 필터 ===

def test_pilot_kpi_skill_filter() -> None:
    """skill_id 필터가 해당 스킬만 집계한다."""
    registry = _make_registry_with_skills("skill_a", "skill_b")

    registry.add_outcome(skill_id="skill_a", verdict="approved")
    registry.add_outcome(skill_id="skill_a", verdict="approved")
    registry.add_outcome(skill_id="skill_b", verdict="rejected")

    kpi_a = registry.get_pilot_kpi(skill_id="skill_a")
    assert kpi_a["total"] == 2
    assert kpi_a["approved"] == 2

    kpi_b = registry.get_pilot_kpi(skill_id="skill_b")
    assert kpi_b["total"] == 1
    assert kpi_b["rejected"] == 1
    registry.close()


# === 13. 스킬별 breakdown ===

def test_pilot_kpi_by_skill() -> None:
    """스킬별 KPI breakdown이 정확하다."""
    registry = _make_registry_with_skills("skill_a", "skill_b")

    for _ in range(3):
        registry.add_outcome(skill_id="skill_a", verdict="approved")
    registry.add_outcome(skill_id="skill_a", verdict="rejected")

    registry.add_outcome(skill_id="skill_b", verdict="edited")
    registry.add_outcome(skill_id="skill_b", verdict="approved")

    by_skill = registry.get_pilot_kpi_by_skill()
    assert len(by_skill) == 2

    # total 내림차순이므로 skill_a가 먼저
    assert by_skill[0]["skill_id"] == "skill_a"
    assert by_skill[0]["total"] == 4
    assert by_skill[0]["approved"] == 3
    assert by_skill[0]["rejected"] == 1

    assert by_skill[1]["skill_id"] == "skill_b"
    assert by_skill[1]["total"] == 2
    assert by_skill[1]["net_useful_rate"] == 1.0  # (1+1)/2
    registry.close()


# === 14. net_useful_rate 정확 ===

def test_pilot_net_useful_rate() -> None:
    """net_useful_rate = (approved + edited) / total이다."""
    registry = _make_registry_with_skills("skill_a")

    registry.add_outcome(skill_id="skill_a", verdict="approved")
    registry.add_outcome(skill_id="skill_a", verdict="edited")
    registry.add_outcome(skill_id="skill_a", verdict="rejected")
    registry.add_outcome(skill_id="skill_a", verdict="redo")

    kpi = registry.get_pilot_kpi()
    assert kpi["net_useful_rate"] == 0.5  # 2/4
    registry.close()


# === 15. pilot report 출력 ===

def test_pilot_report_output(capsys: pytest.CaptureFixture[str]) -> None:
    """pilot CLI가 표를 출력한다."""
    from engine.cli import _print_pilot_report

    report = {
        "global": {
            "total": 10,
            "approved": 6,
            "edited": 2,
            "rejected": 1,
            "redo": 1,
            "acceptance_rate": 0.6,
            "edit_rate": 0.2,
            "reject_rate": 0.1,
            "redo_rate": 0.1,
            "net_useful_rate": 0.8,
        },
        "by_skill": [
            {
                "skill_id": "csv_to_chart",
                "total": 6,
                "approved": 4,
                "edited": 1,
                "rejected": 1,
                "redo": 0,
                "net_useful_rate": 0.833,
            },
        ],
        "period_days": None,
        "skill_filter": None,
    }

    _print_pilot_report(report)
    captured = capsys.readouterr().out

    assert "Pilot Report" in captured
    assert "Net useful" in captured
    assert "80.0%" in captured
    assert "csv_to_chart" in captured


# === 16. outcome CLI happy path (engine.record_outcome) ===

def test_outcome_cli_happy_path() -> None:
    """record_outcome이 정상 동작한다."""
    from engine.loop import CambrianEngine

    engine = CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path=":memory:",
    )

    oid = engine.record_outcome(
        skill_id="hello_world",
        verdict="approved",
        human_note="잘 됨",
    )
    assert oid > 0

    report = engine.get_pilot_report()
    assert report["global"]["total"] == 1
    assert report["global"]["approved"] == 1
    engine.close()


# === 17. stats에 pilot 요약 ===

def test_stats_pilot_summary() -> None:
    """get_pilot_kpi 결과에 total과 net_useful_rate가 포함된다."""
    registry = _make_registry_with_skills("skill_a")

    registry.add_outcome(skill_id="skill_a", verdict="approved")
    registry.add_outcome(skill_id="skill_a", verdict="edited")
    registry.add_outcome(skill_id="skill_a", verdict="rejected")

    kpi = registry.get_pilot_kpi()
    assert kpi["total"] == 3
    assert "net_useful_rate" in kpi
    assert kpi["net_useful_rate"] == round(2 / 3, 3)
    registry.close()


# === 추가: get_pilot_report 통합 ===

def test_get_pilot_report_integration() -> None:
    """get_pilot_report가 global + by_skill 모두 반환한다."""
    from engine.loop import CambrianEngine

    engine = CambrianEngine(
        schemas_dir="schemas",
        skills_dir="skills",
        skill_pool_dir="skill_pool",
        db_path=":memory:",
    )

    engine.record_outcome("hello_world", "approved")
    engine.record_outcome("hello_world", "edited")

    report = engine.get_pilot_report()
    assert report["global"]["total"] == 2
    assert len(report["by_skill"]) >= 1
    assert report["period_days"] is None
    assert report["skill_filter"] is None

    # 특정 스킬 필터
    report_skill = engine.get_pilot_report(skill_id="hello_world")
    assert report_skill["global"]["total"] == 2
    assert report_skill["by_skill"] == []  # 스킬 필터 시 breakdown 없음

    engine.close()


# === 추가: 빈 데이터 pilot report 출력 ===

def test_pilot_report_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """데이터 없을 때 안내 메시지를 출력한다."""
    from engine.cli import _print_pilot_report

    report = {
        "global": {
            "total": 0, "approved": 0, "edited": 0,
            "rejected": 0, "redo": 0,
            "acceptance_rate": 0.0, "edit_rate": 0.0,
            "reject_rate": 0.0, "redo_rate": 0.0,
            "net_useful_rate": 0.0,
        },
        "by_skill": [],
        "period_days": None,
        "skill_filter": None,
    }

    _print_pilot_report(report)
    captured = capsys.readouterr().out
    assert "No pilot outcomes recorded" in captured
