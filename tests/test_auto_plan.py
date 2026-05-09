from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_auto_boardroom import prepare_auto
from tests.test_authority_mode import ROOT, run_cli


def test_auto_plan_turns_boardroom_into_bounded_steps(tmp_path: Path) -> None:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0

    result = run_cli(tmp_path, "auto", "plan", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["plan_id"].startswith("auto-plan-")
    assert payload["steps"]
    assert all(step["owner"].endswith("-agent") for step in payload["steps"])
    assert all(step["success_criteria"] for step in payload["steps"])
    assert payload["next_command"] == "cambrian auto run --max-steps 5 --json"

    plan = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "plan.yaml").read_text(encoding="utf-8"))
    assert plan["steps"][0]["id"] == "step-001"
    assert "required_permissions" in plan["steps"][0]
    assert plan["plan_kind"] == "default"


def test_auto_plan_requires_boardroom_first(tmp_path: Path) -> None:
    prepare_auto(tmp_path)

    result = run_cli(tmp_path, "auto", "plan", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "boardroom decision is missing" in payload["errors"]


def test_auto_plan_blocks_stale_boardroom_summary(tmp_path: Path) -> None:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr

    result = run_cli(tmp_path, "auto", "plan", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "boardroom decision is stale" in payload["errors"][0]
    assert payload["boardroom_handoff_status"] == "ready_for_auto_run"
    assert payload["current_handoff_status"] == "waiting_for_external_result"
    assert payload["next_command"] == "cambrian auto boardroom --json"


def _prepare_result_handoff(tmp_path: Path, result_payload: dict[str, object]) -> None:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    task_ref = json.loads(run_result.stdout)["task_refs"][0]
    result_file = tmp_path / "step_result.yaml"
    full_payload = {
        "changed_files": [],
        "tests": [],
        "next_action": "cambrian auto report --json",
        "evidence": {"notes": ["test evidence"], "artifacts": []},
        "role_outputs": {
            "scope": "handoff scope",
            "acceptance_criteria": ["handoff accepted"],
            "test_plan": ["python -m pytest"],
        },
        **result_payload,
    }
    result_file.write_text(yaml.safe_dump(full_payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ingest = run_cli(tmp_path, "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    assert ingest.returncode == 0, ingest.stderr
    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    assert boardroom.returncode == 0, boardroom.stderr


def test_auto_plan_uses_recovery_steps_for_blocked_handoff(tmp_path: Path) -> None:
    _prepare_result_handoff(
        tmp_path,
        {
            "status": "failed",
            "summary": "blocked",
            "tests": [{"command": "python -m pytest", "status": "failed"}],
            "blockers": ["validation failed"],
        },
    )

    result = run_cli(tmp_path, "auto", "plan", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["plan_kind"] == "recovery"
    assert payload["auto_report_summary"]["handoff_status"] == "needs_boardroom_review"
    assert payload["steps"][0]["owner"] == "pm-agent"
    assert "validation failed" in payload["steps"][0]["task"]
    assert payload["steps"][0]["handoff_status"] == "needs_boardroom_review"
    plan = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "plan.yaml").read_text(encoding="utf-8"))
    assert plan["plan_kind"] == "recovery"


def test_auto_plan_uses_release_or_next_steps_for_validated_handoff(tmp_path: Path) -> None:
    _prepare_result_handoff(
        tmp_path,
        {
            "status": "success",
            "summary": "validated",
            "tests": [{"command": "python -m pytest", "status": "passed"}],
            "blockers": [],
        },
    )

    result = run_cli(tmp_path, "auto", "plan", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["plan_kind"] == "release_gate"
    assert payload["auto_report_summary"]["handoff_status"] == "ready_for_release_or_next_plan"
    assert payload["auto_report_summary"]["quality_route"] == "release_gate"
    assert payload["steps"][0]["owner"] == "release-manager-agent"
    assert "release gate" in payload["steps"][0]["task"]


def test_auto_plan_uses_result_intake_step_when_external_result_is_waiting(tmp_path: Path) -> None:
    prepare_auto(tmp_path)
    assert run_cli(tmp_path, "auto", "boardroom", "--json").returncode == 0
    assert run_cli(tmp_path, "auto", "plan", "--json").returncode == 0
    run_result = run_cli(tmp_path, "auto", "run", "--max-steps", "1", "--json")
    assert run_result.returncode == 0, run_result.stderr
    boardroom = run_cli(tmp_path, "auto", "boardroom", "--json")
    assert boardroom.returncode == 0, boardroom.stderr

    result = run_cli(tmp_path, "auto", "plan", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["plan_kind"] == "result_intake"
    assert payload["auto_report_summary"]["handoff_status"] == "waiting_for_external_result"
    assert payload["steps"][0]["owner"] == "pm-agent"
    assert "result file" in payload["steps"][0]["task"]


def test_auto_plan_uses_validation_step_for_unvalidated_ingest(tmp_path: Path) -> None:
    _prepare_result_handoff(
        tmp_path,
        {
            "status": "success",
            "summary": "done without validation evidence",
            "blockers": [],
        },
    )

    result = run_cli(tmp_path, "auto", "plan", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["plan_kind"] == "validation"
    assert payload["auto_report_summary"]["handoff_status"] == "needs_validation"
    assert payload["steps"][0]["owner"] == "qa-agent"


def test_auto_plan_from_handoff_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "29_AUTO_PLAN_FROM_HANDOFF.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian auto plan",
        "plan_kind",
        "recovery",
        "validated_next",
        "source code",
    ]:
        assert phrase in text
    assert "docs/product/29_AUTO_PLAN_FROM_HANDOFF.md" in readme
    assert "29_AUTO_PLAN_FROM_HANDOFF.md" in index
