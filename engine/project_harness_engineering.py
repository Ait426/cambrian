from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_harness_profile import ProjectHarnessProfileStore, ProjectHarnessScanner, default_project_profile_path
from engine.project_pack_install import SCHEMA_VERSION, _relative, _slug


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


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


def default_engineering_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "engineering"


def default_design_candidate_path(project_root: Path) -> Path:
    return default_engineering_dir(project_root) / "design_candidate.yaml"


def default_review_report_path(project_root: Path) -> Path:
    return default_engineering_dir(project_root) / "review.yaml"


def default_dry_run_path(project_root: Path) -> Path:
    return default_engineering_dir(project_root) / "dry_run.yaml"


@dataclass
class HarnessEngineeringDesignResult:
    schema_version: str
    generated_at: str
    status: str
    design_id: str | None
    harness_id: str | None
    quality_score: int
    confidence: str
    generated_files_preview: list[str]
    design_ref: str | None
    next_command: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "candidate"
        return payload


@dataclass
class HarnessQualityReport:
    schema_version: str
    generated_at: str
    status: str
    quality_score: int
    warnings: list[str]
    blocking_issues: list[str]
    followup_questions: list[dict[str, Any]]
    review_ref: str | None
    next_command: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "ready_for_dry_run"
        return payload


@dataclass
class HarnessDryRunResult:
    schema_version: str
    generated_at: str
    status: str
    dry_run: bool
    request: str
    selected_agents: list[str]
    selected_skills: list[str]
    dispatch_reason: str
    expected_outputs: list[str]
    quality_score: int
    dry_run_ref: str | None
    next_command: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "ready_for_install"
        return payload


def design_harness_candidate(project_root: Path, seed_preset: str | None = None) -> HarnessEngineeringDesignResult:
    """프로젝트 profile과 인터뷰 답변으로 설치 전 설계 후보를 생성한다."""
    root = Path(project_root).resolve()
    try:
        profile = _load_or_scan_profile(root)
        answers = _load_answers(root)
    except (FileNotFoundError, ValueError) as exc:
        return HarnessEngineeringDesignResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            design_id=None,
            harness_id=None,
            quality_score=0,
            confidence="none",
            generated_files_preview=[],
            design_ref=None,
            next_command="cambrian harness interview start --json",
            errors=[str(exc)],
        )
    candidate = _candidate_from_inputs(root, profile, answers, seed_preset)
    saved = _save_yaml(default_design_candidate_path(root), candidate)
    return HarnessEngineeringDesignResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="candidate",
        design_id=str(candidate.get("design_id")),
        harness_id=str(candidate.get("harness", {}).get("id")),
        quality_score=int(candidate.get("quality_score") or 0),
        confidence=str(candidate.get("confidence") or "low"),
        generated_files_preview=list(candidate.get("generated_files_preview", [])),
        design_ref=_relative(saved, root),
        next_command="cambrian harness engineer review --json",
        warnings=list(candidate.get("warnings", [])),
        errors=[],
    )


def review_harness_candidate(project_root: Path) -> HarnessQualityReport:
    """설계 후보가 설치 가능한 품질인지 검수한다."""
    root = Path(project_root).resolve()
    path = default_design_candidate_path(root)
    if not path.exists():
        return HarnessQualityReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="needs_more_info",
            quality_score=0,
            warnings=[],
            blocking_issues=["design_candidate.yaml is missing"],
            followup_questions=[{"id": "design", "question": "먼저 cambrian harness engineer design --json을 실행하세요."}],
            review_ref=None,
            next_command="cambrian harness engineer design --json",
        )
    candidate = _load_yaml(path)
    blocking, followups = _blocking_issues(candidate)
    warnings = _warnings(candidate)
    quality_score = int(candidate.get("quality_score") or 0)
    if quality_score < 50 and "quality_score is below 50" not in blocking:
        blocking.append("quality_score is below 50")
    if blocking:
        status = "needs_more_info"
        next_command = "cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json"
    elif quality_score < 70:
        status = "needs_review"
        warnings.append("quality_score is below install threshold 70")
        next_command = "cambrian harness engineer design --json"
    else:
        status = "ready_for_dry_run"
        next_command = 'cambrian harness engineer dry-run "로그인 문제 봐줘" --json'
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "status": status,
        "quality_score": quality_score,
        "warnings": warnings,
        "blocking_issues": blocking,
        "followup_questions": followups,
        "next_command": next_command,
    }
    saved = _save_yaml(default_review_report_path(root), report)
    return HarnessQualityReport(
        schema_version=SCHEMA_VERSION,
        generated_at=str(report["generated_at"]),
        status=status,
        quality_score=quality_score,
        warnings=warnings,
        blocking_issues=blocking,
        followup_questions=followups,
        review_ref=_relative(saved, root),
        next_command=next_command,
    )


