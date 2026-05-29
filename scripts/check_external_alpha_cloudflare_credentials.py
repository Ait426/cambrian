"""Check Cloudflare credentials without deploying the public site."""

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
from scripts.check_external_alpha_cloudflare_pages_deploy_ready import (  # noqa: E402
    CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_READY_VERDICT,
    CLOUDFLARE_PAGES_TOKEN_RUNBOOK,
    CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
    DEFAULT_WRANGLER_COMMAND,
    Runner,
    _command_string,
    _parse_command,
    _probe_wrangler,
    _wrangler_verdict,
)


CLOUDFLARE_CREDENTIALS_SCHEMA_VERSION = "external_alpha_cloudflare_credentials_v0_1"
CLOUDFLARE_CREDENTIALS_READY_VERDICT = "CLOUDFLARE_CREDENTIALS_READY"
CLOUDFLARE_CREDENTIALS_RECEIPT_NAME = f"{RELEASE_SLUG}-cloudflare-credentials-receipt.json"
REQUIRED_CLOUDFLARE_ENV_VARS = ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]

logger = logging.getLogger(__name__)


class CloudflareCredentialsError(RuntimeError):
    """Cloudflare credential readiness receipt failed validation."""


def check_cloudflare_credentials(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    receipt_path: Path | None = None,
    wrangler_command: tuple[str, ...] = DEFAULT_WRANGLER_COMMAND,
    timeout_seconds: float = 30.0,
    runner: Runner | None = None,
    api_token_present: bool | None = None,
    account_id_present: bool | None = None,
) -> dict[str, Any]:
    """Write a share-safe credential-only receipt for Cloudflare Pages launch."""
    output_dir = output_dir.resolve()
    wrangler = _probe_wrangler(
        wrangler_command,
        timeout_seconds=timeout_seconds,
        runner=runner,
        api_token_present=api_token_present,
        account_id_present=account_id_present,
    )
    payload = _credentials_payload(wrangler=wrangler, wrangler_command=wrangler_command)
    receipt_path = (receipt_path or output_dir / CLOUDFLARE_CREDENTIALS_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_cloudflare_credentials_receipt_file(receipt_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "missing_env_vars": payload["credentials"]["missing_env_vars"],
        "next_action": payload["operator_next_action"],
        "receipt_body_sha256": payload["cloudflare_credentials_body_sha256"],
    }


def verify_cloudflare_credentials_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_cloudflare_credentials_receipt_payload(payload)
    return payload


def verify_cloudflare_credentials_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != CLOUDFLARE_CREDENTIALS_SCHEMA_VERSION:
        raise CloudflareCredentialsError("cloudflare credentials schema_version mismatch.")
    if payload.get("status") not in {"pass", "blocked"}:
        raise CloudflareCredentialsError("cloudflare credentials status mismatch.")
    if payload.get("verdict") not in {
        CLOUDFLARE_CREDENTIALS_READY_VERDICT,
        CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
        CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
        CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT,
        CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
    }:
        raise CloudflareCredentialsError("cloudflare credentials verdict mismatch.")
    if payload.get("safe_to_share") is not True:
        raise CloudflareCredentialsError("cloudflare credentials receipt must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _credential_checks(payload)
    if checks != recalculated:
        raise CloudflareCredentialsError("cloudflare credentials checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise CloudflareCredentialsError("cloudflare credentials checks failed: " + ", ".join(failed))
    if payload.get("cloudflare_credentials_body_sha256") != _receipt_body_sha256(payload):
        raise CloudflareCredentialsError("cloudflare credentials body hash mismatch.")


def _credentials_payload(*, wrangler: dict[str, Any], wrangler_command: tuple[str, ...]) -> dict[str, Any]:
    preflight_verdict = _wrangler_verdict(wrangler)
    verdict = (
        CLOUDFLARE_CREDENTIALS_READY_VERDICT
        if preflight_verdict == CLOUDFLARE_PAGES_READY_VERDICT
        else preflight_verdict
    )
    missing = _missing_env_vars(wrangler)
    payload: dict[str, Any] = {
        "schema_version": CLOUDFLARE_CREDENTIALS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if verdict == CLOUDFLARE_CREDENTIALS_READY_VERDICT else "blocked",
        "verdict": verdict,
        "safe_to_share": True,
        "credentials": {
            "required_env_vars": REQUIRED_CLOUDFLARE_ENV_VARS,
            "missing_env_vars": missing,
            "noninteractive_deploy_credential_ready": wrangler.get("noninteractive_deploy_credential_ready"),
            "api_token_present": wrangler.get("noninteractive_api_token_present"),
            "account_id_present": wrangler.get("account_id_env_var_present"),
            "credential_runbook": CLOUDFLARE_PAGES_TOKEN_RUNBOOK,
        },
        "wrangler": {
            "command_family": _command_string(wrangler_command),
            "version_checked": wrangler.get("version_checked"),
            "version_available": wrangler.get("version_available"),
            "version": wrangler.get("version"),
            "auth_checked": wrangler.get("auth_checked"),
            "authenticated": wrangler.get("authenticated"),
            "auth_state": wrangler.get("auth_state"),
            "raw_output_included": False,
        },
        "policy": {
            "does_not_deploy": True,
            "does_not_create_project": True,
            "does_not_share_url": True,
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "operator_next_action": _operator_next_action(verdict, missing),
        "pm_judgment": (
            "This gate only checks Cloudflare credential readiness; deploy remains blocked until the launch runner "
            "and public URL gate pass."
        ),
    }
    payload["cloudflare_credentials_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _credential_checks(payload)
    return payload


def _credential_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    credentials = _dict(payload, "credentials")
    wrangler = _dict(payload, "wrangler")
    policy = _dict(payload, "policy")
    body_hash = payload.get("cloudflare_credentials_body_sha256")
    is_ready = payload.get("verdict") == CLOUDFLARE_CREDENTIALS_READY_VERDICT
    return {
        "schema_version_present": payload.get("schema_version") == CLOUDFLARE_CREDENTIALS_SCHEMA_VERSION,
        "status_matches_verdict": (payload.get("status") == "pass") == is_ready,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "required_env_vars_recorded": credentials.get("required_env_vars") == REQUIRED_CLOUDFLARE_ENV_VARS,
        "missing_env_vars_recorded": isinstance(credentials.get("missing_env_vars"), list)
        and all(isinstance(item, str) for item in credentials.get("missing_env_vars", [])),
        "ready_requires_no_missing_env_vars": (not is_ready) or credentials.get("missing_env_vars") == [],
        "credential_runbook_recorded": credentials.get("credential_runbook") == CLOUDFLARE_PAGES_TOKEN_RUNBOOK,
        "wrangler_output_redacted": wrangler.get("raw_output_included") is False,
        "wrangler_version_state_recorded": isinstance(wrangler.get("version_available"), bool),
        "wrangler_auth_state_recorded": isinstance(wrangler.get("authenticated"), bool),
        "credential_values_not_recorded": "cloudflare-pages-edit-token" not in serialized
        and "<cloudflare-pages-edit-token>" not in serialized
        and "account-id" not in serialized.lower(),
        "credential_gate_is_no_deploy": policy.get("does_not_deploy") is True
        and policy.get("does_not_create_project") is True
        and policy.get("does_not_share_url") is True,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and len(payload.get("operator_next_action", "")) > 20,
        "pm_judgment_present": isinstance(payload.get("pm_judgment"), str)
        and "credential readiness" in payload.get("pm_judgment", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _operator_next_action(verdict: str, missing: list[str]) -> str:
    if verdict == CLOUDFLARE_CREDENTIALS_READY_VERDICT:
        return (
            "Run python scripts\\launch_external_alpha_cloudflare_pages.py --receipt "
            "dist\\cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json."
        )
    if missing:
        return (
            "Set "
            + " and ".join(missing)
            + " in this shell, then rerun this credential check. See "
            + CLOUDFLARE_PAGES_TOKEN_RUNBOOK
            + "."
        )
    if verdict == CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT:
        return "Run npx wrangler login or fix the API token, then rerun this credential check."
    return "Install or repair Wrangler/npx, then rerun this credential check."


def _missing_env_vars(wrangler: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if wrangler.get("noninteractive_api_token_present") is not True:
        missing.append("CLOUDFLARE_API_TOKEN")
    if wrangler.get("account_id_env_var_present") is not True:
        missing.append("CLOUDFLARE_ACCOUNT_ID")
    return missing


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise CloudflareCredentialsError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise CloudflareCredentialsError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise CloudflareCredentialsError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "cloudflare_credentials_body_sha256", "checks"}
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
    parser = argparse.ArgumentParser(description="Check Cloudflare credentials for the external alpha public launch.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--receipt", default=None)
    parser.add_argument("--verify-receipt", default=None)
    parser.add_argument("--wrangler-command", default=_command_string(DEFAULT_WRANGLER_COMMAND))
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_cloudflare_credentials_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha cloudflare credentials receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha cloudflare credentials receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("missing: %s", ", ".join(payload["credentials"]["missing_env_vars"]) or "none")
        logger.info("next   : %s", payload["operator_next_action"])
        logger.info("body   : %s", payload["cloudflare_credentials_body_sha256"])
        return 0

    try:
        result = check_cloudflare_credentials(
            Path(args.output_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
            wrangler_command=_parse_command(args.wrangler_command),
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing check failure.
        logger.error("[FAIL] external alpha cloudflare credentials: %s", exc)
        return 1

    prefix = "[PASS]" if result["status"] == "pass" else "[BLOCKED]"
    logger.info("%s external alpha cloudflare credentials", prefix)
    logger.info("verdict: %s", result["verdict"])
    logger.info("missing: %s", ", ".join(result["missing_env_vars"]) or "none")
    logger.info("next   : %s", result["next_action"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
