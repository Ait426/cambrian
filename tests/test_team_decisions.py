from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_teams import _team, _teams_payload
from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_teams(project_root: Path, *, active_team_id: str | None = "auth-bug-team") -> None:
    _write_yaml(
        project_root / ".cambrian" / "agents" / "teams.yaml",
        _teams_payload(
            active_team_id=active_team_id,
            teams=[
                _team(
                    "auth-bug-team",
                    "auth-bug-team",
                    ["bug-fix-agent", "regression-test-agent", "review-agent"],
                    tags=["auth", "bugfix"],
                ),
                _team(
                    "safe-patch-team",
                    "safe-patch-team",
                    ["review-agent", "regression-test-agent", "bug-fix-agent"],
                    lead="review-agent",
                    support=["regression-test-agent", "bug-fix-agent"],
                    tags=["safe", "review"],
                ),
                _team(
                    "bad-team",
                    "bad-team",
                    ["missing-agent"],
                    tags=["bad"],
                ),
            ],
        ),
    )


def test_team_accept_apply_team_records_and_applies_active_team(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    trial = _run_cli(["team", "trial", "safe-patch-team", "fix login bug"], cwd=project_root)
    assert trial.returncode == 0, trial.stderr

    proc = _run_cli(["team", "accept", "safe-patch-team", "--decision", "apply_team", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["status"] == "accepted"
    assert payload["decision"]["decision_kind"] == "apply_team"
    assert payload["decision"]["operational_effect"]["applied"] is True
    decisions = _read_yaml(project_root / ".cambrian" / "agents" / "team_decisions.yaml")
    assert decisions["active_decision_team_id"] == "safe-patch-team"
    teams = _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")
    assert teams["active_team_id"] == "safe-patch-team"


def test_team_accept_keep_team_is_decision_only(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    before = _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")

    proc = _run_cli(["team", "accept", "auth-bug-team", "--decision", "keep_team", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["operational_effect"]["applied"] is False
    assert _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")["active_team_id"] == before["active_team_id"]


def test_team_accept_backup_and_watch_are_overlay_only(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    before = _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")

    backup = _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root)
    watch = _run_cli(["team", "accept", "safe-patch-team", "--decision", "watch_team"], cwd=project_root)

    assert backup.returncode == 0, backup.stderr
    assert watch.returncode == 0, watch.stderr
    decisions = _read_yaml(project_root / ".cambrian" / "agents" / "team_decisions.yaml")
    kinds = [item["decision_kind"] for item in decisions["decisions"]]
    assert "keep_as_backup" in kinds
    assert "watch_team" in kinds
    assert _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")["active_team_id"] == before["active_team_id"]


def test_team_dismiss_records_no_operational_effect(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)

    proc = _run_cli(["team", "dismiss", "safe-patch-team", "--resolution", "not needed yet", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["status"] == "dismissed"
    assert payload["decision"]["decision_kind"] == "dismiss_team"
    assert payload["decision"]["resolution"] == "not needed yet"
    assert payload["decision"]["operational_effect"]["applied"] is False


def test_team_accept_apply_team_blocked_if_team_invalid(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    before = _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")

    proc = _run_cli(["team", "accept", "bad-team", "--decision", "apply_team"], cwd=project_root)

    assert proc.returncode != 0
    assert "missing team member agent" in proc.stderr
    assert not (project_root / ".cambrian" / "agents" / "team_decisions.yaml").exists()
    assert _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")["active_team_id"] == before["active_team_id"]


def test_team_decisions_list_and_filter(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "keep_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "dismiss", "safe-patch-team"], cwd=project_root).returncode == 0

    list_proc = _run_cli(["team", "decisions"], cwd=project_root)
    filter_proc = _run_cli(["team", "decisions", "--status", "dismissed", "--json"], cwd=project_root)

    assert list_proc.returncode == 0, list_proc.stderr
    assert "Team Decisions" in list_proc.stdout
    assert "keep_team auth-bug-team" in list_proc.stdout
    payload = json.loads(filter_proc.stdout)
    assert len(payload["decisions"]) == 1
    assert payload["decisions"][0]["status"] == "dismissed"


def test_status_and_team_show_include_team_decision_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    show_proc = _run_cli(["team", "show", "safe-patch-team"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Team decisions:" in status_proc.stdout
    assert "Accepted team hints:" in status_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Decisions:" in show_proc.stdout
    assert "accepted keep_as_backup" in show_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Team Decisions" in harness_proc.stdout


def test_team_decision_is_reflected_in_recommend_and_do_hint(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root).returncode == 0

    recommend_proc = _run_cli(["team", "recommend", "fix login bug", "--json"], cwd=project_root)
    do_proc = _run_cli(["do", "fix login bug"], cwd=project_root)

    assert recommend_proc.returncode == 0, recommend_proc.stderr
    payload = json.loads(recommend_proc.stdout)
    reasons = "\n".join(reason for item in payload["recommendations"] for reason in item.get("reasons", []))
    assert "previously accepted as a backup team" in reasons
    assert do_proc.returncode == 0, do_proc.stderr
    assert "Backup team:" in do_proc.stdout
    assert "safe-patch-team" in do_proc.stdout


def test_team_decisions_do_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before_source = _sha256(source_path)

    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "keep_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "dismiss", "safe-patch-team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "decisions"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "show", "auth-bug-team"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before_source
