"""승격된 agent pack과 candidate promotion record의 연결을 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_agent_pack import validate_agent_pack
from tools.validate_candidate_promotion_record import validate_candidate_promotion_record


REPORT_SCHEMA_VERSION = "0.1"
VALIDATOR_NAME = "promotion_audit_link_verifier_v0_1"
PROMOTER_NAME = "tools/promote_candidate_pack.py"
PROMOTION_STATUS = "promoted_private_version"
PROMOTION_METADATA_KIND = "promoted_agent_pack_metadata_v0_1"

logger = logging.getLogger(__name__)


def verify_promotion_audit_link(promoted_pack_path: Path, promotion_record_path: Path) -> dict[str, Any]:
    """promoted pack과 promotion record가 같은 승격 흐름을 가리키는지 검증한다."""
    resolved_pack_path = promoted_pack_path.resolve()
    resolved_record_path = promotion_record_path.resolve()
    report = _base_report(resolved_pack_path, resolved_record_path)

    pack_validation = validate_agent_pack(resolved_pack_path)
    record_validation = validate_candidate_promotion_record(resolved_record_path)
    report["validation_reports"] = {
        "promoted_pack_status": pack_validation.get("status", "fail"),
        "promotion_record_status": record_validation.get("status", "fail"),
    }
    _check(
        report,
        "promoted_pack_preflight_passed",
        pack_validation.get("status") == "pass",
        "promoted pack은 agent_pack_preflight_v0_1 검증을 통과해야 한다.",
    )
    _check(
        report,
        "promotion_record_validator_passed",
        record_validation.get("status") == "pass",
        "candidate promotion record는 candidate_promotion_record_validator_v0_1 검증을 통과해야 한다.",
    )

    try:
        promoted = _read_json(resolved_pack_path)
        record = _read_json(resolved_record_path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("promotion audit link 검증 입력을 읽지 못했습니다.")
        report["errors"].append(_issue("read_error", str(exc)))
        report["status"] = "fail"
        return report

    if not isinstance(promoted, dict):
        report["errors"].append(_issue("promoted_pack_object", "promoted pack은 JSON 객체여야 한다."))
        report["status"] = "fail"
        return report
    if not isinstance(record, dict):
        report["errors"].append(_issue("promotion_record_object", "promotion record는 JSON 객체여야 한다."))
        report["status"] = "fail"
        return report

    _run_link_checks(report, promoted, record)
    report["status"] = "fail" if report["errors"] else "pass"
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Verify that a promoted pack matches a candidate promotion record")
    parser.add_argument("promoted_pack", help="promoted .agent-pack.json 파일 경로")
    parser.add_argument("promotion_record", help="candidate promotion record JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON 리포트를 출력한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    report = verify_promotion_audit_link(Path(args.promoted_pack), Path(args.promotion_record))
    indent = 2 if args.pretty else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=indent) + "\n")
    return 0 if report["status"] == "pass" else 1


def _base_report(promoted_pack_path: Path, promotion_record_path: Path) -> dict[str, Any]:
    """기본 리포트 구조를 만든다."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validator": VALIDATOR_NAME,
        "status": "fail",
        "input_paths": {
            "promoted_pack": str(promoted_pack_path),
            "promotion_record": str(promotion_record_path),
        },
        "agent_id": "",
        "source": {},
        "validation_reports": {},
        "checks": [],
        "errors": [],
    }


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _run_link_checks(report: dict[str, Any], promoted: dict[str, Any], record: dict[str, Any]) -> None:
    """승격 감사 기록과 promoted pack의 핵심 연결값을 비교한다."""
    files = promoted.get("files") if isinstance(promoted.get("files"), dict) else {}
    agent = files.get("agent.json") if isinstance(files.get("agent.json"), dict) else {}
    manifest = files.get("manifest.json") if isinstance(files.get("manifest.json"), dict) else {}
    marketplace = manifest.get("marketplace") if isinstance(manifest.get("marketplace"), dict) else {}
    promotion_metadata = (
        promoted.get("promotion_metadata") if isinstance(promoted.get("promotion_metadata"), dict) else {}
    )
    source = record.get("source") if isinstance(record.get("source"), dict) else {}

    pack_agent_id = str(agent.get("agent_id") or "")
    record_agent_id = str(record.get("agent_id") or "")
    report["agent_id"] = pack_agent_id or record_agent_id
    report["source"] = {
        "candidate_pack_hash": source.get("candidate_pack_hash", ""),
        "diff_report_hash": source.get("diff_report_hash", ""),
        "promoted_pack_hash": source.get("promoted_pack_hash", ""),
        "promotion_metadata_candidate_hash": promotion_metadata.get("promoted_from_candidate_hash", ""),
        "promotion_metadata_diff_hash": promotion_metadata.get("diff_report_hash", ""),
    }

    _check(
        report,
        "promoted_pack_generated_by_promoter",
        promoted.get("generated_by") == PROMOTER_NAME,
        "promoted pack은 promote_candidate_pack.py가 생성한 산출물이어야 한다.",
    )
    _check(
        report,
        "promotion_record_generated_by_promoter",
        record.get("generated_by") == PROMOTER_NAME,
        "promotion record는 promote_candidate_pack.py가 생성한 산출물이어야 한다.",
    )
    _check(
        report,
        "promotion_metadata_kind",
        promotion_metadata.get("metadata_kind") == PROMOTION_METADATA_KIND,
        "promoted pack은 promoted_agent_pack_metadata_v0_1 메타데이터를 포함해야 한다.",
    )
    _check(
        report,
        "candidate_metadata_removed",
        "candidate_metadata" not in promoted,
        "promoted pack은 candidate_metadata를 직접 포함하지 않아야 한다.",
    )
    _check(
        report,
        "agent_id_matches_record",
        bool(pack_agent_id) and pack_agent_id == record_agent_id,
        "promoted pack의 agent_id와 promotion record의 agent_id가 일치해야 한다.",
    )
    _check(
        report,
        "promoted_pack_hash_matches_record",
        _hash_payload(promoted) == source.get("promoted_pack_hash"),
        "promotion record의 promoted_pack_hash가 현재 promoted pack 해시와 일치해야 한다.",
    )
    _check(
        report,
        "diff_report_hash_matches_record",
        promotion_metadata.get("diff_report_hash") == source.get("diff_report_hash"),
        "promotion_metadata.diff_report_hash와 promotion record의 diff_report_hash가 일치해야 한다.",
    )
    _check(
        report,
        "candidate_pack_hash_matches_record",
        promotion_metadata.get("promoted_from_candidate_hash") == source.get("candidate_pack_hash"),
        "promotion_metadata.promoted_from_candidate_hash와 promotion record의 candidate_pack_hash가 일치해야 한다.",
    )
    _check(
        report,
        "promotion_status_matches",
        promotion_metadata.get("promotion_status") == PROMOTION_STATUS
        and record.get("promotion_status") == PROMOTION_STATUS,
        "promoted pack과 promotion record는 promoted_private_version 상태여야 한다.",
    )
    _check(
        report,
        "promotion_auto_boundary_blocked",
        promotion_metadata.get("auto_promote") is False
        and promotion_metadata.get("proof_claim_allowed") is False
        and promotion_metadata.get("marketplace_sale_ready") is False,
        "promoted pack은 자동 승격, proof 주장, 판매 준비 상태를 모두 차단해야 한다.",
    )
    _check(
        report,
        "manifest_private_boundary",
        manifest.get("evidence_status") == "no_runtime_evidence"
        and marketplace.get("sale_ready") is False
        and marketplace.get("proof_claim_allowed") is False,
        "manifest는 no_runtime_evidence와 판매/proof 차단 경계를 유지해야 한다.",
    )


def _check(report: dict[str, Any], name: str, passed: bool, message: str) -> None:
    """개별 검증 결과를 리포트에 추가한다."""
    status = "pass" if passed else "fail"
    report["checks"].append({"name": name, "status": status, "message": message})
    if not passed:
        report["errors"].append(_issue(name, message))


def _hash_payload(payload: Any) -> str:
    """정렬된 JSON payload의 sha256 해시를 만든다."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _issue(code: str, message: str) -> dict[str, str]:
    """리포트 issue 구조를 만든다."""
    return {"code": code, "message": message}


if __name__ == "__main__":
    raise SystemExit(main())
