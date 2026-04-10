"""CambrianEngine 유닛 테스트."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from engine.loop import CambrianEngine
from engine.models import ExecutionResult, Skill, SkillLifecycle, SkillRuntime
from engine.registry import SkillRegistry


def _make_skill(skill_id: str, status: str = "newborn") -> Skill:
    """테스트용 최소 Skill 객체를 생성한다."""
    return Skill(
        id=skill_id,
        version="1.0.0",
        name="Test Skill",
        description="A test skill",
        domain="testing",
        tags=["test"],
        mode="a",
        runtime=SkillRuntime(language="python"),
        lifecycle=SkillLifecycle(status=status),
        skill_path=Path("."),
    )


def _write_mode_b_skill(
    base_dir: Path,
    skill_id: str,
    domain: str,
    tags: list[str],
    result_value: str = "ok",
    should_fail: bool = False,
    fitness_score: float = 0.0,
) -> Path:
    """Mode B 테스트 스킬 디렉토리를 생성한다."""
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": "Test",
        "description": "test",
        "domain": domain,
        "tags": tags,
        "mode": "b",
        "created_at": "2026-04-03",
        "updated_at": "2026-04-03",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 10,
        },
        "lifecycle": {
            "status": "active",
            "fitness_score": fitness_score,
            "total_executions": 0,
            "successful_executions": 0,
            "last_used": None,
            "crystallized_at": None,
        },
    }
    interface = {
        "input": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "x"}},
            "required": [],
        },
        "output": {
            "type": "object",
            "properties": {"result": {"type": "string", "description": "r"}},
            "required": ["result"],
        },
    }

    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(interface, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")

    execute_dir = skill_dir / "execute"
    execute_dir.mkdir(exist_ok=True)
    if should_fail:
        execute_body = (
            "from __future__ import annotations\n"
            "import json, sys\n\n"
            "def run(input_data: dict) -> dict:\n"
            "    _ = input_data\n"
            "    raise RuntimeError('boom')\n\n"
            "if __name__ == '__main__':\n"
            "    raw = sys.stdin.read()\n"
            "    data = json.loads(raw) if raw.strip() else {}\n"
            "    result = run(data)\n"
            "    print(json.dumps(result, ensure_ascii=False))\n"
        )
    else:
        execute_body = (
            "from __future__ import annotations\n"
            "import json, sys\n\n"
            "def run(input_data: dict) -> dict:\n"
            "    _ = input_data\n"
            f"    return {{'result': '{result_value}'}}\n\n"
            "if __name__ == '__main__':\n"
            "    raw = sys.stdin.read()\n"
            "    data = json.loads(raw) if raw.strip() else {}\n"
            "    result = run(data)\n"
            "    print(json.dumps(result, ensure_ascii=False))\n"
        )
    (execute_dir / "main.py").write_text(execute_body, encoding="utf-8")
    return skill_dir


def _write_mode_a_skill(
    base_dir: Path,
    skill_id: str,
    domain: str,
    tags: list[str],
    fitness_score: float,
) -> Path:
    """Mode A 테스트 스킬 디렉토리를 생성한다."""
    skill_dir = base_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": "Test",
        "description": "test",
        "domain": domain,
        "tags": tags,
        "mode": "a",
        "created_at": "2026-04-03",
        "updated_at": "2026-04-03",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 10,
        },
        "lifecycle": {
            "status": "active",
            "fitness_score": fitness_score,
            "total_executions": 0,
            "successful_executions": 0,
            "last_used": None,
            "crystallized_at": None,
        },
    }
    interface = {
        "input": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "x"}},
            "required": [],
        },
        "output": {
            "type": "object",
            "properties": {"result": {"type": "string", "description": "r"}},
            "required": ["result"],
        },
    }

    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(interface, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "# Test\nRespond with JSON containing result.",
        encoding="utf-8",
    )
    return skill_dir


def test_engine_init_registers_seeds(schemas_dir: Path, tmp_path: Path) -> None:
    """엔진 생성 시 skills/ 디렉토리의 스킬이 자동 등록된다."""
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "skill_pool",
    )

    assert engine.get_skill_count() >= 1
    skills = engine.list_skills()
    ids = [skill["id"] for skill in skills]
    assert "hello_world" in ids


def test_run_task_success(schemas_dir: Path, tmp_path: Path) -> None:
    """hello_world 스킬로 처리 가능한 태스크는 성공한다."""
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "skill_pool",
    )

    result = engine.run_task(
        domain="utility",
        tags=["greeting"],
        input_data={"text": "Cambrian"},
    )

    assert result.success is True
    assert result.output is not None
    assert result.output["greeting"] == "Hello, Cambrian!"


def test_run_task_no_matching_skill(schemas_dir: Path, tmp_path: Path) -> None:
    """domain이 매칭되지 않고 외부 소스도 없으면 실패."""
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "skill_pool",
    )

    result = engine.run_task(
        domain="nonexistent_domain",
        tags=["nonexistent"],
        input_data={"value": "test"},
    )

    assert result.success is False


def test_lifecycle_updated_after_execution(schemas_dir: Path, tmp_path: Path) -> None:
    """실행 후 Registry의 total_executions가 증가한다."""
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "skill_pool",
    )

    engine.run_task(
        domain="utility",
        tags=["greeting"],
        input_data={"text": "test"},
    )
    skill_data = engine.get_registry().get("hello_world")

    assert skill_data["total_executions"] >= 1


def test_run_task_with_crash_skill(schemas_dir: Path, tmp_path: Path) -> None:
    """crash_skill 도메인으로 태스크를 주면 실패하고 재시도 후 최종 실패."""
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "skill_pool",
    )

    result = engine.run_task(
        domain="testing",
        tags=["error"],
        input_data={"message": "crash test"},
        max_retries=1,
    )

    assert result.success is False


def test_no_retries(schemas_dir: Path, tmp_path: Path) -> None:
    """max_retries=0이면 첫 실패에서 바로 최종 결과 반환."""
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir="skills",
        skill_pool_dir=tmp_path / "skill_pool",
    )

    result = engine.run_task(
        domain="testing",
        tags=["error"],
        input_data={"message": "crash"},
        max_retries=0,
    )

    assert result.success is False


# === Phase 2: decay + fossil 테스트 ===


def test_decay_active_to_dormant() -> None:
    """31일 이상 미사용 active 스킬은 dormant로 퇴화한다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("active_old", status="active")
    registry.register(skill)

    now = datetime.now(timezone.utc)
    days_ago_31 = (now - timedelta(days=31)).isoformat()
    registry._conn.execute(
        "UPDATE skills SET last_used = ?, registered_at = ? WHERE id = ?",
        (days_ago_31, days_ago_31, skill.id),
    )
    registry._conn.commit()

    result = registry.decay()
    stored = registry.get(skill.id)

    assert stored["status"] == "dormant"
    assert result == {"dormant": 1, "fossil": 0}


