from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools import run_launch_demo


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "auth_bug_demo"
RUNNER = ROOT / "tools" / "run_launch_demo.py"


def _run_python(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )


def _debug(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"command={result.args}\n"
        f"returncode={result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _fake_step(tmp_path: Path) -> run_launch_demo.CommandResult:
    stdout = tmp_path / "step.stdout.txt"
    stderr = tmp_path / "step.stderr.txt"
    stdout.write_text("ok\n", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    return run_launch_demo.CommandResult(
        name="pack_show",
        title="Show pack",
        command=[sys.executable, "-m", "engine.cli", "pack", "show", "auth-bug-core"],
        display_command="cambrian pack show auth-bug-core",
        cwd=str(tmp_path),
        exit_code=0,
        duration_seconds=0.1,
        status="passed",
        stdout_path=str(stdout),
        stderr_path=str(stderr),
        stdout_excerpt="ok",
        stderr_excerpt="",
    )


def test_runner_file_exists_and_help_works() -> None:
    assert RUNNER.exists()
    result = _run_python(str(RUNNER), "--help")

    assert result.returncode == 0, _debug(result)
    assert "--fixture" in result.stdout
    assert "--out" in result.stdout
    assert "--keep-workdir" in result.stdout


def test_canned_reply_preflight_validates_fixture() -> None:
    preflight = run_launch_demo.validate_canned_reply(DEMO)

    assert preflight["response_kind"] == "patch_candidate"
    assert preflight["old_text"] == "return username"
    assert preflight["new_text"] == "return username.strip().lower()"
    assert Path(preflight["target_path"]).exists()


def test_transcript_and_summary_writers(tmp_path: Path) -> None:
    step = _fake_step(tmp_path)
    transcript = tmp_path / "transcript.md"
    summary_path = tmp_path / "summary.json"

    run_launch_demo.write_transcript(
        transcript,
        generated_at="2026-05-05T00:00:00+00:00",
        fixture=DEMO,
        workdir=tmp_path,
        steps=[step],
    )
    summary = run_launch_demo.build_summary(
        generated_at="2026-05-05T00:00:00+00:00",
        fixture=DEMO,
        workdir=tmp_path,
        steps=[step],
        job_id="job-demo",
        packet_ref=".cambrian/bridge/packets/packet-demo.yaml",
        validated=True,
        preflight={"response_kind": "patch_candidate"},
    )
    run_launch_demo.write_json(summary_path, summary)

    assert "Cambrian Launch Demo Transcript" in transcript.read_text(encoding="utf-8")
    loaded = json.loads(summary_path.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "1.0"
    assert loaded["status"] == "passed"
    assert loaded["steps"][0]["name"] == "pack_show"


def test_launch_rc_report_writer(tmp_path: Path) -> None:
    report = tmp_path / "LAUNCH_RC_REPORT.md"
    summary = {
        "status": "passed",
        "steps": [{"command": "cambrian pack show auth-bug-core", "status": "passed", "duration_seconds": 0.1}],
        "job_id": "job-demo",
        "packet_ref": ".cambrian/bridge/packets/packet-demo.yaml",
        "validated": True,
        "warnings": [],
        "errors": [],
    }

    run_launch_demo.write_launch_rc_report(report, summary, ".launch_runs/latest/transcript.md")
    text = report.read_text(encoding="utf-8")

    assert "## Verdict" in text
    assert "PASS" in text
    assert "This RC dry run uses a canned AI reply fixture" in text
    assert "does not call any AI provider" in text


def test_runner_uses_temp_copy_and_does_not_mutate_original(tmp_path: Path) -> None:
    original = (DEMO / "src" / "auth.py").read_text(encoding="utf-8")
    result = run_launch_demo.run_launch_demo(
        fixture=DEMO,
        out=tmp_path / "run",
        report_path=tmp_path / "LAUNCH_RC_REPORT.md",
        timeout_seconds=30,
    )

    assert result["status"] == "passed"
    assert Path(result["transcript"]).exists()
    assert Path(result["summary"]).exists()
    assert Path(result["report"]).exists()
    assert (DEMO / "src" / "auth.py").read_text(encoding="utf-8") == original
    summary = json.loads(Path(result["summary"]).read_text(encoding="utf-8"))
    assert summary["validated"] is True
    assert summary["job_id"].startswith("job-")


def test_docs_mention_canned_reply_and_no_provider_call() -> None:
    combined = "\n".join(
        [
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "launch" / "DEMO_RUNBOOK.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "launch" / "LAUNCH_RC_REPORT.md").read_text(encoding="utf-8"),
        ]
    ).lower()

    assert "canned ai reply" in combined
    assert "does not call any ai provider" in combined
    assert "python tools/run_launch_demo.py" in combined


def test_launch_runner_docs_make_no_fake_proof_claims() -> None:
    combined = "\n".join(
        [
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "launch" / "DEMO_RUNBOOK.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "launch" / "LAUNCH_RC_REPORT.md").read_text(encoding="utf-8"),
        ]
    ).lower()

    for forbidden in [
        "guaranteed",
        "fully autonomous",
        "proven best",
        "72% validated proposal rate",
        "100% success",
    ]:
        assert forbidden not in combined

    assert "fixture evidence is local first-run evidence" in combined
