import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.promote_candidate_pack import CandidatePromotionError, promote_candidate_pack_with_record
from tools.validate_agent_pack import validate_agent_pack
from tools.validate_candidate_promotion_record import validate_candidate_promotion_record


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PACK = ROOT / "web" / "assets" / "document-organizer.agent-pack.json"
SAMPLE_CANDIDATE = ROOT / "web" / "assets" / "document-organizer.candidate.agent-pack.json"
SAMPLE_DIFF_REPORT = ROOT / "web" / "assets" / "document-organizer.candidate-diff-report.json"
SAMPLE_PROMOTED = ROOT / "web" / "assets" / "document-organizer.promoted.agent-pack.json"
SAMPLE_PROMOTION_RECORD = ROOT / "web" / "assets" / "document-organizer.candidate-promotion-record.json"
PROMOTER = ROOT / "tools" / "promote_candidate_pack.py"
VALIDATOR = ROOT / "tools" / "validate_candidate_promotion_record.py"
AGENT_CONTRACT_SCHEMA = ROOT / "schemas" / "agent_contract_v0_1.schema.json"
AGENT_PACK_BUNDLE_SCHEMA = ROOT / "schemas" / "agent_pack_bundle_v0_1.schema.json"
CANDIDATE_PROMOTION_RECORD_SCHEMA = ROOT / "schemas" / "candidate_promotion_record_v0_1.schema.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assert_promotion_metadata(promoted: dict) -> None:
    metadata = promoted["promotion_metadata"]

    assert promoted["generated_by"] == "tools/promote_candidate_pack.py"
    assert "candidate_metadata" not in promoted
    assert metadata["metadata_kind"] == "promoted_agent_pack_metadata_v0_1"
    assert metadata["source_candidate_metadata_kind"] == "candidate_agent_pack_metadata_v0_1"
    assert metadata["source_candidate_generated_by"] == "tools/generate_candidate_pack.py"
    assert metadata["source_diff_report_kind"] == "candidate_diff_report_v0_1"
    assert metadata["promotion_status"] == "promoted_private_version"
    assert metadata["candidate_apply_status_before_promotion"] == "candidate_not_applied"
    assert metadata["user_command_required"] is True
    assert metadata["auto_promote"] is False
    assert metadata["approved_decision_ids"] == ["decision_1", "decision_2"]
    assert metadata["approved_recommendation_ids"] == ["evo_1", "evo_2"]
    assert metadata["proof_claim_allowed"] is False
    assert metadata["marketplace_sale_ready"] is False
    assert metadata["generated_at"] == "2026-05-10T00:00:00Z"


def test_agent_pack_schema_allows_private_promotion() -> None:
    bundle_schema = _read_json(AGENT_PACK_BUNDLE_SCHEMA)
    agent_schema = _read_json(AGENT_CONTRACT_SCHEMA)
    record_schema = _read_json(CANDIDATE_PROMOTION_RECORD_SCHEMA)

    Draft202012Validator.check_schema(bundle_schema)
    Draft202012Validator.check_schema(agent_schema)
    Draft202012Validator.check_schema(record_schema)
    assert "tools/promote_candidate_pack.py" in bundle_schema["properties"]["generated_by"]["enum"]
    assert "promotion_metadata" in bundle_schema["properties"]
    assert bundle_schema["$defs"]["promotion_metadata"]["properties"]["promotion_status"]["const"] == "promoted_private_version"
    assert bundle_schema["$defs"]["promotion_metadata"]["properties"]["auto_promote"]["const"] is False
    assert "evolution_promoted" in agent_schema["properties"]["provenance"]["items"]["properties"]["kind"]["enum"]
    assert record_schema["properties"]["gate"]["properties"]["auto_promote"]["const"] is False
    assert record_schema["properties"]["proof_boundary"]["properties"]["proof_claim_allowed"]["const"] is False


def test_promote_candidate_pack_creates_promoted_pack_and_record() -> None:
    promoted, record = promote_candidate_pack_with_record(
        SAMPLE_PACK,
        SAMPLE_CANDIDATE,
        SAMPLE_DIFF_REPORT,
        generated_at="2026-05-10T00:00:00Z",
    )

    _assert_promotion_metadata(promoted)
    assert any(item["kind"] == "evolution_promoted" for item in promoted["files"]["agent.json"]["provenance"])
    assert promoted["files"]["manifest.json"]["marketplace"]["sale_ready"] is False
    assert promoted["files"]["manifest.json"]["marketplace"]["proof_claim_allowed"] is False
    assert promoted["files"]["manifest.json"]["evidence_status"] == "no_runtime_evidence"
    assert record["record_kind"] == "candidate_promotion_record_v0_1"
    assert record["promotion_status"] == "promoted_private_version"
    assert record["gate"]["user_command_required"] is True
    assert record["gate"]["auto_promote"] is False
    assert record["outputs"]["candidate_metadata_removed"] is True
    assert record["applied_change_summary"]["approved_recommendation_ids"] == ["evo_1", "evo_2"]


def test_promoted_pack_and_record_samples_validate() -> None:
    pack_report = validate_agent_pack(SAMPLE_PROMOTED)
    record_report = validate_candidate_promotion_record(SAMPLE_PROMOTION_RECORD)
    promoted = _read_json(SAMPLE_PROMOTED)

    assert pack_report["status"] == "pass"
    assert record_report["status"] == "pass"
    assert not pack_report["errors"]
    assert not record_report["errors"]
    assert {check["status"] for check in pack_report["checks"]} == {"pass"}
    assert {check["status"] for check in record_report["checks"]} == {"pass"}
    _assert_promotion_metadata(promoted)


def test_promote_candidate_pack_rejects_hash_mismatch(tmp_path: Path) -> None:
    broken = deepcopy(_read_json(SAMPLE_DIFF_REPORT))
    broken["source"]["candidate_pack_hash"] = "sha256:" + "0" * 64
    broken_path = tmp_path / "bad.candidate-diff-report.json"
    _write_json(broken_path, broken)

    with pytest.raises(CandidatePromotionError, match="candidate pack hash"):
        promote_candidate_pack_with_record(SAMPLE_PACK, SAMPLE_CANDIDATE, broken_path)


def test_promote_candidate_pack_cli_writes_outputs(tmp_path: Path) -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    pack_output = tmp_path / "promoted.agent-pack.json"
    record_output = tmp_path / "candidate-promotion-record.json"

    result = subprocess.run(
        [
            sys.executable,
            str(PROMOTER),
            str(SAMPLE_PACK),
            str(SAMPLE_CANDIDATE),
            str(SAMPLE_DIFF_REPORT),
            "--pretty",
            "--generated-at",
            "2026-05-10T00:00:00Z",
            "--pack-output",
            str(pack_output),
            "--record-output",
            str(record_output),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    promoted = _read_json(pack_output)
    _assert_promotion_metadata(promoted)
    assert validate_agent_pack(pack_output)["status"] == "pass"
    assert validate_candidate_promotion_record(record_output)["status"] == "pass"


def test_promote_candidate_pack_cli_rejects_overwriting_inputs() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [
            sys.executable,
            str(PROMOTER),
            str(SAMPLE_PACK),
            str(SAMPLE_CANDIDATE),
            str(SAMPLE_DIFF_REPORT),
            "--pack-output",
            str(SAMPLE_CANDIDATE),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "입력 파일과 같습니다" in result.stdout


def test_candidate_promotion_record_validator_cli_outputs_json() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(SAMPLE_PROMOTION_RECORD), "--pretty"],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "pass"
    assert report["validator"] == "candidate_promotion_record_validator_v0_1"
