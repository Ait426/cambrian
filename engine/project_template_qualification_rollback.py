"""qualification adoption snapshot과 rollback을 관리하는 모듈."""

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
    build_template_library_decision,
    current_library_decision_by_template,
    default_template_library_decisions_path,
    TemplateLibraryDecisionStore,
)
from engine.project_template_library_policy import build_and_save_template_library_policy_overlay
from engine.project_template_qualification_decisions import (
    LanePlaybook,
    LanePlaybookStore,
    lane_playbook_path,
)
from engine.project_win_lane import LANE_ID, LANE_LABEL

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


class QualificationAdoptionRollbackBlockedError(RuntimeError):
    """qualification adoption rollback이 안전 조건을 만족하지 못할 때 발생한다."""


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓰는 UTC timestamp를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 구분자를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str | None, fallback: str = "item") -> str:
    """값을 파일명에 안전한 slug로 바꾼다."""
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
        logger.warning("qualification rollback artifact load failed: %s (%s)", path, exc)
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


def qualification_adoptions_dir(project_root: Path) -> Path:
    """qualification adoption snapshot 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "qualification_adoptions"


def qualification_rollbacks_dir(project_root: Path) -> Path:
    """qualification rollback 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "qualification_rollbacks"


def default_qualification_adoption_path(project_root: Path, candidate_template_name: str) -> Path:
    """adoption snapshot 기본 저장 경로."""
    return qualification_adoptions_dir(project_root) / (
        f"adoption_{_slug(candidate_template_name)}_{_stamp()}_{_short_id()}.yaml"
    )


def default_qualification_rollback_path(project_root: Path, candidate_template_name: str) -> Path:
    """rollback 기본 저장 경로."""
    return qualification_rollbacks_dir(project_root) / (
        f"rollback_{_slug(candidate_template_name)}_{_stamp()}_{_short_id()}.yaml"
    )


@dataclass
class TemplateQualificationAdoption:
    """qualification accept로 실제 적용된 운영 상태 snapshot."""

    schema_version: str
    adoption_id: str
    created_at: str
    updated_at: str | None
    qualification_decision_ref: str
    qualification_ref: str | None
    candidate_template_name: str
    candidate_template_id: str | None
    reference_template_name: str | None
    reference_template_id: str | None
    actions_applied: dict[str, Any]
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateQualificationRollback:
    """qualification adoption rollback 결과."""

    schema_version: str
    rollback_id: str
    created_at: str
    updated_at: str | None
    adoption_ref: str
    qualification_decision_ref: str | None
    candidate_template_name: str
    reference_template_name: str | None
    restored_state: dict[str, Any]
    resolution: str | None
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class TemplateQualificationAdoptionStore:
    """qualification adoption snapshot 저장소."""

    def save(self, adoption: TemplateQualificationAdoption, path: Path) -> Path:
        """adoption snapshot을 저장한다."""
        return _save_yaml(Path(path).resolve(), adoption.to_dict())

    def load(self, path: Path) -> TemplateQualificationAdoption:
        """adoption snapshot을 로드한다."""
        return _adoption_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, adoptions_dir: Path) -> list[TemplateQualificationAdoption]:
        """저장된 adoption snapshot 목록을 최신순으로 반환한다."""
        target = Path(adoptions_dir).resolve()
        if not target.exists():
            return []
        adoptions = [self.load(path) for path in target.glob("adoption_*.yaml")]
        return sorted(adoptions, key=lambda item: item.created_at, reverse=True)


class TemplateQualificationRollbackStore:
    """qualification rollback 저장소."""

    def save(self, rollback: TemplateQualificationRollback, path: Path) -> Path:
        """rollback 결과를 저장한다."""
        return _save_yaml(Path(path).resolve(), rollback.to_dict())

    def load(self, path: Path) -> TemplateQualificationRollback:
        """rollback 결과를 로드한다."""
        return _rollback_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, rollbacks_dir: Path) -> list[TemplateQualificationRollback]:
        """저장된 rollback 목록을 최신순으로 반환한다."""
        target = Path(rollbacks_dir).resolve()
        if not target.exists():
            return []
        rollbacks = [self.load(path) for path in target.glob("rollback_*.yaml")]
        return sorted(rollbacks, key=lambda item: item.created_at, reverse=True)


