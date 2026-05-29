from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_llm_assist import LLM_GENERATION_EVIDENCE_KEY, call_llm_for_generation, llm_assist_policy
from engine.project_pack_install import SCHEMA_VERSION, _slug


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


def default_generated_skills_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "skills"


@dataclass
class SkillGenerateResult:
    schema_version: str
    generated_at: str
    status: str
    skillset_id: str | None
    harness_id: str | None
    skills: list[dict[str, Any]]
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


def build_skillset(project_root: Path, seed_preset: str | None = None, provider: Any | None = None) -> SkillGenerateResult:
    root = Path(project_root).resolve()
    from engine.project_custom_harness import build_custom_harness_plan
    from engine.project_workforce_builder import build_workforce_payload

    plan = build_custom_harness_plan(root, seed_preset=seed_preset)
    if plan is None:
        return SkillGenerateResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            skillset_id=None,
            harness_id=None,
            skills=[],
            next_command="cambrian harness interview start --json",
            errors=["Custom harness plan is not ready. Complete the harness interview first."],
        )
    workforce = build_workforce_payload(plan)
    llm_assist = _skill_generation_llm_assist(plan, workforce, provider)
    skills = build_skill_payloads(plan, workforce)
    return SkillGenerateResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="draft",
        skillset_id=_skillset_id(str(plan.get("harness_id") or "custom-harness")),
        harness_id=str(plan.get("harness_id") or ""),
        skills=skills,
        next_command="cambrian harness install --confirm --json",
        warnings=list(plan.get("warnings", [])),
        errors=[],
        llm_assist_policy=dict(llm_assist.get("policy", {})),
        llm_generation_evidence=dict(llm_assist.get(LLM_GENERATION_EVIDENCE_KEY, {})),
        generation_quality_status=str(llm_assist.get("policy", {}).get("quality_status") or ""),
    )


def _skill_generation_llm_assist(plan: dict[str, Any], workforce: dict[str, Any], provider: Any | None) -> dict[str, Any]:
    system = (
        "You are Cambrian's skill generation intelligence layer. "
        "Review the harness plan and generated workforce, then advise what project-specific skills, "
        "fusion opportunities, procedures, and validation evidence should be created. "
        "Return concise notes only; Cambrian will keep local safety gates."
    )
    user = yaml.safe_dump(
        {
            "harness_id": plan.get("harness_id"),
            "goal": plan.get("goal"),
            "project": plan.get("project"),
            "workforce_agents": workforce.get("agents") if isinstance(workforce, dict) else None,
            "validation": plan.get("validation"),
            "important_paths": plan.get("important_paths"),
            "codebase_evidence": plan.get("codebase_evidence"),
        },
        allow_unicode=True,
        sort_keys=False,
    )
    return call_llm_for_generation(provider, stage="skill_generation", system=system, user=user)


