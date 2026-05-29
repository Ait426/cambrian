import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import DispatchRecordError
from scripts.check_external_alpha_pilot_evidence import (
    PILOT_EVIDENCE_JSON_NAME,
    PILOT_EVIDENCE_MD_NAME,
    _pilot_evidence_body_sha256,
    _pilot_evidence_checks,
    check_pilot_evidence,
    verify_pilot_evidence_file,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT_EVIDENCE_SCRIPT = ROOT / "scripts" / "check_external_alpha_pilot_evidence.py"


def test_external_alpha_pilot_evidence_outputs_no_decision_without_private_hash(tmp_path: Path) -> None:
    result = check_pilot_evidence(tmp_path)
    json_path = Path(result["pilot_evidence_json"])
    md_path = Path(result["pilot_evidence_md"])

    assert result["status"] == "awaiting_private_pilot_evidence"
    assert result["verdict"] == "NO_DECISION"
    assert json_path.name == PILOT_EVIDENCE_JSON_NAME
    assert md_path.name == PILOT_EVIDENCE_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_pilot_evidence_v0_1"
    assert payload["status"] == "awaiting_private_pilot_evidence"
    assert payload["verdict"] == "NO_DECISION"
    assert payload["safe_to_share"] is True
    assert payload["pilot_evidence_body_sha256"] == _pilot_evidence_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["pilot_evidence_checks"].values())
    assert payload["checks"]["dispatch_manual_only_policy"] is True
    assert payload["checks"]["dispatch_one_recipient_policy"] is True
    assert payload["checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["pilot_evidence_checks"]["dispatch_manual_only_policy"] is True
    assert payload["pilot_evidence_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["pilot_evidence_checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["dispatch_execution_policy"] == {
        "cohort_scaling_allowed": False,
        "manual_operator_dispatch_required": True,
        "max_recipients_per_record": 1,
        "raw_private_content_included": False,
        "records_private_sha256_only": True,
        "script_sends_copy_paste_message": False,
        "script_sends_to_recipient": False,
        "sent_recorded_by_private_hashes_only": False,
    }
    assert payload["decision_allowed"] is False
    assert payload["operator_decision"] == "not_decided"
    assert payload["pilot_learning_summary"] == {
        "summary_kind": "controlled_tags_only",
        "outcome_tag": "not_collected",
        "friction_tags": ["none"],
        "missing_skill_tags": ["none"],
        "raw_feedback_included": False,
        "raw_issue_included": False,
        "free_text_included": False,
    }
    assert payload["metrics"]["pilot_participants_completed"] == 0
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False
    assert payload["private_evidence_fingerprints"]["feedback_form_sha256"] is None
    assert payload["private_evidence_fingerprints"]["raw_private_content_included"] is False
    assert payload["shared_evidence"]["receipt"]["safe_to_share"] is True
    assert payload["shared_evidence"]["diagnostics"]["safe_to_share"] is True
    assert payload["shared_evidence"]["diagnostics"]["redaction_checks_all_true"] is True

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
        "pilot_evidence_json",
    }
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["pilot_review_json"]["sha256"] == payload["pilot_review"]["body_sha256"]
    assert chain_by_kind["pilot_evidence_json"]["file"] == PILOT_EVIDENCE_JSON_NAME
    assert chain_by_kind["pilot_evidence_json"]["sha256"] == payload["pilot_evidence_body_sha256"]
    assert verify_pilot_evidence_file(json_path)["pilot_evidence_body_sha256"] == payload["pilot_evidence_body_sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Pilot Evidence" in markdown
    assert "NO_DECISION" in markdown
    assert "success rate: not collected" in markdown
    assert "Private Evidence Fingerprints" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "raw private content included: False" in markdown
    assert "pilot_evidence_json" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_pilot_evidence_can_record_ready_decision_with_private_hash(tmp_path: Path) -> None:
    feedback_hash = "a" * 64
    issue_hash = "b" * 64
    result = check_pilot_evidence(
        tmp_path,
        feedback_private_sha256=feedback_hash,
        issue_intake_private_sha256=issue_hash,
        operator_decision="fix_before_next",
        outcome_tag="partial",
        friction_tags=["proof_trust", "docs"],
        missing_skill_tags=["harness_engineering"],
    )
    payload = json.loads(Path(result["pilot_evidence_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "pilot_evidence_ready"
    assert result["verdict"] == "READY_FOR_DECISION"
    assert payload["decision_allowed"] is True
    assert payload["operator_decision"] == "fix_before_next"
    assert payload["pilot_learning_summary"]["outcome_tag"] == "partial"
    assert payload["pilot_learning_summary"]["friction_tags"] == ["proof_trust", "docs"]
    assert payload["pilot_learning_summary"]["missing_skill_tags"] == ["harness_engineering"]
    assert payload["checks"]["learning_summary_controlled_tags"] is True
    assert payload["pilot_evidence_checks"]["learning_summary_controlled_tags"] is True
    assert payload["metrics"]["pilot_participants_completed"] == 1
    assert payload["metrics"]["success_rate"] is None
    assert payload["private_evidence_fingerprints"]["feedback_form_sha256"] == feedback_hash
    assert payload["private_evidence_fingerprints"]["issue_intake_sha256"] == issue_hash
    assert payload["pilot_evidence_checks"]["decision_allowed_matches_status"] is True


def test_external_alpha_pilot_evidence_hashes_private_files_without_leaking_paths(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    feedback_path = private_dir / "pilot-feedback.md"
    issue_path = private_dir / "pilot-issue.md"
    feedback_path.write_text("사용자 피드백 원문\n", encoding="utf-8")
    issue_path.write_text("이슈 인테이크 원문\n", encoding="utf-8")
    expected_feedback_hash = hashlib.sha256(feedback_path.read_bytes()).hexdigest()
    expected_issue_hash = hashlib.sha256(issue_path.read_bytes()).hexdigest()

    result = check_pilot_evidence(
        tmp_path,
        feedback_private_file=feedback_path,
        issue_intake_private_file=issue_path,
        operator_decision="fix_before_next",
        outcome_tag="blocked_builder",
        friction_tags=["builder"],
        missing_skill_tags=["skill_fusion"],
    )
    json_path = Path(result["pilot_evidence_json"])
    md_path = Path(result["pilot_evidence_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert result["status"] == "pilot_evidence_ready"
    assert result["verdict"] == "READY_FOR_DECISION"
    assert payload["private_evidence_fingerprints"]["feedback_form_sha256"] == expected_feedback_hash
    assert payload["private_evidence_fingerprints"]["issue_intake_sha256"] == expected_issue_hash
    assert payload["pilot_learning_summary"]["outcome_tag"] == "blocked_builder"
    assert payload["pilot_learning_summary"]["friction_tags"] == ["builder"]
    assert payload["pilot_learning_summary"]["missing_skill_tags"] == ["skill_fusion"]

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(feedback_path) not in serialized
    assert str(issue_path) not in serialized
    assert "pilot-feedback.md" not in serialized
    assert "pilot-issue.md" not in serialized
    assert "사용자 피드백 원문" not in serialized
    assert "이슈 인테이크 원문" not in serialized


def test_external_alpha_pilot_evidence_passes_dispatch_private_files_without_leaking_paths(
    tmp_path: Path,
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient.txt"
    note_path = private_dir / "operator-note.txt"
    ack_path = private_dir / "recipient-ack.txt"
    feedback_path = private_dir / "pilot-feedback.md"
    issue_path = private_dir / "pilot-issue.md"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("확인 완료\n", encoding="utf-8")
    feedback_path.write_text("사용자 피드백 원문\n", encoding="utf-8")
    issue_path.write_text("이슈 인테이크 원문\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()
    expected_feedback_hash = hashlib.sha256(feedback_path.read_bytes()).hexdigest()
    expected_issue_hash = hashlib.sha256(issue_path.read_bytes()).hexdigest()

    result = check_pilot_evidence(
        tmp_path,
        recipient_private_file=recipient_path,
        operator_dispatch_note_private_file=note_path,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_file=ack_path,
        feedback_private_file=feedback_path,
        issue_intake_private_file=issue_path,
        operator_decision="fix_before_next",
        outcome_tag="partial",
        friction_tags=["runner", "proof_trust"],
        missing_skill_tags=["support_diagnostics"],
    )
    evidence_json = Path(result["pilot_evidence_json"])
    evidence_md = Path(result["pilot_evidence_md"])
    review_json = Path(result["pilot_review_json"])
    checkpoint_json = tmp_path / "cambrian-agent-platform-external-alpha-recipient-checkpoint.json"
    dispatch_json = tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json"
    evidence_payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    checkpoint_payload = json.loads(checkpoint_json.read_text(encoding="utf-8"))
    dispatch_payload = json.loads(dispatch_json.read_text(encoding="utf-8"))

    assert result["verdict"] == "READY_FOR_DECISION"
    assert evidence_payload["private_evidence_fingerprints"]["feedback_form_sha256"] == expected_feedback_hash
    assert evidence_payload["private_evidence_fingerprints"]["issue_intake_sha256"] == expected_issue_hash
    assert evidence_payload["pilot_learning_summary"]["outcome_tag"] == "partial"
    assert checkpoint_payload["private_checkpoint_fingerprints"]["recipient_ack_sha256"] == expected_ack_hash
    assert dispatch_payload["dispatch_record"]["recipient_private_sha256"] == expected_recipient_hash
    assert dispatch_payload["dispatch_record"]["operator_dispatch_note_private_sha256"] == expected_note_hash

    serialized = (
        json.dumps(evidence_payload, ensure_ascii=False)
        + evidence_md.read_text(encoding="utf-8")
        + review_json.read_text(encoding="utf-8")
        + json.dumps(checkpoint_payload, ensure_ascii=False)
        + json.dumps(dispatch_payload, ensure_ascii=False)
    )
    for private_path in [recipient_path, note_path, ack_path, feedback_path, issue_path]:
        assert str(private_path) not in serialized
        assert private_path.name not in serialized
    assert "pilot recipient private identifier" not in serialized
    assert "sent by private channel" not in serialized
    assert "확인 완료" not in serialized
    assert "사용자 피드백 원문" not in serialized
    assert "이슈 인테이크 원문" not in serialized


def test_external_alpha_pilot_evidence_rejects_placeholder_sent_at(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="real UTC manual-send timestamp"):
        check_pilot_evidence(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="<sent-at-utc>",
            recipient_ack_private_sha256="c" * 64,
            feedback_private_sha256="d" * 64,
            issue_intake_private_sha256="e" * 64,
            operator_decision="fix_before_next",
            outcome_tag="partial",
        )

    assert not (tmp_path / PILOT_EVIDENCE_JSON_NAME).exists()
    assert not (tmp_path / PILOT_EVIDENCE_MD_NAME).exists()


def test_external_alpha_pilot_evidence_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(PILOT_EVIDENCE_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha pilot-evidence" in output
    assert "verdict         : NO_DECISION" in output
    assert (tmp_path / PILOT_EVIDENCE_MD_NAME).is_file()
    assert (tmp_path / PILOT_EVIDENCE_JSON_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / PILOT_EVIDENCE_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_pilot_evidence_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_pilot_evidence(tmp_path)
    pilot_evidence_path = Path(result["pilot_evidence_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(PILOT_EVIDENCE_SCRIPT), "--verify-pilot-evidence", str(pilot_evidence_path)],
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
    assert "[PASS] external alpha pilot-evidence verification" in verify_output
    assert "verdict: NO_DECISION" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-pilot-evidence.json"
    tampered = json.loads(pilot_evidence_path.read_text(encoding="utf-8"))
    tampered["metrics"]["success_rate"] = 1.0
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(PILOT_EVIDENCE_SCRIPT), "--verify-pilot-evidence", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "pilot-evidence 본문 해시가 일치하지 않습니다" in tampered_result.stdout + tampered_result.stderr

    chain_tampered_path = tmp_path / "tampered-pilot-evidence-chain.json"
    chain_tampered = json.loads(pilot_evidence_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_EVIDENCE_SCRIPT), "--verify-pilot-evidence", str(chain_tampered_path)],
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


    policy_tampered_path = tmp_path / "tampered-pilot-evidence-policy.json"
    policy_tampered = json.loads(pilot_evidence_path.read_text(encoding="utf-8"))
    policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["pilot_evidence_body_sha256"] = _pilot_evidence_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["pilot_evidence_body_sha256"]
    policy_tampered["pilot_evidence_checks"] = _pilot_evidence_checks(policy_tampered)
    policy_tampered_path.write_text(
        json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    policy_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_EVIDENCE_SCRIPT), "--verify-pilot-evidence", str(policy_tampered_path)],
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


def test_external_alpha_pilot_evidence_cli_hashes_private_files(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    feedback_path = private_dir / "pilot-feedback.md"
    issue_path = private_dir / "pilot-issue.md"
    feedback_path.write_text("사용자 피드백 원문\n", encoding="utf-8")
    issue_path.write_text("이슈 인테이크 원문\n", encoding="utf-8")
    expected_feedback_hash = hashlib.sha256(feedback_path.read_bytes()).hexdigest()
    expected_issue_hash = hashlib.sha256(issue_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_EVIDENCE_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--feedback-private-file",
            str(feedback_path),
            "--issue-intake-private-file",
            str(issue_path),
            "--operator-decision",
            "fix_before_next",
            "--outcome-tag",
            "partial",
            "--friction-tag",
            "docs",
            "--missing-skill-tag",
            "skill_search",
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
    payload_text = (tmp_path / PILOT_EVIDENCE_JSON_NAME).read_text(encoding="utf-8")
    markdown = (tmp_path / PILOT_EVIDENCE_MD_NAME).read_text(encoding="utf-8")
    assert "verdict         : READY_FOR_DECISION" in output
    assert expected_feedback_hash in payload_text
    assert expected_issue_hash in payload_text
    assert str(feedback_path) not in payload_text + markdown
    assert str(issue_path) not in payload_text + markdown
    assert "pilot-feedback.md" not in payload_text + markdown
    assert "pilot-issue.md" not in payload_text + markdown
    assert "사용자 피드백 원문" not in payload_text + markdown
    assert "이슈 인테이크 원문" not in payload_text + markdown


def test_external_alpha_pilot_evidence_cli_passes_dispatch_private_files(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient.txt"
    note_path = private_dir / "operator-note.txt"
    ack_path = private_dir / "recipient-ack.txt"
    feedback_path = private_dir / "pilot-feedback.md"
    issue_path = private_dir / "pilot-issue.md"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("확인 완료\n", encoding="utf-8")
    feedback_path.write_text("사용자 피드백 원문\n", encoding="utf-8")
    issue_path.write_text("이슈 인테이크 원문\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()
    expected_feedback_hash = hashlib.sha256(feedback_path.read_bytes()).hexdigest()
    expected_issue_hash = hashlib.sha256(issue_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_EVIDENCE_SCRIPT),
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
            "--feedback-private-file",
            str(feedback_path),
            "--issue-intake-private-file",
            str(issue_path),
            "--operator-decision",
            "fix_before_next",
            "--outcome-tag",
            "partial",
            "--friction-tag",
            "runner",
            "--missing-skill-tag",
            "support_diagnostics",
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
    evidence_text = (tmp_path / PILOT_EVIDENCE_JSON_NAME).read_text(encoding="utf-8")
    evidence_markdown = (tmp_path / PILOT_EVIDENCE_MD_NAME).read_text(encoding="utf-8")
    review_text = (tmp_path / "cambrian-agent-platform-external-alpha-pilot-review.json").read_text(encoding="utf-8")
    checkpoint_text = (tmp_path / "cambrian-agent-platform-external-alpha-recipient-checkpoint.json").read_text(
        encoding="utf-8"
    )
    dispatch_text = (tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json").read_text(
        encoding="utf-8"
    )
    combined = evidence_text + evidence_markdown + review_text + checkpoint_text + dispatch_text
    assert "verdict         : READY_FOR_DECISION" in output
    assert expected_feedback_hash in evidence_text
    assert expected_issue_hash in evidence_text
    assert expected_ack_hash in checkpoint_text
    assert expected_recipient_hash in dispatch_text
    assert expected_note_hash in dispatch_text
    for private_path in [recipient_path, note_path, ack_path, feedback_path, issue_path]:
        assert str(private_path) not in combined
        assert private_path.name not in combined
    assert "pilot recipient private identifier" not in combined
    assert "sent by private channel" not in combined


def test_external_alpha_pilot_evidence_cli_hashes_standard_private_workspace(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient-private.txt"
    note_path = private_dir / "operator-dispatch-note-private.md"
    ack_path = private_dir / "recipient-ack-private.txt"
    feedback_path = private_dir / "pilot-feedback-private.md"
    issue_path = private_dir / "pilot-issue-intake-private.md"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("acknowledged start path\n", encoding="utf-8")
    feedback_path.write_text("feedback says builder flow was partially blocked\n", encoding="utf-8")
    issue_path.write_text("issue intake says runner terminology was confusing\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()
    expected_feedback_hash = hashlib.sha256(feedback_path.read_bytes()).hexdigest()
    expected_issue_hash = hashlib.sha256(issue_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_EVIDENCE_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--private-workspace-dir",
            str(private_dir),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
            "--operator-decision",
            "fix_before_next",
            "--outcome-tag",
            "partial",
            "--friction-tag",
            "runner",
            "--missing-skill-tag",
            "support_diagnostics",
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
    evidence_text = (tmp_path / PILOT_EVIDENCE_JSON_NAME).read_text(encoding="utf-8")
    checkpoint_text = (tmp_path / "cambrian-agent-platform-external-alpha-recipient-checkpoint.json").read_text(
        encoding="utf-8"
    )
    dispatch_text = (tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json").read_text(
        encoding="utf-8"
    )
    combined = evidence_text + checkpoint_text + dispatch_text
    assert "verdict         : READY_FOR_DECISION" in output
    assert expected_feedback_hash in evidence_text
    assert expected_issue_hash in evidence_text
    assert expected_ack_hash in checkpoint_text
    assert expected_recipient_hash in dispatch_text
    assert expected_note_hash in dispatch_text
    assert str(private_dir) not in combined
    for private_path in [recipient_path, note_path, ack_path, feedback_path, issue_path]:
        assert private_path.name not in combined
    assert "feedback says builder flow" not in combined
    assert "issue intake says runner" not in combined


def test_external_alpha_pilot_evidence_cli_rejects_workspace_placeholders(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("sent by private channel\n", encoding="utf-8")
    (private_dir / "recipient-ack-private.txt").write_text("acknowledged start path\n", encoding="utf-8")
    (private_dir / "pilot-feedback-private.md").write_text(
        "PRIVATE - DO NOT SHARE OR COMMIT\n"
        "Keep raw feedback here. Public artifacts must receive only sha256 and controlled tags.\n",
        encoding="utf-8",
    )
    (private_dir / "pilot-issue-intake-private.md").write_text("no issue intake\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_EVIDENCE_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--private-workspace-dir",
            str(private_dir),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
            "--operator-decision",
            "fix_before_next",
            "--outcome-tag",
            "partial",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=120,
    )

    combined = ""
    assert result.returncode == 1
    assert "placeholder" in result.stdout + result.stderr
    assert "확인 완료" not in combined
    assert "사용자 피드백 원문" not in combined
    assert "이슈 인테이크 원문" not in combined
