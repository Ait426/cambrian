"""설치/초기화 E2E 검증 테스트."""

from pathlib import Path

import pytest


def test_init_creates_complete_project(tmp_path: Path, schemas_dir: Path) -> None:
    """cambrian init이 완전한 프로젝트 구조를 생성한다."""
    import subprocess
    import sys

    target = tmp_path / "test_project"

    result = subprocess.run(
        [sys.executable, "-m", "engine", "init", "--dir", str(target)],
        capture_output=True,
        timeout=30,
        cwd=str(Path(__file__).parent.parent),
    )

    assert result.returncode == 0, (
        f"init failed: {result.stderr.decode()}"
    )

    # 필수 디렉토리 확인
    assert (target / "skills").is_dir()
    assert (target / "schemas").is_dir()
    assert (target / "skill_pool").is_dir()

    # 설정 파일 확인
    assert (target / "cambrian.yaml").is_file()

    # schemas에 필수 파일 존재
    assert (target / "schemas" / "meta.schema.json").is_file()
    assert (target / "schemas" / "interface.schema.json").is_file()

    # skills에 최소 1개 시드 스킬 존재
    skill_dirs = [d for d in (target / "skills").iterdir() if d.is_dir()]
    assert len(skill_dirs) > 0, "시드 스킬이 없음"


def test_bundled_data_exists() -> None:
    """패키지 번들 데이터가 존재하는지 확인."""
    from engine._data_path import (
        get_bundled_schemas_dir,
        get_bundled_skills_dir,
    )

    schemas = get_bundled_schemas_dir()
    skills = get_bundled_skills_dir()

    assert schemas.is_dir(), f"번들 schemas 없음: {schemas}"
    assert skills.is_dir(), f"번들 skills 없음: {skills}"
    assert (schemas / "meta.schema.json").is_file()
