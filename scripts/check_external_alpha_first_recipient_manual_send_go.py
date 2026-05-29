"""Aggregate the final private GO/NO-GO before manually sending to one recipient."""

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

from scripts.audit_external_alpha_operator_send_bypass import (  # noqa: E402
    OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
    verify_operator_send_bypass_audit_file,
)
from scripts.audit_external_alpha_send_chain import audit_send_chain  # noqa: E402
from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_first_recipient_send_preflight import (  # noqa: E402
    PREFLIGHT_RECEIPT_NAME,
    verify_first_recipient_send_preflight_receipt_file,
)
from scripts.prepare_external_alpha_operator_dispatch_packet import (  # noqa: E402
    PACKET_JSON_NAME,
    verify_operator_dispatch_packet_file,
)
from scripts.prepare_external_alpha_private_pilot_workspace import DEFAULT_PRIVATE_WORKSPACE_DIR  # noqa: E402


MANUAL_SEND_GO_SCHEMA_VERSION = "external_alpha_first_recipient_manual_send_go_v0_1"
MANUAL_SEND_GO_RECEIPT_NAME = "external-alpha-first-recipient-manual-send-go-receipt.json"
DEFAULT_MANUAL_SEND_GO_WORKSPACE_DIR = DEFAULT_PRIVATE_WORKSPACE_DIR
DEFAULT_OPERATOR_PACKET_PATH = DEFAULT_OUTPUT_DIR / PACKET_JSON_NAME
DEFAULT_OPERATOR_BYPASS_RECEIPT_PATH = DEFAULT_OUTPUT_DIR / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME

logger = logging.getLogger(__name__)


class FirstRecipientManualSendGoError(RuntimeError):
    """First-recipient manual send GO/NO-GO check failed."""


