import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import DispatchRecordError
from scripts.check_external_alpha_pilot_iteration import (
    PILOT_ITERATION_JSON_NAME,
    PILOT_ITERATION_MD_NAME,
    _pilot_iteration_body_sha256,
    _pilot_iteration_checks,
    check_pilot_iteration,
    verify_pilot_iteration_file,
)


ROOT = Path(__file__).resolve().parents[1]
PILOT_ITERATION_SCRIPT = ROOT / "scripts" / "check_external_alpha_pilot_iteration.py"


def test_external_alpha_pilot_iteration_blocks_without_decision(tmp_path: Path) -> None:
    result = check_pilot_iteration(tmp_path)
    json_path = Path(result["pilot_iteration_json"])
    md_path = Path(result["pilot_iteration_md"])

    assert result["status"] == "iteration_blocked"
    assert result["verdict"] == "NO_ITERATION"
    assert json_path.name == PILOT_ITERATION_JSON_NAME
    assert md_path.name == PILOT_ITERATION_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_pilot_iteration_v0_1"
    assert payload["status"] == "iteration_blocked"
    assert payload["verdict"] == "NO_ITERATION"
    assert payload["safe_to_share"] is True
    assert payload["pilot_iteration_body_sha256"] == _pilot_iteration_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["pilot_iteration_checks"].values())
    assert payload["checks"]["dispatch_manual_only_policy"] is True
    assert payload["checks"]["dispatch_one_recipient_policy"] is True
    assert payload["checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["pilot_iteration_checks"]["dispatch_manual_only_policy"] is True
    assert payload["pilot_iteration_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["pilot_iteration_checks"]["dispatch_private_hash_only_policy"] is True
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
    assert payload["iteration_plan"]["max_next_participants"] == 0
    assert payload["iteration_plan"]["scaling_allowed"] is False
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["publish_boundary"]["cohort_scaling_allowed"] is False
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
        "pilot_iteration_json",
    }
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["pilot_decision_json"]["sha256"] == payload["pilot_decision"]["body_sha256"]
    assert chain_by_kind["pilot_iteration_json"]["file"] == PILOT_ITERATION_JSON_NAME
    assert chain_by_kind["pilot_iteration_json"]["sha256"] == payload["pilot_iteration_body_sha256"]
    assert verify_pilot_iteration_file(json_path)["pilot_iteration_body_sha256"] == payload["pilot_iteration_body_sha256"]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Pilot Iteration" in markdown
    assert "NO_ITERATION" in markdown
    assert "max next participants: 0" in markdown
    assert "cohort scaling allowed: False" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "pilot_iteration_json" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


    policy_tampered_path = tmp_path / "tampered-pilot-iteration-policy.json"
    policy_tampered = json.loads(json_path.read_text(encoding="utf-8"))
    policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["pilot_iteration_body_sha256"] = _pilot_iteration_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["pilot_iteration_body_sha256"]
    policy_tampered["pilot_iteration_checks"] = _pilot_iteration_checks(policy_tampered)
    policy_tampered_path.write_text(
        json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert "dispatch_manual_only_policy" in policy_tampered["pilot_iteration_checks"]
    try:
        verify_pilot_iteration_file(policy_tampered_path)
    except Exception as exc:  # noqa: BLE001 - 변조 방어 테스트는 실패 이름을 확인한다.
        assert "dispatch_manual_only_policy" in str(exc)
    else:
        raise AssertionError("dispatch policy tampering must fail verification")


def test_external_alpha_pilot_iteration_allows_only_one_more_after_continue(tmp_path: Path) -> None:
    result = check_pilot_iteration(
        tmp_path,
        feedback_private_sha256="a" * 64,
        issue_intake_private_sha256="b" * 64,
        operator_decision="continue",
        operator_note_private_sha256="c" * 64,
        outcome_tag="completed_gold_path",
        friction_tags=["none"],
        missing_skill_tags=["none"],
    )
    payload = json.loads(Path(result["pilot_iteration_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "next_single_pilot_ready"
    assert result["verdict"] == "SEND_ONE_MORE"
    assert payload["iteration_plan"]["max_next_participants"] == 1
    assert payload["iteration_plan"]["scaling_allowed"] is False
    assert payload["pilot_decision"]["selected"] == "continue"
    assert payload["pilot_learning_summary"]["outcome_tag"] == "completed_gold_path"
    assert payload["pilot_iteration_checks"]["pilot_learning_summary_carried"] is True
    assert payload["publish_boundary"]["marketplace_listing_allowed"] is False
    assert payload["pilot_iteration_checks"]["continue_limited_to_one"] is True


def test_external_alpha_pilot_iteration_routes_fix_and_stop_without_sending(tmp_path: Path) -> None:
    fix_result = check_pilot_iteration(
        tmp_path / "fix",
        feedback_private_sha256="a" * 64,
        issue_intake_private_sha256="b" * 64,
        operator_decision="fix_before_next",
        operator_note_private_sha256="c" * 64,
        outcome_tag="partial",
        friction_tags=["docs"],
        missing_skill_tags=["skill_search"],
    )
    fix_payload = json.loads(Path(fix_result["pilot_iteration_json"]).read_text(encoding="utf-8"))
    assert fix_result["status"] == "patch_required_before_next_pilot"
    assert fix_result["verdict"] == "PATCH_BEFORE_NEXT"
    assert fix_payload["iteration_plan"]["max_next_participants"] == 0
    assert "rerun verify_platform_alpha" in fix_payload["iteration_plan"]["required_before_next"]

    stop_result = check_pilot_iteration(
        tmp_path / "stop",
        feedback_private_sha256="d" * 64,
        issue_intake_private_sha256="e" * 64,
        operator_decision="stop_and_redesign",
        operator_note_private_sha256="f" * 64,
        outcome_tag="blocked_trust",
        friction_tags=["proof_trust"],
        missing_skill_tags=["harness_engineering"],
    )
    stop_payload = json.loads(Path(stop_result["pilot_iteration_json"]).read_text(encoding="utf-8"))
    assert stop_result["status"] == "external_pilot_stopped"
    assert stop_result["verdict"] == "STOPPED_FOR_REDESIGN"
    assert stop_payload["iteration_plan"]["max_next_participants"] == 0
    assert "stop external sends" in stop_payload["iteration_plan"]["required_before_next"]


def test_external_alpha_pilot_iteration_rejects_placeholder_sent_at(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="real UTC manual-send timestamp"):
        check_pilot_iteration(
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

    assert not (tmp_path / PILOT_ITERATION_JSON_NAME).exists()
    assert not (tmp_path / PILOT_ITERATION_MD_NAME).exists()


def test_external_alpha_pilot_iteration_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(PILOT_ITERATION_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha pilot-iteration" in output
    assert "verdict          : NO_ITERATION" in output
    assert (tmp_path / PILOT_ITERATION_MD_NAME).is_file()
    assert (tmp_path / PILOT_ITERATION_JSON_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (tmp_path / PILOT_ITERATION_JSON_NAME).read_text(encoding="utf-8")


def test_external_alpha_pilot_iteration_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_pilot_iteration(tmp_path)
    pilot_iteration_path = Path(result["pilot_iteration_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(PILOT_ITERATION_SCRIPT), "--verify-pilot-iteration", str(pilot_iteration_path)],
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
    assert "[PASS] external alpha pilot-iteration verification" in verify_output
    assert "verdict: NO_ITERATION" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-pilot-iteration.json"
    tampered = json.loads(pilot_iteration_path.read_text(encoding="utf-8"))
    tampered["iteration_plan"]["scaling_allowed"] = True
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(PILOT_ITERATION_SCRIPT), "--verify-pilot-iteration", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "pilot-iteration 본문 해시가 일치하지 않습니다" in tampered_result.stdout + tampered_result.stderr

    chain_tampered_path = tmp_path / "tampered-pilot-iteration-chain.json"
    chain_tampered = json.loads(pilot_iteration_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(PILOT_ITERATION_SCRIPT), "--verify-pilot-iteration", str(chain_tampered_path)],
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


def test_external_alpha_pilot_iteration_cli_hashes_standard_private_workspace(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("sent by private channel\n", encoding="utf-8")
    (private_dir / "recipient-ack-private.txt").write_text("acknowledged start path\n", encoding="utf-8")
    (private_dir / "pilot-feedback-private.md").write_text("feedback says gold path completed\n", encoding="utf-8")
    (private_dir / "pilot-issue-intake-private.md").write_text("no blocking issue\n", encoding="utf-8")
    (private_dir / "operator-decision-note-private.md").write_text("continue with one more pilot only\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(PILOT_ITERATION_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--private-workspace-dir",
            str(private_dir),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
            "--operator-decision",
            "continue",
            "--outcome-tag",
            "completed_gold_path",
            "--friction-tag",
            "none",
            "--missing-skill-tag",
            "none",
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
    payload_text = (tmp_path / PILOT_ITERATION_JSON_NAME).read_text(encoding="utf-8")
    markdown = (tmp_path / PILOT_ITERATION_MD_NAME).read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    combined = payload_text + markdown
    assert "verdict          : SEND_ONE_MORE" in output
    assert payload["iteration_plan"]["max_next_participants"] == 1
    assert payload["iteration_plan"]["scaling_allowed"] is False
    assert payload["pilot_decision"]["selected"] == "continue"
    assert str(private_dir) not in combined
    for filename in [
        "recipient-private.txt",
        "operator-dispatch-note-private.md",
        "recipient-ack-private.txt",
        "pilot-feedback-private.md",
        "pilot-issue-intake-private.md",
        "operator-decision-note-private.md",
    ]:
        assert filename not in combined
    assert "continue with one more pilot only" not in combined
