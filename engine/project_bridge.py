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
        _augment_harness_summary_from_active_context(harness_summary, active_pack_context)
        _augment_agent_summary_from_active_context(agent_summary, active_pack_context)
        request_text = str(request or "").strip()
        intent = _infer_request_intent(request_text)
        packet_id = f"packet_{_timestamp()}_{_short_id()}"
        response_contract = _response_contract(active_pack_context)
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
        company_fit = contract.get("company_fit_report", {}) if isinstance(contract.get("company_fit_report"), dict) else {}
        if company_fit:
            lines.append("  company fit:")
            lines.append(f"    size: {company_fit.get('company_size') or 'unknown'}")
            lines.append(f"    target lift: {company_fit.get('target_lift_pct') or 30}%")
            gaps = _as_list(company_fit.get("coverage_gaps"))
            lines.append(f"    gaps: {', '.join(gaps[:3]) if gaps else 'none'}")
        company_blueprint = contract.get("company_blueprint", {}) if isinstance(contract.get("company_blueprint"), dict) else {}
        if company_blueprint:
            lines.append(f"  company os: {company_blueprint.get('compiler_version') or 'company_os_compiler'}")
        project_discussion_layer = (
            contract.get("project_discussion_layer", {}) if isinstance(contract.get("project_discussion_layer"), dict) else {}
        )
        if project_discussion_layer:
            roles = project_discussion_layer.get("roles", {}) if isinstance(project_discussion_layer.get("roles"), dict) else {}
            lines.append(
                f"  project discussion: {project_discussion_layer.get('status') or 'unknown'} / roles={len(roles)}"
            )
        context_intent = contract.get("context_intent_snapshot", {}) if isinstance(contract.get("context_intent_snapshot"), dict) else {}
        if context_intent:
            detected = context_intent.get("detected_intent", {}) if isinstance(context_intent.get("detected_intent"), dict) else {}
            quality = context_intent.get("quality_gate", {}) if isinstance(context_intent.get("quality_gate"), dict) else {}
            lines.append(
                f"  context intent: {detected.get('primary') or 'unknown'} / {quality.get('current_context_level') or 'unknown'}"
            )
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
        company_fit = contract.get("company_fit_report", {}) if isinstance(contract.get("company_fit_report"), dict) else {}
        if company_fit:
            gaps = _as_list(company_fit.get("coverage_gaps"))
            lines.extend(
                [
                    "- company_fit_report:",
                    f"  - company_size: {company_fit.get('company_size') or 'unknown'}",
                    f"  - target_lift_pct: {company_fit.get('target_lift_pct') or 30}",
                    f"  - coverage_gaps: {', '.join(gaps) if gaps else 'none'}",
                ]
            )
        company_blueprint = contract.get("company_blueprint", {}) if isinstance(contract.get("company_blueprint"), dict) else {}
        if company_blueprint:
            lines.extend(
                [
                    "- company_os:",
                    f"  - compiler_version: {company_blueprint.get('compiler_version') or 'company_os_compiler'}",
                    f"  - blueprint_id: {company_blueprint.get('blueprint_id') or 'none'}",
                ]
            )
        project_discussion_layer = (
            contract.get("project_discussion_layer", {}) if isinstance(contract.get("project_discussion_layer"), dict) else {}
        )
        if project_discussion_layer:
            roles = project_discussion_layer.get("roles", {}) if isinstance(project_discussion_layer.get("roles"), dict) else {}
            docs = (
                project_discussion_layer.get("document_contract", {})
                if isinstance(project_discussion_layer.get("document_contract"), dict)
                else {}
            )
            lines.extend(
                [
                    "- project_discussion_layer:",
                    f"  - status: {project_discussion_layer.get('status') or 'unknown'}",
                    f"  - roles: {', '.join(sorted(str(role_id) for role_id in roles)) or 'none'}",
                    f"  - missing_core_docs: {len(_as_list(docs.get('missing_core_docs')))}",
                ]
            )
        context_intent = contract.get("context_intent_snapshot", {}) if isinstance(contract.get("context_intent_snapshot"), dict) else {}
        if context_intent:
            detected = context_intent.get("detected_intent", {}) if isinstance(context_intent.get("detected_intent"), dict) else {}
            quality = context_intent.get("quality_gate", {}) if isinstance(context_intent.get("quality_gate"), dict) else {}
            relevance = context_intent.get("relevance_filter", {}) if isinstance(context_intent.get("relevance_filter"), dict) else {}
            lines.extend(
                [
                    "- context_intent_snapshot:",
                    f"  - intent: {detected.get('primary') or 'unknown'}",
                    f"  - confidence: {detected.get('confidence') or 'low'}",
                    f"  - context_level: {quality.get('current_context_level') or 'unknown'}",
                    f"  - selected_context_count: {relevance.get('selected_context_count') or 0}",
                ]
            )
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


