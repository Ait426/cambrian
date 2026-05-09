from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "draft"
        return payload


def build_skillset(project_root: Path, seed_preset: str | None = None) -> SkillGenerateResult:
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
    )


def build_skill_payloads(plan: dict[str, Any], workforce: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    project = plan.get("project", {}) if isinstance(plan.get("project"), dict) else {}
    validation = plan.get("validation", {}) if isinstance(plan.get("validation"), dict) else {}
    policy = plan.get("policy", {}) if isinstance(plan.get("policy"), dict) else {}
    domains = [str(item).lower() for item in project.get("domains", []) if item]
    test_framework = str(project.get("test_framework") or "").lower()
    test_commands = [str(item) for item in validation.get("test_commands", []) if item]
    forbidden = [str(item) for item in policy.get("forbidden", []) if item]
    important_paths = [str(item) for item in plan.get("important_paths", []) if item]
    harness_id = str(plan.get("harness_id") or "custom-harness")
    skills: list[dict[str, Any]] = []
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
                ["root-cause-investigator"],
                "문제 재현 경로와 실패 흐름을 추적한다.",
                ["버그 재현", "실패 흐름 분석"],
                ["요청에서 실패 조건을 추출한다.", "관련 경로를 확인한다.", "테스트와 연결되는 실패 조건을 정리한다."],
                ["root cause hypothesis", "evidence notes"],
                forbidden,
                important_paths,
            )
        )
    if test_framework == "jest" or any("jest" in command.lower() for command in test_commands):
        skills.append(
            _skill(
                "inspect-jest-auth-test",
                harness_id,
                ["jest-regression-guardian"],
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
                "inspect-pytest-auth-test",
                harness_id,
                ["pytest-regression-guardian"],
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
            ["auth-flow-investigator", "root-cause-investigator", "risk-reviewer"],
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
            ["risk-reviewer"],
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
    return deduped[:6]


def install_generated_skills(project_root: Path, plan: dict[str, Any], workforce: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[Path]]:
    root = Path(project_root).resolve()
    skills = build_skill_payloads(plan, workforce)
    skills_dir = default_generated_skills_dir(root)
    if skills_dir.exists():
        for old in skills_dir.glob("*.yaml"):
            old.unlink()
    files: list[Path] = []
    for skill in skills:
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
    return {
        "schema_version": SCHEMA_VERSION,
        "id": skill_id,
        "type": "generated_skill",
        "status": "draft",
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
