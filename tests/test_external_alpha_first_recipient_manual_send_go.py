import json
from pathlib import Path

import pytest

from scripts.audit_external_alpha_operator_send_bypass import audit_operator_send_bypass
from scripts.check_external_alpha_first_recipient_manual_send_go import (
    MANUAL_SEND_GO_RECEIPT_NAME,
    FirstRecipientManualSendGoError,
    check_first_recipient_manual_send_go,
    verify_first_recipient_manual_send_go_receipt_file,
)
from scripts.check_external_alpha_first_recipient_send_preflight import (
    _preflight_receipt_checks,
    _receipt_body_sha256 as _preflight_receipt_body_sha256,
    check_first_recipient_send_preflight,
)
from scripts.prepare_external_alpha_first_recipient_send_workspace import prepare_first_recipient_send_workspace
from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet
from scripts.smoke_external_alpha_manual_send_go_rehearsal import smoke_manual_send_go_rehearsal


ROOT = Path(__file__).resolve().parents[1]


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


def test_external_alpha_first_recipient_manual_send_go_passes_after_all_gates(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    recipient_text, note_text = _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    preflight = check_first_recipient_send_preflight(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    bypass = audit_operator_send_bypass(tmp_path, workspace_dir=workspace)
    smoke_manual_send_go_rehearsal(tmp_path)

    result = check_first_recipient_manual_send_go(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert receipt_path.name == MANUAL_SEND_GO_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_first_recipient_manual_send_go_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["release"]["archive_sha256"] == preflight["archive_sha256"] == bypass["archive_sha256"]
    assert payload["gate_receipts"]["preflight"]["body_sha256"] == preflight["receipt_body_sha256"]
    assert payload["gate_receipts"]["operator_send_bypass_audit"]["body_sha256"] == bypass["receipt_body_sha256"]
    assert payload["gate_receipts"]["final_send_chain_audit"]["operator_bypass_audit_required"] is True
    assert payload["operator_packet"]["body_sha256"] == packet["operator_dispatch_packet_body_sha256"]
    assert payload["operator_packet"]["preflight_body_sha256"] == packet["operator_dispatch_packet_body_sha256"]
    assert payload["checks"]["operator_packet_ready_to_send_one"] is True
    assert payload["checks"]["operator_packet_body_hash_present"] is True
    assert payload["checks"]["preflight_operator_packet_file_expected"] is True
    assert payload["checks"]["preflight_operator_packet_body_matches_current_packet"] is True
    assert payload["checks"]["preflight_receipt_ready"] is True
    assert payload["checks"]["operator_bypass_audit_ready"] is True
    assert payload["checks"]["final_send_chain_ready"] is True
    assert payload["checks"]["final_send_chain_requires_bypass"] is True
    assert payload["checks"]["final_send_chain_bypass_hash_matches"] is True
    assert payload["checks"]["script_does_not_send_to_recipient"] is True
    assert all(payload["checks"].values())
    assert all(payload["manual_send_go_receipt_checks"].values())
    assert verify_first_recipient_manual_send_go_receipt_file(receipt_path)[
        "manual_send_go_receipt_body_sha256"
    ] == payload["manual_send_go_receipt_body_sha256"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized
    assert "Recipient identifier/contact goes here" not in serialized
    assert "Record the private channel" not in serialized
    assert "<private-send-channel>" not in serialized


def test_external_alpha_first_recipient_manual_send_go_blocks_until_preflight_ready(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    with pytest.raises(Exception):
        check_first_recipient_send_preflight(
            workspace,
            operator_packet_path=Path(packet_result["packet_json"]),
        )
    audit_operator_send_bypass(tmp_path, workspace_dir=workspace)
    smoke_manual_send_go_rehearsal(tmp_path)
    receipt_path = workspace / MANUAL_SEND_GO_RECEIPT_NAME

    with pytest.raises(FirstRecipientManualSendGoError, match="preflight_receipt_ready"):
        check_first_recipient_manual_send_go(
            workspace,
            output_dir=tmp_path,
            operator_packet_path=Path(packet_result["packet_json"]),
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_manual_send_go_receipt_file(receipt_path, require_go=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_BEFORE_MANUAL_SEND"
    assert payload["checks"]["preflight_receipt_ready"] is False
    assert payload["checks"]["preflight_private_files_ready"] is False
    assert payload["checks"]["operator_bypass_audit_ready"] is True
    assert payload["checks"]["final_send_chain_ready"] is True

    with pytest.raises(FirstRecipientManualSendGoError, match="manual send GO receipt is blocked"):
        verify_first_recipient_manual_send_go_receipt_file(receipt_path)


def test_external_alpha_first_recipient_manual_send_go_rejects_stale_preflight_operator_packet_body(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    check_first_recipient_send_preflight(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    preflight_path = workspace / "external-alpha-first-recipient-send-preflight-receipt.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight["operator_packet"]["body_sha256"] = "0" * 64
    preflight["first_recipient_send_preflight_receipt_body_sha256"] = _preflight_receipt_body_sha256(preflight)
    preflight["first_recipient_send_preflight_receipt_checks"] = _preflight_receipt_checks(preflight)
    preflight_path.write_text(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_operator_send_bypass(tmp_path, workspace_dir=workspace)
    smoke_manual_send_go_rehearsal(tmp_path)
    receipt_path = workspace / MANUAL_SEND_GO_RECEIPT_NAME

    with pytest.raises(
        FirstRecipientManualSendGoError,
        match="preflight_operator_packet_body_matches_current_packet",
    ):
        check_first_recipient_manual_send_go(
            workspace,
            output_dir=tmp_path,
            operator_packet_path=Path(packet_result["packet_json"]),
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_manual_send_go_receipt_file(receipt_path, require_go=False)

    assert payload["status"] == "fail"
    assert payload["checks"]["preflight_receipt_ready"] is True
    assert payload["checks"]["preflight_operator_packet_body_matches_current_packet"] is False
    assert payload["operator_packet"]["body_sha256"] == packet["operator_dispatch_packet_body_sha256"]
    assert payload["operator_packet"]["preflight_body_sha256"] == "0" * 64
