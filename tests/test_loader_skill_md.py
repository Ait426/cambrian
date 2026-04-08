"""loader SKILL.md 강제 테스트."""
from pathlib import Path
import pytest
import yaml
from conftest import create_valid_skill
from engine.exceptions import SkillValidationError
from engine.loader import SkillLoader


def test_loader_rejects_mode_a_without_skill_md(tmp_path: Path, schemas_dir: Path) -> None:
    """mode 'a' 스킬에 SKILL.md가 없으면 SkillValidationError."""
    skill_dir = create_valid_skill(tmp_path)
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["mode"] = "a"
    meta_path.write_text(yaml.dump(meta), encoding="utf-8")
    (skill_dir / "SKILL.md").unlink()

    with pytest.raises(SkillValidationError):
        SkillLoader(schemas_dir).load(skill_dir)


def test_loader_accepts_mode_a_with_skill_md(tmp_path: Path, schemas_dir: Path) -> None:
    """mode 'a' 스킬에 SKILL.md가 있으면 정상 로드."""
    skill_dir = create_valid_skill(tmp_path)
    meta_path = skill_dir / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["mode"] = "a"
    meta_path.write_text(yaml.dump(meta), encoding="utf-8")

    skill = SkillLoader(schemas_dir).load(skill_dir)
    assert skill.mode == "a"
    assert skill.skill_md_content is not None


def test_loader_mode_b_still_requires_skill_md(tmp_path: Path, schemas_dir: Path) -> None:
    """mode 'b' 스킬도 SKILL.md가 없으면 SkillValidationError."""
    skill_dir = create_valid_skill(tmp_path)
    (skill_dir / "SKILL.md").unlink()

    with pytest.raises(SkillValidationError):
        SkillLoader(schemas_dir).load(skill_dir)
