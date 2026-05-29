"""evolution_review_decision_v0_1 파일을 사전 검증한다."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
EVOLUTION_REVIEW_DECISION_SCHEMA = ROOT / "schemas" / "evolution_review_decision_v0_1.schema.json"
REPORT_SCHEMA_VERSION = "0.1"
VALIDATOR_NAME = "evolution_review_decision_validator_v0_1"

logger = logging.getLogger(__name__)


def validate_evolution_review_decision(decision_path: Path) -> dict[str, Any]:
    """evolution review decision을 검증하고 JSON 직렬화 가능한 리포트를 반환한다."""
    resolved_decision_path = decision_path.resolve()
    report = _base_report(resolved_decision_path)

    try:
        decision = _read_json(resolved_decision_path)
        schema = _read_json(EVOLUTION_REVIEW_DECISION_SCHEMA)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("evolution review decision 검증 입력을 읽지 못했습니다.")
        report["status"] = "fail"
        report["errors"].append(_issue("read_error", str(exc)))
        return report

    if isinstance(decision, dict):
        source = decision.get("source_suggestion") if isinstance(decision.get("source_suggestion"), dict) else {}
        report["agent_id"] = str(source.get("agent_id") or "")
    else:
        report["errors"].append(_issue("decision_object", "decision은 JSON 객체여야 합니다."))

    _append_schema_errors(
        report=report,
        validator=Draft202012Validator(schema, format_checker=FormatChecker()),
        payload=decision,
    )

    if isinstance(decision, dict):
        _run_boundary_checks(report, decision)

    report["status"] = "fail" if report["errors"] else "pass"
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Validate an evolution_review_decision_v0_1 JSON file")
    parser.add_argument("decision", help="evolution review decision JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON 리포트를 출력한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    report = validate_evolution_review_decision(Path(args.decision))
    indent = 2 if args.pretty else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=indent) + "\n")
    return 0 if report["status"] == "pass" else 1


def _base_report(decision_path: Path) -> dict[str, Any]:
    """기본 리포트 구조를 만든다."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validator": VALIDATOR_NAME,
        "status": "fail",
        "input_path": str(decision_path),
        "agent_id": "",
        "checks": [],
        "errors": [],
    }


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _append_schema_errors(
    *,
    report: dict[str, Any],
    validator: Draft202012Validator,
    payload: Any,
) -> None:
    """JSON Schema 검증 오류를 리포트에 추가한다."""
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        dotted_path = ".".join(str(part) for part in error.path) or "$"
        report["errors"].append(_issue("decision_schema", f"{dotted_path}: {error.message}"))


