"""canary template burn-in evidence와 promotion gate 모듈."""

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

from engine.project_template_canary import (
    TemplateCanaryStage,
    active_canary_stage,
    load_template_canary_summary,
    unstage_qualification_canary,
)
from engine.project_template_canary_ledger import CanaryLedgerBuilder, CanaryLedgerBlockedError
from engine.project_template_canary_outcomes import CanaryOutcomeBlockedError, CanaryOutcomeSummaryBuilder
from engine.project_template_history import (
    TemplateHistoryBuilder,
    TemplateRetrospectiveStore,
    default_template_retrospectives_dir,
)
from engine.project_template_qualification import (
    TemplateQualificationReport,
    TemplateQualificationStore,
    resolve_template_qualification_path,
)
from engine.project_template_qualification_decisions import (
    LanePlaybookStore,
    accept_qualification,
    lane_playbook_path,
)
from engine.project_templates import HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
RATE_THRESHOLD = 0.05
DURATION_THRESHOLD_SECONDS = 30.0
SOFT_PROMOTION_VERDICTS = {"keep_canary", "insufficient_data"}


class CanaryReportBlockedError(RuntimeError):
    """canary report 생성 조건이 맞지 않을 때 발생한다."""


class CanaryPromotionBlockedError(RuntimeError):
    """canary promotion gate에서 승격을 막을 때 발생한다."""

    def __init__(self, verdict: str | None, message: str, next_action: str | None = None) -> None:
        super().__init__(message)
        self.verdict = verdict
        self.next_action = next_action


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명용 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 식별자를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str | None, fallback: str = "item") -> str:
    """값을 파일/키에 안전한 slug로 바꾼다."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _atomic_write_text(path: Path, content: str) -> None:
    """파일을 원자적으로 저장한다."""
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
    """YAML payload를 저장한다."""
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML artifact를 안전하게 읽는다."""
    if not Path(path).exists():
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("template canary report artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """프로젝트 root 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복 문자열을 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _rate(values: list[Any]) -> float | None:
    """bool-like 값 목록을 rate로 계산한다."""
    known = [value for value in values if value is not None]
    if not known:
        return None
    return round(sum(1 for value in known if bool(value)) / len(known), 4)


def _median(values: list[Any]) -> float | None:
    """숫자 목록의 median을 계산한다."""
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


def default_canary_reports_dir(project_root: Path) -> Path:
    """canary report 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "canary_reports"


def default_canary_report_path(project_root: Path, report: "TemplateCanaryReport") -> Path:
    """canary report 기본 저장 경로."""
    return default_canary_reports_dir(project_root) / (
        f"canary_{_slug(report.candidate_template_name)}_{_stamp()}_{_short_id()}.yaml"
    )


def latest_canary_report_path(project_root: Path) -> Path:
    """latest canary report pointer 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "latest_canary.yaml"


@dataclass
class TemplateCanarySignal:
    """canary verdict에 쓰인 evidence signal."""

    signal_id: str
    kind: str
    summary: str
    value: float | int | str | None
    evidence_ref: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateCanaryMetrics:
    """canary/stable 비교 지표."""

    validated_proposal_rate: float | None
    human_intervention_rate: float | None
    validation_autonomy_rate: float | None
    median_duration_seconds: float | None
    team_template_recommendation_hit_rate: float | None
    reuse_lift: float | None
    repeat_task_improvement_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateCanaryReport:
    """canary burn-in evidence report."""

    schema_version: str
    report_id: str
    generated_at: str
    lane_id: str | None
    lane_label: str | None
    candidate_template_name: str
    candidate_template_id: str | None
    stable_default_template_name: str | None
    stable_default_template_id: str | None
    stage_ref: str | None
    qualification_ref: str | None
    candidate_metrics: TemplateCanaryMetrics
    stable_metrics: TemplateCanaryMetrics | None
    exposure_counts: dict[str, int]
    signals: list[TemplateCanarySignal]
    verdict: str
    summary: list[str] = field(default_factory=list)
    why_promote: list[str] = field(default_factory=list)
    why_wait: list[str] = field(default_factory=list)
    why_clear: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "lane_id": self.lane_id,
            "lane_label": self.lane_label,
            "candidate_template_name": self.candidate_template_name,
            "candidate_template_id": self.candidate_template_id,
            "stable_default_template_name": self.stable_default_template_name,
            "stable_default_template_id": self.stable_default_template_id,
            "stage_ref": self.stage_ref,
            "qualification_ref": self.qualification_ref,
            "candidate_metrics": self.candidate_metrics.to_dict(),
            "stable_metrics": self.stable_metrics.to_dict() if self.stable_metrics else None,
            "exposure_counts": dict(self.exposure_counts),
            "signals": [signal.to_dict() for signal in self.signals],
            "verdict": self.verdict,
            "summary": list(self.summary),
            "why_promote": list(self.why_promote),
            "why_wait": list(self.why_wait),
            "why_clear": list(self.why_clear),
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateCanaryReportStore:
    """canary report 저장소."""

    def save(self, report: TemplateCanaryReport, path: Path) -> Path:
        """report를 저장하고 latest pointer를 갱신한다."""
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent.parent / "latest_canary.yaml", report.to_dict())
        return saved

    def load(self, path: Path) -> TemplateCanaryReport:
        """report를 로드한다."""
        return _report_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, reports_dir: Path) -> list[TemplateCanaryReport]:
        """저장된 report를 최신순으로 반환한다."""
        target = Path(reports_dir).resolve()
        if not target.exists():
            return []
        reports = [self.load(path) for path in target.glob("canary_*.yaml")]
        return sorted(reports, key=lambda report: report.generated_at, reverse=True)


