"""Accepted decision 기반 하네스 정책 overlay."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_dispatch_decisions import StaffingDecisionStore, default_staffing_decisions_path
from engine.project_harness import HarnessProfileStore, default_harness_profile_path
from engine.project_harness_decisions import HarnessDecisionStore, default_harness_decisions_path

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


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


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_harness_policy_overlay_path(project_root: Path) -> Path:
    """하네스 policy overlay 기본 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "harness" / "policy_overlay.yaml"


@dataclass
class HarnessPolicyDecision:
    """overlay에 반영된 accepted decision 요약."""

    decision_id: str
    decision_kind: str
    target: str | None
    title: str
    summary: str
    source_ref: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class HarnessPolicyOverlay:
    """현재 프로젝트에 적용 가능한 안전한 policy overlay."""

    schema_version: str
    generated_at: str
    project_name: str | None
    harness_id: str | None
    preferred_lead_agents: list[str] = field(default_factory=list)
    preferred_support_agents: list[str] = field(default_factory=list)
    backup_agents: list[str] = field(default_factory=list)
    watched_agents: list[str] = field(default_factory=list)
    test_first_practice: bool = False
    narrow_change_scope: bool = False
    increase_review_support: bool = False
    promote_request_focus: list[str] = field(default_factory=list)
    caution_memory_review: bool = False
    note_followup: bool = False
    accepted_decisions: list[HarnessPolicyDecision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["accepted_decisions"] = [item.to_dict() for item in self.accepted_decisions]
        return payload


class HarnessPolicyOverlayBuilder:
    """accepted decision을 안전한 policy overlay로 변환한다."""

    def build(self, project_root: Path) -> HarnessPolicyOverlay:
        """현재 프로젝트의 accepted decision으로 overlay를 만든다."""
        root = Path(project_root).resolve()
        project_name: str | None = root.name
        harness_id: str | None = None
        warnings: list[str] = []
        profile_path = default_harness_profile_path(root)
        if profile_path.exists():
            try:
                profile = HarnessProfileStore().load(profile_path)
                project_name = profile.project_name
                harness_id = profile.harness_id
            except Exception as exc:
                warnings.append(f"harness profile load failed: {exc}")

        overlay = HarnessPolicyOverlay(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            project_name=project_name,
            harness_id=harness_id,
            warnings=warnings,
        )
        self._apply_harness_decisions(root, overlay)
        self._apply_staffing_decisions(root, overlay)
        overlay.preferred_lead_agents = _dedupe(overlay.preferred_lead_agents)
        overlay.preferred_support_agents = _dedupe(overlay.preferred_support_agents)
        overlay.backup_agents = _dedupe(overlay.backup_agents)
        overlay.watched_agents = _dedupe(overlay.watched_agents)
        overlay.promote_request_focus = _dedupe(overlay.promote_request_focus)
        return overlay

    def _apply_harness_decisions(self, root: Path, overlay: HarnessPolicyOverlay) -> None:
        path = default_harness_decisions_path(root)
        if not path.exists():
            return
        try:
            model = HarnessDecisionStore().load(path)
        except Exception as exc:
            overlay.warnings.append(f"harness decisions load failed: {exc}")
            return
        for decision in model.decisions:
            if decision.status != "accepted":
                continue
            kind = str(decision.kind or "").strip()
            target = str(decision.target or "").strip() or None
            overlay.accepted_decisions.append(
                HarnessPolicyDecision(
                    decision_id=decision.decision_id,
                    decision_kind=kind,
                    target=target,
                    title=decision.title,
                    summary=decision.summary,
                    source_ref=decision.source_report_ref,
                    warnings=list(decision.warnings),
                )
            )
            self._map_decision(kind, target, decision.title, decision.summary, overlay)

    def _apply_staffing_decisions(self, root: Path, overlay: HarnessPolicyOverlay) -> None:
        path = default_staffing_decisions_path(root)
        if not path.exists():
            return
        try:
            model = StaffingDecisionStore().load(path)
        except Exception as exc:
            overlay.warnings.append(f"staffing decisions load failed: {exc}")
            return
        for decision in model.decisions:
            if decision.status != "accepted":
                continue
            kind = str(decision.decision_kind or "").strip()
            target = str(decision.target_agent_id or "").strip() or None
            overlay.accepted_decisions.append(
                HarnessPolicyDecision(
                    decision_id=decision.decision_id,
                    decision_kind=kind,
                    target=target,
                    title=decision.title,
                    summary=decision.summary,
                    source_ref=decision.source_ref,
                    warnings=list(decision.warnings),
                )
            )
            self._map_decision(kind, target, decision.title, decision.summary, overlay)

    def _map_decision(
        self,
        kind: str,
        target: str | None,
        title: str,
        summary: str,
        overlay: HarnessPolicyOverlay,
    ) -> None:
        if kind == "prefer_lead" and target:
            overlay.preferred_lead_agents.append(target)
        elif kind == "prefer_support" and target:
            overlay.preferred_support_agents.append(target)
        elif kind == "keep_as_backup" and target:
            overlay.backup_agents.append(target)
        elif kind == "watch_candidate" and target:
            overlay.watched_agents.append(target)
        elif kind == "strengthen_test_practice":
            overlay.test_first_practice = True
        elif kind == "narrow_change_scope":
            overlay.narrow_change_scope = True
        elif kind == "increase_review_support":
            overlay.increase_review_support = True
        elif kind == "promote_request_focus":
            focus = target or _extract_focus(title, summary)
            if focus:
                overlay.promote_request_focus.append(focus)
            else:
                overlay.warnings.append("promote_request_focus decision has no target; kept as display-only policy")
        elif kind == "caution_memory_review":
            overlay.caution_memory_review = True
        elif kind == "note_followup":
            overlay.note_followup = True


class HarnessPolicyStore:
    """policy overlay 저장소."""

    def save(self, overlay: HarnessPolicyOverlay, path: Path) -> Path:
        """overlay를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(overlay.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> HarnessPolicyOverlay:
        """저장된 overlay를 로드한다."""
        target = Path(path).resolve()
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        decisions = [
            HarnessPolicyDecision(
                decision_id=str(item.get("decision_id", "")),
                decision_kind=str(item.get("decision_kind", "")),
                target=str(item.get("target")) if item.get("target") is not None else None,
                title=str(item.get("title", "")),
                summary=str(item.get("summary", "")),
                source_ref=str(item.get("source_ref")) if item.get("source_ref") is not None else None,
                warnings=[str(warning) for warning in item.get("warnings", []) if warning],
            )
            for item in payload.get("accepted_decisions", [])
            if isinstance(item, dict)
        ]
        return HarnessPolicyOverlay(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            preferred_lead_agents=[str(item) for item in payload.get("preferred_lead_agents", []) if item],
            preferred_support_agents=[str(item) for item in payload.get("preferred_support_agents", []) if item],
            backup_agents=[str(item) for item in payload.get("backup_agents", []) if item],
            watched_agents=[str(item) for item in payload.get("watched_agents", []) if item],
            test_first_practice=bool(payload.get("test_first_practice", False)),
            narrow_change_scope=bool(payload.get("narrow_change_scope", False)),
            increase_review_support=bool(payload.get("increase_review_support", False)),
            promote_request_focus=[str(item) for item in payload.get("promote_request_focus", []) if item],
            caution_memory_review=bool(payload.get("caution_memory_review", False)),
            note_followup=bool(payload.get("note_followup", False)),
            accepted_decisions=decisions,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


def _extract_focus(title: str, summary: str) -> str | None:
    text = f"{title} {summary}".lower()
    for token in ("bug_fix", "regression_test", "docs_update", "review", "auth", "login"):
        if token in text:
            return token
    return None


def policy_hints(overlay: HarnessPolicyOverlay) -> list[str]:
    """사람에게 보여줄 policy hint를 만든다."""
    hints: list[str] = []
    if overlay.test_first_practice:
        hints.append("test-first practice is preferred")
    if overlay.narrow_change_scope:
        hints.append("keep change scope narrow before broader refactors")
    if overlay.increase_review_support:
        hints.append("review support is preferred for risky changes")
    if overlay.preferred_lead_agents:
        hints.append(f"preferred lead: {', '.join(overlay.preferred_lead_agents)}")
    if overlay.preferred_support_agents:
        hints.append(f"preferred support: {', '.join(overlay.preferred_support_agents)}")
    if overlay.backup_agents:
        hints.append(f"backup candidates: {', '.join(overlay.backup_agents)}")
    if overlay.watched_agents:
        hints.append(f"watched candidates: {', '.join(overlay.watched_agents)}")
    if overlay.caution_memory_review:
        hints.append("review project memory carefully before relying on it")
    if overlay.note_followup:
        hints.append("follow up on open notes")
    return _dedupe(hints)


def policy_context_from_overlay(overlay: HarnessPolicyOverlay, project_root: Path, overlay_path: Path | None = None) -> dict[str, Any]:
    """request/session artifact에 저장할 policy snapshot을 만든다."""
    root = Path(project_root).resolve()
    target = overlay_path or default_harness_policy_overlay_path(root)
    return {
        "enabled": bool(overlay.accepted_decisions),
        "overlay_ref": _relative_to_project(target, root),
        "preferred_lead_agents": list(overlay.preferred_lead_agents),
        "preferred_support_agents": list(overlay.preferred_support_agents),
        "backup_agents": list(overlay.backup_agents),
        "watched_agents": list(overlay.watched_agents),
        "policy_flags": {
            "test_first_practice": bool(overlay.test_first_practice),
            "narrow_change_scope": bool(overlay.narrow_change_scope),
            "increase_review_support": bool(overlay.increase_review_support),
            "caution_memory_review": bool(overlay.caution_memory_review),
            "note_followup": bool(overlay.note_followup),
        },
        "promote_request_focus": list(overlay.promote_request_focus),
        "applied_hints": policy_hints(overlay),
        "accepted_decision_ids": [item.decision_id for item in overlay.accepted_decisions],
        "warnings": list(overlay.warnings),
    }


def build_and_save_policy_overlay(project_root: Path) -> tuple[HarnessPolicyOverlay, Path]:
    """overlay를 빌드하고 기본 위치에 저장한다."""
    root = Path(project_root).resolve()
    overlay = HarnessPolicyOverlayBuilder().build(root)
    path = default_harness_policy_overlay_path(root)
    HarnessPolicyStore().save(overlay, path)
    return overlay, path


def load_or_build_policy_overlay(project_root: Path) -> HarnessPolicyOverlay:
    """저장된 overlay가 있으면 읽고, 없으면 즉석에서 빌드한다."""
    root = Path(project_root).resolve()
    path = default_harness_policy_overlay_path(root)
    if path.exists():
        try:
            return HarnessPolicyStore().load(path)
        except Exception:
            return HarnessPolicyOverlayBuilder().build(root)
    return HarnessPolicyOverlayBuilder().build(root)


def render_harness_policy_summary(overlay: HarnessPolicyOverlay) -> str:
    """status/show용 policy 요약을 렌더링한다."""
    lines = [
        "Harness policy:",
        f"  accepted hints: {len(policy_hints(overlay))}",
    ]
    if overlay.preferred_lead_agents:
        lines.append(f"  lead prefs   : {', '.join(overlay.preferred_lead_agents)}")
    if overlay.preferred_support_agents:
        lines.append(f"  support prefs: {', '.join(overlay.preferred_support_agents)}")
    rules: list[str] = []
    if overlay.test_first_practice:
        rules.append("test-first")
    if overlay.narrow_change_scope:
        rules.append("narrow-scope")
    if overlay.increase_review_support:
        rules.append("review-support")
    if rules:
        lines.append(f"  rules        : {', '.join(rules)}")
    hints = policy_hints(overlay)
    if hints:
        lines.extend(["", "Accepted policy:"])
        for item in hints[:5]:
            lines.append(f"  - {item}")
    return "\n".join(lines)
