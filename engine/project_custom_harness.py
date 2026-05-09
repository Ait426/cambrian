from __future__ import annotations

import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_harness_interview import (
    HarnessInterviewStore,
    REQUIRED_ANSWER_IDS,
    default_interview_answers_path,
    default_interview_questions_path,
)
from engine.project_harness_profile import ProjectHarnessProfileStore, ProjectHarnessScanner, default_project_profile_path
from engine.project_pack_install import SCHEMA_VERSION, _as_list, _now, _relative, _slug, _stamp


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


def default_root_profile_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "profile.yaml"


def default_custom_harness_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "harness.yaml"


def default_custom_agents_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "agents.yaml"


def default_custom_validation_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "validation.yaml"


def default_custom_plan_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "plan.yaml"


def default_custom_jobs_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "packs" / "jobs"


def default_custom_job_path(project_root: Path, job_id: str) -> Path:
    return default_custom_jobs_dir(project_root) / f"{_slug(job_id, 'job')}.yaml"


@dataclass
class CustomHarnessInstallResult:
    schema_version: str
    generated_at: str
    status: str
    harness_id: str | None
    plan_type: str | None
    installed_files: list[str]
    next_commands: list[str]
    workforce_id: str | None = None
    generated_agents: list[str] = field(default_factory=list)
    generated_skills: list[str] = field(default_factory=list)
    authority_mode: str | None = None
    authority_ref: str | None = None
    no_agent_dispatched: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "installed"
        if self.status == "confirmation_required":
            payload["error"] = "confirmation_required"
            payload["message"] = "Review the harness plan before installing."
            payload["next_command"] = "cambrian harness install --confirm --json"
        return payload


def load_custom_harness(project_root: Path) -> dict[str, Any] | None:
    path = default_custom_harness_path(project_root)
    if not path.exists():
        return None
    payload = _load_yaml(path)
    if str(payload.get("type") or "") != "custom":
        return None
    return payload


def load_custom_agents(project_root: Path) -> list[dict[str, Any]]:
    try:
        from engine.project_workforce_builder import load_generated_agents

        generated = load_generated_agents(project_root)
        if generated:
            return generated
    except Exception:
        pass
    path = default_custom_agents_path(project_root)
    if not path.exists():
        return []
    payload = _load_yaml(path)
    agents = payload.get("agents", [])
    if not isinstance(agents, list):
        return []
    return [dict(item) for item in agents if isinstance(item, dict)]


def load_custom_validation(project_root: Path) -> dict[str, Any]:
    path = default_custom_validation_path(project_root)
    if not path.exists():
        return {}
    payload = _load_yaml(path)
    validation = payload.get("validation", payload)
    return dict(validation) if isinstance(validation, dict) else {}


def build_custom_harness_plan(project_root: Path, seed_preset: str | None = None) -> dict[str, Any] | None:
    root = Path(project_root).resolve()
    answers_payload = HarnessInterviewStore().load_answers(root)
    if answers_payload is None:
        return None
    answers = answers_payload.get("answers", {})
    if not isinstance(answers, dict):
        return None
    if _missing_required(answers):
        return None
    profile = _load_or_scan_profile(root)
    harness_id = _harness_id(root, answers, profile.to_dict())
    agent_specs = _agent_specs(answers)
    test_commands = _test_commands(answers)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "ok": True,
        "plan_type": "custom",
        "harness_id": harness_id,
        "selected_harness": harness_id,
        "status": "draft",
        "seed_preset": seed_preset,
        "project": {
            "name": profile.project_name,
            "language": profile.language,
            "test_framework": profile.test_framework,
            "domains": list(profile.domains),
        },
        "goal": str(answers.get("primary_goal") or "").strip(),
        "agents": agent_specs,
        "validation": {
            "mode": "command",
            "test_commands": test_commands,
            "policy": str(answers.get("change_policy") or "proposal_only").strip(),
            "success_criteria": _as_string_list(answers.get("validation_standard")) or ["관련 검증 기준 충족"],
        },
        "policy": {
            "change_mode": str(answers.get("change_policy") or "proposal_only").strip(),
            "auto_apply": False,
            "forbidden": _as_string_list(answers.get("forbidden_scope")),
            "allowed": _as_string_list(answers.get("allowed_scope")),
            "risk_level": str(answers.get("risk_level") or "").strip() or None,
        },
        "important_paths": _as_string_list(answers.get("important_paths")),
        "install_preview": [
            ".cambrian/profile.yaml",
            ".cambrian/harness.yaml",
            ".cambrian/workforce.yaml",
            ".cambrian/agents/*.yaml",
            ".cambrian/skills/*.yaml",
            ".cambrian/validation.yaml",
            ".cambrian/operating_rules.yaml",
            ".cambrian/interview/answers.yaml",
            ".cambrian/interview/questions.yaml",
            ".cambrian/plan.yaml",
        ],
        "next_command": "cambrian workforce generate --json",
        "next_commands": ["cambrian workforce generate --json", "cambrian harness install --confirm --json"],
        "warnings": _seed_warnings(seed_preset, profile.to_dict()),
        "errors": [],
    }
    return plan


