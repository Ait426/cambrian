"""Cambrian 프로젝트 라우터 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine.brain.models import TaskSpec
from engine.project_mode import ProjectInitializer, ProjectRunPreparer, ProjectStatusReader
from engine.project_router import ProjectSkillRouter


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _load_configs(project_root: Path) -> tuple[dict, dict, dict, dict]:
    cambrian_dir = project_root / ".cambrian"
    return (
        _read_yaml(cambrian_dir / "project.yaml"),
        _read_yaml(cambrian_dir / "rules.yaml"),
        _read_yaml(cambrian_dir / "skills.yaml"),
        _read_yaml(cambrian_dir / "profile.yaml"),
    )


def test_route_bug_fix_request(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    project_cfg, rules, skills, profile = _load_configs(tmp_path)

    result = ProjectSkillRouter().route(
        "로그인 에러 수정해",
        project_cfg,
        rules,
        skills,
        profile,
        explicit_options={"project_root": str(tmp_path)},
    )

    assert result.intent_type == "bug_fix"
    assert "bug_fix" in result.selected_skills()
    assert "regression_test" in result.selected_skills()
    assert result.execution_readiness == "needs_context"
    assert "target_file" in result.required_context


def test_route_test_generation_request(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    project_cfg, rules, skills, profile = _load_configs(tmp_path)

    result = ProjectSkillRouter().route(
        "test_add.py 테스트 만들어",
        project_cfg,
        rules,
        skills,
        profile,
        explicit_options={"project_root": str(tmp_path)},
    )

    assert result.intent_type == "test_generation"
    assert "regression_test" in result.selected_skills()


def test_route_review_request(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    project_cfg, rules, skills, profile = _load_configs(tmp_path)

    result = ProjectSkillRouter().route(
        "A안 B안 중 더 안전한 쪽 골라",
        project_cfg,
        rules,
        skills,
        profile,
        explicit_options={"project_root": str(tmp_path)},
    )

    assert result.intent_type == "review_candidate"
    assert result.execution_readiness == "review_only"
    assert result.selected_skills() == ["review_candidate"]


def test_unknown_request_fallback(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    project_cfg, rules, skills, profile = _load_configs(tmp_path)

    result = ProjectSkillRouter().route(
        "좀 봐줘",
        project_cfg,
        rules,
        skills,
        profile,
        explicit_options={"project_root": str(tmp_path)},
    )

    assert result.intent_type == "unknown"
    assert result.execution_readiness == "needs_context"
    assert result.selected_skills()


def test_explicit_write_file_executable(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "create test_add.py",
        action="write_file",
        target="test_add.py",
        content="def test_add():\n    assert 1 + 1 == 2\n",
        tests=["test_add.py"],
    )

    task_spec = TaskSpec.from_yaml(tmp_path / result.task_spec_path)
    assert result.routing["execution_readiness"] == "executable"
    assert task_spec.actions is not None
    assert task_spec.actions[0]["type"] == "write_file"
    assert task_spec.output_paths == ["test_add.py"]


def test_explicit_patch_file_executable(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("value = 1\n", encoding="utf-8")

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "src/a.py 값을 수정해",
        action="patch_file",
        target="src/a.py",
        old_text="value = 1",
        new_text="value = 2",
    )

    task_spec = TaskSpec.from_yaml(tmp_path / result.task_spec_path)
    assert result.routing["execution_readiness"] == "executable"
    assert task_spec.actions is not None
    assert task_spec.actions[0]["type"] == "patch_file"


def test_unsafe_path_blocked(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "escape file",
        action="write_file",
        target="../escape.py",
        content="print('bad')\n",
    )

    assert result.routing["execution_readiness"] == "blocked"
    task_spec = TaskSpec.from_yaml(tmp_path / result.task_spec_path)
    assert task_spec.actions is None


def test_content_and_content_file_conflict(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    content_file = tmp_path / "payload.txt"
    content_file.write_text("hello\n", encoding="utf-8")

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "file 만들기",
        action="write_file",
        target="test_add.py",
        content="abc",
        content_file=str(content_file),
    )

    assert result.routing["execution_readiness"] == "blocked"
    assert any("동시에" in item for item in result.routing["safety_warnings"])


def test_run_creates_request_and_task_artifacts(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    request_payload = _read_yaml(tmp_path / result.request_path)
    assert (tmp_path / result.request_path).exists()
    assert (tmp_path / result.task_spec_path).exists()
    assert request_payload["routing"]["intent_type"] == "bug_fix"
    assert request_payload["user_request"] == "로그인 에러 수정해"


def test_execute_blocked_when_needs_context(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        execute=True,
    )

    assert result.execution["status"] == "blocked"
    assert "target_file" in result.execution["reason"]
    assert not (tmp_path / ".cambrian" / "brain" / "runs").exists()


def test_execute_executable_path_runs_brain(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "create test_add.py",
        action="write_file",
        target="test_add.py",
        content="def test_add():\n    assert 1 + 1 == 2\n",
        tests=["test_add.py"],
        execute=True,
        max_iterations=4,
    )

    assert result.execution["attempted"] is True
    assert result.execution["status"] == "completed"
    brain_run_id = result.execution["brain_run_id"]
    assert (tmp_path / ".cambrian" / "brain" / "runs" / brain_run_id).exists()
    assert result.execution["report_path"].endswith("report.json")


def test_status_shows_recent_requests(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    status = ProjectStatusReader().read(tmp_path)

    assert status.recent_requests
    assert status.recent_requests[0]["intent_type"] == "bug_fix"


def test_run_json_like_payload_contains_routing(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "create test_add.py",
        action="write_file",
        target="test_add.py",
        content="def test_add():\n    assert 1 + 1 == 2\n",
    )

    payload = result.to_dict()
    assert payload["routing"]["intent_type"] == "test_generation"
    assert payload["routing"]["execution_readiness"] == "executable"
    json.dumps(payload, ensure_ascii=False)
