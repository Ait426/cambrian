"""템플릿의 로컬 경력(passport history)과 사용 후 회고를 관리한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_harness import HarnessProfileStore, default_harness_profile_path
from engine.project_template_bootstrap import default_template_bootstrap_path
from engine.project_template_decisions import (
    TemplateReviewStore,
    default_template_decisions_path,
    default_template_reviews_dir,
)
from engine.project_template_diff import default_template_diff_path
from engine.project_template_recommend import (
    default_request_template_recommendation_path,
    default_template_recommendation_path,
)
from engine.project_template_transfer import (
    default_template_exports_dir,
    default_template_imported_dir,
)
from engine.project_templates import (
    HarnessTemplate,
    HarnessTemplateStore,
    default_current_template_path,
    default_templates_path,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
RATINGS = {"strong", "good", "mixed", "weak"}
RETROSPECTIVE_KINDS = {"bootstrap", "fit", "safety", "team", "policy"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str | None) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def _short_id() -> str:
    return datetime.now(timezone.utc).strftime("%f")[:4]


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


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _trim(text: str | None, limit: int = 140) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def default_template_passports_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "passports"


def default_template_passport_path(project_root: Path, template_name: str) -> Path:
    return default_template_passports_dir(project_root) / f"{_slug(template_name)}.yaml"


def default_template_retrospectives_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "templates" / "retrospectives"


@dataclass
class TemplateOutcomeRecord:
    record_id: str
    created_at: str | None
    template_name: str
    template_id: str | None
    source_kind: str | None
    source_project_name: str | None
    source_harness_id: str | None
    event_kind: str
    outcome: str | None
    artifact_refs: list[str]
    tags: list[str]
    summary: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplatePassportHistory:
    schema_version: str
    generated_at: str
    template_name: str
    template_id: str | None
    template_kind: str | None
    source_kind: str | None
    source_project_name: str | None
    source_harness_id: str | None
    totals: dict[str, int]
    recent_wins: list[str]
    recent_cautions: list[str]
    fit_hints: list[str]
    outcome_records: list[TemplateOutcomeRecord]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "template_name": self.template_name,
            "template_id": self.template_id,
            "template_kind": self.template_kind,
            "source_kind": self.source_kind,
            "source_project_name": self.source_project_name,
            "source_harness_id": self.source_harness_id,
            "totals": dict(self.totals),
            "recent_wins": list(self.recent_wins),
            "recent_cautions": list(self.recent_cautions),
            "fit_hints": list(self.fit_hints),
            "outcome_records": [record.to_dict() for record in self.outcome_records],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class TemplateRetrospective:
    schema_version: str
    retrospective_id: str
    created_at: str
    updated_at: str | None
    template_name: str
    template_id: str | None
    project_name: str | None
    harness_id: str | None
    status: str
    rating: str
    retrospective_kind: str
    text: str
    summary: str | None
    resolution: str | None
    source_apply_ref: str | None
    source_bootstrap_ref: str | None
    source_review_ref: str | None
    tags: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TemplatePassportStore:
    def save(self, passport: TemplatePassportHistory, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), passport.to_dict())

    def load(self, path: Path) -> TemplatePassportHistory:
        return _passport_from_dict(_load_yaml(Path(path).resolve()))


class TemplateRetrospectiveStore:
    def add(self, retrospective: TemplateRetrospective, retrospectives_dir: Path) -> Path:
        target = (
            Path(retrospectives_dir).resolve()
            / f"retrospective_{_timestamp()}_{_slug(retrospective.template_name)}_{_short_id()}.yaml"
        )
        return _save_yaml(target, retrospective.to_dict())

    def load(self, path: Path) -> TemplateRetrospective:
        return _retrospective_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, retrospectives_dir: Path, template_name: str | None = None) -> list[TemplateRetrospective]:
        target = Path(retrospectives_dir).resolve()
        if not target.exists():
            return []
        wanted = _slug(template_name) if template_name else None
        items: list[TemplateRetrospective] = []
        for path in sorted(target.glob("retrospective_*.yaml")):
            try:
                retrospective = self.load(path)
            except Exception as exc:
                logger.warning("template retrospective load failed: %s", exc)
                continue
            if wanted and _slug(retrospective.template_name) != wanted:
                continue
            items.append(retrospective)
        return items

    def acknowledge(self, path: Path, resolution: str | None = None) -> Path:
        retrospective = self.load(path)
        retrospective.status = "acknowledged"
        retrospective.updated_at = _now()
        retrospective.resolution = resolution
        return _save_yaml(Path(path).resolve(), retrospective.to_dict())


class TemplateHistoryBuilder:
    def build_passport(self, project_root: Path, template_name: str) -> TemplatePassportHistory:
        root = Path(project_root).resolve()
        template = _find_template(root, template_name)
        warnings: list[str] = []
        records: list[TemplateOutcomeRecord] = []
        records.extend(_recommendation_records(root, template, warnings))
        records.extend(_diff_records(root, template, warnings))
        records.extend(_review_records(root, template, warnings))
        records.extend(_decision_records(root, template, warnings))
        records.extend(_guardrail_records(root, template, warnings))
        records.extend(_current_template_records(root, template, warnings))
        records.extend(_bootstrap_records(root, template, warnings))
        records.extend(_import_records(root, template, warnings))
        records.extend(_export_records(root, template, warnings))
        retrospectives = TemplateRetrospectiveStore().list(default_template_retrospectives_dir(root), template.name)
        records.extend(_retrospective_records(root, template, retrospectives))
        records.sort(key=lambda record: record.created_at or "")
        totals = _totals(records)
        wins, cautions = _wins_and_cautions(records, retrospectives)
        fit_hints = _dedupe([
            *list(template.fit_hints),
            "prior successful local template use" if totals.get("applied", 0) or totals.get("bootstrapped", 0) else "",
            "recent positive retrospective" if any(item.rating in {"strong", "good"} for item in retrospectives) else "",
        ])[:8]
        return TemplatePassportHistory(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            template_name=template.name,
            template_id=template.template_id,
            template_kind=template.template_kind,
            source_kind=template.source_kind,
            source_project_name=template.source_project_name,
            source_harness_id=template.source_harness_id,
            totals=totals,
            recent_wins=wins[:6],
            recent_cautions=cautions[:6],
            fit_hints=fit_hints,
            outcome_records=records,
            warnings=_dedupe(warnings),
            errors=[],
        )

    def build_all_passports(self, project_root: Path) -> list[TemplatePassportHistory]:
        root = Path(project_root).resolve()
        model = HarnessTemplateStore().load(default_templates_path(root))
        passports: list[TemplatePassportHistory] = []
        for template in model.templates:
            passports.append(self.build_passport(root, template.name))
        return passports


def build_template_retrospective(
    project_root: Path,
    template_name: str,
    text: str,
    *,
    rating: str = "good",
    kind: str = "fit",
    tags: list[str] | None = None,
) -> TemplateRetrospective:
    root = Path(project_root).resolve()
    template = _find_template(root, template_name)
    rating = str(rating or "good").strip()
    kind = str(kind or "fit").strip()
    if rating not in RATINGS:
        raise ValueError(f"unsupported retrospective rating: {rating}")
    if kind not in RETROSPECTIVE_KINDS:
        raise ValueError(f"unsupported retrospective kind: {kind}")
    text = str(text or "").strip()
    if not text:
        raise ValueError("template retrospective text is required")
    project_name, harness_id = _project_and_harness(root)
    apply_ref = _current_template_ref(root, template)
    bootstrap_ref = _bootstrap_ref(root, template)
    review_ref = _latest_review_ref(root, template.name)
    return TemplateRetrospective(
        schema_version=SCHEMA_VERSION,
        retrospective_id=f"template-retrospective-{_timestamp()}-{_slug(template.name)}",
        created_at=_now(),
        updated_at=None,
        template_name=template.name,
        template_id=template.template_id,
        project_name=project_name,
        harness_id=harness_id,
        status="open",
        rating=rating,
        retrospective_kind=kind,
        text=text,
        summary=_trim(text, 120),
        resolution=None,
        source_apply_ref=apply_ref,
        source_bootstrap_ref=bootstrap_ref,
        source_review_ref=review_ref,
        tags=_dedupe(list(tags or [])),
        warnings=[],
        errors=[],
    )


def load_template_history_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    try:
        if template_name:
            passport = TemplateHistoryBuilder().build_passport(root, template_name)
        else:
            current = _safe_load_yaml(default_current_template_path(root))
            name = str(current.get("name") or "").strip()
            if not name:
                return {}
            passport = TemplateHistoryBuilder().build_passport(root, name)
    except Exception as exc:
        logger.warning("template history summary failed: %s", exc)
        return {"warnings": [f"template history summary failed: {exc}"]}
    return {
        "template_name": passport.template_name,
        "template_id": passport.template_id,
        "totals": dict(passport.totals),
        "recent_wins": list(passport.recent_wins),
        "recent_cautions": list(passport.recent_cautions),
        "history_path": _relative_to_project(default_template_passport_path(root, passport.template_name), root),
    }


def render_template_history(passport: TemplatePassportHistory, limit: int = 12) -> str:
    lines = [
        "Template History",
        "==================================================",
        "",
        "Template:",
        f"  {passport.template_name}",
        "",
        "Totals:",
    ]
    for key in _event_keys():
        lines.append(f"  {key:<17}: {int(passport.totals.get(key, 0) or 0)}")
    if passport.recent_wins:
        lines.extend(["", "Recent wins:"])
        lines.extend([f"  - {item}" for item in passport.recent_wins[:5]])
    if passport.recent_cautions:
        lines.extend(["", "Recent cautions:"])
        lines.extend([f"  - {item}" for item in passport.recent_cautions[:5]])
    records = list(passport.outcome_records)[-max(1, int(limit or 12)) :]
    if records:
        lines.extend(["", "Recent records:"])
        for record in reversed(records):
            outcome = f" ({record.outcome})" if record.outcome else ""
            lines.append(f"  - [{record.event_kind}{outcome}] {record.summary}")
    if passport.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in passport.warnings[:5]])
    return "\n".join(lines)


def render_template_history_summary(summary: dict[str, Any]) -> str:
    if not summary or not summary.get("template_name"):
        return "Template history:\n  none"
    totals = summary.get("totals") if isinstance(summary.get("totals"), dict) else {}
    cautions = list(summary.get("recent_cautions", []) or [])
    parts = [
        f"{int(totals.get('applied', 0) or 0)} applies",
        f"{int(totals.get('bootstrapped', 0) or 0)} bootstraps",
        f"{int(totals.get('retrospectives', 0) or 0)} retrospectives",
    ]
    if cautions:
        parts.append(f"{len(cautions)} cautions")
    return "\n".join([
        "Template history:",
        f"  {summary.get('template_name')} — {', '.join(parts)}",
    ])


def render_template_retrospective_saved(retrospective: TemplateRetrospective, saved_path: Path, project_root: Path) -> str:
    return "\n".join([
        "Template retrospective saved.",
        "",
        "Template:",
        f"  {retrospective.template_name}",
        "",
        "Retrospective:",
        f"  [{retrospective.rating}][{retrospective.retrospective_kind}]",
        f"  {retrospective.text}",
        "",
        "Saved:",
        f"  {_relative_to_project(saved_path, project_root)}",
    ])


def render_template_retrospectives(
    retrospectives: list[TemplateRetrospective],
    template_name: str,
    *,
    rating: str | None = None,
    status: str | None = None,
) -> str:
    filtered = [
        item
        for item in retrospectives
        if (rating is None or item.rating == rating) and (status is None or item.status == status)
    ]
    lines = [
        "Template Retrospectives",
        "==================================================",
        "",
        "Template:",
        f"  {template_name}",
        "",
        "Recent:",
    ]
    if not filtered:
        lines.append("  none")
        return "\n".join(lines)
    for index, item in enumerate(reversed(filtered[-10:]), start=1):
        lines.append(f"  {index}. [{item.rating}][{item.retrospective_kind}] {item.summary or _trim(item.text)}")
    return "\n".join(lines)


def _find_template(root: Path, template_name: str) -> HarnessTemplate:
    store = HarnessTemplateStore()
    model = store.load(default_templates_path(root))
    return store.find(model, template_name)


def _record(
    root: Path,
    template: HarnessTemplate,
    *,
    event_kind: str,
    outcome: str | None,
    artifact: Path,
    summary: str,
    created_at: str | None = None,
    tags: list[str] | None = None,
    warnings: list[str] | None = None,
) -> TemplateOutcomeRecord:
    return TemplateOutcomeRecord(
        record_id=f"template-{event_kind}-{_slug(template.name)}-{_slug(artifact.stem)}",
        created_at=created_at,
        template_name=template.name,
        template_id=template.template_id,
        source_kind=template.source_kind,
        source_project_name=template.source_project_name,
        source_harness_id=template.source_harness_id,
        event_kind=event_kind,
        outcome=outcome,
        artifact_refs=[_relative_to_project(artifact, root)],
        tags=_dedupe(list(tags or [])),
        summary=summary,
        warnings=_dedupe(list(warnings or [])),
    )


def _recommendation_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    records: list[TemplateOutcomeRecord] = []
    for path in (default_template_recommendation_path(root), default_request_template_recommendation_path(root)):
        if not path.exists():
            continue
        payload = _safe_load_yaml(path, warnings)
        candidate = _candidate_for_template(payload, template.name)
        if not candidate:
            continue
        outcome = str(candidate.get("recommendation") or "")
        score = candidate.get("score")
        summary = f"Recommended as {outcome or 'candidate'}"
        if score is not None:
            summary += f" with score {score}"
        records.append(_record(
            root,
            template,
            event_kind="recommended",
            outcome=outcome or None,
            artifact=path,
            created_at=str(payload.get("generated_at")) if payload.get("generated_at") else None,
            summary=summary,
            tags=["request"] if payload.get("request") else ["project"],
        ))
    return records


def _diff_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    path = default_template_diff_path(root)
    if not path.exists():
        return []
    payload = _safe_load_yaml(path, warnings)
    if _slug(payload.get("target_template_name")) != _slug(template.name):
        return []
    outcome = "yes" if payload.get("safe_to_apply") else "warned"
    return [_record(
        root,
        template,
        event_kind="diffed",
        outcome=outcome,
        artifact=path,
        created_at=str(payload.get("generated_at")) if payload.get("generated_at") else None,
        summary=f"Diffed against current harness in {payload.get('mode') or 'unknown'} mode",
    )]


def _review_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    records: list[TemplateOutcomeRecord] = []
    reviews_dir = default_template_reviews_dir(root)
    if not reviews_dir.exists():
        return records
    for path in sorted(reviews_dir.glob("review_*.yaml")):
        payload = _safe_load_yaml(path, warnings)
        if _slug(payload.get("template_name")) != _slug(template.name):
            continue
        records.append(_record(
            root,
            template,
            event_kind="reviewed",
            outcome="yes",
            artifact=path,
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            summary=str(payload.get("summary") or f"Reviewed {template.name}"),
        ))
    return records


def _decision_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    path = default_template_decisions_path(root)
    if not path.exists():
        return []
    payload = _safe_load_yaml(path, warnings)
    records: list[TemplateOutcomeRecord] = []
    for item in payload.get("decisions", []) or []:
        if not isinstance(item, dict) or _slug(item.get("template_name")) != _slug(template.name):
            continue
        status = str(item.get("status") or "")
        event_kind = "accepted" if status == "accepted" else "dismissed" if status == "dismissed" else "decision"
        records.append(_record(
            root,
            template,
            event_kind=event_kind,
            outcome="yes" if status == "accepted" else "no" if status == "dismissed" else status,
            artifact=path,
            created_at=str(item.get("created_at")) if item.get("created_at") else None,
            summary=str(item.get("summary") or item.get("title") or f"{status} {template.name}"),
        ))
    return records


def _guardrail_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    path = root / ".cambrian" / "templates" / "apply_guardrails.yaml"
    if not path.exists():
        return []
    payload = _safe_load_yaml(path, warnings)
    if _slug(payload.get("template_name")) != _slug(template.name) or payload.get("status") != "blocked":
        return []
    return [_record(
        root,
        template,
        event_kind="guardrail_blocked",
        outcome="blocked",
        artifact=path,
        created_at=str(payload.get("generated_at")) if payload.get("generated_at") else None,
        summary=f"Apply guardrail blocked {template.name}",
        warnings=[str(value) for value in payload.get("errors", []) if value],
    )]


def _current_template_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    path = default_current_template_path(root)
    if not path.exists():
        return []
    payload = _safe_load_yaml(path, warnings)
    if _slug(payload.get("name")) != _slug(template.name):
        return []
    records: list[TemplateOutcomeRecord] = []
    if payload.get("applied_at"):
        records.append(_record(
            root,
            template,
            event_kind="applied",
            outcome="applied",
            artifact=path,
            created_at=str(payload.get("applied_at")),
            summary=f"Applied as current template: {template.name}",
        ))
    if payload.get("bootstrapped_at") and not default_template_bootstrap_path(root).exists():
        records.append(_record(
            root,
            template,
            event_kind="bootstrapped",
            outcome="applied",
            artifact=path,
            created_at=str(payload.get("bootstrapped_at")),
            summary=f"Bootstrapped as current template: {template.name}",
        ))
    return records


def _bootstrap_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    path = default_template_bootstrap_path(root)
    if not path.exists():
        return []
    payload = _safe_load_yaml(path, warnings)
    if _slug(payload.get("template_name")) != _slug(template.name):
        return []
    return [_record(
        root,
        template,
        event_kind="bootstrapped",
        outcome="applied",
        artifact=path,
        created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
        summary=f"Bootstrapped project with {template.name}",
    )]


def _import_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    records: list[TemplateOutcomeRecord] = []
    imported_dir = default_template_imported_dir(root)
    if not imported_dir.exists():
        return records
    for path in sorted(imported_dir.glob("*.yaml")):
        payload = _safe_load_yaml(path, warnings)
        record = payload.get("record", {}) if isinstance(payload.get("record"), dict) else {}
        item = payload.get("template", {}) if isinstance(payload.get("template"), dict) else {}
        if _slug(record.get("name") or item.get("name")) != _slug(template.name):
            continue
        records.append(_record(
            root,
            template,
            event_kind="imported",
            outcome="yes",
            artifact=path,
            created_at=str(record.get("imported_at")) if record.get("imported_at") else None,
            summary=f"Imported from {record.get('source_project_name') or 'unknown project'}",
        ))
    return records


def _export_records(root: Path, template: HarnessTemplate, warnings: list[str]) -> list[TemplateOutcomeRecord]:
    records: list[TemplateOutcomeRecord] = []
    exports_dir = default_template_exports_dir(root)
    if not exports_dir.exists():
        return records
    for path in sorted(exports_dir.glob("*.yaml")):
        payload = _safe_load_yaml(path, warnings)
        if _slug(payload.get("name")) != _slug(template.name):
            continue
        records.append(_record(
            root,
            template,
            event_kind="exported",
            outcome="yes",
            artifact=path,
            created_at=str(payload.get("exported_at")) if payload.get("exported_at") else None,
            summary=f"Exported portable template {template.name}",
        ))
    return records


def _retrospective_records(
    root: Path,
    template: HarnessTemplate,
    retrospectives: list[TemplateRetrospective],
) -> list[TemplateOutcomeRecord]:
    records: list[TemplateOutcomeRecord] = []
    for retrospective in retrospectives:
        path = _retrospective_path_for_id(root, retrospective.retrospective_id)
        records.append(_record(
            root,
            template,
            event_kind="retrospective",
            outcome=retrospective.rating,
            artifact=path,
            created_at=retrospective.created_at,
            summary=retrospective.summary or _trim(retrospective.text),
            tags=[retrospective.retrospective_kind, f"rating:{retrospective.rating}", *retrospective.tags],
            warnings=list(retrospective.warnings),
        ))
    return records


def _retrospective_path_for_id(root: Path, retrospective_id: str) -> Path:
    retrospectives_dir = default_template_retrospectives_dir(root)
    if retrospectives_dir.exists():
        for path in retrospectives_dir.glob("retrospective_*.yaml"):
            try:
                payload = _load_yaml(path)
            except Exception:
                continue
            if payload.get("retrospective_id") == retrospective_id:
                return path
    return retrospectives_dir / f"{_slug(retrospective_id)}.yaml"


def _totals(records: list[TemplateOutcomeRecord]) -> dict[str, int]:
    totals = {key: 0 for key in _event_keys()}
    for record in records:
        if record.event_kind in totals:
            totals[record.event_kind] += 1
    totals["retrospectives"] = sum(1 for record in records if record.event_kind == "retrospective")
    return totals


def _event_keys() -> list[str]:
    return [
        "recommended",
        "diffed",
        "reviewed",
        "accepted",
        "dismissed",
        "applied",
        "bootstrapped",
        "imported",
        "exported",
        "guardrail_blocked",
        "retrospectives",
    ]


def _wins_and_cautions(
    records: list[TemplateOutcomeRecord],
    retrospectives: list[TemplateRetrospective],
) -> tuple[list[str], list[str]]:
    wins: list[str] = []
    cautions: list[str] = []
    for record in records:
        if record.event_kind in {"applied", "bootstrapped"}:
            wins.append(record.summary)
        if record.event_kind == "accepted":
            wins.append(record.summary)
        if record.event_kind in {"dismissed", "guardrail_blocked"}:
            cautions.append(record.summary)
    for item in retrospectives:
        summary = item.summary or _trim(item.text)
        if item.rating in {"strong", "good"}:
            wins.append(summary)
        elif item.rating in {"mixed", "weak"}:
            cautions.append(summary)
    return _dedupe(wins), _dedupe(cautions)


def _candidate_for_template(payload: dict[str, Any], template_name: str) -> dict[str, Any] | None:
    wanted = _slug(template_name)
    for item in payload.get("candidates", []) or []:
        if isinstance(item, dict) and _slug(item.get("name")) == wanted:
            return item
    return None


def _safe_load_yaml(path: Path, warnings: list[str] | None = None) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return _load_yaml(path)
    except Exception as exc:
        logger.warning("template history source load failed: %s", exc)
        if warnings is not None:
            warnings.append(f"template history source load failed for {path.name}: {exc}")
        return {}


def _project_and_harness(root: Path) -> tuple[str | None, str | None]:
    harness_path = default_harness_profile_path(root)
    if harness_path.exists():
        try:
            harness = HarnessProfileStore().load(harness_path)
            return harness.project_name, harness.harness_id
        except Exception as exc:
            logger.warning("harness context for template retrospective failed: %s", exc)
    project_path = root / ".cambrian" / "project.yaml"
    payload = _safe_load_yaml(project_path)
    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    return str(project.get("name") or root.name), None


def _current_template_ref(root: Path, template: HarnessTemplate) -> str | None:
    path = default_current_template_path(root)
    payload = _safe_load_yaml(path)
    if _slug(payload.get("name")) == _slug(template.name):
        return _relative_to_project(path, root)
    return None


def _bootstrap_ref(root: Path, template: HarnessTemplate) -> str | None:
    path = default_template_bootstrap_path(root)
    payload = _safe_load_yaml(path)
    if _slug(payload.get("template_name")) == _slug(template.name):
        return _relative_to_project(path, root)
    return None


def _latest_review_ref(root: Path, template_name: str) -> str | None:
    try:
        _review, path = TemplateReviewStore().latest(root, template_name)
    except Exception as exc:
        logger.warning("latest template review lookup failed: %s", exc)
        return None
    return _relative_to_project(path, root) if path else None


def _passport_from_dict(payload: dict[str, Any]) -> TemplatePassportHistory:
    records = [
        _record_from_dict(item)
        for item in payload.get("outcome_records", []) or []
        if isinstance(item, dict)
    ]
    return TemplatePassportHistory(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        generated_at=str(payload.get("generated_at", "")),
        template_name=str(payload.get("template_name", "")),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        template_kind=str(payload.get("template_kind")) if payload.get("template_kind") is not None else None,
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        source_project_name=str(payload.get("source_project_name")) if payload.get("source_project_name") is not None else None,
        source_harness_id=str(payload.get("source_harness_id")) if payload.get("source_harness_id") is not None else None,
        totals=dict(payload.get("totals", {}) if isinstance(payload.get("totals"), dict) else {}),
        recent_wins=[str(value) for value in payload.get("recent_wins", []) if value],
        recent_cautions=[str(value) for value in payload.get("recent_cautions", []) if value],
        fit_hints=[str(value) for value in payload.get("fit_hints", []) if value],
        outcome_records=records,
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )


def _record_from_dict(payload: dict[str, Any]) -> TemplateOutcomeRecord:
    return TemplateOutcomeRecord(
        record_id=str(payload.get("record_id", "")),
        created_at=str(payload.get("created_at")) if payload.get("created_at") is not None else None,
        template_name=str(payload.get("template_name", "")),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        source_project_name=str(payload.get("source_project_name")) if payload.get("source_project_name") is not None else None,
        source_harness_id=str(payload.get("source_harness_id")) if payload.get("source_harness_id") is not None else None,
        event_kind=str(payload.get("event_kind", "")),
        outcome=str(payload.get("outcome")) if payload.get("outcome") is not None else None,
        artifact_refs=[str(value) for value in payload.get("artifact_refs", []) if value],
        tags=[str(value) for value in payload.get("tags", []) if value],
        summary=str(payload.get("summary", "")),
        warnings=[str(value) for value in payload.get("warnings", []) if value],
    )


def _retrospective_from_dict(payload: dict[str, Any]) -> TemplateRetrospective:
    return TemplateRetrospective(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        retrospective_id=str(payload.get("retrospective_id", "")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        template_name=str(payload.get("template_name", "")),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
        status=str(payload.get("status", "open")),
        rating=str(payload.get("rating", "good")),
        retrospective_kind=str(payload.get("retrospective_kind", "fit")),
        text=str(payload.get("text", "")),
        summary=str(payload.get("summary")) if payload.get("summary") is not None else None,
        resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
        source_apply_ref=str(payload.get("source_apply_ref")) if payload.get("source_apply_ref") is not None else None,
        source_bootstrap_ref=str(payload.get("source_bootstrap_ref")) if payload.get("source_bootstrap_ref") is not None else None,
        source_review_ref=str(payload.get("source_review_ref")) if payload.get("source_review_ref") is not None else None,
        tags=[str(value) for value in payload.get("tags", []) if value],
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )
