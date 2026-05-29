"""외부 알파 첫 파일럿 증거 패킷을 시크릿 없이 검증한다."""

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
from scripts.check_external_alpha_pilot_review import (
    PILOT_REVIEW_JSON_NAME,
    PILOT_REVIEW_MD_NAME,
    check_pilot_review,
    verify_pilot_review_file,
)
from scripts.collect_external_alpha_diagnostics import collect_diagnostics
from scripts.prepare_external_alpha_handoff import RECEIPT_NAME
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR
from scripts.verify_external_alpha_release import verify_shareable_receipt_file


PILOT_EVIDENCE_SCHEMA_VERSION = "external_alpha_pilot_evidence_v0_1"
PILOT_EVIDENCE_JSON_NAME = f"{RELEASE_SLUG}-pilot-evidence.json"
PILOT_EVIDENCE_MD_NAME = f"{RELEASE_SLUG}-pilot-evidence.md"
DIAGNOSTICS_NAME = "external_alpha_diagnostics.json"
OPERATOR_DECISIONS = {"not_decided", "continue", "fix_before_next", "stop_and_redesign"}
OUTCOME_TAGS = {
    "not_collected",
    "completed_gold_path",
    "partial",
    "blocked_install",
    "blocked_launch",
    "blocked_builder",
    "blocked_runner",
    "blocked_understanding",
    "blocked_trust",
}
FRICTION_TAGS = {
    "none",
    "install",
    "launch",
    "builder",
    "runner",
    "evolution",
    "proof_trust",
    "terminology",
    "docs",
    "performance",
    "privacy",
    "other",
}
MISSING_SKILL_TAGS = {
    "none",
    "agent_generation",
    "skill_generation",
    "skill_search",
    "skill_fusion",
    "harness_engineering",
    "evolution_apply",
    "company_snapshot",
    "platform_launch",
    "support_diagnostics",
    "other",
}

logger = logging.getLogger(__name__)


class PilotEvidenceError(Exception):
    """외부 알파 파일럿 증거 검증 실패."""


