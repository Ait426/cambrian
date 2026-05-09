from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer, ProjectRunPreparer


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


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _fit_harness(project_root: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(["harness", "fit"], cwd=project_root)


def _init_project(project_root: Path) -> None:
    _prepare_python_project(project_root)
    result = ProjectInitializer().init(project_root)
    assert result.status == "initialized"


def test_harness_fit_creates_profile_and_registry(tmp_path: Path) -> None:
    _init_project(tmp_path)

    proc = _fit_harness(tmp_path)

    assert proc.returncode == 0, proc.stderr
    profile_path = tmp_path / ".cambrian" / "harness" / "profile.yaml"
    registry_path = tmp_path / ".cambrian" / "agents" / "registry.yaml"
    assert profile_path.exists()
    assert registry_path.exists()
    profile = _read_yaml(profile_path)
    registry = _read_yaml(registry_path)
    assert profile["recommended_agent_roles"]
    assert profile["active_agents"]
    assert registry["agents"]


def test_harness_show_and_doctor_outputs(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    show_proc = _run_cli(["harness", "show"], cwd=tmp_path)
    doctor_proc = _run_cli(["harness", "doctor"], cwd=tmp_path)

    assert show_proc.returncode == 0, show_proc.stderr
    assert "Cambrian Harness" in show_proc.stdout
    assert "Active agents:" in show_proc.stdout
    assert doctor_proc.returncode == 0, doctor_proc.stderr
    assert "Harness Doctor" in doctor_proc.stdout
    assert "healthy" in doctor_proc.stdout or "warning" in doctor_proc.stdout


def test_agent_list_and_show(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    list_proc = _run_cli(["agent", "list"], cwd=tmp_path)
    show_proc = _run_cli(["agent", "show", "bug-fix-agent"], cwd=tmp_path)

    assert list_proc.returncode == 0, list_proc.stderr
    assert "Equipped:" in list_proc.stdout
    assert "bug-fix-agent" in list_proc.stdout
    assert show_proc.returncode == 0, show_proc.stderr
    assert "Agent Passport" in show_proc.stdout
    assert "Strengths:" in show_proc.stdout
    assert "Risks:" in show_proc.stdout


def test_agent_recommend_bug_fix_request(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    proc = _run_cli(["agent", "recommend", "로그인 에러 수정해"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Agent recommendation" in proc.stdout
    assert "bug-fix-agent" in proc.stdout
    assert "regression-test-agent" in proc.stdout
    assert "review-agent" in proc.stdout


def test_memory_aware_agent_recommendation(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _write_yaml(
        tmp_path / ".cambrian" / "memory" / "lessons.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-25T00:00:00+00:00",
            "project_name": "demo",
            "lessons": [
                {
                    "lesson_id": "lesson-test-practice",
                    "kind": "test_practice",
                    "text": "Run pytest for auth changes before apply.",
                    "confidence": 0.9,
                    "source_refs": ["tests/test_auth.py"],
                    "evidence_count": 2,
                    "tags": ["pytest", "auth"],
                    "created_at": "2026-04-25T00:00:00+00:00",
                    "updated_at": "2026-04-25T00:00:00+00:00",
                    "status": "active",
                    "pinned": True,
                    "suppressed": False,
                    "human_note": None,
                }
            ],
            "sources_scanned": 1,
            "warnings": [],
            "errors": [],
        },
    )
    _fit_harness(tmp_path)

    proc = _run_cli(["agent", "recommend", "로그인 에러 수정해", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    ordered_ids = [item["agent_id"] for item in payload["recommendations"]]
    assert "regression-test-agent" in ordered_ids[:2]


def test_agent_equip_and_unequip_update_profile_and_registry(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    unequip_proc = _run_cli(["agent", "unequip", "bug-fix-agent"], cwd=tmp_path)
    equip_proc = _run_cli(["agent", "equip", "docs-update-agent"], cwd=tmp_path)

    assert unequip_proc.returncode == 0, unequip_proc.stderr
    assert equip_proc.returncode == 0, equip_proc.stderr
    profile = _read_yaml(tmp_path / ".cambrian" / "harness" / "profile.yaml")
    registry = _read_yaml(tmp_path / ".cambrian" / "agents" / "registry.yaml")
    assert "bug-fix-agent" not in profile["active_agents"]
    assert "docs-update-agent" in profile["active_agents"]
    statuses = {item["agent_id"]: item["status"] for item in registry["agents"]}
    assert statuses["bug-fix-agent"] == "available"
    assert statuses["docs-update-agent"] == "equipped"


def test_status_shows_harness_and_active_agents(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    proc = _run_cli(["status"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Harness:" in proc.stdout
    assert "Active agents:" in proc.stdout
    assert "bug-fix-agent" in proc.stdout


def test_run_artifact_includes_harness_context(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")
    request_payload = _read_yaml(tmp_path / result.request_path)

    assert "harness_context" in request_payload
    assert request_payload["harness_context"]["harness_ref"] == ".cambrian/harness/profile.yaml"
    assert "bug-fix-agent" in request_payload["harness_context"]["active_agents"]


def test_missing_agent_gives_helpful_error(tmp_path: Path) -> None:
    _init_project(tmp_path)
    _fit_harness(tmp_path)

    proc = _run_cli(["agent", "show", "missing-agent"], cwd=tmp_path)

    assert proc.returncode != 0
    assert "Agent not found" in proc.stderr
    assert "cambrian agent list" in proc.stderr
