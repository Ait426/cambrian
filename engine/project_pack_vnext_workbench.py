"""pack derivative change를 vNext work order로 추적하는 로컬 workbench."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.project_pack_derivatives import (
    PackDerivativeChange,
    PackDerivativePlan,
    PackDerivativeStore,
    default_pack_derivative_workspaces_dir,
    resolve_pack_derivative_plan_path,
)
from engine.project_pack_install import SCHEMA_VERSION, _as_list, _load_yaml, _now, _relative, _save_yaml

logger = logging.getLogger(__name__)


WORKORDER_KINDS = {
    "metadata_update",
    "known_limits_update",
    "first_job_guide_update",
    "template_evolution",
    "team_review",
    "benchmark_case",
    "response_contract_review",
    "pack_docs_update",
    "release_check",
}


@dataclass
class PackWorkOrder:
    """vNext pack을 release-ready로 만들기 위한 명시적 작업 항목."""

    schema_version: str
    workorder_id: str
    created_at: str
    updated_at: str | None
    pack_ref: str
    pack_id: str
    pack_name: str | None
    namespace: str | None
    version: str | None
    derivative_plan_ref: str | None
    derivative_change_id: str | None
    source_improvement_id: str | None
    kind: str
    status: str
    required: bool
    priority: str
    title: str
    summary: str
    reason: str
    suggested_commands: list[str] = field(default_factory=list)
    affected_metrics: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    completion_note: str | None = None
    completed_evidence_refs: list[str] = field(default_factory=list)
    completed_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackVNextWorkbench:
    """derivative plan에서 파생된 vNext 작업판."""

    schema_version: str
    workbench_id: str
    generated_at: str
    updated_at: str | None
    source_pack_ref: str
    source_pack_id: str
    target_pack_id: str | None
    target_version: str | None
    derivative_plan_ref: str
    derivative_workspace_ref: str | None
    draft_ref: str | None
    workorders: list[PackWorkOrder] = field(default_factory=list)
    open_required_count: int = 0
    done_required_count: int = 0
    skipped_required_count: int = 0
    release_ready: bool = False
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        payload = asdict(self)
        payload["workorders"] = [order.to_dict() for order in self.workorders]
        return payload


@dataclass
class PackWorkOrderDecision:
    """workorder-done/skip 결과를 기록하는 결정."""

    schema_version: str
    decision_id: str
    created_at: str
    workorder_id: str
    status: str
    note: str | None
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """YAML 저장용 dict로 변환한다."""
        return asdict(self)


class PackVNextWorkbenchBuilder:
    """derivative plan을 실행 가능한 work order 모음으로 바꾼다."""

    def build(self, project_root: Path, plan_path: Path) -> PackVNextWorkbench:
        """plan의 derivative changes를 workbench로 변환한다."""
        root = Path(project_root).resolve()
        resolved_plan = resolve_pack_derivative_plan_path(root, str(plan_path))
        plan = PackDerivativeStore().load_plan(resolved_plan)
        plan_ref = _relative(resolved_plan, root)
        workspace_ref, draft_ref = _latest_derivative_workspace_for_plan(root, plan, plan_ref)
        orders = _orders_from_plan(plan, plan_ref)
        workbench = PackVNextWorkbench(
            schema_version=SCHEMA_VERSION,
            workbench_id=f"vnext-workbench-{_slug(plan.suggested_target_pack_id)}-{_stamp()}",
            generated_at=_now(),
            updated_at=None,
            source_pack_ref=plan.source_pack_ref,
            source_pack_id=plan.source_pack_id,
            target_pack_id=plan.suggested_target_pack_id,
            target_version=plan.suggested_version,
            derivative_plan_ref=plan_ref,
            derivative_workspace_ref=workspace_ref,
            draft_ref=draft_ref,
            workorders=orders,
            summary=[],
            next_actions=[],
            warnings=list(plan.warnings),
            errors=list(plan.errors),
        )
        return _recalculate_workbench(workbench)


class PackWorkOrderStore:
    """vNext workbench/workorder 파일 저장소."""

    def save_workbench(self, workbench: PackVNextWorkbench, path: Path) -> Path:
        """workbench를 YAML로 저장한다."""
        return _save_yaml(Path(path).resolve(), workbench.to_dict())

    def load_workbench(self, path: Path) -> PackVNextWorkbench:
        """workbench YAML을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack vNext workbench not found: {path}")
        return _workbench_from_dict(payload)

    def save_workorder(self, order: PackWorkOrder, path: Path) -> Path:
        """work order를 YAML로 저장한다."""
        return _save_yaml(Path(path).resolve(), order.to_dict())

    def load_workorder(self, path: Path) -> PackWorkOrder:
        """work order YAML을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack workorder not found: {path}")
        return _workorder_from_dict(payload)

    def list_workorders(self, directory: Path, pack_id: str | None = None, status: str | None = None) -> list[PackWorkOrder]:
        """저장된 work order 목록을 조회한다."""
        target = Path(directory).resolve()
        if not target.exists():
            return []
        orders: list[PackWorkOrder] = []
        for path in sorted(target.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                order = self.load_workorder(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pack workorder load skipped: %s", exc)
                continue
            if pack_id and not (_pack_matches(order.pack_id, pack_id) or _pack_matches(order.pack_ref, pack_id)):
                continue
            if status and order.status != status:
                continue
            orders.append(order)
        return orders


class PackWorkOrderDecisionStore:
    """work order decision ledger."""

    def add_decision(self, path: Path, decision: PackWorkOrderDecision) -> Path:
        """decision을 누적 저장한다."""
        target = Path(path).resolve()
        payload = _load_yaml(target) if target.exists() else {}
        decisions = [item for item in payload.get("decisions", []) if isinstance(item, dict)]
        decisions.append(decision.to_dict())
        return _save_yaml(
            target,
            {
                "schema_version": SCHEMA_VERSION,
                "updated_at": _now(),
                "decisions": decisions,
            },
        )


def default_pack_vnext_root(project_root: Path) -> Path:
    """vNext artifact root를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "vnext"


