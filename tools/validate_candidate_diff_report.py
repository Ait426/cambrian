"""candidate_diff_report_v0_1 파일을 사전 검증한다."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIFF_REPORT_SCHEMA = ROOT / "schemas" / "candidate_diff_report_v0_1.schema.json"
REPORT_SCHEMA_VERSION = "0.1"
VALIDATOR_NAME = "candidate_diff_report_validator_v0_1"

logger = logging.getLogger(__name__)


def validate_candidate_diff_report(report_path: Path) -> dict[str, Any]:
    """candidate diff report를 검증하고 JSON 직렬화 가능한 리포트를 반환한다."""
    resolved_report_path = report_path.resolve()
    report = _base_report(resolved_report_path)

    try:
        payload = _read_json(resolved_report_path)
        schema = _read_json(CANDIDATE_DIFF_REPORT_SCHEMA)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("candidate diff report 검증 입력을 읽지 못했습니다.")
        report["status"] = "fail"
        report["errors"].append(_issue("read_error", str(exc)))
        return report

    if isinstance(payload, dict):
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        report["agent_id"] = str(source.get("agent_id") or "")
    else:
        report["errors"].append(_issue("diff_report_object", "diff report는 JSON 객체여야 합니다."))

    _append_schema_errors(
        report=report,
        validator=Draft202012Validator(schema, format_checker=FormatChecker()),
        payload=payload,
    )

    if isinstance(payload, dict):
        _run_boundary_checks(report, payload)

    report["status"] = "fail" if report["errors"] else "pass"
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Validate a candidate_diff_report_v0_1 JSON file")
    parser.add_argument("report", help="candidate diff report JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON 리포트를 출력한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    report = validate_candidate_diff_report(Path(args.report))
    indent = 2 if args.pretty else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=indent) + "\n")
    return 0 if report["status"] == "pass" else 1


def _base_report(report_path: Path) -> dict[str, Any]:
    """기본 리포트 구조를 만든다."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validator": VALIDATOR_NAME,
        "status": "fail",
        "input_path": str(report_path),
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
        report["errors"].append(_issue("diff_report_schema", f"{dotted_path}: {error.message}"))


def _run_boundary_checks(report: dict[str, Any], payload: dict[str, Any]) -> None:
    """diff report가 자동 승격이나 proof처럼 오해될 수 있는 경계를 확인한다."""
    comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
    approval_gate = payload.get("approval_gate") if isinstance(payload.get("approval_gate"), dict) else {}
    proof_boundary = payload.get("proof_boundary") if isinstance(payload.get("proof_boundary"), dict) else {}
    unexpected_changes = payload.get("unexpected_changes") if isinstance(payload.get("unexpected_changes"), list) else []
    next_step = payload.get("next_step") if isinstance(payload.get("next_step"), dict) else {}

    _check(
        report,
        "review_pass_not_promoted",
        payload.get("diff_status") == "review_pass_not_promoted",
        "diff report는 review_pass_not_promoted 상태여야 한다.",
    )
    _check(
        report,
        "candidate_pack_valid",
        comparison.get("original_pack_valid") is True
        and comparison.get("candidate_pack_valid") is True
        and comparison.get("candidate_is_distinct") is True,
        "원본과 후보 pack은 모두 유효하고 서로 달라야 한다.",
    )
    _check(
        report,
        "only_approved_changes",
        comparison.get("only_approved_decisions_applied") is True
        and comparison.get("deferred_and_rejected_not_applied") is True
        and not unexpected_changes,
        "승인된 decision 범위 밖의 변경이 없어야 한다.",
    )
    _check(
        report,
        "auto_promotion_blocked",
        approval_gate.get("auto_promote") is False
        and approval_gate.get("candidate_review_required") is True
        and approval_gate.get("promotion_requires_separate_command") is True
        and next_step.get("blocked") == "automatic_candidate_promotion",
        "candidate 자동 승격은 차단되어야 한다.",
    )
    _check(
        report,
        "proof_claim_blocked",
        proof_boundary.get("uses_runtime_evidence") is False
        and proof_boundary.get("proof_claim_allowed") is False
        and proof_boundary.get("success_rate_claim_allowed") is False
        and proof_boundary.get("marketplace_sale_ready") is False,
        "diff report는 proof, 성공률, 판매 준비 상태를 주장하지 않아야 한다.",
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
