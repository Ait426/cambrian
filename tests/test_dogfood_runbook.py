from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "release" / "DOGFOOD_RUNBOOK.md"
REPORT = ROOT / "docs" / "release" / "DOGFOOD_REPORT.md"
CHECKLIST = ROOT / "docs" / "release" / "RC_CHECKLIST.md"
SCRIPT = ROOT / "scripts" / "dogfood_auth_bug_run.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_dogfood_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dogfood_auth_bug_run", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dogfood_docs_exist_and_define_real_target_policy() -> None:
    assert RUNBOOK.exists()
    assert REPORT.exists()
    runbook = _read(RUNBOOK)

    for heading in [
        "## 1. Purpose",
        "## 2. Preconditions",
        "## 3. Target Project Requirements",
        "## 6. Run Auth Bug Core",
        "## 8. Ingest AI Reply",
        "## 9. Validate Job",
        "## 12. What Counts As PASS",
        "## 13. What Counts As FAIL",
    ]:
        assert heading in runbook

    assert "`examples/auth_bug_demo` is not a valid dogfood target." in runbook
    assert "real Python + pytest auth/login project" in runbook
    assert "No target source file is patched automatically." in runbook


def test_dogfood_report_template_records_blocked_without_target() -> None:
    report = _read(REPORT)

    assert "## Verdict" in report
    assert any(verdict in report for verdict in ["BLOCKED", "WAITING_FOR_AI_REPLY", "PARTIAL", "PASS", "FAIL"])
    assert "## Target Project" in report
    assert "## Results" in report
    assert "## Usability Blocker Classification" in report
    assert "C:\\Users\\" not in report
    assert "<operator-local-target-redacted>" in report


def test_rc_checklist_has_dogfood_gate() -> None:
    checklist = _read(CHECKLIST)

    for phrase in [
        "## Dogfood Gate",
        "real Python/pytest project dogfood execution",
        "original project source protection verified",
        "WAITING_FOR_AI_REPLY",
        "DOGFOOD_REPORT.md",
        "examples/auth_bug_demo",
    ]:
        assert phrase in checklist


def test_dogfood_script_blocks_without_target() -> None:
    env = os.environ.copy()
    env.pop("CAMBRIAN_DOGFOOD_TARGET", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "[Task 159R-3 BLOCKED]" in result.stdout
    assert "CAMBRIAN_DOGFOOD_TARGET" in result.stdout


def test_dogfood_script_rejects_auth_bug_demo_target() -> None:
    env = os.environ.copy()
    env.pop("CAMBRIAN_DOGFOOD_TARGET", None)
    demo = ROOT / "examples" / "auth_bug_demo"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(demo)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert result.returncode == 2
    assert "examples/auth_bug_demo" in result.stdout
    assert "not a dogfood target" in result.stdout


def test_dogfood_script_writes_share_safe_partial_report(monkeypatch, tmp_path: Path) -> None:
    module = _load_dogfood_script()
    target = tmp_path / "real_project"
    target.mkdir()
    out = tmp_path / "DOGFOOD_REPORT.md"
    local_cambrian = r"C:\Users\user\AppData\Local\Programs\Python\Python314\Scripts\cambrian.exe"

    def fake_run(command: list[str], cwd: Path, *, name: str, timeout: int = 60) -> dict[str, object]:
        if command[:2] == ["git", "rev-parse"]:
            return {
                "name": name,
                "command": command,
                "cwd": str(cwd),
                "exit_code": 1,
                "duration_seconds": 0.001,
                "stdout": "",
                "stderr": "not a git repo",
                "status": "failed",
            }
        stdout = '{"job": {"job_id": "job-auth-bug-core-test"}}' if name == "pack start" else ""
        return {
            "name": name,
            "command": command,
            "cwd": str(cwd),
            "exit_code": 0,
            "duration_seconds": 0.001,
            "stdout": stdout,
            "stderr": "",
            "status": "passed",
        }

    monkeypatch.setattr(module, "_run", fake_run)
    report = module.run(target=target, ai_reply=None, out=out, cambrian=local_cambrian)

    text = out.read_text(encoding="utf-8")
    assert report["verdict"] == "PARTIAL: WAITING_FOR_AI_REPLY"
    assert "<operator-local-target-redacted>" in text
    assert "cambrian.exe pack start" in text
    assert "PARTIAL: WAITING_FOR_AI_REPLY" in text
    assert str(target) not in text
    assert r"C:\Users\user" not in text
    assert local_cambrian not in text


def test_readme_links_to_dogfood_runbook() -> None:
    readme = _read(ROOT / "README.md")

    assert "docs/release/DOGFOOD_RUNBOOK.md" in readme
