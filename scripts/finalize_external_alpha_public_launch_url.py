"""Finalize or rehearse the external alpha public launch URL gate."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.prepare_external_alpha_public_launch_handoff import (  # noqa: E402
    PUBLIC_LAUNCH_HANDOFF_JSON_NAME,
    prepare_public_launch_handoff,
    verify_public_launch_handoff_file,
)
from scripts.verify_external_alpha_public_download_site_url import (  # noqa: E402
    DOWNLOADED_RELEASE_REQUIRED_FILES,
    PUBLIC_SITE_URL_VERDICT,
    verify_public_download_site_url,
    verify_public_download_site_url_receipt_payload,
)


PUBLIC_LAUNCH_URL_GATE_SCHEMA_VERSION = "external_alpha_public_launch_url_gate_v0_1"
PUBLIC_LAUNCH_URL_READY_VERDICT = "PUBLIC_LAUNCH_URL_READY"
PUBLIC_LAUNCH_URL_REHEARSAL_VERDICT = "PUBLIC_LAUNCH_URL_REHEARSAL_READY"
PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME = f"{RELEASE_SLUG}-public-launch-url-gate-receipt.json"

logger = logging.getLogger(__name__)


class PublicLaunchUrlGateError(RuntimeError):
    """Public launch URL gate generation or verification failed."""


def finalize_public_launch_url(
    base_url: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    expected_archive_sha256: str | None = None,
    timeout_seconds: float = 20.0,
    allow_local_rehearsal: bool = False,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Verify a hosted URL and write the final public launch URL gate receipt."""
    output_dir = output_dir.resolve()
    handoff_result = prepare_public_launch_handoff(output_dir)
    handoff = verify_public_launch_handoff_file(Path(handoff_result["handoff_json"]))
    release = _dict(handoff, "release")
    expected_hash = expected_archive_sha256 or release.get("archive_sha256")

    url_receipt = verify_public_download_site_url(
        base_url,
        expected_archive_sha256=expected_hash,
        timeout_seconds=timeout_seconds,
    )
    classification = _classify_url(_dict(url_receipt, "url").get("base_url"))
    if classification["is_local_or_private"] and not allow_local_rehearsal:
        raise PublicLaunchUrlGateError("local or private URL requires --allow-local-rehearsal.")

    payload = _gate_payload(
        handoff=handoff,
        url_receipt=url_receipt,
        url_classification=classification,
        allow_local_rehearsal=allow_local_rehearsal,
    )
    receipt_path = (receipt_path or output_dir / PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_public_launch_url_gate_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "url": payload["url"]["base_url"],
        "external_sharing_allowed": payload["launch_state"]["external_sharing_allowed"],
        "receipt_body_sha256": payload["public_launch_url_gate_receipt_body_sha256"],
    }


def verify_public_launch_url_gate_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_launch_url_gate_receipt_payload(payload)
    return payload


