"""플랫폼-first .agent-pack.json 번들을 사전 검증한다."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
AGENT_CONTRACT_SCHEMA = ROOT / "schemas" / "agent_contract_v0_1.schema.json"
AGENT_PACK_BUNDLE_SCHEMA = ROOT / "schemas" / "agent_pack_bundle_v0_1.schema.json"
REPORT_SCHEMA_VERSION = "0.1"
VALIDATOR_NAME = "agent_pack_preflight_v0_1"

logger = logging.getLogger(__name__)


def validate_agent_pack(pack_path: Path) -> dict[str, Any]:
    """agent pack bundle을 검증하고 JSON 직렬화 가능한 리포트를 반환한다."""
    resolved_pack_path = pack_path.resolve()
    report = _base_report(resolved_pack_path)

    try:
        bundle = _read_json(resolved_pack_path)
        bundle_schema = _read_json(AGENT_PACK_BUNDLE_SCHEMA)
        agent_schema = _read_json(AGENT_CONTRACT_SCHEMA)
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("agent pack 검증 입력을 읽지 못했습니다.")
        report["status"] = "fail"
        report["errors"].append(_issue("read_error", str(exc)))
        return report

    required_preflight_checks = _required_preflight_checks(bundle_schema)
    if not required_preflight_checks:
        report["errors"].append(
            _issue(
                "schema_required_preflight_checks",
                "agent_pack_bundle schema에 x-required_preflight_checks가 비어 있습니다.",
            )
        )

    _append_schema_errors(
        report=report,
        scope="bundle",
        validator=Draft202012Validator(bundle_schema),
        payload=bundle,
    )

    files = bundle.get("files") if isinstance(bundle, dict) else None
    agent = files.get("agent.json") if isinstance(files, dict) else None
    card = files.get("agent_card.json") if isinstance(files, dict) else None
    manifest = files.get("manifest.json") if isinstance(files, dict) else None
    preflight = files.get("preflight_report.json") if isinstance(files, dict) else None
    marketplace_review = files.get("marketplace_review.json") if isinstance(files, dict) else None

    if isinstance(agent, dict):
        report["agent_id"] = str(agent.get("agent_id") or "")
        report["risk_level"] = str(agent.get("risk_level") or "")
        _append_schema_errors(
            report=report,
            scope="agent",
            validator=Draft202012Validator(agent_schema),
            payload=agent,
        )
    else:
        report["errors"].append(_issue("missing_agent_contract", "files.agent.json이 객체가 아닙니다."))

    if not isinstance(preflight, dict):
        report["errors"].append(_issue("missing_preflight_report", "files.preflight_report.json이 객체가 아닙니다."))

    if not isinstance(card, dict):
        report["errors"].append(_issue("missing_agent_card", "files.agent_card.json이 객체가 아닙니다."))

    if not isinstance(marketplace_review, dict):
        report["errors"].append(_issue("missing_marketplace_review", "files.marketplace_review.json이 객체가 아닙니다."))

    if isinstance(manifest, dict):
        _run_boundary_checks(
            report,
            bundle,
            agent,
            card,
            marketplace_review,
            manifest,
            preflight,
            required_preflight_checks,
        )
    else:
        report["errors"].append(_issue("missing_manifest", "files.manifest.json이 객체가 아닙니다."))

    if report["errors"]:
        report["status"] = "fail"
    elif _risk_blocks(bundle):
        report["status"] = "blocked"
    else:
        report["status"] = "pass"

    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Validate a platform-first .agent-pack.json bundle")
    parser.add_argument("pack", help=".agent-pack.json 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON 리포트를 출력한다")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    report = validate_agent_pack(Path(args.pack))
    indent = 2 if args.pretty else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=indent) + "\n")

    if report["status"] == "pass":
        return 0
    if report["status"] == "blocked":
        return 2
    return 1


def _base_report(pack_path: Path) -> dict[str, Any]:
    """기본 리포트 구조를 만든다."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "validator": VALIDATOR_NAME,
        "status": "fail",
        "input_path": str(pack_path),
        "agent_id": "",
        "risk_level": "",
        "checks": [],
        "warnings": [],
        "errors": [],
    }


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _required_preflight_checks(bundle_schema: Any) -> set[str]:
    """bundle schema가 선언한 필수 preflight 검사 이름을 읽는다."""
    if not isinstance(bundle_schema, dict):
        return set()
    raw_checks = bundle_schema.get("x-required_preflight_checks")
    if not isinstance(raw_checks, list):
        return set()
    return {str(item).strip() for item in raw_checks if str(item).strip()}


