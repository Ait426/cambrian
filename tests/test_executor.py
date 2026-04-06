"""SkillExecutor 테스트."""

from pathlib import Path

import pytest
import yaml

from conftest import create_valid_skill
from engine.executor import SkillExecutor
from engine.loader import SkillLoader


def test_execute_hello_world(schemas_dir: Path) -> None:
    """hello_world 스킬에 {"text": "Cambrian"}을 입력하면 성공한다."""
    loader = SkillLoader(schemas_dir)
    skill = loader.load(Path(__file__).resolve().parents[1] / "skills" / "hello_world")
    executor = SkillExecutor()

    result = executor.execute(skill, {"text": "Cambrian"})

    assert result.success is True
    assert result.output is not None
    assert result.output["greeting"] == "Hello, Cambrian!"
    assert result.exit_code == 0
    assert result.execution_time_ms > 0
    assert result.mode == "b"


def test_execute_hello_world_empty_input(schemas_dir: Path) -> None:
    """hello_world에 빈 dict를 입력하면 "Hello, World!" 반환."""
    loader = SkillLoader(schemas_dir)
    skill = loader.load(Path(__file__).resolve().parents[1] / "skills" / "hello_world")
    executor = SkillExecutor()

    result = executor.execute(skill, {})

    assert result.success is True
    assert result.output is not None
    assert result.output["greeting"] == "Hello, World!"


def test_execute_crash_skill(schemas_dir: Path) -> None:
    """crash_skill은 항상 실패하고 stderr에 에러 메시지가 있다."""
    loader = SkillLoader(schemas_dir)
    skill = loader.load(Path(__file__).resolve().parents[1] / "skills" / "crash_skill")
    executor = SkillExecutor()

    result = executor.execute(skill, {"message": "test error"})

    assert result.success is False
    assert result.exit_code != 0
    assert "test error" in result.stderr
    assert result.output is None


def test_execute_timeout(schemas_dir: Path) -> None:
    """slow_skill(timeout 2초)에 5초 대기를 시키면 타임아웃 실패."""
    loader = SkillLoader(schemas_dir)
    skill = loader.load(Path(__file__).resolve().parents[1] / "skills" / "slow_skill")
    executor = SkillExecutor()

    result = executor.execute(skill, {"seconds": 5})

    assert result.success is False
    assert result.exit_code == -1
    assert "Timeout" in result.error or "timeout" in result.error.lower()


def test_validate_input_valid(schemas_dir: Path) -> None:
    """정상 입력은 에러 리스트가 비어있다."""
    loader = SkillLoader(schemas_dir)
    skill = loader.load(Path(__file__).resolve().parents[1] / "skills" / "hello_world")
    executor = SkillExecutor()

    errors = executor.validate_input(skill, {"text": "hello"})

    assert errors == []


def test_validate_input_invalid(schemas_dir: Path) -> None:
    """필수 필드가 누락되면 에러 리스트에 메시지가 있다."""
    loader = SkillLoader(schemas_dir)
    skill = loader.load(Path(__file__).resolve().parents[1] / "skills" / "hello_world")
    executor = SkillExecutor()

    errors = executor.validate_input(skill, {"wrong_field": 123})

    assert len(errors) > 0


def test_validate_output_valid(schemas_dir: Path) -> None:
    """정상 출력은 에러 리스트가 비어있다."""
    loader = SkillLoader(schemas_dir)
    skill = loader.load(Path(__file__).resolve().parents[1] / "skills" / "hello_world")
    executor = SkillExecutor()

    errors = executor.validate_output(
        skill,
        {"greeting": "Hello!", "timestamp": "..."},
    )

    assert errors == []


def test_execute_mode_a_no_api_key(
    schemas_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mode 'a' 스킬 실행 시 API 키가 없으면 실패 결과를 반환한다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    skill_dir = create_valid_skill(tmp_path, skill_id="mode_a_skill")
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["mode"] = "a"
    meta_path.write_text(yaml.dump(meta), encoding="utf-8")

    loader = SkillLoader(schemas_dir)
    skill = loader.load(skill_dir)
    executor = SkillExecutor()

    result = executor.execute(skill, {"value": "test"})

    assert result.success is False
    assert result.mode == "a"
    assert "ANTHROPIC_API_KEY" in result.error or "anthropic" in result.error
