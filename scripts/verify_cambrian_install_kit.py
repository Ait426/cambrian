from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INSTALL_KIT_SCHEMA_VERSION = "cambrian_install_kit_v0_1"
RECEIPT_SCHEMA_VERSION = "cambrian_install_kit_verification_receipt_v0_1"
MANIFEST_NAME = "CAMBRIAN_INSTALL_KIT_MANIFEST.json"
REQUIRED_FILES = {
    MANIFEST_NAME,
    "README_INSTALL_CAMBRIAN.md",
    "INSTALL_PROMPT_FOR_CODEX_CLAUDE.md",
    "install_cambrian.py",
    "INSTALL_CAMBRIAN.ps1",
    "INSTALL_CAMBRIAN.bat",
    "install_cambrian.sh",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 객체가 아닙니다: {path.name}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(command: list[str | Path], cwd: Path, timeout: int = 180) -> dict[str, Any]:
    result = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": [str(item) for item in command],
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "passed" if result.returncode == 0 else "failed",
    }


def verify_install_kit(zip_path: Path, install_check: bool = False, offline: bool = False) -> dict[str, Any]:
    """install kit ZIP의 파일 해시와 선택적 설치 실행을 검증한다."""
    resolved_zip = zip_path.resolve()
    if not resolved_zip.exists():
        raise FileNotFoundError(f"install kit ZIP을 찾을 수 없습니다: {resolved_zip}")
    tmp = Path(tempfile.mkdtemp(prefix="cambrian-install-kit-check-")).resolve()
    try:
        extract_dir = tmp / "kit"
        extract_dir.mkdir(parents=True)
        with zipfile.ZipFile(resolved_zip) as archive:
            archive.extractall(extract_dir)
        manifest_path = extract_dir / MANIFEST_NAME
        manifest = _read_json(manifest_path)
        checks = _verify_manifest(extract_dir, manifest)
        install_result: dict[str, Any] | None = None
        if install_check:
            project_dir = tmp / "project"
            project_dir.mkdir()
            install_command: list[str | Path] = [sys.executable, extract_dir / "install_cambrian.py", "--project", project_dir]
            if offline:
                install_command.append("--offline")
            install_step = _run(install_command, cwd=extract_dir, timeout=240)
            checks["install_script_passed"] = install_step["exit_code"] == 0
            receipt_path = project_dir / "cambrian_install_receipt.json"
            mcp_receipt_path = project_dir / "mcp_operability_receipt.json"
            checks["install_receipt_present"] = receipt_path.exists()
            checks["mcp_operability_receipt_present"] = mcp_receipt_path.exists()
            receipt = _read_json(receipt_path) if receipt_path.exists() else {}
            mcp_receipt = _read_json(mcp_receipt_path) if mcp_receipt_path.exists() else {}
            receipt_steps = receipt.get("steps", [])
            receipt_next_commands = receipt.get("next_commands", [])
            mcp_receipt_checks = mcp_receipt.get("checks") if isinstance(mcp_receipt.get("checks"), dict) else {}
            checks["install_receipt_status_installed"] = receipt.get("status") == "installed"
            checks["install_receipt_steps_passed"] = bool(receipt_steps) and all(
                isinstance(step, dict) and step.get("status") == "passed"
                for step in receipt_steps
            )
            checks["install_receipt_company_snapshot_help_passed"] = any(
                isinstance(step, dict)
                and "company snapshot --help" in str(step.get("command") or "")
                and step.get("status") == "passed"
                for step in receipt_steps
            )
            checks["install_receipt_company_snapshot_next_command_present"] = any(
                "company snapshot --json" in str(command)
                for command in receipt_next_commands
            )
            checks["install_receipt_mcp_verify_passed"] = any(
                isinstance(step, dict)
                and "mcp verify" in str(step.get("command") or "")
                and step.get("status") == "passed"
                for step in receipt_steps
            )
            checks["install_receipt_mcp_next_command_present"] = any(
                "mcp verify" in str(command)
                for command in receipt_next_commands
            )
            checks["mcp_operability_receipt_go"] = mcp_receipt.get("verdict") == "GO"
            checks["mcp_operability_installed_entrypoint"] = (
                mcp_receipt.get("server_command_mode") == "installed_entrypoint"
                and mcp_receipt.get("installed_entrypoint_command") is True
                and mcp_receipt.get("source_pythonpath_injected") is False
            )
            checks["mcp_operability_no_arbitrary_shell"] = mcp_receipt_checks.get("no_arbitrary_shell") is True
            install_result = {
                "step": {
                    "command": install_step["command"],
                    "exit_code": install_step["exit_code"],
                    "status": install_step["status"],
                },
                "receipt": receipt,
            }
        failed = [name for name, passed in checks.items() if passed is not True]
        result = {
            "schema_version": "cambrian_install_kit_verification_v0_1",
            "status": "pass" if not failed else "fail",
            "zip_file": str(resolved_zip),
            "zip_sha256": _sha256(resolved_zip),
            "manifest_version": manifest.get("package", {}).get("version"),
            "checks": checks,
            "failed_checks": failed,
            "install_check": install_check,
            "offline": offline,
            "install_result": install_result,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if failed:
            raise SystemExit(1)
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_shareable_receipt(output_path: Path, result: dict[str, Any]) -> Path:
    """절대경로 없이 공유 가능한 install kit 검증 receipt를 저장한다."""
    receipt = _shareable_receipt(result)
    _verify_shareable_receipt(receipt)
    resolved_output = output_path.resolve()
    _write_json(resolved_output, receipt)
    return resolved_output


def verify_shareable_receipt_file(path: Path) -> dict[str, Any]:
    """ZIP 없이 install kit 검증 receipt 자체의 무결성과 공유 안전성을 확인한다."""
    receipt = _read_json(path.resolve())
    _verify_shareable_receipt(receipt)
    return receipt


def _shareable_receipt(result: dict[str, Any]) -> dict[str, Any]:
    checks = result.get("checks") if isinstance(result.get("checks"), dict) else {}
    zip_file = Path(str(result.get("zip_file") or "")).name
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": result.get("status"),
        "safe_to_share": True,
        "install_kit": {
            "zip_file": zip_file,
            "zip_sha256": result.get("zip_sha256"),
            "manifest_version": result.get("manifest_version"),
        },
        "verification": {
            "install_check": result.get("install_check") is True,
            "offline": result.get("offline") is True,
            "failed_checks": result.get("failed_checks") if isinstance(result.get("failed_checks"), list) else [],
        },
        "verified_checks": {
            key: value
            for key, value in checks.items()
            if key
            in {
                "schema_version",
                "required_files_present",
                "wheel_present",
                "python_requires_present",
                "entrypoint_present",
                "mcp_entrypoint_present",
                "install_commands_present",
                "files_hashes_match",
                "install_script_passed",
                "install_receipt_present",
                "install_receipt_status_installed",
                "install_receipt_steps_passed",
                "install_receipt_company_snapshot_help_passed",
                "install_receipt_company_snapshot_next_command_present",
                "install_receipt_mcp_verify_passed",
                "install_receipt_mcp_next_command_present",
                "mcp_operability_receipt_present",
                "mcp_operability_receipt_go",
                "mcp_operability_installed_entrypoint",
                "mcp_operability_no_arbitrary_shell",
            }
        },
        "capabilities": {
            "cambrian_help": checks.get("install_receipt_steps_passed") is True,
            "doctor_json": checks.get("install_receipt_steps_passed") is True,
            "company_snapshot_help": checks.get("install_receipt_company_snapshot_help_passed") is True,
            "company_snapshot_next_command": checks.get("install_receipt_company_snapshot_next_command_present") is True,
            "mcp_operability": checks.get("mcp_operability_receipt_go") is True
            and checks.get("mcp_operability_installed_entrypoint") is True
            and checks.get("mcp_operability_no_arbitrary_shell") is True,
        },
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
            "install_result_omitted": True,
        },
    }
    receipt["receipt_body_sha256"] = _receipt_body_sha256(receipt)
    receipt["receipt_checks"] = _receipt_checks(receipt)
    return receipt


def _receipt_body_sha256(receipt: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_body_sha256", "receipt_checks"}
    }
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _receipt_checks(receipt: dict[str, Any]) -> dict[str, bool]:
    serialized = json.dumps(receipt, ensure_ascii=False)
    home = str(Path.home())
    root = str(_repo_root())
    body_hash = receipt.get("receipt_body_sha256")
    verified_checks = receipt.get("verified_checks") if isinstance(receipt.get("verified_checks"), dict) else {}
    privacy = receipt.get("privacy") if isinstance(receipt.get("privacy"), dict) else {}
    return {
        "schema_version_present": receipt.get("schema_version") == RECEIPT_SCHEMA_VERSION,
        "safe_to_share_true": receipt.get("safe_to_share") is True,
        "status_pass": receipt.get("status") == "pass",
        "absolute_paths_omitted": root not in serialized and (not home or home not in serialized),
        "install_result_omitted": privacy.get("install_result_omitted") is True,
        "raw_private_project_data_omitted": privacy.get("raw_private_project_data_included") is False,
        "secrets_omitted": privacy.get("secrets_included") is False,
        "verified_checks_all_true": bool(verified_checks) and all(value is True for value in verified_checks.values()),
        "company_snapshot_help_verified": verified_checks.get("install_receipt_company_snapshot_help_passed") is True,
        "mcp_operability_verified": verified_checks.get("mcp_operability_receipt_go") is True
        and verified_checks.get("mcp_operability_installed_entrypoint") is True
        and verified_checks.get("mcp_operability_no_arbitrary_shell") is True,
        "receipt_body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "receipt_body_hash_matched": body_hash == _receipt_body_sha256(receipt),
    }


