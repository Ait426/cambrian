import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.generate_candidate_pack import CandidatePackError, generate_candidate_pack
from tools.validate_agent_pack import validate_agent_pack


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PACK = ROOT / "web" / "assets" / "document-organizer.agent-pack.json"
SAMPLE_SUGGESTION = ROOT / "web" / "assets" / "document-organizer.evolution-suggestion.json"
SAMPLE_DECISION = ROOT / "web" / "assets" / "document-organizer.evolution-review-decision.json"
SAMPLE_CANDIDATE = ROOT / "web" / "assets" / "document-organizer.candidate.agent-pack.json"
SAMPLE_PROMOTED = ROOT / "web" / "assets" / "document-organizer.promoted.agent-pack.json"
GENERATOR = ROOT / "tools" / "generate_candidate_pack.py"
AGENT_CONTRACT_SCHEMA = ROOT / "schemas" / "agent_contract_v0_1.schema.json"
AGENT_PACK_BUNDLE_SCHEMA = ROOT / "schemas" / "agent_pack_bundle_v0_1.schema.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert_candidate_metadata(candidate: dict) -> None:
    metadata = candidate["candidate_metadata"]

    assert metadata["metadata_kind"] == "candidate_agent_pack_metadata_v0_1"
    assert metadata["source_suggestion_kind"] == "evolution_suggestion_v0_1"
    assert metadata["source_decision_kind"] == "evolution_review_decision_v0_1"
    assert metadata["apply_status"] == "candidate_not_applied"
    assert metadata["auto_apply"] is False
    assert metadata["auto_promote"] is False
    assert metadata["approved_decision_ids"] == ["decision_1", "decision_2"]
    assert metadata["approved_recommendation_ids"] == ["evo_1", "evo_2"]
    assert metadata["deferred_recommendation_ids"] == ["evo_3"]
    assert metadata["rejected_recommendation_ids"] == []
    assert metadata["requires_user_final_review"] is True
    assert metadata["original_pack_preserved"] is True
    assert metadata["generated_at"] == "2026-05-10T00:00:00Z"


def test_agent_pack_schema_allows_candidate_generator_and_provenance() -> None:
    bundle_schema = _read_json(AGENT_PACK_BUNDLE_SCHEMA)
    agent_schema = _read_json(AGENT_CONTRACT_SCHEMA)

    Draft202012Validator.check_schema(bundle_schema)
    Draft202012Validator.check_schema(agent_schema)
    assert "tools/generate_candidate_pack.py" in bundle_schema["properties"]["generated_by"]["enum"]
    assert "candidate_metadata" in bundle_schema["properties"]
    assert bundle_schema["$defs"]["candidate_metadata"]["properties"]["apply_status"]["const"] == "candidate_not_applied"
    assert bundle_schema["$defs"]["candidate_metadata"]["properties"]["auto_apply"]["const"] is False
    assert bundle_schema["$defs"]["candidate_metadata"]["properties"]["auto_promote"]["const"] is False
    assert any(
        rule.get("then", {}).get("required") == ["candidate_metadata"]
        for rule in bundle_schema["allOf"]
    )
    provenance_kind = agent_schema["properties"]["provenance"]["items"]["properties"]["kind"]["enum"]
    assert "evolution_candidate" in provenance_kind


def test_generate_candidate_pack_applies_only_approved_decisions() -> None:
    original = _read_json(SAMPLE_PACK)
    candidate = generate_candidate_pack(
        SAMPLE_PACK,
        SAMPLE_SUGGESTION,
        SAMPLE_DECISION,
        generated_at="2026-05-10T00:00:00Z",
    )

    assert original["generated_by"] == "web/platform/index.html"
    assert candidate["generated_by"] == "tools/generate_candidate_pack.py"
    _assert_candidate_metadata(candidate)
    assert original["files"]["instructions.md"] != candidate["files"]["instructions.md"]
    assert "## 수동 검증 체크리스트" in candidate["files"]["instructions.md"]
    assert "manual_no_api 결과는 proof가 아니며" in "\n".join(candidate["files"]["agent.json"]["known_limits"])
    assert "각 결과 항목은 사용자가 예/아니오로 확인" not in "\n".join(candidate["files"]["agent.json"]["validation_criteria"])
    assert any(
        item["kind"] == "evolution_candidate"
        for item in candidate["files"]["agent.json"]["provenance"]
    )
    assert candidate["files"]["manifest.json"]["marketplace"]["sale_ready"] is False
    assert candidate["files"]["manifest.json"]["marketplace"]["proof_claim_allowed"] is False


