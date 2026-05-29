"""Recipient-style smoke gate for the external alpha release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_external_alpha_release import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_ZIP,
    ReleaseVerificationError,
    verify_release,
)


SMOKE_SCHEMA_VERSION = "external_alpha_release_bundle_smoke_v0_1"
SMOKE_RECEIPT_NAME = "cambrian-agent-platform-external-alpha-bundle-smoke-receipt.json"


class ExternalAlphaBundleSmokeError(RuntimeError):
    """External alpha release bundle smoke gate failed."""


def smoke_release_bundle(
    *,
    zip_path: Path = DEFAULT_ZIP,
    manifest_path: Path = DEFAULT_MANIFEST,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Verify the ZIP as an extracted recipient bundle and write a share-safe smoke receipt."""
    result = verify_release(zip_path=zip_path, manifest_path=manifest_path)
    receipt = _smoke_receipt(result)
    target = (receipt_path or ROOT / "dist" / SMOKE_RECEIPT_NAME).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_bundle_smoke_receipt_file(target)
    return receipt


def verify_bundle_smoke_receipt_file(path: Path) -> dict[str, Any]:
    """Verify a previously written external alpha release bundle smoke receipt."""
    payload = json.loads(path.resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ExternalAlphaBundleSmokeError("external alpha bundle smoke receipt must be a JSON object.")
    verify_bundle_smoke_receipt_payload(payload)
    return payload


def verify_bundle_smoke_receipt_payload(payload: dict[str, Any]) -> None:
    """Validate a share-safe external alpha release bundle smoke receipt payload."""
    if payload.get("schema_version") != SMOKE_SCHEMA_VERSION:
        raise ExternalAlphaBundleSmokeError("external alpha bundle smoke receipt schema_version mismatch.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed = [name for name, passed in checks.items() if passed is not True]
    if not checks or failed:
        raise ExternalAlphaBundleSmokeError("external alpha bundle smoke checks failed: " + ", ".join(failed))
    receipt_checks = payload.get("receipt_checks") if isinstance(payload.get("receipt_checks"), dict) else {}
    failed_receipt = [name for name, passed in receipt_checks.items() if passed is not True]
    if not receipt_checks or failed_receipt:
        raise ExternalAlphaBundleSmokeError(
            "external alpha bundle smoke receipt self-checks failed: " + ", ".join(failed_receipt)
        )
    if payload.get("receipt_body_sha256") != _receipt_body_sha256(payload):
        raise ExternalAlphaBundleSmokeError("external alpha bundle smoke receipt body hash mismatch.")


def _smoke_receipt(result: dict[str, Any]) -> dict[str, Any]:
    policy = result.get("dispatch_execution_policy") if isinstance(result.get("dispatch_execution_policy"), dict) else {}
    browser = result.get("browser_wrapper") if isinstance(result.get("browser_wrapper"), dict) else {}
    batch = result.get("batch_rehearsal") if isinstance(result.get("batch_rehearsal"), dict) else {}
    checks = {
        "release_verifier_passed": result.get("status") == "pass",
        "archive_sha256_present": _looks_like_sha256(str(result.get("archive_sha256") or "")),
        "file_count_positive": isinstance(result.get("file_count"), int) and result["file_count"] > 0,
        "diagnostics_safe_to_share": result.get("diagnostics_status") == "pass"
        and result.get("diagnostics_safe_to_share") is True,
        "browser_wrapper_help_checked": browser.get("status") == "pass"
        and browser.get("script") == "verify_agent_platform_browser_flow.py",
        "batch_rehearsal_checked": batch.get("status") in {"pass", "skipped"},
        "manual_dispatch_policy_locked": policy.get("script_sends_to_recipient") is False
        and policy.get("script_sends_copy_paste_message") is False
        and policy.get("manual_operator_dispatch_required") is True
        and policy.get("max_recipients_per_record") == 1
        and policy.get("records_private_sha256_only") is True,
    }
    payload = {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "safe_to_share": True,
        "release_bundle": {
            "zip_file": DEFAULT_ZIP.name,
            "manifest_file": DEFAULT_MANIFEST.name,
            "archive_sha256": result.get("archive_sha256"),
            "file_count": result.get("file_count"),
            "release_version": result.get("release_version"),
        },
        "recipient_rehearsal": {
            "extracted_platform_verification": "pass",
            "diagnostics_status": result.get("diagnostics_status"),
            "diagnostics_safe_to_share": result.get("diagnostics_safe_to_share"),
            "browser_wrapper_help": browser.get("status"),
            "windows_batch_rehearsal": batch.get("status"),
        },
        "checks": checks,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "claim_boundaries": {
            "public_proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "sale_ready": False,
        },
    }
    payload["receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["receipt_checks"] = _receipt_checks(payload)
    return payload


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    claims = payload.get("claim_boundaries") if isinstance(payload.get("claim_boundaries"), dict) else {}
    return {
        "schema_version_present": payload.get("schema_version") == SMOKE_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "checks_all_true": all(
            value is True for value in (payload.get("checks") if isinstance(payload.get("checks"), dict) else {}).values()
        ),
        "absolute_paths_omitted": privacy.get("absolute_paths_included") is False,
        "raw_private_project_data_omitted": privacy.get("raw_private_project_data_included") is False,
        "secrets_omitted": privacy.get("secrets_included") is False,
        "claim_boundaries_locked": claims.get("public_proof_claim_allowed") is False
        and claims.get("success_rate_claim_allowed") is False
        and claims.get("sale_ready") is False,
        "body_hash_present": _looks_like_sha256(str(payload.get("receipt_body_sha256") or "")),
        "body_hash_matched": payload.get("receipt_body_sha256") == _receipt_body_sha256(payload),
    }


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "receipt_body_sha256", "receipt_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the external alpha ZIP as an extracted recipient bundle.")
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--receipt", type=Path, default=ROOT / "dist" / SMOKE_RECEIPT_NAME)
    parser.add_argument("--verify-receipt", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.verify_receipt:
        payload = verify_bundle_smoke_receipt_file(args.verify_receipt)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    try:
        receipt = smoke_release_bundle(zip_path=args.zip, manifest_path=args.manifest, receipt_path=args.receipt)
    except (ExternalAlphaBundleSmokeError, ReleaseVerificationError, OSError, json.JSONDecodeError) as exc:
        print(f"[FAIL] external alpha release bundle smoke: {exc}", file=sys.stderr)
        return 1

    print("[PASS] external alpha release bundle smoke")
    print(f"zip     : {receipt['release_bundle']['zip_file']}")
    print(f"sha256  : {receipt['release_bundle']['archive_sha256']}")
    print(f"receipt : {receipt['receipt_body_sha256']}")
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
