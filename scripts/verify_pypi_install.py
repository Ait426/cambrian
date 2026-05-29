from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PYPI_INSTALL_RECEIPT_SCHEMA_VERSION = "cambrian_pypi_install_verification_v0_1"
PYPI_INSTALL_RECEIPT_NAME = "pypi_install_verification_receipt.json"
PYPI_SIMPLE_URL = "https://pypi.org/simple/"
TESTPYPI_SIMPLE_URL = "https://test.pypi.org/simple/"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _venv_python(venv_dir: Path) -> Path:
    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    return scripts_dir / ("python.exe" if os.name == "nt" else "python")


def _venv_executable(venv_dir: Path, name: str) -> Path:
    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return scripts_dir / f"{name}{suffix}"


def _run(command: list[str | Path], cwd: Path, *, timeout: int = 240) -> dict[str, Any]:
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


def _package_spec(package: str, version: str | None) -> str:
    if version:
        return f"{package}=={version}"
    return package


def _install_command(
    python: Path,
    *,
    package: str,
    version: str | None,
    repository: str,
    wheel: Path | None,
) -> list[str | Path]:
    if wheel:
        return [python, "-m", "pip", "install", str(wheel)]
    package_spec = _package_spec(package, version)
    if repository == "testpypi":
        return [
            python,
            "-m",
            "pip",
            "install",
            "--index-url",
            TESTPYPI_SIMPLE_URL,
            "--extra-index-url",
            PYPI_SIMPLE_URL,
            package_spec,
        ]
    if repository == "pypi":
        return [python, "-m", "pip", "install", "--index-url", PYPI_SIMPLE_URL, package_spec]
    raise ValueError("repository must be pypi or testpypi")


def _redact_local_paths(value: str, *, root: Path, temp_dir: Path, wheel: Path | None) -> str:
    replacements = [
        (str(root.resolve()), "<repo>"),
        (str(temp_dir.resolve()), "<venv>"),
        (str(Path.home()), "<home>"),
    ]
    if wheel is not None:
        replacements.append((str(wheel.resolve()), wheel.name))
        replacements.append((str(wheel.resolve().parent), "dist/pypi"))
    redacted = value
    for before, after in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        if before:
            redacted = redacted.replace(before, after)
    return redacted


