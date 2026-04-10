"""Cambrian 진화 코어 테스트."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from engine.evolution import SkillEvolver
from engine.executor import SkillExecutor
from engine.judge import SkillJudge
from engine.loop import CambrianEngine
from engine.models import EvolutionRecord, ExecutionResult, JudgeVerdict


@pytest.fixture
def engine(schemas_dir: Path, tmp_path: Path) -> CambrianEngine:
    """Mode A 테스트 스킬이 포함된 CambrianEngine을 생성한다."""
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


def test_add_feedback(engine: CambrianEngine) -> None:
    """feedback()가 생성된 피드백 ID를 반환한다."""
    feedback_id = engine.feedback("evolve_test", 3, "decent")

    assert isinstance(feedback_id, int)
    assert feedback_id > 0


@pytest.mark.parametrize("rating", [0, 6])
def test_add_feedback_invalid_rating(
    engine: CambrianEngine,
    rating: int,
) -> None:
    """유효하지 않은 rating은 ValueError를 발생시킨다."""
    with pytest.raises(ValueError):
        engine.feedback("evolve_test", rating, "bad")


def test_get_feedback(engine: CambrianEngine) -> None:
    """최근 피드백 목록을 최신순으로 반환한다."""
    id1 = engine.feedback("evolve_test", 3, "first")
    id2 = engine.feedback("evolve_test", 4, "second")
    id3 = engine.feedback("evolve_test", 5, "third")

    feedback_list = engine.get_registry().get_feedback("evolve_test")

    assert len(feedback_list) == 3
    assert [item["id"] for item in feedback_list] == [id3, id2, id1]


def test_evolution_record_stored(engine: CambrianEngine) -> None:
    """진화 기록을 저장하면 이력에서 조회할 수 있다."""
    record = EvolutionRecord(
        id=0,
        skill_id="evolve_test",
        parent_skill_md="# Old",
        child_skill_md="# New",
        parent_fitness=0.1,
        child_fitness=0.2,
        adopted=True,
        mutation_summary="summary",
        feedback_ids="[1, 2]",
        created_at=datetime.now().astimezone().isoformat(),
    )

    record_id = engine.get_registry().add_evolution_record(record)
    history = engine.get_registry().get_evolution_history("evolve_test")

    assert record_id > 0
    assert len(history) == 1
    assert history[0]["id"] == record_id
    assert history[0]["adopted"] is True


def test_mutate_returns_string(
    engine: CambrianEngine,
) -> None:
    """mutate()는 mock LLM 응답 문자열을 반환한다."""
    from engine.llm import LLMProvider

    class _MockProvider(LLMProvider):
        def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
            return "# Improved SKILL.md\nBetter instructions."
        def provider_name(self) -> str:
            return "mock"

    evolver = SkillEvolver(
        engine._loader, engine._executor, engine.get_registry(),
        provider=_MockProvider(),
    )
    skill = engine._loader.load(engine.get_registry().get("evolve_test")["skill_path"])
    result = evolver.mutate(skill, [{"id": 1, "rating": 3, "comment": "decent"}])

    assert isinstance(result, str)
    assert len(result) > 0


def test_mutate_prompt_contains_feedback(
    engine: CambrianEngine,
) -> None:
    """mutate() 프롬프트에 포맷된 피드백이 포함된다."""
    from engine.llm import LLMProvider

    captured: dict[str, str] = {}

    class _CapturingProvider(LLMProvider):
        def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
            captured["system"] = system
            captured["user"] = user
            return "# Improved"
        def provider_name(self) -> str:
            return "mock"

    evolver = SkillEvolver(
        engine._loader, engine._executor, engine.get_registry(),
        provider=_CapturingProvider(),
    )
    skill = engine._loader.load(engine.get_registry().get("evolve_test")["skill_path"])
    evolver.mutate(skill, [{"id": 1, "rating": 3, "comment": "decent"}])

    assert "Rating: 3/5" in captured["user"]


def test_evolve_mode_b_rejected(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode B 스킬은 진화 대상에서 거부된다."""
    _ = monkeypatch
    skills_root = Path(engine.get_registry().get("evolve_test")["skill_path"]).parent
    mode_b_dir = skills_root / "mode_b_test"
    mode_b_dir.mkdir(parents=True)

    meta = {
        "id": "mode_b_test",
        "version": "1.0.0",
        "name": "Mode B Test",
        "description": "Mode B evolve rejection",
        "domain": "testing",
        "tags": ["test", "evolve"],
        "created_at": "2026-04-02",
        "updated_at": "2026-04-02",
        "mode": "b",
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
            "properties": {"query": {"type": "string", "description": "query"}},
            "required": ["query"],
        },
        "output": {
            "type": "object",
            "properties": {"html": {"type": "string", "description": "html"}},
            "required": ["html"],
        },
    }
    with open(mode_b_dir / "meta.yaml", "w", encoding="utf-8") as file:
        yaml.safe_dump(meta, file, allow_unicode=True, sort_keys=False)
    with open(mode_b_dir / "interface.yaml", "w", encoding="utf-8") as file:
        yaml.safe_dump(interface, file, allow_unicode=True, sort_keys=False)
    (mode_b_dir / "SKILL.md").write_text("# Mode B", encoding="utf-8")
    execute_dir = mode_b_dir / "execute"
    execute_dir.mkdir()
    (execute_dir / "main.py").write_text(
        'import json\nimport sys\n\n'
        'def run(input_data: dict) -> dict:\n    return {"html": "<p>ok</p>"}\n\n'
        'if __name__ == "__main__":\n    print(json.dumps(run({})))\n',
        encoding="utf-8",
    )

    skill = engine._loader.load(mode_b_dir)
    engine.get_registry().register(skill)
    evolver = SkillEvolver(engine._loader, engine._executor, engine.get_registry())

    with pytest.raises(RuntimeError, match="Only mode 'a'"):
        evolver.evolve(
            "mode_b_test",
            {"query": "hello"},
            [{"id": 1, "rating": 3, "comment": "ok"}],
        )