def dry_run_harness_candidate(project_root: Path, request: str) -> HarnessDryRunResult:
    """설계 후보 기준으로 agent/skill 투입 계획을 시뮬레이션한다."""
    root = Path(project_root).resolve()
    candidate_path = default_design_candidate_path(root)
    review_path = default_review_report_path(root)
    if not candidate_path.exists():
        return _blocked_dry_run("design_candidate.yaml is missing", "cambrian harness engineer design --json")
    if not review_path.exists():
        return _blocked_dry_run("engineering review is required before dry-run", "cambrian harness engineer review --json")
    candidate = _load_yaml(candidate_path)
    review = _load_yaml(review_path)
    if str(review.get("status") or "") != "ready_for_dry_run":
        return _blocked_dry_run("engineering review is not ready for dry-run", "cambrian harness engineer review --json")
    request_text = str(request or "").strip()
    if not request_text:
        return _blocked_dry_run("request is required", 'cambrian harness engineer dry-run "로그인 문제 봐줘" --json')
    selected_agents = _select_agents(candidate, request_text)
    selected_skills = _select_skills(candidate, selected_agents, request_text)
    expected_outputs = _expected_outputs(candidate, selected_skills)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "status": "ready_for_install",
        "dry_run": True,
        "request": request_text,
        "selected_agents": selected_agents,
        "selected_skills": selected_skills,
        "dispatch_reason": "Auth-related request with validation requirement." if _looks_auth_request(request_text) else "Selected by candidate default team and validation needs.",
        "expected_outputs": expected_outputs,
        "quality_score": int(candidate.get("quality_score") or 0),
        "next_command": "cambrian harness install --confirm --json",
        "job_created": False,
    }
    saved = _save_yaml(default_dry_run_path(root), payload)
    return HarnessDryRunResult(
        schema_version=SCHEMA_VERSION,
        generated_at=str(payload["generated_at"]),
        status="ready_for_install",
        dry_run=True,
        request=request_text,
        selected_agents=selected_agents,
        selected_skills=selected_skills,
        dispatch_reason=str(payload["dispatch_reason"]),
        expected_outputs=expected_outputs,
        quality_score=int(payload["quality_score"]),
        dry_run_ref=_relative(saved, root),
        next_command="cambrian harness install --confirm --json",
    )


def engineering_gate_status(project_root: Path) -> dict[str, Any]:
    """설치 전 engineering gate 통과 여부를 반환한다."""
    root = Path(project_root).resolve()
    candidate_path = default_design_candidate_path(root)
    review_path = default_review_report_path(root)
    dry_run_path = default_dry_run_path(root)
    errors: list[str] = []
    candidate: dict[str, Any] = {}
    review: dict[str, Any] = {}
    dry_run: dict[str, Any] = {}
    if not candidate_path.exists():
        errors.append("design_candidate.yaml is missing")
    else:
        candidate = _load_yaml(candidate_path)
    if not review_path.exists():
        errors.append("engineering review is missing")
    else:
        review = _load_yaml(review_path)
    if not dry_run_path.exists():
        errors.append("engineering dry-run is missing")
    else:
        dry_run = _load_yaml(dry_run_path)
    quality_score = int(candidate.get("quality_score") or review.get("quality_score") or 0)
    blocking = review.get("blocking_issues", []) if isinstance(review.get("blocking_issues"), list) else []
    if quality_score < 70:
        errors.append("quality_score is below 70")
    if str(review.get("status") or "") != "ready_for_dry_run":
        errors.append("engineering review did not pass")
    if blocking:
        errors.extend([str(item) for item in blocking])
    if dry_run and str(dry_run.get("status") or "") != "ready_for_install":
        errors.append("engineering dry-run did not pass")
    return {
        "ok": not errors,
        "error": None if not errors else "engineering_gate_not_passed",
        "message": "Run harness engineer review and dry-run before install." if errors else "Engineering gate passed.",
        "quality_score": quality_score,
        "blocking_issues": blocking,
        "errors": _dedupe(errors),
        "next_command": "cambrian harness engineer review --json" if errors else "cambrian harness install --confirm --json",
    }


