"""AI 비종속 prompt packet과 structured reply ingest 브리지."""

from __future__ import annotations

import json
import logging
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
ALLOWED_RESPONSE_KINDS = {"analysis", "patch_candidate", "review", "plan"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    return secrets.token_hex(2)


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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


def default_bridge_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "bridge"


def default_bridge_packets_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "packets"


def default_bridge_replies_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "replies"


def default_bridge_packet_path(project_root: Path, packet: "BridgePacket") -> Path:
    return default_bridge_packets_dir(project_root) / f"{packet.packet_id}.yaml"


def default_bridge_reply_path(project_root: Path, reply: "BridgeReply") -> Path:
    return default_bridge_replies_dir(project_root) / f"{reply.reply_id}.yaml"


@dataclass
class BridgePacket:
    schema_version: str
    packet_id: str
    created_at: str
    project_name: str | None
    harness_id: str | None
    workspace: str
    request: str
    request_intent: str | None
    harness_summary: dict[str, Any]
    agent_summary: dict[str, Any]
    policy_summary: dict[str, Any]
    memory_summary: dict[str, Any]
    response_contract: dict[str, Any]
    suggested_next_actions: list[str]
    execution_contract: dict[str, Any] = field(default_factory=dict)
    codex_claude_instruction: str | None = None
    active_pack_context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BridgeReply:
    schema_version: str
    reply_id: str
    created_at: str
    packet_id: str | None
    project_name: str | None
    request: str | None
    response_kind: str
    content: dict[str, Any]
    raw_text: str | None
    source_reply_path: str | None
    linked_session_id: str | None
    linked_request_ref: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectBridgeBuilder:
    """현재 프로젝트 상태를 어떤 AI에도 붙여넣을 수 있는 작업 패킷으로 압축한다."""

    def build_packet(
        self,
        project_root: Path,
        request: str,
        session_ref: str | None = None,
        active_pack_context_override: dict[str, Any] | None = None,
    ) -> BridgePacket:
        root = Path(project_root).resolve()
        warnings: list[str] = []
        harness_summary = _collect_harness_summary(root, warnings)
        agent_summary = _collect_agent_summary(root, warnings)
        policy_summary = _collect_policy_summary(root, warnings)
        memory_summary = _collect_memory_summary(root, warnings)
        active_pack_context: dict[str, Any] = {}
        if active_pack_context_override is not None:
            active_pack_context = dict(active_pack_context_override)
        else:
            try:
                from engine.project_pack_activation import active_pack_bridge_context

                active_pack_context = active_pack_bridge_context(root)
            except Exception as exc:
                logger.warning("active pack bridge context failed: %s", exc)
        request_text = str(request or "").strip()
        intent = _infer_request_intent(request_text)
        packet_id = f"packet_{_timestamp()}_{_short_id()}"
        response_contract = _response_contract()
        next_actions = [
            "Paste this packet into any AI.",
            "Ask the AI to return YAML or JSON matching response_contract.",
            f"cambrian bridge paste --packet {packet_id}",
            f"cambrian bridge ingest <reply-file> --packet {packet_id} --auto-route",
        ]
        if session_ref:
            next_actions.append(f"Reply can be linked to session: {session_ref}")
        execution_contract = _execution_contract(
            request_text=request_text,
            request_intent=intent,
            harness_summary=harness_summary,
            agent_summary=agent_summary,
            policy_summary=policy_summary,
            active_pack_context=active_pack_context,
            response_contract=response_contract,
        )
        return BridgePacket(
            schema_version=SCHEMA_VERSION,
            packet_id=packet_id,
            created_at=_now(),
            project_name=str(harness_summary.get("project_name") or root.name),
            harness_id=str(harness_summary.get("harness_id")) if harness_summary.get("harness_id") else None,
            workspace=str(root),
            request=request_text,
            request_intent=intent,
            harness_summary=harness_summary,
            agent_summary=agent_summary,
            policy_summary=policy_summary,
            memory_summary=memory_summary,
            active_pack_context=active_pack_context,
            response_contract=response_contract,
            execution_contract=execution_contract,
            codex_claude_instruction=_codex_claude_instruction(execution_contract),
            suggested_next_actions=_dedupe(next_actions),
            warnings=_dedupe(warnings),
            errors=[],
        )


class ProjectBridgeReplyParser:
    """AI가 반환한 YAML/JSON/fenced block 응답을 안전하게 구조화한다."""

    def parse_reply(self, text: str) -> BridgeReply:
        raw_text = str(text or "")
        payload, warnings = _parse_structured_payload(raw_text)
        errors = _validate_reply_payload(payload)
        response_kind = str(payload.get("response_kind", "") or "")
        return BridgeReply(
            schema_version=SCHEMA_VERSION,
            reply_id=f"reply_{_timestamp()}_{_short_id()}",
            created_at=_now(),
            packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            request=str(payload.get("request")) if payload.get("request") is not None else None,
            response_kind=response_kind,
            content=payload,
            raw_text=raw_text,
            source_reply_path=None,
            linked_session_id=None,
            linked_request_ref=None,
            warnings=warnings,
            errors=errors,
        )


class ProjectBridgeStore:
    def save_packet(self, packet: BridgePacket, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), packet.to_dict())

    def save_reply(self, reply: BridgeReply, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), reply.to_dict())

    def load_packet(self, path: Path) -> BridgePacket:
        payload = _load_yaml(Path(path).resolve())
        return _packet_from_dict(payload)

    def load_reply(self, path: Path) -> BridgeReply:
        payload = _load_yaml(Path(path).resolve())
        return _reply_from_dict(payload)


