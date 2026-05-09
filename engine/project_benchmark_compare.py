"""Benchmark baseline과 current-vs-baseline 비교 게이트."""

from __future__ import annotations

import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_benchmarks import (
    BenchmarkReport,
    BenchmarkStore,
    default_benchmark_dir,
    default_reports_dir,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
COMPARE_METRICS = {
    "validated_proposal_rate": "higher_better",
    "adoption_rate": "higher_better",
    "regression_free_apply_rate": "higher_better",
    "human_intervention_rate": "lower_better",
    "validation_autonomy_rate": "higher_better",
    "median_duration_seconds": "lower_better",
}
RATE_THRESHOLD = 0.05
DURATION_THRESHOLD = 30.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    return secrets.token_hex(2)


def _slug(value: str, fallback: str = "item") -> str:
    import re

    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip().lower()).strip("-")
    return text or fallback


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("benchmark compare artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


@dataclass
class BenchmarkBaselineSnapshot:
    schema_version: str
    baseline_id: str
    saved_at: str
    workset_name: str
    source_report_ref: str | None
    source_report_generated_at: str | None
    modes: list[str]
    by_mode: dict[str, Any]
    best_mode: str | None
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkMetricDelta:
    key: str
    baseline_value: float | int | None
    current_value: float | int | None
    delta: float | int | None
    direction: str
    improved: bool | None
    summary: str
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkModeCompare:
    mode: str
    comparable: bool
    deltas: list[BenchmarkMetricDelta]
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["deltas"] = [delta.to_dict() for delta in self.deltas]
        return payload


@dataclass
class BenchmarkCompareReport:
    schema_version: str
    generated_at: str
    compare_id: str
    workset_name: str
    baseline_ref: str | None
    current_report_ref: str | None
    compared_modes: list[str]
    best_mode_before: str | None
    best_mode_now: str | None
    best_mode_changed: bool
    verdict: str
    gate_status: str
    mode_compares: list[BenchmarkModeCompare]
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode_compares"] = [item.to_dict() for item in self.mode_compares]
        return payload


def default_baselines_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "baselines"


def default_compares_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "compares"


class BenchmarkBaselineStore:
    """Benchmark baseline snapshot 저장소."""

    def save(self, snapshot: BenchmarkBaselineSnapshot, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), snapshot.to_dict())

    def load(self, path: Path) -> BenchmarkBaselineSnapshot:
        return _baseline_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, baselines_dir: Path) -> list[BenchmarkBaselineSnapshot]:
        snapshots: list[BenchmarkBaselineSnapshot] = []
        for path in sorted(Path(baselines_dir).glob("baseline_*.yaml")):
            payload = _load_yaml(path)
            if payload:
                snapshots.append(_baseline_from_dict(payload))
        snapshots.sort(key=lambda item: item.saved_at, reverse=True)
        return snapshots


class BenchmarkBaselineBuilder:
    """Benchmark report를 baseline snapshot으로 고정한다."""

    def from_report(self, report_path: Path) -> BenchmarkBaselineSnapshot:
        report = BenchmarkStore().load_report(Path(report_path).resolve())
        return BenchmarkBaselineSnapshot(
            schema_version=SCHEMA_VERSION,
            baseline_id=f"baseline-{_slug(report.workset_name)}-{_short_id()}",
            saved_at=_now(),
            workset_name=report.workset_name,
            source_report_ref=str(Path(report_path).resolve()),
            source_report_generated_at=report.generated_at,
            modes=list(report.modes),
            by_mode=dict(report.by_mode),
            best_mode=report.best_mode,
            notes=[],
            warnings=[],
            errors=[],
        )


class BenchmarkCompareStore:
    """Benchmark compare report 저장소."""

    def save(self, report: BenchmarkCompareReport, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent.parent / "latest_compare.yaml", report.to_dict())
        return saved

    def load(self, path: Path) -> BenchmarkCompareReport:
        return _compare_from_dict(_load_yaml(Path(path).resolve()))


class BenchmarkCompareBuilder:
    """Current benchmark report와 baseline snapshot을 비교한다."""

    def build(
        self,
        project_root: Path,
        workset_name: str,
        baseline_path: Path | None = None,
    ) -> BenchmarkCompareReport:
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        current_path = self._latest_report_path(root, workset_name)
        baseline = self._load_baseline(root, workset_name, baseline_path)
        current = BenchmarkStore().load_report(current_path)
        baseline_modes = set(baseline.by_mode)
        current_modes = set(current.by_mode)
        compared_modes = sorted(baseline_modes & current_modes)
        skipped_baseline = sorted(baseline_modes - current_modes)
        skipped_current = sorted(current_modes - baseline_modes)
        for mode in skipped_baseline:
            warnings.append(f"mode missing in current report: {mode}")
        for mode in skipped_current:
            warnings.append(f"new mode not in baseline: {mode}")
        mode_compares = [
            self._compare_mode(mode, baseline.by_mode.get(mode, {}), current.by_mode.get(mode, {}))
            for mode in compared_modes
        ]
        verdict = self._verdict(mode_compares)
        gate_status = {
            "improved": "green",
            "mixed": "yellow",
            "regressed": "red",
            "insufficient_data": "gray",
        }.get(verdict, "gray")
        if not compared_modes:
            warnings.append("no common modes between baseline and current report")
        summary = self._summary(verdict, mode_compares)
        return BenchmarkCompareReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            compare_id=f"benchmark-compare-{_short_id()}",
            workset_name=current.workset_name,
            baseline_ref=_relative(self._baseline_path_for_ref(root, baseline_path, baseline), root),
            current_report_ref=_relative(current_path, root),
            compared_modes=compared_modes,
            best_mode_before=baseline.best_mode,
            best_mode_now=current.best_mode,
            best_mode_changed=baseline.best_mode != current.best_mode,
            verdict=verdict,
            gate_status=gate_status,
            mode_compares=mode_compares,
            summary=summary,
            next_actions=[
                f"cambrian benchmark compare {current.workset_name} --save",
                f"cambrian benchmark report {current.workset_name}",
            ],
            warnings=_dedupe([*warnings, *[warning for item in mode_compares for warning in item.warnings]]),
            errors=errors,
        )

    def _latest_report_path(self, root: Path, workset_name: str) -> Path:
        latest = default_reports_dir(root) / "latest.yaml"
        if latest.exists():
            payload = _load_yaml(latest)
            if str(payload.get("workset_name") or "") == workset_name:
                return latest.resolve()
        candidates: list[Path] = []
        for path in default_reports_dir(root).glob("report_*.yaml"):
            payload = _load_yaml(path)
            if str(payload.get("workset_name") or "") == workset_name:
                candidates.append(path)
        if not candidates:
            raise FileNotFoundError(f"benchmark report not found for workset: {workset_name}")
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0].resolve()

    def _load_baseline(
        self,
        root: Path,
        workset_name: str,
        baseline_path: Path | None,
    ) -> BenchmarkBaselineSnapshot:
        path = self._resolve_baseline_path(root, workset_name, baseline_path)
        return BenchmarkBaselineStore().load(path)

    def _resolve_baseline_path(self, root: Path, workset_name: str, baseline_path: Path | None) -> Path:
        if baseline_path is not None:
            candidate = Path(baseline_path)
            if candidate.exists():
                return candidate.resolve()
            if (root / candidate).exists():
                return (root / candidate).resolve()
            name = str(baseline_path)
            for path in default_baselines_dir(root).glob("baseline_*.yaml"):
                payload = _load_yaml(path)
                if path.stem == name or str(payload.get("baseline_id") or "") == name:
                    return path.resolve()
            raise FileNotFoundError(f"benchmark baseline not found: {baseline_path}")
        baselines = [
            snapshot
            for snapshot in BenchmarkBaselineStore().list(default_baselines_dir(root))
            if snapshot.workset_name == workset_name
        ]
        if not baselines:
            raise FileNotFoundError(f"benchmark baseline not found for workset: {workset_name}")
        selected = baselines[0]
        for path in default_baselines_dir(root).glob("baseline_*.yaml"):
            payload = _load_yaml(path)
            if str(payload.get("baseline_id") or "") == selected.baseline_id:
                return path.resolve()
        raise FileNotFoundError(f"benchmark baseline artifact not found: {selected.baseline_id}")

    @staticmethod
    def _baseline_path_for_ref(root: Path, baseline_path: Path | None, baseline: BenchmarkBaselineSnapshot) -> Path:
        if baseline_path is not None:
            candidate = Path(baseline_path)
            if candidate.exists():
                return candidate.resolve()
            if (root / candidate).exists():
                return (root / candidate).resolve()
        for path in default_baselines_dir(root).glob("baseline_*.yaml"):
            payload = _load_yaml(path)
            if str(payload.get("baseline_id") or "") == baseline.baseline_id:
                return path.resolve()
        return default_baselines_dir(root) / f"{baseline.baseline_id}.yaml"

    def _compare_mode(self, mode: str, baseline_values: dict[str, Any], current_values: dict[str, Any]) -> BenchmarkModeCompare:
        deltas = [
            self._metric_delta(key, baseline_values.get(key), current_values.get(key), direction)
            for key, direction in COMPARE_METRICS.items()
        ]
        comparable_count = len([delta for delta in deltas if delta.delta is not None])
        improved_count = len([delta for delta in deltas if delta.improved is True])
        regressed_count = len([delta for delta in deltas if delta.improved is False])
        summary: list[str] = []
        if improved_count:
            summary.append(f"{improved_count} metrics improved")
        if regressed_count:
            summary.append(f"{regressed_count} metrics regressed")
        warnings = [str(delta.warning) for delta in deltas if delta.warning]
        if comparable_count < 2:
            warnings.append("too few comparable metrics for this mode")
        return BenchmarkModeCompare(
            mode=mode,
            comparable=comparable_count >= 2,
            deltas=deltas,
            summary=summary or ["no material delta"],
            warnings=_dedupe(warnings),
        )

    @staticmethod
    def _metric_delta(key: str, baseline_value: Any, current_value: Any, direction: str) -> BenchmarkMetricDelta:
        base = _number_or_none(baseline_value)
        current = _number_or_none(current_value)
        if base is None or current is None:
            return BenchmarkMetricDelta(
                key=key,
                baseline_value=base,
                current_value=current,
                delta=None,
                direction=direction,
                improved=None,
                summary="not comparable",
                warning=f"missing baseline or current value for {key}",
            )
        delta = round(current - base, 4)
        threshold = DURATION_THRESHOLD if key == "median_duration_seconds" else RATE_THRESHOLD
        if abs(delta) < threshold:
            improved = None
        elif direction == "higher_better":
            improved = delta > 0
        elif direction == "lower_better":
            improved = delta < 0
        else:
            improved = None
        return BenchmarkMetricDelta(
            key=key,
            baseline_value=base,
            current_value=current,
            delta=delta,
            direction=direction,
            improved=improved,
            summary=_delta_summary(key, delta, direction, improved),
            warning=None,
        )

    @staticmethod
    def _verdict(mode_compares: list[BenchmarkModeCompare]) -> str:
        comparable = [item for item in mode_compares if item.comparable]
        if not comparable:
            return "insufficient_data"
        improved = 0
        regressed = 0
        material = 0
        for item in comparable:
            for delta in item.deltas:
                if delta.improved is True:
                    improved += 1
                    material += 1
                elif delta.improved is False:
                    regressed += 1
                    material += 1
        if material < 2:
            return "insufficient_data"
        if improved > 0 and regressed == 0:
            return "improved"
        if regressed > 0 and improved == 0:
            return "regressed"
        if improved >= regressed + 2:
            return "improved"
        if regressed >= improved + 2:
            return "regressed"
        return "mixed"

    @staticmethod
    def _summary(verdict: str, mode_compares: list[BenchmarkModeCompare]) -> list[str]:
        if verdict == "insufficient_data":
            return ["Not enough comparable benchmark metrics yet."]
        improved_items: list[str] = []
        regressed_items: list[str] = []
        for compare in mode_compares:
            for delta in compare.deltas:
                if delta.improved is True:
                    improved_items.append(f"{compare.mode}: {delta.summary}")
                elif delta.improved is False:
                    regressed_items.append(f"{compare.mode}: {delta.summary}")
        summary: list[str] = []
        if improved_items:
            summary.append(f"Improved: {improved_items[0]}")
        if regressed_items:
            summary.append(f"Regressed: {regressed_items[0]}")
        if not summary:
            summary.append("No material changes beyond threshold.")
        return summary


def baseline_path(project_root: Path, snapshot: BenchmarkBaselineSnapshot) -> Path:
    return default_baselines_dir(project_root) / f"baseline_{_slug(snapshot.workset_name)}_{_stamp()}_{_short_id()}.yaml"


def compare_path(project_root: Path, report: BenchmarkCompareReport) -> Path:
    return default_compares_dir(project_root) / f"compare_{_slug(report.workset_name)}_{_stamp()}_{_short_id()}.yaml"


def latest_compare_path(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "latest_compare.yaml"


def resolve_report_for_baseline(project_root: Path, workset_name: str, report_ref: str | None = None) -> Path:
    root = Path(project_root).resolve()
    if report_ref:
        candidate = Path(report_ref)
        if candidate.exists():
            return candidate.resolve()
        if (root / candidate).exists():
            return (root / candidate).resolve()
        raise FileNotFoundError(f"benchmark report not found: {report_ref}")
    latest = default_reports_dir(root) / "latest.yaml"
    if latest.exists() and str(_load_yaml(latest).get("workset_name") or "") == workset_name:
        return latest.resolve()
    candidates: list[Path] = []
    for path in default_reports_dir(root).glob("report_*.yaml"):
        if str(_load_yaml(path).get("workset_name") or "") == workset_name:
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(f"benchmark report not found for workset: {workset_name}")
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0].resolve()