def test_evolve_no_feedback(engine: CambrianEngine) -> None:
    """피드백 없이 evolve()를 호출하면 RuntimeError를 발생시킨다."""
    with pytest.raises(RuntimeError, match="No feedback"):
        engine.evolve("evolve_test", {"query": "hello"})


def test_evolve_adopted(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Variant 평균 점수가 더 높으면 진화가 채택된다."""

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        """변이된 SKILL.md를 반환한다."""
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved\nImproved instructions here."

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        """스킬 ID에 따라 가짜 실행 결과를 반환한다."""
        _ = self
        _ = input_data
        skill_id = getattr(skill, "id")
        if skill_id == "evolve_test_variant":
            return ExecutionResult(
                skill_id=skill_id,
                success=True,
                output={"html": "<p>variant</p>"},
                execution_time_ms=10,
                mode="a",
            )
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"html": "<p>original</p>"},
            execution_time_ms=100,
            mode="a",
        )

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """Variant가 더 높은 점수를 받도록 Judge 결과를 반환한다."""
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        return JudgeVerdict(
            original_score=5.0,
            variant_score=8.0,
            reasoning="variant is better",
            winner="variant",
        )

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 5, "needs improvement")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is True


def test_evolve_discarded(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Variant 평균 점수가 더 낮으면 진화가 폐기된다."""

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        """변이된 SKILL.md를 반환한다."""
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved\nWorse instructions here."

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        """Variant는 실패하고 original은 성공하도록 결과를 반환한다."""
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

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """Original이 더 높은 점수를 받도록 Judge 결과를 반환한다."""
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        return JudgeVerdict(
            original_score=7.0,
            variant_score=2.0,
            reasoning="original is better",
            winner="original",
        )

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 2, "bad")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is False


