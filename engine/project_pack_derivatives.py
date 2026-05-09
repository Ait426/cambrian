"""pack improvement를 다음 pack draft 계획으로 묶는 derivative workspace."""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.project_pack_authoring import PackDraftBuilder, save_pack_draft
from engine.project_pack_catalog import PackCatalogResolver, load_default_catalog
from engine.project_pack_improvements import (
    PackImprovementQueue,
    PackImprovementQueueItem,
    PackImprovementStore,
    default_pack_improvement_decisions_path,
    default_pack_improvement_items_dir,
    default_pack_improvement_queue_path,
    default_pack_improvement_queues_dir,
    latest_pack_improvement_queue,
)
from engine.project_pack_install import (
    SCHEMA_VERSION,
    InstalledPackStore,
    PackManifest,
    PackManifestLoader,
    default_installed_packs_path,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
)

logger = logging.getLogger(__name__)


DERIVATIVE_CHANGE_KINDS = {
    "metadata_only",
    "known_limits_update",
    "first_job_guide_update",
    "template_evolution_required",
    "team_review_required",
    "benchmark_case_required",
    "response_contract_required",
    "pack_derivative_required",
}


@dataclass
class PackDerivativeChange:
    """accepted improvement에서 파생된 vNext 변경 후보."""

    change_id: str
    source_improvement_id: str | None
    kind: str
    status: str
    title: str
    summary: str
    reason: str
    affected_metrics: list[str] = field(default_factory=list)
    required_commands: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackDerivativePlan:
    """accepted improvements를 다음 pack version 설계도로 묶은 계획."""

    schema_version: str
    plan_id: str
    generated_at: str
    source_pack_ref: str
    source_pack_id: str
    source_pack_name: str | None
    source_version: str | None
    namespace: str | None
    suggested_target_pack_id: str
    suggested_version: str | None
    suggested_version_bump: str
    accepted_improvement_refs: list[str] = field(default_factory=list)
    changes: list[PackDerivativeChange] = field(default_factory=list)
    ready_change_count: int = 0
    unresolved_change_count: int = 0
    blocked_change_count: int = 0
    safe_to_create_draft: bool = False
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["changes"] = [change.to_dict() for change in self.changes]
        return payload


@dataclass
class PackDerivativeWorkspace:
    """derivative-create 결과로 생긴 draft workspace 기록."""

    schema_version: str
    workspace_id: str
    created_at: str
    source_plan_ref: str
    source_pack_ref: str
    target_pack_id: str
    target_version: str | None
    draft_ref: str | None
    included_changes: list[str] = field(default_factory=list)
    unresolved_changes: list[str] = field(default_factory=list)
    status: str = "created"
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


class PackDerivativePlanner:
    """accepted improvement decisions에서 derivative plan을 만든다."""

    def build(self, project_root: Path, pack_ref: str | None = None) -> PackDerivativePlan:
        """pack 단위 accepted improvements를 vNext 변경 계획으로 변환한다."""
        root = Path(project_root).resolve()
        target_pack = _target_pack_ref(root, pack_ref)
        queue, queue_ref = _latest_queue_with_ref(root, target_pack)
        items = _accepted_items(root, target_pack, queue)
        source_pack_id = _source_pack_id(target_pack, queue, items)
        source_pack_ref = target_pack or source_pack_id
        manifest_ref, manifest = _source_manifest(root, source_pack_id, source_pack_ref)
        source_name = _source_pack_name(queue, items, manifest)
        source_version = _source_version(queue, items, manifest)
        namespace = _source_namespace(queue, items, manifest)
        changes = _changes_from_items(items)
        ready = len([change for change in changes if change.status == "ready"])
        unresolved = len([change for change in changes if change.status == "unresolved"])
        blocked = len([change for change in changes if change.status == "blocked"])
        bump = _suggest_version_bump(changes)
        suggested_version = _suggest_version(source_version, bump)
        target_pack_id = _suggest_target_pack_id(source_pack_id)
        warnings: list[str] = []
        errors: list[str] = []
        if not items:
            warnings.append("accepted improvement가 없어 derivative plan evidence가 부족합니다.")
        if manifest is None:
            warnings.append("source pack manifest를 찾지 못해 draft-create 시 refs가 제한될 수 있습니다.")
        source_refs = {
            "improvement_queue_ref": queue_ref,
            "improvement_decisions_ref": _relative(default_pack_improvement_decisions_path(root), root),
            "source_manifest_ref": manifest_ref,
            "proof_ref": _latest_proof_ref(root, source_pack_id),
            "retro_summary_ref": _latest_retro_summary_ref(root, source_pack_id),
        }
        plan = PackDerivativePlan(
            schema_version=SCHEMA_VERSION,
            plan_id=f"derivative-plan-{_slug(source_pack_id)}-{_stamp()}",
            generated_at=_now(),
            source_pack_ref=source_pack_ref or source_pack_id,
            source_pack_id=source_pack_id,
            source_pack_name=source_name,
            source_version=source_version,
            namespace=namespace,
            suggested_target_pack_id=target_pack_id,
            suggested_version=suggested_version,
            suggested_version_bump=bump,
            accepted_improvement_refs=_item_refs(root, items),
            changes=changes,
            ready_change_count=ready,
            unresolved_change_count=unresolved,
            blocked_change_count=blocked,
            safe_to_create_draft=bool(items) and blocked == 0,
            summary=_plan_summary(source_pack_id, target_pack_id, changes, bump),
            next_actions=_plan_next_actions(target_pack_id),
            source_refs={key: value for key, value in source_refs.items() if value},
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )
        return plan