def install_custom_harness(project_root: Path, confirm: bool, seed_preset: str | None = None) -> CustomHarnessInstallResult:
    root = Path(project_root).resolve()
    if not confirm:
        return CustomHarnessInstallResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="confirmation_required",
            harness_id=None,
            plan_type=None,
            installed_files=[],
            next_commands=["cambrian harness install --confirm --json"],
            no_agent_dispatched=True,
            errors=["Review the harness plan before installing."],
        )
    plan = build_custom_harness_plan(root, seed_preset=seed_preset)
    if plan is None:
        return CustomHarnessInstallResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            harness_id=None,
            plan_type=None,
            installed_files=[],
            next_commands=["cambrian harness interview start --json"],
            no_agent_dispatched=True,
            errors=["Custom harness plan is not ready. Complete the harness interview first."],
        )
    profile = _load_or_scan_profile(root).to_dict()
    harness_payload = _harness_payload(plan)
    from engine.project_skill_builder import install_generated_skills
    from engine.project_harness_engineering import (
        default_design_candidate_path,
        default_dry_run_path,
        default_review_report_path,
    )
    from engine.project_workforce_builder import install_generated_workforce

    authority_profile, authority_files = _ensure_authority_profile(root)
    workforce_payload, generated_agents, workforce_files = install_generated_workforce(root, plan)
    generated_skills, skill_mapping, skill_files = install_generated_skills(root, plan, workforce_payload)
    workforce_payload["skills"] = skill_mapping
    if workforce_files:
        _save_yaml(workforce_files[0], workforce_payload)
    agents_payload = {"schema_version": SCHEMA_VERSION, "agents": list(generated_agents)}
    validation_payload = {"schema_version": SCHEMA_VERSION, "validation": dict(plan.get("validation", {}))}
    files = [
        _save_yaml(default_root_profile_path(root), profile),
        _save_yaml(default_custom_harness_path(root), harness_payload),
        _save_yaml(default_custom_agents_path(root), agents_payload),
        _save_yaml(default_custom_validation_path(root), validation_payload),
        _save_yaml(default_custom_plan_path(root), plan),
    ]
    files.extend(workforce_files)
    files.extend(skill_files)
    answers_path = default_interview_answers_path(root)
    questions_path = default_interview_questions_path(root)
    if answers_path.exists():
        files.append(answers_path)
    if questions_path.exists():
        files.append(questions_path)
    for engineering_path in [
        default_design_candidate_path(root),
        default_review_report_path(root),
        default_dry_run_path(root),
    ]:
        if engineering_path.exists():
            files.append(engineering_path)
    files.extend(authority_files)
    return CustomHarnessInstallResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="installed",
        harness_id=str(plan.get("harness_id")),
        plan_type="custom",
        installed_files=[_relative(path, root) for path in files],
        next_commands=['cambrian job start "원하는 작업을 입력하세요"'],
        workforce_id=str(workforce_payload.get("id") or ""),
        generated_agents=[str(agent.get("id")) for agent in generated_agents if agent.get("id")],
        generated_skills=[str(skill.get("id")) for skill in generated_skills if skill.get("id")],
        authority_mode=str(authority_profile.get("mode") or "proposal_only"),
        authority_ref=_relative(authority_files[0], root) if authority_files else ".cambrian/authority.yaml",
        no_agent_dispatched=True,
        warnings=list(plan.get("warnings", [])),
        errors=[],
    )


