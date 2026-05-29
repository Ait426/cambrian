"""Install kit recipient install checkpoint gate."""

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
    DISPATCH_RECORD_MD_NAME,
    InstallKitDispatchRecordError,
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.check_cambrian_install_kit_first_recipient_operator_status import (  # noqa: E402
    OPERATOR_STATUS_RECEIPT_NAME,
)


RECIPIENT_CHECKPOINT_SCHEMA_VERSION = "cambrian_install_kit_recipient_checkpoint_v0_1"
RECIPIENT_CHECKPOINT_JSON_NAME = "cambrian-install-kit-recipient-checkpoint.json"
RECIPIENT_CHECKPOINT_MD_NAME = "cambrian-install-kit-recipient-checkpoint.md"
MANUAL_SEND_GO_RECEIPT_NAME = "cambrian-install-kit-first-recipient-manual-send-go-receipt.json"
INSTALL_SHARE_RECEIPT_NAME = "cambrian_install_share_receipt.json"
GOLD_PATH_SHARE_RECEIPT_NAME = "cambrian_gold_path_share_receipt.json"
MCP_OPERABILITY_RECEIPT_NAME = "mcp_operability_receipt.json"
RECIPIENT_ACK_PRIVATE_NAME = "recipient-ack-private.txt"
RETURNED_RECEIPT_NAMES = (
    INSTALL_SHARE_RECEIPT_NAME,
    GOLD_PATH_SHARE_RECEIPT_NAME,
    MCP_OPERABILITY_RECEIPT_NAME,
)

logger = logging.getLogger(__name__)


class InstallKitRecipientCheckpointError(Exception):
    """Install kit recipient checkpoint gate failure."""


def check_recipient_checkpoint(
    output_dir: Path | None = None,
    skip_verify: bool = False,
    install_share_receipt: Path | None = None,
    gold_path_share_receipt: Path | None = None,
    mcp_operability_receipt: Path | None = None,
    recipient_ack_private_sha256: str | None = None,
    recipient_ack_private_file: Path | None = None,
    recipient_private_sha256: str | None = None,
    recipient_private_file: Path | None = None,
    operator_dispatch_note_private_sha256: str | None = None,
    operator_dispatch_note_private_file: Path | None = None,
    operator_status_receipt: Path | None = None,
    require_operator_status_receipt: bool = False,
    manual_send_go_receipt: Path | None = None,
    require_manual_send_go_receipt: bool = False,
    sent_at_utc: str | None = None,
    allow_synthetic_rehearsal: bool = False,
) -> dict[str, Any]:
    """Record recipient install confirmation without raw recipient text."""
    dist = (output_dir or ROOT / "dist").resolve()
    dist.mkdir(parents=True, exist_ok=True)
    ack_sha256 = _resolve_private_sha256(
        direct_sha256=recipient_ack_private_sha256,
        private_file=recipient_ack_private_file,
        label="recipient acknowledgement",
    )
    post_send_inputs_present = any(
        item is not None
        for item in (
            install_share_receipt,
            gold_path_share_receipt,
            mcp_operability_receipt,
            recipient_ack_private_sha256,
            recipient_ack_private_file,
            recipient_private_sha256,
            recipient_private_file,
            operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file,
            sent_at_utc,
        )
    )
    require_operator_status = bool(require_operator_status_receipt or post_send_inputs_present)
    require_manual_send_go = bool(require_manual_send_go_receipt or post_send_inputs_present)
    try:
        dispatch_result = check_dispatch_record(
            output_dir=dist,
            skip_verify=skip_verify,
            recipient_private_sha256=recipient_private_sha256,
            recipient_private_file=recipient_private_file,
            operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file=operator_dispatch_note_private_file,
            operator_status_receipt=operator_status_receipt,
            require_operator_status_receipt=require_operator_status,
            manual_send_go_receipt=manual_send_go_receipt,
            require_manual_send_go_receipt=require_manual_send_go,
            sent_at_utc=sent_at_utc,
            synthetic_rehearsal_without_real_recipient=allow_synthetic_rehearsal,
        )
    except InstallKitDispatchRecordError as exc:
        raise InstallKitRecipientCheckpointError(str(exc)) from exc
    dispatch_path = Path(str(dispatch_result["dispatch_record_json"]))
    dispatch_record = verify_dispatch_record_file(
        dispatch_path,
        allow_synthetic_rehearsal=allow_synthetic_rehearsal,
    )
    resolved_install_share_receipt = _resolve_returned_receipt_path(install_share_receipt, "install share")
    resolved_gold_path_share_receipt = _resolve_returned_receipt_path(gold_path_share_receipt, "gold path share")
    resolved_mcp_operability_receipt = _resolve_returned_receipt_path(mcp_operability_receipt, "MCP operability")
    install_receipt = (
        _verify_install_share_receipt_file(resolved_install_share_receipt)
        if resolved_install_share_receipt
        else None
    )
    install_receipt_sha256 = _file_sha256(resolved_install_share_receipt) if resolved_install_share_receipt else None
    gold_path_receipt = (
        _verify_gold_path_share_receipt_file(resolved_gold_path_share_receipt)
        if resolved_gold_path_share_receipt
        else None
    )
    gold_path_receipt_sha256 = _file_sha256(resolved_gold_path_share_receipt) if resolved_gold_path_share_receipt else None
    mcp_receipt = (
        _verify_mcp_operability_receipt_file(resolved_mcp_operability_receipt)
        if resolved_mcp_operability_receipt
        else None
    )
    mcp_receipt_sha256 = _file_sha256(resolved_mcp_operability_receipt) if resolved_mcp_operability_receipt else None
    payload = _recipient_checkpoint_payload(
        dispatch_record=dispatch_record,
        install_share_receipt=install_receipt,
        install_share_receipt_sha256=install_receipt_sha256,
        gold_path_share_receipt=gold_path_receipt,
        gold_path_share_receipt_sha256=gold_path_receipt_sha256,
        mcp_operability_receipt=mcp_receipt,
        mcp_operability_receipt_sha256=mcp_receipt_sha256,
        recipient_ack_private_sha256=ack_sha256,
        allow_synthetic_rehearsal=allow_synthetic_rehearsal,
    )

    json_path = dist / RECIPIENT_CHECKPOINT_JSON_NAME
    md_path = dist / RECIPIENT_CHECKPOINT_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_recipient_checkpoint_markdown(payload), encoding="utf-8")
    verify_recipient_checkpoint_file(json_path, allow_synthetic_rehearsal=allow_synthetic_rehearsal)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "recipient_checkpoint_json": str(json_path),
        "recipient_checkpoint_md": str(md_path),
        "dispatch_record_json": str(dispatch_path),
        "zip_file": payload["install_kit"]["zip_file"],
        "zip_sha256": payload["install_kit"]["zip_sha256"],
        "operator_next_action": payload["operator_next_action"],
        "recipient_checkpoint_body_sha256": payload["recipient_checkpoint_body_sha256"],
    }


