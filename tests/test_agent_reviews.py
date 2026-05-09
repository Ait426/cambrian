from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_dispatch import DispatchBoardBuilder
from engine.project_mode import ProjectInitializer


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "auth.py").write_text(
        "def normalize_username(username: str) -> str:\n    return username\n",
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


def _init_project(project_root: Path) -> None:
    _prepare_python_project(project_root)
    result = ProjectInitializer().init(project_root)
    assert result.status == "initialized"


def _fit_harness(project_root: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(["harness", "fit"], cwd=project_root)


def _create_active_session(project_root: Path, *, agent_id: str = "bug-fix-agent") -> str:
    session_id = "do-20260425-010000-a1b2"
    _write_yaml(
        project_root / ".cambrian" / "sessions" / f"do_session_{session_id}.yaml",
        {
            "schema_version": "1.0.0",
            "session_id": session_id,
            "created_at": "2026-04-25T01:00:00+00:00",
            "updated_at": "2026-04-25T01:01:00+00:00",
            "user_request": "로그인 에러 수정해",
            "project_initialized": True,
            "intent": {"intent_type": "bug_fix"},
            "selected_skills": ["project_mode_bugfix"],
            "status": "diagnosed",
            "current_stage": "diagnosed",
            "artifacts": {
                "session_path": f".cambrian/sessions/do_session_{session_id}.yaml",
                "request_path": ".cambrian/requests/request_demo.yaml",
                "report_path": ".cambrian/brain/runs/run-login/report.json",
                "patch_proposal_path": None,
                "patch_intent_path": None,
                "adoption_record_path": None,
            },
            "summary": {
                "understood_as": "bug fix",
                "selected_sources": ["src/auth.py"],
                "selected_tests": [],
            },
            "next_actions": [
                f"cambrian do --continue --session {session_id} --use-suggestion 1 --execute"
            ],
            "next_commands": [
                {
                    "label": "Continue with Cambrian",
                    "command": f"cambrian do --continue --session {session_id} --use-suggestion 1 --execute",
                    "primary": True,
                }
            ],
            "harness_context": {
                "harness_ref": ".cambrian/harness/profile.yaml",
                "active_agents": [agent_id, "regression-test-agent", "review-agent"],
            },
            "agent_context": {
                "enabled": True,
                "harness_ref": ".cambrian/harness/profile.yaml",
                "registry_ref": ".cambrian/agents/registry.yaml",
                "memory_ref": ".cambrian/memory/lessons.yaml",
                "lead_agent_id": agent_id,
                "supporting_agent_ids": ["regression-test-agent", "review-agent"],
                "routes": [],
                "selected_via": "auto",
                "warnings": [],
                "next_actions": [],
            },
            "continuations": [],
            "warnings": [],
            "errors": [],
            "artifact_path": f".cambrian/sessions/do_session_{session_id}.yaml",
        },
    )
    return session_id


def test_agent_review_add_standalone(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr

    proc = _run_cli(
        [
            "agent",
            "review",
            "bug-fix-agent",
            "Handled auth bug well.",
            "--rating",
            "good",
            "--kind",
            "performance",
        ],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    review_files = list((tmp_path / ".cambrian" / "agents" / "reviews").glob("review_*.yaml"))
    assert len(review_files) == 1
    payload = _read_yaml(review_files[0])
    assert payload["agent_id"] == "bug-fix-agent"
    assert payload["session_id"] is None


def test_agent_review_with_active_session_auto_links(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    session_id = _create_active_session(tmp_path)

    proc = _run_cli(
        [
            "agent",
            "review",
            "bug-fix-agent",
            "Handled auth bug well, but almost drifted into a refactor.",
            "--rating",
            "good",
            "--kind",
            "caution",
        ],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    review_file = next((tmp_path / ".cambrian" / "agents" / "reviews").glob("review_*.yaml"))
    payload = _read_yaml(review_file)
    assert payload["session_id"] == session_id
    assert payload["stage"] == "diagnosed"
    assert payload["user_request"] == "로그인 에러 수정해"
    assert payload["context"]["lead_agent"] == "bug-fix-agent"


def test_agent_review_explicit_session_and_artifact_override(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    session_id = _create_active_session(tmp_path)

    proc = _run_cli(
        [
            "agent",
            "review",
            "bug-fix-agent",
            "Explicit session link review.",
            "--session",
            session_id,
            "--artifact",
            str(tmp_path / "src" / "auth.py"),
            "--tag",
            "auth",
        ],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    review_file = next((tmp_path / ".cambrian" / "agents" / "reviews").glob("review_*.yaml"))
    payload = _read_yaml(review_file)
    assert payload["session_id"] == session_id
    assert "src/auth.py" in payload["artifact_refs"]
    assert "auth" in payload["tags"]


def test_missing_agent_review_is_blocked(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr

    proc = _run_cli(["agent", "review", "missing-agent", "bad"], cwd=tmp_path)

    assert proc.returncode != 0
    assert "Agent not found" in proc.stderr


def test_agent_reviews_show_and_history_include_review_summary(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_active_session(tmp_path)

    review_proc = _run_cli(
        [
            "agent",
            "review",
            "bug-fix-agent",
            "Small patch proposal was clear and safe.",
            "--rating",
            "strong",
            "--kind",
            "praise",
        ],
        cwd=tmp_path,
    )
    assert review_proc.returncode == 0, review_proc.stderr

    reviews_proc = _run_cli(["agent", "reviews", "bug-fix-agent"], cwd=tmp_path)
    show_proc = _run_cli(["agent", "show", "bug-fix-agent"], cwd=tmp_path)
    history_proc = _run_cli(["agent", "history", "bug-fix-agent"], cwd=tmp_path)

    assert reviews_proc.returncode == 0, reviews_proc.stderr
    assert "Agent Reviews" in reviews_proc.stdout
    assert "Small patch proposal was clear and safe." in reviews_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Review summary:" in show_proc.stdout
    assert history_proc.returncode == 0, history_proc.stderr
    assert "Recent reviews:" in history_proc.stdout


def test_dispatch_board_uses_reviews_weakly(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr

    positive_proc = _run_cli(
        ["agent", "review", "bug-fix-agent", "Strong on small bug fixes.", "--rating", "strong", "--kind", "praise"],
        cwd=tmp_path,
    )
    caution_proc = _run_cli(
        ["agent", "review", "docs-update-agent", "Not a fit for current work.", "--rating", "weak", "--kind", "fit"],
        cwd=tmp_path,
    )
    assert positive_proc.returncode == 0, positive_proc.stderr
    assert caution_proc.returncode == 0, caution_proc.stderr

    board = DispatchBoardBuilder().build(tmp_path)
    bug_fix = next(item for item in board.candidates if item.agent_id == "bug-fix-agent")
    docs = next(item for item in board.candidates if item.agent_id == "docs-update-agent")

    assert any("recent project review was positive" in reason for reason in bug_fix.reasons)
    assert any("recent project review suggests caution" in reason for reason in docs.reasons)


def test_status_shows_lead_agent_review_hint(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_active_session(tmp_path)

    review_proc = _run_cli(
        ["agent", "review", "bug-fix-agent", "Good recent review with one caution about refactor drift.", "--rating", "good", "--kind", "caution"],
        cwd=tmp_path,
    )
    assert review_proc.returncode == 0, review_proc.stderr

    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Lead agent note:" in status_proc.stdout
    assert "bug-fix-agent" in status_proc.stdout
