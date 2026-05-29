import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.audit_external_alpha_operator_send_bypass import (
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
    OperatorSendBypassAuditError,
    _audit_payload,
    _source_requires_preflight,
    audit_operator_send_bypass,
    verify_operator_send_bypass_audit_file,
    verify_operator_send_bypass_audit_payload,
)
from scripts.prepare_external_alpha_first_recipient_send_workspace import (
    PRIVATE_SEND_RUNBOOK_NAME,
    prepare_first_recipient_send_workspace,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_external_alpha_operator_send_bypass.py"


def test_external_alpha_operator_send_bypass_audit_passes_and_is_share_safe(tmp_path: Path) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    workspace = tmp_path / "private-send-workspace"
    prepare_first_recipient_send_workspace(
        workspace,
        operator_packet_path=Path(packet_result["packet_json"]),
    )

    result = audit_operator_send_bypass(tmp_path, workspace_dir=workspace)
    receipt_path = Path(result["receipt_json"])
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    source_names = {item["source"] for item in payload["audited_sources"]}

    assert result["status"] == "pass"
    assert result["verdict"] == "NO_OPERATOR_PREFLIGHT_BYPASS"
    assert receipt_path.name == OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME
    assert payload["schema_version"] == "external_alpha_operator_send_bypass_audit_v0_1"
    assert payload["safe_to_share"] is True
    assert payload["release"]["archive_sha256"] == result["archive_sha256"]
    assert payload["operator_packet"]["body_sha256"]
    assert payload["policy"]["pre_send_preflight_required_before_dispatch_record"] is True
    assert payload["policy"]["pre_send_preflight_required_before_recipient_checkpoint"] is True
    assert payload["policy"]["raw_private_values_in_receipt"] is False
    assert payload["policy"]["local_paths_in_receipt"] is False
    assert payload["checks"]["operator_packet_preflight_command_present"] is True
    assert payload["checks"]["operator_packet_record_command_requires_preflight"] is True
    assert payload["checks"]["operator_packet_checkpoint_command_requires_preflight"] is True
    assert payload["checks"]["release_manifest_preflight_command_present"] is True
    assert payload["checks"]["private_runbook_checked_when_present"] is True
    assert payload["checks"]["all_operator_dispatch_commands_require_preflight"] is True
    assert payload["operator_send_bypass_audit_checks"]["audited_sources_all_pass"] is True
    assert all(payload["checks"].values())
    assert all(payload["operator_send_bypass_audit_checks"].values())
    assert verify_operator_send_bypass_audit_file(receipt_path)[
        "operator_send_bypass_audit_body_sha256"
    ] == payload["operator_send_bypass_audit_body_sha256"]

    assert {
        "operator_dispatch_packet_json",
        "release_manifest_doc",
        "first_recipient_workspace_script",
        "private_workspace_script",
        "private_send_runbook",
    }.issubset(source_names)

    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert PRIVATE_SEND_RUNBOOK_NAME not in serialized
    assert "Recipient identifier/contact goes here" not in serialized
    assert "Record the private channel" not in serialized
    assert "<private-send-channel>" not in serialized

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    verify_result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-receipt", str(receipt_path)],
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
    assert "[PASS] external alpha operator send bypass audit verification" in verify_output


def test_external_alpha_operator_send_bypass_audit_rejects_private_dispatch_without_preflight(
    tmp_path: Path,
) -> None:
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    operator_packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    source_texts = {
        "operator_dispatch_packet_json": json.dumps(operator_packet, ensure_ascii=False),
        "release_manifest_doc": (
            "python scripts/check_external_alpha_first_recipient_send_preflight.py "
            "--workspace-dir <private-workspace-dir>\n"
            "python scripts/check_external_alpha_dispatch_record.py "
            "--private-workspace-dir <private-workspace-dir> "
            "--sent-at-utc <sent-at-utc> --require-preflight-receipt\n"
            "python scripts/check_external_alpha_recipient_checkpoint.py "
            "--private-workspace-dir <private-workspace-dir> "
            "--sent-at-utc <sent-at-utc> --require-preflight-receipt\n"
        ),
        "first_recipient_workspace_script": (
            "python scripts/check_external_alpha_dispatch_record.py "
            "--private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>\n"
        ),
        "private_workspace_script": (
            "python scripts/check_external_alpha_dispatch_record.py "
            "--private-workspace-dir <private-workspace-dir> "
            "--sent-at-utc <sent-at-utc> --require-preflight-receipt\n"
            "python scripts/check_external_alpha_recipient_checkpoint.py "
            "--private-workspace-dir <private-workspace-dir> "
            "--sent-at-utc <sent-at-utc> --require-preflight-receipt\n"
        ),
        "private_send_runbook": "",
    }

    payload = _audit_payload(
        operator_packet=operator_packet,
        source_texts=source_texts,
        private_runbook_present=False,
    )

    assert payload["status"] == "fail"
    assert payload["verdict"] == "OPERATOR_PREFLIGHT_BYPASS_FOUND"
    assert payload["checks"]["all_operator_dispatch_commands_require_preflight"] is False

    with pytest.raises(OperatorSendBypassAuditError, match="did not pass"):
        verify_operator_send_bypass_audit_payload(payload)


def test_source_requires_preflight_only_for_private_workspace_dispatches() -> None:
    assert _source_requires_preflight("no_dispatch", "python scripts/check_external_alpha_pilot_ready.py")
    assert _source_requires_preflight(
        "safe",
        (
            "python scripts/check_external_alpha_dispatch_record.py "
            "--private-workspace-dir <private-workspace-dir> "
            "--sent-at-utc <sent-at-utc> --require-preflight-receipt"
        ),
    )
    assert not _source_requires_preflight(
        "bypass",
        (
            "python scripts/check_external_alpha_dispatch_record.py "
            "--private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>"
        ),
    )
    assert _source_requires_preflight(
        "checkpoint_safe",
        (
            "python scripts/check_external_alpha_recipient_checkpoint.py "
            "--private-workspace-dir <private-workspace-dir> "
            "--sent-at-utc <sent-at-utc> --require-preflight-receipt"
        ),
    )
    assert not _source_requires_preflight(
        "checkpoint_bypass",
        (
            "python scripts/check_external_alpha_recipient_checkpoint.py "
            "--private-workspace-dir <private-workspace-dir> --sent-at-utc <sent-at-utc>"
        ),
    )
