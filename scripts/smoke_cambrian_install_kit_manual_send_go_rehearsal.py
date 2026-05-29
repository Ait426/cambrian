"""Rehearse the Cambrian install-kit first-recipient manual-send GO path."""

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
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import (  # noqa: E402
    PRIVATE_RUNBOOK_NAME,
    prepare_first_recipient_workspace,
)
from scripts.prepare_cambrian_install_kit_release import RELEASE_BUNDLE_NAME  # noqa: E402
from scripts.smoke_cambrian_install_kit_release_bundle import BUNDLE_SMOKE_RECEIPT_NAME  # noqa: E402


MANUAL_SEND_GO_REHEARSAL_SCHEMA_VERSION = "cambrian_install_kit_manual_send_go_rehearsal_v0_1"
MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME = "cambrian-install-kit-manual-send-go-rehearsal-receipt.json"
SYNTHETIC_SENT_AT_UTC = "2026-05-22T00:00:00+00:00"

PRIVATE_MARKERS = (
    "CAMBRIAN_INSTALL_KIT_REHEARSAL_PRIVATE_RECIPIENT",
    "CAMBRIAN_INSTALL_KIT_REHEARSAL_PRIVATE_CHANNEL",
)
REQUIRED_TRUE_CHECKS = (
    "release_bundle_hash_present",
    "workspace_ready",
    "operator_bypass_audit_pass",
    "operator_status_ready_to_send",
    "operator_status_open_gates_empty",
    "operator_status_manual_send_allowed",
    "dispatch_recorded_sent_one",
    "dispatch_operator_status_required",
    "dispatch_operator_status_ready",
    "dispatch_release_hash_matches",
    "dispatch_private_hashes_match",
    "dispatch_manual_only",
    "one_recipient_policy_locked",
    "synthetic_dispatch_timestamp_fixed",
    "synthetic_dispatch_not_standalone_proof",
    "synthetic_private_values_disclosed",
    "real_manual_send_not_claimed",
    "real_recipient_evidence_not_claimed",
    "raw_private_content_omitted",
    "temporary_paths_omitted",
    "script_did_not_send_to_recipient",
)

logger = logging.getLogger(__name__)


class InstallKitManualSendGoRehearsalError(RuntimeError):
    """Install-kit manual-send GO rehearsal failed."""


