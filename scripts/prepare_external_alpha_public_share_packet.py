"""Prepare the final share packet after the public launch URL gate passes."""

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
from scripts.finalize_external_alpha_public_launch_url import (  # noqa: E402
    PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
    PUBLIC_LAUNCH_URL_READY_VERDICT,
    verify_public_launch_url_gate_receipt_file,
)
from scripts.prepare_external_alpha_public_download_site import ZIP_NAME as PUBLIC_DOWNLOAD_ZIP_NAME  # noqa: E402


PUBLIC_SHARE_PACKET_SCHEMA_VERSION = "external_alpha_public_share_packet_v0_1"
PUBLIC_SHARE_PACKET_VERDICT = "PUBLIC_SHARE_PACKET_READY"
PUBLIC_SHARE_PACKET_JSON_NAME = f"{RELEASE_SLUG}-public-share-packet.json"
PUBLIC_SHARE_PACKET_MD_NAME = f"{RELEASE_SLUG}-public-share-packet.md"

logger = logging.getLogger(__name__)


class PublicSharePacketError(RuntimeError):
    """Public share packet generation or verification failed."""


def prepare_public_share_packet(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    gate_receipt: Path | None = None,
    packet_json: Path | None = None,
    packet_md: Path | None = None,
) -> dict[str, Any]:
    """Write the public share packet, but only after the real HTTPS URL gate passes."""
    output_dir = output_dir.resolve()
    gate_receipt = (gate_receipt or output_dir / PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME).resolve()
    try:
        gate = verify_public_launch_url_gate_receipt_file(gate_receipt)
    except Exception as exc:  # noqa: BLE001 - normalize operator-facing gate failures.
        raise PublicSharePacketError(f"cannot verify public launch URL gate receipt: {gate_receipt.name}") from exc
    _assert_public_gate_ready(gate)

    packet_json = (packet_json or output_dir / PUBLIC_SHARE_PACKET_JSON_NAME).resolve()
    packet_md = (packet_md or output_dir / PUBLIC_SHARE_PACKET_MD_NAME).resolve()
    packet_json.parent.mkdir(parents=True, exist_ok=True)
    packet_md.parent.mkdir(parents=True, exist_ok=True)

    payload = _share_packet_payload(gate=gate, gate_receipt=gate_receipt)
    _write_json(packet_json, payload)
    packet_md.write_text(_share_packet_markdown(payload), encoding="utf-8")
    verify_public_share_packet_file(packet_json)
    _assert_shareable_text(packet_md.read_text(encoding="utf-8"))

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "packet_json": str(packet_json),
        "packet_md": str(packet_md),
        "public_url": payload["url"]["public_url"],
        "receipt_body_sha256": payload["public_share_packet_body_sha256"],
    }


def verify_public_share_packet_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_share_packet_payload(payload)
    return payload


