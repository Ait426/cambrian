import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import build_release
from scripts.smoke_external_alpha_release_bundle import (
    ExternalAlphaBundleSmokeError,
    _smoke_receipt,
    smoke_release_bundle,
    verify_bundle_smoke_receipt_file,
    verify_bundle_smoke_receipt_payload,
)


ROOT = Path(__file__).resolve().parents[1]


def _release_verify_result() -> dict:
    return {
        "status": "pass",
        "archive_sha256": "a" * 64,
        "file_count": 72,
        "release_version": "0.1.0-alpha",
        "diagnostics_status": "pass",
        "diagnostics_safe_to_share": True,
        "browser_wrapper": {
            "status": "pass",
            "script": "verify_agent_platform_browser_flow.py",
            "mode": "help_only",
        },
        "batch_rehearsal": {"status": "pass"},
        "dispatch_execution_policy": {
            "script_sends_to_recipient": False,
            "script_sends_copy_paste_message": False,
            "manual_operator_dispatch_required": True,
            "max_recipients_per_record": 1,
            "records_private_sha256_only": True,
        },
    }


def test_external_alpha_bundle_smoke_receipt_accepts_safe_payload() -> None:
    payload = _smoke_receipt(_release_verify_result())

    verify_bundle_smoke_receipt_payload(payload)
    assert payload["status"] == "pass"
    assert payload["safe_to_share"] is True
    assert payload["privacy"]["absolute_paths_included"] is False
    assert payload["claim_boundaries"]["sale_ready"] is False


def test_external_alpha_bundle_smoke_receipt_rejects_unsafe_policy() -> None:
    result = _release_verify_result()
    result["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    payload = _smoke_receipt(result)

    with pytest.raises(ExternalAlphaBundleSmokeError, match="manual_dispatch_policy_locked"):
        verify_bundle_smoke_receipt_payload(payload)


def test_external_alpha_bundle_smoke_runs_on_built_zip(tmp_path: Path) -> None:
    build_result = build_release(tmp_path)
    receipt_path = tmp_path / "external-alpha-bundle-smoke.json"

    receipt = smoke_release_bundle(
        zip_path=Path(build_result["zip_path"]),
        manifest_path=Path(build_result["manifest_path"]),
        receipt_path=receipt_path,
    )

    assert receipt["status"] == "pass"
    assert receipt["release_bundle"]["archive_sha256"] == build_result["archive_sha256"]
    assert receipt_path.is_file()
    assert verify_bundle_smoke_receipt_file(receipt_path)["status"] == "pass"


def test_external_alpha_bundle_smoke_cli_verifies_receipt(tmp_path: Path) -> None:
    payload = _smoke_receipt(_release_verify_result())
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/smoke_external_alpha_release_bundle.py", "--verify-receipt", str(receipt_path)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "external_alpha_release_bundle_smoke_v0_1" in result.stdout