class TemplateCanaryReportBuilder:
    """active canary의 burn-in evidence report를 만든다."""

    def build(
        self,
        project_root: Path,
        template_name: str | None = None,
        workset_name: str | None = None,
    ) -> TemplateCanaryReport:
        """candidate와 stable default evidence를 모아 verdict를 낸다."""
        root = Path(project_root).resolve()
        stage = active_canary_stage(root)
        if stage is None and not template_name:
            raise CanaryReportBlockedError(
                "No active canary template found. Run: cambrian template qualify-stage <qualification>"
            )
        if stage is not None and template_name and _slug(stage.candidate_template_name) != _slug(template_name):
            raise CanaryReportBlockedError(
                f"Active canary is {stage.candidate_template_name}, not {template_name}"
            )
        candidate_name = str(template_name or (stage.candidate_template_name if stage else "")).strip()
        if not candidate_name:
            raise CanaryReportBlockedError("Canary template name is required.")
        playbook = LanePlaybookStore().load(lane_playbook_path(root))
        template_model = HarnessTemplateStore().load(default_templates_path(root))
        candidate = HarnessTemplateStore().find(template_model, candidate_name)
        stable = _find_template_or_none(template_model, playbook.default_template_name)
        warnings: list[str] = []
        signals: list[TemplateCanarySignal] = []

        qualification_report = _load_qualification_for_stage(root, stage)
        if qualification_report is not None:
            signals.append(_signal(
                "qualification",
                f"qualification verdict is {qualification_report.verdict}",
                qualification_report.verdict,
                stage.qualification_ref if stage else None,
            ))
            if workset_name and qualification_report.workset_name != workset_name:
                warnings.append(
                    f"latest canary qualification workset differs from requested workset: {qualification_report.workset_name}"
                )
        else:
            warnings.append("qualification report is missing for the active canary")

        candidate_metrics, stable_metrics = _metrics_from_evidence(
            root,
            candidate.name,
            stable.name if stable else None,
            qualification_report,
        )
        outcome_counts = _outcome_exposure_counts(root, candidate.name, signals, warnings)
        exposure_counts = _ledger_exposure_counts(root, candidate.name, signals, warnings)
        if not exposure_counts:
            exposure_counts = _exposure_counts(root, candidate.name, signals)
        if outcome_counts:
            exposure_counts.update(outcome_counts)
        retrospective_counts = _retrospective_signals(root, candidate.name, signals)
        history_counts = _history_signals(root, candidate.name, signals)
        if stable is None:
            warnings.append("stable default template is unknown, so stable metrics are unavailable")
        verdict, why_promote, why_wait, why_clear, summary = _verdict(
            qualification_report=qualification_report,
            candidate_metrics=candidate_metrics,
            stable_metrics=stable_metrics,
            exposure_counts=exposure_counts,
            retrospective_counts=retrospective_counts,
            history_counts=history_counts,
        )
        return TemplateCanaryReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"template-canary-report-{_slug(candidate.name)}-{_short_id()}",
            generated_at=_now(),
            lane_id=playbook.lane_id,
            lane_label=playbook.label,
            candidate_template_name=candidate.name,
            candidate_template_id=candidate.template_id,
            stable_default_template_name=stable.name if stable else playbook.default_template_name,
            stable_default_template_id=stable.template_id if stable else None,
            stage_ref=stage.stage_id if stage else None,
            qualification_ref=stage.qualification_ref if stage else None,
            candidate_metrics=candidate_metrics,
            stable_metrics=stable_metrics,
            exposure_counts=exposure_counts,
            signals=signals,
            verdict=verdict,
            summary=summary,
            why_promote=why_promote,
            why_wait=why_wait,
            why_clear=why_clear,
            next_actions=_next_actions(candidate.name, stage, verdict),
            warnings=_dedupe(warnings),
            errors=[],
        )


