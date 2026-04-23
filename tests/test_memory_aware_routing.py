"""Cambrian memory-aware skill routing 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer, ProjectRunPreparer, ProjectStatusReader
from engine.project_router import ProjectSkillRouter


REQUEST_TEXT = "로그인 에러 수정해"


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _prepare_login_fixture(project_root: Path) -> None:
    _prepare_python_project(project_root)
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "tests").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth.py").write_text(
        "def normalize_username(username: str) -> str:\n"
        "    return username\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth import normalize_username\n\n"
        "def test_normalize_username_lowercases_email() -> None:\n"
        "    assert normalize_username(\"USER@EXAMPLE.COM\") == \"user@example.com\"\n",
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


def _write_lessons(project_root: Path, lessons: list[dict]) -> Path:
    memory_path = project_root / ".cambrian" / "memory" / "lessons.yaml"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "generated_at": "2026-04-23T00:00:00+00:00",
        "project_name": project_root.name,
        "lessons": lessons,
        "warnings": [],
        "errors": [],
    }
    memory_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return memory_path


def _lesson(
    lesson_id: str,
    *,
    kind: str,
    text: str,
    tags: list[str] | None = None,
    confidence: float = 0.8,
) -> dict:
    return {
        "lesson_id": lesson_id,
        "kind": kind,
        "text": text,
        "confidence": confidence,
        "source_refs": [".cambrian/adoptions/adoption_001.json"],
        "evidence_count": 1,
        "tags": list(tags or []),
        "created_at": "2026-04-23T00:00:00+00:00",
        "updated_at": "2026-04-23T00:00:00+00:00",
        "status": "active",
    }


def _route(project_root: Path, request: str = REQUEST_TEXT):
    project_cfg, rules, skills, profile = _load_configs(project_root)
    return ProjectSkillRouter().route(
        request,
        project_cfg,
        rules,
        skills,
        profile,
        explicit_options={"project_root": str(project_root)},
    )


def _route_scores(result) -> dict[str, float]:
    return {route.skill_id: route.score for route in result.routes}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_relevant_lesson_matching_by_tag(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )

    result = _route(tmp_path)

    relevant = result.memory_context["relevant_lessons"]
    assert result.memory_context["enabled"] is True
    assert relevant
    assert relevant[0]["lesson_id"] == "lesson-auth-tests-before-login-patches"


def test_relevant_lesson_matching_by_text(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-login-risk",
                kind="risk_warning",
                text="Avoid broad login refactors unless auth integration tests are selected.",
                tags=[],
            )
        ],
    )

    result = _route(tmp_path)

    relevant = result.memory_context["relevant_lessons"]
    assert relevant
    assert relevant[0]["lesson_id"] == "lesson-login-risk"


def test_no_memory_fallback_keeps_base_routing(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = _route(tmp_path)

    assert result.memory_context["enabled"] is False
    assert result.selected_skills() == [
        "bug_fix",
        "regression_test",
        "review_candidate",
    ]


def test_test_practice_boosts_regression_test(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    baseline = _route(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )

    tuned = _route(tmp_path)

    assert _route_scores(tuned)["regression_test"] > _route_scores(baseline)["regression_test"]
    regression_route = next(route for route in tuned.routes if route.skill_id == "regression_test")
    assert "project memory" in regression_route.reason


def test_avoid_pattern_boosts_review_candidate_and_adds_warning(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    baseline = _route(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-avoid-broad-auth-refactor",
                kind="avoid_pattern",
                text="Avoid broad auth refactors unless integration tests are selected.",
                tags=["auth", "refactor", "risk"],
            )
        ],
    )

    tuned = _route(tmp_path)

    assert _route_scores(tuned)["review_candidate"] > _route_scores(baseline)["review_candidate"]
    assert any("Remembered risk" in item for item in tuned.safety_warnings)


def test_missing_evidence_adds_next_action(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-missing-auth-evidence",
                kind="missing_evidence",
                text="Core auth evidence was missing in previous runs.",
                tags=["auth", "evidence"],
            )
        ],
    )

    result = _route(tmp_path)

    assert any(
        "Collect missing evidence" in item
        for item in result.memory_context["next_actions"]
    )


def test_unavailable_skill_warning_is_recorded(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    skills_path = tmp_path / ".cambrian" / "skills.yaml"
    skills_payload = _read_yaml(skills_path)
    skills_payload["recommended_skills"] = [
        {
            "id": "bug_fix",
            "label": "Bug fix",
            "description": "Diagnose and patch small defects with related tests.",
        }
    ]
    skills_payload["selection"]["default"] = ["bug_fix"]
    skills_path.write_text(
        yaml.safe_dump(skills_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests"],
            )
        ],
    )

    result = _route(tmp_path)

    assert any("현재 설정에 없습니다" in item for item in result.safety_warnings)


def test_request_artifact_includes_memory_context(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )

    result = ProjectRunPreparer().prepare(tmp_path, REQUEST_TEXT)
    request_payload = _read_yaml(tmp_path / result.request_path)

    assert result.memory_context["enabled"] is True
    assert request_payload["memory_context"]["enabled"] is True
    assert request_payload["memory_context"]["relevant_lessons"][0]["lesson_id"] == "lesson-auth-tests-before-login-patches"


def test_do_output_includes_remembered(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )

    proc = _run_cli(["do", REQUEST_TEXT], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Remembered:" in proc.stdout
    assert "Run tests/test_auth.py before login-related patches." in proc.stdout


def test_memory_recommend_cli_smoke(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )

    proc = _run_cli(["memory", "recommend", REQUEST_TEXT], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Memory-aware recommendation" in proc.stdout
    assert "Relevant lessons:" in proc.stdout
    assert "Recommended skills:" in proc.stdout


def test_memory_recommend_json_output(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )

    proc = _run_cli(["memory", "recommend", REQUEST_TEXT, "--json"], cwd=tmp_path)
    payload = json.loads(proc.stdout)

    assert proc.returncode == 0, proc.stderr
    assert payload["memory_context"]["enabled"] is True
    assert payload["relevant_lessons"][0]["lesson_id"] == "lesson-auth-tests-before-login-patches"
    assert payload["routes"]


def test_memory_does_not_block_run(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-avoid-broad-auth-refactor",
                kind="avoid_pattern",
                text="Avoid broad auth refactors unless integration tests are selected.",
                tags=["auth", "refactor", "risk"],
            )
        ],
    )

    result = ProjectRunPreparer().prepare(tmp_path, REQUEST_TEXT)

    assert result.status == "draft"
    assert result.routing["execution_readiness"] == "needs_context"
    assert (tmp_path / result.request_path).exists()


def test_status_shows_memory_aware_routing(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )

    status = ProjectStatusReader().read(tmp_path)
    proc = _run_cli(["status"], cwd=tmp_path)

    assert status.memory["routing_enabled"] is True
    assert status.memory["lesson_count"] == 1
    assert "memory-aware routing: enabled" in proc.stdout


def test_memory_related_commands_are_read_only(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    lessons_path = _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests-before-login-patches",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests", "patch"],
            )
        ],
    )
    source_path = tmp_path / "src" / "auth.py"
    before_source = _sha256(source_path)
    before_lessons = _sha256(lessons_path)

    ProjectRunPreparer().prepare(tmp_path, REQUEST_TEXT)
    _run_cli(["memory", "recommend", REQUEST_TEXT], cwd=tmp_path)
    _run_cli(["do", REQUEST_TEXT], cwd=tmp_path)

    assert _sha256(source_path) == before_source
    assert _sha256(lessons_path) == before_lessons
