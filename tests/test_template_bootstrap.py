from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_harness_templates import _prepare_template_source, _write_yaml
from test_template_recommend import _copy_template_store, _prepare_template_store


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bootstrap_target_with_store(tmp_path: Path) -> tuple[Path, Path]:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (project_root / "tests").mkdir()
    _copy_template_store(store_path, project_root)
    return project_root, store_path


def test_init_with_template_wizard_bootstraps_defaults(tmp_path: Path) -> None:
    project_root, _store_path = _bootstrap_target_with_store(tmp_path)

    proc = _run_cli(
        ["init", "--wizard", "--template", "auth-bug-template", "--non-interactive", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "completed"
    assert payload["template_bootstrap"]["status"] == "bootstrapped"
    project = _read_yaml(project_root / ".cambrian" / "project.yaml")
    assert project["project"]["type"] == "python"
    assert "python" in project["project"]["stack"]
    assert project["test"]["command"] == "pytest -q"
    harness = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")
    assert harness["primary_use_cases"]
    assert harness["active_agents"]


def test_init_with_template_non_interactive_bootstraps_defaults(tmp_path: Path) -> None:
    project_root, _store_path = _bootstrap_target_with_store(tmp_path)

    proc = _run_cli(["init", "--template", "auth-bug-template", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "initialized"
    assert payload["template_bootstrap"]["bootstrap_record"]["template_name"] == "auth-bug-template"
    assert (project_root / ".cambrian" / "templates" / "bootstrap_record.yaml").exists()
    assert (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_explicit_input_overrides_template_defaults(tmp_path: Path) -> None:
    project_root, _store_path = _bootstrap_target_with_store(tmp_path)

    proc = _run_cli(
        [
            "init",
            "--template",
            "auth-bug-template",
            "--non-interactive",
            "--type",
            "generic",
            "--test-cmd",
            "python -m pytest custom",
        ],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    project = _read_yaml(project_root / ".cambrian" / "project.yaml")
    assert project["project"]["type"] == "generic"
    assert project["test"]["command"] == "python -m pytest custom"


def test_bootstrap_provenance_saved(tmp_path: Path) -> None:
    project_root, _store_path = _bootstrap_target_with_store(tmp_path)
    assert _run_cli(["init", "--template", "auth-bug-template", "--non-interactive"], cwd=project_root).returncode == 0

    record = _read_yaml(project_root / ".cambrian" / "templates" / "bootstrap_record.yaml")
    current = _read_yaml(project_root / ".cambrian" / "templates" / "current_template.yaml")

    assert record["template_name"] == "auth-bug-template"
    assert record["applied_defaults"]["project_defaults"]
    assert current["name"] == "auth-bug-template"
    assert current["origin"] == "bootstrap"


def test_initialized_project_blocks_init_template(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "initialized"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["init", "--template", "auth-bug-template", "--non-interactive"], cwd=project_root)

    assert proc.returncode != 0
    assert "already fitted" in proc.stderr
    assert "cambrian template diff auth-bug-template" in proc.stderr


def test_template_bootstrap_does_not_copy_live_state(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _prepare_template_source(source_root)
    _write_yaml(source_root / ".cambrian" / "notes" / "note_live.yaml", {"text": "do not copy this note"})
    _write_yaml(source_root / ".cambrian" / "sessions" / "session_live.yaml", {"text": "do not copy this session"})
    _write_yaml(source_root / ".cambrian" / "memory" / "lessons.yaml", {"lessons": [{"text": "do not copy this lesson"}]})
    assert _run_cli(["template", "save", "auth-bug-template"], cwd=source_root).returncode == 0

    project_root = tmp_path / "target"
    project_root.mkdir()
    _copy_template_store(source_root / ".cambrian" / "templates" / "templates.yaml", project_root)
    assert _run_cli(["init", "--template", "auth-bug-template", "--non-interactive"], cwd=project_root).returncode == 0

    dumped = yaml.safe_dump(
        {
            "project": _read_yaml(project_root / ".cambrian" / "project.yaml"),
            "harness": _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml"),
            "bootstrap": _read_yaml(project_root / ".cambrian" / "templates" / "bootstrap_record.yaml"),
        },
        allow_unicode=True,
        sort_keys=False,
    )
    assert "do not copy this note" not in dumped
    assert "do not copy this session" not in dumped
    assert "do not copy this lesson" not in dumped


def test_status_and_harness_show_bootstrap_origin(tmp_path: Path) -> None:
    project_root, _store_path = _bootstrap_target_with_store(tmp_path)
    assert _run_cli(["init", "--template", "auth-bug-template", "--non-interactive"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)
    summary_proc = _run_cli(["summary"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template origin:" in status_proc.stdout
    assert "auth-bug-template (bootstrap)" in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Template origin:" in harness_proc.stdout
    assert "auth-bug-template (bootstrap)" in harness_proc.stdout
    assert summary_proc.returncode == 0, summary_proc.stderr
    assert "Template:" in summary_proc.stdout
    assert "bootstrap: auth-bug-template" in summary_proc.stdout


def test_template_recommend_next_action_for_uninitialized_project(tmp_path: Path) -> None:
    project_root, _store_path = _bootstrap_target_with_store(tmp_path)

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["best_template_name"] == "auth-bug-template"
    assert "cambrian init --wizard --template auth-bug-template" in payload["next_actions"]


def test_template_bootstrap_does_not_mutate_project_source(tmp_path: Path) -> None:
    project_root, _store_path = _bootstrap_target_with_store(tmp_path)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["init", "--template", "auth-bug-template", "--non-interactive"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["harness", "show"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
