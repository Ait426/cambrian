from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def _create_waiting_task(tmp_path: Path) -> str:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    return str(json.loads(run_result.stdout)["task_refs"][0])


def _write_done_result(tmp_path: Path) -> Path:
    result_file = tmp_path / "done_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "done",
                "summary": "current bounded loop is complete",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "done",
                "evidence": {"notes": ["done gate verified"], "artifacts": []},
                "role_outputs": {
                    "scope": "current bounded loop",
                    "acceptance_criteria": ["loop can stop"],
                    "test_plan": ["python -m pytest"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return result_file


def test_done_result_stops_auto_loop_without_new_task(tmp_path: Path) -> None:
    task_ref = _create_waiting_task(tmp_path)
    result_file = _write_done_result(tmp_path)

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr
    ingest_payload = json.loads(ingest.stdout)
    assert ingest_payload["status"] == "done"
    assert ingest_payload["next_state"] == "VALIDATION"

    report = run_cli(tmp_path, "auto", "report", "--json")
    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["status"] == "auto_done"
    assert report_payload["decision_handoff"]["next_command"] is None

    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    assert boardroom.returncode == 0, boardroom.stderr
    boardroom_payload = json.loads(boardroom.stdout)
    assert boardroom_payload["auto_report_summary"]["handoff_status"] == "auto_done"
    assert boardroom_payload["recommended_next_action"] is None

    plan = run_cli(tmp_path, "auto", "plan", "--json")
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_kind"] == "done"
    assert plan_payload["steps"] == []
    assert plan_payload["next_command"] is None

    cycle = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")
    assert cycle.returncode == 0, cycle.stderr
    cycle_payload = json.loads(cycle.stdout)
    assert cycle_payload["plan_kind"] == "done"
    assert cycle_payload["executed_steps"] == 0
    assert cycle_payload["waiting_for_result"] == 0
    assert cycle_payload["task_refs"] == []
    assert cycle_payload["next_command"] is None

    status = run_cli(tmp_path, "auto", "status", "--json")
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["state"] == "DONE"


def test_auto_done_gate_doc_exists() -> None:
    doc = ROOT / "docs" / "product" / "32_AUTO_LOOP_DONE_GATE.md"
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in ["auto_done", "status: done", "no new task", "source code"]:
        assert phrase in text
    assert "32_AUTO_LOOP_DONE_GATE.md" in index
