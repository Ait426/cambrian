from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def _expected_os_task() -> dict[str, str]:
    backlog = (ROOT / "docs" / "product" / "45_AI_COMPANY_OS_TASK_BACKLOG.md").read_text(encoding="utf-8")
    pattern = re.compile(r"^### (OS-\d{2})\s+[^\n]+\n(?P<body>.*?)(?=^### OS-\d{2}\s+|\Z)", re.M | re.S)
    for match in pattern.finditer(backlog):
        if re.search(r"^status:\s*pending\s*$", match.group("body"), re.M):
            return {"id": match.group(1), "status": "pending", "selection_rule": "first_pending"}
    return {"id": "none", "status": "completed", "selection_rule": "no_pending"}


def test_auto_report_includes_mission_status(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "report", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    mission = payload["report"]["mission_status"]
    expected_next_task = _expected_os_task()
    assert mission["mission_kind"] == "auto_mission_control_v0_1"
    assert mission["final_goal"]
    assert mission["current_phase"] == "PRODUCT_CHARTER"
    assert mission["next_task"]["id"] == expected_next_task["id"]
    assert mission["next_task"]["status"] == expected_next_task["status"]
    assert mission["next_task"]["selection_rule"] == expected_next_task["selection_rule"]
    assert mission["completion_score"] < 100
    assert mission["completion_claim"]["can_claim_complete"] is False
    assert mission["completion_claim"]["requires_release_gate_go"] is True
    assert mission["evidence_status"] == "grounded"

    mission_path = tmp_path / mission["mission_ref"]
    assert mission_path.exists()
    saved_mission = yaml.safe_load(mission_path.read_text(encoding="utf-8"))
    assert saved_mission["final_goal"] == mission["final_goal"]
    assert saved_mission["next_task"]["id"] == expected_next_task["id"]


def test_auto_report_cautions_when_mission_evidence_is_missing(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "auto", "report", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    mission = payload["report"]["mission_status"]
    assert mission["status"] == "not_initialized"
    assert mission["evidence_status"] == "missing"
    assert mission["final_goal"] is None
    assert mission["completion_score"] == 0
    assert mission["completion_claim"]["can_claim_complete"] is False
    assert "auto mode is not initialized" in mission["blockers"]
    assert "mission final_goal is missing" in mission["blockers"]


def test_auto_boardroom_summary_carries_mission_status(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "boardroom", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    summary = payload["auto_report_summary"]
    expected_next_task = _expected_os_task()
    assert summary["mission_status"]["next_task"]["id"] == expected_next_task["id"]
    assert summary["mission_next_task"]["id"] == expected_next_task["id"]
    assert summary["mission_completion_score"] < 100
