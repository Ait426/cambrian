"""Pack job retrospective와 pack 단위 feedback summary를 만든다."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_install import SCHEMA_VERSION, _as_list, _load_yaml, _now, _relative, _save_yaml, _slug, _stamp
from engine.project_pack_jobs import PackJob, PackJobStore, default_pack_job_path, resolve_pack_job_path

logger = logging.getLogger(__name__)


OUTCOME_KINDS = [
    "worked_well",
    "needs_improvement",
    "blocked_before_validation",
    "validated_but_not_adopted",
    "applied_but_rejected",
    "regression_or_safety_issue",
    "insufficient_data",
]


@dataclass
class PackJobRetrospectiveSignal:
    """Pack job에서 관찰한 pack-level signal."""

    signal_id: str
    kind: str
    status: str
    summary: str
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackImprovementSuggestion:
    """Retrospective가 제안하는 개선 후보."""

    suggestion_id: str
    kind: str
    priority: str
    confidence: float
    summary: str
    reason: str
    next_commands: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PackJobRetrospective:
    """완료 또는 실패한 pack job 회고 artifact."""

    schema_version: str
    retro_id: str
    generated_at: str
    job_id: str
    job_ref: str
    pack_ref: str
    pack_id: str
    pack_name: str | None
    namespace: str | None
    version: str | None
    request_class: str | None
    lane_id: str | None
    lane_label: str | None
    job_final_status: str | None
    validation_status: str | None
    apply_status: str | None
    adoption_status: str | None
    outcome_classification: list[str] = field(default_factory=list)
    human_feedback: dict[str, Any] = field(default_factory=dict)
    system_evidence: dict[str, Any] = field(default_factory=dict)
    signals: list[PackJobRetrospectiveSignal] = field(default_factory=list)
    suggestions: list[PackImprovementSuggestion] = field(default_factory=list)
    known_limits_observed: list[str] = field(default_factory=list)
    benchmark_case_candidates: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signals"] = [signal.to_dict() for signal in self.signals]
        payload["suggestions"] = [suggestion.to_dict() for suggestion in self.suggestions]
        return payload


@dataclass
class PackRetrospectiveSummary:
    """Pack 단위 retrospective aggregate."""

    schema_version: str
    summary_id: str
    generated_at: str
    pack_ref: str | None
    pack_id: str | None
    pack_name: str | None
    namespace: str | None
    version: str | None
    total_retrospectives: int
    outcome_counts: dict[str, int] = field(default_factory=dict)
    signal_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    top_positive_signals: list[str] = field(default_factory=list)
    top_negative_signals: list[str] = field(default_factory=list)
    top_suggestions: list[PackImprovementSuggestion] = field(default_factory=list)
    known_limits: list[str] = field(default_factory=list)
    benchmark_case_candidates: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_suggestions"] = [suggestion.to_dict() for suggestion in self.top_suggestions]
        return payload


class PackJobRetrospectiveBuilder:
    """Pack job artifact를 회고 artifact로 변환한다."""

    def build(self, project_root: Path, job_ref: str) -> PackJobRetrospective:
        root = Path(project_root).resolve()
        job_path = resolve_pack_job_path(root, job_ref)
        job = PackJobStore().load(job_path)
        job_file_ref = _relative(job_path, root)
        apply_record = _load_optional_ref(root, job.linked_apply_record_ref) or _find_record_by_job(root, "apply_records", "apply", job.job_id)
        adoption_record = _load_optional_ref(root, job.linked_adoption_record_ref) or _find_record_by_job(root, "adoptions", "adoption", job.job_id)
        human_feedback = _human_feedback(job, adoption_record)
        system_evidence = _system_evidence(job, apply_record, adoption_record)
        classifications = _classify_outcome(job, system_evidence, human_feedback)
        source_refs = _source_refs(job, job_file_ref, apply_record, adoption_record)
        signals = _signals_for_job(job, system_evidence, human_feedback, source_refs)
        suggestions = _suggestions_for_signals(job, signals, classifications, source_refs)
        known_limits = _known_limits(job, classifications, signals, human_feedback)
        benchmark_candidates = _benchmark_candidates(job, classifications, signals)
        warnings = _warnings(job, human_feedback, classifications)
        return PackJobRetrospective(
            schema_version=SCHEMA_VERSION,
            retro_id=f"retro-{_slug(job.job_id, 'job')}-{_stamp()}",
            generated_at=_now(),
            job_id=job.job_id,
            job_ref=job_file_ref,
            pack_ref=job.pack_ref,
            pack_id=job.pack_id,
            pack_name=job.pack_name,
            namespace=job.namespace,
            version=job.version,
            request_class=job.request_class,
            lane_id=job.lane_id,
            lane_label=job.lane_label,
            job_final_status=job.final_status or job.status,
            validation_status=job.validation_status,
            apply_status=job.apply_status,
            adoption_status=job.adoption_status,
            outcome_classification=classifications,
            human_feedback=human_feedback,
            system_evidence=system_evidence,
            signals=signals,
            suggestions=suggestions,
            known_limits_observed=known_limits,
            benchmark_case_candidates=benchmark_candidates,
            next_actions=_next_actions(job, suggestions),
            source_refs=source_refs,
            warnings=warnings,
            errors=[],
        )


class PackRetrospectiveSummaryBuilder:
    """저장된 retrospective를 pack 단위로 집계한다."""

    def build(self, project_root: Path, pack_ref: str | None = None) -> PackRetrospectiveSummary:
        root = Path(project_root).resolve()
        retros = PackRetrospectiveStore().list_job_retros(default_job_retrospectives_dir(root), pack_ref)
        first = retros[0] if retros else None
        outcome_counts = {kind: 0 for kind in OUTCOME_KINDS}
        signal_counts: dict[str, dict[str, int]] = {}
        suggestion_map: dict[str, dict[str, Any]] = {}
        known_limits: list[str] = []
        benchmark_candidates: list[str] = []
        for retro in retros:
            for kind in retro.outcome_classification:
                outcome_counts[kind] = outcome_counts.get(kind, 0) + 1
            known_limits.extend(retro.known_limits_observed)
            benchmark_candidates.extend(retro.benchmark_case_candidates)
            for signal in retro.signals:
                per_kind = signal_counts.setdefault(signal.kind, {})
                per_kind[signal.status] = per_kind.get(signal.status, 0) + 1
            for suggestion in retro.suggestions:
                slot = suggestion_map.setdefault(
                    suggestion.kind,
                    {
                        "count": 0,
                        "suggestion": suggestion,
                        "evidence_refs": [],
                    },
                )
                slot["count"] += 1
                slot["evidence_refs"].extend(suggestion.evidence_refs)

        top_positive = _top_signals(signal_counts, "positive")
        top_negative = _top_signals(signal_counts, "negative")
        top_suggestions = _top_suggestions(suggestion_map)
        summary_lines = _summary_lines(len(retros), outcome_counts, top_negative, top_suggestions)
        return PackRetrospectiveSummary(
            schema_version=SCHEMA_VERSION,
            summary_id=f"retro-summary-{_stamp()}-{_short_id(pack_ref or (first.pack_id if first else 'all'))}",
            generated_at=_now(),
            pack_ref=pack_ref or (first.pack_ref if first else None),
            pack_id=pack_ref or (first.pack_id if first else None),
            pack_name=first.pack_name if first else None,
            namespace=first.namespace if first else None,
            version=first.version if first else None,
            total_retrospectives=len(retros),
            outcome_counts=outcome_counts,
            signal_counts=signal_counts,
            top_positive_signals=top_positive,
            top_negative_signals=top_negative,
            top_suggestions=top_suggestions,
            known_limits=_dedupe(known_limits)[:10],
            benchmark_case_candidates=_dedupe(benchmark_candidates)[:10],
            summary=summary_lines,
            warnings=[] if retros else ["no pack job retrospectives found"],
            errors=[],
        )


class PackRetrospectiveStore:
    """Retrospective artifact 저장소."""

    def save_job_retro(self, retro: PackJobRetrospective, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), retro.to_dict())
        latest = default_retrospective_latest_path(_project_root_from_path(saved))
        try:
            _save_yaml(latest, retro.to_dict())
        except Exception as exc:  # noqa: BLE001 - latest pointer 실패는 회고 저장 실패가 아니다.
            logger.warning("pack retrospective latest save failed: %s", exc)
        return saved

    def load_job_retro(self, path: Path) -> PackJobRetrospective:
        return _retro_from_dict(_load_yaml(Path(path).resolve()))

    def list_job_retros(self, retros_dir: Path, pack_id: str | None = None) -> list[PackJobRetrospective]:
        target = Path(retros_dir).resolve()
        if not target.exists():
            return []
        retros: list[PackJobRetrospective] = []
        for path in sorted(target.glob("retro*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                retro = self.load_job_retro(path)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                logger.warning("pack retrospective load skipped: %s (%s)", path, exc)
                continue
            if pack_id and not _retro_matches(retro, pack_id):
                continue
            retros.append(retro)
        return retros

    def save_summary(self, summary: PackRetrospectiveSummary, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), summary.to_dict())
        latest = default_retrospective_summary_latest_path(_project_root_from_path(saved))
        try:
            _save_yaml(latest, summary.to_dict())
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack retrospective summary latest save failed: %s", exc)
        return saved

    def load_summary(self, path: Path) -> PackRetrospectiveSummary:
        return _summary_from_dict(_load_yaml(Path(path).resolve()))


def default_retrospectives_root(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "packs" / "retrospectives"


def default_job_retrospectives_dir(project_root: Path) -> Path:
    return default_retrospectives_root(project_root) / "jobs"


def default_retrospective_summaries_dir(project_root: Path) -> Path:
    return default_retrospectives_root(project_root) / "summaries"


def default_retrospective_latest_path(project_root: Path) -> Path:
    return default_retrospectives_root(project_root) / "latest.yaml"


def default_retrospective_summary_latest_path(project_root: Path) -> Path:
    return default_retrospective_summaries_dir(project_root) / "latest.yaml"


def default_job_retro_path(project_root: Path, retro: PackJobRetrospective) -> Path:
    return default_job_retrospectives_dir(project_root) / f"{retro.retro_id}.yaml"


def default_retro_summary_path(project_root: Path, summary: PackRetrospectiveSummary) -> Path:
    pack = _slug(summary.pack_id or summary.pack_ref or "all", "pack")
    return default_retrospective_summaries_dir(project_root) / f"summary_{pack}_{_stamp()}.yaml"


def save_pack_job_retrospective(project_root: Path, retro: PackJobRetrospective) -> str:
    path = PackRetrospectiveStore().save_job_retro(retro, default_job_retro_path(project_root, retro))
    return _relative(path, Path(project_root).resolve())


def save_pack_retro_summary(project_root: Path, summary: PackRetrospectiveSummary) -> str:
    path = PackRetrospectiveStore().save_summary(summary, default_retro_summary_path(project_root, summary))
    return _relative(path, Path(project_root).resolve())


def latest_pack_retro_summary(project_root: Path, pack_ref: str | None = None) -> PackRetrospectiveSummary | None:
    summaries = default_retrospective_summaries_dir(project_root)
    if not summaries.exists():
        return None
    store = PackRetrospectiveStore()
    for path in sorted(summaries.glob("summary_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            summary = store.load_summary(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack retrospective summary load skipped: %s", exc)
            continue
        if pack_ref is None or _summary_matches(summary, pack_ref):
            return summary
    latest = default_retrospective_summary_latest_path(project_root)
    if pack_ref is None and latest.exists():
        try:
            return store.load_summary(latest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("latest pack retrospective summary load failed: %s", exc)
    return None


def render_pack_job_retrospective(retro: PackJobRetrospective) -> str:
    lines = [
        "Pack Job Retrospective",
        "==================================================",
        "",
        "Job:",
        f"  {retro.job_id}",
        "",
        "Pack:",
        f"  {retro.pack_id}",
        "",
        "Outcome:",
        f"  {', '.join(retro.outcome_classification) or 'unknown'}",
    ]
    if retro.signals:
        lines.extend(["", "Signals:"])
        for signal in retro.signals:
            marker = "+" if signal.status == "positive" else "-" if signal.status == "negative" else "?"
            lines.append(f"  {marker} {signal.kind}: {signal.summary}")
    if retro.suggestions:
        lines.extend(["", "Suggestions:"])
        lines.extend([f"  - {item.kind}: {item.summary}" for item in retro.suggestions])
    if retro.known_limits_observed:
        lines.extend(["", "Known limits observed:"])
        lines.extend([f"  - {item}" for item in retro.known_limits_observed])
    if retro.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in retro.next_actions])
    if retro.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in retro.warnings])
    if retro.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in retro.errors])
    return "\n".join(lines)


def render_pack_retrospectives(retros: list[PackJobRetrospective], limit: int = 20) -> str:
    lines = [
        "Pack Retrospectives",
        "==================================================",
        "",
        "Recent:",
    ]
    if not retros:
        lines.append("  none")
        return "\n".join(lines)
    for idx, retro in enumerate(retros[:limit], 1):
        outcome = ", ".join(retro.outcome_classification) or "unknown"
        top_signal = _top_signal_label(retro)
        lines.append(f"  {idx}. {retro.retro_id} | {retro.pack_id} | {outcome} | {top_signal}")
    return "\n".join(lines)


def render_pack_retro_summary(summary: PackRetrospectiveSummary) -> str:
    lines = [
        "Pack Retrospective Summary",
        "==================================================",
        "",
        "Pack:",
        f"  {summary.pack_id or summary.pack_ref or 'all'}",
        "",
        "Retrospectives:",
        f"  {summary.total_retrospectives}",
        "",
        "Worked well:",
        f"  {summary.outcome_counts.get('worked_well', 0)}",
        "",
        "Needs improvement:",
        f"  {summary.outcome_counts.get('needs_improvement', 0)}",
    ]
    if summary.top_negative_signals:
        lines.extend(["", "Top negative signal:", f"  {summary.top_negative_signals[0]}"])
    if summary.top_suggestions:
        lines.extend(["", "Top suggestion:", f"  {summary.top_suggestions[0].kind}"])
    if summary.known_limits:
        lines.extend(["", "Known limits:"])
        lines.extend([f"  - {item}" for item in summary.known_limits[:5]])
    if summary.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in summary.summary])
    if summary.pack_id or summary.pack_ref:
        lines.extend(["", "Next:", f"  cambrian pack improve {summary.pack_id or summary.pack_ref}"])
    if summary.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in summary.warnings])
    return "\n".join(lines)


def render_pack_retro_summary_compact(summary: PackRetrospectiveSummary | None) -> str:
    if summary is None or summary.total_retrospectives <= 0:
        return ""
    lines = [
        "Retrospectives:",
        f"  {summary.total_retrospectives} total",
    ]
    if summary.top_negative_signals:
        lines.append(f"  top issue: {summary.top_negative_signals[0]}")
    elif summary.top_positive_signals:
        lines.append(f"  top signal: {summary.top_positive_signals[0]}")
    if summary.top_suggestions:
        lines.append(f"  top suggestion: {summary.top_suggestions[0].kind}")
    return "\n".join(lines)


def render_status_pack_retrospective(project_root: Path, latest_job: PackJob | None = None) -> str:
    if latest_job is None:
        return ""
    if latest_job.adoption_status in {"accepted", "rejected", "skipped"} and not _has_job_retro(project_root, latest_job.job_id):
        return "\n".join(["Pack retrospective:", "  recommended for latest job", f"  next: cambrian pack job-retro {latest_job.job_id}"])
    return ""


def _classify_outcome(job: PackJob, evidence: dict[str, Any], human: dict[str, Any]) -> list[str]:
    validated = _bool_or_none(evidence.get("validated_proposal"))
    applied = _bool_or_none(evidence.get("applied"))
    adopted = _bool_or_none(evidence.get("adoption_succeeded"))
    regression_free = _bool_or_none(evidence.get("regression_free_apply"))
    intervention = _bool_or_none(evidence.get("human_intervention"))
    adoption_status = str(human.get("adoption_decision") or job.adoption_status or "")
    classes: list[str] = []
    if regression_free is False:
        classes.append("regression_or_safety_issue")
    if applied is True and adoption_status == "rejected":
        classes.append("applied_but_rejected")
    if validated is True and adoption_status in {"rejected", "skipped", "undecided", ""}:
        classes.append("validated_but_not_adopted")
    if validated is False or job.validation_status in {"blocked", "failed", "not_ready"}:
        classes.append("blocked_before_validation")
    if validated is True and (intervention is True or job.warnings or job.errors):
        classes.append("needs_improvement")
    if validated is True and (adopted is True or applied is True) and regression_free is not False and intervention is not True:
        classes.append("worked_well")
    if not classes:
        classes.append("insufficient_data")
    return _dedupe(classes)


def _signals_for_job(job: PackJob, evidence: dict[str, Any], human: dict[str, Any], refs: dict[str, Any]) -> list[PackJobRetrospectiveSignal]:
    signal_refs = [str(value) for value in refs.values() if isinstance(value, str) and value]
    validated = _bool_or_none(evidence.get("validated_proposal"))
    applied = _bool_or_none(evidence.get("applied"))
    adopted = _bool_or_none(evidence.get("adoption_succeeded"))
    regression_free = _bool_or_none(evidence.get("regression_free_apply"))
    intervention = _bool_or_none(evidence.get("human_intervention"))
    lane_positive = _lane_matches(job)
    return [
        _signal("context_fit", "positive" if job.readiness_status in {"ready", "partial"} else "negative" if job.readiness_status in {"blocked", "unsupported"} else "unknown", _context_summary(job), signal_refs),
        _signal("team_fit", "positive" if job.active_team else "unknown", "expected team context was present" if job.active_team else "team context was not recorded", signal_refs),
        _signal("template_fit", "positive" if job.active_template else "unknown", "expected template context was present" if job.active_template else "template context was not recorded", signal_refs),
        _signal("bridge_quality", "positive" if job.reply_kind == "patch_candidate" and job.linked_patch_intent_ref else "negative" if job.reply_kind and job.status == "blocked" else "unknown", _bridge_summary(job), signal_refs),
        _signal("validation_quality", "positive" if validated is True else "negative" if validated is False or job.validation_status in {"blocked", "failed"} else "unknown", _validation_summary(job, validated), signal_refs),
        _signal("intervention_cost", "positive" if intervention is False else "negative" if intervention is True else "unknown", "human intervention was not recorded" if intervention is False else "human intervention was recorded" if intervention is True else "intervention evidence is missing", signal_refs),
        _signal("adoption_quality", "positive" if adopted is True else "negative" if adopted is False else "unknown", _adoption_summary(human, adopted), signal_refs),
        _signal("lane_fit", "positive" if lane_positive else "negative" if _outside_lane(job) else "unknown", _lane_summary(job), signal_refs),
        _signal("safety_risk", "negative" if regression_free is False or _reason_mentions_risk(human) else "neutral", "regression or safety risk was observed" if regression_free is False else "no explicit safety issue recorded", signal_refs),
        _signal("benchmark_value", "positive" if validated is True and (adopted is True or applied is True) else "neutral", "job may become a reusable benchmark case" if validated is True else "benchmark value is not established", signal_refs),
    ]


def _suggestions_for_signals(job: PackJob, signals: list[PackJobRetrospectiveSignal], classifications: list[str], refs: dict[str, Any]) -> list[PackImprovementSuggestion]:
    suggestions: list[PackImprovementSuggestion] = []
    evidence_refs = [str(value) for value in refs.values() if isinstance(value, str) and value]
    for signal in signals:
        if signal.status != "negative":
            continue
        if signal.kind == "context_fit":
            suggestions.append(_suggestion(job, "strengthen_context_hints", "high", 0.7, "context hint를 보강해야 합니다.", "negative context_fit signal", evidence_refs, [f"cambrian template evolve {job.active_template or '<template>'}", "cambrian benchmark case-add ..."]))
            suggestions.append(_suggestion(job, "add_benchmark_case", "medium", 0.6, "비슷한 실패를 benchmark case로 남길 수 있습니다.", "context failure can become replay evidence", evidence_refs, ["cambrian benchmark case-add ..."]))
        elif signal.kind == "bridge_quality":
            suggestions.append(_suggestion(job, "improve_response_contract", "high", 0.7, "AI reply contract를 더 엄격히 해야 합니다.", "bridge parsing or handoff was weak", evidence_refs, ["cambrian bridge prepare ..."]))
        elif signal.kind == "validation_quality":
            suggestions.append(_suggestion(job, "improve_validation_support", "high", 0.75, "validation 지원과 test hint를 강화해야 합니다.", "validation did not reach a clean proposal", evidence_refs, [f"cambrian template evolve {job.active_template or '<template>'}", f"cambrian benchmark bottlenecks {job.active_workset or '<workset>'}"]))
        elif signal.kind == "adoption_quality":
            suggestions.append(_suggestion(job, "update_known_limits", "medium", 0.65, "거절/스킵 이유를 known limits에 반영할 후보입니다.", "adoption quality was negative", evidence_refs, [f"cambrian pack proof {job.pack_id}"]))
            suggestions.append(_suggestion(job, "review_template_fit", "medium", 0.55, "template fit을 재검토해야 합니다.", "validated output was not adopted", evidence_refs, [f"cambrian template evolve {job.active_template or '<template>'}"]))
        elif signal.kind == "team_fit":
            suggestions.append(_suggestion(job, "review_team_fit", "medium", 0.55, "team fit을 재검토해야 합니다.", "team signal was negative", evidence_refs, ["cambrian team recommend"]))
        elif signal.kind == "template_fit":
            suggestions.append(_suggestion(job, "review_template_fit", "medium", 0.6, "template default를 재검토해야 합니다.", "template signal was negative", evidence_refs, [f"cambrian template evolve {job.active_template or '<template>'}"]))
            suggestions.append(_suggestion(job, "create_pack_derivative", "low", 0.45, "현재 lane 밖이면 derivative pack 후보입니다.", "template mismatch can indicate derivative value", evidence_refs, ["cambrian pack draft ..."]))
    if "worked_well" in classifications:
        suggestions.append(_suggestion(job, "add_benchmark_case", "low", 0.55, "성공한 작업을 replay 가능한 benchmark로 남길 수 있습니다.", "successful job is reusable evidence", evidence_refs, ["cambrian benchmark case-add ..."]))
    return _dedupe_suggestions(suggestions)


def _human_feedback(job: PackJob, adoption_record: dict[str, Any] | None) -> dict[str, Any]:
    decision = str((adoption_record or {}).get("decision") or job.adoption_status or "undecided")
    reason = (
        str((adoption_record or {}).get("reason") or "").strip()
        or str((job.final_outcome_snapshot or {}).get("adoption_reason") or "").strip()
        or str((job.final_outcome_snapshot or {}).get("rejection_reason") or "").strip()
        or None
    )
    feedback: dict[str, Any] = {
        "adoption_decision": decision,
        "adoption_reason": reason if decision == "accepted" else None,
        "rejection_reason": reason if decision == "rejected" else None,
        "skipped_reason": reason if decision == "skipped" else None,
    }
    return feedback


def _system_evidence(job: PackJob, apply_record: dict[str, Any] | None, adoption_record: dict[str, Any] | None) -> dict[str, Any]:
    final = dict(job.final_outcome_snapshot or {})
    outcome = dict(job.outcome_snapshot or {})
    validated = _coalesce_bool(final.get("validated_proposal"), outcome.get("validated_proposal"), job.validation_status == "validated")
    applied = _coalesce_bool(final.get("applied"), (apply_record or {}).get("status") == "applied", job.apply_status == "applied")
    adopted = _coalesce_bool(final.get("adoption_succeeded"), (adoption_record or {}).get("adoption_succeeded"))
    regression_free = _coalesce_bool(final.get("regression_free_apply"), (apply_record or {}).get("regression_free_apply"), (adoption_record or {}).get("regression_free_apply"))
    return {
        "validated_proposal": validated,
        "applied": applied,
        "adoption_succeeded": adopted,
        "regression_free_apply": regression_free,
        "human_intervention": _coalesce_bool(final.get("human_intervention"), outcome.get("human_intervention")),
        "validation_autonomy": _coalesce_bool(final.get("validation_autonomy"), outcome.get("validation_autonomy")),
        "duration_seconds": final.get("duration_seconds", outcome.get("duration_seconds")),
    }


def _source_refs(job: PackJob, job_ref: str, apply_record: dict[str, Any] | None, adoption_record: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "job_ref": job_ref,
        "apply_record_ref": job.linked_apply_record_ref,
        "adoption_record_ref": job.linked_adoption_record_ref,
        "usage_event_ref": job.usage_event_ref,
        "proposal_ref": job.linked_proposal_ref,
        "session_ref": job.linked_session_ref or job.linked_session_id,
        "apply_status": (apply_record or {}).get("status"),
        "adoption_decision": (adoption_record or {}).get("decision"),
    }


def _known_limits(job: PackJob, classifications: list[str], signals: list[PackJobRetrospectiveSignal], human: dict[str, Any]) -> list[str]:
    limits: list[str] = []
    if "validated_but_not_adopted" in classifications:
        limits.append("validated proposal did not become an accepted outcome")
    if "regression_or_safety_issue" in classifications:
        limits.append("apply/regression evidence was negative")
    for signal in signals:
        if signal.status == "negative":
            limits.append(f"{signal.kind}: {signal.summary}")
    reason = human.get("rejection_reason") or human.get("skipped_reason")
    if reason:
        limits.append(f"human feedback: {reason}")
    return _dedupe(limits)


def _benchmark_candidates(job: PackJob, classifications: list[str], signals: list[PackJobRetrospectiveSignal]) -> list[str]:
    if "worked_well" in classifications or any(signal.kind == "benchmark_value" and signal.status == "positive" for signal in signals):
        lane = job.lane_label or job.lane_id or "pack lane"
        return [f"{job.pack_id}: reusable {lane} job pattern"]
    return []


def _warnings(job: PackJob, human: dict[str, Any], classifications: list[str]) -> list[str]:
    warnings = list(job.warnings)
    if human.get("adoption_decision") in {"accepted", "rejected"} and not (human.get("adoption_reason") or human.get("rejection_reason")):
        warnings.append("no human adoption reason provided")
    if "insufficient_data" in classifications:
        warnings.append("job is not complete enough for strong retrospective claims")
    return _dedupe(warnings)


def _next_actions(job: PackJob, suggestions: list[PackImprovementSuggestion]) -> list[str]:
    actions = [f"cambrian pack proof {job.pack_id}", f"cambrian pack retro-summary {job.pack_id}"]
    for suggestion in suggestions[:2]:
        actions.extend(suggestion.next_commands[:2])
    return _dedupe(actions)


def _signal(kind: str, status: str, summary: str, evidence_refs: list[str]) -> PackJobRetrospectiveSignal:
    return PackJobRetrospectiveSignal(
        signal_id=f"signal-{kind}",
        kind=kind,
        status=status,
        summary=summary,
        evidence_refs=_dedupe(evidence_refs),
        warnings=[],
    )


def _suggestion(
    job: PackJob,
    kind: str,
    priority: str,
    confidence: float,
    summary: str,
    reason: str,
    evidence_refs: list[str],
    next_commands: list[str],
) -> PackImprovementSuggestion:
    return PackImprovementSuggestion(
        suggestion_id=f"suggestion-{kind}-{_short_id(job.job_id)}",
        kind=kind,
        priority=priority,
        confidence=confidence,
        summary=summary,
        reason=reason,
        next_commands=[item for item in next_commands if item],
        evidence_refs=_dedupe(evidence_refs),
        warnings=[],
    )


def _context_summary(job: PackJob) -> str:
    if job.readiness_status in {"ready", "partial"}:
        return f"readiness was {job.readiness_status}"
    if job.readiness_status:
        return f"readiness was {job.readiness_status}"
    return "readiness evidence is missing"


def _bridge_summary(job: PackJob) -> str:
    if job.reply_kind == "patch_candidate" and job.linked_patch_intent_ref:
        return "patch candidate was routed into patch intent without retyping"
    if job.reply_kind:
        return f"reply kind was {job.reply_kind}"
    return "bridge reply evidence is missing"


def _validation_summary(job: PackJob, validated: bool | None) -> str:
    if validated is True:
        return "proposal validated cleanly"
    if validated is False:
        return "proposal did not validate"
    return f"validation status is {job.validation_status or 'unknown'}"


def _adoption_summary(human: dict[str, Any], adopted: bool | None) -> str:
    if adopted is True:
        return "result was explicitly accepted"
    if adopted is False:
        return f"result was {human.get('adoption_decision') or 'not accepted'}"
    return "adoption decision is missing"


def _lane_summary(job: PackJob) -> str:
    if _lane_matches(job):
        return f"request stayed inside {job.lane_label or job.lane_id or 'recorded lane'}"
    if _outside_lane(job):
        return "job appears outside the pack strongest lane"
    return "lane fit evidence is missing"


def _lane_matches(job: PackJob) -> bool:
    text = " ".join([job.lane_id or "", job.lane_label or "", job.request_class or ""]).lower()
    return any(token in text for token in ["auth", "login", "pytest", "python"])


def _outside_lane(job: PackJob) -> bool:
    text = " ".join([job.request_class or "", job.lane_label or "", *job.warnings]).lower()
    return any(token in text for token in ["outside", "unsupported", "broad refactor", "docs"])


def _reason_mentions_risk(human: dict[str, Any]) -> bool:
    reason = " ".join(str(value or "") for value in human.values()).lower()
    return any(token in reason for token in ["risk", "unsafe", "broad", "regression", "danger"])


def _top_signals(signal_counts: dict[str, dict[str, int]], status: str) -> list[str]:
    scored = [(kind, counts.get(status, 0)) for kind, counts in signal_counts.items()]
    scored = [(kind, count) for kind, count in scored if count > 0]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return [kind for kind, _ in scored[:5]]


def _top_suggestions(suggestion_map: dict[str, dict[str, Any]]) -> list[PackImprovementSuggestion]:
    ranked: list[tuple[int, PackImprovementSuggestion]] = []
    for payload in suggestion_map.values():
        suggestion = payload["suggestion"]
        count = int(payload["count"])
        priority = "high" if count >= 3 or suggestion.priority == "high" else "medium" if count >= 2 else suggestion.priority
        confidence = min(0.9, float(suggestion.confidence) + (0.1 * max(0, count - 1)))
        ranked.append((
            count,
            PackImprovementSuggestion(
                suggestion.suggestion_id,
                suggestion.kind,
                priority,
                confidence,
                suggestion.summary,
                f"{suggestion.reason}; observed {count} time(s)",
                _dedupe(suggestion.next_commands),
                _dedupe(payload["evidence_refs"]),
                list(suggestion.warnings),
            ),
        ))
    ranked.sort(key=lambda item: (-item[0], item[1].kind))
    return [item for _, item in ranked[:5]]


def _summary_lines(total: int, outcome_counts: dict[str, int], top_negative: list[str], top_suggestions: list[PackImprovementSuggestion]) -> list[str]:
    lines = [f"total_retrospectives={total}", f"worked_well={outcome_counts.get('worked_well', 0)}", f"needs_improvement={outcome_counts.get('needs_improvement', 0)}"]
    if top_negative:
        lines.append(f"top_negative_signal={top_negative[0]}")
    if top_suggestions:
        lines.append(f"top_suggestion={top_suggestions[0].kind}")
    return lines


def _top_signal_label(retro: PackJobRetrospective) -> str:
    for status in ["negative", "positive"]:
        for signal in retro.signals:
            if signal.status == status:
                return f"{signal.kind}:{signal.status}"
    return "no signal"


def _dedupe_suggestions(suggestions: list[PackImprovementSuggestion]) -> list[PackImprovementSuggestion]:
    seen: set[str] = set()
    result: list[PackImprovementSuggestion] = []
    for suggestion in suggestions:
        if suggestion.kind in seen:
            continue
        seen.add(suggestion.kind)
        result.append(suggestion)
    return result


def _find_record_by_job(root: Path, subdir: str, prefix: str, job_id: str) -> dict[str, Any] | None:
    records_dir = root / ".cambrian" / "packs" / "jobs" / subdir
    if not records_dir.exists():
        return None
    for path in sorted(records_dir.glob(f"{prefix}*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _load_any(path)
        if str(payload.get("job_id") or "") == job_id:
            return payload
    return None


def _load_optional_ref(root: Path, ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    path = Path(str(ref))
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        return None
    return _load_any(path)


def _load_any(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("pack retrospective source load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _retro_from_dict(payload: dict[str, Any]) -> PackJobRetrospective:
    return PackJobRetrospective(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        retro_id=str(payload.get("retro_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        job_id=str(payload.get("job_id") or ""),
        job_ref=str(payload.get("job_ref") or ""),
        pack_ref=str(payload.get("pack_ref") or ""),
        pack_id=str(payload.get("pack_id") or ""),
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        request_class=str(payload.get("request_class")) if payload.get("request_class") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        job_final_status=str(payload.get("job_final_status")) if payload.get("job_final_status") is not None else None,
        validation_status=str(payload.get("validation_status")) if payload.get("validation_status") is not None else None,
        apply_status=str(payload.get("apply_status")) if payload.get("apply_status") is not None else None,
        adoption_status=str(payload.get("adoption_status")) if payload.get("adoption_status") is not None else None,
        outcome_classification=_as_list(payload.get("outcome_classification")),
        human_feedback=dict(payload.get("human_feedback", {})) if isinstance(payload.get("human_feedback"), dict) else {},
        system_evidence=dict(payload.get("system_evidence", {})) if isinstance(payload.get("system_evidence"), dict) else {},
        signals=[_signal_from_dict(item) for item in payload.get("signals", []) if isinstance(item, dict)],
        suggestions=[_suggestion_from_dict(item) for item in payload.get("suggestions", []) if isinstance(item, dict)],
        known_limits_observed=_as_list(payload.get("known_limits_observed")),
        benchmark_case_candidates=_as_list(payload.get("benchmark_case_candidates")),
        next_actions=_as_list(payload.get("next_actions")),
        source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _summary_from_dict(payload: dict[str, Any]) -> PackRetrospectiveSummary:
    return PackRetrospectiveSummary(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        summary_id=str(payload.get("summary_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        pack_ref=str(payload.get("pack_ref")) if payload.get("pack_ref") is not None else None,
        pack_id=str(payload.get("pack_id")) if payload.get("pack_id") is not None else None,
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        total_retrospectives=int(payload.get("total_retrospectives") or 0),
        outcome_counts={str(k): int(v or 0) for k, v in (payload.get("outcome_counts") or {}).items()},
        signal_counts={str(k): {str(sk): int(sv or 0) for sk, sv in dict(v).items()} for k, v in (payload.get("signal_counts") or {}).items() if isinstance(v, dict)},
        top_positive_signals=_as_list(payload.get("top_positive_signals")),
        top_negative_signals=_as_list(payload.get("top_negative_signals")),
        top_suggestions=[_suggestion_from_dict(item) for item in payload.get("top_suggestions", []) if isinstance(item, dict)],
        known_limits=_as_list(payload.get("known_limits")),
        benchmark_case_candidates=_as_list(payload.get("benchmark_case_candidates")),
        summary=_as_list(payload.get("summary")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _signal_from_dict(payload: dict[str, Any]) -> PackJobRetrospectiveSignal:
    return PackJobRetrospectiveSignal(
        signal_id=str(payload.get("signal_id") or ""),
        kind=str(payload.get("kind") or ""),
        status=str(payload.get("status") or "unknown"),
        summary=str(payload.get("summary") or ""),
        evidence_refs=_as_list(payload.get("evidence_refs")),
        warnings=_as_list(payload.get("warnings")),
    )


def _suggestion_from_dict(payload: dict[str, Any]) -> PackImprovementSuggestion:
    return PackImprovementSuggestion(
        suggestion_id=str(payload.get("suggestion_id") or ""),
        kind=str(payload.get("kind") or ""),
        priority=str(payload.get("priority") or "low"),
        confidence=float(payload.get("confidence") or 0.0),
        summary=str(payload.get("summary") or ""),
        reason=str(payload.get("reason") or ""),
        next_commands=_as_list(payload.get("next_commands")),
        evidence_refs=_as_list(payload.get("evidence_refs")),
        warnings=_as_list(payload.get("warnings")),
    )


def _retro_matches(retro: PackJobRetrospective, ref: str) -> bool:
    raw = str(ref or "").strip()
    return raw in {retro.pack_id, retro.pack_ref, f"{retro.namespace}/{retro.pack_id}" if retro.namespace else retro.pack_id, f"{retro.pack_id}@{retro.version}" if retro.version else retro.pack_id}


def _summary_matches(summary: PackRetrospectiveSummary, ref: str) -> bool:
    raw = str(ref or "").strip()
    return raw in {summary.pack_id or "", summary.pack_ref or "", f"{summary.namespace}/{summary.pack_id}" if summary.namespace and summary.pack_id else "", f"{summary.pack_id}@{summary.version}" if summary.pack_id and summary.version else ""}


def _has_job_retro(project_root: Path, job_id: str) -> bool:
    for retro in PackRetrospectiveStore().list_job_retros(default_job_retrospectives_dir(project_root)):
        if retro.job_id == job_id:
            return True
    return False


def _coalesce_bool(*values: Any) -> bool | None:
    for value in values:
        parsed = _bool_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


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


def _short_id(value: str | None) -> str:
    import hashlib

    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:8]


def _project_root_from_path(path: Path) -> Path:
    parts = list(Path(path).resolve().parts)
    if ".cambrian" in parts:
        return Path(*parts[: parts.index(".cambrian")])
    return Path.cwd().resolve()
