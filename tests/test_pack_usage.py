from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_usage import (
    PackOutcomeLinkBuilder,
    PackUsageSummaryBuilder,
    default_usage_events_dir,
    record_pack_usage_event,
)
from test_benchmark_replay import _seed_auth_project


ROOT = Path(__file__).resolve().parents[1]


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _install_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _activate_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _events(tmp_path: Path) -> list[dict]:
    paths = sorted((tmp_path / ".cambrian" / "packs" / "usage" / "events").glob("event_*.yaml"))
    return [_read_yaml(path) for path in paths]


def _event_with_surface(tmp_path: Path, surface_kind: str) -> dict:
    matches = [event for event in _events(tmp_path) if event.get("surface_kind") == surface_kind]
    assert matches, f"missing usage event for {surface_kind}"
    return matches[-1]


def _write_session(project_root: Path, *, validated: bool = True) -> str:
    session_ref = ".cambrian/sessions/do_session_do-test.yaml"
    path = project_root / session_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "session_id": "do-test",
                "created_at": "2026-05-03T00:00:00+00:00",
                "updated_at": "2026-05-03T00:02:00+00:00",
                "user_request": "fix auth login",
                "status": "ready",
                "current_stage": "patch_proposal_validated" if validated else "diagnosed",
                "artifacts": {"patch_proposal_path": ".cambrian/proposals/proposal.yaml"},
                "metrics_context": {
                    "active_pack_id": "auth-bug-core",
                    "active_pack_ref": "auth-bug-core@0.1.0",
                    "results": {
                        "validated_proposal": validated,
                        "adoption_succeeded": True,
                        "apply_tests_passed": True,
                    },
                    "human_interventions": {
                        "source_selected_manually": False,
                        "test_selected_manually": False,
                    },
                    "milestones": {
                        "request_started_at": "2026-05-03T00:00:00+00:00",
                        "proposal_validated_at": "2026-05-03T00:02:00+00:00",
                    },
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return session_ref


def test_activation_records_usage_event(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    event = _event_with_surface(tmp_path, "pack_active")

    assert event["event_kind"] == "activated"
    assert event["pack_id"] == "auth-bug-core"
    assert event["active_team"] == "auth-bug-team"


def test_bridge_prepare_records_usage_event(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "bridge", "prepare", "fix auth login", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    event = _event_with_surface(tmp_path, "bridge_prepare")

    assert event["event_kind"] == "used"
    assert event["linked_bridge_packet_ref"] == payload["saved_path"]
    assert event["request"] == "fix auth login"


def test_do_records_usage_event_and_metrics_context(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    init = _cli(tmp_path, "init", "--non-interactive")
    assert init.returncode == 0, init.stderr

    result = _cli(tmp_path, "do", "fix auth login")
    assert result.returncode == 0, result.stderr
    event = _event_with_surface(tmp_path, "do")
    session_path = tmp_path / str(event["linked_session_ref"])
    session = _read_yaml(session_path)

    assert event["event_kind"] == "used"
    assert event["linked_session_id"] == session["session_id"]
    assert session["metrics_context"]["active_pack_id"] == "auth-bug-core"
    assert session["metrics_context"]["reused_context"]["pack"] is True


def test_continue_records_usage_event(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    init = _cli(tmp_path, "init", "--non-interactive")
    assert init.returncode == 0, init.stderr
    do_result = _cli(tmp_path, "do", "fix auth login", "--json")
    assert do_result.returncode == 0, do_result.stderr
    session_id = json.loads(do_result.stdout)["session_id"]

    result = _cli(tmp_path, "do", "--continue", "--session", session_id, "--json")
    assert result.returncode == 0, result.stderr
    event = _event_with_surface(tmp_path, "continue")

    assert event["event_kind"] == "used"
    assert event["linked_session_id"] == session_id


def test_benchmark_replay_records_pack_usage_event(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _seed_auth_project(tmp_path, bridge=True)

    result = _cli(tmp_path, "benchmark", "replay", "login-bug", "--mode", "cambrian_full", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    event = _event_with_surface(tmp_path, "benchmark_replay")

    assert event["event_kind"] == "benchmark_used"
    assert (tmp_path / event["linked_benchmark_replay_ref"]).resolve() == Path(payload["saved_path"]).resolve()
    assert (tmp_path / event["linked_benchmark_result_ref"]).resolve() == Path(payload["result_path"]).resolve()


def test_outcome_link_from_session_and_summary_rates(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    session_ref = _write_session(tmp_path)
    record_pack_usage_event(
        tmp_path,
        event_kind="used",
        surface_kind="do",
        request="fix auth login",
        request_class="bug_fix",
        linked_session_id="do-test",
        linked_session_ref=session_ref,
    )

    links = PackOutcomeLinkBuilder().build_links(tmp_path, "auth-bug-core")
    linked = [link for link in links if link.outcome_source_kind == "session"]
    summary = PackUsageSummaryBuilder().build(tmp_path, "auth-bug-core")

    assert linked
    assert linked[0].validated_proposal is True
    assert linked[0].adoption_succeeded is True
    assert linked[0].regression_free_apply is True
    assert summary.counts["outcome_linked_count"] == 1
    assert summary.counts["validated_proposal_count"] == 1
    assert summary.rates["validated_proposal_rate"] == 1.0
    assert summary.rates["human_intervention_rate"] == 0.0
    assert summary.rates["validation_autonomy_rate"] == 1.0
    assert summary.medians["time_to_validated_proposal_seconds"] == 120.0


def test_partial_link_when_outcome_source_missing(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    record_pack_usage_event(
        tmp_path,
        event_kind="used",
        surface_kind="do",
        request="fix auth login",
        request_class="bug_fix",
        linked_session_id="missing",
        linked_session_ref=".cambrian/sessions/missing.yaml",
    )

    links = PackOutcomeLinkBuilder().build_links(tmp_path, "auth-bug-core")
    partial = [link for link in links if link.outcome_source_kind == "partial"]
    summary = PackUsageSummaryBuilder().build(tmp_path, "auth-bug-core")

    assert partial
    assert partial[0].warnings
    assert summary.counts["used_count"] == 1
    assert summary.counts["outcome_linked_count"] == 0
    assert summary.rates["validated_proposal_rate"] is None


def test_pack_usage_events_and_outcomes_cli(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    session_ref = _write_session(tmp_path)
    record_pack_usage_event(
        tmp_path,
        event_kind="used",
        surface_kind="do",
        linked_session_id="do-test",
        linked_session_ref=session_ref,
    )

    usage = _cli(tmp_path, "pack", "usage", "auth-bug-core", "--save")
    events = _cli(tmp_path, "pack", "events", "auth-bug-core", "--kind", "used")
    outcomes = _cli(tmp_path, "pack", "outcomes", "auth-bug-core", "--save")

    assert usage.returncode == 0, usage.stderr
    assert "Pack Usage" in usage.stdout
    assert "Validated proposals:" in usage.stdout
    assert events.returncode == 0, events.stderr
    assert "used in do" in events.stdout
    assert outcomes.returncode == 0, outcomes.stderr
    assert "Pack Outcomes" in outcomes.stdout
    assert "Validated proposal rate:" in outcomes.stdout
    assert (tmp_path / ".cambrian" / "packs" / "usage" / "latest.yaml").exists()


def test_pack_show_and_status_surface_usage_summary(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    session_ref = _write_session(tmp_path)
    record_pack_usage_event(
        tmp_path,
        event_kind="used",
        surface_kind="do",
        linked_session_id="do-test",
        linked_session_ref=session_ref,
    )

    show = _cli(tmp_path, "pack", "show", "auth-bug-core")
    status = _cli(tmp_path, "status")

    assert show.returncode == 0, show.stderr
    assert "Local usage:" in show.stdout
    assert "1 validated / 1 linked uses" in show.stdout
    assert status.returncode == 0, status.stderr
    assert "Active pack:" in status.stdout
    assert "Local usage:" in status.stdout


def test_usage_surfaces_do_not_mutate_project_source_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")

    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    assert _cli(tmp_path, "pack", "usage").returncode == 0
    assert _cli(tmp_path, "pack", "events").returncode == 0
    assert _cli(tmp_path, "pack", "outcomes", "auth-bug-core").returncode == 0
    assert _cli(tmp_path, "status").returncode == 0

    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
    assert default_usage_events_dir(tmp_path).exists()
