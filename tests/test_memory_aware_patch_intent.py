"""Cambrian memory-aware patch intent 테스트."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_continue import ProjectDoContinuationRunner
from engine.project_do import ProjectDoRunner
from engine.project_mode import ProjectInitializer
from engine.project_patch_intent import PatchIntentBuilder, PatchIntentFiller, PatchIntentStore


REQUEST_TEXT = "로그인 에러 수정해"


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
    ProjectInitializer().init(project_root)


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


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


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


def _write_lessons(project_root: Path, lessons: list[dict]) -> Path:
    path = project_root / ".cambrian" / "memory" / "lessons.yaml"
    _write_yaml(
        path,
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-23T00:00:00+00:00",
            "project_name": project_root.name,
            "lessons": lessons,
            "warnings": [],
            "errors": [],
        },
    )
    return path


def _write_overrides(project_root: Path, overrides: dict[str, dict]) -> Path:
    path = project_root / ".cambrian" / "memory" / "overrides.yaml"
    _write_yaml(
        path,
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-04-23T00:00:00+00:00",
            "overrides": overrides,
            "warnings": [],
            "errors": [],
        },
    )
    return path


def _write_hygiene(project_root: Path, items: list[dict]) -> Path:
    summary = {
        "total": len(items),
        "fresh": sum(1 for item in items if item["status"] == "fresh"),
        "watch": sum(1 for item in items if item["status"] == "watch"),
        "stale": sum(1 for item in items if item["status"] == "stale"),
        "conflicting": sum(1 for item in items if item["status"] == "conflicting"),
        "orphaned": sum(1 for item in items if item["status"] == "orphaned"),
        "suppressed": sum(1 for item in items if item["status"] == "suppressed"),
    }
    path = project_root / ".cambrian" / "memory" / "hygiene.yaml"
    _write_yaml(
        path,
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-23T00:00:00+00:00",
            "lessons_path": ".cambrian/memory/lessons.yaml",
            "overrides_path": ".cambrian/memory/overrides.yaml",
            "summary": summary,
            "items": items,
            "warnings": [],
            "errors": [],
        },
    )
    return path


def _hygiene_item(lesson_id: str, *, status: str) -> dict:
    return {
        "lesson_id": lesson_id,
        "text": lesson_id,
        "kind": "successful_pattern",
        "status": status,
        "severity": "warning",
        "reasons": [f"{status} lesson"],
        "suggested_actions": [],
        "pinned": False,
        "suppressed": status == "suppressed",
        "confidence": 0.8,
        "evidence_count": 1,
        "source_refs": [".cambrian/adoptions/adoption_001.json"],
        "missing_source_refs": [],
        "referenced_paths": [],
        "missing_referenced_paths": [],
        "conflict_refs": [],
        "warnings": [],
    }


def _write_diagnosis_report(project_root: Path) -> Path:
    report_path = project_root / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    _write_json(
        report_path,
        {
            "run_id": "brain-001",
            "user_request": REQUEST_TEXT,
            "diagnostics": {
                "enabled": True,
                "mode": "read_only",
                "inspected_files": [
                    {
                        "path": "src/auth.py",
                        "sha256": "dummy",
                        "size_bytes": 48,
                        "truncated": False,
                        "preview": "def normalize_username(username: str) -> str:\\n    return username\\n",
                    }
                ],
                "related_tests": ["tests/test_auth.py"],
                "test_results": {
                    "passed": 0,
                    "failed": 1,
                    "skipped": 0,
                    "tests_executed": ["tests/test_auth.py"],
                },
            },
        },
    )
    return report_path


def _build_form(project_root: Path):
    return PatchIntentBuilder().build_from_diagnosis(_write_diagnosis_report(project_root), project_root)


def _build_and_save_intent(project_root: Path) -> Path:
    form = _build_form(project_root)
    intent_path = project_root / ".cambrian" / "patch_intents" / "patch_intent_auth.yaml"
    PatchIntentStore().save(form, intent_path)
    return intent_path


def test_successful_pattern_boosts_old_text_candidate(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-minimal-auth-patch-success",
                kind="successful_pattern",
                text="Minimal auth patches worked well for return username normalization.",
                tags=["auth", "return", "username"],
            )
        ],
    )

    form = _build_form(tmp_path)

    candidate = form.old_text_candidates[0]
    assert candidate.memory_boosted is True
    assert candidate.memory_reasons


def test_test_practice_adds_suggested_test_guidance(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
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

    form = _build_form(tmp_path)

    assert form.memory_guidance["suggested_tests"] == ["tests/test_auth.py"]
    assert form.memory_guidance["remembered"]


def test_avoid_pattern_adds_warning_without_removing_candidate(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-avoid-broad-auth-refactor",
                kind="avoid_pattern",
                text="Avoid broad auth refactors unless integration tests are selected.",
                tags=["auth", "refactor"],
            )
        ],
    )

    form = _build_form(tmp_path)

    assert form.old_text_candidates
    assert form.memory_guidance["warnings"]
    assert form.old_text_candidates[0].text == "return username"


def test_suppressed_and_stale_lessons_are_ignored(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-suppressed",
                kind="successful_pattern",
                text="Minimal auth patches worked well for return username normalization.",
                tags=["auth", "return"],
            ),
            _lesson(
                "lesson-stale",
                kind="successful_pattern",
                text="Login return username patch was successful before.",
                tags=["auth", "return"],
            ),
        ],
    )
    _write_overrides(
        tmp_path,
        {
            "lesson-suppressed": {
                "pinned": False,
                "suppressed": True,
                "note": None,
                "updated_at": "2026-04-23T00:00:00+00:00",
                "updated_by": "user",
            }
        },
    )
    _write_hygiene(tmp_path, [_hygiene_item("lesson-stale", status="stale")])

    form = _build_form(tmp_path)

    assert not any(candidate.memory_boosted for candidate in form.old_text_candidates)
    assert form.memory_guidance["omitted"]["suppressed_count"] >= 1
    assert form.memory_guidance["omitted"]["stale_count"] >= 1


def test_pinned_fresh_lesson_is_shown_first(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-secondary",
                kind="successful_pattern",
                text="Auth patches succeeded with focused line edits.",
                tags=["auth"],
            ),
            _lesson(
                "lesson-pinned",
                kind="test_practice",
                text="Run tests/test_auth.py before login-related patches.",
                tags=["auth", "tests"],
            ),
        ],
    )
    _write_overrides(
        tmp_path,
        {
            "lesson-pinned": {
                "pinned": True,
                "suppressed": False,
                "note": "아직 중요함",
                "updated_at": "2026-04-23T00:00:00+00:00",
                "updated_by": "user",
            }
        },
    )

    form = _build_form(tmp_path)

    assert form.memory_guidance["remembered"][0]["lesson_id"] == "lesson-pinned"


def test_patch_intent_artifact_contains_memory_guidance_and_cli_output(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
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
    diagnosis_path = _write_diagnosis_report(tmp_path)

    result = _run_cli(["patch", "intent", str(diagnosis_path)], tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Remembered:" in result.stdout
    intent_files = list((tmp_path / ".cambrian" / "patch_intents").glob("patch_intent_*.yaml"))
    assert intent_files
    payload = _read_yaml(intent_files[-1])
    assert payload["memory_guidance"]["enabled"] is True


def test_intent_fill_preserves_memory_guidance(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
    _write_lessons(
        tmp_path,
        [
            _lesson(
                "lesson-minimal-auth-patch-success",
                kind="successful_pattern",
                text="Minimal auth patches worked well for return username normalization.",
                tags=["auth", "return", "username"],
            )
        ],
    )
    intent_path = _build_and_save_intent(tmp_path)

    form = PatchIntentFiller().fill(
        intent_path,
        old_choice="old-1",
        new_text="return username.strip().lower()",
    )

    assert form.memory_guidance["enabled"] is True
    saved = PatchIntentStore().load(intent_path)
    assert saved.memory_guidance["enabled"] is True


def test_patch_propose_from_intent_preserves_memory_refs(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
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
    intent_path = _build_and_save_intent(tmp_path)
    PatchIntentFiller().fill(
        intent_path,
        old_choice="old-1",
        new_text="return username.strip().lower()",
    )

    result = _run_cli(["patch", "propose", "--from-intent", str(intent_path)], tmp_path)

    assert result.returncode == 0, result.stderr
    proposal_files = list((tmp_path / ".cambrian" / "patches").glob("patch_proposal_*.yaml"))
    assert proposal_files
    proposal_payload = _read_yaml(proposal_files[-1])
    assert proposal_payload["memory_guidance_ref"]["remembered"]


def test_no_memory_fallback_still_builds_intent(tmp_path: Path) -> None:
    _prepare_project(tmp_path)

    form = _build_form(tmp_path)

    assert form.status == "draft"
    assert form.memory_guidance["enabled"] is False


def test_do_continue_diagnosed_stage_uses_memory_guidance(tmp_path: Path) -> None:
    _prepare_project(tmp_path)
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
    diagnosed = ProjectDoRunner().run(
        REQUEST_TEXT,
        tmp_path,
        {
            "sources": ["src/auth.py"],
            "tests": ["tests/test_auth.py"],
            "execute": True,
        },
    )

    continued = ProjectDoContinuationRunner().run(tmp_path, {"session": diagnosed.session_id})

    intent_path = tmp_path / str(continued.artifacts["patch_intent_path"])
    payload = _read_yaml(intent_path)
    assert payload["memory_guidance"]["enabled"] is True
