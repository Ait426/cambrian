"""Cambrian guided patch proposal 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer, ProjectStatusReader
from engine.project_patch import PatchIntent, PatchProposalBuilder


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


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


def _write_diagnosis_report(project_root: Path, *, related_tests: list[str] | None = None) -> Path:
    report_path = project_root / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    _write_json(
        report_path,
        {
            "run_id": "brain-001",
            "diagnostics": {
                "enabled": True,
                "mode": "read_only",
                "inspected_files": [
                    {
                        "path": "src/auth/login.py",
                        "sha256": "dummy",
                        "size_bytes": 48,
                        "truncated": False,
                    }
                ],
                "related_tests": ["tests/test_login.py"] if related_tests is None else related_tests,
                "test_results": {
                    "passed": 0,
                    "failed": 1,
                    "skipped": 0,
                },
                "next_actions": [
                    "Prepare a patch against src/auth/login.py",
                ],
            },
        },
    )
    return report_path


def test_build_patch_proposal_from_diagnosis(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    diagnosis_path = _write_diagnosis_report(tmp_path)

    proposal, proposal_path = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return False",
            new_text="return username == 'admin' and password == 'secret'",
            related_tests=[],
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
            user_request="로그인 에러 수정해",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
    )

    assert proposal.proposal_status == "ready"
    assert proposal.related_tests == ["tests/test_login.py"]
    assert proposal.action["type"] == "patch_file"
    assert proposal.task_spec_path is not None
    assert proposal_path.exists()
    assert (tmp_path / proposal.task_spec_path).exists()


def test_missing_old_text_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path)

    proposal, _ = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return True",
            new_text="return False",
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
    )

    assert proposal.proposal_status == "blocked"
    assert any("old_text was not found" in item for item in proposal.safety_warnings)
    assert proposal.task_spec_path is None


def test_unsafe_target_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)

    proposal, _ = PatchProposalBuilder().build(
        PatchIntent(
            target_path="../escape.py",
            old_text="a",
            new_text="b",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
    )

    assert proposal.proposal_status == "blocked"
    assert any("unsafe target path" in item for item in proposal.safety_warnings)
    assert not (tmp_path.parent / "escape.py").exists()


def test_source_immutability_default(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path)
    target = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(target)

    proposal, _ = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return False",
            new_text="return username == 'admin' and password == 'secret'",
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
    )

    assert proposal.proposal_status == "ready"
    assert _sha256(target) == before_hash


def test_execute_isolated_validation_passed(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path)
    target = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(target)

    proposal, proposal_path = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return False",
            new_text="return username == 'admin' and password == 'secret'",
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
        execute=True,
    )

    saved_payload = _read_yaml(proposal_path)
    assert proposal.proposal_status == "validated"
    assert proposal.validation is not None
    assert proposal.validation["status"] == "passed"
    assert saved_payload["validation"]["status"] == "passed"
    assert (tmp_path / proposal.validation["workspace_path"]).exists()
    assert _sha256(target) == before_hash


def test_execute_isolated_validation_failed(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path)
    target = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(target)

    proposal, _ = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return False",
            new_text="return password == 'wrong'",
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
        execute=True,
    )

    assert proposal.validation is not None
    assert proposal.validation["status"] == "failed"
    assert _sha256(target) == before_hash


def test_inconclusive_validation_without_tests(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path, related_tests=[])

    proposal, _ = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return False",
            new_text="return username == 'admin' and password == 'secret'",
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
        execute=True,
    )

    assert proposal.validation is not None
    assert proposal.validation["status"] == "inconclusive"


def test_content_conflict_blocked(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path)

    proposal, _ = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return False",
            new_text="return True",
            patch_file_path="proposal.patch",
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
    )

    assert proposal.proposal_status == "blocked"
    assert any("--patch-file" in item for item in proposal.safety_warnings)


def test_cli_patch_propose_smoke(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path)

    result = _run_cli(
        [
            "patch",
            "propose",
            "--from-diagnosis",
            ".cambrian/brain/runs/brain-001/report.json",
            "--target",
            "src/auth/login.py",
            "--old-text",
            "return False",
            "--new-text",
            "return username == 'admin' and password == 'secret'",
        ],
        tmp_path,
    )

    assert result.returncode == 0
    assert "Cambrian prepared a patch proposal." in result.stdout
    assert list((tmp_path / ".cambrian" / "patches").glob("patch_proposal_*.yaml"))


def test_cli_patch_propose_json_output(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_diagnosis_report(tmp_path)

    result = _run_cli(
        [
            "patch",
            "propose",
            "--from-diagnosis",
            ".cambrian/brain/runs/brain-001/report.json",
            "--target",
            "src/auth/login.py",
            "--old-text",
            "return False",
            "--new-text",
            "return username == 'admin' and password == 'secret'",
            "--json",
        ],
        tmp_path,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["proposal_status"] == "ready"
    assert payload["proposal_path"]


def test_status_shows_recent_proposal(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_diagnosis_report(tmp_path)
    PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth/login.py",
            old_text="return False",
            new_text="return username == 'admin' and password == 'secret'",
            source_diagnosis_ref=".cambrian/brain/runs/brain-001/report.json",
        ),
        project_root=tmp_path,
        out_dir=tmp_path / ".cambrian" / "patches",
    )

    status = ProjectStatusReader().read(tmp_path)

    assert status.recent_patch_proposal
    assert status.recent_patch_proposal["target"] == "src/auth/login.py"
