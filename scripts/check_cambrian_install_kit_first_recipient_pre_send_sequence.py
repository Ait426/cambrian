"""Run the Cambrian install-kit first-recipient pre-send sequence without sending."""

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

from scripts.audit_cambrian_install_kit_operator_send_bypass import (  # noqa: E402
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
    audit_install_kit_operator_send_bypass,
    verify_operator_send_bypass_audit_file,
)
from scripts.check_cambrian_install_kit_first_recipient_operator_status import (  # noqa: E402
    OPERATOR_STATUS_MD_NAME,
    OPERATOR_STATUS_READY_RECEIPT_NAME,
    OPERATOR_STATUS_RECEIPT_NAME,
    check_first_recipient_operator_status,
    verify_first_recipient_operator_status_receipt_file,
)
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import (  # noqa: E402
    DEFAULT_WORKSPACE_DIR,
    WORKSPACE_RECEIPT_NAME,
    prepare_first_recipient_workspace,
    verify_first_recipient_workspace_receipt_file,
)
from scripts.prepare_cambrian_install_kit_release import RELEASE_BUNDLE_NAME  # noqa: E402
from scripts.smoke_cambrian_install_kit_manual_send_go_rehearsal import (  # noqa: E402
    MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
    smoke_manual_send_go_rehearsal,
    verify_manual_send_go_rehearsal_receipt_file,
)


PRE_SEND_SEQUENCE_SCHEMA_VERSION = "cambrian_install_kit_first_recipient_pre_send_sequence_v0_1"
PRE_SEND_SEQUENCE_RECEIPT_NAME = "cambrian-install-kit-first-recipient-pre-send-sequence-receipt.json"

logger = logging.getLogger(__name__)


class InstallKitFirstRecipientPreSendSequenceError(RuntimeError):
    """Install-kit first-recipient pre-send sequence failed or is blocked."""


