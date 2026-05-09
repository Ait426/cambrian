from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from engine.project_harness_policy import HarnessPolicyOverlayBuilder, default_harness_policy_overlay_path
from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_harness_decisions(project_root: Path, *, dismissed: bool = False) -> None:
    status = "dismissed" if dismissed else "accepted"
    _write_yaml(
        project_root / ".cambrian" / "harness" / "decisions.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-04-25T00:00:00+00:00",
            "warnings": [],
            "errors": [],
            "decisions": [
                {
                    "decision_id": "decision-test-first",
                    "suggestion_id": "suggestion-test-first",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": None,
                    "status": status,
                    "kind": "strengthen_test_practice",
                    "target": None,
                    "title": "Strengthen test-first practice",
                    "summary": "strengthen test-first practice for auth work",
                    "resolution": None,
                    "source_report_ref": ".cambrian/harness/evolution_suggestions.yaml",
                    "evidence_refs": [],
                    "operational_effect": {"type": "none", "applied": False, "details": {}},
                    "tags": [],
                    "warnings": [],
                    "errors": [],
                },
                {
                    "decision_id": "decision-narrow",
                    "suggestion_id": "suggestion-narrow",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": None,
                    "status": status,
                    "kind": "narrow_change_scope",
                    "target": None,
                    "title": "Narrow change scope",
                    "summary": "keep scope narrow before broad refactor",
                    "resolution": None,
                    "source_report_ref": ".cambrian/harness/evolution_suggestions.yaml",
                    "evidence_refs": [],
                    "operational_effect": {"type": "none", "applied": False, "details": {}},
                    "tags": [],
                    "warnings": [],
                    "errors": [],
                },
                {
                    "decision_id": "decision-review-support",
                    "suggestion_id": "suggestion-review-support",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": None,
                    "status": status,
                    "kind": "increase_review_support",
                    "target": None,
                    "title": "Increase review support",
                    "summary": "review support preferred for risky auth changes",
                    "resolution": None,
                    "source_report_ref": ".cambrian/harness/evolution_suggestions.yaml",
                    "evidence_refs": [],
                    "operational_effect": {"type": "none", "applied": False, "details": {}},
                    "tags": [],
                    "warnings": [],
                    "errors": [],
                },
            ],
        },
    )


def _write_staffing_decisions(project_root: Path, *, dismissed: bool = False) -> None:
    status = "dismissed" if dismissed else "accepted"
    _write_yaml(
        project_root / ".cambrian" / "agents" / "staffing_decisions.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-04-25T00:00:00+00:00",
            "warnings": [],
            "errors": [],
            "decisions": [
                {
                    "decision_id": "staffing-prefer-lead",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": None,
                    "status": status,
                    "decision_kind": "prefer_lead",
                    "target_agent_id": "bug-fix-agent",
                    "source_kind": "built_in",
                    "title": "prefer lead bug-fix-agent",
                    "summary": "prefer_lead bug-fix-agent",
                    "resolution": None,
                    "source_ref": ".cambrian/agents/dispatch_board.yaml",
                    "source_type": "dispatch_board",
                    "evidence_refs": [],
                    "operational_effect": {"type": "none", "applied": False, "details": {}},
                    "warnings": [],
                    "errors": [],
                },
                {
                    "decision_id": "staffing-prefer-support",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": None,
                    "status": status,
                    "decision_kind": "prefer_support",
                    "target_agent_id": "review-agent",
                    "source_kind": "built_in",
                    "title": "prefer support review-agent",
                    "summary": "prefer_support review-agent",
                    "resolution": None,
                    "source_ref": ".cambrian/agents/dispatch_board.yaml",
                    "source_type": "dispatch_board",
                    "evidence_refs": [],
                    "operational_effect": {"type": "none", "applied": False, "details": {}},
                    "warnings": [],
                    "errors": [],
                },
                {
                    "decision_id": "staffing-backup",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": None,
                    "status": status,
                    "decision_kind": "keep_as_backup",
                    "target_agent_id": "docs-update-agent",
                    "source_kind": "built_in",
                    "title": "keep docs-update-agent as backup",
                    "summary": "keep_as_backup docs-update-agent",
                    "resolution": None,
                    "source_ref": ".cambrian/agents/trials/trial-demo.yaml",
                    "source_type": "agent_trial",
                    "evidence_refs": [],
                    "operational_effect": {"type": "none", "applied": False, "details": {}},
                    "warnings": [],
                    "errors": [],
                },
                {
                    "decision_id": "staffing-watch",
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": None,
                    "status": status,
                    "decision_kind": "watch_candidate",
                    "target_agent_id": "small-refactor-agent",
                    "source_kind": "built_in",
                    "title": "watch small-refactor-agent",
                    "summary": "watch_candidate small-refactor-agent",
                    "resolution": None,
                    "source_ref": ".cambrian/agents/trials/trial-demo.yaml",
                    "source_type": "agent_trial",
                    "evidence_refs": [],
                    "operational_effect": {"type": "none", "applied": False, "details": {}},
                    "warnings": [],
                    "errors": [],
                },
            ],
        },
    )


