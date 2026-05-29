import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.check_external_alpha_first_recipient_operator_status as operator_status
from scripts.check_external_alpha_first_recipient_operator_status import (
    OPERATOR_STATUS_RECEIPT_NAME,
    FirstRecipientOperatorStatusError,
    _final_chain_depth,
    check_first_recipient_operator_status,
    verify_first_recipient_operator_status_receipt_file,
)
from scripts.check_external_alpha_first_recipient_post_send_sequence import (
    check_first_recipient_post_send_sequence,
)
from scripts.check_external_alpha_first_recipient_manual_send_go import (
    MANUAL_SEND_GO_RECEIPT_NAME,
    _receipt_body_sha256 as _manual_send_go_receipt_body_sha256,
    _receipt_checks as _manual_send_go_receipt_checks,
)
from scripts.check_external_alpha_first_recipient_pre_send_sequence import (
    PRE_SEND_SEQUENCE_RECEIPT_NAME,
    _receipt_body_sha256 as _pre_send_sequence_receipt_body_sha256,
    check_first_recipient_pre_send_sequence,
)
from scripts.prepare_external_alpha_first_recipient_send_workspace import (
    FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME,
    _receipt_body_sha256 as _workspace_receipt_body_sha256,
    prepare_first_recipient_send_workspace,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_external_alpha_first_recipient_operator_status.py"


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


def _rewrite_receipt_archive_hash(
    path: Path,
    *,
    body_key: str,
    body_hash_fn,
    archive_sha256: str,
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["release"]["archive_sha256"] = archive_sha256
    payload[body_key] = body_hash_fn(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _prepare_workspace(tmp_path: Path) -> tuple[Path, Path]:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(packet_result["packet_json"])
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=packet_path)
    return workspace, packet_path


def test_external_alpha_first_recipient_operator_status_blocks_on_private_fields(tmp_path: Path) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert receipt_path.name == OPERATOR_STATUS_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_first_recipient_operator_status_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["private_file_summary"][:2] == [
        {"file": "recipient-private.txt", "sha256_present": False, "status": "placeholder"},
        {"file": "operator-dispatch-note-private.md", "sha256_present": False, "status": "placeholder"},
    ]
    assert payload["private_send_requirements"] == {
        "operator_dispatch_note_confirms_release_hash": False,
        "operator_dispatch_note_mentions_channel": False,
        "operator_dispatch_note_ready": False,
        "recipient_private_exactly_one_contact": False,
        "recipient_private_minimum_signal": False,
        "recipient_private_ready": False,
    }
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["operator_packet_ready"]["done"] is True
    assert checklist["private_workspace_ready"]["done"] is True
    assert checklist["first_recipient_workspace_ready"]["done"] is True
    assert isinstance(checklist["final_send_chain_ready"]["done"], bool)
    assert checklist["recipient_private_ready"]["done"] is False
    assert checklist["operator_note_names_channel"]["done"] is False
    assert checklist["operator_note_confirms_release_hash"]["done"] is False
    assert checklist["pre_send_sequence_ready"]["done"] is False
    assert payload["operator_launch_snapshot"] == {
        "stage": "FILL_PRIVATE_FIELDS",
        "send_state": "BLOCKED",
        "manual_send_allowed": False,
        "manual_operator_dispatch_required": True,
        "script_sends_to_recipient": False,
        "max_recipients": 1,
        "release_archive_sha256": payload["release"]["archive_sha256"],
        "final_send_chain_ready": payload["final_send_chain_audit"]["status"] == "pass",
        "private_fields_ready": False,
        "pre_send_sequence_ready": False,
        "open_gate_ids": [
            "operator_note_confirms_release_hash",
            "operator_note_names_channel",
            "recipient_private_ready",
        ],
        "next_safe_action": payload["operator_next_action"],
        "safe_to_share": True,
    }
    assert payload["checks"]["operator_safe_checklist_controlled"] is True
    assert payload["checks"]["operator_launch_snapshot_controlled"] is True
    assert isinstance(payload["final_send_chain_audit"]["chain_depth"], int)
    assert payload["policy"]["script_sends_to_recipient"] is False
    assert payload["policy"]["manual_operator_dispatch_required"] is True
    assert payload["policy"]["max_recipients"] == 1
    assert all(payload["checks"].values())
    assert all(payload["operator_status_receipt_checks"].values())
    assert verify_first_recipient_operator_status_receipt_file(receipt_path)[
        "operator_status_receipt_body_sha256"
    ] == payload["operator_status_receipt_body_sha256"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "Recipient identifier/contact goes here" not in serialized
    assert "Record the private channel" not in serialized
    assert "<private-send-channel>" not in serialized


def test_external_alpha_first_recipient_operator_status_reports_ready_to_send(tmp_path: Path) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    recipient_text, note_text = _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    check_first_recipient_pre_send_sequence(workspace, output_dir=tmp_path, operator_packet_path=packet_path)

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert payload["gate_receipts"]["pre_send_sequence"]["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert (
        payload["gate_receipts"]["manual_send_go"]["operator_packet"]["body_sha256"]
        == packet["operator_dispatch_packet_body_sha256"]
    )
    assert (
        payload["gate_receipts"]["manual_send_go"]["operator_packet"]["preflight_body_sha256"]
        == packet["operator_dispatch_packet_body_sha256"]
    )
    assert all(payload["private_send_requirements"].values())
    assert payload["private_file_summary"][0]["sha256_present"] is True
    assert payload["private_file_summary"][1]["sha256_present"] is True
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["recipient_private_ready"]["done"] is True
    assert checklist["operator_note_names_channel"]["done"] is True
    assert checklist["operator_note_confirms_release_hash"]["done"] is True
    assert checklist["pre_send_sequence_ready"]["done"] is True
    assert checklist["manual_send_go_operator_packet_bound"]["done"] is True
    assert checklist["first_recipient_workspace_ready"]["done"] is True
    assert checklist["manual_send_recorded"]["done"] is False
    assert payload["operator_launch_snapshot"]["send_state"] == "MANUAL_SEND_ALLOWED_ONE"
    assert payload["operator_launch_snapshot"]["manual_send_allowed"] is True
    assert payload["operator_launch_snapshot"]["final_send_chain_ready"] is True
    assert payload["operator_launch_snapshot"]["private_fields_ready"] is True
    assert payload["operator_launch_snapshot"]["pre_send_sequence_ready"] is True
    assert payload["operator_launch_snapshot"]["open_gate_ids"] == ["manual_send_recorded"]
    assert "Manually send exactly one ZIP" in payload["operator_next_action"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized


@pytest.mark.parametrize(
    "channel_line",
    [
        "private send channel:\n",
        "private send channel:   \n",
        "channel:\n",
    ],
)
def test_external_alpha_first_recipient_operator_status_blocks_empty_channel_value(
    tmp_path: Path,
    channel_line: str,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    (workspace / "recipient-private.txt").write_text(
        "alpha recipient private contact: one-recipient@example.invalid\n",
        encoding="utf-8",
    )
    (workspace / "operator-dispatch-note-private.md").write_text(
        f"{channel_line}attachment sha256 checked: {packet['release']['archive_sha256']}\n"
        "operator note: first external alpha one-recipient send only\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}

    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert payload["private_send_requirements"]["recipient_private_ready"] is True
    assert payload["private_send_requirements"]["operator_dispatch_note_ready"] is True
    assert payload["private_send_requirements"]["operator_dispatch_note_mentions_channel"] is False
    assert payload["private_send_requirements"]["operator_dispatch_note_confirms_release_hash"] is True
    assert checklist["recipient_private_ready"]["done"] is True
    assert checklist["operator_note_names_channel"]["done"] is False
    assert checklist["operator_note_confirms_release_hash"]["done"] is True
    assert "operator_note_names_channel" in payload["operator_launch_snapshot"]["open_gate_ids"]


def test_external_alpha_first_recipient_operator_status_blocks_placeholder_like_recipient(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    (workspace / "recipient-private.txt").write_text("<recipient>\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        "private send channel: direct message\n"
        f"attachment sha256 checked: {packet['release']['archive_sha256']}\n"
        "operator note: first external alpha one-recipient send only\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}

    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert payload["private_send_requirements"]["recipient_private_ready"] is False
    assert payload["private_send_requirements"]["operator_dispatch_note_ready"] is True
    assert payload["private_send_requirements"]["operator_dispatch_note_mentions_channel"] is True
    assert payload["private_send_requirements"]["operator_dispatch_note_confirms_release_hash"] is True
    assert payload["private_file_summary"][0] == {
        "file": "recipient-private.txt",
        "sha256_present": False,
        "status": "placeholder",
    }
    assert checklist["recipient_private_ready"]["done"] is False
    assert checklist["operator_note_names_channel"]["done"] is True
    assert "recipient_private_ready" in payload["operator_launch_snapshot"]["open_gate_ids"]


def test_external_alpha_first_recipient_operator_status_blocks_stale_pre_send_receipts(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    current_archive_sha256 = packet["release"]["archive_sha256"]
    stale_archive_sha256 = "0" * 64
    _fill_required_private_send_files(workspace, current_archive_sha256)
    check_first_recipient_pre_send_sequence(workspace, output_dir=tmp_path, operator_packet_path=packet_path)
    _rewrite_receipt_archive_hash(
        workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME,
        body_key="pre_send_sequence_receipt_body_sha256",
        body_hash_fn=_pre_send_sequence_receipt_body_sha256,
        archive_sha256=stale_archive_sha256,
    )
    _rewrite_receipt_archive_hash(
        workspace / MANUAL_SEND_GO_RECEIPT_NAME,
        body_key="manual_send_go_receipt_body_sha256",
        body_hash_fn=_manual_send_go_receipt_body_sha256,
        archive_sha256=stale_archive_sha256,
    )

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "RUN_PRE_SEND_SEQUENCE"
    assert payload["release"]["archive_sha256"] == current_archive_sha256
    assert payload["gate_receipts"]["pre_send_sequence"]["status"] == "pass"
    assert payload["gate_receipts"]["pre_send_sequence"]["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert payload["gate_receipts"]["pre_send_sequence"]["release_archive_sha256"] == stale_archive_sha256
    assert payload["gate_receipts"]["manual_send_go"]["status"] == "pass"
    assert payload["gate_receipts"]["manual_send_go"]["verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert payload["gate_receipts"]["manual_send_go"]["release_archive_sha256"] == stale_archive_sha256
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["recipient_private_ready"]["done"] is True
    assert checklist["operator_note_names_channel"]["done"] is True
    assert checklist["operator_note_confirms_release_hash"]["done"] is True
    assert checklist["pre_send_sequence_ready"]["done"] is False
    assert payload["operator_launch_snapshot"]["send_state"] == "BLOCKED"
    assert payload["operator_launch_snapshot"]["manual_send_allowed"] is False
    assert payload["operator_launch_snapshot"]["private_fields_ready"] is True
    assert payload["operator_launch_snapshot"]["pre_send_sequence_ready"] is False
    assert payload["operator_launch_snapshot"]["open_gate_ids"] == ["pre_send_sequence_ready"]
    assert "check_external_alpha_first_recipient_pre_send_sequence.py" in payload["operator_next_action"]


def test_external_alpha_first_recipient_operator_status_blocks_manual_send_go_operator_packet_drift(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    check_first_recipient_pre_send_sequence(workspace, output_dir=tmp_path, operator_packet_path=packet_path)

    manual_send_go_path = workspace / MANUAL_SEND_GO_RECEIPT_NAME
    manual_send_go = json.loads(manual_send_go_path.read_text(encoding="utf-8"))
    manual_send_go["operator_packet"]["body_sha256"] = "0" * 64
    manual_send_go["manual_send_go_receipt_body_sha256"] = _manual_send_go_receipt_body_sha256(manual_send_go)
    manual_send_go["manual_send_go_receipt_checks"] = _manual_send_go_receipt_checks(manual_send_go)
    manual_send_go_path.write_text(
        json.dumps(manual_send_go, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "RUN_PRE_SEND_SEQUENCE"
    assert payload["gate_receipts"]["manual_send_go"]["status"] == "pass"
    assert payload["gate_receipts"]["manual_send_go"]["verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert payload["gate_receipts"]["manual_send_go"]["operator_packet"]["body_sha256"] == "0" * 64
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["manual_send_go_operator_packet_bound"]["done"] is False
    assert checklist["pre_send_sequence_ready"]["done"] is False
    assert payload["operator_launch_snapshot"]["send_state"] == "BLOCKED"
    assert payload["operator_launch_snapshot"]["manual_send_allowed"] is False
    assert payload["operator_launch_snapshot"]["open_gate_ids"] == [
        "manual_send_go_operator_packet_bound",
        "pre_send_sequence_ready",
    ]


def test_external_alpha_first_recipient_operator_status_blocks_stale_first_recipient_workspace(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    workspace_receipt_path = workspace / FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME
    workspace_receipt = json.loads(workspace_receipt_path.read_text(encoding="utf-8"))
    workspace_receipt["release"]["archive_sha256"] = "0" * 64
    workspace_receipt["first_recipient_send_workspace_receipt_body_sha256"] = _workspace_receipt_body_sha256(
        workspace_receipt
    )
    workspace_receipt_path.write_text(
        json.dumps(workspace_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "PREPARE_PRIVATE_WORKSPACE"
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["private_workspace_ready"]["done"] is True
    assert checklist["first_recipient_workspace_ready"]["done"] is False
    assert payload["operator_launch_snapshot"]["send_state"] == "BLOCKED"
    assert payload["operator_launch_snapshot"]["manual_send_allowed"] is False
    assert payload["operator_launch_snapshot"]["open_gate_ids"] == ["first_recipient_workspace_ready"]
    assert "prepare_external_alpha_first_recipient_send_workspace.py" in payload["operator_next_action"]


def test_external_alpha_first_recipient_operator_status_names_blocked_final_audit_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])

    def blocked_final_audit(_output_dir: Path, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError(
            "final send-chain audit failed: "
            "release_sources_match_current_manifest, final_chain_complete"
        )

    monkeypatch.setattr(operator_status, "audit_send_chain", blocked_final_audit)

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "CHECK_RELEASE_CHAIN"
    assert payload["final_send_chain_audit"]["failure_summary"] == "failed_checks"
    assert payload["final_send_chain_audit"]["failed_checks"] == [
        "release_sources_match_current_manifest",
        "final_chain_complete",
    ]
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["final_send_chain_ready"]["done"] is False
    assert "release_sources_match_current_manifest" in checklist["final_send_chain_ready"]["safe_next_action"]
    assert payload["checks"]["final_audit_summary_controlled"] is True
    assert verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))[
        "operator_status_receipt_body_sha256"
    ] == payload["operator_status_receipt_body_sha256"]


def test_external_alpha_first_recipient_operator_status_blocks_partial_operator_note(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    (workspace / "recipient-private.txt").write_text(
        "alpha recipient private contact: one-recipient@example.invalid\n",
        encoding="utf-8",
    )
    (workspace / "operator-dispatch-note-private.md").write_text(
        "private send channel: direct message\noperator checked attachment before send\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert payload["private_send_requirements"]["recipient_private_minimum_signal"] is True
    assert payload["private_send_requirements"]["recipient_private_exactly_one_contact"] is True
    assert payload["private_send_requirements"]["operator_dispatch_note_mentions_channel"] is True
    assert payload["private_send_requirements"]["operator_dispatch_note_confirms_release_hash"] is False
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["recipient_private_ready"]["done"] is True
    assert checklist["operator_note_names_channel"]["done"] is True
    assert checklist["operator_note_confirms_release_hash"]["done"] is False
    archive_sha256 = json.loads(packet_path.read_text(encoding="utf-8"))["release"]["archive_sha256"]
    assert f"release ZIP sha256 {archive_sha256}" in payload["operator_next_action"]
    assert verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))[
        "operator_status_receipt_body_sha256"
    ] == payload["operator_status_receipt_body_sha256"]


def test_external_alpha_first_recipient_operator_status_blocks_multiple_recipient_lines(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    (workspace / "recipient-private.txt").write_text(
        "alpha recipient private contact: one-recipient@example.invalid\n"
        "alpha recipient private contact: second-recipient@example.invalid\n",
        encoding="utf-8",
    )

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "FILL_PRIVATE_FIELDS"
    assert payload["private_send_requirements"]["recipient_private_ready"] is True
    assert payload["private_send_requirements"]["recipient_private_minimum_signal"] is True
    assert payload["private_send_requirements"]["recipient_private_exactly_one_contact"] is False
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["recipient_private_ready"]["done"] is False

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "one-recipient@example.invalid" not in serialized
    assert "second-recipient@example.invalid" not in serialized


def test_external_alpha_first_recipient_operator_status_tracks_post_send_ack_and_gold_path(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    check_first_recipient_pre_send_sequence(workspace, output_dir=tmp_path, operator_packet_path=packet_path)
    check_first_recipient_post_send_sequence(
        workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-17T01:00:00+00:00",
    )

    waiting = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    waiting_payload = json.loads(Path(waiting["receipt_json"]).read_text(encoding="utf-8"))
    assert waiting["verdict"] == "WAITING_FOR_RECIPIENT_ACK"
    assert waiting_payload["private_file_summary"][2] == {
        "file": "recipient-ack-private.txt",
        "sha256_present": False,
        "status": "placeholder",
    }
    waiting_checklist = {item["id"]: item for item in waiting_payload["operator_safe_checklist"]}
    assert waiting_checklist["manual_send_recorded"]["done"] is True
    assert waiting_checklist["recipient_ack_ready"]["done"] is False

    _fill_ack(workspace)
    ack_ready = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    assert ack_ready["verdict"] == "RUN_POST_SEND_SEQUENCE_WITH_ACK"
    ack_ready_payload = json.loads(Path(ack_ready["receipt_json"]).read_text(encoding="utf-8"))
    ack_ready_checklist = {item["id"]: item for item in ack_ready_payload["operator_safe_checklist"]}
    assert ack_ready_checklist["recipient_ack_ready"]["done"] is True
    assert ack_ready_payload["private_file_summary"][2] == {
        "file": "recipient-ack-private.txt",
        "status": "ready",
        "sha256_present": True,
        "confirmed_reply_present": True,
        "exactly_one_acknowledgement": True,
    }

    builder_receipt = _write_builder_gold_path_share_receipt(
        tmp_path / "external_alpha_builder_gold_path_share_receipt.json"
    )
    check_first_recipient_post_send_sequence(
        workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-17T01:00:00+00:00",
        builder_gold_path_share_receipt=builder_receipt,
        require_gold_path=True,
    )
    confirmed = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    confirmed_payload = json.loads(Path(confirmed["receipt_json"]).read_text(encoding="utf-8"))

    assert confirmed["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert confirmed_payload["gate_receipts"]["post_send_sequence"]["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert "Collect controlled pilot feedback" in confirmed_payload["operator_next_action"]

    serialized = json.dumps(confirmed_payload, ensure_ascii=False)
    assert str(builder_receipt) not in serialized


def test_external_alpha_first_recipient_operator_status_waits_on_unconfirmed_ack(
    tmp_path: Path,
) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    check_first_recipient_pre_send_sequence(workspace, output_dir=tmp_path, operator_packet_path=packet_path)
    check_first_recipient_post_send_sequence(
        workspace,
        output_dir=tmp_path,
        sent_at_utc="2026-05-17T01:00:00+00:00",
    )

    raw_ack = "I opened the ZIP but did not confirm yet\n"
    (workspace / "recipient-ack-private.txt").write_text(raw_ack, encoding="utf-8")

    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    payload = json.loads(Path(result["receipt_json"]).read_text(encoding="utf-8"))

    assert result["verdict"] == "WAITING_FOR_RECIPIENT_ACK"
    ack_summary = payload["private_file_summary"][2]
    assert ack_summary == {
        "file": "recipient-ack-private.txt",
        "status": "unconfirmed",
        "sha256_present": False,
        "confirmed_reply_present": False,
        "exactly_one_acknowledgement": True,
    }
    checklist = {item["id"]: item for item in payload["operator_safe_checklist"]}
    assert checklist["recipient_ack_ready"]["done"] is False
    assert "exactly one CONFIRMED recipient acknowledgement" in payload["operator_next_action"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert raw_ack.strip() not in serialized


def test_external_alpha_first_recipient_operator_status_cli_passes_and_verifies(tmp_path: Path) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
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
            "--operator-packet",
            str(packet_path),
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
    archive_sha256 = json.loads(packet_path.read_text(encoding="utf-8"))["release"]["archive_sha256"]
    assert result.returncode == 0, output
    assert "[PASS] external alpha first-recipient operator status" in output
    assert "verdict: FILL_PRIVATE_FIELDS" in output
    assert (
        "next   : Fill recipient-private.txt with exactly one non-empty recipient contact, then make "
        f"operator-dispatch-note-private.md name the private send channel and include release ZIP sha256 {archive_sha256} "
        "before running the pre-send sequence."
        in output
    )
    assert "send   : BLOCKED" in output
    assert "private: recipient-private.txt=placeholder, operator-dispatch-note-private.md=placeholder" in output
    assert "open gates:" in output
    assert "- recipient_private_ready: Replace recipient-private.txt placeholder with exactly one recipient contact." in output
    assert "- operator_note_names_channel: Make operator-dispatch-note-private.md name the private send channel." in output
    assert (
        f"- operator_note_confirms_release_hash: Make operator-dispatch-note-private.md include release ZIP sha256 {archive_sha256}."
        in output
    )
    assert f"runbook: {workspace / 'SEND_ONE_NOW_PRIVATE.md'}" in output
    assert (workspace / OPERATOR_STATUS_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify-receipt",
            str(workspace / OPERATOR_STATUS_RECEIPT_NAME),
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
    assert "[PASS] external alpha first-recipient operator status receipt verification" in verify_output
    assert "open gates:" in verify_output
    assert f"runbook: {workspace / 'SEND_ONE_NOW_PRIVATE.md'}" in verify_output


def test_external_alpha_first_recipient_operator_status_rejects_tampering(tmp_path: Path) -> None:
    workspace, packet_path = _prepare_workspace(tmp_path)
    result = check_first_recipient_operator_status(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=packet_path,
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["max_recipients"] = 2
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(FirstRecipientOperatorStatusError):
        verify_first_recipient_operator_status_receipt_file(receipt_path)


def test_external_alpha_first_recipient_operator_status_prefers_final_chain_depth() -> None:
    assert _final_chain_depth({"final_chain_depth": 12, "artifact_chain": []}) == 12
    assert _final_chain_depth({"artifact_chain": [{"kind": "release_zip"}]}) == 1
