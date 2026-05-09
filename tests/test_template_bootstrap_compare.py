from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from engine.project_template_bootstrap_compare import (
    BootstrapTemplateCompareBuilder,
    render_bootstrap_template_compare,
)
from test_agent_transfer import _read_yaml, _run_cli
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


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_bootstrap_compare_shortlist_contains_recommended_and_alternatives(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    report = BootstrapTemplateCompareBuilder().build(project_root)

    assert report.recommended_template_name == "auth-bug-template"
    names = [candidate.template_name for candidate in report.candidates]
    assert names[0] == "auth-bug-template"
    assert "docs-review-template" in names
    assert any(candidate.recommendation == "alternative" for candidate in report.candidates)


def test_bootstrap_compare_summary_shows_reasons(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    report = BootstrapTemplateCompareBuilder().build(project_root)
    rendered = render_bootstrap_template_compare(report)

    assert "Bootstrap Template Shortlist" in rendered
    assert "auth-bug-template" in rendered
    assert "docs-review-template" in rendered
    assert report.compare_summary
    assert any(candidate.short_summary for candidate in report.candidates)


def test_use_recommended_records_considered_templates_and_compare_ref(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--use-recommended-template", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    choice = payload["template_bootstrap_choice"]
    assert choice["selection_mode"] == "recommended"
    assert choice["selected_template_name"] == "auth-bug-template"
    assert "auth-bug-template" in choice["considered_templates"]
    assert "docs-review-template" in choice["considered_templates"]
    assert choice["source_compare_ref"] == ".cambrian/templates/bootstrap_compare.yaml"
    assert (project_root / ".cambrian" / "templates" / "bootstrap_compare.yaml").exists()


def test_answers_file_choose_another_bootstraps_selected_alternative(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)
    answers_path = project_root / "answers.yaml"
    _write_yaml(
        answers_path,
        {
            "template_selection_mode": "manual_choice",
            "selected_template_name": "docs-review-template",
            "project_name": "target",
            "project_type": "python",
            "stack": ["python"],
            "primary_use_cases": ["docs_update"],
            "mode": "balanced",
        },
    )

    proc = _run_cli(["init", "--wizard", "--answers-file", str(answers_path), "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    choice = payload["template_bootstrap_choice"]
    assert choice["selection_mode"] == "manual_choice"
    assert choice["selected_template_name"] == "docs-review-template"
    current = _read_yaml(project_root / ".cambrian" / "templates" / "current_template.yaml")
    record = _read_yaml(project_root / ".cambrian" / "templates" / "bootstrap_record.yaml")
    assert current["name"] == "docs-review-template"
    assert record["template_name"] == "docs-review-template"
    assert record["applied_defaults"]["bootstrap_choice"]["selection_mode"] == "manual_choice"


def test_skip_path_records_shortlist_but_no_selected_template(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--skip-template", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    choice = payload["template_bootstrap_choice"]
    assert choice["selection_mode"] == "skipped"
    assert choice["selected_template_name"] is None
    assert "auth-bug-template" in choice["considered_templates"]
    assert choice["source_compare_ref"] == ".cambrian/templates/bootstrap_compare.yaml"
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_explicit_template_still_beats_recommendation_and_records_shortlist(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--template", "docs-review-template", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    choice = payload["template_bootstrap_choice"]
    assert choice["recommended_template_name"] == "auth-bug-template"
    assert choice["selection_mode"] == "explicit"
    assert choice["selected_template_name"] == "docs-review-template"
    assert "auth-bug-template" in choice["considered_templates"]


def test_non_interactive_default_still_does_not_auto_select(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)

    proc = _run_cli(["init", "--non-interactive", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "template_bootstrap_choice" not in payload
    assert not (project_root / ".cambrian" / "templates" / "bootstrap_compare.yaml").exists()
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_bootstrap_compare_and_choice_do_not_mutate_source_files(tmp_path: Path) -> None:
    project_root = _target_with_templates(tmp_path)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["init", "--use-recommended-template", "--non-interactive"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
