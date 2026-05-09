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
    path = tmp_path / name
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _strong_pm_result() -> dict:
    return {
        "status": "success",
        "summary": "역할별 산출물과 검증 증거를 제출했다.",
        "changed_files": [],
        "tests": [{"command": "python -m pytest tests/test_auto_result_quality_scoring.py", "status": "passed"}],
        "blockers": [],
        "next_action": "cambrian auto report --json",
        "evidence": {"notes": ["역할별 산출물 검증"], "artifacts": []},
        "role_outputs": {
            "scope": "auto result quality scoring",
            "acceptance_criteria": ["quality score is recorded"],
            "test_plan": ["python -m pytest tests/test_auto_result_quality_scoring.py"],
        },
    }


def test_ingest_records_result_quality_score(tmp_path: Path) -> None:
    task_ref = _create_task(tmp_path)
    result_file = _write_result(tmp_path, "strong_result.yaml", _strong_pm_result())

    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")

    assert ingest.returncode == 0, ingest.stderr
    payload = json.loads(ingest.stdout)
    assert payload["result_quality"]["score"] >= 80
    assert payload["result_quality"]["status"] in {"usable", "strong"}
    task = yaml.safe_load((tmp_path / task_ref).read_text(encoding="utf-8"))
    assert task["result_quality"]["score"] == payload["result_quality"]["score"]
    result_record = yaml.safe_load((tmp_path / payload["result_ref"]).read_text(encoding="utf-8"))
    assert result_record["result_quality"]["threshold"] == 80


def test_auto_report_summarizes_result_quality(tmp_path: Path) -> None:
    task_ref = _create_task(tmp_path)
    result_file = _write_result(tmp_path, "strong_result.yaml", _strong_pm_result())
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    report = run_cli(tmp_path, "auto", "report", "--json")

    assert report.returncode == 0, report.stderr
    payload = json.loads(report.stdout)
    step_results = payload["report"]["step_results"]
    assert step_results["quality_average"] >= 80
    assert step_results["quality_threshold"] == 80
    assert step_results["low_quality"] == 0
    assert payload["decision_handoff"]["status"] == "ready_for_release_or_next_plan"


def test_low_quality_validated_result_goes_to_quality_review(tmp_path: Path) -> None:
    task_ref = _create_task(tmp_path)
    weak_result = _strong_pm_result()
    weak_result["tests"] = []
    weak_result["evidence"] = {"notes": [], "artifacts": []}
    weak_result["validation"] = {"status": "passed"}
    result_file = _write_result(tmp_path, "weak_result.yaml", weak_result)
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr
    assert json.loads(ingest.stdout)["status"] == "validated"

    report = run_cli(tmp_path, "auto", "report", "--json")
    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert report.returncode == 0, report.stderr
    report_payload = json.loads(report.stdout)
    assert report_payload["decision_handoff"]["status"] == "needs_result_quality_review"
    assert report_payload["report"]["step_results"]["low_quality"] == 1
    assert boardroom.returncode == 0, boardroom.stderr
    boardroom_payload = json.loads(boardroom.stdout)
    assert boardroom_payload["auto_report_summary"]["handoff_status"] == "needs_result_quality_review"
    assert "low-quality" in boardroom_payload["agenda"]
    assert plan.returncode == 0, plan.stderr
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["plan_kind"] == "quality_review"
    assert plan_payload["steps"][0]["owner"] == "qa-agent"


def test_auto_result_quality_scoring_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "36_AUTO_RESULT_QUALITY_SCORING.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "result_quality",
        "quality_average",
        "needs_result_quality_review",
        "role_outputs",
    ]:
        assert phrase in text
    assert "docs/product/36_AUTO_RESULT_QUALITY_SCORING.md" in readme
    assert "36_AUTO_RESULT_QUALITY_SCORING.md" in index
