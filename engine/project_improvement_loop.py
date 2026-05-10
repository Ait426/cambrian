"""주간 단위 improvement cycle을 관리하는 모듈."""

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
ACTIVE_STATUSES = {"planned", "in_progress", "evaluated"}
METRIC_KEYS = [
    "validated_proposal_rate",
    "adoption_rate",
    "regression_free_apply_rate",
    "median_time_to_validated_proposal",
    "human_intervention_rate",
    "validation_autonomy_rate",
    "lead_agent_hit_rate",
    "team_template_recommendation_hit_rate",
    "reuse_lift",
    "repeat_task_improvement_rate",
]


class ActiveImprovementCycleError(RuntimeError):
    """이미 active improvement cycle이 있을 때 발생한다."""

    def __init__(self, cycle_id: str, cycle_ref: str | None = None) -> None:
        super().__init__(f"active improvement cycle already exists: {cycle_id}")
        self.cycle_id = cycle_id
        self.cycle_ref = cycle_ref


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _week_id() -> str:
    """현재 ISO week id를 만든다."""
    today = datetime.now(timezone.utc).date()
    iso = today.isocalendar()
    return f"{iso.year}_W{iso.week:02d}"


def _stamp() -> str:
    """파일명에 넣을 UTC timestamp를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 충돌 방지 id를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str, fallback: str = "item") -> str:
    """파일명에 안전한 slug를 만든다."""
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
    """YAML/JSON artifact를 안전하게 읽는다."""
    if not Path(path).exists():
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
        if Path(path).suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("improvement artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """프로젝트 기준 상대 경로를 만든다."""
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


def _score(value: Any) -> float | None:
    """숫자형 값을 float로 정규화한다."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ImprovementMetricSnapshot:
    """improvement cycle의 before/after 지표 스냅샷."""

    validated_proposal_rate: float | None
    adoption_rate: float | None
    regression_free_apply_rate: float | None
    median_time_to_validated_proposal: float | None
    human_intervention_rate: float | None
    validation_autonomy_rate: float | None
    lead_agent_hit_rate: float | None
    team_template_recommendation_hit_rate: float | None
    reuse_lift: float | None
    repeat_task_improvement_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ImprovementCycle:
    """한 번에 하나의 병목만 다루는 주간 개선 cycle."""

    schema_version: str
    cycle_id: str
    created_at: str
    updated_at: str | None
    week_id: str
    workset_name: str
    status: str
    selected_bottleneck_kind: str | None
    selected_bottleneck_summary: str | None
    selected_fix_kind: str | None
    selected_fix_summary: str | None
    hypothesis: str
    before_snapshot: ImprovementMetricSnapshot
    after_snapshot: ImprovementMetricSnapshot | None
    verdict: str | None
    evidence_refs: dict[str, Any]
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["before_snapshot"] = self.before_snapshot.to_dict()
        payload["after_snapshot"] = self.after_snapshot.to_dict() if self.after_snapshot else None
        return payload


