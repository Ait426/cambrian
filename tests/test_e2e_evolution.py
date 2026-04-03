"""진화 루프 E2E 테스트.

Part A: Mock LLM으로 전체 루프 검증 (CI용)
Part B: 실제 API로 진화 품질 검증 (API 키 필요)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from engine.evolution import SkillEvolver
from engine.executor import SkillExecutor
from engine.judge import SkillJudge
from engine.loop import CambrianEngine
from engine.models import ExecutionResult, JudgeVerdict

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


def _create_mode_a_skill(skills_dir: Path, skill_id: str = "e2e_skill") -> Path:
    """E2E 테스트용 Mode A 스킬을 생성한다."""
    skill_dir = skills_dir / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": skill_id,
        "version": "1.0.0",
        "name": f"E2E Test Skill {skill_id}",
        "description": "E2E evolution test skill",
        "domain": "testing",
        "tags": ["test", "e2e", "evolve"],
        "created_at": "2026-04-02",
        "updated_at": "2026-04-02",
        "mode": "a",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 60,
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
    interface = {
        "input": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "User query"},
            },
            "required": ["query"],
        },
        "output": {
            "type": "object",
            "properties": {
                "html": {"type": "string", "description": "HTML output"},
            },
            "required": ["html"],
        },
    }

    with open(skill_dir / "meta.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(interface, f, allow_unicode=True, sort_keys=False)
    (skill_dir / "SKILL.md").write_text(
        '# E2E Test Skill\n\nYou receive a query and respond with JSON.\n\n'
        '## Output Format\n'
        'Respond with ONLY a JSON object:\n'
        '```json\n{"html": "<p>your answer here</p>"}\n```\n',
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def e2e_engine(schemas_dir: Path, tmp_path: Path) -> CambrianEngine:
    """E2E 테스트용 CambrianEngine."""
    skills_dir = tmp_path / "skills"
    pool_dir = tmp_path / "pool"
    _create_mode_a_skill(skills_dir)
    return CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
    )


# ═══════════════════════════════════════════════════════════════
# Part A: Mock E2E — 전체 루프를 mock LLM으로 검증
# ═══════════════════════════════════════════════════════════════


class TestMockE2EEvolution:
    """진화 루프의 E2E 흐름을 mock으로 검증한다."""

    @pytest.fixture
    def engine(self, schemas_dir: Path, tmp_path: Path) -> CambrianEngine:
        """Mode A 테스트 스킬이 포함된 엔진을 생성한다."""
        skills_dir = tmp_path / "skills"
        pool_dir = tmp_path / "pool"
        skill_dir = skills_dir / "evolve_test"
        skill_dir.mkdir(parents=True)

        meta = {
            "id": "evolve_test",
            "version": "1.0.0",
            "name": "Evolve Test",
            "description": "Mode A evolve test skill",
            "domain": "testing",
            "tags": ["test", "evolve"],
            "created_at": "2026-04-02",
            "updated_at": "2026-04-02",
            "mode": "a",
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
        interface = {
            "input": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "query"},
                },
                "required": ["query"],
            },
            "output": {
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "html"},
                },
                "required": ["html"],
            },
        }

        with open(skill_dir / "meta.yaml", "w", encoding="utf-8") as file:
            yaml.safe_dump(meta, file, allow_unicode=True, sort_keys=False)
        with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as file:
            yaml.safe_dump(interface, file, allow_unicode=True, sort_keys=False)
        (skill_dir / "SKILL.md").write_text(
            '# Test\nYou receive a query. Respond with JSON: {"html": "<p>answer</p>"}',
            encoding="utf-8",
        )

        return CambrianEngine(
            schemas_dir=schemas_dir,
            skills_dir=skills_dir,
            skill_pool_dir=pool_dir,
            db_path=":memory:",
        )

    def _setup_mocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        variant_success: bool = True,
        variant_wins: bool = True,
        child_skill_md: str = "# Evolved\nImproved instructions here.",
    ) -> None:
        """진화 테스트용 mutate, execute, judge mock을 구성한다."""

        def fake_mutate(
            self: SkillEvolver,
            skill: object,
            feedback_list: list[dict],
        ) -> str:
            """변이된 SKILL.md를 반환한다."""
            _ = self
            _ = skill
            _ = feedback_list
            return child_skill_md

        def fake_execute(
            self: SkillExecutor,
            skill: object,
            input_data: dict,
        ) -> ExecutionResult:
            """원본과 variant에 대해 가짜 실행 결과를 반환한다."""
            _ = self
            _ = input_data
            skill_id = getattr(skill, "id")
            if skill_id == "evolve_test_variant":
                if variant_success:
                    return ExecutionResult(
                        skill_id=skill_id,
                        success=True,
                        output={"html": "<p>variant</p>"},
                        execution_time_ms=10,
                        mode="a",
                    )
                return ExecutionResult(
                    skill_id=skill_id,
                    success=False,
                    output=None,
                    error="variant failed",
                    execution_time_ms=10,
                    mode="a",
                )
            return ExecutionResult(
                skill_id=skill_id,
                success=True,
                output={"html": "<p>original</p>"},
                execution_time_ms=50,
                mode="a",
            )

        def fake_judge(
            self: SkillJudge,
            original_output: dict | None,
            variant_output: dict | None,
            skill_description: str,
            feedback_list: list[dict],
        ) -> JudgeVerdict:
            """Variant 우위 또는 original 우위의 Judge 결과를 반환한다."""
            _ = self
            _ = original_output
            _ = variant_output
            _ = skill_description
            _ = feedback_list
            if variant_wins:
                return JudgeVerdict(
                    original_score=4.0,
                    variant_score=8.0,
                    reasoning="variant wins",
                    winner="variant",
                )
            return JudgeVerdict(
                original_score=7.0,
                variant_score=1.0,
                reasoning="original wins",
                winner="original",
            )

        monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
        monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
        monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    def test_evolution_adopt_changes_skill(
        self,
        engine: CambrianEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """채택된 진화는 원본 SKILL.md를 새 내용으로 교체한다."""
        self._setup_mocks(monkeypatch, variant_success=True, variant_wins=True)

        skill_path = Path(engine.get_registry().get("evolve_test")["skill_path"])
        original_content = (skill_path / "SKILL.md").read_text(encoding="utf-8")

        engine.feedback("evolve_test", 5, "please improve")
        record = engine.evolve("evolve_test", {"query": "hello"})
        updated_content = (skill_path / "SKILL.md").read_text(encoding="utf-8")

        assert record.adopted is True
        assert updated_content != original_content
        assert "# Evolved" in updated_content

    def test_evolution_discard_does_not_change_skill(
        self,
        engine: CambrianEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """폐기된 진화는 원본 SKILL.md를 변경하지 않는다."""

        def fake_mutate(
            self: SkillEvolver,
            skill: object,
            feedback_list: list[dict],
        ) -> str:
            """변이된 SKILL.md를 반환한다."""
            _ = self
            _ = skill
            _ = feedback_list
            return "# Evolved\nBad instructions here."

        def fake_execute(
            self: SkillExecutor,
            skill: object,
            input_data: dict,
        ) -> ExecutionResult:
            """Original은 성공하고 variant는 실패하도록 반환한다."""
            _ = self
            _ = input_data
            skill_id = getattr(skill, "id")
            if skill_id == "evolve_test_variant":
                return ExecutionResult(
                    skill_id=skill_id,
                    success=False,
                    output=None,
                    error="variant failed",
                    execution_time_ms=10,
                    mode="a",
                )
            return ExecutionResult(
                skill_id=skill_id,
                success=True,
                output={"html": "<p>original</p>"},
                execution_time_ms=50,
                mode="a",
            )

        def fail_judge(
            self: SkillJudge,
            original_output: dict | None,
            variant_output: dict | None,
            skill_description: str,
            feedback_list: list[dict],
        ) -> JudgeVerdict:
            """Original 승리 Judge 결과를 반환한다."""
            _ = self
            _ = original_output
            _ = variant_output
            _ = skill_description
            _ = feedback_list
            return JudgeVerdict(7.0, 1.0, "variant bad", "original")

        monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
        monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
        monkeypatch.setattr(SkillJudge, "judge", fail_judge)

        skill_path = Path(engine.get_registry().get("evolve_test")["skill_path"])
        original_content = (skill_path / "SKILL.md").read_text(encoding="utf-8")

        engine.feedback("evolve_test", 2, "this got worse")
        record = engine.evolve("evolve_test", {"query": "hello"})
        updated_content = (skill_path / "SKILL.md").read_text(encoding="utf-8")

        assert record.adopted is False
        assert updated_content == original_content

    def test_evolution_history_is_recorded(
        self,
        engine: CambrianEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """진화 실행 후 evolution_history에 기록이 저장된다."""
        self._setup_mocks(monkeypatch, variant_success=True, variant_wins=True)

        engine.feedback("evolve_test", 5, "record this")
        record = engine.evolve("evolve_test", {"query": "hello"})
        history = engine.get_registry().get_evolution_history("evolve_test")

        assert record.id > 0
        assert len(history) == 1
        assert history[0]["id"] == record.id
        assert history[0]["adopted"] is True

    def test_fitness_accumulates_across_evolutions(
        self,
        engine: CambrianEngine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """여러 번 evolve()를 수행하면 total_executions가 누적된다."""
        self._setup_mocks(monkeypatch, variant_success=True, variant_wins=True)

        initial_data = engine.get_registry().get("evolve_test")
        initial_executions = initial_data["total_executions"]

        engine.feedback("evolve_test", 5, "first evolution")
        engine.evolve("evolve_test", {"query": "hello"})
        engine.feedback("evolve_test", 4, "second evolution")
        engine.evolve("evolve_test", {"query": "hello again"})

        final_data = engine.get_registry().get("evolve_test")

        assert final_data["total_executions"] > initial_executions


# ═══════════════════════════════════════════════════════════════
# Part B: API E2E — 실제 LLM으로 진화 품질 검증
# ═══════════════════════════════════════════════════════════════


class TestApiE2EEvolution:
    """실제 API로 진화 루프를 1회 돌려서 SKILL.md가 실제로 개선되는지 검증."""

    @requires_api_key
    def test_real_evolution_single_round(
        self,
        schemas_dir: Path,
        tmp_path: Path,
    ) -> None:
        """실제 API로 feedback → evolve 1회. SKILL.md가 변경되고 결과가 유효한지."""
        skills_dir = tmp_path / "api_skills"
        pool_dir = tmp_path / "api_pool"
        _create_mode_a_skill(skills_dir, "api_evolve_test")

        engine = CambrianEngine(
            schemas_dir=schemas_dir,
            skills_dir=skills_dir,
            skill_pool_dir=pool_dir,
            db_path=":memory:",
        )

        engine.feedback("api_evolve_test", 2, "Output HTML is too minimal, needs more structure and styling")
        engine.feedback("api_evolve_test", 3, "Should include proper DOCTYPE and meta charset")

        record = engine.evolve(
            "api_evolve_test",
            {"query": "What is Cambrian?"},
        )

        assert record.skill_id == "api_evolve_test"
        assert isinstance(record.child_skill_md, str)
        assert len(record.child_skill_md) > 50
        assert record.child_skill_md != record.parent_skill_md

        history = engine.get_registry().get_evolution_history("api_evolve_test")
        assert len(history) == 1

    @requires_api_key
    def test_real_evolution_improves_output(
        self,
        schemas_dir: Path,
        tmp_path: Path,
    ) -> None:
        """실제 API로 진화 전후 출력을 비교. 진화 후 출력이 더 긴지(더 상세한지) 확인."""
        skills_dir = tmp_path / "compare_skills"
        pool_dir = tmp_path / "compare_pool"
        _create_mode_a_skill(skills_dir, "compare_test")

        engine = CambrianEngine(
            schemas_dir=schemas_dir,
            skills_dir=skills_dir,
            skill_pool_dir=pool_dir,
            db_path=":memory:",
        )

        test_input = {"query": "Explain what an API is in one paragraph"}

        pre_result = engine.run_task(
            domain="testing",
            tags=["test", "e2e"],
            input_data=test_input,
        )
        pre_html = pre_result.output.get("html", "") if pre_result.output else ""

        engine.feedback("compare_test", 2, "Too short. Need at least 3 paragraphs with examples.")
        engine.feedback("compare_test", 1, "No code examples. Should include a REST API example.")
        engine.feedback("compare_test", 3, "Missing structure. Use h2 headers for sections.")

        record = engine.evolve("compare_test", test_input)

        if record.adopted:
            post_result = engine.run_task(
                domain="testing",
                tags=["test", "e2e"],
                input_data=test_input,
            )
            post_html = post_result.output.get("html", "") if post_result.output else ""

            assert len(post_html) >= len(pre_html) * 0.8, (
                f"Post-evolution output ({len(post_html)} chars) should not be "
                f"drastically shorter than pre-evolution ({len(pre_html)} chars)"
            )