def resolve_bridge_packet_path(project_root: Path, packet_ref: str) -> Path:
    return _resolve_bridge_path(project_root, packet_ref, default_bridge_packets_dir(project_root), "packet")


def resolve_bridge_reply_path(project_root: Path, reply_ref: str) -> Path:
    return _resolve_bridge_path(project_root, reply_ref, default_bridge_replies_dir(project_root), "reply")


def render_bridge_packet_prepared(packet: BridgePacket, saved_path: str) -> str:
    return "\n".join(
        [
            "Bridge packet prepared.",
            "",
            "Request:",
            f"  {packet.request}",
            "",
            "Saved:",
            f"  {saved_path}",
            "",
            "Use:",
            "  paste the packet into any AI and ask it to answer using the provided response contract",
            "",
            "Next:",
            f"  cambrian bridge paste --packet {packet.packet_id}",
        ]
    )


def render_bridge_packet(packet: BridgePacket) -> str:
    lines = [
        "Bridge Packet",
        "==================================================",
        "",
        "Packet:",
        f"  {packet.packet_id}",
        "",
        "Request:",
        f"  {packet.request}",
        "",
        "Harness:",
        f"  type : {packet.harness_summary.get('project_type') or 'unknown'}",
        f"  stack: {', '.join(_as_list(packet.harness_summary.get('stack'))) or 'none'}",
        f"  tests: {packet.harness_summary.get('test_command') or 'none'}",
    ]
    active_team = packet.harness_summary.get("active_team")
    if active_team:
        lines.extend(["", "Active team:", f"  {active_team}"])
    active_agents = _as_list(packet.agent_summary.get("active_agents"))
    if active_agents:
        lines.extend(["", "Active agents:"])
        lines.extend([f"  - {agent_id}" for agent_id in active_agents])
    hints = _as_list(packet.policy_summary.get("hints"))
    if hints:
        lines.extend(["", "Accepted policy:"])
        lines.extend([f"  - {hint}" for hint in hints[:5]])
    lessons = _as_list(packet.memory_summary.get("top_lessons"))
    if lessons:
        lines.extend(["", "Relevant memory:"])
        lines.extend([f"  - {lesson}" for lesson in lessons[:3]])
    active_pack = packet.active_pack_context if isinstance(packet.active_pack_context, dict) else {}
    if active_pack:
        lines.extend(
            [
                "",
                "Active pack context:",
                f"  pack    : {active_pack.get('pack_id') or 'unknown'}",
                f"  team    : {active_pack.get('team') or 'none'}",
                f"  template: {active_pack.get('template') or 'none'}",
                f"  lane    : {active_pack.get('lane_label') or active_pack.get('lane_id') or 'none'}",
            ]
        )
    contract = packet.execution_contract if isinstance(packet.execution_contract, dict) else {}
    if contract:
        lines.extend(["", "Execution contract:"])
        lines.append(f"  role: {contract.get('role') or 'none'}")
        selected_agents = _as_list(contract.get("selected_agents"))
        selected_skills = _as_list(contract.get("selected_skills"))
        if selected_agents:
            lines.append(f"  agents: {', '.join(selected_agents)}")
        if selected_skills:
            lines.append(f"  skills: {', '.join(selected_skills)}")
        must_not_do = _as_list(contract.get("must_not_do"))
        if must_not_do:
            lines.append("  must not:")
            lines.extend([f"    - {item}" for item in must_not_do[:4]])
    lines.extend(["", "Next:"])
    lines.extend([f"  - {action}" for action in packet.suggested_next_actions[:3]])
    if packet.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in packet.warnings[:4]])
    return "\n".join(lines)