def create_custom_harness_job(
    project_root: Path,
    request: str,
    selected_agent_id: str | None = None,
    entry_mode: str = "job_start",
) -> tuple[dict[str, Any], dict[str, Any]]:
    from engine.project_bridge import ProjectBridgeBuilder, ProjectBridgeStore, default_bridge_packet_path, render_bridge_packet

    root = Path(project_root).resolve()
    harness = load_custom_harness(root)
    if harness is None:
        raise FileNotFoundError("custom harness is not installed")
    validation = load_custom_validation(root)
    request_text = str(request or "").strip()
    if not request_text:
        raise ValueError("request is required")
    harness_id = str(harness.get("id") or "custom-harness")
    from engine.project_skill_builder import select_skills_for_agents
    from engine.project_workforce_builder import select_agents_for_request

    selected_agents, dispatch_reason, workforce = select_agents_for_request(root, request_text, explicit_agent_id=selected_agent_id)
    if selected_agent_id and not selected_agents:
        raise ValueError(dispatch_reason or f"Requested agent {selected_agent_id} is not installed.")
    if not selected_agents:
        agents = load_custom_agents(root)
        selected_agents = [str(item.get("id")) for item in agents if isinstance(item, dict) and item.get("id")][:3]
        if not dispatch_reason:
            dispatch_reason = "Selected from installed harness agents."
    selected_skills = select_skills_for_agents(root, selected_agents, request_text)
    job_id = f"job-{_slug(harness_id, 'custom-harness')}-{_stamp()}"
    lane_id = f"{harness.get('language')}-{harness.get('test_framework')}"
    bridge_context = {
        "pack_id": harness_id,
        "pack_ref": harness_id,
        "harness_id": harness_id,
        "workforce_id": str(workforce.get("id")) if isinstance(workforce, dict) and workforce.get("id") else None,
        "selected_agents": list(selected_agents),
        "selected_skills": list(selected_skills),
        "dispatch_reason": dispatch_reason,
        "change_policy": str(harness.get("policy", {}).get("change_mode") or "proposal_only"),
        "validation_commands": list(validation.get("test_commands", []) if isinstance(validation.get("test_commands"), list) else []),
        "namespace": "custom",
        "version": None,
        "lane_id": lane_id,
        "lane_label": _lane_label(harness),
        "team": "custom-harness",
        "template": "custom-harness",
        "active_pack_id": harness_id,
        "active_pack_ref": harness_id,
        "active_pack_namespace": "custom",
        "active_pack_version": None,
        "active_pack_lane": lane_id,
        "custom_harness": True,
        "pack_job_id": job_id,
        "pack_job_ref": f".cambrian/packs/jobs/{job_id}.yaml",
    }
    packet = ProjectBridgeBuilder().build_packet(root, request_text, active_pack_context_override=bridge_context)
    packet_path = ProjectBridgeStore().save_packet(packet, default_bridge_packet_path(root, packet))
    next_commands = [
        "cambrian job ingest latest ai_reply_patch_candidate.yaml",
        "cambrian job validate latest",
    ]
    job = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "created_at": _now(),
        "updated_at": None,
        "pack_ref": harness_id,
        "pack_id": harness_id,
        "pack_name": str(harness.get("id") or harness_id),
        "pack_kind": "custom_harness",
        "namespace": "custom",
        "version": None,
        "request": request_text,
        "request_class": packet.request_intent,
        "lane_id": f"{harness.get('language')}-{harness.get('test_framework')}",
        "lane_label": _lane_label(harness),
        "readiness_status": "ready",
        "readiness_ref": None,
        "setup_plan_ref": _relative(default_custom_plan_path(root), root) if default_custom_plan_path(root).exists() else None,
        "entry_mode": entry_mode,
        "linked_bridge_packet_ref": _relative(packet_path, root),
        "linked_session_id": None,
        "linked_session_ref": None,
        "linked_request_ref": None,
        "active_team": None,
        "active_template": None,
        "active_workset": None,
        "status": "waiting_for_ai_reply",
        "next_command": next_commands[0],
        "next_actions": ["Copy the request to your AI tool.", *next_commands],
        "usage_event_ref": None,
        "outcome_snapshot": {
            "harness_id": harness_id,
            "workforce_id": str(workforce.get("id")) if isinstance(workforce, dict) and workforce.get("id") else None,
            "selected_agents": list(selected_agents),
            "selected_skills": list(selected_skills),
            "dispatch_reason": dispatch_reason,
            "change_policy": str(harness.get("policy", {}).get("change_mode") or "proposal_only"),
            "validation_commands": list(validation.get("test_commands", []) if isinstance(validation.get("test_commands"), list) else []),
        },
        "warnings": [],
        "errors": [],
    }
    job_path = _save_custom_job(root, job)
    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "job": job,
        "human_summary": [
            f"custom harness job started for {harness_id}",
            "AI provider was not called.",
            "Source code was not modified.",
        ],
        "packet_preview": render_bridge_packet(packet),
        "next_actions": list(job["next_actions"]),
        "warnings": [],
        "errors": [],
    }
    payload = {
        "job": dict(job),
        "job_ref": _relative(job_path, root),
        "packet_ref": _relative(packet_path, root),
        "packet_preview": result["packet_preview"],
    }
    return result, payload


def _save_custom_job(root: Path, job: dict[str, Any]) -> Path:
    job_id = str(job.get("job_id") or "job-custom")
    job_path = default_custom_job_path(root, job_id)
    _save_yaml(job_path, job)
    _save_yaml(default_custom_jobs_dir(root) / "latest.yaml", job)
    return job_path


def _load_or_scan_profile(root: Path) -> Any:
    path = default_project_profile_path(root)
    if path.exists():
        return ProjectHarnessProfileStore().load(path)
    profile = ProjectHarnessScanner().scan(root)
    ProjectHarnessProfileStore().save(profile, path)
    return profile


def _ensure_authority_profile(root: Path) -> tuple[dict[str, Any], list[Path]]:
    """AI company 설치 시 기본 권한 프로파일을 보장하되 기존 권한은 보존한다."""
    from engine.project_authority import (
        PROPOSAL_ONLY,
        append_authority_log,
        default_authority_path,
        default_authority_profile,
        load_authority_profile,
    )

    authority_path = default_authority_path(root)
    if authority_path.exists():
        return load_authority_profile(root), [authority_path]

    profile = default_authority_profile(PROPOSAL_ONLY)
    saved = _save_yaml(authority_path, profile)
    log_path = append_authority_log(
        root,
        command="cambrian harness install --confirm",
        mode=PROPOSAL_ONLY,
        result="authority_initialized_for_ai_company_install",
        changed_files=[_relative(saved, root)],
        rollback_hint="Run: cambrian authority revoke --json or remove .cambrian/authority.yaml if the install is discarded.",
    )
    return profile, [saved, log_path]


def _missing_required(answers: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in sorted(REQUIRED_ANSWER_IDS):
        value = answers.get(key)
        if value is None:
            missing.append(key)
        elif isinstance(value, str) and not value.strip():
            missing.append(key)
    return missing


def _harness_id(root: Path, answers: dict[str, Any], profile: dict[str, Any]) -> str:
    base = _slug(root.name, "project")
    domains = [str(item).lower() for item in profile.get("domains", []) if item]
    goal = str(answers.get("primary_goal") or "").lower()
    suffixes: list[str] = []
    if "auth" in domains or "인증" in goal or "login" in goal:
        suffixes.append("auth")
    if "예약" in goal or "reservation" in goal or "booking" in goal:
        suffixes.append("reservation")
    if not suffixes:
        suffixes.extend(domains[:2])
    suffix = "-".join(_slug(item, "work") for item in suffixes if item) or "work"
    return f"custom-{base}-{suffix}"


def _agent_specs(answers: dict[str, Any]) -> list[dict[str, str]]:
    raw_roles = _as_string_list(answers.get("agent_roles"))
    if not raw_roles:
        return [
            {"id": "bug-fix-agent", "role": "원인 후보와 수정 제안을 만든다."},
            {"id": "regression-test-agent", "role": "회귀 테스트 관점에서 검증한다."},
            {"id": "review-agent", "role": "위험도와 부작용을 검토한다."},
        ]
    specs: list[dict[str, str]] = []
    for index, role in enumerate(raw_roles, start=1):
        specs.append({"id": f"custom-agent-{index}", "role": role})
    return specs


def _test_commands(answers: dict[str, Any]) -> list[str]:
    commands = _as_string_list(answers.get("test_command"))
    commands.extend(_as_string_list(answers.get("build_command")))
    result: list[str] = []
    seen: set[str] = set()
    for command in commands:
        if command not in seen:
            seen.add(command)
            result.append(command)
    return result


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "\n" in text:
        return [line.strip("- ").strip() for line in text.splitlines() if line.strip("- ").strip()]
    return [text]


def _seed_warnings(seed_preset: str | None, profile: dict[str, Any]) -> list[str]:
    if not seed_preset:
        return []
    recommended = [str(item) for item in profile.get("recommended_harnesses", []) if item]
    if recommended and seed_preset not in recommended:
        return [f"Seed preset {seed_preset} is not the recommended preset for this project."]
    return [f"Seed preset {seed_preset} is used only as a reference. The installed harness remains custom."]


def _harness_payload(plan: dict[str, Any]) -> dict[str, Any]:
    policy = dict(plan.get("policy", {})) if isinstance(plan.get("policy"), dict) else {}
    project = dict(plan.get("project", {})) if isinstance(plan.get("project"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "id": plan.get("harness_id"),
        "type": "custom",
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_from": "conversational_interview",
        "seed_preset": plan.get("seed_preset"),
        "language": project.get("language"),
        "test_framework": project.get("test_framework"),
        "goal": plan.get("goal"),
        "policy": {
            "change_mode": policy.get("change_mode") or "proposal_only",
            "auto_apply": False,
            "forbidden": list(policy.get("forbidden", []) if isinstance(policy.get("forbidden"), list) else []),
            "allowed": list(policy.get("allowed", []) if isinstance(policy.get("allowed"), list) else []),
            "risk_level": policy.get("risk_level"),
        },
        "important_paths": list(plan.get("important_paths", []) if isinstance(plan.get("important_paths"), list) else []),
    }


def _lane_label(harness: dict[str, Any]) -> str:
    language = str(harness.get("language") or "custom").strip()
    framework = str(harness.get("test_framework") or "manual").strip()
    return f"{language} + {framework}"