def _command_receipt_steps(
    commands: list[dict[str, Any]],
    *,
    root: Path,
    temp_dir: Path,
    wheel: Path | None,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for command in commands:
        stdout = str(command.get("stdout") or "")
        stderr = str(command.get("stderr") or "")
        steps.append(
            {
                "command": [
                    _redact_local_paths(str(item), root=root, temp_dir=temp_dir, wheel=wheel)
                    for item in command.get("command", [])
                ],
                "cwd": _redact_local_paths(str(command.get("cwd") or ""), root=root, temp_dir=temp_dir, wheel=wheel),
                "exit_code": command.get("exit_code"),
                "status": command.get("status"),
                "stdout_bytes": len(stdout.encode("utf-8")),
                "stderr_bytes": len(stderr.encode("utf-8")),
                "stdout_sha256": _sha256_text(stdout) if stdout else None,
                "stderr_sha256": _sha256_text(stderr) if stderr else None,
            }
        )
    return steps


def verify_install(
    *,
    repository: str,
    package: str,
    version: str | None,
    wheel: Path | None,
    receipt_path: Path | None,
) -> dict[str, Any]:
    root = _repo_root()
    target_receipt = receipt_path or root / "dist" / PYPI_INSTALL_RECEIPT_NAME
    target_receipt.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="cambrian-pypi-install-")).resolve()
    commands: list[dict[str, Any]] = []
    try:
        venv.EnvBuilder(with_pip=True).create(temp_dir)
        python = _venv_python(temp_dir)
        cambrian = _venv_executable(temp_dir, "cambrian")
        commands.append(_run([python, "-m", "pip", "install", "--upgrade", "pip"], cwd=root, timeout=240))
        commands.append(
            _run(
                _install_command(
                    python,
                    package=package,
                    version=version,
                    repository=repository,
                    wheel=wheel,
                ),
                cwd=root,
                timeout=360,
            )
        )
        commands.append(_run([cambrian, "--help"], cwd=root, timeout=120))
        commands.append(_run([cambrian, "doctor", "--json"], cwd=root, timeout=120))
        checks = {
            "venv_created": python.exists(),
            "pip_upgrade_passed": commands[0]["exit_code"] == 0,
            "install_passed": commands[1]["exit_code"] == 0,
            "cli_help_passed": commands[2]["exit_code"] == 0,
            "doctor_passed": commands[3]["exit_code"] == 0,
            "no_token_required": "TWINE_PASSWORD" not in json.dumps(commands, ensure_ascii=False),
        }
        failed = [name for name, passed in checks.items() if passed is not True]
        receipt = _install_receipt(
            repository=repository,
            package=package,
            version=version,
            wheel=wheel,
            checks=checks,
            failed=failed,
            commands=commands,
            root=root,
            temp_dir=temp_dir,
        )
        target_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verify_pypi_install_receipt_file(target_receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        if failed:
            raise SystemExit(1)
        return receipt
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _install_receipt(
    *,
    repository: str,
    package: str,
    version: str | None,
    wheel: Path | None,
    checks: dict[str, bool],
    failed: list[str],
    commands: list[dict[str, Any]],
    root: Path,
    temp_dir: Path,
) -> dict[str, Any]:
    receipt = {
        "schema_version": PYPI_INSTALL_RECEIPT_SCHEMA_VERSION,
        "generated_at": _now(),
        "status": "verified" if not failed else "blocked",
        "safe_to_share": True,
        "repository": repository,
        "package": package,
        "version": version,
        "wheel": wheel.name if wheel else None,
        "wheel_sha256": _sha256(wheel) if wheel else None,
        "checks": checks,
        "failed_checks": failed,
        "command_steps": _command_receipt_steps(commands, root=root, temp_dir=temp_dir, wheel=wheel),
        "privacy": {
            "absolute_paths_included": False,
            "command_output_text_included": False,
            "tokens_included": False,
        },
    }
    receipt["pypi_install_receipt_body_sha256"] = _receipt_body_sha256(receipt)
    receipt["receipt_checks"] = _receipt_checks(receipt, root=root, temp_dir=temp_dir)
    return receipt


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"pypi_install_receipt_body_sha256", "receipt_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _receipt_checks(payload: dict[str, Any], *, root: Path, temp_dir: Path | None = None) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    command_steps = payload.get("command_steps") if isinstance(payload.get("command_steps"), list) else []
    body_hash = payload.get("pypi_install_receipt_body_sha256")
    temp_text = str(temp_dir) if temp_dir else ""
    return {
        "schema_version_present": payload.get("schema_version") == PYPI_INSTALL_RECEIPT_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "status_verified_or_blocked": payload.get("status") in {"verified", "blocked"},
        "absolute_paths_omitted": str(root) not in serialized
        and (not home or home not in serialized)
        and (not temp_text or temp_text not in serialized),
        "command_output_text_omitted": privacy.get("command_output_text_included") is False
        and all("stdout" not in step and "stderr" not in step for step in command_steps if isinstance(step, dict)),
        "tokens_omitted": privacy.get("tokens_included") is False and "TWINE_PASSWORD" not in serialized,
        "commands_have_statuses": bool(command_steps)
        and all(
            isinstance(step, dict)
            and step.get("status") in {"passed", "failed"}
            and isinstance(step.get("exit_code"), int)
            for step in command_steps
        ),
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def verify_pypi_install_receipt_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PyPI install receipt JSON object expected.")
    _verify_pypi_install_receipt(payload)
    return payload


def _verify_pypi_install_receipt(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PYPI_INSTALL_RECEIPT_SCHEMA_VERSION:
        raise ValueError("PyPI install receipt schema_version mismatch.")
    receipt_checks = payload.get("receipt_checks") if isinstance(payload.get("receipt_checks"), dict) else {}
    if not receipt_checks:
        raise ValueError("PyPI install receipt checks missing.")
    failed = [name for name, passed in receipt_checks.items() if passed is not True]
    if failed:
        raise ValueError("PyPI install receipt verification failed: " + ", ".join(failed))
    if payload.get("pypi_install_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise ValueError("PyPI install receipt body hash mismatch.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Cambrian installs from PyPI/TestPyPI or a built wheel.")
    parser.add_argument("--repository", choices=["pypi", "testpypi"], default="pypi")
    parser.add_argument("--package", default="cambrian")
    parser.add_argument("--version", default=None)
    parser.add_argument("--wheel", type=Path, default=None, help="Verify a local wheel instead of an index install.")
    parser.add_argument("--receipt", type=Path, default=None, help="Receipt path. Default: dist/pypi_install_verification_receipt.json")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Verify an existing PyPI install receipt without reinstalling.")
    args = parser.parse_args()
    if args.verify_receipt:
        payload = verify_pypi_install_receipt_file(args.verify_receipt)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    wheel = args.wheel.resolve() if args.wheel else None
    if wheel and not wheel.exists():
        raise FileNotFoundError(f"wheel not found: {wheel}")
    verify_install(
        repository=args.repository,
        package=args.package,
        version=args.version,
        wheel=wheel,
        receipt_path=args.receipt,
    )


if __name__ == "__main__":
    main()
