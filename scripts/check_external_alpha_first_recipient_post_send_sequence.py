"""Run the operator-side first-recipient post-send sequence without sending."""

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

from scripts.audit_external_alpha_send_chain import audit_send_chain  # noqa: E402
from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_dispatch_record import (  # noqa: E402
    DISPATCH_RECORD_JSON_NAME,
    PREFLIGHT_RECEIPT_NAME,
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.check_external_alpha_recipient_checkpoint import (  # noqa: E402
    RECIPIENT_CHECKPOINT_JSON_NAME,
    check_recipient_checkpoint,
    verify_recipient_checkpoint_file,
)
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR  # noqa: E402


POST_SEND_SEQUENCE_SCHEMA_VERSION = "external_alpha_first_recipient_post_send_sequence_v0_1"
POST_SEND_SEQUENCE_RECEIPT_NAME = "external-alpha-first-recipient-post-send-sequence-receipt.json"
DEFAULT_POST_SEND_WORKSPACE_DIR = DEFAULT_PRIVATE_WORKSPACE_DIR
BUILDER_GOLD_PATH_RECEIPT_NAME = "external_alpha_builder_gold_path_share_receipt.json"
ACK_PLACEHOLDER_FRAGMENTS = (
    "Paste only the private acknowledgement",
    "Paste only CONFIRMED",
)
ACK_CONFIRMED_REPLY = "CONFIRMED"

logger = logging.getLogger(__name__)


class FirstRecipientPostSendSequenceError(RuntimeError):
    """First-recipient post-send sequence failed or is blocked."""


def check_first_recipient_post_send_sequence(
    workspace_dir: Path = DEFAULT_POST_SEND_WORKSPACE_DIR,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    sent_at_utc: str,
    builder_gold_path_share_receipt: Path | None = None,
    receipt_path: Path | None = None,
    require_recipient_checkpoint: bool = False,
    require_gold_path: bool = False,
    require_operator_bypass_audit: bool = True,
    synthetic_rehearsal_without_real_recipient: bool = False,
) -> dict[str, Any]:
    """Record the post-send state for exactly one manually sent recipient."""
    workspace_dir = workspace_dir.resolve()
    output_dir = output_dir.resolve()

    final_audit_result, final_audit_payload = _run_final_audit_step(
        output_dir,
        require_operator_bypass_audit=require_operator_bypass_audit,
    )
    ack_status = _private_ack_status(workspace_dir)
    dispatch_result, dispatch_payload = _run_dispatch_step(
        output_dir=output_dir,
        workspace_dir=workspace_dir,
        sent_at_utc=sent_at_utc,
        synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
    )
    checkpoint_result, checkpoint_payload = _run_checkpoint_step(
        output_dir=output_dir,
        workspace_dir=workspace_dir,
        sent_at_utc=sent_at_utc,
        ack_status=ack_status,
        builder_gold_path_share_receipt=builder_gold_path_share_receipt,
        synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
    )

    payload = _sequence_payload(
        final_audit_payload=final_audit_payload,
        dispatch_payload=dispatch_payload,
        checkpoint_payload=checkpoint_payload,
        ack_status=ack_status,
        builder_gold_path_share_receipt=builder_gold_path_share_receipt,
        require_recipient_checkpoint=require_recipient_checkpoint,
        require_gold_path=require_gold_path,
        step_results={
            "final_send_chain_audit": final_audit_result,
            "dispatch_record": dispatch_result,
            "recipient_ack": _ack_step_result(ack_status),
            "recipient_checkpoint": checkpoint_result,
        },
    )

    receipt_path = (receipt_path or workspace_dir / POST_SEND_SEQUENCE_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_first_recipient_post_send_sequence_receipt_file(receipt_path, require_recorded=False)
    _assert_shareable_receipt_file(receipt_path, workspace_dir, builder_gold_path_share_receipt)

    if payload["status"] != "pass":
        raise FirstRecipientPostSendSequenceError(_blocked_hint(payload))

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["post_send_sequence_receipt_body_sha256"],
        "archive_sha256": payload["release"]["archive_sha256"],
        "recipient_ack_status": payload["ack_summary"]["status"],
        "operator_next_action": payload["operator_next_action"],
    }


def verify_first_recipient_post_send_sequence_receipt_file(
    path: Path,
    *,
    require_recorded: bool = True,
) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_post_send_sequence_receipt_payload(payload, require_recorded=require_recorded)
    return payload


def verify_first_recipient_post_send_sequence_receipt_payload(
    payload: dict[str, Any],
    *,
    require_recorded: bool = True,
) -> None:
    if payload.get("schema_version") != POST_SEND_SEQUENCE_SCHEMA_VERSION:
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt schema_version mismatch.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt checks are missing.")
    ready = all(value is True for value in checks.values())
    if payload.get("status") != ("pass" if ready else "fail"):
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt status does not match checks.")
    expected_verdicts = {
        "BLOCKED_AFTER_MANUAL_SEND",
        "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT",
        "RECIPIENT_CHECKPOINT_RECORDED",
        "RECIPIENT_GOLD_PATH_CONFIRMED",
    }
    if payload.get("verdict") not in expected_verdicts:
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt verdict is invalid.")
    if not ready and payload.get("verdict") != "BLOCKED_AFTER_MANUAL_SEND":
        raise FirstRecipientPostSendSequenceError("blocked post-send sequence has the wrong verdict.")
    if payload.get("safe_to_share") is not True:
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt must be safe_to_share.")
    receipt_checks = payload.get("post_send_sequence_receipt_checks")
    recalculated = _receipt_checks(payload)
    if receipt_checks != recalculated:
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt self-checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise FirstRecipientPostSendSequenceError(
            "post-send sequence receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("post_send_sequence_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt body hash mismatch.")
    if require_recorded and not ready:
        failed = [name for name, passed in checks.items() if passed is not True]
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt is blocked: " + ", ".join(failed))


def _run_final_audit_step(
    output_dir: Path,
    *,
    require_operator_bypass_audit: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        payload = audit_send_chain(
            output_dir,
            require_operator_bypass_audit=require_operator_bypass_audit,
        )
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001 - write a controlled receipt instead of leaking details.
        recorded_payload = _recorded_dispatch_final_audit_fallback(
            output_dir,
            require_operator_bypass_audit=require_operator_bypass_audit,
        )
        if recorded_payload is not None:
            return _step_result("pass", recorded_payload.get("verdict"), []), recorded_payload
        return _step_result("fail", "missing_or_invalid", [_error_code(exc)]), None


def _recorded_dispatch_final_audit_fallback(
    output_dir: Path,
    *,
    require_operator_bypass_audit: bool,
) -> dict[str, Any] | None:
    """Accept a rerun after the send was already recorded by the first post-send pass."""
    try:
        dispatch_payload = verify_dispatch_record_file(output_dir / DISPATCH_RECORD_JSON_NAME)
    except Exception:  # noqa: BLE001 - caller will preserve the original audit error.
        return None
    dispatch_record = _dict(dispatch_payload, "dispatch_record")
    dispatch_policy = _dict(dispatch_payload, "dispatch_execution_policy")
    preflight = _dict(dispatch_payload, "pre_send_preflight")
    release = _dict(dispatch_payload, "release")
    checks = {
        "dispatch_record_already_sent": dispatch_payload.get("verdict") == "SENT_ONE_RECORDED"
        and dispatch_record.get("sent_recorded") is True,
        "dispatch_preflight_required_and_verified": preflight.get("required") is True
        and preflight.get("verified_standalone") is True
        and preflight.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY"
        and _looks_like_sha256(preflight.get("body_sha256")),
        "manual_dispatch_only": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "one_recipient_policy_locked": dispatch_policy.get("max_recipients_per_record") == 1,
        "release_hash_present": _looks_like_sha256(release.get("archive_sha256")),
    }
    if any(value is not True for value in checks.values()):
        return None
    return {
        "status": "pass",
        "verdict": "PRE_SEND_CHAIN_ALREADY_RECORDED",
        "archive_sha256": release.get("archive_sha256"),
        "file_count": release.get("file_count"),
        "dispatch_record_body_sha256": dispatch_payload.get("dispatch_record_body_sha256"),
        "operator_send_bypass_audit_required": require_operator_bypass_audit,
        "checks": checks,
    }


def _run_dispatch_step(
    *,
    output_dir: Path,
    workspace_dir: Path,
    sent_at_utc: str,
    synthetic_rehearsal_without_real_recipient: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = check_dispatch_record(
            output_dir=output_dir,
            skip_build=True,
            private_workspace_dir=workspace_dir,
            sent_at_utc=sent_at_utc,
            require_preflight_receipt=True,
            synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
        )
        payload = verify_dispatch_record_file(
            Path(str(result["dispatch_record_json"])),
            allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
        )
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "missing_or_invalid", [_error_code(exc)]), _load_json_if_exists(
            output_dir / DISPATCH_RECORD_JSON_NAME
        )


def _run_checkpoint_step(
    *,
    output_dir: Path,
    workspace_dir: Path,
    sent_at_utc: str,
    ack_status: dict[str, Any],
    builder_gold_path_share_receipt: Path | None,
    synthetic_rehearsal_without_real_recipient: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if ack_status.get("status") != "ready":
        return _step_result("waiting", "WAITING_FOR_RECIPIENT", []), None
    try:
        result = check_recipient_checkpoint(
            output_dir=output_dir,
            skip_build=True,
            private_workspace_dir=workspace_dir,
            sent_at_utc=sent_at_utc,
            builder_gold_path_share_receipt=builder_gold_path_share_receipt,
            require_preflight_receipt=True,
            allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
        )
        payload = verify_recipient_checkpoint_file(
            Path(str(result["recipient_checkpoint_json"])),
            allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
        )
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "missing_or_invalid", [_error_code(exc)]), _load_json_if_exists(
            output_dir / RECIPIENT_CHECKPOINT_JSON_NAME
        )


def _sequence_payload(
    *,
    final_audit_payload: dict[str, Any] | None,
    dispatch_payload: dict[str, Any] | None,
    checkpoint_payload: dict[str, Any] | None,
    ack_status: dict[str, Any],
    builder_gold_path_share_receipt: Path | None,
    require_recipient_checkpoint: bool,
    require_gold_path: bool,
    step_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    release_hash = _first_hash(
        _release_hash(checkpoint_payload),
        _release_hash(dispatch_payload),
        final_audit_payload.get("archive_sha256") if isinstance(final_audit_payload, dict) else None,
    )
    release_file_count = _first_value(
        _dict(checkpoint_payload, "release").get("file_count"),
        _dict(dispatch_payload, "release").get("file_count"),
    )
    release_hashes = [
        _release_hash(checkpoint_payload),
        _release_hash(dispatch_payload),
        final_audit_payload.get("archive_sha256") if isinstance(final_audit_payload, dict) else None,
    ]
    present_hashes = [value for value in release_hashes if isinstance(value, str)]
    dispatch_record = _dict(dispatch_payload, "dispatch_record")
    dispatch_policy = _dict(dispatch_payload, "dispatch_execution_policy")
    preflight = _dict(dispatch_payload, "pre_send_preflight")
    checkpoint_verdict = checkpoint_payload.get("verdict") if isinstance(checkpoint_payload, dict) else None
    ack_ready = ack_status.get("status") == "ready"
    builder_receipt_requested = builder_gold_path_share_receipt is not None
    builder_receipt_present = _path_is_file(builder_gold_path_share_receipt)
    builder_receipt_sha256 = _file_sha256(builder_gold_path_share_receipt) if builder_receipt_present else None
    checks = {
        "final_send_chain_ready": step_results["final_send_chain_audit"].get("status") == "pass",
        "dispatch_recorded": step_results["dispatch_record"].get("status") == "pass"
        and dispatch_payload is not None
        and dispatch_payload.get("verdict") == "SENT_ONE_RECORDED"
        and dispatch_record.get("sent_recorded") is True,
        "dispatch_preflight_required_and_verified": preflight.get("required") is True
        and preflight.get("verified_standalone") is True
        and preflight.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY",
        "release_hashes_match": bool(present_hashes)
        and len(set(present_hashes)) == 1
        and _looks_like_sha256(present_hashes[0]),
        "manual_dispatch_only": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "one_recipient_policy_locked": dispatch_policy.get("max_recipients_per_record") == 1,
        "recipient_ack_ready_when_required": (not require_recipient_checkpoint and not require_gold_path) or ack_ready,
        "recipient_checkpoint_recorded_when_ack_ready": (not ack_ready)
        or checkpoint_verdict in {"RECIPIENT_CHECKPOINT_RECORDED", "RECIPIENT_GOLD_PATH_CONFIRMED"},
        "builder_receipt_exists_when_provided": (not builder_receipt_requested) or builder_receipt_present,
        "builder_receipt_requires_ack": (not builder_receipt_present) or ack_ready,
        "gold_path_confirmed_when_required": (not require_gold_path)
        or checkpoint_verdict == "RECIPIENT_GOLD_PATH_CONFIRMED",
        "post_send_sequence_only": True,
        "script_does_not_send_to_recipient": True,
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
    }
    ready = all(checks.values())
    verdict = _sequence_verdict(ready=ready, checkpoint_verdict=checkpoint_verdict)
    operator_next_action = _operator_next_action_for_state(
        verdict=verdict,
        ack_ready=ack_ready,
        require_recipient_checkpoint=require_recipient_checkpoint,
        require_gold_path=require_gold_path,
        builder_receipt_present=builder_receipt_present,
    )
    ack_summary = _ack_summary(
        ack_status=ack_status,
        ack_ready=ack_ready,
        require_recipient_checkpoint=require_recipient_checkpoint,
        require_gold_path=require_gold_path,
        builder_receipt_present=builder_receipt_present,
        next_action=operator_next_action,
    )
    blocked_steps = [
        name for name, result in step_results.items() if result.get("status") == "fail"
    ]
    payload: dict[str, Any] = {
        "schema_version": POST_SEND_SEQUENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if ready else "fail",
        "verdict": verdict,
        "safe_to_share": True,
        "release": {
            "zip_file": RELEASE_SLUG + ".zip",
            "archive_sha256": release_hash,
            "file_count": release_file_count,
        },
        "step_results": step_results,
        "post_send_state": {
            "sent_recorded": dispatch_record.get("sent_recorded") is True,
            "sent_at_utc": dispatch_record.get("sent_at_utc"),
            "recipient_ack_status": ack_status.get("status"),
            "recipient_checkpoint_verdict": checkpoint_verdict,
            "builder_gold_path_receipt_requested": builder_receipt_requested,
            "builder_gold_path_receipt_present": builder_receipt_present,
        },
        "gate_receipts": {
            "final_send_chain_audit": {
                "verdict": final_audit_payload.get("verdict")
                if isinstance(final_audit_payload, dict)
                else "missing_or_invalid",
                "release_receipt_body_sha256": final_audit_payload.get("receipt_body_sha256")
                if isinstance(final_audit_payload, dict)
                else None,
                "operator_bypass_audit_required": final_audit_payload.get("operator_send_bypass_audit_required")
                if isinstance(final_audit_payload, dict)
                else None,
            },
            "dispatch_record": {
                "file": DISPATCH_RECORD_JSON_NAME,
                "verdict": dispatch_payload.get("verdict") if isinstance(dispatch_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(dispatch_payload, "dispatch_record_body_sha256"),
                "preflight": {
                    "file": preflight.get("file") or PREFLIGHT_RECEIPT_NAME,
                    "required": preflight.get("required") is True,
                    "body_sha256": preflight.get("body_sha256"),
                    "verified_standalone": preflight.get("verified_standalone") is True,
                },
            },
            "recipient_checkpoint": {
                "file": RECIPIENT_CHECKPOINT_JSON_NAME,
                "verdict": checkpoint_verdict or "not_recorded_yet",
                "body_sha256": _body_hash(checkpoint_payload, "recipient_checkpoint_body_sha256"),
            },
            "builder_gold_path_share_receipt": {
                "file": BUILDER_GOLD_PATH_RECEIPT_NAME if builder_receipt_requested else None,
                "requested": builder_receipt_requested,
                "present": builder_receipt_present,
                "status": "present" if builder_receipt_present else "missing" if builder_receipt_requested else "absent",
                "sha256": builder_receipt_sha256,
            },
        },
        "private_input_fingerprints": {
            "recipient_ack_status": ack_status.get("status"),
            "recipient_ack_sha256": ack_status.get("sha256") if ack_ready else None,
            "recipient_ack_confirmed": ack_status.get("confirmed_reply_present") is True,
            "recipient_ack_exactly_one_line": ack_status.get("exactly_one_acknowledgement") is True,
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "ack_summary": ack_summary,
        "blocked_steps": blocked_steps,
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "post_send_sequence_only": True,
            "requires_preflight_receipt_for_dispatch_record": True,
            "requires_preflight_receipt_for_recipient_checkpoint": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "operator_next_action": operator_next_action,
        "checks": checks,
    }
    payload["post_send_sequence_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["post_send_sequence_receipt_checks"] = _receipt_checks(payload)
    return payload


def _sequence_verdict(*, ready: bool, checkpoint_verdict: str | None) -> str:
    if not ready:
        return "BLOCKED_AFTER_MANUAL_SEND"
    if checkpoint_verdict == "RECIPIENT_GOLD_PATH_CONFIRMED":
        return "RECIPIENT_GOLD_PATH_CONFIRMED"
    if checkpoint_verdict == "RECIPIENT_CHECKPOINT_RECORDED":
        return "RECIPIENT_CHECKPOINT_RECORDED"
    return "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT"


def _operator_next_action(verdict: str) -> str:
    if verdict == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT":
        return "Wait for exactly one CONFIRMED recipient acknowledgement, store it in the private workspace, then rerun this sequence."
    if verdict == "RECIPIENT_CHECKPOINT_RECORDED":
        return "Wait for the builder gold path share receipt or collect controlled pilot feedback."
    if verdict == "RECIPIENT_GOLD_PATH_CONFIRMED":
        return "Collect private feedback and controlled pilot learning tags before any next recipient."
    return "Do not claim the send is recorded. Fix the blocked post-send checks and rerun this sequence."


def _operator_next_action_for_state(
    *,
    verdict: str,
    ack_ready: bool,
    require_recipient_checkpoint: bool,
    require_gold_path: bool,
    builder_receipt_present: bool,
) -> str:
    ack_required = require_recipient_checkpoint or require_gold_path or builder_receipt_present
    if verdict == "BLOCKED_AFTER_MANUAL_SEND" and ack_required and not ack_ready:
        return "Wait for exactly one CONFIRMED recipient acknowledgement, store it in the private workspace, then rerun this sequence."
    return _operator_next_action(verdict)


def _ack_summary(
    *,
    ack_status: dict[str, Any],
    ack_ready: bool,
    require_recipient_checkpoint: bool,
    require_gold_path: bool,
    builder_receipt_present: bool,
    next_action: str,
) -> dict[str, Any]:
    status = ack_status.get("status")
    if status not in {"ready", "missing", "empty", "placeholder", "unreadable", "unconfirmed"}:
        status = "missing"
    return {
        "file": "recipient-ack-private.txt",
        "status": status,
        "sha256_present": ack_ready and _looks_like_sha256(ack_status.get("sha256")),
        "waiting_for_recipient": not ack_ready,
        "required_for_current_command": require_recipient_checkpoint or require_gold_path or builder_receipt_present,
        "confirmed_reply_present": ack_status.get("confirmed_reply_present") is True,
        "exactly_one_acknowledgement": ack_status.get("exactly_one_acknowledgement") is True,
        "raw_private_values_included": False,
        "local_paths_included": False,
        "next_action": next_action,
    }


def _ack_step_result(ack_status: dict[str, Any]) -> dict[str, Any]:
    if ack_status.get("status") == "ready":
        return _step_result("pass", "RECIPIENT_ACK_READY", [])
    return _step_result("waiting", "WAITING_FOR_RECIPIENT", [str(ack_status.get("status") or "missing")])


def _private_ack_status(workspace_dir: Path) -> dict[str, Any]:
    path = workspace_dir / "recipient-ack-private.txt"
    if not path.is_file():
        return _private_status("missing")
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return _private_status("unreadable")
    stripped = text.strip()
    if not stripped:
        return _private_status("empty")
    if any(fragment in text for fragment in ACK_PLACEHOLDER_FRAGMENTS):
        return _private_status("placeholder")
    nonempty_line_count = _nonempty_line_count(text)
    confirmed_reply_present = _is_confirmed_ack(stripped)
    if nonempty_line_count != 1 or not confirmed_reply_present:
        result = _private_status("unconfirmed")
        result["confirmed_reply_present"] = confirmed_reply_present
        result["exactly_one_acknowledgement"] = nonempty_line_count == 1
        return result
    return {
        "file": "recipient-ack-private.txt",
        "status": "ready",
        "sha256": hashlib.sha256(data).hexdigest(),
        "confirmed_reply_present": True,
        "exactly_one_acknowledgement": True,
        "raw_value_included": False,
        "local_path_included": False,
    }


def _nonempty_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _is_confirmed_ack(text: str) -> bool:
    return text.strip().upper() == ACK_CONFIRMED_REPLY


def _private_status(status: str) -> dict[str, Any]:
    return {
        "file": "recipient-ack-private.txt",
        "status": status,
        "sha256": None,
        "confirmed_reply_present": False,
        "exactly_one_acknowledgement": False,
        "raw_value_included": False,
        "local_path_included": False,
    }


def _step_result(status: str, verdict: Any, failed_checks: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "verdict": verdict if isinstance(verdict, str) else "missing_or_invalid",
        "failed_checks": sorted(failed_checks),
    }


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    release = _dict(payload, "release")
    post_send_state = _dict(payload, "post_send_state")
    gate_receipts = _dict(payload, "gate_receipts")
    dispatch_record = _dict(gate_receipts, "dispatch_record")
    preflight = _dict(dispatch_record, "preflight")
    recipient_checkpoint = _dict(gate_receipts, "recipient_checkpoint")
    builder_receipt = _dict(gate_receipts, "builder_gold_path_share_receipt")
    private_inputs = _dict(payload, "private_input_fingerprints")
    ack_summary = _dict(payload, "ack_summary")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    ready = bool(checks) and all(value is True for value in checks.values())
    body_hash = payload.get("post_send_sequence_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == POST_SEND_SEQUENCE_SCHEMA_VERSION,
        "status_matches_checks": (payload.get("status") == "pass") is ready,
        "verdict_matches_checks": payload.get("verdict")
        == _sequence_verdict(
            ready=ready,
            checkpoint_verdict=post_send_state.get("recipient_checkpoint_verdict"),
        ),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "archive_hash_present_when_passed": (not ready) or _looks_like_sha256(release.get("archive_sha256")),
        "dispatch_body_hash_present_when_recorded": post_send_state.get("sent_recorded") is not True
        or _looks_like_sha256(dispatch_record.get("body_sha256")),
        "preflight_hash_present_when_recorded": post_send_state.get("sent_recorded") is not True
        or (
            preflight.get("required") is True
            and preflight.get("verified_standalone") is True
            and _looks_like_sha256(preflight.get("body_sha256"))
        ),
        "recipient_checkpoint_hash_present_when_recorded": post_send_state.get(
            "recipient_checkpoint_verdict"
        )
        not in {"RECIPIENT_CHECKPOINT_RECORDED", "RECIPIENT_GOLD_PATH_CONFIRMED"}
        or _looks_like_sha256(recipient_checkpoint.get("body_sha256")),
        "builder_receipt_hash_present_when_used": builder_receipt.get("present") is not True
        or _looks_like_sha256(builder_receipt.get("sha256")),
        "recipient_ack_hash_present_when_ready": private_inputs.get("recipient_ack_status") != "ready"
        or _looks_like_sha256(private_inputs.get("recipient_ack_sha256")),
        "ack_summary_status_controlled": ack_summary.get("file") == "recipient-ack-private.txt"
        and ack_summary.get("status") in {"ready", "missing", "empty", "placeholder", "unreadable", "unconfirmed"}
        and isinstance(ack_summary.get("sha256_present"), bool)
        and isinstance(ack_summary.get("waiting_for_recipient"), bool),
        "ack_summary_confirmation_controlled": isinstance(ack_summary.get("confirmed_reply_present"), bool)
        and isinstance(ack_summary.get("exactly_one_acknowledgement"), bool),
        "ack_summary_hash_when_ready": ack_summary.get("status") != "ready"
        or ack_summary.get("sha256_present") is True,
        "ack_summary_privacy_safe": ack_summary.get("raw_private_values_included") is False
        and ack_summary.get("local_paths_included") is False,
        "raw_private_values_omitted": private_inputs.get("raw_private_values_included") is False
        and _dict(payload, "policy").get("raw_private_values_in_receipt") is False,
        "local_paths_omitted": private_inputs.get("local_paths_included") is False
        and _dict(payload, "policy").get("local_paths_in_receipt") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "manual_dispatch_only": _dict(payload, "policy").get("script_sends_to_recipient") is False
        and _dict(payload, "policy").get("manual_operator_dispatch_required") is True,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _assert_shareable_receipt_file(
    path: Path,
    workspace_dir: Path,
    builder_gold_path_share_receipt: Path | None,
) -> None:
    text = path.read_text(encoding="utf-8")
    private_values = [
        _read_text_if_exists(workspace_dir / "recipient-private.txt"),
        _read_text_if_exists(workspace_dir / "operator-dispatch-note-private.md"),
        _read_text_if_exists(workspace_dir / "recipient-ack-private.txt"),
    ]
    forbidden = [
        str(ROOT),
        str(Path.home()),
        str(workspace_dir),
        _safe_resolved_path_text(builder_gold_path_share_receipt),
        "Recipient identifier/contact goes here",
        "Record the private channel",
        "<private-send-channel>",
        "Paste only the private acknowledgement",
        "Paste only CONFIRMED",
        *[value for value in private_values if value],
    ]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise FirstRecipientPostSendSequenceError("post-send sequence receipt leaked local path or raw private text.")


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


def _release_hash(payload: dict[str, Any] | None) -> str | None:
    value = _dict(payload, "release").get("archive_sha256")
    return value if isinstance(value, str) else None


def _body_hash(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _first_hash(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and _looks_like_sha256(value):
            return value
    return None


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _blocked_hint(payload: dict[str, Any]) -> str:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed = [name for name, passed in checks.items() if passed is not True]
    ack_summary = _dict(payload, "ack_summary")
    parts = ["first-recipient post-send sequence blocked checks: " + ", ".join(failed)]
    status = ack_summary.get("status")
    if isinstance(status, str):
        details = []
        if ack_summary.get("confirmed_reply_present") is not True:
            details.append("confirmed_reply=false")
        if ack_summary.get("exactly_one_acknowledgement") is not True:
            details.append("exactly_one_acknowledgement=false")
        suffix = "" if not details else " (" + ", ".join(details) + ")"
        parts.append(f"recipient-ack-private.txt={status}{suffix}")
    next_action = ack_summary.get("next_action") or payload.get("operator_next_action")
    if isinstance(next_action, str) and next_action:
        parts.append("next: " + next_action)
    return "; ".join(parts)


def _file_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path_is_file(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.is_file()
    except OSError:
        return False


def _safe_resolved_path_text(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "post_send_sequence_receipt_body_sha256", "post_send_sequence_receipt_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _error_code(exc: Exception) -> str:
    return exc.__class__.__name__


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    try:
        return _read_json(path)
    except Exception:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise FirstRecipientPostSendSequenceError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise FirstRecipientPostSendSequenceError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FirstRecipientPostSendSequenceError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the first-recipient external alpha post-send sequence.")
    parser.add_argument("--workspace-dir", default=str(DEFAULT_POST_SEND_WORKSPACE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--sent-at-utc", default=None)
    parser.add_argument(
        "--builder-gold-path-share-receipt",
        "--gold-path-share-receipt",
        dest="builder_gold_path_share_receipt",
        default=None,
    )
    parser.add_argument("--receipt", default=None, help="Optional share-safe post-send sequence receipt JSON path.")
    parser.add_argument("--require-recipient-checkpoint", action="store_true")
    parser.add_argument("--require-gold-path", action="store_true")
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing post-send sequence receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_post_send_sequence_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - operator-facing reason.
            logger.error("[FAIL] external alpha first-recipient post-send sequence receipt verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha first-recipient post-send sequence receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["post_send_sequence_receipt_body_sha256"])
        return 0

    if not args.sent_at_utc:
        logger.error("[FAIL] external alpha first-recipient post-send sequence: --sent-at-utc is required unless --verify-receipt is used.")
        return 1

    try:
        result = check_first_recipient_post_send_sequence(
            Path(args.workspace_dir),
            output_dir=Path(args.output_dir),
            sent_at_utc=args.sent_at_utc,
            builder_gold_path_share_receipt=Path(args.builder_gold_path_share_receipt)
            if args.builder_gold_path_share_receipt
            else None,
            receipt_path=Path(args.receipt) if args.receipt else None,
            require_recipient_checkpoint=args.require_recipient_checkpoint,
            require_gold_path=args.require_gold_path,
        )
    except Exception as exc:  # noqa: BLE001 - operator-facing reason.
        logger.error("[FAIL] external alpha first-recipient post-send sequence: %s", exc)
        return 1

    logger.info("[PASS] external alpha first-recipient post-send sequence")
    logger.info("verdict: %s", result["verdict"])
    logger.info("ack    : %s", result["recipient_ack_status"])
    logger.info("next   : %s", result["operator_next_action"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
