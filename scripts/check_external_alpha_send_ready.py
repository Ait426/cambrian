"""Build and verify the external alpha send-ready GO/NO-GO receipt."""

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

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, DISPATCH_EXECUTION_POLICY, RELEASE_SLUG
from scripts.prepare_external_alpha_handoff import (
    HANDOFF_JSON_NAME,
    HANDOFF_MD_NAME,
    RECEIPT_NAME,
    prepare_handoff,
    verify_handoff_file,
)
from scripts.verify_external_alpha_release import verify_shareable_receipt_file


SEND_READY_SCHEMA_VERSION = "external_alpha_send_ready_v0_1"
SEND_READY_JSON_NAME = f"{RELEASE_SLUG}-send-ready.json"
SEND_READY_MD_NAME = f"{RELEASE_SLUG}-send-ready.md"
REQUIRED_DO_NOT_SHARE = {
    ".env",
    "browser localStorage",
    "private source or project files",
    "raw AI reply",
    "API key or secret",
}

logger = logging.getLogger(__name__)


class SendReadyError(Exception):
    """Raised when the external alpha send-ready gate cannot prove GO."""


def check_send_ready(output_dir: Path = DEFAULT_OUTPUT_DIR, skip_build: bool = False) -> dict[str, Any]:
    """Build the release handoff and write a share-safe send-ready receipt."""
    output_dir = output_dir.resolve()
    handoff_result = prepare_handoff(output_dir, skip_build=skip_build)
    handoff_path = Path(str(handoff_result["handoff_json"]))
    receipt_path = Path(str(handoff_result["receipt_json"]))
    handoff = verify_handoff_file(handoff_path)
    receipt = verify_shareable_receipt_file(receipt_path)
    payload = _send_ready_payload(handoff, receipt)

    json_path = output_dir / SEND_READY_JSON_NAME
    md_path = output_dir / SEND_READY_MD_NAME
    _write_json(json_path, payload)
    md_path.write_text(_send_ready_markdown(payload), encoding="utf-8")

    _assert_shareable_file(json_path)
    _assert_shareable_file(md_path)

    result = {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "send_ready_json": str(json_path),
        "send_ready_md": str(md_path),
        "handoff_json": str(handoff_path),
        "handoff_md": handoff_result["handoff_md"],
        "receipt_json": handoff_result["receipt_json"],
        "zip_file": payload["release"]["zip_file"],
        "archive_sha256": payload["release"]["archive_sha256"],
    }
    if payload["verdict"] != "GO":
        failed = [name for name, passed in payload["checks"].items() if passed is not True]
        raise SendReadyError("send-ready check failed: " + ", ".join(failed))
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Build the external alpha send-ready GO/NO-GO receipt.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Release output directory. Defaults to dist.")
    parser.add_argument("--skip-build", action="store_true", help="Reuse the existing ZIP, manifest, and handoff.")
    parser.add_argument("--verify-send-ready", default=None, help="Verify an existing send-ready JSON receipt.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_send_ready:
        try:
            payload = verify_send_ready_file(Path(args.verify_send_ready))
        except Exception as exc:  # noqa: BLE001 - CLI should report one concise verifier failure.
            logger.error("[FAIL] external alpha send-ready verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha send-ready verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("body   : %s", payload["send_ready_body_sha256"])
        logger.info("zip    : %s", payload["release"]["zip_file"])
        return 0

    try:
        result = check_send_ready(Path(args.output_dir), skip_build=args.skip_build)
    except Exception as exc:  # noqa: BLE001 - Operational gate failures are reported as one line.
        logger.error("[FAIL] external alpha send-ready: %s", exc)
        return 1

    logger.info("[PASS] external alpha send-ready")
    logger.info("verdict      : %s", result["verdict"])
    logger.info("send_ready_md: %s", result["send_ready_md"])
    logger.info("zip          : %s", result["zip_file"])
    logger.info("sha256       : %s", result["archive_sha256"])
    return 0


def _send_ready_payload(handoff: dict[str, Any], receipt_payload: dict[str, Any]) -> dict[str, Any]:
    """Condense the release handoff and receipt into a send-ready payload."""
    release = handoff.get("release") if isinstance(handoff.get("release"), dict) else {}
    receipt = handoff.get("receipt") if isinstance(handoff.get("receipt"), dict) else {}
    verified = handoff.get("verified") if isinstance(handoff.get("verified"), dict) else {}
    dispatch_policy = (
        handoff.get("dispatch_execution_policy")
        if isinstance(handoff.get("dispatch_execution_policy"), dict)
        else {}
    )
    support_files = handoff.get("support_files") if isinstance(handoff.get("support_files"), list) else []
    do_not_share = handoff.get("do_not_share") if isinstance(handoff.get("do_not_share"), list) else []
    recipient_steps = handoff.get("recipient_steps") if isinstance(handoff.get("recipient_steps"), list) else []
    copy_paste_message = str(handoff.get("copy_paste_message") or "")
    handoff_checks = handoff.get("handoff_checks") if isinstance(handoff.get("handoff_checks"), dict) else {}
    receipt_checks = receipt_payload.get("receipt_checks") if isinstance(receipt_payload.get("receipt_checks"), dict) else {}
    receipt_verified_checks = (
        receipt_payload.get("verified_checks") if isinstance(receipt_payload.get("verified_checks"), dict) else {}
    )

    checks = {
        "handoff_ready": handoff.get("status") == "ready_to_send",
        "handoff_safe_to_share": handoff.get("safe_to_share") is True,
        "handoff_body_hash_matched": handoff_checks.get("handoff_body_hash_matched") is True,
        "handoff_checks_true": bool(handoff_checks) and all(value is True for value in handoff_checks.values()),
        "zip_file_named": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_sha256_present": _looks_like_sha256(release.get("archive_sha256")),
        "file_count_positive": isinstance(release.get("file_count"), int) and release.get("file_count") > 0,
        "receipt_present": receipt.get("file") == RECEIPT_NAME and _looks_like_sha256(receipt.get("body_sha256")),
        "handoff_receipt_body_matches_current_receipt": receipt.get("body_sha256")
        == receipt_payload.get("receipt_body_sha256"),
        "receipt_body_hash_matched": receipt_checks.get("receipt_body_hash_matched") is True,
        "receipt_checks_true": bool(receipt_checks) and all(value is True for value in receipt_checks.values()),
        "receipt_verified_checks_true": bool(receipt_verified_checks)
        and all(value is True for value in receipt_verified_checks.values()),
        "verified_checks_true": bool(verified) and all(value is True for value in verified.values()),
        "support_files_named": {
            "external_alpha_release_verification_receipt.json",
            "external_alpha_diagnostics.json",
        }.issubset(set(str(item) for item in support_files)),
        "dispatch_execution_policy_matched": dispatch_policy == DISPATCH_EXECUTION_POLICY,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "do_not_share_guardrails": REQUIRED_DO_NOT_SHARE.issubset(set(str(item) for item in do_not_share)),
        "recipient_steps_actionable": any("START_CAMBRIAN_AGENT_PLATFORM.bat" in str(step) for step in recipient_steps)
        and any("EXTERNAL_ALPHA_SUPPORT_PACKET.md" in str(step) for step in recipient_steps)
        and any("QUICKSTART_EXTERNAL_ALPHA.md" in str(step) for step in recipient_steps)
        and any("RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in str(step) for step in recipient_steps),
        "copy_paste_message_ready": f"Attachment: {RELEASE_SLUG}.zip" in copy_paste_message
        and "sha256:" in copy_paste_message
        and "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message
        and "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md" in copy_paste_message
        and "Do not send" in copy_paste_message
        and "CONFIRMED" in copy_paste_message
        and "reply only" in copy_paste_message
        and "raw screenshots" in copy_paste_message,
    }
    verdict = "GO" if all(checks.values()) else "NO_GO"
    payload = {
        "schema_version": SEND_READY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready_to_send" if verdict == "GO" else "blocked",
        "verdict": verdict,
        "safe_to_share": True,
        "release": {
            "version": release.get("version"),
            "zip_file": release.get("zip_file"),
            "manifest_file": release.get("manifest_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
            "boundary_count": release.get("boundary_count"),
        },
        "handoff": {
            "file": HANDOFF_JSON_NAME,
            "markdown": HANDOFF_MD_NAME,
            "body_sha256": handoff.get("handoff_body_sha256"),
            "verified_standalone": True,
        },
        "receipt": {
            "file": receipt.get("file"),
            "body_sha256": receipt.get("body_sha256"),
            "verified_standalone": True,
        },
        "dispatch_execution_policy": dispatch_policy,
        "checks": checks,
        "send_to_recipient": [
            str(release.get("zip_file")),
            "copy_paste_message",
        ],
        "operator_next_action": (
            "Manually send the ZIP and copy_paste_message to exactly one external alpha recipient."
            if verdict == "GO"
            else "Fix the failed checks, then rerun send-ready."
        ),
        "do_not_share": do_not_share,
        "copy_paste_message": copy_paste_message,
    }
    payload["send_ready_body_sha256"] = _send_ready_body_sha256(payload)
    payload["artifact_chain"] = _artifact_chain(payload)
    payload["send_ready_checks"] = _send_ready_checks(payload)
    verify_send_ready_payload(payload)
    return payload


def verify_send_ready_file(path: Path) -> dict[str, Any]:
    """Verify an existing send-ready JSON receipt."""
    payload = _read_json(path)
    verify_send_ready_payload(payload)
    return payload


def verify_send_ready_payload(payload: dict[str, Any]) -> None:
    """Verify that a send-ready JSON payload is an untampered GO receipt."""
    if payload.get("schema_version") != SEND_READY_SCHEMA_VERSION:
        raise SendReadyError("send-ready schema_version is invalid.")
    if payload.get("status") != "ready_to_send":
        raise SendReadyError(f"send-ready status is not ready_to_send: {payload.get('status')}")
    if payload.get("verdict") != "GO":
        raise SendReadyError(f"send-ready verdict is not GO: {payload.get('verdict')}")
    if payload.get("safe_to_share") is not True:
        raise SendReadyError("send-ready safe_to_share is not true.")

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks or any(value is not True for value in checks.values()):
        raise SendReadyError("send-ready checks are not all true.")

    send_ready_checks = payload.get("send_ready_checks") if isinstance(payload.get("send_ready_checks"), dict) else {}
    if not send_ready_checks:
        raise SendReadyError("send_ready_checks is missing.")
    if payload.get("send_ready_body_sha256") != _send_ready_body_sha256(payload):
        raise SendReadyError("send-ready body hash does not match.")
    recalculated_checks = _send_ready_checks(payload)
    if send_ready_checks != recalculated_checks:
        raise SendReadyError("send-ready safety checks do not match the current body.")
    failed_checks = [name for name, passed in recalculated_checks.items() if passed is not True]
    if failed_checks:
        raise SendReadyError("send-ready safety check failed: " + ", ".join(failed_checks))


def _send_ready_body_sha256(payload: dict[str, Any]) -> str:
    """Hash the stable send-ready receipt body."""
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"send_ready_body_sha256", "artifact_chain", "send_ready_checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_chain(payload: dict[str, Any]) -> list[dict[str, str]]:
    """List the artifact hashes that make up the send-ready chain."""
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    handoff = payload.get("handoff") if isinstance(payload.get("handoff"), dict) else {}
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    return [
        {
            "kind": "release_zip",
            "file": str(release.get("zip_file") or ""),
            "sha256": str(release.get("archive_sha256") or ""),
        },
        {
            "kind": "handoff_json",
            "file": str(handoff.get("file") or ""),
            "sha256": str(handoff.get("body_sha256") or ""),
        },
        {
            "kind": "receipt_json",
            "file": str(receipt.get("file") or ""),
            "sha256": str(receipt.get("body_sha256") or ""),
        },
        {
            "kind": "send_ready_json",
            "file": SEND_READY_JSON_NAME,
            "sha256": str(payload.get("send_ready_body_sha256") or ""),
        },
    ]


def _send_ready_checks(payload: dict[str, Any]) -> dict[str, bool]:
    """Verify the send-ready payload still matches the release and send policy."""
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    release = payload.get("release") if isinstance(payload.get("release"), dict) else {}
    handoff = payload.get("handoff") if isinstance(payload.get("handoff"), dict) else {}
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    dispatch_policy = (
        payload.get("dispatch_execution_policy")
        if isinstance(payload.get("dispatch_execution_policy"), dict)
        else {}
    )
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    artifact_chain = payload.get("artifact_chain") if isinstance(payload.get("artifact_chain"), list) else []
    do_not_share = payload.get("do_not_share") if isinstance(payload.get("do_not_share"), list) else []
    copy_paste_message = str(payload.get("copy_paste_message") or "")
    body_hash = payload.get("send_ready_body_sha256")
    chain_by_kind = {
        item.get("kind"): item
        for item in artifact_chain
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    }
    return {
        "schema_version_present": payload.get("schema_version") == SEND_READY_SCHEMA_VERSION,
        "verdict_go": payload.get("verdict") == "GO",
        "ready_to_send": payload.get("status") == "ready_to_send",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "absolute_paths_omitted": str(ROOT) not in serialized and (not home or home not in serialized),
        "zip_file_present": release.get("zip_file") == f"{RELEASE_SLUG}.zip",
        "archive_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "handoff_body_hash_present": _looks_like_sha256(handoff.get("body_sha256")),
        "handoff_verified_standalone": handoff.get("verified_standalone") is True,
        "receipt_body_hash_present": _looks_like_sha256(receipt.get("body_sha256")),
        "receipt_verified_standalone": receipt.get("verified_standalone") is True,
        "handoff_receipt_body_matches_current_receipt": checks.get("handoff_receipt_body_matches_current_receipt")
        is True,
        "dispatch_execution_policy_matched": dispatch_policy == DISPATCH_EXECUTION_POLICY,
        "dispatch_manual_only_policy": dispatch_policy.get("script_sends_to_recipient") is False
        and dispatch_policy.get("script_sends_copy_paste_message") is False
        and dispatch_policy.get("manual_operator_dispatch_required") is True,
        "dispatch_one_recipient_policy": dispatch_policy.get("max_recipients_per_record") == 1
        and dispatch_policy.get("cohort_scaling_allowed") is False,
        "dispatch_private_hash_only_policy": dispatch_policy.get("records_private_sha256_only") is True
        and dispatch_policy.get("raw_private_content_included") is False,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "artifact_chain_complete": {"release_zip", "handoff_json", "receipt_json", "send_ready_json"}.issubset(
            set(chain_by_kind)
        ),
        "artifact_chain_hashes_present": bool(artifact_chain)
        and all(isinstance(item, dict) and _looks_like_sha256(item.get("sha256")) for item in artifact_chain),
        "artifact_chain_release_hash_matched": chain_by_kind.get("release_zip", {}).get("sha256")
        == release.get("archive_sha256"),
        "artifact_chain_handoff_hash_matched": chain_by_kind.get("handoff_json", {}).get("sha256")
        == handoff.get("body_sha256"),
        "artifact_chain_receipt_hash_matched": chain_by_kind.get("receipt_json", {}).get("sha256")
        == receipt.get("body_sha256"),
        "artifact_chain_send_ready_hash_matched": chain_by_kind.get("send_ready_json", {}).get("sha256")
        == body_hash,
        "do_not_share_guardrails_present": REQUIRED_DO_NOT_SHARE.issubset(set(str(item) for item in do_not_share)),
        "copy_paste_message_present": f"Attachment: {RELEASE_SLUG}.zip" in copy_paste_message,
        "copy_paste_message_mentions_quickstart": "QUICKSTART_EXTERNAL_ALPHA.md" in copy_paste_message,
        "copy_paste_message_mentions_agent_prompt": "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md"
        in copy_paste_message,
        "recipient_ack_request_present": "CONFIRMED" in copy_paste_message and "reply only" in copy_paste_message,
        "send_ready_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "send_ready_body_hash_matched": body_hash == _send_ready_body_sha256(payload),
    }


def _send_ready_markdown(payload: dict[str, Any]) -> str:
    """Render the send-ready payload as Markdown."""
    dispatch_policy = payload["dispatch_execution_policy"]
    checks = "\n".join(f"- {name}: {passed}" for name, passed in payload["checks"].items())
    artifact_chain = "\n".join(
        f"- {item['kind']}: {item['file']} {item['sha256']}" for item in payload["artifact_chain"]
    )
    do_not_share = "\n".join(f"- {item}" for item in payload["do_not_share"])
    return f"""# Cambrian External Alpha Send Ready

## Verdict

- verdict: {payload["verdict"]}
- status: {payload["status"]}
- safe_to_share: {payload["safe_to_share"]}
- send-ready body sha256: {payload["send_ready_body_sha256"]}
- zip file: {payload["release"]["zip_file"]}
- archive sha256: {payload["release"]["archive_sha256"]}
- file count: {payload["release"]["file_count"]}
- handoff: {payload["handoff"]["file"]}
- handoff body sha256: {payload["handoff"]["body_sha256"]}
- handoff verified standalone: {payload["handoff"]["verified_standalone"]}
- receipt: {payload["receipt"]["file"]}
- receipt body sha256: {payload["receipt"]["body_sha256"]}
- receipt verified standalone: {payload["receipt"]["verified_standalone"]}

## Checks

{checks}

## Artifact Chain

{artifact_chain}

## Dispatch Execution Policy

- script sends to recipient: {dispatch_policy["script_sends_to_recipient"]}
- script sends copy-paste message: {dispatch_policy["script_sends_copy_paste_message"]}
- manual operator dispatch required: {dispatch_policy["manual_operator_dispatch_required"]}
- max recipients per record: {dispatch_policy["max_recipients_per_record"]}
- records private sha256 only: {dispatch_policy["records_private_sha256_only"]}
- raw private content included: {dispatch_policy["raw_private_content_included"]}
- cohort scaling allowed: {dispatch_policy["cohort_scaling_allowed"]}
- sent recorded by private hashes only: {dispatch_policy["sent_recorded_by_private_hashes_only"]}

## Copy Paste Message

```text
{payload["copy_paste_message"]}
```

## Do Not Share

{do_not_share}

## Operator Next Action

{payload["operator_next_action"]}
"""


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SendReadyError(f"Cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise SendReadyError(f"JSON parse failed: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SendReadyError(f"JSON file is not an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _looks_like_sha256(value: Any) -> bool:
    """Return true when value is a lower-case sha256 string."""
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _assert_shareable_file(path: Path) -> None:
    """Reject generated receipts that leak local paths or test secrets."""
    text = path.read_text(encoding="utf-8")
    forbidden_fragments = [str(ROOT), str(Path.home()), "SHOULD_NOT_APPEAR_IN_DIAGNOSTICS"]
    found = [fragment for fragment in forbidden_fragments if fragment and fragment in text]
    if found:
        raise SendReadyError(f"Generated send-ready file contains private local data: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
