"""Cambrian do 앞문 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from engine.brain.models import TaskSpec
from engine.project_do import ProjectDoRunner
from engine.project_mode import ProjectInitializer, ProjectStatusReader


REQUEST_TEXT = "로그인 정규화 버그 수정해"


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _prepare_login_fixture(project_root: Path) -> None:
    _prepare_python_project(project_root)
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth.py").write_text(
        "def normalize_username(username: str) -> str:\n"
        "    return username\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth import normalize_username\n\n"
        "def test_normalize_username_lowercases_email() -> None:\n"
        "    assert normalize_username(\"USER@EXAMPLE.COM\") == \"user@example.com\"\n",
        encoding="utf-8",
    )


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_do_before_init(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)

    proc = _run_cli(["do", REQUEST_TEXT], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Cambrian Do" in proc.stdout
    assert "initialization required" in proc.stdout
    assert "cambrian init --wizard" in proc.stdout
    assert not (tmp_path / ".cambrian" / "project.yaml").exists()


def test_do_creates_session_request_clarification(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    session = ProjectDoRunner().run(REQUEST_TEXT, tmp_path, {})

    assert session.project_initialized is True
    assert session.status == "clarification_open"
    assert session.artifact_path is not None
    assert session.artifacts["request_path"]
    assert session.artifacts["context_scan_path"]
    assert session.artifacts["clarification_path"]
    assert (tmp_path / session.artifact_path).exists()
    assert (tmp_path / session.artifacts["request_path"]).exists()
    assert (tmp_path / session.artifacts["context_scan_path"]).exists()
    assert (tmp_path / session.artifacts["clarification_path"]).exists()


def test_do_use_suggestion_creates_diagnose_task(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    session = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {"use_suggestion": 1},
    )

    assert session.status == "prepared"
    assert session.artifacts["task_spec_path"]
    assert session.artifacts["report_path"] is None
    assert session.summary["selected_sources"] == ["src/auth.py"]
    task_spec = TaskSpec.from_yaml(tmp_path / session.artifacts["task_spec_path"])
    assert task_spec.actions is not None
    assert task_spec.actions[0]["type"] == "inspect_files"


def test_do_source_test_creates_diagnose_task(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before_hash = _sha256(source_path)

    session = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
        },
    )

    assert session.status == "prepared"
    assert session.summary["selected_sources"] == ["src/auth.py"]
    assert session.summary["selected_tests"] == ["tests/test_auth.py"]
    task_spec = TaskSpec.from_yaml(tmp_path / session.artifacts["task_spec_path"])
    assert task_spec.related_tests == ["tests/test_auth.py"]
    assert task_spec.actions is not None
    assert task_spec.actions[0]["type"] == "inspect_files"
    assert _sha256(source_path) == before_hash


def test_do_execute_runs_diagnose_only(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before_hash = _sha256(source_path)

    session = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
            "execute": True,
        },
    )

    assert session.status == "diagnosed"
    assert session.artifacts["brain_run_id"]
    assert session.artifacts["report_path"]
    report_path = tmp_path / session.artifacts["report_path"]
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["diagnostics"]["enabled"] is True
    assert report_payload["diagnostics"]["inspected_files"]
    assert _sha256(source_path) == before_hash


def test_do_execute_without_source_blocked(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before_hash = _sha256(source_path)

    session = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {"execute": True},
    )

    assert session.status == "blocked"
    assert session.artifacts["brain_run_id"] is None
    assert session.artifacts["report_path"] is None
    assert session.errors
    assert _sha256(source_path) == before_hash


def test_do_no_scan_skips_context_scan(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    session = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {"no_scan": True},
    )

    assert session.status == "clarification_open"
    assert session.artifacts["context_scan_path"] is None
    assert session.artifacts["clarification_path"]
    assert any("cambrian context scan" in item for item in session.next_actions)


def test_do_json_output(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    proc = _run_cli(["do", REQUEST_TEXT, "--json"], cwd=tmp_path)
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["session_id"]
    assert payload["status"] in {"needs_context", "clarification_open", "prepared", "diagnosed"}
    assert "artifacts" in payload
    assert "next_actions" in payload


def test_status_shows_recent_do_session(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
        },
    )

    status = ProjectStatusReader().read(tmp_path)
    proc = _run_cli(["status"], cwd=tmp_path)

    assert status.recent_do_session["request"] == REQUEST_TEXT
    assert status.recent_do_session["source"] == "src/auth.py"
    assert "Active work:" in proc.stdout or "Latest completed work:" in proc.stdout
    assert "src/auth.py" in proc.stdout


def test_do_human_output_and_source_immutability(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before_hash = _sha256(source_path)

    basic_proc = _run_cli(["do", REQUEST_TEXT], cwd=tmp_path)
    assert basic_proc.returncode == 0, basic_proc.stderr
    assert "Request:" in basic_proc.stdout
    assert "Understood as:" in basic_proc.stdout
    assert "Found:" in basic_proc.stdout
    assert "Created:" in basic_proc.stdout
    assert "Next:" in basic_proc.stdout
    assert _sha256(source_path) == before_hash

    prepared_session = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {"use_suggestion": 1},
    )
    assert prepared_session.status == "prepared"
    assert _sha256(source_path) == before_hash

    diagnosed_session = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
            "execute": True,
        },
    )
    assert diagnosed_session.status == "diagnosed"
    assert _sha256(source_path) == before_hash
