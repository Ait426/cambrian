from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_harness_templates import _prepare_template_source, _write_yaml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _export_template(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "source"
    _prepare_template_source(source_root)
    assert _run_cli(["template", "save", "auth-bug-template", "--tag", "auth"], cwd=source_root).returncode == 0
    export_path = tmp_path / "auth-bug-template.yaml"
    proc = _run_cli(["template", "export", "auth-bug-template", "--out", str(export_path), "--json"], cwd=source_root)
    assert proc.returncode == 0, proc.stderr
    assert export_path.exists()
    return source_root, export_path


def test_export_local_template_excludes_live_state(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _prepare_template_source(source_root)
    _write_yaml(source_root / ".cambrian" / "notes" / "live.yaml", {"text": "do not export note"})
    _write_yaml(source_root / ".cambrian" / "sessions" / "live.yaml", {"text": "do not export session"})
    _write_yaml(source_root / ".cambrian" / "adoptions" / "live.yaml", {"text": "do not export adoption"})
    assert _run_cli(["template", "save", "auth-bug-template"], cwd=source_root).returncode == 0
    export_path = tmp_path / "portable.yaml"

    proc = _run_cli(["template", "export", "auth-bug-template", "--out", str(export_path), "--json"], cwd=source_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    exported = _read_yaml(export_path)
    dumped = yaml.safe_dump(exported, allow_unicode=True, sort_keys=False)
    assert payload["status"] == "exported"
    assert exported["name"] == "auth-bug-template"
    assert exported["project_defaults"]
    assert exported["team_defaults"]
    assert "do not export note" not in dumped
    assert "do not export session" not in dumped
    assert "do not export adoption" not in dumped


def test_export_missing_template_blocked(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_target_project(project_root)

    proc = _run_cli(["template", "export", "missing-template"], cwd=project_root)

    assert proc.returncode != 0
    assert "Template not found" in proc.stderr


def test_import_template_merges_store_and_saves_provenance(tmp_path: Path) -> None:
    source_root, export_path = _export_template(tmp_path)
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)

    proc = _run_cli(["template", "import", str(export_path), "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    imported_path = target_root / ".cambrian" / "templates" / "imported" / "auth-bug-template.yaml"
    store = _read_yaml(target_root / ".cambrian" / "templates" / "templates.yaml")
    imported = _read_yaml(imported_path)
    template = next(item for item in store["templates"] if item["name"] == "auth-bug-template")
    assert payload["record"]["source_kind"] == "imported"
    assert imported_path.exists()
    assert imported["record"]["source_project_name"] == source_root.name
    assert template["source_kind"] == "imported"
    assert template["source_origin"]["source_project_name"] == source_root.name


def test_imported_template_visible_in_list_and_show(tmp_path: Path) -> None:
    _source_root, export_path = _export_template(tmp_path)
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    assert _run_cli(["template", "import", str(export_path)], cwd=target_root).returncode == 0

    list_proc = _run_cli(["template", "list"], cwd=target_root)
    show_proc = _run_cli(["template", "show", "auth-bug-template"], cwd=target_root)

    assert list_proc.returncode == 0, list_proc.stderr
    assert "Imported:" in list_proc.stdout
    assert "auth-bug-template" in list_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Source:" in show_proc.stdout
    assert "kind : imported" in show_proc.stdout


def test_imported_template_eligible_for_recommend(tmp_path: Path) -> None:
    _source_root, export_path = _export_template(tmp_path)
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    assert _run_cli(["template", "import", str(export_path)], cwd=target_root).returncode == 0

    proc = _run_cli(["template", "recommend", "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert any(candidate["name"] == "auth-bug-template" for candidate in payload["candidates"])


def test_imported_template_eligible_for_bootstrap(tmp_path: Path) -> None:
    _source_root, export_path = _export_template(tmp_path)
    target_root = tmp_path / "uninitialized"
    target_root.mkdir(parents=True)
    (target_root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert _run_cli(["template", "import", str(export_path)], cwd=target_root).returncode == 0

    proc = _run_cli(["init", "--template", "auth-bug-template", "--non-interactive", "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    current = _read_yaml(target_root / ".cambrian" / "templates" / "current_template.yaml")
    assert current["name"] == "auth-bug-template"
    assert current["source_kind"] == "imported"


def test_import_conflict_blocked_without_rename(tmp_path: Path) -> None:
    _source_root, export_path = _export_template(tmp_path)
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    assert _run_cli(["template", "import", str(export_path)], cwd=target_root).returncode == 0

    proc = _run_cli(["template", "import", str(export_path)], cwd=target_root)

    assert proc.returncode != 0
    assert "Template import blocked" in proc.stderr
    assert "--as" in proc.stderr


def test_import_conflict_resolved_with_as_name(tmp_path: Path) -> None:
    _source_root, export_path = _export_template(tmp_path)
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    assert _run_cli(["template", "import", str(export_path)], cwd=target_root).returncode == 0

    proc = _run_cli(["template", "import", str(export_path), "--as", "auth-bug-template-v2", "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    store = _read_yaml(target_root / ".cambrian" / "templates" / "templates.yaml")
    names = {item["name"] for item in store["templates"]}
    assert {"auth-bug-template", "auth-bug-template-v2"} <= names
    renamed = next(item for item in store["templates"] if item["name"] == "auth-bug-template-v2")
    assert renamed["template_id"] == "auth-bug-template-v2"


def test_template_transfer_does_not_mutate_project_source(tmp_path: Path) -> None:
    _source_root, export_path = _export_template(tmp_path)
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    source_path = target_root / "src" / "auth.py"
    before = _sha256(source_path)

    assert _run_cli(["template", "import", str(export_path)], cwd=target_root).returncode == 0
    assert _run_cli(["template", "list"], cwd=target_root).returncode == 0
    assert _run_cli(["template", "show", "auth-bug-template"], cwd=target_root).returncode == 0
    assert _run_cli(["template", "recommend"], cwd=target_root).returncode == 0

    assert _sha256(source_path) == before
