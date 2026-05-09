"""Pack retrospective 신호를 다음 버전 개선 queue로 변환한다."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_install import (
    SCHEMA_VERSION,
    _as_dict,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)
from engine.project_pack_retrospective import (
    PackImprovementSuggestion,
    PackRetrospectiveSummary,
    latest_pack_retro_summary,
)

logger = logging.getLogger(__name__)


IMPROVEMENT_KINDS = {
    "strengthen_context_hints",
    "improve_response_contract",
    "improve_validation_support",
    "update_known_limits",
    "add_benchmark_case",
    "review_team_fit",
    "review_template_fit",
    "create_pack_derivative",
    "update_pack_docs",
    "improve_first_job_guide",
}

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class PackImprovementQueueItem:
    """Pack 개선 후보 하나를 표현한다."""

    schema_version: str
    item_id: str
    created_at: str
    updated_at: str | None
    pack_ref: str
    pack_id: str
    pack_name: str | None
    namespace: str | None
    version: str | None
    kind: str
    status: str
    priority: str
    confidence: float
    title: str
    summary: str
    reason: str
    affected_metrics: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    source_signal_kinds: list[str] = field(default_factory=list)
    next_commands: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML/JSON 직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackImprovementQueue:
    """Pack 단위 improvement queue."""

    schema_version: str
    queue_id: str
    generated_at: str
    pack_ref: str | None
    pack_id: str | None
    pack_name: str | None
    namespace: str | None
    version: str | None
    items: list[PackImprovementQueueItem] = field(default_factory=list)
    top_item_id: str | None = None
    source_refs: dict[str, Any] = field(default_factory=dict)
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML/JSON 직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["items"] = [item.to_dict() for item in self.items]
        return payload


@dataclass
class PackImprovementDecision:
    """Improvement queue item에 대한 사람의 decision."""

    schema_version: str
    decision_id: str
    created_at: str
    item_id: str
    pack_id: str | None
    status: str
    resolution: str | None
    source_item_ref: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML/JSON 직렬화용 dict로 변환한다."""
        return asdict(self)


class PackImprovementQueueBuilder:
    """Retrospective/proof/usage evidence에서 improvement queue를 만든다."""

    def build(self, project_root: Path, pack_ref: str | None = None) -> PackImprovementQueue:
        root = Path(project_root).resolve()
        summary, summary_ref = _latest_summary_with_ref(root, pack_ref)
        target_pack = _target_pack_ref(root, pack_ref, summary)
        canonical_pack = _canonical_pack_id(target_pack, summary)
        usage = _usage_summary(root, canonical_pack)
        proof = _proof_card(root, canonical_pack)
        release_report, release_ref = _latest_release_report(root, canonical_pack)
        source_refs = {
            "retrospective_summary_ref": summary_ref,
            "proof_ref": getattr(proof, "proof_id", None),
            "usage_summary_ref": getattr(usage, "summary_id", None),
            "release_ref": release_ref,
        }
        decisions = PackImprovementDecisionStore().latest_status_by_item(default_pack_improvement_decisions_path(root))
        items = _items_from_sources(root, canonical_pack, summary, usage, proof, release_report, source_refs, decisions)
        top_item = _top_item(items)
        warnings: list[str] = []
        if summary is None:
            warnings.append("retrospective summary가 없어 queue evidence가 제한적입니다.")
        if not items:
            warnings.append("actionable improvement evidence가 아직 부족합니다.")
        return PackImprovementQueue(
            schema_version=SCHEMA_VERSION,
            queue_id=f"improvement-queue-{_slug(canonical_pack or 'all')}-{_stamp()}",
            generated_at=_now(),
            pack_ref=target_pack or canonical_pack,
            pack_id=canonical_pack,
            pack_name=getattr(summary, "pack_name", None) if summary else None,
            namespace=getattr(summary, "namespace", None) if summary else None,
            version=getattr(summary, "version", None) if summary else None,
            items=items,
            top_item_id=top_item.item_id if top_item else None,
            source_refs={key: value for key, value in source_refs.items() if value},
            summary=_queue_summary(canonical_pack, items, top_item),
            warnings=warnings,
            errors=[],
        )


