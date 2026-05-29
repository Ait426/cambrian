"""CLI help 발견성 회귀 테스트."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd or ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_top_level_help_shows_start_here_and_advanced_path() -> None:
    result = _run_cli("--help")

    assert result.returncode == 0, result.stderr
    assert "Start here:" in result.stdout
    assert "cambrian doctor" in result.stdout
    assert "cambrian project scan" in result.stdout
    assert "cambrian harness plan" in result.stdout
    assert "cambrian harness install" in result.stdout
    assert 'cambrian agent dispatch "로그인 에러 수정해"' in result.stdout
    assert "Project-first path:" in result.stdout
    assert "Built-in preset compatibility:" in result.stdout
    assert "harness" in result.stdout
    assert "agent" in result.stdout
    assert "auth-bug-core is the first built-in harness preset" in result.stdout


def test_do_help_contains_examples_and_safety_note() -> None:
    result = _run_cli("do", "--help")

    assert result.returncode == 0, result.stderr
    assert "Examples:" in result.stdout
    assert 'cambrian do "fix the login bug"' in result.stdout
    assert "cambrian do --continue" in result.stdout
    assert "--execute 는 diagnose-only" in result.stdout
    assert "explicit apply" in result.stdout


def test_patch_help_is_marked_advanced_manual() -> None:
    result = _run_cli("patch", "--help")

    assert result.returncode == 0, result.stderr
    assert "advanced/manual" in result.stdout.lower()
    assert "cambrian do / cambrian do --continue" in result.stdout
    assert "apply 는 explicit only" in result.stdout


def test_status_help_mentions_memory_and_next_actions() -> None:
    result = _run_cli("status", "--help")

    assert result.returncode == 0, result.stderr
    assert "project memory" in result.stdout
    assert "active work" in result.stdout
    assert "next actions" in result.stdout


def test_doctor_help_mentions_local_readiness() -> None:
    result = _run_cli("doctor", "--help")

    assert result.returncode == 0, result.stderr
    assert "local readiness" in result.stdout
    assert "cambrian doctor --workspace ./demo" in result.stdout


def test_notes_and_memory_help_exist() -> None:
    notes = _run_cli("notes", "--help")
    memory = _run_cli("memory", "--help")

    assert notes.returncode == 0, notes.stderr
    assert memory.returncode == 0, memory.stderr
    assert "Examples:" in notes.stdout
    assert "cambrian notes add" in notes.stdout
    assert "Examples:" in memory.stdout
    assert "cambrian memory list" in memory.stdout


def test_company_snapshot_help_exists() -> None:
    result = _run_cli("company", "snapshot", "--help")

    assert result.returncode == 0, result.stderr
    assert "snapshot" in result.stdout
    assert "--out" in result.stdout
    assert "--json" in result.stdout


def test_help_matches_do_centered_docs() -> None:
    result = _run_cli("--help")
    quickstart = (ROOT / "docs" / "PROJECT_MODE_QUICKSTART.md").read_text(encoding="utf-8")

    assert result.returncode == 0, result.stderr
    for command_text in [
        "cambrian project scan",
        "cambrian harness plan",
        "cambrian harness install",
        "cambrian agent dispatch",
    ]:
        assert command_text in result.stdout
        assert command_text in quickstart


def test_help_commands_do_not_create_project_artifacts(tmp_path: Path) -> None:
    for args in [
        ("--help",),
        ("do", "--help"),
        ("status", "--help"),
        ("doctor", "--help"),
        ("patch", "--help"),
    ]:
        result = _run_cli(*args, cwd=tmp_path)
        assert result.returncode == 0, result.stderr

    assert not (tmp_path / ".cambrian").exists()


def test_help_output_is_readable_korean_not_mojibake() -> None:
    outputs = [
        _run_cli("--help").stdout,
        _run_cli("do", "--help").stdout,
        _run_cli("patch", "--help").stdout,
        _run_cli("status", "--help").stdout,
        _run_cli("doctor", "--help").stdout,
    ]

    combined = "\n".join(outputs)
    for marker in ["濡", "먯", "꾪", "�"]:
        assert marker not in combined
