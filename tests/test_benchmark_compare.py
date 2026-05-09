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


def _report_payload(workset_name: str, by_mode: dict, best_mode: str | None) -> dict:
    return {
        "schema_version": "1.0.0",
        "generated_at": "2026-04-21T00:00:00+00:00",
        "report_id": f"report-{workset_name}-{best_mode or 'none'}",
        "workset_name": workset_name,
        "modes": list(by_mode),
        "totals": {"cases": 2, "results": len(by_mode) * 2, "modes": len(by_mode)},
        "by_mode": by_mode,
        "by_case": {},
        "best_mode": best_mode,
        "summary": [],
        "next_actions": [],
        "warnings": [],
        "errors": [],
    }


def _write_report(
    project_root: Path,
    workset_name: str,
    by_mode: dict,
    best_mode: str | None = "cambrian_full",
    *,
    latest: bool = False,
    name: str = "fixture",
) -> Path:
    payload = _report_payload(workset_name, by_mode, best_mode)
    report_path = project_root / ".cambrian" / "benchmarks" / "reports" / f"report_{name}.yaml"
    _write_yaml(report_path, payload)
    if latest:
        _write_yaml(project_root / ".cambrian" / "benchmarks" / "reports" / "latest.yaml", payload)
    return report_path


def _mode(
    *,
    validated: float | None,
    adopted: float | None,
    regression_free: float | None,
    intervention: float | None,
    autonomy: float | None,
    duration: float | None,
) -> dict:
    return {
        "validated_proposal_rate": validated,
        "adoption_rate": adopted,
        "regression_free_apply_rate": regression_free,
        "human_intervention_rate": intervention,
        "validation_autonomy_rate": autonomy,
        "median_duration_seconds": duration,
    }


def _baseline_metrics() -> dict:
    return {
        "cambrian_full": _mode(
            validated=0.5,
            adopted=0.4,
            regression_free=1.0,
            intervention=0.5,
            autonomy=0.3,
            duration=300,
        )
    }


def _save_baseline(project_root: Path, workset_name: str, by_mode: dict | None = None, best_mode: str | None = "cambrian_full") -> Path:
    report_path = _write_report(project_root, workset_name, by_mode or _baseline_metrics(), best_mode, name="baseline_source")
    proc = _run_cli(["benchmark", "baseline-save", workset_name, "--report", str(report_path), "--json"], cwd=project_root)
    assert proc.returncode == 0, proc.stderr
    return Path(json.loads(proc.stdout)["saved_path"])


