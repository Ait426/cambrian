from __future__ import annotations

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


def test_evolve_review_summarizes_recent_job_evidence(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)

    result = run_cli(tmp_path, "evolve", "review", "--recent", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["reviewed_jobs"] == 1
    assert payload["signals"]["sample_size"] == 1
    assert payload["signals"]["pattern_threshold_met"] is False
    assert payload["signals"]["maturity_gate"]["status"] == "insufficient_data"
    assert payload["signals"]["maturity_gate"]["apply_allowed"] is False
    assert payload["signals"]["repeated_missing_paths"] == []
    assert "npm test" in payload["signals"]["wrong_test_commands"]
    assert "trace-auth-token-flow" in payload["signals"]["skills_to_improve"]
    assert (tmp_path / ".cambrian" / "evidence" / "repeated_failures.yaml").exists()


def test_evolve_review_uses_validation_evidence_signals(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    validation = ingest_and_validate_patch_candidate(tmp_path)
    complete_latest_job(tmp_path)

    result = run_cli(tmp_path, "evolve", "review", "--recent", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    signals = payload["signals"]
    assert validation["evidence_ref"] in signals["validation_evidence_refs"]
    assert signals["trust_gate_status_counts"]["manual_required"] == 1
    assert "manual_validation_required" in signals["validation_contract_statuses"]
    assert signals["manual_validation_required_jobs"]
    assert "npm test" in signals["validation_commands_needing_manual_run"]
    assert "Patch proposal was not applied to source code" in signals["process_noise_items"]
    assert "Patch proposal was not applied to source code" not in signals["unchecked_items"]
    assert signals["outcome_counts"]["partial"] == 1
    assert signals["evaluator_verdict_counts"]["hold"] == 1
    assert validation["latest_verdict_ref"] in signals["evaluator_verdict_refs"]
    assert signals["promotion_review_gate"]["status"] == "blocked_by_hold"
    assert signals["promotion_review_gate"]["auto_promote"] is False
    assert signals["promotion_review_gate"]["review_required"] is False
    assert signals["evidence_gaps"] == []
    assert payload["promotion_review_decision_ref"] == ".cambrian/evolution/review_decisions/latest_promotion_review.yaml"
    decision = yaml.safe_load((tmp_path / payload["promotion_review_decision_ref"]).read_text(encoding="utf-8"))
    assert decision["decision"] == "hold"
    assert decision["auto_promote"] is False


def test_evolve_review_treats_pass_verdict_as_review_gate_not_auto_promotion(tmp_path: Path) -> None:
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

    result = run_cli(tmp_path, "evolve", "review", "--recent", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    signals = payload["signals"]
    assert signals["evaluator_verdict_counts"]["pass"] == 1
    assert validation["latest_verdict_ref"] in signals["evaluator_verdict_refs"]
    assert signals["promotion_review_gate"]["status"] == "review_required"
    assert signals["promotion_review_gate"]["auto_promote"] is False
    assert signals["promotion_review_gate"]["review_required"] is True
    assert signals["promotion_review_gate"]["pass_jobs"]
    assert payload["promotion_review_decision_ref"] == ".cambrian/evolution/review_decisions/latest_promotion_review.yaml"
    decision = yaml.safe_load((tmp_path / payload["promotion_review_decision_ref"]).read_text(encoding="utf-8"))
    assert decision["decision"] == "needs_human_review"
    assert decision["proof_boundary"]["auto_promote"] is False
    assert decision["next_step"] == "review_latest_verdict_before_any_promotion"


def test_evolve_review_does_not_treat_two_missing_file_mentions_as_pattern(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    outcomes_path = tmp_path / ".cambrian" / "evidence" / "outcomes.yaml"
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "outcomes": [
                    {
                        "job_id": "job-1",
                        "outcome": "success",
                        "notes": "webhook-validation.ts mentioned once",
                        "validation_commands": ["npm run build"],
                        "unchecked_items": ["Patch proposal was not applied to source code"],
                    },
                    {
                        "job_id": "job-2",
                        "outcome": "success",
                        "notes": "hmac-validation.ts mentioned once",
                        "validation_commands": ["npm run build"],
                        "unchecked_items": ["Manual validation command must be run by the user"],
                    },
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "evolve", "review", "--recent", "5", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    signals = payload["signals"]
    assert signals["sample_size"] == 2
    assert signals["maturity_gate"]["status"] == "insufficient_data"
    assert signals["pattern_threshold_met"] is False
    assert signals["repeated_missing_paths"] == []
    assert "Patch proposal was not applied to source code" in signals["process_noise_items"]
    assert "Manual validation command must be run by the user" in signals["process_noise_items"]
    assert "Patch proposal was not applied to source code" not in signals["unchecked_items"]
    assert "Manual validation command must be run by the user" not in signals["unchecked_items"]


def test_evolve_review_marks_small_pattern_set_as_signal_candidate(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    outcomes_path = tmp_path / ".cambrian" / "evidence" / "outcomes.yaml"
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "outcomes": [
                    {
                        "job_id": f"job-{index}",
                        "outcome": "success",
                        "notes": "test command was wrong and backend/src/routes/auth.ts was missed",
                        "validation_commands": ["npm run build"],
                        "selected_skills": ["trace-auth-token-flow"],
                    }
                    for index in range(5)
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(tmp_path, "evolve", "review", "--recent", "5", "--json")

    assert result.returncode == 0, result.stderr
    signals = json.loads(result.stdout)["signals"]
    assert signals["sample_size"] == 5
    assert signals["pattern_threshold_met"] is True
    assert signals["maturity_gate"]["status"] == "signal_candidate"
    assert signals["maturity_gate"]["apply_allowed"] is False
    assert "backend/src/routes/auth.ts" in signals["repeated_missing_paths"]


def test_evolve_review_keeps_removed_file_mentions_out_of_important_paths(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    removed_path = tmp_path / "scripts" / "webhook-validation.ts"
    removed_path.parent.mkdir(parents=True, exist_ok=True)
    removed_path.write_text("export const legacy = true;\n", encoding="utf-8")
    outcomes_path = tmp_path / ".cambrian" / "evidence" / "outcomes.yaml"
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "outcomes": [
                    {
                        "job_id": f"job-{index}",
                        "outcome": "success",
                        "notes": "scripts/webhook-validation.ts 삭제 권장 deprecated remove legacy validator",
                        "validation_commands": ["npm run build"],
                    }
                    for index in range(10)
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    review = run_cli(tmp_path, "evolve", "review", "--recent", "10", "--json")

    assert review.returncode == 0, review.stderr
    signals = json.loads(review.stdout)["signals"]
    assert signals["pattern_threshold_met"] is True
    assert signals["maturity_gate"]["status"] == "review_required"
    assert "scripts/webhook-validation.ts" in signals["path_contexts"]["removed_or_deprecated"]
    assert "scripts/webhook-validation.ts" not in signals["path_contexts"]["important_candidates"]
    assert "scripts/webhook-validation.ts" not in signals["repeated_missing_paths"]

    proposal = run_cli(tmp_path, "evolve", "propose", "--json")

    assert proposal.returncode == 0, proposal.stderr
    payload = json.loads(proposal.stdout)
    assert "scripts/webhook-validation.ts" not in payload["changes"]["harness"]["add_important_paths"]


def test_evolution_review_signal_contract_doc_is_linked() -> None:
    doc = ROOT / "docs" / "product" / "21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    index = (ROOT / "docs" / "product" / "00_INDEX.md").read_text(encoding="utf-8")

    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for phrase in [
        "cambrian evolve review",
        "validation_commands_needing_manual_run",
        "trust_gate_status_counts",
        "manual_validation_required_jobs",
        "evaluator_verdict_counts",
        "promotion_review_gate",
        "evidence_gaps",
        "maturity_gate",
        "insufficient_data",
        "signal_candidate",
        "trusted_pattern",
    ]:
        assert phrase in text
    assert "docs/product/21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md" in readme
    assert "21_EVOLUTION_REVIEW_SIGNAL_CONTRACT.md" in index
