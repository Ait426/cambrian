"""승인된 evolution review decision으로 새 agent pack 후보를 만든다."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate_agent_pack import validate_agent_pack
from tools.validate_evolution_review_decision import validate_evolution_review_decision
from tools.validate_evolution_suggestion import validate_evolution_suggestion


GENERATOR_NAME = "tools/generate_candidate_pack.py"

logger = logging.getLogger(__name__)


class CandidatePackError(Exception):
    """candidate pack 생성 전제 조건이 깨졌을 때 사용한다."""


def generate_candidate_pack(
    pack_path: Path,
    suggestion_path: Path,
    decision_path: Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """승인된 진화 결정만 반영한 새 agent pack 후보를 반환한다."""
    pack_report = validate_agent_pack(pack_path)
    suggestion_report = validate_evolution_suggestion(suggestion_path)
    decision_report = validate_evolution_review_decision(decision_path)
    if pack_report["status"] != "pass":
        raise CandidatePackError(f"agent pack 검증이 pass가 아닙니다: {pack_report['status']}")
    if suggestion_report["status"] != "pass":
        raise CandidatePackError(f"evolution suggestion 검증이 pass가 아닙니다: {suggestion_report['status']}")
    if decision_report["status"] != "pass":
        raise CandidatePackError(f"evolution review decision 검증이 pass가 아닙니다: {decision_report['status']}")

    pack = _read_json(pack_path)
    suggestion = _read_json(suggestion_path)
    decision = _read_json(decision_path)
    _assert_sources_match(pack, suggestion, decision)

    candidate = copy.deepcopy(pack)
    timestamp = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _apply_approved_decisions(candidate, suggestion, decision, timestamp)

    candidate_report = validate_agent_pack_payload(candidate)
    if candidate_report["status"] != "pass":
        raise CandidatePackError(f"candidate pack 검증이 pass가 아닙니다: {candidate_report['status']}")
    return candidate


def validate_agent_pack_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    """임시 파일 없이 candidate payload를 기존 검증기에 통과시킨다."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".agent-pack.json", delete=False) as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)
        temp_path = Path(handle.name)
    try:
        return validate_agent_pack(temp_path)
    finally:
        try:
            temp_path.unlink()
        except OSError as exc:
            logger.warning("임시 candidate pack 파일 삭제 실패: %s", exc)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate a candidate .agent-pack.json from approved evolution decisions")
    parser.add_argument("pack", help="원본 .agent-pack.json 파일 경로")
    parser.add_argument("suggestion", help="evolution_suggestion_v0_1 JSON 파일 경로")
    parser.add_argument("decision", help="evolution_review_decision_v0_1 JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON을 출력한다")
    parser.add_argument("--output", help="생성된 candidate pack을 저장할 경로")
    parser.add_argument("--generated-at", help="테스트와 샘플 생성을 위한 ISO 시간")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    pack_path = Path(args.pack)
    output_path = Path(args.output) if args.output else None
    if output_path and output_path.resolve() == pack_path.resolve():
        logger.error("candidate pack 출력 경로가 원본 pack과 같습니다.")
        _write_stdout({"status": "fail", "error": "candidate pack 출력 경로가 원본 pack과 같습니다."})
        return 1

    try:
        candidate = generate_candidate_pack(
            pack_path,
            Path(args.suggestion),
            Path(args.decision),
            generated_at=args.generated_at,
        )
    except CandidatePackError as exc:
        logger.error("candidate pack 생성 실패: %s", exc)
        _write_stdout({"status": "fail", "error": str(exc)})
        return 1

    output = json.dumps(candidate, ensure_ascii=False, indent=2 if args.pretty else None) + "\n"
    if output_path:
        try:
            output_path.write_text(output, encoding="utf-8")
        except OSError as exc:
            logger.exception("candidate pack 파일을 저장하지 못했습니다.")
            _write_stdout({"status": "fail", "error": str(exc)})
            return 1
    else:
        _write_stdout_raw(output)
    return 0


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


def _write_stdout(payload: dict[str, Any]) -> None:
    """JSON payload를 stdout에 쓴다."""
    _write_stdout_raw(json.dumps(payload, ensure_ascii=False) + "\n")