def test_evolve_trial_count(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """evolve()는 원본 3회와 variant 3회로 총 6회 실행한다."""
    execute_count = {"count": 0}

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        """변이된 SKILL.md를 반환한다."""
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved\nImproved instructions here."

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        """호출 횟수를 기록하며 실행 결과를 반환한다."""
        _ = self
        _ = input_data
        execute_count["count"] += 1
        skill_id = getattr(skill, "id")
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"html": f"<p>{skill_id}</p>"},
            execution_time_ms=25,
            mode="a",
        )

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """Variant가 더 높은 점수를 받도록 Judge 결과를 반환한다."""
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        return JudgeVerdict(5.0, 8.0, "variant is better", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 5, "count runs")
    engine.evolve("evolve_test", {"query": "hello"})

    assert execute_count["count"] == 6


def test_evolve_judge_called_per_trial(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Judge는 trial 수만큼 정확히 3회 호출된다."""
    judge_count = {"count": 0}

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        """변이된 SKILL.md를 반환한다."""
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved\nImproved instructions here."

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        """가짜 실행 결과를 반환한다."""
        _ = self
        _ = input_data
        skill_id = getattr(skill, "id")
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"html": f"<p>{skill_id}</p>"},
            execution_time_ms=20,
            mode="a",
        )

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """Judge 호출 횟수를 기록한다."""
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        judge_count["count"] += 1
        return JudgeVerdict(5.0, 8.0, "variant is better", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 5, "count judges")
    engine.evolve("evolve_test", {"query": "hello"})

    assert judge_count["count"] == 3


def test_evolve_average_scoring(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Judge 평균 점수로 채택 여부와 child_fitness를 계산한다."""
    judge_count = {"count": 0}

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        """변이된 SKILL.md를 반환한다."""
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved\nImproved instructions here."

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        """가짜 실행 결과를 반환한다."""
        _ = self
        _ = input_data
        skill_id = getattr(skill, "id")
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"html": f"<p>{skill_id}</p>"},
            execution_time_ms=20,
            mode="a",
        )

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """호출 순서별로 다른 Judge 점수를 반환한다."""
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        judge_count["count"] += 1
        if judge_count["count"] == 1:
            return JudgeVerdict(6.0, 8.0, "trial1", "variant")
        if judge_count["count"] == 2:
            return JudgeVerdict(4.0, 9.0, "trial2", "variant")
        return JudgeVerdict(5.0, 7.0, "trial3", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 5, "average scoring")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is True
    assert record.child_fitness == pytest.approx(0.8, abs=0.01)


def test_evolve_tie_not_adopted(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """원본과 variant 평균이 같으면 채택하지 않는다."""

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        """변이된 SKILL.md를 반환한다."""
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved\nTie instructions here."

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        """가짜 실행 결과를 반환한다."""
        _ = self
        _ = input_data
        skill_id = getattr(skill, "id")
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"html": f"<p>{skill_id}</p>"},
            execution_time_ms=20,
            mode="a",
        )

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        """동점 Judge 결과를 반환한다."""
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        return JudgeVerdict(6.0, 6.0, "tie", "tie")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 4, "tie case")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is False


# === Phase 2: judge_reasoning 테스트 ===


def test_evolve_stores_judge_reasoning(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """evolve는 Judge reasoning을 record에 누적 저장한다."""

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved"

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        _ = self
        _ = input_data
        skill_id = getattr(skill, "id")
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"html": f"<p>{skill_id}</p>"},
            execution_time_ms=20,
            mode="a",
        )

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        return JudgeVerdict(5.0, 8.0, "good improvement", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 3, "test")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert "good improvement" in record.judge_reasoning
    assert record.judge_reasoning.count("good improvement") == 3


