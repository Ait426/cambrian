"""템플릿 검토와 승인/기각 결정을 로컬 artifact로 관리한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_diff import (
    TemplateDiffBuilder,
    TemplateDiffReport,
    TemplateDiffStore,
    default_template_diff_path,
)
from engine.project_template_recommend import (
    TemplateRecommendationBuilder,
    TemplateRecommendationReport,
    TemplateRecommendationStore,
    default_template_recommendation_path,
)
from engine.project_templates import HarnessTemplateStore, default_current_template_path, default_templates_path, load_current_template

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    """파일명에 쓸 짧은 UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _atomic_write_text(path: Path, content: str) -> None:
    """YAML artifact를 안전하게 저장한다."""
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
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _slug(value: str) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def default_template_reviews_dir(project_root: Path) -> Path:
    """템플릿 review artifact 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "reviews"


def default_template_decisions_path(project_root: Path) -> Path:
    """템플릿 decision store 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "decisions.yaml"


@dataclass
class TemplateReview:
    """템플릿 승인 전 검토 artifact."""

    schema_version: str
    review_id: str
    created_at: str
    template_name: str
    project_name: str | None
    workspace: str
    source_recommendation_ref: str | None
    source_diff_ref: str | None
    summary: str
    fit_reasons: list[str]
    diff_highlights: list[str]
    warnings: list[str]
    next_actions: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateDecision:
    """템플릿 승인/기각 결정."""

    decision_id: str
    created_at: str
    updated_at: str | None
    status: str
    template_name: str
    title: str
    summary: str
    resolution: str | None
    source_review_ref: str | None
    source_diff_ref: str | None
    source_recommendation_ref: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateDecisionStoreModel:
    """템플릿 decision YAML 모델."""

    schema_version: str
    updated_at: str
    decisions: list[TemplateDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateReviewBuilder:
    """recommendation + diff 증거로 사람이 읽는 review를 만든다."""

    def build(self, project_root: Path, template_name: str) -> TemplateReview:
        root = Path(project_root).resolve()
        template_name = _require_template(root, template_name)
        warnings: list[str] = []
        errors: list[str] = []
        recommendation, recommendation_ref = _load_or_build_recommendation(root, warnings)
        diff, diff_ref = _load_or_build_diff(root, template_name, warnings)
        fit_reasons = _fit_reasons_for_template(recommendation, template_name)
        if not fit_reasons:
            warnings.append("no saved recommendation evidence for this template")
        diff_highlights = _diff_highlights(diff)
        if not diff_highlights:
            warnings.append("no diff highlights were available for this template")
        summary = f"Review {template_name} before accepting it as an operating template."
        return TemplateReview(
            schema_version=SCHEMA_VERSION,
            review_id=f"template-review-{_timestamp()}-{_slug(template_name)}",
            created_at=_now(),
            template_name=template_name,
            project_name=diff.project_name or recommendation.project_name,
            workspace=str(root),
            source_recommendation_ref=recommendation_ref,
            source_diff_ref=diff_ref,
            summary=summary,
            fit_reasons=fit_reasons[:6],
            diff_highlights=diff_highlights[:8],
            warnings=_dedupe(warnings),
            next_actions=[
                f"cambrian template accept {template_name}",
                f"cambrian template dismiss {template_name} --resolution \"not the right fit yet\"",
            ],
            errors=errors,
        )


class TemplateReviewStore:
    """템플릿 review artifact 저장소."""

    def save(self, review: TemplateReview, reviews_dir: Path) -> Path:
        target = Path(reviews_dir).resolve() / f"review_{_timestamp()}_{_slug(review.template_name)}.yaml"
        return _save_yaml(target, review.to_dict())

    def load(self, path: Path) -> TemplateReview:
        payload = _load_yaml(Path(path).resolve())
        return _review_from_dict(payload)

    def latest(self, project_root: Path, template_name: str) -> tuple[TemplateReview | None, Path | None]:
        reviews_dir = default_template_reviews_dir(project_root)
        if not reviews_dir.exists():
            return None, None
        slug = _slug(template_name)
        candidates = sorted(reviews_dir.glob(f"review_*_{slug}.yaml"))
        if not candidates:
            return None, None
        path = candidates[-1]
        return self.load(path), path


class TemplateDecisionStore:
    """템플릿 decision store."""

    def load(self, path: Path) -> TemplateDecisionStoreModel:
        target = Path(path).resolve()
        if not target.exists():
            return TemplateDecisionStoreModel(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                decisions=[],
            )
        payload = _load_yaml(target)
        decisions = [
            _decision_from_dict(item)
            for item in payload.get("decisions", []) or []
            if isinstance(item, dict)
        ]
        return TemplateDecisionStoreModel(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            decisions=decisions,
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )

    def save(self, path: Path, model: TemplateDecisionStoreModel) -> Path:
        model.updated_at = _now()
        return _save_yaml(Path(path).resolve(), model.to_dict())

    def add(self, path: Path, decision: TemplateDecision) -> Path:
        model = self.load(path)
        model.decisions.append(decision)
        return self.save(path, model)


def build_template_decision(
    project_root: Path,
    template_name: str,
    *,
    status: str,
    resolution: str | None = None,
) -> TemplateDecision:
    """템플릿 accept/dismiss decision을 만든다. apply는 수행하지 않는다."""
    if status not in {"accepted", "dismissed"}:
        raise ValueError(f"unsupported template decision status: {status}")
    root = Path(project_root).resolve()
    template_name = _require_template(root, template_name)
    warnings: list[str] = []
    review, review_path = TemplateReviewStore().latest(root, template_name)
    source_review_ref = _relative_to_project(review_path, root) if review_path else None
    source_diff_ref = review.source_diff_ref if review else None
    source_recommendation_ref = review.source_recommendation_ref if review else None
    if not review:
        warnings.append("accepted/dismissed without a saved template review")
        diff_path = default_template_diff_path(root)
        rec_path = default_template_recommendation_path(root)
        source_diff_ref = _relative_to_project(diff_path, root) if diff_path.exists() else None
        source_recommendation_ref = _relative_to_project(rec_path, root) if rec_path.exists() else None
        if source_diff_ref is None and source_recommendation_ref is None:
            warnings.append("no saved recommendation or diff evidence was found")
    title = f"{status} {template_name}"
    summary = (
        f"{template_name} is approved for later template apply."
        if status == "accepted"
        else f"{template_name} was dismissed for this project."
    )
    return TemplateDecision(
        decision_id=f"template-decision-{_timestamp()}-{_slug(template_name)}",
        created_at=_now(),
        updated_at=None,
        status=status,
        template_name=template_name,
        title=title,
        summary=summary,
        resolution=resolution,
        source_review_ref=source_review_ref,
        source_diff_ref=source_diff_ref,
        source_recommendation_ref=source_recommendation_ref,
        warnings=_dedupe(warnings),
        errors=[],
    )


def load_template_decision_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """status/show에서 쓰는 최신 템플릿 decision 요약."""
    root = Path(project_root).resolve()
    model = TemplateDecisionStore().load(default_template_decisions_path(root))
    decisions = list(model.decisions)
    if template_name:
        wanted = _slug(template_name)
        decisions = [decision for decision in decisions if _slug(decision.template_name) == wanted]
    accepted = [decision for decision in decisions if decision.status == "accepted"]
    dismissed = [decision for decision in decisions if decision.status == "dismissed"]
    latest = decisions[-1] if decisions else None
    current = load_current_template(root)
    current_name = str(current.get("name") or "").strip() or None
    accepted_not_applied = [
        decision.template_name
        for decision in accepted
        if _slug(decision.template_name) != _slug(current_name or "")
    ]
    return {
        "accepted": len(accepted),
        "dismissed": len(dismissed),
        "latest_status": latest.status if latest else None,
        "latest_template": latest.template_name if latest else None,
        "accepted_not_applied": accepted_not_applied,
        "decisions_path": _relative_to_project(default_template_decisions_path(root), root),
    }


def render_template_review(review: TemplateReview) -> str:
    """템플릿 review를 사람 친화적으로 렌더링한다."""
    lines = [
        "Template Review",
        "==================================================",
        "",
        "Template:",
        f"  {review.template_name}",
        "",
        "Why it fits:",
    ]
    if review.fit_reasons:
        lines.extend([f"  - {reason}" for reason in review.fit_reasons])
    else:
        lines.append("  - no recommendation evidence yet")
    lines.extend(["", "Would change:"])
    if review.diff_highlights:
        lines.extend([f"  - {item}" for item in review.diff_highlights])
    else:
        lines.append("  - no diff evidence yet")
    lines.extend([
        "",
        "No live state copied:",
        "  - notes",
        "  - lessons",
        "  - sessions",
        "  - adoption history",
    ])
    if review.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in review.warnings[:5]])
    if review.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in review.next_actions])
    return "\n".join(lines)


