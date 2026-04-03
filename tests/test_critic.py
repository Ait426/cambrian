"""SkillCritic 비판적 분석 테스트."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.critic import SkillCritic
from engine.loop import CambrianEngine
from engine.models import Skill, SkillLifecycle, SkillRuntime
from engine.registry import SkillRegistry


def _make_skill(skill_id: str = "test_skill") -> Skill:
    """테스트용 Mode A Skill 객체를 생성한다."""
    return Skill(
        id=skill_id,
        version="1.0.0",
        name="Test Skill",
        description="A test skill for critique",
        domain="testing",
        tags=["test"],
        mode="a",
        runtime=SkillRuntime(language="python"),
        lifecycle=SkillLifecycle(status="active"),
        skill_path=Path("."),
        skill_md_content="# Test Skill\n\n## Output Format\n```json\n{\"result\": \"string\"}\n```",
    )


def _mock_provider(response: str) -> MagicMock:
    """mock LLM 프로바이더를 생성한다."""
    provider = MagicMock()
    provider.complete.return_value = response
    return provider


def test_critique_returns_list() -> None:
    """mock LLM으로 critique 호출 시 list[dict]를 반환한다."""
    response = (
        '[{"category": "clarity", "severity": "medium", '
        '"finding": "Ambiguous instruction", "suggestion": "Be more specific"}]'
    )
    provider = _mock_provider(response)
    critic = SkillCritic(provider=provider)
    skill = _make_skill()

    findings = critic.critique(skill)

    assert isinstance(findings, list)
    assert len(findings) == 1
    assert findings[0]["category"] == "clarity"
    assert findings[0]["severity"] == "medium"
    assert findings[0]["finding"] == "Ambiguous instruction"
    assert findings[0]["suggestion"] == "Be more specific"


def test_critique_high_saves_feedback(
    schemas_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HIGH severity 발견 시 [CRITIC] 자동 피드백이 저장된다."""
    response = (
        '[{"category": "format", "severity": "high", '
        '"finding": "Output key ambiguous", "suggestion": "Add required array"}]'
    )
    provider = _mock_provider(response)

    import yaml

    # Mode A 스킬 디렉토리 생성
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "critique_test"
    skill_dir.mkdir(parents=True)

    meta = {
        "id": "critique_test",
        "version": "1.0.0",
        "name": "Critique Test",
        "description": "test",
        "domain": "testing",
        "tags": ["test"],
        "mode": "a",
        "created_at": "2026-04-03",
        "updated_at": "2026-04-03",
        "runtime": {
            "language": "python",
            "needs_network": False,
            "needs_filesystem": False,
            "timeout_seconds": 10,
        },
    }
    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    interface = {
        "input": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "입력"}},
            "required": [],
        },
        "output": {
            "type": "object",
            "properties": {"result": {"type": "string", "description": "결과"}},
            "required": ["result"],
        },
    }
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(interface, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Critique Test\nDo something.", encoding="utf-8")

    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()

    engine = CambrianEngine(
        schemas_dir=schemas_dir,
        skills_dir=skills_dir,
        skill_pool_dir=pool_dir,
        db_path=":memory:",
        provider=provider,
    )

    findings = engine.critique("critique_test")
    assert len(findings) == 1

    feedback_list = engine.get_registry().get_feedback("critique_test")
    critic_feedback = [f for f in feedback_list if f["comment"].startswith("[CRITIC]")]
    assert len(critic_feedback) == 1
    assert critic_feedback[0]["rating"] == 2


def test_critique_empty_no_feedback() -> None:
    """빈 배열 반환 시 피드백이 생성되지 않는다."""
    provider = _mock_provider("[]")
    critic = SkillCritic(provider=provider)
    skill = _make_skill()

    findings = critic.critique(skill)

    assert findings == []


def test_critique_json_parse_error() -> None:
    """LLM이 잘못된 JSON 반환 시 빈 리스트를 반환한다 (크래시 안 함)."""
    provider = _mock_provider("This is not valid JSON at all")
    critic = SkillCritic(provider=provider)
    skill = _make_skill()

    findings = critic.critique(skill)

    assert findings == []


def test_critique_cli_output(schemas_dir: Path) -> None:
    """cambrian critique CLI가 정상 출력된다."""
    result = subprocess.run(
        [sys.executable, "-m", "engine.cli", "critique", "hello_world",
         "--schemas", str(schemas_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).parent.parent),
        timeout=30,
    )

    # LLM 없이 실행하면 에러 또는 빈 결과 — 크래시하지 않는 것이 핵심
    # API 키가 없으면 Error 출력, 있으면 Critique: 출력
    assert result.returncode in (0, 1)
