"""반복 가능한 benchmark workset과 비교 리포트."""

from __future__ import annotations

import json
import logging
import re
import secrets
import statistics
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
ALLOWED_MODES = {
    "raw_ai",
    "bridge_only",
    "cambrian_guided",
    "cambrian_full",
    "manual_baseline",
}
ALLOWED_REQUEST_CLASSES = {"bug_fix", "review", "docs", "refactor", "unknown"}
ALLOWED_VERDICTS = {"strong", "good", "mixed", "weak"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    return secrets.token_hex(2)


def _slug(value: str, fallback: str = "item") -> str:
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


def _load_any(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("benchmark artifact 읽기 실패: %s (%s)", path, exc)
        return {}
    try:
        if Path(path).suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("benchmark artifact 파싱 실패: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "passed", "success", "adopted", "applied"}
    return bool(value)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _rate_known(values: list[Any]) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return round(sum(1 for value in known if _bool(value)) / len(known), 4)


def _median(values: list[Any]) -> float | None:
    numbers: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return None
    return round(float(statistics.median(numbers)), 3)


@dataclass
class BenchmarkCase:
    schema_version: str
    case_id: str
    created_at: str
    name: str
    request: str
    request_class: str
    description: str | None
    tags: list[str] = field(default_factory=list)
    expected_focus: list[str] = field(default_factory=list)
    replay_hints: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkWorkset:
    schema_version: str
    workset_id: str
    created_at: str
    name: str
    description: str | None
    case_ids: list[str]
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    schema_version: str
    result_id: str
    created_at: str
    case_id: str
    mode: str
    status: str
    source_refs: dict[str, Any] = field(default_factory=dict)
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    verdict: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    schema_version: str
    generated_at: str
    report_id: str
    workset_name: str
    modes: list[str]
    totals: dict[str, Any]
    by_mode: dict[str, Any]
    by_case: dict[str, Any]
    best_mode: str | None
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_benchmark_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "benchmarks"


def default_cases_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "cases"


def default_worksets_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "worksets"


def default_results_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "results"


def default_reports_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "reports"


class BenchmarkStore:
    """Benchmark artifact 저장소."""

    def save_case(self, case: BenchmarkCase, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), case.to_dict())

    def save_workset(self, workset: BenchmarkWorkset, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), workset.to_dict())

    def save_result(self, result: BenchmarkResult, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), result.to_dict())

    def save_report(self, report: BenchmarkReport, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent / "latest.yaml", report.to_dict())
        return saved

    def load_case(self, path: Path) -> BenchmarkCase:
        return _case_from_dict(_load_any(Path(path).resolve()))

    def load_workset(self, path: Path) -> BenchmarkWorkset:
        return _workset_from_dict(_load_any(Path(path).resolve()))

    def load_result(self, path: Path) -> BenchmarkResult:
        return _result_from_dict(_load_any(Path(path).resolve()))

    def load_report(self, path: Path) -> BenchmarkReport:
        return _report_from_dict(_load_any(Path(path).resolve()))

    def list_cases(self, project_root: Path) -> list[BenchmarkCase]:
        cases: list[BenchmarkCase] = []
        for path in sorted(default_cases_dir(project_root).glob("case_*.yaml")):
            payload = _load_any(path)
            if payload:
                cases.append(_case_from_dict(payload))
        return cases

    def list_worksets(self, project_root: Path) -> list[BenchmarkWorkset]:
        worksets: list[BenchmarkWorkset] = []
        for path in sorted(default_worksets_dir(project_root).glob("workset_*.yaml")):
            payload = _load_any(path)
            if payload:
                worksets.append(_workset_from_dict(payload))
        return worksets

    def list_results(self, project_root: Path) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        for path in sorted(default_results_dir(project_root).glob("result_*.yaml")):
            payload = _load_any(path)
            if payload:
                results.append(_result_from_dict(payload))
        results.sort(key=lambda item: item.created_at, reverse=True)
        return results

    def resolve_case_path(self, project_root: Path, ref: str) -> Path:
        root = Path(project_root).resolve()
        candidate = Path(ref)
        if candidate.exists():
            return candidate.resolve()
        if (root / candidate).exists():
            return (root / candidate).resolve()
        slug = _slug(ref)
        direct = default_cases_dir(root) / f"case_{slug}.yaml"
        if direct.exists():
            return direct.resolve()
        for path in default_cases_dir(root).glob("case_*.yaml"):
            payload = _load_any(path)
            if str(payload.get("case_id") or "") == ref or str(payload.get("name") or "") == ref:
                return path.resolve()
        raise FileNotFoundError(f"benchmark case not found: {ref}")

    def resolve_workset_path(self, project_root: Path, ref: str) -> Path:
        root = Path(project_root).resolve()
        candidate = Path(ref)
        if candidate.exists():
            return candidate.resolve()
        if (root / candidate).exists():
            return (root / candidate).resolve()
        slug = _slug(ref)
        direct = default_worksets_dir(root) / f"workset_{slug}.yaml"
        if direct.exists():
            return direct.resolve()
        for path in default_worksets_dir(root).glob("workset_*.yaml"):
            payload = _load_any(path)
            if str(payload.get("workset_id") or "") == ref or str(payload.get("name") or "") == ref:
                return path.resolve()
        raise FileNotFoundError(f"benchmark workset not found: {ref}")


class BenchmarkResultRecorder:
    """외부 수행 결과를 benchmark result artifact로 연결한다."""

    def record(
        self,
        project_root: Path,
        *,
        case_ref: str,
        mode: str,
        session_ref: str | None = None,
        reply_ref: str | None = None,
        manual_result_ref: str | None = None,
        summary: str | None = None,
        verdict: str | None = None,
    ) -> tuple[BenchmarkResult, Path]:
        root = Path(project_root).resolve()
        if mode not in ALLOWED_MODES:
            raise ValueError(f"unsupported benchmark mode: {mode}")
        if verdict is not None and verdict not in ALLOWED_VERDICTS:
            raise ValueError(f"unsupported verdict: {verdict}")
        store = BenchmarkStore()
        case = store.load_case(store.resolve_case_path(root, case_ref))
        source_refs: dict[str, Any] = {}
        warnings: list[str] = []
        snapshots: list[dict[str, Any]] = []
        summaries: list[str] = []

        if session_ref:
            session_path, snapshot, session_summary, session_warnings = self._snapshot_from_session(root, session_ref)
            source_refs["session_ref"] = _relative(session_path, root)
            snapshots.append(snapshot)
            if session_summary:
                summaries.append(session_summary)
            warnings.extend(session_warnings)
        if reply_ref:
            reply_path, snapshot, reply_summary, reply_warnings = self._snapshot_from_bridge_reply(root, reply_ref)
            source_refs["bridge_reply_ref"] = _relative(reply_path, root)
            snapshots.append(snapshot)
            if reply_summary:
                summaries.append(reply_summary)
            warnings.extend(reply_warnings)
        if manual_result_ref:
            manual_path = self._resolve_existing(root, manual_result_ref)
            payload = _load_any(manual_path)
            source_refs["manual_result_ref"] = _relative(manual_path, root)
            snapshot = self._snapshot_from_manual(payload)
            snapshots.append(snapshot)
            if payload.get("summary"):
                summaries.append(str(payload.get("summary")))
            warnings.extend(self._missing_snapshot_warnings(snapshot))
        if not snapshots:
            warnings.append("no session/reply/manual result source was provided")
        metrics_snapshot = self._merge_snapshots(snapshots)
        warnings.extend(self._missing_snapshot_warnings(metrics_snapshot))
        result = BenchmarkResult(
            schema_version=SCHEMA_VERSION,
            result_id=f"result-{_slug(case.case_id)}-{mode}-{_short_id()}",
            created_at=_now(),
            case_id=case.case_id,
            mode=mode,
            status="recorded" if snapshots else "partial",
            source_refs=source_refs,
            metrics_snapshot=metrics_snapshot,
            summary=summary or (summaries[0] if summaries else f"{mode} result for {case.name}"),
            verdict=verdict,
            warnings=_dedupe(warnings),
            errors=[],
        )
        result_path = default_results_dir(root) / f"result_{_slug(case.case_id)}_{mode}_{_stamp()}_{_short_id()}.yaml"
        BenchmarkStore().save_result(result, result_path)
        return result, result_path

    def _snapshot_from_session(self, root: Path, session_ref: str) -> tuple[Path, dict[str, Any], str, list[str]]:
        from engine.project_do import DoSessionStore

        path = DoSessionStore().resolve_path(root, session_ref)
        payload = _load_any(path)
        metrics = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
        results = metrics.get("results") if isinstance(metrics.get("results"), dict) else {}
        human = metrics.get("human_interventions") if isinstance(metrics.get("human_interventions"), dict) else {}
        milestones = metrics.get("milestones") if isinstance(metrics.get("milestones"), dict) else {}
        snapshot = {
            "validated_proposal": _bool(results.get("validated_proposal")) or str(payload.get("current_stage") or payload.get("status")) in {"patch_proposal_validated", "adopted"},
            "adoption_succeeded": _bool(results.get("adoption_succeeded")) or str(payload.get("status")) == "adopted",
            "apply_tests_passed": results.get("apply_tests_passed") if "apply_tests_passed" in results else None,
            "human_intervention": any(
                _bool(human.get(key))
                for key in (
                    "source_selected_manually",
                    "test_selected_manually",
                    "old_text_overridden",
                    "new_text_overridden",
                    "explicit_agent_override",
                    "explicit_team_override",
                    "explicit_template_choice",
                )
            ),
            "validation_autonomy": self._validation_autonomy(metrics, payload),
            "lead_agent_hit": self._lead_agent_hit(metrics, payload),
            "team_template_hit": metrics.get("team_template_hit"),
            "duration_seconds": self._duration_seconds(milestones),
        }
        summary = str(payload.get("user_request") or "")
        return path, snapshot, summary, []

    def _snapshot_from_bridge_reply(self, root: Path, reply_ref: str) -> tuple[Path, dict[str, Any], str, list[str]]:
        from engine.project_bridge import ProjectBridgeStore, resolve_bridge_reply_path

        path = resolve_bridge_reply_path(root, reply_ref)
        reply = ProjectBridgeStore().load_reply(path)
        content = reply.content if isinstance(reply.content, dict) else {}
        snapshot = {
            "response_kind": reply.response_kind,
            "validated_proposal": None,
            "adoption_succeeded": None,
            "apply_tests_passed": None,
            "human_intervention": True,
            "validation_autonomy": None,
            "lead_agent_hit": None,
            "team_template_hit": None,
            "duration_seconds": None,
        }
        summary = str(content.get("summary") or reply.request or "")
        warnings = ["bridge reply does not contain direct proposal/adoption metrics"]
        return path, snapshot, summary, warnings

    def _snapshot_from_manual(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "validated_proposal": payload.get("validated_proposal"),
            "adoption_succeeded": payload.get("adoption_succeeded"),
            "apply_tests_passed": payload.get("apply_tests_passed"),
            "human_intervention": payload.get("human_intervention"),
            "validation_autonomy": payload.get("validation_autonomy"),
            "lead_agent_hit": payload.get("lead_agent_hit"),
            "team_template_hit": payload.get("team_template_hit"),
            "duration_seconds": payload.get("duration_seconds"),
        }

    @staticmethod
    def _resolve_existing(root: Path, ref: str) -> Path:
        candidate = Path(ref)
        if candidate.exists():
            return candidate.resolve()
        rel = root / candidate
        if rel.exists():
            return rel.resolve()
        raise FileNotFoundError(f"benchmark source file not found: {ref}")

    @staticmethod
    def _validation_autonomy(metrics: dict[str, Any], payload: dict[str, Any]) -> bool:
        human = metrics.get("human_interventions") if isinstance(metrics.get("human_interventions"), dict) else {}
        results = metrics.get("results") if isinstance(metrics.get("results"), dict) else {}
        continuations = payload.get("continuations") if isinstance(payload.get("continuations"), list) else []
        continued = any(
            isinstance(step, dict) and str(step.get("action")) in {"patch_proposal_created", "patch_proposal_validated"}
            for step in continuations
        )
        return (
            (_bool(results.get("validated_proposal")) or str(payload.get("current_stage") or payload.get("status")) in {"patch_proposal_validated", "adopted"})
            and not _bool(human.get("old_text_overridden"))
            and not _bool(human.get("new_text_overridden"))
            and (continued or str(metrics.get("validation_path", "")) == "continue")
        )

    @staticmethod
    def _lead_agent_hit(metrics: dict[str, Any], payload: dict[str, Any]) -> bool | None:
        lead = str(metrics.get("lead_agent_id") or "")
        agent_context = payload.get("agent_context") if isinstance(payload.get("agent_context"), dict) else {}
        lead = lead or str(agent_context.get("lead_agent_id") or "")
        if not lead:
            return None
        final = str(metrics.get("final_lead_agent_id") or lead)
        return final == lead

    @staticmethod
    def _duration_seconds(milestones: dict[str, Any]) -> float | None:
        start = _parse_datetime(milestones.get("request_started_at"))
        end = _parse_datetime(milestones.get("proposal_validated_at") or milestones.get("applied_at"))
        if start is None or end is None or end < start:
            return None
        return round((end - start).total_seconds(), 3)

    @staticmethod
    def _merge_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key in (
            "validated_proposal",
            "adoption_succeeded",
            "apply_tests_passed",
            "human_intervention",
            "validation_autonomy",
            "lead_agent_hit",
            "team_template_hit",
            "duration_seconds",
            "response_kind",
        ):
            for snapshot in snapshots:
                if key in snapshot and snapshot.get(key) is not None:
                    merged[key] = snapshot.get(key)
                    break
            else:
                merged[key] = None
        return merged

    @staticmethod
    def _missing_snapshot_warnings(snapshot: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for key in ("validated_proposal", "human_intervention", "duration_seconds"):
            if snapshot.get(key) is None:
                warnings.append(f"missing comparable metric: {key}")
        return warnings


class BenchmarkReportBuilder:
    """Workset 기준 mode 비교 리포트를 만든다."""

    def build(self, project_root: Path, workset_name: str) -> BenchmarkReport:
        root = Path(project_root).resolve()
        store = BenchmarkStore()
        warnings: list[str] = []
        errors: list[str] = []
        workset = store.load_workset(store.resolve_workset_path(root, workset_name))
        cases: dict[str, BenchmarkCase] = {}
        for case_ref in workset.case_ids:
            try:
                case = store.load_case(store.resolve_case_path(root, case_ref))
                cases[case.case_id] = case
            except FileNotFoundError as exc:
                warnings.append(str(exc))
        results = [result for result in store.list_results(root) if result.case_id in cases]
        modes = sorted({result.mode for result in results})
        by_mode = self._aggregate_by_mode(results)
        by_case = self._aggregate_by_case(cases, results)
        best_mode = self._best_mode(by_mode)
        if not results:
            warnings.append("no benchmark results found for this workset")
        if len(modes) < 2:
            warnings.append("fewer than two modes are comparable")
        summary = self._summary(best_mode, by_mode)
        report = BenchmarkReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            report_id=f"benchmark-report-{_short_id()}",
            workset_name=workset.name,
            modes=modes,
            totals={
                "cases": len(cases),
                "results": len(results),
                "modes": len(modes),
            },
            by_mode=by_mode,
            by_case=by_case,
            best_mode=best_mode,
            summary=summary,
            next_actions=[
                f"cambrian benchmark report {workset.name} --save",
                "cambrian metrics week --save",
            ],
            warnings=_dedupe(warnings),
            errors=errors,
        )
        return report

    @staticmethod
    def _aggregate_by_mode(results: list[BenchmarkResult]) -> dict[str, Any]:
        by_mode: dict[str, list[BenchmarkResult]] = {}
        for result in results:
            by_mode.setdefault(result.mode, []).append(result)
        aggregated: dict[str, Any] = {}
        for mode, mode_results in sorted(by_mode.items()):
            snapshots = [result.metrics_snapshot for result in mode_results]
            aggregated[mode] = {
                "total_cases": len({result.case_id for result in mode_results}),
                "result_count": len(mode_results),
                "validated_proposal_rate": _rate_known([snapshot.get("validated_proposal") for snapshot in snapshots]),
                "adoption_rate": _rate_known([snapshot.get("adoption_succeeded") for snapshot in snapshots]),
                "regression_free_apply_rate": _rate_known([snapshot.get("apply_tests_passed") for snapshot in snapshots]),
                "human_intervention_rate": _rate_known([snapshot.get("human_intervention") for snapshot in snapshots]),
                "validation_autonomy_rate": _rate_known([snapshot.get("validation_autonomy") for snapshot in snapshots]),
                "median_duration_seconds": _median([snapshot.get("duration_seconds") for snapshot in snapshots]),
                "verdicts": _count_values([result.verdict for result in mode_results if result.verdict]),
            }
        return aggregated

    @staticmethod
    def _aggregate_by_case(cases: dict[str, BenchmarkCase], results: list[BenchmarkResult]) -> dict[str, Any]:
        by_case: dict[str, Any] = {}
        result_groups: dict[str, list[BenchmarkResult]] = {}
        for result in results:
            result_groups.setdefault(result.case_id, []).append(result)
        for case_id, case in sorted(cases.items()):
            case_results = result_groups.get(case_id, [])
            by_case[case_id] = {
                "name": case.name,
                "request_class": case.request_class,
                "modes": sorted({result.mode for result in case_results}),
                "result_count": len(case_results),
                "best_mode": _best_result_for_case(case_results).mode if case_results else None,
            }
        return by_case

    @staticmethod
    def _best_mode(by_mode: dict[str, Any]) -> str | None:
        if not by_mode:
            return None

        def key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, float, float]:
            _, values = item
            validated = _score_value(values.get("validated_proposal_rate"), default=-1.0)
            adopted = _score_value(values.get("adoption_rate"), default=-1.0)
            intervention = _score_value(values.get("human_intervention_rate"), default=1.0)
            duration = _score_value(values.get("median_duration_seconds"), default=1_000_000.0)
            return (validated, adopted, -intervention, -duration)

        return sorted(by_mode.items(), key=key, reverse=True)[0][0]

    @staticmethod
    def _summary(best_mode: str | None, by_mode: dict[str, Any]) -> list[str]:
        if not best_mode:
            return ["No comparable benchmark results yet."]
        values = by_mode.get(best_mode, {})
        summary = [f"{best_mode} leads this workset."]
        if values.get("validated_proposal_rate") is not None:
            summary.append("highest validated proposal rate is the primary comparison axis")
        if values.get("adoption_rate") is not None:
            summary.append("adoption rate is available for comparison")
        if values.get("human_intervention_rate") is not None:
            summary.append("human intervention rate is included as automation pressure")
        return summary


def create_benchmark_case(
    *,
    request: str,
    name: str | None,
    request_class: str,
    description: str | None,
    tags: list[str],
    expected_focus: list[str],
) -> BenchmarkCase:
    if request_class not in ALLOWED_REQUEST_CLASSES:
        raise ValueError(f"unsupported request class: {request_class}")
    case_name = name or _slug(request[:40], "benchmark-case")
    return BenchmarkCase(
        schema_version=SCHEMA_VERSION,
        case_id=_slug(case_name, "benchmark-case"),
        created_at=_now(),
        name=case_name,
        request=request,
        request_class=request_class,
        description=description,
        tags=[str(item) for item in tags if item],
        expected_focus=[str(item) for item in expected_focus if item],
        notes=[],
        warnings=[],
        errors=[],
    )


def create_benchmark_workset(
    *,
    project_root: Path,
    name: str,
    case_refs: list[str],
    description: str | None,
    tags: list[str],
) -> BenchmarkWorkset:
    store = BenchmarkStore()
    case_ids: list[str] = []
    warnings: list[str] = []
    for case_ref in case_refs:
        try:
            case = store.load_case(store.resolve_case_path(project_root, case_ref))
            case_ids.append(case.case_id)
        except FileNotFoundError as exc:
            warnings.append(str(exc))
    return BenchmarkWorkset(
        schema_version=SCHEMA_VERSION,
        workset_id=_slug(name, "workset"),
        created_at=_now(),
        name=name,
        description=description,
        case_ids=_dedupe(case_ids),
        tags=[str(item) for item in tags if item],
        warnings=warnings,
        errors=[],
    )