def test_evolution_history_contains_reasoning(
    engine: CambrianEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """진화 이력에는 Judge reasoning이 저장된다."""

    def fake_mutate(
        self: SkillEvolver,
        skill: object,
        feedback_list: list[dict],
    ) -> str:
        _ = self
        _ = skill
        _ = feedback_list
        return "# Evolved"

    def fake_execute(
        self: SkillExecutor,
        skill: object,
        input_data: dict,
    ) -> ExecutionResult:
        _ = self
        _ = input_data
        skill_id = getattr(skill, "id")
        return ExecutionResult(
            skill_id=skill_id,
            success=True,
            output={"html": f"<p>{skill_id}</p>"},
            execution_time_ms=20,
            mode="a",
        )

    def fake_judge(
        self: SkillJudge,
        original_output: dict | None,
        variant_output: dict | None,
        skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        _ = self
        _ = original_output
        _ = variant_output
        _ = skill_description
        _ = feedback_list
        return JudgeVerdict(5.0, 8.0, "good improvement", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 3, "test")
    engine.evolve("evolve_test", {"query": "hello"})
    history = engine.get_registry().get_evolution_history("evolve_test")

    assert "good improvement" in history[0]["judge_reasoning"]


# === Phase 3: mutate 변이 범위 제한 테스트 ===


def test_mutate_preserves_output_format(
    engine: CambrianEngine,
) -> None:
    """변이 결과에 원본 Output Format 섹션이 보존된다."""
    from engine.llm import LLMProvider

    original_md = (
        '# Test\n\n## Input Format\nJSON input\n\n'
        '## Output Format\nRespond with ONLY a JSON object:\n'
        '```json\n{"html": "..."}\n```\n\n## Design\nOld design'
    )

    class _MockProvider(LLMProvider):
        def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
            # Output Format을 올바르게 유지한 변이 반환
            return (
                '# Test\n\n## Input Format\nJSON input\n\n'
                '## Output Format\nRespond with ONLY a JSON object:\n'
                '```json\n{"html": "..."}\n```\n\n## Design\nImproved design\n\n'
                '## Changelog\n- Improved design section'
            )
        def provider_name(self) -> str:
            return "mock"

    # evolve_test 스킬의 SKILL.md를 Output Format 포함으로 교체
    skill_data = engine.get_registry().get("evolve_test")
    skill_path = Path(skill_data["skill_path"])
    (skill_path / "SKILL.md").write_text(original_md, encoding="utf-8")

    evolver = SkillEvolver(
        engine._loader, engine._executor, engine.get_registry(),
        provider=_MockProvider(),
    )
    skill = engine._loader.load(skill_path)
    result = evolver.mutate(skill, [{"id": 1, "rating": 3, "comment": "improve"}])

    assert "Respond with ONLY a JSON object:" in result
    assert '{"html": "..."}' in result


def test_mutate_restores_output_format(
    engine: CambrianEngine,
) -> None:
    """LLM이 Output Format을 변경하면 원본으로 강제 복원된다."""
    from engine.llm import LLMProvider

    original_md = (
        '# Test\n\n## Output Format\nRespond with ONLY a JSON object:\n'
        '```json\n{"html": "..."}\n```\n\n## Design\nOld design'
    )

    class _BadMutateProvider(LLMProvider):
        def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
            # Output Format을 변경한 잘못된 변이
            return (
                '# Test\n\n## Output Format\nReturn any format you like.\n\n'
                '## Design\nNew design'
            )
        def provider_name(self) -> str:
            return "mock"

    skill_data = engine.get_registry().get("evolve_test")
    skill_path = Path(skill_data["skill_path"])
    (skill_path / "SKILL.md").write_text(original_md, encoding="utf-8")

    evolver = SkillEvolver(
        engine._loader, engine._executor, engine.get_registry(),
        provider=_BadMutateProvider(),
    )
    skill = engine._loader.load(skill_path)
    result = evolver.mutate(skill, [{"id": 1, "rating": 2, "comment": "bad"}])

    # 원본 Output Format이 복원됨
    assert "Respond with ONLY a JSON object:" in result
    # LLM이 넣은 잘못된 내용은 제거됨
    assert "Return any format you like" not in result


# === Phase 4: adoption threshold 테스트 ===


def _patch_evolve_with_verdicts(
    monkeypatch: pytest.MonkeyPatch,
    verdicts_list: list[tuple[float, float]],
) -> None:
    """evolve() 내부를 mock 처리하여 지정된 verdict 점수를 반환하도록 설정한다.

    Args:
        monkeypatch: pytest MonkeyPatch 인스턴스
        verdicts_list: (original_score, variant_score) 튜플 리스트
    """
    call_idx = {"i": 0}

    def fake_mutate(
        self: SkillEvolver, skill: object, feedback_list: list[dict],
    ) -> str:
        _ = self, skill, feedback_list
        return "# Evolved\nThreshold test."

    def fake_execute(
        self: SkillExecutor, skill: object, input_data: dict,
    ) -> ExecutionResult:
        _ = self, input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True,
            output={"html": f"<p>{sid}</p>"},
            execution_time_ms=20, mode="a",
        )

    def fake_judge(
        self: SkillJudge, original_output: dict | None,
        variant_output: dict | None, skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        _ = self, original_output, variant_output, skill_description, feedback_list
        idx = min(call_idx["i"], len(verdicts_list) - 1)
        orig, var = verdicts_list[idx]
        call_idx["i"] += 1
        winner = "variant" if var > orig else ("tie" if var == orig else "original")
        return JudgeVerdict(orig, var, f"trial{idx}", winner)

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)


def test_evolution_adoption_margin_met(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마진 충족(차이 1.0 > 0.5) + 과반 승리 → adopted=True."""
    # 3회 모두 variant=7.0, original=6.0 → 마진 1.0, 승리 3/3
    _patch_evolve_with_verdicts(monkeypatch, [(6.0, 7.0)] * 3)

    engine.feedback("evolve_test", 3, "margin met test")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is True


def test_evolution_adoption_margin_not_met(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마진 미충족(차이 0.3 < 0.5) → adopted=False. 과반 승리해도 거부."""
    # 3회 모두 variant=6.3, original=6.0 → 마진 0.3, 승리 3/3
    _patch_evolve_with_verdicts(monkeypatch, [(6.0, 6.3)] * 3)

    engine.feedback("evolve_test", 3, "margin not met test")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is False


def test_evolution_adoption_majority_not_met(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마진 충족하지만 3회 중 1회만 승리 → adopted=False."""
    # trial1: variant 9.0 > original 5.0 (승리)
    # trial2: variant 5.0 < original 7.0 (패배)
    # trial3: variant 5.0 < original 7.0 (패배)
    # avg_variant=6.33, avg_original=6.33 → 마진 0, 하지만 의도적으로
    # 마진은 충족하도록 조정: (4.0, 8.0), (7.0, 5.0), (7.0, 5.0)
    # avg_orig=6.0, avg_var=6.0 → 마진 0 → 이것도 안됨
    # 다시 설계: (3.0, 8.0), (8.0, 5.0), (8.0, 5.0)
    # avg_orig=6.33, avg_var=6.0 → 마진 음수 → 안됨
    # 정확히: 마진 충족 + 1/3 승리만
    # (5.0, 9.0), (7.0, 6.0), (7.0, 6.0)
    # avg_orig=6.33, avg_var=7.0 → 마진 0.67 > 0.5 ✓, 승리 1/3 ✗
    _patch_evolve_with_verdicts(monkeypatch, [
        (5.0, 9.0),  # variant 승리
        (7.0, 6.0),  # original 승리
        (7.0, 6.0),  # original 승리
    ])

    engine.feedback("evolve_test", 3, "majority not met test")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is False


def test_evolution_adoption_both_conditions(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마진 충족(0.6 > 0.5) + 과반 승리(2/3) → adopted=True."""
    # trial1: variant 7.0 > original 6.0 (승리)
    # trial2: variant 7.0 > original 6.0 (승리)
    # trial3: variant 5.8 < original 6.0 (패배)
    # avg_orig=6.0, avg_var=6.6 → 마진 0.6 > 0.5 ✓, 승리 2/3 > 1.5 ✓
    _patch_evolve_with_verdicts(monkeypatch, [
        (6.0, 7.0),
        (6.0, 7.0),
        (6.0, 5.8),
    ])

    engine.feedback("evolve_test", 3, "both conditions test")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is True


def test_evolution_adoption_tie(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """완전 동점 → margin 0, 승리 0 → adopted=False."""
    _patch_evolve_with_verdicts(monkeypatch, [(6.0, 6.0)] * 3)

    engine.feedback("evolve_test", 3, "tie test")
    record = engine.evolve("evolve_test", {"query": "hello"})

    assert record.adopted is False


# === Phase 5: replay set 테스트 ===


def test_add_evaluation_input(engine: CambrianEngine) -> None:
    """평가 입력을 추가하고 조회할 수 있다."""
    registry = engine.get_registry()
    eval_id = registry.add_evaluation_input(
        skill_id="evolve_test",
        input_data='{"query": "hello"}',
        description="기본 인사 테스트",
    )

    assert eval_id > 0

    inputs = registry.get_evaluation_inputs("evolve_test")
    assert len(inputs) == 1
    assert inputs[0]["id"] == eval_id
    assert inputs[0]["skill_id"] == "evolve_test"
    assert inputs[0]["input_data"] == '{"query": "hello"}'
    assert inputs[0]["description"] == "기본 인사 테스트"

    # 삭제
    registry.remove_evaluation_input(eval_id)
    assert len(registry.get_evaluation_inputs("evolve_test")) == 0


def test_evolve_with_replay_set(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """replay set이 있으면 해당 입력들로 비교를 수행한다."""
    registry = engine.get_registry()
    registry.add_evaluation_input(
        "evolve_test", '{"query": "test1"}', "테스트 입력 1",
    )
    registry.add_evaluation_input(
        "evolve_test", '{"query": "test2"}', "테스트 입력 2",
    )

    captured_inputs: list[dict] = []

    def fake_mutate(
        self: SkillEvolver, skill: object, feedback_list: list[dict],
    ) -> str:
        _ = self, skill, feedback_list
        return "# Evolved\nReplay set test."

    def fake_execute(
        self: SkillExecutor, skill: object, input_data: dict,
    ) -> ExecutionResult:
        _ = self
        captured_inputs.append(input_data)
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True,
            output={"html": f"<p>{sid}</p>"},
            execution_time_ms=20, mode="a",
        )

    def fake_judge(
        self: SkillJudge, original_output: dict | None,
        variant_output: dict | None, skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        _ = self, original_output, variant_output, skill_description, feedback_list
        return JudgeVerdict(5.0, 8.0, "variant better", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 3, "replay set test")
    record = engine.evolve("evolve_test", {"query": "ignored"})

    # replay set 2개 → 원본 2회 + variant 2회 = 4회 실행
    assert len(captured_inputs) == 4
    # 실행된 입력이 replay set의 입력과 일치
    assert captured_inputs[0] == {"query": "test1"}
    assert captured_inputs[1] == {"query": "test1"}
    assert captured_inputs[2] == {"query": "test2"}
    assert captured_inputs[3] == {"query": "test2"}
    assert record.adopted is True


def test_evolve_without_replay_set_fallback(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """replay set이 없으면 기존 로직(test_input × TRIAL_COUNT)으로 동작한다."""
    # evolve_test의 평가 입력이 없는 상태 확인
    registry = engine.get_registry()
    assert len(registry.get_evaluation_inputs("evolve_test")) == 0

    execute_count = {"count": 0}

    def fake_mutate(
        self: SkillEvolver, skill: object, feedback_list: list[dict],
    ) -> str:
        _ = self, skill, feedback_list
        return "# Evolved\nFallback test."

    def fake_execute(
        self: SkillExecutor, skill: object, input_data: dict,
    ) -> ExecutionResult:
        _ = self, input_data
        execute_count["count"] += 1
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True,
            output={"html": f"<p>{sid}</p>"},
            execution_time_ms=20, mode="a",
        )

    def fake_judge(
        self: SkillJudge, original_output: dict | None,
        variant_output: dict | None, skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        _ = self, original_output, variant_output, skill_description, feedback_list
        return JudgeVerdict(5.0, 8.0, "variant better", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 3, "fallback test")
    engine.evolve("evolve_test", {"query": "hello"})

    # TRIAL_COUNT=3 → 원본 3회 + variant 3회 = 6회
    assert execute_count["count"] == 6


def test_replay_set_multiple_inputs(
    engine: CambrianEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """replay set 3개 등록 → evolve 실행 → 3개 verdict 생성."""
    registry = engine.get_registry()
    registry.add_evaluation_input(
        "evolve_test", '{"query": "a"}', "입력 A",
    )
    registry.add_evaluation_input(
        "evolve_test", '{"query": "b"}', "입력 B",
    )
    registry.add_evaluation_input(
        "evolve_test", '{"query": "c"}', "입력 C",
    )

    judge_count = {"count": 0}

    def fake_mutate(
        self: SkillEvolver, skill: object, feedback_list: list[dict],
    ) -> str:
        _ = self, skill, feedback_list
        return "# Evolved\nMultiple inputs test."

    def fake_execute(
        self: SkillExecutor, skill: object, input_data: dict,
    ) -> ExecutionResult:
        _ = self, input_data
        sid = getattr(skill, "id")
        return ExecutionResult(
            skill_id=sid, success=True,
            output={"html": f"<p>{sid}</p>"},
            execution_time_ms=20, mode="a",
        )

    def fake_judge(
        self: SkillJudge, original_output: dict | None,
        variant_output: dict | None, skill_description: str,
        feedback_list: list[dict],
    ) -> JudgeVerdict:
        _ = self, original_output, variant_output, skill_description, feedback_list
        judge_count["count"] += 1
        return JudgeVerdict(5.0, 8.0, f"trial{judge_count['count']}", "variant")

    monkeypatch.setattr(SkillEvolver, "mutate", fake_mutate)
    monkeypatch.setattr(SkillExecutor, "execute", fake_execute)
    monkeypatch.setattr(SkillJudge, "judge", fake_judge)

    engine.feedback("evolve_test", 3, "multiple inputs test")
    record = engine.evolve("evolve_test", {"query": "ignored"})

    # replay set 3개 → Judge 3회 호출
    assert judge_count["count"] == 3
    # 3개 verdict reasoning이 모두 기록됨
    assert "trial1" in record.judge_reasoning
    assert "trial2" in record.judge_reasoning
    assert "trial3" in record.judge_reasoning


def test_ensure_output_format_index_based_replacement():
    """M-3: output format 교체가 정확한 섹션 위치에서만 발생하는지 검증."""
    from engine.evolution import SkillEvolver

    evolver = SkillEvolver.__new__(SkillEvolver)

    original = (
        "# Skill\n\n"
        "## Instructions\nDo stuff.\n\n"
        "## Output Format\n```json\n{\"key\": \"original\"}\n```\n\n"
        "## Notes\nSee Output Format section above for details."
    )

    mutated = (
        "# Skill\n\n"
        "## Instructions\nDo better stuff.\n\n"
        "## Output Format\n```json\n{\"key\": \"CHANGED\"}\n```\n\n"
        "## Notes\nSee Output Format section above for details."
    )

    result = evolver._ensure_output_format(mutated, original)

    # Output Format 섹션이 원본으로 복원됨
    original_section = SkillEvolver._extract_section(original, "## Output Format")
    restored_section = SkillEvolver._extract_section(result, "## Output Format")
    assert restored_section == original_section, "Output Format 섹션 미복원"

    # Notes 섹션의 "Output Format" 텍스트는 변경되지 않아야 함
    assert "See Output Format section above for details." in result, (
        "Notes 섹션의 Output Format 참조 텍스트가 손상됨"
    )
