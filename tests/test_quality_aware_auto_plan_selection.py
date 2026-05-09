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


def _write_result(tmp_path: Path, name: str, payload: dict) -> Path:
    result_file = tmp_path / name
    result_file.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return result_file


def _pm_result(*, evidence: dict, tests: list[dict]) -> dict:
    return {
        "status": "success",
        "summary": "role-specific result is ready for quality-aware planning",
        "changed_files": [],
        "tests": tests,
        "blockers": [],
        "next_action": "cambrian auto report --json",
        "evidence": evidence,
        "role_outputs": {
            "scope": "quality-aware auto plan selection",
            "acceptance_criteria": ["plan route follows result quality"],
            "test_plan": ["python -m pytest tests/test_quality_aware_auto_plan_selection.py"],
        },
    }


def _ingest_result(tmp_path: Path, payload: dict) -> dict:
    task_ref = _create_task(tmp_path)
    result_file = _write_result(tmp_path, "step_result.yaml", payload)
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr
    return json.loads(ingest.stdout)


def test_strong_quality_result_selects_release_gate_plan(tmp_path: Path) -> None:
    _ingest_result(
        tmp_path,
        _pm_result(
            evidence={"notes": ["release evidence exists"], "artifacts": ["docs/product/36_AUTO_RESULT_QUALITY_SCORING.md"]},
            tests=[{"command": "python -m pytest tests/test_quality_aware_auto_plan_selection.py", "status": "passed"}],
        ),
    )

    report = run_cli(tmp_path, "auto", "report", "--json")
    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["quality_route"] == "release_gate"
    assert boardroom.returncode == 0, boardroom.stderr
    boardroom_payload = json.loads(boardroom.stdout)
    assert boardroom_payload["auto_report_summary"]["quality_route"] == "release_gate"
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_kind"] == "release_gate"
    assert plan_payload["steps"][0]["owner"] == "release-manager-agent"
    assert plan_payload["steps"][0]["quality_route"] == "release_gate"


def test_usable_quality_result_selects_next_product_step_plan(tmp_path: Path) -> None:
    ingest_payload = _ingest_result(
        tmp_path,
        _pm_result(
            evidence={"notes": [], "artifacts": []},
            tests=[{"command": "python -m pytest tests/test_quality_aware_auto_plan_selection.py", "status": "passed"}],
        ),
    )
    assert ingest_payload["result_quality"]["status"] == "usable"

    report = run_cli(tmp_path, "auto", "report", "--json")
    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["quality_route"] == "next_product_step"
    assert boardroom.returncode == 0, boardroom.stderr
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_kind"] == "next_product_step"
    assert plan_payload["auto_report_summary"]["quality_route"] == "next_product_step"
    assert plan_payload["steps"][0]["owner"] == "pm-agent"
    assert plan_payload["steps"][0]["quality_route"] == "next_product_step"


def test_quality_aware_auto_plan_selection_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "quality_route",
        "release_gate",
        "next_product_step",
        "quality_review",
    ]:
        assert phrase in text
    assert "docs/product/37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md" in readme
    assert "37_QUALITY_AWARE_AUTO_PLAN_SELECTION.md" in index
