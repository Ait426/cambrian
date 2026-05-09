from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


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


def _init_project(project_root: Path) -> None:
    _prepare_python_project(project_root)
    result = ProjectInitializer().init(project_root)
    assert result.status == "initialized"


def _fit_harness(project_root: Path) -> None:
    proc = _run_cli(["harness", "fit"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr


def _write_suggestion_report(project_root: Path, suggestions: list[dict]) -> Path:
    report_path = project_root / ".cambrian" / "harness" / "evolution_suggestions.yaml"
    _write_yaml(
        report_path,
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-25T00:00:00+00:00",
            "report_id": "evolution-001",
            "project_name": "demo",
            "harness_id": "harness-demo",
            "mode": "board",
            "request": None,
            "suggestions": suggestions,
            "summary": {"total": len(suggestions), "next_commands": []},
            "warnings": [],
            "errors": [],
        },
    )
    return report_path


def _suggestion(*, suggestion_id: str, kind: str, target: str | None, summary: str) -> dict:
    return {
        "suggestion_id": suggestion_id,
        "kind": kind,
        "title": summary,
        "summary": summary,
        "confidence": 0.8,
        "priority": "high",
        "target": target,
        "reasons": ["테스트용 제안입니다"],
        "warnings": [],
        "evidence_refs": [".cambrian/harness/evolution_suggestions.yaml"],
        "next_commands": [],
    }


def test_accept_hire_agent_suggestion_equips_agent(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)
    _write_suggestion_report(
        tmp_path,
        [
            _suggestion(
                suggestion_id="suggest-hire-docs",
                kind="hire_agent",
                target="docs-update-agent",
                summary="Hire docs-update-agent into the current harness.",
            )
        ],
    )

    proc = _run_cli(["harness", "accept", "suggest-hire-docs"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    decisions = _read_yaml(tmp_path / ".cambrian" / "harness" / "decisions.yaml")
    profile = _read_yaml(tmp_path / ".cambrian" / "harness" / "profile.yaml")
    assert decisions["decisions"][0]["status"] == "accepted"
    assert decisions["decisions"][0]["operational_effect"]["type"] == "hire"
    assert "docs-update-agent" in profile["active_agents"]


def test_accept_fire_agent_suggestion_unequips_agent(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)
    _write_suggestion_report(
        tmp_path,
        [
            _suggestion(
                suggestion_id="suggest-fire-bugfix",
                kind="fire_agent",
                target="bug-fix-agent",
                summary="Fire bug-fix-agent from the current harness.",
            )
        ],
    )

    proc = _run_cli(["harness", "accept", "suggest-fire-bugfix"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    decisions = _read_yaml(tmp_path / ".cambrian" / "harness" / "decisions.yaml")
    profile = _read_yaml(tmp_path / ".cambrian" / "harness" / "profile.yaml")
    assert decisions["decisions"][0]["operational_effect"]["type"] == "fire"
    assert "bug-fix-agent" not in profile["active_agents"]


def test_accept_keep_and_strategic_decisions_store_overlay_only(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)
    project_before = (tmp_path / ".cambrian" / "project.yaml").read_text(encoding="utf-8")
    _write_suggestion_report(
        tmp_path,
        [
            _suggestion(
                suggestion_id="suggest-keep-bugfix",
                kind="keep_agent",
                target="bug-fix-agent",
                summary="Keep bug-fix-agent as part of the default harness team.",
            ),
            _suggestion(
                suggestion_id="suggest-test-practice",
                kind="strengthen_test_practice",
                target="auth_work",
                summary="Strengthen test-first practice for auth work.",
            ),
        ],
    )

    keep_proc = _run_cli(["harness", "accept", "suggest-keep-bugfix"], cwd=tmp_path)
    strategic_proc = _run_cli(
        ["harness", "accept", "suggest-test-practice", "--resolution", "테스트 우선 흐름 유지"],
        cwd=tmp_path,
    )

    assert keep_proc.returncode == 0, keep_proc.stderr
    assert strategic_proc.returncode == 0, strategic_proc.stderr
    decisions = _read_yaml(tmp_path / ".cambrian" / "harness" / "decisions.yaml")
    decision_by_id = {item["suggestion_id"]: item for item in decisions["decisions"]}
    assert decision_by_id["suggest-keep-bugfix"]["operational_effect"]["type"] == "keep"
    assert decision_by_id["suggest-test-practice"]["operational_effect"]["type"] == "none"
    assert (tmp_path / ".cambrian" / "project.yaml").read_text(encoding="utf-8") == project_before


def test_dismiss_suggestion_saves_without_operational_effect(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)
    _write_suggestion_report(
        tmp_path,
        [
            _suggestion(
                suggestion_id="suggest-dismiss-docs",
                kind="fire_agent",
                target="docs-update-agent",
                summary="Fire docs-update-agent from the current harness.",
            )
        ],
    )

    proc = _run_cli(
        ["harness", "dismiss", "suggest-dismiss-docs", "--resolution", "문서 작업을 곧 다시 할 예정"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    decisions = _read_yaml(tmp_path / ".cambrian" / "harness" / "decisions.yaml")
    assert decisions["decisions"][0]["status"] == "dismissed"
    assert decisions["decisions"][0]["operational_effect"]["applied"] is False


def test_missing_suggestion_is_blocked(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    proc = _run_cli(["harness", "accept", "missing-suggestion"], cwd=tmp_path)

    assert proc.returncode != 0
    assert "Suggestion not found" in proc.stderr
    assert "cambrian harness suggest" in proc.stderr


def test_harness_decisions_list_and_filter(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)
    _write_suggestion_report(
        tmp_path,
        [
            _suggestion(
                suggestion_id="suggest-accepted",
                kind="keep_agent",
                target="bug-fix-agent",
                summary="Keep bug-fix-agent as part of the default harness team.",
            ),
            _suggestion(
                suggestion_id="suggest-dismissed",
                kind="note_followup",
                target="note-001",
                summary="Follow up on clarify UX confusion before expanding staffing.",
            ),
        ],
    )
    assert _run_cli(["harness", "accept", "suggest-accepted"], cwd=tmp_path).returncode == 0
    assert _run_cli(["harness", "dismiss", "suggest-dismissed"], cwd=tmp_path).returncode == 0

    all_proc = _run_cli(["harness", "decisions"], cwd=tmp_path)
    accepted_proc = _run_cli(["harness", "decisions", "--status", "accepted"], cwd=tmp_path)

    assert all_proc.returncode == 0, all_proc.stderr
    assert "Harness Decisions" in all_proc.stdout
    assert "Accepted:" in all_proc.stdout
    assert "Dismissed:" in all_proc.stdout
    assert accepted_proc.returncode == 0, accepted_proc.stderr
    assert "Keep bug-fix-agent" in accepted_proc.stdout
    assert "Follow up on clarify UX confusion" not in accepted_proc.stdout


def test_status_and_harness_show_include_decision_summary(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)
    _write_suggestion_report(
        tmp_path,
        [
            _suggestion(
                suggestion_id="suggest-strategy",
                kind="increase_review_support",
                target="review-agent",
                summary="Increase review support for risky auth changes.",
            )
        ],
    )
    accept_proc = _run_cli(["harness", "accept", "suggest-strategy"], cwd=tmp_path)
    assert accept_proc.returncode == 0, accept_proc.stderr

    show_proc = _run_cli(["harness", "show"], cwd=tmp_path)
    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert show_proc.returncode == 0, show_proc.stderr
    assert "Harness decisions:" in show_proc.stdout
    assert "Accepted harness hints:" in show_proc.stdout
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Harness decisions:" in status_proc.stdout
    assert "Accepted harness hint:" in status_proc.stdout