def verify_recipient_checkpoint_file(path: Path, *, allow_synthetic_rehearsal: bool = False) -> dict[str, Any]:
    payload = _read_json(path)
    verify_recipient_checkpoint_payload(payload, allow_synthetic_rehearsal=allow_synthetic_rehearsal)
    return payload


def verify_recipient_checkpoint_payload(payload: dict[str, Any], *, allow_synthetic_rehearsal: bool = False) -> None:
    if payload.get("schema_version") != RECIPIENT_CHECKPOINT_SCHEMA_VERSION:
        raise InstallKitRecipientCheckpointError("install kit recipient-checkpoint schema_version이 올바르지 않습니다.")
    if payload.get("status") not in {
        "awaiting_recipient_install",
        "recipient_install_confirmed",
        "recipient_gold_path_confirmed",
    }:
        raise InstallKitRecipientCheckpointError(f"install kit recipient-checkpoint status가 올바르지 않습니다: {payload.get('status')}")
    if payload.get("verdict") not in {
        "WAITING_FOR_RECIPIENT",
        "RECIPIENT_INSTALL_CONFIRMED",
        "RECIPIENT_GOLD_PATH_CONFIRMED",
    }:
        raise InstallKitRecipientCheckpointError(f"install kit recipient-checkpoint verdict가 올바르지 않습니다: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise InstallKitRecipientCheckpointError("install kit recipient-checkpoint safe_to_share가 true가 아닙니다.")
    synthetic_boundary = (
        payload.get("synthetic_rehearsal_boundary")
        if isinstance(payload.get("synthetic_rehearsal_boundary"), dict)
        else None
    )
    if synthetic_boundary is not None and not allow_synthetic_rehearsal:
        raise InstallKitRecipientCheckpointError(
            "synthetic rehearsal recipient checkpoints are not standalone recipient evidence."
        )
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise InstallKitRecipientCheckpointError("install kit recipient-checkpoint checks가 모두 true가 아닙니다.")
    body_hash = payload.get("recipient_checkpoint_body_sha256")
    if body_hash != _recipient_checkpoint_body_sha256(payload):
        raise InstallKitRecipientCheckpointError("install kit recipient-checkpoint 본문 해시가 일치하지 않습니다.")
    recalculated = _recipient_checkpoint_checks(payload)
    if payload.get("recipient_checkpoint_checks") != recalculated:
        raise InstallKitRecipientCheckpointError("install kit recipient-checkpoint 안전 평가 결과가 현재 본문과 일치하지 않습니다.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise InstallKitRecipientCheckpointError("install kit recipient-checkpoint 안전 평가 실패: " + ", ".join(failed))


def _recipient_checkpoint_payload(
    dispatch_record: dict[str, Any],
    install_share_receipt: dict[str, Any] | None,
    install_share_receipt_sha256: str | None,
    gold_path_share_receipt: dict[str, Any] | None,
    gold_path_share_receipt_sha256: str | None,
    mcp_operability_receipt: dict[str, Any] | None,
    mcp_operability_receipt_sha256: str | None,
    recipient_ack_private_sha256: str | None,
    allow_synthetic_rehearsal: bool = False,
) -> dict[str, Any]:
    dispatch_sent = dispatch_record.get("dispatch_record", {}).get("sent_recorded") is True
    operator_status = (
        dispatch_record.get("operator_status_pre_send")
        if isinstance(dispatch_record.get("operator_status_pre_send"), dict)
        else {}
    )
    manual_send_go = (
        dispatch_record.get("manual_send_go_pre_send")
        if isinstance(dispatch_record.get("manual_send_go_pre_send"), dict)
        else {}
    )
    send_materials = (
        dispatch_record.get("send_materials")
        if isinstance(dispatch_record.get("send_materials"), dict)
        else {}
    )
    dispatch_copy_paste_policy = (
        send_materials.get("copy_paste_message_policy")
        if isinstance(send_materials.get("copy_paste_message_policy"), dict)
        else {}
    )
    dispatch_copy_paste_message_sha256 = str(send_materials.get("copy_paste_message_sha256") or "")
    install_confirmed = install_share_receipt is not None and dispatch_sent
    mcp_confirmed = mcp_operability_receipt is not None and install_confirmed
    gold_path_confirmed = gold_path_share_receipt is not None and install_confirmed and mcp_confirmed
    if (
        install_share_receipt is not None
        or gold_path_share_receipt is not None
        or mcp_operability_receipt is not None
        or recipient_ack_private_sha256 is not None
    ) and not dispatch_sent:
        raise InstallKitRecipientCheckpointError("recipient checkpoint는 SENT_ONE_RECORDED dispatch 이후에만 기록할 수 있습니다.")
    if gold_path_share_receipt is not None and install_share_receipt is None:
        raise InstallKitRecipientCheckpointError("gold path share receipt는 install share receipt와 함께 기록해야 합니다.")
    if gold_path_share_receipt is not None and mcp_operability_receipt is None:
        raise InstallKitRecipientCheckpointError("gold path confirmation requires MCP operability receipt.")
    if mcp_operability_receipt is not None and install_share_receipt is None:
        raise InstallKitRecipientCheckpointError("MCP operability receipt는 install share receipt와 함께 기록해야 합니다.")
    install_summary = _install_receipt_summary(install_share_receipt)
    gold_path_summary = _gold_path_receipt_summary(gold_path_share_receipt)
    mcp_summary = _mcp_operability_receipt_summary(mcp_operability_receipt)
    missing_evidence = _missing_recipient_evidence(
        dispatch_sent=dispatch_sent,
        recipient_ack_private_sha256=recipient_ack_private_sha256,
        install_confirmed=install_confirmed,
        gold_path_confirmed=gold_path_confirmed,
        mcp_confirmed=mcp_confirmed,
    )
    operator_next_action = _operator_next_action(
        dispatch_sent=dispatch_sent,
        install_confirmed=install_confirmed,
        gold_path_confirmed=gold_path_confirmed,
        mcp_confirmed=mcp_confirmed,
        missing_evidence=missing_evidence,
    )
    human_next_steps = _human_next_steps(
        dispatch_sent=dispatch_sent,
        install_confirmed=install_confirmed,
        gold_path_confirmed=gold_path_confirmed,
        mcp_confirmed=mcp_confirmed,
        missing_evidence=missing_evidence,
        operator_next_action=operator_next_action,
    )
    checks = {
        "dispatch_record_valid": dispatch_record.get("verdict") in {"READY_TO_SEND_ONE", "SENT_ONE_RECORDED"},
        "dispatch_record_checks_true": _all_true(dispatch_record.get("dispatch_record_checks")),
        "dispatch_sent_before_install_receipt": install_share_receipt is None or dispatch_sent,
        "operator_status_required_when_post_send": (not dispatch_sent)
        or (
            operator_status.get("required") is True
            and operator_status.get("present") is True
            and operator_status.get("verified_standalone") is True
        ),
        "operator_status_ready_when_post_send": (not dispatch_sent)
        or (
            operator_status.get("ready_to_send_one") is True
            and operator_status.get("verdict") == "READY_TO_MANUALLY_SEND_ONE"
            and operator_status.get("send_state") == "READY_TO_SEND"
            and operator_status.get("manual_send_allowed") is True
        ),
        "operator_status_matches_post_send_hashes": (not dispatch_sent)
        or (
            operator_status.get("release_hash_matches_dispatch") is True
            and operator_status.get("release_current_artifacts_match_dispatch") is not False
            and operator_status.get("private_hashes_match_dispatch") is True
        ),
        "manual_send_go_required_when_post_send": (not dispatch_sent)
        or (
            manual_send_go.get("required") is True
            and manual_send_go.get("present") is True
            and manual_send_go.get("verified_standalone") is True
        ),
        "manual_send_go_ready_when_post_send": (not dispatch_sent)
        or (
            manual_send_go.get("ready_to_send_one") is True
            and manual_send_go.get("verdict") == "GO_TO_MANUALLY_SEND_ONE"
        ),
        "manual_send_go_matches_post_send_operator_status": (not dispatch_sent)
        or (
            manual_send_go.get("release_hash_matches_dispatch") is True
            and manual_send_go.get("operator_status_ready_receipt_matches") is True
            and manual_send_go.get("operator_status_body_matches_dispatch") is True
        ),
        "recipient_ack_hash_valid_or_absent": recipient_ack_private_sha256 is None or _looks_like_sha256(recipient_ack_private_sha256),
        "install_share_receipt_valid_or_absent": install_share_receipt is None or _install_share_receipt_valid(install_share_receipt),
        "install_share_receipt_safe_to_share": install_share_receipt is None or install_share_receipt.get("safe_to_share") is True,
        "install_share_receipt_has_no_absolute_paths": install_share_receipt is None
        or install_share_receipt.get("privacy", {}).get("absolute_paths_included") is False,
        "gold_path_requires_install_receipt": gold_path_share_receipt is None or install_share_receipt is not None,
        "gold_path_requires_mcp_operability_receipt": gold_path_share_receipt is None
        or mcp_operability_receipt is not None,
        "gold_path_share_receipt_valid_or_absent": gold_path_share_receipt is None or _gold_path_share_receipt_valid(gold_path_share_receipt),
        "gold_path_share_receipt_safe_to_share": gold_path_share_receipt is None or gold_path_share_receipt.get("safe_to_share") is True,
        "gold_path_share_receipt_has_no_absolute_paths": gold_path_share_receipt is None
        or gold_path_share_receipt.get("privacy", {}).get("absolute_paths_included") is False,
        "gold_path_capabilities_all_true": gold_path_share_receipt is None
        or _all_true(gold_path_share_receipt.get("capabilities_verified")),
        "gold_path_claim_boundaries_locked": gold_path_share_receipt is None
        or (
            gold_path_share_receipt.get("proof_claim_allowed") is False
            and gold_path_share_receipt.get("sale_ready") is False
        ),
        "mcp_operability_receipt_requires_install_receipt": mcp_operability_receipt is None
        or install_share_receipt is not None,
        "mcp_operability_receipt_valid_or_absent": mcp_operability_receipt is None
        or _mcp_operability_receipt_valid(mcp_operability_receipt),
        "mcp_operability_receipt_checks_all_true": mcp_operability_receipt is None
        or _all_true(mcp_operability_receipt.get("checks")),
        "mcp_operability_receipt_installed_wheel_mode": mcp_operability_receipt is None
        or (
            mcp_operability_receipt.get("source_pythonpath_injected") is False
            and mcp_operability_receipt.get("installed_entrypoint_command") is True
            and mcp_operability_receipt.get("server_command_mode") == "installed_entrypoint"
        ),
        "mcp_operability_receipt_no_arbitrary_shell": mcp_operability_receipt is None
        or mcp_operability_receipt.get("checks", {}).get("no_arbitrary_shell") is True,
        "mcp_operability_receipt_explicit_cwd_required": mcp_operability_receipt is None
        or mcp_operability_receipt.get("checks", {}).get("explicit_cwd_required") is True,
        "missing_evidence_summary_controlled": _controlled_strings(missing_evidence, allow_empty=True),
        "human_next_steps_controlled": _controlled_strings(human_next_steps),
        "manual_dispatch_only": dispatch_record.get("dispatch_execution_policy", {}).get("script_sends_to_recipient") is False
        and dispatch_record.get("dispatch_execution_policy", {}).get("manual_operator_dispatch_required") is True,
        "one_recipient_only": dispatch_record.get("dispatch_scope", {}).get("target_recipients") == 1,
        "private_hash_only": dispatch_record.get("dispatch_execution_policy", {}).get("records_private_sha256_only") is True,
        "dispatch_record_mcp_operability_verified": dispatch_record.get("release_bundle_smoke", {}).get("mcp_operability_verified") is True,
        "dispatch_copy_paste_policy_hashed": _looks_like_sha256(dispatch_copy_paste_message_sha256),
        "dispatch_copy_paste_policy_names_install": dispatch_copy_paste_policy.get("bundle_installer_named") is True,
        "dispatch_copy_paste_policy_names_gold_path": dispatch_copy_paste_policy.get("gold_path_runner_named") is True,
        "dispatch_copy_paste_policy_names_mcp_receipt": dispatch_copy_paste_policy.get("mcp_operability_receipt_named") is True,
        "dispatch_copy_paste_policy_marks_local_validation_only": dispatch_copy_paste_policy.get("local_validation_only") is True,
        "dispatch_copy_paste_policy_blocks_public_proof": dispatch_copy_paste_policy.get("public_proof_claim_blocked") is True,
        "dispatch_copy_paste_policy_requires_real_first_recipient_send": (
            dispatch_copy_paste_policy.get("first_recipient_confirmation_requires_real_send") is True
        ),
        "raw_recipient_content_omitted": True,
        "proof_claims_blocked": True,
        "sale_ready_blocked": True,
    }
    payload: dict[str, Any] = {
        "schema_version": RECIPIENT_CHECKPOINT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "recipient_gold_path_confirmed"
            if gold_path_confirmed
            else "recipient_install_confirmed"
            if install_confirmed
            else "awaiting_recipient_install"
        ),
        "verdict": (
            "RECIPIENT_GOLD_PATH_CONFIRMED"
            if gold_path_confirmed
            else "RECIPIENT_INSTALL_CONFIRMED"
            if install_confirmed
            else "WAITING_FOR_RECIPIENT"
        ),
        "safe_to_share": True,
        "install_kit": dispatch_record.get("install_kit"),
        "dispatch_record": {
            "file": DISPATCH_RECORD_JSON_NAME,
            "markdown_file": DISPATCH_RECORD_MD_NAME,
            "body_sha256": dispatch_record.get("dispatch_record_body_sha256"),
            "verdict": dispatch_record.get("verdict"),
            "sent_recorded": dispatch_sent,
            "mcp_operability_verified": dispatch_record.get("release_bundle_smoke", {}).get("mcp_operability_verified") is True,
        },
        "dispatch_copy_paste_message_policy": {
            "copy_paste_message_sha256": dispatch_copy_paste_message_sha256,
            "bundle_installer_named": dispatch_copy_paste_policy.get("bundle_installer_named") is True,
            "gold_path_runner_named": dispatch_copy_paste_policy.get("gold_path_runner_named") is True,
            "share_receipt_named": dispatch_copy_paste_policy.get("share_receipt_named") is True,
            "gold_path_share_receipt_named": dispatch_copy_paste_policy.get("gold_path_share_receipt_named") is True,
            "mcp_operability_receipt_named": dispatch_copy_paste_policy.get("mcp_operability_receipt_named") is True,
            "local_validation_only": dispatch_copy_paste_policy.get("local_validation_only") is True,
            "public_proof_claim_blocked": dispatch_copy_paste_policy.get("public_proof_claim_blocked") is True,
            "first_recipient_confirmation_requires_real_send": (
                dispatch_copy_paste_policy.get("first_recipient_confirmation_requires_real_send") is True
            ),
        },
        "operator_status_pre_send": {
            "file": operator_status.get("file") or OPERATOR_STATUS_RECEIPT_NAME,
            "required": operator_status.get("required") is True,
            "present": operator_status.get("present") is True,
            "verified_standalone": operator_status.get("verified_standalone") is True,
            "body_sha256": operator_status.get("body_sha256"),
            "verdict": operator_status.get("verdict"),
            "ready_to_send_one": operator_status.get("ready_to_send_one") is True,
            "release_hash_matches_dispatch": operator_status.get("release_hash_matches_dispatch") is True,
            "release_current_artifacts_checked": operator_status.get("release_current_artifacts_checked") is True,
            "release_current_artifacts_match_dispatch": operator_status.get(
                "release_current_artifacts_match_dispatch"
            ),
            "release_current_artifacts_gate_passed": operator_status.get("release_current_artifacts_gate_passed")
            is not False,
            "release_current_artifacts_status": operator_status.get("release_current_artifacts_status"),
            "private_hashes_match_dispatch": operator_status.get("private_hashes_match_dispatch") is True,
        },
        "manual_send_go_pre_send": {
            "file": manual_send_go.get("file") or MANUAL_SEND_GO_RECEIPT_NAME,
            "required": manual_send_go.get("required") is True,
            "present": manual_send_go.get("present") is True,
            "verified_standalone": manual_send_go.get("verified_standalone") is True,
            "body_sha256": manual_send_go.get("body_sha256"),
            "verdict": manual_send_go.get("verdict"),
            "ready_to_send_one": manual_send_go.get("ready_to_send_one") is True,
            "release_hash_matches_dispatch": manual_send_go.get("release_hash_matches_dispatch") is True,
            "operator_status_ready_receipt_matches": manual_send_go.get("operator_status_ready_receipt_matches") is True,
            "operator_status_body_matches_dispatch": manual_send_go.get("operator_status_body_matches_dispatch")
            is True,
        },
        "recipient_checkpoint": {
            "recipient_ack_private_sha256": recipient_ack_private_sha256,
            "install_share_receipt_sha256": install_share_receipt_sha256,
            "gold_path_share_receipt_sha256": gold_path_share_receipt_sha256,
            "mcp_operability_receipt_sha256": mcp_operability_receipt_sha256,
            "raw_ack_included": False,
            "raw_install_receipt_path_included": False,
            "raw_gold_path_receipt_path_included": False,
            "raw_mcp_operability_receipt_path_included": False,
        },
        "install_share_receipt": install_summary,
        "gold_path_share_receipt": gold_path_summary,
        "mcp_operability_receipt": mcp_summary,
        "blocking_summary": {
            "missing_evidence": missing_evidence,
            "next_action": operator_next_action,
            "human_next_steps": human_next_steps,
            "required_returned_receipts": list(RETURNED_RECEIPT_NAMES),
            "ack_file": RECIPIENT_ACK_PRIVATE_NAME,
            "proof_closed": gold_path_confirmed,
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "operator_next_action": operator_next_action,
        "checks": checks,
        "artifact_chain": [
            *_sanitize_artifact_chain(dispatch_record.get("artifact_chain")),
            {
                "kind": "install_kit_recipient_checkpoint",
                "file": RECIPIENT_CHECKPOINT_JSON_NAME,
                "sha256": "",
            },
        ],
        "metrics": {
            "recipient_ack_recorded": recipient_ack_private_sha256 is not None,
            "recipient_install_confirmed": install_confirmed,
            "recipient_gold_path_confirmed": gold_path_confirmed,
            "recipient_mcp_operability_confirmed": mcp_confirmed,
            "gold_path_capabilities_verified": gold_path_summary.get("capabilities_verified", {}),
            "success_rate": None,
            "proof_claim_allowed": False,
            "sale_ready": False,
        },
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
    }
    synthetic_dispatch_boundary = (
        dispatch_record.get("synthetic_rehearsal_boundary")
        if isinstance(dispatch_record.get("synthetic_rehearsal_boundary"), dict)
        else None
    )
    if synthetic_dispatch_boundary is not None:
        payload["synthetic_rehearsal_boundary"] = {
            "synthetic_rehearsal": True,
            "standalone_recipient_evidence_allowed": False,
            "standalone_send_evidence_allowed": synthetic_dispatch_boundary.get(
                "standalone_send_evidence_allowed"
            )
            is True,
            "real_manual_send": False,
            "real_recipient_evidence": False,
            "synthetic_dispatch_body_sha256": dispatch_record.get("dispatch_record_body_sha256"),
        }
    payload["recipient_checkpoint_body_sha256"] = _recipient_checkpoint_body_sha256(payload)
    payload["artifact_chain"][-1]["sha256"] = payload["recipient_checkpoint_body_sha256"]
    payload["recipient_checkpoint_checks"] = _recipient_checkpoint_checks(payload)
    verify_recipient_checkpoint_payload(payload, allow_synthetic_rehearsal=allow_synthetic_rehearsal)
    return payload


def _recipient_checkpoint_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "recipient_checkpoint_body_sha256", "recipient_checkpoint_checks"}
    }
    if isinstance(body.get("artifact_chain"), list):
        body["artifact_chain"] = [
            {
                **item,
                "sha256": "" if isinstance(item, dict) and item.get("kind") == "install_kit_recipient_checkpoint" else item.get("sha256"),
            }
            if isinstance(item, dict)
            else item
            for item in body["artifact_chain"]
        ]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _recipient_checkpoint_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(ROOT)
    home = str(Path.home())
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    body_hash = payload.get("recipient_checkpoint_body_sha256")
    blocking_summary = payload.get("blocking_summary") if isinstance(payload.get("blocking_summary"), dict) else {}
    human_next_steps = (
        blocking_summary.get("human_next_steps")
        if isinstance(blocking_summary.get("human_next_steps"), list)
        else []
    )
    missing_evidence = (
        blocking_summary.get("missing_evidence")
        if isinstance(blocking_summary.get("missing_evidence"), list)
        else []
    )
    dispatch_copy_paste_policy = (
        payload.get("dispatch_copy_paste_message_policy")
        if isinstance(payload.get("dispatch_copy_paste_message_policy"), dict)
        else {}
    )
    return {
        "schema_version_present": payload.get("schema_version") == RECIPIENT_CHECKPOINT_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": {
            "install_kit_zip",
            "install_kit_receipt",
            "install_kit_handoff",
            "install_kit_send_ready",
            "install_kit_dispatch_record",
            "install_kit_recipient_checkpoint",
        }.issubset({str(item.get("kind") or "") for item in chain if isinstance(item, dict)}),
        "artifact_chain_self_hash_matched": any(
            item.get("kind") == "install_kit_recipient_checkpoint"
            and item.get("file") == RECIPIENT_CHECKPOINT_JSON_NAME
            and item.get("sha256") == body_hash
            for item in chain
            if isinstance(item, dict)
        ),
        "manual_dispatch_boundary_preserved": payload.get("checks", {}).get("manual_dispatch_only") is True,
        "one_recipient_boundary_preserved": payload.get("checks", {}).get("one_recipient_only") is True,
        "private_hash_boundary_preserved": payload.get("checks", {}).get("private_hash_only") is True,
        "dispatch_copy_paste_boundary_preserved": (
            _looks_like_sha256(dispatch_copy_paste_policy.get("copy_paste_message_sha256"))
            and dispatch_copy_paste_policy.get("bundle_installer_named") is True
            and dispatch_copy_paste_policy.get("gold_path_runner_named") is True
            and dispatch_copy_paste_policy.get("mcp_operability_receipt_named") is True
            and dispatch_copy_paste_policy.get("local_validation_only") is True
            and dispatch_copy_paste_policy.get("public_proof_claim_blocked") is True
            and dispatch_copy_paste_policy.get("first_recipient_confirmation_requires_real_send") is True
        ),
        "claim_boundaries_locked": payload.get("metrics", {}).get("proof_claim_allowed") is False
        and payload.get("metrics", {}).get("sale_ready") is False
        and payload.get("metrics", {}).get("success_rate") is None,
        "blocking_summary_safe": blocking_summary.get("raw_private_values_included") is False
        and blocking_summary.get("local_paths_included") is False,
        "missing_evidence_controlled": _controlled_strings(missing_evidence, allow_empty=True),
        "human_next_steps_controlled": _controlled_strings(human_next_steps),
        "required_returned_receipts_controlled": blocking_summary.get("required_returned_receipts")
        == list(RETURNED_RECEIPT_NAMES),
        "ack_file_named": blocking_summary.get("ack_file") == RECIPIENT_ACK_PRIVATE_NAME,
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _recipient_checkpoint_body_sha256(payload),
        "synthetic_boundary_not_standalone_when_present": (
            "synthetic_rehearsal_boundary" not in payload
        )
        or (
            isinstance(payload.get("synthetic_rehearsal_boundary"), dict)
            and payload["synthetic_rehearsal_boundary"].get("synthetic_rehearsal") is True
            and payload["synthetic_rehearsal_boundary"].get("standalone_recipient_evidence_allowed") is False
            and payload["synthetic_rehearsal_boundary"].get("real_manual_send") is False
            and payload["synthetic_rehearsal_boundary"].get("real_recipient_evidence") is False
        ),
    }


def _recipient_checkpoint_markdown(payload: dict[str, Any]) -> str:
    kit = payload.get("install_kit") if isinstance(payload.get("install_kit"), dict) else {}
    checkpoint = payload["recipient_checkpoint"]
    gold_path = payload.get("gold_path_share_receipt") if isinstance(payload.get("gold_path_share_receipt"), dict) else {}
    mcp_receipt = (
        payload.get("mcp_operability_receipt") if isinstance(payload.get("mcp_operability_receipt"), dict) else {}
    )
    blocking_summary = payload.get("blocking_summary") if isinstance(payload.get("blocking_summary"), dict) else {}
    missing_evidence = blocking_summary.get("missing_evidence") if isinstance(blocking_summary.get("missing_evidence"), list) else []
    human_next_steps = (
        blocking_summary.get("human_next_steps")
        if isinstance(blocking_summary.get("human_next_steps"), list)
        else []
    )
    dispatch_copy_paste_policy = (
        payload.get("dispatch_copy_paste_message_policy")
        if isinstance(payload.get("dispatch_copy_paste_message_policy"), dict)
        else {}
    )
    return f"""# Cambrian Install Kit Recipient Checkpoint

## Verdict

`{payload["verdict"]}`

## Artifact

- ZIP: `{kit.get("zip_file")}`
- ZIP sha256: `{kit.get("zip_sha256")}`
- Dispatch record: `{payload["dispatch_record"]["file"]}`
- Dispatch record body sha256: `{payload["dispatch_record"]["body_sha256"]}`
- MCP operability verified before send: {payload["dispatch_record"]["mcp_operability_verified"]}
- Operator status required before post-send checkpoint: {payload["operator_status_pre_send"]["required"]}
- Operator status ready before post-send checkpoint: {payload["operator_status_pre_send"]["ready_to_send_one"]}
- Manual-send GO required before post-send checkpoint: {payload["manual_send_go_pre_send"]["required"]}
- Manual-send GO ready before post-send checkpoint: {payload["manual_send_go_pre_send"]["ready_to_send_one"]}
- Release current artifacts checked before post-send checkpoint: {payload["operator_status_pre_send"]["release_current_artifacts_checked"]}
- Release current artifacts match before post-send checkpoint: {payload["operator_status_pre_send"]["release_current_artifacts_gate_passed"]}
- Recipient checkpoint body sha256: `{payload["recipient_checkpoint_body_sha256"]}`

## Dispatch Copy-Paste Boundary

- copy-paste message sha256 present: {_looks_like_sha256(dispatch_copy_paste_policy.get("copy_paste_message_sha256"))}
- install runner named: {dispatch_copy_paste_policy.get("bundle_installer_named") is True}
- gold path runner named: {dispatch_copy_paste_policy.get("gold_path_runner_named") is True}
- MCP receipt named: {dispatch_copy_paste_policy.get("mcp_operability_receipt_named") is True}
- local validation only: {dispatch_copy_paste_policy.get("local_validation_only") is True}
- public proof claim blocked: {dispatch_copy_paste_policy.get("public_proof_claim_blocked") is True}
- first-recipient confirmation requires real send: {dispatch_copy_paste_policy.get("first_recipient_confirmation_requires_real_send") is True}

## Recipient Evidence

- dispatch sent recorded: {payload["dispatch_record"]["sent_recorded"]}
- recipient ack private sha256 present: {checkpoint["recipient_ack_private_sha256"] is not None}
- install share receipt sha256 present: {checkpoint["install_share_receipt_sha256"] is not None}
- gold path share receipt sha256 present: {checkpoint.get("gold_path_share_receipt_sha256") is not None}
- MCP operability receipt sha256 present: {checkpoint.get("mcp_operability_receipt_sha256") is not None}
- recipient install confirmed: {payload["metrics"]["recipient_install_confirmed"]}
- recipient gold path confirmed: {payload["metrics"].get("recipient_gold_path_confirmed")}
- recipient MCP operability confirmed: {payload["metrics"].get("recipient_mcp_operability_confirmed")}
- gold path capabilities all true: {gold_path.get("capabilities_all_true")}
- returned MCP receipt checks all true: {mcp_receipt.get("checks_all_true")}
- returned MCP receipt no arbitrary shell: {mcp_receipt.get("no_arbitrary_shell")}

## Missing Evidence

{_markdown_list(missing_evidence or ["none"])}

## Human Next Steps

{_markdown_list(human_next_steps)}

## Boundary

This checkpoint does not store recipient raw text, local receipt paths, raw gold path receipt paths, raw MCP receipt paths, private project data, success-rate claims, public proof claims, or sale-ready claims.
"""


