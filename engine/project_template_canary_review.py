"""canary evidence freshness review와 promotion gate 보강 모듈."""

from __future__ import annotations

import logging
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_canary import active_canary_stage
from engine.project_template_canary_ledger import CanaryEventStore, canary_events_dir
from engine.project_template_canary_outcomes import CanaryOutcomeLinkBuilder, CanaryOutcomeSummaryBuilder
from engine.project_template_qualification_decisions import LanePlaybookStore, lane_playbook_path
from engine.project_templates import HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
RECENT_DAYS = 14
STALE_AFTER_DAYS = 21
EXPIRE_AFTER_DAYS = 35


class CanaryReviewBlockedError(RuntimeError):
    """review 대상 canary를 찾을 수 없을 때 발생한다."""


def _now_dt() -> datetime:
    """현재 UTC 시각을 반환한다."""
    return datetime.now(timezone.utc)


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return _now_dt().isoformat()


def _stamp() -> str:
    """파일명용 UTC timestamp를 만든다."""
    return _now_dt().strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 식별자를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str | None, fallback: str = "item") -> str:
    """값을 파일명에 안전한 slug로 바꾼다."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _atomic_write_text(path: Path, content: str) -> None:
    """텍스트 파일을 원자적으로 저장한다."""
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
        logger.warning("canary review artifact load failed: %s (%s)", path, exc)
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


def _parse_dt(value: Any) -> datetime | None:
    """ISO 시각 문자열을 UTC datetime으로 변환한다."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _days_since(value: datetime | None, now: datetime) -> int | None:
    """특정 시각 이후 지난 일수를 계산한다."""
    if value is None:
        return None
    delta = now - value
    if delta.total_seconds() < 0:
        return 0
    return int(delta.total_seconds() // 86400)


def _ratio(numerator: int, denominator: int) -> float | None:
    """0 나눗셈 없이 비율을 계산한다."""
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def canary_reviews_dir(project_root: Path) -> Path:
    """canary review 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "canary_reviews"


def default_canary_review_path(project_root: Path, report: "TemplateCanaryReviewReport") -> Path:
    """canary review 기본 저장 경로."""
    return canary_reviews_dir(project_root) / f"review_{_slug(report.template_name)}_{_stamp()}_{_short_id()}.yaml"


def latest_canary_review_path(project_root: Path) -> Path:
    """latest canary review pointer 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "latest_canary_review.yaml"


@dataclass
class CanaryFreshnessWindow:
    """canary evidence freshness 판단 window."""

    recent_days: int
    stale_after_days: int
    expire_after_days: int

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateCanaryReviewReport:
    """canary evidence freshness review report."""

    schema_version: str
    review_id: str
    generated_at: str
    template_name: str
    template_id: str | None
    canary_stage_id: str | None
    lane_id: str | None
    lane_label: str | None
    stable_default_template_name: str | None
    window: CanaryFreshnessWindow
    lifetime_counts: dict[str, int]
    recent_counts: dict[str, int]
    recent_ratios: dict[str, float | None]
    evidence_age: dict[str, Any]
    freshness_status: str
    promotion_gate: str
    summary: list[str] = field(default_factory=list)
    why_fresh: list[str] = field(default_factory=list)
    why_wait: list[str] = field(default_factory=list)
    why_stale: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "review_id": self.review_id,
            "generated_at": self.generated_at,
            "template_name": self.template_name,
            "template_id": self.template_id,
            "canary_stage_id": self.canary_stage_id,
            "lane_id": self.lane_id,
            "lane_label": self.lane_label,
            "stable_default_template_name": self.stable_default_template_name,
            "window": self.window.to_dict(),
            "lifetime_counts": dict(self.lifetime_counts),
            "recent_counts": dict(self.recent_counts),
            "recent_ratios": dict(self.recent_ratios),
            "evidence_age": dict(self.evidence_age),
            "freshness_status": self.freshness_status,
            "promotion_gate": self.promotion_gate,
            "summary": list(self.summary),
            "why_fresh": list(self.why_fresh),
            "why_wait": list(self.why_wait),
            "why_stale": list(self.why_stale),
            "next_actions": list(self.next_actions),
            "source_refs": dict(self.source_refs),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateCanaryReviewBuilder:
    """canary ledger/outcome evidence로 freshness를 계산한다."""

    def build(self, project_root: Path, template_name: str | None = None) -> TemplateCanaryReviewReport:
        """active canary 또는 지정 template의 freshness review를 만든다."""
        root = Path(project_root).resolve()
        stage = active_canary_stage(root)
        target_name = str(template_name or (stage.candidate_template_name if stage else "")).strip()
        if not target_name:
            raise CanaryReviewBlockedError(
                "No active canary template found. Run: cambrian template qualify-stage <qualification>"
            )
        if stage is not None and template_name and _slug(stage.candidate_template_name) != _slug(template_name):
            raise CanaryReviewBlockedError(f"Active canary is {stage.candidate_template_name}, not {template_name}")

        now = _now_dt()
        window = CanaryFreshnessWindow(
            recent_days=RECENT_DAYS,
            stale_after_days=STALE_AFTER_DAYS,
            expire_after_days=EXPIRE_AFTER_DAYS,
        )
        warnings: list[str] = []
        events = CanaryEventStore().list_events(canary_events_dir(root), target_name)
        links = CanaryOutcomeLinkBuilder().build_links(root, target_name)
        try:
            outcome_summary = CanaryOutcomeSummaryBuilder().build(root, template_name=target_name)
            lifetime_counts = _lifetime_counts(outcome_summary.counts)
            outcome_ref = ".cambrian/templates/canary_outcomes"
        except Exception as exc:
            logger.warning("canary review outcome summary load failed: %s", exc)
            warnings.append(f"canary outcome summary load failed: {exc}")
            lifetime_counts = _lifetime_counts({})
            outcome_ref = None
        event_counts = _event_counts(events)
        for key in ("surfaced_count", "selected_count", "replay_count", "replay_validated_count", "replay_blocked_count"):
            lifetime_counts[key] = max(lifetime_counts.get(key, 0), event_counts.get(key, 0))

        recent_counts = _recent_counts(events, links, now, window.recent_days)
        recent_ratios = _recent_ratios(recent_counts, links, now, window.recent_days)
        evidence_age = _evidence_age(events, links, now)
        latest_report = _latest_canary_report_payload(root, target_name)
        latest_report_verdict = str(latest_report.get("verdict") or "") if latest_report else None
        freshness_status, why_fresh, why_wait, why_stale = _freshness_status(
            lifetime_counts=lifetime_counts,
            recent_counts=recent_counts,
            evidence_age=evidence_age,
            latest_report_verdict=latest_report_verdict,
            window=window,
        )
        promotion_gate = _promotion_gate(freshness_status, latest_report_verdict)
        summary = _summary_lines(freshness_status, promotion_gate, recent_counts, evidence_age)
        return TemplateCanaryReviewReport(
            schema_version=SCHEMA_VERSION,
            review_id=f"canary-review-{_slug(target_name)}-{_short_id()}",
            generated_at=_now(),
            template_name=target_name,
            template_id=_template_id(root, target_name),
            canary_stage_id=stage.stage_id if stage and _slug(stage.candidate_template_name) == _slug(target_name) else None,
            lane_id=stage.lane_id if stage else getattr(_load_playbook(root), "lane_id", None),
            lane_label=stage.lane_label if stage else getattr(_load_playbook(root), "label", None),
            stable_default_template_name=getattr(_load_playbook(root), "default_template_name", None),
            window=window,
            lifetime_counts=lifetime_counts,
            recent_counts=recent_counts,
            recent_ratios=recent_ratios,
            evidence_age=evidence_age,
            freshness_status=freshness_status,
            promotion_gate=promotion_gate,
            summary=summary,
            why_fresh=why_fresh,
            why_wait=why_wait,
            why_stale=why_stale,
            next_actions=_next_actions(target_name, stage, freshness_status, promotion_gate),
            source_refs={
                "canary_stage_ref": getattr(stage, "qualification_ref", None),
                "canary_ledger_ref": ".cambrian/templates/canary_events",
                "canary_outcomes_ref": outcome_ref,
                "canary_report_ref": latest_report.get("report_id") if latest_report else None,
            },
            warnings=_dedupe(warnings),
            errors=[],
        )


class TemplateCanaryReviewStore:
    """canary review 저장소."""

    def save(self, report: TemplateCanaryReviewReport, path: Path) -> Path:
        """review를 저장하고 latest pointer를 갱신한다."""
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        project_root = saved.parents[3] if len(saved.parents) > 3 else saved.parent
        _save_yaml(latest_canary_review_path(project_root), report.to_dict())
        return saved

    def load(self, path: Path) -> TemplateCanaryReviewReport:
        """review artifact를 로드한다."""
        return _review_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, reports_dir: Path) -> list[TemplateCanaryReviewReport]:
        """저장된 review 목록을 최신순으로 반환한다."""
        target = Path(reports_dir).resolve()
        if not target.exists():
            return []
        reports: list[TemplateCanaryReviewReport] = []
        for path in target.glob("review_*.yaml"):
            payload = _load_yaml(path)
            if payload:
                reports.append(_review_from_dict(payload))
        return sorted(reports, key=lambda report: report.generated_at, reverse=True)


