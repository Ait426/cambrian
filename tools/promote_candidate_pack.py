"""diff gate를 통과한 candidate pack을 private version으로 승격한다."""

from __future__ import annotations

import argparse
import copy
import hashlib
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
from tools.validate_candidate_diff_report import validate_candidate_diff_report
from tools.validate_candidate_promotion_record import validate_candidate_promotion_record


PROMOTER_NAME = "tools/promote_candidate_pack.py"
CANDIDATE_GENERATOR_NAME = "tools/generate_candidate_pack.py"
DIFF_GENERATOR_NAME = "tools/generate_candidate_diff_report.py"
CANDIDATE_NOTICE = "이 후보 pack은 evolution_review_decision_v0_1 기반이며, 최종 적용 전 사용자가 다시 검토해야 합니다."
PROMOTED_NOTICE = "이 private version은 candidate diff gate를 통과했지만 runtime evidence, proof, 공개 판매 준비 상태가 아닙니다."

logger = logging.getLogger(__name__)


class CandidatePromotionError(Exception):
    """candidate promotion 전제 조건이 깨졌을 때 사용한다."""


def promote_candidate_pack(
    original_pack_path: Path,
    candidate_pack_path: Path,
    diff_report_path: Path,
    *,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """검증된 candidate pack을 private version과 promotion record로 승격한다."""
    original_report = validate_agent_pack(original_pack_path)
    candidate_report = validate_agent_pack(candidate_pack_path)
    diff_validation = validate_candidate_diff_report(diff_report_path)
    if original_report["status"] != "pass":
        raise CandidatePromotionError(f"원본 agent pack 검증이 pass가 아닙니다: {original_report['status']}")
    if candidate_report["status"] != "pass":
        raise CandidatePromotionError(f"candidate agent pack 검증이 pass가 아닙니다: {candidate_report['status']}")
    if diff_validation["status"] != "pass":
        raise CandidatePromotionError(f"candidate diff report 검증이 pass가 아닙니다: {diff_validation['status']}")

    original = _read_json(original_pack_path)
    candidate = _read_json(candidate_pack_path)
    diff_report = _read_json(diff_report_path)
    _assert_sources_match(original, candidate, diff_report)

    timestamp = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    promoted = copy.deepcopy(candidate)
    promoted["generated_by"] = PROMOTER_NAME
    candidate_metadata = promoted.pop("candidate_metadata")
    promoted["promotion_metadata"] = _promotion_metadata(candidate_metadata, candidate, diff_report, timestamp)

    agent = promoted["files"]["agent.json"]
    card = promoted["files"]["agent_card.json"]
    _replace_candidate_notice(agent["known_limits"])
    _replace_candidate_notice(card["known_limits"])
    agent["provenance"].append(
        {
            "source": "candidate_diff_report_v0_1",
            "kind": "evolution_promoted",
            "generated_at": timestamp,
        }
    )

    promoted_report = validate_agent_pack_payload(promoted)
    if promoted_report["status"] != "pass":
        raise CandidatePromotionError(f"promoted pack 검증이 pass가 아닙니다: {promoted_report['status']}")
    record = _promotion_record(original, candidate, diff_report, promoted, timestamp)
    record_report = validate_candidate_promotion_record_payload(record)
    if record_report["status"] != "pass":
        raise CandidatePromotionError(f"candidate promotion record 검증이 pass가 아닙니다: {record_report['status']}")
    return promoted, record


def promote_candidate_pack_with_record(
    original_pack_path: Path,
    candidate_pack_path: Path,
    diff_report_path: Path,
    *,
    generated_at: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """promoted pack과 candidate promotion record를 함께 만든다."""
    return promote_candidate_pack(
        original_pack_path,
        candidate_pack_path,
        diff_report_path,
        generated_at=generated_at,
    )


def validate_agent_pack_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    """임시 파일로 promoted payload를 기존 pack 검증기에 통과시킨다."""
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
            logger.warning("임시 promoted pack 파일 삭제 실패: %s", exc)


def validate_candidate_promotion_record_payload(record: dict[str, Any]) -> dict[str, Any]:
    """임시 파일로 promotion record payload를 기존 검증기에 통과시킨다."""
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".candidate-promotion-record.json", delete=False) as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        temp_path = Path(handle.name)
    try:
        return validate_candidate_promotion_record(temp_path)
    finally:
        try:
            temp_path.unlink()
        except OSError as exc:
            logger.warning("임시 promotion record 파일 삭제 실패: %s", exc)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Promote a reviewed candidate .agent-pack.json to a private version")
    parser.add_argument("original_pack", help="원본 .agent-pack.json 파일 경로")
    parser.add_argument("candidate_pack", help="candidate .agent-pack.json 파일 경로")
    parser.add_argument("diff_report", help="candidate_diff_report_v0_1 JSON 파일 경로")
    parser.add_argument("--pretty", action="store_true", help="들여쓰기된 JSON을 출력한다")
    parser.add_argument("--output", help="생성된 promoted pack을 저장할 경로")
    parser.add_argument("--pack-output", help="생성된 promoted pack을 저장할 경로")
    parser.add_argument("--record-output", help="생성된 promotion record를 저장할 경로")
    parser.add_argument("--generated-at", help="테스트와 샘플 생성을 위한 ISO 시간")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    source_paths = {
        Path(args.original_pack).resolve(),
        Path(args.candidate_pack).resolve(),
        Path(args.diff_report).resolve(),
    }
    pack_output_path = Path(args.pack_output or args.output) if (args.pack_output or args.output) else None
    record_output_path = Path(args.record_output) if args.record_output else None
    output_error = _validate_output_paths(source_paths, pack_output_path, record_output_path)
    if output_error:
        logger.error(output_error)
        _write_stdout({"status": "fail", "error": output_error})
        return 1

    try:
        promoted, record = promote_candidate_pack_with_record(
            Path(args.original_pack),
            Path(args.candidate_pack),
            Path(args.diff_report),
            generated_at=args.generated_at,
        )
    except CandidatePromotionError as exc:
        logger.error("candidate promotion 실패: %s", exc)
        _write_stdout({"status": "fail", "error": str(exc)})
        return 1

    promoted_output = json.dumps(promoted, ensure_ascii=False, indent=2 if args.pretty else None) + "\n"
    record_output = json.dumps(record, ensure_ascii=False, indent=2 if args.pretty else None) + "\n"
    if pack_output_path or record_output_path:
        try:
            if pack_output_path:
                pack_output_path.write_text(promoted_output, encoding="utf-8")
            if record_output_path:
                record_output_path.write_text(record_output, encoding="utf-8")
        except OSError as exc:
            logger.exception("candidate promotion 출력 파일을 저장하지 못했습니다.")
            _write_stdout({"status": "fail", "error": str(exc)})
            return 1
    else:
        _write_stdout_raw(
            json.dumps(
                {"promoted_pack": promoted, "promotion_record": record},
                ensure_ascii=False,
                indent=2 if args.pretty else None,
            )
            + "\n"
        )
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


def _validate_output_paths(
    source_paths: set[Path],
    pack_output_path: Path | None,
    record_output_path: Path | None,
) -> str | None:
    """출력 경로가 입력 파일이나 서로를 덮어쓰지 않는지 확인한다."""
    if pack_output_path and pack_output_path.resolve() in source_paths:
        return "promoted pack 출력 경로가 입력 파일과 같습니다."
    if record_output_path and record_output_path.resolve() in source_paths:
        return "promotion record 출력 경로가 입력 파일과 같습니다."
    if pack_output_path and record_output_path and pack_output_path.resolve() == record_output_path.resolve():
        return "promoted pack 출력 경로와 promotion record 출력 경로가 같습니다."
    return None


def _assert_sources_match(
    original: dict[str, Any],
    candidate: dict[str, Any],
    diff_report: dict[str, Any],
) -> None:
    """원본, 후보, diff report가 같은 agent와 해시를 가리키는지 확인한다."""
    source = diff_report["source"]
    agent_ids = {
        original["files"]["agent.json"]["agent_id"],
        candidate["files"]["agent.json"]["agent_id"],
        source["agent_id"],
    }
    if len(agent_ids) != 1:
        raise CandidatePromotionError("원본 pack, candidate pack, diff report의 agent_id가 일치하지 않습니다.")
    if candidate.get("generated_by") != CANDIDATE_GENERATOR_NAME:
        raise CandidatePromotionError("candidate pack은 generate_candidate_pack.py 산출물이어야 합니다.")

    candidate_metadata = candidate.get("candidate_metadata") if isinstance(candidate.get("candidate_metadata"), dict) else {}
    if candidate_metadata.get("apply_status") != "candidate_not_applied":
        raise CandidatePromotionError("candidate pack은 candidate_not_applied 상태여야 합니다.")
    if candidate_metadata.get("requires_user_final_review") is not True:
        raise CandidatePromotionError("candidate pack은 최종 사용자 검토 필요 상태여야 합니다.")
    if diff_report.get("diff_status") != "review_pass_not_promoted":
        raise CandidatePromotionError("diff report는 review_pass_not_promoted 상태여야 합니다.")
    if (diff_report.get("next_step") or {}).get("allowed") != "promote_candidate_after_user_command":
        raise CandidatePromotionError("diff report가 promotion 별도 명령을 허용하지 않습니다.")

    original_hash = _hash_payload(original)
    candidate_hash = _hash_payload(candidate)
    if source.get("original_pack_hash") != original_hash:
        raise CandidatePromotionError("diff report의 original pack hash가 현재 원본과 일치하지 않습니다.")
    if source.get("candidate_pack_hash") != candidate_hash:
        raise CandidatePromotionError("diff report의 candidate pack hash가 현재 후보와 일치하지 않습니다.")


def _promotion_metadata(
    candidate_metadata: dict[str, Any],
    candidate: dict[str, Any],
    diff_report: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """private version 승격 경계를 명시하는 메타데이터를 만든다."""
    return {
        "metadata_kind": "promoted_agent_pack_metadata_v0_1",
        "source_candidate_metadata_kind": candidate_metadata["metadata_kind"],
        "source_candidate_generated_by": candidate["generated_by"],
        "source_diff_report_kind": diff_report["report_kind"],
        "source_diff_report_generated_by": diff_report["generated_by"],
        "promotion_status": "promoted_private_version",
        "candidate_apply_status_before_promotion": candidate_metadata["apply_status"],
        "user_command_required": True,
        "auto_promote": False,
        "approved_decision_ids": candidate_metadata["approved_decision_ids"],
        "approved_recommendation_ids": candidate_metadata["approved_recommendation_ids"],
        "original_pack_preserved": True,
        "candidate_pack_preserved": True,
        "proof_claim_allowed": False,
        "marketplace_sale_ready": False,
        "promoted_from_candidate_hash": _hash_payload(candidate),
        "diff_report_hash": _hash_payload(diff_report),
        "generated_at": generated_at,
    }


def _promotion_record(
    original: dict[str, Any],
    candidate: dict[str, Any],
    diff_report: dict[str, Any],
    promoted: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """candidate promotion record payload를 만든다."""
    change_summary = diff_report["change_summary"]
    return {
        "$schema": "https://cambrian.local/schemas/candidate_promotion_record_v0_1.schema.json",
        "schema_version": "0.1",
        "record_kind": "candidate_promotion_record_v0_1",
        "generated_by": PROMOTER_NAME,
        "generated_at": generated_at,
        "agent_id": promoted["files"]["agent.json"]["agent_id"],
        "promotion_status": "promoted_private_version",
        "source": {
            "original_pack_hash": _hash_payload(original),
            "candidate_pack_hash": _hash_payload(candidate),
            "diff_report_hash": _hash_payload(diff_report),
            "promoted_pack_hash": _hash_payload(promoted),
            "candidate_diff_status": diff_report["diff_status"],
        },
        "gate": {
            "user_command_required": True,
            "auto_promote": False,
            "source_diff_report_required": True,
            "output_overwrite_blocked": True,
        },
        "proof_boundary": {
            "uses_runtime_evidence": False,
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "marketplace_sale_ready": False,
        },
        "applied_change_summary": {
            "changed_path_count": change_summary["changed_path_count"],
            "changed_files": change_summary["changed_files"],
            "approved_recommendation_ids": change_summary["approved_decision_ids"],
            "deferred_or_rejected_recommendation_ids": change_summary["deferred_or_rejected_decision_ids"],
        },
        "outputs": {
            "promoted_pack_kind": promoted["package_kind"],
            "promotion_metadata_kind": promoted["promotion_metadata"]["metadata_kind"],
            "candidate_metadata_removed": "candidate_metadata" not in promoted,
            "private_visibility": promoted["files"]["manifest.json"]["marketplace"]["visibility"] == "private",
        },
    }


def _validate_output_paths(
    source_paths: set[Path],
    pack_output_path: Path | None,
    record_output_path: Path | None,
) -> str:
    """출력 경로가 입력 또는 서로를 덮어쓰지 않는지 확인한다."""
    output_paths = [path.resolve() for path in [pack_output_path, record_output_path] if path]
    if any(path in source_paths for path in output_paths):
        return "출력 경로가 입력 파일과 같습니다."
    if len(output_paths) != len(set(output_paths)):
        return "promoted pack과 promotion record 출력 경로가 같습니다."
    return ""


def _replace_candidate_notice(items: list[str]) -> None:
    """후보 상태 문구를 private version 승격 문구로 바꾼다."""
    try:
        index = items.index(CANDIDATE_NOTICE)
    except ValueError:
        if PROMOTED_NOTICE not in items:
            items.append(PROMOTED_NOTICE)
        return
    items[index] = PROMOTED_NOTICE


def _hash_payload(payload: Any) -> str:
    """정렬된 JSON payload의 sha256 해시를 만든다."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
