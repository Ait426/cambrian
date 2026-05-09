"""bootstrap 단계에서 템플릿 후보 shortlist와 가벼운 비교를 만든다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_recommend import TemplateRecommendationBuilder, TemplateRecommendationReport
from engine.project_template_library_policy import (
    load_or_build_template_library_policy_overlay,
    template_library_policy_by_template,
)
from engine.project_templates import HarnessTemplate, HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    """비교 report를 원자적으로 저장한다."""
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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


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


def _slug(value: str | None) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def default_template_bootstrap_compare_path(project_root: Path) -> Path:
    """bootstrap shortlist 비교 report 기본 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "bootstrap_compare.yaml"


@dataclass
class BootstrapTemplateCandidate:
    """bootstrap 선택용 템플릿 후보 요약."""

    template_name: str
    score: float
    confidence: float
    recommendation: str
    reasons: list[str]
    short_summary: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BootstrapTemplateCompare:
    """추천 템플릿과 대안 후보의 가벼운 비교 report."""

    schema_version: str
    created_at: str
    project_name: str | None
    workspace: str
    recommended_template_name: str | None
    candidates: list[BootstrapTemplateCandidate]
    compare_summary: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "project_name": self.project_name,
            "workspace": self.workspace,
            "recommended_template_name": self.recommended_template_name,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "compare_summary": list(self.compare_summary),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class BootstrapTemplateCompareBuilder:
    """Task 89 추천 결과를 bootstrap shortlist 비교로 압축한다."""

    def build(
        self,
        project_root: Path,
        recommendation_report: TemplateRecommendationReport | None = None,
    ) -> BootstrapTemplateCompare:
        root = Path(project_root).resolve()
        report = recommendation_report or TemplateRecommendationBuilder().build(root)
        store = HarnessTemplateStore()
        model = store.load(default_templates_path(root))
        warnings = list(report.warnings)
        errors = list(report.errors)
        candidates: list[BootstrapTemplateCandidate] = []
        try:
            overlay = load_or_build_template_library_policy_overlay(root, save=True)
            policy_by_template = template_library_policy_by_template(overlay)
        except Exception as exc:
            warnings.append(f"template library policy unavailable for bootstrap compare: {exc}")
            overlay = None
            policy_by_template = {}
        scored_by_name = {scored.name: scored for scored in report.candidates}
        ordered_names: list[str] = []
        if report.best_template_name:
            ordered_names.append(report.best_template_name)
        if overlay is not None:
            for name in list(overlay.backup_templates) + list(overlay.watched_templates):
                if name in scored_by_name:
                    ordered_names.append(name)
        ordered_names.extend(scored.name for scored in report.candidates)
        ordered_names = _dedupe(ordered_names)[:4]

        for index, name in enumerate(ordered_names):
            scored = scored_by_name.get(name)
            if scored is None:
                continue
            try:
                template = store.find(model, scored.name)
            except KeyError:
                warnings.append(f"recommended template missing from store: {scored.name}")
                continue
            policy_decision = policy_by_template.get(_slug(template.name))
            reasons = list(scored.reasons)[:4]
            short_summary = _short_summary(template, scored.reasons)
            if policy_decision is not None:
                policy_text = _policy_short_summary(policy_decision.decision_kind)
                if policy_text:
                    short_summary.append(policy_text)
                    reasons.append(policy_text)
            recommendation = "recommended" if scored.name == report.best_template_name else "alternative"
            if index > 3:
                recommendation = "weak"
            candidates.append(
                BootstrapTemplateCandidate(
                    template_name=template.name,
                    score=float(scored.score),
                    confidence=float(scored.confidence),
                    recommendation=recommendation,
                    reasons=_dedupe(reasons)[:5],
                    short_summary=_dedupe(short_summary)[:6],
                )
            )

        compare_summary: list[str] = []
        for candidate in candidates:
            compare_summary.append(f"{candidate.template_name}:")
            for item in candidate.short_summary[:3]:
                compare_summary.append(f"- {item}")

        if not candidates:
            warnings.append("no template shortlist candidates found")
        return BootstrapTemplateCompare(
            schema_version=SCHEMA_VERSION,
            created_at=_now(),
            project_name=report.project_name or root.name,
            workspace=str(root),
            recommended_template_name=report.best_template_name,
            candidates=candidates,
            compare_summary=compare_summary,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )


class BootstrapTemplateCompareStore:
    """bootstrap compare report 저장소."""

    def save(self, report: BootstrapTemplateCompare, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), report.to_dict())

    def load(self, path: Path) -> BootstrapTemplateCompare:
        payload = _load_yaml(Path(path).resolve())
        return BootstrapTemplateCompare(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            created_at=str(payload.get("created_at", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            workspace=str(payload.get("workspace", "")),
            recommended_template_name=(
                str(payload.get("recommended_template_name"))
                if payload.get("recommended_template_name") is not None
                else None
            ),
            candidates=[
                BootstrapTemplateCandidate(
                    template_name=str(item.get("template_name", "")),
                    score=float(item.get("score", 0.0) or 0.0),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    recommendation=str(item.get("recommendation", "alternative")),
                    reasons=[str(value) for value in item.get("reasons", []) if value],
                    short_summary=[str(value) for value in item.get("short_summary", []) if value],
                )
                for item in payload.get("candidates", []) or []
                if isinstance(item, dict)
            ],
            compare_summary=[str(value) for value in payload.get("compare_summary", []) if value],
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


def render_bootstrap_template_compare(report: BootstrapTemplateCompare) -> str:
    """shortlist와 비교 요약을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Bootstrap Template Shortlist",
        "==================================================",
        "",
        "Recommended:",
        f"  {report.recommended_template_name or 'none'}",
    ]
    alternatives = [
        candidate.template_name
        for candidate in report.candidates
        if candidate.template_name != report.recommended_template_name
    ]
    if alternatives:
        lines.extend(["", "Alternatives:"])
        lines.extend([f"  {index}. {name}" for index, name in enumerate(alternatives[:3], start=1)])
    if report.candidates:
        lines.extend(["", "Compare summary:"])
        for candidate in report.candidates:
            lines.append(f"  {candidate.template_name}:")
            for item in candidate.short_summary[:4]:
                lines.append(f"    - {item}")
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings[:4]])
    return "\n".join(lines)


def _short_summary(template: HarnessTemplate, reasons: list[str]) -> list[str]:
    summary: list[str] = []
    use_cases = _as_list(template.project_defaults.get("primary_use_cases"))
    if use_cases:
        summary.append(f"focus: {', '.join(use_cases[:3])}")
    stack = _as_list(template.project_defaults.get("stack"))
    test_command = str(template.project_defaults.get("test_command") or "").strip()
    if stack or test_command:
        text = ", ".join(stack[:3])
        if test_command:
            text = f"{text} / tests: {test_command}" if text else f"tests: {test_command}"
        summary.append(text)
    active_team = str(
        template.team_defaults.get("active_team_name")
        or template.team_defaults.get("active_team_id")
        or ""
    ).strip()
    if active_team:
        summary.append(f"default team: {active_team}")
    policy_terms = _policy_terms(template.policy_defaults)
    if policy_terms:
        summary.append(f"policy: {', '.join(policy_terms[:4])}")
    if reasons:
        summary.append(reasons[0])
    safety = _safety_terms(template.safety_defaults)
    if safety:
        summary.append(f"safety: {', '.join(safety[:3])}")
    return _dedupe(summary)[:5]


def _policy_short_summary(kind: str) -> str:
    return {
        "promote": "library policy: promoted",
        "keep": "library policy: kept",
        "backup": "library policy: backup template",
        "watch": "library policy: watch",
        "retire": "library policy: retired",
    }.get(str(kind or "").strip(), "")


def _policy_terms(policy: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    if policy.get("test_first_practice"):
        terms.append("test-first")
    if policy.get("narrow_change_scope"):
        terms.append("narrow-scope")
    if policy.get("increase_review_support"):
        terms.append("review-support")
    terms.extend(_as_list(policy.get("promote_request_focus")))
    return _dedupe(terms)


def _safety_terms(safety: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    if safety.get("explicit_adoption_only") or safety.get("never_auto_adopt"):
        terms.append("explicit-adoption")
    if safety.get("require_tests_before_apply") or safety.get("require_tests_before_adoption"):
        terms.append("test-before-apply")
    if safety.get("preserve_source_artifacts"):
        terms.append("preserve-source")
    mutation = str(safety.get("source_mutation_policy") or "").strip()
    if mutation:
        terms.append(mutation)
    return _dedupe(terms)
