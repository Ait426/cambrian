"""프로젝트 team staffing decision 저장소."""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_team_trials import TeamTrialStore, default_team_trials_dir
from engine.project_teams import (
    TeamPreset,
    TeamPresetStore,
    apply_team_preset,
    default_team_presets_path,
)

SCHEMA_VERSION = "1.0.0"
DECISION_KINDS = {"apply_team", "keep_team", "keep_as_backup", "watch_team", "dismiss_team"}
ACCEPT_DECISION_KINDS = {"apply_team", "keep_team", "keep_as_backup", "watch_team"}


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


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


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


def default_team_decisions_path(project_root: Path) -> Path:
    """team decision 기본 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "team_decisions.yaml"


@dataclass
class TeamDecision:
    """사용자가 명시적으로 내린 team staffing decision."""

    decision_id: str
    created_at: str
    updated_at: str | None
    status: str
    decision_kind: str
    target_team_id: str
    target_team_name: str | None
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
class TeamDecisionStoreModel:
    """team decision YAML 모델."""

    schema_version: str
    updated_at: str
    active_decision_team_id: str | None
    decisions: list[TeamDecision]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "active_decision_team_id": self.active_decision_team_id,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TeamDecisionStore:
    """team decision 저장소."""

    def load(self, path: Path) -> TeamDecisionStoreModel:
        """저장된 team decision 모델을 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return TeamDecisionStoreModel(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                active_decision_team_id=None,
                decisions=[],
            )
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        decisions: list[TeamDecision] = []
        for item in payload.get("decisions", []) or []:
            if not isinstance(item, dict):
                continue
            decisions.append(
                TeamDecision(
                    decision_id=str(item.get("decision_id", "")),
                    created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at")) if item.get("updated_at") is not None else None,
                    status=str(item.get("status", "")),
                    decision_kind=str(item.get("decision_kind", "")),
                    target_team_id=str(item.get("target_team_id", "")),
                    target_team_name=str(item.get("target_team_name")) if item.get("target_team_name") is not None else None,
                    title=str(item.get("title", "")),
                    summary=str(item.get("summary", "")),
                    resolution=str(item.get("resolution")) if item.get("resolution") is not None else None,
                    source_ref=str(item.get("source_ref")) if item.get("source_ref") is not None else None,
                    source_type=str(item.get("source_type")) if item.get("source_type") is not None else None,
                    evidence_refs=[str(value) for value in item.get("evidence_refs", []) if value],
                    operational_effect=dict(item.get("operational_effect", {}) if isinstance(item.get("operational_effect"), dict) else {}),
                    warnings=[str(value) for value in item.get("warnings", []) if value],
                    errors=[str(value) for value in item.get("errors", []) if value],
                )
            )
        return TeamDecisionStoreModel(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            active_decision_team_id=str(payload.get("active_decision_team_id")) if payload.get("active_decision_team_id") is not None else None,
            decisions=decisions,
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )

    def save(self, model: TeamDecisionStoreModel, path: Path) -> Path:
        """team decision 모델을 YAML로 저장한다."""
        target = Path(path).resolve()
        model.updated_at = _now()
        _atomic_write_text(target, yaml.safe_dump(model.to_dict(), allow_unicode=True, sort_keys=False))
        return target

    def add(self, path: Path, decision: TeamDecision) -> Path:
        """decision을 append하고 필요하면 active decision team을 갱신한다."""
        model = self.load(path)
        model.decisions.append(decision)
        if decision.status == "accepted" and decision.decision_kind in {"apply_team", "keep_team"}:
            model.active_decision_team_id = decision.target_team_id
        return self.save(model, path)


