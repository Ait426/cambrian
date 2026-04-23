"""engine/_data/ 와 루트 schemas/skills 간 드리프트 방지 테스트.

engine/_data/는 pip install 시 번들되는 복사본이다.
루트 schemas/, skills/가 source of truth이며,
이 테스트는 둘이 동기화되어 있는지 확인한다.
"""

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
BUNDLED_DATA = PROJECT_ROOT / "engine" / "_data"
ROOT_SCHEMAS = PROJECT_ROOT / "schemas"
ROOT_SKILLS = PROJECT_ROOT / "skills"


@pytest.fixture
def skip_if_no_data():
    """_data 디렉토리가 없으면 스킵 (아직 생성 전)."""
    if not BUNDLED_DATA.exists():
        pytest.skip("engine/_data/ not yet created")


def test_schemas_in_sync(skip_if_no_data) -> None:
    """루트 schemas/와 engine/_data/schemas/ 파일 목록이 동일하다."""
    if not ROOT_SCHEMAS.exists():
        pytest.skip("root schemas/ not found")

    bundled = BUNDLED_DATA / "schemas"
    assert bundled.exists(), "engine/_data/schemas/ 없음"

    root_files = sorted(f.name for f in ROOT_SCHEMAS.glob("*.json"))
    bundled_files = sorted(f.name for f in bundled.glob("*.json"))

    assert root_files == bundled_files, (
        f"schemas 파일 불일치:\n"
        f"  root:    {root_files}\n"
        f"  bundled: {bundled_files}"
    )


def test_schema_contents_match(skip_if_no_data) -> None:
    """각 스키마 파일의 내용이 동일하다."""
    if not ROOT_SCHEMAS.exists():
        pytest.skip("root schemas/ not found")

    bundled = BUNDLED_DATA / "schemas"
    for root_file in ROOT_SCHEMAS.glob("*.json"):
        bundled_file = bundled / root_file.name
        assert bundled_file.exists(), f"번들에 {root_file.name} 없음"

        root_content = json.loads(root_file.read_text(encoding="utf-8"))
        bundled_content = json.loads(bundled_file.read_text(encoding="utf-8"))

        assert root_content == bundled_content, (
            f"{root_file.name} 내용 불일치 (drift 발생)"
        )


def test_skill_dirs_in_sync(skip_if_no_data) -> None:
    """루트 skills/의 스킬 디렉토리 목록과 번들이 동일하다."""
    if not ROOT_SKILLS.exists():
        pytest.skip("root skills/ not found")

    bundled = BUNDLED_DATA / "skills"
    assert bundled.exists(), "engine/_data/skills/ 없음"

    root_dirs = sorted(
        d.name for d in ROOT_SKILLS.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    bundled_dirs = sorted(
        d.name for d in bundled.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

    assert root_dirs == bundled_dirs, (
        f"skills 디렉토리 불일치:\n"
        f"  root:    {root_dirs}\n"
        f"  bundled: {bundled_dirs}"
    )


def test_skill_meta_yaml_match(skip_if_no_data) -> None:
    """각 스킬의 meta.yaml이 루트와 번들에서 동일하다."""
    import yaml

    if not ROOT_SKILLS.exists():
        pytest.skip("root skills/ not found")

    bundled = BUNDLED_DATA / "skills"
    for root_skill in ROOT_SKILLS.iterdir():
        if not root_skill.is_dir():
            continue
        meta_root = root_skill / "meta.yaml"
        meta_bundled = bundled / root_skill.name / "meta.yaml"

        if not meta_root.exists():
            continue

        assert meta_bundled.exists(), (
            f"번들에 {root_skill.name}/meta.yaml 없음"
        )

        root_meta = yaml.safe_load(meta_root.read_text(encoding="utf-8"))
        bundled_meta = yaml.safe_load(meta_bundled.read_text(encoding="utf-8"))

        assert root_meta == bundled_meta, (
            f"{root_skill.name}/meta.yaml 드리프트 발생"
        )


def test_policy_in_sync(skip_if_no_data) -> None:
    """cambrian_policy.json이 루트와 번들에서 동일하다."""
    root_policy = PROJECT_ROOT / "cambrian_policy.json"
    bundled_policy = BUNDLED_DATA / "cambrian_policy.json"

    if not root_policy.exists():
        pytest.skip("root cambrian_policy.json not found")

    assert bundled_policy.exists(), "번들에 cambrian_policy.json 없음"

    root_content = json.loads(root_policy.read_text(encoding="utf-8"))
    bundled_content = json.loads(bundled_policy.read_text(encoding="utf-8"))

    assert root_content == bundled_content, (
        "cambrian_policy.json 드리프트 발생"
    )
