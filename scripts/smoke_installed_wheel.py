from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path
from typing import Any


REQUEST_TEXT = "로그인 에러 수정해"
DEFAULT_TIMEOUT = 60


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(
    command: list[str | Path],
    cwd: Path,
    *,
    name: str,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    duration = time.perf_counter() - started
    return {
        "name": name,
        "command": [str(item) for item in command],
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "duration_seconds": round(duration, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "passed" if result.returncode == 0 else "failed",
    }


def _synthetic_step(name: str, cwd: Path, status: str = "passed", note: str = "", duration: float = 0.0) -> dict[str, Any]:
    return {
        "name": name,
        "command": [],
        "cwd": str(cwd),
        "exit_code": 0 if status == "passed" else 1,
        "duration_seconds": round(duration, 3),
        "stdout": note,
        "stderr": "",
        "status": status,
    }


def _venv_python(venv_dir: Path) -> Path:
    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    exe = "python.exe" if os.name == "nt" else "python"
    return scripts_dir / exe


def _venv_cambrian(venv_dir: Path) -> Path:
    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    exe = "cambrian.exe" if os.name == "nt" else "cambrian"
    return scripts_dir / exe


def _build_wheel(root: Path, dist_dir: Path) -> tuple[Path, list[dict[str, Any]]]:
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)

    attempts = [
        (
            "build wheel",
            [sys.executable, "-m", "build", str(root), "--wheel", "--outdir", dist_dir],
            root.parent,
        ),
        (
            "build wheel fallback no isolation",
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", dist_dir],
            root,
        ),
        (
            "build wheel fallback isolated",
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", dist_dir],
            root,
        ),
    ]

    commands: list[dict[str, Any]] = []
    for name, command, cwd in attempts:
        item = _run(command, cwd=cwd, timeout=180, name=name)
        commands.append(item)
        if item["exit_code"] == 0:
            wheels = sorted(dist_dir.glob("cambrian-*.whl"))
            if wheels:
                return wheels[-1], commands

    raise RuntimeError("wheel build failed")


def _write_outputs(out_dir: Path, commands: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "commands.json").write_text(json.dumps(commands, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# RC Fresh Install Smoke Transcript", ""]
    for index, item in enumerate(commands, start=1):
        command_text = " ".join(item.get("command", [])) or item.get("name", "")
        lines.extend(
            [
                f"## Step {index} — {item.get('name', 'command')}",
                "",
                "Command:",
                "```text",
                command_text,
                "```",
                "",
                f"Working directory: {item.get('cwd', '')}",
                f"Exit code: {item['exit_code']}",
                f"Duration: {item['duration_seconds']}s",
                f"Status: {item['status']}",
                "",
                "Stdout excerpt:",
                "```text",
                str(item.get("stdout", ""))[:1200],
                "```",
                "",
                "Stderr excerpt:",
                "```text",
                str(item.get("stderr", ""))[:1200],
                "```",
                "",
            ]
        )
    (out_dir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


def _print_human_summary(summary: dict[str, Any], commands: list[dict[str, Any]]) -> None:
    print("[RC Fresh Install Smoke]")
    print()
    for check in summary["checks"]:
        print(f"{check['name']}: {'PASS' if check['status'] == 'passed' else 'FAIL'}")
    print()
    print(f"Result: {'PASS' if summary['status'] == 'passed' else 'FAIL'}")
    if summary["status"] != "passed":
        failed = next((item for item in commands if item.get("status") != "passed"), None)
        if failed:
            print("Failed step:")
            print(f"Command: {' '.join(failed.get('command', []))}")
            print(f"Exit code: {failed.get('exit_code')}")
            print(f"Stdout excerpt: {str(failed.get('stdout', ''))[:1200]}")
            print(f"Stderr excerpt: {str(failed.get('stderr', ''))[:1200]}")
            print(f"Working directory: {failed.get('cwd')}")
    print()
    print(f"Summary: {summary['output_dir']}")


def run(out_dir: Path | None = None, keep_workdir: bool = False) -> dict[str, Any]:
    root = _repo_root()
    output_dir = out_dir or root / ".launch_runs" / "installed_wheel_latest"
    commands: list[dict[str, Any]] = []
    checks: list[dict[str, str]] = []
    errors: list[str] = []

    def mark(name: str, passed: bool) -> None:
        checks.append({"name": name, "status": "passed" if passed else "failed"})

    tmp = Path(tempfile.mkdtemp(prefix="cambrian-wheel-smoke-")).resolve()
    try:
        dist_dir = root / "dist"
        try:
            wheel, build_commands = _build_wheel(root, dist_dir)
            commands.extend(build_commands)
            mark("build wheel", True)

            venv_dir = tmp / "venv"
            started = time.perf_counter()
            venv.EnvBuilder(with_pip=True).create(venv_dir)
            commands.append(_synthetic_step("create venv", tmp, duration=time.perf_counter() - started))
            mark("create venv", True)

            python = _venv_python(venv_dir)
            cambrian = _venv_cambrian(venv_dir)
            install = _run([python, "-m", "pip", "install", wheel], cwd=root, timeout=180, name="install wheel")
            commands.append(install)
            mark("install wheel", install["exit_code"] == 0)
            if install["exit_code"] != 0:
                raise RuntimeError("wheel install failed")

            install_pytest = _run(
                [python, "-m", "pip", "install", "pytest"],
                cwd=root,
                timeout=180,
                name="install pytest for demo validation",
            )
            commands.append(install_pytest)
            if install_pytest["exit_code"] != 0:
                raise RuntimeError("pytest install failed for demo validation")

            demo_dir = tmp / "auth_bug_demo"
            flow = [
                ("cambrian --help", [cambrian, "--help"], tmp),
                ("cambrian doctor", [cambrian, "doctor", "--json"], tmp),
                ("demo create login-bug", [cambrian, "demo", "create", "login-bug", "--out", demo_dir], tmp),
                ("pack list", [cambrian, "pack", "list", "--json"], demo_dir),
                ("pack show auth-bug-core", [cambrian, "pack", "show", "auth-bug-core", "--json"], demo_dir),
                ("install pack auth-bug-core", [cambrian, "install", "pack", "auth-bug-core", "--json"], demo_dir),
                ("activate auth-bug-core", [cambrian, "pack", "activate", "auth-bug-core", "--json"], demo_dir),
                ("pack start", [cambrian, "pack", "start", REQUEST_TEXT, "--json"], demo_dir),
                (
                    "job-ingest",
                    [cambrian, "pack", "job-ingest", "latest", "fixtures/ai_reply_patch_candidate.yaml", "--json"],
                    demo_dir,
                ),
                ("job-validate", [cambrian, "pack", "job-validate", "latest", "--json"], demo_dir),
            ]
            for name, command, cwd in flow:
                item = _run(command, cwd=cwd, name=name)
                commands.append(item)
                mark(name, item["exit_code"] == 0)
                if item["exit_code"] != 0:
                    raise RuntimeError(f"command failed: {' '.join(str(part) for part in command)}")
        except Exception as exc:
            if not checks or checks[-1]["status"] != "failed":
                mark("current step", False)
            errors.append(str(exc))

        summary = {
            "schema_version": "1.0",
            "status": "passed" if not errors else "failed",
            "repo_root": str(root),
            "output_dir": str(output_dir),
            "checks": checks,
            "steps": [
                {
                    "name": item["name"],
                    "command": " ".join(item["command"]),
                    "exit_code": item["exit_code"],
                    "duration_seconds": item["duration_seconds"],
                    "status": item["status"],
                }
                for item in commands
            ],
            "warnings": [
                "Auth Bug Core validation uses pytest; the smoke installs pytest into the temporary venv."
            ],
            "errors": errors,
            "workdir": str(tmp) if keep_workdir else None,
        }
        _write_outputs(output_dir, commands, summary)
        _print_human_summary(summary, commands)
        if errors:
            raise SystemExit(1)
        return summary
    finally:
        if not keep_workdir:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and smoke-test Cambrian from a fresh installed wheel.")
    parser.add_argument("--out", type=Path, default=None, help="output directory for transcript and summary")
    parser.add_argument("--keep-workdir", action="store_true", help="keep temporary working directory")
    args = parser.parse_args()
    run(out_dir=args.out, keep_workdir=bool(args.keep_workdir))


if __name__ == "__main__":
    main()
