"""Prepare a local-only workspace for one Cambrian install-kit recipient."""

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

from scripts.prepare_cambrian_install_kit_release import RELEASE_BUNDLE_NAME  # noqa: E402
from scripts.smoke_cambrian_install_kit_release_bundle import (  # noqa: E402
    BUNDLE_SMOKE_RECEIPT_NAME,
    verify_bundle_smoke_receipt_payload,
)


WORKSPACE_SCHEMA_VERSION = "cambrian_install_kit_first_recipient_workspace_v0_1"
WORKSPACE_RECEIPT_NAME = "cambrian-install-kit-first-recipient-workspace-receipt.json"
PRIVATE_RUNBOOK_NAME = "SEND_CAMBRIAN_INSTALL_KIT_ONE_PRIVATE.md"
DEFAULT_WORKSPACE_DIR = ROOT / ".cambrian" / "private" / "install-kit-first-recipient"
OPERATOR_STATUS_RECEIPT_NAME = "cambrian-install-kit-first-recipient-operator-status-receipt.json"
OPERATOR_STATUS_READY_RECEIPT_NAME = "cambrian-install-kit-first-recipient-operator-status-ready-receipt.json"
OPERATOR_STATUS_MD_NAME = "cambrian-install-kit-first-recipient-operator-status.md"
PRE_SEND_SEQUENCE_RECEIPT_NAME = "cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json"
MANUAL_SEND_GO_RECEIPT_NAME = "cambrian-install-kit-first-recipient-manual-send-go-receipt.json"
POST_SEND_SEQUENCE_RECEIPT_NAME = "cambrian-install-kit-first-recipient-post-send-sequence-receipt.json"
SENT_AT_UTC_PLACEHOLDER = "<real-sent-at-utc>"
PRIVATE_WORKSPACE_DIR_PLACEHOLDER = "<private-workspace-dir>"
OPERATOR_DISPATCH_NOTE_PRIVATE_NAME = "operator-dispatch-note-private.md"
OPERATOR_DISPATCH_NOTE_LEGACY_PLACEHOLDER = "REPLACE_WITH_PRIVATE_SEND_CHANNEL"
PRIVATE_SEND_CHANNEL_PLACEHOLDER = "<private-send-channel>"
PRIVATE_OPERATOR_NOTE_PLACEHOLDER = "<private-operator-note>"
HUMAN_PRIVATE_FIELD_CHECKLIST = (
    {
        "step": 1,
        "file": "recipient-private.txt",
        "gate": "recipient_private_ready",
        "action": "Replace the whole file with exactly one non-empty recipient identifier or contact.",
    },
    {
        "step": 2,
        "file": OPERATOR_DISPATCH_NOTE_PRIVATE_NAME,
        "gate": "operator_note_names_private_channel",
        "action": "Replace <private-send-channel> with the real private send channel and keep the current release bundle sha256.",
    },
)

PRIVATE_FILE_SPECS = (
    {
        "file": "recipient-private.txt",
        "placeholder": "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER",
        "purpose": "exactly one private recipient identifier or contact",
    },
    {
        "file": OPERATOR_DISPATCH_NOTE_PRIVATE_NAME,
        "placeholder": OPERATOR_DISPATCH_NOTE_LEGACY_PLACEHOLDER,
        "purpose": "private send channel, timestamp, and operator note",
    },
    {
        "file": "recipient-ack-private.txt",
        "placeholder": "WAIT_FOR_ONE_CONFIRMED_LINE",
        "purpose": "exactly one CONFIRMED line from the recipient after manual send",
    },
)
RETURNED_RECEIPT_FILES = (
    "cambrian_install_share_receipt.json",
    "cambrian_gold_path_share_receipt.json",
    "mcp_operability_receipt.json",
)

logger = logging.getLogger(__name__)


class InstallKitFirstRecipientWorkspaceError(RuntimeError):
    """Install-kit first-recipient workspace preparation failed."""


