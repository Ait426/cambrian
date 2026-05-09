"""Benchmark workset replay와 autonomy evidence board."""

from __future__ import annotations

import logging
import secrets
import statistics
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_benchmark_replay import (
    BenchmarkReplayReport,
    BenchmarkReplayRunner,
    BenchmarkReplayStore,
    default_replay_path,
    load_latest_replay_summary,
    save_replay_result,
)
from engine.project_benchmarks import BenchmarkStore, default_benchmark_dir

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
REPLAY_MODES = {"cambrian_guided", "cambrian_full"}
REPLAY_STAGES = [
    "request_start",
    "context_ready",
    "diagnosed",
    "patch_intent_ready",
    "proposal_validated",
]


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
        logger.warning("workset replay artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _rate(values: list[Any]) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return round(sum(1 for value in known if bool(value)) / len(known), 4)


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


def _count(values: list[str | None]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def default_workset_replays_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "workset_replays"


def default_autonomy_boards_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "autonomy_boards"


def default_workset_replay_path(project_root: Path, report: "WorksetReplayReport") -> Path:
    return default_workset_replays_dir(project_root) / f"replay_{_slug(report.workset_name)}_{report.mode}_{_stamp()}_{_short_id()}.yaml"


def default_autonomy_board_path(project_root: Path, board: "AutonomyEvidenceBoard") -> Path:
    return default_autonomy_boards_dir(project_root) / f"board_{_slug(board.workset_name)}_{_stamp()}_{_short_id()}.yaml"


def latest_autonomy_board_path(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "latest_autonomy_board.yaml"


@dataclass
class WorksetReplayEntry:
    case_id: str
    case_name: str
    mode: str
    replay_ref: str | None
    status: str
    autonomy_stage_reached: str | None
    stop_reason: str | None
    validated_proposal: bool | None
    validation_autonomy: bool | None
    human_intervention: bool | None
    duration_seconds: float | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorksetReplayReport:
    schema_version: str
    replay_id: str
    created_at: str
    workset_name: str
    mode: str
    total_cases: int
    entries: list[WorksetReplayEntry]
    stage_counts: dict[str, int]
    stop_reason_counts: dict[str, int]
    summary: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entries"] = [entry.to_dict() for entry in self.entries]
        return payload


@dataclass
class AutonomyModeSummary:
    mode: str
    total_cases: int
    validated_proposal_rate: float | None
    validation_autonomy_rate: float | None
    human_intervention_rate: float | None
    median_duration_seconds: float | None
    stage_counts: dict[str, int]
    stop_reason_counts: dict[str, int]
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomyEvidenceBoard:
    schema_version: str
    generated_at: str
    board_id: str
    workset_name: str
    modes: list[str]
    mode_summaries: list[AutonomyModeSummary]
    best_mode: str | None
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode_summaries"] = [summary.to_dict() for summary in self.mode_summaries]
        return payload


class WorksetReplayStore:
    def save(self, report: WorksetReplayReport, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent.parent / "latest_workset_replay.yaml", report.to_dict())
        try:
            from engine.project_template_canary_ledger import record_canary_replay_outcome

            project_root = saved.parents[3] if len(saved.parents) > 3 else saved.parent
            record_canary_replay_outcome(project_root, report, source_ref=_relative(saved, project_root))
        except Exception as exc:
            logger.warning("canary replay ledger event failed: %s", exc)
        return saved

    def load(self, path: Path) -> WorksetReplayReport:
        return _workset_replay_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, directory: Path) -> list[WorksetReplayReport]:
        reports: list[WorksetReplayReport] = []
        for path in sorted(Path(directory).glob("replay_*.yaml")):
            payload = _load_yaml(path)
            if payload:
                reports.append(_workset_replay_from_dict(payload))
        reports.sort(key=lambda report: report.created_at, reverse=True)
        return reports


class AutonomyEvidenceBoardStore:
    def save(self, board: AutonomyEvidenceBoard, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), board.to_dict())
        _save_yaml(saved.parent.parent / "latest_autonomy_board.yaml", board.to_dict())
        return saved

    def load(self, path: Path) -> AutonomyEvidenceBoard:
        return _board_from_dict(_load_yaml(Path(path).resolve()))


class WorksetReplayRunner:
    def run(
        self,
        project_root: Path,
        workset_name: str,
        mode: str,
        *,
        record_results: bool = True,
    ) -> WorksetReplayReport:
        root = Path(project_root).resolve()
        if mode not in REPLAY_MODES:
            raise ValueError(f"unsupported replay mode: {mode}")
        store = BenchmarkStore()
        workset = store.load_workset(store.resolve_workset_path(root, workset_name))
        entries: list[WorksetReplayEntry] = []
        warnings = list(workset.warnings)
        errors: list[str] = []
        for case_ref in workset.case_ids:
            try:
                replay = BenchmarkReplayRunner().run(root, case_ref, mode)
                replay_path = BenchmarkReplayStore().save(replay, default_replay_path(root, replay))
                replay_ref = _relative(replay_path, root)
                if record_results:
                    save_replay_result(root, replay, replay_ref)
                entries.append(_entry_from_replay(replay, replay_ref))
            except Exception as exc:
                message = f"case replay failed for {case_ref}: {exc}"
                logger.warning(message)
                entries.append(
                    WorksetReplayEntry(
                        case_id=str(case_ref),
                        case_name=str(case_ref),
                        mode=mode,
                        replay_ref=None,
                        status="failed",
                        autonomy_stage_reached=None,
                        stop_reason=message,
                        validated_proposal=None,
                        validation_autonomy=None,
                        human_intervention=None,
                        duration_seconds=None,
                        warnings=[],
                        errors=[message],
                    )
                )
                errors.append(message)
        return _build_workset_replay(workset.name, mode, len(workset.case_ids), entries, warnings, errors)


class AutonomyEvidenceBoardBuilder:
    def build(self, project_root: Path, workset_name: str) -> AutonomyEvidenceBoard:
        root = Path(project_root).resolve()
        reports = [
            report
            for report in WorksetReplayStore().list(default_workset_replays_dir(root))
            if report.workset_name == workset_name
        ]
        latest_by_mode: dict[str, WorksetReplayReport] = {}
        for report in reports:
            latest_by_mode.setdefault(report.mode, report)
        warnings: list[str] = []
        if not latest_by_mode:
            warnings.append("no workset replay reports found")
        if len(latest_by_mode) < 2:
            warnings.append("fewer than two replay modes are available for comparison")
        mode_summaries = [
            _mode_summary_from_report(report)
            for _, report in sorted(latest_by_mode.items())
        ]
        best_mode = _best_mode(mode_summaries)
        if best_mode is None and mode_summaries:
            warnings.append("best mode could not be selected because comparable data is sparse")
        summary = _board_summary(best_mode, mode_summaries)
        return AutonomyEvidenceBoard(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            board_id=f"autonomy-board-{_slug(workset_name)}-{_short_id()}",
            workset_name=workset_name,
            modes=[summary.mode for summary in mode_summaries],
            mode_summaries=mode_summaries,
            best_mode=best_mode,
            summary=summary,
            next_actions=[
                f"cambrian benchmark autonomy-board {workset_name} --save",
                f"cambrian benchmark report {workset_name} --save",
                f"cambrian benchmark compare {workset_name}",
            ],
            warnings=_dedupe(warnings + [warning for item in mode_summaries for warning in item.warnings]),
            errors=[],
        )


def load_latest_autonomy_board_summary(project_root: Path) -> dict[str, Any]:
    payload = _load_yaml(latest_autonomy_board_path(project_root))
    if not payload:
        return {}
    best_mode = payload.get("best_mode")
    validated = None
    top_blocker = None
    summaries = payload.get("mode_summaries", [])
    if isinstance(summaries, list):
        for item in summaries:
            if not isinstance(item, dict):
                continue
            if item.get("mode") == best_mode:
                validated = item.get("validated_proposal_rate")
                reasons = item.get("stop_reason_counts") if isinstance(item.get("stop_reason_counts"), dict) else {}
                top_blocker = next(iter(reasons), None)
                break
    return {
        "workset_name": payload.get("workset_name"),
        "best_mode": best_mode,
        "validated_proposal_rate": validated,
        "top_blocker": top_blocker,
    }


def render_workset_replay(report: WorksetReplayReport, saved_path: str | None = None) -> str:
    lines = [
        "Workset Replay",
        "==================================================",
        "",
        "Workset:",
        f"  {report.workset_name}",
        "",
        "Mode:",
        f"  {report.mode}",
        "",
        "Cases run:",
        f"  {report.total_cases}",
        "",
        "Reached proposal_validated:",
        f"  {report.stage_counts.get('proposal_validated', 0)}",
        "",
        "Stage reached:",
    ]
    for stage in REPLAY_STAGES:
        lines.append(f"  {stage:<20}: {report.stage_counts.get(stage, 0)}/{report.total_cases}")
    lines.extend(["", "Top stop reasons:"])
    if report.stop_reason_counts:
        for reason, count in list(report.stop_reason_counts.items())[:5]:
            lines.append(f"  - {reason} ({count})")
    else:
        lines.append("  none")
    lines.extend(["", "Summary:"])
    lines.append(f"  validated proposal rate : {_format_rate(report.summary.get('validated_proposal_rate'))}")
    lines.append(f"  validation autonomy     : {_format_rate(report.summary.get('validation_autonomy_rate'))}")
    lines.append(f"  human intervention      : {_format_rate(report.summary.get('human_intervention_rate'))}")
    lines.append(f"  median duration         : {_format_seconds(report.summary.get('median_duration_seconds'))}")
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def render_autonomy_board(board: AutonomyEvidenceBoard, saved_path: str | None = None) -> str:
    lines = [
        "Autonomy Evidence Board",
        "==================================================",
        "",
        "Workset:",
        f"  {board.workset_name}",
        "",
        "Modes compared:",
    ]
    if board.modes:
        lines.extend([f"  {mode}" for mode in board.modes])
    else:
        lines.append("  none")
    lines.extend(["", "Best mode:", f"  {board.best_mode or 'none'}", "", "By mode:"])
    for summary in board.mode_summaries:
        lines.extend(
            [
                f"  {summary.mode}",
                f"    validated proposal rate : {_format_rate(summary.validated_proposal_rate)}",
                f"    validation autonomy     : {_format_rate(summary.validation_autonomy_rate)}",
                f"    intervention            : {_format_rate(summary.human_intervention_rate)}",
                f"    median duration         : {_format_seconds(summary.median_duration_seconds)}",
            ]
        )
    top_reasons = _overall_stop_reasons(board.mode_summaries)
    lines.extend(["", "Top stop reasons overall:"])
    if top_reasons:
        for reason, count in list(top_reasons.items())[:5]:
            lines.append(f"  - {reason} ({count})")
    else:
        lines.append("  none")
    if board.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in board.summary])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if board.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in board.warnings])
    return "\n".join(lines)


