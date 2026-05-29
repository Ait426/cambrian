from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_harness_profile import ProjectHarnessProfileStore, ProjectHarnessScanner, default_project_profile_path
from engine.project_pack_install import SCHEMA_VERSION, _relative, _slug
from engine.project_company_layer import build_project_discussion_layer


CODEBASE_EVIDENCE_MIN_EXISTING_PATHS = 2
_ANSWER_KEYS = {
    "primary_goal",
    "test_command",
    "build_command",
    "change_policy",
    "forbidden_scope",
    "important_paths",
    "allowed_scope",
    "validation_standard",
    "agent_roles",
}


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
        errors.extend(_codebase_evidence_issues(candidate))
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
    design_id = f"harness-design-{_slug(root.name, 'project')}-{_date_stamp()}"
    forbidden = _as_string_list(answers.get("forbidden_scope"))
    important_paths = _normalize_path_refs(root, _as_string_list(answers.get("important_paths"))) or _normalize_path_refs(
        root,
        _profile_important_paths(profile_payload),
    )
    allowed_paths = _normalize_path_refs(root, _as_string_list(answers.get("allowed_scope"))) or important_paths
    test_commands = _as_string_list(answers.get("test_command"))
    build_commands = _as_string_list(answers.get("build_command"))
    change_policy = _normalize_change_policy(answers.get("change_policy"))
    profile_domains = _harness_relevant_domains(profile_payload, answers, important_paths)
    codebase_evidence = build_codebase_evidence(root, profile_payload, important_paths, [*test_commands, *build_commands])
    success_criteria = _as_string_list(answers.get("validation_standard"))
    agents = [_attach_codebase_evidence_contract(agent, codebase_evidence) for agent in _agent_candidates(profile_payload, answers)]
    skills = [
        _attach_codebase_evidence_contract(skill, codebase_evidence)
        for skill in _skill_candidates(profile_payload, harness_id, agents, important_paths, forbidden, test_commands)
    ]
    project_discussion_layer = build_project_discussion_layer(
        root,
        harness_id=harness_id,
        goal=str(answers.get("primary_goal") or "").strip(),
        codebase_evidence=codebase_evidence,
    )
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "design_id": design_id,
        "status": "candidate",
        "seed_preset": seed_preset,
        "project_profile": {
            "language": profile_payload.get("language"),
            "test_framework": profile_payload.get("test_framework"),
            "domains": profile_domains,
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
            "change_policy": change_policy,
            "codebase_evidence_status": codebase_evidence["status"],
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
            "evidence_required": [
                "codebase_evidence.status must be grounded before install",
                "test_framework_evidence must be recorded before validation command selection",
                "risk_boundaries must be checked before patch proposal",
            ],
        },
        "codebase_evidence": codebase_evidence,
        "domain_spec": _domain_spec(
            root=root,
            profile=profile_payload,
            answers=answers,
            allowed_paths=allowed_paths,
            forbidden=forbidden,
            test_commands=test_commands,
            build_commands=build_commands,
            success_criteria=success_criteria,
            codebase_evidence=codebase_evidence,
        ),
        "evaluator_contract": _evaluator_contract(test_commands, build_commands, success_criteria),
        "candidate_lineage": _candidate_lineage(design_id, harness_id, seed_preset),
        "execution_boundary": _execution_boundary(answers, allowed_paths, forbidden),
        "project_discussion_layer": project_discussion_layer,
        "generated_files_preview": [
            ".cambrian/harness.yaml",
            ".cambrian/workforce.yaml",
            ".cambrian/agents/*.yaml",
            ".cambrian/skills/*.yaml",
            ".cambrian/validation.yaml",
            ".cambrian/company/discussion/agents.yaml",
        ],
        "warnings": [],
        "errors": [],
        "next_command": "cambrian harness engineer review --json",
    }
    candidate["company_blueprint"] = _company_blueprint(
        design_id=design_id,
        harness_id=harness_id,
        profile=profile_payload,
        codebase_evidence=codebase_evidence,
        agents=agents,
        skills=skills,
        evaluator_contract=candidate["evaluator_contract"],
        project_discussion_layer=project_discussion_layer,
    )
    candidate["harness_os_contract"] = _harness_os_contract(candidate["company_blueprint"], candidate["execution_boundary"])
    candidate["relearning_policy"] = _relearning_policy(candidate["company_blueprint"])
    candidate["marketplace_boundary"] = _marketplace_boundary(candidate["company_blueprint"])
    candidate["quality_gate"] = build_harness_quality_gate(candidate)
    score = quality_score(candidate)
    candidate["quality_score"] = score
    candidate["confidence"] = _confidence(score)
    return candidate


def _company_blueprint(
    *,
    design_id: str,
    harness_id: str,
    profile: dict[str, Any],
    codebase_evidence: dict[str, Any],
    agents: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    evaluator_contract: dict[str, Any],
    project_discussion_layer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    domain_confidence = codebase_evidence.get("domain_confidence", {}) if isinstance(codebase_evidence.get("domain_confidence"), dict) else {}
    confirmed = _as_string_list(domain_confidence.get("confirmed"))
    suspected = _as_string_list(domain_confidence.get("suspected"))
    weak = _as_string_list(domain_confidence.get("weak"))
    agent_ids = [str(agent.get("id")) for agent in agents if isinstance(agent, dict) and agent.get("id")]
    skill_ids = [str(skill.get("id")) for skill in skills if isinstance(skill, dict) and skill.get("id")]
    discussion_layer = project_discussion_layer if isinstance(project_discussion_layer, dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "blueprint_id": f"company-blueprint-{_slug(harness_id, 'harness')}",
        "compiler_version": "company_os_compiler_v1",
        "source_design_id": design_id,
        "harness_id": harness_id,
        "product_position": {
            "cambrian_os": "core",
            "auto_development": "execution_layer",
            "marketplace": "distribution_layer",
        },
        "project_understanding_kernel": {
            "evidence_graph": dict(codebase_evidence.get("evidence_graph", {}) if isinstance(codebase_evidence.get("evidence_graph"), dict) else {}),
            "evidence_status": codebase_evidence.get("status"),
            "confirmed_domains": confirmed,
            "suspected_domains": suspected,
            "weak_domains": weak,
            "identity_rule": "weak domains and keyword-only evidence cannot define the company core",
        },
        "company_compiler": {
            "role_model": "project_fit_ai_company",
            "worker_contracts": agent_ids,
            "skill_contracts": skill_ids,
            "evaluation_contract": dict(evaluator_contract),
            "authority_profile": "explicit_approval_only",
        },
        "harness_os": {
            "goal": "install a project-local AI company operating contract",
            "required_contracts": [
                "goal",
                "roles",
                "authority",
                "forbidden_actions",
                "validation_commands",
                "success_criteria",
                "failure_handling",
                "evidence_requirements",
                "learning_relearning_policy",
                "project_discussion_layer",
            ],
        },
        "project_discussion_layer": {
            "layer_id": discussion_layer.get("layer_id"),
            "status": discussion_layer.get("status"),
            "roles": sorted(
                [
                    str(role_id)
                    for role_id in (
                        discussion_layer.get("roles", {}) if isinstance(discussion_layer.get("roles"), dict) else {}
                    )
                ]
            ),
            "document_contract": dict(
                discussion_layer.get("document_contract", {})
                if isinstance(discussion_layer.get("document_contract"), dict)
                else {}
            ),
        },
        "auto_development_layer": {
            "execution_engines": ["Codex", "Claude", "Cursor", "GPT", "local model"],
            "mode": "proposal_only_until_authorized",
            "bounded_by": ["authority_profile", "risk_boundaries", "evaluation_contract", "rollback_boundary"],
        },
        "marketplace_boundary": {
            "distribution_layer": "separate_project",
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
                "better project context",
                "clearer role responsibility",
                "explicit authority gates",
                "validation-gated proof",
                "failure learning and relearning",
            ],
        },
        "source_profile": {
            "language": profile.get("language"),
            "test_framework": profile.get("test_framework"),
            "domains": _as_string_list(profile.get("domains")),
        },
    }


