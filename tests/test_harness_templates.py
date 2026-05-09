from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_team_decisions import _write_teams


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_template_source(project_root: Path) -> None:
    _prepare_target_project(project_root)
    _write_teams(project_root)
    assert _run_cli(["team", "accept", "auth-bug-team", "--decision", "apply_team"], cwd=project_root).returncode == 0
    assert _run_cli(["team", "accept", "safe-patch-team", "--decision", "keep_as_backup"], cwd=project_root).returncode == 0


def _approve_template_for_apply(project_root: Path, template_name: str) -> None:
    assert _run_cli(["template", "recommend", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "diff", template_name, "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "review", template_name, "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "accept", template_name], cwd=project_root).returncode == 0


def test_template_save_from_current_project(tmp_path: Path) -> None:
    project_root = tmp_path / "source"
    _prepare_template_source(project_root)

    proc = _run_cli(
        ["template", "save", "auth-bug-template", "--description", "Auth bug operating setup", "--tag", "auth", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["template"]["name"] == "auth-bug-template"
    assert payload["template"]["template_kind"] == "team_based"
    assert payload["template"]["team_defaults"]["active_team_id"] == "auth-bug-team"
    assert payload["template"]["policy_defaults"]
    assert (project_root / ".cambrian" / "templates" / "templates.yaml").exists()


def test_template_list_and_show(tmp_path: Path) -> None:
    project_root = tmp_path / "source"
    _prepare_template_source(project_root)
    assert _run_cli(["template", "save", "auth-bug-template"], cwd=project_root).returncode == 0

    list_proc = _run_cli(["template", "list"], cwd=project_root)
    show_proc = _run_cli(["template", "show", "auth-bug-template"], cwd=project_root)

    assert list_proc.returncode == 0, list_proc.stderr
    assert "Harness Templates" in list_proc.stdout
    assert "auth-bug-template" in list_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Harness Template" in show_proc.stdout
    assert "Team defaults:" in show_proc.stdout


def test_template_apply_safe_across_projects(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    _prepare_template_source(source_root)
    assert _run_cli(["template", "save", "auth-bug-template"], cwd=source_root).returncode == 0
    _prepare_target_project(target_root)
    target_templates = target_root / ".cambrian" / "templates" / "templates.yaml"
    target_templates.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_root / ".cambrian" / "templates" / "templates.yaml", target_templates)
    source_path = target_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)
    _approve_template_for_apply(target_root, "auth-bug-template")

    proc = _run_cli(["template", "apply", "auth-bug-template", "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "applied"
    assert (target_root / ".cambrian" / "templates" / "current_template.yaml").exists()
    harness = _read_yaml(target_root / ".cambrian" / "harness" / "profile.yaml")
    assert harness["active_agents"]
    teams = _read_yaml(target_root / ".cambrian" / "agents" / "teams.yaml")
    assert teams["active_team_id"] == "auth-bug-team"
    assert _sha256(source_path) == before


def test_template_apply_blocks_dangerous_origin_overwrite_without_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_template_source(project_root)
    assert _run_cli(["template", "save", "first-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "save", "second-template"], cwd=project_root).returncode == 0
    _approve_template_for_apply(project_root, "first-template")
    assert _run_cli(["template", "apply", "first-template"], cwd=project_root).returncode == 0
    _approve_template_for_apply(project_root, "second-template")

    proc = _run_cli(["template", "apply", "second-template"], cwd=project_root)

    assert proc.returncode != 0
    assert "Template Apply Guardrails" in proc.stdout
    current = _read_yaml(project_root / ".cambrian" / "templates" / "current_template.yaml")
    assert current["name"] == "first-template"


def test_template_apply_with_force_replaces_origin(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_template_source(project_root)
    assert _run_cli(["template", "save", "first-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "save", "second-template"], cwd=project_root).returncode == 0
    _approve_template_for_apply(project_root, "first-template")
    assert _run_cli(["template", "apply", "first-template"], cwd=project_root).returncode == 0
    _approve_template_for_apply(project_root, "second-template")

    proc = _run_cli(["template", "apply", "second-template", "--force", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    current = _read_yaml(project_root / ".cambrian" / "templates" / "current_template.yaml")
    assert current["name"] == "second-template"


def test_template_excludes_live_state(tmp_path: Path) -> None:
    project_root = tmp_path / "source"
    _prepare_template_source(project_root)
    _write_yaml(project_root / ".cambrian" / "notes" / "note_live.yaml", {"text": "do not copy this note"})
    _write_yaml(project_root / ".cambrian" / "sessions" / "do_session_live.yaml", {"user_request": "do not copy this session"})
    _write_yaml(project_root / ".cambrian" / "memory" / "lessons.yaml", {"lessons": [{"text": "do not copy this lesson"}]})

    proc = _run_cli(["template", "save", "safe-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    dumped = yaml.safe_dump(json.loads(proc.stdout)["template"], allow_unicode=True, sort_keys=False)
    assert "do not copy this note" not in dumped
    assert "do not copy this session" not in dumped
    assert "do not copy this lesson" not in dumped


def test_status_harness_show_and_do_include_template_origin(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_template_source(project_root)
    assert _run_cli(["template", "save", "auth-bug-template"], cwd=project_root).returncode == 0
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)
    do_proc = _run_cli(["do", "fix login bug"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Harness template:" in status_proc.stdout
    assert "auth-bug-template" in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Harness template:" in harness_proc.stdout
    assert do_proc.returncode == 0, do_proc.stderr
    assert "Harness template:" in do_proc.stdout
    request_payload = _read_yaml(sorted((project_root / ".cambrian" / "requests").glob("*.yaml"))[-1])
    assert request_payload["template_context"]["name"] == "auth-bug-template"


def test_template_commands_do_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_template_source(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["template", "save", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "list"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "show", "auth-bug-template"], cwd=project_root).returncode == 0
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["do", "fix login bug"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
