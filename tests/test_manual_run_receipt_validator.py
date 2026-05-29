import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from tools.validate_manual_run_receipt import validate_manual_run_receipt


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RECEIPT = ROOT / "web" / "assets" / "document-organizer.manual-run-receipt.json"
VALIDATOR = ROOT / "tools" / "validate_manual_run_receipt.py"
MANUAL_RUN_RECEIPT_SCHEMA = ROOT / "schemas" / "manual_run_receipt_v0_1.schema.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_manual_run_receipt_schema_is_valid() -> None:
    schema = _read_json(MANUAL_RUN_RECEIPT_SCHEMA)

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["receipt_kind"]["const"] == "manual_run_receipt_v0_1"
    assert schema["properties"]["runner_mode"]["const"] == "manual_no_api"
    assert schema["properties"]["privacy"]["properties"]["api_key_collected"]["const"] is False
    assert schema["properties"]["proof_boundary"]["properties"]["proof_claim_allowed"]["const"] is False
    assert schema["properties"]["proof_boundary"]["properties"]["success_rate_claim_allowed"]["const"] is False


def test_validate_manual_run_receipt_passes_sample_receipt() -> None:
    report = validate_manual_run_receipt(SAMPLE_RECEIPT)

    assert report["validator"] == "manual_run_receipt_validator_v0_1"
    assert report["status"] == "pass"
    assert report["agent_id"] == "document-organizer"
    assert not report["errors"]
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert any(check["name"] == "proof_claim_blocked" for check in report["checks"])
    assert any(check["name"] == "evolution_requires_user_approval" for check in report["checks"])


def test_validate_manual_run_receipt_blocks_fake_proof(tmp_path: Path) -> None:
    receipt = deepcopy(_read_json(SAMPLE_RECEIPT))
    receipt["proof_boundary"]["proof_claim_allowed"] = True
    receipt["proof_boundary"]["success_rate_claim_allowed"] = True
    receipt["proof_boundary"]["marketplace_sale_ready"] = True
    broken_path = tmp_path / "fake-proof.manual-run-receipt.json"
    _write_json(broken_path, receipt)

    report = validate_manual_run_receipt(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "receipt_schema" for error in report["errors"])
    assert any(error["code"] == "proof_claim_blocked" for error in report["errors"])


def test_validate_manual_run_receipt_blocks_raw_data_storage(tmp_path: Path) -> None:
    receipt = deepcopy(_read_json(SAMPLE_RECEIPT))
    receipt["privacy"]["stores_raw_inputs"] = True
    receipt["privacy"]["api_key_collected"] = True
    receipt["input_summary"]["stores_raw_input"] = True
    broken_path = tmp_path / "raw-data.manual-run-receipt.json"
    _write_json(broken_path, receipt)

    report = validate_manual_run_receipt(broken_path)

    assert report["status"] == "fail"
    assert any(error["code"] == "receipt_schema" for error in report["errors"])
    assert any(error["code"] == "privacy_keeps_raw_data_out" for error in report["errors"])


def test_validate_manual_run_receipt_cli_outputs_json_report() -> None:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(SAMPLE_RECEIPT), "--pretty"],
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
    assert report["validator"] == "manual_run_receipt_validator_v0_1"


def test_sample_manual_run_receipt_contains_no_raw_text_or_secret_claims() -> None:
    receipt = _read_json(SAMPLE_RECEIPT)
    combined = json.dumps(receipt, ensure_ascii=False)

    assert receipt["input_summary"]["stores_raw_input"] is False
    assert receipt["output_summary"]["stores_raw_output"] is False
    assert receipt["privacy"]["stores_raw_inputs"] is False
    assert receipt["privacy"]["stores_raw_outputs"] is False
    assert receipt["privacy"]["stores_secrets"] is False
    assert receipt["privacy"]["api_key_collected"] is False
    assert receipt["proof_boundary"]["proof_claim_allowed"] is False
    assert "password" not in combined.lower()
    assert "api_key_value" not in combined.lower()
