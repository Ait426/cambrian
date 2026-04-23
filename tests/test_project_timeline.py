"""Cambrian 프로젝트 타임라인 상태 화면 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from engine.project_continue import ProjectDoContinuationRunner
from engine.project_do import ProjectDoRunner
from engine.project_mode import (
    ProjectInitializer,
    ProjectStatusReader,
    render_status_summary,
)
from engine.project_timeline import ProjectTimelineReader

REQUEST_TEXT = "로그인 에러 수정해"


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


def _prepare_login_fixture(project_root: Path) -> None:
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = ['.']\naddopts = '-q'\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (project_root / "src" / "auth.py").write_text(
        "def normalize_username(username: str) -> str:\n"
        "    return username\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth import normalize_username\n\n"
        "def test_normalize_username_lowercases_email() -> None:\n"
        "    assert normalize_username('USER@EXAMPLE.COM') == 'user@example.com'\n",
        encoding="utf-8",
    )


def _make_initialized_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _prepare_login_fixture(project_root)
    result = ProjectInitializer().init(project_root)
    assert result.status == "initialized"
    return project_root


def _make_diagnosed_session(project_root: Path):
    session = ProjectDoRunner().run(
        REQUEST_TEXT,
        project_root,
        {
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
            "execute": True,
        },
    )
    assert session.current_stage == "diagnosed"
    assert session.artifacts["report_path"]
    return session


def _make_validated_session(project_root: Path):
    diagnosed = _make_diagnosed_session(project_root)
    session = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": diagnosed.session_id,
            "old_choice": "old-1",
            "new_text": "return username.strip().lower()",
            "propose": True,
            "validate": True,
        },
    )
    assert session.current_stage == "patch_proposal_validated"
    assert session.artifacts["patch_proposal_path"]
    return session


def _make_adopted_session(project_root: Path):
    validated = _make_validated_session(project_root)
    session = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": validated.session_id,
            "apply": True,
            "reason": "normalize username before login",
        },
    )
    assert session.current_stage == "adopted"
    assert session.artifacts["adoption_record_path"]
    return session


def test_status_before_init(tmp_path: Path) -> None:
    reader = ProjectTimelineReader()

    view = reader.read_project_status(tmp_path)
    proc = _run_cli(["status"], cwd=tmp_path)

    assert view.initialized is False
    assert "cambrian init --wizard" in view.global_next_actions[0]
    assert proc.returncode == 0, proc.stderr
    assert "Cambrian is not fitted to this project yet." in proc.stdout


def test_build_timeline_from_session_artifact(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_diagnosed_session(project_root)

    timeline = ProjectTimelineReader().read_session_timeline(project_root, session.session_id)

    assert timeline.current_stage == "diagnosed"
    assert timeline.status == "diagnosis complete"
    assert [event.kind for event in timeline.events][:4] == [
        "request",
        "context_scan",
        "clarification",
        "diagnosis",
    ]
    assert "src/auth.py" in timeline.selected_sources


def test_timeline_with_adoption_and_latest_summary(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    adopted = _make_adopted_session(project_root)

    reader = ProjectTimelineReader()
    timeline = reader.read_session_timeline(project_root, adopted.session_id)
    view = reader.read_project_status(project_root)

    assert any(event.kind == "adoption" for event in timeline.events)
    assert timeline.current_stage == "adopted"
    assert view.latest_adoption is not None
    assert view.latest_adoption["target"] == "src/auth.py"
    assert view.latest_adoption["tests"] == "passed"


def test_lessons_extraction_from_feedback(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    feedback_dir = project_root / ".cambrian" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    (feedback_dir / "feedback_001.json").write_text(
        json.dumps(
            {
                "keep_patterns": ["Run auth tests before login patches"],
                "avoid_patterns": ["Avoid broad refactors without tests"],
                "suggested_next_actions": ["cambrian do --continue"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    view = ProjectTimelineReader().read_project_status(project_root)

    assert any("Run auth tests before login patches" in item for item in view.recent_lessons)
    assert any("Avoid broad refactors without tests" in item for item in view.recent_lessons)


def test_malformed_artifact_tolerated(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    sessions_dir = project_root / ".cambrian" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "do_session_broken.yaml").write_text("session_id: [broken\n", encoding="utf-8")

    view = ProjectTimelineReader().read_project_status(project_root)

    assert view.initialized is True
    assert view.warnings


def test_missing_referenced_artifact_tolerated(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_diagnosed_session(project_root)
    report_path = project_root / session.artifacts["report_path"]
    report_path.unlink()

    timeline = ProjectTimelineReader().read_session_timeline(project_root, session.session_id)

    assert timeline.warnings
    assert any("report" in item.lower() or "json" in item.lower() for item in timeline.warnings)
    assert any(event.kind == "diagnosis" for event in timeline.events)


def test_active_session_selection(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    _make_adopted_session(project_root)
    active = ProjectDoRunner().run(
        "README 문서 정리",
        project_root,
        {
            "no_scan": True,
        },
    )

    view = ProjectTimelineReader().read_project_status(project_root)

    assert view.active_sessions
    assert view.active_sessions[0].session_id == active.session_id
    assert view.active_sessions[0].current_stage in {"needs_context", "clarification_open"}


def test_cli_status_timeline_and_session_smoke(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_validated_session(project_root)

    timeline_proc = _run_cli(["status", "--timeline"], cwd=project_root)
    session_proc = _run_cli(["status", "--session", session.session_id], cwd=project_root)

    assert timeline_proc.returncode == 0, timeline_proc.stderr
    assert "Cambrian Timeline" in timeline_proc.stdout
    assert REQUEST_TEXT in timeline_proc.stdout
    assert "next:" in timeline_proc.stdout

    assert session_proc.returncode == 0, session_proc.stderr
    assert "Session Timeline" in session_proc.stdout
    assert "Events:" in session_proc.stdout
    assert "Next:" in session_proc.stdout


def test_status_json_output(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_diagnosed_session(project_root)

    status_proc = _run_cli(["status", "--json"], cwd=project_root)
    timeline_proc = _run_cli(["status", "--timeline", "--json"], cwd=project_root)
    session_proc = _run_cli(["status", "--session", session.session_id, "--json"], cwd=project_root)

    status_payload = json.loads(status_proc.stdout)
    timeline_payload = json.loads(timeline_proc.stdout)
    session_payload = json.loads(session_proc.stdout)

    assert status_payload["initialized"] is True
    assert "active_sessions" in status_payload
    assert "recent_sessions" in timeline_payload
    assert session_payload["current_stage"] == "diagnosed"
    assert "events" in session_payload


def test_status_and_timeline_are_read_only(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_diagnosed_session(project_root)
    source_path = project_root / "src" / "auth.py"
    session_path = project_root / ".cambrian" / "sessions" / f"do_session_{session.session_id}.yaml"
    before_source = _sha256(source_path)
    before_session = _sha256(session_path)

    ProjectStatusReader().read(project_root)
    ProjectTimelineReader().read_project_status(project_root)
    ProjectTimelineReader().read_session_timeline(project_root, session.session_id)
    _run_cli(["status"], cwd=project_root)
    _run_cli(["status", "--timeline"], cwd=project_root)
    _run_cli(["status", "--session", session.session_id], cwd=project_root)

    assert _sha256(source_path) == before_source
    assert _sha256(session_path) == before_session


def test_rendered_status_shows_active_work_and_learned(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    _make_adopted_session(project_root)

    status = ProjectStatusReader().read(project_root)
    rendered = render_status_summary(status)

    assert "Active work:" in rendered or "Latest completed work:" in rendered
    assert "Recent journey:" in rendered
    assert "Learned:" in rendered
    assert "Next:" in rendered
