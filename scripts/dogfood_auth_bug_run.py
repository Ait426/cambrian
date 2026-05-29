from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUEST_TEXT = "Fix the login error"
FAILURE_CLASSES = [
    "INSTALL_FAILURE",
    "DOCTOR_FAILURE",
    "PACK_CATALOG_FAILURE",
    "PACK_INSTALL_FAILURE",
    "PACK_ACTIVATE_FAILURE",
    "PACK_START_FAILURE",
    "AI_REPLY_FORMAT_FAILURE",
    "JOB_INGEST_FAILURE",
    "JOB_VALIDATE_FAILURE",
    "OUTPUT_NOT_ACTIONABLE",
    "VALIDATION_NOT_TRUSTWORTHY",
    "USER_FLOW_CONFUSING",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(command: list[str], cwd: Path, *, name: str, timeout: int = 60) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "exit_code": result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "passed" if result.returncode == 0 else "failed",
    }


def _redacted_command(command: list[str]) -> str:
    parts: list[str] = []
    for index, part in enumerate(command):
        candidate = Path(part)
        if index == 0 and (candidate.is_absolute() or "\\" in part or "/" in part):
            parts.append(candidate.name or "<cambrian>")
        elif candidate.is_absolute():
            parts.append("<local-path>")
        else:
            parts.append(part)
    return " ".join(parts)


def _git_info(target: Path) -> dict[str, Any]:
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], target, name="git repo check", timeout=15)
    is_repo = inside["exit_code"] == 0 and inside["stdout"].strip().lower() == "true"
    if not is_repo:
        return {
            "is_repo": False,
            "dirty": None,
            "status_before": "not a git repo",
            "warnings": ["Target is not a git repository; source protection evidence is weaker."],
        }
    status = _run(["git", "status", "--short"], target, name="git status before", timeout=15)
    status_text = status["stdout"].strip()
    return {
        "is_repo": True,
        "dirty": bool(status_text),
        "status_before": status_text or "clean",
        "warnings": ["Target git tree is dirty before dogfood run."] if status_text else [],
    }


def _extract_job_id(step: dict[str, Any]) -> str | None:
    try:
        payload = json.loads(step.get("stdout") or "{}")
    except json.JSONDecodeError:
        payload = {}
    job = payload.get("job") if isinstance(payload, dict) else None
    if isinstance(job, dict) and job.get("job_id"):
        return str(job["job_id"])
    match = re.search(r"job-[A-Za-z0-9_.:-]+", f"{step.get('stdout', '')}\n{step.get('stderr', '')}")
    return match.group(0) if match else None