def resolve_canary_report_path(project_root: Path, report_ref: str) -> Path:
    """canary report id 또는 path를 실제 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(report_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in default_canary_reports_dir(root).glob("canary_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == report_ref or str(payload.get("report_id") or "") == report_ref:
            return path.resolve()
    raise FileNotFoundError(f"canary report not found: {report_ref}")


def load_latest_canary_report(project_root: Path, template_name: str | None = None) -> TemplateCanaryReport | None:
    """latest canary report를 반환한다."""
    root = Path(project_root).resolve()
    reports = TemplateCanaryReportStore().list(default_canary_reports_dir(root))
    if template_name:
        wanted = _slug(template_name)
        reports = [report for report in reports if _slug(report.candidate_template_name) == wanted]
    return reports[0] if reports else None


def load_latest_canary_report_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """status/show/lineage/recommend에서 쓰는 latest canary report 요약."""
    report = load_latest_canary_report(project_root, template_name=template_name)
    if report is None:
        return {}
    return {
        "report_id": report.report_id,
        "candidate_template_name": report.candidate_template_name,
        "stable_default_template_name": report.stable_default_template_name,
        "verdict": report.verdict,
        "summary": list(report.summary[:3]),
        "why_promote": list(report.why_promote[:3]),
        "why_wait": list(report.why_wait[:3]),
        "why_clear": list(report.why_clear[:3]),
    }


def promote_canary_template(
    project_root: Path,
    template_name: str,
    *,
    previous_default_action: str = "keep_as_backup",
    resolution: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """promotion gate를 통과한 canary를 future-facing lane default로 승격한다."""
    root = Path(project_root).resolve()
    stage = active_canary_stage(root)
    if stage is None:
        raise CanaryPromotionBlockedError(None, "No active canary template is staged.")
    if _slug(stage.candidate_template_name) != _slug(template_name):
        raise CanaryPromotionBlockedError(
            None,
            f"Active canary is {stage.candidate_template_name}, not {template_name}.",
        )
    report = load_latest_canary_report(root, template_name=stage.candidate_template_name)
    if report is None:
        raise CanaryPromotionBlockedError(
            None,
            "No canary report exists yet.",
            f"cambrian template canary-report {stage.candidate_template_name} --save",
        )
    if report.verdict == "clear_canary":
        raise CanaryPromotionBlockedError(
            report.verdict,
            "This canary should be cleared, not promoted.",
            f"cambrian template qualify-unstage {stage.qualification_ref}",
        )
    from engine.project_template_canary_review import TemplateCanaryReviewBuilder

    review = TemplateCanaryReviewBuilder().build(root, template_name=stage.candidate_template_name)
    warnings: list[str] = []
    if review.freshness_status in {"stale", "expired", "insufficient_data"}:
        raise CanaryPromotionBlockedError(
            report.verdict,
            f"Canary is not fresh enough for promotion: {review.freshness_status}.",
            f"cambrian template canary-review {stage.candidate_template_name}",
        )
    if review.promotion_gate == "warn" and not force:
        raise CanaryPromotionBlockedError(
            report.verdict,
            f"Canary freshness is {review.freshness_status}; more recent evidence is recommended before promotion.",
            f"cambrian template canary-promote {stage.candidate_template_name} --force",
        )
    if review.promotion_gate == "block":
        raise CanaryPromotionBlockedError(
            report.verdict,
            f"Canary review blocks promotion: {review.freshness_status}.",
            f"cambrian template canary-review {stage.candidate_template_name}",
        )
    if review.promotion_gate == "warn" and force:
        warnings.append(f"forced canary promotion with freshness: {review.freshness_status}")
    if report.verdict != "promote_ready":
        if not force or report.verdict not in SOFT_PROMOTION_VERDICTS:
            raise CanaryPromotionBlockedError(
                report.verdict,
                "Canary is not ready for promotion.",
                f"cambrian template canary-promote {stage.candidate_template_name} --force",
            )
        warnings.append(f"forced canary promotion with verdict: {report.verdict}")
    decision, playbook, library_decisions, adoption, adoption_path = accept_qualification(
        root,
        stage.qualification_ref,
        set_lane_default=True,
        parent_action=previous_default_action,
        resolution=resolution or f"canary promotion gate verdict: {report.verdict}",
        force=force,
    )
    cleared_stage, cleared_playbook, _ = unstage_qualification_canary(
        root,
        stage.qualification_ref,
        resolution="promoted to stable lane default",
    )
    return {
        "status": "promoted",
        "report": report.to_dict(),
        "review": review.to_dict(),
        "decision": decision.to_dict(),
        "lane_playbook": (cleared_playbook or playbook).to_dict(),
        "library_decisions": [item.to_dict() for item in library_decisions],
        "adoption": adoption.to_dict(),
        "adoption_path": _relative(adoption_path, root),
        "cleared_stage": cleared_stage.to_dict(),
        "warnings": warnings,
    }


def render_canary_report(report: TemplateCanaryReport, saved_path: str | None = None) -> str:
    """canary report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Template Canary Report",
        "==================================================",
        "",
        "Lane:",
        f"  {report.lane_label or report.lane_id or 'unknown'}",
        "",
        "Stable default:",
        f"  {report.stable_default_template_name or 'none'}",
        "",
        "Canary:",
        f"  {report.candidate_template_name}",
        "",
        "Verdict:",
        f"  {report.verdict}",
    ]
    if report.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in report.summary[:5]])
    if report.why_promote:
        lines.extend(["", "Why promote:"])
        lines.extend([f"  - {item}" for item in report.why_promote[:5]])
    if report.why_wait:
        lines.extend(["", "Why wait:"])
        lines.extend([f"  - {item}" for item in report.why_wait[:5]])
    if report.why_clear:
        lines.extend(["", "Why clear:"])
        lines.extend([f"  - {item}" for item in report.why_clear[:5]])
    lines.extend(["", "Exposure:"])
    for key in (
        "recommended_count",
        "shortlisted_count",
        "selected_count",
        "selected_with_outcome_count",
        "selected_then_validated_count",
        "selected_then_adopted_count",
        "bootstrap_count",
        "apply_count",
        "replay_count",
        "replay_validated_count",
        "replay_blocked_count",
    ):
        lines.append(f"  {key}: {report.exposure_counts.get(key, 0)}")
    lines.extend(["", "Metrics:"])
    lines.append(f"  candidate validated    : {_pct(report.candidate_metrics.validated_proposal_rate)}")
    lines.append(f"  stable validated       : {_pct(report.stable_metrics.validated_proposal_rate if report.stable_metrics else None)}")
    lines.append(f"  candidate intervention : {_pct(report.candidate_metrics.human_intervention_rate)}")
    lines.append(f"  stable intervention    : {_pct(report.stable_metrics.human_intervention_rate if report.stable_metrics else None)}")
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in report.next_actions[:4]])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings[:5]])
    return "\n".join(lines)


