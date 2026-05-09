from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TS_FIXTURE = ROOT / "tests" / "fixtures" / "typescript_jest_auth_project"


def _run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _copy_ts_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "ts-project"
    shutil.copytree(TS_FIXTURE, target)
    return target


def _make_python_auth_project(root: Path) -> None:
    _write(root / "pyproject.toml", '[project]\nname = "sample-auth"\nversion = "0.1.0"\n')
    _write(root / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(root / "src" / "auth.py", "def login(user):\n    return user\n")
    _write(root / "tests" / "test_auth.py", "def test_login():\n    assert True\n")


def test_typescript_project_blocks_auth_bug_core_install(tmp_path: Path) -> None:
    project = _copy_ts_fixture(tmp_path)

    result = _run_cli(project, "install", "pack", "auth-bug-core", "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "incompatible_harness"
    assert payload["pack"] == "auth-bug-core"
    assert payload["required"]["language"] == "python"
    assert payload["required"]["test_framework"] == "pytest"
    assert payload["detected"]["language"] == "typescript"
    assert payload["detected"]["test_framework"] == "jest"
    assert payload["recommended_harness"] == "typescript-jest-auth-core"


def test_python_pytest_project_allows_auth_bug_core_install(tmp_path: Path) -> None:
    _make_python_auth_project(tmp_path)

    result = _run_cli(tmp_path, "install", "pack", "auth-bug-core", "--json")

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["safe_to_install"] is True
    assert payload["pack_id"] == "auth-bug-core"