class PackImprovementStore:
    """Improvement queue와 item 저장소."""

    def save_queue(self, queue: PackImprovementQueue, path: Path) -> Path:
        """queue와 per-item artifact를 저장한다."""
        target = _save_yaml(Path(path).resolve(), queue.to_dict())
        root = _project_root_from_improvements_path(target)
        per_pack = default_pack_improvement_queues_dir(root) / f"queue_{_slug(queue.pack_id or queue.pack_ref or 'all')}.yaml"
        try:
            _save_yaml(per_pack, queue.to_dict())
        except Exception as exc:  # noqa: BLE001 - queue 본문 저장은 이미 성공했으므로 경고만 남긴다.
            logger.warning("pack improvement per-pack queue save failed: %s", exc)
        for item in queue.items:
            self.save_item(item, default_pack_improvement_item_path(root, item))
        return target

    def load_queue(self, path: Path) -> PackImprovementQueue:
        """저장된 queue를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack improvement queue not found: {path}")
        return _queue_from_dict(payload)

    def save_item(self, item: PackImprovementQueueItem, path: Path) -> Path:
        """개별 item을 저장한다."""
        return _save_yaml(Path(path).resolve(), item.to_dict())

    def load_item(self, path: Path) -> PackImprovementQueueItem:
        """개별 item을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack improvement item not found: {path}")
        return _item_from_dict(payload)

    def list_items(self, items_dir: Path, pack_id: str | None = None, status: str | None = None) -> list[PackImprovementQueueItem]:
        """저장된 item 목록을 반환한다."""
        target = Path(items_dir).resolve()
        if not target.exists():
            return []
        items: list[PackImprovementQueueItem] = []
        for path in sorted(target.glob("item_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                item = self.load_item(path)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                logger.warning("pack improvement item load skipped: %s (%s)", path, exc)
                continue
            if pack_id and not _pack_matches(item.pack_id, pack_id):
                continue
            if status and item.status != status:
                continue
            items.append(item)
        return items


class PackImprovementDecisionStore:
    """Improvement decision ledger."""

    def add_decision(self, path: Path, decision: PackImprovementDecision) -> Path:
        """decision을 append-only YAML ledger에 추가한다."""
        target = Path(path).resolve()
        payload = _load_yaml(target)
        decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
        decisions.append(decision.to_dict())
        return _save_yaml(target, {"schema_version": SCHEMA_VERSION, "decisions": decisions})

    def list_decisions(self, path: Path) -> list[PackImprovementDecision]:
        """decision 목록을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        raw = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
        return [_decision_from_dict(item) for item in raw if isinstance(item, dict)]

    def latest_status_by_item(self, path: Path) -> dict[str, str]:
        """item_id별 최신 decision 상태를 반환한다."""
        statuses: dict[str, str] = {}
        for decision in self.list_decisions(path):
            statuses[decision.item_id] = decision.status
        return statuses


def default_pack_improvements_root(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "packs" / "improvements"


def default_pack_improvement_queue_path(project_root: Path) -> Path:
    return default_pack_improvements_root(project_root) / "queue.yaml"


def default_pack_improvement_queues_dir(project_root: Path) -> Path:
    return default_pack_improvements_root(project_root) / "queues"


def default_pack_improvement_items_dir(project_root: Path) -> Path:
    return default_pack_improvements_root(project_root) / "items"


def default_pack_improvement_decisions_path(project_root: Path) -> Path:
    return default_pack_improvements_root(project_root) / "decisions.yaml"


def default_pack_improvement_item_path(project_root: Path, item: PackImprovementQueueItem) -> Path:
    return default_pack_improvement_items_dir(project_root) / f"{item.item_id}.yaml"


def save_pack_improvement_queue(project_root: Path, queue: PackImprovementQueue) -> str:
    path = PackImprovementStore().save_queue(queue, default_pack_improvement_queue_path(project_root))
    return _relative(path, Path(project_root).resolve())


def latest_pack_improvement_queue(project_root: Path, pack_ref: str | None = None) -> PackImprovementQueue | None:
    root = Path(project_root).resolve()
    store = PackImprovementStore()
    candidates: list[Path] = []
    if pack_ref:
        candidates.append(default_pack_improvement_queues_dir(root) / f"queue_{_slug(pack_ref)}.yaml")
    candidates.append(default_pack_improvement_queue_path(root))
    for path in candidates:
        if not path.exists():
            continue
        try:
            queue = store.load_queue(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack improvement queue load failed: %s", exc)
            continue
        if pack_ref is None or _pack_matches(queue.pack_id or queue.pack_ref, pack_ref):
            return queue
    return None


def resolve_pack_improvement_item_path(project_root: Path, item_ref: str) -> Path:
    root = Path(project_root).resolve()
    raw = Path(str(item_ref))
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend([
            root / raw,
            default_pack_improvement_items_dir(root) / raw,
            default_pack_improvement_items_dir(root) / f"{raw}.yaml",
            default_pack_improvement_items_dir(root) / f"{_slug(str(item_ref))}.yaml",
        ])
    for path in candidates:
        if path.exists():
            return path.resolve()
    raise FileNotFoundError(f"pack improvement item not found: {item_ref}")


def record_pack_improvement_decision(
    project_root: Path,
    item_ref: str,
    status: str,
    resolution: str | None = None,
) -> tuple[PackImprovementDecision, PackImprovementQueueItem, str]:
    """item 상태 decision을 저장하고 item artifact 상태를 갱신한다."""
    root = Path(project_root).resolve()
    if status not in {"accepted", "dismissed", "deferred"}:
        raise ValueError("decision status must be accepted, dismissed, or deferred")
    item_path = resolve_pack_improvement_item_path(root, item_ref)
    store = PackImprovementStore()
    item = store.load_item(item_path)
    decision = PackImprovementDecision(
        schema_version=SCHEMA_VERSION,
        decision_id=f"improvement-decision-{_slug(item.item_id)}-{_stamp()}",
        created_at=_now(),
        item_id=item.item_id,
        pack_id=item.pack_id,
        status=status,
        resolution=str(resolution).strip() if resolution else None,
        source_item_ref=_relative(item_path, root),
        warnings=[],
        errors=[],
    )
    PackImprovementDecisionStore().add_decision(default_pack_improvement_decisions_path(root), decision)
    item.status = status
    item.updated_at = decision.created_at
    store.save_item(item, item_path)
    _refresh_queue_item_status(root, item)
    return decision, item, _relative(item_path, root)


def render_pack_improvement_queue(queue: PackImprovementQueue) -> str:
    lines = [
        "Pack Improvement Queue",
        "==================================================",
        "",
        "Pack:",
        f"  {queue.pack_id or queue.pack_ref or 'all'}",
    ]
    top = _top_item(queue.items)
    if top is not None:
        lines.extend([
            "",
            "Top improvement:",
            f"  {top.kind}",
            "",
            "Why:",
            f"  {top.reason}",
            "",
            "Affected metrics:",
        ])
        lines.extend([f"  - {metric}" for metric in top.affected_metrics] or ["  - none"])
        lines.extend(["", "Next:"])
        lines.extend([f"  {command}" for command in top.next_commands] or ["  no command suggestion"])
    else:
        lines.extend(["", "Top improvement:", "  none"])
    if queue.items:
        lines.extend(["", "Open items:"])
        for item in [item for item in queue.items if item.status == "open"][:8]:
            lines.append(f"  - {item.kind} | {item.priority} | confidence={item.confidence:.2f}")
        accepted = [item for item in queue.items if item.status == "accepted"]
        if accepted:
            lines.extend(["", "Accepted for vNext:"])
            lines.append(f"  {len(accepted)}")
            lines.append(f"  next: cambrian pack derivative-plan {queue.pack_id or queue.pack_ref or ''}".rstrip())
    if queue.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in queue.warnings])
    return "\n".join(lines)


def render_pack_improvements(items: list[PackImprovementQueueItem], status: str | None = None) -> str:
    lines = [
        "Pack Improvements",
        "==================================================",
        "",
        "Items:",
    ]
    if status:
        lines.append(f"  filter: {status}")
    if not items:
        lines.append("  none")
        return "\n".join(lines)
    for item in items:
        lines.append(f"  - {item.item_id} | {item.kind} | {item.status} | {item.priority} | {item.confidence:.2f}")
    return "\n".join(lines)


def render_pack_improvement_item(item: PackImprovementQueueItem) -> str:
    lines = [
        "Pack Improvement",
        "==================================================",
        "",
        "Item:",
        f"  {item.item_id}",
        "",
        "Kind:",
        f"  {item.kind}",
        "",
        "Status:",
        f"  {item.status}",
        "",
        "Priority:",
        f"  {item.priority}",
        "",
        "Confidence:",
        f"  {item.confidence:.2f}",
        "",
        "Summary:",
        f"  {item.summary}",
        "",
        "Reason:",
        f"  {item.reason}",
    ]
    if item.affected_metrics:
        lines.extend(["", "Affected metrics:"])
        lines.extend([f"  - {metric}" for metric in item.affected_metrics])
    if item.evidence_refs:
        lines.extend(["", "Evidence refs:"])
        lines.extend([f"  - {ref}" for ref in item.evidence_refs])
    if item.next_commands:
        lines.extend(["", "Next commands:"])
        lines.extend([f"  {command}" for command in item.next_commands])
    if item.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in item.warnings])
    return "\n".join(lines)


def render_pack_improvement_decision(decision: PackImprovementDecision, item: PackImprovementQueueItem) -> str:
    lines = [
        "Pack Improvement Decision",
        "==================================================",
        "",
        "Item:",
        f"  {item.item_id}",
        "",
        "Decision:",
        f"  {decision.status}",
    ]
    if decision.resolution:
        lines.extend(["", "Resolution:", f"  {decision.resolution}"])
    if item.next_commands:
        lines.extend(["", "Next commands:"])
        lines.extend([f"  {command}" for command in item.next_commands])
    if decision.status == "accepted":
        lines.extend(["", "Derivative:", f"  cambrian pack derivative-plan {item.pack_id}"])
    lines.extend(["", "Safety:", "  decision only; no pack/template/source mutation was performed"])
    return "\n".join(lines)


def render_pack_improvement_compact(queue: PackImprovementQueue | None) -> str:
    if queue is None:
        return ""
    open_items = [item for item in queue.items if item.status == "open"]
    if not open_items:
        return ""
    top = _top_item(open_items)
    lines = [
        "Open improvements:",
        f"  {len(open_items)}",
    ]
    if top is not None:
        lines.append(f"  top: {top.kind}")
        if top.priority == "high":
            lines.append("  priority: high")
    return "\n".join(lines)


def render_status_pack_improvement(queue: PackImprovementQueue | None) -> str:
    if queue is None:
        return ""
    high = [item for item in queue.items if item.status == "open" and item.priority == "high"]
    top = _top_item(high)
    if top is None:
        return ""
    return "\n".join(["Pack improvement:", f"  {top.kind}", f"  next: cambrian pack improvement-show {top.item_id}"])


def _items_from_sources(
    root: Path,
    pack_ref: str | None,
    summary: PackRetrospectiveSummary | None,
    usage: Any | None,
    proof: Any | None,
    release_report: Any | None,
    source_refs: dict[str, Any],
    decisions: dict[str, str],
) -> list[PackImprovementQueueItem]:
    specs: dict[str, dict[str, Any]] = {}
    evidence_refs = _evidence_refs(source_refs)
    if summary is not None:
        for signal_kind, counts in summary.signal_counts.items():
            negative_count = int(counts.get("negative", 0) or 0) if isinstance(counts, dict) else 0
            if negative_count <= 0:
                continue
            for kind in _kinds_for_negative_signal(signal_kind):
                _merge_spec(specs, kind, signal_kind, negative_count, evidence_refs)
        worked_well = int(summary.outcome_counts.get("worked_well", 0) or 0)
        if worked_well >= 2 or summary.benchmark_case_candidates:
            _merge_spec(specs, "add_benchmark_case", "worked_well", worked_well or 1, evidence_refs)
            _merge_spec(specs, "update_pack_docs", "worked_well", worked_well or 1, evidence_refs)
        regression = int(summary.outcome_counts.get("regression_or_safety_issue", 0) or 0)
        if regression:
            _merge_spec(specs, "improve_validation_support", "safety_risk", regression, evidence_refs)
            _merge_spec(specs, "update_known_limits", "safety_risk", regression, evidence_refs)
        for suggestion in summary.top_suggestions:
            if suggestion.kind in IMPROVEMENT_KINDS:
                _merge_spec(specs, suggestion.kind, _signal_from_suggestion(suggestion), 1, _dedupe([*evidence_refs, *suggestion.evidence_refs]))

    proof_weak = [str(item) for item in getattr(proof, "where_weak", []) or []]
    for weak in proof_weak:
        for signal_kind in _signals_mentioned(weak):
            for kind in _kinds_for_negative_signal(signal_kind):
                _merge_spec(specs, kind, signal_kind, 1, _dedupe([*evidence_refs, str(source_refs.get("proof_ref") or "")]))

    usage_degraded = _usage_degraded_signals(usage)
    for signal_kind in usage_degraded:
        for kind in _kinds_for_negative_signal(signal_kind):
            _merge_spec(specs, kind, signal_kind, 1, evidence_refs)

    release_evidence = _dedupe([*evidence_refs, str(source_refs.get("release_ref") or "")])
    for signal_kind in _release_check_degraded_signals(release_report):
        for kind in _kinds_for_negative_signal(signal_kind):
            _merge_spec(specs, kind, signal_kind, 1, release_evidence)

    items = [
        _item_from_spec(root, pack_ref, summary, kind, spec, usage, proof, decisions)
        for kind, spec in specs.items()
    ]
    return sorted(items, key=_item_sort_key)


def _item_from_spec(
    root: Path,
    pack_ref: str | None,
    summary: PackRetrospectiveSummary | None,
    kind: str,
    spec: dict[str, Any],
    usage: Any | None,
    proof: Any | None,
    decisions: dict[str, str],
) -> PackImprovementQueueItem:
    pack_id = pack_ref or getattr(summary, "pack_id", None) or "unknown-pack"
    count = int(spec.get("count", 0) or 0)
    signals = _dedupe([str(item) for item in spec.get("signals", []) if item])
    evidence_refs = _dedupe([str(item) for item in spec.get("evidence_refs", []) if item])
    priority = _priority(kind, signals, count, summary, proof)
    confidence = _confidence(count, evidence_refs, usage, proof, summary)
    item_id = f"item_{_slug(pack_id)}_{_slug(kind)}"
    warnings = []
    if not evidence_refs:
        confidence = min(confidence, 0.3)
        warnings.append("evidence refs가 없어 confidence를 낮췄습니다.")
    return PackImprovementQueueItem(
        schema_version=SCHEMA_VERSION,
        item_id=item_id,
        created_at=_now(),
        updated_at=None,
        pack_ref=pack_id,
        pack_id=pack_id,
        pack_name=getattr(summary, "pack_name", None) if summary else None,
        namespace=getattr(summary, "namespace", None) if summary else None,
        version=getattr(summary, "version", None) if summary else None,
        kind=kind,
        status=decisions.get(item_id, "open"),
        priority=priority,
        confidence=confidence,
        title=_title_for_kind(kind),
        summary=_summary_for_kind(kind, count, signals),
        reason=_reason_for_kind(kind, count, signals),
        affected_metrics=_affected_metrics(kind),
        evidence_refs=evidence_refs,
        source_signal_kinds=signals,
        next_commands=_next_commands(kind, pack_id, summary),
        warnings=warnings,
        errors=[],
    )


def _merge_spec(specs: dict[str, dict[str, Any]], kind: str, signal_kind: str, count: int, evidence_refs: list[str]) -> None:
    if kind not in IMPROVEMENT_KINDS:
        return
    spec = specs.setdefault(kind, {"count": 0, "signals": [], "evidence_refs": []})
    spec["count"] += max(1, int(count or 0))
    spec["signals"].append(signal_kind)
    spec["evidence_refs"].extend(evidence_refs)


def _kinds_for_negative_signal(signal_kind: str) -> list[str]:
    mapping = {
        "context_fit": ["strengthen_context_hints", "add_benchmark_case"],
        "bridge_quality": ["improve_response_contract"],
        "validation_quality": ["improve_validation_support"],
        "adoption_quality": ["update_known_limits", "review_template_fit", "create_pack_derivative"],
        "team_fit": ["review_team_fit"],
        "template_fit": ["review_template_fit", "create_pack_derivative"],
        "safety_risk": ["improve_validation_support", "update_known_limits"],
        "intervention_cost": ["strengthen_context_hints", "improve_first_job_guide"],
        "lane_fit": ["create_pack_derivative", "update_known_limits"],
    }
    return mapping.get(signal_kind, [])


def _affected_metrics(kind: str) -> list[str]:
    mapping = {
        "strengthen_context_hints": ["validated_proposal_rate", "human_intervention_rate", "median_time_to_validated_proposal"],
        "add_benchmark_case": ["repeat_task_improvement_rate", "reuse_lift", "team_template_recommendation_hit_rate"],
        "improve_response_contract": ["human_intervention_rate", "validation_autonomy_rate", "median_time_to_validated_proposal"],
        "improve_validation_support": ["validated_proposal_rate", "validation_autonomy_rate", "regression_free_apply_rate"],
        "update_known_limits": ["adoption_rate", "regression_free_apply_rate", "team_template_recommendation_hit_rate"],
        "review_template_fit": ["adoption_rate", "team_template_recommendation_hit_rate", "repeat_task_improvement_rate"],
        "create_pack_derivative": ["team_template_recommendation_hit_rate", "repeat_task_improvement_rate", "reuse_lift"],
        "review_team_fit": ["lead_agent_hit_rate", "team_template_recommendation_hit_rate"],
        "update_pack_docs": ["reuse_lift", "repeat_task_improvement_rate", "team_template_recommendation_hit_rate"],
        "improve_first_job_guide": ["human_intervention_rate", "median_time_to_validated_proposal", "validated_proposal_rate"],
    }
    return mapping.get(kind, [])


def _next_commands(kind: str, pack_id: str, summary: PackRetrospectiveSummary | None) -> list[str]:
    template = _template_hint(summary)
    workset = _workset_hint(summary)
    mapping = {
        "strengthen_context_hints": [f"cambrian template evolve {template}", "cambrian benchmark case-add ..."],
        "add_benchmark_case": ["cambrian benchmark case-add ...", f"cambrian pack proof {pack_id}"],
        "improve_response_contract": ["cambrian bridge prepare ...", "review pack response contract manually"],
        "improve_validation_support": [f"cambrian template evolve {template}", f"cambrian benchmark bottlenecks {workset}"],
        "update_known_limits": [f"cambrian pack proof {pack_id}", f"cambrian pack proof-export {pack_id}"],
        "review_template_fit": [f"cambrian template evolve {template}", f"cambrian pack draft {pack_id}-next team"],
        "create_pack_derivative": ["cambrian pack draft ...", "cambrian pack build ..."],
        "review_team_fit": ["cambrian team recommend", "cambrian pack draft ..."],
        "update_pack_docs": [f"cambrian pack proof-export {pack_id}", "update pack docs manually"],
        "improve_first_job_guide": [f"cambrian pack setup {pack_id}", f"cambrian pack next"],
    }
    return mapping.get(kind, [])


def _priority(
    kind: str,
    signals: list[str],
    count: int,
    summary: PackRetrospectiveSummary | None,
    proof: Any | None,
) -> str:
    if kind == "add_benchmark_case" and "worked_well" not in signals and "benchmark_value" not in signals:
        return "medium" if count >= 2 else "low"
    if count >= 3:
        return "high"
    if summary is not None and int(summary.outcome_counts.get("regression_or_safety_issue", 0) or 0) > 0:
        if kind in {"improve_validation_support", "update_known_limits"}:
            return "high"
    if kind in {"strengthen_context_hints", "improve_validation_support", "update_known_limits"} and _proof_mentions(proof, kind):
        return "high"
    if kind in {"strengthen_context_hints", "improve_validation_support"} and count >= 1:
        return "high"
    if count >= 2:
        return "medium"
    if any(signal in {"intervention_cost", "team_fit", "template_fit", "adoption_quality"} for signal in signals):
        return "medium"
    return "low"


def _confidence(
    count: int,
    evidence_refs: list[str],
    usage: Any | None,
    proof: Any | None,
    summary: PackRetrospectiveSummary | None,
) -> float:
    confidence = 0.4
    if summary is not None:
        confidence += 0.1
    if proof is not None:
        confidence += 0.1
    if usage is not None and getattr(usage, "counts", {}).get("used_count", 0):
        confidence += 0.1
    if count >= 2:
        confidence += 0.1
    if count >= 3 or _degraded_usage_metric(usage):
        confidence += 0.1
    if not evidence_refs:
        confidence = min(confidence, 0.3)
    return min(0.9, round(confidence, 2))


def _queue_summary(pack_ref: str | None, items: list[PackImprovementQueueItem], top: PackImprovementQueueItem | None) -> list[str]:
    lines = [f"pack={pack_ref or 'all'}", f"items={len(items)}"]
    if top is not None:
        lines.append(f"top={top.kind}")
        lines.append(f"top_priority={top.priority}")
    return lines


def _top_item(items: list[PackImprovementQueueItem]) -> PackImprovementQueueItem | None:
    open_items = [item for item in items if item.status == "open"]
    candidates = open_items or list(items)
    return sorted(candidates, key=_item_sort_key)[0] if candidates else None


def _item_sort_key(item: PackImprovementQueueItem) -> tuple[int, float, str]:
    return (PRIORITY_ORDER.get(item.priority, 9), -float(item.confidence or 0.0), item.kind)


def _latest_summary_with_ref(root: Path, pack_ref: str | None) -> tuple[PackRetrospectiveSummary | None, str | None]:
    summary = latest_pack_retro_summary(root, pack_ref)
    if summary is None:
        return None, None
    summaries_dir = root / ".cambrian" / "packs" / "retrospectives" / "summaries"
    for path in sorted(summaries_dir.glob("summary_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = _load_yaml(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("retrospective summary ref lookup skipped: %s", exc)
            continue
        if str(payload.get("summary_id") or "") == summary.summary_id:
            return summary, _relative(path, root)
    return summary, summary.summary_id


def _target_pack_ref(root: Path, pack_ref: str | None, summary: PackRetrospectiveSummary | None) -> str | None:
    if pack_ref:
        return str(pack_ref)
    if summary is not None and (summary.pack_id or summary.pack_ref):
        return summary.pack_id or summary.pack_ref
    try:
        from engine.project_pack_activation import current_active_pack

        context = current_active_pack(root)
        if context is not None:
            return context.pack_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("active pack lookup for improvement queue failed: %s", exc)
    return None


def _canonical_pack_id(pack_ref: str | None, summary: PackRetrospectiveSummary | None) -> str | None:
    if summary is not None and summary.pack_id:
        return str(summary.pack_id)
    if not pack_ref:
        return None
    return _plain_pack_id(pack_ref)


def _usage_summary(root: Path, pack_ref: str | None) -> Any | None:
    try:
        from engine.project_pack_usage import PackUsageSummaryBuilder

        return PackUsageSummaryBuilder().build(root, pack_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pack usage summary lookup failed during improvement build: %s", exc)
        return None


def _proof_card(root: Path, pack_ref: str | None) -> Any | None:
    if not pack_ref:
        return None
    try:
        from engine.project_pack_proof import latest_pack_proof_card

        return latest_pack_proof_card(root, pack_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pack proof lookup failed during improvement build: %s", exc)
        return None


def _latest_release_report(root: Path, pack_ref: str | None) -> tuple[Any | None, str | None]:
    release_ref = _latest_release_ref(root, pack_ref)
    if not release_ref:
        return None, None
    try:
        from engine.project_pack_release import PackReleaseStore

        release_path = root / release_ref
        return PackReleaseStore().load(release_path), release_ref
    except Exception as exc:  # noqa: BLE001
        logger.warning("pack release-check report lookup failed during improvement build: %s", exc)
        return None, release_ref


def _latest_release_ref(root: Path, pack_ref: str | None) -> str | None:
    if not pack_ref:
        return None
    release_dir = root / ".cambrian" / "packs" / "releases"
    if not release_dir.exists():
        return None
    slug = _slug(pack_ref)
    for path in sorted(release_dir.rglob(f"*{slug}*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        return _relative(path, root)
    return None


def _evidence_refs(source_refs: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for value in source_refs.values():
        if isinstance(value, list):
            refs.extend(str(item) for item in value if item)
        elif value:
            refs.append(str(value))
    return _dedupe(refs)


def _signals_mentioned(text: str) -> list[str]:
    known = [
        "context_fit",
        "bridge_quality",
        "validation_quality",
        "adoption_quality",
        "team_fit",
        "template_fit",
        "safety_risk",
        "intervention_cost",
        "lane_fit",
    ]
    return [signal for signal in known if signal in text]


def _usage_degraded_signals(usage: Any | None) -> list[str]:
    if usage is None:
        return []
    rates = getattr(usage, "rates", {}) or {}
    signals: list[str] = []
    if _rate_low(rates.get("validated_proposal_rate")):
        signals.append("validation_quality")
    if _rate_low(rates.get("adoption_rate")):
        signals.append("adoption_quality")
    if _rate_low(rates.get("validation_autonomy_rate")):
        signals.append("intervention_cost")
    if _rate_low(rates.get("regression_free_apply_rate")):
        signals.append("safety_risk")
    return _dedupe(signals)


def _release_check_degraded_signals(release_report: Any | None) -> list[str]:
    if release_report is None:
        return []
    texts: list[str] = []
    texts.extend(str(item) for item in getattr(release_report, "warnings", []) or [])
    texts.extend(str(item) for item in getattr(release_report, "errors", []) or [])
    texts.extend(str(item) for item in getattr(release_report, "summary", []) or [])
    for check in getattr(release_report, "checks", []) or []:
        texts.extend([
            str(getattr(check, "check_id", "")),
            str(getattr(check, "status", "")),
            str(getattr(check, "summary", "")),
        ])
        texts.extend(str(item) for item in getattr(check, "warnings", []) or [])
        texts.extend(str(item) for item in getattr(check, "errors", []) or [])
    haystack = " ".join(texts).lower()
    signals: list[str] = []
    if getattr(release_report, "safe_to_publish", True) is False or getattr(release_report, "errors", None):
        signals.append("validation_quality")
    if "regression" in haystack or "safety" in haystack or "unsafe" in haystack:
        signals.append("safety_risk")
    if "proof" in haystack or "maturity" in haystack or "publish blocked" in haystack or "release" in haystack:
        signals.append("validation_quality")
    if "compatibility" in haystack or "template" in haystack:
        signals.append("template_fit")
    if "team" in haystack or "lead agent" in haystack:
        signals.append("team_fit")
    if "known limit" in haystack or "adoption" in haystack or "rejected" in haystack:
        signals.append("adoption_quality")
    return _dedupe(signals)


def _degraded_usage_metric(usage: Any | None) -> bool:
    return bool(_usage_degraded_signals(usage))


def _rate_low(value: Any) -> bool:
    try:
        if value is None:
            return False
        return float(value) < 0.5
    except (TypeError, ValueError):
        return False


def _proof_mentions(proof: Any | None, kind: str) -> bool:
    if proof is None:
        return False
    weak = list(getattr(proof, "where_weak", []) or [])
    limits = list(getattr(proof, "known_limits", []) or [])
    haystack = " ".join([*weak, *limits])
    return kind in haystack or any(signal in haystack for signal in _source_signals_for_kind(kind))


def _source_signals_for_kind(kind: str) -> list[str]:
    return [signal for signal in [
        "context_fit",
        "bridge_quality",
        "validation_quality",
        "adoption_quality",
        "team_fit",
        "template_fit",
        "safety_risk",
        "intervention_cost",
        "lane_fit",
    ] if kind in _kinds_for_negative_signal(signal)]


def _signal_from_suggestion(suggestion: PackImprovementSuggestion) -> str:
    reverse = {
        "strengthen_context_hints": "context_fit",
        "add_benchmark_case": "benchmark_value",
        "improve_response_contract": "bridge_quality",
        "improve_validation_support": "validation_quality",
        "update_known_limits": "adoption_quality",
        "review_template_fit": "template_fit",
        "create_pack_derivative": "template_fit",
        "review_team_fit": "team_fit",
    }
    return reverse.get(suggestion.kind, "retrospective_suggestion")


def _title_for_kind(kind: str) -> str:
    return kind.replace("_", " ")


def _summary_for_kind(kind: str, count: int, signals: list[str]) -> str:
    signal_text = ", ".join(signals) if signals else "retrospective evidence"
    return f"{kind} 개선 후보입니다. 근거 신호: {signal_text}; 반복 수: {count}."


def _reason_for_kind(kind: str, count: int, signals: list[str]) -> str:
    if count >= 3:
        return f"repeated negative signals across {count} retrospective observations"
    if "worked_well" in signals:
        return "repeated worked_well outcomes can become reusable proof and benchmark evidence"
    if signals:
        return f"{signals[0]} signal indicates this pack needs {kind}"
    return f"retrospective evidence suggests {kind}"


def _template_hint(summary: PackRetrospectiveSummary | None) -> str:
    if summary is None:
        return "<template>"
    for suggestion in summary.top_suggestions:
        for command in suggestion.next_commands:
            parts = str(command).split()
            if len(parts) >= 4 and parts[:3] == ["cambrian", "template", "evolve"]:
                return parts[3]
    return "<template>"


def _workset_hint(summary: PackRetrospectiveSummary | None) -> str:
    if summary and summary.benchmark_case_candidates:
        return "<workset>"
    return "<workset>"


def _queue_from_dict(payload: dict[str, Any]) -> PackImprovementQueue:
    return PackImprovementQueue(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        queue_id=str(payload.get("queue_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        pack_ref=str(payload.get("pack_ref")) if payload.get("pack_ref") is not None else None,
        pack_id=str(payload.get("pack_id")) if payload.get("pack_id") is not None else None,
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        items=[_item_from_dict(item) for item in payload.get("items", []) if isinstance(item, dict)],
        top_item_id=str(payload.get("top_item_id")) if payload.get("top_item_id") is not None else None,
        source_refs=_as_dict(payload.get("source_refs")),
        summary=_as_list(payload.get("summary")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _item_from_dict(payload: dict[str, Any]) -> PackImprovementQueueItem:
    return PackImprovementQueueItem(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        item_id=str(payload.get("item_id") or ""),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        pack_ref=str(payload.get("pack_ref") or payload.get("pack_id") or "unknown-pack"),
        pack_id=str(payload.get("pack_id") or payload.get("pack_ref") or "unknown-pack"),
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        kind=str(payload.get("kind") or "update_known_limits"),
        status=str(payload.get("status") or "open"),
        priority=str(payload.get("priority") or "low"),
        confidence=float(payload.get("confidence") or 0.0),
        title=str(payload.get("title") or payload.get("kind") or ""),
        summary=str(payload.get("summary") or ""),
        reason=str(payload.get("reason") or ""),
        affected_metrics=_as_list(payload.get("affected_metrics")),
        evidence_refs=_as_list(payload.get("evidence_refs")),
        source_signal_kinds=_as_list(payload.get("source_signal_kinds")),
        next_commands=_as_list(payload.get("next_commands")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _decision_from_dict(payload: dict[str, Any]) -> PackImprovementDecision:
    return PackImprovementDecision(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        decision_id=str(payload.get("decision_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        item_id=str(payload.get("item_id") or ""),
        pack_id=str(payload.get("pack_id")) if payload.get("pack_id") is not None else None,
        status=str(payload.get("status") or "deferred"),
        resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
        source_item_ref=str(payload.get("source_item_ref")) if payload.get("source_item_ref") is not None else None,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _refresh_queue_item_status(root: Path, item: PackImprovementQueueItem) -> None:
    store = PackImprovementStore()
    candidates = [
        default_pack_improvement_queue_path(root),
        default_pack_improvement_queues_dir(root) / f"queue_{_slug(item.pack_id or item.pack_ref or 'all')}.yaml",
    ]
    for queue_path in _dedupe_paths(candidates):
        if not queue_path.exists():
            continue
        try:
            queue = store.load_queue(queue_path)
            changed = False
            for idx, existing in enumerate(queue.items):
                if existing.item_id == item.item_id:
                    queue.items[idx] = item
                    changed = True
            if changed:
                queue.top_item_id = _top_item(queue.items).item_id if _top_item(queue.items) else None
                store.save_queue(queue, queue_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack improvement queue status refresh failed: %s", exc)


def _project_root_from_improvements_path(path: Path) -> Path:
    resolved = Path(path).resolve()
    parts = list(resolved.parts)
    if ".cambrian" in parts:
        return Path(*parts[: parts.index(".cambrian")])
    return resolved.parent


def _pack_matches(value: str | None, pack_ref: str) -> bool:
    raw = str(pack_ref or "").strip()
    if not raw:
        return True
    raw_plain = _plain_pack_id(raw)
    value_plain = _plain_pack_id(value)
    return raw == str(value or "") or raw_plain == value_plain or _local_pack_base(raw_plain) == _local_pack_base(value_plain)


def _plain_pack_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split("@", 1)[0].split("/", 1)[-1]


def _local_pack_base(value: str) -> str:
    raw = str(value or "").strip()
    for suffix in ("-local", "_local"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)]
    return raw


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(Path(path).resolve())
        if key in seen:
            continue
        seen.add(key)
        result.append(Path(path).resolve())
    return result


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
