from __future__ import annotations

import json
from pathlib import Path

from tests.test_harness_engineer_design import pass_engineering_gate, prepare_engineering_project, run_cli


def test_harness_engineer_dry_run_selects_agents_and_skills_without_job(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    design = run_cli(tmp_path, "harness", "engineer", "design", "--json")
    assert design.returncode == 0
    review = run_cli(tmp_path, "harness", "engineer", "review", "--json")
    assert review.returncode == 0

    result = run_cli(tmp_path, "harness", "engineer", "dry-run", "로그인 문제 봐줘", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert "auth-flow-investigator" in payload["selected_agents"]
    assert "regression-test-guardian" in payload["selected_agents"]
    assert "trace-auth-flow" in payload["selected_skills"]
    assert "propose-safe-patch" in payload["selected_skills"]
    assert "job_id" not in payload
    assert not (tmp_path / ".cambrian" / "jobs").exists()
    assert not (tmp_path / ".cambrian" / "packs" / "jobs").exists()


def test_pass_engineering_gate_helper(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)

    _, review, dry_run = pass_engineering_gate(tmp_path)

    assert review["status"] == "ready_for_dry_run"
    assert dry_run["status"] == "ready_for_install"
