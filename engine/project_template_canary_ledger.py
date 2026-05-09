"""canary template 노출/선택/결과를 로컬 ledger로 기록한다."""

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

from engine.project_template_canary import active_canary_stage
from engine.project_template_qualification_decisions import LanePlaybookStore, lane_playbook_path
from engine.project_templates import HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
EVENT_KINDS = {"surfaced", "selected", "skipped", "bootstrapped", "applied", "replayed", "validated", "blocked"}
SURFACE_KINDS = {"recommend", "board", "bootstrap", "manual_apply", "replay"}


class CanaryLedgerBlockedError(RuntimeError):
    """ledger를 만들 수 있는 canary 대상이 없을 때 발생한다."""


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명용 UTC timestamp를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 식별자를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str | None, fallback: str = "item") -> str:
    """문자열을 파일명에 안전한 slug로 변환한다."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _atomic_write_text(path: Path, content: str) -> None:
    """YAML artifact를 원자적으로 저장한다."""
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
    """dict payload를 YAML로 저장한다."""
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML artifact를 안전하게 읽는다."""
    if not Path(path).exists():
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("canary ledger artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """프로젝트 root 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    """0 나눗셈 없이 비율을 계산한다."""
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def canary_events_dir(project_root: Path) -> Path:
    """canary event 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "canary_events"


def canary_ledgers_dir(project_root: Path) -> Path:
    """canary ledger summary 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "canary_ledgers"


def default_canary_event_path(project_root: Path, event: "CanaryExposureEvent") -> Path:
    """canary event 기본 저장 경로."""
    return canary_events_dir(project_root) / f"event_{_stamp()}_{_slug(event.event_kind)}_{_short_id()}.yaml"


def default_canary_ledger_path(project_root: Path, summary: "CanaryLedgerSummary") -> Path:
    """canary ledger 기본 저장 경로."""
    return canary_ledgers_dir(project_root) / f"ledger_{_slug(summary.template_name)}_{_stamp()}_{_short_id()}.yaml"


def latest_canary_ledger_path(project_root: Path) -> Path:
    """latest canary ledger pointer 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "latest_canary_ledger.yaml"


@dataclass
class CanaryExposureEvent:
    """canary가 surface/selection/replay에서 만든 단일 evidence event."""

    schema_version: str
    event_id: str
    created_at: str
    template_name: str
    template_id: str | None
    lane_id: str | None
    lane_label: str | None
    stable_default_template_name: str | None
    event_kind: str
    surface_kind: str
    selection_result: str | None
    request: str | None
    workset_name: str | None
    mode: str | None
    source_ref: str | None
    linked_bootstrap_choice_ref: str | None
    linked_replay_ref: str | None
    linked_metrics_ref: str | None
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class CanaryLedgerSummary:
    """canary events 집계 결과."""

    schema_version: str
    report_id: str
    generated_at: str
    template_name: str
    template_id: str | None
    lane_id: str | None
    lane_label: str | None
    stable_default_template_name: str | None
    counts: dict[str, int]
    ratios: dict[str, float | None]
    summary: list[str]
    source_refs: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class CanaryEventStore:
    """canary exposure event 저장소."""

    def save_event(self, event: CanaryExposureEvent, path: Path) -> Path:
        """event를 저장한다."""
        return _save_yaml(Path(path).resolve(), event.to_dict())

    def load_event(self, path: Path) -> CanaryExposureEvent:
        """event를 읽는다."""
        return _event_from_dict(_load_yaml(Path(path).resolve()))

    def list_events(self, events_dir: Path, template_name: str | None = None) -> list[CanaryExposureEvent]:
        """저장된 canary event 목록을 최신순으로 반환한다."""
        target = Path(events_dir).resolve()
        if not target.exists():
            return []
        events: list[CanaryExposureEvent] = []
        for path in target.glob("event_*.yaml"):
            payload = _load_yaml(path)
            if not payload:
                continue
            event = _event_from_dict(payload)
            if template_name and _slug(event.template_name) != _slug(template_name):
                continue
            events.append(event)
        return sorted(events, key=lambda event: event.created_at, reverse=True)


class CanaryLedgerBuilder:
    """canary event들을 집계한다."""

    def build(self, project_root: Path, template_name: str | None = None) -> CanaryLedgerSummary:
        """active canary 또는 명시 template의 ledger summary를 만든다."""
        root = Path(project_root).resolve()
        stage = active_canary_stage(root)
        target_name = str(template_name or (stage.candidate_template_name if stage else "")).strip()
        if not target_name:
            raise CanaryLedgerBlockedError(
                "No active canary template found. Run: cambrian template qualify-stage <qualification>"
            )
        playbook = _load_playbook(root)
        template_id = _template_id(root, target_name)
        events = CanaryEventStore().list_events(canary_events_dir(root), target_name)
        counts = _counts(events)
        ratios = {
            "selection_rate": _ratio(counts["selected_count"], counts["surfaced_count"]),
            "replay_validated_rate": _ratio(counts["replay_validated_count"], counts["replay_count"]),
            "selected_then_validated_rate": None,
        }
        warnings: list[str] = []
        if counts["selected_count"] and counts["replay_validated_count"]:
            ratios["selected_then_validated_rate"] = _ratio(
                counts["replay_validated_count"],
                counts["selected_count"],
            )
        else:
            warnings.append("selected_then_validated_rate is not linked strongly enough yet")
        summary = _summary(counts, ratios)
        source_refs = _dedupe([event.source_ref or event.linked_replay_ref or event.event_id for event in events])
        return CanaryLedgerSummary(
            schema_version=SCHEMA_VERSION,
            report_id=f"canary-ledger-{_slug(target_name)}-{_short_id()}",
            generated_at=_now(),
            template_name=target_name,
            template_id=template_id,
            lane_id=getattr(playbook, "lane_id", None),
            lane_label=getattr(playbook, "label", None),
            stable_default_template_name=getattr(playbook, "default_template_name", None),
            counts=counts,
            ratios=ratios,
            summary=summary,
            source_refs=source_refs[:40],
            warnings=_dedupe(warnings),
            errors=[],
        )


class CanaryLedgerStore:
    """canary ledger summary 저장소."""

    def save(self, summary: CanaryLedgerSummary, path: Path) -> Path:
        """summary를 저장하고 latest pointer를 갱신한다."""
        saved = _save_yaml(Path(path).resolve(), summary.to_dict())
        project_root = saved.parents[3] if len(saved.parents) > 3 else saved.parent
        _save_yaml(latest_canary_ledger_path(project_root), summary.to_dict())
        return saved

    def load(self, path: Path) -> CanaryLedgerSummary:
        """summary를 읽는다."""
        return _ledger_from_dict(_load_yaml(Path(path).resolve()))


def record_canary_recommendation_surface(
    project_root: Path,
    report: Any,
    *,
    surface_kind: str = "recommend",
    source_ref: str | None = None,
) -> list[CanaryExposureEvent]:
    """recommend/board 결과에 active canary가 보이면 surfaced event를 남긴다."""
    root = Path(project_root).resolve()
    context = _active_context(root)
    if context is None:
        return []
    candidate_names = _candidate_names_from_surface(report)
    if not any(_slug(name) == _slug(context["template_name"]) for name in candidate_names):
        return []
    event = _build_event(
        root,
        context,
        event_kind="surfaced",
        surface_kind=surface_kind,
        selection_result=None,
        request=getattr(report, "request", None),
        workset_name=None,
        mode=getattr(report, "mode", None),
        source_ref=source_ref,
        linked_bootstrap_choice_ref=None,
        linked_replay_ref=None,
        linked_metrics_ref=None,
        summary=f"canary surfaced in template {surface_kind} shortlist",
    )
    _save_event(root, event)
    return [event]


def record_canary_bootstrap_choice(project_root: Path, choice: Any, *, source_ref: str | None = None) -> list[CanaryExposureEvent]:
    """bootstrap choice에서 canary surfaced/selected/skipped event를 남긴다."""
    root = Path(project_root).resolve()
    context = _active_context(root)
    if context is None:
        return []
    considered = [
        str(value)
        for value in [
            *list(getattr(choice, "considered_templates", []) or []),
            *list(getattr(choice, "available_templates", []) or []),
        ]
        if value
    ]
    if not any(_slug(value) == _slug(context["template_name"]) for value in considered):
        return []
    choice_ref = source_ref or ".cambrian/templates/bootstrap_choice.yaml"
    events = [
        _build_event(
            root,
            context,
            event_kind="surfaced",
            surface_kind="bootstrap",
            selection_result=None,
            request=None,
            workset_name=None,
            mode=None,
            source_ref=choice_ref,
            linked_bootstrap_choice_ref=choice_ref,
            linked_replay_ref=None,
            linked_metrics_ref=None,
            summary="canary surfaced in bootstrap shortlist",
        )
    ]
    selected = str(getattr(choice, "selected_template_name", "") or "").strip()
    if _slug(selected) == _slug(context["template_name"]):
        events.append(
            _build_event(
                root,
                context,
                event_kind="selected",
                surface_kind="bootstrap",
                selection_result="canary",
                request=None,
                workset_name=None,
                mode=None,
                source_ref=choice_ref,
                linked_bootstrap_choice_ref=choice_ref,
                linked_replay_ref=None,
                linked_metrics_ref=None,
                summary="canary selected during bootstrap choice",
            )
        )
    else:
        events.append(
            _build_event(
                root,
                context,
                event_kind="skipped",
                surface_kind="bootstrap",
                selection_result=_selection_result(selected, context["stable_default_template_name"]),
                request=None,
                workset_name=None,
                mode=None,
                source_ref=choice_ref,
                linked_bootstrap_choice_ref=choice_ref,
                linked_replay_ref=None,
                linked_metrics_ref=None,
                summary="canary skipped during bootstrap choice",
            )
        )
    for event in events:
        _save_event(root, event)
    return events


def record_canary_template_bootstrap(project_root: Path, template_name: str, *, source_ref: str | None = None) -> list[CanaryExposureEvent]:
    """canary가 실제 bootstrap에 사용되면 bootstrapped event를 남긴다."""
    root = Path(project_root).resolve()
    context = _active_context(root)
    if context is None or _slug(template_name) != _slug(context["template_name"]):
        return []
    event = _build_event(
        root,
        context,
        event_kind="bootstrapped",
        surface_kind="bootstrap",
        selection_result="canary",
        request=None,
        workset_name=None,
        mode=None,
        source_ref=source_ref or ".cambrian/templates/bootstrap_record.yaml",
        linked_bootstrap_choice_ref=".cambrian/templates/bootstrap_choice.yaml",
        linked_replay_ref=None,
        linked_metrics_ref=None,
        summary="canary used for template bootstrap",
    )
    _save_event(root, event)
    return [event]


def record_canary_template_apply(project_root: Path, template_name: str, *, source_ref: str | None = None) -> list[CanaryExposureEvent]:
    """canary가 명시적으로 apply되면 applied event를 남긴다."""
    root = Path(project_root).resolve()
    context = _active_context(root)
    if context is None or _slug(template_name) != _slug(context["template_name"]):
        return []
    event = _build_event(
        root,
        context,
        event_kind="applied",
        surface_kind="manual_apply",
        selection_result="canary",
        request=None,
        workset_name=None,
        mode=None,
        source_ref=source_ref or ".cambrian/templates/current_template.yaml",
        linked_bootstrap_choice_ref=None,
        linked_replay_ref=None,
        linked_metrics_ref=None,
        summary="canary explicitly applied as current template",
    )
    _save_event(root, event)
    return [event]


def record_canary_replay_outcome(project_root: Path, replay_report: Any, *, source_ref: str | None = None) -> list[CanaryExposureEvent]:
    """canary template override replay 결과를 ledger event로 남긴다."""
    root = Path(project_root).resolve()
    context = _active_context(root)
    if context is None:
        return []
    template_context = _template_context_from_replay(replay_report)
    template_name = str(template_context.get("template_name") or "").strip()
    if _slug(template_name) != _slug(context["template_name"]):
        return []
    workset_name = str(getattr(replay_report, "workset_name", "") or "").strip() or None
    mode = str(getattr(replay_report, "mode", "") or "").strip() or None
    replay_ref = source_ref
    events = [
        _build_event(
            root,
            context,
            event_kind="replayed",
            surface_kind="replay",
            selection_result="canary",
            request=None,
            workset_name=workset_name,
            mode=mode,
            source_ref=source_ref,
            linked_bootstrap_choice_ref=None,
            linked_replay_ref=replay_ref,
            linked_metrics_ref=None,
            summary="canary replayed with template override",
        )
    ]
    validated = _replay_validated(replay_report)
    blocked = _replay_blocked(replay_report)
    if validated:
        events.append(
            _build_event(
                root,
                context,
                event_kind="validated",
                surface_kind="replay",
                selection_result="canary",
                request=None,
                workset_name=workset_name,
                mode=mode,
                source_ref=source_ref,
                linked_bootstrap_choice_ref=None,
                linked_replay_ref=replay_ref,
                linked_metrics_ref=None,
                summary="canary replay reached proposal_validated",
            )
        )
    elif blocked:
        events.append(
            _build_event(
                root,
                context,
                event_kind="blocked",
                surface_kind="replay",
                selection_result="canary",
                request=None,
                workset_name=workset_name,
                mode=mode,
                source_ref=source_ref,
                linked_bootstrap_choice_ref=None,
                linked_replay_ref=replay_ref,
                linked_metrics_ref=None,
                summary="canary replay stopped before validation",
            )
        )
    for event in events:
        _save_event(root, event)
    return events


def load_canary_ledger_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """status/show에서 쓰는 compact ledger summary를 만든다."""
    try:
        summary = CanaryLedgerBuilder().build(project_root, template_name=template_name)
    except CanaryLedgerBlockedError:
        return {}
    except Exception as exc:
        logger.warning("canary ledger summary load failed: %s", exc)
        return {"warnings": [f"canary ledger summary load failed: {exc}"]}
    if not any(int(value or 0) for value in summary.counts.values()):
        return {}
    return {
        "template_name": summary.template_name,
        "stable_default_template_name": summary.stable_default_template_name,
        "counts": dict(summary.counts),
        "ratios": dict(summary.ratios),
        "summary": list(summary.summary[:3]),
    }


def render_canary_ledger(summary: CanaryLedgerSummary, saved_path: str | None = None) -> str:
    """canary ledger를 사람이 읽기 좋게 렌더링한다."""
    counts = summary.counts
    ratios = summary.ratios
    lines = [
        "Canary Ledger",
        "==================================================",
        "",
        "Template:",
        f"  {summary.template_name}",
        "",
        "Stable default:",
        f"  {summary.stable_default_template_name or 'none'}",
        "",
        "Surfaced:",
        f"  {counts.get('surfaced_count', 0)}",
        "Selected:",
        f"  {counts.get('selected_count', 0)}",
        "Skipped:",
        f"  {counts.get('skipped_count', 0)}",
        "Replayed:",
        f"  {counts.get('replay_count', 0)}",
        "Replay validated:",
        f"  {counts.get('replay_validated_count', 0)}",
        "",
        "Selection rate:",
        f"  {_pct(ratios.get('selection_rate'))}",
        "",
        "Replay validated rate:",
        f"  {_pct(ratios.get('replay_validated_rate'))}",
    ]
    if summary.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in summary.summary[:5]])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if summary.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in summary.warnings[:5]])
    return "\n".join(lines)


def render_canary_events(events: list[CanaryExposureEvent], *, limit: int = 20) -> str:
    """canary event 목록을 렌더링한다."""
    lines = [
        "Canary Events",
        "==================================================",
        "",
        "Recent:",
    ]
    if not events:
        lines.append("  none")
        return "\n".join(lines)
    for index, event in enumerate(events[: max(1, int(limit or 20))], start=1):
        lines.append(f"  {index}. {event.event_kind} in {event.surface_kind}: {event.summary}")
    return "\n".join(lines)


def render_canary_ledger_summary(summary: dict[str, Any]) -> str:
    """compact canary ledger summary를 렌더링한다."""
    if not summary:
        return "Canary ledger:\n  none"
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    return "\n".join([
        "Canary ledger:",
        f"  surfaced {int(counts.get('surfaced_count', 0) or 0)}",
        f"  selected {int(counts.get('selected_count', 0) or 0)}",
        f"  validated {int(counts.get('replay_validated_count', 0) or 0)}",
    ])


def _save_event(root: Path, event: CanaryExposureEvent) -> Path:
    return CanaryEventStore().save_event(event, default_canary_event_path(root, event))


def _active_context(root: Path) -> dict[str, Any] | None:
    stage = active_canary_stage(root)
    if stage is None:
        return None
    playbook = _load_playbook(root)
    return {
        "template_name": stage.candidate_template_name,
        "template_id": stage.candidate_template_id or _template_id(root, stage.candidate_template_name),
        "lane_id": stage.lane_id or getattr(playbook, "lane_id", None),
        "lane_label": stage.lane_label or getattr(playbook, "label", None),
        "stable_default_template_name": getattr(playbook, "default_template_name", None),
    }


def _load_playbook(root: Path) -> Any:
    try:
        return LanePlaybookStore().load(lane_playbook_path(root))
    except Exception as exc:
        logger.warning("canary ledger lane playbook load failed: %s", exc)
        return type(
            "EmptyPlaybook",
            (),
            {
                "lane_id": None,
                "label": None,
                "default_template_name": None,
            },
        )()


def _template_id(root: Path, template_name: str | None) -> str | None:
    if not template_name:
        return None
    try:
        model = HarnessTemplateStore().load(default_templates_path(root))
        template = HarnessTemplateStore().find(model, template_name)
        return template.template_id
    except Exception as exc:
        logger.warning("canary ledger template lookup failed: %s", exc)
        return None


def _build_event(
    root: Path,
    context: dict[str, Any],
    *,
    event_kind: str,
    surface_kind: str,
    selection_result: str | None,
    request: str | None,
    workset_name: str | None,
    mode: str | None,
    source_ref: str | None,
    linked_bootstrap_choice_ref: str | None,
    linked_replay_ref: str | None,
    linked_metrics_ref: str | None,
    summary: str,
) -> CanaryExposureEvent:
    if event_kind not in EVENT_KINDS:
        raise ValueError(f"unsupported canary event kind: {event_kind}")
    if surface_kind not in SURFACE_KINDS:
        raise ValueError(f"unsupported canary surface kind: {surface_kind}")
    return CanaryExposureEvent(
        schema_version=SCHEMA_VERSION,
        event_id=f"canary-event-{event_kind}-{_short_id()}",
        created_at=_now(),
        template_name=str(context.get("template_name") or ""),
        template_id=str(context.get("template_id")) if context.get("template_id") is not None else None,
        lane_id=str(context.get("lane_id")) if context.get("lane_id") is not None else None,
        lane_label=str(context.get("lane_label")) if context.get("lane_label") is not None else None,
        stable_default_template_name=(
            str(context.get("stable_default_template_name"))
            if context.get("stable_default_template_name") is not None
            else None
        ),
        event_kind=event_kind,
        surface_kind=surface_kind,
        selection_result=selection_result,
        request=request,
        workset_name=workset_name,
        mode=mode,
        source_ref=source_ref,
        linked_bootstrap_choice_ref=linked_bootstrap_choice_ref,
        linked_replay_ref=linked_replay_ref,
        linked_metrics_ref=linked_metrics_ref,
        summary=summary,
        warnings=[],
        errors=[],
    )


def _candidate_names_from_surface(report: Any) -> list[str]:
    names: list[str] = []
    if hasattr(report, "candidates"):
        for candidate in getattr(report, "candidates", []) or []:
            name = getattr(candidate, "name", None) or getattr(candidate, "template_name", None)
            if name:
                names.append(str(name))
    if hasattr(report, "entries"):
        for entry in getattr(report, "entries", []) or []:
            name = getattr(entry, "template_name", None) or getattr(entry, "name", None)
            if name:
                names.append(str(name))
    return _dedupe(names)


def _selection_result(selected: str | None, stable_default: str | None) -> str:
    if not selected:
        return "none"
    if stable_default and _slug(selected) == _slug(stable_default):
        return "stable_default"
    return "other"


def _template_context_from_replay(replay_report: Any) -> dict[str, Any]:
    summary = getattr(replay_report, "summary", None)
    if isinstance(summary, dict) and isinstance(summary.get("template_context"), dict):
        return dict(summary.get("template_context") or {})
    payload = replay_report.to_dict() if hasattr(replay_report, "to_dict") else {}
    if isinstance(payload.get("summary"), dict) and isinstance(payload["summary"].get("template_context"), dict):
        return dict(payload["summary"].get("template_context") or {})
    return {}


def _replay_validated(replay_report: Any) -> bool:
    summary = getattr(replay_report, "summary", None)
    if isinstance(summary, dict):
        rate = summary.get("validated_proposal_rate")
        try:
            if rate is not None and float(rate) > 0:
                return True
        except (TypeError, ValueError):
            pass
    entries = getattr(replay_report, "entries", []) or []
    return any(bool(getattr(entry, "validated_proposal", False)) for entry in entries)


def _replay_blocked(replay_report: Any) -> bool:
    entries = getattr(replay_report, "entries", []) or []
    if entries:
        return any(str(getattr(entry, "status", "")) in {"blocked", "failed", "partial"} for entry in entries)
    return False


def _counts(events: list[CanaryExposureEvent]) -> dict[str, int]:
    selected_bootstrap_count = 0
    bootstrapped_count = 0
    counts = {
        "surfaced_count": 0,
        "recommend_surfaced_count": 0,
        "board_surfaced_count": 0,
        "bootstrap_surfaced_count": 0,
        "selected_count": 0,
        "skipped_count": 0,
        "bootstrap_count": 0,
        "apply_count": 0,
        "replay_count": 0,
        "replay_validated_count": 0,
        "replay_blocked_count": 0,
    }
    for event in events:
        if event.event_kind == "surfaced":
            counts["surfaced_count"] += 1
            if event.surface_kind == "recommend":
                counts["recommend_surfaced_count"] += 1
            elif event.surface_kind == "board":
                counts["board_surfaced_count"] += 1
            elif event.surface_kind == "bootstrap":
                counts["bootstrap_surfaced_count"] += 1
        elif event.event_kind == "selected":
            counts["selected_count"] += 1
            if event.surface_kind == "bootstrap":
                selected_bootstrap_count += 1
        elif event.event_kind == "skipped":
            counts["skipped_count"] += 1
        elif event.event_kind == "bootstrapped":
            bootstrapped_count += 1
        elif event.event_kind == "applied":
            counts["apply_count"] += 1
        elif event.event_kind == "replayed":
            counts["replay_count"] += 1
        elif event.event_kind == "validated":
            counts["replay_validated_count"] += 1
        elif event.event_kind == "blocked" and event.surface_kind == "replay":
            counts["replay_blocked_count"] += 1
    counts["bootstrap_count"] = max(selected_bootstrap_count, bootstrapped_count)
    return counts


def _summary(counts: dict[str, int], ratios: dict[str, float | None]) -> list[str]:
    lines: list[str] = []
    if counts["surfaced_count"]:
        lines.append("the canary is being surfaced in local product flows")
    else:
        lines.append("the canary has not been surfaced yet")
    if counts["selected_count"]:
        lines.append("the canary has at least one explicit selection")
    elif counts["surfaced_count"]:
        lines.append("the canary has been surfaced but not selected yet")
    if counts["replay_validated_count"]:
        lines.append("the canary has replay validation evidence")
    elif counts["replay_count"]:
        lines.append("the canary has replay exposure but no validation yet")
    if ratios.get("selection_rate") is not None:
        lines.append(f"selection rate is {_pct(ratios.get('selection_rate'))}")
    return lines[:5]


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _event_from_dict(payload: dict[str, Any]) -> CanaryExposureEvent:
    return CanaryExposureEvent(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        event_id=str(payload.get("event_id") or f"canary-event-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        template_name=str(payload.get("template_name") or ""),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        stable_default_template_name=(
            str(payload.get("stable_default_template_name"))
            if payload.get("stable_default_template_name") is not None
            else None
        ),
        event_kind=str(payload.get("event_kind") or "surfaced"),
        surface_kind=str(payload.get("surface_kind") or "recommend"),
        selection_result=str(payload.get("selection_result")) if payload.get("selection_result") is not None else None,
        request=str(payload.get("request")) if payload.get("request") is not None else None,
        workset_name=str(payload.get("workset_name")) if payload.get("workset_name") is not None else None,
        mode=str(payload.get("mode")) if payload.get("mode") is not None else None,
        source_ref=str(payload.get("source_ref")) if payload.get("source_ref") is not None else None,
        linked_bootstrap_choice_ref=(
            str(payload.get("linked_bootstrap_choice_ref"))
            if payload.get("linked_bootstrap_choice_ref") is not None
            else None
        ),
        linked_replay_ref=str(payload.get("linked_replay_ref")) if payload.get("linked_replay_ref") is not None else None,
        linked_metrics_ref=str(payload.get("linked_metrics_ref")) if payload.get("linked_metrics_ref") is not None else None,
        summary=str(payload.get("summary") or ""),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _ledger_from_dict(payload: dict[str, Any]) -> CanaryLedgerSummary:
    return CanaryLedgerSummary(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        report_id=str(payload.get("report_id") or f"canary-ledger-{_short_id()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        template_name=str(payload.get("template_name") or ""),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        stable_default_template_name=(
            str(payload.get("stable_default_template_name"))
            if payload.get("stable_default_template_name") is not None
            else None
        ),
        counts={str(key): int(value or 0) for key, value in dict(payload.get("counts", {})).items()},
        ratios={
            str(key): (float(value) if value is not None else None)
            for key, value in dict(payload.get("ratios", {})).items()
        },
        summary=[str(item) for item in payload.get("summary", []) if item],
        source_refs=[str(item) for item in payload.get("source_refs", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