class PackDerivativeCreator:
    """derivative plan에서 안전한 pack draft만 생성한다."""

    def create(
        self,
        project_root: Path,
        plan_path: Path,
        target_pack_id: str,
        version: str | None = None,
    ) -> PackDerivativeWorkspace:
        """template/team/benchmark를 바꾸지 않고 derivative draft를 만든다."""
        root = Path(project_root).resolve()
        plan_ref = resolve_pack_derivative_plan_path(root, str(plan_path))
        plan = PackDerivativeStore().load_plan(plan_ref)
        target = str(target_pack_id or "").strip()
        if not target:
            raise ValueError("target pack id is required")
        if not plan.safe_to_create_draft:
            workspace = PackDerivativeWorkspace(
                schema_version=SCHEMA_VERSION,
                workspace_id=f"derivative-workspace-{_slug(target)}-{_stamp()}",
                created_at=_now(),
                source_plan_ref=_relative(plan_ref, root),
                source_pack_ref=plan.source_pack_ref,
                target_pack_id=target,
                target_version=version,
                draft_ref=None,
                included_changes=[],
                unresolved_changes=[change.title for change in plan.changes if change.status == "unresolved"],
                status="blocked",
                next_actions=[f"cambrian pack derivative-show {plan.plan_id}"],
                warnings=list(plan.warnings),
                errors=["derivative plan is not safe to create as a draft"],
            )
            return workspace
        manifest_ref, manifest = _source_manifest(root, plan.source_pack_id, plan.source_pack_ref)
        refs = _refs_from_manifest(manifest)
        warnings = _draft_warnings(plan)
        errors: list[str] = []
        if not refs or not any(refs.values()):
            errors.append("source pack refs를 찾지 못해 derivative draft를 만들 수 없습니다.")
        derivative_meta = _draft_derivative_metadata(plan, _relative(plan_ref, root))
        draft = PackDraftBuilder().create(
            root,
            target,
            manifest.pack_kind if manifest else "lane",
            refs,
            pack_name=_target_pack_name(target),
            version=version or plan.suggested_version,
            description=_target_description(plan),
            tags=_target_tags(manifest),
            maturity="draft",
        )
        draft.derivative = derivative_meta
        draft.warnings = _dedupe([*draft.warnings, *warnings])
        draft.errors = _dedupe([*draft.errors, *errors])
        draft_ref = save_pack_draft(root, draft) if not errors else None
        workspace = PackDerivativeWorkspace(
            schema_version=SCHEMA_VERSION,
            workspace_id=f"derivative-workspace-{_slug(target)}-{_stamp()}",
            created_at=_now(),
            source_plan_ref=_relative(plan_ref, root),
            source_pack_ref=plan.source_pack_ref,
            target_pack_id=target,
            target_version=version or plan.suggested_version,
            draft_ref=draft_ref,
            included_changes=[change.change_id for change in plan.changes],
            unresolved_changes=[change.title for change in plan.changes if change.status == "unresolved"],
            status="created" if draft_ref and not errors else "failed",
            next_actions=_workspace_next_actions(draft_ref),
            warnings=_dedupe([*plan.warnings, *warnings]),
            errors=_dedupe(errors),
        )
        return workspace


