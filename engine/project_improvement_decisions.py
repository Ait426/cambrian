"""개선 intervention의 keep/dismiss 판단과 persistent overlay를 관리하는 모듈."""

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

from engine.project_improvement_interventions import (
    ImprovementIntervention,
    ImprovementInterventionStore,
    ImprovementOverlayStore,
    default_overlay_path,
    empty_overlay,
    resolve_intervention_path,
)
from engine.project_improvement_loop import (
    ImprovementCycle,
    ImprovementCycleStore,
    default_improvement_dir,
    resolve_cycle_path,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
MAX_REVIEW_SUPPORT_BIAS = 0.3


class KeepBlockedError(RuntimeError):
    """개선 verdict가 충분하지 않아 keep이 차단될 때 발생한다."""

    def __init__(self, verdict: str | None, cycle_id: str | None) -> None:
        super().__init__(f"intervention was not evaluated as improved: {verdict or 'unknown'}")
        self.verdict = verdict
        self.cycle_id = cycle_id


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    """짧은 식별자를 만든다."""
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
    """YAML artifact를 안전하게 읽는다."""
    if not Path(path).exists():
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("improvement decision artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """프로젝트 root 기준 상대 경로를 만든다."""
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


@dataclass
class ImprovementDecision:
    """intervention에 대한 keep/dismiss 판단 기록."""

    schema_version: str
    decision_id: str
    created_at: str
    updated_at: str | None
    intervention_id: str
    cycle_id: str | None
    workset_name: str | None
    status: str
    verdict_at_decision: str | None
    title: str
    summary: str
    resolution: str | None
    source_intervention_ref: str | None
    source_cycle_ref: str | None
    source_evaluation_ref: str | None
    overlay_effects: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ImprovementDecisionStoreModel:
    """개선 decision 저장소 모델."""

    schema_version: str
    updated_at: str
    decisions: list[ImprovementDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["decisions"] = [decision.to_dict() for decision in self.decisions]
        return payload


@dataclass
class PersistentImprovementOverlay:
    """keep된 intervention만 합쳐 만든 장기 개선 overlay."""

    schema_version: str
    generated_at: str
    kept_intervention_ids: list[str]
    kept_cycle_ids: list[str]
    context_hint_bias: bool
    preferred_context_paths: list[str]
    preferred_test_paths: list[str]
    review_support_bias: float
    narrow_scope_bias: bool
    test_first_bias: bool
    preferred_team_ids: list[str]
    preferred_template_names: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class ImprovementDecisionStore:
    """개선 decision 저장소."""

    def load(self, path: Path) -> ImprovementDecisionStoreModel:
        """decisions.yaml을 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        decisions = [
            _decision_from_dict(item)
            for item in payload.get("decisions", [])
            if isinstance(item, dict)
        ]
        return ImprovementDecisionStoreModel(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _now()),
            decisions=decisions,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, path: Path, model: ImprovementDecisionStoreModel) -> Path:
        """decision store를 저장한다."""
        model.updated_at = _now()
        return _save_yaml(Path(path).resolve(), model.to_dict())

    def add(self, path: Path, decision: ImprovementDecision) -> Path:
        """새 decision을 append한다."""
        model = self.load(path)
        model.decisions.append(decision)
        return self.save(path, model)


class PersistentImprovementOverlayBuilder:
    """latest-decision-wins 규칙으로 persistent overlay를 만든다."""

    def build(self, project_root: Path) -> PersistentImprovementOverlay:
        """kept 상태인 intervention들의 overlay 효과를 합친다."""
        root = Path(project_root).resolve()
        model = ImprovementDecisionStore().load(default_decisions_path(root))
        latest = latest_decisions_by_intervention(model.decisions)
        kept = [decision for decision in latest.values() if decision.status == "kept"]
        warnings: list[str] = []
        errors: list[str] = []
        preferred_context_paths: list[str] = []
        preferred_test_paths: list[str] = []
        preferred_team_ids: list[str] = []
        preferred_template_names: list[str] = []
        review_support_bias = 0.0
        context_hint_bias = False
        narrow_scope_bias = False
        test_first_bias = False
        kept_intervention_ids: list[str] = []
        kept_cycle_ids: list[str] = []
        for decision in kept:
            effects = dict(decision.overlay_effects or {})
            kept_intervention_ids.append(decision.intervention_id)
            if decision.cycle_id:
                kept_cycle_ids.append(decision.cycle_id)
            context_hint_bias = context_hint_bias or bool(effects.get("context_hint_bias"))
            narrow_scope_bias = narrow_scope_bias or bool(effects.get("narrow_scope_bias"))
            test_first_bias = test_first_bias or bool(effects.get("test_first_bias"))
            review_support_bias += _float(effects.get("review_support_bias"))
            preferred_context_paths.extend([str(item) for item in effects.get("preferred_context_paths", []) if item])
            preferred_test_paths.extend([str(item) for item in effects.get("preferred_test_paths", []) if item])
            preferred_team_ids.extend([str(item) for item in effects.get("preferred_team_ids", []) if item])
            preferred_template_names.extend([str(item) for item in effects.get("preferred_template_names", []) if item])
            warnings.extend(decision.warnings)
            errors.extend(decision.errors)
        return PersistentImprovementOverlay(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            kept_intervention_ids=_dedupe(kept_intervention_ids),
            kept_cycle_ids=_dedupe(kept_cycle_ids),
            context_hint_bias=context_hint_bias,
            preferred_context_paths=_dedupe(preferred_context_paths),
            preferred_test_paths=_dedupe(preferred_test_paths),
            review_support_bias=min(MAX_REVIEW_SUPPORT_BIAS, round(review_support_bias, 4)),
            narrow_scope_bias=narrow_scope_bias,
            test_first_bias=test_first_bias,
            preferred_team_ids=_dedupe(preferred_team_ids),
            preferred_template_names=_dedupe(preferred_template_names),
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )


class PersistentImprovementOverlayStore:
    """persistent overlay 저장소."""

    def save(self, overlay: PersistentImprovementOverlay, path: Path) -> Path:
        """persistent overlay를 저장한다."""
        return _save_yaml(Path(path).resolve(), overlay.to_dict())

    def load(self, path: Path) -> PersistentImprovementOverlay:
        """persistent overlay를 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            return empty_persistent_overlay()
        return _persistent_overlay_from_dict(payload)


def default_decisions_path(project_root: Path) -> Path:
    """decision store 경로."""
    return default_improvement_dir(project_root) / "decisions.yaml"


def default_persistent_overlay_path(project_root: Path) -> Path:
    """persistent overlay 경로."""
    return default_improvement_dir(project_root) / "persistent_overlay.yaml"


def empty_persistent_overlay() -> PersistentImprovementOverlay:
    """비어 있는 persistent overlay."""
    return PersistentImprovementOverlay(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        kept_intervention_ids=[],
        kept_cycle_ids=[],
        context_hint_bias=False,
        preferred_context_paths=[],
        preferred_test_paths=[],
        review_support_bias=0.0,
        narrow_scope_bias=False,
        test_first_bias=False,
        preferred_team_ids=[],
        preferred_template_names=[],
        warnings=[],
        errors=[],
    )


def load_persistent_overlay(project_root: Path) -> PersistentImprovementOverlay | None:
    """kept intervention이 있으면 persistent overlay를 반환한다."""
    overlay = PersistentImprovementOverlayStore().load(default_persistent_overlay_path(project_root))
    return overlay if overlay.kept_intervention_ids else None


def keep_intervention(
    project_root: Path,
    intervention_ref: str,
    *,
    resolution: str | None = None,
    force: bool = False,
) -> tuple[ImprovementDecision, PersistentImprovementOverlay]:
    """intervention을 persistent overlay로 승격한다."""
    root = Path(project_root).resolve()
    intervention_path = resolve_intervention_path(root, intervention_ref)
    intervention = ImprovementInterventionStore().load(intervention_path)
    cycle, cycle_path = _cycle_for_intervention(root, intervention)
    verdict = cycle.verdict if cycle else None
    warnings: list[str] = []
    if verdict != "improved" and not force:
        raise KeepBlockedError(verdict, cycle.cycle_id if cycle else intervention.cycle_id)
    if verdict != "improved" and force:
        warnings.append(f"forced keep without improved verdict: {verdict or 'unknown'}")
    decision = _decision(
        root,
        intervention,
        intervention_path,
        status="kept",
        verdict=verdict,
        cycle=cycle,
        cycle_path=cycle_path,
        resolution=resolution,
        warnings=warnings,
    )
    ImprovementDecisionStore().add(default_decisions_path(root), decision)
    intervention.status = "kept"
    intervention.updated_at = _now()
    ImprovementInterventionStore().update(intervention_path, intervention)
    _clear_active_if_matches(root, intervention.intervention_id)
    overlay = rebuild_persistent_overlay(root)
    return decision, overlay


def dismiss_intervention(
    project_root: Path,
    intervention_ref: str,
    *,
    resolution: str | None = None,
) -> tuple[ImprovementDecision, PersistentImprovementOverlay]:
    """intervention을 기각하고 active overlay에서 제거한다."""
    root = Path(project_root).resolve()
    intervention_path = resolve_intervention_path(root, intervention_ref)
    intervention = ImprovementInterventionStore().load(intervention_path)
    cycle, cycle_path = _cycle_for_intervention(root, intervention)
    decision = _decision(
        root,
        intervention,
        intervention_path,
        status="dismissed",
        verdict=cycle.verdict if cycle else None,
        cycle=cycle,
        cycle_path=cycle_path,
        resolution=resolution,
        warnings=[],
    )
    ImprovementDecisionStore().add(default_decisions_path(root), decision)
    intervention.status = "dismissed"
    intervention.updated_at = _now()
    ImprovementInterventionStore().update(intervention_path, intervention)
    _clear_active_if_matches(root, intervention.intervention_id)
    overlay = rebuild_persistent_overlay(root)
    return decision, overlay


def rebuild_persistent_overlay(project_root: Path) -> PersistentImprovementOverlay:
    """decisions.yaml에서 persistent overlay를 재생성한다."""
    root = Path(project_root).resolve()
    overlay = PersistentImprovementOverlayBuilder().build(root)
    PersistentImprovementOverlayStore().save(overlay, default_persistent_overlay_path(root))
    return overlay


def latest_decisions_by_intervention(decisions: list[ImprovementDecision]) -> dict[str, ImprovementDecision]:
    """intervention별 latest decision을 반환한다."""
    latest: dict[str, ImprovementDecision] = {}
    for decision in decisions:
        latest[decision.intervention_id] = decision
    return latest


def kept_improvements_summary(project_root: Path) -> dict[str, Any]:
    """status/metrics/proof에서 사용할 kept improvement 요약."""
    root = Path(project_root).resolve()
    overlay = load_persistent_overlay(root)
    if overlay is None:
        return {}
    model = ImprovementDecisionStore().load(default_decisions_path(root))
    latest = latest_decisions_by_intervention(model.decisions)
    kept = [
        latest[item]
        for item in overlay.kept_intervention_ids
        if item in latest and latest[item].status == "kept"
    ]
    return {
        "kept_intervention_ids": list(overlay.kept_intervention_ids),
        "kept_cycle_ids": list(overlay.kept_cycle_ids),
        "kept_count": len(overlay.kept_intervention_ids),
        "kept_fix_kinds": _dedupe([_fix_kind_from_decision(item) for item in kept]),
        "preferred_context_paths": list(overlay.preferred_context_paths),
        "preferred_test_paths": list(overlay.preferred_test_paths),
        "preferred_team_ids": list(overlay.preferred_team_ids),
        "preferred_template_names": list(overlay.preferred_template_names),
        "review_support_bias": overlay.review_support_bias,
        "narrow_scope_bias": overlay.narrow_scope_bias,
        "test_first_bias": overlay.test_first_bias,
    }


def render_decision_kept(decision: ImprovementDecision, overlay: PersistentImprovementOverlay) -> str:
    """keep 결과를 사람이 읽기 쉽게 렌더링한다."""
    return "\n".join([
        "Improvement kept.",
        "",
        "Intervention:",
        f"  {decision.title}",
        "",
        "Meaning:",
        "  this fix is now part of the persistent local improvement overlay",
        "",
        "Persistent overlay:",
        f"  kept improvements: {len(overlay.kept_intervention_ids)}",
        "",
        "Saved:",
        "  .cambrian/improvement/decisions.yaml",
        "  .cambrian/improvement/persistent_overlay.yaml",
    ])


def render_decision_dismissed(decision: ImprovementDecision, overlay: PersistentImprovementOverlay) -> str:
    """dismiss 결과를 사람이 읽기 쉽게 렌더링한다."""
    return "\n".join([
        "Improvement dismissed.",
        "",
        "Intervention:",
        f"  {decision.title}",
        "",
        "Meaning:",
        "  this fix will not remain in the persistent local overlay",
        "",
        "Persistent overlay:",
        f"  kept improvements: {len(overlay.kept_intervention_ids)}",
    ])


def render_decisions(decisions: list[ImprovementDecision]) -> str:
    """decision 목록을 렌더링한다."""
    kept = [item for item in decisions if item.status == "kept"]
    dismissed = [item for item in decisions if item.status == "dismissed"]
    lines = ["Improvement Decisions", "==================================================", ""]
    lines.append("Kept:")
    lines.extend([f"  - {item.title}" for item in kept] or ["  none"])
    lines.extend(["", "Dismissed:"])
    lines.extend([f"  - {item.title}" for item in dismissed] or ["  none"])
    return "\n".join(lines)


def _decision(
    root: Path,
    intervention: ImprovementIntervention,
    intervention_path: Path,
    *,
    status: str,
    verdict: str | None,
    cycle: ImprovementCycle | None,
    cycle_path: Path | None,
    resolution: str | None,
    warnings: list[str],
) -> ImprovementDecision:
    title = intervention.fix_kind
    summary = (
        f"{intervention.fix_kind} {status} for {intervention.workset_name}; "
        f"verdict={verdict or 'unknown'}"
    )
    return ImprovementDecision(
        schema_version=SCHEMA_VERSION,
        decision_id=f"decision-{status}-{_slug(intervention.fix_kind)}-{_short_id()}",
        created_at=_now(),
        updated_at=None,
        intervention_id=intervention.intervention_id,
        cycle_id=cycle.cycle_id if cycle else intervention.cycle_id,
        workset_name=intervention.workset_name,
        status=status,
        verdict_at_decision=verdict,
        title=title,
        summary=summary,
        resolution=resolution,
        source_intervention_ref=_relative(intervention_path, root),
        source_cycle_ref=_relative(cycle_path, root) if cycle_path else intervention.source_cycle_ref,
        source_evaluation_ref=_relative(cycle_path, root) if cycle_path and verdict else None,
        overlay_effects=dict(intervention.overlay_effects or {}),
        warnings=_dedupe(warnings),
        errors=[],
    )


def _cycle_for_intervention(root: Path, intervention: ImprovementIntervention) -> tuple[ImprovementCycle | None, Path | None]:
    cycle_paths: list[Path] = []
    if intervention.source_cycle_ref:
        ref_path = Path(intervention.source_cycle_ref)
        cycle_paths.append(ref_path if ref_path.is_absolute() else root / ref_path)
    if intervention.cycle_id:
        try:
            cycle_paths.append(resolve_cycle_path(root, intervention.cycle_id))
        except FileNotFoundError:
            pass
    for path in cycle_paths:
        if path.exists():
            return ImprovementCycleStore().load(path), path.resolve()
    return None, None


def _clear_active_if_matches(root: Path, intervention_id: str) -> None:
    overlay_store = ImprovementOverlayStore()
    overlay_path = default_overlay_path(root)
    active = overlay_store.load(overlay_path)
    if active.active_intervention_id == intervention_id:
        overlay_store.save(empty_overlay(), overlay_path)


def _fix_kind_from_decision(decision: ImprovementDecision) -> str:
    if decision.title:
        return decision.title
    source = str(decision.summary or "")
    return source.split()[0] if source else decision.intervention_id


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _decision_from_dict(payload: dict[str, Any]) -> ImprovementDecision:
    return ImprovementDecision(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        decision_id=str(payload.get("decision_id") or f"decision-unknown-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        intervention_id=str(payload.get("intervention_id") or ""),
        cycle_id=str(payload.get("cycle_id")) if payload.get("cycle_id") is not None else None,
        workset_name=str(payload.get("workset_name")) if payload.get("workset_name") is not None else None,
        status=str(payload.get("status") or "dismissed"),
        verdict_at_decision=str(payload.get("verdict_at_decision")) if payload.get("verdict_at_decision") is not None else None,
        title=str(payload.get("title") or ""),
        summary=str(payload.get("summary") or ""),
        resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
        source_intervention_ref=str(payload.get("source_intervention_ref")) if payload.get("source_intervention_ref") is not None else None,
        source_cycle_ref=str(payload.get("source_cycle_ref")) if payload.get("source_cycle_ref") is not None else None,
        source_evaluation_ref=str(payload.get("source_evaluation_ref")) if payload.get("source_evaluation_ref") is not None else None,
        overlay_effects=dict(payload.get("overlay_effects", {})) if isinstance(payload.get("overlay_effects"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _persistent_overlay_from_dict(payload: dict[str, Any]) -> PersistentImprovementOverlay:
    return PersistentImprovementOverlay(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        generated_at=str(payload.get("generated_at") or _now()),
        kept_intervention_ids=[str(item) for item in payload.get("kept_intervention_ids", []) if item],
        kept_cycle_ids=[str(item) for item in payload.get("kept_cycle_ids", []) if item],
        context_hint_bias=bool(payload.get("context_hint_bias")),
        preferred_context_paths=[str(item) for item in payload.get("preferred_context_paths", []) if item],
        preferred_test_paths=[str(item) for item in payload.get("preferred_test_paths", []) if item],
        review_support_bias=_float(payload.get("review_support_bias")),
        narrow_scope_bias=bool(payload.get("narrow_scope_bias")),
        test_first_bias=bool(payload.get("test_first_bias")),
        preferred_team_ids=[str(item) for item in payload.get("preferred_team_ids", []) if item],
        preferred_template_names=[str(item) for item in payload.get("preferred_template_names", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
