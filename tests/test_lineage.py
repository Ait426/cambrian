"""Adoption Lineage / History / Audit 테스트 (Task 21).

adoption_lineage 테이블의 ancestors/descendants/history 조회,
CLI lineage/audit 출력을 검증한다.
"""

import json
from pathlib import Path

import pytest

from engine.registry import SkillRegistry


def _make_registry() -> SkillRegistry:
    """인메모리 레지스트리."""
    return SkillRegistry(":memory:")


def _insert_lineage(
    registry: SkillRegistry,
    child_skill: str,
    child_run: str,
    parent_skill: str | None = None,
    parent_run: str | None = None,
    scenario: str | None = None,
    policy: str | None = None,
) -> int:
    """lineage 레코드를 삽입한다."""
    return registry.add_lineage(
        child_skill_name=child_skill,
        child_run_id=child_run,
        parent_skill_name=parent_skill,
        parent_run_id=parent_run,
        scenario_id=scenario,
        policy_hash=policy,
    )


# === Ancestors 테스트 ===

class TestGetAncestors:
    """get_ancestors() 테스트."""

    def test_no_parent_returns_self(self) -> None:
        """부모 없는 최초 채택 → 자기 자신 1건."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001")
        result = reg.get_ancestors("summarize", "run-001")
        assert len(result) == 1
        assert result[0]["skill_name"] == "summarize"
        assert result[0]["parent_skill_name"] is None
        reg.close()

    def test_two_generation_chain(self) -> None:
        """2세대 체인 → 2건 반환."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001")
        _insert_lineage(reg, "summarize", "run-002", "summarize", "run-001")
        result = reg.get_ancestors("summarize", "run-002")
        assert len(result) == 2
        assert result[0]["run_id"] == "run-002"
        assert result[1]["run_id"] == "run-001"
        reg.close()

    def test_three_generation_chain(self) -> None:
        """3세대 체인."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001")
        _insert_lineage(reg, "summarize", "run-002", "summarize", "run-001")
        _insert_lineage(reg, "summarize", "run-003", "summarize", "run-002")
        result = reg.get_ancestors("summarize", "run-003")
        assert len(result) == 3
        reg.close()

    def test_unknown_run_id_returns_empty(self) -> None:
        """없는 run_id → 빈 리스트."""
        reg = _make_registry()
        result = reg.get_ancestors("summarize", "nonexistent")
        assert result == []
        reg.close()


# === Descendants 테스트 ===

class TestGetDescendants:
    """get_descendants() 테스트."""

    def test_leaf_node_returns_empty(self) -> None:
        """자손 없는 말단 → 빈 리스트."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001")
        result = reg.get_descendants("run-001")
        assert result == []
        reg.close()

    def test_one_child(self) -> None:
        """자식 1개."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001")
        _insert_lineage(reg, "summarize", "run-002", "summarize", "run-001")
        result = reg.get_descendants("run-001")
        assert len(result) == 1
        assert result[0]["run_id"] == "run-002"
        reg.close()

    def test_nested_tree(self) -> None:
        """중첩 트리: 자식 → 손자."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001")
        _insert_lineage(reg, "summarize", "run-002", "summarize", "run-001")
        _insert_lineage(reg, "summarize", "run-003", "summarize", "run-002")
        result = reg.get_descendants("run-001")
        assert len(result) == 1
        assert len(result[0]["children"]) == 1
        assert result[0]["children"][0]["run_id"] == "run-003"
        reg.close()

    def test_max_depth_limit(self) -> None:
        """max_depth=1이면 손자를 조회하지 않는다."""
        reg = _make_registry()
        _insert_lineage(reg, "s", "r1")
        _insert_lineage(reg, "s", "r2", "s", "r1")
        _insert_lineage(reg, "s", "r3", "s", "r2")
        result = reg.get_descendants("r1", max_depth=1)
        assert len(result) == 1
        assert result[0]["children"] == []
        reg.close()


# === Adoption History 테스트 ===

