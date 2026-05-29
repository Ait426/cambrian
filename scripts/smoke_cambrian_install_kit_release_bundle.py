from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prepare_cambrian_install_kit_release import (  # noqa: E402
    BUNDLE_GOLD_PATH_NAME,
    BUNDLE_INSTALLER_NAME,
    BUNDLE_VERIFIER_NAME,
    RELEASE_BUNDLE_NAME,
    verify_release_bundle_file,
)


BUNDLE_SMOKE_SCHEMA_VERSION = "cambrian_install_kit_release_bundle_smoke_v0_1"
BUNDLE_SMOKE_RECEIPT_NAME = "cambrian-install-kit-release-bundle-smoke-receipt.json"
DEFAULT_TIMEOUT = 240


class InstallKitReleaseBundleSmokeError(RuntimeError):
    """Install kit release bundle smoke gate failed."""


def smoke_release_bundle(
    bundle_path: Path | None = None,
    receipt_path: Path | None = None,
    *,
    python_executable: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run the recipient-style extracted bundle install and required gold path."""
    bundle = (bundle_path or ROOT / "dist" / RELEASE_BUNDLE_NAME).resolve()
    if not bundle.exists():
        raise FileNotFoundError(f"install kit release bundle을 찾을 수 없습니다: {bundle}")
    receipt_target = (receipt_path or ROOT / "dist" / BUNDLE_SMOKE_RECEIPT_NAME).resolve()
    receipt_target.parent.mkdir(parents=True, exist_ok=True)
    py = python_executable or Path(sys.executable)
    bundle_sha256 = _sha256(bundle)
    steps: list[dict[str, Any]] = []
    install_share_receipt: dict[str, Any] | None = None
    gold_path_share_receipt: dict[str, Any] | None = None

    with tempfile.TemporaryDirectory(prefix="cambrian-install-kit-bundle-smoke-") as tmp_name:
        tmp = Path(tmp_name).resolve()
        extract_dir = tmp / "bundle"
        project_dir = tmp / "project"
        extract_dir.mkdir(parents=True)
        project_dir.mkdir(parents=True)

        try:
            verify_release_bundle_file(bundle)
            steps.append(_synthetic_step("verify release bundle manifest and hash chain"))
        except Exception as exc:  # pragma: no cover - exercised by CLI failure path
            steps.append(_synthetic_step("verify release bundle manifest and hash chain", status="failed", error=str(exc)))

        if steps[-1]["status"] == "passed":
            try:
                with zipfile.ZipFile(bundle) as archive:
                    archive.extractall(extract_dir)
                steps.append(_synthetic_step("extract release bundle"))
            except (OSError, zipfile.BadZipFile) as exc:
                steps.append(_synthetic_step("extract release bundle", status="failed", error=str(exc)))

        if _all_steps_passed(steps):
            steps.append(
                _run(
                    [py, extract_dir / BUNDLE_VERIFIER_NAME],
                    cwd=extract_dir,
                    name="run extracted bundle verifier",
                    timeout=timeout,
                    redaction_roots=[tmp, ROOT],
                )
            )
        if _all_steps_passed(steps):
            steps.append(
                _run(
                    [py, extract_dir / BUNDLE_INSTALLER_NAME, "--project", project_dir],
                    cwd=extract_dir,
                    name="install Cambrian from extracted bundle",
                    timeout=timeout,
                    redaction_roots=[tmp, ROOT],
                )
            )
        if _all_steps_passed(steps):
            install_share_receipt = _read_json(project_dir / "cambrian_install_share_receipt.json")
            steps.append(_synthetic_step("read share-safe install receipt" if install_share_receipt else "read share-safe install receipt", status="passed" if install_share_receipt else "failed"))
        if _all_steps_passed(steps):
            steps.append(
                _run(
                    [py, extract_dir / BUNDLE_GOLD_PATH_NAME, "--project", project_dir],
                    cwd=extract_dir,
                    name="run required AI Company Gold Path",
                    timeout=timeout,
                    redaction_roots=[tmp, ROOT],
                )
            )
        if _all_steps_passed(steps):
            gold_path_share_receipt = _read_json(project_dir / "cambrian_gold_path_share_receipt.json")
            steps.append(_synthetic_step("read share-safe gold path receipt" if gold_path_share_receipt else "read share-safe gold path receipt", status="passed" if gold_path_share_receipt else "failed"))

    receipt = _smoke_receipt(
        bundle_name=bundle.name,
        bundle_sha256=bundle_sha256,
        steps=steps,
        install_share_receipt=install_share_receipt,
        gold_path_share_receipt=gold_path_share_receipt,
    )
    receipt_target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_bundle_smoke_receipt_file(receipt_target)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return receipt


def verify_bundle_smoke_receipt_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise InstallKitReleaseBundleSmokeError("bundle smoke receipt JSON 객체가 아닙니다.")
    verify_bundle_smoke_receipt_payload(payload)
    return payload


def verify_bundle_smoke_receipt_payload(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != BUNDLE_SMOKE_SCHEMA_VERSION:
        raise InstallKitReleaseBundleSmokeError("bundle smoke receipt schema_version이 올바르지 않습니다.")
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    if not checks:
        raise InstallKitReleaseBundleSmokeError("bundle smoke receipt checks가 없습니다.")
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise InstallKitReleaseBundleSmokeError("bundle smoke receipt 검증 실패: " + ", ".join(failed))
    receipt_checks = payload.get("receipt_checks") if isinstance(payload.get("receipt_checks"), dict) else {}
    failed_receipt = [name for name, passed in receipt_checks.items() if passed is not True]
    if failed_receipt:
        raise InstallKitReleaseBundleSmokeError("bundle smoke receipt 자체 검증 실패: " + ", ".join(failed_receipt))
    if payload.get("bundle_smoke_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise InstallKitReleaseBundleSmokeError("bundle smoke receipt body hash가 일치하지 않습니다.")


def _smoke_receipt(
    *,
    bundle_name: str,
    bundle_sha256: str,
    steps: list[dict[str, Any]],
    install_share_receipt: dict[str, Any] | None,
    gold_path_share_receipt: dict[str, Any] | None,
) -> dict[str, Any]:
    install_summary = _install_share_receipt_summary(install_share_receipt)
    gold_path_summary = _gold_path_share_receipt_summary(gold_path_share_receipt)
    checks = {
        "steps_all_passed": _all_steps_passed(steps),
        "bundle_sha256_present": _looks_like_sha256(bundle_sha256),
        "install_share_receipt_present": install_summary["present"],
        "install_share_receipt_safe": install_summary["safe_to_share"] is True
        and install_summary["absolute_paths_included"] is False
        and install_summary["checks_all_true"] is True,
        "gold_path_share_receipt_present": gold_path_summary["present"],
        "gold_path_share_receipt_safe": gold_path_summary["safe_to_share"] is True
        and gold_path_summary["absolute_paths_included"] is False
        and gold_path_summary["checks_all_true"] is True,
        "gold_path_capabilities_all_true": gold_path_summary["capabilities_all_true"] is True,
        "gold_path_mcp_operability_verified": gold_path_summary["mcp_operability_verified"] is True,
        "gold_path_claim_boundaries_locked": gold_path_summary["proof_claim_allowed"] is False
        and gold_path_summary["sale_ready"] is False,
        "raw_private_project_data_omitted": install_summary["raw_private_project_data_included"] is False
        and gold_path_summary["raw_private_project_data_included"] is False,
        "secrets_omitted": install_summary["secrets_included"] is False
        and gold_path_summary["secrets_included"] is False,
    }
    payload = {
        "schema_version": BUNDLE_SMOKE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if all(checks.values()) else "fail",
        "safe_to_share": True,
        "release_bundle": {
            "file": bundle_name,
            "sha256": bundle_sha256,
        },
        "steps": [
            {
                "name": step.get("name"),
                "status": step.get("status"),
                "exit_code": step.get("exit_code"),
                "duration_seconds": step.get("duration_seconds"),
            }
            for step in steps
        ],
        "install_share_receipt": install_summary,
        "gold_path_share_receipt": gold_path_summary,
        "checks": checks,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "claim_boundaries": {
            "public_proof_claim_allowed": False,
            "sale_ready": False,
            "success_rate_claim_allowed": False,
        },
    }
    payload["bundle_smoke_receipt_body_sha256"] = _receipt_body_sha256(payload)
    payload["receipt_checks"] = _receipt_checks(payload)
    return payload


def _install_share_receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        return {
            "present": False,
            "schema_version": None,
            "status": None,
            "safe_to_share": False,
            "absolute_paths_included": True,
            "raw_private_project_data_included": True,
            "secrets_included": True,
            "checks_all_true": False,
            "sha256": None,
        }
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    privacy = receipt.get("privacy") if isinstance(receipt.get("privacy"), dict) else {}
    return {
        "present": True,
        "schema_version": receipt.get("schema_version"),
        "status": receipt.get("status"),
        "safe_to_share": receipt.get("safe_to_share") is True,
        "absolute_paths_included": privacy.get("absolute_paths_included") is True,
        "raw_private_project_data_included": privacy.get("raw_private_project_data_included") is True,
        "secrets_included": privacy.get("secrets_included") is True,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "sha256": _sha256_json(receipt),
    }


def _gold_path_share_receipt_summary(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        return {
            "present": False,
            "schema_version": None,
            "status": None,
            "safe_to_share": False,
            "absolute_paths_included": True,
            "raw_private_project_data_included": True,
            "secrets_included": True,
            "checks_all_true": False,
            "capabilities_all_true": False,
            "mcp_operability_verified": False,
            "capabilities_verified": {},
            "proof_claim_allowed": True,
            "sale_ready": True,
            "sha256": None,
        }
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    privacy = receipt.get("privacy") if isinstance(receipt.get("privacy"), dict) else {}
    capabilities = receipt.get("capabilities_verified") if isinstance(receipt.get("capabilities_verified"), dict) else {}
    return {
        "present": True,
        "schema_version": receipt.get("schema_version"),
        "status": receipt.get("status"),
        "safe_to_share": receipt.get("safe_to_share") is True,
        "absolute_paths_included": privacy.get("absolute_paths_included") is True,
        "raw_private_project_data_included": privacy.get("raw_private_project_data_included") is True,
        "secrets_included": privacy.get("secrets_included") is True,
        "checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "capabilities_all_true": bool(capabilities) and all(value is True for value in capabilities.values()),
        "mcp_operability_verified": capabilities.get("mcp_operability_verified") is True,
        "capabilities_verified": capabilities,
        "proof_claim_allowed": receipt.get("proof_claim_allowed") is True,
        "sale_ready": receipt.get("sale_ready") is True,
        "sha256": _sha256_json(receipt),
    }


def _run(
    command: list[str | Path],
    *,
    cwd: Path,
    name: str,
    timeout: int,
    redaction_roots: list[Path],
) -> dict[str, Any]:
    started = time.perf_counter()
    run_env = dict(os.environ)
    run_env.setdefault("PYTHONIOENCODING", "utf-8")
    run_env.setdefault("PYTHONUTF8", "1")
    try:
        result = subprocess.run(
            [str(item) for item in command],
            cwd=str(cwd),
            env=run_env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        exit_code = result.returncode
        stderr = result.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stderr = str(exc)
    duration = time.perf_counter() - started
    return {
        "name": name,
        "command": [_command_token(item) for item in command],
        "cwd": "<bundle>",
        "exit_code": exit_code,
        "duration_seconds": round(duration, 3),
        "stderr_excerpt": _redact(stderr, redaction_roots=redaction_roots)[:600],
        "status": "passed" if exit_code == 0 else "failed",
    }


def _synthetic_step(name: str, *, status: str = "passed", error: str = "") -> dict[str, Any]:
    return {
        "name": name,
        "command": [],
        "cwd": "<bundle>",
        "exit_code": 0 if status == "passed" else 1,
        "duration_seconds": 0.0,
        "stderr_excerpt": error[:600],
        "status": status,
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"bundle_smoke_receipt_body_sha256", "receipt_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _receipt_checks(payload: dict[str, Any]) -> dict[str, bool]:
    body_hash = payload.get("bundle_smoke_receipt_body_sha256")
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    claim_boundaries = payload.get("claim_boundaries") if isinstance(payload.get("claim_boundaries"), dict) else {}
    return {
        "schema_version_present": payload.get("schema_version") == BUNDLE_SMOKE_SCHEMA_VERSION,
        "status_pass": payload.get("status") == "pass",
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "checks_all_true": all(
            value is True for value in (payload.get("checks") if isinstance(payload.get("checks"), dict) else {}).values()
        ),
        "absolute_paths_omitted": privacy.get("absolute_paths_included") is False,
        "raw_private_project_data_omitted": privacy.get("raw_private_project_data_included") is False,
        "secrets_omitted": privacy.get("secrets_included") is False,
        "claim_boundaries_locked": claim_boundaries.get("public_proof_claim_allowed") is False
        and claim_boundaries.get("sale_ready") is False
        and claim_boundaries.get("success_rate_claim_allowed") is False,
        "body_hash_present": _looks_like_sha256(str(body_hash or "")),
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def _all_steps_passed(steps: list[dict[str, Any]]) -> bool:
    return bool(steps) and all(step.get("status") == "passed" for step in steps)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _command_token(item: str | Path) -> str:
    name = Path(str(item)).name
    if name.lower().startswith("python"):
        return "python"
    if name in {BUNDLE_VERIFIER_NAME, BUNDLE_INSTALLER_NAME, BUNDLE_GOLD_PATH_NAME}:
        return name
    if str(item) == "--project":
        return "--project"
    return "<project>" if "project" in str(item).lower() else str(item)


def _redact(text: str, *, redaction_roots: list[Path]) -> str:
    redacted = text or ""
    for root in sorted((path.resolve() for path in redaction_roots), key=lambda path: len(str(path)), reverse=True):
        redacted = redacted.replace(str(root), "<redacted>")
    redacted = redacted.replace(str(Path.home()), "<home>")
    return redacted


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test Cambrian install kit release bundle as a recipient.")
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist" / RELEASE_BUNDLE_NAME)
    parser.add_argument("--receipt", type=Path, default=ROOT / "dist" / BUNDLE_SMOKE_RECEIPT_NAME)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--verify-receipt", type=Path, default=None)
    args = parser.parse_args()
    if args.verify_receipt:
        payload = verify_bundle_smoke_receipt_file(args.verify_receipt)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    try:
        receipt = smoke_release_bundle(bundle_path=args.bundle, receipt_path=args.receipt, timeout=args.timeout)
    except (InstallKitReleaseBundleSmokeError, FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        print(f"[FAIL] install kit release bundle smoke: {exc}", file=sys.stderr)
        return 1
    return 0 if receipt.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
