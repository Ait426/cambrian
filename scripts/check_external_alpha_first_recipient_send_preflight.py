"""Preflight the one-recipient external alpha send before the operator sends anything."""

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
from scripts.prepare_external_alpha_operator_dispatch_packet import (  # noqa: E402
    PACKET_JSON_NAME,
    verify_operator_dispatch_packet_file,
)
from scripts.prepare_external_alpha_private_pilot_workspace import (  # noqa: E402
    DEFAULT_PRIVATE_WORKSPACE_DIR,
    PRIVATE_FILE_SPECS,
)


PREFLIGHT_SCHEMA_VERSION = "external_alpha_first_recipient_send_preflight_v0_1"
PREFLIGHT_RECEIPT_NAME = "external-alpha-first-recipient-send-preflight-receipt.json"
DEFAULT_OPERATOR_PACKET_PATH = DEFAULT_OUTPUT_DIR / PACKET_JSON_NAME
DEFAULT_PREFLIGHT_WORKSPACE_DIR = DEFAULT_PRIVATE_WORKSPACE_DIR
POST_SEND_REHEARSAL_PREFLIGHT_CONTRACT_SCHEMA_VERSION = "external_alpha_post_send_rehearsal_preflight_contract_v0_1"
REQUIRED_BEFORE_SEND_FILES = {
    "recipient-private.txt",
    "operator-dispatch-note-private.md",
}
PLACEHOLDER_FRAGMENTS = {
    "recipient-private.txt": ("Recipient identifier/contact goes here",),
    "operator-dispatch-note-private.md": ("Record the private channel", "<private-send-channel>"),
}
CHANNEL_MARKERS = (
    "channel",
    "dm",
    "direct message",
    "email",
    "mail",
    "slack",
    "discord",
    "kakao",
    "telegram",
    "sms",
    "message",
    "채널",
    "메시지",
    "이메일",
    "메일",
)

logger = logging.getLogger(__name__)


class FirstRecipientSendPreflightError(RuntimeError):
    """First-recipient send preflight failed."""


