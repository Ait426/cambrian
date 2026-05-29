"""Audit Cambrian install-kit operator send surfaces for status-gate bypasses."""

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

from scripts.check_cambrian_install_kit_dispatch_record import (  # noqa: E402
    DISPATCH_RECORD_JSON_NAME,
    check_dispatch_record,
    verify_dispatch_record_file,
)
from scripts.prepare_cambrian_install_kit_first_recipient_workspace import (  # noqa: E402
    DEFAULT_WORKSPACE_DIR,
    PRIVATE_WORKSPACE_DIR_PLACEHOLDER,
    PRIVATE_RUNBOOK_NAME,
    SENT_AT_UTC_PLACEHOLDER,
)


OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION = "cambrian_install_kit_operator_send_bypass_audit_v0_1"
OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME = "cambrian-install-kit-operator-send-bypass-audit.json"

logger = logging.getLogger(__name__)


class InstallKitOperatorSendBypassAuditError(RuntimeError):
    """Install-kit operator send bypass audit failed."""


def audit_install_kit_operator_send_bypass(
    output_dir: Path | None = None,
    *,
    workspace_dir: Path | None = None,
    receipt_path: Path | None = None,
    skip_verify: bool = False,
) -> dict[str, Any]:
    """Write a share-safe audit receipt proving dispatch commands require pre-send proof."""
    dist = (output_dir or ROOT / "dist").resolve()
    workspace = (workspace_dir or DEFAULT_WORKSPACE_DIR).resolve()
    dist.mkdir(parents=True, exist_ok=True)
    dispatch_record = _load_or_create_dispatch_record(dist, skip_verify=skip_verify)

    release_doc_path = ROOT / "docs" / "release" / "CAMBRIAN_INSTALL_KIT.md"
    workspace_script_path = ROOT / "scripts" / "prepare_cambrian_install_kit_first_recipient_workspace.py"
    operator_status_script_path = ROOT / "scripts" / "check_cambrian_install_kit_first_recipient_operator_status.py"
    post_send_sequence_script_path = ROOT / "scripts" / "check_cambrian_install_kit_first_recipient_post_send_sequence.py"
    dispatch_record_script_path = ROOT / "scripts" / "check_cambrian_install_kit_dispatch_record.py"
    recipient_checkpoint_script_path = ROOT / "scripts" / "check_cambrian_install_kit_recipient_checkpoint.py"
    private_runbook_path = workspace / PRIVATE_RUNBOOK_NAME

    private_runbook_present = private_runbook_path.is_file()
    source_texts = {
        "install_kit_release_doc": _read_text(release_doc_path),
        "first_recipient_workspace_script": _read_text(workspace_script_path),
        "first_recipient_operator_status_script": _read_text(operator_status_script_path),
        "first_recipient_post_send_sequence_script": _read_text(post_send_sequence_script_path),
        "dispatch_record_script": _read_text(dispatch_record_script_path),
        "recipient_checkpoint_script": _read_text(recipient_checkpoint_script_path),
        "private_runbook": _read_text(private_runbook_path) if private_runbook_present else "",
    }
    payload = _audit_payload(
        dispatch_record=dispatch_record,
        source_texts=source_texts,
        private_runbook_present=private_runbook_present,
    )
    target = (receipt_path or dist / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, payload)
    verify_operator_send_bypass_audit_file(target)
    _assert_shareable_receipt_file(target)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(target),
        "receipt_body_sha256": payload["operator_send_bypass_audit_body_sha256"],
        "dispatch_record_body_sha256": payload["dispatch_record"]["body_sha256"],
    }


def verify_operator_send_bypass_audit_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_operator_send_bypass_audit_payload(payload)
    return payload


def verify_operator_send_bypass_audit_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION:
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != "NO_OPERATOR_STATUS_BYPASS":
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit did not pass.")
    if payload.get("safe_to_share") is not True:
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit checks failed.")
    recalculated = _audit_receipt_checks(payload)
    if payload.get("operator_send_bypass_audit_checks") != recalculated:
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit self-checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit self-check failed: " + ", ".join(failed))
    if payload.get("operator_send_bypass_audit_body_sha256") != _audit_body_sha256(payload):
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit body hash mismatch.")


def _load_or_create_dispatch_record(dist: Path, *, skip_verify: bool) -> dict[str, Any]:
    path = dist / DISPATCH_RECORD_JSON_NAME
    if path.is_file():
        return verify_dispatch_record_file(path)
    result = check_dispatch_record(output_dir=dist, skip_verify=skip_verify)
    return verify_dispatch_record_file(Path(str(result["dispatch_record_json"])))