def render_bridge_packet_markdown(packet: BridgePacket) -> str:
    use_cases = _as_list(packet.harness_summary.get("primary_use_cases"))
    agents = _as_list(packet.agent_summary.get("active_agents"))
    hints = _as_list(packet.policy_summary.get("hints"))
    lessons = _as_list(packet.memory_summary.get("top_lessons"))
    lines = [
        "# Cambrian Bridge Packet",
        "",
        "## Request",
        packet.request,
        "",
        "## Project Harness",
        f"- type: {packet.harness_summary.get('project_type') or 'unknown'}",
        f"- tests: {packet.harness_summary.get('test_command') or 'none'}",
        f"- focus: {', '.join(use_cases) or 'none'}",
    ]
    current_template = packet.harness_summary.get("current_template")
    if current_template:
        lines.append(f"- current_template: {current_template}")
    active_team = packet.harness_summary.get("active_team")
    if active_team:
        lines.extend(["", "## Active Team", f"- {active_team}"])
    if agents:
        lines.extend(["", "## Active Agents"])
        lines.extend([f"- {agent_id}" for agent_id in agents])
    if hints:
        lines.extend(["", "## Accepted Policy"])
        lines.extend([f"- {hint}" for hint in hints[:6]])
    if lessons:
        lines.extend(["", "## Relevant Memory"])
        lines.extend([f"- {lesson}" for lesson in lessons[:3]])
    active_pack = packet.active_pack_context if isinstance(packet.active_pack_context, dict) else {}
    if active_pack:
        lines.extend(
            [
                "",
                "## Active Pack Context",
                f"- pack: {active_pack.get('pack_id') or 'unknown'}",
                f"- team: {active_pack.get('team') or 'none'}",
                f"- template: {active_pack.get('template') or 'none'}",
                f"- lane: {active_pack.get('lane_label') or active_pack.get('lane_id') or 'none'}",
                "- soft_context_only: true",
            ]
        )
    contract = packet.execution_contract if isinstance(packet.execution_contract, dict) else {}
    if contract:
        lines.extend(
            [
                "",
                "## Codex / Claude Instruction",
                str(packet.codex_claude_instruction or "").strip(),
                "",
                "## Execution Contract",
                f"- role: {contract.get('role') or 'none'}",
                f"- task: {contract.get('task') or packet.request}",
                f"- change_policy: {contract.get('change_policy') or 'proposal_only'}",
            ]
        )
        selected_agents = _as_list(contract.get("selected_agents"))
        selected_skills = _as_list(contract.get("selected_skills"))
        validation_criteria = _as_list(contract.get("validation_criteria"))
        approval_required_actions = _as_list(contract.get("approval_required_actions"))
        forbidden_actions = _as_list(contract.get("forbidden_actions"))
        if selected_agents:
            lines.extend(["- selected_agents:"] + [f"  - {item}" for item in selected_agents])
        if selected_skills:
            lines.extend(["- selected_skills:"] + [f"  - {item}" for item in selected_skills])
        if validation_criteria:
            lines.extend(["- validation_criteria:"] + [f"  - {item}" for item in validation_criteria])
        if approval_required_actions:
            lines.extend(["- approval_required_actions:"] + [f"  - {item}" for item in approval_required_actions])
        if forbidden_actions:
            lines.extend(["- forbidden_actions:"] + [f"  - {item}" for item in forbidden_actions])
        must_do = _as_list(contract.get("must_do"))
        must_not_do = _as_list(contract.get("must_not_do"))
        if must_do:
            lines.extend(["- must_do:"] + [f"  - {item}" for item in must_do])
        if must_not_do:
            lines.extend(["- must_not_do:"] + [f"  - {item}" for item in must_not_do])
    lines.extend(
        [
            "",
            "## Response Contract",
            "Return YAML or JSON with these keys:",
            "- response_kind: analysis | patch_candidate | review | plan",
            "- summary",
            "- reason",
            "- warnings",
            "",
            "For patch_candidate also include:",
            "- target_path",
            "- old_text",
            "- new_text",
            "- related_tests",
            "",
            "Safety rules:",
            "- Do not mutate project files.",
            "- Do not assume facts outside this packet.",
            "- Keep scope narrow and explain warnings.",
            "",
            "## Fast Path",
            "After the AI returns YAML/JSON, paste it back with:",
            f"cambrian bridge paste --packet {packet.packet_id}",
        ]
    )
    return "\n".join(lines)