def render_template_decision(decision: TemplateDecision, recorded_path: str) -> str:
    """accept/dismiss 결과를 렌더링한다."""
    action = "accepted" if decision.status == "accepted" else "dismissed"
    lines = [
        f"Template {action}.",
        "",
        "Template:",
        f"  {decision.template_name}",
    ]
    if decision.resolution:
        lines.extend(["", "Resolution:", f"  {decision.resolution}"])
    if decision.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in decision.warnings])
    lines.extend(["", "Recorded:", f"  {recorded_path}"])
    if decision.status == "accepted":
        lines.extend(["", "Next:", f"  cambrian template apply {decision.template_name}"])
    return "\n".join(lines)


def render_template_decisions(model: TemplateDecisionStoreModel, status: str | None = None) -> str:
    """템플릿 decision 목록을 렌더링한다."""
    decisions = [
        decision
        for decision in model.decisions
        if status is None or decision.status == status
    ]
    accepted = [decision for decision in decisions if decision.status == "accepted"]
    dismissed = [decision for decision in decisions if decision.status == "dismissed"]
    lines = ["Template Decisions", "==================================================", "", "Accepted:"]
    if accepted:
        lines.extend([f"  - {decision.template_name}" for decision in accepted])
    else:
        lines.append("  none")
    lines.extend(["", "Dismissed:"])
    if dismissed:
        lines.extend([f"  - {decision.template_name}" for decision in dismissed])
    else:
        lines.append("  none")
    return "\n".join(lines)


