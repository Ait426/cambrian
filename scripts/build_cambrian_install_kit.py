from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


INSTALL_KIT_SCHEMA_VERSION = "cambrian_install_kit_v0_1"
KIT_DIR_NAME = "cambrian-install-kit"
MANIFEST_NAME = "CAMBRIAN_INSTALL_KIT_MANIFEST.json"
README_NAME = "README_INSTALL_CAMBRIAN.md"
CLAUDE_PROMPT_NAME = "INSTALL_PROMPT_FOR_CODEX_CLAUDE.md"
INSTALLER_NAME = "install_cambrian.py"
POWERSHELL_INSTALLER_NAME = "INSTALL_CAMBRIAN.ps1"
BATCH_INSTALLER_NAME = "INSTALL_CAMBRIAN.bat"
SHELL_INSTALLER_NAME = "install_cambrian.sh"
DEPENDENCY_WHEEL_PREFIXES = (
    "attrs-",
    "jsonschema-",
    "jsonschema_specifications-",
    "pyyaml-",
    "referencing-",
    "rpds_py-",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_project_version(root: Path) -> str:
    payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(payload["project"]["version"])


def _run(command: list[str | Path], cwd: Path, timeout: int = 600) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [str(item) for item in command],
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        return {
            "command": [str(item) for item in command],
            "cwd": str(cwd),
            "exit_code": 124,
            "stdout": stdout,
            "stderr": f"timed out after {timeout} seconds\n{stderr}",
        }
    return {
        "command": [str(item) for item in command],
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_wheel(root: Path, wheels_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    wheels_dir.mkdir(parents=True, exist_ok=True)
    attempts = [
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", wheels_dir],
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", wheels_dir],
        [sys.executable, "-m", "build", str(root), "--wheel", "--outdir", wheels_dir],
    ]
    commands: list[dict[str, Any]] = []
    for command in attempts:
        item = _run(command, cwd=root)
        commands.append(item)
        if item["exit_code"] == 0:
            wheels = sorted(wheels_dir.glob("cambrian-*.whl"))
            if wheels:
                return wheels[-1], commands
    raise RuntimeError("Cambrian wheel build failed.")


def _download_dependency_wheels(wheels_dir: Path) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--dest",
        wheels_dir,
        "pyyaml>=6.0",
        "jsonschema>=4.20.0",
    ]
    item = _run(command, cwd=wheels_dir, timeout=240)
    commands.append(item)
    return commands


def _restore_cached_dependency_wheels(zip_path: Path, wheels_dir: Path) -> dict[str, Any]:
    restored: list[str] = []
    if zip_path.exists():
        with zipfile.ZipFile(zip_path) as archive:
            for name in archive.namelist():
                filename = Path(name).name
                lower = filename.lower()
                if not name.startswith("wheels/") or not lower.endswith(".whl"):
                    continue
                if lower.startswith("cambrian-"):
                    continue
                if not any(lower.startswith(prefix) for prefix in DEPENDENCY_WHEEL_PREFIXES):
                    continue
                target = wheels_dir / filename
                target.write_bytes(archive.read(name))
                restored.append(filename)
    return {
        "command": ["restore_cached_dependency_wheels", str(zip_path)],
        "cwd": str(wheels_dir),
        "exit_code": 0 if restored else 1,
        "stdout": "\n".join(sorted(restored)),
        "stderr": "" if restored else "no cached dependency wheels restored",
    }


def _has_dependency_wheelhouse(wheels_dir: Path) -> bool:
    names = [path.name.lower() for path in wheels_dir.glob("*.whl")]
    return all(any(name.startswith(prefix) for name in names) for prefix in DEPENDENCY_WHEEL_PREFIXES)


def build_install_kit(
    output_dir: Path | None = None,
    include_dependency_wheels: bool = True,
) -> dict[str, Any]:
    root = _repo_root()
    version = _read_project_version(root)
    dist_dir = (output_dir or root / "dist").resolve()
    kit_dir = dist_dir / KIT_DIR_NAME
    zip_path = dist_dir / f"{KIT_DIR_NAME}-{version}.zip"
    if kit_dir.exists():
        shutil.rmtree(kit_dir)
    kit_dir.mkdir(parents=True, exist_ok=True)
    wheels_dir = kit_dir / "wheels"
    commands: list[dict[str, Any]] = []

    wheel, build_commands = _build_wheel(root, wheels_dir)
    commands.extend(build_commands)
    dependency_mode = "online_or_cached"
    if include_dependency_wheels:
        cache_step = _restore_cached_dependency_wheels(zip_path, wheels_dir)
        commands.append(cache_step)
        if _has_dependency_wheelhouse(wheels_dir):
            dependency_mode = "bundled_wheelhouse"
        else:
            dependency_commands = _download_dependency_wheels(wheels_dir)
            commands.extend(dependency_commands)
            if _has_dependency_wheelhouse(wheels_dir):
                dependency_mode = "bundled_wheelhouse"

    _write(kit_dir / INSTALLER_NAME, _installer_text())
    _write(kit_dir / POWERSHELL_INSTALLER_NAME, _powershell_installer_text())
    _write(kit_dir / BATCH_INSTALLER_NAME, _batch_installer_text())
    _write(kit_dir / SHELL_INSTALLER_NAME, _shell_installer_text())
    _write(kit_dir / README_NAME, _readme_text(version, wheel.name, dependency_mode))
    _write(kit_dir / CLAUDE_PROMPT_NAME, _claude_prompt_text())

    manifest = _manifest(kit_dir, version, wheel.name, dependency_mode, commands)
    _write(kit_dir / MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    manifest = _manifest(kit_dir, version, wheel.name, dependency_mode, commands)
    _write(kit_dir / MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(kit_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(kit_dir).as_posix())

    result = {
        "schema_version": INSTALL_KIT_SCHEMA_VERSION,
        "status": "built",
        "version": version,
        "kit_dir": str(kit_dir),
        "zip_file": str(zip_path),
        "zip_sha256": _sha256(zip_path),
        "wheel_file": wheel.name,
        "wheel_sha256": _sha256(wheel),
        "dependency_mode": dependency_mode,
        "manifest": str(kit_dir / MANIFEST_NAME),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _manifest(
    kit_dir: Path,
    version: str,
    wheel_name: str,
    dependency_mode: str,
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(kit_dir.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        files.append(
            {
                "path": path.relative_to(kit_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "schema_version": INSTALL_KIT_SCHEMA_VERSION,
        "generated_at": _now(),
        "package": {
            "name": "cambrian",
            "version": version,
            "wheel": f"wheels/{wheel_name}",
        },
        "dependency_mode": dependency_mode,
        "python_requires": ">=3.11",
        "entrypoint": "cambrian",
        "mcp_entrypoint": "cambrian-mcp",
        "install_commands": {
            "python": f"python {INSTALLER_NAME}",
            "project": f"python {INSTALLER_NAME} --project <PROJECT_DIR>",
            "powershell": f".\\{POWERSHELL_INSTALLER_NAME}",
            "windows_cmd": BATCH_INSTALLER_NAME,
            "bash": f"bash {SHELL_INSTALLER_NAME}",
        },
        "verified_capabilities": [
            "cambrian --help",
            "cambrian doctor --json",
            "cambrian company snapshot --help",
            "cambrian mcp verify",
            "installed cambrian-mcp entry point",
            "project-local venv install",
        ],
        "files": files,
        "build_summary": {
            "command_count": len(commands),
            "wheel_build_passed": True,
            "dependency_wheel_download_attempted": len(commands) > 1,
            "dependency_wheel_download_passed": len(commands) > 1 and commands[-1]["exit_code"] == 0,
        },
    }


def _installer_text() -> str:
    return r'''from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import venv
from datetime import datetime, timezone
from pathlib import Path


def _scripts_dir(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _venv_python(venv_dir: Path) -> Path:
    return _scripts_dir(venv_dir) / ("python.exe" if os.name == "nt" else "python")


def _venv_cambrian(venv_dir: Path) -> Path:
    return _scripts_dir(venv_dir) / ("cambrian.exe" if os.name == "nt" else "cambrian")


def _venv_cambrian_mcp(venv_dir: Path) -> Path:
    return _scripts_dir(venv_dir) / ("cambrian-mcp.exe" if os.name == "nt" else "cambrian-mcp")


def _run(command: list[str | Path], cwd: Path) -> dict:
    result = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        capture_output=True,
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


def _fail_if_needed(step: dict) -> None:
    if step["exit_code"] != 0:
        print(json.dumps(step, ensure_ascii=False, indent=2))
        raise SystemExit(step["exit_code"])


def _receipt_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path.name}")
    return payload


def install(project: Path | None, venv_name: str, offline: bool) -> dict:
    kit_dir = Path(__file__).resolve().parent
    target_root = project.resolve() if project else kit_dir
    target_root.mkdir(parents=True, exist_ok=True)
    wheels_dir = kit_dir / "wheels"
    cambrian_wheels = sorted(wheels_dir.glob("cambrian-*.whl"))
    if not cambrian_wheels:
        raise SystemExit("wheels 폴더에 cambrian wheel이 없습니다.")
    wheel = cambrian_wheels[-1]
    venv_dir = target_root / venv_name
    if not venv_dir.exists():
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = _venv_python(venv_dir)
    cambrian = _venv_cambrian(venv_dir)
    cambrian_mcp = _venv_cambrian_mcp(venv_dir)
    steps: list[dict] = []
    named_steps: list[tuple[str, dict]] = []
    if not offline:
        steps.append(_run([python, "-m", "pip", "install", "--upgrade", "pip"], cwd=target_root))
        named_steps.append(("pip_upgrade", steps[-1]))
        _fail_if_needed(steps[-1])
    install_command: list[str | Path] = [python, "-m", "pip", "install", "--find-links", wheels_dir, wheel]
    if offline:
        install_command = [python, "-m", "pip", "install", "--no-index", "--find-links", wheels_dir, wheel]
    steps.append(_run(install_command, cwd=target_root))
    named_steps.append(("pip_install", steps[-1]))
    _fail_if_needed(steps[-1])
    steps.append(_run([cambrian, "--help"], cwd=target_root))
    named_steps.append(("cambrian_help", steps[-1]))
    _fail_if_needed(steps[-1])
    steps.append(_run([cambrian, "doctor", "--json"], cwd=target_root))
    named_steps.append(("cambrian_doctor_json", steps[-1]))
    _fail_if_needed(steps[-1])
    steps.append(_run([cambrian, "company", "snapshot", "--help"], cwd=target_root))
    named_steps.append(("cambrian_company_snapshot_help", steps[-1]))
    _fail_if_needed(steps[-1])
    mcp_receipt_path = target_root / "mcp_operability_receipt.json"
    steps.append(
        _run(
            [
                cambrian,
                "mcp",
                "verify",
                "--server-cwd",
                target_root,
                "--receipt",
                mcp_receipt_path,
                "--server-command-json",
                json.dumps([str(cambrian_mcp)]),
                "--json",
            ],
            cwd=target_root,
        )
    )
    named_steps.append(("cambrian_mcp_verify", steps[-1]))
    _fail_if_needed(steps[-1])
    mcp_receipt = _read_json(mcp_receipt_path)
    mcp_checks = mcp_receipt.get("checks") if isinstance(mcp_receipt.get("checks"), dict) else {}
    receipt = {
        "schema_version": "cambrian_install_receipt_v0_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "installed",
        "safe_to_share": False,
        "shareable_receipt": "cambrian_install_share_receipt.json",
        "privacy": {
            "absolute_paths_included": True,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "project_root": str(target_root),
        "venv_dir": str(venv_dir),
        "cambrian_command": str(cambrian),
        "cambrian_mcp_command": str(cambrian_mcp),
        "wheel": wheel.name,
        "offline": offline,
        "mcp_operability_receipt": str(mcp_receipt_path),
        "mcp_operability": {
            "verdict": mcp_receipt.get("verdict"),
            "server_command_mode": mcp_receipt.get("server_command_mode"),
            "installed_entrypoint_command": mcp_receipt.get("installed_entrypoint_command"),
            "source_pythonpath_injected": mcp_receipt.get("source_pythonpath_injected"),
            "no_arbitrary_shell": mcp_checks.get("no_arbitrary_shell"),
            "explicit_cwd_required": mcp_checks.get("explicit_cwd_required"),
        },
        "steps": [
            {
                "command": " ".join(step["command"]),
                "exit_code": step["exit_code"],
                "status": step["status"],
            }
            for step in steps
        ],
        "next_commands": [
            f'"{cambrian}" project scan --json',
            f'"{cambrian}" harness interview start --json',
            f'"{cambrian}" skill generate --json',
            f'"{cambrian}" company snapshot --json',
            f'"{cambrian}" mcp verify --receipt "{mcp_receipt_path}" --server-command-json "{json.dumps([str(cambrian_mcp)]).replace(chr(34), chr(92) + chr(34))}"',
        ],
    }
    receipt_path = target_root / "cambrian_install_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    share_receipt = {
        "schema_version": "cambrian_install_share_receipt_v0_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "installed",
        "safe_to_share": True,
        "privacy": {
            "absolute_paths_included": False,
            "raw_private_project_data_included": False,
            "secrets_included": False,
        },
        "local_receipt_sha256": _receipt_sha256(receipt_path),
        "local_mcp_receipt_sha256": _receipt_sha256(mcp_receipt_path),
        "wheel": wheel.name,
        "offline": offline,
        "mcp_operability": {
            "receipt_file": "mcp_operability_receipt.json",
            "verdict": mcp_receipt.get("verdict"),
            "server_command_mode": mcp_receipt.get("server_command_mode"),
            "installed_entrypoint_command": mcp_receipt.get("installed_entrypoint_command"),
            "source_pythonpath_injected": mcp_receipt.get("source_pythonpath_injected"),
            "no_arbitrary_shell": mcp_checks.get("no_arbitrary_shell"),
            "explicit_cwd_required": mcp_checks.get("explicit_cwd_required"),
        },
        "steps": [
            {
                "name": name,
                "exit_code": step["exit_code"],
                "status": step["status"],
            }
            for name, step in named_steps
        ],
        "checks": {
            "all_steps_passed": all(step["status"] == "passed" for step in steps),
            "cambrian_help_passed": dict(named_steps)["cambrian_help"]["status"] == "passed",
            "cambrian_doctor_json_passed": dict(named_steps)["cambrian_doctor_json"]["status"] == "passed",
            "cambrian_company_snapshot_help_passed": dict(named_steps)["cambrian_company_snapshot_help"]["status"] == "passed",
            "cambrian_mcp_verify_passed": dict(named_steps)["cambrian_mcp_verify"]["status"] == "passed",
            "mcp_operability_receipt_go": mcp_receipt.get("verdict") == "GO",
            "mcp_operability_installed_entrypoint": mcp_receipt.get("server_command_mode") == "installed_entrypoint"
            and mcp_receipt.get("installed_entrypoint_command") is True
            and mcp_receipt.get("source_pythonpath_injected") is False,
            "mcp_operability_no_arbitrary_shell": mcp_checks.get("no_arbitrary_shell") is True,
        },
        "next_commands": [
            "cambrian project scan --json",
            "cambrian harness interview start --json",
            "cambrian skill generate --json",
            "cambrian company snapshot --json",
            "cambrian mcp verify --receipt mcp_operability_receipt.json",
        ],
        "do_not_share": [
            "cambrian_install_receipt.json",
            ".env",
            "API keys",
            "raw private project data",
            "screenshots or raw user text",
        ],
    }
    share_receipt_path = target_root / "cambrian_install_share_receipt.json"
    share_receipt_path.write_text(json.dumps(share_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(share_receipt, ensure_ascii=False, indent=2))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambrian wheel install kit installer")
    parser.add_argument("--project", type=Path, default=None, help="Cambrian을 적용할 프로젝트 폴더. 기본값은 install kit 폴더")
    parser.add_argument("--venv-name", default=".venv-cambrian", help="생성할 venv 폴더명")
    parser.add_argument("--offline", action="store_true", help="wheelhouse만 사용해 설치")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit("Cambrian은 Python 3.11 이상이 필요합니다.")
    install(args.project, args.venv_name, bool(args.offline))


if __name__ == "__main__":
    main()
'''


def _powershell_installer_text() -> str:
    return """param(
  [string]$Project = "",
  [switch]$Offline
)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsList = @("$scriptDir\\install_cambrian.py")
if ($Project -ne "") {
  $argsList += @("--project", $Project)
}
if ($Offline) {
  $argsList += "--offline"
}
python @argsList
"""


def _batch_installer_text() -> str:
    return """@echo off
set SCRIPT_DIR=%~dp0
python "%SCRIPT_DIR%install_cambrian.py" %*
"""


def _shell_installer_text() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/install_cambrian.py" "$@"
"""


def _readme_text(version: str, wheel_name: str, dependency_mode: str) -> str:
    return f"""# Cambrian Install Kit

## What This Is

이 폴더는 다른 PC에서 Cambrian을 설치하기 위한 portable install kit입니다.

포함된 wheel:

```text
wheels/{wheel_name}
```

버전:

```text
{version}
```

dependency mode:

```text
{dependency_mode}
```

## Requirements

```text
Python 3.11 이상
```

## Quick Install

이 install kit 폴더에서 실행:

```bash
python install_cambrian.py
```

특정 프로젝트 폴더에 Cambrian venv를 만들려면:

```bash
python install_cambrian.py --project /path/to/my-project
```

Windows PowerShell:

```powershell
.\\INSTALL_CAMBRIAN.ps1 -Project "C:\\path\\to\\my-project"
```

Windows cmd:

```bat
INSTALL_CAMBRIAN.bat --project C:\\path\\to\\my-project
```

macOS/Linux:

```bash
bash install_cambrian.sh --project /path/to/my-project
```

## Verify

설치가 성공하면 프로젝트 폴더 또는 kit 폴더에 아래 파일이 생깁니다.

```text
cambrian_install_receipt.json
cambrian_install_share_receipt.json
```

`cambrian_install_receipt.json`은 로컬 디버깅용이라 절대경로를 포함합니다.
지원 요청에 첨부해야 한다면 `safe_to_share: true`인 `cambrian_install_share_receipt.json`만 사용하세요.
share receipt에는 `cambrian --help`, `cambrian doctor --json`, `cambrian company snapshot --help` 실행 결과가 PASS로 기록됩니다.

설치 후 AI Company 런타임 증거가 있는 프로젝트에서는 아래 명령으로 private-safe company snapshot을 만들 수 있습니다.

```bash
cambrian company snapshot --json
```

## MCP Verification

The installer also writes:

```text
mcp_operability_receipt.json
```

This local receipt proves that the freshly installed `cambrian-mcp` entry point can be started over stdio and that `cambrian_project_scan` works with an explicit `cwd`. Share only the safe summary inside `cambrian_install_share_receipt.json` unless support explicitly asks for the local MCP receipt.

To connect Codex, Claude, Cursor, or another MCP client after install, use the installed `cambrian-mcp` command and pass an explicit project `cwd` to every Cambrian MCP tool call.

Quick MCP verification:

```bash
cambrian mcp verify --receipt mcp_operability_receipt.json
```

## Claude/Codex

Claude 또는 Codex에게는 `INSTALL_PROMPT_FOR_CODEX_CLAUDE.md` 내용을 그대로 붙여넣으면 됩니다.

## Boundary

이 kit는 Cambrian 명령 설치, doctor 확인, company snapshot CLI 표면 확인을 목표로 합니다.
AI Company Golden Path 전체 검증은 Cambrian 소스 저장소의 `scripts/smoke_ai_company_gold_path.py`에서 수행합니다.
"""


def _claude_prompt_text() -> str:
    return """This folder is a Cambrian install kit.

Goal:
1. Run `python install_cambrian.py` from this folder.
2. If a target project folder is provided, run `python install_cambrian.py --project "<project path>"`.
3. Confirm `cambrian_install_receipt.json`, `cambrian_install_share_receipt.json`, and `mcp_operability_receipt.json` exist.
4. Confirm `cambrian --help`, `cambrian doctor --json`, `cambrian company snapshot --help`, and `cambrian mcp verify --receipt mcp_operability_receipt.json` passed.
5. Confirm the MCP receipt says `verdict: GO`, `server_command_mode: installed_entrypoint`, `installed_entrypoint_command: true`, `source_pythonpath_injected: false`, and `no_arbitrary_shell: true`.
6. If Codex, Claude, Cursor, or another MCP client needs to connect, use the installed `cambrian-mcp` server command and pass an explicit `cwd` to every Cambrian MCP tool call.
7. If the project has AI Company evidence, suggest `cambrian company snapshot --json` as the next command.

Rules:
- Do not print `.env` or secrets.
- For support, attach only `cambrian_install_share_receipt.json` unless the user explicitly asks for local debug receipts.
- `cambrian_install_receipt.json` and `mcp_operability_receipt.json` may contain local paths.
- Do not run git add, commit, push, deploy, publish, or send messages.
- If installation fails, check that the `wheels` folder contains a Cambrian wheel and retry once.
"""
    return """이 폴더는 Cambrian install kit입니다.

목표:
1. 이 폴더의 install_cambrian.py를 실행해서 Cambrian을 설치하세요.
2. 특정 프로젝트 폴더가 주어졌다면 `python install_cambrian.py --project "<프로젝트 경로>"`를 사용하세요.
3. 설치 후 cambrian_install_receipt.json과 cambrian_install_share_receipt.json을 확인하세요.
4. `cambrian --help`, `cambrian doctor --json`, `cambrian company snapshot --help`가 PASS인지 보고하세요.
5. 프로젝트에 AI Company evidence가 있으면 `cambrian company snapshot --json`을 다음 실행 후보로 안내하세요.

주의:
- .env 또는 secret을 출력하지 마세요.
- 지원 요청에는 절대경로가 들어 있는 cambrian_install_receipt.json 대신 cambrian_install_share_receipt.json만 첨부하세요.
- git add/commit/push를 하지 마세요.
- 실패하면 현재 폴더의 wheels 안에 cambrian wheel이 있는지 확인하고 다시 시도하세요.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambrian portable install kit를 빌드한다.")
    parser.add_argument("--output-dir", type=Path, default=None, help="기본값은 dist")
    parser.add_argument("--no-dependency-wheels", action="store_true", help="dependency wheel 다운로드를 건너뛴다")
    args = parser.parse_args()
    build_install_kit(
        output_dir=args.output_dir,
        include_dependency_wheels=not bool(args.no_dependency_wheels),
    )


if __name__ == "__main__":
    main()