def build_skill_payloads(plan: dict[str, Any], workforce: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    project = plan.get("project", {}) if isinstance(plan.get("project"), dict) else {}
    validation = plan.get("validation", {}) if isinstance(plan.get("validation"), dict) else {}
    policy = plan.get("policy", {}) if isinstance(plan.get("policy"), dict) else {}
    domains = _active_domains(plan)
    test_framework = str(project.get("test_framework") or "").lower()
    test_commands = [str(item) for item in validation.get("test_commands", []) if item]
    forbidden = [str(item) for item in policy.get("forbidden", []) if item]
    important_paths = [str(item) for item in plan.get("important_paths", []) if item]
    harness_id = str(plan.get("harness_id") or "custom-harness")
    agent_ids = _workforce_agent_ids(workforce)
    primary_agent = _primary_analysis_agent(agent_ids)
    test_agent = _test_agent(agent_ids)
    risk_agent = _risk_agent(agent_ids)
    skills: list[dict[str, Any]] = []
    if "ddmq-debugger" in agent_ids:
        skills.append(
            _skill(
                "debug-ddmq-queue-flow",
                harness_id,
                ["ddmq-debugger"],
                "Inspect DDMQ dropzone flow, stage handoff, archive routing, and duplicate event risks.",
                ["DDMQ queue flow", "stage handoff", "archive/error routing"],
                ["Cite the DDMQ and orchestrator paths.", "Trace input/output/archive movement for the requested stage.", "List duplicate event or dead-letter risks before proposing a patch."],
                ["DDMQ queue-flow findings", "handoff risk notes", "patch proposal input"],
                forbidden,
                important_paths,
            )
        )
    if "anthropic-api-error-analyst" in agent_ids:
        skills.append(
            _skill(
                "review-anthropic-api-errors",
                harness_id,
                ["anthropic-api-error-analyst"],
                "Classify Anthropic or LLM API failures, token/rate-limit boundaries, and fallback behavior.",
                ["Anthropic API errors", "rate limits", "provider boundary"],
                ["Find provider call sites before proposing changes.", "Separate missing key, rate limit, response parsing, and model failure modes.", "Record external API risk and validation limits."],
                ["provider failure classification", "API risk notes", "patch proposal input"],
                forbidden,
                important_paths,
            )
        )
    if "stage-schema-validator" in agent_ids:
        skills.append(
            _skill(
                "validate-stage-schema-contract",
                harness_id,
                ["stage-schema-validator"],
                "Verify STAGE_SCHEMAS, schema validator behavior, Null Mandate, and stage IO compatibility.",
                ["stage schema contract", "Null Mandate", "stage IO drift"],
                ["Cite schema registry and validator paths.", "Check the requested stage input/output fields against STAGE_SCHEMAS.", "Block completion claims when schema or Null Mandate evidence is missing."],
                ["stage schema findings", "compatibility risk notes", "validation command input"],
                forbidden,
                important_paths,
            )
        )
    if "website" in domains:
        skills.append(
            _skill(
                "shape-website-golden-path",
                harness_id,
                ["web-experience-reviewer"],
                "Review the website goal, first viewport, navigation, local run path, and evidence needed before implementation.",
                ["Website goal framing", "first viewport and page flow", "local validation boundary"],
                ["Confirm the product promise from identity docs.", "Map expected visitor journey and page sections.", "Select a local validation command before claiming readiness."],
                ["website golden path notes", "page structure risks", "local validation notes"],
                forbidden,
                important_paths,
            )
        )
    if "hotel_site" in domains:
        skills.append(
            _skill(
                "review-hospitality-site-contract",
                harness_id,
                ["hospitality-product-reviewer"],
                "Review hotel website requirements, guest trust signals, booking intent, and local PC handoff boundaries.",
                ["Hotel guest journey", "room/location/contact facts", "booking and trust assumptions"],
                ["Extract hotel audience and stay intent from project docs.", "Check room, location, trust, contact, and booking assumptions.", "Flag missing business facts as confirmation-required."],
                ["hotel site requirement notes", "guest conversion risks", "confirmation-required facts"],
                forbidden,
                important_paths,
            )
        )
    if "agent_marketplace_platform" in domains:
        skills.append(
            _skill(
                "review-agent-pack-contract",
                harness_id,
                ["agent-platform-contract-reviewer"],
                "AI 에이전트 pack 생성, 다운로드, Import 계약을 검토한다.",
                ["Builder 계약 변경", "agent pack 다운로드/Import 검토", "Cambrian 런타임 선택형 경계 확인"],
                ["Builder 입력과 pack 출력 계약을 확인한다.", "다운로드/Import roundtrip 영향을 정리한다.", "Cambrian 런타임 결합도가 선택형으로 남는지 확인한다."],
                ["agent pack contract notes", "builder flow risk notes", "runtime coupling notes"],
                forbidden,
                important_paths,
            )
        )
    if "webhook" in domains:
        skills.append(
            _skill(
                "trace-webhook-hmac",
                harness_id,
                ["webhook-signature-reviewer"],
                "Webhook HMAC/Svix 서명 검증 흐름을 추적한다.",
                ["Webhook 검증 실패", "HMAC 서명 오류", "Svix raw body 검증"],
                ["raw body와 서명 헤더 처리 경로를 확인한다.", "401/재시도 부작용을 정리한다.", "검증 명령과 관련 파일을 연결한다."],
                ["webhook signature findings", "HMAC regression notes"],
                forbidden,
                important_paths,
            )
        )
    if "suppression" in domains or "outbound" in domains:
        skills.append(
            _skill(
                "review-suppression-policy",
                harness_id,
                ["outbound-safety-reviewer"],
                "suppression, unsubscribe, 차단 수신자 정책을 검토한다.",
                ["발송 전 차단 조건 검증", "suppression 정책 누락", "unsubscribe 우회 위험"],
                ["발송 전 정책 체크 경로를 찾는다.", "차단 조건과 예외 처리를 확인한다.", "운영 리스크와 테스트 영향을 정리한다."],
                ["suppression policy findings", "blocked-send risk notes"],
                forbidden,
                important_paths,
            )
        )
    if "send_pipeline" in domains:
        skills.append(
            _skill(
                "trace-send-pipeline",
                harness_id,
                ["outbound-safety-reviewer"],
                "발송 파이프라인의 큐, 재시도, 전달 흐름을 추적한다.",
                ["발송 job 실패", "delivery retry 문제", "outbound pipeline 변경"],
                ["발송 job 진입점을 찾는다.", "큐/재시도/실패 경계를 확인한다.", "suppression 정책과 연결되는지 검토한다."],
                ["send pipeline notes", "delivery risk notes"],
                forbidden,
                important_paths,
            )
        )
    if "supabase" in domains:
        skills.append(
            _skill(
                "review-supabase-migrations",
                harness_id,
                ["supabase-schema-reviewer"],
                "Supabase migration, RLS, schema 일관성을 검토한다.",
                ["Supabase schema 변경", "migration 검토", "RLS 정책 영향"],
                ["적용된 migration 수정 여부를 확인한다.", "RLS/정책 변경 위험을 정리한다.", "DB 변경은 수동 승인 전 금지한다."],
                ["migration consistency notes", "Supabase risk notes"],
                forbidden,
                important_paths,
            )
        )
    if "scoring" in domains or "customer" in domains:
        skills.append(
            _skill(
                "trace-scorecard-logic",
                harness_id,
                ["scorecard-logic-reviewer"],
                "고객 선정과 scorecard 계산 로직을 추적한다.",
                ["scorecard 계산 변경", "ICP 고객 선정 기준 검토", "scoring 회귀 위험"],
                ["점수 입력과 가중치 경로를 확인한다.", "선정 기준 변경 영향을 정리한다.", "검증 기준과 관련 테스트를 연결한다."],
                ["scorecard logic notes", "customer selection risk notes"],
                forbidden,
                important_paths,
            )
        )
    if "auth" in domains:
        skills.append(
            _skill(
                "trace-auth-token-flow",
                harness_id,
                ["auth-flow-investigator"],
                "Bearer token parsing and auth middleware flow를 추적한다.",
                ["로그인 실패", "인증 미들웨어 오류", "Bearer token 파싱 문제"],
                ["요청에서 인증 실패 조건을 추출한다.", "auth middleware 경로를 확인한다.", "토큰 파싱/검증/사용자 주입 흐름을 추적한다.", "테스트와 연결되는 실패 조건을 정리한다."],
                ["root cause hypothesis", "evidence notes", "patch proposal input"],
                forbidden,
                important_paths,
            )
        )
    else:
        skills.append(
            _skill(
                "trace-failure-flow",
                harness_id,
                _analysis_agents(agent_ids),
                "문제 재현 경로와 실패 흐름을 추적한다.",
                ["버그 재현", "실패 흐름 분석"],
                ["요청에서 실패 조건을 추출한다.", "관련 경로를 확인한다.", "테스트와 연결되는 실패 조건을 정리한다."],
                ["root cause hypothesis", "evidence notes"],
                forbidden,
                important_paths,
            )
        )
    jest_skill_id = "inspect-jest-auth-test" if "auth" in domains else "inspect-jest-regression"
    pytest_skill_id = "inspect-pytest-auth-test" if "auth" in domains else "inspect-pytest-regression"
    if test_framework == "jest" or any("jest" in command.lower() for command in test_commands):
        skills.append(
            _skill(
                jest_skill_id,
                harness_id,
                [test_agent],
                "Jest auth test와 실패 조건을 분석한다.",
                ["Jest 테스트 실패", "인증 회귀 테스트"],
                ["관련 테스트 파일을 확인한다.", "실패 조건과 기대 동작을 정리한다.", "추가 회귀 테스트 후보를 제안한다."],
                ["test impact notes", "regression suggestions"],
                forbidden,
                test_commands,
            )
        )
    elif test_framework == "pytest" or any("pytest" in command.lower() for command in test_commands):
        skills.append(
            _skill(
                pytest_skill_id,
                harness_id,
                [test_agent],
                "pytest auth test와 실패 조건을 분석한다.",
                ["pytest 테스트 실패", "인증 회귀 테스트"],
                ["관련 테스트 파일을 확인한다.", "실패 조건과 기대 동작을 정리한다.", "추가 회귀 테스트 후보를 제안한다."],
                ["test impact notes", "regression suggestions"],
                forbidden,
                test_commands,
            )
        )
    skills.append(
        _skill(
            "propose-safe-patch",
            harness_id,
            _patch_agents_for_domains(domains, agent_ids),
            "자동 적용 없이 안전한 patch proposal을 만든다.",
            ["수정 제안 필요", "proposal_only 정책"],
            ["수정 범위를 좁힌다.", "old_text/new_text 기반 패치 후보를 만든다.", "금지 범위를 위반하지 않는지 확인한다."],
            ["patch proposal", "risk notes"],
            forbidden,
            important_paths,
        )
    )
    skills.append(
        _skill(
            "review-regression-risk",
            harness_id,
            [risk_agent],
            "수정 제안의 회귀/보안/API 계약 리스크를 검토한다.",
            ["패치 검토", "운영 리스크 검토"],
            ["부작용 가능성을 분류한다.", "검증 명령과 수동 확인 항목을 정리한다."],
            ["risk notes", "manual review checklist"],
            forbidden,
            test_commands,
        )
    )
    if "api" in domains:
        skills.append(
            _skill(
                "review-api-contract",
                harness_id,
                ["api-contract-reviewer"],
                "API 응답 형식과 인증 실패 케이스 계약을 검토한다.",
                ["API 응답 변경", "인증 실패 케이스"],
                ["응답 코드와 메시지 변경 가능성을 확인한다.", "클라이언트 영향 범위를 정리한다."],
                ["api contract notes", "compatibility risks"],
                forbidden,
                important_paths,
            )
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill in skills:
        skill_id = str(skill.get("id") or "")
        if skill_id and skill_id not in seen:
            seen.add(skill_id)
            deduped.append(skill)
    filtered = _filter_skills_for_available_agents(deduped, agent_ids)
    return [_attach_skill_evidence(skill, plan) for skill in filtered[:10]]


def _filter_skills_for_available_agents(skills: list[dict[str, Any]], agent_ids: list[str]) -> list[dict[str, Any]]:
    available = {str(agent_id) for agent_id in agent_ids if agent_id}
    if not available:
        return skills
    filtered: list[dict[str, Any]] = []
    for skill in skills:
        assigned = [str(agent_id) for agent_id in skill.get("assigned_agents", []) if agent_id] if isinstance(skill, dict) else []
        if not assigned or any(agent_id in available for agent_id in assigned):
            filtered.append(skill)
    return filtered


def _attach_skill_evidence(skill: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    if not evidence:
        return skill
    skill_id = str(skill.get("id") or "")
    domain_keys = _skill_evidence_domains(skill_id)
    evidence_paths = _evidence_paths_for_domains(evidence, domain_keys)
    test_evidence = evidence.get("test_framework_evidence", {}) if isinstance(evidence.get("test_framework_evidence"), dict) else {}
    risk_boundaries = evidence.get("risk_boundaries", {}) if isinstance(evidence.get("risk_boundaries"), dict) else {}
    attached = dict(skill)
    attached["codebase_evidence"] = {
        "status": evidence.get("status"),
        "domains": domain_keys,
        "paths": evidence_paths,
        "test_framework": test_evidence.get("framework"),
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


def _skill_evidence_domains(skill_id: str) -> list[str]:
    mapping = {
        "shape-website-golden-path": ["website"],
        "review-hospitality-site-contract": ["hotel_site"],
        "review-agent-pack-contract": ["agent_marketplace_platform"],
        "trace-webhook-hmac": ["webhook"],
        "review-suppression-policy": ["suppression", "outbound"],
        "trace-send-pipeline": ["send_pipeline", "outbound"],
        "review-supabase-migrations": ["supabase"],
        "trace-scorecard-logic": ["scoring", "customer"],
        "trace-auth-token-flow": ["auth", "login"],
        "trace-auth-flow": ["auth", "login"],
        "inspect-jest-auth-test": ["tests"],
        "inspect-pytest-auth-test": ["tests"],
        "inspect-jest-regression": ["tests"],
        "inspect-pytest-regression": ["tests"],
        "propose-safe-patch": [],
        "review-regression-risk": [],
        "review-api-contract": ["api"],
        "debug-ddmq-queue-flow": ["ddmq", "pipeline_automation", "stage_pipeline"],
        "review-anthropic-api-errors": ["llm_api"],
        "validate-stage-schema-contract": ["schema_validation", "stage_pipeline"],
    }
    return list(mapping.get(skill_id, []))


def _evidence_paths_for_domains(evidence: dict[str, Any], domains: list[str]) -> list[str]:
    domain_evidence = evidence.get("domain_evidence", {}) if isinstance(evidence.get("domain_evidence"), dict) else {}
    paths: list[str] = []
    for domain in domains:
        paths.extend([str(item) for item in domain_evidence.get(domain, []) if item])
    if not paths:
        paths.extend([str(item) for item in evidence.get("existing_important_paths", []) if item])
    return _dedupe_texts(paths)[:8]


def _patch_agents_for_domains(domains: list[str], agent_ids: list[str] | None = None) -> list[str]:
    ordered_agent_ids = list(agent_ids or [])
    available = set(ordered_agent_ids)
    preferred = [
        ("website", "web-experience-reviewer"),
        ("hotel_site", "hospitality-product-reviewer"),
        ("agent_marketplace_platform", "agent-platform-contract-reviewer"),
        ("webhook", "webhook-signature-reviewer"),
        ("suppression", "outbound-safety-reviewer"),
        ("send_pipeline", "outbound-safety-reviewer"),
        ("outbound", "outbound-safety-reviewer"),
        ("supabase", "supabase-schema-reviewer"),
        ("scoring", "scorecard-logic-reviewer"),
        ("customer", "scorecard-logic-reviewer"),
        ("auth", "auth-flow-investigator"),
    ]
    agents: list[str] = []
    for domain, agent_id in preferred:
        if domain in domains and (not available or agent_id in available) and agent_id not in agents:
            agents.append(agent_id)
    if not agents:
        agents.append(_primary_analysis_agent(ordered_agent_ids))
    risk_agent = _risk_agent(ordered_agent_ids)
    if risk_agent not in agents:
        agents.append(risk_agent)
    return _dedupe_texts(agents)


def _workforce_agent_ids(workforce: dict[str, Any] | None) -> list[str]:
    if not isinstance(workforce, dict):
        return []
    agents = workforce.get("agents", [])
    if not isinstance(agents, list):
        return []
    ids: list[str] = []
    for agent in agents:
        if isinstance(agent, dict):
            agent_id = str(agent.get("id") or "").strip()
        else:
            agent_id = str(agent or "").strip()
        if agent_id:
            ids.append(agent_id)
    return _dedupe_texts(ids)


def _primary_analysis_agent(agent_ids: list[str]) -> str:
    for agent_id in agent_ids:
        lowered = agent_id.lower()
        if not any(token in lowered for token in ["risk", "boundary", "test", "pytest", "jest", "regression", "verification"]):
            return agent_id
    return agent_ids[0] if agent_ids else "root-cause-investigator"


def _analysis_agents(agent_ids: list[str]) -> list[str]:
    agents = [
        agent_id
        for agent_id in agent_ids
        if not any(token in agent_id.lower() for token in ["risk", "boundary", "test", "pytest", "jest", "regression", "verification"])
    ]
    return agents or [_primary_analysis_agent(agent_ids)]


def _test_agent(agent_ids: list[str]) -> str:
    for agent_id in agent_ids:
        lowered = agent_id.lower()
        if any(token in lowered for token in ["test", "pytest", "jest", "regression", "verification", "guardian"]):
            return agent_id
    return "test-regression-guardian"


def _risk_agent(agent_ids: list[str]) -> str:
    for agent_id in agent_ids:
        lowered = agent_id.lower()
        if any(token in lowered for token in ["risk", "boundary", "approval", "rollback"]):
            return agent_id
    return "risk-reviewer"


def _active_domains(plan: dict[str, Any]) -> list[str]:
    """weak 도메인을 제외하고 skill 생성에 사용할 도메인을 반환한다."""
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


def install_generated_skills(project_root: Path, plan: dict[str, Any], workforce: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[Path]]:
    root = Path(project_root).resolve()
    skills = build_skill_payloads(plan, workforce)
    skills_dir = default_generated_skills_dir(root)
    if skills_dir.exists():
        for old in skills_dir.glob("*.yaml"):
            old.unlink()
    files: list[Path] = []
    for skill in skills:
        skill["status"] = "active"
        files.append(_save_yaml(skills_dir / f"{skill['id']}.yaml", skill))
    return skills, skill_mapping(skills), files


def load_generated_skills(project_root: Path) -> list[dict[str, Any]]:
    skills_dir = default_generated_skills_dir(project_root)
    if not skills_dir.exists():
        return []
    skills: list[dict[str, Any]] = []
    for path in sorted(skills_dir.glob("*.yaml")):
        payload = _load_yaml(path)
        if payload:
            skills.append(payload)
    return skills


def search_generated_skills(project_root: Path, query: str, limit: int = 10) -> dict[str, Any]:
    """설치된 generated skill을 provider 호출 없이 검색한다."""
    skills = load_generated_skills(project_root)
    query_text = str(query or "").strip()
    query_tokens = _search_tokens(query_text)
    results: list[dict[str, Any]] = []
    for skill in skills:
        haystack = _skill_search_text(skill)
        score = _skill_search_score(query_tokens, haystack)
        if query_tokens and score <= 0:
            continue
        results.append(
            {
                "id": str(skill.get("id") or ""),
                "type": str(skill.get("type") or ""),
                "status": str(skill.get("status") or ""),
                "purpose": str(skill.get("purpose") or ""),
                "assigned_agents": [str(item) for item in skill.get("assigned_agents", []) if item],
                "score": score if query_tokens else 1,
                "source": "project_generated_skill",
            }
        )
    results.sort(key=lambda item: (-int(item["score"]), str(item["id"])))
    return {
        "ok": True,
        "status": "searched",
        "query": query_text,
        "total_skills": len(skills),
        "result_count": len(results[:limit]),
        "results": results[:limit],
    }


def fuse_generated_skills(
    project_root: Path,
    skill_a_id: str,
    skill_b_id: str,
    goal: str,
    output_id: str | None = None,
) -> dict[str, Any]:
    """generated skill 2개를 오프라인으로 융합해 새 project skill로 저장한다."""
    root = Path(project_root).resolve()
    if len(str(goal or "").strip()) < 5:
        raise ValueError("goal은 최소 5자 이상이어야 합니다.")
    if skill_a_id == skill_b_id:
        raise ValueError("같은 스킬을 자기 자신과 융합할 수 없습니다.")
    skills = {str(skill.get("id") or ""): skill for skill in load_generated_skills(root)}
    missing = [skill_id for skill_id in [skill_a_id, skill_b_id] if skill_id not in skills]
    if missing:
        raise ValueError("generated skill을 찾을 수 없습니다: " + ", ".join(missing))
    skill_a = skills[skill_a_id]
    skill_b = skills[skill_b_id]
    fused_id = output_id or _fused_skill_id(skill_a_id, skill_b_id)
    if not fused_id:
        raise ValueError("fused skill id를 만들 수 없습니다.")
    if fused_id in skills:
        fused_id = _next_available_fused_id(fused_id, set(skills))
    fused = _fused_skill_payload(fused_id, skill_a, skill_b, goal)
    target = default_generated_skills_dir(root) / f"{fused_id}.yaml"
    _save_yaml(target, fused)
    _attach_skill_to_workforce(root, fused)
    return {
        "ok": True,
        "status": "fused",
        "skill_id": fused_id,
        "skill_ref": str(target.relative_to(root)).replace("\\", "/"),
        "source_skill_ids": [skill_a_id, skill_b_id],
        "goal": str(goal),
        "registered_in_workforce": True,
        "provider_used": False,
        "source_code_modified": False,
        "next_command": f'cambrian job start "{goal}" --json',
    }


def select_skills_for_agents(project_root: Path, selected_agents: list[str], request: str) -> list[str]:
    skills = load_generated_skills(project_root)
    request_lower = str(request or "").lower()
    selected: list[str] = []
    for skill in skills:
        assigned = [str(item) for item in skill.get("assigned_agents", []) if item]
        if any(agent in selected_agents for agent in assigned):
            skill_id = str(skill.get("id") or "")
            if skill_id and skill_id not in selected:
                selected.append(skill_id)
    if any(token in request_lower for token in ["auth", "login", "token", "bearer", "session", "인증", "로그인", "세션", "토큰"]):
        _append_skill(selected, "trace-auth-token-flow", skills)
        _append_skill(selected, "inspect-jest-auth-test", skills)
        _append_skill(selected, "inspect-pytest-auth-test", skills)
    if any(token in request_lower for token in ["webhook", "hmac", "signature", "svix", "서명"]):
        _append_skill(selected, "trace-webhook-hmac", skills)
    if any(token in request_lower for token in ["agent pack", "agent-pack", "builder", "workspace", "다운로드", "에이전트", "pack 계약"]):
        _append_skill(selected, "review-agent-pack-contract", skills)
    if any(token in request_lower for token in ["suppression", "unsubscribe", "outbound", "send", "delivery", "campaign", "발송", "차단"]):
        _append_skill(selected, "review-suppression-policy", skills)
        _append_skill(selected, "trace-send-pipeline", skills)
    if any(token in request_lower for token in ["supabase", "migration", "rls", "schema", "db", "마이그레이션"]):
        _append_skill(selected, "review-supabase-migrations", skills)
    if any(token in request_lower for token in ["score", "scorecard", "scoring", "customer", "icp", "고객", "점수"]):
        _append_skill(selected, "trace-scorecard-logic", skills)
    _append_skill(selected, "propose-safe-patch", skills)
    _append_skill(selected, "review-regression-risk", skills)
    return selected[:5]


def skill_mapping(skills: list[dict[str, Any]]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for skill in skills:
        skill_id = str(skill.get("id") or "")
        for agent_id in skill.get("assigned_agents", []):
            key = str(agent_id)
            mapping.setdefault(key, [])
            if skill_id and skill_id not in mapping[key]:
                mapping[key].append(skill_id)
    return mapping


def render_skill_generate_result(result: SkillGenerateResult) -> str:
    title = "Skillset draft generated." if result.status == "draft" else "Skill generation blocked."
    lines = [
        title,
        "",
        "Skillset:",
        f"  {result.skillset_id or 'none'}",
        "",
        "Harness:",
        f"  {result.harness_id or 'none'}",
        "",
        "Generated skills:",
    ]
    lines.extend([f"  - {skill.get('id')}: {skill.get('purpose')}" for skill in result.skills] or ["  - none"])
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    lines.extend(["", "Next:", f"  {result.next_command or 'none'}"])
    return "\n".join(lines)


def _skill(
    skill_id: str,
    harness_id: str,
    assigned_agents: list[str],
    purpose: str,
    when_to_use: list[str],
    procedure: list[str],
    outputs: list[str],
    forbidden: list[str],
    extra_inputs: list[str],
) -> dict[str, Any]:
    generation_policy = llm_assist_policy("skill_generation", provider_used=False)
    return {
        "schema_version": SCHEMA_VERSION,
        "id": skill_id,
        "type": "generated_skill",
        "status": "draft",
        "generation_contract": {
            "requires_llm_for_intelligent_generation": True,
            "quality_status": generation_policy["quality_status"],
            "llm_enrichment_required": generation_policy["llm_enrichment_required"],
            "evidence_key": LLM_GENERATION_EVIDENCE_KEY,
        },
        "harness_id": harness_id,
        "assigned_agents": [agent for agent in assigned_agents if agent],
        "purpose": purpose,
        "when_to_use": when_to_use,
        "inputs": ["사용자 작업 요청", "project profile", "important paths", *extra_inputs],
        "procedure": procedure,
        "outputs": outputs,
        "forbidden": forbidden,
        "validation": {
            "required": ["관련 테스트 영향 설명", "회귀 위험 설명"],
        },
    }


def _append_skill(selected: list[str], skill_id: str, skills: list[dict[str, Any]]) -> None:
    available = {str(skill.get("id")) for skill in skills}
    if skill_id in available and skill_id not in selected:
        selected.append(skill_id)


def _skillset_id(harness_id: str) -> str:
    return f"skillset-{_slug(harness_id.removeprefix('custom-'), 'project')}"


def _search_tokens(query: str) -> list[str]:
    return [
        token
        for token in _slug(query.replace("-", " "), "query").replace("-", " ").split()
        if token
    ]


def _skill_search_text(skill: dict[str, Any]) -> str:
    parts: list[str] = [
        str(skill.get("id") or ""),
        str(skill.get("purpose") or ""),
    ]
    for key in ["when_to_use", "procedure", "outputs", "assigned_agents", "inputs"]:
        values = skill.get(key, [])
        if isinstance(values, list):
            parts.extend(str(item) for item in values if item)
    return _slug(" ".join(parts).replace("-", " "), "skill").replace("-", " ")


def _skill_search_score(tokens: list[str], haystack: str) -> int:
    return sum(1 for token in tokens if token in haystack)


def _fused_skill_id(skill_a_id: str, skill_b_id: str) -> str:
    return _slug(f"{skill_a_id}-{skill_b_id}-fused", "fused-skill")


def _next_available_fused_id(base_id: str, existing: set[str]) -> str:
    index = 2
    candidate = f"{base_id}-{index}"
    while candidate in existing:
        index += 1
        candidate = f"{base_id}-{index}"
    return candidate


def _fused_skill_payload(
    fused_id: str,
    skill_a: dict[str, Any],
    skill_b: dict[str, Any],
    goal: str,
) -> dict[str, Any]:
    generation_policy = llm_assist_policy("skill_fusion", provider_used=False)
    assigned_agents = _dedupe_texts(
        [
            *[str(item) for item in skill_a.get("assigned_agents", []) if item],
            *[str(item) for item in skill_b.get("assigned_agents", []) if item],
        ]
    )
    forbidden = _dedupe_texts(
        [
            *[str(item) for item in skill_a.get("forbidden", []) if item],
            *[str(item) for item in skill_b.get("forbidden", []) if item],
        ]
    )
    procedure = _dedupe_texts(
        [
            f"{skill_a.get('id')}: {item}"
            for item in skill_a.get("procedure", [])
            if item
        ]
        + [
            f"{skill_b.get('id')}: {item}"
            for item in skill_b.get("procedure", [])
            if item
        ]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "id": fused_id,
        "type": "generated_skill",
        "status": "draft",
        "generation_contract": {
            "requires_llm_for_intelligent_generation": True,
            "quality_status": generation_policy["quality_status"],
            "llm_enrichment_required": generation_policy["llm_enrichment_required"],
            "evidence_key": LLM_GENERATION_EVIDENCE_KEY,
        },
        "harness_id": str(skill_a.get("harness_id") or skill_b.get("harness_id") or ""),
        "assigned_agents": assigned_agents,
        "purpose": str(goal),
        "when_to_use": _dedupe_texts(
            [
                str(goal),
                *[str(item) for item in skill_a.get("when_to_use", []) if item],
                *[str(item) for item in skill_b.get("when_to_use", []) if item],
            ]
        ),
        "inputs": _dedupe_texts(
            [
                *[str(item) for item in skill_a.get("inputs", []) if item],
                *[str(item) for item in skill_b.get("inputs", []) if item],
            ]
        ),
        "procedure": procedure,
        "outputs": _dedupe_texts(
            [
                *[str(item) for item in skill_a.get("outputs", []) if item],
                *[str(item) for item in skill_b.get("outputs", []) if item],
                "fused skill evidence notes",
            ]
        ),
        "forbidden": forbidden,
        "validation": {
            "required": _dedupe_texts(
                [
                    *[str(item) for item in skill_a.get("validation", {}).get("required", []) if item],
                    *[str(item) for item in skill_b.get("validation", {}).get("required", []) if item],
                    "융합된 절차가 원본 두 스킬의 금지 범위를 넘지 않는지 확인",
                ]
            ),
        },
        "provenance": {
            "kind": "offline_generated_skill_fusion",
            "source_skill_ids": [str(skill_a.get("id") or ""), str(skill_b.get("id") or "")],
            "provider_used": False,
            "llm_enrichment_required": True,
            "source_code_modified": False,
        },
    }


def _attach_skill_to_workforce(project_root: Path, skill: dict[str, Any]) -> None:
    workforce_path = Path(project_root).resolve() / ".cambrian" / "workforce.yaml"
    if not workforce_path.exists():
        return
    workforce = _load_yaml(workforce_path)
    skill_id = str(skill.get("id") or "")
    if not skill_id:
        return
    skills_by_agent = workforce.setdefault("skills", {})
    if not isinstance(skills_by_agent, dict):
        workforce["skills"] = {}
        skills_by_agent = workforce["skills"]
    for agent_id in skill.get("assigned_agents", []):
        key = str(agent_id)
        current = skills_by_agent.setdefault(key, [])
        if isinstance(current, list) and skill_id not in current:
            current.append(skill_id)
    _save_yaml(workforce_path, workforce)


def _dedupe_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped
