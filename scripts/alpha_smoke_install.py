"""Cambrian 알파 로컬 설치/doctor/demo smoke 스크립트."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """명령을 실행하고 결과를 반환한다."""
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _venv_python(venv_dir: Path) -> Path:
    """가상환경 Python 경로를 반환한다."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_cambrian(venv_dir: Path) -> Path:
    """가상환경 cambrian 실행 파일 경로를 반환한다."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "cambrian.exe"
    return venv_dir / "bin" / "cambrian"


def _build_distribution(repo_root: Path, dist_dir: Path, env: dict[str, str]) -> tuple[int, str]:
    """가능하면 build를 쓰고, 안 되면 wheel fallback으로 배포본을 만든다."""
    build_proc = _run(
        [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist_dir)],
        cwd=repo_root,
        env=env,
    )
    if build_proc.returncode == 0:
        return 0, "python -m build"

    wheel_proc = _run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(dist_dir)],
        cwd=repo_root,
        env=env,
    )
    if wheel_proc.returncode == 0:
        return 0, "python -m pip wheel"

    sys.stdout.write(build_proc.stdout)
    sys.stderr.write(build_proc.stderr)
    sys.stdout.write(wheel_proc.stdout)
    sys.stderr.write(wheel_proc.stderr)
    return wheel_proc.returncode, "failed"


def main() -> int:
    """빌드, 설치, doctor, demo smoke를 순서대로 실행한다."""
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"

    with tempfile.TemporaryDirectory(prefix="cambrian-alpha-smoke-") as tmp_dir:
        tmp_root = Path(tmp_dir)
        dist_dir = tmp_root / "dist"
        venv_dir = tmp_root / "venv"
        demo_dir = tmp_root / "demo"

        build_code, build_method = _build_distribution(repo_root, dist_dir, env)
        if build_code != 0:
            print("배포본 빌드에 실패했습니다. `pip install -e .[dev]` 후 다시 시도하세요.", file=sys.stderr)
            return build_code

        wheel_paths = sorted(dist_dir.glob("cambrian-*.whl"))
        if not wheel_paths:
            print("빌드 결과에서 wheel을 찾지 못했습니다.", file=sys.stderr)
            return 3
        wheel_path = wheel_paths[-1]

        builder = venv.EnvBuilder(with_pip=True, system_site_packages=True)
        builder.create(venv_dir)
        venv_python = _venv_python(venv_dir)
        cambrian_exe = _venv_cambrian(venv_dir)
        if not venv_python.exists():
            print("가상환경 Python 실행 파일을 찾지 못했습니다.", file=sys.stderr)
            return 4

        install_proc = _run(
            [str(venv_python), "-m", "pip", "install", "--no-deps", str(wheel_path)],
            cwd=repo_root,
            env=env,
        )
        if install_proc.returncode != 0:
            sys.stdout.write(install_proc.stdout)
            sys.stderr.write(install_proc.stderr)
            return install_proc.returncode

        commands: list[tuple[str, list[str], Path]] = [
            ("help", [str(cambrian_exe), "--help"], repo_root),
            ("doctor", [str(cambrian_exe), "doctor", "--json"], repo_root),
            ("demo", [str(cambrian_exe), "demo", "create", "login-bug", "--out", str(demo_dir)], repo_root),
            (
                "init",
                [
                    str(cambrian_exe),
                    "init",
                    "--non-interactive",
                    "--name",
                    "demo",
                    "--type",
                    "python",
                    "--test-cmd",
                    "pytest -q",
                ],
                demo_dir,
            ),
            ("status", [str(cambrian_exe), "status", "--json"], demo_dir),
        ]

        results: dict[str, dict] = {}
        for name, command, cwd in commands:
            proc = _run(command, cwd=cwd, env=env)
            results[name] = {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
            if proc.returncode != 0:
                print(f"[{name}] failed", file=sys.stderr)
                sys.stdout.write(proc.stdout)
                sys.stderr.write(proc.stderr)
                return proc.returncode

        doctor_payload = json.loads(results["doctor"]["stdout"])
        status_payload = json.loads(results["status"]["stdout"])
        print("Cambrian alpha smoke passed.")
        print(f"build   : {build_method}")
        print(f"wheel   : {wheel_path}")
        print(f"doctor  : {doctor_payload.get('summary')}")
        print(f"status  : initialized={status_payload.get('initialized')}")
        print(f"demo    : {demo_dir}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
