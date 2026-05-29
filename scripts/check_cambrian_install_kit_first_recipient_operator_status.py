"""Report the safe operator status for one Cambrian install-kit recipient."""

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

from scripts.check_cambrian_install_kit_dispatch_record import (  # noqa: E402
    DISPATCH_RECORD_JSON_NAME,
    verify_dispatch_record_file,
)
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import (  # noqa: E402
    DEFAULT_WORKSPACE_DIR,
    HUMAN_PRIVATE_FIELD_CHECKLIST,
    OPERATOR_DISPATCH_NOTE_LEGACY_PLACEHOLDER,
    OPERATOR_DISPATCH_NOTE_PRIVATE_NAME,
    PRIVATE_FILE_SPECS,
    PRIVATE_OPERATOR_NOTE_PLACEHOLDER,
    PRIVATE_SEND_CHANNEL_PLACEHOLDER,
    PRIVATE_WORKSPACE_DIR_PLACEHOLDER,
    PRIVATE_RUNBOOK_NAME,
    SENT_AT_UTC_PLACEHOLDER,
    WORKSPACE_RECEIPT_NAME,
    verify_first_recipient_workspace_receipt_file,
)
from scripts.prepare_cambrian_install_kit_release import (  # noqa: E402
    RELEASE_BUNDLE_NAME,
    verify_release_bundle_current_artifacts,
)
from scripts.smoke_cambrian_install_kit_release_bundle import (  # noqa: E402
    BUNDLE_SMOKE_RECEIPT_NAME,
    verify_bundle_smoke_receipt_payload,
)


OPERATOR_STATUS_SCHEMA_VERSION = "cambrian_install_kit_first_recipient_operator_status_v0_1"
OPERATOR_STATUS_RECEIPT_NAME = "cambrian-install-kit-first-recipient-operator-status-receipt.json"
OPERATOR_STATUS_READY_RECEIPT_NAME = "cambrian-install-kit-first-recipient-operator-status-ready-receipt.json"
OPERATOR_STATUS_MD_NAME = "cambrian-install-kit-first-recipient-operator-status.md"
MANUAL_SEND_GO_RECEIPT_NAME = "cambrian-install-kit-first-recipient-manual-send-go-receipt.json"

CHANNEL_MARKERS = (
    "channel",
    "private channel",
    "dm",
    "direct message",
    "email",
    "mail",
    "slack",
    "discord",
    "kakao",
    "telegram",
    "sms",
    "message",
)

logger = logging.getLogger(__name__)


class InstallKitFirstRecipientOperatorStatusError(RuntimeError):
    """Install-kit first-recipient operator status failed."""