def render_canary_report_summary(summary: dict[str, Any]) -> str:
    """show/status/harness용 canary report 요약."""
    if not summary:
        return "Canary burn-in:\n  none"
    lines = ["Canary burn-in:", f"  verdict: {summary.get('verdict') or 'unknown'}"]
    if summary.get("candidate_template_name"):
        lines.append(f"  template: {summary.get('candidate_template_name')}")
    return "\n".join(lines)


def render_canary_promoted(payload: dict[str, Any]) -> str:
    """canary-promote 결과를 렌더링한다."""
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    review = payload.get("review") if isinstance(payload.get("review"), dict) else {}
    playbook = payload.get("lane_playbook") if isinstance(payload.get("lane_playbook"), dict) else {}
    adoption = payload.get("adoption") if isinstance(payload.get("adoption"), dict) else {}
    previous_default = adoption.get("before_state", {}).get("lane_default_template_name") if isinstance(adoption.get("before_state"), dict) else None
    lines = [
        "Canary promoted to stable lane default.",
        "",
        "New default:",
        f"  {playbook.get('default_template_name') or report.get('candidate_template_name') or 'unknown'}",
        "",
        "Previous default:",
        f"  {previous_default or 'none'}",
        "",
        "Verdict:",
        f"  {report.get('verdict') or 'unknown'}",
    ]
    if review:
        lines.extend([
            "",
            "Freshness:",
            f"  {review.get('freshness_status') or 'unknown'}",
            "Promotion gate:",
            f"  {review.get('promotion_gate') or 'unknown'}",
        ])
    warnings = [str(item) for item in payload.get("warnings", []) if item]
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in warnings])
    if payload.get("adoption_path"):
        lines.extend(["", "Saved:", f"  {payload.get('adoption_path')}"])
    return "\n".join(lines)


def _load_qualification_for_stage(root: Path, stage: TemplateCanaryStage | None) -> TemplateQualificationReport | None:
    if stage is None or not stage.qualification_ref:
        return None
    try:
        path = resolve_template_qualification_path(root, stage.qualification_ref)
        return TemplateQualificationStore().load(path)
    except Exception as exc:
        logger.warning("canary qualification load failed: %s", exc)
        return None


def _metrics_from_evidence(
    root: Path,
    candidate_name: str,
    stable_name: str | None,
    qualification_report: TemplateQualificationReport | None,
) -> tuple[TemplateCanaryMetrics, TemplateCanaryMetrics | None]:
    candidate_snapshots: list[dict[str, Any]] = []
    stable_snapshots: list[dict[str, Any]] = []
    if qualification_report is not None:
        candidate_snapshots.extend([run.metrics_snapshot for run in qualification_report.candidate_runs])
        if stable_name and _slug(qualification_report.reference_template_name) == _slug(stable_name):
            stable_snapshots.extend([run.metrics_snapshot for run in qualification_report.reference_runs])
    for payload in _workset_replay_payloads(root):
        template_name = _template_context_name(payload)
        if _slug(template_name) == _slug(candidate_name):
            candidate_snapshots.append(_summary_from_workset_payload(payload))
        elif stable_name and _slug(template_name) == _slug(stable_name):
            stable_snapshots.append(_summary_from_workset_payload(payload))
    candidate = _aggregate_metrics(candidate_snapshots)
    stable = _aggregate_metrics(stable_snapshots) if stable_snapshots else None
    return candidate, stable


def _aggregate_metrics(snapshots: list[dict[str, Any]]) -> TemplateCanaryMetrics:
    return TemplateCanaryMetrics(
        validated_proposal_rate=_avg_metric(snapshots, "validated_proposal_rate"),
        human_intervention_rate=_avg_metric(snapshots, "human_intervention_rate"),
        validation_autonomy_rate=_avg_metric(snapshots, "validation_autonomy_rate"),
        median_duration_seconds=_median([item.get("median_duration_seconds") for item in snapshots]),
        team_template_recommendation_hit_rate=_rate([True for _ in snapshots]) if snapshots else None,
        reuse_lift=None,
        repeat_task_improvement_rate=_avg_metric(snapshots, "validated_proposal_rate") if len(snapshots) >= 2 else None,
    )


