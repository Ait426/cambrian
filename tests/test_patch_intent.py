"""Cambrian guided patch intent 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer, ProjectStatusReader
from engine.project_patch_intent import (
    PatchIntentBuilder,
    PatchIntentFiller,
    PatchIntentStore,
)


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth.py").write_text(
        "import re\n\n"
        "# 사용자 이름 정규화\n"
        "def normalize_username(username: str) -> str:\n"
        "    return username\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth import normalize_username\n\n"
        "def test_normalize_username_lowercases_email() -> None:\n"
        "    assert normalize_username('USER@EXAMPLE.COM') == 'user@example.com'\n",
        encoding="utf-8",
    )


def _write_diagnosis_report(
    project_root: Path,
    *,
    include_target: bool = True,
) -> Path:
    report_path = project_root / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    inspected_files = []
    if include_target:
        inspected_files.append(
            {
                "path": "src/auth.py",
                "sha256": "dummy",
                "size_bytes": 96,
                "truncated": False,
                "preview": "def normalize_username(username: str) -> str:\\n    return username\\n",
            }
        )
    _write_json(
        report_path,
        {
            "run_id": "brain-001",
            "user_request": "로그인 정규화 버그 수정해",
            "diagnostics": {
                "enabled": True,
                "mode": "read_only",
                "inspected_files": inspected_files,
                "related_tests": ["tests/test_auth.py"],
                "test_results": {
                    "passed": 0,
                    "failed": 1,
                    "skipped": 0,
                    "tests_executed": ["tests/test_auth.py"],
                },
                "next_actions": [
                    "Prepare a patch against src/auth.py",
                ],
            },
        },
    )
    return report_path


def _build_and_save_intent(project_root: Path) -> Path:
    form = PatchIntentBuilder().build_from_diagnosis(
        diagnosis_report_path=_write_diagnosis_report(project_root),
        project_root=project_root,
    )
    intent_path = project_root / ".cambrian" / "patch_intents" / "patch_intent_test_auth.py.yaml"
    PatchIntentStore().save(form, intent_path)
    return intent_path


def test_build_intent_from_diagnosis(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    diagnosis_path = _write_diagnosis_report(tmp_path)

    form = PatchIntentBuilder().build_from_diagnosis(diagnosis_path, tmp_path)

    assert form.status == "draft"
    assert form.target_path == "src/auth.py"
    assert form.related_tests == ["tests/test_auth.py"]
    assert any(candidate.text == "return username" for candidate in form.old_text_candidates)


def test_intent_handles_missing_target(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    diagnosis_path = _write_diagnosis_report(tmp_path, include_target=False)

    form = PatchIntentBuilder().build_from_diagnosis(diagnosis_path, tmp_path)

    assert form.status == "blocked"
    assert form.errors


def test_old_text_candidates_exclude_comments_imports(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    diagnosis_path = _write_diagnosis_report(tmp_path)

    form = PatchIntentBuilder().build_from_diagnosis(diagnosis_path, tmp_path)

    assert form.old_text_candidates
    assert all(not candidate.text.startswith("#") for candidate in form.old_text_candidates)
    assert all(not candidate.text.startswith("import ") for candidate in form.old_text_candidates)
    assert all(not candidate.text.startswith("from ") for candidate in form.old_text_candidates)


def test_intent_fill_with_old_choice(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)

    form = PatchIntentFiller().fill(
        intent_path,
        old_choice="old-1",
        new_text="return username.strip().lower()",
    )

    assert form.status == "ready_for_proposal"
    assert form.selected_old_choice == "old-1"
    assert form.selected_old_text == "return username"
    assert form.new_text == "return username.strip().lower()"


def test_intent_fill_old_text_direct(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)

    form = PatchIntentFiller().fill(
        intent_path,
        old_text="return username",
        new_text="return username.strip().lower()",
    )

    assert form.status == "ready_for_proposal"
    assert form.selected_old_text == "return username"


def test_intent_fill_blocks_missing_old_text(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)

    form = PatchIntentFiller().fill(
        intent_path,
        old_text="return missing_value",
        new_text="return username.strip().lower()",
    )

    assert form.status == "blocked"
    assert any("old_text was not found" in item for item in form.errors)


def test_intent_fill_with_new_text_file(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)
    target_path = tmp_path / "src" / "auth.py"
    before_hash = _sha256(target_path)
    new_text_file = tmp_path / "new_text.txt"
    new_text_file.write_text("return username.strip().lower()", encoding="utf-8")

    form = PatchIntentFiller().fill(
        intent_path,
        old_choice="old-1",
        new_text_file=new_text_file,
    )

    assert form.status == "ready_for_proposal"
    assert form.new_text == "return username.strip().lower()"
    assert _sha256(target_path) == before_hash


def test_patch_propose_from_intent(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)
    PatchIntentFiller().fill(
        intent_path,
        old_choice="old-1",
        new_text="return username.strip().lower()",
    )

    result = _run_cli(
        ["patch", "propose", "--from-intent", str(intent_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    proposal_files = list((tmp_path / ".cambrian" / "patches").glob("patch_proposal_*.yaml"))
    assert proposal_files
    proposal_payload = _read_yaml(proposal_files[-1])
    assert proposal_payload["action"]["type"] == "patch_file"
    assert proposal_payload["source_diagnosis_ref"] == ".cambrian/brain/runs/brain-001/report.json"
    assert proposal_payload["related_tests"] == ["tests/test_auth.py"]


def test_draft_intent_cannot_propose(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)

    result = _run_cli(
        ["patch", "propose", "--from-intent", str(intent_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "blocked" in result.stdout.lower() or "could not prepare" in result.stdout.lower()
    assert not list((tmp_path / ".cambrian" / "patches").glob("patch_proposal_*.yaml"))


def test_intent_fill_propose_execute_isolated_validation(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)
    target_path = tmp_path / "src" / "auth.py"
    before_hash = _sha256(target_path)

    result = _run_cli(
        [
            "patch",
            "intent-fill",
            str(intent_path),
            "--old-choice",
            "old-1",
            "--new-text",
            "return username.strip().lower()",
            "--propose",
            "--execute",
        ],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    proposal_files = list((tmp_path / ".cambrian" / "patches").glob("patch_proposal_*.yaml"))
    assert proposal_files
    proposal_payload = _read_yaml(proposal_files[-1])
    assert proposal_payload["validation"]["status"] == "passed"
    assert _sha256(target_path) == before_hash


def test_source_immutability_across_intent_flow(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    diagnosis_path = _write_diagnosis_report(tmp_path)
    target_path = tmp_path / "src" / "auth.py"
    before_hash = _sha256(target_path)

    form = PatchIntentBuilder().build_from_diagnosis(diagnosis_path, tmp_path)
    intent_path = tmp_path / ".cambrian" / "patch_intents" / "patch_intent_immutability.yaml"
    PatchIntentStore().save(form, intent_path)
    assert _sha256(target_path) == before_hash

    PatchIntentFiller().fill(
        intent_path,
        old_choice="old-1",
        new_text="return username.strip().lower()",
    )
    assert _sha256(target_path) == before_hash

    result = _run_cli(
        ["patch", "propose", "--from-intent", str(intent_path), "--execute"],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert _sha256(target_path) == before_hash


def test_cli_smoke(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    diagnosis_path = _write_diagnosis_report(tmp_path)

    intent_proc = _run_cli(["patch", "intent", str(diagnosis_path)], tmp_path)
    assert intent_proc.returncode == 0, intent_proc.stderr
    assert "Cambrian prepared a patch intent form." in intent_proc.stdout

    intent_files = list((tmp_path / ".cambrian" / "patch_intents").glob("patch_intent_*.yaml"))
    assert intent_files

    fill_proc = _run_cli(
        [
            "patch",
            "intent-fill",
            str(intent_files[-1]),
            "--old-choice",
            "old-1",
            "--new-text",
            "return username.strip().lower()",
        ],
        tmp_path,
    )
    assert fill_proc.returncode == 0, fill_proc.stderr

    propose_proc = _run_cli(
        ["patch", "propose", "--from-intent", str(intent_files[-1])],
        tmp_path,
    )
    assert propose_proc.returncode == 0, propose_proc.stderr
    assert "Cambrian prepared a patch proposal." in propose_proc.stdout


def test_status_recent_intent(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    intent_path = _build_and_save_intent(tmp_path)
    PatchIntentFiller().fill(
        intent_path,
        old_choice="old-1",
        new_text="return username.strip().lower()",
    )

    status = ProjectStatusReader().read(tmp_path)
    proc = _run_cli(["status"], tmp_path)

    assert status.recent_patch_intent
    assert status.recent_patch_intent["target"] == "src/auth.py"
    assert "Recent patch intent:" in proc.stdout