def _entry_from_replay(replay: BenchmarkReplayReport, replay_ref: str | None) -> WorksetReplayEntry:
    snapshot = replay.metrics_snapshot if isinstance(replay.metrics_snapshot, dict) else {}
    duration = snapshot.get("duration_seconds")
    try:
        duration_value = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_value = None
    return WorksetReplayEntry(
        case_id=replay.case_id,
        case_name=replay.case_name,
        mode=replay.mode,
        replay_ref=replay_ref,
        status=replay.status,
        autonomy_stage_reached=replay.autonomy_stage_reached,
        stop_reason=replay.stop_reason,
        validated_proposal=_bool_or_none(snapshot.get("validated_proposal")),
        validation_autonomy=_bool_or_none(snapshot.get("validation_autonomy")),
        human_intervention=_bool_or_none(snapshot.get("human_intervention")),
        duration_seconds=duration_value,
        warnings=list(replay.warnings),
        errors=list(replay.errors),
    )


def _build_workset_replay(
    workset_name: str,
    mode: str,
    total_cases: int,
    entries: list[WorksetReplayEntry],
    warnings: list[str],
    errors: list[str],
) -> WorksetReplayReport:
    stage_counts = _count([entry.autonomy_stage_reached for entry in entries])
    for stage in REPLAY_STAGES:
        stage_counts.setdefault(stage, 0)
    stop_reason_counts = _count([entry.stop_reason for entry in entries])
    summary = {
        "validated_proposal_rate": _rate([entry.validated_proposal for entry in entries]),
        "validation_autonomy_rate": _rate([entry.validation_autonomy for entry in entries]),
        "human_intervention_rate": _rate([entry.human_intervention for entry in entries]),
        "median_duration_seconds": _median([entry.duration_seconds for entry in entries]),
    }
    return WorksetReplayReport(
        schema_version=SCHEMA_VERSION,
        replay_id=f"workset-replay-{_slug(workset_name)}-{mode}-{_short_id()}",
        created_at=_now(),
        workset_name=workset_name,
        mode=mode,
        total_cases=total_cases,
        entries=entries,
        stage_counts=stage_counts,
        stop_reason_counts=stop_reason_counts,
        summary=summary,
        warnings=_dedupe(warnings + [warning for entry in entries for warning in entry.warnings]),
        errors=_dedupe(errors + [error for entry in entries for error in entry.errors]),
    )


