"""Mode A (LLM 기반) 실행 테스트."""

import os
from pathlib import Path

import pytest

from engine.executor import SkillExecutor
from engine.loader import SkillLoader
from engine.models import Skill, SkillLifecycle, SkillRuntime


requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.fixture
def loader(schemas_dir: Path) -> SkillLoader:
    """SkillLoader fixture를 반환한다."""
    return SkillLoader(schemas_dir)


@pytest.fixture
def executor() -> SkillExecutor:
    """SkillExecutor fixture를 반환한다."""
    return SkillExecutor()


def _make_mode_a_skill(skill_id: str, skill_md: str | None = "# Test\nRespond JSON.") -> Skill:
    """테스트용 mode a Skill 객체를 만든다."""
    return Skill(
        id=skill_id,
        version="1.0.0",
        name=skill_id,
        description="test",
        domain="test",
        tags=["test"],
        mode="a",
        runtime=SkillRuntime(language="python", timeout_seconds=30),
        lifecycle=SkillLifecycle(),
        skill_path=Path("."),
        skill_md_content=skill_md,
    )


def test_mode_a_no_api_key(executor: SkillExecutor, monkeypatch: pytest.MonkeyPatch) -> None:
    """ANTHROPIC_API_KEY가 없으면 실패 결과를 반환한다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    skill = _make_mode_a_skill("test_no_key")

    result = executor.execute(skill, {"input": "test"})

    assert result.success is False
    assert result.mode == "a"
    assert "ANTHROPIC_API_KEY" in result.error


def test_mode_a_no_skill_md(executor: SkillExecutor) -> None:
    """SKILL.md가 없으면 실패 결과를 반환한다."""
    skill = _make_mode_a_skill("test_no_md", skill_md=None)

    # API 키 없어도 SKILL.md 없음 체크가 먼저인지 확인
    # 키가 있는 환경에서는 SKILL.md 에러, 없는 환경에서는 키 에러 — 둘 다 실패
    result = executor.execute(skill, {"input": "test"})

    assert result.success is False
    assert result.mode == "a"


def test_extract_json_plain(executor: SkillExecutor) -> None:
    """순수 JSON 텍스트를 올바르게 파싱한다."""
    text = '{"html": "<h1>Hello</h1>", "count": 3}'
    result = executor._extract_json(text)

    assert result is not None
    assert result["html"] == "<h1>Hello</h1>"
    assert result["count"] == 3


def test_extract_json_code_block(executor: SkillExecutor) -> None:
    """```json ... ``` 코드 블록에서 JSON을 추출한다."""
    text = 'Here is the result:\n```json\n{"html": "<p>hi</p>", "ok": true}\n```'
    result = executor._extract_json(text)

    assert result is not None
    assert result["html"] == "<p>hi</p>"


def test_extract_json_embedded(executor: SkillExecutor) -> None:
    """텍스트 중간에 포함된 JSON 객체를 추출한다."""
    text = 'Sure! Here you go: {"key": "value", "num": 42} That is all.'
    result = executor._extract_json(text)

    assert result is not None
    assert result["key"] == "value"
    assert result["num"] == 42


@requires_api_key
def test_csv_to_chart_mode_a(loader: SkillLoader) -> None:
    """csv_to_chart 스킬을 Mode A로 실행한다 (API 키 필요)."""
    executor = SkillExecutor()
    skill = loader.load("skills/csv_to_chart")

    assert skill.mode == "a"

    result = executor.execute(
        skill,
        {
            "csv_data": "Month,Revenue\nJan,12500\nFeb,15800\nMar,14200",
            "chart_type": "bar",
            "title": "Q1 Revenue",
        },
    )

    assert result.success is True
    assert result.output is not None
    assert "html" in result.output
    html = result.output["html"]
    assert "<canvas" in html or "chart" in html.lower()


@requires_api_key
def test_json_to_dashboard_mode_a(loader: SkillLoader) -> None:
    """json_to_dashboard 스킬을 Mode A로 실행한다 (API 키 필요)."""
    executor = SkillExecutor()
    skill = loader.load("skills/json_to_dashboard")

    assert skill.mode == "a"

    result = executor.execute(
        skill,
        {
            "title": "Service Status",
            "metrics": [
                {"label": "DAU", "value": "12,430", "change": "+8.2%"},
                {"label": "Revenue", "value": "$48,500", "change": "+12.3%"},
            ],
            "theme": "blue",
        },
    )

    assert result.success is True
    assert result.output is not None
    assert "html" in result.output
    assert result.output.get("metric_count") == 2


@requires_api_key
def test_landing_page_mode_a(loader: SkillLoader) -> None:
    """landing_page 스킬을 Mode A로 실행한다 (API 키 필요)."""
    executor = SkillExecutor()
    skill = loader.load("skills/landing_page")

    assert skill.mode == "a"

    result = executor.execute(
        skill,
        {
            "product_name": "Cambrian",
            "tagline": "AI that evolves itself",
            "color": "indigo",
        },
    )

    assert result.success is True
    assert result.output is not None
    assert "html" in result.output
    html = result.output["html"]
    assert "Cambrian" in html
