import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import DISPATCH_EXECUTION_POLICY, RELEASE_SLUG
from scripts.check_external_alpha_send_ready import (
    SEND_READY_JSON_NAME,
    SEND_READY_MD_NAME,
    SendReadyError,
    _send_ready_body_sha256,
    _send_ready_checks,
    _send_ready_payload,
    check_send_ready,
    verify_send_ready_file,
)
from scripts.prepare_external_alpha_handoff import verify_handoff_file
from scripts.verify_external_alpha_release import verify_shareable_receipt_file


ROOT = Path(__file__).resolve().parents[1]
SEND_READY_SCRIPT = ROOT / "scripts" / "check_external_alpha_send_ready.py"


def test_external_alpha_send_ready_outputs_go(tmp_path: Path) -> None:
    result = check_send_ready(tmp_path)
    json_path = Path(result["send_ready_json"])
    md_path = Path(result["send_ready_md"])

    assert result["verdict"] == "GO"
    assert json_path.name == SEND_READY_JSON_NAME
    assert md_path.name == SEND_READY_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_send_ready_v0_1"
    assert payload["status"] == "ready_to_send"
    assert payload["verdict"] == "GO"
    assert payload["safe_to_share"] is True
    assert isinstance(payload["send_ready_body_sha256"], str)
    assert len(payload["send_ready_body_sha256"]) == 64
    assert payload["send_ready_body_sha256"] == _send_ready_body_sha256(payload)
    assert all(payload["send_ready_checks"].values())
    assert payload["send_ready_checks"]["send_ready_body_hash_matched"] is True
    assert payload["send_ready_checks"]["handoff_verified_standalone"] is True
    assert payload["send_ready_checks"]["receipt_verified_standalone"] is True
    assert payload["send_ready_checks"]["handoff_receipt_body_matches_current_receipt"] is True
    assert payload["send_ready_checks"]["recipient_ack_request_present"] is True
    assert payload["send_ready_checks"]["dispatch_execution_policy_matched"] is True
    assert payload["send_ready_checks"]["dispatch_manual_only_policy"] is True
    assert payload["send_ready_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["send_ready_checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["send_ready_checks"]["copy_paste_message_mentions_quickstart"] is True
    assert payload["send_ready_checks"]["copy_paste_message_mentions_agent_prompt"] is True
    assert payload["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY
    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}
    assert set(chain_by_kind) == {"release_zip", "handoff_json", "receipt_json", "send_ready_json"}
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["handoff_json"]["sha256"] == payload["handoff"]["body_sha256"]
    assert chain_by_kind["receipt_json"]["sha256"] == payload["receipt"]["body_sha256"]
    assert chain_by_kind["send_ready_json"]["sha256"] == payload["send_ready_body_sha256"]
    assert payload["send_ready_checks"]["artifact_chain_complete"] is True
    assert payload["send_ready_checks"]["artifact_chain_hashes_present"] is True
    assert payload["send_ready_checks"]["artifact_chain_release_hash_matched"] is True
    assert payload["send_ready_checks"]["artifact_chain_handoff_hash_matched"] is True
    assert payload["send_ready_checks"]["artifact_chain_receipt_hash_matched"] is True
    assert payload["send_ready_checks"]["artifact_chain_send_ready_hash_matched"] is True
    assert payload["release"]["zip_file"] == f"{RELEASE_SLUG}.zip"
    assert payload["release"]["archive_sha256"] == result["archive_sha256"]
    assert payload["handoff"]["file"] == "cambrian-agent-platform-external-alpha-handoff.json"
    assert isinstance(payload["handoff"]["body_sha256"], str)
    assert len(payload["handoff"]["body_sha256"]) == 64
    assert payload["handoff"]["verified_standalone"] is True
    assert payload["receipt"]["verified_standalone"] is True
    assert payload["checks"]["handoff_body_hash_matched"] is True
    assert payload["checks"]["handoff_checks_true"] is True
    assert payload["checks"]["receipt_body_hash_matched"] is True
    assert payload["checks"]["handoff_receipt_body_matches_current_receipt"] is True
    assert payload["checks"]["receipt_checks_true"] is True
    assert payload["checks"]["receipt_verified_checks_true"] is True
    assert payload["checks"]["dispatch_execution_policy_matched"] is True
    assert payload["checks"]["dispatch_manual_only_policy"] is True
    assert payload["checks"]["dispatch_one_recipient_policy"] is True
    assert payload["checks"]["dispatch_private_hash_only_policy"] is True
    assert all(payload["checks"].values())
    assert verify_send_ready_file(json_path)["send_ready_body_sha256"] == payload["send_ready_body_sha256"]
    assert "copy_paste_message" in payload["send_to_recipient"]
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in payload["copy_paste_message"]
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in payload["copy_paste_message"]
    assert ".env" in payload["do_not_share"]
    assert "raw AI reply" in payload["do_not_share"]
    assert "Attachment: cambrian-agent-platform-external-alpha.zip" in payload["copy_paste_message"]
    assert "Do not send" in payload["copy_paste_message"]
    assert "CONFIRMED" in payload["copy_paste_message"]
    assert "reply only" in payload["copy_paste_message"]
    assert "raw screenshots" in payload["copy_paste_message"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Send Ready" in markdown
    assert "verdict: GO" in markdown
    assert "send-ready body sha256" in markdown
    assert "handoff body sha256" in markdown
    assert "Artifact Chain" in markdown
    assert "release_zip" in markdown
    assert "send_ready_json" in markdown
    assert "handoff verified standalone: True" in markdown
    assert "receipt verified standalone: True" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "Operator Next Action" in markdown
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in markdown
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_send_ready_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(SEND_READY_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha send-ready" in output
    assert "verdict      : GO" in output
    assert (tmp_path / SEND_READY_MD_NAME).is_file()
    assert (tmp_path / SEND_READY_JSON_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / SEND_READY_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_send_ready_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_send_ready(tmp_path)
    send_ready_path = Path(result["send_ready_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(SEND_READY_SCRIPT), "--verify-send-ready", str(send_ready_path)],
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
    assert "[PASS] external alpha send-ready verification" in verify_output
    assert "verdict: GO" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-send-ready.json"
    tampered = json.loads(send_ready_path.read_text(encoding="utf-8"))
    tampered["release"]["archive_sha256"] = "0" * 64
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(SEND_READY_SCRIPT), "--verify-send-ready", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "send-ready body hash does not match" in tampered_result.stdout + tampered_result.stderr

    chain_tampered_path = tmp_path / "tampered-send-ready-chain.json"
    chain_tampered = json.loads(send_ready_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(SEND_READY_SCRIPT), "--verify-send-ready", str(chain_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert chain_tampered_result.returncode == 1
    assert "send-ready safety checks do not match the current body" in (
        chain_tampered_result.stdout + chain_tampered_result.stderr
    )

    policy_tampered_path = tmp_path / "tampered-send-ready-policy.json"
    policy_tampered = json.loads(send_ready_path.read_text(encoding="utf-8"))
    policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["send_ready_body_sha256"] = _send_ready_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["send_ready_body_sha256"]
    policy_tampered["send_ready_checks"] = _send_ready_checks(policy_tampered)
    policy_tampered_path.write_text(
        json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    policy_tampered_result = subprocess.run(
        [sys.executable, str(SEND_READY_SCRIPT), "--verify-send-ready", str(policy_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert policy_tampered_result.returncode == 1
    assert "dispatch_manual_only_policy" in policy_tampered_result.stdout + policy_tampered_result.stderr


def test_external_alpha_send_ready_rejects_stale_handoff_receipt_reference(tmp_path: Path) -> None:
    result = check_send_ready(tmp_path)
    handoff = verify_handoff_file(Path(result["handoff_json"]))
    receipt = verify_shareable_receipt_file(Path(result["receipt_json"]))
    stale_receipt = dict(receipt)
    stale_receipt["receipt_body_sha256"] = "0" * 64

    with pytest.raises(SendReadyError):
        _send_ready_payload(handoff, stale_receipt)
