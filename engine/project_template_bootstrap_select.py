"""init/start bootstrap에서 템플릿 추천 선택 provenance를 관리한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_recommend import (
    TemplateRecommendationBuilder,
    TemplateRecommendationReport,
    TemplateRecommendationStore,
    default_template_recommendation_path,
)
from engine.project_template_bootstrap_compare import (
    BootstrapTemplateCompareBuilder,
    BootstrapTemplateCompareStore,
    default_template_bootstrap_compare_path,
)
from engine.project_template_library_policy import (
    build_and_save_template_library_policy_overlay,
    template_library_policy_context,
)
from engine.project_templates import HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.1.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    """선택 artifact를 원자적으로 저장한다."""
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


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def default_template_bootstrap_choice_path(project_root: Path) -> Path:
    """bootstrap template 선택 기록 기본 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "bootstrap_choice.yaml"


@dataclass
class BootstrapTemplateChoice:
    """init/start bootstrap에서 사용자가 고른 템플릿 선택 기록."""

    schema_version: str
    created_at: str
    project_name: str | None
    workspace: str
    recommended_template_name: str | None
    available_templates: list[str]
    considered_templates: list[str]
    selected_template_name: str | None
    selection_mode: str
    source_recommendation_ref: str | None
    source_compare_ref: str | None
    template_library_policy_context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemplateBootstrapChoiceStore:
    """bootstrap template 선택 기록 저장소."""

    def save(self, choice: BootstrapTemplateChoice, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), choice.to_dict())

    def load(self, path: Path) -> BootstrapTemplateChoice:
        payload = _load_yaml(Path(path).resolve())
        return BootstrapTemplateChoice(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            created_at=str(payload.get("created_at", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            workspace=str(payload.get("workspace", "")),
            recommended_template_name=(
                str(payload.get("recommended_template_name"))
                if payload.get("recommended_template_name") is not None
                else None
            ),
            available_templates=[str(value) for value in payload.get("available_templates", []) if value],
            considered_templates=[
                str(value)
                for value in payload.get("considered_templates", payload.get("available_templates", []))
                if value
            ],
            selected_template_name=(
                str(payload.get("selected_template_name"))
                if payload.get("selected_template_name") is not None
                else None
            ),
            selection_mode=str(payload.get("selection_mode", "skipped")),
            source_recommendation_ref=(
                str(payload.get("source_recommendation_ref"))
                if payload.get("source_recommendation_ref") is not None
                else None
            ),
            source_compare_ref=(
                str(payload.get("source_compare_ref"))
                if payload.get("source_compare_ref") is not None
                else None
            ),
            template_library_policy_context=dict(
                payload.get("template_library_policy_context", {})
                if isinstance(payload.get("template_library_policy_context"), dict)
                else {}
            ),
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


class TemplateBootstrapSelector:
    """템플릿 추천을 bootstrap 선택으로 변환한다."""

    def recommend_for_bootstrap(self, project_root: Path) -> dict[str, Any]:
        """Task 89 추천기를 재사용해 bootstrap 후보를 만든다."""
        root = Path(project_root).resolve()
        report = TemplateRecommendationBuilder().build(root)
        saved_path = TemplateRecommendationStore().save(report, default_template_recommendation_path(root))
        compare = BootstrapTemplateCompareBuilder().build(root, recommendation_report=report)
        compare_path = BootstrapTemplateCompareStore().save(compare, default_template_bootstrap_compare_path(root))
        policy_overlay, policy_path = build_and_save_template_library_policy_overlay(root)
        policy_context = template_library_policy_context(root, policy_overlay, policy_path)
        return {
            "report": report,
            "saved_path": saved_path,
            "compare": compare,
            "compare_path": compare_path,
            "policy_overlay": policy_overlay,
            "policy_path": policy_path,
            "template_library_policy_context": policy_context,
            "best_template_name": report.best_template_name,
            "available_templates": [candidate.name for candidate in report.candidates],
            "considered_templates": [candidate.template_name for candidate in compare.candidates],
            "warnings": _dedupe(list(report.warnings) + list(compare.warnings)),
            "errors": _dedupe(list(report.errors) + list(compare.errors)),
        }

    def choose(
        self,
        project_root: Path,
        recommended_template_name: str | None,
        selected_template_name: str | None,
        use_recommended: bool,
        skip_template: bool,
        *,
        available_templates: list[str] | None = None,
        considered_templates: list[str] | None = None,
        source_recommendation_ref: str | None = None,
        source_compare_ref: str | None = None,
        template_library_policy_context: dict[str, Any] | None = None,
        selection_mode: str | None = None,
    ) -> BootstrapTemplateChoice:
        """명시 선택/추천 사용/건너뛰기를 하나의 provenance로 정규화한다."""
        root = Path(project_root).resolve()
        available = _dedupe(available_templates or self._available_template_names(root))
        default_considered = ([recommended_template_name] if recommended_template_name else []) + available[:4]
        considered = _dedupe(considered_templates or default_considered)
        warnings: list[str] = []
        errors: list[str] = []
        selected = str(selected_template_name or "").strip() or None
        mode = selection_mode

        if skip_template:
            selected = None
            mode = "skipped"
        elif selected:
            mode = mode or "explicit"
        elif use_recommended:
            if recommended_template_name:
                selected = recommended_template_name
                mode = "recommended"
            else:
                mode = "skipped"
                warnings.append("no recommended template was available, so template bootstrap was skipped")
        else:
            selected = None
            mode = "skipped"

        if selected and selected not in available:
            errors.append(f"selected template not found: {selected}")
        if selected and selected not in considered:
            considered.append(selected)

        return BootstrapTemplateChoice(
            schema_version=SCHEMA_VERSION,
            created_at=_now(),
            project_name=root.name,
            workspace=str(root),
            recommended_template_name=recommended_template_name,
            available_templates=available,
            considered_templates=considered,
            selected_template_name=selected,
            selection_mode=mode or "skipped",
            source_recommendation_ref=source_recommendation_ref,
            source_compare_ref=source_compare_ref,
            template_library_policy_context=dict(template_library_policy_context or {}),
            warnings=warnings,
            errors=errors,
        )

    @staticmethod
    def _available_template_names(project_root: Path) -> list[str]:
        store = HarnessTemplateStore()
        model = store.load(default_templates_path(Path(project_root).resolve()))
        return [template.name for template in model.templates]


def save_template_bootstrap_choice(project_root: Path, choice: BootstrapTemplateChoice) -> Path:
    """bootstrap choice artifact를 기본 위치에 저장한다."""
    root = Path(project_root).resolve()
    saved = TemplateBootstrapChoiceStore().save(choice, default_template_bootstrap_choice_path(root))
    try:
        from engine.project_template_canary_ledger import record_canary_bootstrap_choice

        record_canary_bootstrap_choice(root, choice, source_ref=_relative_to_project(saved, root))
    except Exception as exc:
        logger.warning("canary bootstrap choice ledger event failed: %s", exc)
    return saved


def load_template_bootstrap_choice(project_root: Path) -> dict[str, Any]:
    """저장된 bootstrap choice를 dict로 가볍게 읽는다."""
    path = default_template_bootstrap_choice_path(project_root)
    if not path.exists():
        return {}
    try:
        return TemplateBootstrapChoiceStore().load(path).to_dict()
    except Exception as exc:
        logger.warning("template bootstrap choice load failed: %s", exc)
        return {"warnings": [f"template bootstrap choice load failed: {exc}"]}


def render_bootstrap_recommendation_prompt(report: TemplateRecommendationReport) -> str:
    """wizard에서 보여줄 추천 선택 안내를 렌더링한다."""
    lines = [
        "Cambrian found a likely harness template for this project.",
        "",
        "Recommended:",
    ]
    best = next((candidate for candidate in report.candidates if candidate.name == report.best_template_name), None)
    best_name = report.best_template_name or "none"
    if best and _is_canary_candidate(best):
        best_name = f"{best_name} (canary)"
    lines.append(f"  {best_name}")
    if best and best.reasons:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {reason}" for reason in best.reasons[:4]])
    alternatives = [
        (
            f"{candidate.name} (canary)"
            if _is_canary_candidate(candidate)
            else candidate.name
        )
        for candidate in report.candidates
        if candidate.name != report.best_template_name
    ]
    if alternatives:
        lines.extend(["", "Alternatives:"])
        lines.extend([f"  - {name}" for name in alternatives[:3]])
    lines.extend([
        "",
        "Choose:",
        "  1. Use recommended template",
        "  2. Choose another template from the shortlist",
        "  3. Show short comparison",
        "  4. Skip template for now",
    ])
    return "\n".join(lines)


def _is_canary_candidate(candidate: Any) -> bool:
    """bootstrap shortlist에서 canary 라벨이 필요한 후보인지 확인한다."""
    lane_fit = candidate.project_fit.get("lane_playbook") if hasattr(candidate, "project_fit") else None
    return isinstance(lane_fit, dict) and lane_fit.get("standing") == "canary"


def render_bootstrap_choice_result(choice: BootstrapTemplateChoice | dict[str, Any]) -> str:
    """bootstrap 선택 결과를 사람이 읽기 좋게 렌더링한다."""
    payload = choice.to_dict() if isinstance(choice, BootstrapTemplateChoice) else choice
    mode = str(payload.get("selection_mode") or "skipped")
    selected = payload.get("selected_template_name")
    if mode == "skipped" or not selected:
        lines = [
            "Template bootstrap:",
            "  skipped",
        ]
    else:
        label = {
            "recommended": "recommended template",
            "explicit": "explicit template",
            "manual_choice": "manual choice",
        }.get(mode, mode)
        lines = [
            "Template bootstrap:",
            f"  {selected}",
            f"  selected via {label}",
        ]
    warnings = [str(value) for value in payload.get("warnings", []) if value]
    policy_context = payload.get("template_library_policy_context")
    if isinstance(policy_context, dict) and policy_context.get("enabled"):
        hints = [str(value) for value in policy_context.get("applied_hints", []) if value]
        if hints:
            lines.extend(["", "Template library policy:"])
            lines.extend([f"  - {hint}" for hint in hints[:4]])
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in warnings])
    return "\n".join(lines)