def _run_boundary_checks(report: dict[str, Any], decision: dict[str, Any]) -> None:
    """리뷰 기록이 자동 적용처럼 오해될 수 있는 경계를 확인한다."""
    source_suggestion = decision.get("source_suggestion") if isinstance(decision.get("source_suggestion"), dict) else {}
    approval_gate = decision.get("approval_gate") if isinstance(decision.get("approval_gate"), dict) else {}
    proof_boundary = decision.get("proof_boundary") if isinstance(decision.get("proof_boundary"), dict) else {}
    privacy = decision.get("privacy") if isinstance(decision.get("privacy"), dict) else {}
    decisions = decision.get("decisions") if isinstance(decision.get("decisions"), list) else []
    next_step = decision.get("next_step") if isinstance(decision.get("next_step"), dict) else {}
    rollback = decision.get("rollback") if isinstance(decision.get("rollback"), dict) else {}
    recommendation_ids = (
        source_suggestion.get("recommendation_ids")
        if isinstance(source_suggestion.get("recommendation_ids"), list)
        else []
    )
    decision_recommendation_ids = [
        item.get("recommendation_id")
        for item in decisions
        if isinstance(item, dict)
    ]

    _check(
        report,
        "reviewed_not_applied",
        decision.get("review_status") == "reviewed_not_applied",
        "리뷰 기록은 적용 완료가 아니라 reviewed_not_applied 상태여야 한다.",
    )
    _check(
        report,
        "auto_apply_blocked",
        approval_gate.get("user_reviewed") is True
        and approval_gate.get("auto_apply") is False
        and approval_gate.get("auto_promote") is False
        and approval_gate.get("can_create_new_version") is False,
        "리뷰 기록은 자동 적용, 자동 승격, 자동 버전 생성을 허용하지 않아야 한다.",
    )
    _check(
        report,
        "source_suggestion_eligible_for_review",
        source_suggestion.get("source_receipt_eligible_for_suggestion") is True
        and source_suggestion.get("source_receipt_requires_user_approval") is True,
        "리뷰 기록은 eligible receipt에서 온 사용자 승인 필요 suggestion만 대상으로 해야 한다.",
    )
    _check(
        report,
        "decision_count_matches_suggestion",
        isinstance(source_suggestion.get("recommendation_count"), int)
        and len(decisions) == source_suggestion.get("recommendation_count")
        and len(recommendation_ids) == source_suggestion.get("recommendation_count"),
        "decision 개수는 source suggestion의 recommendation_count와 일치해야 한다.",
    )
    _check(
        report,
        "recommendation_decisions_complete",
        bool(recommendation_ids)
        and len(decision_recommendation_ids) == len(set(decision_recommendation_ids))
        and set(decision_recommendation_ids) == set(recommendation_ids),
        "source suggestion의 모든 recommendation_id에 정확히 하나의 decision이 있어야 한다.",
    )
    _check(
        report,
        "separate_apply_step_required",
        approval_gate.get("apply_requires_separate_step") is True
        and next_step.get("allowed") == "generate_candidate_pack_after_user_command"
        and next_step.get("blocked") == "automatic_pack_mutation",
        "pack 후보 생성은 별도 사용자 명령 뒤에만 허용되어야 한다.",
    )
    _check(
        report,
        "proof_claim_blocked",
        proof_boundary.get("uses_runtime_evidence") is False
        and proof_boundary.get("proof_claim_allowed") is False
        and proof_boundary.get("success_rate_claim_allowed") is False
        and proof_boundary.get("marketplace_sale_ready") is False,
        "리뷰 기록은 proof, 성공률, 판매 준비 상태를 주장하지 않아야 한다.",
    )
    _check(
        report,
        "privacy_uses_only_suggestion_metadata",
        privacy.get("stores_raw_inputs") is False
        and privacy.get("stores_raw_outputs") is False
        and privacy.get("stores_secrets") is False
        and privacy.get("uses_only_suggestion_metadata") is True,
        "리뷰 기록은 suggestion 메타데이터만 사용하고 원문과 secret을 저장하지 않아야 한다.",
    )
    _check(
        report,
        "decisions_present",
        bool(decisions)
        and all(isinstance(item, dict) and item.get("decision") in {"approved", "rejected", "deferred"} for item in decisions),
        "각 recommendation에는 approved, rejected, deferred 중 하나의 결정이 있어야 한다.",
    )
    _check(
        report,
        "reviewer_notes_present",
        bool(decisions)
        and all(
            isinstance(item, dict) and bool(str(item.get("reviewer_note") or "").strip())
            for item in decisions
        ),
        "각 recommendation decision에는 빈 문자열이 아닌 reviewer_note가 있어야 한다.",
    )
    _check(
        report,
        "rollback_required",
        rollback.get("required_before_apply") is True,
        "적용 전 rollback 기준이 필요하다.",
    )


def _check(report: dict[str, Any], name: str, passed: bool, message: str) -> None:
    """경계 검사 결과를 기록한다."""
    status = "pass" if passed else "fail"
    report["checks"].append({"name": name, "status": status, "message": message})
    if not passed:
        report["errors"].append(_issue(name, message))


def _issue(code: str, message: str) -> dict[str, str]:
    """리포트 issue 구조를 만든다."""
    return {"code": code, "message": message}


if __name__ == "__main__":
    raise SystemExit(main())
