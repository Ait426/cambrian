from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_release_gate import _ingest, _strong_pm_result
from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def test_auto_cycle_runs_report_boardroom_plan_and_run(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["cycle_id"].startswith("auto-cycle-")
    assert payload["plan_kind"] == "default"
    assert payload["executed_steps"] == 1
    assert payload["waiting_for_result"] == 1
    assert payload["task_refs"]
    assert payload["directive_refs"]
    assert payload["source_code_modified"] is False
    assert payload["provider_api_called"] is False
    assert payload["next_command"].startswith("cambrian auto step ingest")

    cycle_path = tmp_path / payload["cycle_ref"]
    assert cycle_path.exists()
    cycle = yaml.safe_load(cycle_path.read_text(encoding="utf-8"))
    assert cycle["run"]["waiting_for_result"] == 1
    assert cycle["source_code_modified"] is False
    assert (tmp_path / ".cambrian" / "auto" / "report.yaml").exists()
    assert (tmp_path / ".cambrian" / "auto" / "plan.yaml").exists()
    cycle_state = yaml.safe_load((tmp_path / payload["cycle_state_ref"]).read_text(encoding="utf-8"))
    assert cycle_state["loop_kind"] == "auto_completion_loop_v0_1"
    assert cycle_state["latest_cycle_ref"] == payload["cycle_ref"]
    assert cycle_state["next_decision"]["status"] == "waiting_for_external_result"
    assert "input_required" in cycle_state["stop_conditions"]
    assert "release_gate_go" in cycle_state["stop_conditions"]


def test_auto_cycle_uses_recovery_plan_after_blocked_result(tmp_path: Path) -> None:
    prepare_auto(tmp_path)
    first_cycle = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")
    assert first_cycle.returncode == 0, first_cycle.stderr
    task_ref = json.loads(first_cycle.stdout)["task_refs"][0]
    result_file = tmp_path / "blocked_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "blocked by validation",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["validation failed"],
                "next_action": "cambrian auto boardroom --json",
                "evidence": {"notes": ["blocked"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    result = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["handoff_status"] == "needs_boardroom_review"
    assert payload["plan_kind"] == "recovery"
    assert payload["executed_steps"] == 1
    plan = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "plan.yaml").read_text(encoding="utf-8"))
    assert plan["plan_kind"] == "recovery"
    assert plan["company_ledger_guidance"]["next_step_focus"] == "resolve_unchecked_risk"
    assert "validation failed" in plan["company_ledger_guidance"]["unchecked_items"]
    assert "validation failed" in plan["steps"][0]["task"]
    assert "Company ledger requires resolving unchecked risk" in plan["steps"][0]["task"]
    assert any("unchecked risk addressed" in item for item in plan["steps"][0]["success_criteria"])


def test_auto_cycle_pauses_and_records_input_required_stop(tmp_path: Path) -> None:
    prepare_auto(tmp_path)
    first_cycle = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")
    assert first_cycle.returncode == 0, first_cycle.stderr
    task_ref = json.loads(first_cycle.stdout)["task_refs"][0]
    result_file = tmp_path / "input_required_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "human input is required to continue",
                "changed_files": [],
                "tests": [{"command": "manual validation", "status": "blocked"}],
                "blockers": ["required input: raw response status code is needed"],
                "required_input": [
                    {
                        "field": "raw_response_status",
                        "description": "Provide the minimal response status needed to continue.",
                        "example": {"raw_response_status": 200},
                    }
                ],
                "next_action": "wait for user input",
                "evidence": {"notes": ["input missing"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    result = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cycle_status"] == "stopped"
    assert payload["stop_condition"] == "input_required"
    assert payload["executed_steps"] == 0
    assert payload["next_command"] is None
    state = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "state.yaml").read_text(encoding="utf-8"))
    assert state["paused"] is True
    assert state["pause_reason"] == "input_required"
    assert state["input_required"]["required_inputs"][0]["field"] == "raw_response_status"
    cycle_state = yaml.safe_load((tmp_path / payload["cycle_state_ref"]).read_text(encoding="utf-8"))
    assert cycle_state["latest_status"] == "stopped"
    assert cycle_state["latest_stop_condition"] == "input_required"


def test_auto_cycle_stops_after_release_gate_go(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    gate = run_cli(tmp_path, "auto", "release-gate", "--json")
    assert gate.returncode == 0, gate.stderr
    assert json.loads(gate.stdout)["verdict"] == "GO"

    result = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cycle_status"] == "stopped"
    assert payload["stop_condition"] == "release_gate_go"
    assert payload["handoff_status"] == "release_gate_go"
    assert payload["executed_steps"] == 0
    assert payload["next_command"].startswith("cambrian auto next")
    cycle = yaml.safe_load((tmp_path / payload["cycle_ref"]).read_text(encoding="utf-8"))
    assert cycle["next_decision"]["stop_condition"] == "release_gate_go"


def test_auto_cycle_records_authority_required_stop_after_blocked_steps(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "authority", "init", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "init", "--goal", "verify bounded loop authority stop", "--json").returncode == 0

    result = run_cli(tmp_path, "auto", "cycle", "--max-steps", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cycle_status"] == "stopped"
    assert payload["stop_condition"] == "authority_required"
    assert payload["blocked_steps"]
    assert payload["next_decision"]["status"] == "authority_required"
    assert payload["next_command"] == "cambrian authority grant --mode full-authority --json"
    cycle_state = yaml.safe_load((tmp_path / payload["cycle_state_ref"]).read_text(encoding="utf-8"))
    assert cycle_state["latest_stop_condition"] == "authority_required"
    assert cycle_state["next_decision"]["blocked_steps"]


def test_auto_cycle_requires_auto_state(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["failed_step"] == "boardroom"
    assert payload["cycle_status"] == "blocked"
    assert (tmp_path / payload["cycle_ref"]).exists()
    assert payload["source_code_modified"] is False


def test_auto_cycle_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "30_AUTO_CYCLE_COMMAND.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto cycle",
        "report",
        "boardroom",
        "plan",
        "run",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/30_AUTO_CYCLE_COMMAND.md" in readme
    assert "30_AUTO_CYCLE_COMMAND.md" in index
