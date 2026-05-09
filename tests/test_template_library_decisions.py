from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from test_agent_transfer import _read_yaml, _run_cli
from test_harness_templates import _prepare_template_source, _write_yaml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duplicate_template(project_root: Path, source_name: str, target_name: str, **updates: object) -> None:
    store_path = project_root / ".cambrian" / "templates" / "templates.yaml"
    payload = _read_yaml(store_path)
    source = next(item for item in payload["templates"] if item["name"] == source_name)
    duplicate = copy.deepcopy(source)
    duplicate["name"] = target_name
    duplicate["template_id"] = target_name
    duplicate["description"] = str(updates.pop("description", target_name))
    for key, value in updates.items():
        duplicate[key] = value
    payload["templates"].append(duplicate)
    _write_yaml(store_path, payload)


def _prepare_library_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    _prepare_template_source(project_root)
    assert _run_cli(["template", "save", "auth-bug-template", "--tag", "auth"], cwd=project_root).returncode == 0
    _duplicate_template(project_root, "auth-bug-template", "safe-patch-template", tags=["safe", "patch"])
    _duplicate_template(
        project_root,
        "auth-bug-template",
        "legacy-general-template",
        tags=["legacy"],
        project_defaults={
            "project_type": "docs",
            "stack": ["markdown"],
            "test_command": None,
            "mode": "balanced",
            "primary_use_cases": ["docs_update"],
        },
    )
    return project_root


def _decision_payload(project_root: Path, command: str, name: str) -> dict:
    proc = _run_cli(["template", command, name, "--json"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_promote_decision_saved_and_standing_visible(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)

    payload = _decision_payload(project_root, "promote", "auth-bug-template")

    assert payload["decision"]["decision_kind"] == "promote"
    assert (project_root / ".cambrian" / "templates" / "library_decisions.yaml").exists()
    show_proc = _run_cli(["template", "show", "auth-bug-template"], cwd=project_root)
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Library standing:" in show_proc.stdout
    assert "promote" in show_proc.stdout


def test_keep_decision_saved(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)

    payload = _decision_payload(project_root, "keep", "auth-bug-template")

    assert payload["decision"]["decision_kind"] == "keep"
    summary = _run_cli(["template", "library-decisions", "--json"], cwd=project_root)
    assert summary.returncode == 0, summary.stderr
    assert json.loads(summary.stdout)["decisions"][0]["decision_kind"] == "keep"


def test_backup_decision_saved(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)

    payload = _decision_payload(project_root, "backup", "safe-patch-template")

    assert payload["decision"]["decision_kind"] == "backup"
    list_proc = _run_cli(["template", "library-decisions"], cwd=project_root)
    assert list_proc.returncode == 0, list_proc.stderr
    assert "Backup:" in list_proc.stdout
    assert "safe-patch-template" in list_proc.stdout


def test_watch_decision_saved(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)

    payload = _decision_payload(project_root, "watch", "safe-patch-template")

    assert payload["decision"]["decision_kind"] == "watch"
    board = _run_cli(["template", "board", "--json"], cwd=project_root)
    assert board.returncode == 0, board.stderr
    assert "safe-patch-template" in json.loads(board.stdout)["watch_templates"]


def test_retire_decision_saved(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)

    payload = _decision_payload(project_root, "retire", "legacy-general-template")

    assert payload["decision"]["decision_kind"] == "retire"
    board = _run_cli(["template", "board", "--json"], cwd=project_root)
    assert board.returncode == 0, board.stderr
    assert "legacy-general-template" in json.loads(board.stdout)["retire_candidates"]


def test_latest_library_decision_wins(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "auth-bug-template"], cwd=project_root).returncode == 0

    show_proc = _run_cli(["template", "show", "auth-bug-template"], cwd=project_root)
    board_proc = _run_cli(["template", "board", "--json"], cwd=project_root)

    assert show_proc.returncode == 0, show_proc.stderr
    assert "retire" in show_proc.stdout
    assert board_proc.returncode == 0, board_proc.stderr
    assert "auth-bug-template" in json.loads(board_proc.stdout)["retire_candidates"]


def test_board_uses_promote_and_retire_overlay(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "retire", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "promote", "safe-patch-template"], cwd=project_root).returncode == 0

    payload = json.loads(_run_cli(["template", "board", "--json"], cwd=project_root).stdout)

    assert "safe-patch-template" in payload["preferred_templates"]
    assert "auth-bug-template" in payload["retire_candidates"]
    safe = next(item for item in payload["entries"] if item["template_name"] == "safe-patch-template")
    auth = next(item for item in payload["entries"] if item["template_name"] == "auth-bug-template")
    assert "previously promoted in local library" in safe["reasons"]
    assert "retired in local library" in auth["warnings"]


def test_recommend_uses_library_standing_weakly(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "promote", "safe-patch-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    safe = next(item for item in payload["candidates"] if item["name"] == "safe-patch-template")
    auth = next(item for item in payload["candidates"] if item["name"] == "auth-bug-template")
    assert "previously promoted in local template library" in safe["reasons"]
    assert "template is retired in local library" in auth["warnings"]


def test_status_shows_template_library_decision_summary(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "backup", "safe-patch-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "legacy-general-template"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template library decisions:" in status_proc.stdout
    assert "auth-bug-template" in status_proc.stdout
    assert "safe-patch-template" in status_proc.stdout
    assert "legacy-general-template" in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Template library decisions:" in harness_proc.stdout


def test_template_library_decisions_do_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    source_path = project_root / "src" / "auth.py"
    before = _sha256(source_path)

    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "backup", "safe-patch-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "legacy-general-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "board"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "show", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
