import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.prepare_external_alpha_private_pilot_workspace import (
    PRIVATE_WORKSPACE_RECEIPT_NAME,
    PrivatePilotWorkspaceError,
    prepare_private_pilot_workspace,
    verify_private_pilot_workspace_receipt_file,
)


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_WORKSPACE_SCRIPT = ROOT / "scripts" / "prepare_external_alpha_private_pilot_workspace.py"


def test_external_alpha_private_pilot_workspace_creates_templates_and_share_safe_receipt(tmp_path: Path) -> None:
    assert ".cambrian/" in (ROOT / ".gitignore").read_text(encoding="utf-8")

    workspace = tmp_path / "private-pilot"
    result = prepare_private_pilot_workspace(workspace)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["status"] == "pass"
    assert result["verdict"] == "PRIVATE_WORKSPACE_SCAFFOLDED"
    assert receipt_path.name == PRIVATE_WORKSPACE_RECEIPT_NAME
    assert (workspace / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"
    assert (workspace / "README_PRIVATE.md").is_file()

    for name in [
        "recipient-private.txt",
        "operator-dispatch-note-private.md",
        "recipient-ack-private.txt",
        "pilot-feedback-private.md",
        "pilot-issue-intake-private.md",
        "operator-decision-note-private.md",
    ]:
        assert (workspace / name).is_file()

    assert payload["schema_version"] == "external_alpha_private_pilot_workspace_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["private_workspace_policy"]["workspace_path_included"] is False
    assert payload["private_workspace_policy"]["raw_private_values_included"] is False
    assert payload["private_workspace_policy"]["created_private_file_count"] == 6
    assert payload["private_workspace_policy"]["gitignore_blocks_private_files"] is True
    assert payload["private_workspace_policy"]["script_sends_to_recipient"] is False
    assert payload["private_workspace_policy"]["records_private_sha256_only"] is True
    assert payload["checks"]["expected_private_templates_created"] is True
    assert payload["checks"]["dispatch_command_uses_private_workspace"] is True
    assert payload["checks"]["post_send_sequence_uses_private_workspace"] is True
    assert payload["checks"]["pre_send_preflight_uses_private_workspace"] is True
    assert payload["checks"]["operator_status_uses_private_workspace"] is True
    assert payload["checks"]["pre_send_sequence_uses_private_workspace"] is True
    assert payload["checks"]["post_send_receipt_verification_present"] is True
    assert payload["checks"]["recipient_checkpoint_uses_private_workspace"] is True
    assert payload["checks"]["pilot_evidence_uses_private_workspace"] is True
    assert payload["checks"]["pilot_decision_uses_private_workspace"] is True
    assert payload["checks"]["pilot_iteration_uses_private_workspace"] is True
    assert all(payload["checks"].values())
    assert verify_private_pilot_workspace_receipt_file(receipt_path)[
        "private_workspace_receipt_body_sha256"
    ] == payload["private_workspace_receipt_body_sha256"]

    commands = payload["command_templates"]
    assert "python scripts/prepare_external_alpha_private_pilot_workspace.py" in commands["prepare_workspace"]
    assert "python scripts/check_external_alpha_first_recipient_send_preflight.py" in commands["pre_send_preflight"]
    assert "--workspace-dir <private-workspace>" in commands["pre_send_preflight"]
    assert "python scripts/check_external_alpha_first_recipient_operator_status.py" in commands["operator_status"]
    assert "--workspace-dir <private-workspace>" in commands["operator_status"]
    assert "python scripts/check_external_alpha_first_recipient_pre_send_sequence.py" in commands["pre_send_sequence"]
    assert "--workspace-dir <private-workspace>" in commands["pre_send_sequence"]
    assert "--private-workspace-dir <private-workspace>" in commands["record_dispatch"]
    assert "--require-preflight-receipt" in commands["record_dispatch"]
    assert "--workspace-dir <private-workspace>" in commands["record_post_send_sequence"]
    assert "check_external_alpha_first_recipient_post_send_sequence.py" in commands["record_post_send_sequence"]
    assert "--verify-receipt <private-workspace>" in commands["verify_post_send_sequence"]
    assert "--private-workspace-dir <private-workspace>" in commands["record_recipient_checkpoint"]
    assert "--require-preflight-receipt" in commands["record_recipient_checkpoint"]
    assert "--private-workspace-dir <private-workspace>" in commands["record_pilot_evidence"]
    assert "--private-workspace-dir <private-workspace>" in commands["record_pilot_decision"]
    assert "--private-workspace-dir <private-workspace>" in commands["record_pilot_iteration"]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "Recipient identifier/contact goes here" not in serialized
    assert "Keep raw feedback here" not in serialized


def test_external_alpha_private_pilot_workspace_refuses_unsafe_targets(tmp_path: Path) -> None:
    with pytest.raises(PrivatePilotWorkspaceError, match="dist"):
        prepare_private_pilot_workspace(ROOT / "dist" / "private-pilot")

    workspace = tmp_path / "private-pilot"
    prepare_private_pilot_workspace(workspace)

    with pytest.raises(PrivatePilotWorkspaceError, match="already has files"):
        prepare_private_pilot_workspace(workspace)


def test_external_alpha_private_pilot_workspace_cli_passes_and_verifies(tmp_path: Path) -> None:
    workspace = tmp_path / "private-pilot"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [sys.executable, str(PRIVATE_WORKSPACE_SCRIPT), "--workspace-dir", str(workspace)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha private pilot workspace" in output
    assert "PRIVATE_WORKSPACE_SCAFFOLDED" in output
    assert (workspace / PRIVATE_WORKSPACE_RECEIPT_NAME).is_file()

    verify_result = subprocess.run(
        [
            sys.executable,
            str(PRIVATE_WORKSPACE_SCRIPT),
            "--verify-receipt",
            str(workspace / PRIVATE_WORKSPACE_RECEIPT_NAME),
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
    assert "[PASS] external alpha private pilot workspace receipt verification" in verify_output
