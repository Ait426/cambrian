from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_harness_templates import _approve_template_for_apply, _prepare_template_source, _write_yaml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_template_store(project_root: Path) -> Path:
    source_root = project_root / "source"
    _prepare_template_source(source_root)
    assert _run_cli(["template", "save", "auth-bug-template", "--tag", "auth"], cwd=source_root).returncode == 0
    store_path = source_root / ".cambrian" / "templates" / "templates.yaml"
    payload = _read_yaml(store_path)
    auth_template = payload["templates"][0]
    docs_template = copy.deepcopy(auth_template)
    docs_template["template_id"] = "docs-review-template"
    docs_template["name"] = "docs-review-template"
    docs_template["description"] = "Docs review bootstrap"
    docs_template["tags"] = ["docs"]
    docs_template["project_defaults"] = {
        "project_type": "docs",
        "stack": ["markdown"],
        "test_command": None,
        "mode": "balanced",
        "primary_use_cases": ["docs_update"],
    }
    docs_template["agent_defaults"] = {
        "active_agents": ["docs-update-agent"],
        "preferred_lead_agents": ["docs-update-agent"],
        "preferred_support_agents": ["review-agent"],
    }
    docs_template["team_defaults"] = {
        "active_team_id": "docs-review-team",
        "active_team_name": "docs-review-team",
        "active_team": None,
        "backup_teams": [],
        "watched_teams": [],
        "saved_teams": [],
    }
    docs_template["policy_defaults"] = {
        "test_first_practice": False,
        "narrow_change_scope": False,
        "increase_review_support": True,
        "promote_request_focus": ["docs_update"],
    }
    docs_template["fit_hints"] = ["good starting point for docs_update work"]
    payload["templates"].append(docs_template)
    _write_yaml(store_path, payload)
    return store_path


def _copy_template_store(source_store: Path, target_root: Path) -> None:
    target_store = target_root / ".cambrian" / "templates" / "templates.yaml"
    target_store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_store, target_store)


def test_recommend_best_template_for_initialized_project(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["best_template_name"] == "auth-bug-template"
    assert payload["candidates"][0]["recommendation"] == "best_fit"
    assert "cambrian template apply auth-bug-template" in payload["next_actions"]


def test_recommend_with_request_reflects_request_fit(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "recommend", "--request", "로그인 에러 수정해", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "request"
    assert payload["best_template_name"] == "auth-bug-template"
    best = payload["candidates"][0]
    assert "bug_fix" in best["project_fit"]["request_fit"] or "auth" in best["project_fit"]["request_fit"]


def test_uninitialized_lightweight_recommendation(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "uninitialized"
    project_root.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (project_root / "tests").mkdir()
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["signals_mode"] == "lightweight"
    assert payload["best_template_name"] == "auth-bug-template"


def test_unrelated_template_is_weak_or_rejected(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    docs = next(candidate for candidate in payload["candidates"] if candidate["name"] == "docs-review-template")
    assert docs["recommendation"] in {"weak", "reject"}
    assert docs["score"] < payload["candidates"][0]["score"]


def test_save_recommendation_report(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    proc = _run_cli(["template", "recommend", "--save", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    report_path = project_root / payload["saved_path"]
    assert report_path.exists()
    report = _read_yaml(report_path)
    assert report["best_template_name"] == "auth-bug-template"


def test_status_and_harness_show_template_hint_without_current_template(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)

    status_proc = _run_cli(["status"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template hint:" in status_proc.stdout
    assert "auth-bug-template" in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Template hint:" in harness_proc.stdout
    assert "auth-bug-template" in harness_proc.stdout


def test_current_template_suppresses_recommendation_noise(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Harness template:" in status_proc.stdout
    assert "Template hint:" not in status_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Harness template:" in harness_proc.stdout


def test_template_recommend_does_not_mutate_project_source(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "recommend", "--request", "로그인 에러 수정해"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["harness", "show"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
    assert not (project_root / ".cambrian" / "templates" / "recommendation.yaml").exists()