def _avg_metric(snapshots: list[dict[str, Any]], key: str) -> float | None:
    values: list[float] = []
    for item in snapshots:
        try:
            value = item.get(key)
            if value is not None:
                values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _exposure_counts(root: Path, candidate_name: str, signals: list[TemplateCanarySignal]) -> dict[str, int]:
    counts = {
        "recommended_count": 0,
        "shortlisted_count": 0,
        "selected_count": 0,
        "selected_with_outcome_count": 0,
        "selected_then_validated_count": 0,
        "selected_then_adopted_count": 0,
        "selected_then_regression_free_apply_count": 0,
        "bootstrap_count": 0,
        "apply_count": 0,
        "replay_count": 0,
        "replay_validated_count": 0,
        "replay_blocked_count": 0,
    }
    for path in [
        root / ".cambrian" / "templates" / "recommendation.yaml",
        root / ".cambrian" / "templates" / "recommendation__request.yaml",
    ]:
        payload = _load_yaml(path)
        if _candidate_in_recommendation(payload, candidate_name):
            counts["recommended_count"] += 1
            signals.append(_signal("recommendation_surface", "candidate surfaced in template recommendation", 1, _relative(path, root)))
    board = _load_yaml(root / ".cambrian" / "templates" / "library_board.yaml")
    if _candidate_in_board(board, candidate_name):
        counts["recommended_count"] += 1
        signals.append(_signal("recommendation_surface", "candidate surfaced in template board", 1, ".cambrian/templates/library_board.yaml"))
    choice_path = root / ".cambrian" / "templates" / "bootstrap_choice.yaml"
    choice = _load_yaml(choice_path)
    considered = [str(item) for item in choice.get("considered_templates", []) if item]
    if any(_slug(item) == _slug(candidate_name) for item in considered):
        counts["shortlisted_count"] += 1
        signals.append(_signal("bootstrap_selected", "candidate appeared in bootstrap shortlist", 1, _relative(choice_path, root)))
    selected = str(choice.get("selected_template_name") or "")
    if _slug(selected) == _slug(candidate_name):
        counts["selected_count"] += 1
        signals.append(_signal("bootstrap_selected", "candidate selected during bootstrap choice", 1, _relative(choice_path, root)))
    bootstrap = _load_yaml(root / ".cambrian" / "templates" / "bootstrap_record.yaml")
    if _slug(bootstrap.get("template_name")) == _slug(candidate_name):
        counts["bootstrap_count"] += 1
        signals.append(_signal("bootstrap_selected", "candidate used for template bootstrap", 1, ".cambrian/templates/bootstrap_record.yaml"))
    current = _load_yaml(root / ".cambrian" / "templates" / "current_template.yaml")
    if _slug(current.get("name") or current.get("template_name")) == _slug(candidate_name):
        counts["apply_count"] += 1
        signals.append(_signal("template_applied", "candidate is current applied template", 1, ".cambrian/templates/current_template.yaml"))
    replay_count = 0
    for payload in _workset_replay_payloads(root):
        if _slug(_template_context_name(payload)) == _slug(candidate_name):
            replay_count += 1
    counts["replay_count"] = replay_count
    if replay_count:
        signals.append(_signal("benchmark_replay", "candidate has template override replay evidence", replay_count, ".cambrian/benchmarks/workset_replays"))
    return counts


def _outcome_exposure_counts(
    root: Path,
    candidate_name: str,
    signals: list[TemplateCanarySignal],
    warnings: list[str],
) -> dict[str, int]:
    try:
        outcome_summary = CanaryOutcomeSummaryBuilder().build(root, template_name=candidate_name)
    except CanaryOutcomeBlockedError:
        return {}
    except Exception as exc:
        logger.warning("canary outcome attribution load failed: %s", exc)
        warnings.append(f"canary outcome attribution load failed: {exc}")
        return {}
    if not any(int(value or 0) for value in outcome_summary.counts.values()):
        return {}
    counts = {
        "selected_with_outcome_count": int(outcome_summary.counts.get("selected_with_outcome_count", 0) or 0),
        "selected_then_validated_count": int(outcome_summary.counts.get("selected_then_validated_count", 0) or 0),
        "selected_then_adopted_count": int(outcome_summary.counts.get("selected_then_adopted_count", 0) or 0),
        "selected_then_regression_free_apply_count": int(
            outcome_summary.counts.get("selected_then_regression_free_apply_count", 0) or 0
        ),
    }
    signals.append(_signal(
        "retrospective_positive",
        "selected outcome attribution is available",
        counts["selected_with_outcome_count"],
        ".cambrian/templates/canary_outcomes",
    ))
    if counts["selected_then_validated_count"]:
        signals.append(_signal(
            "benchmark_replay",
            "selected canary usage reached validated proposal",
            counts["selected_then_validated_count"],
            ".cambrian/templates/canary_outcomes",
        ))
    return counts


