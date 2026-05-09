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


def _entry(case_id: str, stage: str | None, stop_reason: str | None, *, warnings: list[str] | None = None) -> dict:
    return {
        "case_id": case_id,
        "case_name": case_id,
        "mode": "cambrian_full",
        "replay_ref": f".cambrian/benchmarks/replays/replay_{case_id}.yaml",
        "status": "partial" if stop_reason else "completed",
        "autonomy_stage_reached": stage,
        "stop_reason": stop_reason,
        "validated_proposal": stage == "proposal_validated",
        "validation_autonomy": stage == "proposal_validated",
        "human_intervention": False,
        "duration_seconds": 10,
        "warnings": warnings or [],
        "errors": [],
    }


def _seed_replay(project_root: Path, *, mode: str, entries: list[dict], created_at: str = "2026-04-21T00:00:00+00:00") -> None:
    for entry in entries:
        entry["mode"] = mode
    validated = [entry.get("validated_proposal") for entry in entries]
    autonomy = [entry.get("validation_autonomy") for entry in entries]
    human = [entry.get("human_intervention") for entry in entries]
    stage_counts: dict[str, int] = {}
    stop_counts: dict[str, int] = {}
    for entry in entries:
        stage = entry.get("autonomy_stage_reached")
        if stage:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        stop = entry.get("stop_reason")
        if stop:
            stop_counts[stop] = stop_counts.get(stop, 0) + 1

    def rate(values: list) -> float | None:
        known = [value for value in values if value is not None]
        if not known:
            return None
        return round(sum(1 for value in known if value) / len(known), 4)

    _write_yaml(
        project_root / ".cambrian" / "benchmarks" / "workset_replays" / f"replay_auth-bug-workset_{mode}.yaml",
        {
            "schema_version": "1.0.0",
            "replay_id": f"workset-replay-auth-bug-workset-{mode}",
            "created_at": created_at,
            "workset_name": "auth-bug-workset",
            "mode": mode,
            "total_cases": len(entries),
            "entries": entries,
            "stage_counts": stage_counts,
            "stop_reason_counts": stop_counts,
            "summary": {
                "validated_proposal_rate": rate(validated),
                "validation_autonomy_rate": rate(autonomy),
                "human_intervention_rate": rate(human),
                "median_duration_seconds": 10,
            },
            "warnings": [],
            "errors": [],
        },
    )


def _seed_board(project_root: Path, *, guided_rate: float = 0.0, full_rate: float = 0.5) -> None:
    payload = {
        "schema_version": "1.0.0",
        "generated_at": "2026-04-21T00:00:00+00:00",
        "board_id": "board-auth-bug-workset",
        "workset_name": "auth-bug-workset",
        "modes": ["cambrian_guided", "cambrian_full"],
        "mode_summaries": [
            {
                "mode": "cambrian_guided",
                "total_cases": 3,
                "validated_proposal_rate": guided_rate,
                "validation_autonomy_rate": guided_rate,
                "human_intervention_rate": 0.0,
                "median_duration_seconds": 10,
                "stage_counts": {},
                "stop_reason_counts": {"no safe prefilled patch candidate was available": 3},
                "summary": [],
                "warnings": [],
            },
            {
                "mode": "cambrian_full",
                "total_cases": 3,
                "validated_proposal_rate": full_rate,
                "validation_autonomy_rate": full_rate,
                "human_intervention_rate": 0.0,
                "median_duration_seconds": 10,
                "stage_counts": {},
                "stop_reason_counts": {"ambiguous source selection": 2},
                "summary": [],
                "warnings": [],
            },
        ],
        "best_mode": "cambrian_full",
        "summary": [],
        "next_actions": [],
        "warnings": [],
        "errors": [],
    }
    _write_yaml(project_root / ".cambrian" / "benchmarks" / "latest_autonomy_board.yaml", payload)


def _seed_project_with_replays(project_root: Path, entries: list[dict], *, mode: str = "cambrian_full") -> Path:
    _prepare_target_project(project_root)
    source_path = project_root / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def normalize(username):\n    return username\n", encoding="utf-8")
    _seed_replay(project_root, mode=mode, entries=entries)
    _seed_board(project_root)
    return source_path


