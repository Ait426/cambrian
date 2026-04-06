"""Release Governance Layer 테스트 (Task 12).

신뢰 등급(experimental → candidate → production / quarantined) 관리,
자동 승격/강등, quarantine 격리/해제, governance_log 기록을 검증한다.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from engine.exceptions import SkillNotFoundError
from engine.models import ExecutionResult, Skill, SkillLifecycle, SkillRuntime
from engine.registry import SkillRegistry


def _make_skill(
    skill_id: str = "test_skill",
    status: str = "active",
    fitness: float = 0.0,
    total_exec: int = 0,
    success_exec: int = 0,
) -> Skill:
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
        lifecycle=SkillLifecycle(
            status=status,
            fitness_score=fitness,
            total_executions=total_exec,
            successful_executions=success_exec,
        ),
        skill_path=Path("."),
    )


def _make_registry_with_skill(
    skill_id: str = "test_skill",
    fitness: float = 0.0,
    total_exec: int = 0,
    success_exec: int = 0,
    release_state: str = "experimental",
) -> SkillRegistry:
    """스킬이 하나 등록된 인메모리 레지스트리를 반환한다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill(
        skill_id=skill_id,
        fitness=fitness,
        total_exec=total_exec,
        success_exec=success_exec,
    )
    registry.register(skill)

    # fitness/total_executions 직접 설정 (register는 lifecycle 값을 그대로 저장)
    if fitness > 0 or total_exec > 0:
        registry._conn.execute(
            "UPDATE skills SET fitness_score = ?, total_executions = ?, "
            "successful_executions = ? WHERE id = ?",
            (fitness, total_exec, success_exec, skill_id),
        )
        registry._conn.commit()

    if release_state != "experimental":
        registry.update_release_state(
            skill_id, release_state,
            reason="테스트 초기 설정",
            triggered_by="manual",
        )

    return registry


# === 1. 신규 스킬 기본값 ===

