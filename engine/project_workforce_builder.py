from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "draft"
        return payload


def build_workforce(project_root: Path) -> WorkforceGenerateResult:
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
    workforce = build_workforce_payload(plan)
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
    )


def build_workforce_payload(plan: dict[str, Any]) -> dict[str, Any]:
    harness_id = str(plan.get("harness_id") or "custom-harness")
    workforce_id = f"workforce-{_slug(harness_id.removeprefix('custom-'), 'project')}"
    agents = build_agent_payloads(plan, {"id": workforce_id, "harness_id": harness_id})
    try:
        from engine.project_skill_builder import build_skill_payloads, skill_mapping

        skills = skill_mapping(build_skill_payloads(plan, {"id": workforce_id, "harness_id": harness_id}))
    except Exception:
        skills = {}
    agent_ids = [str(agent["id"]) for agent in agents]
    default_team = _default_team(agent_ids)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "id": workforce_id,
        "type": "generated_workforce",
        "status": "draft",
        "harness_id": harness_id,
        "agents": agent_ids,
        "skills": skills,
        "default_team": default_team,
        "dispatch_policy": {
            "mode": "on_demand",
            "auto_dispatch_on_install": False,
        },
    }


def build_agent_payloads(plan: dict[str, Any], workforce: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    project = plan.get("project", {}) if isinstance(plan.get("project"), dict) else {}
    validation = plan.get("validation", {}) if isinstance(plan.get("validation"), dict) else {}
    policy = plan.get("policy", {}) if isinstance(plan.get("policy"), dict) else {}
    domains = [str(item).lower() for item in project.get("domains", []) if item]
    language = str(project.get("language") or "custom").lower()
    test_framework = str(project.get("test_framework") or "").lower()
    important_paths = [str(item) for item in plan.get("important_paths", []) if item]
    forbidden = [str(item) for item in policy.get("forbidden", []) if item]
    test_commands = [str(item) for item in validation.get("test_commands", []) if item]
    harness_id = str(plan.get("harness_id") or "custom-harness")
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
    if "auth" in domains:
        agents.append(
            {
                **base,
                "id": "auth-flow-investigator",
                "role": "인증 흐름과 토큰 검증 경로를 분석한다.",
                "responsibilities": ["인증 실패 재현 조건을 정리한다.", "수정 후보를 제안한다.", "관련 테스트 영향을 확인한다."],
            }
        )
    else:
        agents.append(
            {
                **base,
                "id": "root-cause-investigator",
                "role": "버그 원인 후보와 수정 방향을 분석한다.",
                "responsibilities": ["문제 재현 조건을 정리한다.", "수정 후보를 제안한다.", "관련 파일 영향을 확인한다."],
            }
        )
    if test_framework == "jest" or any("jest" in command for command in test_commands):
        agents.append(
            {
                **base,
                "id": "jest-regression-guardian",
                "role": "Jest 테스트와 회귀 가능성을 검토한다.",
                "responsibilities": ["관련 Jest 테스트를 식별한다.", "회귀 위험을 설명한다."],
                "test_commands": test_commands or ["npm test"],
            }
        )
    elif test_framework == "pytest" or any("pytest" in command for command in test_commands):
        agents.append(
            {
                **base,
                "id": "pytest-regression-guardian",
                "role": "pytest 테스트와 회귀 가능성을 검토한다.",
                "responsibilities": ["관련 pytest 테스트를 식별한다.", "회귀 위험을 설명한다."],
                "test_commands": test_commands or ["python -m pytest"],
            }
        )
    else:
        agents.append(
            {
                **base,
                "id": "test-regression-guardian",
                "role": "프로젝트 테스트 명령과 회귀 가능성을 검토한다.",
                "responsibilities": ["검증 명령을 확인한다.", "회귀 위험을 설명한다."],
                "test_commands": test_commands,
            }
        )
    if "api" in domains:
        agents.append(
            {
                **base,
                "id": "api-contract-reviewer",
                "role": "API 응답 형식과 실패 케이스를 검토한다.",
                "responsibilities": ["API 계약 변경 위험을 검토한다.", "인증 실패 응답의 부작용을 확인한다."],
            }
        )
    if language in {"typescript", "javascript"} and "api" not in domains:
        agents.append(
            {
                **base,
                "id": "typescript-code-reviewer",
                "role": "TypeScript 타입과 런타임 부작용을 검토한다.",
                "responsibilities": ["타입 안정성 위험을 확인한다.", "런타임 부작용을 설명한다."],
            }
        )
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
        if len(deduped) >= 5:
            break
    return deduped


def install_generated_workforce(project_root: Path, plan: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[Path]]:
    root = Path(project_root).resolve()
    workforce = build_workforce_payload(plan)
    agents = build_agent_payloads(plan, workforce)
    workforce["agents"] = [str(agent["id"]) for agent in agents]
    workforce["default_team"] = _default_team(workforce["agents"])
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
    if any(token in request_lower for token in ["auth", "login", "token", "bearer", "session", "인증", "로그인", "세션", "토큰"]):
        _append_if_available(selected, available, "auth-flow-investigator")
    if not selected:
        for item in workforce.get("default_team", []):
            _append_if_available(selected, available, str(item))
            if selected:
                break
    _append_if_available(selected, available, "jest-regression-guardian")
    _append_if_available(selected, available, "pytest-regression-guardian")
    _append_if_available(selected, available, "test-regression-guardian")
    _append_if_available(selected, available, "risk-reviewer")
    return selected[:3], "Selected from generated workforce by request domain and validation needs.", workforce


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


def _default_team(agent_ids: list[str]) -> list[str]:
    preferred = [
        "auth-flow-investigator",
        "root-cause-investigator",
        "jest-regression-guardian",
        "pytest-regression-guardian",
        "test-regression-guardian",
        "risk-reviewer",
    ]
    team: list[str] = []
    for agent_id in preferred:
        if agent_id in agent_ids and agent_id not in team:
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