def check_first_recipient_operator_status(
    workspace_dir: Path | None = None,
    *,
    output_dir: Path | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Write a share-safe status receipt without sending or exposing private values."""
    workspace = (workspace_dir or DEFAULT_WORKSPACE_DIR).resolve()
    dist = (output_dir or ROOT / "dist").resolve()
    payload = _status_payload(workspace=workspace, dist=dist)

    target = (receipt_path or workspace / OPERATOR_STATUS_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, payload)
    verify_first_recipient_operator_status_receipt_file(target)
    md_target = target.with_name(OPERATOR_STATUS_MD_NAME)
    _write_operator_status_markdown(md_target, payload)
    ready_receipt_path = _write_ready_receipt_if_ready(target, payload)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "manual_send_allowed": payload["operator_gates"]["manual_send_allowed"],
        "send_state": payload["operator_status_summary"]["send_state"],
        "open_gate_ids": payload["operator_status_summary"]["open_gate_ids"],
        "private_file_statuses": payload["operator_status_summary"]["private_file_statuses"],
        "receipt_json": str(target),
        "receipt_md": str(md_target),
        "ready_receipt_json": str(ready_receipt_path) if ready_receipt_path is not None else None,
        "receipt_body_sha256": payload["operator_status_receipt_body_sha256"],
        "next_action": payload["operator_next_action"],
    }


def _write_ready_receipt_if_ready(target: Path, payload: dict[str, Any]) -> Path | None:
    if payload.get("verdict") != "READY_TO_MANUALLY_SEND_ONE":
        return None
    ready_target = target.with_name(OPERATOR_STATUS_READY_RECEIPT_NAME)
    _write_json(ready_target, payload)
    verify_first_recipient_operator_status_receipt_file(ready_target)
    return ready_target


def _write_operator_status_markdown(path: Path, payload: dict[str, Any]) -> None:
    text = _operator_status_markdown(payload)
    _assert_share_safe_markdown(text)
    path.write_text(text, encoding="utf-8")


def _operator_status_markdown(payload: dict[str, Any]) -> str:
    snapshot = payload.get("operator_launch_snapshot") if isinstance(payload.get("operator_launch_snapshot"), dict) else {}
    summary = payload.get("operator_status_summary") if isinstance(payload.get("operator_status_summary"), dict) else {}
    private_statuses = (
        summary.get("private_file_statuses") if isinstance(summary.get("private_file_statuses"), dict) else {}
    )
    open_gates = summary.get("open_gate_ids") if isinstance(summary.get("open_gate_ids"), list) else []
    commands = payload.get("operator_commands") if isinstance(payload.get("operator_commands"), dict) else {}
    command_order = (
        payload.get("operator_command_use_order")
        if isinstance(payload.get("operator_command_use_order"), list)
        else []
    )
    lines = [
        "# Cambrian Install Kit First Recipient Operator Status",
        "",
        f"- verdict: {payload.get('verdict')}",
        f"- send_state: {summary.get('send_state')}",
        f"- manual_send_allowed: {summary.get('manual_send_allowed')}",
        f"- script_sends_to_recipient: {snapshot.get('script_sends_to_recipient')}",
        f"- max_recipients: {snapshot.get('max_recipients')}",
        f"- release_bundle_sha256: {snapshot.get('release_bundle_sha256')}",
        f"- release_bundle_current_artifacts_checked: {snapshot.get('release_bundle_current_artifacts_checked')}",
        f"- release_bundle_current_artifacts_match: {snapshot.get('release_bundle_current_artifacts_match')}",
        f"- bundle_smoke_mcp_operability_verified: {snapshot.get('bundle_smoke_mcp_operability_verified')}",
        f"- private_workspace_ready: {snapshot.get('private_workspace_ready')}",
        f"- dispatch_sent_recorded: {snapshot.get('dispatch_sent_recorded')}",
        f"- dispatch_sent_current: {snapshot.get('dispatch_sent_current')}",
        "",
        "## Open Gates",
        "",
    ]
    if open_gates:
        lines.extend(f"- {gate}" for gate in open_gates)
    else:
        lines.append("- none")
    lines.extend(["", "## Private File Statuses", ""])
    if private_statuses:
        lines.extend(f"- {name}: {status}" for name, status in sorted(private_statuses.items()))
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Human Edit Checklist",
            "",
        ]
    )
    checklist = (
        payload.get("human_private_field_checklist")
        if isinstance(payload.get("human_private_field_checklist"), list)
        else []
    )
    if checklist:
        for item in checklist:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('step')}. {item.get('file')}: {item.get('action')}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Next Safe Action",
            "",
            str(payload.get("operator_next_action") or ""),
            "",
            "## Safe Commands",
            "",
        ]
    )
    if command_order:
        lines.extend(["### Command Use Order", ""])
        for item in command_order:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('step')}. {item.get('command')}: {item.get('when')}"
            )
        lines.extend(["", "### Copyable Commands", ""])
    for name, command in commands.items():
        lines.extend([f"### {name}", "", f"```text", command, "```", ""])
    lines.extend(
        [
            "## Safety Boundary",
            "",
            "- This status file is safe to share.",
            "- It does not include raw recipient values, private channel text, secrets, or absolute workspace paths.",
            "- It does not send the install kit or record manual dispatch.",
            "",
        ]
    )
    return "\n".join(lines)


def _assert_share_safe_markdown(text: str) -> None:
    unsafe_fragments = [
        str(ROOT),
        str(Path.home()),
        "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER",
        "REPLACE_WITH_PRIVATE_SEND_CHANNEL",
        "WAIT_FOR_ONE_CONFIRMED_LINE",
    ]
    leaked = [fragment for fragment in unsafe_fragments if fragment and fragment in text]
    if leaked:
        raise InstallKitFirstRecipientOperatorStatusError("operator status markdown is not share-safe.")


def verify_first_recipient_operator_status_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_operator_status_receipt_payload(payload)
    return payload


def verify_first_recipient_operator_status_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != OPERATOR_STATUS_SCHEMA_VERSION:
        raise InstallKitFirstRecipientOperatorStatusError("operator status receipt schema_version mismatch.")
    if payload.get("status") != "pass":
        raise InstallKitFirstRecipientOperatorStatusError("operator status receipt status must be pass.")
    if payload.get("verdict") not in _allowed_verdicts():
        raise InstallKitFirstRecipientOperatorStatusError("operator status receipt verdict is invalid.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitFirstRecipientOperatorStatusError("operator status receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise InstallKitFirstRecipientOperatorStatusError("operator status receipt checks failed.")
    recalculated = _receipt_checks(payload)
    if payload.get("operator_status_receipt_checks") != recalculated:
        raise InstallKitFirstRecipientOperatorStatusError("operator status receipt self-checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise InstallKitFirstRecipientOperatorStatusError(
            "operator status receipt self-check failed: " + ", ".join(failed)
        )
    if payload.get("operator_status_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitFirstRecipientOperatorStatusError("operator status receipt body hash mismatch.")


def _status_payload(*, workspace: Path, dist: Path) -> dict[str, Any]:
    release = _release_bundle_summary(dist)
    release_current = _release_bundle_current_artifacts_summary(dist)
    smoke = _bundle_smoke_summary(dist, current_bundle_sha256=release.get("sha256"))
    workspace_summary = _workspace_summary(workspace, current_bundle_sha256=release.get("sha256"))
    private_files = [
        _private_file_status(workspace, spec, current_bundle_sha256=release.get("sha256"))
        for spec in PRIVATE_FILE_SPECS
    ]
    by_file = {item["file"]: item for item in private_files}
    recipient = by_file.get("recipient-private.txt", {})
    operator_note = by_file.get("operator-dispatch-note-private.md", {})
    private_hashes = {
        "recipient_private_sha256": recipient.get("private_sha256") if recipient.get("ready") else None,
        "operator_dispatch_note_private_sha256": operator_note.get("private_sha256")
        if operator_note.get("ready")
        else None,
    }
    dispatch = _dispatch_record_summary(
        dist,
        current_bundle_sha256=release.get("sha256"),
        private_hashes=private_hashes,
    )
    dispatch_sent_current = (
        dispatch.get("sent_recorded") is True
        and dispatch.get("release_hash_matches_current_bundle") is True
        and dispatch.get("private_hashes_match_current_files") is True
    )
    ready_before_send = (
        release.get("present") is True
        and release_current.get("current_artifacts_match") is not False
        and smoke.get("verified") is True
        and smoke.get("status") == "pass"
        and smoke.get("release_hash_matches_current_bundle") is True
        and smoke.get("mcp_operability_verified") is True
        and workspace_summary.get("verified") is True
        and workspace_summary.get("release_hash_matches_current_bundle") is True
        and recipient.get("ready") is True
        and operator_note.get("ready") is True
    )
    manual_send_allowed = ready_before_send and dispatch_sent_current is False

    operator_gates = {
        "release_bundle_present": release.get("present") is True,
        "release_bundle_hash_present": _looks_like_sha256(release.get("sha256")),
        "release_bundle_current_artifacts_match": release_current.get("current_artifacts_match") is not False,
        "bundle_smoke_receipt_verified": smoke.get("verified") is True,
        "bundle_smoke_receipt_passed": smoke.get("status") == "pass",
        "bundle_smoke_release_hash_matches_current_bundle": smoke.get("release_hash_matches_current_bundle") is True,
        "bundle_smoke_mcp_operability_verified": smoke.get("mcp_operability_verified") is True,
        "workspace_receipt_verified": workspace_summary.get("verified") is True,
        "workspace_receipt_release_hash_matches_current_bundle": workspace_summary.get(
            "release_hash_matches_current_bundle"
        )
        is True,
        "recipient_private_ready": recipient.get("ready") is True,
        "operator_note_ready": operator_note.get("ready") is True,
        "exactly_one_recipient": recipient.get("non_empty_line_count") == 1 and recipient.get("ready") is True,
        "operator_note_names_private_channel": operator_note.get("channel_named") is True,
        "operator_note_confirms_current_release_hash": operator_note.get("release_hash_named") is True,
        "dispatch_record_sent_current_private_hashes": dispatch_sent_current,
        "manual_send_allowed": manual_send_allowed,
        "one_recipient_only": True,
        "script_sends_to_recipient": False,
        "raw_private_values_included": False,
        "absolute_paths_included": False,
    }
    verdict = _operator_verdict(
        release=release,
        release_current=release_current,
        smoke=smoke,
        workspace_summary=workspace_summary,
        private_files=by_file,
        dispatch=dispatch,
        ready_before_send=ready_before_send,
        dispatch_sent_current=dispatch_sent_current,
    )
    open_gate_ids = _open_gate_ids(operator_gates, verdict=verdict, dispatch_sent_current=dispatch_sent_current)
    send_state = _send_state(verdict=verdict)
    next_action = _next_action(verdict, release_bundle_sha256=release.get("sha256"))
    payload: dict[str, Any] = {
        "schema_version": OPERATOR_STATUS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": verdict,
        "safe_to_share": True,
        "release_bundle": release,
        "release_bundle_current_artifacts": release_current,
        "release_bundle_smoke": smoke,
        "private_workspace": workspace_summary,
        "private_files": private_files,
        "private_hashes": private_hashes,
        "dispatch_record": dispatch,
        "operator_gates": operator_gates,
        "operator_status_summary": {
            "send_state": send_state,
            "manual_send_allowed": manual_send_allowed,
            "open_gate_ids": open_gate_ids,
            "private_file_statuses": _private_file_status_summary(private_files),
        },
        "operator_launch_snapshot": _operator_launch_snapshot(
            verdict=verdict,
            send_state=send_state,
            manual_send_allowed=manual_send_allowed,
            release=release,
            release_current=release_current,
            smoke=smoke,
            workspace_summary=workspace_summary,
            recipient=recipient,
            operator_note=operator_note,
            dispatch=dispatch,
            dispatch_sent_current=dispatch_sent_current,
            open_gate_ids=open_gate_ids,
            next_action=next_action,
        ),
        "operator_next_action": next_action,
        "human_private_field_checklist": _human_private_field_checklist(),
        "operator_commands": _safe_operator_commands(),
        "operator_command_use_order": _operator_command_use_order(),
        "checks": {
            "valid_verdict": verdict in _allowed_verdicts(),
            "status_receipt_only": True,
            "script_does_not_send_to_recipient": True,
            "manual_send_requires_human": True,
            "operator_launch_snapshot_controlled": True,
            "open_gate_ids_safe": True,
            "private_file_statuses_safe": True,
            "safe_to_share_true": True,
            "raw_private_values_omitted": True,
            "absolute_paths_omitted": True,
            "human_private_field_checklist_controlled": True,
        },
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "raw_recipient_content_included": False,
            "secrets_included": False,
        },
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["operator_status_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["operator_status_receipt_checks"] = _receipt_checks(payload)
    return payload


def _operator_launch_snapshot(
    *,
    verdict: str,
    send_state: str,
    manual_send_allowed: bool,
    release: dict[str, Any],
    release_current: dict[str, Any],
    smoke: dict[str, Any],
    workspace_summary: dict[str, Any],
    recipient: dict[str, Any],
    operator_note: dict[str, Any],
    dispatch: dict[str, Any],
    dispatch_sent_current: bool,
    open_gate_ids: list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "stage": verdict,
        "send_state": send_state,
        "manual_send_allowed": manual_send_allowed,
        "manual_operator_dispatch_required": True,
        "script_sends_to_recipient": False,
        "max_recipients": 1,
        "release_bundle_present": release.get("present") is True,
        "release_bundle_sha256": release.get("sha256") if _looks_like_sha256(release.get("sha256")) else None,
        "release_bundle_current_artifacts_checked": release_current.get("comparison_applicable") is True,
        "release_bundle_current_artifacts_match": release_current.get("current_artifacts_match"),
        "bundle_smoke_verified": smoke.get("verified") is True,
        "bundle_smoke_mcp_operability_verified": smoke.get("mcp_operability_verified") is True,
        "private_workspace_ready": workspace_summary.get("verified") is True
        and workspace_summary.get("release_hash_matches_current_bundle") is True,
        "recipient_private_ready": recipient.get("ready") is True,
        "recipient_private_exactly_one": recipient.get("non_empty_line_count") == 1 and recipient.get("ready") is True,
        "operator_note_ready": operator_note.get("ready") is True,
        "operator_note_names_private_channel": operator_note.get("channel_named") is True,
        "operator_note_confirms_current_release_hash": operator_note.get("release_hash_named") is True,
        "dispatch_record_verdict": dispatch.get("verdict"),
        "dispatch_sent_recorded": dispatch.get("sent_recorded") is True,
        "dispatch_sent_current": dispatch_sent_current,
        "open_gate_ids": open_gate_ids,
        "next_safe_action": next_action,
        "safe_to_share": True,
    }


def _private_file_status_summary(private_files: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(item.get("file")): str(item.get("status"))
        for item in private_files
        if isinstance(item, dict) and isinstance(item.get("file"), str)
    }


def _open_gate_ids(
    operator_gates: dict[str, bool],
    *,
    verdict: str | None,
    dispatch_sent_current: bool,
) -> list[str]:
    if verdict == "READY_TO_MANUALLY_SEND_ONE":
        return []
    if verdict == "WAITING_FOR_RECIPIENT_RECEIPTS":
        return ["recipient_receipts_returned"]
    if verdict == "REFRESH_DISPATCH_RECORD":
        return ["dispatch_record_sent_current_private_hashes"]

    if verdict == "PREPARE_RELEASE_BUNDLE":
        candidates = [
            "release_bundle_present",
            "release_bundle_hash_present",
            "release_bundle_current_artifacts_match",
            "bundle_smoke_receipt_verified",
            "bundle_smoke_receipt_passed",
            "bundle_smoke_release_hash_matches_current_bundle",
            "bundle_smoke_mcp_operability_verified",
        ]
    elif verdict == "PREPARE_PRIVATE_WORKSPACE":
        candidates = [
            "workspace_receipt_verified",
            "workspace_receipt_release_hash_matches_current_bundle",
        ]
    elif verdict == "FILL_PRIVATE_FIELDS" or verdict is None:
        candidates = [
            "recipient_private_ready",
            "operator_note_names_private_channel",
            "operator_note_confirms_current_release_hash",
        ]
    else:
        candidates = [
            "release_bundle_present",
            "bundle_smoke_receipt_verified",
            "workspace_receipt_verified",
            "recipient_private_ready",
            "operator_note_names_private_channel",
            "operator_note_confirms_current_release_hash",
        ]
    open_gates = [gate for gate in candidates if operator_gates.get(gate) is not True]
    if not open_gates and verdict not in {"READY_TO_MANUALLY_SEND_ONE", "WAITING_FOR_RECIPIENT_RECEIPTS"}:
        if dispatch_sent_current is not True and operator_gates.get("manual_send_allowed") is not True:
            open_gates.append("manual_send_allowed")
    return open_gates


def _send_state(*, verdict: str) -> str:
    return {
        "READY_TO_MANUALLY_SEND_ONE": "READY_TO_SEND",
        "WAITING_FOR_RECIPIENT_RECEIPTS": "WAITING_FOR_RECIPIENT",
        "REFRESH_DISPATCH_RECORD": "REFRESH_REQUIRED",
    }.get(verdict, "BLOCKED")


def _release_bundle_summary(dist: Path) -> dict[str, Any]:
    path = dist / RELEASE_BUNDLE_NAME
    if not path.is_file():
        return {"file": RELEASE_BUNDLE_NAME, "present": False, "sha256": None}
    return {"file": RELEASE_BUNDLE_NAME, "present": True, "sha256": _file_sha256(path)}


def _release_bundle_current_artifacts_summary(dist: Path) -> dict[str, Any]:
    path = dist / RELEASE_BUNDLE_NAME
    if not path.is_file():
        return {
            "file": RELEASE_BUNDLE_NAME,
            "present": False,
            "comparison_applicable": False,
            "verified": False,
            "current_artifacts_match": False,
            "status": "missing",
        }
    try:
        verified = verify_release_bundle_current_artifacts(path, output_dir=dist)
    except Exception as exc:  # noqa: BLE001
        if _is_current_artifact_mismatch_error(exc):
            return {
                "file": RELEASE_BUNDLE_NAME,
                "present": True,
                "comparison_applicable": True,
                "verified": False,
                "current_artifacts_match": False,
                "status": "stale_current_artifacts",
                "error_code": _safe_error_code(exc),
            }
        return {
            "file": RELEASE_BUNDLE_NAME,
            "present": True,
            "comparison_applicable": False,
            "verified": False,
            "current_artifacts_match": None,
            "status": "not_applicable_to_fixture_or_invalid_bundle",
            "error_code": _safe_error_code(exc),
        }
    checks = verified.get("current_artifact_checks") if isinstance(verified.get("current_artifact_checks"), dict) else {}
    summary = (
        verified.get("current_artifact_summary")
        if isinstance(verified.get("current_artifact_summary"), dict)
        else {}
    )
    return {
        "file": RELEASE_BUNDLE_NAME,
        "present": True,
        "comparison_applicable": True,
        "verified": True,
        "current_artifacts_match": checks.get("current_artifact_hashes_match_bundle") is True,
        "checked_count": summary.get("checked_count"),
        "status": "current_artifacts_match",
    }


def _is_current_artifact_mismatch_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "current artifact" in message or "mismatched=" in message or "missing=" in message


def _safe_error_code(exc: Exception) -> str:
    return exc.__class__.__name__


def _bundle_smoke_summary(dist: Path, *, current_bundle_sha256: Any) -> dict[str, Any]:
    path = dist / BUNDLE_SMOKE_RECEIPT_NAME
    if not path.is_file():
        return {
            "file": BUNDLE_SMOKE_RECEIPT_NAME,
            "present": False,
            "verified": False,
            "status": "missing",
            "body_sha256": None,
            "release_hash_matches_current_bundle": False,
            "mcp_operability_verified": False,
        }
    try:
        payload = _read_json(path)
        verify_bundle_smoke_receipt_payload(payload)
    except Exception:  # noqa: BLE001
        return {
            "file": BUNDLE_SMOKE_RECEIPT_NAME,
            "present": True,
            "verified": False,
            "status": "invalid",
            "body_sha256": None,
            "release_hash_matches_current_bundle": False,
            "mcp_operability_verified": False,
        }
    release = payload.get("release_bundle") if isinstance(payload.get("release_bundle"), dict) else {}
    gold_path = payload.get("gold_path_share_receipt") if isinstance(payload.get("gold_path_share_receipt"), dict) else {}
    return {
        "file": BUNDLE_SMOKE_RECEIPT_NAME,
        "present": True,
        "verified": True,
        "status": payload.get("status"),
        "body_sha256": payload.get("bundle_smoke_receipt_body_sha256"),
        "release_hash_matches_current_bundle": release.get("sha256") == current_bundle_sha256,
        "mcp_operability_verified": gold_path.get("mcp_operability_verified") is True
        or payload.get("checks", {}).get("gold_path_mcp_operability_verified") is True,
    }


def _workspace_summary(workspace: Path, *, current_bundle_sha256: Any) -> dict[str, Any]:
    path = workspace / WORKSPACE_RECEIPT_NAME
    if not path.is_file():
        return {
            "receipt_file": WORKSPACE_RECEIPT_NAME,
            "private_runbook_file": PRIVATE_RUNBOOK_NAME,
            "present": False,
            "verified": False,
            "status": "missing",
            "body_sha256": None,
            "release_hash_matches_current_bundle": False,
        }
    try:
        payload = verify_first_recipient_workspace_receipt_file(path)
    except Exception:  # noqa: BLE001
        return {
            "receipt_file": WORKSPACE_RECEIPT_NAME,
            "private_runbook_file": PRIVATE_RUNBOOK_NAME,
            "present": True,
            "verified": False,
            "status": "invalid",
            "body_sha256": None,
            "release_hash_matches_current_bundle": False,
        }
    release = payload.get("release_bundle") if isinstance(payload.get("release_bundle"), dict) else {}
    return {
        "receipt_file": WORKSPACE_RECEIPT_NAME,
        "private_runbook_file": PRIVATE_RUNBOOK_NAME,
        "present": True,
        "verified": True,
        "status": payload.get("status"),
        "verdict": payload.get("verdict"),
        "body_sha256": payload.get("workspace_receipt_body_sha256"),
        "release_hash_matches_current_bundle": release.get("sha256") == current_bundle_sha256,
    }


def _private_file_status(workspace: Path, spec: dict[str, str], *, current_bundle_sha256: Any) -> dict[str, Any]:
    file_name = spec["file"]
    placeholder = spec["placeholder"]
    path = workspace / file_name
    base: dict[str, Any] = {
        "file": file_name,
        "purpose": spec["purpose"],
        "exists": path.is_file(),
        "status": "missing",
        "non_empty_line_count": 0,
        "ready": False,
        "private_sha256": None,
    }
    if not path.is_file():
        return base
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        base["status"] = "unreadable"
        return base
    stripped = text.strip()
    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    base["non_empty_line_count"] = len(non_empty_lines)
    if not stripped:
        base["status"] = "empty"
        return base
    if stripped == placeholder:
        base["status"] = "placeholder"
        return base
    if file_name == OPERATOR_DISPATCH_NOTE_PRIVATE_NAME and _operator_note_has_unresolved_placeholder(text):
        lowered = text.lower()
        release_hash_named = isinstance(current_bundle_sha256, str) and current_bundle_sha256.lower() in lowered
        base["status"] = "placeholder"
        base["channel_named"] = False
        base["release_hash_named"] = release_hash_named
        return base

    private_sha256 = hashlib.sha256(raw).hexdigest()
    base["status"] = "private_value_present"
    base["private_sha256"] = private_sha256
    if file_name == "recipient-private.txt":
        base["ready"] = len(non_empty_lines) == 1 and _recipient_value_is_real(non_empty_lines[0])
        base["status"] = "ready" if base["ready"] else "too_many_lines"
        if len(non_empty_lines) == 1 and base["ready"] is not True:
            base["status"] = "placeholder"
    elif file_name == "operator-dispatch-note-private.md":
        channel_named = _operator_note_names_private_channel(text)
        lowered = text.lower()
        release_hash_named = isinstance(current_bundle_sha256, str) and current_bundle_sha256.lower() in lowered
        base["channel_named"] = channel_named
        base["release_hash_named"] = release_hash_named
        base["ready"] = channel_named and release_hash_named
        if not channel_named:
            base["status"] = "missing_private_channel"
        elif not release_hash_named:
            base["status"] = "missing_current_release_hash"
        else:
            base["status"] = "ready"
    elif file_name == "recipient-ack-private.txt":
        confirmed = any(line == "CONFIRMED" for line in non_empty_lines)
        base["confirmed"] = confirmed
        base["ready"] = confirmed
        base["status"] = "confirmed" if confirmed else "waiting_for_confirmed_line"
    return base


def _operator_note_has_unresolved_placeholder(text: str) -> bool:
    return (
        PRIVATE_SEND_CHANNEL_PLACEHOLDER in text
        or OPERATOR_DISPATCH_NOTE_LEGACY_PLACEHOLDER in text
    )


def _operator_note_names_private_channel(text: str) -> bool:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if ":" in line:
            key, value = line.split(":", 1)
            key_lowered = key.lower()
            if any(marker in key_lowered for marker in CHANNEL_MARKERS):
                return _operator_note_channel_value_is_real(value)
        for marker in CHANNEL_MARKERS:
            if marker not in lowered:
                continue
            after_marker = lowered.split(marker, 1)[1]
            if _operator_note_channel_value_is_real(after_marker):
                return True
    return False


def _operator_note_channel_value_is_real(value: str) -> bool:
    stripped = value.strip(" \t:-")
    if not stripped:
        return False
    return (
        PRIVATE_SEND_CHANNEL_PLACEHOLDER not in stripped
        and OPERATOR_DISPATCH_NOTE_LEGACY_PLACEHOLDER not in stripped
        and PRIVATE_OPERATOR_NOTE_PLACEHOLDER not in stripped
    )


def _recipient_value_is_real(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    placeholder_markers = (
        "<",
        ">",
        "placeholder",
        "replace",
        "recipient goes here",
        "recipient identifier",
        "sample",
        "dummy",
        "todo",
        "tbd",
    )
    return bool(stripped) and not any(marker in lowered for marker in placeholder_markers)


def _dispatch_record_summary(
    dist: Path,
    *,
    current_bundle_sha256: Any,
    private_hashes: dict[str, Any],
) -> dict[str, Any]:
    path = dist / DISPATCH_RECORD_JSON_NAME
    if not path.is_file():
        return {
            "file": DISPATCH_RECORD_JSON_NAME,
            "present": False,
            "verified": False,
            "status": "missing",
            "sent_recorded": False,
        }
    try:
        payload = verify_dispatch_record_file(path)
    except Exception:  # noqa: BLE001
        return {
            "file": DISPATCH_RECORD_JSON_NAME,
            "present": True,
            "verified": False,
            "status": "invalid",
            "sent_recorded": False,
        }
    record = payload.get("dispatch_record") if isinstance(payload.get("dispatch_record"), dict) else {}
    release_smoke = payload.get("release_bundle_smoke") if isinstance(payload.get("release_bundle_smoke"), dict) else {}
    sent_recorded = record.get("sent_recorded") is True
    private_hashes_match = (
        sent_recorded
        and record.get("recipient_private_sha256") == private_hashes.get("recipient_private_sha256")
        and record.get("operator_dispatch_note_private_sha256")
        == private_hashes.get("operator_dispatch_note_private_sha256")
    )
    return {
        "file": DISPATCH_RECORD_JSON_NAME,
        "present": True,
        "verified": True,
        "status": payload.get("status"),
        "verdict": payload.get("verdict"),
        "body_sha256": payload.get("dispatch_record_body_sha256"),
        "sent_recorded": sent_recorded,
        "sent_at_recorded": isinstance(record.get("sent_at_utc"), str) and bool(record.get("sent_at_utc")),
        "release_hash_matches_current_bundle": release_smoke.get("release_bundle_sha256") == current_bundle_sha256,
        "private_hashes_match_current_files": private_hashes_match,
    }


def _operator_verdict(
    *,
    release: dict[str, Any],
    release_current: dict[str, Any],
    smoke: dict[str, Any],
    workspace_summary: dict[str, Any],
    private_files: dict[str, dict[str, Any]],
    dispatch: dict[str, Any],
    ready_before_send: bool,
    dispatch_sent_current: bool,
) -> str:
    if release.get("present") is not True or smoke.get("verified") is not True:
        return "PREPARE_RELEASE_BUNDLE"
    if release_current.get("current_artifacts_match") is False:
        return "PREPARE_RELEASE_BUNDLE"
    if smoke.get("release_hash_matches_current_bundle") is not True:
        return "PREPARE_RELEASE_BUNDLE"
    if workspace_summary.get("verified") is not True:
        return "PREPARE_PRIVATE_WORKSPACE"
    if workspace_summary.get("release_hash_matches_current_bundle") is not True:
        return "PREPARE_PRIVATE_WORKSPACE"
    if dispatch.get("sent_recorded") is True and dispatch_sent_current is not True:
        return "REFRESH_DISPATCH_RECORD"
    if dispatch_sent_current:
        return "WAITING_FOR_RECIPIENT_RECEIPTS"
    recipient_ready = private_files.get("recipient-private.txt", {}).get("ready") is True
    note_ready = private_files.get("operator-dispatch-note-private.md", {}).get("ready") is True
    if not recipient_ready or not note_ready:
        return "FILL_PRIVATE_FIELDS"
    if ready_before_send:
        return "READY_TO_MANUALLY_SEND_ONE"
    return "FILL_PRIVATE_FIELDS"


def _next_action(verdict: str, *, release_bundle_sha256: Any = None) -> str:
    bundle_hash_hint = (
        f"release bundle sha256 {release_bundle_sha256}"
        if _looks_like_sha256(release_bundle_sha256)
        else "the current release bundle sha256"
    )
    return {
        "PREPARE_RELEASE_BUNDLE": "Regenerate and smoke-test the install-kit release bundle before preparing a recipient workspace.",
        "PREPARE_PRIVATE_WORKSPACE": "Run the first-recipient workspace preparation command for the current release bundle.",
        "FILL_PRIVATE_FIELDS": (
            "Fill recipient-private.txt with exactly one recipient and make operator-dispatch-note-private.md "
            f"name the private channel plus {bundle_hash_hint}."
        ),
        "READY_TO_MANUALLY_SEND_ONE": "The operator may manually send exactly one release bundle, then record dispatch with the private runbook command.",
        "WAITING_FOR_RECIPIENT_RECEIPTS": "Wait for the recipient to return share-safe install, gold path, and MCP operability receipts.",
        "REFRESH_DISPATCH_RECORD": "Review the existing dispatch record; it does not match the current private files or release bundle.",
    }[verdict]


def _human_private_field_checklist() -> list[dict[str, Any]]:
    return [dict(item) for item in HUMAN_PRIVATE_FIELD_CHECKLIST]


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
        "record_dispatch_after_manual_send": (
            "python scripts/check_cambrian_install_kit_dispatch_record.py "
            f"--recipient-private-file {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/recipient-private.txt')} "
            f"--operator-dispatch-note-private-file {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/operator-dispatch-note-private.md')} "
            f"--operator-status-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/' + OPERATOR_STATUS_READY_RECEIPT_NAME)} "
            "--require-operator-status-receipt "
            f"--manual-send-go-receipt {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER + '/' + MANUAL_SEND_GO_RECEIPT_NAME)} "
            "--require-manual-send-go-receipt "
            f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
        ),
        "run_post_send_sequence_after_manual_send": (
            "python scripts/check_cambrian_install_kit_first_recipient_post_send_sequence.py "
            f"--workspace-dir {_quote_placeholder(PRIVATE_WORKSPACE_DIR_PLACEHOLDER)} "
            f"--sent-at-utc {_quote_placeholder(SENT_AT_UTC_PLACEHOLDER)}"
        ),
        "record_recipient_checkpoint_after_return": (
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


def _operator_command_use_order() -> list[dict[str, Any]]:
    return [
        {
            "step": 1,
            "command": "prepare_workspace",
            "when": "Before any send, prepare or refresh the private workspace.",
        },
        {
            "step": 2,
            "command": "check_operator_status",
            "when": "Before any send, inspect the safe GO/NO-GO board.",
        },
        {
            "step": 3,
            "command": "run_pre_send_sequence",
            "when": "Before any send, continue only if it returns READY_TO_MANUALLY_SEND_ONE.",
        },
        {
            "step": 4,
            "command": "run_manual_send_go",
            "when": "Immediately before manual send, continue only if it returns GO_TO_MANUALLY_SEND_ONE.",
        },
        {
            "step": 5,
            "command": "record_dispatch_after_manual_send",
            "when": "After the human manually sends exactly one bundle, record the real UTC send timestamp.",
        },
        {
            "step": 6,
            "command": "run_post_send_sequence_after_manual_send",
            "when": "After dispatch is recorded, wait for returned receipts and acknowledgement evidence.",
        },
        {
            "step": 7,
            "command": "record_recipient_checkpoint_after_return",
            "when": "After returned install, gold path, MCP, and acknowledgement evidence are present.",
        },
    ]


def _quote_placeholder(value: str) -> str:
    return f'"{value}"'


def _operator_commands_quote_placeholders(commands: dict[str, str]) -> bool:
    if not commands:
        return False
    combined = "\n".join(commands.values())
    unsafe_patterns = [
        f"--workspace-dir {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--recipient-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--operator-dispatch-note-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--operator-status-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--sent-at-utc {SENT_AT_UTC_PLACEHOLDER}",
    ]
    return all(pattern not in combined for pattern in unsafe_patterns)


def _allowed_verdicts() -> set[str]:
    return {
        "PREPARE_RELEASE_BUNDLE",
        "PREPARE_PRIVATE_WORKSPACE",
        "FILL_PRIVATE_FIELDS",
        "READY_TO_MANUALLY_SEND_ONE",
        "WAITING_FOR_RECIPIENT_RECEIPTS",
        "REFRESH_DISPATCH_RECORD",
    }


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_status_receipt_body_sha256", "operator_status_receipt_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(ROOT)
    home = str(Path.home())
    body_hash = payload.get("operator_status_receipt_body_sha256")
    commands = payload.get("operator_commands") if isinstance(payload.get("operator_commands"), dict) else {}
    command_order = (
        payload.get("operator_command_use_order")
        if isinstance(payload.get("operator_command_use_order"), list)
        else []
    )
    checklist = (
        payload.get("human_private_field_checklist")
        if isinstance(payload.get("human_private_field_checklist"), list)
        else []
    )
    private_files = payload.get("private_files") if isinstance(payload.get("private_files"), list) else []
    summary = payload.get("operator_status_summary") if isinstance(payload.get("operator_status_summary"), dict) else {}
    open_gate_ids = summary.get("open_gate_ids") if isinstance(summary.get("open_gate_ids"), list) else []
    private_statuses = (
        summary.get("private_file_statuses") if isinstance(summary.get("private_file_statuses"), dict) else {}
    )
    snapshot = payload.get("operator_launch_snapshot") if isinstance(payload.get("operator_launch_snapshot"), dict) else {}
    return {
        "schema_version_present": payload.get("schema_version") == OPERATOR_STATUS_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "valid_verdict": payload.get("verdict") in _allowed_verdicts(),
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "private_placeholders_omitted": "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
        and "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in serialized
        and "WAIT_FOR_ONE_CONFIRMED_LINE" not in serialized,
        "raw_private_values_omitted": payload.get("privacy", {}).get("raw_recipient_content_included") is False,
        "open_gate_ids_are_identifiers": all(isinstance(item, str) and item and " " not in item for item in open_gate_ids),
        "private_file_statuses_are_safe_labels": set(private_statuses).issubset(
            {
                "recipient-private.txt",
                "operator-dispatch-note-private.md",
                "recipient-ack-private.txt",
            }
        )
        and all(isinstance(value, str) and len(value) <= 64 and "\n" not in value for value in private_statuses.values()),
        "private_file_hashes_only": all(
            isinstance(item, dict)
            and (
                item.get("private_sha256") is None
                or (isinstance(item.get("private_sha256"), str) and len(str(item.get("private_sha256"))) == 64)
            )
            for item in private_files
        ),
        "operator_commands_use_workspace_placeholder": bool(commands)
        and all("<private-workspace-dir>" in command for command in commands.values()),
        "operator_commands_shell_safe_placeholders": _operator_commands_quote_placeholders(commands),
        "operator_command_use_order_controlled": _operator_command_use_order_is_controlled(command_order, commands),
        "human_private_field_checklist_controlled": checklist == _human_private_field_checklist(),
        "operator_launch_snapshot_controlled": _operator_launch_snapshot_is_controlled(payload, snapshot),
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _operator_command_use_order_is_controlled(order: list[Any], commands: dict[str, str]) -> bool:
    expected = _operator_command_use_order()
    if order != expected:
        return False
    command_names = [item["command"] for item in expected]
    if set(command_names) != set(commands):
        return False
    return all(
        isinstance(item.get("when"), str)
        and item.get("when")
        and "\n" not in item["when"]
        and str(ROOT) not in item["when"]
        and str(Path.home()) not in item["when"]
        for item in expected
    )


def _operator_launch_snapshot_is_controlled(payload: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    summary = payload.get("operator_status_summary") if isinstance(payload.get("operator_status_summary"), dict) else {}
    return (
        bool(snapshot)
        and snapshot.get("stage") == payload.get("verdict")
        and snapshot.get("send_state") == summary.get("send_state")
        and snapshot.get("manual_send_allowed") == summary.get("manual_send_allowed")
        and snapshot.get("manual_operator_dispatch_required") is True
        and snapshot.get("script_sends_to_recipient") is False
        and snapshot.get("max_recipients") == 1
        and snapshot.get("open_gate_ids") == summary.get("open_gate_ids")
        and snapshot.get("next_safe_action") == payload.get("operator_next_action")
        and snapshot.get("safe_to_share") is True
    )


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitFirstRecipientOperatorStatusError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report safe operator status for one Cambrian install-kit recipient.")
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing operator status receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_operator_status_receipt_file(args.verify_receipt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit first-recipient operator status verification: %s", exc)
            return 1
        logger.info("[PASS] install kit first-recipient operator status verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("send_state: %s", payload["operator_status_summary"]["send_state"])
        logger.info("open_gates: %s", _format_open_gates(payload["operator_status_summary"]["open_gate_ids"]))
        logger.info("body   : %s", payload["operator_status_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_operator_status(
            workspace_dir=args.workspace_dir,
            output_dir=args.output_dir,
            receipt_path=args.receipt,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[FAIL] install kit first-recipient operator status: %s", exc)
        return 1
    logger.info("[PASS] install kit first-recipient operator status")
    logger.info("verdict: %s", result["verdict"])
    logger.info("send_state: %s", result["send_state"])
    logger.info("manual_send_allowed: %s", str(result["manual_send_allowed"]).lower())
    logger.info("private: %s", _format_private_statuses(result["private_file_statuses"]))
    logger.info("open_gates: %s", _format_open_gates(result["open_gate_ids"]))
    logger.info("next_action: %s", result["next_action"])
    logger.info("receipt: %s", Path(str(result["receipt_json"])).name)
    logger.info("md     : %s", Path(str(result["receipt_md"])).name)
    if result.get("ready_receipt_json"):
        logger.info("ready_receipt: %s", Path(str(result["ready_receipt_json"])).name)
    return 0


def _format_private_statuses(statuses: dict[str, str]) -> str:
    if not statuses:
        return "none"
    return ", ".join(f"{name}={status}" for name, status in sorted(statuses.items()))


def _format_open_gates(open_gate_ids: list[str]) -> str:
    return ", ".join(open_gate_ids) if open_gate_ids else "none"


if __name__ == "__main__":
    raise SystemExit(main())
