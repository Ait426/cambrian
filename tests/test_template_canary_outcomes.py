from __future__ import annotations

import json
from pathlib import Path

from engine.project_template_bootstrap_select import TemplateBootstrapSelector, save_template_bootstrap_choice
from engine.project_template_canary_ledger import record_canary_template_apply
from test_agent_transfer import _run_cli
from test_harness_templates import _write_yaml
from test_template_canary_report import _set_lane_default, _stage
from test_template_qualification import _prepare_project, _sha256


def _stage_canary(project_root: Path) -> str:
    _set_lane_default(project_root)
    return _stage(project_root)


def _select_canary(project_root: Path) -> None:
    choice = TemplateBootstrapSelector().choose(
        project_root,
        recommended_template_name="imported-auth-bug-template",
        selected_template_name="auth-bug-template-local",
        use_recommended=False,
        skip_template=False,
        available_templates=["imported-auth-bug-template", "auth-bug-template-local"],
        considered_templates=["imported-auth-bug-template", "auth-bug-template-local"],
    )
    save_template_bootstrap_choice(project_root, choice)


def _write_session(
    project_root: Path,
    *,
    session_id: str = "do-canary",
    validated: bool = True,
    adopted: bool = False,
    regression_free: bool | None = True,
    human_intervention: bool = False,
    validation_autonomy: bool = True,
    duration_seconds: float = 42.0,
) -> Path:
    path = project_root / ".cambrian" / "sessions" / f"do_session_{session_id}.yaml"
    _write_yaml(
        path,
        {
            "schema_version": "1.0.0",
            "session_id": session_id,
            "created_at": "2999-01-01T00:00:00+00:00",
            "updated_at": "2999-01-01T00:00:00+00:00",
            "user_request": "fix auth login",
            "project_initialized": True,
            "intent": {},
            "selected_skills": [],
            "status": "patch_proposal_validated" if validated else "benchmark_replay",
            "current_stage": "proposal_validated" if validated else "diagnosed",
            "artifacts": {"session_path": f".cambrian/sessions/do_session_{session_id}.yaml"},
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
                "human_interventions": {"source_selected_manually": human_intervention},
                "results": {
                    "validated_proposal": validated,
                    "adoption_succeeded": adopted,
                    "apply_tests_passed": regression_free,
                },
                "validation_autonomy": validation_autonomy,
                "duration_seconds": duration_seconds,
                "milestones": {
                    "request_started_at": "2999-01-01T00:00:00+00:00",
                    "proposal_validated_at": "2999-01-01T00:00:42+00:00" if validated else None,
                    "applied_at": "2999-01-01T00:00:45+00:00" if adopted else None,
                },
            },
            "warnings": [],
            "errors": [],
        },
    )
    return path


def test_bootstrap_selection_links_to_session_outcome(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    _select_canary(project_root)
    _write_session(project_root, adopted=True)

    proc = _run_cli(["template", "canary-outcomes", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["counts"]["selected_with_outcome_count"] == 1
    assert payload["counts"]["selected_then_validated_count"] == 1
    assert payload["counts"]["selected_then_adopted_count"] == 1
    assert payload["ratios"]["selected_then_validated_rate"] == 1.0


def test_template_apply_links_to_session_outcome(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    record_canary_template_apply(project_root, "auth-bug-template-local")
    _write_session(project_root, session_id="do-apply", validated=True, validation_autonomy=True)

    proc = _run_cli(["template", "canary-links", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert any(link["selection_source_kind"] == "template_apply" for link in payload["links"])
    assert any(link["validated_proposal"] is True for link in payload["links"])


def test_replay_override_links_to_replay_outcome(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)

    qualify = _run_cli(
        ["template", "qualify", "auth-bug-template-local", "--workset", "auth-bug-workset", "--save"],
        cwd=project_root,
    )
    assert qualify.returncode == 0, qualify.stderr
    proc = _run_cli(["template", "canary-links", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    links = json.loads(proc.stdout)["links"]
    assert any(link["selection_source_kind"] == "replay_override" for link in links)
    assert any(link["outcome_kind"] == "replay_outcome" and link["validated_proposal"] is True for link in links)


def test_partial_link_when_outcome_missing(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    _select_canary(project_root)

    proc = _run_cli(["template", "canary-links", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    links = json.loads(proc.stdout)["links"]
    assert links
    assert links[0]["outcome_kind"] == "partial"
    assert links[0]["warnings"]


def test_summary_counts_and_rates_for_selected_outcomes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    _select_canary(project_root)
    _write_session(
        project_root,
        validated=True,
        adopted=False,
        regression_free=True,
        human_intervention=False,
        validation_autonomy=True,
        duration_seconds=30.0,
    )

    proc = _run_cli(["template", "canary-outcomes", "--save", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["counts"]["selected_count"] == 1
    assert payload["counts"]["selected_with_outcome_count"] == 1
    assert payload["counts"]["selected_then_regression_free_apply_count"] == 1
    assert payload["ratios"]["selected_validation_autonomy_rate"] == 1.0
    assert payload["ratios"]["selected_human_intervention_rate"] == 0.0
    assert payload["medians"]["selected_duration_seconds"] == 30.0
    assert (project_root / payload["saved_path"]).exists()


def test_canary_report_consumes_outcome_attribution_first(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    _select_canary(project_root)
    _write_session(project_root, validated=True)

    proc = _run_cli(["template", "canary-report", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["exposure_counts"]["selected_then_validated_count"] == 1
    assert any("selected canary usage reached validated proposal" in item for item in payload["why_promote"])


def test_status_template_show_and_canary_surface_outcome_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    _select_canary(project_root)
    _write_session(project_root, validated=True)

    status = _run_cli(["status"], cwd=project_root)
    show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    canary = _run_cli(["template", "canary"], cwd=project_root)

    assert status.returncode == 0, status.stderr
    assert show.returncode == 0, show.stderr
    assert canary.returncode == 0, canary.stderr
    assert "Canary outcomes" in status.stdout
    assert "Canary outcomes" in show.stdout
    assert "Canary outcomes" in canary.stdout


def test_canary_outcome_source_immutability(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    before = _sha256(source)
    _stage_canary(project_root)
    _select_canary(project_root)
    _write_session(project_root, validated=True)

    assert _run_cli(["template", "canary-outcomes"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "canary-links"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source) == before