def render_bridge_reply_ingested(reply: BridgeReply, saved_path: str) -> str:
    return "\n".join(
        [
            "Bridge reply ingested.",
            "",
            "Kind:",
            f"  {reply.response_kind or 'unknown'}",
            "",
            "Saved:",
            f"  {saved_path}",
            "",
            "Next:",
            "  review the reply artifact before connecting it to patch/do flow",
        ]
    )


def render_bridge_reply(reply: BridgeReply, activity: dict[str, Any] | None = None) -> str:
    lines = [
        "Bridge Reply",
        "==================================================",
        "",
        "Reply:",
        f"  {reply.reply_id}",
        "",
        "Kind:",
        f"  {reply.response_kind or 'unknown'}",
    ]
    if reply.packet_id:
        lines.extend(["", "Packet:", f"  {reply.packet_id}"])
    summary = str(reply.content.get("summary", "") or "").strip()
    if summary:
        lines.extend(["", "Summary:", f"  {summary}"])
    if reply.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {error}" for error in reply.errors])
    if reply.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in reply.warnings])
    if activity:
        if activity.get("latest_fastpath_id"):
            lines.extend([
                "",
                "Fast path:",
                f"  {activity.get('latest_fastpath_summary') or activity.get('latest_fastpath_status') or 'recorded'}",
            ])
            if activity.get("latest_fastpath_session_id"):
                lines.append(f"  linked session: {activity.get('latest_fastpath_session_id')}")
            if activity.get("latest_fastpath_next_command"):
                lines.append(f"  next: {activity.get('latest_fastpath_next_command')}")
        if activity.get("latest_handoff_status"):
            lines.extend([
                "",
                "Handoff:",
                f"  {activity.get('latest_handoff_kind') or 'unknown'} {activity.get('latest_handoff_status')}",
            ])
            if activity.get("target_artifact_ref"):
                lines.append(f"  artifact: {activity.get('target_artifact_ref')}")
        elif activity.get("latest_review_id"):
            lines.extend([
                "",
                "Review:",
                f"  usable: {'yes' if activity.get('latest_review_usable') else 'no'}",
            ])
            options = _as_list(activity.get("latest_review_options"))
            if options:
                lines.append(f"  handoff: {', '.join(options)}")
        if activity.get("latest_materialization_id"):
            lines.extend([
                "",
                "Materialization:",
                f"  {activity.get('latest_materialization_kind') or 'unknown'} created",
            ])
        if activity.get("latest_context_hint_id"):
            lines.extend([
                "",
                "Context hint:",
                f"  {activity.get('latest_context_hint_id')}",
            ])
        if activity.get("latest_checklist_id"):
            lines.extend([
                "",
                "Checklist:",
                f"  {activity.get('latest_checklist_status') or 'open'}",
            ])
            if activity.get("latest_checklist_next_step"):
                lines.append(f"  next step: {activity.get('latest_checklist_next_step')}")
    return "\n".join(lines)


