"""외부 알파 첫 파일럿 결과 검토 준비 상태를 생성한다."""

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
from scripts.check_external_alpha_pilot_ready import (
    PILOT_DISPATCH_MD_NAME,
    PILOT_READY_JSON_NAME,
    PILOT_READY_MD_NAME,
)
from scripts.check_external_alpha_recipient_checkpoint import (
    RECIPIENT_CHECKPOINT_JSON_NAME,
    RECIPIENT_CHECKPOINT_MD_NAME,
    check_recipient_checkpoint,
    verify_recipient_checkpoint_file,
)
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR


PILOT_REVIEW_SCHEMA_VERSION = "external_alpha_pilot_review_v0_1"
PILOT_REVIEW_JSON_NAME = f"{RELEASE_SLUG}-pilot-review.json"
PILOT_REVIEW_MD_NAME = f"{RELEASE_SLUG}-pilot-review.md"

logger = logging.getLogger(__name__)


class PilotReviewError(Exception):
    """외부 알파 파일럿 검토 준비 판정 실패."""


def check_pilot_review(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    skip_build: bool = False,
    recipient_ack_private_sha256: str | None = None,
    recipient_ack_private_file: Path | None = None,
    recipient_private_sha256: str | None = None,
    recipient_private_file: Path | None = None,
    operator_dispatch_note_private_sha256: str | None = None,
    operator_dispatch_note_private_file: Path | None = None,
    sent_at_utc: str | None = None,
    builder_gold_path_share_receipt: Path | None = None,
    private_workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """recipient-checkpoint 산출물을 기반으로 첫 파일럿 검토 대기 상태를 만든다."""
    output_dir = output_dir.resolve()
    recipient_checkpoint_result = check_recipient_checkpoint(
        output_dir,
        skip_build=skip_build,
        recipient_ack_private_sha256=recipient_ack_private_sha256,
        recipient_ack_private_file=recipient_ack_private_file,
        recipient_private_sha256=recipient_private_sha256,
        recipient_private_file=recipient_private_file,
        operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
        operator_dispatch_note_private_file=operator_dispatch_note_private_file,
        sent_at_utc=sent_at_utc,
        builder_gold_path_share_receipt=builder_gold_path_share_receipt,
        private_workspace_dir=private_workspace_dir,
    )
    recipient_checkpoint_path = Path(str(recipient_checkpoint_result["recipient_checkpoint_json"]))
    recipient_checkpoint = verify_recipient_checkpoint_file(recipient_checkpoint_path)
    payload = _pilot_review_payload(recipient_checkpoint)

    json_path = output_dir / PILOT_REVIEW_JSON_NAME
    md_path = output_dir / PILOT_REVIEW_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_pilot_review_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "pilot_review_json": str(json_path),
        "pilot_review_md": str(md_path),
        "recipient_checkpoint_json": str(recipient_checkpoint_path),
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="외부 알파 첫 파일럿 결과 검토 준비 판정서를 생성한다.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="릴리즈 산출물 폴더. 기본값은 dist")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="기존 ZIP, handoff, send-ready, pilot-ready, dispatch-record를 재사용한다.",
    )
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
    parser.add_argument(
        "--builder-gold-path-share-receipt",
        "--gold-path-share-receipt",
        dest="builder_gold_path_share_receipt",
        default=None,
        help="수령자가 Builder Golden Path 완료 후 보낸 share-safe receipt JSON",
    )
    parser.add_argument("--verify-pilot-review", default=None, help="pilot-review JSON만 단독 검증한다.")
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

    if args.verify_pilot_review:
        try:
            payload = verify_pilot_review_file(Path(args.verify_pilot_review))
        except Exception as exc:  # noqa: BLE001 - 운영 검증 실패 이유를 한 줄로 전달한다.
            logger.error("[FAIL] external alpha pilot-review verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha pilot-review verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["pilot_review_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = check_pilot_review(
            Path(args.output_dir),
            skip_build=args.skip_build,
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
        )
    except Exception as exc:  # noqa: BLE001 - 운영 게이트는 실패 조건을 사용자에게 직접 보여준다.
        logger.error("[FAIL] external alpha pilot-review: %s", exc)
        return 1

    logger.info("[PASS] external alpha pilot-review")
    logger.info("verdict       : %s", result["verdict"])
    logger.info("pilot_review_md: %s", result["pilot_review_md"])
    logger.info("zip           : %s", result["zip_file"])
    logger.info("sha256        : %s", result["archive_sha256"])
    return 0


def _pilot_review_payload(recipient_checkpoint: dict[str, Any]) -> dict[str, Any]:
    """recipient-checkpoint 이후 실제 파일럿 증거가 오기 전의 검토 계약을 만든다."""
    release = recipient_checkpoint.get("release") if isinstance(recipient_checkpoint.get("release"), dict) else {}
    dispatch_record = (
        recipient_checkpoint.get("dispatch_record")
        if isinstance(recipient_checkpoint.get("dispatch_record"), dict)
        else {}
    )
    pilot_ready = (
        recipient_checkpoint.get("pilot_ready") if isinstance(recipient_checkpoint.get("pilot_ready"), dict) else {}
    )
    dispatch_policy = (
        recipient_checkpoint.get("dispatch_execution_policy")
        if isinstance(recipient_checkpoint.get("dispatch_execution_policy"), dict)
        else {}
    )
    checkpoint_checks = (
        recipient_checkpoint.get("recipient_checkpoint_checks")
        if isinstance(recipient_checkpoint.get("recipient_checkpoint_checks"), dict)
        else {}
    )
    decision_thresholds = (
        recipient_checkpoint.get("decision_thresholds")
        if isinstance(recipient_checkpoint.get("decision_thresholds"), dict)
        else {}
    )
    do_not_share = (
        recipient_checkpoint.get("do_not_share") if isinstance(recipient_checkpoint.get("do_not_share"), list) else []
    )
    shared_checkpoint = (
        recipient_checkpoint.get("shared_checkpoint")
        if isinstance(recipient_checkpoint.get("shared_checkpoint"), dict)
        else {}
    )
    builder_gold_path = (
        shared_checkpoint.get("builder_gold_path")
        if isinstance(shared_checkpoint.get("builder_gold_path"), dict)
        else {}
    )
    checkpoint_metrics = (
        recipient_checkpoint.get("metrics") if isinstance(recipient_checkpoint.get("metrics"), dict) else {}
    )
    evidence_required = _evidence_required()
    forbidden_claims = _forbidden_claims()
    checks = {
        "recipient_checkpoint_ready_or_waiting": recipient_checkpoint.get("status")
        in {"awaiting_recipient_checkpoint", "recipient_checkpoint_recorded", "recipient_gold_path_confirmed"}
        and recipient_checkpoint.get("verdict")
        in {"WAITING_FOR_RECIPIENT", "RECIPIENT_CHECKPOINT_RECORDED", "RECIPIENT_GOLD_PATH_CONFIRMED"},
        "recipient_checkpoint_checks_true": bool(checkpoint_checks)
        and all(value is True for value in checkpoint_checks.values()),
        "recipient_checkpoint_body_hash_present": _looks_like_sha256(
            recipient_checkpoint.get("recipient_checkpoint_body_sha256")
        ),
        "dispatch_record_body_hash_present": _looks_like_sha256(dispatch_record.get("body_sha256")),
        "dispatch_record_verified_standalone": dispatch_record.get("verified_standalone") is True,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "checkpoint_raw_private_content_omitted": recipient_checkpoint.get("private_checkpoint_fingerprints", {}).get(
            "raw_private_content_included"
        )
        is False,
        "decision_thresholds_present": {"continue", "fix_before_next", "stop_and_redesign"}.issubset(
            set(decision_thresholds)
        ),
        "evidence_required_before_decision": len(evidence_required) >= 4
        and any("PILOT_FEEDBACK_FORM" in item for item in evidence_required)
        and any("external_alpha_diagnostics.json" in item for item in evidence_required),
        "forbidden_claims_present": {"success rate", "proof claim", "sale ready"}.issubset(set(forbidden_claims)),
        "do_not_share_guardrails": ".env" in do_not_share and "raw AI reply" in do_not_share,
    }
    payload = {
        "schema_version": PILOT_REVIEW_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_pilot_evidence",
        "verdict": "WAITING_FOR_EVIDENCE",
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
            "body_sha256": pilot_ready.get("body_sha256"),
            "verified_standalone": True,
        },
        "dispatch_record": {
            "file": dispatch_record.get("file"),
            "markdown": dispatch_record.get("markdown"),
            "body_sha256": dispatch_record.get("body_sha256"),
            "verified_standalone": True,
            "verdict": dispatch_record.get("verdict"),
            "sent_recorded": dispatch_record.get("sent_recorded"),
        },
        "dispatch_execution_policy": dispatch_policy,
        "recipient_checkpoint": {
            "file": RECIPIENT_CHECKPOINT_JSON_NAME,
            "markdown": RECIPIENT_CHECKPOINT_MD_NAME,
            "body_sha256": recipient_checkpoint.get("recipient_checkpoint_body_sha256"),
            "verified_standalone": True,
            "verdict": recipient_checkpoint.get("verdict"),
            "status": recipient_checkpoint.get("status"),
            "builder_gold_path_confirmed": checkpoint_metrics.get("builder_gold_path_confirmed") is True,
            "builder_gold_path_share_receipt_sha256": builder_gold_path.get("sha256"),
            "builder_gold_path_capabilities_verified": builder_gold_path.get("capabilities_verified", {}),
        },
        "pilot_evidence": {
            "status": "not_collected",
            "required_before_decision": evidence_required,
            "allowed_shared_files": [
                "external_alpha_release_verification_receipt.json",
                "external_alpha_diagnostics.json",
            ],
            "private_workspace_only": [
                "completed docs/launch/PILOT_FEEDBACK_FORM.md",
                "completed docs/launch/PILOT_ISSUE_INTAKE.md",
            ],
        },
        "metrics": {
            "pilot_participants_completed": 0,
            "success_rate": None,
            "proof_claim_allowed": False,
            "sale_ready": False,
        },
        "decision_matrix": decision_thresholds,
        "forbidden_claims": forbidden_claims,
        "checks": checks,
        "operator_next_action": "첫 사용자 1명의 feedback, issue intake, receipt, diagnostics를 받은 뒤에만 continue/fix/stop을 판단한다.",
        "do_not_share": do_not_share,
    }
    payload["pilot_review_body_sha256"] = _pilot_review_body_sha256(payload)
    payload["artifact_chain"] = _pilot_review_artifact_chain(recipient_checkpoint, payload)
    payload["pilot_review_checks"] = _pilot_review_checks(payload)
    verify_pilot_review_payload(payload)
    return payload


