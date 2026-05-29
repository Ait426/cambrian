from __future__ import annotations

import json
import logging
import subprocess
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
from engine.project_llm_assist import LLM_GENERATION_EVIDENCE_KEY, bootstrap_llm_generation_evidence, llm_assist_policy
from engine.project_pack_install import SCHEMA_VERSION, _as_list, _now, _relative, _slug, _stamp


LOGGER = logging.getLogger(__name__)


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


def _save_json(path: Path, payload: dict[str, Any]) -> Path:
    target = Path(path).resolve()
    _atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
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


def default_custom_patch_intents_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "patch_intents"


def default_custom_validation_evidence_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "evidence" / "validation"


def default_custom_jobs_evidence_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "jobs"


def default_custom_outcomes_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "evidence" / "outcomes.yaml"


def default_custom_reports_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "reports"


def default_custom_latest_verdict_path(project_root: Path) -> Path:
    return default_custom_reports_dir(project_root) / "latest_verdict.json"


def default_company_export_manifest_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "company" / "export_manifest.yaml"


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
    except Exception as exc:
        LOGGER.debug("generated custom agents load failed; falling back to custom agents file", exc_info=exc)
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
    agent_specs = _agent_specs(answers, profile.to_dict())
    test_commands = _test_commands(answers)
    change_policy = _normalize_change_policy(answers.get("change_policy")) or "proposal_only"
    success_criteria = _as_string_list(answers.get("validation_standard")) or ["관련 검증 기준 충족"]
    important_paths = _as_string_list(answers.get("important_paths")) or _profile_important_paths(profile.to_dict())
    from engine.project_harness_engineering import build_codebase_evidence, build_harness_quality_gate

    codebase_evidence = build_codebase_evidence(root, profile.to_dict(), important_paths, test_commands)
    domain_spec = _domain_spec(root, profile.to_dict(), answers, test_commands, success_criteria, codebase_evidence)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "ok": True,
        "plan_type": "custom",
        "harness_id": harness_id,
        "selected_harness": harness_id,
        "status": "draft",
        "generation_quality_status": "bootstrap_draft",
        "llm_assist_policy": llm_assist_policy("harness_generation", provider_used=False),
        LLM_GENERATION_EVIDENCE_KEY: bootstrap_llm_generation_evidence("harness_generation"),
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
            "policy": change_policy,
            "success_criteria": success_criteria,
            "evidence_required": [
                "codebase_evidence.status must be grounded before install",
                "test_framework_evidence must be recorded before validation command selection",
                "risk_boundaries must be checked before patch proposal",
            ],
        },
        "domain_spec": domain_spec,
        "codebase_evidence": codebase_evidence,
        "evaluator_contract": _evaluator_contract(test_commands, success_criteria),
        "candidate_lineage": {
            "candidate_id": harness_id,
            "harness_id": harness_id,
            "parent_candidate_id": None,
            "source": "interview_answers",
            "generation_id": "installed-initial",
            "mutation_summary": "custom harness generated from project scan and interview answers",
        },
    "policy": {
            "change_mode": change_policy,
            "auto_apply": False,
            "forbidden": _as_string_list(answers.get("forbidden_scope")),
            "allowed": _as_string_list(answers.get("allowed_scope")),
            "risk_level": str(answers.get("risk_level") or "").strip() or None,
        },
        "important_paths": important_paths,
        "install_preview": [
            ".cambrian/profile.yaml",
            ".cambrian/harness.yaml",
            ".cambrian/workforce.yaml",
            ".cambrian/agents/*.yaml",
            ".cambrian/skills/*.yaml",
            ".cambrian/validation.yaml",
            ".cambrian/operating_rules.yaml",
            ".cambrian/company/discussion/agents.yaml",
            ".cambrian/interview/answers.yaml",
            ".cambrian/interview/questions.yaml",
            ".cambrian/plan.yaml",
        ],
        "next_command": "cambrian workforce generate --json",
        "next_commands": ["cambrian workforce generate --json", "cambrian harness install --confirm --json"],
        "warnings": _seed_warnings(seed_preset, profile.to_dict()),
        "errors": [],
    }
    plan["quality_gate"] = build_harness_quality_gate(
        {
            "project_profile": plan["project"],
            "validation": plan["validation"],
            "workforce": {"agents": agent_specs},
            "codebase_evidence": codebase_evidence,
        }
    )
    from engine.project_company_layer import build_project_discussion_layer

    plan["project_discussion_layer"] = build_project_discussion_layer(
        root,
        harness_id=str(plan.get("harness_id") or harness_id),
        goal=str(plan.get("goal") or ""),
        codebase_evidence=codebase_evidence,
    )
    plan["company_blueprint"] = _company_blueprint_from_plan(plan)
    plan["harness_os_contract"] = _harness_os_contract_from_plan(plan)
    plan["relearning_policy"] = _relearning_policy_from_blueprint(plan["company_blueprint"])
    plan["marketplace_boundary"] = _marketplace_boundary_from_blueprint(plan["company_blueprint"])
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
    from engine.project_company_layer import save_project_discussion_layer
    from engine.project_workforce_builder import install_generated_workforce

    project_mode_files, project_mode_warnings = _ensure_project_mode_baseline(root, plan)
    authority_profile, authority_files = _ensure_authority_profile(root)
    workforce_payload, generated_agents, workforce_files = install_generated_workforce(root, plan)
    generated_skills, skill_mapping, skill_files = install_generated_skills(root, plan, workforce_payload)
    workforce_payload["skills"] = skill_mapping
    if workforce_files:
        _save_yaml(workforce_files[0], workforce_payload)
    agents_payload = {"schema_version": SCHEMA_VERSION, "agents": list(generated_agents)}
    validation_payload = {"schema_version": SCHEMA_VERSION, "validation": dict(plan.get("validation", {}))}
    company_export_manifest = _company_export_manifest(root, plan, workforce_payload, generated_agents, generated_skills)
    discussion_layer_path = save_project_discussion_layer(
        root,
        dict(plan.get("project_discussion_layer", {}) if isinstance(plan.get("project_discussion_layer"), dict) else {}),
    )
    files = [
        *project_mode_files,
        _save_yaml(default_root_profile_path(root), profile),
        _save_yaml(default_custom_harness_path(root), harness_payload),
        _save_yaml(default_custom_agents_path(root), agents_payload),
        _save_yaml(default_custom_validation_path(root), validation_payload),
        _save_yaml(default_custom_plan_path(root), plan),
        _save_yaml(default_company_export_manifest_path(root), company_export_manifest),
        discussion_layer_path,
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
        warnings=_dedupe([*project_mode_warnings, *[str(item) for item in plan.get("warnings", [])]]),
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
    job_stamp = f"{_stamp()}_{datetime.now(timezone.utc).strftime('%f')}"
    job_id = f"job-{_slug(harness_id, 'custom-harness')}-{job_stamp}"
    lane_id = f"{harness.get('language')}-{harness.get('test_framework')}"
    evidence_context = _job_bridge_evidence_context(root, harness, validation, selected_agents, selected_skills, request_text)
    company_context = _job_company_structure_context(workforce, selected_agents, selected_skills, evidence_context)
    bridge_context = {
        "pack_id": harness_id,
        "pack_ref": harness_id,
        "harness_id": harness_id,
        "project_type": "custom_harness",
        "stack": _dedupe([
            str(harness.get("language") or "").strip(),
            str(harness.get("test_framework") or "").strip(),
        ]),
        "workforce_id": str(workforce.get("id")) if isinstance(workforce, dict) and workforce.get("id") else None,
        "selected_agents": list(selected_agents),
        "selected_skills": list(selected_skills),
        "dispatch_reason": dispatch_reason,
        "change_policy": str(harness.get("policy", {}).get("change_mode") or "proposal_only"),
        "validation_commands": list(validation.get("test_commands", []) if isinstance(validation.get("test_commands"), list) else []),
        "company_structure": company_context,
        "company_roles": company_context.get("active_roles", {}),
        "responsibility_matrix": company_context.get("responsibility_matrix", {}),
        "duplicate_guard": company_context.get("duplicate_guard", {}),
        **evidence_context,
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
            "evidence_status": evidence_context.get("evidence_status"),
            "manual_review_required": evidence_context.get("manual_review_required"),
            "domain_confidence": evidence_context.get("domain_confidence"),
            "quality_gate": evidence_context.get("quality_gate"),
            "agent_evidence_context": evidence_context.get("agent_evidence_context"),
            "agent_runtime_contracts": evidence_context.get("agent_runtime_contracts"),
            "llm_required_agents": evidence_context.get("llm_required_agents"),
            "llm_invocation_required": evidence_context.get("llm_invocation_required"),
            "skill_evidence_context": evidence_context.get("skill_evidence_context"),
            "evidence_gap_report": evidence_context.get("evidence_gap_report"),
            "company_blueprint": evidence_context.get("company_blueprint"),
            "harness_os_contract": evidence_context.get("harness_os_contract"),
            "relearning_policy": evidence_context.get("relearning_policy"),
            "marketplace_boundary": evidence_context.get("marketplace_boundary"),
            "project_discussion_layer": evidence_context.get("project_discussion_layer"),
            "company_structure": company_context,
            "company_roles": company_context.get("active_roles", {}),
            "responsibility_matrix": company_context.get("responsibility_matrix", {}),
            "company_loop_context": evidence_context.get("company_loop_context"),
            "context_intent_snapshot": evidence_context.get("context_intent_snapshot"),
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


def _job_bridge_evidence_context(
    root: Path,
    harness: dict[str, Any],
    validation: dict[str, Any],
    selected_agents: list[str],
    selected_skills: list[str],
    request_text: str,
) -> dict[str, Any]:
    codebase_evidence = _compact_codebase_evidence(harness.get("codebase_evidence"))
    domain_spec = dict(harness.get("domain_spec", {}) if isinstance(harness.get("domain_spec"), dict) else {})
    evaluator_contract = dict(harness.get("evaluator_contract", {}) if isinstance(harness.get("evaluator_contract"), dict) else {})
    quality_gate = dict(harness.get("quality_gate", {}) if isinstance(harness.get("quality_gate"), dict) else {})
    policy = dict(harness.get("policy", {}) if isinstance(harness.get("policy"), dict) else {})
    company_blueprint = dict(harness.get("company_blueprint", {}) if isinstance(harness.get("company_blueprint"), dict) else {})
    harness_os_contract = dict(harness.get("harness_os_contract", {}) if isinstance(harness.get("harness_os_contract"), dict) else {})
    relearning_policy = dict(harness.get("relearning_policy", {}) if isinstance(harness.get("relearning_policy"), dict) else {})
    marketplace_boundary = dict(harness.get("marketplace_boundary", {}) if isinstance(harness.get("marketplace_boundary"), dict) else {})
    project_discussion_layer = dict(
        harness.get("project_discussion_layer", {}) if isinstance(harness.get("project_discussion_layer"), dict) else {}
    )
    risk_boundaries = _first_mapping(
        codebase_evidence.get("risk_boundaries"),
        domain_spec.get("risk_boundaries"),
    )
    status = str(codebase_evidence.get("status") or "missing")
    manual_review_required = (
        status != "grounded"
        or bool(codebase_evidence.get("requires_code_review_before_install"))
        or str(quality_gate.get("status") or "") in {"caution", "hold"}
    )
    evidence_warnings = ["manual review required"] if manual_review_required else []
    if status not in {"", "grounded"}:
        evidence_warnings.append(f"codebase evidence status is {status}")
    if quality_gate.get("status"):
        evidence_warnings.extend([f"quality gate status is {quality_gate.get('status')}"])
    validation_commands = _dedupe(
        [
            *_as_string_list(validation.get("test_commands")),
            *_as_string_list(domain_spec.get("validation_commands")),
            *_as_string_list(evaluator_contract.get("validation_commands")),
        ]
    )
    pass_criteria = domain_spec.get("pass_criteria", {}) if isinstance(domain_spec.get("pass_criteria"), dict) else {}
    validation_criteria = _dedupe(
        [
            *_as_string_list(validation.get("success_criteria")),
            *_as_string_list(pass_criteria.get("success_criteria")),
            *_as_string_list(evaluator_contract.get("success_criteria")),
        ]
    )
    forbidden_actions = _dedupe(
        [
            *_as_string_list(policy.get("forbidden")),
            *_as_string_list(domain_spec.get("forbidden_paths")),
            *_as_string_list(risk_boundaries.get("default_forbidden")),
        ]
    )
    risk_checks = _as_string_list(risk_boundaries.get("checks")) if risk_boundaries.get("requires_manual_approval") else []
    approval_required_actions = _dedupe(
        [
            *_as_string_list(domain_spec.get("approval_required_actions")),
            *risk_checks,
        ]
    )
    company_loop_context = _load_company_loop_context(root)
    context_intent_snapshot = _build_context_intent_snapshot(
        root=root,
        request_text=request_text,
        company_loop_context=company_loop_context,
        codebase_evidence=codebase_evidence,
        domain_confidence=dict(
            codebase_evidence.get("domain_confidence", {}) if isinstance(codebase_evidence.get("domain_confidence"), dict) else {}
        ),
        risk_boundaries=risk_boundaries,
    )
    agent_evidence_context = _selected_artifact_evidence_context(root, "agents", selected_agents, codebase_evidence)
    skill_evidence_context = _selected_artifact_evidence_context(root, "skills", selected_skills, codebase_evidence)
    agent_runtime_contracts = _agent_runtime_contracts_from_context(agent_evidence_context)
    llm_required_agents = [
        agent_id
        for agent_id, contract in agent_runtime_contracts.items()
        if isinstance(contract, dict) and contract.get("requires_llm_call")
    ]
    evidence_gap_report = _job_evidence_gap_report(
        codebase_evidence=codebase_evidence,
        agent_evidence_context=agent_evidence_context,
        validation_commands=validation_commands,
    )
    return {
        "codebase_evidence": codebase_evidence,
        "evidence_card": dict(codebase_evidence.get("evidence_card", {}) if isinstance(codebase_evidence.get("evidence_card"), dict) else {}),
        "domain_confidence": dict(codebase_evidence.get("domain_confidence", {}) if isinstance(codebase_evidence.get("domain_confidence"), dict) else {}),
        "quality_gate": quality_gate,
        "evidence_status": status,
        "manual_review_required": manual_review_required,
        "evidence_warnings": _dedupe(evidence_warnings),
        "company_loop_context": company_loop_context,
        "context_intent_snapshot": context_intent_snapshot,
        "agent_evidence_context": agent_evidence_context,
        "agent_runtime_contracts": agent_runtime_contracts,
        "llm_required_agents": llm_required_agents,
        "llm_invocation_required": bool(llm_required_agents),
        "skill_evidence_context": skill_evidence_context,
        "evidence_gap_report": evidence_gap_report,
        "risk_boundaries": risk_boundaries,
        "evaluator_contract": evaluator_contract,
        "company_blueprint": company_blueprint,
        "harness_os_contract": harness_os_contract,
        "relearning_policy": relearning_policy,
        "marketplace_boundary": marketplace_boundary,
        "project_discussion_layer": project_discussion_layer,
        "validation_criteria": validation_criteria,
        "validation_commands": validation_commands,
        "forbidden_actions": forbidden_actions,
        "approval_required_actions": approval_required_actions,
        "response_contract_requirements": [
            "codebase evidence path citation",
            "risk boundary check",
            "validation command selection",
            "patch application state",
            "verdict rationale",
            "domain confidence check",
            "context intent resolution",
            "project discussion role check",
            *(
                ["llm invocation evidence"]
                if llm_required_agents
                else []
            ),
        ],
    }


def _job_evidence_gap_report(
    *,
    codebase_evidence: dict[str, Any],
    agent_evidence_context: dict[str, dict[str, Any]],
    validation_commands: list[str],
) -> dict[str, Any]:
    domain_confidence = codebase_evidence.get("domain_confidence", {}) if isinstance(codebase_evidence.get("domain_confidence"), dict) else {}
    weak = _as_string_list(domain_confidence.get("weak"))
    suspected = _as_string_list(domain_confidence.get("suspected"))
    missing_agent_paths = [
        agent_id
        for agent_id, context in agent_evidence_context.items()
        if isinstance(context, dict) and not _as_string_list(context.get("paths"))
    ]
    gaps: list[str] = []
    if suspected:
        gaps.append("suspected domains need job evidence before proof claims: " + ", ".join(suspected[:6]))
    if weak:
        gaps.append("weak domains must stay reference-only: " + ", ".join(weak[:6]))
    if missing_agent_paths:
        gaps.append("selected agents without direct evidence paths: " + ", ".join(missing_agent_paths[:6]))
    if not validation_commands:
        gaps.append("validation command missing")
    return {
        "status": "gaps_present" if gaps else "ready",
        "purpose": "force the AI worker to produce new evidence-backed findings instead of restating old memory",
        "suspected_domains": suspected,
        "weak_domains": weak,
        "selected_agents_without_paths": missing_agent_paths,
        "validation_commands_present": bool(validation_commands),
        "gaps": gaps,
    }


def _build_context_intent_snapshot(
    *,
    root: Path,
    request_text: str,
    company_loop_context: dict[str, Any],
    codebase_evidence: dict[str, Any],
    domain_confidence: dict[str, Any],
    risk_boundaries: dict[str, Any],
) -> dict[str, Any]:
    try:
        from engine.project_company_layer import build_context_intent_snapshot

        return build_context_intent_snapshot(
            root,
            request_text,
            company_loop_context=company_loop_context,
            codebase_evidence=codebase_evidence,
            domain_confidence=domain_confidence,
            risk_boundaries=risk_boundaries,
        )
    except Exception as exc:
        LOGGER.warning("context intent snapshot build failed: %s", exc)
        return {
            "snapshot_kind": "context_intent_snapshot",
            "status": "unavailable",
            "quality_gate": {
                "target_product_level": "upper",
                "current_context_level": "low",
                "passes_upper_bar": False,
                "reason": f"context intent snapshot unavailable: {type(exc).__name__}",
            },
            "context_policy": {
                "memory_is_not_context": True,
                "manual_review_when_intent_is_low": True,
            },
        }


def _job_company_structure_context(
    workforce: dict[str, Any] | None,
    selected_agents: list[str],
    selected_skills: list[str],
    evidence_context: dict[str, Any],
) -> dict[str, Any]:
    """job start에 넣을 회사 역할 컨텍스트를 만든다."""
    workforce_payload = workforce if isinstance(workforce, dict) else {}
    company = dict(workforce_payload.get("company_structure", {}) if isinstance(workforce_payload.get("company_structure"), dict) else {})
    if not company:
        company = _fallback_company_structure(selected_agents, evidence_context)
    roles = dict(company.get("roles", {}) if isinstance(company.get("roles"), dict) else {})
    active_roles = {
        str(role_id): dict(role)
        for role_id, role in roles.items()
        if isinstance(role, dict) and str(role.get("agent_id") or "") in set(_as_string_list(selected_agents))
    }
    if not active_roles:
        active_roles = {str(role_id): dict(role) for role_id, role in roles.items() if isinstance(role, dict)}
    company_scale = dict(company.get("company_scale", {}) if isinstance(company.get("company_scale"), dict) else {})
    target_lift = dict(company.get("target_lift", {}) if isinstance(company.get("target_lift"), dict) else {})
    duplicate_guard = dict(company.get("duplicate_guard", {}) if isinstance(company.get("duplicate_guard"), dict) else {})
    responsibility_matrix = dict(
        company.get("responsibility_matrix", {}) if isinstance(company.get("responsibility_matrix"), dict) else {}
    )
    company_fit_report = _company_fit_report(
        company=company,
        active_roles=active_roles,
        selected_agents=selected_agents,
        selected_skills=selected_skills,
        evidence_context=evidence_context,
        company_scale=company_scale,
        target_lift=target_lift,
        duplicate_guard=duplicate_guard,
    )
    return {
        "mode": str(company.get("mode") or "lean_project_company"),
        "status": str(company.get("status") or "ready"),
        "principle": company.get("principle")
        or "Map project company responsibilities onto the smallest useful workforce.",
        "company_scale": company_scale,
        "target_lift": target_lift,
        "company_fit_report": company_fit_report,
        "roles": roles,
        "active_roles": active_roles,
        "responsibility_matrix": responsibility_matrix,
        "duplicate_guard": duplicate_guard,
        "selected_agents": _as_string_list(selected_agents),
        "selected_skills": _as_string_list(selected_skills),
        "required_role_checks": [
            "context_manager cited evidence paths",
            "execution_lead stayed inside change policy",
            "verification_owner selected validation command",
        ],
    }


def _company_fit_report(
    *,
    company: dict[str, Any],
    active_roles: dict[str, dict[str, Any]],
    selected_agents: list[str],
    selected_skills: list[str],
    evidence_context: dict[str, Any],
    company_scale: dict[str, Any],
    target_lift: dict[str, Any],
    duplicate_guard: dict[str, Any],
) -> dict[str, Any]:
    """job start에서 AI가 회사 설계의 의도와 빈틈을 바로 읽을 수 있게 요약한다."""
    required_roles = ["context_manager", "direction_owner", "execution_lead", "verification_owner"]
    missing_roles = [role_id for role_id in required_roles if role_id not in active_roles]
    roles_without_evidence = [
        role_id
        for role_id, role in active_roles.items()
        if isinstance(role, dict) and not _as_string_list(role.get("evidence_paths"))
    ]
    validation_commands = _as_string_list(evidence_context.get("validation_commands"))
    evidence_status = str(evidence_context.get("evidence_status") or "missing")
    manual_review_required = bool(evidence_context.get("manual_review_required"))
    coverage_gaps: list[str] = []
    if missing_roles:
        coverage_gaps.append(f"missing required roles: {', '.join(missing_roles)}")
    if roles_without_evidence:
        coverage_gaps.append(f"roles without evidence paths: {', '.join(roles_without_evidence)}")
    if not validation_commands:
        coverage_gaps.append("validation command missing")
    if manual_review_required:
        coverage_gaps.append("manual review required before proof claims")
    duplicate_ids = _as_string_list(duplicate_guard.get("duplicate_agent_ids"))
    if duplicate_ids:
        coverage_gaps.append(f"duplicate agents detected: {', '.join(duplicate_ids)}")
    company_size = str(company_scale.get("company_size") or "unknown")
    product_domains = _as_string_list(company_scale.get("product_domains"))
    external_systems = _as_string_list(company_scale.get("external_systems"))
    important_path_count = int(company_scale.get("important_path_count") or 0)
    why_this_size = [
        f"company_size={company_size}",
        f"important_paths={important_path_count}",
        f"product_domains={len(product_domains)}",
        f"external_systems={len(external_systems)}",
    ]
    return {
        "status": "caution" if coverage_gaps else "ready",
        "company_size": company_size,
        "target_lift_pct": int(target_lift.get("pct") or company_scale.get("target_lift_pct") or 30),
        "why_this_size": why_this_size,
        "active_role_count": len(active_roles),
        "selected_agent_count": len(_as_string_list(selected_agents)),
        "selected_skill_count": len(_as_string_list(selected_skills)),
        "required_roles_present": {role_id: role_id in active_roles for role_id in required_roles},
        "evidence_status": evidence_status,
        "manual_review_required": manual_review_required,
        "validation_commands": validation_commands,
        "coverage_gaps": coverage_gaps,
        "operating_principle": "project-fit company, evidence-first context, proposal-only execution, validation-gated proof",
    }


def _fallback_company_structure(selected_agents: list[str], evidence_context: dict[str, Any]) -> dict[str, Any]:
    """workforce 역할표가 없을 때 선택된 agent로 최소 회사 구조를 만든다."""
    agents = _as_string_list(selected_agents)
    fallback = agents[0] if agents else None
    verifier = next((agent for agent in agents if "regression" in agent or agent == "risk-reviewer"), fallback)
    evidence = evidence_context.get("codebase_evidence", {}) if isinstance(evidence_context.get("codebase_evidence"), dict) else {}
    evidence_paths = _as_string_list(evidence.get("existing_important_paths"))[:8]
    roles = {
        "context_manager": {
            "role_id": "context_manager",
            "office": "context",
            "agent_id": fallback,
            "responsibility": "Maintain project context and cite evidence paths for the job.",
            "evidence_paths": evidence_paths,
            "approval_policy": "explicit",
        },
        "execution_lead": {
            "role_id": "execution_lead",
            "office": "execution",
            "agent_id": fallback,
            "responsibility": "Analyze the requested path without applying changes automatically.",
            "evidence_paths": evidence_paths,
            "approval_policy": "explicit",
        },
        "verification_owner": {
            "role_id": "verification_owner",
            "office": "verification",
            "agent_id": verifier,
            "responsibility": "Select validation commands and block unproven success claims.",
            "evidence_paths": evidence_paths,
            "approval_policy": "explicit",
        },
    }
    matrix: dict[str, list[str]] = {}
    for role_id, role in roles.items():
        agent_id = str(role.get("agent_id") or "")
        if agent_id:
            matrix.setdefault(agent_id, []).append(role_id)
    return {
        "mode": "lean_project_company",
        "status": "incomplete" if not fallback else "ready",
        "roles": roles,
        "responsibility_matrix": matrix,
        "duplicate_guard": {
            "agent_count": len(agents),
            "unique_agent_count": len(set(agents)),
            "max_agents": 5,
            "extra_agent_requires_codebase_evidence": True,
        },
}


def _load_company_loop_context(root: Path) -> dict[str, Any]:
    """Company Layer ledger의 최신 job 루프 컨텍스트를 읽는다."""
    try:
        from engine.project_company_layer import load_company_loop_context

        return load_company_loop_context(root)
    except Exception as exc:
        LOGGER.warning("company loop context load failed: %s", exc)
        return {
            "status": "unavailable",
            "context_records": [],
            "verification_entries": [],
            "warnings": [f"company loop context load failed: {type(exc).__name__}"],
            "promotion_policy": {
                "auto_promote": False,
                "requires_user_review": True,
            },
        }


def _compact_codebase_evidence(value: Any) -> dict[str, Any]:
    evidence = dict(value) if isinstance(value, dict) else {}
    risk_boundaries = dict(evidence.get("risk_boundaries", {}) if isinstance(evidence.get("risk_boundaries"), dict) else {})
    test_framework_evidence = dict(evidence.get("test_framework_evidence", {}) if isinstance(evidence.get("test_framework_evidence"), dict) else {})
    validation_command_evidence = dict(
        evidence.get("validation_command_evidence", {}) if isinstance(evidence.get("validation_command_evidence"), dict) else {}
    )
    domain_evidence = dict(evidence.get("domain_evidence", {}) if isinstance(evidence.get("domain_evidence"), dict) else {})
    weak_domain_evidence = dict(evidence.get("weak_domain_evidence", {}) if isinstance(evidence.get("weak_domain_evidence"), dict) else {})
    return {
        "status": str(evidence.get("status") or "missing"),
        "source": evidence.get("source"),
        "requires_code_review_before_install": bool(evidence.get("requires_code_review_before_install")),
        "existing_important_paths": _as_string_list(evidence.get("existing_important_paths"))[:12],
        "missing_important_paths": _as_string_list(evidence.get("missing_important_paths"))[:12],
        "evidence_card": dict(evidence.get("evidence_card", {}) if isinstance(evidence.get("evidence_card"), dict) else {}),
        "domain_confidence": dict(evidence.get("domain_confidence", {}) if isinstance(evidence.get("domain_confidence"), dict) else {}),
        "domain_evidence": {str(key): _as_string_list(paths)[:8] for key, paths in domain_evidence.items()},
        "weak_domain_evidence": {str(key): _as_string_list(paths)[:8] for key, paths in weak_domain_evidence.items()},
        "test_framework_evidence": test_framework_evidence,
        "validation_command_evidence": validation_command_evidence,
        "risk_boundaries": risk_boundaries,
        "contract_requirements": _as_string_list(evidence.get("contract_requirements")),
    }


def _selected_artifact_evidence_context(
    root: Path,
    artifact_kind: str,
    selected_ids: list[str],
    fallback_evidence: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if artifact_kind == "agents":
        from engine.project_workforce_builder import load_generated_agents

        artifacts = load_generated_agents(root)
    else:
        from engine.project_skill_builder import load_generated_skills

        artifacts = load_generated_skills(root)
    by_id = {str(item.get("id")): item for item in artifacts if isinstance(item, dict) and item.get("id")}
    return {
        artifact_id: _artifact_evidence_context(by_id.get(artifact_id), fallback_evidence)
        for artifact_id in _as_string_list(selected_ids)
    }


def _artifact_evidence_context(artifact: dict[str, Any] | None, fallback_evidence: dict[str, Any]) -> dict[str, Any]:
    payload = artifact if isinstance(artifact, dict) else {}
    evidence = dict(payload.get("codebase_evidence", {}) if isinstance(payload.get("codebase_evidence"), dict) else {})
    risk_boundaries = _first_mapping(evidence.get("risk_boundaries"), fallback_evidence.get("risk_boundaries"))
    validation = payload.get("validation", {}) if isinstance(payload.get("validation"), dict) else {}
    runtime_contract = payload.get("runtime_contract", {}) if isinstance(payload.get("runtime_contract"), dict) else {}
    return {
        "status": str(evidence.get("status") or fallback_evidence.get("status") or "missing"),
        "agent_kind": payload.get("agent_kind"),
        "responsibility_class": payload.get("responsibility_class"),
        "requires_reasoning": bool(payload.get("requires_reasoning")),
        "requires_llm_call": bool(payload.get("requires_llm_call")),
        "runtime_contract": runtime_contract,
        "llm_invocation": dict(runtime_contract.get("llm_invocation", {}))
        if isinstance(runtime_contract.get("llm_invocation"), dict)
        else {},
        "domains": _as_string_list(evidence.get("domains")),
        "paths": _as_string_list(evidence.get("paths")) or _as_string_list(fallback_evidence.get("existing_important_paths"))[:8],
        "test_framework": evidence.get("test_framework")
        or _first_mapping(fallback_evidence.get("test_framework_evidence")).get("framework"),
        "risk_boundaries": risk_boundaries,
        "validation_required": _as_string_list(validation.get("required")),
    }


def _agent_runtime_contracts_from_context(agent_context: dict[str, dict[str, Any]]) -> dict[str, Any]:
    contracts: dict[str, Any] = {}
    for agent_id, context in agent_context.items():
        if not isinstance(context, dict):
            continue
        contracts[str(agent_id)] = {
            "agent_kind": context.get("agent_kind") or "ai_agent",
            "responsibility_class": context.get("responsibility_class"),
            "requires_reasoning": bool(context.get("requires_reasoning")),
            "requires_llm_call": bool(context.get("requires_llm_call")),
            "llm_invocation": dict(context.get("llm_invocation", {})) if isinstance(context.get("llm_invocation"), dict) else {},
        }
    return contracts


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _save_custom_job(root: Path, job: dict[str, Any]) -> Path:
    job_id = str(job.get("job_id") or "job-custom")
    job_path = default_custom_job_path(root, job_id)
    _save_yaml(job_path, job)
    _save_yaml(default_custom_jobs_dir(root) / "latest.yaml", job)
    return job_path


def _reply_evidence_compliance(root: Path, job: dict[str, Any], reply_content: dict[str, Any]) -> dict[str, Any]:
    packet = _load_linked_bridge_packet(root, job)
    response_contract = packet.get("response_contract", {}) if isinstance(packet.get("response_contract"), dict) else {}
    required = _reply_evidence_required_items(response_contract)
    evidence_paths = _reply_evidence_paths(reply_content)
    risk_checked = _reply_risk_boundary_checked(reply_content)
    validation_commands = _reply_validation_commands(reply_content)
    patch_application_state = _reply_patch_application_state(reply_content)
    verdict_rationale = _reply_verdict_rationale(reply_content)
    context_intent_resolved = _reply_context_intent_resolved(reply_content)
    project_discussion_checked = _reply_project_discussion_checked(reply_content)
    llm_invocation_evidence = _reply_llm_invocation_evidence(reply_content)
    satisfied: list[str] = []
    if evidence_paths:
        satisfied.append("codebase_evidence_path_citation")
    if risk_checked:
        satisfied.append("risk_boundary_check")
    if validation_commands:
        satisfied.append("validation_command_selection")
    if patch_application_state.get("stated"):
        satisfied.append("patch_application_state")
    if verdict_rationale:
        satisfied.append("verdict_rationale")
    if context_intent_resolved:
        satisfied.append("context_intent_resolution")
    if project_discussion_checked:
        satisfied.append("project_discussion_role_check")
    if llm_invocation_evidence.get("satisfied"):
        satisfied.append("llm_invocation_evidence")
    missing = [item for item in required if item not in satisfied]
    return {
        "status": "satisfied" if not missing else "incomplete",
        "required": required,
        "satisfied": satisfied,
        "missing": missing,
        "evidence_paths": evidence_paths,
        "risk_boundary_checked": risk_checked,
        "validation_commands": validation_commands,
        "patch_application_state": patch_application_state,
        "verdict_rationale": verdict_rationale,
        "context_intent_resolved": context_intent_resolved,
        "project_discussion_checked": project_discussion_checked,
        "llm_invocation_evidence": llm_invocation_evidence,
        "manual_review_required": bool(missing),
    }


def _job_reply_evidence_compliance(root: Path, job: dict[str, Any]) -> dict[str, Any]:
    stored = job.get("reply_evidence_compliance")
    if isinstance(stored, dict) and stored:
        return dict(stored)
    reply_ref = str(job.get("linked_bridge_reply_ref") or "")
    if reply_ref:
        try:
            reply_payload = _load_yaml(_resolve_root_path(root, Path(reply_ref)))
            content = reply_payload.get("content", {}) if isinstance(reply_payload.get("content"), dict) else {}
            return _reply_evidence_compliance(root, job, content)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            required = _reply_evidence_required_items({})
            return {
                "status": "incomplete",
                "required": required,
                "satisfied": [],
                "missing": required,
                "evidence_paths": [],
                "risk_boundary_checked": False,
                "validation_commands": [],
                "patch_application_state": _empty_patch_application_state(),
                "verdict_rationale": "",
                "context_intent_resolved": False,
                "project_discussion_checked": False,
                "llm_invocation_evidence": _empty_llm_invocation_evidence(),
                "manual_review_required": True,
                "warnings": [f"reply evidence source load failed: {type(exc).__name__}"],
            }
    required = _reply_evidence_required_items({})
    return {
        "status": "incomplete",
        "required": required,
        "satisfied": [],
        "missing": required,
        "evidence_paths": [],
        "risk_boundary_checked": False,
        "validation_commands": [],
        "patch_application_state": _empty_patch_application_state(),
        "verdict_rationale": "",
        "context_intent_resolved": False,
        "project_discussion_checked": False,
        "llm_invocation_evidence": _empty_llm_invocation_evidence(),
        "manual_review_required": True,
    }


def _load_linked_bridge_packet(root: Path, job: dict[str, Any]) -> dict[str, Any]:
    packet_ref = str(job.get("linked_bridge_packet_ref") or "")
    if not packet_ref:
        return {}
    try:
        return _load_yaml(_resolve_root_path(root, Path(packet_ref)))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return {"_load_error": type(exc).__name__}


def _reply_evidence_required_items(response_contract: dict[str, Any]) -> list[str]:
    raw_required = _as_string_list(response_contract.get("evidence_required_keys"))
    normalized = [_normalize_evidence_requirement(item) for item in raw_required]
    required = _dedupe([item for item in normalized if item])
    return required or [
        "codebase_evidence_path_citation",
        "risk_boundary_check",
        "validation_command_selection",
        "patch_application_state",
        "verdict_rationale",
    ]


def _normalize_evidence_requirement(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    if "codebase" in text and "path" in text:
        return "codebase_evidence_path_citation"
    if "risk" in text and "check" in text:
        return "risk_boundary_check"
    if "validation" in text and ("command" in text or "selection" in text):
        return "validation_command_selection"
    if "patch" in text and ("application" in text or "applied" in text or "state" in text):
        return "patch_application_state"
    if "source" in text and ("mutation" in text or "modified" in text):
        return "patch_application_state"
    if "verdict" in text and ("rationale" in text or "reason" in text):
        return "verdict_rationale"
    if "rationale" in text and "verdict" in text:
        return "verdict_rationale"
    if "context" in text and "intent" in text:
        return "context_intent_resolution"
    if "project" in text and "discussion" in text:
        return "project_discussion_role_check"
    if "discussion" in text and "role" in text:
        return "project_discussion_role_check"
    if "llm" in text and ("invocation" in text or "call" in text or "evidence" in text):
        return "llm_invocation_evidence"
    if "ai" in text and "agent" in text and ("invocation" in text or "call" in text):
        return "llm_invocation_evidence"
    if "model" in text and ("invocation" in text or "call" in text):
        return "llm_invocation_evidence"
    return _slug(text, "requirement").replace("-", "_")


def _reply_evidence_paths(reply_content: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ["codebase_evidence_paths", "evidence_paths", "evidence_refs", "evidence_ref"]:
        paths.extend(_as_string_list(reply_content.get(key)))
    evidence = reply_content.get("evidence")
    if isinstance(evidence, dict):
        paths.extend(_as_string_list(evidence.get("paths")))
        paths.extend(_as_string_list(evidence.get("codebase_paths")))
        paths.extend(_as_string_list(evidence.get("refs")))
    elif isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                paths.extend(_as_string_list(item.get("path") or item.get("ref")))
            else:
                paths.extend(_as_string_list(item))
    return _dedupe(paths)


def _reply_risk_boundary_checked(reply_content: dict[str, Any]) -> bool:
    for key in ["risk_boundary_check", "risk_boundaries_checked", "risk_check"]:
        value = reply_content.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            if value.get("checked") is False:
                return False
            return bool(value)
        if _as_string_list(value):
            return True
    return False


def _reply_validation_commands(reply_content: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for key in ["validation_commands", "selected_validation_command", "validation_command"]:
        commands.extend(_as_string_list(reply_content.get(key)))
    selection = reply_content.get("validation_command_selection")
    if isinstance(selection, dict):
        commands.extend(_as_string_list(selection.get("command")))
        commands.extend(_as_string_list(selection.get("commands")))
    else:
        commands.extend(_as_string_list(selection))
    return _dedupe(commands)


def _empty_patch_application_state() -> dict[str, Any]:
    return {
        "stated": False,
        "patch_applied": False,
        "source_code_modified": False,
        "summary": "",
    }


def _reply_patch_application_state(reply_content: dict[str, Any]) -> dict[str, Any]:
    state = _empty_patch_application_state()
    explicit_values: list[Any] = []
    for key in [
        "patch_application_state",
        "patch_application",
        "patch_state",
        "source_mutation_state",
        "source_mutation",
    ]:
        if key in reply_content:
            explicit_values.append(reply_content.get(key))
    if "patch_applied" in reply_content:
        explicit_values.append({"patch_applied": reply_content.get("patch_applied")})
    if "source_code_modified" in reply_content:
        explicit_values.append({"source_code_modified": reply_content.get("source_code_modified")})
    if "source_modified" in reply_content:
        explicit_values.append({"source_code_modified": reply_content.get("source_modified")})

    summaries: list[str] = []
    for value in explicit_values:
        if isinstance(value, dict):
            if value:
                state["stated"] = True
            patch_value = _first_present_value(value, ["patch_applied", "applied", "patch_was_applied"])
            source_value = _first_present_value(value, ["source_code_modified", "source_modified", "source_mutated", "modified"])
            patch_bool = _coerce_reply_bool(patch_value)
            source_bool = _coerce_reply_bool(source_value)
            if patch_bool is not None:
                state["patch_applied"] = patch_bool
            if source_bool is not None:
                state["source_code_modified"] = source_bool
            summaries.extend(_as_string_list(value.get("summary")))
            summaries.extend(_as_string_list(value.get("reason")))
            summaries.extend(_as_string_list(value.get("state")))
        elif isinstance(value, bool):
            state["stated"] = True
            state["patch_applied"] = value
            state["source_code_modified"] = value
        elif _as_string_list(value):
            text = " ".join(_as_string_list(value))
            state["stated"] = True
            patch_bool = _coerce_reply_bool(text)
            if patch_bool is not None:
                state["patch_applied"] = patch_bool
            source_bool = _coerce_reply_bool(text)
            if source_bool is not None:
                state["source_code_modified"] = source_bool
            summaries.append(text)

    state["summary"] = _truncate_text(" | ".join(_dedupe(summaries)), 300)
    return state


def _first_present_value(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload:
            return payload.get(key)
    return None


def _truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 12)].rstrip() + " [truncated]"


def _coerce_reply_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    negative_markers = [
        "not applied",
        "not modified",
        "no source",
        "no mutation",
        "unchanged",
        "proposal only",
        "proposal-only",
        "false",
        "no",
        "none",
    ]
    if any(marker in text for marker in negative_markers):
        return False
    positive_markers = ["applied", "modified", "mutated", "changed", "true", "yes"]
    if any(marker in text for marker in positive_markers):
        return True
    return None


def _reply_verdict_rationale(reply_content: dict[str, Any]) -> str:
    for key in ["verdict_rationale", "verdict_reason", "rationale", "completion_rationale", "proof_rationale"]:
        values = _as_string_list(reply_content.get(key))
        if values:
            return _truncate_text(" ".join(values), 500)
    verdict = reply_content.get("verdict")
    if isinstance(verdict, dict):
        for key in ["rationale", "reason", "summary"]:
            values = _as_string_list(verdict.get(key))
            if values:
                return _truncate_text(" ".join(values), 500)
    return ""


def _reply_context_intent_resolved(reply_content: dict[str, Any]) -> bool:
    for key in ["context_intent_resolution", "intent_resolution", "context_intent"]:
        value = reply_content.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            if value.get("resolved") is False:
                return False
            return bool(value)
        if _as_string_list(value):
            return True
    return False


def _reply_project_discussion_checked(reply_content: dict[str, Any]) -> bool:
    for key in ["project_discussion_role_check", "project_discussion_check", "discussion_role_check", "role_view_summary"]:
        value = reply_content.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, dict):
            if value.get("checked") is False:
                return False
            return bool(value)
        if _as_string_list(value):
            return True
    return False


def _empty_llm_invocation_evidence() -> dict[str, Any]:
    return {
        "satisfied": False,
        "called": False,
        "mode": None,
        "provider": None,
        "agent_ids": [],
        "summary": "",
    }


def _reply_llm_invocation_evidence(reply_content: dict[str, Any]) -> dict[str, Any]:
    evidence = _empty_llm_invocation_evidence()
    raw = _first_present_value(
        reply_content,
        [
            "llm_invocation_evidence",
            "llm_call_evidence",
            "llm_call",
            "ai_agent_invocation",
            "model_invocation",
            "ai_worker_invocation",
        ],
    )
    if isinstance(raw, dict):
        called = raw.get("called")
        if called is False:
            evidence["summary"] = _truncate_text(raw.get("summary") or "LLM call explicitly marked false", 300)
            return evidence
        mode = str(raw.get("mode") or raw.get("call_mode") or raw.get("invocation_mode") or "").strip()
        provider = str(raw.get("provider") or raw.get("model_provider") or raw.get("runtime") or "").strip()
        agent_ids = _as_string_list(raw.get("agent_ids") or raw.get("agents") or raw.get("selected_agents"))
        summary = _truncate_text(raw.get("summary") or raw.get("evidence") or "", 300)
        evidence.update(
            {
                "satisfied": bool(called is True or mode or provider or agent_ids or summary),
                "called": bool(called is not False and (called is True or mode or provider or agent_ids or summary)),
                "mode": mode or None,
                "provider": provider or None,
                "agent_ids": agent_ids,
                "summary": summary,
            }
        )
        return evidence
    values = _as_string_list(raw)
    if values:
        text = _truncate_text(" ".join(values), 300)
        evidence.update(
            {
                "satisfied": True,
                "called": True,
                "mode": "external_ai_worker",
                "summary": text,
            }
        )
    return evidence


def _custom_relearning_gate(
    *,
    snapshot: dict[str, Any],
    reply_evidence_compliance: dict[str, Any],
    unchecked_items: list[str],
    validation_commands: list[str],
) -> dict[str, Any]:
    company_structure = snapshot.get("company_structure", {}) if isinstance(snapshot.get("company_structure"), dict) else {}
    fit_report = company_structure.get("company_fit_report", {}) if isinstance(company_structure.get("company_fit_report"), dict) else {}
    relearning_policy = snapshot.get("relearning_policy", {}) if isinstance(snapshot.get("relearning_policy"), dict) else {}
    coverage_gaps = _as_string_list(fit_report.get("coverage_gaps"))
    triggers: list[str] = []
    if reply_evidence_compliance.get("status") != "satisfied":
        triggers.append("reply evidence compliance incomplete")
    if not validation_commands:
        triggers.append("missing validation command")
    if any("roles without evidence paths" in item for item in coverage_gaps):
        triggers.append("agent without evidence path")
    if any("missing required roles" in item for item in coverage_gaps):
        triggers.append("missing company role")
    if any("duplicate agents" in item for item in coverage_gaps):
        triggers.append("duplicate worker contract")
    if len([item for item in unchecked_items if "Manual" in item or "manual" in item]) >= 2:
        triggers.append("repeated manual review gap")
    status = "stable"
    recommended_action = "keep"
    if triggers:
        status = "review_required"
        recommended_action = "revise"
    if any(trigger in {"missing validation command", "missing company role", "agent without evidence path"} for trigger in triggers):
        status = "rebuild_candidate"
        recommended_action = "rebuild"
    return {
        "status": status,
        "recommended_action": recommended_action,
        "auto_apply": False,
        "auto_promote": False,
        "target_lift_pct": int(relearning_policy.get("target_lift_pct") or 30) if isinstance(relearning_policy, dict) else 30,
        "triggers": _dedupe(triggers),
        "coverage_gaps": coverage_gaps,
        "policy": "do not promote new defaults automatically; route revise/rebuild candidates through user review",
    }


def ingest_custom_harness_job(project_root: Path, job_ref: str, reply_file: Path) -> dict[str, Any]:
    from engine.project_bridge import ProjectBridgeReplyParser, ProjectBridgeStore, default_bridge_reply_path

    root = Path(project_root).resolve()
    job, _ = _load_custom_job(root, job_ref)
    source = _resolve_root_path(root, reply_file)
    reply = ProjectBridgeReplyParser().parse_reply(source.read_text(encoding="utf-8"))
    reply.source_reply_path = _relative(source, root)
    reply.linked_request_ref = _relative(default_custom_job_path(root, str(job.get("job_id") or "")), root)
    errors = list(reply.errors)
    if errors:
        job["status"] = "blocked"
        job["validation_status"] = "blocked"
        job["reply_kind"] = reply.response_kind
        job["errors"] = _dedupe([*list(job.get("errors", [])), *errors])
        _save_custom_job(root, job)
        return {
            "ok": False,
            "status": "blocked",
            "job_id": job.get("job_id"),
            "job_ref": _relative(default_custom_job_path(root, str(job.get("job_id") or "")), root),
            "pack_id": job.get("pack_id"),
            "reply_kind": reply.response_kind,
            "reply_contract_status": "blocked",
            "reply_file_ref": _relative(source, root),
            "request_packet_ref": job.get("linked_bridge_packet_ref"),
            "patch_candidate_accepted": False,
            "patch_applied": False,
            "source_code_modified": False,
            "ai_provider_called": False,
            "next_commands": ["cambrian job ingest latest ai_reply_patch_candidate.yaml"],
            "errors": errors,
            "warnings": list(reply.warnings),
        }
    reply_path = ProjectBridgeStore().save_reply(reply, default_bridge_reply_path(root, reply))
    patch_intent_ref = None
    patch_candidate_accepted = reply.response_kind == "patch_candidate"
    if patch_candidate_accepted:
        patch_intent_ref = _save_patch_intent(root, job, reply.content)
    reply_evidence_compliance = _reply_evidence_compliance(root, job, reply.content)
    patch_application_state = dict(
        reply_evidence_compliance.get("patch_application_state", {})
        if isinstance(reply_evidence_compliance.get("patch_application_state"), dict)
        else _empty_patch_application_state()
    )
    job["reply_kind"] = reply.response_kind
    job["linked_bridge_reply_ref"] = _relative(reply_path, root)
    job["linked_patch_intent_ref"] = patch_intent_ref
    job["reply_file_ref"] = _relative(source, root)
    job["reply_evidence_compliance"] = reply_evidence_compliance
    job["status"] = "validation_ready"
    job["validation_status"] = "ready"
    job["updated_at"] = _now()
    job["next_command"] = "cambrian job validate latest"
    job["next_actions"] = ["cambrian job validate latest"]
    _save_custom_job(root, job)
    return {
        "ok": True,
        "status": "validation_ready",
        "job_id": job.get("job_id"),
        "job_ref": _relative(default_custom_job_path(root, str(job.get("job_id") or "")), root),
        "pack_id": job.get("pack_id"),
        "reply_kind": reply.response_kind,
        "bridge_reply_ref": _relative(reply_path, root),
        "patch_intent_ref": patch_intent_ref,
        "reply_contract_status": "accepted_patch_candidate" if patch_candidate_accepted else "accepted",
        "reply_evidence_compliance": reply_evidence_compliance,
        "reply_evidence_status": reply_evidence_compliance.get("status"),
        "patch_application_state": patch_application_state,
        "verdict_rationale": reply_evidence_compliance.get("verdict_rationale") or "",
        "reply_file_ref": _relative(source, root),
        "request_packet_ref": job.get("linked_bridge_packet_ref"),
        "patch_candidate_accepted": patch_candidate_accepted,
        "patch_applied": False,
        "source_code_modified": False,
        "ai_provider_called": False,
        "next_commands": ["cambrian job validate latest"],
        "warnings": list(reply.warnings),
        "errors": [],
    }


def _validation_commands_not_run(commands: list[str]) -> dict[str, Any]:
    return {
        "status": "not_run" if commands else "not_configured",
        "mode": "manual",
        "commands": list(commands),
        "results": [],
        "summary": "validation commands were recorded but not executed by Cambrian",
    }


def _execute_validation_commands(root: Path, commands: list[str]) -> dict[str, Any]:
    safe_commands = _dedupe([str(command).strip() for command in commands if str(command).strip()])
    if not safe_commands:
        return {
            "status": "not_configured",
            "mode": "local_command_runner",
            "commands": [],
            "results": [],
            "summary": "no validation commands are configured",
        }
    results: list[dict[str, Any]] = []
    for command in safe_commands:
        safety = _validation_command_safety(command)
        if not safety["allowed"]:
            results.append(
                {
                    "command": command,
                    "status": "blocked",
                    "exit_code": None,
                    "duration_ms": 0,
                    "stdout": "",
                    "stderr": "",
                    "safety": safety,
                }
            )
            continue
        started = datetime.now(timezone.utc)
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
            duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            results.append(
                {
                    "command": command,
                    "status": "passed" if completed.returncode == 0 else "failed",
                    "exit_code": completed.returncode,
                    "duration_ms": duration_ms,
                    "stdout": _redact_command_output(completed.stdout),
                    "stderr": _redact_command_output(completed.stderr),
                    "safety": safety,
                }
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            results.append(
                {
                    "command": command,
                    "status": "timeout",
                    "exit_code": None,
                    "duration_ms": duration_ms,
                    "stdout": _redact_command_output(exc.stdout),
                    "stderr": _redact_command_output(exc.stderr),
                    "safety": safety,
                }
            )
    statuses = [str(item.get("status") or "") for item in results]
    if any(status == "blocked" for status in statuses):
        status = "blocked"
    elif any(status in {"failed", "timeout"} for status in statuses):
        status = "failed"
    else:
        status = "passed"
    return {
        "status": status,
        "mode": "local_command_runner",
        "commands": safe_commands,
        "results": results,
        "summary": _validation_run_summary(status, results),
    }


def _validation_command_safety(command: str) -> dict[str, Any]:
    lowered = str(command or "").strip().lower()
    blocked_tokens = [
        "git push",
        "git reset",
        "git checkout",
        "rm -rf",
        "remove-item",
        "rmdir ",
        "del /",
        "npm install",
        "pnpm install",
        "yarn add",
        "pip install",
        ".env",
        "curl ",
        "invoke-webrequest",
        "scp ",
        "ssh ",
    ]
    shell_chaining = ["&&", "||", ";", "|", ">", "<", "`"]
    reasons = [token for token in blocked_tokens if token in lowered]
    reasons.extend([f"shell operator {token}" for token in shell_chaining if token in lowered])
    return {
        "allowed": not reasons,
        "policy": "validation command runner allows local verification commands only",
        "blocked_reasons": reasons,
    }


def _redact_command_output(value: Any) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")
    redacted_lines: list[str] = []
    secret_tokens = ["secret", "token", "password", "api_key", "apikey", "database_url", "service_role"]
    for line in text.splitlines():
        lowered = line.lower()
        if any(token in lowered for token in secret_tokens):
            redacted_lines.append("[redacted sensitive output line]")
        else:
            redacted_lines.append(line)
    redacted = "\n".join(redacted_lines)
    if len(redacted) > 4000:
        return redacted[:4000] + "\n[truncated]"
    return redacted


def _validation_run_summary(status: str, results: list[dict[str, Any]]) -> str:
    passed = len([item for item in results if item.get("status") == "passed"])
    failed = len([item for item in results if item.get("status") in {"failed", "timeout"}])
    blocked = len([item for item in results if item.get("status") == "blocked"])
    return f"validation commands {status}: passed={passed}, failed={failed}, blocked={blocked}"


def _validation_status_from_run(
    validation_run: dict[str, Any],
    *,
    run_commands: bool,
    unchecked_items: list[str],
) -> tuple[str, str, str, bool]:
    if not run_commands:
        return "not_ready", "manual_validation_required", "manual_required", True
    run_status = str(validation_run.get("status") or "")
    if run_status == "passed":
        trust_gate = "verified_with_unchecked_risk" if unchecked_items else "verified"
        return "passed", "commands_executed", trust_gate, False
    if run_status == "failed":
        return "failed", "commands_executed", "validation_failed", False
    if run_status == "blocked":
        return "blocked", "command_execution_blocked", "manual_required", True
    return "not_ready", "validation_command_missing", "manual_required", True


def validate_custom_harness_job(project_root: Path, job_ref: str, run_commands: bool = False) -> dict[str, Any]:
    root = Path(project_root).resolve()
    job, _ = _load_custom_job(root, job_ref)
    harness = load_custom_harness(root) or {}
    job_id = str(job.get("job_id") or "")
    snapshot = dict(job.get("outcome_snapshot", {}) if isinstance(job.get("outcome_snapshot"), dict) else {})
    validation_commands = _as_string_list(snapshot.get("validation_commands"))
    checked_artifacts = _dedupe(
        [
            str(job.get("linked_bridge_packet_ref") or ""),
            str(job.get("reply_file_ref") or ""),
            str(job.get("linked_bridge_reply_ref") or ""),
            str(job.get("linked_patch_intent_ref") or ""),
        ]
    )
    reply_evidence_compliance = _job_reply_evidence_compliance(root, job)
    patch_application_state = dict(
        reply_evidence_compliance.get("patch_application_state", {})
        if isinstance(reply_evidence_compliance.get("patch_application_state"), dict)
        else _empty_patch_application_state()
    )
    patch_applied = bool(patch_application_state.get("patch_applied"))
    source_code_modified = bool(patch_application_state.get("source_code_modified"))
    change_policy = str(snapshot.get("change_policy") or harness.get("policy", {}).get("change_mode") or "proposal_only")
    patch_candidate_present = bool(job.get("linked_patch_intent_ref"))
    validation_run = _execute_validation_commands(root, validation_commands) if run_commands else _validation_commands_not_run(validation_commands)
    unchecked_items: list[str] = []
    if patch_candidate_present and not patch_applied and change_policy != "proposal_only":
        unchecked_items.append("Patch proposal was not applied to source code")
    if not run_commands:
        unchecked_items.append("Manual validation command must be run by the user")
    elif validation_run.get("status") == "blocked":
        unchecked_items.append("Validation command execution was blocked by safety policy")
    elif validation_run.get("status") == "failed":
        failed = ", ".join(
            [
                str(item.get("command"))
                for item in validation_run.get("results", [])
                if isinstance(item, dict) and str(item.get("status") or "") in {"failed", "timeout", "blocked"}
            ][:3]
        )
        unchecked_items.append(f"Validation command failed: {failed or 'unknown'}")
    elif validation_run.get("status") == "not_configured":
        unchecked_items.append("Validation command missing")
    if reply_evidence_compliance.get("status") != "satisfied":
        missing = ", ".join(_as_string_list(reply_evidence_compliance.get("missing"))[:5]) or "unknown"
        unchecked_items.append(f"AI reply evidence compliance incomplete: {missing}")
    relearning_gate = _custom_relearning_gate(
        snapshot=snapshot,
        reply_evidence_compliance=reply_evidence_compliance,
        unchecked_items=unchecked_items,
        validation_commands=validation_commands,
    )
    evidence_target = default_custom_validation_evidence_dir(root) / f"{_slug(job_id, 'job')}.yaml"
    evidence_ref = _relative(evidence_target, root)
    validation_status, validation_contract_status, trust_gate_status, manual_validation_required = _validation_status_from_run(
        validation_run,
        run_commands=run_commands,
        unchecked_items=unchecked_items,
    )
    if run_commands:
        checked_artifacts = _dedupe(
            [
                *checked_artifacts,
                *[
                    f"validation_command:{item.get('command')}"
                    for item in validation_run.get("results", [])
                    if isinstance(item, dict) and item.get("command")
                ],
            ]
        )
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "evidence_kind": "job_validation",
        "job_id": job_id,
        "job_ref": _relative(default_custom_job_path(root, job_id), root),
        "pack_id": job.get("pack_id"),
        "request_packet_ref": job.get("linked_bridge_packet_ref"),
        "reply_file_ref": job.get("reply_file_ref"),
        "bridge_reply_ref": job.get("linked_bridge_reply_ref"),
        "patch_intent_ref": job.get("linked_patch_intent_ref"),
        "validation_status": validation_status,
        "validation_contract_status": validation_contract_status,
        "trust_gate_status": trust_gate_status,
        "manual_validation_required": manual_validation_required,
        "validation_commands": validation_commands,
        "validation_command_execution": validation_run,
        "checked_artifacts": checked_artifacts,
        "unchecked_items": unchecked_items,
        "patch_applied": False,
        "source_code_modified": False,
        "ai_provider_called": False,
        "reply_evidence_compliance": reply_evidence_compliance,
        "patch_application_state": patch_application_state,
        "verdict_rationale": reply_evidence_compliance.get("verdict_rationale") or "",
        "relearning_gate": relearning_gate,
        "context_intent_snapshot": dict(
            snapshot.get("context_intent_snapshot", {}) if isinstance(snapshot.get("context_intent_snapshot"), dict) else {}
        ),
        "outcome_snapshot": {
            **snapshot,
            "validation_lane": "custom harness",
            "auto_apply": False,
            "test_commands": validation_commands,
            "validation_command_execution": validation_run,
            "relearning_gate": relearning_gate,
        },
    }
    evaluator_verdict = _custom_evaluator_verdict(
        job=job,
        harness=harness,
        evidence=evidence,
        evidence_ref=evidence_ref,
    )
    latest_verdict_path = _save_json(default_custom_latest_verdict_path(root), evaluator_verdict)
    latest_verdict_ref = _relative(latest_verdict_path, root)
    evidence["evaluator_verdict"] = {
        "verdict": evaluator_verdict["verdict"],
        "verdict_reason": evaluator_verdict["verdict_reason"],
        "promotion_readiness": evaluator_verdict["promotion_readiness"],
    }
    evidence["latest_verdict_ref"] = latest_verdict_ref
    company_verification = _record_company_verification(
        root=root,
        job_id=job_id,
        stage="validate",
        validation_evidence_ref=evidence_ref,
        verdict_ref=latest_verdict_ref,
        verdict=str(evaluator_verdict.get("verdict") or ""),
        trust_gate_status=str(evidence.get("trust_gate_status") or ""),
        validation_commands=validation_commands,
        checked_artifacts=checked_artifacts,
        unchecked_items=unchecked_items,
        company_roles=snapshot.get("company_roles"),
        context_intent_snapshot=snapshot.get("context_intent_snapshot"),
    )
    evidence["company_verification_record"] = company_verification
    evidence_path = _save_yaml(evidence_target, evidence)
    job["status"] = "validation_ready"
    job["validation_status"] = validation_status
    job["linked_validation_evidence_ref"] = _relative(evidence_path, root)
    job["linked_latest_verdict_ref"] = latest_verdict_ref
    job["updated_at"] = _now()
    job["next_command"] = "cambrian job complete latest --outcome partial --notes \"validation result\""
    job["next_actions"] = [job["next_command"]]
    _save_custom_job(root, job)
    return {
        "ok": bool(run_commands and validation_run.get("status") == "passed"),
        "status": "validation_ready",
        "job_id": job_id,
        "job_ref": _relative(default_custom_job_path(root, job_id), root),
        "pack_id": job.get("pack_id"),
        "validation_status": validation_status,
        "validation_contract_status": validation_contract_status,
        "trust_gate_status": trust_gate_status,
        "manual_validation_required": manual_validation_required,
        "validation_commands": validation_commands,
        "validation_command_execution": validation_run,
        "checked_artifacts": checked_artifacts,
        "unchecked_items": unchecked_items,
        "evidence_ref": _relative(evidence_path, root),
        "latest_verdict_ref": latest_verdict_ref,
        "company_verification_record": company_verification,
        "evaluator_verdict": evaluator_verdict,
        "verdict": evaluator_verdict["verdict"],
        "request_packet_ref": job.get("linked_bridge_packet_ref"),
        "reply_file_ref": job.get("reply_file_ref"),
        "bridge_reply_ref": job.get("linked_bridge_reply_ref"),
        "patch_intent_ref": job.get("linked_patch_intent_ref"),
        "reply_evidence_compliance": reply_evidence_compliance,
        "reply_evidence_status": reply_evidence_compliance.get("status"),
        "patch_application_state": patch_application_state,
        "verdict_rationale": reply_evidence_compliance.get("verdict_rationale") or "",
        "relearning_gate": relearning_gate,
        "patch_applied": False,
        "source_code_modified": False,
        "ai_provider_called": False,
        "outcome_snapshot": evidence["outcome_snapshot"],
        "next_commands": list(job["next_actions"]),
        "warnings": [],
        "errors": [],
    }


def complete_custom_harness_job(project_root: Path, job_ref: str, outcome: str, notes: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    job, _ = _load_custom_job(root, job_ref)
    job_id = str(job.get("job_id") or "")
    outcome_value = str(outcome or "").strip()
    allowed = {"success", "partial", "failed", "rejected", "needs_more_info"}
    if outcome_value not in allowed:
        return {
            "ok": False,
            "status": "blocked",
            "job_id": job_id,
            "outcome": outcome_value,
            "errors": [f"outcome must be one of: {', '.join(sorted(allowed))}"],
        }
    validation_evidence, validation_ref = _latest_custom_validation_evidence(root, job_id)
    snapshot = dict(job.get("outcome_snapshot", {}) if isinstance(job.get("outcome_snapshot"), dict) else {})
    validation_commands = _as_string_list(validation_evidence.get("validation_commands") or snapshot.get("validation_commands"))
    reply_evidence_compliance = dict(
        validation_evidence.get("reply_evidence_compliance", {})
        if isinstance(validation_evidence.get("reply_evidence_compliance"), dict)
        else {}
    )
    patch_application_state = dict(
        validation_evidence.get("patch_application_state", {})
        if isinstance(validation_evidence.get("patch_application_state"), dict)
        else reply_evidence_compliance.get("patch_application_state", {})
        if isinstance(reply_evidence_compliance.get("patch_application_state"), dict)
        else _empty_patch_application_state()
    )
    outcome_target = default_custom_jobs_evidence_dir(root) / _slug(job_id, "job") / "outcome.yaml"
    outcome_ref = _relative(outcome_target, root)
    outcome_payload = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": _now(),
        "evidence_kind": "job_outcome",
        "job_id": job_id,
        "job_ref": _relative(default_custom_job_path(root, job_id), root),
        "request": job.get("request"),
        "outcome": outcome_value,
        "notes": str(notes or "").strip(),
        "validation_evidence_ref": validation_ref,
        "validation_contract_status": _text_or_none(validation_evidence.get("validation_contract_status")),
        "trust_gate_status": _text_or_none(validation_evidence.get("trust_gate_status")),
        "checked_artifacts": _as_string_list(validation_evidence.get("checked_artifacts")),
        "unchecked_items": _as_string_list(validation_evidence.get("unchecked_items")),
        "reply_evidence_compliance": reply_evidence_compliance,
        "patch_application_state": patch_application_state,
        "verdict_rationale": validation_evidence.get("verdict_rationale") or reply_evidence_compliance.get("verdict_rationale") or "",
        "relearning_gate": dict(validation_evidence.get("relearning_gate", {}) if isinstance(validation_evidence.get("relearning_gate"), dict) else {}),
        "context_intent_snapshot": dict(
            snapshot.get("context_intent_snapshot", {}) if isinstance(snapshot.get("context_intent_snapshot"), dict) else {}
        ),
        "harness_id": snapshot.get("harness_id") or job.get("pack_id"),
        "workforce_id": snapshot.get("workforce_id"),
        "selected_agents": _as_string_list(snapshot.get("selected_agents")),
        "selected_skills": _as_string_list(snapshot.get("selected_skills")),
        "validation_commands": validation_commands,
        "change_policy": snapshot.get("change_policy") or "proposal_only",
        "source_code_modified_by_cambrian": False,
        "patch_applied_by_cambrian": False,
        "ai_provider_called_by_cambrian": False,
        "ready_for_evolution": True,
    }
    harness = load_custom_harness(root) or {}
    evaluator_verdict = _custom_outcome_evaluator_verdict(
        job=job,
        harness=harness,
        validation_evidence=validation_evidence,
        validation_ref=validation_ref,
        outcome_payload=outcome_payload,
        outcome_ref=outcome_ref,
    )
    latest_verdict_path = _save_json(default_custom_latest_verdict_path(root), evaluator_verdict)
    latest_verdict_ref = _relative(latest_verdict_path, root)
    outcome_payload["evaluator_verdict"] = {
        "verdict": evaluator_verdict["verdict"],
        "verdict_reason": evaluator_verdict["verdict_reason"],
        "promotion_readiness": evaluator_verdict["promotion_readiness"],
    }
    outcome_payload["latest_verdict_ref"] = latest_verdict_ref
    company_context_record = _record_company_context_outcome(
        root=root,
        job=job,
        outcome_payload=outcome_payload,
        outcome_ref=outcome_ref,
    )
    outcome_payload["company_context_record"] = company_context_record
    company_verification = _record_company_verification(
        root=root,
        job_id=job_id,
        stage="complete",
        validation_evidence_ref=validation_ref,
        verdict_ref=latest_verdict_ref,
        verdict=str(evaluator_verdict.get("verdict") or ""),
        trust_gate_status=str(outcome_payload.get("trust_gate_status") or ""),
        validation_commands=validation_commands,
        checked_artifacts=outcome_payload["checked_artifacts"],
        unchecked_items=outcome_payload["unchecked_items"],
        company_roles=snapshot.get("company_roles"),
        context_evidence_ref=company_context_record.get("saved_path") if isinstance(company_context_record, dict) else None,
        context_intent_snapshot=snapshot.get("context_intent_snapshot"),
    )
    outcome_payload["company_verification_record"] = company_verification
    outcome_path = _save_yaml(outcome_target, outcome_payload)
    ledger_path = _append_custom_outcome(root, outcome_payload)
    job["final_status"] = outcome_value
    job["closed_at"] = _now()
    job["linked_outcome_ref"] = _relative(outcome_path, root)
    job["linked_latest_verdict_ref"] = latest_verdict_ref
    _save_custom_job(root, job)
    return {
        "ok": True,
        "status": "recorded",
        "job_id": job_id,
        "outcome": outcome_value,
        "notes": str(notes or "").strip(),
        "outcome_ref": _relative(outcome_path, root),
        "evidence_ref": _relative(ledger_path, root),
        "validation_evidence_ref": validation_ref,
        "latest_verdict_ref": latest_verdict_ref,
        "company_context_record": company_context_record,
        "company_verification_record": company_verification,
        "evaluator_verdict": evaluator_verdict,
        "verdict": evaluator_verdict["verdict"],
        "validation_contract_status": outcome_payload["validation_contract_status"],
        "trust_gate_status": outcome_payload["trust_gate_status"],
        "validation_commands": validation_commands,
        "checked_artifacts": outcome_payload["checked_artifacts"],
        "unchecked_items": outcome_payload["unchecked_items"],
        "reply_evidence_compliance": reply_evidence_compliance,
        "patch_application_state": patch_application_state,
        "verdict_rationale": outcome_payload["verdict_rationale"],
        "ready_for_evolution": True,
        "relearning_gate": outcome_payload["relearning_gate"],
        "source_code_modified_by_cambrian": False,
        "warnings": [] if validation_ref else ["No validation evidence was found for this job."],
        "errors": [],
    }


def _load_custom_job(root: Path, job_ref: str) -> tuple[dict[str, Any], Path]:
    ref = str(job_ref or "").strip()
    if not ref:
        raise FileNotFoundError("job ref is required")
    if ref == "latest":
        path = default_custom_jobs_dir(root) / "latest.yaml"
        if path.exists():
            return _load_yaml(path), path
        raise FileNotFoundError("latest job not found")
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.exists():
        return _load_yaml(candidate), candidate.resolve()
    jobs_dir = default_custom_jobs_dir(root)
    candidates = [
        jobs_dir / f"{ref}.yaml",
        jobs_dir / f"{_slug(ref, 'job')}.yaml",
        jobs_dir / ref,
    ]
    for path in candidates:
        if path.exists():
            return _load_yaml(path), path.resolve()
    raise FileNotFoundError(f"job not found: {job_ref}")


def _resolve_root_path(root: Path, path: Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    return target.resolve()


def _save_patch_intent(root: Path, job: dict[str, Any], reply_content: dict[str, Any]) -> str:
    job_id = str(job.get("job_id") or "job-custom")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "job_id": job_id,
        "job_ref": _relative(default_custom_job_path(root, job_id), root),
        "response_kind": reply_content.get("response_kind"),
        "summary": reply_content.get("summary"),
        "target_path": reply_content.get("target_path"),
        "old_text": reply_content.get("old_text"),
        "new_text": reply_content.get("new_text"),
        "reason": reply_content.get("reason"),
        "related_tests": _as_string_list(reply_content.get("related_tests")),
        "patch_applied": False,
        "source_code_modified": False,
    }
    path = _save_yaml(default_custom_patch_intents_dir(root) / f"{_slug(job_id, 'job')}.yaml", payload)
    return _relative(path, root)


def _record_company_verification(
    *,
    root: Path,
    job_id: str,
    stage: str,
    validation_evidence_ref: str | None,
    verdict_ref: str | None,
    verdict: str,
    trust_gate_status: str,
    validation_commands: list[str],
    checked_artifacts: list[str],
    unchecked_items: list[str],
    company_roles: Any,
    context_evidence_ref: str | None = None,
    context_intent_snapshot: Any = None,
) -> dict[str, Any]:
    """Company Verification ledger에 job 검증 결과를 기록한다."""
    try:
        from engine.project_company_layer import record_verification_entry

        return record_verification_entry(
            root,
            source=f"job:{stage}",
            job_id=job_id,
            stage=stage,
            validation_evidence_ref=validation_evidence_ref,
            verdict_ref=verdict_ref,
            verdict=verdict,
            trust_gate_status=trust_gate_status,
            validation_commands=validation_commands,
            checked_artifacts=checked_artifacts,
            unchecked_items=unchecked_items,
            company_roles=dict(company_roles) if isinstance(company_roles, dict) else {},
            context_evidence_ref=context_evidence_ref,
            context_intent_snapshot=dict(context_intent_snapshot) if isinstance(context_intent_snapshot, dict) else {},
        )
    except Exception as exc:
        LOGGER.warning("company verification ledger record failed: %s", exc)
        return {
            "ok": False,
            "status": "company_verification_record_failed",
            "error": type(exc).__name__,
            "auto_promote": False,
            "requires_user_review": True,
        }


def _record_company_context_outcome(
    *,
    root: Path,
    job: dict[str, Any],
    outcome_payload: dict[str, Any],
    outcome_ref: str,
) -> dict[str, Any]:
    """Company Context ledger에 job 결과 후보 기록을 남긴다."""
    try:
        from engine.project_company_layer import record_context_candidate

        unchecked = _as_string_list(outcome_payload.get("unchecked_items"))
        validation_commands = _as_string_list(outcome_payload.get("validation_commands"))
        summary = (
            f"job {outcome_payload.get('job_id')} recorded as {outcome_payload.get('outcome')}; "
            f"verdict={outcome_payload.get('evaluator_verdict', {}).get('verdict')}; "
            f"unchecked_risk={len(unchecked)}"
        )
        lesson = "Keep validation evidence and unchecked risk visible in the next job start packet."
        mistake = "Do not claim proof when validation remains manual." if unchecked else None
        return record_context_candidate(
            root,
            source=str(outcome_payload.get("job_id") or job.get("job_id") or "job"),
            summary=summary,
            kind="job_outcome",
            decision="Record job result as context candidate only; do not auto-promote.",
            lesson=f"{lesson} validation_commands={', '.join(validation_commands) or 'none'}",
            mistake=mistake,
            evidence_ref=outcome_ref,
        )
    except Exception as exc:
        LOGGER.warning("company context ledger record failed: %s", exc)
        return {
            "ok": False,
            "status": "company_context_record_failed",
            "error": type(exc).__name__,
            "auto_promote": False,
            "requires_user_review": True,
        }


def _custom_evaluator_verdict(
    job: dict[str, Any],
    harness: dict[str, Any],
    evidence: dict[str, Any],
    evidence_ref: str,
) -> dict[str, Any]:
    validation_commands = _as_string_list(evidence.get("validation_commands"))
    checked_artifacts = _as_string_list(evidence.get("checked_artifacts"))
    unchecked_items = _as_string_list(evidence.get("unchecked_items"))
    evaluator_contract = dict(harness.get("evaluator_contract", {})) if isinstance(harness.get("evaluator_contract"), dict) else {}
    validation_status = str(evidence.get("validation_status") or "")
    verdict = "hold"
    promotion_readiness = "blocked"
    verdict_reason = "manual_validation_required"
    if not validation_commands:
        verdict_reason = "validation_commands_missing"
    elif validation_status == "failed":
        verdict = "rollback"
        verdict_reason = "validation_command_failed"
    elif validation_status == "blocked":
        verdict_reason = "validation_command_blocked"
    elif validation_status == "passed" and not unchecked_items:
        verdict = "pass"
        verdict_reason = "validation_commands_passed"
        promotion_readiness = "review_ready"
    elif validation_status == "passed":
        verdict_reason = "validation_passed_with_unchecked_risk"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "report_kind": "evaluator_verdict",
        "job_id": job.get("job_id"),
        "job_ref": evidence.get("job_ref"),
        "harness_id": harness.get("id") or job.get("pack_id"),
        "domain_spec": dict(harness.get("domain_spec", {})) if isinstance(harness.get("domain_spec"), dict) else {},
        "evaluator_contract": evaluator_contract,
        "candidate_lineage": dict(harness.get("candidate_lineage", {})) if isinstance(harness.get("candidate_lineage"), dict) else {},
        "evidence_ref": evidence_ref,
        "validation_status": evidence.get("validation_status"),
        "validation_contract_status": evidence.get("validation_contract_status"),
        "trust_gate_status": evidence.get("trust_gate_status"),
        "verdict_contract": _as_string_list(evaluator_contract.get("verdicts")) or ["pass", "hold", "rollback"],
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "promotion_readiness": promotion_readiness,
        "rollback_reason": None,
        "metrics": {
            "validation_commands_count": len(validation_commands),
            "checked_artifacts_count": len(checked_artifacts),
            "unchecked_items_count": len(unchecked_items),
            "patch_applied": bool(evidence.get("patch_applied")),
            "source_code_modified": bool(evidence.get("source_code_modified")),
            "ai_provider_called": bool(evidence.get("ai_provider_called")),
        },
        "checked_artifacts": checked_artifacts,
        "unchecked_items": unchecked_items,
        "next_action": _next_validation_action(verdict, validation_status, unchecked_items),
    }


def _next_validation_action(verdict: str, validation_status: str, unchecked_items: list[str]) -> str:
    if verdict == "pass":
        return "Review the pass verdict before promotion; Cambrian does not auto-promote."
    if validation_status == "passed" and unchecked_items:
        return "Validation commands passed, but unchecked risk remains; review the listed items before completion."
    if validation_status == "failed":
        return "Inspect failed validation command output before accepting or applying any patch."
    if validation_status == "blocked":
        return "Run a safer validation command manually or adjust the approved validation command list."
    return "Run the listed validation commands manually, then record job completion outcome."


def _custom_outcome_evaluator_verdict(
    job: dict[str, Any],
    harness: dict[str, Any],
    validation_evidence: dict[str, Any],
    validation_ref: str | None,
    outcome_payload: dict[str, Any],
    outcome_ref: str,
) -> dict[str, Any]:
    manual_outcome = str(outcome_payload.get("outcome") or "")
    validation_commands = _as_string_list(outcome_payload.get("validation_commands"))
    checked_artifacts = _as_string_list(outcome_payload.get("checked_artifacts"))
    unchecked_items = _as_string_list(outcome_payload.get("unchecked_items"))
    evaluator_contract = dict(harness.get("evaluator_contract", {})) if isinstance(harness.get("evaluator_contract"), dict) else {}
    has_validation_evidence = bool(validation_ref)
    validation_status = str(validation_evidence.get("validation_status") or "")
    verdict, verdict_reason, rollback_reason = _outcome_verdict_from_evidence(
        manual_outcome=manual_outcome,
        validation_status=validation_status,
        has_validation_evidence=has_validation_evidence,
        unchecked_items=unchecked_items,
    )
    promotion_readiness = "review_ready" if verdict == "pass" else "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "report_kind": "evaluator_verdict",
        "job_id": job.get("job_id"),
        "job_ref": outcome_payload.get("job_ref"),
        "harness_id": harness.get("id") or outcome_payload.get("harness_id") or job.get("pack_id"),
        "domain_spec": dict(harness.get("domain_spec", {})) if isinstance(harness.get("domain_spec"), dict) else {},
        "evaluator_contract": evaluator_contract,
        "candidate_lineage": dict(harness.get("candidate_lineage", {})) if isinstance(harness.get("candidate_lineage"), dict) else {},
        "evidence_ref": validation_ref,
        "outcome_ref": outcome_ref,
        "validation_status": validation_evidence.get("validation_status"),
        "validation_contract_status": outcome_payload.get("validation_contract_status"),
        "trust_gate_status": outcome_payload.get("trust_gate_status"),
        "manual_outcome": outcome_payload.get("outcome"),
        "manual_notes_present": bool(str(outcome_payload.get("notes") or "").strip()),
        "verdict_contract": _as_string_list(evaluator_contract.get("verdicts")) or ["pass", "hold", "rollback"],
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "promotion_readiness": promotion_readiness,
        "rollback_reason": rollback_reason,
        "metrics": {
            "validation_evidence_present": has_validation_evidence,
            "validation_commands_count": len(validation_commands),
            "checked_artifacts_count": len(checked_artifacts),
            "unchecked_items_count": len(unchecked_items),
            "patch_applied": bool(outcome_payload.get("patch_applied_by_cambrian")),
            "source_code_modified": bool(outcome_payload.get("source_code_modified_by_cambrian")),
            "ai_provider_called": bool(outcome_payload.get("ai_provider_called_by_cambrian")),
        },
        "checked_artifacts": checked_artifacts,
        "unchecked_items": unchecked_items,
        "next_action": _next_action_for_verdict(verdict),
}


def _outcome_verdict_from_evidence(
    *,
    manual_outcome: str,
    validation_status: str,
    has_validation_evidence: bool,
    unchecked_items: list[str],
) -> tuple[str, str, str | None]:
    if manual_outcome in {"failed", "rejected"}:
        return "rollback", f"manual_outcome_{manual_outcome}", f"manual outcome recorded as {manual_outcome}"
    if validation_status == "failed":
        return "rollback", "validation_command_failed", "validation evidence recorded failed commands"
    if manual_outcome == "success":
        if not has_validation_evidence:
            return "hold", "manual_outcome_success_without_validation_evidence", None
        if validation_status != "passed":
            return "hold", f"manual_outcome_success_without_passed_validation_{validation_status or 'unknown'}", None
        if unchecked_items:
            return "hold", "manual_outcome_success_with_unchecked_risk_review_required", None
        return "pass", "manual_outcome_success_with_verified_evidence", None
    return "hold", f"manual_outcome_{manual_outcome or 'unknown'}", None


def _manual_outcome_verdict(outcome: str) -> tuple[str, str, str | None]:
    if outcome == "success":
        return "pass", "manual_outcome_success", None
    if outcome in {"failed", "rejected"}:
        return "rollback", f"manual_outcome_{outcome}", f"manual outcome recorded as {outcome}"
    return "hold", f"manual_outcome_{outcome or 'unknown'}", None


def _next_action_for_verdict(verdict: str) -> str:
    if verdict == "pass":
        return "Review the pass verdict before any promotion; Cambrian does not auto-promote."
    if verdict == "rollback":
        return "Keep the candidate out of promotion and inspect rollback or rejection notes."
    return "Keep the candidate on hold until validation evidence is stronger."


def _latest_custom_validation_evidence(root: Path, job_id: str) -> tuple[dict[str, Any], str | None]:
    evidence_dir = default_custom_validation_evidence_dir(root)
    direct = evidence_dir / f"{_slug(job_id, 'job')}.yaml"
    candidates = [direct] if direct.exists() else []
    if evidence_dir.exists():
        candidates.extend(sorted(evidence_dir.glob("*.yaml"), reverse=True))
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            payload = _load_yaml(resolved)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        if str(payload.get("job_id") or "") == job_id:
            return payload, _relative(resolved, root)
    return {}, None


def _append_custom_outcome(root: Path, outcome_payload: dict[str, Any]) -> Path:
    path = default_custom_outcomes_path(root)
    payload = _load_yaml(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "outcomes": []}
    outcomes = payload.get("outcomes", [])
    if not isinstance(outcomes, list):
        outcomes = []
    job_id = str(outcome_payload.get("job_id") or "")
    outcomes = [item for item in outcomes if not (isinstance(item, dict) and str(item.get("job_id") or "") == job_id)]
    outcomes.append(outcome_payload)
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["outcomes"] = outcomes
    return _save_yaml(path, payload)


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


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _load_or_scan_profile(root: Path) -> Any:
    path = default_project_profile_path(root)
    if path.exists():
        return ProjectHarnessProfileStore().load(path)
    profile = ProjectHarnessScanner().scan(root)
    ProjectHarnessProfileStore().save(profile, path)
    return profile


def _ensure_project_mode_baseline(root: Path, plan: dict[str, Any]) -> tuple[list[Path], list[str]]:
    """Custom harness install must leave project status directly usable."""
    from engine.project_mode import ProjectInitializer

    project = dict(plan.get("project", {}) if isinstance(plan.get("project"), dict) else {})
    validation = dict(plan.get("validation", {}) if isinstance(plan.get("validation"), dict) else {})
    commands = validation.get("test_commands", [])
    test_command = ""
    if isinstance(commands, list) and commands:
        test_command = str(commands[0] or "").strip()
    project_type = str(project.get("language") or "").strip() or None
    result = ProjectInitializer().init(root, project_type=project_type, test_cmd=test_command)
    cambrian_dir = root / ".cambrian"
    files = [
        cambrian_dir / file_name
        for file_name in ProjectInitializer.CONFIG_FILES
        if (cambrian_dir / file_name).exists()
    ]
    warnings = [str(item) for item in getattr(result, "warnings", []) if item]
    if result.status == "blocked":
        warnings.append("Project mode baseline already exists; custom harness install preserved it.")
    return files, warnings


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
    domains = _product_identity_domains(profile)
    goal = str(answers.get("primary_goal") or "").lower()
    identity_text = " ".join(
        [
            goal,
            " ".join(_as_string_list(answers.get("agent_roles"))),
            " ".join(_as_string_list(answers.get("important_paths"))),
        ]
    )
    suffixes: list[str] = []
    if any(token in identity_text for token in ["mission", "24h", "24-hour", "company", "evidence envelope", "outcome sync"]):
        suffixes.append("mission-company")
    if "auth" in domains or "인증" in goal or "login" in goal:
        suffixes.append("auth")
    if "예약" in goal or "reservation" in goal or "booking" in goal:
        suffixes.append("reservation")
    if "mission-company" in suffixes:
        suffixes = ["mission-company"]
    if not suffixes:
        suffixes.extend(domains[:2])
    suffix = "-".join(_slug(item, "work") for item in suffixes if item) or "work"
    return f"custom-{base}-{suffix}"


def _product_identity_domains(profile: dict[str, Any]) -> list[str]:
    non_product_domains = {"tests", "api"}
    confidence = profile.get("domain_confidence", {}) if isinstance(profile.get("domain_confidence"), dict) else {}
    candidates = confidence.get("candidates", {}) if isinstance(confidence.get("candidates"), dict) else {}
    domains: list[str] = []
    if candidates:
        for level in ["confirmed", "suspected"]:
            for domain, candidate in candidates.items():
                domain_key = str(domain).lower()
                if domain_key in non_product_domains:
                    continue
                if isinstance(candidate, dict) and str(candidate.get("confidence") or "") == level:
                    domains.append(domain_key)
    else:
        domains.extend(str(item).lower() for item in profile.get("domains", []) if item)
    return _dedupe([domain for domain in domains if domain not in non_product_domains])


def _agent_specs(answers: dict[str, Any], profile: dict[str, Any] | None = None) -> list[dict[str, str]]:
    raw_roles = _as_string_list(answers.get("agent_roles"))
    if raw_roles:
        try:
            from engine.project_harness_engineering import _looks_like_bootstrap_role_scaffold

            if not _looks_like_bootstrap_role_scaffold(raw_roles, _product_identity_domains(profile or {})):
                return [{"id": f"custom-agent-{index}", "role": role} for index, role in enumerate(raw_roles, start=1)]
        except Exception:
            return [{"id": f"custom-agent-{index}", "role": role} for index, role in enumerate(raw_roles, start=1)]
    if isinstance(profile, dict):
        try:
            from engine.project_harness_engineering import _agent_candidates

            project_fit_agents = _agent_candidates(profile, answers)
            if project_fit_agents:
                return project_fit_agents
        except Exception:
            pass
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


def _normalize_change_policy(value: Any) -> str:
    raw = " ".join(_as_string_list(value)) if isinstance(value, (list, tuple, set)) else str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower().replace("-", "_")
    compact = lowered.replace(" ", "").replace("\t", "")
    proposal_tokens = [
        "proposal_only",
        "proposalonly",
        "patch_proposal_only",
        "read_only",
        "readonly",
        "no_auto_apply",
        "noautomaticpatchapply",
        "noautomaticsourcemutation",
        "do_not_apply",
        "do_not_edit",
        "suggest_only",
        "제안만",
        "제안까지만",
        "수정 제안",
        "패치 제안",
        "자동 적용 금지",
        "자동수정 금지",
        "자동 수정 금지",
        "직접 적용 금지",
        "적용 금지",
        "승인 전 적용 금지",
        "코드 변경하지",
        "읽기 전용",
    ]
    if any(token in lowered or token in compact for token in proposal_tokens):
        return "proposal_only"
    manual_tokens = [
        "manual_confirm",
        "manualconfirm",
        "confirm_before_apply",
        "approval_required",
        "수동 승인",
        "승인 후 적용",
        "확인 후 적용",
        "허락 후 적용",
        "승인받고",
    ]
    if any(token in lowered or token in compact for token in manual_tokens):
        return "manual_confirm"
    auto_tokens = ["auto_apply", "autoapply", "automatic_apply", "자동 적용", "바로 적용", "자동수정", "자동 수정"]
    if any(token in lowered or token in compact for token in auto_tokens):
        return "manual_confirm"
    return raw


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


def _profile_important_paths(profile: dict[str, Any]) -> list[str]:
    paths = profile.get("detected_paths", {}) if isinstance(profile.get("detected_paths"), dict) else {}
    confidence = profile.get("domain_confidence", {}) if isinstance(profile.get("domain_confidence"), dict) else {}
    candidates = confidence.get("candidates", {}) if isinstance(confidence.get("candidates"), dict) else {}
    if candidates:
        domains: list[str] = []
        for level in ["confirmed", "suspected"]:
            for domain, candidate in candidates.items():
                if isinstance(candidate, dict) and str(candidate.get("confidence") or "") == level:
                    domains.append(str(domain))
        selected_by_domain = _profile_paths_for_domains(paths, domains)
        identity_refs = [
            ref
            for domain in domains
            for ref in _as_string_list(candidates.get(domain, {}).get("evidence") if isinstance(candidates.get(domain), dict) else [])
        ]
        selected = [*selected_by_domain, *identity_refs]
        return _dedupe(selected)[:8]
    selected: list[str] = []
    for key in ["webhook", "suppression", "send", "pipeline", "outbound", "scoring", "supabase", "migration", "customer", "auth", "login", "tests"]:
        selected.extend(_as_string_list(paths.get(key)))
    result: list[str] = []
    seen: set[str] = set()
    for path in selected:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result[:8]


def _profile_paths_for_domains(paths: dict[str, Any], domains: list[str]) -> list[str]:
    """confidence가 weak가 아닌 도메인의 scan 경로만 important path 후보로 고른다."""
    buckets = {
        "auth": ["auth", "login"],
        "login": ["login"],
        "webhook": ["webhook"],
        "suppression": ["suppression"],
        "send_pipeline": ["send", "pipeline"],
        "outbound": ["outbound"],
        "scoring": ["scoring"],
        "supabase": ["supabase"],
        "customer": ["customer"],
        "tests": ["tests"],
        "api": ["typescript", "python"],
    }
    selected: list[str] = []
    for domain in domains:
        for bucket in buckets.get(domain, []):
            selected.extend(_as_string_list(paths.get(bucket)))
    return _dedupe(selected)


def _domain_spec(
    root: Path,
    profile: dict[str, Any],
    answers: dict[str, Any],
    test_commands: list[str],
    success_criteria: list[str],
    codebase_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    important_paths = _as_string_list(answers.get("important_paths")) or _profile_important_paths(profile)
    allowed = _as_string_list(answers.get("allowed_scope")) or important_paths
    forbidden = _as_string_list(answers.get("forbidden_scope"))
    evidence = codebase_evidence if isinstance(codebase_evidence, dict) else {}
    return {
        "domain_name": _slug(root.name, "project"),
        "task_description": str(answers.get("primary_goal") or "").strip(),
        "project_ref": ".",
        "language": profile.get("language") or "unknown",
        "test_framework": profile.get("test_framework") or "unknown",
        "codebase_evidence_status": evidence.get("status"),
        "domain_confidence": dict(evidence.get("domain_confidence", {})) if isinstance(evidence.get("domain_confidence"), dict) else {},
        "domain_evidence": dict(evidence.get("domain_evidence", {})) if isinstance(evidence.get("domain_evidence"), dict) else {},
        "weak_domain_evidence": dict(evidence.get("weak_domain_evidence", {})) if isinstance(evidence.get("weak_domain_evidence"), dict) else {},
        "test_framework_evidence": dict(evidence.get("test_framework_evidence", {})) if isinstance(evidence.get("test_framework_evidence"), dict) else {},
        "validation_command_evidence": dict(evidence.get("validation_command_evidence", {})) if isinstance(evidence.get("validation_command_evidence"), dict) else {},
        "risk_boundaries": dict(evidence.get("risk_boundaries", {})) if isinstance(evidence.get("risk_boundaries"), dict) else {},
        "allowed_write_paths": allowed,
        "forbidden_paths": forbidden,
        "validation_commands": test_commands,
        "pass_criteria": {
            "success_criteria": success_criteria,
            "max_regressions": 0,
            "auto_apply": False,
            "requires_codebase_evidence": True,
        },
        "evaluator": {
            "kind": "local_validation",
            "verdict_contract": ["pass", "hold", "rollback"],
        },
        "execution_policy": {
            "sandbox": "workspace",
            "timeout_sec": 120,
            "approval_policy": "explicit",
            "change_policy": _normalize_change_policy(answers.get("change_policy")) or "proposal_only",
            "external_transfer": "explicit_approval_required",
            "provider_api_call": False,
            "auto_apply": False,
        },
    }


def _evaluator_contract(test_commands: list[str], success_criteria: list[str]) -> dict[str, Any]:
    return {
        "kind": "local_validation",
        "validation_commands": test_commands,
        "judge_rubric_ref": ".cambrian/harness/judge_rubric.md",
        "proof_gate": "validation commands and success criteria must be recorded before promotion",
        "success_criteria": success_criteria,
        "evidence_required": [
            "codebase_evidence.existing_important_paths",
            "codebase_evidence.test_framework_evidence",
            "codebase_evidence.risk_boundaries",
        ],
        "verdicts": ["pass", "hold", "rollback"],
    }


def _company_blueprint_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    codebase_evidence = plan.get("codebase_evidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}
    domain_confidence = codebase_evidence.get("domain_confidence", {}) if isinstance(codebase_evidence.get("domain_confidence"), dict) else {}
    project_discussion_layer = (
        plan.get("project_discussion_layer", {}) if isinstance(plan.get("project_discussion_layer"), dict) else {}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "blueprint_id": f"company-blueprint-{_slug(str(plan.get('harness_id') or 'custom-harness'), 'harness')}",
        "compiler_version": "company_os_compiler_v1",
        "harness_id": plan.get("harness_id"),
        "product_position": {
            "cambrian_os": "core",
            "auto_development": "execution_layer",
            "marketplace": "distribution_layer",
        },
        "project_understanding_kernel": {
            "evidence_graph": dict(codebase_evidence.get("evidence_graph", {}) if isinstance(codebase_evidence.get("evidence_graph"), dict) else {}),
            "evidence_status": codebase_evidence.get("status"),
            "confirmed_domains": _as_string_list(domain_confidence.get("confirmed")),
            "suspected_domains": _as_string_list(domain_confidence.get("suspected")),
            "weak_domains": _as_string_list(domain_confidence.get("weak")),
            "noise_policy": "weak domains stay out of the company core until evidence improves",
        },
        "company_compiler": {
            "source": "project evidence graph plus interview answers",
            "outputs": [
                "company_blueprint",
                "harness_contract",
                "worker_contracts",
                "skill_contracts",
                "authority_profile",
                "evaluation_contract",
            ],
            "worker_contracts": [str(agent.get("id")) for agent in plan.get("agents", []) if isinstance(agent, dict) and agent.get("id")],
            "evaluation_contract": dict(plan.get("evaluator_contract", {}) if isinstance(plan.get("evaluator_contract"), dict) else {}),
        },
        "harness_os": {
            "identity": "project-local-ai-company-operating-system",
            "operating_cycle": [
                "project_understanding",
                "company_compilation",
                "project_discussion",
                "authority_gated_execution",
                "validation_evidence",
                "learning_relearning",
            ],
        },
        "project_discussion_layer": {
            "layer_id": project_discussion_layer.get("layer_id"),
            "status": project_discussion_layer.get("status"),
            "roles": sorted(
                [
                    str(role_id)
                    for role_id in (
                        project_discussion_layer.get("roles", {})
                        if isinstance(project_discussion_layer.get("roles"), dict)
                        else {}
                    )
                ]
            ),
            "document_contract": dict(
                project_discussion_layer.get("document_contract", {})
                if isinstance(project_discussion_layer.get("document_contract"), dict)
                else {}
            ),
        },
        "auto_development_layer": {
            "role": "execution feature on top of Cambrian OS",
            "execution_engines": ["Codex", "Claude", "Cursor", "GPT", "local model"],
            "mutation_default": "proposal_only",
        },
        "marketplace_boundary": {
            "role": "distribution layer owned by a separate platform project",
            "exportable_artifacts": [
                "company_blueprint",
                "harness_contract",
                "worker_contracts",
                "skill_contracts",
                "evaluation_contract",
                "proof_summary",
                "evolution_lineage",
            ],
            "sale_ready": False,
            "proof_claim_allowed": False,
        },
        "target_lift": {
            "pct": 30,
            "basis": [
                "project evidence context",
                "role responsibility",
                "authority gates",
                "validation evidence",
                "failure learning and relearning",
            ],
        },
    }


def _harness_os_contract_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    blueprint = plan.get("company_blueprint", {}) if isinstance(plan.get("company_blueprint"), dict) else {}
    policy = plan.get("policy", {}) if isinstance(plan.get("policy"), dict) else {}
    return {
        "contract_version": "company_os_v1",
        "identity": "Cambrian Company OS",
        "blueprint_id": blueprint.get("blueprint_id"),
        "goal": plan.get("goal"),
        "authority": {
            "change_mode": policy.get("change_mode") or "proposal_only",
            "auto_apply": False,
            "explicit_approval_required": True,
        },
        "required_contracts": [
            "goal",
            "roles",
            "permissions",
            "forbidden_actions",
            "validation_commands",
            "success_criteria",
            "failure_handling",
            "evidence_requirements",
            "learning_relearning_policy",
            "project_discussion_layer",
        ],
        "proof_boundary": {
            "proof_claim_allowed_without_runtime_evidence": False,
            "success_rate_claim_allowed_without_runtime_evidence": False,
        },
        "required_context_layers": [
            "project_discussion_layer",
            "company_loop_context",
            "context_intent_snapshot",
        ],
    }


def _relearning_policy_from_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    target = blueprint.get("target_lift", {}) if isinstance(blueprint.get("target_lift"), dict) else {}
    return {
        "mode": "review_before_promotion",
        "auto_promote": False,
        "auto_evolve": False,
        "target_lift_pct": int(target.get("pct") or 30),
        "rebuild_triggers": [
            "weak domain promoted to core",
            "agent without evidence path",
            "missing validation command",
            "reply evidence compliance incomplete",
            "repeated unchecked risk",
        ],
        "decisions": ["keep", "revise", "rebuild", "retire"],
    }


def _marketplace_boundary_from_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    boundary = blueprint.get("marketplace_boundary", {}) if isinstance(blueprint.get("marketplace_boundary"), dict) else {}
    return {
        "distribution_layer": "separate_project",
        "export_manifest_required": True,
        "exportable_artifacts": _as_string_list(boundary.get("exportable_artifacts")),
        "sale_ready": False,
        "proof_claim_allowed": False,
        "success_rate_claim_allowed": False,
        "public_listing_allowed": False,
        "import_policy": "local review and explicit install confirmation required",
    }


def _company_export_manifest(
    root: Path,
    plan: dict[str, Any],
    workforce_payload: dict[str, Any],
    agents: list[dict[str, Any]],
    skills: list[dict[str, Any]],
) -> dict[str, Any]:
    harness_id = str(plan.get("harness_id") or "custom-harness")
    blueprint = plan.get("company_blueprint", {}) if isinstance(plan.get("company_blueprint"), dict) else {}
    boundary = plan.get("marketplace_boundary", {}) if isinstance(plan.get("marketplace_boundary"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": f"company-export-{_slug(harness_id, 'harness')}",
        "generated_at": _now(),
        "harness_id": harness_id,
        "blueprint_id": blueprint.get("blueprint_id"),
        "boundary": {
            "distribution_layer": boundary.get("distribution_layer") or "separate_project",
            "sale_ready": False,
            "proof_claim_allowed": False,
            "success_rate_claim_allowed": False,
            "public_listing_allowed": False,
            "import_policy": boundary.get("import_policy") or "local review and explicit install confirmation required",
        },
        "exportable_artifacts": {
            "company_blueprint": ".cambrian/harness.yaml#company_blueprint",
            "harness_contract": ".cambrian/harness.yaml#harness_os_contract",
            "worker_contracts": ".cambrian/agents/*.yaml",
            "skill_contracts": ".cambrian/skills/*.yaml",
            "evaluation_contract": ".cambrian/harness.yaml#evaluator_contract",
            "project_discussion_layer": ".cambrian/company/discussion/agents.yaml",
            "proof_summary": ".cambrian/reports/latest_verdict.json",
            "evolution_lineage": ".cambrian/evidence/outcomes.yaml",
        },
        "installed_refs": {
            "harness": ".cambrian/harness.yaml",
            "workforce": ".cambrian/workforce.yaml",
            "agents": ".cambrian/agents.yaml",
            "validation": ".cambrian/validation.yaml",
            "plan": ".cambrian/plan.yaml",
        },
        "worker_count": len([agent for agent in agents if isinstance(agent, dict)]),
        "skill_count": len([skill for skill in skills if isinstance(skill, dict)]),
        "workforce_id": workforce_payload.get("id"),
        "source_project": root.name,
        "notes": [
            "This manifest is a local distribution boundary, not a public marketplace listing.",
            "Proof and sale readiness remain false until runtime evidence is reviewed.",
        ],
    }


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
        "status": "active",
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
        "domain_spec": dict(plan.get("domain_spec", {})) if isinstance(plan.get("domain_spec"), dict) else {},
        "codebase_evidence": dict(plan.get("codebase_evidence", {})) if isinstance(plan.get("codebase_evidence"), dict) else {},
        "evidence_card": dict(plan.get("codebase_evidence", {}).get("evidence_card", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}),
        "domain_confidence": dict(plan.get("codebase_evidence", {}).get("domain_confidence", {}) if isinstance(plan.get("codebase_evidence"), dict) else {}),
        "quality_gate": dict(plan.get("quality_gate", {})) if isinstance(plan.get("quality_gate"), dict) else {},
        "evaluator_contract": dict(plan.get("evaluator_contract", {})) if isinstance(plan.get("evaluator_contract"), dict) else {},
        "candidate_lineage": dict(plan.get("candidate_lineage", {})) if isinstance(plan.get("candidate_lineage"), dict) else {},
        "company_blueprint": dict(plan.get("company_blueprint", {})) if isinstance(plan.get("company_blueprint"), dict) else {},
        "harness_os_contract": dict(plan.get("harness_os_contract", {})) if isinstance(plan.get("harness_os_contract"), dict) else {},
        "relearning_policy": dict(plan.get("relearning_policy", {})) if isinstance(plan.get("relearning_policy"), dict) else {},
        "marketplace_boundary": dict(plan.get("marketplace_boundary", {})) if isinstance(plan.get("marketplace_boundary"), dict) else {},
        "project_discussion_layer": dict(plan.get("project_discussion_layer", {}))
        if isinstance(plan.get("project_discussion_layer"), dict)
        else {},
        "important_paths": list(plan.get("important_paths", []) if isinstance(plan.get("important_paths"), list) else []),
    }


def _lane_label(harness: dict[str, Any]) -> str:
    language = str(harness.get("language") or "custom").strip()
    framework = str(harness.get("test_framework") or "manual").strip()
    return f"{language} + {framework}"
