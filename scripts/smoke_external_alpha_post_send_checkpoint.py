"""Rehearse the external alpha post-send checkpoint without real recipient evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_dispatch_record import (  # noqa: E402
    DISPATCH_RECORD_JSON_NAME,
    PREFLIGHT_RECEIPT_NAME,
    verify_dispatch_record_file,
)
from scripts.check_external_alpha_first_recipient_post_send_sequence import (  # noqa: E402
    check_first_recipient_post_send_sequence,
    verify_first_recipient_post_send_sequence_receipt_file,
)
from scripts.check_external_alpha_pilot_iteration import check_pilot_iteration  # noqa: E402
from scripts.check_external_alpha_pilot_ready import PILOT_READY_JSON_NAME, verify_pilot_ready_file  # noqa: E402
from scripts.check_external_alpha_recipient_checkpoint import (  # noqa: E402
    BUILDER_GOLD_PATH_REQUIRED_CAPABILITIES,
    BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA_VERSION,
    RECIPIENT_CHECKPOINT_JSON_NAME,
    verify_recipient_checkpoint_file,
)
from scripts.external_alpha_operator_note_template import operator_dispatch_note_template  # noqa: E402


POST_SEND_REHEARSAL_SCHEMA_VERSION = "external_alpha_post_send_checkpoint_rehearsal_v0_1"
POST_SEND_REHEARSAL_RECEIPT_NAME = f"{RELEASE_SLUG}-post-send-rehearsal-receipt.json"
BUILDER_GOLD_PATH_RECEIPT_NAME = "external_alpha_builder_gold_path_share_receipt.json"
PREFLIGHT_CONTRACT_JSON_NAME = f"{RELEASE_SLUG}-post-send-rehearsal-preflight-contract.json"

PRIVATE_MARKERS = (
    "POST_SEND_REHEARSAL_PRIVATE_RECIPIENT",
    "POST_SEND_REHEARSAL_PRIVATE_OPERATOR_NOTE",
)
POST_SEND_PRIVATE_WORKSPACE_FILES = (
    "recipient-private.txt",
    "operator-dispatch-note-private.md",
    "recipient-ack-private.txt",
)

logger = logging.getLogger(__name__)


class PostSendCheckpointRehearsalError(RuntimeError):
    """Post-send checkpoint rehearsal generation or verification failed."""


def smoke_post_send_checkpoint(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Run a private-input rehearsal and write a share-safe receipt."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    use_existing_release_artifacts = _has_existing_release_artifacts(output_dir)

    with tempfile.TemporaryDirectory(prefix="cambrian-external-alpha-post-send-") as temp_name:
        temp_root = Path(temp_name).resolve()
        work_dir = temp_root / "release"
        private_dir = temp_root / "private"
        work_dir.mkdir()
        private_dir.mkdir()
        if use_existing_release_artifacts:
            _copy_output_files(output_dir, work_dir)

        check_pilot_iteration(
            output_dir=work_dir,
            skip_build=use_existing_release_artifacts,
        )

        from scripts.check_external_alpha_first_recipient_send_preflight import (  # noqa: PLC0415
            _check_first_recipient_send_preflight_with_loaded_operator_packet,
            verify_first_recipient_send_preflight_receipt_file,
        )

        pilot_ready = verify_pilot_ready_file(work_dir / PILOT_READY_JSON_NAME)
        preflight_dispatch = verify_dispatch_record_file(work_dir / DISPATCH_RECORD_JSON_NAME)
        operator_contract = _preflight_operator_contract(
            dispatch_record=preflight_dispatch,
            pilot_ready=pilot_ready,
        )
        contract_path = work_dir / PREFLIGHT_CONTRACT_JSON_NAME
        _write_json(contract_path, operator_contract)
        release_hash = str(operator_contract["release"]["archive_sha256"])

        _write_private_file(
            private_dir / "recipient-private.txt",
            "POST_SEND_REHEARSAL_PRIVATE_RECIPIENT recipient@example.invalid\n",
        )
        _write_private_file(
            private_dir / "operator-dispatch-note-private.md",
            operator_dispatch_note_template(release_hash).replace(
                "<private-send-channel>",
                "direct message",
            ),
        )
        _write_private_file(
            private_dir / "recipient-ack-private.txt",
            "CONFIRMED\n",
        )
        builder_receipt_file = _write_builder_gold_path_share_receipt(
            private_dir / BUILDER_GOLD_PATH_RECEIPT_NAME
        )
        _check_first_recipient_send_preflight_with_loaded_operator_packet(
            private_dir,
            operator_packet=operator_contract,
            operator_packet_path=contract_path,
        )
        preflight = verify_first_recipient_send_preflight_receipt_file(
            private_dir / PREFLIGHT_RECEIPT_NAME,
            require_ready=True,
        )

        result = check_first_recipient_post_send_sequence(
            private_dir,
            output_dir=work_dir,
            sent_at_utc="2026-05-15T00:00:00+00:00",
            builder_gold_path_share_receipt=builder_receipt_file,
            require_gold_path=True,
            require_operator_bypass_audit=False,
            synthetic_rehearsal_without_real_recipient=True,
        )

        sequence_path = Path(str(result["receipt_json"]))
        checkpoint_path = work_dir / RECIPIENT_CHECKPOINT_JSON_NAME
        dispatch_path = work_dir / DISPATCH_RECORD_JSON_NAME
        sequence = verify_first_recipient_post_send_sequence_receipt_file(sequence_path)
        checkpoint = verify_recipient_checkpoint_file(checkpoint_path, allow_synthetic_rehearsal=True)
        dispatch = verify_dispatch_record_file(dispatch_path, allow_synthetic_rehearsal=True)
        generated_text = _generated_text(work_dir)
        payload = _rehearsal_payload(
            sequence=sequence,
            checkpoint=checkpoint,
            dispatch=dispatch,
            preflight=preflight,
            generated_text=generated_text,
            temp_root=temp_root,
            private_workspace_file_names={path.name for path in private_dir.iterdir() if path.is_file()},
            operator_note_template_used=True,
        )

    receipt_path = output_dir / POST_SEND_REHEARSAL_RECEIPT_NAME
    _write_json(receipt_path, payload)
    verify_post_send_rehearsal_receipt_file(receipt_path)
    _assert_shareable_file(receipt_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "archive_sha256": payload["release"]["archive_sha256"],
        "receipt_body_sha256": payload["post_send_rehearsal_receipt_body_sha256"],
    }


def verify_post_send_rehearsal_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_post_send_rehearsal_receipt_payload(payload)
    return payload


def verify_post_send_rehearsal_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != POST_SEND_REHEARSAL_SCHEMA_VERSION:
        raise PostSendCheckpointRehearsalError("post-send rehearsal schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "REHEARSAL_PASS":
        raise PostSendCheckpointRehearsalError("post-send rehearsal did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PostSendCheckpointRehearsalError("post-send rehearsal safe_to_share must be true.")
    if payload.get("real_recipient_evidence") is not False:
        raise PostSendCheckpointRehearsalError("post-send rehearsal must not claim real recipient evidence.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise PostSendCheckpointRehearsalError("post-send rehearsal checks failed.")
    if payload.get("post_send_rehearsal_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PostSendCheckpointRehearsalError("post-send rehearsal receipt body hash mismatch.")
    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden = [str(ROOT), str(Path.home()), *PRIVATE_MARKERS]
    leaked = [item for item in forbidden if item and item in serialized]
    if leaked:
        raise PostSendCheckpointRehearsalError("post-send rehearsal receipt contains private material.")


def _rehearsal_payload(
    *,
    sequence: dict[str, Any],
    checkpoint: dict[str, Any],
    dispatch: dict[str, Any],
    preflight: dict[str, Any],
    generated_text: str,
    temp_root: Path,
    private_workspace_file_names: set[str],
    operator_note_template_used: bool,
) -> dict[str, Any]:
    release = checkpoint.get("release") if isinstance(checkpoint.get("release"), dict) else {}
    dispatch_policy = (
        checkpoint.get("dispatch_execution_policy")
        if isinstance(checkpoint.get("dispatch_execution_policy"), dict)
        else {}
    )
    checkpoint_metrics = checkpoint.get("metrics") if isinstance(checkpoint.get("metrics"), dict) else {}
    dispatch_record = dispatch.get("dispatch_record") if isinstance(dispatch.get("dispatch_record"), dict) else {}
    private_fingerprints = (
        checkpoint.get("private_checkpoint_fingerprints")
        if isinstance(checkpoint.get("private_checkpoint_fingerprints"), dict)
        else {}
    )
    shared_checkpoint = (
        checkpoint.get("shared_checkpoint") if isinstance(checkpoint.get("shared_checkpoint"), dict) else {}
    )
    sequence_gate_receipts = (
        sequence.get("gate_receipts") if isinstance(sequence.get("gate_receipts"), dict) else {}
    )
    sequence_dispatch = (
        sequence_gate_receipts.get("dispatch_record")
        if isinstance(sequence_gate_receipts.get("dispatch_record"), dict)
        else {}
    )
    sequence_preflight = (
        sequence_dispatch.get("preflight") if isinstance(sequence_dispatch.get("preflight"), dict) else {}
    )
    sequence_final_audit = (
        sequence_gate_receipts.get("final_send_chain_audit")
        if isinstance(sequence_gate_receipts.get("final_send_chain_audit"), dict)
        else {}
    )
    sequence_policy = sequence.get("policy") if isinstance(sequence.get("policy"), dict) else {}
    builder_gold_path = (
        shared_checkpoint.get("builder_gold_path")
        if isinstance(shared_checkpoint.get("builder_gold_path"), dict)
        else {}
    )
    preflight_private = (
        preflight.get("private_workspace") if isinstance(preflight.get("private_workspace"), dict) else {}
    )
    preflight_files = (
        preflight_private.get("required_private_files")
        if isinstance(preflight_private.get("required_private_files"), list)
        else []
    )
    preflight_operator_note = next(
        (
            item
            for item in preflight_files
            if isinstance(item, dict) and item.get("file") == "operator-dispatch-note-private.md"
        ),
        {},
    )
    synthetic_boundary = (
        dispatch.get("synthetic_rehearsal_boundary")
        if isinstance(dispatch.get("synthetic_rehearsal_boundary"), dict)
        else {}
    )
    checkpoint_synthetic_boundary = (
        checkpoint.get("synthetic_rehearsal_boundary")
        if isinstance(checkpoint.get("synthetic_rehearsal_boundary"), dict)
        else {}
    )
    temp_path = str(temp_root)
    checks = {
        "preflight_generated_by_real_gate": preflight.get("status") == "pass"
        and preflight.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY",
        "operator_note_template_used": operator_note_template_used,
        "operator_note_template_preflight_contract": preflight_operator_note.get("mentions_channel") is True
        and preflight_operator_note.get("contains_release_hash") is True,
        "post_send_sequence_used": sequence.get("verdict") == "RECIPIENT_GOLD_PATH_CONFIRMED",
        "post_send_sequence_required_preflight": sequence_preflight.get("required") is True
        and sequence_preflight.get("verified_standalone") is True
        and _looks_like_sha256(sequence_preflight.get("body_sha256")),
        "post_send_sequence_manual_only": sequence_policy.get("script_sends_to_recipient") is False
        and sequence_policy.get("manual_operator_dispatch_required") is True
        and sequence_policy.get("post_send_sequence_only") is True,
        "dispatch_recorded_by_private_hashes": dispatch.get("verdict") == "SENT_ONE_RECORDED"
        and dispatch_record.get("sent_recorded") is True
        and _looks_like_sha256(dispatch_record.get("recipient_private_sha256"))
        and _looks_like_sha256(dispatch_record.get("operator_dispatch_note_private_sha256")),
        "synthetic_dispatch_not_standalone_proof": synthetic_boundary.get("synthetic_rehearsal") is True
        and synthetic_boundary.get("standalone_send_evidence_allowed") is False
        and synthetic_boundary.get("real_manual_send") is False
        and synthetic_boundary.get("real_recipient_evidence") is False,
        "recipient_checkpoint_gold_path_confirmed": checkpoint.get("verdict")
        == "RECIPIENT_GOLD_PATH_CONFIRMED",
        "synthetic_checkpoint_not_standalone_proof": checkpoint_synthetic_boundary.get("synthetic_rehearsal")
        is True
        and checkpoint_synthetic_boundary.get("standalone_recipient_evidence_allowed") is False
        and checkpoint_synthetic_boundary.get("real_manual_send") is False
        and checkpoint_synthetic_boundary.get("real_recipient_evidence") is False,
        "recipient_ack_hash_recorded": _looks_like_sha256(private_fingerprints.get("recipient_ack_sha256")),
        "builder_gold_path_receipt_accepted": builder_gold_path.get("present") is True
        and builder_gold_path.get("checks_all_true") is True
        and builder_gold_path.get("capabilities_all_true") is True,
        "manual_one_recipient_policy_locked": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True
        and dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("records_private_sha256_only") is True,
        "private_workspace_dir_shortcut_used": True,
        "standard_private_workspace_filenames_used": set(POST_SEND_PRIVATE_WORKSPACE_FILES).issubset(
            private_workspace_file_names
        ),
        "explicit_private_file_args_omitted": True,
        "explicit_private_sha256_args_omitted": True,
        "claim_boundaries_locked": checkpoint_metrics.get("proof_claim_allowed") is False
        and checkpoint_metrics.get("success_rate_claim_allowed") is False
        and checkpoint_metrics.get("sale_ready") is False
        and checkpoint_metrics.get("success_rate") is None,
        "raw_private_content_omitted": not any(marker in generated_text for marker in PRIVATE_MARKERS),
        "temporary_paths_omitted": temp_path not in generated_text,
        "real_recipient_evidence_not_claimed": True,
    }
    payload: dict[str, Any] = {
        "schema_version": POST_SEND_REHEARSAL_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "REHEARSAL_PASS" if all(checks.values()) else "REHEARSAL_FAIL",
        "safe_to_share": True,
        "real_recipient_evidence": False,
        "purpose": (
            "Operator-only rehearsal of post-send private-hash recording and recipient checkpoint closure. "
            "This receipt is not evidence that a real external recipient completed Cambrian."
        ),
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "rehearsed_flow": {
            "post_send_sequence_verdict": sequence.get("verdict"),
            "post_send_sequence_body_sha256": sequence.get("post_send_sequence_receipt_body_sha256"),
            "post_send_sequence_final_audit_operator_bypass_required": sequence_final_audit.get(
                "operator_bypass_audit_required"
            ),
            "dispatch_record_verdict": dispatch.get("verdict"),
            "recipient_checkpoint_verdict": checkpoint.get("verdict"),
            "recipient_checkpoint_body_sha256": checkpoint.get("recipient_checkpoint_body_sha256"),
            "dispatch_record_body_sha256": dispatch.get("dispatch_record_body_sha256"),
            "artifact_chain_depth": len(checkpoint.get("artifact_chain", []))
            if isinstance(checkpoint.get("artifact_chain"), list)
            else 0,
        },
        "private_input_policy": {
            "private_files_used_in_temp_workspace": True,
            "private_workspace_dir_shortcut_used": True,
            "post_send_sequence_used": True,
            "preflight_receipt_required": True,
            "preflight_generated_by_real_gate": True,
            "operator_note_template_used": operator_note_template_used,
            "standard_private_workspace_files": list(POST_SEND_PRIVATE_WORKSPACE_FILES),
            "explicit_private_file_args_used": False,
            "explicit_private_sha256_args_used": False,
            "stored_private_values": False,
            "stored_private_paths": False,
            "stored_private_hashes_only": True,
            "recipient_ack_hash_present": _looks_like_sha256(private_fingerprints.get("recipient_ack_sha256")),
            "builder_gold_path_share_receipt_hash_present": _looks_like_sha256(
                private_fingerprints.get("builder_gold_path_share_receipt_sha256")
            ),
        },
        "claim_boundaries": {
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "sale_ready": False,
            "market_validated": False,
        },
        "checks": checks,
    }
    payload["post_send_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload


def _write_builder_gold_path_share_receipt(path: Path) -> Path:
    capabilities = {name: True for name in sorted(BUILDER_GOLD_PATH_REQUIRED_CAPABILITIES)}
    payload = {
        "schema_version": BUILDER_GOLD_PATH_SHARE_RECEIPT_SCHEMA_VERSION,
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
    _write_json(path, payload)
    return path


def _preflight_operator_contract(
    *,
    dispatch_record: dict[str, Any],
    pilot_ready: dict[str, Any],
) -> dict[str, Any]:
    """Build the cycle-free send contract used only to exercise the real preflight gate."""
    release = dispatch_record.get("release") if isinstance(dispatch_record.get("release"), dict) else {}
    pilot_dispatch = (
        pilot_ready.get("pilot_dispatch") if isinstance(pilot_ready.get("pilot_dispatch"), dict) else {}
    )
    copy_paste_message = str(pilot_dispatch.get("copy_paste_message") or "")
    payload: dict[str, Any] = {
        "schema_version": "external_alpha_post_send_rehearsal_preflight_contract_v0_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": "READY_TO_SEND_ONE",
        "safe_to_share": True,
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "operator_send_once": {
            "attach_zip_file": release.get("zip_file"),
            "copy_paste_message": copy_paste_message,
            "copy_paste_message_sha256": _text_sha256(copy_paste_message),
            "max_recipients": 1,
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
        },
        "operator_dispatch_packet_checks": {
            "cycle_free_rehearsal_preflight_contract": True,
            "manual_dispatch_only": True,
            "one_recipient_only": True,
        },
    }
    payload["operator_dispatch_packet_body_sha256"] = _operator_contract_body_sha256(payload)
    return payload


def _has_existing_release_artifacts(output_dir: Path) -> bool:
    required = (
        f"{RELEASE_SLUG}.zip",
        f"{RELEASE_SLUG}.manifest.json",
        "external_alpha_release_verification_receipt.json",
        f"{RELEASE_SLUG}-handoff.json",
        f"{RELEASE_SLUG}-send-ready.json",
        f"{RELEASE_SLUG}-pilot-ready.json",
        f"{RELEASE_SLUG}-bundle-smoke-receipt.json",
    )
    return all((output_dir / name).is_file() for name in required)


def _copy_output_files(source_dir: Path, target_dir: Path) -> None:
    for path in sorted(item for item in source_dir.iterdir() if item.is_file()):
        shutil.copy2(path, target_dir / path.name)


def _write_private_file(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _generated_text(work_dir: Path) -> str:
    chunks: list[str] = []
    for path in sorted(item for item in work_dir.rglob("*") if item.is_file()):
        if path.suffix.lower() in {".json", ".md"}:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "post_send_rehearsal_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _operator_contract_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_dispatch_packet_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PostSendCheckpointRehearsalError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PostSendCheckpointRehearsalError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PostSendCheckpointRehearsalError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_shareable_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [str(ROOT), str(Path.home()), *PRIVATE_MARKERS]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise PostSendCheckpointRehearsalError(f"post-send rehearsal receipt contains private material: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse external alpha post-send checkpoint closure.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing post-send rehearsal receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_post_send_rehearsal_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
            logger.error("[FAIL] external alpha post-send checkpoint rehearsal verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha post-send checkpoint rehearsal verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["post_send_rehearsal_receipt_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = smoke_post_send_checkpoint(Path(args.output_dir))
    except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
        logger.error("[FAIL] external alpha post-send checkpoint rehearsal: %s", exc)
        return 1

    logger.info("[PASS] external alpha post-send checkpoint rehearsal")
    logger.info("verdict: REHEARSAL_PASS")
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
