from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_DOCS = ROOT / "docs" / "launch"
CLI_TIMEOUT_SECONDS = 20


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=CLI_TIMEOUT_SECONDS,
        check=False,
    )


def _debug(result: subprocess.CompletedProcess[str], cwd: Path) -> str:
    return (
        f"command={result.args}\n"
        f"cwd={cwd}\n"
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _make_auth_demo_project(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_login_placeholder():\n    assert True\n", encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")


def _quickstart_text() -> str:
    readme = _read(ROOT / "README.md")
    start = readme.index("## Quickstart")
    end = readme.index("## Built-in preset compatibility")
    return readme[start:end]


def test_auth_bug_core_exists_in_catalog() -> None:
    catalog = yaml.safe_load(_read(ROOT / "packs" / "catalog.yaml")) or {}
    entries = catalog.get("entries", [])

    assert any(entry.get("pack_id") == "auth-bug-core" for entry in entries)


def test_pack_show_auth_bug_core_works(tmp_path: Path) -> None:
    _make_auth_demo_project(tmp_path)

    result = _cli(tmp_path, "pack", "show", "auth-bug-core")

    assert result.returncode == 0, _debug(result, tmp_path)
    assert "auth-bug-core" in result.stdout
    assert "cambrian install pack auth-bug-core" in result.stdout


def test_launch_install_activate_start_smoke(tmp_path: Path) -> None:
    _make_auth_demo_project(tmp_path)

    install = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert install.returncode == 0, _debug(install, tmp_path)

    doctor = _cli(tmp_path, "install", "doctor")
    assert doctor.returncode == 0, _debug(doctor, tmp_path)
    assert "Install Doctor" in doctor.stdout

    activate = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert activate.returncode == 0, _debug(activate, tmp_path)

    pack_doctor = _cli(tmp_path, "pack", "doctor", "auth-bug-core")
    assert pack_doctor.returncode == 0, _debug(pack_doctor, tmp_path)

    start = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    assert start.returncode == 0, _debug(start, tmp_path)
    payload = json.loads(start.stdout)
    job = payload["job"]

    assert job["pack_id"] == "auth-bug-core"
    assert job["status"] == "waiting_for_ai_reply"
    assert "cambrian pack job-paste" in job["next_command"]
    assert (tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml").exists()
    assert (tmp_path / job["linked_bridge_packet_ref"]).exists()


def test_readme_quickstart_uses_only_launch_path_commands() -> None:
    quickstart = _quickstart_text()

    for command in [
        "cambrian doctor",
        "cambrian project scan",
        "cambrian harness plan",
        "cambrian harness install",
        'cambrian agent dispatch "로그인 에러 수정해"',
    ]:
        assert command in quickstart

    for excluded in [
        "rollout",
        "derivative",
        "release-local",
        "proof-export",
        "registry sync",
        "canary",
        "marketplace",
    ]:
        assert excluded not in quickstart


def test_launch_docs_exist_and_match_golden_path() -> None:
    for name in [
        "LAUNCH_GOLDEN_PATH.md",
        "DEMO_SCRIPT.md",
        "LAUNCH_CHECKLIST.md",
    ]:
        assert (LAUNCH_DOCS / name).exists()

    combined = "\n".join(_read(path) for path in LAUNCH_DOCS.glob("*.md"))

    for phrase in [
        "Cambrian installs AI worker packs into the AI you already use.",
        "auth-bug-core",
        "cambrian pack start \"로그인 에러 수정해\"",
        "cambrian pack job-ingest latest fixtures/ai_reply_patch_candidate.yaml",
        "cambrian pack job-validate latest",
        "cambrian pack proof auth-bug-core",
    ]:
        assert phrase in combined


def test_launch_docs_and_web_make_no_fake_proof_claims() -> None:
    paths = [
        LAUNCH_DOCS / "LAUNCH_GOLDEN_PATH.md",
        LAUNCH_DOCS / "DEMO_SCRIPT.md",
        LAUNCH_DOCS / "LAUNCH_CHECKLIST.md",
        ROOT / "web" / "packs" / "auth-bug-core.html",
    ]
    combined = "\n".join(_read(path).lower() for path in paths)

    assert "seed pack. local proof required." in combined
    assert "fake proof" in combined
    assert "proven" not in combined
    assert "100% proof" not in combined
    assert "100% success" not in combined
    assert "validated_proposal_rate: 1" not in combined