def _missing_recipient_evidence(
    *,
    dispatch_sent: bool,
    recipient_ack_private_sha256: str | None,
    install_confirmed: bool,
    gold_path_confirmed: bool,
    mcp_confirmed: bool,
) -> list[str]:
    if gold_path_confirmed:
        return []
    if not dispatch_sent:
        return ["SENT_ONE_RECORDED dispatch record"]
    missing: list[str] = []
    if recipient_ack_private_sha256 is None:
        missing.append(RECIPIENT_ACK_PRIVATE_NAME)
    if not install_confirmed:
        missing.append(INSTALL_SHARE_RECEIPT_NAME)
    if not mcp_confirmed:
        missing.append(MCP_OPERABILITY_RECEIPT_NAME)
    if not gold_path_confirmed:
        missing.append(GOLD_PATH_SHARE_RECEIPT_NAME)
    return missing


def _operator_next_action(
    *,
    dispatch_sent: bool,
    install_confirmed: bool,
    gold_path_confirmed: bool,
    mcp_confirmed: bool,
    missing_evidence: list[str],
) -> str:
    if gold_path_confirmed:
        return "Recipient gold path proof is closed. Collect controlled feedback before any next recipient."
    if not dispatch_sent:
        return "Do not claim recipient proof yet. First record SENT_ONE_RECORDED through the first-recipient post-send sequence after the real manual send."
    if install_confirmed and not mcp_confirmed:
        return "Do not claim the gold path yet. Wait for the returned MCP operability receipt and gold path receipt."
    if install_confirmed:
        return "Install proof is recorded. Wait for the remaining gold path evidence before any public proof claim."
    if missing_evidence:
        return "Wait for the missing first-recipient evidence, then rerun the recipient checkpoint."
    return "Wait for the first recipient to return share-safe evidence."


