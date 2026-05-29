"""Run the operator-side first-recipient pre-send sequence without sending."""

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

from scripts.audit_external_alpha_operator_send_bypass import (  # noqa: E402
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
    audit_operator_send_bypass,
)
from scripts.audit_external_alpha_send_chain import audit_send_chain  # noqa: E402
from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_first_recipient_manual_send_go import (  # noqa: E402
    MANUAL_SEND_GO_RECEIPT_NAME,
    check_first_recipient_manual_send_go,
    verify_first_recipient_manual_send_go_receipt_file,
)
from scripts.check_external_alpha_first_recipient_send_preflight import (  # noqa: E402
    PREFLIGHT_RECEIPT_NAME,
    check_first_recipient_send_preflight,
    verify_first_recipient_send_preflight_receipt_file,
)
from scripts.prepare_external_alpha_first_recipient_send_workspace import (  # noqa: E402
    FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME,
    prepare_first_recipient_send_workspace,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import PACKET_JSON_NAME  # noqa: E402
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR  # noqa: E402
from scripts.smoke_external_alpha_manual_send_go_rehearsal import smoke_manual_send_go_rehearsal  # noqa: E402


PRE_SEND_SEQUENCE_SCHEMA_VERSION = "external_alpha_first_recipient_pre_send_sequence_v0_1"
PRE_SEND_SEQUENCE_RECEIPT_NAME = "external-alpha-first-recipient-pre-send-sequence-receipt.json"
DEFAULT_SEQUENCE_WORKSPACE_DIR = DEFAULT_PRIVATE_WORKSPACE_DIR
DEFAULT_OPERATOR_PACKET_PATH = DEFAULT_OUTPUT_DIR / PACKET_JSON_NAME

logger = logging.getLogger(__name__)


class FirstRecipientPreSendSequenceError(RuntimeError):
    """First-recipient pre-send sequence failed or is blocked."""


def check_first_recipient_pre_send_sequence(
    workspace_dir: Path = DEFAULT_SEQUENCE_WORKSPACE_DIR,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    operator_packet_path: Path | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Run all safe pre-send gates and return GO only when a human may send."""
    workspace_dir = workspace_dir.resolve()
    output_dir = output_dir.resolve()
    operator_packet_path = (operator_packet_path or output_dir / PACKET_JSON_NAME).resolve()

    workspace_result, workspace_payload = _run_workspace_step(workspace_dir, operator_packet_path)
    preflight_result, preflight_payload = _run_preflight_step(workspace_dir, operator_packet_path)
    bypass_result, bypass_payload = _run_bypass_step(output_dir, workspace_dir)
    final_audit_result, final_audit_payload = _run_final_audit_step(output_dir)
    manual_go_result, manual_go_payload = _run_manual_go_step(workspace_dir, output_dir, operator_packet_path)

    payload = _sequence_payload(
        workspace_payload=workspace_payload,
        preflight_payload=preflight_payload,
        bypass_payload=bypass_payload,
        final_audit_payload=final_audit_payload,
        manual_go_payload=manual_go_payload,
        step_results={
            "first_recipient_workspace": workspace_result,
            "preflight": preflight_result,
            "operator_bypass_audit": bypass_result,
            "final_send_chain_audit": final_audit_result,
            "manual_send_go": manual_go_result,
        },
    )

    receipt_path = (receipt_path or workspace_dir / PRE_SEND_SEQUENCE_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_first_recipient_pre_send_sequence_receipt_file(receipt_path, require_ready=False)
    _assert_shareable_receipt_file(receipt_path, workspace_dir)

    failed = [name for name, passed in payload["checks"].items() if passed is not True]
    if failed:
        raise FirstRecipientPreSendSequenceError(_blocked_hint(payload))

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["pre_send_sequence_receipt_body_sha256"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def verify_first_recipient_pre_send_sequence_receipt_file(
    path: Path,
    *,
    require_ready: bool = True,
) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_pre_send_sequence_receipt_payload(payload, require_ready=require_ready)
    return payload


def verify_first_recipient_pre_send_sequence_receipt_payload(
    payload: dict[str, Any],
    *,
    require_ready: bool = True,
) -> None:
    if payload.get("schema_version") != PRE_SEND_SEQUENCE_SCHEMA_VERSION:
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt schema_version mismatch.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt checks are missing.")
    ready = all(value is True for value in checks.values())
    expected_status = "pass" if ready else "fail"
    expected_verdict = "READY_TO_MANUALLY_SEND_ONE" if ready else "BLOCKED_BEFORE_MANUAL_SEND"
    if payload.get("status") != expected_status:
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt status does not match checks.")
    if payload.get("verdict") != expected_verdict:
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt verdict does not match checks.")
    if payload.get("safe_to_share") is not True:
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt must be safe_to_share.")
    receipt_checks = payload.get("pre_send_sequence_receipt_checks")
    recalculated = _receipt_checks(payload)
    if receipt_checks != recalculated:
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt self-checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise FirstRecipientPreSendSequenceError(
            "pre-send sequence receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("pre_send_sequence_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt body hash mismatch.")
    if require_ready and not ready:
        failed = [name for name, passed in checks.items() if passed is not True]
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt is blocked: " + ", ".join(failed))


def _run_workspace_step(workspace_dir: Path, operator_packet_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = prepare_first_recipient_send_workspace(
            workspace_dir,
            operator_packet_path=operator_packet_path,
        )
        payload = _load_json(workspace_dir / FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME)
        return _step_result("pass", result.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001 - produce a controlled operator receipt.
        return _step_result("fail", "workspace_not_ready", [_error_code(exc)]), _load_json_if_exists(
            workspace_dir / FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME
        )


def _run_preflight_step(workspace_dir: Path, operator_packet_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        check_first_recipient_send_preflight(workspace_dir, operator_packet_path=operator_packet_path)
    except Exception:
        pass
    payload = _load_preflight(workspace_dir / PREFLIGHT_RECEIPT_NAME)
    if payload is None:
        return _step_result("fail", "missing_or_invalid", ["preflight_receipt_missing_or_invalid"]), None
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed = [name for name, passed in checks.items() if passed is not True]
    status = "pass" if not failed and payload.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY" else "fail"
    return _step_result(status, payload.get("verdict"), failed), payload


def _run_bypass_step(output_dir: Path, workspace_dir: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        audit_operator_send_bypass(output_dir, workspace_dir=workspace_dir)
        payload = _load_json(output_dir / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME)
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "missing_or_invalid", [_error_code(exc)]), _load_json_if_exists(
            output_dir / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME
        )


def _run_final_audit_step(output_dir: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        smoke_manual_send_go_rehearsal(output_dir)
        payload = audit_send_chain(output_dir)
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "missing_or_invalid", [_error_code(exc)]), None


def _run_manual_go_step(
    workspace_dir: Path,
    output_dir: Path,
    operator_packet_path: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        check_first_recipient_manual_send_go(
            workspace_dir,
            output_dir=output_dir,
            operator_packet_path=operator_packet_path,
        )
    except Exception:
        pass
    payload = _load_manual_go(workspace_dir / MANUAL_SEND_GO_RECEIPT_NAME)
    if payload is None:
        return _step_result("fail", "missing_or_invalid", ["manual_go_receipt_missing_or_invalid"]), None
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed = [name for name, passed in checks.items() if passed is not True]
    status = "pass" if not failed and payload.get("verdict") == "GO_TO_MANUALLY_SEND_ONE" else "fail"
    return _step_result(status, payload.get("verdict"), failed), payload


def _sequence_payload(
    *,
    workspace_payload: dict[str, Any] | None,
    preflight_payload: dict[str, Any] | None,
    bypass_payload: dict[str, Any] | None,
    final_audit_payload: dict[str, Any] | None,
    manual_go_payload: dict[str, Any] | None,
    step_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    release_hash = _first_hash(
        _release_hash(manual_go_payload),
        _release_hash(preflight_payload),
        _release_hash(bypass_payload),
        final_audit_payload.get("archive_sha256") if isinstance(final_audit_payload, dict) else None,
        _release_hash(workspace_payload),
    )
    release_file_count = _first_value(
        _dict(manual_go_payload, "release").get("file_count"),
        _dict(preflight_payload, "release").get("file_count"),
        _dict(bypass_payload, "release").get("file_count"),
        _dict(workspace_payload, "release").get("file_count"),
    )
    manual_policy = _dict(manual_go_payload, "policy")
    preflight_policy = _dict(preflight_payload, "policy")
    release_hashes = [
        _release_hash(workspace_payload),
        _release_hash(preflight_payload),
        _release_hash(bypass_payload),
        final_audit_payload.get("archive_sha256") if isinstance(final_audit_payload, dict) else None,
        _release_hash(manual_go_payload),
    ]
    present_hashes = [value for value in release_hashes if isinstance(value, str)]
    checks = {
        "first_recipient_workspace_ready": step_results["first_recipient_workspace"].get("status") == "pass",
        "preflight_ready": step_results["preflight"].get("status") == "pass",
        "operator_bypass_audit_ready": step_results["operator_bypass_audit"].get("status") == "pass",
        "final_send_chain_ready": step_results["final_send_chain_audit"].get("status") == "pass",
        "manual_send_go_ready": step_results["manual_send_go"].get("status") == "pass",
        "release_hashes_match": bool(present_hashes)
        and len(set(present_hashes)) == 1
        and _looks_like_sha256(present_hashes[0]),
        "manual_dispatch_only": manual_policy.get("script_sends_to_recipient") is False
        and manual_policy.get("manual_operator_dispatch_required") is True
        and preflight_policy.get("script_sends_to_recipient") is False
        and preflight_policy.get("manual_operator_dispatch_required") is True,
        "one_recipient_policy_locked": manual_policy.get("max_recipients") == 1
        and preflight_policy.get("max_recipients") == 1,
        "pre_send_sequence_only": True,
        "script_does_not_send_to_recipient": True,
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
    }
    ready = all(checks.values())
    blocked_steps = [name for name, result in step_results.items() if result.get("status") != "pass"]
    required_private_files = _required_private_file_summary(preflight_payload)
    blocked_checks = [name for name, passed in checks.items() if passed is not True]
    operator_next_action = _operator_next_action(
        ready=ready,
        checks=checks,
        required_private_files=required_private_files,
    )
    payload: dict[str, Any] = {
        "schema_version": PRE_SEND_SEQUENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if ready else "fail",
        "verdict": "READY_TO_MANUALLY_SEND_ONE" if ready else "BLOCKED_BEFORE_MANUAL_SEND",
        "safe_to_share": True,
        "release": {
            "zip_file": RELEASE_SLUG + ".zip",
            "archive_sha256": release_hash,
            "file_count": release_file_count,
        },
        "step_results": step_results,
        "gate_receipts": {
            "first_recipient_workspace": {
                "file": FIRST_RECIPIENT_SEND_WORKSPACE_RECEIPT_NAME,
                "verdict": workspace_payload.get("verdict") if isinstance(workspace_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(
                    workspace_payload,
                    "first_recipient_send_workspace_receipt_body_sha256",
                ),
            },
            "preflight": {
                "file": PREFLIGHT_RECEIPT_NAME,
                "verdict": preflight_payload.get("verdict") if isinstance(preflight_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(
                    preflight_payload,
                    "first_recipient_send_preflight_receipt_body_sha256",
                ),
            },
            "operator_send_bypass_audit": {
                "file": OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
                "verdict": bypass_payload.get("verdict") if isinstance(bypass_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(bypass_payload, "operator_send_bypass_audit_body_sha256"),
            },
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
            "manual_send_go": {
                "file": MANUAL_SEND_GO_RECEIPT_NAME,
                "verdict": manual_go_payload.get("verdict")
                if isinstance(manual_go_payload, dict)
                else "missing_or_invalid",
                "body_sha256": _body_hash(manual_go_payload, "manual_send_go_receipt_body_sha256"),
            },
        },
        "blocked_steps": blocked_steps,
        "blocking_summary": {
            "blocked_steps": blocked_steps,
            "blocked_checks": blocked_checks,
            "required_private_files": required_private_files,
            "all_required_private_files_ready": all(item["status"] == "ready" for item in required_private_files),
            "next_action": operator_next_action,
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "pre_send_sequence_only": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "operator_next_action": operator_next_action,
        "checks": checks,
    }
    payload["pre_send_sequence_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["pre_send_sequence_receipt_checks"] = _receipt_checks(payload)
    return payload


def _step_result(status: str, verdict: Any, failed_checks: list[str]) -> dict[str, Any]:
    return {
        "status": status,
        "verdict": verdict if isinstance(verdict, str) else "missing_or_invalid",
        "failed_checks": sorted(failed_checks),
    }


def _required_private_file_summary(preflight_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    allowed_statuses = {"ready", "missing", "empty", "placeholder", "unreadable"}
    private_workspace = _dict(preflight_payload, "private_workspace")
    source_files = (
        private_workspace.get("required_private_files")
        if isinstance(private_workspace.get("required_private_files"), list)
        else []
    )
    by_name = {
        item.get("file"): item
        for item in source_files
        if isinstance(item, dict) and isinstance(item.get("file"), str)
    }
    result: list[dict[str, Any]] = []
    for filename in ("recipient-private.txt", "operator-dispatch-note-private.md"):
        item = by_name.get(filename, {})
        status = item.get("status")
        if status not in allowed_statuses:
            status = "missing"
        is_recipient = filename == "recipient-private.txt"
        is_operator_note = filename == "operator-dispatch-note-private.md"
        result.append(
            {
                "file": filename,
                "status": status,
                "required_before_manual_send": True,
                "sha256_present": _looks_like_sha256(item.get("sha256")),
                "minimum_signal_present": bool(
                    is_recipient
                    and status == "ready"
                    and isinstance(item.get("byte_count"), int)
                    and item.get("byte_count") >= 8
                ),
                "exactly_one_recipient": bool(is_recipient and item.get("exactly_one_recipient") is True),
                "mentions_channel": bool(is_operator_note and item.get("mentions_channel") is True),
                "contains_release_hash": bool(is_operator_note and item.get("contains_release_hash") is True),
            }
        )
    return result


def _operator_next_action(
    *,
    ready: bool,
    checks: dict[str, bool],
    required_private_files: list[dict[str, Any]],
) -> str:
    if ready:
        return "Manually send the ZIP and copy-paste message to exactly one recipient."
    private_files_ready = bool(required_private_files) and all(
        item.get("status") == "ready" for item in required_private_files if isinstance(item, dict)
    )
    if not private_files_ready or checks.get("preflight_ready") is not True:
        if checks.get("final_send_chain_ready") is not True:
            return (
                "Do not send. Fill recipient-private.txt and operator-dispatch-note-private.md, then rerun this "
                "sequence; the final release chain also needs the current manual-send GO rehearsal and final audit."
            )
        return "Do not send. Fill recipient-private.txt and operator-dispatch-note-private.md, then rerun this sequence."
    if checks.get("operator_bypass_audit_ready") is not True:
        return "Do not send. Refresh the operator send-bypass audit, then rerun this sequence."
    if checks.get("final_send_chain_ready") is not True:
        return "Do not send. Run the current manual-send GO rehearsal and final send-chain audit, then rerun this sequence."
    if checks.get("manual_send_go_ready") is not True:
        return "Do not send. Rerun the manual-send GO gate after private preflight and final chain are ready."
    return "Do not send. Resolve the blocked pre-send checks, then rerun this sequence."


def _load_preflight(path: Path) -> dict[str, Any] | None:
    try:
        return verify_first_recipient_send_preflight_receipt_file(path, require_ready=False)
    except Exception:
        return _load_json_if_exists(path)


def _load_manual_go(path: Path) -> dict[str, Any] | None:
    try:
        return verify_first_recipient_manual_send_go_receipt_file(path, require_go=False)
    except Exception:
        return _load_json_if_exists(path)


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    try:
        return _load_json(path)
    except Exception:
        return None


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    release = _dict(payload, "release")
    gate_receipts = _dict(payload, "gate_receipts")
    preflight = _dict(gate_receipts, "preflight")
    bypass = _dict(gate_receipts, "operator_send_bypass_audit")
    manual_go = _dict(gate_receipts, "manual_send_go")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    blocking_summary = _dict(payload, "blocking_summary")
    required_private_files = (
        blocking_summary.get("required_private_files")
        if isinstance(blocking_summary.get("required_private_files"), list)
        else []
    )
    ready = bool(checks) and all(value is True for value in checks.values())
    body_hash = payload.get("pre_send_sequence_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PRE_SEND_SEQUENCE_SCHEMA_VERSION,
        "status_matches_checks": (payload.get("status") == "pass") is ready,
        "verdict_matches_checks": payload.get("verdict")
        == ("READY_TO_MANUALLY_SEND_ONE" if ready else "BLOCKED_BEFORE_MANUAL_SEND"),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "preflight_receipt_body_hash_present_or_blocked": preflight.get("verdict")
        != "FIRST_RECIPIENT_PRE_SEND_READY"
        or _looks_like_sha256(preflight.get("body_sha256")),
        "operator_bypass_body_hash_present": _looks_like_sha256(bypass.get("body_sha256")),
        "manual_go_receipt_body_hash_present_or_blocked": manual_go.get("verdict")
        != "GO_TO_MANUALLY_SEND_ONE"
        or _looks_like_sha256(manual_go.get("body_sha256")),
        "blocking_summary_private_files_named": {item.get("file") for item in required_private_files}
        == {"recipient-private.txt", "operator-dispatch-note-private.md"},
        "blocking_summary_statuses_controlled": all(
            isinstance(item, dict)
            and item.get("status") in {"ready", "missing", "empty", "placeholder", "unreadable"}
            and isinstance(item.get("sha256_present"), bool)
            and isinstance(item.get("minimum_signal_present"), bool)
            and isinstance(item.get("exactly_one_recipient"), bool)
            and isinstance(item.get("mentions_channel"), bool)
            and isinstance(item.get("contains_release_hash"), bool)
            for item in required_private_files
        ),
        "raw_private_values_omitted": _dict(payload, "policy").get("raw_private_values_in_receipt") is False,
        "local_paths_omitted": _dict(payload, "policy").get("local_paths_in_receipt") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "manual_dispatch_only": _dict(payload, "policy").get("script_sends_to_recipient") is False
        and _dict(payload, "policy").get("manual_operator_dispatch_required") is True,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _assert_shareable_receipt_file(path: Path, workspace_dir: Path) -> None:
    text = path.read_text(encoding="utf-8")
    private_values = []
    for filename in ("recipient-private.txt", "operator-dispatch-note-private.md"):
        private_values.append(_read_text_if_exists(workspace_dir / filename))
    forbidden = [
        str(ROOT),
        str(Path.home()),
        str(workspace_dir),
        "Recipient identifier/contact goes here",
        "Record the private channel",
        "<private-send-channel>",
        *[value for value in private_values if value],
    ]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise FirstRecipientPreSendSequenceError("pre-send sequence receipt leaked local path or raw private text.")


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
    summary = _dict(payload, "blocking_summary")
    private_files = (
        summary.get("required_private_files")
        if isinstance(summary.get("required_private_files"), list)
        else []
    )
    private_statuses = [
        _private_status_hint(item)
        for item in private_files
        if isinstance(item, dict) and item.get("file")
    ]
    parts = ["first-recipient pre-send sequence blocked checks: " + ", ".join(failed)]
    if private_statuses:
        parts.append("required private files: " + ", ".join(private_statuses))
    next_action = summary.get("next_action")
    if isinstance(next_action, str) and next_action:
        parts.append("next: " + next_action)
    return "; ".join(parts)


def _private_status_hint(item: dict[str, Any]) -> str:
    name = item.get("file")
    status = item.get("status")
    details: list[str] = []
    if name == "recipient-private.txt" and item.get("minimum_signal_present") is not True:
        details.append("minimum_signal=false")
    if name == "recipient-private.txt" and item.get("exactly_one_recipient") is not True:
        details.append("exactly_one_recipient=false")
    if name == "operator-dispatch-note-private.md":
        if item.get("mentions_channel") is not True:
            details.append("mentions_channel=false")
        if item.get("contains_release_hash") is not True:
            details.append("contains_release_hash=false")
    suffix = "" if not details else " (" + ", ".join(details) + ")"
    return f"{name}={status}{suffix}"


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "pre_send_sequence_receipt_body_sha256", "pre_send_sequence_receipt_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _error_code(exc: Exception) -> str:
    return exc.__class__.__name__


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise FirstRecipientPreSendSequenceError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise FirstRecipientPreSendSequenceError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FirstRecipientPreSendSequenceError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the first-recipient external alpha pre-send sequence.")
    parser.add_argument("--workspace-dir", default=str(DEFAULT_SEQUENCE_WORKSPACE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--operator-packet", default=None)
    parser.add_argument("--receipt", default=None, help="Optional share-safe pre-send sequence receipt JSON path.")
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing ready pre-send sequence receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_pre_send_sequence_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - operator-facing reason.
            logger.error("[FAIL] external alpha first-recipient pre-send sequence receipt verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha first-recipient pre-send sequence receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["pre_send_sequence_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_pre_send_sequence(
            Path(args.workspace_dir),
            output_dir=Path(args.output_dir),
            operator_packet_path=Path(args.operator_packet) if args.operator_packet else None,
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - operator-facing reason.
        logger.error("[FAIL] external alpha first-recipient pre-send sequence: %s", exc)
        return 1

    logger.info("[PASS] external alpha first-recipient pre-send sequence")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
