from __future__ import annotations

import tempfile
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_authority import append_authority_log, load_authority_profile
from engine.project_pack_install import SCHEMA_VERSION, _relative


STATE_ORDER = [
    "INIT",
    "PRODUCT_CHARTER",
    "BOARDROOM_PLANNING",
    "ARCHITECTURE_DECISION",
    "EXECUTION_PLAN",
    "IMPLEMENTATION",
    "VALIDATION",
    "REVIEW",
    "RELEASE_GATE",
    "EVOLUTION",
    "DONE",
    "NEXT_ITERATION",
]


def _explicit_next_goal_command() -> str:
    return 'cambrian auto next --goal "명시적 다음 제품 목표" --json'


def _next_goal_validation_error(goal_text: str) -> str | None:
    normalized = " ".join(str(goal_text or "").strip().lower().split())
    placeholder_goals = {
        "next product iteration",
        "next iteration",
        "next product goal",
        "explicit next product goal",
        "ship next iteration",
        "start next iteration",
        "start the next release iteration",
        "명시적 다음 제품 목표",
        "다음 제품 반복",
        "다음 반복",
        "다음 목표",
        "다음 단계",
        "새 목표",
    }
    if normalized in placeholder_goals:
        return "explicit next product goal is required"
    if normalized.startswith("<") and normalized.endswith(">"):
        return "explicit next product goal is required"
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


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
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _archive_active_auto_iteration(root: Path, archive_dir: Path) -> list[str]:
    auto_dir = default_auto_dir(root)
    archived: list[str] = []
    for file_name in ["mission.yaml", "plan.yaml", "report.yaml", "execution_log.yaml"]:
        source = auto_dir / file_name
        if source.exists():
            target = archive_dir / file_name
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            archived.append(_relative(target, root))
    for dir_name in ["boardroom", "decisions", "tasks", "results", "rejections", "corrections", "cycles", "external_results", "release_gate"]:
        source_dir = auto_dir / dir_name
        if source_dir.exists():
            target_dir = archive_dir / dir_name
            if target_dir.exists():
                target_dir = archive_dir / f"{dir_name}-{_stamp()}"
            shutil.move(str(source_dir), str(target_dir))
            archived.append(_relative(target_dir, root))
    return archived


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def default_auto_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "auto"


