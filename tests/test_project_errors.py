"""Cambrian recovery hint와 last_error 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from engine.project_doctor import DoctorCheck
from engine.project_errors import (
    RecoveryHintBuilder,
    hint_for_doctor_report,
    save_last_error,
)
from engine.project_mode import ProjectInitializer, ProjectStatusReader, render_status_summary
from engine.project_patch import render_patch_proposal_summary
from engine.project_patch_apply import render_patch_apply_summary
from engine.project_patch_intent import render_patch_intent_summary


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _prepare_login_fixture(project_root: Path) -> None:
    _prepare_python_project(project_root)
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth.py").write_text(
        "def normalize_username(username: str) -> str:\n"
        "    return username\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth import normalize_username\n\n"
        "def test_normalize_username_lowercases_email() -> None:\n"
        "    assert normalize_username(\"USER@EXAMPLE.COM\") == \"user@example.com\"\n",
        encoding="utf-8",
    )


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_initialized_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _prepare_login_fixture(project_root)
    ProjectInitializer().init(project_root)
    return project_root


def test_do_before_init_json_recovery(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)

    proc = _run_cli(["do", "로그인 오류 수정", "--json"], cwd=tmp_path)
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["error_id"] == "project_not_initialized"
    assert "Problem" not in proc.stdout
    assert payload["problem"]
    assert payload["why"]
    assert payload["try_next"][0]["command"] == "cambrian init --wizard"


def test_do_continue_without_active_session_writes_last_error(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)

    proc = _run_cli(["do", "--continue", "--json"], cwd=project_root)
    payload = json.loads(proc.stdout)
    last_error = project_root / ".cambrian" / "errors" / "last_error.yaml"

    assert proc.returncode == 0, proc.stderr
    assert payload["error_id"] == "no_active_session"
    assert payload["try_next"][0]["command"].startswith("cambrian do ")
    assert last_error.exists()


def test_context_no_match_recovery_text() -> None:
    rendered = __import__("engine.project_context", fromlist=["render_context_scan_summary"]).render_context_scan_summary(
        {
            "request_id": "req-001",
            "user_request": "완전히 다른 요청",
            "status": "no_match",
            "suggested_sources": [],
            "suggested_tests": [],
            "next_actions": ['cambrian do "완전히 다른 요청 in src/auth.py"'],
        }
    )

    assert "Problem:" in rendered
    assert "Why:" in rendered
    assert "Try:" in rendered


def test_patch_intent_conflicting_args_recovery_text() -> None:
    rendered = render_patch_intent_summary(
        {
            "status": "blocked",
            "target_path": "src/auth.py",
            "errors": ["old_choice, old_text, old_text_file 중 하나만 선택하세요"],
            "warnings": [],
            "next_actions": ['cambrian do --continue --old-choice old-1 --new-text "..." --validate'],
        }
    )

    assert "Problem:" in rendered
    assert "Why:" in rendered
    assert "Try:" in rendered
    assert "cambrian do --continue --old-choice old-1 --new-text \"...\" --validate" in rendered


def test_patch_proposal_missing_old_text_recovery_text() -> None:
    rendered = render_patch_proposal_summary(
        {
            "proposal_status": "blocked",
            "target_path": "src/auth.py",
            "safety_warnings": ["old_text was not found in src/auth.py"],
            "next_actions": ["cambrian do --continue --execute"],
        }
    )

    assert "Problem:" in rendered
    assert "old text" in rendered.lower()
    assert "cambrian do --continue --execute" in rendered


def test_patch_apply_unvalidated_json_recovery_and_no_mutation(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    target = project_root / "src" / "auth.py"
    before_hash = _sha256(target)
    proposal_path = project_root / ".cambrian" / "patches" / "patch_proposal_001_auth.yaml"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        "\n".join(
            [
                "schema_version: '1.0.0'",
                "proposal_id: 'patch-001'",
                "target_path: src/auth.py",
                "proposal_status: ready",
                "related_tests:",
                "  - tests/test_auth.py",
                "action:",
                "  type: patch_file",
                "  target_path: src/auth.py",
                "  old_text: return username",
                "  new_text: return username.strip().lower()",
                "validation:",
                "  attempted: false",
                "  status: not_requested",
            ]
        ),
        encoding="utf-8",
    )

    proc = _run_cli(
        ["patch", "apply", ".cambrian/patches/patch_proposal_001_auth.yaml", "--reason", "로그인 정규화"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    assert "[PATCH APPLY] blocked" in proc.stdout
    assert "Problem:" in proc.stdout
    assert "Why:" in proc.stdout
    assert _sha256(target) == before_hash


def test_doctor_dependency_hint_builder() -> None:
    hint = hint_for_doctor_report(
        {
            "checks": [
                DoctorCheck(
                    name="pytest",
                    status="warn",
                    summary="pytest is not installed",
                    details=["demo flow prefers pytest"],
                ).to_dict()
            ],
            "next_actions": ["pip install pytest", "cambrian doctor"],
        }
    )

    assert hint is not None
    assert hint.error_id == "doctor_dependency_missing"
    assert hint.try_next[0].command == "pip install pytest"


def test_alpha_check_json_has_recovery(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)

    proc = _run_cli(["alpha", "check", "--json"], cwd=project_root)
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["status"] in {"pass", "warn", "fail"}
    assert "checks" in payload
    if payload["status"] in {"warn", "fail"}:
        assert payload["error_id"] == "alpha_not_ready"
        assert payload["try_next"]


def test_status_shows_unresolved_issue_from_last_error(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    hint = RecoveryHintBuilder().missing_source_choice(
        "do-test",
        ['cambrian do --continue --session do-test --use-suggestion 1 --execute'],
    )

    save_last_error(project_root, hint)
    status = ProjectStatusReader().read(project_root)
    rendered = render_status_summary(status)

    assert "Unresolved issue:" in rendered
    assert "A source file has not been selected yet." in rendered
    assert "cambrian do --continue --session do-test --use-suggestion 1 --execute" in rendered