@dataclass
class ImprovementCycleIndex:
    """improvement cycle index."""

    schema_version: str
    updated_at: str
    active_cycle_id: str | None
    cycles: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class ImprovementCycleBuilder:
    """latest evidence에서 다음 improvement cycle을 만든다."""

    def build_next(
        self,
        project_root: Path,
        workset_name: str,
        bottleneck_kind: str | None = None,
        hypothesis: str | None = None,
    ) -> ImprovementCycle:
        """가장 중요한 병목 하나를 선택해 새 cycle을 만든다."""
        root = Path(project_root).resolve()
        store = ImprovementCycleStore()
        active = store.active(root)
        if active is not None:
            active_ref = _cycle_ref(root, active.cycle_id)
            raise ActiveImprovementCycleError(active.cycle_id, active_ref)

        warnings: list[str] = []
        evidence_refs = _latest_evidence_refs(root, workset_name, prefix="before")
        bottleneck_payload = _load_ref_payload(root, evidence_refs.get("before_bottleneck_ref"))
        compare_payload = _load_ref_payload(root, evidence_refs.get("before_compare_ref"))
        proof_payload = _load_ref_payload(root, evidence_refs.get("before_proof_ref"))
        metrics_payload = _load_ref_payload(root, evidence_refs.get("before_metrics_ref"))
        if not bottleneck_payload:
            warnings.append("latest bottleneck report is missing for this workset")
        if not compare_payload:
            warnings.append("latest benchmark compare is missing for this workset")
        if not proof_payload:
            warnings.append("latest proof pack is missing for this workset")
        if not metrics_payload:
            warnings.append("latest weekly metrics report is missing")

        bottleneck = _select_bottleneck(bottleneck_payload, bottleneck_kind)
        if bottleneck_kind and bottleneck is None:
            warnings.append(f"requested bottleneck was not found: {bottleneck_kind}")
        suggestion = _select_suggestion(bottleneck_payload, bottleneck)
        selected_bottleneck_kind = str(bottleneck.get("kind")) if bottleneck else bottleneck_kind
        selected_fix_kind = str(suggestion.get("kind")) if suggestion else None
        selected_fix_summary = str(suggestion.get("summary")) if suggestion and suggestion.get("summary") is not None else None
        selected_bottleneck_summary = (
            str(bottleneck.get("summary"))
            if bottleneck and bottleneck.get("summary") is not None
            else None
        )
        if bottleneck is not None:
            try:
                evidence_refs["before_selected_bottleneck_frequency"] = int(bottleneck.get("frequency") or 0)
            except (TypeError, ValueError):
                evidence_refs["before_selected_bottleneck_frequency"] = None
        before_snapshot = _snapshot_from_evidence(metrics_payload, proof_payload, compare_payload)
        generated_hypothesis = hypothesis or _hypothesis(
            selected_fix_kind,
            selected_bottleneck_kind,
            selected_fix_summary,
        )
        next_actions = _next_actions(workset_name)
        summary = _dedupe([
            f"selected bottleneck: {selected_bottleneck_kind or 'none'}",
            f"selected fix: {selected_fix_summary or selected_fix_kind or 'none'}",
            f"hypothesis: {generated_hypothesis}",
        ])
        return ImprovementCycle(
            schema_version=SCHEMA_VERSION,
            cycle_id=f"cycle-{_slug(workset_name)}-{_short_id()}",
            created_at=_now(),
            updated_at=None,
            week_id=_week_id(),
            workset_name=workset_name,
            status="planned",
            selected_bottleneck_kind=selected_bottleneck_kind,
            selected_bottleneck_summary=selected_bottleneck_summary,
            selected_fix_kind=selected_fix_kind,
            selected_fix_summary=selected_fix_summary,
            hypothesis=generated_hypothesis,
            before_snapshot=before_snapshot,
            after_snapshot=None,
            verdict=None,
            evidence_refs=evidence_refs,
            summary=summary,
            next_actions=next_actions,
            warnings=_dedupe(warnings),
            errors=[],
        )


