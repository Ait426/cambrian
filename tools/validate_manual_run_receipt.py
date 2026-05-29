"""manual_run_receipt_v0_1 파일을 사전 검증한다."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
MANUAL_RUN_RECEIPT_SCHEMA = ROOT / "schemas" / "manual_run_receipt_v0_1.schema.json"
REPORT_SCHEMA_VERSION = "0.1"
VALIDATOR_NAME = "manual_run_receipt_validator_v0_1"

logger = logging.getLogger(__name__)


def validate_manual_run_receipt(receipt_path: Path) -> dict[str, Any]:
    """manual run receipt를 검증하고 JSON 직렬화 가능한 리포트를 반환한다."""
    resolved_receipt_path = receipt_path.resolve()
    report = _base_report(resolved_receipt_path)

    try:
        receipt = _read_json(resolved_receipt_path)
        schema = _read_json(MANUAL_RUN_RECEIPT_SCHEMA)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("manual run receipt 검증 입력을 읽지 못했습니다.")
        report["status"] = "fail"
        report["errors"].append(_issue("read_error", str(exc)))
        return report

    if isinstance(receipt, dict):
        report["agent_id"] = str(receipt.get("agent_id") or "")
    else:
        report["errors"].append(_issue("receipt_object", "receipt는 JSON 객체여야 합니다."))

    _append_schema_errors(
        report=report,
        validator=Draft202012Validator(schema, format_checker=FormatChecker()),
        payload=receipt,
    )

    if isinstance(receipt, dict):
        _run_boundary_checks(report, receipt)

    report["status"] = "fail" if report["errors"] else "pass"
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Validate a manual_run_receipt_v0_1 JSON file")
    parser.add_argument("receipt", help="manual run receipt JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON 리포트를 출력한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    report = validate_manual_run_receipt(Path(args.receipt))
    indent = 2 if args.pretty else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=indent) + "\n")
    return 0 if report["status"] == "pass" else 1


def _base_report(receipt_path: Path) -> dict[str, Any]:
    """기본 리포트 구조를 만든다."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validator": VALIDATOR_NAME,
        "status": "fail",
        "input_path": str(receipt_path),
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
        report["errors"].append(_issue("receipt_schema", f"{dotted_path}: {error.message}"))


def _run_boundary_checks(report: dict[str, Any], receipt: dict[str, Any]) -> None:
    """receipt가 proof처럼 오해될 수 있는 경계를 추가 확인한다."""
    source_bundle = receipt.get("source_bundle") if isinstance(receipt.get("source_bundle"), dict) else {}
    privacy = receipt.get("privacy") if isinstance(receipt.get("privacy"), dict) else {}
    proof_boundary = receipt.get("proof_boundary") if isinstance(receipt.get("proof_boundary"), dict) else {}
    evolution_signal = receipt.get("evolution_signal") if isinstance(receipt.get("evolution_signal"), dict) else {}
    manual_checks = receipt.get("manual_checks") if isinstance(receipt.get("manual_checks"), list) else []

    _check(
        report,
        "manual_receipt_kind",
        receipt.get("receipt_kind") == "manual_run_receipt_v0_1"
        and receipt.get("runner_mode") == "manual_no_api",
        "receipt는 manual_run_receipt_v0_1이며 manual_no_api 모드여야 한다.",
    )
    _check(
        report,
        "manual_review_only",
        receipt.get("run_status") == "manual_review_only",
        "receipt는 자동 proof가 아니라 manual_review_only 상태여야 한다.",
    )
    _check(
        report,
        "source_bundle_not_sale_ready",
        source_bundle.get("evidence_status") == "no_runtime_evidence"
        and source_bundle.get("preflight_status") == "pass"
        and source_bundle.get("marketplace_review_status") == "not_ready",
        "source_bundle은 no_runtime_evidence, pass preflight, not_ready marketplace 상태여야 한다.",
    )
    _check(
        report,
        "privacy_keeps_raw_data_out",
        privacy.get("stores_raw_inputs") is False
        and privacy.get("stores_raw_outputs") is False
        and privacy.get("stores_secrets") is False
        and privacy.get("api_key_collected") is False,
        "receipt는 원문 입력, 원문 결과, secret, API 키를 저장하지 않아야 한다.",
    )
    _check(
        report,
        "proof_claim_blocked",
        proof_boundary.get("evidence_status") == "no_runtime_evidence"
        and proof_boundary.get("proof_claim_allowed") is False
        and proof_boundary.get("success_rate_claim_allowed") is False
        and proof_boundary.get("marketplace_sale_ready") is False,
        "receipt는 proof, 성공률, 판매 준비 상태를 주장하지 않아야 한다.",
    )
    _check(
        report,
        "manual_checks_require_user_review",
        all(
            isinstance(item, dict) and item.get("status") == "user_review_required"
            for item in manual_checks
        ),
        "manual_checks는 모두 user_review_required 상태여야 한다.",
    )
    _check(
        report,
        "evolution_requires_user_approval",
        evolution_signal.get("source") == "manual_review_receipt"
        and evolution_signal.get("requires_user_approval") is True,
        "evolution_signal은 사용자 승인 후에만 진화 제안으로 쓰여야 한다.",
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