def check_first_recipient_manual_send_go(
    workspace_dir: Path = DEFAULT_MANUAL_SEND_GO_WORKSPACE_DIR,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    operator_packet_path: Path = DEFAULT_OPERATOR_PACKET_PATH,
    preflight_receipt_path: Path | None = None,
    operator_bypass_receipt_path: Path | None = None,
    receipt_path: Path | None = None,
    require_manual_send_go_rehearsal: bool = True,
) -> dict[str, Any]:
    """Return GO only when all pre-send gates are ready and no send is recorded."""
    workspace_dir = workspace_dir.resolve()
    output_dir = output_dir.resolve()
    operator_packet_path = operator_packet_path.resolve()
    preflight_receipt_path = (preflight_receipt_path or workspace_dir / PREFLIGHT_RECEIPT_NAME).resolve()
    operator_bypass_receipt_path = (
        operator_bypass_receipt_path or output_dir / OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME
    ).resolve()

    preflight = _load_preflight(preflight_receipt_path)
    operator_packet = _load_operator_packet(operator_packet_path)
    operator_bypass = _load_operator_bypass(operator_bypass_receipt_path)
    final_audit = _load_final_audit(
        output_dir,
        require_manual_send_go_rehearsal=require_manual_send_go_rehearsal,
    )

    payload = _manual_send_go_payload(
        operator_packet_path=operator_packet_path,
        operator_packet=operator_packet,
        preflight=preflight,
        operator_bypass=operator_bypass,
        final_audit=final_audit,
    )

    receipt_path = (receipt_path or workspace_dir / MANUAL_SEND_GO_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_first_recipient_manual_send_go_receipt_file(receipt_path, require_go=False)
    _assert_shareable_receipt_file(receipt_path, workspace_dir)

    failed = [name for name, passed in payload["checks"].items() if passed is not True]
    if failed:
        raise FirstRecipientManualSendGoError("first-recipient manual send blocked checks: " + ", ".join(failed))

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["manual_send_go_receipt_body_sha256"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }


def verify_first_recipient_manual_send_go_receipt_file(
    path: Path,
    *,
    require_go: bool = True,
) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_manual_send_go_receipt_payload(payload, require_go=require_go)
    return payload


def verify_first_recipient_manual_send_go_receipt_payload(
    payload: dict[str, Any],
    *,
    require_go: bool = True,
) -> None:
    if payload.get("schema_version") != MANUAL_SEND_GO_SCHEMA_VERSION:
        raise FirstRecipientManualSendGoError("manual send GO receipt schema_version mismatch.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise FirstRecipientManualSendGoError("manual send GO receipt checks are missing.")
    go = all(value is True for value in checks.values())
    expected_status = "pass" if go else "fail"
    expected_verdict = "GO_TO_MANUALLY_SEND_ONE" if go else "BLOCKED_BEFORE_MANUAL_SEND"
    if payload.get("status") != expected_status:
        raise FirstRecipientManualSendGoError("manual send GO receipt status does not match checks.")
    if payload.get("verdict") != expected_verdict:
        raise FirstRecipientManualSendGoError("manual send GO receipt verdict does not match checks.")
    if payload.get("safe_to_share") is not True:
        raise FirstRecipientManualSendGoError("manual send GO receipt must be safe_to_share.")
    receipt_checks = payload.get("manual_send_go_receipt_checks")
    recalculated = _receipt_checks(payload)
    if receipt_checks != recalculated:
        raise FirstRecipientManualSendGoError("manual send GO receipt checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise FirstRecipientManualSendGoError(
            "manual send GO receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("manual_send_go_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise FirstRecipientManualSendGoError("manual send GO receipt body hash mismatch.")
    if require_go and not go:
        failed = [name for name, passed in checks.items() if passed is not True]
        raise FirstRecipientManualSendGoError("manual send GO receipt is blocked: " + ", ".join(failed))


def _manual_send_go_payload(
    *,
    operator_packet_path: Path,
    operator_packet: dict[str, Any] | None,
    preflight: dict[str, Any] | None,
    operator_bypass: dict[str, Any] | None,
    final_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    operator_release = _dict(operator_packet, "release")
    operator_packet_body_sha256 = (
        operator_packet.get("operator_dispatch_packet_body_sha256") if isinstance(operator_packet, dict) else None
    )
    preflight_operator_packet = _dict(preflight, "operator_packet")
    preflight_release = _dict(preflight, "release")
    bypass_release = _dict(operator_bypass, "release")
    final_archive = final_audit.get("archive_sha256") if isinstance(final_audit, dict) else None
    archive_sha256 = (
        operator_release.get("archive_sha256")
        or preflight_release.get("archive_sha256")
        or bypass_release.get("archive_sha256")
        or final_archive
    )
    preflight_private = _dict(preflight, "private_workspace")
    preflight_files = preflight_private.get("required_private_files")
    if not isinstance(preflight_files, list):
        preflight_files = []
    final_checks = final_audit.get("checks") if isinstance(final_audit, dict) else {}
    checks = {
        "operator_packet_file_expected": operator_packet_path.name == PACKET_JSON_NAME,
        "operator_packet_ready_to_send_one": operator_packet is not None
        and operator_packet.get("status") == "pass"
        and operator_packet.get("verdict") == "READY_TO_SEND_ONE",
        "operator_packet_body_hash_present": _looks_like_sha256(operator_packet_body_sha256),
        "preflight_operator_packet_file_expected": preflight_operator_packet.get("file") == PACKET_JSON_NAME,
        "preflight_operator_packet_body_matches_current_packet": _looks_like_sha256(operator_packet_body_sha256)
        and preflight_operator_packet.get("body_sha256") == operator_packet_body_sha256,
        "preflight_receipt_ready": preflight is not None
        and preflight.get("status") == "pass"
        and preflight.get("verdict") == "FIRST_RECIPIENT_PRE_SEND_READY",
        "preflight_private_files_ready": bool(preflight_files)
        and all(isinstance(item, dict) and item.get("status") == "ready" for item in preflight_files),
        "preflight_records_no_send": preflight_private.get("send_recorded") is False,
        "operator_bypass_audit_ready": operator_bypass is not None
        and operator_bypass.get("status") == "pass"
        and operator_bypass.get("verdict") == "NO_OPERATOR_PREFLIGHT_BYPASS",
        "final_send_chain_ready": final_audit is not None
        and final_audit.get("status") == "pass"
        and final_audit.get("verdict") == "READY_TO_SEND_ONE",
        "final_send_chain_requires_bypass": final_audit is not None
        and final_audit.get("operator_send_bypass_audit_required") is True,
        "final_send_chain_bypass_hash_matches": final_audit is not None
        and operator_bypass is not None
        and final_audit.get("operator_send_bypass_audit_body_sha256")
        == operator_bypass.get("operator_send_bypass_audit_body_sha256"),
        "release_hashes_match": _release_hashes_match(operator_packet, preflight, operator_bypass, final_audit),
        "one_recipient_policy_locked": _dict(preflight, "policy").get("max_recipients") == 1,
        "manual_dispatch_only": _dict(preflight, "policy").get("script_sends_to_recipient") is False
        and _dict(preflight, "policy").get("manual_operator_dispatch_required") is True,
        "final_checks_all_true": isinstance(final_checks, dict)
        and bool(final_checks)
        and all(value is True for value in final_checks.values()),
        "script_does_not_send_to_recipient": True,
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
    }
    go = all(checks.values())
    private_file_summaries = [
        {
            "file": item.get("file"),
            "status": item.get("status"),
            "sha256": item.get("sha256"),
        }
        for item in preflight_files
        if isinstance(item, dict)
    ]
    payload: dict[str, Any] = {
        "schema_version": MANUAL_SEND_GO_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if go else "fail",
        "verdict": "GO_TO_MANUALLY_SEND_ONE" if go else "BLOCKED_BEFORE_MANUAL_SEND",
        "safe_to_share": True,
        "release": {
            "zip_file": RELEASE_SLUG + ".zip",
            "archive_sha256": archive_sha256,
            "file_count": preflight_release.get("file_count") or bypass_release.get("file_count"),
        },
        "operator_packet": {
            "file": operator_packet_path.name,
            "body_sha256": operator_packet_body_sha256,
            "preflight_body_sha256": preflight_operator_packet.get("body_sha256"),
        },
        "gate_receipts": {
            "preflight": {
                "file": PREFLIGHT_RECEIPT_NAME,
                "verdict": preflight.get("verdict") if isinstance(preflight, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(preflight, "first_recipient_send_preflight_receipt_body_sha256"),
                "private_file_summaries": private_file_summaries,
            },
            "operator_send_bypass_audit": {
                "file": OPERATOR_SEND_BYPASS_AUDIT_JSON_NAME,
                "verdict": operator_bypass.get("verdict") if isinstance(operator_bypass, dict) else "missing_or_invalid",
                "body_sha256": _body_hash(operator_bypass, "operator_send_bypass_audit_body_sha256"),
            },
            "final_send_chain_audit": {
                "verdict": final_audit.get("verdict") if isinstance(final_audit, dict) else "missing_or_invalid",
                "release_receipt_body_sha256": final_audit.get("receipt_body_sha256")
                if isinstance(final_audit, dict)
                else None,
                "bundle_smoke_receipt_body_sha256": final_audit.get("bundle_smoke_receipt_body_sha256")
                if isinstance(final_audit, dict)
                else None,
                "operator_bypass_audit_required": final_audit.get("operator_send_bypass_audit_required")
                if isinstance(final_audit, dict)
                else None,
            },
        },
        "policy": {
            "script_sends_to_recipient": False,
            "manual_operator_dispatch_required": True,
            "max_recipients": 1,
            "pre_send_go_no_go_only": True,
            "records_private_sha256_only": True,
            "raw_private_values_in_receipt": False,
            "local_paths_in_receipt": False,
        },
        "operator_next_action": (
            "Manually send the ZIP and copy-paste message to exactly one recipient."
            if go
            else "Do not send. Complete the blocked pre-send gates, then rerun this GO check."
        ),
        "checks": checks,
    }
    payload["manual_send_go_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["manual_send_go_receipt_checks"] = _receipt_checks(payload)
    return payload


def _load_preflight(path: Path) -> dict[str, Any] | None:
    try:
        return verify_first_recipient_send_preflight_receipt_file(path, require_ready=True)
    except Exception:
        return _load_blocked_json(path)


def _load_operator_packet(path: Path) -> dict[str, Any] | None:
    try:
        return verify_operator_dispatch_packet_file(path)
    except Exception:
        return None


def _load_operator_bypass(path: Path) -> dict[str, Any] | None:
    try:
        return verify_operator_send_bypass_audit_file(path)
    except Exception:
        return None


def _load_final_audit(
    output_dir: Path,
    *,
    require_manual_send_go_rehearsal: bool = True,
) -> dict[str, Any] | None:
    try:
        return audit_send_chain(
            output_dir,
            require_manual_send_go_rehearsal=require_manual_send_go_rehearsal,
        )
    except Exception:
        return None


def _load_blocked_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _release_hashes_match(
    operator_packet: dict[str, Any] | None,
    preflight: dict[str, Any] | None,
    operator_bypass: dict[str, Any] | None,
    final_audit: dict[str, Any] | None,
) -> bool:
    hashes = [
        _dict(operator_packet, "release").get("archive_sha256"),
        _dict(preflight, "release").get("archive_sha256"),
        _dict(operator_bypass, "release").get("archive_sha256"),
        final_audit.get("archive_sha256") if isinstance(final_audit, dict) else None,
    ]
    hashes = [value for value in hashes if isinstance(value, str)]
    return bool(hashes) and len(set(hashes)) == 1 and _looks_like_sha256(hashes[0])


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    release = _dict(payload, "release")
    gate_receipts = _dict(payload, "gate_receipts")
    preflight = _dict(gate_receipts, "preflight")
    bypass = _dict(gate_receipts, "operator_send_bypass_audit")
    final_audit = _dict(gate_receipts, "final_send_chain_audit")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    body_hash = payload.get("manual_send_go_receipt_body_sha256")
    go = bool(checks) and all(value is True for value in checks.values())
    return {
        "schema_version_present": payload.get("schema_version") == MANUAL_SEND_GO_SCHEMA_VERSION,
        "status_matches_checks": (payload.get("status") == "pass") is go,
        "verdict_matches_checks": payload.get("verdict")
        == ("GO_TO_MANUALLY_SEND_ONE" if go else "BLOCKED_BEFORE_MANUAL_SEND"),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "preflight_receipt_body_hash_present_or_blocked": preflight.get("verdict")
        != "FIRST_RECIPIENT_PRE_SEND_READY"
        or _looks_like_sha256(preflight.get("body_sha256")),
        "operator_bypass_body_hash_present": _looks_like_sha256(bypass.get("body_sha256")),
        "final_audit_receipt_body_hash_present": _looks_like_sha256(final_audit.get("release_receipt_body_sha256")),
        "raw_private_values_omitted": _dict(payload, "policy").get("raw_private_values_in_receipt") is False,
        "local_paths_omitted": _dict(payload, "policy").get("local_paths_in_receipt") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "manual_dispatch_only": _dict(payload, "policy").get("script_sends_to_recipient") is False
        and _dict(payload, "policy").get("manual_operator_dispatch_required") is True,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _body_hash(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _assert_shareable_receipt_file(path: Path, workspace_dir: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = [
        str(ROOT),
        str(Path.home()),
        str(workspace_dir),
        "Recipient identifier/contact goes here",
        "Record the private channel",
        "<private-send-channel>",
        "alpha recipient private contact",
        "private send channel",
    ]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise FirstRecipientManualSendGoError("manual send GO receipt leaked local path or raw private text.")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "manual_send_go_receipt_body_sha256", "manual_send_go_receipt_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise FirstRecipientManualSendGoError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise FirstRecipientManualSendGoError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FirstRecipientManualSendGoError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate GO/NO-GO before one manual external alpha send.")
    parser.add_argument("--workspace-dir", default=str(DEFAULT_MANUAL_SEND_GO_WORKSPACE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--operator-packet", default=str(DEFAULT_OPERATOR_PACKET_PATH))
    parser.add_argument("--preflight-receipt", default=None)
    parser.add_argument(
        "--operator-bypass-receipt",
        default=None,
        help="Optional operator bypass receipt path. Defaults to <output-dir>/operator-send-bypass-audit JSON.",
    )
    parser.add_argument("--receipt", default=None, help="Optional share-safe GO/NO-GO receipt JSON path.")
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing GO receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_manual_send_go_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
            logger.error("[FAIL] external alpha first-recipient manual send GO receipt verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha first-recipient manual send GO receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["manual_send_go_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_manual_send_go(
            Path(args.workspace_dir),
            output_dir=Path(args.output_dir),
            operator_packet_path=Path(args.operator_packet),
            preflight_receipt_path=Path(args.preflight_receipt) if args.preflight_receipt else None,
            operator_bypass_receipt_path=Path(args.operator_bypass_receipt) if args.operator_bypass_receipt else None,
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
        logger.error("[FAIL] external alpha first-recipient manual send GO: %s", exc)
        return 1

    logger.info("[PASS] external alpha first-recipient manual send GO")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
