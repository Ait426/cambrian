from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentDispatchResult:
    schema_version: str
    generated_at: str
    status: str
    job_id: str | None
    assigned_harness: str | None
    assigned_agents: list[str]
    validation_lane: str | None
    request: str
    next_commands: list[str]
    pack_job: dict[str, Any] | None = None
    harness_id: str | None = None
    harness_status: str | None = None
    change_policy: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "created"
        payload["harness_id"] = self.harness_id or self.assigned_harness
        payload["agents"] = list(self.assigned_agents)
        return payload


class AgentDispatcher:
    def dispatch(self, project_root: Path, request: str) -> AgentDispatchResult:
        root = Path(project_root).resolve()
        request_text = str(request or "").strip()
        if not request_text:
            return AgentDispatchResult(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                status="blocked",
                job_id=None,
                assigned_harness=None,
                assigned_agents=[],
                validation_lane=None,
                request=request_text,
                next_commands=['cambrian agent dispatch "<request>"'],
                errors=["Request is required."],
            )
        custom_result = _dispatch_custom_harness(root, request_text)
        if custom_result is not None:
            return custom_result
        try:
            from engine.project_pack_activation import current_active_pack

            context = current_active_pack(root)
        except ImportError:
            context = None
        if context is None:
            return AgentDispatchResult(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                status="blocked",
                job_id=None,
                assigned_harness=None,
                assigned_agents=[],
                validation_lane=None,
                request=request_text,
                next_commands=["cambrian project scan", "cambrian harness plan", "cambrian harness install"],
                errors=["No active project harness is installed."],
            )

        from engine.project_pack_jobs import PackJobStarter

        started = PackJobStarter().start(root, request_text, pack_ref=context.pack_id)
        job_id = started.job.job_id
        next_commands = [
            f"cambrian job ingest {job_id} ai_reply_patch_candidate.yaml",
            f"cambrian job validate {job_id}",
        ]
        return AgentDispatchResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="created",
            job_id=job_id,
            assigned_harness=context.pack_id,
            assigned_agents=list(context.workers),
            validation_lane=_validation_lane_label(context.pack_id, context.lane_label),
            request=request_text,
            next_commands=next_commands,
            pack_job=started.to_dict(),
            warnings=list(started.warnings),
            errors=list(started.errors),
        )


def render_agent_dispatch_result(result: AgentDispatchResult) -> str:
    title = "Agent dispatch created." if result.status == "created" else "Agent dispatch blocked."
    lines = [
        title,
        "",
        "Job:",
        f"  {result.job_id or 'none'}",
        "",
        "Assigned harness:",
        f"  {result.assigned_harness or 'none'}",
        "",
        "Assigned agents:",
    ]
    lines.extend([f"  - {agent}" for agent in result.assigned_agents] or ["  - none"])
    if result.validation_lane:
        lines.extend(["", "Validation lane:", f"  {result.validation_lane}"])
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    lines.extend(
        [
            "",
            "Next:",
            "  1. Copy the request to your AI tool.",
            "  2. Save the AI reply as ai_reply_patch_candidate.yaml.",
            "  3. Run:",
        ]
    )
    lines.extend([f"     {command}" for command in result.next_commands] or ["     none"])
    return "\n".join(lines)


def _validation_lane_label(pack_id: str | None, lane_label: str | None) -> str | None:
    if pack_id == "typescript-jest-auth-core":
        return "TypeScript + Jest"
    if pack_id == "auth-bug-core":
        return "Python + pytest"
    return lane_label


def _dispatch_custom_harness(root: Path, request: str) -> AgentDispatchResult | None:
    try:
        from engine.project_custom_harness import create_custom_harness_job, load_custom_agents, load_custom_harness, load_custom_validation

        harness = load_custom_harness(root)
        if harness is None:
            return None
        job_payload, pack_job_payload = create_custom_harness_job(root, request, entry_mode="agent_dispatch")
        agents = load_custom_agents(root)
        validation = load_custom_validation(root)
    except FileNotFoundError:
        return None
    job = job_payload.get("job", {}) if isinstance(job_payload.get("job"), dict) else {}
    outcome = job.get("outcome_snapshot", {}) if isinstance(job.get("outcome_snapshot"), dict) else {}
    harness_id = str(harness.get("id") or job.get("pack_id") or "")
    selected = outcome.get("selected_agents", [])
    assigned_agents = [str(item) for item in selected if item] if isinstance(selected, list) else []
    if not assigned_agents:
        assigned_agents = [str(item.get("id")) for item in agents if isinstance(item, dict) and item.get("id")]
    next_commands = [
        f"cambrian job ingest {job.get('job_id')} ai_reply_patch_candidate.yaml",
        f"cambrian job validate {job.get('job_id')}",
    ]
    return AgentDispatchResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="created",
        job_id=str(job.get("job_id") or ""),
        assigned_harness=harness_id,
        assigned_agents=assigned_agents,
        validation_lane=_custom_validation_lane(harness, validation),
        request=request,
        next_commands=next_commands,
        pack_job=pack_job_payload,
        harness_id=harness_id,
        harness_status=str(harness.get("status") or "draft"),
        change_policy=str(harness.get("policy", {}).get("change_mode") or "proposal_only"),
    )


def _custom_validation_lane(harness: dict[str, Any], validation: dict[str, Any]) -> str:
    commands = validation.get("test_commands", [])
    if isinstance(commands, list) and commands:
        return f"{harness.get('language') or 'custom'} + {', '.join(str(item) for item in commands)}"
    return f"{harness.get('language') or 'custom'} + manual validation"
