from __future__ import annotations

import json
from pathlib import Path

from engine.project_template_bootstrap_select import (
    TemplateRecommendationBuilder,
    render_bootstrap_recommendation_prompt,
)
from test_agent_transfer import _read_yaml, _run_cli
from test_harness_templates import _write_yaml
from test_template_qualification import _prepare_project, _sha256


def _qualification_ref(project_root: Path) -> str:
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


def _set_verdict(project_root: Path, qualification_ref: str, verdict: str) -> None:
    path = project_root / qualification_ref
    payload = _read_yaml(path)
    payload["verdict"] = verdict
    _write_yaml(path, payload)


def test_stage_candidate_stronger_updates_canary_and_preserves_default(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _qualification_ref(project_root)

    proc = _run_cli(["template", "qualify-stage", qualification_ref, "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["stage"]["status"] == "active"
    assert payload["stage"]["candidate_template_name"] == "auth-bug-template-local"
    stages = _read_yaml(project_root / ".cambrian" / "templates" / "qualification_stages.yaml")
    playbook = _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")
    assert stages["active_stage_id"] == payload["stage"]["stage_id"]
    assert playbook["default_template_name"] is None
    assert playbook["canary_template_name"] == "auth-bug-template-local"
    assert playbook["canary_status"] == "active"


def test_non_candidate_stronger_blocked_without_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _qualification_ref(project_root)
    _set_verdict(project_root, qualification_ref, "mixed")

    proc = _run_cli(["template", "qualify-stage", qualification_ref], cwd=project_root)

    assert proc.returncode != 0
    assert "candidate_stronger" in proc.stderr
    assert not (project_root / ".cambrian" / "templates" / "qualification_stages.yaml").exists()


def test_force_allows_stage_with_warning(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _qualification_ref(project_root)
    _set_verdict(project_root, qualification_ref, "mixed")

    proc = _run_cli(["template", "qualify-stage", qualification_ref, "--force", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["stage"]["warnings"]
    assert "mixed" in payload["stage"]["warnings"][0]


def test_only_one_active_canary_allowed(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _qualification_ref(project_root)

    first = _run_cli(["template", "qualify-stage", qualification_ref], cwd=project_root)
    second = _run_cli(["template", "qualify-stage", qualification_ref], cwd=project_root)

    assert first.returncode == 0, first.stderr
    assert second.returncode != 0
    assert "already active" in second.stderr


def test_unstage_clears_canary_and_preserves_stable_default(tmp_path: Path) -> None:
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
            "backup_templates": [],
            "retired_templates": [],
            "source_decision_ref": None,
            "notes": [],
            "warnings": [],
            "errors": [],
        },
    )
    qualification_ref = _qualification_ref(project_root)
    staged = _run_cli(["template", "qualify-stage", qualification_ref], cwd=project_root)
    assert staged.returncode == 0, staged.stderr

    proc = _run_cli(
        ["template", "qualify-unstage", qualification_ref, "--resolution", "burn-in ended", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    playbook = _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")
    stages = _read_yaml(project_root / ".cambrian" / "templates" / "qualification_stages.yaml")
    assert playbook["default_template_name"] == "imported-auth-bug-template"
    assert playbook["canary_template_name"] is None
    assert stages["active_stage_id"] is None
    assert stages["stages"][-1]["status"] == "cleared"


def test_recommend_board_and_bootstrap_surface_canary_as_alternative(tmp_path: Path) -> None:
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
            "backup_templates": [],
            "retired_templates": [],
            "source_decision_ref": None,
            "notes": [],
            "warnings": [],
            "errors": [],
        },
    )
    qualification_ref = _qualification_ref(project_root)
    staged = _run_cli(["template", "qualify-stage", qualification_ref], cwd=project_root)
    assert staged.returncode == 0, staged.stderr

    recommend = _run_cli(["template", "recommend", "--json"], cwd=project_root)
    board = _run_cli(["template", "board", "--json"], cwd=project_root)
    prompt = render_bootstrap_recommendation_prompt(TemplateRecommendationBuilder().build(project_root))

    assert recommend.returncode == 0, recommend.stderr
    assert board.returncode == 0, board.stderr
    rec_payload = json.loads(recommend.stdout)
    canary = next(item for item in rec_payload["candidates"] if item["name"] == "auth-bug-template-local")
    default = next(item for item in rec_payload["candidates"] if item["name"] == "imported-auth-bug-template")
    assert "staged as lane canary after stronger qualification" in canary["reasons"]
    assert "selected as strongest-lane default via qualification" in default["reasons"]
    assert "(canary)" in prompt
    board_payload = json.loads(board.stdout)
    board_canary = next(item for item in board_payload["entries"] if item["template_name"] == "auth-bug-template-local")
    assert "staged as lane canary after stronger qualification" in board_canary["reasons"]


def test_show_lineage_status_harness_surface_canary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    qualification_ref = _qualification_ref(project_root)
    staged = _run_cli(["template", "qualify-stage", qualification_ref], cwd=project_root)
    assert staged.returncode == 0, staged.stderr

    canary = _run_cli(["template", "canary"], cwd=project_root)
    show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    lineage = _run_cli(["template", "lineage", "auth-bug-template-local"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)
    harness = _run_cli(["harness", "show"], cwd=project_root)

    assert canary.returncode == 0, canary.stderr
    assert show.returncode == 0, show.stderr
    assert lineage.returncode == 0, lineage.stderr
    assert status.returncode == 0, status.stderr
    assert harness.returncode == 0, harness.stderr
    assert "Canary" in canary.stdout
    assert "auth-bug-template-local" in canary.stdout
    assert "Canary status" in show.stdout
    assert "Canary status" in lineage.stdout
    assert "canary alternative" in status.stdout
    assert "canary template" in harness.stdout


def test_canary_source_immutability(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    before = _sha256(source)
    qualification_ref = _qualification_ref(project_root)

    stage = _run_cli(["template", "qualify-stage", qualification_ref], cwd=project_root)
    canary = _run_cli(["template", "canary"], cwd=project_root)
    unstage = _run_cli(["template", "qualify-unstage", qualification_ref], cwd=project_root)

    assert stage.returncode == 0, stage.stderr
    assert canary.returncode == 0, canary.stderr
    assert unstage.returncode == 0, unstage.stderr
    assert _sha256(source) == before