def render_engineering_result(payload: dict[str, Any]) -> str:
    title = "Harness engineering"
    lines = [title, "", "Status:", f"  {payload.get('status') or 'unknown'}"]
    for key in ["design_id", "harness_id", "quality_score", "confidence", "dry_run", "request"]:
        if key in payload and payload.get(key) is not None:
            lines.extend(["", key.replace("_", " ").title() + ":", f"  {payload.get(key)}"])
    for label, key in [
        ("Selected agents", "selected_agents"),
        ("Selected skills", "selected_skills"),
        ("Expected outputs", "expected_outputs"),
        ("Warnings", "warnings"),
        ("Blocking issues", "blocking_issues"),
        ("Errors", "errors"),
    ]:
        values = payload.get(key)
        if isinstance(values, list) and values:
            lines.extend(["", f"{label}:"])
            lines.extend([f"  - {item}" for item in values])
    if payload.get("next_command"):
        lines.extend(["", "Next:", f"  {payload.get('next_command')}"])
    return "\n".join(lines)


def _candidate_from_inputs(root: Path, profile: Any, answers: dict[str, Any], seed_preset: str | None) -> dict[str, Any]:
    profile_payload = profile.to_dict()
    harness_id = _harness_id(root, profile_payload, answers)
    forbidden = _as_string_list(answers.get("forbidden_scope"))
    important_paths = _as_string_list(answers.get("important_paths")) or _profile_important_paths(profile_payload)
    test_commands = _as_string_list(answers.get("test_command"))
    build_commands = _as_string_list(answers.get("build_command"))
    success_criteria = _as_string_list(answers.get("validation_standard"))
    agents = _agent_candidates(profile_payload)
    skills = _skill_candidates(profile_payload, harness_id, agents, important_paths, forbidden, test_commands)
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "design_id": f"harness-design-{_slug(root.name, 'project')}-{_date_stamp()}",
        "status": "candidate",
        "seed_preset": seed_preset,
        "project_profile": {
            "language": profile_payload.get("language"),
            "test_framework": profile_payload.get("test_framework"),
            "domains": list(profile_payload.get("domains", [])),
        },
        "harness": {
            "id": harness_id,
            "type": "custom",
            "status": "candidate",
            "goal": str(answers.get("primary_goal") or "").strip(),
            "language": profile_payload.get("language") or "unknown",
            "test_framework": profile_payload.get("test_framework") or "unknown",
            "important_paths": important_paths,
            "forbidden": forbidden,
            "change_policy": str(answers.get("change_policy") or "").strip(),
            "policy": {
                "auto_apply": False,
                "source_mutation": False,
            },
        },
        "workforce": {
            "agents": agents,
        },
        "skills": skills,
        "validation": {
            "test_commands": test_commands,
            "build_commands": build_commands,
            "success_criteria": success_criteria,
        },
        "generated_files_preview": [
            ".cambrian/harness.yaml",
            ".cambrian/workforce.yaml",
            ".cambrian/agents/*.yaml",
            ".cambrian/skills/*.yaml",
            ".cambrian/validation.yaml",
        ],
        "warnings": [],
        "errors": [],
        "next_command": "cambrian harness engineer review --json",
    }
    score = quality_score(candidate)
    candidate["quality_score"] = score
    candidate["confidence"] = _confidence(score)
    return candidate


def quality_score(candidate: dict[str, Any]) -> int:
    harness = candidate.get("harness", {}) if isinstance(candidate.get("harness"), dict) else {}
    validation = candidate.get("validation", {}) if isinstance(candidate.get("validation"), dict) else {}
    agents = candidate.get("workforce", {}).get("agents", []) if isinstance(candidate.get("workforce"), dict) else []
    skills = candidate.get("skills", [])
    score = 0
    if str(harness.get("goal") or "").strip():
        score += 15
    if _as_string_list(validation.get("test_commands")):
        score += 15
    if _as_string_list(harness.get("important_paths")):
        score += 10
    if _as_string_list(harness.get("forbidden")):
        score += 10
    if str(harness.get("change_policy") or "").strip() in {"proposal_only", "manual_confirm"}:
        score += 10
    agent_ids = [str(agent.get("id")) for agent in agents if isinstance(agent, dict) and agent.get("id")]
    if 3 <= len(agent_ids) <= 5:
        score += 10
    if agent_ids and _all_agents_have_skills(agent_ids, skills):
        score += 10
    if skills and all(_as_string_list(skill.get("procedure")) for skill in skills if isinstance(skill, dict)):
        score += 10
    if _as_string_list(validation.get("success_criteria")):
        score += 10
    return min(score, 100)


def _load_or_scan_profile(root: Path) -> Any:
    profile_path = default_project_profile_path(root)
    if profile_path.exists():
        return ProjectHarnessProfileStore().load(profile_path)
    profile = ProjectHarnessScanner().scan(root)
    ProjectHarnessProfileStore().save(profile, profile_path)
    return profile


def _load_answers(root: Path) -> dict[str, Any]:
    path = root / ".cambrian" / "interview" / "answers.yaml"
    if not path.exists():
        raise FileNotFoundError("interview answers are missing")
    payload = _load_yaml(path)
    answers = payload.get("answers", {})
    if not isinstance(answers, dict):
        raise ValueError("answers.yaml must contain an answers mapping")
    return answers


def _harness_id(root: Path, profile: dict[str, Any], answers: dict[str, Any]) -> str:
    base = _slug(root.name, "project")
    goal = str(answers.get("primary_goal") or "").lower()
    domains = [str(item).lower() for item in profile.get("domains", []) if item]
    suffixes: list[str] = []
    if "auth" in domains or "auth" in goal or "login" in goal or "인증" in goal:
        suffixes.append("auth")
    if "reservation" in goal or "booking" in goal or "예약" in goal:
        suffixes.append("reservation")
    if not suffixes:
        suffixes = domains[:2] or ["work"]
    return f"custom-{base}-{'-'.join(_slug(item, 'work') for item in suffixes)}"


def _agent_candidates(profile: dict[str, Any]) -> list[dict[str, str]]:
    domains = [str(item).lower() for item in profile.get("domains", []) if item]
    test_framework = str(profile.get("test_framework") or "").lower()
    agents: list[dict[str, str]] = []
    if "auth" in domains:
        agents.append({"id": "auth-flow-investigator", "role": "인증 흐름과 토큰 검증 경로를 분석한다."})
    else:
        agents.append({"id": "root-cause-investigator", "role": "문제 재현 조건과 원인 후보를 분석한다."})
    if test_framework == "jest":
        agents.append({"id": "regression-test-guardian", "role": "Jest 테스트와 회귀 가능성을 검토한다."})
    elif test_framework == "pytest":
        agents.append({"id": "regression-test-guardian", "role": "pytest 테스트와 회귀 가능성을 검토한다."})
    else:
        agents.append({"id": "regression-test-guardian", "role": "프로젝트 테스트 명령과 회귀 가능성을 검토한다."})
    if "api" in domains:
        agents.append({"id": "api-contract-reviewer", "role": "API 응답 형식과 실패 케이스를 검토한다."})
    agents.append({"id": "risk-reviewer", "role": "수정 제안의 부작용과 운영 리스크를 검토한다."})
    return agents[:5]


