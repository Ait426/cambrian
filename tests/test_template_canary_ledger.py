from __future__ import annotations

import json
from pathlib import Path

from engine.project_template_bootstrap_select import TemplateBootstrapSelector, save_template_bootstrap_choice
from test_agent_transfer import _read_yaml, _run_cli
from test_template_canary_report import _set_lane_default, _stage
from test_template_qualification import _prepare_project, _sha256


def _event_payloads(project_root: Path) -> list[dict]:
    events_dir = project_root / ".cambrian" / "templates" / "canary_events"
    return [_read_yaml(path) for path in sorted(events_dir.glob("event_*.yaml"))]


def _event_kinds(project_root: Path) -> list[tuple[str, str]]:
    return [(payload["event_kind"], payload["surface_kind"]) for payload in _event_payloads(project_root)]


def _stage_canary(project_root: Path) -> str:
    _set_lane_default(project_root)
    return _stage(project_root)


def test_recommend_surface_records_canary_event(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)

    proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["canary_events"]
    assert ("surfaced", "recommend") in _event_kinds(project_root)


def test_bootstrap_shortlist_records_surfaced_event(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    choice = TemplateBootstrapSelector().choose(
        project_root,
        recommended_template_name="imported-auth-bug-template",
        selected_template_name=None,
        use_recommended=False,
        skip_template=True,
        available_templates=["imported-auth-bug-template", "auth-bug-template-local"],
        considered_templates=["imported-auth-bug-template", "auth-bug-template-local"],
    )

    save_template_bootstrap_choice(project_root, choice)

    assert ("surfaced", "bootstrap") in _event_kinds(project_root)


def test_bootstrap_selection_records_selected(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
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

    events = _event_payloads(project_root)
    assert ("selected", "bootstrap") in _event_kinds(project_root)
    selected = next(payload for payload in events if payload["event_kind"] == "selected")
    assert selected["selection_result"] == "canary"


def test_bootstrap_skip_records_skipped(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    choice = TemplateBootstrapSelector().choose(
        project_root,
        recommended_template_name="imported-auth-bug-template",
        selected_template_name="imported-auth-bug-template",
        use_recommended=False,
        skip_template=False,
        available_templates=["imported-auth-bug-template", "auth-bug-template-local"],
        considered_templates=["imported-auth-bug-template", "auth-bug-template-local"],
    )

    save_template_bootstrap_choice(project_root, choice)

    events = _event_payloads(project_root)
    assert ("skipped", "bootstrap") in _event_kinds(project_root)
    skipped = next(payload for payload in events if payload["event_kind"] == "skipped")
    assert skipped["selection_result"] == "stable_default"


def test_template_apply_records_applied_event(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    diff = _run_cli(["template", "diff", "auth-bug-template-local", "--save"], cwd=project_root)
    assert diff.returncode == 0, diff.stderr

    proc = _run_cli(["template", "apply", "auth-bug-template-local", "--force", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    assert ("applied", "manual_apply") in _event_kinds(project_root)


def test_replay_records_replayed_and_validated_events(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)

    proc = _run_cli(
        ["template", "qualify", "auth-bug-template-local", "--workset", "auth-bug-workset", "--save", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    kinds = _event_kinds(project_root)
    assert ("replayed", "replay") in kinds
    assert ("validated", "replay") in kinds


def test_ledger_aggregation_counts_and_rates(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0
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
    assert _run_cli(
        ["template", "qualify", "auth-bug-template-local", "--workset", "auth-bug-workset", "--save"],
        cwd=project_root,
    ).returncode == 0

    proc = _run_cli(["template", "canary-ledger", "--save", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["counts"]["surfaced_count"] >= 2
    assert payload["counts"]["selected_count"] == 1
    assert payload["counts"]["replay_count"] >= 1
    assert payload["counts"]["replay_validated_count"] >= 1
    assert payload["ratios"]["selection_rate"] is not None
    assert payload["ratios"]["replay_validated_rate"] is not None
    assert (project_root / payload["saved_path"]).exists()


def test_canary_report_consumes_ledger_backed_counts(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0
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

    proc = _run_cli(["template", "canary-report", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["exposure_counts"]["selected_count"] == 1
    assert any("ledger-backed" in signal["summary"] for signal in payload["signals"])


def test_canary_events_command_filters_raw_events(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0

    proc = _run_cli(["template", "canary-events", "--kind", "surfaced", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["events"]
    assert {event["event_kind"] for event in payload["events"]} == {"surfaced"}


def test_status_template_show_and_canary_surface_ledger_summary(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _prepare_project(project_root)
    _stage_canary(project_root)
    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0

    status = _run_cli(["status"], cwd=project_root)
    show = _run_cli(["template", "show", "auth-bug-template-local"], cwd=project_root)
    canary = _run_cli(["template", "canary"], cwd=project_root)

    assert status.returncode == 0, status.stderr
    assert show.returncode == 0, show.stderr
    assert canary.returncode == 0, canary.stderr
    assert "Canary ledger" in status.stdout
    assert "Canary ledger" in show.stdout
    assert "Canary ledger" in canary.stdout


def test_canary_ledger_source_immutability(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _prepare_project(project_root)
    before = _sha256(source)
    _stage_canary(project_root)

    assert _run_cli(["template", "recommend"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "canary-ledger"], cwd=project_root).returncode == 0
    assert _run_cli(["template", "canary-events"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source) == before
