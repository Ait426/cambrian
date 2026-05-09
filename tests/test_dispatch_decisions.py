from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import (
    _make_importable_passport,
    _prepare_target_project,
    _read_yaml,
    _run_cli,
)


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _import_agent(project_root: Path, tmp_path: Path, *, agent_id: str, requires_test: bool = False) -> None:
    passport_path = _make_importable_passport(
        tmp_path / f"{agent_id}.passport.yaml",
        agent_id=agent_id,
        role_id="bug_fix",
        requires_test=requires_test,
    )
    proc = _run_cli(["agent", "import", str(passport_path)], cwd=project_root)
    assert proc.returncode == 0, proc.stderr


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dispatch_accept_hire_decision_equips_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _import_agent(project_root, tmp_path, agent_id="portable-auth-bug-agent")
    board_proc = _run_cli(["dispatch", "board", "--save"], cwd=project_root)
    assert board_proc.returncode == 0, board_proc.stderr

    proc = _run_cli(
        ["dispatch", "accept", "portable-auth-bug-agent", "--decision", "hire", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["status"] == "accepted"
    assert payload["decision"]["decision_kind"] == "hire"
    assert payload["decision"]["operational_effect"]["applied"] is True
    decisions_path = project_root / ".cambrian" / "agents" / "staffing_decisions.yaml"
    assert decisions_path.exists()
    profile = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")
    assert "portable-auth-bug-agent" in profile["active_agents"]


def test_dispatch_accept_fire_decision_unequips_agent(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)

    proc = _run_cli(["dispatch", "accept", "bug-fix-agent", "--decision", "fire", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["decision_kind"] == "fire"
    assert payload["decision"]["operational_effect"]["type"] == "fire"
    profile = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")
    assert "bug-fix-agent" not in profile["active_agents"]


def test_dispatch_accept_keep_and_strategy_overlay(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)

    keep_proc = _run_cli(["dispatch", "accept", "bug-fix-agent", "--decision", "keep", "--json"], cwd=project_root)
    support_proc = _run_cli(["dispatch", "accept", "review-agent", "--decision", "prefer_support", "--json"], cwd=project_root)

    assert keep_proc.returncode == 0, keep_proc.stderr
    assert support_proc.returncode == 0, support_proc.stderr
    keep_payload = json.loads(keep_proc.stdout)
    support_payload = json.loads(support_proc.stdout)
    assert keep_payload["decision"]["operational_effect"]["applied"] is False
    assert support_payload["decision"]["decision_kind"] == "prefer_support"
    assert support_payload["decision"]["operational_effect"]["type"] == "none"


def test_dispatch_dismiss_decision_has_no_operational_effect(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    before = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")["active_agents"]

    proc = _run_cli(
        ["dispatch", "dismiss", "docs-update-agent", "--decision", "fire", "--resolution", "not now", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["decision"]["status"] == "dismissed"
    assert payload["decision"]["operational_effect"]["applied"] is False
    after = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")["active_agents"]
    assert after == before


def test_dispatch_accept_hire_blocks_imported_blocked_compatibility(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root, with_tests=False)
    _import_agent(project_root, tmp_path, agent_id="portable-blocked-agent", requires_test=True)

    proc = _run_cli(["dispatch", "accept", "portable-blocked-agent", "--decision", "hire"], cwd=project_root)

    assert proc.returncode != 0
    assert "blocked" in proc.stderr
    profile = _read_yaml(project_root / ".cambrian" / "harness" / "profile.yaml")
    assert "portable-blocked-agent" not in profile["active_agents"]


def test_dispatch_decisions_list_and_filter(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    assert _run_cli(["dispatch", "accept", "bug-fix-agent", "--decision", "keep"], cwd=project_root).returncode == 0
    assert _run_cli(["dispatch", "dismiss", "docs-update-agent", "--decision", "fire"], cwd=project_root).returncode == 0

    all_proc = _run_cli(["dispatch", "decisions"], cwd=project_root)
    accepted_proc = _run_cli(["dispatch", "decisions", "--status", "accepted", "--json"], cwd=project_root)

    assert all_proc.returncode == 0, all_proc.stderr
    assert "Staffing Decisions" in all_proc.stdout
    payload = json.loads(accepted_proc.stdout)
    assert all(item["status"] == "accepted" for item in payload["decisions"])


def test_status_and_agent_show_include_staffing_decisions(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    proc = _run_cli(["dispatch", "accept", "bug-fix-agent", "--decision", "keep"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr

    status_proc = _run_cli(["status"], cwd=project_root)
    show_proc = _run_cli(["agent", "show", "bug-fix-agent"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Staffing decisions:" in status_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Staffing decisions:" in show_proc.stdout


def test_dispatch_decisions_do_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    assert _run_cli(["dispatch", "accept", "bug-fix-agent", "--decision", "keep"], cwd=project_root).returncode == 0
    assert _run_cli(["dispatch", "dismiss", "review-agent", "--decision", "prefer_support"], cwd=project_root).returncode == 0
    assert _run_cli(["dispatch", "decisions"], cwd=project_root).returncode == 0
    assert _run_cli(["status"], cwd=project_root).returncode == 0

    assert _sha256(source_path) == before