def verify_pilot_review_file(path: Path) -> dict[str, Any]:
    """pilot-review JSON만 읽어 대기 상태와 공유 안전성을 검증한다."""
    payload = _read_json(path)
    verify_pilot_review_payload(payload)
    return payload


def verify_pilot_review_payload(payload: dict[str, Any]) -> None:
    """pilot-review JSON이 실제 증거 전 성공을 주장하지 않는지 확인한다."""
    if payload.get("schema_version") != PILOT_REVIEW_SCHEMA_VERSION:
        raise PilotReviewError("pilot-review schema_version이 올바르지 않습니다.")
    if payload.get("status") != "awaiting_pilot_evidence":
        raise PilotReviewError(f"pilot-review status가 awaiting_pilot_evidence가 아닙니다: {payload.get('status')}")
    if payload.get("verdict") != "WAITING_FOR_EVIDENCE":
        raise PilotReviewError(f"pilot-review verdict가 WAITING_FOR_EVIDENCE가 아닙니다: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise PilotReviewError("pilot-review safe_to_share가 true가 아닙니다.")

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PilotReviewError("pilot-review checks가 모두 true가 아닙니다.")

    review_checks = payload.get("pilot_review_checks") if isinstance(payload.get("pilot_review_checks"), dict) else {}
    if not review_checks:
        raise PilotReviewError("pilot_review_checks가 없습니다.")
    if payload.get("pilot_review_body_sha256") != _pilot_review_body_sha256(payload):
        raise PilotReviewError("pilot-review 본문 해시가 일치하지 않습니다.")
    recalculated_checks = _pilot_review_checks(payload)
    if review_checks != recalculated_checks:
        raise PilotReviewError("pilot-review 안전 평가 결과가 현재 본문과 일치하지 않습니다.")
    failed_checks = [name for name, passed in recalculated_checks.items() if passed is not True]
    if failed_checks:
        raise PilotReviewError("pilot-review 안전 평가 실패: " + ", ".join(failed_checks))


def _evidence_required() -> list[str]:
    """첫 파일럿 판단 전에 반드시 있어야 하는 증거 목록."""
    return [
        "completed docs/launch/PILOT_FEEDBACK_FORM.md in private workspace",
        "completed docs/launch/PILOT_ISSUE_INTAKE.md if anything blocked the run",
        "external_alpha_release_verification_receipt.json with safe_to_share true",
        "external_alpha_diagnostics.json with every redaction_check true",
        "operator note explaining continue, fix_before_next, or stop_and_redesign decision",
    ]


def _forbidden_claims() -> list[str]:
    """파일럿 증거 전에는 주장하면 안 되는 문구."""
    return [
        "success rate",
        "proof claim",
        "sale ready",
        "market demand validated",
        "performance improvement",
    ]


def _pilot_review_body_sha256(payload: dict[str, Any]) -> str:
    """pilot-review 검증 본문만 정규화해 sha256 해시를 계산한다."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"pilot_review_body_sha256", "artifact_chain", "pilot_review_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pilot_review_artifact_chain(recipient_checkpoint: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    """recipient-checkpoint 증거 체인에 pilot-review 판정서 해시를 덧붙인다."""
    source_chain = (
        recipient_checkpoint.get("artifact_chain")
        if isinstance(recipient_checkpoint.get("artifact_chain"), list)
        else []
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
            "kind": "pilot_review_json",
            "file": PILOT_REVIEW_JSON_NAME,
            "sha256": str(payload.get("pilot_review_body_sha256") or ""),
        }
    )
    return chain


def _pilot_review_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """pilot-review 판정서가 증거 전 성공 주장 없이 공유 가능한지 평가한다."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    pilot_ready = payload.get("pilot_ready") if isinstance(payload.get("pilot_ready"), dict) else {}
    dispatch_record = payload.get("dispatch_record") if isinstance(payload.get("dispatch_record"), dict) else {}
    dispatch_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    recipient_checkpoint = (
        payload.get("recipient_checkpoint") if isinstance(payload.get("recipient_checkpoint"), dict) else {}
    )
    evidence = payload.get("pilot_evidence") if isinstance(payload.get("pilot_evidence"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    decision_matrix = payload.get("decision_matrix") if isinstance(payload.get("decision_matrix"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    artifact_chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    forbidden_claims = payload.get("forbidden_claims") if isinstance(payload.get("forbidden_claims"), list) else []
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    body_hash = payload.get("pilot_review_body_sha256")
    chain_by_kind = {
        item.get("kind"): item
        for item in artifact_chain
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    return {
        "schema_version_present": payload.get("schema_version") == PILOT_REVIEW_SCHEMA_VERSION,
        "waiting_for_evidence_status": payload.get("status") == "awaiting_pilot_evidence",
        "verdict_waiting_for_evidence": payload.get("verdict") == "WAITING_FOR_EVIDENCE",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "pilot_ready_body_hash_present": _looks_like_sha256(pilot_ready.get("body_sha256")),
        "pilot_ready_verified_standalone": pilot_ready.get("verified_standalone") is True,
        "dispatch_record_body_hash_present": _looks_like_sha256(dispatch_record.get("body_sha256")),
        "dispatch_record_verified_standalone": dispatch_record.get("verified_standalone") is True,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "recipient_checkpoint_body_hash_present": _looks_like_sha256(recipient_checkpoint.get("body_sha256")),
        "recipient_checkpoint_verified_standalone": recipient_checkpoint.get("verified_standalone") is True,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": {
            "release_zip",
            "handoff_json",
            "receipt_json",
            "send_ready_json",
            "pilot_ready_json",
            "dispatch_record_json",
            "recipient_checkpoint_json",
            "pilot_review_json",
        }.issubset(set(chain_by_kind)),
        "artifact_chain_hashes_present": bool(artifact_chain)
        and all(isinstance(item, dict) and _looks_like_sha256(item.get("sha256")) for item in artifact_chain),
        "artifact_chain_release_hash_matched": chain_by_kind.get("release_zip", {}).get("sha256")
        == release.get("archive_sha256"),
        "artifact_chain_pilot_ready_hash_matched": chain_by_kind.get("pilot_ready_json", {}).get("sha256")
        == pilot_ready.get("body_sha256"),
        "artifact_chain_dispatch_record_hash_matched": chain_by_kind.get("dispatch_record_json", {}).get("sha256")
        == dispatch_record.get("body_sha256"),
        "artifact_chain_recipient_checkpoint_hash_matched": chain_by_kind.get(
            "recipient_checkpoint_json", {}
        ).get("sha256")
        == recipient_checkpoint.get("body_sha256"),
        "artifact_chain_pilot_review_hash_matched": chain_by_kind.get("pilot_review_json", {}).get("sha256")
        == body_hash,
        "evidence_not_collected": evidence.get("status") == "not_collected",
        "evidence_required_before_decision": len(evidence.get("required_before_decision", [])) >= 4,
        "no_success_rate_before_evidence": metrics.get("success_rate") is None,
        "proof_claim_blocked": metrics.get("proof_claim_allowed") is False,
        "sale_ready_blocked": metrics.get("sale_ready") is False,
        "participant_count_zero": metrics.get("pilot_participants_completed") == 0,
        "decision_matrix_present": {"continue", "fix_before_next", "stop_and_redesign"}.issubset(
            set(decision_matrix)
        ),
        "forbidden_claims_present": {"success rate", "proof claim", "sale ready"}.issubset(set(forbidden_claims)),
        "do_not_share_guardrails_present": ".env" in do_not_share and "raw AI reply" in do_not_share,
        "pilot_review_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "pilot_review_body_hash_matched": body_hash == _pilot_review_body_sha256(payload),
    }


def _pilot_review_markdown(payload: dict[str, Any]) -> str:
    """파일럿 검토 대기 판정서를 사람이 읽을 수 있는 Markdown으로 만든다."""
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    artifact_chain = "\n".join(
        f"- {item['kind']}: {item['file']} {item['sha256']}" for item in payload["artifact_chain"]
    )
    evidence = "\n".join(f"- {item}" for item in payload["pilot_evidence"]["required_before_decision"])
    forbidden = "\n".join(f"- {item}" for item in payload["forbidden_claims"])
    continue_rules = "\n".join(f"- {item}" for item in payload["decision_matrix"]["continue"])
    fix_rules = "\n".join(f"- {item}" for item in payload["decision_matrix"]["fix_before_next"])
    stop_rules = "\n".join(f"- {item}" for item in payload["decision_matrix"]["stop_and_redesign"])
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    dispatch_policy = payload["dispatch_execution_policy"]
    return f"""# Cambrian External Alpha Pilot Review

## Awaiting Pilot Evidence

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- pilot-review body sha256: {payload["pilot_review_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- pilot-ready: {payload["pilot_ready"]["file"]}
- pilot-ready body sha256: {payload["pilot_ready"]["body_sha256"]}
- dispatch-record: {payload["dispatch_record"]["file"]}
- dispatch-record body sha256: {payload["dispatch_record"]["body_sha256"]}
- recipient-checkpoint: {payload["recipient_checkpoint"]["file"]}
- recipient-checkpoint body sha256: {payload["recipient_checkpoint"]["body_sha256"]}
- success rate: not collected
- proof claim allowed: {payload["metrics"]["proof_claim_allowed"]}
- sale ready: {payload["metrics"]["sale_ready"]}

## Dispatch Execution Policy

- script sends to recipient: {dispatch_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {dispatch_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {dispatch_policy["manual_operator_dispatch_required"]}
- max recipients per record: {dispatch_policy["max_recipients_per_record"]}
- records private sha256 only: {dispatch_policy["records_private_sha256_only"]}
- raw private content included: {dispatch_policy["raw_private_content_included"]}
- cohort scaling allowed: {dispatch_policy["cohort_scaling_allowed"]}
- sent recorded by private hashes only: {dispatch_policy["sent_recorded_by_private_hashes_only"]}

## Checks

{checks}

## Evidence Required Before Decision

{evidence}

## Artifact Chain

{artifact_chain}

## Continue

{continue_rules}

## Fix Before Next

{fix_rules}

## Stop And Redesign

{stop_rules}

## Forbidden Claims

{forbidden}

## Do Not Share

{do_not_share}

## Operator Next Action

{payload["operator_next_action"]}
"""


def _read_json(path: Path) -> dict[str, Any]:
    """JSON 파일을 읽고 객체인지 확인한다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PilotReviewError(f"JSON 파일을 읽을 수 없습니다: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PilotReviewError(f"JSON 파싱 실패: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PilotReviewError(f"JSON 객체가 아닙니다: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """JSON 파일을 안정적인 순서로 쓴다."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _looks_like_sha256(value: Any) -> bool:
    """sha256 문자열 형식인지 확인한다."""
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _assert_shareable_file(path: Path) -> None:
    """생성된 판정서에 로컬 절대경로와 테스트 시크릿이 없는지 확인한다."""
    text = path.read_text(encoding="utf-8")
    forbidden_fragments = [str(ROOT), str(Path.home()), "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"]
    found = [fragment for fragment in forbidden_fragments if fragment and fragment in text]
    if found:
        raise PilotReviewError(f"pilot-review 판정서에 공유하면 안 되는 경로 또는 값이 포함되었습니다: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
