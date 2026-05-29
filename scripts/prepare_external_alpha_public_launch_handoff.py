"""Prepare the operator handoff for publishing the external alpha download site."""

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
from scripts.package_external_alpha_public_download_site import (  # noqa: E402
    PACKAGE_VERDICT,
    PUBLIC_SITE_PACKAGE_RECEIPT_NAME,
    PUBLIC_SITE_PACKAGE_ZIP_NAME,
    package_public_download_site,
    verify_public_download_site_package_receipt_file,
)
from scripts.verify_external_alpha_public_download_site_url import DEFAULT_URL_RECEIPT_NAME  # noqa: E402
from scripts.prepare_external_alpha_public_download_site import (  # noqa: E402
    NOJEKYLL_NAME,
    PUBLIC_HOSTING_RUNBOOK_NAME,
    ZIP_NAME as PUBLIC_DOWNLOAD_ZIP_NAME,
)


PUBLIC_LAUNCH_HANDOFF_SCHEMA_VERSION = "external_alpha_public_launch_handoff_v0_1"
PUBLIC_LAUNCH_HANDOFF_VERDICT = "PUBLIC_LAUNCH_HANDOFF_READY"
PUBLIC_LAUNCH_HANDOFF_JSON_NAME = f"{RELEASE_SLUG}-public-launch-handoff.json"
PUBLIC_LAUNCH_HANDOFF_MD_NAME = f"{RELEASE_SLUG}-public-launch-handoff.md"

logger = logging.getLogger(__name__)


class PublicLaunchHandoffError(RuntimeError):
    """Public launch handoff generation or verification failed."""


def prepare_public_launch_handoff(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    handoff_json: Path | None = None,
    handoff_md: Path | None = None,
) -> dict[str, Any]:
    """Write a share-safe operator handoff for publishing the download site."""
    output_dir = output_dir.resolve()
    package_result, package_receipt = _load_or_package_public_download_site(output_dir)

    handoff_json = (handoff_json or output_dir / PUBLIC_LAUNCH_HANDOFF_JSON_NAME).resolve()
    handoff_md = (handoff_md or output_dir / PUBLIC_LAUNCH_HANDOFF_MD_NAME).resolve()
    handoff_json.parent.mkdir(parents=True, exist_ok=True)
    handoff_md.parent.mkdir(parents=True, exist_ok=True)

    payload = _handoff_payload(
        package_result=package_result,
        package_receipt=package_receipt,
    )
    _write_json(handoff_json, payload)
    handoff_md.write_text(_handoff_markdown(payload), encoding="utf-8")
    verify_public_launch_handoff_file(handoff_json)
    _assert_shareable_text(handoff_md.read_text(encoding="utf-8"))

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "handoff_json": str(handoff_json),
        "handoff_md": str(handoff_md),
        "package_zip": package_result["package_zip"],
        "package_sha256": package_result["package_sha256"],
        "receipt_body_sha256": payload["public_launch_handoff_body_sha256"],
        "public_url_state": payload["public_url"]["state"],
    }