def test_generate_candidate_pack_preserves_approved_instruction_proposed_change(
    tmp_path: Path,
) -> None:
    suggestion = deepcopy(_read_json(SAMPLE_SUGGESTION))
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    suggestion["recommendations"].append(
        {
            "id": "evo_4",
            "title": "계약 출력 형식 신호를 instructions에 고정",
            "target": "instructions.md",
            "rationale": "manual_no_api 결과에서 계약 출력 형식 신호가 0/1만 감지됐고 부족 형식은 table입니다.",
            "proposed_change": "instructions.md에 table 출력 형식을 시작 구조와 예시로 고정한다.",
            "risk_level": "medium",
            "acceptance_criteria": [
                "출력 첫 섹션이 계약 출력 형식과 일치한다.",
                "원문 결과를 저장하지 않는다.",
            ],
            "status": "suggested",
        }
    )
    decision["source_suggestion"]["recommendation_count"] = 4
    decision["source_suggestion"]["recommendation_ids"].append("evo_4")
    decision["decisions"].append(
        {
            "id": "decision_4",
            "recommendation_id": "evo_4",
            "target": "instructions.md",
            "decision": "approved",
            "reviewer_note": "표 형식 신호 부족을 후보 instructions에 반영한다.",
            "risk_level": "medium",
        }
    )
    suggestion_path = tmp_path / "format-signal.evolution-suggestion.json"
    decision_path = tmp_path / "format-signal.evolution-review-decision.json"
    _write_json(suggestion_path, suggestion)
    _write_json(decision_path, decision)

    candidate = generate_candidate_pack(
        SAMPLE_PACK,
        suggestion_path,
        decision_path,
        generated_at="2026-05-10T00:00:00Z",
    )
    instructions = candidate["files"]["instructions.md"]

    assert "## 승인된 instructions 진화 제안" in instructions
    assert "계약 출력 형식 신호를 instructions에 고정" in instructions
    assert "table 출력 형식을 시작 구조와 예시로 고정" in instructions
    assert "## 수동 검증 체크리스트" in instructions
    assert "SHOULD_NOT" not in instructions
    assert "evo_4" in candidate["candidate_metadata"]["approved_recommendation_ids"]


def test_generate_candidate_pack_from_promoted_private_version_removes_promotion_metadata(tmp_path: Path) -> None:
    candidate = generate_candidate_pack(
        SAMPLE_PROMOTED,
        SAMPLE_SUGGESTION,
        SAMPLE_DECISION,
        generated_at="2026-05-10T00:00:00Z",
    )

    assert candidate["generated_by"] == "tools/generate_candidate_pack.py"
    assert "promotion_metadata" not in candidate
    _assert_candidate_metadata(candidate)
    candidate_path = tmp_path / "candidate-from-promoted.agent-pack.json"
    _write_json(candidate_path, candidate)
    assert validate_agent_pack(candidate_path)["status"] == "pass"


def test_candidate_pack_sample_validates_with_existing_pack_validator() -> None:
    report = validate_agent_pack(SAMPLE_CANDIDATE)
    check_names = {check["name"] for check in report["checks"]}
    sample = _read_json(SAMPLE_CANDIDATE)

    assert report["status"] == "pass"
    assert report["agent_id"] == "document-organizer"
    assert not report["errors"]
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert {
        "candidate_metadata_required",
        "candidate_not_applied",
        "candidate_has_approved_decision",
        "candidate_requires_final_review",
    }.issubset(check_names)
    _assert_candidate_metadata(sample)


def test_candidate_pack_generator_rejects_overwriting_original_path() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            str(SAMPLE_PACK),
            str(SAMPLE_SUGGESTION),
            str(SAMPLE_DECISION),
            "--output",
            str(SAMPLE_PACK),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "원본 pack과 같습니다" in result.stdout


def test_candidate_pack_generator_rejects_agent_id_mismatch(tmp_path: Path) -> None:
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    decision["source_suggestion"]["agent_id"] = "other-agent"
    decision_path = tmp_path / "other.evolution-review-decision.json"
    _write_json(decision_path, decision)

    with pytest.raises(CandidatePackError, match="agent_id"):
        generate_candidate_pack(SAMPLE_PACK, SAMPLE_SUGGESTION, decision_path)


def test_candidate_pack_generator_rejects_without_approved_decisions(tmp_path: Path) -> None:
    decision = deepcopy(_read_json(SAMPLE_DECISION))
    for item in decision["decisions"]:
        item["decision"] = "deferred"
        item["reviewer_note"] = "후보 pack 생성 전에 추가 검토가 필요하다."
    decision_path = tmp_path / "no-approved.evolution-review-decision.json"
    _write_json(decision_path, decision)

    with pytest.raises(CandidatePackError, match="approved decision"):
        generate_candidate_pack(SAMPLE_PACK, SAMPLE_SUGGESTION, decision_path)


def test_candidate_pack_generator_cli_writes_candidate_file(tmp_path: Path) -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    output_path = tmp_path / "candidate.agent-pack.json"

    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            str(SAMPLE_PACK),
            str(SAMPLE_SUGGESTION),
            str(SAMPLE_DECISION),
            "--pretty",
            "--generated-at",
            "2026-05-10T00:00:00Z",
            "--output",
            str(output_path),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    candidate = _read_json(output_path)
    assert candidate["generated_by"] == "tools/generate_candidate_pack.py"
    _assert_candidate_metadata(candidate)
    assert validate_agent_pack(output_path)["status"] == "pass"
