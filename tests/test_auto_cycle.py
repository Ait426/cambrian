from __future__ import annotations

import json
from pathlib import Path

import yaml

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
    assert "validation failed" in plan["steps"][0]["task"]


def test_auto_cycle_requires_auto_state(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "auto", "cycle", "--max-steps", "1", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["failed_step"] == "boardroom"
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
