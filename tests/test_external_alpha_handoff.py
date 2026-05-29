import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.build_external_alpha_release import DISPATCH_EXECUTION_POLICY, RELEASE_SLUG
from scripts.prepare_external_alpha_handoff import (
    HANDOFF_JSON_NAME,
    HANDOFF_MD_NAME,
    RECEIPT_NAME,
    _handoff_body_sha256,
    _handoff_checks,
    prepare_handoff,
    verify_handoff_file,
)
from scripts.verify_external_alpha_release import verify_shareable_receipt_file


ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SCRIPT = ROOT / "scripts" / "prepare_external_alpha_handoff.py"


def test_external_alpha_handoff_is_shareable(tmp_path: Path) -> None:
    result = prepare_handoff(tmp_path)
    md_path = Path(result["handoff_md"])
    json_path = Path(result["handoff_json"])
    receipt_path = Path(result["receipt_json"])

    assert result["status"] == "ready_to_send"
    assert md_path.name == HANDOFF_MD_NAME
    assert json_path.name == HANDOFF_JSON_NAME
    assert receipt_path.name == RECEIPT_NAME
    assert md_path.is_file()
    assert json_path.is_file()
    assert receipt_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    receipt = verify_shareable_receipt_file(receipt_path)
    assert payload["schema_version"] == "external_alpha_send_handoff_v0_1"
    assert payload["status"] == "ready_to_send"
    assert payload["safe_to_share"] is True
    assert isinstance(payload["handoff_body_sha256"], str)
    assert len(payload["handoff_body_sha256"]) == 64
    assert payload["handoff_body_sha256"] == _handoff_body_sha256(payload)
    assert all(payload["handoff_checks"].values())
    assert payload["handoff_checks"]["handoff_body_hash_matched"] is True
    assert payload["handoff_checks"]["verify_handoff_command_present"] is True
    assert payload["handoff_checks"]["recipient_ack_request_present"] is True
    assert payload["handoff_checks"]["dispatch_execution_policy_matched"] is True
    assert payload["handoff_checks"]["dispatch_manual_only_policy"] is True
    assert payload["handoff_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["handoff_checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["handoff_checks"]["copy_paste_message_mentions_quickstart"] is True
    assert payload["handoff_checks"]["copy_paste_message_mentions_agent_prompt"] is True
    assert payload["handoff_checks"]["recipient_steps_mentions_quickstart"] is True
    assert payload["handoff_checks"]["recipient_steps_mentions_agent_prompt"] is True
    assert payload["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY
    assert payload["release"]["zip_file"] == f"{RELEASE_SLUG}.zip"
    assert payload["release"]["archive_sha256"] == result["archive_sha256"]
    assert payload["receipt"]["file"] == RECEIPT_NAME
    assert payload["receipt"]["body_sha256"] == result["receipt_body_sha256"]
    assert payload["receipt"]["body_sha256"] == receipt["receipt_body_sha256"]
    assert payload["receipt"]["verified_standalone"] is True
    assert payload["verified"]["zip_sha256"] is True
    assert payload["verified"]["manifest_file_hashes"] is True
    assert payload["verified"]["support_packet"] is True
    assert payload["verified"]["receipt_body_hash"] is True
    assert payload["verified"]["receipt_standalone"] is True
    assert payload["verified"]["diagnostics_privacy"] is True
    assert verify_handoff_file(json_path)["handoff_body_sha256"] == payload["handoff_body_sha256"]
    assert "START_CAMBRIAN_AGENT_PLATFORM.bat" in " ".join(payload["recipient_steps"])
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in payload["send_to_recipient"]
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in " ".join(payload["recipient_steps"])
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in payload["copy_paste_message"]
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in payload["send_to_recipient"]
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in " ".join(payload["recipient_steps"])
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in payload["copy_paste_message"]
    assert "external_alpha_release_verification_receipt.json" in payload["support_files"]
    assert "external_alpha_diagnostics.json" in payload["support_files"]
    assert ".env" in payload["do_not_share"]
    assert "raw AI reply" in payload["do_not_share"]
    assert "docs/launch/PILOT_ISSUE_INTAKE.md" in payload["pilot_templates"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Send Handoff" in markdown
    assert "Copy Paste Message" in markdown
    assert "CONFIRMED" in markdown
    assert "reply only" in markdown
    assert "raw screenshots" in markdown
    assert f"Attachment: {RELEASE_SLUG}.zip" in markdown
    assert "sha256:" in markdown
    assert "provider API key" in markdown
    assert "does not require" in markdown
    assert "Do not send" in markdown
    assert RECEIPT_NAME in markdown
    assert "receipt body sha256" in markdown
    assert "handoff body sha256" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in markdown
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "python scripts/prepare_external_alpha_handoff.py --verify-handoff cambrian-agent-platform-external-alpha-handoff.json" in markdown
    assert "python scripts/verify_external_alpha_release.py --verify-receipt external_alpha_release_verification_receipt.json" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_handoff_cli_generates_outputs(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(HANDOFF_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha handoff" in output
    assert (tmp_path / HANDOFF_MD_NAME).is_file()
    assert (tmp_path / HANDOFF_JSON_NAME).is_file()
    assert (tmp_path / RECEIPT_NAME).is_file()
    assert "receipt_json:" in output
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / HANDOFF_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_handoff_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = prepare_handoff(tmp_path)
    handoff_path = Path(result["handoff_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(HANDOFF_SCRIPT), "--verify-handoff", str(handoff_path)],
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
    assert "[PASS] external alpha handoff verification" in verify_output
    assert "handoff:" in verify_output
    assert "receipt:" in verify_output

    tampered_path = tmp_path / "tampered-handoff.json"
    tampered = json.loads(handoff_path.read_text(encoding="utf-8"))
    tampered["release"]["archive_sha256"] = "0" * 64
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(HANDOFF_SCRIPT), "--verify-handoff", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "handoff body hash does not match" in tampered_result.stdout + tampered_result.stderr

    policy_tampered_path = tmp_path / "tampered-handoff-policy.json"
    policy_tampered = json.loads(handoff_path.read_text(encoding="utf-8"))
    policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["handoff_body_sha256"] = _handoff_body_sha256(policy_tampered)
    policy_tampered["handoff_checks"] = _handoff_checks(policy_tampered)
    policy_tampered_path.write_text(
        json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    policy_tampered_result = subprocess.run(
        [sys.executable, str(HANDOFF_SCRIPT), "--verify-handoff", str(policy_tampered_path)],
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
