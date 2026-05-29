import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_external_alpha_pilot_iteration import check_pilot_iteration
from scripts.smoke_external_alpha_private_pilot_workspace import (
    PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME,
    PrivateWorkspaceRehearsalError,
    smoke_private_pilot_workspace,
    verify_private_workspace_rehearsal_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
REHEARSAL_SCRIPT = ROOT / "scripts" / "smoke_external_alpha_private_pilot_workspace.py"


def test_external_alpha_private_workspace_rehearsal_writes_share_safe_receipt(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)

    result = smoke_private_pilot_workspace(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "REHEARSAL_PASS"
    assert receipt_path.name == PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME
    assert payload["schema_version"] == "external_alpha_private_pilot_workspace_rehearsal_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["real_private_workspace"] is False
    assert payload["real_private_data_entered"] is False
    assert payload["release"]["archive_sha256"] == result["archive_sha256"]
    assert payload["scaffold_receipt"]["file"] == "external-alpha-private-pilot-workspace-scaffold-receipt.json"
    assert payload["scaffold_receipt"]["safe_to_share"] is True
    assert payload["scaffold_receipt"]["created_private_file_count"] == 6
    assert payload["scaffold_receipt"]["workspace_path_included"] is False
    assert payload["scaffold_receipt"]["raw_private_values_included"] is False
    assert payload["checks"]["release_archive_hash_present"] is True
    assert payload["checks"]["scaffold_receipt_passed"] is True
    assert payload["checks"]["scaffold_omits_workspace_path"] is True
    assert payload["checks"]["scaffold_omits_raw_private_values"] is True
    assert payload["checks"]["dispatch_command_private_workspace_only"] is True
    assert payload["checks"]["checkpoint_command_private_workspace_only"] is True
    assert payload["checks"]["evidence_command_private_workspace_only"] is True
    assert payload["checks"]["decision_command_private_workspace_only"] is True
    assert payload["checks"]["iteration_command_private_workspace_only"] is True
    assert all(payload["checks"].values())
    assert verify_private_workspace_rehearsal_receipt_file(receipt_path)[
        "private_workspace_rehearsal_receipt_body_sha256"
    ] == payload["private_workspace_rehearsal_receipt_body_sha256"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "Recipient identifier/contact goes here" not in serialized
    assert "Keep raw feedback here" not in serialized
    assert "PRIVATE - DO NOT SHARE OR COMMIT" not in serialized


def test_external_alpha_private_workspace_rehearsal_requires_release_manifest(tmp_path: Path) -> None:
    with pytest.raises(PrivateWorkspaceRehearsalError, match="release manifest is required"):
        smoke_private_pilot_workspace(tmp_path)


def test_external_alpha_private_workspace_rehearsal_cli_passes_and_verifies(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)
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
        timeout=60,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha private workspace rehearsal" in output
    assert "verdict: REHEARSAL_PASS" in output
    assert (tmp_path / PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(REHEARSAL_SCRIPT),
            "--verify-receipt",
            str(tmp_path / PRIVATE_WORKSPACE_REHEARSAL_RECEIPT_NAME),
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
    assert "[PASS] external alpha private workspace rehearsal verification" in verify_output


def test_external_alpha_private_workspace_rehearsal_rejects_tampering(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)
    result = smoke_private_pilot_workspace(tmp_path)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["real_private_data_entered"] = True
    receipt_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(PrivateWorkspaceRehearsalError):
        verify_private_workspace_rehearsal_receipt_file(receipt_path)
