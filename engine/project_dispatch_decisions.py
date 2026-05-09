"""Agent staffing decision 저장소."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_agent_transfer import update_imported_agent_local_status
from engine.project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from engine.project_dispatch import DispatchBoardStore, default_dispatch_board_path
from engine.project_harness import HarnessProfileStore, default_harness_profile_path

SCHEMA_VERSION = "1.0.0"
VALID_DECISION_STATUS = {"accepted", "dismissed"}
VALID_DECISION_KINDS = {
    "hire",
    "fire",
    "keep",
    "prefer_lead",
    "prefer_support",
    "keep_as_backup",
    "watch_candidate",
}
OPERATIONAL_KINDS = {"hire", "fire"}


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _decision_id(agent_id: str, decision_kind: str) -> str:
    """agent와 decision kind 기반의 decision id를 만든다."""
    token = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_agent = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in agent_id).strip("-")
    return f"staffing-{token}-{decision_kind}-{safe_agent}"


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


def default_staffing_decisions_path(project_root: Path) -> Path:
    """staffing decisions 기본 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "staffing_decisions.yaml"


@dataclass
class StaffingDecision:
    """사용자가 명시적으로 내린 agent staffing 결정."""

    decision_id: str
    created_at: str
    updated_at: str | None
    status: str
    decision_kind: str
    target_agent_id: str
    source_kind: str | None
    title: str
    summary: str
    resolution: str | None
    source_ref: str | None
    source_type: str | None
    evidence_refs: list[str]
    operational_effect: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class StaffingDecisionStoreModel:
    """staffing decision 파일 모델."""

    schema_version: str
    updated_at: str
    decisions: list[StaffingDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class StaffingDecisionStore:
    """staffing decision YAML 저장소."""

    def load(self, path: Path) -> StaffingDecisionStoreModel:
        """저장된 decision 모델을 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return StaffingDecisionStoreModel(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                decisions=[],
            )
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        decisions: list[StaffingDecision] = []
        for item in payload.get("decisions", []) or []:
            if not isinstance(item, dict):
                continue
            decisions.append(
                StaffingDecision(
                    decision_id=str(item.get("decision_id", "")),
                    created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at")) if item.get("updated_at") is not None else None,
                    status=str(item.get("status", "accepted")),
                    decision_kind=str(item.get("decision_kind", "")),
                    target_agent_id=str(item.get("target_agent_id", "")),
                    source_kind=str(item.get("source_kind")) if item.get("source_kind") is not None else None,
                    title=str(item.get("title", "")),
                    summary=str(item.get("summary", "")),
                    resolution=str(item.get("resolution")) if item.get("resolution") is not None else None,
                    source_ref=str(item.get("source_ref")) if item.get("source_ref") is not None else None,
                    source_type=str(item.get("source_type")) if item.get("source_type") is not None else None,
                    evidence_refs=[str(ref) for ref in item.get("evidence_refs", []) if ref],
                    operational_effect=dict(item.get("operational_effect", {}))
                    if isinstance(item.get("operational_effect"), dict)
                    else {},
                    warnings=[str(warning) for warning in item.get("warnings", []) if warning],
                    errors=[str(error) for error in item.get("errors", []) if error],
                )
            )
        return StaffingDecisionStoreModel(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            decisions=decisions,
            warnings=[str(warning) for warning in payload.get("warnings", []) if warning],
            errors=[str(error) for error in payload.get("errors", []) if error],
        )

    def save(self, model: StaffingDecisionStoreModel, path: Path) -> Path:
        """decision 모델을 YAML로 저장한다."""
        target = Path(path).resolve()
        model.updated_at = _now()
        _atomic_write_text(
            target,
            yaml.safe_dump(model.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def add(self, path: Path, decision: StaffingDecision) -> Path:
        """새 decision을 추가한다."""
        model = self.load(path)
        model.decisions.append(decision)
        return self.save(model, path)


def _load_agent(project_root: Path, agent_id: str) -> tuple[Any, Any, Any]:
    """현재 registry/harness에서 agent를 찾는다."""
    root = Path(project_root).resolve()
    profile_path = default_harness_profile_path(root)
    registry_path = default_agent_registry_path(root)
    if not profile_path.exists() or not registry_path.exists():
        raise FileNotFoundError("harness profile or agent registry not found")
    profile_store = HarnessProfileStore()
    registry_store = AgentRegistryStore()
    profile = profile_store.load(profile_path)
    registry = AgentRegistryBuilder().build(root, harness=profile)
    for agent in registry.agents:
        if agent.agent_id == agent_id:
            return profile, registry, agent
    raise KeyError(agent_id)


def _source_from_path(project_root: Path, path: Path, agent_id: str) -> dict[str, Any]:
    """명시적 source path에서 provenance를 추출한다."""
    root = Path(project_root).resolve()
    resolved = path if path.is_absolute() else root / path
    if not resolved.exists():
        return {
            "source_ref": _relative_to_project(resolved, root),
            "source_type": None,
            "evidence_refs": [],
            "warnings": [f"source report not found: {_relative_to_project(resolved, root)}"],
        }
    source_type = "staffing_source"
    if resolved.name == "dispatch_board.yaml":
        source_type = "dispatch_board"
    elif resolved.parent.name == "trials":
        source_type = "agent_trial"
    elif resolved.parent.name == "interviews":
        source_type = "agent_compare"
    return {
        "source_ref": _relative_to_project(resolved, root),
        "source_type": source_type,
        "evidence_refs": [_relative_to_project(resolved, root)],
        "warnings": [],
    }


def find_staffing_source(project_root: Path, agent_id: str, source_ref: str | None = None) -> dict[str, Any]:
    """dispatch board, compare, trial 중 최신 provenance를 찾는다."""
    root = Path(project_root).resolve()
    if source_ref:
        return _source_from_path(root, Path(source_ref), agent_id)

    board_path = default_dispatch_board_path(root)
    if board_path.exists():
        try:
            board = DispatchBoardStore().load(board_path)
            for candidate in board.candidates:
                if candidate.agent_id == agent_id:
                    return {
                        "source_ref": _relative_to_project(board_path, root),
                        "source_type": "dispatch_board",
                        "evidence_refs": [_relative_to_project(board_path, root)],
                        "warnings": [],
                        "candidate_recommendation": candidate.recommendation,
                    }
        except Exception as exc:
            return {
                "source_ref": _relative_to_project(board_path, root),
                "source_type": "dispatch_board",
                "evidence_refs": [_relative_to_project(board_path, root)],
                "warnings": [f"dispatch board source read failed: {exc}"],
            }

    interview_dir = root / ".cambrian" / "agents" / "interviews"
    interview_paths = sorted(interview_dir.glob("interview_*.y*ml"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in interview_paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        candidates = payload.get("candidates", []) if isinstance(payload.get("candidates"), list) else []
        if any(isinstance(item, dict) and item.get("agent_id") == agent_id for item in candidates):
            return {
                "source_ref": _relative_to_project(path, root),
                "source_type": "agent_compare",
                "evidence_refs": [_relative_to_project(path, root)],
                "warnings": [],
            }

    trial_dir = root / ".cambrian" / "agents" / "trials"
    trial_paths = sorted(trial_dir.glob("trial_*.y*ml"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in trial_paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if payload.get("shadow_agent_id") == agent_id or payload.get("current_lead_agent_id") == agent_id:
            return {
                "source_ref": _relative_to_project(path, root),
                "source_type": "agent_trial",
                "evidence_refs": [_relative_to_project(path, root)],
                "warnings": [],
            }

    return {
        "source_ref": None,
        "source_type": None,
        "evidence_refs": [],
        "warnings": ["no dispatch board, compare, or trial source found for this agent"],
    }


def apply_staffing_operational_effect(project_root: Path, agent_id: str, decision_kind: str) -> tuple[dict[str, Any], list[str]]:
    """hire/fire decision의 안전한 운영 효과를 적용한다."""
    root = Path(project_root).resolve()
    profile_path = default_harness_profile_path(root)
    registry_path = default_agent_registry_path(root)
    profile, registry, agent = _load_agent(root, agent_id)
    profile_store = HarnessProfileStore()
    registry_store = AgentRegistryStore()
    warnings: list[str] = []

    if decision_kind == "hire":
        compatibility_status = str(agent.stats.get("compatibility_status", "")) if isinstance(agent.stats, dict) else ""
        if agent.source_kind == "imported" and compatibility_status == "blocked":
            raise ValueError(f"imported agent compatibility is blocked: {agent_id}")
        if agent.status == "equipped":
            return {"type": "hire", "applied": False, "details": {"agent_id": agent_id, "status": "already_equipped"}}, warnings
        registry, profile = AgentRegistryBuilder.equip(registry, profile, agent_id)
        update_imported_agent_local_status(root, agent_id, "equipped")
        effect = {
            "type": "hire",
            "applied": True,
            "details": {"agent_id": agent_id, "active_agents": list(profile.active_agents)},
        }
    elif decision_kind == "fire":
        if agent.status != "equipped":
            warnings.append("fire decision accepted for a non-equipped agent; no operational change applied")
            return {"type": "fire", "applied": False, "details": {"agent_id": agent_id, "status": "not_equipped"}}, warnings
        registry, profile = AgentRegistryBuilder.unequip(registry, profile, agent_id)
        update_imported_agent_local_status(root, agent_id, "imported")
        effect = {
            "type": "fire",
            "applied": True,
            "details": {"agent_id": agent_id, "active_agents": list(profile.active_agents)},
        }
    else:
        return {"type": "none", "applied": False, "details": {"agent_id": agent_id}}, warnings

    registry_store.save(registry, registry_path)
    profile_store.save(profile, profile_path)
    return effect, warnings


def build_staffing_decision(
    project_root: Path,
    agent_id: str,
    *,
    status: str,
    decision_kind: str,
    resolution: str | None = None,
    source_ref: str | None = None,
) -> StaffingDecision:
    """CLI 입력에서 staffing decision을 만든다."""
    root = Path(project_root).resolve()
    normalized_status = str(status or "").strip().lower()
    normalized_kind = str(decision_kind or "").strip().lower()
    if normalized_status not in VALID_DECISION_STATUS:
        raise ValueError(f"invalid staffing decision status: {status}")
    if normalized_kind not in VALID_DECISION_KINDS:
        raise ValueError(f"invalid staffing decision kind: {decision_kind}")
    _profile, _registry, agent = _load_agent(root, agent_id)
    source = find_staffing_source(root, agent_id, source_ref=source_ref)
    operational_effect: dict[str, Any] = {"type": "none", "applied": False, "details": {"agent_id": agent_id}}
    warnings = list(source.get("warnings", []))
    if normalized_status == "accepted" and normalized_kind in OPERATIONAL_KINDS:
        effect, effect_warnings = apply_staffing_operational_effect(root, agent_id, normalized_kind)
        operational_effect = effect
        warnings.extend(effect_warnings)
    title = f"{normalized_kind} {agent_id}"
    summary = f"{normalized_kind} {agent_id}"
    if normalized_status == "dismissed":
        summary = f"dismiss {normalized_kind} {agent_id}"
    return StaffingDecision(
        decision_id=_decision_id(agent_id, normalized_kind),
        created_at=_now(),
        updated_at=None,
        status=normalized_status,
        decision_kind=normalized_kind,
        target_agent_id=agent_id,
        source_kind=agent.source_kind,
        title=title,
        summary=summary,
        resolution=str(resolution).strip() if resolution else None,
        source_ref=source.get("source_ref"),
        source_type=source.get("source_type"),
        evidence_refs=[str(ref) for ref in source.get("evidence_refs", []) if ref],
        operational_effect=operational_effect,
        warnings=_dedupe(warnings),
        errors=[],
    )


def summarize_staffing_decisions(model: StaffingDecisionStoreModel, agent_id: str | None = None) -> dict[str, Any]:
    """staffing decisions 요약을 만든다."""
    decisions = [item for item in model.decisions if agent_id is None or item.target_agent_id == agent_id]
    accepted = [item for item in decisions if item.status == "accepted"]
    dismissed = [item for item in decisions if item.status == "dismissed"]
    accepted_hints = [item.summary for item in accepted if item.decision_kind not in OPERATIONAL_KINDS and item.summary]
    return {
        "accepted": len(accepted),
        "dismissed": len(dismissed),
        "accepted_hints": accepted_hints[:3],
        "latest": accepted[-1].summary if accepted else None,
        "decisions": [item.to_dict() for item in decisions[-5:]],
    }


def load_staffing_decision_summary(project_root: Path, agent_id: str | None = None) -> dict[str, Any]:
    """프로젝트 staffing decision 요약을 로드한다."""
    model = StaffingDecisionStore().load(default_staffing_decisions_path(project_root))
    return summarize_staffing_decisions(model, agent_id=agent_id)


def render_staffing_decisions(model: StaffingDecisionStoreModel, *, status: str | None = None) -> str:
    """staffing decision 목록을 사람이 읽기 좋게 렌더링한다."""
    items = [item for item in model.decisions if status is None or item.status == status]
    accepted = [item for item in items if item.status == "accepted"]
    dismissed = [item for item in items if item.status == "dismissed"]
    lines = [
        "Staffing Decisions",
        "==================================================",
        "",
        "Accepted:",
    ]
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


def render_staffing_decision_result(decision: StaffingDecision, saved_path: Path) -> str:
    """accept/dismiss 결과를 렌더링한다."""
    action = "accepted" if decision.status == "accepted" else "dismissed"
    lines = [
        f"Staffing decision {action}.",
        "",
        "Decision:",
        f"  {decision.summary}",
        "",
        "Recorded:",
        f"  {saved_path}",
    ]
    if decision.source_ref:
        lines.extend(["", "Source:", f"  {decision.source_type or 'unknown'}: {decision.source_ref}"])
    effect = decision.operational_effect if isinstance(decision.operational_effect, dict) else {}
    if effect.get("type") and effect.get("type") != "none":
        lines.extend(["", "Operational effect:", f"  {effect.get('type')}: {'applied' if effect.get('applied') else 'not applied'}"])
    if decision.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in decision.warnings])
    return "\n".join(lines)
