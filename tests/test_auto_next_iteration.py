from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_done_gate import _create_waiting_task, _write_done_result
from tests.test_auto_release_gate import _ingest, _strong_pm_result
from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def _prepare_done_loop(tmp_path: Path) -> None:
    task_ref = _create_waiting_task(tmp_path)
    result_file = _write_done_result(tmp_path)
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr
    cycle = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")
    assert cycle.returncode == 0, cycle.stderr
    assert json.loads(cycle.stdout)["plan_kind"] == "done"


def test_auto_next_archives_done_loop_and_starts_new_goal(tmp_path: Path) -> None:
    _prepare_done_loop(tmp_path)

    result = run_cli(tmp_path, "auto", "next", "--goal", "build the next bounded product step", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "next_iteration_started"
    assert payload["state"] == "PRODUCT_CHARTER"
    assert payload["goal"] == "build the next bounded product step"
    assert payload["previous_handoff_status"] == "auto_done"
    assert payload["source_code_modified"] is False
    assert payload["provider_api_called"] is False
    assert payload["iteration_ref"].endswith("iteration.yaml")
    assert payload["archived_refs"]

    state = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "state.yaml").read_text(encoding="utf-8"))
    assert state["goal"] == "build the next bounded product step"
    assert state["previous_goal"]
    assert state["state"] == "PRODUCT_CHARTER"
    assert state["previous_iteration_archive"]

    iteration = yaml.safe_load((tmp_path / payload["iteration_ref"]).read_text(encoding="utf-8"))
    assert iteration["previous_handoff_status"] == "auto_done"
    assert iteration["previous_report_summary"]["handoff_status"] == "auto_done"
    assert iteration["source_code_modified"] is False

    report = run_cli(tmp_path, "auto", "report", "--json")
    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["status"] == "ready_for_auto_run"


def test_auto_next_allows_new_cycle_after_done_archive(tmp_path: Path) -> None:
    _prepare_done_loop(tmp_path)
    next_goal = "verify explicit next goal contract"
    next_result = run_cli(tmp_path, "auto", "next", "--goal", next_goal, "--json")
    assert next_result.returncode == 0, next_result.stderr

    cycle = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")

    assert cycle.returncode == 0, cycle.stderr
    payload = json.loads(cycle.stdout)
    assert payload["ok"] is True
    assert payload["plan_kind"] == "default"
    assert payload["executed_steps"] == 1
    assert payload["waiting_for_result"] == 1
    assert payload["task_refs"]
    task = yaml.safe_load((tmp_path / payload["task_refs"][0]).read_text(encoding="utf-8"))
    assert task["goal"] == next_goal


def test_auto_next_archives_release_gate_go_and_starts_fresh_loop(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    gate = run_cli(tmp_path, "auto", "release-gate", "--json")
    assert gate.returncode == 0, gate.stderr
    gate_payload = json.loads(gate.stdout)
    assert gate_payload["verdict"] == "GO"
    assert (tmp_path / gate_payload["release_gate_ref"]).exists()

    result = run_cli(tmp_path, "auto", "next", "--goal", "verify release gate fresh-start contract", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["previous_handoff_status"] == "release_gate_go"
    assert payload["previous_release_gate_verdict"] == "GO"
    assert payload["archive_manifest"]["release_gate_archived"] is True
    assert payload["archive_manifest"]["previous_release_gate_verdict"] == "GO"
    assert not (tmp_path / ".cambrian" / "auto" / "release_gate").exists()

    iteration = yaml.safe_load((tmp_path / payload["iteration_ref"]).read_text(encoding="utf-8"))
    assert iteration["previous_release_gate"]["verdict"] == "GO"
    assert iteration["archive_manifest"]["release_gate_archived"] is True
    assert iteration["fresh_start_contract"]["active_release_gate_cleared"] is True

    report = run_cli(tmp_path, "auto", "report", "--json")
    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["status"] == "ready_for_auto_run"
    assert report_payload.get("release_gate", {}) == {}


def test_auto_next_rejects_placeholder_goal_after_release_gate_go(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    gate = run_cli(tmp_path, "auto", "release-gate", "--json")
    assert gate.returncode == 0, gate.stderr

    result = run_cli(tmp_path, "auto", "next", "--goal", "Next product iteration", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert "explicit next product goal is required" in payload["errors"]
    assert payload["rejected_goal"] == "Next product iteration"
    assert payload["current_handoff_status"] == "release_gate_go"
    assert payload["next_command"] == 'cambrian auto next --goal "명시적 다음 제품 목표" --json'
    assert payload["goal_examples"]


def test_auto_next_requires_done_or_release_gate_go(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "next", "--goal", "should not start yet", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "auto next requires auto_done or release_gate_go" in payload["errors"]
    assert payload["current_handoff_status"] == "ready_for_auto_run"


def test_auto_next_requires_existing_auto_state(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "auto", "next", "--goal", "new goal", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "auto state is missing" in payload["errors"]


def test_auto_next_iteration_doc_exists() -> None:
    doc = ROOT / "docs" / "product" / "33_AUTO_NEXT_ITERATION_GATE.md"
    fresh_doc = ROOT / "docs" / "product" / "40_AUTO_ITERATION_ARCHIVE_FRESH_START.md"
    explicit_doc = ROOT / "docs" / "product" / "41_EXPLICIT_NEXT_GOAL_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in ["cambrian auto next", "previous evidence", "new goal", "source code", "release_gate_go"]:
        assert phrase in text
    assert fresh_doc.exists()
    fresh_text = fresh_doc.read_text(encoding="utf-8")
    for phrase in ["release_gate_go", "fresh-start contract", "CONDITIONAL GO", "NO-GO"]:
        assert phrase in fresh_text
    assert explicit_doc.exists()
    explicit_text = explicit_doc.read_text(encoding="utf-8")
    for phrase in ["explicit next product goal", "Next product iteration", "release_gate_go", "auto next"]:
        assert phrase in explicit_text
    assert "33_AUTO_NEXT_ITERATION_GATE.md" in index
    assert "40_AUTO_ITERATION_ARCHIVE_FRESH_START.md" in index
    assert "41_EXPLICIT_NEXT_GOAL_CONTRACT.md" in index
    assert "docs/product/40_AUTO_ITERATION_ARCHIVE_FRESH_START.md" in readme
    assert "docs/product/41_EXPLICIT_NEXT_GOAL_CONTRACT.md" in readme