def check_first_recipient_pre_send_sequence(
    workspace_dir: Path | None = None,
    *,
    output_dir: Path | None = None,
    receipt_path: Path | None = None,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Run the safe first-recipient pre-send gates and stop before any real send."""
    workspace = (workspace_dir or DEFAULT_WORKSPACE_DIR).resolve()
    dist = (output_dir or ROOT / "dist").resolve()

    workspace_result, workspace_payload = _run_workspace_step(workspace, dist)
    operator_result, operator_payload = _run_operator_status_step(workspace, dist)
    bypass_result, bypass_payload = _run_bypass_step(workspace, dist, skip_verify=skip_verify)
    rehearsal_result, rehearsal_payload = _run_rehearsal_step(dist, skip_verify=skip_verify)

    payload = _sequence_payload(
        workspace_payload=workspace_payload,
        operator_payload=operator_payload,
        bypass_payload=bypass_payload,
        rehearsal_payload=rehearsal_payload,
        step_results={
            "first_recipient_workspace": workspace_result,
            "operator_status": operator_result,
            "operator_send_bypass_audit": bypass_result,
            "manual_send_go_rehearsal": rehearsal_result,
        },
    )
    target = (receipt_path or workspace / PRE_SEND_SEQUENCE_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, payload)
    verify_first_recipient_pre_send_sequence_receipt_file(target, require_ready=False)
    _assert_shareable_receipt_file(target, workspace)

    failed = [name for name, passed in payload["checks"].items() if passed is not True]
    if failed:
        raise InstallKitFirstRecipientPreSendSequenceError(_blocked_hint(payload))

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(target),
        "receipt_body_sha256": payload["pre_send_sequence_receipt_body_sha256"],
        "release_bundle_sha256": payload["release_bundle"]["sha256"],
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
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt schema_version mismatch.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt checks are missing.")
    ready = all(value is True for value in checks.values())
    if payload.get("status") != ("pass" if ready else "fail"):
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt status does not match checks.")
    if payload.get("verdict") != ("READY_TO_MANUALLY_SEND_ONE" if ready else "BLOCKED_BEFORE_MANUAL_SEND"):
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt verdict does not match checks.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt must be safe_to_share.")
    recalculated = _receipt_checks(payload)
    if payload.get("pre_send_sequence_receipt_checks") != recalculated:
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt self-checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise InstallKitFirstRecipientPreSendSequenceError(
            "pre-send sequence receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("pre_send_sequence_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt body hash mismatch.")
    if require_ready and not ready:
        failed = [name for name, passed in checks.items() if passed is not True]
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt is blocked: " + ", ".join(failed))


def _run_workspace_step(workspace: Path, dist: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = prepare_first_recipient_workspace(workspace_dir=workspace, output_dir=dist)
        payload = verify_first_recipient_workspace_receipt_file(Path(str(result["receipt_json"])))
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001 - keep the operator receipt controlled.
        return _step_result("fail", "workspace_not_ready", [_error_code(exc)]), _load_json_if_exists(
            workspace / WORKSPACE_RECEIPT_NAME
        )


def _run_operator_status_step(workspace: Path, dist: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = check_first_recipient_operator_status(workspace_dir=workspace, output_dir=dist)
        payload = verify_first_recipient_operator_status_receipt_file(Path(str(result["receipt_json"])))
        failed = []
        if payload.get("verdict") != "READY_TO_MANUALLY_SEND_ONE":
            failed.append(str(payload.get("verdict", "operator_status_not_ready")))
        if result.get("ready_receipt_json") is None:
            failed.append("ready_receipt_missing")
        status = "pass" if not failed else "fail"
        return _step_result(status, payload.get("verdict"), failed), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "operator_status_not_ready", [_error_code(exc)]), _load_json_if_exists(
            workspace / OPERATOR_STATUS_RECEIPT_NAME
        )


def _run_bypass_step(
    workspace: Path,
    dist: Path,
    *,
    skip_verify: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = audit_install_kit_operator_send_bypass(
            output_dir=dist,
            workspace_dir=workspace,
            skip_verify=skip_verify,
        )
        payload = verify_operator_send_bypass_audit_file(Path(str(result["receipt_json"])))
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "operator_send_bypass_audit_not_ready", [_error_code(exc)]), _load_json_if_exists(
            dist / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME
        )


def _run_rehearsal_step(
    dist: Path,
    *,
    skip_verify: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        result = smoke_manual_send_go_rehearsal(output_dir=dist, skip_verify=skip_verify)
        payload = verify_manual_send_go_rehearsal_receipt_file(Path(str(result["receipt_json"])))
        return _step_result("pass", payload.get("verdict"), []), payload
    except Exception as exc:  # noqa: BLE001
        return _step_result("fail", "manual_send_go_rehearsal_not_ready", [_error_code(exc)]), _load_json_if_exists(
            dist / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
        )


def _sequence_payload(
    *,
    workspace_payload: dict[str, Any] | None,
    operator_payload: dict[str, Any] | None,
    bypass_payload: dict[str, Any] | None,
    rehearsal_payload: dict[str, Any] | None,
    step_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    release_sha256 = _first_hash(
        _dict(operator_payload, "release_bundle").get("sha256"),
        _dict(workspace_payload, "release_bundle").get("sha256"),
        _dict(rehearsal_payload, "release_bundle").get("sha256"),
    )
    operator_summary = _dict(operator_payload, "operator_status_summary")
    operator_gates = _dict(operator_payload, "operator_gates")
    release_current = _dict(operator_payload, "release_bundle_current_artifacts")
    private_hashes = _dict(operator_payload, "private_hashes")
    release_current_artifacts_match = release_current.get("current_artifacts_match")
    release_current_artifacts_gate_passed = release_current_artifacts_match is not False
    release_hashes = [
        _dict(operator_payload, "release_bundle").get("sha256"),
        _dict(workspace_payload, "release_bundle").get("sha256"),
        _dict(rehearsal_payload, "release_bundle").get("sha256"),
    ]
    present_hashes = [value for value in release_hashes if isinstance(value, str)]
    required_private_files = _required_private_file_summary(operator_payload)
    ready_receipt_file = (
        OPERATOR_STATUS_READY_RECEIPT_NAME
        if operator_payload is not None and operator_payload.get("verdict") == "READY_TO_MANUALLY_SEND_ONE"
        else None
    )
    checks = {
        "first_recipient_workspace_ready": step_results["first_recipient_workspace"].get("status") == "pass",
        "operator_status_ready_to_send": step_results["operator_status"].get("status") == "pass",
        "operator_status_ready_receipt_written": ready_receipt_file == OPERATOR_STATUS_READY_RECEIPT_NAME,
        "operator_status_open_gates_empty": operator_summary.get("open_gate_ids") == [],
        "operator_status_manual_send_allowed": operator_summary.get("manual_send_allowed") is True,
        "operator_status_release_current_artifacts_match": release_current_artifacts_gate_passed,
        "operator_send_bypass_audit_ready": step_results["operator_send_bypass_audit"].get("status") == "pass",
        "manual_send_go_rehearsal_ready": step_results["manual_send_go_rehearsal"].get("status") == "pass",
        "release_hashes_match": bool(present_hashes)
        and len(set(present_hashes)) == 1
        and _looks_like_sha256(present_hashes[0]),
        "one_recipient_policy_locked": operator_gates.get("one_recipient_only") is True
        and operator_gates.get("exactly_one_recipient") is True,
        "pre_send_sequence_only": True,
        "script_does_not_send_to_recipient": True,
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
    }
    ready = all(checks.values())
    blocked_steps = [name for name, result in step_results.items() if result.get("status") != "pass"]
    blocked_checks = [name for name, passed in checks.items() if passed is not True]
    operator_next_action = _operator_next_action(
        ready=ready,
        operator_payload=operator_payload,
        blocked_checks=blocked_checks,
    )
    human_next_steps = _human_next_steps(
        ready=ready,
        required_private_files=required_private_files,
        operator_next_action=operator_next_action,
    )
    payload: dict[str, Any] = {
        "schema_version": PRE_SEND_SEQUENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if ready else "fail",
        "verdict": "READY_TO_MANUALLY_SEND_ONE" if ready else "BLOCKED_BEFORE_MANUAL_SEND",
        "safe_to_share": True,
        "release_bundle": {
            "file": RELEASE_BUNDLE_NAME,
            "sha256": release_sha256,
        },
        "step_results": step_results,
        "gate_receipts": {
            "first_recipient_workspace": {
                "file": WORKSPACE_RECEIPT_NAME,
                "verdict": workspace_payload.get("verdict") if isinstance(workspace_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(workspace_payload, "workspace_receipt_body_sha256"),
            },
            "operator_status": {
                "file": OPERATOR_STATUS_RECEIPT_NAME,
                "status_board_file": OPERATOR_STATUS_MD_NAME,
                "ready_receipt_file": ready_receipt_file,
                "verdict": operator_payload.get("verdict") if isinstance(operator_payload, dict) else "missing_or_invalid",
                "send_state": operator_summary.get("send_state"),
                "manual_send_allowed": operator_summary.get("manual_send_allowed") is True,
                "release_current_artifacts_checked": release_current.get("comparison_applicable") is True,
                "release_current_artifacts_match": release_current_artifacts_match,
                "release_current_artifacts_gate_passed": release_current_artifacts_gate_passed,
                "release_current_artifacts_status": release_current.get("status"),
                "body_sha256": _body_hash(operator_payload, "operator_status_receipt_body_sha256"),
            },
            "operator_send_bypass_audit": {
                "file": OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
                "verdict": bypass_payload.get("verdict") if isinstance(bypass_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(bypass_payload, "operator_send_bypass_audit_body_sha256"),
            },
            "manual_send_go_rehearsal": {
                "file": MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
                "verdict": rehearsal_payload.get("verdict") if isinstance(rehearsal_payload, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(rehearsal_payload, "manual_send_go_rehearsal_receipt_body_sha256"),
            },
        },
        "blocked_steps": blocked_steps,
        "blocking_summary": {
            "blocked_steps": blocked_steps,
            "blocked_checks": blocked_checks,
            "open_gate_ids": _safe_list(operator_summary.get("open_gate_ids")),
            "operator_status_board_file": OPERATOR_STATUS_MD_NAME,
            "required_private_files": required_private_files,
            "all_required_private_files_ready": all(
                item.get("status") == "ready" for item in required_private_files
            ),
            "next_action": operator_next_action,
            "human_next_steps": human_next_steps,
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "private_hashes_present": {
            "recipient_private_sha256": _looks_like_sha256(private_hashes.get("recipient_private_sha256")),
            "operator_dispatch_note_private_sha256": _looks_like_sha256(
                private_hashes.get("operator_dispatch_note_private_sha256")
            ),
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
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["pre_send_sequence_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["pre_send_sequence_receipt_checks"] = _receipt_checks(payload)
    return payload


def _required_private_file_summary(operator_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    private_files = operator_payload.get("private_files") if isinstance(operator_payload, dict) else []
    by_file = {
        item.get("file"): item
        for item in private_files
        if isinstance(item, dict) and isinstance(item.get("file"), str)
    }
    return [
        _private_file_summary(
            "recipient-private.txt",
            by_file.get("recipient-private.txt", {}),
            required_signals={
                "exactly_one_recipient": True,
                "mentions_channel": False,
                "contains_release_hash": False,
            },
        ),
        _private_file_summary(
            "operator-dispatch-note-private.md",
            by_file.get("operator-dispatch-note-private.md", {}),
            required_signals={
                "exactly_one_recipient": False,
                "mentions_channel": True,
                "contains_release_hash": True,
            },
        ),
    ]


def _private_file_summary(
    file_name: str,
    item: dict[str, Any],
    *,
    required_signals: dict[str, bool],
) -> dict[str, Any]:
    status = item.get("status") if isinstance(item.get("status"), str) else "missing"
    allowed_statuses = {
        "ready",
        "missing",
        "empty",
        "placeholder",
        "unreadable",
        "too_many_lines",
        "missing_private_channel",
        "missing_current_release_hash",
        "waiting_for_confirmed_line",
        "confirmed",
    }
    if status not in allowed_statuses:
        status = "missing"
    return {
        "file": file_name,
        "status": status,
        "required_before_manual_send": True,
        "sha256_present": _looks_like_sha256(item.get("private_sha256")),
        "minimum_signal_present": bool(
            status == "ready"
            or (
                file_name == "recipient-private.txt"
                and _looks_like_sha256(item.get("private_sha256"))
                and isinstance(item.get("non_empty_line_count"), int)
                and item.get("non_empty_line_count") >= 1
            )
        ),
        "exactly_one_recipient": bool(
            item.get("ready") is True
            and item.get("non_empty_line_count") == 1
            and file_name == "recipient-private.txt"
        ),
        "mentions_channel": bool(item.get("channel_named") is True and file_name == "operator-dispatch-note-private.md"),
        "contains_release_hash": bool(
            item.get("release_hash_named") is True and file_name == "operator-dispatch-note-private.md"
        ),
        "required_signals": required_signals,
    }


def _operator_next_action(
    *,
    ready: bool,
    operator_payload: dict[str, Any] | None,
    blocked_checks: list[str],
) -> str:
    if ready:
        return "Manually send the release bundle to exactly one recipient, then record dispatch with the preserved READY receipt."
    if isinstance(operator_payload, dict) and isinstance(operator_payload.get("operator_next_action"), str):
        return str(operator_payload["operator_next_action"])
    if blocked_checks:
        return "Do not send. Resolve blocked pre-send checks, then rerun this sequence."
    return "Do not send. Rerun this sequence after preparing the private workspace."


def _human_next_steps(
    *,
    ready: bool,
    required_private_files: list[dict[str, Any]],
    operator_next_action: str,
) -> list[str]:
    if ready:
        return [
            "Manually send exactly one release bundle.",
            f"Keep {OPERATOR_STATUS_READY_RECEIPT_NAME} for dispatch and recipient checkpoint.",
            "After the send, record the real UTC send timestamp in the post-send sequence.",
        ]

    steps = [
        "Do not send the release bundle yet.",
        f"Open {OPERATOR_STATUS_MD_NAME} for the safe GO/NO-GO status board.",
    ]
    by_file = {
        str(item.get("file")): item
        for item in required_private_files
        if isinstance(item, dict) and isinstance(item.get("file"), str)
    }
    recipient = by_file.get("recipient-private.txt", {})
    if recipient.get("exactly_one_recipient") is not True:
        steps.append("Fill recipient-private.txt with exactly one recipient contact or identifier.")
    note = by_file.get("operator-dispatch-note-private.md", {})
    if note.get("mentions_channel") is not True:
        steps.append("Replace <private-send-channel> in operator-dispatch-note-private.md with the real private channel.")
    if note.get("contains_release_hash") is not True:
        steps.append("Ensure operator-dispatch-note-private.md includes the current release bundle sha256.")
    steps.append("Rerun the pre-send sequence and continue only after READY_TO_MANUALLY_SEND_ONE.")
    if operator_next_action:
        steps.append(operator_next_action)
    return _dedupe_strings(steps)


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    ready = bool(checks) and all(value is True for value in checks.values())
    release = _dict(payload, "release_bundle")
    operator_gate = _dict(_dict(payload, "gate_receipts"), "operator_status")
    blocking_summary = _dict(payload, "blocking_summary")
    private_files = (
        blocking_summary.get("required_private_files")
        if isinstance(blocking_summary.get("required_private_files"), list)
        else []
    )
    human_next_steps = (
        blocking_summary.get("human_next_steps")
        if isinstance(blocking_summary.get("human_next_steps"), list)
        else []
    )
    body_hash = payload.get("pre_send_sequence_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PRE_SEND_SEQUENCE_SCHEMA_VERSION,
        "status_matches_checks": payload.get("status") == ("pass" if ready else "fail"),
        "verdict_matches_checks": payload.get("verdict")
        == ("READY_TO_MANUALLY_SEND_ONE" if ready else "BLOCKED_BEFORE_MANUAL_SEND"),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "release_bundle_hash_present": _looks_like_sha256(release.get("sha256")),
        "required_private_files_named": {item.get("file") for item in private_files}
        == {"recipient-private.txt", "operator-dispatch-note-private.md"},
        "required_private_file_statuses_controlled": all(
            isinstance(item, dict)
            and isinstance(item.get("status"), str)
            and isinstance(item.get("sha256_present"), bool)
            and isinstance(item.get("minimum_signal_present"), bool)
            and isinstance(item.get("exactly_one_recipient"), bool)
            and isinstance(item.get("mentions_channel"), bool)
            and isinstance(item.get("contains_release_hash"), bool)
            for item in private_files
        ),
        "operator_status_board_file_named": blocking_summary.get("operator_status_board_file")
        == OPERATOR_STATUS_MD_NAME
        and operator_gate.get("status_board_file") == OPERATOR_STATUS_MD_NAME,
        "operator_status_current_artifact_gate_recorded": isinstance(
            operator_gate.get("release_current_artifacts_checked"), bool
        )
        and operator_gate.get("release_current_artifacts_match") in {True, False, None}
        and isinstance(operator_gate.get("release_current_artifacts_gate_passed"), bool)
        and operator_gate.get("release_current_artifacts_gate_passed")
        == (operator_gate.get("release_current_artifacts_match") is not False),
        "human_next_steps_controlled": bool(human_next_steps)
        and all(
            isinstance(item, str)
            and item
            and "\n" not in item
            and str(ROOT) not in item
            and str(Path.home()) not in item
            for item in human_next_steps
        ),
        "manual_dispatch_only": _dict(payload, "policy").get("script_sends_to_recipient") is False
        and _dict(payload, "policy").get("manual_operator_dispatch_required") is True,
        "raw_private_values_omitted": _dict(payload, "policy").get("raw_private_values_in_receipt") is False,
        "local_paths_omitted": _dict(payload, "policy").get("local_paths_in_receipt") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
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
    required_files = (
        summary.get("required_private_files")
        if isinstance(summary.get("required_private_files"), list)
        else []
    )
    file_parts = []
    for item in required_files:
        if not isinstance(item, dict):
            continue
        if item.get("file") == "recipient-private.txt":
            required = "exactly_one_recipient"
            ready = item.get("exactly_one_recipient") is True
            details = f"exactly_one_recipient={str(item.get('exactly_one_recipient')).lower()}"
        elif item.get("file") == "operator-dispatch-note-private.md":
            required = "private_channel,current_release_hash"
            ready = item.get("mentions_channel") is True and item.get("contains_release_hash") is True
            details = (
                f"mentions_channel={str(item.get('mentions_channel')).lower()} "
                f"contains_release_hash={str(item.get('contains_release_hash')).lower()}"
            )
        else:
            required = "ready"
            ready = item.get("status") == "ready"
            details = f"minimum_signal={str(item.get('minimum_signal_present')).lower()}"
        file_parts.append(
            "{file}={status} required={required} ready={ready} {details}".format(
                file=item.get("file"),
                status=item.get("status"),
                required=required,
                ready=str(ready).lower(),
                details=details,
            )
        )
    human_next_steps = (
        summary.get("human_next_steps")
        if isinstance(summary.get("human_next_steps"), list)
        else []
    )
    return (
        "pre-send sequence blocked checks: "
        + ", ".join(str(item) for item in blocked_checks)
        + "; status_board: "
        + str(summary.get("operator_status_board_file") or OPERATOR_STATUS_MD_NAME)
        + "; required private files: "
        + "; ".join(file_parts)
        + "; next_steps: "
        + " | ".join(str(item) for item in human_next_steps)
        + "; next_action: "
        + str(summary.get("next_action"))
    )


def _assert_shareable_receipt_file(path: Path, workspace: Path) -> None:
    text = path.read_text(encoding="utf-8")
    leaked = [item for item in (str(ROOT), str(Path.home()), str(workspace)) if item and item in text]
    if leaked:
        raise InstallKitFirstRecipientPreSendSequenceError("pre-send sequence receipt leaked a local path.")


def _first_hash(*values: Any) -> str | None:
    for value in values:
        if _looks_like_sha256(value):
            return str(value)
    return None


def _body_hash(payload: dict[str, Any] | None, key: str) -> str | None:
    value = payload.get(key) if isinstance(payload, dict) else None
    return str(value) if _looks_like_sha256(value) else None


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    try:
        return _read_json(path)
    except Exception:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitFirstRecipientPreSendSequenceError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "pre_send_sequence_receipt_body_sha256", "pre_send_sequence_receipt_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _error_code(exc: Exception) -> str:
    return exc.__class__.__name__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Cambrian install-kit first-recipient pre-send sequence.")
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing pre-send sequence receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_pre_send_sequence_receipt_file(args.verify_receipt, require_ready=False)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit first-recipient pre-send sequence receipt verification: %s", exc)
            return 1
        logger.info("[PASS] install kit first-recipient pre-send sequence receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["pre_send_sequence_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_pre_send_sequence(
            workspace_dir=args.workspace_dir,
            output_dir=args.output_dir,
            receipt_path=args.receipt,
            skip_verify=args.skip_verify,
        )
    except InstallKitFirstRecipientPreSendSequenceError as exc:
        logger.error("[FAIL] install kit first-recipient pre-send sequence: %s", exc)
        return 1

    logger.info("[PASS] install kit first-recipient pre-send sequence")
    logger.info("verdict: %s", result["verdict"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    logger.info("release_bundle_sha256: %s", result["release_bundle_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