def _harness_os_contract(company_blueprint: dict[str, Any], execution_boundary: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "company_os_v1",
        "identity": "Cambrian Company OS",
        "harness_identity": "project-local-ai-company-operating-system",
        "blueprint_id": company_blueprint.get("blueprint_id"),
        "authority": dict(execution_boundary),
        "operating_cycle": [
            "understand_project",
            "compile_company",
            "start_job",
            "bridge_execution_engine",
            "validate_with_evidence",
            "record_learning",
            "relearn_or_promote",
        ],
        "required_context_layers": [
            "project_discussion_layer",
            "company_loop_context",
            "context_intent_snapshot",
        ],
        "non_negotiables": [
            "no automatic source mutation",
            "no proof claim without validation evidence",
            "no marketplace sale readiness without runtime evidence",
            "no memory promotion without user review",
        ],
    }


def _relearning_policy(company_blueprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "review_before_promotion",
        "auto_promote": False,
        "auto_evolve": False,
        "rebuild_triggers": [
            "weak domain promoted to core",
            "missing validation command",
            "agent role without evidence paths",
            "reply evidence compliance incomplete",
            "repeated manual review gaps",
        ],
        "candidate_actions": ["keep", "revise", "rebuild", "retire"],
        "target_lift_pct": company_blueprint.get("target_lift", {}).get("pct", 30)
        if isinstance(company_blueprint.get("target_lift"), dict)
        else 30,
    }


def _marketplace_boundary(company_blueprint: dict[str, Any]) -> dict[str, Any]:
    boundary = company_blueprint.get("marketplace_boundary", {}) if isinstance(company_blueprint.get("marketplace_boundary"), dict) else {}
    return {
        "distribution_layer": boundary.get("distribution_layer") or "separate_project",
        "export_manifest_required": True,
        "exportable_artifacts": _as_string_list(boundary.get("exportable_artifacts")),
        "sale_ready": False,
        "proof_claim_allowed": False,
        "success_rate_claim_allowed": False,
        "public_listing_allowed": False,
        "import_policy": "local review and explicit install confirmation required",
    }


def build_harness_quality_gate(candidate: dict[str, Any]) -> dict[str, Any]:
    """하네스 설치 전 evidence-first 품질 게이트 결과를 만든다."""
    evidence = candidate.get("codebase_evidence", {}) if isinstance(candidate.get("codebase_evidence"), dict) else {}
    validation = candidate.get("validation", {}) if isinstance(candidate.get("validation"), dict) else {}
    workforce = candidate.get("workforce", {}) if isinstance(candidate.get("workforce"), dict) else {}
    agents = workforce.get("agents", []) if isinstance(workforce.get("agents"), list) else []
    domain_confidence = evidence.get("domain_confidence", {}) if isinstance(evidence.get("domain_confidence"), dict) else {}
    weak_domains = _as_string_list(domain_confidence.get("weak"))
    confirmed = _as_string_list(domain_confidence.get("confirmed"))
    suspected = _as_string_list(domain_confidence.get("suspected"))
    active_domains = _as_string_list(candidate.get("project_profile", {}).get("domains") if isinstance(candidate.get("project_profile"), dict) else [])
    product_domains = _product_identity_domains_from_confidence(domain_confidence, active_domains)
    checks = {
        "domain_evidence_present": bool(confirmed or suspected or evidence.get("domain_evidence")),
        "important_paths_exist": bool(_as_string_list(evidence.get("existing_important_paths"))) and not _as_string_list(evidence.get("missing_important_paths")),
        "validation_command_present": bool(_as_string_list(validation.get("test_commands"))),
        "risk_boundaries_present": isinstance(evidence.get("risk_boundaries"), dict) and bool(evidence.get("risk_boundaries")),
        "agents_not_duplicated": _agents_not_duplicated(agents),
        "agents_have_evidence_paths": _agents_have_evidence_paths(agents, evidence),
        "weak_domains_not_core": not set(active_domains).intersection(set(weak_domains)),
    }
    blocking = [name for name, ok in checks.items() if not ok and name != "agents_have_evidence_paths"]
    warnings: list[str] = []
    if not checks["agents_have_evidence_paths"]:
        warnings.append("some agents do not have explicit evidence paths yet")
    if weak_domains:
        warnings.append("weak domains kept as reference only: " + ", ".join(weak_domains[:5]))
    if not product_domains:
        warnings.append("product identity evidence is missing; tests/api evidence cannot define harness identity")
    test_evidence = evidence.get("test_framework_evidence", {}) if isinstance(evidence.get("test_framework_evidence"), dict) else {}
    validation_command_evidence = (
        evidence.get("validation_command_evidence", {}) if isinstance(evidence.get("validation_command_evidence"), dict) else {}
    )
    if str(test_evidence.get("status") or "") == "weak" and str(validation_command_evidence.get("status") or "") != "grounded":
        warnings.append("test framework evidence is weak; rely on explicit validation commands")
    status = "hold" if blocking else ("caution" if warnings else "pass")
    return {
        "status": status,
        "checks": checks,
        "blocking_issues": blocking,
        "warnings": _dedupe(warnings),
        "manual_review_required": status != "pass",
        "auto_evolve": False,
        "policy": "hold blocks install; caution allows install with manual review and no automatic evolution",
    }


def _product_identity_domains_from_confidence(domain_confidence: dict[str, Any], active_domains: list[str]) -> list[str]:
    non_product_domains = {"tests", "api"}
    candidates = domain_confidence.get("candidates", {}) if isinstance(domain_confidence.get("candidates"), dict) else {}
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
        domains.extend(str(item).lower() for item in active_domains if item)
    return _dedupe([domain for domain in domains if domain not in non_product_domains])


def _agents_not_duplicated(agents: list[Any]) -> bool:
    """agent id 중복 여부를 확인한다."""
    ids = [str(agent.get("id")) for agent in agents if isinstance(agent, dict) and agent.get("id")]
    return len(ids) == len(set(ids))


def _agents_have_evidence_paths(agents: list[Any], fallback_evidence: dict[str, Any]) -> bool:
    """각 agent가 evidence path를 갖는지 확인한다."""
    fallback_paths = _as_string_list(fallback_evidence.get("existing_important_paths"))
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        evidence = agent.get("codebase_evidence", {}) if isinstance(agent.get("codebase_evidence"), dict) else {}
        if not _as_string_list(evidence.get("paths")) and not fallback_paths:
            return False
    return True


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
        store = ProjectHarnessProfileStore()
        profile = store.load(profile_path)
        if not _profile_needs_rescan(Path(root).resolve(), profile.to_dict()):
            return profile
    profile = ProjectHarnessScanner().scan(root)
    ProjectHarnessProfileStore().save(profile, profile_path)
    return profile


def _profile_needs_rescan(root: Path, profile: dict[str, Any]) -> bool:
    detected_paths = profile.get("detected_paths", {}) if isinstance(profile.get("detected_paths"), dict) else {}
    candidates = profile.get("domain_confidence", {}).get("candidates", {}) if isinstance(profile.get("domain_confidence"), dict) else {}
    for domain in ["auth", "login", "hotel_site", "website", "agent_marketplace_platform"]:
        candidate = candidates.get(domain) if isinstance(candidates, dict) else None
        if not isinstance(candidate, dict):
            continue
        refs = _as_string_list(candidate.get("evidence"))
        if str(candidate.get("confidence") or "") == "confirmed" and "CLAUDE.md" in refs:
            return True
    looks_like_stage_pipeline = any(
        [
            (root / "core" / "ddmq.py").exists(),
            (root / "core" / "schema_registry.py").exists(),
            (root / "core" / "validators" / "schema_validator.py").exists(),
            any((root / "plugins").glob("stage*.py")) if (root / "plugins").exists() else False,
        ]
    )
    has_stage_buckets = any(_as_string_list(detected_paths.get(key)) for key in ["ddmq", "stage_pipeline", "schema_validation", "llm_api"])
    return looks_like_stage_pipeline and not has_stage_buckets


