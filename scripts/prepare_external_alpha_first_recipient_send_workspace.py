"""Prepare the local-only workspace used to send the external alpha to one recipient."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.prepare_external_alpha_operator_dispatch_packet import (  # noqa: E402
    PACKET_JSON_NAME,
    verify_operator_dispatch_packet_file,
)
from scripts.check_external_alpha_first_recipient_send_preflight import (  # noqa: E402
    PREFLIGHT_RECEIPT_NAME,
)
from scripts.external_alpha_operator_note_template import operator_dispatch_note_template  # noqa: E402
from scripts.prepare_external_alpha_private_pilot_workspace import (  # noqa: E402
    DEFAULT_PRIVATE_WORKSPACE_DIR,
    PRIVATE_FILE_SPECS,
    PRIVATE_WORKSPACE_RECEIPT_NAME,
    prepare_private_pilot_workspace,
    refresh_private_pilot_workspace_guides,
    verify_private_pilot_workspace_receipt_file,
)


FIRST_RECIPIENT_SEND_WORKSPACE_SCHEMA_VERSION = "external_alpha_first_recipient_send_workspace_v0_1"
FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME = "external-alpha-first-recipient-send-workspace-receipt.json"
PRIVATE_SEND_RUNBOOK_NAME = "SEND_ONE_NOW_PRIVATE.md"
DEFAULT_OPERATOR_PACKET_PATH = DEFAULT_OUTPUT_DIR / PACKET_JSON_NAME
DEFAULT_FIRST_RECIPIENT_WORKSPACE_DIR = DEFAULT_PRIVATE_WORKSPACE_DIR
SENT_AT_UTC_PLACEHOLDER = "<sent-at-utc>"
SENT_AT_UTC_CLI_PLACEHOLDER = f'"{SENT_AT_UTC_PLACEHOLDER}"'
BUILDER_GOLD_PATH_RECEIPT_PLACEHOLDER = "<external_alpha_builder_gold_path_share_receipt.json>"
BUILDER_GOLD_PATH_RECEIPT_CLI_PLACEHOLDER = f'"{BUILDER_GOLD_PATH_RECEIPT_PLACEHOLDER}"'
OPERATOR_DECISION_PLACEHOLDER = "<continue|fix_before_next|stop_and_redesign>"
OPERATOR_DECISION_CLI_PLACEHOLDER = f'"{OPERATOR_DECISION_PLACEHOLDER}"'
CONTROLLED_OUTCOME_TAG_PLACEHOLDER = "<controlled-outcome-tag>"
CONTROLLED_OUTCOME_TAG_CLI_PLACEHOLDER = f'"{CONTROLLED_OUTCOME_TAG_PLACEHOLDER}"'
CONTROLLED_FRICTION_TAG_PLACEHOLDER = "<controlled-friction-tag>"
CONTROLLED_FRICTION_TAG_CLI_PLACEHOLDER = f'"{CONTROLLED_FRICTION_TAG_PLACEHOLDER}"'
CONTROLLED_MISSING_SKILL_TAG_PLACEHOLDER = "<controlled-missing-skill-tag>"
CONTROLLED_MISSING_SKILL_TAG_CLI_PLACEHOLDER = f'"{CONTROLLED_MISSING_SKILL_TAG_PLACEHOLDER}"'
MOJIBAKE_MARKERS = ("�", "?뺤", "泥", "蹂대", "臾몄", "瑜?", "媛")

OPERATOR_DISPATCH_NOTE_FILE = "operator-dispatch-note-private.md"
OPERATOR_DISPATCH_NOTE_TEMPLATE_PLACEHOLDER = "<private-send-channel>"
OPERATOR_DISPATCH_NOTE_SCAFFOLD_MARKERS = ("Record the private channel",)
OPERATOR_DISPATCH_NOTE_SEED_STATUSES = {
    "created_from_template",
    "force_seeded_from_template",
    "seeded_from_scaffold",
    "seeded_from_empty",
    "already_seeded_template",
    "preserved_existing_private_note",
    "preserved_unreadable_private_note",
}

logger = logging.getLogger(__name__)


class FirstRecipientSendWorkspaceError(RuntimeError):
    """First-recipient send workspace generation or verification failed."""


def prepare_first_recipient_send_workspace(
    workspace_dir: Path = DEFAULT_FIRST_RECIPIENT_WORKSPACE_DIR,
    *,
    operator_packet_path: Path = DEFAULT_OPERATOR_PACKET_PATH,
    receipt_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create a private send runbook plus a share-safe receipt for one manual recipient send."""
    workspace_dir = workspace_dir.resolve()
    operator_packet_path = operator_packet_path.resolve()
    operator_packet = _load_operator_packet(operator_packet_path)
    zip_path = _release_zip_path(operator_packet_path, operator_packet)
    _assert_release_zip_matches_packet(zip_path, operator_packet)

    private_workspace = _ensure_private_workspace_scaffold(workspace_dir=workspace_dir, force=force)
    note_seed = _seed_operator_dispatch_note_template(
        workspace_dir=workspace_dir,
        archive_sha256=str(operator_packet["release"]["archive_sha256"]),
        force=force,
    )
    scaffold_receipt = verify_private_pilot_workspace_receipt_file(workspace_dir / PRIVATE_WORKSPACE_RECEIPT_NAME)

    runbook_path = workspace_dir / PRIVATE_SEND_RUNBOOK_NAME
    runbook_path.write_text(
        _private_send_runbook(
            workspace_dir=workspace_dir,
            zip_path=zip_path,
            operator_packet=operator_packet,
            operator_packet_path=operator_packet_path,
        ),
        encoding="utf-8",
    )

    receipt = _workspace_receipt(
        operator_packet=operator_packet,
        operator_packet_path=operator_packet_path,
        zip_path=zip_path,
        runbook_path=runbook_path,
        scaffold_receipt=scaffold_receipt,
        operator_note_seed=note_seed,
    )
    receipt_path = (receipt_path or workspace_dir / FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, receipt)
    verify_first_recipient_send_workspace_receipt_file(receipt_path)
    _assert_shareable_receipt_file(receipt_path, workspace_dir, operator_packet)

    return {
        "status": receipt["status"],
        "verdict": receipt["verdict"],
        "workspace_dir": str(workspace_dir),
        "private_runbook": str(runbook_path),
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": receipt["first_recipient_send_workspace_receipt_body_sha256"],
        "archive_sha256": receipt["release"]["archive_sha256"],
        "private_workspace_receipt_body_sha256": private_workspace["receipt_body_sha256"],
        "operator_dispatch_note_template_seed_status": note_seed["status"],
    }