def test_decay_dormant_to_fossil() -> None:
    """91일 이상 미사용 dormant 스킬은 fossil로 퇴화한다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("dormant_old", status="dormant")
    registry.register(skill)

    now = datetime.now(timezone.utc)
    days_ago_91 = (now - timedelta(days=91)).isoformat()
    registry._conn.execute(
        "UPDATE skills SET last_used = ?, registered_at = ? WHERE id = ?",
        (days_ago_91, days_ago_91, skill.id),
    )
    registry._conn.commit()

    result = registry.decay()
    stored = registry.get(skill.id)

    assert stored["status"] == "fossil"
    assert result["fossil"] >= 1


def test_decay_null_last_used() -> None:
    """last_used가 NULL이고 31일 이상 지난 newborn 스킬은 dormant가 된다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("newborn_old", status="newborn")
    registry.register(skill)

    now = datetime.now(timezone.utc)
    days_ago_31 = (now - timedelta(days=31)).isoformat()
    registry._conn.execute(
        "UPDATE skills SET last_used = NULL, registered_at = ? WHERE id = ?",
        (days_ago_31, skill.id),
    )
    registry._conn.commit()

    registry.decay()
    stored = registry.get(skill.id)

    assert stored["status"] == "dormant"


def test_decay_recent_untouched() -> None:
    """최근 사용한 active 스킬은 상태가 유지된다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("active_recent", status="active")
    registry.register(skill)

    now = datetime.now(timezone.utc)
    days_ago_5 = (now - timedelta(days=5)).isoformat()
    registry._conn.execute(
        "UPDATE skills SET last_used = ?, registered_at = ? WHERE id = ?",
        (days_ago_5, days_ago_5, skill.id),
    )
    registry._conn.commit()

    result = registry.decay()
    stored = registry.get(skill.id)

    assert stored["status"] == "active"
    assert result == {"dormant": 0, "fossil": 0}


def test_decay_returns_counts() -> None:
    """decay는 dormant와 fossil 전환 개수를 정확히 반환한다."""
    registry = SkillRegistry(":memory:")
    skill_a = _make_skill("skill_a", status="active")
    skill_b = _make_skill("skill_b", status="dormant")
    skill_c = _make_skill("skill_c", status="active")
    registry.register(skill_a)
    registry.register(skill_b)
    registry.register(skill_c)

    now = datetime.now(timezone.utc)
    days_ago_31 = (now - timedelta(days=31)).isoformat()
    days_ago_91 = (now - timedelta(days=91)).isoformat()
    days_ago_5 = (now - timedelta(days=5)).isoformat()

    registry._conn.execute(
        "UPDATE skills SET last_used = ?, registered_at = ? WHERE id = ?",
        (days_ago_31, days_ago_31, skill_a.id),
    )
    registry._conn.execute(
        "UPDATE skills SET last_used = ?, registered_at = ? WHERE id = ?",
        (days_ago_91, days_ago_91, skill_b.id),
    )
    registry._conn.execute(
        "UPDATE skills SET last_used = ?, registered_at = ? WHERE id = ?",
        (days_ago_5, days_ago_5, skill_c.id),
    )
    registry._conn.commit()

    result = registry.decay()

    assert result == {"dormant": 1, "fossil": 1}


def test_search_excludes_fossil_by_default() -> None:
    """status 필터가 없으면 fossil 스킬은 검색에서 제외된다."""
    registry = SkillRegistry(":memory:")
    skill_a = _make_skill("active_skill", status="active")
    skill_b = _make_skill("fossil_skill", status="fossil")
    registry.register(skill_a)
    registry.register(skill_b)

    results = registry.search(domain="testing")

    assert len(results) == 1
    assert results[0]["id"] == skill_a.id


def test_search_explicit_fossil() -> None:
    """status='fossil'을 명시하면 fossil 스킬만 반환한다."""
    registry = SkillRegistry(":memory:")
    skill_a = _make_skill("active_skill_explicit", status="active")
    skill_b = _make_skill("fossil_skill_explicit", status="fossil")
    registry.register(skill_a)
    registry.register(skill_b)

    results = registry.search(domain="testing", status="fossil")

    assert len(results) == 1
    assert results[0]["id"] == skill_b.id


def test_search_with_status_filter_unchanged() -> None:
    """명시적 status 필터 동작은 기존과 동일하게 유지된다."""
    registry = SkillRegistry(":memory:")
    skill_a = _make_skill("active_filtered", status="active")
    skill_b = _make_skill("newborn_filtered", status="newborn")
    registry.register(skill_a)
    registry.register(skill_b)

    results = registry.search(domain="testing", status="active")

    assert len(results) == 1
    assert results[0]["id"] == skill_a.id


# === Phase 2: 경쟁 실행 + decay 테스트 ===


def test_decay_called_on_init(schemas_dir: Path, tmp_path: Path) -> None:
    """엔진 초기화 시 decay가 호출되어 기존 DB의 오래된 스킬을 dormant로 바꾼다."""
    db_path = tmp_path / "test.db"
    registry = SkillRegistry(db_path)
    skill = Skill(
        id="old_skill",
        version="1.0.0",
        name="Old Skill",
        description="old",
        domain="testing",
        tags=["old"],
        mode="a",
        runtime=SkillRuntime(language="python"),
        lifecycle=SkillLifecycle(status="active"),
        skill_path=tmp_path / "skills" / "old_skill",
    )
    registry.register(skill)

    old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    registry._conn.execute(
        "UPDATE skills SET last_used = ?, registered_at = ? WHERE id = ?",
        (old_date, old_date, skill.id),
    )
    registry._conn.commit()
    registry.close()

    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    skills_dir.mkdir(parents=True, exist_ok=True)
    pool_dir.mkdir(parents=True, exist_ok=True)

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=db_path,
    )

    stored = engine._registry.get(skill.id)
    assert stored["status"] == "dormant"


def test_competitive_single_candidate(schemas_dir: Path, tmp_path: Path) -> None:
    """후보가 하나면 경쟁 없이 단일 실행으로 성공한다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir,
        "hello_world",
        domain="utility",
        tags=["greeting"],
        result_value="hello",
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )

    result = engine.run_task(
        domain="utility",
        tags=["greeting"],
        input_data={"text": "hi"},
    )

    assert result.success is True
    assert result.skill_id == "hello_world"


