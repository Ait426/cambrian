"""SkillAbsorber 테스트."""

from pathlib import Path

import pytest

from engine.absorber import SkillAbsorber
from engine.exceptions import SecurityViolationError, SkillLoadError
from engine.registry import SkillRegistry


def test_absorb_safe_skill(schemas_dir: Path, tmp_path: Path) -> None:
    """safe_skill을 흡수하면 skill_pool/에 복사되고 Registry에 등록된다."""
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "skill_pool", registry)

    skill = absorber.absorb(Path("test_skills/safe_skill"))

    assert skill.id == "safe_external"
    assert (tmp_path / "skill_pool" / "safe_external").exists()
    assert registry.get("safe_external")["id"] == "safe_external"

    registry.close()


def test_reject_eval_skill(schemas_dir: Path, tmp_path: Path) -> None:
    """malicious_eval을 흡수하면 SecurityViolationError."""
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "skill_pool", registry)

    with pytest.raises(SecurityViolationError):
        absorber.absorb(Path("test_skills/malicious_eval"))

    assert not (tmp_path / "skill_pool" / "malicious_eval").exists()

    registry.close()


def test_reject_subprocess_skill(schemas_dir: Path, tmp_path: Path) -> None:
    """malicious_subprocess를 흡수하면 SecurityViolationError."""
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "skill_pool", registry)

    with pytest.raises(SecurityViolationError):
        absorber.absorb(Path("test_skills/malicious_subprocess"))

    registry.close()


def test_reject_network_liar(schemas_dir: Path, tmp_path: Path) -> None:
    """network_liar(needs_network:false + requests)를 흡수하면 SecurityViolationError."""
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "skill_pool", registry)

    with pytest.raises(SecurityViolationError):
        absorber.absorb(Path("test_skills/network_liar"))

    registry.close()


def test_absorb_nonexistent(schemas_dir: Path, tmp_path: Path) -> None:
    """없는 경로를 흡수하면 SkillLoadError."""
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "skill_pool", registry)

    with pytest.raises(SkillLoadError):
        absorber.absorb("/nonexistent/path")

    registry.close()


def test_is_absorbed(schemas_dir: Path, tmp_path: Path) -> None:
    """흡수 전 False, 흡수 후 True."""
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "skill_pool", registry)

    assert absorber.is_absorbed("safe_external") is False
    absorber.absorb(Path("test_skills/safe_skill"))
    assert absorber.is_absorbed("safe_external") is True

    registry.close()


def test_remove_absorbed(schemas_dir: Path, tmp_path: Path) -> None:
    """흡수 후 remove하면 파일과 Registry에서 모두 삭제."""
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "skill_pool", registry)

    absorber.absorb(Path("test_skills/safe_skill"))
    absorber.remove("safe_external")

    assert not (tmp_path / "skill_pool" / "safe_external").exists()
    assert absorber.is_absorbed("safe_external") is False

    registry.close()