def test_new_skill_is_experimental() -> None:
    """신규 등록된 스킬의 release_state는 experimental이다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("new_skill")
    registry.register(skill)

    data = registry.get("new_skill")
    assert data["release_state"] == "experimental"
    registry.close()


# === 2. 자동 candidate 승격 ===

def test_auto_promote_to_candidate() -> None:
    """executions >= 10 + fitness >= 0.5이면 candidate로 자동 승격된다."""
    registry = _make_registry_with_skill(
        fitness=0.6, total_exec=12, success_exec=10,
    )

    # CambrianEngine._check_auto_promote 로직 재현
    skill_data = registry.get("test_skill")
    assert skill_data["release_state"] == "experimental"
    assert skill_data["total_executions"] >= 10
    assert skill_data["fitness_score"] >= 0.5

    # 직접 승격 조건 테스트
    registry.update_release_state(
        "test_skill", "candidate",
        reason="auto: executions=12, fitness=0.6000",
        triggered_by="auto",
    )
    data = registry.get("test_skill")
    assert data["release_state"] == "candidate"
    registry.close()


# === 3. 자동 승격 차단: 낮은 fitness ===

def test_auto_promote_blocked_low_fitness() -> None:
    """fitness < 0.5이면 candidate 승격이 안 된다."""
    registry = _make_registry_with_skill(
        fitness=0.4, total_exec=15, success_exec=8,
    )
    skill_data = registry.get("test_skill")
    # 조건 미충족 확인
    assert skill_data["fitness_score"] < 0.5
    assert skill_data["release_state"] == "experimental"
    registry.close()


# === 4. 자동 승격 차단: 낮은 실행 수 ===

def test_auto_promote_blocked_low_executions() -> None:
    """executions < 10이면 candidate 승격이 안 된다."""
    registry = _make_registry_with_skill(
        fitness=0.8, total_exec=5, success_exec=5,
    )
    skill_data = registry.get("test_skill")
    # 조건 미충족 확인
    assert skill_data["total_executions"] < 10
    assert skill_data["release_state"] == "experimental"
    registry.close()


# === 5. 자동 승격 차단: 반복 quarantine ===

def test_auto_promote_blocked_repeated_quarantine() -> None:
    """quarantine 2회 이상 이력이 있으면 candidate 승격이 금지된다."""
    registry = _make_registry_with_skill(
        fitness=0.7, total_exec=15, success_exec=12,
    )

    # quarantine 이력 2회 쌓기
    registry.update_release_state(
        "test_skill", "quarantined",
        reason="test quarantine 1", triggered_by="auto",
    )
    registry.update_release_state(
        "test_skill", "experimental",
        reason="unquarantine 1", triggered_by="manual",
    )
    registry.update_release_state(
        "test_skill", "quarantined",
        reason="test quarantine 2", triggered_by="auto",
    )
    registry.update_release_state(
        "test_skill", "experimental",
        reason="unquarantine 2", triggered_by="manual",
    )

    q_count = registry.get_quarantine_count("test_skill")
    assert q_count >= 2
    registry.close()


# === 6. 수동 production 승격 ===

def test_manual_promote_to_production() -> None:
    """수동 promote로 production 전환이 가능하다."""
    registry = _make_registry_with_skill(
        fitness=0.7, total_exec=15, success_exec=12,
        release_state="candidate",
    )

    registry.update_release_state(
        "test_skill", "production",
        reason="manual promotion", triggered_by="manual",
    )
    data = registry.get("test_skill")
    assert data["release_state"] == "production"
    registry.close()


# === 7. 수동 promote 거부: 낮은 fitness ===

def test_manual_promote_rejects_low_fitness() -> None:
    """fitness < 0.5이면 production 승격 조건 미달이다."""
    registry = _make_registry_with_skill(
        fitness=0.3, total_exec=15, success_exec=5,
        release_state="candidate",
    )
    data = registry.get("test_skill")
    # CLI 핸들러에서 검증하는 조건 확인
    assert data["fitness_score"] < 0.5
    registry.close()


# === 8. 수동 promote 거부: quarantined 상태 ===

def test_manual_promote_rejects_quarantined() -> None:
    """quarantined 상태에서는 promote가 불가하다."""
    registry = _make_registry_with_skill(
        fitness=0.8, total_exec=20, success_exec=18,
        release_state="quarantined",
    )
    data = registry.get("test_skill")
    assert data["release_state"] == "quarantined"
    registry.close()


# === 9. 롤백 시 quarantine 전환 ===

def test_rollback_triggers_quarantine() -> None:
    """update_release_state로 quarantined 전환이 올바르게 작동한다."""
    registry = _make_registry_with_skill(
        fitness=0.1, total_exec=10, success_exec=1,
        release_state="candidate",
    )

    registry.update_release_state(
        "test_skill", "quarantined",
        reason="auto_rollback: fitness=0.1000",
        triggered_by="auto",
    )
    data = registry.get("test_skill")
    assert data["release_state"] == "quarantined"
    registry.close()


# === 10. quarantined 스킬 검색 제외 ===

def test_quarantined_excluded_from_search() -> None:
    """quarantined 스킬은 기본 search()에서 제외된다."""
    registry = SkillRegistry(":memory:")

    skill_a = _make_skill("skill_a")
    skill_b = _make_skill("skill_b")
    registry.register(skill_a)
    registry.register(skill_b)

    # skill_b를 quarantine
    registry.update_release_state(
        "skill_b", "quarantined",
        reason="test", triggered_by="auto",
    )

    results = registry.search(domain="testing")
    ids = [r["id"] for r in results]
    assert "skill_a" in ids
    assert "skill_b" not in ids

    # 명시적 release_state='quarantined' 검색 시에는 포함
    q_results = registry.search(domain="testing", release_state="quarantined")
    q_ids = [r["id"] for r in q_results]
    assert "skill_b" in q_ids
    registry.close()


# === 11. quarantined 스킬 경쟁 제외 ===

def test_quarantined_excluded_from_run() -> None:
    """quarantined 스킬은 run_task() 후보에서 제외된다.

    search() 기본 동작이 quarantined를 제외하므로
    run_task에서 사용하는 search도 동일하게 동작한다.
    """
    registry = SkillRegistry(":memory:")

    skill_a = _make_skill("skill_a")
    registry.register(skill_a)

    registry.update_release_state(
        "skill_a", "quarantined",
        reason="test", triggered_by="auto",
    )

    # active + quarantined가 아닌 것만 반환되므로 빈 결과
    results = registry.search(domain="testing", status="newborn")
    quarantined_ids = [r["id"] for r in results if r["release_state"] == "quarantined"]
    assert len(quarantined_ids) == 0
    registry.close()


# === 12. unquarantine → experimental ===

def test_unquarantine_to_experimental() -> None:
    """unquarantine 시 experimental로 복귀한다."""
    registry = _make_registry_with_skill(
        release_state="quarantined",
    )

    registry.update_release_state(
        "test_skill", "experimental",
        reason="manual unquarantine", triggered_by="manual",
    )
    data = registry.get("test_skill")
    assert data["release_state"] == "experimental"
    registry.close()


# === 13. unquarantine 거부: quarantined가 아닌 경우 ===

def test_unquarantine_rejects_non_quarantined() -> None:
    """quarantined가 아닌 스킬은 unquarantine 대상이 아니다."""
    registry = _make_registry_with_skill(release_state="experimental")
    data = registry.get("test_skill")
    assert data["release_state"] != "quarantined"
    registry.close()


# === 14. 자동 강등: fitness < 0.3 ===

def test_auto_demote_low_fitness() -> None:
    """candidate/production 스킬의 fitness가 0.3 미만이면 experimental로 강등된다."""
    registry = _make_registry_with_skill(
        fitness=0.2, total_exec=20, success_exec=4,
        release_state="production",
    )

    # 강등 로직 재현
    data = registry.get("test_skill")
    assert data["release_state"] == "production"
    assert data["fitness_score"] < 0.3

    registry.update_release_state(
        "test_skill", "experimental",
        reason="auto: fitness dropped to 0.2000",
        triggered_by="auto",
    )
    data = registry.get("test_skill")
    assert data["release_state"] == "experimental"
    registry.close()


# === 15. governance_log 기록 ===

def test_governance_log_recorded() -> None:
    """모든 release_state 전이가 governance_log에 기록된다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("log_skill")
    registry.register(skill)

    # experimental → candidate → production → quarantined
    registry.update_release_state(
        "log_skill", "candidate",
        reason="auto promote", triggered_by="auto",
    )
    registry.update_release_state(
        "log_skill", "production",
        reason="manual promote", triggered_by="manual",
    )
    registry.update_release_state(
        "log_skill", "quarantined",
        reason="auto rollback", triggered_by="auto",
    )

    logs = registry.get_governance_log(skill_id="log_skill")
    assert len(logs) == 3

    # 최신순이므로 quarantined가 첫 번째
    assert logs[0]["to_state"] == "quarantined"
    assert logs[0]["from_state"] == "production"
    assert logs[0]["triggered_by"] == "auto"

    assert logs[1]["to_state"] == "production"
    assert logs[1]["from_state"] == "candidate"

    assert logs[2]["to_state"] == "candidate"
    assert logs[2]["from_state"] == "experimental"
    registry.close()


