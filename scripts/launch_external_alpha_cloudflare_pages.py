"""Run the Cloudflare Pages launch path for the external alpha public site."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_cloudflare_pages_deploy_ready import (  # noqa: E402
    CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
    CLOUDFLARE_PAGES_READY_VERDICT,
    DEFAULT_CLOUDFLARE_PAGES_BRANCH,
    DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME,
    DEFAULT_WRANGLER_COMMAND,
    Runner,
    check_cloudflare_pages_deploy_ready,
    verify_cloudflare_pages_deploy_ready_receipt_file,
)
from scripts.finalize_external_alpha_public_launch_url import (  # noqa: E402
    PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
    PUBLIC_LAUNCH_URL_READY_VERDICT,
    finalize_public_launch_url,
)
from scripts.package_external_alpha_public_download_site import PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME  # noqa: E402
from scripts.prepare_external_alpha_public_share_packet import (  # noqa: E402
    PUBLIC_SHARE_PACKET_JSON_NAME,
    PUBLIC_SHARE_PACKET_MD_NAME,
    PUBLIC_SHARE_PACKET_VERDICT,
    prepare_public_share_packet,
)


CLOUDFLARE_PAGES_LAUNCH_SCHEMA_VERSION = "external_alpha_cloudflare_pages_launch_v0_1"
CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT = "CLOUDFLARE_PAGES_PUBLIC_LAUNCH_READY"
CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT = "BLOCKED_PREFLIGHT_NOT_READY"
CLOUDFLARE_PAGES_LAUNCH_PROJECT_CHECK_FAILED_VERDICT = "BLOCKED_PROJECT_CHECK_FAILED"
CLOUDFLARE_PAGES_LAUNCH_PROJECT_CREATE_FAILED_VERDICT = "BLOCKED_PROJECT_CREATE_FAILED"
CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT = "BLOCKED_DEPLOY_FAILED"
CLOUDFLARE_PAGES_LAUNCH_URL_NOT_FOUND_VERDICT = "BLOCKED_DEPLOY_PUBLIC_URL_NOT_FOUND"
CLOUDFLARE_PAGES_LAUNCH_URL_GATE_FAILED_VERDICT = "BLOCKED_PUBLIC_URL_GATE_FAILED"
CLOUDFLARE_PAGES_LAUNCH_SHARE_PACKET_FAILED_VERDICT = "BLOCKED_PUBLIC_SHARE_PACKET_FAILED"
CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME = f"{RELEASE_SLUG}-cloudflare-pages-launch-receipt.json"

logger = logging.getLogger(__name__)

DeployRunner = Callable[[list[str], float], subprocess.CompletedProcess[str]]
FinalizeFunc = Callable[..., dict[str, Any]]
SharePacketFunc = Callable[..., dict[str, Any]]


class CloudflarePagesLaunchError(RuntimeError):
    """Cloudflare Pages launch receipt generation or verification failed."""


def launch_cloudflare_pages(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    receipt_path: Path | None = None,
    project_name: str = DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME,
    branch: str = DEFAULT_CLOUDFLARE_PAGES_BRANCH,
    wrangler_command: tuple[str, ...] = DEFAULT_WRANGLER_COMMAND,
    preflight_timeout_seconds: float = 30.0,
    deploy_timeout_seconds: float = 300.0,
    url_gate_timeout_seconds: float = 30.0,
    preflight_runner: Runner | None = None,
    deploy_runner: DeployRunner | None = None,
    ensure_project: bool = True,
    api_token_present: bool | None = None,
    account_id_present: bool | None = None,
    finalize_func: FinalizeFunc = finalize_public_launch_url,
    prepare_share_packet: bool = True,
    share_packet_func: SharePacketFunc = prepare_public_share_packet,
) -> dict[str, Any]:
    """Deploy the public site to Cloudflare Pages and run the public URL gate."""
    output_dir = output_dir.resolve()
    preflight_receipt = output_dir / CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME
    preflight_result = check_cloudflare_pages_deploy_ready(
        output_dir,
        receipt_path=preflight_receipt,
        project_name=project_name,
        branch=branch,
        wrangler_command=wrangler_command,
        timeout_seconds=preflight_timeout_seconds,
        runner=preflight_runner,
        api_token_present=api_token_present,
        account_id_present=account_id_present,
    )
    preflight = verify_cloudflare_pages_deploy_ready_receipt_file(preflight_receipt)
    release = _dict(preflight, "release")
    deploy_command = _deploy_command(
        wrangler_command=wrangler_command,
        project_name=project_name,
        branch=branch,
    )

    deploy_result: dict[str, Any] | None = None
    project_result: dict[str, Any] | None = None
    url_gate: dict[str, Any] | None = None
    share_packet: dict[str, Any] | None = None
    public_url: str | None = None
    verdict = CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT
    status = "blocked"

    if preflight_result["verdict"] == CLOUDFLARE_PAGES_READY_VERDICT:
        runner = deploy_runner or _run_command
        if ensure_project:
            project_result = _ensure_pages_project(
                runner=runner,
                wrangler_command=wrangler_command,
                project_name=project_name,
                branch=branch,
                timeout_seconds=deploy_timeout_seconds,
            )
            if project_result["status"] != "ready":
                verdict = (
                    CLOUDFLARE_PAGES_LAUNCH_PROJECT_CHECK_FAILED_VERDICT
                    if project_result["status"] == "check_failed"
                    else CLOUDFLARE_PAGES_LAUNCH_PROJECT_CREATE_FAILED_VERDICT
                )
        else:
            project_result = {
                "ensure_project": False,
                "status": "skipped",
                "list_attempted": False,
                "list_exit_code": None,
                "project_present_before": None,
                "create_attempted": False,
                "create_exit_code": None,
                "project_ready": None,
                "output_redacted": True,
            }

        if verdict == CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT:
            completed = runner(deploy_command, deploy_timeout_seconds)
            public_url = _extract_pages_url((completed.stdout or "") + "\n" + (completed.stderr or ""))
            deploy_result = {
                "attempted": True,
                "exit_code": int(completed.returncode),
                "output_redacted": True,
                "public_https_url_detected": public_url is not None,
            }
            if completed.returncode != 0:
                verdict = CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT
            elif public_url is None:
                verdict = CLOUDFLARE_PAGES_LAUNCH_URL_NOT_FOUND_VERDICT
            else:
                try:
                    gate_result = finalize_func(
                        public_url,
                        output_dir,
                        expected_archive_sha256=release.get("archive_sha256"),
                        timeout_seconds=url_gate_timeout_seconds,
                        receipt_path=output_dir / PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
                    )
                except Exception as exc:  # noqa: BLE001 - keep launch receipt concise and redacted.
                    verdict = CLOUDFLARE_PAGES_LAUNCH_URL_GATE_FAILED_VERDICT
                    url_gate = {
                        "attempted": True,
                        "status": "failed",
                        "error_type": exc.__class__.__name__,
                        "error_message_redacted": True,
                    }
                else:
                    url_gate = {
                        "attempted": True,
                        "status": gate_result.get("status"),
                        "verdict": gate_result.get("verdict"),
                        "receipt_file": Path(str(gate_result.get("receipt_json", ""))).name,
                        "receipt_body_sha256": gate_result.get("receipt_body_sha256"),
                        "external_sharing_allowed": gate_result.get("external_sharing_allowed"),
                    }
                    if (
                        gate_result.get("verdict") == PUBLIC_LAUNCH_URL_READY_VERDICT
                        and gate_result.get("external_sharing_allowed") is True
                    ):
                        if prepare_share_packet:
                            try:
                                packet_result = share_packet_func(
                                    output_dir,
                                    gate_receipt=output_dir / PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
                                    packet_json=output_dir / PUBLIC_SHARE_PACKET_JSON_NAME,
                                    packet_md=output_dir / PUBLIC_SHARE_PACKET_MD_NAME,
                                )
                            except Exception as exc:  # noqa: BLE001 - keep launch receipt concise and redacted.
                                verdict = CLOUDFLARE_PAGES_LAUNCH_SHARE_PACKET_FAILED_VERDICT
                                share_packet = {
                                    "attempted": True,
                                    "status": "failed",
                                    "error_type": exc.__class__.__name__,
                                    "error_message_redacted": True,
                                    "verdict": None,
                                    "receipt_body_sha256": None,
                                }
                            else:
                                share_packet = {
                                    "attempted": True,
                                    "status": packet_result.get("status"),
                                    "verdict": packet_result.get("verdict"),
                                    "json_file": Path(str(packet_result.get("packet_json", ""))).name,
                                    "md_file": Path(str(packet_result.get("packet_md", ""))).name,
                                    "receipt_body_sha256": packet_result.get("receipt_body_sha256"),
                                }
                                if packet_result.get("verdict") == PUBLIC_SHARE_PACKET_VERDICT:
                                    status = "pass"
                                    verdict = CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
                                else:
                                    verdict = CLOUDFLARE_PAGES_LAUNCH_SHARE_PACKET_FAILED_VERDICT
                        else:
                            share_packet = {
                                "attempted": False,
                                "status": "skipped",
                                "verdict": None,
                                "json_file": PUBLIC_SHARE_PACKET_JSON_NAME,
                                "md_file": PUBLIC_SHARE_PACKET_MD_NAME,
                                "receipt_body_sha256": None,
                            }
                            status = "pass"
                            verdict = CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
                    else:
                        verdict = CLOUDFLARE_PAGES_LAUNCH_URL_GATE_FAILED_VERDICT
        else:
            deploy_result = {
                "attempted": False,
                "exit_code": None,
                "output_redacted": True,
                "public_https_url_detected": False,
            }
    else:
        project_result = {
            "ensure_project": ensure_project,
            "status": "not_checked_preflight_blocked",
            "list_attempted": False,
            "list_exit_code": None,
            "project_present_before": None,
            "create_attempted": False,
            "create_exit_code": None,
            "project_ready": False,
            "output_redacted": True,
        }
        deploy_result = {
            "attempted": False,
            "exit_code": None,
            "output_redacted": True,
            "public_https_url_detected": False,
        }

    payload = _launch_payload(
        preflight=preflight,
        status=status,
        verdict=verdict,
        deploy_command=deploy_command,
        project_result=project_result,
        deploy_result=deploy_result,
        url_gate=url_gate,
        share_packet=share_packet,
        public_url=public_url,
    )
    receipt_path = (receipt_path or output_dir / CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_cloudflare_pages_launch_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "public_url": payload["public_url"]["base_url"],
        "external_sharing_allowed": payload["launch_state"]["external_sharing_allowed"],
        "next_action": payload["operator_next_action"],
        "receipt_body_sha256": payload["cloudflare_pages_launch_receipt_body_sha256"],
    }


def verify_cloudflare_pages_launch_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_cloudflare_pages_launch_receipt_payload(payload, receipt_dir=path.resolve().parent)
    return payload


def verify_cloudflare_pages_launch_receipt_payload(
    payload: dict[str, Any],
    *,
    receipt_dir: Path | None = None,
) -> None:
    if payload.get("schema_version") != CLOUDFLARE_PAGES_LAUNCH_SCHEMA_VERSION:
        raise CloudflarePagesLaunchError("cloudflare pages launch schema_version mismatch.")
    if payload.get("status") not in {"pass", "blocked"}:
        raise CloudflarePagesLaunchError("cloudflare pages launch status mismatch.")
    if payload.get("verdict") not in {
        CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT,
        CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT,
        CLOUDFLARE_PAGES_LAUNCH_PROJECT_CHECK_FAILED_VERDICT,
        CLOUDFLARE_PAGES_LAUNCH_PROJECT_CREATE_FAILED_VERDICT,
        CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT,
        CLOUDFLARE_PAGES_LAUNCH_URL_NOT_FOUND_VERDICT,
        CLOUDFLARE_PAGES_LAUNCH_URL_GATE_FAILED_VERDICT,
        CLOUDFLARE_PAGES_LAUNCH_SHARE_PACKET_FAILED_VERDICT,
    }:
        raise CloudflarePagesLaunchError("cloudflare pages launch verdict mismatch.")
    if payload.get("safe_to_share") is not True:
        raise CloudflarePagesLaunchError("cloudflare pages launch receipt must be safe_to_share.")
    if receipt_dir is not None:
        _verify_current_preflight(payload, receipt_dir)

    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _launch_checks(payload, receipt_dir=receipt_dir)
    if checks != recalculated:
        raise CloudflarePagesLaunchError("cloudflare pages launch checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise CloudflarePagesLaunchError("cloudflare pages launch checks failed: " + ", ".join(failed))
    if payload.get("cloudflare_pages_launch_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise CloudflarePagesLaunchError("cloudflare pages launch body hash mismatch.")


def _launch_payload(
    *,
    preflight: dict[str, Any],
    status: str,
    verdict: str,
    deploy_command: list[str],
    project_result: dict[str, Any] | None,
    deploy_result: dict[str, Any] | None,
    url_gate: dict[str, Any] | None,
    share_packet: dict[str, Any] | None,
    public_url: str | None,
) -> dict[str, Any]:
    release = _dict(preflight, "release")
    external_sharing_allowed = verdict == CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
    payload: dict[str, Any] = {
        "schema_version": CLOUDFLARE_PAGES_LAUNCH_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "verdict": verdict,
        "safe_to_share": True,
        "launch_state": {
            "phase": "cloudflare_pages_public_launch",
            "public_url_ready": external_sharing_allowed,
            "share_packet_ready": external_sharing_allowed,
            "external_sharing_allowed": external_sharing_allowed,
            "external_sharing_state": "PUBLIC_URL_VERIFIED" if external_sharing_allowed else "BLOCKED",
        },
        "cloudflare_pages": {
            "deploy_command": _command_string(tuple(deploy_command)),
            "deploy_directory_argument": f"dist\\{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}",
            "output_redacted": True,
        },
        "preflight": {
            "receipt_file": CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
            "verdict": preflight.get("verdict"),
            "receipt_body_sha256": preflight.get("cloudflare_pages_deploy_ready_body_sha256"),
        },
        "preflight_blocker": _preflight_blocker_summary(preflight),
        "project": project_result
        or {
            "ensure_project": True,
            "status": "unknown",
            "list_attempted": False,
            "list_exit_code": None,
            "project_present_before": None,
            "create_attempted": False,
            "create_exit_code": None,
            "project_ready": False,
            "output_redacted": True,
        },
        "deploy_result": deploy_result or {
            "attempted": False,
            "exit_code": None,
            "output_redacted": True,
            "public_https_url_detected": False,
        },
        "public_url": {
            "base_url": public_url,
            "scheme": urllib.parse.urlparse(public_url).scheme if public_url else None,
            "host": urllib.parse.urlparse(public_url).hostname if public_url else None,
        },
        "url_gate": url_gate
        or {
            "attempted": False,
            "status": None,
            "verdict": None,
            "receipt_file": PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
            "receipt_body_sha256": None,
            "external_sharing_allowed": False,
        },
        "share_packet": share_packet
        or {
            "attempted": False,
            "status": None,
            "verdict": None,
            "json_file": PUBLIC_SHARE_PACKET_JSON_NAME,
            "md_file": PUBLIC_SHARE_PACKET_MD_NAME,
            "receipt_body_sha256": None,
        },
        "release": {
            "zip_file": release.get("zip_file"),
            "archive_sha256": release.get("archive_sha256"),
            "file_count": release.get("file_count"),
        },
        "policy": {
            "page_collects_email": False,
            "requires_api_key": False,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "deploy_output_included": False,
            "proof_or_success_claims": False,
            "external_share_before_public_url_gate": False,
        },
        "operator_next_action": _operator_next_action(verdict, preflight=preflight),
        "pm_judgment": (
            "Launch is complete only when Cloudflare deploy succeeds and the hosted URL passes the downloaded ZIP gate."
        ),
    }
    payload["cloudflare_pages_launch_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _launch_checks(payload)
    return payload


def _launch_checks(payload: dict[str, Any], *, receipt_dir: Path | None = None) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    launch_state = _dict(payload, "launch_state")
    cloudflare = _dict(payload, "cloudflare_pages")
    preflight = _dict(payload, "preflight")
    preflight_blocker = _dict(payload, "preflight_blocker")
    deploy_result = _dict(payload, "deploy_result")
    project = _dict(payload, "project")
    public_url = _dict(payload, "public_url")
    url_gate = _dict(payload, "url_gate")
    share_packet = _dict(payload, "share_packet")
    release = _dict(payload, "release")
    policy = _dict(payload, "policy")
    body_hash = payload.get("cloudflare_pages_launch_receipt_body_sha256")
    is_ready = payload.get("verdict") == CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
    preflight_current = True
    if receipt_dir is not None:
        try:
            verify_cloudflare_pages_deploy_ready_receipt_file(receipt_dir / CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME)
        except Exception:  # noqa: BLE001 - represented as a boolean check.
            preflight_current = False
    return {
        "schema_version_present": payload.get("schema_version") == CLOUDFLARE_PAGES_LAUNCH_SCHEMA_VERSION,
        "status_matches_verdict": (payload.get("status") == "pass") == is_ready,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "launch_state_matches_verdict": launch_state.get("public_url_ready") is is_ready
        and launch_state.get("share_packet_ready") is is_ready
        and launch_state.get("external_sharing_allowed") is is_ready,
        "external_share_only_after_url_gate": (is_ready and url_gate.get("external_sharing_allowed") is True)
        or (not is_ready and launch_state.get("external_sharing_allowed") is False),
        "preflight_current": preflight_current,
        "preflight_receipt_ready_or_blocked": preflight.get("receipt_file") == CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME
        and _looks_like_sha256(preflight.get("receipt_body_sha256")),
        "preflight_blocker_summary_recorded": preflight_blocker.get("receipt_file")
        == CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME
        and preflight_blocker.get("verdict") == preflight.get("verdict"),
        "preflight_blocker_names_missing_credentials": preflight.get("verdict")
        not in {CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT, CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT}
        or (
            isinstance(preflight_blocker.get("missing_credential_env_vars"), list)
            and len(preflight_blocker.get("missing_credential_env_vars", [])) > 0
            and all(isinstance(item, str) for item in preflight_blocker.get("missing_credential_env_vars", []))
        ),
        "preflight_blocker_redacted": preflight_blocker.get("raw_private_values_included") is False,
        "ready_requires_ready_preflight": (not is_ready)
        or preflight.get("verdict") == CLOUDFLARE_PAGES_READY_VERDICT,
        "project_output_redacted": project.get("output_redacted") is True,
        "project_ready_before_deploy": (
            preflight.get("verdict") != CLOUDFLARE_PAGES_READY_VERDICT
            and project.get("list_attempted") is False
        )
        or (
            preflight.get("verdict") == CLOUDFLARE_PAGES_READY_VERDICT
            and deploy_result.get("attempted") is True
            and project.get("project_ready") is True
        )
        or (
            preflight.get("verdict") == CLOUDFLARE_PAGES_READY_VERDICT
            and deploy_result.get("attempted") is False
            and project.get("project_ready") is not True
        ),
        "deploy_command_targets_public_site": isinstance(cloudflare.get("deploy_command"), str)
        and "wrangler pages deploy" in cloudflare.get("deploy_command", "")
        and f"dist\\{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}" in cloudflare.get("deploy_command", ""),
        "deploy_output_redacted": cloudflare.get("output_redacted") is True
        and deploy_result.get("output_redacted") is True,
        "deploy_attempt_matches_preflight": (
            preflight.get("verdict") == CLOUDFLARE_PAGES_READY_VERDICT
            and deploy_result.get("attempted") is True
            and project.get("project_ready") is True
        )
        or (
            preflight.get("verdict") == CLOUDFLARE_PAGES_READY_VERDICT
            and deploy_result.get("attempted") is False
            and project.get("project_ready") is not True
        )
        or (
            preflight.get("verdict") != CLOUDFLARE_PAGES_READY_VERDICT
            and deploy_result.get("attempted") is False
        ),
        "public_url_https_when_ready": (not is_ready)
        or (
            isinstance(public_url.get("base_url"), str)
            and public_url.get("scheme") == "https"
            and isinstance(public_url.get("host"), str)
            and public_url.get("host", "").endswith(".pages.dev")
        ),
        "url_gate_ready_when_launch_ready": (not is_ready)
        or (
            url_gate.get("verdict") == PUBLIC_LAUNCH_URL_READY_VERDICT
            and url_gate.get("external_sharing_allowed") is True
            and _looks_like_sha256(url_gate.get("receipt_body_sha256"))
        ),
        "share_packet_ready_when_launch_ready": (not is_ready)
        or (
            share_packet.get("verdict") == PUBLIC_SHARE_PACKET_VERDICT
            and share_packet.get("json_file") == PUBLIC_SHARE_PACKET_JSON_NAME
            and share_packet.get("md_file") == PUBLIC_SHARE_PACKET_MD_NAME
            and _looks_like_sha256(share_packet.get("receipt_body_sha256"))
        ),
        "release_hash_present": _looks_like_sha256(release.get("archive_sha256")),
        "manual_only_no_email_collection": policy.get("page_collects_email") is False,
        "no_api_key_required_by_site": policy.get("requires_api_key") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and policy.get("deploy_output_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("proof_or_success_claims") is False,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and len(payload.get("operator_next_action", "")) > 20,
        "pm_judgment_present": isinstance(payload.get("pm_judgment"), str)
        and "hosted URL passes" in payload.get("pm_judgment", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _verify_current_preflight(payload: dict[str, Any], receipt_dir: Path) -> None:
    preflight = _dict(payload, "preflight")
    if preflight.get("receipt_file") != CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME:
        raise CloudflarePagesLaunchError("cloudflare pages launch preflight receipt name mismatch.")
    try:
        verify_cloudflare_pages_deploy_ready_receipt_file(receipt_dir / CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME)
    except Exception as exc:  # noqa: BLE001 - normalize dependency errors for operator-facing verifier.
        raise CloudflarePagesLaunchError(f"cloudflare pages preflight receipt invalid: {exc}") from exc


def _deploy_command(
    *,
    wrangler_command: tuple[str, ...],
    project_name: str,
    branch: str,
) -> list[str]:
    return [
        *wrangler_command,
        "pages",
        "deploy",
        f"dist\\{PUBLIC_SITE_UPLOAD_ROOT_DIR_NAME}",
        "--project-name",
        project_name,
        "--branch",
        branch,
    ]


def _ensure_pages_project(
    *,
    runner: DeployRunner,
    wrangler_command: tuple[str, ...],
    project_name: str,
    branch: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    list_command = [*wrangler_command, "pages", "project", "list", "--json"]
    list_result = runner(list_command, timeout_seconds)
    project_names = _extract_project_names(list_result.stdout or "")
    if list_result.returncode != 0:
        return {
            "ensure_project": True,
            "status": "check_failed",
            "list_attempted": True,
            "list_exit_code": int(list_result.returncode),
            "project_present_before": None,
            "create_attempted": False,
            "create_exit_code": None,
            "project_ready": False,
            "output_redacted": True,
        }
    if project_name in project_names:
        return {
            "ensure_project": True,
            "status": "ready",
            "list_attempted": True,
            "list_exit_code": 0,
            "project_present_before": True,
            "create_attempted": False,
            "create_exit_code": None,
            "project_ready": True,
            "output_redacted": True,
        }

    create_command = [
        *wrangler_command,
        "pages",
        "project",
        "create",
        project_name,
        "--production-branch",
        branch,
    ]
    create_result = runner(create_command, timeout_seconds)
    return {
        "ensure_project": True,
        "status": "ready" if create_result.returncode == 0 else "create_failed",
        "list_attempted": True,
        "list_exit_code": 0,
        "project_present_before": False,
        "create_attempted": True,
        "create_exit_code": int(create_result.returncode),
        "project_ready": create_result.returncode == 0,
        "output_redacted": True,
    }


def _extract_project_names(output: str) -> set[str]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return set()
    items = payload if isinstance(payload, list) else payload.get("result") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return set()
    names: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("name", "project_name", "projectName"):
            value = item.get(key)
            if isinstance(value, str) and value:
                names.add(value)
    return names


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


def _extract_pages_url(output: str) -> str | None:
    for match in re.findall(r"https://[^\s\]\)\"']+", output):
        candidate = match.rstrip(".,;")
        parsed = urllib.parse.urlparse(candidate)
        if parsed.scheme == "https" and (parsed.hostname or "").endswith(".pages.dev"):
            return candidate
    return None


def _operator_next_action(verdict: str, *, preflight: dict[str, Any] | None = None) -> str:
    if verdict == CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT:
        return "Share the verified public HTTPS URL externally with the generated public share packet attached."
    if verdict == CLOUDFLARE_PAGES_LAUNCH_BLOCKED_PREFLIGHT_VERDICT:
        missing = _missing_cloudflare_credentials(preflight)
        if missing:
            return (
                "Set "
                + " and ".join(missing)
                + " in this shell, then rerun this launch runner. See "
                + str(_dict(preflight, "cloudflare_pages").get("credential_runbook", "docs\\release\\CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md"))
                + "."
            )
        preflight_action = preflight.get("operator_next_action") if isinstance(preflight, dict) else None
        if isinstance(preflight_action, str) and preflight_action:
            return f"Resolve the Cloudflare Pages preflight blocker: {preflight_action}"
        return "Resolve the Cloudflare Pages preflight blocker, then rerun this launch runner."
    if verdict == CLOUDFLARE_PAGES_LAUNCH_PROJECT_CHECK_FAILED_VERDICT:
        return "Fix Cloudflare Pages project listing access, then rerun this launch runner."
    if verdict == CLOUDFLARE_PAGES_LAUNCH_PROJECT_CREATE_FAILED_VERDICT:
        return "Create the Cloudflare Pages project manually or fix project creation permissions, then rerun this launch runner."
    if verdict == CLOUDFLARE_PAGES_LAUNCH_DEPLOY_FAILED_VERDICT:
        return "Inspect the local Wrangler log, fix the deploy failure, then rerun this launch runner."
    if verdict == CLOUDFLARE_PAGES_LAUNCH_URL_NOT_FOUND_VERDICT:
        return "Find the public Pages URL in the Cloudflare dashboard, then run the final public URL gate manually."
    if verdict == CLOUDFLARE_PAGES_LAUNCH_SHARE_PACKET_FAILED_VERDICT:
        return "Prepare the public share packet manually before sharing any public URL externally."
    return "Fix the hosted URL gate failure before sharing any public URL externally."


def _preflight_blocker_summary(preflight: dict[str, Any]) -> dict[str, Any]:
    cloudflare = _dict(preflight, "cloudflare_pages")
    wrangler = _dict(preflight, "wrangler")
    return {
        "receipt_file": CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
        "verdict": preflight.get("verdict"),
        "status": preflight.get("status"),
        "credential_runbook": cloudflare.get("credential_runbook"),
        "required_credential_env_vars": _required_cloudflare_credentials(preflight),
        "missing_credential_env_vars": _missing_cloudflare_credentials(preflight),
        "noninteractive_deploy_credential_ready": wrangler.get("noninteractive_deploy_credential_ready"),
        "api_token_present": wrangler.get("noninteractive_api_token_present"),
        "account_id_present": wrangler.get("account_id_env_var_present"),
        "operator_next_action": preflight.get("operator_next_action"),
        "raw_private_values_included": False,
    }


def _required_cloudflare_credentials(preflight: dict[str, Any] | None) -> list[str]:
    cloudflare = _dict(preflight, "cloudflare_pages")
    value = cloudflare.get("required_credential_env_vars")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]


def _missing_cloudflare_credentials(preflight: dict[str, Any] | None) -> list[str]:
    if not isinstance(preflight, dict):
        return []
    wrangler = _dict(preflight, "wrangler")
    missing: list[str] = []
    if wrangler.get("noninteractive_api_token_present") is not True:
        missing.append("CLOUDFLARE_API_TOKEN")
    if wrangler.get("account_id_env_var_present") is not True:
        missing.append("CLOUDFLARE_ACCOUNT_ID")
    return missing


def _command_string(command: tuple[str, ...]) -> str:
    return " ".join(command)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise CloudflarePagesLaunchError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise CloudflarePagesLaunchError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise CloudflarePagesLaunchError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "cloudflare_pages_launch_receipt_body_sha256", "checks"}
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
        raise CloudflarePagesLaunchError("wrangler command cannot be empty.")
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the external alpha public site through Cloudflare Pages.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--receipt", default=None)
    parser.add_argument("--verify-receipt", default=None)
    parser.add_argument("--project-name", default=DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME)
    parser.add_argument("--branch", default=DEFAULT_CLOUDFLARE_PAGES_BRANCH)
    parser.add_argument("--wrangler-command", default=_command_string(DEFAULT_WRANGLER_COMMAND))
    parser.add_argument("--preflight-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--deploy-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--url-gate-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--skip-project-ensure", action="store_true")
    parser.add_argument("--skip-share-packet", action="store_true")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.verify_receipt:
        try:
            payload = verify_cloudflare_pages_launch_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha cloudflare pages launch receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha cloudflare pages launch receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("share  : %s", payload["launch_state"]["external_sharing_allowed"])
        logger.info("url    : %s", payload["public_url"]["base_url"])
        logger.info("next   : %s", payload["operator_next_action"])
        logger.info("body   : %s", payload["cloudflare_pages_launch_receipt_body_sha256"])
        return 0

    try:
        result = launch_cloudflare_pages(
            Path(args.output_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
            project_name=args.project_name,
            branch=args.branch,
            wrangler_command=_parse_command(args.wrangler_command),
            preflight_timeout_seconds=args.preflight_timeout_seconds,
            deploy_timeout_seconds=args.deploy_timeout_seconds,
            url_gate_timeout_seconds=args.url_gate_timeout_seconds,
            ensure_project=not args.skip_project_ensure,
            prepare_share_packet=not args.skip_share_packet,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing launch failure.
        logger.error("[FAIL] external alpha cloudflare pages launch: %s", exc)
        return 1

    prefix = "[PASS]" if result["status"] == "pass" else "[BLOCKED]"
    logger.info("%s external alpha cloudflare pages launch", prefix)
    logger.info("verdict: %s", result["verdict"])
    logger.info("share  : %s", result["external_sharing_allowed"])
    logger.info("url    : %s", result["public_url"])
    logger.info("next   : %s", result["next_action"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
