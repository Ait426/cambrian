"""agent pack과 manual run receipt로 진화 제안 초안을 만든다."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_agent_pack import validate_agent_pack
from tools.validate_manual_run_receipt import validate_manual_run_receipt

EVOLUTION_SUGGESTION_SCHEMA = ROOT / "schemas" / "evolution_suggestion_v0_1.schema.json"
GENERATOR_NAME = "tools/generate_evolution_suggestion.py"

logger = logging.getLogger(__name__)


class EvolutionSuggestionError(Exception):
    """진화 제안 생성 전제 조건이 깨졌을 때 사용한다."""


def generate_evolution_suggestion(
    pack_path: Path,
    receipt_path: Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """검증된 agent pack과 manual receipt로 적용 전 진화 제안을 만든다."""
    pack_report = validate_agent_pack(pack_path)
    receipt_report = validate_manual_run_receipt(receipt_path)
    if pack_report["status"] != "pass":
        raise EvolutionSuggestionError(f"agent pack 검증이 pass가 아닙니다: {pack_report['status']}")
    if receipt_report["status"] != "pass":
        raise EvolutionSuggestionError(f"manual run receipt 검증이 pass가 아닙니다: {receipt_report['status']}")

    pack = _read_json(pack_path)
    receipt = _read_json(receipt_path)
    agent = pack["files"]["agent.json"]
    if agent["agent_id"] != receipt["agent_id"]:
        raise EvolutionSuggestionError("agent pack과 receipt의 agent_id가 일치하지 않습니다.")
    evolution_signal = receipt.get("evolution_signal") if isinstance(receipt.get("evolution_signal"), dict) else {}
    if evolution_signal.get("eligible_for_suggestion") is not True:
        raise EvolutionSuggestionError("manual run receipt가 진화 제안 생성 대상으로 표시되지 않았습니다.")
    if evolution_signal.get("requires_user_approval") is not True:
        raise EvolutionSuggestionError("manual run receipt의 진화 신호는 사용자 승인을 요구해야 합니다.")

    suggestion = _build_suggestion(
        pack=pack,
        receipt=receipt,
        generated_at=generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    schema = _read_json(EVOLUTION_SUGGESTION_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(suggestion),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        dotted_path = ".".join(str(part) for part in first.path) or "$"
        raise EvolutionSuggestionError(f"생성된 진화 제안이 schema를 통과하지 못했습니다: {dotted_path}: {first.message}")
    return suggestion


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="Generate an evolution_suggestion_v0_1 draft")
    parser.add_argument("pack", help=".agent-pack.json 파일 경로")
    parser.add_argument("receipt", help="manual_run_receipt_v0_1 JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON을 출력한다")
    parser.add_argument("--output", help="생성된 진화 제안 JSON을 저장할 경로")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    try:
        suggestion = generate_evolution_suggestion(Path(args.pack), Path(args.receipt))
    except EvolutionSuggestionError as exc:
        logger.error("진화 제안 생성 실패: %s", exc)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False) + "\n")
        return 1

    output = json.dumps(suggestion, ensure_ascii=False, indent=2 if args.pretty else None) + "\n"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except OSError as exc:
            logger.exception("진화 제안 파일을 저장하지 못했습니다.")
            sys.stdout.write(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False) + "\n")
            return 1
    else:
        sys.stdout.write(output)
    return 0


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _build_suggestion(
    *,
    pack: dict[str, Any],
    receipt: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """schema에 맞는 진화 제안 초안을 구성한다."""
    agent = pack["files"]["agent.json"]
    manual_checks = receipt.get("manual_checks") if isinstance(receipt.get("manual_checks"), list) else []
    evolution_signal = receipt.get("evolution_signal") if isinstance(receipt.get("evolution_signal"), dict) else {}
    check_count = len(manual_checks)
    result_status = str(receipt.get("result_status") or "result_not_recorded")
    recommendations = _recommendations(agent, receipt, check_count)

    return {
        "$schema": "https://cambrian.local/schemas/evolution_suggestion_v0_1.schema.json",
        "schema_version": "0.1",
        "suggestion_kind": "evolution_suggestion_v0_1",
        "generated_by": GENERATOR_NAME,
        "generated_at": generated_at,
        "source_agent": {
          "agent_id": agent["agent_id"],
          "agent_name": agent["name"],
          "bundle_schema": pack["bundle_schema"],
          "risk_level": agent["risk_level"],
        },
        "source_receipt": {
          "receipt_kind": receipt["receipt_kind"],
          "runner_mode": receipt["runner_mode"],
          "run_status": receipt["run_status"],
          "result_status": result_status,
          "input_length": receipt["input_summary"]["input_length"],
          "output_length": receipt["output_summary"]["output_length"],
          "manual_check_count": check_count,
          "eligible_for_suggestion": evolution_signal.get("eligible_for_suggestion") is True,
          "requires_user_approval": evolution_signal.get("requires_user_approval") is True,
        },
        "proposal_status": "draft_requires_user_approval",
        "approval_gate": {
          "requires_user_approval": True,
          "auto_apply": False,
          "auto_promote": False,
          "can_create_new_version": False,
        },
        "proof_boundary": {
          "uses_runtime_evidence": False,
          "proof_claim_allowed": False,
          "success_rate_claim_allowed": False,
          "marketplace_sale_ready": False,
        },
        "privacy": {
          "stores_raw_inputs": False,
          "stores_raw_outputs": False,
          "stores_secrets": False,
          "uses_only_receipt_metadata": True,
        },
        "recommendations": recommendations,
        "rollback": {
          "required_before_apply": True,
          "strategy": "save_previous_agent_pack_before_new_version",
        },
    }


def _recommendations(agent: dict[str, Any], receipt: dict[str, Any], check_count: int) -> list[dict[str, Any]]:
    """receipt 메타데이터를 바탕으로 안전한 진화 제안을 만든다."""
    criteria = agent.get("validation_criteria") if isinstance(agent.get("validation_criteria"), list) else []
    output_length = int(receipt.get("output_summary", {}).get("output_length") or 0)
    result_status = str(receipt.get("result_status") or "")
    recommendations = [
        {
            "id": "evo_1",
            "title": "수동 검증 체크리스트를 출력 말미에 고정",
            "target": "instructions.md",
            "rationale": f"receipt에 {check_count}개의 manual check가 있으며 모두 사용자 검토가 필요합니다.",
            "proposed_change": "결과 마지막에 validation_criteria 기반의 사용자 확인 체크리스트를 항상 붙이도록 instructions.md를 강화합니다.",
            "risk_level": "low",
            "acceptance_criteria": [
                "출력 끝에 사용자 확인 체크리스트가 포함된다.",
                "체크리스트가 proof나 성공률로 표현되지 않는다.",
            ],
            "status": "suggested",
        },
        {
            "id": "evo_2",
            "title": "known limits에 manual_no_api 한계 추가",
            "target": "agent.json.known_limits",
            "rationale": "manual_no_api 실행은 원문 저장 없는 수동 검토 메타데이터만 남기므로 proof가 아닙니다.",
            "proposed_change": "manual_no_api 결과는 proof가 아니며 사용자가 직접 검토해야 한다는 known limit을 추가합니다.",
            "risk_level": "low",
            "acceptance_criteria": [
                "known_limits에 수동 실행 한계가 명시된다.",
                "marketplace_sale_ready가 false로 유지된다.",
            ],
            "status": "suggested",
        },
    ]

    if criteria and result_status == "result_pasted_for_manual_review" and output_length > 0:
        recommendations.append(
            {
                "id": "evo_3",
                "title": "검증 기준을 더 측정 가능한 문장으로 정리",
                "target": "agent.json.validation_criteria",
                "rationale": "receipt에 실제 결과 길이와 수동 검토 기준이 있어 다음 버전에서 검증 문장을 더 명확히 만들 수 있습니다.",
                "proposed_change": "각 validation_criteria를 사용자가 예/아니오로 확인할 수 있는 문장으로 다듬는 초안을 만듭니다.",
                "risk_level": "medium",
                "acceptance_criteria": [
                    "각 검증 기준이 단일 판단 문장으로 유지된다.",
                    "의료, 법률, 투자, 채용 판단으로 범위가 넓어지지 않는다.",
                ],
                "status": "suggested",
            }
        )

    return recommendations


if __name__ == "__main__":
    raise SystemExit(main())