def default_pack_vnext_workbenches_dir(project_root: Path) -> Path:
    """workbench 저장 디렉터리를 반환한다."""
    return default_pack_vnext_root(project_root) / "workbenches"


def default_pack_vnext_workorders_dir(project_root: Path) -> Path:
    """workorder 저장 디렉터리를 반환한다."""
    return default_pack_vnext_root(project_root) / "workorders"


def default_pack_vnext_decisions_path(project_root: Path) -> Path:
    """workorder decision ledger 경로를 반환한다."""
    return default_pack_vnext_root(project_root) / "decisions.yaml"


def default_pack_vnext_latest_workbench_path(project_root: Path) -> Path:
    """latest workbench pointer 경로를 반환한다."""
    return default_pack_vnext_root(project_root) / "latest.yaml"


def default_pack_vnext_workbench_path(project_root: Path, workbench: PackVNextWorkbench) -> Path:
    """workbench 기본 저장 경로를 반환한다."""
    return default_pack_vnext_workbenches_dir(project_root) / f"workbench_{_slug(workbench.target_pack_id)}_{_stamp()}.yaml"


def default_pack_vnext_workorder_path(project_root: Path, order: PackWorkOrder) -> Path:
    """workorder 기본 저장 경로를 반환한다."""
    return default_pack_vnext_workorders_dir(project_root) / f"{order.workorder_id}.yaml"


