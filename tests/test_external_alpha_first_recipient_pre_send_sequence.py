import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_first_recipient_pre_send_sequence import (
    PRE_SEND_SEQUENCE_RECEIPT_NAME,
    FirstRecipientPreSendSequenceError,
    check_first_recipient_pre_send_sequence,
    verify_first_recipient_pre_send_sequence_receipt_file,
)
from scripts.prepare_external_alpha_first_recipient_send_workspace import prepare_first_recipient_send_workspace
from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet
from scripts.smoke_external_alpha_manual_send_go_rehearsal import smoke_manual_send_go_rehearsal


ROOT = Path(__file__).resolve().parents[1]
SEQUENCE_SCRIPT = ROOT / "scripts" / "check_external_alpha_first_recipient_pre_send_sequence.py"


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


def _prepare_operator_packet_with_final_rehearsal(tmp_path: Path) -> dict[str, str]:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    smoke_manual_send_go_rehearsal(tmp_path)
    return packet_result


def test_external_alpha_first_recipient_pre_send_sequence_goes_ready_when_private_fields_ready(
    tmp_path: Path,
) -> None:
    packet_result = _prepare_operator_packet_with_final_rehearsal(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    recipient_text, note_text = _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])

    result = check_first_recipient_pre_send_sequence(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert receipt_path.name == PRE_SEND_SEQUENCE_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_first_recipient_pre_send_sequence_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["release"]["archive_sha256"] == result["archive_sha256"]
    assert payload["step_results"]["first_recipient_workspace"]["status"] == "pass"
    assert payload["step_results"]["preflight"]["verdict"] == "FIRST_RECIPIENT_PRE_SEND_READY"
    assert payload["step_results"]["operator_bypass_audit"]["verdict"] == "NO_OPERATOR_PREFLIGHT_BYPASS"
    assert payload["step_results"]["final_send_chain_audit"]["verdict"] == "READY_TO_SEND_ONE"
    assert payload["step_results"]["manual_send_go"]["verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert payload["blocked_steps"] == []
    assert payload["blocking_summary"]["blocked_steps"] == []
    assert payload["blocking_summary"]["blocked_checks"] == []
    assert payload["blocking_summary"]["all_required_private_files_ready"] is True
    assert payload["blocking_summary"]["required_private_files"] == [
        {
            "file": "recipient-private.txt",
            "contains_release_hash": False,
            "exactly_one_recipient": True,
            "mentions_channel": False,
            "minimum_signal_present": True,
            "required_before_manual_send": True,
            "sha256_present": True,
            "status": "ready",
        },
        {
            "file": "operator-dispatch-note-private.md",
            "contains_release_hash": True,
            "exactly_one_recipient": False,
            "mentions_channel": True,
            "minimum_signal_present": False,
            "required_before_manual_send": True,
            "sha256_present": True,
            "status": "ready",
        },
    ]
    assert payload["policy"]["script_sends_to_recipient"] is False
    assert payload["policy"]["manual_operator_dispatch_required"] is True
    assert payload["policy"]["max_recipients"] == 1
    assert all(payload["checks"].values())
    assert all(payload["pre_send_sequence_receipt_checks"].values())
    assert verify_first_recipient_pre_send_sequence_receipt_file(receipt_path)[
        "pre_send_sequence_receipt_body_sha256"
    ] == payload["pre_send_sequence_receipt_body_sha256"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized


def test_external_alpha_first_recipient_pre_send_sequence_blocks_until_private_fields_ready(
    tmp_path: Path,
) -> None:
    packet_result = _prepare_operator_packet_with_final_rehearsal(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    receipt_path = workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(FirstRecipientPreSendSequenceError, match="preflight_ready"):
        check_first_recipient_pre_send_sequence(
            workspace,
            output_dir=tmp_path,
            operator_packet_path=Path(packet_result["packet_json"]),
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_pre_send_sequence_receipt_file(receipt_path, require_ready=False)

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_BEFORE_MANUAL_SEND"
    assert "preflight" in payload["blocked_steps"]
    assert "manual_send_go" in payload["blocked_steps"]
    assert payload["blocking_summary"]["blocked_steps"] == ["preflight", "manual_send_go"]
    assert "preflight_ready" in payload["blocking_summary"]["blocked_checks"]
    assert "manual_send_go_ready" in payload["blocking_summary"]["blocked_checks"]
    assert payload["blocking_summary"]["all_required_private_files_ready"] is False
    assert payload["blocking_summary"]["required_private_files"] == [
        {
            "file": "recipient-private.txt",
            "contains_release_hash": False,
            "exactly_one_recipient": False,
            "mentions_channel": False,
            "minimum_signal_present": False,
            "required_before_manual_send": True,
            "sha256_present": False,
            "status": "placeholder",
        },
        {
            "file": "operator-dispatch-note-private.md",
            "contains_release_hash": False,
            "exactly_one_recipient": False,
            "mentions_channel": False,
            "minimum_signal_present": False,
            "required_before_manual_send": True,
            "sha256_present": False,
            "status": "placeholder",
        },
    ]
    assert payload["checks"]["first_recipient_workspace_ready"] is True
    assert payload["checks"]["preflight_ready"] is False
    assert payload["checks"]["operator_bypass_audit_ready"] is True
    assert payload["checks"]["final_send_chain_ready"] is True
    assert payload["checks"]["manual_send_go_ready"] is False

    with pytest.raises(FirstRecipientPreSendSequenceError, match="pre-send sequence receipt is blocked"):
        verify_first_recipient_pre_send_sequence_receipt_file(receipt_path)


def test_external_alpha_first_recipient_pre_send_sequence_cli_blocked_names_private_file_statuses(
    tmp_path: Path,
) -> None:
    packet_result = _prepare_operator_packet_with_final_rehearsal(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SEQUENCE_SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
            "--operator-packet",
            str(packet_result["packet_json"]),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=90,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "required private files: recipient-private.txt=placeholder" in output
    assert "operator-dispatch-note-private.md=placeholder" in output
    assert "minimum_signal=false" in output
    assert "exactly_one_recipient=false" in output
    assert "mentions_channel=false" in output
    assert "contains_release_hash=false" in output
    assert "Fill recipient-private.txt and operator-dispatch-note-private.md" in output
    assert str(tmp_path) not in output
    assert "Recipient identifier/contact goes here" not in output
    assert "Record the private channel" not in output
    assert "<private-send-channel>" not in output


def test_external_alpha_first_recipient_pre_send_sequence_names_partial_private_note_requirements(
    tmp_path: Path,
) -> None:
    packet_result = _prepare_operator_packet_with_final_rehearsal(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    (workspace / "recipient-private.txt").write_text(
        "alpha recipient private contact: one-recipient@example.invalid\n",
        encoding="utf-8",
    )
    (workspace / "operator-dispatch-note-private.md").write_text(
        "private send channel: direct message\noperator checked attachment before send\n",
        encoding="utf-8",
    )
    receipt_path = workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(FirstRecipientPreSendSequenceError, match="contains_release_hash=false"):
        check_first_recipient_pre_send_sequence(
            workspace,
            output_dir=tmp_path,
            operator_packet_path=Path(packet_result["packet_json"]),
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_pre_send_sequence_receipt_file(receipt_path, require_ready=False)
    private_files = {item["file"]: item for item in payload["blocking_summary"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert private_files["recipient-private.txt"]["minimum_signal_present"] is True
    assert private_files["recipient-private.txt"]["exactly_one_recipient"] is True
    assert private_files["operator-dispatch-note-private.md"]["status"] == "ready"
    assert private_files["operator-dispatch-note-private.md"]["mentions_channel"] is True
    assert private_files["operator-dispatch-note-private.md"]["contains_release_hash"] is False


def test_external_alpha_first_recipient_pre_send_sequence_blocks_multiple_recipient_lines(
    tmp_path: Path,
) -> None:
    packet_result = _prepare_operator_packet_with_final_rehearsal(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    (workspace / "recipient-private.txt").write_text(
        "alpha recipient private contact: one-recipient@example.invalid\n"
        "alpha recipient private contact: second-recipient@example.invalid\n",
        encoding="utf-8",
    )
    receipt_path = workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME

    with pytest.raises(FirstRecipientPreSendSequenceError, match="exactly_one_recipient=false"):
        check_first_recipient_pre_send_sequence(
            workspace,
            output_dir=tmp_path,
            operator_packet_path=Path(packet_result["packet_json"]),
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_pre_send_sequence_receipt_file(receipt_path, require_ready=False)
    private_files = {item["file"]: item for item in payload["blocking_summary"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert payload["checks"]["preflight_ready"] is False
    assert private_files["recipient-private.txt"]["status"] == "ready"
    assert private_files["recipient-private.txt"]["minimum_signal_present"] is True
    assert private_files["recipient-private.txt"]["exactly_one_recipient"] is False

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "one-recipient@example.invalid" not in serialized
    assert "second-recipient@example.invalid" not in serialized


def test_external_alpha_first_recipient_pre_send_sequence_refreshes_missing_final_rehearsal(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    receipt_path = workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME

    result = check_first_recipient_pre_send_sequence(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=Path(packet_result["packet_json"]),
        receipt_path=receipt_path,
    )

    payload = verify_first_recipient_pre_send_sequence_receipt_file(receipt_path, require_ready=True)

    assert result["verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert payload["checks"]["preflight_ready"] is True
    assert payload["checks"]["final_send_chain_ready"] is True
    assert payload["checks"]["manual_send_go_ready"] is True
    assert payload["blocking_summary"]["all_required_private_files_ready"] is True
    assert payload["blocking_summary"]["next_action"] == "Manually send the ZIP and copy-paste message to exactly one recipient."
    assert (tmp_path / "cambrian-agent-platform-external-alpha-manual-send-go-rehearsal-receipt.json").is_file()


def test_external_alpha_first_recipient_pre_send_sequence_cli_passes_and_verifies(tmp_path: Path) -> None:
    packet_result = _prepare_operator_packet_with_final_rehearsal(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SEQUENCE_SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--output-dir",
            str(tmp_path),
            "--operator-packet",
            str(packet_result["packet_json"]),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=90,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha first-recipient pre-send sequence" in output
    assert "verdict: READY_TO_MANUALLY_SEND_ONE" in output
    assert (workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(SEQUENCE_SCRIPT),
            "--verify-receipt",
            str(workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME),
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
    assert "[PASS] external alpha first-recipient pre-send sequence receipt verification" in verify_output


def test_external_alpha_first_recipient_pre_send_sequence_rejects_tampering(tmp_path: Path) -> None:
    packet_result = _prepare_operator_packet_with_final_rehearsal(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=Path(packet_result["packet_json"]))
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    result = check_first_recipient_pre_send_sequence(
        workspace,
        output_dir=tmp_path,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["max_recipients"] = 2
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(FirstRecipientPreSendSequenceError):
        verify_first_recipient_pre_send_sequence_receipt_file(receipt_path)
