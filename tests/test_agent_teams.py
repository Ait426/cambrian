from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import (
    _make_importable_passport,
    _prepare_target_project,
    _read_yaml,
    _run_cli,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _import_agent(project_root: Path, tmp_path: Path, *, agent_id: str, requires_test: bool = False) -> None:
    passport_path = _make_importable_passport(
        tmp_path / f"{agent_id}.passport.yaml",
        agent_id=agent_id,
        role_id="bug_fix",
        requires_test=requires_test,
    )
    proc = _run_cli(["agent", "import", str(passport_path)], cwd=project_root)
    assert proc.returncode == 0, proc.stderr


def _teams_payload(*, active_team_id: str | None = None, teams: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "updated_at": "2026-04-25T00:00:00+00:00",
        "active_team_id": active_team_id,
        "warnings": [],
        "errors": [],
        "teams": teams,
    }


def _team(
    team_id: str,
    name: str,
    members: list[str],
    *,
    lead: str | None = None,
    support: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "team_id": team_id,
        "name": name,
        "created_at": "2026-04-25T00:00:00+00:00",
        "updated_at": None,
        "description": None,
        "project_name": "target",
        "harness_id": "harness-target",
        "lead_agent_id": lead or members[0],
        "supporting_agent_ids": support if support is not None else members[1:],
        "members": members,
        "tags": tags or [],
        "source_decision_refs": [],
        "source_dispatch_refs": [],
        "fit_hints": ["default team for bug_fix"],
        "warnings": [],
        "errors": [],
    }


def test_team_save_from_current_active_agents(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)

    proc = _run_cli(["team", "save", "auth-bug-team", "--description", "Auth bug team", "--tag", "auth", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["team"]["name"] == "auth-bug-team"
    assert payload["team"]["members"]
    teams_path = project_root / ".cambrian" / "agents" / "teams.yaml"
    assert teams_path.exists()
    teams = _read_yaml(teams_path)
    assert teams["active_team_id"] == "auth-bug-team"


def test_team_save_blocked_with_no_active_agents(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    profile_path = project_root / ".cambrian" / "harness" / "profile.yaml"
    profile = _read_yaml(profile_path)
    profile["active_agents"] = []
    _write_yaml(profile_path, profile)

    proc = _run_cli(["team", "save", "empty-team"], cwd=project_root)

    assert proc.returncode != 0
    assert "no active agents" in proc.stderr


def test_team_list_and_show(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    assert _run_cli(["team", "save", "auth-bug-team"], cwd=project_root).returncode == 0

    list_proc = _run_cli(["team", "list"], cwd=project_root)
    show_proc = _run_cli(["team", "show", "auth-bug-team"], cwd=project_root)

    assert list_proc.returncode == 0, list_proc.stderr
    assert "Teams" in list_proc.stdout
    assert "auth-bug-team" in list_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Team Preset" in show_proc.stdout
    assert "Composition:" in show_proc.stdout


def test_team_apply_updates_active_agents_and_active_team(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_yaml(
        project_root / ".cambrian" / "agents" / "teams.yaml",
        _teams_payload(
            teams=[
                _team(
                    "review-team",
                    "review-team",
                    ["review-agent", "regression-test-agent"],
                    lead="review-agent",
                    support=["regression-test-agent"],
                )
            ]
        ),
    )

    proc = _run_cli(["team", "apply", "review-team", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["active_team_id"] == "review-team"
    profile = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")
    assert profile["active_agents"] == ["review-agent", "regression-test-agent"]
    teams = _read_yaml(project_root / ".cambrian" / "agents" / "teams.yaml")
    assert teams["active_team_id"] == "review-team"


def test_team_apply_blocked_on_missing_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_yaml(
        project_root / ".cambrian" / "agents" / "teams.yaml",
        _teams_payload(teams=[_team("bad-team", "bad-team", ["missing-agent"])]),
    )

    proc = _run_cli(["team", "apply", "bad-team"], cwd=project_root)

    assert proc.returncode != 0
    assert "missing agent" in proc.stderr


def test_team_apply_blocked_on_imported_blocked_member(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root, with_tests=False)
    _import_agent(project_root, tmp_path, agent_id="portable-blocked-agent", requires_test=True)
    _write_yaml(
        project_root / ".cambrian" / "agents" / "teams.yaml",
        _teams_payload(teams=[_team("blocked-team", "blocked-team", ["portable-blocked-agent"])]),
    )

    proc = _run_cli(["team", "apply", "blocked-team"], cwd=project_root)

    assert proc.returncode != 0
    assert "blocked" in proc.stderr


def test_team_recommend_best_team_for_request_and_active_bias(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_yaml(
        project_root / ".cambrian" / "agents" / "teams.yaml",
        _teams_payload(
            active_team_id="auth-bug-team",
            teams=[
                _team("auth-bug-team", "auth-bug-team", ["bug-fix-agent", "regression-test-agent", "review-agent"], tags=["auth", "bugfix"]),
                _team("docs-team", "docs-team", ["docs-update-agent"], tags=["docs"]),
            ],
        ),
    )

    proc = _run_cli(["team", "recommend", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["best_team"]["name"] == "auth-bug-team"
    assert payload["best_team"]["reasons"]
    assert any("currently active" in reason for reason in payload["best_team"]["reasons"])


def test_status_shows_active_team_and_do_output_team_hint(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    assert _run_cli(["team", "save", "auth-bug-team"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    do_proc = _run_cli(["do", "fix login bug"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Harness team:" in status_proc.stdout
    assert "auth-bug-team" in status_proc.stdout
    assert do_proc.returncode == 0, do_proc.stderr
    assert "Team hint:" in do_proc.stdout
    assert "auth-bug-team" in do_proc.stdout


def test_team_commands_do_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["team", "save", "auth-bug-team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "list"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "show", "auth-bug-team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "recommend", "fix login bug"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["do", "fix login bug"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
