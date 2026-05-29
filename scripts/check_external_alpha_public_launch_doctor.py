"""Summarize the current public launch state and the next operator action."""

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
from scripts.check_external_alpha_cloudflare_credentials import (  # noqa: E402
    CLOUDFLARE_CREDENTIALS_READY_VERDICT,
    CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
    check_cloudflare_credentials,
    verify_cloudflare_credentials_receipt_file,
)
from scripts.check_external_alpha_cloudflare_pages_deploy_ready import (  # noqa: E402
    CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
    CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
    CLOUDFLARE_PAGES_READY_VERDICT,
    Runner,
    check_cloudflare_pages_deploy_ready,
    verify_cloudflare_pages_deploy_ready_receipt_file,
)
from scripts.check_external_alpha_public_deploy_candidate import (  # noqa: E402
    PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
    PUBLIC_DEPLOY_CANDIDATE_VERDICT,
    verify_public_deploy_candidate_receipt_file,
)
from scripts.finalize_external_alpha_public_launch_url import (  # noqa: E402
    PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
    PUBLIC_LAUNCH_URL_READY_VERDICT,
    verify_public_launch_url_gate_receipt_file,
)
from scripts.launch_external_alpha_cloudflare_pages import (  # noqa: E402
    CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT,
    CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME,
    verify_cloudflare_pages_launch_receipt_file,
)
from scripts.prepare_external_alpha_public_share_packet import (  # noqa: E402
    PUBLIC_SHARE_PACKET_JSON_NAME,
    PUBLIC_SHARE_PACKET_VERDICT,
    verify_public_share_packet_file,
)


PUBLIC_LAUNCH_DOCTOR_SCHEMA_VERSION = "external_alpha_public_launch_doctor_v0_1"
PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME = f"{RELEASE_SLUG}-public-launch-doctor.json"
PUBLIC_LAUNCH_SHARE_READY_VERDICT = "PUBLIC_LAUNCH_SHARE_READY"
READY_TO_PREPARE_PUBLIC_SHARE_PACKET_VERDICT = "READY_TO_PREPARE_PUBLIC_SHARE_PACKET"
READY_TO_RUN_CLOUDFLARE_LAUNCH_VERDICT = "READY_TO_RUN_CLOUDFLARE_LAUNCH"
BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT = "BLOCKED_CLOUDFLARE_CREDENTIALS"
BLOCKED_CLOUDFLARE_PREFLIGHT_VERDICT = "BLOCKED_CLOUDFLARE_PREFLIGHT"
BLOCKED_PUBLIC_DEPLOY_CANDIDATE_VERDICT = "BLOCKED_PUBLIC_DEPLOY_CANDIDATE"

logger = logging.getLogger(__name__)


class PublicLaunchDoctorError(RuntimeError):
    """Public launch doctor failed."""