class PackDerivativeStore:
    """derivative plan/workspace 파일 저장소."""

    def save_plan(self, plan: PackDerivativePlan, path: Path) -> Path:
        """plan을 YAML로 저장한다."""
        target = _save_yaml(Path(path).resolve(), plan.to_dict())
        latest = default_pack_derivative_latest_plan_path(_project_root_from_derivative_path(target))
        try:
            _save_yaml(latest, plan.to_dict())
        except Exception as exc:  # noqa: BLE001
            logger.warning("latest derivative plan save failed: %s", exc)
        return target

    def load_plan(self, path: Path) -> PackDerivativePlan:
        """저장된 derivative plan을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack derivative plan not found: {path}")
        return _plan_from_dict(payload)

    def save_workspace(self, workspace: PackDerivativeWorkspace, path: Path) -> Path:
        """workspace record를 YAML로 저장한다."""
        return _save_yaml(Path(path).resolve(), workspace.to_dict())

    def load_workspace(self, path: Path) -> PackDerivativeWorkspace:
        """저장된 workspace record를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"pack derivative workspace not found: {path}")
        return _workspace_from_dict(payload)


def default_pack_derivatives_root(project_root: Path) -> Path:
    """derivative artifact root를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "derivatives"


def default_pack_derivative_plans_dir(project_root: Path) -> Path:
    """derivative plan 저장 디렉터리를 반환한다."""
    return default_pack_derivatives_root(project_root) / "plans"


def default_pack_derivative_workspaces_dir(project_root: Path) -> Path:
    """derivative workspace 저장 디렉터리를 반환한다."""
    return default_pack_derivatives_root(project_root) / "workspaces"


def default_pack_derivative_latest_plan_path(project_root: Path) -> Path:
    """latest derivative plan pointer 경로를 반환한다."""
    return default_pack_derivatives_root(project_root) / "latest.yaml"


def default_pack_derivative_plan_path(project_root: Path, plan: PackDerivativePlan) -> Path:
    """plan 기본 저장 경로를 반환한다."""
    return default_pack_derivative_plans_dir(project_root) / f"plan_{_slug(plan.source_pack_id)}_{_stamp()}.yaml"


def default_pack_derivative_workspace_path(project_root: Path, workspace: PackDerivativeWorkspace) -> Path:
    """workspace 기본 저장 경로를 반환한다."""
    return default_pack_derivative_workspaces_dir(project_root) / f"workspace_{_slug(workspace.target_pack_id)}_{_stamp()}.yaml"


def save_pack_derivative_plan(project_root: Path, plan: PackDerivativePlan) -> str:
    """derivative plan을 기본 위치에 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = PackDerivativeStore().save_plan(plan, default_pack_derivative_plan_path(root, plan))
    return _relative(path, root)


def save_pack_derivative_workspace(project_root: Path, workspace: PackDerivativeWorkspace) -> str:
    """derivative workspace를 기본 위치에 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = PackDerivativeStore().save_workspace(workspace, default_pack_derivative_workspace_path(root, workspace))
    return _relative(path, root)


def latest_pack_derivative_plan(project_root: Path, pack_ref: str | None = None) -> PackDerivativePlan | None:
    """pack에 대응하는 최신 derivative plan을 찾는다."""
    root = Path(project_root).resolve()
    store = PackDerivativeStore()
    candidates: list[Path] = []
    plans_dir = default_pack_derivative_plans_dir(root)
    if plans_dir.exists():
        candidates.extend(sorted(plans_dir.glob("plan_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
    latest = default_pack_derivative_latest_plan_path(root)
    if latest.exists():
        candidates.append(latest)
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            plan = store.load_plan(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("derivative plan load skipped: %s", exc)
            continue
        if pack_ref is None or _pack_matches(plan.source_pack_id, pack_ref) or _pack_matches(plan.source_pack_ref, pack_ref):
            return plan
    return None


def resolve_pack_derivative_plan_path(project_root: Path, plan_ref: str) -> Path:
    """plan id/path/latest를 실제 plan path로 해석한다."""
    root = Path(project_root).resolve()
    raw_ref = str(plan_ref or "").strip()
    if not raw_ref:
        raise FileNotFoundError("pack derivative plan ref is required")
    if raw_ref == "latest":
        latest = default_pack_derivative_latest_plan_path(root)
        if latest.exists():
            return latest.resolve()
    raw = Path(raw_ref)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.extend(
            [
                root / raw,
                default_pack_derivative_plans_dir(root) / raw,
                default_pack_derivative_plans_dir(root) / f"{raw}.yaml",
                default_pack_derivative_plans_dir(root) / f"{_slug(raw_ref)}.yaml",
            ]
        )
        if raw_ref.startswith("derivative-plan-"):
            candidates.extend(default_pack_derivative_plans_dir(root).glob(f"*{_slug(raw_ref)}*.yaml"))
    for path in candidates:
        if path.exists():
            return path.resolve()
    plans_dir = default_pack_derivative_plans_dir(root)
    if plans_dir.exists():
        for path in sorted(plans_dir.glob("plan_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                payload = _load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("derivative plan resolve skipped: %s", exc)
                continue
            if str(payload.get("plan_id") or "") == raw_ref:
                return path.resolve()
    raise FileNotFoundError(f"pack derivative plan not found: {plan_ref}")


def render_pack_derivative_plan(plan: PackDerivativePlan) -> str:
    """derivative plan을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Derivative Plan",
        "==================================================",
        "",
        "Source:",
        f"  {plan.source_pack_ref}",
        "",
        "Suggested target:",
        f"  {plan.suggested_target_pack_id}",
        "",
        "Version bump:",
        f"  {plan.suggested_version_bump}",
        "",
        "Accepted improvements:",
    ]
    lines.extend([f"  - {item}" for item in plan.accepted_improvement_refs] or ["  none"])
    lines.extend(["", "Changes:"])
    lines.extend([f"  - {change.kind}: {change.status}" for change in plan.changes] or ["  none"])
    unresolved = [change for change in plan.changes if change.status == "unresolved"]
    if unresolved:
        lines.extend(["", "Unresolved:"])
        for change in unresolved:
            lines.append(f"  - {change.title}")
            for command in change.required_commands[:2]:
                lines.append(f"    {command}")
    if plan.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in plan.next_actions])
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in plan.warnings])
    if plan.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in plan.errors])
    return "\n".join(lines)


