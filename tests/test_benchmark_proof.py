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


def _project_fixture(root: Path, *, lane: bool = True) -> None:
    _write_yaml(
        root / ".cambrian" / "project.yaml",
        {
            "schema_version": "1.0.0",
            "project": {"name": "auth-demo", "type": "python", "stack": ["python", "pytest"]},
            "test": {"command": "pytest -q"},
            "ai_work": {"primary_use_cases": ["bug_fix"]},
        },
    )
    _write_yaml(
        root / ".cambrian" / "profile.yaml",
        {
            "schema_version": "1.0.0",
            "created_at": "2026-04-29T00:00:00+00:00",
            "project_name": "auth-demo",
            "mode": "project",
        },
    )
    _write_yaml(
        root / ".cambrian" / "skills.yaml",
        {
            "schema_version": "1.0.0",
            "skills": [],
        },
    )
    if lane:
        _write_yaml(
            root / ".cambrian" / "lane" / "profile.yaml",
            {
                "schema_version": "1.0.0",
                "generated_at": "2026-04-29T00:00:00+00:00",
                "lane_id": "python-pytest-auth-bug-core",
                "label": "Python + pytest + auth/login bug fixes",
                "status": "strong",
                "project_name": "auth-demo",
                "workspace": str(root),
                "project_type": "python",
                "stack": ["python", "pytest"],
                "test_command": "pytest -q",
                "primary_use_cases": ["bug_fix"],
                "strongest_for": ["auth/login bug fixes"],
                "outside_scope_notes": [],
                "default_team": "auth-bug-team",
                "default_template": "auth-bug-template",
                "default_workset": "auth-bug-workset",
                "reasons": ["python pytest auth bug evidence"],
                "cautions": [],
                "warnings": [],
                "errors": [],
            },
        )


def _benchmark_report(root: Path, *, full: float = 0.7, raw: float = 0.2, bridge: float = 0.4, best: str = "cambrian_full") -> dict:
    report = {
        "schema_version": "1.0.0",
        "generated_at": "2026-04-29T00:00:00+00:00",
        "report_id": "benchmark-report-auth",
        "workset_name": "auth-bug-workset",
        "modes": ["raw_ai", "bridge_only", "cambrian_full"],
        "totals": {"cases": 5},
        "by_mode": {
            "raw_ai": {
                "total_cases": 5,
                "validated_proposal_rate": raw,
                "adoption_rate": 0.0,
                "regression_free_apply_rate": 0.5,
                "human_intervention_rate": 0.8,
                "median_duration_seconds": 300,
            },
            "bridge_only": {
                "total_cases": 5,
                "validated_proposal_rate": bridge,
                "adoption_rate": 0.1,
                "regression_free_apply_rate": 0.8,
                "human_intervention_rate": 0.5,
                "median_duration_seconds": 220,
            },
            "cambrian_full": {
                "total_cases": 5,
                "validated_proposal_rate": full,
                "adoption_rate": 0.5,
                "regression_free_apply_rate": 1.0,
                "human_intervention_rate": 0.2,
                "validation_autonomy_rate": 0.5,
                "median_duration_seconds": 100,
            },
        },
        "by_case": {},
        "best_mode": best,
        "summary": [f"{best} leads"],
        "next_actions": [],
        "warnings": [],
        "errors": [],
    }
    _write_yaml(root / ".cambrian" / "benchmarks" / "reports" / "latest.yaml", report)
    _write_yaml(root / ".cambrian" / "benchmarks" / "reports" / "report_auth.yaml", report)
    return report


def _compare(root: Path, verdict: str = "improved", before: str = "cambrian_guided", now: str = "cambrian_full") -> None:
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
            "best_mode_before": before,
            "best_mode_now": now,
            "best_mode_changed": before != now,
            "verdict": verdict,
            "gate_status": {"improved": "green", "mixed": "yellow", "regressed": "red"}.get(verdict, "gray"),
            "mode_compares": [],
            "summary": [f"compare verdict {verdict}"],
            "next_actions": [],
            "warnings": [],
            "errors": [],
        },
    )


