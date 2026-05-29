from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_authority import append_authority_log, load_authority_profile
from engine.project_pack_install import SCHEMA_VERSION, _relative


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _atomic_write_text(path: Path, content: str) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        delete=False,
        prefix=f".{target.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    tmp_path.replace(target)


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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def default_mission_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "mission.yaml"


def default_mission_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "mission"


def default_mission_events_path(project_root: Path) -> Path:
    return default_mission_dir(project_root) / "events.yaml"


def default_mission_tasks_dir(project_root: Path) -> Path:
    return default_mission_dir(project_root) / "tasks"


def default_mission_operator_path(project_root: Path) -> Path:
    return default_mission_dir(project_root) / "operator.yaml"


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _product_boardroom_gate(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    try:
        from engine.project_company_layer import product_boardroom_status
    except Exception as exc:  # pragma: no cover - defensive import boundary
        return {
            "ready": False,
            "status": "unavailable",
            "blockers": [f"product boardroom status unavailable: {exc}"],
            "next_command": 'cambrian company boardroom install --goal "Keep product direction aligned" --json',
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        }

    status = product_boardroom_status(root)
    blockers: list[str] = []
    mission_path = default_mission_path(root)
    mission = _load_yaml(mission_path) if mission_path.exists() else {}
    decision_packet: dict[str, Any] = {}
    latest_decision_ref = str(status.get("latest_decision_ref") or "").strip()
    if latest_decision_ref:
        decision_path = root / latest_decision_ref
        decision_packet = _load_yaml(decision_path) if decision_path.exists() else {}
    mission_direction_updated_at = _parse_iso_datetime(
        mission.get("direction_updated_at") or mission.get("installed_at") or mission.get("updated_at")
    )
    decision_generated_at = _parse_iso_datetime(decision_packet.get("generated_at"))
    latest_request_generated_at = _parse_iso_datetime(status.get("latest_ai_request_generated_at"))
    if not status.get("installed"):
        blockers.append("CEO/CTO/COO product boardroom is not installed")
    if not status.get("ai_agent_contract_ready"):
        blockers.append("CEO/CTO/COO product boardroom is not backed by AI agent contracts")
    agent_prompt_refs = status.get("agent_prompt_refs") if isinstance(status.get("agent_prompt_refs"), list) else []
    if len(agent_prompt_refs) < 3:
        blockers.append("CEO/CTO/COO agent prompt refs are missing")
    for key, label in [
        ("meeting_protocol_ref", "meeting protocol"),
        ("agenda_ref", "product agenda"),
        ("decision_history_ref", "decision history"),
        ("latest_decision_ref", "latest decision packet"),
    ]:
        if not status.get(key):
            blockers.append(f"product boardroom {label} is missing")
    if status.get("latest_decision_status") != "ready_for_mission":
        blockers.append("latest product boardroom decision is not ready_for_mission")
    if not decision_packet.get("ai_agent_turns_verified"):
        blockers.append("latest product boardroom decision does not contain verified CEO/CTO/COO AI agent turns")
    if int(status.get("decision_count") or 0) < 1:
        blockers.append("product boardroom decision history is empty")
    if mission_direction_updated_at and decision_generated_at and decision_generated_at < mission_direction_updated_at:
        blockers.append("latest product boardroom decision is older than mission direction; convene the product boardroom again")
    elif latest_decision_ref and not decision_generated_at:
        blockers.append("latest product boardroom decision is missing generated_at")
    if latest_request_generated_at and decision_generated_at and latest_request_generated_at > decision_generated_at:
        blockers.append("latest CEO/CTO/COO AI boardroom request has not been ingested into a decision packet")
    ready = not blockers
    next_command = status.get("next_command")
    if not status.get("installed"):
        next_command = 'cambrian company boardroom install --goal "Keep product direction aligned" --json'
    elif not ready:
        next_command = 'cambrian company boardroom convene --topic "next product decision" --json'
    return {
        "ready": ready,
        "status": status.get("status"),
        "blockers": blockers,
        "next_command": next_command,
        "agents_ref": status.get("agents_ref"),
        "agent_prompt_refs": agent_prompt_refs,
        "meeting_protocol_ref": status.get("meeting_protocol_ref"),
        "agenda_ref": status.get("agenda_ref"),
        "decision_history_ref": status.get("decision_history_ref"),
        "latest_decision_ref": status.get("latest_decision_ref"),
        "latest_decision_status": status.get("latest_decision_status"),
        "latest_decision_ai_agent_turns_verified": bool(decision_packet.get("ai_agent_turns_verified")),
        "latest_ai_request_ref": status.get("latest_ai_request_ref"),
        "latest_ai_request_status": status.get("latest_ai_request_status"),
        "latest_decision_generated_at": decision_packet.get("generated_at"),
        "mission_updated_at": mission.get("updated_at"),
        "mission_direction_updated_at": mission.get("direction_updated_at") or mission.get("installed_at") or mission.get("updated_at"),
        "freshness_basis": "mission_direction_updated_at",
        "decision_count": status.get("decision_count"),
        "open_question_count": status.get("open_question_count"),
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }


def _hard_gates() -> list[dict[str, Any]]:
    return [
        {"id": "source_apply", "requires": "explicit human confirmation"},
        {"id": "git_push", "requires": "explicit human confirmation"},
        {"id": "public_release", "requires": "explicit human confirmation"},
        {"id": "deploy", "requires": "explicit human confirmation"},
        {"id": "secrets", "requires": "explicit human confirmation"},
        {"id": "payment_or_external_spend", "requires": "explicit human confirmation"},
        {"id": "database_migration", "requires": "explicit human confirmation"},
    ]


def _company_roles() -> list[dict[str, str]]:
    return [
        {"id": "ceo", "duty": "keep the product goal and customer outcome fixed"},
        {"id": "cto", "duty": "protect architecture, simplicity, and technical direction"},
        {"id": "coo", "duty": "turn strategy into the next bounded operating step"},
        {"id": "engineering", "duty": "produce patches only after a verified directive"},
        {"id": "qa", "duty": "select and verify validation evidence before promotion"},
        {"id": "release", "duty": "block release until install and user path are proven"},
        {"id": "risk", "duty": "enforce hard gates and stop unsafe expansion"},
    ]


def _load_project_contract(root: Path) -> dict[str, Any]:
    cambrian = root / ".cambrian"
    harness_path = cambrian / "harness.yaml"
    validation_path = cambrian / "validation.yaml"
    agents_path = cambrian / "agents.yaml"
    harness = _load_yaml(harness_path) if harness_path.exists() else {}
    validation = _load_yaml(validation_path) if validation_path.exists() else {}
    agents = _load_yaml(agents_path) if agents_path.exists() else {}

    validation_block = validation.get("validation") if isinstance(validation.get("validation"), dict) else {}
    domain_spec = harness.get("domain_spec") if isinstance(harness.get("domain_spec"), dict) else {}
    evaluator = harness.get("evaluator_contract") if isinstance(harness.get("evaluator_contract"), dict) else {}
    policy = harness.get("policy") if isinstance(harness.get("policy"), dict) else {}
    codebase_evidence = harness.get("codebase_evidence") if isinstance(harness.get("codebase_evidence"), dict) else {}

    fallback = _fallback_project_contract(root)
    validation_commands = _as_list(validation_block.get("test_commands"))
    validation_commands.extend(_as_list(domain_spec.get("validation_commands")))
    validation_commands.extend(_as_list(evaluator.get("validation_commands")))
    validation_commands = _as_list(validation_commands)
    if not validation_commands:
        validation_commands = _as_list(fallback.get("validation_commands"))

    agent_items = agents.get("agents") if isinstance(agents.get("agents"), list) else []
    agent_ids = [
        str(item.get("id")).strip()
        for item in agent_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]

    return {
        "harness_id": harness.get("id") or harness.get("harness_id"),
        "harness_ref": _relative(harness_path, root) if harness_path.exists() else None,
        "validation_ref": _relative(validation_path, root) if validation_path.exists() else None,
        "agents_ref": _relative(agents_path, root) if agents_path.exists() else None,
        "validation_commands": validation_commands,
        "change_policy": policy.get("change_mode") or harness.get("change_policy") or "proposal_only",
        "important_paths": _as_list(harness.get("important_paths"))
        or _as_list(codebase_evidence.get("existing_important_paths"))
        or _as_list(fallback.get("important_paths")),
        "agents": agent_ids[:12],
        "contract_source": "installed_harness" if harness_path.exists() else "project_fallback",
    }


def _fallback_project_contract(root: Path) -> dict[str, Any]:
    commands: list[str] = []
    important_paths: list[str] = []

    if (root / "pyproject.toml").exists():
        important_paths.append("pyproject.toml")
        if (root / "tests").exists():
            commands.append("python -m pytest -q")
    if (root / "package.json").exists():
        important_paths.append("package.json")
        commands.append("npm test")
    if (root / "README.md").exists():
        important_paths.append("README.md")

    for candidate in [
        "engine",
        "src",
        "app",
        "tests",
        "docs/product",
        "docs/release",
    ]:
        if (root / candidate).exists():
            important_paths.append(candidate)

    if not commands:
        python_files = list(root.glob("*.py"))
        if python_files:
            important_paths.extend(path.name for path in python_files[:5])
            commands.append("python -m py_compile " + " ".join(path.name for path in python_files[:5]))

    return {
        "validation_commands": _as_list(commands),
        "important_paths": _as_list(important_paths),
    }


def _load_events(root: Path) -> dict[str, Any]:
    path = default_mission_events_path(root)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "events": []}
    payload = _load_yaml(path)
    events = payload.get("events")
    if not isinstance(events, list):
        payload["events"] = []
    return payload


