"""candidate promotion record를 사전 검증한다."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_PROMOTION_RECORD_SCHEMA = ROOT / "schemas" / "candidate_promotion_record_v0_1.schema.json"
REPORT_SCHEMA_VERSION = "0.1"
VALIDATOR_NAME = "candidate_promotion_record_validator_v0_1"

logger = logging.getLogger(__name__)


def validate_candidate_promotion_record(record_path: Path) -> dict[str, Any]:
    """candidate promotion record를 검증하고 JSON 직렬화 가능한 리포트를 반환한다."""
    resolved_record_path = record_path.resolve()
    report = _base_report(resolved_record_path)

    try:
        payload = _read_json(resolved_record_path)
        schema = _read_json(CANDIDATE_PROMOTION_RECORD_SCHEMA)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("candidate promotion record 검증 입력을 읽지 못했습니다.")
        report["status"] = "fail"
        report["errors"].append(_issue("read_error", str(exc)))
        return report

    if isinstance(payload, dict):
        report["agent_id"] = str(payload.get("agent_id") or "")
    else:
        report["errors"].append(_issue("promotion_record_object", "promotion record는 JSON 객체여야 합니다."))

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
    parser = argparse.ArgumentParser(description="Validate a candidate_promotion_record_v0_1 JSON file")
    parser.add_argument("record", help="candidate promotion record JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON 리포트를 출력한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    report = validate_candidate_promotion_record(Path(args.record))
    indent = 2 if args.pretty else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=indent) + "\n")
    return 0 if report["status"] == "pass" else 1


def _base_report(record_path: Path) -> dict[str, Any]:
    """기본 리포트 구조를 만든다."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validator": VALIDATOR_NAME,
        "status": "fail",
        "input_path": str(record_path),
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
        report["errors"].append(_issue("promotion_record_schema", f"{dotted_path}: {error.message}"))


def _run_boundary_checks(report: dict[str, Any], payload: dict[str, Any]) -> None:
    """승격 기록이 자동 승격이나 proof처럼 오해될 수 있는 경계를 확인한다."""
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    gate = payload.get("gate") if isinstance(payload.get("gate"), dict) else {}
    proof_boundary = payload.get("proof_boundary") if isinstance(payload.get("proof_boundary"), dict) else {}
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), dict) else {}

    _check(
        report,
        "promoted_private_version",
        payload.get("promotion_status") == "promoted_private_version"
        and source.get("candidate_diff_status") == "review_pass_not_promoted",
        "승격 기록은 검토 통과 candidate를 private version으로 승격한 상태여야 한다.",
    )
    _check(
        report,
        "source_hashes_present",
        _looks_like_sha256(source.get("original_pack_hash"))
        and _looks_like_sha256(source.get("candidate_pack_hash"))
        and _looks_like_sha256(source.get("diff_report_hash"))
        and _looks_like_sha256(source.get("promoted_pack_hash"))
        and source.get("candidate_pack_hash") != source.get("promoted_pack_hash"),
        "원본, candidate, diff report, promoted pack 해시가 모두 있고 candidate와 promoted pack은 구분되어야 한다.",
    )
    _check(
        report,
        "manual_promotion_gate",
        gate.get("user_command_required") is True
        and gate.get("auto_promote") is False
        and gate.get("source_diff_report_required") is True
        and gate.get("output_overwrite_blocked") is True,
        "승격은 사용자 명령과 diff report를 요구하고 자동 승격과 덮어쓰기를 막아야 한다.",
    )
    _check(
        report,
        "proof_claim_blocked",
        proof_boundary.get("uses_runtime_evidence") is False
        and proof_boundary.get("proof_claim_allowed") is False
        and proof_boundary.get("success_rate_claim_allowed") is False
        and proof_boundary.get("marketplace_sale_ready") is False,
        "승격 기록은 proof, 성공률, 판매 준비 상태를 주장하지 않아야 한다.",
    )
    _check(
        report,
        "candidate_metadata_removed",
        outputs.get("candidate_metadata_removed") is True
        and outputs.get("promotion_metadata_kind") == "promoted_agent_pack_metadata_v0_1"
        and outputs.get("private_visibility") is True,
        "promoted pack은 candidate_metadata 대신 promotion_metadata를 사용하고 private 상태여야 한다.",
    )


def _check(report: dict[str, Any], name: str, passed: bool, message: str) -> None:
    """경계 점검 결과를 기록한다."""
    status = "pass" if passed else "fail"
    report["checks"].append({"name": name, "status": status, "message": message})
    if not passed:
        report["errors"].append(_issue(name, message))


def _looks_like_sha256(value: Any) -> bool:
    """sha256 해시 문자열 형식인지 확인한다."""
    if not isinstance(value, str):
        return False
    prefix = "sha256:"
    digest = value.removeprefix(prefix)
    return value.startswith(prefix) and len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


def _issue(code: str, message: str) -> dict[str, str]:
    """리포트 issue 구조를 만든다."""
    return {"code": code, "message": message}


if __name__ == "__main__":
    raise SystemExit(main())
