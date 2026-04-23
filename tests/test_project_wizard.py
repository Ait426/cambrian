"""Cambrian project wizard 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_mode import ProjectInitializer, ProjectStatusReader


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


def _prepare_python_project(project_root: Path) -> None:
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (project_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "app.py").write_text(
        "def hello() -> str:\n"
        "    return 'hello'\n",
        encoding="utf-8",
    )


def _answers_payload(**overrides: object) -> dict:
    payload: dict = {
        "project_name": "login-bug-demo",
        "project_type": "python",
        "stack": ["python", "pytest", "fastapi"],
        "test_command": "pytest -q",
        "primary_use_cases": ["bug_fix", "regression_test", "review_candidate"],
        "protected_paths": [".git", ".cambrian", ".venv", "migrations"],
        "mode": "balanced",
        "max_variants": 2,
        "auto_adoption": False,
        "notes": ["Prefer small patches before broad refactors."],
    }
    payload.update(overrides)
    return payload


def _write_answers_file(project_root: Path, payload: dict) -> Path:
    answers_path = project_root / "answers.yaml"
    _write_yaml(answers_path, payload)
    return answers_path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_wizard_answers_file_creates_configs(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    answers_path = _write_answers_file(tmp_path, _answers_payload())

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    for file_name in ("project.yaml", "rules.yaml", "skills.yaml", "profile.yaml", "init_report.yaml"):
        assert (tmp_path / ".cambrian" / file_name).exists()

    project_payload = _read_yaml(tmp_path / ".cambrian" / "project.yaml")
    rules_payload = _read_yaml(tmp_path / ".cambrian" / "rules.yaml")
    skills_payload = _read_yaml(tmp_path / ".cambrian" / "skills.yaml")
    profile_payload = _read_yaml(tmp_path / ".cambrian" / "profile.yaml")
    report_payload = _read_yaml(tmp_path / ".cambrian" / "init_report.yaml")

    assert project_payload["project"]["name"] == "login-bug-demo"
    assert project_payload["project"]["type"] == "python"
    assert project_payload["onboarding"]["wizard_completed"] is True
    assert rules_payload["workspace"]["protect_paths"] == [".git", ".cambrian", ".venv", "migrations"]
    assert skills_payload["selection"]["default"] == ["bug_fix", "regression_test", "review_candidate"]
    assert profile_payload["mode"] == "balanced"
    assert profile_payload["defaults"]["max_variants"] == 2
    assert report_payload["status"] == "completed"


def test_wizard_fills_missing_fields_from_detection(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    answers_path = _write_answers_file(
        tmp_path,
        {
            "project_name": "partial-demo",
            "primary_use_cases": ["bug_fix"],
        },
    )

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_payload = _read_yaml(tmp_path / ".cambrian" / "project.yaml")
    profile_payload = _read_yaml(tmp_path / ".cambrian" / "profile.yaml")
    assert project_payload["project"]["type"] == "python"
    assert project_payload["test"]["command"] == "pytest -q"
    assert profile_payload["mode"] == "balanced"


def test_wizard_does_not_overwrite_without_force(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    cambrian_dir = tmp_path / ".cambrian"
    cambrian_dir.mkdir(parents=True, exist_ok=True)
    project_path = cambrian_dir / "project.yaml"
    project_path.write_text("marker: keep\n", encoding="utf-8")
    answers_path = _write_answers_file(tmp_path, _answers_payload())

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "already exist" in result.stdout
    assert project_path.read_text(encoding="utf-8") == "marker: keep\n"


def test_wizard_force_overwrites(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    first_answers = _write_answers_file(tmp_path, _answers_payload(project_name="first-demo"))
    _run_cli(["init", "--wizard", "--answers-file", str(first_answers)], tmp_path)

    second_answers = _write_answers_file(tmp_path, _answers_payload(project_name="second-demo", mode="aggressive", max_variants=3))
    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(second_answers), "--force"],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_payload = _read_yaml(tmp_path / ".cambrian" / "project.yaml")
    init_report = _read_yaml(tmp_path / ".cambrian" / "init_report.yaml")
    assert project_payload["project"]["name"] == "second-demo"
    assert project_payload["onboarding"]["wizard_completed"] is True
    assert init_report["project_name"] == "second-demo"


def test_auto_adoption_forced_false(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    answers_path = _write_answers_file(tmp_path, _answers_payload(auto_adoption=True))

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    rules_payload = _read_yaml(tmp_path / ".cambrian" / "rules.yaml")
    profile_payload = _read_yaml(tmp_path / ".cambrian" / "profile.yaml")
    assert rules_payload["safety"]["never_auto_adopt"] is True
    assert profile_payload["defaults"]["adoption"] == "explicit_only"
    assert "auto_adoption=true" in result.stdout


def test_invalid_mode_warning_falls_back_balanced(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    answers_path = _write_answers_file(tmp_path, _answers_payload(mode="wild"))

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    profile_payload = _read_yaml(tmp_path / ".cambrian" / "profile.yaml")
    assert profile_payload["mode"] == "balanced"
    assert "falling back to balanced" in result.stdout


def test_non_interactive_compatibility(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)

    result = _run_cli(["init", "--non-interactive"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".cambrian" / "project.yaml").exists()
    assert "Cambrian initialized." in result.stdout


def test_wizard_and_non_interactive_without_answers_blocked(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)

    result = _run_cli(["init", "--wizard", "--non-interactive"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert "--answers-file" in result.stdout
    assert not (tmp_path / ".cambrian" / "project.yaml").exists()


def test_status_shows_wizard_completed(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    answers_path = _write_answers_file(tmp_path, _answers_payload())
    _run_cli(["init", "--wizard", "--answers-file", str(answers_path)], tmp_path)

    status = ProjectStatusReader().read(tmp_path)
    result = _run_cli(["status"], tmp_path)

    assert status.onboarding["wizard_completed"] is True
    assert "Project harness:" in result.stdout
    assert "wizard     : completed" in result.stdout


def test_status_suggests_wizard_when_not_completed(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    ProjectInitializer().init(tmp_path)

    status = ProjectStatusReader().read(tmp_path)
    result = _run_cli(["status"], tmp_path)

    assert status.onboarding["wizard_completed"] is False
    assert any("cambrian init --wizard" in item for item in status.next_actions)
    assert "wizard     : not completed" in result.stdout


def test_wizard_json_output(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    answers_path = _write_answers_file(tmp_path, _answers_payload())

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path), "--json"],
        tmp_path,
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["answers"]["project_name"] == "login-bug-demo"
    assert ".cambrian/init_report.yaml" in payload["created_files"]


def test_human_output_contains_created_and_next(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    answers_path = _write_answers_file(tmp_path, _answers_payload())

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "Created:" in result.stdout
    assert "Next:" in result.stdout


def test_wizard_only_changes_cambrian_dir(tmp_path: Path) -> None:
    _prepare_python_project(tmp_path)
    source_path = tmp_path / "src" / "app.py"
    before_hash = _sha256(source_path)
    answers_path = _write_answers_file(tmp_path, _answers_payload())

    result = _run_cli(
        ["init", "--wizard", "--answers-file", str(answers_path)],
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert _sha256(source_path) == before_hash