def _write_stdout_raw(text: str) -> None:
    """문자열을 UTF-8 stdout에 쓴다."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(text)


def _assert_sources_match(
    pack: dict[str, Any],
    suggestion: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    """pack, suggestion, decision이 같은 agent와 추천 목록을 가리키는지 확인한다."""
    agent_id = pack["files"]["agent.json"]["agent_id"]
    suggestion_agent_id = suggestion["source_agent"]["agent_id"]
    decision_agent_id = decision["source_suggestion"]["agent_id"]
    if len({agent_id, suggestion_agent_id, decision_agent_id}) != 1:
        raise CandidatePackError("pack, suggestion, decision의 agent_id가 일치하지 않습니다.")

    suggestion_ids = {item["id"] for item in suggestion["recommendations"]}
    decision_ids = {item["recommendation_id"] for item in decision["decisions"]}
    source_ids = set(decision["source_suggestion"].get("recommendation_ids") or [])
    if decision_ids != suggestion_ids or source_ids != suggestion_ids:
        raise CandidatePackError("decision은 suggestion의 모든 recommendation_id를 정확히 한 번씩 포함해야 합니다.")
    if decision["source_suggestion"]["recommendation_count"] != len(suggestion["recommendations"]):
        raise CandidatePackError("decision의 recommendation_count가 suggestion과 일치하지 않습니다.")


def _apply_approved_decisions(
    candidate: dict[str, Any],
    suggestion: dict[str, Any],
    decision: dict[str, Any],
    generated_at: str,
) -> None:
    """승인된 결정만 candidate pack에 반영한다."""
    recommendations = {item["id"]: item for item in suggestion["recommendations"]}
    approved = [
        item
        for item in decision["decisions"]
        if item["decision"] == "approved"
    ]
    if not approved:
        raise CandidatePackError("approved decision이 없으면 candidate pack을 생성하지 않습니다.")

    files = candidate["files"]
    agent = files["agent.json"]
    card = files["agent_card.json"]
    candidate["generated_by"] = GENERATOR_NAME
    candidate.pop("promotion_metadata", None)
    candidate["candidate_metadata"] = _candidate_metadata(suggestion, decision, approved, generated_at)
    _append_unique(
        agent["known_limits"],
        "이 후보 pack은 evolution_review_decision_v0_1 기반이며, 최종 적용 전 사용자가 다시 검토해야 합니다.",
    )
    _append_unique(
        card["known_limits"],
        "이 후보 pack은 evolution_review_decision_v0_1 기반이며, 최종 적용 전 사용자가 다시 검토해야 합니다.",
    )
    agent["provenance"].append(
        {
            "source": "evolution_review_decision_v0_1",
            "kind": "evolution_candidate",
            "generated_at": generated_at,
        }
    )

    for decision_item in approved:
        recommendation = recommendations[decision_item["recommendation_id"]]
        target = recommendation["target"]
        if target == "instructions.md":
            files["instructions.md"] = _append_instructions_checklist(
                files["instructions.md"],
                agent["validation_criteria"],
            )
            files["instructions.md"] = _append_instructions_evolution_note(
                files["instructions.md"],
                recommendation,
            )
        elif target == "agent.json.known_limits":
            _append_unique(agent["known_limits"], recommendation["proposed_change"])
            _append_unique(card["known_limits"], recommendation["proposed_change"])
        elif target == "agent.json.validation_criteria":
            _append_unique(
                agent["validation_criteria"],
                "각 결과 항목은 사용자가 예/아니오로 확인할 수 있게 작성되어야 한다.",
            )
        elif target == "agent_card.json":
            _append_unique(card["known_limits"], recommendation["proposed_change"])


def _candidate_metadata(
    suggestion: dict[str, Any],
    decision: dict[str, Any],
    approved: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """candidate pack이 적용 완료가 아니라 검토 대상임을 명시하는 메타데이터를 만든다."""
    approved_recommendation_ids = [item["recommendation_id"] for item in approved]
    deferred_recommendation_ids = [
        item["recommendation_id"]
        for item in decision["decisions"]
        if item["decision"] == "deferred"
    ]
    rejected_recommendation_ids = [
        item["recommendation_id"]
        for item in decision["decisions"]
        if item["decision"] == "rejected"
    ]
    return {
        "metadata_kind": "candidate_agent_pack_metadata_v0_1",
        "source_suggestion_kind": suggestion["suggestion_kind"],
        "source_decision_kind": decision["decision_kind"],
        "apply_status": "candidate_not_applied",
        "auto_apply": False,
        "auto_promote": False,
        "approved_decision_ids": [item["id"] for item in approved],
        "approved_recommendation_ids": approved_recommendation_ids,
        "deferred_recommendation_ids": deferred_recommendation_ids,
        "rejected_recommendation_ids": rejected_recommendation_ids,
        "requires_user_final_review": True,
        "original_pack_preserved": True,
        "generated_at": generated_at,
    }


def _append_instructions_checklist(markdown: str, criteria: list[str]) -> str:
    """instructions.md에 수동 검증 체크리스트 섹션을 한 번만 추가한다."""
    marker = "## 수동 검증 체크리스트"
    if marker in markdown:
        return markdown
    checklist = "\n".join(f"- {item}" for item in criteria)
    return (
        markdown.rstrip()
        + "\n\n"
        + marker
        + "\n이 항목은 proof가 아니라 사용자가 직접 확인할 체크리스트입니다.\n"
        + checklist
        + "\n"
    )


def _append_instructions_evolution_note(
    markdown: str,
    recommendation: dict[str, Any],
) -> str:
    """승인된 instructions.md 진화 제안 본문을 후보 pack 검토 섹션에 남긴다."""
    marker = "## 승인된 instructions 진화 제안"
    title = str(recommendation.get("title") or "instructions.md 진화 제안")
    proposed_change = str(recommendation.get("proposed_change") or "").strip()
    line = f"- {title}: {proposed_change}"
    current = markdown.strip()
    if line in current:
        return current
    if marker in current:
        return current + "\n" + line + "\n"
    return (
        current
        + "\n\n"
        + marker
        + "\n이 섹션은 자동 적용 완료가 아니라 후보 pack 검토용입니다.\n"
        + line
        + "\n"
    )


def _append_unique(items: list[str], value: str) -> None:
    """문자열 목록에 중복 없이 값을 추가한다."""
    if value not in items:
        items.append(value)


if __name__ == "__main__":
    raise SystemExit(main())
