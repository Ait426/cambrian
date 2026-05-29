from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_llm_assist import LLM_GENERATION_EVIDENCE_KEY, call_llm_for_generation, llm_assist_policy
from engine.project_pack_install import SCHEMA_VERSION, _relative, _slug


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    target = Path(path).resolve()
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def default_workforce_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "workforce.yaml"


def default_generated_agents_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "agents"


def default_operating_rules_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "operating_rules.yaml"


_AGENT_CONTRACTS: dict[str, dict[str, list[str]]] = {
    "ddmq-debugger": {
        "inputs": ["user request", "DDMQ queue files", "orchestrator stage flow", "archive/error routing evidence"],
        "outputs": ["DDMQ queue-flow findings", "dead-letter or duplicate-event risks", "handoff patch proposal"],
        "validation_required": ["DDMQ stage path cited", "archive/error routing impact explained"],
    },
    "anthropic-api-error-analyst": {
        "inputs": ["user request", "Anthropic API call sites", "provider error handling", "token/rate-limit boundaries"],
        "outputs": ["provider failure classification", "retry and fallback risk notes", "API boundary patch proposal"],
        "validation_required": ["provider call site cited", "API key and rate-limit risk checked"],
    },
    "stage-schema-validator": {
        "inputs": ["user request", "STAGE_SCHEMAS", "schema validator", "stage input/output samples"],
        "outputs": ["stage schema contract findings", "Null Mandate risks", "stage drift patch proposal"],
        "validation_required": ["schema path cited", "stage output compatibility checked"],
    },
    "web-experience-reviewer": {
        "inputs": ["user request", "product identity docs", "page structure evidence", "local run boundary"],
        "outputs": ["website golden path notes", "page structure risks", "local validation notes"],
        "validation_required": ["first viewport intent explained", "local run or build gap recorded"],
    },
    "hospitality-product-reviewer": {
        "inputs": ["user request", "hotel product goal", "guest journey assumptions", "booking/contact boundary"],
        "outputs": ["hotel site requirement notes", "guest conversion risks", "confirmation-required facts"],
        "validation_required": ["guest trust signals checked", "unknown hotel facts marked confirmation-required"],
    },
    "auth-flow-investigator": {
        "inputs": ["user request", "auth/session code evidence", "provider responsibility boundary", "related tests"],
        "outputs": ["auth boundary map", "failure reproduction notes", "patch proposal"],
        "validation_required": ["provider-managed token boundary explained", "auth regression test impact explained"],
    },
    "jest-regression-guardian": {
        "inputs": ["user request", "Jest config", "test commands", "changed file preview"],
        "outputs": ["Jest command plan", "regression risk notes", "missing test evidence"],
        "validation_required": ["Jest command selected", "test gap or pass evidence recorded"],
    },
    "pytest-regression-guardian": {
        "inputs": ["user request", "pytest config", "test commands", "changed file preview"],
        "outputs": ["pytest command plan", "regression risk notes", "missing test evidence"],
        "validation_required": ["pytest command selected", "test gap or pass evidence recorded"],
    },
    "test-regression-guardian": {
        "inputs": ["user request", "validation commands", "changed file preview"],
        "outputs": ["validation command plan", "regression risk notes", "manual verification gap"],
        "validation_required": ["validation command selected", "manual verification gap recorded"],
    },
    "api-contract-reviewer": {
        "inputs": ["user request", "API route evidence", "response contract", "client call sites"],
        "outputs": ["API contract risk notes", "response shape compatibility notes", "failure mode checklist"],
        "validation_required": ["API response shape impact explained", "client compatibility risk explained"],
    },
    "risk-reviewer": {
        "inputs": ["patch proposal", "forbidden paths", "approval policy", "operational constraints"],
        "outputs": ["operational risk register", "approval checklist", "rollback concern notes"],
        "validation_required": ["forbidden path check recorded", "human approval checklist recorded"],
    },
    "root-cause-investigator": {
        "inputs": ["user request", "important paths", "recent failures", "project profile"],
        "outputs": ["root cause hypothesis", "evidence map", "patch proposal"],
        "validation_required": ["root cause evidence cited", "patch scope explained"],
    },
    "agent-platform-contract-reviewer": {
        "inputs": ["user request", "agent pack contract", "Builder flow", "download/import evidence"],
        "outputs": ["agent pack contract notes", "builder flow risk notes", "runtime coupling notes"],
        "validation_required": ["agent pack schema impact explained", "download/import roundtrip risk explained"],
    },
    "typescript-code-reviewer": {
        "inputs": ["user request", "TypeScript files", "runtime boundary", "build command"],
        "outputs": ["type safety notes", "runtime side effect notes", "build risk notes"],
        "validation_required": ["TypeScript build impact explained", "runtime side effect checked"],
    },
    "webhook-signature-reviewer": {
        "inputs": ["user request", "webhook handler", "signature headers", "raw body path"],
        "outputs": ["webhook signature findings", "HMAC regression notes", "risk notes"],
        "validation_required": ["signature base string checked", "401/retry impact explained"],
    },
    "outbound-safety-reviewer": {
        "inputs": ["user request", "send pipeline", "suppression policy", "recipient state"],
        "outputs": ["suppression policy findings", "send pipeline notes", "blocked-send risk notes"],
        "validation_required": ["suppression bypass risk checked", "send retry impact explained"],
    },
    "supabase-schema-reviewer": {
        "inputs": ["user request", "Supabase migrations", "RLS policies", "schema call sites"],
        "outputs": ["migration consistency notes", "Supabase risk notes", "policy impact notes"],
        "validation_required": ["applied migration edit risk checked", "RLS/policy impact explained"],
    },
    "scorecard-logic-reviewer": {
        "inputs": ["user request", "score inputs", "weighting logic", "customer selection rules"],
        "outputs": ["scorecard logic notes", "customer selection risk notes", "validation criteria proposal"],
        "validation_required": ["score input impact explained", "selection criteria change risk checked"],
    },
}

AI_AGENT_RESPONSIBILITY_CLASSES = {
    "context_analysis",
    "contract_execution",
    "domain_execution",
    "risk_direction",
    "technical_review",
    "verification",
}

GENERAL_AGENT_RESPONSIBILITY_CLASSES = {
    "tool_execution",
    "file_operation",
    "command_runner",
}

LLM_INVOCATION_EVIDENCE_KEY = "llm_invocation_evidence"


@dataclass
class WorkforceGenerateResult:
    schema_version: str
    generated_at: str
    status: str
    workforce_id: str | None
    harness_id: str | None
    agents: list[dict[str, Any]]
    next_command: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    llm_assist_policy: dict[str, Any] = field(default_factory=dict)
    llm_generation_evidence: dict[str, Any] = field(default_factory=dict)
    generation_quality_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "draft"
        return payload