def _classify_failure(step_name: str) -> str:
    return {
        "cambrian doctor": "DOCTOR_FAILURE",
        "pack list": "PACK_CATALOG_FAILURE",
        "pack show auth-bug-core": "PACK_CATALOG_FAILURE",
        "install pack auth-bug-core": "PACK_INSTALL_FAILURE",
        "activate auth-bug-core": "PACK_ACTIVATE_FAILURE",
        "pack start": "PACK_START_FAILURE",
        "job-ingest": "JOB_INGEST_FAILURE",
        "job-validate": "JOB_VALIDATE_FAILURE",
    }.get(step_name, "OUTPUT_NOT_ACTIONABLE")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    rows = []
    for step in report["steps"]:
        rows.append(
            f"| {step['name']} | {step['result']} | {step['duration_seconds']}s | {step.get('notes', '')} |"
        )
    rows_text = "\n".join(rows)
    commands = "\n".join(report["commands"])
    blocker_lines = "\n".join(f"- {item}" for item in report["blockers"]) or "- none"
    confusion_lines = "\n".join(f"- {item}" for item in report["confusing_points"]) or "- not evaluated yet"
    git_status = report["target"]["git_status_before"].replace("\n", "\n  ")
    ai_reply = report.get("ai_reply") or "not provided"
    text = f"""# Cambrian Dogfood Report

## Date

{report['date']}

## Target Project

- Path: {report['target']['path']}
- Language: Python
- Test command: pytest or project equivalent
- Git repo: {report['target']['git_repo']}
- Dirty tree before: {report['target']['dirty_tree']}
- Git status before:

```text
{git_status}
```

## Cambrian RC

- Install mode: installed `cambrian` command or provided executable
- Version: recorded by command output if available
- Wheel: see `docs/release/RC_VERIFICATION.md`
- Python: {sys.version.split()[0]}

## Commands

```bash
{commands}
```

## AI Reply

- Reply file: {ai_reply}
- Provider API call: none

## Results

| Step | Result | Duration | Notes |
| --- | ---: | ---: | --- |
{rows_text}

## Human Evaluation

- Was the next command clear: not evaluated yet
- Was the output actionable: not evaluated yet
- Did the result identify a useful patch/test direction: not evaluated yet
- Was validation trustworthy: not evaluated yet
- What was confusing:
{confusion_lines}

## Blockers

{blocker_lines}

## Failure Classes

```text
{', '.join(FAILURE_CLASSES)}
```

## Source Protection

- Automatic patch apply: no
- Provider API call: no
- Allowed target metadata: `.cambrian/`
- Cambrian repo report file: docs/release/DOGFOOD_REPORT.md

## Verdict

{report['verdict']}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _blocked(message: str) -> int:
    print("[Task 159R-3 BLOCKED]")
    print()
    print("Reason:")
    print(f"- {message}")
    print()
    print("Next action:")
    print("- Provide a real Python + pytest auth/login project through `--target` or CAMBRIAN_DOGFOOD_TARGET.")
    return 2


def run(target: Path, ai_reply: Path | None, out: Path, cambrian: str) -> dict[str, Any]:
    root = _repo_root()
    resolved_target = target.resolve()
    demo_path = (root / "examples" / "auth_bug_demo").resolve()
    if resolved_target == demo_path:
        raise SystemExit(_blocked("examples/auth_bug_demo is a smoke fixture, not a dogfood target."))
    if not resolved_target.exists() or not resolved_target.is_dir():
        raise SystemExit(_blocked(f"Target project does not exist: {resolved_target}"))

    git = _git_info(resolved_target)
    steps: list[dict[str, Any]] = []
    blockers: list[str] = []
    commands: list[str] = []

    flow = [
        ("cambrian doctor", [cambrian, "doctor"]),
        ("pack list", [cambrian, "pack", "list"]),
        ("pack show auth-bug-core", [cambrian, "pack", "show", "auth-bug-core"]),
        ("install pack auth-bug-core", [cambrian, "install", "pack", "auth-bug-core"]),
        ("activate auth-bug-core", [cambrian, "pack", "activate", "auth-bug-core"]),
        ("pack start", [cambrian, "pack", "start", REQUEST_TEXT, "--json"]),
    ]

    job_id: str | None = None
    for name, command in flow:
        commands.append(_redacted_command(command))
        step = _run(command, resolved_target, name=name)
        steps.append(step)
        if step["exit_code"] != 0:
            blockers.append(f"{_classify_failure(name)}: {name} failed")
            break
        if name == "pack start":
            job_id = _extract_job_id(step)
            if not job_id:
                blockers.append("OUTPUT_NOT_ACTIONABLE: pack start did not expose a job id")

    if not blockers and ai_reply:
        reply_path = ai_reply.resolve()
        if not reply_path.exists():
            blockers.append(f"AI_REPLY_FORMAT_FAILURE: AI reply file not found: <local-path>")
        else:
            for name, command in [
                ("job-ingest", [cambrian, "pack", "job-ingest", job_id or "latest", str(reply_path), "--json"]),
                ("job-validate", [cambrian, "pack", "job-validate", job_id or "latest", "--json"]),
            ]:
                commands.append(_redacted_command(command))
                step = _run(command, resolved_target, name=name)
                steps.append(step)
                if step["exit_code"] != 0:
                    blockers.append(f"{_classify_failure(name)}: {name} failed")
                    break

    verdict = "FAIL" if blockers else ("PARTIAL: WAITING_FOR_AI_REPLY" if not ai_reply else "PASS")
    report_steps = [
        {
            "name": step["name"],
            "result": "PASS" if step["status"] == "passed" else "FAIL",
            "duration_seconds": step["duration_seconds"],
            "notes": "ok" if step["status"] == "passed" else (step.get("stderr") or step.get("stdout") or "")[:160],
        }
        for step in steps
    ]
    if not ai_reply and not blockers:
        report_steps.extend(
            [
                {"name": "job-ingest", "result": "SKIPPED", "duration_seconds": "", "notes": "waiting for AI reply"},
                {"name": "job-validate", "result": "SKIPPED", "duration_seconds": "", "notes": "waiting for AI reply"},
            ]
        )

    report = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "target": {
            "path": "<operator-local-target-redacted>",
            "git_repo": git["is_repo"],
            "dirty_tree": git["dirty"],
            "git_status_before": git["status_before"],
        },
        "commands": commands,
        "steps": report_steps,
        "job_id": job_id,
        "ai_reply": "<operator-local-ai-reply-redacted>" if ai_reply else None,
        "blockers": blockers,
        "confusing_points": [],
        "verdict": verdict,
    }
    _write_report(out, report)
    print(f"Result: {verdict}")
    print(f"Report: {out}")
    if job_id:
        print(f"Job ID: {job_id}")
    if blockers:
        raise SystemExit(1)
    return report


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run Auth Bug Core dogfood against a real Python/pytest project.")
    parser.add_argument("--target", type=Path, default=None, help="real Python/pytest target project")
    parser.add_argument("--ai-reply", type=Path, default=None, help="optional AI reply YAML file to ingest")
    parser.add_argument("--out", type=Path, default=_repo_root() / "docs" / "release" / "DOGFOOD_REPORT.md")
    parser.add_argument("--cambrian", default=os.environ.get("CAMBRIAN_BIN", "cambrian"))
    args = parser.parse_args()

    target = args.target or (Path(os.environ["CAMBRIAN_DOGFOOD_TARGET"]) if os.environ.get("CAMBRIAN_DOGFOOD_TARGET") else None)
    if target is None:
        raise SystemExit(_blocked("CAMBRIAN_DOGFOOD_TARGET or --target is required."))
    run(target=target, ai_reply=args.ai_reply, out=args.out, cambrian=args.cambrian)


if __name__ == "__main__":
    main()