def save_pack_vnext_workbench(project_root: Path, workbench: PackVNextWorkbench) -> str:
    """workbench와 포함 workorder를 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    store = PackWorkOrderStore()
    saved_orders: list[PackWorkOrder] = []
    for order in workbench.workorders:
        store.save_workorder(order, default_pack_vnext_workorder_path(root, order))
        saved_orders.append(order)
    workbench.workorders = saved_orders
    path = store.save_workbench(workbench, default_pack_vnext_workbench_path(root, workbench))
    try:
        store.save_workbench(workbench, default_pack_vnext_latest_workbench_path(root))
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest vNext workbench save failed: %s", exc)
    return _relative(path, root)


def resolve_pack_workorder_path(project_root: Path, workorder_ref: str) -> Path:
    """workorder id/path/latest를 실제 파일 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw_ref = str(workorder_ref or "").strip()
    if not raw_ref:
        raise FileNotFoundError("pack workorder ref is required")
    if raw_ref == "latest":
        latest = _latest_workorder_path(root)
        if latest is not None:
            return latest
    raw = Path(raw_ref)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend(
            [
                root / raw,
                default_pack_vnext_workorders_dir(root) / raw,
                default_pack_vnext_workorders_dir(root) / f"{raw}.yaml",
                default_pack_vnext_workorders_dir(root) / f"{_slug(raw_ref)}.yaml",
            ]
        )
    for path in candidates:
        if path.exists():
            return path.resolve()
    orders_dir = default_pack_vnext_workorders_dir(root)
    if orders_dir.exists():
        for path in sorted(orders_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = _load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("workorder resolve skipped: %s", exc)
                continue
            if str(payload.get("workorder_id") or "") == raw_ref:
                return path.resolve()
    raise FileNotFoundError(f"pack workorder not found: {workorder_ref}")


def latest_pack_vnext_workbench(project_root: Path, pack_ref: str | None = None) -> PackVNextWorkbench | None:
    """pack에 해당하는 최신 vNext workbench를 찾는다."""
    root = Path(project_root).resolve()
    store = PackWorkOrderStore()
    candidates: list[Path] = []
    workbenches_dir = default_pack_vnext_workbenches_dir(root)
    if workbenches_dir.exists():
        candidates.extend(sorted(workbenches_dir.glob("workbench_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
    latest = default_pack_vnext_latest_workbench_path(root)
    if latest.exists():
        candidates.append(latest)
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            workbench = store.load_workbench(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vNext workbench load skipped: %s", exc)
            continue
        if pack_ref is None or _workbench_matches(workbench, pack_ref):
            return workbench
    return None


def unresolved_required_workorders_for_derivative(
    project_root: Path,
    derivative: dict[str, Any] | None,
    pack_ref: str | None = None,
) -> list[PackWorkOrder]:
    """draft/manifest derivative metadata에 연결된 미완료 required workorder를 찾는다."""
    if not derivative:
        return []
    root = Path(project_root).resolve()
    plan_ref = str(derivative.get("source_plan_ref") or "").strip()
    workbench = _latest_workbench_for_plan_ref(root, plan_ref, pack_ref)
    if workbench is None:
        return []
    return [
        order
        for order in workbench.workorders
        if order.required and order.status in {"open", "blocked", "skipped"}
    ]


def record_pack_workorder_decision(
    project_root: Path,
    workorder_ref: str,
    status: str,
    note: str | None = None,
    evidence_refs: list[str] | None = None,
) -> tuple[PackWorkOrderDecision, PackWorkOrder, str]:
    """workorder 완료/스킵 결정을 저장하고 관련 workbench를 갱신한다."""
    root = Path(project_root).resolve()
    normalized = str(status or "").strip()
    if normalized not in {"done", "skipped", "blocked"}:
        raise ValueError("workorder decision status must be done, skipped, or blocked")
    evidence = _dedupe([str(item) for item in (evidence_refs or []) if item])
    clean_note = str(note).strip() if note is not None else None
    if normalized == "done" and not evidence and not clean_note:
        raise ValueError("workorder-done requires --evidence or --note")
    if normalized == "skipped" and not clean_note:
        raise ValueError("workorder-skip requires --note")
    order_path = resolve_pack_workorder_path(root, workorder_ref)
    store = PackWorkOrderStore()
    order = store.load_workorder(order_path)
    decision = PackWorkOrderDecision(
        schema_version=SCHEMA_VERSION,
        decision_id=f"workorder-decision-{_slug(order.workorder_id)}-{_stamp()}",
        created_at=_now(),
        workorder_id=order.workorder_id,
        status=normalized,
        note=clean_note,
        evidence_refs=evidence,
        warnings=[],
        errors=[],
    )
    order.status = normalized
    order.updated_at = decision.created_at
    order.completion_note = clean_note
    order.completed_evidence_refs = evidence
    order.completed_at = decision.created_at if normalized == "done" else None
    store.save_workorder(order, order_path)
    PackWorkOrderDecisionStore().add_decision(default_pack_vnext_decisions_path(root), decision)
    _refresh_workbenches_for_order(root, order)
    return decision, order, _relative(order_path, root)


def render_pack_vnext_workbench(workbench: PackVNextWorkbench) -> str:
    """workbench 생성 결과를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack VNext Workbench",
        "==================================================",
        "",
        "Target:",
        f"  {workbench.target_pack_id or 'unknown'}",
        "",
        "Required work orders:",
    ]
    required = [order for order in workbench.workorders if order.required]
    lines.extend([f"  - {order.title}" for order in required] or ["  none"])
    lines.extend(["", "Release ready:", f"  {'yes' if workbench.release_ready else 'no'}"])
    if workbench.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in workbench.next_actions])
    if workbench.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in workbench.warnings])
    if workbench.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in workbench.errors])
    return "\n".join(lines)


def render_pack_workorders(orders: list[PackWorkOrder], status: str | None = None) -> str:
    """workorder 목록을 렌더링한다."""
    title = "Pack Work Orders" if status is None else f"Pack Work Orders ({status})"
    lines = [title, "==================================================", ""]
    if not orders:
        lines.append("No work orders found.")
        return "\n".join(lines)
    for order in orders:
        required = "required" if order.required else "optional"
        lines.append(f"- {order.workorder_id}: {order.kind} [{order.status}, {required}, {order.priority}]")
        lines.append(f"  {order.title}")
        if order.suggested_commands:
            lines.append(f"  next: {order.suggested_commands[0]}")
    return "\n".join(lines)


def render_pack_workorder(order: PackWorkOrder) -> str:
    """단일 workorder 상세를 렌더링한다."""
    lines = [
        "Pack Work Order",
        "==================================================",
        "",
        "Work order:",
        f"  {order.workorder_id}",
        "",
        "Kind:",
        f"  {order.kind}",
        "",
        "Status:",
        f"  {order.status}",
        "",
        "Required:",
        f"  {'yes' if order.required else 'no'}",
        "",
        "Why:",
        f"  {order.reason or order.summary}",
        "",
        "Affected metrics:",
    ]
    lines.extend([f"  - {item}" for item in order.affected_metrics] or ["  none"])
    lines.extend(["", "Suggested commands:"])
    lines.extend([f"  {item}" for item in order.suggested_commands] or ["  none"])
    if order.evidence_refs:
        lines.extend(["", "Evidence refs:"])
        lines.extend([f"  - {item}" for item in order.evidence_refs])
    lines.extend(["", "Mark done:"])
    lines.append(f"  cambrian pack workorder-done {order.workorder_id} --evidence <path>")
    if order.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in order.warnings])
    if order.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in order.errors])
    return "\n".join(lines)


def render_pack_workorder_decision(decision: PackWorkOrderDecision, order: PackWorkOrder) -> str:
    """workorder decision 결과를 렌더링한다."""
    lines = [
        "Pack Work Order Decision Recorded",
        "==================================================",
        "",
        "Work order:",
        f"  {order.workorder_id}",
        "",
        "Status:",
        f"  {decision.status}",
    ]
    if decision.note:
        lines.extend(["", "Note:", f"  {decision.note}"])
    if decision.evidence_refs:
        lines.extend(["", "Evidence:"])
        lines.extend([f"  - {item}" for item in decision.evidence_refs])
    lines.extend(["", "Next:", f"  cambrian pack workorders {order.pack_id}"])
    return "\n".join(lines)


def render_pack_vnext_compact(workbench: PackVNextWorkbench | None) -> str:
    """pack show에 붙일 compact vNext workbench 요약."""
    if workbench is None:
        return ""
    open_count = len([order for order in workbench.workorders if order.status == "open"])
    return "\n".join(
        [
            "VNext workbench:",
            f"  open work orders: {open_count}",
            f"  release ready: {'yes' if workbench.release_ready else 'no'}",
        ]
    )


def render_status_pack_vnext(workbench: PackVNextWorkbench | None) -> str:
    """status에 붙일 vNext workbench 요약."""
    if workbench is None:
        return ""
    open_count = len([order for order in workbench.workorders if order.status == "open"])
    if open_count <= 0:
        return ""
    return "\n".join(
        [
            "Pack vNext:",
            f"  {open_count} open work orders for {workbench.target_pack_id or workbench.source_pack_id}",
            f"  next: cambrian pack workorders {workbench.source_pack_id}",
        ]
    )


def _orders_from_plan(plan: PackDerivativePlan, plan_ref: str) -> list[PackWorkOrder]:
    orders = [_order_from_change(plan, change, plan_ref) for change in plan.changes]
    if plan.changes:
        orders.append(_release_check_order(plan, plan_ref))
    return sorted(_dedupe_orders(orders), key=lambda order: (-_priority_rank(order.priority), not order.required, order.kind, order.workorder_id))


def _order_from_change(plan: PackDerivativePlan, change: PackDerivativeChange, plan_ref: str) -> PackWorkOrder:
    kind = _workorder_kind(change.kind)
    required = _workorder_required(change.kind)
    priority = _workorder_priority(change, required)
    return PackWorkOrder(
        schema_version=SCHEMA_VERSION,
        workorder_id=f"wo-{_slug(plan.source_pack_id)}-{_slug(kind)}-{_slug(change.change_id)}-{_stamp()}",
        created_at=_now(),
        updated_at=None,
        pack_ref=plan.source_pack_ref,
        pack_id=plan.source_pack_id,
        pack_name=plan.source_pack_name,
        namespace=plan.namespace,
        version=plan.source_version,
        derivative_plan_ref=plan_ref,
        derivative_change_id=change.change_id,
        source_improvement_id=change.source_improvement_id,
        kind=kind,
        status="open",
        required=required,
        priority=priority,
        title=_workorder_title(kind, change),
        summary=change.summary,
        reason=change.reason,
        suggested_commands=_suggested_commands(kind, change),
        affected_metrics=list(change.affected_metrics),
        evidence_refs=list(change.evidence_refs),
        warnings=[] if change.status != "unresolved" else ["manual execution required; workbench will not mutate project artifacts"],
        errors=[],
    )


def _release_check_order(plan: PackDerivativePlan, plan_ref: str) -> PackWorkOrder:
    return PackWorkOrder(
        schema_version=SCHEMA_VERSION,
        workorder_id=f"wo-{_slug(plan.source_pack_id)}-release-check-{_stamp()}",
        created_at=_now(),
        updated_at=None,
        pack_ref=plan.source_pack_ref,
        pack_id=plan.source_pack_id,
        pack_name=plan.source_pack_name,
        namespace=plan.namespace,
        version=plan.source_version,
        derivative_plan_ref=plan_ref,
        derivative_change_id=None,
        source_improvement_id=None,
        kind="release_check",
        status="open",
        required=False,
        priority="low",
        title="Run vNext release check",
        summary="Run validate/build/release-check after required work orders are complete.",
        reason="release readiness must remain explicit",
        suggested_commands=[
            "cambrian pack validate <draft>",
            "cambrian pack build <draft>",
            "cambrian pack release-check <manifest>",
        ],
        affected_metrics=["reuse_lift", "repeat_task_improvement_rate"],
        evidence_refs=list(plan.accepted_improvement_refs),
        warnings=[],
        errors=[],
    )


def _workorder_kind(change_kind: str) -> str:
    mapping = {
        "metadata_only": "metadata_update",
        "known_limits_update": "known_limits_update",
        "first_job_guide_update": "first_job_guide_update",
        "template_evolution_required": "template_evolution",
        "team_review_required": "team_review",
        "benchmark_case_required": "benchmark_case",
        "response_contract_required": "response_contract_review",
        "pack_derivative_required": "pack_docs_update",
    }
    return mapping.get(change_kind, "metadata_update")


def _workorder_required(change_kind: str) -> bool:
    return change_kind in {
        "known_limits_update",
        "first_job_guide_update",
        "template_evolution_required",
        "team_review_required",
        "benchmark_case_required",
        "response_contract_required",
    }


def _workorder_priority(change: PackDerivativeChange, required: bool) -> str:
    metrics = set(change.affected_metrics)
    if change.status == "blocked" or "regression_free_apply_rate" in metrics:
        return "high"
    if required and ({"validated_proposal_rate", "adoption_rate", "human_intervention_rate", "validation_autonomy_rate"} & metrics):
        return "high"
    if required:
        return "medium"
    return "low"


def _workorder_title(kind: str, change: PackDerivativeChange) -> str:
    labels = {
        "metadata_update": "Update derivative metadata",
        "known_limits_update": "Update pack known limits",
        "first_job_guide_update": "Update first-job guide",
        "template_evolution": "Evolve template context/defaults",
        "team_review": "Review pack team fit",
        "benchmark_case": "Add or review benchmark case",
        "response_contract_review": "Review bridge response contract",
        "pack_docs_update": "Update pack derivative docs",
        "release_check": "Run release check",
    }
    return f"{labels.get(kind, kind.replace('_', ' '))}: {change.title}"


def _suggested_commands(kind: str, change: PackDerivativeChange) -> list[str]:
    if change.required_commands:
        return list(change.required_commands)
    mapping = {
        "metadata_update": ["cambrian pack workorder-done <workorder> --note \"metadata reviewed\""],
        "known_limits_update": ["cambrian pack workorder-done <workorder> --note \"known limits updated in draft metadata\""],
        "first_job_guide_update": ["cambrian pack next <pack>", "cambrian pack workorder-done <workorder> --note \"first-job guide updated\""],
        "template_evolution": ["cambrian template evolve <template>", "cambrian template evolve-accept <proposal>"],
        "team_review": ["cambrian team recommend"],
        "benchmark_case": ["cambrian benchmark case-add ..."],
        "response_contract_review": ["review bridge response contract manually"],
        "pack_docs_update": ["cambrian pack workorder-done <workorder> --note \"pack docs updated\""],
    }
    return mapping.get(kind, [])


def _recalculate_workbench(workbench: PackVNextWorkbench) -> PackVNextWorkbench:
    required = [order for order in workbench.workorders if order.required]
    open_required = [order for order in required if order.status in {"open", "blocked"}]
    done_required = [order for order in required if order.status == "done"]
    skipped_required = [order for order in required if order.status == "skipped"]
    workbench.open_required_count = len(open_required)
    workbench.done_required_count = len(done_required)
    workbench.skipped_required_count = len(skipped_required)
    workbench.release_ready = bool(workbench.draft_ref) and not open_required and not skipped_required
    workbench.summary = [
        f"target={workbench.target_pack_id}",
        f"workorders={len(workbench.workorders)}",
        f"open_required={workbench.open_required_count}",
        f"done_required={workbench.done_required_count}",
        f"skipped_required={workbench.skipped_required_count}",
        f"release_ready={workbench.release_ready}",
    ]
    first_open = next((order for order in workbench.workorders if order.status == "open"), None)
    workbench.next_actions = [f"cambrian pack workorder-show {first_open.workorder_id}"] if first_open else _release_next_actions(workbench)
    if skipped_required:
        workbench.warnings = _dedupe([*workbench.warnings, "required work orders were skipped; release readiness remains blocked"])
    return workbench


def _release_next_actions(workbench: PackVNextWorkbench) -> list[str]:
    if not workbench.release_ready:
        return [f"cambrian pack workorders {workbench.source_pack_id}"]
    if workbench.draft_ref:
        return [
            f"cambrian pack validate {workbench.draft_ref}",
            f"cambrian pack build {workbench.draft_ref}",
        ]
    return []


def _refresh_workbenches_for_order(root: Path, order: PackWorkOrder) -> None:
    store = PackWorkOrderStore()
    workbenches_dir = default_pack_vnext_workbenches_dir(root)
    candidates: list[Path] = []
    if workbenches_dir.exists():
        candidates.extend(workbenches_dir.glob("workbench_*.yaml"))
    latest = default_pack_vnext_latest_workbench_path(root)
    if latest.exists():
        candidates.append(latest)
    for path in _dedupe_paths(candidates):
        try:
            workbench = store.load_workbench(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vNext workbench refresh skipped: %s", exc)
            continue
        changed = False
        for idx, existing in enumerate(workbench.workorders):
            if existing.workorder_id == order.workorder_id:
                workbench.workorders[idx] = order
                changed = True
        if changed:
            workbench.updated_at = _now()
            store.save_workbench(_recalculate_workbench(workbench), path)


def _latest_derivative_workspace_for_plan(root: Path, plan: PackDerivativePlan, plan_ref: str) -> tuple[str | None, str | None]:
    store = PackDerivativeStore()
    workspaces_dir = default_pack_derivative_workspaces_dir(root)
    if not workspaces_dir.exists():
        return None, None
    for path in sorted(workspaces_dir.glob("workspace_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            workspace = store.load_workspace(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("derivative workspace lookup skipped: %s", exc)
            continue
        if _plan_ref_matches(workspace.source_plan_ref, plan_ref, plan.plan_id):
            return _relative(path, root), workspace.draft_ref
    return None, None


def _latest_workbench_for_plan_ref(root: Path, plan_ref: str, pack_ref: str | None = None) -> PackVNextWorkbench | None:
    store = PackWorkOrderStore()
    candidates: list[Path] = []
    workbenches_dir = default_pack_vnext_workbenches_dir(root)
    if workbenches_dir.exists():
        candidates.extend(sorted(workbenches_dir.glob("workbench_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
    for path in candidates:
        try:
            workbench = store.load_workbench(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vNext workbench lookup skipped: %s", exc)
            continue
        if pack_ref and not _workbench_matches(workbench, pack_ref):
            continue
        if not plan_ref or _plan_ref_matches(workbench.derivative_plan_ref, plan_ref, plan_ref):
            return workbench
    return None


def _latest_workorder_path(root: Path) -> Path | None:
    orders_dir = default_pack_vnext_workorders_dir(root)
    if not orders_dir.exists():
        return None
    paths = sorted(orders_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True)
    return paths[0].resolve() if paths else None


def _workbench_matches(workbench: PackVNextWorkbench, pack_ref: str) -> bool:
    return (
        _pack_matches(workbench.source_pack_id, pack_ref)
        or _pack_matches(workbench.source_pack_ref, pack_ref)
        or _pack_matches(workbench.target_pack_id, pack_ref)
    )


def _plan_ref_matches(candidate: str | None, ref: str | None, plan_id: str | None) -> bool:
    raw = str(candidate or "").replace("\\", "/")
    wanted = str(ref or "").replace("\\", "/")
    pid = str(plan_id or "")
    return bool(raw and (raw == wanted or raw.endswith(wanted) or raw == pid or raw.endswith(pid)))


def _workbench_from_dict(payload: dict[str, Any]) -> PackVNextWorkbench:
    orders = [_workorder_from_dict(item) for item in payload.get("workorders", []) if isinstance(item, dict)]
    workbench = PackVNextWorkbench(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        workbench_id=str(payload.get("workbench_id") or f"vnext-workbench-{_stamp()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        source_pack_ref=str(payload.get("source_pack_ref") or payload.get("source_pack_id") or "unknown-pack"),
        source_pack_id=str(payload.get("source_pack_id") or _plain_pack_id(payload.get("source_pack_ref") or "unknown-pack")),
        target_pack_id=str(payload.get("target_pack_id")) if payload.get("target_pack_id") is not None else None,
        target_version=str(payload.get("target_version")) if payload.get("target_version") is not None else None,
        derivative_plan_ref=str(payload.get("derivative_plan_ref") or ""),
        derivative_workspace_ref=str(payload.get("derivative_workspace_ref")) if payload.get("derivative_workspace_ref") is not None else None,
        draft_ref=str(payload.get("draft_ref")) if payload.get("draft_ref") is not None else None,
        workorders=orders,
        open_required_count=int(payload.get("open_required_count") or 0),
        done_required_count=int(payload.get("done_required_count") or 0),
        skipped_required_count=int(payload.get("skipped_required_count") or 0),
        release_ready=bool(payload.get("release_ready")),
        summary=_as_list(payload.get("summary")),
        next_actions=_as_list(payload.get("next_actions")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )
    return _recalculate_workbench(workbench)


def _workorder_from_dict(payload: dict[str, Any]) -> PackWorkOrder:
    return PackWorkOrder(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        workorder_id=str(payload.get("workorder_id") or f"wo-{_stamp()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        pack_ref=str(payload.get("pack_ref") or payload.get("pack_id") or "unknown-pack"),
        pack_id=str(payload.get("pack_id") or _plain_pack_id(payload.get("pack_ref") or "unknown-pack")),
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        derivative_plan_ref=str(payload.get("derivative_plan_ref")) if payload.get("derivative_plan_ref") is not None else None,
        derivative_change_id=str(payload.get("derivative_change_id")) if payload.get("derivative_change_id") is not None else None,
        source_improvement_id=str(payload.get("source_improvement_id")) if payload.get("source_improvement_id") is not None else None,
        kind=str(payload.get("kind") or "metadata_update"),
        status=str(payload.get("status") or "open"),
        required=bool(payload.get("required")),
        priority=str(payload.get("priority") or "medium"),
        title=str(payload.get("title") or payload.get("kind") or "work order"),
        summary=str(payload.get("summary") or ""),
        reason=str(payload.get("reason") or ""),
        suggested_commands=_as_list(payload.get("suggested_commands")),
        affected_metrics=_as_list(payload.get("affected_metrics")),
        evidence_refs=_as_list(payload.get("evidence_refs")),
        completion_note=str(payload.get("completion_note")) if payload.get("completion_note") is not None else None,
        completed_evidence_refs=_as_list(payload.get("completed_evidence_refs")),
        completed_at=str(payload.get("completed_at")) if payload.get("completed_at") is not None else None,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _dedupe_orders(orders: list[PackWorkOrder]) -> list[PackWorkOrder]:
    seen: set[tuple[str, str | None]] = set()
    result: list[PackWorkOrder] = []
    for order in orders:
        key = (order.kind, order.derivative_change_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(order)
    return result


def _pack_matches(value: str | None, pack_ref: str | None) -> bool:
    if not pack_ref:
        return True
    raw_plain = _plain_pack_id(value)
    ref_plain = _plain_pack_id(pack_ref)
    return raw_plain == ref_plain or _local_pack_base(raw_plain) == _local_pack_base(ref_plain) or str(value or "") == str(pack_ref or "")


def _plain_pack_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown-pack"
    return raw.split("@", 1)[0].split("/", 1)[-1]


def _local_pack_base(value: str) -> str:
    raw = str(value or "").strip()
    for suffix in ("-local", "_local"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)]
    return raw


def _priority_rank(priority: str | None) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(priority or ""), 0)


def _slug(value: Any, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _stamp() -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", _now()).strip("_")[:15]


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


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