class TeamDecisionManager:
    """team recommendation/trial을 명시적 운영 결정으로 연결한다."""

    def accept(
        self,
        project_root: Path,
        team_name: str,
        decision_kind: str,
        *,
        source_ref: str | None = None,
        resolution: str | None = None,
    ) -> tuple[TeamDecision, Path]:
        """team decision을 accepted 상태로 저장하고 필요한 safe effect를 적용한다."""
        kind = str(decision_kind or "keep_team").strip()
        if kind not in ACCEPT_DECISION_KINDS:
            raise ValueError(f"unsupported team decision: {kind}")
        root, team = self._load_team(project_root, team_name)
        source_type, source_path, evidence_refs, warnings = _find_source(root, team, source_ref)
        operational_effect: dict[str, Any] = {"type": "none", "applied": False, "details": {}}
        if kind == "apply_team":
            try:
                applied_team, model, apply_warnings = apply_team_preset(root, team.name)
            except KeyError as exc:
                raise ValueError(f"missing team member agent: {exc.args[0]}") from exc
            team = applied_team
            operational_effect = {
                "type": "apply_team",
                "applied": True,
                "details": {
                    "active_team_id": model.active_team_id,
                    "warnings": list(apply_warnings),
                },
            }
            warnings.extend(apply_warnings)
        decision = _build_decision(
            status="accepted",
            decision_kind=kind,
            team=team,
            source_type=source_type,
            source_ref=source_path,
            evidence_refs=evidence_refs,
            operational_effect=operational_effect,
            resolution=resolution,
            warnings=warnings,
        )
        path = default_team_decisions_path(root)
        TeamDecisionStore().add(path, decision)
        return decision, path

    def dismiss(
        self,
        project_root: Path,
        team_name: str,
        *,
        source_ref: str | None = None,
        resolution: str | None = None,
    ) -> tuple[TeamDecision, Path]:
        """team recommendation을 dismissed decision으로 저장한다."""
        root, team = self._load_team(project_root, team_name)
        source_type, source_path, evidence_refs, warnings = _find_source(root, team, source_ref)
        decision = _build_decision(
            status="dismissed",
            decision_kind="dismiss_team",
            team=team,
            source_type=source_type,
            source_ref=source_path,
            evidence_refs=evidence_refs,
            operational_effect={"type": "none", "applied": False, "details": {}},
            resolution=resolution,
            warnings=warnings,
        )
        path = default_team_decisions_path(root)
        TeamDecisionStore().add(path, decision)
        return decision, path

    @staticmethod
    def _load_team(project_root: Path, team_name: str) -> tuple[Path, TeamPreset]:
        root = Path(project_root).resolve()
        model = TeamPresetStore().load(default_team_presets_path(root))
        return root, TeamPresetStore().find(model, team_name)


def _build_decision(
    *,
    status: str,
    decision_kind: str,
    team: TeamPreset,
    source_type: str | None,
    source_ref: str | None,
    evidence_refs: list[str],
    operational_effect: dict[str, Any],
    resolution: str | None,
    warnings: list[str],
) -> TeamDecision:
    title = f"{decision_kind} {team.name}"
    summary = _decision_summary(status, decision_kind, team)
    return TeamDecision(
        decision_id=f"team-decision-{uuid.uuid4().hex[:8]}",
        created_at=_now(),
        updated_at=None,
        status=status,
        decision_kind=decision_kind,
        target_team_id=team.team_id,
        target_team_name=team.name,
        title=title,
        summary=summary,
        resolution=str(resolution).strip() if resolution else None,
        source_ref=source_ref,
        source_type=source_type,
        evidence_refs=_dedupe(evidence_refs),
        operational_effect=dict(operational_effect),
        warnings=_dedupe(warnings),
        errors=[],
    )


def _decision_summary(status: str, decision_kind: str, team: TeamPreset) -> str:
    if status == "dismissed":
        return f"{team.name} was dismissed as a team recommendation."
    if decision_kind == "apply_team":
        return f"{team.name} was accepted and applied as the active team."
    if decision_kind == "keep_team":
        return f"{team.name} was accepted as a team to keep for this harness."
    if decision_kind == "keep_as_backup":
        return f"{team.name} was accepted as a backup team."
    if decision_kind == "watch_team":
        return f"{team.name} was accepted as a team to watch."
    return f"{team.name} decision recorded."


def _find_source(root: Path, team: TeamPreset, source_ref: str | None) -> tuple[str | None, str | None, list[str], list[str]]:
    warnings: list[str] = []
    if source_ref:
        source_path = Path(source_ref)
        resolved = source_path if source_path.is_absolute() else root / source_path
        source_type = "team_trial" if "team_trials" in resolved.parts else "standalone"
        return source_type, _relative_to_project(resolved, root), [_relative_to_project(resolved, root)], warnings
    trial_path = _latest_team_trial_for_team(root, team)
    if trial_path is not None:
        rel = _relative_to_project(trial_path, root)
        return "team_trial", rel, [rel], warnings
    warnings.append("no team trial or recommendation artifact found; recorded as standalone decision")
    return "standalone", None, [], warnings


