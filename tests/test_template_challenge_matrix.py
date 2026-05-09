from __future__ import annotations

import copy
import json
from pathlib import Path

from engine.project_template_challenge_matrix import (
    TemplateChallengeCandidateRun,
    _compare_pair,
)
from test_agent_transfer import _read_yaml, _run_cli
from test_harness_templates import _write_yaml
from test_template_qualification import _prepare_project, _sha256


def _set_lane_playbook(project_root: Path, *, canary: str | None = "auth-bug-template-local") -> None:
    _write_yaml(
        project_root / ".cambrian" / "lane" / "playbook.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-05-01T00:00:00+00:00",
            "lane_id": "python-pytest-auth-bug-core",
            "label": "Python + pytest + auth/login bug fixes",
            "default_template_name": "imported-auth-bug-template",
            "backup_templates": [],
            "retired_templates": [],
            "canary_template_name": canary,
            "canary_stage_id": "stage-auth-local" if canary else None,
            "canary_status": "active" if canary else None,
            "source_decision_ref": None,
            "notes": [],
            "warnings": [],
            "errors": [],
        },
    )


def _add_template(project_root: Path, name: str, *, has_context: bool = True) -> None:
    store_path = project_root / ".cambrian" / "templates" / "templates.yaml"
    store = _read_yaml(store_path)
    base = copy.deepcopy(next(item for item in store["templates"] if item["name"] == "auth-bug-template-local"))
    base["template_id"] = name
    base["name"] = name
    base["description"] = f"{name} challenger"
    base["source_kind"] = "local"
    base["source_origin"] = {
        "parent_template_name": "auth-bug-template-local",
        "root_template_name": "imported-auth-bug-template",
    }
    if has_context:
        base["context_defaults"] = {
            "preferred_context_paths": ["src/auth.py"],
            "preferred_test_paths": ["tests/test_auth.py"],
        }
    else:
        base.pop("context_defaults", None)
        base["policy_defaults"] = {
            "test_first_practice": False,
            "narrow_change_scope": False,
            "increase_review_support": False,
        }
    store["templates"].append(base)
    _write_yaml(store_path, store)


def _write_challengers(project_root: Path, challengers: list[dict | str]) -> None:
    _write_yaml(
        project_root / ".cambrian" / "templates" / "challengers.yaml",
        {
            "schema_version": "1.0.0",
            "updated_at": "2026-05-01T00:00:00+00:00",
            "challengers": challengers,
        },
    )


def _ready_project(project_root: Path, *, challengers: list[dict | str] | None = None) -> Path:
    source = _prepare_project(project_root)
    _set_lane_playbook(project_root)
    _add_template(project_root, "auth-bug-template-local-v2", has_context=True)
    _add_template(project_root, "auth-bug-template-safe", has_context=False)
    _write_challengers(
        project_root,
        challengers
        if challengers is not None
        else [
            {"template_name": "auth-bug-template-local-v2", "status": "queued"},
            {"template_name": "auth-bug-template-safe", "status": "queued"},
        ],
    )
    return source


def _run(name: str, mode: str, **metrics: float | None) -> TemplateChallengeCandidateRun:
    return TemplateChallengeCandidateRun(
        template_name=name,
        template_id=name,
        role="queued_challenger",
        mode=mode,
        replay_ref=None,
        status="completed",
        validated_proposal_rate=metrics.get("validated"),
        human_intervention_rate=metrics.get("intervention"),
        validation_autonomy_rate=metrics.get("autonomy"),
        median_duration_seconds=metrics.get("duration"),
        stage_counts={},
        stop_reason_counts={},
        warnings=[],
        errors=[],
    )