def resolve_canary_review_path(project_root: Path, review_ref: str) -> Path:
    """canary review id 또는 path를 실제 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(review_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in canary_reviews_dir(root).glob("review_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == review_ref or str(payload.get("review_id") or "") == review_ref:
            return path.resolve()
    raise FileNotFoundError(f"canary review not found: {review_ref}")


def load_latest_canary_review(project_root: Path, template_name: str | None = None) -> TemplateCanaryReviewReport | None:
    """latest canary review를 로드한다."""
    root = Path(project_root).resolve()
    wanted = _slug(template_name) if template_name else None
    pointer = latest_canary_review_path(root)
    if pointer.exists():
        review = _review_from_dict(_load_yaml(pointer))
        if not wanted or _slug(review.template_name) == wanted:
            return review
    reports = TemplateCanaryReviewStore().list(canary_reviews_dir(root))
    if wanted:
        reports = [report for report in reports if _slug(report.template_name) == wanted]
    return reports[0] if reports else None


def load_canary_review_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """status/show/harness에서 쓰는 compact review summary를 만든다."""
    try:
        report = TemplateCanaryReviewBuilder().build(project_root, template_name=template_name)
    except CanaryReviewBlockedError:
        return {}
    except Exception as exc:
        logger.warning("canary review summary load failed: %s", exc)
        return {"warnings": [f"canary review summary load failed: {exc}"]}
    return {
        "review_id": report.review_id,
        "template_name": report.template_name,
        "stable_default_template_name": report.stable_default_template_name,
        "freshness_status": report.freshness_status,
        "promotion_gate": report.promotion_gate,
        "recent_counts": dict(report.recent_counts),
        "evidence_age": dict(report.evidence_age),
        "summary": list(report.summary[:3]),
    }


def render_canary_review(report: TemplateCanaryReviewReport, saved_path: str | None = None) -> str:
    """canary review를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Template Canary Review",
        "==================================================",
        "",
        "Template:",
        f"  {report.template_name}",
        "",
        "Stable default:",
        f"  {report.stable_default_template_name or 'none'}",
        "",
        "Freshness:",
        f"  {report.freshness_status}",
        "",
        "Promotion gate:",
        f"  {report.promotion_gate}",
        "",
        "Recent window:",
        f"  {report.window.recent_days} days",
        "",
        "Recent evidence:",
        f"  selected with outcome: {report.recent_counts.get('selected_with_outcome_count_recent', 0)}",
        f"  selected then validated: {report.recent_counts.get('selected_then_validated_count_recent', 0)}",
        f"  replay validated: {report.recent_counts.get('replay_validated_count_recent', 0)}",
    ]
    if report.summary:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {item}" for item in report.summary[:5]])
    if report.why_fresh:
        lines.extend(["", "Fresh signals:"])
        lines.extend([f"  - {item}" for item in report.why_fresh[:5]])
    if report.why_wait:
        lines.extend(["", "Wait signals:"])
        lines.extend([f"  - {item}" for item in report.why_wait[:5]])
    if report.why_stale:
        lines.extend(["", "Stale signals:"])
        lines.extend([f"  - {item}" for item in report.why_stale[:5]])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in report.next_actions[:4]])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings[:5]])
    return "\n".join(lines)


