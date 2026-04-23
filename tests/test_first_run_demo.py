"""Cambrian 첫 실행 demo 테스트."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from engine.demo_project import DemoProjectCreator
from engine.project_continue import ProjectDoContinuationRunner
from engine.project_do import ProjectDoRunner
from engine.project_mode import ProjectStatusReader


REQUEST_TEXT = "로그인 정규화 버그 수정해"


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _run_pytest(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _create_demo(tmp_path: Path) -> Path:
    demo_root = tmp_path / "cambrian-login-demo"
    result = DemoProjectCreator().create("login-bug", demo_root)
    assert result.status == "created"
    return demo_root


def test_demo_create_contains_expected_files_and_initial_failure(tmp_path: Path) -> None:
    demo_root = _create_demo(tmp_path)

    assert (demo_root / "src" / "auth.py").exists()
    assert (demo_root / "tests" / "test_auth.py").exists()
    assert (demo_root / "demo_answers.yaml").exists()
    assert (demo_root / "README_DEMO.md").exists()

    pytest_result = _run_pytest(demo_root)
    assert pytest_result.returncode != 0
    assert "failed" in pytest_result.stdout.lower()


def test_generated_demo_readme_uses_do_centered_primary_flow(tmp_path: Path) -> None:
    demo_root = _create_demo(tmp_path)
    content = (demo_root / "README_DEMO.md").read_text(encoding="utf-8")

    assert "cambrian do \"로그인 정규화 버그 수정해\"" in content
    assert "cambrian do --continue --use-suggestion 1 --execute" in content
    assert "cambrian do --continue --old-choice old-1 --new-text \"return username.strip().lower()\" --validate" in content
    assert "cambrian do --continue --apply --reason \"normalize username before login\"" in content
    assert "cambrian status" in content
    assert "## Advanced / manual path" in content
    start_here, advanced = content.split("## Advanced / manual path", maxsplit=1)
    assert "cambrian patch intent" not in start_here
    assert "cambrian patch intent-fill" not in start_here
    assert "cambrian patch apply" not in start_here
    assert "cambrian patch intent" in advanced
    assert "cambrian patch intent-fill" in advanced
    assert "cambrian patch apply" in advanced


def test_demo_create_blocked_without_force(tmp_path: Path) -> None:
    demo_root = tmp_path / "demo"
    demo_root.mkdir(parents=True, exist_ok=True)
    (demo_root / "keep.txt").write_text("existing", encoding="utf-8")

    result = DemoProjectCreator().create("login-bug", demo_root, force=False)

    assert result.status == "blocked"
    assert (demo_root / "keep.txt").read_text(encoding="utf-8") == "existing"


def test_demo_create_force_overwrites_files(tmp_path: Path) -> None:
    demo_root = tmp_path / "demo"
    demo_root.mkdir(parents=True, exist_ok=True)
    (demo_root / "src").mkdir(parents=True, exist_ok=True)
    (demo_root / "src" / "auth.py").write_text("broken", encoding="utf-8")

    result = DemoProjectCreator().create("login-bug", demo_root, force=True)

    assert result.status == "overwritten"
    assert "return username" in (demo_root / "src" / "auth.py").read_text(encoding="utf-8")


def test_demo_init_creates_cambrian_configs(tmp_path: Path) -> None:
    demo_root = _create_demo(tmp_path)

    init_result = _run_cli(
        ["init", "--wizard", "--answers-file", "demo_answers.yaml"],
        demo_root,
    )

    assert init_result.returncode == 0, init_result.stderr
    assert (demo_root / ".cambrian" / "project.yaml").exists()
    assert (demo_root / ".cambrian" / "rules.yaml").exists()
    assert (demo_root / ".cambrian" / "skills.yaml").exists()
    assert (demo_root / ".cambrian" / "profile.yaml").exists()


def test_demo_journey_smoke_and_source_mutation_timing(tmp_path: Path) -> None:
    demo_root = _create_demo(tmp_path)
    init_result = _run_cli(
        ["init", "--wizard", "--answers-file", "demo_answers.yaml"],
        demo_root,
    )
    assert init_result.returncode == 0, init_result.stderr

    source_path = demo_root / "src" / "auth.py"
    before_apply = source_path.read_text(encoding="utf-8")
    assert "return username" in before_apply

    first = ProjectDoRunner().run(REQUEST_TEXT, demo_root, {})
    assert first.status == "clarification_open"
    assert first.artifacts["context_scan_path"]

    diagnosed = ProjectDoRunner().run(
        REQUEST_TEXT,
        demo_root,
        {
            "use_suggestion": 1,
            "execute": True,
        },
    )
    assert diagnosed.status == "diagnosed"
    assert diagnosed.artifacts["report_path"]
    assert source_path.read_text(encoding="utf-8") == before_apply

    draft = ProjectDoContinuationRunner().run(demo_root, {"session": diagnosed.session_id})
    assert draft.current_stage == "patch_intent_draft"
    assert draft.artifacts["patch_intent_path"]

    validated = ProjectDoContinuationRunner().run(
        demo_root,
        {
            "session": draft.session_id,
            "old_choice": "old-1",
            "new_text": "return username.strip().lower()",
            "propose": True,
            "validate": True,
        },
    )
    assert validated.current_stage == "patch_proposal_validated"
    assert validated.artifacts["patch_proposal_path"]
    assert source_path.read_text(encoding="utf-8") == before_apply

    adopted = ProjectDoContinuationRunner().run(
        demo_root,
        {
            "session": validated.session_id,
            "apply": True,
            "reason": "normalize username before login",
        },
    )
    assert adopted.current_stage == "adopted"
    assert adopted.artifacts["adoption_record_path"]
    assert "return username.strip().lower()" in source_path.read_text(encoding="utf-8")

    pytest_result = _run_pytest(demo_root)
    assert pytest_result.returncode == 0, pytest_result.stdout + pytest_result.stderr

    status = ProjectStatusReader().read(demo_root)
    status_cli = _run_cli(["status"], demo_root)
    assert status.initialized is True
    assert status.latest_patch_adoption
    assert status_cli.returncode == 0, status_cli.stderr
    assert "Latest adoption:" in status_cli.stdout or "Latest completed work:" in status_cli.stdout


def test_first_run_demo_doc_exists_and_mentions_core_commands() -> None:
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "FIRST_RUN_DEMO.md"
    content = doc_path.read_text(encoding="utf-8")

    assert doc_path.exists()
    assert "cambrian demo create login-bug" in content
    assert "cambrian init --wizard --answers-file demo_answers.yaml" in content
    assert "cambrian do" in content
    assert "cambrian patch apply" in content
    assert "cambrian status" in content


def test_demo_cli_help_includes_create() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    proc = _run_cli(["demo", "--help"], repo_root)

    assert proc.returncode == 0, proc.stderr
    assert "create" in proc.stdout
    assert "demo" in proc.stdout.lower()
