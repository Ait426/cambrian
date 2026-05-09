"""Autonomy evidence에서 병목과 개선 queue를 만든다."""

from __future__ import annotations

import logging
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_benchmark_compare import latest_compare_path
from engine.project_benchmark_workset_replay import (
    WorksetReplayEntry,
    WorksetReplayReport,
    WorksetReplayStore,
    default_workset_replays_dir,
    latest_autonomy_board_path,
)
from engine.project_benchmarks import default_benchmark_dir

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
VALID_MODES = {"all", "cambrian_guided", "cambrian_full"}


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


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("autonomy bottleneck artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def default_bottlenecks_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "bottlenecks"


def default_bottleneck_report_path(project_root: Path, report: "AutonomyBottleneckReport") -> Path:
    return default_bottlenecks_dir(project_root) / f"bottlenecks_{_slug(report.workset_name)}_{report.mode}_{_stamp()}_{_short_id()}.yaml"


def latest_bottleneck_path(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "latest_bottleneck.yaml"


@dataclass
class AutonomyBottleneck:
    bottleneck_id: str
    kind: str
    mode: str
    severity: str
    frequency: int
    affected_cases: list[str]
    summary: str
    reasons: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomyImprovementSuggestion:
    suggestion_id: str
    kind: str
    target: str | None
    priority: str
    confidence: float
    summary: str
    reasons: list[str] = field(default_factory=list)
    next_commands: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AutonomyBottleneckReport:
    schema_version: str
    generated_at: str
    report_id: str
    workset_name: str
    mode: str
    source_refs: dict[str, Any]
    bottlenecks: list[AutonomyBottleneck]
    suggestions: list[AutonomyImprovementSuggestion]
    summary: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bottlenecks"] = [item.to_dict() for item in self.bottlenecks]
        payload["suggestions"] = [item.to_dict() for item in self.suggestions]
        return payload


class AutonomyBottleneckStore:
    def save(self, report: AutonomyBottleneckReport, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent.parent / "latest_bottleneck.yaml", report.to_dict())
        return saved

    def load(self, path: Path) -> AutonomyBottleneckReport:
        return _report_from_dict(_load_yaml(Path(path).resolve()))


class AutonomyBottleneckAnalyzer:
    def build(self, project_root: Path, workset_name: str, mode: str = "all") -> AutonomyBottleneckReport:
        root = Path(project_root).resolve()
        if mode not in VALID_MODES:
            raise ValueError(f"unsupported bottleneck mode: {mode}")

        warnings: list[str] = []
        errors: list[str] = []
        board_payload, board_ref = _latest_board_payload(root, workset_name)
        if not board_payload:
            warnings.append("no autonomy board found for workset")

        replay_reports = _latest_replay_reports(root, workset_name, mode)
        if not replay_reports:
            warnings.append("no workset replay reports found for analysis")

        compare_payload = _latest_compare_payload(root, workset_name)
        entries = [entry for report in replay_reports for entry in report.entries]
        total_cases = len(entries)
        bottlenecks = self._detect_bottlenecks(
            workset_name=workset_name,
            mode=mode,
            reports=replay_reports,
            entries=entries,
            board_payload=board_payload,
            compare_payload=compare_payload,
        )
        suggestions = self._suggestions(workset_name, mode, bottlenecks)
        metrics = _summary_metrics(replay_reports, board_payload, mode)
        summary = {
            "top_bottleneck": bottlenecks[0].kind if bottlenecks else None,
            "top_suggestion": suggestions[0].summary if suggestions else None,
            "validated_proposal_rate": metrics.get("validated_proposal_rate"),
            "validation_autonomy_rate": metrics.get("validation_autonomy_rate"),
            "human_intervention_rate": metrics.get("human_intervention_rate"),
            "best_mode": board_payload.get("best_mode") if board_payload else None,
            "total_analyzed_entries": total_cases,
        }
        source_refs = {
            "autonomy_board_ref": board_ref,
            "replay_refs": [_report_ref(root, report) for report in replay_reports],
            "compare_ref": _relative(latest_compare_path(root), root) if compare_payload else None,
        }
        if not bottlenecks and entries:
            warnings.append("no repeated autonomy bottleneck exceeded V1 thresholds")
        return AutonomyBottleneckReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            report_id=f"autonomy-bottlenecks-{_slug(workset_name)}-{mode}-{_short_id()}",
            workset_name=workset_name,
            mode=mode,
            source_refs=source_refs,
            bottlenecks=bottlenecks,
            suggestions=suggestions,
            summary=summary,
            warnings=_dedupe(warnings),
            errors=errors,
        )

    def _detect_bottlenecks(
        self,
        *,
        workset_name: str,
        mode: str,
        reports: list[WorksetReplayReport],
        entries: list[WorksetReplayEntry],
        board_payload: dict[str, Any],
        compare_payload: dict[str, Any],
    ) -> list[AutonomyBottleneck]:
        if not entries:
            return []
        total = len(entries)
        candidates: list[AutonomyBottleneck] = []
        checks = [
            ("ambiguous_context_selection", _match_ambiguous_context),
            ("no_safe_context_candidate", _match_no_safe_context),
            ("missing_patch_candidate", _match_missing_patch_candidate),
            ("validation_failure_cluster", _match_validation_failure),
            ("weak_team_fit", _match_team_fit),
            ("weak_template_fit", _match_template_fit),
            ("review_support_gap", _match_review_gap),
            ("narrow_scope_gap", _match_scope_gap),
            ("memory_hygiene_drag", _match_memory_gap),
        ]
        for kind, matcher in checks:
            matched = [entry for entry in entries if matcher(entry)]
            if not _meaningful(matched, total):
                continue
            candidates.append(
                _bottleneck(
                    kind=kind,
                    workset_name=workset_name,
                    mode=mode,
                    matched=matched,
                    total=total,
                    board_payload=board_payload,
                    compare_payload=compare_payload,
                )
            )
        if mode == "all":
            bridge_gap = _bridge_dependency_gap(workset_name, reports, board_payload, compare_payload)
            if bridge_gap is not None:
                candidates.append(bridge_gap)
        candidates.sort(key=lambda item: (_severity_rank(item.severity), item.frequency, item.kind), reverse=True)
        return candidates

    def _suggestions(
        self,
        workset_name: str,
        mode: str,
        bottlenecks: list[AutonomyBottleneck],
    ) -> list[AutonomyImprovementSuggestion]:
        suggestions: list[AutonomyImprovementSuggestion] = []
        for bottleneck in bottlenecks:
            mapping = _SUGGESTION_MAP.get(bottleneck.kind)
            if mapping is None:
                continue
            suggestion_kind, summary, commands = mapping
            suggestions.append(
                AutonomyImprovementSuggestion(
                    suggestion_id=f"suggestion-{suggestion_kind}-{_short_id()}",
                    kind=suggestion_kind,
                    target=workset_name,
                    priority=bottleneck.severity,
                    confidence=_confidence(bottleneck),
                    summary=summary,
                    reasons=[
                        f"{bottleneck.kind} affected {bottleneck.frequency} case(s) in {mode} analysis",
                        *bottleneck.reasons[:2],
                    ],
                    next_commands=[command.format(workset=workset_name) for command in commands],
                    evidence_refs=list(bottleneck.evidence_refs),
                    warnings=[],
                )
            )
        suggestions.sort(key=lambda item: (_severity_rank(item.priority), item.confidence), reverse=True)
        return suggestions


_SUGGESTION_MAP: dict[str, tuple[str, str, list[str]]] = {
    "ambiguous_context_selection": (
        "strengthen_context_hints",
        "strengthen context hints for repeated files/tests in this workset",
        ["cambrian bridge context-hints", "cambrian benchmark bottlenecks {workset} --mode all"],
    ),
    "no_safe_context_candidate": (
        "add_case_replay_hints",
        "add safer replay hints or template fit signals for cases with no context candidate",
        ["cambrian benchmark cases", "cambrian template recommend"],
    ),
    "missing_patch_candidate": (
        "add_bridge_patch_candidate",
        "improve bridge patch candidate coverage for cases that stall after diagnosis",
        ["cambrian bridge prepare \"<request>\"", "cambrian bridge ingest <reply-file>"],
    ),
    "validation_failure_cluster": (
        "improve_validation_support",
        "improve validation support before treating patch-intent-ready as autonomous success",
        ["cambrian benchmark replay-workset {workset} --mode cambrian_full", "cambrian metrics week"],
    ),
    "bridge_dependency_gap": (
        "improve_bridge_coverage",
        "full mode is outperforming guided mode, so expand bridge coverage deliberately",
        ["cambrian benchmark replay-workset {workset} --mode cambrian_full", "cambrian bridge prepare \"<request>\""],
    ),
    "weak_team_fit": (
        "review_team_fit",
        "review team fit for cases with repeated support or staffing-related stalls",
        ["cambrian team recommend", "cambrian team trial"],
    ),
    "weak_template_fit": (
        "review_template_fit",
        "review template fit for repeated autonomy stalls in this workset",
        ["cambrian template recommend", "cambrian template board"],
    ),
    "review_support_gap": (
        "increase_review_support",
        "increase review support where validation or safety review repeatedly blocks autonomy",
        ["cambrian team recommend", "cambrian template board"],
    ),
    "narrow_scope_gap": (
        "narrow_scope_defaults",
        "tighten narrow-scope defaults to reduce broad-refactor drift",
        ["cambrian harness suggest", "cambrian template recommend"],
    ),
    "memory_hygiene_drag": (
        "review_memory_hygiene",
        "review memory hygiene because stale or conflicting hints may be dragging autonomy",
        ["cambrian memory hygiene", "cambrian status"],
    ),
}


def render_bottleneck_report(report: AutonomyBottleneckReport, saved_path: str | None = None) -> str:
    lines = [
        "Autonomy Bottlenecks",
        "==================================================",
        "",
        "Workset:",
        f"  {report.workset_name}",
        "",
        "Mode:",
        f"  {report.mode}",
        "",
        "Top bottlenecks:",
    ]
    if report.bottlenecks:
        for index, bottleneck in enumerate(report.bottlenecks[:5], start=1):
            lines.append(f"  {index}. {bottleneck.kind}")
            lines.append(f"     - {bottleneck.summary}")
            if bottleneck.reasons:
                lines.append(f"       why: {bottleneck.reasons[0]}")
    else:
        lines.append("  none")
    lines.extend(["", "Top next fixes:"])
    if report.suggestions:
        for suggestion in report.suggestions[:5]:
            lines.append(f"  - {suggestion.summary}")
    else:
        lines.append("  none")
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings[:5]])
    return "\n".join(lines)