class ImprovementCycleStore:
    """improvement cycle 저장소."""

    def save(self, cycle: ImprovementCycle, path: Path) -> Path:
        """cycle과 index를 저장한다."""
        saved = _save_yaml(Path(path).resolve(), cycle.to_dict())
        self._save_index(saved.parent.parent, self._index_for(saved.parent.parent, saved, cycle))
        return saved

    def update(self, cycle_path: Path, cycle: ImprovementCycle) -> Path:
        """기존 cycle을 갱신한다."""
        return self.save(cycle, cycle_path)

    def load(self, path: Path) -> ImprovementCycle:
        """cycle artifact를 읽는다."""
        return _cycle_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, cycles_dir: Path) -> list[ImprovementCycle]:
        """최근 cycle 목록을 읽는다."""
        cycles: list[ImprovementCycle] = []
        for path in sorted(Path(cycles_dir).glob("cycle_*.yaml")):
            payload = _load_yaml(path)
            if payload:
                cycles.append(_cycle_from_dict(payload))
        cycles.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
        return cycles

    def active(self, project_root: Path) -> ImprovementCycle | None:
        """현재 active cycle을 읽는다."""
        root = Path(project_root).resolve()
        index = _load_yaml(default_improvement_index_path(root))
        active_id = index.get("active_cycle_id")
        if not active_id:
            return None
        try:
            cycle = self.load(resolve_cycle_path(root, str(active_id)))
        except FileNotFoundError:
            return None
        if cycle.status in ACTIVE_STATUSES:
            return cycle
        return None

    def _index_for(self, improvement_dir: Path, saved_path: Path, cycle: ImprovementCycle) -> ImprovementCycleIndex:
        payload = _load_yaml(improvement_dir / "index.yaml")
        cycles = list(payload.get("cycles", [])) if isinstance(payload.get("cycles"), list) else []
        cycle_ref = _relative(saved_path, improvement_dir.parent.parent)
        entry = {
            "cycle_id": cycle.cycle_id,
            "cycle_ref": cycle_ref,
            "workset_name": cycle.workset_name,
            "status": cycle.status,
            "verdict": cycle.verdict,
            "selected_bottleneck_kind": cycle.selected_bottleneck_kind,
            "selected_fix_kind": cycle.selected_fix_kind,
            "updated_at": cycle.updated_at or cycle.created_at,
        }
        cycles = [item for item in cycles if not isinstance(item, dict) or item.get("cycle_id") != cycle.cycle_id]
        cycles.insert(0, entry)
        active_cycle_id = payload.get("active_cycle_id")
        if cycle.status in ACTIVE_STATUSES:
            active_cycle_id = cycle.cycle_id
        elif active_cycle_id == cycle.cycle_id:
            active_cycle_id = None
        return ImprovementCycleIndex(
            schema_version=SCHEMA_VERSION,
            updated_at=_now(),
            active_cycle_id=active_cycle_id if isinstance(active_cycle_id, str) else None,
            cycles=cycles[:100],
            warnings=[],
            errors=[],
        )

    def _save_index(self, improvement_dir: Path, index: ImprovementCycleIndex) -> Path:
        return _save_yaml(improvement_dir / "index.yaml", index.to_dict())


class ImprovementCycleEvaluator:
    """cycle의 before/after를 비교해 verdict를 낸다."""

    def evaluate(self, project_root: Path, cycle_path: Path) -> ImprovementCycle:
        """latest evidence를 after snapshot으로 삼아 cycle을 평가한다."""
        root = Path(project_root).resolve()
        path = Path(cycle_path).resolve()
        cycle = ImprovementCycleStore().load(path)
        after_refs = _latest_evidence_refs(root, cycle.workset_name, prefix="after")
        after_metrics = _load_ref_payload(root, after_refs.get("after_metrics_ref"))
        after_proof = _load_ref_payload(root, after_refs.get("after_proof_ref"))
        after_compare = _load_ref_payload(root, after_refs.get("after_compare_ref"))
        after_bottleneck = _load_ref_payload(root, after_refs.get("after_bottleneck_ref"))
        after_snapshot = _snapshot_from_evidence(after_metrics, after_proof, after_compare)
        before_frequency = _score(cycle.evidence_refs.get("before_selected_bottleneck_frequency"))
        before_frequency = int(before_frequency) if before_frequency is not None else None
        after_frequency = _bottleneck_frequency(after_bottleneck, cycle.selected_bottleneck_kind)
        verdict, summary, warnings = _evaluate_verdict(
            before=cycle.before_snapshot,
            after=after_snapshot,
            before_frequency=before_frequency,
            after_frequency=after_frequency,
        )
        cycle.after_snapshot = after_snapshot
        cycle.verdict = verdict
        cycle.status = "evaluated"
        cycle.updated_at = _now()
        cycle.evidence_refs.update(after_refs)
        cycle.summary = _dedupe([*cycle.summary, *summary])
        cycle.warnings = _dedupe([*cycle.warnings, *warnings])
        return cycle


def default_improvement_dir(project_root: Path) -> Path:
    """improvement 저장 루트."""
    return Path(project_root).resolve() / ".cambrian" / "improvement"


def default_cycles_dir(project_root: Path) -> Path:
    """cycle 저장 디렉터리."""
    return default_improvement_dir(project_root) / "cycles"


def default_improvement_index_path(project_root: Path) -> Path:
    """improvement index 경로."""
    return default_improvement_dir(project_root) / "index.yaml"


def default_cycle_path(project_root: Path, cycle: ImprovementCycle) -> Path:
    """cycle 기본 저장 경로."""
    return default_cycles_dir(project_root) / f"cycle_{cycle.week_id}_{_slug(cycle.workset_name)}_{_short_id()}.yaml"


def resolve_cycle_path(project_root: Path, cycle_ref: str) -> Path:
    """cycle id 또는 path를 실제 artifact 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(cycle_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in default_cycles_dir(root).glob("cycle_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == cycle_ref or str(payload.get("cycle_id") or "") == cycle_ref:
            return path.resolve()
    if cycle_ref in {"active", "latest"}:
        summary = load_latest_improvement_summary(root)
        ref = summary.get("cycle_ref")
        if ref:
            return (root / str(ref)).resolve()
    raise FileNotFoundError(f"improvement cycle not found: {cycle_ref}")


def render_cycle_started(cycle: ImprovementCycle, saved_path: Path, project_root: Path) -> str:
    """cycle 시작 결과를 렌더링한다."""
    lines = [
        "Improvement Cycle Started",
        "==================================================",
        "",
        "Workset:",
        f"  {cycle.workset_name}",
        "",
        "Selected bottleneck:",
        f"  {cycle.selected_bottleneck_kind or 'none'}",
        "",
        "Selected fix:",
        f"  {cycle.selected_fix_summary or cycle.selected_fix_kind or 'none'}",
        "",
        "Hypothesis:",
        f"  {cycle.hypothesis}",
        "",
        "Next:",
    ]
    lines.extend([f"  {index}. {action}" for index, action in enumerate(cycle.next_actions, start=1)])
    lines.extend(["", "Saved:", f"  {_relative(saved_path, project_root)}"])
    if cycle.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in cycle.warnings[:5]])
    return "\n".join(lines)


def render_cycle(cycle: ImprovementCycle) -> str:
    """cycle 상세를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Improvement Cycle",
        "==================================================",
        "",
        "Cycle:",
        f"  {cycle.cycle_id}",
        "",
        "Workset:",
        f"  {cycle.workset_name}",
        "",
        "Status:",
        f"  {cycle.status}",
        "",
        "Bottleneck:",
        f"  {cycle.selected_bottleneck_kind or 'none'}",
    ]
    if cycle.selected_bottleneck_summary:
        lines.append(f"  {cycle.selected_bottleneck_summary}")
    lines.extend([
        "",
        "Hypothesis:",
        f"  {cycle.hypothesis}",
        "",
        "Before:",
        *_snapshot_lines(cycle.before_snapshot, "  "),
    ])
    if cycle.after_snapshot is not None:
        lines.extend(["", "After:", *_snapshot_lines(cycle.after_snapshot, "  ")])
    if cycle.verdict:
        lines.extend(["", "Verdict:", f"  {cycle.verdict}"])
    if cycle.next_actions and cycle.status != "closed":
        lines.extend(["", "Next:"])
        lines.extend([f"  {index}. {action}" for index, action in enumerate(cycle.next_actions, start=1)])
    if cycle.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in cycle.summary[-6:]])
    if cycle.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in cycle.warnings[:5]])
    return "\n".join(lines)


def render_cycles(cycles: list[ImprovementCycle]) -> str:
    """cycle 목록을 렌더링한다."""
    lines = [
        "Improvement Cycles",
        "==================================================",
        "",
        "Recent:",
    ]
    if not cycles:
        lines.append("  none")
        return "\n".join(lines)
    for index, cycle in enumerate(cycles[:20], start=1):
        verdict = f", verdict: {cycle.verdict}" if cycle.verdict else ""
        lines.append(
            f"  {index}. {cycle.cycle_id} [{cycle.status}{verdict}] "
            f"{cycle.selected_bottleneck_kind or 'none'}"
        )
    return "\n".join(lines)