def test_build_overlay_from_accepted_decisions(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_harness_decisions(project_root)
    _write_staffing_decisions(project_root)

    overlay = HarnessPolicyOverlayBuilder().build(project_root)

    assert overlay.test_first_practice is True
    assert overlay.narrow_change_scope is True
    assert overlay.increase_review_support is True
    assert overlay.preferred_lead_agents == ["bug-fix-agent"]
    assert overlay.preferred_support_agents == ["review-agent"]
    assert overlay.backup_agents == ["docs-update-agent"]
    assert overlay.watched_agents == ["small-refactor-agent"]


def test_dismissed_decisions_are_ignored(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_harness_decisions(project_root, dismissed=True)
    _write_staffing_decisions(project_root, dismissed=True)

    overlay = HarnessPolicyOverlayBuilder().build(project_root)

    assert overlay.test_first_practice is False
    assert overlay.preferred_lead_agents == []
    assert overlay.preferred_support_agents == []
    assert overlay.accepted_decisions == []


def test_do_output_and_request_artifact_include_policy_context(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_harness_decisions(project_root)
    _write_staffing_decisions(project_root)

    proc = _run_cli(["do", "fix login bug"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert "Harness policy:" in proc.stdout
    assert "test-first" in proc.stdout
    assert "narrow" in proc.stdout
    request_path = sorted((project_root / ".cambrian" / "requests").glob("request_*.yaml"))[-1]
    payload = _read_yaml(request_path)
    policy_context = payload["harness_policy_context"]
    assert policy_context["enabled"] is True
    assert policy_context["policy_flags"]["test_first_practice"] is True
    assert policy_context["policy_flags"]["narrow_change_scope"] is True
    assert "review-agent" in policy_context["preferred_support_agents"]
    assert "docs-update-agent" in policy_context["backup_agents"]
    assert default_harness_policy_overlay_path(project_root).exists()


def test_do_routing_uses_preferred_lead_reason(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_staffing_decisions(project_root)

    proc = _run_cli(["do", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    routes = payload["agent_context"]["routes"]
    bug_fix = next(item for item in routes if item["agent_id"] == "bug-fix-agent")
    assert payload["agent_context"]["lead_agent_id"] == "bug-fix-agent"
    assert "accepted policy prefers this lead agent" in bug_fix["reasons"]


def test_review_support_policy_surfaces_support_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_harness_decisions(project_root)
    _write_staffing_decisions(project_root)

    proc = _run_cli(["do", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "review-agent" in payload["agent_context"]["supporting_agent_ids"]
    review_route = next(item for item in payload["agent_context"]["routes"] if item["agent_id"] == "review-agent")
    assert any("review support" in reason for reason in review_route["reasons"])


def test_status_and_harness_show_include_policy(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_harness_decisions(project_root)
    _write_staffing_decisions(project_root)

    status_proc = _run_cli(["status"], cwd=project_root)
    show_proc = _run_cli(["harness", "show"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Harness policy:" in status_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Harness policy:" in show_proc.stdout
    assert "preferred lead" in show_proc.stdout or "lead prefs" in show_proc.stdout


def test_continue_preserves_policy_context(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_harness_decisions(project_root)
    do_proc = _run_cli(["do", "fix login bug"], cwd=project_root)
    assert do_proc.returncode == 0, do_proc.stderr
    session_path = sorted((project_root / ".cambrian" / "sessions").glob("do_session_*.yaml"))[-1]
    session_payload = _read_yaml(session_path)

    continue_proc = _run_cli(["do", "continue placeholder", "--continue", "--session", session_payload["session_id"]], cwd=project_root)

    assert continue_proc.returncode == 0, continue_proc.stderr
    updated = _read_yaml(session_path)
    assert updated["harness_policy_context"]["enabled"] is True
    assert updated["harness_policy_context"]["policy_flags"]["test_first_practice"] is True


def test_harness_policy_does_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_harness_decisions(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["do", "fix login bug"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0
    assert _run_cli(["harness", "show"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
