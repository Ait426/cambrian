from __future__ import annotations

import tempfile
import json
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
    for file_name in ["plan.yaml", "report.yaml", "execution_log.yaml"]:
        source = auto_dir / file_name
        if source.exists():
            target = archive_dir / file_name
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            archived.append(_relative(target, root))
    for dir_name in ["boardroom", "decisions", "tasks", "results", "cycles", "external_results", "release_gate"]:
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


def default_auto_tasks_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "tasks"


def default_auto_results_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "results"


def default_auto_cycles_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "cycles"


def default_auto_release_gate_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "release_gate"


def default_auto_iterations_dir(project_root: Path) -> Path:
    return default_auto_dir(project_root) / "iterations"


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
    state_path = _save_yaml(default_auto_state_path(root), state)
    organization_path = _save_yaml(default_auto_organization_path(root), organization)
    append_authority_log(
        root,
        command=f"cambrian auto init --goal {goal_text}",
        mode=str(authority["mode"]),
        result="auto_initialized",
        changed_files=[_relative(state_path, root), _relative(organization_path, root)],
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
        changed_files=[_relative(state_path, root), _relative(iteration_path, root)],
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
        ],
        "fresh_start_cleared": [
            ".cambrian/auto/plan.yaml",
            ".cambrian/auto/report.yaml",
            ".cambrian/auto/execution_log.yaml",
            ".cambrian/auto/boardroom/",
            ".cambrian/auto/decisions/",
            ".cambrian/auto/tasks/",
            ".cambrian/auto/results/",
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
    meeting = {
        "schema_version": SCHEMA_VERSION,
        "meeting_id": meeting_id,
        "created_at": _now(),
        "agenda": _boardroom_agenda(str(state.get("goal") or ""), report_summary),
        "goal": state.get("goal"),
        "authority_mode": authority["mode"],
        "source_auto_report": report_ref,
        "auto_report_summary": report_summary,
        "decisions": _boardroom_decisions(str(state.get("goal") or ""), str(authority["mode"]), report_summary),
        "recommended_next_action": _boardroom_recommended_next_action(report_summary),
    }
    meeting_path = _save_yaml(default_auto_boardroom_dir(root) / f"{meeting_id}.yaml", meeting)
    decision_path = _save_yaml(default_auto_decisions_dir(root) / f"{meeting_id}.yaml", {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "source_meeting": meeting_id,
        "auto_report_summary": report_summary,
        "decisions": meeting["decisions"],
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
        "auto_report_summary": report_summary,
        "steps": steps,
        "next_command": next_command,
    }
    plan_path = _save_yaml(default_auto_plan_path(root), plan)
    _update_state(root, "EXECUTION_PLAN")
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
        "steps": plan["steps"],
        "next_command": plan["next_command"],
        "plan_ref": _relative(plan_path, root),
    }


def run_auto_cycle(project_root: Path, max_steps: int = 1) -> dict[str, Any]:
    root = Path(project_root).resolve()
    cycle_id = f"auto-cycle-{_stamp()}"
    report_payload = auto_report(root)
    if not report_payload.get("ok"):
        return _cycle_blocked(cycle_id, "report", report_payload)
    boardroom_payload = run_boardroom(root)
    if not boardroom_payload.get("ok"):
        return _cycle_blocked(cycle_id, "boardroom", boardroom_payload)
    plan_payload = create_auto_plan(root)
    if not plan_payload.get("ok"):
        return _cycle_blocked(cycle_id, "plan", plan_payload)
    run_payload = run_auto_plan(root, max_steps=max_steps)
    if not run_payload.get("ok"):
        return _cycle_blocked(cycle_id, "run", run_payload)

    authority = load_authority_profile(root)
    cycle_record = {
        "schema_version": SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "created_at": _now(),
        "max_steps": max(0, min(int(max_steps or 0), 50)),
        "report_ref": report_payload.get("report_ref"),
        "boardroom_ref": boardroom_payload.get("boardroom_ref"),
        "decision_ref": boardroom_payload.get("decision_ref"),
        "plan_ref": plan_payload.get("plan_ref"),
        "plan_kind": plan_payload.get("plan_kind"),
        "handoff_status": (plan_payload.get("auto_report_summary") or {}).get("handoff_status"),
        "run": {
            "executed_steps": run_payload.get("executed_steps"),
            "blocked_steps": run_payload.get("blocked_steps", []),
            "task_refs": run_payload.get("task_refs", []),
            "directive_refs": run_payload.get("directive_refs", []),
            "waiting_for_result": run_payload.get("waiting_for_result"),
            "next_state": run_payload.get("next_state"),
        },
        "source_code_modified": False,
        "provider_api_called": False,
    }
    cycle_path = _save_yaml(default_auto_cycles_dir(root) / f"{cycle_id}.yaml", cycle_record)
    append_authority_log(
        root,
        command=f"cambrian auto cycle --max-steps {cycle_record['max_steps']}",
        mode=str(authority["mode"]),
        result="auto_cycle_recorded",
        changed_files=[_relative(cycle_path, root)],
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
        "waiting_for_result": run_payload.get("waiting_for_result"),
        "source_code_modified": False,
        "provider_api_called": False,
        "next_command": _cycle_next_command(run_payload),
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
            entry["status"] = "waiting_for_result"
            entry["result"] = "codex_directive_created"
            entry["task_ref"] = task["task_ref"]
            entry["directive_ref"] = task["directive_ref"]
            executed.append(entry)
    next_state = "DONE" if str(plan.get("plan_kind") or "") == "done" else "IMPLEMENTATION" if executed else "EXECUTION_PLAN"
    if blocked and not executed:
        next_state = "EXECUTION_PLAN"
    log_path = _append_execution_log(root, authority["mode"], executed, blocked, next_state, task_refs, directive_refs)
    _update_state(root, next_state)
    append_authority_log(
        root,
        command=f"cambrian auto run --max-steps {limit}",
        mode=str(authority["mode"]),
        result="auto_run_recorded",
        changed_files=[_relative(log_path, root), _relative(state_path, root), *task_refs, *directive_refs],
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
        "waiting_for_result": len(executed),
        "evidence_files": [_relative(log_path, root)],
        "source_code_modified": False,
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
        return {
            "ok": False,
            "error": "invalid_result_contract",
            "errors": contract_errors,
            "task_ref": _relative(task_path, root),
            "result_path": _relative(source_path, root) if _is_within(root, source_path) else str(source_path),
            "required_fields": _required_step_result_fields(),
            "example": _step_result_contract_example(),
            "role_compliance": _role_compliance_summary(task, False),
            "source_code_modified": False,
            "next_command": f"cambrian auto step ingest {_relative(task_path, root)} --result step_result.yaml --json",
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
    _save_yaml(task_path, task)
    result_ref_path = _save_yaml(default_auto_results_dir(root) / f"{task.get('task_id')}.yaml", result_record)
    log_path = _append_step_result_log(root, task, result_record)
    next_state = "REVIEW" if status == "blocked" else "VALIDATION"
    _update_state(root, next_state)
    append_authority_log(
        root,
        command=f"cambrian auto step ingest {task_ref}",
        mode=str(load_authority_profile(root)["mode"]),
        result=f"auto_step_{status}",
        changed_files=[_relative(task_path, root), _relative(result_ref_path, root), _relative(log_path, root)],
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
        "source_code_modified": False,
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
    report = payload.get("report")
    if isinstance(report, dict):
        step_results = report.get("step_results", {})
        if isinstance(step_results, dict):
            lines.append("")
            lines.append("Step results:")
            lines.append(f"  Total: {step_results.get('total', 0)}")
            lines.append(f"  Blocked: {step_results.get('blocked', 0)}")
            lines.append(f"  Validated: {step_results.get('validated', 0)}")
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


def _build_auto_report(root: Path) -> dict[str, Any]:
    status = _base_auto_status(root)
    plan = _load_yaml(default_auto_plan_path(root)) if default_auto_plan_path(root).exists() else {}
    execution_log = _load_yaml(default_auto_execution_log_path(root)) if default_auto_execution_log_path(root).exists() else {}
    task_statuses = _summarize_auto_task_statuses(root)
    step_results = _summarize_auto_step_results(execution_log)
    release_gate = _summarize_release_gate(root)
    decision_handoff = _auto_decision_handoff(status, task_statuses, step_results, release_gate)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "status": status,
        "plan_id": plan.get("plan_id"),
        "execution_runs": len(execution_log.get("runs", [])) if isinstance(execution_log.get("runs"), list) else 0,
        "task_statuses": task_statuses,
        "step_results": step_results,
        "release_gate": release_gate,
        "decision_handoff": decision_handoff,
        "source_code_modified": False,
    }


def _boardroom_report_summary(report: dict[str, Any]) -> dict[str, Any]:
    handoff = dict(report.get("decision_handoff") or {})
    task_statuses = dict(report.get("task_statuses") or {})
    step_results = dict(report.get("step_results") or {})
    release_gate = dict(report.get("release_gate") or {})
    return {
        "handoff_status": handoff.get("status") or "unknown",
        "handoff_reason": handoff.get("reason"),
        "release_gate_verdict": release_gate.get("verdict"),
        "release_gate_ref": release_gate.get("release_gate_ref"),
        "release_gate_required_before_release": release_gate.get("required_before_release", []),
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
        "required_inputs": handoff.get("required_inputs", []),
        "input_request_refs": handoff.get("input_request_refs", []),
        "next_command": handoff.get("next_command"),
    }


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
    return all(boardroom_latest.get(key) == current_latest.get(key) for key in latest_keys)


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


def _cycle_blocked(cycle_id: str, failed_step: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "cycle_id": cycle_id,
        "failed_step": failed_step,
        "errors": payload.get("errors", [f"auto cycle failed at {failed_step}"]),
        "payload": payload,
        "source_code_modified": False,
        "provider_api_called": False,
        "next_command": payload.get("next_command"),
    }


def _cycle_next_command(run_payload: dict[str, Any]) -> str | None:
    if run_payload.get("next_state") == "DONE":
        return None
    task_refs = run_payload.get("task_refs", [])
    if isinstance(task_refs, list) and task_refs:
        first = str(task_refs[0])
        return f"cambrian auto step ingest {first} --result step_result.yaml --json"
    return "cambrian auto report --json"


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
    return {
        "validated_result": int(report_summary.get("validated_results") or 0) > 0,
        "strong_quality": str(quality.get("status") or "") == "strong" and int(quality.get("score") or 0) >= 90,
        "no_open_blockers": not bool(report_summary.get("open_blockers") or []),
        "tests_present": latest_has_tests,
        "evidence_present": latest_has_evidence,
        "release_gate_plan": str(plan.get("plan_kind") or "") == "release_gate",
        "release_manager_first": _plan_first_owner(plan) == "release-manager-agent",
        "source_code_not_modified": not bool(report.get("source_code_modified")),
        "low_quality_absent": int(step_results.get("low_quality") or 0) == 0,
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
        "no_open_blockers",
        "tests_present",
        "evidence_present",
        "source_code_not_modified",
        "low_quality_absent",
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
        "no_open_blockers": "no open blockers",
        "tests_present": "test evidence",
        "evidence_present": "evidence notes or artifacts",
        "release_gate_plan": "release gate plan",
        "release_manager_first": "release manager review step",
        "source_code_not_modified": "source safety confirmation",
        "low_quality_absent": "no low-quality validated result",
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


def _write_auto_task_directive(root: Path, plan_id: str, plan: dict[str, Any], step: dict[str, Any], authority_mode: str) -> dict[str, str]:
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
        "authority_mode": authority_mode,
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
    _save_yaml(task_ref_path, task_payload)
    _atomic_write_text(directive_ref_path, _render_codex_directive(task_payload))
    return {
        "task_ref": _relative(task_ref_path.resolve(), root),
        "directive_ref": _relative(directive_ref_path.resolve(), root),
    }


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
) -> dict[str, Any]:
    release_gate = release_gate or {}
    release_verdict = str(release_gate.get("verdict") or "").upper()
    release_gate_is_current = _release_gate_is_current_for_latest_result(release_gate, step_results)
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


def _validate_step_result_contract(result: dict[str, Any], task: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    for field in _required_step_result_fields():
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

    score = min(100, max(0, int(score)))
    return {
        "score": score,
        "threshold": _result_quality_threshold(),
        "status": _quality_status(score),
        "weak_signals": weak_signals,
        "owner": task.get("owner"),
        "required_role_output_keys": required_keys,
    }


def _quality_status(score: int) -> str:
    if score >= 90:
        return "strong"
    if score >= _result_quality_threshold():
        return "usable"
    if score >= 50:
        return "weak"
    return "poor"


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


def _step_result_contract_example() -> dict[str, Any]:
    return {
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
            "result_quality": result_record.get("result_quality", {}),
            "source_code_modified_by_ingest": False,
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
            "waiting_for_result": len(executed),
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