def _ledger_exposure_counts(
    root: Path,
    candidate_name: str,
    signals: list[TemplateCanarySignal],
    warnings: list[str],
) -> dict[str, int]:
    try:
        ledger = CanaryLedgerBuilder().build(root, template_name=candidate_name)
    except CanaryLedgerBlockedError:
        return {}
    except Exception as exc:
        logger.warning("canary ledger exposure load failed: %s", exc)
        warnings.append(f"canary ledger exposure load failed: {exc}")
        return {}
    if not any(int(value or 0) for value in ledger.counts.values()):
        return {}
    counts = {
        "recommended_count": int(ledger.counts.get("recommend_surfaced_count", 0) or 0)
        + int(ledger.counts.get("board_surfaced_count", 0) or 0),
        "shortlisted_count": int(ledger.counts.get("bootstrap_surfaced_count", 0) or 0),
        "selected_count": int(ledger.counts.get("selected_count", 0) or 0),
        "bootstrap_count": int(ledger.counts.get("bootstrap_count", 0) or 0),
        "apply_count": int(ledger.counts.get("apply_count", 0) or 0),
        "replay_count": int(ledger.counts.get("replay_count", 0) or 0),
        "replay_validated_count": int(ledger.counts.get("replay_validated_count", 0) or 0),
        "replay_blocked_count": int(ledger.counts.get("replay_blocked_count", 0) or 0),
    }
    signals.append(_signal(
        "recommendation_surface",
        "exposure evidence is ledger-backed",
        int(ledger.counts.get("surfaced_count", 0) or 0),
        ".cambrian/templates/canary_events",
    ))
    if counts["replay_validated_count"]:
        signals.append(_signal(
            "benchmark_replay",
            "ledger recorded canary replay validation evidence",
            counts["replay_validated_count"],
            ".cambrian/templates/canary_events",
        ))
    return counts


def _retrospective_signals(root: Path, candidate_name: str, signals: list[TemplateCanarySignal]) -> dict[str, int]:
    positives = 0
    cautions = 0
    for item in TemplateRetrospectiveStore().list(default_template_retrospectives_dir(root), candidate_name):
        if item.rating in {"strong", "good"}:
            positives += 1
            signals.append(_signal("retrospective_positive", item.summary or item.text, item.rating, item.retrospective_id))
        elif item.rating in {"mixed", "weak"}:
            cautions += 1
            signals.append(_signal("retrospective_caution", item.summary or item.text, item.rating, item.retrospective_id))
    return {"positive": positives, "caution": cautions}


def _history_signals(root: Path, candidate_name: str, signals: list[TemplateCanarySignal]) -> dict[str, int]:
    try:
        passport = TemplateHistoryBuilder().build_passport(root, candidate_name)
    except Exception as exc:
        logger.warning("canary template history load failed: %s", exc)
        return {"wins": 0, "cautions": 0}
    wins = len(passport.recent_wins)
    cautions = len(passport.recent_cautions)
    if wins:
        signals.append(_signal("template_applied", "candidate has positive local template history", wins, None))
    if cautions:
        signals.append(_signal("retrospective_caution", "candidate has caution history", cautions, None))
    return {"wins": wins, "cautions": cautions}