def _append_schema_errors(
    *,
    report: dict[str, Any],
    scope: str,
    validator: Draft202012Validator,
    payload: Any,
) -> None:
    """JSON Schema 검증 오류를 리포트에 추가한다."""
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        dotted_path = ".".join(str(part) for part in error.path) or "$"
        report["errors"].append(_issue(f"{scope}_schema", f"{dotted_path}: {error.message}"))


def _run_boundary_checks(
    report: dict[str, Any],
    bundle: dict[str, Any],
    agent: Any,
    card: Any,
    marketplace_review: Any,
    manifest: dict[str, Any],
    preflight: Any,
    required_preflight_checks: set[str],
) -> None:
    """플랫폼-first 안전 경계를 추가 점검한다."""
    files = bundle.get("files") if isinstance(bundle.get("files"), dict) else {}
    expected_files = set(manifest.get("files") or [])
    actual_files = set(files)

    _check(
        report,
        "required_files_present",
        expected_files.issubset(actual_files),
        "manifest에 적힌 파일이 번들에 모두 존재한다.",
    )

    if isinstance(agent, dict):
        _check(
            report,
            "manifest_agent_id_matches_contract",
            manifest.get("agent_id") == agent.get("agent_id"),
            "manifest.agent_id와 agent.json.agent_id가 일치한다.",
        )
        _check(
            report,
            "risk_report_matches_contract",
            str((bundle.get("riskReport") or {}).get("level", "")).lower() == agent.get("risk_level"),
            "riskReport.level과 agent.json.risk_level이 일치한다.",
        )
        _check(
            report,
            "secret_collection_forbidden",
            (agent.get("data_policy") or {}).get("secret_collection") == "forbidden_by_default",
            "비밀번호, 토큰, 개인 API 키 수집은 기본 금지다.",
        )

    if isinstance(preflight, dict):
        _check(
            report,
            "preflight_validator_matches",
            preflight.get("validator") == VALIDATOR_NAME,
            "preflight_report.json은 agent_pack_preflight_v0_1 리포트다.",
        )
        if isinstance(agent, dict):
            _check(
                report,
                "preflight_agent_id_matches_contract",
                preflight.get("agent_id") == agent.get("agent_id"),
                "preflight_report.json.agent_id와 agent.json.agent_id가 일치한다.",
            )
            _check(
                report,
                "preflight_risk_matches_contract",
                preflight.get("risk_level") == agent.get("risk_level"),
                "preflight_report.json.risk_level과 agent.json.risk_level이 일치한다.",
            )

    if isinstance(agent, dict) and isinstance(card, dict):
        _check(
            report,
            "agent_card_matches_contract",
            card.get("agent_id") == agent.get("agent_id")
            and card.get("risk_level") == agent.get("risk_level")
            and card.get("evidence_status") == "no_runtime_evidence",
            "agent_card.json은 agent.json과 핵심 식별자, 위험도, 증거 상태가 일치한다.",
        )
        card_marketplace = card.get("marketplace") if isinstance(card.get("marketplace"), dict) else {}
        _check(
            report,
            "agent_card_private_preview",
            card.get("card_kind") == "private_agent_card"
            and card_marketplace.get("visibility") == "private"
            and card_marketplace.get("sale_ready") is False
            and card_marketplace.get("proof_claim_allowed") is False,
            "agent_card.json은 private preview card이며 판매 또는 proof 주장을 허용하지 않는다.",
        )

    if isinstance(card, dict) and isinstance(marketplace_review, dict):
        _check(
            report,
            "marketplace_review_matches_card",
            marketplace_review.get("agent_id") == card.get("agent_id")
            and marketplace_review.get("listing_visibility") == card.get("marketplace", {}).get("visibility"),
            "marketplace_review.json은 agent_card.json과 공개 범위, 식별자가 일치한다.",
        )
        _check(
            report,
            "marketplace_review_not_ready",
            marketplace_review.get("status") == "not_ready"
            and marketplace_review.get("sale_ready") is False
            and marketplace_review.get("proof_claim_allowed") is False,
            "marketplace_review.json은 공개 판매와 proof 주장을 아직 허용하지 않는다.",
        )

    marketplace = manifest.get("marketplace") if isinstance(manifest.get("marketplace"), dict) else {}
    _check(
        report,
        "private_by_default",
        marketplace.get("visibility") == "private",
        "마켓 공개 상태는 기본 private이다.",
    )
    _check(
        report,
        "sale_not_ready",
        marketplace.get("sale_ready") is False,
        "판매 준비 상태는 기본 false다.",
    )
    _check(
        report,
        "proof_claim_blocked",
        marketplace.get("proof_claim_allowed") is False and manifest.get("evidence_status") == "no_runtime_evidence",
        "실행 증거가 없으면 proof/성능 주장을 허용하지 않는다.",
    )
    _check(
        report,
        "cambrian_not_required",
        (manifest.get("runtime") or {}).get("cambrian_required") is False,
        "초기 플랫폼 패키지는 Cambrian Runtime을 필수로 요구하지 않는다.",
    )
    _check(
        report,
        "legal_notice_names_no_runtime_evidence",
        "no_runtime_evidence" in str(files.get("legal_notice.md") or ""),
        "legal_notice.md는 실행 증거 없음 상태를 명시한다.",
    )
    _check(
        report,
        "runner_names_cambrian_optional",
        "Cambrian 없이도 사용할 수 있습니다" in str(files.get("run_local.md") or ""),
        "run_local.md는 Cambrian 없이도 사용할 수 있음을 명시한다.",
    )
    _check(
        report,
        "runner_names_manual_runner",
        "web/runner/index.html" in str(files.get("run_local.md") or "")
        and "manual_no_api" in str(files.get("run_local.md") or ""),
        "run_local.md는 web/runner/index.html 수동 실행 경로와 manual_no_api 모드를 명시한다.",
    )

    generated_by = bundle.get("generated_by")
    candidate_metadata = bundle.get("candidate_metadata") if isinstance(bundle.get("candidate_metadata"), dict) else {}
    promotion_metadata = bundle.get("promotion_metadata") if isinstance(bundle.get("promotion_metadata"), dict) else {}
    is_candidate = generated_by == "tools/generate_candidate_pack.py"
    is_promoted = generated_by == "tools/promote_candidate_pack.py"
    if is_candidate:
        _check(
            report,
            "candidate_metadata_required",
            bool(candidate_metadata)
            and candidate_metadata.get("metadata_kind") == "candidate_agent_pack_metadata_v0_1"
            and candidate_metadata.get("source_suggestion_kind") == "evolution_suggestion_v0_1"
            and candidate_metadata.get("source_decision_kind") == "evolution_review_decision_v0_1",
            "candidate pack은 candidate_agent_pack_metadata_v0_1 메타데이터를 포함해야 한다.",
        )
        _check(
            report,
            "candidate_not_applied",
            candidate_metadata.get("apply_status") == "candidate_not_applied"
            and candidate_metadata.get("auto_apply") is False
            and candidate_metadata.get("auto_promote") is False,
            "candidate pack은 적용 완료나 자동 승격 상태가 아니어야 한다.",
        )
        _check(
            report,
            "candidate_has_approved_decision",
            bool(candidate_metadata.get("approved_decision_ids"))
            and bool(candidate_metadata.get("approved_recommendation_ids")),
            "candidate pack은 최소 하나 이상의 approved decision과 recommendation을 근거로 해야 한다.",
        )
        _check(
            report,
            "candidate_requires_final_review",
            candidate_metadata.get("requires_user_final_review") is True
            and candidate_metadata.get("original_pack_preserved") is True,
            "candidate pack은 최종 사용자 재검토가 필요하고 원본 pack 보존을 명시해야 한다.",
        )
        _check(
            report,
            "candidate_pack_has_no_promotion_metadata",
            "promotion_metadata" not in bundle,
            "candidate pack은 promotion_metadata를 포함하지 않아야 한다.",
        )
    elif is_promoted:
        _check(
            report,
            "promotion_metadata_required",
            bool(promotion_metadata)
            and promotion_metadata.get("metadata_kind") == "promoted_agent_pack_metadata_v0_1"
            and promotion_metadata.get("source_candidate_metadata_kind") == "candidate_agent_pack_metadata_v0_1"
            and promotion_metadata.get("source_diff_report_kind") == "candidate_diff_report_v0_1",
            "promoted pack은 promoted_agent_pack_metadata_v0_1 메타데이터를 포함해야 한다.",
        )
        _check(
            report,
            "promotion_requires_user_command",
            promotion_metadata.get("promotion_status") == "promoted_private_version"
            and promotion_metadata.get("candidate_apply_status_before_promotion") == "candidate_not_applied"
            and promotion_metadata.get("user_command_required") is True
            and promotion_metadata.get("auto_promote") is False,
            "promoted pack은 사용자 명령 기반 private version이며 자동 승격이면 안 된다.",
        )
        _check(
            report,
            "promotion_preserves_sources",
            promotion_metadata.get("original_pack_preserved") is True
            and promotion_metadata.get("candidate_pack_preserved") is True
            and _looks_like_sha256(promotion_metadata.get("promoted_from_candidate_hash"))
            and _looks_like_sha256(promotion_metadata.get("diff_report_hash")),
            "promoted pack은 원본, candidate, diff report 흔적을 해시로 남겨야 한다.",
        )
        _check(
            report,
            "promotion_keeps_private_boundary",
            promotion_metadata.get("proof_claim_allowed") is False
            and promotion_metadata.get("marketplace_sale_ready") is False
            and manifest.get("evidence_status") == "no_runtime_evidence"
            and marketplace.get("sale_ready") is False
            and marketplace.get("proof_claim_allowed") is False,
            "promoted pack은 private 버전으로만 승격되며 proof/판매 주장을 하지 않아야 한다.",
        )
        _check(
            report,
            "promoted_pack_has_no_candidate_metadata",
            "candidate_metadata" not in bundle,
            "promoted pack은 candidate_metadata를 그대로 가져오지 않고 promotion_metadata로 구분해야 한다.",
        )
    else:
        _check(
            report,
            "builder_pack_has_no_candidate_metadata",
            "candidate_metadata" not in bundle,
            "Builder pack은 candidate_metadata를 포함하지 않아야 한다.",
        )
        _check(
            report,
            "builder_pack_has_no_promotion_metadata",
            "promotion_metadata" not in bundle,
            "Builder pack은 promotion_metadata를 포함하지 않아야 한다.",
        )

    risk_report = bundle.get("riskReport") if isinstance(bundle.get("riskReport"), dict) else {}
    blocks = risk_report.get("blocks") if isinstance(risk_report.get("blocks"), list) else []
    expected_preflight_status = "blocked" if blocks else "pass"
    if isinstance(preflight, dict):
        _check(
            report,
            "preflight_status_matches_risk",
            preflight.get("status") == expected_preflight_status,
            "preflight_report.json.status는 Red 차단 여부와 일치한다.",
        )
        _check(
            report,
            "preflight_evidence_status_matches_manifest",
            preflight.get("evidence_status") == manifest.get("evidence_status") == "no_runtime_evidence",
            "preflight_report.json.evidence_status와 manifest.evidence_status가 일치한다.",
        )
    if blocks:
        report["warnings"].append(_issue("risk_blocked", "차단 대상 위험이 포함되어 blocked 상태가 된다."))
    if isinstance(preflight, dict):
        embedded_check_names = {
            str(item.get("name") or "")
            for item in preflight.get("checks", [])
            if isinstance(item, dict)
        }
        _check(
            report,
            "embedded_preflight_checks_complete",
            required_preflight_checks.issubset(embedded_check_names),
            "preflight_report.json은 현재 v0.1 필수 검사 이름을 모두 포함한다.",
        )


def _check(report: dict[str, Any], name: str, passed: bool, message: str) -> None:
    """경계 점검 결과를 기록한다."""
    status = "pass" if passed else "fail"
    report["checks"].append({"name": name, "status": status, "message": message})
    if not passed:
        report["errors"].append(_issue(name, message))


def _risk_blocks(bundle: dict[str, Any]) -> bool:
    """위험 차단 항목이 있는지 확인한다."""
    risk_report = bundle.get("riskReport") if isinstance(bundle.get("riskReport"), dict) else {}
    blocks = risk_report.get("blocks") if isinstance(risk_report.get("blocks"), list) else []
    return bool(blocks)


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