def _mode_summary_from_report(report: WorksetReplayReport) -> AutonomyModeSummary:
    warnings: list[str] = []
    if report.total_cases <= 0:
        warnings.append("no cases in workset replay")
    if report.summary.get("validated_proposal_rate") is None:
        warnings.append("validated proposal rate is not comparable")
    return AutonomyModeSummary(
        mode=report.mode,
        total_cases=report.total_cases,
        validated_proposal_rate=report.summary.get("validated_proposal_rate"),
        validation_autonomy_rate=report.summary.get("validation_autonomy_rate"),
        human_intervention_rate=report.summary.get("human_intervention_rate"),
        median_duration_seconds=report.summary.get("median_duration_seconds"),
        stage_counts=dict(report.stage_counts),
        stop_reason_counts=dict(report.stop_reason_counts),
        summary=_mode_summary_lines(report),
        warnings=_dedupe(warnings + list(report.warnings)),
    )


def _mode_summary_lines(report: WorksetReplayReport) -> list[str]:
    validated = report.summary.get("validated_proposal_rate")
    lines: list[str] = []
    if validated is not None:
        lines.append(f"{report.mode} reached validated proposal on {float(validated) * 100:.0f}% of cases")
    top_reason = next(iter(report.stop_reason_counts), None)
    if top_reason:
        lines.append(f"top blocker: {top_reason}")
    return lines or ["no comparable autonomy signal yet"]


