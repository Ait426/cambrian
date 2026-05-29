"""Install kit first-recipient dispatch record gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_cambrian_install_kit_send_ready import (  # noqa: E402
    SEND_READY_JSON_NAME,
    SEND_READY_MD_NAME,
    check_send_ready,
    verify_send_ready_file,
)
from scripts.prepare_cambrian_install_kit_release import (  # noqa: E402
    RELEASE_BUNDLE_NAME,
    verify_release_bundle_current_artifacts,
)
from scripts.smoke_cambrian_install_kit_release_bundle import (  # noqa: E402
    BUNDLE_SMOKE_RECEIPT_NAME,
    verify_bundle_smoke_receipt_file,
)


DISPATCH_RECORD_SCHEMA_VERSION = "cambrian_install_kit_dispatch_record_v0_1"
DISPATCH_RECORD_JSON_NAME = "cambrian-install-kit-dispatch-record.json"
DISPATCH_RECORD_MD_NAME = "cambrian-install-kit-dispatch-record.md"
MANUAL_SEND_GO_RECEIPT_NAME = "cambrian-install-kit-first-recipient-manual-send-go-receipt.json"
_MAX_SENT_AT_FUTURE_SKEW = timedelta(minutes=5)

logger = logging.getLogger(__name__)


class InstallKitDispatchRecordError(Exception):
    """Install kit dispatch record gate failure."""


def check_dispatch_record(
    output_dir: Path | None = None,
    skip_verify: bool = False,
    recipient_private_sha256: str | None = None,
    recipient_private_file: Path | None = None,
    operator_dispatch_note_private_sha256: str | None = None,
    operator_dispatch_note_private_file: Path | None = None,
    operator_status_receipt: Path | None = None,
    require_operator_status_receipt: bool = False,
    manual_send_go_receipt: Path | None = None,
    require_manual_send_go_receipt: bool = False,
    sent_at_utc: str | None = None,
    allow_synthetic_rehearsal_without_manual_send_go_receipt: bool = False,
    synthetic_rehearsal_without_real_recipient: bool = False,
) -> dict[str, Any]:
    """Create a private-safe first-recipient dispatch record."""
    dist = (output_dir or ROOT / "dist").resolve()
    dist.mkdir(parents=True, exist_ok=True)
    if sent_at_utc is not None:
        sent_at_utc = _validated_sent_at_utc(sent_at_utc)
    resolved_recipient_sha256 = _resolve_private_sha256(
        direct_sha256=recipient_private_sha256,
        private_file=recipient_private_file,
        label="recipient identifier",
    )
    resolved_operator_note_sha256 = _resolve_private_sha256(
        direct_sha256=operator_dispatch_note_private_sha256,
        private_file=operator_dispatch_note_private_file,
        label="operator dispatch note",
    )
    sent_recorded = _sent_recorded(
        resolved_recipient_sha256,
        resolved_operator_note_sha256,
        sent_at_utc,
    )
    if sent_recorded and _uses_standard_first_recipient_files(
        recipient_private_file=recipient_private_file,
        operator_dispatch_note_private_file=operator_dispatch_note_private_file,
    ):
        require_operator_status_receipt = True
        require_manual_send_go_receipt = not allow_synthetic_rehearsal_without_manual_send_go_receipt
    send_ready_path = dist / SEND_READY_JSON_NAME
    if send_ready_path.exists():
        send_ready = verify_send_ready_file(send_ready_path)
    else:
        send_ready_result = check_send_ready(output_dir=dist, skip_verify=skip_verify)
        send_ready_path = Path(str(send_ready_result["send_ready_json"]))
        send_ready = verify_send_ready_file(send_ready_path)
    release_bundle_smoke_path = dist / BUNDLE_SMOKE_RECEIPT_NAME
    release_bundle_smoke = verify_bundle_smoke_receipt_file(release_bundle_smoke_path)
    release_bundle_current_artifacts = _release_bundle_current_artifacts_summary(dist)
    operator_status_summary = _operator_status_summary(
        operator_status_receipt=operator_status_receipt,
        require_operator_status_receipt=require_operator_status_receipt,
        recipient_private_sha256=resolved_recipient_sha256,
        operator_dispatch_note_private_sha256=resolved_operator_note_sha256,
        release_bundle_smoke=release_bundle_smoke,
        release_bundle_current_artifacts=release_bundle_current_artifacts,
        sent_at_utc=sent_at_utc,
    )
    if manual_send_go_receipt is None and operator_status_receipt is not None:
        candidate = operator_status_receipt.with_name(MANUAL_SEND_GO_RECEIPT_NAME)
        if candidate.is_file():
            manual_send_go_receipt = candidate
    manual_send_go_summary = _manual_send_go_summary(
        manual_send_go_receipt=manual_send_go_receipt,
        require_manual_send_go_receipt=require_manual_send_go_receipt,
        recipient_private_sha256=resolved_recipient_sha256,
        operator_dispatch_note_private_sha256=resolved_operator_note_sha256,
        release_bundle_smoke=release_bundle_smoke,
        operator_status_summary=operator_status_summary,
        sent_at_utc=sent_at_utc,
    )
    payload = _dispatch_record_payload(
        send_ready=send_ready,
        release_bundle_smoke=release_bundle_smoke,
        release_bundle_current_artifacts=release_bundle_current_artifacts,
        recipient_private_sha256=resolved_recipient_sha256,
        operator_dispatch_note_private_sha256=resolved_operator_note_sha256,
        operator_status_summary=operator_status_summary,
        manual_send_go_summary=manual_send_go_summary,
        sent_at_utc=sent_at_utc,
        synthetic_rehearsal_without_manual_send_go_receipt=allow_synthetic_rehearsal_without_manual_send_go_receipt,
        synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
    )

    json_path = dist / DISPATCH_RECORD_JSON_NAME
    md_path = dist / DISPATCH_RECORD_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_dispatch_record_markdown(payload), encoding="utf-8")
    verify_dispatch_record_file(
        json_path,
        allow_synthetic_rehearsal=(
            allow_synthetic_rehearsal_without_manual_send_go_receipt
            or synthetic_rehearsal_without_real_recipient
        ),
    )
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "dispatch_record_json": str(json_path),
        "dispatch_record_md": str(md_path),
        "send_ready_json": str(send_ready_path),
        "zip_file": payload["install_kit"]["zip_file"],
        "zip_sha256": payload["install_kit"]["zip_sha256"],
        "dispatch_record_body_sha256": payload["dispatch_record_body_sha256"],
    }


def verify_dispatch_record_file(path: Path, *, allow_synthetic_rehearsal: bool = False) -> dict[str, Any]:
    """Verify an existing dispatch-record JSON without regenerating it."""
    payload = _read_json(path)
    verify_dispatch_record_payload(payload, allow_synthetic_rehearsal=allow_synthetic_rehearsal)
    return payload


def verify_dispatch_record_payload(payload: dict[str, Any], *, allow_synthetic_rehearsal: bool = False) -> None:
    """Verify dispatch scope, hash chain, and share-safety boundaries."""
    if payload.get("schema_version") != DISPATCH_RECORD_SCHEMA_VERSION:
        raise InstallKitDispatchRecordError("install kit dispatch-record schema_version이 올바르지 않습니다.")
    if payload.get("status") not in {"ready_to_dispatch_one", "dispatch_recorded"}:
        raise InstallKitDispatchRecordError(f"install kit dispatch-record status가 올바르지 않습니다: {payload.get('status')}")
    if payload.get("verdict") not in {"READY_TO_SEND_ONE", "SENT_ONE_RECORDED"}:
        raise InstallKitDispatchRecordError(f"install kit dispatch-record verdict가 올바르지 않습니다: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise InstallKitDispatchRecordError("install kit dispatch-record safe_to_share가 true가 아닙니다.")

    synthetic_boundary = (
        payload.get("synthetic_rehearsal_boundary")
        if isinstance(payload.get("synthetic_rehearsal_boundary"), dict)
        else None
    )
    if synthetic_boundary is not None and not allow_synthetic_rehearsal:
        raise InstallKitDispatchRecordError(
            "synthetic rehearsal dispatch records are not standalone send evidence."
        )

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise InstallKitDispatchRecordError("install kit dispatch-record checks가 모두 true가 아닙니다.")

    body_hash = payload.get("dispatch_record_body_sha256")
    if body_hash != _dispatch_record_body_sha256(payload):
        raise InstallKitDispatchRecordError("install kit dispatch-record 본문 해시가 일치하지 않습니다.")
    recalculated = _dispatch_record_checks(payload)
    if payload.get("dispatch_record_checks") != recalculated:
        raise InstallKitDispatchRecordError("install kit dispatch-record 안전 평가 결과가 현재 본문과 일치하지 않습니다.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise InstallKitDispatchRecordError("install kit dispatch-record 안전 평가 실패: " + ", ".join(failed))


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


def _operator_status_summary(
    *,
    operator_status_receipt: Path | None,
    require_operator_status_receipt: bool,
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    release_bundle_smoke: dict[str, Any],
    release_bundle_current_artifacts: dict[str, Any],
    sent_at_utc: str | None,
) -> dict[str, Any] | None:
    sent_recorded = _sent_recorded(
        recipient_private_sha256=recipient_private_sha256,
        operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
        sent_at_utc=sent_at_utc,
    )
    if sent_recorded and require_operator_status_receipt and operator_status_receipt is None:
        raise InstallKitDispatchRecordError(
            "operator status receipt is required before recording SENT_ONE_RECORDED."
        )
    if operator_status_receipt is None:
        return None

    payload = _verify_operator_status_receipt_file(operator_status_receipt)
    status_summary = (
        payload.get("operator_status_summary") if isinstance(payload.get("operator_status_summary"), dict) else {}
    )
    private_hashes = payload.get("private_hashes") if isinstance(payload.get("private_hashes"), dict) else {}
    release = payload.get("release_bundle") if isinstance(payload.get("release_bundle"), dict) else {}
    release_bundle = (
        release_bundle_smoke.get("release_bundle")
        if isinstance(release_bundle_smoke.get("release_bundle"), dict)
        else {}
    )
    open_gate_ids = status_summary.get("open_gate_ids") if isinstance(status_summary.get("open_gate_ids"), list) else []
    ready_to_send_one = (
        payload.get("verdict") == "READY_TO_MANUALLY_SEND_ONE"
        and status_summary.get("send_state") == "READY_TO_SEND"
        and status_summary.get("manual_send_allowed") is True
        and open_gate_ids == []
    )
    release_hash_matches = release.get("sha256") == release_bundle.get("sha256")
    release_current_artifacts_match = release_bundle_current_artifacts.get("current_artifacts_match")
    release_current_artifacts_gate_passed = release_current_artifacts_match is not False
    private_hashes_match = (
        private_hashes.get("recipient_private_sha256") == recipient_private_sha256
        and private_hashes.get("operator_dispatch_note_private_sha256") == operator_dispatch_note_private_sha256
    )
    summary = {
        "required": bool(require_operator_status_receipt and sent_recorded),
        "present": True,
        "file": operator_status_receipt.name,
        "verified_standalone": True,
        "body_sha256": payload.get("operator_status_receipt_body_sha256"),
        "verdict": payload.get("verdict"),
        "send_state": status_summary.get("send_state"),
        "manual_send_allowed": status_summary.get("manual_send_allowed") is True,
        "open_gate_ids": [str(item) for item in open_gate_ids],
        "ready_to_send_one": ready_to_send_one,
        "release_bundle_sha256": release.get("sha256"),
        "release_hash_matches_dispatch": release_hash_matches,
        "release_current_artifacts_checked": release_bundle_current_artifacts.get("comparison_applicable") is True,
        "release_current_artifacts_match_dispatch": release_current_artifacts_match,
        "release_current_artifacts_gate_passed": release_current_artifacts_gate_passed,
        "release_current_artifacts_status": release_bundle_current_artifacts.get("status"),
        "private_hashes_match_dispatch": private_hashes_match,
        "raw_private_values_included": False,
        "absolute_paths_included": False,
    }
    if sent_recorded and require_operator_status_receipt:
        if not ready_to_send_one:
            raise InstallKitDispatchRecordError(
                "operator status receipt must be READY_TO_MANUALLY_SEND_ONE before recording SENT_ONE_RECORDED."
            )
        if not release_hash_matches:
            raise InstallKitDispatchRecordError(
                "operator status receipt release hash does not match the dispatch release bundle."
            )
        if not release_current_artifacts_gate_passed:
            raise InstallKitDispatchRecordError(
                "operator status receipt release bundle current artifacts do not match current dist."
            )
        if not private_hashes_match:
            raise InstallKitDispatchRecordError(
                "operator status receipt private hashes do not match the dispatch private files."
            )
    return summary


def _verify_operator_status_receipt_file(path: Path) -> dict[str, Any]:
    from scripts.check_cambrian_install_kit_first_recipient_operator_status import (  # noqa: PLC0415
        verify_first_recipient_operator_status_receipt_file,
    )

    return verify_first_recipient_operator_status_receipt_file(path)


def _manual_send_go_summary(
    *,
    manual_send_go_receipt: Path | None,
    require_manual_send_go_receipt: bool,
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    release_bundle_smoke: dict[str, Any],
    operator_status_summary: dict[str, Any] | None,
    sent_at_utc: str | None,
) -> dict[str, Any] | None:
    sent_recorded = _sent_recorded(
        recipient_private_sha256=recipient_private_sha256,
        operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
        sent_at_utc=sent_at_utc,
    )
    if sent_recorded and require_manual_send_go_receipt and manual_send_go_receipt is None:
        raise InstallKitDispatchRecordError(
            "manual-send GO receipt is required before recording SENT_ONE_RECORDED."
        )
    if manual_send_go_receipt is None:
        return None

    payload = _verify_manual_send_go_receipt_file(manual_send_go_receipt)
    release = payload.get("release_bundle") if isinstance(payload.get("release_bundle"), dict) else {}
    release_bundle = (
        release_bundle_smoke.get("release_bundle")
        if isinstance(release_bundle_smoke.get("release_bundle"), dict)
        else {}
    )
    operator_gate = (
        payload.get("gate_receipts", {}).get("operator_status")
        if isinstance(payload.get("gate_receipts"), dict)
        and isinstance(payload.get("gate_receipts", {}).get("operator_status"), dict)
        else {}
    )
    pre_send_gate = (
        payload.get("gate_receipts", {}).get("pre_send_sequence")
        if isinstance(payload.get("gate_receipts"), dict)
        and isinstance(payload.get("gate_receipts", {}).get("pre_send_sequence"), dict)
        else {}
    )
    ready_to_send_one = (
        payload.get("status") == "pass"
        and payload.get("verdict") == "GO_TO_MANUALLY_SEND_ONE"
        and all(value is True for value in (payload.get("checks") or {}).values())
    )
    release_hash_matches = release.get("sha256") == release_bundle.get("sha256")
    operator_status_body_matches = (
        operator_status_summary is None
        or operator_status_summary.get("body_sha256") == operator_gate.get("body_sha256")
    )
    operator_status_ready_receipt_matches = operator_gate.get("ready_receipt_file") == (
        operator_status_summary or {}
    ).get("file")
    summary = {
        "required": bool(require_manual_send_go_receipt and sent_recorded),
        "present": True,
        "file": manual_send_go_receipt.name,
        "verified_standalone": True,
        "body_sha256": payload.get("manual_send_go_receipt_body_sha256"),
        "verdict": payload.get("verdict"),
        "ready_to_send_one": ready_to_send_one,
        "release_bundle_sha256": release.get("sha256"),
        "release_hash_matches_dispatch": release_hash_matches,
        "pre_send_sequence_file": pre_send_gate.get("file"),
        "pre_send_sequence_verdict": pre_send_gate.get("verdict"),
        "pre_send_sequence_body_sha256": pre_send_gate.get("body_sha256"),
        "operator_status_ready_receipt_matches": operator_status_ready_receipt_matches,
        "operator_status_body_matches_dispatch": operator_status_body_matches,
        "operator_status_body_sha256": operator_gate.get("body_sha256"),
        "raw_private_values_included": False,
        "absolute_paths_included": False,
    }
    if sent_recorded and require_manual_send_go_receipt:
        if not ready_to_send_one:
            raise InstallKitDispatchRecordError(
                "manual-send GO receipt must be GO_TO_MANUALLY_SEND_ONE before recording SENT_ONE_RECORDED."
            )
        if not release_hash_matches:
            raise InstallKitDispatchRecordError(
                "manual-send GO receipt release hash does not match the dispatch release bundle."
            )
        if not operator_status_body_matches or not operator_status_ready_receipt_matches:
            raise InstallKitDispatchRecordError(
                "manual-send GO receipt does not match the dispatch operator status receipt."
            )
    return summary


def _verify_manual_send_go_receipt_file(path: Path) -> dict[str, Any]:
    from scripts.check_cambrian_install_kit_first_recipient_manual_send_go import (  # noqa: PLC0415
        verify_first_recipient_manual_send_go_receipt_file,
    )

    return verify_first_recipient_manual_send_go_receipt_file(path)


def _dispatch_record_payload(
    send_ready: dict[str, Any],
    release_bundle_smoke: dict[str, Any],
    release_bundle_current_artifacts: dict[str, Any],
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    operator_status_summary: dict[str, Any] | None,
    manual_send_go_summary: dict[str, Any] | None,
    sent_at_utc: str | None,
    synthetic_rehearsal_without_manual_send_go_receipt: bool = False,
    synthetic_rehearsal_without_real_recipient: bool = False,
) -> dict[str, Any]:
    sent_recorded = _sent_recorded(
        recipient_private_sha256=recipient_private_sha256,
        operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
        sent_at_utc=sent_at_utc,
    )
    status = "dispatch_recorded" if sent_recorded else "ready_to_dispatch_one"
    verdict = "SENT_ONE_RECORDED" if sent_recorded else "READY_TO_SEND_ONE"
    policy = send_ready.get("dispatch_execution_policy") if isinstance(send_ready.get("dispatch_execution_policy"), dict) else {}
    dispatch_policy = {
        "script_sends_to_recipient": policy.get("script_sends_to_recipient") is True,
        "script_sends_copy_paste_message": policy.get("script_sends_copy_paste_message") is True,
        "manual_operator_dispatch_required": policy.get("manual_operator_dispatch_required") is True,
        "max_recipients_per_record": int(policy.get("max_recipients_per_record") or 1),
        "records_private_sha256_only": True,
        "sent_recorded_by_private_hashes_only": sent_recorded,
    }
    copy_paste_message = str(send_ready.get("copy_paste_message") or "")
    release_bundle = (
        release_bundle_smoke.get("release_bundle")
        if isinstance(release_bundle_smoke.get("release_bundle"), dict)
        else {}
    )
    gold_path_summary = (
        release_bundle_smoke.get("gold_path_share_receipt")
        if isinstance(release_bundle_smoke.get("gold_path_share_receipt"), dict)
        else {}
    )
    checks = {
        "send_ready_go": send_ready.get("verdict") == "GO",
        "send_ready_checks_true": _all_true(send_ready.get("send_ready_checks")),
        "release_bundle_smoke_receipt_status_pass": release_bundle_smoke.get("status") == "pass",
        "release_bundle_smoke_receipt_checks_true": _all_true(release_bundle_smoke.get("checks"))
        and _all_true(release_bundle_smoke.get("receipt_checks")),
        "release_bundle_smoke_gold_path_confirmed": gold_path_summary.get("status") == "passed"
        and gold_path_summary.get("capabilities_all_true") is True,
        "release_bundle_smoke_mcp_operability_verified": gold_path_summary.get("mcp_operability_verified") is True,
        "release_bundle_smoke_claim_boundaries_locked": (
            release_bundle_smoke.get("claim_boundaries", {}).get("public_proof_claim_allowed") is False
            and release_bundle_smoke.get("claim_boundaries", {}).get("sale_ready") is False
            and release_bundle_smoke.get("claim_boundaries", {}).get("success_rate_claim_allowed") is False
        ),
        "manual_operator_dispatch_required": dispatch_policy["manual_operator_dispatch_required"] is True,
        "script_does_not_send_to_recipient": dispatch_policy["script_sends_to_recipient"] is False,
        "script_does_not_send_copy_paste_message": dispatch_policy["script_sends_copy_paste_message"] is False,
        "max_one_recipient": dispatch_policy["max_recipients_per_record"] == 1,
        "copy_paste_message_hashed": _looks_like_sha256(_text_sha256(copy_paste_message)),
        "copy_paste_message_mentions_bundle_installer": "INSTALL_CAMBRIAN_FROM_BUNDLE.py" in copy_paste_message,
        "copy_paste_message_mentions_gold_path_runner": "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py" in copy_paste_message,
        "copy_paste_message_mentions_share_receipt": "cambrian_install_share_receipt.json" in copy_paste_message,
        "copy_paste_message_mentions_gold_path_share_receipt": "cambrian_gold_path_share_receipt.json" in copy_paste_message,
        "copy_paste_message_mentions_mcp_operability_receipt": "mcp_operability_receipt.json" in copy_paste_message,
        "copy_paste_message_marks_local_validation_only": "local validation evidence only" in copy_paste_message,
        "copy_paste_message_blocks_public_proof_claims": "do not claim public proof" in copy_paste_message,
        "copy_paste_message_blocks_first_recipient_claims": (
            "First-recipient confirmation requires a real human send" in copy_paste_message
        ),
        "private_hashes_valid_or_absent": _private_hashes_valid_or_absent(
            recipient_private_sha256=recipient_private_sha256,
            operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
            sent_at_utc=sent_at_utc,
        ),
        "operator_status_receipt_required_when_sent": (not sent_recorded)
        or operator_status_summary is None
        or operator_status_summary.get("required") is False
        or operator_status_summary.get("verified_standalone") is True,
        "operator_status_ready_when_sent": (not sent_recorded)
        or operator_status_summary is None
        or operator_status_summary.get("required") is False
        or operator_status_summary.get("ready_to_send_one") is True,
        "operator_status_release_hash_matches_when_present": operator_status_summary is None
        or operator_status_summary.get("release_hash_matches_dispatch") is True,
        "operator_status_release_current_artifacts_match_when_present": operator_status_summary is None
        or operator_status_summary.get("release_current_artifacts_match_dispatch") is not False,
        "operator_status_private_hashes_match_when_present": operator_status_summary is None
        or (not sent_recorded)
        or operator_status_summary.get("private_hashes_match_dispatch") is True,
        "manual_send_go_receipt_required_when_sent": (not sent_recorded)
        or manual_send_go_summary is None
        or manual_send_go_summary.get("required") is False
        or manual_send_go_summary.get("verified_standalone") is True,
        "manual_send_go_ready_when_sent": (not sent_recorded)
        or manual_send_go_summary is None
        or manual_send_go_summary.get("required") is False
        or manual_send_go_summary.get("ready_to_send_one") is True,
        "manual_send_go_release_hash_matches_when_present": manual_send_go_summary is None
        or manual_send_go_summary.get("release_hash_matches_dispatch") is True,
        "manual_send_go_operator_status_matches_when_present": manual_send_go_summary is None
        or (not sent_recorded)
        or (
            manual_send_go_summary.get("operator_status_ready_receipt_matches") is True
            and manual_send_go_summary.get("operator_status_body_matches_dispatch") is True
        ),
        "no_success_or_proof_claim": True,
        "sale_ready_blocked": True,
    }
    payload: dict[str, Any] = {
        "schema_version": DISPATCH_RECORD_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "verdict": verdict,
        "safe_to_share": True,
        "install_kit": send_ready.get("install_kit"),
        "send_ready": {
            "file": SEND_READY_JSON_NAME,
            "markdown_file": SEND_READY_MD_NAME,
            "body_sha256": send_ready.get("send_ready_body_sha256"),
            "verified_standalone": True,
        },
        "release_bundle_smoke": {
            "file": BUNDLE_SMOKE_RECEIPT_NAME,
            "body_sha256": release_bundle_smoke.get("bundle_smoke_receipt_body_sha256"),
            "release_bundle_file": Path(str(release_bundle.get("file") or "")).name,
            "release_bundle_sha256": release_bundle.get("sha256"),
            "gold_path_capabilities_all_true": gold_path_summary.get("capabilities_all_true") is True,
            "mcp_operability_verified": gold_path_summary.get("mcp_operability_verified") is True,
            "gold_path_capabilities_verified": gold_path_summary.get("capabilities_verified", {}),
            "verified_standalone": True,
        },
        "release_bundle_current_artifacts": release_bundle_current_artifacts,
        "dispatch_record": {
            "sent_recorded": sent_recorded,
            "sent_at_utc": sent_at_utc if sent_recorded else None,
            "recipient_private_sha256": recipient_private_sha256 if sent_recorded else None,
            "operator_dispatch_note_private_sha256": operator_dispatch_note_private_sha256 if sent_recorded else None,
            "raw_recipient_included": False,
            "raw_operator_note_included": False,
        },
        "operator_status_pre_send": operator_status_summary
        or {
            "required": False,
            "present": False,
            "verified_standalone": False,
            "ready_to_send_one": False,
        },
        "manual_send_go_pre_send": manual_send_go_summary
        or {
            "required": False,
            "present": False,
            "verified_standalone": False,
            "ready_to_send_one": False,
        },
        "dispatch_scope": {
            "target_recipients": 1,
            "max_recipients_per_record": 1,
            "cohort_scaling_allowed": False,
            "marketplace_listing_allowed": False,
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
        },
        "dispatch_execution_policy": dispatch_policy,
        "send_materials": {
            "zip_file": (send_ready.get("install_kit") or {}).get("zip_file"),
            "copy_paste_message_sha256": _text_sha256(copy_paste_message),
            "copy_paste_message_policy": {
                "bundle_installer_named": "INSTALL_CAMBRIAN_FROM_BUNDLE.py" in copy_paste_message,
                "gold_path_runner_named": "RUN_CAMBRIAN_GOLD_PATH_FROM_BUNDLE.py" in copy_paste_message,
                "share_receipt_named": "cambrian_install_share_receipt.json" in copy_paste_message,
                "gold_path_share_receipt_named": "cambrian_gold_path_share_receipt.json" in copy_paste_message,
                "mcp_operability_receipt_named": "mcp_operability_receipt.json" in copy_paste_message,
                "local_validation_only": "local validation evidence only" in copy_paste_message,
                "public_proof_claim_blocked": "do not claim public proof" in copy_paste_message,
                "first_recipient_confirmation_requires_real_send": (
                    "First-recipient confirmation requires a real human send" in copy_paste_message
                ),
                "no_secret_request": ".env" in copy_paste_message and "비밀값" in copy_paste_message,
                "no_raw_screenshot_request": "스크린샷 원문" in copy_paste_message,
            },
        },
        "checks": checks,
        "artifact_chain": [
            *_sanitize_artifact_chain(send_ready.get("artifact_chain")),
            {
                "kind": "install_kit_send_ready",
                "file": SEND_READY_JSON_NAME,
                "sha256": str(send_ready.get("send_ready_body_sha256") or ""),
            },
            {
                "kind": "install_kit_release_bundle_smoke",
                "file": BUNDLE_SMOKE_RECEIPT_NAME,
                "sha256": str(release_bundle_smoke.get("bundle_smoke_receipt_body_sha256") or ""),
            },
            *(
                [
                    {
                        "kind": "install_kit_operator_status",
                        "file": str(operator_status_summary.get("file") or ""),
                        "sha256": str(operator_status_summary.get("body_sha256") or ""),
                    }
                ]
                if operator_status_summary is not None
                else []
            ),
            *(
                [
                    {
                        "kind": "install_kit_manual_send_go",
                        "file": str(manual_send_go_summary.get("file") or ""),
                        "sha256": str(manual_send_go_summary.get("body_sha256") or ""),
                    }
                ]
                if manual_send_go_summary is not None
                else []
            ),
        ],
        "metrics": {
            "success_rate": None,
            "proof_claim_allowed": False,
            "sale_ready": False,
        },
        "do_not_share": send_ready.get("do_not_share"),
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
    }
    if synthetic_rehearsal_without_manual_send_go_receipt or synthetic_rehearsal_without_real_recipient:
        payload["synthetic_rehearsal_boundary"] = {
            "synthetic_rehearsal": True,
            "standalone_send_evidence_allowed": False,
            "real_manual_send": False,
            "real_recipient_evidence": False,
            "synthetic_private_inputs": True,
            "manual_send_go_receipt_omitted_by_rehearsal_only_exception": (
                synthetic_rehearsal_without_manual_send_go_receipt
            ),
            "post_send_rehearsal_without_real_recipient": synthetic_rehearsal_without_real_recipient,
        }
    payload["dispatch_record_body_sha256"] = _dispatch_record_body_sha256(payload)
    payload["artifact_chain"].append(
        {
            "kind": "install_kit_dispatch_record",
            "file": DISPATCH_RECORD_JSON_NAME,
            "sha256": payload["dispatch_record_body_sha256"],
        }
    )
    payload["dispatch_record_checks"] = _dispatch_record_checks(payload)
    return payload


def _dispatch_record_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "dispatch_record_body_sha256", "dispatch_record_checks"}
    }
    if isinstance(body.get("artifact_chain"), list):
        body["artifact_chain"] = [
            item
            for item in body["artifact_chain"]
            if not (isinstance(item, dict) and item.get("kind") == "install_kit_dispatch_record")
        ]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _dispatch_record_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    root = str(ROOT)
    home = str(Path.home())
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    policy = payload.get("dispatch_execution_policy") if isinstance(payload.get("dispatch_execution_policy"), dict) else {}
    scope = payload.get("dispatch_scope") if isinstance(payload.get("dispatch_scope"), dict) else {}
    record = payload.get("dispatch_record") if isinstance(payload.get("dispatch_record"), dict) else {}
    operator_status = (
        payload.get("operator_status_pre_send")
        if isinstance(payload.get("operator_status_pre_send"), dict)
        else {}
    )
    manual_go = (
        payload.get("manual_send_go_pre_send")
        if isinstance(payload.get("manual_send_go_pre_send"), dict)
        else {}
    )
    body_hash = payload.get("dispatch_record_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == DISPATCH_RECORD_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": {
            "install_kit_zip",
            "install_kit_receipt",
            "install_kit_handoff",
            "install_kit_send_ready",
            "install_kit_release_bundle_smoke",
            "install_kit_dispatch_record",
        }.issubset({str(item.get("kind") or "") for item in chain if isinstance(item, dict)}),
        "artifact_chain_self_hash_matched": any(
            item.get("kind") == "install_kit_dispatch_record"
            and item.get("sha256") == body_hash
            and item.get("file") == DISPATCH_RECORD_JSON_NAME
            for item in chain
            if isinstance(item, dict)
        ),
        "manual_dispatch_only": policy.get("script_sends_to_recipient") is False
        and policy.get("script_sends_copy_paste_message") is False
        and policy.get("manual_operator_dispatch_required") is True,
        "one_recipient_only": policy.get("max_recipients_per_record") == 1
        and scope.get("target_recipients") == 1
        and scope.get("cohort_scaling_allowed") is False,
        "private_hash_only_recording": policy.get("records_private_sha256_only") is True
        and record.get("raw_recipient_included") is False
        and record.get("raw_operator_note_included") is False,
        "operator_status_required_when_requested": (operator_status.get("required") is not True)
        or operator_status.get("verified_standalone") is True,
        "operator_status_ready_when_required": (operator_status.get("required") is not True)
        or (
            operator_status.get("ready_to_send_one") is True
            and operator_status.get("verdict") == "READY_TO_MANUALLY_SEND_ONE"
            and operator_status.get("send_state") == "READY_TO_SEND"
            and operator_status.get("manual_send_allowed") is True
        ),
        "operator_status_hashes_match_when_required": (operator_status.get("required") is not True)
        or (
            operator_status.get("release_hash_matches_dispatch") is True
            and operator_status.get("private_hashes_match_dispatch") is True
        ),
        "operator_status_current_artifacts_match_when_required": (operator_status.get("required") is not True)
        or operator_status.get("release_current_artifacts_match_dispatch") is not False,
        "operator_status_summary_share_safe": operator_status.get("raw_private_values_included") is not True
        and operator_status.get("absolute_paths_included") is not True
        and (
            operator_status.get("file") is None
            or Path(str(operator_status.get("file"))).name == operator_status.get("file")
        ),
        "manual_send_go_required_when_requested": (manual_go.get("required") is not True)
        or manual_go.get("verified_standalone") is True,
        "manual_send_go_ready_when_required": (manual_go.get("required") is not True)
        or (
            manual_go.get("ready_to_send_one") is True
            and manual_go.get("verdict") == "GO_TO_MANUALLY_SEND_ONE"
            and manual_go.get("release_hash_matches_dispatch") is True
            and manual_go.get("operator_status_ready_receipt_matches") is True
            and manual_go.get("operator_status_body_matches_dispatch") is True
        ),
        "manual_send_go_summary_share_safe": manual_go.get("raw_private_values_included") is not True
        and manual_go.get("absolute_paths_included") is not True
        and (
            manual_go.get("file") is None
            or Path(str(manual_go.get("file"))).name == manual_go.get("file")
        ),
        "claim_boundaries_locked": scope.get("proof_claim_allowed") is False
        and scope.get("success_rate_claim_allowed") is False
        and scope.get("marketplace_listing_allowed") is False
        and payload.get("metrics", {}).get("sale_ready") is False,
        "sent_record_consistent": _sent_record_consistent(record, policy),
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _dispatch_record_body_sha256(payload),
    }


def _dispatch_record_markdown(payload: dict[str, Any]) -> str:
    kit = payload["install_kit"] if isinstance(payload.get("install_kit"), dict) else {}
    policy = payload["dispatch_execution_policy"]
    record = payload["dispatch_record"]
    operator_status = (
        payload.get("operator_status_pre_send")
        if isinstance(payload.get("operator_status_pre_send"), dict)
        else {}
    )
    manual_go = (
        payload.get("manual_send_go_pre_send")
        if isinstance(payload.get("manual_send_go_pre_send"), dict)
        else {}
    )
    return f"""# Cambrian Install Kit Dispatch Record

