from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_harness_templates import _approve_template_for_apply, _prepare_template_source, _write_yaml
from test_template_recommend import _copy_template_store


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_saved_template(project_root: Path, name: str = "auth-bug-template") -> None:
    _prepare_template_source(project_root)
    assert _run_cli(["template", "save", name, "--tag", "auth"], cwd=project_root).returncode == 0


def _duplicate_template(project_root: Path, source_name: str, target_name: str) -> None:
    store_path = project_root / ".cambrian" / "templates" / "templates.yaml"
    payload = _read_yaml(store_path)
    source = next(item for item in payload["templates"] if item["name"] == source_name)
    duplicate = copy.deepcopy(source)
    duplicate["name"] = target_name
    duplicate["template_id"] = target_name
    payload["templates"].append(duplicate)
    _write_yaml(store_path, payload)


def test_build_template_passport_history_counts_usage_events(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_saved_template(project_root)
    assert _run_cli(["template", "recommend", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "diff", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "review", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "history", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["totals"]["recommended"] >= 1
    assert payload["totals"]["diffed"] == 1
    assert payload["totals"]["reviewed"] == 1
    assert payload["totals"]["accepted"] == 1
    assert payload["totals"]["applied"] == 1
    assert (project_root / ".cambrian" / "templates" / "passports" / "auth-bug-template.yaml").exists()


def test_history_counts_imported_exported_and_bootstrapped_events(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _prepare_saved_template(source_root)
    assert _run_cli(["template", "export", "auth-bug-template"], cwd=source_root).returncode == 0

    export_path = next((source_root / ".cambrian" / "templates" / "exports").glob("auth-bug-template_*.yaml"))
    source_history = _run_cli(["template", "history", "auth-bug-template", "--json"], cwd=source_root)
    assert source_history.returncode == 0, source_history.stderr
    assert json.loads(source_history.stdout)["totals"]["exported"] == 1

    target_root = tmp_path / "target"
    target_root.mkdir(parents=True)
    assert _run_cli(["template", "import", str(export_path)], cwd=target_root).returncode == 0
    assert _run_cli(["init", "--template", "auth-bug-template", "--non-interactive"], cwd=target_root).returncode == 0

    target_history = _run_cli(["template", "history", "auth-bug-template", "--json"], cwd=target_root)

    assert target_history.returncode == 0, target_history.stderr
    payload = json.loads(target_history.stdout)
    assert payload["totals"]["imported"] == 1
    assert payload["totals"]["bootstrapped"] == 1


def test_template_retrospective_add_and_list(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_saved_template(project_root)

    proc = _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template",
            "Good fit for auth/login work, but too heavy for docs.",
            "--rating",
            "good",
            "--kind",
            "fit",
            "--tag",
            "auth",
            "--json",
        ],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["rating"] == "good"
    saved_path = project_root / payload["saved_path"]
    assert saved_path.exists()
    list_proc = _run_cli(["template", "retrospectives", "auth-bug-template"], cwd=project_root)
    assert list_proc.returncode == 0, list_proc.stderr
    assert "Good fit for auth/login work" in list_proc.stdout


def test_history_includes_retrospective_cautions(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_saved_template(project_root)
    assert _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template",
            "Team defaults were useful, but review support felt too heavy.",
            "--rating",
            "mixed",
            "--kind",
            "team",
        ],
        cwd=project_root,
    ).returncode == 0

    proc = _run_cli(["template", "history", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["totals"]["retrospectives"] == 1
    assert payload["recent_cautions"]


def test_template_recommend_uses_history_weakly(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_saved_template(project_root, name="auth-bug-template")
    _duplicate_template(project_root, "auth-bug-template", "auth-bug-template-v2")
    assert _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template-v2",
            "This template worked very well for auth bug fixes.",
            "--rating",
            "strong",
            "--kind",
            "fit",
        ],
        cwd=project_root,
    ).returncode == 0

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    candidates = {item["name"]: item for item in payload["candidates"]}
    assert candidates["auth-bug-template-v2"]["score"] > candidates["auth-bug-template"]["score"]
    assert "template has prior positive local outcome history" in candidates["auth-bug-template-v2"]["reasons"]


def test_weak_retrospective_adds_recommendation_caution(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_saved_template(project_root, name="auth-bug-template")
    _duplicate_template(project_root, "auth-bug-template", "auth-bug-template-v2")
    assert _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template-v2",
            "Poor fit for this project.",
            "--rating",
            "weak",
            "--kind",
            "fit",
        ],
        cwd=project_root,
    ).returncode == 0

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    caution = next(item for item in payload["candidates"] if item["name"] == "auth-bug-template-v2")
    assert "template has local caution history" in caution["warnings"]


def test_template_show_status_and_harness_show_include_history_hint(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_saved_template(project_root)
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template",
            "Good fit after apply.",
            "--rating",
            "good",
        ],
        cwd=project_root,
    ).returncode == 0

    show_proc = _run_cli(["template", "show", "auth-bug-template"], cwd=project_root)
    status_proc = _run_cli(["status"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert show_proc.returncode == 0, show_proc.stderr
    assert "Template history:" in show_proc.stdout
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template history:" in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Template history:" in harness_proc.stdout


def test_template_history_commands_do_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_saved_template(project_root)
    source_path = project_root / "src" / "auth.py"
    before = _sha256(source_path)

    assert _run_cli(["template", "history", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template",
            "Good local fit.",
            "--rating",
            "good",
        ],
        cwd=project_root,
    ).returncode == 0
    assert _run_cli(["template", "retrospectives", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "show", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
