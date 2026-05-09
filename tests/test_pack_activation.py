from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=False,
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _install_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _activate_seed_pack(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    result = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert result.returncode == 0, result.stderr
    return result


def test_activate_installed_pack_records_context(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)

    result = _activate_seed_pack(tmp_path)
    active_path = tmp_path / ".cambrian" / "install" / "active_pack.yaml"
    active = _read_yaml(active_path)

    assert "Pack activated." in result.stdout
    assert active["pack_id"] == "auth-bug-core"
    assert active["status"] == "active"
    assert active["workers"] == ["bug-fix-agent", "regression-test-agent", "review-agent"]
    assert active["default_team"] == "auth-bug-team"
    assert active["default_template"] == "auth-bug-template"
    assert active["default_workset"] == "auth-bug-workset"
    assert active["lane_id"] == "python-pytest-auth-bug-core"


def test_cannot_activate_uninstalled_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pack", "activate", "auth-bug-core")

    assert result.returncode != 0
    assert "Pack is not installed" in result.stderr
    assert "cambrian install pack auth-bug-core" in result.stderr
    assert not (tmp_path / ".cambrian" / "install" / "active_pack.yaml").exists()


def test_active_command_shows_context(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "active")

    assert result.returncode == 0, result.stderr
    assert "Active Pack" in result.stdout
    assert "auth-bug-core" in result.stdout
    assert "auth-bug-team" in result.stdout
    assert "auth-bug-template" in result.stdout
    assert "auth-bug-workset" in result.stdout


def test_pack_next_guide_for_auth_bug_core(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "next")

    assert result.returncode == 0, result.stderr
    assert "Pack Next" in result.stdout
    assert 'cambrian pack start "로그인 에러 수정해"' in result.stdout
    assert "cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml" in result.stdout
    assert "cambrian pack job-validate <job-id>" in result.stdout
    assert "cambrian pack proof auth-bug-core" in result.stdout


def test_deactivate_keeps_installed_pack_index(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "deactivate")
    active = _read_yaml(tmp_path / ".cambrian" / "install" / "active_pack.yaml")
    installed = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")

    assert result.returncode == 0, result.stderr
    assert "Pack deactivated." in result.stdout
    assert active["status"] == "inactive"
    assert installed["packs"][0]["pack_id"] == "auth-bug-core"


def test_status_shows_active_pack_summary(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "status")

    assert result.returncode == 0, result.stderr
    assert "Active pack:" in result.stdout
    assert "auth-bug-core" in result.stdout
    assert 'next: cambrian pack start "로그인 에러 수정해"' in result.stdout


def test_bridge_prepare_surfaces_active_pack_context(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "bridge", "prepare", "로그인 에러 수정해", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["packet"]["active_pack_context"]["pack_id"] == "auth-bug-core"
    assert payload["packet"]["active_pack_context"]["team"] == "auth-bug-team"
    packet_path = tmp_path / payload["saved_path"]
    saved_packet = _read_yaml(packet_path)
    assert saved_packet["active_pack_context"]["template"] == "auth-bug-template"


def test_do_surfaces_active_pack_and_metrics_context(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    init = _cli(tmp_path, "init", "--non-interactive")
    assert init.returncode == 0, init.stderr

    result = _cli(tmp_path, "do", "로그인 에러 수정해")

    assert result.returncode == 0, result.stderr
    assert "Active pack context:" in result.stdout
    assert "auth-bug-core" in result.stdout
    assert "fit     : in-lane" in result.stdout
    sessions = sorted((tmp_path / ".cambrian" / "sessions").glob("do_session_*.yaml"))
    assert sessions
    session = _read_yaml(sessions[-1])
    assert session["metrics_context"]["active_pack_id"] == "auth-bug-core"
    assert session["metrics_context"]["active_pack_lane"] == "python-pytest-auth-bug-core"
    assert session["metrics_context"]["reused_context"]["pack"] is True


def test_activation_does_not_auto_apply_or_bootstrap(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")

    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    active = _cli(tmp_path, "pack", "active")
    next_result = _cli(tmp_path, "pack", "next")

    assert active.returncode == 0, active.stderr
    assert next_result.returncode == 0, next_result.stderr
    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
    assert not (tmp_path / ".cambrian" / "templates" / "current_template.yaml").exists()
    assert not (tmp_path / ".cambrian" / "templates" / "bootstrap_record.yaml").exists()
    assert not (tmp_path / ".cambrian" / "sessions").exists()
