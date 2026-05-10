from __future__ import annotations

import hashlib
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _write_validating_auth_fixture(project_root: Path) -> None:
    (project_root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "src" / "auth.py").write_text(
        "def normalize_username(username: str) -> str:\n"
        "    return username\n",
        encoding="utf-8",
    )
    (project_root / "tests" / "test_auth.py").write_text(
        "from src.auth import normalize_username\n\n\n"
        "def test_normalize_username_for_login() -> None:\n"
        "    assert normalize_username('Alice@EXAMPLE.COM') == 'alice@example.com'\n",
        encoding="utf-8",
    )


def test_do_safe_autonomy_strong_lane_reaches_diagnose(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before = _sha256(source_path)

    proc = _run_cli(["do", "fix auth login bug", "--safe-autonomy", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["lane_status"] == "strong"
    assert payload["autonomy_stage_reached"] == "diagnosed"
    assert payload["stop_reason"] == "no patch prefill available"
    assert payload["metrics_snapshot"]["validated_proposal"] is False
    assert (tmp_path / payload["saved_path"]).exists()
    assert _sha256(source_path) == before


def test_do_safe_autonomy_ambiguous_context_blocks(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)
    (tmp_path / "src" / "auth_login.py").write_text(
        "def login_auth(value: str) -> str:\n    return value\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "login_auth.py").write_text(
        "def auth_login(value: str) -> str:\n    return value\n",
        encoding="utf-8",
    )

    proc = _run_cli(["do", "fix auth login bug", "--safe-autonomy", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert payload["stop_reason"] == "ambiguous source selection"
    assert payload["autonomy_stage_reached"] == "request_start"


def test_continue_safe_autonomy_uses_bridge_prefill_to_validate(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)
    _write_validating_auth_fixture(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before = _sha256(source_path)
    reply_path = tmp_path / "reply.yaml"
    _write_yaml(
        reply_path,
        {
            "response_kind": "patch_candidate",
            "request": "fix auth login bug",
            "summary": "normalize username before login",
            "target_path": "src/auth.py",
            "old_text": "return username",
            "new_text": "return username.strip().lower()",
            "reason": "narrow auth login fix with pytest validation",
            "related_tests": ["tests/test_auth.py"],
            "warnings": ["keep scope narrow"],
        },
    )

    fastpath = _run_cli(["bridge", "ingest", str(reply_path), "--auto-route", "--json"], cwd=tmp_path)
    assert fastpath.returncode == 0, fastpath.stderr
    fastpath_payload = json.loads(fastpath.stdout)
    session_id = fastpath_payload["linked_session_id"]
    assert session_id

    proc = _run_cli(["continue", "--session", session_id, "--safe-autonomy", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["autonomy_stage_reached"] == "proposal_validated"
    assert payload["status"] == "completed"
    assert payload["metrics_snapshot"]["validated_proposal"] is True
    assert payload["metrics_snapshot"]["validation_autonomy"] is True
    assert payload["metrics_snapshot"]["human_intervention"] is False
    assert payload["linked_proposal_ref"]
    assert _sha256(source_path) == before


def test_do_safe_autonomy_out_of_lane_no_attempt(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)

    proc = _run_cli(["do", "update deployment migration documentation", "--safe-autonomy", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert payload["autonomy_stage_reached"] == "request_start"
    assert payload["stop_reason"] == "request is outside the current strongest lane"


def test_status_shows_latest_safe_autonomy_run(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)
    proc = _run_cli(["do", "fix auth login bug", "--safe-autonomy", "--json"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr

    status = _run_cli(["status"], cwd=tmp_path)

    assert status.returncode == 0, status.stderr
    assert "Safe autonomy:" in status.stdout
    assert "latest run" in status.stdout
    assert "no patch prefill available" in status.stdout


def test_autonomy_show_and_source_immutability(tmp_path: Path) -> None:
    _prepare_strong_lane_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    before = _sha256(source_path)
    proc = _run_cli(["do", "fix auth login bug", "--safe-autonomy", "--json"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    saved_path = json.loads(proc.stdout)["saved_path"]

    show = _run_cli(["autonomy", "show", saved_path], cwd=tmp_path)

    assert show.returncode == 0, show.stderr
    assert "Safe autonomy stopped." in show.stdout
    assert "Stage reached:" in show.stdout
    assert _sha256(source_path) == before
