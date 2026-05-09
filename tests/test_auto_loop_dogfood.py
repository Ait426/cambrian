from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "auto_loop_dogfood.py"), *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_auto_loop_dogfood_docs_exist() -> None:
    assert (ROOT / "docs" / "release" / "AUTO_LOOP_DOGFOOD_RUNBOOK.md").exists()
    assert (ROOT / "docs" / "release" / "AUTO_LOOP_DOGFOOD_REPORT.md").exists()
    assert (ROOT / "scripts" / "auto_loop_dogfood.py").exists()


def test_auto_loop_dogfood_script_does_not_fake_pass_without_target(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    result = run_script("--out", str(report))

    assert result.returncode == 2
    assert "Result: BLOCKED" in result.stdout
    assert "target project is required" in result.stdout
    assert "PASS" not in result.stdout
    assert report.exists()
    assert "BLOCKED" in report.read_text(encoding="utf-8")


def test_auto_loop_dogfood_rejects_auth_bug_demo_target(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    result = run_script("--target", str(ROOT / "examples" / "auth_bug_demo"), "--out", str(report))

    assert result.returncode == 2
    assert "Result: BLOCKED" in result.stdout
    assert "demo project cannot be used" in result.stdout
    assert "PASS" not in result.stdout


def test_auto_loop_dogfood_runbook_names_required_loop() -> None:
    text = (ROOT / "docs" / "release" / "AUTO_LOOP_DOGFOOD_RUNBOOK.md").read_text(encoding="utf-8")

    for phrase in [
        "auto cycle",
        "auto step ingest",
        "WAITING_FOR_RESULT",
        "examples/auth_bug_demo",
        "source patches",
    ]:
        assert phrase in text


def test_rc_checklist_links_auto_loop_dogfood_gate() -> None:
    checklist = (ROOT / "docs" / "release" / "RC_CHECKLIST.md").read_text(encoding="utf-8")

    for phrase in [
        "Auto Loop Dogfood Gate",
        "AUTO_LOOP_DOGFOOD_REPORT.md",
        "auto step ingest",
    ]:
        assert phrase in checklist
