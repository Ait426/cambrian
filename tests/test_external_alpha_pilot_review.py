import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import DispatchRecordError
from scripts.check_external_alpha_pilot_review import (
    PILOT_REVIEW_JSON_NAME,
    PILOT_REVIEW_MD_NAME,
    _pilot_review_body_sha256,
    _pilot_review_checks,
    check_pilot_review,
    verify_pilot_review_file,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT_REVIEW_SCRIPT = ROOT / "scripts" / "check_external_alpha_pilot_review.py"


def _write_builder_gold_path_share_receipt(path: Path) -> Path:
    payload = {
        "schema_version": "external_alpha_builder_gold_path_share_receipt_v0_1",
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "checks": {
            "builder_golden_path_completed": True,
            "manual_no_api_runner_used": True,
            "promotion_audit_lineage_verified": True,
            "raw_browser_storage_excluded": True,
        },
        "capabilities_verified": {
            "agent_pack_created": True,
            "manual_runner_receipt_created": True,
            "evolution_suggestion_created": True,
            "candidate_diff_report_created": True,
            "promoted_private_version_created": True,
            "promotion_audit_record_created": True,
            "private_hub_lineage_verified": True,
        },
        "proof_claim_allowed": False,
        "success_rate_claim_allowed": False,
        "sale_ready": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_external_alpha_pilot_review_outputs_waiting_for_evidence(tmp_path: Path) -> None:
    result = check_pilot_review(tmp_path)
    json_path = Path(result["pilot_review_json"])
    md_path = Path(result["pilot_review_md"])

    assert result["status"] == "awaiting_pilot_evidence"
    assert result["verdict"] == "WAITING_FOR_EVIDENCE"
    assert json_path.name == PILOT_REVIEW_JSON_NAME
    assert md_path.name == PILOT_REVIEW_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_pilot_review_v0_1"
    assert payload["status"] == "awaiting_pilot_evidence"
    assert payload["verdict"] == "WAITING_FOR_EVIDENCE"
    assert payload["safe_to_share"] is True
    assert payload["pilot_review_body_sha256"] == _pilot_review_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["pilot_review_checks"].values())
    assert payload["checks"]["recipient_checkpoint_ready_or_waiting"] is True
    assert payload["checks"]["evidence_required_before_decision"] is True
    assert payload["checks"]["dispatch_manual_only_policy"] is True
    assert payload["checks"]["dispatch_one_recipient_policy"] is True
    assert payload["checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["pilot_review_checks"]["dispatch_manual_only_policy"] is True
    assert payload["pilot_review_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["pilot_review_checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["dispatch_execution_policy"] == {
        "script_sends_to_recipient": False,
        "script_sends_copy_paste_message": False,
        "manual_operator_dispatch_required": True,
        "max_recipients_per_record": 1,
        "records_private_sha256_only": True,
        "raw_private_content_included": False,
        "cohort_scaling_allowed": False,
        "sent_recorded_by_private_hashes_only": False,
    }
    assert payload["metrics"]["pilot_participants_completed"] == 0
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False
    assert payload["pilot_evidence"]["status"] == "not_collected"
    assert "success rate" in payload["forbidden_claims"]
    assert "proof claim" in payload["forbidden_claims"]
    assert "sale ready" in payload["forbidden_claims"]

    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}
    assert set(chain_by_kind) == {
        "release_zip",
        "handoff_json",
        "receipt_json",
        "send_ready_json",
        "pilot_ready_json",
        "bundle_smoke_receipt_json",
        "dispatch_record_json",
        "recipient_checkpoint_json",
        "pilot_review_json",
    }
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["pilot_ready_json"]["sha256"] == payload["pilot_ready"]["body_sha256"]
    assert chain_by_kind["dispatch_record_json"]["sha256"] == payload["dispatch_record"]["body_sha256"]
    assert chain_by_kind["recipient_checkpoint_json"]["sha256"] == payload["recipient_checkpoint"]["body_sha256"]
    assert chain_by_kind["pilot_review_json"]["file"] == PILOT_REVIEW_JSON_NAME
    assert chain_by_kind["pilot_review_json"]["sha256"] == payload["pilot_review_body_sha256"]
    assert payload["pilot_review_checks"]["artifact_chain_complete"] is True
    assert payload["pilot_review_checks"]["artifact_chain_pilot_review_hash_matched"] is True
    assert verify_pilot_review_file(json_path)["pilot_review_body_sha256"] == payload["pilot_review_body_sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Pilot Review" in markdown
    assert "Awaiting Pilot Evidence" in markdown
    assert "WAITING_FOR_EVIDENCE" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "success rate: not collected" in markdown
    assert "Evidence Required Before Decision" in markdown
    assert "Forbidden Claims" in markdown
    assert "pilot_review_json" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_pilot_review_passes_private_files_to_recipient_checkpoint_without_leaking_paths(
    tmp_path: Path,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient.txt"
    note_path = private_dir / "operator-note.txt"
    ack_path = private_dir / "recipient-ack.txt"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("확인 완료\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()

    result = check_pilot_review(
        tmp_path,
        recipient_private_file=recipient_path,
        operator_dispatch_note_private_file=note_path,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_file=ack_path,
    )
    review_json = Path(result["pilot_review_json"])
    review_md = Path(result["pilot_review_md"])
    checkpoint_json = Path(result["recipient_checkpoint_json"])
    dispatch_json = tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json"
    review_payload = json.loads(review_json.read_text(encoding="utf-8"))
    checkpoint_payload = json.loads(checkpoint_json.read_text(encoding="utf-8"))
    dispatch_payload = json.loads(dispatch_json.read_text(encoding="utf-8"))

    assert result["verdict"] == "WAITING_FOR_EVIDENCE"
    assert checkpoint_payload["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert checkpoint_payload["private_checkpoint_fingerprints"]["recipient_ack_sha256"] == expected_ack_hash
    assert dispatch_payload["dispatch_record"]["recipient_private_sha256"] == expected_recipient_hash
    assert dispatch_payload["dispatch_record"]["operator_dispatch_note_private_sha256"] == expected_note_hash

    serialized = (
        json.dumps(review_payload, ensure_ascii=False)
        + review_md.read_text(encoding="utf-8")
        + json.dumps(checkpoint_payload, ensure_ascii=False)
        + json.dumps(dispatch_payload, ensure_ascii=False)
    )
    assert str(recipient_path) not in serialized
    assert str(note_path) not in serialized
    assert str(ack_path) not in serialized
    assert "recipient.txt" not in serialized
    assert "operator-note.txt" not in serialized
    assert "recipient-ack.txt" not in serialized
    assert "pilot recipient private identifier" not in serialized
    assert "sent by private channel" not in serialized
    assert "확인 완료" not in serialized


def test_external_alpha_pilot_review_rejects_placeholder_sent_at(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="real UTC manual-send timestamp"):
        check_pilot_review(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="<sent-at-utc>",
            recipient_ack_private_sha256="c" * 64,
        )

    assert not (tmp_path / PILOT_REVIEW_JSON_NAME).exists()
    assert not (tmp_path / PILOT_REVIEW_MD_NAME).exists()


def test_external_alpha_pilot_review_carries_builder_gold_path_receipt_summary(tmp_path: Path) -> None:
    receipt_path = _write_builder_gold_path_share_receipt(tmp_path / "external_alpha_builder_gold_path_share_receipt.json")
    expected_receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    result = check_pilot_review(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_sha256="c" * 64,
        builder_gold_path_share_receipt=receipt_path,
    )
    review_payload = json.loads(Path(result["pilot_review_json"]).read_text(encoding="utf-8"))
    checkpoint_payload = json.loads(Path(result["recipient_checkpoint_json"]).read_text(encoding="utf-8"))

    assert checkpoint_payload["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert review_payload["recipient_checkpoint"]["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert review_payload["recipient_checkpoint"]["builder_gold_path_confirmed"] is True
    assert review_payload["recipient_checkpoint"]["builder_gold_path_share_receipt_sha256"] == expected_receipt_hash
    assert all(review_payload["recipient_checkpoint"]["builder_gold_path_capabilities_verified"].values())
    assert "builder_gold_path_share_receipt" in {item["kind"] for item in review_payload["artifact_chain"]}
    assert verify_pilot_review_file(Path(result["pilot_review_json"]))["pilot_review_checks"][
        "artifact_chain_hashes_present"
    ] is True

    serialized = json.dumps(review_payload, ensure_ascii=False)
    assert str(receipt_path) not in serialized


def test_external_alpha_pilot_review_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(PILOT_REVIEW_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha pilot-review" in output
    assert "verdict       : WAITING_FOR_EVIDENCE" in output
    assert (tmp_path / PILOT_REVIEW_MD_NAME).is_file()
    assert (tmp_path / PILOT_REVIEW_JSON_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / PILOT_REVIEW_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_pilot_review_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_pilot_review(tmp_path)
    pilot_review_path = Path(result["pilot_review_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(PILOT_REVIEW_SCRIPT), "--verify-pilot-review", str(pilot_review_path)],
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
    assert "[PASS] external alpha pilot-review verification" in verify_output
    assert "verdict: WAITING_FOR_EVIDENCE" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-pilot-review.json"
    tampered = json.loads(pilot_review_path.read_text(encoding="utf-8"))
    tampered["metrics"]["success_rate"] = 1.0
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(PILOT_REVIEW_SCRIPT), "--verify-pilot-review", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "pilot-review 본문 해시가 일치하지 않습니다" in tampered_result.stdout + tampered_result.stderr

    chain_tampered_path = tmp_path / "tampered-pilot-review-chain.json"
    chain_tampered = json.loads(pilot_review_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_REVIEW_SCRIPT), "--verify-pilot-review", str(chain_tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert chain_tampered_result.returncode == 1
    assert "안전 평가 결과가 현재 본문과 일치하지 않습니다" in (
        chain_tampered_result.stdout + chain_tampered_result.stderr
    )


    policy_tampered_path = tmp_path / "tampered-pilot-review-policy.json"
    policy_tampered = json.loads(pilot_review_path.read_text(encoding="utf-8"))
    policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["pilot_review_body_sha256"] = _pilot_review_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["pilot_review_body_sha256"]
    policy_tampered["pilot_review_checks"] = _pilot_review_checks(policy_tampered)
    policy_tampered_path.write_text(json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    policy_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_REVIEW_SCRIPT), "--verify-pilot-review", str(policy_tampered_path)],
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


def test_external_alpha_pilot_review_cli_passes_private_files(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient.txt"
    note_path = private_dir / "operator-note.txt"
    ack_path = private_dir / "recipient-ack.txt"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("확인 완료\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_REVIEW_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--recipient-private-file",
            str(recipient_path),
            "--operator-dispatch-note-private-file",
            str(note_path),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
            "--recipient-ack-private-file",
            str(ack_path),
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
    review_text = (tmp_path / PILOT_REVIEW_JSON_NAME).read_text(encoding="utf-8")
    review_markdown = (tmp_path / PILOT_REVIEW_MD_NAME).read_text(encoding="utf-8")
    checkpoint_text = (tmp_path / "cambrian-agent-platform-external-alpha-recipient-checkpoint.json").read_text(
        encoding="utf-8"
    )
    dispatch_text = (tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json").read_text(
        encoding="utf-8"
    )
    combined = review_text + review_markdown + checkpoint_text + dispatch_text
    assert "verdict       : WAITING_FOR_EVIDENCE" in output
    assert expected_ack_hash in checkpoint_text
    assert expected_recipient_hash in dispatch_text
    assert expected_note_hash in dispatch_text
    assert str(recipient_path) not in combined
    assert str(note_path) not in combined
    assert str(ack_path) not in combined
    assert "recipient.txt" not in combined
    assert "operator-note.txt" not in combined
    assert "recipient-ack.txt" not in combined
    assert "pilot recipient private identifier" not in combined
    assert "sent by private channel" not in combined


def test_external_alpha_pilot_review_cli_hashes_standard_private_workspace(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient-private.txt"
    note_path = private_dir / "operator-dispatch-note-private.md"
    ack_path = private_dir / "recipient-ack-private.txt"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("acknowledged start path\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_REVIEW_SCRIPT),
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
    assert result.returncode == 0, output
    review_text = (tmp_path / PILOT_REVIEW_JSON_NAME).read_text(encoding="utf-8")
    checkpoint_text = (tmp_path / "cambrian-agent-platform-external-alpha-recipient-checkpoint.json").read_text(
        encoding="utf-8"
    )
    dispatch_text = (tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json").read_text(
        encoding="utf-8"
    )
    combined = review_text + checkpoint_text + dispatch_text
    assert "verdict       : WAITING_FOR_EVIDENCE" in output
    assert expected_ack_hash in checkpoint_text
    assert expected_recipient_hash in dispatch_text
    assert expected_note_hash in dispatch_text
    assert str(private_dir) not in combined
    for private_path in [recipient_path, note_path, ack_path]:
        assert private_path.name not in combined
    assert "pilot recipient private identifier" not in combined
    assert "sent by private channel" not in combined
    assert "acknowledged start path" not in combined
    assert "확인 완료" not in combined