def check_public_launch_doctor(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    receipt_path: Path | None = None,
    preflight_runner: Runner | None = None,
    api_token_present: bool | None = None,
    account_id_present: bool | None = None,
) -> dict[str, Any]:
    """Write a safe, no-deploy public launch status receipt."""
    output_dir = output_dir.resolve()
    credential_result = check_cloudflare_credentials(
        output_dir,
        receipt_path=output_dir / CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
        runner=preflight_runner,
        api_token_present=api_token_present,
        account_id_present=account_id_present,
    )
    credential_payload = verify_cloudflare_credentials_receipt_file(output_dir / CLOUDFLARE_CREDENTIALS_RECEIPT_NAME)
    candidate = _load_receipt(
        output_dir / PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
        verify_public_deploy_candidate_receipt_file,
    )
    preflight_result: dict[str, Any] | None = None
    preflight_payload: dict[str, Any] | None = None
    if candidate["ok"]:
        preflight_result = check_cloudflare_pages_deploy_ready(
            output_dir,
            receipt_path=output_dir / CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
            runner=preflight_runner,
            api_token_present=api_token_present,
            account_id_present=account_id_present,
        )
        preflight_payload = verify_cloudflare_pages_deploy_ready_receipt_file(
            output_dir / CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME
        )

    launch = _load_receipt(output_dir / CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME, verify_cloudflare_pages_launch_receipt_file)
    url_gate = _load_receipt(output_dir / PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME, verify_public_launch_url_gate_receipt_file)
    share_packet = _load_receipt(output_dir / PUBLIC_SHARE_PACKET_JSON_NAME, verify_public_share_packet_file)

    payload = _doctor_payload(
        credential_result=credential_result,
        credential_payload=credential_payload,
        candidate=candidate,
        preflight_result=preflight_result,
        preflight_payload=preflight_payload,
        launch=launch,
        url_gate=url_gate,
        share_packet=share_packet,
    )
    receipt_path = (receipt_path or output_dir / PUBLIC_LAUNCH_DOCTOR_RECEIPT_NAME).resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(receipt_path, payload)
    verify_public_launch_doctor_receipt_file(receipt_path)

    return {
        "status": payload["status"],
        "verdict": payload["verdict"],
        "receipt_json": str(receipt_path),
        "next_action": payload["next_action"]["command"],
        "external_sharing_allowed": payload["launch_state"]["external_sharing_allowed"],
        "receipt_body_sha256": payload["public_launch_doctor_body_sha256"],
    }


