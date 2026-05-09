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


def _rewrite_qualification_verdict(project_root: Path, qualification_ref: str, verdict: str) -> None:
    path = project_root / qualification_ref
    payload = _read_yaml(path)
    payload["verdict"] = verdict
    payload["why_candidate_stronger"] = []
    payload["where_candidate_weaker"] = [f"forced {verdict} fixture"]
    _write_yaml(path, payload)


def _library_decisions(project_root: Path) -> list[dict]:
    path = project_root / ".cambrian" / "templates" / "library_decisions.yaml"
    if not path.exists():
        return []
    return list(_read_yaml(path).get("decisions", []) or [])


def test_accept_candidate_stronger_promotes_candidate(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)

    proc = _run_cli(["template", "qualify-accept", qualification_ref, "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "accepted"
    decisions = _library_decisions(project_root)
    assert any(
        item["template_name"] == "auth-bug-template-local" and item["decision_kind"] == "promote"
        for item in decisions
    )
    assert any(
        item["template_name"] == "imported-auth-bug-template" and item["decision_kind"] == "backup"
        for item in decisions
    )


def test_accept_with_lane_default_switch_keeps_parent_as_backup(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)

    proc = _run_cli(
        ["template", "qualify-accept", qualification_ref, "--set-lane-default", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    playbook = _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")
    assert playbook["default_template_name"] == "auth-bug-template-local"
    assert "imported-auth-bug-template" in playbook["backup_templates"]
    assert playbook["retired_templates"] == []


def test_parent_retire_action_records_retirement(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)

    proc = _run_cli(
        [
            "template",
            "qualify-accept",
            qualification_ref,
            "--set-lane-default",
            "--parent-action",
            "retire",
            "--json",
        ],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    playbook = _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")
    assert "imported-auth-bug-template" in playbook["retired_templates"]
    decisions = _library_decisions(project_root)
    assert any(
        item["template_name"] == "imported-auth-bug-template" and item["decision_kind"] == "retire"
        for item in decisions
    )


def test_non_candidate_stronger_blocked_without_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)
    _rewrite_qualification_verdict(project_root, qualification_ref, "mixed")

    proc = _run_cli(["template", "qualify-accept", qualification_ref], cwd=project_root)

    assert proc.returncode != 0
    assert "candidate_stronger" in proc.stderr
    assert not (project_root / ".cambrian" / "lane" / "playbook.yaml").exists()


def test_force_allows_non_stronger_accept_with_warning(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)
    _rewrite_qualification_verdict(project_root, qualification_ref, "mixed")

    proc = _run_cli(["template", "qualify-accept", qualification_ref, "--force", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["warnings"]
    assert payload["decision"]["qualification_verdict"] == "mixed"


def test_dismiss_stores_decision_without_rollback(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)

    proc = _run_cli(
        ["template", "qualify-dismiss", qualification_ref, "--resolution", "gain too small", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    decisions = _read_yaml(project_root / ".cambrian" / "templates" / "qualification_decisions.yaml")
    assert decisions["decisions"][-1]["status"] == "dismissed"
    assert _library_decisions(project_root) == []
    assert not (project_root / ".cambrian" / "lane" / "playbook.yaml").exists()


def test_surface_and_recommend_use_lane_default_switch_weakly(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _saved_qualification(project_root)
    accept = _run_cli(
        ["template", "qualify-accept", qualification_ref, "--set-lane-default"],
        cwd=project_root,
    )
    assert accept.returncode == 0, accept.stderr

    show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    lineage = _run_cli(["template", "lineage", "auth-bug-template-local"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)
    harness = _run_cli(["harness", "show"], cwd=project_root)
    recommend = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert show.returncode == 0, show.stderr
    assert "Qualification decision:" in show.stdout
    assert "accepted" in show.stdout
    assert lineage.returncode == 0, lineage.stderr
    assert "Latest qualification decision:" in lineage.stdout
    assert status.returncode == 0, status.stderr
    assert "Strongest lane default template:" in status.stdout
    assert "auth-bug-template-local" in status.stdout
    assert harness.returncode == 0, harness.stderr
    assert "Lane playbook:" in harness.stdout
    assert recommend.returncode == 0, recommend.stderr
    candidates = {item["name"]: item for item in json.loads(recommend.stdout)["candidates"]}
    assert "selected as strongest-lane default via qualification" in candidates["auth-bug-template-local"]["reasons"]


def test_qualify_decisions_lists_and_source_immutability(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    before = _sha256(source)
    current_template = project_root / ".cambrian" / "templates" / "current_template.yaml"
    current_before = current_template.read_text(encoding="utf-8") if current_template.exists() else None
    qualification_ref = _saved_qualification(project_root)

    accept = _run_cli(["template", "qualify-accept", qualification_ref, "--set-lane-default"], cwd=project_root)
    decisions = _run_cli(["template", "qualify-decisions"], cwd=project_root)

    assert accept.returncode == 0, accept.stderr
    assert decisions.returncode == 0, decisions.stderr
    assert "Template Qualification Decisions" in decisions.stdout
    assert "auth-bug-template-local" in decisions.stdout
    assert _sha256(source) == before
    current_after = current_template.read_text(encoding="utf-8") if current_template.exists() else None
    assert current_after == current_before