def build_workforce(project_root: Path, provider: Any | None = None) -> WorkforceGenerateResult:
    root = Path(project_root).resolve()
    from engine.project_custom_harness import build_custom_harness_plan

    plan = build_custom_harness_plan(root)
    if plan is None:
        return WorkforceGenerateResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            workforce_id=None,
            harness_id=None,
            agents=[],
            next_command="cambrian harness interview start --json",
            errors=["Custom harness plan is not ready. Complete the harness interview first."],
        )
    llm_assist = _workforce_generation_llm_assist(plan, provider)
    workforce = build_workforce_payload(plan, llm_assist=llm_assist)
    agents = build_agent_payloads(plan, workforce)
    return WorkforceGenerateResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="draft",
        workforce_id=str(workforce.get("id")),
        harness_id=str(plan.get("harness_id")),
        agents=agents,
        next_command="cambrian harness install --confirm --json",
        warnings=list(plan.get("warnings", [])),
        errors=[],
        llm_assist_policy=dict(llm_assist.get("policy", {})),
        llm_generation_evidence=dict(llm_assist.get(LLM_GENERATION_EVIDENCE_KEY, {})),
        generation_quality_status=str(llm_assist.get("policy", {}).get("quality_status") or ""),
    )


def build_workforce_payload(plan: dict[str, Any], llm_assist: dict[str, Any] | None = None) -> dict[str, Any]:
    harness_id = str(plan.get("harness_id") or "custom-harness")
    workforce_id = f"workforce-{_slug(harness_id.removeprefix('custom-'), 'project')}"
    llm_assist_payload = llm_assist or _workforce_generation_llm_assist(plan, None)
    agents = build_agent_payloads(plan, {"id": workforce_id, "harness_id": harness_id})
    company_structure = build_company_structure(plan, agents)
    agent_ids = [str(agent["id"]) for agent in agents]
    try:
        from engine.project_skill_builder import build_skill_payloads, skill_mapping

        skills = skill_mapping(build_skill_payloads(plan, {"id": workforce_id, "harness_id": harness_id, "agents": agent_ids}))
    except Exception:
        skills = {}
    default_team = _default_team(agent_ids)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "id": workforce_id,
        "type": "generated_workforce",
        "status": "draft",
        "generation_quality_status": str(llm_assist_payload.get("policy", {}).get("quality_status") or "bootstrap_draft"),
        "llm_assist_policy": dict(llm_assist_payload.get("policy", {})),
        LLM_GENERATION_EVIDENCE_KEY: dict(llm_assist_payload.get(LLM_GENERATION_EVIDENCE_KEY, {})),
        "llm_generation_notes": llm_assist_payload.get("llm_notes"),
        "harness_id": harness_id,
        "agents": agent_ids,
        "skills": skills,
        "default_team": default_team,
        "agent_kind_summary": _agent_kind_summary(agents),
        "agent_runtime_contracts": _agent_runtime_contracts(agents),
        "agent_runtime_policy": {
            "general_agent": "May run deterministic workflow, routing, file, or validation operations without LLM reasoning.",
            "ai_agent": "Must call an LLM or external AI worker for thinking, analysis, review, planning, or product discussion.",
            "thinking_requires_llm_call": True,
            "llm_invocation_evidence_key": LLM_INVOCATION_EVIDENCE_KEY,
        },
        "company_structure": company_structure,
        "responsibility_matrix": company_structure.get("responsibility_matrix", {}),
        "duplicate_guard": company_structure.get("duplicate_guard", {}),
        "dispatch_policy": {
            "mode": "on_demand",
            "auto_dispatch_on_install": False,
        },
    }


def _workforce_generation_llm_assist(plan: dict[str, Any], provider: Any | None) -> dict[str, Any]:
    project = plan.get("project", {}) if isinstance(plan.get("project"), dict) else {}
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    system = (
        "You are Cambrian's workforce generation intelligence layer. "
        "Review the project harness plan and advise which AI agents, deterministic agents, skills, "
        "risk gates, and validation evidence should shape the generated workforce. "
        "Return concise notes only; Cambrian will keep local safety gates."
    )
    user = yaml.safe_dump(
        {
            "harness_id": plan.get("harness_id"),
            "goal": plan.get("goal"),
            "project": project,
            "domains": project.get("domains") if isinstance(project, dict) else None,
            "validation": plan.get("validation"),
            "important_paths": plan.get("important_paths"),
            "codebase_evidence_status": evidence.get("status") if isinstance(evidence, dict) else None,
            "policy": plan.get("policy"),
        },
        allow_unicode=True,
        sort_keys=False,
    )
    return call_llm_for_generation(provider, stage="workforce_generation", system=system, user=user)


