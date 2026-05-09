from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .project_agent_router import AgentRoute, HarnessAwareAgentRouter
from .project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from .project_harness import HarnessProfileStore, default_harness_profile_path


SCHEMA_VERSION = "1"


@dataclass
class AgentTrialStep:
    kind: str
    status: str
    summary: str
    artifact_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AgentTrialReport:
    schema_version: str
    generated_at: str
    trial_id: str
    project_name: str | None
    harness_id: str | None
    request: str
    request_intent: str | None
    current_lead_agent_id: str | None
    shadow_agent_id: str
    selected_via: str
    compatibility_status: str | None
    status: str
    steps: list[AgentTrialStep] = field(default_factory=list)
    comparison: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_path: str | None = None


def default_agent_trials_dir(project_root: Path) -> Path:
    return project_root / ".cambrian" / "agents" / "trials"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _safe_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-") or "agent"


def default_agent_trial_path(project_root: Path, report: AgentTrialReport) -> Path:
    suffix = report.trial_id.rsplit("-", 1)[-1]
    return default_agent_trials_dir(project_root) / f"trial_{_timestamp()}_{_safe_token(report.shadow_agent_id)}_{suffix}.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _load_harness(project_root: Path) -> Any | None:
    path = default_harness_profile_path(project_root)
    if not path.exists():
        return None
    try:
        return HarnessProfileStore().load(path)
    except Exception:
        return None


def _load_registry(project_root: Path, harness: Any | None = None) -> Any:
    registry_path = default_agent_registry_path(project_root)
    if registry_path.exists():
        try:
            return AgentRegistryStore().load(registry_path)
        except Exception:
            pass
    return AgentRegistryBuilder().build(project_root, harness=harness)


def _find_route(routes: list[AgentRoute], agent_id: str) -> AgentRoute | None:
    for route in routes:
        if route.agent_id == agent_id:
            return route
    return None


def _fit_label(score: float | None) -> str:
    value = score or 0.0
    if value >= 0.7:
        return "strong"
    if value >= 0.45:
        return "good"
    if value >= 0.25:
        return "partial"
    return "weak"


def _intent_from_route(route: AgentRoute | None) -> str | None:
    if route is None:
        return None
    role = (route.role_id or "").replace("_agent", "").replace("-agent", "")
    return role or None


def _agent_exists(project_root: Path, agent_id: str, harness: Any | None) -> bool:
    registry = _load_registry(project_root, harness)
    return any(agent.agent_id == agent_id for agent in registry.agents)


def _agent_compatibility(project_root: Path, agent_id: str, harness: Any | None) -> str | None:
    registry = _load_registry(project_root, harness)
    for agent in registry.agents:
        if agent.agent_id == agent_id:
            stats = agent.stats if isinstance(agent.stats, dict) else {}
            return stats.get("compatibility_status")
    return None


class AgentTrialRunner:
    def run(
        self,
        project_root: Path,
        shadow_agent_id: str,
        request: str,
        current_lead_agent_id: str | None = None,
    ) -> AgentTrialReport:
        root = project_root.resolve()
        harness = _load_harness(root)
        project_name = getattr(harness, "project_name", None)
        harness_id = getattr(harness, "harness_id", None)
        generated_at = _now()
        trial_id = f"trial-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"

        if not _agent_exists(root, shadow_agent_id, harness):
            return AgentTrialReport(
                schema_version=SCHEMA_VERSION,
                generated_at=generated_at,
                trial_id=trial_id,
                project_name=project_name,
                harness_id=harness_id,
                request=request,
                request_intent=None,
                current_lead_agent_id=current_lead_agent_id,
                shadow_agent_id=shadow_agent_id,
                selected_via="explicit_trial",
                compatibility_status=None,
                status="blocked",
                steps=[
                    AgentTrialStep(
                        kind="diagnose",
                        status="blocked",
                        summary=f"Shadow candidate not found: {shadow_agent_id}",
                    )
                ],
                comparison={"result": "inconclusive", "reasons": [f"Shadow candidate not found: {shadow_agent_id}"]},
                errors=[f"Shadow candidate not found: {shadow_agent_id}"],
                next_actions=["cambrian agent list"],
            )

        compatibility = _agent_compatibility(root, shadow_agent_id, harness)
        if compatibility == "blocked":
            return self._blocked_report(
                generated_at=generated_at,
                trial_id=trial_id,
                project_name=project_name,
                harness_id=harness_id,
                request=request,
                current_lead_agent_id=current_lead_agent_id,
                shadow_agent_id=shadow_agent_id,
                compatibility_status=compatibility,
                reason=f"Shadow candidate has blocked compatibility: {shadow_agent_id}",
            )

        router = HarnessAwareAgentRouter()
        try:
            lead_context = router.route(
                user_request=request,
                project_root=root,
                explicit_agent_id=current_lead_agent_id,
            )
            shadow_context = router.route(
                user_request=request,
                project_root=root,
                explicit_agent_id=shadow_agent_id,
            )
        except ValueError as exc:
            return self._blocked_report(
                generated_at=generated_at,
                trial_id=trial_id,
                project_name=project_name,
                harness_id=harness_id,
                request=request,
                current_lead_agent_id=current_lead_agent_id,
                shadow_agent_id=shadow_agent_id,
                compatibility_status=compatibility,
                reason=str(exc),
            )

        lead_agent_id = current_lead_agent_id or lead_context.lead_agent_id
        lead_route = _find_route(lead_context.routes, lead_agent_id) if lead_agent_id else None
        shadow_route = _find_route(shadow_context.routes, shadow_agent_id)
        request_intent = _intent_from_route(lead_route or shadow_route)
        steps = self._build_steps(harness, shadow_route)
        comparison = self._compare(lead_route, shadow_route)

        next_actions = [
            f"cambrian agent show {shadow_agent_id}",
            f'cambrian do "{request}" --agent {shadow_agent_id}',
        ]
        if shadow_route and shadow_route.status != "equipped":
            next_actions.insert(1, f"cambrian agent hire {shadow_agent_id}")

        warnings = list(shadow_route.warnings if shadow_route else [])
        warnings.extend(lead_context.warnings)
        warnings.extend(shadow_context.warnings)

        return AgentTrialReport(
            schema_version=SCHEMA_VERSION,
            generated_at=generated_at,
            trial_id=trial_id,
            project_name=project_name,
            harness_id=harness_id,
            request=request,
            request_intent=request_intent,
            current_lead_agent_id=lead_agent_id,
            shadow_agent_id=shadow_agent_id,
            selected_via="explicit_trial",
            compatibility_status=compatibility,
            status="completed",
            steps=steps,
            comparison=comparison,
            next_actions=next_actions,
            warnings=warnings,
            errors=[],
        )

    def _blocked_report(
        self,
        *,
        generated_at: str,
        trial_id: str,
        project_name: str | None,
        harness_id: str | None,
        request: str,
        current_lead_agent_id: str | None,
        shadow_agent_id: str,
        compatibility_status: str | None,
        reason: str,
    ) -> AgentTrialReport:
        return AgentTrialReport(
            schema_version=SCHEMA_VERSION,
            generated_at=generated_at,
            trial_id=trial_id,
            project_name=project_name,
            harness_id=harness_id,
            request=request,
            request_intent=None,
            current_lead_agent_id=current_lead_agent_id,
            shadow_agent_id=shadow_agent_id,
            selected_via="explicit_trial",
            compatibility_status=compatibility_status,
            status="blocked",
            steps=[AgentTrialStep(kind="diagnose", status="blocked", summary=reason)],
            comparison={
                "lead_summary": {"agent_id": current_lead_agent_id},
                "shadow_summary": {"agent_id": shadow_agent_id, "compatibility": compatibility_status},
                "result": "inconclusive",
                "reasons": [reason],
            },
            next_actions=["cambrian agent list"],
            warnings=[reason],
            errors=[],
        )

    def _build_steps(self, harness: Any | None, shadow_route: AgentRoute | None) -> list[AgentTrialStep]:
        score = shadow_route.score if shadow_route else 0.0
        role = shadow_route.role_id if shadow_route else ""
        has_tests = bool(getattr(harness, "test_command", None))
        steps = [
            AgentTrialStep(
                kind="diagnose",
                status="success" if score >= 0.2 else "blocked",
                summary="Shadow candidate was evaluated against the current harness and request.",
                artifact_refs=[],
                warnings=[] if score >= 0.2 else ["Shadow candidate has weak request fit."],
            )
        ]

        direct_roles = {"bug_fix", "small_refactor", "docs_update", "patch_proposal", "diagnose"}
        if role in direct_roles or score >= 0.35:
            steps.append(
                AgentTrialStep(
                    kind="patch_intent",
                    status="success",
                    summary="Shadow candidate can form a bounded patch intent for this request.",
                )
            )
            steps.append(
                AgentTrialStep(
                    kind="patch_proposal",
                    status="success" if score >= 0.35 else "skipped",
                    summary="Shadow candidate has enough fit for a proposal-level dry run.",
                )
            )
        else:
            steps.append(
                AgentTrialStep(
                    kind="patch_intent",
                    status="skipped",
                    summary="Shadow candidate is better suited as support than direct patch lead.",
                )
            )
            steps.append(
                AgentTrialStep(
                    kind="patch_proposal",
                    status="skipped",
                    summary="Proposal-level trial skipped because direct request fit is low.",
                )
            )

        validation_status = "success" if has_tests and score >= 0.35 else "skipped"
        validation_summary = (
            "Current harness has a test command, so isolated validation would be available."
            if validation_status == "success"
            else "Isolated validation was not run; no source changes were applied."
        )
        steps.append(AgentTrialStep(kind="validation", status=validation_status, summary=validation_summary))
        return steps

    def _compare(self, lead_route: AgentRoute | None, shadow_route: AgentRoute | None) -> dict[str, Any]:
        lead_score = lead_route.score if lead_route else 0.0
        shadow_score = shadow_route.score if shadow_route else 0.0
        lead_agent = lead_route.agent_id if lead_route else None
        shadow_agent = shadow_route.agent_id if shadow_route else None
        diff = shadow_score - lead_score
        if shadow_route is None:
            result = "inconclusive"
        elif diff >= 0.12:
            result = "shadow_stronger"
        elif diff <= -0.12:
            result = "lead_stronger"
        else:
            result = "comparable"

        reasons: list[str] = []
        if shadow_route:
            reasons.extend(shadow_route.reasons[:3])
        if lead_route and lead_route.agent_id != shadow_agent:
            reasons.append(f"Current lead remains {lead_route.agent_id} with {_fit_label(lead_score)} local fit.")
        if result == "comparable":
            reasons.append("Current lead and shadow candidate are close enough to compare before hiring.")
        elif result == "shadow_stronger":
            reasons.append("Shadow candidate has stronger routing fit for this request.")
        elif result == "lead_stronger":
            reasons.append("Current lead has stronger routing fit for this request.")
        else:
            reasons.append("Trial evidence is not strong enough to compare the agents.")

        return {
            "lead_summary": {
                "agent_id": lead_agent,
                "fit": _fit_label(lead_score),
                "score": round(lead_score, 3),
            },
            "shadow_summary": {
                "agent_id": shadow_agent,
                "fit": _fit_label(shadow_score),
                "score": round(shadow_score, 3),
                "compatibility": shadow_route.compatibility_status if shadow_route else None,
            },
            "result": result,
            "reasons": reasons,
        }