def capture_qualification_adoption_state(
    project_root: Path,
    candidate_template_name: str,
    reference_template_name: str | None,
) -> dict[str, Any]:
    """현재 library standing과 lane playbook 상태를 snapshot으로 캡처한다."""
    root = Path(project_root).resolve()
    library = current_library_decision_by_template(root)
    playbook_payload = _load_yaml(lane_playbook_path(root))
    candidate_key = _slug(candidate_template_name)
    reference_key = _slug(reference_template_name) if reference_template_name else None
    return {
        "candidate_library_standing": _standing_payload(library.get(candidate_key)),
        "reference_library_standing": _standing_payload(library.get(reference_key)) if reference_key else None,
        "lane_playbook_exists": lane_playbook_path(root).exists(),
        "lane_default_template_name": playbook_payload.get("default_template_name"),
        "lane_backup_templates": [str(item) for item in playbook_payload.get("backup_templates", []) if item],
        "lane_retired_templates": [str(item) for item in playbook_payload.get("retired_templates", []) if item],
        "lane_canary_template_name": playbook_payload.get("canary_template_name"),
        "lane_canary_stage_id": playbook_payload.get("canary_stage_id"),
        "lane_canary_status": playbook_payload.get("canary_status"),
        "lane_source_decision_ref": playbook_payload.get("source_decision_ref"),
        "lane_notes": [str(item) for item in playbook_payload.get("notes", []) if item],
        "lane_warnings": [str(item) for item in playbook_payload.get("warnings", []) if item],
        "lane_errors": [str(item) for item in playbook_payload.get("errors", []) if item],
    }


def save_qualification_adoption(
    project_root: Path,
    decision: Any,
    *,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
) -> tuple[TemplateQualificationAdoption, Path]:
    """qualification accept 결과를 adoption snapshot으로 저장한다."""
    root = Path(project_root).resolve()
    adoption = TemplateQualificationAdoption(
        schema_version=SCHEMA_VERSION,
        adoption_id=f"qualification-adoption-{_slug(getattr(decision, 'candidate_template_name', None))}-{_short_id()}",
        created_at=_now(),
        updated_at=None,
        qualification_decision_ref=str(getattr(decision, "decision_id", "")),
        qualification_ref=str(getattr(decision, "qualification_ref", "")) or None,
        candidate_template_name=str(getattr(decision, "candidate_template_name", "")),
        candidate_template_id=getattr(decision, "candidate_template_id", None),
        reference_template_name=getattr(decision, "reference_template_name", None),
        reference_template_id=getattr(decision, "reference_template_id", None),
        actions_applied={
            "promoted_candidate": bool(getattr(decision, "actions", {}).get("promote_candidate")),
            "set_lane_default": bool(getattr(decision, "actions", {}).get("set_lane_default")),
            "parent_action": str(getattr(decision, "actions", {}).get("parent_action") or "none"),
        },
        before_state=dict(before_state),
        after_state=dict(after_state),
        status="applied",
        warnings=[],
        errors=[],
    )
    path = default_qualification_adoption_path(root, adoption.candidate_template_name)
    TemplateQualificationAdoptionStore().save(adoption, path)
    return adoption, path


