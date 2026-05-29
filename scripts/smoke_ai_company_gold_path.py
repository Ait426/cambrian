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

import yaml


REQUEST_TEXT = "check refresh token login failure"
FUSION_GOAL = "refresh token login failure를 추적하고 Jest 회귀 위험을 함께 검토한다."
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
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    run_env.setdefault("PYTHONIOENCODING", "utf-8")
    run_env.setdefault("PYTHONUTF8", "1")
    try:
        result = subprocess.run(
            [str(item) for item in command],
            cwd=str(cwd),
            env=run_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        duration = time.perf_counter() - started
        return {
            "name": name,
            "command": [str(item) for item in command],
            "cwd": str(cwd),
            "exit_code": 124,
            "duration_seconds": round(duration, 3),
            "stdout": stdout,
            "stderr": f"timed out after {timeout} seconds\n{stderr}",
            "status": "failed",
        }
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


def _venv_cambrian_mcp(venv_dir: Path) -> Path:
    scripts_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    exe = "cambrian-mcp.exe" if os.name == "nt" else "cambrian-mcp"
    return scripts_dir / exe


def _cached_dependency_wheelhouse(root: Path) -> Path | None:
    wheels_dir = root / "dist" / "cambrian-install-kit" / "wheels"
    required_prefixes = ("attrs-", "jsonschema-", "jsonschema_specifications-", "pyyaml-", "referencing-", "rpds_py-")
    if not wheels_dir.exists():
        return None
    names = [path.name.lower() for path in wheels_dir.glob("*.whl")]
    if all(any(name.startswith(prefix) for name in names) for prefix in required_prefixes):
        return wheels_dir
    return None


def _build_wheel(root: Path, wheelhouse: Path) -> tuple[Path, list[dict[str, Any]]]:
    if wheelhouse.exists():
        shutil.rmtree(wheelhouse)
    wheelhouse.mkdir(parents=True, exist_ok=True)
    attempts = [
        (
            "build wheel fallback no isolation",
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-w", wheelhouse],
            root,
        ),
        (
            "build wheel fallback isolated",
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", wheelhouse],
            root,
        ),
        (
            "build wheel",
            [sys.executable, "-m", "build", str(root), "--wheel", "--outdir", wheelhouse],
            root.parent,
        ),
    ]
    commands: list[dict[str, Any]] = []
    for name, command, cwd in attempts:
        item = _run(command, cwd=cwd, timeout=180, name=name)
        commands.append(item)
        if item["exit_code"] == 0:
            wheels = sorted(wheelhouse.glob("cambrian-*.whl"))
            if wheels:
                return wheels[-1], commands
    raise RuntimeError("wheel build failed")


def _write_project(project_dir: Path) -> None:
    _write(project_dir / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(project_dir / "tsconfig.json", "{}")
    _write(project_dir / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(project_dir / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _write_answers(project_dir: Path) -> None:
    answers = """session_id: harness-interview-gold-path
answers:
  primary_goal: Investigate auth login bugs safely.
  test_command: npm test
  build_command: npm run build
  change_policy: proposal_only
  forbidden_scope:
    - no automatic patch apply
    - no DB schema changes
  important_paths:
    - backend/src/middleware/authMiddleware.ts
    - backend/tests/auth.test.ts
  validation_standard: Relevant Jest tests pass and regression risk is explained.
"""
    _write(project_dir / ".cambrian" / "interview" / "answers.yaml", answers)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _json_from_stdout(step: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(step.get("stdout") or "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{step['name']} JSON 출력 파싱 실패") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{step['name']} JSON 출력이 객체가 아닙니다.")
    return payload


def _expand_outcome_evidence(project_dir: Path, count: int = 10) -> None:
    outcomes_path = project_dir / ".cambrian" / "evidence" / "outcomes.yaml"
    payload = yaml.safe_load(outcomes_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("outcomes evidence must be a YAML object")
    outcomes = payload.get("outcomes", [])
    if not isinstance(outcomes, list) or not outcomes:
        raise RuntimeError("outcomes evidence is missing")
    if len(outcomes) >= count:
        return
    seed = dict(outcomes[-1])
    seed_job_id = str(seed.get("job_id") or "job-maturity")
    expanded = [dict(item) for item in outcomes if isinstance(item, dict)]
    for index in range(len(expanded), count):
        item = dict(seed)
        item["job_id"] = f"{seed_job_id}-maturity-{index + 1:03d}"
        expanded.append(item)
    payload["outcomes"] = expanded
    outcomes_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_outputs(out_dir: Path, commands: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "commands.json").write_text(json.dumps(commands, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# AI Company Gold Path Smoke Transcript", ""]
    for index, item in enumerate(commands, start=1):
        command_text = " ".join(item.get("command", [])) or item.get("name", "")
        lines.extend(
            [
                f"## Step {index} - {item.get('name', 'command')}",
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
    print("[AI Company Gold Path Smoke]")
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
    output_dir = out_dir or root / ".launch_runs" / "ai_company_gold_path_latest"
    commands: list[dict[str, Any]] = []
    checks: list[dict[str, str]] = []
    errors: list[str] = []

    def mark(name: str, passed: bool) -> None:
        checks.append({"name": name, "status": "passed" if passed else "failed"})

    tmp = Path(tempfile.mkdtemp(prefix="cambrian-ai-company-gold-")).resolve()
    try:
        try:
            wheel, build_commands = _build_wheel(root, tmp / "wheelhouse")
            commands.extend(build_commands)
            mark("build wheel", True)

            venv_dir = tmp / "venv"
            started = time.perf_counter()
            venv.EnvBuilder(with_pip=True).create(venv_dir)
            commands.append(_synthetic_step("create venv", tmp, duration=time.perf_counter() - started))
            mark("create venv", True)

            python = _venv_python(venv_dir)
            cambrian = _venv_cambrian(venv_dir)
            cambrian_mcp = _venv_cambrian_mcp(venv_dir)
            dependency_wheelhouse = _cached_dependency_wheelhouse(root)
            install_command: list[str | Path] = [python, "-m", "pip", "install", wheel]
            if dependency_wheelhouse is not None:
                install_command = [
                    python,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--find-links",
                    dependency_wheelhouse,
                    wheel,
                ]
            install = _run(install_command, cwd=tmp, timeout=180, name="install wheel")
            commands.append(install)
            mark("install wheel", install["exit_code"] == 0)
            if install["exit_code"] != 0:
                raise RuntimeError("wheel install failed")

            mcp_receipt = (output_dir / "mcp_operability_receipt.json").resolve()
            mcp_operability = _run(
                [
                    cambrian,
                    "mcp",
                    "verify",
                    "--server-cwd",
                    tmp,
                    "--receipt",
                    mcp_receipt,
                    "--server-command-json",
                    json.dumps([str(cambrian_mcp)]),
                    "--json",
                ],
                cwd=tmp,
                timeout=60,
                name="installed cambrian mcp verify",
            )
            commands.append(mcp_operability)
            mark("mcp operability receipt", mcp_operability["exit_code"] == 0)
            if mcp_operability["exit_code"] != 0:
                raise RuntimeError("mcp operability verifier failed")
            mcp_payload = _json_from_stdout(mcp_operability)
            if mcp_payload.get("verdict") != "GO" or not mcp_receipt.exists():
                raise RuntimeError("mcp operability receipt did not return GO")
            mark("installed cambrian-mcp entry point is operable", True)

            project_dir = tmp / "auth_company_project"
            project_dir.mkdir()
            _write_project(project_dir)

            flow = [
                ("cambrian --help", [cambrian, "--help"], tmp),
                ("cambrian doctor", [cambrian, "doctor", "--json"], project_dir),
                ("project scan", [cambrian, "project", "scan", "--json"], project_dir),
                ("harness interview start", [cambrian, "harness", "interview", "start", "--json"], project_dir),
            ]
            for name, command, cwd in flow:
                item = _run(command, cwd=cwd, name=name)
                commands.append(item)
                mark(name, item["exit_code"] == 0)
                if item["exit_code"] != 0:
                    raise RuntimeError(f"command failed: {' '.join(str(part) for part in command)}")

            _write_answers(project_dir)
            flow_after_answers = [
                (
                    "harness interview answer",
                    [cambrian, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json"],
                    project_dir,
                ),
                ("harness engineer design", [cambrian, "harness", "engineer", "design", "--json"], project_dir),
                ("harness engineer review", [cambrian, "harness", "engineer", "review", "--json"], project_dir),
                (
                    "harness engineer dry-run",
                    [cambrian, "harness", "engineer", "dry-run", REQUEST_TEXT, "--json"],
                    project_dir,
                ),
                ("workforce generate", [cambrian, "workforce", "generate", "--json"], project_dir),
                ("skill generate", [cambrian, "skill", "generate", "--json"], project_dir),
                ("harness install", [cambrian, "harness", "install", "--confirm", "--json"], project_dir),
                ("skill search", [cambrian, "skill", "search", "auth", "token", "--json"], project_dir),
                (
                    "skill fuse",
                    [
                        cambrian,
                        "skill",
                        "fuse",
                        "trace-auth-token-flow",
                        "inspect-jest-auth-test",
                        "--goal",
                        FUSION_GOAL,
                        "--json",
                    ],
                    project_dir,
                ),
                ("job start", [cambrian, "job", "start", REQUEST_TEXT, "--json"], project_dir),
                (
                    "job complete",
                    [
                        cambrian,
                        "job",
                        "complete",
                        "latest",
                        "--outcome",
                        "partial",
                        "--notes",
                        "test command was wrong and refresh token path was missed",
                        "--json",
                    ],
                    project_dir,
                ),
                ("evolve propose", [cambrian, "evolve", "propose", "--json"], project_dir),
            ]
            proposal_id: str | None = None
            fused_skill_id: str | None = None
            for name, command, cwd in flow_after_answers:
                item = _run(command, cwd=cwd, name=name)
                commands.append(item)
                mark(name, item["exit_code"] == 0)
                if item["exit_code"] != 0:
                    raise RuntimeError(f"command failed: {' '.join(str(part) for part in command)}")
                if name == "skill search":
                    payload = _json_from_stdout(item)
                    result_ids = [result.get("id") for result in payload.get("results", []) if isinstance(result, dict)]
                    if "trace-auth-token-flow" not in result_ids:
                        raise RuntimeError("skill search did not find trace-auth-token-flow")
                    mark("skill search finds generated skill", True)
                if name == "skill fuse":
                    payload = _json_from_stdout(item)
                    fused_skill_id = str(payload.get("skill_id") or "")
                    if not fused_skill_id:
                        raise RuntimeError("skill fuse did not return skill_id")
                    mark("skill fuse creates project skill", (project_dir / ".cambrian" / "skills" / f"{fused_skill_id}.yaml").exists())
                if name == "job start":
                    payload = _json_from_stdout(item)
                    if not payload.get("selected_agents") or not payload.get("selected_skills"):
                        raise RuntimeError("job start did not select agents and skills")
                    mark("job start selects agents and skills", True)
                if name == "job complete":
                    started = time.perf_counter()
                    _expand_outcome_evidence(project_dir, count=10)
                    commands.append(
                        _synthetic_step(
                            "expand evolution maturity evidence",
                            project_dir,
                            note="expanded local synthetic outcome evidence to 10 samples for maturity gate",
                            duration=time.perf_counter() - started,
                        )
                    )
                    mark("evolution maturity evidence", True)
                if name == "evolve propose":
                    payload = _json_from_stdout(item)
                    proposal_id = str(payload.get("proposal_id") or "")
                    if not proposal_id:
                        raise RuntimeError("evolve propose did not return proposal_id")

            preview = _run([cambrian, "evolve", "preview", str(proposal_id), "--json"], cwd=project_dir, name="evolve preview")
            commands.append(preview)
            mark("evolve preview", preview["exit_code"] == 0)
            if preview["exit_code"] != 0:
                raise RuntimeError("evolve preview failed")

            apply = _run(
                [cambrian, "evolve", "apply", str(proposal_id), "--confirm", "--json"],
                cwd=project_dir,
                name="evolve apply",
            )
            commands.append(apply)
            mark("evolve apply", apply["exit_code"] == 0)
            if apply["exit_code"] != 0:
                raise RuntimeError("evolve apply failed")

            snapshot = _run([cambrian, "company", "snapshot", "--json"], cwd=project_dir, name="company snapshot")
            commands.append(snapshot)
            mark("company snapshot", snapshot["exit_code"] == 0)
            if snapshot["exit_code"] != 0:
                raise RuntimeError("company snapshot failed")
            snapshot_payload = _json_from_stdout(snapshot)
            snapshot_body = snapshot_payload.get("snapshot", {}) if isinstance(snapshot_payload.get("snapshot"), dict) else {}
            privacy = snapshot_body.get("privacy_boundary", {}) if isinstance(snapshot_body.get("privacy_boundary"), dict) else {}
            marketplace = snapshot_body.get("marketplace", {}) if isinstance(snapshot_body.get("marketplace"), dict) else {}
            validation = snapshot_body.get("validation", {}) if isinstance(snapshot_body.get("validation"), dict) else {}
            snapshot_ref = str(snapshot_payload.get("snapshot_ref") or "")
            snapshot_ok = (
                validation.get("status") == "pass"
                and privacy.get("raw_private_project_data_included") is False
                and marketplace.get("sale_ready") is False
                and bool(snapshot_ref)
                and (project_dir / snapshot_ref).exists()
            )
            mark("company snapshot is private-safe artifact", snapshot_ok)
            if not snapshot_ok:
                raise RuntimeError("company snapshot did not validate as private-safe artifact")

            required_files = [
                ".cambrian/harness.yaml",
                ".cambrian/workforce.yaml",
                ".cambrian/agents/auth-flow-investigator.yaml",
                ".cambrian/skills/trace-auth-token-flow.yaml",
                ".cambrian/evolution/proposals",
                ".cambrian/company/snapshots",
            ]
            for relative in required_files:
                exists = (project_dir / relative).exists()
                mark(f"artifact exists: {relative}", exists)
                if not exists:
                    raise RuntimeError(f"required artifact missing: {relative}")
        except Exception as exc:
            if not checks or checks[-1]["status"] != "failed":
                mark("current step", False)
            errors.append(str(exc))

        summary = {
            "schema_version": "ai_company_gold_path_smoke_v0_1",
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
            "capabilities_verified": {
                "ai_agents_created": any(check["name"] == "artifact exists: .cambrian/agents/auth-flow-investigator.yaml" and check["status"] == "passed" for check in checks),
                "skills_generated_searched_and_fused": any(check["name"] == "skill fuse creates project skill" and check["status"] == "passed" for check in checks),
                "harness_engineering_system_created": any(check["name"] == "harness engineer dry-run" and check["status"] == "passed" for check in checks),
                "evolution_proposed_previewed_and_applied": any(check["name"] == "evolve apply" and check["status"] == "passed" for check in checks),
                "company_snapshot_generated": any(check["name"] == "company snapshot is private-safe artifact" and check["status"] == "passed" for check in checks),
                "mcp_operability_verified": any(check["name"] == "mcp operability receipt" and check["status"] == "passed" for check in checks),
            },
            "warnings": [
                "골든패스는 provider API key 없이 로컬 계약, generated skill, evidence, metadata 진화를 검증한다.",
                "source code는 자동 수정하지 않는다.",
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
    parser = argparse.ArgumentParser(description="Fresh installed wheel에서 AI company gold path를 검증한다.")
    parser.add_argument("--out", type=Path, default=None, help="transcript와 summary 출력 폴더")
    parser.add_argument("--keep-workdir", action="store_true", help="임시 작업 폴더 보존")
    args = parser.parse_args()
    run(out_dir=args.out, keep_workdir=bool(args.keep_workdir))


if __name__ == "__main__":
    main()
