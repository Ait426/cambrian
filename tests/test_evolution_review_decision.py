import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from tools.validate_evolution_review_decision import validate_evolution_review_decision


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
EVOLUTION_REVIEW = WEB / "evolution" / "index.html"
SAMPLE_DECISION = WEB / "assets" / "document-organizer.evolution-review-decision.json"
VALIDATOR = ROOT / "tools" / "validate_evolution_review_decision.py"
EVOLUTION_REVIEW_DECISION_SCHEMA = ROOT / "schemas" / "evolution_review_decision_v0_1.schema.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_evolution_review_decision_schema_is_valid() -> None:
    schema = _read_json(EVOLUTION_REVIEW_DECISION_SCHEMA)

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["decision_kind"]["const"] == "evolution_review_decision_v0_1"
    assert schema["properties"]["review_status"]["const"] == "reviewed_not_applied"
    assert schema["properties"]["approval_gate"]["properties"]["auto_apply"]["const"] is False
    assert schema["properties"]["approval_gate"]["properties"]["apply_requires_separate_step"]["const"] is True
    assert schema["properties"]["next_step"]["properties"]["blocked"]["const"] == "automatic_pack_mutation"
    source_suggestion = schema["properties"]["source_suggestion"]
    assert "recommendation_ids" in source_suggestion["required"]
    assert source_suggestion["properties"]["source_receipt_eligible_for_suggestion"]["const"] is True
    assert source_suggestion["properties"]["source_receipt_requires_user_approval"]["const"] is True
    assert schema["properties"]["decisions"]["items"]["properties"]["reviewer_note"]["minLength"] == 1


def test_evolution_review_page_exists_and_is_linked_from_home() -> None:
    home = _read(WEB / "index.html")
    page = _read(EVOLUTION_REVIEW)

    assert EVOLUTION_REVIEW.exists()
    assert "evolution/index.html" in home
    assert "Open Evolution Review" in home
    for phrase in [
        "Evolution Review Gate",
        "evolution_review_decision_v0_1",
        "reviewed_not_applied",
        "Runner handoff",
        "agent-platform-evolution-handoff-v0-1",
        "agent_platform_evolution_handoff_v0_1",
        "manual_runner_to_evolution_review",
        "source_bundle",
        "validateEvolutionHandoff",
        "loadEvolutionHandoff",
        "후보 pack 내보내기",
        "diff report 내보내기",
        "promoted pack 내보내기",
        "promotion record 내보내기",
        "Private Hub로 보내기",
        "agent-platform-hub-handoff-v0-1",
        "agent_platform_hub_handoff_v0_1",
        "evolution_review_to_private_download_hub",
        "buildCandidatePackAfterUserCommand",
        "buildCandidateDiffReportAfterUserCommand",
        "buildPromotionOutputsAfterUserCommand",
        "sendPromotionOutputsToHub",
        "sourceBundleLifecycleStage",
        "source_lifecycle",
        "candidate 원본은 Builder pack 또는 promoted_private_version이어야 합니다",
        "promoted_private_version을 새 candidate review 초안으로 만들기 위해 이전 promotion_metadata를 제거한다.",
        "candidate_agent_pack_metadata_v0_1",
        "candidate_diff_report_v0_1",
        "candidate_promotion_record_v0_1",
        "candidate_not_applied",
        "promoted_private_version",
        "promoted_agent_pack_metadata_v0_1",
        "review_pass_not_promoted",
        "automatic_candidate_promotion",
        "user_command_required",
        "original_pack_preserved",
        "localStorage에서 제거했습니다",
        "buildDecision",
        "validateSuggestion",
        "automatic_pack_mutation",
        "generate_candidate_pack_after_user_command",
        "source_receipt.eligible_for_suggestion은 true여야 합니다",
        "recommendation_ids",
        "reviewDecisionErrors",
        "모든 recommendation에 리뷰 메모가 필요합니다",
        "proof_claim_allowed: false",
        "success_rate_claim_allowed: false",
        "pack은 수정되지 않았습니다",
    ]:
        assert phrase in page


