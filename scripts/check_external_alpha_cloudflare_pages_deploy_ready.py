"""Check whether the public download site is ready for Cloudflare Pages deploy."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_public_deploy_candidate import (  # noqa: E402
    PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
    PUBLIC_DEPLOY_CANDIDATE_VERDICT,
    check_public_deploy_candidate,
    verify_public_deploy_candidate_receipt_file,
)
from scripts.package_external_alpha_public_download_site import (  # noqa: E402
    PUBLIC_SITE_PACKAGE_ZIP_NAME,
    PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME,
)
from scripts.prepare_external_alpha_public_download_site import INDEX_NAME, ZIP_NAME  # noqa: E402


CLOUDFLARE_PAGES_DEPLOY_READY_SCHEMA_VERSION = "external_alpha_cloudflare_pages_deploy_ready_v0_1"
CLOUDFLARE_PAGES_READY_VERDICT = "READY_TO_DEPLOY_WITH_WRANGLER"
CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT = "BLOCKED_AUTH_REQUIRED"
CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT = "BLOCKED_API_TOKEN_REQUIRED"
CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT = "BLOCKED_ACCOUNT_ID_REQUIRED"
CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT = "BLOCKED_WRANGLER_UNAVAILABLE"
CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME = f"{RELEASE_SLUG}-cloudflare-pages-deploy-ready.json"
DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME = "cambrian-alpha"
DEFAULT_CLOUDFLARE_PAGES_BRANCH = "main"
DEFAULT_WRANGLER_COMMAND = ("npx", "wrangler")
CLOUDFLARE_PAGES_TOKEN_RUNBOOK = "docs\\release\\CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md"

logger = logging.getLogger(__name__)

Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


class CloudflarePagesDeployReadyError(RuntimeError):
    """Cloudflare Pages deploy readiness check failed."""


def check_cloudflare_pages_deploy_ready(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    receipt_path: Path | None = None,
    project_name: str = DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME,
    branch: str = DEFAULT_CLOUDFLARE_PAGES_BRANCH,
    wrangler_command: tuple[str, ...] = DEFAULT_WRANGLER_COMMAND,
    timeout_seconds: float = 30.0,
    runner: Runner | None = None,
    api_token_present: bool | None = None,
    account_id_present: bool | None = None,
) -> dict[str, Any]:
    """Write a share-safe receipt for the Cloudflare Pages deploy preflight."""
    output_dir = output_dir.resolve()
    candidate = _load_or_build_public_deploy_candidate(output_dir)
    wrangler = _probe_wrangler(
        wrangler_command,
        timeout_seconds=timeout_seconds,
        runner=runner,
        api_token_present=api_token_present,
        account_id_present=account_id_present,
    )

    payload = _deploy_ready_payload(
        candidate=candidate,
        project_name=project_name,
        branch=branch,
        wrangler_command=wrangler_command,
        wrangler=wrangler,
    )
    receipt_path = (receipt_path or output_dir / CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_cloudflare_pages_deploy_ready_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "deploy_command": payload["cloudflare_pages"]["deploy_command"],
        "login_command": payload["cloudflare_pages"]["login_command"],
        "final_url_gate_command": payload["cloudflare_pages"]["final_url_gate_command"],
        "receipt_body_sha256": payload["cloudflare_pages_deploy_ready_body_sha256"],
    }


def verify_cloudflare_pages_deploy_ready_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_cloudflare_pages_deploy_ready_receipt_payload(payload, receipt_dir=path.resolve().parent)
    return payload


def verify_cloudflare_pages_deploy_ready_receipt_payload(
    payload: dict[str, Any],
    *,
    receipt_dir: Path | None = None,
) -> None:
    if payload.get("schema_version") != CLOUDFLARE_PAGES_DEPLOY_READY_SCHEMA_VERSION:
        raise CloudflarePagesDeployReadyError("cloudflare pages deploy readiness schema_version mismatch.")
    if payload.get("status") not in {"pass", "blocked"}:
        raise CloudflarePagesDeployReadyError("cloudflare pages deploy readiness status mismatch.")
    if payload.get("verdict") not in {
        CLOUDFLARE_PAGES_READY_VERDICT,
        CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT,
        CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
        CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
        CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
    }:
        raise CloudflarePagesDeployReadyError("cloudflare pages deploy readiness verdict mismatch.")
    if payload.get("safe_to_share") is not True:
        raise CloudflarePagesDeployReadyError("cloudflare pages deploy readiness must be safe_to_share.")
    if receipt_dir is not None:
        _verify_current_public_deploy_candidate(payload, receipt_dir)

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _deploy_ready_checks(payload, receipt_dir=receipt_dir)
    if checks != recalculated:
        raise CloudflarePagesDeployReadyError("cloudflare pages deploy readiness checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise CloudflarePagesDeployReadyError(
            "cloudflare pages deploy readiness checks failed: " + ", ".join(failed)
        )
    if payload.get("cloudflare_pages_deploy_ready_body_sha256") != _receipt_body_sha256(payload):
        raise CloudflarePagesDeployReadyError("cloudflare pages deploy readiness body hash mismatch.")


def _deploy_ready_payload(
    *,
    candidate: dict[str, Any],
    project_name: str,
    branch: str,
    wrangler_command: tuple[str, ...],
    wrangler: dict[str, Any],
) -> dict[str, Any]:
    candidate_release = _dict(candidate, "release")
    deploy_candidate = _dict(candidate, "deploy_candidate")
    archive_sha256 = candidate_release.get("archive_sha256")
    command_prefix = _command_string(wrangler_command)
    deploy_command = (
        f"{command_prefix} pages deploy dist\\{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME} "
        f"--project-name {project_name} --branch {branch}"
    )
    login_command = f"{command_prefix} login"
    final_url_gate_command = (
        "python scripts\\finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL> "
        f"--expected-archive-sha256 {archive_sha256} "
        " --receipt dist\\cambrian-agent-platform-external-alpha-public-launch-url-gate-receipt.json"
    )
    verdict = _wrangler_verdict(wrangler)
    payload: dict[str, Any] = {
        "schema_version": CLOUDFLARE_PAGES_DEPLOY_READY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if verdict == CLOUDFLARE_PAGES_READY_VERDICT else "blocked",
        "verdict": verdict,
        "safe_to_share": True,
        "launch_state": {
            "phase": "public_https_hosting",
            "public_url_ready": False,
            "external_sharing_allowed": False,
            "external_sharing_state": "BLOCKED_UNTIL_PUBLIC_LAUNCH_URL_GATE",
            "required_next_gate": "PUBLIC_LAUNCH_URL_READY",
        },
        "cloudflare_pages": {
            "host_class": "Cloudflare Pages direct upload",
            "project_name": project_name,
            "branch": branch,
            "deploy_directory_argument": f"dist\\{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}",
            "deploy_command": deploy_command,
            "login_command": login_command,
            "final_url_gate_command": final_url_gate_command,
            "required_success_signal": "wrangler pages deploy returns a public https://*.pages.dev URL",
            "noninteractive_credential_required": "CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID",
            "required_credential_env_vars": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"],
            "required_account_env_var": "CLOUDFLARE_ACCOUNT_ID",
            "recommended_account_env_var": "CLOUDFLARE_ACCOUNT_ID",
            "required_token_permission": "Account / Cloudflare Pages / Edit",
            "api_permission_alias": "Pages Write",
            "credential_runbook": CLOUDFLARE_PAGES_TOKEN_RUNBOOK,
        },
        "wrangler": wrangler,
        "public_deploy_candidate": {
            "receipt_file": PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
            "verdict": candidate.get("verdict"),
            "receipt_body_sha256": candidate.get("public_deploy_candidate_receipt_body_sha256"),
            "package_zip_file": deploy_candidate.get("package_zip_file"),
            "package_sha256": deploy_candidate.get("package_sha256"),
            "upload_root_directory": deploy_candidate.get("upload_root_directory"),
        },
        "release": {
            "zip_file": candidate_release.get("public_download_zip_file"),
            "archive_sha256": archive_sha256,
            "file_count": candidate_release.get("file_count"),
        },
        "site_contract": {
            "entrypoint": INDEX_NAME,
            "download_zip": ZIP_NAME,
            "upload_unit": f"{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}/ contents",
            "package_zip": PUBLIC_SITE_PACKAGE_ZIP_NAME,
        },
        "policy": {
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "proof_or_success_claims": False,
            "external_share_before_public_url_gate": False,
            "auth_output_redacted": True,
        },
        "operator_next_action": _operator_next_action(verdict),
        "pm_judgment": (
            "The release artifact is ready; the remaining launch bottleneck is public HTTPS hosting plus the URL gate."
        ),
    }
    payload["cloudflare_pages_deploy_ready_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _deploy_ready_checks(payload)
    return payload


def _probe_wrangler(
    wrangler_command: tuple[str, ...],
    *,
    timeout_seconds: float,
    runner: Runner | None,
    api_token_present: bool | None,
    account_id_present: bool | None,
) -> dict[str, Any]:
    runner = runner or _run_command
    token_present = bool(os.environ.get("CLOUDFLARE_API_TOKEN")) if api_token_present is None else api_token_present
    account_present = (
        bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID")) if account_id_present is None else account_id_present
    )
    version_command = [*wrangler_command, "--version"]
    version_result = _run_probe(runner, version_command, timeout_seconds)
    version = _extract_version(version_result.get("stdout", ""))
    version_available = version_result["returncode"] == 0 and version is not None

    whoami_result: dict[str, Any] | None = None
    authenticated = False
    auth_state = "not_checked_wrangler_unavailable"
    if version_available:
        whoami_command = [*wrangler_command, "whoami"]
        whoami_result = _run_probe(runner, whoami_command, timeout_seconds)
        authenticated = whoami_result["returncode"] == 0
        auth_state = "authenticated" if authenticated else "not_authenticated"

    return {
        "command_family": _command_string(wrangler_command),
        "version_checked": True,
        "version_available": version_available,
        "version": version,
        "auth_checked": version_available,
        "authenticated": authenticated,
        "auth_state": auth_state,
        "noninteractive_api_token_present": token_present,
        "noninteractive_deploy_credential_ready": token_present and account_present,
        "account_id_env_var_present": account_present,
        "account_id_required_for_direct_upload": True,
        "account_id_recommended_for_direct_upload": True,
        "version_probe_exit_code": version_result["returncode"],
        "whoami_probe_exit_code": None if whoami_result is None else whoami_result["returncode"],
        "raw_output_included": False,
    }


def _load_or_build_public_deploy_candidate(output_dir: Path) -> dict[str, Any]:
    candidate_receipt_path = output_dir / PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME
    if candidate_receipt_path.is_file():
        try:
            return verify_public_deploy_candidate_receipt_file(candidate_receipt_path)
        except Exception:  # noqa: BLE001 - stale candidates are rebuilt below.
            pass
    candidate_result = check_public_deploy_candidate(output_dir)
    return verify_public_deploy_candidate_receipt_file(Path(candidate_result["receipt_json"]))


def _run_probe(runner: Runner, command: list[str], timeout_seconds: float) -> dict[str, Any]:
    try:
        result = runner(command, timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": exc.__class__.__name__,
        }
    return {
        "returncode": int(result.returncode),
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }


def _run_command(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    resolved_command = list(command)
    resolved_executable = shutil.which(resolved_command[0])
    if resolved_executable:
        resolved_command[0] = resolved_executable
    return subprocess.run(
        resolved_command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )


def _wrangler_verdict(wrangler: dict[str, Any]) -> str:
    if wrangler.get("version_available") is not True:
        return CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT
    if wrangler.get("noninteractive_api_token_present") is not True:
        return CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT
    if wrangler.get("account_id_env_var_present") is not True:
        return CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT
    if wrangler.get("authenticated") is not True:
        return CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT
    return CLOUDFLARE_PAGES_READY_VERDICT


def _operator_next_action(verdict: str) -> str:
    if verdict == CLOUDFLARE_PAGES_READY_VERDICT:
        return (
            "Run the Cloudflare Pages deploy command, copy the returned public HTTPS URL, then run the final "
            "public launch URL gate before sharing externally."
        )
    if verdict == CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT:
        return (
            "Run the Wrangler login command, rerun this preflight, then deploy only after the verdict becomes "
            "READY_TO_DEPLOY_WITH_WRANGLER."
        )
    if verdict == CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT:
        return (
            "Set CLOUDFLARE_API_TOKEN for this non-interactive shell, rerun this preflight, then deploy only after "
            "the verdict becomes READY_TO_DEPLOY_WITH_WRANGLER."
        )
    if verdict == CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT:
        return (
            "Set CLOUDFLARE_ACCOUNT_ID for this non-interactive shell, rerun this preflight, then deploy only after "
            "the verdict becomes READY_TO_DEPLOY_WITH_WRANGLER."
        )
    return "Install or repair Wrangler/npx, rerun this preflight, then continue with login and deploy."


def _verify_current_public_deploy_candidate(payload: dict[str, Any], receipt_dir: Path) -> None:
    candidate_info = _dict(payload, "public_deploy_candidate")
    receipt_file = candidate_info.get("receipt_file")
    if receipt_file != PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME:
        raise CloudflarePagesDeployReadyError("cloudflare pages deploy readiness candidate receipt name mismatch.")
    try:
        verify_public_deploy_candidate_receipt_file(receipt_dir / PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME)
    except Exception as exc:  # noqa: BLE001 - normalize dependency errors for operator-facing verifier.
        raise CloudflarePagesDeployReadyError(f"public deploy candidate receipt invalid: {exc}") from exc


def _deploy_ready_checks(payload: dict[str, Any], *, receipt_dir: Path | None = None) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    launch_state = _dict(payload, "launch_state")
    cloudflare = _dict(payload, "cloudflare_pages")
    wrangler = _dict(payload, "wrangler")
    candidate = _dict(payload, "public_deploy_candidate")
    release = _dict(payload, "release")
    site_contract = _dict(payload, "site_contract")
    policy = _dict(payload, "policy")
    body_hash = payload.get("cloudflare_pages_deploy_ready_body_sha256")
    candidate_current = True
    if receipt_dir is not None:
        try:
            verify_public_deploy_candidate_receipt_file(receipt_dir / PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME)
        except Exception:  # noqa: BLE001 - represented as a boolean check.
            candidate_current = False
    return {
        "schema_version_present": payload.get("schema_version") == CLOUDFLARE_PAGES_DEPLOY_READY_SCHEMA_VERSION,
        "status_matches_verdict": (payload.get("status") == "pass")
        == (payload.get("verdict") == CLOUDFLARE_PAGES_READY_VERDICT),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "verdict_matches_wrangler_probe": payload.get("verdict") == _wrangler_verdict(wrangler),
        "external_share_blocked_until_url_gate": launch_state.get("external_sharing_allowed") is False
        and launch_state.get("external_sharing_state") == "BLOCKED_UNTIL_PUBLIC_LAUNCH_URL_GATE"
        and launch_state.get("required_next_gate") == "PUBLIC_LAUNCH_URL_READY",
        "cloudflare_project_named": cloudflare.get("project_name") == DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME
        or isinstance(cloudflare.get("project_name"), str)
        and len(cloudflare.get("project_name", "")) > 0,
        "deploy_command_targets_pages": isinstance(cloudflare.get("deploy_command"), str)
        and "wrangler pages deploy" in cloudflare.get("deploy_command", "")
        and f"dist\\{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}" in cloudflare.get("deploy_command", "")
        and f"--project-name {cloudflare.get('project_name')}" in cloudflare.get("deploy_command", "")
        and f"--branch {cloudflare.get('branch')}" in cloudflare.get("deploy_command", ""),
        "login_command_present": isinstance(cloudflare.get("login_command"), str)
        and "wrangler login" in cloudflare.get("login_command", ""),
        "credential_runbook_recorded": cloudflare.get("credential_runbook") == CLOUDFLARE_PAGES_TOKEN_RUNBOOK,
        "cloudflare_pages_token_permission_recorded": cloudflare.get("required_token_permission")
        == "Account / Cloudflare Pages / Edit"
        and cloudflare.get("api_permission_alias") == "Pages Write",
        "account_id_requirement_recorded": cloudflare.get("required_account_env_var")
        == "CLOUDFLARE_ACCOUNT_ID"
        and cloudflare.get("recommended_account_env_var") == "CLOUDFLARE_ACCOUNT_ID"
        and isinstance(cloudflare.get("required_credential_env_vars"), list)
        and "CLOUDFLARE_API_TOKEN" in cloudflare.get("required_credential_env_vars", [])
        and "CLOUDFLARE_ACCOUNT_ID" in cloudflare.get("required_credential_env_vars", [])
        and wrangler.get("account_id_required_for_direct_upload") is True
        and wrangler.get("account_id_recommended_for_direct_upload") is True
        and isinstance(wrangler.get("account_id_env_var_present"), bool),
        "final_url_gate_present": isinstance(cloudflare.get("final_url_gate_command"), str)
        and "finalize_external_alpha_public_launch_url.py <PUBLIC_HTTPS_URL>" in cloudflare.get(
            "final_url_gate_command", ""
        )
        and str(release.get("archive_sha256")) in cloudflare.get("final_url_gate_command", ""),
        "wrangler_output_redacted": wrangler.get("raw_output_included") is False,
        "wrangler_version_checked": wrangler.get("version_checked") is True,
        "noninteractive_api_token_state_recorded": isinstance(
            wrangler.get("noninteractive_api_token_present"), bool
        )
        and isinstance(wrangler.get("noninteractive_deploy_credential_ready"), bool),
        "wrangler_available_or_blocker_recorded": wrangler.get("version_available") is True
        or payload.get("verdict") == CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
        "wrangler_auth_ready_or_blocker_recorded": wrangler.get("authenticated") is True
        or payload.get("verdict")
        in {
            CLOUDFLARE_PAGES_AUTH_BLOCKED_VERDICT,
            CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
            CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
            CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
        },
        "noninteractive_token_ready_or_blocker_recorded": wrangler.get("noninteractive_api_token_present") is True
        or payload.get("verdict")
        in {CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT, CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT},
        "noninteractive_account_ready_or_blocker_recorded": wrangler.get("account_id_env_var_present") is True
        or payload.get("verdict")
        in {
            CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
            CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
            CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
        },
        "noninteractive_credentials_ready_or_blocker_recorded": wrangler.get(
            "noninteractive_deploy_credential_ready"
        )
        is True
        or payload.get("verdict")
        in {
            CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
            CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
            CLOUDFLARE_PAGES_WRANGLER_BLOCKED_VERDICT,
        },
        "public_deploy_candidate_current": candidate_current,
        "public_deploy_candidate_ready": candidate.get("verdict") == PUBLIC_DEPLOY_CANDIDATE_VERDICT
        and candidate.get("receipt_file") == PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
        "package_hash_present": _looks_like_sha256(candidate.get("package_sha256")),
        "release_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "release_zip_named": release.get("zip_file") == ZIP_NAME,
        "site_contract_names_index_and_zip": site_contract.get("entrypoint") == INDEX_NAME
        and site_contract.get("download_zip") == ZIP_NAME
        and site_contract.get("package_zip") == PUBLIC_SITE_PACKAGE_ZIP_NAME,
        "manual_only_no_email_collection": policy.get("page_collects_email") is False,
        "no_api_key_required": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and policy.get("auth_output_redacted") is True
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and len(payload.get("operator_next_action", "")) > 20,
        "pm_judgment_present": isinstance(payload.get("pm_judgment"), str)
        and "public HTTPS hosting" in payload.get("pm_judgment", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _extract_version(output: str) -> str | None:
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", output)
    return match.group(1) if match else None


def _command_string(command: tuple[str, ...]) -> str:
    return " ".join(command)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise CloudflarePagesDeployReadyError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise CloudflarePagesDeployReadyError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise CloudflarePagesDeployReadyError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "cloudflare_pages_deploy_ready_body_sha256", "checks"}
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


def _parse_command(value: str) -> tuple[str, ...]:
    parts = tuple(part for part in value.split(" ") if part)
    if not parts:
        raise CloudflarePagesDeployReadyError("wrangler command cannot be empty.")
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Cloudflare Pages deploy readiness for the external alpha.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--receipt", default=None)
    parser.add_argument("--verify-receipt", default=None)
    parser.add_argument("--project-name", default=DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME)
    parser.add_argument("--branch", default=DEFAULT_CLOUDFLARE_PAGES_BRANCH)
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
            payload = verify_cloudflare_pages_deploy_ready_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha cloudflare pages deploy readiness receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha cloudflare pages deploy readiness receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("share  : %s", payload["launch_state"]["external_sharing_allowed"])
        logger.info("body   : %s", payload["cloudflare_pages_deploy_ready_body_sha256"])
        return 0

    try:
        result = check_cloudflare_pages_deploy_ready(
            Path(args.output_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
            project_name=args.project_name,
            branch=args.branch,
            wrangler_command=_parse_command(args.wrangler_command),
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing check failure.
        logger.error("[FAIL] external alpha cloudflare pages deploy readiness: %s", exc)
        return 1

    prefix = "[PASS]" if result["verdict"] == CLOUDFLARE_PAGES_READY_VERDICT else "[BLOCKED]"
    logger.info("%s external alpha cloudflare pages deploy readiness", prefix)
    logger.info("verdict: %s", result["verdict"])
    logger.info("login  : %s", result["login_command"])
    logger.info("deploy : %s", result["deploy_command"])
    logger.info("gate   : %s", result["final_url_gate_command"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
