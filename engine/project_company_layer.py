"""프로젝트 안 AI 회사 계층 상태 모델."""

from __future__ import annotations

import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.exceptions import CambrianError
from engine.project_pack_install import SCHEMA_VERSION, _relative, _slug

logger = logging.getLogger(__name__)

OFFICE_ORDER = ["context", "direction", "execution", "verification"]
LEAN_COMPANY_MODE = "lean_project_company"
COMPANY_EXPANSION_BLOCKED_TYPES = [
    "extra_office",
    "decorative_role",
    "speculative_agent",
    "uncited_workflow",
]


class CompanyLayerError(CambrianError):
    """Company Layer 입력과 운영 상태 오류."""

OFFICE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "context": {
        "label": "Context Office",
        "korean_label": "기억실",
        "role": "프로젝트 기억과 작업 맥락을 관리한다.",
        "required_components": ["project_profile", "memory_lessons", "decision_history", "mistake_log"],
    },
    "direction": {
        "label": "Direction Office",
        "korean_label": "전략실",
        "role": "로드맵, 우선순위, 다음 행동을 결정한다.",
        "required_components": ["roadmap", "backlog", "priority_policy", "boardroom_decisions"],
    },
    "execution": {
        "label": "Execution Office",
        "korean_label": "실행팀",
        "role": "작업 분해, 에이전트 배치, 패치 제안을 수행한다.",
        "required_components": ["workforce", "job_router", "team_registry", "active_jobs"],
    },
    "verification": {
        "label": "Verification Office",
        "korean_label": "감사실",
        "role": "검증, proof, 회귀 위험, pass/hold/rollback 판정을 관리한다.",
        "required_components": ["validation_policy", "evidence_ledger", "review_gate", "proof_auditor"],
    },
}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
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


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """YAML 파일을 저장한다."""
    target = Path(path).resolve()
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML 파일을 dict로 읽고 실패 시 빈 dict를 반환한다."""
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("company layer YAML 읽기 실패: %s (%s)", target, exc)
        return {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("company layer YAML top-level mapping 아님: %s", target)
        return {}
    return payload


def default_company_dir(project_root: Path) -> Path:
    """Company Layer 상태 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "company"


def default_company_status_path(project_root: Path) -> Path:
    """Company Layer 상태 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "status.yaml"


def default_company_charter_path(project_root: Path) -> Path:
    """Company Layer charter 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "charter.yaml"


def default_company_task_schedule_path(project_root: Path) -> Path:
    """Company Layer task schedule 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "task_schedule.yaml"


def default_company_office_path(project_root: Path, office_id: str) -> Path:
    """개별 office skeleton 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "offices" / f"{office_id}.yaml"


def default_company_context_records_path(project_root: Path) -> Path:
    """Context Office 장기 context 후보 기록 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "context" / "records.yaml"


def default_company_context_decision_history_path(project_root: Path) -> Path:
    """Context Office 결정 이력 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "context" / "decision_history.yaml"


def default_company_context_lessons_path(project_root: Path) -> Path:
    """Context Office 교훈 ledger 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "context" / "lessons.yaml"


def default_company_context_mistakes_path(project_root: Path) -> Path:
    """Context Office 반복 실수 후보 ledger 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "context" / "mistakes.yaml"


def default_company_context_promotion_review_path(project_root: Path) -> Path:
    """Context 후보 기억 승격 검토 packet 경로를 반환한다."""
    return default_company_dir(project_root) / "context" / "promotion_review.yaml"


def default_company_verification_ledger_path(project_root: Path) -> Path:
    """Verification Office의 job 검증 ledger 파일 경로를 반환한다."""
    return default_company_dir(project_root) / "verification" / "ledger.yaml"


def default_company_discussion_agents_path(project_root: Path) -> Path:
    return default_company_dir(project_root) / "discussion" / "agents.yaml"


def default_company_product_boardroom_dir(project_root: Path) -> Path:
    return default_company_dir(project_root) / "product_boardroom"