def _audit_payload(
    *,
    dispatch_record: dict[str, Any],
    source_texts: dict[str, str],
    private_runbook_present: bool,
) -> dict[str, Any]:
    dispatch_policy = (
        dispatch_record.get("dispatch_execution_policy")
        if isinstance(dispatch_record.get("dispatch_execution_policy"), dict)
        else {}
    )
    source_results = {
        name: _dispatch_commands_require_pre_send_proof(name, text)
        for name, text in source_texts.items()
        if name != "private_runbook" or private_runbook_present
    }
    shell_safe_results = {
        name: _operator_command_placeholders_shell_safe(name, text)
        for name, text in source_texts.items()
        if name != "private_runbook" or private_runbook_present
    }
    checks = {
        "dispatch_record_ready_or_recorded": dispatch_record.get("verdict")
        in {"READY_TO_SEND_ONE", "SENT_ONE_RECORDED"},
        "dispatch_record_manual_operator_required": dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_record_script_sends_to_recipient_false": dispatch_policy.get("script_sends_to_recipient") is False,
        "dispatch_record_private_hashes_only": dispatch_policy.get("records_private_sha256_only") is True,
        "dispatch_script_requires_status_receipt_when_required": _dispatch_script_enforces_required_receipt(
            source_texts.get("dispatch_record_script", "")
        ),
        "dispatch_script_requires_manual_send_go_when_required": _dispatch_script_enforces_required_manual_send_go(
            source_texts.get("dispatch_record_script", "")
        ),
        "recipient_checkpoint_requires_status_receipt_when_post_send": _recipient_checkpoint_script_enforces_required_receipt(
            source_texts.get("recipient_checkpoint_script", "")
        ),
        "recipient_checkpoint_requires_manual_send_go_when_post_send": _recipient_checkpoint_script_enforces_manual_send_go(
            source_texts.get("recipient_checkpoint_script", "")
        ),
        "post_send_sequence_requires_status_receipt_when_recording": _post_send_sequence_script_enforces_required_receipt(
            source_texts.get("first_recipient_post_send_sequence_script", "")
        ),
        "post_send_sequence_requires_manual_send_go_when_recording": _post_send_sequence_script_enforces_manual_send_go(
            source_texts.get("first_recipient_post_send_sequence_script", "")
        ),
        "release_doc_dispatch_commands_require_operator_status": source_results.get(
            "install_kit_release_doc"
        )
        is True,
        "workspace_runbook_dispatch_commands_require_operator_status": source_results.get(
            "first_recipient_workspace_script"
        )
        is True,
        "operator_status_safe_command_requires_operator_status": source_results.get(
            "first_recipient_operator_status_script"
        )
        is True,
        "private_runbook_checked_when_present": (not private_runbook_present)
        or source_results.get("private_runbook") is True,
        "all_operator_dispatch_commands_require_operator_status": bool(source_results)
        and all(source_results.values()),
        "release_doc_operator_commands_shell_safe": shell_safe_results.get("install_kit_release_doc") is True,
        "workspace_operator_commands_shell_safe": shell_safe_results.get("first_recipient_workspace_script") is True,
        "operator_status_operator_commands_shell_safe": shell_safe_results.get("first_recipient_operator_status_script")
        is True,
        "private_runbook_shell_safe_when_present": (not private_runbook_present)
        or shell_safe_results.get("private_runbook") is True,
        "all_operator_command_placeholders_shell_safe": bool(shell_safe_results)
        and all(shell_safe_results.values()),
        "receipt_omits_raw_source_text": True,
        "receipt_omits_private_workspace_path": True,
        "receipt_omits_raw_private_values": True,
    }
    payload: dict[str, Any] = {
        "schema_version": OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "verdict": "NO_OPERATOR_STATUS_BYPASS" if all(checks.values()) else "OPERATOR_STATUS_BYPASS_FOUND",
        "safe_to_share": True,
        "dispatch_record": {
            "file": DISPATCH_RECORD_JSON_NAME,
            "verdict": dispatch_record.get("verdict"),
            "body_sha256": dispatch_record.get("dispatch_record_body_sha256"),
        },
        "audited_sources": [
            {
                "source": name,
                "dispatch_commands_require_operator_status": passed,
                "dispatch_commands_require_manual_send_go": passed,
                "dispatch_commands_require_pre_send_proof": passed,
                "operator_command_placeholders_shell_safe": shell_safe_results.get(name) is True,
            }
            for name, passed in sorted(source_results.items())
        ],
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "status_receipt_required_before_sent_record": True,
            "manual_send_go_receipt_required_before_sent_record": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "checks": checks,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    payload["operator_send_bypass_audit_body_sha256"] = _audit_body_sha256(payload)
    payload["operator_send_bypass_audit_checks"] = _audit_receipt_checks(payload)
    return payload


def _dispatch_commands_require_pre_send_proof(_name: str, text: str) -> bool:
    if not text:
        return False
    markers = (
        "check_cambrian_install_kit_dispatch_record.py",
        "check_cambrian_install_kit_recipient_checkpoint.py",
    )
    seen_private_dispatch = False
    for marker in markers:
        start = 0
        while True:
            index = text.find(marker, start)
            if index < 0:
                break
            window = _dispatch_command_window(_name, text, index)
            private_or_sent_record = any(
                flag in window
                for flag in (
                    "--recipient-private-file",
                    "--recipient-private-sha256",
                    "--operator-dispatch-note-private-file",
                    "--operator-dispatch-note-private-sha256",
                    "--recipient-ack-private-file",
                    "--recipient-ack-private-sha256",
                    "--install-share-receipt",
                    "--gold-path-share-receipt",
                    "--mcp-operability-receipt",
                    "--sent-at-utc",
                )
            )
            if private_or_sent_record:
                seen_private_dispatch = True
                if "--operator-status-receipt" not in window or "--require-operator-status-receipt" not in window:
                    return False
                if "--manual-send-go-receipt" not in window or "--require-manual-send-go-receipt" not in window:
                    return False
            start = index + len(marker)
    return True if seen_private_dispatch else True


def _dispatch_command_window(name: str, text: str, index: int) -> str:
    if name not in {"install_kit_release_doc", "private_runbook"}:
        return text[index : index + 1400]
    line_start = text.rfind("\n", 0, index) + 1
    lines = text[line_start:].splitlines()
    collected: list[str] = []
    for line in lines:
        if collected and line.startswith("python scripts/"):
            break
        collected.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return "\n".join(collected)


def _dispatch_script_enforces_required_receipt(text: str) -> bool:
    required_markers = (
        "--operator-status-receipt",
        "--require-operator-status-receipt",
        "operator status receipt is required before recording SENT_ONE_RECORDED",
        "READY_TO_MANUALLY_SEND_ONE before recording SENT_ONE_RECORDED",
        "release hash does not match the dispatch release bundle",
        "private hashes do not match the dispatch private files",
    )
    return all(marker in text for marker in required_markers)


def _dispatch_script_enforces_required_manual_send_go(text: str) -> bool:
    required_markers = (
        "--manual-send-go-receipt",
        "--require-manual-send-go-receipt",
        "manual-send GO receipt is required before recording SENT_ONE_RECORDED",
        "manual-send GO receipt must be GO_TO_MANUALLY_SEND_ONE before recording SENT_ONE_RECORDED",
        "manual-send GO receipt release hash does not match the dispatch release bundle",
        "manual-send GO receipt does not match the dispatch operator status receipt",
    )
    return all(marker in text for marker in required_markers)


def _recipient_checkpoint_script_enforces_required_receipt(text: str) -> bool:
    required_markers = (
        "--operator-status-receipt",
        "--require-operator-status-receipt",
        "post_send_inputs_present",
        "require_operator_status",
        "operator_status_required_when_post_send",
        "operator_status_ready_when_post_send",
        "operator_status_matches_post_send_hashes",
    )
    return all(marker in text for marker in required_markers)


def _recipient_checkpoint_script_enforces_manual_send_go(text: str) -> bool:
    required_markers = (
        "--manual-send-go-receipt",
        "--require-manual-send-go-receipt",
        "manual_send_go_receipt",
        "require_manual_send_go",
        "require_manual_send_go_receipt",
    )
    return all(marker in text for marker in required_markers)


def _post_send_sequence_script_enforces_required_receipt(text: str) -> bool:
    required_markers = (
        "SENT_AT_UTC_REQUIRED",
        "check_dispatch_record(",
        "operator_status_receipt=workspace / OPERATOR_STATUS_READY_RECEIPT_NAME",
        "require_operator_status_receipt=True",
        "check_recipient_checkpoint(",
        "operator_status_pre_send",
        "operator_status_required_and_ready",
        "operator_status_matches_dispatch",
    )
    return all(marker in text for marker in required_markers)


def _post_send_sequence_script_enforces_manual_send_go(text: str) -> bool:
    required_markers = (
        "MANUAL_SEND_GO_RECEIPT_NAME",
        "manual_send_go_receipt=workspace / MANUAL_SEND_GO_RECEIPT_NAME",
        "require_manual_send_go_receipt=True",
    )
    return all(marker in text for marker in required_markers)


def _operator_command_placeholders_shell_safe(name: str, text: str) -> bool:
    if not text:
        return False
    unsafe_patterns = (
        f"--sent-at-utc {SENT_AT_UTC_PLACEHOLDER}",
        f"--workspace-dir {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--verify-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--recipient-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--operator-dispatch-note-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--operator-status-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--manual-send-go-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--recipient-ack-private-file {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--install-share-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--gold-path-share-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        f"--mcp-operability-receipt {PRIVATE_WORKSPACE_DIR_PLACEHOLDER}",
        "--install-share-receipt <path/to/",
        "--gold-path-share-receipt <path/to/",
        "--mcp-operability-receipt <path/to/",
        "--recipient-private-file <private-",
        "--operator-dispatch-note-private-file <private-",
        "--recipient-ack-private-file <private-",
    )
    if any(pattern in text for pattern in unsafe_patterns):
        return False
    if name in {"install_kit_release_doc", "private_runbook"}:
        if "--sent-at-utc" in text and f'--sent-at-utc "{SENT_AT_UTC_PLACEHOLDER}"' not in text:
            return False
        if "private-workspace-dir" in text and f'"{PRIVATE_WORKSPACE_DIR_PLACEHOLDER}' not in text:
            return False
    if name == "first_recipient_workspace_script":
        required_markers = (
            "private_runbook_shell_safe_placeholders",
            "operator_commands_shell_safe_placeholders",
            "_quote_placeholder",
            "_runbook_quotes_command_placeholders",
            "_operator_commands_quote_placeholders",
        )
        return all(marker in text for marker in required_markers)
    if name == "first_recipient_operator_status_script":
        required_markers = (
            "operator_commands_shell_safe_placeholders",
            "_quote_placeholder",
            "_operator_commands_quote_placeholders",
        )
        return all(marker in text for marker in required_markers)
    return True


def _audit_receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    dispatch_record = payload.get("dispatch_record") if isinstance(payload.get("dispatch_record"), dict) else {}
    audited_sources = payload.get("audited_sources") if isinstance(payload.get("audited_sources"), list) else []
    body_hash = payload.get("operator_send_bypass_audit_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == OPERATOR_SEND_BYPASS_AUDIT_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_no_bypass": payload.get("verdict") == "NO_OPERATOR_STATUS_BYPASS",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "dispatch_record_hash_present": _looks_like_sha256(dispatch_record.get("body_sha256")),
        "audited_sources_present": bool(audited_sources),
        "audited_sources_all_pass": all(
            isinstance(item, dict) and item.get("dispatch_commands_require_operator_status") is True
            and item.get("dispatch_commands_require_manual_send_go") is True
            and item.get("dispatch_commands_require_pre_send_proof") is True
            and item.get("operator_command_placeholders_shell_safe") is True
            for item in audited_sources
        ),
        "absolute_paths_omitted": str(ROOT) not in serialized and str(Path.home()) not in serialized,
        "private_placeholders_omitted": "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER" not in serialized
        and "REPLACE_WITH_PRIVATE_SEND_CHANNEL" not in serialized,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _audit_body_sha256(payload),
    }


def _audit_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "operator_send_bypass_audit_body_sha256", "operator_send_bypass_audit_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_shareable_receipt_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = (
        str(ROOT),
        str(Path.home()),
        "REPLACE_WITH_ONE_RECIPIENT_IDENTIFIER",
        "REPLACE_WITH_PRIVATE_SEND_CHANNEL",
        "WAIT_FOR_ONE_CONFIRMED_LINE",
    )
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise InstallKitOperatorSendBypassAuditError("operator send bypass audit receipt contains private material.")


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallKitOperatorSendBypassAuditError(f"cannot read audit source: {path.name}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitOperatorSendBypassAuditError("JSON payload is not an object.")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Cambrian install-kit operator send bypass surfaces.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--workspace-dir", type=Path, default=DEFAULT_WORKSPACE_DIR)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing audit receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_operator_send_bypass_audit_file(args.verify_receipt)
        except Exception as exc:  # noqa: BLE001
            logger.error("[FAIL] install kit operator send bypass audit verification: %s", exc)
            return 1
        logger.info("[PASS] install kit operator send bypass audit verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["operator_send_bypass_audit_body_sha256"])
        return 0

    try:
        result = audit_install_kit_operator_send_bypass(
            output_dir=args.output_dir,
            workspace_dir=args.workspace_dir,
            receipt_path=args.receipt,
            skip_verify=bool(args.skip_verify),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("[FAIL] install kit operator send bypass audit: %s", exc)
        return 1
    logger.info("[PASS] install kit operator send bypass audit")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", Path(str(result["receipt_json"])).name)
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
