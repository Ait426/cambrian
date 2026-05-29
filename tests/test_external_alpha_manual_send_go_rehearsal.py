import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet
from scripts.smoke_external_alpha_manual_send_go_rehearsal import (
    MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME,
    ManualSendGoRehearsalError,
    REQUIRED_TRUE_CHECKS,
    _receipt_body_sha256,
    smoke_manual_send_go_rehearsal,
    verify_manual_send_go_rehearsal_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
REHEARSAL_SCRIPT = ROOT / "scripts" / "smoke_external_alpha_manual_send_go_rehearsal.py"


def test_external_alpha_manual_send_go_rehearsal_writes_share_safe_receipt(tmp_path: Path) -> None:
    prepare_operator_dispatch_packet(tmp_path)

    result = smoke_manual_send_go_rehearsal(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "REHEARSAL_PASS"
    assert receipt_path.name == MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_first_recipient_manual_send_go_rehearsal_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["real_manual_send"] is False
    assert payload["real_recipient_evidence"] is False
    assert payload["synthetic_private_values_used"] is True
    assert payload["release"]["archive_sha256"] == result["archive_sha256"]
    assert payload["rehearsed_flow"]["preflight_verdict"] == "FIRST_RECIPIENT_PRE_SEND_READY"
    assert payload["rehearsed_flow"]["operator_bypass_verdict"] == "NO_OPERATOR_PREFLIGHT_BYPASS"
    assert payload["rehearsed_flow"]["manual_send_go_verdict"] == "GO_TO_MANUALLY_SEND_ONE"
    assert payload["rehearsed_flow"]["operator_status_verdict"] == "READY_TO_MANUALLY_SEND_ONE"
    assert payload["rehearsed_flow"]["operator_status_manual_send_go_packet_bound"] is True
    assert payload["rehearsed_flow"]["final_send_chain_verdict"] == "READY_TO_SEND_ONE"
    assert payload["rehearsed_flow"]["final_send_chain_requires_bypass"] is True
    assert payload["private_input_policy"]["stored_private_values"] is False
    assert payload["private_input_policy"]["stored_private_paths"] is False
    assert payload["private_input_policy"]["stored_private_hashes_only"] is True
    assert payload["operator_boundary"]["script_sends_to_recipient"] is False
    assert payload["operator_boundary"]["manual_operator_dispatch_required"] is True
    assert payload["operator_boundary"]["max_recipients"] == 1
    assert payload["checks"]["preflight_ready"] is True
    assert payload["checks"]["operator_bypass_ready"] is True
    assert payload["checks"]["manual_send_go_ready"] is True
    assert payload["checks"]["operator_status_ready_to_send"] is True
    assert payload["checks"]["operator_status_safe_to_share"] is True
    assert payload["checks"]["operator_status_release_hash_matches"] is True
    assert payload["checks"]["operator_status_manual_send_go_packet_bound"] is True
    assert payload["checks"]["manual_go_final_chain_ready"] is True
    assert payload["checks"]["release_hashes_match"] is True
    assert payload["checks"]["operator_note_template_used"] is True
    assert payload["checks"]["operator_note_template_preflight_contract"] is True
    assert payload["checks"]["raw_private_content_omitted"] is True
    assert all(payload["checks"].values())
    assert verify_manual_send_go_rehearsal_receipt_file(receipt_path)[
        "manual_send_go_rehearsal_receipt_body_sha256"
    ] == payload["manual_send_go_rehearsal_receipt_body_sha256"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "MANUAL_SEND_GO_REHEARSAL_PRIVATE_RECIPIENT" not in serialized
    assert "MANUAL_SEND_GO_REHEARSAL_PRIVATE_OPERATOR_NOTE" not in serialized


def test_external_alpha_manual_send_go_rehearsal_requires_operator_packet(tmp_path: Path) -> None:
    with pytest.raises(ManualSendGoRehearsalError, match="release artifacts are required"):
        smoke_manual_send_go_rehearsal(tmp_path)


def test_external_alpha_manual_send_go_rehearsal_cli_passes_and_verifies(tmp_path: Path) -> None:
    prepare_operator_dispatch_packet(tmp_path)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [sys.executable, str(REHEARSAL_SCRIPT), "--output-dir", str(tmp_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=90,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha manual-send GO rehearsal" in output
    assert "verdict: REHEARSAL_PASS" in output
    assert (tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(REHEARSAL_SCRIPT),
            "--verify-receipt",
            str(tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha manual-send GO rehearsal verification" in verify_output


def test_external_alpha_manual_send_go_rehearsal_rejects_tampering(tmp_path: Path) -> None:
    prepare_operator_dispatch_packet(tmp_path)
    result = smoke_manual_send_go_rehearsal(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["real_manual_send"] = True
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ManualSendGoRehearsalError):
        verify_manual_send_go_rehearsal_receipt_file(receipt_path)


def test_external_alpha_manual_send_go_rehearsal_requires_operator_status_ready_check(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    payload = _valid_rehearsal_payload()
    del payload["checks"]["operator_status_ready_to_send"]
    payload["manual_send_go_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ManualSendGoRehearsalError, match="operator_status_ready_to_send"):
        verify_manual_send_go_rehearsal_receipt_file(receipt_path)


def test_external_alpha_manual_send_go_rehearsal_requires_operator_status_ready_verdict(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    payload = _valid_rehearsal_payload()
    payload["rehearsed_flow"]["operator_status_verdict"] = "FILL_PRIVATE_FIELDS"
    payload["manual_send_go_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ManualSendGoRehearsalError, match="operator status is not ready"):
        verify_manual_send_go_rehearsal_receipt_file(receipt_path)


def test_external_alpha_manual_send_go_rehearsal_requires_operator_status_packet_binding(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    payload = _valid_rehearsal_payload()
    payload["rehearsed_flow"]["operator_status_manual_send_go_packet_bound"] = False
    payload["manual_send_go_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ManualSendGoRehearsalError, match="packet binding is not ready"):
        verify_manual_send_go_rehearsal_receipt_file(receipt_path)


def _valid_rehearsal_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "external_alpha_first_recipient_manual_send_go_rehearsal_v0_1",
        "status": "pass",
        "verdict": "REHEARSAL_PASS",
        "safe_to_share": True,
        "real_manual_send": False,
        "real_recipient_evidence": False,
        "synthetic_private_values_used": True,
        "release": {"archive_sha256": "a" * 64},
        "rehearsed_flow": {
            "operator_status_verdict": "READY_TO_MANUALLY_SEND_ONE",
            "operator_status_receipt_body_sha256": "b" * 64,
            "operator_status_manual_send_go_packet_bound": True,
        },
        "checks": {name: True for name in REQUIRED_TRUE_CHECKS},
    }
    payload["manual_send_go_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload
