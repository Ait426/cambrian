"""설치된 pack을 현재 작업 context로 명시 활성화하는 모듈."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_install import (
    InstalledPackRecord,
    InstalledPackStore,
    PackManifest,
    PackManifestLoader,
    default_install_dir,
    default_installed_packs_path,
    _as_list,
    _as_dict,
    _load_yaml,
    _relative,
    _save_yaml,
)
from engine.project_pack_trust import PackLockEntry, PackLockStore, default_pack_lock_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓰기 좋은 UTC 타임스탬프를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def default_active_pack_path(project_root: Path) -> Path:
    """active pack context 기본 저장 경로를 반환한다."""
    return default_install_dir(project_root) / "active_pack.yaml"


def default_next_guides_dir(project_root: Path) -> Path:
    """pack next guide 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "next_guides"


@dataclass
class ActivePackContext:
    """현재 프로젝트에서 선택된 installed pack 작업 context."""

    schema_version: str
    activated_at: str
    pack_ref: str
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    namespace: str | None
    source_kind: str | None
    source_ref: str | None
    installed_pack_ref: str | None
    lock_ref: str | None
    lane_id: str | None
    lane_label: str | None
    workers: list[str]
    teams: list[str]
    templates: list[str]
    benchmarks: list[str]
    default_team: str | None
    default_template: str | None
    default_workset: str | None
    status: str
    contract_template_kind: str | None = None
    validation_criteria: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    approval_required_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)

    def metrics_payload(self) -> dict[str, Any]:
        """do/bridge metrics_context에 남길 최소 provenance를 만든다."""
        return {
            "active_pack_id": self.pack_id,
            "active_pack_ref": self.pack_ref,
            "active_pack_namespace": self.namespace,
            "active_pack_version": self.version,
            "active_pack_lane": self.lane_id,
            "reused_context": {"pack": True},
        }


@dataclass
class PackNextAction:
    """active pack 기준 다음에 실행할 수 있는 명령."""

    title: str
    command: str
    reason: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackNextGuide:
    """active pack 기준 첫 작업 안내서."""

    schema_version: str
    generated_at: str
    pack_id: str | None
    pack_name: str | None
    active: bool
    fit_status: str | None
    recommended_request_examples: list[str]
    next_actions: list[PackNextAction]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["next_actions"] = [item.to_dict() for item in self.next_actions]
        return payload


class PackActivationStore:
    """active_pack.yaml 저장소."""

    def load(self, path: Path) -> ActivePackContext | None:
        """active pack context를 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return None
        payload = _load_yaml(target)
        if not payload:
            return None
        return _context_from_dict(payload)

    def save(self, path: Path, context: ActivePackContext) -> Path:
        """active pack context를 저장한다."""
        target = Path(path).resolve()
        _save_yaml(target, context.to_dict())
        return target

    def clear(self, path: Path) -> Path:
        """active pack context를 비활성 상태로 표시한다."""
        target = Path(path).resolve()
        existing = self.load(target)
        if existing is None:
            existing = ActivePackContext(
                schema_version=SCHEMA_VERSION,
                activated_at=_now(),
                pack_ref="",
                pack_id="",
                pack_name="",
                pack_kind="",
                version=None,
                namespace=None,
                source_kind=None,
                source_ref=None,
                installed_pack_ref=None,
                lock_ref=None,
                lane_id=None,
                lane_label=None,
                workers=[],
                teams=[],
                templates=[],
                benchmarks=[],
                default_team=None,
                default_template=None,
                default_workset=None,
                status="inactive",
            )
        existing.status = "inactive"
        existing.activated_at = _now()
        return self.save(target, existing)


class PackActivator:
    """installed pack을 active work context로 선택한다."""

    def activate(self, project_root: Path, pack_ref: str) -> ActivePackContext:
        """설치된 pack만 active context로 저장한다."""
        root = Path(project_root).resolve()
        record = _resolve_installed_record(root, pack_ref)
        context = _context_from_record(root, record)
        PackActivationStore().save(default_active_pack_path(root), context)
        return context

    def deactivate(self, project_root: Path) -> ActivePackContext:
        """active pack을 해제하되 installed pack 자체는 건드리지 않는다."""
        root = Path(project_root).resolve()
        PackActivationStore().clear(default_active_pack_path(root))
        context = PackActivationStore().load(default_active_pack_path(root))
        if context is None:
            raise ValueError("active pack context could not be cleared")
        return context


class PackNextGuideBuilder:
    """active pack 기준 다음 명령 안내를 만든다."""

    def build(self, project_root: Path, pack_ref: str | None = None) -> PackNextGuide:
        """명시 pack 또는 현재 active pack 기준 first job guide를 만든다."""
        root = Path(project_root).resolve()
        context: ActivePackContext | None = None
        if pack_ref:
            record = _resolve_installed_record(root, pack_ref)
            context = _context_from_record(root, record)
        else:
            context = PackActivationStore().load(default_active_pack_path(root))

        if context is None or context.status != "active":
            return PackNextGuide(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                pack_id=None,
                pack_name=None,
                active=False,
                fit_status=None,
                recommended_request_examples=[],
                next_actions=[
                    PackNextAction(
                        title="Activate an installed pack",
                        command="cambrian pack activate auth-bug-core",
                        reason="pack install은 작업 context 선택이 아니므로 activation이 필요합니다.",
                    )
                ],
                warnings=["active pack이 없습니다."],
            )

        examples = _request_examples(context)
        request = examples[0] if examples else "작은 버그 수정해"
        actions = [
            PackNextAction(
                title="Start a pack job",
                command=f'cambrian pack start "{request}"',
                reason="active pack context로 첫 작업 job과 AI packet을 만듭니다.",
            ),
            PackNextAction(
                title="Ingest AI reply",
                command="cambrian pack job-ingest <job-id> fixtures/ai_reply_patch_candidate.yaml",
                reason="AI 답변을 pack job에 붙여 bridge fast path로 넘깁니다.",
            ),
            PackNextAction(
                title="Validate job",
                command="cambrian pack job-validate <job-id>",
                reason="source apply 전에 validated proposal 경계까지 진행합니다.",
            ),
        ]
        if context.default_workset:
            actions.append(
                PackNextAction(
                    title="Generate local proof",
                    command=f"cambrian pack proof {context.pack_id}",
                    reason="실제 사용 후 local proof를 생성합니다.",
                )
            )
        return PackNextGuide(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            pack_id=context.pack_id,
            pack_name=context.pack_name,
            active=True,
            fit_status=_fit_status(context),
            recommended_request_examples=examples,
            next_actions=actions,
        )


def current_active_pack(project_root: Path) -> ActivePackContext | None:
    """현재 active pack context를 반환한다."""
    context = PackActivationStore().load(default_active_pack_path(project_root))
    if context is None or context.status != "active":
        return None
    return context


def save_pack_next_guide(project_root: Path, guide: PackNextGuide) -> Path:
    """next guide derived artifact를 저장한다."""
    root = Path(project_root).resolve()
    pack_id = guide.pack_id or "no-active-pack"
    path = default_next_guides_dir(root) / f"next_{pack_id}_{_stamp()}.yaml"
    _save_yaml(path, guide.to_dict())
    return path


def active_pack_bridge_context(project_root: Path) -> dict[str, Any]:
    """bridge packet에 넣을 active pack soft context를 만든다."""
    context = current_active_pack(project_root)
    if context is None:
        return {}
    return pack_context_bridge_payload(context)


def context_for_installed_pack(project_root: Path, pack_ref: str) -> ActivePackContext:
    """active 상태를 바꾸지 않고 installed pack context를 만든다."""
    record = _resolve_installed_record(project_root, pack_ref)
    return _context_from_record(project_root, record)


def pack_context_bridge_payload(context: ActivePackContext) -> dict[str, Any]:
    """bridge packet에 넣을 pack soft context payload를 만든다."""
    return {
        "pack_id": context.pack_id,
        "pack_ref": context.pack_ref,
        "pack_name": context.pack_name,
        "pack_kind": context.pack_kind,
        "namespace": context.namespace,
        "version": context.version,
        "lane_id": context.lane_id,
        "lane_label": context.lane_label,
        "workers": list(context.workers),
        "selected_agents": list(context.workers),
        "team": context.default_team,
        "template": context.default_template,
        "benchmark": context.default_workset,
        "change_policy": "proposal_only",
        "contract_template_kind": context.contract_template_kind,
        "validation_criteria": list(context.validation_criteria),
        "forbidden_actions": list(context.forbidden_actions),
        "approval_required_actions": list(context.approval_required_actions),
        "soft_context_only": True,
    }


def apply_active_pack_to_do_session(project_root: Path, session: Any) -> None:
    """do session에 active pack hint와 metrics provenance를 약하게 붙인다."""
    context = current_active_pack(project_root)
    if context is None:
        return
    active_payload = active_pack_bridge_context(project_root)
    if not isinstance(getattr(session, "summary", None), dict):
        return
    session.summary["active_pack_context"] = active_payload
    request = str(getattr(session, "user_request", "") or "")
    fit = _request_fit(context, request)
    session.summary["active_pack_fit"] = fit
    if isinstance(getattr(session, "metrics_context", None), dict):
        session.metrics_context.update(context.metrics_payload())
        try:
            from engine.project_pack_readiness import PackReadinessBuilder
            from engine.project_pack_setup import latest_pack_setup_plan

            readiness = PackReadinessBuilder().build(project_root, context.pack_id)
            session.metrics_context["active_pack_readiness"] = readiness.readiness_status
            session.metrics_context["active_pack_fit_status"] = readiness.fit_status
            setup_plan = latest_pack_setup_plan(project_root, context.pack_id)
            if setup_plan is not None:
                session.metrics_context["pack_setup_plan_ref"] = setup_plan.saved_ref
                session.metrics_context["pack_setup_status"] = setup_plan.readiness_status
        except Exception as exc:
            logger.warning("active pack readiness metrics failed: %s", exc)
    if isinstance(getattr(session, "warnings", None), list) and fit == "outside-lane":
        session.warnings.append(
            f"active pack {context.pack_id} is optimized for {context.lane_label or context.lane_id or 'its lane'}, but this request may be outside-lane."
        )


def render_pack_activated(context: ActivePackContext, guide: PackNextGuide) -> str:
    """pack activate 결과를 렌더링한다."""
    lines = [
        "Pack activated.",
        "",
        "Pack:",
        f"  {context.pack_ref}",
        "",
        "This does not apply a template or modify source code.",
        "It only selects this pack as the current work context.",
    ]
    if context.default_team or context.default_template or context.default_workset:
        lines.extend(["", "Context:"])
        if context.default_team:
            lines.append(f"  team     : {context.default_team}")
        if context.default_template:
            lines.append(f"  template : {context.default_template}")
        if context.default_workset:
            lines.append(f"  workset  : {context.default_workset}")
    if guide.next_actions:
        first = guide.next_actions[0]
        lines.extend(["", "Recommended first job:", f"  {first.command}"])
    return "\n".join(lines)


def render_active_pack(context: ActivePackContext | None, guide: PackNextGuide | None = None) -> str:
    """현재 active pack을 렌더링한다."""
    if context is None or context.status != "active":
        return "\n".join(
            [
                "Active Pack",
                "==================================================",
                "",
                "No active pack.",
                "",
                "Use:",
                "  cambrian pack activate auth-bug-core",
            ]
        )
    lines = [
        "Active Pack",
        "==================================================",
        "",
        "Pack:",
        f"  id      : {context.pack_id}",
        f"  ref     : {context.pack_ref}",
        f"  kind    : {context.pack_kind}",
        f"  version : {context.version or 'none'}",
        "",
        "Lane:",
        f"  {context.lane_label or context.lane_id or 'none'}",
        "",
        "Workers:",
    ]
    lines.extend([f"  - {item}" for item in context.workers] or ["  - none"])
    lines.extend(["", "Team:", f"  {context.default_team or ', '.join(context.teams) or 'none'}"])
    lines.extend(["", "Template:", f"  {context.default_template or ', '.join(context.templates) or 'none'}"])
    lines.extend(["", "Benchmark:", f"  {context.default_workset or ', '.join(context.benchmarks) or 'none'}"])
    if guide and guide.next_actions:
        lines.extend(["", "Next:", f"  {guide.next_actions[0].command}"])
    return "\n".join(lines)


def render_pack_next(guide: PackNextGuide) -> str:
    """pack next guide를 렌더링한다."""
    lines = [
        "Pack Next",
        "==================================================",
        "",
        "Active pack:",
        f"  {guide.pack_id or 'none'}",
    ]
    if guide.fit_status:
        lines.extend(["", "Fit:", f"  {guide.fit_status}"])
    if guide.recommended_request_examples:
        lines.extend(["", "Suggested requests:"])
        lines.extend([f"  - {item}" for item in guide.recommended_request_examples])
    if guide.next_actions:
        first = guide.next_actions[0]
        lines.extend(["", "Start a job:", f"  {first.command}"])
        remaining = guide.next_actions[1:]
        if remaining:
            lines.extend(["", "Then:"])
            lines.append("  paste the generated packet into your AI")
            for action in remaining:
                lines.append(f"  {action.command}")
    if guide.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in guide.warnings])
    if guide.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in guide.errors])
    return "\n".join(lines)


def render_pack_deactivated(context: ActivePackContext) -> str:
    """pack deactivate 결과를 렌더링한다."""
    return "\n".join(
        [
            "Pack deactivated.",
            "",
            "Installed packs were not removed.",
            "No template was applied or reverted.",
        ]
    )


def render_status_active_pack(context: ActivePackContext | None) -> str:
    """status 화면에 붙일 compact active pack 요약을 만든다."""
    if context is None:
        return ""
    request = _request_examples(context)[0] if _request_examples(context) else "작은 버그 수정해"
    return "\n".join(
        [
            "",
            "Active pack:",
            f"  {context.pack_id}",
            f'  next: cambrian pack start "{request}"',
        ]
    )


def render_active_pack_bridge_hint(context: ActivePackContext | None) -> str:
    """bridge prepare 출력에 붙일 active pack 힌트를 만든다."""
    if context is None:
        return ""
    return "\n".join(
        [
            "",
            "Active pack context:",
            f"  pack    : {context.pack_id}",
            f"  team    : {context.default_team or 'none'}",
            f"  template: {context.default_template or 'none'}",
        ]
    )


def _resolve_installed_record(project_root: Path, pack_ref: str) -> InstalledPackRecord:
    """installed_packs.yaml에서 pack ref를 해석한다."""
    index = InstalledPackStore().load(default_installed_packs_path(project_root))
    try:
        record = InstalledPackStore().find(index, pack_ref)
    except KeyError as exc:
        raise KeyError(
            f"Pack is not installed.\n\nUse:\n  cambrian install pack {pack_ref}"
        ) from exc
    if record.status == "uninstalled":
        raise KeyError(
            f"Pack is not installed.\n\nUse:\n  cambrian install pack {pack_ref}"
        )
    return record


def _context_from_record(project_root: Path, record: InstalledPackRecord) -> ActivePackContext:
    """installed pack record에서 active context를 만든다."""
    root = Path(project_root).resolve()
    artifacts = dict(record.installed_artifacts or {})
    manifest = _load_manifest_for_record(root, record)
    lock_entry = _find_lock_entry(root, record)
    lane = manifest.lane if manifest is not None and isinstance(manifest.lane, dict) else {}
    lane_id = str(lane.get("lane_id") or artifacts.get("lane") or "") or None
    lane_label = str(lane.get("label") or "") or None
    teams = _as_list(artifacts.get("teams"))
    templates = _as_list(artifacts.get("templates"))
    benchmarks = _as_list(artifacts.get("benchmarks"))
    workers = _as_list(artifacts.get("agents") or artifacts.get("workers"))
    default_team = str(lane.get("default_team") or "") or (teams[0] if teams else None)
    default_template = str(lane.get("default_template") or "") or (templates[0] if templates else None)
    default_workset = str(lane.get("default_workset") or "") or (benchmarks[0] if benchmarks else None)
    pack_ref = _pack_ref(record)
    lock_ref = None
    if lock_entry is not None:
        lock_ref = f".cambrian/install/pack_lock.yaml#{pack_ref}"
    installed_pack_ref = f".cambrian/install/installed_packs.yaml#{pack_ref}"
    warnings = list(record.warnings or [])
    if manifest is None:
        warnings.append("manifest copy를 읽지 못해 installed_artifacts 요약만 사용했습니다.")
    contract_defaults = _agent_contract_defaults(manifest, default_template)
    return ActivePackContext(
        schema_version=SCHEMA_VERSION,
        activated_at=_now(),
        pack_ref=pack_ref,
        pack_id=record.pack_id,
        pack_name=record.pack_name,
        pack_kind=record.pack_kind,
        version=record.version,
        namespace=record.namespace,
        source_kind=record.source_kind,
        source_ref=record.source_ref,
        installed_pack_ref=installed_pack_ref,
        lock_ref=lock_ref,
        lane_id=lane_id,
        lane_label=lane_label,
        workers=workers,
        teams=teams,
        templates=templates,
        benchmarks=benchmarks,
        default_team=default_team,
        default_template=default_template,
        default_workset=default_workset,
        status="active",
        contract_template_kind=contract_defaults.get("contract_template_kind"),
        validation_criteria=_as_list(contract_defaults.get("validation_criteria")),
        forbidden_actions=_as_list(contract_defaults.get("forbidden_actions")),
        approval_required_actions=_as_list(contract_defaults.get("approval_required_actions")),
        warnings=warnings,
        errors=list(record.errors or []),
    )


def _agent_contract_defaults(manifest: PackManifest | None, default_template: str | None) -> dict[str, Any]:
    if manifest is None or manifest.pack_kind != "agent":
        return {}
    templates = [dict(item) for item in manifest.templates if isinstance(item, dict)]
    selected: dict[str, Any] | None = None
    if default_template:
        for template in templates:
            candidates = {
                str(template.get("name") or ""),
                str(template.get("template_id") or ""),
            }
            if default_template in candidates:
                selected = template
                break
    if selected is None:
        for template in templates:
            if str(template.get("template_kind") or "") == "agent_contract":
                selected = template
                break
    if selected is None:
        return {}
    safety_defaults = _as_dict(selected.get("safety_defaults"))
    validation_defaults = _as_dict(selected.get("validation_defaults"))
    template_kind = str(selected.get("template_kind") or "") or None
    return {
        "contract_template_kind": template_kind,
        "validation_criteria": _as_list(validation_defaults.get("validation_criteria")),
        "forbidden_actions": _as_list(safety_defaults.get("forbidden_actions")),
        "approval_required_actions": _as_list(safety_defaults.get("approval_required_actions")),
    }


def _load_manifest_for_record(project_root: Path, record: InstalledPackRecord) -> PackManifest | None:
    """installed record의 manifest copy를 로드한다."""
    manifest_ref = record.latest_manifest_ref or record.manifest_ref
    if not manifest_ref:
        return None
    path = Path(manifest_ref)
    if not path.is_absolute():
        path = Path(project_root).resolve() / manifest_ref
    try:
        return PackManifestLoader().load(path)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("active pack manifest load failed: %s", exc)
        return None


def _find_lock_entry(project_root: Path, record: InstalledPackRecord) -> PackLockEntry | None:
    """pack_lock.yaml에서 installed pack entry를 찾는다."""
    try:
        lockfile = PackLockStore().load(default_pack_lock_path(project_root))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        logger.warning("active pack lockfile load failed: %s", exc)
        return None
    for entry in lockfile.packs:
        if entry.pack_id != record.pack_id:
            continue
        if entry.namespace and record.namespace and entry.namespace != record.namespace:
            continue
        return entry
    return None


def _pack_ref(record: InstalledPackRecord) -> str:
    """사람이 읽기 쉬운 pack ref를 만든다."""
    base = f"{record.namespace}/{record.pack_id}" if record.namespace else record.pack_id
    return f"{base}@{record.version}" if record.version else base


def _context_from_dict(payload: dict[str, Any]) -> ActivePackContext:
    """dict payload에서 ActivePackContext를 복원한다."""
    return ActivePackContext(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        activated_at=str(payload.get("activated_at") or _now()),
        pack_ref=str(payload.get("pack_ref") or ""),
        pack_id=str(payload.get("pack_id") or ""),
        pack_name=str(payload.get("pack_name") or ""),
        pack_kind=str(payload.get("pack_kind") or ""),
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        source_ref=str(payload.get("source_ref")) if payload.get("source_ref") is not None else None,
        installed_pack_ref=str(payload.get("installed_pack_ref")) if payload.get("installed_pack_ref") is not None else None,
        lock_ref=str(payload.get("lock_ref")) if payload.get("lock_ref") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        workers=_as_list(payload.get("workers")),
        teams=_as_list(payload.get("teams")),
        templates=_as_list(payload.get("templates")),
        benchmarks=_as_list(payload.get("benchmarks")),
        default_team=str(payload.get("default_team")) if payload.get("default_team") is not None else None,
        default_template=str(payload.get("default_template")) if payload.get("default_template") is not None else None,
        default_workset=str(payload.get("default_workset")) if payload.get("default_workset") is not None else None,
        status=str(payload.get("status") or "inactive"),
        contract_template_kind=str(payload.get("contract_template_kind")) if payload.get("contract_template_kind") is not None else None,
        validation_criteria=_as_list(payload.get("validation_criteria")),
        forbidden_actions=_as_list(payload.get("forbidden_actions")),
        approval_required_actions=_as_list(payload.get("approval_required_actions")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _request_examples(context: ActivePackContext) -> list[str]:
    """pack별 first job 예시 요청을 반환한다."""
    if context.pack_id == "auth-bug-core" or "auth" in (context.lane_id or ""):
        return [
            "로그인 에러 수정해",
            "username normalize 버그 수정해",
            "tests/test_auth.py 기준으로 작은 패치 만들어줘",
        ]
    label = context.lane_label or context.pack_name or context.pack_id
    return [
        f"{label}에 맞는 작은 버그 수정해",
        "관련 테스트 기준으로 좁은 패치 만들어줘",
    ]


def _fit_status(context: ActivePackContext) -> str:
    """active pack의 기본 fit 상태를 보수적으로 판단한다."""
    if context.pack_id == "auth-bug-core" or "auth" in (context.lane_id or ""):
        return "strong"
    if context.lane_id:
        return "partial"
    return "unknown"


def _request_fit(context: ActivePackContext, request: str) -> str:
    """요청 문장과 active pack lane의 대략적 적합도를 판단한다."""
    text = str(request or "").lower()
    auth_markers = ["login", "auth", "username", "password", "로그인", "인증"]
    if context.pack_id == "auth-bug-core" or "auth" in (context.lane_id or ""):
        return "in-lane" if any(marker in text for marker in auth_markers) else "outside-lane"
    return "unknown"
