from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer, ProjectRunPreparer


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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
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
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth import normalize_username\n\n\ndef test_normalize_username_keeps_value() -> None:\n    assert normalize_username('Alice') == 'Alice'\n",
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


def _create_agent_history_artifacts(project_root: Path) -> dict:
    run_result = ProjectRunPreparer().prepare(project_root, "로그인 에러 수정해")
    request_path = project_root / run_result.request_path
    request_payload = _read_yaml(request_path)
    harness_context = dict(request_payload.get("harness_context", {}))
    assert harness_context.get("active_agents")

    report_rel = ".cambrian/brain/runs/run-login/report.json"
    _write_json(
        project_root / report_rel,
        {
            "report_id": "run-login",
            "created_at": "2026-04-25T00:02:00+00:00",
            "diagnostics": {
                "related_tests": ["tests/test_auth.py"],
            },
        },
    )

    proposal_rel = ".cambrian/patches/patch_proposal_patch-demo_auth.yaml"
    _write_yaml(
        project_root / proposal_rel,
        {
            "schema_version": "1.0.0",
            "proposal_id": "patch-demo",
            "created_at": "2026-04-25T00:03:00+00:00",
            "user_request": "로그인 에러 수정해",
            "source_diagnosis_ref": report_rel,
            "source_context_ref": None,
            "target_path": "src/auth.py",
            "related_tests": ["tests/test_auth.py"],
            "action": {
                "type": "patch_file",
                "target_path": "src/auth.py",
                "old_text": "return username",
                "new_text": "return username.strip().lower()",
            },
            "proposal_status": "validated",
            "safety_warnings": [],
            "validation": {
                "attempted": True,
                "status": "passed",
                "tests": {
                    "passed": 1,
                    "failed": 0,
                    "tests_executed": ["tests/test_auth.py"],
                },
            },
            "task_spec_path": ".cambrian/tasks/task_patch_patch-demo.yaml",
            "next_actions": [],
        },
    )

    session_id = "do-20260425-000000-a1b2"
    _write_yaml(
        project_root / ".cambrian" / "sessions" / f"do_session_{session_id}.yaml",
        {
            "schema_version": "1.0.0",
            "session_id": session_id,
            "created_at": "2026-04-25T00:01:00+00:00",
            "updated_at": "2026-04-25T00:04:00+00:00",
            "user_request": "로그인 에러 수정해",
            "project_initialized": True,
            "intent": {"intent_type": "bug_fix"},
            "selected_skills": ["project_mode_bugfix"],
            "status": "patch_proposal_validated",
            "current_stage": "patch_proposal_validated",
            "artifacts": {
                "session_path": f".cambrian/sessions/do_session_{session_id}.yaml",
                "request_path": run_result.request_path,
                "report_path": report_rel,
                "patch_proposal_path": proposal_rel,
                "patch_intent_path": None,
                "adoption_record_path": None,
            },
            "summary": {
                "understood_as": "bug fix",
                "selected_sources": ["src/auth.py"],
                "selected_tests": ["tests/test_auth.py"],
            },
            "next_actions": [
                "cambrian do --continue --session do-20260425-000000-a1b2 --apply --reason \"normalize username before login\""
            ],
            "next_commands": [],
            "harness_context": harness_context,
            "continuations": [],
            "warnings": [],
            "errors": [],
            "artifact_path": f".cambrian/sessions/do_session_{session_id}.yaml",
        },
    )

    adoption_rel = ".cambrian/adoptions/adoption_20260425_patch-demo.json"
    _write_json(
        project_root / adoption_rel,
        {
            "schema_version": "1.0.0",
            "adoption_id": "adoption-demo",
            "adoption_type": "patch_proposal",
            "created_at": "2026-04-25T00:05:00+00:00",
            "proposal_id": "patch-demo",
            "source_proposal_path": proposal_rel,
            "target_path": "src/auth.py",
            "human_reason": "normalize username before login",
            "post_apply_tests": {
                "passed": 1,
                "failed": 0,
            },
            "adoption_status": "adopted",
        },
    )

    _write_yaml(
        project_root / ".cambrian" / "notes" / "note_20260425_000600_demo.yaml",
        {
            "schema_version": "1.0.0",
            "note_id": "note-demo",
            "created_at": "2026-04-25T00:06:00+00:00",
            "updated_at": None,
            "status": "open",
            "kind": "success",
            "severity": "low",
            "text": "status 에 next command 가 잘 보여서 좋았음",
            "resolution": None,
            "project_name": project_root.name,
            "session_id": session_id,
            "session_ref": f".cambrian/sessions/do_session_{session_id}.yaml",
            "stage": "patch_proposal_validated",
            "artifact_refs": [proposal_rel],
            "tags": ["ux"],
            "context": {
                "user_request": "로그인 에러 수정해",
                "next_command": "cambrian do --continue --session do-20260425-000000-a1b2 --apply --reason \"normalize username before login\"",
                "command_name": "cambrian do",
                "workspace": ".",
            },
            "warnings": [],
            "errors": [],
        },
    )
    return {
        "request_path": request_path,
        "proposal_rel": proposal_rel,
        "adoption_rel": adoption_rel,
        "session_id": session_id,
    }


