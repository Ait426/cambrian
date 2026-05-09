from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_transfer import _prepare_target_project, _run_cli


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_case(
    project_root: Path,
    *,
    case_id: str,
    request: str,
    replay_hints: dict | None = None,
) -> None:
    _write_yaml(
        project_root / ".cambrian" / "benchmarks" / "cases" / f"case_{case_id}.yaml",
        {
            "schema_version": "1.0.0",
            "case_id": case_id,
            "created_at": "2026-04-21T00:00:00+00:00",
            "name": case_id,
            "request": request,
            "request_class": "bug_fix",
            "description": None,
            "tags": ["auth", "login"],
            "expected_focus": ["auth"],
            "replay_hints": replay_hints or {},
            "notes": [],
            "warnings": [],
            "errors": [],
        },
    )


def _seed_workset(project_root: Path, case_ids: list[str]) -> None:
    _write_yaml(
        project_root / ".cambrian" / "benchmarks" / "worksets" / "workset_auth-bug-workset.yaml",
        {
            "schema_version": "1.0.0",
            "workset_id": "auth-bug-workset",
            "created_at": "2026-04-21T00:00:00+00:00",
            "name": "auth-bug-workset",
            "description": None,
            "case_ids": case_ids,
            "tags": ["auth"],
            "warnings": [],
            "errors": [],
        },
    )


def _seed_auth_workset(project_root: Path, *, include_missing: bool = False) -> Path:
    _prepare_target_project(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        "\n".join(
            [
                "def normalize(username):",
                "    return username",
                "",
            ]
        ),
        encoding="utf-8",
    )
    test_path = project_root / "tests" / "test_auth.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text("def test_normalize():\n    assert True\n", encoding="utf-8")
    reply_path = project_root / ".cambrian" / "bridge" / "replies" / "reply_login.yaml"
    _write_yaml(
        reply_path,
        {
            "schema_version": "1.0.0",
            "reply_id": "reply_login",
            "created_at": "2026-04-21T00:00:00+00:00",
            "packet_id": None,
            "project_name": "demo",
            "request": "fix auth login",
            "response_kind": "patch_candidate",
            "content": {
                "response_kind": "patch_candidate",
                "summary": "normalize username before login",
                "target_path": "src/auth.py",
                "old_text": "return username",
                "new_text": "return username.strip().lower()",
                "reason": "narrow auth normalization fix",
                "related_tests": ["tests/test_auth.py"],
                "warnings": [],
            },
            "raw_text": None,
            "source_reply_path": None,
            "linked_session_id": None,
            "linked_request_ref": None,
            "warnings": [],
            "errors": [],
        },
    )
    _seed_case(
        project_root,
        case_id="login-bug",
        request="fix auth login",
        replay_hints={
            "source_path_hint": "src/auth.py",
            "test_path_hint": "tests/test_auth.py",
            "bridge_reply_ref": ".cambrian/bridge/replies/reply_login.yaml",
        },
    )
    _seed_case(
        project_root,
        case_id="auth-edge-case",
        request="fix auth edge case",
        replay_hints={
            "source_path_hint": "src/auth.py",
            "test_path_hint": "tests/test_auth.py",
        },
    )
    case_ids = ["login-bug", "auth-edge-case"]
    if include_missing:
        case_ids.append("missing-case")
    _seed_workset(project_root, case_ids)
    return source_path


def test_replay_workset_runs_all_cases_and_saves(tmp_path: Path) -> None:
    _seed_auth_workset(tmp_path)

    proc = _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_full", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["total_cases"] == 2
    assert [entry["case_id"] for entry in report["entries"]] == ["login-bug", "auth-edge-case"]
    assert Path(report["saved_path"]).exists()
    assert list((tmp_path / ".cambrian" / "benchmarks" / "workset_replays").glob("replay_*.yaml"))


def test_one_case_failure_does_not_kill_workset_replay(tmp_path: Path) -> None:
    _seed_auth_workset(tmp_path, include_missing=True)

    proc = _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_full", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["total_cases"] == 3
    failed = next(entry for entry in report["entries"] if entry["case_id"] == "missing-case")
    assert failed["status"] == "failed"
    assert report["errors"]


def test_stage_and_stop_reason_aggregation(tmp_path: Path) -> None:
    _seed_auth_workset(tmp_path)

    proc = _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_full", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["stage_counts"]["proposal_validated"] == 1
    assert report["stage_counts"]["diagnosed"] == 1
    assert report["stop_reason_counts"]["no safe prefilled patch candidate was available"] == 1


def test_autonomy_summary_metrics(tmp_path: Path) -> None:
    _seed_auth_workset(tmp_path)

    proc = _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_full", "--json"],
        cwd=tmp_path,
    )

    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)["summary"]
    assert summary["validated_proposal_rate"] == 0.5
    assert summary["validation_autonomy_rate"] == 0.5
    assert summary["human_intervention_rate"] == 0.0
    assert summary["median_duration_seconds"] is not None


def test_autonomy_board_compares_modes_and_picks_best(tmp_path: Path) -> None:
    _seed_auth_workset(tmp_path)
    assert _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_guided"],
        cwd=tmp_path,
    ).returncode == 0
    assert _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_full"],
        cwd=tmp_path,
    ).returncode == 0

    proc = _run_cli(["benchmark", "autonomy-board", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    board = json.loads(proc.stdout)
    assert board["best_mode"] == "cambrian_full"
    modes = {item["mode"]: item for item in board["mode_summaries"]}
    assert modes["cambrian_guided"]["validated_proposal_rate"] == 0.0
    assert modes["cambrian_full"]["validated_proposal_rate"] == 0.5


def test_autonomy_board_insufficient_data_warning_and_save(tmp_path: Path) -> None:
    _seed_auth_workset(tmp_path)
    assert _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_guided"],
        cwd=tmp_path,
    ).returncode == 0

    proc = _run_cli(["benchmark", "autonomy-board", "auth-bug-workset", "--save", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    board = json.loads(proc.stdout)
    assert "fewer than two replay modes are available for comparison" in board["warnings"]
    assert Path(board["saved_path"]).exists()
    assert list((tmp_path / ".cambrian" / "benchmarks" / "autonomy_boards").glob("board_*.yaml"))


def test_status_autonomy_summary_and_source_immutability(tmp_path: Path) -> None:
    source_path = _seed_auth_workset(tmp_path)
    before = _sha256(source_path)
    assert _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_full"],
        cwd=tmp_path,
    ).returncode == 0
    assert _run_cli(["benchmark", "autonomy-board", "auth-bug-workset", "--save"], cwd=tmp_path).returncode == 0

    proc = _run_cli(["status"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert "Benchmark autonomy:" in proc.stdout
    assert "auth-bug-workset" in proc.stdout
    assert _sha256(source_path) == before


def test_workset_replays_list(tmp_path: Path) -> None:
    _seed_auth_workset(tmp_path)
    assert _run_cli(
        ["benchmark", "replay-workset", "auth-bug-workset", "--mode", "cambrian_full"],
        cwd=tmp_path,
    ).returncode == 0

    proc = _run_cli(["benchmark", "workset-replays", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["workset_replays"][0]["workset_name"] == "auth-bug-workset"