def render_evaluation(cycle: ImprovementCycle) -> str:
    """평가 결과를 렌더링한다."""
    lines = [
        "Improvement Cycle Evaluation",
        "==================================================",
        "",
        "Bottleneck:",
        f"  {cycle.selected_bottleneck_kind or 'none'}",
        "",
        "Verdict:",
        f"  {cycle.verdict or 'inconclusive'}",
        "",
        "Before:",
        *_snapshot_lines(cycle.before_snapshot, "  "),
    ]
    if cycle.after_snapshot:
        lines.extend(["", "After:", *_snapshot_lines(cycle.after_snapshot, "  ")])
    if cycle.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in cycle.summary[-6:]])
    if cycle.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in cycle.warnings[-5:]])
    return "\n".join(lines)


def load_latest_improvement_summary(project_root: Path) -> dict[str, Any]:
    """status/metrics에서 쓸 latest improvement 요약을 읽는다."""
    root = Path(project_root).resolve()
    index = _load_yaml(default_improvement_index_path(root))
    active_id = index.get("active_cycle_id")
    cycle: ImprovementCycle | None = None
    cycle_ref: str | None = None
    if active_id:
        try:
            path = resolve_cycle_path(root, str(active_id))
            cycle = ImprovementCycleStore().load(path)
            cycle_ref = _relative(path, root)
        except FileNotFoundError:
            cycle = None
    if cycle is None:
        cycles = ImprovementCycleStore().list(default_cycles_dir(root))
        if cycles:
            cycle = cycles[0]
            cycle_ref = _cycle_ref(root, cycle.cycle_id)
    if cycle is None:
        return {}
    return {
        "cycle_id": cycle.cycle_id,
        "cycle_ref": cycle_ref,
        "workset_name": cycle.workset_name,
        "status": cycle.status,
        "selected_bottleneck_kind": cycle.selected_bottleneck_kind,
        "selected_fix_summary": cycle.selected_fix_summary,
        "hypothesis": cycle.hypothesis,
        "verdict": cycle.verdict,
    }