def _human_next_steps(
    *,
    dispatch_sent: bool,
    install_confirmed: bool,
    gold_path_confirmed: bool,
    mcp_confirmed: bool,
    missing_evidence: list[str],
    operator_next_action: str,
) -> list[str]:
    steps: list[str] = []
    if not dispatch_sent:
        steps.extend(
            [
                "Do not claim recipient proof before the real manual send is recorded.",
                "Run the first-recipient pre-send sequence until READY_TO_MANUALLY_SEND_ONE.",
                "After the human sends exactly one bundle, run the post-send sequence with the real UTC sent timestamp.",
            ]
        )
    elif gold_path_confirmed:
        steps.append("Collect controlled feedback before sending to another recipient.")
    else:
        if RECIPIENT_ACK_PRIVATE_NAME in missing_evidence:
            steps.append("Put exactly one CONFIRMED acknowledgement in recipient-ack-private.txt.")
        returned_missing = [name for name in missing_evidence if name in RETURNED_RECEIPT_NAMES]
        if returned_missing:
            steps.append("Collect missing returned share-safe receipts: " + ", ".join(returned_missing) + ".")
        if install_confirmed and not mcp_confirmed:
            steps.append("Gold path confirmation requires the returned installed-entrypoint MCP operability receipt.")
        if install_confirmed and not gold_path_confirmed:
            steps.append("Do not make public proof, success-rate, or sale-ready claims until the gold path receipt is confirmed.")
    if operator_next_action:
        steps.append(operator_next_action)
    return _dedupe_strings(steps)


