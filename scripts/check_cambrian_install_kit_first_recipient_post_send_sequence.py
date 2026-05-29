"""Run the Cambrian install-kit first-recipient post-send sequence without sending."""

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
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.check_cambrian_install_kit_first_recipient_operator_status import (  # noqa: E402
    OPERATOR_STATUS_READY_RECEIPT_NAME,
)
from scripts.check_cambrian_install_kit_recipient_checkpoint import (  # noqa: E402
    RECIPIENT_CHECKPOINT_JSON_NAME,
    check_recipient_checkpoint,
    verify_recipient_checkpoint_file,
)
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import (  # noqa: E402
    DEFAULT_WORKSPACE_DIR,
)
from scripts.prepare_cambrian_install_kit_release import RELEASE_BUNDLE_NAME  # noqa: E402


POST_SEND_SEQUENCE_SCHEMA_VERSION = "cambrian_install_kit_first_recipient_post_send_sequence_v0_1"
POST_SEND_SEQUENCE_RECEIPT_NAME = "cambrian-install-kit-first-recipient-post-send-sequence-receipt.json"
MANUAL_SEND_GO_RECEIPT_NAME = "cambrian-install-kit-first-recipient-manual-send-go-receipt.json"
RETURNED_RECEIPT_DIR_NAME = "returned-receipts"
INSTALL_SHARE_RECEIPT_NAME = "cambrian_install_share_receipt.json"
GOLD_PATH_SHARE_RECEIPT_NAME = "cambrian_gold_path_share_receipt.json"
MCP_OPERABILITY_RECEIPT_NAME = "mcp_operability_receipt.json"
ACK_PLACEHOLDER = "WAIT_FOR_ONE_CONFIRMED_LINE"
ACK_CONFIRMED_REPLY = "CONFIRMED"

logger = logging.getLogger(__name__)


class InstallKitFirstRecipientPostSendSequenceError(RuntimeError):
    """Install-kit first-recipient post-send sequence failed or is blocked."""


