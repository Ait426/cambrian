from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from engine.project_template_library_policy import (
    TemplateLibraryPolicyStore,
    build_and_save_template_library_policy_overlay,
    default_template_library_policy_overlay_path,
)
from test_agent_transfer import _read_yaml, _run_cli
from test_template_library_decisions import _duplicate_template, _prepare_library_project


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_template_library(source_root: Path, target_root: Path) -> None:
    target_templates = target_root / ".cambrian" / "templates"
    target_templates.mkdir(parents=True, exist_ok=True)
    for name in ("templates.yaml", "library_decisions.yaml"):
        source = source_root / ".cambrian" / "templates" / name
        if source.exists():
            shutil.copy2(source, target_templates / name)


def _uninitialized_target(tmp_path: Path, source_root: Path) -> Path:
    target_root = tmp_path / "target"
    target_root.mkdir(parents=True, exist_ok=True)
    (target_root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (target_root / "tests").mkdir()
    _copy_template_library(source_root, target_root)
    return target_root


def test_build_overlay_from_library_decisions(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    _duplicate_template(project_root, "auth-bug-template", "keep-template")
    _duplicate_template(project_root, "auth-bug-template", "watch-template")
    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "keep", "keep-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "backup", "safe-patch-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "watch", "watch-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "legacy-general-template"], cwd=project_root).returncode == 0

    overlay, path = build_and_save_template_library_policy_overlay(project_root)

    assert path == default_template_library_policy_overlay_path(project_root)
    assert "auth-bug-template" in overlay.promoted_templates
    assert "keep-template" in overlay.kept_templates
    assert "safe-patch-template" in overlay.backup_templates
    assert "watch-template" in overlay.watched_templates
    assert "legacy-general-template" in overlay.retired_templates
    saved = TemplateLibraryPolicyStore().load(path)
    assert saved.promoted_templates == overlay.promoted_templates


def test_latest_policy_decision_wins(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "auth-bug-template"], cwd=project_root).returncode == 0

    overlay, _ = build_and_save_template_library_policy_overlay(project_root)

    assert "auth-bug-template" not in overlay.promoted_templates
    assert "auth-bug-template" in overlay.retired_templates


def test_recommend_uses_promote_and_retire_policy_bias(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "promote", "safe-patch-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "auth-bug-template"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    safe = next(item for item in payload["candidates"] if item["name"] == "safe-patch-template")
    auth = next(item for item in payload["candidates"] if item["name"] == "auth-bug-template")
    assert safe["score"] > auth["score"]
    assert "previously promoted in local template library" in safe["reasons"]
    assert "template is retired in local library" in auth["warnings"]
    assert auth["project_fit"]["template_library_policy"]["decision_kind"] == "retire"


def test_bootstrap_shortlist_uses_backup_and_watch_policy(tmp_path: Path) -> None:
    source_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "backup", "safe-patch-template"], cwd=source_root).returncode == 0
    assert _run_cli(["template", "watch", "legacy-general-template"], cwd=source_root).returncode == 0
    target_root = _uninitialized_target(tmp_path, source_root)

    proc = _run_cli(["init", "--skip-template", "--non-interactive", "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    choice = payload["template_bootstrap_choice"]
    context = choice["template_library_policy_context"]
    assert "safe-patch-template" in context["backup_templates"]
    assert "legacy-general-template" in context["watched_templates"]
    compare = _read_yaml(target_root / ".cambrian" / "templates" / "bootstrap_compare.yaml")
    safe = next(item for item in compare["candidates"] if item["template_name"] == "safe-patch-template")
    legacy = next(item for item in compare["candidates"] if item["template_name"] == "legacy-general-template")
    assert "library policy: backup template" in safe["short_summary"]
    assert "library policy: watch" in legacy["short_summary"]


def test_explicit_template_beats_retire_policy(tmp_path: Path) -> None:
    source_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "retire", "legacy-general-template"], cwd=source_root).returncode == 0
    target_root = _uninitialized_target(tmp_path, source_root)

    proc = _run_cli(
        ["init", "--template", "legacy-general-template", "--non-interactive", "--json"],
        cwd=target_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    choice = payload["template_bootstrap_choice"]
    assert choice["selection_mode"] == "explicit"
    assert choice["selected_template_name"] == "legacy-general-template"
    assert "legacy-general-template" in choice["template_library_policy_context"]["retired_templates"]
    current = _read_yaml(target_root / ".cambrian" / "templates" / "current_template.yaml")
    assert current["name"] == "legacy-general-template"


def test_bootstrap_choice_stores_library_policy_context(tmp_path: Path) -> None:
    source_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=source_root).returncode == 0
    assert _run_cli(["template", "backup", "safe-patch-template"], cwd=source_root).returncode == 0
    target_root = _uninitialized_target(tmp_path, source_root)

    proc = _run_cli(["init", "--use-recommended-template", "--non-interactive", "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    choice = _read_yaml(target_root / ".cambrian" / "templates" / "bootstrap_choice.yaml")
    context = choice["template_library_policy_context"]
    assert context["enabled"] is True
    assert context["overlay_ref"] == ".cambrian/templates/library_policy_overlay.yaml"
    assert "auth-bug-template" in context["promoted_templates"]
    assert "safe-patch-template" in context["backup_templates"]


def test_status_and_template_show_policy_summary(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "backup", "safe-patch-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "legacy-general-template"], cwd=project_root).returncode == 0

    status_proc = _run_cli(["status"], cwd=project_root)
    show_proc = _run_cli(["template", "show", "auth-bug-template"], cwd=project_root)
    harness_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Template library policy:" in status_proc.stdout
    assert "auth-bug-template" in status_proc.stdout
    assert "safe-patch-template" in status_proc.stdout
    assert "legacy-general-template" in status_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Library standing:" in show_proc.stdout
    assert "promote" in show_proc.stdout or "promoted" in show_proc.stdout
    assert harness_proc.returncode == 0, harness_proc.stderr
    assert "Template library policy:" in harness_proc.stdout


def test_policy_overlay_surfaces_do_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = _prepare_library_project(tmp_path)
    source_path = project_root / "src" / "auth.py"
    before = _sha256(source_path)
    assert _run_cli(["template", "promote", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "retire", "legacy-general-template"], cwd=project_root).returncode == 0

    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "board"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "show", "auth-bug-template"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