def test_baseline_save_from_report(tmp_path: Path) -> None:
    report_path = _write_report(tmp_path, "auth-bug-workset", _baseline_metrics(), "cambrian_full")

    proc = _run_cli(["benchmark", "baseline-save", "auth-bug-workset", "--report", str(report_path), "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["baseline"]["workset_name"] == "auth-bug-workset"
    assert payload["baseline"]["best_mode"] == "cambrian_full"
    assert payload["baseline"]["by_mode"]["cambrian_full"]["validated_proposal_rate"] == 0.5
    assert Path(payload["saved_path"]).exists()


def test_baselines_list_filters_workset(tmp_path: Path) -> None:
    _save_baseline(tmp_path, "auth-bug-workset")
    _save_baseline(tmp_path, "docs-workset", {"raw_ai": _mode(validated=0.2, adopted=0.1, regression_free=None, intervention=0.8, autonomy=0.1, duration=500)}, "raw_ai")

    proc = _run_cli(["benchmark", "baselines", "--workset", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    baselines = json.loads(proc.stdout)["baselines"]
    assert len(baselines) == 1
    assert baselines[0]["workset_name"] == "auth-bug-workset"


def test_compare_current_vs_baseline_improved_and_save(tmp_path: Path) -> None:
    _save_baseline(tmp_path, "auth-bug-workset")
    _write_report(
        tmp_path,
        "auth-bug-workset",
        {
            "cambrian_full": _mode(
                validated=0.7,
                adopted=0.6,
                regression_free=1.0,
                intervention=0.3,
                autonomy=0.5,
                duration=240,
            )
        },
        "cambrian_full",
        latest=True,
        name="current",
    )

    proc = _run_cli(["benchmark", "compare", "auth-bug-workset", "--save", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["verdict"] == "improved"
    assert report["gate_status"] == "green"
    assert report["mode_compares"][0]["deltas"][0]["improved"] is True
    assert Path(report["saved_path"]).exists()
    assert (tmp_path / ".cambrian" / "benchmarks" / "latest_compare.yaml").exists()


def test_compare_current_vs_baseline_regressed(tmp_path: Path) -> None:
    _save_baseline(tmp_path, "auth-bug-workset")
    _write_report(
        tmp_path,
        "auth-bug-workset",
        {
            "cambrian_full": _mode(
                validated=0.3,
                adopted=0.2,
                regression_free=0.7,
                intervention=0.8,
                autonomy=0.1,
                duration=380,
            )
        },
        "cambrian_full",
        latest=True,
        name="current",
    )

    proc = _run_cli(["benchmark", "compare", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["verdict"] == "regressed"
    assert report["gate_status"] == "red"


def test_compare_current_vs_baseline_mixed(tmp_path: Path) -> None:
    _save_baseline(tmp_path, "auth-bug-workset")
    _write_report(
        tmp_path,
        "auth-bug-workset",
        {
            "cambrian_full": _mode(
                validated=0.7,
                adopted=0.6,
                regression_free=1.0,
                intervention=0.7,
                autonomy=0.3,
                duration=380,
            )
        },
        "cambrian_full",
        latest=True,
        name="current",
    )

    proc = _run_cli(["benchmark", "compare", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["verdict"] == "mixed"
    assert report["gate_status"] == "yellow"


def test_compare_insufficient_data(tmp_path: Path) -> None:
    by_mode = {"cambrian_full": _mode(validated=None, adopted=None, regression_free=None, intervention=None, autonomy=None, duration=None)}
    _save_baseline(tmp_path, "auth-bug-workset", by_mode)
    _write_report(tmp_path, "auth-bug-workset", by_mode, "cambrian_full", latest=True, name="current")

    proc = _run_cli(["benchmark", "compare", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["verdict"] == "insufficient_data"
    assert report["gate_status"] == "gray"
    assert report["warnings"]


def test_compare_tracks_best_mode_changed(tmp_path: Path) -> None:
    _save_baseline(
        tmp_path,
        "auth-bug-workset",
        {"cambrian_full": _baseline_metrics()["cambrian_full"], "cambrian_guided": _baseline_metrics()["cambrian_full"]},
        "cambrian_guided",
    )
    _write_report(
        tmp_path,
        "auth-bug-workset",
        {
            "cambrian_full": _mode(validated=0.7, adopted=0.6, regression_free=1.0, intervention=0.3, autonomy=0.5, duration=240),
            "cambrian_guided": _baseline_metrics()["cambrian_full"],
        },
        "cambrian_full",
        latest=True,
        name="current",
    )

    proc = _run_cli(["benchmark", "compare", "auth-bug-workset", "--json"], cwd=tmp_path)

    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["best_mode_before"] == "cambrian_guided"
    assert report["best_mode_now"] == "cambrian_full"
    assert report["best_mode_changed"] is True


def test_status_benchmark_trend_and_source_immutability(tmp_path: Path) -> None:
    _prepare_target_project(tmp_path)
    source_path = tmp_path / "src" / "auth.py"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("def login():\n    return True\n", encoding="utf-8")
    before = _sha256(source_path)
    _save_baseline(tmp_path, "auth-bug-workset")
    _write_report(
        tmp_path,
        "auth-bug-workset",
        {"cambrian_full": _mode(validated=0.7, adopted=0.6, regression_free=1.0, intervention=0.3, autonomy=0.5, duration=240)},
        "cambrian_full",
        latest=True,
        name="current",
    )
    assert _run_cli(["benchmark", "compare", "auth-bug-workset", "--save"], cwd=tmp_path).returncode == 0

    status_proc = _run_cli(["status"], cwd=tmp_path)

    assert status_proc.returncode == 0, status_proc.stderr
    assert "Benchmark trend:" in status_proc.stdout
    assert "improved vs latest baseline" in status_proc.stdout
    assert _sha256(source_path) == before
