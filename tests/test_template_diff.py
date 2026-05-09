from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_harness_templates import _approve_template_for_apply, _write_yaml
from test_template_recommend import _prepare_template_store


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_template_store(source_store: Path, target_root: Path) -> None:
    target_store = target_root / ".cambrian" / "templates" / "templates.yaml"
    target_store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_store, target_store)


def test_diff_with_no_current_template(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "diff", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "no_current_template"
    assert payload["target_template_name"] == "auth-bug-template"
    assert payload["summary"]["total_entries"] > 0
    assert payload["summary"]["missing_in_project_count"] + payload["summary"]["changed_count"] > 0
    assert payload["safe_to_apply"] is True


def test_diff_with_current_template_already_applied(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "diff", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "compare_current"
    assert payload["current_template_name"] == "auth-bug-template"
    assert payload["summary"]["same_count"] >= 5
    assert payload["safe_to_apply"] is True


def test_diff_between_different_templates(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "diff", "docs-review-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "compare_candidate"
    assert payload["target_template_name"] == "docs-review-template"
    assert payload["summary"]["changed_count"] > 0


def test_list_field_diff_for_agents_and_teams(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "diff", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    entries = json.loads(proc.stdout)["entries"]
    active_agents = next(entry for entry in entries if entry["section"] == "agent_defaults" and entry["key"] == "active_agents")
    backup_teams = next(entry for entry in entries if entry["section"] == "team_defaults" and entry["key"] == "backup_teams")
    assert active_agents["status"] in {"same", "changed", "missing_in_project"}
    assert backup_teams["status"] in {"changed", "missing_in_project"}


def test_live_state_excluded_from_diff(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)
    _write_yaml(project_root / ".cambrian" / "notes" / "note_live.yaml", {"text": "do not diff this note"})
    _write_yaml(project_root / ".cambrian" / "sessions" / "session_live.yaml", {"request": "do not diff this session"})
    _write_yaml(project_root / ".cambrian" / "memory" / "lessons.yaml", {"lessons": [{"text": "do not diff this lesson"}]})

    proc = _run_cli(["template", "diff", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    dumped = yaml.safe_dump(json.loads(proc.stdout), allow_unicode=True, sort_keys=False)
    assert "do not diff this note" not in dumped
    assert "do not diff this session" not in dumped
    assert "do not diff this lesson" not in dumped


def test_save_diff_report(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "diff", "auth-bug-template", "--save", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    report_path = project_root / payload["saved_path"]
    assert report_path.exists()
    report = _read_yaml(report_path)
    assert report["target_template_name"] == "auth-bug-template"


def test_status_hint_points_to_template_diff(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["status"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "Template hint:" in proc.stdout
    assert "cambrian template diff auth-bug-template" in proc.stdout


def test_template_recommend_suggests_diff_before_apply(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "recommend"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "cambrian template diff auth-bug-template" in proc.stdout
    assert proc.stdout.index("cambrian template diff auth-bug-template") < proc.stdout.index("cambrian template apply auth-bug-template")


def test_template_diff_does_not_mutate_project_source(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["template", "diff", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
    assert not (project_root / ".cambrian" / "templates" / "diff_report.yaml").exists()
