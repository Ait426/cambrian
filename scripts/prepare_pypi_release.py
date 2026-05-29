from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
import venv
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PYPI_RECEIPT_SCHEMA_VERSION = "cambrian_pypi_release_receipt_v0_1"
PYPI_PREFLIGHT_RECEIPT_SCHEMA_VERSION = "cambrian_pypi_publish_preflight_receipt_v0_1"
PYPI_PUBLISH_READY_SCHEMA_VERSION = "cambrian_pypi_publish_ready_v0_1"
DEFAULT_DIST_SUBDIR = "pypi"
PYPI_RECEIPT_NAME = "pypi_release_receipt.json"
PYPI_LOCAL_WHEEL_INSTALL_RECEIPT_NAME = "pypi_local_wheel_install_receipt.json"
PYPI_PREFLIGHT_RECEIPT_NAME = "pypi_publish_preflight_receipt.json"
TESTPYPI_INSTALL_RECEIPT_NAME = "pypi_testpypi_install_receipt.json"
PYPI_PUBLISH_READY_RECEIPT_TEMPLATE = "pypi-publish-ready-{repository}.json"
PYPI_UPLOAD_URL = "https://upload.pypi.org/legacy/"
TESTPYPI_UPLOAD_URL = "https://test.pypi.org/legacy/"
PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _venv_python(venv_dir: Path) -> Path:
    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    return scripts_dir / ("python.exe" if os.name == "nt" else "python")


def _run(
    command: list[str | Path],
    cwd: Path,
    *,
    timeout: int = 240,
    env: dict[str, str] | None = None,
    redact_env: bool = False,
) -> dict[str, Any]:
    result = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    command_for_receipt = [str(item) for item in command]
    if redact_env:
        command_for_receipt = [
            "<redacted>" if "TWINE_PASSWORD" in str(item) else str(item)
            for item in command_for_receipt
        ]
    return {
        "command": command_for_receipt,
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "passed" if result.returncode == 0 else "failed",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_pyproject(root: Path) -> dict[str, Any]:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def _project_metadata(root: Path) -> dict[str, Any]:
    pyproject = _read_pyproject(root)
    project = pyproject.get("project", {})
    return {
        "name": str(project.get("name") or ""),
        "version": str(project.get("version") or ""),
        "description": str(project.get("description") or ""),
        "readme": str(project.get("readme") or ""),
        "requires_python": str(project.get("requires-python") or ""),
        "license": str(project.get("license") or ""),
    }


def _package_name_status(name: str) -> dict[str, Any]:
    url = PYPI_JSON_URL.format(name=name)
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"status": "available", "url": url}
        return {"status": "error", "url": url, "error": f"HTTP {exc.code}"}
    except OSError as exc:
        return {"status": "unknown", "url": url, "error": str(exc)}
    releases = payload.get("releases") if isinstance(payload, dict) else {}
    return {
        "status": "exists",
        "url": url,
        "latest_version": payload.get("info", {}).get("version") if isinstance(payload.get("info"), dict) else None,
        "release_count": len(releases) if isinstance(releases, dict) else None,
    }


def _ensure_build_tools(root: Path, tool_venv: Path) -> tuple[Path, list[dict[str, Any]]]:
    if tool_venv.exists():
        shutil.rmtree(tool_venv)
    venv.EnvBuilder(with_pip=True).create(tool_venv)
    python = _venv_python(tool_venv)
    commands = [
        _run([python, "-m", "pip", "install", "--upgrade", "pip"], cwd=root, timeout=240),
        _run([python, "-m", "pip", "install", "build>=1.2", "twine>=6.0"], cwd=root, timeout=240),
    ]
    failed = [item for item in commands if item["exit_code"] != 0]
    if failed:
        raise RuntimeError("PyPI build tool 설치 실패")
    return python, commands


def _clean_dist_dir(dist_dir: Path) -> None:
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)


