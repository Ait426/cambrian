"""Cambrian 프로젝트 notes 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from engine.project_alpha_audit import ProjectAlphaAudit
from engine.project_mode import ProjectInitializer, ProjectStatusReader, render_status_summary
from engine.project_notes import ProjectNotesStore, default_notes_dir
from engine.project_summary import ProjectUsageSummaryBuilder


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = ['.']\naddopts = '-q'\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth.py").write_text(
        "def normalize_username(username: str) -> str:\n"
        "    return username\n",
        encoding="utf-8",
    )


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


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_session(
    project_root: Path,
    *,
    session_id: str,
    stage: str,
    user_request: str = "로그인 정규화 버그 수정해",
    clarification_path: str | None = None,
    report_path: str | None = None,
    patch_intent_path: str | None = None,
    patch_proposal_path: str | None = None,
    adoption_record_path: str | None = None,
) -> Path:
    payload = {
        "schema_version": "1.0.0",
        "session_id": session_id,
        "created_at": "2026-04-23T00:00:00Z",
        "updated_at": "2026-04-23T00:00:00Z",
        "user_request": user_request,
        "project_initialized": True,
        "status": stage,
        "current_stage": stage,
        "artifacts": {
            "session_path": f".cambrian/sessions/do_session_{session_id}.yaml",
            "clarification_path": clarification_path,
            "report_path": report_path,
            "patch_intent_path": patch_intent_path,
            "patch_proposal_path": patch_proposal_path,
            "adoption_record_path": adoption_record_path,
        },
        "summary": {
            "selected_sources": ["src/auth.py"],
            "selected_tests": ["tests/test_auth.py"],
        },
        "next_actions": ["cambrian status"],
        "next_commands": [
            {
                "label": "현재 작업 계속하기",
                "command": f"cambrian do --continue --session {session_id} --use-suggestion 1 --execute",
                "reason": "다음 단계로 이어갑니다.",
                "stage": stage,
                "primary": True,
                "requires_user_input": False,
            }
        ],
        "warnings": [],
        "errors": [],
    }
    path = project_root / ".cambrian" / "sessions" / f"do_session_{session_id}.yaml"
    _write_yaml(path, payload)
    return path


def _latest_note(project_root: Path) -> dict:
    notes = ProjectNotesStore().list(default_notes_dir(project_root))
    assert notes
    return notes[0].to_dict()


def test_add_note_standalone(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)

    proc = _run_cli(
        ["notes", "add", "clarify step was confusing", "--kind", "confusion", "--severity", "medium", "--json"],
        cwd=project_root,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["status"] == "open"
    assert payload["kind"] == "confusion"
    assert payload["session_id"] is None
    assert (project_root / payload["note_path"]).exists()


def test_notes_resolve_rejects_non_note_artifact_paths(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    project_config = project_root / ".cambrian" / "project.yaml"
    before_hash = _sha256(project_config)

    with pytest.raises(FileNotFoundError):
        ProjectNotesStore().resolve_path(project_root, str(project_config))

    assert _sha256(project_config) == before_hash


def test_add_note_with_active_session_auto_link(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    clarification_rel = ".cambrian/clarifications/clarification_req-001.yaml"
    _write_yaml(project_root / clarification_rel, {"status": "open"})
    _write_session(
        project_root,
        session_id="do-test",
        stage="clarification_open",
        clarification_path=clarification_rel,
    )

    proc = _run_cli(
        ["notes", "add", "source choice was confusing", "--kind", "confusion", "--json"],
        cwd=project_root,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["session_id"] == "do-test"
    assert payload["stage"] == "clarification_open"
    assert clarification_rel in payload["artifact_refs"]
    assert payload["context"]["next_command"].startswith("cambrian do --continue")


def test_terminal_session_does_not_auto_link_standalone_note(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    _write_session(
        project_root,
        session_id="do-terminal",
        stage="adopted",
        adoption_record_path=".cambrian/adoptions/adoption_001.json",
    )

    proc = _run_cli(
        ["notes", "add", "finished work should not auto-link", "--kind", "note", "--json"],
        cwd=project_root,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["session_id"] is None
    assert payload["stage"] is None
    assert payload["session_ref"] is None


def test_add_note_with_explicit_session_and_artifact_refs(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    _write_session(project_root, session_id="do-active", stage="clarification_open")
    explicit_path = _write_session(project_root, session_id="do-explicit", stage="diagnosed")

    proc = _run_cli(
        [
            "notes",
            "add",
            "patch intent 후보 추천이 좋았음",
            "--kind",
            "success",
            "--session",
            "do-explicit",
            "--artifact",
            ".cambrian/brain/runs/run-001/report.json",
            "--artifact",
            ".cambrian/patch_intents/patch_intent_001.yaml",
            "--json",
        ],
        cwd=project_root,
    )
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["session_id"] == "do-explicit"
    assert payload["session_ref"].endswith(Path(explicit_path).name)
    assert ".cambrian/brain/runs/run-001/report.json" in payload["artifact_refs"]
    assert ".cambrian/patch_intents/patch_intent_001.yaml" in payload["artifact_refs"]


def test_notes_list_show_and_resolve(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)

    add_proc = _run_cli(
        ["notes", "add", "doctor 메시지가 모호했음", "--kind", "friction", "--severity", "high", "--json"],
        cwd=project_root,
    )
    note_payload = json.loads(add_proc.stdout)
    note_id = note_payload["note_id"]

    list_proc = _run_cli(["notes", "list", "--json"], cwd=project_root)
    list_payload = json.loads(list_proc.stdout)
    assert list_proc.returncode == 0, list_proc.stderr
    assert list_payload["count"] == 1
    assert list_payload["notes"][0]["note_id"] == note_id

    show_proc = _run_cli(["notes", "show", note_id, "--json"], cwd=project_root)
    show_payload = json.loads(show_proc.stdout)
    assert show_payload["note_id"] == note_id
    assert show_payload["kind"] == "friction"

    resolve_proc = _run_cli(
        ["notes", "resolve", note_id, "--resolution", "doctor 문구를 더 명확하게 다듬음", "--json"],
        cwd=project_root,
    )
    resolve_payload = json.loads(resolve_proc.stdout)
    assert resolve_payload["status"] == "resolved"
    assert resolve_payload["resolution"] == "doctor 문구를 더 명확하게 다듬음"
    assert resolve_payload["updated_at"]


def test_missing_note_id_has_helpful_error(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)

    proc = _run_cli(["notes", "show", "note-does-not-exist"], cwd=project_root)

    assert proc.returncode == 1
    assert "Note not found" in proc.stderr
    assert "cambrian notes list" in proc.stderr


def test_status_and_summary_include_note_counts(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    _write_session(project_root, session_id="do-test", stage="patch_proposal_validated")

    _run_cli(
        ["notes", "add", "status에 다음 명령이 잘 보여서 좋았음", "--kind", "success", "--severity", "low"],
        cwd=project_root,
    )
    add_proc = _run_cli(
        ["notes", "add", "clarify가 아직 좀 헷갈림", "--kind", "confusion", "--severity", "high", "--json"],
        cwd=project_root,
    )
    note_id = json.loads(add_proc.stdout)["note_id"]
    _run_cli(
        ["notes", "resolve", note_id, "--resolution", "clarify recovery hint를 추가로 다듬음"],
        cwd=project_root,
    )

    status = ProjectStatusReader().read(project_root)
    rendered = render_status_summary(status)
    summary = ProjectUsageSummaryBuilder().build(project_root)

    assert "User notes:" in rendered
    assert summary.counts["notes_open"] == 1
    assert summary.counts["notes_resolved"] == 1
    assert summary.counts["notes_success"] == 1
    assert summary.counts["notes_confusion"] == 1


def test_alpha_audit_warns_on_open_high_note(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    _run_cli(
        ["notes", "add", "doctor 메시지가 여전히 모호함", "--kind", "bug", "--severity", "high"],
        cwd=project_root,
    )

    check = ProjectAlphaAudit()._check_user_notes(project_root)

    assert check.status == "warn"
    assert check.check_id == "user_notes_feedback"


def test_notes_commands_do_not_mutate_source_files(tmp_path: Path) -> None:
    project_root = _make_initialized_project(tmp_path)
    source_path = project_root / "src" / "auth.py"
    before_hash = _sha256(source_path)

    add_proc = _run_cli(["notes", "add", "이 흐름은 좋았음", "--kind", "success", "--json"], cwd=project_root)
    note_id = json.loads(add_proc.stdout)["note_id"]
    _run_cli(["notes", "list"], cwd=project_root)
    _run_cli(["notes", "show", note_id], cwd=project_root)
    _run_cli(["notes", "resolve", note_id, "--resolution", "확인 완료"], cwd=project_root)

    assert _sha256(source_path) == before_hash
    assert default_notes_dir(project_root).exists()
