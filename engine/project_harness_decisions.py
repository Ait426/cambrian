"""Cambrian 프로젝트 하네스 결정 저장소."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from engine.project_agent_transfer import update_imported_agent_local_status
from engine.project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from engine.project_harness import HarnessProfileStore, default_harness_profile_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
_VALID_DECISION_STATUS = {"accepted", "dismissed"}
_OPERATIONAL_KINDS = {"hire_agent", "fire_agent", "keep_agent"}

if TYPE_CHECKING:
    from engine.project_harness_evolution import HarnessEvolutionReport, HarnessSuggestion


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _decision_id(suggestion_id: str) -> str:
    """제안 id 기반 결정 id를 만든다."""
    token = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"decision-{token}-{suggestion_id}"


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
    """순서를 유지하며 중복 문자열을 제거한다."""
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
    """프로젝트 루트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_harness_decisions_path(project_root: Path) -> Path:
    """하네스 결정 기본 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "harness" / "decisions.yaml"


@dataclass
class HarnessDecision:
    """하네스 제안에 대한 사용자의 명시적 결정."""

    decision_id: str
    suggestion_id: str
    created_at: str
    updated_at: str | None
    status: str
    kind: str
    target: str | None
    title: str
    summary: str
    resolution: str | None
    source_report_ref: str | None
    evidence_refs: list[str]
    operational_effect: dict
    tags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class HarnessDecisionStoreModel:
    """하네스 결정 저장 모델."""

    schema_version: str
    updated_at: str
    decisions: list[HarnessDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "decisions": [item.to_dict() for item in self.decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class HarnessDecisionStore:
    """하네스 결정 저장/로드 도구."""

    def load(self, path: Path) -> HarnessDecisionStoreModel:
        """저장된 결정을 읽는다."""
        target = Path(path).resolve()
        if not target.exists():
            return HarnessDecisionStoreModel(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                decisions=[],
            )
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        decisions: list[HarnessDecision] = []
        for item in payload.get("decisions", []) or []:
            if not isinstance(item, dict):
                continue
            decisions.append(
                HarnessDecision(
                    decision_id=str(item.get("decision_id", "")),
                    suggestion_id=str(item.get("suggestion_id", "")),
                    created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at")) if item.get("updated_at") is not None else None,
                    status=str(item.get("status", "accepted")),
                    kind=str(item.get("kind", "")),
                    target=str(item.get("target")) if item.get("target") is not None else None,
                    title=str(item.get("title", "")),
                    summary=str(item.get("summary", "")),
                    resolution=str(item.get("resolution")) if item.get("resolution") is not None else None,
                    source_report_ref=str(item.get("source_report_ref")) if item.get("source_report_ref") is not None else None,
                    evidence_refs=[str(ref) for ref in item.get("evidence_refs", []) if ref],
                    operational_effect=dict(item.get("operational_effect", {}))
                    if isinstance(item.get("operational_effect"), dict)
                    else {},
                    tags=[str(tag) for tag in item.get("tags", []) if tag],
                    warnings=[str(warning) for warning in item.get("warnings", []) if warning],
                    errors=[str(error) for error in item.get("errors", []) if error],
                )
            )
        return HarnessDecisionStoreModel(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            decisions=decisions,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, model: HarnessDecisionStoreModel, path: Path) -> Path:
        """결정 모델을 YAML로 저장한다."""
        target = Path(path).resolve()
        model.updated_at = _now()
        _atomic_write_text(
            target,
            yaml.safe_dump(model.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def add(self, path: Path, decision: HarnessDecision) -> Path:
        """결정을 추가하거나 같은 suggestion id 결정을 갱신한다."""
        model = self.load(path)
        replaced = False
        for index, current in enumerate(model.decisions):
            if current.suggestion_id != decision.suggestion_id:
                continue
            decision.created_at = current.created_at or decision.created_at
            decision.updated_at = _now()
            model.decisions[index] = decision
            replaced = True
            break
        if not replaced:
            model.decisions.append(decision)
        return self.save(model, path)


def load_latest_harness_suggestion(
    project_root: Path,
    suggestion_id: str,
) -> tuple["HarnessEvolutionReport", "HarnessSuggestion", Path]:
    """가장 최근 suggestion 보고서에서 suggestion id를 찾는다."""
    from engine.project_harness_evolution import (
        HarnessEvolutionStore,
        default_harness_evolution_path,
        default_request_harness_evolution_path,
    )

    root = Path(project_root).resolve()
    candidates = [
        path
        for path in [default_harness_evolution_path(root), default_request_harness_evolution_path(root)]
        if path.exists()
    ]
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    store = HarnessEvolutionStore()
    for path in candidates:
        report = store.load(path)
        for suggestion in report.suggestions:
            if suggestion.suggestion_id == suggestion_id:
                return report, suggestion, path
    raise KeyError(suggestion_id)


def apply_operational_harness_suggestion(project_root: Path, suggestion: "HarnessSuggestion") -> dict:
    """운영형 suggestion을 안전한 범위에서 반영한다."""
    root = Path(project_root).resolve()
    target = str(suggestion.target or "").strip()
    effect: dict = {"type": "none", "applied": False, "details": {}}
    if suggestion.kind not in _OPERATIONAL_KINDS:
        return effect
    if suggestion.kind == "keep_agent":
        return {"type": "keep", "applied": False, "details": {"target": target}}
    if not target:
        raise ValueError("operational suggestion target is missing")

    profile_path = default_harness_profile_path(root)
    registry_path = default_agent_registry_path(root)
    if not profile_path.exists() or not registry_path.exists():
        raise FileNotFoundError("harness profile or agent registry not found")

    profile_store = HarnessProfileStore()
    registry_store = AgentRegistryStore()
    profile = profile_store.load(profile_path)
    registry = AgentRegistryBuilder().build(root, harness=profile)

    if suggestion.kind == "hire_agent":
        registry, profile = AgentRegistryBuilder.equip(registry, profile, target)
        update_imported_agent_local_status(root, target, "equipped")
        effect = {
            "type": "hire",
            "applied": True,
            "details": {"agent_id": target, "active_agents": list(profile.active_agents)},
        }
    elif suggestion.kind == "fire_agent":
        registry, profile = AgentRegistryBuilder.unequip(registry, profile, target)
        update_imported_agent_local_status(root, target, "imported")
        effect = {
            "type": "fire",
            "applied": True,
            "details": {"agent_id": target, "active_agents": list(profile.active_agents)},
        }
    registry_store.save(registry, registry_path)
    profile_store.save(profile, profile_path)
    return effect


def build_harness_decision(
    project_root: Path,
    suggestion: "HarnessSuggestion",
    *,
    status: str,
    resolution: str | None = None,
    source_report_ref: str | None = None,
) -> HarnessDecision:
    """suggestion에서 HarnessDecision 객체를 만든다."""
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in _VALID_DECISION_STATUS:
        raise ValueError(f"invalid harness decision status: {status}")

    root = Path(project_root).resolve()
    operational_effect = {"type": "none", "applied": False, "details": {}}
    warnings: list[str] = []
    if normalized_status == "accepted":
        try:
            operational_effect = apply_operational_harness_suggestion(root, suggestion)
        except FileNotFoundError:
            warnings.append("operational effect skipped because harness profile or agent registry is missing")
        except KeyError as exc:
            raise ValueError(f"operational suggestion target not found: {exc.args[0]}") from exc
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    return HarnessDecision(
        decision_id=_decision_id(suggestion.suggestion_id),
        suggestion_id=suggestion.suggestion_id,
        created_at=_now(),
        updated_at=None,
        status=normalized_status,
        kind=suggestion.kind,
        target=suggestion.target,
        title=suggestion.title,
        summary=suggestion.summary,
        resolution=str(resolution).strip() if resolution else None,
        source_report_ref=source_report_ref,
        evidence_refs=list(suggestion.evidence_refs),
        operational_effect=operational_effect,
        tags=[suggestion.kind, normalized_status],
        warnings=_dedupe([*warnings, *suggestion.warnings]),
        errors=[],
    )


def summarize_harness_decisions(model: HarnessDecisionStoreModel) -> dict:
    """결정 요약 dict를 만든다."""
    accepted = [item for item in model.decisions if item.status == "accepted"]
    dismissed = [item for item in model.decisions if item.status == "dismissed"]
    accepted_summaries = [item.summary for item in accepted if item.summary]
    strategic = [
        item.summary
        for item in accepted
        if item.kind not in {"hire_agent", "fire_agent", "keep_agent"} and item.summary
    ]
    return {
        "accepted": len(accepted),
        "dismissed": len(dismissed),
        "accepted_summaries": accepted_summaries[:3],
        "accepted_strategic": strategic[:3],
        "latest": accepted_summaries[0] if accepted_summaries else None,
    }


def render_harness_decisions(
    model: HarnessDecisionStoreModel,
    *,
    status: str | None = None,
) -> str:
    """하네스 결정 목록을 사람용 텍스트로 렌더링한다."""
    items = [
        item
        for item in model.decisions
        if status is None or item.status == status
    ]
    lines = [
        "Harness Decisions",
        "==================================================",
    ]
    accepted = [item for item in items if item.status == "accepted"]
    dismissed = [item for item in items if item.status == "dismissed"]
    lines.extend(["", "Accepted:"])
    if accepted:
        for index, item in enumerate(accepted, start=1):
            lines.append(f"  {index}. {item.summary}")
    else:
        lines.append("  none")
    lines.extend(["", "Dismissed:"])
    if dismissed:
        for index, item in enumerate(dismissed, start=1):
            lines.append(f"  {index}. {item.summary}")
    else:
        lines.append("  none")
    return "\n".join(lines)


def render_harness_decision_summary(model: HarnessDecisionStoreModel) -> str:
    """show/status에 붙일 compact decision 요약을 렌더링한다."""
    summary = summarize_harness_decisions(model)
    lines = [
        "Harness decisions:",
        f"  accepted : {int(summary.get('accepted', 0) or 0)}",
        f"  dismissed: {int(summary.get('dismissed', 0) or 0)}",
    ]
    accepted_strategic = list(summary.get("accepted_strategic", [])) if isinstance(summary.get("accepted_strategic"), list) else []
    if accepted_strategic:
        lines.extend(["", "Accepted harness hints:"])
        for item in accepted_strategic[:3]:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def load_harness_decision_summary(project_root: Path) -> dict:
    """프로젝트의 결정 요약을 로드한다."""
    model = HarnessDecisionStore().load(default_harness_decisions_path(project_root))
    return summarize_harness_decisions(model)
