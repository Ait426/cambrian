import json
import os
import subprocess
import sys
import hashlib
from pathlib import Path

import pytest

from scripts.build_external_alpha_release import RELEASE_SLUG
from scripts.check_external_alpha_dispatch_record import (
    DispatchRecordError,
    PREFLIGHT_RECEIPT_NAME,
    _preflight_receipt_body_sha256,
    check_dispatch_record,
)
from scripts.check_external_alpha_recipient_checkpoint import (
    RECIPIENT_CHECKPOINT_JSON_NAME,
    RECIPIENT_CHECKPOINT_MD_NAME,
    RecipientCheckpointError,
    _recipient_checkpoint_body_sha256,
    _recipient_checkpoint_checks,
    check_recipient_checkpoint,
    verify_recipient_checkpoint_file,
)


ROOT = Path(__file__).resolve().parents[1]
RECIPIENT_CHECKPOINT_SCRIPT = ROOT / "scripts" / "check_external_alpha_recipient_checkpoint.py"


def _write_ready_preflight_receipt(
    path: Path,
    *,
    archive_sha256: str,
    recipient_private_sha256: str,
    operator_dispatch_note_private_sha256: str,
) -> Path:
    payload = {
        "schema_version": "external_alpha_first_recipient_send_preflight_v0_1",
        "generated_at": "2026-05-15T00:00:00+00:00",
        "status": "pass",
        "verdict": "FIRST_RECIPIENT_PRE_SEND_READY",
        "safe_to_share": True,
        "release": {
            "zip_file": f"{RELEASE_SLUG}.zip",
            "archive_sha256": archive_sha256,
            "file_count": 1,
        },
        "operator_packet": {
            "file": "cambrian-agent-platform-external-alpha-operator-dispatch-packet.json",
            "body_sha256": "d" * 64,
            "copy_paste_message_sha256": "e" * 64,
        },
        "private_workspace": {
            "required_private_files": [
                {
                    "file": "recipient-private.txt",
                    "status": "ready",
                    "sha256": recipient_private_sha256,
                    "raw_value_included": False,
                    "local_path_included": False,
                },
                {
                    "file": "operator-dispatch-note-private.md",
                    "status": "ready",
                    "sha256": operator_dispatch_note_private_sha256,
                    "raw_value_included": False,
                    "local_path_included": False,
                },
            ],
            "raw_private_values_included": False,
            "local_paths_included": False,
            "send_recorded": False,
        },
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "pre_send_gate_only": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "checks": {"test_ready_preflight": True},
    }
    payload["first_recipient_send_preflight_receipt_body_sha256"] = _preflight_receipt_body_sha256(payload)
    payload["first_recipient_send_preflight_receipt_checks"] = {"test_receipt_self_check": True}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_builder_gold_path_share_receipt(path: Path) -> Path:
    capabilities = {
        "agent_pack_created": True,
        "manual_runner_receipt_created": True,
        "evolution_suggestion_created": True,
        "candidate_diff_report_created": True,
        "promoted_private_version_created": True,
        "promotion_audit_record_created": True,
        "private_hub_lineage_verified": True,
    }
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
        "capabilities_verified": capabilities,
        "proof_claim_allowed": False,
        "success_rate_claim_allowed": False,
        "sale_ready": False,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_external_alpha_recipient_checkpoint_waits_without_ack(tmp_path: Path) -> None:
    result = check_recipient_checkpoint(tmp_path)
    json_path = Path(result["recipient_checkpoint_json"])
    md_path = Path(result["recipient_checkpoint_md"])

    assert result["status"] == "awaiting_recipient_checkpoint"
    assert result["verdict"] == "WAITING_FOR_RECIPIENT"
    assert json_path.name == RECIPIENT_CHECKPOINT_JSON_NAME
    assert md_path.name == RECIPIENT_CHECKPOINT_MD_NAME
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "external_alpha_recipient_checkpoint_v0_1"
    assert payload["status"] == "awaiting_recipient_checkpoint"
    assert payload["verdict"] == "WAITING_FOR_RECIPIENT"
    assert payload["safe_to_share"] is True
    assert payload["recipient_checkpoint_body_sha256"] == _recipient_checkpoint_body_sha256(payload)
    assert all(payload["checks"].values())
    assert all(payload["recipient_checkpoint_checks"].values())
    assert payload["checks"]["dispatch_manual_only_policy"] is True
    assert payload["checks"]["dispatch_one_recipient_policy"] is True
    assert payload["checks"]["dispatch_private_hash_only_policy"] is True
    assert payload["recipient_checkpoint_checks"]["dispatch_manual_only_policy"] is True
    assert payload["recipient_checkpoint_checks"]["dispatch_one_recipient_policy"] is True
    assert payload["recipient_checkpoint_checks"]["dispatch_private_hash_only_policy"] is True
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
    assert payload["metrics"]["recipient_started"] is False
    assert payload["metrics"]["builder_gold_path_confirmed"] is False
    assert payload["metrics"]["success_rate"] is None
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["success_rate_claim_allowed"] is False
    assert payload["private_checkpoint_fingerprints"]["recipient_ack_sha256"] is None
    assert payload["private_checkpoint_fingerprints"]["builder_gold_path_share_receipt_sha256"] is None
    assert payload["private_checkpoint_fingerprints"]["raw_private_content_included"] is False
    assert payload["private_checkpoint_fingerprints"]["raw_builder_gold_path_receipt_path_included"] is False
    assert payload["shared_checkpoint"]["receipt"]["safe_to_share"] is True
    assert payload["shared_checkpoint"]["diagnostics"]["safe_to_share"] is True
    assert payload["shared_checkpoint"]["diagnostics"]["redaction_checks_all_true"] is True
    assert payload["shared_checkpoint"]["builder_gold_path"]["present"] is False

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
    }
    assert chain_by_kind["release_zip"]["file"] == f"{RELEASE_SLUG}.zip"
    assert chain_by_kind["release_zip"]["sha256"] == payload["release"]["archive_sha256"]
    assert chain_by_kind["dispatch_record_json"]["sha256"] == payload["dispatch_record"]["body_sha256"]
    assert chain_by_kind["recipient_checkpoint_json"]["file"] == RECIPIENT_CHECKPOINT_JSON_NAME
    assert chain_by_kind["recipient_checkpoint_json"]["sha256"] == payload["recipient_checkpoint_body_sha256"]
    assert verify_recipient_checkpoint_file(json_path)["recipient_checkpoint_body_sha256"] == payload[
        "recipient_checkpoint_body_sha256"
    ]

    markdown = md_path.read_text(encoding="utf-8")
    assert "Cambrian External Alpha Recipient Checkpoint" in markdown
    assert "WAITING_FOR_RECIPIENT" in markdown
    assert "Dispatch Execution Policy" in markdown
    assert "script sends to recipient: False" in markdown
    assert "manual operator dispatch required: True" in markdown
    assert "records private sha256 only: True" in markdown
    assert "recipient started: False" in markdown
    assert "recipient_checkpoint_json" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ROOT) not in serialized
    assert str(tmp_path) not in serialized
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in serialized


