"""프로젝트 memory hygiene 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_memory_hygiene import (
    MemoryHygieneChecker,
    MemoryHygieneStore,
    default_memory_hygiene_path,
)
from engine.project_mode import ProjectInitializer, ProjectRunPreparer, ProjectStatusReader, render_status_summary
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


def _write_overrides(project_root: Path, overrides: dict[str, dict]) -> Path:
    path = project_root / ".cambrian" / "memory" / "overrides.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "updated_at": "2026-04-23T00:00:00+00:00",
        "overrides": overrides,
        "warnings": [],
        "errors": [],
    }
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _lesson(
    lesson_id: str,
    *,
    kind: str,
    text: str,
    source_refs: list[str] | None = None,
    tags: list[str] | None = None,
    confidence: float = 0.8,
    evidence_count: int = 1,
) -> dict:
    return {
        "lesson_id": lesson_id,
        "kind": kind,
        "text": text,
        "confidence": confidence,
        "source_refs": list(source_refs or []),
        "evidence_count": evidence_count,
        "tags": list(tags or []),
        "created_at": "2026-04-23T00:00:00+00:00",
        "updated_at": "2026-04-23T00:00:00+00:00",
        "status": "active",
    }


def _write_adoption(project_root: Path, name: str, *, target_path: str, human_reason: str) -> Path:
    path = project_root / ".cambrian" / "adoptions" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "adoption_id": name.replace(".json", ""),
        "target_path": target_path,
        "human_reason": human_reason,
        "post_apply_tests": {"passed": 1, "failed": 0},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _checker(project_root: Path):
    return MemoryHygieneChecker().check(project_root)


def _save_hygiene(project_root: Path):
    report = _checker(project_root)
    path = default_memory_hygiene_path(project_root)
    MemoryHygieneStore().save(report, path)
    return report, path


def _route(project_root: Path, request: str = REQUEST_TEXT):
    cambrian_dir = project_root / ".cambrian"
    project_cfg = _read_yaml(cambrian_dir / "project.yaml")
    rules = _read_yaml(cambrian_dir / "rules.yaml")
    skills = _read_yaml(cambrian_dir / "skills.yaml")
    profile = _read_yaml(cambrian_dir / "profile.yaml")
    return ProjectSkillRouter().route(
        request,
        project_cfg,
        rules,
        skills,
        profile,
        explicit_options={"project_root": str(project_root)},
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fresh_lesson(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded with tests",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
                evidence_count=2,
            )
        ],
    )

    report = _checker(tmp_path)

    assert report.items[0].status == "fresh"


def test_missing_referenced_path_is_stale(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    (tmp_path / "tests" / "test_auth.py").unlink()
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded with tests",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
            )
        ],
    )

    report = _checker(tmp_path)
    item = report.items[0]

    assert item.status == "stale"
    assert "tests/test_auth.py" in item.missing_referenced_paths


def test_missing_all_source_refs_is_orphaned(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-orphan",
                kind="successful_pattern",
                text="Small patch strategy worked for auth fixes.",
                source_refs=[".cambrian/adoptions/missing.json"],
                tags=["auth"],
            )
        ],
    )

    report = _checker(tmp_path)

    assert report.items[0].status == "orphaned"


def test_low_confidence_single_evidence_is_watch(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-watch",
                kind="successful_pattern",
                text="Prefer small auth patches first.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth"],
                confidence=0.6,
                evidence_count=1,
            )
        ],
    )

    report = _checker(tmp_path)

    assert report.items[0].status == "watch"


def test_suppressed_override_status(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-suppressed",
                kind="avoid_pattern",
                text="Avoid broad auth refactors unless integration tests are selected.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "refactor"],
            )
        ],
    )
    _write_overrides(
        tmp_path,
        {
            "lesson-suppressed": {
                "pinned": False,
                "suppressed": True,
                "note": "old lesson",
                "updated_at": "2026-04-23T00:00:00+00:00",
                "updated_by": "user",
            }
        },
    )

    report = _checker(tmp_path)

    assert report.items[0].status == "suppressed"
    assert report.items[0].suggested_actions == ["Run: cambrian memory unsuppress lesson-suppressed"]


def test_pinned_stale_becomes_watch(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    (tmp_path / "tests" / "test_auth.py").unlink()
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-pinned",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
            )
        ],
    )
    _write_overrides(
        tmp_path,
        {
            "lesson-pinned": {
                "pinned": True,
                "suppressed": False,
                "note": "still important",
                "updated_at": "2026-04-23T00:00:00+00:00",
                "updated_by": "user",
            }
        },
    )

    report = _checker(tmp_path)
    item = report.items[0]

    assert item.status == "watch"
    assert any("Pinned lesson has hygiene issue" in reason for reason in item.reasons)


def test_conflict_avoid_vs_adopted(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_refactor.json",
        target_path="src/auth.py",
        human_reason="auth refactor succeeded with integration tests",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-avoid-refactor",
                kind="avoid_pattern",
                text="Avoid broad auth refactors unless integration tests are selected.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "refactor", "risk"],
                evidence_count=1,
            )
        ],
    )

    report = _checker(tmp_path)
    item = report.items[0]

    assert item.status == "conflicting"
    assert f".cambrian/adoptions/{adoption.name}" in item.conflict_refs


def test_hygiene_report_saved_by_cli(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
            )
        ],
    )

    proc = _run_cli(["memory", "hygiene"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    hygiene_path = default_memory_hygiene_path(tmp_path)
    assert hygiene_path.exists()
    payload = _read_yaml(hygiene_path)
    assert payload["summary"]["fresh"] == 1


def test_memory_list_and_show_display_hygiene(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    (tmp_path / "tests" / "test_auth.py").unlink()
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
            )
        ],
    )
    _save_hygiene(tmp_path)

    list_proc = _run_cli(["memory", "list"], cwd=tmp_path)
    show_proc = _run_cli(["memory", "show", "lesson-auth-tests"], cwd=tmp_path)

    assert "hygiene: stale" in list_proc.stdout
    assert "status: stale" in show_proc.stdout


def test_status_shows_hygiene_summary(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    (tmp_path / "tests" / "test_auth.py").unlink()
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
            )
        ],
    )
    _save_hygiene(tmp_path)

    status = ProjectStatusReader().read(tmp_path)
    output = render_status_summary(status)

    assert "Memory hygiene:" in output
    assert "stale" in output


def test_routing_excludes_stale_and_records_omitted(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    (tmp_path / "tests" / "test_auth.py").unlink()
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests", "patch"],
            )
        ],
    )
    _save_hygiene(tmp_path)

    result = _route(tmp_path)
    hygiene = result.memory_context.get("hygiene", {})

    assert result.memory_context["relevant_lessons"] == []
    assert hygiene["enabled"] is True
    assert hygiene["omitted_due_to_hygiene"][0]["lesson_id"] == "lesson-auth-tests"
    assert hygiene["omitted_due_to_hygiene"][0]["status"] == "stale"


def test_watch_lesson_adds_warning(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-watch",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests", "patch"],
                confidence=0.6,
                evidence_count=1,
            )
        ],
    )
    _save_hygiene(tmp_path)

    result = _route(tmp_path)

    assert result.memory_context["relevant_lessons"]
    assert any("needs review" in item for item in result.safety_warnings)


def test_memory_hygiene_json_output(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
            )
        ],
    )

    proc = _run_cli(["memory", "hygiene", "--json"], cwd=tmp_path)
    payload = json.loads(proc.stdout)

    assert payload["summary"]["fresh"] == 1
    assert payload["items"][0]["lesson_id"] == "lesson-auth-tests"


def test_memory_hygiene_paths_are_read_only(tmp_path: Path) -> None:
    _prepare_login_fixture(tmp_path)
    ProjectInitializer().init(tmp_path)
    adoption = _write_adoption(
        tmp_path,
        "adoption_auth.json",
        target_path="src/auth.py",
        human_reason="auth patch succeeded",
    )
    lessons_path = _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-auth-tests",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                source_refs=[f".cambrian/adoptions/{adoption.name}"],
                tags=["auth", "tests"],
            )
        ],
    )
    source_path = tmp_path / "src" / "auth.py"
    before_source = _sha256(source_path)
    before_lessons = _sha256(lessons_path)

    _run_cli(["memory", "hygiene"], cwd=tmp_path)
    _run_cli(["memory", "list"], cwd=tmp_path)
    _route(tmp_path)

    assert _sha256(source_path) == before_source
    assert _sha256(lessons_path) == before_lessons
