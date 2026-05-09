"""로컬 템플릿 라이브러리의 preferred/watch/retire 보드를 만든다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_history import TemplateHistoryBuilder
from engine.project_template_library_decisions import load_template_library_decision_summary
from engine.project_template_library_policy import (
    TemplateLibraryPolicyDecision,
    build_and_save_template_library_policy_overlay,
    load_template_library_policy_summary,
    template_library_policy_by_template,
)
from engine.project_template_recommend import TemplateRecommendationBuilder, TemplateRecommendationReport
from engine.project_template_qualification import load_latest_template_qualification_summary
from engine.project_templates import HarnessTemplate, HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
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
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


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


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _slug(value: str | None) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def default_template_library_board_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "library_board.yaml"


@dataclass
class TemplateLibraryEntry:
    template_name: str
    template_id: str | None
    template_kind: str | None
    source_kind: str | None
    score: float
    confidence: float
    recommendation: str
    reasons: list[str]
    warnings: list[str]
    usage_summary: dict[str, Any]
    fit_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateLibraryBoard:
    schema_version: str
    generated_at: str
    report_id: str
    project_name: str | None
    workspace: str
    mode: str
    request: str | None
    preferred_templates: list[str]
    strong_alternatives: list[str]
    promising_imported: list[str]
    watch_templates: list[str]
    retire_candidates: list[str]
    entries: list[TemplateLibraryEntry]
    summary: dict[str, Any]
    next_actions: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "report_id": self.report_id,
            "project_name": self.project_name,
            "workspace": self.workspace,
            "mode": self.mode,
            "request": self.request,
            "preferred_templates": list(self.preferred_templates),
            "strong_alternatives": list(self.strong_alternatives),
            "promising_imported": list(self.promising_imported),
            "watch_templates": list(self.watch_templates),
            "retire_candidates": list(self.retire_candidates),
            "entries": [entry.to_dict() for entry in self.entries],
            "summary": dict(self.summary),
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateLibraryBoardBuilder:
    def build(self, project_root: Path, request: str | None = None) -> TemplateLibraryBoard:
        root = Path(project_root).resolve()
        store = HarnessTemplateStore()
        model = store.load(default_templates_path(root))
        recommendation = TemplateRecommendationBuilder().build(root, request=request)
        candidate_by_name = {candidate.name: candidate for candidate in recommendation.candidates}
        policy_overlay, _ = build_and_save_template_library_policy_overlay(root)
        decision_by_template = template_library_policy_by_template(policy_overlay)
        warnings = list(recommendation.warnings)
        entries: list[TemplateLibraryEntry] = []
        for template in model.templates:
            try:
                history = TemplateHistoryBuilder().build_passport(root, template.name)
            except Exception as exc:
                logger.warning("template history for board failed: %s", exc)
                history = None
                warnings.append(f"template history unavailable for {template.name}: {exc}")
            candidate = candidate_by_name.get(template.name)
            decision = decision_by_template.get(_slug(template.name))
            entries.append(_entry_from_template(root, template, candidate, history, decision))
        entries.sort(key=lambda entry: entry.score, reverse=True)
        preferred = [entry.template_name for entry in entries if entry.recommendation == "preferred"]
        strong = [entry.template_name for entry in entries if entry.recommendation == "strong_alternative"]
        promising = [entry.template_name for entry in entries if entry.recommendation == "promising_imported"]
        watch = [entry.template_name for entry in entries if entry.recommendation == "watch"]
        retire = [entry.template_name for entry in entries if entry.recommendation == "retire_candidate"]
        next_actions = _next_actions(preferred, strong, promising)
        summary = {
            "templates_seen": len(entries),
            "local_templates": sum(1 for entry in entries if entry.source_kind != "imported"),
            "imported_templates": sum(1 for entry in entries if entry.source_kind == "imported"),
            "preferred_count": len(preferred),
            "retire_candidate_count": len(retire),
            "best_recommendation": recommendation.best_template_name,
            "library_decisions": load_template_library_decision_summary(root),
            "library_policy": load_template_library_policy_summary(root),
        }
        return TemplateLibraryBoard(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            report_id=f"template-library-board-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            project_name=recommendation.project_name,
            workspace=str(root),
            mode="request" if request else "project",
            request=request,
            preferred_templates=preferred,
            strong_alternatives=strong,
            promising_imported=promising,
            watch_templates=watch,
            retire_candidates=retire,
            entries=entries,
            summary=summary,
            next_actions=next_actions,
            warnings=_dedupe(warnings),
            errors=[],
        )


class TemplateLibraryBoardStore:
    def save(self, report: TemplateLibraryBoard, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), report.to_dict())

    def load(self, path: Path) -> TemplateLibraryBoard:
        payload = _load_yaml(Path(path).resolve())
        entries = [
            TemplateLibraryEntry(
                template_name=str(item.get("template_name", "")),
                template_id=str(item.get("template_id")) if item.get("template_id") is not None else None,
                template_kind=str(item.get("template_kind")) if item.get("template_kind") is not None else None,
                source_kind=str(item.get("source_kind")) if item.get("source_kind") is not None else None,
                score=float(item.get("score", 0.0) or 0.0),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                recommendation=str(item.get("recommendation", "")),
                reasons=[str(value) for value in item.get("reasons", []) if value],
                warnings=[str(value) for value in item.get("warnings", []) if value],
                usage_summary=dict(item.get("usage_summary", {}) if isinstance(item.get("usage_summary"), dict) else {}),
                fit_summary=dict(item.get("fit_summary", {}) if isinstance(item.get("fit_summary"), dict) else {}),
            )
            for item in payload.get("entries", []) or []
            if isinstance(item, dict)
        ]
        return TemplateLibraryBoard(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            report_id=str(payload.get("report_id", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            workspace=str(payload.get("workspace", "")),
            mode=str(payload.get("mode", "project")),
            request=str(payload.get("request")) if payload.get("request") is not None else None,
            preferred_templates=[str(value) for value in payload.get("preferred_templates", []) if value],
            strong_alternatives=[str(value) for value in payload.get("strong_alternatives", []) if value],
            promising_imported=[str(value) for value in payload.get("promising_imported", []) if value],
            watch_templates=[str(value) for value in payload.get("watch_templates", []) if value],
            retire_candidates=[str(value) for value in payload.get("retire_candidates", []) if value],
            entries=entries,
            summary=dict(payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}),
            next_actions=[str(value) for value in payload.get("next_actions", []) if value],
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


def _entry_from_template(
    root: Path,
    template: HarnessTemplate,
    candidate: Any | None,
    history: Any | None,
    decision: TemplateLibraryPolicyDecision | None = None,
) -> TemplateLibraryEntry:
    candidate_score = float(getattr(candidate, "score", 0.1) if candidate is not None else 0.1)
    candidate_confidence = float(getattr(candidate, "confidence", 0.2) if candidate is not None else 0.2)
    reasons = list(getattr(candidate, "reasons", []) if candidate is not None else [])
    warnings = list(getattr(candidate, "warnings", []) if candidate is not None else [])
    fit_summary = dict(getattr(candidate, "project_fit", {}) if candidate is not None else {})
    totals = dict(getattr(history, "totals", {}) if history is not None else {})
    recent_wins = list(getattr(history, "recent_wins", []) if history is not None else [])
    recent_cautions = list(getattr(history, "recent_cautions", []) if history is not None else [])
    usage = {
        "recommended": int(totals.get("recommended", 0) or 0),
        "reviewed": int(totals.get("reviewed", 0) or 0),
        "accepted": int(totals.get("accepted", 0) or 0),
        "dismissed": int(totals.get("dismissed", 0) or 0),
        "applied": int(totals.get("applied", 0) or 0),
        "bootstrapped": int(totals.get("bootstrapped", 0) or 0),
        "imported": int(totals.get("imported", 0) or 0),
        "exported": int(totals.get("exported", 0) or 0),
        "guardrail_blocked": int(totals.get("guardrail_blocked", 0) or 0),
        "retrospectives": int(totals.get("retrospectives", 0) or 0),
        "recent_positive": len(recent_wins),
        "recent_cautions": len(recent_cautions),
    }
    score = candidate_score
    local_usage = usage["accepted"] + usage["applied"] + usage["bootstrapped"] + usage["retrospectives"]
    if usage["applied"] or usage["bootstrapped"]:
        score += 0.08
        reasons.append("successful local apply/bootstrap history")
    if usage["accepted"]:
        score += 0.04
        reasons.append("approved in this project")
    if recent_wins:
        score += 0.05
        reasons.append("positive retrospective or outcome history")
    if template.source_kind == "local":
        score += 0.02
    if recent_cautions:
        score -= min(0.18, 0.06 * len(recent_cautions))
        warnings.append("recent caution history")
    if usage["dismissed"] or usage["guardrail_blocked"]:
        score -= 0.08
        warnings.append("approval or guardrail caution exists")
    decision_kind = decision.decision_kind if decision is not None else None
    if decision_kind:
        fit_summary["template_library_policy"] = {
            "decision_kind": decision_kind,
            "decision_id": decision.decision_id,
            "source_ref": decision.source_ref,
        }
        fit_summary["library_decision"] = dict(fit_summary["template_library_policy"])
    if decision_kind == "promote":
        score += 0.09
        reasons.append("previously promoted in local library")
    elif decision_kind == "keep":
        score += 0.04
        reasons.append("kept in local library")
    elif decision_kind == "backup":
        score += 0.06
        reasons.append("marked as backup template")
    elif decision_kind == "watch":
        score -= 0.02
        warnings.append("marked for watch in local library")
    elif decision_kind == "retire":
        score -= 0.35
        warnings.append("retired in local library")
    qualification = load_latest_template_qualification_summary(root, template.name)
    if qualification:
        fit_summary["template_qualification"] = qualification
        verdict = str(qualification.get("verdict") or "")
        if verdict == "candidate_stronger":
            score += 0.05
            reasons.append("qualified above parent on auth-bug-workset")
        elif verdict == "regressed":
            score -= 0.12
            warnings.append("qualification regressed against parent")
    score = _clamp(score)
    recommendation = _bucket(template, score, local_usage, usage, candidate_score, recent_cautions, decision_kind)
    reasons = _dedupe(reasons)
    warnings = _dedupe(warnings)
    if recommendation == "promising_imported":
        reasons.append("imported template has good fit but limited local history")
    if recommendation == "retire_candidate":
        warnings.append("template looks weak for current project focus")
    return TemplateLibraryEntry(
        template_name=template.name,
        template_id=template.template_id,
        template_kind=template.template_kind,
        source_kind=template.source_kind,
        score=score,
        confidence=candidate_confidence,
        recommendation=recommendation,
        reasons=_dedupe(reasons)[:8],
        warnings=_dedupe(warnings)[:8],
        usage_summary=usage,
        fit_summary=fit_summary,
    )


def _bucket(
    template: HarnessTemplate,
    score: float,
    local_usage: int,
    usage: dict[str, int],
    candidate_score: float,
    recent_cautions: list[str],
    decision_kind: str | None = None,
) -> str:
    if decision_kind == "retire":
        return "retire_candidate"
    if decision_kind == "watch":
        return "watch"
    if decision_kind == "backup" and score >= 0.35:
        return "strong_alternative"
    if decision_kind == "promote" and score >= 0.45:
        return "preferred"
    if decision_kind == "keep" and score >= 0.5:
        return "strong_alternative"
    caution_count = len(recent_cautions) + usage.get("dismissed", 0) + usage.get("guardrail_blocked", 0)
    if candidate_score < 0.25 or (caution_count >= 2 and candidate_score < 0.5) or (caution_count >= 3 and local_usage <= 1):
        return "retire_candidate"
    if caution_count > 0:
        return "watch"
    if template.source_kind == "imported" and local_usage <= 1 and score >= 0.45:
        return "promising_imported"
    if template.source_kind != "imported" and score >= 0.68 and local_usage > 0:
        return "preferred"
    if score >= 0.5:
        return "strong_alternative"
    return "watch"


def _next_actions(preferred: list[str], strong: list[str], promising: list[str]) -> list[str]:
    target = (preferred or strong or promising or [None])[0]
    if not target:
        return ["cambrian template save auth-bug-template"]
    return [
        f"cambrian template show {target}",
        f"cambrian template diff {target}",
    ]


def load_template_library_board_summary(project_root: Path, request: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    try:
        board = TemplateLibraryBoardBuilder().build(root, request=request)
    except Exception as exc:
        logger.warning("template library board summary failed: %s", exc)
        return {"warnings": [f"template library board failed: {exc}"]}
    return {
        "preferred_templates": list(board.preferred_templates),
        "strong_alternatives": list(board.strong_alternatives),
        "promising_imported": list(board.promising_imported),
        "watch_templates": list(board.watch_templates),
        "retire_candidates": list(board.retire_candidates),
        "summary": dict(board.summary),
    }


def load_template_library_standing_summary(project_root: Path, template_name: str) -> dict[str, Any]:
    try:
        board = TemplateLibraryBoardBuilder().build(project_root)
    except Exception as exc:
        logger.warning("template library standing failed: %s", exc)
        return {"warnings": [f"template library standing failed: {exc}"]}
    wanted = _slug(template_name)
    for entry in board.entries:
        if _slug(entry.template_name) == wanted:
            return entry.to_dict()
    return {}


def render_template_library_board(board: TemplateLibraryBoard) -> str:
    preferred_label = "Preferred for this request:" if board.request else "Preferred now:"
    lines = [
        "Template Library Board",
        "==================================================",
        "",
        preferred_label,
    ]
    _append_bucket(lines, board.preferred_templates)
    lines.extend(["", "Strong alternatives:"])
    _append_bucket(lines, board.strong_alternatives)
    lines.extend(["", "Promising imported:"])
    _append_bucket(lines, board.promising_imported)
    lines.extend(["", "Watch:"])
    _append_bucket(lines, board.watch_templates)
    lines.extend(["", "Retire candidate:"])
    _append_bucket(lines, board.retire_candidates)
    leader = board.entries[0] if board.entries else None
    if leader:
        lines.extend(["", f"Why {leader.template_name} leads:"])
        if leader.reasons:
            lines.extend([f"  - {reason}" for reason in leader.reasons[:5]])
        else:
            lines.append("  - strongest available template fit")
    if board.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in board.warnings[:4]])
    if board.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in board.next_actions[:3]])
    return "\n".join(lines)


def render_template_library_summary(summary: dict[str, Any]) -> str:
    preferred = list(summary.get("preferred_templates", []) or [])
    retire = list(summary.get("retire_candidates", []) or [])
    watch = list(summary.get("watch_templates", []) or [])
    if not preferred and not retire and not watch:
        return "Template library:\n  no standing yet"
    lines = ["Template library:"]
    if preferred:
        lines.append(f"  preferred : {preferred[0]}")
    if watch:
        lines.append(f"  watch     : {watch[0]}")
    if retire:
        lines.append(f"  retire    : {retire[0]}")
    return "\n".join(lines)


def render_template_library_standing(entry: dict[str, Any]) -> str:
    if not entry:
        return "Library standing:\n  unknown"
    fit_summary = entry.get("fit_summary") if isinstance(entry.get("fit_summary"), dict) else {}
    library_decision = (
        fit_summary.get("library_decision")
        if isinstance(fit_summary.get("library_decision"), dict)
        else {}
    )
    decision_kind = str(library_decision.get("decision_kind") or "").strip()
    lines = [
        "Library standing:",
        f"  {decision_kind or entry.get('recommendation') or 'unknown'}",
    ]
    if decision_kind:
        lines.append(f"  board bucket: {entry.get('recommendation') or 'unknown'}")
    reasons = [str(value) for value in entry.get("reasons", []) if value]
    warnings = [str(value) for value in entry.get("warnings", []) if value]
    if reasons:
        lines.extend(["", "Standing reasons:"])
        lines.extend([f"  - {reason}" for reason in reasons[:3]])
    if warnings:
        lines.extend(["", "Standing warnings:"])
        lines.extend([f"  - {warning}" for warning in warnings[:3]])
    return "\n".join(lines)


def _append_bucket(lines: list[str], names: list[str]) -> None:
    if names:
        lines.extend([f"  - {name}" for name in names])
    else:
        lines.append("  none")
