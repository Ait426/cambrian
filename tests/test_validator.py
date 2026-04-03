"""SkillValidator 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.validator import SkillValidator


VALID_META = {
    "id": "hello_world",
    "version": "1.0.0",
    "name": "Hello World",
    "description": "입력 텍스트에 인사말을 붙여 반환하는 테스트용 스킬",
    "domain": "utility",
    "tags": ["test", "greeting", "utility"],
    "author": "cambrian",
    "license": "MIT",
    "created_at": "2026-04-01",
    "updated_at": "2026-04-01",
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

VALID_INTERFACE = {
    "input": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "인사말을 붙일 대상 텍스트",
            }
        },
        "required": ["text"],
    },
    "output": {
        "type": "object",
        "properties": {
            "greeting": {
                "type": "string",
                "description": "인사말이 붙은 결과 텍스트",
            },
            "timestamp": {
                "type": "string",
                "format": "datetime",
                "description": "실행 시각 (ISO 8601)",
            },
        },
        "required": ["greeting"],
    },
}

VALID_SKILL_MD = "# Hello World Skill\n"
VALID_EXECUTE = "def run(input_data: dict) -> dict:\n    return {'greeting': 'Hello, World!'}\n"


def create_valid_skill(tmp_path: Path) -> Path:
    """Create a valid skill directory for tests."""
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()

    (skill_dir / "meta.yaml").write_text(
        yaml.safe_dump(VALID_META, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "interface.yaml").write_text(
        yaml.safe_dump(VALID_INTERFACE, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    execute_dir = skill_dir / "execute"
    execute_dir.mkdir()
    (execute_dir / "main.py").write_text(VALID_EXECUTE, encoding="utf-8")
    return skill_dir


@pytest.fixture
def validator() -> SkillValidator:
    """Create a validator that uses project schemas."""
    project_root = Path(__file__).resolve().parents[1]
    return SkillValidator(project_root / "schemas")


def test_valid_skill_passes(validator: SkillValidator) -> None:
    """skills/hello_world 디렉토리를 검증하면 valid=True를 반환한다."""
    project_root = Path(__file__).resolve().parents[1]
    result = validator.validate(project_root / "skills" / "hello_world")

    assert result.valid is True
    assert result.skill_id == "hello_world"
    assert result.errors == []


def test_missing_meta_yaml(tmp_path: Path, validator: SkillValidator) -> None:
    """meta.yaml이 없는 디렉토리를 검증하면 valid=False + 에러 메시지."""
    skill_dir = create_valid_skill(tmp_path)
    (skill_dir / "meta.yaml").unlink()

    result = validator.validate(skill_dir)

    assert result.valid is False
    assert any("meta.yaml" in error for error in result.errors)


def test_invalid_meta_id_format(tmp_path: Path, validator: SkillValidator) -> None:
    """id가 'Hello-World' (대문자+하이픈)이면 검증 실패."""
    skill_dir = create_valid_skill(tmp_path)
    meta_path = skill_dir / "meta.yaml"
    meta_data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta_data["id"] = "Hello-World"
    meta_path.write_text(
        yaml.safe_dump(meta_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = validator.validate(skill_dir)

    assert result.valid is False
    assert any("id 형식 오류" in error for error in result.errors)


def test_interface_missing_description(tmp_path: Path, validator: SkillValidator) -> None:
    """interface.yaml에서 input property에 description이 없으면 실패."""
    skill_dir = create_valid_skill(tmp_path)
    interface_path = skill_dir / "interface.yaml"
    interface_data = yaml.safe_load(interface_path.read_text(encoding="utf-8"))
    del interface_data["input"]["properties"]["text"]["description"]
    interface_path.write_text(
        yaml.safe_dump(interface_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = validator.validate(skill_dir)

    assert result.valid is False
    assert any("description" in error for error in result.errors)


def test_mode_b_without_execute(tmp_path: Path, validator: SkillValidator) -> None:
    """mode가 'b'인데 execute/main.py가 없으면 실패."""
    skill_dir = create_valid_skill(tmp_path)
    (skill_dir / "execute" / "main.py").unlink()
    (skill_dir / "execute").rmdir()

    result = validator.validate(skill_dir)

    assert result.valid is False
    assert any("execute/main.py" in error for error in result.errors)


def test_execute_without_run_function(tmp_path: Path, validator: SkillValidator) -> None:
    """execute/main.py가 있지만 run() 함수가 정의되지 않으면 실패."""
    skill_dir = create_valid_skill(tmp_path)
    (skill_dir / "execute" / "main.py").write_text(
        "def not_run():\n    return {}\n",
        encoding="utf-8",
    )

    result = validator.validate(skill_dir)

    assert result.valid is False
    assert any("run() 함수가 정의되지 않음" in error for error in result.errors)


def test_mode_a_without_execute_passes(tmp_path: Path, validator: SkillValidator) -> None:
    """mode가 'a'이면 execute/main.py가 없어도 valid=True."""
    skill_dir = create_valid_skill(tmp_path)
    meta_path = skill_dir / "meta.yaml"
    meta_data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta_data["mode"] = "a"
    meta_path.write_text(
        yaml.safe_dump(meta_data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "execute" / "main.py").unlink()
    (skill_dir / "execute").rmdir()

    result = validator.validate(skill_dir)

    assert result.valid is True


def test_broken_yaml(tmp_path: Path, validator: SkillValidator) -> None:
    """meta.yaml 내용이 유효한 YAML이 아니면 파싱 에러."""
    skill_dir = create_valid_skill(tmp_path)
    (skill_dir / "meta.yaml").write_text("{{invalid yaml content", encoding="utf-8")

    result = validator.validate(skill_dir)

    assert result.valid is False
    assert result.skill_id is None
    assert any("YAML 파싱 오류" in error for error in result.errors)
