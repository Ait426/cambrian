import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_first_recipient_post_send_sequence import (
    POST_SEND_SEQUENCE_RECEIPT_NAME,
    FirstRecipientPostSendSequenceError,
    check_first_recipient_post_send_sequence,
    verify_first_recipient_post_send_sequence_receipt_file,
)
from scripts.check_external_alpha_first_recipient_pre_send_sequence import check_first_recipient_pre_send_sequence
from scripts.check_external_alpha_dispatch_record import DISPATCH_RECORD_JSON_NAME
from scripts.prepare_external_alpha_first_recipient_send_workspace import prepare_first_recipient_send_workspace
from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_external_alpha_first_recipient_post_send_sequence.py"


def _fill_required_private_send_files(workspace: Path, archive_sha256: str) -> tuple[str, str]:
    recipient_text = "alpha recipient private contact: one-recipient@example.invalid\n"
    note_text = (
        "private send channel: direct message\n"
        f"attachment sha256 checked: {archive_sha256}\n"
        "operator note: first external alpha one-recipient send only\n"
    )
    (workspace / "recipient-private.txt").write_text(recipient_text, encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(note_text, encoding="utf-8")
    return recipient_text, note_text


def _fill_ack(workspace: Path) -> str:
    ack_text = "CONFIRMED\n"
    (workspace / "recipient-ack-private.txt").write_text(ack_text, encoding="utf-8")
    return ack_text


def _write_builder_gold_path_share_receipt(path: Path) -> Path:
    payload = {
        "schema_version": "external_alpha_builder_gold_path_share_receipt_v0_1",
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "checks": {
            "builder_golden_path_completed": True,
            "manual_no_api_runner_used": True,
            "promotion_audit_lineage_verified": True,
            "raw_browser_storage_excluded": True,
        },
        "capabilities_verified": {
            "agent_pack_created": True,
            "manual_runner_receipt_created": True,
            "evolution_suggestion_created": True,
            "candidate_diff_report_created": True,
            "promoted_private_version_created": True,
            "promotion_audit_record_created": True,
            "private_hub_lineage_verified": True,
        },
        "proof_claim_allowed": False,
        "success_rate_claim_allowed": False,
        "sale_ready": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _prepare_ready_pre_send(tmp_path: Path) -> tuple[Path, Path, str, str]:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(packet_result["packet_json"])
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=packet_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    recipient_text, note_text = _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    check_first_recipient_pre_send_sequence(workspace, output_dir=tmp_path, operator_packet_path=packet_path)
    return workspace, packet_path, recipient_text, note_text


def test_external_alpha_first_recipient_post_send_sequence_records_sent_and_waits_for_ack(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)

    result = check_first_recipient_post_send_sequence(
        workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-17T01:00:00+00:00",
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT"
    assert receipt_path.name == POST_SEND_SEQUENCE_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_first_recipient_post_send_sequence_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["step_results"]["dispatch_record"]["verdict"] == "SENT_ONE_RECORDED"
    assert payload["step_results"]["recipient_ack"]["verdict"] == "WAITING_FOR_RECIPIENT"
    assert payload["post_send_state"]["sent_recorded"] is True
    assert payload["post_send_state"]["recipient_ack_status"] == "placeholder"
    assert payload["ack_summary"] == {
        "file": "recipient-ack-private.txt",
        "confirmed_reply_present": False,
        "exactly_one_acknowledgement": False,
        "local_paths_included": False,
        "next_action": (
            "Wait for exactly one CONFIRMED recipient acknowledgement, store it in the private workspace, "
            "then rerun this sequence."
        ),
        "raw_private_values_included": False,
        "required_for_current_command": False,
        "sha256_present": False,
        "status": "placeholder",
        "waiting_for_recipient": True,
    }
    assert payload["gate_receipts"]["dispatch_record"]["preflight"]["required"] is True
    assert payload["gate_receipts"]["dispatch_record"]["preflight"]["verified_standalone"] is True
    assert payload["policy"]["script_sends_to_recipient"] is False
    assert payload["policy"]["requires_preflight_receipt_for_dispatch_record"] is True
    assert payload["policy"]["requires_preflight_receipt_for_recipient_checkpoint"] is True
    assert all(payload["checks"].values())
    assert all(payload["post_send_sequence_receipt_checks"].values())
    assert verify_first_recipient_post_send_sequence_receipt_file(receipt_path)[
        "post_send_sequence_receipt_body_sha256"
    ] == payload["post_send_sequence_receipt_body_sha256"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized


def test_external_alpha_first_recipient_post_send_sequence_rejects_placeholder_sent_at(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)
    receipt_path = workspace / POST_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(FirstRecipientPostSendSequenceError, match="dispatch_recorded"):
        check_first_recipient_post_send_sequence(
            workspace,
            output_dir=tmp_path,
            sent_at_utc="<sent-at-utc>",
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["checks"]["dispatch_recorded"] is False
    assert payload["post_send_state"]["sent_recorded"] is False
    assert payload["step_results"]["dispatch_record"]["failed_checks"] == ["DispatchRecordError"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "<sent-at-utc>" not in serialized
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized


def test_external_alpha_first_recipient_post_send_sequence_records_checkpoint_when_ack_ready(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)
    ack_text = _fill_ack(workspace)

    result = check_first_recipient_post_send_sequence(
        workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-17T01:00:00+00:00",
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert payload["step_results"]["recipient_ack"]["verdict"] == "RECIPIENT_ACK_READY"
    assert payload["step_results"]["recipient_checkpoint"]["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert payload["post_send_state"]["recipient_ack_status"] == "ready"
    assert payload["private_input_fingerprints"]["recipient_ack_sha256"]
    assert payload["ack_summary"]["status"] == "ready"
    assert payload["ack_summary"]["confirmed_reply_present"] is True
    assert payload["ack_summary"]["exactly_one_acknowledgement"] is True
    assert payload["ack_summary"]["sha256_present"] is True
    assert payload["ack_summary"]["waiting_for_recipient"] is False
    assert payload["gate_receipts"]["recipient_checkpoint"]["body_sha256"]
    assert all(payload["checks"].values())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized
    assert ack_text.strip() not in serialized


def test_external_alpha_first_recipient_post_send_sequence_blocks_unconfirmed_ack(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)
    ack_text = "I opened the ZIP but did not confirm yet\n"
    (workspace / "recipient-ack-private.txt").write_text(ack_text, encoding="utf-8")
    receipt_path = workspace / POST_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(FirstRecipientPostSendSequenceError, match="recipient-ack-private.txt=unconfirmed"):
        check_first_recipient_post_send_sequence(
            workspace,
            output_dir=tmp_path,
            sent_at_utc="2026-05-17T01:00:00+00:00",
            require_recipient_checkpoint=True,
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["ack_summary"]["status"] == "unconfirmed"
    assert payload["ack_summary"]["confirmed_reply_present"] is False
    assert payload["ack_summary"]["exactly_one_acknowledgement"] is True
    assert payload["checks"]["recipient_ack_ready_when_required"] is False

    serialized = json.dumps(payload, ensure_ascii=False)
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized
    assert ack_text.strip() not in serialized


def test_external_alpha_first_recipient_post_send_sequence_confirms_gold_path(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, _recipient_text, _note_text = _prepare_ready_pre_send(tmp_path)
    _fill_ack(workspace)
    builder_receipt = _write_builder_gold_path_share_receipt(
        tmp_path / "external_alpha_builder_gold_path_share_receipt.json"
    )

    result = check_first_recipient_post_send_sequence(
        workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-17T01:00:00+00:00",
        builder_gold_path_share_receipt=builder_receipt,
        require_gold_path=True,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["step_results"]["recipient_checkpoint"]["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["gate_receipts"]["builder_gold_path_share_receipt"]["present"] is True
    assert payload["gate_receipts"]["builder_gold_path_share_receipt"]["file"] == (
        "external_alpha_builder_gold_path_share_receipt.json"
    )
    assert payload["checks"]["gold_path_confirmed_when_required"] is True
    assert payload["ack_summary"]["required_for_current_command"] is True
    assert str(builder_receipt) not in json.dumps(payload, ensure_ascii=False)


def test_external_alpha_first_recipient_post_send_sequence_blocks_without_preflight(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    receipt_path = workspace / POST_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(FirstRecipientPostSendSequenceError, match="dispatch_recorded"):
        check_first_recipient_post_send_sequence(
            workspace,
            output_dir=tmp_path,
            sent_at_utc="2026-05-17T01:00:00+00:00",
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)
    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["checks"]["dispatch_recorded"] is False
    assert payload["ack_summary"]["status"] == "placeholder"

    with pytest.raises(FirstRecipientPostSendSequenceError, match="post-send sequence receipt is blocked"):
        verify_first_recipient_post_send_sequence_receipt_file(receipt_path)


def test_external_alpha_first_recipient_post_send_sequence_blocks_missing_builder_receipt(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)
    receipt_path = workspace / POST_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(FirstRecipientPostSendSequenceError, match="builder_receipt_exists_when_provided"):
        check_first_recipient_post_send_sequence(
            workspace,
            output_dir=tmp_path,
            sent_at_utc="2026-05-17T01:00:00+00:00",
            builder_gold_path_share_receipt=tmp_path / "external_alpha_builder_gold_path_share_receipt.json",
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["checks"]["dispatch_recorded"] is True
    assert payload["checks"]["builder_receipt_exists_when_provided"] is False
    assert payload["post_send_state"]["sent_recorded"] is True
    assert payload["post_send_state"]["builder_gold_path_receipt_requested"] is True
    assert payload["post_send_state"]["builder_gold_path_receipt_present"] is False
    assert payload["gate_receipts"]["builder_gold_path_share_receipt"] == {
        "file": "external_alpha_builder_gold_path_share_receipt.json",
        "present": False,
        "requested": True,
        "sha256": None,
        "status": "missing",
    }

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized


def test_external_alpha_first_recipient_post_send_sequence_cli_passes_and_verifies(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, _recipient_text, _note_text = _prepare_ready_pre_send(tmp_path)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
            "--sent-at-utc",
            "2026-05-17T01:00:00+00:00",
        ],
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
    assert "[PASS] external alpha first-recipient post-send sequence" in output
    assert "verdict: SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT" in output
    assert "ack    : placeholder" in output
    assert "next   : Wait for exactly one CONFIRMED recipient acknowledgement" in output
    assert (workspace / POST_SEND_SEQUENCE_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify-receipt",
            str(workspace / POST_SEND_SEQUENCE_RECEIPT_NAME),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha first-recipient post-send sequence receipt verification" in verify_output


def test_external_alpha_first_recipient_post_send_sequence_cli_requires_sent_at_unless_verifying(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, _recipient_text, _note_text = _prepare_ready_pre_send(tmp_path)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "--sent-at-utc is required unless --verify-receipt is used" in output
    assert str(tmp_path) not in output


def test_external_alpha_first_recipient_post_send_sequence_cli_blocked_names_ack_status(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
            "--sent-at-utc",
            "2026-05-17T01:00:00+00:00",
            "--require-recipient-checkpoint",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "recipient-ack-private.txt=placeholder" in output
    assert "Wait for exactly one CONFIRMED recipient acknowledgement" in output
    assert str(ROOT) not in output
    assert str(tmp_path) not in output
    assert recipient_text.strip() not in output
    assert note_text.strip() not in output


def test_external_alpha_first_recipient_post_send_sequence_cli_rejects_placeholder_sent_at_safely(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
            "--sent-at-utc",
            "<sent-at-utc>",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    receipt_path = workspace / POST_SEND_SEQUENCE_RECEIPT_NAME
    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert result.returncode == 1, output
    assert "dispatch_recorded" in output
    assert "real UTC manual-send timestamp" not in output
    assert "<sent-at-utc>" not in output
    assert str(ROOT) not in output
    assert str(tmp_path) not in output
    assert recipient_text.strip() not in output
    assert note_text.strip() not in output
    dispatch_payload = json.loads((tmp_path / DISPATCH_RECORD_JSON_NAME).read_text(encoding="utf-8"))
    assert dispatch_payload["verdict"] == "READY_TO_SEND_ONE"
    assert dispatch_payload["dispatch_record"]["sent_recorded"] is False
    assert dispatch_payload["dispatch_record"]["sent_at_utc"] is None
    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["checks"]["dispatch_recorded"] is False
    assert payload["post_send_state"]["sent_recorded"] is False
    assert payload["step_results"]["dispatch_record"]["failed_checks"] == ["DispatchRecordError"]
    assert "<sent-at-utc>" not in json.dumps(payload, ensure_ascii=False)


def test_external_alpha_first_recipient_post_send_sequence_cli_rejects_missing_builder_receipt_safely(
    tmp_path: Path,
) -> None:
    workspace, _packet_path, recipient_text, note_text = _prepare_ready_pre_send(tmp_path)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
            "--sent-at-utc",
            "2026-05-17T01:00:00+00:00",
            "--builder-gold-path-share-receipt",
            "<external_alpha_builder_gold_path_share_receipt.json>",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    receipt_path = workspace / POST_SEND_SEQUENCE_RECEIPT_NAME
    payload = verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)

    assert result.returncode == 1, output
    assert "builder_receipt_exists_when_provided" in output
    assert "<external_alpha_builder_gold_path_share_receipt.json>" not in output
    assert str(ROOT) not in output
    assert str(tmp_path) not in output
    assert recipient_text.strip() not in output
    assert note_text.strip() not in output
    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_AFTER_MANUAL_SEND"
    assert payload["checks"]["builder_receipt_exists_when_provided"] is False
    assert payload["gate_receipts"]["builder_gold_path_share_receipt"]["status"] == "missing"
    assert "<external_alpha_builder_gold_path_share_receipt.json>" not in json.dumps(payload, ensure_ascii=False)
