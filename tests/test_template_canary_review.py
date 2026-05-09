from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_agent_transfer import _run_cli
from test_harness_templates import _write_yaml
from test_template_canary_report import _set_lane_default, _stage
from test_template_qualification import _prepare_project, _sha256


def _iso(days_ago: int, seconds_offset: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago) + timedelta(seconds=seconds_offset)).isoformat()


def _event(
    project_root: Path,
    *,
    event_id: str,
    created_at: str,
    event_kind: str = "selected",
    surface_kind: str = "bootstrap",
    selection_result: str | None = "canary",
) -> None:
    _write_yaml(
        project_root / ".cambrian" / "templates" / "canary_events" / f"event_{event_id}.yaml",
        {
            "schema_version": "1.0.0",
            "event_id": f"canary-event-{event_id}",
            "created_at": created_at,
            "template_name": "auth-bug-template-local",
            "template_id": "auth-bug-template-local",
            "lane_id": "python-pytest-auth-bug-core",
            "lane_label": "Python + pytest + auth/login bug fixes",
            "stable_default_template_name": "imported-auth-bug-template",
            "event_kind": event_kind,
            "surface_kind": surface_kind,
            "selection_result": selection_result,
            "request": None,
            "workset_name": "auth-bug-workset",
            "mode": None,
            "source_ref": ".cambrian/templates/bootstrap_choice.yaml",
            "linked_bootstrap_choice_ref": ".cambrian/templates/bootstrap_choice.yaml",
            "linked_replay_ref": None,
            "linked_metrics_ref": None,
            "summary": "canary selected for freshness review test",
            "warnings": [],
            "errors": [],
        },
    )


def _session(
    project_root: Path,
    *,
    session_id: str,
    created_at: str,
    validated: bool = True,
    adopted: bool = False,
    human_intervention: bool = False,
    validation_autonomy: bool = True,
) -> None:
    _write_yaml(
        project_root / ".cambrian" / "sessions" / f"do_session_{session_id}.yaml",
        {
            "schema_version": "1.0.0",
            "session_id": session_id,
            "created_at": created_at,
            "updated_at": created_at,
            "user_request": "fix auth login",
            "project_initialized": True,
            "intent": {},
            "selected_skills": [],
            "status": "patch_proposal_validated" if validated else "blocked",
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
                    "apply_tests_passed": validated,
                },
                "validation_autonomy": validation_autonomy,
                "duration_seconds": 42.0,
                "milestones": {
                    "request_started_at": created_at,
                    "proposal_validated_at": created_at if validated else None,
                    "applied_at": created_at if adopted else None,
                },
            },
            "warnings": [],
            "errors": [],
        },
    )


def _stage_project(project_root: Path) -> None:
    _prepare_project(project_root)
    _set_lane_default(project_root)
    _stage(project_root)


def _validated_selection(project_root: Path, *, suffix: str, days_ago: int, adopted: bool = False) -> None:
    selected_at = _iso(days_ago, 0)
    _event(project_root, event_id=f"selected-{suffix}", created_at=selected_at)
    _session(project_root, session_id=f"canary-{suffix}", created_at=_iso(days_ago, 60), adopted=adopted)


def _save_report(project_root: Path) -> dict:
    proc = _run_cli(["template", "canary-report", "--save", "--json"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_fresh_verdict_allows_promotion_gate(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="a", days_ago=1)
    _validated_selection(project_root, suffix="b", days_ago=2, adopted=True)
    _save_report(project_root)

    proc = _run_cli(["template", "canary-review", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["freshness_status"] == "fresh"
    assert payload["promotion_gate"] == "allow"
    assert payload["recent_counts"]["selected_then_validated_count_recent"] >= 2


def test_warming_verdict_warns_for_small_recent_volume(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="a", days_ago=1)
    _save_report(project_root)

    proc = _run_cli(["template", "canary-review", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["freshness_status"] == "warming"
    assert payload["promotion_gate"] == "warn"


def test_review_due_verdict_for_old_positive_history(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="old", days_ago=19)
    _save_report(project_root)

    proc = _run_cli(["template", "canary-review", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["freshness_status"] == "review_due"


def test_stale_verdict_blocks_old_evidence(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="stale", days_ago=25)
    _save_report(project_root)

    proc = _run_cli(["template", "canary-review", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["freshness_status"] == "stale"
    assert payload["promotion_gate"] == "block"


def test_expired_verdict_blocks_cold_canary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="expired", days_ago=40)
    _save_report(project_root)

    proc = _run_cli(["template", "canary-review", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["freshness_status"] == "expired"
    assert payload["promotion_gate"] == "block"


def test_insufficient_data_verdict_for_active_canary_without_outcomes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)

    proc = _run_cli(["template", "canary-review", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["freshness_status"] == "insufficient_data"
    assert payload["promotion_gate"] == "block"


def test_canary_promote_uses_review_gate(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="a", days_ago=1)
    _validated_selection(project_root, suffix="b", days_ago=2)
    _save_report(project_root)
    review = _run_cli(["template", "canary-review", "--save"], cwd=project_root)
    assert review.returncode == 0, review.stderr

    proc = _run_cli(["template", "canary-promote", "auth-bug-template-local", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["review"]["freshness_status"] == "fresh"


def test_warming_soft_blocks_without_force_and_allows_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="a", days_ago=1)
    _save_report(project_root)

    blocked = _run_cli(["template", "canary-promote", "auth-bug-template-local"], cwd=project_root)
    forced = _run_cli(["template", "canary-promote", "auth-bug-template-local", "--force", "--json"], cwd=project_root)

    assert blocked.returncode != 0
    assert "warming" in blocked.stderr
    assert forced.returncode == 0, forced.stderr
    assert json.loads(forced.stdout)["warnings"]


def test_stale_blocks_promotion_even_with_force(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="stale", days_ago=25)
    _save_report(project_root)

    proc = _run_cli(["template", "canary-promote", "auth-bug-template-local", "--force"], cwd=project_root)

    assert proc.returncode != 0
    assert "stale" in proc.stderr
    assert "canary-review" in proc.stderr


def test_status_show_canary_and_harness_surface_review(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _stage_project(project_root)
    _validated_selection(project_root, suffix="a", days_ago=1)
    _save_report(project_root)
    review = _run_cli(["template", "canary-review", "--save"], cwd=project_root)
    assert review.returncode == 0, review.stderr

    status = _run_cli(["status"], cwd=project_root)
    show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    canary = _run_cli(["template", "canary"], cwd=project_root)
    harness = _run_cli(["harness", "show"], cwd=project_root)

    assert status.returncode == 0, status.stderr
    assert show.returncode == 0, show.stderr
    assert canary.returncode == 0, canary.stderr
    assert harness.returncode == 0, harness.stderr
    assert "Canary review" in status.stdout
    assert "Canary review" in show.stdout
    assert "Canary review" in canary.stdout
    assert "Canary review" in harness.stdout


def test_canary_review_source_immutability(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    before = _sha256(source)
    _set_lane_default(project_root)
    _stage(project_root)
    _validated_selection(project_root, suffix="a", days_ago=1)

    review = _run_cli(["template", "canary-review", "--save"], cwd=project_root)
    show = _run_cli(["template", "canary-review-show", ".cambrian/templates/latest_canary_review.yaml"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)

    assert review.returncode == 0, review.stderr
    assert show.returncode == 0, show.stderr
    assert status.returncode == 0, status.stderr
    assert _sha256(source) == before