def _ensure_private_workspace_scaffold(*, workspace_dir: Path, force: bool) -> dict[str, Any]:
    """Create the scaffold once, then reuse it without overwriting private files."""
    receipt_path = workspace_dir / PRIVATE_WORKSPACE_RECEIPT_NAME
    private_files_present = all((workspace_dir / spec["file"]).is_file() for spec in PRIVATE_FILE_SPECS)
    if force or not receipt_path.is_file() or not private_files_present:
        return prepare_private_pilot_workspace(workspace_dir=workspace_dir, force=force)
    private_workspace = refresh_private_pilot_workspace_guides(workspace_dir=workspace_dir)
    payload = verify_private_pilot_workspace_receipt_file(receipt_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "workspace_dir": str(workspace_dir),
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": private_workspace["receipt_body_sha256"],
        "private_files": private_workspace["private_files"],
    }


def _seed_operator_dispatch_note_template(
    *,
    workspace_dir: Path,
    archive_sha256: str,
    force: bool,
) -> dict[str, str]:
    """Seed the private operator note template without overwriting real private notes."""
    note_path = workspace_dir / OPERATOR_DISPATCH_NOTE_FILE
    template = operator_dispatch_note_template(archive_sha256)
    if force:
        note_path.write_text(template, encoding="utf-8")
        return {"file": OPERATOR_DISPATCH_NOTE_FILE, "status": "force_seeded_from_template"}
    if not note_path.is_file():
        note_path.write_text(template, encoding="utf-8")
        return {"file": OPERATOR_DISPATCH_NOTE_FILE, "status": "created_from_template"}
    try:
        current = note_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"file": OPERATOR_DISPATCH_NOTE_FILE, "status": "preserved_unreadable_private_note"}
    if not current.strip():
        note_path.write_text(template, encoding="utf-8")
        return {"file": OPERATOR_DISPATCH_NOTE_FILE, "status": "seeded_from_empty"}
    if any(marker in current for marker in OPERATOR_DISPATCH_NOTE_SCAFFOLD_MARKERS):
        note_path.write_text(template, encoding="utf-8")
        return {"file": OPERATOR_DISPATCH_NOTE_FILE, "status": "seeded_from_scaffold"}
    if current == template or OPERATOR_DISPATCH_NOTE_TEMPLATE_PLACEHOLDER in current:
        return {"file": OPERATOR_DISPATCH_NOTE_FILE, "status": "already_seeded_template"}
    return {"file": OPERATOR_DISPATCH_NOTE_FILE, "status": "preserved_existing_private_note"}