def _cycle_from_dict(payload: dict[str, Any]) -> ImprovementCycle:
    before = payload.get("before_snapshot") if isinstance(payload.get("before_snapshot"), dict) else {}
    after = payload.get("after_snapshot") if isinstance(payload.get("after_snapshot"), dict) else None
    return ImprovementCycle(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        cycle_id=str(payload.get("cycle_id") or f"cycle-unknown-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        week_id=str(payload.get("week_id") or _week_id()),
        workset_name=str(payload.get("workset_name") or "unknown"),
        status=str(payload.get("status") or "planned"),
        selected_bottleneck_kind=str(payload.get("selected_bottleneck_kind")) if payload.get("selected_bottleneck_kind") is not None else None,
        selected_bottleneck_summary=str(payload.get("selected_bottleneck_summary")) if payload.get("selected_bottleneck_summary") is not None else None,
        selected_fix_kind=str(payload.get("selected_fix_kind")) if payload.get("selected_fix_kind") is not None else None,
        selected_fix_summary=str(payload.get("selected_fix_summary")) if payload.get("selected_fix_summary") is not None else None,
        hypothesis=str(payload.get("hypothesis") or ""),
        before_snapshot=_snapshot_from_dict(before),
        after_snapshot=_snapshot_from_dict(after) if isinstance(after, dict) else None,
        verdict=str(payload.get("verdict")) if payload.get("verdict") is not None else None,
        evidence_refs=dict(payload.get("evidence_refs", {})) if isinstance(payload.get("evidence_refs"), dict) else {},
        summary=[str(item) for item in payload.get("summary", [])] if isinstance(payload.get("summary"), list) else [],
        next_actions=[str(item) for item in payload.get("next_actions", [])] if isinstance(payload.get("next_actions"), list) else [],
        warnings=[str(item) for item in payload.get("warnings", [])] if isinstance(payload.get("warnings"), list) else [],
        errors=[str(item) for item in payload.get("errors", [])] if isinstance(payload.get("errors"), list) else [],
    )


def _snapshot_from_dict(payload: dict[str, Any]) -> ImprovementMetricSnapshot:
    return ImprovementMetricSnapshot(**{key: _score(payload.get(key)) for key in METRIC_KEYS})


def _latest_evidence_refs(root: Path, workset_name: str, *, prefix: str) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    metrics = _latest_simple(root / ".cambrian" / "metrics" / "latest.yaml")
    compare = _latest_matching(root, root / ".cambrian" / "benchmarks" / "latest_compare.yaml", root / ".cambrian" / "benchmarks" / "compares", "compare_*.yaml", workset_name)
    bottleneck = _latest_matching(root, root / ".cambrian" / "benchmarks" / "latest_bottleneck.yaml", root / ".cambrian" / "benchmarks" / "bottlenecks", "bottlenecks_*.yaml", workset_name)
    proof = _latest_matching(root, root / ".cambrian" / "benchmarks" / "proof" / "latest.yaml", root / ".cambrian" / "benchmarks" / "proof", "proof_*.yaml", workset_name)
    if metrics:
        refs[f"{prefix}_metrics_ref"] = metrics
    if compare:
        refs[f"{prefix}_compare_ref"] = compare
    if bottleneck:
        refs[f"{prefix}_bottleneck_ref"] = bottleneck
    if proof:
        refs[f"{prefix}_proof_ref"] = proof
    return refs


def _latest_simple(path: Path) -> str | None:
    if path.exists():
        return _relative(path, path.parents[2] if len(path.parents) > 2 else path.parent)
    return None


def _latest_matching(root: Path, latest_path: Path, directory: Path, pattern: str, workset_name: str) -> str | None:
    payload = _load_yaml(latest_path)
    if payload and str(payload.get("workset_name") or "") == workset_name:
        return _relative(latest_path, root)
    candidates: list[Path] = []
    if directory.exists():
        for path in directory.glob(pattern):
            item = _load_yaml(path)
            if str(item.get("workset_name") or "") == workset_name:
                candidates.append(path)
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return _relative(candidates[0], root) if candidates else None


def _load_ref_payload(root: Path, ref: Any) -> dict[str, Any]:
    if not ref:
        return {}
    path = Path(str(ref))
    if not path.is_absolute():
        path = root / path
    return _load_yaml(path)


def _snapshot_from_evidence(
    metrics_payload: dict[str, Any],
    proof_payload: dict[str, Any],
    compare_payload: dict[str, Any],
) -> ImprovementMetricSnapshot:
    metrics_summary = metrics_payload.get("summary") if isinstance(metrics_payload.get("summary"), dict) else {}
    proof_metrics = proof_payload.get("key_metrics") if isinstance(proof_payload.get("key_metrics"), dict) else {}
    compare_metrics = _metrics_from_compare(compare_payload)
    values: dict[str, Any] = {}
    for key in METRIC_KEYS:
        values[key] = _first_value(metrics_summary.get(key), proof_metrics.get(key), compare_metrics.get(key))
    if values.get("median_time_to_validated_proposal") is None:
        values["median_time_to_validated_proposal"] = _first_value(
            metrics_summary.get("median_duration_seconds"),
            proof_metrics.get("median_duration_seconds"),
            compare_metrics.get("median_duration_seconds"),
        )
    return _snapshot_from_dict(values)


def _metrics_from_compare(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    compares = payload.get("mode_compares")
    if not isinstance(compares, list):
        return result
    preferred = None
    for item in compares:
        if isinstance(item, dict) and item.get("mode") == payload.get("best_mode_now"):
            preferred = item
            break
    if preferred is None:
        preferred = next((item for item in compares if isinstance(item, dict)), None)
    if not isinstance(preferred, dict):
        return result
    deltas = preferred.get("deltas")
    if not isinstance(deltas, list):
        return result
    for delta in deltas:
        if not isinstance(delta, dict):
            continue
        key = str(delta.get("key") or "")
        current = delta.get("current_value")
        if key == "median_duration_seconds":
            result["median_time_to_validated_proposal"] = current
        elif key:
            result[key] = current
    return result


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _select_bottleneck(payload: dict[str, Any], explicit_kind: str | None) -> dict[str, Any] | None:
    items = payload.get("bottlenecks")
    if not isinstance(items, list):
        return None
    candidates = [item for item in items if isinstance(item, dict)]
    if explicit_kind:
        for item in candidates:
            if item.get("kind") == explicit_kind:
                return item
        return None
    candidates.sort(
        key=lambda item: (
            _severity_rank(str(item.get("severity") or "")),
            int(item.get("frequency") or 0),
        ),
        reverse=True,
    )
    return candidates[0] if candidates else None


def _select_suggestion(payload: dict[str, Any], bottleneck: dict[str, Any] | None) -> dict[str, Any] | None:
    items = payload.get("suggestions")
    if not isinstance(items, list):
        return None
    suggestions = [item for item in items if isinstance(item, dict)]
    if not suggestions:
        return None
    if bottleneck:
        kind = str(bottleneck.get("kind") or "")
        for item in suggestions:
            reasons = " ".join(str(reason) for reason in item.get("reasons", []) if reason)
            if kind and kind in reasons:
                return item
    suggestions.sort(
        key=lambda item: (
            _severity_rank(str(item.get("priority") or "")),
            float(item.get("confidence") or 0),
        ),
        reverse=True,
    )
    return suggestions[0]


def _severity_rank(value: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(value, 0)


def _hypothesis(fix_kind: str | None, bottleneck_kind: str | None, fix_summary: str | None) -> str:
    templates = {
        "strengthen_context_hints": "stronger auth file/test context hints will reduce ambiguity and raise validated proposal rate",
        "improve_validation_support": "better validation support should reduce stops after patch intent and increase validation autonomy",
        "narrow_scope_defaults": "stronger narrow-scope defaults should reduce refactor drift and improve validation success",
        "add_bridge_patch_candidate": "better bridge patch candidate coverage should reduce manual old/new entry and improve validation autonomy",
        "review_team_fit": "a better fitting team should reduce support gaps and improve validated proposal rate",
        "review_template_fit": "a better fitting template should reduce repeated stalls and improve repeat task performance",
        "improve_bridge_coverage": "stronger bridge coverage should raise full-mode autonomy on this workset",
    }
    if fix_kind in templates:
        return templates[fix_kind]
    if fix_summary:
        return f"{fix_summary} should reduce {bottleneck_kind or 'the selected bottleneck'} and improve benchmark outcomes"
    return "one focused fix should reduce the selected bottleneck and improve benchmark outcomes"


def _next_actions(workset_name: str) -> list[str]:
    return [
        "implement exactly one fix",
        f"cambrian benchmark replay-workset {workset_name} --mode cambrian_guided",
        f"cambrian benchmark replay-workset {workset_name} --mode cambrian_full",
        f"cambrian benchmark autonomy-board {workset_name}",
        f"cambrian benchmark compare {workset_name}",
        "cambrian metrics week --save",
        "cambrian improve evaluate <cycle-id>",
    ]


def _evaluate_verdict(
    *,
    before: ImprovementMetricSnapshot,
    after: ImprovementMetricSnapshot,
    before_frequency: int | None,
    after_frequency: int | None,
) -> tuple[str, list[str], list[str]]:
    summary: list[str] = []
    warnings: list[str] = []
    positives = 0
    negatives = 0
    comparable = 0

    for key, direction in [
        ("validated_proposal_rate", "higher"),
        ("human_intervention_rate", "lower"),
        ("validation_autonomy_rate", "higher"),
        ("repeat_task_improvement_rate", "higher"),
        ("reuse_lift", "higher"),
        ("regression_free_apply_rate", "higher"),
    ]:
        before_value = getattr(before, key)
        after_value = getattr(after, key)
        delta = _delta(before_value, after_value)
        if delta is None:
            continue
        comparable += 1
        improved = delta >= 0.05 if direction == "higher" else delta <= -0.05
        regressed = delta <= -0.05 if direction == "higher" else delta >= 0.05
        if improved:
            positives += 1
            summary.append(f"{key} improved {_format_delta(delta, key)}")
        elif regressed:
            negatives += 1
            summary.append(f"{key} regressed {_format_delta(delta, key)}")
        else:
            summary.append(f"{key} stayed stable {_format_delta(delta, key)}")

    if before_frequency is not None and after_frequency is not None:
        comparable += 1
        frequency_delta = after_frequency - before_frequency
        if frequency_delta <= -1:
            positives += 1
            summary.append(f"selected bottleneck frequency decreased {frequency_delta}")
        elif frequency_delta >= 1:
            negatives += 1
            summary.append(f"selected bottleneck frequency increased +{frequency_delta}")
        else:
            summary.append("selected bottleneck frequency stayed stable")
    else:
        warnings.append("selected bottleneck frequency was not comparable")

    if comparable == 0:
        return "inconclusive", summary, [*warnings, "no comparable before/after metrics"]
    if negatives and positives:
        return "mixed", summary, warnings
    if negatives:
        return "regressed", summary, warnings
    if positives:
        return "improved", summary, warnings
    return "inconclusive", summary, [*warnings, "metrics were comparable but did not move materially"]


def _delta(before_value: float | None, after_value: float | None) -> float | None:
    if before_value is None or after_value is None:
        return None
    return round(after_value - before_value, 4)


def _format_delta(delta: float, key: str) -> str:
    if key == "median_time_to_validated_proposal":
        return f"{delta:+.0f}s"
    return f"{delta * 100:+.0f}pt"


def _bottleneck_frequency(payload: dict[str, Any], kind: str | None) -> int | None:
    if not kind:
        return None
    items = payload.get("bottlenecks")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("kind") == kind:
            try:
                return int(item.get("frequency") or 0)
            except (TypeError, ValueError):
                return None
    return 0


def _snapshot_lines(snapshot: ImprovementMetricSnapshot, prefix: str) -> list[str]:
    return [
        f"{prefix}validated proposal rate : {_format_rate(snapshot.validated_proposal_rate)}",
        f"{prefix}human intervention rate : {_format_rate(snapshot.human_intervention_rate)}",
        f"{prefix}validation autonomy     : {_format_rate(snapshot.validation_autonomy_rate)}",
        f"{prefix}repeat improvement      : {_format_points(snapshot.repeat_task_improvement_rate)}",
        f"{prefix}reuse lift              : {_format_points(snapshot.reuse_lift)}",
    ]


def _format_rate(value: Any) -> str:
    number = _score(value)
    if number is None:
        return "n/a"
    return f"{number * 100:.0f}%"


def _format_points(value: Any) -> str:
    number = _score(value)
    if number is None:
        return "n/a"
    return f"{number * 100:+.0f}pt"


def _cycle_ref(root: Path, cycle_id: str) -> str | None:
    for path in default_cycles_dir(root).glob("cycle_*.yaml"):
        payload = _load_yaml(path)
        if payload.get("cycle_id") == cycle_id:
            return _relative(path, root)
    return None


def close_cycle(project_root: Path, cycle_path: Path, resolution: str | None = None) -> ImprovementCycle:
    """cycle을 닫고 active pointer를 정리한다."""
    root = Path(project_root).resolve()
    path = Path(cycle_path).resolve()
    cycle = ImprovementCycleStore().load(path)
    cycle.status = "closed"
    cycle.updated_at = _now()
    if resolution:
        cycle.summary = _dedupe([*cycle.summary, f"resolution: {resolution}"])
    ImprovementCycleStore().update(path, cycle)
    return cycle