def test_competitive_multiple_mode_b(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """여러 Mode B 후보가 성공하면 실행 시간이 짧은 후보를 반환한다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir,
        "skill_a",
        domain="comp_test",
        tags=["compete"],
        result_value="a",
        fitness_score=0.2,
    )
    _write_mode_b_skill(
        skills_dir,
        "skill_b",
        domain="comp_test",
        tags=["compete"],
        result_value="b",
        fitness_score=0.8,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )

    # 실행 시간을 제어하여 skill_a(50ms) < skill_b(200ms) 설정
    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        """실행 시간을 제어한 가짜 실행기."""
        _ = input_data
        skill_id = getattr(skill, "id")
        time_map = {"skill_a": 50, "skill_b": 200}
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"result": skill_id},
            execution_time_ms=time_map[skill_id],
            mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.run_task(
        domain="comp_test",
        tags=["compete"],
        input_data={},
    )

    assert result.success is True
    # 실행 시간이 짧은 skill_a가 승리 (fitness가 낮아도)
    assert result.skill_id == "skill_a"


def test_competitive_all_fail(schemas_dir: Path, tmp_path: Path) -> None:
    """경쟁 실행 후보가 모두 실패하면 최종 결과도 실패다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir,
        "fail_a",
        domain="fail_test",
        tags=["fail"],
        should_fail=True,
    )
    _write_mode_b_skill(
        skills_dir,
        "fail_b",
        domain="fail_test",
        tags=["fail"],
        should_fail=True,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )

    result = engine.run_task(
        domain="fail_test",
        tags=["fail"],
        input_data={},
        max_retries=0,
    )

    assert result.success is False


def test_competitive_mode_a_limited(
    schemas_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode A 경쟁 실행은 fitness 상위 2개까지만 실행한다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_a_skill(
        skills_dir,
        "mode_a_high",
        domain="limit_test",
        tags=["limit"],
        fitness_score=0.9,
    )
    _write_mode_a_skill(
        skills_dir,
        "mode_a_mid",
        domain="limit_test",
        tags=["limit"],
        fitness_score=0.8,
    )
    _write_mode_a_skill(
        skills_dir,
        "mode_a_low",
        domain="limit_test",
        tags=["limit"],
        fitness_score=0.1,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )

    executed_ids: list[str] = []

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        """실행된 스킬 ID를 기록하며 성공 결과를 반환한다."""
        _ = input_data
        skill_id = getattr(skill, "id")
        executed_ids.append(skill_id)
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"result": skill_id},
            execution_time_ms=10,
            mode="a",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.run_task(
        domain="limit_test",
        tags=["limit"],
        input_data={},
    )

    assert result.success is True
    assert len(executed_ids) == 2
    assert "mode_a_low" not in executed_ids