def _augment_harness_summary_from_active_context(summary: dict[str, Any], active_pack_context: dict[str, Any]) -> None:
    """설치형 pack/custom harness 컨텍스트를 사람이 보는 bridge 요약에 반영한다."""
    if not isinstance(active_pack_context, dict) or not active_pack_context:
        return
    custom_harness = bool(active_pack_context.get("custom_harness"))
    harness_id = active_pack_context.get("harness_id") or active_pack_context.get("pack_id")
    if harness_id and (custom_harness or not summary.get("harness_id")):
        summary["harness_id"] = str(harness_id)
    project_type = active_pack_context.get("project_type") or active_pack_context.get("pack_kind")
    if not project_type and active_pack_context.get("custom_harness"):
        project_type = "custom_harness"
    if project_type and (custom_harness or not summary.get("project_type")):
        summary["project_type"] = str(project_type)
    stack = _as_list(active_pack_context.get("stack"))
    if not stack:
        stack = _stack_from_lane(active_pack_context.get("lane_label")) or _stack_from_lane(active_pack_context.get("lane_id"))
    if stack and (custom_harness or not _as_list(summary.get("stack"))):
        summary["stack"] = stack
    validation_commands = _as_list(active_pack_context.get("validation_commands"))
    if validation_commands and (custom_harness or not summary.get("test_command")):
        summary["test_command"] = validation_commands[0]
    selected_agents = _as_list(active_pack_context.get("selected_agents"))
    if selected_agents and (custom_harness or not _as_list(summary.get("active_agents"))):
        summary["active_agents"] = selected_agents


def _augment_agent_summary_from_active_context(summary: dict[str, Any], active_pack_context: dict[str, Any]) -> None:
    """Keep the visible packet agent list aligned with the active custom harness."""
    if not isinstance(active_pack_context, dict) or not active_pack_context:
        return
    selected_agents = _as_list(active_pack_context.get("selected_agents"))
    if not selected_agents:
        return
    if active_pack_context.get("custom_harness") or not _as_list(summary.get("active_agents")):
        summary["active_agents"] = selected_agents
        summary["preferred_lead"] = selected_agents[0]
        summary["preferred_support"] = selected_agents[1:3]


