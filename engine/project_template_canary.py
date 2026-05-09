"""qualification 결과를 lane canary 템플릿으로 stage하는 모듈."""

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

from engine.project_template_qualification import (
    TemplateQualificationReport,
    TemplateQualificationStore,
    resolve_template_qualification_path,
)
from engine.project_template_qualification_decisions import (
    LanePlaybook,
    LanePlaybookStore,
    lane_playbook_path,
)
from engine.project_templates import HarnessTemplateStore, default_templates_path
from engine.project_win_lane import LANE_ID, LANE_LABEL

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


class TemplateCanaryStageBlockedError(RuntimeError):
    """canary stage 안전 조건이 맞지 않을 때 발생한다."""

    def __init__(self, message: str, qualification_ref: str | None = None) -> None:
        super().__init__(message)
        self.qualification_ref = qualification_ref


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


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
        logger.warning("template canary artifact load failed: %s (%s)", path, exc)
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


def qualification_stages_path(project_root: Path) -> Path:
    """qualification canary stage store 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "qualification_stages.yaml"


@dataclass
class TemplateCanaryStage:
    """lane canary로 stage된 qualification 후보."""

    schema_version: str
    stage_id: str
    created_at: str
    updated_at: str | None
    qualification_ref: str
    qualification_verdict: str | None
    candidate_template_name: str
    candidate_template_id: str | None
    reference_template_name: str | None
    reference_template_id: str | None
    lane_id: str | None
    lane_label: str | None
    status: str
    reason: str | None
    source_refs: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateCanaryStoreModel:
    """qualification canary stage store 모델."""

    schema_version: str
    updated_at: str
    active_stage_id: str | None
    stages: list[TemplateCanaryStage]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "active_stage_id": self.active_stage_id,
            "stages": [stage.to_dict() for stage in self.stages],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateCanaryStore:
    """qualification canary stage 저장소."""

    def load(self, path: Path) -> TemplateCanaryStoreModel:
        """qualification_stages.yaml을 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        stages = [
            _stage_from_dict(item)
            for item in payload.get("stages", []) or []
            if isinstance(item, dict)
        ]
        return TemplateCanaryStoreModel(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _now()),
            active_stage_id=(
                str(payload.get("active_stage_id"))
                if payload.get("active_stage_id") is not None
                else None
            ),
            stages=stages,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, path: Path, model: TemplateCanaryStoreModel) -> Path:
        """stage store를 저장한다."""
        model.updated_at = _now()
        return _save_yaml(Path(path).resolve(), model.to_dict())

    def add(self, path: Path, stage: TemplateCanaryStage) -> Path:
        """새 stage를 active canary로 추가한다."""
        model = self.load(path)
        model.stages.append(stage)
        model.active_stage_id = stage.stage_id if stage.status == "active" else model.active_stage_id
        return self.save(path, model)


def stage_qualification_as_canary(
    project_root: Path,
    qualification_ref: str,
    *,
    reason: str | None = None,
    force: bool = False,
) -> tuple[TemplateCanaryStage, LanePlaybook, Path]:
    """qualification 후보를 stable default 변경 없이 canary로 stage한다."""
    root = Path(project_root).resolve()
    qualification_path = resolve_template_qualification_path(root, qualification_ref)
    report = TemplateQualificationStore().load(qualification_path)
    _require_template(root, report.candidate_template_name)
    if report.reference_template_name:
        _require_template(root, report.reference_template_name)

    warnings: list[str] = []
    qualification_rel = _relative(qualification_path, root)
    if report.verdict != "candidate_stronger" and not force:
        raise TemplateCanaryStageBlockedError(
            f"qualification verdict is not candidate_stronger: {report.verdict or 'unknown'}",
            qualification_rel,
        )
    if report.verdict != "candidate_stronger" and force:
        warnings.append(f"forced canary stage without candidate_stronger verdict: {report.verdict}")

    store = TemplateCanaryStore()
    stages_path = qualification_stages_path(root)
    model = store.load(stages_path)
    active = _active_stage(model)
    if active is not None:
        raise TemplateCanaryStageBlockedError(
            f"a canary template is already active: {active.candidate_template_name}",
            qualification_rel,
        )

    stage = _stage_from_report(
        report,
        qualification_rel=qualification_rel,
        reason=reason or f"{report.verdict or 'unknown'} on {report.workset_name}",
        warnings=warnings,
    )
    store.add(stages_path, stage)
    playbook = _apply_canary_to_playbook(root, stage)
    return stage, playbook, stages_path


def unstage_qualification_canary(
    project_root: Path,
    qualification_ref: str,
    *,
    resolution: str | None = None,
) -> tuple[TemplateCanaryStage, LanePlaybook, Path]:
    """active canary를 제거하고 stable default는 유지한다."""
    root = Path(project_root).resolve()
    qualification_path = resolve_template_qualification_path(root, qualification_ref)
    report = TemplateQualificationStore().load(qualification_path)
    qualification_rel = _relative(qualification_path, root)
    stages_path = qualification_stages_path(root)
    store = TemplateCanaryStore()
    model = store.load(stages_path)
    active = _active_stage(model)
    if active is None:
        raise TemplateCanaryStageBlockedError("no active canary template is staged", qualification_rel)
    if (
        _slug(active.qualification_ref) != _slug(qualification_rel)
        and _slug(active.candidate_template_name) != _slug(report.candidate_template_name)
    ):
        raise TemplateCanaryStageBlockedError(
            f"active canary belongs to {active.candidate_template_name}, not {report.candidate_template_name}",
            qualification_rel,
        )
    active.status = "cleared"
    active.updated_at = _now()
    if resolution:
        active.reason = resolution
    model.active_stage_id = None
    model.stages = [active if stage.stage_id == active.stage_id else stage for stage in model.stages]
    store.save(stages_path, model)
    playbook = _clear_canary_from_playbook(root, active)
    return active, playbook, stages_path


def load_template_canary_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """status/show/lineage에서 쓰는 canary 요약."""
    root = Path(project_root).resolve()
    model = TemplateCanaryStore().load(qualification_stages_path(root))
    active = _active_stage(model)
    stages = list(model.stages)
    if template_name:
        wanted = _slug(template_name)
        stages = [
            stage
            for stage in stages
            if _slug(stage.candidate_template_name) == wanted
            or _slug(stage.reference_template_name) == wanted
        ]
        if active and active not in stages:
            active = None
    latest = stages[-1] if stages else None
    playbook = LanePlaybookStore().load(lane_playbook_path(root))
    if not active and not latest and not playbook.canary_template_name:
        return {}
    summary: dict[str, Any] = {
        "active_stage_id": active.stage_id if active else None,
        "active_template_name": active.candidate_template_name if active else playbook.canary_template_name,
        "active_reference_template_name": active.reference_template_name if active else None,
        "active_status": active.status if active else playbook.canary_status,
        "active_reason": active.reason if active else None,
        "stable_default_template_name": playbook.default_template_name,
        "lane_id": playbook.lane_id,
        "lane_label": playbook.label,
        "stages_path": _relative(qualification_stages_path(root), root),
    }
    if latest:
        summary.update({
            "latest_stage_id": latest.stage_id,
            "latest_candidate": latest.candidate_template_name,
            "latest_reference": latest.reference_template_name,
            "latest_status": latest.status,
            "latest_reason": latest.reason,
            "latest_verdict": latest.qualification_verdict,
        })
    return summary


def render_template_canary(stage: TemplateCanaryStage | None, playbook: LanePlaybook | None = None) -> str:
    """현재 lane canary 상태를 사람이 읽기 좋게 렌더링한다."""
    stable = playbook.default_template_name if playbook else None
    lines = ["Lane Canary", "==================================================", ""]
    lines.extend(["Lane:", f"  {(playbook.label if playbook else LANE_LABEL)}", ""])
    lines.extend(["Stable default:", f"  {stable or 'none'}", ""])
    if stage is None:
        lines.extend(["Canary:", "  none"])
        return "\n".join(lines)
    lines.extend([
        "Canary:",
        f"  {stage.candidate_template_name}",
        "",
        "Meaning:",
        "  this template is staged as a preferred alternative before any lane-default switch",
    ])
    if stage.reference_template_name:
        lines.extend(["", "Reference:", f"  {stage.reference_template_name}"])
    if stage.reason:
        lines.extend(["", "Reason:", f"  {stage.reason}"])
    if stage.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in stage.warnings])
    return "\n".join(lines)


def render_template_canary_staged(stage: TemplateCanaryStage, playbook: LanePlaybook, stages_path: Path, root: Path) -> str:
    """qualify-stage 결과를 렌더링한다."""
    lines = [
        "Template staged as canary.",
        "",
        "Candidate:",
        f"  {stage.candidate_template_name}",
        "",
        "Reference:",
        f"  {stage.reference_template_name or 'unknown'}",
        "",
        "Meaning:",
        "  the stable lane default remains unchanged, but this candidate will now be surfaced as a preferred alternative",
        "",
        "Stable default:",
        f"  {playbook.default_template_name or 'none'}",
        "",
        "Saved:",
        f"  {_relative(stages_path, root)}",
        "  .cambrian/lane/playbook.yaml",
    ]
    if stage.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in stage.warnings])
    return "\n".join(lines)


def render_template_canary_cleared(stage: TemplateCanaryStage, playbook: LanePlaybook) -> str:
    """qualify-unstage 결과를 렌더링한다."""
    lines = [
        "Template canary cleared.",
        "",
        "Candidate:",
        f"  {stage.candidate_template_name}",
        "",
        "Stable default:",
        f"  {playbook.default_template_name or 'none'}",
    ]
    if stage.reason:
        lines.extend(["", "Resolution:", f"  {stage.reason}"])
    return "\n".join(lines)


def render_template_canary_summary(summary: dict[str, Any]) -> str:
    """template show/lineage/status용 canary 요약."""
    if not summary:
        return "Canary:\n  none"
    active = summary.get("active_template_name")
    latest_status = summary.get("latest_status") or summary.get("active_status")
    if active:
        lines = ["Canary status:", f"  {summary.get('active_status') or 'active'}"]
        lines.append(f"  template: {active}")
        default = summary.get("stable_default_template_name")
        if default:
            lines.append(f"  stable default: {default}")
        return "\n".join(lines)
    if latest_status:
        return "\n".join(["Canary status:", f"  {latest_status}"])
    return "Canary:\n  none"


def active_canary_stage(project_root: Path) -> TemplateCanaryStage | None:
    """현재 active canary stage를 반환한다."""
    model = TemplateCanaryStore().load(qualification_stages_path(project_root))
    return _active_stage(model)


def _stage_from_report(
    report: TemplateQualificationReport,
    *,
    qualification_rel: str,
    reason: str,
    warnings: list[str],
) -> TemplateCanaryStage:
    """qualification report에서 stage 모델을 만든다."""
    return TemplateCanaryStage(
        schema_version=SCHEMA_VERSION,
        stage_id=f"template-canary-stage-{_slug(report.candidate_template_name)}-{_short_id()}",
        created_at=_now(),
        updated_at=None,
        qualification_ref=qualification_rel,
        qualification_verdict=report.verdict,
        candidate_template_name=report.candidate_template_name,
        candidate_template_id=report.candidate_template_id,
        reference_template_name=report.reference_template_name,
        reference_template_id=report.reference_template_id,
        lane_id=LANE_ID,
        lane_label=LANE_LABEL,
        status="active",
        reason=reason,
        source_refs={
            "qualification_ref": qualification_rel,
            "candidate_template_ref": report.source_refs.get("candidate_template_ref"),
            "reference_template_ref": report.source_refs.get("reference_template_ref"),
            "lineage_ref": report.source_refs.get("lineage_ref"),
        },
        warnings=_dedupe(warnings),
        errors=[],
    )


def _apply_canary_to_playbook(root: Path, stage: TemplateCanaryStage) -> LanePlaybook:
    """lane playbook에 canary 슬롯만 기록한다."""
    store = LanePlaybookStore()
    playbook = store.load(lane_playbook_path(root))
    playbook.canary_template_name = stage.candidate_template_name
    playbook.canary_stage_id = stage.stage_id
    playbook.canary_status = "active"
    playbook.notes = _dedupe([
        *playbook.notes,
        f"{stage.candidate_template_name} staged as strongest-lane canary",
    ])
    store.save(lane_playbook_path(root), playbook)
    return playbook


def _clear_canary_from_playbook(root: Path, stage: TemplateCanaryStage) -> LanePlaybook:
    """lane playbook의 canary 슬롯을 비운다."""
    store = LanePlaybookStore()
    playbook = store.load(lane_playbook_path(root))
    if not playbook.canary_stage_id or playbook.canary_stage_id == stage.stage_id:
        playbook.canary_template_name = None
        playbook.canary_stage_id = None
        playbook.canary_status = None
    playbook.notes = _dedupe([
        *playbook.notes,
        f"{stage.candidate_template_name} canary cleared",
    ])
    store.save(lane_playbook_path(root), playbook)
    return playbook


def _active_stage(model: TemplateCanaryStoreModel) -> TemplateCanaryStage | None:
    """store 모델에서 active stage를 찾는다."""
    if model.active_stage_id:
        for stage in model.stages:
            if stage.stage_id == model.active_stage_id and stage.status == "active":
                return stage
    for stage in reversed(model.stages):
        if stage.status == "active":
            return stage
    return None


def _require_template(project_root: Path, template_name: str) -> None:
    """template store에 대상 템플릿이 있는지 확인한다."""
    model = HarnessTemplateStore().load(default_templates_path(project_root))
    HarnessTemplateStore().find(model, template_name)


def _stage_from_dict(payload: dict[str, Any]) -> TemplateCanaryStage:
    """dict에서 TemplateCanaryStage를 복원한다."""
    return TemplateCanaryStage(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        stage_id=str(payload.get("stage_id") or f"template-canary-stage-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        qualification_ref=str(payload.get("qualification_ref") or ""),
        qualification_verdict=str(payload.get("qualification_verdict")) if payload.get("qualification_verdict") is not None else None,
        candidate_template_name=str(payload.get("candidate_template_name") or ""),
        candidate_template_id=str(payload.get("candidate_template_id")) if payload.get("candidate_template_id") is not None else None,
        reference_template_name=str(payload.get("reference_template_name")) if payload.get("reference_template_name") is not None else None,
        reference_template_id=str(payload.get("reference_template_id")) if payload.get("reference_template_id") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        status=str(payload.get("status") or "active"),
        reason=str(payload.get("reason")) if payload.get("reason") is not None else None,
        source_refs=dict(payload.get("source_refs", {}) if isinstance(payload.get("source_refs"), dict) else {}),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
