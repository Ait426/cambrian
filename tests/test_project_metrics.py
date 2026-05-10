from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from engine.project_do import ProjectDoRunner
from engine.project_metrics import ProjectMetricsBuilder
from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_metrics_project(project_root: Path) -> None:
    _write_yaml(
        project_root / ".cambrian" / "project.yaml",
        {
            "project": {"name": "metrics-demo"},
            "ai_work": {"primary_use_cases": ["bug_fix"]},
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "requests" / "request_req-baseline.yaml",
        {
            "schema_version": "1.0.0",
            "request_id": "req-baseline",
            "created_at": "2026-04-20T00:00:00+00:00",
            "user_request": "fix login baseline",
            "metrics_context": {
                "request_class": "bug_fix",
                "request_started_at": "2026-04-20T00:00:00+00:00",
                "reused_context": {
                    "memory": False,
                    "harness_policy": False,
                    "team_policy": False,
                    "template": False,
                    "bridge": False,
                },
            },
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "requests" / "request_req-recent.yaml",
        {
            "schema_version": "1.0.0",
            "request_id": "req-recent",
            "created_at": "2026-04-21T00:00:00+00:00",
            "user_request": "fix login recent",
            "metrics_context": {
                "request_class": "bug_fix",
                "request_started_at": "2026-04-21T00:00:00+00:00",
                "reused_context": {
                    "memory": True,
                    "harness_policy": True,
                    "team_policy": False,
                    "template": True,
                    "bridge": False,
                },
            },
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "sessions" / "do_session_do-baseline.yaml",
        {
            "schema_version": "1.0.0",
            "session_id": "do-baseline",
            "created_at": "2026-04-20T00:01:00+00:00",
            "user_request": "fix login baseline",
            "status": "prepared",
            "current_stage": "diagnose_ready",
            "artifacts": {"request_path": ".cambrian/requests/request_req-baseline.yaml"},
            "agent_context": {"lead_agent_id": "bug-fix-agent"},
            "metrics_context": {
                "lead_agent_id": "bug-fix-agent",
                "final_lead_agent_id": "review-agent",
                "human_interventions": {
                    "source_selected_manually": True,
                    "test_selected_manually": False,
                    "old_text_overridden": False,
                    "new_text_overridden": False,
                    "explicit_agent_override": False,
                    "explicit_team_override": False,
                    "explicit_template_choice": False,
                },
                "milestones": {"request_started_at": "2026-04-20T00:00:00+00:00"},
                "results": {
                    "validated_proposal": False,
                    "adoption_succeeded": False,
                    "apply_tests_passed": False,
                },
            },
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "sessions" / "do_session_do-recent.yaml",
        {
            "schema_version": "1.0.0",
            "session_id": "do-recent",
            "created_at": "2026-04-21T00:01:00+00:00",
            "user_request": "fix login recent",
            "status": "adopted",
            "current_stage": "adopted",
            "artifacts": {"request_path": ".cambrian/requests/request_req-recent.yaml"},
            "agent_context": {"lead_agent_id": "bug-fix-agent"},
            "continuations": [{"action": "patch_proposal_validated"}],
            "metrics_context": {
                "lead_agent_id": "bug-fix-agent",
                "final_lead_agent_id": "bug-fix-agent",
                "validation_path": "continue",
                "human_interventions": {
                    "source_selected_manually": False,
                    "test_selected_manually": False,
                    "old_text_overridden": False,
                    "new_text_overridden": False,
                    "explicit_agent_override": False,
                    "explicit_team_override": False,
                    "explicit_template_choice": False,
                },
                "milestones": {
                    "request_started_at": "2026-04-21T00:00:00+00:00",
                    "proposal_validated_at": "2026-04-21T00:10:00+00:00",
                    "applied_at": "2026-04-21T00:20:00+00:00",
                },
                "results": {
                    "validated_proposal": True,
                    "adoption_succeeded": True,
                    "apply_tests_passed": True,
                },
            },
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "patches" / "patch_proposal_patch-1_auth.py.yaml",
        {
            "schema_version": "1.0.0",
            "proposal_id": "patch-1",
            "created_at": "2026-04-21T00:10:00+00:00",
            "user_request": "fix login recent",
            "proposal_status": "validated",
            "validation": {"attempted": True, "status": "passed"},
            "metrics_context": {
                "request_id": "req-recent",
                "proposal_validated_at": "2026-04-21T00:10:00+00:00",
                "validated_proposal": True,
            },
        },
    )
    _write_json(
        project_root / ".cambrian" / "adoptions" / "adoption_patch-1.json",
        {
            "schema_version": "1.0.0",
            "adoption_id": "adoption-1",
            "created_at": "2026-04-21T00:20:00+00:00",
            "proposal_id": "patch-1",
            "adoption_status": "adopted",
            "post_apply_tests": {"exit_code": 0, "failed": 0, "passed": 3},
            "metrics_context": {
                "request_id": "req-recent",
                "adoption_succeeded": True,
                "apply_tests_passed": True,
            },
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "templates" / "recommendation.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-21T00:00:00+00:00",
            "recommended_template_name": "auth-bug-template",
        },
    )
    _write_yaml(
        project_root / ".cambrian" / "templates" / "decisions.yaml",
        {
            "schema_version": "1.0.0",
            "decisions": [
                {
                    "created_at": "2026-04-21T00:00:00+00:00",
                    "template_name": "auth-bug-template",
                    "status": "accepted",
                }
            ],
        },
    )


def test_metrics_week_empty_project(tmp_path: Path) -> None:
    proc = _run_cli(
        ["metrics", "week", "--start", "2026-04-20", "--end", "2026-04-27", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["counts"]["total_requests"] == 0
    assert payload["summary"]["validated_proposal_rate"] is None
    assert payload["warnings"]


def test_metrics_week_calculates_core_kpis(tmp_path: Path) -> None:
    _seed_metrics_project(tmp_path)

    report = ProjectMetricsBuilder().build_week(tmp_path, start="2026-04-20", end="2026-04-27")

    assert report.counts["total_requests"] == 2
    assert report.counts["validated_requests"] == 1
    assert report.summary["validated_proposal_rate"] == 0.5
    assert report.summary["adoption_rate"] == 1.0
    assert report.summary["regression_free_apply_rate"] == 1.0
    assert report.summary["median_time_to_validated_proposal"] == 600.0
    assert report.summary["human_intervention_rate"] == 0.5
    assert report.summary["validation_autonomy_rate"] == 0.5
    assert report.summary["lead_agent_hit_rate"] == 0.5
    assert report.summary["team_template_recommendation_hit_rate"] == 1.0
    assert report.summary["reuse_lift"] == 1.0
    assert report.summary["repeat_task_improvement_rate"] == 1.0


def test_metrics_week_save_and_status_summary(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    _seed_metrics_project(tmp_path)

    proc = _run_cli(
        ["metrics", "week", "--start", "2026-04-20", "--end", "2026-04-27", "--save", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    saved_path = Path(payload["saved_path"])
    assert saved_path.exists()
    assert (tmp_path / ".cambrian" / "metrics" / "latest.yaml").exists()

    status_proc = _run_cli(["status"], cwd=tmp_path)
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Weekly metrics" in status_proc.stdout


def test_do_artifacts_include_metrics_context(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)

    session = ProjectDoRunner().run("fix login bug", tmp_path, {})

    assert session.metrics_context["milestones"]["request_started_at"]
    assert "human_interventions" in session.metrics_context
    request_path = tmp_path / session.artifacts["request_path"]
    request_payload = _read_yaml(request_path)
    assert request_payload["metrics_context"]["request_class"] in {"bug_fix", "unknown"}
    assert "reused_context" in request_payload["metrics_context"]


def test_metrics_save_does_not_mutate_source_files(tmp_path: Path) -> None:
    _seed_metrics_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def login():\n    return True\n", encoding="utf-8")
    before = _sha256(source_path)

    proc = _run_cli(
        ["metrics", "week", "--start", "2026-04-20", "--end", "2026-04-27", "--save"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    assert _sha256(source_path) == before
