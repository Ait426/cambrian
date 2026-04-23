"""Cambrian run clarifier 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from engine.brain.models import TaskSpec
from engine.project_clarifier import RunClarifier
from engine.project_mode import ProjectInitializer, ProjectRunPreparer, ProjectStatusReader


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _prepare_login_fixture(project_root: Path, *, failing_test: bool = False) -> None:
    _prepare_python_project(project_root)
    (project_root / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "auth" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth" / "login.py").write_text(
        "def login(username: str, password: str) -> bool:\n"
        "    return username == 'admin' and password == 'secret'\n",
        encoding="utf-8",
    )
    assertion = "False" if failing_test else "True"
    (project_root / "tests" / "test_login.py").write_text(
        "def test_login_flow() -> None:\n"
        f"    assert {assertion}\n",
        encoding="utf-8",
    )


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


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


def test_create_clarification_from_needs_context_request(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    request_payload = _read_yaml(tmp_path / result.request_path)
    clarification_path = tmp_path / request_payload["clarification"]["path"]
    session = RunClarifier().load(clarification_path)

    assert session.status == "open"
    assert session.missing_context
    assert [question.kind for question in session.questions] == ["source", "test"]
    assert session.questions[0].options[0]["value"] == "src/auth/login.py"


def test_clarify_show_open_questions(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    proc = _run_cli(["clarify", result.request_id], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Choose a source file:" in proc.stdout
    assert "src/auth/login.py" in proc.stdout
    assert "Next:" in proc.stdout


def test_use_suggestion_selects_source(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    clarification_path = tmp_path / result.clarification["artifact_path"]

    session = RunClarifier().answer(clarification_path, use_suggestion=1)

    assert session.selected_context["sources"] == ["src/auth/login.py"]
    assert session.status == "ready"


def test_explicit_source_test_selection(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    clarification_path = tmp_path / result.clarification["artifact_path"]

    session = RunClarifier().answer(
        clarification_path,
        source=["src/auth/login.py"],
        tests=["tests/test_login.py"],
    )

    assert session.selected_context["sources"] == ["src/auth/login.py"]
    assert session.selected_context["tests"] == ["tests/test_login.py"]
    assert session.status == "ready"
    assert session.generated_task_spec_path is not None
    task_spec = TaskSpec.from_yaml(tmp_path / session.generated_task_spec_path)
    assert task_spec.actions is not None
    assert task_spec.actions[0]["type"] == "inspect_files"


def test_unsafe_source_blocked(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    clarification_path = tmp_path / result.clarification["artifact_path"]

    session = RunClarifier().answer(clarification_path, source=["../escape.py"])

    assert session.status == "blocked"
    assert session.generated_task_spec_path is None
    assert session.errors


def test_no_test_still_ready_with_warning(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    clarification_path = tmp_path / result.clarification["artifact_path"]

    session = RunClarifier().answer(clarification_path, source=["src/auth/login.py"])

    assert session.status == "ready"
    assert any("관련 테스트를 선택하지 않아" in item for item in session.warnings)


def test_execute_diagnose_only(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path, failing_test=True)
    ProjectInitializer().init(tmp_path)
    source_path = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(source_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    clarification_path = tmp_path / result.clarification["artifact_path"]

    RunClarifier().answer(
        clarification_path,
        source=["src/auth/login.py"],
        tests=["tests/test_login.py"],
    )
    session = RunClarifier().execute_ready(clarification_path, max_iterations=4)

    assert session.execution is not None
    assert session.execution["attempted"] is True
    assert session.execution["report_path"].endswith("report.json")
    assert (tmp_path / session.execution["report_path"]).exists()
    assert _sha256(source_path) == before_hash


def test_request_id_resolution(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    clarifier = RunClarifier()
    clarification_path = tmp_path / result.clarification["artifact_path"]
    session = clarifier.load(clarification_path)

    assert clarifier.resolve_artifact_path(result.request_id, tmp_path) == clarification_path.resolve()
    assert clarifier.resolve_artifact_path(session.clarification_id, tmp_path) == clarification_path.resolve()
    assert clarifier.resolve_artifact_path(clarification_path, tmp_path) == clarification_path.resolve()
    with pytest.raises(FileNotFoundError):
        clarifier.resolve_artifact_path("missing-request", tmp_path)


def test_run_auto_creates_clarification_when_needs_context(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    proc = _run_cli(["run", "로그인 에러 수정해"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "clarification" in proc.stdout
    assert "cambrian clarify" in proc.stdout
    request_files = sorted((tmp_path / ".cambrian" / "requests").glob("request_*.yaml"))
    assert request_files
    payload = _read_yaml(request_files[-1])
    assert payload["clarification"]["enabled"] is True


def test_status_shows_open_clarification(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    status = ProjectStatusReader().read(tmp_path)
    proc = _run_cli(["status"], cwd=tmp_path)

    assert status.open_clarification
    assert "Open clarification:" in proc.stdout
    assert "src/auth/login.py" in proc.stdout


def test_clarify_json_output(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    proc = _run_cli(["clarify", result.request_id, "--json"], cwd=tmp_path)
    payload = json.loads(proc.stdout)

    assert payload["status"] == "open"
    assert payload["questions"]
    assert payload["request_id"] == result.request_id


def test_source_immutability_during_clarify_flow(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path, failing_test=True)
    ProjectInitializer().init(tmp_path)
    source_path = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(source_path)
    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    clarification_path = tmp_path / result.clarification["artifact_path"]
    clarifier = RunClarifier()

    _ = clarifier.load(clarification_path)
    assert _sha256(source_path) == before_hash

    _ = clarifier.answer(clarification_path, source=["src/auth/login.py"])
    assert _sha256(source_path) == before_hash

    _ = clarifier.execute_ready(clarification_path, max_iterations=4)
    assert _sha256(source_path) == before_hash
