from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_template_recommend import _copy_template_store, _prepare_template_store


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target_with_templates(tmp_path: Path) -> Path:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (project_root / "tests").mkdir()
    _copy_template_store(store_path, project_root)
    return project_root


def test_recommended_template_choice_bootstraps_and_records_choice(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(
        ["init", "--wizard", "--use-recommended-template", "--non-interactive", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "completed"
    assert payload["template_bootstrap_choice"]["selection_mode"] == "recommended"
    assert payload["template_bootstrap_choice"]["selected_template_name"] == "auth-bug-template"
    choice = _read_yaml(project_root / ".cambrian" / "templates" / "bootstrap_choice.yaml")
    record = _read_yaml(project_root / ".cambrian" / "templates" / "bootstrap_record.yaml")
    assert choice["selection_mode"] == "recommended"
    assert record["template_name"] == "auth-bug-template"
    assert record["applied_defaults"]["bootstrap_choice"]["selection_mode"] == "recommended"


def test_explicit_template_beats_recommendation(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--template", "docs-review-template", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["template_bootstrap_choice"]["selection_mode"] == "explicit"
    assert payload["template_bootstrap_choice"]["selected_template_name"] == "docs-review-template"
    current = _read_yaml(project_root / ".cambrian" / "templates" / "current_template.yaml")
    assert current["name"] == "docs-review-template"


def test_skip_template_records_skip_without_bootstrap(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--wizard", "--skip-template", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["template_bootstrap_choice"]["selection_mode"] == "skipped"
    assert payload["template_bootstrap_choice"]["selected_template_name"] is None
    choice = _read_yaml(project_root / ".cambrian" / "templates" / "bootstrap_choice.yaml")
    assert choice["selection_mode"] == "skipped"
    assert not (project_root / ".cambrian" / "templates" / "bootstrap_record.yaml").exists()
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_non_interactive_use_recommended_template(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--use-recommended-template", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "initialized"
    assert payload["template_bootstrap_choice"]["selection_mode"] == "recommended"
    assert payload["template_bootstrap"]["bootstrap_record"]["template_name"] == "auth-bug-template"


def test_non_interactive_default_does_not_auto_apply_template(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "template_bootstrap_choice" not in payload
    assert not (project_root / ".cambrian" / "templates" / "bootstrap_choice.yaml").exists()
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_initialized_project_blocks_template_selection(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "initialized"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["init", "--use-recommended-template", "--non-interactive"], cwd=project_root)

    assert proc.returncode != 0
    assert "already fitted" in proc.stderr
    assert "cambrian template diff" in proc.stderr


def test_status_and_harness_show_selection_origin(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)
    assert _run_cli(["init", "--use-recommended-template", "--non-interactive"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "selected via recommended template" in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "selected via recommended template" in harness_proc.stdout


def test_status_shows_skipped_template_choice(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)
    assert _run_cli(["init", "--skip-template", "--non-interactive"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    assert _run_cli(["harness", "fit"], cwd=project_root).returncode == 0
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template bootstrap:" in status_proc.stdout
    assert "skipped" in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Template bootstrap:" in harness_proc.stdout
    assert "skipped" in harness_proc.stdout


def test_template_bootstrap_selection_does_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["init", "--use-recommended-template", "--non-interactive"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["harness", "show"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