def _autonomy(root: Path, *, full_validated: float = 0.6, full_autonomy: float = 0.5) -> None:
    _write_yaml(
        root / ".cambrian" / "benchmarks" / "latest_autonomy_board.yaml",
        {
            "schema_version": "1.0.0",
            "generated_at": "2026-04-29T00:00:00+00:00",
            "board_id": "board-auth",
            "workset_name": "auth-bug-workset",
            "modes": ["cambrian_guided", "cambrian_full"],
            "best_mode": "cambrian_full",
            "mode_summaries": [
                {
                    "mode": "cambrian_guided",
                    "total_cases": 5,
                    "validated_proposal_rate": 0.3,
                    "validation_autonomy_rate": 0.25,
                    "human_intervention_rate": 0.6,
                    "median_duration_seconds": 200,
                    "stage_counts": {"diagnosed": 2},
                    "stop_reason_counts": {"no patch candidate available": 2},
                    "summary": [],
                    "warnings": [],
                },
                {
                    "mode": "cambrian_full",
                    "total_cases": 5,
                    "validated_proposal_rate": full_validated,
                    "validation_autonomy_rate": full_autonomy,
                    "human_intervention_rate": 0.2,
                    "median_duration_seconds": 100,
                    "stage_counts": {"proposal_validated": 3},
                    "stop_reason_counts": {"ambiguous source selection": 1},
                    "summary": [],
                    "warnings": [],
                },
            ],
            "summary": ["cambrian_full leads"],
            "next_actions": [],
            "warnings": [],
            "errors": [],
        },
    )


def _bottleneck(root: Path) -> None:
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
                    "bottleneck_id": "bn-1",
                    "kind": "ambiguous_context_selection",
                    "mode": "all",
                    "severity": "high",
                    "frequency": 3,
                    "affected_cases": ["login-bug"],
                    "summary": "ambiguous source selection blocks auth edge cases",
                    "reasons": [],
                    "evidence_refs": [],
                    "warnings": [],
                }
            ],
            "suggestions": [
                {
                    "suggestion_id": "suggest-1",
                    "kind": "strengthen_context_hints",
                    "target": "auth files",
                    "priority": "high",
                    "confidence": 0.8,
                    "summary": "strengthen context hints for repeated auth files/tests",
                    "reasons": [],
                    "next_commands": [],
                    "evidence_refs": [],
                    "warnings": [],
                }
            ],
            "summary": {
                "top_bottleneck": "ambiguous_context_selection",
                "top_suggestion": "strengthen context hints for repeated auth files/tests",
                "validated_proposal_rate": 0.6,
                "validation_autonomy_rate": 0.5,
                "human_intervention_rate": 0.2,
                "best_mode": "cambrian_full",
            },
            "warnings": [],
            "errors": [],
        },
    )


def _metrics(root: Path, *, repeat: float = 0.1, reuse: float = 0.12) -> None:
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
                "validated_proposal_rate": 0.6,
                "adoption_rate": 0.5,
                "regression_free_apply_rate": 1.0,
                "median_time_to_validated_proposal": 90,
                "human_intervention_rate": 0.2,
                "validation_autonomy_rate": 0.5,
                "reuse_lift": reuse,
                "repeat_task_improvement_rate": repeat,
            },
            "counts": {},
            "warnings": [],
            "errors": [],
        },
    )


def _full_evidence(root: Path) -> None:
    _project_fixture(root)
    _benchmark_report(root)
    _compare(root)
    _autonomy(root)
    _bottleneck(root)
    _metrics(root)


