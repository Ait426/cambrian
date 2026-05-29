from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_authority_mode import ROOT, run_cli


def prepare_auto(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "authority", "grant", "--mode", "full-authority", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "init", "--goal", "제품을 설치형 RC로 완성", "--json").returncode == 0


def test_auto_boardroom_creates_role_decisions(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "boardroom", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["meeting_id"].startswith("boardroom-")
    assert "ceo" in payload["decisions"]
    assert "cto" in payload["decisions"]
    assert "coo" in payload["decisions"]
    assert "pm" in payload["decisions"]
    assert payload["recommended_next_action"] == "cambrian auto plan --json"
    assert payload["report_evidence_refs"]
    assert payload["decision_lineage"]["source_auto_report"] == ".cambrian/auto/report.yaml"

    boardroom_files = list((tmp_path / ".cambrian" / "auto" / "boardroom").glob("boardroom-*.yaml"))
    decision_files = list((tmp_path / ".cambrian" / "auto" / "decisions").glob("boardroom-*.yaml"))
    assert boardroom_files
    assert decision_files

    meeting = yaml.safe_load(boardroom_files[0].read_text(encoding="utf-8"))
    assert meeting["decisions"]["engineering"]["decision"]
    assert meeting["decisions"]["engineering"]["evidence_refs"]
    assert meeting["decisions"]["engineering"]["evidence_citations"][0]["kind"] == "auto_report"
    decision = yaml.safe_load(decision_files[0].read_text(encoding="utf-8"))
    assert decision["decision_lineage"]["decision_roles"]
    assert decision["source_auto_report"] == ".cambrian/auto/report.yaml"


def _prepare_waiting_task(tmp_path: Path) -> str:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    return str(json.loads(run_result.stdout)["task_refs"][0])


def test_auto_boardroom_reads_blocked_result_handoff(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "blocked_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "blocked by validation failure",
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

    result = run_cli(tmp_path, "auto", "boardroom", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["auto_report_summary"]["handoff_status"] == "needs_boardroom_review"
    assert payload["auto_report_summary"]["blocked_results"] == 1
    assert "blocked auto step" in payload["agenda"]
    assert payload["decisions"]["ceo"]["decision"].startswith("Stop forward planning")
    assert payload["recommended_next_action"] == "cambrian auto plan --json"

    meeting_files = sorted((tmp_path / ".cambrian" / "auto" / "boardroom").glob("boardroom-*.yaml"))
    meeting = yaml.safe_load(meeting_files[-1].read_text(encoding="utf-8"))
    assert meeting["auto_report_summary"]["open_blockers"][0]["blockers"] == ["validation failed"]
    assert meeting["source_auto_report"] == ".cambrian/auto/report.yaml"


def test_auto_boardroom_reads_validated_result_handoff(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    result_file = tmp_path / "validated_result.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "success",
                "summary": "validated implementation result",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "passed"}],
                "blockers": [],
                "next_action": "cambrian auto report --json",
                "evidence": {"notes": ["validated"], "artifacts": []},
                "role_outputs": {
                    "scope": "validated handoff scope",
                    "acceptance_criteria": ["validated evidence available"],
                    "test_plan": ["python -m pytest"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    result = run_cli(tmp_path, "auto", "boardroom", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["auto_report_summary"]["handoff_status"] == "ready_for_release_or_next_plan"
    assert payload["auto_report_summary"]["validated_results"] == 1
    assert "validated auto step" in payload["agenda"]
    assert payload["decisions"]["release_manager"]["decision"].startswith("Check whether")
    assert payload["recommended_next_action"] == "cambrian auto plan --json"


def test_auto_plan_records_boardroom_decision_lineage_on_steps(tmp_path: Path) -> None:
    prepare_auto(tmp_path)
    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    assert boardroom.returncode == 0, boardroom.stderr

    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert plan.returncode == 0, plan.stderr
    payload = json.loads(plan.stdout)
    assert payload["decision_lineage"]["boardroom_ref"] == json.loads(boardroom.stdout)["boardroom_ref"]
    assert payload["decision_lineage"]["decision_ref"] == json.loads(boardroom.stdout)["decision_ref"]
    assert payload["decision_lineage"]["source_auto_report"] == ".cambrian/auto/report.yaml"
    assert payload["steps"][0]["boardroom_decision_lineage"]["role"] == "pm"
    assert payload["steps"][0]["boardroom_role_decision"]["role"] == "pm"
    assert payload["steps"][0]["decision_evidence_refs"]
    assert "boardroom decision evidence cited" in payload["steps"][0]["success_criteria"]

    saved = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "plan.yaml").read_text(encoding="utf-8"))
    assert saved["source_decision"] == json.loads(boardroom.stdout)["decision_ref"]
    assert saved["steps"][2]["boardroom_decision_lineage"]["role"] == "engineering"
    assert saved["steps"][4]["boardroom_decision_lineage"]["role"] == "release_manager"


def test_stale_boardroom_cannot_create_plan_after_handoff_changes(tmp_path: Path) -> None:
    task_ref = _prepare_waiting_task(tmp_path)
    stale_boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    assert stale_boardroom.returncode == 0, stale_boardroom.stderr
    result_file = tmp_path / "blocked_after_boardroom.yaml"
    result_file.write_text(
        yaml.safe_dump(
            {
                "status": "failed",
                "summary": "blocked after stale boardroom",
                "changed_files": [],
                "tests": [{"command": "python -m pytest", "status": "failed"}],
                "blockers": ["new blocker after boardroom"],
                "next_action": "cambrian auto boardroom --json",
                "evidence": {"notes": ["new blocker"], "artifacts": []},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr

    plan = run_cli(tmp_path, "auto", "plan", "--json")

    assert plan.returncode == 1
    payload = json.loads(plan.stdout)
    assert payload["ok"] is False
    assert "boardroom decision is stale" in payload["errors"][0]
    assert payload["next_command"] == "cambrian auto boardroom --json"


def test_auto_boardroom_report_review_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "28_AUTO_BOARDROOM_REPORT_REVIEW.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto boardroom",
        "auto_report_summary",
        "needs_boardroom_review",
        "ready_for_release_or_next_plan",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/28_AUTO_BOARDROOM_REPORT_REVIEW.md" in readme
    assert "28_AUTO_BOARDROOM_REPORT_REVIEW.md" in index
