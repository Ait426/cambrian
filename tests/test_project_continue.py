"""Cambrian do continue 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_continue import DoContinuationPlanner, ProjectDoContinuationRunner
from engine.project_do import DoSession, DoSessionStore, ProjectDoRunner
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _make_initialized_project(tmp_path: Path) -> Path:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    return tmp_path


def _make_clarification_session(project_root: Path) -> DoSession:
    return ProjectDoRunner().run(REQUEST_TEXT, project_root, {})


def _make_diagnosed_session(project_root: Path) -> DoSession:
    return ProjectDoRunner().run(
        REQUEST_TEXT,
        project_root,
        {
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
            "execute": True,
        },
    )


def _make_patch_intent_draft_session(project_root: Path) -> DoSession:
    diagnosed = _make_diagnosed_session(project_root)
    return ProjectDoContinuationRunner().run(project_root, {"session": diagnosed.session_id})


def _make_patch_intent_ready_session(project_root: Path) -> DoSession:
    draft = _make_patch_intent_draft_session(project_root)
    return ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": draft.session_id,
            "old_choice": "old-1",
            "new_text": "return username.strip().lower()",
        },
    )


def _make_patch_proposal_ready_session(project_root: Path) -> DoSession:
    ready = _make_patch_intent_ready_session(project_root)
    return ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": ready.session_id,
            "propose": True,
        },
    )


def _make_validated_session(project_root: Path) -> DoSession:
    ready = _make_patch_intent_ready_session(project_root)
    return ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": ready.session_id,
            "propose": True,
            "validate": True,
        },
    )


def test_resolve_latest_active_session(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    store = DoSessionStore()
    adopted = DoSession(
        schema_version="1.1.0",
        session_id="do-old",
        created_at="2026-04-15T01:00:00Z",
        updated_at="2026-04-15T01:00:00Z",
        user_request="old",
        project_initialized=True,
        intent=None,
        selected_skills=[],
        status="adopted",
        current_stage="adopted",
        artifacts={"session_path": None},
        summary={},
        next_actions=[],
        continuations=[],
    )
    active = DoSession(
        schema_version="1.1.0",
        session_id="do-new",
        created_at="2026-04-15T02:00:00Z",
        updated_at="2026-04-15T02:00:00Z",
        user_request="new",
        project_initialized=True,
        intent=None,
        selected_skills=[],
        status="clarification_open",
        current_stage="clarification_open",
        artifacts={"session_path": None},
        summary={},
        next_actions=["cambrian do --continue --use-suggestion 1"],
        continuations=[],
    )
    store.save(project_root, adopted)
    store.save(project_root, active)

    resolved = store.resolve_path(project_root)
    loaded = store.load(resolved)

    assert loaded.session_id == "do-new"


def test_continue_clarification_with_use_suggestion(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_clarification_session(project_root)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": session.session_id,
            "use_suggestion": 1,
        },
    )

    assert continued.current_stage == "diagnose_ready"
    assert continued.artifacts["task_spec_path"] is not None
    assert continued.summary["selected_sources"] == ["src/auth.py"]


def test_continue_clarification_with_execute(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_clarification_session(project_root)
    source_path = project_root / "src" / "auth.py"
    before_hash = _sha256(source_path)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": session.session_id,
            "use_suggestion": 1,
            "execute": True,
        },
    )

    assert continued.current_stage == "diagnosed"
    assert continued.artifacts["report_path"] is not None
    assert _sha256(source_path) == before_hash


def test_continue_diagnosed_creates_patch_intent(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    diagnosed = _make_diagnosed_session(project_root)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {"session": diagnosed.session_id},
    )

    assert continued.current_stage == "patch_intent_draft"
    assert continued.artifacts["patch_intent_path"] is not None
    assert continued.summary["old_text_candidates"]


def test_continue_diagnosed_with_old_new_propose_validate(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    diagnosed = _make_diagnosed_session(project_root)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": diagnosed.session_id,
            "old_choice": "old-1",
            "new_text": "return username.strip().lower()",
            "propose": True,
            "validate": True,
        },
    )

    assert continued.current_stage == "patch_proposal_validated"
    assert continued.artifacts["patch_intent_path"] is not None
    assert continued.artifacts["patch_proposal_path"] is not None
    proposal_payload = _read_yaml(project_root / continued.artifacts["patch_proposal_path"])
    assert proposal_payload["validation"]["status"] == "passed"


def test_continue_intent_draft_fill(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    draft = _make_patch_intent_draft_session(project_root)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": draft.session_id,
            "old_choice": "old-1",
            "new_text": "return username.strip().lower()",
        },
    )

    assert continued.current_stage == "patch_intent_ready"
    intent_payload = _read_yaml(project_root / continued.artifacts["patch_intent_path"])
    assert intent_payload["status"] == "ready_for_proposal"


def test_continue_proposal_ready_validate(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    ready = _make_patch_proposal_ready_session(project_root)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": ready.session_id,
            "validate": True,
        },
    )

    assert continued.current_stage == "patch_proposal_validated"
    proposal_payload = _read_yaml(project_root / continued.artifacts["patch_proposal_path"])
    assert proposal_payload["validation"]["status"] == "passed"


def test_continue_validated_proposal_apply_requires_reason(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    validated = _make_validated_session(project_root)
    source_path = project_root / "src" / "auth.py"
    before_hash = _sha256(source_path)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": validated.session_id,
            "apply": True,
        },
    )

    assert continued.status == "blocked"
    assert continued.current_stage == "patch_proposal_validated"
    assert continued.artifacts["adoption_record_path"] is None
    assert _sha256(source_path) == before_hash


def test_continue_validated_proposal_apply_success(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    validated = _make_validated_session(project_root)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": validated.session_id,
            "apply": True,
            "reason": "fix login normalization",
        },
    )

    assert continued.current_stage == "adopted"
    assert continued.artifacts["adoption_record_path"] is not None
    assert (project_root / continued.artifacts["adoption_record_path"]).exists()
    latest_path = project_root / ".cambrian" / "adoptions" / "_latest.json"
    assert latest_path.exists()


def test_no_auto_apply_by_default(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    validated = _make_validated_session(project_root)
    source_path = project_root / "src" / "auth.py"
    before_hash = _sha256(source_path)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": validated.session_id,
        },
    )

    assert continued.current_stage == "patch_proposal_validated"
    assert continued.artifacts["adoption_record_path"] is None
    assert any("--apply --reason" in item for item in continued.next_actions)
    assert _sha256(source_path) == before_hash


def test_session_artifact_updated_atomically(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    session = _make_clarification_session(project_root)
    session_path = project_root / session.artifact_path
    before_payload = _read_yaml(session_path)

    continued = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": session.session_id,
            "use_suggestion": 1,
        },
    )

    after_payload = _read_yaml(project_root / continued.artifact_path)
    assert after_payload["updated_at"] != before_payload["updated_at"]
    assert after_payload["continuations"]
    assert after_payload["artifacts"]["task_spec_path"]


def test_do_continue_json_output(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    diagnosed = _make_diagnosed_session(project_root)

    proc = _run_cli(
        ["do", "--continue", "--session", diagnosed.session_id, "--json"],
        cwd=project_root,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["current_stage"] == "patch_intent_draft"
    assert payload["artifacts"]["patch_intent_path"]
    assert payload["next_actions"]


def test_status_active_session(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    ready = _make_patch_proposal_ready_session(project_root)

    status = ProjectStatusReader().read(project_root)
    proc = _run_cli(["status"], cwd=project_root)

    assert status.recent_do_session["active"] is True
    assert status.recent_do_session["stage"] == "patch_proposal_ready"
    assert "Active work:" in proc.stdout
    assert "ready to validate patch" in proc.stdout


def test_build_next_commands_are_session_bound_for_active_session(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    planner = DoContinuationPlanner()
    clarification = _make_clarification_session(project_root)
    diagnosed = _make_diagnosed_session(project_root)
    validated = _make_validated_session(project_root)

    cases = [
        ("clarification_open", clarification),
        ("diagnosed", diagnosed),
        ("patch_proposal_validated", validated),
    ]
    for stage, session in cases:
        commands = planner._build_next_commands(session, stage, {})
        continue_commands = [item for item in commands if item.startswith("cambrian do --continue")]
        assert continue_commands
        assert all(f"--session {session.session_id}" in item for item in continue_commands)


def test_status_primary_next_command_is_session_bound(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    ready = _make_patch_proposal_ready_session(project_root)

    status = ProjectStatusReader().read(project_root)
    proc = _run_cli(["status"], cwd=project_root)

    assert f"--session {ready.session_id}" in status.recent_do_session["next"]
    assert f"--session {ready.session_id}" in proc.stdout


def test_multiple_active_sessions_do_not_cross_continue_commands(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    clarification = _make_clarification_session(project_root)
    diagnosed = _make_diagnosed_session(project_root)
    planner = DoContinuationPlanner()

    clarification_commands = planner._build_next_commands(clarification, "clarification_open", {})
    diagnosed_commands = planner._build_next_commands(diagnosed, "diagnosed", {})

    assert any(f"--session {clarification.session_id}" in item for item in clarification_commands)
    assert all(f"--session {diagnosed.session_id}" not in item for item in clarification_commands)
    assert any(f"--session {diagnosed.session_id}" in item for item in diagnosed_commands)
    assert all(f"--session {clarification.session_id}" not in item for item in diagnosed_commands)


def test_recovery_hint_continue_command_uses_session_when_available(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    validated = _make_validated_session(project_root)

    proc = _run_cli(
        ["do", "--continue", "--session", validated.session_id, "--apply", "--json"],
        cwd=project_root,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["error_id"] == "apply_requires_reason"
    assert f"--session {validated.session_id}" in payload["try_next"][0]["command"]


def test_next_commands_persist_session_binding_in_artifact(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    ready = _make_patch_proposal_ready_session(project_root)
    session_payload = _read_yaml(project_root / ready.artifact_path)

    assert session_payload["next_actions"]
    assert f"--session {ready.session_id}" in session_payload["next_actions"][0]
    assert session_payload["next_commands"]
    assert f"--session {ready.session_id}" in session_payload["next_commands"][0]["command"]


def test_source_immutability_before_apply(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    source_path = project_root / "src" / "auth.py"
    before_hash = _sha256(source_path)

    session = _make_clarification_session(project_root)
    step1 = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": session.session_id,
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
        },
    )
    assert _sha256(source_path) == before_hash

    step2 = ProjectDoContinuationRunner().run(
        project_root,
        {"session": step1.session_id, "execute": True},
    )
    assert _sha256(source_path) == before_hash

    step3 = ProjectDoContinuationRunner().run(
        project_root,
        {
            "session": step2.session_id,
            "old_choice": "old-1",
            "new_text": "return username.strip().lower()",
            "propose": True,
            "validate": True,
        },
    )
    assert step3.current_stage == "patch_proposal_validated"
    assert _sha256(source_path) == before_hash