def _verdict(
    *,
    qualification_report: TemplateQualificationReport | None,
    candidate_metrics: TemplateCanaryMetrics,
    stable_metrics: TemplateCanaryMetrics | None,
    exposure_counts: dict[str, int],
    retrospective_counts: dict[str, int],
    history_counts: dict[str, int],
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    why_promote: list[str] = []
    why_wait: list[str] = []
    why_clear: list[str] = []
    summary: list[str] = []
    qualification_verdict = qualification_report.verdict if qualification_report else None
    if qualification_verdict == "candidate_stronger":
        why_promote.append("qualification says candidate_stronger")
    elif qualification_verdict in {"regressed", "mixed"}:
        why_clear.append(f"qualification verdict is {qualification_verdict}")
    else:
        why_wait.append("qualification evidence is missing or inconclusive")

    metric_comparison = _metric_comparison(candidate_metrics, stable_metrics)
    why_promote.extend(metric_comparison["positive"])
    why_wait.extend(metric_comparison["wait"])
    why_clear.extend(metric_comparison["negative"])
    exposure_total = sum(int(exposure_counts.get(key, 0) or 0) for key in exposure_counts)
    burn_in_total = (
        int(exposure_counts.get("selected_count", 0) or 0)
        + int(exposure_counts.get("selected_then_validated_count", 0) or 0)
        + int(exposure_counts.get("selected_then_adopted_count", 0) or 0)
        + int(exposure_counts.get("bootstrap_count", 0) or 0)
        + int(exposure_counts.get("apply_count", 0) or 0)
        + int(exposure_counts.get("replay_validated_count", 0) or 0)
        + int(retrospective_counts.get("positive", 0) or 0)
        + int(history_counts.get("wins", 0) or 0)
    )
    if exposure_total <= 1:
        why_wait.append("canary exposure is still low")
    if burn_in_total >= 1:
        why_promote.append("canary has at least one post-stage positive burn-in signal")
    if int(exposure_counts.get("selected_then_validated_count", 0) or 0):
        why_promote.append("selected canary usage reached validated proposal")
    if int(exposure_counts.get("selected_with_outcome_count", 0) or 0) and not int(
        exposure_counts.get("selected_then_validated_count", 0) or 0
    ):
        why_wait.append("selected canary usage has linked outcomes but no validation yet")
    if int(exposure_counts.get("replay_blocked_count", 0) or 0) > int(
        exposure_counts.get("replay_validated_count", 0) or 0
    ):
        why_wait.append("canary replay blocks still exceed validated replay evidence")
    if retrospective_counts.get("caution", 0) or history_counts.get("cautions", 0):
        why_clear.append("canary has caution or weak retrospective history")

    if why_clear and (qualification_verdict == "regressed" or len(why_clear) >= 2):
        verdict = "clear_canary"
    elif not qualification_report and exposure_total <= 1:
        verdict = "insufficient_data"
    elif qualification_verdict == "candidate_stronger" and not why_clear and burn_in_total >= 1 and _has_metric_support(metric_comparison):
        verdict = "promote_ready"
    elif qualification_verdict == "candidate_stronger" or exposure_total > 1:
        verdict = "keep_canary" if qualification_verdict == "candidate_stronger" else "insufficient_data"
    else:
        verdict = "insufficient_data"

    if verdict == "promote_ready":
        summary.append("canary has qualification support, burn-in signal, and no major metric regression")
    elif verdict == "keep_canary":
        summary.append("canary looks promising, but more burn-in evidence is needed")
    elif verdict == "clear_canary":
        summary.append("canary has negative evidence and should be cleared rather than promoted")
    else:
        summary.append("not enough canary burn-in evidence to make a promotion decision")
    return verdict, _dedupe(why_promote), _dedupe(why_wait), _dedupe(why_clear), summary


def _metric_comparison(candidate: TemplateCanaryMetrics, stable: TemplateCanaryMetrics | None) -> dict[str, list[str]]:
    result = {"positive": [], "wait": [], "negative": []}
    if stable is None:
        result["wait"].append("stable default metrics are unavailable")
        return result
    validated_delta = _delta(candidate.validated_proposal_rate, stable.validated_proposal_rate)
    intervention_delta = _delta(candidate.human_intervention_rate, stable.human_intervention_rate)
    autonomy_delta = _delta(candidate.validation_autonomy_rate, stable.validation_autonomy_rate)
    duration_delta = _delta(candidate.median_duration_seconds, stable.median_duration_seconds)
    if validated_delta is not None:
        if validated_delta >= RATE_THRESHOLD:
            result["positive"].append(f"validated proposal rate improved +{validated_delta:.0%}")
        elif validated_delta <= -RATE_THRESHOLD:
            result["negative"].append(f"validated proposal rate regressed {validated_delta:.0%}")
        else:
            result["positive"].append("validated proposal rate is stable")
    else:
        result["wait"].append("validated proposal comparison is missing")
    if intervention_delta is not None:
        if intervention_delta <= -RATE_THRESHOLD:
            result["positive"].append(f"human intervention rate improved {intervention_delta:.0%}")
        elif intervention_delta >= RATE_THRESHOLD:
            result["negative"].append(f"human intervention rate worsened +{intervention_delta:.0%}")
        else:
            result["positive"].append("human intervention rate is stable")
    else:
        result["wait"].append("human intervention comparison is missing")
    if autonomy_delta is not None and autonomy_delta >= RATE_THRESHOLD:
        result["positive"].append(f"validation autonomy improved +{autonomy_delta:.0%}")
    elif autonomy_delta is not None and autonomy_delta <= -RATE_THRESHOLD:
        result["negative"].append(f"validation autonomy regressed {autonomy_delta:.0%}")
    if duration_delta is not None and duration_delta > DURATION_THRESHOLD_SECONDS:
        result["negative"].append(f"median duration worsened +{duration_delta:.0f}s")
    return result


def _has_metric_support(metric_comparison: dict[str, list[str]]) -> bool:
    positives = metric_comparison.get("positive", [])
    negatives = metric_comparison.get("negative", [])
    return bool(positives) and not negatives


def _delta(candidate: float | None, stable: float | None) -> float | None:
    if candidate is None or stable is None:
        return None
    return round(float(candidate) - float(stable), 4)


def _next_actions(candidate_name: str, stage: TemplateCanaryStage | None, verdict: str) -> list[str]:
    if verdict == "promote_ready":
        return [f"cambrian template canary-promote {candidate_name}"]
    if verdict == "clear_canary" and stage is not None:
        return [f"cambrian template qualify-unstage {stage.qualification_ref}"]
    if stage is not None:
        return [
            f"cambrian template canary-report {candidate_name} --save",
            f"cambrian template qualify-unstage {stage.qualification_ref}",
        ]
    return [f"cambrian template canary-report {candidate_name} --save"]


def _candidate_in_recommendation(payload: dict[str, Any], candidate_name: str) -> bool:
    if not payload:
        return False
    if _slug(payload.get("best_template_name")) == _slug(candidate_name):
        return True
    for item in payload.get("candidates", []) or []:
        if not isinstance(item, dict):
            continue
        if _slug(item.get("name")) == _slug(candidate_name) and str(item.get("recommendation")) not in {"weak", "reject"}:
            return True
    return False


def _candidate_in_board(payload: dict[str, Any], candidate_name: str) -> bool:
    for item in payload.get("entries", []) or []:
        if not isinstance(item, dict):
            continue
        if _slug(item.get("template_name")) == _slug(candidate_name) and str(item.get("recommendation")) != "retire_candidate":
            return True
    return False


def _workset_replay_payloads(root: Path) -> list[dict[str, Any]]:
    target = root / ".cambrian" / "benchmarks" / "workset_replays"
    if not target.exists():
        return []
    return [_load_yaml(path) for path in sorted(target.glob("replay_*.yaml")) if _load_yaml(path)]


def _template_context_name(payload: dict[str, Any]) -> str | None:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    context = summary.get("template_context") if isinstance(summary.get("template_context"), dict) else {}
    if context.get("template_name"):
        return str(context.get("template_name"))
    context = payload.get("template_context") if isinstance(payload.get("template_context"), dict) else {}
    return str(context.get("template_name")) if context.get("template_name") else None


def _summary_from_workset_payload(payload: dict[str, Any]) -> dict[str, Any]:
    summary = dict(payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {})
    if "validated_proposal_rate" not in summary:
        entries = [item for item in payload.get("entries", []) or [] if isinstance(item, dict)]
        summary["validated_proposal_rate"] = _rate([entry.get("validated_proposal") for entry in entries])
        summary["human_intervention_rate"] = _rate([entry.get("human_intervention") for entry in entries])
        summary["validation_autonomy_rate"] = _rate([entry.get("validation_autonomy") for entry in entries])
        summary["median_duration_seconds"] = _median([entry.get("duration_seconds") for entry in entries])
    return summary


def _signal(kind: str, summary: str, value: float | int | str | None, evidence_ref: str | None) -> TemplateCanarySignal:
    return TemplateCanarySignal(
        signal_id=f"canary-signal-{kind}-{_short_id()}",
        kind=kind,
        summary=str(summary or kind),
        value=value,
        evidence_ref=evidence_ref,
        warnings=[],
    )


def _find_template_or_none(model: Any, template_name: str | None) -> Any | None:
    if not template_name:
        return None
    try:
        return HarnessTemplateStore().find(model, template_name)
    except KeyError:
        return None


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def _report_from_dict(payload: dict[str, Any]) -> TemplateCanaryReport:
    return TemplateCanaryReport(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        report_id=str(payload.get("report_id") or f"template-canary-report-{_short_id()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        candidate_template_name=str(payload.get("candidate_template_name") or ""),
        candidate_template_id=str(payload.get("candidate_template_id")) if payload.get("candidate_template_id") is not None else None,
        stable_default_template_name=str(payload.get("stable_default_template_name")) if payload.get("stable_default_template_name") is not None else None,
        stable_default_template_id=str(payload.get("stable_default_template_id")) if payload.get("stable_default_template_id") is not None else None,
        stage_ref=str(payload.get("stage_ref")) if payload.get("stage_ref") is not None else None,
        qualification_ref=str(payload.get("qualification_ref")) if payload.get("qualification_ref") is not None else None,
        candidate_metrics=_metrics_from_dict(payload.get("candidate_metrics", {})),
        stable_metrics=(
            _metrics_from_dict(payload.get("stable_metrics", {}))
            if isinstance(payload.get("stable_metrics"), dict)
            else None
        ),
        exposure_counts={str(key): int(value or 0) for key, value in dict(payload.get("exposure_counts", {})).items()},
        signals=[
            _signal_from_dict(item)
            for item in payload.get("signals", []) or []
            if isinstance(item, dict)
        ],
        verdict=str(payload.get("verdict") or "insufficient_data"),
        summary=[str(item) for item in payload.get("summary", []) if item],
        why_promote=[str(item) for item in payload.get("why_promote", []) if item],
        why_wait=[str(item) for item in payload.get("why_wait", []) if item],
        why_clear=[str(item) for item in payload.get("why_clear", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _metrics_from_dict(payload: dict[str, Any]) -> TemplateCanaryMetrics:
    return TemplateCanaryMetrics(
        validated_proposal_rate=_float_or_none(payload.get("validated_proposal_rate")),
        human_intervention_rate=_float_or_none(payload.get("human_intervention_rate")),
        validation_autonomy_rate=_float_or_none(payload.get("validation_autonomy_rate")),
        median_duration_seconds=_float_or_none(payload.get("median_duration_seconds")),
        team_template_recommendation_hit_rate=_float_or_none(payload.get("team_template_recommendation_hit_rate")),
        reuse_lift=_float_or_none(payload.get("reuse_lift")),
        repeat_task_improvement_rate=_float_or_none(payload.get("repeat_task_improvement_rate")),
    )


def _signal_from_dict(payload: dict[str, Any]) -> TemplateCanarySignal:
    return TemplateCanarySignal(
        signal_id=str(payload.get("signal_id") or f"canary-signal-{_short_id()}"),
        kind=str(payload.get("kind") or "unknown"),
        summary=str(payload.get("summary") or ""),
        value=payload.get("value"),
        evidence_ref=str(payload.get("evidence_ref")) if payload.get("evidence_ref") is not None else None,
        warnings=[str(item) for item in payload.get("warnings", []) if item],
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
