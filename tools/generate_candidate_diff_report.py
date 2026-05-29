"""원본 pack과 candidate pack의 차이 리포트를 만든다."""

from __future__ import annotations

import argparse
import hashlib
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
from tools.validate_evolution_review_decision import validate_evolution_review_decision


CANDIDATE_DIFF_REPORT_SCHEMA = ROOT / "schemas" / "candidate_diff_report_v0_1.schema.json"
GENERATOR_NAME = "tools/generate_candidate_diff_report.py"

logger = logging.getLogger(__name__)


class CandidateDiffError(Exception):
    """candidate diff report 생성 전제 조건이 깨졌을 때 사용한다."""


def generate_candidate_diff_report(
    original_pack_path: Path,
    candidate_pack_path: Path,
    decision_path: Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """원본 pack과 candidate pack의 변경이 승인된 범위 안인지 검토한다."""
    original_report = validate_agent_pack(original_pack_path)
    candidate_report = validate_agent_pack(candidate_pack_path)
    decision_report = validate_evolution_review_decision(decision_path)
    if original_report["status"] != "pass":
        raise CandidateDiffError(f"원본 agent pack 검증이 pass가 아닙니다: {original_report['status']}")
    if candidate_report["status"] != "pass":
        raise CandidateDiffError(f"candidate agent pack 검증이 pass가 아닙니다: {candidate_report['status']}")
    if decision_report["status"] != "pass":
        raise CandidateDiffError(f"evolution review decision 검증이 pass가 아닙니다: {decision_report['status']}")

    original = _read_json(original_pack_path)
    candidate = _read_json(candidate_pack_path)
    decision = _read_json(decision_path)
    _assert_sources_match(original, candidate, decision)

    approved_decisions = _approved_decisions(decision)
    blocked_decisions = _deferred_or_rejected_decisions(decision)
    allowed_path_reasons = _allowed_paths_for_decisions(
        approved_decisions,
        allow_promotion_metadata_removal=_is_promoted_private_version(original),
    )
    changes = _changed_paths(original, candidate)
    allowed_changes = []
    unexpected_changes = []
    for change in changes:
        reason = allowed_path_reasons.get(change["path"])
        if reason is None and change["path"].startswith("candidate_metadata."):
            reason = allowed_path_reasons["candidate_metadata"]
        if (
            reason is None
            and change["path"].startswith("promotion_metadata.")
            and change["change_type"] == "removed"
        ):
            reason = allowed_path_reasons.get("promotion_metadata")
        if reason:
            allowed_changes.append({**change, **reason})
        else:
            unexpected_changes.append(change)

    report = {
        "$schema": "https://cambrian.local/schemas/candidate_diff_report_v0_1.schema.json",
        "schema_version": "0.1",
        "report_kind": "candidate_diff_report_v0_1",
        "generated_by": GENERATOR_NAME,
        "generated_at": generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": {
            "agent_id": original["files"]["agent.json"]["agent_id"],
            "original_pack_hash": _hash_payload(original),
            "candidate_pack_hash": _hash_payload(candidate),
            "decision_kind": decision["decision_kind"],
            "decision_review_status": decision["review_status"],
        },
        "diff_status": "review_pass_not_promoted" if not unexpected_changes else "review_fail",
        "comparison": {
            "agent_id_matches": True,
            "original_pack_valid": True,
            "candidate_pack_valid": True,
            "candidate_is_distinct": _hash_payload(original) != _hash_payload(candidate),
            "only_approved_decisions_applied": not unexpected_changes,
            "deferred_and_rejected_not_applied": _blocked_decisions_not_applied(changes, blocked_decisions),
        },
        "approval_gate": {
            "auto_promote": False,
            "candidate_review_required": True,
            "promotion_requires_separate_command": True,
        },
        "proof_boundary": {
            "uses_runtime_evidence": False,
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "marketplace_sale_ready": False,
        },
        "change_summary": {
            "changed_path_count": len(changes),
            "changed_files": _changed_files(changes),
            "approved_decision_ids": [item["recommendation_id"] for item in approved_decisions],
            "deferred_or_rejected_decision_ids": [item["recommendation_id"] for item in blocked_decisions],
        },
        "allowed_changes": allowed_changes,
        "unexpected_changes": unexpected_changes,
        "next_step": {
            "allowed": "promote_candidate_after_user_command",
            "blocked": "automatic_candidate_promotion",
        },
    }
    _validate_report_schema(report)
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate a candidate_diff_report_v0_1 JSON file")
    parser.add_argument("original_pack", help="원본 .agent-pack.json 파일 경로")
    parser.add_argument("candidate_pack", help="candidate .agent-pack.json 파일 경로")
    parser.add_argument("decision", help="evolution_review_decision_v0_1 JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON을 출력한다")
    parser.add_argument("--output", help="생성된 diff report를 저장할 경로")
    parser.add_argument("--generated-at", help="테스트와 샘플 생성을 위한 ISO 시간")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    try:
        report = generate_candidate_diff_report(
            Path(args.original_pack),
            Path(args.candidate_pack),
            Path(args.decision),
            generated_at=args.generated_at,
        )
    except CandidateDiffError as exc:
        logger.error("candidate diff report 생성 실패: %s", exc)
        _write_stdout({"status": "fail", "error": str(exc)})
        return 1

    output = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None) + "\n"
    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except OSError as exc:
            logger.exception("candidate diff report 파일을 저장하지 못했습니다.")
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