def resolve_qualification_adoption_path(project_root: Path, adoption_ref: str) -> Path:
    """adoption id 또는 path를 실제 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(adoption_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in qualification_adoptions_dir(root).glob("adoption_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == adoption_ref or str(payload.get("adoption_id") or "") == adoption_ref:
            return path.resolve()
    raise FileNotFoundError(f"qualification adoption not found: {adoption_ref}")


def revert_qualification_adoption(
    project_root: Path,
    adoption_ref: str,
    *,
    resolution: str | None = None,
) -> tuple[TemplateQualificationRollback, TemplateQualificationAdoption, Path, list[TemplateLibraryDecision]]:
    """qualification adoption snapshot을 기준으로 library/lane 상태를 복구한다."""
    root = Path(project_root).resolve()
    adoption_path = resolve_qualification_adoption_path(root, adoption_ref)
    adoption_store = TemplateQualificationAdoptionStore()
    adoption = adoption_store.load(adoption_path)
    if adoption.status != "applied":
        raise QualificationAdoptionRollbackBlockedError("This qualification adoption has already been reverted.")
    if not isinstance(adoption.before_state, dict):
        raise QualificationAdoptionRollbackBlockedError("Cannot restore because the adoption snapshot is incomplete.")

    library_decisions = _restore_library_standing(root, adoption, _relative(adoption_path, root), resolution)
    restored_playbook = _restore_lane_playbook(root, adoption.before_state)
    build_and_save_template_library_policy_overlay(root)

    rollback = TemplateQualificationRollback(
        schema_version=SCHEMA_VERSION,
        rollback_id=f"qualification-rollback-{_slug(adoption.candidate_template_name)}-{_short_id()}",
        created_at=_now(),
        updated_at=None,
        adoption_ref=_relative(adoption_path, root),
        qualification_decision_ref=adoption.qualification_decision_ref,
        candidate_template_name=adoption.candidate_template_name,
        reference_template_name=adoption.reference_template_name,
        restored_state={
            "candidate_library_standing": adoption.before_state.get("candidate_library_standing"),
            "reference_library_standing": adoption.before_state.get("reference_library_standing"),
            "lane_default_template_name": restored_playbook.default_template_name,
            "lane_backup_templates": list(restored_playbook.backup_templates),
            "lane_retired_templates": list(restored_playbook.retired_templates),
            "lane_canary_template_name": restored_playbook.canary_template_name,
            "lane_canary_stage_id": restored_playbook.canary_stage_id,
            "lane_canary_status": restored_playbook.canary_status,
        },
        resolution=resolution,
        status="reverted",
        warnings=[],
        errors=[],
    )
    rollback_path = TemplateQualificationRollbackStore().save(
        rollback,
        default_qualification_rollback_path(root, adoption.candidate_template_name),
    )
    adoption.status = "reverted"
    adoption.updated_at = _now()
    adoption_store.save(adoption, adoption_path)
    return rollback, adoption, rollback_path, library_decisions


def load_qualification_adoption_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """template show/lineage/status에서 쓰는 adoption/rollback 요약."""
    root = Path(project_root).resolve()
    adoptions = TemplateQualificationAdoptionStore().list(qualification_adoptions_dir(root))
    rollbacks = TemplateQualificationRollbackStore().list(qualification_rollbacks_dir(root))
    if template_name:
        wanted = _slug(template_name)
        adoptions = [
            item for item in adoptions
            if _slug(item.candidate_template_name) == wanted
            or _slug(item.reference_template_name) == wanted
        ]
        rollbacks = [
            item for item in rollbacks
            if _slug(item.candidate_template_name) == wanted
            or _slug(item.reference_template_name) == wanted
        ]
    latest_adoption = adoptions[0] if adoptions else None
    latest_rollback = rollbacks[0] if rollbacks else None
    summary: dict[str, Any] = {
        "adoption_count": len(adoptions),
        "rollback_count": len(rollbacks),
    }
    if latest_adoption:
        summary.update({
            "latest_adoption_id": latest_adoption.adoption_id,
            "latest_adoption_status": latest_adoption.status,
            "latest_candidate": latest_adoption.candidate_template_name,
            "latest_reference": latest_adoption.reference_template_name,
            "latest_actions": dict(latest_adoption.actions_applied),
            "latest_lane_default_after": latest_adoption.after_state.get("lane_default_template_name"),
            "latest_lane_default_before": latest_adoption.before_state.get("lane_default_template_name"),
        })
    if latest_rollback:
        summary.update({
            "latest_rollback_id": latest_rollback.rollback_id,
            "latest_rollback_status": latest_rollback.status,
            "latest_rollback_candidate": latest_rollback.candidate_template_name,
            "latest_restored_lane_default": latest_rollback.restored_state.get("lane_default_template_name"),
            "latest_rollback_ref": latest_rollback.adoption_ref,
        })
    return summary if summary.get("adoption_count") or summary.get("rollback_count") else {}


def render_qualification_adoptions(adoptions: list[TemplateQualificationAdoption]) -> str:
    """qualification adoption 목록을 렌더링한다."""
    applied = [item for item in adoptions if item.status == "applied"]
    reverted = [item for item in adoptions if item.status == "reverted"]
    lines = ["Template Qualification Adoptions", "==================================================", "", "Applied:"]
    if applied:
        for item in applied:
            lane = "yes" if item.actions_applied.get("set_lane_default") else "no"
            parent_action = item.actions_applied.get("parent_action") or "none"
            lines.extend([
                f"  - {item.candidate_template_name}",
                f"    decision : {item.qualification_decision_ref}",
                f"    lane default switched : {lane}",
                f"    parent action : {parent_action}",
            ])
    else:
        lines.append("  none")
    lines.extend(["", "Reverted:"])
    if reverted:
        lines.extend([f"  - {item.candidate_template_name}" for item in reverted])
    else:
        lines.append("  none")
    return "\n".join(lines)


def render_qualification_reverted(
    rollback: TemplateQualificationRollback,
    rollback_path: Path,
    root: Path,
) -> str:
    """qualification rollback 결과를 렌더링한다."""
    lines = [
        "Template qualification adoption reverted.",
        "",
        "Candidate:",
        f"  {rollback.candidate_template_name}",
        "",
        "Restored:",
        "  - lane default template",
        "  - parent backup/retire state",
        "  - library standing",
    ]
    restored_default = rollback.restored_state.get("lane_default_template_name")
    if restored_default:
        lines.extend(["", "Lane default restored:", f"  {restored_default}"])
    if rollback.resolution:
        lines.extend(["", "Resolution:", f"  {rollback.resolution}"])
    lines.extend(["", "Saved:", f"  {_relative(rollback_path, root)}"])
    return "\n".join(lines)


def render_qualification_adoption_summary(summary: dict[str, Any]) -> str:
    """template show/lineage에서 쓰는 adoption/rollback 요약을 렌더링한다."""
    if not summary:
        return "Qualification adoption:\n  none"
    lines = ["Qualification adoption:"]
    if summary.get("latest_rollback_status") == "reverted":
        lines.append("  reverted")
        restored = summary.get("latest_restored_lane_default")
        if restored:
            lines.append(f"  restored lane default: {restored}")
    elif summary.get("latest_adoption_status"):
        lines.append(f"  {summary.get('latest_adoption_status')}")
        actions = summary.get("latest_actions") if isinstance(summary.get("latest_actions"), dict) else {}
        if actions.get("set_lane_default"):
            lines.append("  lane default switched: yes")
    return "\n".join(lines)


def _standing_payload(decision: TemplateLibraryDecision | None) -> dict[str, Any] | None:
    """library decision을 rollback snapshot에 필요한 standing payload로 축약한다."""
    if decision is None:
        return None
    return {
        "decision_kind": decision.decision_kind,
        "decision_id": decision.decision_id,
        "template_name": decision.template_name,
        "template_id": decision.template_id,
        "source_ref": decision.source_ref,
    }


def _restore_library_standing(
    root: Path,
    adoption: TemplateQualificationAdoption,
    adoption_source_ref: str,
    resolution: str | None,
) -> list[TemplateLibraryDecision]:
    """snapshot의 이전 standing으로 library decision을 복구한다."""
    recorded: list[TemplateLibraryDecision] = []
    for template_name, key in [
        (adoption.candidate_template_name, "candidate_library_standing"),
        (adoption.reference_template_name, "reference_library_standing"),
    ]:
        if not template_name:
            continue
        standing = adoption.before_state.get(key)
        restore_kind = _restore_kind(standing)
        decision = build_template_library_decision(
            root,
            template_name,
            restore_kind,
            source_ref=adoption_source_ref,
            resolution=resolution or "qualification adoption rollback restored previous standing",
        )
        TemplateLibraryDecisionStore().add(default_template_library_decisions_path(root), decision)
        recorded.append(decision)
    return recorded


def _restore_kind(standing: Any) -> str:
    """snapshot standing을 library decision kind로 변환한다."""
    if isinstance(standing, dict):
        kind = str(standing.get("decision_kind") or "").strip()
        if kind in {"promote", "keep", "backup", "watch", "retire", "clear"}:
            return kind
    return "clear"


def _restore_lane_playbook(root: Path, state: dict[str, Any]) -> LanePlaybook:
    """snapshot의 이전 lane playbook 상태를 복원한다."""
    playbook = LanePlaybook(
        schema_version=SCHEMA_VERSION,
        updated_at=_now(),
        lane_id=LANE_ID,
        label=LANE_LABEL,
        default_template_name=(
            str(state.get("lane_default_template_name"))
            if state.get("lane_default_template_name") is not None
            else None
        ),
        backup_templates=_dedupe([str(item) for item in state.get("lane_backup_templates", []) if item]),
        retired_templates=_dedupe([str(item) for item in state.get("lane_retired_templates", []) if item]),
        source_decision_ref=(
            str(state.get("lane_source_decision_ref"))
            if state.get("lane_source_decision_ref") is not None
            else None
        ),
        canary_template_name=(
            str(state.get("lane_canary_template_name"))
            if state.get("lane_canary_template_name") is not None
            else None
        ),
        canary_stage_id=(
            str(state.get("lane_canary_stage_id"))
            if state.get("lane_canary_stage_id") is not None
            else None
        ),
        canary_status=(
            str(state.get("lane_canary_status"))
            if state.get("lane_canary_status") is not None
            else None
        ),
        notes=[str(item) for item in state.get("lane_notes", []) if item],
        warnings=[str(item) for item in state.get("lane_warnings", []) if item],
        errors=[str(item) for item in state.get("lane_errors", []) if item],
    )
    LanePlaybookStore().save(lane_playbook_path(root), playbook)
    return playbook


def _adoption_from_dict(payload: dict[str, Any]) -> TemplateQualificationAdoption:
    """dict에서 TemplateQualificationAdoption을 복원한다."""
    return TemplateQualificationAdoption(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        adoption_id=str(payload.get("adoption_id") or f"qualification-adoption-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        qualification_decision_ref=str(payload.get("qualification_decision_ref") or ""),
        qualification_ref=str(payload.get("qualification_ref")) if payload.get("qualification_ref") is not None else None,
        candidate_template_name=str(payload.get("candidate_template_name") or ""),
        candidate_template_id=str(payload.get("candidate_template_id")) if payload.get("candidate_template_id") is not None else None,
        reference_template_name=str(payload.get("reference_template_name")) if payload.get("reference_template_name") is not None else None,
        reference_template_id=str(payload.get("reference_template_id")) if payload.get("reference_template_id") is not None else None,
        actions_applied=dict(payload.get("actions_applied", {}) if isinstance(payload.get("actions_applied"), dict) else {}),
        before_state=dict(payload.get("before_state", {}) if isinstance(payload.get("before_state"), dict) else {}),
        after_state=dict(payload.get("after_state", {}) if isinstance(payload.get("after_state"), dict) else {}),
        status=str(payload.get("status") or "applied"),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _rollback_from_dict(payload: dict[str, Any]) -> TemplateQualificationRollback:
    """dict에서 TemplateQualificationRollback을 복원한다."""
    return TemplateQualificationRollback(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        rollback_id=str(payload.get("rollback_id") or f"qualification-rollback-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        adoption_ref=str(payload.get("adoption_ref") or ""),
        qualification_decision_ref=str(payload.get("qualification_decision_ref")) if payload.get("qualification_decision_ref") is not None else None,
        candidate_template_name=str(payload.get("candidate_template_name") or ""),
        reference_template_name=str(payload.get("reference_template_name")) if payload.get("reference_template_name") is not None else None,
        restored_state=dict(payload.get("restored_state", {}) if isinstance(payload.get("restored_state"), dict) else {}),
        resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
        status=str(payload.get("status") or "reverted"),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
