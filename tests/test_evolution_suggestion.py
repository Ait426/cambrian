import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.generate_evolution_suggestion import EvolutionSuggestionError, generate_evolution_suggestion
from tools.validate_evolution_suggestion import validate_evolution_suggestion


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PACK = ROOT / "web" / "assets" / "document-organizer.agent-pack.json"
SAMPLE_RECEIPT = ROOT / "web" / "assets" / "document-organizer.manual-run-receipt.json"
SAMPLE_SUGGESTION = ROOT / "web" / "assets" / "document-organizer.evolution-suggestion.json"
GENERATOR = ROOT / "tools" / "generate_evolution_suggestion.py"
VALIDATOR = ROOT / "tools" / "validate_evolution_suggestion.py"
EVOLUTION_SUGGESTION_SCHEMA = ROOT / "schemas" / "evolution_suggestion_v0_1.schema.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_evolution_suggestion_schema_is_valid() -> None:
    schema = _read_json(EVOLUTION_SUGGESTION_SCHEMA)

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["suggestion_kind"]["const"] == "evolution_suggestion_v0_1"
    assert "tools/generate_evolution_suggestion.py" in schema["properties"]["generated_by"]["enum"]
    assert "web/runner/index.html" in schema["properties"]["generated_by"]["enum"]
    assert schema["properties"]["proposal_status"]["const"] == "draft_requires_user_approval"
    assert schema["properties"]["approval_gate"]["properties"]["auto_apply"]["const"] is False
    assert schema["properties"]["approval_gate"]["properties"]["auto_promote"]["const"] is False
    assert schema["properties"]["proof_boundary"]["properties"]["proof_claim_allowed"]["const"] is False
    source_receipt = schema["properties"]["source_receipt"]["properties"]
    assert source_receipt["eligible_for_suggestion"]["const"] is True
    assert source_receipt["requires_user_approval"]["const"] is True


def test_generate_evolution_suggestion_from_pack_and_receipt() -> None:
    suggestion = generate_evolution_suggestion(
        SAMPLE_PACK,
        SAMPLE_RECEIPT,
        generated_at="2026-05-10T00:00:00Z",
    )
    schema = _read_json(EVOLUTION_SUGGESTION_SCHEMA)

    Draft202012Validator(schema).validate(suggestion)
    assert suggestion["suggestion_kind"] == "evolution_suggestion_v0_1"
    assert suggestion["source_agent"]["agent_id"] == "document-organizer"
    assert suggestion["source_receipt"]["receipt_kind"] == "manual_run_receipt_v0_1"
    assert suggestion["source_receipt"]["eligible_for_suggestion"] is True
    assert suggestion["source_receipt"]["requires_user_approval"] is True
    assert suggestion["approval_gate"]["requires_user_approval"] is True
    assert suggestion["approval_gate"]["auto_apply"] is False
    assert suggestion["proof_boundary"]["success_rate_claim_allowed"] is False
    assert suggestion["privacy"]["uses_only_receipt_metadata"] is True
    assert {item["status"] for item in suggestion["recommendations"]} == {"suggested"}


def test_validate_evolution_suggestion_passes_sample() -> None:
    report = validate_evolution_suggestion(SAMPLE_SUGGESTION)

    assert report["validator"] == "evolution_suggestion_validator_v0_1"
    assert report["status"] == "pass"
    assert report["agent_id"] == "document-organizer"
    assert not report["errors"]
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert any(check["name"] == "auto_apply_blocked" for check in report["checks"])
    assert any(check["name"] == "source_receipt_eligible_for_suggestion" for check in report["checks"])


def test_sample_evolution_suggestion_matches_generator_output() -> None:
    sample = _read_json(SAMPLE_SUGGESTION)
    generated = generate_evolution_suggestion(
        SAMPLE_PACK,
        SAMPLE_RECEIPT,
        generated_at=sample["generated_at"],
    )

    assert generated == sample


def test_validate_evolution_suggestion_blocks_auto_apply_and_fake_proof(tmp_path: Path) -> None:
    suggestion = deepcopy(_read_json(SAMPLE_SUGGESTION))
    suggestion["approval_gate"]["auto_apply"] = True
    suggestion["approval_gate"]["auto_promote"] = True
    suggestion["proof_boundary"]["proof_claim_allowed"] = True
    suggestion["proof_boundary"]["success_rate_claim_allowed"] = True
    broken_path = tmp_path / "bad.evolution-suggestion.json"
    _write_json(broken_path, suggestion)

    report = validate_evolution_suggestion(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "suggestion_schema" for error in report["errors"])
    assert any(error["code"] == "auto_apply_blocked" for error in report["errors"])
    assert any(error["code"] == "proof_claim_blocked" for error in report["errors"])


def test_generate_evolution_suggestion_rejects_agent_id_mismatch(tmp_path: Path) -> None:
    receipt = deepcopy(_read_json(SAMPLE_RECEIPT))
    receipt["agent_id"] = "other-agent"
    receipt_path = tmp_path / "other.manual-run-receipt.json"
    _write_json(receipt_path, receipt)

    with pytest.raises(EvolutionSuggestionError, match="agent_id"):
        generate_evolution_suggestion(SAMPLE_PACK, receipt_path)


def test_generate_evolution_suggestion_rejects_ineligible_receipt(tmp_path: Path) -> None:
    receipt = deepcopy(_read_json(SAMPLE_RECEIPT))
    receipt["result_status"] = "result_not_recorded"
    receipt["evolution_signal"]["eligible_for_suggestion"] = False
    receipt_path = tmp_path / "ineligible.manual-run-receipt.json"
    _write_json(receipt_path, receipt)

    with pytest.raises(EvolutionSuggestionError, match="진화 제안 생성 대상"):
        generate_evolution_suggestion(SAMPLE_PACK, receipt_path)


def test_generate_evolution_suggestion_cli_outputs_json() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(GENERATOR), str(SAMPLE_PACK), str(SAMPLE_RECEIPT), "--pretty"],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    suggestion = json.loads(result.stdout)
    assert suggestion["suggestion_kind"] == "evolution_suggestion_v0_1"
    assert suggestion["approval_gate"]["auto_apply"] is False


def test_validate_evolution_suggestion_cli_outputs_json_report() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(SAMPLE_SUGGESTION), "--pretty"],
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
    assert report["validator"] == "evolution_suggestion_validator_v0_1"