def build_agent_payloads(plan: dict[str, Any], workforce: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    project = plan.get("project", {}) if isinstance(plan.get("project"), dict) else {}
    validation = plan.get("validation", {}) if isinstance(plan.get("validation"), dict) else {}
    policy = plan.get("policy", {}) if isinstance(plan.get("policy"), dict) else {}
    domains = _active_domains(plan)
    language = str(project.get("language") or "custom").lower()
    test_framework = str(project.get("test_framework") or "").lower()
    important_paths = [str(item) for item in plan.get("important_paths", []) if item]
    forbidden = [str(item) for item in policy.get("forbidden", []) if item]
    test_commands = [str(item) for item in validation.get("test_commands", []) if item]
    harness_id = str(plan.get("harness_id") or "custom-harness")
    scale_plan = _company_scale_plan(plan, domains)
    agent_cap = int(scale_plan.get("agent_cap") or 5)
    base = {
        "type": "generated_agent",
        "status": "draft",
        "harness_id": harness_id,
        "scope": important_paths,
        "forbidden": forbidden,
        "inputs": ["사용자 작업 요청", "project profile", "harness rules", "important paths"],
        "outputs": ["root cause hypothesis", "patch proposal", "risk notes"],
        "validation": {
            "required": ["테스트 영향 설명", "회귀 위험 설명"],
        },
    }
    agents: list[dict[str, Any]] = []
    custom_agents = _custom_role_agents_from_plan(plan, base, test_commands)
    _use_custom_agents = bool(custom_agents)
    if custom_agents:
        agents.extend(custom_agents)
    if not _use_custom_agents:
        if "website" in domains and not _has_agent(agents, "web-experience-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "web-experience-reviewer",
                    "role": "Reviews the website structure, first screen, navigation, local execution path, and user-facing quality gates.",
                    "outputs": ["website golden path notes", "page structure risks", "local validation notes"],
                    "responsibilities": ["Confirm the website promise from identity docs.", "Map the visitor journey before implementation.", "Tie readiness claims to local validation evidence."],
                }
            )
        if "hotel_site" in domains and not _has_agent(agents, "hospitality-product-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "hospitality-product-reviewer",
                    "role": "Reviews hotel guest intent, room/booking content, trust signals, and stay-site conversion risks.",
                    "outputs": ["hotel site requirement notes", "guest conversion risks", "confirmation-required facts"],
                    "responsibilities": ["Identify the hotel guest segments and stay intent.", "Check room, location, contact, booking, and trust assumptions.", "Mark missing hotel facts as confirmation-required before implementation."],
                }
            )
        if "agent_marketplace_platform" in domains and not _has_agent(agents, "agent-platform-contract-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "agent-platform-contract-reviewer",
                    "role": "AI 에이전트 pack 생성/다운로드 계약과 Builder 흐름을 검토한다.",
                    "outputs": ["agent pack contract notes", "builder flow risk notes", "runtime coupling notes"],
                    "responsibilities": ["Builder 입력과 pack 출력 계약을 확인한다.", "다운로드/Import roundtrip을 검토한다.", "Cambrian 결합도가 선택형으로 남는지 확인한다."],
                }
            )
        if "webhook" in domains and not _has_agent(agents, "webhook-signature-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "webhook-signature-reviewer",
                    "role": "Webhook HMAC/Svix 서명 검증 경로를 분석한다.",
                    "outputs": ["webhook signature findings", "HMAC regression notes", "risk notes"],
                    "responsibilities": ["raw body와 서명 헤더 처리 경로를 확인한다.", "401/재시도 부작용을 정리한다.", "관련 검증 명령을 연결한다."],
                }
            )
        if any(domain in domains for domain in ["suppression", "send_pipeline", "outbound"]) and not _has_agent(agents, "outbound-safety-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "outbound-safety-reviewer",
                    "role": "suppression 정책과 발송 파이프라인 안전 조건을 검토한다.",
                    "outputs": ["suppression policy findings", "send pipeline notes", "blocked-send risk notes"],
                    "responsibilities": ["발송 전 차단 조건을 확인한다.", "unsubscribe/suppression 우회 가능성을 검토한다.", "재시도와 큐 처리 위험을 정리한다."],
                }
            )
        if "supabase" in domains and not _has_agent(agents, "supabase-schema-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "supabase-schema-reviewer",
                    "role": "Supabase migration, RLS, schema 변경 위험을 검토한다.",
                    "outputs": ["migration consistency notes", "Supabase risk notes"],
                    "responsibilities": ["적용된 migration 수정 여부를 확인한다.", "RLS/정책 변경 위험을 정리한다.", "DB 변경은 수동 승인 전 금지한다."],
                }
            )
        if any(domain in domains for domain in ["scoring", "customer"]) and not _has_agent(agents, "scorecard-logic-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "scorecard-logic-reviewer",
                    "role": "고객 선정과 scorecard 계산 흐름을 분석한다.",
                    "outputs": ["scorecard logic notes", "customer selection risk notes"],
                    "responsibilities": ["점수 입력과 가중치 경로를 확인한다.", "선정 기준 변경 영향을 정리한다.", "검증 기준을 제안한다."],
                }
            )
        if "auth" in domains and not _has_agent(agents, "auth-flow-investigator"):
            agents.append(
                {
                    **base,
                    "id": "auth-flow-investigator",
                    "role": "인증 흐름과 토큰 검증 경로를 분석한다.",
                    "responsibilities": ["인증 실패 재현 조건을 정리한다.", "수정 후보를 제안한다.", "관련 테스트 영향을 확인한다."],
                }
            )
        if not agents:
            agents.append(
                {
                    **base,
                    "id": "root-cause-investigator",
                    "role": "버그 원인 후보와 수정 방향을 분석한다.",
                    "responsibilities": ["문제 재현 조건을 정리한다.", "수정 후보를 제안한다.", "관련 파일 영향을 확인한다."],
                }
            )
        if "api" in domains and len(agents) < agent_cap and not _has_agent(agents, "api-contract-reviewer"):
            agents.append(
                {
                    **base,
                    "id": "api-contract-reviewer",
                    "role": "API 응답 형식과 실패 케이스를 검토한다.",
                    "responsibilities": ["API 계약 변경 위험을 검토한다.", "인증 실패 응답의 부작용을 확인한다."],
                }
            )
        if language in {"typescript", "javascript"} and "api" not in domains and len(agents) < agent_cap:
            agents.append(
                {
                    **base,
                    "id": "typescript-code-reviewer",
                    "role": "TypeScript 타입과 런타임 부작용을 검토한다.",
                    "responsibilities": ["타입 안정성 위험을 확인한다.", "런타임 부작용을 설명한다."],
                }
            )
    if not any(_agent_responsibility_class(str(agent.get("id") or "")) == "verification" for agent in agents) and (
        test_framework == "jest" or any("jest" in command for command in test_commands)
    ):
        agents.append(
            {
                **base,
                "id": "jest-regression-guardian",
                "role": "Jest 테스트와 회귀 가능성을 검토한다.",
                "responsibilities": ["관련 Jest 테스트를 식별한다.", "회귀 위험을 설명한다."],
                "test_commands": test_commands or ["npm test"],
            }
        )
    elif not any(_agent_responsibility_class(str(agent.get("id") or "")) == "verification" for agent in agents) and (
        test_framework == "pytest" or any("pytest" in command for command in test_commands)
    ):
        agents.append(
            {
                **base,
                "id": "pytest-regression-guardian",
                "role": "pytest 테스트와 회귀 가능성을 검토한다.",
                "responsibilities": ["관련 pytest 테스트를 식별한다.", "회귀 위험을 설명한다."],
                "test_commands": test_commands or ["python -m pytest"],
            }
        )
    elif not any(_agent_responsibility_class(str(agent.get("id") or "")) == "verification" for agent in agents):
        agents.append(
            {
                **base,
                "id": "test-regression-guardian",
                "role": "프로젝트 테스트 명령과 회귀 가능성을 검토한다.",
                "responsibilities": ["검증 명령을 확인한다.", "회귀 위험을 설명한다."],
                "test_commands": test_commands,
            }
        )
    if not any(_agent_responsibility_class(str(agent.get("id") or "")) == "risk_direction" for agent in agents):
        agents.append(
            {
                **base,
                "id": "risk-reviewer",
                "role": "수정 제안의 부작용과 운영 리스크를 검토한다.",
                "responsibilities": ["운영 리스크를 분류한다.", "사람이 적용 전 확인할 항목을 정리한다."],
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent in agents:
        agent_id = str(agent.get("id") or "")
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            deduped.append(agent)
        if len(deduped) >= agent_cap:
            break
    agents_with_evidence = [_attach_agent_evidence(_specialize_agent_contract(agent), plan) for agent in deduped]
    agents_with_runtime = [_attach_agent_runtime_contract(agent) for agent in agents_with_evidence]
    return _attach_company_roles(agents_with_runtime, plan)


def _custom_role_agents_from_plan(plan: dict[str, Any], base: dict[str, Any], test_commands: list[str]) -> list[dict[str, Any]]:
    """interview agent_roles를 실제 workforce agent로 승격한다."""
    specs = plan.get("agents", []) if isinstance(plan.get("agents"), list) else []
    agents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, spec in enumerate(specs, start=1):
        if not isinstance(spec, dict):
            continue
        source_id = str(spec.get("id") or "").strip()
        if source_id and not source_id.startswith("custom-agent-"):
            continue
        role = str(spec.get("role") or "").strip()
        if not role:
            continue
        agent_id = _role_agent_id(role, index)
        if agent_id in seen:
            continue
        seen.add(agent_id)
        agent = {
            **base,
            "id": agent_id,
            "role": role,
            "outputs": _custom_agent_outputs(agent_id),
            "responsibilities": _custom_agent_responsibilities(role),
        }
        if _agent_responsibility_class(agent_id) == "verification":
            agent["test_commands"] = test_commands
        agents.append(agent)
    domains = _active_domains(plan)
    cap = int(_company_scale_plan(plan, domains).get("agent_cap") or 5)
    return agents[:cap]


def _should_prefer_custom_role_agents(domains: list[str]) -> bool:
    """강한 제품 도메인이 없으면 인터뷰 역할을 우선한다."""
    strong_domains = [domain for domain in domains if domain not in {"tests", "api"}]
    return not strong_domains or set(strong_domains).issubset({"agent_marketplace_platform", "cambrian_local_bridge"})


def _role_agent_id(role: str, index: int) -> str:
    """역할 문자열의 접두어를 agent id로 정규화한다."""
    prefix = str(role or "").split(":", 1)[0].strip()
    if not prefix or len(prefix) > 64:
        prefix = f"custom-agent-{index}"
    return _slug(prefix, f"custom-agent-{index}")


def _custom_agent_outputs(agent_id: str) -> list[str]:
    """custom agent 책임군에 맞는 출력 계약을 만든다."""
    responsibility = _agent_responsibility_class(agent_id)
    if responsibility == "verification":
        return ["validation command plan", "regression risk notes", "manual verification gap"]
    if responsibility == "risk_direction":
        return ["operational risk register", "approval checklist", "rollback concern notes"]
    if responsibility == "technical_review":
        return ["contract notes", "compatibility risks", "side effect notes"]
    return ["domain findings", "evidence map", "patch proposal"]


def _custom_agent_responsibilities(role: str) -> list[str]:
    """역할 설명을 실행 가능한 책임 문장으로 바꾼다."""
    description = str(role or "").split(":", 1)[-1].strip()
    if not description:
        description = "요청 범위의 evidence를 확인하고 수정 후보를 정리한다."
    return [description, "관련 evidence path를 인용한다.", "검증 명령과 회귀 위험을 함께 정리한다."]


def _has_agent(agents: list[dict[str, Any]], agent_id: str) -> bool:
    """agent 목록에 특정 agent id가 있는지 확인한다."""
    return any(str(agent.get("id") or "") == agent_id for agent in agents if isinstance(agent, dict))


def _specialize_agent_contract(agent: dict[str, Any]) -> dict[str, Any]:
    agent_id = str(agent.get("id") or "")
    contract = _AGENT_CONTRACTS.get(agent_id)
    if not contract:
        return agent
    specialized = dict(agent)
    specialized["inputs"] = list(contract.get("inputs", specialized.get("inputs", [])))
    specialized["outputs"] = list(contract.get("outputs", specialized.get("outputs", [])))
    validation = specialized.get("validation", {})
    if not isinstance(validation, dict):
        validation = {}
    validation["required"] = list(contract.get("validation_required", validation.get("required", [])))
    specialized["validation"] = validation
    return specialized


def _agent_kind_for_responsibility(responsibility_class: str) -> str:
    if responsibility_class in GENERAL_AGENT_RESPONSIBILITY_CLASSES:
        return "general_agent"
    return "ai_agent" if responsibility_class in AI_AGENT_RESPONSIBILITY_CLASSES else "ai_agent"


def _attach_agent_runtime_contract(agent: dict[str, Any]) -> dict[str, Any]:
    attached = dict(agent)
    agent_id = str(attached.get("id") or "")
    responsibility_class = _agent_responsibility_class(agent_id)
    agent_kind = _agent_kind_for_responsibility(responsibility_class)
    requires_reasoning = agent_kind == "ai_agent"
    llm_contract = {
        "required": requires_reasoning,
        "reason": "agent performs thinking, analysis, review, planning, or judgment"
        if requires_reasoning
        else "agent is deterministic and does not own judgment",
        "allowed_modes": ["external_ai_worker", "provider_api", "local_model"],
        "must_record_evidence": requires_reasoning,
        "evidence_key": LLM_INVOCATION_EVIDENCE_KEY,
        "accepted_providers": ["codex", "claude", "gpt", "cursor", "anthropic", "openai", "google", "local_model"],
    }
    attached["agent_kind"] = agent_kind
    attached["responsibility_class"] = responsibility_class
    attached["requires_reasoning"] = requires_reasoning
    attached["requires_llm_call"] = requires_reasoning
    attached["runtime_contract"] = {
        "agent_kind": agent_kind,
        "thinking_requires_llm_call": True,
        "llm_invocation": llm_contract,
        "template_output_allowed": not requires_reasoning,
    }
    generation_policy = llm_assist_policy("agent_generation", provider_used=False)
    attached["generation_contract"] = {
        "requires_llm_for_intelligent_generation": True,
        "quality_status": generation_policy["quality_status"],
        "llm_enrichment_required": generation_policy["llm_enrichment_required"],
        "evidence_key": LLM_GENERATION_EVIDENCE_KEY,
    }
    validation = attached.get("validation", {})
    if not isinstance(validation, dict):
        validation = {}
    validation["required"] = _dedupe_texts(
        [
            *[str(item) for item in validation.get("required", []) if item],
            *([f"{LLM_INVOCATION_EVIDENCE_KEY} recorded"] if requires_reasoning else []),
        ]
    )
    attached["validation"] = validation
    return attached


def _agent_kind_summary(agents: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {"ai_agent": 0, "general_agent": 0}
    llm_required: list[str] = []
    for agent in agents:
        agent_kind = str(agent.get("agent_kind") or "ai_agent")
        counts[agent_kind] = counts.get(agent_kind, 0) + 1
        if agent.get("requires_llm_call"):
            llm_required.append(str(agent.get("id") or ""))
    return {
        "counts": counts,
        "llm_required_agents": _dedupe_texts([item for item in llm_required if item]),
        "thinking_requires_llm_call": True,
    }


def _agent_runtime_contracts(agents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        str(agent.get("id")): {
            "agent_kind": agent.get("agent_kind"),
            "responsibility_class": agent.get("responsibility_class"),
            "requires_reasoning": bool(agent.get("requires_reasoning")),
            "requires_llm_call": bool(agent.get("requires_llm_call")),
            "runtime_contract": dict(agent.get("runtime_contract", {}))
            if isinstance(agent.get("runtime_contract"), dict)
            else {},
        }
        for agent in agents
        if agent.get("id")
    }


def _attach_agent_evidence(agent: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    if not evidence:
        return agent
    agent_id = str(agent.get("id") or "")
    domain_keys = _agent_evidence_domains(agent_id)
    evidence_paths = _evidence_paths_for_domains(evidence, domain_keys)
    test_evidence = evidence.get("test_framework_evidence", {}) if isinstance(evidence.get("test_framework_evidence"), dict) else {}
    validation_command_evidence = (
        evidence.get("validation_command_evidence", {}) if isinstance(evidence.get("validation_command_evidence"), dict) else {}
    )
    risk_boundaries = evidence.get("risk_boundaries", {}) if isinstance(evidence.get("risk_boundaries"), dict) else {}
    attached = dict(agent)
    attached["codebase_evidence"] = {
        "status": evidence.get("status"),
        "domains": domain_keys,
        "paths": evidence_paths,
        "test_framework": test_evidence.get("framework"),
        "validation_commands": _dedupe_texts([str(item) for item in validation_command_evidence.get("commands", []) if item]),
        "risk_boundaries": risk_boundaries,
    }
    attached["inputs"] = _dedupe_texts(
        [
            *[str(item) for item in attached.get("inputs", []) if item],
            "codebase evidence",
            "risk boundaries",
            "test framework evidence",
        ]
    )
    validation = attached.get("validation", {})
    if not isinstance(validation, dict):
        validation = {}
    validation["required"] = _dedupe_texts(
        [
            *[str(item) for item in validation.get("required", []) if item],
            "codebase evidence path cited",
            "risk boundary checked",
        ]
    )
    attached["validation"] = validation
    return attached


def _agent_evidence_domains(agent_id: str) -> list[str]:
    mapping = {
        "web-experience-reviewer": ["website"],
        "hospitality-product-reviewer": ["hotel_site"],
        "agent-platform-contract-reviewer": ["agent_marketplace_platform"],
        "webhook-signature-reviewer": ["webhook"],
        "outbound-safety-reviewer": ["suppression", "send_pipeline", "outbound"],
        "supabase-schema-reviewer": ["supabase"],
        "scorecard-logic-reviewer": ["scoring", "customer"],
        "auth-flow-investigator": ["auth", "login"],
        "api-contract-reviewer": ["api"],
        "jest-regression-guardian": ["tests"],
        "pytest-regression-guardian": ["tests"],
        "test-regression-guardian": ["tests"],
        "typescript-code-reviewer": ["api"],
        "risk-reviewer": ["risk"],
        "ddmq-debugger": ["ddmq", "pipeline_automation", "stage_pipeline"],
        "anthropic-api-error-analyst": ["llm_api"],
        "stage-schema-validator": ["schema_validation", "stage_pipeline"],
    }
    return list(mapping.get(agent_id, []))


def _active_domains(plan: dict[str, Any]) -> list[str]:
    """weak 도메인을 제외하고 workforce 생성에 사용할 도메인을 반환한다."""
    harness_id = str(plan.get("harness_id") or "").lower()
    if "mission-company" in harness_id:
        return ["mission_company", "tests"]
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    confidence = evidence.get("domain_confidence", {}) if isinstance(evidence.get("domain_confidence"), dict) else {}
    candidates = confidence.get("candidates", {}) if isinstance(confidence.get("candidates"), dict) else {}
    if candidates:
        domains: list[str] = []
        for level in ["confirmed", "suspected"]:
            for domain, candidate in candidates.items():
                if isinstance(candidate, dict) and str(candidate.get("confidence") or "") == level:
                    domains.append(str(domain).lower())
        return _dedupe_texts(domains)
    project = plan.get("project", {}) if isinstance(plan.get("project"), dict) else {}
    return _dedupe_texts([str(item).lower() for item in project.get("domains", []) if item])


def _company_scale_plan(plan: dict[str, Any], domains: list[str]) -> dict[str, Any]:
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    risk_boundaries = evidence.get("risk_boundaries", {}) if isinstance(evidence.get("risk_boundaries"), dict) else {}
    important_paths = _dedupe_texts([str(item) for item in plan.get("important_paths", []) if item])
    product_domains = [domain for domain in _dedupe_texts(domains) if domain not in {"tests", "api"}]
    external_systems = _dedupe_texts([str(item) for item in risk_boundaries.get("external_systems", []) if item])
    signal_count = len(product_domains) + len(external_systems)
    path_count = len(important_paths)
    if signal_count >= 5 or path_count >= 10:
        company_size = "departmental"
        agent_cap = 8
    elif signal_count >= 3 or path_count >= 6:
        company_size = "project_fit"
        agent_cap = 7
    elif signal_count >= 1 or path_count >= 4:
        company_size = "focused"
        agent_cap = 5
    else:
        company_size = "compact"
        agent_cap = 4
    return {
        "company_size": company_size,
        "agent_cap": agent_cap,
        "target_lift_pct": 30,
        "product_domains": product_domains,
        "external_systems": external_systems,
        "important_path_count": path_count,
        "complexity_signal_count": signal_count,
        "policy": "Scale company size to codebase evidence; tests/api can support validation but cannot define product identity.",
    }


def _evidence_paths_for_domains(evidence: dict[str, Any], domains: list[str]) -> list[str]:
    domain_evidence = evidence.get("domain_evidence", {}) if isinstance(evidence.get("domain_evidence"), dict) else {}
    paths: list[str] = []
    for domain in domains:
        paths.extend([str(item) for item in domain_evidence.get(domain, []) if item])
    if not paths:
        paths.extend([str(item) for item in evidence.get("existing_important_paths", []) if item])
    return _dedupe_texts(paths)[:8]


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped


def build_company_structure(plan: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    """프로젝트 evidence와 설치 agent를 최소 회사 역할표로 매핑한다."""
    agent_ids = [str(agent.get("id") or "") for agent in agents if agent.get("id")]
    unique_agent_ids = _dedupe_texts(agent_ids)
    by_id = {str(agent.get("id")): agent for agent in agents if agent.get("id")}
    scale_plan = _company_scale_plan(plan, _active_domains(plan))
    context_agent = _first_available_agent(
        unique_agent_ids,
        ["root-cause-investigator", "agent-platform-contract-reviewer", "auth-flow-investigator", "webhook-signature-reviewer", "outbound-safety-reviewer"],
    ) or _first_agent_by_class(unique_agent_ids, ["context_analysis", "domain_execution", "contract_execution", "technical_review"])
    execution_agent = _first_available_agent(
        unique_agent_ids,
        [
            "webhook-signature-reviewer",
            "agent-platform-contract-reviewer",
            "outbound-safety-reviewer",
            "supabase-schema-reviewer",
            "scorecard-logic-reviewer",
            "auth-flow-investigator",
            "typescript-code-reviewer",
            "root-cause-investigator",
        ],
    ) or _first_agent_by_class(unique_agent_ids, ["domain_execution", "contract_execution", "technical_review", "context_analysis"])
    verification_agent = _first_available_agent(
        unique_agent_ids,
        ["jest-regression-guardian", "pytest-regression-guardian", "test-regression-guardian", "risk-reviewer"],
    ) or _first_agent_by_class(unique_agent_ids, ["verification"])
    direction_agent = _first_available_agent(
        unique_agent_ids,
        ["risk-reviewer", "api-contract-reviewer"],
    ) or _first_agent_by_class(unique_agent_ids, ["risk_direction", "technical_review", "verification"]) or context_agent
    fallback = unique_agent_ids[0] if unique_agent_ids else None
    roles = {
        "context_manager": _company_role(
            role_id="context_manager",
            office="context",
            agent_id=context_agent or fallback,
            responsibility="Maintain project context, evidence citations, uncertainty, and prior decisions for the current job.",
            evidence_paths=_company_role_evidence_paths(by_id.get(context_agent or fallback or ""), plan),
        ),
        "direction_owner": _company_role(
            role_id="direction_owner",
            office="direction",
            agent_id=direction_agent or fallback,
            responsibility="Keep the job inside the approved goal, change policy, and risk boundary.",
            evidence_paths=_company_policy_evidence_paths(plan),
        ),
        "execution_lead": _company_role(
            role_id="execution_lead",
            office="execution",
            agent_id=execution_agent or fallback,
            responsibility="Analyze the requested code path and produce only proposal-level work unless approval is explicit.",
            evidence_paths=_company_role_evidence_paths(by_id.get(execution_agent or fallback or ""), plan),
        ),
        "verification_owner": _company_role(
            role_id="verification_owner",
            office="verification",
            agent_id=verification_agent or fallback,
            responsibility="Select validation commands, identify regression risk, and block proof claims without evidence.",
            evidence_paths=_company_validation_evidence_paths(plan),
        ),
    }
    roles.update(_specialist_company_roles(unique_agent_ids, roles, by_id, plan))
    responsibility_matrix = _responsibility_matrix(roles)
    duplicate_agent_ids = [agent_id for agent_id in unique_agent_ids if agent_ids.count(agent_id) > 1]
    missing_roles = [role_id for role_id, role in roles.items() if not role.get("agent_id")]
    return {
        "mode": "project_fit_company" if scale_plan.get("company_size") in {"project_fit", "departmental"} else "lean_project_company",
        "status": "ready" if not missing_roles else "incomplete",
        "principle": "Scale the company to project evidence; create specialists only when codebase evidence justifies them.",
        "company_scale": scale_plan,
        "target_lift": {
            "pct": 30,
            "basis": "better project context, role coverage, validation selection, and risk gating than a raw AI prompt",
        },
        "roles": roles,
        "responsibility_matrix": responsibility_matrix,
        "duplicate_guard": {
            "agent_count": len(agent_ids),
            "unique_agent_count": len(unique_agent_ids),
            "max_agents": int(scale_plan.get("agent_cap") or 5),
            "duplicate_agent_ids": duplicate_agent_ids,
            "missing_roles": missing_roles,
            "same_agent_multi_role_allowed": True,
            "extra_agent_requires_codebase_evidence": True,
        },
    }


def _attach_company_roles(agents: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """각 agent에 회사 역할과 중복 방지 키를 덧붙인다."""
    company_structure = build_company_structure(plan, agents)
    roles = company_structure.get("roles", {}) if isinstance(company_structure.get("roles"), dict) else {}
    roles_by_agent: dict[str, list[str]] = {}
    offices_by_agent: dict[str, list[str]] = {}
    for role_id, role in roles.items():
        if not isinstance(role, dict):
            continue
        agent_id = str(role.get("agent_id") or "")
        if not agent_id:
            continue
        roles_by_agent.setdefault(agent_id, []).append(str(role_id))
        offices_by_agent.setdefault(agent_id, []).append(str(role.get("office") or ""))
    attached: list[dict[str, Any]] = []
    for agent in agents:
        agent_id = str(agent.get("id") or "")
        updated = dict(agent)
        company_roles = _dedupe_texts(roles_by_agent.get(agent_id, []))
        offices = _dedupe_texts(offices_by_agent.get(agent_id, []))
        updated["company_roles"] = company_roles
        updated["primary_company_role"] = company_roles[0] if company_roles else _agent_responsibility_class(agent_id)
        updated["company_offices"] = offices
        updated["responsibility_class"] = _agent_responsibility_class(agent_id)
        updated["duplicate_guard_key"] = f"{updated['responsibility_class']}:{','.join(_agent_evidence_domains(agent_id)) or 'general'}"
        attached.append(updated)
    return attached


def _company_role(
    *,
    role_id: str,
    office: str,
    agent_id: str | None,
    responsibility: str,
    evidence_paths: list[str],
) -> dict[str, Any]:
    """회사 역할 슬롯의 공통 payload를 만든다."""
    return {
        "role_id": role_id,
        "office": office,
        "agent_id": agent_id,
        "responsibility": responsibility,
        "evidence_paths": _dedupe_texts(evidence_paths)[:8],
        "approval_policy": "explicit",
    }


def _specialist_company_roles(
    agent_ids: list[str],
    base_roles: dict[str, dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    assigned = {str(role.get("agent_id") or "") for role in base_roles.values() if isinstance(role, dict)}
    specialists: dict[str, dict[str, Any]] = {}
    for agent_id in agent_ids:
        if not agent_id or agent_id in assigned:
            continue
        role_id = f"specialist_{agent_id.replace('-', '_')}"
        specialists[role_id] = _company_role(
            role_id=role_id,
            office="specialist",
            agent_id=agent_id,
            responsibility=f"Own project-specific review for {agent_id} when the request touches its evidence paths.",
            evidence_paths=_company_role_evidence_paths(by_id.get(agent_id), plan),
        )
    return specialists


def _responsibility_matrix(roles: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """agent별 담당 회사 역할 목록을 만든다."""
    matrix: dict[str, list[str]] = {}
    for role_id, role in roles.items():
        agent_id = str(role.get("agent_id") or "")
        if not agent_id:
            continue
        matrix.setdefault(agent_id, []).append(str(role_id))
    return {agent_id: _dedupe_texts(role_ids) for agent_id, role_ids in matrix.items()}


def _first_available_agent(agent_ids: list[str], preferred: list[str]) -> str | None:
    """선호 순서에서 설치된 첫 agent를 고른다."""
    for agent_id in preferred:
        if agent_id and agent_id in agent_ids:
            return agent_id
    return None


def _first_agent_by_class(agent_ids: list[str], classes: list[str]) -> str | None:
    """책임군 우선순위에 맞는 첫 에이전트를 고른다."""
    for responsibility_class in [str(item) for item in classes if item]:
        for agent_id in agent_ids:
            if _agent_responsibility_class(agent_id) == responsibility_class:
                return agent_id
    return None


def _agent_responsibility_class(agent_id: str) -> str:
    """Classify an agent id for lean company role mapping."""
    lowered = str(agent_id or "").lower()
    """agent id를 회사 책임군으로 분류한다."""
    if agent_id in {"jest-regression-guardian", "pytest-regression-guardian", "test-regression-guardian"}:
        return "verification"
    if agent_id == "risk-reviewer":
        return "risk_direction"
    if agent_id in {"api-contract-reviewer", "typescript-code-reviewer"}:
        return "technical_review"
    if agent_id == "agent-platform-contract-reviewer":
        return "contract_execution"
    if agent_id == "root-cause-investigator":
        return "context_analysis"
    if any(token in lowered for token in ["test", "pytest", "jest", "regression", "verification", "guardian", "validator"]):
        return "verification"
    if any(token in lowered for token in ["risk", "boundary", "approval", "rollback"]):
        return "risk_direction"
    if any(token in lowered for token in ["command-runner", "test-runner", "installer", "router", "file-operator", "artifact-writer"]):
        return "tool_execution"
    if any(token in lowered for token in ["api", "contract", "typescript", "web-input", "web", "route"]):
        return "technical_review"
    if any(token in lowered for token in ["ledger", "generation", "generator", "excel", "workbook", "template"]):
        return "domain_execution"
    return "domain_execution"


def _company_role_evidence_paths(agent: dict[str, Any] | None, plan: dict[str, Any]) -> list[str]:
    """역할이 인용해야 할 코드 evidence 경로를 고른다."""
    if isinstance(agent, dict):
        evidence = agent.get("codebase_evidence", {}) if isinstance(agent.get("codebase_evidence"), dict) else {}
        paths = _dedupe_texts([str(item) for item in evidence.get("paths", []) if item])
        if paths:
            return paths
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    return _dedupe_texts([str(item) for item in evidence.get("existing_important_paths", []) if item])


def _company_validation_evidence_paths(plan: dict[str, Any]) -> list[str]:
    """검증 책임자가 우선 확인할 테스트 evidence 경로를 고른다."""
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    test_evidence = evidence.get("test_framework_evidence", {}) if isinstance(evidence.get("test_framework_evidence"), dict) else {}
    paths = [str(item) for item in test_evidence.get("test_paths", []) if item]
    if not paths:
        paths = [str(item) for item in plan.get("important_paths", []) if item]
    return _dedupe_texts(paths)


def _company_policy_evidence_paths(plan: dict[str, Any]) -> list[str]:
    """방향 책임자가 확인할 정책/위험 evidence 경로를 고른다."""
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    risk_boundaries = evidence.get("risk_boundaries", {}) if isinstance(evidence.get("risk_boundaries"), dict) else {}
    refs = [str(item) for item in risk_boundaries.get("policy_refs", []) if item]
    if refs:
        return _dedupe_texts(refs)
    return _dedupe_texts([str(item) for item in plan.get("important_paths", []) if item])


def install_generated_workforce(project_root: Path, plan: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[Path]]:
    root = Path(project_root).resolve()
    workforce = build_workforce_payload(plan)
    agents = build_agent_payloads(plan, workforce)
    workforce["status"] = "installed"
    workforce["agents"] = [str(agent["id"]) for agent in agents]
    workforce["default_team"] = _default_team(workforce["agents"])
    workforce["company_structure"] = build_company_structure(plan, agents)
    workforce["responsibility_matrix"] = workforce["company_structure"].get("responsibility_matrix", {})
    workforce["duplicate_guard"] = workforce["company_structure"].get("duplicate_guard", {})
    workforce["agent_kind_summary"] = _agent_kind_summary(agents)
    workforce["agent_runtime_contracts"] = _agent_runtime_contracts(agents)
    try:
        from engine.project_skill_builder import build_skill_payloads, skill_mapping

        workforce["skills"] = skill_mapping(build_skill_payloads(plan, workforce))
    except Exception:
        workforce["skills"] = {}
    files = [_save_yaml(default_workforce_path(root), workforce)]
    agents_dir = default_generated_agents_dir(root)
    if agents_dir.exists():
        for old in agents_dir.glob("*.yaml"):
            old.unlink()
    for agent in agents:
        agent["status"] = "active"
        files.append(_save_yaml(agents_dir / f"{agent['id']}.yaml", agent))
    files.append(_save_yaml(default_operating_rules_path(root), _operating_rules(plan)))
    return workforce, agents, files


def load_workforce(project_root: Path) -> dict[str, Any] | None:
    path = default_workforce_path(project_root)
    if not path.exists():
        return None
    return _load_yaml(path)


def load_generated_agents(project_root: Path) -> list[dict[str, Any]]:
    root = Path(project_root).resolve()
    agents_dir = default_generated_agents_dir(root)
    if not agents_dir.exists():
        return []
    agents: list[dict[str, Any]] = []
    for path in sorted(agents_dir.glob("*.yaml")):
        payload = _load_yaml(path)
        if payload:
            agents.append(payload)
    return agents


def select_agents_for_request(project_root: Path, request: str, explicit_agent_id: str | None = None) -> tuple[list[str], str, dict[str, Any] | None]:
    root = Path(project_root).resolve()
    workforce = load_workforce(root)
    agents = load_generated_agents(root)
    available = {str(agent.get("id")): agent for agent in agents if agent.get("id")}
    if explicit_agent_id:
        if explicit_agent_id in available:
            return [explicit_agent_id], f"User explicitly requested {explicit_agent_id}.", workforce
        return [], f"Requested agent {explicit_agent_id} is not installed in the generated workforce.", workforce
    if not workforce:
        return [], "No generated workforce is installed.", None
    request_lower = str(request or "").lower()
    selected: list[str] = []
    if any(token in request_lower for token in ["webhook", "hmac", "signature", "svix", "서명"]):
        _append_if_available(selected, available, "webhook-signature-reviewer")
    if any(token in request_lower for token in ["agent pack", "agent-pack", "builder", "workspace", "다운로드", "에이전트", "pack 계약"]):
        _append_if_available(selected, available, "agent-platform-contract-reviewer")
    if any(token in request_lower for token in ["suppression", "unsubscribe", "outbound", "send", "delivery", "campaign", "발송", "차단"]):
        _append_if_available(selected, available, "outbound-safety-reviewer")
    if any(token in request_lower for token in ["supabase", "migration", "rls", "schema", "db", "마이그레이션"]):
        _append_if_available(selected, available, "supabase-schema-reviewer")
    if any(token in request_lower for token in ["score", "scorecard", "scoring", "customer", "icp", "고객", "점수"]):
        _append_if_available(selected, available, "scorecard-logic-reviewer")
    if any(token in request_lower for token in ["auth", "login", "token", "bearer", "session", "인증", "로그인", "세션", "토큰"]):
        _append_if_available(selected, available, "auth-flow-investigator")
    if not selected:
        for item in workforce.get("default_team", []):
            _append_if_available(selected, available, str(item))
    _append_first_agent_by_class(selected, available, "verification")
    _append_first_agent_by_class(selected, available, "risk_direction")
    _append_if_available(selected, available, "jest-regression-guardian")
    _append_if_available(selected, available, "pytest-regression-guardian")
    _append_if_available(selected, available, "test-regression-guardian")
    _append_if_available(selected, available, "risk-reviewer")
    selected = _prioritize_required_company_role_agents(selected, available, workforce)
    return selected[: _dispatch_agent_cap(workforce)], "Selected from generated workforce by request domain and validation needs.", workforce


def _prioritize_required_company_role_agents(
    selected: list[str],
    available: dict[str, dict[str, Any]],
    workforce: dict[str, Any] | None,
) -> list[str]:
    workforce_payload = workforce if isinstance(workforce, dict) else {}
    company = workforce_payload.get("company_structure", {}) if isinstance(workforce_payload.get("company_structure"), dict) else {}
    roles = company.get("roles", {}) if isinstance(company.get("roles"), dict) else {}
    required_agents: list[str] = []
    for role_id in ["execution_lead", "context_manager", "direction_owner", "verification_owner"]:
        role = roles.get(role_id)
        if not isinstance(role, dict):
            continue
        agent_id = str(role.get("agent_id") or "")
        if agent_id in available:
            required_agents.append(agent_id)
    prioritized: list[str] = []
    if selected:
        _append_unique(prioritized, selected[0])
    for agent_id in required_agents:
        _append_unique(prioritized, agent_id)
    for agent_id in selected[1:]:
        _append_unique(prioritized, agent_id)
    return prioritized


def _append_unique(selected: list[str], agent_id: str) -> None:
    if agent_id and agent_id not in selected:
        selected.append(agent_id)


def render_workforce_generate_result(result: WorkforceGenerateResult) -> str:
    title = "Workforce draft generated." if result.status == "draft" else "Workforce generation blocked."
    lines = [
        title,
        "",
        "Workforce:",
        f"  {result.workforce_id or 'none'}",
        "",
        "Harness:",
        f"  {result.harness_id or 'none'}",
        "",
        "Generated agents:",
    ]
    lines.extend([f"  - {agent.get('id')}: {agent.get('role')}" for agent in result.agents] or ["  - none"])
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    lines.extend(["", "Next:", f"  {result.next_command or 'none'}"])
    return "\n".join(lines)


def _append_if_available(selected: list[str], available: dict[str, dict[str, Any]], agent_id: str) -> None:
    if agent_id in available and agent_id not in selected:
        selected.append(agent_id)


def _append_first_agent_by_class(selected: list[str], available: dict[str, dict[str, Any]], responsibility_class: str) -> None:
    for agent_id in available:
        if _agent_responsibility_class(agent_id) == responsibility_class:
            _append_if_available(selected, available, agent_id)
            return


def _dispatch_agent_cap(workforce: dict[str, Any] | None) -> int:
    company = workforce.get("company_structure", {}) if isinstance(workforce, dict) else {}
    scale = company.get("company_scale", {}) if isinstance(company.get("company_scale"), dict) else {}
    company_size = str(scale.get("company_size") or "")
    if company_size == "departmental":
        return 6
    if company_size == "project_fit":
        return 5
    return 4


def _default_team(agent_ids: list[str]) -> list[str]:
    team: list[str] = []
    for responsibility_class in [
        "domain_execution",
        "contract_execution",
        "context_analysis",
        "technical_review",
        "verification",
        "risk_direction",
    ]:
        agent_id = _first_agent_by_class(agent_ids, [responsibility_class])
        if agent_id and agent_id not in team:
            team.append(agent_id)
    for agent_id in agent_ids:
        if agent_id not in team:
            team.append(agent_id)
        if len(team) >= 3:
            break
    return team[:3]


def _operating_rules(plan: dict[str, Any]) -> dict[str, Any]:
    policy = plan.get("policy", {}) if isinstance(plan.get("policy"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "proposal_only",
        "auto_apply": False,
        "dispatch_policy": {
            "mode": "on_demand",
            "auto_dispatch_on_install": False,
        },
        "forbidden": list(policy.get("forbidden", [])) if isinstance(policy.get("forbidden"), list) else [],
        "allowed": list(policy.get("allowed", [])) if isinstance(policy.get("allowed"), list) else [],
        "human_approval_required": True,
    }