def _best_mode(summaries: list[AutonomyModeSummary]) -> str | None:
    comparable = [summary for summary in summaries if summary.validated_proposal_rate is not None]
    if not comparable:
        return None

    def key(summary: AutonomyModeSummary) -> tuple[float, float, float, float]:
        validated = _score(summary.validated_proposal_rate, -1.0)
        autonomy = _score(summary.validation_autonomy_rate, -1.0)
        intervention = _score(summary.human_intervention_rate, 1.0)
        duration = _score(summary.median_duration_seconds, 1_000_000.0)
        return (validated, autonomy, -intervention, -duration)

    return sorted(comparable, key=key, reverse=True)[0].mode


def _board_summary(best_mode: str | None, summaries: list[AutonomyModeSummary]) -> list[str]:
    if not summaries:
        return ["No workset replay evidence yet."]
    if not best_mode:
        return ["Autonomy evidence is too sparse to pick a best mode."]
    selected = next((summary for summary in summaries if summary.mode == best_mode), None)
    if selected is None:
        return [f"{best_mode} leads this workset."]
    validated = _format_rate(selected.validated_proposal_rate)
    return [f"{best_mode} leads this workset with validated proposal rate {validated}."]


def _overall_stop_reasons(summaries: list[AutonomyModeSummary]) -> dict[str, int]:
    combined: dict[str, int] = {}
    for summary in summaries:
        for reason, count in summary.stop_reason_counts.items():
            combined[reason] = combined.get(reason, 0) + int(count or 0)
    return dict(sorted(combined.items(), key=lambda item: (-item[1], item[0])))


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "success", "passed"}
    return bool(value)


