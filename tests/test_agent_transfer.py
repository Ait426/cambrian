from __future__ import annotations

import json
from pathlib import Path

import yaml

from test_agent_history import (
    _create_agent_history_artifacts,
    _fit_harness,
    _init_project,
    _run_cli,
)


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _prepare_source_project(project_root: Path) -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    _init_project(project_root)
    fit_proc = _fit_harness(project_root)
    assert fit_proc.returncode == 0, fit_proc.stderr
    _create_agent_history_artifacts(project_root)
    export_path = project_root / "bug-fix-agent.passport.yaml"
    export_proc = _run_cli(
        ["agent", "export", "bug-fix-agent", "--out", str(export_path), "--json"],
        cwd=project_root,
    )
    assert export_proc.returncode == 0, export_proc.stderr
    assert export_path.exists()
    return export_path


def _prepare_target_project(project_root: Path, *, bug_fix: bool = True, with_tests: bool = True) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    _init_project(project_root)
    project_path = project_root / ".cambrian" / "project.yaml"
    payload = _read_yaml(project_path)
    if bug_fix:
        payload.setdefault("ai_work", {})["primary_use_cases"] = ["bug_fix"]
    if not with_tests:
        payload.setdefault("test", {})["command"] = None
    _write_yaml(project_path, payload)
    fit_proc = _fit_harness(project_root)
    assert fit_proc.returncode == 0, fit_proc.stderr


def _make_importable_passport(path: Path, *, agent_id: str, role_id: str = "bug_fix", requires_test: bool = True) -> Path:
    payload = {
        "schema_version": "1.0.0",
        "exported_at": "2026-04-25T00:00:00+00:00",
        "export_id": f"export-{agent_id}",
        "source_project_name": "login-demo",
        "source_harness_id": "harness-login-demo",
        "source_harness": {
            "project_type": "python",
            "stack": ["python", "pytest"],
            "test_command": "pytest -q",
            "primary_use_cases": ["bug_fix"],
            "mode": "balanced",
        },
        "agent_id": agent_id,
        "role_id": role_id,
        "label": f"{agent_id} label",
        "description": "portable agent passport",
        "passport_summary": {
            "status": "equipped",
            "totals": {
                "sessions_seen": 4,
                "requests_seen": 4,
                "diagnoses": 3,
                "patch_intents": 2,
                "patch_proposals": 2,
                "validations_passed": 1,
                "validations_failed": 0,
                "adoptions": 1,
                "notes_linked": 0,
            },
            "recent_wins": ["auth/login fix adopted with passing tests"],
            "recent_risks": [],
            "fit_hints": ["Strong fit for auth/login bug fixes in pytest-based projects."],
        },
        "strengths": ["small defect correction", "targeted code changes"],
        "risks": ["can drift into broad refactor if context is weak"],
        "preferred_signals": ["bug_fix", "failing tests"],
        "required_harness_conditions": ["explicit apply"] + (["test command available"] if requires_test else []),
        "blocked_conditions": ["no test command"] if requires_test else [],
        "tags": ["bug", "patch"],
        "source_refs": {
            "passport_path": ".cambrian/agents/passports/bug-fix-agent.yaml",
            "registry_path": ".cambrian/agents/registry.yaml",
            "harness_path": ".cambrian/harness/profile.yaml",
            "dispatch_log_path": ".cambrian/agents/dispatch_log.yaml",
        },
        "warnings": [],
        "errors": [],
    }
    _write_yaml(path, payload)
    return path


