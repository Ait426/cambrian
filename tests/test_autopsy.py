"""Autopsy 테스트."""

from pathlib import Path

from engine.autopsy import Autopsy
from engine.models import (
    ExecutionResult,
    FailureType,
    Skill,
    SkillLifecycle,
    SkillRuntime,
)


def make_dummy_skill(skill_id: str = "test_skill") -> Skill:
    """테스트용 더미 Skill 객체를 생성한다.

    Args:
        skill_id: 생성할 스킬 ID

    Returns:
        테스트용 Skill 객체
    """
    return Skill(
        id=skill_id,
        version="1.0.0",
        name="Test Skill",
        description="Dummy skill for testing",
        domain="testing",
        tags=["test"],
        mode="b",
        runtime=SkillRuntime(language="python"),
        lifecycle=SkillLifecycle(),
        skill_path=Path("/dummy"),
        interface_input={"type": "object", "properties": {}, "required": []},
        interface_output={"type": "object", "properties": {}, "required": []},
    )


def test_skill_missing() -> None:
    """skill=None으로 분석하면 SKILL_MISSING."""
    autopsy = Autopsy()
    result = ExecutionResult(skill_id="unknown", success=False, error="no skill")

    report = autopsy.analyze(result, skill=None)

    assert report.failure_type == FailureType.SKILL_MISSING
    assert report.needed_skill is not None
    assert report.retry_suggested is False


def test_timeout() -> None:
    """exit_code=-1이면 TIMEOUT."""
    autopsy = Autopsy()
    some_skill = make_dummy_skill("slow")
    result = ExecutionResult(
        skill_id="slow",
        success=False,
        error="Timeout after 2s",
        exit_code=-1,
    )

    report = autopsy.analyze(result, skill=some_skill)

    assert report.failure_type == FailureType.TIMEOUT
    assert report.retry_suggested is True
    assert report.fitness_penalty == 0.3


def test_input_mismatch() -> None:
    """stderr에 TypeError가 있으면 INPUT_MISMATCH."""
    autopsy = Autopsy()
    some_skill = make_dummy_skill()
    result = ExecutionResult(
        skill_id="test",
        success=False,
        stderr="TypeError: expected str got int",
        exit_code=1,
    )

    report = autopsy.analyze(result, skill=some_skill)

    assert report.failure_type == FailureType.INPUT_MISMATCH
    assert report.fitness_penalty == 0.1


def test_execution_error() -> None:
    """stderr에 ValueError가 있으면 EXECUTION_ERROR."""
    autopsy = Autopsy()
    some_skill = make_dummy_skill()
    result = ExecutionResult(
        skill_id="test",
        success=False,
        stderr="ValueError: invalid literal",
        exit_code=1,
    )

    report = autopsy.analyze(result, skill=some_skill)

    assert report.failure_type == FailureType.EXECUTION_ERROR
    assert report.fitness_penalty == 0.5


def test_module_not_found() -> None:
    """ModuleNotFoundError도 EXECUTION_ERROR로 분류."""
    autopsy = Autopsy()
    some_skill = make_dummy_skill()
    result = ExecutionResult(
        skill_id="test",
        success=False,
        stderr="ModuleNotFoundError: No module named 'pandas'",
        exit_code=1,
    )

    report = autopsy.analyze(result, skill=some_skill)

    assert report.failure_type == FailureType.EXECUTION_ERROR


def test_output_invalid() -> None:
    """error에 "Invalid JSON output"이 있으면 OUTPUT_INVALID."""
    autopsy = Autopsy()
    some_skill = make_dummy_skill()
    result = ExecutionResult(
        skill_id="test",
        success=False,
        error="Invalid JSON output: not a json",
        exit_code=0,
    )

    report = autopsy.analyze(result, skill=some_skill)

    assert report.failure_type == FailureType.OUTPUT_INVALID
    assert report.fitness_penalty == 0.4


def test_unknown() -> None:
    """어떤 키워드도 매칭 안 되면 UNKNOWN."""
    autopsy = Autopsy()
    some_skill = make_dummy_skill()
    result = ExecutionResult(
        skill_id="test",
        success=False,
        error="something weird",
        stderr="",
        exit_code=1,
    )

    report = autopsy.analyze(result, skill=some_skill)

    assert report.failure_type == FailureType.UNKNOWN
    assert report.retry_suggested is True


def test_stderr_summary_truncated() -> None:
    """stderr이 500자 초과면 stderr_summary가 500자로 잘린다."""
    autopsy = Autopsy()
    some_skill = make_dummy_skill()
    long_stderr = "x" * 1000
    result = ExecutionResult(
        skill_id="test",
        success=False,
        stderr=long_stderr,
        exit_code=1,
    )

    report = autopsy.analyze(result, skill=some_skill)

    assert len(report.stderr_summary) == 500