def test_proof_pack_builds_from_available_sources(tmp_path: Path) -> None:
    _full_evidence(tmp_path)

    proc = _run_cli(["benchmark", "proof", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["workset_name"] == "auth-bug-workset"
    assert payload["best_mode"] == "cambrian_full"
    assert payload["source_refs"]["benchmark_report_ref"]
    assert payload["key_metrics"]["validated_proposal_rate"] == 0.7
    assert len(payload["claims"]) >= 3


def test_proof_wins_now_verdict(tmp_path: Path) -> None:
    _full_evidence(tmp_path)

    payload = json.loads(_run_cli(["benchmark", "proof", "auth-bug-workset", "--json"], cwd=tmp_path).stdout)

    assert payload["current_verdict"] == "wins_now"
    assert "cambrian_full" in payload["why_it_wins"][0]


def test_proof_promising_verdict_with_missing_compare(tmp_path: Path) -> None:
    _project_fixture(tmp_path)
    _benchmark_report(tmp_path)
    _autonomy(tmp_path)
    _metrics(tmp_path)

    payload = json.loads(_run_cli(["benchmark", "proof", "auth-bug-workset", "--json"], cwd=tmp_path).stdout)

    assert payload["current_verdict"] == "promising"
    assert any("compare" in warning for warning in payload["warnings"])


def test_proof_mixed_verdict_when_full_loses_to_bridge_only(tmp_path: Path) -> None:
    _project_fixture(tmp_path)
    _benchmark_report(tmp_path, full=0.55, raw=0.2, bridge=0.8, best="bridge_only")
    _compare(tmp_path, verdict="mixed", before="bridge_only", now="bridge_only")
    _autonomy(tmp_path, full_validated=0.4, full_autonomy=0.2)
    _metrics(tmp_path)

    payload = json.loads(_run_cli(["benchmark", "proof", "auth-bug-workset", "--json"], cwd=tmp_path).stdout)

    assert payload["current_verdict"] == "mixed"


def test_proof_regressed_verdict(tmp_path: Path) -> None:
    _full_evidence(tmp_path)
    _compare(tmp_path, verdict="regressed", before="cambrian_full", now="raw_ai")

    payload = json.loads(_run_cli(["benchmark", "proof", "auth-bug-workset", "--json"], cwd=tmp_path).stdout)

    assert payload["current_verdict"] == "regressed"


def test_proof_insufficient_data_verdict(tmp_path: Path) -> None:
    _project_fixture(tmp_path, lane=False)

    payload = json.loads(_run_cli(["benchmark", "proof", "auth-bug-workset", "--json"], cwd=tmp_path).stdout)

    assert payload["current_verdict"] == "insufficient_data"
    assert payload["warnings"]


def test_proof_next_one_fix_from_bottleneck(tmp_path: Path) -> None:
    _full_evidence(tmp_path)

    payload = json.loads(_run_cli(["benchmark", "proof", "auth-bug-workset", "--json"], cwd=tmp_path).stdout)

    assert payload["next_one_fix"] == "strengthen context hints for repeated auth files/tests"
    assert payload["where_it_fails"]


def test_proof_save_yaml_and_markdown_and_show(tmp_path: Path) -> None:
    _full_evidence(tmp_path)

    proc = _run_cli(["benchmark", "proof", "auth-bug-workset", "--save", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    yaml_path = Path(payload["saved_yaml_path"])
    md_path = Path(payload["saved_markdown_path"])
    assert yaml_path.exists()
    assert md_path.exists()
    assert "Cambrian Benchmark Proof Pack" in md_path.read_text(encoding="utf-8")

    show = _run_cli(["benchmark", "proof-show", str(yaml_path)], cwd=tmp_path)
    assert show.returncode == 0, show.stderr
    assert "Benchmark Proof Pack" in show.stdout
    assert "Current verdict:" in show.stdout
    assert _read_yaml(yaml_path)["current_verdict"] == "wins_now"


def test_status_shows_latest_proof_summary(tmp_path: Path) -> None:
    _full_evidence(tmp_path)
    proc = _run_cli(["benchmark", "proof", "auth-bug-workset", "--save", "--json"], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr

    status = _run_cli(["status"], cwd=tmp_path)

    assert status.returncode == 0, status.stderr
    assert "Benchmark proof:" in status.stdout
    assert "auth-bug-workset -> wins_now" in status.stdout
    assert "next fix" in status.stdout


def test_proof_commands_do_not_mutate_source_files(tmp_path: Path) -> None:
    _full_evidence(tmp_path)
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def normalize_username(username):\n    return username\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")

    proc = _run_cli(["benchmark", "proof", "auth-bug-workset", "--save"], cwd=tmp_path)
    show = _run_cli(["benchmark", "proof-show", "latest"], cwd=tmp_path)
    status = _run_cli(["status"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert show.returncode == 0, show.stderr
    assert status.returncode == 0, status.stderr
    assert source.read_text(encoding="utf-8") == before