def prepare_first_recipient_workspace(
    workspace_dir: Path | None = None,
    *,
    output_dir: Path | None = None,
    receipt_path: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create private placeholders, a local-only runbook, and a share-safe receipt."""
    dist = (output_dir or ROOT / "dist").resolve()
    workspace = (workspace_dir or DEFAULT_WORKSPACE_DIR).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    returned_dir = workspace / "returned-receipts"
    returned_dir.mkdir(parents=True, exist_ok=True)

    bundle_path = dist / RELEASE_BUNDLE_NAME
    smoke_path = dist / BUNDLE_SMOKE_RECEIPT_NAME
    if not bundle_path.is_file():
        raise InstallKitFirstRecipientWorkspaceError(f"release bundle is missing: {RELEASE_BUNDLE_NAME}")
    smoke = _read_json(smoke_path)
    verify_bundle_smoke_receipt_payload(smoke)
    release_bundle_sha256 = _file_sha256(bundle_path)

    private_files = [
        _seed_private_file(workspace, spec, release_bundle_sha256=release_bundle_sha256, force=force)
        for spec in PRIVATE_FILE_SPECS
    ]
    returned_readme = returned_dir / "README_RETURNED_RECEIPTS_PRIVATE.md"
    returned_readme.write_text(_returned_receipts_readme(), encoding="utf-8")

    runbook_path = workspace / PRIVATE_RUNBOOK_NAME
    runbook_path.write_text(
        _private_runbook(
            workspace=workspace,
            release_bundle_sha256=release_bundle_sha256,
            smoke_body_sha256=str(smoke.get("bundle_smoke_receipt_body_sha256")),
        ),
        encoding="utf-8",
    )

    receipt = _workspace_receipt(
        release_bundle_sha256=release_bundle_sha256,
        smoke=smoke,
        private_files=private_files,
        runbook_path=runbook_path,
        returned_readme=returned_readme,
    )
    target = (receipt_path or workspace / WORKSPACE_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, receipt)
    verify_first_recipient_workspace_receipt_file(target)
    return {
        "status": receipt["status"],
        "verdict": receipt["verdict"],
        "workspace_dir": str(workspace),
        "private_runbook": str(runbook_path),
        "receipt_json": str(target),
        "receipt_body_sha256": receipt["workspace_receipt_body_sha256"],
        "release_bundle_sha256": receipt["release_bundle"]["sha256"],
    }


def verify_first_recipient_workspace_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_workspace_receipt_payload(payload)
    return payload


def verify_first_recipient_workspace_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != WORKSPACE_SCHEMA_VERSION:
        raise InstallKitFirstRecipientWorkspaceError("workspace receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "INSTALL_KIT_FIRST_RECIPIENT_WORKSPACE_READY":
        raise InstallKitFirstRecipientWorkspaceError("workspace receipt did not pass.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitFirstRecipientWorkspaceError("workspace receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise InstallKitFirstRecipientWorkspaceError("workspace receipt checks failed.")
    receipt_checks = _receipt_checks(payload)
    if payload.get("workspace_receipt_checks") != receipt_checks:
        raise InstallKitFirstRecipientWorkspaceError("workspace receipt self-checks are stale.")
    failed = [name for name, passed in receipt_checks.items() if passed is not True]
    if failed:
        raise InstallKitFirstRecipientWorkspaceError("workspace receipt self-check failed: " + ", ".join(failed))
    if payload.get("workspace_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitFirstRecipientWorkspaceError("workspace receipt body hash mismatch.")


def _seed_private_file(
    workspace: Path,
    spec: dict[str, str],
    *,
    release_bundle_sha256: str,
    force: bool,
) -> dict[str, Any]:
    path = workspace / spec["file"]
    placeholder = spec["placeholder"]
    scaffold = (
        _operator_dispatch_note_template(release_bundle_sha256)
        if spec["file"] == OPERATOR_DISPATCH_NOTE_PRIVATE_NAME
        else placeholder + "\n"
    )
    if force or not path.exists():
        path.write_text(scaffold, encoding="utf-8")
        status = "placeholder"
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            status = "unreadable_preserved"
        else:
            stripped = text.strip()
            if not stripped:
                path.write_text(scaffold, encoding="utf-8")
                status = "placeholder"
            elif stripped == placeholder or _is_operator_dispatch_note_scaffold(spec["file"], text):
                if spec["file"] == OPERATOR_DISPATCH_NOTE_PRIVATE_NAME:
                    path.write_text(scaffold, encoding="utf-8")
                status = "placeholder"
            else:
                status = "private_value_preserved"
    return {
        "file": spec["file"],
        "purpose": spec["purpose"],
        "status": status,
        "exists": path.is_file(),
        "sha256_present": status == "private_value_preserved",
    }


def _operator_dispatch_note_template(release_bundle_sha256: str) -> str:
    return f"""# Cambrian Install Kit First Recipient - Operator Dispatch Note Private

This file is local-only. Do not share it, commit it, paste it into chat, or attach screenshots of it.

private channel: {PRIVATE_SEND_CHANNEL_PLACEHOLDER}
release bundle sha256: {release_bundle_sha256}
operator note: {PRIVATE_OPERATOR_NOTE_PLACEHOLDER}

Replace `{PRIVATE_SEND_CHANNEL_PLACEHOLDER}` with the real private send channel before running the pre-send sequence.
Cambrian must keep blocking manual send while this placeholder remains.
"""


def _is_operator_dispatch_note_scaffold(file_name: str, text: str) -> bool:
    if file_name != OPERATOR_DISPATCH_NOTE_PRIVATE_NAME:
        return False
    return (
        PRIVATE_SEND_CHANNEL_PLACEHOLDER in text
        or OPERATOR_DISPATCH_NOTE_LEGACY_PLACEHOLDER in text
    )


def _workspace_receipt(
    *,
    release_bundle_sha256: str,
    smoke: dict[str, Any],
    private_files: list[dict[str, Any]],
    runbook_path: Path,
    returned_readme: Path,
) -> dict[str, Any]:
    operator_commands = _safe_operator_commands()
    human_private_field_checklist = _human_private_field_checklist()
    runbook_text = runbook_path.read_text(encoding="utf-8")
    checks = {
        "release_bundle_sha256_present": _looks_like_sha256(release_bundle_sha256),
        "bundle_smoke_status_pass": smoke.get("status") == "pass",
        "bundle_smoke_checks_true": _all_true(smoke.get("checks")),
        "bundle_smoke_mcp_verified": smoke.get("checks", {}).get("gold_path_mcp_operability_verified") is True,
        "private_files_created_or_preserved": all(item.get("exists") is True for item in private_files),
        "returned_receipts_named": set(RETURNED_RECEIPT_FILES).issubset(set(_returned_receipt_commands().keys())),
        "runbook_written": runbook_path.name == PRIVATE_RUNBOOK_NAME and runbook_path.is_file(),
        "script_sends_to_recipient_false": True,
        "manual_operator_send_required": True,
        "one_recipient_only": True,
        "raw_private_content_omitted": True,
        "returned_readme_written": returned_readme.name == "README_RETURNED_RECEIPTS_PRIVATE.md"
        and returned_readme.is_file(),
        "private_runbook_shell_safe_placeholders": _runbook_quotes_command_placeholders(runbook_path),
        "private_runbook_names_operator_status_board": OPERATOR_STATUS_MD_NAME in runbook_text,
        "private_runbook_two_edit_checklist": _runbook_has_two_edit_checklist(runbook_text),
        "human_private_field_checklist_controlled": _human_private_field_checklist_is_controlled(
            human_private_field_checklist
        ),
        "operator_commands_shell_safe_placeholders": _operator_commands_quote_placeholders(operator_commands),
    }
    payload: dict[str, Any] = {
        "schema_version": WORKSPACE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": "INSTALL_KIT_FIRST_RECIPIENT_WORKSPACE_READY",
        "safe_to_share": True,
        "release_bundle": {
            "file": RELEASE_BUNDLE_NAME,
            "sha256": release_bundle_sha256,
        },
        "release_bundle_smoke": {
            "file": BUNDLE_SMOKE_RECEIPT_NAME,
            "body_sha256": smoke.get("bundle_smoke_receipt_body_sha256"),
            "status": smoke.get("status"),
            "mcp_operability_verified": smoke.get("checks", {}).get("gold_path_mcp_operability_verified") is True,
        },
        "workspace_artifacts": {
            "private_runbook_file": PRIVATE_RUNBOOK_NAME,
            "workspace_receipt_file": WORKSPACE_RECEIPT_NAME,
            "operator_status_receipt_file": OPERATOR_STATUS_RECEIPT_NAME,
            "operator_status_ready_receipt_file": OPERATOR_STATUS_READY_RECEIPT_NAME,
            "operator_status_board_file": OPERATOR_STATUS_MD_NAME,
            "returned_receipts_readme_file": "returned-receipts/README_RETURNED_RECEIPTS_PRIVATE.md",
        },
        "private_files": private_files,
        "human_private_field_checklist": human_private_field_checklist,
        "returned_receipts": list(RETURNED_RECEIPT_FILES),
        "operator_commands": operator_commands,
        "checks": checks,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "raw_recipient_content_included": False,
            "secrets_included": False,
        },
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["workspace_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["workspace_receipt_checks"] = _receipt_checks(payload)
    return payload


def _private_runbook(*, workspace: Path, release_bundle_sha256: str, smoke_body_sha256: str) -> str:
    status_command = (
        f'python scripts/check_cambrian_install_kit_first_recipient_operator_status.py --workspace-dir "{workspace}"'
    )
    pre_send_sequence_command = (
        f'python scripts/check_cambrian_install_kit_first_recipient_pre_send_sequence.py --workspace-dir "{workspace}"'
    )
    manual_send_go_command = (
        f'python scripts/check_cambrian_install_kit_first_recipient_manual_send_go.py --workspace-dir "{workspace}"'
    )
    dispatch_command = (
        f'python scripts/check_cambrian_install_kit_dispatch_record.py --recipient-private-file "{workspace / "recipient-private.txt"}" '
        f'--operator-dispatch-note-private-file "{workspace / "operator-dispatch-note-private.md"}" '
        f'--operator-status-receipt "{workspace / OPERATOR_STATUS_READY_RECEIPT_NAME}" '
        "--require-operator-status-receipt "
        f'--manual-send-go-receipt "{workspace / MANUAL_SEND_GO_RECEIPT_NAME}" '
        "--require-manual-send-go-receipt "
        f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
    )
    checkpoint_command = (
        f'python scripts/check_cambrian_install_kit_recipient_checkpoint.py '
        f'--recipient-private-file "{workspace / "recipient-private.txt"}" '
        f'--operator-dispatch-note-private-file "{workspace / "operator-dispatch-note-private.md"}" '
        f'--operator-status-receipt "{workspace / OPERATOR_STATUS_READY_RECEIPT_NAME}" '
        "--require-operator-status-receipt "
        f'--manual-send-go-receipt "{workspace / MANUAL_SEND_GO_RECEIPT_NAME}" '
        "--require-manual-send-go-receipt "
        f'--recipient-ack-private-file "{workspace / "recipient-ack-private.txt"}" '
        f'--install-share-receipt "{workspace / "returned-receipts" / "cambrian_install_share_receipt.json"}" '
        f'--gold-path-share-receipt "{workspace / "returned-receipts" / "cambrian_gold_path_share_receipt.json"}" '
        f'--mcp-operability-receipt "{workspace / "returned-receipts" / "mcp_operability_receipt.json"}" '
        f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
    )
    post_send_sequence_command = (
        f'python scripts/check_cambrian_install_kit_first_recipient_post_send_sequence.py --workspace-dir "{workspace}" '
        f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
    )
    return f"""# Cambrian Install Kit First Recipient - Private Runbook

This file is local-only. Do not share it, commit it, paste it into chat, or attach screenshots of it.

## Before Manual Send

Only these two files are edited before manual-send GO:

- `recipient-private.txt`: replace the whole file with exactly one non-empty recipient identifier or contact.
- `operator-dispatch-note-private.md`: replace `{PRIVATE_SEND_CHANNEL_PLACEHOLDER}` with the real private send channel and keep this release bundle sha256 unchanged: `{release_bundle_sha256}`.

1. Replace `recipient-private.txt` with exactly one recipient contact or identifier.
2. Replace `operator-dispatch-note-private.md` with the private channel and this exact release bundle sha256: `{release_bundle_sha256}`.
3. Run the pre-send sequence command below and continue only when verdict is `READY_TO_MANUALLY_SEND_ONE`.
4. Run the manual-send GO command below and continue only when verdict is `GO_TO_MANUALLY_SEND_ONE`.
5. If you need a narrower diagnosis, run the operator status command below and inspect only the safe gate ids.
6. Open `{OPERATOR_STATUS_MD_NAME}` after the status command if you want the human-readable safe status board. It mirrors verdict, open gates, private file statuses, release bundle sha256, and safe commands without raw recipient or channel values.
7. Confirm that `{OPERATOR_STATUS_READY_RECEIPT_NAME}` exists. This preserved READY receipt is the file used by dispatch and recipient checkpoint after the normal status receipt later changes to `WAITING_FOR_RECIPIENT_RECEIPTS`.
8. Send exactly one file manually: `{RELEASE_BUNDLE_NAME}`.
9. Bundle smoke receipt body sha256: `{smoke_body_sha256}`.

Cambrian does not send this file, email, message, or upload anything for you.

```powershell
{pre_send_sequence_command}
```

```powershell
{manual_send_go_command}
```

```powershell
{status_command}
```

## Message To Send With The Bundle

Ask the recipient to open `START_HERE_CAMBRIAN_INSTALL_KIT.md`, run the install path, run the required AI Company Gold Path, then return only these share-safe receipts:

```text
cambrian_install_share_receipt.json
cambrian_gold_path_share_receipt.json
mcp_operability_receipt.json
```

## After Manual Send

Run this only after the one manual send actually happened. Replace `{SENT_AT_UTC_PLACEHOLDER}` with the real UTC send timestamp, for example `2026-05-15T10:00:00Z`.

```powershell
{post_send_sequence_command}
```

If you need the lower-level dispatch command directly:

```powershell
{dispatch_command}
```

## After Recipient Returns Receipts

Put returned receipts in `returned-receipts/`, put exactly one `CONFIRMED` line in `recipient-ack-private.txt`, then run:

```powershell
{checkpoint_command}
```

## Boundary

Do not pass raw recipient, channel, acknowledgement, or support text directly in CLI arguments. Use these private files so public artifacts store only sha256 values and safe summaries.
"""


def _returned_receipts_readme() -> str:
    return """# Returned Receipts - Private

Place only recipient-returned share-safe receipts in this folder:

- cambrian_install_share_receipt.json
- cambrian_gold_path_share_receipt.json
- mcp_operability_receipt.json

Do not place raw project files, secrets, screenshots, logs, or private conversation text here.
"""


def _returned_receipt_commands() -> dict[str, str]:
    return {
        "cambrian_install_share_receipt.json": f"--install-share-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/returned-receipts/cambrian_install_share_receipt.json')}",
        "cambrian_gold_path_share_receipt.json": f"--gold-path-share-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/returned-receipts/cambrian_gold_path_share_receipt.json')}",
        "mcp_operability_receipt.json": f"--mcp-operability-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/returned-receipts/mcp_operability_receipt.json')}",
    }


def _human_private_field_checklist() -> list[dict[str, Any]]:
    return [dict(item) for item in HUMAN_PRIVATE_FIELD_CHECKLIST]


def _human_private_field_checklist_is_controlled(checklist: Any) -> bool:
    return checklist == _human_private_field_checklist()


def _runbook_has_two_edit_checklist(text: str) -> bool:
    return (
        "Only these two files are edited before manual-send GO:" in text
        and "- `recipient-private.txt`: replace the whole file with exactly one non-empty recipient identifier or contact."
        in text
        and f"- `operator-dispatch-note-private.md`: replace `{PRIVATE_SEND_CHANNEL_PLACEHOLDER}` with the real private send channel"
        in text
    )


def _safe_operator_commands() -> dict[str, str]:
    return {
        "prepare_workspace": (
            "python scripts/prepare_cambrian_install_kit_first_recipient_workspace.py "
            f"--workspace-dir {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER)}"
        ),
        "check_operator_status": (
            "python scripts/check_cambrian_install_kit_first_recipient_operator_status.py "
            f"--workspace-dir {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER)}"
        ),
        "run_pre_send_sequence": (
            "python scripts/check_cambrian_install_kit_first_recipient_pre_send_sequence.py "
            f"--workspace-dir {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER)}"
        ),
        "run_manual_send_go": (
            "python scripts/check_cambrian_install_kit_first_recipient_manual_send_go.py "
            f"--workspace-dir {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER)}"
        ),
        "record_dispatch": (
            "python scripts/check_cambrian_install_kit_dispatch_record.py "
            f"--recipient-private-file {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/recipient-private.txt')} "
            f"--operator-dispatch-note-private-file {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/operator-dispatch-note-private.md')} "
            f"--operator-status-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/' + OPERATOR_STATUS_READY_RECEIPT_NAME)} "
            "--require-operator-status-receipt "
            f"--manual-send-go-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/' + MANUAL_SEND_GO_RECEIPT_NAME)} "
            "--require-manual-send-go-receipt "
            f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
        ),
        "run_post_send_sequence": (
            "python scripts/check_cambrian_install_kit_first_recipient_post_send_sequence.py "
            f"--workspace-dir {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER)} "
            f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
        ),
        "record_recipient_checkpoint": (
            "python scripts/check_cambrian_install_kit_recipient_checkpoint.py "
            f"--recipient-private-file {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/recipient-private.txt')} "
            f"--operator-dispatch-note-private-file {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/operator-dispatch-note-private.md')} "
            f"--operator-status-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/' + OPERATOR_STATUS_READY_RECEIPT_NAME)} "
            "--require-operator-status-receipt "
            f"--manual-send-go-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/' + MANUAL_SEND_GO_RECEIPT_NAME)} "
            "--require-manual-send-go-receipt "
            f"--recipient-ack-private-file {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/recipient-ack-private.txt')} "
            f"--install-share-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/returned-receipts/cambrian_install_share_receipt.json')} "
            f"--gold-path-share-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/returned-receipts/cambrian_gold_path_share_receipt.json')} "
            f"--mcp-operability-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/returned-receipts/mcp_operability_receipt.json')} "
            f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
        ),
    }


def _quote_placeholder(value: str) -> str:
    return f'"{value}"'


def _runbook_quotes_command_placeholders(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}" in text
        and f"--sent-at-utc {SENT_AT_UTC_PLACEHOLDER}" not in text
    )


def _operator_commands_quote_placeholders(commands: dict[str, str]) -> bool:
    if not commands:
        return False
    combined = "\n".join(commands.values())
    unsafe_patterns = [
        f"--workspace-dir {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--recipient-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--operator-dispatch-note-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--operator-status-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--recipient-ack-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--install-share-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--gold-path-share-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--mcp-operability-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--sent-at-utc {SENT_AT_UTC_PLACEHOLDER}",
    ]
    return all(pattern not in combined for pattern in unsafe_patterns)


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "workspace_receipt_body_sha256", "workspace_receipt_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(ROOT)
    home = str(Path.home())
    body_hash = payload.get("workspace_receipt_body_sha256")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    commands = payload.get("operator_commands") if isinstance(payload.get("operator_commands"), dict) else {}
    return {
        "schema_version_present": payload.get("schema_version") == WORKSPACE_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "private_values_omitted": "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
        and "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in serialized
        and "WAIT_FOR_ONE_CONFIRMED_LINE" not in serialized,
        "operator_commands_use_workspace_placeholder": bool(commands)
        and all("<private-workspace-dir>" in command for command in commands.values()),
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _all_true(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise InstallKitFirstRecipientWorkspaceError(f"required JSON file is missing: {path.name}") from exc
    if not isinstance(payload, dict):
        raise InstallKitFirstRecipientWorkspaceError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a private workspace for one Cambrian install-kit recipient.")
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Rewrite scaffold placeholders even if files already exist.")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing workspace receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_workspace_receipt_file(args.verify_receipt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit first-recipient workspace verification: %s", exc)
            return 1
        logger.info("[PASS] install kit first-recipient workspace verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["workspace_receipt_body_sha256"])
        logger.info("bundle : %s", payload["release_bundle"]["file"])
        return 0

    try:
        result = prepare_first_recipient_workspace(
            workspace_dir=args.workspace_dir,
            output_dir=args.output_dir,
            receipt_path=args.receipt,
            force=bool(args.force),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[FAIL] install kit first-recipient workspace: %s", exc)
        return 1
    logger.info("[PASS] install kit first-recipient workspace")
    logger.info("verdict: %s", result["verdict"])
    logger.info("runbook: %s", result["private_runbook"])
    logger.info("receipt: %s", result["receipt_json"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
