from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from engine.project_team_policy import build_and_save_team_policy_overlay
from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_team_decisions import _write_teams


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _latest_yaml(directory: Path) -> Path:
    candidates = sorted(directory.glob("*.yaml"), key=lambda path: path.stat().st_mtime, reverse=True)
    assert candidates
    return candidates[0]


def test_build_overlay_from_accepted_team_decisions(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "apply_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "watch_team"], cwd=project_root).returncode == 0

    overlay, path = build_and_save_team_policy_overlay(project_root)

    assert path.exists()
    assert overlay.current_team_id == "auth-bug-team"
    assert "safe-patch-team" in overlay.backup_teams
    assert "safe-patch-team" in overlay.watched_teams
    assert len(overlay.accepted_decisions) == 3


def test_dismissed_team_decisions_are_ignored(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "dismiss", "safe-patch-team"], cwd=project_root).returncode == 0

    overlay, _path = build_and_save_team_policy_overlay(project_root)

    assert overlay.current_team_id is None
    assert overlay.backup_teams == []
    assert overlay.watched_teams == []
    assert overlay.accepted_decisions == []


def test_do_output_and_artifacts_include_team_policy_context(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "apply_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root).returncode == 0

    proc = _run_cli(["do", "fix login bug"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "Accepted team policy:" in proc.stdout
    assert "auth-bug-team is the accepted current team" in proc.stdout
    request_payload = _read_yaml(_latest_yaml(project_root / ".cambrian" / "requests"))
    session_payload = _read_yaml(_latest_yaml(project_root / ".cambrian" / "sessions"))
    assert request_payload["team_policy_context"]["current_team_id"] == "auth-bug-team"
    assert "safe-patch-team" in request_payload["team_policy_context"]["backup_teams"]
    assert session_payload["team_policy_context"]["current_team_id"] == "auth-bug-team"
    assert (project_root / ".cambrian" / "agents" / "team_policy_overlay.yaml").exists()


def test_continue_carries_team_policy_context(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "apply_team"], cwd=project_root).returncode == 0
    do_proc = _run_cli(["do", "fix login bug"], cwd=project_root)
    assert do_proc.returncode == 0, do_proc.stderr
    session_payload = _read_yaml(_latest_yaml(project_root / ".cambrian" / "sessions"))

    continue_proc = _run_cli(["do", "--continue", "--session", session_payload["session_id"]], cwd=project_root)

    assert continue_proc.returncode == 0, continue_proc.stderr
    assert "Accepted team policy still in effect:" in continue_proc.stdout
    continued_payload = _read_yaml(project_root / ".cambrian" / "sessions" / f"do_session_{session_payload['session_id']}.yaml")
    assert continued_payload["team_policy_context"]["current_team_id"] == "auth-bug-team"


def test_status_team_show_and_harness_show_include_policy(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "apply_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    show_proc = _run_cli(["team", "show", "safe-patch-team"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Team policy:" in status_proc.stdout
    assert "current : auth-bug-team" in status_proc.stdout
    assert "backup  : safe-patch-team" in status_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Policy role:" in show_proc.stdout
    assert "backup team" in show_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Accepted team policy:" in harness_proc.stdout
    assert "safe-patch-team" in harness_proc.stdout


def test_team_recommend_uses_policy_lightly(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "apply_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root).returncode == 0

    proc = _run_cli(["team", "recommend", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    reasons = "\n".join(reason for item in payload["recommendations"] for reason in item.get("reasons", []))
    assert "accepted team policy marks this as the current team" in reasons
    assert "accepted team policy keeps this as backup" in reasons


def test_team_policy_does_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "apply_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "watch_team"], cwd=project_root).returncode == 0

    assert _run_cli(["do", "fix login bug"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "show", "safe-patch-team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "recommend", "fix login bug"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