def _load_answers(root: Path) -> dict[str, Any]:
    path = root / ".cambrian" / "interview" / "answers.yaml"
    if not path.exists():
        raise FileNotFoundError("interview answers are missing")
    payload = _load_yaml(path)
    if isinstance(payload.get("answers"), dict):
        answers = payload.get("answers", {})
    elif any(key in payload for key in _ANSWER_KEYS):
        answers = {key: value for key, value in payload.items() if key in _ANSWER_KEYS}
    else:
        answers = {}
    if not isinstance(answers, dict):
        raise ValueError("answers.yaml must contain an answers mapping")
    return answers


def build_codebase_evidence(
    project_root: Path,
    profile: dict[str, Any],
    important_paths: list[str],
    validation_commands: list[str] | None = None,
) -> dict[str, Any]:
    """프로젝트 하네스가 실제 코드 증거에 기대는지 확인하는 요약을 만든다."""
    root = Path(project_root).resolve()
    important = _normalize_path_refs(root, important_paths)
    existing = _existing_relative_paths(root, important)
    missing = [path for path in important if path not in existing]
    detected_paths = profile.get("detected_paths", {}) if isinstance(profile.get("detected_paths"), dict) else {}
    domains = _effective_profile_domains(profile)
    domain_evidence = _domain_evidence(detected_paths, domains)
    domain_evidence.update(_identity_domain_evidence(profile, domains))
    weak_domain_evidence = _weak_domain_evidence(profile, detected_paths)
    test_framework_evidence = _test_framework_evidence(profile, detected_paths)
    validation_command_evidence = _validation_command_evidence(validation_commands or [], important, existing, test_framework_evidence)
    domain_confidence = _reinforce_domain_confidence_with_important_paths(
        dict(profile.get("domain_confidence", {}) if isinstance(profile.get("domain_confidence"), dict) else {}),
        domain_evidence,
        existing,
    )
    risk_boundaries = _risk_boundaries(profile, existing, important)
    profile_scan_refs = _dedupe(
        [
            item
            for values in detected_paths.values()
            if isinstance(values, list)
            for item in _as_string_list(values)
        ]
    )
    has_tests = bool(_as_string_list(detected_paths.get("tests")))
    has_source_paths = bool(_as_string_list(detected_paths.get("python")) or _as_string_list(detected_paths.get("typescript")))
    existing_count = len(existing)
    status = "grounded"
    if missing or existing_count < CODEBASE_EVIDENCE_MIN_EXISTING_PATHS or not domain_evidence:
        status = "weak"
    bootstrap_mode = "blank_project_identity_grounded" if status == "grounded" and not has_source_paths else None
    return {
        "status": status,
        "source": "project_scan_codebase_and_interview_answers",
        "bootstrap_mode": bootstrap_mode,
        "requires_code_review_before_install": status != "grounded" or bool(bootstrap_mode),
        "minimum_existing_paths": CODEBASE_EVIDENCE_MIN_EXISTING_PATHS,
        "existing_important_paths": existing,
        "missing_important_paths": missing,
        "profile_scan_ref_count": len(profile_scan_refs),
        "has_test_evidence": has_tests,
        "evidence_card": dict(profile.get("evidence_card", {})) if isinstance(profile.get("evidence_card"), dict) else {},
        "evidence_graph": dict(profile.get("evidence_graph", {})) if isinstance(profile.get("evidence_graph"), dict) else {},
        "domain_confidence": domain_confidence,
        "domain_evidence": domain_evidence,
        "weak_domain_evidence": weak_domain_evidence,
        "test_framework_evidence": test_framework_evidence,
        "validation_command_evidence": validation_command_evidence,
        "risk_boundaries": risk_boundaries,
        "contract_requirements": [
            "agents must cite codebase_evidence.existing_important_paths before proposing changes",
            "skills must check codebase_evidence.risk_boundaries before patch proposals",
            "validation must use codebase_evidence.validation_command_evidence when test framework evidence is weak",
        ],
        "notes": [
            "인터뷰 답변만으로 전용 하네스라고 판단하지 않는다.",
            "중요 경로는 실제 파일 존재와 project scan 증거로 다시 확인한다.",
        ],
    }


def _existing_relative_paths(root: Path, paths: list[str]) -> list[str]:
    existing: list[str] = []
    for path_ref in paths:
        normalized = _normalize_project_path_ref(root, path_ref)
        if not normalized:
            continue
        candidate = (root / normalized).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.exists():
            existing.append(normalized)
    return existing


def _effective_profile_domains(profile: dict[str, Any]) -> list[str]:
    """profile의 domain_confidence에서 weak가 아닌 도메인만 반환한다."""
    confidence = profile.get("domain_confidence", {}) if isinstance(profile.get("domain_confidence"), dict) else {}
    candidates = confidence.get("candidates", {}) if isinstance(confidence.get("candidates"), dict) else {}
    if not candidates:
        return [str(item).lower() for item in profile.get("domains", []) if item]
    domains: list[str] = []
    for level in ["confirmed", "suspected"]:
        for domain, candidate in candidates.items():
            if isinstance(candidate, dict) and str(candidate.get("confidence") or "") == level:
                domains.append(str(domain).lower())
    return _dedupe(domains)


def _identity_domain_evidence(profile: dict[str, Any], domains: list[str]) -> dict[str, list[str]]:
    """identity evidence만으로 확인된 도메인의 경로 evidence를 반환한다."""
    confidence = profile.get("domain_confidence", {}) if isinstance(profile.get("domain_confidence"), dict) else {}
    candidates = confidence.get("candidates", {}) if isinstance(confidence.get("candidates"), dict) else {}
    evidence: dict[str, list[str]] = {}
    for domain in domains:
        candidate = candidates.get(domain)
        if not isinstance(candidate, dict):
            continue
        refs = _as_string_list(candidate.get("evidence"))
        if refs:
            evidence[domain] = refs[:8]
    return evidence


def _weak_domain_evidence(profile: dict[str, Any], detected_paths: dict[str, Any]) -> dict[str, list[str]]:
    """weak 도메인의 근거를 참고용으로만 보관한다."""
    confidence = profile.get("domain_confidence", {}) if isinstance(profile.get("domain_confidence"), dict) else {}
    candidates = confidence.get("candidates", {}) if isinstance(confidence.get("candidates"), dict) else {}
    weak: dict[str, list[str]] = {}
    for domain, candidate in candidates.items():
        if isinstance(candidate, dict) and str(candidate.get("confidence") or "") == "weak":
            refs = _as_string_list(candidate.get("evidence"))
            if not refs:
                refs = _domain_evidence(detected_paths, [str(domain)]).get(str(domain), [])
            weak[str(domain)] = refs[:8]
    return weak


def _domain_evidence(detected_paths: dict[str, Any], domains: list[str]) -> dict[str, list[str]]:
    bucket_by_domain = {
        "website": ["typescript", "python"],
        "hotel_site": [],
        "auth": ["auth", "login"],
        "login": ["login"],
        "suppression": ["suppression"],
        "webhook": ["webhook"],
        "send_pipeline": ["send", "pipeline"],
        "outbound": ["outbound"],
        "scoring": ["scoring"],
        "supabase": ["supabase"],
        "customer": ["customer"],
        "ddmq": ["ddmq"],
        "stage_pipeline": ["stage_pipeline"],
        "schema_validation": ["schema_validation"],
        "llm_api": ["llm_api"],
        "pipeline_automation": ["pipeline"],
        "tests": ["tests"],
        "api": ["typescript", "python"],
        "agent_marketplace_platform": [],
        "cambrian_local_bridge": [],
    }
    evidence: dict[str, list[str]] = {}
    for domain in domains:
        refs: list[str] = []
        for bucket in bucket_by_domain.get(domain, [domain]):
            refs.extend(_as_string_list(detected_paths.get(bucket)))
        refs = _filter_domain_evidence_refs(domain, _dedupe(refs))[:8]
        if refs:
            evidence[domain] = refs
    return evidence