def render_canary_review_summary(summary: dict[str, Any]) -> str:
    """compact canary review summary를 렌더링한다."""
    if not summary:
        return "Canary review:\n  none"
    lines = [
        "Canary review:",
        f"  {summary.get('template_name') or 'canary'} -> {summary.get('freshness_status') or 'unknown'}",
    ]
    if summary.get("promotion_gate"):
        lines.append(f"  promotion gate: {summary.get('promotion_gate')}")
    return "\n".join(lines)


def _lifetime_counts(counts: dict[str, Any]) -> dict[str, int]:
    """outcome/ledger count를 review용 key로 정규화한다."""
    keys = [
        "surfaced_count",
        "selected_count",
        "selected_with_outcome_count",
        "selected_then_validated_count",
        "selected_then_adopted_count",
        "replay_count",
        "replay_validated_count",
        "replay_blocked_count",
    ]
    return {key: int(counts.get(key, 0) or 0) for key in keys}


def _event_counts(events: list[Any]) -> dict[str, int]:
    """raw event count를 lifetime key로 집계한다."""
    counts = _lifetime_counts({})
    for event in events:
        if event.event_kind == "surfaced":
            counts["surfaced_count"] += 1
        elif event.event_kind == "selected":
            counts["selected_count"] += 1
        elif event.event_kind == "applied":
            counts["selected_count"] += 1
        elif event.event_kind == "replayed":
            counts["replay_count"] += 1
        elif event.event_kind == "validated":
            counts["replay_validated_count"] += 1
        elif event.event_kind == "blocked" and event.surface_kind == "replay":
            counts["replay_blocked_count"] += 1
    return counts