def render_template_decision_summary(summary: dict[str, Any]) -> str:
    """템플릿 decision compact summary."""
    latest_template = summary.get("latest_template")
    latest_status = summary.get("latest_status")
    accepted_not_applied = list(summary.get("accepted_not_applied", []) or [])
    lines = [
        "Template decisions:",
        f"  accepted : {int(summary.get('accepted', 0) or 0)}",
        f"  dismissed: {int(summary.get('dismissed', 0) or 0)}",
    ]
    if latest_template and latest_status:
        lines.append(f"  latest   : {latest_template} ({latest_status})")
    if accepted_not_applied:
        lines.extend(["", "Accepted next template:", f"  {accepted_not_applied[-1]}"])
    return "\n".join(lines)


def _require_template(root: Path, template_name: str) -> str:
    store = HarnessTemplateStore()
    model = store.load(default_templates_path(root))
    template = store.find(model, template_name)
    return template.name


def _load_or_build_recommendation(root: Path, warnings: list[str]) -> tuple[TemplateRecommendationReport, str | None]:
    path = default_template_recommendation_path(root)
    if path.exists():
        try:
            return TemplateRecommendationStore().load(path), _relative_to_project(path, root)
        except Exception as exc:
            logger.warning("template recommendation evidence load failed: %s", exc)
            warnings.append(f"template recommendation evidence load failed: {exc}")
    report = TemplateRecommendationBuilder().build(root)
    warnings.append("using unsaved template recommendation evidence")
    return report, None


def _load_or_build_diff(root: Path, template_name: str, warnings: list[str]) -> tuple[TemplateDiffReport, str | None]:
    path = default_template_diff_path(root)
    if path.exists():
        try:
            report = TemplateDiffStore().load(path)
            if _slug(report.target_template_name) == _slug(template_name):
                return report, _relative_to_project(path, root)
            warnings.append("saved diff report targets a different template; using fresh diff")
        except Exception as exc:
            logger.warning("template diff evidence load failed: %s", exc)
            warnings.append(f"template diff evidence load failed: {exc}")
    report = TemplateDiffBuilder().build(root, template_name)
    warnings.append("using unsaved template diff evidence")
    return report, None


def _fit_reasons_for_template(report: TemplateRecommendationReport, template_name: str) -> list[str]:
    wanted = _slug(template_name)
    for candidate in report.candidates:
        if _slug(candidate.name) == wanted:
            return [str(reason) for reason in candidate.reasons if reason]
    return []


def _diff_highlights(report: TemplateDiffReport) -> list[str]:
    return [
        entry.summary
        for entry in report.entries
        if entry.status in {"changed", "missing_in_project"}
    ][:8]


def _review_from_dict(payload: dict[str, Any]) -> TemplateReview:
    return TemplateReview(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        review_id=str(payload.get("review_id", "")),
        created_at=str(payload.get("created_at", "")),
        template_name=str(payload.get("template_name", "")),
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        workspace=str(payload.get("workspace", "")),
        source_recommendation_ref=(
            str(payload.get("source_recommendation_ref"))
            if payload.get("source_recommendation_ref") is not None
            else None
        ),
        source_diff_ref=str(payload.get("source_diff_ref")) if payload.get("source_diff_ref") is not None else None,
        summary=str(payload.get("summary", "")),
        fit_reasons=[str(value) for value in payload.get("fit_reasons", []) if value],
        diff_highlights=[str(value) for value in payload.get("diff_highlights", []) if value],
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        next_actions=[str(value) for value in payload.get("next_actions", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )


def _decision_from_dict(payload: dict[str, Any]) -> TemplateDecision:
    return TemplateDecision(
        decision_id=str(payload.get("decision_id", "")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        status=str(payload.get("status", "")),
        template_name=str(payload.get("template_name", "")),
        title=str(payload.get("title", "")),
        summary=str(payload.get("summary", "")),
        resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
        source_review_ref=(
            str(payload.get("source_review_ref"))
            if payload.get("source_review_ref") is not None
            else None
        ),
        source_diff_ref=str(payload.get("source_diff_ref")) if payload.get("source_diff_ref") is not None else None,
        source_recommendation_ref=(
            str(payload.get("source_recommendation_ref"))
            if payload.get("source_recommendation_ref") is not None
            else None
        ),
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )
