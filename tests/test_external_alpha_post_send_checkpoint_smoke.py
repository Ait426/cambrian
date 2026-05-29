import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.smoke_external_alpha_post_send_checkpoint import (
    POST_SEND_REHEARSAL_RECEIPT_NAME,
    PostSendCheckpointRehearsalError,
    smoke_post_send_checkpoint,
    verify_post_send_rehearsal_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
POST_SEND_SMOKE_SCRIPT = ROOT / "scripts" / "smoke_external_alpha_post_send_checkpoint.py"


def test_external_alpha_post_send_checkpoint_rehearsal_receipt_passes(tmp_path: Path) -> None:
    result = smoke_post_send_checkpoint(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "REHEARSAL_PASS"
    assert receipt_path.name == POST_SEND_REHEARSAL_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_post_send_checkpoint_rehearsal_v0_1"
    assert payload["status"] == "pass"
    assert payload["verdict"] == "REHEARSAL_PASS"
    assert payload["safe_to_share"] is True
    assert payload["real_recipient_evidence"] is False
    assert payload["release"]["zip_file"] == f"{RELEASE_SLUG}.zip"
    assert payload["release"]["file_count"] > 0
    assert payload["rehearsed_flow"]["post_send_sequence_verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["rehearsed_flow"]["post_send_sequence_body_sha256"]
    assert payload["rehearsed_flow"]["post_send_sequence_final_audit_operator_bypass_required"] is False
    assert payload["rehearsed_flow"]["dispatch_record_verdict"] == "SENT_ONE_RECORDED"
    assert payload["rehearsed_flow"]["recipient_checkpoint_verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["rehearsed_flow"]["artifact_chain_depth"] >= 9
    assert payload["private_input_policy"]["stored_private_values"] is False
    assert payload["private_input_policy"]["stored_private_paths"] is False
    assert payload["private_input_policy"]["stored_private_hashes_only"] is True
    assert payload["private_input_policy"]["private_workspace_dir_shortcut_used"] is True
    assert payload["private_input_policy"]["post_send_sequence_used"] is True
    assert payload["private_input_policy"]["preflight_receipt_required"] is True
    assert payload["private_input_policy"]["preflight_generated_by_real_gate"] is True
    assert payload["private_input_policy"]["operator_note_template_used"] is True
    assert payload["private_input_policy"]["standard_private_workspace_files"] == [
        "recipient-private.txt",
        "operator-dispatch-note-private.md",
        "recipient-ack-private.txt",
    ]
    assert payload["private_input_policy"]["explicit_private_file_args_used"] is False
    assert payload["private_input_policy"]["explicit_private_sha256_args_used"] is False
    assert payload["claim_boundaries"]["proof_claim_allowed"] is False
    assert payload["claim_boundaries"]["success_rate_claim_allowed"] is False
    assert payload["claim_boundaries"]["sale_ready"] is False
    assert payload["claim_boundaries"]["market_validated"] is False
    assert payload["checks"]["preflight_generated_by_real_gate"] is True
    assert payload["checks"]["operator_note_template_used"] is True
    assert payload["checks"]["operator_note_template_preflight_contract"] is True
    assert payload["checks"]["synthetic_dispatch_not_standalone_proof"] is True
    assert payload["checks"]["synthetic_checkpoint_not_standalone_proof"] is True
    assert all(payload["checks"].values())
    assert verify_post_send_rehearsal_receipt_file(receipt_path)["verdict"] == "REHEARSAL_PASS"

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "POST_SEND_REHEARSAL_PRIVATE_RECIPIENT" not in serialized
    assert "POST_SEND_REHEARSAL_PRIVATE_OPERATOR_NOTE" not in serialized
    assert "POST_SEND_REHEARSAL_PRIVATE_ACK" not in serialized
    assert "recipient@example.invalid" not in serialized
    assert "확인 완료" not in serialized


def test_external_alpha_post_send_checkpoint_rehearsal_cli_passes_and_verifies(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(POST_SEND_SMOKE_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha post-send checkpoint rehearsal" in output
    assert "verdict: REHEARSAL_PASS" in output
    assert (tmp_path / POST_SEND_REHEARSAL_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(POST_SEND_SMOKE_SCRIPT),
            "--verify-receipt",
            str(tmp_path / POST_SEND_REHEARSAL_RECEIPT_NAME),
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
    assert "[PASS] external alpha post-send checkpoint rehearsal verification" in verify_output
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / POST_SEND_REHEARSAL_RECEIPT_NAME).read_text(
        encoding="utf-8"
    )


def test_external_alpha_post_send_checkpoint_rehearsal_rejects_real_recipient_claim(
    tmp_path: Path,
) -> None:
    result = smoke_post_send_checkpoint(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["real_recipient_evidence"] = True
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PostSendCheckpointRehearsalError, match="real recipient evidence"):
        verify_post_send_rehearsal_receipt_file(receipt_path)