def _recent_counts(events: list[Any], links: list[Any], now: datetime, recent_days: int) -> dict[str, int]:
    """recent window 안의 canary evidence를 집계한다."""
    cutoff = now - timedelta(days=recent_days)
    counts = {
        "surfaced_count_recent": 0,
        "selected_count_recent": 0,
        "selected_with_outcome_count_recent": 0,
        "selected_then_validated_count_recent": 0,
        "selected_then_adopted_count_recent": 0,
        "replay_count_recent": 0,
        "replay_validated_count_recent": 0,
        "replay_blocked_count_recent": 0,
    }
    for event in events:
        created = _parse_dt(event.created_at)
        if created is None or created < cutoff:
            continue
        if event.event_kind == "surfaced":
            counts["surfaced_count_recent"] += 1
        elif event.event_kind in {"selected", "applied", "bootstrapped"}:
            counts["selected_count_recent"] += 1
        elif event.event_kind == "replayed":
            counts["replay_count_recent"] += 1
        elif event.event_kind == "validated":
            counts["replay_validated_count_recent"] += 1
        elif event.event_kind == "blocked" and event.surface_kind == "replay":
            counts["replay_blocked_count_recent"] += 1
    for link in links:
        selected_at = _parse_dt(link.selected_at) or _parse_dt(link.created_at)
        if selected_at is None or selected_at < cutoff:
            continue
        if link.outcome_kind in {"session_outcome", "replay_outcome"}:
            counts["selected_with_outcome_count_recent"] += 1
            if link.validated_proposal is True:
                counts["selected_then_validated_count_recent"] += 1
            if link.adoption_succeeded is True:
                counts["selected_then_adopted_count_recent"] += 1
    return counts


