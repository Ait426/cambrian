"""Build and verify the external alpha send handoff artifacts."""

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

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, DISPATCH_EXECUTION_POLICY, RELEASE_SLUG, build_release
from scripts.verify_external_alpha_release import (
    SUPPORT_PACKET_NAME,
    verify_release,
    verify_shareable_receipt_file,
    write_shareable_receipt,
)


HANDOFF_SCHEMA_VERSION = "external_alpha_send_handoff_v0_1"
HANDOFF_MD_NAME = f"{RELEASE_SLUG}-handoff.md"
HANDOFF_JSON_NAME = f"{RELEASE_SLUG}-handoff.json"
RECEIPT_NAME = "external_alpha_release_verification_receipt.json"
REQUIRED_DO_NOT_SHARE = [
    ".env",
    "browser localStorage",
    "private source or project files",
    "raw AI reply",
    "API key or secret",
]

logger = logging.getLogger(__name__)


class HandoffError(Exception):
    """Raised when the external alpha handoff cannot be produced or verified."""


def prepare_handoff(output_dir: Path = DEFAULT_OUTPUT_DIR, skip_build: bool = False) -> dict[str, Any]:
    """Build or reuse the release ZIP, verify it, and write share-safe handoff artifacts."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if skip_build:
        zip_path = output_dir / f"{RELEASE_SLUG}.zip"
        manifest_path = output_dir / f"{RELEASE_SLUG}.manifest.json"
        if not zip_path.is_file() or not manifest_path.is_file():
            raise HandoffError("Existing ZIP and manifest are missing. Rerun without --skip-build.")
        build_result = {
            "zip_path": str(zip_path),
            "manifest_path": str(manifest_path),
        }
    else:
        build_result = build_release(output_dir)

    zip_path = Path(str(build_result["zip_path"]))
    manifest_path = Path(str(build_result["manifest_path"]))
    verification = verify_release(zip_path=zip_path, manifest_path=manifest_path)
    receipt_path = write_shareable_receipt(output_dir / RECEIPT_NAME, verification)
    receipt = verify_shareable_receipt_file(receipt_path)
    payload = _handoff_payload(zip_path.name, manifest_path.name, receipt_path.name, receipt, verification)

    json_path = output_dir / HANDOFF_JSON_NAME
    md_path = output_dir / HANDOFF_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_handoff_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)

    return {
        "status": payload["status"],
        "handoff_json": str(json_path),
        "handoff_md": str(md_path),
        "receipt_json": str(receipt_path),
        "receipt_body_sha256": payload["receipt"]["body_sha256"],
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
        "file_count": payload["release"]["file_count"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Build the external alpha send handoff Markdown and JSON.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Release output directory. Defaults to dist.")
    parser.add_argument("--skip-build", action="store_true", help="Reuse the existing ZIP and manifest.")
    parser.add_argument("--verify-handoff", default=None, help="Verify an existing handoff JSON file.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_handoff:
        try:
            payload = verify_handoff_file(Path(args.verify_handoff))
        except Exception as exc:  # noqa: BLE001 - CLI should report one concise verifier failure.
            logger.error("[FAIL] external alpha handoff verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha handoff verification")
        logger.info("status : %s", payload["status"])
        logger.info("handoff: %s", payload["handoff_body_sha256"])
        logger.info("receipt: %s", payload["receipt"]["body_sha256"])
        return 0

    try:
        result = prepare_handoff(Path(args.output_dir), skip_build=args.skip_build)
    except Exception as exc:  # noqa: BLE001 - Operational gate failures are reported as one line.
        logger.error("[FAIL] external alpha handoff: %s", exc)
        return 1

    logger.info("[PASS] external alpha handoff")
    logger.info("handoff_md  : %s", result["handoff_md"])
    logger.info("handoff_json: %s", result["handoff_json"])
    logger.info("receipt_json: %s", result["receipt_json"])
    logger.info("zip         : %s", result["zip_file"])
    logger.info("sha256      : %s", result["archive_sha256"])
    return 0


def _handoff_payload(
    zip_file: str,
    manifest_file: str,
    receipt_file: str,
    receipt: dict[str, Any],
    verification: dict[str, Any],
) -> dict[str, Any]:
    """Create a share-safe handoff payload without local paths or private values."""
    diagnostics_do_not_share = verification.get("diagnostics_do_not_share")
    if not isinstance(diagnostics_do_not_share, list):
        diagnostics_do_not_share = REQUIRED_DO_NOT_SHARE

    dispatch_policy = (
        verification.get("dispatch_execution_policy")
        if isinstance(verification.get("dispatch_execution_policy"), dict)
        else {}
    )

    payload = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_to_send",
        "safe_to_share": True,
        "release": {
            "version": verification.get("release_version"),
            "zip_file": zip_file,
            "manifest_file": manifest_file,
            "archive_sha256": verification.get("archive_sha256"),
            "file_count": verification.get("file_count"),
            "boundary_count": verification.get("boundary_count"),
            "trust_report": verification.get("trust_report"),
            "support_packet": SUPPORT_PACKET_NAME,
        },
        "receipt": {
            "file": receipt_file,
            "schema_version": receipt.get("schema_version"),
            "body_sha256": receipt.get("receipt_body_sha256"),
            "verified_standalone": True,
        },
        "dispatch_execution_policy": dispatch_policy,
        "verified": {
            "zip_sha256": True,
            "manifest_file_hashes": True,
            "trust_report": True,
            "support_packet": True,
            "current_source_manifest": verification.get("release_sources_match_current_manifest") is True,
            "receipt_body_hash": True,
            "receipt_standalone": True,
            "diagnostics_privacy": verification.get("diagnostics_safe_to_share") is True,
            "batch_rehearsal": _batch_status(verification) in {"pass", "skipped"},
        },
        "send_to_recipient": [
            zip_file,
            "ZIP sha256",
            "QUICKSTART_EXTERNAL_ALPHA.md",
            "copy_paste_message",
            "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
        ],
        "recipient_steps": [
            "Unzip the ZIP file.",
            "Read QUICKSTART_EXTERNAL_ALPHA.md first.",
            "Use START_HERE_EXTERNAL_ALPHA.md only if you need the detailed manual.",
            "If delegating to Claude/Codex, paste RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md exactly.",
            "Run START_CAMBRIAN_AGENT_PLATFORM.bat.",
            "If anything fails, read EXTERNAL_ALPHA_SUPPORT_PACKET.md.",
            "For support, send only external_alpha_release_verification_receipt.json and external_alpha_diagnostics.json.",
        ],
        "support_files": [
            "external_alpha_release_verification_receipt.json",
            "external_alpha_diagnostics.json",
        ],
        "do_not_share": diagnostics_do_not_share,
        "commands": {
            "release_build": "python scripts/build_external_alpha_release.py",
            "release_verify": "python scripts/verify_external_alpha_release.py",
            "handoff_prepare": "python scripts/prepare_external_alpha_handoff.py",
            "handoff_verify": "python scripts/prepare_external_alpha_handoff.py --verify-handoff cambrian-agent-platform-external-alpha-handoff.json",
            "receipt": "python scripts/verify_external_alpha_release.py --receipt external_alpha_release_verification_receipt.json",
            "receipt_verify": "python scripts/verify_external_alpha_release.py --verify-receipt external_alpha_release_verification_receipt.json",
            "diagnostics": "python scripts/collect_external_alpha_diagnostics.py --output external_alpha_diagnostics.json",
        },
        "pilot_templates": [
            "docs/launch/PILOT_ISSUE_INTAKE.md",
            "docs/launch/PILOT_FEEDBACK_FORM.md",
        ],
        "copy_paste_message": _copy_paste_message(zip_file, verification),
    }
    payload["handoff_body_sha256"] = _handoff_body_sha256(payload)
    payload["handoff_checks"] = _handoff_checks(payload)
    verify_handoff_payload(payload)
    return payload


def verify_handoff_file(path: Path) -> dict[str, Any]:
    """Verify an existing handoff JSON file."""
    payload = _read_json(path)
    verify_handoff_payload(payload)
    return payload


def verify_handoff_payload(payload: dict[str, Any]) -> None:
    """Verify that a handoff JSON payload is untampered and share-safe."""
    if payload.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        raise HandoffError("handoff schema_version is invalid.")
    if payload.get("status") != "ready_to_send":
        raise HandoffError(f"handoff status is not ready_to_send: {payload.get('status')}")
    if payload.get("safe_to_share") is not True:
        raise HandoffError("handoff safe_to_share is not true.")
    checks = payload.get("handoff_checks") if isinstance(payload.get("handoff_checks"), dict) else {}
    if not checks:
        raise HandoffError("handoff_checks is missing.")
    failed_checks = [name for name, passed in checks.items() if passed is not True]
    if failed_checks:
        raise HandoffError("handoff safety check failed: " + ", ".join(failed_checks))
    verified = payload.get("verified") if isinstance(payload.get("verified"), dict) else {}
    if not verified or any(value is not True for value in verified.values()):
        raise HandoffError("handoff verified entries are not all true.")
    if payload.get("handoff_body_sha256") != _handoff_body_sha256(payload):
        raise HandoffError("handoff body hash does not match.")
    recalculated_checks = _handoff_checks(payload)
    if checks != recalculated_checks:
        raise HandoffError("handoff safety check results do not match the current body.")


def _handoff_body_sha256(payload: dict[str, Any]) -> str:
    """Hash the stable handoff body."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"handoff_body_sha256", "handoff_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _handoff_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """Verify the handoff contains only share-safe send evidence."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    dispatch_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    support_files = payload.get("support_files") if isinstance(payload.get("support_files"), list) else []
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    copy_paste_message = str(payload.get("copy_paste_message") or "")
    commands = payload.get("commands") if isinstance(payload.get("commands"), dict) else {}
    verified = payload.get("verified") if isinstance(payload.get("verified"), dict) else {}
    body_hash = payload.get("handoff_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == HANDOFF_SCHEMA_VERSION,
        "ready_to_send": payload.get("status") == "ready_to_send",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": isinstance(release.get("zip_file"), str) and release.get("zip_file", "").endswith(".zip"),
        "archive_hash_present": isinstance(release.get("archive_sha256"), str)
        and len(release.get("archive_sha256", "")) == 64,
        "receipt_file_present": receipt.get("file") == RECEIPT_NAME,
        "receipt_body_hash_present": isinstance(receipt.get("body_sha256"), str)
        and len(receipt.get("body_sha256", "")) == 64,
        "support_files_present": RECEIPT_NAME in support_files and "external_alpha_diagnostics.json" in support_files,
        "dispatch_execution_policy_matched": dispatch_policy == DISPATCH_EXECUTION_POLICY,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "do_not_share_guidance_present": ".env" in do_not_share and "raw AI reply" in do_not_share,
        "recipient_ack_request_present": "CONFIRMED" in copy_paste_message and "reply only" in copy_paste_message,
        "copy_paste_message_mentions_quickstart": "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message,
        "copy_paste_message_mentions_agent_prompt": "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md"
        in copy_paste_message,
        "recipient_steps_mentions_quickstart": any(
            "QUICKSTART_EXTERNAL_ALPHA.md" in str(step) for step in payload.get("recipient_steps", [])
        ),
        "recipient_steps_mentions_agent_prompt": any(
            "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in str(step)
            for step in payload.get("recipient_steps", [])
        ),
        "verify_handoff_command_present": "verify-handoff" in str(commands.get("handoff_verify", "")),
        "verified_all_true": bool(verified) and all(value is True for value in verified.values()),
        "handoff_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "handoff_body_hash_matched": body_hash == _handoff_body_sha256(payload),
    }


def _copy_paste_message(zip_file: str, verification: dict[str, Any]) -> str:
    """Build the exact message the operator can send to one external alpha recipient."""
    return "\n".join(
        [
            "Cambrian Agent Platform External Alpha",
            "",
            f"Attachment: {zip_file}",
            f"sha256: {verification.get('archive_sha256')}",
            "",
            "Please unzip it, read QUICKSTART_EXTERNAL_ALPHA.md first, then run START_CAMBRIAN_AGENT_PLATFORM.bat.",
            "If you hand this to Claude/Codex, paste RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md exactly.",
            "After you confirm QUICKSTART and the run path, reply only: CONFIRMED.",
            "This alpha does not require a public marketplace, payment, cloud execution, or provider API key.",
            "If anything fails, read EXTERNAL_ALPHA_SUPPORT_PACKET.md and send only the receipt and diagnostics JSON.",
            "Do not send .env, browser localStorage, raw private project files, raw AI reply text, API keys/secrets, or raw screenshots.",
        ]
    )


def _handoff_markdown(payload: dict[str, Any]) -> str:
    """Render the share-safe handoff as Markdown."""
    release = payload["release"]
    receipt = payload["receipt"]
    dispatch_policy = payload["dispatch_execution_policy"]
    recipient_steps = "\n".join(f"{index}. {step}" for index, step in enumerate(payload["recipient_steps"], start=1))
    support_files = "\n".join(f"- {item}" for item in payload["support_files"])
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    templates = "\n".join(f"- {item}" for item in payload["pilot_templates"])
    return f"""# Cambrian External Alpha Send Handoff