def _built_files(dist_dir: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(dist_dir.iterdir()):
        if path.is_file():
            files.append(
                {
                    "file": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    return files


def _redact_local_paths(value: str, *, root: Path, tool_venv: Path | None = None, dist_dir: Path | None = None) -> str:
    replacements = [
        (str(root.resolve()), "<repo>"),
        (str(Path.home()), "<home>"),
    ]
    if tool_venv is not None:
        replacements.append((str(tool_venv.resolve()), "<tool-venv>"))
    if dist_dir is not None:
        replacements.append((str(dist_dir.resolve()), "dist/pypi"))
    redacted = value
    for before, after in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        if before:
            redacted = redacted.replace(before, after)
    return redacted


def _safe_receipt_path(path: Path, *, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.name


def _command_receipt_steps(
    commands: list[dict[str, Any]],
    *,
    root: Path,
    tool_venv: Path,
    dist_dir: Path,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for command in commands:
        stdout = str(command.get("stdout") or "")
        stderr = str(command.get("stderr") or "")
        steps.append(
            {
                "command": [
                    _redact_local_paths(str(item), root=root, tool_venv=tool_venv, dist_dir=dist_dir)
                    for item in command.get("command", [])
                ],
                "cwd": _redact_local_paths(str(command.get("cwd") or ""), root=root, tool_venv=tool_venv, dist_dir=dist_dir),
                "exit_code": command.get("exit_code"),
                "status": command.get("status"),
                "stdout_bytes": len(stdout.encode("utf-8")),
                "stderr_bytes": len(stderr.encode("utf-8")),
                "stdout_sha256": _sha256_text(stdout) if stdout else None,
                "stderr_sha256": _sha256_text(stderr) if stderr else None,
            }
        )
    return steps


def _wheel_metadata_has_local_paths(wheel_path: Path, root: Path) -> bool:
    root_text = str(root)
    home_text = str(Path.home())
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        for name in metadata_names:
            text = archive.read(name).decode("utf-8", errors="replace")
            if root_text in text or (home_text and home_text in text):
                return True
    return False


def prepare_release(
    dist_dir: Path | None = None,
    upload: str | None = None,
    skip_name_check: bool = False,
    testpypi_install_receipt: Path | None = None,
    publish_ready_receipt: Path | None = None,
) -> dict[str, Any]:
    root = _repo_root()
    metadata = _project_metadata(root)
    target_dist = (dist_dir or root / "dist" / DEFAULT_DIST_SUBDIR).resolve()
    testpypi_install_gate: dict[str, Any] | None = None
    publish_ready_gate: dict[str, Any] | None = None
    if upload == "pypi":
        gate_receipt = (
            testpypi_install_receipt
            or root / "dist" / TESTPYPI_INSTALL_RECEIPT_NAME
        )
        testpypi_install_gate = _verify_testpypi_install_gate(
            gate_receipt,
            expected_package=metadata["name"],
            expected_version=metadata["version"],
        )
    upload_env_gate = _verify_upload_environment(upload) if upload else None
    if upload:
        gate_receipt = publish_ready_receipt or root / "dist" / PYPI_PUBLISH_READY_RECEIPT_TEMPLATE.format(repository=upload)
        publish_ready_gate = _verify_publish_ready_gate(
            gate_receipt,
            repository=upload,
            expected_package=metadata["name"],
            expected_version=metadata["version"],
            root=root,
        )
    tool_venv = Path(tempfile.mkdtemp(prefix="cambrian-pypi-tools-")).resolve()
    commands: list[dict[str, Any]] = []
    upload_result: dict[str, Any] | None = None
    try:
        tool_python, setup_commands = _ensure_build_tools(root, tool_venv)
        commands.extend(setup_commands)
        _clean_dist_dir(target_dist)
        build_step = _run([tool_python, "-m", "build", str(root), "--sdist", "--wheel", "--outdir", target_dist], cwd=root, timeout=300)
        commands.append(build_step)
        if build_step["exit_code"] != 0:
            raise RuntimeError("PyPI dist build 실패")
        twine_check = _run([tool_python, "-m", "twine", "check", *sorted(target_dist.glob("*"))], cwd=root, timeout=180)
        commands.append(twine_check)
        if twine_check["exit_code"] != 0:
            raise RuntimeError("twine check 실패")
        name_status = {"status": "skipped"}
        if not skip_name_check:
            name_status = _package_name_status(metadata["name"])
        files = _built_files(target_dist)
        wheel_files = [target_dist / item["file"] for item in files if item["file"].endswith(".whl")]
        sdist_files = [item for item in files if item["file"].endswith(".tar.gz")]
        checks = {
            "metadata_name_present": metadata["name"] == "cambrian",
            "metadata_version_present": bool(metadata["version"]),
            "metadata_description_present": bool(metadata["description"]),
            "metadata_readme_present": metadata["readme"] == "README.md",
            "metadata_license_present": metadata["license"] == "MIT",
            "wheel_built": bool(wheel_files),
            "sdist_built": bool(sdist_files),
            "twine_check_passed": twine_check["exit_code"] == 0,
            "wheel_metadata_has_no_local_paths": bool(wheel_files)
            and all(not _wheel_metadata_has_local_paths(path, root) for path in wheel_files),
            "pypi_name_not_known_taken": name_status.get("status") in {"available", "skipped", "unknown"},
            "dist_dir_isolated": target_dist.name == DEFAULT_DIST_SUBDIR and target_dist.parent.name == "dist",
        }
        if upload:
            checks["upload_environment_verified"] = upload_env_gate is not None and upload_env_gate["status"] == "verified"
            checks["publish_ready_receipt_verified"] = publish_ready_gate is not None and publish_ready_gate["status"] == "verified"
        if upload == "pypi":
            checks["testpypi_install_receipt_verified"] = True
        if upload:
            upload_result = _upload(tool_python, target_dist, upload)
            checks["upload_passed"] = upload_result["exit_code"] == 0
        receipt = _release_receipt(
            metadata=metadata,
            files=files,
            name_status=name_status,
            checks=checks,
            upload=upload,
            upload_result=upload_result,
            upload_env_gate=upload_env_gate,
            testpypi_install_gate=testpypi_install_gate,
            publish_ready_gate=publish_ready_gate,
            commands=commands,
            root=root,
            tool_venv=tool_venv,
            dist_dir=target_dist,
        )
        receipt_path = root / "dist" / PYPI_RECEIPT_NAME
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verify_pypi_release_receipt_file(receipt_path)
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        if receipt["failed_checks"]:
            raise SystemExit(1)
        return receipt
    finally:
        shutil.rmtree(tool_venv, ignore_errors=True)


def _release_receipt(
    *,
    metadata: dict[str, Any],
    files: list[dict[str, Any]],
    name_status: dict[str, Any],
    checks: dict[str, bool],
    upload: str | None,
    upload_result: dict[str, Any] | None,
    upload_env_gate: dict[str, Any] | None = None,
    testpypi_install_gate: dict[str, Any] | None = None,
    publish_ready_gate: dict[str, Any] | None = None,
    commands: list[dict[str, Any]],
    root: Path,
    tool_venv: Path,
    dist_dir: Path,
) -> dict[str, Any]:
    failed = [name for name, passed in checks.items() if passed is not True]
    sanitized_upload_result = None
    if upload_result is not None:
        sanitized_upload_result = _command_receipt_steps(
            [upload_result],
            root=root,
            tool_venv=tool_venv,
            dist_dir=dist_dir,
        )[0]
    receipt = {
        "schema_version": PYPI_RECEIPT_SCHEMA_VERSION,
        "generated_at": _now(),
        "status": "ready" if not failed else "blocked",
        "safe_to_share": True,
        "metadata": metadata,
        "dist_dir": "dist/pypi",
        "files": files,
        "name_status": name_status,
        "checks": checks,
        "failed_checks": failed,
        "upload_requested": upload,
        "upload_result": sanitized_upload_result,
        "upload_env_gate": upload_env_gate,
        "testpypi_install_gate": testpypi_install_gate,
        "publish_ready_gate": publish_ready_gate,
        "command_steps": _command_receipt_steps(commands, root=root, tool_venv=tool_venv, dist_dir=dist_dir),
        "publish_commands": {
            "testpypi": "TWINE_USERNAME=__token__ TWINE_PASSWORD=<testpypi-token> python scripts/prepare_pypi_release.py --upload testpypi --publish-ready-receipt dist/pypi-publish-ready-testpypi.json",
            "pypi": "TWINE_USERNAME=__token__ TWINE_PASSWORD=<pypi-token> python scripts/prepare_pypi_release.py --upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --publish-ready-receipt dist/pypi-publish-ready-pypi.json",
        },
        "privacy": {
            "absolute_paths_included": False,
            "command_output_text_included": False,
            "tokens_included": False,
        },
    }
    receipt["pypi_release_receipt_body_sha256"] = _receipt_body_sha256(receipt)
    receipt["receipt_checks"] = _receipt_checks(receipt, root=root)
    return receipt


def _verify_testpypi_install_gate(
    receipt_path: Path,
    *,
    expected_package: str,
    expected_version: str,
) -> dict[str, Any]:
    try:
        from scripts.verify_pypi_install import verify_pypi_install_receipt_file
    except ModuleNotFoundError:
        from verify_pypi_install import verify_pypi_install_receipt_file

    resolved = receipt_path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(
            "Final PyPI upload requires a verified TestPyPI install receipt: "
            f"{receipt_path}"
        )
    receipt = verify_pypi_install_receipt_file(resolved)
    checks = receipt.get("checks") if isinstance(receipt.get("checks"), dict) else {}
    receipt_checks = receipt.get("receipt_checks") if isinstance(receipt.get("receipt_checks"), dict) else {}
    gate_checks = {
        "repository_testpypi": receipt.get("repository") == "testpypi",
        "package_matched": receipt.get("package") == expected_package,
        "version_matched": receipt.get("version") == expected_version,
        "status_verified": receipt.get("status") == "verified",
        "install_checks_all_true": bool(checks) and all(value is True for value in checks.values()),
        "receipt_checks_all_true": bool(receipt_checks) and all(value is True for value in receipt_checks.values()),
    }
    failed = [name for name, passed in gate_checks.items() if passed is not True]
    if failed:
        raise ValueError("TestPyPI install receipt gate failed: " + ", ".join(failed))
    return {
        "status": "verified",
        "receipt": resolved.name,
        "receipt_body_sha256": receipt.get("pypi_install_receipt_body_sha256"),
        "checks": gate_checks,
    }


def _verify_publish_ready_gate(
    receipt_path: Path,
    *,
    repository: str,
    expected_package: str,
    expected_version: str,
    root: Path,
) -> dict[str, Any]:
    resolved = receipt_path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(
            "PyPI publish-ready receipt is required before upload: "
            f"{receipt_path}"
        )
    receipt = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("PyPI publish-ready receipt JSON object expected.")
    publish_ready_checks = receipt.get("publish_ready_checks") if isinstance(receipt.get("publish_ready_checks"), dict) else {}
    package = receipt.get("package") if isinstance(receipt.get("package"), dict) else {}
    gate_checks = {
        "schema_version": receipt.get("schema_version") == PYPI_PUBLISH_READY_SCHEMA_VERSION,
        "repository_matched": receipt.get("repository") == repository,
        "verdict_go": receipt.get("verdict") == "GO",
        "package_matched": package.get("name") == expected_package,
        "version_matched": package.get("version") == expected_version,
        "safe_to_share": receipt.get("safe_to_share") is True,
        "publish_ready_checks_all_true": bool(publish_ready_checks)
        and all(value is True for value in publish_ready_checks.values()),
    }
    failed = [name for name, passed in gate_checks.items() if passed is not True]
    if failed:
        raise ValueError("PyPI publish-ready receipt gate failed: " + ", ".join(failed))
    return {
        "status": "verified",
        "repository": repository,
        "receipt": _safe_receipt_path(resolved, root=root),
        "verdict": receipt.get("verdict"),
        "receipt_body_sha256": receipt.get("publish_ready_body_sha256"),
        "wheel_sha256": package.get("wheel_sha256"),
        "checks": gate_checks,
    }


def _verify_upload_environment(repository: str) -> dict[str, Any]:
    if repository not in {"testpypi", "pypi"}:
        raise ValueError("repository must be testpypi or pypi")
    username = os.environ.get("TWINE_USERNAME", "__token__")
    password = os.environ.get("TWINE_PASSWORD")
    if username != "__token__":
        raise RuntimeError("TWINE_USERNAME must be __token__ for Cambrian PyPI API-token uploads.")
    if not password:
        raise RuntimeError("TWINE_PASSWORD must be set in the local environment before upload.")
    return {
        "status": "verified",
        "repository": repository,
        "twine_username": "__token__",
        "twine_password_present": True,
        "twine_password_recorded": False,
    }


def _upload_environment_status(repository: str) -> dict[str, Any]:
    try:
        return _verify_upload_environment(repository)
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "blocked",
            "repository": repository,
            "twine_username_required": "__token__",
            "twine_username_is_token": os.environ.get("TWINE_USERNAME", "__token__") == "__token__",
            "twine_password_present": bool(os.environ.get("TWINE_PASSWORD")),
            "twine_password_recorded": False,
            "reason": str(exc),
        }


def _testpypi_install_gate_status(
    receipt_path: Path,
    *,
    expected_package: str,
    expected_version: str,
    root: Path,
) -> dict[str, Any]:
    try:
        return _verify_testpypi_install_gate(
            receipt_path,
            expected_package=expected_package,
            expected_version=expected_version,
        )
    except FileNotFoundError:
        return {
            "status": "blocked",
            "receipt": _safe_receipt_path(receipt_path, root=root),
            "reason": "missing_testpypi_install_receipt",
            "checks": {
                "repository_testpypi": False,
                "package_matched": False,
                "version_matched": False,
                "status_verified": False,
                "install_checks_all_true": False,
                "receipt_checks_all_true": False,
            },
        }
    except ValueError as exc:
        return {
            "status": "blocked",
            "receipt": _safe_receipt_path(receipt_path, root=root),
            "reason": "invalid_testpypi_install_receipt",
            "detail": str(exc).split(":", 1)[0],
            "checks": {
                "repository_testpypi": False,
                "package_matched": False,
                "version_matched": False,
                "status_verified": False,
                "install_checks_all_true": False,
                "receipt_checks_all_true": False,
            },
        }


def _safe_error_detail(message: str, *, root: Path) -> str:
    return _redact_local_paths(message, root=root)


def _release_receipt_gate_status(receipt_path: Path, *, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    safe_receipt = _safe_receipt_path(receipt_path, root=root)
    checks = {
        "status_ready": False,
        "artifacts_verified": False,
    }
    try:
        receipt = verify_pypi_release_receipt_file(receipt_path)
    except FileNotFoundError:
        return {}, {
            "status": "blocked",
            "receipt": safe_receipt,
            "reason": "missing_release_receipt",
            "checks": checks,
        }
    except ValueError as exc:
        return {}, {
            "status": "blocked",
            "receipt": safe_receipt,
            "reason": "invalid_release_receipt",
            "detail": _safe_error_detail(str(exc), root=root).split(":", 1)[0],
            "checks": checks,
        }
    artifact_checks = receipt.get("artifact_verification_checks") if isinstance(receipt.get("artifact_verification_checks"), dict) else {}
    checks = {
        "status_ready": receipt.get("status") == "ready",
        "artifacts_verified": bool(artifact_checks) and all(value is True for value in artifact_checks.values()),
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    return receipt, {
        "status": "verified" if not failed else "blocked",
        "receipt": safe_receipt,
        "reason": None if not failed else "release_receipt_not_ready",
        "receipt_body_sha256": receipt.get("pypi_release_receipt_body_sha256"),
        "checks": checks,
    }


def _local_install_receipt_gate_status(
    receipt_path: Path,
    *,
    expected_package: str,
    expected_version: str,
    expected_wheel_sha256: str,
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        from scripts.verify_pypi_install import verify_pypi_install_receipt_file
    except ModuleNotFoundError:
        from verify_pypi_install import verify_pypi_install_receipt_file

    safe_receipt = _safe_receipt_path(receipt_path, root=root)
    checks = {
        "status_verified": False,
        "package_matched": False,
        "version_matched": False,
        "wheel_hash_matched": False,
    }
    try:
        receipt = verify_pypi_install_receipt_file(receipt_path)
    except FileNotFoundError:
        return {}, {
            "status": "blocked",
            "receipt": safe_receipt,
            "reason": "missing_local_install_receipt",
            "checks": checks,
        }
    except ValueError as exc:
        return {}, {
            "status": "blocked",
            "receipt": safe_receipt,
            "reason": "invalid_local_install_receipt",
            "detail": _safe_error_detail(str(exc), root=root).split(":", 1)[0],
            "checks": checks,
        }
    checks = {
        "status_verified": receipt.get("status") == "verified",
        "package_matched": bool(expected_package) and receipt.get("package") == expected_package,
        "version_matched": bool(expected_version) and receipt.get("version") == expected_version,
        "wheel_hash_matched": bool(expected_wheel_sha256) and receipt.get("wheel_sha256") == expected_wheel_sha256,
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    return receipt, {
        "status": "verified" if not failed else "blocked",
        "receipt": safe_receipt,
        "reason": None if not failed else "local_install_receipt_not_matched",
        "receipt_body_sha256": receipt.get("pypi_install_receipt_body_sha256"),
        "checks": checks,
    }


def preflight_publish(
    *,
    repository: str,
    release_receipt: Path | None = None,
    local_install_receipt: Path | None = None,
    testpypi_install_receipt: Path | None = None,
    receipt_path: Path | None = None,
    require_token_env: bool = False,
) -> dict[str, Any]:
    if repository not in {"testpypi", "pypi"}:
        raise ValueError("repository must be testpypi or pypi")
    root = _repo_root()
    release_path = release_receipt or root / "dist" / PYPI_RECEIPT_NAME
    local_install_path = local_install_receipt or root / "dist" / PYPI_LOCAL_WHEEL_INSTALL_RECEIPT_NAME
    target_receipt = receipt_path or root / "dist" / PYPI_PREFLIGHT_RECEIPT_NAME
    target_receipt.parent.mkdir(parents=True, exist_ok=True)

    release, release_gate = _release_receipt_gate_status(release_path, root=root)
    metadata = release.get("metadata") if isinstance(release.get("metadata"), dict) else {}
    files = release.get("files") if isinstance(release.get("files"), list) else []
    wheel_files = [item for item in files if isinstance(item, dict) and str(item.get("file") or "").endswith(".whl")]
    wheel_sha = str(wheel_files[0].get("sha256") or "") if wheel_files else ""
    local_install, local_install_gate = _local_install_receipt_gate_status(
        local_install_path,
        expected_package=str(metadata.get("name") or ""),
        expected_version=str(metadata.get("version") or ""),
        expected_wheel_sha256=wheel_sha,
        root=root,
    )
    token_env = _upload_environment_status(repository)
    testpypi_gate = None
    if repository == "pypi":
        gate_receipt = testpypi_install_receipt or root / "dist" / TESTPYPI_INSTALL_RECEIPT_NAME
        testpypi_gate = _testpypi_install_gate_status(
            gate_receipt,
            expected_package=str(metadata.get("name") or ""),
            expected_version=str(metadata.get("version") or ""),
            root=root,
        )

    checks = {
        "release_receipt_ready": release_gate.get("checks", {}).get("status_ready") is True,
        "release_receipt_artifacts_verified": release_gate.get("checks", {}).get("artifacts_verified") is True,
        "local_install_receipt_verified": local_install_gate.get("checks", {}).get("status_verified") is True,
        "local_install_package_matched": local_install_gate.get("checks", {}).get("package_matched") is True,
        "local_install_version_matched": local_install_gate.get("checks", {}).get("version_matched") is True,
        "local_install_wheel_hash_matched": local_install_gate.get("checks", {}).get("wheel_hash_matched") is True,
        "token_env_ready": token_env.get("status") == "verified",
        "testpypi_install_receipt_verified": repository != "pypi"
        or (isinstance(testpypi_gate, dict) and testpypi_gate.get("status") == "verified"),
    }
    blocking_check_names = [
        "release_receipt_ready",
        "release_receipt_artifacts_verified",
        "local_install_receipt_verified",
        "local_install_package_matched",
        "local_install_version_matched",
        "local_install_wheel_hash_matched",
        "testpypi_install_receipt_verified",
    ]
    if require_token_env:
        blocking_check_names.append("token_env_ready")
    blocking = [name for name in blocking_check_names if checks.get(name) is not True]
    status = "blocked"
    if not blocking:
        if token_env.get("status") == "verified":
            status = f"ready_to_upload_{repository}"
        else:
            status = f"ready_for_{repository}_token"
    receipt = {
        "schema_version": PYPI_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
        "generated_at": _now(),
        "status": status,
        "safe_to_share": True,
        "repository": repository,
        "require_token_env": require_token_env,
        "release_receipt": _safe_receipt_path(release_path, root=root),
        "local_install_receipt": _safe_receipt_path(local_install_path, root=root),
        "testpypi_install_receipt": _safe_receipt_path(testpypi_install_receipt or root / "dist" / TESTPYPI_INSTALL_RECEIPT_NAME, root=root)
        if repository == "pypi"
        else None,
        "metadata": {
            "name": metadata.get("name"),
            "version": metadata.get("version"),
        },
        "wheel_sha256": wheel_sha or None,
        "checks": checks,
        "blocking_checks": blocking,
        "release_receipt_gate": release_gate,
        "local_install_gate": local_install_gate,
        "upload_env_gate": token_env,
        "testpypi_install_gate": testpypi_gate,
        "next_commands": _preflight_next_commands(repository),
        "privacy": {
            "absolute_paths_included": False,
            "command_output_text_included": False,
            "tokens_included": False,
        },
    }
    receipt["pypi_publish_preflight_receipt_body_sha256"] = _preflight_receipt_body_sha256(receipt)
    receipt["receipt_checks"] = _preflight_receipt_checks(receipt, root=root)
    target_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_pypi_publish_preflight_receipt_file(target_receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    if receipt["status"] == "blocked":
        raise SystemExit(1)
    return receipt


def _preflight_next_commands(repository: str) -> dict[str, str]:
    if repository == "testpypi":
        return {
            "upload": "TWINE_USERNAME=__token__ TWINE_PASSWORD=<testpypi-token> python scripts/prepare_pypi_release.py --upload testpypi --publish-ready-receipt dist/pypi-publish-ready-testpypi.json",
            "install_verify": "python scripts/verify_pypi_install.py --repository testpypi --version 0.3.0 --receipt dist/pypi_testpypi_install_receipt.json",
        }
    return {
        "upload": "TWINE_USERNAME=__token__ TWINE_PASSWORD=<pypi-token> python scripts/prepare_pypi_release.py --upload pypi --testpypi-install-receipt dist/pypi_testpypi_install_receipt.json --publish-ready-receipt dist/pypi-publish-ready-pypi.json",
        "install_verify": "python scripts/verify_pypi_install.py --repository pypi --version 0.3.0",
    }


def _preflight_receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"pypi_publish_preflight_receipt_body_sha256", "receipt_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _preflight_receipt_checks(payload: dict[str, Any], *, root: Path) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    body_hash = payload.get("pypi_publish_preflight_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PYPI_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "status_known": payload.get("status") in {
            "blocked",
            "ready_for_testpypi_token",
            "ready_for_pypi_token",
            "ready_to_upload_testpypi",
            "ready_to_upload_pypi",
        },
        "absolute_paths_omitted": str(root) not in serialized and (not home or home not in serialized),
        "command_output_text_omitted": privacy.get("command_output_text_included") is False,
        "tokens_omitted": privacy.get("tokens_included") is False
        and "TWINE_PASSWORD=" not in serialized.replace("TWINE_PASSWORD=<testpypi-token>", "").replace("TWINE_PASSWORD=<pypi-token>", ""),
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _preflight_receipt_body_sha256(payload),
    }


def verify_pypi_publish_preflight_receipt_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PyPI publish preflight receipt JSON object expected.")
    if payload.get("schema_version") != PYPI_PREFLIGHT_RECEIPT_SCHEMA_VERSION:
        raise ValueError("PyPI publish preflight receipt schema_version mismatch.")
    receipt_checks = payload.get("receipt_checks") if isinstance(payload.get("receipt_checks"), dict) else {}
    if not receipt_checks:
        raise ValueError("PyPI publish preflight receipt checks missing.")
    failed = [name for name, passed in receipt_checks.items() if passed is not True]
    if failed:
        raise ValueError("PyPI publish preflight receipt verification failed: " + ", ".join(failed))
    if payload.get("pypi_publish_preflight_receipt_body_sha256") != _preflight_receipt_body_sha256(payload):
        raise ValueError("PyPI publish preflight receipt body hash mismatch.")
    return payload


def _receipt_body_sha256(payload: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key not in {"pypi_release_receipt_body_sha256", "receipt_checks", "artifact_verification_checks"}
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _receipt_checks(payload: dict[str, Any], *, root: Path) -> dict[str, bool]:
    serialized = json.dumps(payload, ensure_ascii=False)
    home = str(Path.home())
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
    publish_commands = payload.get("publish_commands") if isinstance(payload.get("publish_commands"), dict) else {}
    command_steps = payload.get("command_steps") if isinstance(payload.get("command_steps"), list) else []
    body_hash = payload.get("pypi_release_receipt_body_sha256")
    return {
        "schema_version_present": payload.get("schema_version") == PYPI_RECEIPT_SCHEMA_VERSION,
        "safe_to_share_true": payload.get("safe_to_share") is True,
        "status_ready_or_blocked": payload.get("status") in {"ready", "blocked"},
        "dist_dir_relative": payload.get("dist_dir") == "dist/pypi",
        "absolute_paths_omitted": str(root) not in serialized and (not home or home not in serialized),
        "command_output_text_omitted": privacy.get("command_output_text_included") is False
        and all("stdout" not in step and "stderr" not in step for step in command_steps if isinstance(step, dict)),
        "tokens_omitted": privacy.get("tokens_included") is False
        and "<testpypi-token>" in str(publish_commands.get("testpypi") or "")
        and "<pypi-token>" in str(publish_commands.get("pypi") or ""),
        "files_have_hashes": bool(files)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("file"), str)
            and isinstance(item.get("bytes"), int)
            and isinstance(item.get("sha256"), str)
            and len(str(item.get("sha256"))) == 64
            for item in files
        ),
        "checks_all_true_when_ready": payload.get("status") != "ready"
        or (bool(checks) and all(value is True for value in checks.values())),
        "body_hash_present": isinstance(body_hash, str) and len(body_hash) == 64,
        "body_hash_matched": body_hash == _receipt_body_sha256(payload),
    }


def verify_pypi_release_receipt_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PyPI release receipt JSON object expected.")
    _verify_pypi_release_receipt(payload)
    artifact_checks = _verify_receipt_artifacts(path.resolve(), payload)
    failed_artifacts = [name for name, passed in artifact_checks.items() if passed is not True]
    if failed_artifacts:
        raise ValueError("PyPI release receipt artifact verification failed: " + ", ".join(failed_artifacts))
    payload["artifact_verification_checks"] = artifact_checks
    return payload


def _verify_pypi_release_receipt(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != PYPI_RECEIPT_SCHEMA_VERSION:
        raise ValueError("PyPI release receipt schema_version mismatch.")
    receipt_checks = payload.get("receipt_checks") if isinstance(payload.get("receipt_checks"), dict) else {}
    if not receipt_checks:
        raise ValueError("PyPI release receipt checks missing.")
    failed = [name for name, passed in receipt_checks.items() if passed is not True]
    if failed:
        raise ValueError("PyPI release receipt verification failed: " + ", ".join(failed))
    if payload.get("pypi_release_receipt_body_sha256") != _receipt_body_sha256(payload):
        raise ValueError("PyPI release receipt body hash mismatch.")


def _verify_receipt_artifacts(receipt_path: Path, payload: dict[str, Any]) -> dict[str, bool]:
    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    artifact_dir = receipt_path.parent / DEFAULT_DIST_SUBDIR
    checks: dict[str, bool] = {
        "artifact_dir_present": artifact_dir.exists(),
        "receipt_lists_artifacts": bool(files),
    }
    for item in files:
        if not isinstance(item, dict):
            checks["artifact_item_valid"] = False
            continue
        name = str(item.get("file") or "")
        path = artifact_dir / name
        checks[f"artifact_present:{name}"] = path.exists()
        checks[f"artifact_hash_matched:{name}"] = (
            path.exists()
            and path.stat().st_size == int(item.get("bytes") or -1)
            and _sha256(path) == item.get("sha256")
        )
    return checks


def _upload(tool_python: Path, dist_dir: Path, repository: str) -> dict[str, Any]:
    repository = repository.lower()
    if repository not in {"testpypi", "pypi"}:
        raise ValueError("upload 대상은 testpypi 또는 pypi만 허용합니다.")
    _verify_upload_environment(repository)
    username = os.environ.get("TWINE_USERNAME", "__token__")
    password = os.environ.get("TWINE_PASSWORD")
    if not password:
        raise RuntimeError("TWINE_PASSWORD 환경변수에 PyPI API token을 설정해야 업로드할 수 있습니다.")
    upload_url = TESTPYPI_UPLOAD_URL if repository == "testpypi" else PYPI_UPLOAD_URL
    env = dict(os.environ)
    env["TWINE_USERNAME"] = username
    env["TWINE_PASSWORD"] = password
    return _run(
        [
            tool_python,
            "-m",
            "twine",
            "upload",
            "--non-interactive",
            "--repository-url",
            upload_url,
            *sorted(dist_dir.glob("*")),
        ],
        cwd=_repo_root(),
        timeout=300,
        env=env,
        redact_env=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambrian PyPI 릴리즈를 빌드/검증하고 선택적으로 업로드한다.")
    parser.add_argument("--dist-dir", type=Path, default=None, help="기본값은 dist/pypi")
    parser.add_argument("--upload", choices=["testpypi", "pypi"], default=None, help="토큰이 있을 때만 실제 업로드")
    parser.add_argument("--skip-name-check", action="store_true", help="PyPI name availability 조회를 건너뛴다")
    parser.add_argument("--verify-receipt", type=Path, default=None, help="Build/upload 없이 기존 PyPI release receipt만 검증한다")
    parser.add_argument(
        "--testpypi-install-receipt",
        type=Path,
        default=None,
        help="Required for --upload pypi. Default: dist/pypi_testpypi_install_receipt.json",
    )
    parser.add_argument(
        "--publish-ready-receipt",
        type=Path,
        default=None,
        help="Required for --upload. Default: dist/pypi-publish-ready-<repository>.json",
    )
    parser.add_argument("--preflight-upload", choices=["testpypi", "pypi"], default=None, help="Verify publish readiness without uploading.")
    parser.add_argument("--release-receipt", type=Path, default=None, help="Release receipt for --preflight-upload.")
    parser.add_argument("--local-install-receipt", type=Path, default=None, help="Local wheel install receipt for --preflight-upload.")
    parser.add_argument("--preflight-receipt", type=Path, default=None, help="Receipt path for --preflight-upload.")
    parser.add_argument("--require-token-env", action="store_true", help="Make upload token env a blocking preflight check.")
    parser.add_argument("--verify-preflight-receipt", type=Path, default=None, help="Verify an existing PyPI publish preflight receipt.")
    args = parser.parse_args()
    if args.verify_receipt:
        payload = verify_pypi_release_receipt_file(args.verify_receipt)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.verify_preflight_receipt:
        payload = verify_pypi_publish_preflight_receipt_file(args.verify_preflight_receipt)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.preflight_upload:
        preflight_publish(
            repository=args.preflight_upload,
            release_receipt=args.release_receipt,
            local_install_receipt=args.local_install_receipt,
            testpypi_install_receipt=args.testpypi_install_receipt,
            receipt_path=args.preflight_receipt,
            require_token_env=bool(args.require_token_env),
        )
        return
    prepare_release(
        dist_dir=args.dist_dir,
        upload=args.upload,
        skip_name_check=bool(args.skip_name_check),
        testpypi_install_receipt=args.testpypi_install_receipt,
        publish_ready_receipt=args.publish_ready_receipt,
    )


if __name__ == "__main__":
    main()
