"""qualification 결과를 템플릿 운영 결정과 lane default로 승격하는 모듈."""

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

from engine.project_template_library_decisions import (
    TemplateLibraryDecision,
    TemplateLibraryDecisionStore,
    build_template_library_decision,
    default_template_library_decisions_path,
)
from engine.project_template_library_policy import build_and_save_template_library_policy_overlay
from engine.project_template_qualification import (
    TemplateQualificationReport,
    TemplateQualificationStore,
    resolve_template_qualification_path,
)
from engine.project_templates import HarnessTemplateStore, default_templates_path
from engine.project_win_lane import DEFAULT_TEMPLATE, LANE_ID, LANE_LABEL, default_lane_dir

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
PARENT_ACTIONS = {"keep_as_backup", "retire", "none"}


class QualificationAcceptBlockedError(RuntimeError):
    """qualification verdict가 충분하지 않아 accept가 차단될 때 발생한다."""

    def __init__(self, verdict: str | None, qualification_ref: str) -> None:
        super().__init__(f"qualification verdict is not candidate_stronger: {verdict or 'unknown'}")
        self.verdict = verdict
        self.qualification_ref = qualification_ref


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    """짧은 식별자를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str | None, fallback: str = "item") -> str:
    """문자열을 파일/키에 안전한 slug로 바꾼다."""
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
        logger.warning("template qualification decision artifact load failed: %s (%s)", path, exc)
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


def qualification_decisions_path(project_root: Path) -> Path:
    """qualification decision store 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "qualification_decisions.yaml"


def lane_playbook_path(project_root: Path) -> Path:
    """strongest lane playbook 경로."""
    return default_lane_dir(project_root) / "playbook.yaml"


@dataclass
class TemplateQualificationDecision:
    """qualification accept/dismiss 운영 결정."""

    schema_version: str
    decision_id: str
    created_at: str
    updated_at: str | None
    qualification_ref: str
    qualification_verdict: str | None
    candidate_template_name: str
    candidate_template_id: str | None
    reference_template_name: str | None
    reference_template_id: str | None
    status: str
    actions: dict[str, Any]
    title: str
    summary: str
    resolution: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateQualificationDecisionStoreModel:
    """qualification decision store 모델."""

    schema_version: str
    updated_at: str
    decisions: list[TemplateQualificationDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class LanePlaybook:
    """strongest lane의 future-facing 기본 템플릿 운영 상태."""

    schema_version: str
    updated_at: str
    lane_id: str
    label: str
    default_template_name: str | None
    backup_templates: list[str]
    retired_templates: list[str]
    source_decision_ref: str | None
    canary_template_name: str | None = None
    canary_stage_id: str | None = None
    canary_status: str | None = None
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class TemplateQualificationDecisionStore:
    """qualification decision 저장소."""

    def load(self, path: Path) -> TemplateQualificationDecisionStoreModel:
        """qualification_decisions.yaml을 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        decisions = [
            _decision_from_dict(item)
            for item in payload.get("decisions", []) or []
            if isinstance(item, dict)
        ]
        return TemplateQualificationDecisionStoreModel(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _now()),
            decisions=decisions,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, path: Path, model: TemplateQualificationDecisionStoreModel) -> Path:
        """decision store를 저장한다."""
        model.updated_at = _now()
        return _save_yaml(Path(path).resolve(), model.to_dict())

    def add(self, path: Path, decision: TemplateQualificationDecision) -> Path:
        """decision을 append한다."""
        model = self.load(path)
        model.decisions.append(decision)
        return self.save(path, model)


class LanePlaybookStore:
    """lane playbook 저장소."""

    def load(self, path: Path) -> LanePlaybook:
        """lane playbook을 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            return empty_lane_playbook()
        return LanePlaybook(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _now()),
            lane_id=str(payload.get("lane_id") or LANE_ID),
            label=str(payload.get("label") or LANE_LABEL),
            default_template_name=str(payload.get("default_template_name")) if payload.get("default_template_name") is not None else None,
            backup_templates=[str(item) for item in payload.get("backup_templates", []) if item],
            retired_templates=[str(item) for item in payload.get("retired_templates", []) if item],
            source_decision_ref=str(payload.get("source_decision_ref")) if payload.get("source_decision_ref") is not None else None,
            canary_template_name=str(payload.get("canary_template_name")) if payload.get("canary_template_name") is not None else None,
            canary_stage_id=str(payload.get("canary_stage_id")) if payload.get("canary_stage_id") is not None else None,
            canary_status=str(payload.get("canary_status")) if payload.get("canary_status") is not None else None,
            notes=[str(item) for item in payload.get("notes", []) if item],
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, path: Path, playbook: LanePlaybook) -> Path:
        """lane playbook을 저장한다."""
        playbook.updated_at = _now()
        return _save_yaml(Path(path).resolve(), playbook.to_dict())


def empty_lane_playbook() -> LanePlaybook:
    """비어 있는 lane playbook을 만든다."""
    return LanePlaybook(
        schema_version=SCHEMA_VERSION,
        updated_at=_now(),
        lane_id=LANE_ID,
        label=LANE_LABEL,
        default_template_name=None,
        backup_templates=[],
        retired_templates=[],
        source_decision_ref=None,
        canary_template_name=None,
        canary_stage_id=None,
        canary_status=None,
        notes=[],
        warnings=[],
        errors=[],
    )


def accept_qualification(
    project_root: Path,
    qualification_ref: str,
    *,
    set_lane_default: bool = False,
    parent_action: str = "keep_as_backup",
    resolution: str | None = None,
    force: bool = False,
) -> tuple[TemplateQualificationDecision, LanePlaybook | None, list[TemplateLibraryDecision], Any, Path]:
    """qualification을 운영 결정으로 accept하고 필요한 library/lane 상태를 갱신한다."""
    root = Path(project_root).resolve()
    if parent_action not in PARENT_ACTIONS:
        raise ValueError(f"unsupported parent action: {parent_action}")
    qualification_path = resolve_template_qualification_path(root, qualification_ref)
    report = TemplateQualificationStore().load(qualification_path)
    _require_template(root, report.candidate_template_name)
    if report.reference_template_name:
        _require_template(root, report.reference_template_name)
    warnings: list[str] = []
    if report.verdict != "candidate_stronger" and not force:
        raise QualificationAcceptBlockedError(report.verdict, _relative(qualification_path, root))
    if report.verdict != "candidate_stronger" and force:
        warnings.append(f"forced accept without candidate_stronger verdict: {report.verdict}")
    from engine.project_template_qualification_rollback import (
        capture_qualification_adoption_state,
        save_qualification_adoption,
    )

    before_state = capture_qualification_adoption_state(
        root,
        report.candidate_template_name,
        report.reference_template_name,
    )
    decision = _decision_from_report(
        root,
        qualification_path,
        report,
        status="accepted",
        set_lane_default=set_lane_default,
        parent_action=parent_action,
        resolution=resolution,
        warnings=warnings,
    )
    TemplateQualificationDecisionStore().add(qualification_decisions_path(root), decision)
    library_decisions = _apply_library_decisions(root, decision, report, qualification_path, resolution)
    build_and_save_template_library_policy_overlay(root)
    playbook: LanePlaybook | None = None
    if set_lane_default:
        playbook = _apply_lane_playbook(root, decision, report, parent_action)
    after_state = capture_qualification_adoption_state(
        root,
        report.candidate_template_name,
        report.reference_template_name,
    )
    adoption, adoption_path = save_qualification_adoption(
        root,
        decision,
        before_state=before_state,
        after_state=after_state,
    )
    return decision, playbook, library_decisions, adoption, adoption_path


def dismiss_qualification(
    project_root: Path,
    qualification_ref: str,
    *,
    resolution: str | None = None,
) -> TemplateQualificationDecision:
    """qualification 채택을 기각한다. 기존 library/lane mutation은 되돌리지 않는다."""
    root = Path(project_root).resolve()
    qualification_path = resolve_template_qualification_path(root, qualification_ref)
    report = TemplateQualificationStore().load(qualification_path)
    decision = _decision_from_report(
        root,
        qualification_path,
        report,
        status="dismissed",
        set_lane_default=False,
        parent_action="none",
        resolution=resolution,
        warnings=["dismiss does not roll back prior library or lane playbook changes"],
    )
    TemplateQualificationDecisionStore().add(qualification_decisions_path(root), decision)
    return decision


def load_qualification_decision_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """template show/lineage/status에서 쓰는 qualification decision 요약."""
    root = Path(project_root).resolve()
    model = TemplateQualificationDecisionStore().load(qualification_decisions_path(root))
    decisions = list(model.decisions)
    if template_name:
        wanted = _slug(template_name)
        decisions = [
            decision for decision in decisions
            if _slug(decision.candidate_template_name) == wanted
            or _slug(str(decision.reference_template_name or "")) == wanted
        ]
    latest_by_candidate: dict[str, TemplateQualificationDecision] = {}
    for decision in decisions:
        latest_by_candidate[_slug(decision.candidate_template_name)] = decision
    current = list(latest_by_candidate.values())
    accepted = [decision for decision in current if decision.status == "accepted"]
    dismissed = [decision for decision in current if decision.status == "dismissed"]
    latest = decisions[-1] if decisions else None
    return {
        "total": len(decisions),
        "accepted": [decision.candidate_template_name for decision in accepted],
        "dismissed": [decision.candidate_template_name for decision in dismissed],
        "latest_status": latest.status if latest else None,
        "latest_candidate": latest.candidate_template_name if latest else None,
        "latest_reference": latest.reference_template_name if latest else None,
        "latest_verdict": latest.qualification_verdict if latest else None,
        "latest_actions": dict(latest.actions) if latest else {},
        "decisions_path": _relative(qualification_decisions_path(root), root),
    }


def load_lane_playbook_summary(project_root: Path) -> dict[str, Any]:
    """lane playbook 요약을 반환한다."""
    playbook = LanePlaybookStore().load(lane_playbook_path(project_root))
    if (
        not playbook.default_template_name
        and not playbook.backup_templates
        and not playbook.retired_templates
        and not playbook.canary_template_name
    ):
        return {}
    return {
        "lane_id": playbook.lane_id,
        "label": playbook.label,
        "default_template_name": playbook.default_template_name,
        "backup_templates": list(playbook.backup_templates),
        "retired_templates": list(playbook.retired_templates),
        "source_decision_ref": playbook.source_decision_ref,
        "canary_template_name": playbook.canary_template_name,
        "canary_stage_id": playbook.canary_stage_id,
        "canary_status": playbook.canary_status,
        "notes": list(playbook.notes),
        "warnings": list(playbook.warnings),
        "errors": list(playbook.errors),
    }


def render_qualification_accepted(
    decision: TemplateQualificationDecision,
    playbook: LanePlaybook | None,
    library_decisions: list[TemplateLibraryDecision],
    adoption_ref: str | None = None,
) -> str:
    """qualification accept 결과를 렌더링한다."""
    lines = [
        "Template qualification accepted.",
        "",
        "Candidate:",
        f"  {decision.candidate_template_name}",
        "",
        "Actions:",
    ]
    lines.append("  - promoted in local library" if decision.actions.get("promote_candidate") else "  - candidate promotion skipped")
    if decision.actions.get("set_lane_default"):
        lines.append("  - set as lane default template")
    parent_action = decision.actions.get("parent_action")
    if parent_action == "keep_as_backup":
        lines.append("  - parent kept as backup")
    elif parent_action == "retire":
        lines.append("  - parent retired")
    else:
        lines.append("  - parent unchanged")
    if decision.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in decision.warnings])
    lines.extend(["", "Saved:", "  .cambrian/templates/qualification_decisions.yaml"])
    if adoption_ref:
        lines.append(f"  {adoption_ref}")
    if playbook is not None:
        lines.append("  .cambrian/lane/playbook.yaml")
    if library_decisions:
        lines.append("  .cambrian/templates/library_decisions.yaml")
    return "\n".join(lines)


def render_qualification_dismissed(decision: TemplateQualificationDecision) -> str:
    """qualification dismiss 결과를 렌더링한다."""
    lines = [
        "Template qualification dismissed.",
        "",
        "Candidate:",
        f"  {decision.candidate_template_name}",
        "",
        "Meaning:",
        "  this qualification will not switch the lane default or promote the candidate",
        "  dismiss does not roll back prior accepted library/playbook changes",
    ]
    if decision.resolution:
        lines.extend(["", "Resolution:", f"  {decision.resolution}"])
    lines.extend(["", "Saved:", "  .cambrian/templates/qualification_decisions.yaml"])
    return "\n".join(lines)


def render_qualification_decisions(decisions: list[TemplateQualificationDecision]) -> str:
    """qualification decision 목록을 렌더링한다."""
    accepted = [decision for decision in decisions if decision.status == "accepted"]
    dismissed = [decision for decision in decisions if decision.status == "dismissed"]
    lines = ["Template Qualification Decisions", "==================================================", "", "Accepted:"]
    if accepted:
        for decision in accepted:
            suffix = "lane default switched" if decision.actions.get("set_lane_default") else "promoted only"
            lines.append(f"  - {decision.candidate_template_name} -> {suffix}")
    else:
        lines.append("  none")
    lines.extend(["", "Dismissed:"])
    if dismissed:
        lines.extend([f"  - {decision.candidate_template_name}" for decision in dismissed])
    else:
        lines.append("  none")
    return "\n".join(lines)


def render_lane_playbook_summary(summary: dict[str, Any]) -> str:
    """lane playbook 요약을 렌더링한다."""
    if not summary:
        return "Lane playbook:\n  none"
    lines = [
        "Lane playbook:",
        f"  default template: {summary.get('default_template_name') or DEFAULT_TEMPLATE}",
    ]
    backups = [str(item) for item in summary.get("backup_templates", []) if item]
    retired = [str(item) for item in summary.get("retired_templates", []) if item]
    canary = str(summary.get("canary_template_name") or "").strip()
    if backups:
        lines.append(f"  backup templates: {', '.join(backups[:3])}")
    if retired:
        lines.append(f"  retired templates: {', '.join(retired[:3])}")
    if canary:
        lines.append(f"  canary template : {canary}")
    return "\n".join(lines)


def _apply_library_decisions(
    root: Path,
    decision: TemplateQualificationDecision,
    report: TemplateQualificationReport,
    qualification_path: Path,
    resolution: str | None,
) -> list[TemplateLibraryDecision]:
    library_store = TemplateLibraryDecisionStore()
    library_path = default_template_library_decisions_path(root)
    source_ref = _relative(qualification_path, root)
    recorded: list[TemplateLibraryDecision] = []
    if decision.actions.get("promote_candidate"):
        candidate_decision = build_template_library_decision(
            root,
            report.candidate_template_name,
            "promote",
            source_ref=source_ref,
            resolution=resolution or "accepted candidate_stronger qualification",
        )
        library_store.add(library_path, candidate_decision)
        recorded.append(candidate_decision)
    parent_action = str(decision.actions.get("parent_action") or "none")
    if report.reference_template_name and parent_action in {"keep_as_backup", "retire"}:
        kind = "backup" if parent_action == "keep_as_backup" else "retire"
        parent_decision = build_template_library_decision(
            root,
            report.reference_template_name,
            kind,
            source_ref=source_ref,
            resolution=resolution or f"qualification parent action: {parent_action}",
        )
        library_store.add(library_path, parent_decision)
        recorded.append(parent_decision)
    return recorded


