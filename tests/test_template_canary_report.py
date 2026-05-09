from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_agent_transfer import _read_yaml, _run_cli
from test_harness_templates import _write_yaml
from test_template_canary import _qualification_ref, _set_verdict
from test_template_qualification import _prepare_project, _sha256


def _set_lane_default(project_root: Path, template_name: str = "imported-auth-bug-template") -> None:
    _write_yaml(
        project_root / ".cambrian" / "lane" / "playbook.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-04-30T00:00:00+00:00",
            "lane_id": "python-pytest-auth-bug-core",
            "label": "Python + pytest + auth/login bug fixes",
            "default_template_name": template_name,
            "backup_templates": [],
            "retired_templates": [],
            "canary_template_name": None,
            "canary_stage_id": None,
            "canary_status": None,
            "source_decision_ref": None,
            "notes": [],
            "warnings": [],
            "errors": [],
        },
    )


def _stage(project_root: Path, *, verdict: str = "candidate_stronger", force: bool = False) -> str:
    qualification_ref = _qualification_ref(project_root)
    if verdict != "candidate_stronger":
        _set_verdict(project_root, qualification_ref, verdict)
    command = ["template", "qualify-stage", qualification_ref]
    if force:
        command.append("--force")
    proc = _run_cli(command, cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    return qualification_ref


def _positive_retrospective(project_root: Path) -> None:
    proc = _run_cli(
        [
            "template",
            "retrospective",
            "auth-bug-template-local",
            "canary stayed better in repeated auth/login fixes",
            "--rating",
            "strong",
        ],
        cwd=project_root,
    )
    assert proc.returncode == 0, proc.stderr


def _iso(days_ago: int, seconds_offset: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago) + timedelta(seconds=seconds_offset)).isoformat()


def _canary_selected_outcome(project_root: Path, *, suffix: str, days_ago: int = 1) -> None:
    selected_at = _iso(days_ago, 0)
    _write_yaml(
        project_root / ".cambrian" / "templates" / "canary_events" / f"event_selected_{suffix}.yaml",
        {
            "schema_version": "1.0.0",
            "event_id": f"canary-event-selected-{suffix}",
            "created_at": selected_at,
            "template_name": "auth-bug-template-local",
            "template_id": "auth-bug-template-local",
            "lane_id": "python-pytest-auth-bug-core",
            "lane_label": "Python + pytest + auth/login bug fixes",
            "stable_default_template_name": "imported-auth-bug-template",
            "event_kind": "selected",
            "surface_kind": "bootstrap",
            "selection_result": "canary",
            "request": None,
            "workset_name": "auth-bug-workset",
            "mode": None,
            "source_ref": ".cambrian/templates/bootstrap_choice.yaml",
            "linked_bootstrap_choice_ref": ".cambrian/templates/bootstrap_choice.yaml",
            "linked_replay_ref": None,
            "linked_metrics_ref": None,
            "summary": "canary selected for promotion gate test",
            "warnings": [],
            "errors": [],
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "sessions" / f"do_session_canary_{suffix}.yaml",
        {
            "schema_version": "1.0.0",
            "session_id": f"canary-{suffix}",
            "created_at": _iso(days_ago, 60),
            "updated_at": _iso(days_ago, 60),
            "user_request": "fix auth login",
            "project_initialized": True,
            "intent": {},
            "selected_skills": [],
            "status": "patch_proposal_validated",
            "current_stage": "proposal_validated",
            "artifacts": {"session_path": f".cambrian/sessions/do_session_canary_{suffix}.yaml"},
            "summary": {},
            "next_actions": [],
            "template_context": {
                "name": "auth-bug-template-local",
                "template_name": "auth-bug-template-local",
                "template_selection_source": "bootstrap_selection",
            },
            "metrics_context": {
                "template_name": "auth-bug-template-local",
                "template_selection_source": "bootstrap_selection",
                "human_interventions": {"source_selected_manually": False},
                "results": {
                    "validated_proposal": True,
                    "adoption_succeeded": False,
                    "apply_tests_passed": True,
                },
                "validation_autonomy": True,
                "duration_seconds": 42.0,
                "milestones": {
                    "request_started_at": _iso(days_ago, 60),
                    "proposal_validated_at": _iso(days_ago, 90),
                    "applied_at": None,
                },
            },
            "warnings": [],
            "errors": [],
        },
    )


def test_canary_report_builds_from_active_stage(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)

    proc = _run_cli(["template", "canary-report", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["candidate_template_name"] == "auth-bug-template-local"
    assert payload["stable_default_template_name"] == "imported-auth-bug-template"
    assert payload["verdict"] in {"keep_canary", "promote_ready"}
    assert payload["signals"]


def test_canary_report_blocks_without_active_canary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)

    proc = _run_cli(["template", "canary-report"], cwd=project_root)

    assert proc.returncode != 0
    assert "qualify-stage" in proc.stderr or "canary" in proc.stderr


def test_promote_ready_verdict_with_positive_burn_in(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)
    _positive_retrospective(project_root)

    proc = _run_cli(["template", "canary-report", "--save", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "promote_ready"
    assert "saved_path" in payload
    assert (project_root / payload["saved_path"]).exists()


def test_keep_canary_verdict_for_positive_but_limited_data(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)

    proc = _run_cli(["template", "canary-report", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["verdict"] == "keep_canary"


def test_clear_canary_verdict_for_negative_qualification(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root, verdict="regressed", force=True)

    proc = _run_cli(["template", "canary-report", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "clear_canary"
    assert payload["next_actions"]
    assert "qualify-unstage" in payload["next_actions"][0]


def test_insufficient_data_verdict_for_forced_inconclusive_stage(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage(project_root, verdict="inconclusive", force=True)

    proc = _run_cli(["template", "canary-report", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["verdict"] == "insufficient_data"


def test_canary_promote_switches_lane_default_and_writes_adoption(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)
    _positive_retrospective(project_root)
    _canary_selected_outcome(project_root, suffix="a", days_ago=1)
    _canary_selected_outcome(project_root, suffix="b", days_ago=2)
    report = _run_cli(["template", "canary-report", "--save"], cwd=project_root)
    assert report.returncode == 0, report.stderr

    proc = _run_cli(["template", "canary-promote", "auth-bug-template-local", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    playbook = _read_yaml(project_root / ".cambrian" / "lane" / "playbook.yaml")
    stages = _read_yaml(project_root / ".cambrian" / "templates" / "qualification_stages.yaml")
    assert payload["status"] == "promoted"
    assert playbook["default_template_name"] == "auth-bug-template-local"
    assert playbook["canary_template_name"] is None
    assert stages["active_stage_id"] is None
    assert list((project_root / ".cambrian" / "templates" / "qualification_adoptions").glob("adoption_*.yaml"))


def test_keep_canary_blocks_promotion_without_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)
    report = _run_cli(["template", "canary-report", "--save"], cwd=project_root)
    assert report.returncode == 0, report.stderr

    proc = _run_cli(["template", "canary-promote", "auth-bug-template-local"], cwd=project_root)

    assert proc.returncode != 0
    assert "keep_canary" in proc.stderr
    assert "canary-review" in proc.stderr


def test_force_promote_allows_keep_canary_with_warning(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)
    _canary_selected_outcome(project_root, suffix="warming", days_ago=1)
    report = _run_cli(["template", "canary-report", "--save"], cwd=project_root)
    assert report.returncode == 0, report.stderr

    proc = _run_cli(["template", "canary-promote", "auth-bug-template-local", "--force", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["warnings"]
    assert "freshness" in payload["warnings"][0]


def test_clear_canary_blocks_promotion(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root, verdict="regressed", force=True)
    report = _run_cli(["template", "canary-report", "--save"], cwd=project_root)
    assert report.returncode == 0, report.stderr

    proc = _run_cli(["template", "canary-promote", "auth-bug-template-local", "--force"], cwd=project_root)

    assert proc.returncode != 0
    assert "clear_canary" in proc.stderr
    assert "qualify-unstage" in proc.stderr


def test_report_show_status_lineage_and_harness_surface_verdict(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)
    report = _run_cli(["template", "canary-report", "--save", "--json"], cwd=project_root)
    assert report.returncode == 0, report.stderr
    report_path = json.loads(report.stdout)["saved_path"]

    show_report = _run_cli(["template", "canary-report-show", report_path], cwd=project_root)
    template_show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    lineage = _run_cli(["template", "lineage", "auth-bug-template-local"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)
    harness = _run_cli(["harness", "show"], cwd=project_root)

    assert show_report.returncode == 0, show_report.stderr
    assert template_show.returncode == 0, template_show.stderr
    assert lineage.returncode == 0, lineage.stderr
    assert status.returncode == 0, status.stderr
    assert harness.returncode == 0, harness.stderr
    assert "Template Canary Report" in show_report.stdout
    assert "Canary burn-in" in template_show.stdout
    assert "Canary burn-in" in lineage.stdout
    assert "verdict: keep_canary" in status.stdout
    assert "Canary burn-in" in harness.stdout


def test_promote_ready_canary_strengthens_recommendation_reason(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)
    _positive_retrospective(project_root)
    report = _run_cli(["template", "canary-report", "--save"], cwd=project_root)
    assert report.returncode == 0, report.stderr

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    canary = next(item for item in payload["candidates"] if item["name"] == "auth-bug-template-local")
    assert "canary is promotion-ready in the strongest lane" in canary["reasons"]


def test_canary_report_source_immutability(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    _set_lane_default(project_root)
    before = _sha256(source)
    _stage(project_root)

    report = _run_cli(["template", "canary-report", "--save"], cwd=project_root)
    show = _run_cli(["template", "canary-report-show", ".cambrian/templates/latest_canary.yaml"], cwd=project_root)
    promote = _run_cli(["template", "canary-promote", "auth-bug-template-local"], cwd=project_root)

    assert report.returncode == 0, report.stderr
    assert show.returncode == 0, show.stderr
    assert promote.returncode != 0
    assert _sha256(source) == before
