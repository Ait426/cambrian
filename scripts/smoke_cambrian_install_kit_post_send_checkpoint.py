"""Rehearse the Cambrian install-kit post-send recipient checkpoint."""

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

from scripts.audit_cambrian_install_kit_operator_send_bypass import (  # noqa: E402
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
    audit_install_kit_operator_send_bypass,
    verify_operator_send_bypass_audit_file,
)
from scripts.check_cambrian_install_kit_dispatch_record import (  # noqa: E402
    DISPATCH_RECORD_JSON_NAME,
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.check_cambrian_install_kit_first_recipient_operator_status import (  # noqa: E402
    OPERATOR_STATUS_RECEIPT_NAME,
    OPERATOR_STATUS_READY_RECEIPT_NAME,
    check_first_recipient_operator_status,
    verify_first_recipient_operator_status_receipt_file,
)
from scripts.check_cambrian_install_kit_first_recipient_manual_send_go import (  # noqa: E402
    MANUAL_SEND_GO_RECEIPT_NAME,
    check_first_recipient_manual_send_go,
    verify_first_recipient_manual_send_go_receipt_file,
)
from scripts.check_cambrian_install_kit_recipient_checkpoint import (  # noqa: E402
    RECIPIENT_CHECKPOINT_JSON_NAME,
    check_recipient_checkpoint,
    verify_recipient_checkpoint_file,
)
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import prepare_first_recipient_workspace  # noqa: E402
from scripts.prepare_cambrian_install_kit_release import RELEASE_BUNDLE_NAME  # noqa: E402
from scripts.smoke_cambrian_install_kit_release_bundle import BUNDLE_SMOKE_RECEIPT_NAME  # noqa: E402


POST_SEND_REHEARSAL_SCHEMA_VERSION = "cambrian_install_kit_post_send_checkpoint_rehearsal_v0_1"
POST_SEND_REHEARSAL_RECEIPT_NAME = "cambrian-install-kit-post-send-checkpoint-rehearsal-receipt.json"
SYNTHETIC_SENT_AT_UTC = "2026-05-22T00:00:00+00:00"

PRIVATE_MARKERS = (
    "CAMBRIAN_INSTALL_KIT_POST_SEND_PRIVATE_RECIPIENT",
    "CAMBRIAN_INSTALL_KIT_POST_SEND_PRIVATE_CHANNEL",
    "CAMBRIAN_INSTALL_KIT_POST_SEND_PRIVATE_ACK",
)
REQUIRED_TRUE_CHECKS = (
    "operator_bypass_audit_pass",
    "operator_status_ready_to_send",
    "manual_send_go_ready_to_send",
    "dispatch_recorded_sent_one",
    "dispatch_manual_send_go_required",
    "recipient_checkpoint_gold_path_confirmed",
    "recipient_checkpoint_operator_status_required",
    "recipient_checkpoint_operator_status_ready",
    "recipient_checkpoint_manual_send_go_required",
    "install_share_receipt_accepted",
    "gold_path_share_receipt_accepted",
    "mcp_operability_receipt_accepted",
    "returned_mcp_installed_entrypoint",
    "manual_dispatch_only",
    "one_recipient_policy_locked",
    "synthetic_dispatch_timestamp_fixed",
    "synthetic_dispatch_not_standalone_proof",
    "synthetic_checkpoint_not_standalone_proof",
    "synthetic_private_values_disclosed",
    "real_recipient_evidence_not_claimed",
    "raw_private_content_omitted",
    "temporary_paths_omitted",
    "script_did_not_send_to_recipient",
)

logger = logging.getLogger(__name__)


class InstallKitPostSendCheckpointRehearsalError(RuntimeError):
    """Install-kit post-send checkpoint rehearsal failed."""


def smoke_post_send_checkpoint_rehearsal(
    output_dir: Path | None = None,
    *,
    receipt_path: Path | None = None,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Run the post-send recipient checkpoint with synthetic returned receipts."""
    dist = (output_dir or ROOT / "dist").resolve()
    _require_release_artifacts(dist)

    with tempfile.TemporaryDirectory(prefix="cambrian-install-kit-post-send-") as temp_name:
        temp_root = Path(temp_name).resolve()
        work_dir = temp_root / "release"
        private_dir = temp_root / "private"
        returned_dir = private_dir / "returned-receipts"
        work_dir.mkdir()
        private_dir.mkdir()
        returned_dir.mkdir()
        _copy_output_files(dist, work_dir)

        workspace = prepare_first_recipient_workspace(
            workspace_dir=private_dir,
            output_dir=work_dir,
            force=True,
        )
        release_bundle_sha256 = str(workspace["release_bundle_sha256"])
        _write_synthetic_private_files(private_dir, release_bundle_sha256=release_bundle_sha256)
        install_receipt = _write_install_share_receipt(returned_dir / "cambrian_install_share_receipt.json")
        gold_path_receipt = _write_gold_path_share_receipt(returned_dir / "cambrian_gold_path_share_receipt.json")
        mcp_receipt = _write_mcp_operability_receipt(returned_dir / "mcp_operability_receipt.json")

        operator_status_result = check_first_recipient_operator_status(
            workspace_dir=private_dir,
            output_dir=work_dir,
        )
        operator_status = verify_first_recipient_operator_status_receipt_file(
            private_dir / OPERATOR_STATUS_RECEIPT_NAME
        )
        ready_operator_status_receipt = private_dir / OPERATOR_STATUS_READY_RECEIPT_NAME
        verify_first_recipient_operator_status_receipt_file(ready_operator_status_receipt)
        audit_install_kit_operator_send_bypass(
            output_dir=work_dir,
            workspace_dir=private_dir,
            skip_verify=skip_verify,
        )
        operator_bypass = verify_operator_send_bypass_audit_file(work_dir / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME)
        manual_go_result = check_first_recipient_manual_send_go(
            workspace_dir=private_dir,
            output_dir=work_dir,
            skip_verify=skip_verify,
        )
        manual_send_go_receipt = private_dir / MANUAL_SEND_GO_RECEIPT_NAME
        manual_go = verify_first_recipient_manual_send_go_receipt_file(manual_send_go_receipt)
        sent_at_utc = SYNTHETIC_SENT_AT_UTC
        check_dispatch_record(
            output_dir=work_dir,
            skip_verify=skip_verify,
            recipient_private_file=private_dir / "recipient-private.txt",
            operator_dispatch_note_private_file=private_dir / "operator-dispatch-note-private.md",
            operator_status_receipt=ready_operator_status_receipt,
            require_operator_status_receipt=True,
            manual_send_go_receipt=manual_send_go_receipt,
            require_manual_send_go_receipt=True,
            sent_at_utc=sent_at_utc,
            synthetic_rehearsal_without_real_recipient=True,
        )
        dispatch_record = verify_dispatch_record_file(
            work_dir / DISPATCH_RECORD_JSON_NAME,
            allow_synthetic_rehearsal=True,
        )
        check_recipient_checkpoint(
            output_dir=work_dir,
            skip_verify=skip_verify,
            install_share_receipt=install_receipt,
            gold_path_share_receipt=gold_path_receipt,
            mcp_operability_receipt=mcp_receipt,
            recipient_private_file=private_dir / "recipient-private.txt",
            operator_dispatch_note_private_file=private_dir / "operator-dispatch-note-private.md",
            operator_status_receipt=ready_operator_status_receipt,
            require_operator_status_receipt=True,
            manual_send_go_receipt=manual_send_go_receipt,
            require_manual_send_go_receipt=True,
            recipient_ack_private_file=private_dir / "recipient-ack-private.txt",
            sent_at_utc=sent_at_utc,
            allow_synthetic_rehearsal=True,
        )
        checkpoint = verify_recipient_checkpoint_file(
            work_dir / RECIPIENT_CHECKPOINT_JSON_NAME,
            allow_synthetic_rehearsal=True,
        )
        generated_text = json.dumps(
            {
                "operator_status_result": operator_status_result,
                "operator_status": operator_status,
                "operator_bypass": operator_bypass,
                "manual_go_result": manual_go_result,
                "manual_go": manual_go,
                "dispatch_record": dispatch_record,
                "checkpoint": checkpoint,
            },
            ensure_ascii=False,
        )
        payload = _rehearsal_payload(
            release_bundle_sha256=release_bundle_sha256,
            operator_status=operator_status,
            operator_bypass=operator_bypass,
            manual_go=manual_go,
            dispatch_record=dispatch_record,
            checkpoint=checkpoint,
            generated_text=generated_text,
            temp_root=temp_root,
        )

    target = (receipt_path or dist / POST_SEND_REHEARSAL_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, payload)
    verify_post_send_checkpoint_rehearsal_receipt_file(target)
    _assert_shareable_receipt_file(target)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(target),
        "release_bundle_sha256": payload["release_bundle"]["sha256"],
        "receipt_body_sha256": payload["post_send_rehearsal_receipt_body_sha256"],
    }


def verify_post_send_checkpoint_rehearsal_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_post_send_checkpoint_rehearsal_receipt_payload(payload)
    return payload


def verify_post_send_checkpoint_rehearsal_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != POST_SEND_REHEARSAL_SCHEMA_VERSION:
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "REHEARSAL_PASS":
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal did not pass.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal must be safe_to_share.")
    if payload.get("real_recipient_evidence") is not False:
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal must not claim real recipient evidence.")
    if payload.get("synthetic_private_values_used") is not True:
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal must disclose synthetic private values.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal checks failed.")
    missing = [name for name in REQUIRED_TRUE_CHECKS if checks.get(name) is not True]
    if missing:
        raise InstallKitPostSendCheckpointRehearsalError(
            "post-send rehearsal required checks missing or failed: " + ", ".join(missing)
        )
    flow = payload.get("rehearsed_flow") if isinstance(payload.get("rehearsed_flow"), dict) else {}
    if flow.get("recipient_checkpoint_verdict") != "RECIPIENT_GOLD_PATH_CONFIRMED":
        raise InstallKitPostSendCheckpointRehearsalError("recipient checkpoint is not gold-path confirmed.")
    if payload.get("post_send_rehearsal_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal body hash mismatch.")
    serialized = json.dumps(payload, ensure_ascii=False)
    leaked = [item for item in (str(ROOT), str(Path.home()), *PRIVATE_MARKERS) if item and item in serialized]
    if leaked:
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal receipt contains private material.")


def _rehearsal_payload(
    *,
    release_bundle_sha256: str,
    operator_status: dict[str, Any],
    operator_bypass: dict[str, Any],
    manual_go: dict[str, Any],
    dispatch_record: dict[str, Any],
    checkpoint: dict[str, Any],
    generated_text: str,
    temp_root: Path,
) -> dict[str, Any]:
    operator_summary = (
        operator_status.get("operator_status_summary")
        if isinstance(operator_status.get("operator_status_summary"), dict)
        else {}
    )
    dispatch_policy = (
        dispatch_record.get("dispatch_execution_policy")
        if isinstance(dispatch_record.get("dispatch_execution_policy"), dict)
        else {}
    )
    dispatch_scope = (
        dispatch_record.get("dispatch_scope") if isinstance(dispatch_record.get("dispatch_scope"), dict) else {}
    )
    dispatch = (
        dispatch_record.get("dispatch_record")
        if isinstance(dispatch_record.get("dispatch_record"), dict)
        else {}
    )
    dispatch_manual_go = (
        dispatch_record.get("manual_send_go_pre_send")
        if isinstance(dispatch_record.get("manual_send_go_pre_send"), dict)
        else {}
    )
    synthetic_boundary = (
        dispatch_record.get("synthetic_rehearsal_boundary")
        if isinstance(dispatch_record.get("synthetic_rehearsal_boundary"), dict)
        else {}
    )
    checkpoint_synthetic_boundary = (
        checkpoint.get("synthetic_rehearsal_boundary")
        if isinstance(checkpoint.get("synthetic_rehearsal_boundary"), dict)
        else {}
    )
    checkpoint_operator = (
        checkpoint.get("operator_status_pre_send")
        if isinstance(checkpoint.get("operator_status_pre_send"), dict)
        else {}
    )
    checkpoint_manual_go = (
        checkpoint.get("manual_send_go_pre_send")
        if isinstance(checkpoint.get("manual_send_go_pre_send"), dict)
        else {}
    )
    install_summary = (
        checkpoint.get("install_share_receipt")
        if isinstance(checkpoint.get("install_share_receipt"), dict)
        else {}
    )
    gold_summary = (
        checkpoint.get("gold_path_share_receipt")
        if isinstance(checkpoint.get("gold_path_share_receipt"), dict)
        else {}
    )
    mcp_summary = (
        checkpoint.get("mcp_operability_receipt")
        if isinstance(checkpoint.get("mcp_operability_receipt"), dict)
        else {}
    )
    checks = {
        "operator_bypass_audit_pass": operator_bypass.get("status") == "pass"
        and operator_bypass.get("verdict") == "NO_OPERATOR_STATUS_BYPASS",
        "operator_status_ready_to_send": operator_status.get("status") == "pass"
        and operator_status.get("verdict") == "READY_TO_MANUALLY_SEND_ONE"
        and operator_summary.get("manual_send_allowed") is True
        and operator_summary.get("open_gate_ids") == [],
        "manual_send_go_ready_to_send": manual_go.get("status") == "pass"
        and manual_go.get("verdict") == "GO_TO_MANUALLY_SEND_ONE",
        "dispatch_recorded_sent_one": dispatch_record.get("status") == "dispatch_recorded"
        and dispatch_record.get("verdict") == "SENT_ONE_RECORDED",
        "dispatch_manual_send_go_required": dispatch_manual_go.get("required") is True
        and dispatch_manual_go.get("present") is True
        and dispatch_manual_go.get("verified_standalone") is True
        and dispatch_manual_go.get("ready_to_send_one") is True,
        "recipient_checkpoint_gold_path_confirmed": checkpoint.get("status") == "recipient_gold_path_confirmed"
        and checkpoint.get("verdict") == "RECIPIENT_GOLD_PATH_CONFIRMED",
        "recipient_checkpoint_operator_status_required": checkpoint_operator.get("required") is True
        and checkpoint_operator.get("present") is True
        and checkpoint_operator.get("verified_standalone") is True,
        "recipient_checkpoint_operator_status_ready": checkpoint_operator.get("ready_to_send_one") is True
        and checkpoint_operator.get("release_hash_matches_dispatch") is True
        and checkpoint_operator.get("private_hashes_match_dispatch") is True,
        "recipient_checkpoint_manual_send_go_required": checkpoint_manual_go.get("required") is True
        and checkpoint_manual_go.get("present") is True
        and checkpoint_manual_go.get("verified_standalone") is True
        and checkpoint_manual_go.get("ready_to_send_one") is True,
        "install_share_receipt_accepted": install_summary.get("present") is True
        and install_summary.get("checks_all_true") is True,
        "gold_path_share_receipt_accepted": gold_summary.get("present") is True
        and gold_summary.get("checks_all_true") is True
        and gold_summary.get("capabilities_all_true") is True,
        "mcp_operability_receipt_accepted": mcp_summary.get("present") is True
        and mcp_summary.get("checks_all_true") is True
        and mcp_summary.get("verdict") == "GO",
        "returned_mcp_installed_entrypoint": mcp_summary.get("installed_wheel_mode") is True
        and mcp_summary.get("server_command_mode") == "installed_entrypoint"
        and mcp_summary.get("installed_entrypoint_command") is True,
        "manual_dispatch_only": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "one_recipient_policy_locked": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_scope.get("target_recipients") == 1
        and dispatch_scope.get("cohort_scaling_allowed") is False,
        "synthetic_dispatch_timestamp_fixed": dispatch.get("sent_at_utc") == SYNTHETIC_SENT_AT_UTC,
        "synthetic_dispatch_not_standalone_proof": synthetic_boundary.get("synthetic_rehearsal") is True
        and synthetic_boundary.get("standalone_send_evidence_allowed") is False
        and synthetic_boundary.get("real_manual_send") is False
        and synthetic_boundary.get("real_recipient_evidence") is False,
        "synthetic_checkpoint_not_standalone_proof": checkpoint_synthetic_boundary.get("synthetic_rehearsal")
        is True
        and checkpoint_synthetic_boundary.get("standalone_recipient_evidence_allowed") is False
        and checkpoint_synthetic_boundary.get("real_manual_send") is False
        and checkpoint_synthetic_boundary.get("real_recipient_evidence") is False,
        "synthetic_private_values_disclosed": True,
        "real_recipient_evidence_not_claimed": True,
        "raw_private_content_omitted": not any(marker in generated_text for marker in PRIVATE_MARKERS),
        "temporary_paths_omitted": str(temp_root) not in generated_text,
        "script_did_not_send_to_recipient": True,
    }
    payload: dict[str, Any] = {
        "schema_version": POST_SEND_REHEARSAL_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "REHEARSAL_PASS" if all(checks.values()) else "REHEARSAL_FAIL",
        "safe_to_share": True,
        "real_recipient_evidence": False,
        "synthetic_private_values_used": True,
        "purpose": (
            "Synthetic rehearsal proving the install-kit post-send checkpoint can close install, "
            "gold-path, and MCP receipts while requiring the operator-status GO receipt. "
            "It also requires the final manual-send GO receipt. "
            "This receipt is not evidence that any real recipient completed Cambrian."
        ),
        "release_bundle": {
            "file": RELEASE_BUNDLE_NAME,
            "sha256": release_bundle_sha256,
        },
        "rehearsed_flow": {
            "operator_bypass_verdict": operator_bypass.get("verdict"),
            "operator_status_verdict": operator_status.get("verdict"),
            "manual_send_go_verdict": manual_go.get("verdict"),
            "dispatch_record_verdict": dispatch_record.get("verdict"),
            "dispatch_record_body_sha256": dispatch_record.get("dispatch_record_body_sha256"),
            "dispatch_manual_send_go_required": dispatch_manual_go.get("required") is True,
            "dispatch_synthetic_standalone_send_evidence_allowed": synthetic_boundary.get(
                "standalone_send_evidence_allowed"
            )
            is True,
            "recipient_checkpoint_verdict": checkpoint.get("verdict"),
            "recipient_checkpoint_body_sha256": checkpoint.get("recipient_checkpoint_body_sha256"),
            "recipient_checkpoint_operator_status_required": checkpoint_operator.get("required") is True,
            "recipient_checkpoint_manual_send_go_required": checkpoint_manual_go.get("required") is True,
            "recipient_checkpoint_synthetic_standalone_recipient_evidence_allowed": checkpoint_synthetic_boundary.get(
                "standalone_recipient_evidence_allowed"
            )
            is True,
            "returned_mcp_server_command_mode": mcp_summary.get("server_command_mode"),
        },
        "private_input_policy": {
            "private_files_used_in_temp_workspace": True,
            "returned_receipts_are_synthetic": True,
            "stored_private_values": False,
            "stored_private_paths": False,
            "stored_private_hashes_only": True,
            "synthetic_values_only": True,
            "synthetic_sent_at_utc": SYNTHETIC_SENT_AT_UTC,
        },
        "claim_boundaries": {
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "sale_ready": False,
            "market_validated": False,
        },
        "checks": checks,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["post_send_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload


def _require_release_artifacts(dist: Path) -> None:
    missing = [
        name
        for name in (
            RELEASE_BUNDLE_NAME,
            BUNDLE_SMOKE_RECEIPT_NAME,
        )
        if not (dist / name).is_file()
    ]
    if missing:
        raise InstallKitPostSendCheckpointRehearsalError("missing release artifact(s): " + ", ".join(missing))


def _copy_output_files(source_dir: Path, target_dir: Path) -> None:
    for path in source_dir.iterdir():
        if path.is_file():
            shutil.copy2(path, target_dir / path.name)


def _write_synthetic_private_files(private_dir: Path, *, release_bundle_sha256: str) -> None:
    (private_dir / "recipient-private.txt").write_text(
        "CAMBRIAN_INSTALL_KIT_POST_SEND_PRIVATE_RECIPIENT@example.invalid\n",
        encoding="utf-8",
    )
    (private_dir / "operator-dispatch-note-private.md").write_text(
        "\n".join(
            [
                "private channel: email",
                "private marker: CAMBRIAN_INSTALL_KIT_POST_SEND_PRIVATE_CHANNEL",
                f"release bundle sha256: {release_bundle_sha256}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (private_dir / "recipient-ack-private.txt").write_text(
        "CONFIRMED CAMBRIAN_INSTALL_KIT_POST_SEND_PRIVATE_ACK\n",
        encoding="utf-8",
    )


def _write_install_share_receipt(path: Path) -> Path:
    payload = {
        "schema_version": "cambrian_install_share_receipt_v0_1",
        "generated_at": "2026-05-22T00:00:00+00:00",
        "status": "installed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "local_receipt_sha256": "d" * 64,
        "wheel": "cambrian-0.3.0-py3-none-any.whl",
        "offline": True,
        "checks": {
            "all_steps_passed": True,
            "cambrian_help_passed": True,
            "cambrian_doctor_json_passed": True,
            "cambrian_company_snapshot_help_passed": True,
        },
    }
    _write_json(path, payload)
    return path


def _write_gold_path_share_receipt(path: Path) -> Path:
    capabilities = {
        "ai_agents_created": True,
        "skills_generated_searched_and_fused": True,
        "harness_engineering_system_created": True,
        "evolution_proposed_previewed_and_applied": True,
        "company_snapshot_generated": True,
        "mcp_operability_verified": True,
    }
    payload = {
        "schema_version": "cambrian_bundle_gold_path_share_receipt_v0_1",
        "generated_at": "2026-05-22T00:00:00+00:00",
        "status": "passed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "checks": {
            "cambrian --help": True,
            "cambrian doctor": True,
            "project scan": True,
            "harness engineer dry-run": True,
            "skill fuse": True,
            "evolve apply": True,
            "company snapshot is private-safe artifact": True,
        },
        "capabilities_verified": capabilities,
        "proof_claim_allowed": False,
        "sale_ready": False,
    }
    _write_json(path, payload)
    return path


def _write_mcp_operability_receipt(path: Path) -> Path:
    payload = {
        "schema_version": "1.0.0",
        "generated_at": "2026-05-22T00:00:00+00:00",
        "verifier": "cambrian mcp verify",
        "server_command": ["cambrian-mcp"],
        "server_command_mode": "installed_entrypoint",
        "installed_entrypoint_command": True,
        "installed_entrypoint_required": True,
        "installed_entrypoint_required_satisfied": True,
        "server_cwd": "recipient-project",
        "source_pythonpath_injected": False,
        "tool_count": 2,
        "tool_names": ["cambrian_project_scan", "cambrian_harness_install"],
        "checks": {
            "initialize": True,
            "tools_list": True,
            "missing_cwd_blocked": True,
            "project_scan_with_explicit_cwd": True,
            "harness_install_requires_confirm": True,
            "allowlisted_cli_only": True,
            "no_arbitrary_shell": True,
            "explicit_cwd_required": True,
        },
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "verdict": "GO",
    }
    _write_json(path, payload)
    return path


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "post_send_rehearsal_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_shareable_receipt_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    leaked = [item for item in (str(ROOT), str(Path.home()), *PRIVATE_MARKERS) if item and item in text]
    if leaked:
        raise InstallKitPostSendCheckpointRehearsalError("post-send rehearsal receipt contains private material.")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitPostSendCheckpointRehearsalError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse Cambrian install-kit post-send recipient checkpoint.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing rehearsal receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_post_send_checkpoint_rehearsal_receipt_file(args.verify_receipt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit post-send checkpoint rehearsal verification: %s", exc)
            return 1
        logger.info("[PASS] install kit post-send checkpoint rehearsal verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["post_send_rehearsal_receipt_body_sha256"])
        return 0

    try:
        result = smoke_post_send_checkpoint_rehearsal(
            output_dir=args.output_dir,
            receipt_path=args.receipt,
            skip_verify=bool(args.skip_verify),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[FAIL] install kit post-send checkpoint rehearsal: %s", exc)
        return 1
    logger.info("[PASS] install kit post-send checkpoint rehearsal")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", Path(str(result["receipt_json"])).name)
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
