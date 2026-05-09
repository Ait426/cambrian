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
        check=False,
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _install_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _activate_seed_pack(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pack", "activate", "auth-bug-core")
    assert result.returncode == 0, result.stderr


def _python_pytest_auth_project(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def login():\n    return True\n", encoding="utf-8")
    test_file.write_text("def test_login():\n    assert True\n", encoding="utf-8")


def test_start_with_active_pack_creates_job(tmp_path: Path) -> None:
    _python_pytest_auth_project(tmp_path)
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    payload = json.loads(result.stdout)
    job = payload["job"]

    assert result.returncode == 0, result.stderr
    assert job["pack_id"] == "auth-bug-core"
    assert job["status"] == "waiting_for_ai_reply"
    assert job["linked_bridge_packet_ref"]
    assert "cambrian pack job-paste" in job["next_command"]
    assert (tmp_path / ".cambrian" / "packs" / "jobs" / "latest.yaml").exists()
    assert (tmp_path / job["linked_bridge_packet_ref"]).exists()


def test_start_with_explicit_pack_without_active_pack(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "start", "--pack", "auth-bug-core", "로그인 에러 수정해", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["job"]["pack_id"] == "auth-bug-core"
    assert payload["job"]["status"] == "waiting_for_ai_reply"
    assert not (tmp_path / ".cambrian" / "install" / "active_pack.yaml").exists()


def test_start_without_pack_helpful_error(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pack", "start", "로그인 에러 수정해")

    assert result.returncode != 0
    assert "No active pack is selected" in result.stderr
    assert "cambrian pack activate auth-bug-core" in result.stderr


def test_readiness_blocked_prevents_start(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    (tmp_path / ".cambrian" / "templates" / "templates.yaml").unlink()

    result = _cli(tmp_path, "pack", "start", "--pack", "auth-bug-core", "로그인 에러 수정해", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode != 0
    assert payload["job"]["status"] == "blocked"
    assert payload["job"]["readiness_status"] == "blocked"
    assert not (tmp_path / ".cambrian" / "packs" / "jobs").exists()
    assert not (tmp_path / ".cambrian" / "bridge" / "packets").exists()


def test_partial_readiness_warns_but_proceeds(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["job"]["readiness_status"] == "partial"
    assert any("readiness is partial" in warning for warning in payload["warnings"])
    assert payload["job"]["linked_bridge_packet_ref"]


def test_job_show_works(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    start = _cli(tmp_path, "pack", "start", "로그인 에러 수정해")
    assert start.returncode == 0, start.stderr

    result = _cli(tmp_path, "pack", "job-show", "latest")

    assert result.returncode == 0, result.stderr
    assert "Pack Job" in result.stdout
    assert "auth-bug-core" in result.stdout
    assert "Bridge packet:" in result.stdout


def test_job_next_works(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    start = _cli(tmp_path, "pack", "start", "로그인 에러 수정해")
    assert start.returncode == 0, start.stderr

    result = _cli(tmp_path, "pack", "job-next", "latest")

    assert result.returncode == 0, result.stderr
    assert "Pack Job Next" in result.stdout
    assert "cambrian pack job-paste" in result.stdout
    assert "cambrian bridge paste --packet" in result.stdout


def test_usage_event_recorded(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    payload = json.loads(result.stdout)
    event_ref = payload["job"]["usage_event_ref"]
    event = _read_yaml(tmp_path / event_ref)

    assert result.returncode == 0, result.stderr
    assert event["event_kind"] == "used"
    assert event["surface_kind"] == "pack_start"
    assert event["linked_bridge_packet_ref"] == payload["job"]["linked_bridge_packet_ref"]
    assert event["linked_request_ref"].startswith(".cambrian/packs/jobs/")


def test_bridge_packet_includes_pack_context(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "start", "로그인 에러 수정해", "--json")
    payload = json.loads(result.stdout)
    packet = _read_yaml(tmp_path / payload["job"]["linked_bridge_packet_ref"])
    context = packet["active_pack_context"]

    assert result.returncode == 0, result.stderr
    assert context["pack_id"] == "auth-bug-core"
    assert context["team"] == "auth-bug-team"
    assert context["template"] == "auth-bug-template"
    assert context["lane_label"] == "Python + pytest + auth/login bug fixes"
    assert context["pack_job_id"] == payload["job"]["job_id"]


def test_pack_start_does_not_mutate_source_or_call_apply(tmp_path: Path) -> None:
    _python_pytest_auth_project(tmp_path)
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)

    result = _cli(tmp_path, "pack", "start", "로그인 에러 수정해")

    assert result.returncode == 0, result.stderr
    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
    assert not (tmp_path / ".cambrian" / "adoption").exists()
    assert not (tmp_path / ".cambrian" / "templates" / "bootstrap_record.yaml").exists()
    assert not (tmp_path / ".cambrian" / "sessions").exists()


def test_docs_mention_pack_start_flow() -> None:
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "product" / "06_PACKS_AND_INSTALL.md",
        ROOT / "docs" / "product" / "07_EXECUTION_LOOPS.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs)

    assert 'cambrian pack start "로그인 에러 수정해"' in text
    assert "cambrian pack job-paste" in text
    assert "cambrian bridge paste --packet" in text
    assert "does not call an ai provider" in text.lower()
    assert "mutate source code" in text.lower()
