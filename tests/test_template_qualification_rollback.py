from __future__ import annotations

import json
from pathlib import Path

from test_agent_transfer import _read_yaml, _run_cli
from test_harness_templates import _write_yaml
from test_template_qualification import _prepare_project, _sha256


def _saved_qualification(project_root: Path) -> str:
    proc = _run_cli(
        [
            "template",
            "qualify",
            "auth-bug-template-local",
            "--workset",
            "auth-bug-workset",
            "--save",
            "--json",
        ],
        cwd=project_root,
    )
    assert proc.returncode == 0, proc.stderr
    return str(json.loads(proc.stdout)["saved_path"])


def _accept(project_root: Path, qualification_ref: str, *args: str) -> dict:
    proc = _run_cli(["template", "qualify-accept", qualification_ref, *args, "--json"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _latest_library_kind(project_root: Path, template_name: str) -> str | None:
    decisions_path = project_root / ".cambrian" / "templates" / "library_decisions.yaml"
    if not decisions_path.exists():
        return None
    decisions = _read_yaml(decisions_path).get("decisions", []) or []
    latest = [
        item for item in decisions
        if item.get("template_name") == template_name
    ]
    return latest[-1].get("decision_kind") if latest else None


def test_accept_writes_adoption_snapshot(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)

    payload = _accept(project_root, qualification_ref, "--set-lane-default")

    adoption_path = project_root / payload["adoption_path"]
    assert adoption_path.exists()
    adoption = _read_yaml(adoption_path)
    assert adoption["status"] == "applied"
    assert adoption["before_state"]["candidate_library_standing"] is None
    assert adoption["after_state"]["candidate_library_standing"]["decision_kind"] == "promote"
    assert adoption["after_state"]["lane_default_template_name"] == "auth-bug-template-local"


def test_rollback_restores_lane_default_and_parent_lists(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _write_yaml(
        project_root / ".cambrian" / "lane" / "playbook.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-04-30T00:00:00+00:00",
            "lane_id": "python-pytest-auth-bug-core",
            "label": "Python + pytest + auth/login bug fixes",
            "default_template_name": "imported-auth-bug-template",
            "backup_templates": ["legacy-backup-template"],
            "retired_templates": ["old-retired-template"],
            "source_decision_ref": "previous-decision",
            "notes": ["previous lane state"],
            "warnings": [],
            "errors": [],
        },
    )
    qualification_ref = _saved_qualification(project_root)
    accepted = _accept(project_root, qualification_ref, "--set-lane-default")

    revert = _run_cli(["template", "qualify-revert", accepted["adoption_path"], "--json"], cwd=project_root)

    assert revert.returncode == 0, revert.stderr
    playbook = _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")
    assert playbook["default_template_name"] == "imported-auth-bug-template"
    assert playbook["backup_templates"] == ["legacy-backup-template"]
    assert playbook["retired_templates"] == ["old-retired-template"]
    rollback_path = project_root / json.loads(revert.stdout)["rollback_path"]
    assert rollback_path.exists()


def test_rollback_restores_parent_retire_state(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)
    accepted = _accept(project_root, qualification_ref, "--set-lane-default", "--parent-action", "retire")
    assert "imported-auth-bug-template" in _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")["retired_templates"]

    revert = _run_cli(["template", "qualify-revert", accepted["adoption_path"], "--json"], cwd=project_root)

    assert revert.returncode == 0, revert.stderr
    playbook = _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")
    assert playbook["retired_templates"] == []


def test_rollback_clears_candidate_standing_when_none_before(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)
    accepted = _accept(project_root, qualification_ref)
    assert _latest_library_kind(project_root, "auth-bug-template-local") == "promote"

    revert = _run_cli(["template", "qualify-revert", accepted["adoption_path"], "--json"], cwd=project_root)

    assert revert.returncode == 0, revert.stderr
    assert _latest_library_kind(project_root, "auth-bug-template-local") == "clear"
    recommend = _run_cli(["template", "recommend", "--json"], cwd=project_root)
    assert recommend.returncode == 0, recommend.stderr
    candidate = {
        item["name"]: item
        for item in json.loads(recommend.stdout)["candidates"]
    }["auth-bug-template-local"]
    assert "previously promoted in local template library" not in candidate["reasons"]


def test_rollback_restores_prior_candidate_and_reference_standing(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    keep = _run_cli(["template", "keep", "auth-bug-template-local"], cwd=project_root)
    watch = _run_cli(["template", "watch", "imported-auth-bug-template"], cwd=project_root)
    assert keep.returncode == 0, keep.stderr
    assert watch.returncode == 0, watch.stderr
    qualification_ref = _saved_qualification(project_root)
    accepted = _accept(project_root, qualification_ref, "--set-lane-default", "--parent-action", "retire")

    revert = _run_cli(["template", "qualify-revert", accepted["adoption_path"], "--json"], cwd=project_root)

    assert revert.returncode == 0, revert.stderr
    assert _latest_library_kind(project_root, "auth-bug-template-local") == "keep"
    assert _latest_library_kind(project_root, "imported-auth-bug-template") == "watch"


def test_already_reverted_is_blocked(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)
    accepted = _accept(project_root, qualification_ref, "--set-lane-default")
    first = _run_cli(["template", "qualify-revert", accepted["adoption_path"]], cwd=project_root)
    second = _run_cli(["template", "qualify-revert", accepted["adoption_path"]], cwd=project_root)

    assert first.returncode == 0, first.stderr
    assert second.returncode != 0
    assert "already been reverted" in second.stderr


def test_adoptions_show_lineage_status_and_source_immutability(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    source_before = _sha256(source)
    current_template = project_root / ".cambrian" / "templates" / "current_template.yaml"
    current_before = current_template.read_text(encoding="utf-8") if current_template.exists() else None
    qualification_ref = _saved_qualification(project_root)
    accepted = _accept(project_root, qualification_ref, "--set-lane-default")
    revert = _run_cli(
        ["template", "qualify-revert", accepted["adoption_path"], "--resolution", "later evidence regressed"],
        cwd=project_root,
    )
    adoptions = _run_cli(["template", "qualify-adoptions"], cwd=project_root)
    show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    lineage = _run_cli(["template", "lineage", "auth-bug-template-local"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)
    harness = _run_cli(["harness", "show"], cwd=project_root)

    assert revert.returncode == 0, revert.stderr
    assert adoptions.returncode == 0, adoptions.stderr
    assert "Reverted:" in adoptions.stdout
    assert show.returncode == 0, show.stderr
    assert "Qualification adoption:" in show.stdout
    assert "reverted" in show.stdout
    assert lineage.returncode == 0, lineage.stderr
    assert "Qualification adoption:" in lineage.stdout
    assert status.returncode == 0, status.stderr
    assert "Lane default rollback:" in status.stdout
    assert harness.returncode == 0, harness.stderr
    assert "Qualification adoption:" in harness.stdout
    assert _sha256(source) == source_before
    current_after = current_template.read_text(encoding="utf-8") if current_template.exists() else None
    assert current_after == current_before