def _latest_team_trial_for_team(root: Path, team: TeamPreset) -> Path | None:
    trials_dir = default_team_trials_dir(root)
    candidates = sorted(trials_dir.glob("team_trial_*.yaml"), key=lambda path: path.stat().st_mtime, reverse=True)
    store = TeamTrialStore()
    for candidate in candidates:
        try:
            report = store.load(candidate)
        except Exception:
            continue
        if report.shadow_team_id == team.team_id or report.current_team_id == team.team_id:
            return candidate
    return None


def load_team_decision_summary(project_root: Path, team_id: str | None = None) -> dict[str, Any]:
    """status/team show용 team decision 요약을 반환한다."""
    model = TeamDecisionStore().load(default_team_decisions_path(project_root))
    decisions = [
        decision
        for decision in model.decisions
        if team_id is None or decision.target_team_id == team_id or decision.target_team_name == team_id
    ]
    accepted = [decision for decision in decisions if decision.status == "accepted"]
    dismissed = [decision for decision in decisions if decision.status == "dismissed"]
    accepted_hints = [decision.summary for decision in accepted[-3:]]
    return {
        "accepted": len(accepted),
        "dismissed": len(dismissed),
        "active_decision_team_id": model.active_decision_team_id,
        "accepted_hints": accepted_hints,
        "backup_teams": [decision.target_team_name or decision.target_team_id for decision in accepted if decision.decision_kind == "keep_as_backup"],
        "watch_teams": [decision.target_team_name or decision.target_team_id for decision in accepted if decision.decision_kind == "watch_team"],
        "decisions": [decision.to_dict() for decision in decisions],
    }


def team_decision_reason(team_id: str, summary: dict[str, Any]) -> str | None:
    """추천/표시용으로 team decision 요약 문장을 반환한다."""
    decisions = [
        item
        for item in summary.get("decisions", [])
        if isinstance(item, dict) and item.get("target_team_id") == team_id
    ]
    if not decisions:
        return None
    latest = decisions[-1]
    status = str(latest.get("status", ""))
    kind = str(latest.get("decision_kind", ""))
    if status == "accepted":
        if kind == "apply_team":
            return "previously accepted as the active team"
        if kind == "keep_as_backup":
            return "previously accepted as a backup team"
        if kind == "watch_team":
            return "previously accepted as a watched team"
        if kind == "keep_team":
            return "previously accepted as a team to keep"
    if status == "dismissed":
        return "previously dismissed as a team recommendation"
    return None


def render_team_decisions(model: TeamDecisionStoreModel, status_filter: str | None = None) -> str:
    """team decisions 목록을 사람이 읽기 좋게 렌더링한다."""
    decisions = [
        decision
        for decision in model.decisions
        if status_filter is None or decision.status == status_filter
    ]
    accepted = [decision for decision in decisions if decision.status == "accepted"]
    dismissed = [decision for decision in decisions if decision.status == "dismissed"]
    lines = ["Team Decisions", "==================================================", "", "Accepted:"]
    if not accepted:
        lines.append("  none")
    for index, decision in enumerate(accepted, start=1):
        lines.append(f"  {index}. {decision.decision_kind} {decision.target_team_name or decision.target_team_id}")
    lines.extend(["", "Dismissed:"])
    if not dismissed:
        lines.append("  none")
    for index, decision in enumerate(dismissed, start=1):
        lines.append(f"  {index}. {decision.decision_kind} {decision.target_team_name or decision.target_team_id}")
    return "\n".join(lines)


def render_team_decision_result(decision: TeamDecision, path: Path) -> str:
    """accept/dismiss 결과를 사람이 읽기 좋게 렌더링한다."""
    heading = "Team decision accepted." if decision.status == "accepted" else "Team decision dismissed."
    lines = [
        heading,
        "",
        "Team:",
        f"  {decision.target_team_name or decision.target_team_id}",
        "",
        "Decision:",
        f"  {decision.decision_kind}",
    ]
    if decision.resolution:
        lines.extend(["", "Reason:", f"  {decision.resolution}"])
    if decision.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in decision.warnings])
    lines.extend(["", "Recorded:", f"  {path}"])
    return "\n".join(lines)