def verify_public_launch_url_gate_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PUBLIC_LAUNCH_URL_GATE_SCHEMA_VERSION:
        raise PublicLaunchUrlGateError("public launch URL gate schema_version mismatch.")
    if payload.get("status") != "pass":
        raise PublicLaunchUrlGateError("public launch URL gate did not pass.")
    if payload.get("verdict") not in {PUBLIC_LAUNCH_URL_READY_VERDICT, PUBLIC_LAUNCH_URL_REHEARSAL_VERDICT}:
        raise PublicLaunchUrlGateError("public launch URL gate verdict mismatch.")
    if payload.get("safe_to_share") is not True:
        raise PublicLaunchUrlGateError("public launch URL gate must be safe_to_share.")

    url_receipt = _dict(payload, "url_receipt")
    verify_public_download_site_url_receipt_payload(url_receipt)

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _gate_checks(payload)
    if checks != recalculated:
        raise PublicLaunchUrlGateError("public launch URL gate checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicLaunchUrlGateError("public launch URL gate checks failed: " + ", ".join(failed))
    if payload.get("public_launch_url_gate_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise PublicLaunchUrlGateError("public launch URL gate body hash mismatch.")


def _gate_payload(
    *,
    handoff: dict[str, Any],
    url_receipt: dict[str, Any],
    url_classification: dict[str, Any],
    allow_local_rehearsal: bool,
) -> dict[str, Any]:
    is_rehearsal = bool(url_classification.get("is_local_or_private"))
    verdict = PUBLIC_LAUNCH_URL_REHEARSAL_VERDICT if is_rehearsal else PUBLIC_LAUNCH_URL_READY_VERDICT
    external_sharing_allowed = not is_rehearsal
    url = _dict(url_receipt, "url")
    observed = _dict(url_receipt, "observed")
    downloaded = _dict(url_receipt, "downloaded_release_zip")
    package = _dict(handoff, "package")
    release = _dict(handoff, "release")
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_LAUNCH_URL_GATE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": verdict,
        "safe_to_share": True,
        "launch_state": {
            "mode": "local_rehearsal" if is_rehearsal else "public_url",
            "public_url_ready": not is_rehearsal,
            "local_rehearsal_ready": is_rehearsal,
            "external_sharing_allowed": external_sharing_allowed,
            "external_sharing_state": "PUBLIC_URL_VERIFIED" if not is_rehearsal else "BLOCKED_LOCAL_REHEARSAL_ONLY",
        },
        "url": {
            "base_url": url.get("base_url"),
            "entrypoint": url.get("entrypoint"),
            "scheme": url_classification.get("scheme"),
            "host": url_classification.get("host"),
            "is_local_or_private": url_classification.get("is_local_or_private"),
            "allow_local_rehearsal": allow_local_rehearsal,
        },
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "package": {
            "zip_file": package.get("zip_file"),
            "zip_sha256": package.get("zip_sha256"),
            "receipt_body_sha256": package.get("receipt_body_sha256"),
        },
        "handoff": {
            "file": PUBLIC_LAUNCH_HANDOFF_JSON_NAME,
            "verdict": handoff.get("verdict"),
            "receipt_body_sha256": handoff.get("public_launch_handoff_body_sha256"),
        },
        "downloaded_release_zip": downloaded,
        "url_receipt_summary": {
            "verdict": url_receipt.get("verdict"),
            "body_sha256": url_receipt.get("public_download_site_url_receipt_body_sha256"),
            "downloaded_zip_sha256": observed.get("zip_sha256"),
            "downloaded_zip_bytes": observed.get("zip_bytes"),
        },
        "url_receipt": url_receipt,
        "policy": {
            "requires_public_https_for_external_share": True,
            "local_rehearsal_cannot_be_shared": True,
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
        },
        "pm_judgment": (
            "External sharing is allowed only for a non-local HTTPS URL that passes the full URL and downloaded ZIP smoke gate."
        ),
    }
    payload["public_launch_url_gate_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _gate_checks(payload)
    return payload


def _gate_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    launch_state = _dict(payload, "launch_state")
    url = _dict(payload, "url")
    release = _dict(payload, "release")
    package = _dict(payload, "package")
    handoff = _dict(payload, "handoff")
    downloaded = _dict(payload, "downloaded_release_zip")
    url_summary = _dict(payload, "url_receipt_summary")
    url_receipt = _dict(payload, "url_receipt")
    policy = _dict(payload, "policy")
    required_files = downloaded.get("required_files_present")
    required_files = required_files if isinstance(required_files, list) else []
    is_rehearsal = launch_state.get("mode") == "local_rehearsal"
    is_public = launch_state.get("mode") == "public_url"
    body_hash = payload.get("public_launch_url_gate_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_LAUNCH_URL_GATE_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "verdict_matches_mode": (is_rehearsal and payload.get("verdict") == PUBLIC_LAUNCH_URL_REHEARSAL_VERDICT)
        or (is_public and payload.get("verdict") == PUBLIC_LAUNCH_URL_READY_VERDICT),
        "url_receipt_ready": url_receipt.get("verdict") == PUBLIC_SITE_URL_VERDICT
        and url_summary.get("verdict") == PUBLIC_SITE_URL_VERDICT,
        "url_receipt_hash_present": _looks_like_sha256(url_summary.get("body_sha256")),
        "url_not_placeholder": isinstance(url.get("base_url"), str)
        and "<" not in url.get("base_url", "")
        and ">" not in url.get("base_url", ""),
        "public_url_https_for_external_share": (is_public and url.get("scheme") == "https")
        or (is_rehearsal and url.get("is_local_or_private") is True),
        "local_rehearsal_blocked_from_external_share": (is_rehearsal and url.get("allow_local_rehearsal") is True)
        == (is_rehearsal and launch_state.get("external_sharing_allowed") is False),
        "public_url_external_share_allowed": (is_public and url.get("is_local_or_private") is False)
        == (is_public and launch_state.get("external_sharing_allowed") is True),
        "launch_state_consistent": (
            is_rehearsal
            and launch_state.get("public_url_ready") is False
            and launch_state.get("local_rehearsal_ready") is True
            and launch_state.get("external_sharing_state") == "BLOCKED_LOCAL_REHEARSAL_ONLY"
        )
        or (
            is_public
            and launch_state.get("public_url_ready") is True
            and launch_state.get("local_rehearsal_ready") is False
            and launch_state.get("external_sharing_state") == "PUBLIC_URL_VERIFIED"
        ),
        "release_hash_matched": _looks_like_sha256(release.get("archive_sha256"))
        and release.get("archive_sha256") == url_summary.get("downloaded_zip_sha256"),
        "package_hash_present": _looks_like_sha256(package.get("zip_sha256")),
        "handoff_ready": handoff.get("verdict") == "PUBLIC_LAUNCH_HANDOFF_READY"
        and _looks_like_sha256(handoff.get("receipt_body_sha256")),
        "downloaded_zip_opened": isinstance(downloaded.get("entry_count"), int)
        and downloaded.get("entry_count", 0) > 0,
        "downloaded_zip_root_locked": downloaded.get("root_dir") == RELEASE_SLUG
        and downloaded.get("all_entries_under_root") is True,
        "downloaded_user_entrypoints_present": set(DOWNLOADED_RELEASE_REQUIRED_FILES).issubset(
            set(required_files)
        ),
        "downloaded_quickstart_actionable": downloaded.get("quickstart_mentions_start_bat") is True
        and downloaded.get("quickstart_mentions_builder_golden_path") is True
        and downloaded.get("prompt_mentions_quickstart") is True
        and downloaded.get("prompt_mentions_start_bat") is True,
        "manual_only_no_email_collection": policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "policy_requires_https": policy.get("requires_public_https_for_external_share") is True,
        "policy_blocks_local_rehearsal_share": policy.get("local_rehearsal_cannot_be_shared") is True,
        "pm_judgment_present": isinstance(payload.get("pm_judgment"), str)
        and "External sharing is allowed only" in payload.get("pm_judgment", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _classify_url(base_url: Any) -> dict[str, Any]:
    if not isinstance(base_url, str):
        raise PublicLaunchUrlGateError("URL receipt base_url is missing.")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PublicLaunchUrlGateError("base URL must be an http or https URL.")
    host = parsed.hostname or ""
    return {
        "scheme": parsed.scheme,
        "host": host,
        "is_local_or_private": _is_local_or_private_host(host),
    }


def _is_local_or_private_host(host: str) -> bool:
    lowered = host.lower()
    if lowered in {"localhost", "0.0.0.0"} or lowered.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicLaunchUrlGateError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicLaunchUrlGateError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicLaunchUrlGateError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_launch_url_gate_receipt_body_sha256", "checks"}
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
    parser = argparse.ArgumentParser(description="Finalize or rehearse the external alpha public launch URL gate.")
    parser.add_argument("base_url", nargs="?")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--expected-archive-sha256", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--allow-local-rehearsal", action="store_true")
    parser.add_argument("--receipt", default=None)
    parser.add_argument("--verify-receipt", default=None)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_public_launch_url_gate_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public launch URL gate receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha public launch URL gate receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("share  : %s", payload["launch_state"]["external_sharing_allowed"])
        logger.info("body   : %s", payload["public_launch_url_gate_receipt_body_sha256"])
        return 0

    if not args.base_url:
        logger.error("[FAIL] base_url is required unless --verify-receipt is used")
        return 2

    try:
        result = finalize_public_launch_url(
            args.base_url,
            Path(args.output_dir),
            expected_archive_sha256=args.expected_archive_sha256,
            timeout_seconds=args.timeout_seconds,
            allow_local_rehearsal=args.allow_local_rehearsal,
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing URL gate failure.
        logger.error("[FAIL] external alpha public launch URL gate: %s", exc)
        return 1

    logger.info("[PASS] external alpha public launch URL gate")
    logger.info("verdict: %s", result["verdict"])
    logger.info("url    : %s", result["url"])
    logger.info("share  : %s", result["external_sharing_allowed"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