def test_competitive_fitness_all_updated(schemas_dir: Path, tmp_path: Path) -> None:
    """경쟁 실행된 성공 후보들의 lifecycle 실행 횟수가 모두 갱신된다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir,
        "update_a",
        domain="update_test",
        tags=["update"],
        result_value="a",
        fitness_score=0.2,
    )
    _write_mode_b_skill(
        skills_dir,
        "update_b",
        domain="update_test",
        tags=["update"],
        result_value="b",
        fitness_score=0.4,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )

    result = engine.run_task(
        domain="update_test",
        tags=["update"],
        input_data={},
    )

    skill_a = engine._registry.get("update_a")
    skill_b = engine._registry.get("update_b")

    assert result.success is True
    assert skill_a["total_executions"] >= 1
    assert skill_b["total_executions"] >= 1


# === 경쟁 실행 승자 선택 테스트 (execution_time 기반) ===


def test_competitive_mode_b_fastest_wins(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode B 2개 후보: 실행 시간이 짧은 쪽이 승리한다 (fitness 무관)."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "fast_b", domain="speed", tags=["race"],
        result_value="fast", fitness_score=0.1,
    )
    _write_mode_b_skill(
        skills_dir, "slow_b", domain="speed", tags=["race"],
        result_value="slow", fitness_score=0.9,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        """fast_b=30ms, slow_b=500ms."""
        _ = input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": sid},
            execution_time_ms=30 if sid == "fast_b" else 500,
            mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.run_task(domain="speed", tags=["race"], input_data={})

    assert result.success is True
    assert result.skill_id == "fast_b"


def test_competitive_mode_a_tiebreaker(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode A 2개 후보: 모두 999999이므로 fitness tiebreaker로 높은 쪽 승리."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_a_skill(
        skills_dir, "a_high", domain="tie", tags=["tie"], fitness_score=0.9,
    )
    _write_mode_a_skill(
        skills_dir, "a_low", domain="tie", tags=["tie"], fitness_score=0.1,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        """Mode A 결과 반환."""
        _ = input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": sid},
            execution_time_ms=100, mode="a",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.run_task(domain="tie", tags=["tie"], input_data={})

    assert result.success is True
    # Mode A 동점 → fitness tiebreaker → a_high 승리
    assert result.skill_id == "a_high"


def test_competitive_mode_b_over_mode_a(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode B + Mode A 혼합: Mode B 빠른 쪽이 Mode A보다 우선한다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "b_fast", domain="mix", tags=["mix"],
        result_value="b_fast", fitness_score=0.1,
    )
    _write_mode_a_skill(
        skills_dir, "a_top", domain="mix", tags=["mix"], fitness_score=0.9,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        """b_fast=40ms(mode b), a_top=100ms(mode a)."""
        _ = input_data
        sid = getattr(skill, "id")
        mode = getattr(skill, "mode")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": sid},
            execution_time_ms=40 if sid == "b_fast" else 100,
            mode=mode,
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.run_task(domain="mix", tags=["mix"], input_data={})

    assert result.success is True
    # Mode B(40ms) < Mode A(999999) → b_fast 승리
    assert result.skill_id == "b_fast"


def test_competitive_single_success(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """여러 후보 중 1개만 성공하면 해당 후보가 승리한다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "winner", domain="single", tags=["single"],
        result_value="win", fitness_score=0.1,
    )
    _write_mode_b_skill(
        skills_dir, "loser", domain="single", tags=["single"],
        result_value="lose", fitness_score=0.9,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        """winner만 성공, loser는 실패."""
        _ = input_data
        sid = getattr(skill, "id")
        if sid == "winner":
            return ExecutionResult(
                skill_id=sid, success=True, output={"result": "win"},
                execution_time_ms=100, mode="b",
            )
        return ExecutionResult(
            skill_id=sid, success=False, error="crash",
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.run_task(
        domain="single", tags=["single"], input_data={}, max_retries=0,
    )

    assert result.success is True
    assert result.skill_id == "winner"


def test_competitive_all_fail_returns_none(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """모든 후보가 실패하면 None이 반환된다 (최종 결과 실패)."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "fail_x", domain="allfail", tags=["allfail"],
        result_value="x", fitness_score=0.5,
    )
    _write_mode_b_skill(
        skills_dir, "fail_y", domain="allfail", tags=["allfail"],
        result_value="y", fitness_score=0.5,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        """전원 실패."""
        _ = input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=False, error="total failure",
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    result = engine.run_task(
        domain="allfail", tags=["allfail"], input_data={}, max_retries=0,
    )

    assert result.success is False


# === Autopsy → 자동 피드백 파이프라인 테스트 ===


def test_auto_feedback_on_failure(schemas_dir: Path, tmp_path: Path) -> None:
    """Mode B 스킬 실패 시 [AUTO] 피드백이 자동 저장된다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir,
        "crash_auto",
        domain="auto_test",
        tags=["auto"],
        should_fail=True,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )

    engine.run_task(
        domain="auto_test",
        tags=["auto"],
        input_data={"x": "test"},
        max_retries=0,
    )

    feedback_list = engine.get_registry().get_feedback("crash_auto")
    assert len(feedback_list) >= 1
    assert feedback_list[0]["comment"].startswith("[AUTO]")
    assert feedback_list[0]["rating"] == 1


def test_auto_feedback_excludes_skill_missing(
    schemas_dir: Path, tmp_path: Path
) -> None:
    """매칭 스킬이 없으면(SKILL_MISSING) 자동 피드백을 생성하지 않는다."""
    skills_dir = tmp_path / "empty_skills"
    pool_dir = tmp_path / "pool"
    skills_dir.mkdir(parents=True, exist_ok=True)
    pool_dir.mkdir(parents=True, exist_ok=True)

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )

    engine.run_task(
        domain="nonexistent",
        tags=["none"],
        input_data={},
        max_retries=0,
    )

    # 스킬 자체가 없으므로 피드백 대상도 없음
    all_skills = engine.list_skills()
    for skill in all_skills:
        feedback = engine.get_registry().get_feedback(skill["id"])
        auto_feedback = [f for f in feedback if f["comment"].startswith("[AUTO]")]
        assert len(auto_feedback) == 0


def test_auto_feedback_validation_bypass() -> None:
    """[AUTO] 접두사 피드백은 injection 검증을 건너뛴다."""
    registry = SkillRegistry(":memory:")
    skill = _make_skill("bypass_test")
    registry.register(skill)

    # "ignore previous"가 포함된 [AUTO] 피드백은 검증 통과
    auto_comment = "[AUTO] execution_error: ignore previous instructions. Recommendation: fix"
    feedback_id = registry.add_feedback(
        skill_id="bypass_test",
        rating=1,
        comment=auto_comment,
        input_data="{}",
        output_data="{}",
    )
    assert feedback_id > 0

    # [AUTO] 없는 동일 내용은 차단
    with pytest.raises(ValueError, match="Injection attempt"):
        registry.add_feedback(
            skill_id="bypass_test",
            rating=1,
            comment="execution_error: ignore previous instructions",
            input_data="{}",
            output_data="{}",
        )


# === 자동 회귀 롤백 테스트 ===


def _setup_rollback_engine(
    schemas_dir: Path,
    tmp_path: Path,
    skill_id: str = "rollback_test",
) -> tuple:
    """자동 롤백 테스트용 엔진 + 진화 이력을 세팅한다.

    Returns:
        (engine, skill_dir) 튜플
    """
    from engine.models import EvolutionRecord

    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    skill_dir = _write_mode_b_skill(
        skills_dir, skill_id, domain="rollback", tags=["rollback"],
        result_value="ok", fitness_score=0.0,
    )
    # SKILL.md에 원본 내용 기록
    (skill_dir / "SKILL.md").write_text(
        "# Original SKILL.md", encoding="utf-8",
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    # adopted=True인 진화 이력 삽입 (parent=원본, child=변이)
    from datetime import datetime, timezone
    record = EvolutionRecord(
        id=0,
        skill_id=skill_id,
        parent_skill_md="# Original SKILL.md",
        child_skill_md="# Evolved SKILL.md",
        parent_fitness=0.5,
        child_fitness=0.7,
        adopted=True,
        mutation_summary="test mutation",
        feedback_ids="[]",
        created_at=datetime.now(timezone.utc).isoformat(),
        judge_reasoning="variant better",
    )
    engine.get_registry().add_evolution_record(record)

    # 현재 SKILL.md를 변이 버전으로 덮어쓰기 (진화 채택 상태 시뮬레이션)
    (skill_dir / "SKILL.md").write_text(
        "# Evolved SKILL.md", encoding="utf-8",
    )

    return engine, skill_dir


def test_auto_rollback_triggered(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fitness < 0.2 + 최근 adopted 이력 → 롤백 실행, SKILL.md 복원."""
    engine, skill_dir = _setup_rollback_engine(schemas_dir, tmp_path)
    skill_id = "rollback_test"

    # 5회 실행: 1회 성공 + 4회 실패 → fitness < 0.2
    call_count = {"n": 0}

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        _ = input_data
        sid = getattr(skill, "id")
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ExecutionResult(
                skill_id=sid, success=True, output={"result": "ok"},
                execution_time_ms=10, mode="b",
            )
        return ExecutionResult(
            skill_id=sid, success=False, error="crash",
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    # 5회 실행 (단일 후보이므로 _run_competitive 경유 안 함 → run_task 직접)
    for _ in range(5):
        engine.run_task(
            domain="rollback", tags=["rollback"], input_data={},
            max_retries=0,
        )

    # rollback 후 fitness는 parent_fitness(0.5)로 리셋되고 quarantine 격리됨
    skill_data = engine.get_registry().get(skill_id)
    assert abs(skill_data["fitness_score"] - 0.5) < 1e-9
    assert skill_data["release_state"] == "quarantined"

    # SKILL.md가 원본으로 복원됨
    restored = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert restored == "# Original SKILL.md"


def test_auto_rollback_not_triggered_high_fitness(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fitness >= 0.2이면 롤백 미실행."""
    engine, skill_dir = _setup_rollback_engine(schemas_dir, tmp_path)

    # 5회 모두 성공 → fitness 높음
    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        _ = input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": "ok"},
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    for _ in range(5):
        engine.run_task(
            domain="rollback", tags=["rollback"], input_data={},
            max_retries=0,
        )

    skill_data = engine.get_registry().get("rollback_test")
    assert skill_data["fitness_score"] >= 0.2

    # SKILL.md 변이 버전 유지 (롤백 안 됨)
    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert content == "# Evolved SKILL.md"


def test_auto_rollback_not_triggered_no_history(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """진화 이력 없으면 롤백 미실행."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    skill_dir = _write_mode_b_skill(
        skills_dir, "no_history", domain="rollback", tags=["rollback"],
        result_value="ok", fitness_score=0.0,
    )
    (skill_dir / "SKILL.md").write_text(
        "# Current SKILL.md", encoding="utf-8",
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    # 5회 전부 실패 → fitness < 0.2이지만 이력 없음
    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        _ = input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=False, error="crash",
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    for _ in range(5):
        engine.run_task(
            domain="rollback", tags=["rollback"], input_data={},
            max_retries=0,
        )

    # 이력 없으므로 SKILL.md 그대로
    content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert content == "# Current SKILL.md"


def test_auto_rollback_marks_record(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """롤백 후 evolution_history의 auto_rolled_back=True로 마킹된다."""
    engine, _ = _setup_rollback_engine(
        schemas_dir, tmp_path, skill_id="mark_test",
    )
    skill_id = "mark_test"

    # 5회: 1회 성공 + 4회 실패
    call_count = {"n": 0}

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        _ = input_data
        sid = getattr(skill, "id")
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ExecutionResult(
                skill_id=sid, success=True, output={"result": "ok"},
                execution_time_ms=10, mode="b",
            )
        return ExecutionResult(
            skill_id=sid, success=False, error="crash",
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    for _ in range(5):
        engine.run_task(
            domain="rollback", tags=["rollback"], input_data={},
            max_retries=0,
        )

    history = engine.get_registry().get_evolution_history(skill_id, limit=1)
    assert len(history) == 1
    assert history[0]["auto_rolled_back"] is True


def test_auto_rollback_uses_registry_api() -> None:
    """C-1: _conn 직접 접근 없이 Registry public method로만 처리되는지 검증."""
    import ast
    import inspect
    from engine.loop import CambrianEngine

    source = inspect.getsource(CambrianEngine)
    tree = ast.parse(source)

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if node.attr == "_conn":
                # _registry._conn 패턴 탐지
                if isinstance(node.value, ast.Attribute) and node.value.attr == "_registry":
                    violations.append(f"line {node.lineno}: _registry._conn 접근")

    assert violations == [], (
        f"loop.py에서 _registry._conn 직접 접근 발견: {violations}"
    )


def test_auto_rollback_restores_parent_state(
    tmp_path: Path, schemas_dir: Path,
) -> None:
    """C-2: auto rollback이 SKILL.md + fitness + flag + quarantine을 모두 복원하는지 검증."""
    # Mode A 스킬 생성 (evolve 대상)
    skill_id = "evolve_target"
    skill_dir = tmp_path / "skills" / skill_id
    skill_dir.mkdir(parents=True)

    import yaml
    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": "Evolve Target",
        "description": "A skill for evolution test",
        "domain": "testing",
        "tags": ["test"],
        "mode": "a",
        "created_at": "2026-04-01",
        "updated_at": "2026-04-01",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 10,
        },
        "lifecycle": {
            "status": "active",
            "fitness_score": 0.0,
            "total_executions": 0,
            "successful_executions": 0,
            "last_used": None,
            "crystallized_at": None,
        },
    }
    with open(skill_dir / "meta.yaml", "w") as f:
        yaml.dump(meta, f)

    interface = {
        "input": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "x"}},
            "required": [],
        },
        "output": {
            "type": "object",
            "properties": {"result": {"type": "string", "description": "r"}},
            "required": ["result"],
        },
    }
    with open(skill_dir / "interface.yaml", "w") as f:
        yaml.dump(interface, f)

    parent_md = "# Parent SKILL.md\nOriginal content."
    (skill_dir / "SKILL.md").write_text(parent_md, encoding="utf-8")

    # 엔진 생성
    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=tmp_path / "skills",
        skill_pool_dir=tmp_path / "pool",
        db_path=":memory:",
    )

    registry = engine.get_registry()

    # fitness를 낮게 설정 + 실행 횟수 >= 5
    for _ in range(6):
        fail_result = ExecutionResult(
            skill_id=skill_id, success=False, error="test fail",
            execution_time_ms=100, mode="a",
        )
        registry.update_after_execution(skill_id, fail_result)

    # evolution_history에 adopted record 삽입
    from engine.models import EvolutionRecord
    child_md = "# Child SKILL.md\nMutated content."
    (skill_dir / "SKILL.md").write_text(child_md, encoding="utf-8")

    parent_fitness = 0.8
    record = EvolutionRecord(
        id=0,
        skill_id=skill_id,
        parent_skill_md=parent_md,
        child_skill_md=child_md,
        parent_fitness=parent_fitness,
        child_fitness=0.1,
        adopted=True,
        mutation_summary="test mutation",
        feedback_ids="[]",
        created_at="2026-04-01T00:00:00",
    )
    record_id = registry.add_evolution_record(record)

    # rollback 트리거: fitness가 rollback threshold 미만이어야 함
    # 기본 rollback_fitness_threshold = 0.2, 현재 fitness는 6회 실패로 0.0
    engine._check_auto_rollback(skill_id)

    # === 검증 ===

    # 1. SKILL.md가 parent 버전으로 복원됨
    restored_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert restored_md == parent_md, "SKILL.md가 parent로 복원되지 않음"

    # 2. evolution_history에 auto_rolled_back=1
    history = registry.get_evolution_history(skill_id, limit=1)
    assert history[0]["auto_rolled_back"] == 1, "auto_rolled_back 플래그 미설정"

    # 3. fitness가 parent_fitness로 리셋됨
    skill_data = registry.get(skill_id)
    assert skill_data["fitness_score"] == parent_fitness, (
        f"fitness 미복원: expected {parent_fitness}, got {skill_data['fitness_score']}"
    )

    # 4. release_state가 quarantined
    assert skill_data["release_state"] == "quarantined", (
        f"quarantine 미전이: {skill_data['release_state']}"
    )

    engine.close()


# === run_traces 경쟁 실행 trace 테스트 ===


def test_competitive_run_saves_trace(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """경쟁 실행 후 run_traces에 competitive_run 행이 저장된다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "trace_a", domain="trace_test", tags=["trace"],
        result_value="a", fitness_score=0.3,
    )
    _write_mode_b_skill(
        skills_dir, "trace_b", domain="trace_test", tags=["trace"],
        result_value="b", fitness_score=0.5,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        _ = input_data
        sid = getattr(skill, "id")
        time_map = {"trace_a": 50, "trace_b": 200}
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": sid},
            execution_time_ms=time_map[sid], mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    engine.run_task(domain="trace_test", tags=["trace"], input_data={"x": "1"})

    traces = engine.get_run_traces(trace_type="competitive_run", limit=1)
    assert len(traces) == 1
    trace = traces[0]
    assert trace["trace_type"] == "competitive_run"
    assert trace["candidate_count"] == 2
    assert trace["success_count"] == 2
    assert trace["winner_id"] == "trace_a"  # 실행시간 50ms < 200ms
    assert "execution_time=" in trace["winner_reason"]
    assert trace["domain"] == "trace_test"
    assert trace["tags"] == ["trace"]


def test_competitive_all_fail_saves_trace(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전부 실패 시에도 trace가 저장된다 (winner_id=None)."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "fail_t1", domain="fail_trace", tags=["fail"],
        result_value="x", fitness_score=0.5,
    )
    _write_mode_b_skill(
        skills_dir, "fail_t2", domain="fail_trace", tags=["fail"],
        result_value="y", fitness_score=0.5,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        _ = input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=False, error="boom",
            execution_time_ms=10, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    engine.run_task(
        domain="fail_trace", tags=["fail"], input_data={}, max_retries=0,
    )

    traces = engine.get_run_traces(trace_type="competitive_run", limit=1)
    assert len(traces) == 1
    assert traces[0]["winner_id"] is None
    assert traces[0]["winner_reason"] == "all_failed"
    assert traces[0]["success_count"] == 0


def test_get_traces_by_skill_id(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skill_id 필터로 해당 스킬이 참여한 trace만 조회한다."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _write_mode_b_skill(
        skills_dir, "filter_a", domain="filter", tags=["filter"],
        result_value="a", fitness_score=0.5,
    )
    _write_mode_b_skill(
        skills_dir, "filter_b", domain="filter", tags=["filter"],
        result_value="b", fitness_score=0.5,
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir, skills_dir=skills_dir,
        skill_pool_dir=pool_dir, db_path=":memory:",
    )

    def fake_execute(skill: object, input_data: dict) -> ExecutionResult:
        _ = input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True, output={"result": sid},
            execution_time_ms=50, mode="b",
        )

    monkeypatch.setattr(engine._executor, "execute", fake_execute)

    engine.run_task(domain="filter", tags=["filter"], input_data={})

    # winner로 필터
    traces = engine.get_run_traces(skill_id="filter_a")
    assert len(traces) >= 1


def test_get_traces_limit(schemas_dir: Path, tmp_path: Path) -> None:
    """limit 파라미터로 반환 개수를 제한한다."""
    registry = SkillRegistry(":memory:")
    for i in range(5):
        registry.add_run_trace(
            trace_type="competitive_run",
            domain="limit_test",
            tags=[],
            input_summary="",
            candidate_count=1,
            success_count=1,
            winner_id=f"skill_{i}",
            winner_reason="test",
            candidates_json="[]",
            total_ms=10,
        )

    assert len(registry.get_run_traces(limit=3)) == 3
    assert len(registry.get_run_traces(limit=10)) == 5

    registry.close()


def test_run_task_does_not_absorb_same_skill_twice(tmp_path, schemas_dir):
    """M-2: 동일 external skill이 같은 task 재시도 중 중복 흡수되지 않는지 검증."""
    import yaml

    # 항상 실패하는 skill을 external에 배치
    ext_dir = tmp_path / "external"
    fail_skill = ext_dir / "fail_skill"
    fail_skill.mkdir(parents=True)
    (fail_skill / "execute").mkdir()

    meta = {
        "id": "fail_skill",
        "version": "1.0.0",
        "name": "Fail",
        "description": "always fails",
        "domain": "testing",
        "tags": ["test"],
        "mode": "b",
        "created_at": "2026-04-01",
        "updated_at": "2026-04-01",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 5,
        },
        "lifecycle": {"status": "active", "fitness_score": 0.0},
    }
    with open(fail_skill / "meta.yaml", "w") as f:
        yaml.dump(meta, f)

    interface = {
        "input": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "x"}},
            "required": [],
        },
        "output": {
            "type": "object",
            "properties": {"r": {"type": "string", "description": "r"}},
            "required": ["r"],
        },
    }
    with open(fail_skill / "interface.yaml", "w") as f:
        yaml.dump(interface, f)

    (fail_skill / "SKILL.md").write_text("# Fail\nAlways fails.")
    (fail_skill / "execute" / "main.py").write_text(
        'import sys; sys.exit(1)\n'
    )

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=tmp_path / "empty_skills",
        skill_pool_dir=tmp_path / "pool",
        db_path=":memory:",
        external_skill_dirs=[str(ext_dir)],
    )

    # empty_skills 디렉토리 생성
    (tmp_path / "empty_skills").mkdir(exist_ok=True)

    # 흡수 호출 횟수 추적
    original_absorb = engine._absorber.absorb
    absorb_count = [0]

    def counting_absorb(path):
        absorb_count[0] += 1
        return original_absorb(path)

    engine._absorber.absorb = counting_absorb

    result = engine.run_task("testing", ["test"], {"x": "hello"}, max_retries=3)

    # 최대 1번만 흡수되어야 함
    assert absorb_count[0] <= 1, (
        f"동일 skill이 {absorb_count[0]}번 흡수됨 (기대: ≤1)"
    )

    engine.close()