def _filter_domain_evidence_refs(domain: str, refs: list[str]) -> list[str]:
    if domain != "api":
        return refs
    selected = []
    for ref in refs:
        lowered = str(ref).lower().replace("\\", "/")
        if "/api/" in lowered or lowered.endswith("/api") or "routes" in lowered or "route." in lowered or "server" in lowered:
            selected.append(ref)
    return selected


def _test_framework_evidence(profile: dict[str, Any], detected_paths: dict[str, Any]) -> dict[str, Any]:
    framework = str(profile.get("test_framework") or "unknown")
    frameworks = _as_string_list(profile.get("test_frameworks")) or ([framework] if framework else [])
    config_paths = _dedupe(
        [
            *_as_string_list(detected_paths.get("package_json")),
            *_as_string_list(detected_paths.get("tsconfig")),
            *_as_string_list(detected_paths.get("jest_config")),
            *_as_string_list(detected_paths.get("config")),
        ]
    )[:12]
    test_paths = _dedupe(_as_string_list(detected_paths.get("tests")))[:12]
    status = "grounded" if framework != "unknown" and (config_paths or test_paths) else "weak"
    return {
        "status": status,
        "framework": framework,
        "frameworks": _dedupe(frameworks),
        "config_paths": config_paths,
        "test_paths": test_paths,
        "source": "project_scan_detected_paths",
    }


def _validation_command_evidence(
    commands: list[str],
    important_paths: list[str],
    existing_paths: list[str],
    test_framework_evidence: dict[str, Any],
) -> dict[str, Any]:
    commands = _dedupe([str(item) for item in commands if item])
    command_kinds: list[str] = []
    for command in commands:
        lowered = command.lower()
        if "tsc" in lowered:
            command_kinds.append("typecheck")
        elif "build" in lowered:
            command_kinds.append("build")
        elif "smoke" in lowered or "validation" in lowered or "tsx" in lowered:
            command_kinds.append("smoke")
        elif "test" in lowered or "pytest" in lowered or "jest" in lowered or "vitest" in lowered:
            command_kinds.append("test")
        else:
            command_kinds.append("custom")
    status = "grounded" if commands and (existing_paths or important_paths or test_framework_evidence.get("status") == "grounded") else "weak"
    return {
        "status": status,
        "commands": commands,
        "command_kinds": _dedupe(command_kinds),
        "runnable": bool(commands),
        "source": "interview_answers_and_project_scan",
        "framework_status": test_framework_evidence.get("status"),
        "manual_review_required": status != "grounded",
    }


def _reinforce_domain_confidence_with_important_paths(
    confidence: dict[str, Any],
    domain_evidence: dict[str, list[str]],
    existing_paths: list[str],
) -> dict[str, Any]:
    if not confidence:
        return confidence
    candidates = confidence.get("candidates", {}) if isinstance(confidence.get("candidates"), dict) else {}
    if not candidates:
        return confidence
    existing_set = {str(path) for path in existing_paths}
    updated_candidates: dict[str, Any] = {}
    for domain, candidate in candidates.items():
        if not isinstance(candidate, dict):
            updated_candidates[domain] = candidate
            continue
        item = dict(candidate)
        refs = _as_string_list(domain_evidence.get(str(domain), []))
        important_refs = [ref for ref in refs if ref in existing_set]
        if item.get("confidence") == "suspected" and important_refs:
            item["confidence"] = "confirmed"
            item["reason"] = f"{item.get('reason') or 'code evidence'}; promoted because interview important_paths include project code evidence"
            item["evidence"] = _dedupe([*_as_string_list(item.get("evidence")), *important_refs])[:12]
        updated_candidates[domain] = item
    confirmed = sorted([str(domain) for domain, item in updated_candidates.items() if isinstance(item, dict) and item.get("confidence") == "confirmed"])
    suspected = sorted([str(domain) for domain, item in updated_candidates.items() if isinstance(item, dict) and item.get("confidence") == "suspected"])
    weak = sorted([str(domain) for domain, item in updated_candidates.items() if isinstance(item, dict) and item.get("confidence") == "weak"])
    reinforced = dict(confidence)
    reinforced["candidates"] = updated_candidates
    reinforced["confirmed"] = confirmed
    reinforced["suspected"] = suspected
    reinforced["weak"] = weak
    return reinforced


def _risk_boundaries(profile: dict[str, Any], existing_paths: list[str], important_paths: list[str]) -> dict[str, Any]:
    domains = {str(item).lower() for item in profile.get("domains", []) if item}
    evidence_card = profile.get("evidence_card", {}) if isinstance(profile.get("evidence_card"), dict) else {}
    risk_evidence = evidence_card.get("risk_evidence", {}) if isinstance(evidence_card.get("risk_evidence"), dict) else {}
    external_systems: list[str] = []
    if "website" in domains:
        external_systems.append("public_web_surface")
    if "hotel_site" in domains:
        external_systems.append("hotel_booking_or_contact_flow")
    if "supabase" in domains:
        external_systems.append("supabase")
    if "webhook" in domains:
        external_systems.append("webhook_provider")
    if domains.intersection({"send_pipeline", "outbound", "suppression"}):
        external_systems.append("outbound_delivery")
    if domains.intersection({"ddmq", "stage_pipeline", "schema_validation", "pipeline_automation"}):
        external_systems.append("pipeline_runtime")
    if "llm_api" in domains:
        external_systems.append("llm_provider_api")
    if "api" in domains:
        external_systems.append("api_clients")
    return {
        "source": "project_scan_domains_and_existing_paths",
        "requires_manual_approval": True,
        "auto_apply": False,
        "source_mutation": False,
        "write_scope": existing_paths or important_paths,
        "external_systems": _dedupe(external_systems),
        "policy_refs": _as_string_list(risk_evidence.get("policy_refs")),
        "default_forbidden": [".env", "secrets", "git push", "applied migrations without approval"],
        "checks": [
            "forbidden path check",
            "external transfer approval check",
            "rollback concern check",
        ],
    }


def _attach_codebase_evidence_contract(item: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, dict) or not evidence:
        return item
    attached = dict(item)
    test_evidence = evidence.get("test_framework_evidence", {}) if isinstance(evidence.get("test_framework_evidence"), dict) else {}
    validation_command_evidence = (
        evidence.get("validation_command_evidence", {}) if isinstance(evidence.get("validation_command_evidence"), dict) else {}
    )
    risk_boundaries = evidence.get("risk_boundaries", {}) if isinstance(evidence.get("risk_boundaries"), dict) else {}
    attached["codebase_evidence"] = {
        "status": evidence.get("status"),
        "paths": _as_string_list(evidence.get("existing_important_paths"))[:8],
        "test_framework": test_evidence.get("framework"),
        "validation_commands": _as_string_list(validation_command_evidence.get("commands")),
        "risk_boundaries": risk_boundaries,
    }
    attached["inputs"] = _dedupe(
        [
            *_as_string_list(attached.get("inputs")),
            "codebase evidence",
            "risk boundaries",
            "test framework evidence",
        ]
    )
    validation = attached.get("validation", {})
    if not isinstance(validation, dict):
        validation = {}
    validation["required"] = _dedupe(
        [
            *_as_string_list(validation.get("required")),
            "codebase evidence path cited",
            "risk boundary checked",
        ]
    )
    attached["validation"] = validation
    return attached


