from __future__ import annotations

import json
from pathlib import Path

import yaml

from test_agent_transfer import _run_cli


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _project_fixture(root: Path) -> None:
    _write_yaml(
        root / ".cambrian" / "project.yaml",
        {
            "schema_version": "1.0.0",
            "project": {"name": "auth-demo", "type": "python", "stack": ["python", "pytest"]},
            "test": {"command": "pytest -q"},
        },
    )
    _write_yaml(
        root / ".cambrian" / "profile.yaml",
        {"schema_version": "1.0.0", "project_name": "auth-demo", "mode": "project"},
    )
    _write_yaml(root / ".cambrian" / "skills.yaml", {"schema_version": "1.0.0", "skills": []})


def _metrics(root: Path, *, validated: float = 0.35, human: float = 0.44, autonomy: float = 0.2, reuse: float = 0.02, repeat: float = 0.01) -> None:
    _write_yaml(
        root / ".cambrian" / "metrics" / "latest.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-29T00:00:00+00:00",
            "week_id": "2026_W18",
            "project_name": "auth-demo",
            "workspace": str(root),
            "metrics": [],
            "summary": {
                "validated_proposal_rate": validated,
                "adoption_rate": 0.2,
                "regression_free_apply_rate": 1.0,
                "median_time_to_validated_proposal": 600,
                "human_intervention_rate": human,
                "validation_autonomy_rate": autonomy,
                "lead_agent_hit_rate": 0.7,
                "team_template_recommendation_hit_rate": 0.6,
                "reuse_lift": reuse,
                "repeat_task_improvement_rate": repeat,
            },
            "counts": {},
            "warnings": [],
            "errors": [],
        },
    )


def _compare(root: Path, verdict: str = "mixed") -> None:
    _write_yaml(
        root / ".cambrian" / "benchmarks" / "latest_compare.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-29T00:00:00+00:00",
            "compare_id": "compare-auth",
            "workset_name": "auth-bug-workset",
            "baseline_ref": "baseline.yaml",
            "current_report_ref": ".cambrian/benchmarks/reports/latest.yaml",
            "compared_modes": ["cambrian_full"],
            "best_mode_before": "cambrian_guided",
            "best_mode_now": "cambrian_full",
            "best_mode_changed": True,
            "verdict": verdict,
            "gate_status": "yellow",
            "mode_compares": [],
            "summary": [],
            "next_actions": [],
            "warnings": [],
            "errors": [],
        },
    )


def _proof(root: Path, *, validated: float = 0.35, human: float = 0.44, autonomy: float = 0.2, reuse: float = 0.02, repeat: float = 0.01) -> None:
    _write_yaml(
        root / ".cambrian" / "benchmarks" / "proof" / "latest.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-29T00:00:00+00:00",
            "proof_id": "proof-auth",
            "project_name": "auth-demo",
            "workspace": str(root),
            "workset_name": "auth-bug-workset",
            "strongest_lane": "Python + pytest + auth/login bug fixes",
            "lane_status": "strong",
            "compared_modes": ["raw_ai", "bridge_only", "cambrian_full"],
            "best_mode": "cambrian_full",
            "previous_best_mode": "cambrian_guided",
            "best_mode_changed": True,
            "key_metrics": {
                "validated_proposal_rate": validated,
                "adoption_rate": 0.2,
                "regression_free_apply_rate": 1.0,
                "median_time_to_validated_proposal": 600,
                "human_intervention_rate": human,
                "validation_autonomy_rate": autonomy,
                "reuse_lift": reuse,
                "repeat_task_improvement_rate": repeat,
            },
            "claims": [],
            "current_verdict": "promising",
            "why_it_wins": [],
            "where_it_fails": [],
            "next_one_fix": "strengthen context hints for repeated auth files/tests",
            "source_refs": {},
            "warnings": [],
            "errors": [],
        },
    )


def _bottleneck(root: Path, *, kind: str = "ambiguous_context_selection", frequency: int = 4) -> None:
    _write_yaml(
        root / ".cambrian" / "benchmarks" / "latest_bottleneck.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-29T00:00:00+00:00",
            "report_id": "bottlenecks-auth",
            "workset_name": "auth-bug-workset",
            "mode": "all",
            "source_refs": {},
            "bottlenecks": [
                {
                    "bottleneck_id": "bottleneck-auth",
                    "kind": kind,
                    "mode": "all",
                    "severity": "high",
                    "frequency": frequency,
                    "affected_cases": ["login-bug", "auth-edge"],
                    "summary": f"{frequency} cases are blocked by {kind}",
                    "reasons": [f"{kind} affected {frequency} case(s)"],
                    "evidence_refs": [],
                    "warnings": [],
                }
            ],
            "suggestions": [
                {
                    "suggestion_id": "suggestion-context",
                    "kind": "strengthen_context_hints",
                    "target": "auth-bug-workset",
                    "priority": "high",
                    "confidence": 0.8,
                    "summary": "strengthen context hints for repeated auth files/tests",
                    "reasons": [f"{kind} affected {frequency} case(s)"],
                    "next_commands": ["cambrian bridge context-hints"],
                    "evidence_refs": [],
                    "warnings": [],
                }
            ],
            "summary": {
                "top_bottleneck": kind,
                "top_suggestion": "strengthen context hints for repeated auth files/tests",
                "validated_proposal_rate": 0.35,
                "validation_autonomy_rate": 0.2,
                "human_intervention_rate": 0.44,
                "best_mode": "cambrian_full",
            },
            "warnings": [],
            "errors": [],
        },
    )


