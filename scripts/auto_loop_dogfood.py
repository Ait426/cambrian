from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_GOAL = "Validate Cambrian auto loop on a real project"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _excerpt(text: str, limit: int = 1200) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _is_within(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_target_label(target: Path) -> str:
    return f"{target.name} (sanitized path)"


def _is_rejected_demo_target(repo_root: Path, target: Path) -> bool:
    demo = (repo_root / "examples" / "auth_bug_demo").resolve()
    resolved = target.resolve()
    if resolved == demo:
        return True
    if _is_within(demo, resolved):
        return True
    return False


def _cambrian_prefix(args: argparse.Namespace) -> tuple[list[str], bool]:
    if args.cambrian:
        return [args.cambrian], False
    return [sys.executable, "-m", "engine.cli"], True


def _subprocess_env(repo_root: Path, use_repo_cli: bool) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if use_repo_cli:
        previous = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(repo_root) if not previous else str(repo_root) + os.pathsep + previous
    return env


def _run(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout: int = 90,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        duration = round(time.perf_counter() - started, 3)
        return {
            "name": name,
            "command": " ".join(command),
            "returncode": completed.returncode,
            "result": "PASS" if completed.returncode == 0 else "FAIL",
            "duration": duration,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "payload": _parse_json(completed.stdout),
        }
    except FileNotFoundError as exc:
        return {
            "name": name,
            "command": " ".join(command),
            "returncode": 127,
            "result": "FAIL",
            "duration": round(time.perf_counter() - started, 3),
            "stdout": "",
            "stderr": str(exc),
            "payload": {},
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "command": " ".join(command),
            "returncode": 124,
            "result": "FAIL",
            "duration": round(time.perf_counter() - started, 3),
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "command timed out",
            "payload": {},
        }


def _parse_json(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _git_status(target: Path) -> dict[str, Any]:
    git_dir = target / ".git"
    if not git_dir.exists():
        return {"is_git_repo": False, "status": "not a git repo"}
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=str(target),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return {
        "is_git_repo": True,
        "status": result.stdout.strip() or "clean",
        "returncode": result.returncode,
    }


def _step_table(steps: list[dict[str, Any]]) -> str:
    lines = ["| Step | Result | Duration | Notes |", "|---|---:|---:|---|"]
    for step in steps:
        notes = ""
        payload = step.get("payload") or {}
        if payload.get("error"):
            notes = str(payload["error"])
        elif payload.get("failed_step"):
            notes = f"failed_step={payload['failed_step']}"
        elif step.get("stderr"):
            notes = _excerpt(str(step["stderr"]), 140).replace("\n", " ")
        lines.append(f"| {step['name']} | {step['result']} | {step['duration']}s | {notes} |")
    return "\n".join(lines)


def _write_report(
    *,
    out_path: Path,
    target: Path | None,
    mode: str,
    verdict: str,
    repo_cli_used: bool,
    git_before: dict[str, Any] | None,
    git_after: dict[str, Any] | None,
    task_ref: str | None,
    result_file: Path | None,
    steps: list[dict[str, Any]],
    reason: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target_label = _safe_target_label(target) if target else "not provided"
    result_label = result_file.name if result_file else "not provided"
    report = f"""# Auto Loop Dogfood Report

## Date

{_now()}

## Target

- Mode: {mode}
- Target: {target_label}
- Git repo before: {(git_before or {}).get("is_git_repo", "unknown")}
- Git status before: {(git_before or {}).get("status", "unknown")}
- Git repo after: {(git_after or {}).get("is_git_repo", "unknown")}
- Git status after: {(git_after or {}).get("status", "unknown")}

## Cambrian Execution

- Repo CLI used: {"yes" if repo_cli_used else "no"}
- Result file: {result_label}
- Task ref: {task_ref or "not created"}

## Command Results

{_step_table(steps)}

## Verdict

{verdict}

## Reason

{reason}

## Safety

- Demo target was not accepted as a real project.
- The script does not create a fake PASS without a target.
- The auto loop creates Cambrian metadata and Codex/Claude task directives only.
- Source patch application is not performed by this script.

## Next Action

- If verdict is `WAITING_FOR_RESULT`, execute the generated directive in Codex or Claude.
- Save the result using the hardened result contract.
- Run `cambrian auto step ingest <task-ref> --result <result-file> --json`.
- Run `cambrian auto cycle --max-steps 1 --json` again.
"""
    out_path.write_text(report, encoding="utf-8")


def _blocked(reason: str, out_path: Path | None = None) -> int:
    if out_path:
        _write_report(
            out_path=out_path,
            target=None,
            mode="blocked",
            verdict="BLOCKED",
            repo_cli_used=False,
            git_before=None,
            git_after=None,
            task_ref=None,
            result_file=None,
            steps=[],
            reason=reason,
        )
    print("[Auto Loop Dogfood]")
    print("Result: BLOCKED")
    print(f"Reason: {reason}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="실제 프로젝트 auto loop dogfood 검증")
    parser.add_argument("--target", default=os.environ.get("CAMBRIAN_AUTO_LOOP_TARGET"))
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--result", default=None, help="auto step ingest에 사용할 결과 YAML/JSON")
    parser.add_argument("--task-ref", default=None, help="이미 생성된 auto task ref")
    parser.add_argument("--out", default="docs/release/AUTO_LOOP_DOGFOOD_REPORT.md")
    parser.add_argument("--cambrian", default=os.environ.get("CAMBRIAN_COMMAND"))
    parser.add_argument("--max-steps", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = _repo_root()
    out_path = (repo_root / args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    if not args.target:
        return _blocked("target project is required", out_path)

    target = Path(args.target).expanduser().resolve()
    if _is_rejected_demo_target(repo_root, target):
        return _blocked("demo project cannot be used as real auto loop dogfood target", out_path)
    if not target.exists() or not target.is_dir():
        return _blocked("target project does not exist or is not a directory", out_path)

    result_file = Path(args.result).expanduser().resolve() if args.result else None
    if result_file is not None and not result_file.exists():
        return _blocked("result file does not exist", out_path)

    prefix, repo_cli_used = _cambrian_prefix(args)
    env = _subprocess_env(repo_root, repo_cli_used)
    git_before = _git_status(target)
    steps: list[dict[str, Any]] = []

    def run_cli(name: str, *cli_args: str) -> dict[str, Any]:
        step = _run(name=name, command=[*prefix, *cli_args], cwd=target, env=env)
        steps.append(step)
        return step

    if result_file is not None and args.task_ref:
        task_ref = str(args.task_ref)
        ingest = run_cli("auto step ingest", "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
        if ingest["returncode"] != 0:
            git_after = _git_status(target)
            _write_report(
                out_path=out_path,
                target=target,
                mode="real target auto loop with existing task result",
                verdict="FAIL",
                repo_cli_used=repo_cli_used,
                git_before=git_before,
                git_after=git_after,
                task_ref=task_ref,
                result_file=result_file,
                steps=steps,
                reason="auto step ingest failed",
            )
            print("Result: FAIL")
            return 1
        run_cli("auto cycle after ingest", "auto", "cycle", "--max-steps", str(args.max_steps), "--json")
        final_step = steps[-1]
        verdict = "PASS" if final_step["returncode"] == 0 else "FAIL"
        git_after = _git_status(target)
        _write_report(
            out_path=out_path,
            target=target,
            mode="real target auto loop with existing task result",
            verdict=verdict,
            repo_cli_used=repo_cli_used,
            git_before=git_before,
            git_after=git_after,
            task_ref=task_ref,
            result_file=result_file,
            steps=steps,
            reason="existing task result was ingested and a follow-up auto cycle was executed",
        )
        print("[Auto Loop Dogfood]")
        print(f"Task ref: {task_ref}")
        print(f"Result: {verdict}")
        return 0 if verdict == "PASS" else 1

    run_cli("authority grant", "authority", "grant", "--mode", "full-authority", "--json")
    if steps[-1]["returncode"] != 0:
        git_after = _git_status(target)
        _write_report(
            out_path=out_path,
            target=target,
            mode="real target auto loop",
            verdict="FAIL",
            repo_cli_used=repo_cli_used,
            git_before=git_before,
            git_after=git_after,
            task_ref=None,
            result_file=result_file,
            steps=steps,
            reason="authority grant failed",
        )
        print("Result: FAIL")
        return 1

    run_cli("auto init", "auto", "init", "--goal", str(args.goal), "--json")
    if steps[-1]["returncode"] != 0:
        git_after = _git_status(target)
        _write_report(
            out_path=out_path,
            target=target,
            mode="real target auto loop",
            verdict="FAIL",
            repo_cli_used=repo_cli_used,
            git_before=git_before,
            git_after=git_after,
            task_ref=None,
            result_file=result_file,
            steps=steps,
            reason="auto init failed",
        )
        print("Result: FAIL")
        return 1

    first_cycle = run_cli("auto cycle", "auto", "cycle", "--max-steps", str(args.max_steps), "--json")
    task_refs = list((first_cycle.get("payload") or {}).get("task_refs") or [])
    task_ref = str(task_refs[0]) if task_refs else None
    if first_cycle["returncode"] != 0 or not task_ref:
        git_after = _git_status(target)
        _write_report(
            out_path=out_path,
            target=target,
            mode="real target auto loop",
            verdict="FAIL",
            repo_cli_used=repo_cli_used,
            git_before=git_before,
            git_after=git_after,
            task_ref=task_ref,
            result_file=result_file,
            steps=steps,
            reason="auto cycle failed or no task ref was created",
        )
        print("Result: FAIL")
        return 1

    if result_file is None:
        git_after = _git_status(target)
        _write_report(
            out_path=out_path,
            target=target,
            mode="real target auto loop",
            verdict="WAITING_FOR_RESULT",
            repo_cli_used=repo_cli_used,
            git_before=git_before,
            git_after=git_after,
            task_ref=task_ref,
            result_file=None,
            steps=steps,
            reason="auto cycle created an external task directive and is waiting for Codex/Claude result",
        )
        print("[Auto Loop Dogfood]")
        print(f"Task ref: {task_ref}")
        print("Result: WAITING_FOR_RESULT")
        return 0

    ingest = run_cli("auto step ingest", "auto", "step", "ingest", task_ref, "--result", str(result_file), "--json")
    if ingest["returncode"] != 0:
        git_after = _git_status(target)
        _write_report(
            out_path=out_path,
            target=target,
            mode="real target auto loop with result",
            verdict="FAIL",
            repo_cli_used=repo_cli_used,
            git_before=git_before,
            git_after=git_after,
            task_ref=task_ref,
            result_file=result_file,
            steps=steps,
            reason="auto step ingest failed",
        )
        print("Result: FAIL")
        return 1

    run_cli("auto cycle after ingest", "auto", "cycle", "--max-steps", str(args.max_steps), "--json")
    final_step = steps[-1]
    verdict = "PASS" if final_step["returncode"] == 0 else "FAIL"
    git_after = _git_status(target)
    _write_report(
        out_path=out_path,
        target=target,
        mode="real target auto loop with result",
        verdict=verdict,
        repo_cli_used=repo_cli_used,
        git_before=git_before,
        git_after=git_after,
        task_ref=task_ref,
        result_file=result_file,
        steps=steps,
        reason="result was ingested and a follow-up auto cycle was executed",
    )
    print("[Auto Loop Dogfood]")
    print(f"Task ref: {task_ref}")
    print(f"Result: {verdict}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