def _apply_lane_playbook(
    root: Path,
    decision: TemplateQualificationDecision,
    report: TemplateQualificationReport,
    parent_action: str,
) -> LanePlaybook:
    store = LanePlaybookStore()
    playbook = store.load(lane_playbook_path(root))
    previous_default = playbook.default_template_name
    playbook.default_template_name = report.candidate_template_name
    if playbook.canary_template_name == report.candidate_template_name:
        playbook.canary_template_name = None
        playbook.canary_stage_id = None
        playbook.canary_status = None
    if parent_action == "keep_as_backup" and report.reference_template_name:
        playbook.backup_templates = _dedupe([*playbook.backup_templates, report.reference_template_name])
    if parent_action == "retire" and report.reference_template_name:
        playbook.retired_templates = _dedupe([*playbook.retired_templates, report.reference_template_name])
    if previous_default and previous_default != report.candidate_template_name and parent_action == "keep_as_backup":
        playbook.backup_templates = _dedupe([*playbook.backup_templates, previous_default])
    if previous_default and previous_default != report.candidate_template_name and parent_action == "retire":
        playbook.retired_templates = _dedupe([*playbook.retired_templates, previous_default])
    playbook.source_decision_ref = decision.decision_id
    playbook.notes = _dedupe([
        *playbook.notes,
        f"{report.candidate_template_name} selected as strongest-lane default via qualification",
    ])
    store.save(lane_playbook_path(root), playbook)
    return playbook


def _decision_from_report(
    root: Path,
    qualification_path: Path,
    report: TemplateQualificationReport,
    *,
    status: str,
    set_lane_default: bool,
    parent_action: str,
    resolution: str | None,
    warnings: list[str],
) -> TemplateQualificationDecision:
    qualification_ref = _relative(qualification_path, root)
    title = f"{status} qualification for {report.candidate_template_name}"
    summary = (
        f"{report.candidate_template_name} {status}; "
        f"verdict={report.verdict}; parent_action={parent_action}"
    )
    return TemplateQualificationDecision(
        schema_version=SCHEMA_VERSION,
        decision_id=f"template-qualification-decision-{status}-{_slug(report.candidate_template_name)}-{_short_id()}",
        created_at=_now(),
        updated_at=None,
        qualification_ref=qualification_ref,
        qualification_verdict=report.verdict,
        candidate_template_name=report.candidate_template_name,
        candidate_template_id=report.candidate_template_id,
        reference_template_name=report.reference_template_name,
        reference_template_id=report.reference_template_id,
        status=status,
        actions={
            "promote_candidate": status == "accepted",
            "set_lane_default": bool(set_lane_default) and status == "accepted",
            "parent_action": parent_action,
        },
        title=title,
        summary=summary,
        resolution=resolution,
        warnings=_dedupe(warnings),
        errors=[],
    )


def _require_template(root: Path, template_name: str) -> None:
    model = HarnessTemplateStore().load(default_templates_path(root))
    HarnessTemplateStore().find(model, template_name)


def _decision_from_dict(payload: dict[str, Any]) -> TemplateQualificationDecision:
    return TemplateQualificationDecision(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        decision_id=str(payload.get("decision_id") or f"qualification-decision-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        qualification_ref=str(payload.get("qualification_ref") or ""),
        qualification_verdict=str(payload.get("qualification_verdict")) if payload.get("qualification_verdict") is not None else None,
        candidate_template_name=str(payload.get("candidate_template_name") or ""),
        candidate_template_id=str(payload.get("candidate_template_id")) if payload.get("candidate_template_id") is not None else None,
        reference_template_name=str(payload.get("reference_template_name")) if payload.get("reference_template_name") is not None else None,
        reference_template_id=str(payload.get("reference_template_id")) if payload.get("reference_template_id") is not None else None,
        status=str(payload.get("status") or "dismissed"),
        actions=dict(payload.get("actions", {}) if isinstance(payload.get("actions"), dict) else {}),
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
