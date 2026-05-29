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
        "role_outputs",
        "scope",
        "acceptance_criteria",
        "test_plan",
        "examples/auth_bug_demo",
        "source patches",
    ]:
        assert phrase in text


def test_auto_loop_dogfood_creates_directive_and_accepts_hardened_result(tmp_path: Path) -> None:
    target = tmp_path / "auto-loop-release-target"
    target.mkdir()
    (target / "PROJECT_BRIEF.md").write_text(
        "# Auto Loop Release Target\n\nTemporary release finishing target for Cambrian auto loop.\n",
        encoding="utf-8",
    )
    waiting_report = tmp_path / "waiting-report.md"
    waiting = run_script("--target", str(target), "--out", str(waiting_report))

    assert waiting.returncode == 0
    assert "Result: WAITING_FOR_RESULT" in waiting.stdout
    task_ref_line = next(line for line in waiting.stdout.splitlines() if line.startswith("Task ref: "))
    task_ref = task_ref_line.replace("Task ref: ", "", 1).strip()
    assert task_ref.startswith(".cambrian/auto/tasks/")
    task_path = target / task_ref
    assert task_path.exists()
    task_text = task_path.read_text(encoding="utf-8")
    for phrase in [
        "directive_type: role_specific_auto_task",
        "status: waiting_for_result",
        "result_contract:",
        "required_fields:",
        "evidence_required: true",
        "required_role_output_keys:",
    ]:
        assert phrase in task_text

    result_file = tmp_path / "auto-loop-release-result.yaml"
    result_file.write_text(
        "\n".join(
            [
                "status: success",
                "summary: Auto loop release dogfood directive completed with no source patch.",
                "changed_files: []",
                "tests:",
                '  - command: "python -m pytest -q tests/test_auto_loop_dogfood.py"',
                "    status: passed",
                "blockers: []",
                'next_action: "cambrian auto cycle --max-steps 1 --json"',
                "evidence:",
                "  notes:",
                '    - "Task directive was created and reviewed for release dogfood."',
                "  artifacts:",
                f'    - "{task_ref}"',
                "role_outputs:",
                '  scope: "Verify the auto-loop release handoff without source patching."',
                (
                    '  acceptance_criteria: "The directive exists, result contract is complete, '
                    'ingest succeeds, and the next auto cycle runs."'
                ),
                '  test_plan: "Run the focused auto-loop dogfood pytest coverage and receipt checks."',
                "",
            ]
        ),
        encoding="utf-8",
    )
    pass_report = tmp_path / "pass-report.md"
    passed = run_script(
        "--target",
        str(target),
        "--task-ref",
        task_ref,
        "--result",
        str(result_file),
        "--out",
        str(pass_report),
    )

    assert passed.returncode == 0
    assert "Result: PASS" in passed.stdout
    report_text = pass_report.read_text(encoding="utf-8")
    assert "auto step ingest | PASS" in report_text
    assert "auto cycle after ingest | PASS" in report_text
    assert str(tmp_path) not in report_text


def test_rc_checklist_links_auto_loop_dogfood_gate() -> None:
    checklist = (ROOT / "docs" / "release" / "RC_CHECKLIST.md").read_text(encoding="utf-8")

    for phrase in [
        "Auto Loop Dogfood Gate",
        "AUTO_LOOP_DOGFOOD_REPORT.md",
        "auto step ingest",
    ]:
        assert phrase in checklist
