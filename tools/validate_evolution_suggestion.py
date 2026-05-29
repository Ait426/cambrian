"""evolution_suggestion_v0_1 파일을 사전 검증한다."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
EVOLUTION_SUGGESTION_SCHEMA = ROOT / "schemas" / "evolution_suggestion_v0_1.schema.json"
REPORT_SCHEMA_VERSION = "0.1"
VALIDATOR_NAME = "evolution_suggestion_validator_v0_1"

logger = logging.getLogger(__name__)


def validate_evolution_suggestion(suggestion_path: Path) -> dict[str, Any]:
    """evolution suggestion을 검증하고 JSON 직렬화 가능한 리포트를 반환한다."""
    resolved_suggestion_path = suggestion_path.resolve()
    report = _base_report(resolved_suggestion_path)

    try:
        suggestion = _read_json(resolved_suggestion_path)
        schema = _read_json(EVOLUTION_SUGGESTION_SCHEMA)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("evolution suggestion 검증 입력을 읽지 못했습니다.")
        report["status"] = "fail"
        report["errors"].append(_issue("read_error", str(exc)))
        return report

    if isinstance(suggestion, dict):
        source_agent = suggestion.get("source_agent") if isinstance(suggestion.get("source_agent"), dict) else {}
        report["agent_id"] = str(source_agent.get("agent_id") or "")
    else:
        report["errors"].append(_issue("suggestion_object", "suggestion은 JSON 객체여야 합니다."))

    _append_schema_errors(
        report=report,
        validator=Draft202012Validator(schema, format_checker=FormatChecker()),
        payload=suggestion,
    )

    if isinstance(suggestion, dict):
        _run_boundary_checks(report, suggestion)

    report["status"] = "fail" if report["errors"] else "pass"
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Validate an evolution_suggestion_v0_1 JSON file")
    parser.add_argument("suggestion", help="evolution suggestion JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON 리포트를 출력한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    report = validate_evolution_suggestion(Path(args.suggestion))
    indent = 2 if args.pretty else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=indent) + "\n")
    return 0 if report["status"] == "pass" else 1


def _base_report(suggestion_path: Path) -> dict[str, Any]:
    """기본 리포트 구조를 만든다."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validator": VALIDATOR_NAME,
        "status": "fail",
        "input_path": str(suggestion_path),
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
        report["errors"].append(_issue("suggestion_schema", f"{dotted_path}: {error.message}"))


def _run_boundary_checks(report: dict[str, Any], suggestion: dict[str, Any]) -> None:
    """진화 제안이 자동 적용이나 proof처럼 오해될 수 있는 경계를 확인한다."""
    approval_gate = suggestion.get("approval_gate") if isinstance(suggestion.get("approval_gate"), dict) else {}
    proof_boundary = suggestion.get("proof_boundary") if isinstance(suggestion.get("proof_boundary"), dict) else {}
    privacy = suggestion.get("privacy") if isinstance(suggestion.get("privacy"), dict) else {}
    rollback = suggestion.get("rollback") if isinstance(suggestion.get("rollback"), dict) else {}
    source_receipt = suggestion.get("source_receipt") if isinstance(suggestion.get("source_receipt"), dict) else {}
    recommendations = suggestion.get("recommendations") if isinstance(suggestion.get("recommendations"), list) else []

    _check(
        report,
        "draft_requires_user_approval",
        suggestion.get("proposal_status") == "draft_requires_user_approval"
        and approval_gate.get("requires_user_approval") is True,
        "진화 제안은 사용자 승인이 필요한 draft여야 한다.",
    )
    _check(
        report,
        "auto_apply_blocked",
        approval_gate.get("auto_apply") is False
        and approval_gate.get("auto_promote") is False
        and approval_gate.get("can_create_new_version") is False,
        "진화 제안은 자동 적용, 자동 승격, 자동 버전 생성을 허용하지 않아야 한다.",
    )
    _check(
        report,
        "source_receipt_eligible_for_suggestion",
        source_receipt.get("eligible_for_suggestion") is True
        and source_receipt.get("requires_user_approval") is True,
        "진화 제안은 eligible_for_suggestion receipt에서만 만들고 사용자 승인을 요구해야 한다.",
    )
    _check(
        report,
        "proof_claim_blocked",
        proof_boundary.get("uses_runtime_evidence") is False
        and proof_boundary.get("proof_claim_allowed") is False
        and proof_boundary.get("success_rate_claim_allowed") is False
        and proof_boundary.get("marketplace_sale_ready") is False,
        "진화 제안은 proof, 성공률, 판매 준비 상태를 주장하지 않아야 한다.",
    )
    _check(
        report,
        "privacy_uses_only_metadata",
        privacy.get("stores_raw_inputs") is False
        and privacy.get("stores_raw_outputs") is False
        and privacy.get("stores_secrets") is False
        and privacy.get("uses_only_receipt_metadata") is True,
        "진화 제안은 receipt 메타데이터만 사용하고 원문과 secret을 저장하지 않아야 한다.",
    )
    _check(
        report,
        "recommendations_are_suggested_only",
        bool(recommendations)
        and all(isinstance(item, dict) and item.get("status") == "suggested" for item in recommendations),
        "recommendations는 suggested 상태여야 한다.",
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
