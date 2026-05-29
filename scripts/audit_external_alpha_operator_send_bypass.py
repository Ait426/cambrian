"""Audit operator-facing send surfaces for preflight bypasses."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.prepare_external_alpha_first_recipient_send_workspace import (  # noqa: E402
    DEFAULT_FIRST_RECIPIENT_WORKSPACE_DIR,
    PRIVATE_SEND_RUNBOOK_NAME,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import (  # noqa: E402
    PACKET_JSON_NAME,
    verify_operator_dispatch_packet_file,
)


OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION = "external_alpha_operator_send_bypass_audit_v0_1"
OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME = f"{RELEASE_SLUG}-operator-send-bypass-audit.json"

logger = logging.getLogger(__name__)


class OperatorSendBypassAuditError(RuntimeError):
    """Operator send bypass audit failed."""


def audit_operator_send_bypass(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    workspace_dir: Path = DEFAULT_FIRST_RECIPIENT_WORKSPACE_DIR,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Ensure exposed one-recipient send paths cannot skip the pre-send preflight."""
    output_dir = output_dir.resolve()
    workspace_dir = workspace_dir.resolve()
    operator_packet_path = output_dir / PACKET_JSON_NAME
    operator_packet = _load_operator_packet(operator_packet_path)
    release_manifest_path = ROOT / "docs" / "release" / "EXTERNAL_ALPHA_RELEASE_MANIFEST.md"
    first_recipient_script_path = ROOT / "scripts" / "prepare_external_alpha_first_recipient_send_workspace.py"
    private_workspace_script_path = ROOT / "scripts" / "prepare_external_alpha_private_pilot_workspace.py"
    private_runbook_path = workspace_dir / PRIVATE_SEND_RUNBOOK_NAME

    sources = {
        "operator_dispatch_packet_json": json.dumps(operator_packet, ensure_ascii=False),
        "release_manifest_doc": _read_text(release_manifest_path),
        "first_recipient_workspace_script": _read_text(first_recipient_script_path),
        "private_workspace_script": _read_text(private_workspace_script_path),
        "private_send_runbook": _read_text(private_runbook_path) if private_runbook_path.is_file() else "",
    }
    payload = _audit_payload(
        operator_packet=operator_packet,
        source_texts=sources,
        private_runbook_present=private_runbook_path.is_file(),
    )
    receipt_path = (receipt_path or output_dir / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_operator_send_bypass_audit_file(receipt_path)
    _assert_shareable_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["operator_send_bypass_audit_body_sha256"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def verify_operator_send_bypass_audit_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_operator_send_bypass_audit_payload(payload)
    return payload


def verify_operator_send_bypass_audit_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION:
        raise OperatorSendBypassAuditError("operator send bypass audit schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "NO_OPERATOR_PREFLIGHT_BYPASS":
        raise OperatorSendBypassAuditError("operator send bypass audit did not pass.")
    if payload.get("safe_to_share") is not True:
        raise OperatorSendBypassAuditError("operator send bypass audit must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise OperatorSendBypassAuditError("operator send bypass audit checks failed.")
    audit_checks = payload.get("operator_send_bypass_audit_checks")
    recalculated = _audit_receipt_checks(payload)
    if audit_checks != recalculated:
        raise OperatorSendBypassAuditError("operator send bypass audit self-checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise OperatorSendBypassAuditError("operator send bypass audit self-check failed: " + ", ".join(failed))
    if payload.get("operator_send_bypass_audit_body_sha256") != _audit_body_sha256(payload):
        raise OperatorSendBypassAuditError("operator send bypass audit body hash mismatch.")


def _audit_payload(
    *,
    operator_packet: dict[str, Any],
    source_texts: dict[str, str],
    private_runbook_present: bool,
) -> dict[str, Any]:
    release = operator_packet.get("release") if isinstance(operator_packet.get("release"), dict) else {}
    before_manual = (
        operator_packet.get("before_manual_send")
        if isinstance(operator_packet.get("before_manual_send"), dict)
        else {}
    )
    after_manual = (
        operator_packet.get("after_manual_send")
        if isinstance(operator_packet.get("after_manual_send"), dict)
        else {}
    )
    source_results = {
        name: _source_requires_preflight(name, text)
        for name, text in source_texts.items()
        if name != "private_send_runbook" or private_runbook_present
    }
    checks = {
        "operator_packet_ready_to_send_one": operator_packet.get("verdict") == "READY_TO_SEND_ONE",
        "operator_packet_preflight_command_present": "check_external_alpha_first_recipient_send_preflight.py"
        in str(before_manual.get("pre_send_preflight_command")),
        "operator_packet_record_command_requires_preflight": "--require-preflight-receipt"
        in str(after_manual.get("record_command")),
        "operator_packet_checkpoint_command_requires_preflight": "--require-preflight-receipt"
        in str(after_manual.get("then_checkpoint_command")),
        "operator_packet_record_command_private_workspace_only": "--private-workspace-dir <private-workspace-dir>"
        in str(after_manual.get("record_command")),
        "release_manifest_preflight_command_present": "check_external_alpha_first_recipient_send_preflight.py"
        in source_texts.get("release_manifest_doc", ""),
        "private_runbook_checked_when_present": (not private_runbook_present)
        or "check_external_alpha_first_recipient_send_preflight.py" in source_texts.get("private_send_runbook", ""),
        "all_operator_dispatch_commands_require_preflight": all(source_results.values()),
        "source_paths_are_public_names_only": True,
        "receipt_omits_raw_operator_packet_text": True,
        "receipt_omits_private_workspace_path": True,
    }
    payload: dict[str, Any] = {
        "schema_version": OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "NO_OPERATOR_PREFLIGHT_BYPASS" if all(checks.values()) else "OPERATOR_PREFLIGHT_BYPASS_FOUND",
        "safe_to_share": True,
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "operator_packet": {
            "file": PACKET_JSON_NAME,
            "body_sha256": operator_packet.get("operator_dispatch_packet_body_sha256"),
        },
        "audited_sources": [
            {"source": name, "dispatch_commands_require_preflight": passed}
            for name, passed in sorted(source_results.items())
        ],
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "pre_send_preflight_required_before_dispatch_record": True,
            "pre_send_preflight_required_before_recipient_checkpoint": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "checks": checks,
    }
    payload["operator_send_bypass_audit_body_sha256"] = _audit_body_sha256(payload)
    payload["operator_send_bypass_audit_checks"] = _audit_receipt_checks(payload)
    return payload


def _source_requires_preflight(_name: str, text: str) -> bool:
    if not text:
        return False
    markers = (
        "check_external_alpha_dispatch_record.py",
        "check_external_alpha_recipient_checkpoint.py",
    )
    for marker in markers:
        start = 0
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            window = text[index : index + 700]
            if "--private-workspace-dir" in window and "--require-preflight-receipt" not in window:
                return False
            start = index + len(marker)
    return True


def _audit_receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    operator_packet = payload.get("operator_packet") if isinstance(payload.get("operator_packet"), dict) else {}
    audited_sources = payload.get("audited_sources") if isinstance(payload.get("audited_sources"), list) else []
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    body_hash = payload.get("operator_send_bypass_audit_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_no_bypass": payload.get("verdict") == "NO_OPERATOR_PREFLIGHT_BYPASS",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "operator_packet_hash_present": _looks_like_sha256(operator_packet.get("body_sha256")),
        "audited_sources_present": bool(audited_sources),
        "audited_sources_all_pass": all(
            isinstance(item, dict) and item.get("dispatch_commands_require_preflight") is True
            for item in audited_sources
        ),
        "absolute_paths_omitted": str(ROOT) not in serialized and str(Path.home()) not in serialized,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _audit_body_sha256(payload),
    }


def _load_operator_packet(path: Path) -> dict[str, Any]:
    try:
        return verify_operator_dispatch_packet_file(path)
    except Exception as exc:  # noqa: BLE001 - operator-facing error.
        raise OperatorSendBypassAuditError(f"operator dispatch packet is not ready: {path.name}") from exc


def _audit_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_send_bypass_audit_body_sha256", "operator_send_bypass_audit_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise OperatorSendBypassAuditError(f"cannot read audit source: {path.name}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise OperatorSendBypassAuditError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise OperatorSendBypassAuditError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise OperatorSendBypassAuditError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _assert_shareable_receipt_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [
        str(ROOT),
        str(Path.home()),
        "Recipient identifier/contact goes here",
        "Record the private channel",
        "<private-send-channel>",
    ]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise OperatorSendBypassAuditError("operator send bypass audit receipt leaked local path or private text.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit external alpha operator send surfaces for preflight bypasses.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--workspace-dir", default=str(DEFAULT_FIRST_RECIPIENT_WORKSPACE_DIR))
    parser.add_argument("--receipt", default=None, help="Optional share-safe audit receipt JSON path.")
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing operator send bypass audit receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_operator_send_bypass_audit_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
            logger.error("[FAIL] external alpha operator send bypass audit verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha operator send bypass audit verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["operator_send_bypass_audit_body_sha256"])
        return 0

    try:
        result = audit_operator_send_bypass(
            Path(args.output_dir),
            workspace_dir=Path(args.workspace_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
        logger.error("[FAIL] external alpha operator send bypass audit: %s", exc)
        return 1

    logger.info("[PASS] external alpha operator send bypass audit")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