def case_path(project_root: Path, case: BenchmarkCase) -> Path:
    return default_cases_dir(project_root) / f"case_{_slug(case.case_id)}.yaml"


def workset_path(project_root: Path, workset: BenchmarkWorkset) -> Path:
    return default_worksets_dir(project_root) / f"workset_{_slug(workset.workset_id)}.yaml"


def report_path(project_root: Path, report: BenchmarkReport) -> Path:
    return default_reports_dir(project_root) / f"report_{_slug(report.workset_name)}_{_stamp()}_{_short_id()}.yaml"


def load_latest_benchmark_summary(project_root: Path) -> dict[str, Any]:
    payload = _load_any(default_reports_dir(project_root) / "latest.yaml")
    if not payload:
        return {}
    return {
        "workset_name": payload.get("workset_name"),
        "best_mode": payload.get("best_mode"),
        "report_id": payload.get("report_id"),
    }


def render_cases(cases: list[BenchmarkCase]) -> str:
    lines = ["Benchmark Cases", "==================================================", ""]
    if not cases:
        lines.append("No benchmark cases yet.")
        return "\n".join(lines)
    for case in cases:
        tags = ", ".join(case.tags) or "none"
        lines.append(f"- {case.name} [{case.request_class}]")
        lines.append(f"  id  : {case.case_id}")
        lines.append(f"  tags: {tags}")
    return "\n".join(lines)