def _answer_domain_hints(answers: dict[str, Any], important_paths: list[str]) -> list[str]:
    text = " ".join(
        [
            str(answers.get("primary_goal") or ""),
            " ".join(_as_string_list(answers.get("agent_roles"))),
            " ".join(important_paths),
        ]
    ).lower()
    hints: list[str] = []
    if "ddmq" in text:
        hints.append("ddmq")
    if any(token in text for token in ["stage1", "stage2", "stage3", "stage4", "stage5", "stage schema", "stage-schema", "stage_"]):
        hints.append("stage_pipeline")
    if any(token in text for token in ["schema_registry", "schema validator", "schema_validator", "schema validation", "stage schema"]):
        hints.append("schema_validation")
    if any(token in text for token in ["anthropic", "claude api", "llm api", "api error", "rate limit"]):
        hints.append("llm_api")
    if any(token in text for token in ["pipeline", "orchestrator", "queue", "retry"]):
        hints.append("pipeline_automation")
    if any(token in text for token in ["mission", "24h", "24-hour", "company", "evidence envelope", "outcome sync"]):
        hints.append("mission_company")
    return _dedupe(hints)


def _harness_relevant_domains(profile: dict[str, Any], answers: dict[str, Any], important_paths: list[str]) -> list[str]:
    answer_hints = _answer_domain_hints(answers, important_paths)
    scanned = _effective_profile_domains(profile) or [str(item).lower() for item in profile.get("domains", []) if item]
    if answer_hints:
        supporting = [domain for domain in scanned if domain in {"tests"}]
        return _dedupe([*answer_hints, *supporting])
    return _dedupe(scanned)


def _harness_id(root: Path, profile: dict[str, Any], answers: dict[str, Any]) -> str:
    base = _slug(root.name, "project")
    goal = str(answers.get("primary_goal") or "").lower()
    important_paths = _as_string_list(answers.get("important_paths"))
    answer_hints = _answer_domain_hints(answers, important_paths)
    domains = _harness_relevant_domains(profile, answers, important_paths)
    if not domains:
        domains = [str(item).lower() for item in profile.get("domains", []) if item]
    suffixes: list[str] = []
    if any(domain in domains for domain in ["ddmq", "stage_pipeline", "pipeline_automation"]):
        suffixes.append("pipeline")
    if "schema_validation" in domains:
        suffixes.append("schema")
    if "auth" in domains or "auth" in goal or "login" in goal or "인증" in goal:
        suffixes.append("auth")
    if "hotel_site" in domains or "hotel" in goal or "stay" in goal:
        suffixes.append("hotel-site")
    if "website" in domains or "homepage" in goal or "website" in goal:
        suffixes.append("website")
    if "reservation" in goal or "booking" in goal or "예약" in goal:
        suffixes.append("reservation")
    if answer_hints and any(hint in answer_hints for hint in ["ddmq", "stage_pipeline", "schema_validation", "pipeline_automation", "llm_api"]):
        suffixes = [suffix for suffix in suffixes if suffix not in {"auth", "hotel-site"}]
    if "mission_company" in answer_hints:
        suffixes = ["mission-company"]
    if not suffixes:
        suffixes = [domain for domain in domains if domain not in {"tests", "api"}][:2] or ["work"]
    return f"custom-{base}-{'-'.join(_slug(item, 'work') for item in suffixes)}"


def _agent_candidates(profile: dict[str, Any], answers: dict[str, Any] | None = None) -> list[dict[str, str]]:
    answers = answers or {}
    domains = _harness_relevant_domains(profile, answers, _as_string_list(answers.get("important_paths")))
    test_framework = str(profile.get("test_framework") or "").lower()
    custom_agents = _custom_role_agent_candidates(answers, domains)
    if custom_agents:
        return custom_agents[:5]
    agents: list[dict[str, str]] = []
    if any(domain in domains for domain in ["ddmq", "stage_pipeline", "schema_validation", "pipeline_automation", "llm_api"]):
        if "pipeline_automation" in domains and not any(domain in domains for domain in ["ddmq", "stage_pipeline", "schema_validation", "llm_api"]):
            agents.append({"id": "pipeline-orchestration-debugger", "role": "Reviews pipeline entrypoints, stage handoff, retry, and orchestration failure evidence."})
        if "ddmq" in domains:
            agents.append({"id": "ddmq-debugger", "role": "Reviews DDMQ queue flow, dead-letter behavior, and failed work item evidence."})
        if "llm_api" in domains:
            agents.append({"id": "anthropic-api-error-analyst", "role": "Reviews Anthropic/LLM API failure modes, rate limits, payload boundaries, and retry safety."})
        if "schema_validation" in domains or "stage_pipeline" in domains:
            agents.append({"id": "stage-schema-validator", "role": "Reviews stage input/output schema contracts and validation drift across the pipeline."})
    if "website" in domains:
        agents.append({"id": "web-experience-reviewer", "role": "Reviews the website structure, page flow, local execution path, and user-facing quality gates."})
    if "hotel_site" in domains:
        agents.append({"id": "hospitality-product-reviewer", "role": "Reviews hotel guest intent, room/booking content, trust signals, and stay-site conversion risks."})
    if "agent_marketplace_platform" in domains:
        agents.append({"id": "agent-platform-contract-reviewer", "role": "AI 에이전트 pack 생성/다운로드 계약과 Builder 흐름을 검토한다."})
    if "webhook" in domains:
        agents.append({"id": "webhook-signature-reviewer", "role": "Webhook HMAC/Svix 서명 검증 경로를 분석한다."})
    if any(domain in domains for domain in ["suppression", "send_pipeline", "outbound"]):
        agents.append({"id": "outbound-safety-reviewer", "role": "suppression 정책과 발송 파이프라인 안전 조건을 검토한다."})
    if "supabase" in domains:
        agents.append({"id": "supabase-schema-reviewer", "role": "Supabase migration, RLS, schema 변경 위험을 검토한다."})
    if any(domain in domains for domain in ["scoring", "customer"]):
        agents.append({"id": "scorecard-logic-reviewer", "role": "고객 선정과 scorecard 계산 흐름을 분석한다."})
    if not agents and "auth" in domains:
        agents.append({"id": "auth-flow-investigator", "role": "인증 흐름과 토큰 검증 경로를 분석한다."})
    if not agents:
        agents.append({"id": "root-cause-investigator", "role": "문제 재현 조건과 원인 후보를 분석한다."})
    if test_framework == "jest":
        agents.append({"id": "regression-test-guardian", "role": "Jest 테스트와 회귀 가능성을 검토한다."})
    elif test_framework == "pytest":
        agents.append({"id": "regression-test-guardian", "role": "pytest 테스트와 회귀 가능성을 검토한다."})
    else:
        agents.append({"id": "regression-test-guardian", "role": "프로젝트 테스트 명령과 회귀 가능성을 검토한다."})
    if "api" in domains and len(agents) < 4:
        agents.append({"id": "api-contract-reviewer", "role": "API 응답 형식과 실패 케이스를 검토한다."})
    agents.append({"id": "risk-reviewer", "role": "수정 제안의 부작용과 운영 리스크를 검토한다."})
    return agents[:5]


def _custom_role_agent_candidates(answers: dict[str, Any], domains: list[str]) -> list[dict[str, str]]:
    """명시적 agent_roles가 있고 도메인 전용 하네스가 약할 때 사용자 역할을 에이전트로 승격한다."""
    roles = _as_string_list(answers.get("agent_roles"))
    if not roles:
        return []
    if _looks_like_bootstrap_role_scaffold(roles, domains):
        return []
    agents: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, role in enumerate(roles, start=1):
        agent_id = _role_agent_id(role, index)
        if agent_id in seen:
            continue
        seen.add(agent_id)
        agents.append({"id": agent_id, "role": role})
    return agents[:5]


