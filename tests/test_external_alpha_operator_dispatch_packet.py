import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.check_external_alpha_pilot_iteration import check_pilot_iteration
from scripts.prepare_external_alpha_operator_dispatch_packet import (
    PACKET_JSON_NAME,
    PACKET_MD_NAME,
    OperatorDispatchPacketError,
    _packet_body_sha256,
    _packet_checks,
    prepare_operator_dispatch_packet,
    verify_operator_dispatch_packet_file,
)


ROOT = Path(__file__).resolve().parents[1]
PACKET_SCRIPT = ROOT / "scripts" / "prepare_external_alpha_operator_dispatch_packet.py"


def test_external_alpha_operator_dispatch_packet_outputs_send_once_packet(tmp_path: Path) -> None:
    check_pilot_iteration(tmp_path)

    result = prepare_operator_dispatch_packet(tmp_path, refresh_chain=False)
    json_path = Path(result["packet_json"])
    md_path = Path(result["packet_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert result["status"] == "pass"
    assert result["verdict"] == "READY_TO_SEND_ONE"
    assert json_path.name == PACKET_JSON_NAME
    assert md_path.name == PACKET_MD_NAME
    assert payload["schema_version"] == "external_alpha_operator_dispatch_packet_v0_1"
    assert payload["status"] == "pass"
    assert payload["verdict"] == "READY_TO_SEND_ONE"
    assert payload["safe_to_share"] is True
    assert payload["release"]["zip_file"] == f"{RELEASE_SLUG}.zip"
    assert payload["operator_send_once"]["attach_zip_file"] == f"{RELEASE_SLUG}.zip"
    assert payload["operator_send_once"]["max_recipients"] == 1
    assert payload["operator_send_once"]["script_sends_to_recipient"] is False
    assert payload["operator_send_once"]["manual_operator_dispatch_required"] is True
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in payload["operator_send_once"][
        "copy_paste_message"
    ]
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in payload["operator_send_once"]["copy_paste_message"]
    assert "EXTERNAL_ALPHA_SUPPORT_PACKET.md" in payload["operator_send_once"]["copy_paste_message"]
    assert "raw AI reply" in payload["operator_send_once"]["copy_paste_message"]
    assert "prepare_external_alpha_private_pilot_workspace.py" in payload["before_manual_send"][
        "prepare_private_workspace_command"
    ]
    assert "--workspace-dir <private-workspace-dir>" in payload["before_manual_send"][
        "prepare_private_workspace_command"
    ]
    assert "prepare_external_alpha_first_recipient_send_workspace.py" in payload["before_manual_send"][
        "prepare_first_recipient_workspace_command"
    ]
    assert f"--operator-packet dist\\{PACKET_JSON_NAME}" in payload["before_manual_send"][
        "prepare_first_recipient_workspace_command"
    ]
    assert "check_external_alpha_first_recipient_send_preflight.py" in payload["before_manual_send"][
        "pre_send_preflight_command"
    ]
    assert f"--operator-packet dist\\{PACKET_JSON_NAME}" in payload["before_manual_send"][
        "pre_send_preflight_command"
    ]
    assert payload["before_manual_send"]["expected_preflight_receipt"] == (
        "external-alpha-first-recipient-send-preflight-receipt.json"
    )
    assert "audit_external_alpha_operator_send_bypass.py" in payload["before_manual_send"][
        "operator_bypass_audit_command"
    ]
    assert "--workspace-dir <private-workspace-dir>" in payload["before_manual_send"][
        "operator_bypass_audit_command"
    ]
    assert payload["before_manual_send"]["expected_operator_bypass_audit_receipt"] == (
        "cambrian-agent-platform-external-alpha-operator-send-bypass-audit.json"
    )
    assert payload["before_manual_send"]["final_send_chain_audit_command"] == (
        "python scripts/audit_external_alpha_send_chain.py"
    )
    assert "--skip-operator-bypass-audit" not in payload["before_manual_send"]["final_send_chain_audit_command"]
    assert "check_external_alpha_first_recipient_manual_send_go.py" in payload["before_manual_send"][
        "manual_send_go_command"
    ]
    assert "--workspace-dir <private-workspace-dir>" in payload["before_manual_send"]["manual_send_go_command"]
    assert payload["before_manual_send"]["expected_manual_send_go_receipt"] == (
        "external-alpha-first-recipient-manual-send-go-receipt.json"
    )
    assert "check_external_alpha_first_recipient_pre_send_sequence.py" in payload["before_manual_send"][
        "pre_send_sequence_command"
    ]
    assert "--workspace-dir <private-workspace-dir>" in payload["before_manual_send"]["pre_send_sequence_command"]
    assert payload["before_manual_send"]["expected_pre_send_sequence_receipt"] == (
        "external-alpha-first-recipient-pre-send-sequence-receipt.json"
    )
    assert "check_external_alpha_first_recipient_operator_status.py" in payload["before_manual_send"][
        "operator_status_command"
    ]
    assert "--workspace-dir <private-workspace-dir>" in payload["before_manual_send"]["operator_status_command"]
    assert payload["before_manual_send"]["expected_operator_status_receipt"] == (
        "external-alpha-first-recipient-operator-status-receipt.json"
    )
    assert payload["after_manual_send"]["private_workspace_receipt"] == (
        "external-alpha-private-pilot-workspace-scaffold-receipt.json"
    )
    assert "--private-workspace-dir <private-workspace-dir>" in payload["after_manual_send"]["record_command"]
    assert "--require-preflight-receipt" in payload["after_manual_send"]["record_command"]
    assert "check_external_alpha_first_recipient_post_send_sequence.py" in payload["after_manual_send"][
        "post_send_sequence_command"
    ]
    assert "--workspace-dir <private-workspace-dir>" in payload["after_manual_send"]["post_send_sequence_command"]
    assert "--sent-at-utc <sent-at-utc>" in payload["after_manual_send"]["post_send_sequence_command"]
    assert payload["after_manual_send"]["expected_post_send_sequence_receipt"] == (
        "external-alpha-first-recipient-post-send-sequence-receipt.json"
    )
    assert "--private-workspace-dir <private-workspace-dir>" in payload["after_manual_send"]["then_checkpoint_command"]
    assert "--require-preflight-receipt" in payload["after_manual_send"]["then_checkpoint_command"]
    assert "--recipient-private-file" not in payload["after_manual_send"]["record_command"]
    assert "--recipient-ack-private-file" not in payload["after_manual_send"]["then_checkpoint_command"]
    assert payload["after_manual_send"]["expected_recipient_receipt"] == "external_alpha_builder_gold_path_share_receipt.json"
    assert payload["required_before_send"]["final_audit"]["chain_depth"] >= 12
    assert payload["required_before_send"]["post_send_checkpoint_rehearsal"]["file"] == (
        "cambrian-agent-platform-external-alpha-post-send-rehearsal-receipt.json"
    )
    assert payload["required_before_send"]["post_send_checkpoint_rehearsal"]["verdict"] == "REHEARSAL_PASS"
    assert payload["required_before_send"]["post_send_checkpoint_rehearsal"]["real_recipient_evidence"] is False
    assert payload["required_before_send"]["post_send_checkpoint_rehearsal"]["preflight_generated_by_real_gate"] is True
    assert payload["required_before_send"]["post_send_checkpoint_rehearsal"]["operator_note_template_used"] is True
    assert (
        payload["required_before_send"]["post_send_checkpoint_rehearsal"][
            "operator_note_template_preflight_contract"
        ]
        is True
    )
    assert payload["required_before_send"]["pilot_learning_loop_rehearsal"]["file"] == (
        "cambrian-agent-platform-external-alpha-pilot-learning-rehearsal-receipt.json"
    )
    assert payload["required_before_send"]["pilot_learning_loop_rehearsal"]["verdict"] == "REHEARSAL_PASS"
    assert payload["required_before_send"]["pilot_learning_loop_rehearsal"]["real_pilot_evidence"] is False
    assert payload["required_before_send"]["pilot_learning_loop_rehearsal"]["iteration_verdict"] == "PATCH_BEFORE_NEXT"
    assert payload["required_before_send"]["private_workspace_scaffold_rehearsal"]["file"] == (
        "cambrian-agent-platform-external-alpha-private-workspace-rehearsal-receipt.json"
    )
    assert payload["required_before_send"]["private_workspace_scaffold_rehearsal"]["verdict"] == "REHEARSAL_PASS"
    assert payload["required_before_send"]["private_workspace_scaffold_rehearsal"]["real_private_workspace"] is False
    assert payload["required_before_send"]["private_workspace_scaffold_rehearsal"]["real_private_data_entered"] is False
    assert payload["checks"]["post_send_rehearsal_passed"] is True
    assert payload["checks"]["post_send_rehearsal_matches_release"] is True
    assert payload["checks"]["post_send_rehearsal_no_real_recipient_claim"] is True
    assert payload["checks"]["post_send_rehearsal_real_preflight_gate"] is True
    assert payload["checks"]["post_send_rehearsal_operator_note_template_contract"] is True
    assert payload["checks"]["pilot_learning_rehearsal_passed"] is True
    assert payload["checks"]["pilot_learning_rehearsal_matches_release"] is True
    assert payload["checks"]["pilot_learning_rehearsal_no_real_pilot_claim"] is True
    assert payload["checks"]["pilot_learning_rehearsal_patch_before_next"] is True
    assert payload["checks"]["private_workspace_rehearsal_passed"] is True
    assert payload["checks"]["private_workspace_rehearsal_matches_release"] is True
    assert payload["checks"]["private_workspace_rehearsal_no_real_private_claim"] is True
    assert payload["checks"]["private_workspace_rehearsal_scaffold_safe"] is True
    assert payload["checks"]["final_audit_ready_to_send_one"] is True
    assert payload["checks"]["bundle_smoke_matches_release"] is True
    assert payload["checks"]["copy_paste_message_ascii_only"] is True
    assert payload["checks"]["copy_paste_message_mojibake_free"] is True
    assert payload["checks"]["copy_paste_message_names_quickstart"] is True
    assert payload["operator_dispatch_packet_checks"]["copy_paste_message_names_quickstart"] is True
    assert payload["operator_dispatch_packet_checks"]["copy_paste_message_ascii_only"] is True
    assert payload["operator_dispatch_packet_checks"]["copy_paste_message_mojibake_free"] is True
    assert payload["operator_dispatch_packet_checks"]["private_workspace_rehearsal_hash_present"] is True
    assert payload["operator_dispatch_packet_checks"]["private_workspace_rehearsal_no_real_private_claim"] is True
    assert payload["operator_dispatch_packet_checks"]["private_workspace_rehearsal_release_hash_matched"] is True
    assert payload["operator_dispatch_packet_checks"]["private_workspace_scaffold_receipt_hash_present"] is True
    assert payload["operator_dispatch_packet_checks"]["post_send_rehearsal_hash_present"] is True
    assert payload["operator_dispatch_packet_checks"]["post_send_rehearsal_no_real_recipient_claim"] is True
    assert payload["operator_dispatch_packet_checks"]["post_send_rehearsal_release_hash_matched"] is True
    assert payload["operator_dispatch_packet_checks"]["post_send_rehearsal_real_preflight_gate"] is True
    assert (
        payload["operator_dispatch_packet_checks"]["post_send_rehearsal_operator_note_template_contract"]
        is True
    )
    assert payload["operator_dispatch_packet_checks"]["pilot_learning_rehearsal_hash_present"] is True
    assert payload["operator_dispatch_packet_checks"]["pilot_learning_rehearsal_no_real_pilot_claim"] is True
    assert payload["operator_dispatch_packet_checks"]["pilot_learning_rehearsal_release_hash_matched"] is True
    assert payload["operator_dispatch_packet_checks"]["pilot_learning_rehearsal_patch_before_next"] is True
    assert payload["operator_dispatch_packet_checks"]["private_workspace_scaffold_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["first_recipient_workspace_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["first_recipient_workspace_command_uses_operator_packet"] is True
    assert payload["operator_dispatch_packet_checks"]["pre_send_preflight_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["pre_send_preflight_command_uses_operator_packet"] is True
    assert payload["operator_dispatch_packet_checks"]["pre_send_preflight_receipt_named"] is True
    assert payload["operator_dispatch_packet_checks"]["operator_bypass_audit_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["operator_bypass_audit_receipt_named"] is True
    assert payload["operator_dispatch_packet_checks"]["final_send_chain_audit_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["final_send_chain_audit_no_internal_skip_flag"] is True
    assert payload["operator_dispatch_packet_checks"]["manual_send_go_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["manual_send_go_receipt_named"] is True
    assert payload["operator_dispatch_packet_checks"]["pre_send_sequence_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["pre_send_sequence_receipt_named"] is True
    assert payload["operator_dispatch_packet_checks"]["operator_status_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["operator_status_receipt_named"] is True
    assert payload["operator_dispatch_packet_checks"]["after_send_record_command_requires_preflight"] is True
    assert payload["operator_dispatch_packet_checks"]["after_send_checkpoint_command_requires_preflight"] is True
    assert payload["operator_dispatch_packet_checks"]["post_send_sequence_command_present"] is True
    assert payload["operator_dispatch_packet_checks"]["post_send_sequence_receipt_named"] is True
    assert payload["operator_dispatch_packet_checks"]["private_workspace_receipt_named"] is True
    assert all(payload["checks"].values())
    assert all(payload["operator_dispatch_packet_checks"].values())
    assert verify_operator_dispatch_packet_file(json_path)["operator_dispatch_packet_body_sha256"] == payload[
        "operator_dispatch_packet_body_sha256"
    ]

    assert "Cambrian External Alpha Operator Dispatch Packet" in markdown
    assert "Send Exactly Once" in markdown
    assert "post-send rehearsal real recipient evidence: False" in markdown
    assert "post-send rehearsal real preflight gate: True" in markdown
    assert "post-send rehearsal operator note template contract: True" in markdown
    assert "private workspace rehearsal real private workspace: False" in markdown
    assert "private workspace rehearsal real private data entered: False" in markdown
    assert "pilot learning rehearsal real pilot evidence: False" in markdown
    assert "pilot learning rehearsal iteration verdict: PATCH_BEFORE_NEXT" in markdown
    assert "prepare_external_alpha_private_pilot_workspace.py" in markdown
    assert "prepare_external_alpha_first_recipient_send_workspace.py" in markdown
    assert "check_external_alpha_first_recipient_send_preflight.py" in markdown
    assert "audit_external_alpha_operator_send_bypass.py" in markdown
    assert "audit_external_alpha_send_chain.py" in markdown
    assert "check_external_alpha_first_recipient_manual_send_go.py" in markdown
    assert "check_external_alpha_first_recipient_pre_send_sequence.py" in markdown
    assert "check_external_alpha_first_recipient_operator_status.py" in markdown
    assert "check_external_alpha_first_recipient_post_send_sequence.py" in markdown
    assert "--skip-operator-bypass-audit" not in markdown
    assert f"{RELEASE_SLUG}.zip" in markdown
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in markdown
    assert "external_alpha_builder_gold_path_share_receipt.json" in markdown
    assert "CONFIRMED" in markdown
    assert "�" not in markdown
    assert "?뺤" not in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_operator_dispatch_packet_cli_passes_and_verifies(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(PACKET_SCRIPT), "--output-dir", str(tmp_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[PASS] external alpha operator dispatch packet" in output
    assert "verdict: READY_TO_SEND_ONE" in output
    assert (tmp_path / PACKET_JSON_NAME).is_file()
    assert (tmp_path / PACKET_MD_NAME).is_file()

    verify_result = subprocess.run(
        [sys.executable, str(PACKET_SCRIPT), "--verify-packet", str(tmp_path / PACKET_JSON_NAME)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )

    verify_output = verify_result.stdout + verify_result.stderr
    assert verify_result.returncode == 0, verify_output
    assert "[PASS] external alpha operator dispatch packet verification" in verify_output
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / PACKET_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_operator_dispatch_packet_rejects_tampering(tmp_path: Path) -> None:
    result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(result["packet_json"])
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    payload["operator_send_once"]["max_recipients"] = 2
    packet_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(OperatorDispatchPacketError):
        verify_operator_dispatch_packet_file(packet_path)


def test_external_alpha_operator_dispatch_packet_rejects_recomputed_command_tampering(tmp_path: Path) -> None:
    result = prepare_operator_dispatch_packet(tmp_path)
    packet_path = Path(result["packet_json"])
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    payload["before_manual_send"]["prepare_first_recipient_workspace_command"] = (
        "python scripts/prepare_external_alpha_first_recipient_send_workspace.py "
        "--workspace-dir <private-workspace-dir>"
    )
    payload["operator_dispatch_packet_body_sha256"] = _packet_body_sha256(payload)
    payload["operator_dispatch_packet_checks"] = _packet_checks(payload)
    packet_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        OperatorDispatchPacketError,
        match="first_recipient_workspace_command_uses_operator_packet",
    ):
        verify_operator_dispatch_packet_file(packet_path)
