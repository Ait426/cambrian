from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from test_agent_teams import _team, _teams_payload
from test_agent_transfer import _prepare_target_project, _read_yaml, _run_cli
from test_benchmark_replay import _seed_auth_project
from test_improvement_loop import _evidence, _start_cycle
from test_template_recommend import _copy_template_store, _prepare_template_store


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pack_cycle(
    root: Path,
    *,
    team: str | None = None,
    template: str | None = None,
    context_path: str = "src/auth.py",
    test_path: str = "tests/test_auth.py",
) -> dict:
    _evidence(root)
    cycle = _start_cycle(root)
    args = [
        "improve",
        "pack",
        cycle["cycle_id"],
        "--context-path",
        context_path,
        "--test-path",
        test_path,
        "--json",
    ]
    if team:
        args.extend(["--team", team])
    if template:
        args.extend(["--template", template])
    proc = _run_cli(args, cwd=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict)
    return payload


def _apply_pack(root: Path, pack: dict) -> dict:
    proc = _run_cli(["improve", "apply", pack["saved_path"], "--json"], cwd=root)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict)
    return payload


def test_pack_created_from_cycle(tmp_path: Path) -> None:
    pack = _pack_cycle(tmp_path)

    assert pack["status"] == "drafted"
    assert pack["fix_kind"] == "strengthen_context_hints"
    assert pack["overlay_effects"]["context_hint_bias"] is True
    assert pack["overlay_effects"]["preferred_context_paths"] == ["src/auth.py"]
    assert pack["overlay_effects"]["preferred_test_paths"] == ["tests/test_auth.py"]
    assert Path(pack["saved_path"]).exists()


def test_apply_intervention_creates_overlay(tmp_path: Path) -> None:
    pack = _pack_cycle(tmp_path)

    applied = _apply_pack(tmp_path, pack)

    overlay = applied["overlay"]
    assert applied["status"] == "applied"
    assert overlay["active_intervention_id"] == pack["intervention_id"]
    assert overlay["context_hint_bias"] is True
    overlay_path = tmp_path / ".cambrian" / "improvement" / "overlay.yaml"
    assert overlay_path.exists()
    saved = _read_yaml(Path(pack["saved_path"]))
    assert saved["status"] == "applied"


def test_only_one_active_intervention_allowed(tmp_path: Path) -> None:
    first = _pack_cycle(tmp_path)
    _apply_pack(tmp_path, first)

    proc = _run_cli(["improve", "apply", first["saved_path"]], cwd=tmp_path)

    assert proc.returncode == 1
    assert "already active" in proc.stderr
    assert "improve revert" in proc.stderr


def test_revert_intervention_clears_overlay(tmp_path: Path) -> None:
    pack = _pack_cycle(tmp_path)
    _apply_pack(tmp_path, pack)

    proc = _run_cli(["improve", "revert", pack["saved_path"], "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "reverted"
    assert payload["overlay"]["active_intervention_id"] is None
    saved = _read_yaml(Path(pack["saved_path"]))
    assert saved["status"] == "reverted"


def test_context_scan_reflects_context_hint_bias(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_auth.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")
    pack = _pack_cycle(tmp_path)
    _apply_pack(tmp_path, pack)

    proc = _run_cli(["context", "scan", "fix login auth bug", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    source = next(item for item in payload["suggested_sources"] if item["path"] == "src/auth.py")
    test = next(item for item in payload["suggested_tests"] if item["path"] == "tests/test_auth.py")
    assert any("active improvement intervention prefers this file/test" in reason for reason in source["reasons"])
    assert any("active improvement intervention prefers this file/test" in reason for reason in test["reasons"])


def test_do_and_status_show_active_intervention_hints(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    pack = _pack_cycle(tmp_path)
    _apply_pack(tmp_path, pack)

    do_proc = _run_cli(["do", "fix login auth bug"], cwd=tmp_path)
    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert do_proc.returncode == 0, do_proc.stderr
    assert "Improvement intervention:" in do_proc.stdout
    assert status_proc.returncode == 0, status_proc.stderr
    assert "Improvement intervention:" in status_proc.stdout
    assert "strengthen_context_hints" in status_proc.stdout


def test_team_and_template_recommendation_use_weak_bias(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _write_yaml(
        project_root / ".cambrian" / "agents" / "teams.yaml",
        _teams_payload(
            active_team_id=None,
            teams=[
                _team("auth-bug-team", "auth-bug-team", ["bug-fix-agent", "regression-test-agent", "review-agent"], tags=["auth"]),
                _team("docs-team", "docs-team", ["docs-update-agent"], tags=["docs"]),
            ],
        ),
    )
    store_path = _prepare_template_store(tmp_path)
    _copy_template_store(store_path, project_root)
    pack = _pack_cycle(project_root, team="auth-bug-team", template="auth-bug-template")
    _apply_pack(project_root, pack)

    team_proc = _run_cli(["team", "recommend", "fix login bug", "--json"], cwd=project_root)
    template_proc = _run_cli(["template", "recommend", "--json"], cwd=project_root)

    assert team_proc.returncode == 0, team_proc.stderr
    team_payload = json.loads(team_proc.stdout)
    auth_team = next(item for item in team_payload["recommendations"] if item["name"] == "auth-bug-team")
    assert any("active improvement intervention prefers this team" in reason for reason in auth_team["reasons"])
    assert template_proc.returncode == 0, template_proc.stderr
    template_payload = json.loads(template_proc.stdout)
    auth_template = next(item for item in template_payload["candidates"] if item["name"] == "auth-bug-template")
    assert any("active improvement intervention prefers this template" in reason for reason in auth_template["reasons"])


def test_metrics_and_replay_store_active_intervention_ref(tmp_path: Path) -> None:
    source_path = _seed_auth_project(tmp_path, bridge=False)
    before = _sha256(source_path)
    _evidence(tmp_path)
    pack = _pack_cycle(tmp_path)
    _apply_pack(tmp_path, pack)

    metrics_proc = _run_cli(["metrics", "week", "--json"], cwd=tmp_path)
    replay_proc = _run_cli(["benchmark", "replay", "login-bug", "--mode", "cambrian_guided", "--json"], cwd=tmp_path)

    assert metrics_proc.returncode == 0, metrics_proc.stderr
    metrics = json.loads(metrics_proc.stdout)
    assert metrics["summary"]["active_intervention_id"] == pack["intervention_id"]
    assert replay_proc.returncode == 0, replay_proc.stderr
    replay = json.loads(replay_proc.stdout)
    assert replay["metrics_snapshot"]["active_intervention_id"] == pack["intervention_id"]
    assert _sha256(source_path) == before


def test_source_immutability_for_intervention_flow(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def login():\n    return True\n", encoding="utf-8")
    before = _sha256(source_path)
    pack = _pack_cycle(tmp_path)
    _apply_pack(tmp_path, pack)

    assert _run_cli(["context", "scan", "fix login auth bug"], cwd=tmp_path).returncode == 0
    assert _run_cli(["do", "fix login auth bug"], cwd=tmp_path).returncode == 0
    assert _run_cli(["improve", "revert", pack["saved_path"]], cwd=tmp_path).returncode == 0

    assert _sha256(source_path) == before
