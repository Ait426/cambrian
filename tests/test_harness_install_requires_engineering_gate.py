from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_harness_engineer_design import pass_engineering_gate, prepare_engineering_project, run_cli


def test_harness_install_confirm_requires_engineering_gate(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)

    result = run_cli(tmp_path, "harness", "install", "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "engineering_gate_not_passed"
    assert any("design_candidate.yaml is missing" in error for error in payload["errors"])
    assert not (tmp_path / ".cambrian" / "harness.yaml").exists()


def test_harness_install_confirm_requires_dry_run(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    assert run_cli(tmp_path, "harness", "engineer", "design", "--json").returncode == 0
    assert run_cli(tmp_path, "harness", "engineer", "review", "--json").returncode == 0

    result = run_cli(tmp_path, "harness", "install", "--confirm", "--json")

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["error"] == "engineering_gate_not_passed"
    assert any("engineering dry-run is missing" in error for error in payload["errors"])


def test_harness_install_confirm_succeeds_after_review_and_dry_run(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)

    result = run_cli(tmp_path, "harness", "install", "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "installed"
    assert payload["no_agent_dispatched"] is True
    assert payload["authority_mode"] == "proposal_only"
    assert payload["authority_ref"] == ".cambrian/authority.yaml"
    assert ".cambrian/harness.yaml" in payload["installed_files"]
    assert ".cambrian/workforce.yaml" in payload["installed_files"]
    assert ".cambrian/authority.yaml" in payload["installed_files"]
    assert ".cambrian/engineering/design_candidate.yaml" in payload["installed_files"]
    assert ".cambrian/engineering/review.yaml" in payload["installed_files"]
    assert ".cambrian/engineering/dry_run.yaml" in payload["installed_files"]
    assert any(path.startswith(".cambrian/skills/") for path in payload["installed_files"])

    authority = yaml.safe_load((tmp_path / ".cambrian" / "authority.yaml").read_text(encoding="utf-8"))
    assert authority["mode"] == "proposal_only"
    assert authority["permissions"]["filesystem_write"] is False
    assert authority["permissions"]["command_exec"] is False


def test_harness_install_preserves_existing_full_authority(tmp_path: Path) -> None:
    prepare_engineering_project(tmp_path)
    pass_engineering_gate(tmp_path)
    grant = run_cli(tmp_path, "authority", "grant", "--mode", "full-authority", "--json")
    assert grant.returncode == 0, grant.stderr

    result = run_cli(tmp_path, "harness", "install", "--confirm", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["authority_mode"] == "full_authority"
    authority = yaml.safe_load((tmp_path / ".cambrian" / "authority.yaml").read_text(encoding="utf-8"))
    assert authority["mode"] == "full_authority"
    assert authority["permissions"]["filesystem_write"] is True
    assert authority["permissions"]["command_exec"] is True
