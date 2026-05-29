from __future__ import annotations

import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _run_cli


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


def _add_auth_benchmark_signal(project_root: Path) -> None:
    _write_yaml(
        project_root / ".cambrian" / "benchmarks" / "cases" / "case_login_bug.yaml",
        {
            "schema_version": "1.0.0",
            "case_id": "case-login-bug",
            "name": "login-bug",
            "request": "fix auth login bug",
            "request_class": "bug_fix",
            "tags": ["auth", "login"],
            "expected_focus": ["narrow_scope", "regression_test"],
        },
    )


def _prepare_strong_lane_project(project_root: Path) -> None:
    _prepare_target_project(project_root)
    _add_auth_benchmark_signal(project_root)


def test_strong_lane_detection(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)

    proc = _run_cli(["lane", "show", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    profile = payload["profile"]
    assert profile["status"] == "strong"
    assert profile["lane_id"] == "python-pytest-auth-bug-core"
    assert profile["default_team"] == "auth-bug-team"
    assert profile["default_template"] == "auth-bug-template"
    assert profile["default_workset"] == "auth-bug-workset"
    assert (tmp_path / ".cambrian" / "lane" / "profile.yaml").exists()


def test_partial_lane_detection(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)

    proc = _run_cli(["lane", "show", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    profile = json.loads(proc.stdout)["profile"]
    assert profile["status"] == "partial"


def test_outside_lane_detection(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / ".cambrian" / "project.yaml",
        {
            "schema_version": "1.0.0",
            "project": {"name": "docs-only", "type": "docs", "stack": ["markdown"]},
            "test": {"command": None},
            "ai_work": {"primary_use_cases": ["docs"]},
        },
    )

    proc = _run_cli(["lane", "show", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    profile = json.loads(proc.stdout)["profile"]
    assert profile["status"] == "outside"


def test_status_shows_lane_summary(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)

    proc = _run_cli(["status"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Current strongest lane:" in proc.stdout
    assert "Python + pytest + auth/login narrow bug fix" in proc.stdout
    assert "status: strong" in proc.stdout


def test_harness_show_shows_lane_defaults(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)

    proc = _run_cli(["harness", "show"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Current strongest lane:" in proc.stdout
    assert "auth-bug-team" in proc.stdout
    assert "auth-bug-template" in proc.stdout
    assert "auth-bug-workset" in proc.stdout


def test_do_shows_out_of_lane_caution_without_blocking(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)

    proc = _run_cli(["do", "update deployment migration documentation"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Win lane caution:" in proc.stdout
    assert "outside Cambrian's current strongest lane" in proc.stdout


def test_docs_and_help_mention_strongest_lane() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = [
        root / "README.md",
        root / "docs" / "FIRST_RUN_DEMO.md",
        root / "docs" / "PROJECT_MODE_QUICKSTART.md",
        root / "docs" / "ALPHA_INSTALL.md",
    ]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "Current strongest lane" in text
        assert "Python + pytest + auth/login narrow bug fix" in text
        assert "auth-bug-team" in text
        assert "auth-bug-template" in text
        assert "auth-bug-workset" in text


def test_lane_commands_do_not_mutate_source_files(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize(username):\n    return username\n", encoding="utf-8")
    before = source_path.read_text(encoding="utf-8")

    lane_proc = _run_cli(["lane", "show"], cwd=tmp_path)
    status_proc = _run_cli(["status"], cwd=tmp_path)
    do_proc = _run_cli(["do", "update deployment migration documentation"], cwd=tmp_path)

    assert lane_proc.returncode == 0, lane_proc.stderr
    assert status_proc.returncode == 0, status_proc.stderr
    assert do_proc.returncode == 0, do_proc.stderr
    assert source_path.read_text(encoding="utf-8") == before