def test_agent_export_contains_source_and_summary(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    export_path = _prepare_source_project(source_root)

    payload = _read_yaml(export_path)

    assert payload["agent_id"] == "bug-fix-agent"
    assert payload["source_project_name"] == source_root.name
    assert payload["source_harness"]["project_type"] == "python"
    assert payload["passport_summary"]["totals"]["adoptions"] == 1
    assert payload["passport_summary"]["recent_wins"]


def test_agent_export_missing_agent_is_blocked(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path / "project")

    proc = _run_cli(["agent", "export", "missing-agent"], cwd=tmp_path / "project")

    assert proc.returncode != 0
    assert "Agent not found" in proc.stderr


def test_agent_import_creates_imported_artifact_with_good_compatibility(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    passport_path = _make_importable_passport(tmp_path / "portable-auth-bug-agent.passport.yaml", agent_id="portable-auth-bug-agent")

    proc = _run_cli(["agent", "import", str(passport_path), "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    imported_path = target_root / ".cambrian" / "agents" / "imported" / "portable-auth-bug-agent.yaml"
    assert imported_path.exists()
    assert payload["record"]["compatibility"]["status"] == "good"
    assert payload["record"]["compatibility"]["score"] >= 0.75


def test_agent_import_blocked_compatibility_keeps_record_but_blocks_equip(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    _prepare_target_project(target_root, with_tests=False)
    passport_path = _make_importable_passport(tmp_path / "portable-validation-agent.passport.yaml", agent_id="portable-validation-agent", role_id="patch_validation", requires_test=True)

    proc = _run_cli(["agent", "import", str(passport_path), "--equip", "--json"], cwd=target_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["record"]["compatibility"]["status"] == "blocked"
    assert payload["record"]["local_status"] == "imported"
    imported_path = target_root / ".cambrian" / "agents" / "imported" / "portable-validation-agent.yaml"
    assert imported_path.exists()
    profile = _read_yaml(target_root / ".cambrian" / "harness" / "profile.yaml")
    assert "portable-validation-agent" not in profile["active_agents"]


def test_agent_list_show_and_recommend_include_imported_agent(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    passport_path = _make_importable_passport(tmp_path / "portable-auth-bug-agent.passport.yaml", agent_id="portable-auth-bug-agent")
    import_proc = _run_cli(["agent", "import", str(passport_path)], cwd=target_root)
    assert import_proc.returncode == 0, import_proc.stderr

    list_proc = _run_cli(["agent", "list"], cwd=target_root)
    show_proc = _run_cli(["agent", "show", "portable-auth-bug-agent"], cwd=target_root)
    recommend_proc = _run_cli(["agent", "recommend", "로그인 에러 수정해", "--json"], cwd=target_root)

    assert list_proc.returncode == 0, list_proc.stderr
    assert "portable-auth-bug-agent" in list_proc.stdout
    assert "[imported" in list_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "source kind : imported" in show_proc.stdout
    assert "compatibility  : good" in show_proc.stdout
    assert recommend_proc.returncode == 0, recommend_proc.stderr
    recommendations = json.loads(recommend_proc.stdout)["recommendations"]
    assert any(item["agent_id"] == "portable-auth-bug-agent" for item in recommendations)


def test_agent_equip_imported_agent_updates_status_and_harness(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    passport_path = _make_importable_passport(tmp_path / "portable-auth-bug-agent.passport.yaml", agent_id="portable-auth-bug-agent")
    import_proc = _run_cli(["agent", "import", str(passport_path)], cwd=target_root)
    assert import_proc.returncode == 0, import_proc.stderr

    equip_proc = _run_cli(["agent", "equip", "portable-auth-bug-agent", "--json"], cwd=target_root)

    assert equip_proc.returncode == 0, equip_proc.stderr
    profile = _read_yaml(target_root / ".cambrian" / "harness" / "profile.yaml")
    registry = _read_yaml(target_root / ".cambrian" / "agents" / "registry.yaml")
    imported = _read_yaml(target_root / ".cambrian" / "agents" / "imported" / "portable-auth-bug-agent.yaml")
    assert "portable-auth-bug-agent" in profile["active_agents"]
    statuses = {item["agent_id"]: item["status"] for item in registry["agents"]}
    assert statuses["portable-auth-bug-agent"] == "equipped"
    assert imported["record"]["local_status"] == "equipped"


def test_agent_import_conflict_with_built_in_is_blocked(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    export_path = _prepare_source_project(source_root)
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)

    proc = _run_cli(["agent", "import", str(export_path)], cwd=target_root)

    assert proc.returncode != 0
    assert "Agent import blocked" in proc.stderr


def test_harness_doctor_and_status_show_imported_agent_summary(tmp_path: Path) -> None:
    target_root = tmp_path / "target"
    _prepare_target_project(target_root)
    passport_path = _make_importable_passport(tmp_path / "portable-auth-bug-agent.passport.yaml", agent_id="portable-auth-bug-agent")
    import_proc = _run_cli(["agent", "import", str(passport_path), "--equip"], cwd=target_root)
    assert import_proc.returncode == 0, import_proc.stderr

    doctor_proc = _run_cli(["harness", "doctor"], cwd=target_root)
    status_proc = _run_cli(["status"], cwd=target_root)

    assert doctor_proc.returncode == 0, doctor_proc.stderr
    assert "imported" in doctor_proc.stdout.lower()
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Imported agents:" in status_proc.stdout
    assert "equipped  : 1" in status_proc.stdout