def default_company_product_boardroom_agents_path(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "agents.yaml"


def default_company_product_boardroom_conversations_dir(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "conversations"


def default_company_product_boardroom_requests_dir(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "requests"


def default_company_product_boardroom_latest_request_path(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "latest_ai_request.yaml"


def default_company_product_boardroom_decision_path(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "decision_packet.yaml"


def default_company_product_boardroom_questions_path(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "open_questions.yaml"


def default_company_product_boardroom_agent_prompts_dir(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "agent_prompts"


def default_company_product_boardroom_agent_prompt_path(project_root: Path, agent_id: str) -> Path:
    return default_company_product_boardroom_agent_prompts_dir(project_root) / f"{_slug(agent_id, 'agent')}.md"


def default_company_product_boardroom_protocol_path(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "meeting_protocol.md"


def default_company_product_boardroom_agenda_path(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "agenda.yaml"


def default_company_product_boardroom_decision_history_path(project_root: Path) -> Path:
    return default_company_product_boardroom_dir(project_root) / "decision_history.yaml"


PROJECT_DISCUSSION_CORE_DOCS = [
    "CONTEXT_INDEX.md",
    "PROJECT_BRIEF.md",
    "PRODUCT_CONSTITUTION.md",
    "ROADMAP.md",
    "DECISION_LOG.md",
    "ARCHITECTURE.md",
    "RISK_BOUNDARIES.md",
    "VALIDATION_PLAYBOOK.md",
    "OPEN_QUESTIONS.md",
]

PROJECT_DISCUSSION_SUPPORTING_DOCS = [
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "TODO.md",
    "MEMORY.md",
    "memory/mistakes.md",
    "docs/product/00_INDEX.md",
    "docs/product/14_PRODUCT_CONSTITUTION.md",
    "docs/product/42_TEN_YEAR_ARCHITECTURE.md",
]

PRODUCT_BOARDROOM_AGENT_IDS = ["ceo-agent", "cto-agent", "coo-agent"]

PRODUCT_BOARDROOM_CONTEXT_DOCS = [
    ".cambrian/mission.yaml",
    ".cambrian/mission/operator.yaml",
    ".cambrian/company/discussion/agents.yaml",
    ".cambrian/company/status.yaml",
    "CONTEXT_INDEX.md",
    "PROJECT_BRIEF.md",
    "README.md",
    "TODO.md",
    "docs/product/00_INDEX.md",
    "docs/product/14_PRODUCT_CONSTITUTION.md",
    "docs/product/42_TEN_YEAR_ARCHITECTURE.md",
    "docs/release/NEXT_SESSION_HANDOFF.md",
]

AI_BOARDROOM_TURN_REQUIRED_FIELDS = [
    "position",
    "decision",
    "evidence_refs",
    "assumptions",
    "risks",
    "next_constraint",
]

AI_BOARDROOM_AUTH_VALUES = {"ai_agent", "external_ai_agent", "llm_agent", "model_agent"}


def _existing_refs(root: Path, refs: list[str]) -> list[str]:
    """존재하는 상대 경로만 반환한다."""
    found: list[str] = []
    for ref in refs:
        path = root / ref
        if path.exists():
            found.append(ref)
    return found


def _dedupe_refs(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def build_project_discussion_layer(
    project_root: Path,
    *,
    harness_id: str,
    goal: str | None = None,
    codebase_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    evidence = codebase_evidence if isinstance(codebase_evidence, dict) else {}
    evidence_card = evidence.get("evidence_card", {}) if isinstance(evidence.get("evidence_card"), dict) else {}
    identity_evidence = [
        str(item).strip()
        for item in evidence_card.get("identity_evidence", [])
        if isinstance(item, str) and item.strip()
    ]
    existing_core_docs = _existing_refs(root, list(PROJECT_DISCUSSION_CORE_DOCS))
    existing_supporting_docs = _existing_refs(root, list(PROJECT_DISCUSSION_SUPPORTING_DOCS))
    existing_context_docs = _dedupe_refs([*existing_core_docs, *existing_supporting_docs, *identity_evidence])
    missing_core_docs = [doc for doc in PROJECT_DISCUSSION_CORE_DOCS if doc not in existing_core_docs]
    status = "ready" if existing_context_docs else "needs_context_docs"
    if existing_context_docs and missing_core_docs:
        status = "partial"
    roles = {
        "ceo-agent": {
            "role_id": "ceo-agent",
            "office": "direction",
            "title": "CEO",
            "responsibility": "Own product direction, customer value, business risk, and scope discipline before implementation.",
            "decision_scope": ["product_direction", "market_positioning", "priority_tradeoff", "scope_boundary"],
        },
        "cto-agent": {
            "role_id": "cto-agent",
            "office": "direction",
            "title": "CTO",
            "responsibility": "Own architecture, technical risk, maintainability, and long-term platform choices.",
            "decision_scope": ["architecture", "technical_risk", "system_boundary", "long_term_maintainability"],
        },
        "coo-agent": {
            "role_id": "coo-agent",
            "office": "execution",
            "title": "COO",
            "responsibility": "Own execution order, operating cadence, bottlenecks, and handoff clarity.",
            "decision_scope": ["execution_order", "operating_cadence", "blocked_work", "handoff"],
        },
        "pm-agent": {
            "role_id": "pm-agent",
            "office": "context",
            "title": "PM",
            "responsibility": "Own user intent, requirements clarity, UX priority, and acceptance criteria.",
            "decision_scope": ["user_intent", "requirements", "acceptance_criteria", "ux_priority"],
        },
        "context-archivist-agent": {
            "role_id": "context-archivist-agent",
            "office": "context",
            "title": "Context Archivist",
            "responsibility": "Own context index, decision log hygiene, unresolved questions, and source citations.",
            "decision_scope": ["context_index", "decision_log", "missing_docs", "unresolved_questions"],
        },
    }
    shared_citations = existing_context_docs[:10]
    for role in roles.values():
        role["required_citations"] = shared_citations
        role["approval_policy"] = "proposal_only"
    return {
        "schema_version": SCHEMA_VERSION,
        "layer_id": f"project-discussion-{_slug(harness_id, 'harness')}",
        "status": status,
        "harness_id": harness_id,
        "goal": str(goal or "").strip(),
        "purpose": "Keep project discussion, direction, architecture, execution order, and context hygiene inside the installed harness.",
        "roles": roles,
        "document_contract": {
            "core_docs": list(PROJECT_DISCUSSION_CORE_DOCS),
            "supporting_docs": list(PROJECT_DISCUSSION_SUPPORTING_DOCS),
            "existing_core_docs": existing_core_docs,
            "existing_supporting_docs": existing_supporting_docs,
            "existing_context_docs": existing_context_docs,
            "missing_core_docs": missing_core_docs,
            "missing_docs_are_blockers": False,
            "policy": "Missing docs must be reported as context gaps; do not invent project facts.",
        },
        "discussion_triggers": [
            "direction",
            "strategy",
            "roadmap",
            "architecture",
            "product",
            "priority",
            "next step",
            "business",
            "context",
            "goal",
            "risk",
            "why",
        ],
        "meeting_policy": {
            "source_mutation": False,
            "auto_decision": False,
            "requires_user_approval_for_direction_change": True,
            "must_cite_existing_context_docs": True,
            "must_list_missing_context_docs": True,
            "proof_claim_allowed_without_runtime_evidence": False,
        },
        "response_shape": [
            "role_view_summary",
            "context_docs_used",
            "missing_context_docs",
            "recommended_next_decision",
            "unresolved_questions",
        ],
    }


def save_project_discussion_layer(project_root: Path, layer: dict[str, Any]) -> Path:
    roles = layer.get("roles", {}) if isinstance(layer.get("roles"), dict) else {}
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "artifact_kind": "project_discussion_layer",
        "project_discussion_layer": dict(layer),
        "agents": [dict(role) for role in roles.values() if isinstance(role, dict)],
    }
    return _save_yaml(default_company_discussion_agents_path(project_root), payload)


def _product_boardroom_context_refs(root: Path) -> list[str]:
    refs = _existing_refs(root, list(PRODUCT_BOARDROOM_CONTEXT_DOCS))
    refs.extend(
        _existing_refs(
            root,
            [
                ".cambrian/company/product_boardroom/decision_packet.yaml",
                ".cambrian/company/product_boardroom/open_questions.yaml",
            ],
        )
    )
    return _dedupe_refs(refs)


def _mission_goal_from_state(root: Path) -> str:
    mission_path = root / ".cambrian" / "mission.yaml"
    mission = _load_yaml(mission_path) if mission_path.exists() else {}
    return str(mission.get("goal") or "").strip()


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    text = str(value or "").strip()
    return [text] if text else []


def _is_ai_authored_turn(raw: dict[str, Any]) -> bool:
    if raw.get("ai_agent") is True:
        return True
    authorship = str(raw.get("turn_authorship") or raw.get("authorship") or raw.get("source") or "").strip().lower()
    return authorship in AI_BOARDROOM_AUTH_VALUES


def _normalize_ai_boardroom_turn(agent_id: str, contract: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CompanyLayerError(f"{agent_id} AI turn must be a mapping")
    missing = [field for field in AI_BOARDROOM_TURN_REQUIRED_FIELDS if field not in raw]
    if missing:
        raise CompanyLayerError(f"{agent_id} AI turn is missing required fields: {', '.join(missing)}")
    if not _is_ai_authored_turn(raw):
        raise CompanyLayerError(f"{agent_id} turn must declare ai_agent: true or turn_authorship: ai_agent")
    evidence_refs = _as_text_list(raw.get("evidence_refs"))
    if not evidence_refs:
        raise CompanyLayerError(f"{agent_id} AI turn must cite at least one evidence_ref")
    return {
        "speaker": agent_id,
        "title": contract.get("title") or raw.get("title"),
        "agent_kind": "ai_agent",
        "turn_source": "ai_agent_reply",
        "turn_authorship": str(raw.get("turn_authorship") or raw.get("authorship") or "ai_agent"),
        "ai_agent_verified": True,
        "agent_prompt_ref": contract.get("agent_prompt_ref") or raw.get("agent_prompt_ref"),
        "required_questions": contract.get("must_answer") or [],
        "position": str(raw.get("position") or "").strip(),
        "decision": str(raw.get("decision") or "").strip(),
        "evidence_refs": evidence_refs,
        "assumptions": _as_text_list(raw.get("assumptions")),
        "risks": _as_text_list(raw.get("risks")),
        "next_constraint": str(raw.get("next_constraint") or "").strip(),
    }


def _extract_ai_boardroom_turns(reply: dict[str, Any], agents_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    role_views = reply.get("role_views") if isinstance(reply.get("role_views"), dict) else {}
    turns_by_speaker: dict[str, dict[str, Any]] = {}
    raw_turns = reply.get("turns")
    if isinstance(raw_turns, list):
        for item in raw_turns:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker") or item.get("agent_id") or item.get("role_id") or "").strip()
            if speaker:
                turns_by_speaker[speaker] = item
    turns: list[dict[str, Any]] = []
    for agent_id in PRODUCT_BOARDROOM_AGENT_IDS:
        raw = role_views.get(agent_id)
        if not isinstance(raw, dict):
            raw = turns_by_speaker.get(agent_id, {})
        turns.append(_normalize_ai_boardroom_turn(agent_id, agents_by_id.get(agent_id, {}), raw))
    return turns


def _ai_boardroom_open_questions(reply: dict[str, Any], turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_questions = reply.get("open_questions")
    if isinstance(raw_questions, list) and raw_questions:
        questions: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_questions, start=1):
            if isinstance(item, dict):
                question = str(item.get("question") or "").strip()
                owner = str(item.get("owner") or "").strip()
                qid = str(item.get("id") or f"ai-question-{idx:03d}").strip()
            else:
                question = str(item or "").strip()
                owner = ""
                qid = f"ai-question-{idx:03d}"
            if question:
                questions.append({"id": qid, "question": question, "owner": owner or "boardroom"})
        if questions:
            return questions
    generated: list[dict[str, Any]] = []
    for turn in turns:
        owner = str(turn.get("speaker") or "boardroom")
        constraint = str(turn.get("next_constraint") or "").strip()
        if constraint:
            generated.append(
                {
                    "id": f"{owner}-next-constraint",
                    "question": f"What proof closes this constraint: {constraint}",
                    "owner": owner,
                }
            )
    return generated


def _product_boardroom_agents(root: Path, goal: str, context_refs: list[str]) -> list[dict[str, Any]]:
    shared_contract = {
        "agent_kind": "ai_agent",
        "runtime": "external_ai_worker",
        "operating_mode": "product_discussion_ai_agent",
        "goal": goal,
        "required_context_refs": context_refs[:12],
        "turn_source": "ai_agent_reply",
        "requires_ai_generated_turn": True,
        "template_turn_allowed": False,
        "ai_agent_contract_version": "1.0.0",
        "approval_policy": "proposal_only",
        "can_modify_source": False,
        "can_call_provider_api": False,
        "must_cite_existing_context": True,
        "must_mark_assumptions": True,
    }
    return [
        {
            **shared_contract,
            "agent_id": "ceo-agent",
            "role_id": "ceo-agent",
            "title": "CEO",
            "office": "direction",
            "agent_prompt_ref": _relative(default_company_product_boardroom_agent_prompt_path(root, "ceo-agent"), root),
            "mission": "Keep Cambrian focused on external-user value, market position, release trust, and scope discipline.",
            "discussion_lens": [
                "customer outcome",
                "business priority",
                "positioning",
                "what not to build yet",
            ],
            "must_answer": [
                "What product outcome matters most now?",
                "What should be cut or delayed?",
                "What proof would make a real user trust the next step?",
            ],
        },
        {
            **shared_contract,
            "agent_id": "cto-agent",
            "role_id": "cto-agent",
            "title": "CTO",
            "office": "direction",
            "agent_prompt_ref": _relative(default_company_product_boardroom_agent_prompt_path(root, "cto-agent"), root),
            "mission": "Protect architecture, implementation simplicity, reliability gates, and long-term maintainability.",
            "discussion_lens": [
                "architecture fit",
                "failure mode",
                "testability",
                "technical debt",
            ],
            "must_answer": [
                "What is the smallest technical move that preserves the architecture?",
                "What can break if the 24h loop repeats this work?",
                "What validation evidence must exist before promotion?",
            ],
        },
        {
            **shared_contract,
            "agent_id": "coo-agent",
            "role_id": "coo-agent",
            "title": "COO",
            "office": "execution",
            "agent_prompt_ref": _relative(default_company_product_boardroom_agent_prompt_path(root, "coo-agent"), root),
            "mission": "Turn product direction into one bounded operating step with clear cadence, handoff, and blockers.",
            "discussion_lens": [
                "next action",
                "operating cadence",
                "handoff clarity",
                "blocker removal",
            ],
            "must_answer": [
                "What is the next bounded mission job?",
                "What must the worker stop after producing?",
                "What human approval gate must stay closed?",
            ],
        },
    ]


def _render_product_boardroom_agent_prompt(agent: dict[str, Any]) -> str:
    lines = [
        f"# Cambrian Product Boardroom: {agent.get('title')}",
        "",
        "You are an AI agent inside the Cambrian 24h company loop.",
        "You must produce an original role-specific boardroom turn; Cambrian templates may not speak for you.",
        "",
        "## AI Agent Contract",
        "- agent_kind: ai_agent",
        "- turn_source: ai_agent_reply",
        "- template_turn_allowed: false",
        "- Your turn is not valid unless it declares ai_agent: true or turn_authorship: ai_agent.",
        "",
        "## Mission",
        str(agent.get("mission") or ""),
        "",
        "## Non-Negotiable Boundaries",
        "- Do not apply source patches.",
        "- Do not push git.",
        "- Do not deploy, publish, spend money, touch secrets, or migrate databases.",
        "- Do not claim proof without runtime evidence.",
        "- Mark unknown facts as assumptions.",
        "- Cite installed context refs when making product claims.",
        "",
        "## Discussion Lens",
    ]
    lines.extend(f"- {item}" for item in agent.get("discussion_lens", []) if item)
    lines.extend(
        [
            "",
            "## Required Questions",
        ]
    )
    lines.extend(f"- {item}" for item in agent.get("must_answer", []) if item)
    lines.extend(
        [
            "",
            "## Output Shape",
            "- ai_agent",
            "- turn_authorship",
            "- position",
            "- decision",
            "- evidence_refs",
            "- assumptions",
            "- risks",
            "- next_constraint",
            "",
        ]
    )
    return "\n".join(lines)


def _render_product_boardroom_protocol(goal: str, agents: list[dict[str, Any]]) -> str:
    agent_ids = [str(agent.get("agent_id") or "") for agent in agents if agent.get("agent_id")]
    return "\n".join(
        [
            "# Cambrian CEO/CTO/COO Product Boardroom Protocol",
            "",
            "## Purpose",
            "Force the 24h company loop to discuss product direction before repeated mission work.",
            "",
            "## Goal",
            goal,
            "",
            "## Required Agents",
            *(f"- {agent_id}" for agent_id in agent_ids),
            "",
            "## AI Agent Requirement",
            "- CEO, CTO, and COO turns must come from AI agent reply content.",
            "- Cambrian may create request packets and validate replies, but it must not fabricate role turns.",
            "- A decision packet is ready_for_mission only after all three AI agent turns are ingested.",
            "",
            "## Meeting Order",
            "1. CEO states the external-user product outcome and scope cut.",
            "2. CTO states the architecture constraint and validation proof.",
            "3. COO states the next bounded mission job and stop condition.",
            "4. The meeting writes exactly one decision packet.",
            "",
            "## Hard Stop Conditions",
            "- Missing context refs must be reported.",
            "- Template or placeholder turns cannot create a ready_for_mission decision packet.",
            "- Direction changes require human approval.",
            "- Source patches, git push, deploy, publish, secrets, spend, and migrations are forbidden.",
            "- The next mission may open at most one job and must validate before sync.",
            "",
        ]
    )


def _save_product_boardroom_support_files(root: Path, goal: str, agents: list[dict[str, Any]]) -> dict[str, Any]:
    prompt_refs: list[str] = []
    for agent in agents:
        agent_id = str(agent.get("agent_id") or agent.get("role_id") or "").strip()
        if not agent_id:
            continue
        path = default_company_product_boardroom_agent_prompt_path(root, agent_id)
        _atomic_write_text(path, _render_product_boardroom_agent_prompt(agent))
        prompt_refs.append(_relative(path, root))
    protocol_path = default_company_product_boardroom_protocol_path(root)
    _atomic_write_text(protocol_path, _render_product_boardroom_protocol(goal, agents))
    return {
        "agent_prompt_refs": prompt_refs,
        "meeting_protocol_ref": _relative(protocol_path, root),
    }


def _ensure_product_boardroom_history(root: Path) -> Path:
    path = default_company_product_boardroom_decision_history_path(root)
    if not path.exists():
        _save_yaml(
            path,
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": _now(),
                "artifact_kind": "product_boardroom_decision_history",
                "decisions": [],
                "source_code_modified_by_cambrian": False,
                "provider_api_called_by_cambrian": False,
            },
        )
    return path


def _save_product_boardroom_agenda(
    root: Path,
    *,
    goal: str,
    topic: str,
    input_refs: list[str],
    open_questions: list[dict[str, Any]],
) -> Path:
    agenda = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "artifact_kind": "product_boardroom_agenda",
        "status": "ready",
        "goal": goal,
        "next_topic": topic,
        "input_refs": _dedupe_refs(input_refs),
        "ai_agent_turns_required": True,
        "template_turn_allowed": False,
        "standing_order": [
            "CEO: external-user outcome and scope cut",
            "CTO: architecture constraint and validation proof",
            "COO: next bounded job and stop condition",
            "Boardroom: exactly one decision packet",
        ],
        "open_questions": open_questions,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    return _save_yaml(default_company_product_boardroom_agenda_path(root), agenda)


def _append_product_boardroom_decision_history(root: Path, decision_packet: dict[str, Any]) -> Path:
    path = _ensure_product_boardroom_history(root)
    payload = _load_yaml(path)
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
    record = {
        "recorded_at": _now(),
        "topic": decision_packet.get("topic"),
        "status": decision_packet.get("status"),
        "conversation_ref": decision_packet.get("conversation_ref"),
        "decision_packet_ref": _relative(default_company_product_boardroom_decision_path(root), root),
        "consensus": decision_packet.get("consensus"),
        "mission_gate": decision_packet.get("mission_gate"),
        "ai_agent_turns_verified": bool(decision_packet.get("ai_agent_turns_verified")),
        "ai_reply_ref": decision_packet.get("ai_reply_ref"),
        "open_question_count": len(decision_packet.get("open_questions", []))
        if isinstance(decision_packet.get("open_questions"), list)
        else 0,
    }
    decisions.append(record)
    payload.update(
        {
            "schema_version": SCHEMA_VERSION,
            "updated_at": _now(),
            "artifact_kind": "product_boardroom_decision_history",
            "decisions": decisions,
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        }
    )
    return _save_yaml(path, payload)


def install_product_boardroom(project_root: Path, goal: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    resolved_goal = str(goal or "").strip() or _mission_goal_from_state(root) or "Keep product direction aligned before each 24h company tick."
    context_refs = _product_boardroom_context_refs(root)
    agents = _product_boardroom_agents(root, resolved_goal, context_refs)
    support_files = _save_product_boardroom_support_files(root, resolved_goal, agents)
    history_path = _ensure_product_boardroom_history(root)
    agenda_path = _save_product_boardroom_agenda(
        root,
        goal=resolved_goal,
        topic="next product decision",
        input_refs=context_refs,
        open_questions=[],
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "artifact_kind": "product_boardroom_agents",
        "boardroom_id": "ceo-cto-coo-product-boardroom",
        "status": "ready" if context_refs else "needs_context",
        "purpose": "Make CEO, CTO, and COO AI agent discussion a required decision packet before autonomous company work repeats.",
        "goal": resolved_goal,
        "ai_agent_required": True,
        "ai_agent_turns_required": True,
        "template_turn_allowed": False,
        "agent_ids": list(PRODUCT_BOARDROOM_AGENT_IDS),
        "agents": agents,
        "agent_prompt_refs": support_files["agent_prompt_refs"],
        "meeting_protocol_ref": support_files["meeting_protocol_ref"],
        "agenda_ref": _relative(agenda_path, root),
        "decision_history_ref": _relative(history_path, root),
        "context_contract": {
            "context_refs": context_refs,
            "missing_context_is_blocker": False,
            "policy": "Agents may reason from installed context refs only; unknown facts must be marked as assumptions.",
        },
        "meeting_policy": {
            "auto_apply": False,
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
            "requires_user_approval_for_direction_change": True,
            "max_decisions_per_meeting": 1,
            "output_required": "decision_packet",
            "decision_packet_requires_ai_agent_turns": True,
        },
    }
    saved = _save_yaml(default_company_product_boardroom_agents_path(root), payload)
    return {
        "ok": True,
        "status": "product_boardroom_installed",
        "boardroom_id": payload["boardroom_id"],
        "agent_ids": list(PRODUCT_BOARDROOM_AGENT_IDS),
        "agent_count": len(agents),
        "agents_ref": _relative(saved, root),
        "agent_prompt_refs": support_files["agent_prompt_refs"],
        "meeting_protocol_ref": support_files["meeting_protocol_ref"],
        "agenda_ref": _relative(agenda_path, root),
        "decision_history_ref": _relative(history_path, root),
        "context_refs": context_refs,
        "next_command": 'cambrian company boardroom convene --topic "next product decision" --json',
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }


def product_boardroom_status(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    agents_path = default_company_product_boardroom_agents_path(root)
    protocol_path = default_company_product_boardroom_protocol_path(root)
    agenda_path = default_company_product_boardroom_agenda_path(root)
    history_path = default_company_product_boardroom_decision_history_path(root)
    decision_path = default_company_product_boardroom_decision_path(root)
    questions_path = default_company_product_boardroom_questions_path(root)
    agents_payload = _load_yaml(agents_path) if agents_path.exists() else {}
    agents = agents_payload.get("agents") if isinstance(agents_payload.get("agents"), list) else []
    agent_ids = [
        str(agent.get("agent_id") or agent.get("role_id") or "").strip()
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("agent_id") or agent.get("role_id") or "").strip()
    ]
    installed = all(agent_id in agent_ids for agent_id in PRODUCT_BOARDROOM_AGENT_IDS)
    ai_agent_contract_ready = installed and all(
        isinstance(agent, dict)
        and str(agent.get("agent_kind") or "") == "ai_agent"
        and str(agent.get("turn_source") or "") == "ai_agent_reply"
        and agent.get("requires_ai_generated_turn") is True
        and agent.get("template_turn_allowed") is False
        for agent in agents
        if str(agent.get("agent_id") or agent.get("role_id") or "").strip() in PRODUCT_BOARDROOM_AGENT_IDS
    )
    latest_decision = _load_yaml(decision_path) if decision_path.exists() else {}
    latest_request_path = default_company_product_boardroom_latest_request_path(root)
    latest_request = _load_yaml(latest_request_path) if latest_request_path.exists() else {}
    history = _load_yaml(history_path) if history_path.exists() else {}
    open_questions = _load_yaml(questions_path) if questions_path.exists() else {}
    status = "boardroom_ready" if installed else "not_installed"
    if agents_path.exists() and not installed:
        status = "partial"
    if installed and not ai_agent_contract_ready:
        status = "ai_agent_contract_required"
    return {
        "ok": True,
        "status": status,
        "boardroom_id": agents_payload.get("boardroom_id") or "ceo-cto-coo-product-boardroom",
        "installed": installed,
        "ai_agent_required": True,
        "ai_agent_contract_ready": ai_agent_contract_ready,
        "ai_agent_turns_required": True,
        "agent_ids": agent_ids,
        "required_agent_ids": list(PRODUCT_BOARDROOM_AGENT_IDS),
        "agents_ref": _relative(agents_path, root) if agents_path.exists() else None,
        "agent_prompt_refs": agents_payload.get("agent_prompt_refs") or [],
        "meeting_protocol_ref": _relative(protocol_path, root) if protocol_path.exists() else agents_payload.get("meeting_protocol_ref"),
        "agenda_ref": _relative(agenda_path, root) if agenda_path.exists() else agents_payload.get("agenda_ref"),
        "decision_history_ref": _relative(history_path, root) if history_path.exists() else agents_payload.get("decision_history_ref"),
        "decision_count": len(history.get("decisions", [])) if isinstance(history.get("decisions"), list) else 0,
        "latest_ai_request_ref": _relative(latest_request_path, root) if latest_request_path.exists() else None,
        "latest_ai_request_status": latest_request.get("status") if latest_request else None,
        "latest_ai_request_generated_at": latest_request.get("generated_at") if latest_request else None,
        "latest_decision_ref": _relative(decision_path, root) if decision_path.exists() else None,
        "latest_decision_status": latest_decision.get("status") if latest_decision else None,
        "latest_decision_ai_agent_turns_verified": bool(latest_decision.get("ai_agent_turns_verified")) if latest_decision else False,
        "open_questions_ref": _relative(questions_path, root) if questions_path.exists() else None,
        "open_question_count": len(open_questions.get("questions", [])) if isinstance(open_questions.get("questions"), list) else 0,
        "context_refs": _product_boardroom_context_refs(root),
        "next_command": (
            'cambrian company boardroom convene --topic "next product decision" --json'
            if installed
            else 'cambrian company boardroom install --goal "Keep product direction aligned" --json'
        ),
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }


def convene_product_boardroom(project_root: Path, topic: str, context: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    clean_topic = str(topic or "").strip()
    if not clean_topic:
        raise CompanyLayerError("boardroom topic is required")

    status = product_boardroom_status(root)
    if not status.get("installed"):
        install_product_boardroom(root)
        status = product_boardroom_status(root)

    context_refs = _product_boardroom_context_refs(root)
    goal = _mission_goal_from_state(root) or "Keep product direction aligned before each 24h company tick."
    agents_path = default_company_product_boardroom_agents_path(root)
    agents_payload = _load_yaml(agents_path) if agents_path.exists() else {}
    if not agents_payload.get("agent_prompt_refs") or not default_company_product_boardroom_protocol_path(root).exists():
        install_product_boardroom(root, goal=goal)
        status = product_boardroom_status(root)
        agents_payload = _load_yaml(agents_path) if agents_path.exists() else {}
    missing_core_docs = [doc for doc in PRODUCT_BOARDROOM_CONTEXT_DOCS if not (root / doc).exists()]
    request_packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "artifact_kind": "product_boardroom_ai_agent_request",
        "status": "waiting_for_ai_agents",
        "topic": clean_topic,
        "goal": goal,
        "manual_context": str(context or "").strip(),
        "context_refs": context_refs,
        "missing_context_refs": missing_core_docs,
        "agents": list(PRODUCT_BOARDROOM_AGENT_IDS),
        "agent_prompt_refs": agents_payload.get("agent_prompt_refs") or [],
        "meeting_protocol_ref": agents_payload.get("meeting_protocol_ref"),
        "ai_agent_required": True,
        "ai_agent_turns_required": True,
        "template_turn_allowed": False,
        "required_reply_shape": {
            "role_views": {
                agent_id: {
                    "ai_agent": True,
                    "turn_authorship": "ai_agent",
                    "required_fields": list(AI_BOARDROOM_TURN_REQUIRED_FIELDS),
                }
                for agent_id in PRODUCT_BOARDROOM_AGENT_IDS
            },
            "optional_fields": ["consensus", "open_questions"],
        },
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    request_path = default_company_product_boardroom_requests_dir(root) / f"{_slug(clean_topic, 'product-boardroom-ai-request')}-{_stamp()}.yaml"
    saved_request = _save_yaml(request_path, request_packet)
    latest_request = default_company_product_boardroom_latest_request_path(root)
    _save_yaml(latest_request, {**request_packet, "request_ref": _relative(saved_request, root)})
    agenda_path = _save_product_boardroom_agenda(
        root,
        goal=goal,
        topic="collect CEO/CTO/COO AI agent replies for the latest request",
        input_refs=[_relative(saved_request, root), *context_refs],
        open_questions=[],
    )
    return {
        "ok": True,
        "status": "waiting_for_ai_agents",
        "boardroom_status": status.get("status"),
        "topic": clean_topic,
        "agent_ids": list(PRODUCT_BOARDROOM_AGENT_IDS),
        "ai_agent_required": True,
        "ai_agent_turns_required": True,
        "template_turn_allowed": False,
        "ai_request_ref": _relative(saved_request, root),
        "latest_ai_request_ref": _relative(latest_request, root),
        "agent_prompt_refs": agents_payload.get("agent_prompt_refs") or [],
        "meeting_protocol_ref": agents_payload.get("meeting_protocol_ref"),
        "agenda_ref": _relative(agenda_path, root),
        "decision_history_ref": status.get("decision_history_ref"),
        "next_command": "cambrian company boardroom ingest ai_boardroom_reply.yaml --json",
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }


def ingest_product_boardroom_reply(project_root: Path, reply_path: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    source = Path(reply_path)
    if not source.is_absolute():
        source = root / source
    if not source.is_file():
        raise CompanyLayerError(f"AI boardroom reply file not found: {reply_path}")

    status = product_boardroom_status(root)
    if not status.get("installed"):
        raise CompanyLayerError("CEO/CTO/COO product boardroom is not installed")
    if not status.get("ai_agent_contract_ready"):
        raise CompanyLayerError("CEO/CTO/COO boardroom must be reinstalled with ai_agent contracts before ingest")

    reply = _load_yaml(source)
    if not reply:
        raise CompanyLayerError(f"AI boardroom reply is empty or invalid YAML: {reply_path}")
    context_refs = _product_boardroom_context_refs(root)
    goal = _mission_goal_from_state(root) or str(reply.get("goal") or "").strip() or "Keep product direction aligned before each 24h company tick."
    clean_topic = str(reply.get("topic") or status.get("latest_ai_request_status") or "AI boardroom decision").strip()
    latest_request_ref = str(status.get("latest_ai_request_ref") or "").strip()
    latest_request = _load_yaml(root / latest_request_ref) if latest_request_ref and (root / latest_request_ref).exists() else {}
    if latest_request.get("topic"):
        clean_topic = str(latest_request.get("topic") or clean_topic).strip()
    agents_payload = _load_yaml(default_company_product_boardroom_agents_path(root))
    agent_contracts = agents_payload.get("agents") if isinstance(agents_payload.get("agents"), list) else []
    agents_by_id = {
        str(agent.get("agent_id") or agent.get("role_id") or "").strip(): agent
        for agent in agent_contracts
        if isinstance(agent, dict) and str(agent.get("agent_id") or agent.get("role_id") or "").strip()
    }
    turns = _extract_ai_boardroom_turns(reply, agents_by_id)
    consensus = reply.get("consensus") if isinstance(reply.get("consensus"), dict) else {}
    if not consensus:
        consensus = {
            "decision": " / ".join(str(turn.get("decision") or "").strip() for turn in turns if turn.get("decision")),
            "scope": "AI agent boardroom decision; no source mutation, deploy, publish, spend, secrets, or migration.",
            "recommended_next_mission": str(turns[-1].get("next_constraint") or "Open exactly one bounded mission job and validate before sync."),
        }
    questions = _ai_boardroom_open_questions(reply, turns)
    missing_core_docs = [doc for doc in PRODUCT_BOARDROOM_CONTEXT_DOCS if not (root / doc).exists()]
    conversation = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "artifact_kind": "product_boardroom_conversation",
        "status": "convened",
        "topic": clean_topic,
        "goal": goal,
        "ai_agent_required": True,
        "ai_agent_turns_verified": True,
        "turn_source": "ai_agent_reply",
        "ai_reply_ref": _relative(source, root),
        "latest_ai_request_ref": latest_request_ref or None,
        "context_refs": context_refs,
        "agents": list(PRODUCT_BOARDROOM_AGENT_IDS),
        "agent_prompt_refs": agents_payload.get("agent_prompt_refs") or [],
        "meeting_protocol_ref": agents_payload.get("meeting_protocol_ref"),
        "turns": turns,
        "consensus": consensus,
        "assumptions": _as_text_list(reply.get("assumptions")),
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    conversations_dir = default_company_product_boardroom_conversations_dir(root)
    conversation_path = conversations_dir / f"{_slug(clean_topic, 'product-boardroom-ai')}-{_stamp()}.yaml"
    saved_conversation = _save_yaml(conversation_path, conversation)
    decision_ready = bool(context_refs) and all(bool(turn.get("ai_agent_verified")) for turn in turns)
    decision_packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "artifact_kind": "product_boardroom_decision_packet",
        "status": "ready_for_mission" if decision_ready else "needs_context",
        "topic": clean_topic,
        "goal": goal,
        "conversation_ref": _relative(saved_conversation, root),
        "context_refs": context_refs,
        "agent_prompt_refs": agents_payload.get("agent_prompt_refs") or [],
        "meeting_protocol_ref": agents_payload.get("meeting_protocol_ref"),
        "decision_history_ref": _relative(default_company_product_boardroom_decision_history_path(root), root),
        "next_agenda_ref": _relative(default_company_product_boardroom_agenda_path(root), root),
        "missing_context_refs": missing_core_docs,
        "ai_agent_required": True,
        "ai_agent_turns_verified": True,
        "turn_source": "ai_agent_reply",
        "ai_reply_ref": _relative(source, root),
        "latest_ai_request_ref": latest_request_ref or None,
        "role_views": {
            "ceo-agent": turns[0],
            "cto-agent": turns[1],
            "coo-agent": turns[2],
        },
        "consensus": consensus,
        "mission_gate": {
            "ready_for_mission": decision_ready,
            "requires_ai_agent_turns": True,
            "ai_agent_turns_verified": True,
            "requires_human_approval_for_direction_change": True,
            "max_mission_jobs_per_tick": 1,
            "must_stop_after_job_packet": True,
            "must_validate_before_sync": True,
            "auto_apply": False,
        },
        "open_questions": questions,
        "forbidden_actions": [
            "source_patch_apply",
            "git_push",
            "deploy",
            "publish",
            "external_spend",
            "secret_read_or_write",
            "database_migration",
        ],
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    saved_decision = _save_yaml(default_company_product_boardroom_decision_path(root), decision_packet)
    if latest_request_ref:
        latest_request_path = root / latest_request_ref
        if latest_request_path.exists():
            request_payload = _load_yaml(latest_request_path)
            request_payload.update(
                {
                    "status": "ingested",
                    "ingested_at": _now(),
                    "ai_reply_ref": _relative(source, root),
                    "decision_packet_ref": _relative(saved_decision, root),
                }
            )
            _save_yaml(latest_request_path, request_payload)
    history_path = _append_product_boardroom_decision_history(root, decision_packet)
    agenda_path = _save_product_boardroom_agenda(
        root,
        goal=goal,
        topic="review open questions and select the next bounded product proof",
        input_refs=[_relative(saved_decision, root), _relative(saved_conversation, root), *context_refs],
        open_questions=questions,
    )
    saved_questions = _save_yaml(
        default_company_product_boardroom_questions_path(root),
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now(),
            "artifact_kind": "product_boardroom_open_questions",
            "topic": clean_topic,
            "conversation_ref": _relative(saved_conversation, root),
            "questions": questions,
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        },
    )
    return {
        "ok": True,
        "status": "product_boardroom_ai_decision_ingested",
        "boardroom_status": status.get("status"),
        "topic": clean_topic,
        "agent_ids": list(PRODUCT_BOARDROOM_AGENT_IDS),
        "ai_agent_turns_verified": True,
        "ai_reply_ref": _relative(source, root),
        "conversation_ref": _relative(saved_conversation, root),
        "decision_packet_ref": _relative(saved_decision, root),
        "open_questions_ref": _relative(saved_questions, root),
        "agent_prompt_refs": agents_payload.get("agent_prompt_refs") or [],
        "meeting_protocol_ref": agents_payload.get("meeting_protocol_ref"),
        "agenda_ref": _relative(agenda_path, root),
        "decision_history_ref": _relative(history_path, root),
        "mission_gate": decision_packet["mission_gate"],
        "consensus": consensus,
        "next_command": "cambrian mission tick --json",
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }


def _office_status(found_refs: list[str], required_count: int) -> str:
    """발견된 증거 수로 office 상태를 계산한다."""
    if not found_refs:
        return "planned"
    if len(found_refs) >= required_count:
        return "active"
    return "partial"


def _company_base_initialized(root: Path) -> bool:
    """회사 베이스 운영 파일들이 모두 있는지 확인한다."""
    required_paths = [
        default_company_charter_path(root),
        default_company_task_schedule_path(root),
        *(default_company_office_path(root, office_id) for office_id in OFFICE_ORDER),
    ]
    return all(path.exists() for path in required_paths)


def _context_promotion_exists(root: Path) -> bool:
    """Context 후보가 장기 ledger로 승격된 기록이 있는지 확인한다."""
    promotion_paths = [
        default_company_context_decision_history_path(root),
        default_company_context_lessons_path(root),
        default_company_context_mistakes_path(root),
    ]
    return any(path.exists() for path in promotion_paths)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ledger_unchecked_count(entry: dict[str, Any]) -> int:
    if "unchecked_risk_count" in entry:
        return max(0, _safe_int(entry.get("unchecked_risk_count"), default=0))
    unchecked_items = entry.get("unchecked_items", [])
    if isinstance(unchecked_items, list):
        return len([item for item in unchecked_items if str(item or "").strip()])
    return 0


def _entry_has_validation_evidence(entry: dict[str, Any]) -> bool:
    validation_ref = str(entry.get("validation_evidence_ref") or "").strip()
    verdict_ref = str(entry.get("verdict_ref") or "").strip()
    validation_commands = entry.get("validation_commands", [])
    checked_artifacts = entry.get("checked_artifacts", [])
    return bool(
        validation_ref
        or verdict_ref
        or (isinstance(validation_commands, list) and any(str(item or "").strip() for item in validation_commands))
        or (isinstance(checked_artifacts, list) and any(str(item or "").strip() for item in checked_artifacts))
    )


def _is_verified_ledger_entry(entry: dict[str, Any]) -> bool:
    return (
        str(entry.get("verdict") or "").strip() == "pass"
        and str(entry.get("trust_gate_status") or "").strip() == "verified"
        and _ledger_unchecked_count(entry) == 0
        and _entry_has_validation_evidence(entry)
    )


def _compact_verified_ledger_entry(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    return {
        "id": entry.get("id"),
        "created_at": entry.get("created_at"),
        "job_id": entry.get("job_id"),
        "stage": entry.get("stage"),
        "verdict": entry.get("verdict"),
        "trust_gate_status": entry.get("trust_gate_status"),
        "unchecked_risk_count": _ledger_unchecked_count(entry),
        "validation_evidence_ref": entry.get("validation_evidence_ref"),
        "verdict_ref": entry.get("verdict_ref"),
    }


def _verification_ledger_proof(root: Path, *, job_id: str | None = None) -> dict[str, Any]:
    ledger_path = default_company_verification_ledger_path(root)
    payload = _load_yaml(ledger_path)
    raw_entries = payload.get("entries", [])
    entries = [entry for entry in raw_entries if isinstance(entry, dict)] if isinstance(raw_entries, list) else []
    verified_entries = [entry for entry in entries if _is_verified_ledger_entry(entry)]
    target_job_id = str(job_id or "").strip()
    matching_entries = [
        entry for entry in verified_entries if not target_job_id or str(entry.get("job_id") or "").strip() == target_job_id
    ]
    latest_entry = matching_entries[-1] if matching_entries else None
    return {
        "exists": latest_entry is not None,
        "ledger_ref": _relative(ledger_path, root) if ledger_path.exists() else None,
        "entry_count": len(entries),
        "verified_entry_count": len(verified_entries),
        "matching_verified_entry_count": len(matching_entries),
        "required_job_id": target_job_id or None,
        "latest_verified_entry": _compact_verified_ledger_entry(latest_entry),
    }


def _mission_last_outcome_verified(root: Path) -> dict[str, Any]:
    mission_path = root / ".cambrian" / "mission.yaml"
    mission = _load_yaml(mission_path)
    last_outcome = mission.get("last_outcome") if isinstance(mission.get("last_outcome"), dict) else {}
    unchecked_count = max(0, _safe_int(last_outcome.get("unchecked_count"), default=0))
    verified = (
        bool(last_outcome)
        and str(last_outcome.get("outcome") or "").strip() == "success"
        and str(last_outcome.get("verdict") or "").strip() == "pass"
        and str(last_outcome.get("trust_gate_status") or "").strip() == "verified"
        and unchecked_count == 0
    )
    return {
        "exists": verified,
        "mission_ref": ".cambrian/mission.yaml#last_outcome" if mission_path.exists() else None,
        "job_id": str(last_outcome.get("job_id") or "").strip() or None,
        "outcome": last_outcome.get("outcome"),
        "verdict": last_outcome.get("verdict"),
        "trust_gate_status": last_outcome.get("trust_gate_status"),
        "unchecked_count": unchecked_count,
        "latest_verdict_ref": last_outcome.get("latest_verdict_ref"),
    }


def _company_loop_proof(root: Path) -> dict[str, Any]:
    mission_proof = _mission_last_outcome_verified(root)
    job_id = mission_proof.get("job_id") if mission_proof.get("exists") else None
    matching_ledger_proof = (
        _verification_ledger_proof(root, job_id=str(job_id))
        if job_id
        else {
            "exists": False,
            "ledger_ref": _relative(default_company_verification_ledger_path(root), root)
            if default_company_verification_ledger_path(root).exists()
            else None,
            "latest_verified_entry": None,
        }
    )
    exists = bool(mission_proof.get("exists") and job_id and matching_ledger_proof.get("exists"))
    return {
        "exists": exists,
        "mission_last_outcome": mission_proof,
        "verification_entry_matches_last_outcome": bool(matching_ledger_proof.get("exists")),
        "matching_verification_entry": matching_ledger_proof.get("latest_verified_entry"),
        "proof_refs": [
            ref
            for ref in [
                mission_proof.get("mission_ref"),
                matching_ledger_proof.get("ledger_ref") if matching_ledger_proof.get("exists") else None,
            ]
            if ref
        ],
    }


def _company_next_allowed_work(
    root: Path,
    context_promotion_exists: bool,
    company_loop_proof_exists: bool = False,
) -> dict[str, str]:
    """현재 증거 기준으로 회사가 다음에 처리해도 되는 최소 작업을 고른다."""
    if not _company_base_initialized(root):
        return {
            "task_id": "company-base-000",
            "office": "all",
            "reason": "회사 베이스 운영 파일이 아직 고정되지 않았다.",
        }
    if not default_company_context_records_path(root).exists():
        return {
            "task_id": "company-base-001",
            "office": "context",
            "reason": "프로젝트 기억 후보가 아직 기록되지 않았다.",
        }
    if not context_promotion_exists:
        return {
            "task_id": "company-base-001",
            "office": "context",
            "reason": "기록된 context 후보가 장기 기억으로 승격되지 않았다.",
        }
    if not default_company_office_path(root, "verification").exists():
        return {
            "task_id": "company-base-004",
            "office": "verification",
            "reason": "검증 사무실 베이스가 없다.",
        }
    return {
        "task_id": "company-loop-ready" if company_loop_proof_exists else "company-loop-proof",
        "office": "verification",
        "reason": (
            "verified company loop proof exists; select the next bounded mission step from the operator state."
            if company_loop_proof_exists
            else "회사 루프가 실제 작업을 통과했다는 proof가 아직 없다."
        ),
    }


def _company_necessity_gate(
    root: Path,
    context_promotion_exists: bool,
    company_loop_proof_exists: bool = False,
) -> dict[str, Any]:
    """프로젝트에 필요한 최소 회사만 허용하는 확장 게이트를 만든다."""
    return {
        "mode": LEAN_COMPANY_MODE,
        "principle": "프로젝트 증거 없이 사무실, 역할, 업무를 늘리지 않는다.",
        "allowed_offices": list(OFFICE_ORDER),
        "office_count": len(OFFICE_ORDER),
        "expansion_allowed": False,
        "requires_evidence_for_new_office": True,
        "requires_user_approval": True,
        "blocked_expansion_types": list(COMPANY_EXPANSION_BLOCKED_TYPES),
        "next_allowed_work": _company_next_allowed_work(root, context_promotion_exists, company_loop_proof_exists),
    }


def _context_office(root: Path) -> dict[str, Any]:
    """Context Office 상태를 만든다."""
    refs = _existing_refs(
        root,
        [
            ".cambrian/profile.yaml",
            ".cambrian/project/profile.yaml",
            ".cambrian/memory/lessons.json",
            ".cambrian/notes/notes.yaml",
            ".cambrian/bridge/packets",
            ".cambrian/bridge/replies",
            ".cambrian/company/context/records.yaml",
            ".cambrian/company/context/decision_history.yaml",
            ".cambrian/company/context/lessons.yaml",
            ".cambrian/company/context/mistakes.yaml",
            ".cambrian/company/context/promotion_review.yaml",
            ".cambrian/company/offices/context.yaml",
        ],
    )
    if ".cambrian/company/context/decision_history.yaml" in refs or ".cambrian/company/context/lessons.yaml" in refs:
        next_gap = "context 승격 ledger는 생겼고, 다음은 승격 기록을 direction/execution 루프에서 참조하는 단계가 필요하다."
    elif ".cambrian/company/context/records.yaml" in refs:
        next_gap = "context 후보 기록은 생겼고, 다음은 후보를 장기 memory/decision history로 승격하는 정책이 필요하다."
    else:
        next_gap = "job 결과를 장기 memory와 decision history로 승격하는 context manager가 필요하다."
    office = dict(OFFICE_DEFINITIONS["context"])
    office.update(
        {
            "status": _office_status(refs, 3),
            "evidence_refs": refs,
            "next_gap": next_gap,
        }
    )
    return office


def _direction_office(root: Path) -> dict[str, Any]:
    """Direction Office 상태를 만든다."""
    refs = _existing_refs(
        root,
        [
            ".cambrian/plan.yaml",
            ".cambrian/harness.yaml",
            ".cambrian/auto/state.yaml",
            ".cambrian/auto/organization.yaml",
            ".cambrian/auto/boardroom",
            ".cambrian/auto/plan.yaml",
            ".cambrian/company/charter.yaml",
            ".cambrian/company/task_schedule.yaml",
            ".cambrian/company/offices/direction.yaml",
            ".cambrian/company/product_boardroom/agents.yaml",
            ".cambrian/company/product_boardroom/decision_packet.yaml",
        ],
    )
    office = dict(OFFICE_DEFINITIONS["direction"])
    office.update(
        {
            "status": _office_status(refs, 4),
            "evidence_refs": refs,
            "next_gap": "roadmap/backlog/priority policy가 분리된 운영 기록으로 필요하다.",
        }
    )
    return office


def _execution_office(root: Path) -> dict[str, Any]:
    """Execution Office 상태를 만든다."""
    refs = _existing_refs(
        root,
        [
            ".cambrian/workforce.yaml",
            ".cambrian/agents.yaml",
            ".cambrian/agents",
            ".cambrian/skills",
            ".cambrian/jobs",
            ".cambrian/packs/jobs",
            ".cambrian/auto/tasks",
            ".cambrian/company/offices/execution.yaml",
        ],
    )
    office = dict(OFFICE_DEFINITIONS["execution"])
    office.update(
        {
            "status": _office_status(refs, 4),
            "evidence_refs": refs,
            "next_gap": "작업 요청을 역할별 팀으로 안정적으로 라우팅하는 job router가 필요하다.",
        }
    )
    return office


def _verification_office(root: Path) -> dict[str, Any]:
    """Verification Office 상태를 만든다."""
    refs = _existing_refs(
        root,
        [
            ".cambrian/validation.yaml",
            ".cambrian/evidence",
            ".cambrian/evidence/validation",
            ".cambrian/reports/latest_verdict.json",
            ".cambrian/company/verification/ledger.yaml",
            ".cambrian/auto/results",
            ".cambrian/auto/release_gate",
            ".cambrian/company/offices/verification.yaml",
        ],
    )
    office = dict(OFFICE_DEFINITIONS["verification"])
    office.update(
        {
            "status": _office_status(refs, 4),
            "evidence_refs": refs,
            "next_gap": "pass/hold/rollback 결과를 proof ledger로 누적하는 감사 체계가 필요하다.",
        }
    )
    return office


def build_company_layer_status(project_root: Path) -> dict[str, Any]:
    """프로젝트의 Company Layer 상태판을 만든다.

    Args:
        project_root: Cambrian이 설치된 프로젝트 루트.

    Returns:
        Context/Direction/Execution/Verification 상태를 담은 dict.
    """
    root = Path(project_root).resolve()
    offices = {
        "context": _context_office(root),
        "direction": _direction_office(root),
        "execution": _execution_office(root),
        "verification": _verification_office(root),
    }
    office_statuses = [str(offices[name]["status"]) for name in OFFICE_ORDER]
    active_count = sum(1 for status in office_statuses if status == "active")
    partial_count = sum(1 for status in office_statuses if status == "partial")
    base_initialized = _company_base_initialized(root)
    context_promotion_exists = _context_promotion_exists(root)
    verification_ledger_proof = _verification_ledger_proof(root)
    company_loop_proof = _company_loop_proof(root)
    project_company_ready = bool(
        base_initialized
        and context_promotion_exists
        and verification_ledger_proof.get("exists")
        and company_loop_proof.get("exists")
    )
    if project_company_ready:
        status = "company_ready"
    elif base_initialized:
        status = "base_initialized"
    else:
        status = "partial" if active_count or partial_count else "planned"
    missing_offices = [name for name in OFFICE_ORDER if offices[name]["status"] != "active"]
    if project_company_ready:
        current_capability = "verified_company_loop"
    elif base_initialized:
        current_capability = "company_base_initialized"
    elif active_count or partial_count:
        current_capability = "specialist_workforce_or_partial_company"
    else:
        current_capability = "planned_company_layer"
    readiness_blockers = []
    if not context_promotion_exists:
        readiness_blockers.append("context promotion proof is missing")
    if not company_loop_proof.get("exists"):
        readiness_blockers.append("company loop proof is missing")
    if not verification_ledger_proof.get("exists"):
        readiness_blockers.append("verification ledger proof is missing")
    necessity_gate = _company_necessity_gate(root, context_promotion_exists, bool(company_loop_proof.get("exists")))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "status": status,
        "base_initialized": base_initialized,
        "context_promotion_exists": context_promotion_exists,
        "company_loop_proof_exists": bool(company_loop_proof.get("exists")),
        "verification_ledger_proof_exists": bool(verification_ledger_proof.get("exists")),
        "company_loop_proof": company_loop_proof,
        "verification_ledger_proof": verification_ledger_proof,
        "project_company_ready": project_company_ready,
        "auto_leadership_enabled": False,
        "approval_required_for_plan_changes": True,
        "project_root": str(root),
        "offices": offices,
        "necessity_gate": necessity_gate,
        "summary": {
            "active_offices": active_count,
            "partial_offices": partial_count,
            "missing_offices": missing_offices,
            "current_capability": current_capability,
            "company_design_mode": LEAN_COMPANY_MODE,
            "expansion_allowed": necessity_gate["expansion_allowed"],
            "readiness_blockers": readiness_blockers,
            "readiness_note": (
                "verified company loop proof exists; auto leadership remains disabled without explicit operator scheduling"
                if project_company_ready
                else "베이스 운영 파일은 있어도 자동 리더십과 검증된 회사 루프는 아직 활성화하지 않는다."
            ),
        },
        "next_command": "cambrian company status --save --json",
    }
    return payload


def save_company_layer_status(project_root: Path) -> tuple[dict[str, Any], Path]:
    """Company Layer 상태판을 저장한다."""
    root = Path(project_root).resolve()
    payload = build_company_layer_status(root)
    saved = _save_yaml(default_company_status_path(root), payload)
    payload["saved_path"] = _relative(saved, root)
    return payload, saved


def _office_skeleton(office_id: str) -> dict[str, Any]:
    """개별 office의 기본 운영 skeleton을 만든다."""
    definition = OFFICE_DEFINITIONS[office_id]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "office_id": office_id,
        "label": definition["label"],
        "korean_label": definition["korean_label"],
        "role": definition["role"],
        "status": "base_planned",
        "required_components": list(definition["required_components"]),
        "operating_rules": [
            "사용자 승인 없는 중요 계획 변경 금지",
            "검증되지 않은 내용을 proof로 승격 금지",
            "시크릿과 .env 내용 저장 금지",
        ],
    }
    if office_id == "context":
        payload["storage"] = {
            "context_records": ".cambrian/company/context/records.yaml",
            "decision_history": ".cambrian/company/context/decision_history.yaml",
            "lessons": ".cambrian/company/context/lessons.yaml",
            "mistakes": ".cambrian/company/context/mistakes.yaml",
            "promotion_target": ".cambrian/memory/lessons.json 또는 decision history",
        }
        payload["promotion_policy"] = {
            "auto_promote": False,
            "requires_user_review": True,
            "secret_storage_forbidden": True,
        }
    return payload


def _base_task_schedule(goal: str) -> dict[str, Any]:
    """회사 베이스 완성용 task schedule을 만든다."""
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "goal": goal,
        "status": "base_planned",
        "principle": "베이스 회사 계층을 먼저 완성하고, Claude/Codex UX 최적화는 이후 업그레이드로 진행한다.",
        "necessity_policy": {
            "mode": LEAN_COMPANY_MODE,
            "allowed_offices": list(OFFICE_ORDER),
            "no_extra_offices_without_evidence": True,
            "no_decorative_roles": True,
            "next_work_rule": "한 번에 가장 큰 운영 공백 하나만 처리한다.",
        },
        "non_goals": [
            "프로젝트 증거 없는 사무실 추가",
            "장식용 임원 또는 역할 추가",
            "작업 흐름과 무관한 사내 프로세스 추가",
        ],
        "deferred_upgrades": [
            {
                "id": "company-upgrade-later-001",
                "title": "Claude/Codex UX 오버헤드 개선",
                "reason": "회사 베이스 완성 전에는 job/ingest/validate UX 최적화보다 4대 사무실 루프 고정이 우선이다.",
                "activation_condition": "Context/Direction/Execution/Verification 베이스 루프가 proof와 함께 1회 이상 통과한 뒤 검토한다.",
                "status": "deferred",
            }
        ],
        "tasks": [
            {
                "id": "company-base-001",
                "office": "context",
                "title": "Context Office 베이스",
                "objective": "프로젝트 기억, 결정, 반복 실수, job 결과 승격 경계를 만든다.",
                "status": "planned",
                "acceptance": [
                    "장기 memory 저장 위치가 있다.",
                    "job 결과를 context로 승격할 규칙이 있다.",
                    "시크릿 저장 금지 규칙이 있다.",
                ],
            },
            {
                "id": "company-base-002",
                "office": "direction",
                "title": "Direction Office 베이스",
                "objective": "로드맵, 우선순위, backlog, 다음 행동 결정을 분리한다.",
                "status": "planned",
                "acceptance": [
                    "roadmap과 backlog가 구분된다.",
                    "사용자 승인 없는 목표 변경이 금지된다.",
                    "다음 작업 후보가 기록된다.",
                ],
            },
            {
                "id": "company-base-003",
                "office": "execution",
                "title": "Execution Office 베이스",
                "objective": "작업 요청을 에이전트/팀/스킬로 라우팅하는 운영 경계를 만든다.",
                "status": "planned",
                "acceptance": [
                    "job router 입력과 출력 계약이 있다.",
                    "에이전트 역할과 권한이 기록된다.",
                    "자동 적용은 기본 금지다.",
                ],
            },
            {
                "id": "company-base-004",
                "office": "verification",
                "title": "Verification Office 베이스",
                "objective": "검증, proof, pass/hold/rollback 판정과 evidence ledger를 만든다.",
                "status": "planned",
                "acceptance": [
                    "검증 명령과 결과가 기록된다.",
                    "hold는 실패와 구분된다.",
                    "proof 없는 성능 주장이 금지된다.",
                ],
            },
        ],
    }


def init_company_layer_base(project_root: Path, goal: str | None = None) -> dict[str, Any]:
    """Company Layer 베이스 운영 파일을 생성한다.

    Args:
        project_root: Cambrian이 설치된 프로젝트 루트.
        goal: 회사 베이스 초기 목표.

    Returns:
        생성된 파일과 다음 명령을 포함한 payload.
    """
    root = Path(project_root).resolve()
    goal_text = str(goal or "프로젝트 안 AI 회사 베이스 완성").strip()
    charter = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "status": "base_planned",
        "goal": goal_text,
        "company_model": {
            "context": OFFICE_DEFINITIONS["context"]["label"],
            "direction": OFFICE_DEFINITIONS["direction"]["label"],
            "execution": OFFICE_DEFINITIONS["execution"]["label"],
            "verification": OFFICE_DEFINITIONS["verification"]["label"],
        },
        "necessity_gate": {
            "mode": LEAN_COMPANY_MODE,
            "allowed_offices": list(OFFICE_ORDER),
            "expansion_allowed": False,
            "requires_evidence_for_new_office": True,
            "requires_user_approval": True,
            "blocked_expansion_types": list(COMPANY_EXPANSION_BLOCKED_TYPES),
        },
        "policy": {
            "auto_leadership_enabled": False,
            "approval_required_for_plan_changes": True,
            "auto_apply": False,
            "provider_api_call_required": False,
        },
    }
    schedule = _base_task_schedule(goal_text)
    saved_paths = [
        _save_yaml(default_company_charter_path(root), charter),
        _save_yaml(default_company_task_schedule_path(root), schedule),
    ]
    for office_id in OFFICE_ORDER:
        saved_paths.append(_save_yaml(default_company_office_path(root, office_id), _office_skeleton(office_id)))
    status_payload, status_path = save_company_layer_status(root)
    saved_paths.append(status_path)
    return {
        "ok": True,
        "status": "base_planned",
        "goal": goal_text,
        "base_initialized": status_payload["base_initialized"],
        "project_company_ready": status_payload["project_company_ready"],
        "auto_leadership_enabled": False,
        "saved_paths": [_relative(path, root) for path in saved_paths],
        "task_count": len(schedule["tasks"]),
        "next_command": "cambrian company status --save --json",
    }


def _required_text(value: str | None, field_name: str) -> str:
    """필수 문자열 입력을 정리하고 비어 있으면 차단한다."""
    text = str(value or "").strip()
    if not text:
        raise CompanyLayerError(f"{field_name} 값이 필요합니다.")
    return text


def _optional_text(value: str | None) -> str | None:
    """선택 문자열 입력을 정리한다."""
    text = str(value or "").strip()
    return text or None


def record_context_candidate(
    project_root: Path,
    *,
    source: str,
    summary: str,
    kind: str = "job_result",
    decision: str | None = None,
    lesson: str | None = None,
    mistake: str | None = None,
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Context Office에 장기 context 후보 기록을 추가한다.

    Args:
        project_root: Cambrian이 설치된 프로젝트 루트.
        source: 기록 출처. 예: job id, handoff, manual review.
        summary: 장기 context 후보로 남길 요약.
        kind: 기록 종류.
        decision: 보존할 결정 사항.
        lesson: 보존할 교훈.
        mistake: 반복 실수 후보.
        evidence_ref: 근거 파일 경로.

    Returns:
        저장 결과와 record id를 담은 payload.
    """
    root = Path(project_root).resolve()
    source_text = _required_text(source, "source")
    summary_text = _required_text(summary, "summary")
    kind_text = _required_text(kind, "kind")
    records_path = default_company_context_records_path(root)
    existing_payload = _load_yaml(records_path)
    existing_records = existing_payload.get("records", [])
    if not isinstance(existing_records, list):
        logger.warning("context records가 list가 아니어서 새 기록 목록으로 초기화합니다: %s", records_path)
        existing_records = []

    record_id = f"context-record-{len(existing_records) + 1:04d}"
    record = {
        "id": record_id,
        "created_at": _now(),
        "kind": kind_text,
        "source": source_text,
        "summary": summary_text,
        "signals": {
            "decision": _optional_text(decision),
            "lesson": _optional_text(lesson),
            "mistake": _optional_text(mistake),
        },
        "evidence_ref": _optional_text(evidence_ref),
        "promotion_status": "candidate",
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
            "secret_storage_forbidden": True,
        },
    }
    store_payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "status": "candidate_records",
        "records": [*existing_records, record],
    }
    saved = _save_yaml(records_path, store_payload)
    review_packet = build_context_promotion_review_packet(root)
    return {
        "ok": True,
        "status": "context_recorded",
        "record_id": record_id,
        "record_count": len(store_payload["records"]),
        "promotion_status": "candidate",
        "saved_path": _relative(saved, root),
        "promotion_review_ref": review_packet.get("review_ref"),
        "next_command": "cambrian company status --save --json",
    }


def _load_context_records(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Context 후보 기록 저장소를 읽는다."""
    records_payload = _load_yaml(default_company_context_records_path(root))
    records = records_payload.get("records", [])
    if not isinstance(records, list):
        raise CompanyLayerError("context records 형식이 올바르지 않습니다.")
    typed_records = [record for record in records if isinstance(record, dict)]
    if len(typed_records) != len(records):
        raise CompanyLayerError("context records 안에 잘못된 record 항목이 있습니다.")
    return records_payload, typed_records


def _find_context_record(records: list[dict[str, Any]], record_id: str) -> dict[str, Any]:
    """record id로 context 후보를 찾는다."""
    target_id = _required_text(record_id, "record_id")
    for record in records:
        if str(record.get("id", "")) == target_id:
            return record
    raise CompanyLayerError(f"context record를 찾을 수 없습니다: {target_id}")


def _append_context_ledger(path: Path, ledger_key: str, entry: dict[str, Any]) -> Path:
    """Context Office ledger에 항목을 추가한다."""
    payload = _load_yaml(path)
    entries = payload.get(ledger_key, [])
    if not isinstance(entries, list):
        logger.warning("context ledger가 list가 아니어서 새 목록으로 초기화합니다: %s", path)
        entries = []
    updated_payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        ledger_key: [*entries, entry],
    }
    return _save_yaml(path, updated_payload)


def build_context_promotion_review_packet(project_root: Path) -> dict[str, Any]:
    """후보 context 기록을 사용자가 검토할 수 있는 승격 packet으로 저장한다."""
    root = Path(project_root).resolve()
    records_payload, records = _safe_context_records(root)
    verification_entries = _verification_entries_by_job(root)
    pending_records = [record for record in records if str(record.get("promotion_status") or "candidate") != "promoted"]
    review_items = [
        _promotion_review_item(record, verification_entries.get(str(record.get("source") or ""), []))
        for record in pending_records
    ]
    review_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "packet_kind": "context_promotion_review",
        "status": "pending_user_review" if review_items else "empty",
        "source_records_ref": _relative(default_company_context_records_path(root), root)
        if default_company_context_records_path(root).exists()
        else None,
        "verification_ledger_ref": _relative(default_company_verification_ledger_path(root), root)
        if default_company_verification_ledger_path(root).exists()
        else None,
        "review_items": review_items,
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
            "approval_command": "cambrian company context promote <record_id> --confirm --json",
        },
        "records_status": records_payload.get("status"),
    }
    saved = _save_yaml(default_company_context_promotion_review_path(root), review_payload)
    return {
        "ok": True,
        "status": review_payload["status"],
        "review_item_count": len(review_items),
        "review_ref": _relative(saved, root),
        "auto_promote": False,
        "requires_user_review": True,
    }


def _safe_context_records(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """context records를 검토 packet 생성용으로 안전하게 읽는다."""
    payload = _load_yaml(default_company_context_records_path(root))
    records = payload.get("records", [])
    if not isinstance(records, list):
        logger.warning("context records가 list가 아니어서 검토 대상 없음으로 처리합니다: %s", default_company_context_records_path(root))
        records = []
    return payload, [record for record in records if isinstance(record, dict)]


def _verification_entries_by_job(root: Path) -> dict[str, list[dict[str, Any]]]:
    """verification ledger entry를 job_id 기준으로 묶는다."""
    payload = _load_yaml(default_company_verification_ledger_path(root))
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        return {}
    by_job: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        job_id = str(entry.get("job_id") or "")
        if job_id:
            by_job.setdefault(job_id, []).append(entry)
    return by_job


def _promotion_review_item(record: dict[str, Any], verification_entries: list[dict[str, Any]]) -> dict[str, Any]:
    """context 후보 하나를 review packet 항목으로 변환한다."""
    signals = record.get("signals", {}) if isinstance(record.get("signals"), dict) else {}
    proposed_targets = [
        target
        for target, key in [("decision_history", "decision"), ("lessons", "lesson"), ("mistakes", "mistake")]
        if _optional_text(str(signals.get(key) or ""))
    ]
    unchecked_risk_count = sum(int(entry.get("unchecked_risk_count") or 0) for entry in verification_entries)
    return {
        "record_id": record.get("id"),
        "source": record.get("source"),
        "summary": record.get("summary"),
        "evidence_ref": record.get("evidence_ref"),
        "proposed_targets": proposed_targets,
        "verification_entry_ids": [entry.get("id") for entry in verification_entries if entry.get("id")],
        "unchecked_risk_count": unchecked_risk_count,
        "approval_state": "pending_user_review",
        "auto_promote": False,
        "requires_user_review": True,
    }


def record_verification_entry(
    project_root: Path,
    *,
    source: str,
    job_id: str,
    stage: str,
    validation_evidence_ref: str | None = None,
    verdict_ref: str | None = None,
    verdict: str | None = None,
    trust_gate_status: str | None = None,
    validation_commands: list[str] | None = None,
    checked_artifacts: list[str] | None = None,
    unchecked_items: list[str] | None = None,
    company_roles: dict[str, Any] | None = None,
    context_evidence_ref: str | None = None,
    context_intent_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verification Office ledger에 job 검증 기록을 추가한다."""
    root = Path(project_root).resolve()
    source_text = _required_text(source, "source")
    job_id_text = _required_text(job_id, "job_id")
    stage_text = _required_text(stage, "stage")
    ledger_path = default_company_verification_ledger_path(root)
    payload = _load_yaml(ledger_path)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        logger.warning("verification ledger가 list가 아니어서 새 목록으로 초기화합니다: %s", ledger_path)
        entries = []
    entry_id = f"verification-entry-{len(entries) + 1:04d}"
    clean_unchecked_items = _clean_text_list(unchecked_items)
    entry = {
        "id": entry_id,
        "created_at": _now(),
        "source": source_text,
        "job_id": job_id_text,
        "stage": stage_text,
        "validation_evidence_ref": _optional_text(validation_evidence_ref),
        "verdict_ref": _optional_text(verdict_ref),
        "verdict": _optional_text(verdict),
        "trust_gate_status": _optional_text(trust_gate_status),
        "validation_commands": _clean_text_list(validation_commands),
        "checked_artifacts": _clean_text_list(checked_artifacts),
        "unchecked_items": clean_unchecked_items,
        "unchecked_risk_count": len(clean_unchecked_items),
        "company_roles": company_roles if isinstance(company_roles, dict) else {},
        "context_evidence_ref": _optional_text(context_evidence_ref),
        "context_intent": _compact_context_intent_snapshot(context_intent_snapshot),
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
        },
    }
    updated_payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "status": "verification_records",
        "entries": [*entries, entry],
    }
    saved = _save_yaml(ledger_path, updated_payload)
    return {
        "ok": True,
        "status": "verification_recorded",
        "entry_id": entry_id,
        "entry_count": len(updated_payload["entries"]),
        "saved_path": _relative(saved, root),
        "auto_promote": False,
        "requires_user_review": True,
    }


def _compact_context_intent_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, dict) or not snapshot:
        return {}
    intent = snapshot.get("detected_intent", {}) if isinstance(snapshot.get("detected_intent"), dict) else {}
    quality = snapshot.get("quality_gate", {}) if isinstance(snapshot.get("quality_gate"), dict) else {}
    relevance = snapshot.get("relevance_filter", {}) if isinstance(snapshot.get("relevance_filter"), dict) else {}
    return {
        "primary_intent": intent.get("primary") or "unknown",
        "intent_confidence": intent.get("confidence") or "low",
        "target_product_level": quality.get("target_product_level") or "upper",
        "current_context_level": quality.get("current_context_level") or "unknown",
        "passes_upper_bar": bool(quality.get("passes_upper_bar")),
        "selected_context_count": int(relevance.get("selected_context_count") or 0),
        "candidate_context_is_unapproved_signal": True,
    }


def load_company_loop_context(project_root: Path, limit: int = 3) -> dict[str, Any]:
    """다음 job start가 참고할 최신 Company Layer ledger 요약을 읽는다."""
    root = Path(project_root).resolve()
    count = max(1, int(limit or 1))
    context_payload = _load_yaml(default_company_context_records_path(root))
    records = context_payload.get("records", [])
    if not isinstance(records, list):
        records = []
    verification_payload = _load_yaml(default_company_verification_ledger_path(root))
    entries = verification_payload.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    typed_records = [record for record in records if isinstance(record, dict)]
    candidate_records = [record for record in typed_records if str(record.get("promotion_status") or "candidate") != "promoted"]
    recent_context = typed_records[-count:]
    recent_verification = [entry for entry in entries if isinstance(entry, dict)][-count:]
    promoted_memory = _load_promoted_context_memory(root, count)
    return {
        "status": "available" if recent_context or recent_verification or promoted_memory["total_count"] else "empty",
        "context_records": recent_context,
        "candidate_context_records": candidate_records[-count:],
        "promoted_memory": promoted_memory,
        "verification_entries": recent_verification,
        "context_records_ref": _relative(default_company_context_records_path(root), root)
        if default_company_context_records_path(root).exists()
        else None,
        "promotion_review_ref": _relative(default_company_context_promotion_review_path(root), root)
        if default_company_context_promotion_review_path(root).exists()
        else None,
        "verification_ledger_ref": _relative(default_company_verification_ledger_path(root), root)
        if default_company_verification_ledger_path(root).exists()
        else None,
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
        },
    }


def build_context_intent_snapshot(
    project_root: Path,
    request: str,
    *,
    company_loop_context: dict[str, Any] | None = None,
    codebase_evidence: dict[str, Any] | None = None,
    domain_confidence: dict[str, Any] | None = None,
    risk_boundaries: dict[str, Any] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    request_text = _required_text(request, "request")
    loop = company_loop_context if isinstance(company_loop_context, dict) else load_company_loop_context(root, limit=limit)
    evidence = codebase_evidence if isinstance(codebase_evidence, dict) else {}
    domains = domain_confidence if isinstance(domain_confidence, dict) else {}
    risks = risk_boundaries if isinstance(risk_boundaries, dict) else {}
    tokens = _context_tokens(request_text)
    intent = _resolve_user_intent(request_text, tokens)
    selected_promoted, promoted_total = _select_promoted_memory(loop, tokens, limit)
    selected_candidates, candidate_total = _select_relevant_items(
        loop.get("candidate_context_records", []),
        tokens,
        limit=limit,
        approved=False,
    )
    selected_verification, verification_total = _select_relevant_items(
        loop.get("verification_entries", []),
        tokens,
        limit=limit,
        approved=False,
    )
    selected_count = (
        len(selected_promoted["decisions"])
        + len(selected_promoted["lessons"])
        + len(selected_promoted["mistakes"])
        + len(selected_candidates)
        + len(selected_verification)
    )
    total_count = promoted_total + candidate_total + verification_total
    confidence = str(intent.get("confidence") or "low")
    grounded = str(evidence.get("status") or "") == "grounded"
    has_domains = bool(domains.get("confirmed") or domains.get("suspected"))
    has_risk_boundary = bool(risks)
    quality_level = "upper" if confidence in {"high", "medium"} and grounded and has_domains and has_risk_boundary else "middle"
    if confidence == "low" and not selected_count:
        quality_level = "low"
    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot_kind": "context_intent_snapshot",
        "status": "available",
        "generated_at": _now(),
        "request": request_text,
        "request_tokens": tokens[:16],
        "detected_intent": intent,
        "quality_gate": {
            "target_product_level": "upper",
            "current_context_level": quality_level,
            "passes_upper_bar": quality_level == "upper",
            "reason": _context_quality_reason(confidence, grounded, has_domains, has_risk_boundary, selected_count),
        },
        "context_policy": {
            "memory_is_not_context": True,
            "use_relevance_filter": True,
            "promoted_memory_is_approved_context": True,
            "candidate_context_is_unapproved_signal": True,
            "discard_irrelevant_recent_memory": True,
            "manual_review_when_intent_is_low": True,
        },
        "relevance_filter": {
            "token_count": len(tokens),
            "selected_context_count": selected_count,
            "promoted_memory_matched_count": (
                len(selected_promoted["decisions"]) + len(selected_promoted["lessons"]) + len(selected_promoted["mistakes"])
            ),
            "candidate_context_matched_count": len(selected_candidates),
            "verification_matched_count": len(selected_verification),
            "discarded_as_irrelevant_count": max(0, total_count - selected_count),
        },
        "selected_context": {
            "promoted_memory": selected_promoted,
            "candidate_context_records": selected_candidates,
            "verification_entries": selected_verification,
        },
        "intent_boundary": {
            "do_not_use_memory_by_recency_only": True,
            "do_not_promote_candidate_memory_without_user_review": True,
            "do_not_treat_cambrian_process_noise_as_project_intent": True,
            "weak_domain_evidence_requires_manual_review": True,
        },
        "guidance": _context_intent_guidance(intent, selected_count),
    }


def _context_tokens(text: str) -> list[str]:
    raw_tokens = re.findall(r"[0-9A-Za-z가-힣_]+", str(text or "").lower())
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "into",
        "job",
        "start",
        "next",
        "task",
        "작업",
        "다음",
        "진행",
        "시작",
        "프로젝트",
        "캄브리안",
    }
    result: list[str] = []
    for token in raw_tokens:
        if len(token) < 2 or token in stopwords:
            continue
        if token not in result:
            result.append(token)
    return result


def _resolve_user_intent(request: str, tokens: list[str]) -> dict[str, Any]:
    lowered = str(request or "").lower()
    intent_keywords = {
        "bug_fix": ["bug", "fix", "error", "fail", "broken", "버그", "오류", "에러", "실패", "고쳐"],
        "validation_followup": ["validate", "validation", "test", "proof", "risk", "검증", "테스트", "증거", "위험"],
        "implementation": ["implement", "build", "add", "create", "만들", "구현", "추가", "개발"],
        "architecture_direction": ["architecture", "design", "structure", "plan", "구조", "설계", "방향", "계획"],
        "context_intent_os": ["context", "intent", "memory", "맥락", "의도", "기억", "사용자"],
        "harness_company_design": ["harness", "company", "agent", "skill", "하네스", "회사", "에이전트", "스킬"],
        "marketplace_boundary": ["market", "marketplace", "export", "import", "마켓", "거래", "판매", "유통"],
        "new_project_bootstrap": ["new project", "bootstrap", "empty", "새프로젝트", "초기", "시작"],
    }
    scores: dict[str, int] = {}
    signals: list[str] = []
    token_set = set(tokens)
    for intent, keywords in intent_keywords.items():
        score = 0
        for keyword in keywords:
            keyword_text = str(keyword).lower()
            if " " in keyword_text:
                matched = keyword_text in lowered
            else:
                matched = keyword_text in lowered or keyword_text in token_set
            if matched:
                score += 1
                signals.append(f"{intent}:{keyword}")
        if score:
            scores[intent] = score
    if not scores:
        return {
            "primary": "unknown",
            "confidence": "low",
            "scores": {},
            "signals": [],
            "requires_user_clarification": True,
        }
    primary = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_score = scores[primary]
    confidence = "high" if top_score >= 2 else "medium"
    return {
        "primary": primary,
        "confidence": confidence,
        "scores": scores,
        "signals": signals[:8],
        "requires_user_clarification": confidence == "low",
    }


def _select_promoted_memory(loop: dict[str, Any], tokens: list[str], limit: int) -> tuple[dict[str, list[dict[str, Any]]], int]:
    promoted = loop.get("promoted_memory", {}) if isinstance(loop.get("promoted_memory"), dict) else {}
    selected: dict[str, list[dict[str, Any]]] = {"decisions": [], "lessons": [], "mistakes": []}
    total = 0
    for key in ["decisions", "lessons", "mistakes"]:
        items = promoted.get(key, [])
        typed = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        total += len(typed)
        selected[key] = _rank_relevant_items(typed, tokens, approved=True)[:limit]
    return selected, total


def _select_relevant_items(items: Any, tokens: list[str], *, limit: int, approved: bool) -> tuple[list[dict[str, Any]], int]:
    typed = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    return _rank_relevant_items(typed, tokens, approved=approved)[:limit], len(typed)


def _rank_relevant_items(items: list[dict[str, Any]], tokens: list[str], *, approved: bool) -> list[dict[str, Any]]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        score = _context_relevance_score(item, tokens)
        if score <= 0:
            continue
        ranked.append((score, {**item, "context_relevance_score": score, "approved_context": approved}))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in ranked]


def _context_relevance_score(item: dict[str, Any], tokens: list[str]) -> int:
    if not tokens:
        return 0
    text = _flatten_context_text(item).lower()
    if not text:
        return 0
    return sum(1 for token in tokens if token in text)


def _flatten_context_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_context_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_context_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _context_quality_reason(
    confidence: str,
    grounded: bool,
    has_domains: bool,
    has_risk_boundary: bool,
    selected_count: int,
) -> str:
    missing: list[str] = []
    if confidence == "low":
        missing.append("intent confidence is low")
    if not grounded:
        missing.append("codebase evidence is not grounded")
    if not has_domains:
        missing.append("domain evidence is missing")
    if not has_risk_boundary:
        missing.append("risk boundary is missing")
    relevance_note = ""
    if selected_count == 0:
        relevance_note = "no relevant company memory matched; current request and codebase evidence should dominate"
    if missing:
        return "; ".join([*missing, *([relevance_note] if relevance_note else [])])
    if relevance_note:
        return relevance_note
    return "intent, evidence, risk boundary, and relevant context are aligned"


def _context_intent_guidance(intent: dict[str, Any], selected_count: int) -> list[str]:
    guidance = [
        "Resolve current user intent before using stored memory.",
        "Use promoted_memory as approved context only when it is relevant to the request.",
        "Use candidate_context_records as unapproved signals, not as facts.",
        "Ignore recent records that do not match the request intent.",
    ]
    if str(intent.get("confidence") or "low") == "low":
        guidance.append("Ask for clarification or mark manual_review_required before making directional claims.")
    if selected_count == 0:
        guidance.append("Proceed from codebase evidence and current request because no relevant company memory matched.")
    return guidance


def _load_promoted_context_memory(root: Path, limit: int) -> dict[str, Any]:
    """장기 기억으로 승격된 context ledger를 구분해 읽는다."""
    decisions_payload = _load_yaml(default_company_context_decision_history_path(root))
    lessons_payload = _load_yaml(default_company_context_lessons_path(root))
    mistakes_payload = _load_yaml(default_company_context_mistakes_path(root))
    decisions = decisions_payload.get("decisions", [])
    lessons = lessons_payload.get("lessons", [])
    mistakes = mistakes_payload.get("mistakes", [])
    typed_decisions = [item for item in decisions if isinstance(item, dict)] if isinstance(decisions, list) else []
    typed_lessons = [item for item in lessons if isinstance(item, dict)] if isinstance(lessons, list) else []
    typed_mistakes = [item for item in mistakes if isinstance(item, dict)] if isinstance(mistakes, list) else []
    return {
        "decisions": typed_decisions[-limit:],
        "lessons": typed_lessons[-limit:],
        "mistakes": typed_mistakes[-limit:],
        "total_count": len(typed_decisions) + len(typed_lessons) + len(typed_mistakes),
    }


def _clean_text_list(values: list[str] | None) -> list[str]:
    """문자열 목록을 안전하게 정리한다."""
    cleaned: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            cleaned.append(text)
    return cleaned


def promote_context_candidate(project_root: Path, record_id: str, *, confirm: bool = False) -> dict[str, Any]:
    """Context 후보 기록을 장기 context ledger로 수동 승격한다.

    Args:
        project_root: Cambrian이 설치된 프로젝트 루트.
        record_id: 승격할 context 후보 id.
        confirm: 사용자 승인 여부. False면 승격하지 않는다.

    Returns:
        승격 결과와 저장 경로를 담은 payload.
    """
    if not confirm:
        raise CompanyLayerError("context 후보 승격은 --confirm 승인이 필요합니다.")

    root = Path(project_root).resolve()
    records_payload, records = _load_context_records(root)
    record = _find_context_record(records, record_id)
    if str(record.get("promotion_status", "")) == "promoted":
        raise CompanyLayerError(f"이미 승격된 context record입니다: {record_id}")

    signals = record.get("signals", {})
    if not isinstance(signals, dict):
        raise CompanyLayerError(f"context record signals 형식이 올바르지 않습니다: {record_id}")

    promoted_at = _now()
    base_entry = {
        "record_id": record.get("id"),
        "promoted_at": promoted_at,
        "source": record.get("source"),
        "summary": record.get("summary"),
        "evidence_ref": record.get("evidence_ref"),
        "approval_state": "approved_by_user",
    }
    saved_paths: list[Path] = []
    promoted_targets: list[str] = []

    decision = _optional_text(str(signals.get("decision") or ""))
    if decision:
        saved_paths.append(
            _append_context_ledger(
                default_company_context_decision_history_path(root),
                "decisions",
                {**base_entry, "decision": decision},
            )
        )
        promoted_targets.append("decision_history")

    lesson = _optional_text(str(signals.get("lesson") or ""))
    if lesson:
        saved_paths.append(
            _append_context_ledger(
                default_company_context_lessons_path(root),
                "lessons",
                {**base_entry, "lesson": lesson},
            )
        )
        promoted_targets.append("lessons")

    mistake = _optional_text(str(signals.get("mistake") or ""))
    if mistake:
        saved_paths.append(
            _append_context_ledger(
                default_company_context_mistakes_path(root),
                "mistakes",
                {**base_entry, "mistake": mistake},
            )
        )
        promoted_targets.append("mistakes")

    if not promoted_targets:
        raise CompanyLayerError(f"승격할 decision/lesson/mistake 신호가 없습니다: {record_id}")

    for candidate in records:
        if candidate is record:
            candidate["promotion_status"] = "promoted"
            candidate["promoted_at"] = promoted_at
            candidate["promoted_targets"] = promoted_targets
            break
    records_payload["updated_at"] = promoted_at
    records_payload["records"] = records
    saved_paths.append(_save_yaml(default_company_context_records_path(root), records_payload))
    review_packet = build_context_promotion_review_packet(root)

    return {
        "ok": True,
        "status": "context_promoted",
        "record_id": record.get("id"),
        "promoted_targets": promoted_targets,
        "saved_paths": [_relative(path, root) for path in saved_paths],
        "promotion_review_ref": review_packet.get("review_ref"),
        "auto_promote": False,
        "requires_user_review": True,
        "next_command": "cambrian company status --save --json",
    }


def render_company_layer_status(payload: dict[str, Any]) -> str:
    """Company Layer 상태를 사람이 읽기 좋은 텍스트로 만든다."""
    lines = [
        "Cambrian Company Layer",
        f"status: {payload.get('status')}",
        f"project_company_ready: {payload.get('project_company_ready')}",
        f"auto_leadership_enabled: {payload.get('auto_leadership_enabled')}",
        f"company_design_mode: {payload.get('summary', {}).get('company_design_mode') if isinstance(payload.get('summary'), dict) else None}",
        f"expansion_allowed: {payload.get('summary', {}).get('expansion_allowed') if isinstance(payload.get('summary'), dict) else None}",
        "",
        "Offices:",
    ]
    offices = payload.get("offices", {})
    if isinstance(offices, dict):
        for key in OFFICE_ORDER:
            office = offices.get(key, {})
            if not isinstance(office, dict):
                continue
            refs = office.get("evidence_refs", [])
            lines.append(f"- {office.get('label', key)}: {office.get('status')} ({len(refs) if isinstance(refs, list) else 0} evidence refs)")
            gap = office.get("next_gap")
            if gap:
                lines.append(f"  next_gap: {gap}")
    necessity_gate = payload.get("necessity_gate", {})
    if isinstance(necessity_gate, dict):
        next_allowed_work = necessity_gate.get("next_allowed_work", {})
        if isinstance(next_allowed_work, dict):
            lines.extend(
                [
                    "",
                    "Necessity gate:",
                    f"- mode: {necessity_gate.get('mode')}",
                    f"- next_allowed_work: {next_allowed_work.get('task_id')} ({next_allowed_work.get('office')})",
                ]
            )
    saved_path = payload.get("saved_path")
    if saved_path:
        lines.extend(["", f"saved: {saved_path}"])
    next_command = payload.get("next_command")
    if next_command:
        lines.extend(["", f"next: {next_command}"])
    return "\n".join(lines)
