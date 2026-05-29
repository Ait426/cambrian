"""Rehearse the final first-recipient manual-send GO gate without sending."""

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


MANUAL_SEND_GO_REHEARSAL_SCHEMA_VERSION = "external_alpha_first_recipient_manual_send_go_rehearsal_v0_1"
MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME = f"{RELEASE_SLUG}-manual-send-go-rehearsal-receipt.json"
PACKET_JSON_NAME = f"{RELEASE_SLUG}-operator-dispatch-packet.json"
OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME = f"{RELEASE_SLUG}-operator-send-bypass-audit.json"
PREFLIGHT_RECEIPT_NAME = "external-alpha-first-recipient-send-preflight-receipt.json"
MANUAL_SEND_GO_RECEIPT_NAME = "external-alpha-first-recipient-manual-send-go-receipt.json"
OPERATOR_STATUS_RECEIPT_NAME = "external-alpha-first-recipient-operator-status-receipt.json"
PRIVATE_SEND_RUNBOOK_NAME = "SEND_ONE_NOW_PRIVATE.md"

PRIVATE_MARKERS = (
    "MANUAL_SEND_GO_REHEARSAL_PRIVATE_RECIPIENT",
    "MANUAL_SEND_GO_REHEARSAL_PRIVATE_OPERATOR_NOTE",
)
PRIVATE_WORKSPACE_FILES = (
    "recipient-private.txt",
    "operator-dispatch-note-private.md",
)
REQUIRED_TRUE_CHECKS = (
    "preflight_ready",
    "operator_bypass_ready",
    "manual_send_go_ready",
    "operator_status_ready_to_send",
    "operator_status_safe_to_share",
    "operator_status_release_hash_matches",
    "operator_status_manual_send_go_packet_bound",
    "manual_go_final_chain_ready",
    "manual_go_checks_all_true",
    "release_hashes_match",
    "operator_note_template_used",
    "operator_note_template_preflight_contract",
    "manual_dispatch_only",
    "one_recipient_policy_locked",
    "preflight_did_not_record_send",
    "script_did_not_send_to_recipient",
    "synthetic_private_values_disclosed",
    "real_manual_send_not_claimed",
    "real_recipient_evidence_not_claimed",
    "raw_private_content_omitted",
    "temporary_paths_omitted",
)

logger = logging.getLogger(__name__)


class ManualSendGoRehearsalError(RuntimeError):
    """Manual-send GO rehearsal generation or verification failed."""