def smoke_manual_send_go_rehearsal(
    output_dir: Path | None = None,
    *,
    receipt_path: Path | None = None,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Run a synthetic private-input rehearsal without sending anything."""
    dist = (output_dir or ROOT / "dist").resolve()
    _require_release_artifacts(dist)

    with tempfile.TemporaryDirectory(prefix="cambrian-install-kit-manual-go-") as temp_name:
        temp_root = Path(temp_name).resolve()
        work_dir = temp_root / "release"
        private_dir = temp_root / "private"
        work_dir.mkdir()
        private_dir.mkdir()
        _copy_output_files(dist, work_dir)

        workspace = prepare_first_recipient_workspace(
            workspace_dir=private_dir,
            output_dir=work_dir,
            force=True,
        )
        release_bundle_sha256 = str(workspace["release_bundle_sha256"])
        _write_synthetic_private_files(private_dir, release_bundle_sha256=release_bundle_sha256)

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
        sent_at_utc = SYNTHETIC_SENT_AT_UTC
        check_dispatch_record(
            output_dir=work_dir,
            skip_verify=skip_verify,
            recipient_private_file=private_dir / "recipient-private.txt",
            operator_dispatch_note_private_file=private_dir / "operator-dispatch-note-private.md",
            operator_status_receipt=ready_operator_status_receipt,
            require_operator_status_receipt=True,
            allow_synthetic_rehearsal_without_manual_send_go_receipt=True,
            sent_at_utc=sent_at_utc,
        )
        dispatch_record = verify_dispatch_record_file(
            work_dir / DISPATCH_RECORD_JSON_NAME,
            allow_synthetic_rehearsal=True,
        )
        safe_workspace = {
            "status": workspace.get("status"),
            "verdict": workspace.get("verdict"),
            "receipt_body_sha256": workspace.get("receipt_body_sha256"),
            "release_bundle_sha256": workspace.get("release_bundle_sha256"),
        }
        generated_text = json.dumps(
            {
                "workspace": safe_workspace,
                "operator_status_result": operator_status_result,
                "operator_status": operator_status,
                "operator_bypass": operator_bypass,
                "dispatch_record": dispatch_record,
            },
            ensure_ascii=False,
        )
        payload = _rehearsal_payload(
            release_bundle_sha256=release_bundle_sha256,
            workspace=workspace,
            operator_status=operator_status,
            operator_bypass=operator_bypass,
            dispatch_record=dispatch_record,
            generated_text=generated_text,
            temp_root=temp_root,
        )

    target = (receipt_path or dist / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, payload)
    verify_manual_send_go_rehearsal_receipt_file(target)
    _assert_shareable_receipt_file(target)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(target),
        "release_bundle_sha256": payload["release_bundle"]["sha256"],
        "receipt_body_sha256": payload["manual_send_go_rehearsal_receipt_body_sha256"],
    }


def verify_manual_send_go_rehearsal_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_manual_send_go_rehearsal_receipt_payload(payload)
    return payload


def verify_manual_send_go_rehearsal_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != MANUAL_SEND_GO_REHEARSAL_SCHEMA_VERSION:
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "REHEARSAL_PASS":
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal did not pass.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal must be safe_to_share.")
    if payload.get("real_manual_send") is not False:
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal must not claim a real send.")
    if payload.get("real_recipient_evidence") is not False:
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal must not claim real recipient evidence.")
    if payload.get("synthetic_private_values_used") is not True:
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal must disclose synthetic private values.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal checks failed.")
    missing = [name for name in REQUIRED_TRUE_CHECKS if checks.get(name) is not True]
    if missing:
        raise InstallKitManualSendGoRehearsalError(
            "manual-send GO rehearsal required checks missing or failed: " + ", ".join(missing)
        )
    flow = payload.get("rehearsed_flow") if isinstance(payload.get("rehearsed_flow"), dict) else {}
    if flow.get("operator_status_verdict") != "READY_TO_MANUALLY_SEND_ONE":
        raise InstallKitManualSendGoRehearsalError("operator status is not READY_TO_MANUALLY_SEND_ONE.")
    if flow.get("dispatch_record_verdict") != "SENT_ONE_RECORDED":
        raise InstallKitManualSendGoRehearsalError("dispatch record is not SENT_ONE_RECORDED.")
    if payload.get("manual_send_go_rehearsal_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal body hash mismatch.")
    serialized = json.dumps(payload, ensure_ascii=False)
    leaked = [item for item in (str(ROOT), str(Path.home()), *PRIVATE_MARKERS) if item and item in serialized]
    if leaked:
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal receipt contains private material.")


def _rehearsal_payload(
    *,
    release_bundle_sha256: str,
    workspace: dict[str, Any],
    operator_status: dict[str, Any],
    operator_bypass: dict[str, Any],
    dispatch_record: dict[str, Any],
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
    dispatch_pre_send = (
        dispatch_record.get("operator_status_pre_send")
        if isinstance(dispatch_record.get("operator_status_pre_send"), dict)
        else {}
    )
    dispatch = (
        dispatch_record.get("dispatch_record")
        if isinstance(dispatch_record.get("dispatch_record"), dict)
        else {}
    )
    synthetic_boundary = (
        dispatch_record.get("synthetic_rehearsal_boundary")
        if isinstance(dispatch_record.get("synthetic_rehearsal_boundary"), dict)
        else {}
    )
    checks = {
        "release_bundle_hash_present": _looks_like_sha256(release_bundle_sha256),
        "workspace_ready": workspace.get("verdict") == "INSTALL_KIT_FIRST_RECIPIENT_WORKSPACE_READY",
        "operator_bypass_audit_pass": operator_bypass.get("status") == "pass"
        and operator_bypass.get("verdict") == "NO_OPERATOR_STATUS_BYPASS",
        "operator_status_ready_to_send": operator_status.get("status") == "pass"
        and operator_status.get("verdict") == "READY_TO_MANUALLY_SEND_ONE",
        "operator_status_open_gates_empty": operator_summary.get("open_gate_ids") == [],
        "operator_status_manual_send_allowed": operator_summary.get("manual_send_allowed") is True,
        "operator_status_safe_to_share": operator_status.get("safe_to_share") is True,
        "dispatch_recorded_sent_one": dispatch_record.get("status") == "dispatch_recorded"
        and dispatch_record.get("verdict") == "SENT_ONE_RECORDED"
        and dispatch.get("sent_recorded") is True,
        "dispatch_operator_status_required": dispatch_pre_send.get("required") is True
        and dispatch_pre_send.get("present") is True
        and dispatch_pre_send.get("verified_standalone") is True,
        "dispatch_operator_status_ready": dispatch_pre_send.get("ready_to_send_one") is True
        and dispatch_pre_send.get("verdict") == "READY_TO_MANUALLY_SEND_ONE",
        "dispatch_release_hash_matches": dispatch_pre_send.get("release_hash_matches_dispatch") is True,
        "dispatch_private_hashes_match": dispatch_pre_send.get("private_hashes_match_dispatch") is True,
        "dispatch_manual_only": dispatch_policy.get("script_sends_to_recipient") is False
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
        "synthetic_private_values_disclosed": True,
        "real_manual_send_not_claimed": True,
        "real_recipient_evidence_not_claimed": True,
        "raw_private_content_omitted": not any(marker in generated_text for marker in PRIVATE_MARKERS),
        "temporary_paths_omitted": str(temp_root) not in generated_text,
        "script_did_not_send_to_recipient": True,
    }
    payload: dict[str, Any] = {
        "schema_version": MANUAL_SEND_GO_REHEARSAL_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "REHEARSAL_PASS" if all(checks.values()) else "REHEARSAL_FAIL",
        "safe_to_share": True,
        "real_manual_send": False,
        "real_recipient_evidence": False,
        "synthetic_private_values_used": True,
        "purpose": (
            "Synthetic rehearsal proving the install-kit first-recipient path can reach "
            "READY_TO_MANUALLY_SEND_ONE and then record SENT_ONE_RECORDED when private fields are ready. "
            "This receipt is not evidence that any real recipient was contacted."
        ),
        "release_bundle": {
            "file": RELEASE_BUNDLE_NAME,
            "sha256": release_bundle_sha256,
        },
        "rehearsed_flow": {
            "workspace_verdict": workspace.get("verdict"),
            "workspace_receipt_body_sha256": workspace.get("receipt_body_sha256"),
            "operator_bypass_verdict": operator_bypass.get("verdict"),
            "operator_bypass_receipt_body_sha256": operator_bypass.get(
                "operator_send_bypass_audit_body_sha256"
            ),
            "operator_status_verdict": operator_status.get("verdict"),
            "operator_status_receipt_body_sha256": operator_status.get(
                "operator_status_receipt_body_sha256"
            ),
            "dispatch_record_verdict": dispatch_record.get("verdict"),
            "dispatch_record_body_sha256": dispatch_record.get("dispatch_record_body_sha256"),
            "dispatch_operator_status_required": dispatch_pre_send.get("required") is True,
            "dispatch_synthetic_standalone_send_evidence_allowed": synthetic_boundary.get(
                "standalone_send_evidence_allowed"
            )
            is True,
        },
        "private_input_policy": {
            "private_files_used_in_temp_workspace": True,
            "stored_private_values": False,
            "stored_private_paths": False,
            "stored_private_hashes_only": True,
            "synthetic_values_only": True,
            "synthetic_sent_at_utc": SYNTHETIC_SENT_AT_UTC,
        },
        "operator_boundary": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "rehearsal_receipt_is_not_dispatch_evidence": True,
        },
        "checks": checks,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["manual_send_go_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
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
        raise InstallKitManualSendGoRehearsalError("missing release artifact(s): " + ", ".join(missing))


def _copy_output_files(source_dir: Path, target_dir: Path) -> None:
    for path in source_dir.iterdir():
        if path.is_file():
            shutil.copy2(path, target_dir / path.name)


def _write_synthetic_private_files(private_dir: Path, *, release_bundle_sha256: str) -> None:
    (private_dir / "recipient-private.txt").write_text(
        "CAMBRIAN_INSTALL_KIT_REHEARSAL_PRIVATE_RECIPIENT@example.invalid\n",
        encoding="utf-8",
    )
    (private_dir / "operator-dispatch-note-private.md").write_text(
        "\n".join(
            [
                "private channel: email",
                "private marker: CAMBRIAN_INSTALL_KIT_REHEARSAL_PRIVATE_CHANNEL",
                f"release bundle sha256: {release_bundle_sha256}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "manual_send_go_rehearsal_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_shareable_receipt_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    leaked = [item for item in (str(ROOT), str(Path.home()), *PRIVATE_MARKERS) if item and item in text]
    if leaked:
        raise InstallKitManualSendGoRehearsalError("manual-send GO rehearsal receipt contains private material.")


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitManualSendGoRehearsalError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse Cambrian install-kit first-recipient manual-send GO.")
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
            payload = verify_manual_send_go_rehearsal_receipt_file(args.verify_receipt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit manual-send GO rehearsal verification: %s", exc)
            return 1
        logger.info("[PASS] install kit manual-send GO rehearsal verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["manual_send_go_rehearsal_receipt_body_sha256"])
        return 0

    try:
        result = smoke_manual_send_go_rehearsal(
            output_dir=args.output_dir,
            receipt_path=args.receipt,
            skip_verify=bool(args.skip_verify),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[FAIL] install kit manual-send GO rehearsal: %s", exc)
        return 1
    logger.info("[PASS] install kit manual-send GO rehearsal")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", Path(str(result["receipt_json"])).name)
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
