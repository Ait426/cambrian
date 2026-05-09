from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "examples" / "auth_bug_demo"
DEFAULT_REPLY = Path("fixtures") / "ai_reply_patch_candidate.yaml"
DEFAULT_OUT_ROOT = ROOT / ".launch_runs"
DOC_REPORT = ROOT / "docs" / "launch" / "LAUNCH_RC_REPORT.md"
DEFAULT_TIMEOUT_SECONDS = 30
SCHEMA_VERSION = "1.0"


@dataclass
class CommandResult:
    name: str
    title: str
    command: list[str]
    display_command: str
    cwd: str
    exit_code: int
    duration_seconds: float
    status: str
    stdout_path: str
    stderr_path: str
    stdout_excerpt: str
    stderr_excerpt: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def excerpt(text: str, limit: int = 1600) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def shell_command(command: list[str]) -> str:
    rendered: list[str] = []
    for part in command:
        if re.search(r"\s", part):
            rendered.append(json.dumps(part, ensure_ascii=False))
        else:
            rendered.append(part)
    return " ".join(rendered)


def cambrian_display(args: list[str]) -> str:
    return shell_command(["cambrian", *args])


def validate_canned_reply(fixture: Path, reply: Path = DEFAULT_REPLY) -> dict[str, Any]:
    fixture = fixture.resolve()
    reply_path = reply if reply.is_absolute() else fixture / reply
    if not fixture.exists():
        raise ValueError(f"fixture not found: {fixture}")
    if not reply_path.exists():
        raise ValueError(f"canned reply not found: {reply_path}")

    data = yaml.safe_load(read_text(reply_path)) or {}
    if data.get("response_kind") != "patch_candidate":
        raise ValueError("canned reply response_kind must be patch_candidate")

    target_rel = data.get("target_path")
    old_text = data.get("old_text")
    new_text = data.get("new_text")
    if not target_rel:
        raise ValueError("canned reply target_path is required")
    if not old_text:
        raise ValueError("canned reply old_text is required")
    if not str(new_text or "").strip():
        raise ValueError("canned reply new_text must be non-empty")

    target = fixture / str(target_rel)
    if not target.exists():
        raise ValueError(f"canned reply target_path does not exist: {target}")
    source = read_text(target)
    if str(old_text) not in source:
        raise ValueError("canned reply old_text is not present in target source")

    return {
        "reply_path": str(reply_path),
        "target_path": str(target),
        "response_kind": data.get("response_kind"),
        "old_text": old_text,
        "new_text": new_text,
    }


def prepare_output_dir(out: Path | None) -> Path:
    if out is None:
        out = DEFAULT_OUT_ROOT / run_id()
    if not out.is_absolute():
        out = ROOT / out
    out = out.resolve()

    launch_root = DEFAULT_OUT_ROOT.resolve()
    if out.exists():
        try:
            out.relative_to(launch_root)
        except ValueError as exc:
            raise ValueError(f"output path already exists outside .launch_runs: {out}") from exc
        if out == launch_root:
            raise ValueError("refusing to replace .launch_runs root")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=False)
    return out


def copy_fixture(fixture: Path, run_dir: Path) -> Path:
    workdir = run_dir / "workdir"
    shutil.copytree(fixture.resolve(), workdir)
    return workdir


def run_cli_step(
    *,
    name: str,
    title: str,
    args: list[str],
    cwd: Path,
    stdout_dir: Path,
    stderr_dir: Path,
    timeout_seconds: int,
) -> CommandResult:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    actual = [sys.executable, "-m", "engine.cli", *args]
    started = time.perf_counter()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        proc = subprocess.run(
            actual,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration = time.perf_counter() - started
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
        exit_code = -1
        errors.append(f"command timed out after {timeout_seconds}s")

    if duration > timeout_seconds:
        warnings.append(f"duration exceeded timeout target: {duration:.2f}s")
    elif duration > 30:
        warnings.append(f"command took longer than 30s: {duration:.2f}s")

    status = "passed" if exit_code == 0 and not errors else "failed"
    if exit_code != 0 and not errors:
        errors.append(f"exit code {exit_code}")

    stdout_path = stdout_dir / f"{name}.stdout.txt"
    stderr_path = stderr_dir / f"{name}.stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    return CommandResult(
        name=name,
        title=title,
        command=actual,
        display_command=cambrian_display(args),
        cwd=str(cwd),
        exit_code=exit_code,
        duration_seconds=round(duration, 3),
        status=status,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_excerpt=excerpt(stdout),
        stderr_excerpt=excerpt(stderr),
        warnings=warnings,
        errors=errors,
    )


