"""Collect a share-safe diagnostics report for external alpha support."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "external_alpha_diagnostics.json"
REPORT_SCHEMA_VERSION = "external_alpha_diagnostics_v0_1"
SHARE_GUIDANCE = (
    "Share only this diagnostics JSON when safe_to_share is true. Do not share .env, browser localStorage, "
    "private source, private project files, raw AI replies, or API keys."
)
SUPPORT_NEXT_ACTION = "Attach only this diagnostics JSON to the support request."
MISSING_FILES_NEXT_ACTION = "Check the missing required files, then rerun diagnostics."
MINIMAL_EVIDENCE_NEXT_ACTION = "Check safe_to_share and redaction_checks before sharing minimal evidence."
DO_NOT_SHARE = [
    ".env",
    "browser localStorage",
    "private source or project files",
    "raw AI reply",
    "API key or secret",
]
logger = logging.getLogger(__name__)

REQUIRED_FILES = (
    "QUICKSTART_EXTERNAL_ALPHA.md",
    "START_HERE_EXTERNAL_ALPHA.md",
    "RUN_CAMBRIAN_AGENT_PLATFORM_PROMPT_FOR_CODEX_CLAUDE.md",
    "EXTERNAL_ALPHA_SUPPORT_PACKET.md",
    "START_CAMBRIAN_AGENT_PLATFORM.bat",
    "VERIFY_CAMBRIAN_AGENT_PLATFORM_RC.bat",
    "COLLECT_CAMBRIAN_AGENT_PLATFORM_DIAGNOSTICS.bat",
    "docs/release/EXTERNAL_ALPHA_RELEASE_MANIFEST.md",
    "docs/release/RC_INSTALL_GUIDE.md",
    "scripts/verify_platform_alpha.py",
    "scripts/smoke_external_alpha_release_bundle.py",
    "scripts/smoke_external_alpha_manual_send_go_rehearsal.py",
    "scripts/smoke_external_alpha_post_send_checkpoint.py",
    "scripts/smoke_external_alpha_pilot_learning_loop.py",
    "scripts/prepare_external_alpha_operator_dispatch_packet.py",
    "scripts/check_external_alpha_first_recipient_pre_send_sequence.py",
    "scripts/check_external_alpha_first_recipient_post_send_sequence.py",
    "scripts/check_external_alpha_first_recipient_operator_status.py",
    "scripts/check_external_alpha_pilot_evidence.py",
    "scripts/check_external_alpha_pilot_decision.py",
    "scripts/check_external_alpha_pilot_iteration.py",
    "scripts/collect_external_alpha_diagnostics.py",
    "web/index.html",
    "web/platform/index.html",
    "web/runner/index.html",
    "web/evolution/index.html",
    "web/assets/document-organizer.agent-pack.json",
    "web/assets/document-organizer.promoted.agent-pack.json",
    "web/assets/document-organizer.candidate-promotion-record.json",
)

FORBIDDEN_TOP_LEVEL_NAMES = (
    ".env",
    ".git",
    ".cambrian",
    ".pytest_tmp",
    ".pytest_cache",
    "__pycache__",
)


class DiagnosticsError(Exception):
    """Raised when diagnostics cannot be generated."""


def collect_diagnostics(output_path: Path = DEFAULT_OUTPUT, run_verify: bool = True) -> dict[str, Any]:
    """Collect a diagnostics report without reading secrets or private project content."""
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "fail",
        "safe_to_share": False,
        "share_guidance": SHARE_GUIDANCE,
        "privacy": {
            "environment_variables_collected": False,
            "env_files_read": False,
            "secret_values_collected": False,
            "user_documents_collected": False,
            "path_sanitization": "bundle_root_and_home_replaced",
        },
        "system": _system_info(),
        "package": _package_info(),
        "required_files": _required_file_reports(),
        "forbidden_top_level_paths": _forbidden_top_level_reports(),
        "platform_verification": _run_platform_verification() if run_verify else {"status": "skipped"},
    }
    report["status"] = _report_status(report)
    _attach_share_safety(report)
    report["support_summary"] = _support_summary(report)
    _write_report(output_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Collect a Cambrian external alpha diagnostics JSON report.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Diagnostics JSON output path.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip platform self-verification.")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        report = collect_diagnostics(Path(args.output), run_verify=not args.skip_verify)
    except DiagnosticsError as exc:
        logger.error("[FAIL] external alpha diagnostics: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI should turn unexpected crashes into one reportable failure.
        logger.exception("[FAIL] external alpha diagnostics crashed: %s", exc)
        return 1

    logger.info("[PASS] external alpha diagnostics written: %s", Path(args.output))
    logger.info("status: %s", report["status"])
    logger.info("safe_to_share: %s", report["safe_to_share"])
    logger.info("support_summary: %s", report["support_summary"]["next_action"])
    return 0 if report["status"] == "pass" else 1


def _system_info() -> dict[str, str]:
    """Summarize runtime facts without exposing paths."""
    return {
        "platform": platform.system(),
        "platform_release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable_name": Path(sys.executable).name,
    }


def _package_info() -> dict[str, Any]:
    """Summarize bundle root metadata."""
    bundle_manifest = ROOT / "EXTERNAL_ALPHA_BUNDLE_MANIFEST.json"
    return {
        "root_name": ROOT.name,
        "bundle_manifest_present": bundle_manifest.is_file(),
    }


def _required_file_reports() -> list[dict[str, Any]]:
    """Report required file presence and hashes."""
    reports: list[dict[str, Any]] = []
    for relative in REQUIRED_FILES:
        path = ROOT / relative
        exists = path.is_file()
        item: dict[str, Any] = {"path": relative, "exists": exists}
        if exists:
            item["bytes"] = path.stat().st_size
            item["sha256"] = _sha256_file(path)
        reports.append(item)
    return reports


def _forbidden_top_level_reports() -> list[dict[str, Any]]:
    """Report forbidden top-level names without reading their contents."""
    reports: list[dict[str, Any]] = []
    for name in FORBIDDEN_TOP_LEVEL_NAMES:
        path = ROOT / name
        if path.exists():
            reports.append({"path": name, "present": True, "kind": "dir" if path.is_dir() else "file"})
    return reports


def _run_platform_verification() -> dict[str, Any]:
    """Run platform verification and sanitize its output tails."""
    script = ROOT / "scripts" / "verify_platform_alpha.py"
    if not script.is_file():
        return {"status": "fail", "returncode": None, "stderr": "verify_platform_alpha.py not found"}

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )
    status = "pass" if result.returncode == 0 else "fail"
    return {
        "status": status,
        "returncode": result.returncode,
        "stdout_tail": _sanitize_text(result.stdout[-6000:]),
        "stderr_tail": _sanitize_text(result.stderr[-6000:]),
    }


def _report_status(report: dict[str, Any]) -> str:
    """Compute the overall diagnostics status."""
    files_ok = all(item.get("exists") is True for item in report["required_files"])
    verify = report.get("platform_verification")
    verify_ok = isinstance(verify, dict) and verify.get("status") in {"pass", "skipped"}
    return "pass" if files_ok and verify_ok else "fail"


def _attach_share_safety(report: dict[str, Any]) -> None:
    """Attach redaction checks and safe_to_share status."""
    privacy = report.get("privacy") if isinstance(report.get("privacy"), dict) else {}
    serialized = json.dumps(report, ensure_ascii=False)
    home = str(Path.home())

    checks = {
        "bundle_root_path_redacted": str(ROOT) not in serialized,
        "home_path_redacted": not home or home not in serialized,
        "environment_variables_omitted": privacy.get("environment_variables_collected") is False,
        "env_files_omitted": privacy.get("env_files_read") is False,
        "secret_values_omitted": privacy.get("secret_values_collected") is False,
        "user_documents_omitted": privacy.get("user_documents_collected") is False,
    }
    report["redaction_checks"] = checks
    report["safe_to_share"] = all(checks.values())


def _support_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Summarize the support next action without raw user data."""
    required_files = report.get("required_files") if isinstance(report.get("required_files"), list) else []
    forbidden_paths = (
        report.get("forbidden_top_level_paths") if isinstance(report.get("forbidden_top_level_paths"), list) else []
    )
    verification = report.get("platform_verification") if isinstance(report.get("platform_verification"), dict) else {}
    missing_required_files = [
        item.get("path")
        for item in required_files
        if isinstance(item, dict) and isinstance(item.get("path"), str) and item.get("exists") is not True
    ]
    present_forbidden_paths = [
        item.get("path")
        for item in forbidden_paths
        if isinstance(item, dict) and isinstance(item.get("path"), str) and item.get("present") is True
    ]

    if report.get("status") == "pass" and report.get("safe_to_share") is True:
        next_action = SUPPORT_NEXT_ACTION
    elif missing_required_files:
        next_action = MISSING_FILES_NEXT_ACTION
    else:
        next_action = MINIMAL_EVIDENCE_NEXT_ACTION

    return {
        "status": report.get("status"),
        "safe_to_share": report.get("safe_to_share"),
        "platform_verification_status": verification.get("status"),
        "missing_required_files": missing_required_files,
        "present_forbidden_top_level_paths": present_forbidden_paths,
        "next_action": next_action,
        "do_not_share": DO_NOT_SHARE,
    }


def _write_report(output_path: Path, report: dict[str, Any]) -> None:
    """Write diagnostics as stable JSON."""
    resolved_output = output_path.resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    try:
        resolved_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise DiagnosticsError(f"Cannot write diagnostics report: {resolved_output}") from exc


def _sanitize_text(value: str) -> str:
    """Redact local root and home paths from command output."""
    sanitized = value.replace(str(ROOT), "<bundle_root>")
    home = str(Path.home())
    if home and home in sanitized:
        sanitized = sanitized.replace(home, "<home>")
    return sanitized


def _sha256_file(path: Path) -> str:
    """Return a file sha256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