def render_worksets(worksets: list[BenchmarkWorkset]) -> str:
    lines = ["Benchmark Worksets", "==================================================", ""]
    if not worksets:
        lines.append("No benchmark worksets yet.")
        return "\n".join(lines)
    for workset in worksets:
        lines.append(f"- {workset.name}")
        lines.append(f"  id   : {workset.workset_id}")
        lines.append(f"  cases: {len(workset.case_ids)}")
    return "\n".join(lines)


def render_attach_result(result: BenchmarkResult, saved_path: Path, root: Path) -> str:
    try:
        saved_ref = _relative(saved_path, root)
    except ValueError:
        saved_ref = str(saved_path)
    lines = [
        "Benchmark result recorded.",
        "",
        "Case:",
        f"  {result.case_id}",
        "",
        "Mode:",
        f"  {result.mode}",
        "",
        "Snapshot:",
        f"  validated   : {_human_bool(result.metrics_snapshot.get('validated_proposal'))}",
        f"  adopted     : {_human_bool(result.metrics_snapshot.get('adoption_succeeded'))}",
        f"  intervention: {_human_bool(result.metrics_snapshot.get('human_intervention'))}",
        "",
        "Saved:",
        f"  {saved_ref}",
    ]
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    return "\n".join(lines)


def render_report(report: BenchmarkReport) -> str:
    lines = [
        "Benchmark Report",
        "==================================================",
        "",
        "Workset:",
        f"  {report.workset_name}",
        "",
        "Compared modes:",
    ]
    if report.modes:
        lines.extend([f"  {mode}" for mode in report.modes])
    else:
        lines.append("  none")
    lines.extend(["", "Best mode:", f"  {report.best_mode or 'none'}", "", "By mode:"])
    if not report.by_mode:
        lines.append("  no result records")
    for mode, values in report.by_mode.items():
        lines.extend(
            [
                f"  {mode}",
                f"    validated   : {_format_rate(values.get('validated_proposal_rate'))}",
                f"    adopted     : {_format_rate(values.get('adoption_rate'))}",
                f"    regression  : {_format_rate(values.get('regression_free_apply_rate'))}",
                f"    intervention: {_format_rate(values.get('human_intervention_rate'))}",
                f"    autonomy    : {_format_rate(values.get('validation_autonomy_rate'))}",
                f"    median time : {_format_seconds(values.get('median_duration_seconds'))}",
            ]
        )
    if report.summary:
        lines.extend(["", f"Why {report.best_mode or 'no mode'} leads:"])
        lines.extend([f"  - {item}" for item in report.summary])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in report.next_actions])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    return "\n".join(lines)