def load_latest_bottleneck_summary(project_root: Path) -> dict[str, Any]:
    payload = _load_yaml(latest_bottleneck_path(Path(project_root).resolve()))
    if not payload:
        return {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "workset_name": payload.get("workset_name"),
        "mode": payload.get("mode"),
        "top_bottleneck": summary.get("top_bottleneck"),
        "top_suggestion": summary.get("top_suggestion"),
        "validated_proposal_rate": summary.get("validated_proposal_rate"),
        "validation_autonomy_rate": summary.get("validation_autonomy_rate"),
        "human_intervention_rate": summary.get("human_intervention_rate"),
    }


def _latest_board_payload(root: Path, workset_name: str) -> tuple[dict[str, Any], str | None]:
    latest = latest_autonomy_board_path(root)
    payload = _load_yaml(latest)
    if payload and str(payload.get("workset_name") or "") == workset_name:
        return payload, _relative(latest, root)
    boards_dir = default_benchmark_dir(root) / "autonomy_boards"
    candidates: list[Path] = []
    for path in boards_dir.glob("board_*.yaml"):
        item = _load_yaml(path)
        if str(item.get("workset_name") or "") == workset_name:
            candidates.append(path)
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        return {}, None
    selected = candidates[0]
    return _load_yaml(selected), _relative(selected, root)