def _stack_from_lane(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[^A-Za-z0-9_.-]+", text) if part.strip()]
    return _dedupe([part for part in parts if part.lower() not in {"none", "unknown", "custom", "harness"}])


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


def _response_contract(active_pack_context: dict[str, Any] | None = None) -> dict[str, Any]:
    active = active_pack_context if isinstance(active_pack_context, dict) else {}
    llm_required_agents = _as_list(active.get("llm_required_agents"))
    evidence_required_keys = [
        "codebase evidence path citation",
        "risk boundary check",
        "validation command selection",
        "patch application state",
        "verdict rationale",
        "context intent resolution",
        "project discussion role check",
    ]
    evidence_guidance = [
        "cite the codebase evidence paths used for the conclusion",
        "separate confirmed/suspected domains from weak keyword evidence",
        "state whether risk_boundaries were checked",
        "explain which validation command should be run and why",
        "state whether any patch was applied and whether source code was modified",
        "state the verdict and why the evidence supports it",
        "state how current user intent was resolved from packet context",
        "cite project_discussion_layer context docs for product or direction claims",
    ]
    if llm_required_agents or active.get("llm_invocation_required"):
        evidence_required_keys.append("llm invocation evidence")
        evidence_guidance.append(
            "record llm_invocation_evidence for thinking agents, including mode/provider and selected agent ids"
        )
    return {
        "format": "YAML or JSON",
        "allowed_response_kinds": sorted(ALLOWED_RESPONSE_KINDS),
        "required_keys": ["response_kind", "summary"],
        "patch_candidate_required_keys": ["target_path", "old_text", "new_text", "reason"],
        "evidence_required_keys": evidence_required_keys,
        "evidence_guidance": evidence_guidance,
        "llm_required_agents": llm_required_agents,
        "company_guidance": [
            "state which company role owns context, execution proposal, and validation",
            "use project_discussion_layer for product, strategy, architecture, and next-step discussions",
            "read company_fit_report before answering and address any coverage_gaps",
            "read context_intent_snapshot before using memory or prior job records",
            "use company_blueprint as the operating contract for the installed AI company",
            "do not add duplicate agents when an existing role already covers the responsibility",
            "keep context_manager, execution_lead, and verification_owner responsibilities visible",
        ],
        "relearning_guidance": [
            "separate learning candidates from approved memory",
            "recommend revise or rebuild when evidence shows the company structure was wrong",
            "never promote new defaults without user review",
        ],
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
    codebase_evidence = dict(active_pack_context.get("codebase_evidence", {}) if isinstance(active_pack_context.get("codebase_evidence"), dict) else {})
    evidence_card = dict(active_pack_context.get("evidence_card", {}) if isinstance(active_pack_context.get("evidence_card"), dict) else {})
    if not evidence_card and isinstance(codebase_evidence.get("evidence_card"), dict):
        evidence_card = dict(codebase_evidence.get("evidence_card", {}))
    domain_confidence = dict(active_pack_context.get("domain_confidence", {}) if isinstance(active_pack_context.get("domain_confidence"), dict) else {})
    if not domain_confidence and isinstance(codebase_evidence.get("domain_confidence"), dict):
        domain_confidence = dict(codebase_evidence.get("domain_confidence", {}))
    quality_gate = dict(active_pack_context.get("quality_gate", {}) if isinstance(active_pack_context.get("quality_gate"), dict) else {})
    agent_evidence_context = dict(active_pack_context.get("agent_evidence_context", {}) if isinstance(active_pack_context.get("agent_evidence_context"), dict) else {})
    agent_runtime_contracts = dict(active_pack_context.get("agent_runtime_contracts", {}) if isinstance(active_pack_context.get("agent_runtime_contracts"), dict) else {})
    llm_required_agents = _as_list(active_pack_context.get("llm_required_agents"))
    llm_invocation_required = bool(active_pack_context.get("llm_invocation_required") or llm_required_agents)
    skill_evidence_context = dict(active_pack_context.get("skill_evidence_context", {}) if isinstance(active_pack_context.get("skill_evidence_context"), dict) else {})
    company_structure = dict(active_pack_context.get("company_structure", {}) if isinstance(active_pack_context.get("company_structure"), dict) else {})
    company_fit_report = dict(
        company_structure.get("company_fit_report", {}) if isinstance(company_structure.get("company_fit_report"), dict) else {}
    )
    company_blueprint = dict(active_pack_context.get("company_blueprint", {}) if isinstance(active_pack_context.get("company_blueprint"), dict) else {})
    harness_os_contract = dict(
        active_pack_context.get("harness_os_contract", {}) if isinstance(active_pack_context.get("harness_os_contract"), dict) else {}
    )
    relearning_policy = dict(active_pack_context.get("relearning_policy", {}) if isinstance(active_pack_context.get("relearning_policy"), dict) else {})
    marketplace_boundary = dict(
        active_pack_context.get("marketplace_boundary", {}) if isinstance(active_pack_context.get("marketplace_boundary"), dict) else {}
    )
    project_discussion_layer = dict(
        active_pack_context.get("project_discussion_layer", {})
        if isinstance(active_pack_context.get("project_discussion_layer"), dict)
        else {}
    )
    company_roles = dict(active_pack_context.get("company_roles", {}) if isinstance(active_pack_context.get("company_roles"), dict) else {})
    if not company_roles and isinstance(company_structure.get("active_roles"), dict):
        company_roles = dict(company_structure.get("active_roles", {}))
    responsibility_matrix = dict(active_pack_context.get("responsibility_matrix", {}) if isinstance(active_pack_context.get("responsibility_matrix"), dict) else {})
    if not responsibility_matrix and isinstance(company_structure.get("responsibility_matrix"), dict):
        responsibility_matrix = dict(company_structure.get("responsibility_matrix", {}))
    duplicate_guard = dict(active_pack_context.get("duplicate_guard", {}) if isinstance(active_pack_context.get("duplicate_guard"), dict) else {})
    if not duplicate_guard and isinstance(company_structure.get("duplicate_guard"), dict):
        duplicate_guard = dict(company_structure.get("duplicate_guard", {}))
    company_loop_context = dict(
        active_pack_context.get("company_loop_context", {}) if isinstance(active_pack_context.get("company_loop_context"), dict) else {}
    )
    context_intent_snapshot = dict(
        active_pack_context.get("context_intent_snapshot", {})
        if isinstance(active_pack_context.get("context_intent_snapshot"), dict)
        else {}
    )
    evidence_gap_report = dict(
        active_pack_context.get("evidence_gap_report", {}) if isinstance(active_pack_context.get("evidence_gap_report"), dict) else {}
    )
    risk_boundaries = dict(active_pack_context.get("risk_boundaries", {}) if isinstance(active_pack_context.get("risk_boundaries"), dict) else {})
    if not risk_boundaries and isinstance(codebase_evidence.get("risk_boundaries"), dict):
        risk_boundaries = dict(codebase_evidence.get("risk_boundaries", {}))
    evaluator_contract = dict(active_pack_context.get("evaluator_contract", {}) if isinstance(active_pack_context.get("evaluator_contract"), dict) else {})
    evidence_status = str(active_pack_context.get("evidence_status") or codebase_evidence.get("status") or "missing")
    manual_review_required = bool(active_pack_context.get("manual_review_required")) or evidence_status not in {"", "grounded"}
    evidence_warnings = _as_list(active_pack_context.get("evidence_warnings"))
    if manual_review_required and "manual review required" not in evidence_warnings:
        evidence_warnings.append("manual review required")
    must_do = [
        "요청을 설치된 하네스, 인력, 스킬, 정책 기준으로 분석한다.",
        "근거와 불확실성을 분리해서 설명한다.",
        "패치가 필요하면 자동 적용이 아니라 patch_candidate로 제안한다.",
        "검증 명령과 회귀 위험을 함께 적는다.",
        "response_contract에 맞는 YAML 또는 JSON으로 답한다.",
        "cite codebase_evidence paths used for the conclusion.",
        "record the risk boundary check before proposing a patch.",
        "explain validation command selection before claiming readiness.",
    ]
    if company_roles:
        must_do.append("state which AI company role is responsible for context, execution proposal, and verification.")
    if company_fit_report:
        must_do.append("read company_fit_report and address coverage_gaps before recommending next action.")
    if company_blueprint:
        must_do.append("treat company_blueprint as the operating context, not as a prompt snippet.")
    if project_discussion_layer:
        must_do.append("use project_discussion_layer before product, strategy, architecture, roadmap, or next-step claims.")
        must_do.append("cite project_discussion_layer document_contract and list missing context docs instead of inventing facts.")
    if relearning_policy:
        must_do.append("use relearning_policy to separate revise/rebuild candidates from approved memory.")
    if duplicate_guard:
        must_do.append("do not introduce duplicate agents when duplicate_guard says the existing workforce covers the role.")
    if company_loop_context.get("status") == "available":
        must_do.append("review company_loop_context before answering and carry forward prior unchecked risks.")
        must_do.append("distinguish promoted_memory from candidate_context_records; do not treat candidates as approved memory.")
    if context_intent_snapshot:
        must_do.append("resolve the current user intent with context_intent_snapshot before using company memory.")
        must_do.append("discard irrelevant recent memory when context_intent_snapshot marks it outside the request intent.")
    if evidence_gap_report:
        must_do.append("use evidence_gap_report to produce new evidence-backed findings instead of restating old memory.")
    if llm_invocation_required:
        must_do.append("record llm_invocation_evidence because selected AI agents require an LLM call for thinking work.")
    if validation_criteria:
        must_do.append("결과가 계약 validation_criteria를 어떻게 만족하는지 설명한다.")
    if domain_confidence:
        must_do.append("use domain_confidence to avoid treating weak domains as the harness core.")
    if quality_gate:
        must_do.append("respect quality_gate status before claiming the harness is ready.")
    if manual_review_required:
        must_do.append("manual review required: codebase_evidence is weak or incomplete, so do not make confident proof claims.")
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
        "codebase_evidence": codebase_evidence,
        "evidence_card": evidence_card,
        "domain_confidence": domain_confidence,
        "quality_gate": quality_gate,
        "agent_evidence_context": agent_evidence_context,
        "agent_runtime_contracts": agent_runtime_contracts,
        "llm_required_agents": llm_required_agents,
        "llm_invocation_required": llm_invocation_required,
        "skill_evidence_context": skill_evidence_context,
        "company_structure": company_structure,
        "company_fit_report": company_fit_report,
        "company_blueprint": company_blueprint,
        "harness_os_contract": harness_os_contract,
        "relearning_policy": relearning_policy,
        "marketplace_boundary": marketplace_boundary,
        "project_discussion_layer": project_discussion_layer,
        "company_roles": company_roles,
        "responsibility_matrix": responsibility_matrix,
        "duplicate_guard": duplicate_guard,
        "company_loop_context": company_loop_context,
        "context_intent_snapshot": context_intent_snapshot,
        "evidence_gap_report": evidence_gap_report,
        "risk_boundaries": risk_boundaries,
        "evaluator_contract": evaluator_contract,
        "evidence_status": evidence_status,
        "manual_review_required": manual_review_required,
        "evidence_warnings": _dedupe(evidence_warnings),
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
    evidence_paths = ", ".join(_contract_evidence_paths(contract)[:6]) or "명시된 codebase evidence path 없음"
    evidence_status = str(contract.get("evidence_status") or "missing")
    llm_required = ", ".join(_as_list(contract.get("llm_required_agents"))) or "none"
    company_roles = _company_role_summary(contract)
    company_loop = _company_loop_summary(contract)
    context_intent = _context_intent_summary(contract)
    project_discussion = _project_discussion_summary(contract)
    manual_review = "필요" if contract.get("manual_review_required") else "불필요"
    return "\n".join(
        [
            "너는 Cambrian이 이 프로젝트 안에 설치한 AI 회사의 실행 엔진이다.",
            f"작업: {contract.get('task') or ''}",
            f"투입 agent: {agents}",
            f"투입 skill: {skills}",
            f"변경 정책: {contract.get('change_policy') or 'proposal_only'}",
            f"codebase evidence 상태: {evidence_status}",
            f"codebase evidence path: {evidence_paths}",
            f"LLM-required agents: {llm_required}",
            f"AI company roles: {company_roles}",
            f"Project discussion layer: {project_discussion}",
            f"Company ledger: {company_loop}",
            f"Context intent: {context_intent}",
            f"manual review required: {manual_review}",
            f"검증 명령 후보: {validation}",
            f"계약 검증 기준: {criteria}",
            f"승인 필요 행동: {approvals}",
            f"금지 행동: {forbidden}",
            "응답에는 codebase evidence path citation, risk boundary check, validation command selection을 포함하라.",
            "소스 파일을 직접 수정했다고 주장하지 말고, patch_candidate 또는 analysis 형태로 답하라.",
            "반드시 response_contract에 맞는 YAML 또는 JSON으로 답하라.",
        ]
    )


def _contract_evidence_paths(contract: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    codebase_evidence = contract.get("codebase_evidence", {}) if isinstance(contract.get("codebase_evidence"), dict) else {}
    paths.extend(_as_list(codebase_evidence.get("existing_important_paths")))
    for context_key in ["agent_evidence_context", "skill_evidence_context"]:
        context = contract.get(context_key, {})
        if not isinstance(context, dict):
            continue
        for item in context.values():
            if isinstance(item, dict):
                paths.extend(_as_list(item.get("paths")))
    return _dedupe(paths)


def _company_role_summary(contract: dict[str, Any]) -> str:
    """실행 지시문에 표시할 회사 역할 요약을 만든다."""
    roles = contract.get("company_roles", {}) if isinstance(contract.get("company_roles"), dict) else {}
    if not roles:
        structure = contract.get("company_structure", {}) if isinstance(contract.get("company_structure"), dict) else {}
        roles = structure.get("active_roles", {}) if isinstance(structure.get("active_roles"), dict) else {}
    summaries: list[str] = []
    for role_id, role in roles.items():
        if not isinstance(role, dict):
            continue
        agent_id = str(role.get("agent_id") or "unassigned")
        summaries.append(f"{role_id}={agent_id}")
    return ", ".join(_dedupe(summaries)) or "company roles not assigned"


def _project_discussion_summary(contract: dict[str, Any]) -> str:
    layer = contract.get("project_discussion_layer", {}) if isinstance(contract.get("project_discussion_layer"), dict) else {}
    if not layer:
        return "project_discussion_layer=missing"
    roles = layer.get("roles", {}) if isinstance(layer.get("roles"), dict) else {}
    docs = layer.get("document_contract", {}) if isinstance(layer.get("document_contract"), dict) else {}
    existing_docs = _as_list(docs.get("existing_context_docs"))
    missing_docs = _as_list(docs.get("missing_core_docs"))
    return (
        f"status={layer.get('status') or 'unknown'}; roles={len(roles)}; "
        f"context_docs={len(existing_docs)}; missing_core_docs={len(missing_docs)}"
    )


def _company_loop_summary(contract: dict[str, Any]) -> str:
    """실행 지시문에 표시할 회사 ledger 요약을 만든다."""
    loop = contract.get("company_loop_context", {}) if isinstance(contract.get("company_loop_context"), dict) else {}
    status = str(loop.get("status") or "empty")
    context_count = len(loop.get("context_records", [])) if isinstance(loop.get("context_records"), list) else 0
    candidate_count = len(loop.get("candidate_context_records", [])) if isinstance(loop.get("candidate_context_records"), list) else 0
    verification_count = len(loop.get("verification_entries", [])) if isinstance(loop.get("verification_entries"), list) else 0
    promoted_memory = loop.get("promoted_memory", {}) if isinstance(loop.get("promoted_memory"), dict) else {}
    promoted_count = int(promoted_memory.get("total_count") or 0)
    return (
        f"{status}; context_records={context_count}; candidate_records={candidate_count}; "
        f"promoted_memory={promoted_count}; verification_entries={verification_count}"
    )


def _context_intent_summary(contract: dict[str, Any]) -> str:
    snapshot = contract.get("context_intent_snapshot", {}) if isinstance(contract.get("context_intent_snapshot"), dict) else {}
    if not snapshot:
        return "context_intent_snapshot=missing"
    intent = snapshot.get("detected_intent", {}) if isinstance(snapshot.get("detected_intent"), dict) else {}
    quality = snapshot.get("quality_gate", {}) if isinstance(snapshot.get("quality_gate"), dict) else {}
    relevance = snapshot.get("relevance_filter", {}) if isinstance(snapshot.get("relevance_filter"), dict) else {}
    return (
        f"intent={intent.get('primary') or 'unknown'}; confidence={intent.get('confidence') or 'low'}; "
        f"context_level={quality.get('current_context_level') or 'unknown'}; "
        f"selected_context={relevance.get('selected_context_count') or 0}"
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
