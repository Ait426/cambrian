"""Run the guarded public launch sequence for the external alpha."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_external_alpha_release import DEFAULT_OUTPUT_DIR, RELEASE_SLUG  # noqa: E402
from scripts.check_external_alpha_cloudflare_credentials import (  # noqa: E402
    CLOUDFLARE_CREDENTIALS_READY_VERDICT,
    CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
    check_cloudflare_credentials,
)
from scripts.check_external_alpha_cloudflare_pages_deploy_ready import (  # noqa: E402
    DEFAULT_CLOUDFLARE_PAGES_BRANCH,
    DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME,
    DEFAULT_WRANGLER_COMMAND,
    Runner,
    _command_string,
    _parse_command,
)
from scripts.check_external_alpha_public_launch_doctor import (  # noqa: E402
    PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME,
    check_public_launch_doctor,
)
from scripts.launch_external_alpha_cloudflare_pages import (  # noqa: E402
    CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT,
    CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME,
    DeployRunner,
    FinalizeFunc,
    SharePacketFunc,
    finalize_public_launch_url,
    launch_cloudflare_pages,
    prepare_public_share_packet,
)


PUBLIC_LAUNCH_SEQUENCE_SCHEMA_VERSION = "external_alpha_public_launch_sequence_v0_1"
PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT = "PUBLIC_LAUNCH_SEQUENCE_READY"
PUBLIC_LAUNCH_SEQUENCE_BLOCKED_CREDENTIALS_VERDICT = "BLOCKED_CLOUDFLARE_CREDENTIALS"
PUBLIC_LAUNCH_SEQUENCE_BLOCKED_LAUNCH_VERDICT = "BLOCKED_CLOUDFLARE_LAUNCH"
PUBLIC_LAUNCH_SEQUENCE_BLOCKED_DOCTOR_VERDICT = "BLOCKED_PUBLIC_LAUNCH_DOCTOR"
PUBLIC_LAUNCH_SEQUENCE_RECEIPT_NAME = f"{RELEASE_SLUG}-public-launch-sequence-receipt.json"

logger = logging.getLogger(__name__)

CredentialFunc = Callable[..., dict[str, Any]]
LaunchFunc = Callable[..., dict[str, Any]]
DoctorFunc = Callable[..., dict[str, Any]]


class PublicLaunchSequenceError(RuntimeError):
    """Public launch sequence receipt failed validation."""


def run_public_launch_sequence(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    receipt_path: Path | None = None,
    project_name: str = DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME,
    branch: str = DEFAULT_CLOUDFLARE_PAGES_BRANCH,
    wrangler_command: tuple[str, ...] = DEFAULT_WRANGLER_COMMAND,
    credential_timeout_seconds: float = 30.0,
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
    credential_func: CredentialFunc = check_cloudflare_credentials,
    launch_func: LaunchFunc = launch_cloudflare_pages,
    doctor_func: DoctorFunc = check_public_launch_doctor,
) -> dict[str, Any]:
    """Run credential check, optional launch, then doctor summary."""
    output_dir = output_dir.resolve()
    credential_result = credential_func(
        output_dir,
        receipt_path=output_dir / CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
        wrangler_command=wrangler_command,
        timeout_seconds=credential_timeout_seconds,
        runner=preflight_runner,
        api_token_present=api_token_present,
        account_id_present=account_id_present,
    )

    launch_result: dict[str, Any] | None = None
    launch_attempted = credential_result.get("verdict") == CLOUDFLARE_CREDENTIALS_READY_VERDICT
    if launch_attempted:
        launch_result = launch_func(
            output_dir,
            receipt_path=output_dir / CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME,
            project_name=project_name,
            branch=branch,
            wrangler_command=wrangler_command,
            preflight_timeout_seconds=preflight_timeout_seconds,
            deploy_timeout_seconds=deploy_timeout_seconds,
            url_gate_timeout_seconds=url_gate_timeout_seconds,
            preflight_runner=preflight_runner,
            deploy_runner=deploy_runner,
            ensure_project=ensure_project,
            api_token_present=api_token_present,
            account_id_present=account_id_present,
            finalize_func=finalize_func,
            prepare_share_packet=prepare_share_packet,
            share_packet_func=share_packet_func,
        )

    doctor_result: dict[str, Any] | None = None
    doctor_attempted = (
        isinstance(launch_result, dict)
        and launch_result.get("verdict") == CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
    )
    if doctor_attempted:
        doctor_result = doctor_func(
            output_dir,
            receipt_path=output_dir / PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME,
            preflight_runner=preflight_runner,
            api_token_present=api_token_present,
            account_id_present=account_id_present,
        )

    payload = _sequence_payload(
        credential_result=credential_result,
        launch_result=launch_result,
        launch_attempted=launch_attempted,
        doctor_result=doctor_result,
        doctor_attempted=doctor_attempted,
    )
    receipt_path = (receipt_path or output_dir / PUBLIC_LAUNCH_SEQUENCE_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_public_launch_sequence_receipt_file(receipt_path)
    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "external_sharing_allowed": payload["launch_state"]["external_sharing_allowed"],
        "next_action": payload["operator_next_action"],
        "receipt_body_sha256": payload["public_launch_sequence_body_sha256"],
    }


def verify_public_launch_sequence_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_launch_sequence_receipt_payload(payload)
    return payload


def verify_public_launch_sequence_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PUBLIC_LAUNCH_SEQUENCE_SCHEMA_VERSION:
        raise PublicLaunchSequenceError("public launch sequence schema_version mismatch.")
    if payload.get("status") not in {"pass", "blocked"}:
        raise PublicLaunchSequenceError("public launch sequence status mismatch.")
    if payload.get("verdict") not in {
        PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT,
        PUBLIC_LAUNCH_SEQUENCE_BLOCKED_CREDENTIALS_VERDICT,
        PUBLIC_LAUNCH_SEQUENCE_BLOCKED_LAUNCH_VERDICT,
        PUBLIC_LAUNCH_SEQUENCE_BLOCKED_DOCTOR_VERDICT,
    }:
        raise PublicLaunchSequenceError("public launch sequence verdict mismatch.")
    if payload.get("safe_to_share") is not True:
        raise PublicLaunchSequenceError("public launch sequence must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _sequence_checks(payload)
    if checks != recalculated:
        raise PublicLaunchSequenceError("public launch sequence checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicLaunchSequenceError("public launch sequence checks failed: " + ", ".join(failed))
    if payload.get("public_launch_sequence_body_sha256") != _receipt_body_sha256(payload):
        raise PublicLaunchSequenceError("public launch sequence body hash mismatch.")


def _sequence_payload(
    *,
    credential_result: dict[str, Any],
    launch_result: dict[str, Any] | None,
    launch_attempted: bool,
    doctor_result: dict[str, Any] | None,
    doctor_attempted: bool,
) -> dict[str, Any]:
    external_sharing_allowed = (
        isinstance(doctor_result, dict) and doctor_result.get("external_sharing_allowed") is True
    )
    verdict = _sequence_verdict(
        credential_result=credential_result,
        launch_result=launch_result,
        launch_attempted=launch_attempted,
        external_sharing_allowed=external_sharing_allowed,
    )
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_LAUNCH_SEQUENCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if verdict == PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT else "blocked",
        "verdict": verdict,
        "safe_to_share": True,
        "launch_state": {
            "phase": "public_launch_sequence",
            "external_sharing_allowed": external_sharing_allowed,
            "credential_ready": credential_result.get("verdict") == CLOUDFLARE_CREDENTIALS_READY_VERDICT,
            "launch_attempted": launch_attempted,
        },
        "stages": {
            "cloudflare_credentials": {
                "receipt_file": CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
                "verdict": credential_result.get("verdict"),
                "missing_env_vars": credential_result.get("missing_env_vars"),
                "receipt_body_sha256": credential_result.get("receipt_body_sha256"),
            },
            "cloudflare_launch": {
                "attempted": launch_attempted,
                "receipt_file": CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME if launch_attempted else None,
                "verdict": launch_result.get("verdict") if isinstance(launch_result, dict) else None,
                "external_sharing_allowed": launch_result.get("external_sharing_allowed")
                if isinstance(launch_result, dict)
                else False,
                "receipt_body_sha256": launch_result.get("receipt_body_sha256")
                if isinstance(launch_result, dict)
                else None,
            },
            "public_launch_doctor": {
                "attempted": doctor_attempted,
                "receipt_file": PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME if doctor_attempted else None,
                "verdict": doctor_result.get("verdict") if isinstance(doctor_result, dict) else None,
                "external_sharing_allowed": doctor_result.get("external_sharing_allowed")
                if isinstance(doctor_result, dict)
                else False,
                "receipt_body_sha256": doctor_result.get("receipt_body_sha256")
                if isinstance(doctor_result, dict)
                else None,
            },
        },
        "policy": {
            "does_not_deploy_without_credentials": True,
            "raw_private_values_included": False,
            "local_paths_included": False,
        },
        "operator_next_action": _operator_next_action(
            verdict=verdict,
            credential_result=credential_result,
            launch_result=launch_result,
            doctor_result=doctor_result,
        ),
        "pm_judgment": (
            "The safest public launch path is a single guarded sequence: credentials first, launch only if ready, "
            "then doctor confirmation only after a launch-ready receipt."
        ),
    }
    payload["public_launch_sequence_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _sequence_checks(payload)
    return payload


def _sequence_verdict(
    *,
    credential_result: dict[str, Any],
    launch_result: dict[str, Any] | None,
    launch_attempted: bool,
    external_sharing_allowed: bool,
) -> str:
    if external_sharing_allowed:
        return PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT
    if credential_result.get("verdict") != CLOUDFLARE_CREDENTIALS_READY_VERDICT:
        return PUBLIC_LAUNCH_SEQUENCE_BLOCKED_CREDENTIALS_VERDICT
    if not launch_attempted or not isinstance(launch_result, dict):
        return PUBLIC_LAUNCH_SEQUENCE_BLOCKED_LAUNCH_VERDICT
    if launch_result.get("verdict") != CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT:
        return PUBLIC_LAUNCH_SEQUENCE_BLOCKED_LAUNCH_VERDICT
    return PUBLIC_LAUNCH_SEQUENCE_BLOCKED_DOCTOR_VERDICT


def _sequence_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    stages = _dict(payload, "stages")
    credentials = _dict(stages, "cloudflare_credentials")
    launch = _dict(stages, "cloudflare_launch")
    doctor = _dict(stages, "public_launch_doctor")
    launch_state = _dict(payload, "launch_state")
    policy = _dict(payload, "policy")
    body_hash = payload.get("public_launch_sequence_body_sha256")
    is_ready = payload.get("verdict") == PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_LAUNCH_SEQUENCE_SCHEMA_VERSION,
        "status_matches_verdict": (payload.get("status") == "pass") == is_ready,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "credential_stage_recorded": credentials.get("receipt_file") == CLOUDFLARE_CREDENTIALS_RECEIPT_NAME
        and isinstance(credentials.get("verdict"), str),
        "launch_stage_respects_credentials": (
            credentials.get("verdict") == CLOUDFLARE_CREDENTIALS_READY_VERDICT
            and launch_state.get("launch_attempted") is True
            and launch.get("attempted") is True
        )
        or (
            credentials.get("verdict") != CLOUDFLARE_CREDENTIALS_READY_VERDICT
            and launch_state.get("launch_attempted") is False
            and launch.get("attempted") is False
        ),
        "doctor_stage_respects_launch": (
            launch.get("verdict") == CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
            and doctor.get("attempted") is True
            and doctor.get("receipt_file") == PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME
            and isinstance(doctor.get("verdict"), str)
        )
        or (
            launch.get("verdict") != CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT
            and doctor.get("attempted") is False
            and doctor.get("receipt_file") is None
        ),
        "external_share_matches_doctor": (
            doctor.get("attempted") is True
            and launch_state.get("external_sharing_allowed") is (doctor.get("external_sharing_allowed") is True)
        )
        or (
            doctor.get("attempted") is False
            and launch_state.get("external_sharing_allowed") is False
        ),
        "no_deploy_without_credentials": credentials.get("verdict") == CLOUDFLARE_CREDENTIALS_READY_VERDICT
        or launch.get("attempted") is False,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "next_action_present": isinstance(payload.get("operator_next_action"), str)
        and len(payload.get("operator_next_action", "")) > 20,
        "pm_judgment_present": isinstance(payload.get("pm_judgment"), str)
        and "guarded sequence" in payload.get("pm_judgment", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _operator_next_action(
    *,
    verdict: str,
    credential_result: dict[str, Any],
    launch_result: dict[str, Any] | None,
    doctor_result: dict[str, Any] | None,
) -> str:
    if verdict == PUBLIC_LAUNCH_SEQUENCE_READY_VERDICT:
        return "Review the public launch doctor and public share packet before external sharing."
    if verdict == PUBLIC_LAUNCH_SEQUENCE_BLOCKED_CREDENTIALS_VERDICT:
        return credential_result.get("next_action") or "Set Cloudflare credentials, then rerun this sequence."
    if verdict == PUBLIC_LAUNCH_SEQUENCE_BLOCKED_LAUNCH_VERDICT:
        if isinstance(launch_result, dict) and launch_result.get("next_action"):
            return str(launch_result["next_action"])
        return "Fix the Cloudflare launch blocker, then rerun this sequence."
    if isinstance(doctor_result, dict) and doctor_result.get("next_action"):
        return str(doctor_result["next_action"])
    return "Fix the public launch doctor blocker, then rerun this sequence."


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicLaunchSequenceError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicLaunchSequenceError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicLaunchSequenceError(f"JSON payload must be an object: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_launch_sequence_body_sha256", "checks"}
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
    parser = argparse.ArgumentParser(description="Run the guarded external alpha public launch sequence.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--receipt", default=None)
    parser.add_argument("--verify-receipt", default=None)
    parser.add_argument("--project-name", default=DEFAULT_CLOUDFLARE_PAGES_PROJECT_NAME)
    parser.add_argument("--branch", default=DEFAULT_CLOUDFLARE_PAGES_BRANCH)
    parser.add_argument("--wrangler-command", default=_command_string(DEFAULT_WRANGLER_COMMAND))
    parser.add_argument("--credential-timeout-seconds", type=float, default=30.0)
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
            payload = verify_public_launch_sequence_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public launch sequence receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha public launch sequence receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("share  : %s", payload["launch_state"]["external_sharing_allowed"])
        logger.info("next   : %s", payload["operator_next_action"])
        logger.info("body   : %s", payload["public_launch_sequence_body_sha256"])
        return 0

    try:
        result = run_public_launch_sequence(
            Path(args.output_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
            project_name=args.project_name,
            branch=args.branch,
            wrangler_command=_parse_command(args.wrangler_command),
            credential_timeout_seconds=args.credential_timeout_seconds,
            preflight_timeout_seconds=args.preflight_timeout_seconds,
            deploy_timeout_seconds=args.deploy_timeout_seconds,
            url_gate_timeout_seconds=args.url_gate_timeout_seconds,
            ensure_project=not args.skip_project_ensure,
            prepare_share_packet=not args.skip_share_packet,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing sequence failure.
        logger.error("[FAIL] external alpha public launch sequence: %s", exc)
        return 1

    prefix = "[PASS]" if result["status"] == "pass" else "[BLOCKED]"
    logger.info("%s external alpha public launch sequence", prefix)
    logger.info("verdict: %s", result["verdict"])
    logger.info("share  : %s", result["external_sharing_allowed"])
    logger.info("next   : %s", result["next_action"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