def _skill_candidates(
    profile: dict[str, Any],
    harness_id: str,
    agents: list[dict[str, str]],
    important_paths: list[str],
    forbidden: list[str],
    test_commands: list[str],
) -> list[dict[str, Any]]:
    agent_ids = {agent["id"] for agent in agents}
    domains = [str(item).lower() for item in profile.get("domains", []) if item]
    skills: list[dict[str, Any]] = []
    if "auth-flow-investigator" in agent_ids:
        skills.append(
            _skill(
                "trace-auth-flow",
                harness_id,
                ["auth-flow-investigator"],
                "인증 요청, 토큰, 미들웨어 경로를 추적한다.",
                ["요청에서 인증 실패 조건을 추출한다.", "중요 경로와 테스트를 연결한다.", "원인 후보와 evidence를 정리한다."],
                ["root cause hypothesis", "evidence notes"],
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
                "실패 재현 경로와 원인 후보를 추적한다.",
                ["요청에서 실패 조건을 추출한다.", "중요 경로와 테스트를 연결한다.", "원인 후보와 evidence를 정리한다."],
                ["root cause hypothesis", "evidence notes"],
                forbidden,
                important_paths,
            )
        )
    skills.append(
        _skill(
            "inspect-test-failure",
            harness_id,
            ["regression-test-guardian"],
            "테스트 실패 조건과 회귀 위험을 분석한다.",
            ["테스트 명령 후보를 확인한다.", "관련 테스트 파일을 확인한다.", "회귀 위험을 정리한다."],
            ["test impact notes", "regression suggestions"],
            forbidden,
            test_commands,
        )
    )
    skills.append(
        _skill(
            "propose-safe-patch",
            harness_id,
            ["auth-flow-investigator" if "auth-flow-investigator" in agent_ids else "root-cause-investigator", "risk-reviewer"],
            "자동 적용 없이 안전한 patch proposal을 만든다.",
            ["수정 범위를 좁힌다.", "old_text/new_text 기반 제안을 만든다.", "금지 범위를 위반하지 않는지 확인한다."],
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
            ["부작용 가능성을 분류한다.", "사람이 적용 전 확인할 항목을 정리한다."],
            ["risk notes", "manual review checklist"],
            forbidden,
            test_commands,
        )
    )
    if "api" in domains and "api-contract-reviewer" in agent_ids:
        skills.append(
            _skill(
                "review-api-contract",
                harness_id,
                ["api-contract-reviewer"],
                "API 응답 형식과 인증 실패 케이스 계약을 검토한다.",
                ["응답 코드와 메시지 변경 가능성을 확인한다.", "클라이언트 영향 범위를 정리한다."],
                ["api contract notes", "compatibility risks"],
                forbidden,
                important_paths,
            )
        )
    return skills


def _skill(
    skill_id: str,
    harness_id: str,
    assigned_agents: list[str],
    purpose: str,
    procedure: list[str],
    outputs: list[str],
    forbidden: list[str],
    inputs: list[str],
) -> dict[str, Any]:
    return {
        "id": skill_id,
        "type": "generated_skill",
        "status": "candidate",
        "harness_id": harness_id,
        "assigned_agents": assigned_agents,
        "purpose": purpose,
        "procedure": procedure,
        "inputs": ["사용자 작업 요청", "project profile", *inputs],
        "outputs": outputs,
        "forbidden": forbidden,
        "validation": {"required": ["관련 테스트 영향 설명", "회귀 위험 설명"]},
    }


