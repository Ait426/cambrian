from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from tests.test_job_complete_evidence import (
    ROOT,
    complete_latest_job,
    ingest_and_validate_patch_candidate,
    mark_latest_validation_evidence_passed,
    prepare_custom_harness_project,
    run_cli,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expand_outcomes(root: Path, count: int = 10) -> None:
    outcomes_path = root / ".cambrian" / "evidence" / "outcomes.yaml"
    payload = yaml.safe_load(outcomes_path.read_text(encoding="utf-8"))
    seed = dict(payload["outcomes"][0])
    payload["outcomes"] = [{**seed, "job_id": f"job-maturity-{index:03d}"} for index in range(count)]
    outcomes_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


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
    assert payload["changed_files_preview"] == []
    assert payload["change_preview"] == {}
    assert payload["next_command"].startswith("cambrian evolve preview ")
    assert payload["changes"]["harness"]["add_important_paths"] == []
    assert payload["changes"]["agents"]["update"] == []
    assert payload["changes"]["skills"]["update"] == []
    assert payload["maturity_gate"]["status"] == "insufficient_data"
    assert payload["safety"]["evolution_apply_allowed"] is False
    proposal_path = tmp_path / payload["proposal_ref"]
    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert proposal["evidence"]["signals"]["pattern_threshold_met"] is False
    assert proposal["maturity_gate"]["status"] == "insufficient_data"
    assert proposal["safety"]["evolution_apply_allowed"] is False
    assert proposal["safety"]["requires_confirm"] is True
    assert proposal["safety"]["source_code_modified"] is False
    assert proposal["safety"]["auto_promote"] is False
    assert proposal["changed_files_preview"] == payload["changed_files_preview"]


def test_evolve_propose_carries_validation_evidence_into_skill_changes(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    ingest_and_validate_patch_candidate(tmp_path)
    complete_latest_job(tmp_path)

    result = run_cli(tmp_path, "evolve", "propose", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["maturity_gate"]["status"] == "insufficient_data"
    proposal = yaml.safe_load((tmp_path / payload["proposal_ref"]).read_text(encoding="utf-8"))
    assert proposal["maturity_gate"]["status"] == "insufficient_data"
    assert proposal["evidence"]["signals"]["process_noise_items"]
    assert payload["changes"]["skills"]["update"] == []
    assert payload["changes"]["harness"]["add_success_criteria"] == []


def test_evolve_propose_carries_validation_evidence_into_skill_changes_after_maturity_gate(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    ingest_and_validate_patch_candidate(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path, count=10)

    result = run_cli(tmp_path, "evolve", "propose", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["maturity_gate"]["status"] == "review_required"
    assert payload["safety"]["evolution_apply_allowed"] is True
    skill_updates = payload["changes"]["skills"]["update"]
    trace_update = next(item for item in skill_updates if item["id"] == "trace-auth-token-flow")
    assert any("Manual validation evidence required: npm test" == item for item in trace_update["add_validation_required"])
    assert "Patch proposal was not applied to source code" not in trace_update["known_failure_patterns"]
    assert not any(item.startswith("Resolve unchecked validation item:") for item in payload["changes"]["harness"]["add_success_criteria"])
    assert not any("refresh token 발급" in item for item in trace_update["add_procedure"])
    agent_update = next(item for item in payload["changes"]["agents"]["update"] if item["id"] == "auth-flow-investigator")
    assert not any("refresh token 발급" in item for item in agent_update["add_responsibilities"])
    proposal = yaml.safe_load((tmp_path / payload["proposal_ref"]).read_text(encoding="utf-8"))
    assert proposal["maturity_gate"]["status"] == "review_required"
    assert proposal["safety"]["evolution_apply_allowed"] is True
    assert proposal["evidence"]["signals"]["trust_gate_status_counts"]["manual_required"] == 10
    assert "Patch proposal was not applied to source code" in proposal["evidence"]["signals"]["process_noise_items"]


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
    proposal_path = tmp_path / ".cambrian" / "evolution" / "proposals" / f"{proposal_id}.yaml"
    assert payload["proposal_sha256"] == _sha256(proposal_path)
    assert payload["preview_sha256"]
    assert payload["preview_digest_ref"] == f".cambrian/evolution/previews/{proposal_id}.digest.yaml"
    assert payload["changed_files_preview"] == []
    assert payload["change_preview"] == {}
    assert payload["safety"]["maturity_gate_status"] == "insufficient_data"
    assert payload["safety"]["evolution_apply_allowed"] is False
    assert (tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8") == harness_before


def test_evolve_preview_shows_apply_plan_after_maturity_gate(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    ingest_and_validate_patch_candidate(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path, count=10)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_payload = json.loads(proposed.stdout)
    proposal_id = proposal_payload["proposal_id"]
    harness_before = (tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8")

    result = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["changed_files_preview"]
    assert proposal_payload["changes"]["harness"]["add_important_paths"] == []
    assert ".cambrian/harness.yaml" not in payload["changed_files_preview"]
    assert ".cambrian/validation.yaml" in payload["changed_files_preview"]
    assert ".cambrian/skills/trace-auth-token-flow.yaml" in payload["change_preview"]
    assert payload["safety"]["maturity_gate_status"] == "review_required"
    assert payload["safety"]["evolution_apply_allowed"] is True
    assert payload["safety"]["requires_confirm"] is True
    assert payload["safety"]["auto_promote"] is False
    assert payload["safety"]["source_code_modified"] is False
    assert payload["next_command"] == f"cambrian evolve apply {proposal_id} --confirm --json"
    preview_record = yaml.safe_load((tmp_path / payload["preview_ref"]).read_text(encoding="utf-8"))
    assert preview_record["proposal_sha256"] == payload["proposal_sha256"]
    digest_lock = yaml.safe_load((tmp_path / payload["preview_digest_ref"]).read_text(encoding="utf-8"))
    assert digest_lock["lock_kind"] == "evolution_preview_digest_lock"
    assert digest_lock["preview_ref"] == payload["preview_ref"]
    assert digest_lock["proposal_sha256"] == payload["proposal_sha256"]
    assert digest_lock["preview_sha256"] == payload["preview_sha256"]
    assert payload["preview_sha256"] == _sha256(tmp_path / payload["preview_ref"])
    assert (tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8") == harness_before


def test_evolve_propose_carries_pass_verdict_as_review_gate_not_auto_promotion(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)
    mark_latest_validation_evidence_passed(tmp_path, validation)
    complete = run_cli(
        tmp_path,
        "job",
        "complete",
        "latest",
        "--outcome",
        "success",
        "--notes",
        "manual validation passed",
        "--json",
    )
    assert complete.returncode == 0, complete.stderr

    result = run_cli(tmp_path, "evolve", "propose", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["changes"]
    proposal = yaml.safe_load((tmp_path / payload["proposal_ref"]).read_text(encoding="utf-8"))
    gate = proposal["evidence"]["signals"]["promotion_review_gate"]
    assert gate["status"] == "review_required"
    assert gate["auto_promote"] is False
    assert gate["review_required"] is True
    assert proposal["evidence"]["promotion_review_decision_ref"] == ".cambrian/evolution/review_decisions/latest_promotion_review.yaml"
    assert proposal["evidence"]["promotion_review_decision_sha256"]
    assert proposal["safety"]["auto_promote"] is False
    assert proposal["safety"]["promotion_review_required"] is True
    assert proposal["safety"]["promotion_review_gate_status"] == "review_required"
    preview = run_cli(tmp_path, "evolve", "preview", payload["proposal_id"], "--json")
    assert preview.returncode == 0, preview.stderr
    preview_payload = json.loads(preview.stdout)
    assert preview_payload["safety"]["promotion_review_required"] is True
    assert preview_payload["safety"]["auto_promote"] is False


def test_evolve_preview_blocks_pass_proposal_without_review_decision(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)
    mark_latest_validation_evidence_passed(tmp_path, validation)
    complete = run_cli(
        tmp_path,
        "job",
        "complete",
        "latest",
        "--outcome",
        "success",
        "--notes",
        "manual validation passed",
        "--json",
    )
    assert complete.returncode == 0, complete.stderr
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    assert proposed.returncode == 0, proposed.stderr
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    decision_path = tmp_path / ".cambrian" / "evolution" / "review_decisions" / "latest_promotion_review.yaml"
    decision_path.unlink()

    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")

    assert preview.returncode == 1
    payload = json.loads(preview.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert "promotion review decision not found" in payload["errors"][0]


def test_evolve_preview_blocks_tampered_review_decision_digest(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)
    mark_latest_validation_evidence_passed(tmp_path, validation)
    complete = run_cli(
        tmp_path,
        "job",
        "complete",
        "latest",
        "--outcome",
        "success",
        "--notes",
        "manual validation passed",
        "--json",
    )
    assert complete.returncode == 0, complete.stderr
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    assert proposed.returncode == 0, proposed.stderr
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    decision_path = tmp_path / ".cambrian" / "evolution" / "review_decisions" / "latest_promotion_review.yaml"
    decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
    decision["next_step"] = "tampered_after_proposal"
    decision_path.write_text(yaml.safe_dump(decision, allow_unicode=True, sort_keys=False), encoding="utf-8")

    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")

    assert preview.returncode == 1
    payload = json.loads(preview.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["errors"] == ["promotion review decision digest mismatch"]


def test_evolution_proposal_preview_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian evolve propose",
        "cambrian evolve preview",
        "quality_score",
        "risk_score",
        "changed_files_preview",
        "change_preview",
        "source_code_modified",
        "promotion_review_required",
        "maturity_gate_status",
        "evolution_apply_allowed",
        "trusted_pattern",
        "proposal_sha256",
        "preview_sha256",
        "preview_digest_ref",
        "evolution_preview_digest_lock",
        "promotion_review_decision_sha256",
    ]:
        assert phrase in text
    assert "docs/product/22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md" in readme
    assert "22_EVOLUTION_PROPOSAL_PREVIEW_CONTRACT.md" in index