def _recent_ratios(counts: dict[str, int], links: list[Any], now: datetime, recent_days: int) -> dict[str, float | None]:
    """recent link 기반 비율을 계산한다."""
    cutoff = now - timedelta(days=recent_days)
    recent_outcome_links = [
        link
        for link in links
        if link.outcome_kind in {"session_outcome", "replay_outcome"}
        and ((_parse_dt(link.selected_at) or _parse_dt(link.created_at)) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    autonomy_values = [link.validation_autonomy for link in recent_outcome_links if link.validation_autonomy is not None]
    intervention_values = [link.human_intervention for link in recent_outcome_links if link.human_intervention is not None]
    return {
        "selected_outcome_coverage_rate_recent": _ratio(
            counts["selected_with_outcome_count_recent"],
            counts["selected_count_recent"],
        ),
        "selected_then_validated_rate_recent": _ratio(
            counts["selected_then_validated_count_recent"],
            counts["selected_with_outcome_count_recent"],
        ),
        "selected_then_adopted_rate_recent": _ratio(
            counts["selected_then_adopted_count_recent"],
            counts["selected_with_outcome_count_recent"],
        ),
        "selected_validation_autonomy_rate_recent": _bool_rate(autonomy_values),
        "selected_human_intervention_rate_recent": _bool_rate(intervention_values),
    }


def _bool_rate(values: list[bool]) -> float | None:
    """bool 값의 true 비율을 계산한다."""
    if not values:
        return None
    return round(sum(1 for value in values if value) / len(values), 4)


def _evidence_age(events: list[Any], links: list[Any], now: datetime) -> dict[str, Any]:
    """마지막 활동/검증/채택 시각과 age를 계산한다."""
    surfaced = [_parse_dt(event.created_at) for event in events if event.event_kind == "surfaced"]
    selected = [
        _parse_dt(event.created_at)
        for event in events
        if event.event_kind in {"selected", "applied", "bootstrapped"} and event.selection_result in {None, "canary"}
    ]
    activity = [_parse_dt(event.created_at) for event in events]
    validated = [_parse_dt(event.created_at) for event in events if event.event_kind == "validated"]
    adopted: list[datetime | None] = []
    for link in links:
        link_time = _parse_dt(link.selected_at) or _parse_dt(link.created_at)
        activity.append(link_time)
        if link.validated_proposal is True:
            validated.append(link_time)
        if link.adoption_succeeded is True:
            adopted.append(link_time)
    last_activity = _max_dt(activity)
    last_validated = _max_dt(validated)
    return {
        "last_surfaced_at": _dt_to_str(_max_dt(surfaced)),
        "last_selected_at": _dt_to_str(_max_dt(selected)),
        "last_validated_at": _dt_to_str(last_validated),
        "last_adopted_at": _dt_to_str(_max_dt(adopted)),
        "days_since_last_activity": _days_since(last_activity, now),
        "days_since_last_validated": _days_since(last_validated, now),
    }


def _max_dt(values: list[datetime | None]) -> datetime | None:
    """None을 제외한 최대 datetime."""
    known = [value for value in values if value is not None]
    return max(known) if known else None


def _dt_to_str(value: datetime | None) -> str | None:
    """datetime을 ISO 문자열로 바꾼다."""
    return value.isoformat() if value is not None else None


def _freshness_status(
    *,
    lifetime_counts: dict[str, int],
    recent_counts: dict[str, int],
    evidence_age: dict[str, Any],
    latest_report_verdict: str | None,
    window: CanaryFreshnessWindow,
) -> tuple[str, list[str], list[str], list[str]]:
    """deterministic freshness status를 계산한다."""
    why_fresh: list[str] = []
    why_wait: list[str] = []
    why_stale: list[str] = []
    days_activity = evidence_age.get("days_since_last_activity")
    days_validated = evidence_age.get("days_since_last_validated")
    lifetime_positive = (
        int(lifetime_counts.get("selected_then_validated_count", 0) or 0)
        + int(lifetime_counts.get("selected_then_adopted_count", 0) or 0)
        + int(lifetime_counts.get("replay_validated_count", 0) or 0)
    )
    recent_positive = (
        int(recent_counts.get("selected_then_validated_count_recent", 0) or 0)
        + int(recent_counts.get("selected_then_adopted_count_recent", 0) or 0)
        + int(recent_counts.get("replay_validated_count_recent", 0) or 0)
    )
    recent_outcomes = int(recent_counts.get("selected_with_outcome_count_recent", 0) or 0)
    recent_blocks = int(recent_counts.get("replay_blocked_count_recent", 0) or 0)
    if not lifetime_positive and not int(lifetime_counts.get("selected_with_outcome_count", 0) or 0):
        why_wait.append("canary has little or no attributable selected outcome evidence")
        return "insufficient_data", why_fresh, why_wait, why_stale
    if days_activity is not None and days_activity > window.expire_after_days:
        why_stale.append(f"no canary activity for {days_activity} days")
        return "expired", why_fresh, why_wait, why_stale
    if days_activity is not None and days_activity > window.stale_after_days:
        why_stale.append(f"no meaningful recent activity for {days_activity} days")
        return "stale", why_fresh, why_wait, why_stale
    if recent_blocks > recent_positive and recent_positive == 0:
        why_stale.append("recent replay blocks dominate validated evidence")
        return "stale", why_fresh, why_wait, why_stale
    if recent_outcomes >= 2 or int(recent_counts.get("replay_validated_count_recent", 0) or 0) >= 2:
        if days_validated is not None and days_validated <= window.recent_days and latest_report_verdict != "clear_canary":
            why_fresh.append("recent selected outcome or replay validation evidence is sufficient")
            return "fresh", why_fresh, why_wait, why_stale
    if recent_outcomes > 0 or recent_positive > 0:
        why_wait.append("recent positive evidence exists, but sample size is still small")
        return "warming", why_fresh, why_wait, why_stale
    if lifetime_positive:
        if days_validated is None or days_validated > window.recent_days:
            why_wait.append("positive history exists, but last meaningful validation is outside the recent window")
            return "review_due", why_fresh, why_wait, why_stale
    why_wait.append("recent canary evidence is too sparse to justify promotion")
    return "insufficient_data", why_fresh, why_wait, why_stale


def _promotion_gate(freshness_status: str, latest_report_verdict: str | None) -> str:
    """freshness와 latest report verdict로 promotion gate를 계산한다."""
    if freshness_status == "fresh" and latest_report_verdict == "promote_ready":
        return "allow"
    if freshness_status == "fresh" and latest_report_verdict == "keep_canary":
        return "warn"
    if freshness_status in {"warming", "review_due"} and latest_report_verdict in {"promote_ready", "keep_canary"}:
        return "warn"
    return "block"


def _summary_lines(
    status: str,
    gate: str,
    recent_counts: dict[str, int],
    evidence_age: dict[str, Any],
) -> list[str]:
    """human-readable summary를 만든다."""
    lines = [f"canary freshness is {status}", f"promotion gate is {gate}"]
    if recent_counts.get("selected_with_outcome_count_recent"):
        lines.append(
            f"recent selected-with-outcome count is {recent_counts.get('selected_with_outcome_count_recent')}"
        )
    if recent_counts.get("selected_then_validated_count_recent"):
        lines.append(
            f"recent selected-then-validated count is {recent_counts.get('selected_then_validated_count_recent')}"
        )
    days_validated = evidence_age.get("days_since_last_validated")
    if days_validated is not None:
        lines.append(f"last validated evidence was {days_validated} days ago")
    return lines


def _next_actions(template_name: str, stage: Any, status: str, gate: str) -> list[str]:
    """freshness 상태별 다음 액션을 제안한다."""
    if gate == "allow":
        return [f"cambrian template canary-promote {template_name}"]
    if status in {"stale", "expired"} and stage is not None:
        return [f"cambrian template qualify-unstage {stage.qualification_ref}"]
    return [
        f"cambrian template canary-outcomes {template_name}",
        f"cambrian template canary-report {template_name} --save",
    ]


def _latest_canary_report_payload(root: Path, template_name: str) -> dict[str, Any]:
    """latest canary report payload를 순환 import 없이 읽는다."""
    wanted = _slug(template_name)
    pointer = root / ".cambrian" / "templates" / "latest_canary.yaml"
    if pointer.exists():
        payload = _load_yaml(pointer)
        if _slug(str(payload.get("candidate_template_name") or "")) == wanted:
            return payload
    reports_dir = root / ".cambrian" / "templates" / "canary_reports"
    reports: list[tuple[str, dict[str, Any]]] = []
    if reports_dir.exists():
        for path in reports_dir.glob("canary_*.yaml"):
            payload = _load_yaml(path)
            if _slug(str(payload.get("candidate_template_name") or "")) == wanted:
                reports.append((str(payload.get("generated_at") or ""), payload))
    reports.sort(key=lambda item: item[0], reverse=True)
    return reports[0][1] if reports else {}


def _load_playbook(root: Path) -> Any:
    """lane playbook을 안전하게 로드한다."""
    try:
        return LanePlaybookStore().load(lane_playbook_path(root))
    except Exception as exc:
        logger.warning("canary review lane playbook load failed: %s", exc)
        return type(
            "EmptyPlaybook",
            (),
            {"lane_id": None, "label": None, "default_template_name": None},
        )()


def _template_id(root: Path, template_name: str | None) -> str | None:
    """template id를 찾는다."""
    if not template_name:
        return None
    try:
        model = HarnessTemplateStore().load(default_templates_path(root))
        template = HarnessTemplateStore().find(model, template_name)
        return template.template_id
    except Exception as exc:
        logger.warning("canary review template lookup failed: %s", exc)
        return None


def _review_from_dict(payload: dict[str, Any]) -> TemplateCanaryReviewReport:
    """dict에서 review 모델을 복원한다."""
    window_payload = payload.get("window") if isinstance(payload.get("window"), dict) else {}
    return TemplateCanaryReviewReport(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        review_id=str(payload.get("review_id") or f"canary-review-{_short_id()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        template_name=str(payload.get("template_name") or ""),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        canary_stage_id=str(payload.get("canary_stage_id")) if payload.get("canary_stage_id") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        stable_default_template_name=(
            str(payload.get("stable_default_template_name"))
            if payload.get("stable_default_template_name") is not None
            else None
        ),
        window=CanaryFreshnessWindow(
            recent_days=int(window_payload.get("recent_days", RECENT_DAYS) or RECENT_DAYS),
            stale_after_days=int(window_payload.get("stale_after_days", STALE_AFTER_DAYS) or STALE_AFTER_DAYS),
            expire_after_days=int(window_payload.get("expire_after_days", EXPIRE_AFTER_DAYS) or EXPIRE_AFTER_DAYS),
        ),
        lifetime_counts={str(key): int(value or 0) for key, value in dict(payload.get("lifetime_counts", {})).items()},
        recent_counts={str(key): int(value or 0) for key, value in dict(payload.get("recent_counts", {})).items()},
        recent_ratios={str(key): (float(value) if value is not None else None) for key, value in dict(payload.get("recent_ratios", {})).items()},
        evidence_age=dict(payload.get("evidence_age", {}) or {}),
        freshness_status=str(payload.get("freshness_status") or "insufficient_data"),
        promotion_gate=str(payload.get("promotion_gate") or "block"),
        summary=[str(item) for item in payload.get("summary", []) if item],
        why_fresh=[str(item) for item in payload.get("why_fresh", []) if item],
        why_wait=[str(item) for item in payload.get("why_wait", []) if item],
        why_stale=[str(item) for item in payload.get("why_stale", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        source_refs=dict(payload.get("source_refs", {}) or {}),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