def test_auto_rollback_db_failure_is_observable(tmp_path, schemas_dir):
    """DB update 실패 시 result에 db_applied=False와 에러 메시지가 기록된다."""
    from unittest.mock import patch
    import yaml

    # Mode A 스킬 생성
    skill_id = "rollback_db_fail"
    skill_dir = tmp_path / "skills" / skill_id
    skill_dir.mkdir(parents=True)

    meta = {
        "id": skill_id, "version": "1.0.0", "name": "Test",
        "description": "test", "domain": "testing", "tags": ["test"],
        "mode": "a", "created_at": "2026-04-01", "updated_at": "2026-04-01",
        "runtime": {"language": "python", "needs_network": False,
                     "needs_filesystem": False, "timeout_seconds": 10},
        "lifecycle": {"status": "active", "fitness_score": 0.0,
                       "total_executions": 0, "successful_executions": 0,
                       "last_used": None, "crystallized_at": None},
    }
    interface = {
        "input": {"type": "object", "properties": {"x": {"type": "string", "description": "x"}}, "required": []},
        "output": {"type": "object", "properties": {"r": {"type": "string", "description": "r"}}, "required": ["r"]},
    }
    with open(skill_dir / "meta.yaml", "w") as f:
        yaml.dump(meta, f)
    with open(skill_dir / "interface.yaml", "w") as f:
        yaml.dump(interface, f)
    (skill_dir / "SKILL.md").write_text("# Child\nMutated.", encoding="utf-8")

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=tmp_path / "skills",
        skill_pool_dir=tmp_path / "pool",
        db_path=":memory:",
    )
    registry = engine.get_registry()

    # evolution record 삽입
    from engine.models import EvolutionRecord
    record = EvolutionRecord(
        id=0, skill_id=skill_id,
        parent_skill_md="# Parent\nOriginal.",
        child_skill_md="# Child\nMutated.",
        parent_fitness=0.8, child_fitness=0.1,
        adopted=True, mutation_summary="test",
        feedback_ids="[]", created_at="2026-04-01T00:00:00",
    )
    record_id = registry.add_evolution_record(record)

    skill_data = registry.get(skill_id)
    record_data = registry.get_evolution_history(skill_id, limit=1)[0]

    # DB apply_auto_rollback를 강제 실패시킴
    with patch.object(
        registry, "apply_auto_rollback",
        side_effect=RuntimeError("DB write failed"),
    ):
        result = engine._execute_auto_rollback(
            skill_id, skill_data, record_data,
        )

    # 파일은 복원됨
    assert result["file_restored"] is True
    # DB는 실패
    assert result["db_applied"] is False
    # 에러 메시지에 실패 내용 포함
    assert any("db_update_failed" in e for e in result["errors"])

    engine.close()