## Verdict

`{payload["verdict"]}`

## Artifact

- ZIP: `{kit.get("zip_file")}`
- ZIP sha256: `{kit.get("zip_sha256")}`
- Send-ready: `{payload["send_ready"]["file"]}`
- Send-ready body sha256: `{payload["send_ready"]["body_sha256"]}`
- Release bundle smoke: `{payload["release_bundle_smoke"]["file"]}`
- Release bundle smoke body sha256: `{payload["release_bundle_smoke"]["body_sha256"]}`
- Required gold path confirmed: {payload["release_bundle_smoke"]["gold_path_capabilities_all_true"]}
- MCP operability verified: {payload["release_bundle_smoke"]["mcp_operability_verified"]}
- Dispatch record body sha256: `{payload["dispatch_record_body_sha256"]}`

## Dispatch Scope

- target recipients: 1
- max recipients per record: 1
- cohort scaling allowed: False
- marketplace listing allowed: False
- proof claim allowed: False
- success rate claim allowed: False

## Dispatch Execution Policy

- script sends to recipient: {policy["script_sends_to_recipient"]}
- script sends copy-paste message: {policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {policy["manual_operator_dispatch_required"]}
- records private sha256 only: {policy["records_private_sha256_only"]}
- sent recorded by private hashes only: {policy["sent_recorded_by_private_hashes_only"]}

## Dispatch Record

- sent recorded: {record["sent_recorded"]}
- sent at UTC: {record["sent_at_utc"]}
- recipient private sha256 present: {record["recipient_private_sha256"] is not None}
- operator dispatch note private sha256 present: {record["operator_dispatch_note_private_sha256"] is not None}

## Operator Status Proof

- required: {operator_status.get("required") is True}
- present: {operator_status.get("present") is True}
- verified standalone: {operator_status.get("verified_standalone") is True}
- verdict: {operator_status.get("verdict")}
- send state: {operator_status.get("send_state")}
- manual send allowed: {operator_status.get("manual_send_allowed") is True}
- release hash matches dispatch: {operator_status.get("release_hash_matches_dispatch") is True}
- release current artifacts checked: {operator_status.get("release_current_artifacts_checked") is True}
- release current artifacts match dispatch: {operator_status.get("release_current_artifacts_match_dispatch") is not False}
- private hashes match dispatch: {operator_status.get("private_hashes_match_dispatch") is True}

## Manual Send GO Proof

- required: {manual_go.get("required") is True}
- present: {manual_go.get("present") is True}
- verified standalone: {manual_go.get("verified_standalone") is True}
- verdict: {manual_go.get("verdict")}
- ready to send one: {manual_go.get("ready_to_send_one") is True}
- release hash matches dispatch: {manual_go.get("release_hash_matches_dispatch") is True}
- operator status receipt matches: {manual_go.get("operator_status_ready_receipt_matches") is True}
- operator status body matches: {manual_go.get("operator_status_body_matches_dispatch") is True}

## Boundary

This record does not send the install kit, does not store recipient raw text, and does not permit public proof, marketplace, sale-ready, or success-rate claims.
"""


def _resolve_private_sha256(
    direct_sha256: str | None,
    private_file: Path | None,
    label: str,
) -> str | None:
    if direct_sha256 and private_file:
        raise InstallKitDispatchRecordError(f"{label}: direct sha256과 private file은 동시에 사용할 수 없습니다.")
    if private_file:
        return hashlib.sha256(private_file.read_bytes()).hexdigest()
    if direct_sha256 is not None and not _looks_like_sha256(direct_sha256):
        raise InstallKitDispatchRecordError(f"{label}: sha256 형식이 아닙니다.")
    return direct_sha256


def _sent_recorded(
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    sent_at_utc: str | None,
) -> bool:
    present = [recipient_private_sha256 is not None, operator_dispatch_note_private_sha256 is not None, sent_at_utc is not None]
    if any(present) and not all(present):
        raise InstallKitDispatchRecordError("sent 기록에는 recipient/note/sent_at 세 값이 모두 필요합니다.")
    return all(present)


def _uses_standard_first_recipient_files(
    *,
    recipient_private_file: Path | None,
    operator_dispatch_note_private_file: Path | None,
) -> bool:
    return (
        isinstance(recipient_private_file, Path)
        and isinstance(operator_dispatch_note_private_file, Path)
        and recipient_private_file.name == "recipient-private.txt"
        and operator_dispatch_note_private_file.name == "operator-dispatch-note-private.md"
    )


def _validated_sent_at_utc(value: str) -> str:
    sent_at = value.strip()
    if not sent_at or "<" in sent_at or ">" in sent_at:
        raise InstallKitDispatchRecordError(
            "sent_at_utc must be the real UTC manual-send timestamp, not a placeholder."
        )
    try:
        parsed = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InstallKitDispatchRecordError("sent_at_utc must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise InstallKitDispatchRecordError("sent_at_utc must include UTC timezone, such as 2026-05-15T10:00:00Z.")
    if parsed.astimezone(timezone.utc) > datetime.now(timezone.utc) + _MAX_SENT_AT_FUTURE_SKEW:
        raise InstallKitDispatchRecordError("sent_at_utc must not be in the future.")
    return sent_at


def _private_hashes_valid_or_absent(
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    sent_at_utc: str | None,
) -> bool:
    if recipient_private_sha256 is None and operator_dispatch_note_private_sha256 is None and sent_at_utc is None:
        return True
    return (
        _looks_like_sha256(recipient_private_sha256)
        and _looks_like_sha256(operator_dispatch_note_private_sha256)
        and isinstance(sent_at_utc, str)
        and _sent_at_utc_is_valid(sent_at_utc)
    )


def _sent_record_consistent(record: dict[str, Any], policy: dict[str, Any]) -> bool:
    if record.get("sent_recorded") is True:
        return (
            _looks_like_sha256(record.get("recipient_private_sha256"))
            and _looks_like_sha256(record.get("operator_dispatch_note_private_sha256"))
            and _sent_at_utc_is_valid(record.get("sent_at_utc"))
            and policy.get("sent_recorded_by_private_hashes_only") is True
        )
    return (
        record.get("recipient_private_sha256") is None
        and record.get("operator_dispatch_note_private_sha256") is None
        and record.get("sent_at_utc") is None
        and policy.get("sent_recorded_by_private_hashes_only") is False
    )


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


def _sent_at_utc_is_valid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        _validated_sent_at_utc(value)
    except InstallKitDispatchRecordError:
        return False
    return True


def _all_true(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise InstallKitDispatchRecordError("JSON 객체가 아닙니다.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cambrian install kit 첫 수령자 발송 기록 장부를 생성한다.")
    parser.add_argument("--output-dir", type=Path, default=None, help="산출물 출력 폴더. 기본값은 dist")
    parser.add_argument("--skip-verify", action="store_true", help="send-ready 준비 시 ZIP 재검증을 건너뛴다.")
    parser.add_argument("--recipient-private-sha256", default=None, help="수령자 원문 식별자 대신 저장할 sha256")
    parser.add_argument("--recipient-private-file", type=Path, default=None, help="수령자 원문 파일. 내용과 경로는 저장하지 않고 sha256만 계산한다.")
    parser.add_argument("--operator-dispatch-note-private-sha256", default=None, help="운영 발송 노트 원문 대신 저장할 sha256")
    parser.add_argument("--operator-dispatch-note-private-file", type=Path, default=None, help="운영 발송 노트 파일. 내용과 경로는 저장하지 않고 sha256만 계산한다.")
    parser.add_argument("--sent-at-utc", default=None, help="실제 발송 시각. 예: 2026-05-15T10:00:00+00:00")
    parser.add_argument("--verify-dispatch-record", type=Path, default=None, help="기존 dispatch-record JSON만 검증한다.")
    parser.add_argument("--operator-status-receipt", type=Path, default=None, help="READY_TO_MANUALLY_SEND_ONE operator status receipt JSON.")
    parser.add_argument("--require-operator-status-receipt", action="store_true", help="Require a READY_TO_MANUALLY_SEND_ONE operator status receipt before recording SENT_ONE_RECORDED.")
    parser.add_argument("--manual-send-go-receipt", type=Path, default=None, help="GO_TO_MANUALLY_SEND_ONE manual-send GO receipt JSON.")
    parser.add_argument("--require-manual-send-go-receipt", action="store_true", help="Require a GO_TO_MANUALLY_SEND_ONE manual-send GO receipt before recording SENT_ONE_RECORDED.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_dispatch_record:
        try:
            payload = verify_dispatch_record_file(args.verify_dispatch_record)
        except Exception as exc:  # noqa: BLE001 - 운영 게이트 실패 이유를 그대로 보여준다.
            logger.error("[FAIL] install kit dispatch-record verification: %s", exc)
            return 1
        logger.info("[PASS] install kit dispatch-record verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["dispatch_record_body_sha256"])
        logger.info("zip    : %s", payload["install_kit"]["zip_file"])
        return 0

    try:
        result = check_dispatch_record(
            output_dir=args.output_dir,
            skip_verify=bool(args.skip_verify),
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
    except Exception as exc:  # noqa: BLE001 - 운영 게이트 실패 이유를 그대로 보여준다.
        logger.error("[FAIL] install kit dispatch-record: %s", exc)
        return 1

    logger.info("[PASS] install kit dispatch-record")
    logger.info("verdict: %s", result["verdict"])
    logger.info("record : %s", result["dispatch_record_md"])
    logger.info("zip    : %s", result["zip_file"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
