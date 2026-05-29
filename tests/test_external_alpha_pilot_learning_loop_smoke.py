import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.smoke_external_alpha_pilot_learning_loop import (
    PILOT_LEARNING_REHEARSAL_RECEIPT_NAME,
    PilotLearningLoopRehearsalError,
    smoke_pilot_learning_loop,
    verify_pilot_learning_rehearsal_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT_LEARNING_SCRIPT = ROOT / "scripts" / "smoke_external_alpha_pilot_learning_loop.py"


def test_external_alpha_pilot_learning_loop_rehearsal_receipt_passes(tmp_path: Path) -> None:
    result = smoke_pilot_learning_loop(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "REHEARSAL_PASS"
    assert receipt_path.name == PILOT_LEARNING_REHEARSAL_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_pilot_learning_loop_rehearsal_v0_1"
    assert payload["status"] == "pass"
    assert payload["verdict"] == "REHEARSAL_PASS"
    assert payload["safe_to_share"] is True
    assert payload["real_pilot_evidence"] is False
    assert payload["release"]["zip_file"] == f"{RELEASE_SLUG}.zip"
    assert payload["rehearsed_flow"]["pilot_evidence_verdict"] == "READY_FOR_DECISION"
    assert payload["rehearsed_flow"]["pilot_decision_verdict"] == "FIX_BEFORE_NEXT"
    assert payload["rehearsed_flow"]["pilot_iteration_verdict"] == "PATCH_BEFORE_NEXT"
    assert payload["rehearsed_flow"]["artifact_chain_depth"] >= 11
    assert payload["learning_summary"] == {
        "outcome_tag": "partial",
        "friction_tags": ["docs", "terminology"],
        "missing_skill_tags": ["skill_search"],
        "raw_feedback_included": False,
        "raw_issue_included": False,
        "free_text_included": False,
    }
    assert payload["private_input_policy"]["stored_private_values"] is False
    assert payload["private_input_policy"]["stored_private_paths"] is False
    assert payload["private_input_policy"]["stored_private_hashes_only"] is True
    assert payload["private_input_policy"]["private_workspace_dir_shortcut_used"] is True
    assert payload["private_input_policy"]["standard_private_workspace_files"] == [
        "recipient-private.txt",
        "operator-dispatch-note-private.md",
        "recipient-ack-private.txt",
        "pilot-feedback-private.md",
        "pilot-issue-intake-private.md",
        "operator-decision-note-private.md",
    ]
    assert payload["private_input_policy"]["explicit_private_file_args_used"] is False
    assert payload["private_input_policy"]["explicit_private_sha256_args_used"] is False
    assert payload["private_input_policy"]["feedback_hash_present"] is True
    assert payload["private_input_policy"]["issue_intake_hash_present"] is True
    assert payload["private_input_policy"]["operator_decision_note_hash_present"] is True
    assert payload["iteration_boundary"]["decision"] == "fix_before_next"
    assert payload["iteration_boundary"]["max_next_participants"] == 0
    assert payload["iteration_boundary"]["scaling_allowed"] is False
    assert payload["claim_boundaries"]["proof_claim_allowed"] is False
    assert payload["claim_boundaries"]["success_rate_claim_allowed"] is False
    assert payload["claim_boundaries"]["sale_ready"] is False
    assert payload["claim_boundaries"]["market_validated"] is False
    assert payload["claim_boundaries"]["marketplace_listing_allowed"] is False
    assert all(payload["checks"].values())
    assert verify_pilot_learning_rehearsal_receipt_file(receipt_path)["verdict"] == "REHEARSAL_PASS"

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    for marker in [
        "PILOT_LEARNING_REHEARSAL_PRIVATE_RECIPIENT",
        "PILOT_LEARNING_REHEARSAL_PRIVATE_OPERATOR_DISPATCH_NOTE",
        "PILOT_LEARNING_REHEARSAL_PRIVATE_ACK",
        "PILOT_LEARNING_REHEARSAL_PRIVATE_FEEDBACK",
        "PILOT_LEARNING_REHEARSAL_PRIVATE_ISSUE",
        "PILOT_LEARNING_REHEARSAL_PRIVATE_DECISION_NOTE",
        "recipient@example.invalid",
        "fix before next pilot",
    ]:
        assert marker not in serialized


def test_external_alpha_pilot_learning_loop_rehearsal_cli_passes_and_verifies(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(PILOT_LEARNING_SCRIPT), "--output-dir", str(tmp_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha pilot learning loop rehearsal" in output
    assert "verdict: REHEARSAL_PASS" in output
    assert (tmp_path / PILOT_LEARNING_REHEARSAL_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(PILOT_LEARNING_SCRIPT),
            "--verify-receipt",
            str(tmp_path / PILOT_LEARNING_REHEARSAL_RECEIPT_NAME),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha pilot learning loop rehearsal verification" in verify_output
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / PILOT_LEARNING_REHEARSAL_RECEIPT_NAME).read_text(
        encoding="utf-8"
    )


def test_external_alpha_pilot_learning_loop_rehearsal_rejects_real_pilot_claim(tmp_path: Path) -> None:
    result = smoke_pilot_learning_loop(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["real_pilot_evidence"] = True
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PilotLearningLoopRehearsalError, match="real pilot evidence"):
        verify_pilot_learning_rehearsal_receipt_file(receipt_path)