def check_first_recipient_post_send_sequence(
    workspace_dir: Path | None = None,
    *,
    output_dir: Path | None = None,
    sent_at_utc: str | None = None,
    install_share_receipt: Path | None = None,
    gold_path_share_receipt: Path | None = None,
    mcp_operability_receipt: Path | None = None,
    receipt_path: Path | None = None,
    require_recipient_checkpoint: bool = False,
    require_gold_path: bool = False,
    skip_verify: bool = False,
    synthetic_rehearsal_without_real_recipient: bool = False,
) -> dict[str, Any]:
    """Record the safe state after exactly one human manual send."""
    workspace = (workspace_dir or DEFAULT_WORKSPACE_DIR).resolve()
    dist = (output_dir or ROOT / "dist").resolve()
    resolved_install = _default_returned_receipt(
        workspace,
        install_share_receipt,
        INSTALL_SHARE_RECEIPT_NAME,
    )
    resolved_gold = _default_returned_receipt(
        workspace,
        gold_path_share_receipt,
        GOLD_PATH_SHARE_RECEIPT_NAME,
    )
    resolved_mcp = _default_returned_receipt(
        workspace,
        mcp_operability_receipt,
        MCP_OPERABILITY_RECEIPT_NAME,
    )
    ack_status = _private_ack_status(workspace)

    if not sent_at_utc:
        dispatch_result, dispatch_payload = _step_result("fail", "SENT_AT_UTC_REQUIRED", ["sent_at_utc_required"]), None
        checkpoint_result, checkpoint_payload = _step_result("waiting", "WAITING_FOR_RECIPIENT", []), None
    else:
        dispatch_result, dispatch_payload = _run_dispatch_step(
            output_dir=dist,
            workspace=workspace,
            sent_at_utc=sent_at_utc,
            skip_verify=skip_verify,
            synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
        )
        checkpoint_result, checkpoint_payload = _run_checkpoint_step(
            output_dir=dist,
            workspace=workspace,
            sent_at_utc=sent_at_utc,
            ack_status=ack_status,
            install_share_receipt=resolved_install,
            gold_path_share_receipt=resolved_gold,
            mcp_operability_receipt=resolved_mcp,
            require_recipient_checkpoint=require_recipient_checkpoint,
            require_gold_path=require_gold_path,
            skip_verify=skip_verify,
            synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
        )

    payload = _sequence_payload(
        release_bundle_sha256=_release_bundle_sha256(dist),
        dispatch_payload=dispatch_payload,
        checkpoint_payload=checkpoint_payload,
        ack_status=ack_status,
        install_share_receipt=resolved_install,
        gold_path_share_receipt=resolved_gold,
        mcp_operability_receipt=resolved_mcp,
        require_recipient_checkpoint=require_recipient_checkpoint,
        require_gold_path=require_gold_path,
        sent_at_utc=sent_at_utc,
        step_results={
            "dispatch_record": dispatch_result,
            "recipient_ack": _ack_step_result(ack_status),
            "recipient_checkpoint": checkpoint_result,
        },
    )
    target = (receipt_path or workspace / POST_SEND_SEQUENCE_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, payload)
    verify_first_recipient_post_send_sequence_receipt_file(target, require_recorded=False)
    _assert_shareable_receipt_file(target, workspace)

    if payload["status"] != "pass":
        raise InstallKitFirstRecipientPostSendSequenceError(_blocked_hint(payload))

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(target),
        "receipt_body_sha256": payload["post_send_sequence_receipt_body_sha256"],
        "release_bundle_sha256": payload["release_bundle"]["sha256"],
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
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt schema_version mismatch.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt checks are missing.")
    ready = all(value is True for value in checks.values())
    if payload.get("status") != ("pass" if ready else "fail"):
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt status does not match checks.")
    if payload.get("verdict") not in {
        "BLOCKED_AFTER_MANUAL_SEND",
        "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT",
        "RECIPIENT_INSTALL_CONFIRMED",
        "RECIPIENT_GOLD_PATH_CONFIRMED",
    }:
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt verdict is invalid.")
    if not ready and payload.get("verdict") != "BLOCKED_AFTER_MANUAL_SEND":
        raise InstallKitFirstRecipientPostSendSequenceError("blocked post-send sequence has the wrong verdict.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt must be safe_to_share.")
    recalculated = _receipt_checks(payload)
    if payload.get("post_send_sequence_receipt_checks") != recalculated:
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt self-checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise InstallKitFirstRecipientPostSendSequenceError(
            "post-send sequence receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("post_send_sequence_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt body hash mismatch.")
    if require_recorded and not ready:
        failed = [name for name, passed in checks.items() if passed is not True]
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt is blocked: " + ", ".join(failed))


def _run_dispatch_step(
    *,
    output_dir: Path,
    workspace: Path,
    sent_at_utc: str,
    skip_verify: bool,
    synthetic_rehearsal_without_real_recipient: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = check_dispatch_record(
            output_dir=output_dir,
            skip_verify=skip_verify,
            recipient_private_file=workspace / "recipient-private.txt",
            operator_dispatch_note_private_file=workspace / "operator-dispatch-note-private.md",
            operator_status_receipt=workspace / OPERATOR_STATUS_READY_RECEIPT_NAME,
            require_operator_status_receipt=True,
            manual_send_go_receipt=workspace / MANUAL_SEND_GO_RECEIPT_NAME,
            require_manual_send_go_receipt=True,
            sent_at_utc=sent_at_utc,
            synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
        )
        payload = verify_dispatch_record_file(
            Path(str(result["dispatch_record_json"])),
            allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
        )
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "DISPATCH_NOT_RECORDED", _safe_error_codes(exc)), _load_json_if_exists(
            output_dir / DISPATCH_RECORD_JSON_NAME
        )


def _run_checkpoint_step(
    *,
    output_dir: Path,
    workspace: Path,
    sent_at_utc: str,
    ack_status: dict[str, Any],
    install_share_receipt: Path | None,
    gold_path_share_receipt: Path | None,
    mcp_operability_receipt: Path | None,
    require_recipient_checkpoint: bool,
    require_gold_path: bool,
    skip_verify: bool,
    synthetic_rehearsal_without_real_recipient: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    returned_receipt_requested = any(
        path is not None for path in (install_share_receipt, gold_path_share_receipt, mcp_operability_receipt)
    )
    returned_receipt_present = any(
        _path_is_file(path) for path in (install_share_receipt, gold_path_share_receipt, mcp_operability_receipt)
    )
    if ack_status.get("status") != "ready" and not returned_receipt_present and not require_recipient_checkpoint and not require_gold_path:
        return _step_result("waiting", "WAITING_FOR_RECIPIENT", []), None
    if ack_status.get("status") != "ready":
        return _step_result("fail", "RECIPIENT_ACK_NOT_READY", [str(ack_status.get("status") or "missing")]), None
    try:
        result = check_recipient_checkpoint(
            output_dir=output_dir,
            skip_verify=skip_verify,
            recipient_private_file=workspace / "recipient-private.txt",
            operator_dispatch_note_private_file=workspace / "operator-dispatch-note-private.md",
            operator_status_receipt=workspace / OPERATOR_STATUS_READY_RECEIPT_NAME,
            require_operator_status_receipt=True,
            manual_send_go_receipt=workspace / MANUAL_SEND_GO_RECEIPT_NAME,
            require_manual_send_go_receipt=True,
            recipient_ack_private_file=workspace / "recipient-ack-private.txt",
            install_share_receipt=install_share_receipt,
            gold_path_share_receipt=gold_path_share_receipt,
            mcp_operability_receipt=mcp_operability_receipt,
            sent_at_utc=sent_at_utc,
            allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
        )
        payload = verify_recipient_checkpoint_file(
            Path(str(result["recipient_checkpoint_json"])),
            allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
        )
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "RECIPIENT_CHECKPOINT_NOT_RECORDED", _safe_error_codes(exc)), _load_json_if_exists(
            output_dir / RECIPIENT_CHECKPOINT_JSON_NAME
        )


def _sequence_payload(
    *,
    release_bundle_sha256: str | None,
    dispatch_payload: dict[str, Any] | None,
    checkpoint_payload: dict[str, Any] | None,
    ack_status: dict[str, Any],
    install_share_receipt: Path | None,
    gold_path_share_receipt: Path | None,
    mcp_operability_receipt: Path | None,
    require_recipient_checkpoint: bool,
    require_gold_path: bool,
    sent_at_utc: str | None,
    step_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    dispatch_record = _dict(dispatch_payload, "dispatch_record")
    dispatch_policy = _dict(dispatch_payload, "dispatch_execution_policy")
    operator_status = _dict(dispatch_payload, "operator_status_pre_send")
    checkpoint_verdict = checkpoint_payload.get("verdict") if isinstance(checkpoint_payload, dict) else None
    checkpoint_copy_paste_boundary = _checkpoint_copy_paste_boundary_summary(checkpoint_payload)
    ack_ready = ack_status.get("status") == "ready"
    returned_receipt_requested = any(
        path is not None for path in (install_share_receipt, gold_path_share_receipt, mcp_operability_receipt)
    )
    checks = {
        "sent_at_utc_present": isinstance(sent_at_utc, str) and bool(sent_at_utc.strip()),
        "dispatch_recorded": step_results["dispatch_record"].get("status") == "pass"
        and dispatch_payload is not None
        and dispatch_payload.get("verdict") == "SENT_ONE_RECORDED"
        and dispatch_record.get("sent_recorded") is True,
        "operator_status_required_and_ready": operator_status.get("required") is True
        and operator_status.get("present") is True
        and operator_status.get("verified_standalone") is True
        and operator_status.get("ready_to_send_one") is True
        and operator_status.get("verdict") == "READY_TO_MANUALLY_SEND_ONE",
        "operator_status_matches_dispatch": operator_status.get("release_hash_matches_dispatch") is True
        and operator_status.get("release_current_artifacts_match_dispatch") is not False
        and operator_status.get("private_hashes_match_dispatch") is True,
        "manual_dispatch_only": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "one_recipient_policy_locked": dispatch_policy.get("max_recipients_per_record") == 1,
        "recipient_ack_ready_when_required": (not returned_receipt_requested and not require_recipient_checkpoint and not require_gold_path)
        or ack_ready,
        "recipient_checkpoint_recorded_when_ack_ready": (not ack_ready)
        or checkpoint_verdict in {"RECIPIENT_INSTALL_CONFIRMED", "RECIPIENT_GOLD_PATH_CONFIRMED"},
        "install_receipt_present_when_checkpoint_required": (not require_recipient_checkpoint)
        or _path_is_file(install_share_receipt),
        "gold_path_confirmed_when_required": (not require_gold_path)
        or checkpoint_verdict == "RECIPIENT_GOLD_PATH_CONFIRMED",
        "post_send_sequence_only": True,
        "script_does_not_send_to_recipient": True,
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
        "recipient_checkpoint_copy_paste_boundary_preserved": _checkpoint_copy_paste_boundary_ready(
            checkpoint_copy_paste_boundary
        ),
    }
    ready = all(checks.values())
    verdict = _sequence_verdict(ready=ready, checkpoint_verdict=checkpoint_verdict)
    operator_next_action = _operator_next_action(
        verdict=verdict,
        ack_ready=ack_ready,
        returned_receipt_present=returned_receipt_requested,
        require_recipient_checkpoint=require_recipient_checkpoint,
        require_gold_path=require_gold_path,
    )
    returned_receipts = {
        INSTALL_SHARE_RECEIPT_NAME: _returned_receipt_summary(install_share_receipt),
        GOLD_PATH_SHARE_RECEIPT_NAME: _returned_receipt_summary(gold_path_share_receipt),
        MCP_OPERABILITY_RECEIPT_NAME: _returned_receipt_summary(mcp_operability_receipt),
    }
    human_next_steps = _human_next_steps(
        verdict=verdict,
        sent_at_utc=sent_at_utc,
        ack_status=ack_status,
        returned_receipts=returned_receipts,
        require_recipient_checkpoint=require_recipient_checkpoint,
        require_gold_path=require_gold_path,
        operator_next_action=operator_next_action,
    )
    payload: dict[str, Any] = {
        "schema_version": POST_SEND_SEQUENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if ready else "fail",
        "verdict": verdict,
        "safe_to_share": True,
        "release_bundle": {
            "file": RELEASE_BUNDLE_NAME,
            "sha256": release_bundle_sha256,
        },
        "step_results": step_results,
        "post_send_state": {
            "sent_at_utc": sent_at_utc,
            "sent_recorded": dispatch_record.get("sent_recorded") is True,
            "recipient_ack_status": ack_status.get("status"),
            "recipient_checkpoint_verdict": checkpoint_verdict,
            "install_share_receipt_requested": install_share_receipt is not None,
            "install_share_receipt_present": _path_is_file(install_share_receipt),
            "gold_path_share_receipt_requested": gold_path_share_receipt is not None,
            "gold_path_share_receipt_present": _path_is_file(gold_path_share_receipt),
            "mcp_operability_receipt_requested": mcp_operability_receipt is not None,
            "mcp_operability_receipt_present": _path_is_file(mcp_operability_receipt),
        },
        "gate_receipts": {
            "dispatch_record": {
                "file": DISPATCH_RECORD_JSON_NAME,
                "verdict": dispatch_payload.get("verdict") if isinstance(dispatch_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(dispatch_payload, "dispatch_record_body_sha256"),
            },
            "operator_status_pre_send": {
                "file": operator_status.get("file") or OPERATOR_STATUS_READY_RECEIPT_NAME,
                "required": operator_status.get("required") is True,
                "verified_standalone": operator_status.get("verified_standalone") is True,
                "verdict": operator_status.get("verdict"),
                "body_sha256": operator_status.get("body_sha256"),
                "release_current_artifacts_checked": operator_status.get("release_current_artifacts_checked") is True,
                "release_current_artifacts_match_dispatch": operator_status.get(
                    "release_current_artifacts_match_dispatch"
                ),
                "release_current_artifacts_gate_passed": operator_status.get("release_current_artifacts_gate_passed")
                is not False,
            },
            "recipient_checkpoint": {
                "file": RECIPIENT_CHECKPOINT_JSON_NAME,
                "verdict": checkpoint_verdict or "not_recorded_yet",
                "body_sha256": _body_hash(checkpoint_payload, "recipient_checkpoint_body_sha256"),
                "dispatch_copy_paste_message_policy": checkpoint_copy_paste_boundary,
            },
        },
        "returned_receipts": returned_receipts,
        "ack_summary": _ack_summary(ack_status, next_action=operator_next_action),
        "blocked_steps": [name for name, result in step_results.items() if result.get("status") == "fail"],
        "blocking_summary": {
            "blocked_checks": [name for name, passed in checks.items() if passed is not True],
            "next_action": operator_next_action,
            "human_next_steps": human_next_steps,
            "required_returned_receipts": list(RETURNED_RECEIPT_NAMES),
            "ack_file": "recipient-ack-private.txt",
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "post_send_sequence_only": True,
            "requires_ready_operator_status_receipt": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "operator_next_action": operator_next_action,
        "checks": checks,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["post_send_sequence_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["post_send_sequence_receipt_checks"] = _receipt_checks(payload)
    return payload


def _checkpoint_copy_paste_boundary_summary(checkpoint_payload: dict[str, Any] | None) -> dict[str, Any]:
    policy = _dict(checkpoint_payload, "dispatch_copy_paste_message_policy")
    checkpoint_checks = _dict(checkpoint_payload, "recipient_checkpoint_checks")
    recorded = isinstance(checkpoint_payload, dict)
    return {
        "recorded": recorded,
        "copy_paste_message_sha256": (
            str(policy.get("copy_paste_message_sha256"))
            if _looks_like_sha256(policy.get("copy_paste_message_sha256"))
            else None
        ),
        "bundle_installer_named": policy.get("bundle_installer_named") is True,
        "gold_path_runner_named": policy.get("gold_path_runner_named") is True,
        "share_receipt_named": policy.get("share_receipt_named") is True,
        "gold_path_share_receipt_named": policy.get("gold_path_share_receipt_named") is True,
        "mcp_operability_receipt_named": policy.get("mcp_operability_receipt_named") is True,
        "local_validation_only": policy.get("local_validation_only") is True,
        "public_proof_claim_blocked": policy.get("public_proof_claim_blocked") is True,
        "first_recipient_confirmation_requires_real_send": (
            policy.get("first_recipient_confirmation_requires_real_send") is True
        ),
        "boundary_preserved": checkpoint_checks.get("dispatch_copy_paste_boundary_preserved") is True,
        "raw_copy_paste_message_included": False,
    }


def _checkpoint_copy_paste_boundary_ready(boundary: dict[str, Any]) -> bool:
    if boundary.get("recorded") is not True:
        return boundary.get("raw_copy_paste_message_included") is False
    return (
        _looks_like_sha256(boundary.get("copy_paste_message_sha256"))
        and boundary.get("bundle_installer_named") is True
        and boundary.get("gold_path_runner_named") is True
        and boundary.get("share_receipt_named") is True
        and boundary.get("gold_path_share_receipt_named") is True
        and boundary.get("mcp_operability_receipt_named") is True
        and boundary.get("local_validation_only") is True
        and boundary.get("public_proof_claim_blocked") is True
        and boundary.get("first_recipient_confirmation_requires_real_send") is True
        and boundary.get("boundary_preserved") is True
        and boundary.get("raw_copy_paste_message_included") is False
    )


def _sequence_verdict(*, ready: bool, checkpoint_verdict: str | None) -> str:
    if not ready:
        return "BLOCKED_AFTER_MANUAL_SEND"
    if checkpoint_verdict == "RECIPIENT_GOLD_PATH_CONFIRMED":
        return "RECIPIENT_GOLD_PATH_CONFIRMED"
    if checkpoint_verdict == "RECIPIENT_INSTALL_CONFIRMED":
        return "RECIPIENT_INSTALL_CONFIRMED"
    return "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT"


def _operator_next_action(
    *,
    verdict: str,
    ack_ready: bool,
    returned_receipt_present: bool,
    require_recipient_checkpoint: bool,
    require_gold_path: bool,
) -> str:
    if verdict == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT":
        return "Wait for returned share-safe receipts and one CONFIRMED acknowledgement, then rerun this sequence."
    if verdict == "RECIPIENT_INSTALL_CONFIRMED":
        return "Wait for the gold-path and MCP receipts before claiming the gold path."
    if verdict == "RECIPIENT_GOLD_PATH_CONFIRMED":
        return "Collect controlled feedback before any next recipient."
    if returned_receipt_present and not ack_ready:
        return "Do not record recipient proof yet. Put exactly one CONFIRMED line in recipient-ack-private.txt, then rerun."
    if returned_receipt_present:
        return "Fix missing or invalid returned share-safe receipt files, then rerun this sequence."
    if require_recipient_checkpoint or require_gold_path:
        return "Do not claim recipient proof yet. Collect the required ack and share-safe receipts, then rerun."
    return "Do not claim the send is recorded. Provide --sent-at-utc only after the human manual send actually happened."


RETURNED_RECEIPT_NAMES = (
    INSTALL_SHARE_RECEIPT_NAME,
    GOLD_PATH_SHARE_RECEIPT_NAME,
    MCP_OPERABILITY_RECEIPT_NAME,
)


def _human_next_steps(
    *,
    verdict: str,
    sent_at_utc: str | None,
    ack_status: dict[str, Any],
    returned_receipts: dict[str, dict[str, Any]],
    require_recipient_checkpoint: bool,
    require_gold_path: bool,
    operator_next_action: str,
) -> list[str]:
    steps: list[str] = []
    if not sent_at_utc:
        steps.extend(
            [
                "Do not run post-send evidence recording before the manual send actually happened.",
                "Replace <real-sent-at-utc> with the real UTC timestamp from the manual send.",
            ]
        )
    if verdict == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT":
        steps.extend(
            [
                "Wait for the recipient to return share-safe install, gold path, and MCP operability receipts.",
                "Put returned receipts in returned-receipts/ using the expected filenames.",
                "Put exactly one CONFIRMED line in recipient-ack-private.txt after the recipient confirms.",
            ]
        )
    elif verdict == "RECIPIENT_INSTALL_CONFIRMED":
        steps.append("Wait for cambrian_gold_path_share_receipt.json and mcp_operability_receipt.json before claiming gold path.")
    elif verdict == "RECIPIENT_GOLD_PATH_CONFIRMED":
        steps.append("Collect controlled feedback before sending to another recipient.")
    else:
        if ack_status.get("status") != "ready" and (require_recipient_checkpoint or require_gold_path or _any_receipt_requested(returned_receipts)):
            steps.append("Put exactly one CONFIRMED line in recipient-ack-private.txt.")
        missing = _missing_requested_returned_receipts(returned_receipts)
        if missing:
            steps.append("Add missing returned receipt files: " + ", ".join(missing) + ".")
        if require_recipient_checkpoint and not missing:
            steps.append("Rerun after the required acknowledgement and returned receipts are present.")
        if require_gold_path:
            steps.append("Gold path confirmation requires install, gold path, and MCP operability receipts.")
    if operator_next_action:
        steps.append(operator_next_action)
    return _dedupe_strings(steps)


def _any_receipt_requested(returned_receipts: dict[str, dict[str, Any]]) -> bool:
    return any(item.get("requested") is True for item in returned_receipts.values() if isinstance(item, dict))


def _missing_requested_returned_receipts(returned_receipts: dict[str, dict[str, Any]]) -> list[str]:
    return [
        name
        for name, item in returned_receipts.items()
        if isinstance(item, dict) and item.get("requested") is True and item.get("present") is not True
    ]


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _private_ack_status(workspace: Path) -> dict[str, Any]:
    path = workspace / "recipient-ack-private.txt"
    if not path.is_file():
        return _private_status("missing")
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return _private_status("unreadable")
    stripped = text.strip()
    if not stripped:
        return _private_status("empty")
    if stripped == ACK_PLACEHOLDER:
        return _private_status("placeholder")
    non_empty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    confirmed = len(non_empty_lines) == 1 and non_empty_lines[0] == ACK_CONFIRMED_REPLY
    if not confirmed:
        result = _private_status("unconfirmed")
        result["confirmed_reply_present"] = ACK_CONFIRMED_REPLY in non_empty_lines
        result["exactly_one_acknowledgement"] = len(non_empty_lines) == 1
        return result
    return {
        "file": "recipient-ack-private.txt",
        "status": "ready",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "confirmed_reply_present": True,
        "exactly_one_acknowledgement": True,
        "raw_value_included": False,
        "local_path_included": False,
    }


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


def _ack_step_result(ack_status: dict[str, Any]) -> dict[str, Any]:
    if ack_status.get("status") == "ready":
        return _step_result("pass", "RECIPIENT_ACK_READY", [])
    return _step_result("waiting", "WAITING_FOR_RECIPIENT", [str(ack_status.get("status") or "missing")])


def _ack_summary(ack_status: dict[str, Any], *, next_action: str) -> dict[str, Any]:
    return {
        "file": "recipient-ack-private.txt",
        "status": str(ack_status.get("status") or "missing"),
        "sha256_present": _looks_like_sha256(ack_status.get("sha256")),
        "confirmed_reply_present": ack_status.get("confirmed_reply_present") is True,
        "exactly_one_acknowledgement": ack_status.get("exactly_one_acknowledgement") is True,
        "raw_private_values_included": False,
        "local_paths_included": False,
        "next_action": next_action,
    }


def _returned_receipt_summary(path: Path | None) -> dict[str, Any]:
    requested = path is not None
    present = _path_is_file(path)
    return {
        "requested": requested,
        "present": present,
        "status": "present" if present else "missing" if requested else "absent",
        "file": path.name if present and path is not None else None,
        "sha256": _file_sha256(path) if present and path is not None else None,
        "raw_path_included": False,
    }


def _default_returned_receipt(workspace: Path, explicit: Path | None, name: str) -> Path | None:
    if explicit is not None:
        return explicit
    candidate = workspace / RETURNED_RECEIPT_DIR_NAME / name
    return candidate if candidate.is_file() else None


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    ready = bool(checks) and all(value is True for value in checks.values())
    release = _dict(payload, "release_bundle")
    body_hash = payload.get("post_send_sequence_receipt_body_sha256")
    ack_summary = _dict(payload, "ack_summary")
    recipient_checkpoint_gate = _dict(_dict(payload, "gate_receipts"), "recipient_checkpoint")
    recipient_checkpoint_boundary = _dict(recipient_checkpoint_gate, "dispatch_copy_paste_message_policy")
    blocking_summary = _dict(payload, "blocking_summary")
    human_next_steps = (
        blocking_summary.get("human_next_steps")
        if isinstance(blocking_summary.get("human_next_steps"), list)
        else []
    )
    return {
        "schema_version_present": payload.get("schema_version") == POST_SEND_SEQUENCE_SCHEMA_VERSION,
        "status_matches_checks": payload.get("status") == ("pass" if ready else "fail"),
        "verdict_matches_checks": payload.get("verdict") == _sequence_verdict(
            ready=ready,
            checkpoint_verdict=_dict(_dict(payload, "gate_receipts"), "recipient_checkpoint").get("verdict"),
        )
        or payload.get("verdict") == "SENT_ONE_RECORDED_WAITING_FOR_RECIPIENT",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "release_bundle_hash_present": _looks_like_sha256(release.get("sha256")),
        "ack_summary_safe": ack_summary.get("raw_private_values_included") is False
        and ack_summary.get("local_paths_included") is False,
        "human_next_steps_controlled": bool(human_next_steps)
        and all(
            isinstance(item, str)
            and item
            and "\n" not in item
            and str(ROOT) not in item
            and str(Path.home()) not in item
            for item in human_next_steps
        ),
        "returned_receipt_names_controlled": blocking_summary.get("required_returned_receipts")
        == list(RETURNED_RECEIPT_NAMES),
        "ack_file_named": blocking_summary.get("ack_file") == "recipient-ack-private.txt",
        "manual_dispatch_only": _dict(payload, "policy").get("script_sends_to_recipient") is False
        and _dict(payload, "policy").get("manual_operator_dispatch_required") is True,
        "raw_private_values_omitted": _dict(payload, "policy").get("raw_private_values_in_receipt") is False,
        "local_paths_omitted": _dict(payload, "policy").get("local_paths_in_receipt") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "recipient_checkpoint_copy_paste_boundary_safe": _checkpoint_copy_paste_boundary_ready(
            recipient_checkpoint_boundary
        ),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _step_result(status: str, verdict: Any, failed_checks: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "verdict": verdict if isinstance(verdict, str) else "missing_or_invalid",
        "failed_checks": sorted(str(item) for item in failed_checks),
    }


def _blocked_hint(payload: dict[str, Any]) -> str:
    summary = _dict(payload, "blocking_summary")
    blocked_checks = summary.get("blocked_checks") if isinstance(summary.get("blocked_checks"), list) else []
    ack = _dict(payload, "ack_summary")
    returned = payload.get("returned_receipts") if isinstance(payload.get("returned_receipts"), dict) else {}
    missing_requested = _missing_requested_returned_receipts(
        {str(name): item for name, item in returned.items() if isinstance(item, dict)}
    )
    human_next_steps = (
        summary.get("human_next_steps")
        if isinstance(summary.get("human_next_steps"), list)
        else []
    )
    return (
        "post-send sequence blocked checks: "
        + ", ".join(str(item) for item in blocked_checks)
        + "; recipient-ack-private.txt="
        + str(ack.get("status"))
        + "; missing_returned_receipts: "
        + (", ".join(missing_requested) if missing_requested else "none")
        + "; next_steps: "
        + " | ".join(str(item) for item in human_next_steps)
        + "; next_action: "
        + str(summary.get("next_action"))
    )


def _assert_shareable_receipt_file(path: Path, workspace: Path) -> None:
    text = path.read_text(encoding="utf-8")
    leaked = [item for item in (str(ROOT), str(Path.home()), str(workspace)) if item and item in text]
    if leaked:
        raise InstallKitFirstRecipientPostSendSequenceError("post-send sequence receipt leaked private material.")


def _release_bundle_sha256(dist: Path) -> str | None:
    path = dist / RELEASE_BUNDLE_NAME
    return _file_sha256(path) if path.is_file() else None


def _body_hash(payload: dict[str, Any] | None, key: str) -> str | None:
    value = payload.get(key) if isinstance(payload, dict) else None
    return str(value) if _looks_like_sha256(value) else None


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    try:
        return _read_json(path)
    except Exception:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitFirstRecipientPostSendSequenceError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "post_send_sequence_receipt_body_sha256", "post_send_sequence_receipt_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _path_is_file(path: Path | None) -> bool:
    if path is None:
        return False
    try:
        return path.is_file()
    except OSError:
        return False


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _error_code(exc: Exception) -> str:
    return exc.__class__.__name__


def _safe_error_codes(exc: Exception) -> list[str]:
    codes = [_error_code(exc)]
    message = str(exc).lower()
    if "current artifact" in message or "current artifacts" in message:
        codes.append("release_current_artifacts_match_dispatch")
    return _dedupe_strings(codes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Cambrian install-kit first-recipient post-send sequence.")
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--sent-at-utc", default=None)
    parser.add_argument("--install-share-receipt", type=Path, default=None)
    parser.add_argument("--gold-path-share-receipt", type=Path, default=None)
    parser.add_argument("--mcp-operability-receipt", type=Path, default=None)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--require-recipient-checkpoint", action="store_true")
    parser.add_argument("--require-gold-path", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing post-send sequence receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_post_send_sequence_receipt_file(args.verify_receipt, require_recorded=False)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit first-recipient post-send sequence receipt verification: %s", exc)
            return 1
        logger.info("[PASS] install kit first-recipient post-send sequence receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["post_send_sequence_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_post_send_sequence(
            workspace_dir=args.workspace_dir,
            output_dir=args.output_dir,
            sent_at_utc=args.sent_at_utc,
            install_share_receipt=args.install_share_receipt,
            gold_path_share_receipt=args.gold_path_share_receipt,
            mcp_operability_receipt=args.mcp_operability_receipt,
            receipt_path=args.receipt,
            require_recipient_checkpoint=bool(args.require_recipient_checkpoint),
            require_gold_path=bool(args.require_gold_path),
            skip_verify=bool(args.skip_verify),
        )
    except InstallKitFirstRecipientPostSendSequenceError as exc:
        logger.error("[FAIL] install kit first-recipient post-send sequence: %s", exc)
        return 1

    logger.info("[PASS] install kit first-recipient post-send sequence")
    logger.info("verdict: %s", result["verdict"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    logger.info("release_bundle_sha256: %s", result["release_bundle_sha256"])
    logger.info("next_action: %s", result["operator_next_action"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
