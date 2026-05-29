"""?몃? ?뚰뙆 泥?諛쒖넚 湲곕줉???먮Ц ?놁씠 ?④린??寃뚯씠?몃? ?ㅽ뻾?쒕떎."""

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

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, DISPATCH_EXECUTION_POLICY, RELEASE_SLUG
from scripts.check_external_alpha_pilot_ready import (
    PILOT_DISPATCH_MD_NAME,
    PILOT_READY_JSON_NAME,
    PILOT_READY_MD_NAME,
    check_pilot_ready,
    verify_pilot_ready_file,
)
from scripts.smoke_external_alpha_release_bundle import (
    SMOKE_RECEIPT_NAME,
    smoke_release_bundle,
    verify_bundle_smoke_receipt_file,
)
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR


DISPATCH_RECORD_SCHEMA_VERSION = "external_alpha_dispatch_record_v0_1"
DISPATCH_RECORD_JSON_NAME = f"{RELEASE_SLUG}-dispatch-record.json"
DISPATCH_RECORD_MD_NAME = f"{RELEASE_SLUG}-dispatch-record.md"
PREFLIGHT_SCHEMA_VERSION = "external_alpha_first_recipient_send_preflight_v0_1"
PREFLIGHT_RECEIPT_NAME = "external-alpha-first-recipient-send-preflight-receipt.json"
_MAX_SENT_AT_FUTURE_SKEW = timedelta(minutes=5)
DISPATCH_POLICY_INHERITED_KEYS = (
    "script_sends_to_recipient",
    "script_sends_copy_paste_message",
    "manual_operator_dispatch_required",
    "max_recipients_per_record",
    "records_private_sha256_only",
    "raw_private_content_included",
    "cohort_scaling_allowed",
)

logger = logging.getLogger(__name__)


class DispatchRecordError(Exception):
    """?몃? ?뚰뙆 泥?諛쒖넚 湲곕줉 寃뚯씠???ㅽ뙣."""


