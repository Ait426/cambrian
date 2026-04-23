"""Cambrian 프로젝트 usage summary 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer
from engine.project_summary import (
    ProjectUsageSummaryBuilder,
    ProjectUsageSummaryStore,
    default_usage_summary_path,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = ['.']\naddopts = '-q'\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")


def _make_initialized_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _prepare_python_project(project_root)
    ProjectInitializer().init(project_root)
    return project_root


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


def test_empty_project_summary_has_zero_counts_and_init_next(tmp_path: Path) -> None:
    summary = ProjectUsageSummaryBuilder().build(tmp_path)

    assert summary.project_name == tmp_path.name
    assert summary.counts["sessions"] == 0
    assert summary.counts["diagnoses"] == 0
    assert summary.counts["patch_proposals"] == 0
    assert summary.counts["adoptions"] == 0
    assert summary.next_actions == ["cambrian init --wizard"]
    assert summary.safety["automatic_adoption_enabled"] is False


def test_summary_counts_core_artifacts_and_validations(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    cambrian_dir = project_root / ".cambrian"

    _write_yaml(
        cambrian_dir / "requests" / "request_001.yaml",
        {"request_id": "req-001", "user_request": "로그인 에러 수정해"},
    )
    _write_yaml(
        cambrian_dir / "context" / "context_001.yaml",
        {"request_id": "req-001", "suggested_sources": ["src/auth.py"]},
    )
    _write_yaml(
        cambrian_dir / "clarifications" / "clarification_001.yaml",
        {"status": "open", "user_request": "로그인 에러 수정해"},
    )
    _write_json(
        cambrian_dir / "brain" / "runs" / "brain-001" / "report.json",
        {"run_id": "brain-001", "diagnostics": {"enabled": True}},
    )
    _write_yaml(
        cambrian_dir / "patch_intents" / "patch_intent_001_auth.yaml",
        {"intent_id": "intent-001", "status": "draft", "target_path": "src/auth.py"},
    )
    _write_yaml(
        cambrian_dir / "patches" / "patch_proposal_001_auth.yaml",
        {
            "proposal_id": "patch-001",
            "proposal_status": "validated",
            "target_path": "src/auth.py",
            "validation": {"attempted": True, "status": "passed"},
        },
    )
    _write_yaml(
        cambrian_dir / "patches" / "patch_proposal_002_auth.yaml",
        {
            "proposal_id": "patch-002",
            "proposal_status": "failed",
            "target_path": "src/auth.py",
            "validation": {"attempted": True, "status": "failed"},
        },
    )
    _write_json(
        cambrian_dir / "feedback" / "feedback_001.json",
        {"keep_patterns": ["Keep minimal auth patch"]},
    )

    summary = ProjectUsageSummaryBuilder().build(project_root)

    assert summary.counts["requests"] == 1
    assert summary.counts["context_scans"] == 1
    assert summary.counts["clarifications"] == 1
    assert summary.counts["diagnoses"] == 1
    assert summary.counts["patch_intents"] == 1
    assert summary.counts["patch_proposals"] == 2
    assert summary.counts["patch_validations_passed"] == 1
    assert summary.counts["patch_validations_failed"] == 1
    assert summary.counts["feedback_records"] == 1


def test_summary_counts_adoptions_and_latest_pointer(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    cambrian_dir = project_root / ".cambrian"

    _write_json(
        cambrian_dir / "adoptions" / "adoption_001_patch-001.json",
        {
            "adoption_id": "adoption-001",
            "adoption_status": "adopted",
            "target_path": "src/auth.py",
            "post_apply_tests": {"passed": 1, "failed": 0},
        },
    )
    _write_json(
        cambrian_dir / "adoptions" / "_latest.json",
        {
            "latest_adoption_id": "adoption-001",
            "latest_adoption_path": ".cambrian/adoptions/adoption_001_patch-001.json",
            "target_path": "src/auth.py",
        },
    )

    summary = ProjectUsageSummaryBuilder().build(project_root)

    assert summary.counts["adoptions"] == 1
    assert summary.safety["explicit_adoptions"] == 1
    assert summary.safety["latest_pointer_exists"] is True
    assert summary.latest["latest_adoption"]["target_path"] == "src/auth.py"


def test_summary_memory_fields_and_top_lessons(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    memory_dir = project_root / ".cambrian" / "memory"

    _write_yaml(
        memory_dir / "lessons.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-23T00:00:00Z",
            "project_name": "project",
            "lessons": [
                {
                    "lesson_id": "lesson-auth-test",
                    "kind": "test_practice",
                    "text": "Run tests/test_auth.py before login-related patches.",
                    "confidence": 0.9,
                    "source_refs": [".cambrian/adoptions/adoption_001.json"],
                    "evidence_count": 2,
                    "tags": ["auth", "tests"],
                    "created_at": "2026-04-23T00:00:00Z",
                    "updated_at": "2026-04-23T00:00:00Z",
                    "status": "active",
                },
                {
                    "lesson_id": "lesson-broad-refactor",
                    "kind": "avoid_pattern",
                    "text": "Avoid broad auth refactors unless integration tests are selected.",
                    "confidence": 0.7,
                    "source_refs": [".cambrian/feedback/feedback_001.json"],
                    "evidence_count": 1,
                    "tags": ["auth", "refactor"],
                    "created_at": "2026-04-23T00:00:00Z",
                    "updated_at": "2026-04-23T00:00:00Z",
                    "status": "active",
                },
            ],
            "warnings": [],
            "errors": [],
        },
    )
    _write_yaml(
        memory_dir / "overrides.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-04-23T00:10:00Z",
            "overrides": {
                "lesson-auth-test": {
                    "lesson_id": "lesson-auth-test",
                    "pinned": True,
                    "suppressed": False,
                    "note": "아직 중요한 규칙",
                    "updated_at": "2026-04-23T00:10:00Z",
                    "updated_by": "user",
                },
                "lesson-broad-refactor": {
                    "lesson_id": "lesson-broad-refactor",
                    "pinned": False,
                    "suppressed": True,
                    "updated_at": "2026-04-23T00:11:00Z",
                    "updated_by": "user",
                },
            },
        },
    )
    _write_yaml(
        memory_dir / "hygiene.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-23T00:20:00Z",
            "lessons_path": ".cambrian/memory/lessons.yaml",
            "overrides_path": ".cambrian/memory/overrides.yaml",
            "summary": {
                "total": 2,
                "fresh": 1,
                "watch": 1,
                "stale": 0,
                "conflicting": 0,
                "orphaned": 0,
                "suppressed": 1,
            },
            "items": [
                {
                    "lesson_id": "lesson-auth-test",
                    "text": "Run tests/test_auth.py before login-related patches.",
                    "kind": "test_practice",
                    "status": "fresh",
                    "severity": "info",
                    "reasons": [],
                    "suggested_actions": [],
                    "pinned": True,
                    "suppressed": False,
                    "confidence": 0.9,
                    "evidence_count": 2,
                    "source_refs": [".cambrian/adoptions/adoption_001.json"],
                    "missing_source_refs": [],
                    "referenced_paths": ["tests/test_auth.py"],
                    "missing_referenced_paths": [],
                    "conflict_refs": [],
                    "warnings": [],
                },
                {
                    "lesson_id": "lesson-broad-refactor",
                    "text": "Avoid broad auth refactors unless integration tests are selected.",
                    "kind": "avoid_pattern",
                    "status": "suppressed",
                    "severity": "info",
                    "reasons": [],
                    "suggested_actions": [],
                    "pinned": False,
                    "suppressed": True,
                    "confidence": 0.7,
                    "evidence_count": 1,
                    "source_refs": [".cambrian/feedback/feedback_001.json"],
                    "missing_source_refs": [],
                    "referenced_paths": [],
                    "missing_referenced_paths": [],
                    "conflict_refs": [],
                    "warnings": [],
                },
            ],
            "warnings": [],
            "errors": [],
        },
    )

    summary = ProjectUsageSummaryBuilder().build(project_root)

    assert summary.memory["lessons_count"] == 2
    assert summary.memory["pinned_count"] == 1
    assert summary.memory["suppressed_count"] == 1
    assert summary.memory["hygiene"]["watch"] == 1
    assert summary.memory["top_lessons"][0] == "Run tests/test_auth.py before login-related patches."
    assert summary.counts["pinned_lessons"] == 1
    assert summary.counts["suppressed_lessons"] == 1


def test_summary_active_work_and_recent_journey_include_next_command(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    cambrian_dir = project_root / ".cambrian"

    _write_yaml(
        cambrian_dir / "sessions" / "do_session_do-001.yaml",
        {
            "session_id": "do-001",
            "user_request": "로그인 에러 수정해",
            "status": "patch_proposal_validated",
            "current_stage": "patch_proposal_validated",
            "next_actions": [
                'cambrian do --continue --session do-001 --apply --reason "normalize username before login"',
            ],
            "next_commands": [
                {
                    "label": "계속 진행",
                    "command": 'cambrian do --continue --session do-001 --apply --reason "normalize username before login"',
                    "reason": "검증된 proposal이 준비되었습니다.",
                    "stage": "patch_proposal_validated",
                    "primary": True,
                    "requires_user_input": True,
                }
            ],
            "summary": {"patch_validation_status": "passed"},
            "errors": [],
        },
    )
    _write_json(
        cambrian_dir / "adoptions" / "adoption_001_patch-001.json",
        {
            "adoption_id": "adoption-001",
            "adoption_status": "adopted",
            "target_path": "src/auth.py",
            "post_apply_tests": {"passed": 1, "failed": 0},
        },
    )

    summary = ProjectUsageSummaryBuilder().build(project_root)

    assert summary.active_work
    assert summary.active_work[0]["session_id"] == "do-001"
    assert "--apply --reason" in summary.active_work[0]["next_command"]
    assert any(item["kind"] == "adoption" for item in summary.recent_journey)


def test_cli_summary_smoke_json_and_save(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    cambrian_dir = project_root / ".cambrian"
    source_path = project_root / "src.py"
    source_path.write_text("print('safe')\n", encoding="utf-8")

    _write_yaml(
        cambrian_dir / "sessions" / "do_session_do-001.yaml",
        {
            "session_id": "do-001",
            "user_request": "README 정리",
            "status": "clarification_open",
            "current_stage": "clarification_open",
            "next_actions": ["cambrian do --continue --session do-001 --use-suggestion 1 --execute"],
            "next_commands": [
                {
                    "label": "계속 진행",
                    "command": "cambrian do --continue --session do-001 --use-suggestion 1 --execute",
                    "reason": "context 선택이 열려 있습니다.",
                    "stage": "clarification_open",
                    "primary": True,
                    "requires_user_input": False,
                }
            ],
            "summary": {},
            "errors": [],
        },
    )

    session_path = cambrian_dir / "sessions" / "do_session_do-001.yaml"
    before_source = _sha256(source_path)
    before_session = _sha256(session_path)

    human_proc = _run_cli(["summary"], project_root)
    assert human_proc.returncode == 0, human_proc.stderr
    assert "Cambrian Project Summary" in human_proc.stdout
    assert "Work so far:" in human_proc.stdout
    assert "Safety:" in human_proc.stdout
    assert "Project memory:" in human_proc.stdout

    json_proc = _run_cli(["summary", "--json"], project_root)
    assert json_proc.returncode == 0, json_proc.stderr
    payload = json.loads(json_proc.stdout)
    assert "counts" in payload
    assert "memory" in payload
    assert "safety" in payload

    save_proc = _run_cli(["summary", "--save"], project_root)
    assert save_proc.returncode == 0, save_proc.stderr
    summary_path = default_usage_summary_path(project_root)
    assert summary_path.exists()
    saved = ProjectUsageSummaryStore().load(summary_path)
    assert saved.counts["sessions"] == 1

    status_proc = _run_cli(["status"], project_root)
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Summary:" in status_proc.stdout
    assert "Run: cambrian summary" in status_proc.stdout

    assert _sha256(source_path) == before_source
    assert _sha256(session_path) == before_session