def _append_event(root: Path, event: dict[str, Any]) -> Path:
    payload = _load_events(root)
    event = {"created_at": _now(), **event}
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["events"].append(event)
    return _save_yaml(default_mission_events_path(root), payload)


def install_mission(project_root: Path, goal: str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    goal_text = str(goal or "").strip()
    if not goal_text:
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["goal is required"],
            "next_command": 'cambrian mission install --goal "Finish this product" --json',
        }

    authority = load_authority_profile(root)
    contract = _load_project_contract(root)
    mission = {
        "schema_version": SCHEMA_VERSION,
        "installed_at": _now(),
        "updated_at": _now(),
        "direction_updated_at": _now(),
        "status": "active",
        "goal": goal_text,
        "loop_kind": "bounded_24h_company",
        "authority_mode": authority.get("mode") or "proposal_only",
        "run_count": 0,
        "max_step_default": 1,
        "operating_loop": [
            "mission_state",
            "boardroom_decision",
            "bounded_worker_directive",
            "ai_reply_ingest",
            "evidence_envelope",
            "validation_gate",
            "promotion_or_retry",
        ],
        "company_roles": _company_roles(),
        "hard_gates": _hard_gates(),
        "project_contract": contract,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "next_action": "cambrian mission run --max-steps 1 --json",
    }
    mission_path = _save_yaml(default_mission_path(root), mission)
    events_path = _append_event(
        root,
        {
            "event": "mission_installed",
            "goal": goal_text,
            "mission_ref": _relative(mission_path, root),
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        },
    )
    append_authority_log(
        root,
        command=f"cambrian mission install --goal {goal_text}",
        mode=str(authority.get("mode") or "proposal_only"),
        result="mission_installed",
        changed_files=[_relative(mission_path, root), _relative(events_path, root)],
        rollback_hint="Remove .cambrian/mission.yaml and .cambrian/mission/ if this mission was not intended.",
    )
    return {
        "ok": True,
        "status": "installed",
        "goal": goal_text,
        "mission_ref": _relative(mission_path, root),
        "events_ref": _relative(events_path, root),
        "loop_kind": "bounded_24h_company",
        "hard_gates": mission["hard_gates"],
        "project_contract": contract,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "next_command": mission["next_action"],
    }


