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
    replay_hints: dict | None = None,
    request: str = "fix auth login",
) -> None:
    _write_yaml(
        project_root / ".cambrian" / "benchmarks" / "cases" / "case_login-bug.yaml",
        {
            "schema_version": "1.0.0",
            "case_id": "login-bug",
            "created_at": "2026-04-21T00:00:00+00:00",
            "name": "login-bug",
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


def _seed_auth_project(project_root: Path, *, bridge: bool = False) -> Path:
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
    hints = {
        "source_path_hint": "src/auth.py",
        "test_path_hint": "tests/test_auth.py",
    }
    if bridge:
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
        hints["bridge_reply_ref"] = ".cambrian/bridge/replies/reply_login.yaml"
    _seed_case(project_root, replay_hints=hints)
    return source_path


def test_replay_guided_stops_at_patch_intent_without_bridge(tmp_path: Path) -> None:
    _seed_auth_project(tmp_path, bridge=False)

    proc = _run_cli(["benchmark", "replay", "login-bug", "--mode", "cambrian_guided", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["autonomy_stage_reached"] == "diagnosed"
    assert report["stop_reason"] == "no safe prefilled patch candidate was available"
    assert report["metrics_snapshot"]["validated_proposal"] is False
    assert report["metrics_snapshot"]["human_intervention"] is False
    assert Path(report["saved_path"]).exists()
    assert Path(report["result_path"]).exists()


def test_replay_full_reaches_proposal_validated_with_bridge_reply(tmp_path: Path) -> None:
    source_path = _seed_auth_project(tmp_path, bridge=True)
    before = _sha256(source_path)

    proc = _run_cli(["benchmark", "replay", "login-bug", "--mode", "cambrian_full", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["autonomy_stage_reached"] == "proposal_validated"
    assert report["status"] == "completed"
    assert report["metrics_snapshot"]["validated_proposal"] is True
    assert report["metrics_snapshot"]["validation_autonomy"] is True
    assert report["metrics_snapshot"]["adoption_succeeded"] is False
    assert report["metrics_snapshot"]["apply_tests_passed"] is None
    assert report["linked_bridge_reply_ref"] == ".cambrian/bridge/replies/reply_login.yaml"
    assert list((tmp_path / ".cambrian" / "patch_intents").glob("patch_intent_*.yaml"))
    assert not (tmp_path / ".cambrian" / "adoptions").exists()
    assert _sha256(source_path) == before


def test_replay_ambiguous_context_blocks(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "auth.py").write_text("AUTH = True\n", encoding="utf-8")
    (tmp_path / "docs" / "auth.md").write_text("auth notes\n", encoding="utf-8")
    _seed_case(tmp_path, replay_hints={}, request="auth issue")

    proc = _run_cli(["benchmark", "replay", "login-bug", "--mode", "cambrian_guided", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["autonomy_stage_reached"] == "request_start"
    assert report["stop_reason"] == "ambiguous source selection"
    context_step = next(step for step in report["steps"] if step["kind"] == "context_ready")
    assert context_step["status"] == "blocked"
    assert context_step["warnings"]


def test_replay_show_and_replays_list(tmp_path: Path) -> None:
    _seed_auth_project(tmp_path, bridge=False)
    proc = _run_cli(["benchmark", "replay", "login-bug", "--mode", "cambrian_guided", "--json"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    saved_path = json.loads(proc.stdout)["saved_path"]

    show_proc = _run_cli(["benchmark", "replay-show", saved_path], cwd=tmp_path)
    list_proc = _run_cli(["benchmark", "replays", "--json"], cwd=tmp_path)

    assert show_proc.returncode == 0, show_proc.stderr
    assert "Benchmark Replay" in show_proc.stdout
    assert list_proc.returncode == 0, list_proc.stderr
    assert json.loads(list_proc.stdout)["replays"][0]["case_id"] == "login-bug"


def test_replay_record_result_feeds_benchmark_report(tmp_path: Path) -> None:
    _seed_auth_project(tmp_path, bridge=True)
    assert _run_cli(
        ["benchmark", "workset-save", "auth-bug-workset", "--case", "login-bug"],
        cwd=tmp_path,
    ).returncode == 0
    replay_proc = _run_cli(["benchmark", "replay", "login-bug", "--mode", "cambrian_full", "--json"], cwd=tmp_path)
    assert replay_proc.returncode == 0, replay_proc.stderr

    report_proc = _run_cli(["benchmark", "report", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert report_proc.returncode == 0, report_proc.stderr
    report = json.loads(report_proc.stdout)
    assert report["by_mode"]["cambrian_full"]["validated_proposal_rate"] == 1.0
    assert report["by_mode"]["cambrian_full"]["validation_autonomy_rate"] == 1.0


def test_status_replay_summary_and_source_immutability(tmp_path: Path) -> None:
    source_path = _seed_auth_project(tmp_path, bridge=True)
    before = _sha256(source_path)
    assert _run_cli(["benchmark", "replay", "login-bug", "--mode", "cambrian_full"], cwd=tmp_path).returncode == 0

    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Benchmark replay:" in status_proc.stdout
    assert "proposal_validated" in status_proc.stdout
    assert _sha256(source_path) == before
