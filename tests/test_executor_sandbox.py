"""executor sandbox 강제 테스트."""
import os
import shutil
import tempfile
from pathlib import Path
import pytest
from engine.exceptions import SandboxEnforcementError
from engine.executor import SkillExecutor
from engine.loader import SkillLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_executor_blocks_network_when_disabled(schemas_dir: Path) -> None:
    """needs_network=false 스킬의 socket 연결이 sandbox에 의해 차단된다."""
    skill = SkillLoader(schemas_dir).load(PROJECT_ROOT / "test_skills" / "network_escaper")
    result = SkillExecutor().execute(skill, {})
    assert result.success is False
    assert "Blocked" in (result.error or "") + (result.stderr or "")


def test_executor_blocks_filesystem_when_disabled(schemas_dir: Path) -> None:
    """needs_filesystem=false 스킬의 외부 파일 읽기가 sandbox에 의해 차단된다."""
    skill = SkillLoader(schemas_dir).load(PROJECT_ROOT / "test_skills" / "filesystem_escaper")
    result = SkillExecutor().execute(skill, {})
    assert result.success is False
    assert "Blocked" in (result.error or "") + (result.stderr or "")


def test_executor_hello_world_unaffected(schemas_dir: Path) -> None:
    """기존 hello_world 스킬은 sandbox 적용 후에도 정상 동작한다."""
    skill = SkillLoader(schemas_dir).load(PROJECT_ROOT / "skills" / "hello_world")
    result = SkillExecutor().execute(skill, {"text": "Cambrian"})
    assert result.success is True
    assert result.output["greeting"] == "Hello, Cambrian!"


def test_executor_blocks_pathlib_read_text(schemas_dir: Path) -> None:
    """needs_filesystem=false 스킬의 pathlib.Path.read_text 우회도 sandbox에 의해 차단된다."""
    skill = SkillLoader(schemas_dir).load(PROJECT_ROOT / "test_skills" / "pathlib_escaper")
    result = SkillExecutor().execute(skill, {})
    assert result.success is False
    assert "Blocked" in (result.error or "") + (result.stderr or "")


def test_executor_sandbox_missing_bootstrap(schemas_dir: Path) -> None:
    """sandbox bootstrap 파일이 없으면 SandboxEnforcementError가 발생한다."""
    skill = SkillLoader(schemas_dir).load(PROJECT_ROOT / "test_skills" / "network_escaper")
    executor = SkillExecutor()
    safe_env = executor._build_safe_env()

    # sandbox/sitecustomize.py를 임시로 이동시켜 bootstrap 누락 상황 재현
    sandbox_dir = Path(__file__).resolve().parents[1] / "engine" / "sandbox"
    bootstrap = sandbox_dir / "sitecustomize.py"
    backup = sandbox_dir / "sitecustomize.py.bak"

    shutil.move(str(bootstrap), str(backup))
    try:
        with pytest.raises(SandboxEnforcementError):
            executor._apply_sandbox_env(skill, safe_env)
    finally:
        shutil.move(str(backup), str(bootstrap))