def render_pack_derivative_workspace(workspace: PackDerivativeWorkspace) -> str:
    """derivative-create 결과를 렌더링한다."""
    title = "Pack derivative draft created." if workspace.status == "created" else "Pack derivative draft blocked."
    lines = [
        title,
        "",
        "Target:",
        f"  {workspace.target_pack_id}",
        "",
        "Draft:",
        f"  {workspace.draft_ref or 'none'}",
    ]
    if workspace.unresolved_changes:
        lines.extend(["", "Unresolved changes:"])
        lines.extend([f"  - {item}" for item in workspace.unresolved_changes])
    if workspace.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in workspace.next_actions])
    if workspace.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in workspace.warnings])
    if workspace.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in workspace.errors])
    return "\n".join(lines)


def render_pack_derivative_compact(plan: PackDerivativePlan | None) -> str:
    """pack show/proof에 붙일 compact derivative summary를 만든다."""
    if plan is None:
        return ""
    return "\n".join(
        [
            "Derivative plan:",
            f"  target: {plan.suggested_target_pack_id}",
            f"  changes: {len(plan.changes)}",
            f"  unresolved: {plan.unresolved_change_count}",
        ]
    )


def render_status_pack_derivative(plan: PackDerivativePlan | None, accepted_count: int = 0) -> str:
    """status에 표시할 derivative 상태 요약을 만든다."""
    if plan is not None:
        return "\n".join(
            [
                "Pack derivative:",
                f"  {plan.suggested_target_pack_id} proposed",
                f"  next: cambrian pack derivative-show {plan.plan_id}",
            ]
        )
    if accepted_count > 0:
        return "\n".join(
            [
                "Pack derivative:",
                "  accepted improvements ready for vNext planning",
                "  next: cambrian pack derivative-plan",
            ]
        )
    return ""


def accepted_improvement_count(project_root: Path, pack_ref: str | None = None) -> int:
    """pack에 대해 accepted improvement 수를 반환한다."""
    root = Path(project_root).resolve()
    target = _target_pack_ref(root, pack_ref)
    queue, _ = _latest_queue_with_ref(root, target)
    return len(_accepted_items(root, target, queue))


def _changes_from_items(items: list[PackImprovementQueueItem]) -> list[PackDerivativeChange]:
    changes: list[PackDerivativeChange] = []
    for item in items:
        for kind in _change_kinds_for_improvement(item.kind):
            status = _change_status(kind)
            change = PackDerivativeChange(
                change_id=f"change_{_slug(item.item_id)}_{_slug(kind)}",
                source_improvement_id=item.item_id,
                kind=kind,
                status=status,
                title=_change_title(kind, item),
                summary=_change_summary(kind, item),
                reason=item.reason,
                affected_metrics=list(item.affected_metrics),
                required_commands=_required_commands(kind, item),
                evidence_refs=list(item.evidence_refs),
                warnings=[] if status != "unresolved" else ["required action is not implemented by derivative-create"],
                errors=[],
            )
            changes.append(change)
    return sorted(_dedupe_changes(changes), key=lambda item: (_status_rank(item.status), item.kind, item.change_id))


