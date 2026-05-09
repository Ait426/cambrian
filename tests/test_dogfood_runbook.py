from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "release" / "DOGFOOD_RUNBOOK.md"
REPORT = ROOT / "docs" / "release" / "DOGFOOD_REPORT.md"
CHECKLIST = ROOT / "docs" / "release" / "RC_CHECKLIST.md"
SCRIPT = ROOT / "scripts" / "dogfood_auth_bug_run.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dogfood_docs_exist_and_define_real_target_policy() -> None:
    assert RUNBOOK.exists()
    assert REPORT.exists()
    runbook = _read(RUNBOOK)

    for heading in [
        "## 1. Purpose",
        "## 2. Preconditions",
        "## 3. Target project requirements",
        "## 6. Run Auth Bug Core",
        "## 8. Ingest AI reply",
        "## 9. Validate job",
        "## 12. What counts as PASS",
        "## 13. What counts as FAIL",
    ]:
        assert heading in runbook

    assert "examples/auth_bug_demo는 dogfood 대상이 아님" in runbook
    assert "실제 Python + pytest auth/login 프로젝트" in runbook
    assert "source code 자동 apply" in runbook


def test_dogfood_report_template_records_blocked_without_target() -> None:
    report = _read(REPORT)

    assert "## Verdict" in report
    assert any(verdict in report for verdict in ["BLOCKED", "WAITING_FOR_AI_REPLY", "PARTIAL", "PASS", "FAIL"])
    assert "## Target Project" in report
    assert "## Results" in report


def test_rc_checklist_has_dogfood_gate() -> None:
    checklist = _read(CHECKLIST)

    for phrase in [
        "## Dogfood Gate",
        "실제 Python/pytest 프로젝트를 대상으로 dogfood 실행",
        "원본 프로젝트 보호 확인",
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
    assert "dogfood 대상이 아닙니다" in result.stdout


def test_readme_links_to_dogfood_runbook() -> None:
    readme = _read(ROOT / "README.md")

    assert "docs/release/DOGFOOD_RUNBOOK.md" in readme