def check_dispatch_record(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    skip_build: bool = False,
    recipient_private_sha256: str | None = None,
    recipient_private_file: Path | None = None,
    operator_dispatch_note_private_sha256: str | None = None,
    operator_dispatch_note_private_file: Path | None = None,
    sent_at_utc: str | None = None,
    private_workspace_dir: Path | None = None,
    preflight_receipt_file: Path | None = None,
    require_preflight_receipt: bool = False,
    synthetic_rehearsal_without_real_recipient: bool = False,
) -> dict[str, Any]:
    """pilot-ready ?곗텧臾쇱쓣 湲곕컲?쇰줈 泥?諛쒖넚 湲곕줉 ?λ?瑜?留뚮뱺??"""
    output_dir = output_dir.resolve()
    if private_workspace_dir is not None:
        workspace = private_workspace_dir.resolve()
        recipient_private_file, operator_dispatch_note_private_file = _resolve_dispatch_private_workspace_files(
            private_workspace_dir=workspace,
            recipient_private_sha256=recipient_private_sha256,
            recipient_private_file=recipient_private_file,
            operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file=operator_dispatch_note_private_file,
        )
        candidate_preflight = workspace / PREFLIGHT_RECEIPT_NAME
        require_preflight_receipt = True
        if preflight_receipt_file is None and (require_preflight_receipt or candidate_preflight.is_file()):
            preflight_receipt_file = candidate_preflight
        recipient_private_sha256 = None
        operator_dispatch_note_private_sha256 = None
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
    if sent_at_utc is not None:
        sent_at_utc = _validated_sent_at_utc(sent_at_utc)
    sent_recorded = _sent_recorded(
        recipient_private_sha256=resolved_recipient_sha256,
        operator_dispatch_note_private_sha256=resolved_operator_note_sha256,
        sent_at_utc=sent_at_utc,
    )
    preflight_receipt = None
    if require_preflight_receipt and sent_recorded and preflight_receipt_file is None:
        raise DispatchRecordError("pre-send preflight receipt is required before recording SENT_ONE_RECORDED.")
    if require_preflight_receipt and sent_recorded and preflight_receipt_file is not None and not preflight_receipt_file.is_file():
        raise DispatchRecordError("pre-send preflight receipt is required before recording SENT_ONE_RECORDED.")
    if preflight_receipt_file is not None:
        preflight_receipt = _verify_preflight_receipt_file(preflight_receipt_file)
    pilot_ready_result = check_pilot_ready(output_dir, skip_build=skip_build)
    pilot_ready_path = Path(str(pilot_ready_result["pilot_ready_json"]))
    pilot_ready = verify_pilot_ready_file(pilot_ready_path)
    bundle_smoke = _load_or_create_bundle_smoke(output_dir)
    payload = _dispatch_record_payload(
        pilot_ready=pilot_ready,
        bundle_smoke=bundle_smoke,
        recipient_private_sha256=resolved_recipient_sha256,
        operator_dispatch_note_private_sha256=resolved_operator_note_sha256,
        sent_at_utc=sent_at_utc,
        preflight_receipt=preflight_receipt,
        preflight_receipt_file_name=preflight_receipt_file.name if preflight_receipt_file is not None else None,
        require_preflight_receipt=require_preflight_receipt and sent_recorded,
        synthetic_rehearsal_without_real_recipient=synthetic_rehearsal_without_real_recipient,
    )

    json_path = output_dir / DISPATCH_RECORD_JSON_NAME
    md_path = output_dir / DISPATCH_RECORD_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_dispatch_record_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)
    verify_dispatch_record_file(
        json_path,
        allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
    )

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "dispatch_record_json": str(json_path),
        "dispatch_record_md": str(md_path),
        "pilot_ready_json": str(pilot_ready_path),
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 吏꾩엯??"""
    parser = argparse.ArgumentParser(description="?몃? ?뚰뙆 泥?諛쒖넚 湲곕줉 ?λ?瑜??앹꽦?쒕떎.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="由대━利??곗텧臾??대뜑. 湲곕낯媛믪? dist")
    parser.add_argument("--skip-build", action="store_true", help="湲곗〈 ZIP, handoff, send-ready, pilot-ready瑜??ъ궗?⑺븳??")
    parser.add_argument("--recipient-private-sha256", default=None, help="?섏떊???먮Ц ?앸퀎???????ν븷 private sha256")
    parser.add_argument(
        "--recipient-private-file",
        default=None,
        help="?섏떊???먮Ц ?앸퀎???뚯씪 寃쎈줈. ?뚯씪 ?댁슜怨?寃쎈줈????ν븯吏 ?딄퀬 sha256留?怨꾩궛?쒕떎.",
    )
    parser.add_argument(
        "--operator-dispatch-note-private-sha256",
        default=None,
        help="諛쒖넚 ?댁쁺 ?명듃 ?먮Ц ?????ν븷 private sha256",
    )
    parser.add_argument(
        "--operator-dispatch-note-private-file",
        default=None,
        help="諛쒖넚 ?댁쁺 ?명듃 ?먮Ц ?뚯씪 寃쎈줈. ?뚯씪 ?댁슜怨?寃쎈줈????ν븯吏 ?딄퀬 sha256留?怨꾩궛?쒕떎.",
    )
    parser.add_argument("--sent-at-utc", default=None, help="?ㅼ젣 諛쒖넚 ?쒓컖. ?? 2026-05-11T10:00:00+00:00")
    parser.add_argument("--verify-dispatch-record", default=None, help="dispatch-record JSON留??⑤룆 寃利앺븳??")
    parser.add_argument("--preflight-receipt", default=None, help="Ready pre-send preflight receipt JSON.")
    parser.add_argument(
        "--require-preflight-receipt",
        action="store_true",
        help="Require a ready pre-send preflight receipt before recording SENT_ONE_RECORDED.",
    )
    parser.add_argument(
        "--private-workspace-dir",
        default=None,
        help=(
            "Standard private workspace directory. Uses recipient-private.txt and "
            "operator-dispatch-note-private.md after placeholder text is replaced."
        ),
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_dispatch_record:
        try:
            payload = verify_dispatch_record_file(Path(args.verify_dispatch_record))
        except Exception as exc:  # noqa: BLE001 - ?댁쁺 寃利??ㅽ뙣 ?댁쑀瑜???以꾨줈 ?꾨떖?쒕떎.
            logger.error("[FAIL] external alpha dispatch-record verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha dispatch-record verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["dispatch_record_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = check_dispatch_record(
            output_dir=Path(args.output_dir),
            skip_build=args.skip_build,
            recipient_private_sha256=args.recipient_private_sha256,
            recipient_private_file=Path(args.recipient_private_file) if args.recipient_private_file else None,
            operator_dispatch_note_private_sha256=args.operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file=Path(args.operator_dispatch_note_private_file)
            if args.operator_dispatch_note_private_file
            else None,
            sent_at_utc=args.sent_at_utc,
            private_workspace_dir=Path(args.private_workspace_dir) if args.private_workspace_dir else None,
            preflight_receipt_file=Path(args.preflight_receipt) if args.preflight_receipt else None,
            require_preflight_receipt=args.require_preflight_receipt,
        )
    except Exception as exc:  # noqa: BLE001 - ?댁쁺 寃뚯씠?몃뒗 ?ㅽ뙣 議곌굔???ъ슜?먯뿉寃?吏곸젒 蹂댁뿬以??
        logger.error("[FAIL] external alpha dispatch-record: %s", exc)
        return 1

    logger.info("[PASS] external alpha dispatch-record")
    logger.info("verdict          : %s", result["verdict"])
    logger.info("dispatch_record_md: %s", result["dispatch_record_md"])
    logger.info("zip              : %s", result["zip_file"])
    logger.info("sha256           : %s", result["archive_sha256"])
    return 0


def verify_dispatch_record_file(path: Path, *, allow_synthetic_rehearsal: bool = False) -> dict[str, Any]:
    """dispatch-record JSON留??쎌뼱 蹂議??щ?? 怨듭쑀 ?덉쟾?깆쓣 寃利앺븳??"""
    payload = _read_json(path)
    verify_dispatch_record_payload(payload, allow_synthetic_rehearsal=allow_synthetic_rehearsal)
    return payload


def verify_dispatch_record_payload(payload: dict[str, Any], *, allow_synthetic_rehearsal: bool = False) -> None:
    """dispatch-record JSON??泥?諛쒖넚 ?쒗븳怨??먮Ц 鍮꾧났媛??먯튃??吏?ㅻ뒗吏 ?뺤씤?쒕떎."""
    if payload.get("schema_version") != DISPATCH_RECORD_SCHEMA_VERSION:
        raise DispatchRecordError("dispatch-record schema_version is invalid.")
    if payload.get("status") not in {"ready_to_dispatch_one", "dispatch_recorded"}:
        raise DispatchRecordError(f"dispatch-record status is invalid: {payload.get('status')}")
    if payload.get("verdict") not in {"READY_TO_SEND_ONE", "SENT_ONE_RECORDED"}:
        raise DispatchRecordError(f"dispatch-record verdict is invalid: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise DispatchRecordError("dispatch-record safe_to_share is not true.")

    synthetic_boundary = (
        payload.get("synthetic_rehearsal_boundary")
        if isinstance(payload.get("synthetic_rehearsal_boundary"), dict)
        else None
    )
    if synthetic_boundary is not None and not allow_synthetic_rehearsal:
        raise DispatchRecordError("synthetic rehearsal dispatch records are not standalone send evidence.")

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise DispatchRecordError("dispatch-record checks are not all true.")

    record_checks = payload.get("dispatch_record_checks") if isinstance(payload.get("dispatch_record_checks"), dict) else {}
    if not record_checks:
        raise DispatchRecordError("dispatch_record_checks is missing.")
    if payload.get("dispatch_record_body_sha256") != _dispatch_record_body_sha256(payload):
        raise DispatchRecordError("dispatch-record body hash does not match.")
    recalculated_checks = _dispatch_record_checks(payload)
    if record_checks != recalculated_checks:
        raise DispatchRecordError("dispatch-record safety checks do not match the current body.")
    failed_checks = [name for name, passed in recalculated_checks.items() if passed is not True]
    if failed_checks:
        raise DispatchRecordError("dispatch-record safety check failed: " + ", ".join(failed_checks))


def _dispatch_record_payload(
    pilot_ready: dict[str, Any],
    bundle_smoke: dict[str, Any],
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    sent_at_utc: str | None,
    preflight_receipt: dict[str, Any] | None = None,
    preflight_receipt_file_name: str | None = None,
    require_preflight_receipt: bool = False,
    synthetic_rehearsal_without_real_recipient: bool = False,
) -> dict[str, Any]:
    """泥??ъ슜??1紐?諛쒖넚 以鍮꾩? ?ㅼ젣 諛쒖넚 湲곕줉??媛숈? ?λ? ?뺤떇?쇰줈 留뚮뱺??"""
    release = pilot_ready.get("release") if isinstance(pilot_ready.get("release"), dict) else {}
    pilot_ready_checks = (
        pilot_ready.get("pilot_ready_checks") if isinstance(pilot_ready.get("pilot_ready_checks"), dict) else {}
    )
    pilot_dispatch = pilot_ready.get("pilot_dispatch") if isinstance(pilot_ready.get("pilot_dispatch"), dict) else {}
    pilot_ready_dispatch_policy = (
        pilot_ready.get("dispatch_execution_policy")
        if isinstance(pilot_ready.get("dispatch_execution_policy"), dict)
        else {}
    )
    decision_thresholds = (
        pilot_ready.get("pilot_decision_thresholds")
        if isinstance(pilot_ready.get("pilot_decision_thresholds"), dict)
        else {}
    )
    do_not_share = pilot_ready.get("do_not_share") if isinstance(pilot_ready.get("do_not_share"), list) else []
    sent_recorded = _sent_recorded(
        recipient_private_sha256=recipient_private_sha256,
        operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
        sent_at_utc=sent_at_utc,
    )
    copy_paste_message = str(pilot_dispatch.get("copy_paste_message") or "")
    copy_paste_message_policy = _copy_paste_message_policy(copy_paste_message)
    preflight_private_hashes = _preflight_private_hashes(preflight_receipt)
    bundle_smoke_release = (
        bundle_smoke.get("release_bundle") if isinstance(bundle_smoke.get("release_bundle"), dict) else {}
    )
    bundle_smoke_privacy = bundle_smoke.get("privacy") if isinstance(bundle_smoke.get("privacy"), dict) else {}
    status = "dispatch_recorded" if sent_recorded else "ready_to_dispatch_one"
    verdict = "SENT_ONE_RECORDED" if sent_recorded else "READY_TO_SEND_ONE"
    dispatch_execution_policy = _dispatch_execution_policy(
        sent_recorded=sent_recorded,
        source_policy=pilot_ready_dispatch_policy,
    )
    checks = {
        "pilot_ready_go": pilot_ready.get("status") == "pilot_ready" and pilot_ready.get("verdict") == "GO",
        "pilot_ready_checks_true": bool(pilot_ready_checks) and all(value is True for value in pilot_ready_checks.values()),
        "pilot_ready_dispatch_policy_matched": pilot_ready_dispatch_policy == DISPATCH_EXECUTION_POLICY,
        "dispatch_policy_inherits_pilot_ready": _dispatch_policy_inherits_pilot_ready(
            dispatch_execution_policy,
            pilot_ready_dispatch_policy,
            sent_recorded,
        ),
        "pilot_ready_body_hash_present": _looks_like_sha256(pilot_ready.get("pilot_ready_body_sha256")),
        "bundle_smoke_receipt_status_pass": bundle_smoke.get("status") == "pass",
        "bundle_smoke_receipt_checks_true": _all_true(bundle_smoke.get("checks"))
        and _all_true(bundle_smoke.get("receipt_checks")),
        "bundle_smoke_release_hash_matches": bundle_smoke_release.get("archive_sha256")
        == release.get("archive_sha256"),
        "bundle_smoke_privacy_safe": bundle_smoke.get("safe_to_share") is True
        and bundle_smoke_privacy.get("absolute_paths_included") is False
        and bundle_smoke_privacy.get("raw_private_project_data_included") is False
        and bundle_smoke_privacy.get("secrets_included") is False,
        "pilot_dispatch_markdown_referenced": PILOT_DISPATCH_MD_NAME == pilot_ready.get("pilot_ready_checks", {})
        .get("pilot_dispatch_markdown_present", PILOT_DISPATCH_MD_NAME)
        or bool(pilot_dispatch),
        "target_participants_one": pilot_dispatch.get("target_participants") == 1,
        "timebox_present": pilot_dispatch.get("timebox_minutes") == 10,
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "copy_paste_message_hashed": _looks_like_sha256(_text_sha256(copy_paste_message)),
        "copy_paste_message_policy_locked": all(copy_paste_message_policy.values()),
        "copy_paste_message_quickstart_locked": copy_paste_message_policy.get("quickstart_named") is True,
        "copy_paste_message_agent_prompt_locked": copy_paste_message_policy.get("agent_prompt_named") is True,
        "pre_send_preflight_required_when_requested": (not require_preflight_receipt)
        or preflight_receipt is not None,
        "pre_send_preflight_ready_when_present": preflight_receipt is None
        or (
            preflight_receipt.get("status") == "pass"
            and preflight_receipt.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY"
        ),
        "pre_send_preflight_release_hash_matches": preflight_receipt is None
        or preflight_receipt.get("release", {}).get("archive_sha256") == release.get("archive_sha256"),
        "pre_send_preflight_private_hashes_match": preflight_receipt is None
        or (
            preflight_private_hashes.get("recipient_private_sha256") == recipient_private_sha256
            and preflight_private_hashes.get("operator_dispatch_note_private_sha256")
            == operator_dispatch_note_private_sha256
        ),
        "pre_send_preflight_share_safe": preflight_receipt is None
        or (
            preflight_receipt.get("safe_to_share") is True
            and preflight_receipt.get("private_workspace", {}).get("raw_private_values_included") is False
            and preflight_receipt.get("private_workspace", {}).get("local_paths_included") is False
        ),
        "private_hashes_valid_or_absent": _private_hashes_valid_or_absent(
            recipient_private_sha256,
            operator_dispatch_note_private_sha256,
            sent_at_utc,
        ),
        "raw_recipient_omitted": True,
        "raw_message_thread_omitted": True,
        "send_one_only": True,
        "cohort_scaling_blocked": True,
        "success_claims_blocked": True,
        "decision_thresholds_carried": {"continue", "fix_before_next", "stop_and_redesign"}.issubset(
            set(decision_thresholds)
        ),
    }
    if not checks["private_hashes_valid_or_absent"]:
        raise DispatchRecordError("諛쒖넚 湲곕줉? recipient/note/sent_at??紐⑤몢 ?앸왂?섍굅??紐⑤몢 private sha256怨?UTC ?쒓컖?쇰줈 湲곕줉?댁빞 ?⑸땲??")

    payload = {
        "schema_version": DISPATCH_RECORD_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "verdict": verdict,
        "safe_to_share": True,
        "release": {
            "version": release.get("version"),
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "pilot_ready": {
            "file": PILOT_READY_JSON_NAME,
            "markdown": PILOT_READY_MD_NAME,
            "dispatch_markdown": PILOT_DISPATCH_MD_NAME,
            "body_sha256": pilot_ready.get("pilot_ready_body_sha256"),
            "dispatch_execution_policy": pilot_ready_dispatch_policy,
            "verified_standalone": True,
        },
        "bundle_smoke_receipt": {
            "file": SMOKE_RECEIPT_NAME,
            "body_sha256": bundle_smoke.get("receipt_body_sha256"),
            "release_zip": bundle_smoke_release.get("zip_file"),
            "release_archive_sha256": bundle_smoke_release.get("archive_sha256"),
            "verified_standalone": True,
        },
        "dispatch_scope": {
            "target_participants": 1,
            "max_recipients_per_record": 1,
            "timebox_minutes": pilot_dispatch.get("timebox_minutes"),
            "cohort_scaling_allowed": False,
            "marketplace_listing_allowed": False,
        },
        "dispatch_execution_policy": dispatch_execution_policy,
        "send_materials": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "pilot_dispatch_markdown": PILOT_DISPATCH_MD_NAME,
            "copy_paste_message_sha256": _text_sha256(copy_paste_message),
            "copy_paste_message_policy": copy_paste_message_policy,
        },
        "pre_send_preflight": {
            "required": require_preflight_receipt,
            "file": preflight_receipt_file_name,
            "body_sha256": preflight_receipt.get("first_recipient_send_preflight_receipt_body_sha256")
            if preflight_receipt is not None
            else None,
            "release_archive_sha256": preflight_receipt.get("release", {}).get("archive_sha256")
            if preflight_receipt is not None
            else None,
            "verdict": preflight_receipt.get("verdict") if preflight_receipt is not None else None,
            "verified_standalone": preflight_receipt is not None,
            "private_hashes_matched": preflight_receipt is not None
            and preflight_private_hashes.get("recipient_private_sha256") == recipient_private_sha256
            and preflight_private_hashes.get("operator_dispatch_note_private_sha256")
            == operator_dispatch_note_private_sha256,
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "dispatch_record": {
            "sent_recorded": sent_recorded,
            "sent_at_utc": _normalize_sent_at(sent_at_utc) if sent_recorded else None,
            "recipient_private_sha256": recipient_private_sha256 if sent_recorded else None,
            "operator_dispatch_note_private_sha256": operator_dispatch_note_private_sha256 if sent_recorded else None,
            "raw_recipient_included": False,
            "raw_message_thread_included": False,
        },
        "decision_thresholds": decision_thresholds,
        "metrics": {
            "pilot_participants_completed": 0,
            "success_rate": None,
            "proof_claim_allowed": False,
            "sale_ready": False,
            "market_validated": False,
        },
        "checks": checks,
        "operator_next_action": _operator_next_action(sent_recorded),
        "do_not_share": do_not_share
        + [
            "recipient raw identifier",
            "dispatch message thread raw text",
            "operator dispatch note raw text",
        ],
    }
    if synthetic_rehearsal_without_real_recipient:
        payload["synthetic_rehearsal_boundary"] = {
            "synthetic_rehearsal": True,
            "standalone_send_evidence_allowed": False,
            "real_manual_send": False,
            "real_recipient_evidence": False,
            "synthetic_private_inputs": True,
            "preflight_receipt_rehearsal_only_exception": True,
        }
    payload["dispatch_record_body_sha256"] = _dispatch_record_body_sha256(payload)
    payload["artifact_chain"] = _dispatch_record_artifact_chain(pilot_ready, payload)
    payload["dispatch_record_checks"] = _dispatch_record_checks(payload)
    verify_dispatch_record_payload(
        payload,
        allow_synthetic_rehearsal=synthetic_rehearsal_without_real_recipient,
    )
    return payload


def _sent_recorded(
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    sent_at_utc: str | None,
) -> bool:
    """諛쒖넚 湲곕줉 ?꾨뱶媛 紐⑤몢 ?ㅼ뼱?붿쓣 ?뚮쭔 ?ㅼ젣 諛쒖넚 湲곕줉?쇰줈 蹂몃떎."""
    provided = [recipient_private_sha256 is not None, operator_dispatch_note_private_sha256 is not None, sent_at_utc is not None]
    if any(provided) and not all(provided):
        return False
    return all(provided)


def _private_hashes_valid_or_absent(
    recipient_private_sha256: str | None,
    operator_dispatch_note_private_sha256: str | None,
    sent_at_utc: str | None,
) -> bool:
    """諛쒖넚 湲곕줉???녾굅?? ?먮Ц ?놁씠 ?댁떆? UTC ?쒓컖留??덈뒗吏 ?뺤씤?쒕떎."""
    if recipient_private_sha256 is None and operator_dispatch_note_private_sha256 is None and sent_at_utc is None:
        return True
    return (
        _looks_like_sha256(recipient_private_sha256)
        and _looks_like_sha256(operator_dispatch_note_private_sha256)
        and _sent_at_utc_is_valid(sent_at_utc)
    )


def _all_true(value: Any) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _copy_paste_message_policy(copy_paste_message: str) -> dict[str, bool]:
    """Verify the first-send message keeps recipient instructions readable and private-safe."""
    return {
        "zip_attachment_named": f"Attachment: {RELEASE_SLUG}.zip" in copy_paste_message,
        "sha256_present": "sha256:" in copy_paste_message,
        "quickstart_named": "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message,
        "agent_prompt_named": "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in copy_paste_message,
        "recipient_ack_short_reply": "CONFIRMED" in copy_paste_message and "reply only" in copy_paste_message,
        "no_raw_screenshot_request": "raw screenshots" in copy_paste_message
        and "Do not send" in copy_paste_message,
        "provider_key_not_requested": "provider API key" in copy_paste_message
        and "does not require" in copy_paste_message,
    }


def _dispatch_execution_policy(sent_recorded: bool, source_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    base = source_policy if isinstance(source_policy, dict) else DISPATCH_EXECUTION_POLICY
    return {
        "script_sends_to_recipient": base.get("script_sends_to_recipient"),
        "script_sends_copy_paste_message": base.get("script_sends_copy_paste_message"),
        "manual_operator_dispatch_required": base.get("manual_operator_dispatch_required"),
        "max_recipients_per_record": base.get("max_recipients_per_record"),
        "records_private_sha256_only": base.get("records_private_sha256_only"),
        "raw_private_content_included": base.get("raw_private_content_included"),
        "cohort_scaling_allowed": base.get("cohort_scaling_allowed"),
        "sent_recorded_by_private_hashes_only": sent_recorded,
    }


def _dispatch_policy_inherits_pilot_ready(
    dispatch_policy: dict[str, Any],
    pilot_ready_policy: dict[str, Any],
    sent_recorded: bool,
) -> bool:
    """pilot-ready ?뺤콉?먯꽌 ?ㅼ젣 諛쒖넚 湲곕줉 ?щ?留??뚯깮?먮뒗吏 ?뺤씤?쒕떎."""
    if not isinstance(dispatch_policy, dict) or not isinstance(pilot_ready_policy, dict):
        return False
    inherited = all(dispatch_policy.get(key) == pilot_ready_policy.get(key) for key in DISPATCH_POLICY_INHERITED_KEYS)
    return inherited and dispatch_policy.get("sent_recorded_by_private_hashes_only") is sent_recorded


def _resolve_private_sha256(
    direct_sha256: str | None,
    private_file: Path | None,
    label: str,
) -> str | None:
    """private ?먮Ц ?뚯씪? 寃쎈줈???댁슜????ν븯吏 ?딄퀬 sha256留?怨꾩궛?쒕떎."""
    if direct_sha256 is not None and private_file is not None:
        raise DispatchRecordError(f"{label}??sha256 ?먮뒗 private file 以??섎굹留??낅젰?댁빞 ?⑸땲??")
    if private_file is None:
        return direct_sha256
    try:
        data = private_file.read_bytes()
    except OSError as exc:
        raise DispatchRecordError(f"{label} private file???쎌쓣 ???놁뒿?덈떎.") from exc
    return hashlib.sha256(data).hexdigest()


def _verify_preflight_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise DispatchRecordError("pre-send preflight receipt schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "FIRST_RECIPIENT_PRE_SEND_READY":
        raise DispatchRecordError("pre-send preflight receipt is not ready.")
    if payload.get("safe_to_share") is not True:
        raise DispatchRecordError("pre-send preflight receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    receipt_checks = (
        payload.get("first_recipient_send_preflight_receipt_checks")
        if isinstance(payload.get("first_recipient_send_preflight_receipt_checks"), dict)
        else {}
    )
    if not checks or any(value is not True for value in checks.values()):
        raise DispatchRecordError("pre-send preflight receipt checks failed.")
    if not receipt_checks or any(value is not True for value in receipt_checks.values()):
        raise DispatchRecordError("pre-send preflight receipt self-checks failed.")
    if payload.get("first_recipient_send_preflight_receipt_body_sha256") != _preflight_receipt_body_sha256(payload):
        raise DispatchRecordError("pre-send preflight receipt body hash mismatch.")
    return payload


def _preflight_private_hashes(payload: dict[str, Any] | None) -> dict[str, str | None]:
    result = {
        "recipient_private_sha256": None,
        "operator_dispatch_note_private_sha256": None,
    }
    if not isinstance(payload, dict):
        return result
    workspace = payload.get("private_workspace") if isinstance(payload.get("private_workspace"), dict) else {}
    private_files = (
        workspace.get("required_private_files")
        if isinstance(workspace.get("required_private_files"), list)
        else []
    )
    for item in private_files:
        if not isinstance(item, dict):
            continue
        if item.get("file") == "recipient-private.txt":
            result["recipient_private_sha256"] = item.get("sha256")
        if item.get("file") == "operator-dispatch-note-private.md":
            result["operator_dispatch_note_private_sha256"] = item.get("sha256")
    return result


def _preflight_receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "generated_at",
            "first_recipient_send_preflight_receipt_body_sha256",
            "first_recipient_send_preflight_receipt_checks",
        }
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_dispatch_private_workspace_files(
    *,
    private_workspace_dir: Path,
    recipient_private_sha256: str | None,
    recipient_private_file: Path | None,
    operator_dispatch_note_private_sha256: str | None,
    operator_dispatch_note_private_file: Path | None,
) -> tuple[Path, Path]:
    """Map the standard private workspace to dispatch private files without leaking paths."""
    if any(
        value is not None
        for value in (
            recipient_private_sha256,
            recipient_private_file,
            operator_dispatch_note_private_sha256,
            operator_dispatch_note_private_file,
        )
    ):
        raise DispatchRecordError("--private-workspace-dir cannot be combined with explicit private sha256/file inputs.")
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
    )


def _private_workspace_file(
    workspace: Path,
    filename: str,
    label: str,
    placeholder_fragments: tuple[str, ...],
) -> Path:
    path = workspace / filename
    if not path.is_file():
        raise DispatchRecordError(f"{label} private workspace file is missing: {filename}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DispatchRecordError(f"{label} private workspace file cannot be read: {filename}") from exc
    if not text.strip():
        raise DispatchRecordError(f"{label} private workspace file is empty: {filename}")
    if any(fragment in text for fragment in placeholder_fragments):
        raise DispatchRecordError(f"{label} private workspace file still contains scaffold placeholder text: {filename}")
    return path


def _load_or_create_bundle_smoke(output_dir: Path) -> dict[str, Any]:
    """Verify the recipient-style bundle smoke receipt, creating it when absent."""
    smoke_path = output_dir / SMOKE_RECEIPT_NAME
    zip_path = output_dir / f"{RELEASE_SLUG}.zip"
    manifest_path = output_dir / f"{RELEASE_SLUG}.manifest.json"
    if smoke_path.is_file():
        smoke = verify_bundle_smoke_receipt_file(smoke_path)
        release = smoke.get("release_bundle") if isinstance(smoke.get("release_bundle"), dict) else {}
        if release.get("archive_sha256") == _sha256_file(zip_path):
            return smoke
    return smoke_release_bundle(
        zip_path=zip_path,
        manifest_path=manifest_path,
        receipt_path=smoke_path,
    )


def _normalize_sent_at(value: str | None) -> str | None:
    """UTC ?ㅽ봽?뗭씠 ?덈뒗 ISO ?쒓컖留??듦낵?쒗궓??"""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _validated_sent_at_utc(value: str) -> str:
    sent_at = value.strip()
    if not sent_at or "<" in sent_at or ">" in sent_at:
        raise DispatchRecordError(
            "sent_at_utc must be the real UTC manual-send timestamp, not a placeholder."
        )
    try:
        parsed = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DispatchRecordError("sent_at_utc must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise DispatchRecordError("sent_at_utc must include UTC timezone, such as 2026-05-17T01:00:00Z.")
    if parsed.astimezone(timezone.utc) > datetime.now(timezone.utc) + _MAX_SENT_AT_FUTURE_SKEW:
        raise DispatchRecordError("sent_at_utc must not be in the future.")
    return sent_at


def _sent_at_utc_is_valid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        _validated_sent_at_utc(value)
    except DispatchRecordError:
        return False
    return True


def _operator_next_action(sent_recorded: bool) -> str:
    """諛쒖넚 ?꾪썑???댁쁺?먭? ?댁빞 ???쇱쓣 ??以꾨줈 怨좎젙?쒕떎."""
    if sent_recorded:
        return "泥??ъ슜??1紐낆쓽 feedback, issue intake, receipt, diagnostics瑜?諛쏆? ??pilot-review? pilot-evidence瑜?媛깆떊?쒕떎."
    return "ZIP怨?pilot-dispatch copy-paste message瑜?泥??몃? ?뚰뙆 ?ъ슜??1紐낆뿉寃뚮쭔 蹂대궡怨? 蹂대깉?ㅻ㈃ private sha256留??ｌ뼱 dispatch-record瑜??ㅼ떆 ?ㅽ뻾?쒕떎."


def _dispatch_record_body_sha256(payload: dict[str, Any]) -> str:
    """dispatch-record 寃利?蹂몃Ц留??뺢퇋?뷀빐 sha256 ?댁떆瑜?怨꾩궛?쒕떎."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"dispatch_record_body_sha256", "artifact_chain", "dispatch_record_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dispatch_record_artifact_chain(pilot_ready: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    """pilot-ready 利앷굅 泥댁씤??dispatch-record ?댁떆瑜??㏓텤?몃떎."""
    source_chain = pilot_ready.get("artifact_chain") if isinstance(pilot_ready.get("artifact_chain"), list) else []
    chain = [
        {
            "kind": str(item.get("kind") or ""),
            "file": str(item.get("file") or ""),
            "sha256": str(item.get("sha256") or ""),
        }
        for item in source_chain
        if isinstance(item, dict)
    ]
    smoke = payload.get("bundle_smoke_receipt") if isinstance(payload.get("bundle_smoke_receipt"), dict) else {}
    chain.append(
        {
            "kind": "bundle_smoke_receipt_json",
            "file": SMOKE_RECEIPT_NAME,
            "sha256": str(smoke.get("body_sha256") or ""),
        }
    )
    preflight = payload.get("pre_send_preflight") if isinstance(payload.get("pre_send_preflight"), dict) else {}
    if _looks_like_sha256(preflight.get("body_sha256")):
        chain.append(
            {
                "kind": "pre_send_preflight_receipt_json",
                "file": str(preflight.get("file") or PREFLIGHT_RECEIPT_NAME),
                "sha256": str(preflight.get("body_sha256") or ""),
            }
        )
    chain.append(
        {
            "kind": "dispatch_record_json",
            "file": DISPATCH_RECORD_JSON_NAME,
            "sha256": str(payload.get("dispatch_record_body_sha256") or ""),
        }
    )
    return chain


def _dispatch_record_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """dispatch-record媛 怨듭쑀 媛?ν븳 泥?諛쒖넚 ?λ??몄? ?됯??쒕떎."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    pilot_ready = payload.get("pilot_ready") if isinstance(payload.get("pilot_ready"), dict) else {}
    bundle_smoke = (
        payload.get("bundle_smoke_receipt") if isinstance(payload.get("bundle_smoke_receipt"), dict) else {}
    )
    pilot_ready_dispatch_policy = (
        pilot_ready.get("dispatch_execution_policy")
        if isinstance(pilot_ready.get("dispatch_execution_policy"), dict)
        else {}
    )
    dispatch_scope = payload.get("dispatch_scope") if isinstance(payload.get("dispatch_scope"), dict) else {}
    dispatch_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    send_materials = payload.get("send_materials") if isinstance(payload.get("send_materials"), dict) else {}
    preflight = payload.get("pre_send_preflight") if isinstance(payload.get("pre_send_preflight"), dict) else {}
    copy_paste_message_policy = (
        send_materials.get("copy_paste_message_policy")
        if isinstance(send_materials.get("copy_paste_message_policy"), dict)
        else {}
    )
    dispatch_record = payload.get("dispatch_record") if isinstance(payload.get("dispatch_record"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    artifact_chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    body_hash = payload.get("dispatch_record_body_sha256")
    chain_by_kind = {
        item.get("kind"): item
        for item in artifact_chain
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    sent_recorded = dispatch_record.get("sent_recorded") is True
    preflight_required = preflight.get("required") is True
    preflight_should_validate = preflight_required or preflight.get("verified_standalone") is True
    required_chain_kinds = {
        "release_zip",
        "handoff_json",
        "receipt_json",
        "send_ready_json",
        "pilot_ready_json",
        "bundle_smoke_receipt_json",
        "dispatch_record_json",
    }
    if preflight_should_validate:
        required_chain_kinds.add("pre_send_preflight_receipt_json")
    return {
        "schema_version_present": payload.get("schema_version") == DISPATCH_RECORD_SCHEMA_VERSION,
        "status_valid": payload.get("status") in {"ready_to_dispatch_one", "dispatch_recorded"},
        "verdict_valid": payload.get("verdict") in {"READY_TO_SEND_ONE", "SENT_ONE_RECORDED"},
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "pilot_ready_body_hash_present": _looks_like_sha256(pilot_ready.get("body_sha256")),
        "pilot_ready_verified_standalone": pilot_ready.get("verified_standalone") is True,
        "bundle_smoke_body_hash_present": _looks_like_sha256(bundle_smoke.get("body_sha256")),
        "bundle_smoke_verified_standalone": bundle_smoke.get("verified_standalone") is True,
        "bundle_smoke_release_hash_matched": bundle_smoke.get("release_archive_sha256") == release.get("archive_sha256"),
        "pilot_dispatch_markdown_referenced": pilot_ready.get("dispatch_markdown") == PILOT_DISPATCH_MD_NAME,
        "pilot_ready_dispatch_policy_matched": pilot_ready_dispatch_policy == DISPATCH_EXECUTION_POLICY,
        "send_one_only": dispatch_scope.get("target_participants") == 1
        and dispatch_scope.get("max_recipients_per_record") == 1,
        "cohort_scaling_blocked": dispatch_scope.get("cohort_scaling_allowed") is False,
        "dispatch_policy_inherits_pilot_ready": _dispatch_policy_inherits_pilot_ready(
            dispatch_policy,
            pilot_ready_dispatch_policy,
            sent_recorded,
        ),
        "dispatch_policy_manual_only": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_policy_one_recipient": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_policy_private_hash_only": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "dispatch_policy_sent_recording_consistent": dispatch_policy.get("sent_recorded_by_private_hashes_only")
        is sent_recorded,
        "copy_paste_message_hash_present": _looks_like_sha256(send_materials.get("copy_paste_message_sha256")),
        "copy_paste_message_policy_locked": bool(copy_paste_message_policy)
        and all(value is True for value in copy_paste_message_policy.values()),
        "copy_paste_message_quickstart_locked": copy_paste_message_policy.get("quickstart_named") is True,
        "copy_paste_message_agent_prompt_locked": copy_paste_message_policy.get("agent_prompt_named") is True,
        "copy_paste_message_ack_request_locked": copy_paste_message_policy.get("recipient_ack_short_reply") is True,
        "copy_paste_message_no_raw_screenshot_locked": copy_paste_message_policy.get("no_raw_screenshot_request")
        is True,
        "pre_send_preflight_required_consistent": (not preflight_required) or sent_recorded,
        "pre_send_preflight_verified_when_required": (not preflight_required)
        or preflight.get("verified_standalone") is True,
        "pre_send_preflight_body_hash_present_when_used": (not preflight_should_validate)
        or _looks_like_sha256(preflight.get("body_sha256")),
        "pre_send_preflight_release_hash_matched_when_used": (not preflight_should_validate)
        or preflight.get("release_archive_sha256") == release.get("archive_sha256"),
        "pre_send_preflight_private_hashes_matched_when_used": (not preflight_should_validate)
        or preflight.get("private_hashes_matched") is True,
        "pre_send_preflight_raw_private_omitted": (not preflight_should_validate)
        or preflight.get("raw_private_values_included") is False,
        "pre_send_preflight_local_paths_omitted": (not preflight_should_validate)
        or preflight.get("local_paths_included") is False,
        "raw_recipient_omitted": dispatch_record.get("raw_recipient_included") is False,
        "raw_message_thread_omitted": dispatch_record.get("raw_message_thread_included") is False,
        "sent_record_consistent": (sent_recorded and payload.get("status") == "dispatch_recorded")
        or ((not sent_recorded) and payload.get("status") == "ready_to_dispatch_one"),
        "sent_record_private_hashes_valid": (not sent_recorded)
        or (
            _looks_like_sha256(dispatch_record.get("recipient_private_sha256"))
            and _looks_like_sha256(dispatch_record.get("operator_dispatch_note_private_sha256"))
            and _sent_at_utc_is_valid(dispatch_record.get("sent_at_utc"))
        ),
        "no_success_rate_claim": metrics.get("success_rate") is None,
        "proof_claim_blocked": metrics.get("proof_claim_allowed") is False,
        "sale_ready_blocked": metrics.get("sale_ready") is False,
        "market_validated_blocked": metrics.get("market_validated") is False,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": required_chain_kinds.issubset(set(chain_by_kind)),
        "artifact_chain_hashes_present": bool(artifact_chain)
        and all(isinstance(item, dict) and _looks_like_sha256(item.get("sha256")) for item in artifact_chain),
        "artifact_chain_release_hash_matched": chain_by_kind.get("release_zip", {}).get("sha256")
        == release.get("archive_sha256"),
        "artifact_chain_pilot_ready_hash_matched": chain_by_kind.get("pilot_ready_json", {}).get("sha256")
        == pilot_ready.get("body_sha256"),
        "artifact_chain_bundle_smoke_hash_matched": chain_by_kind.get("bundle_smoke_receipt_json", {}).get("sha256")
        == bundle_smoke.get("body_sha256"),
        "artifact_chain_preflight_hash_matched_when_used": (not preflight_should_validate)
        or chain_by_kind.get("pre_send_preflight_receipt_json", {}).get("sha256") == preflight.get("body_sha256"),
        "artifact_chain_dispatch_record_hash_matched": chain_by_kind.get("dispatch_record_json", {}).get("sha256")
        == body_hash,
        "do_not_share_guardrails_present": ".env" in do_not_share
        and "raw AI reply" in do_not_share
        and "recipient raw identifier" in do_not_share,
        "dispatch_record_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "dispatch_record_body_hash_matched": body_hash == _dispatch_record_body_sha256(payload),
    }


def _dispatch_record_markdown(payload: dict[str, Any]) -> str:
    """泥?諛쒖넚 湲곕줉 ?λ?瑜??щ엺???쎌쓣 ???덈뒗 Markdown?쇰줈 留뚮뱺??"""
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    copy_policy = "\n".join(
        f"- {name}: {passed}" for name, passed in payload["send_materials"]["copy_paste_message_policy"].items()
    )
    artifact_chain = "\n".join(
        f"- {item['kind']}: {item['file']} {item['sha256']}" for item in payload["artifact_chain"]
    )
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    dispatch_record = payload["dispatch_record"]
    dispatch_policy = payload["dispatch_execution_policy"]
    preflight = payload["pre_send_preflight"]
    return f"""# Cambrian External Alpha Dispatch Record

## Verdict

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- dispatch-record body sha256: {payload["dispatch_record_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- pilot-ready: {payload["pilot_ready"]["file"]}
- pilot-dispatch markdown: {payload["pilot_ready"]["dispatch_markdown"]}
- bundle smoke receipt: {payload["bundle_smoke_receipt"]["file"]}
- bundle smoke receipt body sha256: {payload["bundle_smoke_receipt"]["body_sha256"]}
- pilot-ready dispatch policy inherited: {payload["dispatch_record_checks"]["dispatch_policy_inherits_pilot_ready"]}

## Dispatch Scope

- target participants: {payload["dispatch_scope"]["target_participants"]}
- max recipients per record: {payload["dispatch_scope"]["max_recipients_per_record"]}
- timebox minutes: {payload["dispatch_scope"]["timebox_minutes"]}
- cohort scaling allowed: {payload["dispatch_scope"]["cohort_scaling_allowed"]}

## Dispatch Execution Policy

- script sends to recipient: {dispatch_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {dispatch_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {dispatch_policy["manual_operator_dispatch_required"]}
- max recipients per record: {dispatch_policy["max_recipients_per_record"]}
- records private sha256 only: {dispatch_policy["records_private_sha256_only"]}
- raw private content included: {dispatch_policy["raw_private_content_included"]}
- cohort scaling allowed: {dispatch_policy["cohort_scaling_allowed"]}
- sent recorded by private hashes only: {dispatch_policy["sent_recorded_by_private_hashes_only"]}

## Send Materials

- zip file: {payload["send_materials"]["zip_file"]}
- archive sha256: {payload["send_materials"]["archive_sha256"]}
- pilot dispatch markdown: {payload["send_materials"]["pilot_dispatch_markdown"]}
- copy-paste message sha256: {payload["send_materials"]["copy_paste_message_sha256"]}

## Pre-send Preflight

- required: {preflight["required"]}
- file: {preflight["file"]}
- body sha256: {preflight["body_sha256"]}
- release archive sha256: {preflight["release_archive_sha256"]}
- verdict: {preflight["verdict"]}
- verified standalone: {preflight["verified_standalone"]}
- private hashes matched: {preflight["private_hashes_matched"]}
- raw private values included: {preflight["raw_private_values_included"]}
- local paths included: {preflight["local_paths_included"]}

## Copy Paste Message Policy

{copy_policy}

## Private Dispatch Record

- sent recorded: {dispatch_record["sent_recorded"]}
- sent at utc: {dispatch_record["sent_at_utc"]}
- recipient private sha256: {dispatch_record["recipient_private_sha256"]}
- operator dispatch note private sha256: {dispatch_record["operator_dispatch_note_private_sha256"]}
- raw recipient included: {dispatch_record["raw_recipient_included"]}
- raw message thread included: {dispatch_record["raw_message_thread_included"]}

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
    """JSON ?뚯씪???쎄퀬 媛앹껜?몄? ?뺤씤?쒕떎."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DispatchRecordError(f"JSON ?뚯씪???쎌쓣 ???놁뒿?덈떎: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise DispatchRecordError(f"JSON ?뚯떛 ?ㅽ뙣: {path.name}") from exc
    if not isinstance(payload, dict):
        raise DispatchRecordError(f"JSON 媛앹껜媛 ?꾨떃?덈떎: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """JSON ?뚯씪???덉젙?곸씤 ?쒖꽌濡??대떎."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text_sha256(value: str) -> str:
    """臾몄옄??sha256??怨꾩궛?쒕떎."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    """sha256 臾몄옄???뺤떇?몄? ?뺤씤?쒕떎."""
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _assert_shareable_file(path: Path) -> None:
    """?앹꽦???λ???濡쒖뺄 ?덈?寃쎈줈? ?뚯뒪???쒗겕由우씠 ?녿뒗吏 ?뺤씤?쒕떎."""
    text = path.read_text(encoding="utf-8")
    forbidden_fragments = [str(ROOT), str(Path.home()), "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"]
    found = [fragment for fragment in forbidden_fragments if fragment and fragment in text]
    if found:
        raise DispatchRecordError(f"dispatch-record ?λ???怨듭쑀?섎㈃ ???섎뒗 寃쎈줈 ?먮뒗 媛믪씠 ?ы븿?섏뿀?듬땲?? {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