def _looks_like_bootstrap_role_scaffold(roles: list[str], domains: list[str]) -> bool:
    """Auto-draft roles should not override project-fit domain specialists."""
    domain_set = {str(domain or "").lower() for domain in domains}
    if not domain_set.intersection(
        {
            "agent_marketplace_platform",
            "ddmq",
            "hotel_site",
            "llm_api",
            "pipeline_automation",
            "schema_validation",
            "stage_pipeline",
            "website",
        }
    ):
        return False
    scaffold = {"context-manager", "execution-lead", "verification-owner"}
    scaffold.update(f"{domain}-reviewer" for domain in domain_set)
    normalized_roles = {str(role or "").strip().lower() for role in roles if str(role or "").strip()}
    return bool(normalized_roles) and normalized_roles.issubset(scaffold)


def _role_agent_id(role: str, index: int) -> str:
    """agent_roles 문장의 접두어를 안정적인 agent id로 바꾼다."""
    prefix = str(role or "").split(":", 1)[0].strip()
    if not prefix or len(prefix) > 64:
        prefix = f"custom-agent-{index}"
    return _slug(prefix, f"custom-agent-{index}")


def _skill_candidates(
    profile: dict[str, Any],
    harness_id: str,
    agents: list[dict[str, str]],
    important_paths: list[str],
    forbidden: list[str],
    test_commands: list[str],
) -> list[dict[str, Any]]:
    agent_ids = _dedupe([str(agent["id"]) for agent in agents if agent.get("id")])
    domains = _effective_profile_domains(profile) or [str(item).lower() for item in profile.get("domains", []) if item]
    skills: list[dict[str, Any]] = []
    if "ddmq-debugger" in agent_ids:
        skills.append(
            _skill(
                "debug-ddmq-queue-flow",
                harness_id,
                ["ddmq-debugger"],
                "Trace DDMQ queue inputs, dequeue behavior, failed items, retries, and dead-letter boundaries before proposing changes.",
                ["Find the DDMQ queue entrypoint and persistence boundary.", "Map failed item lifecycle from enqueue to terminal state.", "Connect each hypothesis to an existing important path and validation command."],
                ["DDMQ failure map", "queue boundary risks", "validation notes"],
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
                "Review Anthropic API call sites, payload contracts, rate-limit handling, and retry safety.",
                ["Identify the provider call path without exposing secrets.", "Classify transport, rate-limit, schema, and model-response failures.", "Check retry and fallback behavior against validation evidence."],
                ["Anthropic API failure taxonomy", "provider boundary risks", "retry safety notes"],
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
                "Validate stage input/output schemas, registry usage, and drift between stage plugins.",
                ["List stage files and their declared input/output contracts.", "Compare schema registry expectations with validator behavior.", "Flag contract drift before any implementation proposal."],
                ["stage schema contract map", "schema drift findings", "validator regression notes"],
                forbidden,
                important_paths,
            )
        )
    if "pipeline-orchestration-debugger" in agent_ids:
        skills.append(
            _skill(
                "trace-pipeline-orchestration",
                harness_id,
                ["pipeline-orchestration-debugger"],
                "Trace pipeline orchestration, stage handoff, retry, and terminal-state behavior.",
                ["Identify orchestration entrypoints and stage ordering.", "Map retry and error propagation rules.", "Tie proposed changes to existing paths and runnable validation commands."],
                ["pipeline orchestration map", "handoff risks", "retry behavior notes"],
                forbidden,
                important_paths,
            )
        )
    if "web-experience-reviewer" in agent_ids:
        skills.append(
            _skill(
                "shape-website-golden-path",
                harness_id,
                ["web-experience-reviewer"],
                "Review the site goal, first viewport, navigation, local run path, and evidence needed before implementation.",
                ["Confirm the product promise from identity docs.", "Map the expected visitor journey and page sections.", "Select a local validation command before claiming readiness."],
                ["website golden path notes", "page structure risks", "local validation notes"],
                forbidden,
                important_paths,
            )
        )
    if "hospitality-product-reviewer" in agent_ids:
        skills.append(
            _skill(
                "review-hospitality-site-contract",
                harness_id,
                ["hospitality-product-reviewer"],
                "Review hotel website requirements, guest trust signals, booking intent, and local PC handoff boundaries.",
                ["Extract hotel audience and stay intent from project docs.", "Check room, location, trust, contact, and booking assumptions.", "Flag any missing business facts as confirmation-required."],
                ["hotel site requirement notes", "guest conversion risks", "confirmation-required facts"],
                forbidden,
                important_paths,
            )
        )
    if "webhook-signature-reviewer" in agent_ids:
        skills.append(
            _skill(
                "trace-webhook-hmac",
                harness_id,
                ["webhook-signature-reviewer"],
                "Webhook HMAC/Svix 서명 검증 흐름을 추적한다.",
                ["서명 헤더와 raw body 처리 경로를 확인한다.", "재시도/실패 응답 영향을 정리한다.", "검증 명령과 연결한다."],
                ["webhook signature findings", "HMAC regression notes"],
                forbidden,
                important_paths,
            )
        )
    if "agent-platform-contract-reviewer" in agent_ids:
        skills.append(
            _skill(
                "review-agent-pack-contract",
                harness_id,
                ["agent-platform-contract-reviewer"],
                "AI 에이전트 pack 생성, 다운로드, Import 계약을 검토한다.",
                ["Builder 입력과 pack 출력 계약을 확인한다.", "다운로드/Import roundtrip 영향을 정리한다.", "Cambrian 런타임 결합도가 선택형으로 남는지 확인한다."],
                ["agent pack contract notes", "builder flow risk notes"],
                forbidden,
                important_paths,
            )
        )
    if "outbound-safety-reviewer" in agent_ids:
        if any(domain in domains for domain in ["suppression", "outbound"]):
            skills.append(
                _skill(
                    "review-suppression-policy",
                    harness_id,
                    ["outbound-safety-reviewer"],
                    "suppression, unsubscribe, 차단 수신자 정책을 검토한다.",
                    ["발송 전 차단 조건을 확인한다.", "정책 누락과 우회 가능성을 정리한다.", "운영 리스크를 evidence로 남긴다."],
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
                    ["발송 job 진입점을 찾는다.", "실패/재시도 경계를 확인한다.", "테스트 영향 범위를 정리한다."],
                    ["send pipeline notes", "delivery risk notes"],
                    forbidden,
                    important_paths,
                )
            )
    if "supabase-schema-reviewer" in agent_ids:
        skills.append(
            _skill(
                "review-supabase-migrations",
                harness_id,
                ["supabase-schema-reviewer"],
                "Supabase migration, RLS, schema 일관성을 검토한다.",
                ["적용된 migration 수정 여부를 확인한다.", "RLS/정책 변경 위험을 정리한다.", "DB 변경은 수동 승인 전 금지한다."],
                ["migration consistency notes", "Supabase risk notes"],
                forbidden,
                important_paths,
            )
        )
    if "scorecard-logic-reviewer" in agent_ids:
        skills.append(
            _skill(
                "trace-scorecard-logic",
                harness_id,
                ["scorecard-logic-reviewer"],
                "고객 선정과 scorecard 계산 로직을 추적한다.",
                ["점수 입력과 가중치 경로를 확인한다.", "선정 기준 변경 영향을 정리한다.", "검증 기준과 연결한다."],
                ["scorecard logic notes", "customer selection risk notes"],
                forbidden,
                important_paths,
            )
        )
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
                _analysis_agents(agent_ids),
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
            [_test_agent(agent_ids)],
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
            _dedupe([_primary_patch_agent(agent_ids), _risk_agent(agent_ids)]),
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
            [_risk_agent(agent_ids)],
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


def _primary_patch_agent(agent_ids: list[str]) -> str:
    for agent_id in [
        "web-experience-reviewer",
        "hospitality-product-reviewer",
        "webhook-signature-reviewer",
        "agent-platform-contract-reviewer",
        "outbound-safety-reviewer",
        "supabase-schema-reviewer",
        "scorecard-logic-reviewer",
        "auth-flow-investigator",
        "root-cause-investigator",
    ]:
        if agent_id in agent_ids:
            return agent_id
    return _primary_analysis_agent(agent_ids)