def _change_kinds_for_improvement(kind: str) -> list[str]:
    mapping = {
        "strengthen_context_hints": ["template_evolution_required"],
        "improve_response_contract": ["response_contract_required"],
        "improve_validation_support": ["template_evolution_required", "benchmark_case_required"],
        "update_known_limits": ["known_limits_update"],
        "add_benchmark_case": ["benchmark_case_required"],
        "review_team_fit": ["team_review_required"],
        "review_template_fit": ["template_evolution_required"],
        "create_pack_derivative": ["pack_derivative_required"],
        "update_pack_docs": ["metadata_only"],
        "improve_first_job_guide": ["first_job_guide_update"],
    }
    return mapping.get(kind, ["metadata_only"])


def _change_status(kind: str) -> str:
    if kind in {"metadata_only", "known_limits_update", "first_job_guide_update", "pack_derivative_required"}:
        return "ready"
    return "unresolved"


def _required_commands(kind: str, item: PackImprovementQueueItem) -> list[str]:
    if kind == "template_evolution_required":
        return ["cambrian template evolve <template>"]
    if kind == "team_review_required":
        return ["cambrian team recommend", f"cambrian pack draft {item.pack_id}-v2"]
    if kind == "benchmark_case_required":
        return ["cambrian benchmark case-add ..."]
    if kind == "response_contract_required":
        return ["review bridge response contract manually"]
    if kind == "pack_derivative_required":
        return [f"cambrian pack derivative-create <plan> --as {item.pack_id}-v2"]
    if kind == "known_limits_update":
        return [f"cambrian pack proof {item.pack_id}"]
    if kind == "first_job_guide_update":
        return [f"cambrian pack setup {item.pack_id}", f"cambrian pack next {item.pack_id}"]
    return list(item.next_commands[:2])


def _accepted_items(
    root: Path,
    pack_ref: str | None,
    queue: PackImprovementQueue | None,
) -> list[PackImprovementQueueItem]:
    store = PackImprovementStore()
    items = store.list_items(default_pack_improvement_items_dir(root), pack_id=pack_ref)
    if queue is not None:
        by_id = {item.item_id: item for item in items}
        for item in queue.items:
            if pack_ref and not _pack_matches(item.pack_id, pack_ref):
                continue
            by_id.setdefault(item.item_id, item)
        items = list(by_id.values())
    decisions = _latest_decisions(root)
    accepted: list[PackImprovementQueueItem] = []
    for item in items:
        status = decisions.get(item.item_id, item.status)
        if status == "accepted":
            item.status = "accepted"
            accepted.append(item)
    return sorted(accepted, key=lambda item: (-_priority_rank(item.priority), -float(item.confidence or 0.0), item.kind))


def _latest_decisions(root: Path) -> dict[str, str]:
    try:
        from engine.project_pack_improvements import PackImprovementDecisionStore

        return PackImprovementDecisionStore().latest_status_by_item(default_pack_improvement_decisions_path(root))
    except Exception as exc:  # noqa: BLE001
        logger.warning("pack improvement decisions lookup failed: %s", exc)
        return {}


