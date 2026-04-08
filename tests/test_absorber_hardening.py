"""SkillAbsorber symlink 차단 테스트."""
from pathlib import Path
import pytest
import yaml
from engine.absorber import SkillAbsorber
from engine.exceptions import SymlinkSecurityError
from engine.registry import SkillRegistry


def _make_skill_dir(base: Path, skill_id: str = "test_external") -> Path:
    """테스트용 정상 스킬 디렉토리를 생성한다."""
    d = base / skill_id
    (d / "execute").mkdir(parents=True)
    (d / "meta.yaml").write_text(yaml.dump({
        "id": skill_id, "version": "1.0.0", "name": "T", "description": "t",
        "domain": "testing", "tags": ["test"], "mode": "b",
        "created_at": "2026-04-08", "updated_at": "2026-04-08",
        "runtime": {"language": "python", "needs_network": False,
                    "needs_filesystem": False, "timeout_seconds": 10},
        "lifecycle": {"status": "active", "fitness_score": 0.0,
                      "total_executions": 0, "successful_executions": 0,
                      "last_used": None, "crystallized_at": None},
    }), encoding="utf-8")
    (d / "interface.yaml").write_text(yaml.dump({
        "input": {"type": "object", "properties": {
            "dummy": {"type": "string", "description": "d"},
        }, "required": []},
        "output": {"type": "object", "properties": {
            "result": {"type": "string", "description": "r"},
        }, "required": []},
    }), encoding="utf-8")
    (d / "SKILL.md").write_text("# T\n", encoding="utf-8")
    (d / "execute" / "main.py").write_text(
        'import json,sys\ndef run(input_data: dict) -> dict:\n    return {}\nif __name__ == "__main__":\n    print(json.dumps(run({})))',
        encoding="utf-8",
    )
    return d


def test_absorber_rejects_symlinked_files(tmp_path: Path, schemas_dir: Path) -> None:
    """symlink가 포함된 스킬은 흡수가 차단되고 pool에 복사되지 않는다."""
    skill_dir = _make_skill_dir(tmp_path / "source")
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    (skill_dir / "execute" / "evil.py").symlink_to(target)

    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "pool", registry)
    with pytest.raises(SymlinkSecurityError):
        absorber.absorb(skill_dir)
    assert not (tmp_path / "pool" / "test_external").exists()
    registry.close()


def test_absorber_rejects_symlink_to_parent(tmp_path: Path, schemas_dir: Path) -> None:
    """부모 디렉토리를 가리키는 symlink도 차단된다."""
    skill_dir = _make_skill_dir(tmp_path / "source")
    (skill_dir / "escape.txt").symlink_to(tmp_path)

    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "pool", registry)
    with pytest.raises(SymlinkSecurityError):
        absorber.absorb(skill_dir)
    registry.close()


def test_absorber_accepts_clean_skill(tmp_path: Path, schemas_dir: Path) -> None:
    """symlink 없는 정상 스킬은 정상적으로 흡수된다."""
    skill_dir = _make_skill_dir(tmp_path / "source")
    registry = SkillRegistry(":memory:")
    absorber = SkillAbsorber(schemas_dir, tmp_path / "pool", registry)
    skill = absorber.absorb(skill_dir)
    assert skill.id == "test_external"
    assert (tmp_path / "pool" / "test_external").exists()
    registry.close()