def test_agent_history_builds_passport_and_dispatch_log(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_agent_history_artifacts(tmp_path)

    proc = _run_cli(["agent", "history", "bug-fix-agent", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    passport_path = tmp_path / ".cambrian" / "agents" / "passports" / "bug-fix-agent.yaml"
    dispatch_log_path = tmp_path / ".cambrian" / "agents" / "dispatch_log.yaml"
    assert passport_path.exists()
    assert dispatch_log_path.exists()
    assert payload["totals"]["requests_seen"] == 1
    assert payload["totals"]["diagnoses"] == 1
    assert payload["totals"]["patch_proposals"] == 1
    assert payload["totals"]["validations_passed"] == 1
    assert payload["totals"]["adoptions"] == 1
    dispatch_log = _read_yaml(dispatch_log_path)
    assert any(item["agent_id"] == "bug-fix-agent" for item in dispatch_log["records"])


def test_agent_without_history_still_builds(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr

    proc = _run_cli(["agent", "history", "docs-update-agent", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["agent_id"] == "docs-update-agent"
    assert payload["totals"]["sessions_seen"] == 0
    assert payload["totals"]["adoptions"] == 0


def test_agent_recommend_uses_local_history_reason(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_agent_history_artifacts(tmp_path)

    proc = _run_cli(["agent", "recommend", "로그인 에러 수정해", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["recommendations"][0]["agent_id"] == "bug-fix-agent"
    assert any("adoption 성공" in reason for reason in payload["recommendations"][0]["why"])


def test_agent_list_and_show_include_history_summary(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_agent_history_artifacts(tmp_path)

    list_proc = _run_cli(["agent", "list"], cwd=tmp_path)
    show_proc = _run_cli(["agent", "show", "bug-fix-agent"], cwd=tmp_path)

    assert list_proc.returncode == 0, list_proc.stderr
    assert "bug-fix-agent (" in list_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "History:" in show_proc.stdout
    assert "Recent win:" in show_proc.stdout


def test_harness_doctor_and_status_include_agent_history(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_agent_history_artifacts(tmp_path)
    history_proc = _run_cli(["agent", "history", "bug-fix-agent"], cwd=tmp_path)
    assert history_proc.returncode == 0, history_proc.stderr

    doctor_proc = _run_cli(["harness", "doctor"], cwd=tmp_path)
    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert doctor_proc.returncode == 0, doctor_proc.stderr
    assert "passport histories present" in doctor_proc.stdout
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Recent agent activity:" in status_proc.stdout
    assert "bug-fix-agent adopted 1 change" in status_proc.stdout


def test_agent_history_keeps_source_files_unchanged(tmp_path: Path) -> None:
    _init_project(tmp_path)
    fit_proc = _fit_harness(tmp_path)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_agent_history_artifacts(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()

    proc = _run_cli(["agent", "history", "bug-fix-agent"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    after_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert before_hash == after_hash
    assert (tmp_path / ".cambrian" / "agents" / "passports" / "bug-fix-agent.yaml").exists()
    assert (tmp_path / ".cambrian" / "agents" / "dispatch_log.yaml").exists()
