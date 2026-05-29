import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import DISPATCH_EXECUTION_POLICY, RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import (
    DISPATCH_RECORD_JSON_NAME,
    DISPATCH_RECORD_MD_NAME,
    DispatchRecordError,
    _dispatch_record_body_sha256,
    _dispatch_record_checks,
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.check_external_alpha_first_recipient_send_preflight import (
    PREFLIGHT_RECEIPT_NAME,
    check_first_recipient_send_preflight,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import prepare_operator_dispatch_packet
from scripts.smoke_external_alpha_release_bundle import SMOKE_RECEIPT_NAME, _smoke_receipt


ROOT = Path(__file__).resolve().parents[1]
DISPATCH_RECORD_SCRIPT = ROOT / "scripts" / "check_external_alpha_dispatch_record.py"


def test_external_alpha_dispatch_record_outputs_ready_to_send_one(tmp_path: Path) -> None:
    result = check_dispatch_record(tmp_path)
    json_path = Path(result["dispatch_record_json"])
    md_path = Path(result["dispatch_record_md"])

    assert result["status"] == "ready_to_dispatch_one"
    assert result["verdict"] == "READY_TO_SEND_ONE"
    assert json_path.name == DISPATCH_RECORD_JSON_NAME
    assert md_path.name == DISPATCH_RECORD_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_dispatch_record_v0_1"
    assert payload["status"] == "ready_to_dispatch_one"
    assert payload["verdict"] == "READY_TO_SEND_ONE"
    assert payload["safe_to_share"] is True
    assert payload["dispatch_record_body_sha256"] == _dispatch_record_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["dispatch_record_checks"].values())
    assert payload["dispatch_scope"]["target_participants"] == 1
    assert payload["dispatch_scope"]["max_recipients_per_record"] == 1
    assert payload["dispatch_scope"]["cohort_scaling_allowed"] is False
    assert payload["pilot_ready"]["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY
    assert payload["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY
    assert payload["checks"]["pilot_ready_dispatch_policy_matched"] is True
    assert payload["checks"]["dispatch_policy_inherits_pilot_ready"] is True
    assert payload["checks"]["bundle_smoke_receipt_status_pass"] is True
    assert payload["checks"]["bundle_smoke_release_hash_matches"] is True
    assert payload["checks"]["bundle_smoke_privacy_safe"] is True
    assert payload["dispatch_record_checks"]["pilot_ready_dispatch_policy_matched"] is True
    assert payload["dispatch_record_checks"]["dispatch_policy_inherits_pilot_ready"] is True
    assert payload["dispatch_record_checks"]["bundle_smoke_body_hash_present"] is True
    assert payload["dispatch_record_checks"]["bundle_smoke_release_hash_matched"] is True
    assert payload["dispatch_record_checks"]["artifact_chain_bundle_smoke_hash_matched"] is True
    assert payload["dispatch_record_checks"]["dispatch_policy_manual_only"] is True
    assert payload["dispatch_record_checks"]["dispatch_policy_one_recipient"] is True
    assert payload["dispatch_record_checks"]["dispatch_policy_private_hash_only"] is True
    assert payload["dispatch_record_checks"]["dispatch_policy_sent_recording_consistent"] is True
    assert payload["dispatch_record"]["sent_recorded"] is False
    assert payload["dispatch_record"]["recipient_private_sha256"] is None
    assert payload["dispatch_record"]["raw_recipient_included"] is False
    assert payload["checks"]["copy_paste_message_policy_locked"] is True
    assert payload["checks"]["copy_paste_message_quickstart_locked"] is True
    assert payload["checks"]["copy_paste_message_agent_prompt_locked"] is True
    assert payload["dispatch_record_checks"]["copy_paste_message_policy_locked"] is True
    assert payload["dispatch_record_checks"]["copy_paste_message_quickstart_locked"] is True
    assert payload["dispatch_record_checks"]["copy_paste_message_agent_prompt_locked"] is True
    assert payload["dispatch_record_checks"]["copy_paste_message_ack_request_locked"] is True
    assert payload["dispatch_record_checks"]["copy_paste_message_no_raw_screenshot_locked"] is True
    assert payload["send_materials"]["copy_paste_message_policy"] == {
        "zip_attachment_named": True,
        "sha256_present": True,
        "quickstart_named": True,
        "agent_prompt_named": True,
        "recipient_ack_short_reply": True,
        "no_raw_screenshot_request": True,
        "provider_key_not_requested": True,
    }
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False

    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}
    assert set(chain_by_kind) == {
        "release_zip",
        "handoff_json",
        "receipt_json",
        "send_ready_json",
        "pilot_ready_json",
        "bundle_smoke_receipt_json",
        "dispatch_record_json",
    }
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["pilot_ready_json"]["sha256"] == payload["pilot_ready"]["body_sha256"]
    assert chain_by_kind["bundle_smoke_receipt_json"]["sha256"] == payload["bundle_smoke_receipt"]["body_sha256"]
    assert chain_by_kind["dispatch_record_json"]["file"] == DISPATCH_RECORD_JSON_NAME
    assert chain_by_kind["dispatch_record_json"]["sha256"] == payload["dispatch_record_body_sha256"]
    assert verify_dispatch_record_file(json_path)["dispatch_record_body_sha256"] == payload["dispatch_record_body_sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Dispatch Record" in markdown
    assert "READY_TO_SEND_ONE" in markdown
    assert "max recipients per record: 1" in markdown
    assert "cohort scaling allowed: False" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "pilot-ready dispatch policy inherited: True" in markdown
    assert "bundle smoke receipt:" in markdown
    assert "bundle_smoke_receipt_json" in markdown
    assert "Copy Paste Message Policy" in markdown
    assert "quickstart_named: True" in markdown
    assert "agent_prompt_named: True" in markdown
    assert "recipient_ack_short_reply: True" in markdown
    assert "no_raw_screenshot_request: True" in markdown
    assert "dispatch_record_json" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_dispatch_record_can_record_private_sent_hashes(tmp_path: Path) -> None:
    result = check_dispatch_record(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
    )
    payload = json.loads(Path(result["dispatch_record_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "dispatch_recorded"
    assert result["verdict"] == "SENT_ONE_RECORDED"
    assert payload["dispatch_record"]["sent_recorded"] is True
    assert payload["dispatch_record"]["sent_at_utc"] == "2026-05-11T10:00:00+00:00"
    assert payload["dispatch_record"]["recipient_private_sha256"] == "a" * 64
    assert payload["dispatch_record"]["operator_dispatch_note_private_sha256"] == "b" * 64
    expected_policy = dict(DISPATCH_EXECUTION_POLICY)
    expected_policy["sent_recorded_by_private_hashes_only"] = True
    assert payload["pilot_ready"]["dispatch_execution_policy"] == DISPATCH_EXECUTION_POLICY
    assert payload["dispatch_execution_policy"] == expected_policy
    assert payload["dispatch_execution_policy"]["sent_recorded_by_private_hashes_only"] is True
    assert payload["dispatch_record_checks"]["dispatch_policy_inherits_pilot_ready"] is True
    assert payload["dispatch_record_checks"]["sent_record_private_hashes_valid"] is True
    assert payload["dispatch_record_checks"]["dispatch_policy_sent_recording_consistent"] is True


def test_external_alpha_dispatch_record_rejects_placeholder_sent_at_when_recording(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="real UTC manual-send timestamp"):
        check_dispatch_record(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="<sent-at-utc>",
        )


def test_external_alpha_dispatch_record_rejects_non_utc_sent_at_when_recording(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="must include UTC timezone"):
        check_dispatch_record(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="2026-05-17T10:00:00+09:00",
        )


def test_external_alpha_dispatch_record_rejects_future_sent_at_when_recording(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="must not be in the future"):
        check_dispatch_record(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="2999-01-01T00:00:00+00:00",
        )


def test_external_alpha_dispatch_record_refreshes_stale_bundle_smoke_receipt(tmp_path: Path) -> None:
    stale = _smoke_receipt(
        {
            "status": "pass",
            "archive_sha256": "0" * 64,
            "file_count": 72,
            "release_version": "0.1.0-alpha",
            "diagnostics_status": "pass",
            "diagnostics_safe_to_share": True,
            "browser_wrapper": {"status": "pass", "script": "verify_agent_platform_browser_flow.py"},
            "batch_rehearsal": {"status": "pass"},
            "dispatch_execution_policy": {
                "script_sends_to_recipient": False,
                "script_sends_copy_paste_message": False,
                "manual_operator_dispatch_required": True,
                "max_recipients_per_record": 1,
                "records_private_sha256_only": True,
            },
        }
    )
    (tmp_path / SMOKE_RECEIPT_NAME).write_text(
        json.dumps(stale, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    result = check_dispatch_record(tmp_path)
    payload = json.loads(Path(result["dispatch_record_json"]).read_text(encoding="utf-8"))

    assert payload["checks"]["bundle_smoke_release_hash_matches"] is True
    assert payload["bundle_smoke_receipt"]["release_archive_sha256"] == payload["release"]["archive_sha256"]


def test_external_alpha_dispatch_record_hashes_private_files_without_leaking_paths(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient.txt"
    note_path = private_dir / "operator-note.txt"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("private channel: email\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()

    result = check_dispatch_record(
        tmp_path,
        recipient_private_file=recipient_path,
        operator_dispatch_note_private_file=note_path,
        sent_at_utc="2026-05-11T10:00:00+00:00",
    )
    json_path = Path(result["dispatch_record_json"])
    md_path = Path(result["dispatch_record_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert result["status"] == "dispatch_recorded"
    assert result["verdict"] == "SENT_ONE_RECORDED"
    assert payload["dispatch_record"]["recipient_private_sha256"] == expected_recipient_hash
    assert payload["dispatch_record"]["operator_dispatch_note_private_sha256"] == expected_note_hash

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(recipient_path) not in serialized
    assert str(note_path) not in serialized
    assert "recipient.txt" not in serialized
    assert "operator-note.txt" not in serialized
    assert "pilot recipient private identifier" not in serialized
    assert "private channel: email" not in serialized


def test_external_alpha_dispatch_record_rejects_partial_private_record(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="recipient/note/sent_at"):
        check_dispatch_record(tmp_path, recipient_private_sha256="a" * 64)


def test_external_alpha_dispatch_record_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(DISPATCH_RECORD_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha dispatch-record" in output
    assert "verdict          : READY_TO_SEND_ONE" in output
    assert (tmp_path / DISPATCH_RECORD_MD_NAME).is_file()
    assert (tmp_path / DISPATCH_RECORD_JSON_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (
        tmp_path / DISPATCH_RECORD_JSON_NAME
    ).read_text(encoding="utf-8")


def test_external_alpha_dispatch_record_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_dispatch_record(tmp_path)
    dispatch_record_path = Path(result["dispatch_record_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(DISPATCH_RECORD_SCRIPT), "--verify-dispatch-record", str(dispatch_record_path)],
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
    assert "[PASS] external alpha dispatch-record verification" in verify_output
    assert "verdict: READY_TO_SEND_ONE" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-dispatch-record.json"
    tampered = json.loads(dispatch_record_path.read_text(encoding="utf-8"))
    tampered["dispatch_scope"]["cohort_scaling_allowed"] = True
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(DISPATCH_RECORD_SCRIPT), "--verify-dispatch-record", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "dispatch-record body hash does not match" in tampered_result.stdout + tampered_result.stderr

    chain_tampered_path = tmp_path / "tampered-dispatch-record-chain.json"
    chain_tampered = json.loads(dispatch_record_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(DISPATCH_RECORD_SCRIPT), "--verify-dispatch-record", str(chain_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert chain_tampered_result.returncode == 1
    assert "dispatch-record safety checks do not match the current body" in (
        chain_tampered_result.stdout + chain_tampered_result.stderr
    )


    policy_tampered_path = tmp_path / "tampered-dispatch-record-policy.json"
    policy_tampered = json.loads(dispatch_record_path.read_text(encoding="utf-8"))
    policy_tampered["send_materials"]["copy_paste_message_policy"]["no_raw_screenshot_request"] = False
    policy_tampered["dispatch_record_body_sha256"] = _dispatch_record_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["dispatch_record_body_sha256"]
    policy_tampered_path.write_text(json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    policy_tampered_result = subprocess.run(
        [sys.executable, str(DISPATCH_RECORD_SCRIPT), "--verify-dispatch-record", str(policy_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert policy_tampered_result.returncode == 1
    assert "dispatch-record" in policy_tampered_result.stdout + policy_tampered_result.stderr

    execution_policy_tampered_path = tmp_path / "tampered-dispatch-record-execution-policy.json"
    execution_policy_tampered = json.loads(dispatch_record_path.read_text(encoding="utf-8"))
    execution_policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    execution_policy_tampered["dispatch_record_body_sha256"] = _dispatch_record_body_sha256(execution_policy_tampered)
    execution_policy_tampered["artifact_chain"][-1]["sha256"] = execution_policy_tampered["dispatch_record_body_sha256"]
    execution_policy_tampered["dispatch_record_checks"] = _dispatch_record_checks(execution_policy_tampered)
    execution_policy_tampered_path.write_text(
        json.dumps(execution_policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    execution_policy_tampered_result = subprocess.run(
        [sys.executable, str(DISPATCH_RECORD_SCRIPT), "--verify-dispatch-record", str(execution_policy_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert execution_policy_tampered_result.returncode == 1
    assert "dispatch_policy_manual_only" in (
        execution_policy_tampered_result.stdout + execution_policy_tampered_result.stderr
    )

    source_policy_tampered_path = tmp_path / "tampered-dispatch-record-source-policy.json"
    source_policy_tampered = json.loads(dispatch_record_path.read_text(encoding="utf-8"))
    source_policy_tampered["pilot_ready"]["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    source_policy_tampered["dispatch_record_body_sha256"] = _dispatch_record_body_sha256(source_policy_tampered)
    source_policy_tampered["artifact_chain"][-1]["sha256"] = source_policy_tampered["dispatch_record_body_sha256"]
    source_policy_tampered["dispatch_record_checks"] = _dispatch_record_checks(source_policy_tampered)
    source_policy_tampered_path.write_text(
        json.dumps(source_policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    source_policy_tampered_result = subprocess.run(
        [sys.executable, str(DISPATCH_RECORD_SCRIPT), "--verify-dispatch-record", str(source_policy_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    source_policy_tampered_output = source_policy_tampered_result.stdout + source_policy_tampered_result.stderr
    assert source_policy_tampered_result.returncode == 1
    assert "pilot_ready_dispatch_policy_matched" in source_policy_tampered_output
    assert "dispatch_policy_inherits_pilot_ready" in source_policy_tampered_output


def test_external_alpha_dispatch_record_cli_hashes_private_files(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient.txt"
    note_path = private_dir / "operator-note.txt"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("private channel: email\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(DISPATCH_RECORD_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--recipient-private-file",
            str(recipient_path),
            "--operator-dispatch-note-private-file",
            str(note_path),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
        ],
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
    payload_text = (tmp_path / DISPATCH_RECORD_JSON_NAME).read_text(encoding="utf-8")
    markdown = (tmp_path / DISPATCH_RECORD_MD_NAME).read_text(encoding="utf-8")
    assert "verdict          : SENT_ONE_RECORDED" in output
    assert expected_recipient_hash in payload_text
    assert expected_note_hash in payload_text
    assert str(recipient_path) not in payload_text + markdown
    assert str(note_path) not in payload_text + markdown
    assert "recipient.txt" not in payload_text + markdown
    assert "operator-note.txt" not in payload_text + markdown
    assert "pilot recipient private identifier" not in payload_text + markdown
    assert "private channel: email" not in payload_text + markdown


def test_external_alpha_dispatch_record_cli_hashes_standard_private_workspace(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient-private.txt"
    note_path = private_dir / "operator-dispatch-note-private.md"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("private channel: email\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    note_path.write_text(
        "private channel: email\n"
        f"attachment sha256 checked: {packet['release']['archive_sha256']}\n",
        encoding="utf-8",
    )
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    preflight_result = check_first_recipient_send_preflight(
        private_dir,
        operator_packet_path=Path(packet_result["packet_json"]),
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(DISPATCH_RECORD_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--private-workspace-dir",
            str(private_dir),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
            "--skip-build",
            "--require-preflight-receipt",
        ],
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
    payload_text = (tmp_path / DISPATCH_RECORD_JSON_NAME).read_text(encoding="utf-8")
    markdown = (tmp_path / DISPATCH_RECORD_MD_NAME).read_text(encoding="utf-8")
    assert "verdict          : SENT_ONE_RECORDED" in output
    assert expected_recipient_hash in payload_text
    assert expected_note_hash in payload_text
    assert Path(preflight_result["receipt_json"]).name == PREFLIGHT_RECEIPT_NAME
    assert "pre_send_preflight_receipt_json" in payload_text
    assert preflight_result["receipt_body_sha256"] in payload_text
    assert str(private_dir) not in payload_text + markdown
    assert "recipient-private.txt" not in payload_text + markdown
    assert "operator-dispatch-note-private.md" not in payload_text + markdown


def test_external_alpha_dispatch_record_cli_requires_preflight_when_requested(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("private channel: email\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(DISPATCH_RECORD_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--private-workspace-dir",
            str(private_dir),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
            "--require-preflight-receipt",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "pre-send preflight receipt" in output


def test_external_alpha_dispatch_record_private_workspace_requires_preflight_by_default(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("private channel: email\n", encoding="utf-8")

    with pytest.raises(DispatchRecordError, match="pre-send preflight receipt"):
        check_dispatch_record(
            tmp_path,
            private_workspace_dir=private_dir,
            sent_at_utc="2026-05-11T10:00:00+00:00",
        )


def test_external_alpha_synthetic_rehearsal_dispatch_is_not_standalone_send_evidence(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient-private.txt"
    note_path = private_dir / "operator-dispatch-note-private.md"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    packet_result = prepare_operator_dispatch_packet(tmp_path)
    packet = json.loads(Path(packet_result["packet_json"]).read_text(encoding="utf-8"))
    note_path.write_text(
        "private channel: direct message\n"
        f"attachment sha256 checked: {packet['release']['archive_sha256']}\n",
        encoding="utf-8",
    )
    check_first_recipient_send_preflight(
        private_dir,
        operator_packet_path=Path(packet_result["packet_json"]),
    )

    result = check_dispatch_record(
        tmp_path,
        private_workspace_dir=private_dir,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        skip_build=True,
        synthetic_rehearsal_without_real_recipient=True,
    )
    dispatch_path = Path(result["dispatch_record_json"])

    with pytest.raises(DispatchRecordError, match="not standalone send evidence"):
        verify_dispatch_record_file(dispatch_path)

    payload = verify_dispatch_record_file(dispatch_path, allow_synthetic_rehearsal=True)
    assert payload["verdict"] == "SENT_ONE_RECORDED"
    assert payload["synthetic_rehearsal_boundary"]["synthetic_rehearsal"] is True
    assert payload["synthetic_rehearsal_boundary"]["standalone_send_evidence_allowed"] is False
    assert payload["synthetic_rehearsal_boundary"]["real_manual_send"] is False
    assert payload["synthetic_rehearsal_boundary"]["real_recipient_evidence"] is False


def test_external_alpha_dispatch_record_cli_rejects_workspace_placeholders(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text(
        "PRIVATE - DO NOT SHARE OR COMMIT\nRecipient identifier/contact goes here\n",
        encoding="utf-8",
    )
    (private_dir / "operator-dispatch-note-private.md").write_text("private channel: email\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(DISPATCH_RECORD_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--private-workspace-dir",
            str(private_dir),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "placeholder" in output

