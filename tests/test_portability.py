"""Cambrian 스킬 패키지 내보내기/가져오기 테스트."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import yaml

from engine.loader import SkillLoader
from engine.portability import SkillPorter
from engine.registry import SkillRegistry


def _create_test_skill(skills_dir: Path, schemas_dir: Path) -> tuple[SkillLoader, SkillRegistry, str]:
    """테스트용 스킬을 생성하고 등록한다."""
    skill_dir = skills_dir / "export_test"
    skill_dir.mkdir(parents=True)

    meta = {
        "id": "export_test",
        "version": "1.0.0",
        "name": "Export Test",
        "description": "export test skill",
        "domain": "testing",
        "tags": ["test", "export"],
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
    interface = {
        "input": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "q"}},
            "required": ["query"],
        },
        "output": {
            "type": "object",
            "properties": {"html": {"type": "string", "description": "h"}},
            "required": ["html"],
        },
    }

    with open(skill_dir / "meta.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    with open(skill_dir / "interface.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(interface, f, allow_unicode=True, sort_keys=False)
    (skill_dir / "SKILL.md").write_text("# Export Test Skill\nTest content.", encoding="utf-8")

    loader = SkillLoader(schemas_dir)
    registry = SkillRegistry(":memory:")
    skill = loader.load(skill_dir)
    registry.register(skill)

    return loader, registry, "export_test"


def test_export_creates_package(schemas_dir: Path, tmp_path: Path) -> None:
    """export 후 .cambrian zip 파일이 생성된다."""
    skills_dir = tmp_path / "skills"
    loader, registry, skill_id = _create_test_skill(skills_dir, schemas_dir)

    porter = SkillPorter(loader, registry, tmp_path / "pool")
    output_dir = tmp_path / "export"
    zip_path = porter.export_skill(skill_id, output_dir)

    assert zip_path.exists()
    assert zip_path.suffix == ".cambrian"


def test_export_contains_files(schemas_dir: Path, tmp_path: Path) -> None:
    """zip 안에 meta.yaml, SKILL.md, 메타데이터가 포함된다."""
    skills_dir = tmp_path / "skills"
    loader, registry, skill_id = _create_test_skill(skills_dir, schemas_dir)

    porter = SkillPorter(loader, registry, tmp_path / "pool")
    zip_path = porter.export_skill(skill_id, tmp_path / "export")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "meta.yaml" in names
        assert "SKILL.md" in names
        assert "interface.yaml" in names
        assert "_cambrian_metadata.json" in names

        # 메타데이터 내용 확인
        metadata = json.loads(zf.read("_cambrian_metadata.json"))
        assert metadata["skill_id"] == "export_test"


def test_import_registers_skill(schemas_dir: Path, tmp_path: Path) -> None:
    """import 후 registry에 스킬이 등록된다."""
    skills_dir = tmp_path / "skills"
    loader, registry, skill_id = _create_test_skill(skills_dir, schemas_dir)

    porter = SkillPorter(loader, registry, tmp_path / "pool")
    zip_path = porter.export_skill(skill_id, tmp_path / "export")

    # 새 registry에서 import
    registry2 = SkillRegistry(":memory:")
    porter2 = SkillPorter(loader, registry2, tmp_path / "pool2")
    imported_id = porter2.import_skill(zip_path)

    assert imported_id == "export_test"
    data = registry2.get("export_test")
    assert data["domain"] == "testing"


def test_export_import_roundtrip(schemas_dir: Path, tmp_path: Path) -> None:
    """export → import 후 원본과 동일한 스킬이 복원된다."""
    skills_dir = tmp_path / "skills"
    loader, registry, skill_id = _create_test_skill(skills_dir, schemas_dir)

    # 피드백 추가
    registry.add_feedback("export_test", 4, "nice skill", "{}", "{}")

    porter = SkillPorter(loader, registry, tmp_path / "pool")
    zip_path = porter.export_skill(skill_id, tmp_path / "export")

    # 새 환경에서 import
    registry2 = SkillRegistry(":memory:")
    porter2 = SkillPorter(loader, registry2, tmp_path / "pool2")
    imported_id = porter2.import_skill(zip_path)

    # 원본과 동일 확인
    original = registry.get("export_test")
    imported = registry2.get("export_test")

    assert imported["id"] == original["id"]
    assert imported["domain"] == original["domain"]
    assert imported["tags"] == original["tags"]
    assert imported["mode"] == original["mode"]

    # SKILL.md 내용 동일 확인
    imported_skill = loader.load(imported["skill_path"])
    assert "Export Test Skill" in (imported_skill.skill_md_content or "")