def load_bridge_summary(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    packet_paths = _sorted_yaml_files(default_bridge_packets_dir(root), "packet_*.yaml")
    reply_paths = _sorted_yaml_files(default_bridge_replies_dir(root), "reply_*.yaml")
    latest_packet = _load_latest_packet(packet_paths)
    latest_reply = _load_latest_reply(reply_paths)
    return {
        "packet_count": len(packet_paths),
        "reply_count": len(reply_paths),
        "latest_packet_id": latest_packet.packet_id if latest_packet else None,
        "latest_packet_ref": _relative_to_project(packet_paths[0], root) if packet_paths else None,
        "latest_reply_id": latest_reply.reply_id if latest_reply else None,
        "latest_reply_kind": latest_reply.response_kind if latest_reply else None,
        "latest_reply_ref": _relative_to_project(reply_paths[0], root) if reply_paths else None,
        "pending_packets": max(0, len(packet_paths) - len(reply_paths)),
    }


def render_bridge_status_summary(summary: dict[str, Any]) -> str:
    if not summary or not int(summary.get("packet_count", 0) or 0):
        return "Bridge:\n  no packets yet"
    lines = ["Bridge:"]
    if summary.get("latest_packet_id"):
        lines.append(f"  latest packet : {summary.get('latest_packet_id')}")
    if summary.get("latest_reply_id"):
        lines.append(
            f"  latest reply  : {summary.get('latest_reply_id')} ({summary.get('latest_reply_kind') or 'unknown'})"
        )
    elif int(summary.get("pending_packets", 0) or 0) > 0:
        lines.append(f"  pending       : {int(summary.get('pending_packets', 0) or 0)} packet waiting for AI reply")
    return "\n".join(lines)


def _collect_harness_summary(root: Path, warnings: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"project_name": root.name}
    try:
        from engine.project_harness import HarnessProfileStore, default_harness_profile_path

        harness_path = default_harness_profile_path(root)
        if harness_path.exists():
            harness = HarnessProfileStore().load(harness_path)
            summary.update(
                {
                    "project_name": harness.project_name,
                    "harness_id": harness.harness_id,
                    "project_type": harness.project_type,
                    "stack": list(harness.stack),
                    "test_command": harness.test_command,
                    "mode": harness.mode,
                    "primary_use_cases": list(harness.primary_use_cases),
                    "active_agents": list(harness.active_agents),
                }
            )
    except Exception as exc:
        warnings.append(f"harness summary unavailable: {exc}")
    try:
        from engine.project_templates import load_current_template

        current = load_current_template(root)
        if current:
            summary["current_template"] = current.get("name")
    except Exception as exc:
        warnings.append(f"template summary unavailable: {exc}")
    try:
        from engine.project_teams import load_team_summary

        team_summary = load_team_summary(root)
        active_team = team_summary.get("active_team") if isinstance(team_summary.get("active_team"), dict) else None
        if active_team:
            summary["active_team"] = active_team.get("name") or active_team.get("team_id")
    except Exception as exc:
        warnings.append(f"team summary unavailable: {exc}")
    return summary


def _collect_agent_summary(root: Path, warnings: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"active_agents": []}
    try:
        from engine.project_agents import AgentRegistryStore, default_agent_registry_path

        registry_path = default_agent_registry_path(root)
        if registry_path.exists():
            registry = AgentRegistryStore().load(registry_path)
            active = [agent.agent_id for agent in registry.agents if agent.status == "equipped"]
            watched = [agent.agent_id for agent in registry.agents if agent.status in {"watch", "trial"}]
            summary["active_agents"] = active
            summary["watched_candidates"] = watched
            if active:
                summary["preferred_lead"] = active[0]
                summary["preferred_support"] = active[1:3]
    except Exception as exc:
        warnings.append(f"agent summary unavailable: {exc}")
    return summary


def _collect_policy_summary(root: Path, warnings: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"hints": []}
    try:
        from engine.project_harness_policy import load_or_build_policy_overlay, policy_hints

        overlay = load_or_build_policy_overlay(root)
        summary.update(
            {
                "test_first_practice": bool(overlay.test_first_practice),
                "narrow_change_scope": bool(overlay.narrow_change_scope),
                "increase_review_support": bool(overlay.increase_review_support),
                "hints": policy_hints(overlay),
            }
        )
    except Exception as exc:
        warnings.append(f"harness policy unavailable: {exc}")
    try:
        from engine.project_team_policy import load_or_build_team_policy_overlay, team_policy_hints

        team_overlay = load_or_build_team_policy_overlay(root)
        summary["current_team"] = team_overlay.current_team_name
        summary["backup_team"] = (team_overlay.backup_teams or [None])[0]
        summary["hints"] = _dedupe(list(summary.get("hints", [])) + team_policy_hints(team_overlay))
    except Exception as exc:
        warnings.append(f"team policy unavailable: {exc}")
    try:
        from engine.project_template_library_policy import load_or_build_template_library_policy_overlay

        library_overlay = load_or_build_template_library_policy_overlay(root, save=False)
        summary["template_library_policy"] = {
            "promoted": list(library_overlay.promoted_templates),
            "kept": list(library_overlay.kept_templates),
            "backup": list(library_overlay.backup_templates),
            "watch": list(library_overlay.watched_templates),
            "retire": list(library_overlay.retired_templates),
        }
    except Exception as exc:
        warnings.append(f"template library policy unavailable: {exc}")
    return summary


def _collect_memory_summary(root: Path, warnings: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {"top_lessons": [], "active_notes": []}
    try:
        from engine.project_memory import load_project_memory

        memory = load_project_memory(root)
        lessons = [
            lesson.text
            for lesson in getattr(memory, "lessons", [])
            if getattr(lesson, "status", "active") == "active" and not getattr(lesson, "suppressed", False)
        ]
        summary["top_lessons"] = lessons[:3]
    except Exception as exc:
        warnings.append(f"memory summary unavailable: {exc}")
    try:
        from engine.project_notes import ProjectNotesStore, default_notes_dir

        notes = ProjectNotesStore().list(default_notes_dir(root))
        summary["active_notes"] = [note.text for note in notes if note.status == "open"][:3]
    except Exception as exc:
        warnings.append(f"notes summary unavailable: {exc}")
    try:
        from engine.project_memory_hygiene import default_memory_hygiene_path, load_memory_hygiene

        hygiene_path = default_memory_hygiene_path(root)
        if hygiene_path.exists():
            hygiene = load_memory_hygiene(root)
            summary["hygiene_caution"] = bool(getattr(hygiene, "warnings", []))
    except Exception as exc:
        warnings.append(f"memory hygiene unavailable: {exc}")
    return summary


def _response_contract() -> dict[str, Any]:
    return {
        "format": "YAML or JSON",
        "allowed_response_kinds": sorted(ALLOWED_RESPONSE_KINDS),
        "required_keys": ["response_kind", "summary"],
        "patch_candidate_required_keys": ["target_path", "old_text", "new_text", "reason"],
        "safety": [
            "do not mutate project files",
            "do not assume facts outside the packet",
            "return structured content only",
        ],
    }


def _execution_contract(
    request_text: str,
    request_intent: str | None,
    harness_summary: dict[str, Any],
    agent_summary: dict[str, Any],
    policy_summary: dict[str, Any],
    active_pack_context: dict[str, Any],
    response_contract: dict[str, Any],
) -> dict[str, Any]:
    selected_agents = _as_list(active_pack_context.get("selected_agents")) or _as_list(agent_summary.get("active_agents"))
    selected_skills = _as_list(active_pack_context.get("selected_skills"))
    validation_commands = _as_list(active_pack_context.get("validation_commands")) or _as_list(harness_summary.get("test_command"))
    validation_criteria = _as_list(active_pack_context.get("validation_criteria"))
    forbidden_actions = _as_list(active_pack_context.get("forbidden_actions"))
    approval_required_actions = _as_list(active_pack_context.get("approval_required_actions"))
    change_policy = str(active_pack_context.get("change_policy") or "proposal_only")
    harness_id = active_pack_context.get("harness_id") or active_pack_context.get("pack_id") or harness_summary.get("harness_id")
    must_do = [
        "요청을 설치된 하네스, 인력, 스킬, 정책 기준으로 분석한다.",
        "근거와 불확실성을 분리해서 설명한다.",
        "패치가 필요하면 자동 적용이 아니라 patch_candidate로 제안한다.",
        "검증 명령과 회귀 위험을 함께 적는다.",
        "response_contract에 맞는 YAML 또는 JSON으로 답한다.",
    ]
    if validation_criteria:
        must_do.append("결과가 계약 validation_criteria를 어떻게 만족하는지 설명한다.")
    must_not_do = [
        "프로젝트 파일을 직접 수정했다고 주장하지 않는다.",
        "사용자가 제공하지 않은 secret, API key, 개인 정보를 요구하거나 출력하지 않는다.",
        "패치를 적용했다고 말하지 않는다.",
        "패킷 밖의 사실을 확정적으로 가정하지 않는다.",
        "검증하지 않은 성공을 성공처럼 말하지 않는다.",
    ]
    if approval_required_actions:
        must_not_do.append("approval_required_actions는 사용자 승인 전 실행하지 않는다.")
    must_not_do.extend([f"금지 행동을 수행하지 않는다: {item}" for item in forbidden_actions])
    return {
        "contract_version": "1.0",
        "execution_engines": ["Codex", "Claude", "Cursor", "GPT", "local model"],
        "role": "Cambrian 프로젝트 AI 회사의 실행 엔진",
        "task": request_text,
        "request_intent": request_intent,
        "harness_id": harness_id,
        "workforce_id": active_pack_context.get("workforce_id"),
        "selected_agents": selected_agents,
        "selected_skills": selected_skills,
        "change_policy": change_policy,
        "validation_commands": validation_commands,
        "validation_criteria": validation_criteria,
        "forbidden_actions": forbidden_actions,
        "approval_required_actions": approval_required_actions,
        "contract_template_kind": active_pack_context.get("contract_template_kind"),
        "must_do": _dedupe(must_do),
        "must_not_do": _dedupe(must_not_do),
        "response_contract": response_contract,
        "handoff_back": [
            "AI 응답을 ai_reply_patch_candidate.yaml 파일로 저장한다.",
            "cambrian job ingest latest ai_reply_patch_candidate.yaml",
            "cambrian job validate latest",
        ],
        "policy_hints": _as_list(policy_summary.get("hints"))[:6],
    }


def _codex_claude_instruction(contract: dict[str, Any]) -> str:
    agents = ", ".join(_as_list(contract.get("selected_agents"))) or "선택된 agent 없음"
    skills = ", ".join(_as_list(contract.get("selected_skills"))) or "선택된 skill 없음"
    validation = ", ".join(_as_list(contract.get("validation_commands"))) or "명시된 검증 명령 없음"
    criteria = "; ".join(_as_list(contract.get("validation_criteria"))) or "명시된 계약 검증 기준 없음"
    approvals = "; ".join(_as_list(contract.get("approval_required_actions"))) or "승인 필요 행동 없음"
    forbidden = "; ".join(_as_list(contract.get("forbidden_actions"))) or "금지 행동 없음"
    return "\n".join(
        [
            "너는 Cambrian이 이 프로젝트 안에 설치한 AI 회사의 실행 엔진이다.",
            f"작업: {contract.get('task') or ''}",
            f"투입 agent: {agents}",
            f"투입 skill: {skills}",
            f"변경 정책: {contract.get('change_policy') or 'proposal_only'}",
            f"검증 명령 후보: {validation}",
            f"계약 검증 기준: {criteria}",
            f"승인 필요 행동: {approvals}",
            f"금지 행동: {forbidden}",
            "소스 파일을 직접 수정했다고 주장하지 말고, patch_candidate 또는 analysis 형태로 답하라.",
            "반드시 response_contract에 맞는 YAML 또는 JSON으로 답하라.",
        ]
    )


def _infer_request_intent(request: str) -> str | None:
    lowered = request.lower()
    pairs = [
        ("bug_fix", ("bug", "fix", "error", "login", "auth", "버그", "오류", "에러", "로그인")),
        ("docs_update", ("docs", "readme", "문서")),
        ("small_refactor", ("refactor", "cleanup", "리팩터", "정리")),
        ("regression_test", ("test", "pytest", "테스트")),
    ]
    for intent, tokens in pairs:
        if any(token in lowered for token in tokens):
            return intent
    return None


def _parse_structured_payload(text: str) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    candidates = _extract_structured_candidates(text)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as json_exc:
            last_error = json_exc
            try:
                payload = yaml.safe_load(candidate)
            except yaml.YAMLError as yaml_exc:
                last_error = yaml_exc
                continue
        if isinstance(payload, dict):
            if candidate != text:
                warnings.append("structured reply was extracted from a fenced markdown block")
            payload = _normalize_reply_payload(payload)
            return payload, warnings
    if last_error is not None:
        raise ValueError(f"structured reply parse failed: {last_error}") from last_error
    raise ValueError("structured reply parse failed: no YAML or JSON mapping found")


def _normalize_reply_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if str(normalized.get("response_kind", "") or "").strip() != "patch_candidate":
        return normalized
    patch = normalized.get("patch")
    if not isinstance(patch, dict):
        return normalized
    aliases = {
        "target_path": ("target_path", "path", "file"),
        "old_text": ("old_text", "before"),
        "new_text": ("new_text", "after"),
        "reason": ("reason",),
        "related_tests": ("related_tests", "tests"),
    }
    for target_key, source_keys in aliases.items():
        if normalized.get(target_key) not in (None, ""):
            continue
        for source_key in source_keys:
            value = patch.get(source_key)
            if value not in (None, ""):
                normalized[target_key] = value
                break
    return normalized


def _extract_structured_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"```(?:yaml|yml|json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE):
        body = match.group(1).strip()
        if body:
            candidates.append(body)
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    return candidates


def _validate_reply_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    response_kind = str(payload.get("response_kind", "") or "").strip()
    if response_kind not in ALLOWED_RESPONSE_KINDS:
        errors.append("response_kind must be one of: analysis, patch_candidate, review, plan")
    if not str(payload.get("summary", "") or "").strip():
        errors.append("summary is required")
    if response_kind == "patch_candidate":
        for key in ("target_path", "old_text", "new_text", "reason"):
            if payload.get(key) is None or str(payload.get(key)).strip() == "":
                errors.append(f"{key} is required for patch_candidate")
    return errors


def _resolve_bridge_path(project_root: Path, ref: str, directory: Path, prefix: str) -> Path:
    root = Path(project_root).resolve()
    candidate = Path(str(ref))
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.exists():
        return candidate.resolve()
    directory = directory.resolve()
    if not directory.exists():
        raise FileNotFoundError(ref)
    wanted = str(ref).strip()
    for path in sorted(directory.glob(f"{prefix}_*.yaml")):
        if path.stem == wanted or path.name == wanted or path.stem.startswith(wanted):
            return path.resolve()
    raise FileNotFoundError(ref)


def _packet_from_dict(payload: dict[str, Any]) -> BridgePacket:
    return BridgePacket(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        packet_id=str(payload.get("packet_id", "")),
        created_at=str(payload.get("created_at", "")),
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
        workspace=str(payload.get("workspace", "")),
        request=str(payload.get("request", "")),
        request_intent=str(payload.get("request_intent")) if payload.get("request_intent") is not None else None,
        harness_summary=dict(payload.get("harness_summary", {}) if isinstance(payload.get("harness_summary"), dict) else {}),
        agent_summary=dict(payload.get("agent_summary", {}) if isinstance(payload.get("agent_summary"), dict) else {}),
        policy_summary=dict(payload.get("policy_summary", {}) if isinstance(payload.get("policy_summary"), dict) else {}),
        memory_summary=dict(payload.get("memory_summary", {}) if isinstance(payload.get("memory_summary"), dict) else {}),
        active_pack_context=dict(payload.get("active_pack_context", {}) if isinstance(payload.get("active_pack_context"), dict) else {}),
        response_contract=dict(payload.get("response_contract", {}) if isinstance(payload.get("response_contract"), dict) else {}),
        execution_contract=dict(payload.get("execution_contract", {}) if isinstance(payload.get("execution_contract"), dict) else {}),
        codex_claude_instruction=str(payload.get("codex_claude_instruction")) if payload.get("codex_claude_instruction") is not None else None,
        suggested_next_actions=[str(value) for value in payload.get("suggested_next_actions", []) if value],
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )


def _reply_from_dict(payload: dict[str, Any]) -> BridgeReply:
    return BridgeReply(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        reply_id=str(payload.get("reply_id", "")),
        created_at=str(payload.get("created_at", "")),
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        request=str(payload.get("request")) if payload.get("request") is not None else None,
        response_kind=str(payload.get("response_kind", "")),
        content=dict(payload.get("content", {}) if isinstance(payload.get("content"), dict) else {}),
        raw_text=str(payload.get("raw_text")) if payload.get("raw_text") is not None else None,
        source_reply_path=str(payload.get("source_reply_path")) if payload.get("source_reply_path") is not None else None,
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_request_ref=str(payload.get("linked_request_ref")) if payload.get("linked_request_ref") is not None else None,
        warnings=[str(value) for value in payload.get("warnings", []) if value],
        errors=[str(value) for value in payload.get("errors", []) if value],
    )


def _sorted_yaml_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted((path for path in directory.glob(pattern) if path.is_file()), key=lambda path: path.stat().st_mtime, reverse=True)


def _load_latest_packet(paths: list[Path]) -> BridgePacket | None:
    if not paths:
        return None
    try:
        return ProjectBridgeStore().load_packet(paths[0])
    except Exception as exc:
        logger.warning("latest bridge packet load failed: %s", exc)
        return None


def _load_latest_reply(paths: list[Path]) -> BridgeReply | None:
    if not paths:
        return None
    try:
        return ProjectBridgeStore().load_reply(paths[0])
    except Exception as exc:
        logger.warning("latest bridge reply load failed: %s", exc)
        return None