def test_validate_evolution_review_decision_passes_sample() -> None:
    report = validate_evolution_review_decision(SAMPLE_DECISION)

    assert report["validator"] == "evolution_review_decision_validator_v0_1"
    assert report["status"] == "pass"
    assert report["agent_id"] == "document-organizer"
    assert not report["errors"]
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert any(check["name"] == "auto_apply_blocked" for check in report["checks"])
    assert any(check["name"] == "source_suggestion_eligible_for_review" for check in report["checks"])
    assert any(check["name"] == "decision_count_matches_suggestion" for check in report["checks"])
    assert any(check["name"] == "recommendation_decisions_complete" for check in report["checks"])
    assert any(check["name"] == "reviewer_notes_present" for check in report["checks"])
    assert any(check["name"] == "separate_apply_step_required" for check in report["checks"])


def test_validate_evolution_review_decision_blocks_auto_apply(tmp_path: Path) -> None:
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    decision["approval_gate"]["auto_apply"] = True
    decision["approval_gate"]["can_create_new_version"] = True
    decision["next_step"]["blocked"] = "none"
    broken_path = tmp_path / "auto-apply.evolution-review-decision.json"
    _write_json(broken_path, decision)

    report = validate_evolution_review_decision(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "decision_schema" for error in report["errors"])
    assert any(error["code"] == "auto_apply_blocked" for error in report["errors"])
    assert any(error["code"] == "separate_apply_step_required" for error in report["errors"])


def test_validate_evolution_review_decision_blocks_fake_proof_and_raw_storage(tmp_path: Path) -> None:
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    decision["proof_boundary"]["proof_claim_allowed"] = True
    decision["proof_boundary"]["success_rate_claim_allowed"] = True
    decision["privacy"]["stores_raw_inputs"] = True
    decision["privacy"]["stores_secrets"] = True
    broken_path = tmp_path / "fake-proof.evolution-review-decision.json"
    _write_json(broken_path, decision)

    report = validate_evolution_review_decision(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "decision_schema" for error in report["errors"])
    assert any(error["code"] == "proof_claim_blocked" for error in report["errors"])
    assert any(error["code"] == "privacy_uses_only_suggestion_metadata" for error in report["errors"])


def test_validate_evolution_review_decision_blocks_unqualified_source(tmp_path: Path) -> None:
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    decision["source_suggestion"]["source_receipt_eligible_for_suggestion"] = False
    decision["source_suggestion"]["source_receipt_requires_user_approval"] = False
    broken_path = tmp_path / "unqualified.evolution-review-decision.json"
    _write_json(broken_path, decision)

    report = validate_evolution_review_decision(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "decision_schema" for error in report["errors"])
    assert any(error["code"] == "source_suggestion_eligible_for_review" for error in report["errors"])


def test_validate_evolution_review_decision_blocks_incomplete_recommendation_coverage(tmp_path: Path) -> None:
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    decision["decisions"] = decision["decisions"][:-1]
    broken_path = tmp_path / "incomplete.evolution-review-decision.json"
    _write_json(broken_path, decision)

    report = validate_evolution_review_decision(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "decision_count_matches_suggestion" for error in report["errors"])
    assert any(error["code"] == "recommendation_decisions_complete" for error in report["errors"])


def test_validate_evolution_review_decision_blocks_empty_reviewer_note(tmp_path: Path) -> None:
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    decision["decisions"][0]["reviewer_note"] = ""
    broken_path = tmp_path / "empty-note.evolution-review-decision.json"
    _write_json(broken_path, decision)

    report = validate_evolution_review_decision(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "decision_schema" for error in report["errors"])
    assert any(error["code"] == "reviewer_notes_present" for error in report["errors"])


def test_validate_evolution_review_decision_cli_outputs_json_report() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(SAMPLE_DECISION), "--pretty"],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "pass"
    assert report["validator"] == "evolution_review_decision_validator_v0_1"
