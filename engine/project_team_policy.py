"""accepted team decision 기반 team policy overlay."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_harness import HarnessProfileStore, default_harness_profile_path
from engine.project_team_decisions import TeamDecision, TeamDecisionStore, default_team_decisions_path
from engine.project_teams import TeamPreset, TeamPresetStore, default_team_presets_path

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
    """프로젝트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_team_policy_overlay_path(project_root: Path) -> Path:
    """team policy overlay 기본 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "team_policy_overlay.yaml"


@dataclass
class TeamPolicyDecision:
    """overlay에 반영된 accepted team decision 요약."""

    decision_id: str
    decision_kind: str
    target_team_id: str | None
    target_team_name: str | None
    title: str
    summary: str
    source_ref: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class TeamPolicyOverlay:
    """현재 프로젝트의 accepted team policy snapshot."""

    schema_version: str
    generated_at: str
    project_name: str | None
    harness_id: str | None
    current_team_id: str | None = None
    current_team_name: str | None = None
    kept_teams: list[str] = field(default_factory=list)
    backup_teams: list[str] = field(default_factory=list)
    watched_teams: list[str] = field(default_factory=list)
    accepted_decisions: list[TeamPolicyDecision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "project_name": self.project_name,
            "harness_id": self.harness_id,
            "current_team_id": self.current_team_id,
            "current_team_name": self.current_team_name,
            "kept_teams": list(self.kept_teams),
            "backup_teams": list(self.backup_teams),
            "watched_teams": list(self.watched_teams),
            "accepted_decisions": [decision.to_dict() for decision in self.accepted_decisions],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TeamPolicyOverlayBuilder:
    """team_decisions.yaml을 안전한 policy overlay로 변환한다."""

    def build(self, project_root: Path) -> TeamPolicyOverlay:
        """accepted team decisions로 overlay를 만든다."""
        root = Path(project_root).resolve()
        project_name: str | None = root.name
        harness_id: str | None = None
        warnings: list[str] = []
        harness_path = default_harness_profile_path(root)
        if harness_path.exists():
            try:
                harness = HarnessProfileStore().load(harness_path)
                project_name = harness.project_name
                harness_id = harness.harness_id
            except Exception as exc:
                warnings.append(f"harness profile load failed: {exc}")

        overlay = TeamPolicyOverlay(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            project_name=project_name,
            harness_id=harness_id,
            warnings=warnings,
        )
        team_model = TeamPresetStore().load(default_team_presets_path(root))
        teams_by_id = {team.team_id: team for team in team_model.teams}
        teams_by_name = {team.name: team for team in team_model.teams}
        decision_model = TeamDecisionStore().load(default_team_decisions_path(root))
        for decision in decision_model.decisions:
            if decision.status != "accepted":
                continue
            team = teams_by_id.get(decision.target_team_id)
            if team is None and decision.target_team_name:
                team = teams_by_name.get(decision.target_team_name)
            if team is None:
                overlay.warnings.append(f"team decision references missing team: {decision.target_team_id or decision.target_team_name}")
                continue
            self._apply_decision(overlay, team_model.active_team_id, team, decision)
        overlay.kept_teams = _dedupe(overlay.kept_teams)
        overlay.backup_teams = _dedupe(overlay.backup_teams)
        overlay.watched_teams = _dedupe(overlay.watched_teams)
        return overlay

    @staticmethod
    def _apply_decision(
        overlay: TeamPolicyOverlay,
        active_team_id: str | None,
        team: TeamPreset,
        decision: TeamDecision,
    ) -> None:
        overlay.accepted_decisions.append(
            TeamPolicyDecision(
                decision_id=decision.decision_id,
                decision_kind=decision.decision_kind,
                target_team_id=team.team_id,
                target_team_name=team.name,
                title=decision.title,
                summary=decision.summary,
                source_ref=decision.source_ref,
                warnings=list(decision.warnings),
            )
        )
        if decision.decision_kind == "apply_team":
            if active_team_id == team.team_id:
                overlay.current_team_id = team.team_id
                overlay.current_team_name = team.name
            else:
                overlay.warnings.append(f"accepted apply_team is not currently active: {team.name}")
        elif decision.decision_kind == "keep_team":
            overlay.kept_teams.append(team.name)
        elif decision.decision_kind == "keep_as_backup":
            overlay.backup_teams.append(team.name)
        elif decision.decision_kind == "watch_team":
            overlay.watched_teams.append(team.name)


class TeamPolicyStore:
    """team policy overlay 저장소."""

    def save(self, overlay: TeamPolicyOverlay, path: Path) -> Path:
        """overlay를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(target, yaml.safe_dump(overlay.to_dict(), allow_unicode=True, sort_keys=False))
        return target

    def load(self, path: Path) -> TeamPolicyOverlay:
        """저장된 overlay를 로드한다."""
        payload = yaml.safe_load(Path(path).resolve().read_text(encoding="utf-8")) or {}
        decisions = [
            TeamPolicyDecision(
                decision_id=str(item.get("decision_id", "")),
                decision_kind=str(item.get("decision_kind", "")),
                target_team_id=str(item.get("target_team_id")) if item.get("target_team_id") is not None else None,
                target_team_name=str(item.get("target_team_name")) if item.get("target_team_name") is not None else None,
                title=str(item.get("title", "")),
                summary=str(item.get("summary", "")),
                source_ref=str(item.get("source_ref")) if item.get("source_ref") is not None else None,
                warnings=[str(value) for value in item.get("warnings", []) if value],
            )
            for item in payload.get("accepted_decisions", []) or []
            if isinstance(item, dict)
        ]
        return TeamPolicyOverlay(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            current_team_id=str(payload.get("current_team_id")) if payload.get("current_team_id") is not None else None,
            current_team_name=str(payload.get("current_team_name")) if payload.get("current_team_name") is not None else None,
            kept_teams=[str(value) for value in payload.get("kept_teams", []) if value],
            backup_teams=[str(value) for value in payload.get("backup_teams", []) if value],
            watched_teams=[str(value) for value in payload.get("watched_teams", []) if value],
            accepted_decisions=decisions,
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


def build_and_save_team_policy_overlay(project_root: Path) -> tuple[TeamPolicyOverlay, Path]:
    """team policy overlay를 빌드하고 기본 위치에 저장한다."""
    root = Path(project_root).resolve()
    overlay = TeamPolicyOverlayBuilder().build(root)
    path = default_team_policy_overlay_path(root)
    TeamPolicyStore().save(overlay, path)
    return overlay, path


def load_or_build_team_policy_overlay(project_root: Path) -> TeamPolicyOverlay:
    """저장된 overlay가 있으면 읽고, 없으면 즉석에서 빌드한다."""
    root = Path(project_root).resolve()
    path = default_team_policy_overlay_path(root)
    if path.exists():
        try:
            return TeamPolicyStore().load(path)
        except Exception:
            return TeamPolicyOverlayBuilder().build(root)
    return TeamPolicyOverlayBuilder().build(root)


def team_policy_hints(overlay: TeamPolicyOverlay) -> list[str]:
    """사람에게 보여줄 team policy hint를 만든다."""
    hints: list[str] = []
    if overlay.current_team_name:
        hints.append(f"{overlay.current_team_name} is the accepted current team")
    for team_name in overlay.kept_teams:
        hints.append(f"{team_name} is kept for this harness")
    for team_name in overlay.backup_teams:
        hints.append(f"{team_name} is kept as backup")
    for team_name in overlay.watched_teams:
        hints.append(f"{team_name} is being watched, not used by default")
    return _dedupe(hints)


def team_policy_context(project_root: Path) -> dict[str, Any]:
    """request/session artifact에 넣을 team policy snapshot을 만든다."""
    root = Path(project_root).resolve()
    overlay, path = build_and_save_team_policy_overlay(root)
    return {
        "enabled": True,
        "overlay_ref": _relative_to_project(path, root),
        "current_team_id": overlay.current_team_id,
        "current_team_name": overlay.current_team_name,
        "kept_teams": list(overlay.kept_teams),
        "backup_teams": list(overlay.backup_teams),
        "watched_teams": list(overlay.watched_teams),
        "applied_hints": team_policy_hints(overlay),
        "warnings": list(overlay.warnings),
    }


def team_policy_role(team: TeamPreset, overlay: TeamPolicyOverlay) -> str | None:
    """특정 team이 overlay에서 맡은 역할을 반환한다."""
    if overlay.current_team_id == team.team_id or overlay.current_team_name == team.name:
        return "current team"
    if team.name in overlay.kept_teams or team.team_id in overlay.kept_teams:
        return "kept team"
    if team.name in overlay.backup_teams or team.team_id in overlay.backup_teams:
        return "backup team"
    if team.name in overlay.watched_teams or team.team_id in overlay.watched_teams:
        return "watched team"
    return None


def render_team_policy_summary(overlay: TeamPolicyOverlay) -> str:
    """team policy overlay를 사람이 읽기 좋게 렌더링한다."""
    lines = ["Accepted team policy:"]
    if overlay.current_team_name:
        lines.extend(["  current:", f"    - {overlay.current_team_name}"])
    if overlay.kept_teams:
        lines.extend(["  kept:"])
        lines.extend([f"    - {item}" for item in overlay.kept_teams])
    if overlay.backup_teams:
        lines.extend(["  backup:"])
        lines.extend([f"    - {item}" for item in overlay.backup_teams])
    if overlay.watched_teams:
        lines.extend(["  watch:"])
        lines.extend([f"    - {item}" for item in overlay.watched_teams])
    if len(lines) == 1:
        lines.append("  none")
    return "\n".join(lines)