def default_auto_state_path(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "state.yaml"


def default_auto_organization_path(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "organization.yaml"


def default_auto_boardroom_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "boardroom"


def default_auto_decisions_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "decisions"


def default_auto_plan_path(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "plan.yaml"


def default_auto_execution_log_path(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "execution_log.yaml"


def default_auto_report_path(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "report.yaml"


def default_auto_mission_path(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "mission.yaml"


def default_auto_tasks_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "tasks"


def default_auto_results_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "results"


def default_auto_rejections_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "rejections"


def default_auto_corrections_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "corrections"


def default_auto_cycles_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "cycles"


def default_auto_cycle_state_path(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "cycle_state.yaml"


def default_auto_release_gate_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "release_gate"


def default_auto_iterations_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "iterations"


def default_skill_knowledge_ledger_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "skills" / "knowledge_ledger.yaml"


def default_worker_performance_ledger_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "workers" / "performance_ledger.yaml"


def default_relearning_review_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "relearning" / "review.yaml"


def default_company_snapshots_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "company" / "snapshots"


def default_input_requests_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "input_requests"


def default_input_answers_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "input_answers"


def default_input_deferred_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "input_deferred"


def init_auto_mode(project_root: Path, goal: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    goal_text = str(goal or "").strip()
    if not goal_text:
        return _blocked("goal is required", 'cambrian auto init --goal "제품 목표" --json')
    authority = load_authority_profile(root)
    state = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "updated_at": _now(),
        "state": "PRODUCT_CHARTER",
        "previous_state": "INIT",
        "goal": goal_text,
        "paused": False,
        "authority_mode": authority["mode"],
        "state_machine": STATE_ORDER,
        "next_command": "cambrian auto boardroom --json",
    }
    organization = _default_organization(authority["mode"])
    mission = _initial_mission_state(goal_text, str(authority["mode"]))
    state_path = _save_yaml(default_auto_state_path(root), state)
    organization_path = _save_yaml(default_auto_organization_path(root), organization)
    mission_path = _save_yaml(default_auto_mission_path(root), mission)
    append_authority_log(
        root,
        command=f"cambrian auto init --goal {goal_text}",
        mode=str(authority["mode"]),
        result="auto_initialized",
        changed_files=[_relative(state_path, root), _relative(organization_path, root), _relative(mission_path, root)],
        rollback_hint="Remove .cambrian/auto/ if this initialization was not intended.",
    )
    return {
        "ok": True,
        "status": "initialized",
        "state": "PRODUCT_CHARTER",
        "goal": goal_text,
        "authority": authority["mode"],
        "state_ref": _relative(state_path, root),
        "organization_ref": _relative(organization_path, root),
        "mission_ref": _relative(mission_path, root),
        "next_command": "cambrian auto boardroom --json",
    }


def start_next_auto_iteration(project_root: Path, goal: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    goal_text = str(goal or "").strip()
    if not goal_text:
        return _blocked("goal is required", 'cambrian auto next --goal "제품 목표" --json')
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    previous_state = _load_yaml(state_path)
    previous_report = _build_auto_report(root)
    previous_summary = _boardroom_report_summary(previous_report)
    previous_handoff_status = str(previous_summary.get("handoff_status") or "")
    if previous_handoff_status not in {"auto_done", "release_gate_go"}:
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["auto next requires auto_done or release_gate_go"],
            "current_handoff_status": previous_handoff_status,
            "release_gate_verdict": previous_summary.get("release_gate_verdict"),
            "next_command": "cambrian auto report --json",
        }
    goal_error = _next_goal_validation_error(goal_text)
    if goal_error:
        return {
            "ok": False,
            "status": "blocked",
            "errors": [goal_error],
            "rejected_goal": goal_text,
            "current_handoff_status": previous_handoff_status,
            "release_gate_verdict": previous_summary.get("release_gate_verdict"),
            "goal_examples": [
                "ONMI-STAY 예약 취소 플로우 검증 강화",
                "auto loop stale boardroom guard 보강",
            ],
            "next_command": _explicit_next_goal_command(),
        }
    previous_release_gate = dict(previous_report.get("release_gate") or {})
    authority = load_authority_profile(root)
    iteration_id = f"iteration-{_stamp()}"
    archive_dir = default_auto_iterations_dir(root) / iteration_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_refs = _archive_active_auto_iteration(root, archive_dir)
    archive_manifest = _next_iteration_archive_manifest(
        archived_refs=archived_refs,
        previous_summary=previous_summary,
        previous_release_gate=previous_release_gate,
    )
    state = {
        "schema_version": SCHEMA_VERSION,
        "created_at": previous_state.get("created_at") or _now(),
        "updated_at": _now(),
        "state": "PRODUCT_CHARTER",
        "previous_state": previous_state.get("state"),
        "previous_goal": previous_state.get("goal"),
        "goal": goal_text,
        "paused": False,
        "authority_mode": authority["mode"],
        "state_machine": STATE_ORDER,
        "iteration_id": iteration_id,
        "previous_iteration_archive": _relative(archive_dir, root),
        "previous_handoff_status": previous_handoff_status,
        "previous_release_gate_verdict": previous_summary.get("release_gate_verdict"),
        "previous_release_gate_ref": previous_summary.get("release_gate_ref"),
        "next_command": "cambrian auto boardroom --json",
    }
    state_path = _save_yaml(state_path, state)
    organization_path = default_auto_organization_path(root)
    if not organization_path.exists():
        organization_path = _save_yaml(organization_path, _default_organization(authority["mode"]))
    mission_path = _save_yaml(default_auto_mission_path(root), _initial_mission_state(goal_text, str(authority["mode"])))
    iteration_record = {
        "schema_version": SCHEMA_VERSION,
        "iteration_id": iteration_id,
        "created_at": _now(),
        "previous_goal": previous_state.get("goal"),
        "next_goal": goal_text,
        "previous_state": previous_state.get("state"),
        "previous_handoff_status": previous_handoff_status,
        "previous_report_summary": previous_summary,
        "previous_release_gate": previous_release_gate,
        "archived_refs": archived_refs,
        "archive_manifest": archive_manifest,
        "fresh_start_contract": {
            "active_state": "PRODUCT_CHARTER",
            "active_release_gate_cleared": True,
            "active_tasks_cleared": True,
            "active_results_cleared": True,
            "next_command": "cambrian auto boardroom --json",
        },
        "source_code_modified": False,
        "provider_api_called": False,
    }
    iteration_path = _save_yaml(archive_dir / "iteration.yaml", iteration_record)
    append_authority_log(
        root,
        command=f"cambrian auto next --goal {goal_text}",
        mode=str(authority["mode"]),
        result="next_iteration_started",
        changed_files=[_relative(state_path, root), _relative(mission_path, root), _relative(iteration_path, root)],
        rollback_hint="Restore the archived .cambrian/auto files from the iteration archive if needed.",
    )
    return {
        "ok": True,
        "status": "next_iteration_started",
        "state": "PRODUCT_CHARTER",
        "goal": goal_text,
        "previous_goal": previous_state.get("goal"),
        "previous_handoff_status": previous_handoff_status,
        "previous_release_gate_verdict": previous_summary.get("release_gate_verdict"),
        "previous_release_gate_ref": previous_summary.get("release_gate_ref"),
        "iteration_id": iteration_id,
        "iteration_ref": _relative(iteration_path, root),
        "archived_refs": archived_refs,
        "archive_manifest": archive_manifest,
        "state_ref": _relative(state_path, root),
        "organization_ref": _relative(organization_path, root),
        "mission_ref": _relative(mission_path, root),
        "source_code_modified": False,
        "provider_api_called": False,
        "next_command": "cambrian auto boardroom --json",
    }


def _next_iteration_archive_manifest(
    *,
    archived_refs: list[str],
    previous_summary: dict[str, Any],
    previous_release_gate: dict[str, Any],
) -> dict[str, Any]:
    normalized_refs = [ref.replace("\\", "/") for ref in archived_refs]
    return {
        "archived_refs": archived_refs,
        "previous_handoff_status": previous_summary.get("handoff_status"),
        "previous_release_gate_verdict": previous_summary.get("release_gate_verdict"),
        "previous_release_gate_ref": previous_summary.get("release_gate_ref"),
        "release_gate_archived": any("/release_gate" in ref for ref in normalized_refs),
        "release_gate_id": previous_release_gate.get("release_gate_id"),
        "fresh_start_active_files": [
            ".cambrian/auto/state.yaml",
            ".cambrian/auto/organization.yaml",
            ".cambrian/auto/mission.yaml",
        ],
        "fresh_start_cleared": [
            ".cambrian/auto/mission.yaml",
            ".cambrian/auto/plan.yaml",
            ".cambrian/auto/report.yaml",
            ".cambrian/auto/execution_log.yaml",
            ".cambrian/auto/boardroom/",
            ".cambrian/auto/decisions/",
            ".cambrian/auto/tasks/",
            ".cambrian/auto/results/",
            ".cambrian/auto/rejections/",
            ".cambrian/auto/corrections/",
            ".cambrian/auto/cycles/",
            ".cambrian/auto/external_results/",
            ".cambrian/auto/release_gate/",
        ],
        "source_code_modified": False,
        "provider_api_called": False,
    }


def auto_status(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    status = _base_auto_status(root)
    if status.get("state") is None:
        return status
    report = _build_auto_report(root)
    decision_handoff = dict(report.get("decision_handoff") or {})
    if decision_handoff.get("next_command") or decision_handoff.get("status") == "input_required":
        status["decision_handoff"] = decision_handoff
        status["next_command"] = decision_handoff.get("next_command")
    return status


def _base_auto_status(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state_path = default_auto_state_path(root)
    authority = load_authority_profile(root)
    if not state_path.exists():
        return {
            "ok": True,
            "status": "not_initialized",
            "state": None,
            "authority": authority["mode"],
            "next_command": 'cambrian auto init --goal "제품 목표" --json',
        }
    state = _load_yaml(state_path)
    payload = {
        "ok": True,
        "status": "paused" if state.get("paused") else "active",
        "state": state.get("state"),
        "goal": state.get("goal"),
        "authority": authority["mode"],
        "state_ref": _relative(state_path, root),
        "next_command": _next_for_state(str(state.get("state") or "")),
    }
    if isinstance(state.get("input_required"), dict):
        payload["input_required"] = state.get("input_required")
    if isinstance(state.get("resolved_inputs"), dict):
        payload["resolved_inputs"] = state.get("resolved_inputs")
    if isinstance(state.get("deferred_inputs"), dict):
        payload["deferred_inputs"] = state.get("deferred_inputs")
    return payload


def run_boardroom(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    state = _load_yaml(state_path)
    authority = load_authority_profile(root)
    report = _build_auto_report(root)
    report_path = _save_yaml(default_auto_report_path(root), report)
    report_ref = _relative(report_path, root)
    report_summary = _boardroom_report_summary(report)
    meeting_id = f"boardroom-{_stamp()}"
    meeting_ref = _relative(default_auto_boardroom_dir(root) / f"{meeting_id}.yaml", root)
    decision_ref = _relative(default_auto_decisions_dir(root) / f"{meeting_id}.yaml", root)
    evidence_refs = _boardroom_evidence_refs(report_ref, report_summary)
    decisions = _attach_boardroom_evidence_to_decisions(
        _boardroom_decisions(str(state.get("goal") or ""), str(authority["mode"]), report_summary),
        evidence_refs,
        report_summary,
    )
    decision_lineage = _boardroom_decision_lineage(
        meeting_id=meeting_id,
        meeting_ref=meeting_ref,
        decision_ref=decision_ref,
        report_ref=report_ref,
        report_summary=report_summary,
        decisions=decisions,
    )
    meeting = {
        "schema_version": SCHEMA_VERSION,
        "meeting_id": meeting_id,
        "created_at": _now(),
        "agenda": _boardroom_agenda(str(state.get("goal") or ""), report_summary),
        "goal": state.get("goal"),
        "authority_mode": authority["mode"],
        "source_auto_report": report_ref,
        "auto_report_summary": report_summary,
        "report_evidence_refs": evidence_refs,
        "decisions": decisions,
        "decision_lineage": decision_lineage,
        "decision_ref": decision_ref,
        "recommended_next_action": _boardroom_recommended_next_action(report_summary),
    }
    meeting_path = _save_yaml(default_auto_boardroom_dir(root) / f"{meeting_id}.yaml", meeting)
    decision_path = _save_yaml(default_auto_decisions_dir(root) / f"{meeting_id}.yaml", {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "source_meeting": meeting_id,
        "source_boardroom": meeting_ref,
        "source_auto_report": report_ref,
        "auto_report_summary": report_summary,
        "report_evidence_refs": evidence_refs,
        "decision_lineage": decision_lineage,
        "decisions": decisions,
    })
    _update_state(root, "BOARDROOM_PLANNING")
    append_authority_log(
        root,
        command="cambrian auto boardroom",
        mode=str(authority["mode"]),
        result="boardroom_recorded",
        changed_files=[_relative(report_path, root), _relative(meeting_path, root), _relative(decision_path, root)],
        rollback_hint="Delete the boardroom and decision files if this record is not wanted.",
    )
    return {
        "ok": True,
        "meeting_id": meeting_id,
        "agenda": meeting["agenda"],
        "auto_report_summary": report_summary,
        "decisions": meeting["decisions"],
        "report_evidence_refs": evidence_refs,
        "decision_lineage": decision_lineage,
        "recommended_next_action": meeting["recommended_next_action"],
        "boardroom_ref": _relative(meeting_path, root),
        "decision_ref": _relative(decision_path, root),
    }


def create_auto_plan(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    meeting_path = _latest_file(default_auto_boardroom_dir(root), "boardroom-*.yaml")
    if meeting_path is None:
        return _blocked("boardroom decision is missing", "cambrian auto boardroom --json")
    state = _load_yaml(state_path)
    authority = load_authority_profile(root)
    meeting = _load_yaml(meeting_path)
    report_summary = dict(meeting.get("auto_report_summary") or {})
    current_report_summary = _boardroom_report_summary(_build_auto_report(root))
    if not _auto_report_summary_matches_for_plan(report_summary, current_report_summary):
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["boardroom decision is stale; rerun cambrian auto boardroom before planning"],
            "boardroom_handoff_status": report_summary.get("handoff_status"),
            "current_handoff_status": current_report_summary.get("handoff_status"),
            "next_command": "cambrian auto boardroom --json",
        }
    plan_kind, steps = _plan_steps_from_handoff(report_summary)
    company_ledger_guidance = dict(report_summary.get("company_ledger_guidance") or {})
    result_contract_guidance = dict(report_summary.get("result_contract_guidance") or {})
    decision_lineage = _plan_decision_lineage(meeting, meeting_path, root)
    steps = _attach_company_ledger_guidance_to_steps(steps, company_ledger_guidance)
    steps = _attach_result_contract_guidance_to_steps(steps, result_contract_guidance)
    steps = _attach_boardroom_decision_lineage_to_steps(steps, decision_lineage)
    plan_id = f"auto-plan-{_stamp()}"
    next_command = None if plan_kind == "done" else "cambrian auto run --max-steps 5 --json"
    if plan_kind == "next_iteration":
        next_command = _explicit_next_goal_command()
    if plan_kind == "input_wait":
        next_command = None
    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "created_at": _now(),
        "goal": state.get("goal") or "Complete product workflow",
        "source_boardroom": _relative(meeting_path, root),
        "authority_mode": authority["mode"],
        "plan_kind": plan_kind,
        "source_decision": decision_lineage.get("decision_ref"),
        "decision_lineage": decision_lineage,
        "auto_report_summary": report_summary,
        "company_loop_context": report_summary.get("company_loop_context", {}),
        "company_ledger_guidance": company_ledger_guidance,
        "result_contract_guidance": result_contract_guidance,
        "steps": steps,
        "next_command": next_command,
    }
    plan_path = _save_yaml(default_auto_plan_path(root), plan)
    next_state = "DONE" if plan_kind == "done" else "EXECUTION_PLAN"
    _update_state(root, next_state)
    append_authority_log(
        root,
        command="cambrian auto plan",
        mode=str(authority["mode"]),
        result="plan_created",
        changed_files=[_relative(plan_path, root)],
        rollback_hint="Delete .cambrian/auto/plan.yaml to discard this plan.",
    )
    return {
        "ok": True,
        "plan_id": plan_id,
        "goal": plan["goal"],
        "plan_kind": plan_kind,
        "auto_report_summary": report_summary,
        "decision_lineage": decision_lineage,
        "company_ledger_guidance": company_ledger_guidance,
        "result_contract_guidance": result_contract_guidance,
        "steps": plan["steps"],
        "next_command": plan["next_command"],
        "plan_ref": _relative(plan_path, root),
    }


def run_auto_cycle(project_root: Path, max_steps: int = 1) -> dict[str, Any]:
    root = Path(project_root).resolve()
    cycle_id = f"auto-cycle-{_stamp()}"
    report_payload = auto_report(root)
    if not report_payload.get("ok"):
        return _cycle_blocked(root, cycle_id, "report", report_payload, max_steps=max_steps)
    handoff = dict(report_payload.get("decision_handoff") or {})
    stop = _cycle_stop_from_handoff(handoff)
    if stop:
        return _cycle_stopped(root, cycle_id, report_payload, handoff, stop, max_steps=max_steps)
    boardroom_payload = run_boardroom(root)
    if not boardroom_payload.get("ok"):
        return _cycle_blocked(root, cycle_id, "boardroom", boardroom_payload, max_steps=max_steps)
    plan_payload = create_auto_plan(root)
    if not plan_payload.get("ok"):
        return _cycle_blocked(root, cycle_id, "plan", plan_payload, max_steps=max_steps)
    run_payload = run_auto_plan(root, max_steps=max_steps)
    if not run_payload.get("ok"):
        return _cycle_blocked(root, cycle_id, "run", run_payload, max_steps=max_steps)

    authority = load_authority_profile(root)
    next_decision = _cycle_next_decision(
        handoff_status=(plan_payload.get("auto_report_summary") or {}).get("handoff_status"),
        run_payload=run_payload,
        plan_payload=plan_payload,
    )
    cycle_status = "stopped" if next_decision.get("status") == "authority_required" else "recorded"
    stop_condition = "authority_required" if next_decision.get("status") == "authority_required" else None
    cycle_record = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "created_at": _now(),
        "max_steps": max(0, min(int(max_steps or 0), 50)),
        "status": cycle_status,
        "stop_condition": stop_condition,
        "report_ref": report_payload.get("report_ref"),
        "boardroom_ref": boardroom_payload.get("boardroom_ref"),
        "decision_ref": boardroom_payload.get("decision_ref"),
        "plan_ref": plan_payload.get("plan_ref"),
        "plan_kind": plan_payload.get("plan_kind"),
        "handoff_status": (plan_payload.get("auto_report_summary") or {}).get("handoff_status"),
        "next_decision": next_decision,
        "run": {
            "executed_steps": run_payload.get("executed_steps"),
            "blocked_steps": run_payload.get("blocked_steps", []),
            "task_refs": run_payload.get("task_refs", []),
            "directive_refs": run_payload.get("directive_refs", []),
            "job_refs": run_payload.get("job_refs", []),
            "packet_refs": run_payload.get("packet_refs", []),
            "waiting_for_result": run_payload.get("waiting_for_result"),
            "next_state": run_payload.get("next_state"),
        },
        "source_code_modified": False,
        "provider_api_called": False,
    }
    cycle_path = _save_yaml(default_auto_cycles_dir(root) / f"{cycle_id}.yaml", cycle_record)
    loop_state_path = _write_auto_cycle_state(root, cycle_record, cycle_path)
    append_authority_log(
        root,
        command=f"cambrian auto cycle --max-steps {cycle_record['max_steps']}",
        mode=str(authority["mode"]),
        result="auto_cycle_recorded",
        changed_files=[_relative(cycle_path, root), _relative(loop_state_path, root)],
        rollback_hint="Remove the auto cycle record if this orchestration was not intended.",
    )
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "cycle_ref": _relative(cycle_path, root),
        "max_steps": cycle_record["max_steps"],
        "report_ref": report_payload.get("report_ref"),
        "boardroom_ref": boardroom_payload.get("boardroom_ref"),
        "decision_ref": boardroom_payload.get("decision_ref"),
        "plan_ref": plan_payload.get("plan_ref"),
        "plan_kind": plan_payload.get("plan_kind"),
        "handoff_status": cycle_record["handoff_status"],
        "executed_steps": run_payload.get("executed_steps"),
        "blocked_steps": run_payload.get("blocked_steps", []),
        "task_refs": run_payload.get("task_refs", []),
        "directive_refs": run_payload.get("directive_refs", []),
        "job_refs": run_payload.get("job_refs", []),
        "packet_refs": run_payload.get("packet_refs", []),
        "waiting_for_result": run_payload.get("waiting_for_result"),
        "cycle_status": cycle_status,
        "stop_condition": stop_condition,
        "next_decision": next_decision,
        "cycle_state_ref": _relative(loop_state_path, root),
        "source_code_modified": False,
        "provider_api_called": False,
        "next_command": next_decision.get("next_command"),
    }


def run_auto_plan(project_root: Path, max_steps: int = 5) -> dict[str, Any]:
    root = Path(project_root).resolve()
    plan_path = default_auto_plan_path(root)
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    if not plan_path.exists():
        return _blocked("auto plan is missing", "cambrian auto plan --json")
    state = _load_yaml(state_path)
    if bool(state.get("paused")):
        return _blocked("auto mode is paused", "cambrian auto resume --json")
    plan = _load_yaml(plan_path)
    plan_kind = str(plan.get("plan_kind") or "")
    if plan_kind == "next_iteration":
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["next_iteration plan cannot be run; start a new iteration with auto next"],
            "plan_kind": plan_kind,
            "next_command": plan.get("next_command") or _explicit_next_goal_command(),
        }
    authority = load_authority_profile(root)
    permissions = dict(authority.get("permissions") or {})
    limit = max(0, min(int(max_steps or 0), 50))
    steps = [dict(item) for item in plan.get("steps", []) if isinstance(item, dict)]
    plan_id = str(plan.get("plan_id") or "auto-plan")
    executed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    task_refs: list[str] = []
    directive_refs: list[str] = []
    job_refs: list[str] = []
    packet_refs: list[str] = []
    for step in steps[:limit]:
        missing = _missing_permissions(step, permissions)
        entry = {
            "step_id": step.get("id"),
            "owner": step.get("owner"),
            "task": step.get("task"),
            "required_permissions": step.get("required_permissions", []),
            "changed_files": [],
            "commands_executed": [],
            "test_results": [],
            "decision_source": plan.get("source_boardroom"),
            "rollback_hint": "No source files were changed by auto run V1.",
        }
        if missing:
            entry["status"] = "blocked"
            entry["missing_permissions"] = missing
            blocked.append(entry)
        else:
            task = _write_auto_task_directive(root, plan_id, plan, step, authority["mode"])
            task_refs.append(str(task["task_ref"]))
            directive_refs.append(str(task["directive_ref"]))
            if task.get("job_ref"):
                job_refs.append(str(task["job_ref"]))
                entry["job_ref"] = task.get("job_ref")
            if task.get("packet_ref"):
                packet_refs.append(str(task["packet_ref"]))
                entry["packet_ref"] = task.get("packet_ref")
            if task.get("job_next_commands"):
                entry["job_next_commands"] = task.get("job_next_commands")
            entry["status"] = "waiting_for_result"
            entry["result"] = "codex_directive_created"
            entry["task_ref"] = task["task_ref"]
            entry["directive_ref"] = task["directive_ref"]
            executed.append(entry)
    next_state = "DONE" if str(plan.get("plan_kind") or "") == "done" else "IMPLEMENTATION" if executed else "EXECUTION_PLAN"
    if blocked and not executed:
        next_state = "EXECUTION_PLAN"
    log_path = _append_execution_log(root, authority["mode"], executed, blocked, next_state, task_refs, directive_refs, job_refs, packet_refs)
    _update_state(root, next_state)
    append_authority_log(
        root,
        command=f"cambrian auto run --max-steps {limit}",
        mode=str(authority["mode"]),
        result="auto_run_recorded",
        changed_files=[_relative(log_path, root), _relative(state_path, root), *task_refs, *directive_refs, *job_refs, *packet_refs],
        rollback_hint="Auto run V1 only recorded metadata task directives. Remove .cambrian/auto/tasks/ entries if needed.",
    )
    return {
        "ok": True,
        "mode": "auto",
        "authority": authority["mode"],
        "executed_steps": len(executed),
        "blocked_steps": blocked,
        "next_state": next_state,
        "max_steps": limit,
        "task_refs": task_refs,
        "directive_refs": directive_refs,
        "job_refs": job_refs,
        "packet_refs": packet_refs,
        "waiting_for_result": len(executed),
        "evidence_files": [_relative(log_path, root)],
        "source_code_modified": False,
        "provider_api_called": False,
    }


def pause_auto(project_root: Path) -> dict[str, Any]:
    return _set_paused(project_root, True)


def resume_auto(project_root: Path) -> dict[str, Any]:
    return _set_paused(project_root, False)


def answer_auto_input(project_root: Path, field: str, value: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    field_name = str(field or "").strip()
    input_value = str(value or "").strip()
    if not field_name:
        return _blocked("input field is required", "cambrian auto input answer --field <field> --value <value> --json")
    if not input_value:
        return _blocked("input value is required", f"cambrian auto input answer --field {field_name} --value <value> --json")
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    state = _load_yaml(state_path)
    input_required = state.get("input_required", {})
    required_inputs = input_required.get("required_inputs", []) if isinstance(input_required, dict) else []
    normalized_required = _normalize_required_input(required_inputs)
    if normalized_required and field_name not in {str(item.get("field") or "") for item in normalized_required}:
        return {
            "ok": False,
            "status": "blocked",
            "errors": [f"input field is not currently required: {field_name}"],
            "required_inputs": normalized_required,
            "next_command": "cambrian auto status --json",
        }
    answer = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "field": field_name,
        "value": input_value,
        "source": "human_input",
        "used_for": "auto input_required gate",
    }
    answer_path = _save_yaml(default_input_answers_dir(root) / f"{_safe_slug(field_name)}.yaml", answer)
    resolved_inputs = state.get("resolved_inputs", {})
    if not isinstance(resolved_inputs, dict):
        resolved_inputs = {}
    resolved_inputs[field_name] = {
        "answered_at": _now(),
        "answer_ref": _relative(answer_path, root),
    }
    state["resolved_inputs"] = resolved_inputs
    missing = [
        item
        for item in normalized_required
        if str(item.get("field") or "") not in resolved_inputs
    ]
    if not missing:
        state["paused"] = False
        state["pause_reason"] = None
        state["input_required"] = None
        state["next_command"] = "cambrian auto report --json"
    state["updated_at"] = _now()
    state_path = _save_yaml(state_path, state)
    append_authority_log(
        root,
        command=f"cambrian auto input answer --field {field_name}",
        mode=str(load_authority_profile(root)["mode"]),
        result="auto_input_answered",
        changed_files=[_relative(answer_path, root), _relative(state_path, root)],
        rollback_hint="Remove the input answer file and restore input_required in .cambrian/auto/state.yaml if needed.",
    )
    return {
        "ok": True,
        "status": "input_answered",
        "field": field_name,
        "answer_ref": _relative(answer_path, root),
        "remaining_required_inputs": missing,
        "auto_paused": bool(state.get("paused")),
        "state_ref": _relative(state_path, root),
        "next_command": "cambrian auto status --json" if missing else "cambrian auto report --json",
    }


def defer_auto_input(project_root: Path, field: str, reason: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    field_name = str(field or "").strip()
    reason_text = str(reason or "").strip()
    if not field_name:
        return _blocked("input field is required", "cambrian auto input defer --field <field> --reason <reason> --json")
    if not reason_text:
        return _blocked("defer reason is required", f"cambrian auto input defer --field {field_name} --reason <reason> --json")
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    report = _build_auto_report(root)
    decision_handoff = dict(report.get("decision_handoff") or {})
    if decision_handoff.get("status") != "input_required":
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["auto input is not currently required"],
            "next_command": decision_handoff.get("next_command") or "cambrian auto status --json",
        }
    required_inputs = _normalize_required_input(decision_handoff.get("required_inputs"))
    required_fields = {str(item.get("field") or "") for item in required_inputs}
    if required_inputs and field_name not in required_fields:
        return {
            "ok": False,
            "status": "blocked",
            "errors": [f"input field is not currently required: {field_name}"],
            "required_inputs": required_inputs,
            "next_command": "cambrian auto input list --json",
        }
    matched_input = next((item for item in required_inputs if str(item.get("field") or "") == field_name), {"field": field_name})
    defer_record = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "field": field_name,
        "reason": reason_text,
        "source": "human_defer",
        "used_for": "auto input_required gate",
        "required_input": matched_input,
        "source_handoff_status": decision_handoff.get("status"),
        "source_blockers": decision_handoff.get("input_blockers", []),
    }
    defer_path = _save_yaml(default_input_deferred_dir(root) / f"{_safe_slug(field_name)}.yaml", defer_record)
    state = _load_yaml(state_path)
    deferred_inputs = state.get("deferred_inputs", {})
    if not isinstance(deferred_inputs, dict):
        deferred_inputs = {}
    deferred_inputs[field_name] = {
        "deferred_at": _now(),
        "reason": reason_text,
        "defer_ref": _relative(defer_path, root),
    }
    state["deferred_inputs"] = deferred_inputs
    satisfied_fields = set()
    for bucket_name in ("resolved_inputs", "deferred_inputs"):
        bucket = state.get(bucket_name, {})
        if isinstance(bucket, dict):
            satisfied_fields.update(str(item).strip() for item in bucket.keys())
    remaining = [item for item in required_inputs if str(item.get("field") or "").strip() not in satisfied_fields]
    if not remaining:
        state["paused"] = False
        state["pause_reason"] = None
        state["input_required"] = None
        state["next_command"] = "cambrian auto boardroom --json"
    state["updated_at"] = _now()
    state_path = _save_yaml(state_path, state)
    append_authority_log(
        root,
        command=f"cambrian auto input defer --field {field_name}",
        mode=str(load_authority_profile(root)["mode"]),
        result="auto_input_deferred",
        changed_files=[_relative(defer_path, root), _relative(state_path, root)],
        rollback_hint="Remove the deferred input file and restore input_required in .cambrian/auto/state.yaml if needed.",
    )
    return {
        "ok": True,
        "status": "input_deferred",
        "field": field_name,
        "reason": reason_text,
        "defer_ref": _relative(defer_path, root),
        "remaining_required_inputs": remaining,
        "auto_paused": bool(state.get("paused")),
        "state_ref": _relative(state_path, root),
        "next_command": "cambrian auto input list --json" if remaining else "cambrian auto boardroom --json",
    }


def list_auto_inputs(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    report = _build_auto_report(root)
    decision_handoff = dict(report.get("decision_handoff") or {})
    state = _load_yaml(state_path)
    resolved_inputs = state.get("resolved_inputs", {})
    if not isinstance(resolved_inputs, dict):
        resolved_inputs = {}
    deferred_inputs = state.get("deferred_inputs", {})
    if not isinstance(deferred_inputs, dict):
        deferred_inputs = {}
    if decision_handoff.get("status") != "input_required":
        return {
            "ok": True,
            "status": "no_input_required",
            "required_inputs": [],
            "resolved_inputs": resolved_inputs,
            "deferred_inputs": deferred_inputs,
            "next_command": decision_handoff.get("next_command"),
        }
    input_request_refs = _ensure_input_request_files(root, decision_handoff)
    if input_request_refs:
        decision_handoff["input_request_refs"] = input_request_refs
    _pause_for_input_required(root, decision_handoff)
    return {
        "ok": True,
        "status": "input_required",
        "required_inputs": decision_handoff.get("required_inputs", []),
        "input_blockers": decision_handoff.get("input_blockers", []),
        "input_request_refs": decision_handoff.get("input_request_refs", []),
        "resolved_inputs": resolved_inputs,
        "deferred_inputs": deferred_inputs,
        "next_command": None,
    }


def auto_report(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    report = _build_auto_report(root)
    mission_ref = _save_mission_status_from_report(root, report)
    if mission_ref:
        mission_status = dict(report.get("mission_status") or {})
        mission_status["mission_ref"] = mission_ref
        if mission_status.get("evidence_status") == "caution" and mission_status.get("final_goal"):
            mission_status["evidence_status"] = "grounded"
        evidence_refs = mission_status.get("evidence_refs", [])
        if not isinstance(evidence_refs, list):
            evidence_refs = []
        mission_status["evidence_refs"] = _auto_dedupe_text([mission_ref, *[str(item) for item in evidence_refs]])
        report["mission_status"] = mission_status
    decision_handoff = dict(report.get("decision_handoff") or {})
    if decision_handoff.get("status") == "input_required":
        input_request_refs = _ensure_input_request_files(root, decision_handoff)
        if input_request_refs:
            decision_handoff["input_request_refs"] = input_request_refs
            report["decision_handoff"] = decision_handoff
        _pause_for_input_required(root, decision_handoff)
        report["status"] = _base_auto_status(root)
    report_path = _save_yaml(default_auto_report_path(root), report)
    return {
        "ok": True,
        "report": report,
        "report_ref": _relative(report_path, root),
        "decision_handoff": decision_handoff,
        "next_command": decision_handoff.get("next_command"),
    }


def run_release_gate(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    report = _build_auto_report(root)
    report_path = _save_yaml(default_auto_report_path(root), report)
    report_summary = _boardroom_report_summary(report)
    plan = _load_yaml(default_auto_plan_path(root)) if default_auto_plan_path(root).exists() else {}
    package = _build_release_gate_package(root, report, report_summary, plan)
    gate_path = _save_yaml(default_auto_release_gate_dir(root) / f"{package['release_gate_id']}.yaml", package)
    _update_state(root, "RELEASE_GATE")
    append_authority_log(
        root,
        command="cambrian auto release-gate",
        mode=str(load_authority_profile(root)["mode"]),
        result=f"release_gate_{str(package.get('verdict')).lower().replace(' ', '_')}",
        changed_files=[_relative(report_path, root), _relative(gate_path, root)],
        rollback_hint="Delete the release gate package if this decision package was not intended.",
    )
    return {
        "ok": True,
        "release_gate_id": package["release_gate_id"],
        "verdict": package["verdict"],
        "reason": package["reason"],
        "evidence_checklist": package["evidence_checklist"],
        "required_before_release": package["required_before_release"],
        "deferred_after_release": package["deferred_after_release"],
        "quality_route": package["quality_route"],
        "proof_summary": package["proof_summary"],
        "source_result": package["source_result"],
        "report_ref": _relative(report_path, root),
        "release_gate_ref": _relative(gate_path, root),
        "source_code_modified": False,
        "next_command": package["next_command"],
    }


def ingest_auto_step_result(project_root: Path, task_ref: str, result_path: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    task_path = _resolve_auto_task_path(root, str(task_ref or ""))
    if task_path is None:
        return _blocked("auto task is missing", "cambrian auto run --max-steps 5 --json")
    source_path = Path(result_path)
    if not source_path.is_absolute():
        source_path = (root / source_path).resolve()
    if not source_path.exists():
        return _blocked(f"result file not found: {result_path}", None)
    task = _load_yaml(task_path)
    result_payload = _load_result_payload(source_path)
    contract_errors = _validate_step_result_contract(result_payload, task)
    if contract_errors:
        performance_record = record_worker_performance_event(
            root,
            task=task,
            outcome="rejected",
            status="invalid_result_contract",
            evidence_refs=[
                _relative(task_path, root),
                _relative(source_path, root) if _is_within(root, source_path) else str(source_path),
            ],
            errors=contract_errors,
        )
        rejection_record, rejection_path, log_path = _record_auto_step_rejection(root, task_path, task, source_path, contract_errors)
        rejection_record["worker_performance_record"] = {
            "status": performance_record.get("status"),
            "event_id": performance_record.get("event_id"),
            "ledger_ref": performance_record.get("ledger_ref"),
            "aggregate_keys": performance_record.get("aggregate_keys", []),
        }
        _save_yaml(rejection_path, rejection_record)
        rejection_ref = _relative(rejection_path, root)
        log_ref = _relative(log_path, root)
        performance_ref = str(performance_record.get("ledger_ref") or "")
        append_authority_log(
            root,
            command=f"cambrian auto step ingest {task_ref}",
            mode=str(load_authority_profile(root)["mode"]),
            result="auto_step_rejected_invalid_contract",
            changed_files=_auto_dedupe_text([rejection_ref, log_ref, performance_ref]),
            rollback_hint="Delete the rejection record if this failed ingest should not be kept as evidence.",
        )
        return {
            "ok": False,
            "error": "invalid_result_contract",
            "errors": contract_errors,
            "task_ref": _relative(task_path, root),
            "result_path": _relative(source_path, root) if _is_within(root, source_path) else str(source_path),
            "rejection_ref": rejection_ref,
            "correction_directive_ref": rejection_record.get("correction_directive_ref"),
            "corrected_result_template_ref": rejection_record.get("corrected_result_template_ref"),
            "execution_log_ref": log_ref,
            "worker_performance_record": rejection_record["worker_performance_record"],
            "required_fields": _required_step_result_fields_for_task(task),
            "example": _step_result_contract_example(task),
            "role_compliance": _role_compliance_summary(task, False),
            "company_ledger_compliance_required": rejection_record.get("company_ledger_compliance_required"),
            "source_code_modified": False,
            "provider_api_called": False,
            "next_command": rejection_record.get("next_command"),
        }
    status = _derive_step_status(result_payload)
    task["status"] = status
    task["result_ref"] = _relative(source_path, root) if _is_within(root, source_path) else str(source_path)
    task["result_ingested_at"] = _now()
    task["result_summary"] = result_payload.get("summary")
    task["result_blockers"] = result_payload.get("blockers", [])
    task["result_tests"] = result_payload.get("tests", [])
    task["result_evidence"] = result_payload.get("evidence", {})
    task["result_role_outputs"] = result_payload.get("role_outputs", {})

    result_record = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "task_id": task.get("task_id"),
        "job_id": _auto_company_job_id(task),
        "task_ref": _relative(task_path, root),
        "source_result_ref": task["result_ref"],
        "status": status,
        "summary": result_payload.get("summary"),
        "changed_files": result_payload.get("changed_files", []),
        "tests": result_payload.get("tests", []),
        "blockers": result_payload.get("blockers", []),
        "next_action": result_payload.get("next_action"),
        "evidence": result_payload.get("evidence", {}),
        "role_outputs": result_payload.get("role_outputs", {}),
        "company_ledger_compliance": result_payload.get("company_ledger_compliance", {}),
        "required_input": result_payload.get("required_input", result_payload.get("required_inputs", [])),
        "role_compliance": _role_compliance_summary(task, True),
        "safety": {
            "source_code_modified_by_ingest": False,
            "provider_api_called_by_ingest": False,
        },
    }
    result_quality = _score_step_result_quality(task, result_record)
    task["result_quality"] = result_quality
    result_record["result_quality"] = result_quality
    result_ref_path = _save_yaml(default_auto_results_dir(root) / f"{task.get('task_id')}.yaml", result_record)
    result_skill_candidate = record_skill_knowledge_candidate(
        root,
        source=f"auto_step_result:{task.get('task_id') or Path(str(task_ref)).stem}",
        skill_ids=_skill_ids_for_task(task),
        summary=f"Auto step result produced candidate skill knowledge with status {status}.",
        warning=_skill_knowledge_warning_for_result(status, result_record),
        evidence_refs=[_relative(result_ref_path, root), task["result_ref"]],
        knowledge_kind=f"result_{status}_candidate",
    )
    result_record["skill_knowledge_candidate"] = {
        "status": result_skill_candidate.get("status"),
        "candidate_id": result_skill_candidate.get("candidate_id"),
        "candidate_ref": result_skill_candidate.get("candidate_ref"),
        "ledger_ref": result_skill_candidate.get("ledger_ref"),
        "auto_promote": result_skill_candidate.get("auto_promote"),
    }
    task["skill_knowledge_candidate"] = result_record["skill_knowledge_candidate"]
    result_performance_record = record_worker_performance_event(
        root,
        task=task,
        outcome=status,
        status=status,
        evidence_refs=[_relative(result_ref_path, root), task["result_ref"]],
        result_quality=result_quality,
        blockers=_auto_text_list(result_record.get("blockers")),
    )
    result_record["worker_performance_record"] = {
        "status": result_performance_record.get("status"),
        "event_id": result_performance_record.get("event_id"),
        "ledger_ref": result_performance_record.get("ledger_ref"),
        "aggregate_keys": result_performance_record.get("aggregate_keys", []),
    }
    task["worker_performance_record"] = result_record["worker_performance_record"]
    company_records = _record_auto_company_ledgers(root, task, result_record, _relative(result_ref_path, root))
    result_record["company_verification_record"] = company_records["verification"]
    result_record["company_context_record"] = company_records["context"]
    result_record["promotion_policy"] = {
        "auto_promote": False,
        "requires_user_review": True,
    }
    resolved_rejections = _resolve_auto_step_rejections(root, task, result_record, _relative(result_ref_path, root))
    if int(resolved_rejections.get("count", 0) or 0) > 0:
        retry_performance_record = record_worker_performance_event(
            root,
            task=task,
            outcome="retry_resolved",
            status=status,
            evidence_refs=[_relative(result_ref_path, root), *_auto_text_list(resolved_rejections.get("changed_files"))],
            result_quality=result_quality,
            blockers=_auto_text_list(result_record.get("blockers")),
            resolved_rejections=resolved_rejections,
        )
        result_record["retry_worker_performance_record"] = {
            "status": retry_performance_record.get("status"),
            "event_id": retry_performance_record.get("event_id"),
            "ledger_ref": retry_performance_record.get("ledger_ref"),
            "aggregate_keys": retry_performance_record.get("aggregate_keys", []),
        }
        result_record["resolved_rejections"] = resolved_rejections
        task["resolved_rejections"] = resolved_rejections
    task["company_verification_record"] = company_records["verification"]
    task["company_context_record"] = company_records["context"]
    _save_yaml(task_path, task)
    _save_yaml(result_ref_path, result_record)
    log_path = _append_step_result_log(root, task, result_record)
    next_state = "REVIEW" if status == "blocked" else "VALIDATION"
    _update_state(root, next_state)
    company_changed_files = _company_record_changed_files(company_records)
    result_candidate_changed_files = _auto_text_list(result_skill_candidate.get("ledger_ref"))
    performance_changed_files = _auto_text_list(result_performance_record.get("ledger_ref"))
    retry_performance_record = result_record.get("retry_worker_performance_record", {}) if isinstance(result_record.get("retry_worker_performance_record"), dict) else {}
    performance_changed_files.extend(_auto_text_list(retry_performance_record.get("ledger_ref")))
    rejection_changed_files = _auto_text_list(resolved_rejections.get("changed_files"))
    append_authority_log(
        root,
        command=f"cambrian auto step ingest {task_ref}",
        mode=str(load_authority_profile(root)["mode"]),
        result=f"auto_step_{status}",
        changed_files=[
            _relative(task_path, root),
            _relative(result_ref_path, root),
            _relative(log_path, root),
            *company_changed_files,
            *result_candidate_changed_files,
            *performance_changed_files,
            *rejection_changed_files,
        ],
        rollback_hint="Remove the auto result record and reset the task status if this ingest was not intended.",
    )
    return {
        "ok": status in {"validated", "done", "result_ingested", "blocked"},
        "status": status,
        "task_id": task.get("task_id"),
        "task_ref": _relative(task_path, root),
        "result_ref": _relative(result_ref_path, root),
        "execution_log_ref": _relative(log_path, root),
        "next_state": next_state,
        "changed_files": result_record["changed_files"],
        "tests": result_record["tests"],
        "blockers": result_record["blockers"],
        "role_compliance": result_record["role_compliance"],
        "result_quality": result_record["result_quality"],
        "company_verification_record": result_record["company_verification_record"],
        "company_context_record": result_record["company_context_record"],
        "resolved_rejections": resolved_rejections,
        "source_code_modified": False,
        "provider_api_called": False,
        "next_command": "cambrian auto report --json" if status != "blocked" else "cambrian auto boardroom --json",
    }


def render_auto_result(payload: dict[str, Any]) -> str:
    lines = ["Cambrian Auto Mode", ""]
    if payload.get("status"):
        lines.append(f"Status: {payload.get('status')}")
    if payload.get("state"):
        lines.append(f"State: {payload.get('state')}")
    if payload.get("goal"):
        lines.append(f"Goal: {payload.get('goal')}")
    if payload.get("authority"):
        lines.append(f"Authority: {payload.get('authority')}")
    if payload.get("meeting_id"):
        lines.append(f"Meeting: {payload.get('meeting_id')}")
    if payload.get("plan_id"):
        lines.append(f"Plan: {payload.get('plan_id')}")
    if payload.get("release_gate_id"):
        lines.append(f"Release gate: {payload.get('release_gate_id')}")
    if payload.get("verdict"):
        lines.append(f"Verdict: {payload.get('verdict')}")
    if "executed_steps" in payload:
        lines.append(f"Executed steps: {payload.get('executed_steps')}")
        lines.append(f"Blocked steps: {len(payload.get('blocked_steps') or [])}")
    if payload.get("waiting_for_result") is not None:
        lines.append(f"Waiting for result: {payload.get('waiting_for_result')}")
    if payload.get("task_refs"):
        lines.append("")
        lines.append("Task directives:")
        for item in payload.get("task_refs") or []:
            lines.append(f"  - {item}")
    if payload.get("task_ref"):
        lines.append(f"Task: {payload.get('task_ref')}")
    if payload.get("result_ref"):
        lines.append(f"Result: {payload.get('result_ref')}")
    if payload.get("rejection_ref"):
        lines.append(f"Rejection: {payload.get('rejection_ref')}")
    if payload.get("correction_directive_ref"):
        lines.append(f"Correction directive: {payload.get('correction_directive_ref')}")
    if payload.get("corrected_result_template_ref"):
        lines.append(f"Corrected result template: {payload.get('corrected_result_template_ref')}")
    report = payload.get("report")
    if isinstance(report, dict):
        mission_status = report.get("mission_status", {})
        if isinstance(mission_status, dict):
            lines.append("")
            lines.append("Mission status:")
            lines.append(f"  Phase: {mission_status.get('current_phase')}")
            lines.append(f"  Completion score: {mission_status.get('completion_score')}")
            next_task = mission_status.get("next_task", {})
            if isinstance(next_task, dict):
                lines.append(f"  Next task: {next_task.get('id')} {next_task.get('title')}")
        step_results = report.get("step_results", {})
        if isinstance(step_results, dict):
            lines.append("")
            lines.append("Step results:")
            lines.append(f"  Total: {step_results.get('total', 0)}")
            lines.append(f"  Blocked: {step_results.get('blocked', 0)}")
            lines.append(f"  Validated: {step_results.get('validated', 0)}")
        result_rejections = report.get("result_rejections", {})
        if isinstance(result_rejections, dict) and int(result_rejections.get("total", 0) or 0) > 0:
            lines.append("")
            lines.append("Result rejections:")
            lines.append(f"  Total: {result_rejections.get('total', 0)}")
            lines.append(f"  Open: {result_rejections.get('open_count', 0)}")
        handoff = report.get("decision_handoff", {})
        if isinstance(handoff, dict) and handoff.get("status"):
            lines.append("")
            lines.append("Decision handoff:")
            lines.append(f"  {handoff.get('status')}")
    if payload.get("blockers"):
        lines.append("")
        lines.append("Blockers:")
        for item in payload.get("blockers") or []:
            lines.append(f"  - {item}")
    if payload.get("next_command"):
        lines.append("")
        lines.append("Next:")
        lines.append(f"  {payload['next_command']}")
    elif payload.get("recommended_next_action"):
        lines.append("")
        lines.append("Next:")
        lines.append(f"  {payload['recommended_next_action']}")
    if payload.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for error in payload["errors"]:
            lines.append(f"  - {error}")
    return "\n".join(lines)


def _default_organization(authority_mode: str) -> dict[str, Any]:
    roles = [
        ("ceo-agent", "제품 방향과 출시 판단"),
        ("cto-agent", "기술 설계와 리스크 판단"),
        ("coo-agent", "실행 순서와 운영 안정성"),
        ("pm-agent", "작업지시서와 완료 기준 작성"),
        ("engineering-agent", "구현"),
        ("qa-agent", "검증"),
        ("release-manager-agent", "출시 판정"),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "organization": {
            "mode": "auto_product_build",
            "authority_mode": authority_mode,
            "roles": [{"id": role_id, "responsibility": responsibility} for role_id, responsibility in roles],
        },
    }


def _initial_mission_state(goal: str, authority_mode: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mission_kind": "auto_mission_control_v0_1",
        "created_at": _now(),
        "updated_at": _now(),
        "final_goal": str(goal or "").strip(),
        "authority_mode": authority_mode,
        "source": "cambrian auto init",
        "status": "active",
        "current_phase": "PRODUCT_CHARTER",
        "next_task": {},
        "blockers": [],
        "completion_score": None,
        "completion_claim_policy": {
            "requires_release_gate_go": True,
            "no_success_rate_without_runtime_evidence": True,
        },
    }


def _build_auto_report(root: Path) -> dict[str, Any]:
    status = _base_auto_status(root)
    plan = _load_yaml(default_auto_plan_path(root)) if default_auto_plan_path(root).exists() else {}
    execution_log = _load_yaml(default_auto_execution_log_path(root)) if default_auto_execution_log_path(root).exists() else {}
    task_statuses = _summarize_auto_task_statuses(root)
    step_results = _summarize_auto_step_results(execution_log)
    result_rejections = _summarize_auto_result_rejections(execution_log, task_statuses)
    release_gate = _summarize_release_gate(root)
    proof_summary = _build_proof_summary(root, status, task_statuses, step_results, release_gate)
    recovery_loop = _auto_recovery_loop_summary(result_rejections)
    company_loop_context = _load_auto_company_loop_context(root)
    company_ledger_guidance = _auto_company_ledger_guidance(company_loop_context)
    result_contract_guidance = _auto_result_contract_guidance(result_rejections)
    skill_knowledge = _skill_knowledge_summary(root)
    worker_performance = _worker_performance_summary(root)
    relearning_review = _relearning_review_summary(root)
    decision_handoff = _auto_decision_handoff(status, task_statuses, step_results, release_gate, result_rejections)
    mission_status = _build_mission_status(root, status, task_statuses, step_results, release_gate, decision_handoff, proof_summary)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "mission_status": mission_status,
        "status": status,
        "plan_id": plan.get("plan_id"),
        "execution_runs": len(execution_log.get("runs", [])) if isinstance(execution_log.get("runs"), list) else 0,
        "task_statuses": task_statuses,
        "step_results": step_results,
        "result_rejections": result_rejections,
        "recovery_loop": recovery_loop,
        "release_gate": release_gate,
        "proof_summary": proof_summary,
        "company_loop_context": company_loop_context,
        "company_ledger_guidance": company_ledger_guidance,
        "result_contract_guidance": result_contract_guidance,
        "skill_knowledge": skill_knowledge,
        "worker_performance": worker_performance,
        "relearning_review": relearning_review,
        "decision_handoff": decision_handoff,
        "source_code_modified": False,
    }


def _boardroom_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    handoff = dict(report.get("decision_handoff") or {})
    task_statuses = dict(report.get("task_statuses") or {})
    step_results = dict(report.get("step_results") or {})
    result_rejections = dict(report.get("result_rejections") or {})
    recovery_loop = dict(report.get("recovery_loop") or {})
    release_gate = dict(report.get("release_gate") or {})
    proof_summary = dict(report.get("proof_summary") or {})
    company_loop_context = dict(report.get("company_loop_context") or {})
    company_ledger_guidance = dict(report.get("company_ledger_guidance") or {})
    result_contract_guidance = dict(report.get("result_contract_guidance") or {})
    skill_knowledge = dict(report.get("skill_knowledge") or {})
    worker_performance = dict(report.get("worker_performance") or {})
    relearning_review = dict(report.get("relearning_review") or {})
    mission_status = dict(report.get("mission_status") or {})
    return {
        "handoff_status": handoff.get("status") or "unknown",
        "handoff_reason": handoff.get("reason"),
        "mission_status": mission_status,
        "mission_next_task": mission_status.get("next_task", {}),
        "mission_completion_score": mission_status.get("completion_score"),
        "release_gate_verdict": release_gate.get("verdict"),
        "release_gate_ref": release_gate.get("release_gate_ref"),
        "release_gate_required_before_release": release_gate.get("required_before_release", []),
        "proof_summary": proof_summary,
        "proof_status": proof_summary.get("proof_status"),
        "proof_gaps": proof_summary.get("proof_gaps", []),
        "task_total": task_statuses.get("total", 0),
        "waiting_for_result": task_statuses.get("waiting_for_result", 0),
        "validated_results": step_results.get("validated", 0),
        "done_results": step_results.get("done", 0),
        "blocked_results": step_results.get("blocked", 0),
        "open_blockers": step_results.get("open_blockers", []),
        "quality_average": step_results.get("quality_average"),
        "quality_threshold": step_results.get("quality_threshold"),
        "quality_route": handoff.get("quality_route"),
        "low_quality_results": step_results.get("low_quality", 0),
        "low_quality_items": step_results.get("low_quality_results", []),
        "latest_result": step_results.get("latest", {}),
        "result_rejections": result_rejections,
        "recovery_loop": recovery_loop,
        "open_result_rejections": result_rejections.get("open_count", 0),
        "latest_rejection": result_rejections.get("latest", {}),
        "company_loop_context": company_loop_context,
        "company_ledger_guidance": company_ledger_guidance,
        "result_contract_guidance": result_contract_guidance,
        "skill_knowledge": skill_knowledge,
        "worker_performance": worker_performance,
        "relearning_review": relearning_review,
        "required_inputs": handoff.get("required_inputs", []),
        "input_request_refs": handoff.get("input_request_refs", []),
        "next_command": handoff.get("next_command"),
    }


def _build_mission_status(
    root: Path,
    status: dict[str, Any],
    task_statuses: dict[str, Any],
    step_results: dict[str, Any],
    release_gate: dict[str, Any],
    decision_handoff: dict[str, Any],
    proof_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    proof_summary = proof_summary or {}
    mission_path = default_auto_mission_path(root)
    mission = _load_yaml(mission_path) if mission_path.exists() else {}
    final_goal = str(mission.get("final_goal") or status.get("goal") or "").strip()
    next_task = _select_next_os_task(root)
    blockers = _mission_blockers(status, step_results, release_gate, decision_handoff, final_goal, mission_path.exists())
    completion_score = _mission_completion_score(status, task_statuses, step_results, release_gate, decision_handoff)
    release_verdict = str(release_gate.get("verdict") or "").upper()
    completion_state = "verified_complete" if release_verdict == "GO" and completion_score == 100 else "in_progress"
    if status.get("status") == "not_initialized":
        completion_state = "not_initialized"
    elif blockers:
        completion_state = "blocked" if _mission_has_hard_blocker(decision_handoff, release_gate) else "caution"
    evidence_status = "grounded" if mission_path.exists() and final_goal else "caution"
    if status.get("status") == "not_initialized" or not final_goal:
        evidence_status = "missing"
    return {
        "mission_kind": "auto_mission_control_v0_1",
        "status": completion_state,
        "evidence_status": evidence_status,
        "final_goal": final_goal or None,
        "current_phase": _mission_current_phase(status, decision_handoff),
        "next_task": next_task,
        "blockers": blockers,
        "completion_score": completion_score,
        "proof_summary": proof_summary,
        "completion_claim": {
            "can_claim_complete": completion_state == "verified_complete",
            "requires_release_gate_go": True,
            "release_gate_verdict": release_gate.get("verdict"),
            "proof_ref": release_gate.get("release_gate_ref"),
            "proof_status": proof_summary.get("proof_status"),
            "proof_gaps": proof_summary.get("proof_gaps", []),
            "runtime_evidence_required": True,
            "success_rate_allowed": bool(proof_summary.get("success_rate_allowed")),
            "success_rate": proof_summary.get("success_rate") if proof_summary.get("success_rate_allowed") else None,
        },
        "mission_ref": _relative(mission_path, root) if mission_path.exists() else None,
        "evidence_refs": _mission_evidence_refs(root, mission_path, next_task, release_gate),
    }


def _mission_current_phase(status: dict[str, Any], decision_handoff: dict[str, Any]) -> str:
    handoff_status = str(decision_handoff.get("status") or "").strip()
    if handoff_status in {
        "input_required",
        "needs_result_contract_correction",
        "needs_boardroom_review",
        "release_gate_go",
        "release_gate_conditional_go",
        "release_gate_no_go",
    }:
        return handoff_status
    state = str(status.get("state") or "").strip()
    if state:
        return state
    return str(status.get("status") or "unknown")


def _build_proof_summary(
    root: Path,
    status: dict[str, Any],
    task_statuses: dict[str, Any],
    step_results: dict[str, Any],
    release_gate: dict[str, Any],
) -> dict[str, Any]:
    latest_record = _latest_step_result_record(root, {"step_results": step_results})
    latest = step_results.get("latest", {}) if isinstance(step_results.get("latest"), dict) else {}
    tests = latest_record.get("tests", []) if latest_record else []
    evidence = latest_record.get("evidence", {}) if latest_record else {}
    validation_commands = _auto_validation_commands(latest_record) if latest_record else []
    runtime_evidence_present = _tests_have_content(tests)
    proof_artifact_present = _evidence_has_content(evidence)
    validated_result_present = int(step_results.get("validated", 0) or 0) > 0
    quality = latest.get("result_quality", {}) if isinstance(latest.get("result_quality"), dict) else {}
    strong_quality = str(quality.get("status") or "") == "strong" and int(quality.get("score") or 0) >= 90
    proof_gaps: list[str] = []
    if status.get("status") == "not_initialized":
        proof_gaps.append("auto mode is not initialized")
    if int(task_statuses.get("waiting_for_result", 0) or 0) > 0:
        proof_gaps.append("external worker result is pending")
    if not validated_result_present:
        proof_gaps.append("validated runtime result is missing")
    if not runtime_evidence_present:
        proof_gaps.append("runtime validation command evidence is missing")
    if not proof_artifact_present:
        proof_gaps.append("proof notes or artifacts are missing")
    if validated_result_present and not strong_quality:
        proof_gaps.append("strong result quality proof is missing")
    release_verdict = str(release_gate.get("verdict") or "").upper()
    proof_ready = validated_result_present and runtime_evidence_present and proof_artifact_present and strong_quality
    return {
        "schema_version": SCHEMA_VERSION,
        "proof_kind": "auto_validation_proof_loop_v0_1",
        "proof_status": "ready" if proof_ready else "gaps",
        "proof_ready": proof_ready,
        "proof_gaps": _auto_dedupe_text(proof_gaps),
        "preflight": {
            "auto_initialized": status.get("status") != "not_initialized",
            "task_total": task_statuses.get("total", 0),
            "waiting_for_result": task_statuses.get("waiting_for_result", 0),
        },
        "runtime_evidence": {
            "present": runtime_evidence_present,
            "validated_result_present": validated_result_present,
            "validation_commands": validation_commands,
            "latest_result_ref": latest.get("result_ref"),
        },
        "proof_evidence": {
            "present": proof_artifact_present,
            "result_quality_status": quality.get("status"),
            "result_quality_score": quality.get("score"),
            "evidence_artifacts": _auto_text_list(evidence.get("artifacts")) if isinstance(evidence, dict) else [],
        },
        "release_claim": {
            "release_gate_verdict": release_gate.get("verdict"),
            "can_claim_success": proof_ready and release_verdict == "GO",
            "success_rate_allowed": proof_ready,
        },
        "success_rate_allowed": proof_ready,
        "success_rate": 100 if proof_ready and release_verdict == "GO" else None,
    }


def _mission_blockers(
    status: dict[str, Any],
    step_results: dict[str, Any],
    release_gate: dict[str, Any],
    decision_handoff: dict[str, Any],
    final_goal: str,
    mission_exists: bool,
) -> list[str]:
    blockers: list[str] = []
    if status.get("status") == "not_initialized":
        blockers.append("auto mode is not initialized")
    if not final_goal:
        blockers.append("mission final_goal is missing")
    if not mission_exists:
        blockers.append("mission control state file is missing")
    result_rejections = decision_handoff.get("result_rejections", {})
    if not isinstance(result_rejections, dict):
        result_rejections = {}
    if int(result_rejections.get("open_count", 0) or 0) > 0:
        blockers.append("open result contract rejection requires correction")
    if decision_handoff.get("status") == "input_required":
        blockers.append("human input is required")
    if decision_handoff.get("status") == "waiting_for_external_result":
        blockers.append("external AI worker result is still pending")
    for item in step_results.get("open_blockers", []) or []:
        if not isinstance(item, dict):
            continue
        for blocker in item.get("blockers", []) or []:
            text = str(blocker).strip()
            if text:
                blockers.append(text)
    required = release_gate.get("required_before_release", [])
    if isinstance(required, list) and required and str(release_gate.get("verdict") or "").upper() != "GO":
        blockers.extend([str(item) for item in required if str(item).strip()])
    return _auto_dedupe_text(blockers)


def _save_mission_status_from_report(root: Path, report: dict[str, Any]) -> str | None:
    mission_status = report.get("mission_status", {})
    if not isinstance(mission_status, dict):
        return None
    final_goal = str(mission_status.get("final_goal") or "").strip()
    if not final_goal:
        return None
    mission_path = default_auto_mission_path(root)
    previous = _load_yaml(mission_path) if mission_path.exists() else {}
    mission = {
        "schema_version": SCHEMA_VERSION,
        "mission_kind": "auto_mission_control_v0_1",
        "created_at": previous.get("created_at") or _now(),
        "updated_at": _now(),
        "final_goal": final_goal,
        "status": mission_status.get("status"),
        "current_phase": mission_status.get("current_phase"),
        "next_task": mission_status.get("next_task", {}),
        "blockers": mission_status.get("blockers", []),
        "completion_score": mission_status.get("completion_score"),
        "completion_claim": mission_status.get("completion_claim", {}),
        "proof_summary": mission_status.get("proof_summary", {}),
        "evidence_refs": mission_status.get("evidence_refs", []),
        "completion_claim_policy": {
            "requires_release_gate_go": True,
            "no_success_rate_without_runtime_evidence": True,
        },
    }
    saved = _save_yaml(mission_path, mission)
    return _relative(saved, root)


def _mission_has_hard_blocker(decision_handoff: dict[str, Any], release_gate: dict[str, Any]) -> bool:
    handoff_status = str(decision_handoff.get("status") or "")
    if handoff_status in {"input_required", "needs_result_contract_correction", "needs_boardroom_review"}:
        return True
    return str(release_gate.get("verdict") or "").upper() == "NO-GO"


def _mission_completion_score(
    status: dict[str, Any],
    task_statuses: dict[str, Any],
    step_results: dict[str, Any],
    release_gate: dict[str, Any],
    decision_handoff: dict[str, Any],
) -> int:
    if status.get("status") == "not_initialized":
        return 0
    score = 10
    state = str(status.get("state") or "")
    if state in STATE_ORDER:
        score = max(score, min(65, 10 + (STATE_ORDER.index(state) * 5)))
    if int(task_statuses.get("waiting_for_result", 0) or 0) > 0:
        score = max(score, 35)
    if int(step_results.get("validated", 0) or 0) > 0:
        score = max(score, 70)
    if decision_handoff.get("status") == "ready_for_release_or_next_plan":
        score = max(score, 80)
    if int(step_results.get("done", 0) or 0) > 0:
        score = max(score, 85)
    verdict = str(release_gate.get("verdict") or "").upper()
    if verdict == "CONDITIONAL GO":
        score = max(score, 88)
    elif verdict == "NO-GO":
        score = min(score, 60)
    elif verdict == "GO":
        return 100
    if _mission_has_hard_blocker(decision_handoff, release_gate):
        score = min(score, 60)
    return max(0, min(score, 99))


def _mission_evidence_refs(root: Path, mission_path: Path, next_task: dict[str, Any], release_gate: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    if mission_path.exists():
        refs.append(_relative(mission_path, root))
    task_source = str(next_task.get("source") or "").strip()
    if task_source:
        refs.append(task_source)
    release_ref = str(release_gate.get("release_gate_ref") or "").strip()
    if release_ref:
        refs.append(release_ref)
    return _auto_dedupe_text(refs)


def _select_next_os_task(root: Path) -> dict[str, Any]:
    for backlog_path in _candidate_os_task_backlog_paths(root):
        if not backlog_path.exists():
            continue
        try:
            text = backlog_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        tasks = _parse_os_task_backlog(text)
        for task in tasks:
            if task.get("status") == "pending":
                task["selection_rule"] = "first_pending"
                task["source"] = _relative(backlog_path, root)
                return task
        if tasks:
            return {
                "id": "none",
                "title": "No pending AI Company OS task",
                "status": "completed",
                "selection_rule": "no_pending",
                "source": _relative(backlog_path, root),
            }
    return {
        "id": "project_next_step",
        "title": "Project next step",
        "status": "unknown",
        "selection_rule": "fallback_without_backlog",
        "source": None,
    }


def _candidate_os_task_backlog_paths(root: Path) -> list[Path]:
    package_root = Path(__file__).resolve().parents[1]
    return [
        Path(root).resolve() / "docs" / "product" / "45_AI_COMPANY_OS_TASK_BACKLOG.md",
        package_root / "docs" / "product" / "45_AI_COMPANY_OS_TASK_BACKLOG.md",
    ]


def _parse_os_task_backlog(text: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    pattern = re.compile(r"^### (OS-\d{2})\s+([^\n]+)\n(?P<body>.*?)(?=^### OS-\d{2}\s+|\Z)", re.M | re.S)
    for match in pattern.finditer(text):
        body = match.group("body")
        status_match = re.search(r"^status:\s*([^\n]+)", body, re.M)
        status = str(status_match.group(1)).strip() if status_match else "unknown"
        tasks.append(
            {
                "id": match.group(1),
                "title": match.group(2).strip(),
                "status": status,
            }
        )
    return tasks


def _auto_report_summary_matches_for_plan(boardroom_summary: dict[str, Any], current_summary: dict[str, Any]) -> bool:
    keys = [
        "handoff_status",
        "release_gate_verdict",
        "release_gate_ref",
        "task_total",
        "waiting_for_result",
        "validated_results",
        "done_results",
        "blocked_results",
        "quality_average",
        "quality_route",
        "low_quality_results",
        "open_result_rejections",
    ]
    for key in keys:
        if boardroom_summary.get(key) != current_summary.get(key):
            return False
    boardroom_latest = boardroom_summary.get("latest_result")
    current_latest = current_summary.get("latest_result")
    if not isinstance(boardroom_latest, dict):
        boardroom_latest = {}
    if not isinstance(current_latest, dict):
        current_latest = {}
    latest_keys = ["task_ref", "result_ref", "status"]
    if not all(boardroom_latest.get(key) == current_latest.get(key) for key in latest_keys):
        return False
    boardroom_rejection = boardroom_summary.get("latest_rejection")
    current_rejection = current_summary.get("latest_rejection")
    if not isinstance(boardroom_rejection, dict):
        boardroom_rejection = {}
    if not isinstance(current_rejection, dict):
        current_rejection = {}
    rejection_keys = ["task_ref", "rejection_ref", "error"]
    return all(boardroom_rejection.get(key) == current_rejection.get(key) for key in rejection_keys)


def _load_auto_company_loop_context(root: Path) -> dict[str, Any]:
    try:
        from engine.project_company_layer import load_company_loop_context

        return load_company_loop_context(root)
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": type(exc).__name__,
            "message": str(exc),
            "promotion_policy": {
                "auto_promote": False,
                "requires_user_review": True,
            },
        }


def _auto_company_ledger_guidance(company_loop_context: dict[str, Any]) -> dict[str, Any]:
    loop = company_loop_context if isinstance(company_loop_context, dict) else {}
    recent_context = [
        {
            "id": item.get("id"),
            "kind": item.get("kind"),
            "source": item.get("source"),
            "summary": item.get("summary"),
            "evidence_ref": item.get("evidence_ref"),
            "promotion_status": item.get("promotion_status"),
        }
        for item in loop.get("context_records", [])
        if isinstance(item, dict)
    ][-3:]
    recent_verification = [
        {
            "id": item.get("id"),
            "job_id": item.get("job_id"),
            "stage": item.get("stage"),
            "verdict": item.get("verdict"),
            "trust_gate_status": item.get("trust_gate_status"),
            "validation_commands": item.get("validation_commands", []),
            "unchecked_risk_count": item.get("unchecked_risk_count", 0),
            "unchecked_items": item.get("unchecked_items", []),
        }
        for item in loop.get("verification_entries", [])
        if isinstance(item, dict)
    ][-3:]
    unchecked_items = _auto_dedupe_text(
        [
            text
            for item in recent_verification
            if isinstance(item, dict)
            for text in _auto_text_list(item.get("unchecked_items"))
        ]
    )
    validation_commands = _auto_dedupe_text(
        [
            text
            for item in recent_verification
            if isinstance(item, dict)
            for text in _auto_text_list(item.get("validation_commands"))
        ]
    )
    recent_summaries = _auto_dedupe_text(
        [
            text
            for item in recent_context
            if isinstance(item, dict)
            for text in _auto_text_list(item.get("summary"))
        ]
    )
    promoted_memory = loop.get("promoted_memory", {}) if isinstance(loop.get("promoted_memory"), dict) else {}
    next_step_focus = "fresh_plan"
    if unchecked_items:
        next_step_focus = "resolve_unchecked_risk"
    elif recent_context:
        next_step_focus = "advance_from_candidate_context"
    return {
        "status": loop.get("status") or "empty",
        "context_records_ref": loop.get("context_records_ref"),
        "verification_ledger_ref": loop.get("verification_ledger_ref"),
        "promotion_review_ref": loop.get("promotion_review_ref"),
        "candidate_context_count": len(loop.get("candidate_context_records", []) if isinstance(loop.get("candidate_context_records"), list) else []),
        "promoted_memory_count": int(promoted_memory.get("total_count") or 0),
        "recent_context_records": recent_context,
        "recent_verification_entries": recent_verification,
        "recent_result_summaries": recent_summaries,
        "unchecked_items": unchecked_items,
        "validation_commands": validation_commands,
        "next_step_focus": next_step_focus,
        "duplicate_guard": {
            "mode": "do_not_repeat_prior_auto_result",
            "recent_summaries": recent_summaries,
            "requires_new_acceptance_delta": bool(recent_summaries),
        },
        "must_do": [
            "read company ledger before drafting the next auto step",
            "treat candidate context records as unapproved signals, not final memory",
            "carry forward unchecked risks into acceptance criteria",
            "do not auto-promote context; require user review",
        ],
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
        },
    }


def _auto_result_contract_guidance(result_rejections: dict[str, Any]) -> dict[str, Any]:
    rejections = result_rejections if isinstance(result_rejections, dict) else {}
    recovery_loop = _auto_recovery_loop_summary(rejections)
    total = int(rejections.get("total") or 0)
    if total <= 0:
        return {
            "status": "empty",
            "total_rejections": 0,
            "open_count": 0,
            "resolved_count": 0,
            "recovery_loop": recovery_loop,
        }
    latest = rejections.get("latest", {}) if isinstance(rejections.get("latest"), dict) else {}
    latest_resolution = rejections.get("latest_resolution", {}) if isinstance(rejections.get("latest_resolution"), dict) else {}
    open_count = int(rejections.get("open_count") or 0)
    resolved_count = int(rejections.get("resolved_count") or 0)
    recent_errors = _auto_text_list(latest.get("errors"))
    required_fields = _auto_text_list(latest.get("required_fields"))
    status = "open_rejection" if open_count else "available"
    next_step_focus = "fix_result_contract" if open_count else "prevent_contract_regression"
    return {
        "status": status,
        "total_rejections": total,
        "open_count": open_count,
        "resolved_count": resolved_count,
        "next_step_focus": next_step_focus,
        "latest_rejection_ref": latest.get("rejection_ref"),
        "latest_correction_directive_ref": latest.get("correction_directive_ref"),
        "latest_corrected_result_template_ref": latest.get("corrected_result_template_ref"),
        "latest_resolved_by_result_ref": latest.get("resolved_by_result_ref") or latest_resolution.get("resolved_by_result_ref"),
        "latest_resolution": latest_resolution,
        "resolved_mistake_refs": _auto_resolved_mistake_refs(rejections),
        "recent_errors": recent_errors,
        "required_fields": required_fields,
        "guidance_kind": "candidate_warning_not_promoted_memory",
        "recovery_loop": recovery_loop,
        "must_do": [
            "review prior result contract errors before writing the next auto result",
            "include every required result field even when the task seems simple",
            "do not treat rejected result files as proof or promoted memory",
            "carry resolved contract failures only as candidate warning guidance",
        ],
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
        },
    }


def _empty_skill_knowledge_ledger() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ledger_kind": "skill_knowledge_ledger_v0_1",
        "created_at": _now(),
        "updated_at": _now(),
        "candidates": [],
        "approved_knowledge": [],
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
            "candidate_warning_only": True,
        },
    }


def _load_skill_knowledge_ledger(root: Path) -> dict[str, Any]:
    path = default_skill_knowledge_ledger_path(root)
    if not path.exists():
        return _empty_skill_knowledge_ledger()
    try:
        payload = _load_yaml(path)
    except Exception:
        return _empty_skill_knowledge_ledger()
    if not isinstance(payload.get("candidates"), list):
        payload["candidates"] = []
    if not isinstance(payload.get("approved_knowledge"), list):
        payload["approved_knowledge"] = []
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("ledger_kind", "skill_knowledge_ledger_v0_1")
    payload.setdefault(
        "promotion_policy",
        {
            "auto_promote": False,
            "requires_user_review": True,
            "candidate_warning_only": True,
        },
    )
    return payload


def _empty_relearning_review() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "review_kind": "relearning_promotion_gate_v0_1",
        "created_at": _now(),
        "updated_at": _now(),
        "status": "pending_review",
        "review_items": [],
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
            "rebuild_candidates_visible_without_auto_apply": True,
        },
    }


def _load_relearning_review(root: Path) -> dict[str, Any]:
    path = default_relearning_review_path(root)
    if not path.exists():
        return _empty_relearning_review()
    try:
        payload = _load_yaml(path)
    except Exception:
        return _empty_relearning_review()
    if not isinstance(payload.get("review_items"), list):
        payload["review_items"] = []
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("review_kind", "relearning_promotion_gate_v0_1")
    payload.setdefault("status", "pending_review")
    payload.setdefault(
        "promotion_policy",
        {
            "auto_promote": False,
            "requires_user_review": True,
            "rebuild_candidates_visible_without_auto_apply": True,
        },
    )
    return payload


def record_relearning_review_candidate(
    root: Path,
    *,
    source: str,
    category: str,
    reason: str,
    evidence_refs: list[str],
    candidate_ref: str | None = None,
    rebuild_target: str | None = None,
) -> dict[str, Any]:
    evidence = _auto_dedupe_text(_auto_text_list(evidence_refs))
    if not evidence:
        return {"ok": False, "status": "rejected", "reason": "evidence_refs required", "auto_apply": False}
    review = _load_relearning_review(root)
    item = {
        "review_id": f"relearning-{_safe_slug(source or category)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}",
        "created_at": _now(),
        "status": "pending_user_review",
        "route": "relearning_review",
        "category": str(category or "knowledge"),
        "source": str(source or "unknown"),
        "reason": str(reason or "review required"),
        "candidate_ref": candidate_ref,
        "rebuild_target": rebuild_target,
        "evidence_refs": evidence,
        "auto_apply": False,
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
            "rebuild_candidate_only": True,
        },
    }
    items = review.get("review_items", [])
    if not isinstance(items, list):
        items = []
    items.append(item)
    review["review_items"] = items
    review["updated_at"] = _now()
    review_path = _save_yaml(default_relearning_review_path(root), review)
    return {
        "ok": True,
        "status": "pending_user_review",
        "review_id": item["review_id"],
        "review_ref": f"{_relative(review_path, root)}#review_items.{len(items) - 1}",
        "ledger_ref": _relative(review_path, root),
        "auto_apply": False,
    }


def _skill_candidate_requires_relearning(candidate: dict[str, Any]) -> bool:
    kind = str(candidate.get("knowledge_kind") or "").lower()
    text = " ".join([str(candidate.get("summary") or ""), str(candidate.get("warning") or "")]).lower()
    markers = ["rejection", "blocked", "failure", "failed", "conflict", "invalid", "do not repeat"]
    return any(marker in kind or marker in text for marker in markers)


def _skill_candidate_signature(candidate: dict[str, Any]) -> str:
    skills = ",".join(sorted(_auto_text_list(candidate.get("skill_ids"))))
    body = "|".join(
        [
            str(candidate.get("knowledge_kind") or ""),
            skills,
            str(candidate.get("summary") or "").strip().lower(),
            str(candidate.get("warning") or "").strip().lower(),
        ]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _apply_skill_candidate_promotion_gate(ledger: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if _skill_candidate_requires_relearning(candidate):
        candidate["approval_status"] = "relearning_review_required"
        candidate["status"] = "candidate"
        candidate["auto_promote"] = False
        candidate["promotion_ready"] = False
        candidate["promotion_policy"] = {
            "auto_promote": False,
            "requires_user_review": True,
            "route": "relearning_review",
        }
        return candidate
    signature = _skill_candidate_signature(candidate)
    same_verified = 1
    for item in ledger.get("candidates", []):
        if isinstance(item, dict) and _skill_candidate_signature(item) == signature:
            same_verified += 1
    candidate["verified_evidence_count"] = same_verified
    if same_verified >= 3:
        candidate["approval_status"] = "promotion_ready"
        candidate["promotion_ready"] = True
    else:
        candidate["approval_status"] = "candidate"
        candidate["promotion_ready"] = False
    candidate["status"] = "candidate"
    candidate["auto_promote"] = False
    candidate["promotion_policy"] = {
        "auto_promote": False,
        "requires_user_review": True,
        "minimum_verified_evidence": 3,
        "promotion_ready_not_auto_promoted": same_verified >= 3,
    }
    return candidate


def record_skill_knowledge_candidate(
    root: Path,
    *,
    source: str,
    skill_ids: list[str],
    summary: str,
    warning: str,
    evidence_refs: list[str],
    knowledge_kind: str = "runtime_warning",
) -> dict[str, Any]:
    evidence = _auto_dedupe_text(_auto_text_list(evidence_refs))
    if not evidence:
        return {
            "ok": False,
            "status": "rejected",
            "reason": "evidence_refs required",
            "auto_promote": False,
        }
    skills = _auto_dedupe_text([str(item) for item in skill_ids if str(item or "").strip()])
    if not skills:
        skills = ["auto-result-contract"]
    source_text = str(source or "runtime").strip() or "runtime"
    candidate_id = f"skill-knowledge-{_safe_slug(source_text)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"
    candidate = {
        "candidate_id": candidate_id,
        "created_at": _now(),
        "status": "candidate",
        "approval_status": "candidate",
        "knowledge_kind": str(knowledge_kind or "runtime_warning"),
        "skill_ids": skills,
        "summary": str(summary or "").strip(),
        "warning": str(warning or "").strip(),
        "source": source_text,
        "evidence_refs": evidence,
        "auto_promote": False,
        "approved": False,
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
            "candidate_warning_only": True,
        },
    }
    ledger = _load_skill_knowledge_ledger(root)
    candidate = _apply_skill_candidate_promotion_gate(ledger, candidate)
    ledger["updated_at"] = _now()
    candidates = ledger.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    candidates.append(candidate)
    ledger["candidates"] = candidates
    ledger.setdefault("approved_knowledge", [])
    ledger_path = _save_yaml(default_skill_knowledge_ledger_path(root), ledger)
    relearning_review = {}
    if _skill_candidate_requires_relearning(candidate):
        relearning_review = record_relearning_review_candidate(
            root,
            source=candidate_id,
            category="skill_knowledge",
            reason=str(candidate.get("warning") or candidate.get("summary") or "candidate requires relearning review"),
            candidate_ref=f"{_relative(ledger_path, root)}#candidates.{len(candidates) - 1}",
            rebuild_target=_short_join(_auto_text_list(candidate.get("skill_ids")), limit=4),
            evidence_refs=evidence,
        )
    return {
        "ok": True,
        "status": "candidate",
        "candidate_id": candidate_id,
        "candidate_ref": f"{_relative(ledger_path, root)}#candidates.{len(candidates) - 1}",
        "ledger_ref": _relative(ledger_path, root),
        "candidate": candidate,
        "relearning_review": relearning_review,
        "auto_promote": False,
    }


def suppress_skill_knowledge_candidate(
    root: Path,
    candidate_id: str,
    *,
    reason: str,
    action: str = "suppress",
) -> dict[str, Any]:
    ledger_path = default_skill_knowledge_ledger_path(root)
    if not ledger_path.exists():
        return {"ok": False, "status": "not_found", "reason": "skill knowledge ledger is missing"}
    ledger = _load_skill_knowledge_ledger(root)
    action_status = "archived" if str(action or "").strip().lower() == "archive" else "suppressed"
    candidates = ledger.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        if str(item.get("candidate_id") or "") != str(candidate_id or ""):
            continue
        item["status"] = action_status
        item["approval_status"] = action_status
        item["suppression"] = {
            "status": action_status,
            "reason": str(reason or "user suppressed candidate"),
            "updated_at": _now(),
            "auto_inject": False,
        }
        item["auto_promote"] = False
        ledger["updated_at"] = _now()
        _save_yaml(ledger_path, ledger)
        return {
            "ok": True,
            "status": action_status,
            "candidate_id": candidate_id,
            "candidate_ref": f"{_relative(ledger_path, root)}#candidates.{index}",
            "ledger_ref": _relative(ledger_path, root),
            "auto_inject": False,
        }
    return {"ok": False, "status": "not_found", "candidate_id": candidate_id}


def _skill_ids_for_task(task: dict[str, Any]) -> list[str]:
    skills = ["auto-result-contract"]
    job_bridge = task.get("job_bridge", {}) if isinstance(task.get("job_bridge"), dict) else {}
    selected_skills = job_bridge.get("selected_skills", [])
    if isinstance(selected_skills, list):
        skills.extend(str(item) for item in selected_skills if str(item or "").strip())
    owner = str(task.get("owner") or "").strip()
    if owner:
        skills.append(f"auto-role:{owner}")
    role_profile = task.get("role_profile", {}) if isinstance(task.get("role_profile"), dict) else {}
    role_id = str(role_profile.get("role_id") or "").strip()
    if role_id:
        skills.append(f"auto-role:{role_id}")
    return _auto_dedupe_text(skills)


def _skill_knowledge_summary(root: Path) -> dict[str, Any]:
    path = default_skill_knowledge_ledger_path(root)
    ledger = _load_skill_knowledge_ledger(root)
    candidates = [
        item
        for item in ledger.get("candidates", [])
        if isinstance(item, dict) and str(item.get("status") or "") not in {"suppressed", "archived"}
    ]
    approved = [item for item in ledger.get("approved_knowledge", []) if isinstance(item, dict)]
    suppressed_count = len(
        [
            item
            for item in ledger.get("candidates", [])
            if isinstance(item, dict) and str(item.get("status") or "") in {"suppressed", "archived"}
        ]
    )
    if not candidates and not approved:
        return {
            "status": "empty",
            "ledger_ref": _relative(path, root),
            "candidate_count": 0,
            "approved_count": 0,
            "suppressed_count": suppressed_count,
            "candidates": [],
            "approved_knowledge": [],
            "promotion_policy": dict(ledger.get("promotion_policy") or {}),
        }
    recent_candidates = candidates[-5:]
    return {
        "status": "available",
        "ledger_ref": _relative(path, root),
        "candidate_count": len(candidates),
        "approved_count": len(approved),
        "suppressed_count": suppressed_count,
        "candidates": [
            {
                "candidate_id": item.get("candidate_id"),
                "status": item.get("status"),
                "approval_status": item.get("approval_status"),
                "knowledge_kind": item.get("knowledge_kind"),
                "skill_ids": item.get("skill_ids", []),
                "summary": item.get("summary"),
                "warning": item.get("warning"),
                "evidence_refs": item.get("evidence_refs", []),
                "auto_promote": item.get("auto_promote"),
            }
            for item in recent_candidates
        ],
        "approved_knowledge": approved[-5:],
        "promotion_policy": dict(ledger.get("promotion_policy") or {}),
    }


def _skill_knowledge_guidance_for_task(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    ledger = _load_skill_knowledge_ledger(root)
    selected_skill_ids = _skill_ids_for_task(task)
    selected = set(selected_skill_ids)
    candidates = [
        item
        for item in ledger.get("candidates", [])
        if isinstance(item, dict) and str(item.get("status") or "") not in {"suppressed", "archived"}
    ]
    approved = [item for item in ledger.get("approved_knowledge", []) if isinstance(item, dict)]
    relevant_candidates = [
        item
        for item in candidates
        if selected.intersection(set(_auto_text_list(item.get("skill_ids"))))
    ]
    relevant_approved = [
        item
        for item in approved
        if selected.intersection(set(_auto_text_list(item.get("skill_ids"))))
    ]
    if not relevant_candidates and not relevant_approved:
        return {
            "status": "empty",
            "ledger_ref": _relative(default_skill_knowledge_ledger_path(root), root),
            "selected_skill_ids": selected_skill_ids,
            "candidate_count": 0,
            "approved_count": 0,
            "candidate_warnings": [],
            "approved_knowledge": [],
            "promotion_policy": {
                "auto_promote": False,
                "requires_user_review": True,
                "candidate_warning_only": True,
            },
        }
    recent_candidates = relevant_candidates[-5:]
    return {
        "status": "candidate_available" if relevant_candidates else "approved_available",
        "ledger_ref": _relative(default_skill_knowledge_ledger_path(root), root),
        "selected_skill_ids": selected_skill_ids,
        "candidate_count": len(relevant_candidates),
        "approved_count": len(relevant_approved),
        "candidate_warnings": [
            {
                "candidate_id": item.get("candidate_id"),
                "knowledge_kind": item.get("knowledge_kind"),
                "summary": item.get("summary"),
                "warning": item.get("warning"),
                "evidence_refs": item.get("evidence_refs", []),
                "auto_promote": item.get("auto_promote"),
                "approval_status": item.get("approval_status"),
            }
            for item in recent_candidates
        ],
        "approved_knowledge": relevant_approved[-5:],
        "promotion_policy": {
            "auto_promote": False,
            "requires_user_review": True,
            "candidate_warning_only": True,
        },
    }


def _skill_knowledge_warning_for_result(status: str, result_record: dict[str, Any]) -> str:
    normalized = str(status or "").strip().lower()
    blockers = _auto_text_list(result_record.get("blockers"))
    tests = result_record.get("tests", [])
    failed_tests = []
    if isinstance(tests, list):
        failed_tests = [
            str(item.get("command") or item.get("name") or item)
            for item in tests
            if isinstance(item, dict) and str(item.get("status") or item.get("result") or "").strip().lower() in {"failed", "fail", "error"}
        ]
    if normalized == "blocked" or blockers:
        return f"Prior step was blocked; review blockers before reusing this skill pattern: {_short_join(blockers or failed_tests, limit=4)}."
    if failed_tests:
        return f"Prior step had failing validation; do not treat it as proof: {_short_join(failed_tests, limit=4)}."
    return "Prior step completed with evidence; treat this as candidate skill guidance only until user review promotes it."


def _empty_worker_performance_ledger() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ledger_kind": "worker_performance_ledger_v0_1",
        "created_at": _now(),
        "updated_at": _now(),
        "minimum_samples_for_confidence": 5,
        "events": [],
        "aggregates": {},
        "dispatch_policy": {
            "hard_lock_choices": False,
            "low_sample_size_caution": True,
            "minimum_samples_for_confidence": 5,
        },
    }


def _load_worker_performance_ledger(root: Path) -> dict[str, Any]:
    path = default_worker_performance_ledger_path(root)
    if not path.exists():
        return _empty_worker_performance_ledger()
    try:
        payload = _load_yaml(path)
    except Exception:
        return _empty_worker_performance_ledger()
    if not isinstance(payload.get("events"), list):
        payload["events"] = []
    if not isinstance(payload.get("aggregates"), dict):
        payload["aggregates"] = {}
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("ledger_kind", "worker_performance_ledger_v0_1")
    payload.setdefault("minimum_samples_for_confidence", 5)
    payload.setdefault(
        "dispatch_policy",
        {
            "hard_lock_choices": False,
            "low_sample_size_caution": True,
            "minimum_samples_for_confidence": 5,
        },
    )
    return payload


def _worker_identity_for_task(task: dict[str, Any]) -> dict[str, Any]:
    job_bridge = task.get("job_bridge", {}) if isinstance(task.get("job_bridge"), dict) else {}
    agents = _auto_text_list(job_bridge.get("selected_agents"))
    skills = _auto_text_list(job_bridge.get("selected_skills"))
    owner = str(task.get("owner") or "").strip()
    if not agents and owner:
        agents = [f"auto-role:{owner}"]
    agents.append("auto-worker")
    if not skills:
        skills = _skill_ids_for_task(task)
    return {
        "owner": owner or "auto-agent",
        "job_id": job_bridge.get("job_id") or task.get("task_id"),
        "selected_agents": _auto_dedupe_text(agents),
        "selected_skills": _auto_dedupe_text(skills),
        "dispatch_reason": job_bridge.get("dispatch_reason"),
    }


def _worker_combo_key(agent_id: str, skill_id: str) -> str:
    return f"{_safe_slug(agent_id)}__{_safe_slug(skill_id)}"


def record_worker_performance_event(
    root: Path,
    *,
    task: dict[str, Any],
    outcome: str,
    status: str,
    evidence_refs: list[str],
    result_quality: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    blockers: list[str] | None = None,
    resolved_rejections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = _auto_dedupe_text(_auto_text_list(evidence_refs))
    if not evidence:
        return {"ok": False, "status": "rejected", "reason": "evidence_refs required"}
    identity = _worker_identity_for_task(task)
    agents = identity["selected_agents"] or [f"auto-role:{identity['owner']}"]
    skills = identity["selected_skills"] or ["auto-result-contract"]
    quality = result_quality if isinstance(result_quality, dict) else {}
    event = {
        "event_id": f"worker-performance-{_stamp()}-{datetime.now(timezone.utc).strftime('%f')}",
        "created_at": _now(),
        "outcome": str(outcome or "unknown"),
        "status": str(status or "unknown"),
        "task_id": task.get("task_id"),
        "task_ref": task.get("task_ref") or task.get("directive_ref"),
        "owner": identity["owner"],
        "job_id": identity.get("job_id"),
        "selected_agents": agents,
        "selected_skills": skills,
        "dispatch_reason": identity.get("dispatch_reason"),
        "result_quality": quality,
        "errors": _auto_text_list(errors or []),
        "blockers": _auto_text_list(blockers or []),
        "resolved_rejection_count": int((resolved_rejections or {}).get("count") or 0) if isinstance(resolved_rejections, dict) else 0,
        "evidence_refs": evidence,
    }
    ledger = _load_worker_performance_ledger(root)
    events = ledger.get("events", [])
    if not isinstance(events, list):
        events = []
    events.append(event)
    ledger["events"] = events
    ledger["aggregates"] = _worker_performance_aggregates(events, int(ledger.get("minimum_samples_for_confidence") or 3))
    ledger["updated_at"] = _now()
    ledger_path = _save_yaml(default_worker_performance_ledger_path(root), ledger)
    relearning_review = {}
    if str(outcome or "") in {"rejected", "blocked"} or _auto_text_list(errors or []) or _auto_text_list(blockers or []):
        relearning_review = record_relearning_review_candidate(
            root,
            source=event["event_id"],
            category="worker_performance",
            reason=f"Worker performance event needs review before promotion: outcome={event['outcome']}, status={event['status']}",
            rebuild_target=_short_join([*agents, *skills], limit=6),
            evidence_refs=evidence,
            candidate_ref=f"{_relative(ledger_path, root)}#events.{len(events) - 1}",
        )
    return {
        "ok": True,
        "status": "recorded",
        "event_id": event["event_id"],
        "ledger_ref": _relative(ledger_path, root),
        "relearning_review": relearning_review,
        "aggregate_keys": _worker_event_combo_keys(event),
    }


def _worker_event_combo_keys(event: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for agent in _auto_text_list(event.get("selected_agents")):
        for skill in _auto_text_list(event.get("selected_skills")):
            keys.append(_worker_combo_key(agent, skill))
    return _auto_dedupe_text(keys)


def _worker_performance_aggregates(events: list[Any], minimum_samples: int) -> dict[str, Any]:
    aggregates: dict[str, Any] = {}
    for raw in events:
        if not isinstance(raw, dict):
            continue
        outcome = str(raw.get("outcome") or "")
        quality = raw.get("result_quality", {}) if isinstance(raw.get("result_quality"), dict) else {}
        quality_score = int(quality.get("score") or 0) if str(quality.get("score") or "").isdigit() else 0
        passed = outcome in {"validated", "done", "success"} or str(quality.get("status") or "") in {"strong", "usable"}
        rejected = outcome == "rejected"
        blocked = outcome == "blocked" or bool(_auto_text_list(raw.get("blockers")))
        retry_count = int(raw.get("resolved_rejection_count") or 0)
        for key in _worker_event_combo_keys(raw):
            item = aggregates.setdefault(
                key,
                {
                    "combo_key": key,
                    "agent_id": None,
                    "skill_id": None,
                    "sample_count": 0,
                    "validated_count": 0,
                    "rejection_count": 0,
                    "blocker_count": 0,
                    "retry_count": 0,
                    "quality_score_total": 0,
                    "recent_event_refs": [],
                },
            )
            agent_id, skill_id = _worker_combo_parts_for_key(raw, key)
            item["agent_id"] = item.get("agent_id") or agent_id
            item["skill_id"] = item.get("skill_id") or skill_id
            item["sample_count"] += 1
            item["validated_count"] += 1 if passed else 0
            item["rejection_count"] += 1 if rejected else 0
            item["blocker_count"] += 1 if blocked else 0
            item["retry_count"] += retry_count
            item["quality_score_total"] += quality_score
            refs = item.get("recent_event_refs", [])
            if isinstance(refs, list):
                refs.append(raw.get("event_id"))
                item["recent_event_refs"] = refs[-5:]
    for item in aggregates.values():
        samples = int(item.get("sample_count") or 0)
        validated = int(item.get("validated_count") or 0)
        rejections = int(item.get("rejection_count") or 0)
        blockers = int(item.get("blocker_count") or 0)
        retries = int(item.get("retry_count") or 0)
        quality_average = int(item.get("quality_score_total") or 0) / samples if samples else 0.0
        score = max(0, min(100, int((validated / samples * 100 if samples else 0) + (quality_average * 0.2) - (rejections * 20) - (blockers * 15) - (retries * 5))))
        item["quality_average"] = round(quality_average, 2)
        item["validated_rate"] = round(validated / samples, 3) if samples else 0
        item["rejection_rate"] = round(rejections / samples, 3) if samples else 0
        item["blocker_rate"] = round(blockers / samples, 3) if samples else 0
        item["performance_score"] = score
        item["confidence"] = "low_data" if samples < minimum_samples else "evidence_backed"
        item["caution"] = "low_sample_size" if samples < minimum_samples else None
    return aggregates


def _worker_combo_parts_for_key(event: dict[str, Any], key: str) -> tuple[str | None, str | None]:
    for agent in _auto_text_list(event.get("selected_agents")):
        for skill in _auto_text_list(event.get("selected_skills")):
            if _worker_combo_key(agent, skill) == key:
                return agent, skill
    return None, None


def _worker_performance_summary(root: Path) -> dict[str, Any]:
    path = default_worker_performance_ledger_path(root)
    ledger = _load_worker_performance_ledger(root)
    events = [item for item in ledger.get("events", []) if isinstance(item, dict)]
    aggregates = ledger.get("aggregates", {}) if isinstance(ledger.get("aggregates"), dict) else {}
    if not events:
        return {
            "status": "empty",
            "ledger_ref": _relative(path, root),
            "event_count": 0,
            "aggregate_count": 0,
            "minimum_samples_for_confidence": int(ledger.get("minimum_samples_for_confidence") or 3),
            "dispatch_policy": dict(ledger.get("dispatch_policy") or {}),
        }
    ranked = sorted(
        [item for item in aggregates.values() if isinstance(item, dict)],
        key=lambda item: (int(item.get("performance_score") or 0), int(item.get("sample_count") or 0)),
        reverse=True,
    )
    return {
        "status": "available",
        "ledger_ref": _relative(path, root),
        "event_count": len(events),
        "aggregate_count": len(aggregates),
        "minimum_samples_for_confidence": int(ledger.get("minimum_samples_for_confidence") or 3),
        "top_combinations": ranked[:5],
        "low_data_count": len([item for item in aggregates.values() if isinstance(item, dict) and item.get("confidence") == "low_data"]),
        "dispatch_policy": dict(ledger.get("dispatch_policy") or {}),
    }


def _worker_performance_guidance_for_task(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    ledger = _load_worker_performance_ledger(root)
    aggregates = ledger.get("aggregates", {}) if isinstance(ledger.get("aggregates"), dict) else {}
    identity = _worker_identity_for_task(task)
    agents = identity["selected_agents"] or [f"auto-role:{identity['owner']}"]
    skills = identity["selected_skills"] or _skill_ids_for_task(task)
    relevant: list[dict[str, Any]] = []
    for agent in agents:
        for skill in skills:
            item = aggregates.get(_worker_combo_key(agent, skill))
            if isinstance(item, dict):
                relevant.append(dict(item))
    minimum = int(ledger.get("minimum_samples_for_confidence") or 3)
    if not relevant:
        return {
            "status": "empty",
            "ledger_ref": _relative(default_worker_performance_ledger_path(root), root),
            "selected_agents": agents,
            "selected_skills": skills,
            "minimum_samples_for_confidence": minimum,
            "hints": [],
            "dispatch_policy": dict(ledger.get("dispatch_policy") or {}),
        }
    relevant = sorted(relevant, key=lambda item: int(item.get("performance_score") or 0), reverse=True)
    return {
        "status": "available",
        "ledger_ref": _relative(default_worker_performance_ledger_path(root), root),
        "selected_agents": agents,
        "selected_skills": skills,
        "minimum_samples_for_confidence": minimum,
        "hints": relevant[:5],
        "low_data_caution": any(str(item.get("confidence") or "") == "low_data" for item in relevant),
        "dispatch_policy": dict(ledger.get("dispatch_policy") or {}),
    }


def _relearning_review_summary(root: Path) -> dict[str, Any]:
    path = default_relearning_review_path(root)
    review = _load_relearning_review(root)
    items = [item for item in review.get("review_items", []) if isinstance(item, dict)]
    pending = [item for item in items if str(item.get("status") or "") == "pending_user_review"]
    if not items:
        return {
            "status": "empty",
            "review_ref": _relative(path, root),
            "review_item_count": 0,
            "pending_count": 0,
            "promotion_policy": dict(review.get("promotion_policy") or {}),
        }
    return {
        "status": "pending_user_review" if pending else "available",
        "review_ref": _relative(path, root),
        "review_item_count": len(items),
        "pending_count": len(pending),
        "recent_review_items": items[-5:],
        "promotion_policy": dict(review.get("promotion_policy") or {}),
    }


def generate_company_snapshot(project_root: Path, *, out: Path | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    snapshot_id = f"company-snapshot-{_stamp()}-{datetime.now(timezone.utc).strftime('%f')}"
    report = _build_auto_report(root)
    source_refs = _company_snapshot_source_refs(root)
    source_hashes = _company_snapshot_source_hashes(root, source_refs)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_kind": "company_snapshot_v0_1",
        "snapshot_id": snapshot_id,
        "generated_at": _now(),
        "company_artifact": {
            "artifact_kind": "ai_company_os_marketplace_ready_snapshot",
            "marketplace_layer": "future_after_runtime_proof_maturity",
            "export_scope": "summaries_hashes_and_lineage_only",
        },
        "marketplace": {
            "visibility": "private",
            "public_listing_allowed": False,
            "sale_ready": False,
            "proof_claim_allowed": False,
            "reason": "Company snapshot is exportable for review, but marketplace sale remains future layer until runtime proof maturity.",
        },
        "privacy_boundary": {
            "raw_private_project_data_included": False,
            "source_file_contents_included": False,
            "secrets_included": False,
            "private_paths_excluded": [
                ".env",
                ".cambrian/input_answers/",
                ".cambrian/auto/results/",
                ".cambrian/auto/tasks/",
                ".cambrian/auto/corrections/",
                ".cambrian/auto/external_results/",
            ],
            "public_safe_content": ["counts", "relative refs", "sha256 fingerprints", "proof summaries", "lineage summaries"],
        },
        "company_components": _company_snapshot_components(root, report),
        "proof_summary": _company_snapshot_proof_summary(report),
        "evolution_lineage": _company_snapshot_lineage(root, report, source_refs, source_hashes),
        "known_limits": _company_snapshot_known_limits(report),
        "provenance": {
            "generated_by": "engine.project_auto_mode.generate_company_snapshot",
            "source_refs": source_refs,
            "source_sha256": source_hashes,
            "signature_ready": True,
        },
    }
    snapshot["body_sha256"] = _stable_payload_sha256(snapshot)
    validation = validate_company_snapshot(snapshot)
    snapshot["validation"] = validation
    target = out
    if target is None:
        target = default_company_snapshots_dir(root) / f"{snapshot_id}.yaml"
    target = target if target.is_absolute() else (root / target)
    saved = _save_yaml(target, snapshot)
    return {
        "ok": validation["status"] == "pass",
        "status": "snapshot_generated",
        "snapshot": snapshot,
        "snapshot_ref": _relative(saved, root) if _is_within(root, saved) else str(saved),
        "body_sha256": snapshot["body_sha256"],
        "source_code_modified": False,
        "provider_api_called": False,
    }


def validate_company_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "snapshot_kind": snapshot.get("snapshot_kind") == "company_snapshot_v0_1",
        "marketplace_private": (snapshot.get("marketplace") or {}).get("visibility") == "private",
        "sale_blocked": (snapshot.get("marketplace") or {}).get("sale_ready") is False,
        "proof_claim_blocked": (snapshot.get("marketplace") or {}).get("proof_claim_allowed") is False,
        "raw_private_data_excluded": (snapshot.get("privacy_boundary") or {}).get("raw_private_project_data_included") is False,
        "source_contents_excluded": (snapshot.get("privacy_boundary") or {}).get("source_file_contents_included") is False,
        "proof_summary_present": isinstance(snapshot.get("proof_summary"), dict) and bool(snapshot.get("proof_summary")),
        "lineage_present": isinstance(snapshot.get("evolution_lineage"), dict) and bool(snapshot.get("evolution_lineage")),
        "provenance_hashes_present": bool((snapshot.get("provenance") or {}).get("source_sha256")),
        "body_hash_present": isinstance(snapshot.get("body_sha256"), str) and len(str(snapshot.get("body_sha256"))) == 64,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "validator": "company_snapshot_validator_v0_1",
        "checks": checks,
    }


def _company_snapshot_source_refs(root: Path) -> list[str]:
    candidates = [
        default_auto_mission_path(root),
        default_auto_report_path(root),
        default_auto_execution_log_path(root),
        default_skill_knowledge_ledger_path(root),
        default_worker_performance_ledger_path(root),
        default_relearning_review_path(root),
        root / ".cambrian" / "company" / "context" / "records.yaml",
        root / ".cambrian" / "company" / "verification" / "ledger.yaml",
        root / ".cambrian" / "custom_harness" / "harness.yaml",
        root / ".cambrian" / "workforce" / "workforce.yaml",
    ]
    refs = [_relative(path, root) for path in candidates if path.exists() and _is_within(root, path)]
    return _auto_dedupe_text(refs)


def _company_snapshot_source_hashes(root: Path, refs: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for ref in refs:
        path = (root / ref).resolve()
        if not path.exists() or not _is_within(root, path):
            continue
        hashes[ref] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _company_snapshot_components(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    skill_knowledge = report.get("skill_knowledge", {}) if isinstance(report.get("skill_knowledge"), dict) else {}
    worker_performance = report.get("worker_performance", {}) if isinstance(report.get("worker_performance"), dict) else {}
    relearning = report.get("relearning_review", {}) if isinstance(report.get("relearning_review"), dict) else {}
    company_ledger = report.get("company_ledger_guidance", {}) if isinstance(report.get("company_ledger_guidance"), dict) else {}
    return {
        "harness": {
            "installed": (root / ".cambrian" / "custom_harness").exists(),
            "raw_config_included": False,
        },
        "company_ledgers": {
            "context_candidate_count": int(company_ledger.get("candidate_context_count") or 0),
            "promoted_memory_count": int(company_ledger.get("promoted_memory_count") or 0),
        },
        "skills": {
            "candidate_count": int(skill_knowledge.get("candidate_count") or 0),
            "approved_count": int(skill_knowledge.get("approved_count") or 0),
            "suppressed_count": int(skill_knowledge.get("suppressed_count") or 0),
        },
        "workers": {
            "performance_event_count": int(worker_performance.get("event_count") or 0),
            "aggregate_count": int(worker_performance.get("aggregate_count") or 0),
            "low_data_count": int(worker_performance.get("low_data_count") or 0),
        },
        "relearning": {
            "review_item_count": int(relearning.get("review_item_count") or 0),
            "pending_count": int(relearning.get("pending_count") or 0),
        },
    }


def _company_snapshot_proof_summary(report: dict[str, Any]) -> dict[str, Any]:
    proof = report.get("proof_summary", {}) if isinstance(report.get("proof_summary"), dict) else {}
    release_gate = report.get("release_gate", {}) if isinstance(report.get("release_gate"), dict) else {}
    mission = report.get("mission_status", {}) if isinstance(report.get("mission_status"), dict) else {}
    return {
        "proof_status": proof.get("proof_status"),
        "proof_ready": proof.get("proof_ready"),
        "proof_gaps": proof.get("proof_gaps", []),
        "runtime_validation_evidence": proof.get("runtime_validation_evidence", {}),
        "release_verdict": release_gate.get("verdict"),
        "release_gate_ref": release_gate.get("release_gate_ref"),
        "mission_completion_state": mission.get("completion_state"),
        "completion_score": mission.get("completion_score"),
        "success_rate_claim": None,
        "raw_runtime_outputs_included": False,
    }


def _company_snapshot_lineage(root: Path, report: dict[str, Any], source_refs: list[str], source_hashes: dict[str, str]) -> dict[str, Any]:
    mission = report.get("mission_status", {}) if isinstance(report.get("mission_status"), dict) else {}
    return {
        "lineage_kind": "company_snapshot_lineage_v0_1",
        "mission_next_task": mission.get("next_task", {}),
        "source_refs": source_refs,
        "source_sha256": source_hashes,
        "decision_handoff": report.get("decision_handoff", {}),
        "recovery_loop": report.get("recovery_loop", {}),
        "relearning_review": report.get("relearning_review", {}),
        "private_content_policy": "refs_and_hashes_only",
    }


def _company_snapshot_known_limits(report: dict[str, Any]) -> list[str]:
    limits = [
        "Snapshot is private review artifact; marketplace sale is blocked until runtime proof maturity.",
        "Raw project files, secrets, AI replies, and result bodies are excluded.",
    ]
    proof = report.get("proof_summary", {}) if isinstance(report.get("proof_summary"), dict) else {}
    for gap in _auto_text_list(proof.get("proof_gaps")):
        limits.append(f"proof_gap: {gap}")
    return _auto_dedupe_text(limits)


def _auto_recovery_loop_summary(result_rejections: dict[str, Any]) -> dict[str, Any]:
    rejections = result_rejections if isinstance(result_rejections, dict) else {}
    total = int(rejections.get("total") or 0)
    open_count = int(rejections.get("open_count") or 0)
    resolved_count = int(rejections.get("resolved_count") or 0)
    latest = rejections.get("latest", {}) if isinstance(rejections.get("latest"), dict) else {}
    latest_resolution = rejections.get("latest_resolution", {}) if isinstance(rejections.get("latest_resolution"), dict) else {}
    if open_count > 0:
        status = "correction_required"
        next_guidance = "correct rejected result before planning unrelated work"
    elif resolved_count > 0:
        status = "resolved_guidance_available"
        next_guidance = "warn next worker about resolved contract failure without promoting it to memory"
    elif total > 0:
        status = "recorded"
        next_guidance = "review rejection history"
    else:
        status = "none"
        next_guidance = "no recovery history"
    return {
        "schema_version": SCHEMA_VERSION,
        "loop_kind": "auto_rejection_correction_recovery_v0_1",
        "status": status,
        "flow": ["rejection", "correction", "resolved", "next_guidance"],
        "total_rejections": total,
        "open_count": open_count,
        "resolved_count": resolved_count,
        "latest_rejection_ref": latest.get("rejection_ref"),
        "latest_correction_directive_ref": latest.get("correction_directive_ref"),
        "latest_corrected_result_template_ref": latest.get("corrected_result_template_ref"),
        "latest_resolved_by_result_ref": latest.get("resolved_by_result_ref") or latest_resolution.get("resolved_by_result_ref"),
        "latest_errors": _auto_text_list(latest.get("errors")),
        "next_guidance": next_guidance,
        "promotion_policy": {
            "auto_promote": False,
            "candidate_warning_only": True,
            "requires_user_review": True,
        },
    }


def _auto_resolved_mistake_refs(result_rejections: dict[str, Any]) -> list[str]:
    latest = result_rejections.get("latest", {}) if isinstance(result_rejections.get("latest"), dict) else {}
    latest_resolution = (
        result_rejections.get("latest_resolution", {}) if isinstance(result_rejections.get("latest_resolution"), dict) else {}
    )
    return _auto_dedupe_text(
        [
            *_auto_text_list(latest.get("rejection_ref")),
            *_auto_text_list(latest.get("correction_directive_ref")),
            *_auto_text_list(latest.get("corrected_result_template_ref")),
            *_auto_text_list(latest.get("resolved_by_result_ref")),
            *_auto_text_list(latest_resolution.get("resolved_by_result_ref")),
        ]
    )


def _attach_result_contract_guidance_to_steps(steps: list[dict[str, Any]], guidance: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(guidance, dict) or str(guidance.get("status") or "") in {"", "empty"}:
        return steps
    enriched: list[dict[str, Any]] = []
    for step in steps:
        item = dict(step)
        item["result_contract_guidance"] = guidance
        item["task"] = _task_with_result_contract_guidance(str(item.get("task") or ""), guidance)
        criteria = item.get("success_criteria", [])
        if not isinstance(criteria, list):
            criteria = []
        item["success_criteria"] = _auto_dedupe_text(
            [
                *[str(entry) for entry in criteria],
                "result contract history reviewed",
                *_result_contract_success_criteria(guidance),
            ]
        )
        enriched.append(item)
    return enriched


def _task_with_result_contract_guidance(task: str, guidance: dict[str, Any]) -> str:
    text = task.strip() or "Execute the next auto step"
    parts = [text]
    errors = _auto_text_list(guidance.get("recent_errors"))
    required_fields = _auto_text_list(guidance.get("required_fields"))
    if errors:
        parts.append(f"Do not repeat prior result contract error: {_short_join(errors, limit=3)}.")
    if required_fields:
        parts.append(f"Preserve required result fields: {_short_join(required_fields, limit=6)}.")
    recovery_loop = guidance.get("recovery_loop", {}) if isinstance(guidance.get("recovery_loop"), dict) else {}
    if str(recovery_loop.get("status") or "") == "resolved_guidance_available":
        parts.append("Treat the resolved contract failure as candidate warning guidance, not promoted memory.")
    return " ".join(parts)


def _result_contract_success_criteria(guidance: dict[str, Any]) -> list[str]:
    criteria = ["rejected result not reused as proof"]
    required_fields = _auto_text_list(guidance.get("required_fields"))
    if required_fields:
        criteria.append(f"required result fields preserved: {_short_join(required_fields, limit=6)}")
    if int(guidance.get("resolved_count") or 0) > 0:
        criteria.append("prior result contract rejection did not recur")
    return criteria


def _attach_company_ledger_guidance_to_steps(steps: list[dict[str, Any]], guidance: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(guidance, dict) or str(guidance.get("status") or "") in {"", "empty"}:
        return steps
    enriched: list[dict[str, Any]] = []
    for step in steps:
        item = dict(step)
        item["company_ledger_guidance"] = guidance
        item["task"] = _task_with_company_ledger_guidance(str(item.get("task") or ""), guidance)
        criteria = item.get("success_criteria", [])
        if not isinstance(criteria, list):
            criteria = []
        item["success_criteria"] = _auto_dedupe_text(
            [
                *[str(entry) for entry in criteria],
                "company ledger context reviewed",
                *_ledger_success_criteria(guidance),
            ]
        )
        enriched.append(item)
    return enriched


def _task_with_company_ledger_guidance(task: str, guidance: dict[str, Any]) -> str:
    text = task.strip() or "Execute the next auto step"
    parts = [text]
    focus = str(guidance.get("next_step_focus") or "")
    summaries = _auto_text_list(guidance.get("recent_result_summaries"))
    unchecked = _auto_text_list(guidance.get("unchecked_items"))
    if focus == "resolve_unchecked_risk" and unchecked:
        parts.append(f"Company ledger requires resolving unchecked risk: {_short_join(unchecked)}.")
    elif summaries:
        parts.append(f"Do not repeat prior auto result; advance from: {_short_join(summaries)}.")
    validation_commands = _auto_text_list(guidance.get("validation_commands"))
    if validation_commands:
        parts.append(f"Carry forward validation command evidence: {_short_join(validation_commands)}.")
    return " ".join(parts)


def _ledger_success_criteria(guidance: dict[str, Any]) -> list[str]:
    criteria = ["prior candidate context not repeated"]
    unchecked = _auto_text_list(guidance.get("unchecked_items"))
    if unchecked:
        criteria.append(f"unchecked risk addressed: {_short_join(unchecked)}")
    validation_commands = _auto_text_list(guidance.get("validation_commands"))
    if validation_commands:
        criteria.append(f"validation command carried forward: {_short_join(validation_commands)}")
    duplicate_guard = guidance.get("duplicate_guard", {}) if isinstance(guidance.get("duplicate_guard"), dict) else {}
    if duplicate_guard.get("requires_new_acceptance_delta"):
        criteria.append("new acceptance delta defined")
    return criteria


def _short_join(items: list[str], limit: int = 2) -> str:
    selected = [str(item) for item in items if str(item).strip()][:limit]
    if not selected:
        return "none"
    suffix = "" if len(items) <= limit else f" (+{len(items) - limit} more)"
    return "; ".join(selected) + suffix


def _boardroom_evidence_refs(report_ref: str, report_summary: dict[str, Any]) -> list[str]:
    refs: list[str] = [report_ref]
    latest_result = report_summary.get("latest_result", {})
    if isinstance(latest_result, dict):
        refs.extend(
            [
                str(latest_result.get("task_ref") or ""),
                str(latest_result.get("result_ref") or ""),
            ]
        )
    latest_rejection = report_summary.get("latest_rejection", {})
    if isinstance(latest_rejection, dict):
        refs.extend(
            [
                str(latest_rejection.get("task_ref") or ""),
                str(latest_rejection.get("rejection_ref") or ""),
                str(latest_rejection.get("correction_directive_ref") or ""),
            ]
        )
    mission = report_summary.get("mission_status", {})
    if isinstance(mission, dict):
        refs.append(str(mission.get("mission_ref") or ""))
        refs.extend(_auto_text_list(mission.get("evidence_refs")))
    refs.extend(_auto_text_list(report_summary.get("input_request_refs")))
    refs.append(str(report_summary.get("release_gate_ref") or ""))
    return _auto_dedupe_text([ref for ref in refs if ref])


def _boardroom_evidence_citations(report_summary: dict[str, Any], evidence_refs: list[str]) -> list[dict[str, Any]]:
    citations = [
        {
            "kind": "auto_report",
            "ref": evidence_refs[0] if evidence_refs else ".cambrian/auto/report.yaml",
            "supports": ["handoff_status", "next_command", "mission_status"],
            "handoff_status": report_summary.get("handoff_status"),
        }
    ]
    latest_result = report_summary.get("latest_result", {})
    if isinstance(latest_result, dict) and latest_result:
        citations.append(
            {
                "kind": "latest_result",
                "ref": latest_result.get("result_ref") or latest_result.get("task_ref"),
                "supports": ["validated_results", "blocked_results", "quality_route"],
                "status": latest_result.get("status"),
            }
        )
    latest_rejection = report_summary.get("latest_rejection", {})
    if isinstance(latest_rejection, dict) and latest_rejection:
        citations.append(
            {
                "kind": "latest_rejection",
                "ref": latest_rejection.get("rejection_ref") or latest_rejection.get("task_ref"),
                "supports": ["result_contract_correction", "required_fields"],
                "error": latest_rejection.get("error"),
            }
        )
    release_gate_ref = str(report_summary.get("release_gate_ref") or "")
    if release_gate_ref:
        citations.append(
            {
                "kind": "release_gate",
                "ref": release_gate_ref,
                "supports": ["release_gate_verdict", "release_gate_required_before_release"],
                "verdict": report_summary.get("release_gate_verdict"),
            }
        )
    return [item for item in citations if item.get("ref")]


def _attach_boardroom_evidence_to_decisions(
    decisions: dict[str, Any],
    evidence_refs: list[str],
    report_summary: dict[str, Any],
) -> dict[str, Any]:
    citations = _boardroom_evidence_citations(report_summary, evidence_refs)
    enriched: dict[str, Any] = {}
    for role, decision in decisions.items():
        if not isinstance(decision, dict):
            continue
        item = dict(decision)
        item["role"] = role
        item["evidence_refs"] = evidence_refs
        item["evidence_citations"] = citations
        item["source_handoff_status"] = report_summary.get("handoff_status")
        enriched[role] = item
    return enriched


def _boardroom_decision_lineage(
    *,
    meeting_id: str,
    meeting_ref: str,
    decision_ref: str,
    report_ref: str,
    report_summary: dict[str, Any],
    decisions: dict[str, Any],
) -> dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "boardroom_ref": meeting_ref,
        "decision_ref": decision_ref,
        "source_auto_report": report_ref,
        "handoff_status": report_summary.get("handoff_status"),
        "next_command": report_summary.get("next_command"),
        "report_evidence_refs": _boardroom_evidence_refs(report_ref, report_summary),
        "decision_roles": sorted(decisions.keys()),
        "stale_guard": {
            "summary_keys": [
                "handoff_status",
                "release_gate_verdict",
                "release_gate_ref",
                "task_total",
                "waiting_for_result",
                "validated_results",
                "done_results",
                "blocked_results",
                "quality_average",
                "quality_route",
                "low_quality_results",
                "open_result_rejections",
            ],
            "latest_result_keys": ["task_ref", "result_ref", "status"],
            "latest_rejection_keys": ["task_ref", "rejection_ref", "error"],
        },
    }


def _plan_decision_lineage(meeting: dict[str, Any], meeting_path: Path, root: Path) -> dict[str, Any]:
    lineage = meeting.get("decision_lineage", {})
    if not isinstance(lineage, dict):
        lineage = {}
    result = dict(lineage)
    result.setdefault("boardroom_ref", _relative(meeting_path, root))
    result.setdefault("decision_ref", meeting.get("decision_ref"))
    result.setdefault("source_auto_report", meeting.get("source_auto_report"))
    result.setdefault("handoff_status", (meeting.get("auto_report_summary") or {}).get("handoff_status") if isinstance(meeting.get("auto_report_summary"), dict) else None)
    result["decisions"] = meeting.get("decisions", {})
    return result


def _attach_boardroom_decision_lineage_to_steps(
    steps: list[dict[str, Any]],
    decision_lineage: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(decision_lineage, dict):
        return steps
    decisions = decision_lineage.get("decisions", {})
    if not isinstance(decisions, dict):
        decisions = {}
    enriched: list[dict[str, Any]] = []
    for step in steps:
        item = dict(step)
        role = _boardroom_role_for_owner(str(item.get("owner") or ""))
        decision = decisions.get(role) if isinstance(decisions.get(role), dict) else {}
        item["boardroom_decision_lineage"] = {
            "boardroom_ref": decision_lineage.get("boardroom_ref"),
            "decision_ref": decision_lineage.get("decision_ref"),
            "source_auto_report": decision_lineage.get("source_auto_report"),
            "handoff_status": decision_lineage.get("handoff_status"),
            "role": role,
        }
        if decision:
            item["boardroom_role_decision"] = decision
            item["decision_evidence_refs"] = decision.get("evidence_refs", [])
        criteria = item.get("success_criteria", [])
        if not isinstance(criteria, list):
            criteria = []
        item["success_criteria"] = _auto_dedupe_text(
            [
                *[str(entry) for entry in criteria],
                "boardroom decision evidence cited",
            ]
        )
        enriched.append(item)
    return enriched


def _boardroom_role_for_owner(owner: str) -> str:
    normalized = owner.lower()
    if "release" in normalized:
        return "release_manager"
    if "qa" in normalized:
        return "qa"
    if "cto" in normalized or "architect" in normalized:
        return "cto"
    if "engineering" in normalized or "engineer" in normalized:
        return "engineering"
    if "pm" in normalized or "product" in normalized:
        return "pm"
    if "coo" in normalized or "ops" in normalized:
        return "coo"
    if "ceo" in normalized:
        return "ceo"
    return "coo"


def _boardroom_agenda(goal: str, report_summary: dict[str, Any]) -> str:
    status = str(report_summary.get("handoff_status") or "")
    if status == "auto_done":
        return "Confirm auto loop completion and preserve the evidence trail"
    if status == "release_gate_go":
        return "Confirm release gate GO and prepare the next product iteration"
    if status == "release_gate_conditional_go":
        return "Review conditional release gate evidence and decide required cleanup"
    if status == "release_gate_no_go":
        return "Review release gate NO-GO evidence and create recovery plan"
    if status == "needs_boardroom_review":
        return "Review blocked auto step results and decide the next recovery plan"
    if status == "needs_result_contract_correction":
        return "Review rejected auto result contract and request a corrected result file"
    if status == "ready_for_release_or_next_plan":
        route = str(report_summary.get("quality_route") or "")
        if route == "release_gate":
            return "Review strong validated auto step result quality and decide release gate readiness"
        if route == "next_product_step":
            return "Review usable validated auto step result quality and define the next product step"
        return "Review validated auto step results and decide the next plan or release gate"
    if status == "needs_result_quality_review":
        return "Review low-quality auto step results before release or next planning"
    if status == "waiting_for_external_result":
        return "Wait for Codex/Claude result intake before changing the plan"
    if status == "input_required":
        return "Wait for required human input before changing the plan"
    if status == "needs_validation":
        return "Decide how to validate the ingested auto step result"
    if goal:
        return f"Decide next step for product completion: {goal}"
    return "Decide next step for product completion"


def _boardroom_recommended_next_action(report_summary: dict[str, Any]) -> str | None:
    status = str(report_summary.get("handoff_status") or "")
    if status == "auto_done":
        return None
    if status == "release_gate_go":
        return _explicit_next_goal_command()
    if status == "needs_result_contract_correction":
        return "cambrian auto plan --json"
    if status == "waiting_for_external_result":
        return "cambrian auto step ingest <task-ref> --result step_result.yaml --json"
    if status == "input_required":
        return None
    return "cambrian auto plan --json"


def _boardroom_decisions(goal: str, authority_mode: str, report_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = report_summary or {}
    handoff_status = str(summary.get("handoff_status") or "")
    blocker_count = int(summary.get("blocked_results") or 0)
    waiting_count = int(summary.get("waiting_for_result") or 0)
    validated_count = int(summary.get("validated_results") or 0)
    done_count = int(summary.get("done_results") or 0)
    decisions = {
        "ceo": {
            "decision": "Focus on installable custom harness workflow before broad product surface.",
            "reason": "Core product value is project-specific AI workforce creation.",
        },
        "cto": {
            "decision": "Avoid large CLI refactor; add authority and auto state modules only.",
            "reason": "Minimize structural risk before the next RC gate.",
        },
        "coo": {
            "decision": "Run in bounded cycles with evidence after each step.",
            "reason": "Prevent uncontrolled long-running automation.",
        },
        "pm": {
            "decision": "Create narrow implementation tasks with explicit validation gates.",
            "reason": "Codex needs bounded instructions and acceptance criteria.",
        },
        "engineering": {
            "decision": "Generate execution proposals before modifying source.",
            "reason": f"Current authority mode is {authority_mode}.",
        },
        "qa": {
            "decision": "Treat tests and smoke gates as release blockers only when they affect the selected scope.",
            "reason": "Keep validation proportional to the local RC goal.",
        },
        "release_manager": {
            "decision": "Require release gate evidence before tagging.",
            "reason": "Release artifacts need traceable local proof.",
        },
    }
    if handoff_status == "auto_done":
        decisions["ceo"] = {
            "decision": "Stop the current auto loop and keep the evidence trail as the completion record.",
            "reason": f"{done_count} completed result(s) indicate no further automatic task is needed.",
        }
        decisions["coo"] = {
            "decision": "Do not create another execution task unless a new goal is started.",
            "reason": "The latest result explicitly marked the loop as done.",
        }
        decisions["release_manager"] = {
            "decision": "Preserve the final report and release evidence instead of opening another release task.",
            "reason": "Completion should terminate the current bounded loop.",
        }
    elif handoff_status == "release_gate_go":
        decisions["ceo"] = {
            "decision": "Accept the release gate GO and start the next product iteration only with a new goal.",
            "reason": f"Release gate package {summary.get('release_gate_ref') or 'latest'} has a GO verdict.",
        }
        decisions["coo"] = {
            "decision": "Archive the completed loop before opening another auto iteration.",
            "reason": "The next loop should not reuse stale release gate evidence.",
        }
        decisions["release_manager"] = {
            "decision": "Preserve the GO evidence package as the release decision record.",
            "reason": "The release gate is the close-out artifact for this iteration.",
        }
    elif handoff_status == "release_gate_conditional_go":
        required = summary.get("release_gate_required_before_release") or []
        decisions["ceo"] = {
            "decision": "Allow conditional progress only after required release-gate cleanup is explicit.",
            "reason": f"Conditional release gate still requires: {_blocker_summary(required)}.",
        }
        decisions["pm"] = {
            "decision": "Convert the conditional release requirements into a bounded cleanup task.",
            "reason": "Conditional GO should not silently become full GO.",
        }
        decisions["release_manager"] = {
            "decision": "Keep the release gate open until required evidence is resolved or deferred.",
            "reason": "Release evidence is incomplete.",
        }
    elif handoff_status == "release_gate_no_go":
        required = summary.get("release_gate_required_before_release") or []
        decisions["ceo"] = {
            "decision": "Do not proceed to release or next iteration until NO-GO evidence is addressed.",
            "reason": f"Release gate is missing: {_blocker_summary(required)}.",
        }
        decisions["qa"] = {
            "decision": "Classify the NO-GO evidence as release-blocking validation work.",
            "reason": "NO-GO means the current loop lacks sufficient trusted evidence.",
        }
        decisions["pm"] = {
            "decision": "Create a recovery plan from the release gate missing evidence.",
            "reason": "The next Codex directive must target the release blocker, not a new feature.",
        }
    elif handoff_status == "needs_boardroom_review":
        decisions["ceo"] = {
            "decision": "Stop forward planning until blocked auto step results are understood.",
            "reason": f"{blocker_count} blocked result(s) require recovery before the next build cycle.",
        }
        decisions["cto"] = {
            "decision": "Classify the blocker root cause before changing architecture.",
            "reason": "Blocked Codex/Claude output should become a bounded fix task, not a broad refactor.",
        }
        decisions["pm"] = {
            "decision": "Write the next plan around the blocker and required validation evidence.",
            "reason": "The next Codex directive must include the failing evidence and recovery criteria.",
        }
        decisions["qa"] = {
            "decision": "Keep the blocker as release-blocking until validation evidence is ingested.",
            "reason": "Auto report marked the result as blocked.",
        }
    elif handoff_status == "needs_result_contract_correction":
        latest_rejection = summary.get("latest_rejection", {}) if isinstance(summary.get("latest_rejection"), dict) else {}
        errors = latest_rejection.get("errors", [])
        decisions["coo"] = {
            "decision": "Keep the current task waiting and do not create unrelated implementation work.",
            "reason": "The latest Codex/Claude result failed the required result contract.",
        }
        decisions["pm"] = {
            "decision": "Request a corrected result file that satisfies every missing contract field.",
            "reason": f"Rejected result errors: {_blocker_summary(errors)}.",
        }
        decisions["qa"] = {
            "decision": "Treat the rejection as contract evidence, not product validation evidence.",
            "reason": "Invalid result files must not enter Company Ledger or release proof.",
        }
    elif handoff_status == "ready_for_release_or_next_plan":
        quality_route = str(summary.get("quality_route") or "")
        if quality_route == "release_gate":
            decisions["ceo"] = {
                "decision": "Move the strong validated result into release gate review.",
                "reason": f"{validated_count} validated result(s) have enough quality for release-gate consideration.",
            }
            decisions["pm"] = {
                "decision": "Do not broaden scope; preserve the accepted result as release evidence.",
                "reason": "Strong result quality should harden the gate instead of creating unrelated work.",
            }
            decisions["release_manager"] = {
                "decision": "Check whether the strong auto result is enough for the release gate.",
                "reason": "Release decisions require traceable local evidence and a final go/no-go judgment.",
            }
        elif quality_route == "next_product_step":
            decisions["ceo"] = {
                "decision": "Use the validated result as a base for the next bounded product step.",
                "reason": "The result is usable, but not strong enough to skip directly to release gate.",
            }
            decisions["pm"] = {
                "decision": "Convert the usable result into a narrower next product task.",
                "reason": "The next plan should improve evidence depth while keeping momentum.",
            }
            decisions["qa"] = {
                "decision": "Add validation expectations that would raise the next result to strong quality.",
                "reason": "Usable quality can advance only with explicit follow-up validation.",
            }
        else:
            decisions["ceo"] = {
                "decision": "Continue toward the next plan or release gate using validated evidence.",
                "reason": f"{validated_count} validated result(s) are available for the next decision.",
            }
            decisions["pm"] = {
                "decision": "Convert validated evidence into the next bounded plan step.",
                "reason": "The next plan should build on the accepted result instead of restarting from defaults.",
            }
            decisions["release_manager"] = {
                "decision": "Check whether the validated result is enough for a release gate.",
                "reason": "Release decisions require traceable local evidence.",
            }
    elif handoff_status == "needs_result_quality_review":
        quality_average = summary.get("quality_average")
        decisions["ceo"] = {
            "decision": "Do not advance to release or the next build plan until result quality is reviewed.",
            "reason": f"Latest validated result quality is below threshold: {quality_average}.",
        }
        decisions["pm"] = {
            "decision": "Ask for a tighter role-specific result file before replanning.",
            "reason": "The result passed the structural contract but did not provide enough useful evidence.",
        }
        decisions["qa"] = {
            "decision": "Classify which role output or evidence signal is weak.",
            "reason": "Validated status is not enough without usable role output quality.",
        }
    elif handoff_status == "waiting_for_external_result":
        decisions["coo"] = {
            "decision": "Do not create a new plan while task directives are still waiting for results.",
            "reason": f"{waiting_count} task directive(s) still need result intake.",
        }
        decisions["pm"] = {
            "decision": "Ask Codex/Claude to return the result file before replanning.",
            "reason": "Planning without external execution evidence would break the auto loop.",
        }
    elif handoff_status == "input_required":
        required = summary.get("required_inputs") or []
        decisions["ceo"] = {
            "decision": "Pause the auto loop until the required human input is supplied.",
            "reason": f"Missing input blocks safe execution: {_blocker_summary(required)}.",
        }
        decisions["coo"] = {
            "decision": "Do not create another boardroom-plan-run cycle while input is missing.",
            "reason": "Repeating the loop would only create duplicate blocked recovery tasks.",
        }
        decisions["pm"] = {
            "decision": "Produce a concise input request instead of a new implementation task.",
            "reason": "The next useful action belongs to the human, not the auto runner.",
        }
        decisions["qa"] = {
            "decision": "Keep implementation blocked until the input has traceable evidence.",
            "reason": "Missing external facts must not be replaced by guesses.",
        }
    elif handoff_status == "needs_validation":
        decisions["qa"] = {
            "decision": "Request explicit validation evidence before release or next-cycle planning.",
            "reason": "A result was ingested without enough test or validation proof.",
        }
        decisions["pm"] = {
            "decision": "Create a validation-focused next step.",
            "reason": "The loop needs trustworthy evidence before moving forward.",
        }
    return decisions


def _default_plan_steps() -> list[dict[str, Any]]:
    return [
        {
            "id": "step-001",
            "owner": "pm-agent",
            "task": "Write a bounded Codex implementation directive",
            "success_criteria": ["scope bounded", "tests defined"],
            "required_permissions": ["filesystem_read"],
        },
        {
            "id": "step-002",
            "owner": "cto-agent",
            "task": "Review architecture and risk before implementation",
            "success_criteria": ["risk noted", "no large refactor"],
            "required_permissions": ["filesystem_read"],
        },
        {
            "id": "step-003",
            "owner": "engineering-agent",
            "task": "Create an execution proposal for the next product change",
            "success_criteria": ["changed files listed", "rollback hint present"],
            "required_permissions": ["filesystem_write", "command_exec"],
        },
        {
            "id": "step-004",
            "owner": "qa-agent",
            "task": "Plan validation commands for the proposed change",
            "success_criteria": ["test command selected", "failure mode documented"],
            "required_permissions": ["test_run"],
        },
        {
            "id": "step-005",
            "owner": "release-manager-agent",
            "task": "Prepare release gate checklist",
            "success_criteria": ["artifact gate identified", "release decision pending"],
            "required_permissions": ["build_artifact"],
        },
    ]


def _plan_steps_from_handoff(report_summary: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    status = str(report_summary.get("handoff_status") or "")
    if status == "auto_done":
        return "done", []
    if status == "release_gate_go":
        return "next_iteration", _next_iteration_plan_steps(report_summary)
    if status == "release_gate_conditional_go":
        return "conditional_release_review", _conditional_release_plan_steps(report_summary)
    if status == "release_gate_no_go":
        return "release_gate_recovery", _release_gate_recovery_plan_steps(report_summary)
    if status == "needs_boardroom_review":
        return "recovery", _recovery_plan_steps(report_summary)
    if status == "needs_result_contract_correction":
        return "result_contract_correction", _result_contract_correction_plan_steps(report_summary)
    if status == "ready_for_release_or_next_plan":
        quality_route = str(report_summary.get("quality_route") or "")
        if quality_route == "release_gate":
            return "release_gate", _release_gate_plan_steps(report_summary)
        if quality_route == "next_product_step":
            return "next_product_step", _next_product_step_plan_steps(report_summary)
        return "validated_next", _validated_next_plan_steps(report_summary)
    if status == "needs_result_quality_review":
        return "quality_review", _quality_review_plan_steps(report_summary)
    if status == "waiting_for_external_result":
        return "result_intake", _result_intake_plan_steps(report_summary)
    if status == "input_required":
        return "input_wait", []
    if status == "needs_validation":
        return "validation", _validation_plan_steps(report_summary)
    return "default", _default_plan_steps()


def _cycle_stop_from_handoff(handoff: dict[str, Any]) -> dict[str, Any] | None:
    status = str(handoff.get("status") or "")
    if status == "input_required":
        return {
            "stop_condition": "input_required",
            "reason": handoff.get("reason") or "Auto loop needs human input before continuing.",
            "next_command": None,
        }
    if status == "release_gate_go":
        return {
            "stop_condition": "release_gate_go",
            "reason": handoff.get("reason") or "Release gate returned GO; current loop is complete.",
            "next_command": handoff.get("next_command") or _explicit_next_goal_command(),
        }
    if status == "auto_done":
        return {
            "stop_condition": "auto_done",
            "reason": handoff.get("reason") or "The current auto loop is done.",
            "next_command": None,
        }
    if status == "authority_required":
        return {
            "stop_condition": "authority_required",
            "reason": handoff.get("reason") or "Additional authority is required before continuing.",
            "next_command": handoff.get("next_command") or "cambrian authority grant --mode full-authority --json",
        }
    if status == "hard_safety_block":
        return {
            "stop_condition": "hard_safety_block",
            "reason": handoff.get("reason") or "A hard safety block stopped the loop.",
            "next_command": None,
        }
    return None


def _cycle_stopped(
    root: Path,
    cycle_id: str,
    report_payload: dict[str, Any],
    handoff: dict[str, Any],
    stop: dict[str, Any],
    *,
    max_steps: int,
) -> dict[str, Any]:
    plan_kind = "done" if stop.get("stop_condition") == "auto_done" else None
    if stop.get("stop_condition") == "input_required":
        request_refs = _ensure_input_request_files(root, handoff)
        if request_refs:
            handoff = dict(handoff)
            handoff["input_request_refs"] = request_refs
        _pause_for_input_required(root, handoff)
    elif stop.get("stop_condition") == "auto_done":
        _update_state(root, "DONE")
    next_decision = {
        "status": "stopped",
        "stop_condition": stop.get("stop_condition"),
        "reason": stop.get("reason"),
        "next_command": stop.get("next_command"),
    }
    cycle_record = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "created_at": _now(),
        "max_steps": max(0, min(int(max_steps or 0), 50)),
        "status": "stopped",
        "stop_condition": stop.get("stop_condition"),
        "report_ref": report_payload.get("report_ref"),
        "handoff_status": handoff.get("status"),
        "plan_kind": plan_kind,
        "handoff": handoff,
        "next_decision": next_decision,
        "run": {
            "executed_steps": 0,
            "blocked_steps": [],
            "task_refs": [],
            "directive_refs": [],
            "waiting_for_result": 0,
            "next_state": None,
        },
        "source_code_modified": False,
        "provider_api_called": False,
    }
    cycle_path = _save_yaml(default_auto_cycles_dir(root) / f"{cycle_id}.yaml", cycle_record)
    loop_state_path = _write_auto_cycle_state(root, cycle_record, cycle_path)
    append_authority_log(
        root,
        command=f"cambrian auto cycle --max-steps {cycle_record['max_steps']}",
        mode=str(load_authority_profile(root)["mode"]),
        result=f"auto_cycle_stopped_{stop.get('stop_condition')}",
        changed_files=[_relative(cycle_path, root), _relative(loop_state_path, root)],
        rollback_hint="Remove the auto cycle stop record if this orchestration was not intended.",
    )
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "cycle_ref": _relative(cycle_path, root),
        "cycle_state_ref": _relative(loop_state_path, root),
        "max_steps": cycle_record["max_steps"],
        "cycle_status": "stopped",
        "stop_condition": stop.get("stop_condition"),
        "handoff_status": handoff.get("status"),
        "plan_kind": plan_kind,
        "report_ref": report_payload.get("report_ref"),
        "executed_steps": 0,
        "blocked_steps": [],
        "task_refs": [],
        "directive_refs": [],
        "waiting_for_result": 0,
        "next_decision": next_decision,
        "source_code_modified": False,
        "provider_api_called": False,
        "next_command": next_decision.get("next_command"),
    }


def _cycle_blocked(
    root: Path,
    cycle_id: str,
    failed_step: str,
    payload: dict[str, Any],
    *,
    max_steps: int,
) -> dict[str, Any]:
    next_decision = {
        "status": "blocked",
        "failed_step": failed_step,
        "reason": _short_join(payload.get("errors", [f"auto cycle failed at {failed_step}"]), limit=3),
        "next_command": payload.get("next_command"),
    }
    cycle_record = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "created_at": _now(),
        "max_steps": max(0, min(int(max_steps or 0), 50)),
        "status": "blocked",
        "failed_step": failed_step,
        "errors": payload.get("errors", [f"auto cycle failed at {failed_step}"]),
        "next_decision": next_decision,
        "source_code_modified": False,
        "provider_api_called": False,
    }
    cycle_path = _save_yaml(default_auto_cycles_dir(root) / f"{cycle_id}.yaml", cycle_record)
    loop_state_path = _write_auto_cycle_state(root, cycle_record, cycle_path)
    return {
        "ok": False,
        "cycle_id": cycle_id,
        "cycle_ref": _relative(cycle_path, root),
        "cycle_state_ref": _relative(loop_state_path, root),
        "cycle_status": "blocked",
        "failed_step": failed_step,
        "errors": payload.get("errors", [f"auto cycle failed at {failed_step}"]),
        "payload": payload,
        "next_decision": next_decision,
        "source_code_modified": False,
        "provider_api_called": False,
        "next_command": payload.get("next_command"),
    }


def _cycle_next_decision(
    *,
    handoff_status: Any,
    run_payload: dict[str, Any],
    plan_payload: dict[str, Any],
) -> dict[str, Any]:
    blocked_steps = run_payload.get("blocked_steps", [])
    if isinstance(blocked_steps, list) and blocked_steps:
        return {
            "status": "authority_required",
            "reason": "At least one planned auto step is blocked by missing permissions.",
            "blocked_steps": blocked_steps,
            "next_command": "cambrian authority grant --mode full-authority --json",
        }
    if run_payload.get("next_state") == "DONE":
        return {
            "status": "done",
            "reason": "The current loop produced a done plan.",
            "next_command": None,
        }
    task_refs = run_payload.get("task_refs", [])
    if isinstance(task_refs, list) and task_refs:
        first = str(task_refs[0])
        return {
            "status": "waiting_for_external_result",
            "reason": "A bounded task directive was created and needs result intake.",
            "next_command": f"cambrian auto step ingest {first} --result step_result.yaml --json",
        }
    return {
        "status": str(handoff_status or "ready_for_report"),
        "reason": "No task directive was created; refresh the report to choose the next safe action.",
        "plan_kind": plan_payload.get("plan_kind"),
        "next_command": "cambrian auto report --json",
    }


def _write_auto_cycle_state(root: Path, cycle_record: dict[str, Any], cycle_path: Path) -> Path:
    state_path = default_auto_cycle_state_path(root)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "loop_kind": "auto_completion_loop_v0_1",
        "latest_cycle_id": cycle_record.get("cycle_id"),
        "latest_cycle_ref": _relative(cycle_path, root),
        "latest_status": cycle_record.get("status"),
        "latest_stop_condition": cycle_record.get("stop_condition"),
        "handoff_status": cycle_record.get("handoff_status"),
        "next_decision": cycle_record.get("next_decision", {}),
        "evidence_refs": [_relative(cycle_path, root)],
        "stop_conditions": [
            "input_required",
            "authority_required",
            "release_gate_go",
            "auto_done",
            "hard_safety_block",
        ],
        "source_code_modified": False,
        "provider_api_called": False,
    }
    return _save_yaml(state_path, payload)


def _recovery_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = report_summary.get("open_blockers", [])
    blocker_text = _blocker_summary(blockers)
    return [
        {
            "id": "step-001",
            "owner": "pm-agent",
            "task": f"Write a recovery directive for blocked auto result: {blocker_text}",
            "success_criteria": ["blocker reproduced", "recovery scope bounded", "validation command defined"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "needs_boardroom_review",
        },
        {
            "id": "step-002",
            "owner": "qa-agent",
            "task": "Define validation evidence required to unblock the auto step",
            "success_criteria": ["failing evidence referenced", "pass criteria written"],
            "required_permissions": ["test_run"],
            "handoff_status": "needs_boardroom_review",
        },
        {
            "id": "step-003",
            "owner": "engineering-agent",
            "task": "Create a bounded fix proposal for the blocked auto step",
            "success_criteria": ["changed files listed", "rollback hint present", "no broad refactor"],
            "required_permissions": ["filesystem_write", "command_exec"],
            "handoff_status": "needs_boardroom_review",
        },
    ]


def _result_contract_correction_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    latest = report_summary.get("latest_rejection", {})
    if not isinstance(latest, dict):
        latest = {}
    errors = _auto_text_list(latest.get("errors"))
    required_fields = _auto_text_list(latest.get("required_fields"))
    task_ref = str(latest.get("task_ref") or "<task-ref>")
    source_result = str(latest.get("source_result_ref") or "rejected result")
    correction_ref = str(latest.get("correction_directive_ref") or "")
    template_ref = str(latest.get("corrected_result_template_ref") or "")
    error_text = _short_join(errors, limit=8)
    field_text = _short_join(required_fields, limit=6)
    correction_note = f" Read correction directive: {correction_ref}." if correction_ref else ""
    return [
        {
            "id": "step-001",
            "owner": "pm-agent",
            "task": f"Request a corrected auto result file for {task_ref}: {error_text}. Source: {source_result}.{correction_note}",
            "success_criteria": [
                "rejection errors referenced",
                "required fields listed",
                "corrected ingest command prepared",
                "correction directive referenced",
            ],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "needs_result_contract_correction",
            "rejection_ref": latest.get("rejection_ref"),
            "correction_directive_ref": latest.get("correction_directive_ref"),
            "corrected_result_template_ref": latest.get("corrected_result_template_ref"),
            "required_fields": required_fields,
        },
        {
            "id": "step-002",
            "owner": "qa-agent",
            "task": f"Verify the corrected result contract includes required fields: {field_text}. Template: {template_ref or 'inline contract example'}",
            "success_criteria": [
                "missing contract fields resolved",
                "company ledger compliance included when required",
                "invalid result not promoted as proof",
            ],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "needs_result_contract_correction",
            "rejection_ref": latest.get("rejection_ref"),
            "correction_directive_ref": latest.get("correction_directive_ref"),
            "corrected_result_template_ref": latest.get("corrected_result_template_ref"),
        },
    ]


def _next_iteration_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    release_ref = report_summary.get("release_gate_ref") or "latest release gate"
    return [
        {
            "id": "step-001",
            "owner": "release-manager-agent",
            "task": f"Preserve GO release gate evidence before next iteration: {release_ref}",
            "success_criteria": ["GO package referenced", "next iteration requires explicit goal", "no stale gate reused"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "release_gate_go",
        },
        {
            "id": "step-002",
            "owner": "pm-agent",
            "task": "Draft the next product iteration goal without reopening the completed release gate",
            "success_criteria": ["new goal drafted", "old loop archived", "scope remains bounded"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "release_gate_go",
        },
    ]


def _conditional_release_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    required = report_summary.get("release_gate_required_before_release") or []
    required_text = _blocker_summary(required)
    return [
        {
            "id": "step-001",
            "owner": "release-manager-agent",
            "task": f"Review conditional release gate requirements: {required_text}",
            "success_criteria": ["required evidence classified", "defer or fix decision written", "GO not assumed"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "release_gate_conditional_go",
        },
        {
            "id": "step-002",
            "owner": "pm-agent",
            "task": "Convert conditional release requirements into a bounded cleanup directive",
            "success_criteria": ["cleanup scope bounded", "acceptance criteria defined", "next evidence command listed"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "release_gate_conditional_go",
        },
    ]


def _release_gate_recovery_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    required = report_summary.get("release_gate_required_before_release") or []
    required_text = _blocker_summary(required)
    return [
        {
            "id": "step-001",
            "owner": "pm-agent",
            "task": f"Write a NO-GO recovery directive from release gate evidence: {required_text}",
            "success_criteria": ["release blocker named", "recovery scope bounded", "validation evidence defined"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "release_gate_no_go",
        },
        {
            "id": "step-002",
            "owner": "qa-agent",
            "task": "Define validation evidence required to move NO-GO back to release gate review",
            "success_criteria": ["missing tests/evidence listed", "quality threshold stated", "release gate rerun command included"],
            "required_permissions": ["test_run"],
            "handoff_status": "release_gate_no_go",
        },
    ]


def _validated_next_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    latest = report_summary.get("latest_result", {})
    latest_ref = latest.get("result_ref") if isinstance(latest, dict) else None
    return [
        {
            "id": "step-001",
            "owner": "release-manager-agent",
            "task": f"Review validated auto result for release gate readiness: {latest_ref or 'latest result'}",
            "success_criteria": ["validated evidence referenced", "release gate decision drafted"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "ready_for_release_or_next_plan",
        },
        {
            "id": "step-002",
            "owner": "pm-agent",
            "task": "Convert validated result into the next bounded product step",
            "success_criteria": ["next step scoped", "acceptance criteria defined"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "ready_for_release_or_next_plan",
        },
    ]


def _release_gate_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    latest = report_summary.get("latest_result", {})
    latest_ref = latest.get("result_ref") if isinstance(latest, dict) else None
    return [
        {
            "id": "step-001",
            "owner": "release-manager-agent",
            "task": f"Run release gate review for strong auto result: {latest_ref or 'latest result'}",
            "success_criteria": ["go/no-go verdict drafted", "release evidence referenced", "remaining risks listed"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "ready_for_release_or_next_plan",
            "quality_route": "release_gate",
        },
        {
            "id": "step-002",
            "owner": "qa-agent",
            "task": "Confirm the strong result has enough validation evidence for release gate",
            "success_criteria": ["tests referenced", "quality score referenced", "release-blocking gaps listed"],
            "required_permissions": ["test_run"],
            "handoff_status": "ready_for_release_or_next_plan",
            "quality_route": "release_gate",
        },
    ]


def _next_product_step_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    latest = report_summary.get("latest_result", {})
    latest_ref = latest.get("result_ref") if isinstance(latest, dict) else None
    return [
        {
            "id": "step-001",
            "owner": "pm-agent",
            "task": f"Convert usable auto result into the next bounded product step: {latest_ref or 'latest result'}",
            "success_criteria": ["next task scoped", "missing evidence converted to acceptance criteria"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "ready_for_release_or_next_plan",
            "quality_route": "next_product_step",
        },
        {
            "id": "step-002",
            "owner": "qa-agent",
            "task": "Define the validation evidence needed to raise the next result to strong quality",
            "success_criteria": ["test evidence defined", "quality gap listed", "release gate deferred explicitly"],
            "required_permissions": ["test_run"],
            "handoff_status": "ready_for_release_or_next_plan",
            "quality_route": "next_product_step",
        },
    ]


def _quality_review_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    latest = report_summary.get("latest_result", {})
    latest_ref = latest.get("result_ref") if isinstance(latest, dict) else None
    quality_average = report_summary.get("quality_average")
    return [
        {
            "id": "step-001",
            "owner": "qa-agent",
            "task": f"Review role-specific result quality before advancing: {latest_ref or 'latest result'}",
            "success_criteria": ["quality weakness classified", "required evidence listed", "pass threshold defined"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "needs_result_quality_review",
            "quality_average": quality_average,
        },
        {
            "id": "step-002",
            "owner": "pm-agent",
            "task": "Convert the quality review into a tighter result request",
            "success_criteria": ["missing role outputs named", "next result contract clarified"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "needs_result_quality_review",
        },
    ]


def _build_release_gate_package(
    root: Path,
    report: dict[str, Any],
    report_summary: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    latest = report_summary.get("latest_result", {})
    if not isinstance(latest, dict):
        latest = {}
    quality = latest.get("result_quality", {})
    if not isinstance(quality, dict):
        quality = {}
    score = int(quality.get("score") or 0)
    quality_status = str(quality.get("status") or "unknown")
    quality_route = str(report_summary.get("quality_route") or "")
    checklist = _release_gate_checklist(root, report, report_summary, plan)
    proof_summary = dict(report.get("proof_summary") or {})
    verdict, reason = _release_gate_verdict(checklist, quality_route, score)
    required = _release_gate_required_before_release(checklist, quality_route)
    deferred = _release_gate_deferred_after_release(verdict, quality_status)
    return {
        "schema_version": SCHEMA_VERSION,
        "release_gate_id": f"release-gate-{_stamp()}",
        "created_at": _now(),
        "verdict": verdict,
        "reason": reason,
        "source_result": latest.get("result_ref") or latest.get("task_ref"),
        "source_report": _relative(default_auto_report_path(root), root),
        "source_plan": _relative(default_auto_plan_path(root), root) if default_auto_plan_path(root).exists() else None,
        "handoff_status": report_summary.get("handoff_status"),
        "quality_route": quality_route,
        "proof_summary": proof_summary,
        "quality": {
            "score": score,
            "status": quality_status,
            "threshold": quality.get("threshold"),
            "weak_signals": quality.get("weak_signals", []),
        },
        "evidence_checklist": checklist,
        "required_before_release": required,
        "deferred_after_release": deferred,
        "safety": {
            "source_code_modified_by_release_gate": False,
            "provider_api_called_by_release_gate": False,
            "automatic_release": False,
        },
        "next_command": _release_gate_next_command(verdict),
    }


def _release_gate_checklist(
    root: Path,
    report: dict[str, Any],
    report_summary: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, bool]:
    latest = report_summary.get("latest_result", {})
    if not isinstance(latest, dict):
        latest = {}
    quality = latest.get("result_quality", {})
    if not isinstance(quality, dict):
        quality = {}
    step_results = report.get("step_results", {})
    if not isinstance(step_results, dict):
        step_results = {}
    latest_has_tests = _latest_result_has_tests(root, report)
    latest_has_evidence = _latest_result_has_evidence(root, report)
    proof_summary = report.get("proof_summary", {}) if isinstance(report.get("proof_summary"), dict) else {}
    return {
        "validated_result": int(report_summary.get("validated_results") or 0) > 0,
        "strong_quality": str(quality.get("status") or "") == "strong" and int(quality.get("score") or 0) >= 90,
        "company_ledger_compliance": _release_gate_company_ledger_compliance_ok(quality),
        "no_open_blockers": not bool(report_summary.get("open_blockers") or []),
        "tests_present": latest_has_tests,
        "evidence_present": latest_has_evidence,
        "release_gate_plan": str(plan.get("plan_kind") or "") == "release_gate",
        "release_manager_first": _plan_first_owner(plan) == "release-manager-agent",
        "source_code_not_modified": not bool(report.get("source_code_modified")),
        "low_quality_absent": int(step_results.get("low_quality") or 0) == 0,
        "proof_ready": bool(proof_summary.get("proof_ready")),
        "runtime_validation_evidence": bool((proof_summary.get("runtime_evidence") or {}).get("present")),
    }


def _latest_result_has_tests(root: Path, report: dict[str, Any]) -> bool:
    latest_record = _latest_step_result_record(root, report)
    return _tests_have_content(latest_record.get("tests", [])) if latest_record else False


def _latest_result_has_evidence(root: Path, report: dict[str, Any]) -> bool:
    latest_record = _latest_step_result_record(root, report)
    return _evidence_has_content(latest_record.get("evidence", {})) if latest_record else False


def _latest_step_result_record(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    step_results = report.get("step_results", {})
    latest = step_results.get("latest", {}) if isinstance(step_results, dict) else {}
    if not isinstance(latest, dict):
        return {}
    result_ref = latest.get("result_ref")
    if not result_ref:
        return {}
    result_path = (root / str(result_ref)).resolve()
    if not result_path.exists():
        return {}
    try:
        return _load_yaml(result_path)
    except Exception:
        return {}


def _release_gate_company_ledger_compliance_ok(quality: dict[str, Any]) -> bool:
    ledger_quality = quality.get("company_ledger_compliance", {}) if isinstance(quality.get("company_ledger_compliance"), dict) else {}
    if not ledger_quality:
        return True
    if ledger_quality.get("required") is not True:
        return True
    return ledger_quality.get("ok") is True and str(ledger_quality.get("status") or "") == "compliant"


def _plan_first_owner(plan: dict[str, Any]) -> str:
    steps = plan.get("steps", [])
    if not isinstance(steps, list) or not steps:
        return ""
    first = steps[0]
    if not isinstance(first, dict):
        return ""
    return str(first.get("owner") or "")


def _release_gate_verdict(checklist: dict[str, bool], quality_route: str, score: int) -> tuple[str, str]:
    hard_requirements = [
        "validated_result",
        "strong_quality",
        "company_ledger_compliance",
        "no_open_blockers",
        "tests_present",
        "evidence_present",
        "source_code_not_modified",
        "low_quality_absent",
        "proof_ready",
        "runtime_validation_evidence",
    ]
    if quality_route == "release_gate" and score >= 90 and all(checklist.get(item) for item in hard_requirements):
        if checklist.get("release_gate_plan") and checklist.get("release_manager_first"):
            return "GO", "Strong validated result has release gate evidence."
        return "CONDITIONAL GO", "Strong result exists, but release gate plan evidence is incomplete."
    if checklist.get("validated_result") and score >= _result_quality_threshold():
        return "CONDITIONAL GO", "Validated result is usable, but release gate evidence is incomplete."
    return "NO-GO", "Release gate lacks validated strong evidence."


def _release_gate_required_before_release(checklist: dict[str, bool], quality_route: str) -> list[str]:
    required: list[str] = []
    labels = {
        "validated_result": "validated auto result",
        "strong_quality": "strong result quality score",
        "company_ledger_compliance": "company ledger compliance proof",
        "no_open_blockers": "no open blockers",
        "tests_present": "test evidence",
        "evidence_present": "evidence notes or artifacts",
        "release_gate_plan": "release gate plan",
        "release_manager_first": "release manager review step",
        "source_code_not_modified": "source safety confirmation",
        "low_quality_absent": "no low-quality validated result",
        "proof_ready": "proof summary is ready",
        "runtime_validation_evidence": "runtime validation evidence",
    }
    for key, label in labels.items():
        if not checklist.get(key):
            required.append(label)
    if quality_route != "release_gate":
        required.append("quality route must be release_gate")
    return required


def _release_gate_deferred_after_release(verdict: str, quality_status: str) -> list[str]:
    if verdict == "GO":
        return ["next iteration planning", "post-release backlog grooming"]
    if verdict == "CONDITIONAL GO":
        return ["non-blocking evidence cleanup", f"quality status follow-up: {quality_status}"]
    return []


def _release_gate_next_command(verdict: str) -> str:
    if verdict == "GO":
        return _explicit_next_goal_command()
    if verdict == "CONDITIONAL GO":
        return "cambrian auto boardroom --json"
    return "cambrian auto plan --json"


def _result_intake_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    waiting = int(report_summary.get("waiting_for_result") or 0)
    return [
        {
            "id": "step-001",
            "owner": "pm-agent",
            "task": f"Collect Codex/Claude result file for {waiting} waiting auto task directive(s)",
            "success_criteria": ["result file path identified", "auto step ingest command prepared"],
            "required_permissions": ["filesystem_read"],
            "handoff_status": "waiting_for_external_result",
        }
    ]


def _validation_plan_steps(report_summary: dict[str, Any]) -> list[dict[str, Any]]:
    latest = report_summary.get("latest_result", {})
    latest_ref = latest.get("result_ref") if isinstance(latest, dict) else None
    return [
        {
            "id": "step-001",
            "owner": "qa-agent",
            "task": f"Create validation evidence for ingested auto result: {latest_ref or 'latest result'}",
            "success_criteria": ["test command selected", "validation status recorded"],
            "required_permissions": ["test_run"],
            "handoff_status": "needs_validation",
        }
    ]


def _blocker_summary(blockers: Any) -> str:
    if not isinstance(blockers, list) or not blockers:
        return "unknown blocker"
    first = blockers[0]
    if isinstance(first, dict):
        values = first.get("blockers", [])
        if isinstance(values, list) and values:
            return str(values[0])
    return str(first)


def _missing_permissions(step: dict[str, Any], permissions: dict[str, Any]) -> list[str]:
    required = step.get("required_permissions", [])
    if not isinstance(required, list):
        return []
    missing: list[str] = []
    for permission in required:
        value = permissions.get(str(permission))
        if value is not True:
            missing.append(str(permission))
    return missing


def _write_auto_task_directive(root: Path, plan_id: str, plan: dict[str, Any], step: dict[str, Any], authority_mode: str) -> dict[str, Any]:
    step_id = str(step.get("id") or "step")
    task_id = f"{plan_id}-{step_id}"
    tasks_dir = default_auto_tasks_dir(root)
    task_ref_path = tasks_dir / f"{task_id}.yaml"
    directive_ref_path = tasks_dir / f"{task_id}.md"
    owner = str(step.get("owner") or "auto-agent")
    role_profile = _auto_role_profile(owner)
    result_contract = _auto_result_contract(role_profile)
    task_payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "created_at": _now(),
        "directive_type": "role_specific_auto_task",
        "status": "waiting_for_result",
        "plan_id": plan_id,
        "step_id": step_id,
        "owner": owner,
        "role_profile": role_profile,
        "task": step.get("task"),
        "goal": plan.get("goal"),
        "source_boardroom": plan.get("source_boardroom"),
        "boardroom_decision_lineage": step.get("boardroom_decision_lineage", {}),
        "boardroom_role_decision": step.get("boardroom_role_decision", {}),
        "decision_evidence_refs": step.get("decision_evidence_refs", []),
        "authority_mode": authority_mode,
        "company_ledger_guidance": step.get("company_ledger_guidance", {}),
        "result_contract_guidance": step.get("result_contract_guidance", {}),
        "success_criteria": step.get("success_criteria", []),
        "required_permissions": step.get("required_permissions", []),
        "execution_engine": "Codex or Claude",
        "directive_ref": _relative(directive_ref_path.resolve(), root),
        "safety": {
            "source_code_modified_by_auto_run": False,
            "provider_api_called_by_auto_run": False,
            "requires_result_ingest": True,
        },
        "result_contract": result_contract,
        "expected_result": {
            "status": "success | partial | failed | blocked | done | needs_more_info",
            "summary": "작업 결과 요약",
            "changed_files": [],
            "tests": [],
            "blockers": [],
            "next_action": "결과를 검증하고 다음 auto step으로 넘길지 판단",
            "evidence": {"notes": [], "artifacts": []},
        },
    }
    if _auto_company_ledger_guidance_available(task_payload):
        task_payload["result_contract"] = _with_company_ledger_result_contract(result_contract)
        task_payload["expected_result"]["company_ledger_compliance"] = _company_ledger_compliance_example(
            dict(task_payload.get("company_ledger_guidance", {}))
        )
    task_payload["worker_performance_guidance"] = _worker_performance_guidance_for_task(root, task_payload)
    task_payload["job_bridge"] = _maybe_create_auto_task_job(root, task_payload)
    task_payload["worker_performance_guidance"] = _worker_performance_guidance_for_task(root, task_payload)
    task_payload["skill_knowledge_guidance"] = _skill_knowledge_guidance_for_task(root, task_payload)
    _save_yaml(task_ref_path, task_payload)
    _atomic_write_text(directive_ref_path, _render_codex_directive(task_payload))
    result = {
        "task_ref": _relative(task_ref_path.resolve(), root),
        "directive_ref": _relative(directive_ref_path.resolve(), root),
    }
    job_bridge = task_payload.get("job_bridge", {}) if isinstance(task_payload.get("job_bridge"), dict) else {}
    if job_bridge.get("status") == "linked":
        result["job_ref"] = str(job_bridge.get("job_ref") or "")
        result["packet_ref"] = str(job_bridge.get("packet_ref") or "")
        result["job_next_commands"] = list(job_bridge.get("next_commands", []))
    return result


def _maybe_create_auto_task_job(root: Path, task_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from engine.project_custom_harness import create_custom_harness_job, load_custom_harness

        if load_custom_harness(root) is None:
            return {"status": "not_linked", "reason": "custom harness is not installed"}
        job_payload, pack_job_payload = create_custom_harness_job(
            root,
            _auto_task_job_request(task_payload),
            entry_mode="auto_task",
        )
    except Exception as exc:
        return {
            "status": "not_linked",
            "reason": f"{type(exc).__name__}: {exc}",
        }
    job = dict(pack_job_payload.get("job", {}) if isinstance(pack_job_payload.get("job"), dict) else {})
    outcome = dict(job.get("outcome_snapshot", {}) if isinstance(job.get("outcome_snapshot"), dict) else {})
    bridge_contract = _attach_auto_worker_bridge_packet(root, task_payload, pack_job_payload, outcome)
    return {
        "status": "linked",
        "job_id": job.get("job_id"),
        "job_ref": pack_job_payload.get("job_ref"),
        "packet_ref": pack_job_payload.get("packet_ref"),
        "selected_agents": outcome.get("selected_agents", []),
        "selected_skills": outcome.get("selected_skills", []),
        "dispatch_reason": outcome.get("dispatch_reason"),
        "next_commands": [
            "Paste the linked bridge packet into Codex or Claude.",
            "Ask the AI to return the auto step result contract shown in this directive.",
            f"cambrian auto step ingest {task_payload.get('task_id')} --result step_result.yaml --json",
        ],
        "source_code_modified_by_job_bridge": False,
        "provider_api_called_by_job_bridge": False,
        "provider_adapter": bridge_contract.get("provider_adapter", {}),
        "result_contract_sha256": bridge_contract.get("result_contract_sha256"),
        "packet_result_contract_sha256": bridge_contract.get("packet_result_contract_sha256"),
        "contract_alignment": bridge_contract.get("contract_alignment", {}),
    }


def _attach_auto_worker_bridge_packet(
    root: Path,
    task_payload: dict[str, Any],
    pack_job_payload: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:
    packet_ref = str(pack_job_payload.get("packet_ref") or "").strip()
    provider_adapter = _auto_worker_provider_adapter()
    result_contract = dict(task_payload.get("result_contract", {}) if isinstance(task_payload.get("result_contract"), dict) else {})
    result_contract_hash = _stable_payload_sha256(result_contract)
    fallback = {
        "provider_adapter": provider_adapter,
        "result_contract_sha256": result_contract_hash,
        "packet_result_contract_sha256": None,
        "contract_alignment": {"contracts_match": False, "reason": "bridge packet missing"},
    }
    if not packet_ref:
        return fallback
    packet_path = Path(packet_ref)
    if not packet_path.is_absolute():
        packet_path = (root / packet_path).resolve()
    if not packet_path.exists():
        fallback["contract_alignment"] = {"contracts_match": False, "reason": f"bridge packet not found: {packet_ref}"}
        return fallback
    packet = _load_yaml(packet_path)
    execution_contract = dict(packet.get("execution_contract", {}) if isinstance(packet.get("execution_contract"), dict) else {})
    active_context = dict(packet.get("active_pack_context", {}) if isinstance(packet.get("active_pack_context"), dict) else {})
    worker_bridge = _auto_worker_bridge_context(
        root=root,
        task_payload=task_payload,
        outcome=outcome,
        execution_contract=execution_contract,
        active_context=active_context,
        provider_adapter=provider_adapter,
        result_contract_hash=result_contract_hash,
    )
    execution_contract["auto_step_result_contract"] = result_contract
    execution_contract["auto_worker_bridge"] = worker_bridge
    active_context["auto_worker_bridge"] = worker_bridge
    packet["execution_contract"] = execution_contract
    packet["active_pack_context"] = active_context
    packet["provider_adapter"] = provider_adapter
    packet["auto_worker_bridge"] = worker_bridge
    packet["auto_step_result_contract"] = result_contract
    packet["codex_claude_instruction"] = _append_auto_worker_bridge_instruction(
        str(packet.get("codex_claude_instruction") or ""), worker_bridge
    )
    _save_yaml(packet_path, packet)
    return {
        "provider_adapter": provider_adapter,
        "result_contract_sha256": result_contract_hash,
        "packet_result_contract_sha256": worker_bridge["contract_alignment"]["packet_result_contract_sha256"],
        "contract_alignment": worker_bridge["contract_alignment"],
    }


def _auto_worker_provider_adapter() -> dict[str, Any]:
    return {
        "mode": "provider_neutral",
        "provider_identity": "external_ai_worker",
        "supported_providers": ["codex", "claude", "gpt", "cursor"],
        "provider_lock_in": False,
        "adapter_contract": "Providers may differ in UI and model behavior, but must return the same auto_step_result_contract.",
    }


def _auto_worker_bridge_context(
    *,
    root: Path,
    task_payload: dict[str, Any],
    outcome: dict[str, Any],
    execution_contract: dict[str, Any],
    active_context: dict[str, Any],
    provider_adapter: dict[str, Any],
    result_contract_hash: str,
) -> dict[str, Any]:
    result_contract = dict(task_payload.get("result_contract", {}) if isinstance(task_payload.get("result_contract"), dict) else {})
    packet_contract_hash = _stable_payload_sha256(result_contract)
    mission_path = default_auto_mission_path(root)
    mission = _load_yaml(mission_path) if mission_path.exists() else {}
    evidence_status = str(execution_contract.get("evidence_status") or active_context.get("evidence_status") or "")
    manual_review_required = bool(execution_contract.get("manual_review_required") or active_context.get("manual_review_required"))
    return {
        "schema_version": SCHEMA_VERSION,
        "bridge_kind": "auto_external_ai_worker_bridge",
        "created_at": _now(),
        "provider_adapter": provider_adapter,
        "mission_context": {
            "mission_ref": _relative(mission_path, root) if mission_path.exists() else None,
            "final_goal": mission.get("final_goal") or task_payload.get("goal"),
            "current_phase": mission.get("current_phase"),
            "plan_id": task_payload.get("plan_id"),
            "step_id": task_payload.get("step_id"),
            "source_boardroom": task_payload.get("source_boardroom"),
            "decision_lineage": task_payload.get("boardroom_decision_lineage", {}),
        },
        "worker_context": {
            "owner": task_payload.get("owner"),
            "role_profile": task_payload.get("role_profile", {}),
            "selected_agents": list(outcome.get("selected_agents", [])),
            "selected_skills": list(outcome.get("selected_skills", [])),
            "dispatch_reason": outcome.get("dispatch_reason"),
            "worker_performance_guidance": task_payload.get("worker_performance_guidance", {}),
            "company_roles": execution_contract.get("company_roles") or active_context.get("company_roles") or {},
        },
        "evidence_context": {
            "evidence_status": evidence_status,
            "manual_review_required": manual_review_required,
            "evidence_paths": _auto_worker_evidence_paths(task_payload, execution_contract, active_context),
            "decision_evidence_refs": _auto_text_list(task_payload.get("decision_evidence_refs")),
            "codebase_evidence": execution_contract.get("codebase_evidence") or active_context.get("codebase_evidence") or {},
            "agent_evidence_context": execution_contract.get("agent_evidence_context") or active_context.get("agent_evidence_context") or {},
            "skill_evidence_context": execution_contract.get("skill_evidence_context") or active_context.get("skill_evidence_context") or {},
        },
        "risk_boundaries": {
            "authority_mode": task_payload.get("authority_mode"),
            "required_permissions": task_payload.get("required_permissions", []),
            "task_safety": task_payload.get("safety", {}),
            "harness_risk_boundaries": execution_contract.get("risk_boundaries") or active_context.get("risk_boundaries") or {},
            "must_not_do": execution_contract.get("must_not_do", []),
        },
        "validation": {
            "success_criteria": task_payload.get("success_criteria", []),
            "validation_commands": execution_contract.get("validation_commands") or active_context.get("validation_commands") or [],
            "result_intake_required": True,
            "ingest_command": f"cambrian auto step ingest {task_payload.get('task_id')} --result step_result.yaml --json",
        },
        "result_contract": result_contract,
        "contract_alignment": {
            "contracts_match": packet_contract_hash == result_contract_hash,
            "directive_result_contract_sha256": result_contract_hash,
            "packet_result_contract_sha256": packet_contract_hash,
            "required_result_contract": "auto_step_result_contract",
        },
    }


def _auto_worker_evidence_paths(
    task_payload: dict[str, Any], execution_contract: dict[str, Any], active_context: dict[str, Any]
) -> list[str]:
    refs: list[str] = []
    refs.extend(_auto_text_list(task_payload.get("source_boardroom")))
    refs.extend(_auto_text_list(task_payload.get("decision_evidence_refs")))
    ledger = task_payload.get("company_ledger_guidance", {}) if isinstance(task_payload.get("company_ledger_guidance"), dict) else {}
    for key in ["context_records_ref", "verification_ledger_ref", "promotion_review_ref"]:
        refs.extend(_auto_text_list(ledger.get(key)))
    for context in [execution_contract, active_context]:
        evidence = context.get("codebase_evidence", {}) if isinstance(context.get("codebase_evidence"), dict) else {}
        refs.extend(_auto_text_list(evidence.get("existing_important_paths")))
        refs.extend(_auto_text_list(evidence.get("missing_important_paths")))
        evidence_card = context.get("evidence_card", {}) if isinstance(context.get("evidence_card"), dict) else {}
        refs.extend(_auto_text_list(evidence_card.get("identity_evidence")))
    return _auto_dedupe_text(refs)


def _stable_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _append_auto_worker_bridge_instruction(instruction: str, worker_bridge: dict[str, Any]) -> str:
    addition = "\n".join(
        [
            "",
            "Auto external worker bridge:",
            "- Treat provider identity as provider-neutral; do not rely on Claude/Codex/GPT/Cursor-specific behavior.",
            "- Return only the auto_step_result_contract required by this packet and ingest it with the listed command.",
            f"- result_contract_sha256: {worker_bridge.get('contract_alignment', {}).get('packet_result_contract_sha256')}",
        ]
    )
    if "Auto external worker bridge:" in instruction:
        return instruction
    return f"{instruction.rstrip()}{addition}\n"


def _auto_task_job_request(task_payload: dict[str, Any]) -> str:
    owner = str(task_payload.get("owner") or "auto-agent")
    task = str(task_payload.get("task") or "")
    goal = str(task_payload.get("goal") or "")
    ledger = task_payload.get("company_ledger_guidance", {}) if isinstance(task_payload.get("company_ledger_guidance"), dict) else {}
    ledger_status = str(ledger.get("status") or "empty")
    context_refs = ", ".join(_auto_text_list(ledger.get("context_records_ref")) + _auto_text_list(ledger.get("verification_ledger_ref")))
    contract_guidance = task_payload.get("result_contract_guidance", {}) if isinstance(task_payload.get("result_contract_guidance"), dict) else {}
    contract_status = str(contract_guidance.get("status") or "empty")
    contract_errors = _short_join(_auto_text_list(contract_guidance.get("recent_errors")), limit=4)
    performance = task_payload.get("worker_performance_guidance", {}) if isinstance(task_payload.get("worker_performance_guidance"), dict) else {}
    performance_status = str(performance.get("status") or "empty")
    performance_hints = performance.get("hints", []) if isinstance(performance.get("hints"), list) else []
    performance_hint_text = "none"
    if performance_hints:
        first_hint = performance_hints[0] if isinstance(performance_hints[0], dict) else {}
        performance_hint_text = (
            f"{first_hint.get('agent_id')} + {first_hint.get('skill_id')} "
            f"score={first_hint.get('performance_score')} confidence={first_hint.get('confidence')}"
        )
    return "\n".join(
        [
            f"Auto task owner: {owner}",
            f"Project goal: {goal}",
            f"Task: {task}",
            "Use the installed Cambrian company context.",
            f"Company ledger status: {ledger_status}",
            f"Company ledger refs: {context_refs or 'none'}",
            f"Result contract guidance status: {contract_status}",
            f"Prior result contract errors to avoid: {contract_errors}",
            f"Worker performance guidance status: {performance_status}",
            f"Worker performance hint: {performance_hint_text}",
            "Use worker performance as cautionary dispatch context only; do not hard-lock agent or skill choices.",
            "Return a YAML or JSON auto step result with status, summary, changed_files, tests, blockers, next_action, evidence, and role_outputs.",
        ]
    )


def _auto_role_profile(owner: str) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {
        "ceo-agent": {
            "role_id": "ceo-agent",
            "mission": "제품 방향과 출시 판단을 좁혀 다음 의사결정 기준을 만든다.",
            "focus": ["제품 목표", "우선순위", "GO/NO-GO 판단"],
            "required_result_keys": ["decision", "priority", "not_doing"],
            "instructions": [
                "현재 목표가 Cambrian의 AI company runtime 방향과 맞는지 판단한다.",
                "이번 단계에서 하지 않을 일을 명확히 분리한다.",
                "다음 실행 단계를 하나의 결정으로 정리한다.",
            ],
            "outputs": ["release decision", "priority call", "not-doing list"],
            "forbidden": ["새 기능 범위 확장", "근거 없는 GO 판정"],
        },
        "cto-agent": {
            "role_id": "cto-agent",
            "mission": "기술 구조와 리스크를 검토하고 최소 변경 전략을 제안한다.",
            "focus": ["아키텍처", "리스크", "최소 변경"],
            "required_result_keys": ["architecture_notes", "risks", "minimal_change_plan"],
            "instructions": [
                "대규모 리팩토링 없이 목적을 달성하는 경로를 고른다.",
                "수정이 필요한 파일과 건드리면 안 되는 파일을 분리한다.",
                "검증 가능한 기술 리스크를 명시한다.",
            ],
            "outputs": ["architecture note", "risk list", "minimal change plan"],
            "forbidden": ["CLI 프레임워크 교체", "ProjectStatusReader.read() 리팩토링"],
        },
        "coo-agent": {
            "role_id": "coo-agent",
            "mission": "실행 순서와 병목을 정리해 자동 루프가 멈추지 않게 만든다.",
            "focus": ["순서", "병목", "운영 안정성"],
            "required_result_keys": ["execution_order", "blocker_handling", "evidence_map"],
            "instructions": [
                "현재 상태에서 다음 1~3개 실행 단계를 정리한다.",
                "막히는 조건과 복구 명령을 함께 적는다.",
                "증거 파일과 로그 위치를 확인한다.",
            ],
            "outputs": ["execution order", "blocker handling", "evidence map"],
            "forbidden": ["무한 루프 실행", "실패를 PASS로 처리"],
        },
        "pm-agent": {
            "role_id": "pm-agent",
            "mission": "제품 목표를 Codex가 수행 가능한 좁은 작업지시서로 바꾼다.",
            "focus": ["작업 범위", "완료 기준", "결과 계약"],
            "required_result_keys": ["scope", "acceptance_criteria", "test_plan"],
            "instructions": [
                "이번 작업의 목표와 비목표를 한 번에 구분되게 쓴다.",
                "수정 허용 파일, 금지 사항, 검증 명령을 명확히 적는다.",
                "결과 보고에 필요한 필드를 빠뜨리지 않는다.",
            ],
            "outputs": ["bounded directive", "acceptance criteria", "test plan"],
            "forbidden": ["추상적 목표만 남기기", "새 기능을 암묵적으로 추가하기"],
        },
        "engineering-agent": {
            "role_id": "engineering-agent",
            "mission": "지시된 범위 안에서 구현 후보와 검증 가능한 변경을 만든다.",
            "focus": ["구현 후보", "변경 파일", "회귀 테스트"],
            "required_result_keys": ["implementation_plan", "changed_files", "rollback_hint"],
            "instructions": [
                "수정 전 재현 조건과 기대 결과를 확인한다.",
                "허용된 파일 안에서 최소 변경을 적용한다.",
                "변경한 파일과 테스트 결과를 결과 계약에 기록한다.",
            ],
            "outputs": ["implementation patch", "changed files", "test result"],
            "forbidden": ["자동 patch apply 기능 추가", "사용자 승인 없는 destructive 작업"],
        },
        "qa-agent": {
            "role_id": "qa-agent",
            "mission": "완료 기준을 검증하고 실패 원인을 재현 가능한 형태로 분류한다.",
            "focus": ["검증 명령", "회귀 위험", "실패 분류"],
            "required_result_keys": ["test_matrix", "failure_classification", "release_risk"],
            "instructions": [
                "핵심 경로 테스트와 관련 회귀 테스트를 구분한다.",
                "실패 시 명령, 출력 요약, 재현 조건을 남긴다.",
                "불확실한 항목은 PASS로 처리하지 않는다.",
            ],
            "outputs": ["test matrix", "failure classification", "release risk"],
            "forbidden": ["테스트 기대값만 낮추기", "재현 없는 실패 단정"],
        },
        "release-manager-agent": {
            "role_id": "release-manager-agent",
            "mission": "릴리즈 가능 여부와 산출물 증거를 점검한다.",
            "focus": ["릴리즈 게이트", "산출물", "체크리스트"],
            "required_result_keys": ["verdict", "artifact_checklist", "post_release_backlog"],
            "instructions": [
                "P0/P1/P2를 분리하고 릴리즈 차단 여부를 판단한다.",
                "문서, 테스트, 산출물의 불일치를 확인한다.",
                "출시 전 필수 수정과 출시 후 backlog를 분리한다.",
            ],
            "outputs": ["go-no-go verdict", "artifact checklist", "post-release backlog"],
            "forbidden": ["P0를 문서로만 덮기", "NO-GO 상태에서 tag 생성"],
        },
    }
    return profiles.get(
        owner,
        {
            "role_id": owner or "auto-agent",
            "mission": "주어진 auto plan step을 안전하게 수행 가능한 작업으로 정리한다.",
            "focus": ["작업 범위", "증거", "다음 액션"],
            "required_result_keys": ["step_result", "evidence", "next_action"],
            "instructions": [
                "현재 step의 목표를 확인한다.",
                "변경 범위와 검증 방법을 명확히 기록한다.",
                "결과 계약 필드를 모두 채운다.",
            ],
            "outputs": ["step result", "evidence", "next action"],
            "forbidden": ["시크릿 출력", "사용자 확인 없는 destructive 작업"],
        },
    )


def _auto_result_contract(role_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    required_role_output_keys = []
    if isinstance(role_profile, dict):
        required_role_output_keys = list(role_profile.get("required_result_keys") or [])
    return {
        "required_fields": ["status", "summary", "changed_files", "tests", "blockers", "next_action", "evidence"],
        "allowed_statuses": ["success", "partial", "failed", "blocked", "done", "needs_more_info"],
        "role_outputs_required_for": ["success", "partial", "done"],
        "required_role_output_keys": required_role_output_keys,
        "evidence_required": True,
        "source_code_modified_must_be_reported": True,
    }


def _markdown_list(items: Any, fallback: str) -> str:
    if not isinstance(items, list) or not items:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in items)


def _render_codex_directive(task: dict[str, Any]) -> str:
    profile = dict(task.get("role_profile") or _auto_role_profile(str(task.get("owner") or "auto-agent")))
    contract = dict(task.get("result_contract") or _auto_result_contract(profile))
    criteria = _markdown_list(task.get("success_criteria"), "완료 기준 확인")
    permissions = _markdown_list(task.get("required_permissions"), "권한 요구 없음")
    focus = _markdown_list(profile.get("focus"), "역할별 초점 확인")
    instructions = _markdown_list(profile.get("instructions"), "현재 step을 안전하게 수행한다.")
    outputs = _markdown_list(profile.get("outputs"), "결과와 증거를 남긴다.")
    forbidden = _markdown_list(profile.get("forbidden"), "시크릿 출력 금지")
    required_fields = _markdown_list(contract.get("required_fields"), "status")
    required_role_keys = _markdown_list(contract.get("required_role_output_keys"), "역할별 산출물 없음")
    allowed_statuses = ", ".join(str(item) for item in contract.get("allowed_statuses", []) or ["success", "partial", "failed", "blocked"])
    job_bridge_section = _render_auto_task_job_bridge_section(task)
    company_ledger_section = _render_auto_task_company_ledger_section(task)
    result_contract_guidance_section = _render_auto_task_result_contract_guidance_section(task)
    skill_knowledge_section = _render_auto_task_skill_knowledge_section(task)
    worker_performance_section = _render_auto_task_worker_performance_section(task)
    return "\n".join(
        [
            f"# Cambrian Auto Task Directive - {task.get('task_id')}",
            "",
            "## 목표",
            str(task.get("task") or ""),
            "",
            "## 제품 목표",
            str(task.get("goal") or ""),
            "",
            "## 담당 역할",
            f"- 역할 ID: {profile.get('role_id')}",
            f"- 임무: {profile.get('mission')}",
            "",
            "## 역할별 초점",
            focus,
            "",
            "## 역할별 작업 지시",
            instructions,
            "",
            "## 기대 산출물",
            outputs,
            "",
            "## 완료 기준",
            criteria,
            "",
            "## 필요한 권한",
            permissions,
            "",
            "## 역할별 금지 사항",
            forbidden,
            "",
            job_bridge_section,
            "",
            company_ledger_section,
            "",
            result_contract_guidance_section,
            "",
            skill_knowledge_section,
            "",
            worker_performance_section,
            "",
            "## 안전 경계",
            "- 이 지시서는 auto run이 생성한 작업지시서다.",
            "- auto run 자체는 source code를 수정하지 않았다.",
            "- 시크릿을 출력하지 않는다.",
            "- git push를 하지 않는다.",
            "- destructive 작업은 별도 사용자 확인 없이는 수행하지 않는다.",
            "",
            "## 결과 계약",
            "결과 파일은 YAML 또는 JSON으로 작성하고 아래 필드를 모두 포함한다.",
            required_fields,
            "",
            "## 역할별 산출물 계약",
            "`success`, `partial`, `done` 결과는 `role_outputs`에 아래 키를 포함해야 한다.",
            required_role_keys,
            "",
            f"허용 status: {allowed_statuses}",
            "",
            "예시:",
            "```yaml",
            "status: success",
            "summary: \"무엇을 했는지 한 문장으로 요약\"",
            "changed_files: []",
            "tests: []",
            "blockers: []",
            "next_action: \"cambrian auto report --json\"",
            "evidence:",
            "  notes: []",
            "  artifacts: []",
            "role_outputs:",
            "  key: \"역할별 산출물\"",
            "```",
            "",
        ]
    )


def _render_auto_task_job_bridge_section(task: dict[str, Any]) -> str:
    job_bridge = task.get("job_bridge", {}) if isinstance(task.get("job_bridge"), dict) else {}
    if job_bridge.get("status") != "linked":
        return "\n".join(
            [
                "## Cambrian Job Bridge",
                "- status: not_linked",
                f"- reason: {job_bridge.get('reason') or 'custom harness is not installed'}",
                "- use this directive as the source of truth for the auto step result contract.",
            ]
        )
    lines = [
        "## Cambrian Job Bridge",
        "- status: linked",
        f"- job_ref: {job_bridge.get('job_ref')}",
        f"- packet_ref: {job_bridge.get('packet_ref')}",
        "- paste the linked bridge packet into Codex or Claude for richer project/company context.",
        "- even when using the bridge packet, return the auto step result contract below.",
    ]
    provider_adapter = job_bridge.get("provider_adapter", {}) if isinstance(job_bridge.get("provider_adapter"), dict) else {}
    if provider_adapter:
        lines.append(f"- provider_identity: {provider_adapter.get('provider_identity')}")
        lines.append(f"- provider_lock_in: {provider_adapter.get('provider_lock_in')}")
    contract_alignment = job_bridge.get("contract_alignment", {}) if isinstance(job_bridge.get("contract_alignment"), dict) else {}
    if contract_alignment:
        lines.append(f"- auto_step_result_contract_sha256: {contract_alignment.get('packet_result_contract_sha256')}")
        lines.append(f"- contracts_match: {contract_alignment.get('contracts_match')}")
    selected_agents = job_bridge.get("selected_agents", [])
    if isinstance(selected_agents, list) and selected_agents:
        lines.append("- selected_agents:")
        lines.extend([f"  - {item}" for item in selected_agents])
    selected_skills = job_bridge.get("selected_skills", [])
    if isinstance(selected_skills, list) and selected_skills:
        lines.append("- selected_skills:")
        lines.extend([f"  - {item}" for item in selected_skills])
    return "\n".join(lines)


def _render_auto_task_company_ledger_section(task: dict[str, Any]) -> str:
    guidance = task.get("company_ledger_guidance", {}) if isinstance(task.get("company_ledger_guidance"), dict) else {}
    if str(guidance.get("status") or "") in {"", "empty"}:
        return "\n".join(
            [
                "## Company Ledger",
                "- status: empty",
                "- no prior company ledger context is available for this auto step.",
            ]
        )
    lines = [
        "## Company Ledger",
        f"- status: {guidance.get('status')}",
        f"- context_records_ref: {guidance.get('context_records_ref')}",
        f"- verification_ledger_ref: {guidance.get('verification_ledger_ref')}",
        f"- promotion_review_ref: {guidance.get('promotion_review_ref')}",
        f"- candidate_context_count: {guidance.get('candidate_context_count')}",
        f"- promoted_memory_count: {guidance.get('promoted_memory_count')}",
        f"- next_step_focus: {guidance.get('next_step_focus')}",
        "- policy: candidate context is an unapproved signal; do not treat it as promoted memory.",
        "- result_contract: include company_ledger_compliance proving ledger review, duplicate guard, promotion policy, and validation command selection.",
    ]
    duplicate_guard = guidance.get("duplicate_guard", {}) if isinstance(guidance.get("duplicate_guard"), dict) else {}
    if duplicate_guard:
        lines.append("- duplicate_guard:")
        lines.append(f"  - mode: {duplicate_guard.get('mode')}")
        lines.append(f"  - requires_new_acceptance_delta: {duplicate_guard.get('requires_new_acceptance_delta')}")
    unchecked_items = guidance.get("unchecked_items", [])
    if isinstance(unchecked_items, list) and unchecked_items:
        lines.append("- unchecked_items:")
        lines.extend([f"  - {item}" for item in unchecked_items])
    validation_commands = guidance.get("validation_commands", [])
    if isinstance(validation_commands, list) and validation_commands:
        lines.append("- validation_commands:")
        lines.extend([f"  - {item}" for item in validation_commands])
    recent_context = guidance.get("recent_context_records", [])
    if isinstance(recent_context, list) and recent_context:
        lines.append("- recent_context_records:")
        for item in recent_context:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('id')}: {item.get('summary')}")
    recent_verification = guidance.get("recent_verification_entries", [])
    if isinstance(recent_verification, list) and recent_verification:
        lines.append("- recent_verification_entries:")
        for item in recent_verification:
            if isinstance(item, dict):
                lines.append(
                    f"  - {item.get('id')}: verdict={item.get('verdict')}, unchecked_risk_count={item.get('unchecked_risk_count')}"
                )
    must_do = guidance.get("must_do", [])
    if isinstance(must_do, list) and must_do:
        lines.append("- must_do:")
        lines.extend([f"  - {item}" for item in must_do])
    return "\n".join(lines)


def _render_auto_task_result_contract_guidance_section(task: dict[str, Any]) -> str:
    guidance = task.get("result_contract_guidance", {}) if isinstance(task.get("result_contract_guidance"), dict) else {}
    if str(guidance.get("status") or "") in {"", "empty"}:
        return "\n".join(
            [
                "## Result Contract History",
                "- status: empty",
                "- no prior auto result contract rejection is available for this auto step.",
            ]
        )
    lines = [
        "## Result Contract History",
        f"- status: {guidance.get('status')}",
        f"- total_rejections: {guidance.get('total_rejections')}",
        f"- open_count: {guidance.get('open_count')}",
        f"- resolved_count: {guidance.get('resolved_count')}",
        f"- next_step_focus: {guidance.get('next_step_focus')}",
        f"- latest_rejection_ref: {guidance.get('latest_rejection_ref')}",
        f"- latest_correction_directive_ref: {guidance.get('latest_correction_directive_ref')}",
        f"- latest_corrected_result_template_ref: {guidance.get('latest_corrected_result_template_ref')}",
        f"- latest_resolved_by_result_ref: {guidance.get('latest_resolved_by_result_ref')}",
        f"- guidance_kind: {guidance.get('guidance_kind')}",
        "- policy: rejected result files are not proof, validation evidence, or promoted memory.",
    ]
    recovery_loop = guidance.get("recovery_loop", {}) if isinstance(guidance.get("recovery_loop"), dict) else {}
    if recovery_loop:
        lines.append("- recovery_loop:")
        lines.append(f"  - status: {recovery_loop.get('status')}")
        lines.append(f"  - next_guidance: {recovery_loop.get('next_guidance')}")
        promotion_policy = recovery_loop.get("promotion_policy", {}) if isinstance(recovery_loop.get("promotion_policy"), dict) else {}
        lines.append(f"  - auto_promote: {promotion_policy.get('auto_promote')}")
        lines.append(f"  - candidate_warning_only: {promotion_policy.get('candidate_warning_only')}")
    recent_errors = guidance.get("recent_errors", [])
    if isinstance(recent_errors, list) and recent_errors:
        lines.append("- recent_errors:")
        lines.extend([f"  - {item}" for item in recent_errors])
    required_fields = guidance.get("required_fields", [])
    if isinstance(required_fields, list) and required_fields:
        lines.append("- required_fields:")
        lines.extend([f"  - {item}" for item in required_fields])
    must_do = guidance.get("must_do", [])
    if isinstance(must_do, list) and must_do:
        lines.append("- must_do:")
        lines.extend([f"  - {item}" for item in must_do])
    return "\n".join(lines)


def _render_auto_task_skill_knowledge_section(task: dict[str, Any]) -> str:
    guidance = task.get("skill_knowledge_guidance", {}) if isinstance(task.get("skill_knowledge_guidance"), dict) else {}
    if str(guidance.get("status") or "") in {"", "empty"}:
        return "\n".join(
            [
                "## Skill Knowledge Ledger",
                "- status: empty",
                f"- ledger_ref: {guidance.get('ledger_ref')}",
                "- no approved or candidate skill knowledge is available for the selected skills.",
            ]
        )
    lines = [
        "## Skill Knowledge Ledger",
        f"- status: {guidance.get('status')}",
        f"- ledger_ref: {guidance.get('ledger_ref')}",
        f"- candidate_count: {guidance.get('candidate_count')}",
        f"- approved_count: {guidance.get('approved_count')}",
        "- policy: candidate knowledge is warning guidance only until user review promotes it.",
    ]
    policy = guidance.get("promotion_policy", {}) if isinstance(guidance.get("promotion_policy"), dict) else {}
    if policy:
        lines.append("- promotion_policy:")
        lines.append(f"  - auto_promote: {policy.get('auto_promote')}")
        lines.append(f"  - requires_user_review: {policy.get('requires_user_review')}")
        lines.append(f"  - candidate_warning_only: {policy.get('candidate_warning_only')}")
    selected_skill_ids = guidance.get("selected_skill_ids", [])
    if isinstance(selected_skill_ids, list) and selected_skill_ids:
        lines.append("- selected_skill_ids:")
        lines.extend([f"  - {item}" for item in selected_skill_ids])
    warnings = guidance.get("candidate_warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append("- candidate_warnings:")
        for item in warnings:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('candidate_id')}: {item.get('warning') or item.get('summary')}")
                evidence_refs = item.get("evidence_refs", [])
                if isinstance(evidence_refs, list) and evidence_refs:
                    lines.append(f"    evidence_refs: {_short_join([str(ref) for ref in evidence_refs], limit=4)}")
                lines.append(f"    auto_promote: {item.get('auto_promote')}")
    approved = guidance.get("approved_knowledge", [])
    if isinstance(approved, list) and approved:
        lines.append("- approved_knowledge:")
        for item in approved:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('knowledge_id') or item.get('candidate_id')}: {item.get('summary')}")
    return "\n".join(lines)


def _render_auto_task_worker_performance_section(task: dict[str, Any]) -> str:
    guidance = task.get("worker_performance_guidance", {}) if isinstance(task.get("worker_performance_guidance"), dict) else {}
    if str(guidance.get("status") or "") in {"", "empty"}:
        return "\n".join(
            [
                "## Worker Performance Ledger",
                "- status: empty",
                f"- ledger_ref: {guidance.get('ledger_ref')}",
                "- no prior worker performance evidence is available for this dispatch context.",
            ]
        )
    lines = [
        "## Worker Performance Ledger",
        f"- status: {guidance.get('status')}",
        f"- ledger_ref: {guidance.get('ledger_ref')}",
        f"- minimum_samples_for_confidence: {guidance.get('minimum_samples_for_confidence')}",
        f"- low_data_caution: {guidance.get('low_data_caution')}",
        "- policy: use these hints as dispatch caution only; do not hard-lock agent or skill choices.",
    ]
    policy = guidance.get("dispatch_policy", {}) if isinstance(guidance.get("dispatch_policy"), dict) else {}
    if policy:
        lines.append("- dispatch_policy:")
        lines.append(f"  - hard_lock_choices: {policy.get('hard_lock_choices')}")
        lines.append(f"  - low_sample_size_caution: {policy.get('low_sample_size_caution')}")
    hints = guidance.get("hints", [])
    if isinstance(hints, list) and hints:
        lines.append("- hints:")
        for item in hints:
            if isinstance(item, dict):
                lines.append(
                    f"  - {item.get('agent_id')} + {item.get('skill_id')}: "
                    f"score={item.get('performance_score')}, samples={item.get('sample_count')}, "
                    f"confidence={item.get('confidence')}, caution={item.get('caution')}"
                )
    return "\n".join(lines)


def _resolve_auto_task_path(root: Path, task_ref: str) -> Path | None:
    raw = str(task_ref or "").strip()
    if not raw:
        return None
    candidates = [Path(raw), default_auto_tasks_dir(root) / raw, default_auto_tasks_dir(root) / f"{raw}.yaml"]
    for path in candidates:
        target = path if path.is_absolute() else (root / path)
        if target.exists():
            return target.resolve()
    return None


def _summarize_auto_task_statuses(root: Path) -> dict[str, Any]:
    tasks_dir = default_auto_tasks_dir(root)
    counts: dict[str, int] = {}
    task_refs: dict[str, list[str]] = {}
    if not tasks_dir.exists():
        return {"total": 0, "by_status": {}, "refs": {}}
    for task_path in sorted(tasks_dir.glob("*.yaml")):
        try:
            task = _load_yaml(task_path)
        except Exception:
            status = "unreadable"
        else:
            status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        task_refs.setdefault(status, []).append(_relative(task_path.resolve(), root))
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "refs": task_refs,
        "waiting_for_result": counts.get("waiting_for_result", 0),
        "validated": counts.get("validated", 0),
        "blocked": counts.get("blocked", 0),
    }


def _summarize_auto_step_results(execution_log: dict[str, Any]) -> dict[str, Any]:
    raw_results = execution_log.get("step_results", [])
    if not isinstance(raw_results, list):
        raw_results = []
    result_items = [item for item in raw_results if isinstance(item, dict)]
    latest_by_task: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(result_items):
        task_id = str(item.get("task_id") or "").strip()
        task_ref = str(item.get("task_ref") or "").strip()
        result_ref = str(item.get("result_ref") or "").strip()
        task_key = task_id or task_ref or result_ref or f"anonymous-result-{index}"
        latest_by_task[task_key] = item
    counts: dict[str, int] = {}
    open_blockers: list[dict[str, Any]] = []
    quality_scores: list[int] = []
    low_quality_results: list[dict[str, Any]] = []
    latest: dict[str, Any] | None = None
    for item in result_items:
        status = str(item.get("status") or "unknown")
        quality = item.get("result_quality", {})
        latest = {
            "task_id": item.get("task_id"),
            "task_ref": item.get("task_ref"),
            "result_ref": item.get("result_ref"),
            "status": status,
            "next_action": item.get("next_action"),
            "ingested_at": item.get("ingested_at"),
            "result_quality": quality if isinstance(quality, dict) else {},
            "company_ledger_compliance": item.get("company_ledger_compliance", {}),
        }
        required_input = _required_input_from_step_result(item)
        if required_input:
            latest["required_input"] = required_input
    for item in latest_by_task.values():
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        quality = item.get("result_quality", {})
        quality_score = None
        if isinstance(quality, dict) and isinstance(quality.get("score"), int):
            quality_score = int(quality["score"])
            quality_scores.append(quality_score)
        required_input = _required_input_from_step_result(item)
        blockers = item.get("blockers", [])
        if isinstance(blockers, list) and blockers:
            blocker_record = {
                "task_id": item.get("task_id"),
                "task_ref": item.get("task_ref"),
                "blockers": blockers,
            }
            if required_input:
                blocker_record["required_input"] = required_input
            open_blockers.append(blocker_record)
        if status == "validated" and quality_score is not None and quality_score < _result_quality_threshold():
            low_quality_results.append(
                {
                    "task_id": item.get("task_id"),
                    "task_ref": item.get("task_ref"),
                    "result_ref": item.get("result_ref"),
                    "score": quality_score,
                    "status": (quality or {}).get("status") if isinstance(quality, dict) else "unknown",
                    "weak_signals": (quality or {}).get("weak_signals", []) if isinstance(quality, dict) else [],
                }
            )
    quality_average = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "latest": latest or {},
        "open_blockers": open_blockers,
        "quality_average": quality_average,
        "quality_threshold": _result_quality_threshold(),
        "low_quality": len(low_quality_results),
        "low_quality_results": low_quality_results,
        "validated": counts.get("validated", 0),
        "done": counts.get("done", 0),
        "result_ingested": counts.get("result_ingested", 0),
        "blocked": counts.get("blocked", 0),
    }


def _summarize_auto_result_rejections(execution_log: dict[str, Any], task_statuses: dict[str, Any]) -> dict[str, Any]:
    raw_rejections = execution_log.get("step_rejections", [])
    if not isinstance(raw_rejections, list):
        raw_rejections = []
    raw_resolutions = execution_log.get("step_rejection_resolutions", [])
    if not isinstance(raw_resolutions, list):
        raw_resolutions = []
    rejection_items = [item for item in raw_rejections if isinstance(item, dict)]
    resolution_items = [item for item in raw_resolutions if isinstance(item, dict)]
    resolved_ids = {
        str(item.get("rejection_id") or "")
        for item in resolution_items
        if str(item.get("rejection_id") or "").strip()
    }
    waiting_refs = set(
        str(item)
        for item in (
            task_statuses.get("refs", {}).get("waiting_for_result", [])
            if isinstance(task_statuses.get("refs"), dict)
            else []
        )
    )
    by_error: dict[str, int] = {}
    latest: dict[str, Any] | None = None
    latest_by_task: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(rejection_items):
        error = str(item.get("error") or "unknown")
        by_error[error] = by_error.get(error, 0) + 1
        summary = _rejection_summary_item(item)
        latest = summary
        task_key = str(item.get("task_id") or item.get("task_ref") or f"anonymous-rejection-{index}")
        latest_by_task[task_key] = summary
    open_items = [
        item
        for item in latest_by_task.values()
        if str(item.get("task_ref") or "") in waiting_refs
        and str(item.get("status") or "") != "resolved"
        and str(item.get("rejection_id") or "") not in resolved_ids
    ]
    return {
        "total": len(rejection_items),
        "by_error": by_error,
        "latest": latest or {},
        "open": open_items,
        "open_count": len(open_items),
        "resolved_count": len(resolution_items),
        "latest_resolution": resolution_items[-1] if resolution_items else {},
    }


def _rejection_summary_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rejection_id": item.get("rejection_id"),
        "rejection_ref": item.get("rejection_ref"),
        "task_id": item.get("task_id"),
        "task_ref": item.get("task_ref"),
        "source_result_ref": item.get("source_result_ref"),
        "correction_directive_ref": item.get("correction_directive_ref"),
        "corrected_result_template_ref": item.get("corrected_result_template_ref"),
        "status": item.get("status"),
        "error": item.get("error"),
        "errors": item.get("errors", []),
        "required_fields": item.get("required_fields", []),
        "company_ledger_compliance_required": item.get("company_ledger_compliance_required"),
        "rejected_at": item.get("rejected_at"),
    }


def _summarize_release_gate(root: Path) -> dict[str, Any]:
    gate_path = _latest_file(default_auto_release_gate_dir(root), "release-gate-*.yaml")
    if gate_path is None:
        return {}
    try:
        gate = _load_yaml(gate_path)
    except Exception:
        return {
            "release_gate_ref": _relative(gate_path, root),
            "verdict": "unreadable",
            "required_before_release": ["release gate package is unreadable"],
        }
    return {
        "release_gate_id": gate.get("release_gate_id"),
        "release_gate_ref": _relative(gate_path, root),
        "verdict": gate.get("verdict"),
        "reason": gate.get("reason"),
        "quality_route": gate.get("quality_route"),
        "quality": gate.get("quality", {}),
        "proof_summary": gate.get("proof_summary", {}),
        "source_result": gate.get("source_result"),
        "required_before_release": gate.get("required_before_release", []),
        "deferred_after_release": gate.get("deferred_after_release", []),
        "created_at": gate.get("created_at"),
    }


def _auto_decision_handoff(
    status: dict[str, Any],
    task_statuses: dict[str, Any],
    step_results: dict[str, Any],
    release_gate: dict[str, Any] | None = None,
    result_rejections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    release_gate = release_gate or {}
    result_rejections = result_rejections or {}
    release_verdict = str(release_gate.get("verdict") or "").upper()
    release_gate_is_current = _release_gate_is_current_for_latest_result(release_gate, step_results)
    if int(result_rejections.get("open_count", 0) or 0) > 0:
        latest_rejection = result_rejections.get("latest", {})
        if not isinstance(latest_rejection, dict):
            latest_rejection = {}
        return {
            "status": "needs_result_contract_correction",
            "reason": "A Codex/Claude result was rejected because it did not satisfy the auto result contract.",
            "result_rejections": result_rejections,
            "latest_rejection": latest_rejection,
            "next_command": "cambrian auto boardroom --json",
        }
    if release_verdict == "GO" and release_gate_is_current:
        return {
            "status": "release_gate_go",
            "reason": release_gate.get("reason") or "Release gate returned GO.",
            "release_gate_verdict": "GO",
            "release_gate_ref": release_gate.get("release_gate_ref"),
            "next_command": _explicit_next_goal_command(),
        }
    if release_verdict == "CONDITIONAL GO" and release_gate_is_current:
        return {
            "status": "release_gate_conditional_go",
            "reason": release_gate.get("reason") or "Release gate returned CONDITIONAL GO.",
            "release_gate_verdict": "CONDITIONAL GO",
            "release_gate_ref": release_gate.get("release_gate_ref"),
            "next_command": "cambrian auto boardroom --json",
        }
    if release_verdict == "NO-GO" and release_gate_is_current:
        return {
            "status": "release_gate_no_go",
            "reason": release_gate.get("reason") or "Release gate returned NO-GO.",
            "release_gate_verdict": "NO-GO",
            "release_gate_ref": release_gate.get("release_gate_ref"),
            "next_command": "cambrian auto boardroom --json",
        }
    input_gate = _input_gate_from_step_results(step_results, _satisfied_auto_inputs(status))
    if input_gate:
        return {
            "status": "input_required",
            "reason": "Auto loop is blocked by missing human input.",
            "required_inputs": input_gate.get("required_inputs", []),
            "input_blockers": input_gate.get("input_blockers", []),
            "latest_result": input_gate.get("latest_result", {}),
            "next_command": None,
        }
    if int(step_results.get("blocked", 0) or 0) > 0 or step_results.get("open_blockers"):
        return {
            "status": "needs_boardroom_review",
            "reason": "At least one auto step result is blocked.",
            "next_command": "cambrian auto boardroom --json",
        }
    if int(task_statuses.get("waiting_for_result", 0) or 0) > 0:
        return {
            "status": "waiting_for_external_result",
            "reason": "One or more Codex/Claude task directives still need result intake.",
            "next_command": "cambrian auto step ingest <task-ref> --result step_result.yaml --json",
        }
    if int(step_results.get("done", 0) or 0) > 0:
        return {
            "status": "auto_done",
            "reason": "The latest auto step result explicitly completed the current loop.",
            "next_command": None,
        }
    if int(step_results.get("low_quality", 0) or 0) > 0:
        return {
            "status": "needs_result_quality_review",
            "reason": "At least one validated auto step result is below the role-output quality threshold.",
            "quality_route": "quality_review",
            "next_command": "cambrian auto boardroom --json",
        }
    if int(step_results.get("validated", 0) or 0) > 0:
        quality_route = _quality_route_from_step_results(step_results)
        return {
            "status": "ready_for_release_or_next_plan",
            "reason": _quality_route_reason(quality_route),
            "quality_route": quality_route,
            "next_command": "cambrian auto plan --json",
        }
    if int(step_results.get("result_ingested", 0) or 0) > 0:
        return {
            "status": "needs_validation",
            "reason": "A result was ingested, but validation evidence is incomplete.",
            "next_command": "cambrian auto report --json",
        }
    if status.get("status") == "not_initialized":
        return {
            "status": "not_initialized",
            "reason": "Auto mode has not been initialized.",
            "next_command": 'cambrian auto init --goal "Build this product" --json',
        }
    return {
        "status": "ready_for_auto_run",
        "reason": "No pending task results were found.",
        "next_command": "cambrian auto run --max-steps 5 --json",
    }


def _release_gate_is_current_for_latest_result(release_gate: dict[str, Any], step_results: dict[str, Any]) -> bool:
    if not release_gate:
        return False
    latest = step_results.get("latest", {})
    if not isinstance(latest, dict) or not latest:
        return True
    source_result = str(release_gate.get("source_result") or "").strip()
    latest_result = str(latest.get("result_ref") or "").strip()
    if source_result and latest_result and source_result != latest_result:
        return False
    gate_created_at = str(release_gate.get("created_at") or "").strip()
    latest_ingested_at = str(latest.get("ingested_at") or "").strip()
    if gate_created_at and latest_ingested_at:
        return gate_created_at >= latest_ingested_at
    return True


def _input_gate_from_step_results(
    step_results: dict[str, Any],
    resolved_inputs: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    latest = step_results.get("latest", {})
    if not isinstance(latest, dict):
        latest = {}
    required_inputs: list[dict[str, Any]] = []
    input_blockers: list[str] = []
    for blocker in step_results.get("open_blockers", []) or []:
        if not isinstance(blocker, dict):
            continue
        blocker_required = _normalize_required_input(blocker.get("required_input"))
        blocker_texts = [str(item) for item in blocker.get("blockers", []) or []]
        if blocker_required:
            required_inputs.extend(blocker_required)
            input_blockers.extend(blocker_texts)
        elif _looks_like_human_input_blocker(blocker_texts):
            required_inputs.extend(_infer_required_inputs_from_blockers(blocker_texts))
            input_blockers.extend(blocker_texts)
    latest_required = _normalize_required_input(latest.get("required_input"))
    if latest_required:
        required_inputs.extend(latest_required)
    deduped = _dedupe_required_inputs(required_inputs)
    resolved_fields = set()
    if isinstance(resolved_inputs, dict):
        resolved_fields = {str(field).strip() for field in resolved_inputs.keys()}
    deduped = [item for item in deduped if str(item.get("field") or "").strip() not in resolved_fields]
    if not deduped:
        return None
    return {
        "required_inputs": deduped,
        "input_blockers": list(dict.fromkeys(input_blockers)),
        "latest_result": latest,
    }


def _satisfied_auto_inputs(status: dict[str, Any]) -> dict[str, Any]:
    satisfied: dict[str, Any] = {}
    for bucket_name in ("resolved_inputs", "deferred_inputs"):
        bucket = status.get(bucket_name, {})
        if isinstance(bucket, dict):
            for field, value in bucket.items():
                key = str(field).strip()
                if key:
                    satisfied[key] = value
    return satisfied


def _required_input_from_step_result(item: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = _normalize_required_input(item.get("required_input"))
    if explicit:
        return explicit
    explicit = _normalize_required_input(item.get("required_inputs"))
    if explicit:
        return explicit
    evidence = item.get("evidence", {})
    if isinstance(evidence, dict):
        explicit = _normalize_required_input(evidence.get("required_input"))
        if explicit:
            return explicit
        explicit = _normalize_required_input(evidence.get("required_inputs"))
        if explicit:
            return explicit
    blockers = [str(blocker) for blocker in item.get("blockers", []) or []]
    if _looks_like_human_input_blocker(blockers):
        return _infer_required_inputs_from_blockers(blockers)
    return []


def _normalize_required_input(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if isinstance(item, dict):
            field = str(item.get("field") or item.get("id") or f"input_{index}").strip()
            description = str(item.get("description") or item.get("reason") or field).strip()
            normalized.append(
                {
                    "id": str(item.get("id") or field).strip(),
                    "field": field,
                    "description": description,
                    "example": item.get("example", item.get("accepted_example", "")),
                }
            )
        else:
            text = str(item or "").strip()
            if text:
                normalized.append(
                    {
                        "id": text.lower().replace(" ", "_")[:80],
                        "field": text,
                        "description": text,
                        "example": "",
                    }
                )
    return [item for item in normalized if item.get("field")]


def _dedupe_required_inputs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    has_specific_input = any(str(item.get("field") or item.get("id") or "").strip().lower() != "human_input" for item in items)
    for item in items:
        key = str(item.get("field") or item.get("id") or "").strip().lower()
        if has_specific_input and key == "human_input":
            continue
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _looks_like_human_input_blocker(blockers: list[str]) -> bool:
    joined = " ".join(blockers).lower()
    input_markers = [
        "required input",
        "human input",
        "user input",
        "missing input",
        "input required",
        "사용자",
        "입력",
        "제공",
        "필요",
        "확인 필요",
        "값이 필요",
    ]
    evidence_markers = ["staystatus", "raw response", "샘플", "응답", "상태 코드", "외부", "증거"]
    return any(marker in joined for marker in input_markers) and any(marker in joined for marker in evidence_markers)


def _infer_required_inputs_from_blockers(blockers: list[str]) -> list[dict[str, Any]]:
    joined = " ".join(blockers)
    if "stayStatus" in joined or "staystatus" in joined.lower():
        return [
            {
                "id": "yanolja_cancel_stay_status",
                "field": "stayStatus",
                "description": "취소된 야놀자 예약 raw 응답의 stayStatus 값",
                "example": {"stayStatus": "..."},
            }
        ]
    return [
        {
            "id": "human_input",
            "field": "human_input",
            "description": blockers[0] if blockers else "Missing human input",
            "example": "",
        }
    ]


def _ensure_input_request_files(root: Path, handoff: dict[str, Any]) -> list[str]:
    required_inputs = _normalize_required_input(handoff.get("required_inputs"))
    if not required_inputs:
        return []
    refs: list[str] = []
    for item in required_inputs:
        slug = _safe_slug(str(item.get("id") or item.get("field") or "human_input"))
        path = default_input_requests_dir(root) / f"{slug}.md"
        content = _render_input_request_markdown(item, handoff)
        _atomic_write_text(path, content)
        refs.append(_relative(path, root))
    return refs


def _render_input_request_markdown(item: dict[str, Any], handoff: dict[str, Any]) -> str:
    field = str(item.get("field") or "human_input")
    description = str(item.get("description") or field)
    example = item.get("example", "")
    if isinstance(example, dict):
        example_text = json.dumps(example, ensure_ascii=False, indent=2)
    else:
        example_text = str(example or "{\n  \"" + field + "\": \"...\"\n}")
    blockers = handoff.get("input_blockers", []) or []
    lines = [
        f"# 입력 필요: {field}",
        "",
        "## 필요한 입력",
        "",
        description,
        "",
        "## 권장 형식",
        "",
        "```json",
        example_text,
        "```",
        "",
        "## 차단 사유",
        "",
    ]
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- 이 값이 없으면 안전하게 다음 자동 단계를 진행할 수 없습니다.")
    lines.extend(
        [
            "",
            "## 안전 규칙",
            "",
            "- 토큰, 쿠키, API 키, Authorization 헤더는 제공하지 마세요.",
            "- 개인 식별 정보와 전체 원문은 제공하지 마세요.",
            "- 필요한 필드 값만 최소로 제공하세요.",
        ]
    )
    return "\n".join(lines) + "\n"


def _pause_for_input_required(root: Path, handoff: dict[str, Any]) -> None:
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return
    state = _load_yaml(state_path)
    state["paused"] = True
    state["pause_reason"] = "input_required"
    state["input_required"] = {
        "created_at": _now(),
        "required_inputs": handoff.get("required_inputs", []),
        "input_request_refs": handoff.get("input_request_refs", []),
        "reason": handoff.get("reason"),
    }
    state["updated_at"] = _now()
    _save_yaml(state_path, state)


def _safe_slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in value)
    slug = "_".join(part for part in slug.split("_") if part)
    return slug[:80] or "human_input"


def _quality_route_from_step_results(step_results: dict[str, Any]) -> str:
    latest = step_results.get("latest", {})
    if not isinstance(latest, dict):
        return "validated_next"
    quality = latest.get("result_quality", {})
    if not isinstance(quality, dict):
        return "validated_next"
    quality_status = str(quality.get("status") or "")
    if quality_status == "strong":
        return "release_gate"
    if quality_status == "usable":
        return "next_product_step"
    if quality_status in {"weak", "poor"}:
        return "quality_review"
    return "validated_next"


def _quality_route_reason(quality_route: str) -> str:
    if quality_route == "release_gate":
        return "Recent auto step result is strong enough for release gate review."
    if quality_route == "next_product_step":
        return "Recent auto step result is usable and should become the next bounded product step."
    if quality_route == "quality_review":
        return "Recent auto step result needs quality review before release or next planning."
    return "Recent auto step result has validation evidence."


def _load_result_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"result file top level must be a mapping: {path}")
    return payload


def _required_step_result_fields() -> list[str]:
    return ["status", "summary", "changed_files", "tests", "blockers", "next_action", "evidence"]


def _required_step_result_fields_for_task(task: dict[str, Any] | None) -> list[str]:
    fields = list(_required_step_result_fields())
    if _auto_company_ledger_guidance_available(task):
        fields.append("company_ledger_compliance")
    return _auto_dedupe_text(fields)


def _validate_step_result_contract(result: dict[str, Any], task: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    for field in _required_step_result_fields_for_task(task):
        if field not in result:
            errors.append(f"missing required field: {field}")
    status = str(result.get("status") or result.get("result") or "").strip().lower()
    allowed_statuses = {"success", "partial", "failed", "blocked", "done", "completed", "complete", "needs_more_info"}
    if "status" in result and status not in allowed_statuses:
        errors.append(f"status must be one of: {', '.join(sorted(allowed_statuses))}")
    if "summary" in result and not str(result.get("summary") or "").strip():
        errors.append("summary must be a non-empty string")
    for list_field in ["changed_files", "tests", "blockers"]:
        if list_field in result and not isinstance(result.get(list_field), list):
            errors.append(f"{list_field} must be a list")
    if "next_action" in result and not str(result.get("next_action") or "").strip():
        errors.append("next_action must be a non-empty string")
    if "evidence" in result and not isinstance(result.get("evidence"), dict):
        errors.append("evidence must be a mapping")
    tests = result.get("tests", [])
    if isinstance(tests, list):
        for index, item in enumerate(tests):
            if not isinstance(item, dict):
                errors.append(f"tests[{index}] must be a mapping")
                continue
            if not str(item.get("command") or "").strip():
                errors.append(f"tests[{index}].command is required")
            if not str(item.get("status") or item.get("result") or "").strip():
                errors.append(f"tests[{index}].status is required")
    errors.extend(_validate_role_result_contract(result, task))
    errors.extend(_validate_company_ledger_result_contract(result, task))
    return errors


def _role_result_required_keys(task: dict[str, Any] | None) -> list[str]:
    if not isinstance(task, dict):
        return []
    contract = task.get("result_contract", {})
    if isinstance(contract, dict):
        keys = contract.get("required_role_output_keys")
        if isinstance(keys, list):
            return [str(item) for item in keys if str(item).strip()]
    profile = task.get("role_profile", {})
    if isinstance(profile, dict):
        keys = profile.get("required_result_keys")
        if isinstance(keys, list):
            return [str(item) for item in keys if str(item).strip()]
    return []


def _role_outputs_required_for_status(task: dict[str, Any] | None, status: str) -> bool:
    if not isinstance(task, dict):
        return False
    contract = task.get("result_contract", {})
    if not isinstance(contract, dict):
        return False
    required_for = contract.get("role_outputs_required_for", [])
    if not isinstance(required_for, list):
        return False
    return status in {str(item).strip().lower() for item in required_for}


def _validate_role_result_contract(result: dict[str, Any], task: dict[str, Any] | None) -> list[str]:
    status = str(result.get("status") or result.get("result") or "").strip().lower()
    if not _role_outputs_required_for_status(task, status):
        return []
    required_keys = _role_result_required_keys(task)
    if not required_keys:
        return []
    owner = str((task or {}).get("owner") or "auto-agent")
    role_outputs = result.get("role_outputs")
    if not isinstance(role_outputs, dict):
        return [f"role_outputs must be a mapping for {owner}"]
    errors: list[str] = []
    for key in required_keys:
        value = role_outputs.get(key)
        if value is None:
            errors.append(f"role_outputs.{key} is required for {owner}")
        elif isinstance(value, str) and not value.strip():
            errors.append(f"role_outputs.{key} must be non-empty for {owner}")
        elif isinstance(value, (list, dict)) and not value:
            errors.append(f"role_outputs.{key} must be non-empty for {owner}")
    return errors


def _auto_company_ledger_guidance_available(task: dict[str, Any] | None) -> bool:
    if not isinstance(task, dict):
        return False
    guidance = task.get("company_ledger_guidance", {})
    if not isinstance(guidance, dict):
        return False
    return str(guidance.get("status") or "").strip() not in {"", "empty"}


def _with_company_ledger_result_contract(contract: dict[str, Any]) -> dict[str, Any]:
    updated = dict(contract)
    updated["required_fields"] = _auto_dedupe_text([*_auto_text_list(updated.get("required_fields")), "company_ledger_compliance"])
    updated["company_ledger_compliance_required"] = True
    updated["company_ledger_compliance_required_fields"] = [
        "ledger_reviewed",
        "duplicate_guard_checked",
        "promotion_policy_respected",
        "new_acceptance_delta",
        "unchecked_items_addressed",
        "validation_commands_selected",
    ]
    return updated


def _company_ledger_compliance_example(guidance: dict[str, Any]) -> dict[str, Any]:
    return {
        "ledger_reviewed": True,
        "duplicate_guard_checked": True,
        "promotion_policy_respected": True,
        "new_acceptance_delta": "What changed beyond the prior auto result.",
        "unchecked_items_addressed": _auto_text_list(guidance.get("unchecked_items")),
        "validation_commands_selected": _auto_text_list(guidance.get("validation_commands")),
    }


def _validate_company_ledger_result_contract(result: dict[str, Any], task: dict[str, Any] | None) -> list[str]:
    if not _auto_company_ledger_guidance_available(task):
        return []
    guidance = task.get("company_ledger_guidance", {}) if isinstance(task, dict) else {}
    if not isinstance(guidance, dict):
        guidance = {}
    compliance = result.get("company_ledger_compliance")
    if not isinstance(compliance, dict):
        return ["company_ledger_compliance must be a mapping when company ledger guidance is present"]
    errors: list[str] = []
    if compliance.get("ledger_reviewed") is not True:
        errors.append("company_ledger_compliance.ledger_reviewed must be true")
    if compliance.get("promotion_policy_respected") is not True:
        errors.append("company_ledger_compliance.promotion_policy_respected must be true")
    duplicate_guard = guidance.get("duplicate_guard", {}) if isinstance(guidance.get("duplicate_guard"), dict) else {}
    if duplicate_guard.get("requires_new_acceptance_delta"):
        if compliance.get("duplicate_guard_checked") is not True:
            errors.append("company_ledger_compliance.duplicate_guard_checked must be true")
        if not _has_content(compliance.get("new_acceptance_delta")):
            errors.append("company_ledger_compliance.new_acceptance_delta is required")
    if _auto_text_list(guidance.get("unchecked_items")) and not _has_content(compliance.get("unchecked_items_addressed")):
        errors.append("company_ledger_compliance.unchecked_items_addressed is required")
    if _auto_text_list(guidance.get("validation_commands")) and not _has_content(compliance.get("validation_commands_selected")):
        errors.append("company_ledger_compliance.validation_commands_selected is required")
    return errors


def _role_compliance_summary(task: dict[str, Any], ok: bool) -> dict[str, Any]:
    return {
        "ok": ok,
        "owner": task.get("owner"),
        "required_role_output_keys": _role_result_required_keys(task),
        "role_outputs_required_for": (task.get("result_contract") or {}).get("role_outputs_required_for", []),
    }


def _result_quality_threshold() -> int:
    return 80


def _score_step_result_quality(task: dict[str, Any], result_record: dict[str, Any]) -> dict[str, Any]:
    score = 0
    weak_signals: list[str] = []
    role_compliance = result_record.get("role_compliance", {})
    if isinstance(role_compliance, dict) and role_compliance.get("ok") is True:
        score += 35
    else:
        weak_signals.append("role compliance missing")

    required_keys = _role_result_required_keys(task)
    role_outputs = result_record.get("role_outputs", {})
    if required_keys:
        present = 0
        if isinstance(role_outputs, dict):
            for key in required_keys:
                value = role_outputs.get(key)
                if _has_content(value):
                    present += 1
                else:
                    weak_signals.append(f"role_outputs.{key} weak or missing")
        else:
            weak_signals.append("role_outputs is not a mapping")
        score += round(20 * present / max(len(required_keys), 1))
    else:
        score += 10

    evidence = result_record.get("evidence", {})
    if _evidence_has_content(evidence):
        score += 10
    else:
        weak_signals.append("evidence has no notes or artifacts")

    tests = result_record.get("tests", [])
    if _tests_have_content(tests):
        score += 15
    else:
        weak_signals.append("tests are missing or incomplete")

    if str(result_record.get("summary") or "").strip():
        score += 5
    else:
        weak_signals.append("summary is empty")

    if str(result_record.get("next_action") or "").strip():
        score += 5
    else:
        weak_signals.append("next_action is empty")

    blockers = result_record.get("blockers", [])
    if not isinstance(blockers, list) or not blockers:
        score += 5
    else:
        weak_signals.append("blockers are present")

    ledger_quality = _company_ledger_quality_signal(task, result_record)
    if ledger_quality["required"]:
        if ledger_quality["ok"]:
            score += 5
        else:
            score = min(score, _result_quality_threshold() - 1)
            weak_signals.extend(_auto_text_list(ledger_quality.get("errors")))

    score = min(100, max(0, int(score)))
    return {
        "score": score,
        "threshold": _result_quality_threshold(),
        "status": _quality_status(score),
        "weak_signals": weak_signals,
        "owner": task.get("owner"),
        "required_role_output_keys": required_keys,
        "company_ledger_compliance": ledger_quality,
    }


def _quality_status(score: int) -> str:
    if score >= 90:
        return "strong"
    if score >= _result_quality_threshold():
        return "usable"
    if score >= 50:
        return "weak"
    return "poor"


def _company_ledger_quality_signal(task: dict[str, Any], result_record: dict[str, Any]) -> dict[str, Any]:
    required = _auto_company_ledger_guidance_available(task)
    compliance = result_record.get("company_ledger_compliance", {})
    if not required:
        return {
            "required": False,
            "ok": True,
            "status": "not_required",
            "score_bonus": 0,
            "errors": [],
        }
    errors = _validate_company_ledger_result_contract({"company_ledger_compliance": compliance}, task)
    ok = not errors
    return {
        "required": True,
        "ok": ok,
        "status": "compliant" if ok else "incomplete",
        "score_bonus": 5 if ok else 0,
        "errors": errors,
    }


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _evidence_has_content(evidence: Any) -> bool:
    if not isinstance(evidence, dict):
        return False
    return _has_content(evidence.get("notes")) or _has_content(evidence.get("artifacts"))


def _tests_have_content(tests: Any) -> bool:
    if not isinstance(tests, list) or not tests:
        return False
    for item in tests:
        if not isinstance(item, dict):
            return False
        if not str(item.get("command") or "").strip():
            return False
        if not str(item.get("status") or item.get("result") or "").strip():
            return False
    return True


def _step_result_contract_example(task: dict[str, Any] | None = None) -> dict[str, Any]:
    example = {
        "status": "success",
        "summary": "작업 결과 요약",
        "changed_files": [],
        "tests": [{"command": "python -m pytest", "status": "passed"}],
        "blockers": [],
        "next_action": "cambrian auto report --json",
        "evidence": {
            "notes": ["검증 근거를 적는다."],
            "artifacts": [],
        },
        "role_outputs": {
            "scope": "역할별 산출물 예시",
            "acceptance_criteria": ["완료 기준"],
            "test_plan": ["검증 명령"],
        },
    }
    if _auto_company_ledger_guidance_available(task):
        guidance = task.get("company_ledger_guidance", {}) if isinstance(task, dict) else {}
        example["company_ledger_compliance"] = _company_ledger_compliance_example(
            dict(guidance) if isinstance(guidance, dict) else {}
        )
    return example


def _record_auto_company_ledgers(root: Path, task: dict[str, Any], result_record: dict[str, Any], result_ref: str) -> dict[str, Any]:
    verification = _record_auto_company_verification(root, task, result_record, result_ref)
    context = _record_auto_company_context(root, task, result_record, result_ref)
    return {
        "verification": verification,
        "context": context,
    }


def _record_auto_company_verification(root: Path, task: dict[str, Any], result_record: dict[str, Any], result_ref: str) -> dict[str, Any]:
    try:
        from engine.project_company_layer import record_verification_entry

        return record_verification_entry(
            root,
            source="auto:step_ingest",
            job_id=_auto_company_job_id(task),
            stage="auto_step_ingest",
            validation_evidence_ref=result_ref,
            verdict_ref=result_ref,
            verdict=_auto_company_verdict(result_record),
            trust_gate_status=_auto_company_trust_gate_status(result_record),
            validation_commands=_auto_validation_commands(result_record),
            checked_artifacts=_auto_checked_artifacts(result_record),
            unchecked_items=_auto_unchecked_items(result_record),
            company_roles=_auto_company_roles(task),
            context_intent_snapshot=_auto_context_intent_snapshot(root, task),
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "auto_company_verification_failed",
            "error": type(exc).__name__,
            "message": str(exc),
            "auto_promote": False,
            "requires_user_review": True,
        }


def _record_auto_company_context(root: Path, task: dict[str, Any], result_record: dict[str, Any], result_ref: str) -> dict[str, Any]:
    try:
        from engine.project_company_layer import record_context_candidate

        unchecked_items = _auto_unchecked_items(result_record)
        quality = result_record.get("result_quality", {}) if isinstance(result_record.get("result_quality"), dict) else {}
        summary = (
            f"auto task {task.get('task_id')} recorded as {result_record.get('status')}; "
            f"quality={quality.get('status') or 'unknown'}; unchecked_risk={len(unchecked_items)}"
        )
        lesson = (
            "Carry auto step result evidence, changed files, validation commands, and unchecked risks into the next company job context."
        )
        mistake = "Do not promote auto step output to long-term memory until the user reviews the promotion packet." if unchecked_items else None
        return record_context_candidate(
            root,
            source=_auto_company_job_id(task),
            summary=summary,
            kind="auto_step_result",
            decision="Record auto step result as a context candidate only; do not auto-promote.",
            lesson=f"{lesson} validation_commands={', '.join(_auto_validation_commands(result_record)) or 'none'}",
            mistake=mistake,
            evidence_ref=result_ref,
        )
    except Exception as exc:
        return {
            "ok": False,
            "status": "auto_company_context_failed",
            "error": type(exc).__name__,
            "message": str(exc),
            "auto_promote": False,
            "requires_user_review": True,
        }


def _auto_company_job_id(task: dict[str, Any]) -> str:
    job_bridge = task.get("job_bridge", {}) if isinstance(task.get("job_bridge"), dict) else {}
    return str(job_bridge.get("job_id") or task.get("task_id") or "auto-step")


def _auto_company_roles(task: dict[str, Any]) -> dict[str, Any]:
    job_bridge = task.get("job_bridge", {}) if isinstance(task.get("job_bridge"), dict) else {}
    return {
        "auto_owner": task.get("owner"),
        "selected_agents": _auto_text_list(job_bridge.get("selected_agents")),
        "selected_skills": _auto_text_list(job_bridge.get("selected_skills")),
        "dispatch_reason": job_bridge.get("dispatch_reason"),
    }


def _auto_context_intent_snapshot(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    request = str(task.get("task") or task.get("goal") or task.get("task_id") or "auto step result").strip()
    try:
        from engine.project_company_layer import build_context_intent_snapshot, load_company_loop_context

        return build_context_intent_snapshot(
            root,
            request,
            company_loop_context=load_company_loop_context(root),
        )
    except Exception as exc:
        return {
            "snapshot_kind": "context_intent_snapshot_unavailable",
            "error": type(exc).__name__,
            "message": str(exc),
        }


def _auto_company_verdict(result_record: dict[str, Any]) -> str:
    status = str(result_record.get("status") or "").strip()
    quality = result_record.get("result_quality", {}) if isinstance(result_record.get("result_quality"), dict) else {}
    quality_status = str(quality.get("status") or "").strip()
    if status in {"validated", "done"} and quality_status in {"strong", "usable"} and not _auto_unchecked_items(result_record):
        return "pass"
    return "hold"


def _auto_company_trust_gate_status(result_record: dict[str, Any]) -> str:
    if _auto_company_verdict(result_record) == "pass":
        return "pass"
    return "manual_required"


def _auto_validation_commands(result_record: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    tests = result_record.get("tests", [])
    if isinstance(tests, list):
        for item in tests:
            if isinstance(item, dict):
                commands.extend(_auto_text_list(item.get("command")))
            else:
                commands.extend(_auto_text_list(item))
    return _auto_dedupe_text(commands)


def _auto_checked_artifacts(result_record: dict[str, Any]) -> list[str]:
    evidence = result_record.get("evidence", {}) if isinstance(result_record.get("evidence"), dict) else {}
    return _auto_dedupe_text(
        [
            *_auto_text_list(result_record.get("changed_files")),
            *_auto_text_list(evidence.get("artifacts")),
        ]
    )


def _auto_unchecked_items(result_record: dict[str, Any]) -> list[str]:
    unchecked = [*_auto_text_list(result_record.get("blockers"))]
    quality = result_record.get("result_quality", {}) if isinstance(result_record.get("result_quality"), dict) else {}
    if str(quality.get("status") or "") in {"weak", "poor"}:
        unchecked.extend(_auto_text_list(quality.get("weak_signals")))
    if not _tests_have_content(result_record.get("tests", [])):
        unchecked.append("auto step result has no complete validation command evidence")
    return _auto_dedupe_text(unchecked)


def _auto_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_auto_text_list(item))
        return result
    if isinstance(value, dict):
        return [str(value)]
    text = str(value).strip()
    return [text] if text else []


def _auto_dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _company_record_changed_files(company_records: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ["verification", "context"]:
        record = company_records.get(key, {}) if isinstance(company_records.get(key), dict) else {}
        refs.extend(_auto_text_list(record.get("saved_path")))
        refs.extend(_auto_text_list(record.get("promotion_review_ref")))
    return _auto_dedupe_text(refs)


def _derive_step_status(result: dict[str, Any]) -> str:
    explicit = str(result.get("status") or result.get("result") or "").strip().lower()
    blockers = result.get("blockers", [])
    if explicit in {"blocked", "failed", "fail", "error"} or (isinstance(blockers, list) and blockers):
        return "blocked"
    if explicit in {"done", "completed", "complete"}:
        return "done"
    validation = result.get("validation", {})
    validation_status = ""
    if isinstance(validation, dict):
        validation_status = str(validation.get("status") or validation.get("result") or "").strip().lower()
    tests = result.get("tests", [])
    if validation_status in {"passed", "pass", "validated", "success"}:
        return "validated"
    if isinstance(tests, list) and tests:
        failed = [
            item for item in tests
            if isinstance(item, dict) and str(item.get("result") or item.get("status") or "").strip().lower() in {"failed", "fail", "error"}
        ]
        if failed:
            return "blocked"
        return "validated"
    return "result_ingested"


def _record_auto_step_rejection(
    root: Path,
    task_path: Path,
    task: dict[str, Any],
    source_path: Path,
    errors: list[str],
) -> tuple[dict[str, Any], Path, Path]:
    task_ref = _relative(task_path, root)
    source_result_ref = _relative(source_path, root) if _is_within(root, source_path) else str(source_path)
    task_id = str(task.get("task_id") or Path(task_ref).stem or "auto-task")
    rejection_id = f"rejection-{_safe_slug(task_id)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"
    guidance = task.get("company_ledger_guidance", {}) if isinstance(task.get("company_ledger_guidance"), dict) else {}
    rejection_path = default_auto_rejections_dir(root) / f"{rejection_id}.yaml"
    record = {
        "schema_version": SCHEMA_VERSION,
        "rejection_id": rejection_id,
        "created_at": _now(),
        "task_id": task.get("task_id"),
        "task_ref": task_ref,
        "source_result_ref": source_result_ref,
        "rejection_ref": _relative(rejection_path, root),
        "status": "rejected",
        "error": "invalid_result_contract",
        "errors": errors,
        "required_fields": _required_step_result_fields_for_task(task),
        "company_ledger_guidance_status": guidance.get("status") or "empty",
        "company_ledger_compliance_required": _auto_company_ledger_guidance_available(task),
        "safety": {
            "source_code_modified_by_ingest": False,
            "provider_api_called_by_ingest": False,
        },
        "next_command": f"cambrian auto step ingest {task_ref} --result corrected_step_result.yaml --json",
    }
    example_payload = _step_result_contract_example(task)
    template_path = default_auto_corrections_dir(root) / f"{rejection_id}-corrected-result-template.yaml"
    template_path = _save_yaml(template_path, example_payload)
    record["corrected_result_template_ref"] = _relative(template_path, root)
    directive_path = default_auto_corrections_dir(root) / f"{rejection_id}-correction.md"
    _atomic_write_text(directive_path, _render_result_contract_correction_directive(task, record, example_payload))
    record["correction_directive_ref"] = _relative(directive_path, root)
    skill_candidate = record_skill_knowledge_candidate(
        root,
        source=f"auto_step_rejection:{rejection_id}",
        skill_ids=_skill_ids_for_task(task),
        summary="Auto step result contract rejection created a skill knowledge candidate.",
        warning=f"Do not repeat invalid result contract: {_short_join(errors, limit=4)}.",
        evidence_refs=[
            record["rejection_ref"],
            record["source_result_ref"],
            record["correction_directive_ref"],
            record["corrected_result_template_ref"],
        ],
        knowledge_kind="result_contract_rejection_warning",
    )
    record["skill_knowledge_candidate"] = {
        "status": skill_candidate.get("status"),
        "candidate_id": skill_candidate.get("candidate_id"),
        "candidate_ref": skill_candidate.get("candidate_ref"),
        "ledger_ref": skill_candidate.get("ledger_ref"),
        "auto_promote": skill_candidate.get("auto_promote"),
    }
    rejection_path = _save_yaml(rejection_path, record)
    log_path = _append_step_rejection_log(root, record)
    return record, rejection_path, log_path


def _render_result_contract_correction_directive(
    task: dict[str, Any],
    rejection_record: dict[str, Any],
    example_payload: dict[str, Any],
) -> str:
    errors = "\n".join(f"- {item}" for item in _auto_text_list(rejection_record.get("errors"))) or "- unknown contract error"
    required_fields = "\n".join(f"- {item}" for item in _auto_text_list(rejection_record.get("required_fields"))) or "- none"
    example_yaml = yaml.safe_dump(example_payload, allow_unicode=True, sort_keys=False).strip()
    return "\n".join(
        [
            f"# Auto Result Contract Correction - {rejection_record.get('rejection_id')}",
            "",
            "## Rejected Task",
            f"- task_ref: {rejection_record.get('task_ref')}",
            f"- task_id: {rejection_record.get('task_id')}",
            f"- source_result_ref: {rejection_record.get('source_result_ref')}",
            "",
            "## Why It Was Rejected",
            errors,
            "",
            "## Required Fields",
            required_fields,
            "",
            "## Correction Rules",
            "- Return a corrected YAML or JSON result file, not source code.",
            "- Keep the original task waiting until the corrected result is ingested.",
            "- Do not treat the rejected result as proof, validation evidence, or promoted memory.",
            "- Include company_ledger_compliance when the template contains it.",
            "",
            "## Corrected Result Template",
            "```yaml",
            example_yaml,
            "```",
            "",
            "## Retry Command",
            f"`{rejection_record.get('next_command')}`",
            "",
        ]
    )


def _resolve_auto_step_rejections(
    root: Path,
    task: dict[str, Any],
    result_record: dict[str, Any],
    result_ref: str,
) -> dict[str, Any]:
    log_path = default_auto_execution_log_path(root)
    if not log_path.exists():
        return {"status": "none", "count": 0, "resolved": [], "changed_files": []}
    payload = _load_yaml(log_path)
    rejections = payload.get("step_rejections", [])
    if not isinstance(rejections, list):
        return {"status": "none", "count": 0, "resolved": [], "changed_files": []}
    resolutions = payload.get("step_rejection_resolutions", [])
    if not isinstance(resolutions, list):
        resolutions = []
    resolved_ids = {
        str(item.get("rejection_id") or "")
        for item in resolutions
        if isinstance(item, dict) and str(item.get("rejection_id") or "").strip()
    }
    task_id = str(task.get("task_id") or "").strip()
    task_ref = str(result_record.get("task_ref") or "").strip()
    changed_files: list[str] = []
    resolved_items: list[dict[str, Any]] = []
    for item in rejections:
        if not isinstance(item, dict):
            continue
        rejection_id = str(item.get("rejection_id") or "").strip()
        if rejection_id and rejection_id in resolved_ids:
            continue
        if str(item.get("status") or "") == "resolved":
            continue
        same_task = False
        if task_id and str(item.get("task_id") or "") == task_id:
            same_task = True
        if task_ref and str(item.get("task_ref") or "") == task_ref:
            same_task = True
        if not same_task:
            continue
        resolved_at = _now()
        resolution = {
            "resolved_at": resolved_at,
            "rejection_id": item.get("rejection_id"),
            "rejection_ref": item.get("rejection_ref"),
            "task_id": item.get("task_id"),
            "task_ref": item.get("task_ref"),
            "resolved_by_result_ref": result_ref,
            "resolution_status": result_record.get("status"),
            "resolution_summary": result_record.get("summary"),
            "source_code_modified_by_resolution": False,
            "provider_api_called_by_resolution": False,
        }
        skill_candidate = record_skill_knowledge_candidate(
            root,
            source=f"auto_step_rejection_resolved:{rejection_id or item.get('task_id') or 'unknown'}",
            skill_ids=_skill_ids_for_task(task),
            summary="Resolved result contract rejection created a skill knowledge candidate.",
            warning=f"Prior rejection was resolved; preserve the required result contract and do not reuse the rejected result as proof. Errors: {_short_join(_auto_text_list(item.get('errors')), limit=4)}.",
            evidence_refs=[
                str(item.get("rejection_ref") or ""),
                str(item.get("correction_directive_ref") or ""),
                str(result_ref or ""),
            ],
            knowledge_kind="result_contract_resolution_warning",
        )
        resolution["skill_knowledge_candidate"] = {
            "status": skill_candidate.get("status"),
            "candidate_id": skill_candidate.get("candidate_id"),
            "candidate_ref": skill_candidate.get("candidate_ref"),
            "ledger_ref": skill_candidate.get("ledger_ref"),
            "auto_promote": skill_candidate.get("auto_promote"),
        }
        if skill_candidate.get("ledger_ref"):
            changed_files.append(str(skill_candidate.get("ledger_ref")))
        item["status"] = "resolved"
        item["resolved_at"] = resolved_at
        item["resolved_by_result_ref"] = result_ref
        item["resolution_summary"] = result_record.get("summary")
        item["skill_knowledge_candidate"] = resolution["skill_knowledge_candidate"]
        rejection_ref = str(item.get("rejection_ref") or "").strip()
        if rejection_ref:
            rejection_path = Path(rejection_ref)
            if not rejection_path.is_absolute():
                rejection_path = (root / rejection_path).resolve()
            if rejection_path.exists():
                try:
                    rejection_payload = _load_yaml(rejection_path)
                except Exception:
                    rejection_payload = {}
                if isinstance(rejection_payload, dict):
                    rejection_payload["status"] = "resolved"
                    rejection_payload["resolved_at"] = resolved_at
                    rejection_payload["resolved_by_result_ref"] = result_ref
                    rejection_payload["resolution_status"] = result_record.get("status")
                    rejection_payload["resolution_summary"] = result_record.get("summary")
                    rejection_payload["resolution_skill_knowledge_candidate"] = resolution["skill_knowledge_candidate"]
                    _save_yaml(rejection_path, rejection_payload)
                    changed_files.append(_relative(rejection_path, root) if _is_within(root, rejection_path) else str(rejection_path))
        resolutions.append(resolution)
        resolved_items.append(resolution)
    if not resolved_items:
        return {"status": "none", "count": 0, "resolved": [], "changed_files": []}
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["step_rejections"] = rejections
    payload["step_rejection_resolutions"] = resolutions
    log_path = _save_yaml(log_path, payload)
    changed_files.append(_relative(log_path, root))
    return {
        "status": "resolved",
        "count": len(resolved_items),
        "resolved": resolved_items,
        "execution_log_ref": _relative(log_path, root),
        "changed_files": _auto_dedupe_text(changed_files),
    }


def _append_step_rejection_log(root: Path, rejection_record: dict[str, Any]) -> Path:
    path = default_auto_execution_log_path(root)
    payload = _load_yaml(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "runs": []}
    rejections = payload.get("step_rejections", [])
    if not isinstance(rejections, list):
        rejections = []
    rejections.append(
        {
            "rejected_at": _now(),
            "rejection_id": rejection_record.get("rejection_id"),
            "rejection_ref": rejection_record.get("rejection_ref"),
            "task_id": rejection_record.get("task_id"),
            "task_ref": rejection_record.get("task_ref"),
            "source_result_ref": rejection_record.get("source_result_ref"),
            "correction_directive_ref": rejection_record.get("correction_directive_ref"),
            "corrected_result_template_ref": rejection_record.get("corrected_result_template_ref"),
            "status": rejection_record.get("status"),
            "error": rejection_record.get("error"),
            "errors": rejection_record.get("errors", []),
            "required_fields": rejection_record.get("required_fields", []),
            "company_ledger_compliance_required": rejection_record.get("company_ledger_compliance_required"),
            "skill_knowledge_candidate": rejection_record.get("skill_knowledge_candidate", {}),
            "source_code_modified_by_ingest": False,
            "provider_api_called_by_ingest": False,
        }
    )
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["step_rejections"] = rejections
    return _save_yaml(path, payload)


def _append_step_result_log(root: Path, task: dict[str, Any], result_record: dict[str, Any]) -> Path:
    path = default_auto_execution_log_path(root)
    payload = _load_yaml(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "runs": []}
    step_results = payload.get("step_results", [])
    if not isinstance(step_results, list):
        step_results = []
    step_results.append(
        {
            "ingested_at": _now(),
            "task_id": task.get("task_id"),
            "task_ref": result_record.get("task_ref"),
            "result_ref": result_record.get("source_result_ref"),
            "status": result_record.get("status"),
            "summary": result_record.get("summary"),
            "changed_files": result_record.get("changed_files", []),
            "tests": result_record.get("tests", []),
            "blockers": result_record.get("blockers", []),
            "next_action": result_record.get("next_action"),
            "evidence": result_record.get("evidence", {}),
            "required_input": result_record.get("required_input", []),
            "role_compliance": result_record.get("role_compliance", {}),
            "role_outputs": result_record.get("role_outputs", {}),
            "company_ledger_compliance": result_record.get("company_ledger_compliance", {}),
            "result_quality": result_record.get("result_quality", {}),
            "company_verification_record": result_record.get("company_verification_record", {}),
            "company_context_record": result_record.get("company_context_record", {}),
            "skill_knowledge_candidate": result_record.get("skill_knowledge_candidate", {}),
            "worker_performance_record": result_record.get("worker_performance_record", {}),
            "retry_worker_performance_record": result_record.get("retry_worker_performance_record", {}),
            "resolved_rejections": result_record.get("resolved_rejections", {}),
            "source_code_modified_by_ingest": False,
            "provider_api_called_by_ingest": False,
        }
    )
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["step_results"] = step_results
    return _save_yaml(path, payload)


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    matches = sorted(directory.glob(pattern))
    return matches[-1] if matches else None


def _update_state(project_root: Path, state_name: str) -> Path:
    root = Path(project_root).resolve()
    state_path = default_auto_state_path(root)
    state = _load_yaml(state_path) if state_path.exists() else {"schema_version": SCHEMA_VERSION}
    state["previous_state"] = state.get("state")
    state["state"] = state_name
    state["updated_at"] = _now()
    state.setdefault("state_machine", STATE_ORDER)
    return _save_yaml(state_path, state)


def _append_execution_log(
    project_root: Path,
    authority_mode: str,
    executed: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
    next_state: str,
    task_refs: list[str] | None = None,
    directive_refs: list[str] | None = None,
    job_refs: list[str] | None = None,
    packet_refs: list[str] | None = None,
) -> Path:
    root = Path(project_root).resolve()
    path = default_auto_execution_log_path(root)
    payload = _load_yaml(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "runs": []}
    runs = payload.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    runs.append(
        {
            "executed_at": _now(),
            "mode": authority_mode,
            "command": "cambrian auto run",
            "working_directory": ".",
            "executed_steps": executed,
            "blocked_steps": blocked,
            "changed_files": [],
            "commands_executed": [],
            "test_results": [],
            "result": "recorded",
            "next_state": next_state,
            "task_refs": task_refs or [],
            "directive_refs": directive_refs or [],
            "job_refs": job_refs or [],
            "packet_refs": packet_refs or [],
            "waiting_for_result": len(executed),
            "source_code_modified": False,
            "provider_api_called": False,
            "rollback_hint": "No source files were modified by auto run V1.",
        }
    )
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["runs"] = runs
    return _save_yaml(path, payload)


def _set_paused(project_root: Path, paused: bool) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state_path = default_auto_state_path(root)
    if not state_path.exists():
        return _blocked("auto state is missing", 'cambrian auto init --goal "제품 목표" --json')
    state = _load_yaml(state_path)
    state["paused"] = paused
    state["updated_at"] = _now()
    _save_yaml(state_path, state)
    return {
        "ok": True,
        "status": "paused" if paused else "active",
        "state": state.get("state"),
        "state_ref": _relative(state_path, root),
        "next_command": "cambrian auto resume --json" if paused else _next_for_state(str(state.get("state") or "")),
    }


def _next_for_state(state_name: str) -> str | None:
    if state_name == "PRODUCT_CHARTER":
        return "cambrian auto boardroom --json"
    if state_name == "BOARDROOM_PLANNING":
        return "cambrian auto plan --json"
    if state_name in {"EXECUTION_PLAN", "IMPLEMENTATION"}:
        return "cambrian auto run --max-steps 5 --json"
    if state_name == "VALIDATION":
        return "cambrian auto report --json"
    if state_name == "DONE":
        return None
    return None


def _blocked(message: str, next_command: str | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "blocked",
        "errors": [message],
        "next_command": next_command,
    }
