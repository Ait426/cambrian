"""외부 알파 수령자 시작 확인을 원문 없이 기록하는 게이트를 실행한다."""

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

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import (
    DISPATCH_RECORD_JSON_NAME,
    DISPATCH_RECORD_MD_NAME,
    PREFLIGHT_RECEIPT_NAME,
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.collect_external_alpha_diagnostics import collect_diagnostics
from scripts.prepare_external_alpha_handoff import RECEIPT_NAME
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR
from scripts.verify_external_alpha_release import verify_shareable_receipt_file


RECIPIENT_CHECKPOINT_SCHEMA_VERSION = "external_alpha_recipient_checkpoint_v0_1"
RECIPIENT_CHECKPOINT_JSON_NAME = f"{RELEASE_SLUG}-recipient-checkpoint.json"
RECIPIENT_CHECKPOINT_MD_NAME = f"{RELEASE_SLUG}-recipient-checkpoint.md"
DIAGNOSTICS_NAME = "external_alpha_diagnostics.json"
BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA_VERSION = "external_alpha_builder_gold_path_share_receipt_v0_1"
BUILDER_GOLD_PATH_REQUIRED_CAPABILITIES = {
    "agent_pack_created",
    "manual_runner_receipt_created",
    "evolution_suggestion_created",
    "candidate_diff_report_created",
    "promoted_private_version_created",
    "promotion_audit_record_created",
    "private_hub_lineage_verified",
}

logger = logging.getLogger(__name__)


class RecipientCheckpointError(Exception):
    """외부 알파 수령자 시작 확인 게이트 실패."""


def check_recipient_checkpoint(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    skip_build: bool = False,
    receipt_path: Path | None = None,
    diagnostics_path: Path | None = None,
    recipient_ack_private_sha256: str | None = None,
    recipient_ack_private_file: Path | None = None,
    recipient_private_sha256: str | None = None,
    recipient_private_file: Path | None = None,
    operator_dispatch_note_private_sha256: str | None = None,
    operator_dispatch_note_private_file: Path | None = None,
    sent_at_utc: str | None = None,
    builder_gold_path_share_receipt: Path | None = None,
    private_workspace_dir: Path | None = None,
    preflight_receipt_file: Path | None = None,
    require_preflight_receipt: bool = False,
    allow_synthetic_rehearsal: bool = False,
) -> dict[str, Any]:
    """dispatch-record 이후 수령자 시작 확인 상태를 만든다."""
    output_dir = output_dir.resolve()
    if private_workspace_dir is not None:
        workspace = private_workspace_dir.resolve()
        (
            recipient_private_file,
            operator_dispatch_note_private_file,
            recipient_ack_private_file,
        ) = _resolve_checkpoint_private_workspace_files(
            private_workspace_dir=workspace,
            recipient_ack_private_sha256=recipient_ack_private_sha256,
            recipient_ack_private_file=recipient_ack_private_file,
            recipient_private_sha256=recipient_private_sha256,
            recipient_private_file=recipient_private_file,
            operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file=operator_dispatch_note_private_file,
        )
        candidate_preflight = workspace / PREFLIGHT_RECEIPT_NAME
        if preflight_receipt_file is None and (require_preflight_receipt or candidate_preflight.is_file()):
            preflight_receipt_file = candidate_preflight
        recipient_ack_private_sha256 = None
        recipient_private_sha256 = None
        operator_dispatch_note_private_sha256 = None
    resolved_ack_sha256 = _resolve_private_sha256(
        direct_sha256=recipient_ack_private_sha256,
        private_file=recipient_ack_private_file,
        label="recipient acknowledgement",
    )
    dispatch_record_result = check_dispatch_record(
        output_dir=output_dir,
        skip_build=skip_build,
        recipient_private_sha256=recipient_private_sha256,
        recipient_private_file=recipient_private_file,
        operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
        operator_dispatch_note_private_file=operator_dispatch_note_private_file,
        sent_at_utc=sent_at_utc,
        preflight_receipt_file=preflight_receipt_file,
        require_preflight_receipt=require_preflight_receipt,
        synthetic_rehearsal_without_real_recipient=allow_synthetic_rehearsal,
    )
    dispatch_record_path = Path(str(dispatch_record_result["dispatch_record_json"]))
    dispatch_record = verify_dispatch_record_file(
        dispatch_record_path,
        allow_synthetic_rehearsal=allow_synthetic_rehearsal,
    )

    resolved_receipt = receipt_path.resolve() if receipt_path is not None else output_dir / RECEIPT_NAME
    resolved_diagnostics = diagnostics_path.resolve() if diagnostics_path is not None else output_dir / DIAGNOSTICS_NAME
    if diagnostics_path is None:
        collect_diagnostics(resolved_diagnostics)

    receipt = verify_shareable_receipt_file(resolved_receipt)
    diagnostics = _verify_diagnostics_file(resolved_diagnostics)
    resolved_builder_gold_path_share_receipt = _resolve_builder_gold_path_share_receipt_path(
        builder_gold_path_share_receipt
    )
    builder_gold_path_receipt = (
        _verify_builder_gold_path_share_receipt_file(resolved_builder_gold_path_share_receipt)
        if resolved_builder_gold_path_share_receipt
        else None
    )
    builder_gold_path_receipt_sha256 = (
        _file_sha256(resolved_builder_gold_path_share_receipt)
        if resolved_builder_gold_path_share_receipt
        else None
    )
    payload = _recipient_checkpoint_payload(
        dispatch_record=dispatch_record,
        receipt=receipt,
        diagnostics=diagnostics,
        diagnostics_file=resolved_diagnostics.name,
        recipient_ack_private_sha256=resolved_ack_sha256,
        builder_gold_path_share_receipt=builder_gold_path_receipt,
        builder_gold_path_share_receipt_sha256=builder_gold_path_receipt_sha256,
        allow_synthetic_rehearsal=allow_synthetic_rehearsal,
    )

    json_path = output_dir / RECIPIENT_CHECKPOINT_JSON_NAME
    md_path = output_dir / RECIPIENT_CHECKPOINT_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_recipient_checkpoint_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "recipient_checkpoint_json": str(json_path),
        "recipient_checkpoint_md": str(md_path),
        "dispatch_record_json": str(dispatch_record_path),
        "receipt_json": str(resolved_receipt),
        "diagnostics_json": str(resolved_diagnostics),
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="외부 알파 수령자 시작 확인 장부를 생성한다.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="릴리즈 산출물 폴더. 기본값은 dist")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="기존 ZIP, handoff, send-ready, pilot-ready, dispatch-record를 재사용한다.",
    )
    parser.add_argument("--receipt", default=None, help="공유 가능한 release receipt JSON 경로")
    parser.add_argument("--diagnostics", default=None, help="공유 가능한 diagnostics JSON 경로. 생략하면 새로 생성한다.")
    parser.add_argument("--recipient-ack-private-sha256", default=None, help="수령자 시작 확인 원문 대신 저장할 private sha256")
    parser.add_argument(
        "--recipient-ack-private-file",
        default=None,
        help="수령자 시작 확인 원문 파일 경로. 파일 내용과 경로는 저장하지 않고 sha256만 계산한다.",
    )
    parser.add_argument("--recipient-private-sha256", default=None, help="수신자 원문 식별자 대신 저장할 private sha256")
    parser.add_argument(
        "--recipient-private-file",
        default=None,
        help="수신자 원문 식별자 파일 경로. 파일 내용과 경로는 저장하지 않고 sha256만 계산한다.",
    )
    parser.add_argument(
        "--operator-dispatch-note-private-sha256",
        default=None,
        help="발송 운영 노트 원문 대신 저장할 private sha256",
    )
    parser.add_argument(
        "--operator-dispatch-note-private-file",
        default=None,
        help="발송 운영 노트 원문 파일 경로. 파일 내용과 경로는 저장하지 않고 sha256만 계산한다.",
    )
    parser.add_argument("--sent-at-utc", default=None, help="실제 발송 시각. 예: 2026-05-11T10:00:00+00:00")
    parser.add_argument("--preflight-receipt", default=None, help="Ready pre-send preflight receipt JSON.")
    parser.add_argument(
        "--require-preflight-receipt",
        action="store_true",
        help="Require a ready pre-send preflight receipt before recording a post-send recipient checkpoint.",
    )
    parser.add_argument(
        "--builder-gold-path-share-receipt",
        "--gold-path-share-receipt",
        dest="builder_gold_path_share_receipt",
        default=None,
        help="수령자가 Builder Golden Path 완료 후 보낸 share-safe receipt JSON",
    )
    parser.add_argument("--verify-recipient-checkpoint", default=None, help="recipient-checkpoint JSON만 단독 검증한다.")
    parser.add_argument(
        "--private-workspace-dir",
        default=None,
        help=(
            "Standard private workspace directory. Uses recipient-private.txt, "
            "operator-dispatch-note-private.md, and recipient-ack-private.txt after placeholders are replaced."
        ),
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_recipient_checkpoint:
        try:
            payload = verify_recipient_checkpoint_file(Path(args.verify_recipient_checkpoint))
        except Exception as exc:  # noqa: BLE001 - 운영 검증 실패 이유를 한 줄로 전달한다.
            logger.error("[FAIL] external alpha recipient-checkpoint verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha recipient-checkpoint verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["recipient_checkpoint_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = check_recipient_checkpoint(
            output_dir=Path(args.output_dir),
            skip_build=args.skip_build,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostics_path=Path(args.diagnostics) if args.diagnostics else None,
            recipient_ack_private_sha256=args.recipient_ack_private_sha256,
            recipient_ack_private_file=Path(args.recipient_ack_private_file) if args.recipient_ack_private_file else None,
            recipient_private_sha256=args.recipient_private_sha256,
            recipient_private_file=Path(args.recipient_private_file) if args.recipient_private_file else None,
            operator_dispatch_note_private_sha256=args.operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file=Path(args.operator_dispatch_note_private_file)
            if args.operator_dispatch_note_private_file
            else None,
            sent_at_utc=args.sent_at_utc,
            builder_gold_path_share_receipt=Path(args.builder_gold_path_share_receipt)
            if args.builder_gold_path_share_receipt
            else None,
            private_workspace_dir=Path(args.private_workspace_dir) if args.private_workspace_dir else None,
            preflight_receipt_file=Path(args.preflight_receipt) if args.preflight_receipt else None,
            require_preflight_receipt=args.require_preflight_receipt,
        )
    except Exception as exc:  # noqa: BLE001 - 운영 게이트는 실패 조건을 사용자에게 직접 보여준다.
        logger.error("[FAIL] external alpha recipient-checkpoint: %s", exc)
        return 1

    logger.info("[PASS] external alpha recipient-checkpoint")
    logger.info("verdict                 : %s", result["verdict"])
    logger.info("recipient_checkpoint_md: %s", result["recipient_checkpoint_md"])
    logger.info("zip                     : %s", result["zip_file"])
    logger.info("sha256                  : %s", result["archive_sha256"])
    return 0


def verify_recipient_checkpoint_file(path: Path, *, allow_synthetic_rehearsal: bool = False) -> dict[str, Any]:
    """recipient-checkpoint JSON만 읽어 변조 여부와 공유 안전성을 검증한다."""
    payload = _read_json(path)
    verify_recipient_checkpoint_payload(payload, allow_synthetic_rehearsal=allow_synthetic_rehearsal)
    return payload


def verify_recipient_checkpoint_payload(payload: dict[str, Any], *, allow_synthetic_rehearsal: bool = False) -> None:
    """recipient-checkpoint JSON이 시작 확인 전후의 경계를 지키는지 확인한다."""
    if payload.get("schema_version") != RECIPIENT_CHECKPOINT_SCHEMA_VERSION:
        raise RecipientCheckpointError("recipient-checkpoint schema_version이 올바르지 않습니다.")
    if payload.get("status") not in {
        "awaiting_recipient_checkpoint",
        "recipient_checkpoint_recorded",
        "recipient_gold_path_confirmed",
    }:
        raise RecipientCheckpointError(f"recipient-checkpoint status가 올바르지 않습니다: {payload.get('status')}")
    if payload.get("verdict") not in {"WAITING_FOR_RECIPIENT", "RECIPIENT_CHECKPOINT_RECORDED", "RECIPIENT_GOLD_PATH_CONFIRMED"}:
        raise RecipientCheckpointError(f"recipient-checkpoint verdict가 올바르지 않습니다: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise RecipientCheckpointError("recipient-checkpoint safe_to_share가 true가 아닙니다.")

    synthetic_boundary = (
        payload.get("synthetic_rehearsal_boundary")
        if isinstance(payload.get("synthetic_rehearsal_boundary"), dict)
        else None
    )
    if synthetic_boundary is not None and not allow_synthetic_rehearsal:
        raise RecipientCheckpointError(
            "synthetic rehearsal recipient checkpoints are not standalone recipient evidence."
        )

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise RecipientCheckpointError("recipient-checkpoint checks가 모두 true가 아닙니다.")

    checkpoint_checks = (
        payload.get("recipient_checkpoint_checks")
        if isinstance(payload.get("recipient_checkpoint_checks"), dict)
        else {}
    )
    if not checkpoint_checks:
        raise RecipientCheckpointError("recipient_checkpoint_checks가 없습니다.")
    if payload.get("recipient_checkpoint_body_sha256") != _recipient_checkpoint_body_sha256(payload):
        raise RecipientCheckpointError("recipient-checkpoint 본문 해시가 일치하지 않습니다.")
    recalculated_checks = _recipient_checkpoint_checks(payload)
    if checkpoint_checks != recalculated_checks:
        raise RecipientCheckpointError("recipient-checkpoint 안전 평가 결과가 현재 본문과 일치하지 않습니다.")
    failed_checks = [name for name, passed in recalculated_checks.items() if passed is not True]
    if failed_checks:
        raise RecipientCheckpointError("recipient-checkpoint 안전 평가 실패: " + ", ".join(failed_checks))


def _recipient_checkpoint_payload(
    dispatch_record: dict[str, Any],
    receipt: dict[str, Any],
    diagnostics: dict[str, Any],
    diagnostics_file: str,
    recipient_ack_private_sha256: str | None,
    builder_gold_path_share_receipt: dict[str, Any] | None,
    builder_gold_path_share_receipt_sha256: str | None,
    allow_synthetic_rehearsal: bool = False,
) -> dict[str, Any]:
    """수령자가 시작 파일을 열었는지 확인하되 원문은 넣지 않는다."""
    release = dispatch_record.get("release") if isinstance(dispatch_record.get("release"), dict) else {}
    dispatch_checks = (
        dispatch_record.get("dispatch_record_checks")
        if isinstance(dispatch_record.get("dispatch_record_checks"), dict)
        else {}
    )
    private_dispatch = (
        dispatch_record.get("dispatch_record") if isinstance(dispatch_record.get("dispatch_record"), dict) else {}
    )
    preflight = (
        dispatch_record.get("pre_send_preflight")
        if isinstance(dispatch_record.get("pre_send_preflight"), dict)
        else {}
    )
    dispatch_policy = (
        dispatch_record.get("dispatch_execution_policy")
        if isinstance(dispatch_record.get("dispatch_execution_policy"), dict)
        else {}
    )
    do_not_share = dispatch_record.get("do_not_share") if isinstance(dispatch_record.get("do_not_share"), list) else []
    pilot_ready = dispatch_record.get("pilot_ready") if isinstance(dispatch_record.get("pilot_ready"), dict) else {}
    decision_thresholds = (
        dispatch_record.get("decision_thresholds")
        if isinstance(dispatch_record.get("decision_thresholds"), dict)
        else {}
    )
    redaction_checks = diagnostics.get("redaction_checks") if isinstance(diagnostics.get("redaction_checks"), dict) else {}
    ack_hash_present = _looks_like_sha256(recipient_ack_private_sha256)
    dispatch_was_recorded = private_dispatch.get("sent_recorded") is True
    checkpoint_recorded = ack_hash_present and dispatch_was_recorded
    builder_gold_path_confirmed = builder_gold_path_share_receipt is not None and checkpoint_recorded
    if builder_gold_path_share_receipt is not None and not checkpoint_recorded:
        raise RecipientCheckpointError(
            "Builder Golden Path share receipt는 SENT_ONE_RECORDED dispatch와 recipient ack 이후에만 기록할 수 있습니다."
        )
    builder_gold_path_summary = _builder_gold_path_receipt_summary(builder_gold_path_share_receipt)
    if builder_gold_path_share_receipt_sha256 is not None:
        builder_gold_path_summary["sha256"] = builder_gold_path_share_receipt_sha256
    checks = {
        "dispatch_record_ready": dispatch_record.get("status") in {"ready_to_dispatch_one", "dispatch_recorded"}
        and dispatch_record.get("verdict") in {"READY_TO_SEND_ONE", "SENT_ONE_RECORDED"},
        "dispatch_record_checks_true": bool(dispatch_checks) and all(value is True for value in dispatch_checks.values()),
        "dispatch_record_body_hash_present": _looks_like_sha256(dispatch_record.get("dispatch_record_body_sha256")),
        "dispatch_one_participant": dispatch_record.get("dispatch_scope", {}).get("target_participants") == 1,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "dispatch_preflight_gate_ready_when_required": preflight.get("required") is not True
        or (
            preflight.get("verified_standalone") is True
            and _looks_like_sha256(preflight.get("body_sha256"))
            and preflight.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY"
        ),
        "dispatch_checkpoint_requires_sent_record": (not ack_hash_present) or dispatch_was_recorded,
        "recipient_ack_hash_valid_or_absent": recipient_ack_private_sha256 is None or ack_hash_present,
        "receipt_safe_to_share": receipt.get("safe_to_share") is True and receipt.get("status") == "pass",
        "receipt_body_hash_present": _looks_like_sha256(receipt.get("receipt_body_sha256")),
        "diagnostics_safe_to_share": diagnostics.get("safe_to_share") is True and diagnostics.get("status") == "pass",
        "diagnostics_redaction_checks_true": bool(redaction_checks)
        and all(value is True for value in redaction_checks.values()),
        "builder_gold_path_receipt_valid_or_absent": builder_gold_path_share_receipt is None
        or _builder_gold_path_share_receipt_valid(builder_gold_path_share_receipt),
        "builder_gold_path_receipt_safe_to_share": builder_gold_path_share_receipt is None
        or builder_gold_path_share_receipt.get("safe_to_share") is True,
        "builder_gold_path_receipt_has_no_absolute_paths": builder_gold_path_share_receipt is None
        or builder_gold_path_share_receipt.get("privacy", {}).get("absolute_paths_included") is False,
        "builder_gold_path_capabilities_all_true": builder_gold_path_share_receipt is None
        or _all_required_capabilities_true(builder_gold_path_share_receipt.get("capabilities_verified")),
        "builder_gold_path_claim_boundaries_locked": builder_gold_path_share_receipt is None
        or (
            builder_gold_path_share_receipt.get("proof_claim_allowed") is False
            and builder_gold_path_share_receipt.get("success_rate_claim_allowed") is False
            and builder_gold_path_share_receipt.get("sale_ready") is False
        ),
        "raw_recipient_ack_omitted": True,
        "success_claims_blocked": True,
        "proof_claims_blocked": True,
        "sale_ready_blocked": True,
    }
    payload = {
        "schema_version": RECIPIENT_CHECKPOINT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "recipient_gold_path_confirmed"
            if builder_gold_path_confirmed
            else "recipient_checkpoint_recorded"
            if checkpoint_recorded
            else "awaiting_recipient_checkpoint"
        ),
        "verdict": (
            "RECIPIENT_GOLD_PATH_CONFIRMED"
            if builder_gold_path_confirmed
            else "RECIPIENT_CHECKPOINT_RECORDED"
            if checkpoint_recorded
            else "WAITING_FOR_RECIPIENT"
        ),
        "safe_to_share": True,
        "release": {
            "version": release.get("version"),
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "dispatch_record": {
            "file": DISPATCH_RECORD_JSON_NAME,
            "markdown": DISPATCH_RECORD_MD_NAME,
            "body_sha256": dispatch_record.get("dispatch_record_body_sha256"),
            "verified_standalone": True,
            "verdict": dispatch_record.get("verdict"),
            "sent_recorded": private_dispatch.get("sent_recorded") is True,
            "pre_send_preflight": {
                "required": preflight.get("required") is True,
                "file": preflight.get("file"),
                "body_sha256": preflight.get("body_sha256"),
                "verdict": preflight.get("verdict"),
                "verified_standalone": preflight.get("verified_standalone") is True,
            },
        },
        "dispatch_execution_policy": dispatch_policy,
        "pilot_ready": {
            "file": pilot_ready.get("file"),
            "markdown": pilot_ready.get("markdown"),
            "dispatch_markdown": pilot_ready.get("dispatch_markdown"),
            "body_sha256": pilot_ready.get("body_sha256"),
            "verified_standalone": pilot_ready.get("verified_standalone") is True,
        },
        "shared_checkpoint": {
            "receipt": {
                "file": RECEIPT_NAME,
                "status": receipt.get("status"),
                "safe_to_share": receipt.get("safe_to_share") is True,
                "body_sha256": receipt.get("receipt_body_sha256"),
            },
            "diagnostics": {
                "file": diagnostics_file,
                "status": diagnostics.get("status"),
                "safe_to_share": diagnostics.get("safe_to_share") is True,
                "redaction_checks_all_true": bool(redaction_checks)
                and all(value is True for value in redaction_checks.values()),
            },
            "builder_gold_path": builder_gold_path_summary,
        },
        "private_checkpoint_fingerprints": {
            "recipient_ack_sha256": recipient_ack_private_sha256 if checkpoint_recorded else None,
            "builder_gold_path_share_receipt_sha256": builder_gold_path_share_receipt_sha256
            if builder_gold_path_confirmed
            else None,
            "raw_private_content_included": False,
            "raw_builder_gold_path_receipt_path_included": False,
        },
        "metrics": {
            "recipient_started": checkpoint_recorded,
            "builder_gold_path_confirmed": builder_gold_path_confirmed,
            "builder_gold_path_capabilities_verified": builder_gold_path_summary.get("capabilities_verified", {}),
            "pilot_participants_completed": 0,
            "success_rate": None,
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "sale_ready": False,
            "market_validated": False,
        },
        "decision_thresholds": decision_thresholds,
        "checks": checks,
        "operator_next_action": _operator_next_action(
            checkpoint_recorded=checkpoint_recorded,
            builder_gold_path_confirmed=builder_gold_path_confirmed,
        ),
        "do_not_share": do_not_share
        + [
            "recipient acknowledgement raw text",
            "recipient screen recording",
            "recipient private environment details",
        ],
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
    payload["artifact_chain"] = _recipient_checkpoint_artifact_chain(dispatch_record, payload)
    payload["recipient_checkpoint_checks"] = _recipient_checkpoint_checks(payload)
    verify_recipient_checkpoint_payload(payload, allow_synthetic_rehearsal=allow_synthetic_rehearsal)
    return payload


def _operator_next_action(checkpoint_recorded: bool, builder_gold_path_confirmed: bool) -> str:
    """수령자 시작 확인 전후의 다음 행동을 고정한다."""
    if builder_gold_path_confirmed:
        return "수령자가 Builder Golden Path까지 완료했으므로 private feedback/intake와 controlled learning tag를 수집한다."
    if checkpoint_recorded:
        return "수령자가 시작 파일과 검증 경로를 확인했으므로 feedback, issue intake, receipt, diagnostics를 기다린다."
    return "첫 사용자 1명의 시작 확인을 기다리고, 확인 원문은 private workspace에 둔 뒤 sha256만 기록한다."


def _resolve_private_sha256(
    direct_sha256: str | None,
    private_file: Path | None,
    label: str,
) -> str | None:
    """private 원문 파일은 경로나 내용을 저장하지 않고 sha256만 계산한다."""
    if direct_sha256 is not None and private_file is not None:
        raise RecipientCheckpointError(f"{label}는 sha256 또는 private file 중 하나만 입력해야 합니다.")
    if private_file is None:
        return direct_sha256
    try:
        data = private_file.read_bytes()
    except OSError as exc:
        raise RecipientCheckpointError(f"{label} private file을 읽을 수 없습니다.") from exc
    return hashlib.sha256(data).hexdigest()


def _resolve_checkpoint_private_workspace_files(
    *,
    private_workspace_dir: Path,
    recipient_ack_private_sha256: str | None,
    recipient_ack_private_file: Path | None,
    recipient_private_sha256: str | None,
    recipient_private_file: Path | None,
    operator_dispatch_note_private_sha256: str | None,
    operator_dispatch_note_private_file: Path | None,
) -> tuple[Path, Path, Path]:
    """Map the standard private workspace to checkpoint private files without leaking paths."""
    if any(
        value is not None
        for value in (
            recipient_ack_private_sha256,
            recipient_ack_private_file,
            recipient_private_sha256,
            recipient_private_file,
            operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file,
        )
    ):
        raise RecipientCheckpointError("--private-workspace-dir cannot be combined with explicit private sha256/file inputs.")
    workspace = private_workspace_dir.resolve()
    return (
        _private_workspace_file(
            workspace,
            "recipient-private.txt",
            "recipient identifier",
            ("Recipient identifier/contact goes here",),
        ),
        _private_workspace_file(
            workspace,
            "operator-dispatch-note-private.md",
            "operator dispatch note",
            ("Record the private channel", "<private-send-channel>"),
        ),
        _private_workspace_file(
            workspace,
            "recipient-ack-private.txt",
            "recipient acknowledgement",
            ("Paste only the private acknowledgement",),
        ),
    )


def _private_workspace_file(
    workspace: Path,
    filename: str,
    label: str,
    placeholder_fragments: tuple[str, ...],
) -> Path:
    path = workspace / filename
    if not path.is_file():
        raise RecipientCheckpointError(f"{label} private workspace file is missing: {filename}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecipientCheckpointError(f"{label} private workspace file cannot be read: {filename}") from exc
    if not text.strip():
        raise RecipientCheckpointError(f"{label} private workspace file is empty: {filename}")
    if any(fragment in text for fragment in placeholder_fragments):
        raise RecipientCheckpointError(f"{label} private workspace file still contains scaffold placeholder text: {filename}")
    return path


def _recipient_checkpoint_body_sha256(payload: dict[str, Any]) -> str:
    """recipient-checkpoint 검증 본문만 정규화해 sha256 해시를 계산한다."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"recipient_checkpoint_body_sha256", "artifact_chain", "recipient_checkpoint_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _recipient_checkpoint_artifact_chain(
    dispatch_record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    """dispatch-record 증거 체인에 recipient-checkpoint 해시를 덧붙인다."""
    source_chain = (
        dispatch_record.get("artifact_chain") if isinstance(dispatch_record.get("artifact_chain"), list) else []
    )
    chain = [
        {
            "kind": str(item.get("kind") or ""),
            "file": str(item.get("file") or ""),
            "sha256": str(item.get("sha256") or ""),
        }
        for item in source_chain
        if isinstance(item, dict)
    ]
    chain.append(
        {
            "kind": "recipient_checkpoint_json",
            "file": RECIPIENT_CHECKPOINT_JSON_NAME,
            "sha256": str(payload.get("recipient_checkpoint_body_sha256") or ""),
        }
    )
    builder_gold_path = (
        payload.get("shared_checkpoint", {}).get("builder_gold_path")
        if isinstance(payload.get("shared_checkpoint"), dict)
        else {}
    )
    if isinstance(builder_gold_path, dict) and builder_gold_path.get("present") is True:
        chain.append(
            {
                "kind": "builder_gold_path_share_receipt",
                "file": str(builder_gold_path.get("file") or "external_alpha_builder_gold_path_share_receipt.json"),
                "sha256": str(builder_gold_path.get("sha256") or ""),
            }
        )
    return chain


def _recipient_checkpoint_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """recipient-checkpoint가 공유 가능한 시작 확인 장부인지 평가한다."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    dispatch_record = payload.get("dispatch_record") if isinstance(payload.get("dispatch_record"), dict) else {}
    preflight = (
        dispatch_record.get("pre_send_preflight")
        if isinstance(dispatch_record.get("pre_send_preflight"), dict)
        else {}
    )
    pilot_ready = payload.get("pilot_ready") if isinstance(payload.get("pilot_ready"), dict) else {}
    shared_checkpoint = (
        payload.get("shared_checkpoint") if isinstance(payload.get("shared_checkpoint"), dict) else {}
    )
    receipt = shared_checkpoint.get("receipt") if isinstance(shared_checkpoint.get("receipt"), dict) else {}
    diagnostics = (
        shared_checkpoint.get("diagnostics") if isinstance(shared_checkpoint.get("diagnostics"), dict) else {}
    )
    builder_gold_path = (
        shared_checkpoint.get("builder_gold_path")
        if isinstance(shared_checkpoint.get("builder_gold_path"), dict)
        else {}
    )
    private_checkpoint = (
        payload.get("private_checkpoint_fingerprints")
        if isinstance(payload.get("private_checkpoint_fingerprints"), dict)
        else {}
    )
    synthetic_boundary = (
        payload.get("synthetic_rehearsal_boundary")
        if isinstance(payload.get("synthetic_rehearsal_boundary"), dict)
        else {}
    )
    dispatch_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    artifact_chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    body_hash = payload.get("recipient_checkpoint_body_sha256")
    chain_by_kind = {
        item.get("kind"): item
        for item in artifact_chain
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    checkpoint_recorded = payload.get("status") in {"recipient_checkpoint_recorded", "recipient_gold_path_confirmed"}
    required_chain_kinds = {
        "release_zip",
        "handoff_json",
        "receipt_json",
        "send_ready_json",
        "pilot_ready_json",
        "dispatch_record_json",
        "recipient_checkpoint_json",
    }
    if preflight.get("required") is True or preflight.get("verified_standalone") is True:
        required_chain_kinds.add("pre_send_preflight_receipt_json")
    return {
        "schema_version_present": payload.get("schema_version") == RECIPIENT_CHECKPOINT_SCHEMA_VERSION,
        "status_valid": payload.get("status")
        in {"awaiting_recipient_checkpoint", "recipient_checkpoint_recorded", "recipient_gold_path_confirmed"},
        "verdict_valid": payload.get("verdict")
        in {"WAITING_FOR_RECIPIENT", "RECIPIENT_CHECKPOINT_RECORDED", "RECIPIENT_GOLD_PATH_CONFIRMED"},
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "synthetic_boundary_not_standalone_when_present": not synthetic_boundary
        or (
            synthetic_boundary.get("synthetic_rehearsal") is True
            and synthetic_boundary.get("standalone_recipient_evidence_allowed") is False
            and synthetic_boundary.get("real_manual_send") is False
            and synthetic_boundary.get("real_recipient_evidence") is False
        ),
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "dispatch_record_body_hash_present": _looks_like_sha256(dispatch_record.get("body_sha256")),
        "dispatch_record_verified_standalone": dispatch_record.get("verified_standalone") is True,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "dispatch_preflight_gate_ready_when_required": preflight.get("required") is not True
        or (
            preflight.get("verified_standalone") is True
            and _looks_like_sha256(preflight.get("body_sha256"))
            and preflight.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY"
        ),
        "pilot_ready_body_hash_present": _looks_like_sha256(pilot_ready.get("body_sha256")),
        "pilot_ready_verified_standalone": pilot_ready.get("verified_standalone") is True,
        "receipt_safe_to_share": receipt.get("safe_to_share") is True and receipt.get("status") == "pass",
        "receipt_body_hash_present": _looks_like_sha256(receipt.get("body_sha256")),
        "diagnostics_safe_to_share": diagnostics.get("safe_to_share") is True and diagnostics.get("status") == "pass",
        "diagnostics_redaction_checks_true": diagnostics.get("redaction_checks_all_true") is True,
        "builder_gold_path_receipt_valid_or_absent": builder_gold_path.get("present") is not True
        or (
            builder_gold_path.get("schema_version") == BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA_VERSION
            and builder_gold_path.get("status") == "passed"
            and builder_gold_path.get("safe_to_share") is True
            and builder_gold_path.get("checks_all_true") is True
            and builder_gold_path.get("capabilities_all_true") is True
        ),
        "builder_gold_path_receipt_hash_valid_or_absent": builder_gold_path.get("present") is not True
        or _looks_like_sha256(builder_gold_path.get("sha256")),
        "builder_gold_path_claim_boundaries_locked": builder_gold_path.get("present") is not True
        or (
            builder_gold_path.get("proof_claim_allowed") is False
            and builder_gold_path.get("success_rate_claim_allowed") is False
            and builder_gold_path.get("sale_ready") is False
        ),
        "gold_path_verdict_requires_receipt": payload.get("verdict") != "RECIPIENT_GOLD_PATH_CONFIRMED"
        or builder_gold_path.get("present") is True,
        "recorded_checkpoint_has_ack_hash": (not checkpoint_recorded)
        or _looks_like_sha256(private_checkpoint.get("recipient_ack_sha256")),
        "raw_private_content_omitted": private_checkpoint.get("raw_private_content_included") is False,
        "raw_builder_receipt_path_omitted": private_checkpoint.get("raw_builder_gold_path_receipt_path_included") is False,
        "no_success_rate_claim": metrics.get("success_rate") is None,
        "proof_claim_blocked": metrics.get("proof_claim_allowed") is False,
        "success_rate_claim_blocked": metrics.get("success_rate_claim_allowed") is False,
        "sale_ready_blocked": metrics.get("sale_ready") is False,
        "market_validated_blocked": metrics.get("market_validated") is False,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": required_chain_kinds.issubset(set(chain_by_kind)),
        "artifact_chain_hashes_present": bool(artifact_chain)
        and all(isinstance(item, dict) and _looks_like_sha256(item.get("sha256")) for item in artifact_chain),
        "artifact_chain_release_hash_matched": chain_by_kind.get("release_zip", {}).get("sha256")
        == release.get("archive_sha256"),
        "artifact_chain_dispatch_record_hash_matched": chain_by_kind.get("dispatch_record_json", {}).get("sha256")
        == dispatch_record.get("body_sha256"),
        "artifact_chain_preflight_hash_matched_when_used": preflight.get("verified_standalone") is not True
        or chain_by_kind.get("pre_send_preflight_receipt_json", {}).get("sha256") == preflight.get("body_sha256"),
        "artifact_chain_recipient_checkpoint_hash_matched": chain_by_kind.get(
            "recipient_checkpoint_json", {}
        ).get("sha256")
        == body_hash,
        "do_not_share_guardrails_present": ".env" in do_not_share
        and "raw AI reply" in do_not_share
        and "recipient acknowledgement raw text" in do_not_share,
        "recipient_checkpoint_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "recipient_checkpoint_body_hash_matched": body_hash == _recipient_checkpoint_body_sha256(payload),
    }


def _resolve_builder_gold_path_share_receipt_path(path: Path | None) -> Path | None:
    """Fail closed before placeholder or missing builder receipt paths reach JSON/hash readers."""
    if path is None:
        return None
    raw_path = str(path).strip()
    if not raw_path or "<" in raw_path or ">" in raw_path or "|" in raw_path:
        raise RecipientCheckpointError(
            "Builder Golden Path share receipt file is missing or still a placeholder."
        )
    try:
        if not path.is_file():
            raise RecipientCheckpointError(
                "Builder Golden Path share receipt file is missing or still a placeholder."
            )
    except OSError as exc:
        raise RecipientCheckpointError(
            "Builder Golden Path share receipt file is missing or still a placeholder."
        ) from exc
    return path


def _verify_builder_gold_path_share_receipt_file(path: Path) -> dict[str, Any]:
    """Builder Golden Path share receipt가 원문 없이 공유 가능한지 확인한다."""
    payload = _read_json(path)
    if not _builder_gold_path_share_receipt_valid(payload):
        raise RecipientCheckpointError("Builder Golden Path share receipt가 유효하지 않습니다.")
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    if str(ROOT) in serialized or (home and home in serialized):
        raise RecipientCheckpointError("Builder Golden Path share receipt에 로컬 절대경로가 포함되어 있습니다.")
    return payload


def _builder_gold_path_share_receipt_valid(payload: dict[str, Any]) -> bool:
    """외부 알파 Builder Golden Path 완료 receipt의 최소 계약."""
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    return (
        payload.get("schema_version") == BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA_VERSION
        and payload.get("status") == "passed"
        and payload.get("safe_to_share") is True
        and privacy.get("absolute_paths_included") is False
        and privacy.get("raw_private_project_data_included") is False
        and privacy.get("secrets_included") is False
        and bool(checks)
        and all(value is True for value in checks.values())
        and _all_required_capabilities_true(payload.get("capabilities_verified"))
        and payload.get("proof_claim_allowed") is False
        and payload.get("success_rate_claim_allowed") is False
        and payload.get("sale_ready") is False
    )


def _builder_gold_path_receipt_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    """공유 산출물에는 Builder receipt의 원문이 아니라 안전한 요약과 파일 해시만 남긴다."""
    if payload is None:
        return {
            "present": False,
            "file": None,
            "sha256": None,
            "schema_version": None,
            "status": None,
            "safe_to_share": None,
            "checks_all_true": False,
            "capabilities_all_true": False,
            "capabilities_verified": {},
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "sale_ready": False,
        }
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    capabilities = payload.get("capabilities_verified") if isinstance(payload.get("capabilities_verified"), dict) else {}
    return {
        "present": True,
        "file": "external_alpha_builder_gold_path_share_receipt.json",
        "sha256": None,
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status"),
        "safe_to_share": payload.get("safe_to_share"),
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "capabilities_all_true": _all_required_capabilities_true(capabilities),
        "capabilities_verified": {
            name: capabilities.get(name) is True for name in sorted(BUILDER_GOLD_PATH_REQUIRED_CAPABILITIES)
        },
        "proof_claim_allowed": payload.get("proof_claim_allowed"),
        "success_rate_claim_allowed": payload.get("success_rate_claim_allowed"),
        "sale_ready": payload.get("sale_ready"),
    }


def _all_required_capabilities_true(value: Any) -> bool:
    """Builder Golden Path 필수 capability가 모두 true인지 확인한다."""
    if not isinstance(value, dict):
        return False
    return all(value.get(name) is True for name in BUILDER_GOLD_PATH_REQUIRED_CAPABILITIES)


def _verify_diagnostics_file(path: Path) -> dict[str, Any]:
    """diagnostics JSON이 공유 가능한 최소 증거인지 검증한다."""
    payload = _read_json(path)
    if payload.get("schema_version") != "external_alpha_diagnostics_v0_1":
        raise RecipientCheckpointError("diagnostics schema_version이 올바르지 않습니다.")
    if payload.get("status") != "pass":
        raise RecipientCheckpointError(f"diagnostics status가 pass가 아닙니다: {payload.get('status')}")
    if payload.get("safe_to_share") is not True:
        raise RecipientCheckpointError("diagnostics safe_to_share가 true가 아닙니다.")
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    for name in ["environment_variables_collected", "env_files_read", "secret_values_collected", "user_documents_collected"]:
        if privacy.get(name) is not False:
            raise RecipientCheckpointError(f"diagnostics privacy 플래그가 안전하지 않습니다: {name}")
    redaction_checks = payload.get("redaction_checks") if isinstance(payload.get("redaction_checks"), dict) else {}
    if not redaction_checks or any(value is not True for value in redaction_checks.values()):
        raise RecipientCheckpointError("diagnostics redaction_checks가 모두 true가 아닙니다.")
    support = payload.get("support_summary") if isinstance(payload.get("support_summary"), dict) else {}
    if support.get("status") != "pass" or support.get("safe_to_share") is not True:
        raise RecipientCheckpointError("diagnostics support_summary가 공유 가능한 pass 상태가 아닙니다.")
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    if str(ROOT) in serialized or (home and home in serialized):
        raise RecipientCheckpointError("diagnostics에 로컬 절대경로가 포함되었습니다.")
    return payload


def _recipient_checkpoint_markdown(payload: dict[str, Any]) -> str:
    """수령자 시작 확인 장부를 사람이 읽을 수 있는 Markdown으로 만든다."""
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    artifact_chain = "\n".join(
        f"- {item['kind']}: {item['file']} {item['sha256']}" for item in payload["artifact_chain"]
    )
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    shared = payload["shared_checkpoint"]
    private = payload["private_checkpoint_fingerprints"]
    dispatch_policy = payload["dispatch_execution_policy"]
    preflight = payload["dispatch_record"]["pre_send_preflight"]
    return f"""# Cambrian External Alpha Recipient Checkpoint

## Verdict

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- recipient-checkpoint body sha256: {payload["recipient_checkpoint_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- dispatch-record: {payload["dispatch_record"]["file"]}
- dispatch-record body sha256: {payload["dispatch_record"]["body_sha256"]}
- pre-send preflight required: {preflight["required"]}
- pre-send preflight body sha256: {preflight["body_sha256"]}
- pre-send preflight verified standalone: {preflight["verified_standalone"]}

## Dispatch Execution Policy

- script sends to recipient: {dispatch_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {dispatch_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {dispatch_policy["manual_operator_dispatch_required"]}
- max recipients per record: {dispatch_policy["max_recipients_per_record"]}
- records private sha256 only: {dispatch_policy["records_private_sha256_only"]}
- raw private content included: {dispatch_policy["raw_private_content_included"]}
- cohort scaling allowed: {dispatch_policy["cohort_scaling_allowed"]}
- sent recorded by private hashes only: {dispatch_policy["sent_recorded_by_private_hashes_only"]}

## Shared Checkpoint

- receipt file: {shared["receipt"]["file"]}
- receipt safe_to_share: {shared["receipt"]["safe_to_share"]}
- diagnostics file: {shared["diagnostics"]["file"]}
- diagnostics safe_to_share: {shared["diagnostics"]["safe_to_share"]}
- diagnostics redaction checks all true: {shared["diagnostics"]["redaction_checks_all_true"]}

## Builder Golden Path Share Receipt

- present: {shared["builder_gold_path"]["present"]}
- status: {shared["builder_gold_path"]["status"]}
- safe_to_share: {shared["builder_gold_path"]["safe_to_share"]}
- sha256: {shared["builder_gold_path"]["sha256"]}
- checks all true: {shared["builder_gold_path"]["checks_all_true"]}
- capabilities all true: {shared["builder_gold_path"]["capabilities_all_true"]}
- proof claim allowed: {shared["builder_gold_path"]["proof_claim_allowed"]}
- success rate claim allowed: {shared["builder_gold_path"]["success_rate_claim_allowed"]}
- sale ready: {shared["builder_gold_path"]["sale_ready"]}

## Private Checkpoint Fingerprints

- recipient ack sha256: {private["recipient_ack_sha256"]}
- builder gold path share receipt sha256: {private["builder_gold_path_share_receipt_sha256"]}
- raw private content included: {private["raw_private_content_included"]}
- raw builder gold path receipt path included: {private["raw_builder_gold_path_receipt_path_included"]}

## Metrics Boundary

- recipient started: {payload["metrics"]["recipient_started"]}
- builder gold path confirmed: {payload["metrics"]["builder_gold_path_confirmed"]}
- success rate: not collected
- proof claim allowed: {payload["metrics"]["proof_claim_allowed"]}
- success rate claim allowed: {payload["metrics"]["success_rate_claim_allowed"]}
- sale ready: {payload["metrics"]["sale_ready"]}

## Checks

{checks}

## Artifact Chain

{artifact_chain}

## Do Not Share

{do_not_share}

## Operator Next Action

{payload["operator_next_action"]}
"""


def _read_json(path: Path) -> dict[str, Any]:
    """JSON 파일을 읽고 객체인지 확인한다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise RecipientCheckpointError(f"JSON 파일을 읽을 수 없습니다: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise RecipientCheckpointError(f"JSON 파싱 실패: {path.name}") from exc
    if not isinstance(payload, dict):
        raise RecipientCheckpointError(f"JSON 객체가 아닙니다: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """JSON 파일을 안정적인 순서로 쓴다."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _looks_like_sha256(value: Any) -> bool:
    """sha256 문자열 형식인지 확인한다."""
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _file_sha256(path: Path) -> str:
    """파일 내용을 sha256으로 계산한다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_shareable_file(path: Path) -> None:
    """생성된 장부에 로컬 절대경로와 테스트 시크릿이 없는지 확인한다."""
    text = path.read_text(encoding="utf-8")
    forbidden_fragments = [str(ROOT), str(Path.home()), "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"]
    found = [fragment for fragment in forbidden_fragments if fragment and fragment in text]
    if found:
        raise RecipientCheckpointError(
            f"recipient-checkpoint 장부에 공유하면 안 되는 경로 또는 값이 포함되었습니다: {path.name}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