def mission_status(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    mission_path = default_mission_path(root)
    if not mission_path.exists():
        return {
            "ok": True,
            "status": "not_installed",
            "mission_ref": None,
            "next_command": 'cambrian mission install --goal "Finish this product" --json',
        }
    mission = _load_yaml(mission_path)
    events = _load_events(root)
    latest_event = events.get("events", [])[-1] if events.get("events") else None
    return {
        "ok": True,
        "status": mission.get("status") or "active",
        "goal": mission.get("goal"),
        "loop_kind": mission.get("loop_kind") or "bounded_24h_company",
        "run_count": int(mission.get("run_count") or 0),
        "mission_ref": _relative(mission_path, root),
        "last_task_ref": mission.get("last_task_ref"),
        "last_job_id": mission.get("last_job_id"),
        "last_job_ref": mission.get("last_job_ref"),
        "last_bridge_packet_ref": mission.get("last_bridge_packet_ref"),
        "last_outcome": mission.get("last_outcome"),
        "latest_event": latest_event,
        "hard_gates": mission.get("hard_gates") or _hard_gates(),
        "project_contract": mission.get("project_contract") or _load_project_contract(root),
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "next_command": mission.get("next_action") or "cambrian mission run --max-steps 1 --json",
    }


def mission_operator(project_root: Path, *, save: bool = False) -> dict[str, Any]:
    root = Path(project_root).resolve()
    status = mission_status(root)
    if status.get("status") == "not_installed":
        payload = {
            "ok": False,
            "status": "not_installed",
            "operator_mode": "supervised_24h_company",
            "mission_ref": status.get("mission_ref"),
            "next_command": status.get("next_command"),
            "errors": ["mission is not installed"],
        }
        if save:
            saved = _save_yaml(default_mission_operator_path(root), payload)
            payload["operator_ref"] = _relative(saved, root)
        return payload

    last_outcome = status.get("last_outcome") if isinstance(status.get("last_outcome"), dict) else {}
    next_command = str(status.get("next_command") or "").strip()
    run_count = int(status.get("run_count") or 0)
    outcome_ok = (
        last_outcome.get("outcome") == "success"
        and last_outcome.get("verdict") == "pass"
        and last_outcome.get("trust_gate_status") == "verified"
        and int(last_outcome.get("unchecked_count") or 0) == 0
    )
    ready_command = "cambrian mission run --max-steps 1 --start-job --json"
    waiting_for_ai_reply = "job ingest latest" in next_command
    ready_for_next_job = outcome_ok and next_command == ready_command
    minimum_cycles = 3
    boardroom_gate = _product_boardroom_gate(root)
    boardroom_ready = bool(boardroom_gate.get("ready"))
    safe_to_schedule = ready_for_next_job and run_count >= minimum_cycles and boardroom_ready

    if waiting_for_ai_reply:
        operator_status = "waiting_for_ai_reply"
        blockers = [
            "latest mission job is open; ingest an evidence envelope before opening another mission job",
        ]
    elif not outcome_ok and run_count > 0:
        operator_status = "attention_required"
        blockers = [
            "last linked mission outcome is missing, failed, unverified, or has unchecked risk",
        ]
    elif safe_to_schedule:
        operator_status = "operator_ready"
        blockers = []
    elif ready_for_next_job and run_count >= minimum_cycles and not boardroom_ready:
        operator_status = "boardroom_required"
        blockers = list(boardroom_gate.get("blockers") or ["product boardroom is not ready"])
    elif ready_for_next_job:
        operator_status = "manual_repeat_recommended"
        blockers = [f"need {minimum_cycles} verified cycles before scheduler install; current_run_count={run_count}"]
    else:
        operator_status = "ready_for_first_job"
        blockers = []

    if operator_status not in {"operator_ready", "waiting_for_ai_reply", "attention_required"} and boardroom_gate.get("blockers"):
        blockers = _as_list([*blockers, *list(boardroom_gate.get("blockers") or [])])
    operator_next_command = next_command or ready_command
    if operator_status == "boardroom_required":
        operator_next_command = str(boardroom_gate.get("next_command") or operator_next_command)

    payload = {
        "ok": True,
        "status": operator_status,
        "operator_mode": "supervised_24h_company",
        "mission_ref": status.get("mission_ref"),
        "goal": status.get("goal"),
        "loop_kind": status.get("loop_kind"),
        "run_count": run_count,
        "last_job_id": status.get("last_job_id"),
        "last_outcome": last_outcome or None,
        "next_command": operator_next_command,
        "scheduler_readiness": {
            "safe_to_schedule": safe_to_schedule,
            "minimum_verified_cycles": minimum_cycles,
            "current_run_count": run_count,
            "last_outcome_verified": outcome_ok,
            "product_boardroom_ready": boardroom_ready,
            "requires_next_command": ready_command,
            "actual_next_command": next_command,
            "recommended_tick_command": ready_command if safe_to_schedule else operator_next_command,
        },
        "tick_contract": {
            "max_mission_jobs_per_tick": 1,
            "requires_product_boardroom_ready": True,
            "must_stop_after_job_packet": True,
            "must_not_fabricate_ai_reply": True,
            "must_not_complete_without_validation": True,
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        },
        "product_boardroom_gate": boardroom_gate,
        "hard_gates": status.get("hard_gates") or _hard_gates(),
        "blockers": blockers,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }
    if save:
        saved = _save_yaml(default_mission_operator_path(root), payload)
        payload["operator_ref"] = _relative(saved, root)
        _append_event(
            root,
            {
                "event": "mission_operator_saved",
                "status": operator_status,
                "safe_to_schedule": safe_to_schedule,
                "operator_ref": payload["operator_ref"],
            },
        )
    return payload


def mission_tick(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    operator = mission_operator(root, save=True)
    if not operator.get("ok"):
        return {
            "ok": False,
            "status": "tick_blocked",
            "reason": "mission operator is not ready",
            "operator": operator,
            "next_command": operator.get("next_command"),
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        }

    readiness = operator.get("scheduler_readiness") if isinstance(operator.get("scheduler_readiness"), dict) else {}
    if not readiness.get("safe_to_schedule"):
        events_path = _append_event(
            root,
            {
                "event": "mission_tick_skipped",
                "operator_status": operator.get("status"),
                "blockers": operator.get("blockers") or [],
                "next_command": operator.get("next_command"),
                "product_boardroom_gate": operator.get("product_boardroom_gate"),
                "source_code_modified_by_cambrian": False,
                "provider_api_called_by_cambrian": False,
            },
        )
        return {
            "ok": True,
            "status": "tick_skipped",
            "operator_status": operator.get("status"),
            "operator_ref": operator.get("operator_ref"),
            "blockers": operator.get("blockers") or [],
            "next_command": operator.get("next_command"),
            "product_boardroom_gate": operator.get("product_boardroom_gate"),
            "events_ref": _relative(events_path, root),
            "opened_job": None,
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        }

    run_result = run_mission(root, max_steps=1, start_job=True)
    linked_jobs = run_result.get("linked_jobs") if isinstance(run_result.get("linked_jobs"), list) else []
    opened_job = linked_jobs[0] if linked_jobs else None
    events_path = _append_event(
        root,
        {
            "event": "mission_tick_started_job" if run_result.get("ok") else "mission_tick_blocked",
            "operator_status": operator.get("status"),
            "run_count": run_result.get("run_count"),
            "opened_job": opened_job,
            "blocked_job_starts": run_result.get("blocked_job_starts") or [],
            "next_command": run_result.get("next_command"),
            "product_boardroom_gate": operator.get("product_boardroom_gate"),
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        },
    )
    return {
        "ok": bool(run_result.get("ok")),
        "status": "tick_started_job" if run_result.get("ok") else "tick_blocked",
        "operator_status": operator.get("status"),
        "operator_ref": operator.get("operator_ref"),
        "run_count": run_result.get("run_count"),
        "task_refs": run_result.get("task_refs") or [],
        "opened_job": opened_job,
        "blocked_job_starts": run_result.get("blocked_job_starts") or [],
        "next_command": run_result.get("next_command"),
        "events_ref": _relative(events_path, root),
        "tick_contract": operator.get("tick_contract"),
        "product_boardroom_gate": operator.get("product_boardroom_gate"),
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }


def _latest_outcome(root: Path, mission: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    path = root / ".cambrian" / "evidence" / "outcomes.yaml"
    if not path.exists():
        return None, None
    payload = _load_yaml(path)
    outcomes = payload.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        return None, _relative(path, root)
    last_job_ref = str(mission.get("last_job_ref") or "").strip()
    last_job_id = str(mission.get("last_job_id") or "").strip()
    if not last_job_ref and not last_job_id:
        return None, _relative(path, root)
    for item in reversed(outcomes):
        if isinstance(item, dict):
            job_ref = str(item.get("job_ref") or "").strip()
            job_id = str(item.get("job_id") or "").strip()
            if (last_job_ref and job_ref == last_job_ref) or (last_job_id and job_id == last_job_id):
                return dict(item), _relative(path, root)
    return None, _relative(path, root)


def _outcome_sync_key(outcome: dict[str, Any]) -> str:
    return "|".join(
        [
            str(outcome.get("job_id") or ""),
            str(outcome.get("outcome") or ""),
            str(outcome.get("latest_verdict_ref") or ""),
            str(outcome.get("recorded_at") or ""),
        ]
    )


def sync_mission(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    mission_path = default_mission_path(root)
    if not mission_path.exists():
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["mission is not installed"],
            "next_command": 'cambrian mission install --goal "Finish this product" --json',
        }
    mission = _load_yaml(mission_path)
    outcome, outcomes_ref = _latest_outcome(root, mission)
    if outcome is None:
        cleared_stale_outcome = False
        if "last_outcome" in mission:
            mission.pop("last_outcome", None)
            mission["updated_at"] = _now()
            _save_yaml(mission_path, mission)
            cleared_stale_outcome = True
        payload = {
            "ok": True,
            "status": "no_outcome",
            "mission_ref": _relative(mission_path, root),
            "outcomes_ref": outcomes_ref,
            "cleared_stale_outcome": cleared_stale_outcome,
            "next_command": mission.get("next_action") or "cambrian mission run --max-steps 1 --json",
        }
        _append_event(
            root,
            {
                "event": "mission_sync_no_outcome",
                "outcomes_ref": outcomes_ref,
                "cleared_stale_outcome": cleared_stale_outcome,
            },
        )
        return payload

    sync_key = _outcome_sync_key(outcome)
    synced = _as_list(mission.get("synced_outcome_keys"))
    verdict_payload = outcome.get("evaluator_verdict") if isinstance(outcome.get("evaluator_verdict"), dict) else {}
    verdict = str(verdict_payload.get("verdict") or outcome.get("verdict") or "").strip() or "unknown"
    unchecked_items = _as_list(outcome.get("unchecked_items"))
    last_outcome = {
        "job_id": outcome.get("job_id"),
        "job_ref": outcome.get("job_ref"),
        "outcome": outcome.get("outcome"),
        "verdict": verdict,
        "trust_gate_status": outcome.get("trust_gate_status"),
        "validation_contract_status": outcome.get("validation_contract_status"),
        "latest_verdict_ref": outcome.get("latest_verdict_ref"),
        "outcomes_ref": outcomes_ref,
        "unchecked_count": len(unchecked_items),
        "validation_commands": _as_list(outcome.get("validation_commands")),
    }
    already_synced = sync_key in synced
    if not already_synced:
        synced.append(sync_key)
    mission["updated_at"] = _now()
    mission["last_outcome"] = last_outcome
    mission["synced_outcome_keys"] = synced[-50:]
    if verdict == "pass" and not unchecked_items:
        mission["next_action"] = "cambrian mission run --max-steps 1 --start-job --json"
        mission["status"] = "active"
    else:
        mission["next_action"] = "cambrian mission run --max-steps 1 --json"
        mission["status"] = "active"
    _save_yaml(mission_path, mission)
    events_path = _append_event(
        root,
        {
            "event": "mission_synced_outcome" if not already_synced else "mission_sync_up_to_date",
            "sync_key": sync_key,
            "last_outcome": last_outcome,
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        },
    )
    return {
        "ok": True,
        "status": "up_to_date" if already_synced else "synced",
        "mission_ref": _relative(mission_path, root),
        "events_ref": _relative(events_path, root),
        "last_outcome": last_outcome,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "next_command": mission["next_action"],
    }


def _build_worker_directive(mission: dict[str, Any], task_id: str, max_steps: int) -> dict[str, Any]:
    contract = mission.get("project_contract") if isinstance(mission.get("project_contract"), dict) else {}
    validation_commands = _as_list(contract.get("validation_commands"))
    return {
        "task_id": task_id,
        "role": "24h_company_worker",
        "objective": "Advance the mission by one verified release-moving step.",
        "mission_goal": mission.get("goal"),
        "max_steps": max_steps,
        "bounded_scope": {
            "change_policy": contract.get("change_policy") or "proposal_only",
            "source_apply_requires_confirm": True,
            "stop_when_evidence_is_missing": True,
            "do_not_expand_scope": True,
        },
        "required_evidence_envelope": [
            "codebase_evidence_path_citation",
            "risk_boundary_check",
            "validation_command_selection",
            "patch_application_state",
            "verdict_rationale",
            "context_intent_resolution",
            "project_discussion_role_check",
        ],
        "validation_commands": validation_commands,
        "important_paths": _as_list(contract.get("important_paths")),
        "hard_gates": mission.get("hard_gates") or _hard_gates(),
        "success_definition": [
            "one concrete blocker, patch proposal, or validation gap is resolved",
            "all claims cite local project evidence",
            "validation command choice is explicit",
            "unchecked items are listed instead of hidden",
        ],
    }


def _mission_job_request(mission: dict[str, Any], directive: dict[str, Any]) -> str:
    worker = directive.get("worker_directive") if isinstance(directive.get("worker_directive"), dict) else {}
    task_id = str(directive.get("task_id") or worker.get("task_id") or "mission-step")
    goal = str(mission.get("goal") or worker.get("mission_goal") or "").strip()
    validation_commands = ", ".join(_as_list(worker.get("validation_commands"))) or "select and justify validation command"
    return (
        f"[mission:{task_id}] Advance the 24h company goal by one verified step. "
        f"Goal: {goal}. "
        "Return an evidence envelope with codebase_evidence_path_citation, risk_boundary_check, "
        "validation_command_selection, patch_application_state, verdict_rationale, "
        "context_intent_resolution, and project_discussion_role_check. "
        f"Validation: {validation_commands}."
    )


def _start_mission_job(root: Path, mission: dict[str, Any], directive: dict[str, Any]) -> dict[str, Any]:
    request = _mission_job_request(mission, directive)
    try:
        from engine.project_custom_harness import create_custom_harness_job

        job_payload, pack_job_payload = create_custom_harness_job(root, request, entry_mode="mission")
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "status": "blocked",
            "reason": str(exc),
            "request": request,
            "next_command": "cambrian harness engineer design --json",
        }
    except ValueError as exc:
        return {
            "ok": False,
            "status": "blocked",
            "reason": str(exc),
            "request": request,
            "next_command": "cambrian mission run --max-steps 1 --json",
        }

    job = job_payload.get("job", {}) if isinstance(job_payload.get("job"), dict) else {}
    next_actions = list(job.get("next_actions", [])) if isinstance(job.get("next_actions"), list) else []
    return {
        "ok": True,
        "status": "created",
        "request": request,
        "job_id": job.get("job_id"),
        "job_ref": pack_job_payload.get("job_ref") if isinstance(pack_job_payload, dict) else None,
        "packet_ref": pack_job_payload.get("packet_ref") if isinstance(pack_job_payload, dict) else job.get("linked_bridge_packet_ref"),
        "harness_id": job.get("pack_id"),
        "next_commands": next_actions,
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
    }


def run_mission(project_root: Path, max_steps: int = 1, start_job: bool = False) -> dict[str, Any]:
    root = Path(project_root).resolve()
    mission_path = default_mission_path(root)
    if not mission_path.exists():
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["mission is not installed"],
            "next_command": 'cambrian mission install --goal "Finish this product" --json',
        }
    bounded_steps = max(1, min(int(max_steps or 1), 5))
    mission = _load_yaml(mission_path)
    if str(mission.get("status") or "active") != "active":
        return {
            "ok": False,
            "status": "blocked",
            "errors": [f"mission status is {mission.get('status')}"],
            "next_command": "cambrian mission resume --json",
        }

    run_count = int(mission.get("run_count") or 0) + 1
    task_refs: list[str] = []
    tasks: list[dict[str, Any]] = []
    linked_jobs: list[dict[str, Any]] = []
    blocked_job_starts: list[dict[str, Any]] = []
    for index in range(1, bounded_steps + 1):
        task_id = f"mission-step-{_stamp()}-{index:03d}"
        directive = {
            "schema_version": SCHEMA_VERSION,
            "created_at": _now(),
            "run_count": run_count,
            "task_id": task_id,
            "status": "waiting_for_ai_worker",
            "company_loop": {
                "stage": "bounded_worker_directive",
                "next_stage": "ai_reply_ingest",
            },
            "worker_directive": _build_worker_directive(mission, task_id, bounded_steps),
            "next_commands": [
                "execute this directive in Codex or Claude",
                "save the AI reply evidence envelope",
                "cambrian job ingest latest ai_reply_patch_candidate.yaml --json",
                "cambrian job validate latest --run --json",
                "cambrian job complete latest --outcome success --evidence .cambrian/evidence/outcomes.yaml --json",
            ],
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        }
        if start_job:
            linked_job = _start_mission_job(root, mission, directive)
            directive["linked_job"] = linked_job
            if linked_job.get("ok"):
                linked_jobs.append(linked_job)
            else:
                blocked_job_starts.append(linked_job)
        task_path = _save_yaml(default_mission_tasks_dir(root) / f"{task_id}.yaml", directive)
        task_refs.append(_relative(task_path, root))
        tasks.append(directive)

    mission["updated_at"] = _now()
    mission["last_run_at"] = _now()
    mission["run_count"] = run_count
    mission["last_task_ref"] = task_refs[-1]
    if linked_jobs:
        mission["last_job_ref"] = linked_jobs[-1].get("job_ref")
        mission["last_job_id"] = linked_jobs[-1].get("job_id")
        mission["last_bridge_packet_ref"] = linked_jobs[-1].get("packet_ref")
        mission["next_action"] = "cambrian job ingest latest ai_reply_patch_candidate.yaml --json"
    elif blocked_job_starts:
        mission["last_job_start_blocker"] = blocked_job_starts[-1]
        mission["next_action"] = blocked_job_starts[-1].get("next_command") or "cambrian mission run --max-steps 1 --json"
    else:
        mission["next_action"] = "cambrian mission run --max-steps 1 --json"
    mission["source_code_modified_by_cambrian"] = False
    mission["provider_api_called_by_cambrian"] = False
    _save_yaml(mission_path, mission)
    events_path = _append_event(
        root,
        {
            "event": "mission_run_created_directives",
            "run_count": run_count,
            "task_refs": task_refs,
            "start_job": bool(start_job),
            "linked_jobs": linked_jobs,
            "blocked_job_starts": blocked_job_starts,
            "source_code_modified_by_cambrian": False,
            "provider_api_called_by_cambrian": False,
        },
    )
    ok = not blocked_job_starts
    return {
        "ok": ok,
        "status": "waiting_for_ai_reply" if linked_jobs else "waiting_for_ai_worker" if ok else "blocked",
        "goal": mission.get("goal"),
        "run_count": run_count,
        "executed_steps": 0,
        "created_directives": len(task_refs),
        "task_refs": task_refs,
        "linked_jobs": linked_jobs,
        "blocked_job_starts": blocked_job_starts,
        "events_ref": _relative(events_path, root),
        "hard_gates": mission.get("hard_gates") or _hard_gates(),
        "source_code_modified_by_cambrian": False,
        "provider_api_called_by_cambrian": False,
        "next_command": mission.get("next_action")
        or "execute the task directive, then ingest and validate the AI reply evidence",
        "tasks": tasks,
    }


def resume_mission(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    mission_path = default_mission_path(root)
    if not mission_path.exists():
        return mission_status(root)
    mission = _load_yaml(mission_path)
    mission["status"] = "active"
    mission["updated_at"] = _now()
    mission["next_action"] = "cambrian mission run --max-steps 1 --json"
    _save_yaml(mission_path, mission)
    _append_event(root, {"event": "mission_resumed", "status": "active"})
    return mission_status(root)


def render_mission_result(payload: dict[str, Any]) -> str:
    lines = ["Cambrian Mission Company", ""]
    lines.append(f"Status: {payload.get('status')}")
    if payload.get("goal"):
        lines.append(f"Goal: {payload.get('goal')}")
    if payload.get("loop_kind"):
        lines.append(f"Loop: {payload.get('loop_kind')}")
    if payload.get("run_count") is not None:
        lines.append(f"Run count: {payload.get('run_count')}")
    if payload.get("mission_ref"):
        lines.append(f"Mission: {payload.get('mission_ref')}")
    if payload.get("task_refs"):
        lines.append("")
        lines.append("Task directives:")
        for ref in payload.get("task_refs") or []:
            lines.append(f"  - {ref}")
    if payload.get("linked_jobs"):
        lines.append("")
        lines.append("Linked jobs:")
        for item in payload.get("linked_jobs") or []:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('job_ref') or item.get('job_id')}")
    if payload.get("last_outcome"):
        outcome = payload.get("last_outcome")
        if isinstance(outcome, dict):
            lines.append("")
            lines.append("Last outcome:")
            lines.append(f"  job: {outcome.get('job_id') or outcome.get('job_ref')}")
            lines.append(f"  outcome: {outcome.get('outcome')}")
            lines.append(f"  verdict: {outcome.get('verdict')}")
    if payload.get("blocked_job_starts"):
        lines.append("")
        lines.append("Blocked job starts:")
        for item in payload.get("blocked_job_starts") or []:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('reason')}")
    if payload.get("hard_gates"):
        lines.append("")
        lines.append("Hard gates:")
        for gate in payload.get("hard_gates") or []:
            if isinstance(gate, dict):
                lines.append(f"  - {gate.get('id')}: {gate.get('requires')}")
    if payload.get("next_command"):
        lines.append("")
        lines.append(f"Next: {payload.get('next_command')}")
    if payload.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for error in payload.get("errors") or []:
            lines.append(f"  - {error}")
    return "\n".join(lines)
