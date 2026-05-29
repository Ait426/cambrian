import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_first_recipient_send_preflight import check_first_recipient_send_preflight
from scripts.prepare_external_alpha_first_recipient_send_workspace import (
    BUILDER_GOLD_PATH_RECEIPT_PLACEHOLDER,
    CONTROLLED_FRICTION_TAG_PLACEHOLDER,
    CONTROLLED_MISSING_SKILL_TAG_PLACEHOLDER,
    CONTROLLED_OUTCOME_TAG_PLACEHOLDER,
    FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME,
    OPERATOR_DECISION_PLACEHOLDER,
    PRIVATE_SEND_RUNBOOK_NAME,
    SENT_AT_UTC_PLACEHOLDER,
    FirstRecipientSendWorkspaceError,
    prepare_first_recipient_send_workspace,
    verify_first_recipient_send_workspace_receipt_file,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import (
    PACKET_JSON_NAME,
    prepare_operator_dispatch_packet,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_external_alpha_first_recipient_send_workspace.py"


def _operator_note_template_from_runbook(runbook: str) -> str:
    marker = "## Operator Dispatch Note Template"
    start = runbook.index(marker)
    fenced_start = runbook.index("```text", start) + len("```text")
    fenced_end = runbook.index("```", fenced_start)
    return runbook[fenced_start:fenced_end].strip() + "\n"


def test_external_alpha_first_recipient_send_workspace_creates_private_runbook_and_safe_receipt(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"

    result = prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = Path(result["receipt_json"])
    runbook_path = Path(result["private_runbook"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    runbook = runbook_path.read_text(encoding="utf-8")
    operator_note_path = workspace / "operator-dispatch-note-private.md"
    operator_note = operator_note_path.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["verdict"] == "FIRST_RECIPIENT_SEND_WORKSPACE_READY"
    assert result["operator_dispatch_note_template_seed_status"] == "seeded_from_scaffold"
    assert receipt_path.name == FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME
    assert runbook_path.name == PRIVATE_SEND_RUNBOOK_NAME
    assert packet["operator_send_once"]["copy_paste_message"] in runbook
    assert "## Do This Now - Two Private Edits" in runbook
    assert "exactly one recipient contact or identifier" in runbook
    assert "change only `<private-send-channel>`" in runbook
    assert "Do not pass recipient, contact, channel, acknowledgement, feedback, or issue text as CLI arguments" in runbook
    assert "Keep raw private values only in the private workspace files" in runbook
    assert str(workspace / "recipient-private.txt") in runbook
    assert str(workspace / "operator-dispatch-note-private.md") in runbook
    assert str(workspace / "recipient-ack-private.txt") in runbook
    assert packet["release"]["archive_sha256"] in runbook
    assert "private send channel" in runbook
    assert "## Operator Dispatch Note Template" in runbook
    assert "private send channel: <private-send-channel>" in runbook
    assert f'attachment sha256 checked: {packet["release"]["archive_sha256"]}' in runbook
    assert "operator note: first external alpha one-recipient send only" in runbook
    assert "private send channel: <private-send-channel>" in operator_note
    assert f'attachment sha256 checked: {packet["release"]["archive_sha256"]}' in operator_note
    assert "operator note: first external alpha one-recipient send only" in operator_note
    assert f'--private-workspace-dir "{workspace}"' in runbook
    assert "check_external_alpha_first_recipient_send_preflight.py" in runbook
    assert "check_external_alpha_first_recipient_post_send_sequence.py" in runbook
    assert "check_external_alpha_first_recipient_operator_status.py" in runbook
    assert f'--workspace-dir "{workspace}"' in runbook
    assert "--operator-packet" in runbook
    assert "--require-preflight-receipt" in runbook
    assert SENT_AT_UTC_PLACEHOLDER in runbook
    assert f'--sent-at-utc "{SENT_AT_UTC_PLACEHOLDER}"' in runbook
    assert f"--sent-at-utc {SENT_AT_UTC_PLACEHOLDER}" not in runbook
    assert f'--builder-gold-path-share-receipt "{BUILDER_GOLD_PATH_RECEIPT_PLACEHOLDER}"' in runbook
    assert f"--builder-gold-path-share-receipt {BUILDER_GOLD_PATH_RECEIPT_PLACEHOLDER}" not in runbook
    assert f'--operator-decision "{OPERATOR_DECISION_PLACEHOLDER}"' in runbook
    assert f"--operator-decision {OPERATOR_DECISION_PLACEHOLDER}" not in runbook
    assert f'--outcome-tag "{CONTROLLED_OUTCOME_TAG_PLACEHOLDER}"' in runbook
    assert f'--friction-tag "{CONTROLLED_FRICTION_TAG_PLACEHOLDER}"' in runbook
    assert f'--missing-skill-tag "{CONTROLLED_MISSING_SKILL_TAG_PLACEHOLDER}"' in runbook
    assert "Placeholders inside commands are quoted on purpose" in runbook
    assert "Do not use the time this runbook was generated as send evidence." in runbook
    assert "Suggested sent_at_utc format:" not in runbook
    assert "--recipient-private-file" not in runbook
    assert "--operator-dispatch-note-private-file" not in runbook

    assert payload["schema_version"] == "external_alpha_first_recipient_send_workspace_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["release"]["archive_sha256"] == packet["release"]["archive_sha256"]
    assert payload["operator_packet"]["body_sha256"] == packet["operator_dispatch_packet_body_sha256"]
    assert payload["operator_packet"]["copy_paste_message_sha256"] == packet["operator_send_once"][
        "copy_paste_message_sha256"
    ]
    assert payload["private_workspace"]["send_runbook_file"] == PRIVATE_SEND_RUNBOOK_NAME
    assert payload["private_workspace"]["preflight_receipt_file"] == (
        "external-alpha-first-recipient-send-preflight-receipt.json"
    )
    assert payload["private_workspace"]["operator_dispatch_note_template_seed"] == {
        "file": "operator-dispatch-note-private.md",
        "local_path_included": False,
        "raw_template_included": False,
        "status": "seeded_from_scaffold",
    }
    assert payload["private_workspace"]["send_runbook_safe_to_share"] is False
    assert payload["private_workspace"]["send_runbook_contains_local_paths"] is True
    assert payload["private_workspace"]["send_runbook_contains_copy_paste_message"] is True
    assert payload["checks"]["operator_packet_ready_to_send_one"] is True
    assert payload["checks"]["private_send_runbook_created"] is True
    assert payload["checks"]["operator_copy_paste_message_ascii_only"] is True
    assert payload["checks"]["operator_copy_paste_message_mojibake_free"] is True
    assert payload["checks"]["private_send_runbook_ascii_message_present"] is True
    assert payload["checks"]["private_send_runbook_mojibake_free"] is True
    assert payload["checks"]["private_send_runbook_two_edit_block_present"] is True
    assert payload["checks"]["operator_dispatch_note_template_seed_controlled"] is True
    assert payload["checks"]["operator_dispatch_note_template_seeded_or_preserved"] is True
    assert payload["checks"]["private_values_not_cli_arguments_warning_present"] is True
    assert payload["checks"]["private_send_runbook_preflight_command_present"] is True
    assert payload["checks"]["private_send_runbook_operator_status_command_present"] is True
    assert payload["checks"]["private_send_runbook_real_sent_at_placeholder_present"] is True
    assert payload["checks"]["private_send_runbook_shell_safe_placeholders"] is True
    assert all(payload["checks"].values())
    assert verify_first_recipient_send_workspace_receipt_file(receipt_path)[
        "first_recipient_send_workspace_receipt_body_sha256"
    ] == payload["first_recipient_send_workspace_receipt_body_sha256"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert packet["operator_send_once"]["copy_paste_message"] not in serialized
    assert "<private-send-channel>" not in serialized
    assert "Recipient identifier/contact goes here" not in serialized
    assert "CONFIRMED" in runbook
    assert "\u5360?" not in runbook
    assert "?\uf9d0?" not in runbook


def test_external_alpha_first_recipient_send_workspace_template_passes_preflight(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(packet_result["packet_json"])
    workspace = tmp_path / "private-send-workspace"

    result = prepare_first_recipient_send_workspace(workspace, operator_packet_path=packet_path)
    runbook = Path(result["private_runbook"]).read_text(encoding="utf-8")
    note_text = _operator_note_template_from_runbook(runbook).replace(
        "<private-send-channel>",
        "direct message",
    )
    recipient_text = "alpha recipient private contact: one-recipient@example.invalid\n"
    (workspace / "recipient-private.txt").write_text(recipient_text, encoding="utf-8")
    (workspace / "operator-dispatch-note-private.md").write_text(note_text, encoding="utf-8")

    preflight = check_first_recipient_send_preflight(workspace, operator_packet_path=packet_path)
    preflight_payload = json.loads(Path(preflight["receipt_json"]).read_text(encoding="utf-8"))
    private_files = {
        item["file"]: item for item in preflight_payload["private_workspace"]["required_private_files"]
    }

    assert preflight["verdict"] == "FIRST_RECIPIENT_PRE_SEND_READY"
    assert private_files["operator-dispatch-note-private.md"]["mentions_channel"] is True
    assert private_files["operator-dispatch-note-private.md"]["contains_release_hash"] is True
    assert private_files["recipient-private.txt"]["byte_count"] >= 8

    serialized = json.dumps(preflight_payload, ensure_ascii=False)
    assert recipient_text.strip() not in serialized
    assert note_text.strip() not in serialized
    assert "<private-send-channel>" not in serialized


def test_external_alpha_first_recipient_send_workspace_refreshes_runbook_without_overwriting_private_files(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    recipient_path = workspace / "recipient-private.txt"
    recipient_path.write_text("real private recipient marker\n", encoding="utf-8")
    note_path = workspace / "operator-dispatch-note-private.md"
    real_note = "private send channel: direct message\noperator already filled private note\n"
    note_path.write_text(real_note, encoding="utf-8")
    readme_path = workspace / "README_PRIVATE.md"
    readme_path.write_text("stale generated readme\n", encoding="utf-8")

    result = prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )

    assert result["verdict"] == "FIRST_RECIPIENT_SEND_WORKSPACE_READY"
    assert result["operator_dispatch_note_template_seed_status"] == "preserved_existing_private_note"
    assert recipient_path.read_text(encoding="utf-8") == "real private recipient marker\n"
    assert note_path.read_text(encoding="utf-8") == real_note
    assert "check_external_alpha_first_recipient_operator_status.py" in readme_path.read_text(encoding="utf-8")
    assert "check_external_alpha_first_recipient_pre_send_sequence.py" in readme_path.read_text(encoding="utf-8")
    assert f'--private-workspace-dir "{workspace}"' in (workspace / PRIVATE_SEND_RUNBOOK_NAME).read_text(
        encoding="utf-8"
    )


def test_external_alpha_first_recipient_send_workspace_requires_operator_packet(tmp_path: Path) -> None:
    with pytest.raises(FirstRecipientSendWorkspaceError, match="operator dispatch packet"):
        prepare_first_recipient_send_workspace(
            tmp_path / "private-send-workspace",
            operator_packet_path=tmp_path / PACKET_JSON_NAME,
        )


def test_external_alpha_first_recipient_send_workspace_cli_passes_and_verifies(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
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
    assert "[PASS] external alpha first-recipient send workspace" in output
    assert "FIRST_RECIPIENT_SEND_WORKSPACE_READY" in output
    assert (workspace / FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME).is_file()
    assert (workspace / PRIVATE_SEND_RUNBOOK_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify-receipt",
            str(workspace / FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME),
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
    assert "[PASS] external alpha first-recipient send workspace receipt verification" in verify_output


def test_external_alpha_first_recipient_send_workspace_rejects_tampering(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    result = prepare_first_recipient_send_workspace(
        tmp_path / "private-send-workspace",
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["policy"]["max_recipients"] = 2
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(FirstRecipientSendWorkspaceError):
        verify_first_recipient_send_workspace_receipt_file(receipt_path)