def test_auto_rollback_file_failure_is_observable(tmp_path, schemas_dir):
    """파일 복원 실패 시 result에 file_restored=False가 기록되고,
    DB quarantine은 여전히 시도된다."""
    import yaml

    skill_id = "rollback_file_fail"
    skill_dir = tmp_path / "skills" / skill_id
    skill_dir.mkdir(parents=True)

    meta = {
        "id": skill_id, "version": "1.0.0", "name": "Test",
        "description": "test", "domain": "testing", "tags": ["test"],
        "mode": "a", "created_at": "2026-04-01", "updated_at": "2026-04-01",
        "runtime": {"language": "python", "needs_network": False,
                     "needs_filesystem": False, "timeout_seconds": 10},
        "lifecycle": {"status": "active", "fitness_score": 0.0,
                       "total_executions": 0, "successful_executions": 0,
                       "last_used": None, "crystallized_at": None},
    }
    interface = {
        "input": {"type": "object", "properties": {"x": {"type": "string", "description": "x"}}, "required": []},
        "output": {"type": "object", "properties": {"r": {"type": "string", "description": "r"}}, "required": ["r"]},
    }
    with open(skill_dir / "meta.yaml", "w") as f:
        yaml.dump(meta, f)
    with open(skill_dir / "interface.yaml", "w") as f:
        yaml.dump(interface, f)
    (skill_dir / "SKILL.md").write_text("# Child\nMutated.", encoding="utf-8")

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=tmp_path / "skills",
        skill_pool_dir=tmp_path / "pool",
        db_path=":memory:",
    )
    registry = engine.get_registry()

    from engine.models import EvolutionRecord
    record = EvolutionRecord(
        id=0, skill_id=skill_id,
        parent_skill_md="# Parent\nOriginal.",
        child_skill_md="# Child\nMutated.",
        parent_fitness=0.8, child_fitness=0.1,
        adopted=True, mutation_summary="test",
        feedback_ids="[]", created_at="2026-04-01T00:00:00",
    )
    registry.add_evolution_record(record)

    skill_data = registry.get(skill_id)
    record_data = registry.get_evolution_history(skill_id, limit=1)[0]

    # skill_path를 존재하지 않는 경로로 변조 → 파일 쓰기 실패
    bad_skill_data = dict(skill_data)
    bad_skill_data["skill_path"] = "/nonexistent/path/that/does/not/exist"

    result = engine._execute_auto_rollback(
        skill_id, bad_skill_data, record_data,
    )

    # 파일 복원 실패
    assert result["file_restored"] is False
    assert any("file_restore_failed" in e for e in result["errors"])

    # DB quarantine은 성공 (파일 실패와 무관하게 시도)
    assert result["db_applied"] is True

    # DB 상태 확인: quarantined
    refreshed = registry.get(skill_id)
    assert refreshed["release_state"] == "quarantined"

    engine.close()