def _latest_compare_payload(root: Path, workset_name: str) -> dict[str, Any]:
    payload = _load_yaml(latest_compare_path(root))
    if payload and str(payload.get("workset_name") or "") == workset_name:
        return payload
    return {}


def _latest_replay_reports(root: Path, workset_name: str, mode: str) -> list[WorksetReplayReport]:
    reports = [
        report
        for report in WorksetReplayStore().list(default_workset_replays_dir(root))
        if report.workset_name == workset_name and (mode == "all" or report.mode == mode)
    ]
    latest_by_mode: dict[str, WorksetReplayReport] = {}
    for report in reports:
        latest_by_mode.setdefault(report.mode, report)
    return list(latest_by_mode.values())


def _report_ref(root: Path, report: WorksetReplayReport) -> str | None:
    for path in default_workset_replays_dir(root).glob("replay_*.yaml"):
        payload = _load_yaml(path)
        if payload.get("replay_id") == report.replay_id:
            return _relative(path, root)
    return None


def _summary_metrics(reports: list[WorksetReplayReport], board_payload: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode != "all" and reports:
        return dict(reports[0].summary)
    if board_payload and isinstance(board_payload.get("mode_summaries"), list):
        best_mode = board_payload.get("best_mode")
        for item in board_payload.get("mode_summaries", []):
            if isinstance(item, dict) and item.get("mode") == best_mode:
                return {
                    "validated_proposal_rate": item.get("validated_proposal_rate"),
                    "validation_autonomy_rate": item.get("validation_autonomy_rate"),
                    "human_intervention_rate": item.get("human_intervention_rate"),
                }
    entries = [entry for report in reports for entry in report.entries]
    return {
        "validated_proposal_rate": _rate([entry.validated_proposal for entry in entries]),
        "validation_autonomy_rate": _rate([entry.validation_autonomy for entry in entries]),
        "human_intervention_rate": _rate([entry.human_intervention for entry in entries]),
    }


def _rate(values: list[Any]) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return round(sum(1 for value in known if bool(value)) / len(known), 4)


def _meaningful(matched: list[WorksetReplayEntry], total: int) -> bool:
    if not matched:
        return False
    if len(matched) >= 2:
        return True
    return total <= 2 and len(matched) / max(total, 1) >= 0.5


def _bottleneck(
    *,
    kind: str,
    workset_name: str,
    mode: str,
    matched: list[WorksetReplayEntry],
    total: int,
    board_payload: dict[str, Any],
    compare_payload: dict[str, Any],
) -> AutonomyBottleneck:
    severity = _severity(len(matched), total, kind)
    affected = _dedupe([entry.case_name or entry.case_id for entry in matched])
    reasons = _reasons(kind, matched)
    evidence_refs = _dedupe([ref for entry in matched for ref in [entry.replay_ref] if ref])
    confidence_note = []
    if board_payload:
        confidence_note.append("autonomy board evidence is available")
    if compare_payload:
        confidence_note.append("benchmark compare evidence is available")
    return AutonomyBottleneck(
        bottleneck_id=f"bottleneck-{kind}-{_slug(workset_name)}-{_short_id()}",
        kind=kind,
        mode=mode,
        severity=severity,
        frequency=len(matched),
        affected_cases=affected,
        summary=_summary_for_kind(kind, len(matched), total),
        reasons=_dedupe(reasons + confidence_note),
        evidence_refs=evidence_refs,
        warnings=[],
    )


def _bridge_dependency_gap(
    workset_name: str,
    reports: list[WorksetReplayReport],
    board_payload: dict[str, Any],
    compare_payload: dict[str, Any],
) -> AutonomyBottleneck | None:
    by_mode = {report.mode: report for report in reports}
    guided = by_mode.get("cambrian_guided")
    full = by_mode.get("cambrian_full")
    if guided is None or full is None:
        return None
    guided_rate = _float(guided.summary.get("validated_proposal_rate"))
    full_rate = _float(full.summary.get("validated_proposal_rate"))
    if guided_rate is None or full_rate is None or full_rate - guided_rate < 0.2:
        return None
    affected = [entry for entry in full.entries if entry.validated_proposal]
    return _bottleneck(
        kind="bridge_dependency_gap",
        workset_name=workset_name,
        mode="all",
        matched=affected or full.entries,
        total=max(full.total_cases, 1),
        board_payload=board_payload,
        compare_payload=compare_payload,
    )


def _text(entry: WorksetReplayEntry) -> str:
    parts = [
        entry.stop_reason or "",
        " ".join(entry.warnings),
        " ".join(entry.errors),
        entry.autonomy_stage_reached or "",
    ]
    return " ".join(parts).lower()


def _match_ambiguous_context(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return "ambiguous source selection" in text or "ambiguous context" in text


def _match_no_safe_context(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return "no safe source candidate" in text or "no safe context candidate" in text


def _match_missing_patch_candidate(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return (
        "no safe prefilled patch candidate" in text
        or "patch candidate" in text and "not available" in text
        or "bridge reply missing" in text
        or "no patch candidate" in text
    )


def _match_validation_failure(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return entry.autonomy_stage_reached == "patch_intent_ready" and (
        "validation" in text
        or "old_text" in text
        or "prefill is incomplete" in text
        or "not found in target" in text
    )


def _match_team_fit(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return "team" in text or "staff" in text or "lead agent" in text


def _match_template_fit(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return "template" in text or "weak fit" in text


def _match_review_gap(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return "review" in text or "support" in text or "safety" in text


def _match_scope_gap(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return "broad refactor" in text or "scope" in text or "narrow" in text


def _match_memory_gap(entry: WorksetReplayEntry) -> bool:
    text = _text(entry)
    return "memory" in text or "stale" in text or "conflict" in text or "hygiene" in text


def _severity(frequency: int, total: int, kind: str) -> str:
    share = frequency / max(total, 1)
    if kind in {"ambiguous_context_selection", "missing_patch_candidate", "validation_failure_cluster"} and frequency >= 2:
        return "high"
    if share >= 0.4 and frequency >= 2:
        return "high"
    if frequency >= 2 or share >= 0.25:
        return "medium"
    return "low"


def _severity_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)


def _confidence(bottleneck: AutonomyBottleneck) -> float:
    value = 0.5
    if bottleneck.frequency >= 2:
        value += 0.1
    if bottleneck.evidence_refs:
        value += 0.1
    if any("autonomy board" in reason for reason in bottleneck.reasons):
        value += 0.1
    if any("benchmark compare" in reason for reason in bottleneck.reasons):
        value += 0.1
    return min(0.9, round(value, 2))


def _summary_for_kind(kind: str, frequency: int, total: int) -> str:
    details = {
        "ambiguous_context_selection": "cases stopped before diagnose because source selection stayed ambiguous",
        "no_safe_context_candidate": "cases could not find a safe context candidate",
        "missing_patch_candidate": "cases reached diagnose but had no safe patch candidate",
        "validation_failure_cluster": "cases reached patch intent but did not validate",
        "bridge_dependency_gap": "full mode outperformed guided mode because bridge-assisted evidence mattered",
        "weak_team_fit": "cases show repeated team or staffing fit signals",
        "weak_template_fit": "cases show repeated template fit caution signals",
        "review_support_gap": "cases show repeated review or safety support gaps",
        "narrow_scope_gap": "cases show repeated narrow-scope or broad-refactor drift signals",
        "memory_hygiene_drag": "cases show memory hygiene or stale hint signals",
    }
    return f"{frequency}/{total} {details.get(kind, 'cases show repeated autonomy stall signals')}"


def _reasons(kind: str, matched: list[WorksetReplayEntry]) -> list[str]:
    cases = ", ".join(_dedupe([entry.case_name or entry.case_id for entry in matched])[:5])
    stop_reasons = _dedupe([entry.stop_reason or "" for entry in matched if entry.stop_reason])
    reasons = [f"affected cases: {cases}"] if cases else []
    if stop_reasons:
        reasons.append(f"top stop reason: {stop_reasons[0]}")
    if kind == "bridge_dependency_gap":
        reasons.append("cambrian_full is materially stronger than cambrian_guided on this workset")
    return reasons


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _report_from_dict(payload: dict[str, Any]) -> AutonomyBottleneckReport:
    return AutonomyBottleneckReport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        generated_at=str(payload.get("generated_at") or ""),
        report_id=str(payload.get("report_id") or ""),
        workset_name=str(payload.get("workset_name") or ""),
        mode=str(payload.get("mode") or "all"),
        source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
        bottlenecks=[
            AutonomyBottleneck(
                bottleneck_id=str(item.get("bottleneck_id") or ""),
                kind=str(item.get("kind") or ""),
                mode=str(item.get("mode") or "all"),
                severity=str(item.get("severity") or "low"),
                frequency=int(item.get("frequency", 0) or 0),
                affected_cases=[str(case) for case in item.get("affected_cases", []) if case],
                summary=str(item.get("summary") or ""),
                reasons=[str(reason) for reason in item.get("reasons", []) if reason],
                evidence_refs=[str(ref) for ref in item.get("evidence_refs", []) if ref],
                warnings=[str(warning) for warning in item.get("warnings", []) if warning],
            )
            for item in payload.get("bottlenecks", [])
            if isinstance(item, dict)
        ],
        suggestions=[
            AutonomyImprovementSuggestion(
                suggestion_id=str(item.get("suggestion_id") or ""),
                kind=str(item.get("kind") or ""),
                target=str(item.get("target")) if item.get("target") is not None else None,
                priority=str(item.get("priority") or "low"),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                summary=str(item.get("summary") or ""),
                reasons=[str(reason) for reason in item.get("reasons", []) if reason],
                next_commands=[str(command) for command in item.get("next_commands", []) if command],
                evidence_refs=[str(ref) for ref in item.get("evidence_refs", []) if ref],
                warnings=[str(warning) for warning in item.get("warnings", []) if warning],
            )
            for item in payload.get("suggestions", [])
            if isinstance(item, dict)
        ],
        summary=dict(payload.get("summary", {})) if isinstance(payload.get("summary"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
