from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_job_complete_evidence import complete_latest_job, prepare_custom_harness_project, run_cli


def _expand_outcomes(root: Path, count: int = 10) -> None:
    outcomes_path = root / ".cambrian" / "evidence" / "outcomes.yaml"
    payload = yaml.safe_load(outcomes_path.read_text(encoding="utf-8"))
    seed = dict(payload["outcomes"][0])
    payload["outcomes"] = [{**seed, "job_id": f"job-maturity-{index:03d}"} for index in range(count)]
    outcomes_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_skill_evolution_extends_trace_auth_token_flow(tmp_path: Path) -> None:
    prepare_custom_harness_project(tmp_path)
    complete_latest_job(tmp_path)
    _expand_outcomes(tmp_path)
    proposed = run_cli(tmp_path, "evolve", "propose", "--json")
    proposal_id = json.loads(proposed.stdout)["proposal_id"]
    preview = run_cli(tmp_path, "evolve", "preview", proposal_id, "--json")
    assert preview.returncode == 0, preview.stderr

    applied = run_cli(tmp_path, "evolve", "apply", proposal_id, "--confirm", "--json")
    assert applied.returncode == 0, applied.stderr

    skill_path = tmp_path / ".cambrian" / "skills" / "trace-auth-token-flow.yaml"
    skill = yaml.safe_load(skill_path.read_text(encoding="utf-8"))
    assert skill["type"] == "generated_skill"
    assert any("refresh token" in step for step in skill["procedure"])
    assert "refresh token mismatch" in skill["when_to_use"]
    assert any("refresh token" in item for item in skill["validation"]["required"])
