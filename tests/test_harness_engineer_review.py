from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_harness_engineer_design import make_typescript_auth_project, prepare_engineering_project, run_cli


def test_harness_engineer_review_passes_good_candidate(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0

    result = run_cli(tmp_path, "harness", "engineer", "review", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "ready_for_dry_run"
    assert payload["quality_score"] >= 70
    assert payload["blocking_issues"] == []
    assert payload["next_command"].startswith("cambrian harness engineer dry-run")


def test_harness_engineer_review_reports_missing_info(tmp_path: Path) -> None:
    make_typescript_auth_project(tmp_path)
    assert run_cli(tmp_path, "project", "scan", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "interview", "start", "--json").returncode == 0
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "Investigate auth bugs.",
                    "forbidden_scope": ["no automatic patch apply"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0

    result = run_cli(tmp_path, "harness", "engineer", "review", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "needs_more_info"
    assert "test_command is missing" in payload["blocking_issues"]
    assert "change_policy is missing" in payload["blocking_issues"]
    assert {question["id"] for question in payload["followup_questions"]} >= {"test_command", "change_policy"}
