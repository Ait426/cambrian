"""Cambrian 프로젝트 모드 UX 셸 테스트."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import (
    ProjectInitializer,
    ProjectRunPreparer,
    ProjectStatusReader,
    render_status_summary,
)


def _read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


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


def test_init_creates_config_files(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)

    result = ProjectInitializer().init(tmp_path)

    assert result.status == "initialized"
    for file_name in ("project.yaml", "rules.yaml", "skills.yaml", "profile.yaml"):
        assert (tmp_path / ".cambrian" / file_name).exists()


def test_init_does_not_overwrite_without_force(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    initializer = ProjectInitializer()
    initializer.init(tmp_path)
    project_path = tmp_path / ".cambrian" / "project.yaml"
    project_path.write_text("marker: keep\n", encoding="utf-8")

    result = initializer.init(tmp_path, force=False)

    assert result.status == "blocked"
    assert project_path.read_text(encoding="utf-8") == "marker: keep\n"


def test_init_repairs_profile_only_harness_install_state(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    profile_path = tmp_path / ".cambrian" / "profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text("custom_harness_profile: keep\n", encoding="utf-8")

    result = ProjectInitializer().init(tmp_path, force=False)

    assert result.status == "initialized"
    assert (tmp_path / ".cambrian" / "project.yaml").exists()
    assert (tmp_path / ".cambrian" / "skills.yaml").exists()
    assert profile_path.read_text(encoding="utf-8") == "custom_harness_profile: keep\n"
    assert any("profile.yaml" in warning for warning in result.warnings)


def test_status_reports_partial_custom_harness_before_project_baseline_repair(tmp_path: Path) -> None:
    harness_path = tmp_path / ".cambrian" / "harness.yaml"
    _write_yaml(
        harness_path,
        {
            "schema_version": "1.0.0",
            "id": "custom-avf-pipeline",
            "type": "custom",
            "status": "active",
            "quality_gate": {"status": "ready", "score": 92},
        },
    )

    status = ProjectStatusReader().read(tmp_path)

    assert status.initialized is False
    assert status.harness["fitted"] is True
    assert status.harness["type"] == "custom_harness"
    assert status.status_truth["status"] == "partial"
    assert "project_mode_baseline_missing" in status.status_truth["evidence_gaps"]
    assert "repair the missing project mode baseline" in status.next_actions[0]
    assert "Custom harness detected" in render_status_summary(status)


def test_status_truth_reports_custom_harness_agents_skills_authority_and_validation(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)
    _write_yaml(
        tmp_path / ".cambrian" / "harness.yaml",
        {
            "schema_version": "1.0.0",
            "id": "custom-avf-pipeline",
            "type": "custom",
            "status": "active",
            "quality_gate": {"status": "ready", "score": 94},
            "policy": {
                "change_mode": "proposal_only",
                "auto_apply": False,
                "forbidden": ["git push"],
                "allowed": ["avf.py"],
            },
            "codebase_evidence": {
                "status": "grounded",
                "existing_important_paths": ["avf.py", "tests/test_avf.py"],
                "missing_important_paths": [],
                "domain_confidence": {
                    "confirmed": ["stage_pipeline"],
                    "suspected": ["schema_validation"],
                    "weak": [],
                },
            },
            "domain_spec": {
                "execution_policy": {
                    "change_policy": "proposal_only",
                    "provider_api_call": False,
                    "external_transfer": "explicit_approval_required",
                    "auto_apply": False,
                }
            },
            "evaluator_contract": {"validation_commands": ["python -m pytest -q tests/test_avf.py"]},
        },
    )
    _write_yaml(
        tmp_path / ".cambrian" / "agents.yaml",
        {"schema_version": "1.0.0", "agents": [{"id": "ddmq-debugger"}, {"id": "stage-schema-validator"}]},
    )
    _write_yaml(
        tmp_path / ".cambrian" / "validation.yaml",
        {
            "schema_version": "1.0.0",
            "validation": {"test_commands": ["python -m pytest -q tests/test_avf.py"], "policy": "proposal_only"},
        },
    )
    _write_yaml(
        tmp_path / ".cambrian" / "skills" / "trace-stage-pipeline.yaml",
        {"id": "trace-stage-pipeline", "status": "active", "assigned_agents": ["ddmq-debugger"]},
    )
    _write_json(
        tmp_path / ".cambrian" / "reports" / "latest_verdict.json",
        {
            "job_id": "job-001",
            "validation_status": "passed",
            "validation_contract_status": "commands_executed",
            "trust_gate_status": "verified",
            "verdict": "pass",
            "unchecked_items": [],
        },
    )

    status = ProjectStatusReader().read(tmp_path)
    truth = status.status_truth

    assert truth["status"] == "verified"
    assert truth["active_harness"]["harness_id"] == "custom-avf-pipeline"
    assert truth["active_agents"]["ids"] == ["ddmq-debugger", "stage-schema-validator"]
    assert truth["active_skills"]["ids"] == ["trace-stage-pipeline"]
    assert truth["authority"]["change_mode"] == "proposal_only"
    assert truth["authority"]["source_apply_requires_confirm"] is True
    assert truth["validation"]["trust_gate_status"] == "verified"
    assert truth["evidence_gaps"] == []
    assert truth["release_boundaries"]["status_truth_claim_allowed"] is True
    assert truth["release_boundaries"]["external_release_claim_allowed"] is False


def test_init_force_overwrites(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    initializer = ProjectInitializer()
    initializer.init(tmp_path)
    project_path = tmp_path / ".cambrian" / "project.yaml"
    project_path.write_text("marker: keep\n", encoding="utf-8")

    result = initializer.init(tmp_path, force=True)

    assert result.status == "initialized"
    assert "marker: keep" not in project_path.read_text(encoding="utf-8")


def test_auto_detection_python_and_pytest(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)

    ProjectInitializer().init(tmp_path)
    project_payload = _read_yaml(tmp_path / ".cambrian" / "project.yaml")

    assert project_payload["project"]["type"] == "python"
    assert project_payload["detected"]["python"] is True
    assert project_payload["detected"]["pytest"] is True
    assert project_payload["test"]["command"] == "pytest -q"


def test_run_prepares_request_and_task_draft(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "로그인 에러 수정해")

    assert result.user_request == "로그인 에러 수정해"
    assert (tmp_path / result.request_path).exists()
    assert (tmp_path / result.task_spec_path).exists()
    request_payload = _read_yaml(tmp_path / result.request_path)
    assert request_payload["user_request"] == "로그인 에러 수정해"
    assert request_payload["selected_skills"]


def test_run_does_not_execute_by_default(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "작은 버그를 수정해")

    assert result.status == "draft"
    assert result.execution["attempted"] is False
    assert not (tmp_path / ".cambrian" / "brain" / "runs").exists()


def test_run_execute_blocked_if_no_actions(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(
        tmp_path,
        "로그인 에러 수정해",
        execute=True,
    )

    assert result.status == "blocked"
    assert result.execution["attempted"] is True
    assert result.execution["status"] == "blocked"
    assert "no executable actions" in result.execution["reason"]


def test_skill_selection_uses_default_selection(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    result = ProjectRunPreparer().prepare(tmp_path, "리팩터링해")

    assert result.selected_skills == [
        "small_refactor",
        "regression_test",
        "review_candidate",
    ]


def test_status_before_init_does_not_crash(tmp_path: Path) -> None:
    status = ProjectStatusReader().read(tmp_path)

    assert status.initialized is False
    assert status.next_actions


def test_status_after_init_reads_project_summary(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    status = ProjectStatusReader().read(tmp_path)

    assert status.initialized is True
    assert status.project["type"] == "python"
    assert status.profile["mode"] == "balanced"
    assert "bug_fix" in status.recommended_skills


def test_status_with_recent_artifacts_collects_memory(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    _write_json(
        tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "run_state.json",
        {
            "run_id": "brain-001",
            "updated_at": "2026-04-22T10:00:00+00:00",
        },
    )
    _write_json(
        tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json",
        {
            "next_actions": ["Run related tests again"],
        },
    )
    _write_json(
        tmp_path / ".cambrian" / "feedback" / "feedback_001.json",
        {
            "keep_patterns": ["Keep minimal auth patch"],
            "avoid_patterns": ["Avoid broad auth refactor"],
            "suggested_next_actions": ["Add integration tests for login flow"],
        },
    )
    _write_yaml(
        tmp_path / ".cambrian" / "next_generation" / "next_generation_001.yaml",
        {
            "lessons": {
                "keep": ["Keep minimal auth patch"],
                "avoid": ["Avoid broad auth refactor"],
            },
        },
    )
    _write_yaml(
        tmp_path / ".cambrian" / "evolution" / "_selection_pressure.yaml",
        {
            "risk_flags": ["repeated_no_winner"],
        },
    )
    _write_json(
        tmp_path / ".cambrian" / "adoptions" / "_latest.json",
        {
            "latest_adoption_id": "adoption-001",
        },
    )

    status = ProjectStatusReader().read(tmp_path)

    assert status.memory["last_run"] == "brain-001"
    assert status.memory["last_adoption"] == "adoption-001"
    assert "repeated no winner" == status.memory["current_risk"]
    assert any("Keep minimal auth patch" in item for item in status.recent_lessons)
    assert any("Add integration tests" in item for item in status.next_actions)


def test_cli_smoke_init_run_status(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)

    init_proc = _run_cli(["init", "--non-interactive"], cwd=tmp_path)
    assert init_proc.returncode == 0, init_proc.stderr
    assert "Cambrian initialized" in init_proc.stdout

    run_proc = _run_cli(["run", "로그인 에러 수정해", "--dry-run"], cwd=tmp_path)
    assert run_proc.returncode == 0, run_proc.stderr
    assert "Cambrian prepared" in run_proc.stdout

    status_proc = _run_cli(["status"], cwd=tmp_path)
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Cambrian Project Status" in status_proc.stdout


def test_json_output_for_init_run_status(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)

    init_proc = _run_cli(["init", "--json"], cwd=tmp_path)
    init_payload = json.loads(init_proc.stdout)
    assert init_payload["status"] == "initialized"

    run_proc = _run_cli(["run", "로그인 에러 수정해", "--json"], cwd=tmp_path)
    run_payload = json.loads(run_proc.stdout)
    assert run_payload["user_request"] == "로그인 에러 수정해"

    status_proc = _run_cli(["status", "--json"], cwd=tmp_path)
    status_payload = json.loads(status_proc.stdout)
    assert status_payload["initialized"] is True


def test_source_safety_only_changes_cambrian_dir(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    source_path = tmp_path / "app.py"
    source_path.write_text("print('safe')\n", encoding="utf-8")

    initializer = ProjectInitializer()
    initializer.init(tmp_path)
    ProjectRunPreparer().prepare(tmp_path, "버그를 수정해")
    ProjectStatusReader().read(tmp_path)

    assert source_path.read_text(encoding="utf-8") == "print('safe')\n"