def _primary_analysis_agent(agent_ids: list[str]) -> str:
    """generic 분석 스킬을 배정할 실제 agent를 고른다."""
    for agent_id in agent_ids:
        lowered = agent_id.lower()
        if not any(token in lowered for token in ["risk", "test", "pytest", "regression"]):
            return agent_id
    return next(iter(agent_ids), "root-cause-investigator")


def _analysis_agents(agent_ids: list[str]) -> list[str]:
    agents = [
        agent_id
        for agent_id in agent_ids
        if not any(token in agent_id.lower() for token in ["risk", "boundary", "test", "pytest", "jest", "regression", "verification"])
    ]
    return agents or [_primary_analysis_agent(agent_ids)]


def _test_agent(agent_ids: list[str]) -> str:
    """검증 스킬을 배정할 agent를 고른다."""
    for agent_id in agent_ids:
        lowered = agent_id.lower()
        if any(token in lowered for token in ["test", "pytest", "regression", "qa"]):
            return agent_id
    for agent_id in agent_ids:
        lowered = agent_id.lower()
        if any(token in lowered for token in ["verification", "validator"]):
            return agent_id
    return "regression-test-guardian" if "regression-test-guardian" in agent_ids else next(iter(agent_ids), "regression-test-guardian")


def _risk_agent(agent_ids: list[str]) -> str:
    """리스크 검토 스킬을 배정할 agent를 고른다."""
    for agent_id in agent_ids:
        lowered = agent_id.lower()
        if "risk" in lowered or "boundary" in lowered:
            return agent_id
    return "risk-reviewer" if "risk-reviewer" in agent_ids else next(iter(agent_ids), "risk-reviewer")


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


def _domain_spec(
    root: Path,
    profile: dict[str, Any],
    answers: dict[str, Any],
    allowed_paths: list[str],
    forbidden: list[str],
    test_commands: list[str],
    build_commands: list[str],
    success_criteria: list[str],
    codebase_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    commands = _dedupe([*test_commands, *build_commands])
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
        "allowed_write_paths": allowed_paths,
        "forbidden_paths": forbidden,
        "validation_commands": commands,
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
        "execution_policy": _execution_boundary(answers, allowed_paths, forbidden),
    }