def check_pilot_evidence(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    skip_build: bool = False,
    receipt_path: Path | None = None,
    diagnostics_path: Path | None = None,
    feedback_private_sha256: str | None = None,
    feedback_private_file: Path | None = None,
    issue_intake_private_sha256: str | None = None,
    issue_intake_private_file: Path | None = None,
    recipient_ack_private_sha256: str | None = None,
    recipient_ack_private_file: Path | None = None,
    recipient_private_sha256: str | None = None,
    recipient_private_file: Path | None = None,
    operator_dispatch_note_private_sha256: str | None = None,
    operator_dispatch_note_private_file: Path | None = None,
    sent_at_utc: str | None = None,
    builder_gold_path_share_receipt: Path | None = None,
    operator_decision: str = "not_decided",
    outcome_tag: str = "not_collected",
    friction_tags: list[str] | None = None,
    missing_skill_tags: list[str] | None = None,
    private_workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """공유 가능한 receipt/diagnostics와 private feedback 해시만으로 파일럿 증거 상태를 만든다."""
    output_dir = output_dir.resolve()
    if private_workspace_dir is not None:
        feedback_private_file, issue_intake_private_file = _resolve_evidence_private_workspace_files(
            private_workspace_dir=private_workspace_dir,
            feedback_private_sha256=feedback_private_sha256,
            feedback_private_file=feedback_private_file,
            issue_intake_private_sha256=issue_intake_private_sha256,
            issue_intake_private_file=issue_intake_private_file,
        )
        feedback_private_sha256 = None
        issue_intake_private_sha256 = None
    resolved_feedback_sha256 = _resolve_private_sha256(
        direct_sha256=feedback_private_sha256,
        private_file=feedback_private_file,
        label="pilot feedback",
    )
    resolved_issue_sha256 = _resolve_private_sha256(
        direct_sha256=issue_intake_private_sha256,
        private_file=issue_intake_private_file,
        label="issue intake",
    )
    pilot_review_result = check_pilot_review(
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
    pilot_review_path = Path(str(pilot_review_result["pilot_review_json"]))
    pilot_review = verify_pilot_review_file(pilot_review_path)

    resolved_receipt = receipt_path.resolve() if receipt_path is not None else output_dir / RECEIPT_NAME
    resolved_diagnostics = diagnostics_path.resolve() if diagnostics_path is not None else output_dir / DIAGNOSTICS_NAME
    if diagnostics_path is None:
        collect_diagnostics(resolved_diagnostics)

    receipt = verify_shareable_receipt_file(resolved_receipt)
    diagnostics = verify_diagnostics_file(resolved_diagnostics)
    payload = _pilot_evidence_payload(
        pilot_review=pilot_review,
        receipt=receipt,
        diagnostics=diagnostics,
        diagnostics_file=resolved_diagnostics.name,
        feedback_private_sha256=resolved_feedback_sha256,
        issue_intake_private_sha256=resolved_issue_sha256,
        operator_decision=operator_decision,
        outcome_tag=outcome_tag,
        friction_tags=friction_tags,
        missing_skill_tags=missing_skill_tags,
    )

    json_path = output_dir / PILOT_EVIDENCE_JSON_NAME
    md_path = output_dir / PILOT_EVIDENCE_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_pilot_evidence_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "pilot_evidence_json": str(json_path),
        "pilot_evidence_md": str(md_path),
        "pilot_review_json": str(pilot_review_path),
        "receipt_json": str(resolved_receipt),
        "diagnostics_json": str(resolved_diagnostics),
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="외부 알파 첫 파일럿 증거 패킷을 검증한다.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="릴리즈 산출물 폴더. 기본값은 dist")
    parser.add_argument("--skip-build", action="store_true", help="기존 ZIP, handoff, send-ready, pilot-ready를 재사용한다.")
    parser.add_argument("--receipt", default=None, help="공유 가능한 release receipt JSON 경로")
    parser.add_argument("--diagnostics", default=None, help="공유 가능한 diagnostics JSON 경로. 생략하면 새로 생성한다.")
    parser.add_argument("--feedback-private-sha256", default=None, help="완료된 pilot feedback 원문 대신 저장할 private sha256")
    parser.add_argument(
        "--feedback-private-file",
        default=None,
        help="완료된 pilot feedback 원문 파일 경로. 파일 내용과 경로는 저장하지 않고 sha256만 계산한다.",
    )
    parser.add_argument("--issue-intake-private-sha256", default=None, help="완료된 issue intake 원문 대신 저장할 private sha256")
    parser.add_argument(
        "--issue-intake-private-file",
        default=None,
        help="완료된 issue intake 원문 파일 경로. 파일 내용과 경로는 저장하지 않고 sha256만 계산한다.",
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
    parser.add_argument("--operator-decision", default="not_decided", choices=sorted(OPERATOR_DECISIONS))
    parser.add_argument("--outcome-tag", default="not_collected", choices=sorted(OUTCOME_TAGS))
    parser.add_argument(
        "--friction-tag",
        action="append",
        dest="friction_tags",
        default=None,
        help="Raw feedback 대신 기록할 controlled friction tag. 반복 사용하거나 comma로 여러 개를 넣을 수 있다.",
    )
    parser.add_argument(
        "--missing-skill-tag",
        action="append",
        dest="missing_skill_tags",
        default=None,
        help="Raw issue 대신 기록할 controlled missing-skill tag. 반복 사용하거나 comma로 여러 개를 넣을 수 있다.",
    )
    parser.add_argument("--verify-pilot-evidence", default=None, help="pilot-evidence JSON만 단독 검증한다.")
    parser.add_argument(
        "--private-workspace-dir",
        default=None,
        help=(
            "Standard private workspace directory. Uses recipient/ack/dispatch files plus "
            "pilot-feedback-private.md and pilot-issue-intake-private.md after placeholders are replaced."
        ),
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_pilot_evidence:
        try:
            payload = verify_pilot_evidence_file(Path(args.verify_pilot_evidence))
        except Exception as exc:  # noqa: BLE001 - 운영 검증 실패 이유를 한 줄로 전달한다.
            logger.error("[FAIL] external alpha pilot-evidence verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha pilot-evidence verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["pilot_evidence_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = check_pilot_evidence(
            output_dir=Path(args.output_dir),
            skip_build=args.skip_build,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostics_path=Path(args.diagnostics) if args.diagnostics else None,
            feedback_private_sha256=args.feedback_private_sha256,
            feedback_private_file=Path(args.feedback_private_file) if args.feedback_private_file else None,
            issue_intake_private_sha256=args.issue_intake_private_sha256,
            issue_intake_private_file=Path(args.issue_intake_private_file) if args.issue_intake_private_file else None,
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
            operator_decision=args.operator_decision,
            outcome_tag=args.outcome_tag,
            friction_tags=args.friction_tags,
            missing_skill_tags=args.missing_skill_tags,
            private_workspace_dir=Path(args.private_workspace_dir) if args.private_workspace_dir else None,
        )
    except Exception as exc:  # noqa: BLE001 - 운영 게이트는 실패 조건을 사용자에게 직접 보여준다.
        logger.error("[FAIL] external alpha pilot-evidence: %s", exc)
        return 1

    logger.info("[PASS] external alpha pilot-evidence")
    logger.info("verdict         : %s", result["verdict"])
    logger.info("pilot_evidence_md: %s", result["pilot_evidence_md"])
    logger.info("zip             : %s", result["zip_file"])
    logger.info("sha256          : %s", result["archive_sha256"])
    return 0


def verify_diagnostics_file(path: Path) -> dict[str, Any]:
    """diagnostics JSON이 공유 가능한 최소 증거인지 검증한다."""
    payload = _read_json(path)
    _verify_diagnostics_payload(payload)
    return payload


def verify_pilot_evidence_file(path: Path) -> dict[str, Any]:
    """pilot-evidence JSON만 읽어 변조 여부와 공유 안전성을 검증한다."""
    payload = _read_json(path)
    verify_pilot_evidence_payload(payload)
    return payload


def verify_pilot_evidence_payload(payload: dict[str, Any]) -> None:
    """pilot-evidence JSON이 private 원문 없이 판단 경계를 지키는지 확인한다."""
    if payload.get("schema_version") != PILOT_EVIDENCE_SCHEMA_VERSION:
        raise PilotEvidenceError("pilot-evidence schema_version이 올바르지 않습니다.")
    if payload.get("status") not in {"awaiting_private_pilot_evidence", "pilot_evidence_ready"}:
        raise PilotEvidenceError(f"pilot-evidence status가 올바르지 않습니다: {payload.get('status')}")
    if payload.get("verdict") not in {"NO_DECISION", "READY_FOR_DECISION"}:
        raise PilotEvidenceError(f"pilot-evidence verdict가 올바르지 않습니다: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise PilotEvidenceError("pilot-evidence safe_to_share가 true가 아닙니다.")

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PilotEvidenceError("pilot-evidence checks가 모두 true가 아닙니다.")

    evidence_checks = (
        payload.get("pilot_evidence_checks") if isinstance(payload.get("pilot_evidence_checks"), dict) else {}
    )
    if not evidence_checks:
        raise PilotEvidenceError("pilot_evidence_checks가 없습니다.")
    if payload.get("pilot_evidence_body_sha256") != _pilot_evidence_body_sha256(payload):
        raise PilotEvidenceError("pilot-evidence 본문 해시가 일치하지 않습니다.")
    recalculated_checks = _pilot_evidence_checks(payload)
    if evidence_checks != recalculated_checks:
        raise PilotEvidenceError("pilot-evidence 안전 평가 결과가 현재 본문과 일치하지 않습니다.")
    failed_checks = [name for name, passed in recalculated_checks.items() if passed is not True]
    if failed_checks:
        raise PilotEvidenceError("pilot-evidence 안전 평가 실패: " + ", ".join(failed_checks))


def _pilot_evidence_payload(
    pilot_review: dict[str, Any],
    receipt: dict[str, Any],
    diagnostics: dict[str, Any],
    diagnostics_file: str,
    feedback_private_sha256: str | None,
    issue_intake_private_sha256: str | None,
    operator_decision: str,
    outcome_tag: str,
    friction_tags: list[str] | None,
    missing_skill_tags: list[str] | None,
) -> dict[str, Any]:
    """파일럿 증거 패킷을 원문 없이 구성한다."""
    release = pilot_review.get("release") if isinstance(pilot_review.get("release"), dict) else {}
    review_checks = (
        pilot_review.get("pilot_review_checks") if isinstance(pilot_review.get("pilot_review_checks"), dict) else {}
    )
    dispatch_policy = (
        pilot_review.get("dispatch_execution_policy")
        if isinstance(pilot_review.get("dispatch_execution_policy"), dict)
        else {}
    )
    diagnostics_summary = diagnostics.get("support_summary") if isinstance(diagnostics.get("support_summary"), dict) else {}
    redaction_checks = diagnostics.get("redaction_checks") if isinstance(diagnostics.get("redaction_checks"), dict) else {}
    feedback_hash_present = _looks_like_sha256(feedback_private_sha256)
    issue_hash_ok = issue_intake_private_sha256 is None or _looks_like_sha256(issue_intake_private_sha256)
    learning_summary = _pilot_learning_summary(outcome_tag, friction_tags, missing_skill_tags)
    learning_summary_collected = learning_summary["outcome_tag"] != "not_collected"
    decision_ready = feedback_hash_present and learning_summary_collected and operator_decision != "not_decided"
    checks = {
        "pilot_review_waiting_for_evidence": pilot_review.get("status") == "awaiting_pilot_evidence"
        and pilot_review.get("verdict") == "WAITING_FOR_EVIDENCE",
        "pilot_review_checks_true": bool(review_checks) and all(value is True for value in review_checks.values()),
        "receipt_passed": receipt.get("status") == "pass" and receipt.get("safe_to_share") is True,
        "receipt_body_hash_present": _looks_like_sha256(receipt.get("receipt_body_sha256")),
        "diagnostics_passed": diagnostics.get("status") == "pass" and diagnostics.get("safe_to_share") is True,
        "diagnostics_redaction_checks_true": bool(redaction_checks)
        and all(value is True for value in redaction_checks.values()),
        "diagnostics_support_summary_safe": diagnostics_summary.get("safe_to_share") is True
        and diagnostics_summary.get("status") == "pass",
        "operator_decision_valid": operator_decision in OPERATOR_DECISIONS,
        "private_hashes_are_sha256_or_missing": (feedback_private_sha256 is None or feedback_hash_present)
        and issue_hash_ok,
        "decision_blocked_without_feedback_hash": operator_decision == "not_decided" or feedback_hash_present,
        "learning_summary_controlled_tags": _learning_summary_controlled(learning_summary),
        "learning_summary_no_free_text": learning_summary.get("free_text_included") is False
        and learning_summary.get("raw_feedback_included") is False
        and learning_summary.get("raw_issue_included") is False,
        "decision_blocked_without_learning_summary": operator_decision == "not_decided" or learning_summary_collected,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "raw_private_content_omitted": True,
    }
    payload = {
        "schema_version": PILOT_EVIDENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pilot_evidence_ready" if decision_ready else "awaiting_private_pilot_evidence",
        "verdict": "READY_FOR_DECISION" if decision_ready else "NO_DECISION",
        "safe_to_share": True,
        "release": {
            "version": release.get("version"),
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "pilot_review": {
            "file": PILOT_REVIEW_JSON_NAME,
            "markdown": PILOT_REVIEW_MD_NAME,
            "body_sha256": pilot_review.get("pilot_review_body_sha256"),
            "verified_standalone": True,
        },
        "dispatch_execution_policy": dispatch_policy,
        "shared_evidence": {
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
                "support_next_action": diagnostics_summary.get("next_action"),
            },
        },
        "private_evidence_fingerprints": {
            "feedback_form_sha256": feedback_private_sha256,
            "issue_intake_sha256": issue_intake_private_sha256,
            "raw_private_content_included": False,
        },
        "pilot_learning_summary": learning_summary,
        "operator_decision": operator_decision,
        "decision_allowed": decision_ready,
        "metrics": {
            "pilot_participants_completed": 1 if feedback_hash_present and learning_summary_collected else 0,
            "success_rate": None,
            "proof_claim_allowed": False,
            "sale_ready": False,
        },
        "forbidden_claims": [
            "success rate",
            "proof claim",
            "sale ready",
            "market demand validated",
            "performance improvement",
        ],
        "checks": checks,
        "operator_next_action": "private feedback 해시, controlled learning summary, 운영 판단을 확인한 뒤 pilot decision 단계로 이동한다."
        if decision_ready
        else "완료된 pilot feedback 원문은 private workspace에 두고 sha256과 controlled outcome/friction tag만 기록한 뒤 다시 실행한다.",
        "do_not_share": [
            ".env",
            "browser localStorage",
            "사용자 원문 문서",
            "raw AI reply",
            "completed pilot feedback raw text",
            "completed issue intake raw text",
            "API key 또는 secret",
        ],
    }
    payload["pilot_evidence_body_sha256"] = _pilot_evidence_body_sha256(payload)
    payload["artifact_chain"] = _pilot_evidence_artifact_chain(pilot_review, payload)
    payload["pilot_evidence_checks"] = _pilot_evidence_checks(payload)
    verify_pilot_evidence_payload(payload)
    return payload


def _pilot_learning_summary(
    outcome_tag: str,
    friction_tags: list[str] | None,
    missing_skill_tags: list[str] | None,
) -> dict[str, Any]:
    """Store only controlled pilot learning tags, never raw feedback text."""
    if outcome_tag not in OUTCOME_TAGS:
        raise PilotEvidenceError(f"unknown outcome tag: {outcome_tag}")
    return {
        "summary_kind": "controlled_tags_only",
        "outcome_tag": outcome_tag,
        "friction_tags": _normalize_tags(friction_tags, FRICTION_TAGS, default="none", label="friction"),
        "missing_skill_tags": _normalize_tags(
            missing_skill_tags,
            MISSING_SKILL_TAGS,
            default="none",
            label="missing skill",
        ),
        "raw_feedback_included": False,
        "raw_issue_included": False,
        "free_text_included": False,
    }


def _normalize_tags(values: list[str] | None, allowed: set[str], *, default: str, label: str) -> list[str]:
    """Normalize comma/repeated controlled tags into a deterministic unique list."""
    tags: list[str] = []
    for value in values or []:
        for part in str(value).split(","):
            tag = part.strip()
            if tag:
                tags.append(tag)
    if not tags:
        tags = [default]
    invalid = [tag for tag in tags if tag not in allowed]
    if invalid:
        raise PilotEvidenceError(f"unknown {label} tag: {', '.join(invalid)}")
    if len(tags) > 1 and default in tags:
        tags = [tag for tag in tags if tag != default]
    return list(dict.fromkeys(tags))


def _learning_summary_controlled(summary: dict[str, Any]) -> bool:
    """Check that the public learning summary contains only allowlisted tags."""
    return (
        summary.get("summary_kind") == "controlled_tags_only"
        and summary.get("outcome_tag") in OUTCOME_TAGS
        and isinstance(summary.get("friction_tags"), list)
        and all(tag in FRICTION_TAGS for tag in summary.get("friction_tags", []))
        and isinstance(summary.get("missing_skill_tags"), list)
        and all(tag in MISSING_SKILL_TAGS for tag in summary.get("missing_skill_tags", []))
    )


def _pilot_evidence_body_sha256(payload: dict[str, Any]) -> str:
    """pilot-evidence 검증 본문만 정규화해 sha256 해시를 계산한다."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"pilot_evidence_body_sha256", "artifact_chain", "pilot_evidence_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_private_sha256(
    direct_sha256: str | None,
    private_file: Path | None,
    label: str,
) -> str | None:
    """private 원문 파일은 경로나 내용을 저장하지 않고 sha256만 계산한다."""
    if direct_sha256 is not None and private_file is not None:
        raise PilotEvidenceError(f"{label}는 sha256 또는 private file 중 하나만 입력해야 합니다.")
    if private_file is None:
        return direct_sha256
    try:
        data = private_file.read_bytes()
    except OSError as exc:
        raise PilotEvidenceError(f"{label} private file을 읽을 수 없습니다.") from exc
    return hashlib.sha256(data).hexdigest()


def _resolve_evidence_private_workspace_files(
    *,
    private_workspace_dir: Path,
    feedback_private_sha256: str | None,
    feedback_private_file: Path | None,
    issue_intake_private_sha256: str | None,
    issue_intake_private_file: Path | None,
) -> tuple[Path, Path]:
    """Map the standard private workspace to pilot evidence files without leaking paths."""
    if any(
        value is not None
        for value in (
            feedback_private_sha256,
            feedback_private_file,
            issue_intake_private_sha256,
            issue_intake_private_file,
        )
    ):
        raise PilotEvidenceError("--private-workspace-dir cannot be combined with explicit feedback/issue inputs.")
    workspace = private_workspace_dir.resolve()
    return (
        _private_workspace_file(
            workspace,
            "pilot-feedback-private.md",
            "pilot feedback",
            ("Keep raw feedback here",),
        ),
        _private_workspace_file(
            workspace,
            "pilot-issue-intake-private.md",
            "issue intake",
            ("Keep raw issue intake here",),
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
        raise PilotEvidenceError(f"{label} private workspace file is missing: {filename}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PilotEvidenceError(f"{label} private workspace file cannot be read: {filename}") from exc
    if not text.strip():
        raise PilotEvidenceError(f"{label} private workspace file is empty: {filename}")
    if any(fragment in text for fragment in placeholder_fragments):
        raise PilotEvidenceError(f"{label} private workspace file still contains scaffold placeholder text: {filename}")
    return path


def _pilot_evidence_artifact_chain(pilot_review: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    """pilot-review 증거 체인에 pilot-evidence 판정서 해시를 덧붙인다."""
    source_chain = pilot_review.get("artifact_chain") if isinstance(pilot_review.get("artifact_chain"), list) else []
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
            "kind": "pilot_evidence_json",
            "file": PILOT_EVIDENCE_JSON_NAME,
            "sha256": str(payload.get("pilot_evidence_body_sha256") or ""),
        }
    )
    return chain


def _pilot_evidence_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """pilot-evidence 판정서가 원문 없이 공유 가능한지 평가한다."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    pilot_review = payload.get("pilot_review") if isinstance(payload.get("pilot_review"), dict) else {}
    dispatch_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    shared = payload.get("shared_evidence") if isinstance(payload.get("shared_evidence"), dict) else {}
    receipt = shared.get("receipt") if isinstance(shared.get("receipt"), dict) else {}
    diagnostics = shared.get("diagnostics") if isinstance(shared.get("diagnostics"), dict) else {}
    private_fingerprints = (
        payload.get("private_evidence_fingerprints")
        if isinstance(payload.get("private_evidence_fingerprints"), dict)
        else {}
    )
    learning_summary = (
        payload.get("pilot_learning_summary") if isinstance(payload.get("pilot_learning_summary"), dict) else {}
    )
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    artifact_chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    body_hash = payload.get("pilot_evidence_body_sha256")
    feedback_hash = private_fingerprints.get("feedback_form_sha256")
    issue_hash = private_fingerprints.get("issue_intake_sha256")
    chain_by_kind = {
        item.get("kind"): item
        for item in artifact_chain
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    return {
        "schema_version_present": payload.get("schema_version") == PILOT_EVIDENCE_SCHEMA_VERSION,
        "status_valid": payload.get("status") in {"awaiting_private_pilot_evidence", "pilot_evidence_ready"},
        "verdict_valid": payload.get("verdict") in {"NO_DECISION", "READY_FOR_DECISION"},
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "pilot_review_body_hash_present": _looks_like_sha256(pilot_review.get("body_sha256")),
        "pilot_review_verified_standalone": pilot_review.get("verified_standalone") is True,
        "receipt_safe": receipt.get("status") == "pass" and receipt.get("safe_to_share") is True,
        "receipt_body_hash_present": _looks_like_sha256(receipt.get("body_sha256")),
        "diagnostics_safe": diagnostics.get("status") == "pass" and diagnostics.get("safe_to_share") is True,
        "diagnostics_redaction_checks_true": diagnostics.get("redaction_checks_all_true") is True,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "raw_private_content_omitted": private_fingerprints.get("raw_private_content_included") is False,
        "private_hashes_are_sha256_or_missing": (feedback_hash is None or _looks_like_sha256(feedback_hash))
        and (issue_hash is None or _looks_like_sha256(issue_hash)),
        "decision_blocked_without_feedback_hash": payload.get("operator_decision") == "not_decided"
        or _looks_like_sha256(feedback_hash),
        "learning_summary_controlled_tags": _learning_summary_controlled(learning_summary),
        "learning_summary_no_free_text": learning_summary.get("free_text_included") is False
        and learning_summary.get("raw_feedback_included") is False
        and learning_summary.get("raw_issue_included") is False,
        "decision_blocked_without_learning_summary": payload.get("operator_decision") == "not_decided"
        or learning_summary.get("outcome_tag") != "not_collected",
        "decision_allowed_matches_status": payload.get("decision_allowed")
        is (payload.get("status") == "pilot_evidence_ready" and payload.get("verdict") == "READY_FOR_DECISION"),
        "no_success_rate_before_decision": metrics.get("success_rate") is None,
        "proof_claim_blocked": metrics.get("proof_claim_allowed") is False,
        "sale_ready_blocked": metrics.get("sale_ready") is False,
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
            "pilot_evidence_json",
        }.issubset(set(chain_by_kind)),
        "artifact_chain_hashes_present": bool(artifact_chain)
        and all(isinstance(item, dict) and _looks_like_sha256(item.get("sha256")) for item in artifact_chain),
        "artifact_chain_release_hash_matched": chain_by_kind.get("release_zip", {}).get("sha256")
        == release.get("archive_sha256"),
        "artifact_chain_pilot_review_hash_matched": chain_by_kind.get("pilot_review_json", {}).get("sha256")
        == pilot_review.get("body_sha256"),
        "artifact_chain_pilot_evidence_hash_matched": chain_by_kind.get("pilot_evidence_json", {}).get("sha256")
        == body_hash,
        "do_not_share_guardrails_present": ".env" in do_not_share
        and "raw AI reply" in do_not_share
        and "completed pilot feedback raw text" in do_not_share,
        "pilot_evidence_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "pilot_evidence_body_hash_matched": body_hash == _pilot_evidence_body_sha256(payload),
    }


def _verify_diagnostics_payload(payload: dict[str, Any]) -> None:
    """diagnostics JSON이 지원 요청에 공유 가능한 상태인지 확인한다."""
    if payload.get("schema_version") != "external_alpha_diagnostics_v0_1":
        raise PilotEvidenceError("diagnostics schema_version이 올바르지 않습니다.")
    if payload.get("status") != "pass":
        raise PilotEvidenceError(f"diagnostics status가 pass가 아닙니다: {payload.get('status')}")
    if payload.get("safe_to_share") is not True:
        raise PilotEvidenceError("diagnostics safe_to_share가 true가 아닙니다.")
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    for name in ["environment_variables_collected", "env_files_read", "secret_values_collected", "user_documents_collected"]:
        if privacy.get(name) is not False:
            raise PilotEvidenceError(f"diagnostics privacy 플래그가 안전하지 않습니다: {name}")
    redaction_checks = payload.get("redaction_checks") if isinstance(payload.get("redaction_checks"), dict) else {}
    if not redaction_checks or any(value is not True for value in redaction_checks.values()):
        raise PilotEvidenceError("diagnostics redaction_checks가 모두 true가 아닙니다.")
    support = payload.get("support_summary") if isinstance(payload.get("support_summary"), dict) else {}
    if support.get("status") != "pass" or support.get("safe_to_share") is not True:
        raise PilotEvidenceError("diagnostics support_summary가 공유 가능한 pass 상태가 아닙니다.")
    do_not_share = support.get("do_not_share") if isinstance(support.get("do_not_share"), list) else []
    if ".env" not in do_not_share or "raw AI reply" not in do_not_share:
        raise PilotEvidenceError("diagnostics support_summary 공유 금지 안내가 부족합니다.")
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    if str(ROOT) in serialized or (home and home in serialized):
        raise PilotEvidenceError("diagnostics에 로컬 절대경로가 포함되었습니다.")


def _pilot_evidence_markdown(payload: dict[str, Any]) -> str:
    """파일럿 증거 패킷을 사람이 읽을 수 있는 Markdown으로 만든다."""
    dispatch_policy = payload["dispatch_execution_policy"]
    learning_summary = payload["pilot_learning_summary"]
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    artifact_chain = "\n".join(
        f"- {item['kind']}: {item['file']} {item['sha256']}" for item in payload["artifact_chain"]
    )
    forbidden = "\n".join(f"- {item}" for item in payload["forbidden_claims"])
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    return f"""# Cambrian External Alpha Pilot Evidence

## Verdict

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- pilot-evidence body sha256: {payload["pilot_evidence_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- pilot-review: {payload["pilot_review"]["file"]}
- pilot-review body sha256: {payload["pilot_review"]["body_sha256"]}
- receipt: {payload["shared_evidence"]["receipt"]["file"]}
- diagnostics: {payload["shared_evidence"]["diagnostics"]["file"]}
- decision allowed: {payload["decision_allowed"]}
- operator decision: {payload["operator_decision"]}
- success rate: not collected
- proof claim allowed: {payload["metrics"]["proof_claim_allowed"]}
- sale ready: {payload["metrics"]["sale_ready"]}

## Checks

{checks}

## Private Evidence Fingerprints

- feedback form sha256 present: {_looks_like_sha256(payload["private_evidence_fingerprints"]["feedback_form_sha256"])}
- issue intake sha256 present: {_looks_like_sha256(payload["private_evidence_fingerprints"]["issue_intake_sha256"])}
- raw private content included: {payload["private_evidence_fingerprints"]["raw_private_content_included"]}

## Pilot Learning Summary

- summary kind: {learning_summary["summary_kind"]}
- outcome tag: {learning_summary["outcome_tag"]}
- friction tags: {", ".join(learning_summary["friction_tags"])}
- missing skill tags: {", ".join(learning_summary["missing_skill_tags"])}
- raw feedback included: {learning_summary["raw_feedback_included"]}
- raw issue included: {learning_summary["raw_issue_included"]}
- free text included: {learning_summary["free_text_included"]}

## Dispatch Execution Policy

- script sends to recipient: {dispatch_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {dispatch_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {dispatch_policy["manual_operator_dispatch_required"]}
- max recipients per record: {dispatch_policy["max_recipients_per_record"]}
- records private sha256 only: {dispatch_policy["records_private_sha256_only"]}
- raw private content included: {dispatch_policy["raw_private_content_included"]}
- cohort scaling allowed: {dispatch_policy["cohort_scaling_allowed"]}
- sent recorded by private hashes only: {dispatch_policy["sent_recorded_by_private_hashes_only"]}

## Artifact Chain

{artifact_chain}

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
        raise PilotEvidenceError(f"JSON 파일을 읽을 수 없습니다: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PilotEvidenceError(f"JSON 파싱 실패: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PilotEvidenceError(f"JSON 객체가 아닙니다: {path.name}")
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
        raise PilotEvidenceError(f"pilot-evidence 판정서에 공유하면 안 되는 경로 또는 값이 포함되었습니다: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
