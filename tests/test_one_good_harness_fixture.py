from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.smoke_one_good_harness_fixture import (
    FIXTURE_DIR,
    FIXTURE_ROOT,
    OneGoodHarnessReplayError,
    replay_one_good_harness_missing_evidence_fixture,
    replay_one_good_harness_fixture,
    verify_one_good_harness_fixture_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_EXPECTATIONS = {
    "python_auth_service": [
        "README.md",
        "pyproject.toml",
        "src/auth_service.py",
        "tests/test_auth_service.py",
        "fixtures/job_request.txt",
        "fixtures/interview_answers.yaml",
        "fixtures/ai_reply_analysis.yaml",
        "fixtures/ai_reply_missing_evidence.yaml",
    ],
    "python_invoice_rules": [
        "README.md",
        "pyproject.toml",
        "src/invoice_rules.py",
        "tests/test_invoice_rules.py",
        "fixtures/job_request.txt",
        "fixtures/interview_answers.yaml",
        "fixtures/ai_reply_analysis.yaml",
    ],
}


def test_one_good_harness_fixtures_are_safe_to_commit() -> None:
    for fixture_name, expected in FIXTURE_EXPECTATIONS.items():
        fixture_dir = FIXTURE_ROOT / fixture_name
        for rel_path in expected:
            assert (fixture_dir / rel_path).is_file()

        combined = "\n".join((fixture_dir / rel_path).read_text(encoding="utf-8") for rel_path in expected)
        assert ".env" not in combined
        assert "api_key" not in combined.lower()
        assert "password" not in combined.lower()
        assert "BEGIN PRIVATE KEY" not in combined


def test_one_good_harness_default_fixture_replay_writes_share_safe_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "one-good-harness-fixture-replay-receipt.json"

    result = replay_one_good_harness_fixture(receipt_path=receipt_path, timeout=90)
    payload = verify_one_good_harness_fixture_receipt_file(receipt_path)

    _assert_share_safe_pass_receipt(result, payload, tmp_path, "python_auth_service")


def test_one_good_harness_second_fixture_replay_writes_share_safe_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "one-good-harness-python-invoice-rules-replay-receipt.json"

    result = replay_one_good_harness_fixture(
        fixture_dir=FIXTURE_ROOT / "python_invoice_rules",
        receipt_path=receipt_path,
        timeout=90,
    )
    payload = verify_one_good_harness_fixture_receipt_file(receipt_path)

    _assert_share_safe_pass_receipt(result, payload, tmp_path, "python_invoice_rules")


def test_one_good_harness_missing_evidence_replay_writes_share_safe_hold_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "one-good-harness-missing-evidence-hold-receipt.json"

    result = replay_one_good_harness_missing_evidence_fixture(receipt_path=receipt_path, timeout=90)
    payload = verify_one_good_harness_fixture_receipt_file(receipt_path)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert result["verdict"] == "ONE_GOOD_HARNESS_HOLD_REPLAYED"
    assert payload["status"] == "hold"
    assert payload["safe_to_share"] is True
    assert payload["provider_api_called_by_cambrian"] is False
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["public_proof_claim_allowed"] is False
    assert payload["sale_ready"] is False
    checks = payload["checks"]
    assert isinstance(checks, dict)
    assert checks["reply_evidence_incomplete"] is True
    assert checks["missing_evidence_reported"] is True
    assert checks["validation_commands_ran"] is True
    assert checks["trust_gate_not_verified"] is True
    assert checks["verdict_hold"] is True
    assert checks["unchecked_risk_recorded"] is True
    negative_proof = payload["negative_proof"]
    assert isinstance(negative_proof, dict)
    assert negative_proof["fake_pass_blocked"] is True
    assert negative_proof["evaluator_verdict"] == "hold"
    assert negative_proof["trust_gate_status"] != "verified"
    assert "risk_boundary_check" in negative_proof["missing_evidence"]
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized


def _assert_share_safe_pass_receipt(
    result: dict[str, object],
    payload: dict[str, object],
    tmp_path: Path,
    fixture_name: str,
) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)

    assert result["verdict"] == "ONE_GOOD_HARNESS_REPLAYED"
    assert payload["status"] == "pass"
    assert payload["safe_to_share"] is True
    fixture = payload["fixture"]
    assert isinstance(fixture, dict)
    assert fixture["name"] == fixture_name
    assert fixture["workdir_included"] is False
    checks = payload["checks"]
    assert isinstance(checks, dict)
    assert checks["all_steps_passed"] is True
    assert checks["source_hashes_unchanged"] is True
    assert checks["reply_evidence_accepted"] is True
    assert checks["validation_passed"] is True
    assert checks["validation_trust_verified"] is True
    assert checks["job_completed_with_pass_verdict"] is True
    capabilities = payload["capabilities_verified"]
    assert isinstance(capabilities, dict)
    assert capabilities["harness_engineering_design_review_dry_run"] is True
    assert capabilities["job_complete_and_verdict"] is True
    assert payload["provider_api_called_by_cambrian"] is False
    assert payload["source_code_modified_by_cambrian"] is False
    assert payload["public_proof_claim_allowed"] is False
    assert payload["sale_ready"] is False
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized


def test_one_good_harness_fixture_receipt_rejects_tampering(tmp_path: Path) -> None:
    receipt_path = tmp_path / "one-good-harness-fixture-replay-receipt.json"
    replay_one_good_harness_fixture(receipt_path=receipt_path, timeout=90)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["checks"]["source_hashes_unchanged"] = False
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(OneGoodHarnessReplayError):
        verify_one_good_harness_fixture_receipt_file(tampered)
