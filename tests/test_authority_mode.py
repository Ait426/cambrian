from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_authority_status_defaults_to_proposal_only(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "authority", "status", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "proposal_only"
    assert payload["permissions"]["filesystem_write"] is False
    assert payload["permissions"]["command_exec"] is False
    assert payload["defaulted"] is True
    assert not (tmp_path / ".cambrian" / "authority.yaml").exists()


def test_authority_grant_and_revoke_write_profile_and_audit_log(tmp_path: Path) -> None:
    grant = run_cli(tmp_path, "authority", "grant", "--mode", "full-authority", "--json")

    assert grant.returncode == 0, grant.stderr
    grant_payload = json.loads(grant.stdout)
    assert grant_payload["mode"] == "full_authority"
    assert grant_payload["permissions"]["filesystem_write"] is True
    assert grant_payload["permissions"]["git_commit"] is True

    authority = yaml.safe_load((tmp_path / ".cambrian" / "authority.yaml").read_text(encoding="utf-8"))
    assert authority["mode"] == "full_authority"

    revoke = run_cli(tmp_path, "authority", "revoke", "--json")
    assert revoke.returncode == 0, revoke.stderr
    revoke_payload = json.loads(revoke.stdout)
    assert revoke_payload["mode"] == "proposal_only"
    assert revoke_payload["permissions"]["filesystem_write"] is False

    log = yaml.safe_load((tmp_path / ".cambrian" / "evidence" / "authority_log.yaml").read_text(encoding="utf-8"))
    assert len(log["events"]) >= 2
    assert log["events"][-1]["result"] == "revoked_to_proposal_only"
