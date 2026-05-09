"""canary template 선택 이후 outcome attribution을 계산한다."""

from __future__ import annotations

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

from engine.project_template_canary import active_canary_stage
from engine.project_template_canary_ledger import (
    CanaryEventStore,
    CanaryExposureEvent,
    CanaryLedgerBuilder,
    canary_events_dir,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


class CanaryOutcomeBlockedError(RuntimeError):
    """outcome attribution 대상 canary를 찾을 수 없을 때 발생한다."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    return secrets.token_hex(2)


def _slug(value: str | None, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
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
        logger.warning("canary outcome artifact load failed: %s (%s)", path, exc)
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


def canary_outcome_links_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "canary_outcomes" / "links"


def canary_outcome_summaries_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "canary_outcomes" / "summaries"


def default_canary_outcome_link_path(project_root: Path, link: "CanaryOutcomeLink") -> Path:
    return canary_outcome_links_dir(project_root) / f"link_{_stamp()}_{_slug(link.selection_source_kind)}_{_short_id()}.yaml"


def default_canary_outcome_summary_path(project_root: Path, summary: "CanaryOutcomeSummary") -> Path:
    return canary_outcome_summaries_dir(project_root) / f"summary_{_slug(summary.template_name)}_{_stamp()}_{_short_id()}.yaml"


def latest_canary_outcomes_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "latest_canary_outcomes.yaml"


@dataclass
class CanaryOutcomeLink:
    """canary 선택/override와 downstream 결과를 잇는 단일 attribution link."""

    schema_version: str
    link_id: str
    created_at: str
    template_name: str
    template_id: str | None
    canary_stage_id: str | None
    selection_source_kind: str
    selection_ref: str | None
    selected_at: str | None
    linked_session_id: str | None
    linked_session_ref: str | None
    linked_request_ref: str | None
    linked_benchmark_result_ref: str | None
    linked_replay_ref: str | None
    outcome_kind: str
    validated_proposal: bool | None
    adoption_succeeded: bool | None
    regression_free_apply: bool | None
    human_intervention: bool | None
    validation_autonomy: bool | None
    duration_seconds: float | None
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanaryOutcomeSummary:
    """canary outcome attribution 집계."""

    schema_version: str
    report_id: str
    generated_at: str
    template_name: str
    template_id: str | None
    canary_stage_id: str | None
    counts: dict[str, int]
    ratios: dict[str, float | None]
    medians: dict[str, float | None]
    summary: list[str]
    source_refs: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CanaryOutcomeLinkBuilder:
    """canary 선택 event와 session/replay outcome을 연결한다."""

    def build_links(self, project_root: Path, template_name: str) -> list[CanaryOutcomeLink]:
        root = Path(project_root).resolve()
        stage = active_canary_stage(root)
        stage_id = stage.stage_id if stage and _same(stage.candidate_template_name, template_name) else None
        template_id = stage.candidate_template_id if stage and _same(stage.candidate_template_name, template_name) else None
        events = CanaryEventStore().list_events(canary_events_dir(root), template_name)
        sessions = _session_payloads(root)
        benchmark_results = _benchmark_result_payloads(root)
        links: list[CanaryOutcomeLink] = []
        seen: set[str] = set()

        for event in sorted(events, key=lambda item: item.created_at):
            if event.event_kind == "selected" and event.selection_result == "canary":
                link = _link_selection_event(root, event, sessions, benchmark_results, stage_id, template_id)
            elif event.event_kind in {"applied", "bootstrapped"}:
                link = _link_selection_event(root, event, sessions, benchmark_results, stage_id, template_id)
            elif event.event_kind == "replayed":
                link = _link_replay_event(root, event, stage_id, template_id)
            else:
                continue
            if link.link_id in seen:
                continue
            seen.add(link.link_id)
            links.append(link)
        return links


class CanaryOutcomeSummaryBuilder:
    """canary outcome link를 집계한다."""

    def build(self, project_root: Path, template_name: str | None = None) -> CanaryOutcomeSummary:
        root = Path(project_root).resolve()
        stage = active_canary_stage(root)
        target_name = str(template_name or (stage.candidate_template_name if stage else "")).strip()
        if not target_name:
            raise CanaryOutcomeBlockedError(
                "No active canary template found. Run: cambrian template qualify-stage <qualification>"
            )
        links = CanaryOutcomeLinkBuilder().build_links(root, target_name)
        try:
            ledger = CanaryLedgerBuilder().build(root, target_name)
            ledger_counts = dict(ledger.counts)
            ledger_ratios = dict(ledger.ratios)
        except Exception as exc:
            logger.warning("canary outcome ledger load failed: %s", exc)
            ledger_counts = {}
            ledger_ratios = {}
        counts = _summary_counts(links, ledger_counts)
        ratios = _summary_ratios(links, counts, ledger_ratios)
        medians = _summary_medians(links)
        warnings: list[str] = []
        partials = [link for link in links if link.outcome_kind == "partial"]
        if partials:
            warnings.append(f"{len(partials)} canary selections have no linked outcome yet")
        if counts["selected_count"] and not counts["selected_with_outcome_count"]:
            warnings.append("canary was selected but no high-confidence downstream outcome was found")
        return CanaryOutcomeSummary(
            schema_version=SCHEMA_VERSION,
            report_id=f"canary-outcomes-{_slug(target_name)}-{_short_id()}",
            generated_at=_now(),
            template_name=target_name,
            template_id=_first_non_empty([link.template_id for link in links]) or getattr(stage, "candidate_template_id", None),
            canary_stage_id=getattr(stage, "stage_id", None) if stage and _same(stage.candidate_template_name, target_name) else None,
            counts=counts,
            ratios=ratios,
            medians=medians,
            summary=_summary_lines(counts, ratios),
            source_refs=_dedupe([ref for link in links for ref in _link_refs(link)])[:60],
            warnings=_dedupe(warnings),
            errors=[],
        )


class CanaryOutcomeStore:
    """canary outcome link/summary 저장소."""

    def save_link(self, link: CanaryOutcomeLink, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), link.to_dict())

    def save_summary(self, summary: CanaryOutcomeSummary, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), summary.to_dict())
        project_root = saved.parents[4] if len(saved.parents) > 4 else saved.parent
        _save_yaml(latest_canary_outcomes_path(project_root), summary.to_dict())
        return saved

    def load_link(self, path: Path) -> CanaryOutcomeLink:
        return _link_from_dict(_load_yaml(Path(path).resolve()))

    def load_summary(self, path: Path) -> CanaryOutcomeSummary:
        return _summary_from_dict(_load_yaml(Path(path).resolve()))


def build_and_save_canary_outcomes(
    project_root: Path,
    template_name: str | None = None,
) -> tuple[CanaryOutcomeSummary, list[CanaryOutcomeLink], Path]:
    root = Path(project_root).resolve()
    summary = CanaryOutcomeSummaryBuilder().build(root, template_name=template_name)
    links = CanaryOutcomeLinkBuilder().build_links(root, summary.template_name)
    store = CanaryOutcomeStore()
    for link in links:
        store.save_link(link, default_canary_outcome_link_path(root, link))
    summary_path = store.save_summary(summary, default_canary_outcome_summary_path(root, summary))
    return summary, links, summary_path


def load_canary_outcome_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    try:
        summary = CanaryOutcomeSummaryBuilder().build(project_root, template_name=template_name)
    except CanaryOutcomeBlockedError:
        return {}
    except Exception as exc:
        logger.warning("canary outcome summary load failed: %s", exc)
        return {"warnings": [f"canary outcome summary load failed: {exc}"]}
    if not any(int(value or 0) for value in summary.counts.values()):
        return {}
    return {
        "template_name": summary.template_name,
        "counts": dict(summary.counts),
        "ratios": dict(summary.ratios),
        "medians": dict(summary.medians),
        "summary": list(summary.summary[:3]),
    }


def render_canary_outcomes(summary: CanaryOutcomeSummary, saved_path: str | None = None) -> str:
    counts = summary.counts
    ratios = summary.ratios
    lines = [
        "Canary Outcome Attribution",
        "==================================================",
        "",
        "Template:",
        f"  {summary.template_name}",
        "",
        "Selected:",
        f"  {counts.get('selected_count', 0)}",
        "",
        "Selected with outcome:",
        f"  {counts.get('selected_with_outcome_count', 0)}",
        "",
        "Selected then validated:",
        f"  {counts.get('selected_then_validated_count', 0)}",
        "",
        "Selected then adopted:",
        f"  {counts.get('selected_then_adopted_count', 0)}",
        "",
        "Selected validation autonomy:",
        f"  {_pct(ratios.get('selected_validation_autonomy_rate'))}",
        "",
        "Selected human intervention:",
        f"  {_pct(ratios.get('selected_human_intervention_rate'))}",
    ]
    if summary.medians.get("selected_duration_seconds") is not None:
        lines.extend(["", "Median selected duration:", f"  {summary.medians.get('selected_duration_seconds')}s"])
    if summary.summary:
        lines.extend(["", "Meaning:"])
        lines.extend([f"  - {item}" for item in summary.summary[:5]])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if summary.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in summary.warnings[:5]])
    return "\n".join(lines)


def render_canary_links(links: list[CanaryOutcomeLink], *, limit: int = 20) -> str:
    lines = [
        "Canary Outcome Links",
        "==================================================",
        "",
        "Recent:",
    ]
    if not links:
        lines.append("  none")
        return "\n".join(lines)
    for index, link in enumerate(links[: max(1, int(limit or 20))], start=1):
        outcome = "validated proposal" if link.validated_proposal else link.outcome_kind
        lines.append(f"  {index}. {link.selection_source_kind} → {link.outcome_kind} → {outcome}")
    return "\n".join(lines)


def render_canary_outcome_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return "Canary outcomes:\n  none"
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    return "\n".join([
        "Canary outcomes:",
        f"  selected {int(counts.get('selected_count', 0) or 0)}",
        f"  with outcome {int(counts.get('selected_with_outcome_count', 0) or 0)}",
        f"  validated {int(counts.get('selected_then_validated_count', 0) or 0)}",
    ])


def _link_selection_event(
    root: Path,
    event: CanaryExposureEvent,
    sessions: list[tuple[Path, dict[str, Any]]],
    benchmark_results: list[tuple[Path, dict[str, Any]]],
    stage_id: str | None,
    template_id: str | None,
) -> CanaryOutcomeLink:
    selection_kind = "template_apply" if event.event_kind == "applied" else "bootstrap_selection"
    session = _matching_session(event, sessions)
    if session is not None:
        path, payload = session
        outcome = _session_outcome(payload)
        benchmark_ref = _matching_benchmark_result_ref(path, benchmark_results)
        return _link(
            event=event,
            stage_id=stage_id,
            template_id=template_id,
            selection_source_kind=selection_kind,
            selection_ref=event.source_ref or event.linked_bootstrap_choice_ref,
            linked_session_id=str(payload.get("session_id") or path.stem),
            linked_session_ref=_relative(path, root),
            linked_request_ref=_request_ref(payload),
            linked_benchmark_result_ref=benchmark_ref,
            linked_replay_ref=None,
            outcome_kind="session_outcome",
            outcome=outcome,
            summary="canary selection linked to session outcome",
            warnings=[],
        )
    return _link(
        event=event,
        stage_id=stage_id,
        template_id=template_id,
        selection_source_kind=selection_kind,
        selection_ref=event.source_ref or event.linked_bootstrap_choice_ref,
        linked_session_id=None,
        linked_session_ref=None,
        linked_request_ref=None,
        linked_benchmark_result_ref=None,
        linked_replay_ref=None,
        outcome_kind="partial",
        outcome={},
        summary="canary selection has no linked downstream outcome yet",
        warnings=["no matching session outcome found for canary selection"],
    )


def _link_replay_event(
    root: Path,
    event: CanaryExposureEvent,
    stage_id: str | None,
    template_id: str | None,
) -> CanaryOutcomeLink:
    replay_ref = event.linked_replay_ref or event.source_ref
    payload = _load_yaml(_resolve_ref(root, replay_ref)) if replay_ref else {}
    if payload:
        return _link(
            event=event,
            stage_id=stage_id,
            template_id=template_id,
            selection_source_kind="replay_override",
            selection_ref=replay_ref,
            linked_session_id=None,
            linked_session_ref=None,
            linked_request_ref=None,
            linked_benchmark_result_ref=None,
            linked_replay_ref=replay_ref,
            outcome_kind="replay_outcome",
            outcome=_replay_outcome(payload),
            summary="canary replay override linked to replay outcome",
            warnings=[],
        )
    return _link(
        event=event,
        stage_id=stage_id,
        template_id=template_id,
        selection_source_kind="replay_override",
        selection_ref=replay_ref,
        linked_session_id=None,
        linked_session_ref=None,
        linked_request_ref=None,
        linked_benchmark_result_ref=None,
        linked_replay_ref=replay_ref,
        outcome_kind="partial",
        outcome={},
        summary="canary replay event has no readable replay artifact",
        warnings=["no matching replay artifact found for canary replay event"],
    )


def _link(
    *,
    event: CanaryExposureEvent,
    stage_id: str | None,
    template_id: str | None,
    selection_source_kind: str,
    selection_ref: str | None,
    linked_session_id: str | None,
    linked_session_ref: str | None,
    linked_request_ref: str | None,
    linked_benchmark_result_ref: str | None,
    linked_replay_ref: str | None,
    outcome_kind: str,
    outcome: dict[str, Any],
    summary: str,
    warnings: list[str],
) -> CanaryOutcomeLink:
    return CanaryOutcomeLink(
        schema_version=SCHEMA_VERSION,
        link_id=f"canary-link-{_slug(selection_source_kind)}-{_slug(event.event_id)}",
        created_at=_now(),
        template_name=event.template_name,
        template_id=event.template_id or template_id,
        canary_stage_id=stage_id,
        selection_source_kind=selection_source_kind,
        selection_ref=selection_ref,
        selected_at=event.created_at,
        linked_session_id=linked_session_id,
        linked_session_ref=linked_session_ref,
        linked_request_ref=linked_request_ref,
        linked_benchmark_result_ref=linked_benchmark_result_ref,
        linked_replay_ref=linked_replay_ref,
        outcome_kind=outcome_kind,
        validated_proposal=_bool_or_none(outcome.get("validated_proposal")),
        adoption_succeeded=_bool_or_none(outcome.get("adoption_succeeded")),
        regression_free_apply=_bool_or_none(outcome.get("regression_free_apply")),
        human_intervention=_bool_or_none(outcome.get("human_intervention")),
        validation_autonomy=_bool_or_none(outcome.get("validation_autonomy")),
        duration_seconds=_float_or_none(outcome.get("duration_seconds")),
        summary=summary,
        warnings=list(warnings),
        errors=[],
    )


def _matching_session(
    event: CanaryExposureEvent,
    sessions: list[tuple[Path, dict[str, Any]]],
) -> tuple[Path, dict[str, Any]] | None:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path, payload in sessions:
        if not _same(_session_template_name(payload), event.template_name):
            continue
        if event.created_at and str(payload.get("created_at") or "") and str(payload.get("created_at")) < event.created_at:
            continue
        matches.append((path, payload))
    if not matches:
        return None
    return sorted(matches, key=lambda item: str(item[1].get("created_at") or item[0].name))[0]


def _session_payloads(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    sessions_dir = root / ".cambrian" / "sessions"
    if not sessions_dir.exists():
        return []
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(sessions_dir.glob("do_session_*.yaml")):
        payload = _load_yaml(path)
        if payload:
            payloads.append((path, payload))
    return payloads


def _benchmark_result_payloads(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    results_dir = root / ".cambrian" / "benchmarks" / "results"
    if not results_dir.exists():
        return []
    payloads: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(results_dir.glob("result_*.yaml")):
        payload = _load_yaml(path)
        if payload:
            payloads.append((path, payload))
    return payloads


def _matching_benchmark_result_ref(
    session_path: Path,
    benchmark_results: list[tuple[Path, dict[str, Any]]],
) -> str | None:
    session_id = str(_load_yaml(session_path).get("session_id") or "")
    for path, payload in benchmark_results:
        source_refs = payload.get("source_refs") if isinstance(payload.get("source_refs"), dict) else {}
        values = [str(value) for value in source_refs.values() if value is not None]
        if any(session_id and session_id in value for value in values) or any(session_path.name in value for value in values):
            return str(path)
    return None


def _session_template_name(payload: dict[str, Any]) -> str | None:
    metrics = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
    template_context = payload.get("template_context") if isinstance(payload.get("template_context"), dict) else {}
    for source in (metrics, template_context):
        for key in ("template_name", "current_template_name", "selected_template_name", "name"):
            if source.get(key):
                return str(source.get(key))
    return None


def _session_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
    results = metrics.get("results") if isinstance(metrics.get("results"), dict) else {}
    human = metrics.get("human_interventions") if isinstance(metrics.get("human_interventions"), dict) else {}
    validated = _bool_or_none(results.get("validated_proposal"))
    intervention = any(bool(value) for value in human.values()) if human else _bool_or_none(metrics.get("human_intervention"))
    validation_autonomy = metrics.get("validation_autonomy")
    if validation_autonomy is None:
        validation_autonomy = bool(validated and not intervention) if validated is not None else None
    return {
        "validated_proposal": validated,
        "adoption_succeeded": _bool_or_none(results.get("adoption_succeeded")),
        "regression_free_apply": _bool_or_none(results.get("apply_tests_passed")),
        "human_intervention": intervention,
        "validation_autonomy": _bool_or_none(validation_autonomy),
        "duration_seconds": _duration_from_metrics(metrics),
    }


def _replay_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    validated_rate = _float_or_none(summary.get("validated_proposal_rate"))
    human_rate = _float_or_none(summary.get("human_intervention_rate"))
    autonomy_rate = _float_or_none(summary.get("validation_autonomy_rate"))
    duration = _float_or_none(summary.get("median_duration_seconds"))
    if validated_rate is None and entries:
        validated_rate = _rate([_bool_or_none(item.get("validated_proposal")) for item in entries if isinstance(item, dict)])
    return {
        "validated_proposal": bool(validated_rate and validated_rate > 0),
        "adoption_succeeded": False,
        "regression_free_apply": None,
        "human_intervention": bool(human_rate and human_rate > 0) if human_rate is not None else None,
        "validation_autonomy": bool(autonomy_rate and autonomy_rate > 0) if autonomy_rate is not None else None,
        "duration_seconds": duration,
    }


def _request_ref(payload: dict[str, Any]) -> str | None:
    artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
    for key in ("request_path", "request_ref", "session_path"):
        if artifacts.get(key):
            return str(artifacts.get(key))
    return None


def _resolve_ref(root: Path, ref: str | None) -> Path:
    if not ref:
        return root / "__missing__"
    path = Path(ref)
    if path.exists():
        return path.resolve()
    if (root / path).exists():
        return (root / path).resolve()
    return root / ref


def _duration_from_metrics(metrics: dict[str, Any]) -> float | None:
    if metrics.get("duration_seconds") is not None:
        return _float_or_none(metrics.get("duration_seconds"))
    milestones = metrics.get("milestones") if isinstance(metrics.get("milestones"), dict) else {}
    start = _parse_datetime(milestones.get("request_started_at"))
    end = _parse_datetime(milestones.get("proposal_validated_at") or milestones.get("applied_at"))
    if start is None or end is None:
        return None
    return round(max(0.0, (end - start).total_seconds()), 3)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _summary_counts(links: list[CanaryOutcomeLink], ledger_counts: dict[str, int]) -> dict[str, int]:
    outcome_links = [link for link in links if link.outcome_kind in {"session_outcome", "replay_outcome"}]
    selected_links = [link for link in links if link.selection_source_kind in {"bootstrap_selection", "template_apply"}]
    selected_outcomes = [link for link in selected_links if link.outcome_kind == "session_outcome"]
    replay_outcomes = [link for link in links if link.selection_source_kind == "replay_override" and link.outcome_kind == "replay_outcome"]
    selected_count = max(int(ledger_counts.get("selected_count", 0) or 0), len(selected_links))
    return {
        "surfaced_count": int(ledger_counts.get("surfaced_count", 0) or 0),
        "selected_count": selected_count,
        "selected_with_outcome_count": len(selected_outcomes),
        "selected_then_validated_count": sum(1 for link in selected_outcomes if link.validated_proposal is True),
        "selected_then_adopted_count": sum(1 for link in selected_outcomes if link.adoption_succeeded is True),
        "selected_then_regression_free_apply_count": sum(
            1 for link in selected_outcomes if link.regression_free_apply is True
        ),
        "replay_count": max(int(ledger_counts.get("replay_count", 0) or 0), len(replay_outcomes)),
        "replay_validated_count": max(
            int(ledger_counts.get("replay_validated_count", 0) or 0),
            sum(1 for link in replay_outcomes if link.validated_proposal is True),
        ),
        "replay_blocked_count": int(ledger_counts.get("replay_blocked_count", 0) or 0),
        "outcome_link_count": len(outcome_links),
        "partial_link_count": sum(1 for link in links if link.outcome_kind == "partial"),
    }


def _summary_ratios(
    links: list[CanaryOutcomeLink],
    counts: dict[str, int],
    ledger_ratios: dict[str, float | None],
) -> dict[str, float | None]:
    selected_outcomes = [
        link
        for link in links
        if link.selection_source_kind in {"bootstrap_selection", "template_apply"} and link.outcome_kind == "session_outcome"
    ]
    return {
        "selection_rate": ledger_ratios.get("selection_rate"),
        "selected_outcome_coverage_rate": _ratio(counts["selected_with_outcome_count"], counts["selected_count"]),
        "selected_then_validated_rate": _ratio(
            counts["selected_then_validated_count"],
            counts["selected_with_outcome_count"],
        ),
        "selected_then_adopted_rate": _ratio(
            counts["selected_then_adopted_count"],
            counts["selected_with_outcome_count"],
        ),
        "selected_validation_autonomy_rate": _rate([link.validation_autonomy for link in selected_outcomes]),
        "selected_human_intervention_rate": _rate([link.human_intervention for link in selected_outcomes]),
    }


def _summary_medians(links: list[CanaryOutcomeLink]) -> dict[str, float | None]:
    selected = [
        link.duration_seconds
        for link in links
        if link.selection_source_kind in {"bootstrap_selection", "template_apply"}
        and link.outcome_kind == "session_outcome"
        and link.duration_seconds is not None
    ]
    replay = [
        link.duration_seconds
        for link in links
        if link.selection_source_kind == "replay_override"
        and link.outcome_kind == "replay_outcome"
        and link.duration_seconds is not None
    ]
    return {
        "selected_duration_seconds": _median(selected),
        "replay_duration_seconds": _median(replay),
    }


def _summary_lines(counts: dict[str, int], ratios: dict[str, float | None]) -> list[str]:
    lines: list[str] = []
    if counts["selected_with_outcome_count"]:
        lines.append("canary selections have linked downstream outcomes")
    elif counts["selected_count"]:
        lines.append("canary has selections, but outcome linkage is still incomplete")
    else:
        lines.append("canary has no explicit selected outcome evidence yet")
    if counts["selected_then_validated_count"]:
        lines.append("selected canary usage reached validated proposal")
    if counts["selected_then_adopted_count"]:
        lines.append("selected canary usage reached adoption")
    if ratios.get("selected_human_intervention_rate") == 0:
        lines.append("linked selected outcomes show no recorded human intervention")
    return lines[:5]


def _link_refs(link: CanaryOutcomeLink) -> list[str]:
    return [
        item
        for item in [
            link.selection_ref,
            link.linked_session_ref,
            link.linked_request_ref,
            link.linked_benchmark_result_ref,
            link.linked_replay_ref,
        ]
        if item
    ]


def _first_non_empty(values: list[str | None]) -> str | None:
    for value in values:
        if value:
            return value
    return None


def _same(left: str | None, right: str | None) -> bool:
    return _slug(left) == _slug(right)


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "pass", "passed"}:
        return True
    if text in {"false", "no", "0", "fail", "failed"}:
        return False
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _rate(values: list[bool | None]) -> float | None:
    known = [value for value in values if value is not None]
    if not known:
        return None
    return round(sum(1 for value in known if value) / len(known), 4)


def _median(values: list[float | None]) -> float | None:
    known = [float(value) for value in values if value is not None]
    if not known:
        return None
    return round(float(statistics.median(known)), 3)


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _link_from_dict(payload: dict[str, Any]) -> CanaryOutcomeLink:
    return CanaryOutcomeLink(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        link_id=str(payload.get("link_id") or f"canary-link-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        template_name=str(payload.get("template_name") or ""),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        canary_stage_id=str(payload.get("canary_stage_id")) if payload.get("canary_stage_id") is not None else None,
        selection_source_kind=str(payload.get("selection_source_kind") or "bootstrap_selection"),
        selection_ref=str(payload.get("selection_ref")) if payload.get("selection_ref") is not None else None,
        selected_at=str(payload.get("selected_at")) if payload.get("selected_at") is not None else None,
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_session_ref=str(payload.get("linked_session_ref")) if payload.get("linked_session_ref") is not None else None,
        linked_request_ref=str(payload.get("linked_request_ref")) if payload.get("linked_request_ref") is not None else None,
        linked_benchmark_result_ref=(
            str(payload.get("linked_benchmark_result_ref"))
            if payload.get("linked_benchmark_result_ref") is not None
            else None
        ),
        linked_replay_ref=str(payload.get("linked_replay_ref")) if payload.get("linked_replay_ref") is not None else None,
        outcome_kind=str(payload.get("outcome_kind") or "partial"),
        validated_proposal=_bool_or_none(payload.get("validated_proposal")),
        adoption_succeeded=_bool_or_none(payload.get("adoption_succeeded")),
        regression_free_apply=_bool_or_none(payload.get("regression_free_apply")),
        human_intervention=_bool_or_none(payload.get("human_intervention")),
        validation_autonomy=_bool_or_none(payload.get("validation_autonomy")),
        duration_seconds=_float_or_none(payload.get("duration_seconds")),
        summary=str(payload.get("summary") or ""),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _summary_from_dict(payload: dict[str, Any]) -> CanaryOutcomeSummary:
    return CanaryOutcomeSummary(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        report_id=str(payload.get("report_id") or f"canary-outcomes-{_short_id()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        template_name=str(payload.get("template_name") or ""),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        canary_stage_id=str(payload.get("canary_stage_id")) if payload.get("canary_stage_id") is not None else None,
        counts={str(key): int(value or 0) for key, value in dict(payload.get("counts", {})).items()},
        ratios={
            str(key): (float(value) if value is not None else None)
            for key, value in dict(payload.get("ratios", {})).items()
        },
        medians={
            str(key): (float(value) if value is not None else None)
            for key, value in dict(payload.get("medians", {})).items()
        },
        summary=[str(item) for item in payload.get("summary", []) if item],
        source_refs=[str(item) for item in payload.get("source_refs", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
