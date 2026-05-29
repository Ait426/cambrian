from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from engine.demo_project import DemoProjectCreator


ROOT = Path(__file__).resolve().parents[1]
CLI_TIMEOUT = 30


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("wheel-dist")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", str(out_dir)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(out_dir)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            check=False,
        )
    assert result.returncode == 0, (
        f"wheel build failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    wheels = sorted(out_dir.glob("cambrian-*.whl"))
    assert wheels
    return wheels[-1]


def _run_extracted(extract_root: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(extract_root)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=CLI_TIMEOUT,
        check=False,
    )


def test_wheel_contains_bundled_auth_bug_pack_data(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = set(archive.namelist())

    assert "engine/_data/packs/catalog.yaml" in names
    assert "engine/_data/packs/auth-bug-core.cambrian-pack.yaml" in names


def test_demo_creator_includes_canned_reply_fixture(tmp_path: Path) -> None:
    demo_dir = tmp_path / "demo"
    result = DemoProjectCreator().create("login-bug", demo_dir)
    fixture = demo_dir / "fixtures" / "ai_reply_patch_candidate.yaml"

    assert result.status == "created"
    assert fixture.exists()
    payload = yaml.safe_load(fixture.read_text(encoding="utf-8")) or {}
    target = demo_dir / str(payload["target_path"])
    assert payload["response_kind"] == "patch_candidate"
    assert target.exists()
    assert payload["old_text"] in target.read_text(encoding="utf-8")
    assert str(payload["new_text"]).strip()


def test_installed_wheel_pack_list_works_from_extracted_wheel(built_wheel: Path, tmp_path: Path) -> None:
    extract_root = tmp_path / "wheel-root"
    project_root = tmp_path / "project"
    extract_root.mkdir()
    project_root.mkdir()
    with zipfile.ZipFile(built_wheel) as archive:
        archive.extractall(extract_root)

    listed = _run_extracted(extract_root, project_root, "pack", "list", "--json")
    assert listed.returncode == 0, (
        f"pack list failed\nstdout:\n{listed.stdout}\nstderr:\n{listed.stderr}"
    )
    payload = json.loads(listed.stdout)
    assert any(item["entry"]["pack_id"] == "auth-bug-core" for item in payload["packs"])

    shown = _run_extracted(extract_root, project_root, "pack", "show", "auth-bug-core", "--json")
    assert shown.returncode == 0, (
        f"pack show failed\nstdout:\n{shown.stdout}\nstderr:\n{shown.stderr}"
    )
    show_payload = json.loads(shown.stdout)
    assert show_payload["entry"]["pack_id"] == "auth-bug-core"


def test_cli_help_is_pack_first_and_not_garbled() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "engine.cli", "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=CLI_TIMEOUT,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    help_text = result.stdout
    assert "Cambrian installs a custom AI harness for each project" in help_text
    assert "cambrian doctor" in help_text
    assert "cambrian project scan" in help_text
    assert "cambrian harness plan" in help_text
    assert "cambrian harness install" in help_text
    assert 'cambrian agent dispatch "로그인 에러 수정해"' in help_text
    assert "cambrian init --wizard" not in help_text.split("Start here:", 1)[1].split("Project-first path:", 1)[0]
    for garbled in ["怨", "�", "?꾨", "?앺"]:
        assert garbled not in help_text


def test_release_docs_describe_fresh_install_gate() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install_guide = (ROOT / "docs" / "release" / "RC_INSTALL_GUIDE.md").read_text(encoding="utf-8")
    checklist = (ROOT / "docs" / "release" / "RC_CHECKLIST.md").read_text(encoding="utf-8")
    verification = (ROOT / "docs" / "release" / "RC_VERIFICATION.md").read_text(encoding="utf-8")

    for text in [readme, install_guide, checklist, verification]:
        assert "auth-bug-core" in text
        assert "fixtures/ai_reply_patch_candidate.yaml" in text
    assert "python scripts/smoke_installed_wheel.py" in readme
    assert "RC_INSTALL_GUIDE.md" in readme
    assert "pack catalog not found" in install_guide
    assert "Result: PASS" in checklist
    assert "PASS" in verification


def test_installed_wheel_smoke_keeps_release_dist_artifacts() -> None:
    source = (ROOT / "scripts" / "smoke_installed_wheel.py").read_text(encoding="utf-8")

    assert 'dist_dir = output_dir / "wheel-build-dist"' in source
    assert 'dist_dir = root / "dist"' not in source
    assert 'errors="replace"' in source