def _latest_queue_with_ref(root: Path, pack_ref: str | None) -> tuple[PackImprovementQueue | None, str | None]:
    queue = latest_pack_improvement_queue(root, pack_ref)
    if queue is None:
        return None, None
    candidates = []
    if pack_ref:
        candidates.append(default_pack_improvement_queues_dir(root) / f"queue_{_slug(pack_ref)}.yaml")
    candidates.append(default_pack_improvement_queue_path(root))
    for path in candidates:
        if path.exists():
            try:
                payload = _load_yaml(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("improvement queue ref lookup skipped: %s", exc)
                continue
            if str(payload.get("queue_id") or "") == queue.queue_id:
                return queue, _relative(path, root)
    return queue, queue.queue_id


def _target_pack_ref(root: Path, pack_ref: str | None) -> str | None:
    if pack_ref:
        return str(pack_ref)
    try:
        from engine.project_pack_activation import current_active_pack

        active = current_active_pack(root)
        if active is not None:
            return active.pack_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("active pack lookup for derivative plan failed: %s", exc)
    queue = latest_pack_improvement_queue(root)
    if queue is not None:
        return queue.pack_id or queue.pack_ref
    return None


def _source_pack_id(
    pack_ref: str | None,
    queue: PackImprovementQueue | None,
    items: list[PackImprovementQueueItem],
) -> str:
    if queue is not None and queue.pack_id:
        return _plain_pack_id(queue.pack_id)
    if items:
        return _plain_pack_id(items[0].pack_id)
    return _plain_pack_id(pack_ref or "unknown-pack")


def _source_pack_name(
    queue: PackImprovementQueue | None,
    items: list[PackImprovementQueueItem],
    manifest: PackManifest | None,
) -> str | None:
    if queue is not None and queue.pack_name:
        return queue.pack_name
    if items and items[0].pack_name:
        return items[0].pack_name
    return manifest.pack_name if manifest is not None else None


def _source_version(
    queue: PackImprovementQueue | None,
    items: list[PackImprovementQueueItem],
    manifest: PackManifest | None,
) -> str | None:
    if queue is not None and queue.version:
        return queue.version
    if items and items[0].version:
        return items[0].version
    return manifest.version if manifest is not None else None


def _source_namespace(
    queue: PackImprovementQueue | None,
    items: list[PackImprovementQueueItem],
    manifest: PackManifest | None,
) -> str | None:
    if queue is not None and queue.namespace:
        return queue.namespace
    if items and items[0].namespace:
        return items[0].namespace
    return manifest.namespace if manifest is not None else None


def _source_manifest(root: Path, source_pack_id: str, source_pack_ref: str | None) -> tuple[str | None, PackManifest | None]:
    for path in _source_manifest_candidates(root, source_pack_id, source_pack_ref):
        if not path or not path.exists():
            continue
        try:
            return _relative(path, root), PackManifestLoader().load(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("source pack manifest skipped: %s (%s)", path, exc)
    return None, None


def _source_manifest_candidates(root: Path, source_pack_id: str, source_pack_ref: str | None) -> list[Path]:
    candidates: list[Path] = []
    raw = Path(str(source_pack_ref or ""))
    if raw.exists():
        candidates.append(raw.resolve())
    try:
        index = InstalledPackStore().load(default_installed_packs_path(root))
        for lookup in _dedupe([source_pack_ref, source_pack_id]):
            try:
                record = InstalledPackStore().find(index, str(lookup))
            except Exception as exc:  # noqa: BLE001
                logger.debug("installed pack lookup skipped for derivative source %s: %s", lookup, exc)
                continue
            for ref in [record.latest_manifest_ref, record.manifest_ref, *record.manifest_history]:
                if ref:
                    candidates.append((root / ref).resolve())
    except Exception as exc:  # noqa: BLE001
        logger.debug("installed source manifest lookup skipped: %s", exc)
    try:
        catalog = load_default_catalog(root)
        entry = PackCatalogResolver().find_entry(catalog, source_pack_ref or source_pack_id)
        candidates.append(PackCatalogResolver().resolve_manifest_path(root, entry))
    except Exception as exc:  # noqa: BLE001
        logger.debug("catalog source manifest lookup skipped: %s", exc)
    slug = _slug(source_pack_id)
    candidates.extend(
        [
            root / "packs" / f"{slug}.cambrian-pack.yaml",
            root / "packs" / "generated" / f"{slug}.cambrian-pack.yaml",
        ]
    )
    return _dedupe_paths(candidates)


def _refs_from_manifest(manifest: PackManifest | None) -> dict[str, list[str] | str | None]:
    if manifest is None:
        return {"workers": [], "teams": [], "templates": [], "benchmarks": [], "lane": None}
    return {
        "workers": _dedupe([str(item.get("agent_id") or item.get("id") or item.get("name") or "") for item in manifest.workers]),
        "teams": _dedupe([str(item.get("name") or item.get("team_id") or "") for item in manifest.teams]),
        "templates": _dedupe([str(item.get("name") or item.get("template_id") or "") for item in manifest.templates]),
        "benchmarks": _dedupe([str(item.get("name") or item.get("workset_id") or "") for item in manifest.benchmarks]),
        "lane": (manifest.lane or {}).get("lane_id") if manifest.lane else None,
    }


def _draft_derivative_metadata(plan: PackDerivativePlan, plan_ref: str) -> dict[str, Any]:
    return {
        "source_pack_ref": plan.source_pack_ref,
        "source_plan_ref": plan_ref,
        "accepted_improvements": list(plan.accepted_improvement_refs),
        "changes": [
            {
                "kind": change.kind,
                "status": change.status,
                "source_improvement_id": change.source_improvement_id,
                "required_commands": list(change.required_commands),
                "evidence_refs": list(change.evidence_refs),
            }
            for change in plan.changes
        ],
        "unresolved_changes": [change.title for change in plan.changes if change.status == "unresolved"],
    }


def _draft_warnings(plan: PackDerivativePlan) -> list[str]:
    warnings: list[str] = []
    unresolved = [change.title for change in plan.changes if change.status == "unresolved"]
    if unresolved:
        warnings.append("Derivative draft has unresolved required changes; do not claim these improvements are implemented.")
        warnings.extend([f"Derivative unresolved change: {item}" for item in unresolved])
    return _dedupe(warnings)


def _target_description(plan: PackDerivativePlan) -> str:
    return (
        f"Derivative draft of {plan.source_pack_id}. "
        "Accepted improvements are recorded as plan metadata; unresolved changes still require explicit commands."
    )


def _target_tags(manifest: PackManifest | None) -> list[str]:
    tags: list[str] = ["derivative", "vnext"]
    if manifest is not None:
        compat = manifest.compatibility or {}
        tags.extend(_as_list(compat.get("tags")))
    return _dedupe(tags)


def _target_pack_name(target_pack_id: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", target_pack_id) if part) or target_pack_id


def _workspace_next_actions(draft_ref: str | None) -> list[str]:
    if not draft_ref:
        return []
    return [
        f"cambrian pack validate {draft_ref}",
        f"cambrian pack build {draft_ref}",
    ]


def _plan_next_actions(target_pack_id: str) -> list[str]:
    return [
        f"cambrian pack derivative-create latest --as {target_pack_id}",
    ]


def _plan_summary(source_pack_id: str, target_pack_id: str, changes: list[PackDerivativeChange], bump: str) -> list[str]:
    return [
        f"source={source_pack_id}",
        f"target={target_pack_id}",
        f"changes={len(changes)}",
        f"version_bump={bump}",
    ]


def _suggest_target_pack_id(source_pack_id: str) -> str:
    if source_pack_id.endswith("-v2") or source_pack_id.endswith("-vnext"):
        return f"{source_pack_id}-next"
    return f"{source_pack_id}-v2"


def _suggest_version_bump(changes: list[PackDerivativeChange]) -> str:
    if not changes:
        return "unknown"
    kinds = {change.kind for change in changes}
    if kinds <= {"metadata_only", "known_limits_update", "first_job_guide_update"}:
        return "patch"
    if "pack_derivative_required" in kinds and len(kinds) == 1:
        return "minor"
    if {"template_evolution_required", "team_review_required", "benchmark_case_required", "response_contract_required"} & kinds:
        return "minor"
    return "unknown"


def _suggest_version(version: str | None, bump: str) -> str | None:
    if not version:
        return None
    parts = str(version).split(".")
    if len(parts) < 3 or not all(part.isdigit() for part in parts[:3]):
        return None
    major, minor, patch = [int(part) for part in parts[:3]]
    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor += 1
        patch = 0
    elif bump == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        return None
    return f"{major}.{minor}.{patch}"


def _item_refs(root: Path, items: list[PackImprovementQueueItem]) -> list[str]:
    refs: list[str] = []
    items_dir = default_pack_improvement_items_dir(root)
    for item in items:
        found = None
        if items_dir.exists():
            for path in items_dir.glob("item_*.yaml"):
                try:
                    payload = _load_yaml(path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("improvement item ref lookup skipped: %s", exc)
                    continue
                if str(payload.get("item_id") or "") == item.item_id:
                    found = _relative(path, root)
                    break
        refs.append(found or item.item_id)
    return _dedupe(refs)


def _latest_proof_ref(root: Path, pack_id: str) -> str | None:
    try:
        from engine.project_pack_proof import latest_pack_proof_card

        card = latest_pack_proof_card(root, pack_id)
        if card is not None:
            return f".cambrian/packs/proof/{card.proof_id}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest proof lookup for derivative plan failed: %s", exc)
    return None


def _latest_retro_summary_ref(root: Path, pack_id: str) -> str | None:
    try:
        from engine.project_pack_retrospective import latest_pack_retro_summary

        summary = latest_pack_retro_summary(root, pack_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("latest retro summary lookup for derivative plan failed: %s", exc)
        summary = None
    if summary is None:
        return None
    summaries_dir = root / ".cambrian" / "packs" / "retrospectives" / "summaries"
    for path in sorted(summaries_dir.glob("summary_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = _load_yaml(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("retro summary ref lookup skipped: %s", exc)
            continue
        if str(payload.get("summary_id") or "") == summary.summary_id:
            return _relative(path, root)
    return summary.summary_id


def _plan_from_dict(payload: dict[str, Any]) -> PackDerivativePlan:
    changes = [_change_from_dict(item) for item in payload.get("changes", []) if isinstance(item, dict)]
    return PackDerivativePlan(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        plan_id=str(payload.get("plan_id") or f"derivative-plan-{_stamp()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        source_pack_ref=str(payload.get("source_pack_ref") or payload.get("source_pack_id") or "unknown-pack"),
        source_pack_id=str(payload.get("source_pack_id") or _plain_pack_id(payload.get("source_pack_ref") or "unknown-pack")),
        source_pack_name=str(payload.get("source_pack_name")) if payload.get("source_pack_name") is not None else None,
        source_version=str(payload.get("source_version")) if payload.get("source_version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        suggested_target_pack_id=str(payload.get("suggested_target_pack_id") or "unknown-pack-v2"),
        suggested_version=str(payload.get("suggested_version")) if payload.get("suggested_version") is not None else None,
        suggested_version_bump=str(payload.get("suggested_version_bump") or "unknown"),
        accepted_improvement_refs=_as_list(payload.get("accepted_improvement_refs")),
        changes=changes,
        ready_change_count=int(payload.get("ready_change_count") or len([item for item in changes if item.status == "ready"])),
        unresolved_change_count=int(payload.get("unresolved_change_count") or len([item for item in changes if item.status == "unresolved"])),
        blocked_change_count=int(payload.get("blocked_change_count") or len([item for item in changes if item.status == "blocked"])),
        safe_to_create_draft=bool(payload.get("safe_to_create_draft")),
        summary=_as_list(payload.get("summary")),
        next_actions=_as_list(payload.get("next_actions")),
        source_refs=payload.get("source_refs") if isinstance(payload.get("source_refs"), dict) else {},
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _change_from_dict(payload: dict[str, Any]) -> PackDerivativeChange:
    return PackDerivativeChange(
        change_id=str(payload.get("change_id") or f"change-{_stamp()}"),
        source_improvement_id=str(payload.get("source_improvement_id")) if payload.get("source_improvement_id") is not None else None,
        kind=str(payload.get("kind") or "metadata_only"),
        status=str(payload.get("status") or "proposed"),
        title=str(payload.get("title") or payload.get("kind") or "change"),
        summary=str(payload.get("summary") or ""),
        reason=str(payload.get("reason") or ""),
        affected_metrics=_as_list(payload.get("affected_metrics")),
        required_commands=_as_list(payload.get("required_commands")),
        evidence_refs=_as_list(payload.get("evidence_refs")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _workspace_from_dict(payload: dict[str, Any]) -> PackDerivativeWorkspace:
    return PackDerivativeWorkspace(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        workspace_id=str(payload.get("workspace_id") or f"derivative-workspace-{_stamp()}"),
        created_at=str(payload.get("created_at") or _now()),
        source_plan_ref=str(payload.get("source_plan_ref") or ""),
        source_pack_ref=str(payload.get("source_pack_ref") or ""),
        target_pack_id=str(payload.get("target_pack_id") or ""),
        target_version=str(payload.get("target_version")) if payload.get("target_version") is not None else None,
        draft_ref=str(payload.get("draft_ref")) if payload.get("draft_ref") is not None else None,
        included_changes=_as_list(payload.get("included_changes")),
        unresolved_changes=_as_list(payload.get("unresolved_changes")),
        status=str(payload.get("status") or "created"),
        next_actions=_as_list(payload.get("next_actions")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _change_title(kind: str, item: PackImprovementQueueItem) -> str:
    label = kind.replace("_", " ")
    return f"{label} from {item.kind}"


def _change_summary(kind: str, item: PackImprovementQueueItem) -> str:
    return f"{item.kind} accepted improvement를 {kind} derivative change로 추적합니다."


def _dedupe_changes(changes: list[PackDerivativeChange]) -> list[PackDerivativeChange]:
    seen: set[tuple[str, str | None]] = set()
    result: list[PackDerivativeChange] = []
    for change in changes:
        key = (change.kind, change.source_improvement_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(change)
    return result


def _project_root_from_derivative_path(path: Path) -> Path:
    resolved = Path(path).resolve()
    parts = list(resolved.parts)
    if ".cambrian" in parts:
        return Path(*parts[: parts.index(".cambrian")])
    return resolved.parent


def _plain_pack_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown-pack"
    return raw.split("@", 1)[0].split("/", 1)[-1]


def _pack_matches(value: str | None, pack_ref: str | None) -> bool:
    if not pack_ref:
        return True
    return _plain_pack_id(value) == _plain_pack_id(pack_ref) or str(value or "") == str(pack_ref or "")


def _slug(value: Any, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _stamp() -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", _now()).strip("_")[:15]


def _priority_rank(priority: str | None) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(priority or ""), 0)


def _status_rank(status: str | None) -> int:
    return {"blocked": 0, "unresolved": 1, "proposed": 2, "ready": 3}.get(str(status or ""), 4)


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
