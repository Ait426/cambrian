"""개선 cycle의 가설을 되돌릴 수 있는 intervention overlay로 바꾸는 모듈."""

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

from engine.project_improvement_loop import (
    ImprovementCycleStore,
    default_improvement_dir,
    resolve_cycle_path,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
SUPPORTED_FIX_KINDS = {
    "strengthen_context_hints",
    "improve_validation_support",
    "increase_review_support",
    "narrow_scope_defaults",
    "strengthen_test_practice",
    "prefer_strongest_team",
    "prefer_strongest_template",
}


class ActiveInterventionError(RuntimeError):
    """이미 active intervention이 있을 때 발생한다."""

    def __init__(self, intervention_id: str, intervention_ref: str | None = None) -> None:
        super().__init__(f"active improvement intervention already exists: {intervention_id}")
        self.intervention_id = intervention_id
        self.intervention_ref = intervention_ref


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명용 timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 id."""
    return secrets.token_hex(2)


def _slug(value: str, fallback: str = "item") -> str:
    """파일명에 안전한 slug."""
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
        logger.warning("improvement intervention artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """project root 기준 상대 경로."""
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


@dataclass
class ImprovementIntervention:
    """개선 실험 intervention pack."""

    schema_version: str
    intervention_id: str
    created_at: str
    updated_at: str | None
    cycle_id: str
    workset_name: str
    bottleneck_kind: str
    fix_kind: str
    hypothesis: str
    status: str
    overlay_effects: dict[str, Any]
    source_cycle_ref: str | None
    source_bottleneck_ref: str | None
    source_compare_ref: str | None
    source_proof_ref: str | None
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ImprovementOverlay:
    """현재 적용 중인 안전 intervention overlay."""

    schema_version: str
    generated_at: str
    active_intervention_id: str | None
    active_cycle_id: str | None
    context_hint_bias: bool
    preferred_context_paths: list[str]
    preferred_test_paths: list[str]
    review_support_bias: float
    narrow_scope_bias: bool
    test_first_bias: bool
    preferred_team_ids: list[str]
    preferred_template_names: list[str]
    source_intervention_ref: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


class ImprovementInterventionBuilder:
    """cycle에서 intervention pack을 만든다."""

    def from_cycle(
        self,
        project_root: Path,
        cycle_path: Path,
        *,
        teams: list[str] | None = None,
        templates: list[str] | None = None,
        context_paths: list[str] | None = None,
        test_paths: list[str] | None = None,
    ) -> ImprovementIntervention:
        """cycle의 fix kind를 safe overlay effect로 변환한다."""
        root = Path(project_root).resolve()
        path = Path(cycle_path).resolve()
        cycle = ImprovementCycleStore().load(path)
        fix_kind = cycle.selected_fix_kind or _fix_kind_for_bottleneck(cycle.selected_bottleneck_kind)
        warnings: list[str] = []
        if fix_kind not in SUPPORTED_FIX_KINDS:
            warnings.append(f"unsupported fix kind was converted to narrow_scope_defaults: {fix_kind}")
            fix_kind = "narrow_scope_defaults"
        overlay_effects, effect_warnings = _effects_for_fix(
            fix_kind,
            context_paths=list(context_paths or []),
            test_paths=list(test_paths or []),
            teams=list(teams or []),
            templates=list(templates or []),
        )
        warnings.extend(effect_warnings)
        evidence = dict(cycle.evidence_refs or {})
        return ImprovementIntervention(
            schema_version=SCHEMA_VERSION,
            intervention_id=f"intervention-{_slug(cycle.workset_name)}-{_short_id()}",
            created_at=_now(),
            updated_at=None,
            cycle_id=cycle.cycle_id,
            workset_name=cycle.workset_name,
            bottleneck_kind=cycle.selected_bottleneck_kind or "unknown",
            fix_kind=fix_kind,
            hypothesis=cycle.hypothesis,
            status="drafted",
            overlay_effects=overlay_effects,
            source_cycle_ref=_relative(path, root),
            source_bottleneck_ref=evidence.get("before_bottleneck_ref"),
            source_compare_ref=evidence.get("before_compare_ref"),
            source_proof_ref=evidence.get("before_proof_ref"),
            summary=_summary_for_effects(fix_kind, overlay_effects),
            warnings=_dedupe(warnings),
            errors=[],
        )


class ImprovementInterventionStore:
    """intervention artifact 저장소."""

    def save(self, intervention: ImprovementIntervention, path: Path) -> Path:
        """intervention과 latest pointer를 저장한다."""
        saved = _save_yaml(Path(path).resolve(), intervention.to_dict())
        _save_yaml(saved.parent.parent / "latest_intervention.yaml", intervention.to_dict())
        return saved

    def update(self, intervention_path: Path, intervention: ImprovementIntervention) -> Path:
        """intervention을 갱신한다."""
        return self.save(intervention, intervention_path)

    def load(self, path: Path) -> ImprovementIntervention:
        """intervention artifact를 읽는다."""
        return _intervention_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, interventions_dir: Path) -> list[ImprovementIntervention]:
        """최근 intervention 목록을 읽는다."""
        interventions: list[ImprovementIntervention] = []
        for path in sorted(Path(interventions_dir).glob("intervention_*.yaml")):
            payload = _load_yaml(path)
            if payload:
                interventions.append(_intervention_from_dict(payload))
        interventions.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
        return interventions


class ImprovementOverlayStore:
    """active overlay 저장소."""

    def save(self, overlay: ImprovementOverlay, path: Path) -> Path:
        """overlay를 저장한다."""
        return _save_yaml(Path(path).resolve(), overlay.to_dict())

    def load(self, path: Path) -> ImprovementOverlay:
        """overlay를 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            return empty_overlay()
        return _overlay_from_dict(payload)


def default_interventions_dir(project_root: Path) -> Path:
    """intervention 저장 디렉터리."""
    return default_improvement_dir(project_root) / "interventions"


def default_intervention_path(project_root: Path, intervention: ImprovementIntervention) -> Path:
    """intervention 기본 저장 경로."""
    return default_interventions_dir(project_root) / f"intervention_{_stamp()}_{_short_id()}.yaml"


def default_overlay_path(project_root: Path) -> Path:
    """active overlay 경로."""
    return default_improvement_dir(project_root) / "overlay.yaml"


def resolve_intervention_path(project_root: Path, intervention_ref: str) -> Path:
    """intervention id 또는 path를 실제 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(intervention_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in default_interventions_dir(root).glob("intervention_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == intervention_ref or str(payload.get("intervention_id") or "") == intervention_ref:
            return path.resolve()
    raise FileNotFoundError(f"improvement intervention not found: {intervention_ref}")


def empty_overlay() -> ImprovementOverlay:
    """비활성 overlay 객체."""
    return ImprovementOverlay(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        active_intervention_id=None,
        active_cycle_id=None,
        context_hint_bias=False,
        preferred_context_paths=[],
        preferred_test_paths=[],
        review_support_bias=0.0,
        narrow_scope_bias=False,
        test_first_bias=False,
        preferred_team_ids=[],
        preferred_template_names=[],
        source_intervention_ref=None,
        warnings=[],
        errors=[],
    )


def apply_intervention(project_root: Path, intervention_path: Path) -> tuple[ImprovementIntervention, ImprovementOverlay]:
    """intervention을 active overlay로 적용한다."""
    root = Path(project_root).resolve()
    overlay_path = default_overlay_path(root)
    existing = ImprovementOverlayStore().load(overlay_path)
    if existing.active_intervention_id:
        raise ActiveInterventionError(existing.active_intervention_id, existing.source_intervention_ref)
    path = Path(intervention_path).resolve()
    intervention = ImprovementInterventionStore().load(path)
    overlay = overlay_from_intervention(intervention, _relative(path, root))
    ImprovementOverlayStore().save(overlay, overlay_path)
    intervention.status = "applied"
    intervention.updated_at = _now()
    ImprovementInterventionStore().update(path, intervention)
    return intervention, overlay


def revert_intervention(project_root: Path, intervention_path: Path) -> tuple[ImprovementIntervention, ImprovementOverlay]:
    """active intervention을 되돌린다."""
    root = Path(project_root).resolve()
    path = Path(intervention_path).resolve()
    intervention = ImprovementInterventionStore().load(path)
    overlay = ImprovementOverlayStore().load(default_overlay_path(root))
    if overlay.active_intervention_id and overlay.active_intervention_id != intervention.intervention_id:
        raise ActiveInterventionError(overlay.active_intervention_id, overlay.source_intervention_ref)
    cleared = empty_overlay()
    ImprovementOverlayStore().save(cleared, default_overlay_path(root))
    intervention.status = "reverted"
    intervention.updated_at = _now()
    ImprovementInterventionStore().update(path, intervention)
    return intervention, cleared


def overlay_from_intervention(intervention: ImprovementIntervention, source_ref: str | None) -> ImprovementOverlay:
    """intervention의 overlay effects를 active overlay로 변환한다."""
    effects = dict(intervention.overlay_effects or {})
    return ImprovementOverlay(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        active_intervention_id=intervention.intervention_id,
        active_cycle_id=intervention.cycle_id,
        context_hint_bias=bool(effects.get("context_hint_bias")),
        preferred_context_paths=[str(item) for item in effects.get("preferred_context_paths", []) if item],
        preferred_test_paths=[str(item) for item in effects.get("preferred_test_paths", []) if item],
        review_support_bias=float(effects.get("review_support_bias") or 0.0),
        narrow_scope_bias=bool(effects.get("narrow_scope_bias")),
        test_first_bias=bool(effects.get("test_first_bias")),
        preferred_team_ids=[str(item) for item in effects.get("preferred_team_ids", []) if item],
        preferred_template_names=[str(item) for item in effects.get("preferred_template_names", []) if item],
        source_intervention_ref=source_ref,
        warnings=list(intervention.warnings),
        errors=list(intervention.errors),
    )


def load_active_overlay(project_root: Path) -> ImprovementOverlay | None:
    """active overlay가 있으면 반환한다."""
    overlay = ImprovementOverlayStore().load(default_overlay_path(project_root))
    return overlay if overlay.active_intervention_id else None


def active_intervention_summary(project_root: Path) -> dict[str, Any]:
    """status/do/metrics에서 쓸 active intervention 요약."""
    overlay = load_active_overlay(project_root)
    if overlay is None:
        return {}
    return {
        "active_intervention_id": overlay.active_intervention_id,
        "active_cycle_id": overlay.active_cycle_id,
        "source_intervention_ref": overlay.source_intervention_ref,
        "preferred_context_paths": list(overlay.preferred_context_paths),
        "preferred_test_paths": list(overlay.preferred_test_paths),
        "review_support_bias": overlay.review_support_bias,
        "narrow_scope_bias": overlay.narrow_scope_bias,
        "test_first_bias": overlay.test_first_bias,
        "preferred_team_ids": list(overlay.preferred_team_ids),
        "preferred_template_names": list(overlay.preferred_template_names),
        "kind": _active_intervention_kind(project_root, overlay),
    }


def apply_improvement_overlay_to_scan(scan_result: Any, project_root: Path) -> Any:
    """context scan 결과에 active intervention의 약한 path bias를 반영한다."""
    overlay = load_active_overlay(project_root)
    if overlay is None:
        return scan_result
    _apply_candidate_bias(
        scan_result.suggested_sources,
        overlay.preferred_context_paths,
        project_root,
        "source",
    )
    _apply_candidate_bias(
        scan_result.suggested_tests,
        overlay.preferred_test_paths,
        project_root,
        "test",
    )
    if overlay.context_hint_bias and (overlay.preferred_context_paths or overlay.preferred_test_paths):
        scan_result.warnings = _dedupe([
            *list(getattr(scan_result, "warnings", []) or []),
            "active improvement intervention is applying weak context/test path bias",
        ])
    scan_result.suggested_sources = sorted(scan_result.suggested_sources, key=lambda item: (-float(item.score), item.path))
    scan_result.suggested_tests = sorted(scan_result.suggested_tests, key=lambda item: (-float(item.score), item.path))
    if scan_result.status == "no_match" and (scan_result.suggested_sources or scan_result.suggested_tests):
        scan_result.status = "success"
    return scan_result


def intervention_metrics_context(project_root: Path) -> dict[str, Any]:
    """metrics_context에 남길 active intervention linkage."""
    summary = active_intervention_summary(project_root)
    if not summary:
        return {}
    return {
        "active_intervention_ref": summary.get("source_intervention_ref"),
        "active_intervention_id": summary.get("active_intervention_id"),
        "active_intervention_kind": summary.get("kind"),
    }


def render_intervention_pack_created(intervention: ImprovementIntervention, saved_ref: str) -> str:
    """intervention pack 생성 결과를 렌더링한다."""
    lines = [
        "Improvement intervention pack created.",
        "",
        "Cycle:",
        f"  {intervention.cycle_id}",
        "",
        "Fix:",
        f"  {intervention.fix_kind}",
        "",
        "Effect:",
    ]
    lines.extend([f"  - {item}" for item in _effect_lines(intervention.overlay_effects)])
    lines.extend(["", "Saved:", f"  {saved_ref}"])
    if intervention.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in intervention.warnings[:5]])
    return "\n".join(lines)


def render_intervention_applied(intervention: ImprovementIntervention, overlay: ImprovementOverlay) -> str:
    """intervention 적용 결과를 렌더링한다."""
    lines = [
        "Improvement intervention applied.",
        "",
        "Active intervention:",
        f"  {intervention.intervention_id}",
        "",
        "This will influence:",
    ]
    if overlay.context_hint_bias:
        lines.append("  - context scan hints")
    if overlay.review_support_bias:
        lines.append("  - review support preference")
    if overlay.narrow_scope_bias:
        lines.append("  - narrow scope guidance")
    if overlay.test_first_bias:
        lines.append("  - test-first guidance")
    if overlay.preferred_team_ids:
        lines.append("  - team recommendation preference")
    if overlay.preferred_template_names:
        lines.append("  - template recommendation preference")
    if len(lines) <= 6:
        lines.append("  - safe local overlay metadata")
    return "\n".join(lines)


def render_interventions(interventions: list[ImprovementIntervention]) -> str:
    """intervention 목록 렌더링."""
    lines = ["Improvement Interventions", "==================================================", "", "Recent:"]
    if not interventions:
        lines.append("  none")
        return "\n".join(lines)
    for index, item in enumerate(interventions[:20], start=1):
        lines.append(f"  {index}. {item.intervention_id} [{item.status}] {item.fix_kind}")
    return "\n".join(lines)


def _effects_for_fix(
    fix_kind: str,
    *,
    context_paths: list[str],
    test_paths: list[str],
    teams: list[str],
    templates: list[str],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    effects = {
        "context_hint_bias": False,
        "preferred_context_paths": _dedupe(context_paths),
        "preferred_test_paths": _dedupe(test_paths),
        "review_support_bias": 0.0,
        "narrow_scope_bias": False,
        "test_first_bias": False,
        "preferred_team_ids": _dedupe(teams),
        "preferred_template_names": _dedupe(templates),
    }
    if fix_kind == "strengthen_context_hints":
        effects["context_hint_bias"] = True
        if not effects["preferred_context_paths"]:
            effects["preferred_context_paths"] = ["src/auth.py"]
            warnings.append("default auth source path was used as a weak hint")
        if not effects["preferred_test_paths"]:
            effects["preferred_test_paths"] = ["tests/test_auth.py"]
            warnings.append("default auth test path was used as a weak hint")
    elif fix_kind == "improve_validation_support":
        effects["test_first_bias"] = True
        effects["review_support_bias"] = 0.08
    elif fix_kind == "increase_review_support":
        effects["review_support_bias"] = 0.1
    elif fix_kind == "narrow_scope_defaults":
        effects["narrow_scope_bias"] = True
    elif fix_kind == "strengthen_test_practice":
        effects["test_first_bias"] = True
    elif fix_kind == "prefer_strongest_team":
        if not effects["preferred_team_ids"]:
            effects["preferred_team_ids"] = ["auth-bug-team"]
            warnings.append("default strongest team hint was used")
    elif fix_kind == "prefer_strongest_template":
        if not effects["preferred_template_names"]:
            effects["preferred_template_names"] = ["auth-bug-template"]
            warnings.append("default strongest template hint was used")
    return effects, warnings


def _fix_kind_for_bottleneck(kind: str | None) -> str:
    mapping = {
        "ambiguous_context_selection": "strengthen_context_hints",
        "no_safe_context_candidate": "strengthen_context_hints",
        "missing_patch_candidate": "improve_validation_support",
        "validation_failure_cluster": "improve_validation_support",
        "review_support_gap": "increase_review_support",
        "narrow_scope_gap": "narrow_scope_defaults",
        "weak_team_fit": "prefer_strongest_team",
        "weak_template_fit": "prefer_strongest_template",
    }
    return mapping.get(str(kind or ""), "narrow_scope_defaults")


def _summary_for_effects(fix_kind: str, effects: dict[str, Any]) -> str:
    effect_text = ", ".join(_effect_lines(effects)) or "safe overlay metadata only"
    return f"{fix_kind}: {effect_text}"


def _effect_lines(effects: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if effects.get("context_hint_bias"):
        lines.append("enable context hint bias")
    if effects.get("preferred_context_paths"):
        lines.append(f"prefer source paths: {', '.join(effects.get('preferred_context_paths', [])[:3])}")
    if effects.get("preferred_test_paths"):
        lines.append(f"prefer test paths: {', '.join(effects.get('preferred_test_paths', [])[:3])}")
    if effects.get("review_support_bias"):
        lines.append("increase review support bias slightly")
    if effects.get("narrow_scope_bias"):
        lines.append("prefer narrow-scope guidance")
    if effects.get("test_first_bias"):
        lines.append("prefer test-first guidance")
    if effects.get("preferred_team_ids"):
        lines.append(f"prefer teams: {', '.join(effects.get('preferred_team_ids', [])[:3])}")
    if effects.get("preferred_template_names"):
        lines.append(f"prefer templates: {', '.join(effects.get('preferred_template_names', [])[:3])}")
    return lines


def _apply_candidate_bias(candidates: list[Any], preferred_paths: list[str], project_root: Path, kind: str) -> None:
    preferred = _dedupe(preferred_paths)
    existing = {str(getattr(item, "path", "")): item for item in candidates}
    for path in preferred:
        if path in existing:
            candidate = existing[path]
            candidate.score = min(1.0, round(float(candidate.score) + 0.08, 2))
            candidate.reasons = _dedupe([
                *list(candidate.reasons),
                "active improvement intervention prefers this file/test",
            ])
            continue
        absolute = project_root / path
        if absolute.exists():
            from engine.project_context import ContextCandidate

            candidates.append(
                ContextCandidate(
                    path=path,
                    kind=kind,
                    score=0.12,
                    reasons=["active improvement intervention prefers this file/test"],
                    matched_terms=[],
                )
            )


def _active_intervention_kind(project_root: Path, overlay: ImprovementOverlay) -> str | None:
    if not overlay.source_intervention_ref:
        return None
    path = Path(overlay.source_intervention_ref)
    if not path.is_absolute():
        path = Path(project_root).resolve() / path
    payload = _load_yaml(path)
    return str(payload.get("fix_kind")) if payload.get("fix_kind") else None


def _intervention_from_dict(payload: dict[str, Any]) -> ImprovementIntervention:
    return ImprovementIntervention(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        intervention_id=str(payload.get("intervention_id") or f"intervention-unknown-{_short_id()}"),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        cycle_id=str(payload.get("cycle_id") or ""),
        workset_name=str(payload.get("workset_name") or "unknown"),
        bottleneck_kind=str(payload.get("bottleneck_kind") or "unknown"),
        fix_kind=str(payload.get("fix_kind") or "narrow_scope_defaults"),
        hypothesis=str(payload.get("hypothesis") or ""),
        status=str(payload.get("status") or "drafted"),
        overlay_effects=dict(payload.get("overlay_effects", {})) if isinstance(payload.get("overlay_effects"), dict) else {},
        source_cycle_ref=str(payload.get("source_cycle_ref")) if payload.get("source_cycle_ref") is not None else None,
        source_bottleneck_ref=str(payload.get("source_bottleneck_ref")) if payload.get("source_bottleneck_ref") is not None else None,
        source_compare_ref=str(payload.get("source_compare_ref")) if payload.get("source_compare_ref") is not None else None,
        source_proof_ref=str(payload.get("source_proof_ref")) if payload.get("source_proof_ref") is not None else None,
        summary=str(payload.get("summary") or ""),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _overlay_from_dict(payload: dict[str, Any]) -> ImprovementOverlay:
    return ImprovementOverlay(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        generated_at=str(payload.get("generated_at") or _now()),
        active_intervention_id=str(payload.get("active_intervention_id")) if payload.get("active_intervention_id") is not None else None,
        active_cycle_id=str(payload.get("active_cycle_id")) if payload.get("active_cycle_id") is not None else None,
        context_hint_bias=bool(payload.get("context_hint_bias")),
        preferred_context_paths=[str(item) for item in payload.get("preferred_context_paths", []) if item],
        preferred_test_paths=[str(item) for item in payload.get("preferred_test_paths", []) if item],
        review_support_bias=float(payload.get("review_support_bias") or 0.0),
        narrow_scope_bias=bool(payload.get("narrow_scope_bias")),
        test_first_bias=bool(payload.get("test_first_bias")),
        preferred_team_ids=[str(item) for item in payload.get("preferred_team_ids", []) if item],
        preferred_template_names=[str(item) for item in payload.get("preferred_template_names", []) if item],
        source_intervention_ref=str(payload.get("source_intervention_ref")) if payload.get("source_intervention_ref") is not None else None,
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _load_persistent_overlay(project_root: Path) -> Any | None:
    """keep된 persistent overlay를 지연 로드한다."""
    try:
        from engine.project_improvement_decisions import load_persistent_overlay

        return load_persistent_overlay(project_root)
    except Exception as exc:
        logger.warning("persistent improvement overlay load failed: %s", exc)
        return None


def _kept_improvements_summary(project_root: Path) -> dict[str, Any]:
    """keep된 improvement 요약을 지연 로드한다."""
    try:
        from engine.project_improvement_decisions import kept_improvements_summary

        return kept_improvements_summary(project_root)
    except Exception as exc:
        logger.warning("kept improvement summary load failed: %s", exc)
        return {}


def _apply_candidate_bias_reasoned(
    candidates: list[Any],
    preferred_paths: list[str],
    project_root: Path,
    kind: str,
    *,
    reason: str,
    boost: float,
    new_score: float,
) -> None:
    """선호 path를 후보에 약한 이유와 함께 반영한다."""
    preferred = _dedupe(preferred_paths)
    existing = {str(getattr(item, "path", "")): item for item in candidates}
    for path in preferred:
        if path in existing:
            candidate = existing[path]
            candidate.score = min(1.0, round(float(candidate.score) + boost, 2))
            candidate.reasons = _dedupe([*list(candidate.reasons), reason])
            continue
        absolute = Path(project_root) / path
        if absolute.exists():
            from engine.project_context import ContextCandidate

            candidates.append(
                ContextCandidate(
                    path=path,
                    kind=kind,
                    score=new_score,
                    reasons=[reason],
                    matched_terms=[],
                )
            )


def effective_intervention_preferences(project_root: Path) -> dict[str, Any]:
    """active overlay와 persistent overlay를 합친 추천용 선호 요약."""
    active = active_intervention_summary(project_root)
    kept = _kept_improvements_summary(project_root)
    return {
        "preferred_context_paths": _dedupe([
            *list(kept.get("preferred_context_paths", []) if kept else []),
            *list(active.get("preferred_context_paths", []) if active else []),
        ]),
        "preferred_test_paths": _dedupe([
            *list(kept.get("preferred_test_paths", []) if kept else []),
            *list(active.get("preferred_test_paths", []) if active else []),
        ]),
        "preferred_team_ids": _dedupe([
            *list(kept.get("preferred_team_ids", []) if kept else []),
            *list(active.get("preferred_team_ids", []) if active else []),
        ]),
        "preferred_template_names": _dedupe([
            *list(kept.get("preferred_template_names", []) if kept else []),
            *list(active.get("preferred_template_names", []) if active else []),
        ]),
        "has_active": bool(active),
        "has_kept": bool(kept),
    }


def apply_improvement_overlay_to_scan(scan_result: Any, project_root: Path) -> Any:
    """context scan 결과에 active/persistent improvement bias를 약하게 반영한다."""
    overlay = load_active_overlay(project_root)
    persistent = _load_persistent_overlay(project_root)
    if overlay is None and persistent is None:
        return scan_result
    if persistent is not None:
        _apply_candidate_bias_reasoned(
            scan_result.suggested_sources,
            persistent.preferred_context_paths,
            project_root,
            "source",
            reason="kept improvement prefers this file/test",
            boost=0.05,
            new_score=0.10,
        )
        _apply_candidate_bias_reasoned(
            scan_result.suggested_tests,
            persistent.preferred_test_paths,
            project_root,
            "test",
            reason="kept improvement prefers this file/test",
            boost=0.05,
            new_score=0.10,
        )
    if overlay is not None:
        _apply_candidate_bias_reasoned(
            scan_result.suggested_sources,
            overlay.preferred_context_paths,
            project_root,
            "source",
            reason="active improvement intervention prefers this file/test",
            boost=0.08,
            new_score=0.12,
        )
        _apply_candidate_bias_reasoned(
            scan_result.suggested_tests,
            overlay.preferred_test_paths,
            project_root,
            "test",
            reason="active improvement intervention prefers this file/test",
            boost=0.08,
            new_score=0.12,
        )
    if persistent is not None and persistent.context_hint_bias and (persistent.preferred_context_paths or persistent.preferred_test_paths):
        scan_result.warnings = _dedupe([
            *list(getattr(scan_result, "warnings", []) or []),
            "kept improvement is applying weak context/test path bias",
        ])
    if overlay is not None and overlay.context_hint_bias and (overlay.preferred_context_paths or overlay.preferred_test_paths):
        scan_result.warnings = _dedupe([
            *list(getattr(scan_result, "warnings", []) or []),
            "active improvement intervention is applying weak context/test path bias",
        ])
    scan_result.suggested_sources = sorted(scan_result.suggested_sources, key=lambda item: (-float(item.score), item.path))
    scan_result.suggested_tests = sorted(scan_result.suggested_tests, key=lambda item: (-float(item.score), item.path))
    if scan_result.status == "no_match" and (scan_result.suggested_sources or scan_result.suggested_tests):
        scan_result.status = "success"
    return scan_result


def intervention_metrics_context(project_root: Path) -> dict[str, Any]:
    """metrics_context에 active/persistent intervention linkage를 남긴다."""
    active = active_intervention_summary(project_root)
    kept = _kept_improvements_summary(project_root)
    payload: dict[str, Any] = {}
    if active:
        payload.update({
            "active_intervention_ref": active.get("source_intervention_ref"),
            "active_intervention_id": active.get("active_intervention_id"),
            "active_intervention_kind": active.get("kind"),
        })
    if kept:
        payload.update({
            "kept_intervention_ids": list(kept.get("kept_intervention_ids", []) or []),
            "kept_intervention_count": kept.get("kept_count"),
            "kept_improvement_kinds": list(kept.get("kept_fix_kinds", []) or []),
        })
    return payload