def verify_first_recipient_send_workspace_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_send_workspace_receipt_payload(payload)
    return payload


def verify_first_recipient_send_workspace_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != FIRST_RECIPIENT_SEND_WORKSPACE_SCHEMA_VERSION:
        raise FirstRecipientSendWorkspaceError("first-recipient send workspace receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "FIRST_RECIPIENT_SEND_WORKSPACE_READY":
        raise FirstRecipientSendWorkspaceError("first-recipient send workspace receipt did not pass.")
    if payload.get("safe_to_share") is not True:
        raise FirstRecipientSendWorkspaceError("first-recipient send workspace receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise FirstRecipientSendWorkspaceError("first-recipient send workspace receipt checks failed.")
    if payload.get("first_recipient_send_workspace_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise FirstRecipientSendWorkspaceError("first-recipient send workspace receipt body hash mismatch.")


def _load_operator_packet(path: Path) -> dict[str, Any]:
    try:
        return verify_operator_dispatch_packet_file(path)
    except Exception as exc:  # noqa: BLE001 - wrap for operator-facing CLI output.
        raise FirstRecipientSendWorkspaceError(f"operator dispatch packet is not ready: {path.name}") from exc


def _release_zip_path(operator_packet_path: Path, operator_packet: dict[str, Any]) -> Path:
    release = operator_packet.get("release") if isinstance(operator_packet.get("release"), dict) else {}
    zip_file = release.get("zip_file")
    if not isinstance(zip_file, str) or not zip_file:
        raise FirstRecipientSendWorkspaceError("operator dispatch packet does not name a release ZIP.")
    return operator_packet_path.parent / zip_file


def _assert_release_zip_matches_packet(zip_path: Path, operator_packet: dict[str, Any]) -> None:
    release = operator_packet.get("release") if isinstance(operator_packet.get("release"), dict) else {}
    expected = release.get("archive_sha256")
    if not zip_path.is_file():
        raise FirstRecipientSendWorkspaceError(f"release ZIP is missing beside operator packet: {zip_path.name}")
    actual = _file_sha256(zip_path)
    if actual != expected:
        raise FirstRecipientSendWorkspaceError("release ZIP hash does not match operator dispatch packet.")


def _private_send_runbook(
    *,
    workspace_dir: Path,
    zip_path: Path,
    operator_packet: dict[str, Any],
    operator_packet_path: Path,
) -> str:
    send_once = operator_packet["operator_send_once"]
    copy_paste_message = str(send_once["copy_paste_message"])
    return f"""# First Recipient Send Runbook - Private

This file is local-only. Do not share it, commit it, paste it into chat, or attach screenshots of it.

## Do This Now - Two Private Edits

1. Replace `{workspace_dir / "recipient-private.txt"}` with exactly one recipient contact or identifier on one non-empty line.
2. Open `{workspace_dir / "operator-dispatch-note-private.md"}`. If it still contains `<private-send-channel>`, change only `<private-send-channel>` to the real private channel and keep the sha256 line exact.

Do not pass recipient, contact, channel, acknowledgement, feedback, or issue text as CLI arguments. Keep raw private values only in the private workspace files.

## Before Sending

- Send to exactly one recipient.
- Attach this ZIP: {zip_path}
- Confirm ZIP sha256 before sending: {operator_packet["release"]["archive_sha256"]}
- Store the raw recipient identifier only in: {workspace_dir / "recipient-private.txt"}; use one non-empty line for exactly one recipient.
- Store the raw operator dispatch note only in: {workspace_dir / "operator-dispatch-note-private.md"}
- The operator dispatch note must include the private send channel and this exact ZIP sha256: {operator_packet["release"]["archive_sha256"]}
- After the recipient replies, store only exactly one non-empty `CONFIRMED` line in: {workspace_dir / "recipient-ack-private.txt"}.
- Keep `{SENT_AT_UTC_PLACEHOLDER}` in all commands until the manual send has actually happened.
- After the one manual send, replace `{SENT_AT_UTC_PLACEHOLDER}` with the real UTC send timestamp, for example `2026-05-17T01:00:00Z`.
- Do not use the time this runbook was generated as send evidence.
- Placeholders inside commands are quoted on purpose so shells pass them to Cambrian instead of interpreting `<`, `>`, or `|`.

## Copy-Paste Message

```text
{copy_paste_message}
```

## Preflight Before Manual Send

Fill `recipient-private.txt` and finish `operator-dispatch-note-private.md` first. The note file is pre-seeded with the canonical template when it is still scaffold text; the operator note must name the private send channel and confirm the exact ZIP sha256 above. This command does not send anything.

## Operator Dispatch Note Template

This is already seeded into `{workspace_dir / "operator-dispatch-note-private.md"}` when that file still has scaffold text. If the file is missing or stale, paste this template and replace `<private-send-channel>` with the real private channel. Keep the sha256 line exact.

```text
{operator_dispatch_note_template(operator_packet["release"]["archive_sha256"]).rstrip()}
```

Do not put the raw recipient identifier in this note. Store the recipient only in `{workspace_dir / "recipient-private.txt"}`.

```bash
python scripts/check_external_alpha_first_recipient_send_preflight.py --workspace-dir "{workspace_dir}" --operator-packet "{operator_packet_path}"
```

Expected preflight receipt: `{PREFLIGHT_RECEIPT_NAME}`

Run the full pre-send sequence before the manual send. If blocked, it names only safe private file statuses such as `recipient-private.txt=placeholder`; it does not print raw recipient text.

```bash
python scripts/check_external_alpha_first_recipient_pre_send_sequence.py --workspace-dir "{workspace_dir}"
```

Check the safe operator status before sending. This names the current stage and next action without printing raw private values.

```bash
python scripts/check_external_alpha_first_recipient_operator_status.py --workspace-dir "{workspace_dir}"
```

## Record Dispatch After Manual Send

Prefer the post-send sequence. It does not send anything.

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --workspace-dir "{workspace_dir}" --sent-at-utc {SENT_AT_UTC_CLI_PLACEHOLDER}
```

If the recipient has not acknowledged yet, this records the manual send and prints only safe ack status such as `recipient-ack-private.txt=placeholder`, plus the next action. It does not print raw acknowledgement text.

Receipt-only verification does not require `--sent-at-utc`.

```bash
python scripts/check_external_alpha_first_recipient_post_send_sequence.py --verify-receipt "{workspace_dir / "external-alpha-first-recipient-post-send-sequence-receipt.json"}"
```

Check the safe operator status after recording the send or after adding acknowledgement/gold-path evidence.

```bash
python scripts/check_external_alpha_first_recipient_operator_status.py --workspace-dir "{workspace_dir}"
```

Lower-level dispatch record command:

```bash
python scripts/check_external_alpha_dispatch_record.py --private-workspace-dir "{workspace_dir}" --sent-at-utc {SENT_AT_UTC_CLI_PLACEHOLDER} --require-preflight-receipt
```

## Record Recipient Checkpoint After Acknowledgement

```bash
python scripts/check_external_alpha_recipient_checkpoint.py --private-workspace-dir "{workspace_dir}" --sent-at-utc {SENT_AT_UTC_CLI_PLACEHOLDER} --require-preflight-receipt --builder-gold-path-share-receipt {BUILDER_GOLD_PATH_RECEIPT_CLI_PLACEHOLDER}
```

## Continue Pilot Learning After Feedback

Use `{workspace_dir / "pilot-feedback-private.md"}`, `{workspace_dir / "pilot-issue-intake-private.md"}`, and `{workspace_dir / "operator-decision-note-private.md"}` only as private inputs. Public artifacts must receive sha256 values, controlled tags, and share-safe receipts only.

```bash
python scripts/check_external_alpha_pilot_evidence.py --private-workspace-dir "{workspace_dir}" --sent-at-utc {SENT_AT_UTC_CLI_PLACEHOLDER} --builder-gold-path-share-receipt {BUILDER_GOLD_PATH_RECEIPT_CLI_PLACEHOLDER} --operator-decision {OPERATOR_DECISION_CLI_PLACEHOLDER} --outcome-tag {CONTROLLED_OUTCOME_TAG_CLI_PLACEHOLDER} --friction-tag {CONTROLLED_FRICTION_TAG_CLI_PLACEHOLDER} --missing-skill-tag {CONTROLLED_MISSING_SKILL_TAG_CLI_PLACEHOLDER}
```

```bash
python scripts/check_external_alpha_pilot_decision.py --private-workspace-dir "{workspace_dir}" --sent-at-utc {SENT_AT_UTC_CLI_PLACEHOLDER} --builder-gold-path-share-receipt {BUILDER_GOLD_PATH_RECEIPT_CLI_PLACEHOLDER} --operator-decision {OPERATOR_DECISION_CLI_PLACEHOLDER} --outcome-tag {CONTROLLED_OUTCOME_TAG_CLI_PLACEHOLDER} --friction-tag {CONTROLLED_FRICTION_TAG_CLI_PLACEHOLDER} --missing-skill-tag {CONTROLLED_MISSING_SKILL_TAG_CLI_PLACEHOLDER}
```

```bash
python scripts/check_external_alpha_pilot_iteration.py --private-workspace-dir "{workspace_dir}" --sent-at-utc {SENT_AT_UTC_CLI_PLACEHOLDER} --builder-gold-path-share-receipt {BUILDER_GOLD_PATH_RECEIPT_CLI_PLACEHOLDER} --operator-decision {OPERATOR_DECISION_CLI_PLACEHOLDER} --outcome-tag {CONTROLLED_OUTCOME_TAG_CLI_PLACEHOLDER} --friction-tag {CONTROLLED_FRICTION_TAG_CLI_PLACEHOLDER} --missing-skill-tag {CONTROLLED_MISSING_SKILL_TAG_CLI_PLACEHOLDER}
```
"""


def _workspace_receipt(
    *,
    operator_packet: dict[str, Any],
    operator_packet_path: Path,
    zip_path: Path,
    runbook_path: Path,
    scaffold_receipt: dict[str, Any],
    operator_note_seed: dict[str, str],
) -> dict[str, Any]:
    send_once = operator_packet.get("operator_send_once") if isinstance(operator_packet.get("operator_send_once"), dict) else {}
    release = operator_packet.get("release") if isinstance(operator_packet.get("release"), dict) else {}
    copy_paste_message = str(send_once.get("copy_paste_message") or "")
    runbook_text = runbook_path.read_text(encoding="utf-8") if runbook_path.is_file() else ""
    checks = {
        "operator_packet_ready_to_send_one": operator_packet.get("verdict") == "READY_TO_SEND_ONE",
        "operator_packet_self_checks_passed": all(
            value is True for value in operator_packet.get("operator_dispatch_packet_checks", {}).values()
        ),
        "manual_dispatch_only": send_once.get("script_sends_to_recipient") is False
        and send_once.get("manual_operator_dispatch_required") is True,
        "one_recipient_only": send_once.get("max_recipients") == 1,
        "release_zip_exists": zip_path.is_file(),
        "release_zip_hash_matched": zip_path.is_file() and _file_sha256(zip_path) == release.get("archive_sha256"),
        "private_workspace_scaffolded": scaffold_receipt.get("verdict") == "PRIVATE_WORKSPACE_SCAFFOLDED",
        "private_workspace_receipt_share_safe": scaffold_receipt.get("safe_to_share") is True,
        "private_send_runbook_created": runbook_path.is_file(),
        "operator_copy_paste_message_ascii_only": _is_ascii(copy_paste_message),
        "operator_copy_paste_message_mojibake_free": _is_mojibake_free(copy_paste_message),
        "private_send_runbook_ascii_message_present": copy_paste_message in runbook_text
        and _is_ascii(copy_paste_message),
        "private_send_runbook_mojibake_free": _is_mojibake_free(runbook_text),
        "private_send_runbook_two_edit_block_present": (
            "## Do This Now - Two Private Edits" in runbook_text
            and "exactly one recipient contact or identifier" in runbook_text
            and "change only `<private-send-channel>`" in runbook_text
        ),
        "operator_dispatch_note_template_seed_controlled": operator_note_seed.get("status")
        in OPERATOR_DISPATCH_NOTE_SEED_STATUSES
        and operator_note_seed.get("file") == OPERATOR_DISPATCH_NOTE_FILE,
        "operator_dispatch_note_template_seeded_or_preserved": operator_note_seed.get("status")
        in OPERATOR_DISPATCH_NOTE_SEED_STATUSES,
        "private_values_not_cli_arguments_warning_present": (
            "Do not pass recipient, contact, channel, acknowledgement, feedback, or issue text as CLI arguments"
            in runbook_text
            and "Keep raw private values only in the private workspace files" in runbook_text
        ),
        "private_send_runbook_preflight_command_present": (
            "check_external_alpha_first_recipient_send_preflight.py" in runbook_text
            and f'--workspace-dir "{runbook_path.parent}"' in runbook_text
            and "--operator-packet" in runbook_text
        ),
        "private_send_runbook_operator_status_command_present": (
            "check_external_alpha_first_recipient_operator_status.py" in runbook_text
            and f'--workspace-dir "{runbook_path.parent}"' in runbook_text
        ),
        "private_send_runbook_real_sent_at_placeholder_present": (
            SENT_AT_UTC_PLACEHOLDER in runbook_text
            and "Do not use the time this runbook was generated as send evidence." in runbook_text
            and "Suggested sent_at_utc format:" not in runbook_text
        ),
        "private_send_runbook_shell_safe_placeholders": _runbook_shell_safe_placeholders(runbook_text),
        "receipt_omits_local_paths": True,
        "receipt_omits_copy_paste_message": True,
    }
    payload: dict[str, Any] = {
        "schema_version": FIRST_RECIPIENT_SEND_WORKSPACE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "FIRST_RECIPIENT_SEND_WORKSPACE_READY" if all(checks.values()) else "FIRST_RECIPIENT_SEND_WORKSPACE_BLOCKED",
        "safe_to_share": True,
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "operator_packet": {
            "file": operator_packet_path.name,
            "body_sha256": operator_packet.get("operator_dispatch_packet_body_sha256"),
            "copy_paste_message_sha256": send_once.get("copy_paste_message_sha256"),
        },
        "private_workspace": {
            "scaffold_receipt_file": PRIVATE_WORKSPACE_RECEIPT_NAME,
            "scaffold_receipt_body_sha256": scaffold_receipt.get("private_workspace_receipt_body_sha256"),
            "send_runbook_file": PRIVATE_SEND_RUNBOOK_NAME,
            "preflight_receipt_file": PREFLIGHT_RECEIPT_NAME,
            "operator_dispatch_note_template_seed": {
                "file": OPERATOR_DISPATCH_NOTE_FILE,
                "status": operator_note_seed.get("status"),
                "raw_template_included": False,
                "local_path_included": False,
            },
            "send_runbook_contains_local_paths": True,
            "send_runbook_contains_copy_paste_message": True,
            "send_runbook_safe_to_share": False,
        },
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "records_private_sha256_only_after_send": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "do_not_share": [
            PRIVATE_SEND_RUNBOOK_NAME,
            "recipient raw identifier",
            "operator dispatch note raw text",
            "recipient acknowledgement raw text",
            "pilot feedback raw text",
            "pilot issue intake raw text",
            "operator decision note raw text",
            "private workspace path",
            ".env",
            "API key or secret",
        ],
        "checks": checks,
    }
    payload["first_recipient_send_workspace_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload


def _runbook_shell_safe_placeholders(runbook_text: str) -> bool:
    """Return true when command placeholders are quoted instead of shell-active tokens."""
    quoted_required = [
        f'--sent-at-utc "{SENT_AT_UTC_PLACEHOLDER}"',
        f'--builder-gold-path-share-receipt "{BUILDER_GOLD_PATH_RECEIPT_PLACEHOLDER}"',
        f'--operator-decision "{OPERATOR_DECISION_PLACEHOLDER}"',
        f'--outcome-tag "{CONTROLLED_OUTCOME_TAG_PLACEHOLDER}"',
        f'--friction-tag "{CONTROLLED_FRICTION_TAG_PLACEHOLDER}"',
        f'--missing-skill-tag "{CONTROLLED_MISSING_SKILL_TAG_PLACEHOLDER}"',
    ]
    unquoted_forbidden = [
        f"--sent-at-utc {SENT_AT_UTC_PLACEHOLDER}",
        f"--builder-gold-path-share-receipt {BUILDER_GOLD_PATH_RECEIPT_PLACEHOLDER}",
        f"--operator-decision {OPERATOR_DECISION_PLACEHOLDER}",
        f"--outcome-tag {CONTROLLED_OUTCOME_TAG_PLACEHOLDER}",
        f"--friction-tag {CONTROLLED_FRICTION_TAG_PLACEHOLDER}",
        f"--missing-skill-tag {CONTROLLED_MISSING_SKILL_TAG_PLACEHOLDER}",
    ]
    return all(fragment in runbook_text for fragment in quoted_required) and not any(
        fragment in runbook_text for fragment in unquoted_forbidden
    )


def _assert_shareable_receipt_file(path: Path, workspace_dir: Path, operator_packet: dict[str, Any]) -> None:
    text = path.read_text(encoding="utf-8")
    copy_paste_message = str(operator_packet.get("operator_send_once", {}).get("copy_paste_message") or "")
    forbidden = [
        str(ROOT),
        str(Path.home()),
        str(workspace_dir),
        copy_paste_message,
        "Recipient identifier/contact goes here",
        "Record the private channel",
        OPERATOR_DISPATCH_NOTE_TEMPLATE_PLACEHOLDER,
        "Paste only the private acknowledgement",
        "Keep raw feedback here",
        "Keep raw issue intake here",
        "Write the private decision rationale",
    ]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise FirstRecipientSendWorkspaceError("first-recipient send workspace receipt leaked local path or private text.")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "first_recipient_send_workspace_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_ascii(value: str) -> bool:
    return all(ord(char) < 128 for char in value)


def _is_mojibake_free(value: str) -> bool:
    return not any(marker in value for marker in MOJIBAKE_MARKERS)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise FirstRecipientSendWorkspaceError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise FirstRecipientSendWorkspaceError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FirstRecipientSendWorkspaceError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the private workspace for one external alpha recipient send.")
    parser.add_argument("--workspace-dir", default=str(DEFAULT_FIRST_RECIPIENT_WORKSPACE_DIR))
    parser.add_argument("--operator-packet", default=str(DEFAULT_OPERATOR_PACKET_PATH))
    parser.add_argument("--receipt", default=None, help="Optional share-safe receipt JSON path.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite private scaffold and runbook. Use only before any real private data is entered.",
    )
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing first-recipient workspace receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_send_workspace_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
            logger.error("[FAIL] external alpha first-recipient send workspace receipt verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha first-recipient send workspace receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["first_recipient_send_workspace_receipt_body_sha256"])
        return 0

    try:
        result = prepare_first_recipient_send_workspace(
            Path(args.workspace_dir),
            operator_packet_path=Path(args.operator_packet),
            receipt_path=Path(args.receipt) if args.receipt else None,
            force=args.force,
        )
    except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
        logger.error("[FAIL] external alpha first-recipient send workspace: %s", exc)
        return 1

    logger.info("[PASS] external alpha first-recipient send workspace")
    logger.info("verdict : %s", result["verdict"])
    logger.info("runbook : %s", result["private_runbook"])
    logger.info("receipt : %s", result["receipt_json"])
    logger.info("sha256  : %s", result["archive_sha256"])
    logger.info("body    : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