def _verify_shareable_receipt(receipt: dict[str, Any]) -> None:
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError("install kit receipt schema_version이 올바르지 않습니다.")
    if receipt.get("status") != "pass":
        raise ValueError(f"install kit receipt status가 pass가 아닙니다: {receipt.get('status')}")
    checks = receipt.get("receipt_checks") if isinstance(receipt.get("receipt_checks"), dict) else {}
    if not checks:
        raise ValueError("install kit receipt_checks가 없습니다.")
    failed = [name for name, passed in checks.items() if passed is not True]
    if failed:
        raise ValueError("install kit receipt 안전 점검 실패: " + ", ".join(failed))
    if receipt.get("receipt_body_sha256") != _receipt_body_sha256(receipt):
        raise ValueError("install kit receipt 본문 해시가 일치하지 않습니다.")


def _verify_manifest(extract_dir: Path, manifest: dict[str, Any]) -> dict[str, bool]:
    listed_files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
    file_paths = {
        str(item.get("path") or "")
        for item in listed_files
        if isinstance(item, dict)
    }
    wheel_paths = [path for path in file_paths if path.startswith("wheels/") and path.endswith(".whl")]
    checks: dict[str, bool] = {
        "schema_version": manifest.get("schema_version") == INSTALL_KIT_SCHEMA_VERSION,
        "required_files_present": REQUIRED_FILES.issubset(file_paths | {MANIFEST_NAME}),
        "wheel_present": bool(wheel_paths),
        "python_requires_present": manifest.get("python_requires") == ">=3.11",
        "entrypoint_present": manifest.get("entrypoint") == "cambrian",
        "mcp_entrypoint_present": manifest.get("mcp_entrypoint") == "cambrian-mcp",
        "install_commands_present": isinstance(manifest.get("install_commands"), dict)
        and bool(manifest.get("install_commands", {}).get("project")),
        "files_hashes_match": True,
    }
    for item in listed_files:
        if not isinstance(item, dict):
            checks["files_hashes_match"] = False
            continue
        rel = str(item.get("path") or "")
        path = extract_dir / rel
        if not path.exists() or path.stat().st_size != int(item.get("bytes") or -1) or _sha256(path) != item.get("sha256"):
            checks["files_hashes_match"] = False
    return checks


def _default_zip() -> Path:
    root = _repo_root()
    candidates = sorted((root / "dist").glob("cambrian-install-kit-*.zip"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return root / "dist" / "cambrian-install-kit-0.3.0.zip"
    return candidates[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambrian install kit ZIP을 검증한다.")
    parser.add_argument("--zip", type=Path, default=None, help="검증할 install kit ZIP")
    parser.add_argument("--install-check", action="store_true", help="ZIP을 풀어 실제 설치까지 확인한다.")
    parser.add_argument("--offline", action="store_true", help="install check에서 --offline 설치를 사용한다.")
    parser.add_argument("--receipt", type=Path, default=None, help="공유 가능한 install kit 검증 receipt JSON 출력 경로")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="ZIP 없이 install kit 검증 receipt JSON만 검증한다.")
    args = parser.parse_args()
    if args.verify_receipt:
        receipt = verify_shareable_receipt_file(args.verify_receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return
    result = verify_install_kit(args.zip or _default_zip(), install_check=bool(args.install_check), offline=bool(args.offline))
    if args.receipt:
        receipt_path = write_shareable_receipt(args.receipt, result)
        print(json.dumps({"receipt": str(receipt_path), "status": "written"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
