"""Cambrian patch apply 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer, ProjectStatusReader
from engine.project_patch_apply import PatchApplier


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
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


def _prepare_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (project_root / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth" / "login.py").write_text(
        "def login(username: str, password: str) -> bool:\n"
        "    return False\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_login.py").write_text(
        "from src.auth.login import login\n\n"
        "def test_login_success() -> None:\n"
        "    assert login('admin', 'secret') is True\n",
        encoding="utf-8",
    )


def _write_context_artifacts(project_root: Path) -> dict[str, Path]:
    diagnosis_path = project_root / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    context_path = project_root / ".cambrian" / "context" / "context_001.yaml"
    task_path = project_root / ".cambrian" / "tasks" / "task_patch_patch-001.yaml"

    _write_json(
        diagnosis_path,
        {
            "run_id": "brain-001",
            "diagnostics": {
                "enabled": True,
                "related_tests": ["tests/test_login.py"],
                "test_results": {
                    "passed": 0,
                    "failed": 1,
                    "skipped": 0,
                },
            },
        },
    )
    _write_yaml(
        context_path,
        {
            "schema_version": "1.0.0",
            "request_id": "req-001",
            "status": "success",
            "top_source": "src/auth/login.py",
            "top_test": "tests/test_login.py",
        },
    )
    _write_yaml(
        task_path,
        {
            "task_id": "task-patch-patch-001",
            "goal": "Validate patch proposal for src/auth/login.py",
            "related_tests": ["tests/test_login.py"],
            "output_paths": ["src/auth/login.py"],
            "actions": [
                {
                    "type": "patch_file",
                    "target_path": "src/auth/login.py",
                    "old_text": "return False",
                    "new_text": "return username == 'admin' and password == 'secret'",
                }
            ],
        },
    )
    return {
        "diagnosis": diagnosis_path,
        "context": context_path,
        "task": task_path,
    }


def _write_proposal(
    project_root: Path,
    *,
    proposal_id: str = "patch-001",
    target_path: str = "src/auth/login.py",
    old_text: str = "return False",
    new_text: str = "return username == 'admin' and password == 'secret'",
    related_tests: list[str] | None = None,
    validation_attempted: bool = True,
    validation_status: str = "passed",
) -> Path:
    artifacts = _write_context_artifacts(project_root)
    proposal_path = project_root / ".cambrian" / "patches" / f"patch_proposal_{proposal_id}.yaml"
    tests = ["tests/test_login.py"] if related_tests is None else related_tests
    _write_yaml(
        proposal_path,
        {
            "schema_version": "1.0.0",
            "proposal_id": proposal_id,
            "created_at": "2026-04-23T00:00:00Z",
            "user_request": "로그인 오류 수정",
            "source_diagnosis_ref": ".cambrian/brain/runs/brain-001/report.json",
            "source_context_ref": ".cambrian/context/context_001.yaml",
            "target_path": target_path,
            "related_tests": tests,
            "action": {
                "type": "patch_file",
                "target_path": target_path,
                "old_text": old_text,
                "new_text": new_text,
            },
            "proposal_status": "validated" if validation_attempted and validation_status == "passed" else "ready",
            "safety_warnings": [],
            "validation": {
                "attempted": validation_attempted,
                "status": validation_status,
                "tests": {
                    "passed": 1 if validation_status == "passed" else 0,
                    "failed": 0 if validation_status == "passed" else 1,
                    "skipped": 0,
                    "exit_code": 0 if validation_status == "passed" else 1,
                    "tests_executed": tests,
                },
            },
            "task_spec_path": ".cambrian/tasks/task_patch_patch-001.yaml",
            "next_actions": [
                "Review proposal artifact",
                "Apply/adopt explicitly when ready",
            ],
        },
    )
    return proposal_path


def test_apply_validated_proposal_success(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    target = tmp_path / "src" / "auth" / "login.py"
    latest = tmp_path / ".cambrian" / "adoptions" / "_latest.json"
    assert result.status == "applied"
    assert "return username == 'admin' and password == 'secret'" in target.read_text(encoding="utf-8")
    assert result.post_apply_tests is not None
    assert result.post_apply_tests["passed"] == 1
    assert Path(tmp_path / result.adoption_record_path).exists()
    assert latest.exists()


def test_reason_required(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    target = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(target)

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="",
    )

    assert result.status == "blocked"
    assert _sha256(target) == before_hash
    assert not (tmp_path / ".cambrian" / "adoptions").exists()


def test_unvalidated_proposal_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(
        tmp_path,
        validation_attempted=False,
        validation_status="not_requested",
    )
    target = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(target)

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert result.status == "blocked"
    assert _sha256(target) == before_hash


def test_old_text_missing_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    target = tmp_path / "src" / "auth" / "login.py"
    target.write_text(
        "def login(username: str, password: str) -> bool:\n"
        "    return None\n",
        encoding="utf-8",
    )
    before_hash = _sha256(target)

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert result.status == "blocked"
    assert _sha256(target) == before_hash


def test_old_text_multiple_matches_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    target = tmp_path / "src" / "auth" / "login.py"
    target.write_text(
        "def login(username: str, password: str) -> bool:\n"
        "    if username == 'admin':\n"
        "        return False\n"
        "    return False\n",
        encoding="utf-8",
    )
    before_hash = _sha256(target)

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert result.status == "blocked"
    assert _sha256(target) == before_hash


def test_unsafe_target_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path, target_path="../escape.py")

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert result.status == "blocked"
    assert not (tmp_path.parent / "escape.py").exists()


def test_backup_and_hash_recorded(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    original = (tmp_path / "src" / "auth" / "login.py").read_text(encoding="utf-8")

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert result.status == "applied"
    applied = result.applied_files[0]
    backup_path = Path(str(applied["backup_path"]))
    assert backup_path.exists()
    assert applied["before_sha256"] != applied["after_sha256"]
    assert backup_path.read_text(encoding="utf-8") == original


def test_post_apply_test_failure_restores(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(
        tmp_path,
        new_text="return password == 'wrong'",
    )
    target = tmp_path / "src" / "auth" / "login.py"
    original = target.read_text(encoding="utf-8")
    latest = tmp_path / ".cambrian" / "adoptions" / "_latest.json"

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert result.status == "failed"
    assert target.read_text(encoding="utf-8") == original
    assert result.post_apply_tests is not None
    assert result.post_apply_tests["failed"] > 0
    assert not list((tmp_path / ".cambrian" / "adoptions").glob("adoption_*.json"))
    assert not latest.exists()


def test_dry_run_no_mutation(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    target = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(target)

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
        dry_run=True,
    )

    assert result.status == "dry_run"
    assert _sha256(target) == before_hash
    assert result.post_apply_tests is not None
    assert result.post_apply_tests["old_text_matches"] == 1
    assert not list((tmp_path / ".cambrian" / "adoptions").glob("adoption_*.json"))


def test_duplicate_idempotency(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    latest = tmp_path / ".cambrian" / "adoptions" / "_latest.json"

    first = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )
    latest_before = latest.read_text(encoding="utf-8")

    second = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert first.status == "applied"
    assert second.status == "duplicate"
    assert second.adoption_record_path == first.adoption_record_path
    assert latest.read_text(encoding="utf-8") == latest_before


def test_source_artifacts_immutable(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    diagnosis_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    context_path = tmp_path / ".cambrian" / "context" / "context_001.yaml"
    task_path = tmp_path / ".cambrian" / "tasks" / "task_patch_patch-001.yaml"
    before = {
        "proposal": _sha256(proposal_path),
        "diagnosis": _sha256(diagnosis_path),
        "context": _sha256(context_path),
        "task": _sha256(task_path),
    }

    result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    assert result.status == "applied"
    after = {
        "proposal": _sha256(proposal_path),
        "diagnosis": _sha256(diagnosis_path),
        "context": _sha256(context_path),
        "task": _sha256(task_path),
    }
    assert before == after


def test_cli_smoke_success(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(tmp_path)

    result = _run_cli(
        [
            "patch",
            "apply",
            str(proposal_path.relative_to(tmp_path)),
            "--reason",
            "로그인 오류 수정",
        ],
        tmp_path,
    )

    assert result.returncode == 0
    assert "[PATCH APPLY] adopted" in result.stdout
    assert list((tmp_path / ".cambrian" / "adoptions").glob("adoption_*.json"))


def test_cli_smoke_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    proposal_path = _write_proposal(
        tmp_path,
        validation_attempted=False,
        validation_status="not_requested",
    )

    result = _run_cli(
        [
            "patch",
            "apply",
            str(proposal_path.relative_to(tmp_path)),
            "--reason",
            "로그인 오류 수정",
        ],
        tmp_path,
    )

    assert result.returncode == 0
    assert "[PATCH APPLY] blocked" in result.stdout
    assert not list((tmp_path / ".cambrian" / "adoptions").glob("adoption_*.json"))


def test_status_latest_adoption(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    proposal_path = _write_proposal(tmp_path)
    PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=tmp_path,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        reason="로그인 오류 수정",
    )

    status = ProjectStatusReader().read(tmp_path)

    assert status.latest_patch_adoption
    assert status.latest_patch_adoption["target"] == "src/auth/login.py"
    assert status.latest_patch_adoption["tests"] == "passed"
    assert status.latest_patch_adoption["reason"] == "로그인 오류 수정"
