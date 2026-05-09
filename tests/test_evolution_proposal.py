from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_job_complete_evidence import (
    ROOT,
    complete_latest_job,
    ingest_and_validate_patch_candidate,
    prepare_custom_harness_project,
    run_cli,
)


def test_evolve_propose_creates_harness_agent_skill_proposal(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)

    result = run_cli(tmp_path, "evolve", "propose", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["proposal_id"].startswith("evolution-")
    assert payload["quality_score"] >= 0
    assert payload["risk_score"] >= 0
    assert payload["changed_files_preview"]
    assert payload["change_preview"]
    assert payload["next_command"].startswith("cambrian evolve preview ")
    assert payload["changes"]["harness"]["add_important_paths"]
    assert payload["changes"]["agents"]["update"]
    assert payload["changes"]["skills"]["update"]
    proposal_path = tmp_path / payload["proposal_ref"]
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert proposal["safety"]["requires_confirm"] is True
    assert proposal["safety"]["source_code_modified"] is False
    assert proposal["changed_files_preview"] == payload["changed_files_preview"]


def test_evolve_propose_carries_validation_evidence_into_skill_changes(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    ingest_and_validate_patch_candidate(tmp_path)
    complete_latest_job(tmp_path)

    result = run_cli(tmp_path, "evolve", "propose", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    skill_updates = payload["changes"]["skills"]["update"]
    trace_update = next(item for item in skill_updates if item["id"] == "trace-auth-token-flow")
    assert any("Manual validation evidence required: npm test" == item for item in trace_update["add_validation_required"])
    assert "Patch proposal was not applied to source code" in trace_update["known_failure_patterns"]
    assert any(
        "Patch proposal was not applied to source code" in item
        for item in payload["changes"]["harness"]["add_success_criteria"]
    )
    proposal = yaml.safe_load((tmp_path / payload["proposal_ref"]).read_text(encoding="utf-8"))
    assert proposal["evidence"]["signals"]["trust_gate_status_counts"]["manual_required"] == 1


def test_evolve_preview_shows_apply_plan_without_modifying_metadata(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    ingest_and_validate_patch_candidate(tmp_path)
    complete_latest_job(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    harness_before = (tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "previewed"
    assert payload["proposal_id"] == proposal_id
    assert payload["preview_ref"]
    assert payload["changed_files_preview"]
    assert ".cambrian/harness.yaml" in payload["changed_files_preview"]
    assert ".cambrian/skills/trace-auth-token-flow.yaml" in payload["change_preview"]
    assert payload["safety"]["requires_confirm"] is True
    assert payload["safety"]["source_code_modified"] is False
    assert payload["next_command"] == f"cambrian evolve apply {proposal_id} --confirm --json"
    assert (tmp_path / payload["preview_ref"]).exists()
    assert (tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8") == harness_before
