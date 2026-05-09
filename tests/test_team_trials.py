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
                    "docs-team",
                    "docs-team",
                    ["docs-update-agent"],
                    tags=["docs"],
                ),
            ],
        ),
    )


def test_team_trial_against_current_active_team(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)

    proc = _run_cli(["team", "trial", "safe-patch-team", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "completed"
    assert payload["current_team_id"] == "auth-bug-team"
    assert payload["shadow_team_id"] == "safe-patch-team"
    assert payload["comparison"]["result"] in {"current_stronger", "shadow_stronger", "comparable", "inconclusive"}
    assert list((project_root / ".cambrian" / "agents" / "team_trials").glob("team_trial_*.yaml"))


def test_team_trial_without_current_active_team(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root, active_team_id=None)

    proc = _run_cli(["team", "trial", "safe-patch-team", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["current_team_id"] is None
    assert payload["comparison"]["result"] == "shadow_stronger"


def test_team_trial_shadow_team_not_found_is_blocked(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)

    proc = _run_cli(["team", "trial", "missing-team", "fix login bug"], cwd=project_root)

    assert proc.returncode != 0
    assert "Team trial blocked" in proc.stderr
    assert "team not found" in proc.stderr


def test_team_trial_show_by_path(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    proc = _run_cli(["team", "trial", "safe-patch-team", "fix login bug", "--json"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    trial_path = sorted((project_root / ".cambrian" / "agents" / "team_trials").glob("team_trial_*.yaml"))[-1]

    show_proc = _run_cli(["team", "trial-show", str(trial_path), "--json"], cwd=project_root)

    assert show_proc.returncode == 0, show_proc.stderr
    payload = json.loads(show_proc.stdout)
    assert payload["shadow_team_id"] == "safe-patch-team"
    assert payload["steps"]
    assert payload["comparison"]["reasons"]
    id_proc = _run_cli(["team", "trial-show", payload["trial_id"], "--json"], cwd=project_root)
    assert id_proc.returncode == 0, id_proc.stderr


def test_team_recommend_uses_recent_trial_hint(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "trial", "safe-patch-team", "fix login bug"], cwd=project_root).returncode == 0

    proc = _run_cli(["team", "recommend", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    flattened_reasons = "\n".join(
        reason
        for item in payload["recommendations"]
        for reason in item.get("reasons", [])
    )
    assert "recent team trial result" in flattened_reasons


def test_status_shows_recent_team_trial(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "trial", "safe-patch-team", "fix login bug"], cwd=project_root).returncode == 0

    proc = _run_cli(["status"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "Recent team trial:" in proc.stdout
    assert "safe-patch-team" in proc.stdout


def test_current_team_stronger_case(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root, active_team_id="auth-bug-team")

    proc = _run_cli(["team", "trial", "docs-team", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["comparison"]["result"] == "current_stronger"


def test_shadow_team_stronger_case(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root, active_team_id="docs-team")

    proc = _run_cli(["team", "trial", "auth-bug-team", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["comparison"]["result"] == "shadow_stronger"


def test_team_trial_does_not_mutate_source_or_active_team(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_teams(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before_source = _sha256(source_path)
    before_profile = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")
    before_teams = _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")

    proc = _run_cli(["team", "trial", "safe-patch-team", "fix login bug"], cwd=project_root)
    show_proc = _run_cli(["team", "trial-show", "safe-patch-team"], cwd=project_root)
    status_proc = _run_cli(["status"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert show_proc.returncode == 0, show_proc.stderr
    assert status_proc.returncode == 0, status_proc.stderr
    assert _sha256(source_path) == before_source
    assert _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")["active_agents"] == before_profile["active_agents"]
    assert _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")["active_team_id"] == before_teams["active_team_id"]