def _evidence(root: Path) -> None:
    _project_fixture(root)
    _metrics(root)
    _compare(root)
    _proof(root)
    _bottleneck(root)


def _start_cycle(root: Path) -> dict:
    result = _run_cli(["improve", "next", "auth-bug-workset", "--json"], cwd=root)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_improve_next_creates_cycle(tmp_path: Path) -> None:
    _evidence(tmp_path)

    payload = _start_cycle(tmp_path)

    saved_path = Path(payload["saved_path"])
    assert saved_path.exists()
    assert payload["selected_bottleneck_kind"] == "ambiguous_context_selection"
    assert payload["selected_fix_kind"] == "strengthen_context_hints"
    assert payload["before_snapshot"]["validated_proposal_rate"] == 0.35
    assert "reduce ambiguity" in payload["hypothesis"]


def test_only_one_active_cycle_allowed(tmp_path: Path) -> None:
    _evidence(tmp_path)
    _start_cycle(tmp_path)

    result = _run_cli(["improve", "next", "auth-bug-workset"], cwd=tmp_path)

    assert result.returncode == 1
    assert "already active" in result.stderr


def test_improve_show_works(tmp_path: Path) -> None:
    _evidence(tmp_path)
    payload = _start_cycle(tmp_path)

    result = _run_cli(["improve", "show", payload["cycle_id"]], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Improvement Cycle" in result.stdout
    assert "ambiguous_context_selection" in result.stdout


def test_improve_evaluate_improved(tmp_path: Path) -> None:
    _evidence(tmp_path)
    payload = _start_cycle(tmp_path)
    _metrics(tmp_path, validated=0.49, human=0.29, autonomy=0.36, reuse=0.08, repeat=0.1)
    _proof(tmp_path, validated=0.49, human=0.29, autonomy=0.36, reuse=0.08, repeat=0.1)
    _bottleneck(tmp_path, frequency=2)

    result = _run_cli(["improve", "evaluate", payload["cycle_id"], "--json"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    evaluated = json.loads(result.stdout)
    assert evaluated["verdict"] == "improved"
    assert evaluated["after_snapshot"]["validated_proposal_rate"] == 0.49


def test_improve_evaluate_mixed(tmp_path: Path) -> None:
    _evidence(tmp_path)
    payload = _start_cycle(tmp_path)
    _metrics(tmp_path, validated=0.49, human=0.6, autonomy=0.36, reuse=0.01, repeat=0.02)
    _proof(tmp_path, validated=0.49, human=0.6, autonomy=0.36, reuse=0.01, repeat=0.02)
    _bottleneck(tmp_path, frequency=4)

    result = _run_cli(["improve", "evaluate", payload["cycle_id"], "--json"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    evaluated = json.loads(result.stdout)
    assert evaluated["verdict"] == "mixed"


def test_improve_evaluate_regressed(tmp_path: Path) -> None:
    _evidence(tmp_path)
    payload = _start_cycle(tmp_path)
    _metrics(tmp_path, validated=0.2, human=0.6, autonomy=0.1, reuse=-0.02, repeat=-0.05)
    _proof(tmp_path, validated=0.2, human=0.6, autonomy=0.1, reuse=-0.02, repeat=-0.05)
    _bottleneck(tmp_path, frequency=6)

    result = _run_cli(["improve", "evaluate", payload["cycle_id"], "--json"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    evaluated = json.loads(result.stdout)
    assert evaluated["verdict"] == "regressed"


def test_improve_evaluate_inconclusive(tmp_path: Path) -> None:
    _project_fixture(tmp_path)
    _bottleneck(tmp_path)
    payload = _start_cycle(tmp_path)

    result = _run_cli(["improve", "evaluate", payload["cycle_id"], "--json"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    evaluated = json.loads(result.stdout)
    assert evaluated["verdict"] == "inconclusive"


def test_improve_close_works(tmp_path: Path) -> None:
    _evidence(tmp_path)
    payload = _start_cycle(tmp_path)

    closed = _run_cli(["improve", "close", payload["cycle_id"], "--resolution", "context hints added"], cwd=tmp_path)
    assert closed.returncode == 0, closed.stderr

    started_again = _run_cli(["improve", "next", "auth-bug-workset", "--json"], cwd=tmp_path)
    assert started_again.returncode == 0, started_again.stderr


def test_status_improvement_summary(tmp_path: Path) -> None:
    _evidence(tmp_path)
    _start_cycle(tmp_path)

    result = _run_cli(["status"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Improvement cycle:" in result.stdout
    assert "ambiguous_context_selection" in result.stdout


def test_metrics_week_improvement_focus(tmp_path: Path) -> None:
    _evidence(tmp_path)
    _start_cycle(tmp_path)

    result = _run_cli(["metrics", "week"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Improvement focus this week:" in result.stdout
    assert "ambiguous_context_selection" in result.stdout


def test_source_immutability(tmp_path: Path) -> None:
    _evidence(tmp_path)
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")

    payload = _start_cycle(tmp_path)
    _run_cli(["improve", "show", payload["cycle_id"]], cwd=tmp_path)
    _run_cli(["improve", "evaluate", payload["cycle_id"]], cwd=tmp_path)
    _run_cli(["improve", "close", payload["cycle_id"], "--resolution", "record only"], cwd=tmp_path)

    assert source.read_text(encoding="utf-8") == before