def _evaluator_contract(test_commands: list[str], build_commands: list[str], success_criteria: list[str]) -> dict[str, Any]:
    return {
        "kind": "local_validation",
        "validation_commands": _dedupe([*test_commands, *build_commands]),
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


def _candidate_lineage(design_id: str, harness_id: str, seed_preset: str | None) -> dict[str, Any]:
    return {
        "candidate_id": design_id,
        "harness_id": harness_id,
        "parent_candidate_id": None,
        "source": "interview_answers",
        "seed_preset": seed_preset,
        "generation_id": "initial",
        "mutation_summary": "initial project-specific harness candidate generated from scan and interview answers",
        "promotion_gate": "review, dry-run, validation evidence, and explicit install confirmation",
    }


def _execution_boundary(answers: dict[str, Any], allowed_paths: list[str], forbidden: list[str]) -> dict[str, Any]:
    return {
        "sandbox": "workspace",
        "timeout_sec": 120,
        "approval_policy": "explicit",
        "change_policy": _normalize_change_policy(answers.get("change_policy")),
        "allowed_write_paths": allowed_paths,
        "forbidden_paths": forbidden,
        "external_transfer": "explicit_approval_required",
        "provider_api_call": False,
        "auto_apply": False,
    }


def _contract_issues(candidate: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    domain_spec = candidate.get("domain_spec", {}) if isinstance(candidate.get("domain_spec"), dict) else {}
    evaluator = candidate.get("evaluator_contract", {}) if isinstance(candidate.get("evaluator_contract"), dict) else {}
    lineage = candidate.get("candidate_lineage", {}) if isinstance(candidate.get("candidate_lineage"), dict) else {}
    boundary = candidate.get("execution_boundary", {}) if isinstance(candidate.get("execution_boundary"), dict) else {}
    if not domain_spec:
        issues.append("domain_spec is missing")
    else:
        if not str(domain_spec.get("task_description") or "").strip():
            issues.append("domain_spec task_description is missing")
        if not _as_string_list(domain_spec.get("allowed_write_paths")):
            issues.append("domain_spec allowed_write_paths is missing")
        if not _as_string_list(domain_spec.get("validation_commands")):
            issues.append("domain_spec validation_commands is missing")
        if not isinstance(domain_spec.get("pass_criteria"), dict):
            issues.append("domain_spec pass_criteria is missing")
        if not isinstance(domain_spec.get("test_framework_evidence"), dict):
            issues.append("domain_spec test_framework_evidence is missing")
        if not isinstance(domain_spec.get("risk_boundaries"), dict):
            issues.append("domain_spec risk_boundaries is missing")
    if not evaluator:
        issues.append("evaluator_contract is missing")
    else:
        if not _as_string_list(evaluator.get("validation_commands")):
            issues.append("evaluator_contract validation_commands is missing")
        if not _as_string_list(evaluator.get("verdicts")):
            issues.append("evaluator_contract verdicts are missing")
        if not _as_string_list(evaluator.get("evidence_required")):
            issues.append("evaluator_contract evidence_required is missing")
    if not lineage:
        issues.append("candidate_lineage is missing")
    else:
        if not str(lineage.get("candidate_id") or "").strip():
            issues.append("candidate_lineage candidate_id is missing")
        if not str(lineage.get("generation_id") or "").strip():
            issues.append("candidate_lineage generation_id is missing")
    if not boundary:
        issues.append("execution_boundary is missing")
    else:
        if not str(boundary.get("sandbox") or "").strip():
            issues.append("execution_boundary sandbox is missing")
        if not boundary.get("timeout_sec"):
            issues.append("execution_boundary timeout_sec is missing")
        if str(boundary.get("approval_policy") or "") != "explicit":
            issues.append("execution_boundary approval_policy must be explicit")
    return issues


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
    issues.extend(_codebase_evidence_issues(candidate))
    issues.extend(_contract_issues(candidate))
    quality_gate = candidate.get("quality_gate", {}) if isinstance(candidate.get("quality_gate"), dict) else {}
    if str(quality_gate.get("status") or "") == "hold":
        issues.extend([f"quality_gate: {item}" for item in _as_string_list(quality_gate.get("blocking_issues"))])
    return issues, questions


def _codebase_evidence_issues(candidate: dict[str, Any]) -> list[str]:
    evidence = candidate.get("codebase_evidence", {}) if isinstance(candidate.get("codebase_evidence"), dict) else {}
    if not evidence:
        return ["codebase_evidence is missing"]
    issues: list[str] = []
    missing_paths = _as_string_list(evidence.get("missing_important_paths"))
    existing_paths = _as_string_list(evidence.get("existing_important_paths"))
    domain_evidence = evidence.get("domain_evidence", {})
    test_framework_evidence = evidence.get("test_framework_evidence", {})
    risk_boundaries = evidence.get("risk_boundaries", {})
    if missing_paths:
        issues.append("important_paths contain missing files: " + ", ".join(missing_paths[:5]))
    if len(existing_paths) < int(evidence.get("minimum_existing_paths") or CODEBASE_EVIDENCE_MIN_EXISTING_PATHS):
        issues.append("codebase_evidence requires at least 2 existing project paths")
    if not isinstance(domain_evidence, dict) or not domain_evidence:
        issues.append("codebase_evidence has no code-backed domain evidence")
    if not isinstance(test_framework_evidence, dict) or not test_framework_evidence:
        issues.append("codebase_evidence has no test framework evidence")
    if not isinstance(risk_boundaries, dict) or not risk_boundaries:
        issues.append("codebase_evidence has no risk boundary evidence")
    if str(evidence.get("status") or "") != "grounded":
        issues.append("codebase_evidence is not grounded")
    return _dedupe(issues)


def _warnings(candidate: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    harness = candidate.get("harness", {}) if isinstance(candidate.get("harness"), dict) else {}
    validation = candidate.get("validation", {}) if isinstance(candidate.get("validation"), dict) else {}
    evidence = candidate.get("codebase_evidence", {}) if isinstance(candidate.get("codebase_evidence"), dict) else {}
    if not _as_string_list(validation.get("build_commands")):
        warnings.append("build_command is missing")
    if not _as_string_list(harness.get("important_paths")):
        warnings.append("important_paths is missing")
    if not _as_string_list(harness.get("forbidden")):
        warnings.append("forbidden_scope is missing")
    domain_evidence = evidence.get("domain_evidence", {}) if isinstance(evidence.get("domain_evidence"), dict) else {}
    domain_keys = {str(key) for key in domain_evidence}
    if domain_keys == {"tests"}:
        warnings.append("domain evidence is validation-only; rely on interview roles and important paths")
    elif domain_keys and domain_keys.issubset({"auth", "login", "tests", "api"}) and domain_keys.intersection({"auth", "login"}):
        warnings.append("domain evidence is narrow; verify this is not an auth-biased harness")
    quality_gate = candidate.get("quality_gate", {}) if isinstance(candidate.get("quality_gate"), dict) else {}
    if str(quality_gate.get("status") or "") == "caution":
        warnings.extend([f"quality_gate: {item}" for item in _as_string_list(quality_gate.get("warnings"))])
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
    request_lower = str(request or "").lower()
    if any(token in request_lower for token in ["webhook", "hmac", "signature", "svix", "서명"]) and "webhook-signature-reviewer" in available:
        selected.append("webhook-signature-reviewer")
    if any(token in request_lower for token in ["suppression", "unsubscribe", "outbound", "send", "delivery", "campaign", "발송", "차단"]) and "outbound-safety-reviewer" in available:
        selected.append("outbound-safety-reviewer")
    if any(token in request_lower for token in ["supabase", "migration", "rls", "schema", "db", "마이그레이션"]) and "supabase-schema-reviewer" in available:
        selected.append("supabase-schema-reviewer")
    if any(token in request_lower for token in ["score", "scorecard", "scoring", "customer", "icp", "고객", "점수"]) and "scorecard-logic-reviewer" in available:
        selected.append("scorecard-logic-reviewer")
    if _looks_auth_request(request) and "auth-flow-investigator" in available:
        selected.append("auth-flow-investigator")
    for agent_id in ["regression-test-guardian", "risk-reviewer"]:
        if agent_id in available and agent_id not in selected:
            selected.append(agent_id)
    if not selected:
        selected = _candidate_default_agents(available)
    else:
        _append_candidate_agent_by_class(selected, available, "verification")
        _append_candidate_agent_by_class(selected, available, "risk_direction")
    return selected[: _candidate_dispatch_cap(candidate)]


def _candidate_default_agents(available: list[str]) -> list[str]:
    selected: list[str] = []
    for responsibility_class in ["domain_execution", "contract_execution", "context_analysis", "technical_review", "verification", "risk_direction"]:
        _append_candidate_agent_by_class(selected, available, responsibility_class)
    for agent_id in available:
        if agent_id not in selected:
            selected.append(agent_id)
        if len(selected) >= 3:
            break
    return selected


def _candidate_dispatch_cap(candidate: dict[str, Any]) -> int:
    evidence = candidate.get("codebase_evidence", {}) if isinstance(candidate.get("codebase_evidence"), dict) else {}
    confidence = evidence.get("domain_confidence", {}) if isinstance(evidence.get("domain_confidence"), dict) else {}
    active_domains = _as_string_list(candidate.get("project_profile", {}).get("domains") if isinstance(candidate.get("project_profile"), dict) else [])
    product_domains = _product_identity_domains_from_confidence(confidence, active_domains)
    risk = evidence.get("risk_boundaries", {}) if isinstance(evidence.get("risk_boundaries"), dict) else {}
    external_systems = _as_string_list(risk.get("external_systems"))
    signal_count = len(product_domains) + len(external_systems)
    if signal_count >= 5:
        return 6
    if signal_count >= 3:
        return 5
    return 4


def _append_candidate_agent_by_class(selected: list[str], available: list[str], responsibility_class: str) -> None:
    for agent_id in available:
        if agent_id not in selected and _candidate_agent_class(agent_id) == responsibility_class:
            selected.append(agent_id)
            return


def _candidate_agent_class(agent_id: str) -> str:
    lowered = str(agent_id or "").lower()
    if agent_id == "agent-platform-contract-reviewer":
        return "contract_execution"
    if agent_id == "root-cause-investigator":
        return "context_analysis"
    if any(token in lowered for token in ["test", "pytest", "jest", "regression", "verification", "guardian"]):
        return "verification"
    if any(token in lowered for token in ["risk", "boundary", "approval", "rollback"]):
        return "risk_direction"
    if any(token in lowered for token in ["api", "contract", "typescript", "web-input", "web", "route"]):
        return "technical_review"
    return "domain_execution"


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
    domains = _effective_profile_domains(profile)
    if domains:
        selected_by_domain = _domain_evidence(paths, domains)
        selected = [path for refs in selected_by_domain.values() for path in refs]
        identity_refs = _identity_domain_evidence(profile, domains)
        selected.extend(path for refs in identity_refs.values() for path in refs)
        return _dedupe(selected)[:8]
    selected: list[str] = []
    for key in [
        "ddmq",
        "stage_pipeline",
        "schema_validation",
        "llm_api",
        "webhook",
        "suppression",
        "send",
        "pipeline",
        "outbound",
        "scoring",
        "supabase",
        "migration",
        "customer",
        "auth",
        "login",
        "tests",
    ]:
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
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_as_string_list(item))
        return items
    text = str(value).strip()
    if not text:
        return []
    if "\n" not in text:
        item = _strip_yaml_list_marker(text)
        return [item] if item else []
    items = []
    for line in text.splitlines():
        item = _strip_yaml_list_marker(line)
        if item:
            items.append(item)
    return items


def _strip_yaml_list_marker(value: Any) -> str:
    text = str(value or "").strip()
    while text.startswith(("-", "*")):
        text = text[1:].strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"', "`"}:
        text = text[1:-1].strip()
    return text


def _normalize_path_refs(root: Path, paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for path_ref in paths:
        path = _normalize_project_path_ref(root, path_ref)
        if path:
            normalized.append(path)
    return _dedupe(normalized)


def _normalize_project_path_ref(root: Path, path_ref: Any) -> str | None:
    text = _strip_yaml_list_marker(path_ref).replace("\\", "/").strip()
    if not text:
        return None
    if "\n" in text:
        return None
    if text.startswith("file://"):
        text = text[len("file://") :].strip()
    if text.startswith("./"):
        text = text[2:]
    if text.startswith("/") and not (len(text) > 2 and text[1] == ":"):
        text = text.lstrip("/")
    parts = [part for part in text.split("/") if part and part != "."]
    if parts and parts[0].lower() == root.name.lower():
        text = "/".join(parts[1:])
    try:
        raw_path = Path(text)
        candidate = raw_path.resolve() if raw_path.is_absolute() else (root / text).resolve()
        rel = candidate.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return rel.as_posix()


def _normalize_change_policy(value: Any) -> str:
    raw = " ".join(_as_string_list(value)) if isinstance(value, (list, tuple, set)) else str(value or "").strip()
    if not raw:
        return ""
    lowered = raw.lower().replace("-", "_")
    compact = lowered.replace(" ", "").replace("\t", "")
    proposal_tokens = [
        "proposal_only",
        "proposalonly",
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
        "직접 적용 금지",
        "자동 적용 금지",
        "자동수정 금지",
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
    auto_tokens = ["auto_apply", "autoapply", "automatic_apply", "자동 적용", "바로 적용"]
    if any(token in lowered or token in compact for token in auto_tokens):
        return "auto_apply"
    return raw


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