def _load_or_package_public_download_site(output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_path = output_dir / PUBLIC_SITE_PACKAGE_RECEIPT_NAME
    if receipt_path.is_file():
        try:
            package_receipt = verify_public_download_site_package_receipt_file(receipt_path)
        except Exception:  # noqa: BLE001 - stale packages are rebuilt below.
            package_receipt = {}
        else:
            package = _dict(package_receipt, "package")
            package_zip = output_dir / str(package.get("file", PUBLIC_SITE_PACKAGE_ZIP_NAME))
            return (
                {
                    "status": package_receipt.get("status"),
                    "verdict": package_receipt.get("verdict"),
                    "package_zip": str(package_zip),
                    "receipt_json": str(receipt_path),
                    "package_sha256": package.get("sha256"),
                    "receipt_body_sha256": package_receipt.get("public_download_site_package_receipt_body_sha256"),
                },
                package_receipt,
            )

    package_result = package_public_download_site(output_dir)
    package_receipt = verify_public_download_site_package_receipt_file(Path(package_result["receipt_json"]))
    return package_result, package_receipt


def verify_public_launch_handoff_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_launch_handoff_payload(payload)
    return payload


def verify_public_launch_handoff_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PUBLIC_LAUNCH_HANDOFF_SCHEMA_VERSION:
        raise PublicLaunchHandoffError("public launch handoff schema_version mismatch.")
    if payload.get("status") != "pass" or payload.get("verdict") != PUBLIC_LAUNCH_HANDOFF_VERDICT:
        raise PublicLaunchHandoffError("public launch handoff did not pass.")
    if payload.get("safe_to_share") is not True:
        raise PublicLaunchHandoffError("public launch handoff must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _handoff_checks(payload)
    if checks != recalculated:
        raise PublicLaunchHandoffError("public launch handoff checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicLaunchHandoffError("public launch handoff checks failed: " + ", ".join(failed))
    if payload.get("public_launch_handoff_body_sha256") != _handoff_body_sha256(payload):
        raise PublicLaunchHandoffError("public launch handoff body hash mismatch.")


def _handoff_payload(
    *,
    package_result: dict[str, Any],
    package_receipt: dict[str, Any],
) -> dict[str, Any]:
    package = _dict(package_receipt, "package")
    release = _dict(package_receipt, "release")
    package_sha256 = package_result.get("package_sha256")
    archive_sha256 = release.get("archive_sha256")
    verify_command = (
        "python scripts\\verify_external_alpha_public_download_site_url.py <PUBLIC_URL> "
        f"--expected-archive-sha256 {archive_sha256} "
        f"--receipt dist\\{DEFAULT_URL_RECEIPT_NAME}"
    )
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_LAUNCH_HANDOFF_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass",
        "verdict": PUBLIC_LAUNCH_HANDOFF_VERDICT,
        "safe_to_share": True,
        "launch_state": {
            "phase": "public_download_hosting",
            "public_url_ready": False,
            "public_url_state": "PENDING_PUBLIC_URL",
            "external_sharing_state": "BLOCKED_UNTIL_PUBLIC_URL_VERIFIED",
        },
        "package": {
            "zip_file": PUBLIC_SITE_PACKAGE_ZIP_NAME,
            "zip_sha256": package_sha256,
            "receipt_file": PUBLIC_SITE_PACKAGE_RECEIPT_NAME,
            "receipt_body_sha256": package_result.get("receipt_body_sha256"),
            "entry_count": package.get("entry_count"),
            "bytes": package.get("bytes"),
            "verdict": package_receipt.get("verdict"),
        },
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": archive_sha256,
            "file_count": release.get("file_count"),
        },
        "hosting": {
            "site_root_after_unzip": "web root",
            "entrypoint": "index.html",
            "required_support_files": [
                "_headers",
                NOJEKYLL_NAME,
                "robots.txt",
                "404.html",
                PUBLIC_HOSTING_RUNBOOK_NAME,
                PUBLIC_DOWNLOAD_ZIP_NAME,
                "cambrian-agent-platform-external-alpha.manifest.json",
                "external_alpha_release_verification_receipt.json",
            ],
            "operator_steps": [
                "Upload the public download site package ZIP to one static hosting target.",
                f"Unzip the package so index.html and {PUBLIC_DOWNLOAD_ZIP_NAME} are in the same web root.",
                "Open the hosted index.html URL in a browser.",
                "Run the URL verification command before sharing the URL externally.",
                "Share the URL only after the verifier returns PUBLIC_DOWNLOAD_SITE_URL_READY.",
            ],
        },
        "public_url": {
            "state": "PENDING_PUBLIC_URL",
            "placeholder": "<PUBLIC_URL>",
            "verify_command": verify_command,
            "expected_url_receipt": f"dist\\{DEFAULT_URL_RECEIPT_NAME}",
            "share_allowed_before_verify": False,
        },
        "policy": {
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
            "manual_send_gate_replaced": False,
            "fake_public_url_included": False,
        },
        "pm_judgment": (
            "The product is not truly launched until a hosted URL passes URL verification. "
            "The current artifact is the correct handoff for creating that URL."
        ),
    }
    payload["public_launch_handoff_body_sha256"] = _handoff_body_sha256(payload)
    payload["checks"] = _handoff_checks(payload)
    return payload


def _handoff_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    launch_state = _dict(payload, "launch_state")
    package = _dict(payload, "package")
    release = _dict(payload, "release")
    hosting = _dict(payload, "hosting")
    public_url = _dict(payload, "public_url")
    policy = _dict(payload, "policy")
    required_support_files = hosting.get("required_support_files")
    operator_steps = hosting.get("operator_steps")
    verify_command = public_url.get("verify_command", "")
    body_hash = payload.get("public_launch_handoff_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_LAUNCH_HANDOFF_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "verdict_ready": payload.get("verdict") == PUBLIC_LAUNCH_HANDOFF_VERDICT,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "public_url_pending": launch_state.get("public_url_ready") is False
        and launch_state.get("public_url_state") == "PENDING_PUBLIC_URL"
        and public_url.get("state") == "PENDING_PUBLIC_URL",
        "external_sharing_blocked_until_verified": launch_state.get("external_sharing_state")
        == "BLOCKED_UNTIL_PUBLIC_URL_VERIFIED"
        and public_url.get("share_allowed_before_verify") is False,
        "package_ready": package.get("zip_file") == PUBLIC_SITE_PACKAGE_ZIP_NAME
        and package.get("receipt_file") == PUBLIC_SITE_PACKAGE_RECEIPT_NAME
        and package.get("verdict") == PACKAGE_VERDICT,
        "package_hash_present": _looks_like_sha256(package.get("zip_sha256")),
        "package_receipt_hash_present": _looks_like_sha256(package.get("receipt_body_sha256")),
        "release_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "hosting_entrypoint_index": hosting.get("entrypoint") == "index.html",
        "support_files_named": isinstance(required_support_files, list)
        and {
            "_headers",
            NOJEKYLL_NAME,
            "robots.txt",
            "404.html",
            PUBLIC_HOSTING_RUNBOOK_NAME,
            PUBLIC_DOWNLOAD_ZIP_NAME,
        }.issubset(
            set(required_support_files)
        ),
        "operator_steps_complete": isinstance(operator_steps, list)
        and len(operator_steps) >= 5
        and any("URL verification" in step for step in operator_steps),
        "verify_command_uses_placeholder": isinstance(verify_command, str)
        and "<PUBLIC_URL>" in verify_command
        and "verify_external_alpha_public_download_site_url.py" in verify_command,
        "verify_command_pins_release_hash": isinstance(verify_command, str)
        and str(release.get("archive_sha256")) in verify_command,
        "url_receipt_named": public_url.get("expected_url_receipt") == f"dist\\{DEFAULT_URL_RECEIPT_NAME}",
        "manual_only_no_email_collection": policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "manual_gate_not_replaced": policy.get("manual_send_gate_replaced") is False,
        "no_fake_public_url": policy.get("fake_public_url_included") is False
        and "http://" not in serialized
        and "https://" not in serialized,
        "pm_judgment_present": isinstance(payload.get("pm_judgment"), str)
        and "not truly launched" in payload.get("pm_judgment", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _handoff_body_sha256(payload),
    }


def _handoff_markdown(payload: dict[str, Any]) -> str:
    package = _dict(payload, "package")
    release = _dict(payload, "release")
    public_url = _dict(payload, "public_url")
    hosting = _dict(payload, "hosting")
    steps = hosting.get("operator_steps") if isinstance(hosting.get("operator_steps"), list) else []
    step_lines = "\n".join(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    return f"""# Cambrian Public Download Launch Handoff

Verdict: `{payload["verdict"]}`

This handoff exists for one purpose: create a real public download URL without losing the package receipt, checksum discipline, or launch boundary.

## Package To Publish

```text
dist\\{package["zip_file"]}
```

Package ZIP sha256:

```text
{package["zip_sha256"]}
```

External alpha ZIP sha256:

```text
{release["archive_sha256"]}
```

## Operator Steps

{step_lines}

## Required Verification

After the public URL exists, run:

```text
{public_url["verify_command"]}
```

Expected URL receipt:

```text
{public_url["expected_url_receipt"]}
```

Do not share the public URL externally until the verifier returns `PUBLIC_DOWNLOAD_SITE_URL_READY`.

## Boundary

- This handoff does not collect email.
- This handoff does not require API keys.
- This handoff does not include private recipient/channel values.
- This handoff does not claim public traction or success metrics.
- This handoff does not replace the controlled first-recipient private send gate.
"""


def _assert_shareable_text(text: str) -> None:
    forbidden = [str(ROOT), str(Path.home()), ".env", "API key or secret", "raw private project files"]
    leaked = [item for item in forbidden if item and item in text]
    if leaked:
        raise PublicLaunchHandoffError("public launch handoff contains private material.")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicLaunchHandoffError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicLaunchHandoffError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicLaunchHandoffError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _handoff_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_launch_handoff_body_sha256", "checks"}
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
    parser = argparse.ArgumentParser(description="Prepare the public launch handoff for external alpha hosting.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--handoff-json", default=None)
    parser.add_argument("--handoff-md", default=None)
    parser.add_argument("--verify-handoff", default=None)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_handoff:
        try:
            payload = verify_public_launch_handoff_file(Path(args.verify_handoff))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public launch handoff verification: %s", exc)
            return 1
        logger.info("[PASS] external alpha public launch handoff verification")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("state  : %s", payload["public_url"]["state"])
        logger.info("body   : %s", payload["public_launch_handoff_body_sha256"])
        return 0

    try:
        result = prepare_public_launch_handoff(
            Path(args.output_dir),
            handoff_json=Path(args.handoff_json) if args.handoff_json else None,
            handoff_md=Path(args.handoff_md) if args.handoff_md else None,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing build failure.
        logger.error("[FAIL] external alpha public launch handoff: %s", exc)
        return 1

    logger.info("[PASS] external alpha public launch handoff")
    logger.info("verdict: %s", result["verdict"])
    logger.info("state  : %s", result["public_url_state"])
    logger.info("md     : %s", result["handoff_md"])
    logger.info("json   : %s", result["handoff_json"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
