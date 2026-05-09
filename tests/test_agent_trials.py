from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_agent_transfer import (
    _make_importable_passport,
    _prepare_target_project,
    _run_cli,
)


def _import_portable_agent(project_root: Path, tmp_path: Path, *, agent_id: str, requires_test: bool = True) -> None:
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


def test_agent_trial_with_imported_good_candidate_creates_artifact(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _import_portable_agent(project_root, tmp_path, agent_id="portable-auth-bug-agent")

    proc = _run_cli(["agent", "trial", "portable-auth-bug-agent", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "completed"
    assert payload["shadow_agent_id"] == "portable-auth-bug-agent"
    assert payload["comparison"]["result"] in {"shadow_stronger", "lead_stronger", "comparable", "inconclusive"}
    saved_path = Path(payload["saved_path"])
    assert saved_path.exists()
    assert saved_path.parent == project_root / ".cambrian" / "agents" / "trials"


def test_agent_trial_blocked_for_blocked_compatibility(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root, with_tests=False)
    _import_portable_agent(project_root, tmp_path, agent_id="portable-blocked-agent", requires_test=True)

    proc = _run_cli(["agent", "trial", "portable-blocked-agent", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "blocked"
    assert payload["compatibility_status"] == "blocked"
    assert payload["steps"][0]["status"] == "blocked"


def test_agent_trial_uses_current_lead_by_default(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)

    proc = _run_cli(["agent", "trial", "review-agent", "fix login bug", "--json"], cwd=project_root)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["current_lead_agent_id"] == "bug-fix-agent"
    assert payload["shadow_agent_id"] == "review-agent"
    assert "lead_summary" in payload["comparison"]
    assert "shadow_summary" in payload["comparison"]


def test_agent_trial_show_by_path(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _import_portable_agent(project_root, tmp_path, agent_id="portable-auth-bug-agent")
    trial_proc = _run_cli(["agent", "trial", "portable-auth-bug-agent", "fix login bug", "--json"], cwd=project_root)
    assert trial_proc.returncode == 0, trial_proc.stderr
    saved_path = Path(json.loads(trial_proc.stdout)["saved_path"])

    show_proc = _run_cli(["agent", "trial-show", str(saved_path), "--json"], cwd=project_root)

    assert show_proc.returncode == 0, show_proc.stderr
    payload = json.loads(show_proc.stdout)
    assert payload["shadow_agent_id"] == "portable-auth-bug-agent"
    assert payload["comparison"]["result"]


def test_status_shows_recent_trial_hint(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _import_portable_agent(project_root, tmp_path, agent_id="portable-auth-bug-agent")
    trial_proc = _run_cli(["agent", "trial", "portable-auth-bug-agent", "fix login bug"], cwd=project_root)
    assert trial_proc.returncode == 0, trial_proc.stderr

    status_proc = _run_cli(["status"], cwd=project_root)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Recent trial:" in status_proc.stdout
    assert "portable-auth-bug-agent" in status_proc.stdout


def test_dispatch_recommend_mentions_recent_trial(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _import_portable_agent(project_root, tmp_path, agent_id="portable-auth-bug-agent")
    trial_proc = _run_cli(["agent", "trial", "portable-auth-bug-agent", "fix login bug"], cwd=project_root)
    assert trial_proc.returncode == 0, trial_proc.stderr

    dispatch_proc = _run_cli(["dispatch", "recommend", "fix login bug"], cwd=project_root)

    assert dispatch_proc.returncode == 0, dispatch_proc.stderr
    assert "portable-auth-bug-agent" in dispatch_proc.stdout
    assert "recent shadow trial result" in dispatch_proc.stdout


def test_agent_trial_does_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "target"
    _prepare_target_project(project_root)
    _import_portable_agent(project_root, tmp_path, agent_id="portable-auth-bug-agent")
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize_login(value):\n    return value.strip()\n", encoding="utf-8")
    before = _sha256(source_path)

    trial_proc = _run_cli(["agent", "trial", "portable-auth-bug-agent", "fix login bug"], cwd=project_root)
    assert trial_proc.returncode == 0, trial_proc.stderr
    saved_path = next((project_root / ".cambrian" / "agents" / "trials").glob("trial_*.yaml"))
    show_proc = _run_cli(["agent", "trial-show", str(saved_path)], cwd=project_root)
    status_proc = _run_cli(["status"], cwd=project_root)

    assert show_proc.returncode == 0, show_proc.stderr
    assert status_proc.returncode == 0, status_proc.stderr
    assert _sha256(source_path) == before
