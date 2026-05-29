import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_first_recipient_send_preflight import (
    PREFLIGHT_RECEIPT_NAME,
    FirstRecipientSendPreflightError,
    _recipient_value_is_real,
    check_first_recipient_send_preflight,
    verify_first_recipient_send_preflight_receipt_file,
)
from scripts.external_alpha_operator_note_template import operator_dispatch_note_template
from scripts.prepare_external_alpha_first_recipient_send_workspace import (
    prepare_first_recipient_send_workspace,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_external_alpha_first_recipient_send_preflight.py"


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


def test_external_alpha_first_recipient_send_preflight_passes_with_real_private_inputs(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    recipient_text, note_text = _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])

    result = check_first_recipient_send_preflight(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "FIRST_RECIPIENT_PRE_SEND_READY"
    assert receipt_path.name == PREFLIGHT_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_first_recipient_send_preflight_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["release"]["archive_sha256"] == packet["release"]["archive_sha256"]
    assert payload["checks"]["operator_packet_file_expected"] is True
    assert payload["operator_packet"]["file"] == "cambrian-agent-platform-external-alpha-operator-dispatch-packet.json"
    assert payload["operator_packet"]["schema_version"] == "external_alpha_operator_dispatch_packet_v0_1"
    assert payload["operator_packet"]["body_sha256"] == packet["operator_dispatch_packet_body_sha256"]
    assert payload["private_workspace"]["send_recorded"] is False
    assert payload["policy"]["script_sends_to_recipient"] is False
    assert payload["policy"]["pre_send_gate_only"] is True
    assert payload["checks"]["recipient_private_ready"] is True
    assert payload["checks"]["operator_dispatch_note_private_ready"] is True
    assert payload["checks"]["recipient_private_minimum_signal"] is True
    assert payload["checks"]["recipient_private_exactly_one_contact"] is True
    assert payload["checks"]["operator_dispatch_note_mentions_channel"] is True
    assert payload["checks"]["operator_dispatch_note_confirms_release_hash"] is True
    assert payload["checks"]["copy_paste_message_ready"] is True
    assert payload["checks"]["script_does_not_send_to_recipient"] is True
    assert all(payload["checks"].values())
    assert all(payload["first_recipient_send_preflight_receipt_checks"].values())

    private_files = {item["file"]: item for item in payload["private_workspace"]["required_private_files"]}
    assert private_files["recipient-private.txt"]["status"] == "ready"
    assert private_files["operator-dispatch-note-private.md"]["status"] == "ready"
    assert private_files["recipient-private.txt"]["byte_count"] >= 8
    assert private_files["recipient-private.txt"]["nonempty_line_count"] == 1
    assert private_files["recipient-private.txt"]["exactly_one_recipient"] is True
    assert private_files["operator-dispatch-note-private.md"]["mentions_channel"] is True
    assert private_files["operator-dispatch-note-private.md"]["contains_release_hash"] is True
    assert private_files["recipient-private.txt"]["sha256"] == hashlib.sha256(
        (workspace / "recipient-private.txt").read_bytes()
    ).hexdigest()
    assert private_files["operator-dispatch-note-private.md"]["sha256"] == hashlib.sha256(
        (workspace / "operator-dispatch-note-private.md").read_bytes()
    ).hexdigest()

    verified = verify_first_recipient_send_preflight_receipt_file(receipt_path)
    assert verified["first_recipient_send_preflight_receipt_body_sha256"] == payload[
        "first_recipient_send_preflight_receipt_body_sha256"
    ]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized
    assert packet["operator_send_once"]["copy_paste_message"] not in serialized
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in packet["operator_send_once"]["copy_paste_message"]
    assert "Recipient identifier/contact goes here" not in serialized
    assert "Record the private channel" not in serialized
    assert "<private-send-channel>" not in serialized


def test_external_alpha_first_recipient_send_preflight_blocks_unresolved_operator_note_template(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(packet_result["packet_json"])
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=packet_path,
    )
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    (workspace / "recipient-private.txt").write_text(
        "alpha recipient private contact: one-recipient@example.invalid\n",
        encoding="utf-8",
    )
    (workspace / "operator-dispatch-note-private.md").write_text(
        operator_dispatch_note_template(packet["release"]["archive_sha256"]),
        encoding="utf-8",
    )
    receipt_path = workspace / PREFLIGHT_RECEIPT_NAME

    with pytest.raises(FirstRecipientSendPreflightError, match="operator_dispatch_note_private_ready"):
        check_first_recipient_send_preflight(
            workspace,
            operator_packet_path=packet_path,
            receipt_path=receipt_path,
        )

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    private_files = {item["file"]: item for item in payload["private_workspace"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert payload["checks"]["recipient_private_ready"] is True
    assert payload["checks"]["operator_dispatch_note_private_ready"] is False
    assert payload["checks"]["operator_dispatch_note_mentions_channel"] is False
    assert payload["checks"]["operator_dispatch_note_confirms_release_hash"] is False
    assert private_files["operator-dispatch-note-private.md"]["status"] == "placeholder"
    assert private_files["operator-dispatch-note-private.md"]["sha256"] is None

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "<private-send-channel>" not in serialized


@pytest.mark.parametrize(
    "channel_line",
    [
        "private send channel:\n",
        "private send channel:   \n",
        "channel:\n",
    ],
)
def test_external_alpha_first_recipient_send_preflight_blocks_empty_operator_note_channel(
    tmp_path: Path,
    channel_line: str,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(packet_result["packet_json"])
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=packet_path)
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
    receipt_path = workspace / PREFLIGHT_RECEIPT_NAME

    with pytest.raises(FirstRecipientSendPreflightError, match="operator_dispatch_note_mentions_channel"):
        check_first_recipient_send_preflight(
            workspace,
            operator_packet_path=packet_path,
            receipt_path=receipt_path,
        )

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    private_files = {item["file"]: item for item in payload["private_workspace"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert payload["checks"]["recipient_private_ready"] is True
    assert payload["checks"]["operator_dispatch_note_private_ready"] is True
    assert payload["checks"]["operator_dispatch_note_mentions_channel"] is False
    assert payload["checks"]["operator_dispatch_note_confirms_release_hash"] is True
    assert private_files["operator-dispatch-note-private.md"]["status"] == "ready"
    assert private_files["operator-dispatch-note-private.md"]["mentions_channel"] is False
    assert private_files["operator-dispatch-note-private.md"]["contains_release_hash"] is True


def test_external_alpha_recipient_value_helper_rejects_placeholder_like_values() -> None:
    for value in ["<recipient>", "placeholder recipient", "replace me", "TODO", "TBD", "sample"]:
        assert _recipient_value_is_real(value) is False
    assert _recipient_value_is_real("alpha recipient private contact: one-recipient@example.invalid") is True


def test_external_alpha_first_recipient_send_preflight_blocks_placeholder_like_recipient(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(packet_result["packet_json"])
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(workspace, operator_packet_path=packet_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    (workspace / "recipient-private.txt").write_text("<recipient>\n", encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(
        "private send channel: direct message\n"
        f"attachment sha256 checked: {packet['release']['archive_sha256']}\n"
        "operator note: first external alpha one-recipient send only\n",
        encoding="utf-8",
    )
    receipt_path = workspace / PREFLIGHT_RECEIPT_NAME

    with pytest.raises(FirstRecipientSendPreflightError, match="recipient_private_ready"):
        check_first_recipient_send_preflight(
            workspace,
            operator_packet_path=packet_path,
            receipt_path=receipt_path,
        )

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    private_files = {item["file"]: item for item in payload["private_workspace"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert payload["checks"]["recipient_private_ready"] is False
    assert payload["checks"]["operator_dispatch_note_private_ready"] is True
    assert private_files["recipient-private.txt"]["status"] == "placeholder"
    assert private_files["recipient-private.txt"]["sha256"] is None
    assert private_files["recipient-private.txt"]["nonempty_line_count"] == 1


def test_external_alpha_first_recipient_send_preflight_blocks_multiple_recipient_lines(
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
    (workspace / "recipient-private.txt").write_text(
        "alpha recipient private contact: one@example.invalid\n"
        "alpha recipient private contact: two@example.invalid\n",
        encoding="utf-8",
    )
    receipt_path = workspace / PREFLIGHT_RECEIPT_NAME

    with pytest.raises(FirstRecipientSendPreflightError, match="recipient_private_exactly_one_contact"):
        check_first_recipient_send_preflight(
            workspace,
            operator_packet_path=Path(packet_result["packet_json"]),
            receipt_path=receipt_path,
        )

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    private_files = {item["file"]: item for item in payload["private_workspace"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert payload["checks"]["recipient_private_ready"] is True
    assert payload["checks"]["recipient_private_minimum_signal"] is True
    assert payload["checks"]["recipient_private_exactly_one_contact"] is False
    assert private_files["recipient-private.txt"]["status"] == "ready"
    assert private_files["recipient-private.txt"]["nonempty_line_count"] == 2
    assert private_files["recipient-private.txt"]["exactly_one_recipient"] is False
    assert private_files["recipient-private.txt"]["sha256"] == hashlib.sha256(
        (workspace / "recipient-private.txt").read_bytes()
    ).hexdigest()

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "one@example.invalid" not in serialized
    assert "two@example.invalid" not in serialized


def test_external_alpha_first_recipient_send_preflight_rejects_noncanonical_operator_packet_name(
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
    copied_packet_path = tmp_path / "operator-packet-copy.json"
    copied_packet_path.write_bytes(Path(packet_result["packet_json"]).read_bytes())
    receipt_path = workspace / PREFLIGHT_RECEIPT_NAME

    with pytest.raises(FirstRecipientSendPreflightError, match="operator_packet_file_expected"):
        check_first_recipient_send_preflight(
            workspace,
            operator_packet_path=copied_packet_path,
            receipt_path=receipt_path,
        )

    payload = verify_first_recipient_send_preflight_receipt_file(receipt_path, require_ready=False)

    assert payload["status"] == "fail"
    assert payload["checks"]["operator_packet_file_expected"] is False
    assert payload["operator_packet"]["file"] == "operator-packet-copy.json"
    assert payload["checks"]["recipient_private_ready"] is True
    assert payload["checks"]["operator_dispatch_note_private_ready"] is True


def test_external_alpha_first_recipient_send_preflight_blocks_placeholders_and_writes_safe_receipt(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = workspace / PREFLIGHT_RECEIPT_NAME

    with pytest.raises(FirstRecipientSendPreflightError, match="recipient_private_ready"):
        check_first_recipient_send_preflight(
            workspace,
            operator_packet_path=Path(packet_result["packet_json"]),
            receipt_path=receipt_path,
        )

    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    private_files = {item["file"]: item for item in payload["private_workspace"]["required_private_files"]}

    assert payload["status"] == "fail"
    assert payload["verdict"] == "BLOCKED_UNTIL_PRIVATE_FIELDS_FILLED"
    assert payload["checks"]["recipient_private_ready"] is False
    assert payload["checks"]["operator_dispatch_note_private_ready"] is False
    assert payload["checks"]["operator_dispatch_note_confirms_release_hash"] is False
    assert private_files["recipient-private.txt"]["status"] == "placeholder"
    assert private_files["recipient-private.txt"]["sha256"] is None
    assert private_files["operator-dispatch-note-private.md"]["status"] == "placeholder"
    assert private_files["operator-dispatch-note-private.md"]["sha256"] is None
    assert all(payload["first_recipient_send_preflight_receipt_checks"].values())

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "Recipient identifier/contact goes here" not in serialized
    assert "Record the private channel" not in serialized
    assert "<private-send-channel>" not in serialized


def test_external_alpha_first_recipient_send_preflight_cli_passes_and_verifies(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--operator-packet",
            packet_result["packet_json"],
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
    assert "[PASS] external alpha first-recipient send preflight" in output
    assert "FIRST_RECIPIENT_PRE_SEND_READY" in output
    assert (workspace / PREFLIGHT_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify-receipt",
            str(workspace / PREFLIGHT_RECEIPT_NAME),
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
    assert "[PASS] external alpha first-recipient send preflight receipt verification" in verify_output


def test_external_alpha_first_recipient_send_preflight_cli_rejects_placeholders(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace-dir",
            str(workspace),
            "--operator-packet",
            packet_result["packet_json"],
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
    assert result.returncode == 1
    assert "recipient_private_ready" in output
    assert (workspace / PREFLIGHT_RECEIPT_NAME).is_file()


def test_external_alpha_first_recipient_send_preflight_rejects_tampering(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    _fill_required_private_send_files(workspace, packet["release"]["archive_sha256"])
    result = check_first_recipient_send_preflight(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["max_recipients"] = 2
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(FirstRecipientSendPreflightError):
        verify_first_recipient_send_preflight_receipt_file(receipt_path)
