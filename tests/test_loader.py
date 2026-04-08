"""SkillLoader 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import create_valid_skill

from engine.exceptions import SkillLoadError, SkillValidationError
from engine.loader import SkillLoader
from engine.models import Skill, SkillLifecycle, SkillRuntime


def test_load_valid_skill(tmp_path: Path, schemas_dir: Path) -> None:
    """정상 스킬 디렉토리를 로드하면 Skill 객체가 반환된다."""
    skill_dir = create_valid_skill(tmp_path)
    loader = SkillLoader(schemas_dir)

    skill = loader.load(skill_dir)

    assert isinstance(skill, Skill)
    assert skill.id == "test_skill"
    assert skill.mode == "b"
    assert isinstance(skill.runtime, SkillRuntime)
    assert isinstance(skill.lifecycle, SkillLifecycle)
    assert skill.skill_path.is_absolute()


def test_load_hello_world(schemas_dir: Path) -> None:
    """실제 skills/hello_world 디렉토리를 로드한다."""
    loader = SkillLoader(schemas_dir)
    project_root = Path(__file__).resolve().parents[1]

    skill = loader.load(project_root / "skills" / "hello_world")

    assert skill.id == "hello_world"
    assert skill.runtime.language == "python"
    assert skill.interface_input["properties"]["text"]["type"] == "string"
    assert "greeting" in skill.interface_output["properties"]
    assert skill.skill_md_content is not None
    assert "Hello World" in skill.skill_md_content


def test_load_nonexistent_directory(schemas_dir: Path) -> None:
    """존재하지 않는 경로를 로드하면 SkillLoadError."""
    loader = SkillLoader(schemas_dir)

    with pytest.raises(SkillLoadError):
        loader.load("/nonexistent/path")


def test_load_invalid_skill(tmp_path: Path, schemas_dir: Path) -> None:
    """meta.yaml의 id가 유효하지 않으면 SkillValidationError."""
    skill_dir = create_valid_skill(tmp_path)
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["id"] = "INVALID-ID"
    meta_path.write_text(yaml.dump(meta), encoding="utf-8")

    loader = SkillLoader(schemas_dir)

    with pytest.raises(SkillValidationError) as exc_info:
        loader.load(skill_dir)

    assert len(exc_info.value.errors) > 0


def test_load_without_lifecycle(tmp_path: Path, schemas_dir: Path) -> None:
    """meta.yaml에 lifecycle 섹션이 없어도 기본값으로 로드된다."""
    skill_dir = create_valid_skill(tmp_path)
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    del meta["lifecycle"]
    meta_path.write_text(yaml.dump(meta), encoding="utf-8")

    loader = SkillLoader(schemas_dir)
    skill = loader.load(skill_dir)

    assert skill.lifecycle.status == "newborn"
    assert skill.lifecycle.fitness_score == 0.0
    assert skill.lifecycle.total_executions == 0


def test_load_mode_a_without_skill_md(tmp_path: Path, schemas_dir: Path) -> None:
    """mode 'a' 스킬에서 SKILL.md가 없으면 load 단계에서 SkillValidationError."""
    skill_dir = create_valid_skill(tmp_path)
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["mode"] = "a"
    meta_path.write_text(yaml.dump(meta), encoding="utf-8")
    (skill_dir / "SKILL.md").unlink()

    loader = SkillLoader(schemas_dir)
    with pytest.raises(SkillValidationError):
        loader.load(skill_dir)


def test_load_directory(tmp_path: Path, schemas_dir: Path) -> None:
    """base_dir 안의 유효한 스킬만 로드하고, 잘못된 건 건너뛴다."""
    valid_skill_dir = create_valid_skill(tmp_path, skill_id="valid_skill")

    invalid_skill_dir = create_valid_skill(tmp_path, skill_id="invalid_skill")
    invalid_meta_path = invalid_skill_dir / "meta.yaml"
    invalid_meta = yaml.safe_load(invalid_meta_path.read_text(encoding="utf-8"))
    invalid_meta["id"] = "INVALID-ID"
    invalid_meta_path.write_text(yaml.dump(invalid_meta), encoding="utf-8")

    not_a_skill_dir = tmp_path / "not_a_skill"
    not_a_skill_dir.mkdir()

    loader = SkillLoader(schemas_dir)
    skills = loader.load_directory(tmp_path)

    assert len(skills) == 1
    assert skills[0].id == valid_skill_dir.name