def _score(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _workset_replay_from_dict(payload: dict[str, Any]) -> WorksetReplayReport:
    return WorksetReplayReport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        replay_id=str(payload.get("replay_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        workset_name=str(payload.get("workset_name") or ""),
        mode=str(payload.get("mode") or "cambrian_guided"),
        total_cases=int(payload.get("total_cases", 0) or 0),
        entries=[_entry_from_dict(item) for item in payload.get("entries", []) if isinstance(item, dict)],
        stage_counts={str(key): int(value or 0) for key, value in dict(payload.get("stage_counts", {})).items()},
        stop_reason_counts={str(key): int(value or 0) for key, value in dict(payload.get("stop_reason_counts", {})).items()},
        summary=dict(payload.get("summary", {})) if isinstance(payload.get("summary"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _entry_from_dict(payload: dict[str, Any]) -> WorksetReplayEntry:
    return WorksetReplayEntry(
        case_id=str(payload.get("case_id") or ""),
        case_name=str(payload.get("case_name") or payload.get("case_id") or ""),
        mode=str(payload.get("mode") or "cambrian_guided"),
        replay_ref=str(payload.get("replay_ref")) if payload.get("replay_ref") is not None else None,
        status=str(payload.get("status") or "partial"),
        autonomy_stage_reached=str(payload.get("autonomy_stage_reached")) if payload.get("autonomy_stage_reached") is not None else None,
        stop_reason=str(payload.get("stop_reason")) if payload.get("stop_reason") is not None else None,
        validated_proposal=_bool_or_none(payload.get("validated_proposal")),
        validation_autonomy=_bool_or_none(payload.get("validation_autonomy")),
        human_intervention=_bool_or_none(payload.get("human_intervention")),
        duration_seconds=_score(payload.get("duration_seconds"), None) if payload.get("duration_seconds") is not None else None,
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _board_from_dict(payload: dict[str, Any]) -> AutonomyEvidenceBoard:
    return AutonomyEvidenceBoard(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        generated_at=str(payload.get("generated_at") or ""),
        board_id=str(payload.get("board_id") or ""),
        workset_name=str(payload.get("workset_name") or ""),
        modes=[str(item) for item in payload.get("modes", []) if item],
        mode_summaries=[_mode_summary_from_dict(item) for item in payload.get("mode_summaries", []) if isinstance(item, dict)],
        best_mode=str(payload.get("best_mode")) if payload.get("best_mode") is not None else None,
        summary=[str(item) for item in payload.get("summary", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _mode_summary_from_dict(payload: dict[str, Any]) -> AutonomyModeSummary:
    return AutonomyModeSummary(
        mode=str(payload.get("mode") or ""),
        total_cases=int(payload.get("total_cases", 0) or 0),
        validated_proposal_rate=payload.get("validated_proposal_rate"),
        validation_autonomy_rate=payload.get("validation_autonomy_rate"),
        human_intervention_rate=payload.get("human_intervention_rate"),
        median_duration_seconds=payload.get("median_duration_seconds"),
        stage_counts=dict(payload.get("stage_counts", {})) if isinstance(payload.get("stage_counts"), dict) else {},
        stop_reason_counts=dict(payload.get("stop_reason_counts", {})) if isinstance(payload.get("stop_reason_counts"), dict) else {},
        summary=[str(item) for item in payload.get("summary", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
    )
