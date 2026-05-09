from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def _create_task(tmp_path: Path) -> str:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    return str(json.loads(run_result.stdout)["task_refs"][0])


def _write_result(tmp_path: Path, payload: dict) -> Path:
    result_file = tmp_path / "release_result.yaml"
    result_file.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return result_file


def _strong_pm_result() -> dict:
    return {
        "status": "success",
        "summary": "release gate evidence is ready",
        "changed_files": [],
        "tests": [{"command": "python -m pytest tests/test_auto_release_gate.py", "status": "passed"}],
        "blockers": [],
        "next_action": "cambrian auto report --json",
        "evidence": {"notes": ["release evidence exists"], "artifacts": ["tests/test_auto_release_gate.py"]},
        "role_outputs": {
            "scope": "release gate evidence package",
            "acceptance_criteria": ["GO/NO-GO package is saved"],
            "test_plan": ["python -m pytest tests/test_auto_release_gate.py"],
        },
    }


def _usable_pm_result() -> dict:
    payload = _strong_pm_result()
    payload["evidence"] = {"notes": [], "artifacts": []}
    return payload


def _ingest(tmp_path: Path, payload: dict) -> dict:
    task_ref = _create_task(tmp_path)
    result_file = _write_result(tmp_path, payload)
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr
    return json.loads(ingest.stdout)


def test_auto_release_gate_creates_go_package_for_strong_result(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    plan = run_cli(tmp_path, "auto", "plan", "--json")
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["plan_kind"] == "release_gate"

    result = run_cli(tmp_path, "auto", "release-gate", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "GO"
    assert payload["quality_route"] == "release_gate"
    assert payload["source_code_modified"] is False
    assert all(payload["evidence_checklist"].values())
    gate_path = tmp_path / payload["release_gate_ref"]
    assert gate_path.exists()
    gate = yaml.safe_load(gate_path.read_text(encoding="utf-8"))
    assert gate["safety"]["automatic_release"] is False
    assert gate["verdict"] == "GO"


def test_release_gate_go_drives_next_iteration_handoff(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    gate = run_cli(tmp_path, "auto", "release-gate", "--json")
    assert gate.returncode == 0, gate.stderr
    assert json.loads(gate.stdout)["verdict"] == "GO"

    report = run_cli(tmp_path, "auto", "report", "--json")
    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["status"] == "release_gate_go"
    assert "auto next" in report_payload["decision_handoff"]["next_command"]
    assert boardroom.returncode == 0, boardroom.stderr
    boardroom_payload = json.loads(boardroom.stdout)
    assert boardroom_payload["auto_report_summary"]["release_gate_verdict"] == "GO"
    assert boardroom_payload["recommended_next_action"].startswith("cambrian auto next")
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_kind"] == "next_iteration"
    assert plan_payload["next_command"].startswith("cambrian auto next")
    status = run_cli(tmp_path, "auto", "status", "--json")
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout)
    assert status_payload["decision_handoff"]["status"] == "release_gate_go"
    assert status_payload["next_command"].startswith("cambrian auto next")
    run = run_cli(tmp_path, "auto", "run", "--max-steps", "5", "--json")
    assert run.returncode == 1
    run_payload = json.loads(run.stdout)
    assert run_payload["ok"] is False
    assert run_payload["plan_kind"] == "next_iteration"
    assert "next_iteration plan cannot be run" in run_payload["errors"][0]


def test_auto_release_gate_returns_conditional_go_when_release_plan_is_missing(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0

    result = run_cli(tmp_path, "auto", "release-gate", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "CONDITIONAL GO"
    assert "release gate plan" in payload["required_before_release"]
    assert payload["evidence_checklist"]["release_gate_plan"] is False


def test_conditional_release_gate_drives_cleanup_plan(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    gate = run_cli(tmp_path, "auto", "release-gate", "--json")
    assert gate.returncode == 0, gate.stderr
    assert json.loads(gate.stdout)["verdict"] == "CONDITIONAL GO"

    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert plan.returncode == 0, plan.stderr
    payload = json.loads(plan.stdout)
    assert payload["plan_kind"] == "conditional_release_review"
    assert payload["auto_report_summary"]["handoff_status"] == "release_gate_conditional_go"
    assert payload["steps"][0]["owner"] == "release-manager-agent"


def test_newer_release_cleanup_result_makes_old_conditional_gate_stale(tmp_path: Path) -> None:
    _ingest(tmp_path, _strong_pm_result())
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    gate = run_cli(tmp_path, "auto", "release-gate", "--json")
    assert gate.returncode == 0, gate.stderr
    assert json.loads(gate.stdout)["verdict"] == "CONDITIONAL GO"
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run.returncode == 0, run.stderr
    task_ref = json.loads(run.stdout)["task_refs"][0]
    result = _strong_pm_result()
    result["role_outputs"] = {
        "verdict": "conditional release cleanup resolved",
        "artifact_checklist": ["release-manager cleanup evidence exists"],
        "post_release_backlog": ["split long pytest runs in CI"],
    }
    result_file = _write_result(tmp_path, result)
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    report = run_cli(tmp_path, "auto", "report", "--json")
    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["status"] == "ready_for_release_or_next_plan"
    assert report_payload["decision_handoff"]["quality_route"] == "release_gate"
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    plan = run_cli(tmp_path, "auto", "plan", "--json")
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["plan_kind"] == "release_gate"


def test_auto_release_gate_returns_no_go_for_usable_result_without_evidence(tmp_path: Path) -> None:
    ingest = _ingest(tmp_path, _usable_pm_result())
    assert ingest["result_quality"]["status"] == "usable"
    assert run_cli(tmp_path, "auto", "report", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0

    result = run_cli(tmp_path, "auto", "release-gate", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "CONDITIONAL GO"
    assert payload["quality_route"] == "next_product_step"
    assert "quality route must be release_gate" in payload["required_before_release"]


def test_no_go_release_gate_drives_recovery_plan(tmp_path: Path) -> None:
    prepare_auto(tmp_path)
    gate = run_cli(tmp_path, "auto", "release-gate", "--json")
    assert gate.returncode == 0, gate.stderr
    assert json.loads(gate.stdout)["verdict"] == "NO-GO"

    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert plan.returncode == 0, plan.stderr
    payload = json.loads(plan.stdout)
    assert payload["plan_kind"] == "release_gate_recovery"
    assert payload["auto_report_summary"]["handoff_status"] == "release_gate_no_go"
    assert payload["steps"][0]["owner"] == "pm-agent"


def test_auto_release_gate_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "38_RELEASE_GATE_EVIDENCE_PACKAGE.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in ["auto release-gate", "GO", "CONDITIONAL GO", "NO-GO", "release_gate"]:
        assert phrase in text
    assert "docs/product/38_RELEASE_GATE_EVIDENCE_PACKAGE.md" in readme
    assert "38_RELEASE_GATE_EVIDENCE_PACKAGE.md" in index


def test_release_gate_decision_loop_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "39_RELEASE_GATE_DECISION_LOOP.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "release_gate_go",
        "release_gate_conditional_go",
        "release_gate_no_go",
        "next_iteration",
    ]:
        assert phrase in text
    assert "docs/product/39_RELEASE_GATE_DECISION_LOOP.md" in readme
    assert "39_RELEASE_GATE_DECISION_LOOP.md" in index
