"""Cambrian context-assisted diagnose-only run 테스트."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from engine.brain.adapters.executor_v1 import ExecutorV1
from engine.brain.models import TaskSpec, WorkItem
from engine.project_context import ProjectContextScanner
from engine.project_mode import (
    ProjectInitializer,
    ProjectRunPreparer,
    ProjectStatusReader,
)
from engine.project_run_builder import DiagnoseTaskSpecBuilder


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_inspect_files_action_reads_file(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    target_path = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(target_path)

    result = ExecutorV1(tmp_path).execute(
        WorkItem(
            item_id="work-001",
            description="inspect login source",
            action={
                "type": "inspect_files",
                "target_paths": ["src/auth/login.py"],
            },
        )
    )

    assert result.status == "success"
    assert result.details is not None
    inspected = result.details["inspected_files"]
    assert inspected[0]["path"] == "src/auth/login.py"
    assert inspected[0]["sha256"] == before_hash
    assert inspected[0]["preview"]
    assert _sha256(target_path) == before_hash


def test_inspect_files_blocks_unsafe_path(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)

    result = ExecutorV1(tmp_path).execute(
        WorkItem(
            item_id="work-001",
            description="unsafe inspect",
            action={
                "type": "inspect_files",
                "target_paths": ["../escape.py"],
            },
        )
    )

    assert result.status == "failure"
    assert result.details is not None
    assert result.details["inspected_files"] == []
    assert result.details["errors"]


def test_inspect_files_skips_large_file(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    large_path = tmp_path / "src" / "large.txt"
    large_path.parent.mkdir(parents=True, exist_ok=True)
    large_path.write_text("a" * (1_048_576 + 16), encoding="utf-8")

    result = ExecutorV1(tmp_path).execute(
        WorkItem(
            item_id="work-001",
            description="large inspect",
            action={
                "type": "inspect_files",
                "target_paths": ["src/large.txt"],
            },
        )
    )

    assert result.details is not None
    assert result.details["inspected_files"] == []
    assert result.details["skipped_files"][0]["reason"] == "file_too_large"


def test_diagnose_task_spec_builder_from_context(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    context_scan = {
        "_source_path": ".cambrian/context/context_req.yaml",
        "top_source": "src/auth/login.py",
        "top_test": "tests/test_login.py",
        "source_candidates": [{"path": "src/auth/login.py", "score": 10, "why": "matched login"}],
        "test_candidates": [{"path": "tests/test_login.py", "score": 9, "why": "matched login test"}],
    }

    build = DiagnoseTaskSpecBuilder().build_from_context(
        user_request="로그인 에러 수정해",
        context_scan=context_scan,
        selected_sources=["src/auth/login.py"],
        selected_tests=["tests/test_login.py"],
        request_id="req-001",
        project_config={},
    )

    assert build.task_spec.actions is not None
    assert build.task_spec.actions[0]["type"] == "inspect_files"
    assert build.task_spec.related_tests == ["tests/test_login.py"]
    assert build.task_spec.output_paths == []
    assert all(
        action["type"] not in {"write_file", "patch_file"}
        for action in build.task_spec.actions
    )


def test_run_use_top_context_creates_diagnose_task(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        use_top_context=True,
    )

    task_spec = TaskSpec.from_yaml(tmp_path / result.task_spec_path)
    assert result.diagnose_only is True
    assert result.routing["execution_readiness"] == "executable"
    assert result.selected_context["sources"] == ["src/auth/login.py"]
    assert result.selected_context["tests"] == ["tests/test_login.py"]
    assert result.context_scan_path is not None
    assert task_spec.actions is not None
    assert task_spec.actions[0]["type"] == "inspect_files"


def test_run_context_source_test_builds_diagnose_task(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    scanner = ProjectContextScanner()
    scan_result = scanner.scan(tmp_path, "로그인 에러 수정해", "req-ctx")
    context_path = tmp_path / ".cambrian" / "context" / "context_req-ctx.yaml"
    scanner.save(scan_result, context_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        context_path=str(context_path),
        source_paths=["src/auth/login.py"],
        tests=["tests/test_login.py"],
    )

    assert result.diagnose_only is True
    assert result.selected_context["sources"] == ["src/auth/login.py"]
    assert result.selected_context["tests"] == ["tests/test_login.py"]
    task_spec = TaskSpec.from_yaml(tmp_path / result.task_spec_path)
    assert task_spec.actions is not None
    assert task_spec.actions[0]["type"] == "inspect_files"


def test_diagnose_action_conflict_is_blocked(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        diagnose_only=True,
        action="write_file",
        target="tmp.txt",
        content="bad\n",
    )

    task_spec = TaskSpec.from_yaml(tmp_path / result.task_spec_path)
    assert result.routing["execution_readiness"] == "blocked"
    assert task_spec.actions is None


def test_execute_diagnose_only_runs_and_keeps_source_immutable(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path, failing_test=True)
    ProjectInitializer().init(tmp_path)
    source_path = tmp_path / "src" / "auth" / "login.py"
    before_hash = _sha256(source_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        use_top_context=True,
        execute=True,
        max_iterations=4,
    )

    assert result.execution["attempted"] is True
    assert result.execution["report_path"].endswith("report.json")
    report = _read_yaml(tmp_path / result.request_path)
    assert report["execution"]["attempted"] is True
    report_json = _read_yaml(tmp_path / result.request_path)
    assert report_json["diagnose_only"] is True
    brain_report_path = tmp_path / result.execution["report_path"]
    diagnostics_report = yaml.safe_load(brain_report_path.read_text(encoding="utf-8")) if brain_report_path.suffix == ".yaml" else None
    assert _sha256(source_path) == before_hash


def test_execute_without_top_source_remains_blocked(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        use_top_context=True,
        execute=True,
    )

    assert result.execution["status"] == "blocked"
    assert not (tmp_path / ".cambrian" / "brain" / "runs").exists()


def test_diagnostic_report_contains_test_result(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path, failing_test=True)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        use_top_context=True,
        execute=True,
        max_iterations=4,
    )

    report_path = tmp_path / result.execution["report_path"]
    import json

    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["diagnostics"]["enabled"] is True
    assert report_payload["diagnostics"]["test_results"]["failed"] > 0
    assert any(
        "Prepare a patch against src/auth/login.py" in item
        for item in report_payload["diagnostics"]["next_actions"]
    )


def test_status_shows_recent_diagnostic(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path, failing_test=True)
    ProjectInitializer().init(tmp_path)
    ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        use_top_context=True,
        execute=True,
        max_iterations=4,
    )

    status = ProjectStatusReader().read(tmp_path)

    assert status.recent_diagnostic
    assert "src/auth/login.py" in status.recent_diagnostic["source"]
