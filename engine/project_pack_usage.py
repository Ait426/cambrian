"""Pack 사용 이벤트와 결과 attribution을 로컬 evidence로 기록한다."""

from __future__ import annotations

import json
import logging
import statistics
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
EVENT_KINDS = {"activated", "surfaced", "used", "benchmark_used", "deactivated"}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓰기 좋은 UTC 타임스탬프를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id(value: str | None = None) -> str:
    """짧은 식별자 조각을 만든다."""
    seed = value or _now()
    import hashlib

    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def _slug(value: str | None) -> str:
    """파일명에 안전한 slug를 만든다."""
    text = str(value or "unknown").strip().lower()
    chars: list[str] = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", ".", "/"}:
            chars.append("-" if char == "/" else char)
        else:
            chars.append("-")
    slug = "".join(chars).strip("-._")
    return slug or "unknown"


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


def _load_any(path: Path) -> dict[str, Any]:
    """YAML 또는 JSON artifact를 안전하게 읽는다."""
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("pack usage artifact load failed: %s (%s)", path, exc)
        return {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("pack usage artifact ignored: top level is not mapping: %s", path)
        return {}
    return payload


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _resolve_ref(project_root: Path, ref: str | None) -> Path | None:
    """artifact ref를 실제 경로로 변환한다."""
    if not ref:
        return None
    path = Path(str(ref))
    if not path.is_absolute():
        path = Path(project_root).resolve() / path
    return path


def _parse_datetime(value: Any) -> datetime | None:
    """ISO 문자열이나 date 값을 datetime으로 변환한다."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _duration_seconds(start: Any, end: Any) -> float | None:
    """두 시각 사이의 초 단위 duration을 계산한다."""
    start_dt = _parse_datetime(start)
    end_dt = _parse_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    return max(0.0, (end_dt - start_dt).total_seconds())


def _bool_or_none(value: Any) -> bool | None:
    """느슨한 bool 값을 bool/None으로 정규화한다."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "pass", "passed", "ok", "adopted", "applied"}:
        return True
    if text in {"0", "false", "no", "n", "fail", "failed", "none", "null", "blocked"}:
        return False
    return None


def default_pack_usage_dir(project_root: Path) -> Path:
    """pack usage 루트 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "usage"


def default_usage_events_dir(project_root: Path) -> Path:
    """usage event 저장 디렉터리를 반환한다."""
    return default_pack_usage_dir(project_root) / "events"


def default_usage_links_dir(project_root: Path) -> Path:
    """outcome link 저장 디렉터리를 반환한다."""
    return default_pack_usage_dir(project_root) / "links"


def default_usage_summaries_dir(project_root: Path) -> Path:
    """usage summary 저장 디렉터리를 반환한다."""
    return default_pack_usage_dir(project_root) / "summaries"


def default_usage_latest_path(project_root: Path) -> Path:
    """latest usage summary pointer 경로를 반환한다."""
    return default_pack_usage_dir(project_root) / "latest.yaml"


def default_usage_event_path(project_root: Path, event: "PackUsageEvent") -> Path:
    """usage event 기본 저장 경로를 반환한다."""
    return default_usage_events_dir(project_root) / f"event_{_slug(event.pack_id)}_{_stamp()}_{_short_id(event.event_id)}.yaml"


def default_outcome_link_path(project_root: Path, link: "PackOutcomeLink") -> Path:
    """outcome link 기본 저장 경로를 반환한다."""
    return default_usage_links_dir(project_root) / f"link_{_slug(link.pack_id)}_{_stamp()}_{_short_id(link.link_id)}.yaml"


def default_usage_summary_path(project_root: Path, summary: "PackUsageSummary") -> Path:
    """usage summary 기본 저장 경로를 반환한다."""
    pack = summary.pack_id or "all"
    return default_usage_summaries_dir(project_root) / f"summary_{_slug(pack)}_{_stamp()}_{_short_id(summary.summary_id)}.yaml"


@dataclass
class PackUsageEvent:
    """pack이 어떤 surface에서 사용되었는지 남기는 로컬 이벤트."""

    schema_version: str
    event_id: str
    created_at: str
    pack_ref: str
    pack_id: str
    pack_name: str | None
    pack_kind: str | None
    version: str | None
    namespace: str | None
    event_kind: str
    surface_kind: str
    request: str | None
    request_class: str | None
    linked_session_id: str | None
    linked_session_ref: str | None
    linked_request_ref: str | None
    linked_bridge_packet_ref: str | None
    linked_bridge_reply_ref: str | None
    linked_benchmark_replay_ref: str | None
    linked_benchmark_result_ref: str | None
    active_team: str | None
    active_template: str | None
    active_workset: str | None
    lane_id: str | None
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class PackOutcomeLink:
    """usage event와 실제 outcome source를 연결한 결과."""

    schema_version: str
    link_id: str
    created_at: str
    pack_ref: str
    pack_id: str
    version: str | None
    namespace: str | None
    usage_event_ref: str | None
    outcome_source_kind: str
    linked_session_id: str | None
    linked_session_ref: str | None
    linked_proposal_ref: str | None
    linked_benchmark_result_ref: str | None
    linked_replay_ref: str | None
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
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class PackUsageSummary:
    """pack usage와 outcome attribution을 집계한 요약."""

    schema_version: str
    summary_id: str
    generated_at: str
    pack_ref: str | None
    pack_id: str | None
    pack_name: str | None
    version: str | None
    namespace: str | None
    counts: dict[str, int]
    rates: dict[str, float | None]
    medians: dict[str, float | None]
    recent_events: list[str]
    source_refs: list[str]
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class PackUsageEventStore:
    """pack usage event 저장소."""

    def save_event(self, event: PackUsageEvent, path: Path) -> Path:
        """usage event를 저장한다."""
        return _save_yaml(Path(path).resolve(), event.to_dict())

    def load_event(self, path: Path) -> PackUsageEvent:
        """usage event를 로드한다."""
        return _event_from_dict(_load_any(Path(path).resolve()))

    def list_events(self, events_dir: Path, pack_id: str | None = None) -> list[PackUsageEvent]:
        """usage event 목록을 반환한다."""
        target = Path(events_dir).resolve()
        if not target.exists():
            return []
        events: list[PackUsageEvent] = []
        for path in sorted(target.glob("event_*.yaml")):
            payload = _load_any(path)
            if not payload:
                continue
            event = _event_from_dict(payload)
            if pack_id and not _pack_matches(event, pack_id):
                continue
            events.append(event)
        events.sort(key=lambda item: item.created_at, reverse=True)
        return events


class PackOutcomeLinkBuilder:
    """usage event를 session/replay/proposal outcome과 연결한다."""

    def build_links(self, project_root: Path, pack_id: str | None = None) -> list[PackOutcomeLink]:
        """pack usage event 기반 outcome link를 생성한다."""
        root = Path(project_root).resolve()
        events = PackUsageEventStore().list_events(default_usage_events_dir(root), pack_id=pack_id)
        links = [self._link_event(root, event) for event in events]
        return links

    def _link_event(self, project_root: Path, event: PackUsageEvent) -> PackOutcomeLink:
        event_ref = _event_ref(project_root, event)
        session_ref = event.linked_session_ref
        if session_ref:
            session_path = _resolve_ref(project_root, session_ref)
            if session_path is not None and session_path.exists():
                return _link_from_session(project_root, event, event_ref, session_path)
        replay_ref = event.linked_benchmark_replay_ref
        if replay_ref:
            replay_path = _resolve_ref(project_root, replay_ref)
            if replay_path is not None and replay_path.exists():
                return _link_from_replay(project_root, event, event_ref, replay_path)
        result_ref = event.linked_benchmark_result_ref
        if result_ref:
            result_path = _resolve_ref(project_root, result_ref)
            if result_path is not None and result_path.exists():
                return _link_from_benchmark_result(project_root, event, event_ref, result_path)
        return _partial_link(event, event_ref, "usage event exists but linked outcome source was not found")


class PackUsageSummaryBuilder:
    """pack usage와 outcome을 집계한다."""

    def build(self, project_root: Path, pack_ref: str | None = None) -> PackUsageSummary:
        """pack_ref가 없으면 전체 pack usage를 집계한다."""
        root = Path(project_root).resolve()
        events = PackUsageEventStore().list_events(default_usage_events_dir(root), pack_id=pack_ref)
        links = PackOutcomeLinkBuilder().build_links(root, pack_id=pack_ref)
        linked = [link for link in links if link.outcome_source_kind != "partial"]

        counts = {
            "activated_count": sum(1 for event in events if event.event_kind == "activated"),
            "surfaced_count": sum(1 for event in events if event.event_kind == "surfaced"),
            "used_count": sum(1 for event in events if event.event_kind in {"used", "benchmark_used"}),
            "bridge_used_count": sum(1 for event in events if event.surface_kind == "bridge_prepare"),
            "do_used_count": sum(1 for event in events if event.surface_kind == "do"),
            "continue_used_count": sum(1 for event in events if event.surface_kind == "continue"),
            "benchmark_used_count": sum(1 for event in events if event.event_kind == "benchmark_used"),
            "outcome_linked_count": len(linked),
            "validated_proposal_count": sum(1 for link in linked if link.validated_proposal is True),
            "adopted_count": sum(1 for link in linked if link.adoption_succeeded is True),
            "regression_free_apply_count": sum(1 for link in linked if link.regression_free_apply is True),
            "human_intervention_count": sum(1 for link in linked if link.human_intervention is True),
            "validation_autonomy_count": sum(1 for link in linked if link.validation_autonomy is True),
        }
        apply_records = _job_apply_records(root, pack_ref)
        adoption_records = _job_adoption_records(root, pack_ref)
        counts.update({
            "applied_count": max(
                sum(1 for event in events if event.surface_kind == "pack_job_apply"),
                sum(1 for record in apply_records if str(record.get("status")) == "applied"),
            ),
            "adoption_decision_count": len(adoption_records),
            "accepted_count": sum(1 for record in adoption_records if str(record.get("decision")) == "accepted"),
            "rejected_count": sum(1 for record in adoption_records if str(record.get("decision")) == "rejected"),
            "skipped_count": sum(1 for record in adoption_records if str(record.get("decision")) == "skipped"),
        })
        rates = {
            "validated_proposal_rate": _rate(counts["validated_proposal_count"], counts["outcome_linked_count"]),
            "adoption_rate": _rate(counts["adopted_count"], counts["validated_proposal_count"]),
            "regression_free_apply_rate": _rate(counts["regression_free_apply_count"], counts["adopted_count"]),
            "human_intervention_rate": _rate(counts["human_intervention_count"], counts["outcome_linked_count"]),
            "validation_autonomy_rate": _rate(counts["validation_autonomy_count"], counts["outcome_linked_count"]),
            "outcome_coverage_rate": _rate(counts["outcome_linked_count"], counts["used_count"]),
        }
        durations = [link.duration_seconds for link in linked if link.duration_seconds is not None]
        medians = {"time_to_validated_proposal_seconds": statistics.median(durations) if durations else None}
        first = events[0] if events else None
        warnings = []
        partial_count = len([link for link in links if link.outcome_source_kind == "partial"])
        if partial_count:
            warnings.append(f"{partial_count} usage events could not be linked to outcomes.")
        summary_lines = [
            f"used={counts['used_count']}",
            f"outcome_linked={counts['outcome_linked_count']}",
            f"validated={counts['validated_proposal_count']}",
            f"applied={counts['applied_count']}",
            f"accepted={counts['accepted_count']}",
            f"human_intervention={counts['human_intervention_count']}",
        ]
        return PackUsageSummary(
            schema_version=SCHEMA_VERSION,
            summary_id=f"pack-usage-summary-{_stamp()}-{_short_id(pack_ref)}",
            generated_at=_now(),
            pack_ref=pack_ref or (first.pack_ref if first else None),
            pack_id=pack_ref or (first.pack_id if first else None),
            pack_name=first.pack_name if first else None,
            version=first.version if first else None,
            namespace=first.namespace if first else None,
            counts=counts,
            rates=rates,
            medians=medians,
            recent_events=[event.event_id for event in events[:5]],
            source_refs=[_event_ref(root, event) for event in events[:20]],
            summary=summary_lines,
            warnings=warnings,
        )


class PackUsageSummaryStore:
    """pack usage summary 저장소."""

    def save(self, summary: PackUsageSummary, path: Path) -> Path:
        """summary를 저장하고 latest pointer도 갱신한다."""
        saved = _save_yaml(Path(path).resolve(), summary.to_dict())
        latest = saved.parent.parent / "latest.yaml"
        try:
            _save_yaml(latest, summary.to_dict())
        except Exception as exc:
            logger.warning("pack usage latest pointer save failed: %s", exc)
        return saved

    def load(self, path: Path) -> PackUsageSummary:
        """summary를 로드한다."""
        payload = _load_any(Path(path).resolve())
        return _summary_from_dict(payload)


def record_pack_usage_event(
    project_root: Path,
    *,
    event_kind: str,
    surface_kind: str,
    request: str | None = None,
    request_class: str | None = None,
    linked_session_id: str | None = None,
    linked_session_ref: str | None = None,
    linked_request_ref: str | None = None,
    linked_bridge_packet_ref: str | None = None,
    linked_bridge_reply_ref: str | None = None,
    linked_benchmark_replay_ref: str | None = None,
    linked_benchmark_result_ref: str | None = None,
    summary: str | None = None,
) -> Path | None:
    """현재 active pack 기준 usage event를 기록한다."""
    from engine.project_pack_activation import current_active_pack

    context = current_active_pack(project_root)
    if context is None:
        return None
    return record_pack_usage_from_context(
        project_root,
        context,
        event_kind=event_kind,
        surface_kind=surface_kind,
        request=request,
        request_class=request_class,
        linked_session_id=linked_session_id,
        linked_session_ref=linked_session_ref,
        linked_request_ref=linked_request_ref,
        linked_bridge_packet_ref=linked_bridge_packet_ref,
        linked_bridge_reply_ref=linked_bridge_reply_ref,
        linked_benchmark_replay_ref=linked_benchmark_replay_ref,
        linked_benchmark_result_ref=linked_benchmark_result_ref,
        summary=summary,
    )


def record_pack_usage_from_context(
    project_root: Path,
    context: Any,
    *,
    event_kind: str,
    surface_kind: str,
    request: str | None = None,
    request_class: str | None = None,
    linked_session_id: str | None = None,
    linked_session_ref: str | None = None,
    linked_request_ref: str | None = None,
    linked_bridge_packet_ref: str | None = None,
    linked_bridge_reply_ref: str | None = None,
    linked_benchmark_replay_ref: str | None = None,
    linked_benchmark_result_ref: str | None = None,
    summary: str | None = None,
) -> Path:
    """명시 context 기준 usage event를 기록한다."""
    root = Path(project_root).resolve()
    event = PackUsageEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"pack-event-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}-{_short_id(str(getattr(context, 'pack_ref', '')) + surface_kind + _now())}",
        created_at=_now(),
        pack_ref=str(getattr(context, "pack_ref", "") or getattr(context, "pack_id", "")),
        pack_id=str(getattr(context, "pack_id", "")),
        pack_name=str(getattr(context, "pack_name")) if getattr(context, "pack_name", None) is not None else None,
        pack_kind=str(getattr(context, "pack_kind")) if getattr(context, "pack_kind", None) is not None else None,
        version=str(getattr(context, "version")) if getattr(context, "version", None) is not None else None,
        namespace=str(getattr(context, "namespace")) if getattr(context, "namespace", None) is not None else None,
        event_kind=event_kind if event_kind in EVENT_KINDS else "used",
        surface_kind=surface_kind,
        request=request,
        request_class=request_class,
        linked_session_id=linked_session_id,
        linked_session_ref=linked_session_ref,
        linked_request_ref=linked_request_ref,
        linked_bridge_packet_ref=linked_bridge_packet_ref,
        linked_bridge_reply_ref=linked_bridge_reply_ref,
        linked_benchmark_replay_ref=linked_benchmark_replay_ref,
        linked_benchmark_result_ref=linked_benchmark_result_ref,
        active_team=str(getattr(context, "default_team")) if getattr(context, "default_team", None) is not None else None,
        active_template=str(getattr(context, "default_template")) if getattr(context, "default_template", None) is not None else None,
        active_workset=str(getattr(context, "default_workset")) if getattr(context, "default_workset", None) is not None else None,
        lane_id=str(getattr(context, "lane_id")) if getattr(context, "lane_id", None) is not None else None,
        summary=summary or f"{event_kind} on {surface_kind}",
    )
    return PackUsageEventStore().save_event(event, default_usage_event_path(root, event))


def safe_record_pack_usage_event(project_root: Path, **kwargs: Any) -> Path | None:
    """usage 기록 실패가 본 명령을 실패시키지 않도록 감싼다."""
    try:
        return record_pack_usage_event(project_root, **kwargs)
    except Exception as exc:
        logger.warning("pack usage event record failed: %s", exc)
        return None


def safe_record_pack_usage_from_context(project_root: Path, context: Any, **kwargs: Any) -> Path | None:
    """context 기반 usage 기록을 안전하게 시도한다."""
    try:
        return record_pack_usage_from_context(project_root, context, **kwargs)
    except Exception as exc:
        logger.warning("pack usage context event record failed: %s", exc)
        return None


def save_pack_outcome_links(project_root: Path, links: list[PackOutcomeLink]) -> list[str]:
    """outcome link들을 저장하고 상대 경로 목록을 반환한다."""
    root = Path(project_root).resolve()
    refs: list[str] = []
    for link in links:
        path = default_outcome_link_path(root, link)
        saved = _save_yaml(path, link.to_dict())
        refs.append(_relative(saved, root))
    return refs


def render_pack_usage(summary: PackUsageSummary) -> str:
    """pack usage summary를 사람이 읽기 좋게 렌더링한다."""
    counts = summary.counts
    lines = [
        "Pack Usage",
        "==================================================",
        "",
        "Pack:",
        f"  {summary.pack_id or 'all'}",
        "",
        "Used:",
        f"  {counts.get('used_count', 0)}",
        "",
        "Outcome linked:",
        f"  {counts.get('outcome_linked_count', 0)}",
        "",
        "Validated proposals:",
        f"  {counts.get('validated_proposal_count', 0)}",
        "",
        "Human intervention:",
        f"  {counts.get('human_intervention_count', 0)}",
        "",
        "Validation autonomy:",
        f"  {counts.get('validation_autonomy_count', 0)}",
    ]
    if summary.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in summary.warnings])
    return "\n".join(lines)


def render_pack_outcomes(summary: PackUsageSummary) -> str:
    """pack outcome attribution summary를 렌더링한다."""
    counts = summary.counts
    rates = summary.rates
    lines = [
        "Pack Outcomes",
        "==================================================",
        "",
        "Pack:",
        f"  {summary.pack_id or 'all'}",
        "",
        "Outcome-linked uses:",
        f"  {counts.get('outcome_linked_count', 0)}",
        "",
        "Validated proposal rate:",
        f"  {_format_rate(rates.get('validated_proposal_rate'))}",
        "",
        "Adoption rate:",
        f"  {_format_rate(rates.get('adoption_rate'))}",
        "",
        "Regression-free apply rate:",
        f"  {_format_rate(rates.get('regression_free_apply_rate'))}",
        "",
        "Human intervention rate:",
        f"  {_format_rate(rates.get('human_intervention_rate'))}",
        "",
        "Validation autonomy rate:",
        f"  {_format_rate(rates.get('validation_autonomy_rate'))}",
    ]
    median = summary.medians.get("time_to_validated_proposal_seconds")
    if median is not None:
        lines.extend(["", "Median time to validated proposal:", f"  {_format_seconds(median)}"])
    if summary.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in summary.warnings])
    return "\n".join(lines)


def render_pack_events(events: list[PackUsageEvent], *, limit: int = 20) -> str:
    """raw usage event 목록을 렌더링한다."""
    lines = [
        "Pack Events",
        "==================================================",
        "",
        "Recent:",
    ]
    selected = events[:limit]
    if not selected:
        lines.append("  none")
        return "\n".join(lines)
    for index, event in enumerate(selected, start=1):
        target = event.pack_id or "unknown"
        lines.append(f"  {index}. {event.event_kind} in {event.surface_kind} ({target})")
        if event.linked_session_id:
            lines.append(f"     session: {event.linked_session_id}")
        if event.linked_bridge_packet_ref:
            lines.append(f"     packet : {event.linked_bridge_packet_ref}")
    return "\n".join(lines)


def render_pack_usage_compact(summary: PackUsageSummary) -> str:
    """status/pack show에 붙일 compact usage summary를 만든다."""
    counts = summary.counts
    used = int(counts.get("used_count", 0) or 0)
    linked = int(counts.get("outcome_linked_count", 0) or 0)
    validated = int(counts.get("validated_proposal_count", 0) or 0)
    intervention = int(counts.get("human_intervention_count", 0) or 0)
    if used == 0 and linked == 0:
        return ""
    return "\n".join(
        [
            "",
            "Local usage:",
            f"  used      : {used}",
            f"  outcomes  : {validated} validated / {linked} linked uses",
            f"  intervention: {intervention}",
        ]
    )


def _event_from_dict(payload: dict[str, Any]) -> PackUsageEvent:
    """dict에서 PackUsageEvent를 복원한다."""
    return PackUsageEvent(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        event_id=str(payload.get("event_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        pack_ref=str(payload.get("pack_ref") or ""),
        pack_id=str(payload.get("pack_id") or ""),
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        pack_kind=str(payload.get("pack_kind")) if payload.get("pack_kind") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        event_kind=str(payload.get("event_kind") or "used"),
        surface_kind=str(payload.get("surface_kind") or "unknown"),
        request=str(payload.get("request")) if payload.get("request") is not None else None,
        request_class=str(payload.get("request_class")) if payload.get("request_class") is not None else None,
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_session_ref=str(payload.get("linked_session_ref")) if payload.get("linked_session_ref") is not None else None,
        linked_request_ref=str(payload.get("linked_request_ref")) if payload.get("linked_request_ref") is not None else None,
        linked_bridge_packet_ref=str(payload.get("linked_bridge_packet_ref")) if payload.get("linked_bridge_packet_ref") is not None else None,
        linked_bridge_reply_ref=str(payload.get("linked_bridge_reply_ref")) if payload.get("linked_bridge_reply_ref") is not None else None,
        linked_benchmark_replay_ref=str(payload.get("linked_benchmark_replay_ref")) if payload.get("linked_benchmark_replay_ref") is not None else None,
        linked_benchmark_result_ref=str(payload.get("linked_benchmark_result_ref")) if payload.get("linked_benchmark_result_ref") is not None else None,
        active_team=str(payload.get("active_team")) if payload.get("active_team") is not None else None,
        active_template=str(payload.get("active_template")) if payload.get("active_template") is not None else None,
        active_workset=str(payload.get("active_workset")) if payload.get("active_workset") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        summary=str(payload.get("summary") or ""),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _summary_from_dict(payload: dict[str, Any]) -> PackUsageSummary:
    """dict에서 PackUsageSummary를 복원한다."""
    return PackUsageSummary(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        summary_id=str(payload.get("summary_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        pack_ref=str(payload.get("pack_ref")) if payload.get("pack_ref") is not None else None,
        pack_id=str(payload.get("pack_id")) if payload.get("pack_id") is not None else None,
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        counts=dict(payload.get("counts", {})) if isinstance(payload.get("counts"), dict) else {},
        rates=dict(payload.get("rates", {})) if isinstance(payload.get("rates"), dict) else {},
        medians=dict(payload.get("medians", {})) if isinstance(payload.get("medians"), dict) else {},
        recent_events=[str(item) for item in payload.get("recent_events", []) if item],
        source_refs=[str(item) for item in payload.get("source_refs", []) if item],
        summary=[str(item) for item in payload.get("summary", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _event_ref(project_root: Path, event: PackUsageEvent) -> str | None:
    """event_id로 저장된 event path를 찾는다."""
    root = Path(project_root).resolve()
    events_dir = default_usage_events_dir(root)
    if not events_dir.exists():
        return None
    for path in events_dir.glob("event_*.yaml"):
        payload = _load_any(path)
        if str(payload.get("event_id") or "") == event.event_id:
            return _relative(path, root)
    return None


def _pack_matches(event: PackUsageEvent, ref: str) -> bool:
    """pack id/ref/namespace ref 필터를 검사한다."""
    raw = str(ref or "").strip()
    if not raw:
        return True
    candidates = {
        event.pack_id,
        event.pack_ref,
        f"{event.namespace}/{event.pack_id}" if event.namespace else event.pack_id,
        f"{event.namespace}/{event.pack_id}@{event.version}" if event.namespace and event.version else "",
        f"{event.pack_id}@{event.version}" if event.version else "",
    }
    return raw in {item for item in candidates if item}


def _link_from_session(project_root: Path, event: PackUsageEvent, event_ref: str | None, session_path: Path) -> PackOutcomeLink:
    """session artifact에서 outcome link를 만든다."""
    payload = _load_any(session_path)
    metrics_context = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
    results = metrics_context.get("results") if isinstance(metrics_context.get("results"), dict) else {}
    human = metrics_context.get("human_interventions") if isinstance(metrics_context.get("human_interventions"), dict) else {}
    milestones = metrics_context.get("milestones") if isinstance(metrics_context.get("milestones"), dict) else {}
    stage = str(payload.get("current_stage") or payload.get("status") or "")
    validated = _bool_or_none(results.get("validated_proposal"))
    if validated is None:
        validated = stage in {"patch_proposal_validated", "adopted"}
    adopted = _bool_or_none(results.get("adoption_succeeded"))
    if adopted is None:
        adopted = stage == "adopted"
    apply_passed = _bool_or_none(results.get("apply_tests_passed"))
    regression_free = _bool_or_none(results.get("regression_free_apply"))
    if regression_free is None:
        regression_free = True if adopted and apply_passed is True else False if adopted and apply_passed is False else None
    human_intervention = any(
        _bool_or_none(value) is True
        for key, value in human.items()
        if str(key) != "bridge_paste_fastpath"
    )
    validation_autonomy = True if validated and not human_intervention else False if validated else None
    duration = _duration_seconds(
        milestones.get("request_started_at") or payload.get("created_at"),
        milestones.get("proposal_validated_at") or payload.get("updated_at"),
    ) if validated else None
    return PackOutcomeLink(
        schema_version=SCHEMA_VERSION,
        link_id=f"pack-link-{_stamp()}-{_short_id(event.event_id)}",
        created_at=_now(),
        pack_ref=event.pack_ref,
        pack_id=event.pack_id,
        version=event.version,
        namespace=event.namespace,
        usage_event_ref=event_ref,
        outcome_source_kind="session",
        linked_session_id=str(payload.get("session_id") or event.linked_session_id or ""),
        linked_session_ref=_relative(session_path, project_root),
        linked_proposal_ref=_string_or_none((payload.get("artifacts") or {}).get("patch_proposal_path")) if isinstance(payload.get("artifacts"), dict) else None,
        linked_benchmark_result_ref=None,
        linked_replay_ref=None,
        validated_proposal=validated,
        adoption_succeeded=adopted,
        regression_free_apply=regression_free,
        human_intervention=human_intervention,
        validation_autonomy=validation_autonomy,
        duration_seconds=duration,
        summary="linked to session outcome",
    )


def _link_from_replay(project_root: Path, event: PackUsageEvent, event_ref: str | None, replay_path: Path) -> PackOutcomeLink:
    """benchmark replay artifact에서 outcome link를 만든다."""
    payload = _load_any(replay_path)
    snapshot = payload.get("metrics_snapshot") if isinstance(payload.get("metrics_snapshot"), dict) else {}
    return PackOutcomeLink(
        schema_version=SCHEMA_VERSION,
        link_id=f"pack-link-{_stamp()}-{_short_id(event.event_id)}",
        created_at=_now(),
        pack_ref=event.pack_ref,
        pack_id=event.pack_id,
        version=event.version,
        namespace=event.namespace,
        usage_event_ref=event_ref,
        outcome_source_kind="benchmark_replay",
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else event.linked_session_id,
        linked_session_ref=str(payload.get("linked_session_ref")) if payload.get("linked_session_ref") is not None else event.linked_session_ref,
        linked_proposal_ref=None,
        linked_benchmark_result_ref=event.linked_benchmark_result_ref,
        linked_replay_ref=_relative(replay_path, project_root),
        validated_proposal=_bool_or_none(snapshot.get("validated_proposal")),
        adoption_succeeded=_bool_or_none(snapshot.get("adoption_succeeded")),
        regression_free_apply=_bool_or_none(snapshot.get("regression_free_apply") or snapshot.get("apply_tests_passed")),
        human_intervention=_bool_or_none(snapshot.get("human_intervention")),
        validation_autonomy=_bool_or_none(snapshot.get("validation_autonomy")),
        duration_seconds=_float_or_none(snapshot.get("duration_seconds")),
        summary="linked to benchmark replay outcome",
    )


def _link_from_benchmark_result(project_root: Path, event: PackUsageEvent, event_ref: str | None, result_path: Path) -> PackOutcomeLink:
    """benchmark result artifact에서 outcome link를 만든다."""
    payload = _load_any(result_path)
    snapshot = payload.get("metrics_snapshot") if isinstance(payload.get("metrics_snapshot"), dict) else {}
    return PackOutcomeLink(
        schema_version=SCHEMA_VERSION,
        link_id=f"pack-link-{_stamp()}-{_short_id(event.event_id)}",
        created_at=_now(),
        pack_ref=event.pack_ref,
        pack_id=event.pack_id,
        version=event.version,
        namespace=event.namespace,
        usage_event_ref=event_ref,
        outcome_source_kind="benchmark_result",
        linked_session_id=event.linked_session_id,
        linked_session_ref=event.linked_session_ref,
        linked_proposal_ref=None,
        linked_benchmark_result_ref=_relative(result_path, project_root),
        linked_replay_ref=event.linked_benchmark_replay_ref,
        validated_proposal=_bool_or_none(snapshot.get("validated_proposal")),
        adoption_succeeded=_bool_or_none(snapshot.get("adoption_succeeded")),
        regression_free_apply=_bool_or_none(snapshot.get("regression_free_apply") or snapshot.get("apply_tests_passed")),
        human_intervention=_bool_or_none(snapshot.get("human_intervention")),
        validation_autonomy=_bool_or_none(snapshot.get("validation_autonomy")),
        duration_seconds=_float_or_none(snapshot.get("duration_seconds")),
        summary="linked to benchmark result outcome",
    )


def _partial_link(event: PackUsageEvent, event_ref: str | None, warning: str) -> PackOutcomeLink:
    """outcome source가 없는 partial link를 만든다."""
    return PackOutcomeLink(
        schema_version=SCHEMA_VERSION,
        link_id=f"pack-link-{_stamp()}-{_short_id(event.event_id)}",
        created_at=_now(),
        pack_ref=event.pack_ref,
        pack_id=event.pack_id,
        version=event.version,
        namespace=event.namespace,
        usage_event_ref=event_ref,
        outcome_source_kind="partial",
        linked_session_id=event.linked_session_id,
        linked_session_ref=event.linked_session_ref,
        linked_proposal_ref=None,
        linked_benchmark_result_ref=event.linked_benchmark_result_ref,
        linked_replay_ref=event.linked_benchmark_replay_ref,
        validated_proposal=None,
        adoption_succeeded=None,
        regression_free_apply=None,
        human_intervention=None,
        validation_autonomy=None,
        duration_seconds=None,
        summary="partial attribution",
        warnings=[warning],
    )


def _job_adoption_records(project_root: Path, pack_ref: str | None = None) -> list[dict[str, Any]]:
    """pack job adoption record를 usage summary용으로 읽는다."""
    records_dir = Path(project_root).resolve() / ".cambrian" / "packs" / "jobs" / "adoptions"
    if not records_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(records_dir.glob("adoption*.yaml")):
        payload = _load_any(path)
        if not payload:
            continue
        pack_id = str(payload.get("pack_id") or "")
        pack_ref_value = str(payload.get("pack_ref") or "")
        if pack_ref and pack_ref not in {pack_id, pack_ref_value}:
            continue
        records.append(payload)
    return records


def _job_apply_records(project_root: Path, pack_ref: str | None = None) -> list[dict[str, Any]]:
    """pack job apply record를 usage summary용으로 읽는다."""
    records_dir = Path(project_root).resolve() / ".cambrian" / "packs" / "jobs" / "apply_records"
    if not records_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(records_dir.glob("apply*.yaml")):
        payload = _load_any(path)
        if not payload:
            continue
        pack_id = str(payload.get("pack_id") or "")
        pack_ref_value = str(payload.get("pack_ref") or "")
        if pack_ref and pack_ref not in {pack_id, pack_ref_value}:
            continue
        records.append(payload)
    return records


def _rate(numerator: int, denominator: int) -> float | None:
    """0 분모를 null로 처리하는 rate 계산."""
    if denominator <= 0:
        return None
    return numerator / denominator


def _format_rate(value: Any) -> str:
    """rate를 사람이 읽기 좋게 포맷한다."""
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def _format_seconds(value: Any) -> str:
    """초 단위 값을 사람이 읽기 좋게 포맷한다."""
    if value is None:
        return "n/a"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds / 60:.1f}m"


def _float_or_none(value: Any) -> float | None:
    """float 변환을 안전하게 수행한다."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    """빈 문자열을 None으로 정규화한다."""
    if value in (None, ""):
        return None
    return str(value)
