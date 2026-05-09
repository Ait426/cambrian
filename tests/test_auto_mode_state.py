from __future__ import annotations

import json
from pathlib import Path

import yaml

from tests.test_authority_mode import run_cli


def test_auto_init_creates_state_and_organization(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "authority", "grant", "--mode", "full-authority", "--json").returncode == 0

    result = run_cli(tmp_path, "auto", "init", "--goal", "제품을 설치형 RC로 완성", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["state"] == "PRODUCT_CHARTER"
    assert payload["authority"] == "full_authority"

    state = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "state.yaml").read_text(encoding="utf-8"))
    assert state["goal"] == "제품을 설치형 RC로 완성"
    assert state["paused"] is False

    organization = yaml.safe_load((tmp_path / ".cambrian" / "auto" / "organization.yaml").read_text(encoding="utf-8"))
    role_ids = [item["id"] for item in organization["organization"]["roles"]]
    assert "ceo-agent" in role_ids
    assert "cto-agent" in role_ids
    assert "coo-agent" in role_ids
    assert "pm-agent" in role_ids
    assert "engineering-agent" in role_ids
    assert "qa-agent" in role_ids
    assert "release-manager-agent" in role_ids


def test_auto_status_reports_not_initialized(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "auto", "status", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "not_initialized"
    assert payload["authority"] == "proposal_only"
