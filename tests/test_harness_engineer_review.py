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


def test_harness_engineer_review_blocks_missing_meta_harness_contract(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0
    candidate_path = tmp_path / ".cambrian" / "engineering" / "design_candidate.yaml"
    candidate = yaml.safe_load(candidate_path.read_text(encoding="utf-8"))
    candidate.pop("domain_spec")
    candidate.pop("evaluator_contract")
    candidate.pop("candidate_lineage")
    candidate.pop("execution_boundary")
    candidate_path.write_text(yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result = run_cli(tmp_path, "harness", "engineer", "review", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "domain_spec is missing" in payload["blocking_issues"]
    assert "evaluator_contract is missing" in payload["blocking_issues"]
    assert "candidate_lineage is missing" in payload["blocking_issues"]
    assert "execution_boundary is missing" in payload["blocking_issues"]


def test_harness_engineer_review_blocks_ungrounded_important_paths(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    answers = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    payload = yaml.safe_load(answers.read_text(encoding="utf-8"))
    payload["answers"]["important_paths"] = ["backend/src/missingAuth.ts", "backend/tests/missingAuth.test.ts"]
    answers.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert run_cli(tmp_path, "harness", "interview", "answer", "--answers", ".cambrian/interview/answers.yaml", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0

    result = run_cli(tmp_path, "harness", "engineer", "review", "--json")

    assert result.returncode == 1
    review = json.loads(result.stdout)
    assert review["ok"] is False
    assert any("important_paths contain missing files" in issue for issue in review["blocking_issues"])
    assert "codebase_evidence is not grounded" in review["blocking_issues"]