def smoke_manual_send_go_rehearsal(output_dir: Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    """Run a synthetic private-input rehearsal and write a share-safe GO receipt."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _require_release_artifacts(output_dir)

    with tempfile.TemporaryDirectory(prefix="cambrian-external-alpha-manual-go-") as temp_name:
        temp_root = Path(temp_name).resolve()
        work_dir = temp_root / "release"
        private_dir = temp_root / "private"
        work_dir.mkdir()
        private_dir.mkdir()
        _copy_output_files(output_dir, work_dir)
        packet_path = work_dir / PACKET_JSON_NAME

        # Lazy imports avoid a circular dependency with the operator packet builder.
        from scripts.audit_external_alpha_operator_send_bypass import (  # noqa: PLC0415
            audit_operator_send_bypass,
            verify_operator_send_bypass_audit_file,
        )
        from scripts.prepare_external_alpha_first_recipient_send_workspace import (  # noqa: PLC0415
            prepare_first_recipient_send_workspace,
        )
        from scripts.check_external_alpha_first_recipient_manual_send_go import (  # noqa: PLC0415
            check_first_recipient_manual_send_go,
            verify_first_recipient_manual_send_go_receipt_file,
        )
        from scripts.check_external_alpha_first_recipient_operator_status import (  # noqa: PLC0415
            check_first_recipient_operator_status,
            verify_first_recipient_operator_status_receipt_file,
        )
        from scripts.check_external_alpha_first_recipient_send_preflight import (  # noqa: PLC0415
            check_first_recipient_send_preflight,
            verify_first_recipient_send_preflight_receipt_file,
        )

        workspace = prepare_first_recipient_send_workspace(private_dir, operator_packet_path=packet_path)
        runbook_text = Path(workspace["private_runbook"]).read_text(encoding="utf-8")
        _write_synthetic_private_files(private_dir, runbook_text)
        check_first_recipient_send_preflight(private_dir, operator_packet_path=packet_path)
        preflight = verify_first_recipient_send_preflight_receipt_file(
            private_dir / PREFLIGHT_RECEIPT_NAME,
            require_ready=True,
        )
        audit_operator_send_bypass(work_dir, workspace_dir=private_dir)
        operator_bypass = verify_operator_send_bypass_audit_file(work_dir / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME)
        check_first_recipient_manual_send_go(
            private_dir,
            output_dir=work_dir,
            operator_packet_path=packet_path,
            require_manual_send_go_rehearsal=False,
        )
        manual_go = verify_first_recipient_manual_send_go_receipt_file(private_dir / MANUAL_SEND_GO_RECEIPT_NAME)
        check_first_recipient_operator_status(
            private_dir,
            output_dir=work_dir,
            operator_packet_path=packet_path,
            require_manual_send_go_rehearsal=False,
        )
        operator_status = verify_first_recipient_operator_status_receipt_file(
            private_dir / OPERATOR_STATUS_RECEIPT_NAME
        )
        generated_text = _generated_shareable_text(work_dir=work_dir, private_dir=private_dir)
        payload = _rehearsal_payload(
            preflight=preflight,
            operator_bypass=operator_bypass,
            manual_go=manual_go,
            operator_status=operator_status,
            generated_text=generated_text,
            temp_root=temp_root,
            private_workspace_file_names={path.name for path in private_dir.iterdir() if path.is_file()},
            operator_note_template_used=True,
        )

    receipt_path = output_dir / MANUAL_SEND_GO_REHEARSAL_RECEIPT_NAME
    _write_json(receipt_path, payload)
    verify_manual_send_go_rehearsal_receipt_file(receipt_path)
    _assert_shareable_file(receipt_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "archive_sha256": payload["release"]["archive_sha256"],
        "receipt_body_sha256": payload["manual_send_go_rehearsal_receipt_body_sha256"],
    }


def verify_manual_send_go_rehearsal_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_manual_send_go_rehearsal_receipt_payload(payload)
    return payload


def verify_manual_send_go_rehearsal_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != MANUAL_SEND_GO_REHEARSAL_SCHEMA_VERSION:
        raise ManualSendGoRehearsalError("manual-send GO rehearsal schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "REHEARSAL_PASS":
        raise ManualSendGoRehearsalError("manual-send GO rehearsal did not pass.")
    if payload.get("safe_to_share") is not True:
        raise ManualSendGoRehearsalError("manual-send GO rehearsal safe_to_share must be true.")
    if payload.get("real_manual_send") is not False:
        raise ManualSendGoRehearsalError("manual-send GO rehearsal must not claim a real manual send.")
    if payload.get("real_recipient_evidence") is not False:
        raise ManualSendGoRehearsalError("manual-send GO rehearsal must not claim real recipient evidence.")
    if payload.get("synthetic_private_values_used") is not True:
        raise ManualSendGoRehearsalError("manual-send GO rehearsal must disclose synthetic private values.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise ManualSendGoRehearsalError("manual-send GO rehearsal checks failed.")
    missing_or_failed = [name for name in REQUIRED_TRUE_CHECKS if checks.get(name) is not True]
    if missing_or_failed:
        raise ManualSendGoRehearsalError(
            "manual-send GO rehearsal required checks missing or failed: " + ", ".join(missing_or_failed)
        )
    rehearsed_flow = payload.get("rehearsed_flow") if isinstance(payload.get("rehearsed_flow"), dict) else {}
    if rehearsed_flow.get("operator_status_verdict") != "READY_TO_MANUALLY_SEND_ONE":
        raise ManualSendGoRehearsalError("manual-send GO rehearsal operator status is not ready.")
    if rehearsed_flow.get("operator_status_manual_send_go_packet_bound") is not True:
        raise ManualSendGoRehearsalError("manual-send GO rehearsal operator status packet binding is not ready.")
    if not _looks_like_sha256(rehearsed_flow.get("operator_status_receipt_body_sha256")):
        raise ManualSendGoRehearsalError("manual-send GO rehearsal operator status receipt hash is missing.")
    if payload.get("manual_send_go_rehearsal_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise ManualSendGoRehearsalError("manual-send GO rehearsal receipt body hash mismatch.")
    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden = [str(ROOT), str(Path.home()), *PRIVATE_MARKERS]
    leaked = [item for item in forbidden if item and item in serialized]
    if leaked:
        raise ManualSendGoRehearsalError("manual-send GO rehearsal receipt contains private material.")


def _rehearsal_payload(
    *,
    preflight: dict[str, Any],
    operator_bypass: dict[str, Any],
    manual_go: dict[str, Any],
    operator_status: dict[str, Any],
    generated_text: str,
    temp_root: Path,
    private_workspace_file_names: set[str],
    operator_note_template_used: bool,
) -> dict[str, Any]:
    release = manual_go.get("release") if isinstance(manual_go.get("release"), dict) else {}
    preflight_release = preflight.get("release") if isinstance(preflight.get("release"), dict) else {}
    bypass_release = operator_bypass.get("release") if isinstance(operator_bypass.get("release"), dict) else {}
    go_checks = manual_go.get("checks") if isinstance(manual_go.get("checks"), dict) else {}
    gate_receipts = manual_go.get("gate_receipts") if isinstance(manual_go.get("gate_receipts"), dict) else {}
    operator_status_release = (
        operator_status.get("release") if isinstance(operator_status.get("release"), dict) else {}
    )
    operator_status_manual_send_go_packet_bound = _operator_status_checklist_done(
        operator_status,
        "manual_send_go_operator_packet_bound",
    )
    final_audit = (
        gate_receipts.get("final_send_chain_audit")
        if isinstance(gate_receipts.get("final_send_chain_audit"), dict)
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
    operator_note = next(
        (
            item
            for item in preflight_files
            if isinstance(item, dict) and item.get("file") == "operator-dispatch-note-private.md"
        ),
        {},
    )
    temp_path = str(temp_root)
    checks = {
        "preflight_ready": preflight.get("status") == "pass"
        and preflight.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY",
        "preflight_private_hashes_present": all(
            isinstance(item, dict)
            and item.get("file") in PRIVATE_WORKSPACE_FILES
            and item.get("status") == "ready"
            and _looks_like_sha256(item.get("sha256"))
            for item in preflight_files
        )
        and {item.get("file") for item in preflight_files if isinstance(item, dict)}
        == set(PRIVATE_WORKSPACE_FILES),
        "operator_bypass_ready": operator_bypass.get("status") == "pass"
        and operator_bypass.get("verdict") == "NO_OPERATOR_PREFLIGHT_BYPASS",
        "manual_send_go_ready": manual_go.get("status") == "pass"
        and manual_go.get("verdict") == "GO_TO_MANUALLY_SEND_ONE",
        "operator_status_ready_to_send": operator_status.get("status") == "pass"
        and operator_status.get("verdict") == "READY_TO_MANUALLY_SEND_ONE",
        "operator_status_safe_to_share": operator_status.get("safe_to_share") is True,
        "operator_status_release_hash_matches": operator_status_release.get("archive_sha256")
        == release.get("archive_sha256")
        and _looks_like_sha256(operator_status_release.get("archive_sha256")),
        "operator_status_manual_send_go_packet_bound": operator_status_manual_send_go_packet_bound,
        "manual_go_final_chain_ready": final_audit.get("verdict") == "READY_TO_SEND_ONE"
        and final_audit.get("operator_bypass_audit_required") is True,
        "manual_go_checks_all_true": bool(go_checks) and all(value is True for value in go_checks.values()),
        "release_hashes_match": release.get("archive_sha256")
        == preflight_release.get("archive_sha256")
        == bypass_release.get("archive_sha256")
        and _looks_like_sha256(release.get("archive_sha256")),
        "standard_private_workspace_filenames_used": set(PRIVATE_WORKSPACE_FILES).issubset(
            private_workspace_file_names
        ),
        "private_runbook_required_preflight": PRIVATE_SEND_RUNBOOK_NAME in private_workspace_file_names,
        "operator_note_template_used": operator_note_template_used,
        "operator_note_template_preflight_contract": operator_note.get("mentions_channel") is True
        and operator_note.get("contains_release_hash") is True,
        "manual_dispatch_only": manual_go.get("policy", {}).get("script_sends_to_recipient") is False
        and manual_go.get("policy", {}).get("manual_operator_dispatch_required") is True,
        "one_recipient_policy_locked": manual_go.get("policy", {}).get("max_recipients") == 1,
        "preflight_did_not_record_send": go_checks.get("preflight_records_no_send") is True,
        "script_did_not_send_to_recipient": go_checks.get("script_does_not_send_to_recipient") is True,
        "synthetic_private_values_disclosed": True,
        "real_manual_send_not_claimed": True,
        "real_recipient_evidence_not_claimed": True,
        "raw_private_content_omitted": not any(marker in generated_text for marker in PRIVATE_MARKERS),
        "temporary_paths_omitted": temp_path not in generated_text,
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
            "Operator-only rehearsal proving the final manual-send GO gate can pass after private fields are "
            "filled. This receipt is not evidence that any real recipient was contacted."
        ),
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "rehearsed_flow": {
            "preflight_verdict": preflight.get("verdict"),
            "preflight_receipt_body_sha256": preflight.get(
                "first_recipient_send_preflight_receipt_body_sha256"
            ),
            "operator_bypass_verdict": operator_bypass.get("verdict"),
            "operator_bypass_receipt_body_sha256": operator_bypass.get(
                "operator_send_bypass_audit_body_sha256"
            ),
            "manual_send_go_verdict": manual_go.get("verdict"),
            "manual_send_go_receipt_body_sha256": manual_go.get("manual_send_go_receipt_body_sha256"),
            "operator_status_verdict": operator_status.get("verdict"),
            "operator_status_receipt_body_sha256": operator_status.get(
                "operator_status_receipt_body_sha256"
            ),
            "operator_status_manual_send_go_packet_bound": operator_status_manual_send_go_packet_bound,
            "final_send_chain_verdict": final_audit.get("verdict"),
            "final_send_chain_requires_bypass": final_audit.get("operator_bypass_audit_required"),
        },
        "private_input_policy": {
            "private_files_used_in_temp_workspace": True,
            "standard_private_workspace_files": list(PRIVATE_WORKSPACE_FILES),
            "stored_private_values": False,
            "stored_private_paths": False,
            "stored_private_hashes_only": True,
            "manual_send_performed": False,
            "synthetic_values_only": True,
        },
        "operator_boundary": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "rehearsal_receipt_is_not_dispatch_evidence": True,
        },
        "checks": checks,
    }
    payload["manual_send_go_rehearsal_receipt_body_sha256"] = _receipt_body_sha256(payload)
    return payload


def _operator_status_checklist_done(operator_status: dict[str, Any], item_id: str) -> bool:
    checklist = operator_status.get("operator_safe_checklist")
    if not isinstance(checklist, list):
        return False
    return any(isinstance(item, dict) and item.get("id") == item_id and item.get("done") is True for item in checklist)


def _require_release_artifacts(output_dir: Path) -> None:
    required = (
        f"{RELEASE_SLUG}.zip",
        f"{RELEASE_SLUG}.manifest.json",
        "external_alpha_release_verification_receipt.json",
        f"{RELEASE_SLUG}-handoff.json",
        f"{RELEASE_SLUG}-send-ready.json",
        f"{RELEASE_SLUG}-pilot-ready.json",
        f"{RELEASE_SLUG}-dispatch-record.json",
        f"{RELEASE_SLUG}-recipient-checkpoint.json",
        f"{RELEASE_SLUG}-pilot-review.json",
        f"{RELEASE_SLUG}-pilot-evidence.json",
        f"{RELEASE_SLUG}-pilot-decision.json",
        f"{RELEASE_SLUG}-pilot-iteration.json",
        f"{RELEASE_SLUG}-bundle-smoke-receipt.json",
        PACKET_JSON_NAME,
    )
    missing = [name for name in required if not (output_dir / name).is_file()]
    if missing:
        raise ManualSendGoRehearsalError("release artifacts are required before rehearsal: " + ", ".join(missing))


def _copy_output_files(source_dir: Path, target_dir: Path) -> None:
    for path in sorted(item for item in source_dir.iterdir() if item.is_file()):
        shutil.copy2(path, target_dir / path.name)


def _write_synthetic_private_files(private_dir: Path, runbook_text: str) -> None:
    (private_dir / "recipient-private.txt").write_text(
        "MANUAL_SEND_GO_REHEARSAL_PRIVATE_RECIPIENT one-recipient@example.invalid\n",
        encoding="utf-8",
    )
    operator_note = _operator_note_template_from_runbook(runbook_text).replace(
        "<private-send-channel>",
        "direct message",
    )
    (private_dir / "operator-dispatch-note-private.md").write_text(
        operator_note,
        encoding="utf-8",
    )


def _operator_note_template_from_runbook(runbook_text: str) -> str:
    marker = "## Operator Dispatch Note Template"
    try:
        start = runbook_text.index(marker)
        fenced_start = runbook_text.index("```text", start) + len("```text")
        fenced_end = runbook_text.index("```", fenced_start)
    except ValueError as exc:
        raise ManualSendGoRehearsalError("private runbook operator note template is missing.") from exc
    return runbook_text[fenced_start:fenced_end].strip() + "\n"


def _generated_shareable_text(*, work_dir: Path, private_dir: Path) -> str:
    chunks: list[str] = []
    for path in sorted(item for item in work_dir.rglob("*") if item.is_file()):
        if path.suffix.lower() in {".json", ".md"}:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    for name in (PREFLIGHT_RECEIPT_NAME, MANUAL_SEND_GO_RECEIPT_NAME, OPERATOR_STATUS_RECEIPT_NAME):
        path = private_dir / name
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "manual_send_go_rehearsal_receipt_body_sha256"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ManualSendGoRehearsalError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ManualSendGoRehearsalError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ManualSendGoRehearsalError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_shareable_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [str(ROOT), str(Path.home()), *PRIVATE_MARKERS]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise ManualSendGoRehearsalError(f"manual-send GO rehearsal receipt contains private material: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rehearse external alpha manual-send GO gate without sending.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing manual-send GO rehearsal receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_manual_send_go_rehearsal_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
            logger.error("[FAIL] external alpha manual-send GO rehearsal verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha manual-send GO rehearsal verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["manual_send_go_rehearsal_receipt_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = smoke_manual_send_go_rehearsal(Path(args.output_dir))
    except Exception as exc:  # noqa: BLE001 - show operator-facing reason.
        logger.error("[FAIL] external alpha manual-send GO rehearsal: %s", exc)
        return 1

    logger.info("[PASS] external alpha manual-send GO rehearsal")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