def _blocking_issues(candidate: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    harness = candidate.get("harness", {}) if isinstance(candidate.get("harness"), dict) else {}
    validation = candidate.get("validation", {}) if isinstance(candidate.get("validation"), dict) else {}
    issues: list[str] = []
    questions: list[dict[str, str]] = []
    if not str(harness.get("goal") or "").strip():
        issues.append("primary_goal is missing")
        questions.append({"id": "primary_goal", "question": "이 프로젝트에서 Cambrian이 주로 맡아야 할 작업은 무엇인가요?"})
    if not _as_string_list(validation.get("test_commands")):
        issues.append("test_command is missing")
        questions.append({"id": "test_command", "question": "이 프로젝트의 실제 테스트 명령은 무엇인가요?"})
    if not str(harness.get("change_policy") or "").strip():
        issues.append("change_policy is missing")
        questions.append({"id": "change_policy", "question": "Cambrian은 제안까지만 해야 하나요, 수동 승인 후 적용까지 허용하나요?"})
    if str(harness.get("policy", {}).get("auto_apply") if isinstance(harness.get("policy"), dict) else "") == "True":
        issues.append("auto_apply must be false")
    agents = candidate.get("workforce", {}).get("agents", []) if isinstance(candidate.get("workforce"), dict) else []
    if not 3 <= len([item for item in agents if isinstance(item, dict)]) <= 5:
        issues.append("agent count must be between 3 and 5")
    skills = candidate.get("skills", [])
    agent_ids = [str(agent.get("id")) for agent in agents if isinstance(agent, dict) and agent.get("id")]
    if agent_ids and not _all_agents_have_skills(agent_ids, skills):
        issues.append("every agent must have at least one skill")
    if any(not _as_string_list(skill.get("procedure")) for skill in skills if isinstance(skill, dict)):
        issues.append("every skill must include procedure")
    if not _as_string_list(validation.get("success_criteria")):
        issues.append("validation success criteria is missing")
    return issues, questions


def _warnings(candidate: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    harness = candidate.get("harness", {}) if isinstance(candidate.get("harness"), dict) else {}
    validation = candidate.get("validation", {}) if isinstance(candidate.get("validation"), dict) else {}
    if not _as_string_list(validation.get("build_commands")):
        warnings.append("build_command is missing")
    if not _as_string_list(harness.get("important_paths")):
        warnings.append("important_paths is missing")
    if not _as_string_list(harness.get("forbidden")):
        warnings.append("forbidden_scope is missing")
    return warnings


def _blocked_dry_run(error: str, next_command: str) -> HarnessDryRunResult:
    return HarnessDryRunResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="blocked",
        dry_run=True,
        request="",
        selected_agents=[],
        selected_skills=[],
        dispatch_reason="",
        expected_outputs=[],
        quality_score=0,
        dry_run_ref=None,
        next_command=next_command,
        errors=[error],
    )


def _select_agents(candidate: dict[str, Any], request: str) -> list[str]:
    agents = candidate.get("workforce", {}).get("agents", []) if isinstance(candidate.get("workforce"), dict) else []
    available = [str(agent.get("id")) for agent in agents if isinstance(agent, dict) and agent.get("id")]
    selected: list[str] = []
    if _looks_auth_request(request) and "auth-flow-investigator" in available:
        selected.append("auth-flow-investigator")
    for agent_id in ["regression-test-guardian", "risk-reviewer"]:
        if agent_id in available and agent_id not in selected:
            selected.append(agent_id)
    if not selected:
        selected = available[:3]
    return selected[:3]


def _select_skills(candidate: dict[str, Any], selected_agents: list[str], request: str) -> list[str]:
    skills = candidate.get("skills", [])
    selected: list[str] = []
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        skill_id = str(skill.get("id") or "")
        assigned = [str(item) for item in skill.get("assigned_agents", []) if item]
        if skill_id and any(agent in selected_agents for agent in assigned):
            selected.append(skill_id)
    if _looks_auth_request(request):
        for preferred in ["trace-auth-flow", "inspect-test-failure", "propose-safe-patch", "review-regression-risk"]:
            if any(str(skill.get("id")) == preferred for skill in skills if isinstance(skill, dict)) and preferred not in selected:
                selected.append(preferred)
    return selected[:5]


def _expected_outputs(candidate: dict[str, Any], selected_skills: list[str]) -> list[str]:
    outputs: list[str] = []
    skills = candidate.get("skills", [])
    for skill in skills:
        if isinstance(skill, dict) and str(skill.get("id")) in selected_skills:
            outputs.extend(_as_string_list(skill.get("outputs")))
    return _dedupe(outputs)


def _profile_important_paths(profile: dict[str, Any]) -> list[str]:
    paths = profile.get("detected_paths", {}) if isinstance(profile.get("detected_paths"), dict) else {}
    selected: list[str] = []
    for key in ["auth", "login", "tests"]:
        selected.extend(_as_string_list(paths.get(key)))
    return _dedupe(selected)[:8]


def _all_agents_have_skills(agent_ids: list[str], skills: Any) -> bool:
    mapping: dict[str, int] = {agent_id: 0 for agent_id in agent_ids}
    for skill in skills if isinstance(skills, list) else []:
        if not isinstance(skill, dict):
            continue
        for agent_id in _as_string_list(skill.get("assigned_agents")):
            if agent_id in mapping:
                mapping[agent_id] += 1
    return all(count > 0 for count in mapping.values())


def _looks_auth_request(request: str) -> bool:
    text = str(request or "").lower()
    return any(token in text for token in ["auth", "login", "token", "bearer", "session", "인증", "로그인", "세션", "토큰"])


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [text]


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _confidence(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 70:
        return "medium"
    if score >= 50:
        return "low"
    return "insufficient"