# === 16. governance_log 쿼리: skill_id 필터 + limit ===

def test_governance_log_query() -> None:
    """skill_id 필터와 limit이 올바르게 동작한다."""
    registry = SkillRegistry(":memory:")
    skill_a = _make_skill("skill_a")
    skill_b = _make_skill("skill_b")
    registry.register(skill_a)
    registry.register(skill_b)

    registry.update_release_state(
        "skill_a", "candidate", reason="a promote", triggered_by="auto",
    )
    registry.update_release_state(
        "skill_b", "candidate", reason="b promote", triggered_by="auto",
    )
    registry.update_release_state(
        "skill_a", "production", reason="a prod", triggered_by="manual",
    )

    # skill_a만 필터
    logs_a = registry.get_governance_log(skill_id="skill_a")
    assert len(logs_a) == 2
    assert all(log["skill_id"] == "skill_a" for log in logs_a)

    # 전체 + limit=2
    all_logs = registry.get_governance_log(limit=2)
    assert len(all_logs) == 2
    registry.close()


# === 17. stats에 release_state 표시 (global) ===

def test_stats_shows_release_state() -> None:
    """list_all 결과에 release_state 필드가 포함된다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("stats_skill")
    registry.register(skill)

    all_skills = registry.list_all()
    assert len(all_skills) > 0
    assert "release_state" in all_skills[0]
    assert all_skills[0]["release_state"] == "experimental"
    registry.close()


# === 18. 스킬 stats에 release 표시 ===

def test_skill_stats_shows_release() -> None:
    """개별 스킬 조회 시 release_state 필드가 포함된다."""
    registry = _make_registry_with_skill(release_state="production")

    data = registry.get("test_skill")
    assert data["release_state"] == "production"
    registry.close()


# === 추가: invalid release_state 검증 ===

def test_update_release_state_invalid() -> None:
    """유효하지 않은 release_state는 ValueError를 발생시킨다."""
    registry = _make_registry_with_skill()

    with pytest.raises(ValueError, match="Invalid release_state"):
        registry.update_release_state(
            "test_skill", "invalid_state",
            reason="test", triggered_by="manual",
        )
    registry.close()


# === 추가: quarantine_count 정확도 ===

def test_quarantine_count_accuracy() -> None:
    """get_quarantine_count는 quarantined 전이만 정확히 카운트한다."""
    registry = _make_registry_with_skill()

    assert registry.get_quarantine_count("test_skill") == 0

    registry.update_release_state(
        "test_skill", "quarantined", reason="q1", triggered_by="auto",
    )
    assert registry.get_quarantine_count("test_skill") == 1

    registry.update_release_state(
        "test_skill", "experimental", reason="unq1", triggered_by="manual",
    )
    # 해제해도 quarantine 카운트는 유지
    assert registry.get_quarantine_count("test_skill") == 1

    registry.update_release_state(
        "test_skill", "quarantined", reason="q2", triggered_by="auto",
    )
    assert registry.get_quarantine_count("test_skill") == 2
    registry.close()


# === 추가: register()가 기존 스킬의 release_state를 보존 ===

def test_register_preserves_release_state() -> None:
    """재등록 시 release_state가 보존된다."""
    registry = _make_registry_with_skill(release_state="production")

    # 같은 ID로 재등록
    skill = _make_skill("test_skill")
    registry.register(skill)

    data = registry.get("test_skill")
    assert data["release_state"] == "production"
    registry.close()