def _case_from_dict(payload: dict[str, Any]) -> BenchmarkCase:
    return BenchmarkCase(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        case_id=str(payload.get("case_id") or payload.get("name") or ""),
        created_at=str(payload.get("created_at") or ""),
        name=str(payload.get("name") or payload.get("case_id") or ""),
        request=str(payload.get("request") or ""),
        request_class=str(payload.get("request_class") or "unknown"),
        description=str(payload.get("description")) if payload.get("description") is not None else None,
        tags=[str(item) for item in payload.get("tags", []) if item],
        expected_focus=[str(item) for item in payload.get("expected_focus", []) if item],
        replay_hints=dict(payload.get("replay_hints", {})) if isinstance(payload.get("replay_hints"), dict) else {},
        notes=[str(item) for item in payload.get("notes", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _workset_from_dict(payload: dict[str, Any]) -> BenchmarkWorkset:
    return BenchmarkWorkset(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        workset_id=str(payload.get("workset_id") or payload.get("name") or ""),
        created_at=str(payload.get("created_at") or ""),
        name=str(payload.get("name") or payload.get("workset_id") or ""),
        description=str(payload.get("description")) if payload.get("description") is not None else None,
        case_ids=[str(item) for item in payload.get("case_ids", []) if item],
        tags=[str(item) for item in payload.get("tags", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _result_from_dict(payload: dict[str, Any]) -> BenchmarkResult:
    return BenchmarkResult(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        result_id=str(payload.get("result_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        case_id=str(payload.get("case_id") or ""),
        mode=str(payload.get("mode") or "manual_baseline"),
        status=str(payload.get("status") or "recorded"),
        source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
        metrics_snapshot=dict(payload.get("metrics_snapshot", {})) if isinstance(payload.get("metrics_snapshot"), dict) else {},
        summary=str(payload.get("summary") or ""),
        verdict=str(payload.get("verdict")) if payload.get("verdict") is not None else None,
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _report_from_dict(payload: dict[str, Any]) -> BenchmarkReport:
    return BenchmarkReport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        generated_at=str(payload.get("generated_at") or ""),
        report_id=str(payload.get("report_id") or ""),
        workset_name=str(payload.get("workset_name") or ""),
        modes=[str(item) for item in payload.get("modes", []) if item],
        totals=dict(payload.get("totals", {})) if isinstance(payload.get("totals"), dict) else {},
        by_mode=dict(payload.get("by_mode", {})) if isinstance(payload.get("by_mode"), dict) else {},
        by_case=dict(payload.get("by_case", {})) if isinstance(payload.get("by_case"), dict) else {},
        best_mode=str(payload.get("best_mode")) if payload.get("best_mode") is not None else None,
        summary=[str(item) for item in payload.get("summary", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _score_value(value: Any, *, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _best_result_for_case(results: list[BenchmarkResult]) -> BenchmarkResult:
    def key(result: BenchmarkResult) -> tuple[float, float, float, float]:
        snapshot = result.metrics_snapshot
        validated = 1.0 if _bool(snapshot.get("validated_proposal")) else 0.0
        adopted = 1.0 if _bool(snapshot.get("adoption_succeeded")) else 0.0
        intervention = 1.0 if _bool(snapshot.get("human_intervention")) else 0.0
        duration = _score_value(snapshot.get("duration_seconds"), default=1_000_000.0)
        return (validated, adopted, -intervention, -duration)

    return sorted(results, key=key, reverse=True)[0]


def _count_values(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _human_bool(value: Any) -> str:
    if value is None:
        return "n/a"
    return "yes" if _bool(value) else "no"


def _format_rate(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def _format_seconds(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return "n/a"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
