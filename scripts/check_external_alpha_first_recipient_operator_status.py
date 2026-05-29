"""Report the safe operator status for the first external alpha recipient."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_external_alpha_send_chain import audit_send_chain  # noqa: E402
from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_first_recipient_manual_send_go import (  # noqa: E402
    MANUAL_SEND_GO_RECEIPT_NAME,
    verify_first_recipient_manual_send_go_receipt_file,
)
from scripts.check_external_alpha_first_recipient_post_send_sequence import (  # noqa: E402
    BUILDER_GOLD_PATH_RECEIPT_NAME,
    POST_SEND_SEQUENCE_RECEIPT_NAME,
    verify_first_recipient_post_send_sequence_receipt_file,
)
from scripts.check_external_alpha_first_recipient_pre_send_sequence import (  # noqa: E402
    PRE_SEND_SEQUENCE_RECEIPT_NAME,
    verify_first_recipient_pre_send_sequence_receipt_file,
)
from scripts.check_external_alpha_first_recipient_send_preflight import (  # noqa: E402
    PREFLIGHT_RECEIPT_NAME,
    _operator_note_mentions_private_channel,
    _recipient_value_is_real,
    verify_first_recipient_send_preflight_receipt_file,
)
from scripts.prepare_external_alpha_first_recipient_send_workspace import (  # noqa: E402
    FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME,
    PRIVATE_SEND_RUNBOOK_NAME,
    verify_first_recipient_send_workspace_receipt_file,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import (  # noqa: E402
    PACKET_JSON_NAME,
    verify_operator_dispatch_packet_file,
)
from scripts.prepare_external_alpha_private_pilot_workspace import (  # noqa: E402
    DEFAULT_PRIVATE_WORKSPACE_DIR,
    PRIVATE_FILE_SPECS,
    PRIVATE_WORKSPACE_RECEIPT_NAME,
)


OPERATOR_STATUS_SCHEMA_VERSION = "external_alpha_first_recipient_operator_status_v0_1"
OPERATOR_STATUS_RECEIPT_NAME = "external-alpha-first-recipient-operator-status-receipt.json"
DEFAULT_OPERATOR_STATUS_WORKSPACE_DIR = DEFAULT_PRIVATE_WORKSPACE_DIR
DEFAULT_OPERATOR_PACKET_PATH = DEFAULT_OUTPUT_DIR / PACKET_JSON_NAME
ACK_CONFIRMED_REPLY = "CONFIRMED"
CHANNEL_MARKERS = (
    "channel",
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
    "채널",
    "메시지",
    "이메일",
    "메일",
)

logger = logging.getLogger(__name__)


class FirstRecipientOperatorStatusError(RuntimeError):
    """First-recipient operator status inspection failed."""


ReceiptVerifier = Callable[[Path], dict[str, Any]]


def check_first_recipient_operator_status(
    workspace_dir: Path = DEFAULT_OPERATOR_STATUS_WORKSPACE_DIR,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    operator_packet_path: Path | None = None,
    builder_gold_path_share_receipt: Path | None = None,
    receipt_path: Path | None = None,
    require_manual_send_go_rehearsal: bool = True,
) -> dict[str, Any]:
    """Inspect the first-recipient operator state without sending or leaking private data."""
    workspace_dir = workspace_dir.resolve()
    output_dir = output_dir.resolve()
    operator_packet_path = (operator_packet_path or output_dir / PACKET_JSON_NAME).resolve()
    builder_gold_path_share_receipt = (
        builder_gold_path_share_receipt.resolve() if builder_gold_path_share_receipt else None
    )

    payload = _status_payload(
        workspace_dir=workspace_dir,
        output_dir=output_dir,
        operator_packet_path=operator_packet_path,
        builder_gold_path_share_receipt=builder_gold_path_share_receipt,
        require_manual_send_go_rehearsal=require_manual_send_go_rehearsal,
    )

    receipt_path = (receipt_path or workspace_dir / OPERATOR_STATUS_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_first_recipient_operator_status_receipt_file(receipt_path)
    _assert_shareable_receipt_file(receipt_path, workspace_dir, builder_gold_path_share_receipt)

    private_runbook_path = _private_runbook_path(workspace_dir)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "private_runbook": str(private_runbook_path) if private_runbook_path.is_file() else None,
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["operator_status_receipt_body_sha256"],
        "archive_sha256": payload["release"].get("archive_sha256"),
        "next_action": payload["operator_next_action"],
    }


def verify_first_recipient_operator_status_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_operator_status_receipt_payload(payload)
    return payload


def verify_first_recipient_operator_status_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != OPERATOR_STATUS_SCHEMA_VERSION:
        raise FirstRecipientOperatorStatusError("operator status receipt schema_version mismatch.")
    if payload.get("safe_to_share") is not True:
        raise FirstRecipientOperatorStatusError("operator status receipt must be safe_to_share.")
    if payload.get("status") != "pass":
        raise FirstRecipientOperatorStatusError("operator status receipt did not pass.")
    if payload.get("verdict") not in _allowed_verdicts():
        raise FirstRecipientOperatorStatusError("operator status receipt verdict is invalid.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise FirstRecipientOperatorStatusError("operator status receipt checks failed.")
    receipt_checks = payload.get("operator_status_receipt_checks")
    recalculated = _receipt_checks(payload)
    if receipt_checks != recalculated:
        raise FirstRecipientOperatorStatusError("operator status receipt self-checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise FirstRecipientOperatorStatusError(
            "operator status receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("operator_status_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise FirstRecipientOperatorStatusError("operator status receipt body hash mismatch.")


def _status_payload(
    *,
    workspace_dir: Path,
    output_dir: Path,
    operator_packet_path: Path,
    builder_gold_path_share_receipt: Path | None,
    require_manual_send_go_rehearsal: bool,
) -> dict[str, Any]:
    workspace_exists = workspace_dir.is_dir()
    operator_packet = _load_operator_packet(operator_packet_path)
    operator_release_hash = _summary_release_hash(operator_packet)
    private_files = [
        _private_file_status(workspace_dir, spec["file"], release_archive_sha256=operator_release_hash)
        for spec in PRIVATE_FILE_SPECS
    ]
    required_private = [
        item for item in private_files if item["file"] in {"recipient-private.txt", "operator-dispatch-note-private.md"}
    ]
    ack_status = next(item for item in private_files if item["file"] == "recipient-ack-private.txt")
    private_send_requirements = _private_send_requirements(required_private)

    receipts = {
        "operator_packet": operator_packet,
        "private_workspace": _load_receipt(
            workspace_dir / PRIVATE_WORKSPACE_RECEIPT_NAME,
            lambda path: _read_json(path),
            "private_workspace_receipt_body_sha256",
        ),
        "first_recipient_workspace": _load_receipt(
            workspace_dir / FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME,
            verify_first_recipient_send_workspace_receipt_file,
            "first_recipient_send_workspace_receipt_body_sha256",
        ),
        "preflight": _load_receipt(
            workspace_dir / PREFLIGHT_RECEIPT_NAME,
            lambda path: verify_first_recipient_send_preflight_receipt_file(path, require_ready=False),
            "first_recipient_send_preflight_receipt_body_sha256",
        ),
        "manual_send_go": _load_receipt(
            workspace_dir / MANUAL_SEND_GO_RECEIPT_NAME,
            lambda path: verify_first_recipient_manual_send_go_receipt_file(path, require_go=False),
            "manual_send_go_receipt_body_sha256",
            extra_summary=_manual_send_go_operator_packet_summary,
        ),
        "pre_send_sequence": _load_receipt(
            workspace_dir / PRE_SEND_SEQUENCE_RECEIPT_NAME,
            lambda path: verify_first_recipient_pre_send_sequence_receipt_file(path, require_ready=False),
            "pre_send_sequence_receipt_body_sha256",
        ),
        "post_send_sequence": _load_receipt(
            workspace_dir / POST_SEND_SEQUENCE_RECEIPT_NAME,
            lambda path: verify_first_recipient_post_send_sequence_receipt_file(path, require_recorded=False),
            "post_send_sequence_receipt_body_sha256",
        ),
    }
    final_audit = _final_audit_summary(
        output_dir,
        require_manual_send_go_rehearsal=require_manual_send_go_rehearsal,
    )
    builder_receipt = _builder_receipt_summary(builder_gold_path_share_receipt)
    archive_sha256 = _first_hash(
        _summary_release_hash(final_audit),
        _summary_release_hash(receipts["operator_packet"]),
        _summary_release_hash(receipts["post_send_sequence"]),
        _summary_release_hash(receipts["pre_send_sequence"]),
        _summary_release_hash(receipts["manual_send_go"]),
    )
    verdict = _operator_stage(
        workspace_exists=workspace_exists,
        operator_packet=receipts["operator_packet"],
        first_recipient_workspace=receipts["first_recipient_workspace"],
        final_audit=final_audit,
        archive_sha256=archive_sha256,
        required_private=required_private,
        private_send_requirements=private_send_requirements,
        ack_status=ack_status,
        builder_receipt=builder_receipt,
        pre_send_sequence=receipts["pre_send_sequence"],
        manual_send_go=receipts["manual_send_go"],
        post_send_sequence=receipts["post_send_sequence"],
    )
    next_action = _next_action(verdict, archive_sha256=archive_sha256)
    operator_safe_checklist = _operator_safe_checklist(
        workspace_exists=workspace_exists,
        operator_packet=receipts["operator_packet"],
        first_recipient_workspace=receipts["first_recipient_workspace"],
        final_audit=final_audit,
        archive_sha256=archive_sha256,
        private_send_requirements=private_send_requirements,
        ack_status=ack_status,
        builder_receipt=builder_receipt,
        pre_send_sequence=receipts["pre_send_sequence"],
        manual_send_go=receipts["manual_send_go"],
        post_send_sequence=receipts["post_send_sequence"],
    )
    file_count = _first_value(
        _summary_file_count(final_audit),
        _summary_file_count(receipts["operator_packet"]),
        _summary_file_count(receipts["post_send_sequence"]),
        _summary_file_count(receipts["pre_send_sequence"]),
    )
    operator_launch_snapshot = _operator_launch_snapshot(
        verdict=verdict,
        archive_sha256=archive_sha256,
        final_audit=final_audit,
        private_send_requirements=private_send_requirements,
        operator_safe_checklist=operator_safe_checklist,
        next_action=next_action,
    )
    checks = {
        "stage_valid": verdict in _allowed_verdicts(),
        "next_action_present": isinstance(next_action, str) and bool(next_action),
        "private_file_statuses_controlled": all(
            item["status"] in {"ready", "missing", "empty", "placeholder", "unreadable", "unconfirmed"}
            for item in private_files
        ),
        "private_file_hashes_not_included": all("sha256" not in item for item in private_files),
        "private_send_requirements_controlled": all(
            isinstance(value, bool) for value in private_send_requirements.values()
        ),
        "operator_safe_checklist_controlled": _safe_checklist_controlled(operator_safe_checklist),
        "operator_launch_snapshot_controlled": _operator_launch_snapshot_controlled(operator_launch_snapshot),
        "operator_packet_status_controlled": receipts["operator_packet"]["status"]
        in {"pass", "missing", "missing_or_invalid"},
        "final_audit_status_controlled": final_audit["status"] in {"pass", "missing_or_invalid"},
        "final_audit_summary_controlled": _final_audit_summary_controlled(final_audit),
        "builder_receipt_status_controlled": builder_receipt["status"] in {"not_provided", "pass", "missing_or_invalid"},
        "manual_dispatch_only": True,
        "one_recipient_policy_locked": True,
        "script_does_not_send_to_recipient": True,
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
    }
    payload: dict[str, Any] = {
        "schema_version": OPERATOR_STATUS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": verdict,
        "safe_to_share": True,
        "release": {
            "zip_file": RELEASE_SLUG + ".zip",
            "archive_sha256": archive_sha256,
            "file_count": file_count,
        },
        "workspace": {
            "name": "external-alpha-first-pilot",
            "exists": workspace_exists,
            "local_path_included": False,
        },
        "private_file_summary": [_safe_private_file_summary(item) for item in private_files],
        "private_send_requirements": private_send_requirements,
        "operator_safe_checklist": operator_safe_checklist,
        "operator_launch_snapshot": operator_launch_snapshot,
        "gate_receipts": receipts,
        "final_send_chain_audit": final_audit,
        "builder_gold_path_share_receipt": builder_receipt,
        "operator_next_action": next_action,
        "policy": {
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "script_sends_to_recipient": False,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
            "status_only": True,
        },
        "checks": checks,
    }
    payload["operator_status_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["operator_status_receipt_checks"] = _receipt_checks(payload)
    return payload


def _operator_stage(
    *,
    workspace_exists: bool,
    operator_packet: dict[str, Any],
    first_recipient_workspace: dict[str, Any],
    final_audit: dict[str, Any],
    archive_sha256: str | None,
    required_private: list[dict[str, Any]],
    private_send_requirements: dict[str, bool],
    ack_status: dict[str, Any],
    builder_receipt: dict[str, Any],
    pre_send_sequence: dict[str, Any],
    manual_send_go: dict[str, Any],
    post_send_sequence: dict[str, Any],
) -> str:
    if operator_packet["status"] != "pass":
        return "PREPARE_OPERATOR_PACKET"
    if not workspace_exists:
        return "PREPARE_PRIVATE_WORKSPACE"
    if not _first_recipient_workspace_ready(first_recipient_workspace, archive_sha256):
        return "PREPARE_PRIVATE_WORKSPACE"

    post_verdict = post_send_sequence.get("verdict")
    sent_or_checkpoint_recorded = post_send_sequence["status"] == "pass" and post_verdict in {
        "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT",
        "RECIPIENT_CHECKPOINT_RECORDED",
        "RECIPIENT_GOLD_PATH_CONFIRMED",
    }
    if post_send_sequence["status"] == "pass" and post_verdict == "RECIPIENT_GOLD_PATH_CONFIRMED":
        return "RECIPIENT_GOLD_PATH_CONFIRMED"
    if (
        sent_or_checkpoint_recorded
        and ack_status["status"] == "ready"
        and builder_receipt["status"] == "pass"
        and post_verdict != "RECIPIENT_GOLD_PATH_CONFIRMED"
    ):
        return "RUN_POST_SEND_SEQUENCE_WITH_GOLD_PATH"
    if ack_status["status"] == "ready" and post_verdict == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT":
        return "RUN_POST_SEND_SEQUENCE_WITH_ACK"
    if post_send_sequence["status"] == "pass" and post_verdict == "RECIPIENT_CHECKPOINT_RECORDED":
        return "RECIPIENT_CHECKPOINT_RECORDED"
    if post_send_sequence["status"] == "pass" and post_verdict == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT":
        return "WAITING_FOR_RECIPIENT_ACK"

    if any(item["status"] != "ready" for item in required_private) or not all(private_send_requirements.values()):
        return "FILL_PRIVATE_FIELDS"
    if final_audit["status"] != "pass":
        return "CHECK_RELEASE_CHAIN"
    if _pre_send_sequence_ready(
        pre_send_sequence,
        manual_send_go,
        archive_sha256,
        operator_packet.get("body_sha256"),
    ):
        return "READY_TO_MANUALLY_SEND_ONE"
    return "RUN_PRE_SEND_SEQUENCE"


def _next_action(verdict: str, *, archive_sha256: str | None = None) -> str:
    archive_hint = (
        f"release ZIP sha256 {archive_sha256}"
        if isinstance(archive_sha256, str) and _looks_like_sha256(archive_sha256)
        else "the exact release ZIP sha256"
    )
    actions = {
        "PREPARE_OPERATOR_PACKET": "Run python scripts/prepare_external_alpha_operator_dispatch_packet.py.",
        "PREPARE_PRIVATE_WORKSPACE": (
            "Run python scripts/prepare_external_alpha_first_recipient_send_workspace.py "
            "--workspace-dir <private-workspace-dir>."
        ),
        "FILL_PRIVATE_FIELDS": (
            "Fill recipient-private.txt with exactly one non-empty recipient contact, then make "
            f"operator-dispatch-note-private.md name the private send channel and include {archive_hint} "
            "before running the pre-send sequence."
        ),
        "CHECK_RELEASE_CHAIN": (
            "Run python scripts/audit_external_alpha_send_chain.py and fix the named blocked gate before any send."
        ),
        "RUN_PRE_SEND_SEQUENCE": "Run python scripts/check_external_alpha_first_recipient_pre_send_sequence.py.",
        "READY_TO_MANUALLY_SEND_ONE": (
            "Manually send exactly one ZIP using the operator packet, then record post-send with sent_at_utc."
        ),
        "WAITING_FOR_RECIPIENT_ACK": (
            "Wait for exactly one CONFIRMED recipient acknowledgement, store it in recipient-ack-private.txt, then rerun status."
        ),
        "RUN_POST_SEND_SEQUENCE_WITH_ACK": (
            "Run python scripts/check_external_alpha_first_recipient_post_send_sequence.py with the same sent_at_utc."
        ),
        "RUN_POST_SEND_SEQUENCE_WITH_GOLD_PATH": (
            "Run the post-send sequence with --builder-gold-path-share-receipt to confirm the gold path."
        ),
        "RECIPIENT_CHECKPOINT_RECORDED": (
            "Collect the builder gold path share receipt or private feedback before any next recipient."
        ),
        "RECIPIENT_GOLD_PATH_CONFIRMED": (
            "Collect controlled pilot feedback, decide fix/continue/stop, and do not send to another recipient yet."
        ),
    }
    return actions[verdict]


def _open_operator_gates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    checklist = payload.get("operator_safe_checklist")
    if not isinstance(checklist, list):
        return []
    relevant_ids = set(_relevant_open_gate_ids(str(payload.get("verdict")), checklist))
    if not relevant_ids:
        return []
    return [
        item
        for item in checklist
        if isinstance(item, dict) and item.get("id") in relevant_ids and item.get("done") is not True
    ]


def _relevant_open_gate_ids(verdict: str, checklist: list[dict[str, Any]]) -> list[str]:
    relevant_ids_by_verdict = {
        "PREPARE_OPERATOR_PACKET": {"operator_packet_ready"},
        "PREPARE_PRIVATE_WORKSPACE": {"private_workspace_ready", "first_recipient_workspace_ready"},
        "FILL_PRIVATE_FIELDS": {
            "recipient_private_ready",
            "operator_note_names_channel",
            "operator_note_confirms_release_hash",
        },
        "CHECK_RELEASE_CHAIN": {"final_send_chain_ready"},
        "RUN_PRE_SEND_SEQUENCE": {"pre_send_sequence_ready", "manual_send_go_operator_packet_bound"},
        "READY_TO_MANUALLY_SEND_ONE": {"manual_send_recorded"},
        "WAITING_FOR_RECIPIENT_ACK": {"recipient_ack_ready"},
        "RUN_POST_SEND_SEQUENCE_WITH_ACK": set(),
        "RUN_POST_SEND_SEQUENCE_WITH_GOLD_PATH": set(),
        "RECIPIENT_CHECKPOINT_RECORDED": {"builder_gold_path_receipt_ready"},
        "RECIPIENT_GOLD_PATH_CONFIRMED": set(),
    }
    relevant_ids = relevant_ids_by_verdict.get(verdict, set())
    if not relevant_ids or not isinstance(checklist, list):
        return []
    return sorted(
        str(item["id"])
        for item in checklist
        if isinstance(item, dict) and item.get("id") in relevant_ids and item.get("done") is not True
    )


def _operator_launch_snapshot(
    *,
    verdict: str,
    archive_sha256: str | None,
    final_audit: dict[str, Any],
    private_send_requirements: dict[str, bool],
    operator_safe_checklist: list[dict[str, Any]],
    next_action: str,
) -> dict[str, Any]:
    pre_send_sequence_ready = _checklist_done(operator_safe_checklist, "pre_send_sequence_ready")
    final_send_chain_ready = final_audit.get("status") == "pass" and final_audit.get("verdict") == "READY_TO_SEND_ONE"
    private_fields_ready = all(private_send_requirements.values())
    manual_send_allowed = (
        verdict == "READY_TO_MANUALLY_SEND_ONE"
        and final_send_chain_ready
        and private_fields_ready
        and pre_send_sequence_ready
    )
    return {
        "stage": verdict,
        "send_state": "MANUAL_SEND_ALLOWED_ONE" if manual_send_allowed else "BLOCKED",
        "manual_send_allowed": manual_send_allowed,
        "manual_operator_dispatch_required": True,
        "script_sends_to_recipient": False,
        "max_recipients": 1,
        "release_archive_sha256": archive_sha256,
        "final_send_chain_ready": final_send_chain_ready,
        "private_fields_ready": private_fields_ready,
        "pre_send_sequence_ready": pre_send_sequence_ready,
        "open_gate_ids": _relevant_open_gate_ids(verdict, operator_safe_checklist),
        "next_safe_action": next_action,
        "safe_to_share": True,
    }


def _checklist_done(checklist: list[dict[str, Any]], item_id: str) -> bool:
    return any(isinstance(item, dict) and item.get("id") == item_id and item.get("done") is True for item in checklist)


def _operator_launch_snapshot_controlled(snapshot: dict[str, Any]) -> bool:
    open_gate_ids = snapshot.get("open_gate_ids")
    allowed_gate_ids = {
        "operator_packet_ready",
        "private_workspace_ready",
        "first_recipient_workspace_ready",
        "final_send_chain_ready",
        "recipient_private_ready",
        "operator_note_names_channel",
        "operator_note_confirms_release_hash",
        "pre_send_sequence_ready",
        "manual_send_go_operator_packet_bound",
        "manual_send_recorded",
        "recipient_ack_ready",
        "builder_gold_path_receipt_ready",
    }
    return (
        snapshot.get("stage") in _allowed_verdicts()
        and snapshot.get("send_state") in {"BLOCKED", "MANUAL_SEND_ALLOWED_ONE"}
        and isinstance(snapshot.get("manual_send_allowed"), bool)
        and snapshot.get("manual_operator_dispatch_required") is True
        and snapshot.get("script_sends_to_recipient") is False
        and snapshot.get("max_recipients") == 1
        and (snapshot.get("release_archive_sha256") is None or _looks_like_sha256(snapshot.get("release_archive_sha256")))
        and isinstance(snapshot.get("final_send_chain_ready"), bool)
        and isinstance(snapshot.get("private_fields_ready"), bool)
        and isinstance(snapshot.get("pre_send_sequence_ready"), bool)
        and isinstance(open_gate_ids, list)
        and all(item in allowed_gate_ids for item in open_gate_ids)
        and isinstance(snapshot.get("next_safe_action"), str)
        and bool(snapshot.get("next_safe_action"))
        and snapshot.get("safe_to_share") is True
    )


def _private_status_line_for_verdict(payload: dict[str, Any]) -> str | None:
    private_files = payload.get("private_file_summary")
    if not isinstance(private_files, list):
        return None
    by_file = {item.get("file"): item for item in private_files if isinstance(item, dict)}
    verdict = payload.get("verdict")
    if verdict == "FILL_PRIVATE_FIELDS":
        selected = [
            by_file.get("recipient-private.txt"),
            by_file.get("operator-dispatch-note-private.md"),
        ]
    elif verdict in {"WAITING_FOR_RECIPIENT_ACK", "RUN_POST_SEND_SEQUENCE_WITH_ACK"}:
        selected = [by_file.get("recipient-ack-private.txt")]
    else:
        selected = []
    parts = [_format_private_file_status(item) for item in selected if isinstance(item, dict)]
    return ", ".join(part for part in parts if part) or None


def _format_private_file_status(item: dict[str, Any]) -> str:
    status = item.get("status")
    filename = item.get("file")
    if not isinstance(filename, str) or not isinstance(status, str):
        return ""
    details: list[str] = []
    if filename == "recipient-ack-private.txt" and status in {"ready", "unconfirmed"}:
        details.append(f"confirmed_reply={str(item.get('confirmed_reply_present') is True).lower()}")
        details.append(f"exactly_one_acknowledgement={str(item.get('exactly_one_acknowledgement') is True).lower()}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"{filename}={status}{suffix}"


def _log_operator_status_details(payload: dict[str, Any]) -> None:
    launch_snapshot = payload.get("operator_launch_snapshot")
    if isinstance(launch_snapshot, dict):
        logger.info("send   : %s", launch_snapshot.get("send_state"))
    private_status = _private_status_line_for_verdict(payload)
    if private_status:
        logger.info("private: %s", private_status)
    final_audit_status = _final_audit_status_line_for_verdict(payload)
    if final_audit_status:
        logger.info("%s", final_audit_status)
    open_gates = _open_operator_gates(payload)
    if open_gates:
        logger.info("open gates:")
        for item in open_gates:
            logger.info("- %s: %s", item["id"], item["safe_next_action"])


def _final_audit_status_line_for_verdict(payload: dict[str, Any]) -> str | None:
    if payload.get("verdict") != "CHECK_RELEASE_CHAIN":
        return None
    final_audit = _dict(payload, "final_send_chain_audit")
    failed_checks = final_audit.get("failed_checks")
    if isinstance(failed_checks, list) and failed_checks:
        return "final audit blocked checks: " + ", ".join(str(item) for item in failed_checks)
    error_code = final_audit.get("error_code")
    if isinstance(error_code, str) and error_code:
        return f"final audit blocked: {error_code}"
    return "final audit blocked: missing_or_invalid"


def _private_runbook_path(workspace_dir: Path) -> Path:
    return workspace_dir / PRIVATE_SEND_RUNBOOK_NAME


def _load_operator_packet(path: Path) -> dict[str, Any]:
    return _load_receipt(path, verify_operator_dispatch_packet_file, "operator_dispatch_packet_body_sha256")


ExtraReceiptSummary = Callable[[dict[str, Any]], dict[str, Any]]


def _load_receipt(
    path: Path,
    verifier: ReceiptVerifier,
    body_key: str,
    *,
    extra_summary: ExtraReceiptSummary | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "file": path.name,
            "present": False,
            "status": "missing",
            "verdict": "missing",
            "body_sha256": None,
            "release_archive_sha256": None,
            "file_count": None,
        }
    try:
        payload = verifier(path)
    except Exception as exc:  # noqa: BLE001 - status receipt carries only the error class.
        return {
            "file": path.name,
            "present": True,
            "status": "missing_or_invalid",
            "verdict": "missing_or_invalid",
            "body_sha256": None,
            "release_archive_sha256": None,
            "file_count": None,
            "error_code": exc.__class__.__name__,
        }
    release = _dict(payload, "release")
    if not release:
        release = _dict(payload, "release_bundle")
    summary = {
        "file": path.name,
        "present": True,
        "status": payload.get("status") if isinstance(payload.get("status"), str) else "pass",
        "verdict": payload.get("verdict") if isinstance(payload.get("verdict"), str) else "verified",
        "body_sha256": payload.get(body_key) if isinstance(payload.get(body_key), str) else None,
        "release_archive_sha256": release.get("archive_sha256"),
        "file_count": release.get("file_count"),
    }
    if extra_summary is not None:
        summary.update(extra_summary(payload))
    return summary


def _manual_send_go_operator_packet_summary(payload: dict[str, Any]) -> dict[str, Any]:
    operator_packet = _dict(payload, "operator_packet")
    return {
        "operator_packet": {
            "file": operator_packet.get("file") if isinstance(operator_packet.get("file"), str) else None,
            "body_sha256": operator_packet.get("body_sha256")
            if _looks_like_sha256(operator_packet.get("body_sha256"))
            else None,
            "preflight_body_sha256": operator_packet.get("preflight_body_sha256")
            if _looks_like_sha256(operator_packet.get("preflight_body_sha256"))
            else None,
        }
    }


def _final_audit_summary(output_dir: Path, *, require_manual_send_go_rehearsal: bool = True) -> dict[str, Any]:
    try:
        payload = audit_send_chain(
            output_dir,
            require_manual_send_go_rehearsal=require_manual_send_go_rehearsal,
        )
    except Exception as exc:  # noqa: BLE001
        failed_checks = _extract_final_audit_failed_checks(exc)
        return {
            "status": "missing_or_invalid",
            "verdict": "missing_or_invalid",
            "archive_sha256": None,
            "file_count": None,
            "receipt_body_sha256": None,
            "bundle_smoke_receipt_body_sha256": None,
            "operator_send_bypass_audit_body_sha256": None,
            "chain_depth": 0,
            "error_code": exc.__class__.__name__,
            "failure_summary": "failed_checks" if failed_checks else "verification_error",
            "failed_checks": failed_checks,
            "manual_send_go_rehearsal_required": require_manual_send_go_rehearsal,
        }
    return {
        "status": payload.get("status"),
        "verdict": payload.get("verdict"),
        "archive_sha256": payload.get("archive_sha256"),
        "file_count": payload.get("file_count"),
        "receipt_body_sha256": payload.get("receipt_body_sha256"),
        "bundle_smoke_receipt_body_sha256": payload.get("bundle_smoke_receipt_body_sha256"),
        "operator_send_bypass_audit_body_sha256": payload.get("operator_send_bypass_audit_body_sha256"),
        "chain_depth": _final_chain_depth(payload),
        "failure_summary": "none",
        "failed_checks": [],
        "manual_send_go_rehearsal_required": payload.get("manual_send_go_rehearsal_required"),
    }


def _extract_final_audit_failed_checks(exc: Exception) -> list[str]:
    prefix = "final send-chain audit failed: "
    text = str(exc)
    if not text.startswith(prefix):
        return []
    failed_checks = [item.strip() for item in text[len(prefix) :].split(",")]
    return [item for item in failed_checks if _safe_identifier(item)]


def _final_audit_summary_controlled(summary: dict[str, Any]) -> bool:
    failed_checks = summary.get("failed_checks")
    failure_summary = summary.get("failure_summary")
    error_code = summary.get("error_code")
    return (
        isinstance(failed_checks, list)
        and all(_safe_identifier(item) for item in failed_checks)
        and failure_summary in {"none", "failed_checks", "verification_error"}
        and (error_code is None or _safe_identifier(error_code))
        and isinstance(summary.get("manual_send_go_rehearsal_required"), bool)
    )


def _final_chain_depth(payload: dict[str, Any]) -> int:
    value = payload.get("final_chain_depth")
    if isinstance(value, int):
        return value
    chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    return len(chain)


def _builder_receipt_summary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"file": BUILDER_GOLD_PATH_RECEIPT_NAME, "provided": False, "status": "not_provided", "sha256_present": False}
    if not path.is_file():
        return {
            "file": path.name,
            "provided": True,
            "status": "missing_or_invalid",
            "sha256_present": False,
            "error_code": "FileNotFoundError",
        }
    try:
        payload = _read_json(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "file": path.name,
            "provided": True,
            "status": "missing_or_invalid",
            "sha256_present": False,
            "error_code": exc.__class__.__name__,
        }
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    ready = (
        payload.get("schema_version") == "external_alpha_builder_gold_path_share_receipt_v0_1"
        and payload.get("safe_to_share") is True
        and bool(checks)
        and all(value is True for value in checks.values())
    )
    return {
        "file": path.name,
        "provided": True,
        "status": "pass" if ready else "missing_or_invalid",
        "sha256_present": ready,
    }


def _private_file_status(workspace_dir: Path, filename: str, *, release_archive_sha256: str | None) -> dict[str, Any]:
    path = workspace_dir / filename
    if not path.is_file():
        return _private_status(filename, "missing")
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return _private_status(filename, "unreadable")
    stripped = text.strip()
    if not stripped:
        return _private_status(filename, "empty")
    if _is_placeholder(filename, text):
        return _private_status(filename, "placeholder")
    if filename == "recipient-private.txt":
        nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(nonempty_lines) == 1 and not _recipient_value_is_real(nonempty_lines[0]):
            return _private_status(filename, "placeholder")
    result = {"file": filename, "status": "ready", "sha256_present": True}
    if filename == "recipient-private.txt":
        result["minimum_signal_present"] = len(data) >= 8
        result["exactly_one_recipient"] = _nonempty_line_count(text) == 1
    if filename == "operator-dispatch-note-private.md":
        result["mentions_channel"] = _operator_note_mentions_private_channel(text)
        result["contains_release_hash"] = _looks_like_sha256(release_archive_sha256) and str(
            release_archive_sha256
        ) in text
    if filename == "recipient-ack-private.txt":
        result["confirmed_reply_present"] = _is_confirmed_ack(stripped)
        result["exactly_one_acknowledgement"] = _nonempty_line_count(text) == 1
        if result["confirmed_reply_present"] is not True or result["exactly_one_acknowledgement"] is not True:
            result["status"] = "unconfirmed"
            result["sha256_present"] = False
    return result


def _nonempty_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _is_confirmed_ack(text: str) -> bool:
    return text.strip().upper() == ACK_CONFIRMED_REPLY


def _private_status(filename: str, status: str) -> dict[str, Any]:
    return {"file": filename, "status": status, "sha256_present": False}


def _safe_private_file_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "file": item["file"],
        "status": item["status"],
        "sha256_present": item["sha256_present"],
    }
    if item.get("file") == "recipient-ack-private.txt" and item.get("status") in {"ready", "unconfirmed"}:
        summary["confirmed_reply_present"] = item.get("confirmed_reply_present") is True
        summary["exactly_one_acknowledgement"] = item.get("exactly_one_acknowledgement") is True
    return summary


def _private_send_requirements(required_private: list[dict[str, Any]]) -> dict[str, bool]:
    by_name = {item.get("file"): item for item in required_private if isinstance(item.get("file"), str)}
    recipient = by_name.get("recipient-private.txt", {})
    operator_note = by_name.get("operator-dispatch-note-private.md", {})
    return {
        "recipient_private_ready": recipient.get("status") == "ready",
        "recipient_private_minimum_signal": recipient.get("minimum_signal_present") is True,
        "recipient_private_exactly_one_contact": recipient.get("exactly_one_recipient") is True,
        "operator_dispatch_note_ready": operator_note.get("status") == "ready",
        "operator_dispatch_note_mentions_channel": operator_note.get("mentions_channel") is True,
        "operator_dispatch_note_confirms_release_hash": operator_note.get("contains_release_hash") is True,
    }


def _operator_safe_checklist(
    *,
    workspace_exists: bool,
    operator_packet: dict[str, Any],
    first_recipient_workspace: dict[str, Any],
    final_audit: dict[str, Any],
    archive_sha256: str | None,
    private_send_requirements: dict[str, bool],
    ack_status: dict[str, Any],
    builder_receipt: dict[str, Any],
    pre_send_sequence: dict[str, Any],
    manual_send_go: dict[str, Any],
    post_send_sequence: dict[str, Any],
) -> list[dict[str, Any]]:
    manual_send_go_operator_packet_bound = _manual_send_go_operator_packet_bound(
        manual_send_go,
        operator_packet.get("body_sha256"),
    )
    pre_send_ready = _pre_send_sequence_ready(
        pre_send_sequence,
        manual_send_go,
        archive_sha256,
        operator_packet.get("body_sha256"),
    )
    post_verdict = post_send_sequence.get("verdict")
    manual_send_recorded = post_send_sequence.get("status") == "pass" and post_verdict in {
        "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT",
        "RECIPIENT_CHECKPOINT_RECORDED",
        "RECIPIENT_GOLD_PATH_CONFIRMED",
    }
    return [
        {
            "id": "operator_packet_ready",
            "stage": "setup",
            "done": operator_packet.get("status") == "pass",
            "safe_next_action": "Run prepare_external_alpha_operator_dispatch_packet.py.",
        },
        {
            "id": "private_workspace_ready",
            "stage": "setup",
            "done": workspace_exists,
            "safe_next_action": "Run prepare_external_alpha_first_recipient_send_workspace.py.",
        },
        {
            "id": "first_recipient_workspace_ready",
            "stage": "setup",
            "done": _first_recipient_workspace_ready(first_recipient_workspace, archive_sha256),
            "safe_next_action": (
                "Run prepare_external_alpha_first_recipient_send_workspace.py to refresh the private runbook "
                "for the current release ZIP."
            ),
        },
        {
            "id": "final_send_chain_ready",
            "stage": "before_manual_send",
            "done": final_audit.get("status") == "pass" and final_audit.get("verdict") == "READY_TO_SEND_ONE",
            "safe_next_action": (
                "Run audit_external_alpha_send_chain.py until READY_TO_SEND_ONE; rebuild release artifacts if "
                "release_sources_match_current_manifest is blocked."
            ),
        },
        {
            "id": "recipient_private_ready",
            "stage": "before_manual_send",
            "done": private_send_requirements.get("recipient_private_ready") is True
            and private_send_requirements.get("recipient_private_minimum_signal") is True
            and private_send_requirements.get("recipient_private_exactly_one_contact") is True,
            "safe_next_action": "Replace recipient-private.txt placeholder with exactly one recipient contact.",
        },
        {
            "id": "operator_note_names_channel",
            "stage": "before_manual_send",
            "done": private_send_requirements.get("operator_dispatch_note_mentions_channel") is True,
            "safe_next_action": "Make operator-dispatch-note-private.md name the private send channel.",
        },
        {
            "id": "operator_note_confirms_release_hash",
            "stage": "before_manual_send",
            "done": private_send_requirements.get("operator_dispatch_note_confirms_release_hash") is True,
            "safe_next_action": _operator_note_release_hash_action(archive_sha256),
        },
        {
            "id": "pre_send_sequence_ready",
            "stage": "before_manual_send",
            "done": pre_send_ready,
            "safe_next_action": "Run check_external_alpha_first_recipient_pre_send_sequence.py.",
        },
        {
            "id": "manual_send_go_operator_packet_bound",
            "stage": "before_manual_send",
            "done": manual_send_go_operator_packet_bound,
            "safe_next_action": (
                "Rerun check_external_alpha_first_recipient_pre_send_sequence.py with the current operator packet."
            ),
        },
        {
            "id": "manual_send_recorded",
            "stage": "after_manual_send",
            "done": manual_send_recorded,
            "safe_next_action": "After one manual send, run check_external_alpha_first_recipient_post_send_sequence.py.",
        },
        {
            "id": "recipient_ack_ready",
            "stage": "after_manual_send",
            "done": ack_status.get("status") == "ready",
            "safe_next_action": "Store exactly one CONFIRMED acknowledgement in recipient-ack-private.txt.",
        },
        {
            "id": "builder_gold_path_receipt_ready",
            "stage": "after_manual_send",
            "done": builder_receipt.get("status") == "pass",
            "safe_next_action": "Attach the safe builder gold path share receipt when the recipient completes it.",
        },
    ]


def _operator_note_release_hash_action(archive_sha256: str | None) -> str:
    if isinstance(archive_sha256, str) and _looks_like_sha256(archive_sha256):
        return f"Make operator-dispatch-note-private.md include release ZIP sha256 {archive_sha256}."
    return "Make operator-dispatch-note-private.md include the exact release ZIP sha256."


def _safe_checklist_controlled(checklist: list[dict[str, Any]]) -> bool:
    allowed_ids = {
        "operator_packet_ready",
        "private_workspace_ready",
        "first_recipient_workspace_ready",
        "final_send_chain_ready",
        "recipient_private_ready",
        "operator_note_names_channel",
        "operator_note_confirms_release_hash",
        "pre_send_sequence_ready",
        "manual_send_go_operator_packet_bound",
        "manual_send_recorded",
        "recipient_ack_ready",
        "builder_gold_path_receipt_ready",
    }
    return bool(checklist) and all(
        isinstance(item, dict)
        and item.get("id") in allowed_ids
        and item.get("stage") in {"setup", "before_manual_send", "after_manual_send"}
        and isinstance(item.get("done"), bool)
        and isinstance(item.get("safe_next_action"), str)
        and bool(item.get("safe_next_action"))
        for item in checklist
    )


def _first_recipient_workspace_ready(summary: dict[str, Any], archive_sha256: str | None) -> bool:
    return (
        summary.get("status") == "pass"
        and summary.get("verdict") == "FIRST_RECIPIENT_SEND_WORKSPACE_READY"
        and _looks_like_sha256(archive_sha256)
        and summary.get("release_archive_sha256") == archive_sha256
    )


def _pre_send_sequence_ready(
    pre_send_sequence: dict[str, Any],
    manual_send_go: dict[str, Any],
    archive_sha256: str | None,
    operator_packet_body_sha256: str | None,
) -> bool:
    manual_send_go_bound = _manual_send_go_operator_packet_bound(manual_send_go, operator_packet_body_sha256)
    return (
        manual_send_go_bound
        and _current_release_receipt_ready(
            pre_send_sequence,
            archive_sha256,
            "READY_TO_MANUALLY_SEND_ONE",
        )
    ) or (
        manual_send_go_bound
        and _current_release_receipt_ready(
            manual_send_go,
            archive_sha256,
            "GO_TO_MANUALLY_SEND_ONE",
        )
    )


def _manual_send_go_operator_packet_bound(
    manual_send_go: dict[str, Any],
    operator_packet_body_sha256: str | None,
) -> bool:
    operator_packet = _dict(manual_send_go, "operator_packet")
    return (
        _looks_like_sha256(operator_packet_body_sha256)
        and manual_send_go.get("status") == "pass"
        and manual_send_go.get("verdict") == "GO_TO_MANUALLY_SEND_ONE"
        and operator_packet.get("file") == PACKET_JSON_NAME
        and operator_packet.get("body_sha256") == operator_packet_body_sha256
        and operator_packet.get("preflight_body_sha256") == operator_packet_body_sha256
    )


def _current_release_receipt_ready(
    summary: dict[str, Any],
    archive_sha256: str | None,
    expected_verdict: str,
) -> bool:
    return (
        summary.get("status") == "pass"
        and summary.get("verdict") == expected_verdict
        and _looks_like_sha256(archive_sha256)
        and summary.get("release_archive_sha256") == archive_sha256
    )


def _is_placeholder(filename: str, text: str) -> bool:
    fragments = {
        "recipient-private.txt": ("Recipient identifier/contact goes here",),
        "operator-dispatch-note-private.md": ("Record the private channel", "<private-send-channel>"),
        "recipient-ack-private.txt": ("Paste only the private acknowledgement", "Paste only CONFIRMED"),
        "pilot-feedback-private.md": ("Keep raw feedback here",),
        "pilot-issue-intake-private.md": ("Keep raw issue intake here",),
        "operator-decision-note-private.md": ("Write the private decision rationale",),
    }
    return any(fragment in text for fragment in fragments.get(filename, ()))


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    private_files = payload.get("private_file_summary") if isinstance(payload.get("private_file_summary"), list) else []
    private_send_requirements = (
        payload.get("private_send_requirements")
        if isinstance(payload.get("private_send_requirements"), dict)
        else {}
    )
    operator_safe_checklist = (
        payload.get("operator_safe_checklist")
        if isinstance(payload.get("operator_safe_checklist"), list)
        else []
    )
    operator_launch_snapshot = (
        payload.get("operator_launch_snapshot")
        if isinstance(payload.get("operator_launch_snapshot"), dict)
        else {}
    )
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    body_hash = payload.get("operator_status_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == OPERATOR_STATUS_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_valid": payload.get("verdict") in _allowed_verdicts(),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and bool(payload.get("operator_next_action")),
        "private_file_statuses_controlled": bool(private_files)
        and all(
            isinstance(item, dict)
            and item.get("file") in {spec["file"] for spec in PRIVATE_FILE_SPECS}
            and item.get("status") in {"ready", "missing", "empty", "placeholder", "unreadable", "unconfirmed"}
            and isinstance(item.get("sha256_present"), bool)
            and "sha256" not in item
            for item in private_files
        ),
        "private_send_requirements_controlled": set(private_send_requirements) == {
            "recipient_private_ready",
            "recipient_private_minimum_signal",
            "recipient_private_exactly_one_contact",
            "operator_dispatch_note_ready",
            "operator_dispatch_note_mentions_channel",
            "operator_dispatch_note_confirms_release_hash",
        }
        and all(isinstance(value, bool) for value in private_send_requirements.values()),
        "operator_safe_checklist_controlled": _safe_checklist_controlled(operator_safe_checklist),
        "operator_launch_snapshot_controlled": _operator_launch_snapshot_controlled(operator_launch_snapshot),
        "final_audit_summary_controlled": _final_audit_summary_controlled(_dict(payload, "final_send_chain_audit")),
        "policy_manual_only": _dict(payload, "policy").get("manual_operator_dispatch_required") is True
        and _dict(payload, "policy").get("script_sends_to_recipient") is False,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "raw_private_values_omitted": _dict(payload, "policy").get("raw_private_values_in_receipt") is False
        and "Recipient identifier/contact goes here" not in serialized
        and "Record the private channel" not in serialized
        and "<private-send-channel>" not in serialized
        and "Paste only the private acknowledgement" not in serialized
        and "Paste only CONFIRMED" not in serialized,
        "local_paths_omitted": _dict(payload, "policy").get("local_paths_in_receipt") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _assert_shareable_receipt_file(
    path: Path,
    workspace_dir: Path,
    builder_gold_path_share_receipt: Path | None,
) -> None:
    text = path.read_text(encoding="utf-8")
    private_values = [_read_text_if_exists(workspace_dir / spec["file"]) for spec in PRIVATE_FILE_SPECS]
    forbidden = [
        str(ROOT),
        str(Path.home()),
        str(workspace_dir),
        str(builder_gold_path_share_receipt.resolve()) if builder_gold_path_share_receipt else "",
        "Recipient identifier/contact goes here",
        "Record the private channel",
        "<private-send-channel>",
        "Paste only the private acknowledgement",
        "Paste only CONFIRMED",
        "Keep raw feedback here",
        "Keep raw issue intake here",
        "Write the private decision rationale",
        *[value for value in private_values if value],
    ]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise FirstRecipientOperatorStatusError("operator status receipt leaked local path or raw private text.")


def _summary_release_hash(summary: dict[str, Any]) -> str | None:
    for key in ("archive_sha256", "release_archive_sha256"):
        value = summary.get(key)
        if _looks_like_sha256(value):
            return value
    return None


def _summary_file_count(summary: dict[str, Any]) -> Any:
    return summary.get("file_count")


def _first_hash(*values: Any) -> str | None:
    for value in values:
        if _looks_like_sha256(value):
            return value
    return None


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _allowed_verdicts() -> set[str]:
    return {
        "PREPARE_OPERATOR_PACKET",
        "PREPARE_PRIVATE_WORKSPACE",
        "FILL_PRIVATE_FIELDS",
        "CHECK_RELEASE_CHAIN",
        "RUN_PRE_SEND_SEQUENCE",
        "READY_TO_MANUALLY_SEND_ONE",
        "WAITING_FOR_RECIPIENT_ACK",
        "RUN_POST_SEND_SEQUENCE_WITH_ACK",
        "RUN_POST_SEND_SEQUENCE_WITH_GOLD_PATH",
        "RECIPIENT_CHECKPOINT_RECORDED",
        "RECIPIENT_GOLD_PATH_CONFIRMED",
    }


def _read_text_if_exists(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise FirstRecipientOperatorStatusError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise FirstRecipientOperatorStatusError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FirstRecipientOperatorStatusError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_status_receipt_body_sha256", "operator_status_receipt_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _safe_identifier(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.isascii()
        and all(char.isalnum() or char == "_" for char in value)
        and not any(char in value for char in "\\/:. ")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the first-recipient external alpha operator status.")
    parser.add_argument("--workspace-dir", default=str(DEFAULT_OPERATOR_STATUS_WORKSPACE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--operator-packet", default=None)
    parser.add_argument("--builder-gold-path-share-receipt", default=None)
    parser.add_argument("--receipt", default=None, help="Optional share-safe operator status receipt JSON path.")
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing operator status receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_operator_status_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - operator-facing reason.
            logger.error("[FAIL] external alpha first-recipient operator status receipt verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha first-recipient operator status receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("next   : %s", payload["operator_next_action"])
        _log_operator_status_details(payload)
        runbook_path = _private_runbook_path(Path(args.verify_receipt).resolve().parent)
        if runbook_path.is_file():
            logger.info("runbook: %s", runbook_path)
        logger.info("body   : %s", payload["operator_status_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_operator_status(
            Path(args.workspace_dir),
            output_dir=Path(args.output_dir),
            operator_packet_path=Path(args.operator_packet) if args.operator_packet else None,
            builder_gold_path_share_receipt=Path(args.builder_gold_path_share_receipt)
            if args.builder_gold_path_share_receipt
            else None,
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - operator-facing reason.
        logger.error("[FAIL] external alpha first-recipient operator status: %s", exc)
        return 1

    logger.info("[PASS] external alpha first-recipient operator status")
    logger.info("verdict: %s", result["verdict"])
    logger.info("next   : %s", result["next_action"])
    payload = verify_first_recipient_operator_status_receipt_file(Path(result["receipt_json"]))
    _log_operator_status_details(payload)
    if result["private_runbook"]:
        logger.info("runbook: %s", result["private_runbook"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
