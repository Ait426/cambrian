"""외부 알파 파일럿 결정 이후 다음 운영 단계를 제한한다."""

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
from scripts.check_external_alpha_pilot_decision import (
    PILOT_DECISION_JSON_NAME,
    PILOT_DECISION_MD_NAME,
    check_pilot_decision,
    verify_pilot_decision_file,
)
from scripts.check_external_alpha_pilot_evidence import FRICTION_TAGS, MISSING_SKILL_TAGS, OPERATOR_DECISIONS, OUTCOME_TAGS
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR


PILOT_ITERATION_SCHEMA_VERSION = "external_alpha_pilot_iteration_v0_1"
PILOT_ITERATION_JSON_NAME = f"{RELEASE_SLUG}-pilot-iteration.json"
PILOT_ITERATION_MD_NAME = f"{RELEASE_SLUG}-pilot-iteration.md"

logger = logging.getLogger(__name__)


class PilotIterationError(Exception):
    """외부 알파 파일럿 반복 운영 판정 실패."""


def check_pilot_iteration(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    skip_build: bool = False,
    receipt_path: Path | None = None,
    diagnostics_path: Path | None = None,
    feedback_private_sha256: str | None = None,
    issue_intake_private_sha256: str | None = None,
    recipient_ack_private_sha256: str | None = None,
    recipient_private_sha256: str | None = None,
    operator_dispatch_note_private_sha256: str | None = None,
    sent_at_utc: str | None = None,
    builder_gold_path_share_receipt: Path | None = None,
    operator_decision: str = "not_decided",
    operator_note_private_sha256: str | None = None,
    outcome_tag: str = "not_collected",
    friction_tags: list[str] | None = None,
    missing_skill_tags: list[str] | None = None,
    private_workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """pilot-decision 이후 다음 운영 단계를 확장 없이 제한한다."""
    output_dir = output_dir.resolve()
    pilot_decision_result = check_pilot_decision(
        output_dir=output_dir,
        skip_build=skip_build,
        receipt_path=receipt_path,
        diagnostics_path=diagnostics_path,
        feedback_private_sha256=feedback_private_sha256,
        issue_intake_private_sha256=issue_intake_private_sha256,
        recipient_ack_private_sha256=recipient_ack_private_sha256,
        recipient_private_sha256=recipient_private_sha256,
        operator_dispatch_note_private_sha256=operator_dispatch_note_private_sha256,
        sent_at_utc=sent_at_utc,
        builder_gold_path_share_receipt=builder_gold_path_share_receipt,
        operator_decision=operator_decision,
        operator_note_private_sha256=operator_note_private_sha256,
        outcome_tag=outcome_tag,
        friction_tags=friction_tags,
        missing_skill_tags=missing_skill_tags,
        private_workspace_dir=private_workspace_dir,
    )
    pilot_decision_path = Path(str(pilot_decision_result["pilot_decision_json"]))
    pilot_decision = verify_pilot_decision_file(pilot_decision_path)
    payload = _pilot_iteration_payload(pilot_decision)

    json_path = output_dir / PILOT_ITERATION_JSON_NAME
    md_path = output_dir / PILOT_ITERATION_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_pilot_iteration_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "pilot_iteration_json": str(json_path),
        "pilot_iteration_md": str(md_path),
        "pilot_decision_json": str(pilot_decision_path),
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="외부 알파 파일럿 결정 이후 다음 운영 단계를 제한한다.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="릴리즈 산출물 폴더. 기본값은 dist")
    parser.add_argument("--skip-build", action="store_true", help="기존 ZIP, handoff, send-ready, pilot-ready를 재사용한다.")
    parser.add_argument("--receipt", default=None, help="공유 가능한 release receipt JSON 경로")
    parser.add_argument("--diagnostics", default=None, help="공유 가능한 diagnostics JSON 경로. 생략하면 새로 생성한다.")
    parser.add_argument("--feedback-private-sha256", default=None, help="완료된 pilot feedback 원문 대신 저장할 private sha256")
    parser.add_argument("--issue-intake-private-sha256", default=None, help="완료된 issue intake 원문 대신 저장할 private sha256")
    parser.add_argument("--recipient-ack-private-sha256", default=None, help="수령자 시작 확인 원문 대신 저장할 private sha256")
    parser.add_argument("--recipient-private-sha256", default=None, help="수신자 원문 식별자 대신 저장할 private sha256")
    parser.add_argument("--operator-dispatch-note-private-sha256", default=None, help="발송 운영 노트 원문 대신 저장할 private sha256")
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
    )
    parser.add_argument(
        "--missing-skill-tag",
        action="append",
        dest="missing_skill_tags",
        default=None,
    )
    parser.add_argument("--operator-note-private-sha256", default=None, help="운영 판단 노트 원문 대신 저장할 private sha256")
    parser.add_argument("--verify-pilot-iteration", default=None, help="pilot-iteration JSON만 단독 검증한다.")
    parser.add_argument(
        "--private-workspace-dir",
        default=None,
        help=(
            "Standard private workspace directory. Uses recipient, evidence, and decision private files "
            "after placeholders are replaced."
        ),
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_pilot_iteration:
        try:
            payload = verify_pilot_iteration_file(Path(args.verify_pilot_iteration))
        except Exception as exc:  # noqa: BLE001 - 운영 검증 실패 이유를 한 줄로 전달한다.
            logger.error("[FAIL] external alpha pilot-iteration verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha pilot-iteration verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["pilot_iteration_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = check_pilot_iteration(
            output_dir=Path(args.output_dir),
            skip_build=args.skip_build,
            receipt_path=Path(args.receipt) if args.receipt else None,
            diagnostics_path=Path(args.diagnostics) if args.diagnostics else None,
            feedback_private_sha256=args.feedback_private_sha256,
            issue_intake_private_sha256=args.issue_intake_private_sha256,
            recipient_ack_private_sha256=args.recipient_ack_private_sha256,
            recipient_private_sha256=args.recipient_private_sha256,
            operator_dispatch_note_private_sha256=args.operator_dispatch_note_private_sha256,
            sent_at_utc=args.sent_at_utc,
            builder_gold_path_share_receipt=Path(args.builder_gold_path_share_receipt)
            if args.builder_gold_path_share_receipt
            else None,
            operator_decision=args.operator_decision,
            operator_note_private_sha256=args.operator_note_private_sha256,
            outcome_tag=args.outcome_tag,
            friction_tags=args.friction_tags,
            missing_skill_tags=args.missing_skill_tags,
            private_workspace_dir=Path(args.private_workspace_dir) if args.private_workspace_dir else None,
        )
    except Exception as exc:  # noqa: BLE001 - 운영 게이트는 실패 조건을 사용자에게 직접 보여준다.
        logger.error("[FAIL] external alpha pilot-iteration: %s", exc)
        return 1

    logger.info("[PASS] external alpha pilot-iteration")
    logger.info("verdict          : %s", result["verdict"])
    logger.info("pilot_iteration_md: %s", result["pilot_iteration_md"])
    logger.info("zip              : %s", result["zip_file"])
    logger.info("sha256           : %s", result["archive_sha256"])
    return 0


def verify_pilot_iteration_file(path: Path) -> dict[str, Any]:
    """pilot-iteration JSON만 읽어 변조 여부와 공유 안전성을 검증한다."""
    payload = _read_json(path)
    verify_pilot_iteration_payload(payload)
    return payload


def verify_pilot_iteration_payload(payload: dict[str, Any]) -> None:
    """pilot-iteration JSON이 확장 금지와 다음 단계 제한을 지키는지 확인한다."""
    if payload.get("schema_version") != PILOT_ITERATION_SCHEMA_VERSION:
        raise PilotIterationError("pilot-iteration schema_version이 올바르지 않습니다.")
    if payload.get("status") not in {
        "iteration_blocked",
        "next_single_pilot_ready",
        "patch_required_before_next_pilot",
        "external_pilot_stopped",
    }:
        raise PilotIterationError(f"pilot-iteration status가 올바르지 않습니다: {payload.get('status')}")
    if payload.get("verdict") not in {"NO_ITERATION", "SEND_ONE_MORE", "PATCH_BEFORE_NEXT", "STOPPED_FOR_REDESIGN"}:
        raise PilotIterationError(f"pilot-iteration verdict가 올바르지 않습니다: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise PilotIterationError("pilot-iteration safe_to_share가 true가 아닙니다.")

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PilotIterationError("pilot-iteration checks가 모두 true가 아닙니다.")

    iteration_checks = (
        payload.get("pilot_iteration_checks") if isinstance(payload.get("pilot_iteration_checks"), dict) else {}
    )
    if not iteration_checks:
        raise PilotIterationError("pilot_iteration_checks가 없습니다.")
    if payload.get("pilot_iteration_body_sha256") != _pilot_iteration_body_sha256(payload):
        raise PilotIterationError("pilot-iteration 본문 해시가 일치하지 않습니다.")
    recalculated_checks = _pilot_iteration_checks(payload)
    if iteration_checks != recalculated_checks:
        raise PilotIterationError("pilot-iteration 안전 평가 결과가 현재 본문과 일치하지 않습니다.")
    failed_checks = [name for name, passed in recalculated_checks.items() if passed is not True]
    if failed_checks:
        raise PilotIterationError("pilot-iteration 안전 평가 실패: " + ", ".join(failed_checks))


def _pilot_iteration_payload(pilot_decision: dict[str, Any]) -> dict[str, Any]:
    """운영 결정에 맞는 다음 반복 계획을 만든다."""
    release = pilot_decision.get("release") if isinstance(pilot_decision.get("release"), dict) else {}
    decision = pilot_decision.get("decision") if isinstance(pilot_decision.get("decision"), dict) else {}
    decision_checks = (
        pilot_decision.get("pilot_decision_checks")
        if isinstance(pilot_decision.get("pilot_decision_checks"), dict)
        else {}
    )
    dispatch_policy = (
        pilot_decision.get("dispatch_execution_policy")
        if isinstance(pilot_decision.get("dispatch_execution_policy"), dict)
        else {}
    )
    learning_summary = (
        pilot_decision.get("pilot_learning_summary")
        if isinstance(pilot_decision.get("pilot_learning_summary"), dict)
        else {}
    )
    selected = decision.get("selected") if isinstance(decision.get("selected"), str) else None
    recorded = decision.get("recorded") is True and pilot_decision.get("status") == "pilot_decision_recorded"
    route = _iteration_route(selected, recorded)
    checks = {
        "pilot_decision_verified": bool(decision_checks) and all(value is True for value in decision_checks.values()),
        "pilot_decision_recorded_or_blocked": recorded or pilot_decision.get("status") == "decision_blocked",
        "route_matches_decision": route["status"] == _expected_status(selected, recorded),
        "continue_limited_to_one": selected != "continue" or route["max_next_participants"] == 1,
        "fix_blocks_next_send": selected != "fix_before_next" or route["max_next_participants"] == 0,
        "stop_blocks_next_send": selected != "stop_and_redesign" or route["max_next_participants"] == 0,
        "blocked_has_no_next_send": recorded or route["max_next_participants"] == 0,
        "scaling_blocked": route["scaling_allowed"] is False,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "public_claims_blocked": True,
        "raw_private_content_omitted": True,
        "pilot_learning_summary_carried": _learning_summary_controlled(learning_summary),
    }
    payload = {
        "schema_version": PILOT_ITERATION_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": route["status"],
        "verdict": route["verdict"],
        "safe_to_share": True,
        "release": {
            "version": release.get("version"),
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "pilot_decision": {
            "file": PILOT_DECISION_JSON_NAME,
            "markdown": PILOT_DECISION_MD_NAME,
            "body_sha256": pilot_decision.get("pilot_decision_body_sha256"),
            "verified_standalone": True,
            "verdict": pilot_decision.get("verdict"),
            "selected": selected,
            "recorded": recorded,
        },
        "dispatch_execution_policy": dispatch_policy,
        "pilot_learning_summary": learning_summary,
        "iteration_plan": route,
        "metrics": {
            "pilot_participants_completed": pilot_decision.get("metrics", {}).get("pilot_participants_completed"),
            "success_rate": None,
            "proof_claim_allowed": False,
            "sale_ready": False,
            "market_validated": False,
        },
        "publish_boundary": {
            "public_claim_allowed": False,
            "marketplace_listing_allowed": False,
            "proof_badge_allowed": False,
            "cohort_scaling_allowed": False,
        },
        "checks": checks,
        "operator_next_action": route["operator_next_action"],
        "do_not_share": [
            ".env",
            "browser localStorage",
            "사용자 원문 문서",
            "raw AI reply",
            "completed pilot feedback raw text",
            "completed issue intake raw text",
            "operator decision note raw text",
            "API key 또는 secret",
        ],
    }
    payload["pilot_iteration_body_sha256"] = _pilot_iteration_body_sha256(payload)
    payload["artifact_chain"] = _pilot_iteration_artifact_chain(pilot_decision, payload)
    payload["pilot_iteration_checks"] = _pilot_iteration_checks(payload)
    verify_pilot_iteration_payload(payload)
    return payload


def _iteration_route(selected: str | None, recorded: bool) -> dict[str, Any]:
    """결정값을 다음 반복 계획으로 변환한다."""
    if not recorded:
        return {
            "status": "iteration_blocked",
            "verdict": "NO_ITERATION",
            "max_next_participants": 0,
            "scaling_allowed": False,
            "required_before_next": [
                "pilot-decision recorded",
                "private feedback sha256",
                "operator decision note sha256",
            ],
            "operator_next_action": "pilot-decision을 먼저 기록한다.",
        }
    if selected == "continue":
        return {
            "status": "next_single_pilot_ready",
            "verdict": "SEND_ONE_MORE",
            "max_next_participants": 1,
            "scaling_allowed": False,
            "required_before_next": [
                "send exactly one next external pilot",
                "rerun receipt/diagnostics/evidence/decision chain after that pilot",
            ],
            "operator_next_action": "다음 외부 파일럿은 1명만 보내고 같은 증거 체인을 반복한다.",
        }
    if selected == "fix_before_next":
        return {
            "status": "patch_required_before_next_pilot",
            "verdict": "PATCH_BEFORE_NEXT",
            "max_next_participants": 0,
            "scaling_allowed": False,
            "required_before_next": [
                "patch release surface",
                "rerun verify_platform_alpha",
                "rerun send-ready through pilot-decision gates",
            ],
            "operator_next_action": "다음 사용자에게 보내기 전에 release surface를 수정하고 전체 게이트를 다시 실행한다.",
        }
    return {
        "status": "external_pilot_stopped",
        "verdict": "STOPPED_FOR_REDESIGN",
        "max_next_participants": 0,
        "scaling_allowed": False,
        "required_before_next": [
            "stop external sends",
            "redesign product boundary and message",
            "restart from send-ready only after redesign",
        ],
        "operator_next_action": "외부 파일럿을 멈추고 product boundary와 메시지를 재설계한다.",
    }


def _expected_status(selected: str | None, recorded: bool) -> str:
    """결정값에 맞는 status를 반환한다."""
    if not recorded:
        return "iteration_blocked"
    if selected == "continue":
        return "next_single_pilot_ready"
    if selected == "fix_before_next":
        return "patch_required_before_next_pilot"
    return "external_pilot_stopped"


def _pilot_iteration_body_sha256(payload: dict[str, Any]) -> str:
    """pilot-iteration 검증 본문만 정규화해 sha256 해시를 계산한다."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"pilot_iteration_body_sha256", "artifact_chain", "pilot_iteration_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pilot_iteration_artifact_chain(pilot_decision: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    """pilot-decision 증거 체인에 pilot-iteration 판정서 해시를 덧붙인다."""
    source_chain = pilot_decision.get("artifact_chain") if isinstance(pilot_decision.get("artifact_chain"), list) else []
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
            "kind": "pilot_iteration_json",
            "file": PILOT_ITERATION_JSON_NAME,
            "sha256": str(payload.get("pilot_iteration_body_sha256") or ""),
        }
    )
    return chain


def _pilot_iteration_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """pilot-iteration 판정서가 확장 금지와 공유 안전성을 지키는지 평가한다."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    decision = payload.get("pilot_decision") if isinstance(payload.get("pilot_decision"), dict) else {}
    dispatch_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    plan = payload.get("iteration_plan") if isinstance(payload.get("iteration_plan"), dict) else {}
    learning_summary = (
        payload.get("pilot_learning_summary") if isinstance(payload.get("pilot_learning_summary"), dict) else {}
    )
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    publish_boundary = payload.get("publish_boundary") if isinstance(payload.get("publish_boundary"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    artifact_chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    body_hash = payload.get("pilot_iteration_body_sha256")
    chain_by_kind = {
        item.get("kind"): item
        for item in artifact_chain
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    return {
        "schema_version_present": payload.get("schema_version") == PILOT_ITERATION_SCHEMA_VERSION,
        "status_valid": payload.get("status")
        in {
            "iteration_blocked",
            "next_single_pilot_ready",
            "patch_required_before_next_pilot",
            "external_pilot_stopped",
        },
        "verdict_valid": payload.get("verdict")
        in {"NO_ITERATION", "SEND_ONE_MORE", "PATCH_BEFORE_NEXT", "STOPPED_FOR_REDESIGN"},
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "pilot_decision_body_hash_present": _looks_like_sha256(decision.get("body_sha256")),
        "pilot_decision_verified_standalone": decision.get("verified_standalone") is True,
        "plan_matches_payload": plan.get("status") == payload.get("status") and plan.get("verdict") == payload.get("verdict"),
        "continue_limited_to_one": payload.get("verdict") != "SEND_ONE_MORE"
        or plan.get("max_next_participants") == 1,
        "non_continue_blocks_sending": payload.get("verdict") == "SEND_ONE_MORE"
        or plan.get("max_next_participants") == 0,
        "scaling_blocked": plan.get("scaling_allowed") is False,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "pilot_learning_summary_carried": _learning_summary_controlled(learning_summary),
        "no_success_rate_claim": metrics.get("success_rate") is None,
        "proof_claim_blocked": metrics.get("proof_claim_allowed") is False,
        "sale_ready_blocked": metrics.get("sale_ready") is False,
        "market_validated_blocked": metrics.get("market_validated") is False,
        "public_claims_blocked": publish_boundary.get("public_claim_allowed") is False
        and publish_boundary.get("marketplace_listing_allowed") is False
        and publish_boundary.get("proof_badge_allowed") is False
        and publish_boundary.get("cohort_scaling_allowed") is False,
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
            "pilot_decision_json",
            "pilot_iteration_json",
        }.issubset(set(chain_by_kind)),
        "artifact_chain_hashes_present": bool(artifact_chain)
        and all(isinstance(item, dict) and _looks_like_sha256(item.get("sha256")) for item in artifact_chain),
        "artifact_chain_release_hash_matched": chain_by_kind.get("release_zip", {}).get("sha256")
        == release.get("archive_sha256"),
        "artifact_chain_pilot_decision_hash_matched": chain_by_kind.get("pilot_decision_json", {}).get("sha256")
        == decision.get("body_sha256"),
        "artifact_chain_pilot_iteration_hash_matched": chain_by_kind.get("pilot_iteration_json", {}).get("sha256")
        == body_hash,
        "do_not_share_guardrails_present": ".env" in do_not_share
        and "raw AI reply" in do_not_share
        and "operator decision note raw text" in do_not_share,
        "pilot_iteration_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "pilot_iteration_body_hash_matched": body_hash == _pilot_iteration_body_sha256(payload),
    }


def _learning_summary_controlled(summary: dict[str, Any]) -> bool:
    """Check that pilot iteration carries only controlled public learning tags."""
    return (
        summary.get("summary_kind") == "controlled_tags_only"
        and summary.get("outcome_tag") in OUTCOME_TAGS
        and isinstance(summary.get("friction_tags"), list)
        and all(tag in FRICTION_TAGS for tag in summary.get("friction_tags", []))
        and isinstance(summary.get("missing_skill_tags"), list)
        and all(tag in MISSING_SKILL_TAGS for tag in summary.get("missing_skill_tags", []))
        and summary.get("free_text_included") is False
        and summary.get("raw_feedback_included") is False
        and summary.get("raw_issue_included") is False
    )


def _pilot_iteration_markdown(payload: dict[str, Any]) -> str:
    """파일럿 반복 운영 판정서를 사람이 읽을 수 있는 Markdown으로 만든다."""
    dispatch_policy = payload["dispatch_execution_policy"]
    learning_summary = payload["pilot_learning_summary"]
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    artifact_chain = "\n".join(
        f"- {item['kind']}: {item['file']} {item['sha256']}" for item in payload["artifact_chain"]
    )
    required = "\n".join(f"- {item}" for item in payload["iteration_plan"]["required_before_next"])
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    return f"""# Cambrian External Alpha Pilot Iteration

## Verdict

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- pilot-iteration body sha256: {payload["pilot_iteration_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- pilot-decision: {payload["pilot_decision"]["file"]}
- pilot-decision body sha256: {payload["pilot_decision"]["body_sha256"]}
- selected decision: {payload["pilot_decision"]["selected"]}
- max next participants: {payload["iteration_plan"]["max_next_participants"]}
- scaling allowed: {payload["iteration_plan"]["scaling_allowed"]}
- success rate: not collected
- proof claim allowed: {payload["metrics"]["proof_claim_allowed"]}
- sale ready: {payload["metrics"]["sale_ready"]}

## Checks

{checks}

## Required Before Next

{required}

## Artifact Chain

{artifact_chain}

## Publish Boundary

- public claim allowed: {payload["publish_boundary"]["public_claim_allowed"]}
- marketplace listing allowed: {payload["publish_boundary"]["marketplace_listing_allowed"]}
- proof badge allowed: {payload["publish_boundary"]["proof_badge_allowed"]}
- cohort scaling allowed: {payload["publish_boundary"]["cohort_scaling_allowed"]}

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
        raise PilotIterationError(f"JSON 파일을 읽을 수 없습니다: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PilotIterationError(f"JSON 파싱 실패: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PilotIterationError(f"JSON 객체가 아닙니다: {path.name}")
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
        raise PilotIterationError(f"pilot-iteration 판정서에 공유하면 안 되는 경로 또는 값이 포함되었습니다: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