def extract_job_id(step: CommandResult) -> str:
    try:
        data = json.loads(Path(step.stdout_path).read_text(encoding="utf-8"))
        job_id = data.get("job", {}).get("job_id")
        if job_id:
            return str(job_id)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\bjob-[A-Za-z0-9_.-]+", step.stdout_excerpt)
    if match:
        return match.group(0)
    raise ValueError("job id could not be extracted from pack start output")


def extract_packet_ref(step: CommandResult) -> str | None:
    try:
        data = json.loads(Path(step.stdout_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = data.get("job", {}).get("linked_bridge_packet_ref")
    return str(value) if value else None


def validation_passed(step: CommandResult) -> bool:
    try:
        data = json.loads(Path(step.stdout_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return data.get("validation_status") == "validated"


def build_summary(
    *,
    generated_at: str,
    fixture: Path,
    workdir: Path,
    steps: list[CommandResult],
    job_id: str | None,
    packet_ref: str | None,
    validated: bool,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    errors = [error for step in steps for error in step.errors]
    warnings = [warning for step in steps for warning in step.warnings]
    status = "passed" if not errors and validated else "failed"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "status": status,
        "fixture": str(fixture),
        "workdir": str(workdir),
        "steps": [
            {
                "name": step.name,
                "command": step.display_command,
                "exit_code": step.exit_code,
                "duration_seconds": step.duration_seconds,
                "status": step.status,
            }
            for step in steps
        ],
        "job_id": job_id,
        "packet_ref": packet_ref,
        "validated": validated,
        "preflight": preflight,
        "warnings": warnings,
        "errors": errors,
    }


def write_json(path: Path, data: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_transcript(path: Path, *, generated_at: str, fixture: Path, workdir: Path, steps: list[CommandResult]) -> None:
    lines = [
        "# Cambrian Launch Demo Transcript",
        "",
        "## Environment",
        f"- fixture: `{fixture}`",
        f"- workdir: `{workdir}`",
        f"- generated_at: `{generated_at}`",
        f"- python: `{sys.version.split()[0]}`",
        f"- platform: `{platform.platform()}`",
        "",
    ]
    for index, step in enumerate(steps, start=1):
        lines.extend(
            [
                f"## Step {index} -- {step.title}",
                "",
                "Command:",
                "```bash",
                step.display_command,
                "```",
                "",
                f"CWD: `{step.cwd}`",
                f"Exit code: `{step.exit_code}`",
                f"Duration: `{step.duration_seconds}s`",
                f"Status: `{step.status}`",
                "",
                "Stdout excerpt:",
                "```text",
                step.stdout_excerpt.strip(),
                "```",
                "",
                "Stderr excerpt:",
                "```text",
                step.stderr_excerpt.strip(),
                "```",
                "",
            ]
        )
        if step.warnings:
            lines.extend(["Warnings:", *[f"- {warning}" for warning in step.warnings], ""])
        if step.errors:
            lines.extend(["Errors:", *[f"- {error}" for error in step.errors], ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_launch_rc_report(path: Path, summary: dict[str, Any], transcript_ref: str) -> None:
    verdict = "PASS" if summary["status"] == "passed" else "FAIL"
    ready = "Ready" if verdict == "PASS" else "Not ready"
    commands = "\n".join(f"- `{step['command']}` -> {step['status']} ({step['duration_seconds']}s)" for step in summary["steps"])
    errors = summary.get("errors") or []
    warnings = summary.get("warnings") or []
    lines = [
        "# Launch RC Report",
        "",
        "## Verdict",
        verdict,
        "",
        "## What was tested",
        "- Auth Bug Core install",
        "- activation",
        "- pack start",
        "- canned reply ingest",
        "- validation",
        "- local proof check",
        "",
        "## Commands",
        commands,
        "",
        "## Result",
        f"- status: `{summary['status']}`",
        f"- job_id: `{summary.get('job_id')}`",
        f"- packet_ref: `{summary.get('packet_ref')}`",
        f"- validated: `{summary.get('validated')}`",
        f"- transcript: `{transcript_ref}`",
        "",
        "## Known manual steps",
        "- Real demos still require pasting the generated packet into the AI a user already uses.",
        "- This RC dry run uses a canned AI reply fixture and does not call any AI provider.",
        "- Fixture evidence is local demo evidence, not public benchmark proof.",
        "",
        "## Launch blockers",
    ]
    if errors:
        lines.extend([f"- {error}" for error in errors])
    else:
        lines.append("- None from the latest dry run.")
    if warnings:
        lines.extend(["", "## Warnings", *[f"- {warning}" for warning in warnings]])
    lines.extend(
        [
            "",
            "## Non-launch scope",
            "- registry",
            "- rollout",
            "- vNext",
            "- marketplace",
            "- cloud execution",
            "",
            "## Final decision",
            ready,
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def abort_on_failed_step(step: CommandResult) -> None:
    if step.status == "passed":
        return
    raise RuntimeError(
        "\n".join(
            [
                f"Launch demo step failed: {step.name}",
                f"Command: {step.display_command}",
                f"CWD: {step.cwd}",
                f"Exit code: {step.exit_code}",
                f"Duration: {step.duration_seconds}s",
                "STDOUT:",
                step.stdout_excerpt,
                "STDERR:",
                step.stderr_excerpt,
                "Hint: run the same command inside the recorded workdir.",
            ]
        )
    )


def run_launch_demo(
    *,
    fixture: Path = DEFAULT_FIXTURE,
    out: Path | None = None,
    keep_workdir: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    report_path: Path = DOC_REPORT,
) -> dict[str, Any]:
    del keep_workdir
    fixture = fixture.resolve()
    preflight = validate_canned_reply(fixture)
    run_dir = prepare_output_dir(out)
    stdout_dir = run_dir / "stdout"
    stderr_dir = run_dir / "stderr"
    stdout_dir.mkdir()
    stderr_dir.mkdir()
    workdir = copy_fixture(fixture, run_dir)
    generated_at = utc_now()

    steps: list[CommandResult] = []

    def add_step(name: str, title: str, args: list[str]) -> CommandResult:
        step = run_cli_step(
            name=name,
            title=title,
            args=args,
            cwd=workdir,
            stdout_dir=stdout_dir,
            stderr_dir=stderr_dir,
            timeout_seconds=timeout_seconds,
        )
        steps.append(step)
        abort_on_failed_step(step)
        return step

    add_step("pack_show", "Show pack", ["pack", "show", "auth-bug-core"])
    add_step("install_pack", "Install pack", ["install", "pack", "auth-bug-core"])
    add_step("install_doctor", "Install doctor", ["install", "doctor"])
    add_step("pack_activate", "Activate pack", ["pack", "activate", "auth-bug-core"])
    add_step("pack_doctor", "Pack doctor", ["pack", "doctor", "auth-bug-core"])
    start = add_step("pack_start", "Start job", ["pack", "start", "로그인 에러 수정해", "--json"])
    job_id = extract_job_id(start)
    packet_ref = extract_packet_ref(start)
    add_step("job_ingest", "Ingest canned AI reply", ["pack", "job-ingest", job_id, str(DEFAULT_REPLY), "--json"])
    validate = add_step("job_validate", "Validate job", ["pack", "job-validate", job_id, "--json"])
    proof = add_step("pack_proof", "Check local proof", ["pack", "proof", "auth-bug-core"])

    validated = validation_passed(validate)
    if not validated:
        proof.errors.append("validation_status was not validated")

    summary = build_summary(
        generated_at=generated_at,
        fixture=fixture,
        workdir=workdir,
        steps=steps,
        job_id=job_id,
        packet_ref=packet_ref,
        validated=validated,
        preflight=preflight,
    )
    write_json(run_dir / "commands.json", [asdict(step) for step in steps])
    write_json(run_dir / "summary.json", summary)
    write_transcript(run_dir / "transcript.md", generated_at=generated_at, fixture=fixture, workdir=workdir, steps=steps)
    try:
        transcript_ref = str((run_dir / "transcript.md").resolve().relative_to(ROOT))
    except ValueError:
        transcript_ref = str(run_dir / "transcript.md")
    write_launch_rc_report(report_path, summary, transcript_ref)
    return {
        "run_dir": str(run_dir),
        "transcript": str(run_dir / "transcript.md"),
        "summary": str(run_dir / "summary.json"),
        "report": str(report_path),
        "status": summary["status"],
        "job_id": job_id,
        "proof_exit_code": proof.exit_code,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cambrian Auth Bug Core 출시 데모 dry run을 실행하고 증거를 저장합니다.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="데모 fixture 디렉터리")
    parser.add_argument("--out", default=None, help="출시 dry-run 출력 디렉터리")
    parser.add_argument("--keep-workdir", action="store_true", help="호환 옵션입니다. workdir은 항상 evidence로 보존됩니다.")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="각 CLI 명령 timeout 초")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_launch_demo(
            fixture=Path(args.fixture),
            out=Path(args.out) if args.out else None,
            keep_workdir=args.keep_workdir,
            timeout_seconds=args.timeout,
        )
    except Exception as exc:
        print(f"Launch demo dry run failed: {exc}", file=sys.stderr)
        return 1

    print("Launch demo dry run complete.")
    print(f"Status: {result['status']}")
    print(f"Transcript: {result['transcript']}")
    print(f"Summary: {result['summary']}")
    print(f"Report: {result['report']}")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