def _controlled_strings(values: list[Any], *, allow_empty: bool = False) -> bool:
    root = str(ROOT)
    home = str(Path.home())
    return (allow_empty or bool(values)) and all(
        isinstance(value, str)
        and bool(value)
        and "\n" not in value
        and root not in value
        and (not home or home not in value)
        for value in values
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _markdown_list(values: list[Any]) -> str:
    items = [str(value) for value in values if isinstance(value, str) and value]
    if not items:
        return "- none"
    return "\n".join(f"- {item}" for item in items)


def _resolve_returned_receipt_path(path: Path | None, label: str) -> Path | None:
    if path is None:
        return None
    raw_path = str(path).strip()
    if not raw_path or "<" in raw_path or ">" in raw_path or "|" in raw_path:
        raise InstallKitRecipientCheckpointError(
            f"{label} receipt file is missing or still a placeholder."
        )
    try:
        if not path.is_file():
            raise InstallKitRecipientCheckpointError(
                f"{label} receipt file is missing or still a placeholder."
            )
    except OSError as exc:
        raise InstallKitRecipientCheckpointError(
            f"{label} receipt file is missing or still a placeholder."
        ) from exc
    return path


def _verify_install_share_receipt_file(path: Path) -> dict[str, Any]:
    receipt = _read_json(path)
    if not _install_share_receipt_valid(receipt):
        raise InstallKitRecipientCheckpointError("install share receipt가 유효하지 않습니다.")
    serialized = json.dumps(receipt, ensure_ascii=False)
    if str(ROOT) in serialized or str(Path.home()) in serialized:
        raise InstallKitRecipientCheckpointError("install share receipt에 로컬 절대경로가 포함되어 있습니다.")
    return receipt


def _install_share_receipt_valid(receipt: dict[str, Any]) -> bool:
    privacy = receipt.get("privacy") if isinstance(receipt.get("privacy"), dict) else {}
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    return (
        receipt.get("schema_version") == "cambrian_install_share_receipt_v0_1"
        and receipt.get("status") == "installed"
        and receipt.get("safe_to_share") is True
        and privacy.get("absolute_paths_included") is False
        and privacy.get("raw_private_project_data_included") is False
        and privacy.get("secrets_included") is False
        and bool(checks)
        and all(value is True for value in checks.values())
    )


def _verify_gold_path_share_receipt_file(path: Path) -> dict[str, Any]:
    receipt = _read_json(path)
    if not _gold_path_share_receipt_valid(receipt):
        raise InstallKitRecipientCheckpointError("gold path share receipt가 유효하지 않습니다.")
    serialized = json.dumps(receipt, ensure_ascii=False)
    if str(ROOT) in serialized or str(Path.home()) in serialized:
        raise InstallKitRecipientCheckpointError("gold path share receipt에 로컬 절대경로가 포함되어 있습니다.")
    return receipt


def _gold_path_share_receipt_valid(receipt: dict[str, Any]) -> bool:
    privacy = receipt.get("privacy") if isinstance(receipt.get("privacy"), dict) else {}
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    capabilities = receipt.get("capabilities_verified") if isinstance(receipt.get("capabilities_verified"), dict) else {}
    return (
        receipt.get("schema_version") == "cambrian_bundle_gold_path_share_receipt_v0_1"
        and receipt.get("status") == "passed"
        and receipt.get("safe_to_share") is True
        and privacy.get("absolute_paths_included") is False
        and privacy.get("raw_private_project_data_included") is False
        and privacy.get("secrets_included") is False
        and bool(checks)
        and all(value is True for value in checks.values())
        and bool(capabilities)
        and all(value is True for value in capabilities.values())
        and receipt.get("proof_claim_allowed") is False
        and receipt.get("sale_ready") is False
    )


def _verify_mcp_operability_receipt_file(path: Path) -> dict[str, Any]:
    receipt = _read_json(path)
    if not _mcp_operability_receipt_valid(receipt):
        raise InstallKitRecipientCheckpointError("MCP operability receipt가 유효하지 않습니다.")
    return receipt


def _mcp_operability_receipt_valid(receipt: dict[str, Any]) -> bool:
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    required_checks = {
        "initialize",
        "tools_list",
        "missing_cwd_blocked",
        "project_scan_with_explicit_cwd",
        "harness_install_requires_confirm",
        "allowlisted_cli_only",
        "no_arbitrary_shell",
        "explicit_cwd_required",
    }
    return (
        receipt.get("schema_version") == "1.0.0"
        and receipt.get("verdict") == "GO"
        and receipt.get("verifier") == "cambrian mcp verify"
        and receipt.get("source_pythonpath_injected") is False
        and receipt.get("installed_entrypoint_command") is True
        and receipt.get("server_command_mode") == "installed_entrypoint"
        and receipt.get("source_code_modified_by_cambrian") is False
        and receipt.get("provider_api_called_by_cambrian") is False
        and required_checks.issubset(checks.keys())
        and all(checks.get(name) is True for name in required_checks)
    )


def _install_receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if receipt is None:
        return {
            "present": False,
            "status": None,
            "safe_to_share": None,
            "checks_all_true": False,
        }
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    return {
        "present": True,
        "schema_version": receipt.get("schema_version"),
        "status": receipt.get("status"),
        "safe_to_share": receipt.get("safe_to_share"),
        "wheel": receipt.get("wheel"),
        "offline": receipt.get("offline"),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "cambrian_help_passed": checks.get("cambrian_help_passed") is True,
        "cambrian_doctor_json_passed": checks.get("cambrian_doctor_json_passed") is True,
        "cambrian_company_snapshot_help_passed": checks.get("cambrian_company_snapshot_help_passed") is True,
    }


def _gold_path_receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if receipt is None:
        return {
            "present": False,
            "status": None,
            "safe_to_share": None,
            "checks_all_true": False,
            "capabilities_all_true": False,
        }
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    capabilities = receipt.get("capabilities_verified") if isinstance(receipt.get("capabilities_verified"), dict) else {}
    return {
        "present": True,
        "schema_version": receipt.get("schema_version"),
        "status": receipt.get("status"),
        "safe_to_share": receipt.get("safe_to_share"),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "capabilities_all_true": bool(capabilities) and all(value is True for value in capabilities.values()),
        "capabilities_verified": {
            "ai_agents_created": capabilities.get("ai_agents_created") is True,
            "skills_generated_searched_and_fused": capabilities.get("skills_generated_searched_and_fused") is True,
            "harness_engineering_system_created": capabilities.get("harness_engineering_system_created") is True,
            "evolution_proposed_previewed_and_applied": capabilities.get("evolution_proposed_previewed_and_applied") is True,
            "company_snapshot_generated": capabilities.get("company_snapshot_generated") is True,
            "mcp_operability_verified": capabilities.get("mcp_operability_verified") is True,
        },
        "proof_claim_allowed": receipt.get("proof_claim_allowed"),
        "sale_ready": receipt.get("sale_ready"),
    }


def _mcp_operability_receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if receipt is None:
        return {
            "present": False,
            "verdict": None,
            "checks_all_true": False,
            "installed_wheel_mode": False,
        }
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    return {
        "present": True,
        "schema_version": receipt.get("schema_version"),
        "verdict": receipt.get("verdict"),
        "verifier": receipt.get("verifier"),
        "tool_count": receipt.get("tool_count"),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "installed_wheel_mode": (
            receipt.get("source_pythonpath_injected") is False
            and receipt.get("installed_entrypoint_command") is True
            and receipt.get("server_command_mode") == "installed_entrypoint"
        ),
        "server_command_mode": receipt.get("server_command_mode"),
        "installed_entrypoint_command": receipt.get("installed_entrypoint_command") is True,
        "initialize": checks.get("initialize") is True,
        "tools_list": checks.get("tools_list") is True,
        "missing_cwd_blocked": checks.get("missing_cwd_blocked") is True,
        "project_scan_with_explicit_cwd": checks.get("project_scan_with_explicit_cwd") is True,
        "harness_install_requires_confirm": checks.get("harness_install_requires_confirm") is True,
        "allowlisted_cli_only": checks.get("allowlisted_cli_only") is True,
        "no_arbitrary_shell": checks.get("no_arbitrary_shell") is True,
        "explicit_cwd_required": checks.get("explicit_cwd_required") is True,
        "source_code_modified_by_cambrian": receipt.get("source_code_modified_by_cambrian") is True,
        "provider_api_called_by_cambrian": receipt.get("provider_api_called_by_cambrian") is True,
    }


def _resolve_private_sha256(direct_sha256: str | None, private_file: Path | None, label: str) -> str | None:
    if direct_sha256 and private_file:
        raise InstallKitRecipientCheckpointError(f"{label}: direct sha256과 private file은 동시에 사용할 수 없습니다.")
    if private_file:
        return hashlib.sha256(private_file.read_bytes()).hexdigest()
    if direct_sha256 is not None and not _looks_like_sha256(direct_sha256):
        raise InstallKitRecipientCheckpointError(f"{label}: sha256 형식이 아닙니다.")
    return direct_sha256


def _sanitize_artifact_chain(chain: Any) -> list[dict[str, str]]:
    if not isinstance(chain, list):
        return []
    sanitized: list[dict[str, str]] = []
    for item in chain:
        if not isinstance(item, dict):
            continue
        sanitized.append(
            {
                "kind": str(item.get("kind") or ""),
                "file": Path(str(item.get("file") or "")).name,
                "sha256": str(item.get("sha256") or ""),
            }
        )
    return sanitized


def _all_true(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitRecipientCheckpointError("JSON 객체가 아닙니다.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cambrian install kit 수령자 설치 확인 장부를 생성한다.")
    parser.add_argument("--output-dir", type=Path, default=None, help="산출물 출력 폴더. 기본값은 dist")
    parser.add_argument("--skip-verify", action="store_true", help="dispatch-record 준비 시 ZIP 재검증을 건너뛴다.")
    parser.add_argument("--install-share-receipt", type=Path, default=None, help="수령자가 보낸 cambrian_install_share_receipt.json")
    parser.add_argument("--gold-path-share-receipt", type=Path, default=None, help="수령자가 보낸 cambrian_gold_path_share_receipt.json")
    parser.add_argument("--mcp-operability-receipt", type=Path, default=None, help="수령자가 보낸 mcp_operability_receipt.json")
    parser.add_argument("--recipient-ack-private-sha256", default=None, help="수령자 확인 원문 대신 저장할 sha256")
    parser.add_argument("--recipient-ack-private-file", type=Path, default=None, help="수령자 확인 원문 파일. 내용/경로는 저장하지 않고 sha256만 계산한다.")
    parser.add_argument("--recipient-private-sha256", default=None, help="수령자 식별자 원문 대신 저장할 sha256")
    parser.add_argument("--recipient-private-file", type=Path, default=None, help="수령자 식별자 원문 파일. 내용/경로는 저장하지 않고 sha256만 계산한다.")
    parser.add_argument("--operator-dispatch-note-private-sha256", default=None, help="운영 발송 노트 원문 대신 저장할 sha256")
    parser.add_argument("--operator-dispatch-note-private-file", type=Path, default=None, help="운영 발송 노트 파일. 내용/경로는 저장하지 않고 sha256만 계산한다.")
    parser.add_argument("--operator-status-receipt", type=Path, default=None, help="READY_TO_MANUALLY_SEND_ONE operator status receipt JSON.")
    parser.add_argument("--require-operator-status-receipt", action="store_true", help="Require a READY_TO_MANUALLY_SEND_ONE operator status receipt before recording post-send recipient evidence.")
    parser.add_argument("--manual-send-go-receipt", type=Path, default=None, help="GO_TO_MANUALLY_SEND_ONE manual-send GO receipt JSON.")
    parser.add_argument("--require-manual-send-go-receipt", action="store_true", help="Require a GO_TO_MANUALLY_SEND_ONE manual-send GO receipt before recording post-send recipient evidence.")
    parser.add_argument("--sent-at-utc", default=None, help="실제 발송 시각. 예: 2026-05-15T10:00:00+00:00")
    parser.add_argument("--verify-recipient-checkpoint", type=Path, default=None, help="기존 recipient-checkpoint JSON만 검증한다.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_recipient_checkpoint:
        try:
            payload = verify_recipient_checkpoint_file(args.verify_recipient_checkpoint)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit recipient-checkpoint verification: %s", exc)
            return 1
        logger.info("[PASS] install kit recipient-checkpoint verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("next   : %s", payload.get("operator_next_action"))
        logger.info("body   : %s", payload["recipient_checkpoint_body_sha256"])
        logger.info("zip    : %s", payload["install_kit"]["zip_file"])
        return 0

    try:
        result = check_recipient_checkpoint(
            output_dir=args.output_dir,
            skip_verify=bool(args.skip_verify),
            install_share_receipt=args.install_share_receipt,
            gold_path_share_receipt=args.gold_path_share_receipt,
            mcp_operability_receipt=args.mcp_operability_receipt,
            recipient_ack_private_sha256=args.recipient_ack_private_sha256,
            recipient_ack_private_file=args.recipient_ack_private_file,
            recipient_private_sha256=args.recipient_private_sha256,
            recipient_private_file=args.recipient_private_file,
            operator_dispatch_note_private_sha256=args.operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file=args.operator_dispatch_note_private_file,
            operator_status_receipt=args.operator_status_receipt,
            require_operator_status_receipt=bool(args.require_operator_status_receipt),
            manual_send_go_receipt=args.manual_send_go_receipt,
            require_manual_send_go_receipt=bool(args.require_manual_send_go_receipt),
            sent_at_utc=args.sent_at_utc,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[FAIL] install kit recipient-checkpoint: %s", exc)
        return 1

    logger.info("[PASS] install kit recipient-checkpoint")
    logger.info("verdict: %s", result["verdict"])
    logger.info("next   : %s", result["operator_next_action"])
    logger.info("record : %s", result["recipient_checkpoint_md"])
    logger.info("zip    : %s", result["zip_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