class TestGetAdoptionHistory:
    """get_adoption_history() 테스트."""

    def test_empty_returns_empty(self) -> None:
        """레코드 없음 → 빈 리스트."""
        reg = _make_registry()
        assert reg.get_adoption_history() == []
        reg.close()

    def test_filter_by_skill(self) -> None:
        """스킬 이름으로 필터링."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001", scenario="s1")
        _insert_lineage(reg, "translate", "run-002", scenario="s1")
        result = reg.get_adoption_history(skill_name="summarize")
        assert len(result) == 1
        assert result[0]["child_skill_name"] == "summarize"
        reg.close()

    def test_filter_by_scenario(self) -> None:
        """시나리오 ID로 필터링."""
        reg = _make_registry()
        _insert_lineage(reg, "summarize", "run-001", scenario="scen-A")
        _insert_lineage(reg, "summarize", "run-002", scenario="scen-B")
        result = reg.get_adoption_history(scenario_id="scen-A")
        assert len(result) == 1
        reg.close()

    def test_filter_by_since(self) -> None:
        """since 필터로 오래된 레코드 제외."""
        reg = _make_registry()
        # 수동 날짜 INSERT
        reg._conn.execute(
            """
            INSERT INTO adoption_lineage
                (child_skill_name, child_run_id, adopted_at)
            VALUES (?, ?, ?)
            """,
            ("summarize", "run-001", "2025-01-01T00:00:00"),
        )
        reg._conn.execute(
            """
            INSERT INTO adoption_lineage
                (child_skill_name, child_run_id, adopted_at)
            VALUES (?, ?, ?)
            """,
            ("summarize", "run-002", "2026-01-01T00:00:00"),
        )
        reg._conn.commit()

        result = reg.get_adoption_history(since="2025-06-01")
        assert len(result) == 1
        assert result[0]["child_run_id"] == "run-002"
        reg.close()

    def test_limit(self) -> None:
        """limit 파라미터 동작."""
        reg = _make_registry()
        for i in range(10):
            _insert_lineage(reg, "summarize", f"run-{i:03d}")
        result = reg.get_adoption_history(limit=3)
        assert len(result) == 3
        reg.close()

    def test_returns_desc_order(self) -> None:
        """최신순 반환."""
        reg = _make_registry()
        reg._conn.execute(
            """
            INSERT INTO adoption_lineage
                (child_skill_name, child_run_id, adopted_at)
            VALUES (?, ?, ?)
            """,
            ("summarize", "run-001", "2025-01-01T00:00:00"),
        )
        reg._conn.execute(
            """
            INSERT INTO adoption_lineage
                (child_skill_name, child_run_id, adopted_at)
            VALUES (?, ?, ?)
            """,
            ("summarize", "run-002", "2026-01-01T00:00:00"),
        )
        reg._conn.commit()

        result = reg.get_adoption_history()
        assert result[0]["child_run_id"] == "run-002"
        reg.close()


# === CLI 출력 테스트 ===

def test_lineage_cli_no_records(capsys: pytest.CaptureFixture[str]) -> None:
    """채택 기록 없을 때 안내 메시지."""
    from engine.loop import CambrianEngine
    engine = CambrianEngine(
        schemas_dir="schemas", skills_dir="skills",
        skill_pool_dir="skill_pool", db_path=":memory:",
    )
    registry = engine.get_registry()

    history = registry.get_adoption_history(skill_name="nonexistent")
    assert history == []
    engine.close()


def test_audit_empty_records() -> None:
    """채택 기록 없을 때 빈 리스트."""
    reg = _make_registry()
    result = reg.get_adoption_history(skill_name="nonexistent")
    assert result == []
    reg.close()


def test_add_lineage_returns_id() -> None:
    """add_lineage가 생성된 ID를 반환한다."""
    reg = _make_registry()
    lid = _insert_lineage(reg, "test_skill", "run-abc")
    assert lid > 0
    reg.close()


def test_lineage_with_scenario_and_policy() -> None:
    """scenario_id와 policy_hash가 올바르게 저장된다."""
    reg = _make_registry()
    _insert_lineage(
        reg, "skill_a", "run-001",
        scenario="hotel_test", policy="sha256:abc",
    )
    history = reg.get_adoption_history(scenario_id="hotel_test")
    assert len(history) == 1
    assert history[0]["policy_hash"] == "sha256:abc"
    reg.close()