def verify_public_launch_doctor_receipt_file(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    verify_public_launch_doctor_receipt_payload(payload)
    return payload


def verify_public_launch_doctor_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PUBLIC_LAUNCH_DOCTOR_SCHEMA_VERSION:
        raise PublicLaunchDoctorError("public launch doctor schema_version mismatch.")
    if payload.get("status") not in {"pass", "blocked", "ready"}:
        raise PublicLaunchDoctorError("public launch doctor status mismatch.")
    if payload.get("verdict") not in {
        PUBLIC_LAUNCH_SHARE_READY_VERDICT,
        READY_TO_PREPARE_PUBLIC_SHARE_PACKET_VERDICT,
        READY_TO_RUN_CLOUDFLARE_LAUNCH_VERDICT,
        BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT,
        BLOCKED_CLOUDFLARE_PREFLIGHT_VERDICT,
        BLOCKED_PUBLIC_DEPLOY_CANDIDATE_VERDICT,
    }:
        raise PublicLaunchDoctorError("public launch doctor verdict mismatch.")
    if payload.get("safe_to_share") is not True:
        raise PublicLaunchDoctorError("public launch doctor must be safe_to_share.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    recalculated = _doctor_checks(payload)
    if checks != recalculated:
        raise PublicLaunchDoctorError("public launch doctor checks are stale.")
    failed = [name for name, passed in recalculated.items() if passed is not True]
    if failed:
        raise PublicLaunchDoctorError("public launch doctor checks failed: " + ", ".join(failed))
    if payload.get("public_launch_doctor_body_sha256") != _receipt_body_sha256(payload):
        raise PublicLaunchDoctorError("public launch doctor body hash mismatch.")


def _doctor_payload(
    *,
    credential_result: dict[str, Any],
    credential_payload: dict[str, Any],
    candidate: dict[str, Any],
    preflight_result: dict[str, Any] | None,
    preflight_payload: dict[str, Any] | None,
    launch: dict[str, Any],
    url_gate: dict[str, Any],
    share_packet: dict[str, Any],
) -> dict[str, Any]:
    verdict = _doctor_verdict(credential_result, candidate, preflight_result, launch, url_gate, share_packet)
    status = "pass" if verdict == PUBLIC_LAUNCH_SHARE_READY_VERDICT else "ready" if verdict.startswith("READY_") else "blocked"
    external_sharing_allowed = verdict == PUBLIC_LAUNCH_SHARE_READY_VERDICT
    payload: dict[str, Any] = {
        "schema_version": PUBLIC_LAUNCH_DOCTOR_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "verdict": verdict,
        "safe_to_share": True,
        "launch_state": {
            "phase": "public_launch_doctor",
            "external_sharing_allowed": external_sharing_allowed,
            "public_url_ready": _receipt_verdict(url_gate) == PUBLIC_LAUNCH_URL_READY_VERDICT,
            "share_packet_ready": _receipt_verdict(share_packet) == PUBLIC_SHARE_PACKET_VERDICT,
        },
        "artifacts": {
            "cloudflare_credentials": _credential_summary(credential_result, credential_payload),
            "public_deploy_candidate": _artifact_summary(
                candidate,
                expected_file=PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
            ),
            "cloudflare_pages_preflight": _preflight_summary(preflight_result, preflight_payload),
            "cloudflare_pages_launch": _artifact_summary(
                launch,
                expected_file=CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME,
            ),
            "public_url_gate": _artifact_summary(
                url_gate,
                expected_file=PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
            ),
            "public_share_packet": _artifact_summary(
                share_packet,
                expected_file=PUBLIC_SHARE_PACKET_JSON_NAME,
            ),
        },
        "next_action": _next_action(
            verdict,
            credential_payload=credential_payload,
            preflight_payload=preflight_payload,
        ),
        "policy": {
            "does_not_deploy": True,
            "does_not_share_url": True,
            "raw_private_values_included": False,
            "local_paths_included": False,
            "external_share_before_public_url_gate": False,
        },
        "pm_judgment": (
            "The public launch is a state machine: deploy candidate, Cloudflare preflight, Cloudflare launch, "
            "public URL gate, then share packet."
        ),
    }
    payload["public_launch_doctor_body_sha256"] = _receipt_body_sha256(payload)
    payload["checks"] = _doctor_checks(payload)
    return payload


def _doctor_verdict(
    credential_result: dict[str, Any],
    candidate: dict[str, Any],
    preflight_result: dict[str, Any] | None,
    launch: dict[str, Any],
    url_gate: dict[str, Any],
    share_packet: dict[str, Any],
) -> str:
    if _receipt_verdict(share_packet) == PUBLIC_SHARE_PACKET_VERDICT:
        return PUBLIC_LAUNCH_SHARE_READY_VERDICT
    if _receipt_verdict(url_gate) == PUBLIC_LAUNCH_URL_READY_VERDICT:
        return READY_TO_PREPARE_PUBLIC_SHARE_PACKET_VERDICT
    if _receipt_verdict(launch) == CLOUDFLARE_PAGES_LAUNCH_READY_VERDICT:
        return READY_TO_PREPARE_PUBLIC_SHARE_PACKET_VERDICT
    if not candidate["ok"] or _receipt_verdict(candidate) != PUBLIC_DEPLOY_CANDIDATE_VERDICT:
        return BLOCKED_PUBLIC_DEPLOY_CANDIDATE_VERDICT
    if credential_result.get("verdict") != CLOUDFLARE_CREDENTIALS_READY_VERDICT:
        return BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT
    preflight_verdict = preflight_result.get("verdict") if isinstance(preflight_result, dict) else None
    if preflight_verdict == CLOUDFLARE_PAGES_READY_VERDICT:
        return READY_TO_RUN_CLOUDFLARE_LAUNCH_VERDICT
    if preflight_verdict in {
        CLOUDFLARE_PAGES_API_TOKEN_BLOCKED_VERDICT,
        CLOUDFLARE_PAGES_ACCOUNT_ID_BLOCKED_VERDICT,
    }:
        return BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT
    return BLOCKED_CLOUDFLARE_PREFLIGHT_VERDICT


def _next_action(
    verdict: str,
    *,
    credential_payload: dict[str, Any] | None = None,
    preflight_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if verdict == PUBLIC_LAUNCH_SHARE_READY_VERDICT:
        return {
            "label": "Share public packet",
            "command": "review dist\\cambrian-agent-platform-external-alpha-public-share-packet.md",
        }
    if verdict == READY_TO_PREPARE_PUBLIC_SHARE_PACKET_VERDICT:
        return {
            "label": "Prepare public share packet",
            "command": "python scripts\\prepare_external_alpha_public_share_packet.py",
        }
    if verdict == READY_TO_RUN_CLOUDFLARE_LAUNCH_VERDICT:
        return {
            "label": "Run Cloudflare launch",
            "command": (
                "python scripts\\launch_external_alpha_cloudflare_pages.py "
                "--receipt dist\\cambrian-agent-platform-external-alpha-cloudflare-pages-launch-receipt.json"
            ),
        }
    if verdict == BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT:
        missing = _missing_credential_gate_env_vars(credential_payload) or _missing_cloudflare_credentials(
            preflight_payload
        )
        return {
            "label": "Set Cloudflare credentials",
            "command": (
                "read docs\\release\\CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md; set "
                + " and ".join(
                    missing
                    or _required_credential_gate_env_vars(credential_payload)
                    or _required_cloudflare_credentials(preflight_payload)
                )
                + "; rerun python scripts\\check_external_alpha_cloudflare_credentials.py "
                "--receipt dist\\cambrian-agent-platform-external-alpha-cloudflare-credentials-receipt.json"
            ),
            "runbook": "docs\\release\\CLOUDFLARE_PAGES_TOKEN_RUNBOOK.md",
            "required_env_vars": _required_credential_gate_env_vars(credential_payload)
            or _required_cloudflare_credentials(preflight_payload),
            "missing_env_vars": missing,
            "credential_receipt": CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
        }
    if verdict == BLOCKED_PUBLIC_DEPLOY_CANDIDATE_VERDICT:
        return {
            "label": "Rebuild public deploy candidate",
            "command": (
                "python scripts\\check_external_alpha_public_deploy_candidate.py "
                "--receipt dist\\cambrian-agent-platform-external-alpha-public-deploy-candidate-receipt.json"
            ),
        }
    return {
        "label": "Fix Cloudflare preflight",
        "command": (
            "python scripts\\check_external_alpha_cloudflare_pages_deploy_ready.py "
            "--receipt dist\\cambrian-agent-platform-external-alpha-cloudflare-pages-deploy-ready.json"
        ),
    }


def _doctor_checks(payload: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    artifacts = _dict(payload, "artifacts")
    credentials = _dict(artifacts, "cloudflare_credentials")
    preflight = _dict(artifacts, "cloudflare_pages_preflight")
    launch_state = _dict(payload, "launch_state")
    next_action = _dict(payload, "next_action")
    policy = _dict(payload, "policy")
    body_hash = payload.get("public_launch_doctor_body_sha256")
    verdict = payload.get("verdict")
    return {
        "schema_version_present": payload.get("schema_version") == PUBLIC_LAUNCH_DOCTOR_SCHEMA_VERSION,
        "status_matches_verdict": (payload.get("status") == "pass") == (verdict == PUBLIC_LAUNCH_SHARE_READY_VERDICT),
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "candidate_artifact_recorded": _dict(artifacts, "public_deploy_candidate").get("file")
        == PUBLIC_DEPLOY_CANDIDATE_RECEIPT_NAME,
        "credential_artifact_recorded": credentials.get("file") == CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
        "preflight_artifact_recorded": _dict(artifacts, "cloudflare_pages_preflight").get("file")
        == CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
        "launch_artifact_recorded": _dict(artifacts, "cloudflare_pages_launch").get("file")
        == CLOUDFLARE_PAGES_LAUNCH_RECEIPT_NAME,
        "url_gate_artifact_recorded": _dict(artifacts, "public_url_gate").get("file")
        == PUBLIC_LAUNCH_URL_GATE_RECEIPT_NAME,
        "share_packet_artifact_recorded": _dict(artifacts, "public_share_packet").get("file")
        == PUBLIC_SHARE_PACKET_JSON_NAME,
        "external_share_only_when_share_ready": launch_state.get("external_sharing_allowed")
        is (verdict == PUBLIC_LAUNCH_SHARE_READY_VERDICT),
        "next_action_present": isinstance(next_action.get("command"), str)
        and len(next_action.get("command", "")) > 8,
        "credential_blocker_names_missing_env_vars": verdict != BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT
        or (
            isinstance(next_action.get("missing_env_vars"), list)
            and len(next_action.get("missing_env_vars", [])) > 0
            and all(isinstance(item, str) for item in next_action.get("missing_env_vars", []))
        ),
        "credential_blocker_matches_artifact_summary": verdict != BLOCKED_CLOUDFLARE_CREDENTIALS_VERDICT
        or tuple(next_action.get("missing_env_vars", []))
        in {
            tuple(credentials.get("missing_env_vars", [])),
            tuple(preflight.get("missing_credential_env_vars", [])),
        },
        "credential_gate_is_no_deploy": credentials.get("does_not_deploy") is True,
        "doctor_is_no_deploy": policy.get("does_not_deploy") is True,
        "doctor_is_no_share": policy.get("does_not_share_url") is True,
        "privacy_safe": policy.get("raw_private_values_included") is False
        and policy.get("local_paths_included") is False
        and str(ROOT) not in serialized
        and str(Path.home()) not in serialized,
        "claim_boundary_locked": policy.get("external_share_before_public_url_gate") is False,
        "pm_judgment_present": isinstance(payload.get("pm_judgment"), str)
        and "state machine" in payload.get("pm_judgment", ""),
        "body_hash_present": _looks_like_sha256(body_hash),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _load_receipt(path: Path, verifier: Any) -> dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "file": path.name, "verdict": None, "error": "missing"}
    try:
        payload = verifier(path)
    except Exception as exc:  # noqa: BLE001 - doctor reports summarized failure state.
        return {"ok": False, "file": path.name, "verdict": None, "error": exc.__class__.__name__}
    return {"ok": True, "file": path.name, "payload": payload, "verdict": payload.get("verdict")}


def _artifact_summary(receipt: dict[str, Any], *, expected_file: str) -> dict[str, Any]:
    payload = receipt.get("payload") if isinstance(receipt.get("payload"), dict) else {}
    return {
        "file": expected_file,
        "ok": receipt.get("ok") is True,
        "verdict": payload.get("verdict") if payload else receipt.get("verdict"),
        "status": payload.get("status") if payload else None,
        "body_sha256": _known_body_hash(payload),
        "error": receipt.get("error"),
    }


def _credential_summary(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    credentials = _dict(payload, "credentials")
    policy = _dict(payload, "policy")
    return {
        "file": CLOUDFLARE_CREDENTIALS_RECEIPT_NAME,
        "ok": isinstance(payload, dict),
        "verdict": result.get("verdict") if isinstance(result, dict) else payload.get("verdict"),
        "status": result.get("status") if isinstance(result, dict) else payload.get("status"),
        "body_sha256": payload.get("cloudflare_credentials_body_sha256"),
        "required_env_vars": credentials.get("required_env_vars"),
        "missing_env_vars": credentials.get("missing_env_vars"),
        "credential_runbook": credentials.get("credential_runbook"),
        "does_not_deploy": policy.get("does_not_deploy") is True,
    }


def _preflight_summary(result: dict[str, Any] | None, payload: dict[str, Any] | None) -> dict[str, Any]:
    cloudflare = _dict(payload, "cloudflare_pages") if isinstance(payload, dict) else {}
    wrangler = _dict(payload, "wrangler") if isinstance(payload, dict) else {}
    return {
        "file": CLOUDFLARE_PAGES_DEPLOY_RECEIPT_NAME,
        "ok": isinstance(payload, dict),
        "verdict": result.get("verdict") if isinstance(result, dict) else None,
        "status": result.get("status") if isinstance(result, dict) else None,
        "body_sha256": payload.get("cloudflare_pages_deploy_ready_body_sha256") if isinstance(payload, dict) else None,
        "account_id_present": wrangler.get("account_id_env_var_present") if isinstance(payload, dict) else None,
        "api_token_present": wrangler.get("noninteractive_api_token_present") if isinstance(payload, dict) else None,
        "noninteractive_deploy_credential_ready": wrangler.get("noninteractive_deploy_credential_ready")
        if isinstance(payload, dict)
        else None,
        "required_credential_env_vars": _required_cloudflare_credentials(payload),
        "missing_credential_env_vars": _missing_cloudflare_credentials(payload),
        "credential_runbook": cloudflare.get("credential_runbook") if isinstance(payload, dict) else None,
        "operator_next_action": payload.get("operator_next_action") if isinstance(payload, dict) else None,
    }


def _required_cloudflare_credentials(payload: dict[str, Any] | None) -> list[str]:
    cloudflare = _dict(payload, "cloudflare_pages")
    value = cloudflare.get("required_credential_env_vars")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"]


def _required_credential_gate_env_vars(payload: dict[str, Any] | None) -> list[str]:
    credentials = _dict(payload, "credentials")
    value = credentials.get("required_env_vars")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _missing_cloudflare_credentials(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    wrangler = _dict(payload, "wrangler")
    missing: list[str] = []
    if wrangler.get("noninteractive_api_token_present") is not True:
        missing.append("CLOUDFLARE_API_TOKEN")
    if wrangler.get("account_id_env_var_present") is not True:
        missing.append("CLOUDFLARE_ACCOUNT_ID")
    return missing


def _missing_credential_gate_env_vars(payload: dict[str, Any] | None) -> list[str]:
    credentials = _dict(payload, "credentials")
    value = credentials.get("missing_env_vars")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _known_body_hash(payload: dict[str, Any]) -> str | None:
    for key in (
        "cloudflare_credentials_body_sha256",
        "public_deploy_candidate_receipt_body_sha256",
        "cloudflare_pages_launch_receipt_body_sha256",
        "public_launch_url_gate_receipt_body_sha256",
        "public_share_packet_body_sha256",
    ):
        value = payload.get(key)
        if _looks_like_sha256(value):
            return value
    return None


def _receipt_verdict(receipt: dict[str, Any]) -> str | None:
    payload = receipt.get("payload") if isinstance(receipt.get("payload"), dict) else None
    if payload:
        verdict = payload.get("verdict")
        return verdict if isinstance(verdict, str) else None
    verdict = receipt.get("verdict")
    return verdict if isinstance(verdict, str) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise PublicLaunchDoctorError(f"cannot read JSON file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise PublicLaunchDoctorError(f"cannot parse JSON file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PublicLaunchDoctorError(f"JSON payload must be an object: {path.name}")
    return payload


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"generated_at", "public_launch_doctor_body_sha256", "checks"}
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
    parser = argparse.ArgumentParser(description="Check the external alpha public launch state.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
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
            payload = verify_public_launch_doctor_receipt_file(Path(args.verify_receipt))
        except Exception as exc:  # noqa: BLE001 - concise operator-facing verifier failure.
            logger.error("[FAIL] external alpha public launch doctor receipt: %s", exc)
            return 1
        logger.info("[PASS] external alpha public launch doctor receipt")
        logger.info("verdict: %s", payload["verdict"])
        logger.info("share  : %s", payload["launch_state"]["external_sharing_allowed"])
        logger.info("next   : %s", payload["next_action"]["command"])
        logger.info("body   : %s", payload["public_launch_doctor_body_sha256"])
        return 0

    try:
        result = check_public_launch_doctor(
            Path(args.output_dir),
            receipt_path=Path(args.receipt) if args.receipt else None,
        )
    except Exception as exc:  # noqa: BLE001 - concise operator-facing doctor failure.
        logger.error("[FAIL] external alpha public launch doctor: %s", exc)
        return 1

    prefix = "[PASS]" if result["status"] == "pass" else "[READY]" if result["status"] == "ready" else "[BLOCKED]"
    logger.info("%s external alpha public launch doctor", prefix)
    logger.info("verdict: %s", result["verdict"])
    logger.info("share  : %s", result["external_sharing_allowed"])
    logger.info("next   : %s", result["next_action"])
    logger.info("body   : %s", result["receipt_body_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