def test_detect_ambiguous_context_selection(tmp_path: Path) -> None:
    _seed_project_with_replays(
        tmp_path,
        [
            _entry("case-a", "request_start", "ambiguous source selection"),
            _entry("case-b", "request_start", "ambiguous source selection"),
            _entry("case-c", "proposal_validated", None),
        ],
    )

    proc = _run_cli(["benchmark", "bottlenecks", "auth-bug-workset", "--mode", "cambrian_full", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    kinds = [item["kind"] for item in report["bottlenecks"]]
    assert "ambiguous_context_selection" in kinds


def test_detect_missing_patch_candidate_and_suggestion(tmp_path: Path) -> None:
    _seed_project_with_replays(
        tmp_path,
        [
            _entry("case-a", "diagnosed", "no safe prefilled patch candidate was available"),
            _entry("case-b", "diagnosed", "no safe prefilled patch candidate was available"),
            _entry("case-c", "proposal_validated", None),
        ],
    )

    proc = _run_cli(["benchmark", "bottlenecks", "auth-bug-workset", "--mode", "cambrian_full", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert "missing_patch_candidate" in [item["kind"] for item in report["bottlenecks"]]
    assert "add_bridge_patch_candidate" in [item["kind"] for item in report["suggestions"]]


def test_detect_bridge_dependency_gap(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    _seed_replay(
        tmp_path,
        mode="cambrian_guided",
        entries=[
            _entry("case-a", "diagnosed", "no safe prefilled patch candidate was available"),
            _entry("case-b", "diagnosed", "no safe prefilled patch candidate was available"),
            _entry("case-c", "diagnosed", "no safe prefilled patch candidate was available"),
        ],
    )
    _seed_replay(
        tmp_path,
        mode="cambrian_full",
        entries=[
            _entry("case-a", "proposal_validated", None),
            _entry("case-b", "proposal_validated", None),
            _entry("case-c", "diagnosed", "no safe prefilled patch candidate was available"),
        ],
    )
    _seed_board(tmp_path, guided_rate=0.0, full_rate=0.667)

    proc = _run_cli(["benchmark", "bottlenecks", "auth-bug-workset", "--mode", "all", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert "bridge_dependency_gap" in [item["kind"] for item in report["bottlenecks"]]
    assert "improve_bridge_coverage" in [item["kind"] for item in report["suggestions"]]


def test_detect_validation_failure_cluster(tmp_path: Path) -> None:
    _seed_project_with_replays(
        tmp_path,
        [
            _entry("case-a", "patch_intent_ready", "old_text was not found in target file"),
            _entry("case-b", "patch_intent_ready", "validation failed before proposal"),
            _entry("case-c", "proposal_validated", None),
        ],
    )

    proc = _run_cli(["benchmark", "bottlenecks", "auth-bug-workset", "--mode", "cambrian_full", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert "validation_failure_cluster" in [item["kind"] for item in report["bottlenecks"]]
    assert "improve_validation_support" in [item["kind"] for item in report["suggestions"]]


def test_detect_team_and_review_support_gap(tmp_path: Path) -> None:
    _seed_project_with_replays(
        tmp_path,
        [
            _entry("case-a", "patch_intent_ready", "review support missing for team fit"),
            _entry("case-b", "patch_intent_ready", "review support missing for team fit"),
            _entry("case-c", "proposal_validated", None),
        ],
    )

    proc = _run_cli(["benchmark", "bottlenecks", "auth-bug-workset", "--mode", "cambrian_full", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    kinds = [item["kind"] for item in report["bottlenecks"]]
    assert "weak_team_fit" in kinds
    assert "review_support_gap" in kinds


def test_priority_confidence_and_save(tmp_path: Path) -> None:
    _seed_project_with_replays(
        tmp_path,
        [
            _entry("case-a", "request_start", "ambiguous source selection"),
            _entry("case-b", "request_start", "ambiguous source selection"),
            _entry("case-c", "proposal_validated", None),
        ],
    )

    proc = _run_cli(["benchmark", "bottlenecks", "auth-bug-workset", "--mode", "cambrian_full", "--save", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    top = report["bottlenecks"][0]
    suggestion = report["suggestions"][0]
    assert top["severity"] == "high"
    assert suggestion["confidence"] >= 0.7
    assert Path(report["saved_path"]).exists()
    assert list((tmp_path / ".cambrian" / "benchmarks" / "bottlenecks").glob("bottlenecks_*.yaml"))


def test_status_and_metrics_surface_latest_bottleneck(tmp_path: Path) -> None:
    source_path = _seed_project_with_replays(
        tmp_path,
        [
            _entry("case-a", "request_start", "ambiguous source selection"),
            _entry("case-b", "request_start", "ambiguous source selection"),
            _entry("case-c", "proposal_validated", None),
        ],
    )
    before = _sha256(source_path)
    assert _run_cli(["benchmark", "bottlenecks", "auth-bug-workset", "--save"], cwd=tmp_path).returncode == 0

    status_proc = _run_cli(["status"], cwd=tmp_path)
    metrics_proc = _run_cli(["metrics", "week"], cwd=tmp_path)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Autonomy bottleneck:" in status_proc.stdout
    assert "ambiguous_context_selection" in status_proc.stdout
    assert metrics_proc.returncode == 0, metrics_proc.stderr
    assert "Top bottleneck this week:" in metrics_proc.stdout
    assert "ambiguous_context_selection" in metrics_proc.stdout
    assert _sha256(source_path) == before