def check_first_recipient_send_preflight(
    workspace_dir: Path = DEFAULT_PREFLIGHT_WORKSPACE_DIR,
    *,
    operator_packet_path: Path = DEFAULT_OPERATOR_PACKET_PATH,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Check that the operator has replaced required private placeholders before sending."""
    workspace_dir = workspace_dir.resolve()
    operator_packet_path = operator_packet_path.resolve()
    operator_packet = _load_operator_packet(operator_packet_path)
    return _check_first_recipient_send_preflight_with_loaded_operator_packet(
        workspace_dir,
        operator_packet=operator_packet,
        operator_packet_path=operator_packet_path,
        receipt_path=receipt_path,
    )


def _check_first_recipient_send_preflight_with_loaded_operator_packet(
    workspace_dir: Path,
    *,
    operator_packet: dict[str, Any],
    operator_packet_path: Path,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Run the real preflight gate with an already validated send contract."""
    workspace_dir = workspace_dir.resolve()
    operator_packet_path = operator_packet_path.resolve()
    zip_path = _release_zip_path(operator_packet_path, operator_packet)
    release = operator_packet.get("release") if isinstance(operator_packet.get("release"), dict) else {}

    private_files = _required_private_file_statuses(workspace_dir, release_archive_sha256=release.get("archive_sha256"))
    payload = _preflight_payload(
        workspace_dir=workspace_dir,
        operator_packet=operator_packet,
        operator_packet_path=operator_packet_path,
        zip_path=zip_path,
        private_files=private_files,
    )

    receipt_path = (receipt_path or workspace_dir / PREFLIGHT_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_first_recipient_send_preflight_receipt_file(receipt_path, require_ready=False)
    _assert_shareable_receipt_file(receipt_path, workspace_dir, private_files, operator_packet)

    failed = [name for name, passed in payload["checks"].items() if passed is not True]
    if failed:
        raise FirstRecipientSendPreflightError(
            "first-recipient pre-send preflight blocked checks: " + ", ".join(failed)
        )

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["first_recipient_send_preflight_receipt_body_sha256"],
        "archive_sha256": payload["release"]["archive_sha256"],
        "recipient_private_sha256": _private_hash(private_files, "recipient-private.txt"),
        "operator_dispatch_note_private_sha256": _private_hash(
            private_files,
            "operator-dispatch-note-private.md",
        ),
    }


def verify_first_recipient_send_preflight_receipt_file(
    path: Path,
    *,
    require_ready: bool = True,
) -> dict[str, Any]:
    payload = _read_json(path)
    verify_first_recipient_send_preflight_receipt_payload(payload, require_ready=require_ready)
    return payload


def verify_first_recipient_send_preflight_receipt_payload(
    payload: dict[str, Any],
    *,
    require_ready: bool = True,
) -> None:
    if payload.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise FirstRecipientSendPreflightError("first-recipient send preflight schema_version mismatch.")
    if payload.get("status") not in {"pass", "fail"}:
        raise FirstRecipientSendPreflightError("first-recipient send preflight status is invalid.")
    if payload.get("verdict") not in {"FIRST_RECIPIENT_PRE_SEND_READY", "BLOCKED_UNTIL_PRIVATE_FIELDS_FILLED"}:
        raise FirstRecipientSendPreflightError("first-recipient send preflight verdict is invalid.")
    if payload.get("safe_to_share") is not True:
        raise FirstRecipientSendPreflightError("first-recipient send preflight receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise FirstRecipientSendPreflightError("first-recipient send preflight checks are missing.")
    expected_ready = all(value is True for value in checks.values())
    if (payload.get("status") == "pass") is not expected_ready:
        raise FirstRecipientSendPreflightError("first-recipient send preflight status does not match checks.")
    expected_verdict = "FIRST_RECIPIENT_PRE_SEND_READY" if expected_ready else "BLOCKED_UNTIL_PRIVATE_FIELDS_FILLED"
    if payload.get("verdict") != expected_verdict:
        raise FirstRecipientSendPreflightError("first-recipient send preflight verdict does not match checks.")
    receipt_checks = payload.get("first_recipient_send_preflight_receipt_checks")
    recalculated = _preflight_receipt_checks(payload)
    if receipt_checks != recalculated:
        raise FirstRecipientSendPreflightError("first-recipient send preflight receipt checks are stale.")
    failed_receipt_checks = [name for name, passed in recalculated.items() if passed is not True]
    if failed_receipt_checks:
        raise FirstRecipientSendPreflightError(
            "first-recipient send preflight receipt self-check failed: " + ", ".join(failed_receipt_checks)
        )
    if payload.get("first_recipient_send_preflight_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise FirstRecipientSendPreflightError("first-recipient send preflight body hash mismatch.")
    if require_ready and not expected_ready:
        failed = [name for name, passed in checks.items() if passed is not True]
        raise FirstRecipientSendPreflightError(
            "first-recipient send preflight is blocked: " + ", ".join(failed)
        )


def _preflight_payload(
    *,
    workspace_dir: Path,
    operator_packet: dict[str, Any],
    operator_packet_path: Path,
    zip_path: Path,
    private_files: list[dict[str, Any]],
) -> dict[str, Any]:
    release = operator_packet.get("release") if isinstance(operator_packet.get("release"), dict) else {}
    send_once = operator_packet.get("operator_send_once") if isinstance(operator_packet.get("operator_send_once"), dict) else {}
    packet_checks = (
        operator_packet.get("operator_dispatch_packet_checks")
        if isinstance(operator_packet.get("operator_dispatch_packet_checks"), dict)
        else {}
    )
    ready_file_map = {item["file"]: item for item in private_files}
    recipient = ready_file_map.get("recipient-private.txt", {})
    dispatch_note = ready_file_map.get("operator-dispatch-note-private.md", {})
    copy_paste_message = str(send_once.get("copy_paste_message") or "")
    release_hash = release.get("archive_sha256")
    operator_packet_schema = operator_packet.get("schema_version")
    operator_packet_file_expected = operator_packet_path.name == PACKET_JSON_NAME or (
        operator_packet_schema == POST_SEND_REHEARSAL_PREFLIGHT_CONTRACT_SCHEMA_VERSION
        and operator_packet_path.name == f"{RELEASE_SLUG}-post-send-rehearsal-preflight-contract.json"
    )
    checks = {
        "operator_packet_file_expected": operator_packet_file_expected,
        "operator_packet_ready_to_send_one": operator_packet.get("verdict") == "READY_TO_SEND_ONE",
        "operator_packet_self_checks_passed": bool(packet_checks)
        and all(value is True for value in packet_checks.values()),
        "manual_dispatch_only": send_once.get("script_sends_to_recipient") is False
        and send_once.get("manual_operator_dispatch_required") is True,
        "one_recipient_only": send_once.get("max_recipients") == 1,
        "release_zip_exists": zip_path.is_file(),
        "release_zip_hash_matched": zip_path.is_file() and _file_sha256(zip_path) == release.get("archive_sha256"),
        "copy_paste_message_hash_matched": send_once.get("copy_paste_message_sha256")
        == _text_sha256(copy_paste_message),
        "copy_paste_message_ascii_only": all(ord(char) < 128 for char in copy_paste_message),
        "copy_paste_message_ready": "CONFIRMED" in copy_paste_message
        and "reply only" in copy_paste_message
        and "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message
        and "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in copy_paste_message,
        "recipient_private_ready": recipient.get("status") == "ready",
        "operator_dispatch_note_private_ready": dispatch_note.get("status") == "ready",
        "recipient_private_minimum_signal": recipient.get("status") == "ready"
        and isinstance(recipient.get("byte_count"), int)
        and recipient.get("byte_count") >= 8,
        "recipient_private_exactly_one_contact": recipient.get("status") == "ready"
        and recipient.get("exactly_one_recipient") is True,
        "operator_dispatch_note_mentions_channel": dispatch_note.get("status") == "ready"
        and dispatch_note.get("mentions_channel") is True,
        "operator_dispatch_note_confirms_release_hash": dispatch_note.get("status") == "ready"
        and _looks_like_sha256(release_hash)
        and dispatch_note.get("contains_release_hash") is True,
        "recipient_private_sha256_present": _looks_like_sha256(recipient.get("sha256")),
        "operator_dispatch_note_private_sha256_present": _looks_like_sha256(dispatch_note.get("sha256")),
        "receipt_omits_raw_private_values": True,
        "receipt_omits_local_paths": True,
        "preflight_does_not_record_send": True,
        "script_does_not_send_to_recipient": True,
    }
    ready = all(checks.values())
    payload: dict[str, Any] = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if ready else "fail",
        "verdict": "FIRST_RECIPIENT_PRE_SEND_READY" if ready else "BLOCKED_UNTIL_PRIVATE_FIELDS_FILLED",
        "safe_to_share": True,
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "operator_packet": {
            "file": operator_packet_path.name,
            "schema_version": operator_packet.get("schema_version"),
            "body_sha256": operator_packet.get("operator_dispatch_packet_body_sha256"),
            "copy_paste_message_sha256": send_once.get("copy_paste_message_sha256"),
        },
        "private_workspace": {
            "required_private_files": private_files,
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
        "operator_next_action": (
            "Manually send the ZIP and copy-paste message to exactly one recipient."
            if ready
            else "Replace the required private workspace placeholders, then rerun this preflight before sending."
        ),
        "checks": checks,
    }
    payload["first_recipient_send_preflight_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["first_recipient_send_preflight_receipt_checks"] = _preflight_receipt_checks(payload)
    return payload


def _preflight_receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    operator_packet = payload.get("operator_packet") if isinstance(payload.get("operator_packet"), dict) else {}
    private_workspace = (
        payload.get("private_workspace") if isinstance(payload.get("private_workspace"), dict) else {}
    )
    private_files = (
        private_workspace.get("required_private_files")
        if isinstance(private_workspace.get("required_private_files"), list)
        else []
    )
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    body_hash = payload.get("first_recipient_send_preflight_receipt_body_sha256")
    ready = bool(checks) and all(value is True for value in checks.values())
    file_names = {item.get("file") for item in private_files if isinstance(item, dict)}
    return {
        "schema_version_present": payload.get("schema_version") == PREFLIGHT_SCHEMA_VERSION,
        "status_matches_checks": (payload.get("status") == "pass") is ready,
        "verdict_matches_checks": payload.get("verdict")
        == ("FIRST_RECIPIENT_PRE_SEND_READY" if ready else "BLOCKED_UNTIL_PRIVATE_FIELDS_FILLED"),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "release_archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "operator_packet_hash_present": _looks_like_sha256(operator_packet.get("body_sha256")),
        "copy_paste_message_hash_present": _looks_like_sha256(operator_packet.get("copy_paste_message_sha256")),
        "required_private_files_named": file_names == REQUIRED_BEFORE_SEND_FILES,
        "private_statuses_controlled": all(
            isinstance(item, dict)
            and item.get("status") in {"ready", "missing", "empty", "placeholder", "unreadable"}
            and isinstance(item.get("byte_count"), int)
            and isinstance(item.get("nonempty_line_count"), int)
            and isinstance(item.get("exactly_one_recipient"), bool)
            and isinstance(item.get("mentions_channel"), bool)
            and isinstance(item.get("contains_release_hash"), bool)
            for item in private_files
        ),
        "ready_private_files_have_hashes": all(
            item.get("status") != "ready" or _looks_like_sha256(item.get("sha256"))
            for item in private_files
            if isinstance(item, dict)
        ),
        "blocked_private_files_omit_hashes": all(
            item.get("status") == "ready" or item.get("sha256") is None
            for item in private_files
            if isinstance(item, dict)
        ),
        "raw_private_values_omitted": private_workspace.get("raw_private_values_included") is False,
        "local_paths_omitted": private_workspace.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "send_not_recorded": private_workspace.get("send_recorded") is False,
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _required_private_file_statuses(workspace_dir: Path, *, release_archive_sha256: Any) -> list[dict[str, Any]]:
    specs = [spec for spec in PRIVATE_FILE_SPECS if spec["file"] in REQUIRED_BEFORE_SEND_FILES]
    return [_private_file_status(workspace_dir, spec, release_archive_sha256=release_archive_sha256) for spec in specs]


def _private_file_status(workspace_dir: Path, spec: dict[str, str], *, release_archive_sha256: Any) -> dict[str, Any]:
    filename = spec["file"]
    path = workspace_dir / filename
    result: dict[str, Any] = {
        "file": filename,
        "purpose": spec["purpose"],
        "status": "missing",
        "sha256": None,
        "byte_count": 0,
        "nonempty_line_count": 0,
        "exactly_one_recipient": False,
        "mentions_channel": False,
        "contains_release_hash": False,
    }
    if not path.is_file():
        return result
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except OSError:
        result["status"] = "unreadable"
        return result
    except UnicodeDecodeError:
        result["status"] = "unreadable"
        return result
    result["byte_count"] = len(data)
    if not text.strip():
        result["status"] = "empty"
        return result
    if any(fragment in text for fragment in PLACEHOLDER_FRAGMENTS.get(filename, ())):
        result["status"] = "placeholder"
        return result
    result["nonempty_line_count"] = _nonempty_line_count(text)
    if filename == "recipient-private.txt":
        nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(nonempty_lines) == 1 and not _recipient_value_is_real(nonempty_lines[0]):
            result["status"] = "placeholder"
            return result
    result["status"] = "ready"
    result["sha256"] = hashlib.sha256(data).hexdigest()
    if filename == "recipient-private.txt":
        result["exactly_one_recipient"] = result["nonempty_line_count"] == 1
    if filename == "operator-dispatch-note-private.md":
        result["mentions_channel"] = _operator_note_mentions_private_channel(text)
        result["contains_release_hash"] = _looks_like_sha256(release_archive_sha256) and str(
            release_archive_sha256
        ) in text
    return result


def _operator_note_mentions_private_channel(text: str) -> bool:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if ":" in line:
            key, value = line.split(":", 1)
            key_lowered = key.lower()
            if any(marker in key_lowered for marker in CHANNEL_MARKERS):
                return _operator_note_channel_value_is_real(value)
        for marker in CHANNEL_MARKERS:
            if marker not in lowered:
                continue
            after_marker = lowered.split(marker, 1)[1]
            if _operator_note_channel_value_is_real(after_marker):
                return True
    return False


def _operator_note_channel_value_is_real(value: str) -> bool:
    stripped = value.strip(" \t:-")
    if not stripped:
        return False
    return (
        "Record the private channel" not in stripped
        and "<private-send-channel>" not in stripped
    )


def _recipient_value_is_real(value: str) -> bool:
    stripped = value.strip()
    lowered = stripped.lower()
    placeholder_markers = (
        "<",
        ">",
        "placeholder",
        "replace",
        "recipient goes here",
        "recipient identifier",
        "sample",
        "dummy",
        "todo",
        "tbd",
    )
    return bool(stripped) and not any(marker in lowered for marker in placeholder_markers)


def _nonempty_line_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _load_operator_packet(path: Path) -> dict[str, Any]:
    try:
        return verify_operator_dispatch_packet_file(path)
    except Exception as exc:  # noqa: BLE001 - wrap for operator-facing CLI output.
        raise FirstRecipientSendPreflightError(f"operator dispatch packet is not ready: {path.name}") from exc


def _release_zip_path(operator_packet_path: Path, operator_packet: dict[str, Any]) -> Path:
    release = operator_packet.get("release") if isinstance(operator_packet.get("release"), dict) else {}
    zip_file = release.get("zip_file")
    if not isinstance(zip_file, str) or not zip_file:
        raise FirstRecipientSendPreflightError("operator dispatch packet does not name a release ZIP.")
    return operator_packet_path.parent / zip_file


def _assert_shareable_receipt_file(
    path: Path,
    workspace_dir: Path,
    private_files: list[dict[str, Any]],
    operator_packet: dict[str, Any],
) -> None:
    text = path.read_text(encoding="utf-8")
    copy_paste_message = str(operator_packet.get("operator_send_once", {}).get("copy_paste_message") or "")
    raw_private_values = []
    for item in private_files:
        filename = item.get("file")
        if isinstance(filename, str):
            raw_private_values.append(_read_text_if_exists(workspace_dir / filename))
    forbidden = [
        str(ROOT),
        str(Path.home()),
        str(workspace_dir),
        copy_paste_message,
        "Recipient identifier/contact goes here",
        "Record the private channel",
        "<private-send-channel>",
        *[value for value in raw_private_values if value],
    ]
    found = [item for item in forbidden if item and item in text]
    if found:
        raise FirstRecipientSendPreflightError("first-recipient send preflight receipt leaked path or raw private text.")


def _read_text_if_exists(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""


def _private_hash(private_files: list[dict[str, Any]], filename: str) -> str | None:
    for item in private_files:
        if item.get("file") == filename:
            value = item.get("sha256")
            return value if isinstance(value, str) else None
    return None


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "generated_at",
            "first_recipient_send_preflight_receipt_body_sha256",
            "first_recipient_send_preflight_receipt_checks",
        }
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise FirstRecipientSendPreflightError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise FirstRecipientSendPreflightError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise FirstRecipientSendPreflightError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight one external alpha recipient send before manual dispatch.")
    parser.add_argument("--workspace-dir", default=str(DEFAULT_PREFLIGHT_WORKSPACE_DIR))
    parser.add_argument("--operator-packet", default=str(DEFAULT_OPERATOR_PACKET_PATH))
    parser.add_argument("--receipt", default=None, help="Optional share-safe preflight receipt JSON path.")
    parser.add_argument("--verify-receipt", default=None, help="Verify an existing ready preflight receipt JSON.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_first_recipient_send_preflight_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
            logger.error("[FAIL] external alpha first-recipient send preflight receipt verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha first-recipient send preflight receipt verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["first_recipient_send_preflight_receipt_body_sha256"])
        return 0

    try:
        result = check_first_recipient_send_preflight(
            Path(args.workspace_dir),
            operator_packet_path=Path(args.operator_packet),
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - report operator-facing reason.
        logger.error("[FAIL] external alpha first-recipient send preflight: %s", exc)
        return 1

    logger.info("[PASS] external alpha first-recipient send preflight")
    logger.info("verdict: %s", result["verdict"])
    logger.info("receipt: %s", result["receipt_json"])
    logger.info("sha256 : %s", result["archive_sha256"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