def test_external_alpha_recipient_checkpoint_records_ack_only_after_dispatch(tmp_path: Path) -> None:
    result = check_recipient_checkpoint(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_sha256="c" * 64,
    )
    payload = json.loads(Path(result["recipient_checkpoint_json"]).read_text(encoding="utf-8"))

    assert result["status"] == "recipient_checkpoint_recorded"
    assert result["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert payload["dispatch_record"]["sent_recorded"] is True
    assert payload["dispatch_execution_policy"]["sent_recorded_by_private_hashes_only"] is True
    assert payload["private_checkpoint_fingerprints"]["recipient_ack_sha256"] == "c" * 64
    assert payload["metrics"]["recipient_started"] is True
    assert payload["metrics"]["builder_gold_path_confirmed"] is False
    assert payload["recipient_checkpoint_checks"]["recorded_checkpoint_has_ack_hash"] is True


def test_external_alpha_synthetic_recipient_checkpoint_is_not_standalone_evidence(tmp_path: Path) -> None:
    result = check_recipient_checkpoint(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_sha256="c" * 64,
        allow_synthetic_rehearsal=True,
    )
    checkpoint_path = Path(result["recipient_checkpoint_json"])

    with pytest.raises(RecipientCheckpointError, match="not standalone recipient evidence"):
        verify_recipient_checkpoint_file(checkpoint_path)

    payload = verify_recipient_checkpoint_file(checkpoint_path, allow_synthetic_rehearsal=True)
    assert payload["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert payload["synthetic_rehearsal_boundary"]["synthetic_rehearsal"] is True
    assert payload["synthetic_rehearsal_boundary"]["standalone_recipient_evidence_allowed"] is False
    assert payload["synthetic_rehearsal_boundary"]["real_manual_send"] is False
    assert payload["synthetic_rehearsal_boundary"]["real_recipient_evidence"] is False
    assert payload["recipient_checkpoint_checks"]["synthetic_boundary_not_standalone_when_present"] is True


def test_external_alpha_recipient_checkpoint_rejects_placeholder_sent_at(tmp_path: Path) -> None:
    with pytest.raises(DispatchRecordError, match="real UTC manual-send timestamp"):
        check_recipient_checkpoint(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="<sent-at-utc>",
            recipient_ack_private_sha256="c" * 64,
        )

    assert not (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).exists()
    assert not (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).exists()


def test_external_alpha_recipient_checkpoint_blocks_missing_builder_gold_path_receipt(
    tmp_path: Path,
) -> None:
    missing_receipt_path = tmp_path / "external_alpha_builder_gold_path_share_receipt.json"

    with pytest.raises(
        RecipientCheckpointError,
        match="Builder Golden Path share receipt file is missing or still a placeholder",
    ):
        check_recipient_checkpoint(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="2026-05-11T10:00:00+00:00",
            recipient_ack_private_sha256="c" * 64,
            builder_gold_path_share_receipt=missing_receipt_path,
        )

    assert not (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).exists()
    assert not (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).exists()


def test_external_alpha_recipient_checkpoint_cli_rejects_placeholder_builder_receipt_safely(
    tmp_path: Path,
) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("sent by private channel\n", encoding="utf-8")
    (private_dir / "recipient-ack-private.txt").write_text("CONFIRMED\n", encoding="utf-8")
    placeholder = "<external_alpha_builder_gold_path_share_receipt.json>"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(RECIPIENT_CHECKPOINT_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--private-workspace-dir",
            str(private_dir),
            "--sent-at-utc",
            "2026-05-11T10:00:00+00:00",
            "--builder-gold-path-share-receipt",
            placeholder,
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
    assert "Builder Golden Path share receipt file is missing or still a placeholder." in output
    assert placeholder not in output
    assert str(ROOT) not in output
    assert str(tmp_path) not in output
    assert "pilot recipient private identifier" not in output
    assert "sent by private channel" not in output
    assert "CONFIRMED" not in output
    assert not (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).exists()
    assert not (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).exists()


def test_external_alpha_recipient_checkpoint_records_builder_gold_path_share_receipt(
    tmp_path: Path,
) -> None:
    receipt_path = _write_builder_gold_path_share_receipt(tmp_path / "external_alpha_builder_gold_path_share_receipt.json")
    expected_receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    result = check_recipient_checkpoint(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_sha256="c" * 64,
        builder_gold_path_share_receipt=receipt_path,
    )
    json_path = Path(result["recipient_checkpoint_json"])
    md_path = Path(result["recipient_checkpoint_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert result["status"] == "recipient_gold_path_confirmed"
    assert result["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert payload["shared_checkpoint"]["builder_gold_path"]["present"] is True
    assert payload["shared_checkpoint"]["builder_gold_path"]["sha256"] == expected_receipt_hash
    assert payload["shared_checkpoint"]["builder_gold_path"]["checks_all_true"] is True
    assert payload["shared_checkpoint"]["builder_gold_path"]["capabilities_all_true"] is True
    assert all(payload["shared_checkpoint"]["builder_gold_path"]["capabilities_verified"].values())
    assert payload["private_checkpoint_fingerprints"]["builder_gold_path_share_receipt_sha256"] == expected_receipt_hash
    assert payload["private_checkpoint_fingerprints"]["raw_builder_gold_path_receipt_path_included"] is False
    assert payload["metrics"]["builder_gold_path_confirmed"] is True
    assert all(payload["metrics"]["builder_gold_path_capabilities_verified"].values())
    assert payload["metrics"]["proof_claim_allowed"] is False
    assert payload["metrics"]["success_rate_claim_allowed"] is False
    assert payload["metrics"]["sale_ready"] is False
    assert payload["recipient_checkpoint_checks"]["builder_gold_path_receipt_valid_or_absent"] is True
    assert payload["recipient_checkpoint_checks"]["builder_gold_path_claim_boundaries_locked"] is True
    assert verify_recipient_checkpoint_file(json_path)["verdict"] == "RECIPIENT_GOLD_PATH_CONFIRMED"
    assert "RECIPIENT_GOLD_PATH_CONFIRMED" in markdown
    assert "Builder Golden Path Share Receipt" in markdown

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(receipt_path) not in serialized
    assert "external_alpha_builder_gold_path_share_receipt.json" in serialized


def test_external_alpha_recipient_checkpoint_blocks_builder_gold_path_without_ack(
    tmp_path: Path,
) -> None:
    receipt_path = _write_builder_gold_path_share_receipt(tmp_path / "external_alpha_builder_gold_path_share_receipt.json")

    try:
        check_recipient_checkpoint(
            tmp_path,
            recipient_private_sha256="a" * 64,
            operator_dispatch_note_private_sha256="b" * 64,
            sent_at_utc="2026-05-11T10:00:00+00:00",
            builder_gold_path_share_receipt=receipt_path,
        )
    except Exception as exc:  # noqa: BLE001
        assert "recipient ack" in str(exc)
    else:
        raise AssertionError("Builder Golden Path receipt without recipient ack should be blocked")


def test_external_alpha_recipient_checkpoint_hashes_private_ack_file_without_leaking_path(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    ack_path = private_dir / "recipient-ack.txt"
    ack_path.write_text("확인 완료\n", encoding="utf-8")
    expected_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()

    result = check_recipient_checkpoint(
        tmp_path,
        recipient_private_sha256="a" * 64,
        operator_dispatch_note_private_sha256="b" * 64,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_file=ack_path,
    )
    json_path = Path(result["recipient_checkpoint_json"])
    md_path = Path(result["recipient_checkpoint_md"])
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert result["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert payload["private_checkpoint_fingerprints"]["recipient_ack_sha256"] == expected_hash
    assert payload["metrics"]["recipient_started"] is True

    serialized = json.dumps(payload, ensure_ascii=False) + markdown
    assert str(ack_path) not in serialized
    assert "recipient-ack.txt" not in serialized
    assert "확인 완료" not in serialized


def test_external_alpha_recipient_checkpoint_hashes_dispatch_private_files_without_leaking_paths(
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

    result = check_recipient_checkpoint(
        tmp_path,
        recipient_private_file=recipient_path,
        operator_dispatch_note_private_file=note_path,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        recipient_ack_private_file=ack_path,
    )
    checkpoint_json = Path(result["recipient_checkpoint_json"])
    checkpoint_md = Path(result["recipient_checkpoint_md"])
    dispatch_json = Path(result["dispatch_record_json"])
    checkpoint_payload = json.loads(checkpoint_json.read_text(encoding="utf-8"))
    dispatch_payload = json.loads(dispatch_json.read_text(encoding="utf-8"))

    assert result["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert checkpoint_payload["private_checkpoint_fingerprints"]["recipient_ack_sha256"] == expected_ack_hash
    assert dispatch_payload["dispatch_record"]["recipient_private_sha256"] == expected_recipient_hash
    assert dispatch_payload["dispatch_record"]["operator_dispatch_note_private_sha256"] == expected_note_hash

    serialized = (
        json.dumps(checkpoint_payload, ensure_ascii=False)
        + checkpoint_md.read_text(encoding="utf-8")
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


def test_external_alpha_recipient_checkpoint_requires_preflight_when_requested_for_private_workspace(
    tmp_path: Path,
) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("sent by private channel\n", encoding="utf-8")
    (private_dir / "recipient-ack-private.txt").write_text("?뺤씤 ?꾨즺\n", encoding="utf-8")

    with pytest.raises(Exception, match="pre-send preflight receipt"):
        check_recipient_checkpoint(
            tmp_path,
            private_workspace_dir=private_dir,
            sent_at_utc="2026-05-11T10:00:00+00:00",
            require_preflight_receipt=True,
        )


def test_external_alpha_recipient_checkpoint_carries_required_preflight_chain_for_private_workspace(
    tmp_path: Path,
) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient-private.txt"
    note_path = private_dir / "operator-dispatch-note-private.md"
    ack_path = private_dir / "recipient-ack-private.txt"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("?뺤씤 ?꾨즺\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()

    release = check_dispatch_record(tmp_path)
    _write_ready_preflight_receipt(
        private_dir / PREFLIGHT_RECEIPT_NAME,
        archive_sha256=release["archive_sha256"],
        recipient_private_sha256=expected_recipient_hash,
        operator_dispatch_note_private_sha256=expected_note_hash,
    )

    result = check_recipient_checkpoint(
        tmp_path,
        skip_build=True,
        private_workspace_dir=private_dir,
        sent_at_utc="2026-05-11T10:00:00+00:00",
        require_preflight_receipt=True,
    )
    payload = json.loads(Path(result["recipient_checkpoint_json"]).read_text(encoding="utf-8"))
    chain_by_kind = {item["kind"]: item for item in payload["artifact_chain"]}

    assert result["verdict"] == "RECIPIENT_CHECKPOINT_RECORDED"
    assert payload["dispatch_record"]["pre_send_preflight"]["required"] is True
    assert payload["dispatch_record"]["pre_send_preflight"]["file"] == PREFLIGHT_RECEIPT_NAME
    assert payload["dispatch_record"]["pre_send_preflight"]["verified_standalone"] is True
    assert "pre_send_preflight_receipt_json" in chain_by_kind
    assert (
        chain_by_kind["pre_send_preflight_receipt_json"]["sha256"]
        == payload["dispatch_record"]["pre_send_preflight"]["body_sha256"]
    )
    assert payload["checks"]["dispatch_preflight_gate_ready_when_required"] is True
    assert payload["recipient_checkpoint_checks"]["artifact_chain_preflight_hash_matched_when_used"] is True


def test_external_alpha_recipient_checkpoint_cli_passes(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["CAMBRIAN_FAKE_SECRET_FOR_TEST"] = "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"

    result = subprocess.run(
        [sys.executable, str(RECIPIENT_CHECKPOINT_SCRIPT), "--output-dir", str(tmp_path)],
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
    assert "[PASS] external alpha recipient-checkpoint" in output
    assert "verdict                 : WAITING_FOR_RECIPIENT" in output
    assert (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).is_file()
    assert (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).is_file()
    assert "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS" not in (
        tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME
    ).read_text(encoding="utf-8")


def test_external_alpha_recipient_checkpoint_cli_verifier_passes_and_rejects_tampering(tmp_path: Path) -> None:
    result = check_recipient_checkpoint(tmp_path)
    checkpoint_path = Path(result["recipient_checkpoint_json"])
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    verify_result = subprocess.run(
        [sys.executable, str(RECIPIENT_CHECKPOINT_SCRIPT), "--verify-recipient-checkpoint", str(checkpoint_path)],
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
    assert "[PASS] external alpha recipient-checkpoint verification" in verify_output
    assert "verdict: WAITING_FOR_RECIPIENT" in verify_output
    assert "body   :" in verify_output

    tampered_path = tmp_path / "tampered-recipient-checkpoint.json"
    tampered = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    tampered["metrics"]["success_rate"] = 1.0
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tampered_result = subprocess.run(
        [sys.executable, str(RECIPIENT_CHECKPOINT_SCRIPT), "--verify-recipient-checkpoint", str(tampered_path)],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert tampered_result.returncode == 1
    assert "recipient-checkpoint 본문 해시가 일치하지 않습니다" in (
        tampered_result.stdout + tampered_result.stderr
    )

    chain_tampered_path = tmp_path / "tampered-recipient-checkpoint-chain.json"
    chain_tampered = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    chain_tampered["artifact_chain"][-1]["sha256"] = "f" * 64
    chain_tampered_path.write_text(json.dumps(chain_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    chain_tampered_result = subprocess.run(
        [sys.executable, str(RECIPIENT_CHECKPOINT_SCRIPT), "--verify-recipient-checkpoint", str(chain_tampered_path)],
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


    policy_tampered_path = tmp_path / "tampered-recipient-checkpoint-policy.json"
    policy_tampered = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    policy_tampered["dispatch_execution_policy"]["script_sends_to_recipient"] = True
    policy_tampered["recipient_checkpoint_body_sha256"] = _recipient_checkpoint_body_sha256(policy_tampered)
    policy_tampered["artifact_chain"][-1]["sha256"] = policy_tampered["recipient_checkpoint_body_sha256"]
    policy_tampered["recipient_checkpoint_checks"] = _recipient_checkpoint_checks(policy_tampered)
    policy_tampered_path.write_text(json.dumps(policy_tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    policy_tampered_result = subprocess.run(
        [sys.executable, str(RECIPIENT_CHECKPOINT_SCRIPT), "--verify-recipient-checkpoint", str(policy_tampered_path)],
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


def test_external_alpha_recipient_checkpoint_cli_hashes_private_ack_file(tmp_path: Path) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    ack_path = private_dir / "recipient-ack.txt"
    ack_path.write_text("확인 완료\n", encoding="utf-8")
    expected_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(RECIPIENT_CHECKPOINT_SCRIPT),
            "--output-dir",
            str(tmp_path),
            "--recipient-private-sha256",
            "a" * 64,
            "--operator-dispatch-note-private-sha256",
            "b" * 64,
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
    payload_text = (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).read_text(encoding="utf-8")
    markdown = (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).read_text(encoding="utf-8")
    assert "verdict                 : RECIPIENT_CHECKPOINT_RECORDED" in output
    assert expected_hash in payload_text
    assert str(ack_path) not in payload_text + markdown
    assert "recipient-ack.txt" not in payload_text + markdown
    assert "확인 완료" not in payload_text + markdown


def test_external_alpha_recipient_checkpoint_cli_hashes_dispatch_private_files(tmp_path: Path) -> None:
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
            str(RECIPIENT_CHECKPOINT_SCRIPT),
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
    checkpoint_text = (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).read_text(encoding="utf-8")
    checkpoint_markdown = (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).read_text(encoding="utf-8")
    dispatch_text = (tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json").read_text(
        encoding="utf-8"
    )
    combined = checkpoint_text + checkpoint_markdown + dispatch_text
    assert "verdict                 : RECIPIENT_CHECKPOINT_RECORDED" in output
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


def test_external_alpha_recipient_checkpoint_cli_hashes_standard_private_workspace(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    recipient_path = private_dir / "recipient-private.txt"
    note_path = private_dir / "operator-dispatch-note-private.md"
    ack_path = private_dir / "recipient-ack-private.txt"
    recipient_path.write_text("pilot recipient private identifier\n", encoding="utf-8")
    note_path.write_text("sent by private channel\n", encoding="utf-8")
    ack_path.write_text("?뺤씤 ?꾨즺\n", encoding="utf-8")
    expected_recipient_hash = hashlib.sha256(recipient_path.read_bytes()).hexdigest()
    expected_note_hash = hashlib.sha256(note_path.read_bytes()).hexdigest()
    expected_ack_hash = hashlib.sha256(ack_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(RECIPIENT_CHECKPOINT_SCRIPT),
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
    checkpoint_text = (tmp_path / RECIPIENT_CHECKPOINT_JSON_NAME).read_text(encoding="utf-8")
    checkpoint_markdown = (tmp_path / RECIPIENT_CHECKPOINT_MD_NAME).read_text(encoding="utf-8")
    dispatch_text = (tmp_path / "cambrian-agent-platform-external-alpha-dispatch-record.json").read_text(
        encoding="utf-8"
    )
    combined = checkpoint_text + checkpoint_markdown + dispatch_text
    assert "verdict                 : RECIPIENT_CHECKPOINT_RECORDED" in output
    assert expected_ack_hash in checkpoint_text
    assert expected_recipient_hash in dispatch_text
    assert expected_note_hash in dispatch_text
    assert str(private_dir) not in combined
    assert "recipient-private.txt" not in combined
    assert "operator-dispatch-note-private.md" not in combined
    assert "recipient-ack-private.txt" not in combined
    assert "pilot recipient private identifier" not in combined
    assert "sent by private channel" not in combined


def test_external_alpha_recipient_checkpoint_cli_rejects_workspace_ack_placeholder(tmp_path: Path) -> None:
    private_dir = tmp_path / "private-workspace"
    private_dir.mkdir()
    (private_dir / "recipient-private.txt").write_text("pilot recipient private identifier\n", encoding="utf-8")
    (private_dir / "operator-dispatch-note-private.md").write_text("sent by private channel\n", encoding="utf-8")
    (private_dir / "recipient-ack-private.txt").write_text(
        "PRIVATE - DO NOT SHARE OR COMMIT\nPaste only the private acknowledgement text here after the recipient replies.\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [
            sys.executable,
            str(RECIPIENT_CHECKPOINT_SCRIPT),
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