def test_auto_rollback_db_updates_are_transactional(tmp_path, schemas_dir):
    """DB 트랜잭션 중 일부 실패 시 전체가 롤백되어 부분 적용이 없다."""
    from unittest.mock import patch, MagicMock
    import yaml
    import sqlite3

    skill_id = "rollback_txn_test"
    skill_dir = tmp_path / "skills" / skill_id
    skill_dir.mkdir(parents=True)

    meta = {
        "id": skill_id, "version": "1.0.0", "name": "Test",
        "description": "test", "domain": "testing", "tags": ["test"],
        "mode": "a", "created_at": "2026-04-01", "updated_at": "2026-04-01",
        "runtime": {"language": "python", "needs_network": False,
                     "needs_filesystem": False, "timeout_seconds": 10},
        "lifecycle": {"status": "active", "fitness_score": 0.0,
                       "total_executions": 0, "successful_executions": 0,
                       "last_used": None, "crystallized_at": None},
    }
    interface = {
        "input": {"type": "object", "properties": {"x": {"type": "string", "description": "x"}}, "required": []},
        "output": {"type": "object", "properties": {"r": {"type": "string", "description": "r"}}, "required": ["r"]},
    }
    with open(skill_dir / "meta.yaml", "w") as f:
        yaml.dump(meta, f)
    with open(skill_dir / "interface.yaml", "w") as f:
        yaml.dump(interface, f)
    (skill_dir / "SKILL.md").write_text("# Child", encoding="utf-8")

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=tmp_path / "skills",
        skill_pool_dir=tmp_path / "pool",
        db_path=":memory:",
    )
    registry = engine.get_registry()

    from engine.models import EvolutionRecord
    record = EvolutionRecord(
        id=0, skill_id=skill_id,
        parent_skill_md="# Parent",
        child_skill_md="# Child",
        parent_fitness=0.8, child_fitness=0.1,
        adopted=True, mutation_summary="test",
        feedback_ids="[]", created_at="2026-04-01T00:00:00",
    )
    registry.add_evolution_record(record)

    # 원본 상태 스냅샷
    original_state = registry.get(skill_id)
    original_fitness = original_state["fitness_score"]
    original_release = original_state["release_state"]

    record_data = registry.get_evolution_history(skill_id, limit=1)[0]

    # apply_auto_rollback 내부에서 3번째 SQL(release_state UPDATE) 시점에 실패 주입.
    # sqlite3.Connection.execute는 read-only attribute이므로 patch.object로 교체
    # 할 수 없음 → _conn 자체를 wrapper로 일시 교체하는 방식으로 주입.
    real_conn = registry._conn

    class _FailingConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, params=()):
            if "release_state" in str(sql) and "quarantined" in str(params):
                raise sqlite3.OperationalError("injected failure")
            return self._inner.execute(sql, params)

        def commit(self):
            return self._inner.commit()

        def rollback(self):
            return self._inner.rollback()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    registry._conn = _FailingConn(real_conn)
    try:
        try:
            registry.apply_auto_rollback(
                skill_id=skill_id,
                record_id=record_data["id"],
                parent_fitness=0.8,
                reason="test",
            )
        except sqlite3.OperationalError:
            pass  # 예상된 실패
    finally:
        registry._conn = real_conn

    # 트랜잭션 롤백 확인: 모든 DB 상태가 원본 그대로
    after_state = registry.get(skill_id)
    assert after_state["fitness_score"] == original_fitness, (
        f"fitness 부분 적용됨: {original_fitness} → {after_state['fitness_score']}"
    )
    assert after_state["release_state"] == original_release, (
        f"release_state 부분 적용됨: {original_release} → {after_state['release_state']}"
    )

    # auto_rolled_back도 미적용
    history = registry.get_evolution_history(skill_id, limit=1)
    assert history[0]["auto_rolled_back"] == 0, "auto_rolled_back 부분 적용됨"

    engine.close()