def _hash_payload(payload: Any) -> str:
    """정렬된 JSON payload의 sha256 해시를 만든다."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _assert_sources_match(original: dict[str, Any], candidate: dict[str, Any], decision: dict[str, Any]) -> None:
    """원본, 후보, decision이 같은 agent를 가리키는지 확인한다."""
    ids = {
        original["files"]["agent.json"]["agent_id"],
        candidate["files"]["agent.json"]["agent_id"],
        decision["source_suggestion"]["agent_id"],
    }
    if len(ids) != 1:
        raise CandidateDiffError("원본 pack, candidate pack, decision의 agent_id가 일치하지 않습니다.")
    if decision["review_status"] != "reviewed_not_applied":
        raise CandidateDiffError("decision은 reviewed_not_applied 상태여야 합니다.")


def _approved_decisions(decision: dict[str, Any]) -> list[dict[str, Any]]:
    """승인된 decision 목록을 반환한다."""
    return [item for item in decision["decisions"] if item["decision"] == "approved"]


def _deferred_or_rejected_decisions(decision: dict[str, Any]) -> list[dict[str, Any]]:
    """보류 또는 거절된 decision 목록을 반환한다."""
    return [item for item in decision["decisions"] if item["decision"] != "approved"]


def _allowed_paths_for_decisions(
    decisions: list[dict[str, Any]],
    *,
    allow_promotion_metadata_removal: bool = False,
) -> dict[str, dict[str, str]]:
    """승인된 decision이 허용하는 변경 경로를 만든다."""
    allowed = {
        "candidate_metadata": {
            "source_decision_id": "candidate_metadata",
            "reason": "candidate pack 생성 경계와 승인 decision 요약을 남긴다.",
        },
        "generated_by": {
            "source_decision_id": "candidate_metadata",
            "reason": "candidate pack 생성 도구 출처를 남긴다.",
        },
        "files.agent.json.provenance": {
            "source_decision_id": "candidate_metadata",
            "reason": "evolution_candidate provenance를 남긴다.",
        },
    }
    if allow_promotion_metadata_removal:
        allowed["promotion_metadata"] = {
            "source_decision_id": "candidate_metadata",
            "reason": "promoted_private_version을 새 candidate review 초안으로 만들기 위해 이전 promotion_metadata를 제거한다.",
        }
    for item in decisions:
        rec_id = item["recommendation_id"]
        target = item["target"]
        if target == "instructions.md":
            allowed["files.instructions.md"] = {
                "source_decision_id": rec_id,
                "reason": "승인된 instructions.md 진화 제안을 반영한다.",
            }
        elif target == "agent.json.known_limits":
            allowed["files.agent.json.known_limits"] = {
                "source_decision_id": rec_id,
                "reason": "승인된 agent known_limits 진화 제안을 반영한다.",
            }
            allowed["files.agent_card.json.known_limits"] = {
                "source_decision_id": rec_id,
                "reason": "agent card의 known limits를 agent 계약과 맞춘다.",
            }
        elif target == "agent.json.validation_criteria":
            allowed["files.agent.json.validation_criteria"] = {
                "source_decision_id": rec_id,
                "reason": "승인된 validation_criteria 진화 제안을 반영한다.",
            }
        elif target == "agent_card.json":
            allowed["files.agent_card.json.known_limits"] = {
                "source_decision_id": rec_id,
                "reason": "승인된 agent card 진화 제안을 반영한다.",
            }
    return allowed


def _changed_paths(original: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, str]]:
    """원본과 후보의 leaf 경로 변경 목록을 만든다."""
    original_flat = _flatten(original)
    candidate_flat = _flatten(candidate)
    changes = []
    for path in sorted(set(original_flat) | set(candidate_flat)):
        if original_flat.get(path) == candidate_flat.get(path):
            continue
        if path not in original_flat:
            change_type = "added"
        elif path not in candidate_flat:
            change_type = "removed"
        else:
            change_type = "modified"
        changes.append({"path": path, "change_type": change_type})
    return changes


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """dict는 재귀적으로, list와 원시값은 leaf로 취급해 평탄화한다."""
    if isinstance(value, dict):
        flattened = {}
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten(item, child_prefix))
        return flattened
    return {prefix: value}


def _blocked_decisions_not_applied(changes: list[dict[str, str]], decisions: list[dict[str, Any]]) -> bool:
    """보류/거절된 decision 대상이 변경되지 않았는지 확인한다."""
    changed_paths = {item["path"] for item in changes}
    blocked_allowed_paths = _allowed_paths_for_decisions(decisions)
    for metadata_path in ["candidate_metadata", "generated_by", "files.agent.json.provenance", "promotion_metadata"]:
        blocked_allowed_paths.pop(metadata_path, None)
    return not bool(changed_paths & set(blocked_allowed_paths))


def _is_promoted_private_version(pack: dict[str, Any]) -> bool:
    """원본 pack이 Hub에서 다시 진화할 수 있는 promoted private version인지 확인한다."""
    metadata = pack.get("promotion_metadata") if isinstance(pack.get("promotion_metadata"), dict) else {}
    return (
        pack.get("generated_by") == "tools/promote_candidate_pack.py"
        and "candidate_metadata" not in pack
        and metadata.get("metadata_kind") == "promoted_agent_pack_metadata_v0_1"
        and metadata.get("promotion_status") == "promoted_private_version"
        and metadata.get("user_command_required") is True
        and metadata.get("auto_promote") is False
        and metadata.get("proof_claim_allowed") is False
        and metadata.get("marketplace_sale_ready") is False
    )


def _changed_files(changes: list[dict[str, str]]) -> list[str]:
    """변경 path에서 파일 단위 이름을 추출한다."""
    files = set()
    for item in changes:
        path = item["path"]
        if path.startswith("files."):
            without_prefix = path.removeprefix("files.")
            for suffix in [".json", ".md"]:
                marker = suffix + "."
                if marker in without_prefix:
                    files.add(without_prefix.split(marker, 1)[0] + suffix)
                    break
            else:
                files.add(without_prefix)
        else:
            files.add(path)
    return sorted(files)


def _validate_report_schema(report: dict[str, Any]) -> None:
    """생성된 diff report가 schema를 통과하는지 확인한다."""
    schema = _read_json(CANDIDATE_DIFF_REPORT_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(report),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        dotted_path = ".".join(str(part) for part in first.path) or "$"
        raise CandidateDiffError(f"생성된 diff report가 schema를 통과하지 못했습니다: {dotted_path}: {first.message}")


if __name__ == "__main__":
    raise SystemExit(main())
