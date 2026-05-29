import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.build_external_alpha_release import DISPATCH_EXECUTION_POLICY, RELEASE_SLUG
from scripts.check_external_alpha_pilot_ready import (
    PILOT_DISPATCH_MD_NAME,
    PILOT_READY_JSON_NAME,
    PILOT_READY_MD_NAME,
    _pilot_ready_body_sha256,
    _pilot_ready_checks,
    check_pilot_ready,
    verify_pilot_ready_file,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT_READY_SCRIPT = ROOT / "scripts" / "check_external_alpha_pilot_ready.py"


def test_external_alpha_pilot_ready_outputs_go(tmp_path: Path) -> None:
    result = check_pilot_ready(tmp_path)
    json_path = Path(result["pilot_ready_json"])
    md_path = Path(result["pilot_ready_md"])
    dispatch_path = Path(result["pilot_dispatch_md"])

    assert result["verdict"] == "GO"
    assert json_path.name == PILOT_READY_JSON_NAME
    assert md_path.name == PILOT_READY_MD_NAME
    assert dispatch_path.name == PILOT_DISPATCH_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()
    assert dispatch_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_pilot_ready_v0_1"
    assert payload["status"] == "pilot_ready"
    assert payload["verdict"] == "GO"
    assert payload["safe_to_share"] is True
    assert isinstance(payload["pilot_ready_body_sha256"], str)
    assert len(payload["pilot_ready_body_sha256"]) == 64
    assert payload["pilot_ready_body_sha256"] == _pilot_ready_body_sha256(payload)
    assert all(payload["pilot_ready_checks"].values())
    assert payload["pilot_ready_checks"]["pilot_ready_body_hash_matched"] is True
    assert payload["pilot_ready_checks"]["send_ready_verified_standalone"] is True
    assert payload["pilot_ready_checks"]["receipt_verified_standalone"] is True
    assert payload["pilot_ready_checks"]["dispatch_recipient_ack_request_present"] is True
    assert payload["pilot_ready_checks"]["dispatch_manual_only_policy"] is True
    assert payload["pilot_ready_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["pilot_ready_checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["pilot_ready_checks"]["dispatch_quickstart_present"] is True
    assert payload["pilot_ready_checks"]["dispatch_agent_prompt_present"] is True
    assert payload["pilot_ready_checks"]["dispatch_execution_policy_matched"] is True
    assert payload["pilot_ready_checks"]["dispatch_execution_policy_manual_only"] is True
    assert payload["pilot_ready_checks"]["dispatch_execution_policy_one_recipient"] is True
    assert payload["pilot_ready_checks"]["dispatch_execution_policy_private_hash_only"] is True
    assert payload["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY
    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}
    assert set(chain_by_kind) == {"release_zip", "handoff_json", "receipt_json", "send_ready_json", "pilot_ready_json"}
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["handoff_json"]["sha256"] == payload["handoff"]["body_sha256"]
    assert chain_by_kind["receipt_json"]["sha256"] == payload["receipt"]["body_sha256"]
    assert chain_by_kind["send_ready_json"]["sha256"] == payload["send_ready"]["body_sha256"]
    assert chain_by_kind["pilot_ready_json"]["file"] == PILOT_READY_JSON_NAME
    assert chain_by_kind["pilot_ready_json"]["sha256"] == payload["pilot_ready_body_sha256"]
    assert payload["pilot_ready_checks"]["artifact_chain_complete"] is True
    assert payload["pilot_ready_checks"]["artifact_chain_hashes_present"] is True
    assert payload["pilot_ready_checks"]["artifact_chain_release_hash_matched"] is True
    assert payload["pilot_ready_checks"]["artifact_chain_handoff_hash_matched"] is True
    assert payload["pilot_ready_checks"]["artifact_chain_receipt_hash_matched"] is True
    assert payload["pilot_ready_checks"]["artifact_chain_send_ready_hash_matched"] is True
    assert payload["pilot_ready_checks"]["artifact_chain_pilot_ready_hash_matched"] is True
    assert all(payload["checks"].values())
    assert payload["checks"]["send_ready_go"] is True
    assert payload["checks"]["pilot_templates_present"] is True
    assert payload["checks"]["issue_intake_privacy_guidance"] is True
    assert payload["checks"]["feedback_storage_guidance"] is True
    assert payload["checks"]["pilot_stop_rule_present"] is True
    assert payload["release"]["zip_file"] == f"{RELEASE_SLUG}.zip"
    assert payload["release"]["archive_sha256"] == result["archive_sha256"]
    assert payload["send_ready"]["file"] == "cambrian-agent-platform-external-alpha-send-ready.json"
    assert payload["handoff"]["file"] == "cambrian-agent-platform-external-alpha-handoff.json"
    assert payload["receipt"]["file"] == "external_alpha_release_verification_receipt.json"
    assert payload["receipt"]["safe_to_share"] is True
    assert "docs/launch/PILOT_ISSUE_INTAKE.md" in payload["pilot_templates"]
    assert "docs/launch/PILOT_FEEDBACK_FORM.md" in payload["pilot_templates"]
    assert "continue" in payload["pilot_decision_thresholds"]
    assert "fix_before_next" in payload["pilot_decision_thresholds"]
    assert "stop_and_redesign" in payload["pilot_decision_thresholds"]
    assert payload["pilot_dispatch"]["target_participants"] == 1
    assert payload["pilot_dispatch"]["timebox_minutes"] == 10
    assert payload["pilot_dispatch"]["execution_policy"] == {
        "script_sends_to_recipient": False,
        "script_sends_copy_paste_message": False,
        "manual_operator_dispatch_required": True,
        "max_recipients_per_pilot": 1,
        "cohort_scaling_allowed": False,
        "records_private_sha256_only_after_send": True,
        "raw_private_content_included": False,
    }
    assert "copy_paste_message" in payload["pilot_dispatch"]["send_to_recipient"]
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in payload["pilot_dispatch"]["send_to_recipient"]
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in payload["pilot_dispatch"]["copy_paste_message"]
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in " ".join(payload["pilot_dispatch"]["recipient_checklist"])
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in payload["pilot_dispatch"]["copy_paste_message"]
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in " ".join(
        payload["pilot_dispatch"]["recipient_checklist"]
    )
    assert "CONFIRMED" in payload["pilot_dispatch"]["copy_paste_message"]
    assert "reply only" in payload["pilot_dispatch"]["copy_paste_message"]
    assert "docs/launch/PILOT_FEEDBACK_FORM.md" in payload["pilot_dispatch"]["collect_after_pilot"]
    assert "docs/launch/PILOT_ISSUE_INTAKE.md" in payload["pilot_dispatch"]["collect_after_pilot"]
    assert verify_pilot_ready_file(json_path)["pilot_ready_body_sha256"] == payload["pilot_ready_body_sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Pilot Ready" in markdown
    assert "verdict: GO" in markdown
    assert "Artifact Chain" in markdown
    assert "pilot_ready_json" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "Pilot Success Criteria" in markdown
    assert "Stop And Redesign" in markdown
    assert "Operator Next Action" in markdown
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in markdown
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in markdown

    dispatch_markdown = dispatch_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Pilot Dispatch" in dispatch_markdown
    assert "Send One First" in dispatch_markdown
    assert "timebox minutes: 10" in dispatch_markdown
    assert "Execution Policy" in dispatch_markdown
    assert "script sends to recipient: False" in dispatch_markdown
    assert "manual operator dispatch required: True" in dispatch_markdown
    assert "max recipients per pilot: 1" in dispatch_markdown
    assert "records private sha256 only after send: True" in dispatch_markdown
    assert "Copy Paste Message" in dispatch_markdown
    assert "CONFIRMED" in dispatch_markdown
    assert "reply only" in dispatch_markdown
    assert "Recipient Checklist" in dispatch_markdown
    assert "Collect After Pilot" in dispatch_markdown
    assert "Stop And Redesign If" in dispatch_markdown
    assert "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in dispatch_markdown
    assert "QUICKSTART_EXTERNAL_ALPHA.md" in dispatch_markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown + dispatch_markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_pilot_ready_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(PILOT_READY_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha pilot-ready" in output
    assert "verdict      : GO" in output
    assert "dispatch_md  :" in output
    assert (tmp_path / PILOT_READY_MD_NAME).is_file()
    assert (tmp_path / PILOT_READY_JSON_NAME).is_file()
    assert (tmp_path / PILOT_DISPATCH_MD_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / PILOT_READY_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_pilot_ready_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_pilot_ready(tmp_path)
    pilot_ready_path = Path(result["pilot_ready_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(PILOT_READY_SCRIPT), "--verify-pilot-ready", str(pilot_ready_path)],
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
    assert "[PASS] external alpha pilot-ready verification" in verify_output
    assert "verdict: GO" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-pilot-ready.json"
    tampered = json.loads(pilot_ready_path.read_text(encoding="utf-8"))
    tampered["release"]["archive_sha256"] = "0" * 64
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(PILOT_READY_SCRIPT), "--verify-pilot-ready", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "pilot-ready" in tampered_result.stdout + tampered_result.stderr

    chain_tampered_path = tmp_path / "tampered-pilot-ready-chain.json"
    chain_tampered = json.loads(pilot_ready_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_READY_SCRIPT), "--verify-pilot-ready", str(chain_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert chain_tampered_result.returncode == 1
    assert "pilot-ready safety checks do not match the current body." in (
        chain_tampered_result.stdout + chain_tampered_result.stderr
    )

    policy_tampered_path = tmp_path / "tampered-pilot-ready-policy.json"
    policy_tampered = json.loads(pilot_ready_path.read_text(encoding="utf-8"))
    policy_tampered["pilot_dispatch"]["execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["pilot_ready_body_sha256"] = _pilot_ready_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["pilot_ready_body_sha256"]
    policy_tampered["pilot_ready_checks"] = _pilot_ready_checks(policy_tampered)
    policy_tampered_path.write_text(json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    policy_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_READY_SCRIPT), "--verify-pilot-ready", str(policy_tampered_path)],
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

    top_policy_tampered_path = tmp_path / "tampered-pilot-ready-top-dispatch-policy.json"
    top_policy_tampered = json.loads(pilot_ready_path.read_text(encoding="utf-8"))
    top_policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    top_policy_tampered["pilot_ready_body_sha256"] = _pilot_ready_body_sha256(top_policy_tampered)
    top_policy_tampered["artifact_chain"][-1]["sha256"] = top_policy_tampered["pilot_ready_body_sha256"]
    top_policy_tampered["pilot_ready_checks"] = _pilot_ready_checks(top_policy_tampered)
    top_policy_tampered_path.write_text(
        json.dumps(top_policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    top_policy_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_READY_SCRIPT), "--verify-pilot-ready", str(top_policy_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert top_policy_tampered_result.returncode == 1
    assert "dispatch_execution_policy_manual_only" in (
        top_policy_tampered_result.stdout + top_policy_tampered_result.stderr
    )
