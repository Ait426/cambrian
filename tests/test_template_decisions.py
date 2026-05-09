from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_template_recommend import _prepare_template_store


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_template_store(source_store: Path, target_root: Path) -> None:
    target_store = target_root / ".cambrian" / "templates" / "templates.yaml"
    target_store.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_store, target_store)


def _prepare_project_with_templates(tmp_path: Path) -> Path:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _copy_template_store(store_path, project_root)
    return project_root


def _save_recommend_and_diff(project_root: Path, template_name: str = "auth-bug-template") -> None:
    recommend = _run_cli(["template", "recommend", "--save"], cwd=project_root)
    diff = _run_cli(["template", "diff", template_name, "--save"], cwd=project_root)
    assert recommend.returncode == 0, recommend.stderr
    assert diff.returncode == 0, diff.stderr


def test_template_review_builds_from_recommendation_and_diff(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _save_recommend_and_diff(project_root)

    proc = _run_cli(["template", "review", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["template_name"] == "auth-bug-template"
    assert payload["source_recommendation_ref"] == ".cambrian/templates/recommendation.yaml"
    assert payload["source_diff_ref"] == ".cambrian/templates/diff_report.yaml"
    assert payload["fit_reasons"]
    assert payload["diff_highlights"]


def test_template_review_save(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _save_recommend_and_diff(project_root)

    proc = _run_cli(["template", "review", "auth-bug-template", "--save", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    saved_path = project_root / payload["saved_path"]
    assert saved_path.exists()
    review = _read_yaml(saved_path)
    assert review["template_name"] == "auth-bug-template"


def test_accept_template_records_decision_without_apply(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _save_recommend_and_diff(project_root)
    assert _run_cli(["template", "review", "auth-bug-template", "--save"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "accept", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "accepted"
    decision = payload["decision"]
    assert decision["source_review_ref"]
    assert decision["source_diff_ref"] == ".cambrian/templates/diff_report.yaml"
    assert decision["source_recommendation_ref"] == ".cambrian/templates/recommendation.yaml"
    assert (project_root / ".cambrian" / "templates" / "decisions.yaml").exists()
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_dismiss_template_records_resolution(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _save_recommend_and_diff(project_root)

    proc = _run_cli(
        ["template", "dismiss", "auth-bug-template", "--resolution", "Not a good fit right now", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "dismissed"
    assert payload["decision"]["resolution"] == "Not a good fit right now"
    decisions = _read_yaml(project_root / ".cambrian" / "templates" / "decisions.yaml")
    assert decisions["decisions"][0]["status"] == "dismissed"


def test_template_decisions_list_and_filter(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "dismiss", "docs-review-template"], cwd=project_root).returncode == 0

    all_proc = _run_cli(["template", "decisions"], cwd=project_root)
    accepted_proc = _run_cli(["template", "decisions", "--status", "accepted", "--json"], cwd=project_root)

    assert all_proc.returncode == 0, all_proc.stderr
    assert "Template Decisions" in all_proc.stdout
    assert accepted_proc.returncode == 0, accepted_proc.stderr
    payload = json.loads(accepted_proc.stdout)
    assert len(payload["decisions"]) == 1
    assert payload["decisions"][0]["template_name"] == "auth-bug-template"


def test_status_shows_accepted_not_applied_hint(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["status"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "Template decision:" in proc.stdout
    assert "cambrian template apply auth-bug-template" in proc.stdout


def test_template_show_includes_decision_summary(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "show", "auth-bug-template"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "Template decisions:" in proc.stdout
    assert "accepted" in proc.stdout


def test_harness_show_includes_template_decision_summary(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["harness", "show"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "Template decisions:" in proc.stdout
    assert "Accepted next template:" in proc.stdout
    assert "auth-bug-template" in proc.stdout


def test_standalone_accept_has_warning(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)

    proc = _run_cli(["template", "accept", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    warnings = payload["decision"]["warnings"]
    assert any("without a saved template review" in warning for warning in warnings)
    assert any("no saved recommendation or diff evidence" in warning for warning in warnings)


def test_template_decision_commands_do_not_mutate_source(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _save_recommend_and_diff(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["template", "review", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "dismiss", "docs-review-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "decisions"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "show", "auth-bug-template"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
    assert (project_root / ".cambrian" / "templates" / "reviews").exists()
    assert (project_root / ".cambrian" / "templates" / "decisions.yaml").exists()
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()