def verify_public_share_packet_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PUBLIC_SHARE_PACKET_SCHEMA_VERSION:
        raise PublicSharePacketError("public share packet schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != PUBLIC_SHARE_PACKET_VERDICT:
        raise PublicSharePacketError("public share packet did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PublicSharePacketError("public share packet must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _share_packet_checks(payload)
    if checks != recalculated:
        raise PublicSharePacketError("public share packet checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicSharePacketError("public share packet checks failed: " + ", ".join(failed))
    if payload.get("public_share_packet_body_sha256") != _packet_body_sha256(payload):
        raise PublicSharePacketError("public share packet body hash mismatch.")


def _assert_public_gate_ready(gate: dict[str, Any]) -> None:
    launch_state = _dict(gate, "launch_state")
    url = _dict(gate, "url")
    if gate.get("verdict") != PUBLIC_LAUNCH_URL_READY_VERDICT:
        raise PublicSharePacketError("public share packet requires PUBLIC_LAUNCH_URL_READY.")
    if launch_state.get("external_sharing_allowed") is not True:
        raise PublicSharePacketError("public share packet requires external_sharing_allowed=true.")
    if url.get("scheme") != "https" or url.get("is_local_or_private") is not False:
        raise PublicSharePacketError("public share packet requires a non-local HTTPS URL.")


def _share_packet_payload(*, gate: dict[str, Any], gate_receipt: Path) -> dict[str, Any]:
    launch_state = _dict(gate, "launch_state")
    url = _dict(gate, "url")
    release = _dict(gate, "release")
    package = _dict(gate, "package")
    url_summary = _dict(gate, "url_receipt_summary")
    url_receipt = _dict(gate, "url_receipt")
    url_receipt_url = _dict(url_receipt, "url")
    public_url = str(url.get("base_url"))
    archive_sha256 = release.get("archive_sha256")
    copy_paste = _copy_paste_message(public_url=public_url, archive_sha256=str(archive_sha256))

    payload: dict[str, Any] = {
        "schema_version": PUBLIC_SHARE_PACKET_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": PUBLIC_SHARE_PACKET_VERDICT,
        "safe_to_share": True,
        "source_gate": {
            "file": gate_receipt.name,
            "verdict": gate.get("verdict"),
            "receipt_body_sha256": gate.get("public_launch_url_gate_receipt_body_sha256"),
            "external_sharing_allowed": launch_state.get("external_sharing_allowed"),
        },
        "url": {
            "public_url": public_url,
            "entrypoint": url.get("entrypoint"),
            "scheme": url.get("scheme"),
            "host": url.get("host"),
            "is_local_or_private": url.get("is_local_or_private"),
            "url_receipt_base_url": url_receipt_url.get("base_url"),
        },
        "download": {
            "public_zip_file": PUBLIC_DOWNLOAD_ZIP_NAME,
            "release_zip_file": release.get("zip_file"),
            "archive_sha256": archive_sha256,
            "downloaded_zip_sha256": url_summary.get("downloaded_zip_sha256"),
            "downloaded_zip_bytes": url_summary.get("downloaded_zip_bytes"),
        },
        "package": {
            "zip_file": package.get("zip_file"),
            "zip_sha256": package.get("zip_sha256"),
        },
        "copy_paste": {
            "message": copy_paste,
            "contains_public_url": public_url in copy_paste,
            "contains_archive_sha256": str(archive_sha256) in copy_paste,
        },
        "policy": {
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
            "production_ready_claim": False,
            "external_sharing_requires_source_gate": True,
        },
        "operator_next_action": "Share only the copy_paste.message after reviewing the public URL and checksum.",
    }
    payload["public_share_packet_body_sha256"] = _packet_body_sha256(payload)
    payload["checks"] = _share_packet_checks(payload)
    return payload


def _share_packet_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    source_gate = _dict(payload, "source_gate")
    url = _dict(payload, "url")
    download = _dict(payload, "download")
    package = _dict(payload, "package")
    copy_paste = _dict(payload, "copy_paste")
    policy = _dict(payload, "policy")
    message = copy_paste.get("message", "")
    public_url = url.get("public_url", "")
    body_hash = payload.get("public_share_packet_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_SHARE_PACKET_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready": payload.get("verdict") == PUBLIC_SHARE_PACKET_VERDICT,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "source_gate_allows_external_sharing": source_gate.get("verdict") == PUBLIC_LAUNCH_URL_READY_VERDICT
        and source_gate.get("external_sharing_allowed") is True
        and _looks_like_sha256(source_gate.get("receipt_body_sha256")),
        "public_url_is_https": isinstance(public_url, str)
        and public_url.startswith("https://")
        and url.get("scheme") == "https",
        "public_url_is_not_local": url.get("is_local_or_private") is False,
        "public_url_matches_url_receipt": public_url == url.get("url_receipt_base_url"),
        "public_url_not_placeholder": isinstance(public_url, str) and "<" not in public_url and ">" not in public_url,
        "download_zip_named": download.get("public_zip_file") == PUBLIC_DOWNLOAD_ZIP_NAME,
        "download_hash_present": _looks_like_sha256(download.get("archive_sha256"))
        and _looks_like_sha256(download.get("downloaded_zip_sha256")),
        "download_hash_matched": download.get("archive_sha256") == download.get("downloaded_zip_sha256"),
        "package_hash_present": _looks_like_sha256(package.get("zip_sha256")),
        "copy_paste_contains_public_url": copy_paste.get("contains_public_url") is True
        and isinstance(message, str)
        and public_url in message,
        "copy_paste_contains_archive_sha256": copy_paste.get("contains_archive_sha256") is True
        and isinstance(message, str)
        and str(download.get("archive_sha256")) in message,
        "copy_paste_sets_alpha_boundary": isinstance(message, str)
        and "external alpha" in message.lower()
        and "production ready" not in message.lower(),
        "manual_only_no_email_collection": policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False
        and policy.get("production_ready_claim") is False,
        "source_gate_required": policy.get("external_sharing_requires_source_gate") is True,
        "no_plain_http_url": "http://" not in serialized,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and "copy_paste.message" in payload.get("operator_next_action", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _packet_body_sha256(payload),
    }


def _copy_paste_message(*, public_url: str, archive_sha256: str) -> str:
    return (
        "Cambrian external alpha download is ready:\n"
        f"{public_url}\n\n"
        f"Download file: {PUBLIC_DOWNLOAD_ZIP_NAME}\n"
        f"SHA256: {archive_sha256}\n\n"
        "This is an external alpha for installation and gold-path verification. "
        "Use the landing page quickstart and share support-safe receipts only if support is needed."
    )


def _share_packet_markdown(payload: dict[str, Any]) -> str:
    url = _dict(payload, "url")
    download = _dict(payload, "download")
    copy_paste = _dict(payload, "copy_paste")
    return f"""# Cambrian Public Share Packet

Verdict: `{payload["verdict"]}`

Public URL:

```text
{url["public_url"]}
```

Download file:

```text
{download["public_zip_file"]}
```

Download sha256:

```text
{download["archive_sha256"]}
```

## Copy-Paste Message

```text
{copy_paste["message"]}
```

## Boundary

- Share this packet only after the source gate verdict is `PUBLIC_LAUNCH_URL_READY`.
- Do not claim production readiness, public traction, or success metrics from this alpha page.
- Do not add private recipient/channel values to this packet.
"""


def _assert_shareable_text(text: str) -> None:
    forbidden = [str(ROOT), str(Path.home()), ".env", "API key or secret", "raw private project files", "http://"]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise PublicSharePacketError("public share packet contains private or non-public material.")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicSharePacketError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicSharePacketError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicSharePacketError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _packet_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_share_packet_body_sha256", "checks"}
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dict(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _looks_like_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the external alpha public share packet.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--gate-receipt", default=None)
    parser.add_argument("--packet-json", default=None)
    parser.add_argument("--packet-md", default=None)
    parser.add_argument("--verify-packet", default=None)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_packet:
        try:
            payload = verify_public_share_packet_file(Path(args.verify_packet))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public share packet verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha public share packet verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("url    : %s", payload["url"]["public_url"])
        logger.info("body   : %s", payload["public_share_packet_body_sha256"])
        return 0

    try:
        result = prepare_public_share_packet(
            Path(args.output_dir),
            gate_receipt=Path(args.gate_receipt) if args.gate_receipt else None,
            packet_json=Path(args.packet_json) if args.packet_json else None,
            packet_md=Path(args.packet_md) if args.packet_md else None,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing packet failure.
        logger.error("[FAIL] external alpha public share packet: %s", exc)
        return 1

    logger.info("[PASS] external alpha public share packet")
    logger.info("verdict: %s", result["verdict"])
    logger.info("url    : %s", result["public_url"])
    logger.info("md     : %s", result["packet_md"])
    logger.info("json   : %s", result["packet_json"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
