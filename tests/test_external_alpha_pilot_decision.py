import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import DispatchRecordError
from scripts.check_external_alpha_pilot_decision import (
    PILOT_DECISION_JSON_NAME,
    PILOT_DECISION_MD_NAME,
    _pilot_decision_body_sha256,
    _pilot_decision_checks,
    check_pilot_decision,
    verify_pilot_decision_file,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT_DECISION_SCRIPT = ROOT / "scripts" / "check_external_alpha_pilot_decision.py"


def test_external_alpha_pilot_decision_blocks_without_ready_evidence(tmp_path: Path) -> None:
    result = check_pilot_decision(tmp_path)
    json_path = Path(result["pilot_decision_json"])
    md_path = Path(result["pilot_decision_md"])

    assert result["status"] == "decision_blocked"
    assert result["verdict"] == "NO_DECISION"
    assert json_path.name == PILOT_DECISION_JSON_NAME
    assert md_path.name == PILOT_DECISION_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_pilot_decision_v0_1"
    assert payload["status"] == "decision_blocked"
    assert payload["verdict"] == "NO_DECISION"
    assert payload["safe_to_share"] is True
    assert payload["pilot_decision_body_sha256"] == _pilot_decision_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["pilot_decision_checks"].values())
    assert payload["checks"]["dispatch_manual_only_policy"] is True
    assert payload["checks"]["dispatch_one_recipient_policy"] is True
    assert payload["checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["pilot_decision_checks"]["dispatch_manual_only_policy"] is True
    assert payload["pilot_decision_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["pilot_decision_checks"]["dispatch_private_hash_only_policy"] is True
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
    assert payload["decision"]["recorded"] is False
    assert payload["decision"]["blocked_reason"] == "evidence_not_ready"
    assert payload["decision"]["raw_operator_note_included"] is False
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False
    assert payload["metrics"]["market_validated"] is False
    assert payload["publish_boundary"]["public_claim_allowed"] is False
    assert payload["publish_boundary"]["marketplace_listing_allowed"] is False
    assert payload["publish_boundary"]["proof_badge_allowed"] is False
    assert payload["pilot_learning_summary"]["outcome_tag"] == "not_collected"

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
        "pilot_decision_json",
    }
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["pilot_evidence_json"]["sha256"] == payload["pilot_evidence"]["body_sha256"]
    assert chain_by_kind["pilot_decision_json"]["file"] == PILOT_DECISION_JSON_NAME
    assert chain_by_kind["pilot_decision_json"]["sha256"] == payload["pilot_decision_body_sha256"]
    assert verify_pilot_decision_file(json_path)["pilot_decision_body_sha256"] == payload["pilot_decision_body_sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Pilot Decision" in markdown
    assert "NO_DECISION" in markdown
    assert "blocked reason: evidence_not_ready" in markdown
    assert "success rate: not collected" in markdown
    assert "Publish Boundary" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "pilot_decision_json" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_pilot_decision_records_final_choice_with_note_hash(tmp_path: Path) -> None:
    feedback_hash = "a" * 64
    issue_hash = "b" * 64
    note_hash = "c" * 64
    result = check_pilot_decision(
        tmp_path,
        feedback_private_sha256=feedback_hash,
        issue_intake_private_sha256=issue_hash,
        operator_decision="fix_before_next",
        operator_note_private_sha256=note_hash,
        outcome_tag="partial",
        friction_tags=["proof_trust"],
        missing_skill_tags=["harness_engineering"],
    )
    payload = json.loads(Path(result["pilot_decision_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "pilot_decision_recorded"
    assert result["verdict"] == "FIX_BEFORE_NEXT"
    assert payload["decision"]["recorded"] is True
    assert payload["decision"]["selected"] == "fix_before_next"
    assert payload["decision"]["blocked_reason"] == "none"
    assert payload["decision"]["operator_note_sha256"] == note_hash
    assert payload["decision"]["raw_operator_note_included"] is False
    assert payload["decision"]["next_stage"] == "patch_release_surface_before_next_pilot"
    assert payload["pilot_learning_summary"]["outcome_tag"] == "partial"
    assert payload["pilot_learning_summary"]["friction_tags"] == ["proof_trust"]
    assert payload["pilot_learning_summary"]["missing_skill_tags"] == ["harness_engineering"]
    assert payload["pilot_decision_checks"]["pilot_learning_summary_carried"] is True
    assert payload["metrics"]["success_rate"] is None
    assert payload["publish_boundary"]["marketplace_listing_allowed"] is False
    assert payload["pilot_decision_checks"]["recorded_decision_has_note_hash"] is True


def test_external_alpha_pilot_decision_hashes_private_files_without_leaking_paths(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    feedback_path = private_dir / "pilot-feedback.md"
    issue_path = private_dir / "pilot-issue.md"
    note_path = private_dir / "operator-decision-note.md"
    feedback_path.write_text("사용자 피드백 원문\n", encoding="utf-8")
    issue_path.write_text("이슈 인테이크 원문\n", encoding="utf-8")
    note_path.write_text("운영 판단 노트 원문\n", encoding="utf-8")
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()

    result = check_pilot_decision(
        tmp_path,
        feedback_private_file=feedback_path,
        issue_intake_private_file=issue_path,
        operator_decision="fix_before_next",
        operator_note_private_file=note_path,
        outcome_tag="blocked_runner",
        friction_tags=["runner"],
        missing_skill_tags=["support_diagnostics"],
    )
    json_path = Path(result["pilot_decision_json"])
    md_path = Path(result["pilot_decision_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert result["status"] == "pilot_decision_recorded"
    assert result["verdict"] == "FIX_BEFORE_NEXT"
    assert payload["decision"]["operator_note_sha256"] == expected_note_hash
    assert payload["decision"]["raw_operator_note_included"] is False
    assert payload["pilot_learning_summary"]["outcome_tag"] == "blocked_runner"

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(feedback_path) not in serialized
    assert str(issue_path) not in serialized
    assert str(note_path) not in serialized
    assert "pilot-feedback.md" not in serialized
    assert "pilot-issue.md" not in serialized
    assert "operator-decision-note.md" not in serialized
    assert "사용자 피드백 원문" not in serialized
    assert "이슈 인테이크 원문" not in serialized
    assert "운영 판단 노트 원문" not in serialized


def test_external_alpha_pilot_decision_rejects_placeholder_sent_at(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="real UTC manual-send timestamp"):
        check_pilot_decision(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="<sent-at-utc>",
            recipient_ack_private_sha256="c" * 64,
            feedback_private_sha256="d" * 64,
            issue_intake_private_sha256="e" * 64,
            operator_decision="fix_before_next",
            operator_note_private_sha256="f" * 64,
            outcome_tag="partial",
        )

    assert not (tmp_path / PILOT_DECISION_JSON_NAME).exists()
    assert not (tmp_path / PILOT_DECISION_MD_NAME).exists()


def test_external_alpha_pilot_decision_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(PILOT_DECISION_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha pilot-decision" in output
    assert "verdict         : NO_DECISION" in output
    assert (tmp_path / PILOT_DECISION_MD_NAME).is_file()
    assert (tmp_path / PILOT_DECISION_JSON_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / PILOT_DECISION_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_pilot_decision_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_pilot_decision(tmp_path)
    pilot_decision_path = Path(result["pilot_decision_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(PILOT_DECISION_SCRIPT), "--verify-pilot-decision", str(pilot_decision_path)],
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
    assert "[PASS] external alpha pilot-decision verification" in verify_output
    assert "verdict: NO_DECISION" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-pilot-decision.json"
    tampered = json.loads(pilot_decision_path.read_text(encoding="utf-8"))
    tampered["metrics"]["success_rate"] = 1.0
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(PILOT_DECISION_SCRIPT), "--verify-pilot-decision", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "pilot-decision 본문 해시가 일치하지 않습니다" in tampered_result.stdout + tampered_result.stderr

    chain_tampered_path = tmp_path / "tampered-pilot-decision-chain.json"
    chain_tampered = json.loads(pilot_decision_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_DECISION_SCRIPT), "--verify-pilot-decision", str(chain_tampered_path)],
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


    policy_tampered_path = tmp_path / "tampered-pilot-decision-policy.json"
    policy_tampered = json.loads(pilot_decision_path.read_text(encoding="utf-8"))
    policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["pilot_decision_body_sha256"] = _pilot_decision_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["pilot_decision_body_sha256"]
    policy_tampered["pilot_decision_checks"] = _pilot_decision_checks(policy_tampered)
    policy_tampered_path.write_text(
        json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    policy_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_DECISION_SCRIPT), "--verify-pilot-decision", str(policy_tampered_path)],
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


def test_external_alpha_pilot_decision_cli_hashes_private_files(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    feedback_path = private_dir / "pilot-feedback.md"
    issue_path = private_dir / "pilot-issue.md"
    note_path = private_dir / "operator-decision-note.md"
    feedback_path.write_text("사용자 피드백 원문\n", encoding="utf-8")
    issue_path.write_text("이슈 인테이크 원문\n", encoding="utf-8")
    note_path.write_text("운영 판단 노트 원문\n", encoding="utf-8")
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_DECISION_SCRIPT),
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
            "proof_trust,docs",
            "--missing-skill-tag",
            "harness_engineering,support_diagnostics",
            "--operator-note-private-file",
            str(note_path),
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
    payload_text = (tmp_path / PILOT_DECISION_JSON_NAME).read_text(encoding="utf-8")
    markdown = (tmp_path / PILOT_DECISION_MD_NAME).read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    assert "verdict         : FIX_BEFORE_NEXT" in output
    assert expected_note_hash in payload_text
    assert payload["pilot_learning_summary"]["friction_tags"] == ["proof_trust", "docs"]
    assert payload["pilot_learning_summary"]["missing_skill_tags"] == ["harness_engineering", "support_diagnostics"]
    assert str(feedback_path) not in payload_text + markdown
    assert str(issue_path) not in payload_text + markdown
    assert str(note_path) not in payload_text + markdown
    assert "pilot-feedback.md" not in payload_text + markdown
    assert "pilot-issue.md" not in payload_text + markdown
    assert "operator-decision-note.md" not in payload_text + markdown


def test_external_alpha_pilot_decision_cli_hashes_standard_private_workspace(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient-private.txt"
    note_path = private_dir / "operator-dispatch-note-private.md"
    ack_path = private_dir / "recipient-ack-private.txt"
    feedback_path = private_dir / "pilot-feedback-private.md"
    issue_path = private_dir / "pilot-issue-intake-private.md"
    decision_note_path = private_dir / "operator-decision-note-private.md"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("acknowledged start path\n", encoding="utf-8")
    feedback_path.write_text("feedback says builder flow was partially blocked\n", encoding="utf-8")
    issue_path.write_text("issue intake says runner terminology was confusing\n", encoding="utf-8")
    decision_note_path.write_text("operator says fix docs before next pilot\n", encoding="utf-8")
    expected_decision_note_hash = hashlib.sha256(decision_note_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_DECISION_SCRIPT),
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
    payload_text = (tmp_path / PILOT_DECISION_JSON_NAME).read_text(encoding="utf-8")
    markdown = (tmp_path / PILOT_DECISION_MD_NAME).read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    combined = payload_text + markdown
    assert "verdict         : FIX_BEFORE_NEXT" in output
    assert payload["decision"]["operator_note_sha256"] == expected_decision_note_hash
    assert payload["decision"]["raw_operator_note_included"] is False
    assert payload["pilot_learning_summary"]["outcome_tag"] == "partial"
    assert str(private_dir) not in combined
    for private_path in [recipient_path, note_path, ack_path, feedback_path, issue_path, decision_note_path]:
        assert private_path.name not in combined
    assert "operator says fix docs" not in combined


def test_external_alpha_pilot_decision_cli_rejects_workspace_decision_placeholder(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("sent by private channel\n", encoding="utf-8")
    (private_dir / "recipient-ack-private.txt").write_text("acknowledged start path\n", encoding="utf-8")
    (private_dir / "pilot-feedback-private.md").write_text("feedback collected\n", encoding="utf-8")
    (private_dir / "pilot-issue-intake-private.md").write_text("issue intake collected\n", encoding="utf-8")
    (private_dir / "operator-decision-note-private.md").write_text(
        "PRIVATE - DO NOT SHARE OR COMMIT\n"
        "Write the private decision rationale here after evidence is collected.\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_DECISION_SCRIPT),
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

    payload_text = ""
    markdown = ""
    assert result.returncode == 1
    assert "placeholder" in result.stdout + result.stderr
    assert "사용자 피드백 원문" not in payload_text + markdown
    assert "이슈 인테이크 원문" not in payload_text + markdown
    assert "운영 판단 노트 원문" not in payload_text + markdown
