from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_harness_templates import _approve_template_for_apply
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


def test_apply_safe_when_diff_review_accept_exist(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _approve_template_for_apply(project_root, "auth-bug-template")

    proc = _run_cli(["template", "apply", "auth-bug-template", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "applied"
    assert payload["guardrails"]["status"] == "safe"
    assert (project_root / ".cambrian" / "templates" / "apply_guardrails.yaml").exists()
    assert (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_apply_without_accept_is_blocked_until_force(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "recommend", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "diff", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "review", "auth-bug-template", "--save"], cwd=project_root).returncode == 0

    blocked = _run_cli(["template", "apply", "auth-bug-template", "--json"], cwd=project_root)
    forced = _run_cli(["template", "apply", "auth-bug-template", "--force", "--json"], cwd=project_root)

    assert blocked.returncode != 0
    blocked_payload = json.loads(blocked.stdout)
    assert blocked_payload["guardrails"]["status"] == "safe_with_warnings"
    assert blocked_payload["force_allowed"] is True
    assert forced.returncode == 0, forced.stderr
    assert json.loads(forced.stdout)["status"] == "applied"


def test_dismissed_decision_blocks_apply_even_with_force(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "recommend", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "diff", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "review", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "dismiss", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "apply", "auth-bug-template", "--force", "--json"], cwd=project_root)

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["guardrails"]["status"] == "blocked"
    assert any(check["check_id"] == "decision_status" and check["status"] == "fail" for check in payload["guardrails"]["checks"])
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()


def test_missing_diff_blocks_apply(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "recommend", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "review", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "apply", "auth-bug-template", "--force", "--json"], cwd=project_root)

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["guardrails"]["status"] == "blocked"
    assert any(check["check_id"] == "diff_exists" and check["status"] == "fail" for check in payload["guardrails"]["checks"])


def test_review_missing_warns_and_requires_force(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "diff", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0

    blocked = _run_cli(["template", "apply", "auth-bug-template", "--json"], cwd=project_root)
    forced = _run_cli(["template", "apply", "auth-bug-template", "--force", "--json"], cwd=project_root)

    assert blocked.returncode != 0
    assert json.loads(blocked.stdout)["guardrails"]["status"] == "safe_with_warnings"
    assert forced.returncode == 0, forced.stderr


def test_current_template_conflict_warns(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _approve_template_for_apply(project_root, "auth-bug-template")
    assert _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "diff", "docs-review-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "review", "docs-review-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "accept", "docs-review-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "apply", "docs-review-template", "--json"], cwd=project_root)

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["guardrails"]["status"] == "safe_with_warnings"
    assert any(check["check_id"] == "current_template_conflict" and check["status"] == "warn" for check in payload["guardrails"]["checks"])


def test_uninitialized_project_blocked(tmp_path: Path) -> None:
    store_path = _prepare_template_store(tmp_path)
    project_root = tmp_path / "uninitialized"
    project_root.mkdir(parents=True)
    _copy_template_store(store_path, project_root)
    assert _run_cli(["template", "diff", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "review", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "accept", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "apply", "auth-bug-template", "--force", "--json"], cwd=project_root)

    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["guardrails"]["status"] == "blocked"
    assert any(check["check_id"] == "initialized_project" and check["status"] == "fail" for check in payload["guardrails"]["checks"])


def test_status_and_show_include_guardrail_summary(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    _approve_template_for_apply(project_root, "auth-bug-template")
    blocked = _run_cli(["template", "apply", "auth-bug-template", "--json"], cwd=project_root)
    assert blocked.returncode == 0, blocked.stderr

    status_proc = _run_cli(["status"], cwd=project_root)
    show_proc = _run_cli(["template", "show", "auth-bug-template"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template apply guardrail:" in status_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Template apply guardrail:" in show_proc.stdout


def test_apply_guardrails_do_not_mutate_source(tmp_path: Path) -> None:
    project_root = _prepare_project_with_templates(tmp_path)
    assert _run_cli(["template", "diff", "auth-bug-template", "--save"], cwd=project_root).returncode == 0
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    blocked = _run_cli(["template", "apply", "auth-bug-template"], cwd=project_root)

    assert blocked.returncode != 0
    assert _sha256(source_path) == before
    assert (project_root / ".cambrian" / "templates" / "apply_guardrails.yaml").exists()
    assert not (project_root / ".cambrian" / "templates" / "current_template.yaml").exists()