## Status

- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- release version: {release["version"]}
- zip file: {release["zip_file"]}
- manifest file: {release["manifest_file"]}
- archive sha256: {release["archive_sha256"]}
- file count: {release["file_count"]}
- boundary count: {release["boundary_count"]}
- trust report: {release["trust_report"]}
- support packet: {release["support_packet"]}
- receipt file: {receipt["file"]}
- receipt body sha256: {receipt["body_sha256"]}
- receipt verified standalone: {receipt["verified_standalone"]}
- handoff body sha256: {payload["handoff_body_sha256"]}

## Copy Paste Message

```text
{payload["copy_paste_message"]}
```

## Recipient Steps

{recipient_steps}

## Support Files

{support_files}

## Dispatch Execution Policy

- script sends to recipient: {dispatch_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {dispatch_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {dispatch_policy["manual_operator_dispatch_required"]}
- max recipients per record: {dispatch_policy["max_recipients_per_record"]}
- records private sha256 only: {dispatch_policy["records_private_sha256_only"]}
- raw private content included: {dispatch_policy["raw_private_content_included"]}
- cohort scaling allowed: {dispatch_policy["cohort_scaling_allowed"]}
- sent recorded by private hashes only: {dispatch_policy["sent_recorded_by_private_hashes_only"]}

## Do Not Share

{do_not_share}

## Pilot Templates

{templates}

## Operator Commands

```bash
{payload["commands"]["release_build"]}
{payload["commands"]["release_verify"]}
{payload["commands"]["handoff_prepare"]}
{payload["commands"]["handoff_verify"]}
{payload["commands"]["receipt_verify"]}
```
"""


def _batch_status(verification: dict[str, Any]) -> str:
    """Read the batch rehearsal status from release verification."""
    batch = verification.get("batch_rehearsal")
    if isinstance(batch, dict) and isinstance(batch.get("status"), str):
        return str(batch["status"])
    return "unknown"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    """Read a UTF-8 JSON object."""
    if not path.is_file():
        raise HandoffError(f"handoff JSON file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HandoffError(f"handoff JSON parse failed: {exc}") from exc
    if not isinstance(payload, dict):
        raise HandoffError("handoff JSON must be an object.")
    return payload


def _assert_shareable_file(path: Path) -> None:
    """Reject generated handoff files that leak local paths or test secrets."""
    text = path.read_text(encoding="utf-8")
    forbidden_fragments = [str(ROOT), str(Path.home()), "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"]
    found = [fragment for fragment in forbidden_fragments if fragment and fragment in text]
    if found:
        raise HandoffError(f"Generated handoff file contains private local data: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
