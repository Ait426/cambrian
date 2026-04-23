"""Cambrian 프로젝트 여정 E2E 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_activity import ProjectActivityReader
from engine.project_mode import (
    ProjectInitializer,
    ProjectRunPreparer,
    ProjectStatusReader,
    render_status_summary,
)
from engine.project_patch import PatchIntent, PatchProposalBuilder
from engine.project_patch_apply import PatchApplier


REQUEST_TEXT = "로그인 정규화 버그 수정해"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _fixture_root() -> Path:
    return _repo_root() / "tests" / "fixtures" / "project_mode" / "login_bug"


def _copy_fixture(target_root: Path) -> Path:
    project_root = target_root / "login_bug_project"
    shutil.copytree(_fixture_root(), project_root)
    return project_root


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_repo_root())
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


def _latest_file(directory: Path, pattern: str) -> Path:
    candidates = sorted(
        directory.glob(pattern),
        key=lambda item: (item.stat().st_mtime, item.name),
    )
    assert candidates
    return candidates[-1]


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e2e_project_journey_success(tmp_path: Path) -> None:
    project_root = _copy_fixture(tmp_path)
    source_path = project_root / "src" / "auth.py"
    before_hash = _sha256(source_path)

    init_proc = _run_cli(
        [
            "init",
            "--non-interactive",
            "--name",
            "login-bug-demo",
            "--type",
            "python",
            "--test-cmd",
            "pytest -q",
        ],
        project_root,
    )
    assert init_proc.returncode == 0, init_proc.stderr
    assert "Cambrian initialized." in init_proc.stdout

    run_proc = _run_cli(["run", REQUEST_TEXT], project_root)
    assert run_proc.returncode == 0, run_proc.stderr
    assert "Cambrian found likely context." in run_proc.stdout
    assert _sha256(source_path) == before_hash

    request_payload = _read_yaml(
        _latest_file(project_root / ".cambrian" / "requests", "request_*.yaml")
    )
    assert request_payload["context_scan_ref"]
    assert request_payload["context_scan"]["top_sources"] == ["src/auth.py"]
    assert request_payload["context_scan"]["top_tests"] == ["tests/test_auth.py"]

    diagnose_proc = _run_cli(
        ["run", REQUEST_TEXT, "--use-top-context", "--execute"],
        project_root,
    )
    assert diagnose_proc.returncode == 0, diagnose_proc.stderr
    assert "Cambrian diagnosed the request." in diagnose_proc.stdout
    assert _sha256(source_path) == before_hash

    diagnose_request = _read_yaml(
        _latest_file(project_root / ".cambrian" / "requests", "request_*.yaml")
    )
    report_path = project_root / diagnose_request["execution"]["report_path"]
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["diagnostics"]["enabled"] is True
    assert report_payload["diagnostics"]["test_results"]["failed"] > 0

    propose_proc = _run_cli(
        [
            "patch",
            "propose",
            "--from-diagnosis",
            diagnose_request["execution"]["report_path"],
            "--target",
            "src/auth.py",
            "--old-text",
            "return username",
            "--new-text",
            "return username.strip().lower()",
            "--test",
            "tests/test_auth.py",
            "--execute",
        ],
        project_root,
    )
    assert propose_proc.returncode == 0, propose_proc.stderr
    assert "Cambrian validated the patch proposal in isolation." in propose_proc.stdout
    assert _sha256(source_path) == before_hash

    proposal_path = _latest_file(project_root / ".cambrian" / "patches", "patch_proposal_*.yaml")
    proposal_payload = _read_yaml(proposal_path)
    assert proposal_payload["validation"]["status"] == "passed"

    apply_proc = _run_cli(
        [
            "patch",
            "apply",
            str(proposal_path.relative_to(project_root)).replace("\\", "/"),
            "--reason",
            "normalize username before login",
        ],
        project_root,
    )
    assert apply_proc.returncode == 0, apply_proc.stderr
    assert "[PATCH APPLY] adopted" in apply_proc.stdout
    assert "Created:" in apply_proc.stdout
    assert "Next:" in apply_proc.stdout
    assert source_path.read_text(encoding="utf-8").strip().endswith("return username.strip().lower()")

    pytest_proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert pytest_proc.returncode == 0, pytest_proc.stdout + pytest_proc.stderr

    latest_path = project_root / ".cambrian" / "adoptions" / "_latest.json"
    latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
    assert latest_payload["proposal_id"] == proposal_payload["proposal_id"]
    assert Path(project_root / latest_payload["latest_adoption_path"]).exists()

    status_proc = _run_cli(["status"], project_root)
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Recent journey:" in status_proc.stdout
    assert "Patch adopted" in status_proc.stdout or "patch adopted" in status_proc.stdout
    assert "Next:" in status_proc.stdout


def test_source_not_modified_before_apply(tmp_path: Path) -> None:
    project_root = _copy_fixture(tmp_path)
    ProjectInitializer().init(project_root)
    source_path = project_root / "src" / "auth.py"
    before_hash = _sha256(source_path)

    ProjectRunPreparer().prepare(project_root, REQUEST_TEXT)
    assert _sha256(source_path) == before_hash

    diagnose_result = ProjectRunPreparer().prepare(
        project_root,
        REQUEST_TEXT,
        use_top_context=True,
        execute=True,
        max_iterations=4,
    )
    assert _sha256(source_path) == before_hash

    proposal, proposal_path = PatchProposalBuilder().build(
        PatchIntent(
            target_path="src/auth.py",
            old_text="return username",
            new_text="return username.strip().lower()",
            related_tests=["tests/test_auth.py"],
            source_diagnosis_ref=diagnose_result.execution["report_path"],
            user_request=REQUEST_TEXT,
        ),
        project_root=project_root,
        out_dir=project_root / ".cambrian" / "patches",
        execute=True,
    )
    assert proposal.validation is not None
    assert proposal.validation["status"] == "passed"
    assert _sha256(source_path) == before_hash

    apply_result = PatchApplier().apply(
        proposal_path=proposal_path,
        project_root=project_root,
        adoptions_dir=project_root / ".cambrian" / "adoptions",
        reason="normalize username before login",
    )
    assert apply_result.status == "applied"
    assert _sha256(source_path) != before_hash


def test_status_before_journey(tmp_path: Path) -> None:
    project_root = _copy_fixture(tmp_path)
    ProjectInitializer().init(project_root)

    status = ProjectStatusReader().read(project_root)
    rendered = render_status_summary(status)

    assert status.recent_journey == []
    assert "Recent journey:" in rendered
    assert "  none yet" in rendered
    assert "Next:" in rendered


def test_activity_reader_handles_malformed_artifacts(tmp_path: Path) -> None:
    project_root = _copy_fixture(tmp_path)
    ProjectInitializer().init(project_root)
    (project_root / ".cambrian" / "requests").mkdir(parents=True, exist_ok=True)
    (project_root / ".cambrian" / "context").mkdir(parents=True, exist_ok=True)
    (project_root / ".cambrian" / "patches").mkdir(parents=True, exist_ok=True)
    (project_root / ".cambrian" / "adoptions").mkdir(parents=True, exist_ok=True)

    (project_root / ".cambrian" / "requests" / "request_bad.yaml").write_text("[\n", encoding="utf-8")
    (project_root / ".cambrian" / "context" / "context_bad.yaml").write_text("{\n", encoding="utf-8")
    (project_root / ".cambrian" / "patches" / "patch_proposal_bad.yaml").write_text(":\n", encoding="utf-8")
    (project_root / ".cambrian" / "adoptions" / "_latest.json").write_text("{bad", encoding="utf-8")

    status = ProjectStatusReader().read(project_root)

    assert status.initialized is True
    assert status.warnings


def test_activity_reader_latest_ordering(tmp_path: Path) -> None:
    project_root = _copy_fixture(tmp_path)
    ProjectInitializer().init(project_root)

    requests_dir = project_root / ".cambrian" / "requests"
    patches_dir = project_root / ".cambrian" / "patches"
    adoptions_dir = project_root / ".cambrian" / "adoptions"
    requests_dir.mkdir(parents=True, exist_ok=True)
    patches_dir.mkdir(parents=True, exist_ok=True)
    adoptions_dir.mkdir(parents=True, exist_ok=True)

    old_request = requests_dir / "request_old.yaml"
    new_request = requests_dir / "request_new.yaml"
    old_request.write_text(
        yaml.safe_dump(
            {
                "request_id": "req-old",
                "created_at": "2026-04-22T00:00:00Z",
                "user_request": "오래된 요청",
                "routing": {"intent_type": "bug_fix", "execution_readiness": "needs_context"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    new_request.write_text(
        yaml.safe_dump(
            {
                "request_id": "req-new",
                "created_at": "2026-04-23T00:00:00Z",
                "user_request": "최신 요청",
                "routing": {"intent_type": "bug_fix", "execution_readiness": "needs_context"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    os.utime(old_request, (1, 1))
    os.utime(new_request, (2, 2))

    old_proposal = patches_dir / "patch_proposal_old.yaml"
    new_proposal = patches_dir / "patch_proposal_new.yaml"
    old_proposal.write_text(
        yaml.safe_dump(
            {
                "created_at": "2026-04-22T00:00:00Z",
                "target_path": "src/old.py",
                "proposal_status": "ready",
                "validation": {"attempted": False, "status": "not_requested"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    new_proposal.write_text(
        yaml.safe_dump(
            {
                "created_at": "2026-04-23T00:00:00Z",
                "target_path": "src/new.py",
                "proposal_status": "validated",
                "validation": {"attempted": True, "status": "passed"},
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    os.utime(old_proposal, (1, 1))
    os.utime(new_proposal, (2, 2))

    old_adoption = adoptions_dir / "adoption_old.json"
    new_adoption = adoptions_dir / "adoption_new.json"
    old_adoption.write_text(
        json.dumps(
            {
                "created_at": "2026-04-22T00:00:00Z",
                "target_path": "src/old.py",
                "post_apply_tests": {"passed": 1, "failed": 0},
                "human_reason": "old",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    new_adoption.write_text(
        json.dumps(
            {
                "created_at": "2026-04-23T00:00:00Z",
                "target_path": "src/new.py",
                "post_apply_tests": {"passed": 1, "failed": 0},
                "human_reason": "new",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.utime(old_adoption, (1, 1))
    os.utime(new_adoption, (2, 2))

    summary = ProjectActivityReader().read(project_root, [])

    assert summary.latest_request is not None
    assert summary.latest_request.title == "최신 요청"
    assert summary.latest_patch_proposal is not None
    assert summary.latest_patch_proposal.title == "src/new.py"
    assert summary.latest_adoption is not None
    assert summary.latest_adoption.title == "src/new.py"


def test_cli_output_contains_created_and_next(tmp_path: Path) -> None:
    project_root = _copy_fixture(tmp_path)
    _run_cli(
        [
            "init",
            "--non-interactive",
            "--name",
            "login-bug-demo",
            "--type",
            "python",
            "--test-cmd",
            "pytest -q",
        ],
        project_root,
    )

    run_proc = _run_cli(["run", REQUEST_TEXT], project_root)
    assert run_proc.returncode == 0
    assert "Created:" in run_proc.stdout
    assert "Next:" in run_proc.stdout

    diagnosis_request = _run_cli(
        ["run", REQUEST_TEXT, "--use-top-context", "--execute"],
        project_root,
    )
    assert diagnosis_request.returncode == 0
    request_payload = _read_yaml(
        _latest_file(project_root / ".cambrian" / "requests", "request_*.yaml")
    )
    proposal_proc = _run_cli(
        [
            "patch",
            "propose",
            "--from-diagnosis",
            request_payload["execution"]["report_path"],
            "--target",
            "src/auth.py",
            "--old-text",
            "return username",
            "--new-text",
            "return username.strip().lower()",
            "--test",
            "tests/test_auth.py",
            "--execute",
        ],
        project_root,
    )
    assert proposal_proc.returncode == 0
    proposal_path = _latest_file(project_root / ".cambrian" / "patches", "patch_proposal_*.yaml")

    apply_proc = _run_cli(
        [
            "patch",
            "apply",
            str(proposal_path.relative_to(project_root)).replace("\\", "/"),
            "--reason",
            "normalize username before login",
        ],
        project_root,
    )
    assert apply_proc.returncode == 0
    assert "Created:" in apply_proc.stdout
    assert "Next:" in apply_proc.stdout


def test_quickstart_doc_exists() -> None:
    quickstart_path = _repo_root() / "docs" / "PROJECT_MODE_QUICKSTART.md"
    content = quickstart_path.read_text(encoding="utf-8")

    assert quickstart_path.exists()
    assert "cambrian init" in content
    assert "cambrian run" in content
    assert "cambrian patch propose" in content
    assert "cambrian patch apply" in content
    assert "cambrian status" in content