class AgentTrialStore:
    def save(self, report: AgentTrialReport, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(report)
        data.pop("saved_path", None)
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
        report.saved_path = str(path)
        return path

    def load(self, path: Path) -> AgentTrialReport:
        data = _read_yaml(path)
        steps = [AgentTrialStep(**step) for step in data.get("steps", []) if isinstance(step, dict)]
        return AgentTrialReport(
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
            generated_at=str(data.get("generated_at") or ""),
            trial_id=str(data.get("trial_id") or path.stem),
            project_name=data.get("project_name"),
            harness_id=data.get("harness_id"),
            request=str(data.get("request") or ""),
            request_intent=data.get("request_intent"),
            current_lead_agent_id=data.get("current_lead_agent_id"),
            shadow_agent_id=str(data.get("shadow_agent_id") or ""),
            selected_via=str(data.get("selected_via") or "explicit_trial"),
            compatibility_status=data.get("compatibility_status"),
            status=str(data.get("status") or "completed"),
            steps=steps,
            comparison=data.get("comparison") if isinstance(data.get("comparison"), dict) else {},
            next_actions=list(data.get("next_actions") or []),
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
            saved_path=str(path),
        )


def _is_trial_path(path: Path, trials_dir: Path) -> bool:
    try:
        resolved = path.resolve()
        resolved.relative_to(trials_dir.resolve())
    except ValueError:
        return False
    return resolved.name.startswith("trial_") and resolved.suffix in {".yaml", ".yml"}


def resolve_agent_trial_path(project_root: Path, trial_ref: str) -> Path:
    root = project_root.resolve()
    trials_dir = default_agent_trials_dir(root)
    raw = Path(trial_ref)
    candidates = [raw if raw.is_absolute() else (root / raw)]
    for candidate in candidates:
        if candidate.exists():
            if not _is_trial_path(candidate, trials_dir):
                raise ValueError("Trial show only accepts files inside .cambrian/agents/trials/ named trial_*.yaml.")
            return candidate.resolve()

    for path in sorted(trials_dir.glob("trial_*.y*ml"), key=lambda item: item.stat().st_mtime, reverse=True):
        data = _read_yaml(path)
        if data.get("trial_id") == trial_ref or path.stem == trial_ref or path.name == trial_ref:
            return path
    raise FileNotFoundError(f"Trial not found: {trial_ref}")


def load_recent_agent_trial_summary(project_root: Path) -> dict[str, Any] | None:
    trials_dir = default_agent_trials_dir(project_root)
    paths = sorted(trials_dir.glob("trial_*.y*ml"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not paths:
        return None
    report = AgentTrialStore().load(paths[0])
    comparison = report.comparison if isinstance(report.comparison, dict) else {}
    return {
        "trial_id": report.trial_id,
        "path": str(paths[0]),
        "request": report.request,
        "current_lead_agent_id": report.current_lead_agent_id,
        "shadow_agent_id": report.shadow_agent_id,
        "status": report.status,
        "result": comparison.get("result"),
    }


def render_agent_trial(report: AgentTrialReport) -> str:
    lines = [
        "Agent Trial",
        "=" * 50,
        "",
        "Request:",
        f"  {report.request}",
        "",
        "Current lead:",
        f"  {report.current_lead_agent_id or 'none'}",
        "",
        "Shadow candidate:",
        f"  {report.shadow_agent_id}",
        "",
        "Result:",
        f"  {report.comparison.get('result', report.status)}",
    ]
    reasons = report.comparison.get("reasons") if isinstance(report.comparison, dict) else []
    if reasons:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {reason}" for reason in reasons])
    if report.steps:
        lines.extend(["", "Trial steps:"])
        for step in report.steps:
            lines.append(f"  - {step.kind}: {step.status} — {step.summary}")
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings])
    if report.saved_path:
        lines.extend(["", "Saved:", f"  {report.saved_path}"])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in report.next_actions])
    return "\n".join(lines)


def report_to_json(report: AgentTrialReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)