def load_latest_compare_summary(project_root: Path) -> dict[str, Any]:
    payload = _load_yaml(latest_compare_path(project_root))
    if not payload:
        return {}
    return {
        "workset_name": payload.get("workset_name"),
        "verdict": payload.get("verdict"),
        "gate_status": payload.get("gate_status"),
        "best_mode_before": payload.get("best_mode_before"),
        "best_mode_now": payload.get("best_mode_now"),
    }


def render_baselines(baselines: list[BenchmarkBaselineSnapshot]) -> str:
    lines = ["Benchmark Baselines", "==================================================", ""]
    if not baselines:
        lines.append("No benchmark baselines yet.")
        return "\n".join(lines)
    by_workset: dict[str, list[BenchmarkBaselineSnapshot]] = {}
    for baseline in baselines:
        by_workset.setdefault(baseline.workset_name, []).append(baseline)
    for workset_name, items in sorted(by_workset.items()):
        lines.append(f"{workset_name}:")
        for item in items:
            lines.append(f"  - {item.baseline_id}")
            lines.append(f"    best mode: {item.best_mode or 'none'}")
    return "\n".join(lines)


def render_baseline_saved(snapshot: BenchmarkBaselineSnapshot, saved_path: Path, root: Path) -> str:
    return "\n".join(
        [
            "Benchmark baseline saved.",
            "",
            "Workset:",
            f"  {snapshot.workset_name}",
            "",
            "Best mode:",
            f"  {snapshot.best_mode or 'none'}",
            "",
            "Saved:",
            f"  {_relative(saved_path, root)}",
        ]
    )


def render_compare_report(report: BenchmarkCompareReport) -> str:
    lines = [
        "Benchmark Compare",
        "==================================================",
        "",
        "Workset:",
        f"  {report.workset_name}",
        "",
        "Compared to:",
        f"  {Path(report.baseline_ref or '').name or 'unknown'}",
        "",
        "Overall:",
        f"  {report.verdict}",
        "",
        "Gate:",
        f"  {report.gate_status}",
        "",
        "Best mode before:",
        f"  {report.best_mode_before or 'none'}",
        "",
        "Best mode now:",
        f"  {report.best_mode_now or 'none'}",
        "",
        "Key deltas:",
    ]
    if not report.mode_compares:
        lines.append("  no comparable modes")
    for mode_compare in report.mode_compares:
        lines.append(f"  {mode_compare.mode}")
        for delta in mode_compare.deltas:
            lines.append(f"    {_label(delta.key):<25}: {delta.summary}")
    if report.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in report.summary])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in report.next_actions])
    return "\n".join(lines)


def _baseline_from_dict(payload: dict[str, Any]) -> BenchmarkBaselineSnapshot:
    return BenchmarkBaselineSnapshot(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        baseline_id=str(payload.get("baseline_id") or ""),
        saved_at=str(payload.get("saved_at") or ""),
        workset_name=str(payload.get("workset_name") or ""),
        source_report_ref=str(payload.get("source_report_ref")) if payload.get("source_report_ref") is not None else None,
        source_report_generated_at=str(payload.get("source_report_generated_at")) if payload.get("source_report_generated_at") is not None else None,
        modes=[str(item) for item in payload.get("modes", []) if item],
        by_mode=dict(payload.get("by_mode", {})) if isinstance(payload.get("by_mode"), dict) else {},
        best_mode=str(payload.get("best_mode")) if payload.get("best_mode") is not None else None,
        notes=[str(item) for item in payload.get("notes", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _compare_from_dict(payload: dict[str, Any]) -> BenchmarkCompareReport:
    mode_compares = [
        _mode_compare_from_dict(item)
        for item in payload.get("mode_compares", [])
        if isinstance(item, dict)
    ]
    return BenchmarkCompareReport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        generated_at=str(payload.get("generated_at") or ""),
        compare_id=str(payload.get("compare_id") or ""),
        workset_name=str(payload.get("workset_name") or ""),
        baseline_ref=str(payload.get("baseline_ref")) if payload.get("baseline_ref") is not None else None,
        current_report_ref=str(payload.get("current_report_ref")) if payload.get("current_report_ref") is not None else None,
        compared_modes=[str(item) for item in payload.get("compared_modes", []) if item],
        best_mode_before=str(payload.get("best_mode_before")) if payload.get("best_mode_before") is not None else None,
        best_mode_now=str(payload.get("best_mode_now")) if payload.get("best_mode_now") is not None else None,
        best_mode_changed=bool(payload.get("best_mode_changed", False)),
        verdict=str(payload.get("verdict") or "insufficient_data"),
        gate_status=str(payload.get("gate_status") or "gray"),
        mode_compares=mode_compares,
        summary=[str(item) for item in payload.get("summary", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _mode_compare_from_dict(payload: dict[str, Any]) -> BenchmarkModeCompare:
    return BenchmarkModeCompare(
        mode=str(payload.get("mode") or ""),
        comparable=bool(payload.get("comparable", False)),
        deltas=[_delta_from_dict(item) for item in payload.get("deltas", []) if isinstance(item, dict)],
        summary=[str(item) for item in payload.get("summary", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
    )


def _delta_from_dict(payload: dict[str, Any]) -> BenchmarkMetricDelta:
    improved = payload.get("improved")
    return BenchmarkMetricDelta(
        key=str(payload.get("key") or ""),
        baseline_value=_number_or_none(payload.get("baseline_value")),
        current_value=_number_or_none(payload.get("current_value")),
        delta=_number_or_none(payload.get("delta")),
        direction=str(payload.get("direction") or "neutral"),
        improved=improved if isinstance(improved, bool) else None,
        summary=str(payload.get("summary") or ""),
        warning=str(payload.get("warning")) if payload.get("warning") is not None else None,
    )


def _number_or_none(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return round(number, 4)


def _delta_summary(key: str, delta: float | int, direction: str, improved: bool | None) -> str:
    if key == "median_duration_seconds":
        text = f"{delta:+.0f}s vs baseline"
    else:
        text = f"{float(delta) * 100:+.0f}pt vs baseline"
    if improved is True:
        return f"{text} improved"
    if improved is False:
        return f"{text} regressed"
    return f"{text} stable"


def _label(key: str) -> str:
    return {
        "validated_proposal_rate": "validated proposal rate",
        "adoption_rate": "adoption rate",
        "regression_free_apply_rate": "regression-free apply",
        "human_intervention_rate": "human intervention",
        "validation_autonomy_rate": "validation autonomy",
        "median_duration_seconds": "median duration",
    }.get(key, key)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