def test_matrix_includes_stable_canary_and_queued_challengers(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _ready_project(project_root)

    proc = _run_cli(
        ["template", "challenge-matrix", "--workset", "auth-bug-workset", "--save", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    roles = {(run["template_name"], run["role"]) for run in payload["candidate_runs"]}
    assert ("imported-auth-bug-template", "stable_default") in roles
    assert ("auth-bug-template-local", "active_canary") in roles
    assert ("auth-bug-template-local-v2", "queued_challenger") in roles
    assert set(payload["queued_challengers"]) == {"auth-bug-template-local-v2", "auth-bug-template-safe"}
    assert Path(project_root / payload["saved_path"]).exists()


def test_no_queued_challengers_warning(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _ready_project(project_root, challengers=[])

    proc = _run_cli(
        ["template", "challenge-matrix", "--workset", "auth-bug-workset", "--mode", "guided", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["next_best_challenger"] is None
    assert "no queued challengers found" in payload["warnings"]


def test_pairwise_stronger_mixed_and_inconclusive_verdicts() -> None:
    stronger = _compare_pair(
        _run("challenger", "cambrian_guided", validated=0.8, intervention=0.1, autonomy=0.8, duration=90),
        _run("stable", "cambrian_guided", validated=0.6, intervention=0.2, autonomy=0.6, duration=100),
        "challenger",
        "stable",
        "cambrian_guided",
    )
    mixed = _compare_pair(
        _run("challenger", "cambrian_full", validated=0.8, intervention=0.4, autonomy=0.7, duration=120),
        _run("stable", "cambrian_full", validated=0.6, intervention=0.1, autonomy=0.7, duration=90),
        "challenger",
        "stable",
        "cambrian_full",
    )
    inconclusive = _compare_pair(
        _run("challenger", "cambrian_guided", validated=None, intervention=None, autonomy=None, duration=None),
        _run("stable", "cambrian_guided", validated=None, intervention=None, autonomy=None, duration=None),
        "challenger",
        "stable",
        "cambrian_guided",
    )

    assert stronger.verdict == "stronger"
    assert mixed.verdict == "mixed"
    assert inconclusive.verdict == "inconclusive"


def test_ranking_selects_next_best_challenger(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _ready_project(project_root)

    proc = _run_cli(
        ["template", "challenge-matrix", "--workset", "auth-bug-workset", "--mode", "both", "--json"],
        cwd=project_root,
    )

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ranked_challengers"][0] == "auth-bug-template-local-v2"
    assert payload["next_best_challenger"] == "auth-bug-template-local-v2"


def test_challenge_board_consumes_latest_matrix(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _ready_project(project_root)
    matrix = _run_cli(
        ["template", "challenge-matrix", "--workset", "auth-bug-workset", "--save", "--json"],
        cwd=project_root,
    )
    assert matrix.returncode == 0, matrix.stderr

    board = _run_cli(["template", "challenge-board", "--json"], cwd=project_root)

    assert board.returncode == 0, board.stderr
    payload = json.loads(board.stdout)
    assert payload["matrix_backed"] is True
    assert payload["next_best_challenger"] == "auth-bug-template-local-v2"


def test_show_challengers_status_and_harness_surface_matrix(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _ready_project(project_root)
    matrix = _run_cli(
        ["template", "challenge-matrix", "--workset", "auth-bug-workset", "--save"],
        cwd=project_root,
    )
    assert matrix.returncode == 0, matrix.stderr

    show = _run_cli(["template", "show", "auth-bug-template-local-v2"], cwd=project_root)
    challengers = _run_cli(["template", "challengers"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)
    harness = _run_cli(["harness", "show"], cwd=project_root)

    assert show.returncode == 0, show.stderr
    assert challengers.returncode == 0, challengers.stderr
    assert status.returncode == 0, status.stderr
    assert harness.returncode == 0, harness.stderr
    assert "Challenger matrix" in show.stdout
    assert "Template Challengers" in challengers.stdout
    assert "auth-bug-template-local-v2" in status.stdout
    assert "Challenger matrix" in harness.stdout


def test_challenge_matrix_does_not_mutate_project_source(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = _ready_project(project_root)
    before = _sha256(source)

    matrix = _run_cli(
        ["template", "challenge-matrix", "--workset", "auth-bug-workset", "--save"],
        cwd=project_root,
    )
    board = _run_cli(["template", "challenge-board"], cwd=project_root)
    show = _run_cli(["template", "show", "auth-bug-template-local-v2"], cwd=project_root)
    status = _run_cli(["status"], cwd=project_root)

    assert matrix.returncode == 0, matrix.stderr
    assert board.returncode == 0, board.stderr
    assert show.returncode == 0, show.stderr
    assert status.returncode == 0, status.stderr
    assert _sha256(source) == before
