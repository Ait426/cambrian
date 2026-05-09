from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_install import SCHEMA_VERSION, _relative


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
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def default_evolution_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "evolution"


def default_proposals_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "proposals"


def default_applied_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "applied"


def default_previews_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "previews"


def default_audit_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "audit"


def default_backups_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "backups"


def default_rollback_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "rollback"


def default_rollback_runs_dir(project_root: Path) -> Path:
    return default_rollback_dir(project_root) / "applied"


def default_history_path(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "history.yaml"


def default_last_review_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "evidence" / "repeated_failures.yaml"


def default_outcomes_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "evidence" / "outcomes.yaml"


def load_outcomes(project_root: Path) -> list[dict[str, Any]]:
    path = default_outcomes_path(project_root)
    if not path.exists():
        return []
    payload = _load_yaml(path)
    outcomes = payload.get("outcomes", [])
    if not isinstance(outcomes, list):
        return []
    return [dict(item) for item in outcomes if isinstance(item, dict)]


@dataclass
class EvolutionReviewResult:
    schema_version: str
    generated_at: str
    status: str
    reviewed_jobs: int
    signals: dict[str, Any]
    next_command: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "reviewed"
        return payload


@dataclass
class EvolutionProposalResult:
    schema_version: str
    generated_at: str
    status: str
    proposal_id: str | None
    summary: str | None
    changes: dict[str, Any]
    risk: str | None
    proposal_ref: str | None
    next_command: str | None
    quality_score: int | None = None
    risk_score: int | None = None
    evidence_refs: list[str] = field(default_factory=list)
    changed_files_preview: list[str] = field(default_factory=list)
    change_preview: dict[str, Any] = field(default_factory=dict)
    preview_ref: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "proposed"
        return payload


@dataclass
class EvolutionPreviewResult:
    schema_version: str
    generated_at: str
    status: str
    proposal_id: str | None
    proposal_ref: str | None
    preview_ref: str | None
    quality_score: int | None
    risk_score: int | None
    risk: str | None
    evidence_refs: list[str]
    changed_files_preview: list[str]
    change_preview: dict[str, Any]
    safety: dict[str, Any]
    next_command: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "previewed"
        return payload


@dataclass
class EvolutionApplyResult:
    schema_version: str
    generated_at: str
    status: str
    proposal_id: str | None
    applied_ref: str | None
    history_ref: str | None
    changed_files: list[str]
    audit_ref: str | None = None
    rollback_ref: str | None = None
    backup_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "applied"
        if self.status == "confirmation_required":
            payload["error"] = "confirmation_required"
        return payload


@dataclass
class EvolutionRollbackResult:
    schema_version: str
    generated_at: str
    status: str
    proposal_id: str | None
    rollback_ref: str | None
    rollback_applied_ref: str | None
    history_ref: str | None
    restored_files: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "rolled_back"
        if self.status == "confirmation_required":
            payload["error"] = "confirmation_required"
        return payload


def review_evidence(project_root: Path, recent: int = 5) -> EvolutionReviewResult:
    """최근 job outcome evidence에서 진화 후보 신호를 요약한다."""
    root = Path(project_root).resolve()
    outcomes = load_outcomes(root)
    selected = outcomes[-max(1, int(recent or 5)) :]
    if not selected:
        result = EvolutionReviewResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            reviewed_jobs=0,
            signals=_empty_signals(),
            next_command=None,
            errors=['No job outcome evidence found. Run: cambrian job complete latest --outcome partial --notes "..."'],
        )
        _save_yaml(default_last_review_path(root), result.to_dict())
        return result
    signals = _signals_from_outcomes(root, selected)
    result = EvolutionReviewResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="reviewed",
        reviewed_jobs=len(selected),
        signals=signals,
        next_command="cambrian evolve propose --json",
        warnings=[],
        errors=[],
    )
    _save_yaml(default_last_review_path(root), result.to_dict())
    return result


def propose_evolution(project_root: Path) -> EvolutionProposalResult:
    """저장된 outcome evidence를 바탕으로 적용 전 검토용 진화 제안서를 만든다."""
    root = Path(project_root).resolve()
    review = review_evidence(root, recent=5)
    if review.status != "reviewed":
        return EvolutionProposalResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=None,
            summary=None,
            changes={},
            risk=None,
            proposal_ref=None,
            next_command=None,
            errors=list(review.errors),
        )
    proposal_id = f"evolution-{_stamp()}"
    changes = _changes_from_signals(review.signals)
    preview = _proposal_preview(root, proposal_id, changes, review.signals)
    proposal = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "created_at": _now(),
        "status": "proposed",
        "summary": "Improve auth token flow coverage and validation command.",
        "risk": preview["risk"],
        "quality_score": preview["quality_score"],
        "risk_score": preview["risk_score"],
        "evidence": {
            "reviewed_jobs": review.reviewed_jobs,
            "signals": review.signals,
            "refs": preview["evidence_refs"],
        },
        "changes": changes,
        "changed_files_preview": preview["changed_files_preview"],
        "change_preview": preview["change_preview"],
        "safety": {
            "auto_apply": False,
            "source_code_modified": False,
            "preset_modified": False,
            "requires_confirm": True,
        },
        "next_command": f"cambrian evolve preview {proposal_id} --json",
    }
    proposal_path = _save_yaml(default_proposals_dir(root) / f"{proposal_id}.yaml", proposal)
    return EvolutionProposalResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="proposed",
        proposal_id=proposal_id,
        summary=str(proposal["summary"]),
        changes=changes,
        risk=str(preview["risk"]),
        proposal_ref=_relative(proposal_path, root),
        next_command=str(proposal["next_command"]),
        quality_score=int(preview["quality_score"]),
        risk_score=int(preview["risk_score"]),
        evidence_refs=list(preview["evidence_refs"]),
        changed_files_preview=list(preview["changed_files_preview"]),
        change_preview=dict(preview["change_preview"]),
    )


def preview_evolution(project_root: Path, proposal_id: str) -> EvolutionPreviewResult:
    """진화 제안을 적용하지 않고 변경 preview와 risk를 저장한다."""
    root = Path(project_root).resolve()
    proposal_path = _resolve_proposal_path(root, proposal_id)
    if proposal_path is None:
        return EvolutionPreviewResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=str(proposal_id or "").strip() or None,
            proposal_ref=None,
            preview_ref=None,
            quality_score=None,
            risk_score=None,
            risk=None,
            evidence_refs=[],
            changed_files_preview=[],
            change_preview={},
            safety={},
            next_command=None,
            errors=[f"proposal not found: {proposal_id}"],
        )
    proposal = _load_yaml(proposal_path)
    resolved_id = str(proposal.get("proposal_id") or proposal_path.stem)
    changes = proposal.get("changes") if isinstance(proposal.get("changes"), dict) else {}
    signals = proposal.get("evidence", {}).get("signals", {}) if isinstance(proposal.get("evidence"), dict) else {}
    preview = _proposal_preview(root, resolved_id, changes, signals)
    preview_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "status": "previewed",
        "proposal_id": resolved_id,
        "proposal_ref": _relative(proposal_path, root),
        "quality_score": preview["quality_score"],
        "risk_score": preview["risk_score"],
        "risk": preview["risk"],
        "evidence_refs": preview["evidence_refs"],
        "changed_files_preview": preview["changed_files_preview"],
        "change_preview": preview["change_preview"],
        "safety": {
            "auto_apply": False,
            "source_code_modified": False,
            "preset_modified": False,
            "requires_confirm": True,
        },
        "next_command": f"cambrian evolve apply {resolved_id} --confirm --json",
    }
    preview_path = _save_yaml(default_previews_dir(root) / f"{resolved_id}.yaml", preview_payload)
    return EvolutionPreviewResult(
        schema_version=SCHEMA_VERSION,
        generated_at=str(preview_payload["generated_at"]),
        status="previewed",
        proposal_id=resolved_id,
        proposal_ref=_relative(proposal_path, root),
        preview_ref=_relative(preview_path, root),
        quality_score=int(preview["quality_score"]),
        risk_score=int(preview["risk_score"]),
        risk=str(preview["risk"]),
        evidence_refs=list(preview["evidence_refs"]),
        changed_files_preview=list(preview["changed_files_preview"]),
        change_preview=dict(preview["change_preview"]),
        safety=dict(preview_payload["safety"]),
        next_command=str(preview_payload["next_command"]),
    )


def apply_evolution(project_root: Path, proposal_id: str, confirm: bool = False) -> EvolutionApplyResult:
    """사용자 승인 후 로컬 .cambrian metadata에만 진화 제안을 적용한다."""
    root = Path(project_root).resolve()
    proposal_ref = str(proposal_id or "").strip()
    if not proposal_ref:
        return EvolutionApplyResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=None,
            applied_ref=None,
            history_ref=None,
            changed_files=[],
            errors=["proposal id is required"],
        )
    proposal_path = _resolve_proposal_path(root, proposal_ref)
    if proposal_path is None:
        return EvolutionApplyResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=proposal_ref,
            applied_ref=None,
            history_ref=None,
            changed_files=[],
            errors=[f"proposal not found: {proposal_ref}"],
        )
    proposal = _load_yaml(proposal_path)
    resolved_id = str(proposal.get("proposal_id") or proposal_path.stem)
    if not confirm:
        return EvolutionApplyResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="confirmation_required",
            proposal_id=resolved_id,
            applied_ref=None,
            history_ref=None,
            changed_files=[],
            errors=["Review the evolution proposal before applying."],
        )
    candidate_paths = _candidate_change_paths(root, proposal)
    before_snapshots = _capture_before_snapshots(root, resolved_id, candidate_paths)
    changed = _apply_changes(root, proposal)
    audit_path, rollback_path, backup_refs = _write_apply_audit(
        root,
        resolved_id,
        proposal,
        changed,
        before_snapshots,
        _relative(proposal_path, root),
    )
    applied_payload = dict(proposal)
    applied_payload["status"] = "applied"
    applied_payload["applied_at"] = _now()
    applied_payload["changed_files"] = changed
    applied_payload["audit_ref"] = _relative(audit_path, root)
    applied_payload["rollback_ref"] = _relative(rollback_path, root)
    applied_payload["backup_refs"] = backup_refs
    applied_path = _save_yaml(default_applied_dir(root) / f"{resolved_id}.yaml", applied_payload)
    history_path = _append_history(
        root,
        resolved_id,
        changed,
        audit_ref=_relative(audit_path, root),
        rollback_ref=_relative(rollback_path, root),
    )
    return EvolutionApplyResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="applied",
        proposal_id=resolved_id,
        applied_ref=_relative(applied_path, root),
        history_ref=_relative(history_path, root),
        changed_files=changed,
        audit_ref=_relative(audit_path, root),
        rollback_ref=_relative(rollback_path, root),
        backup_refs=backup_refs,
    )


def rollback_evolution(project_root: Path, proposal_id: str, confirm: bool = False) -> EvolutionRollbackResult:
    """사용자 승인 후 apply 백업으로 로컬 .cambrian metadata만 복원한다."""
    root = Path(project_root).resolve()
    proposal_ref = str(proposal_id or "").strip()
    if not proposal_ref:
        return EvolutionRollbackResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=None,
            rollback_ref=None,
            rollback_applied_ref=None,
            history_ref=None,
            restored_files=[],
            errors=["proposal id is required"],
        )
    rollback_path = _resolve_rollback_path(root, proposal_ref)
    if rollback_path is None:
        return EvolutionRollbackResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=proposal_ref,
            rollback_ref=None,
            rollback_applied_ref=None,
            history_ref=None,
            restored_files=[],
            errors=[f"rollback manifest not found: {proposal_ref}"],
        )
    rollback_manifest = _load_yaml(rollback_path)
    resolved_id = str(rollback_manifest.get("proposal_id") or rollback_path.stem)
    if not confirm:
        return EvolutionRollbackResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="confirmation_required",
            proposal_id=resolved_id,
            rollback_ref=_relative(rollback_path, root),
            rollback_applied_ref=None,
            history_ref=None,
            restored_files=[],
            errors=["Review the rollback manifest before restoring metadata."],
        )
    restored, warnings = _restore_from_rollback_manifest(root, rollback_manifest)
    rollback_record = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": resolved_id,
        "rolled_back_at": _now(),
        "status": "rolled_back",
        "rollback_ref": _relative(rollback_path, root),
        "restored_files": restored,
        "warnings": warnings,
        "safety": {
            "source_code_modified": False,
            "preset_modified": False,
            "auto_apply": False,
            "requires_confirm": True,
        },
    }
    rollback_applied_path = _save_yaml(default_rollback_runs_dir(root) / f"{resolved_id}.yaml", rollback_record)
    history_path = _append_rollback_history(
        root,
        resolved_id,
        restored,
        rollback_ref=_relative(rollback_path, root),
        rollback_applied_ref=_relative(rollback_applied_path, root),
    )
    return EvolutionRollbackResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="rolled_back",
        proposal_id=resolved_id,
        rollback_ref=_relative(rollback_path, root),
        rollback_applied_ref=_relative(rollback_applied_path, root),
        history_ref=_relative(history_path, root),
        restored_files=restored,
        warnings=warnings,
    )


def _empty_signals() -> dict[str, Any]:
    return {
        "repeated_missing_paths": [],
        "wrong_test_commands": [],
        "validation_commands_needing_manual_run": [],
        "validation_evidence_refs": [],
        "trust_gate_status_counts": {},
        "validation_contract_statuses": [],
        "manual_validation_required_jobs": [],
        "unchecked_items": [],
        "outcome_counts": {},
        "evidence_gaps": [],
        "underused_agents": [],
        "skills_to_improve": [],
        "failure_terms": [],
    }


def _signals_from_outcomes(root: Path, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    signals = _empty_signals()
    notes_blob = "\n".join(str(item.get("notes") or "") for item in outcomes).lower()
    paths = _path_mentions(notes_blob)
    if "refresh" in notes_blob and "backend/src/routes/auth.ts" not in paths:
        paths.append("backend/src/routes/auth.ts")
    signals["repeated_missing_paths"] = paths[:8]
    if any(token in notes_blob for token in ["test command", "wrong test", "테스트 명령", "틀렸", "잘못"]):
        signals["wrong_test_commands"] = _validation_commands(outcomes)
    selected_agents = {agent for item in outcomes for agent in _as_list(item.get("selected_agents"))}
    workforce_agents = _installed_workforce_agents(root)
    signals["underused_agents"] = [agent for agent in workforce_agents if agent not in selected_agents]
    selected_skills = {skill for item in outcomes for skill in _as_list(item.get("selected_skills"))}
    if any(token in notes_blob for token in ["refresh", "token", "session", "auth", "인증", "세션", "토큰"]):
        selected_skills.add("trace-auth-token-flow")
    signals["skills_to_improve"] = sorted(selected_skills)
    terms: list[str] = []
    for term in ["refresh token", "session renewal", "test command", "auth route"]:
        if term in notes_blob:
            terms.append(term)
    signals["failure_terms"] = terms
    _enrich_signals_with_validation_evidence(signals, outcomes, notes_blob)
    return signals


def _enrich_signals_with_validation_evidence(
    signals: dict[str, Any],
    outcomes: list[dict[str, Any]],
    notes_blob: str,
) -> None:
    unchecked_blob = "\n".join(
        str(entry)
        for item in outcomes
        for entry in _as_list(item.get("unchecked_items"))
    ).lower()
    combined_blob = f"{notes_blob}\n{unchecked_blob}"
    paths = _merge_list(signals.get("repeated_missing_paths"), _path_mentions(unchecked_blob))
    if "refresh" in combined_blob and "backend/src/routes/auth.ts" not in paths:
        paths.append("backend/src/routes/auth.ts")
    signals["repeated_missing_paths"] = paths[:8]
    signals["validation_commands_needing_manual_run"] = _manual_validation_commands(outcomes)
    signals["validation_evidence_refs"] = _unique(
        str(item.get("validation_evidence_ref") or "")
        for item in outcomes
        if str(item.get("validation_evidence_ref") or "").strip()
    )
    signals["trust_gate_status_counts"] = _counts(str(item.get("trust_gate_status") or "unknown") for item in outcomes)
    signals["validation_contract_statuses"] = _unique(
        str(item.get("validation_contract_status") or "")
        for item in outcomes
        if str(item.get("validation_contract_status") or "").strip()
    )
    signals["manual_validation_required_jobs"] = [
        str(item.get("job_id") or "")
        for item in outcomes
        if _is_manual_validation_required(item)
    ]
    signals["unchecked_items"] = _unique(
        str(entry)
        for item in outcomes
        for entry in _as_list(item.get("unchecked_items"))
        if str(entry).strip()
    )
    signals["outcome_counts"] = _counts(str(item.get("outcome") or "unknown") for item in outcomes)
    signals["evidence_gaps"] = [
        str(item.get("job_id") or "")
        for item in outcomes
        if not str(item.get("validation_evidence_ref") or "").strip()
    ]
    if signals["manual_validation_required_jobs"]:
        skills = set(_as_list(signals.get("skills_to_improve")))
        skills.update(skill for item in outcomes for skill in _as_list(item.get("selected_skills")))
        signals["skills_to_improve"] = sorted(str(skill) for skill in skills if str(skill))
    if "manual validation" in combined_blob and "manual validation" not in signals["failure_terms"]:
        signals["failure_terms"].append("manual validation")
    if "patch proposal" in combined_blob and "patch proposal" not in signals["failure_terms"]:
        signals["failure_terms"].append("patch proposal")


def _is_manual_validation_required(outcome: dict[str, Any]) -> bool:
    return (
        str(outcome.get("validation_contract_status") or "") == "manual_validation_required"
        or str(outcome.get("trust_gate_status") or "") == "manual_required"
        or any("manual" in str(item).lower() for item in _as_list(outcome.get("unchecked_items")))
    )


def _manual_validation_commands(outcomes: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for item in outcomes:
        if not _is_manual_validation_required(item):
            continue
        commands.extend(_as_list(item.get("validation_commands")))
    return _unique(str(command) for command in commands if str(command).strip())


def _unique(items: Any) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if item is None or item == "":
            continue
        if item not in result:
            result.append(item)
    return result


def _counts(items: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(item or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _enrich_changes_from_signals(signals: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    harness = changes.get("harness") if isinstance(changes.get("harness"), dict) else {}
    harness["add_success_criteria"] = _merge_list(
        harness.get("add_success_criteria"),
        [f"Resolve unchecked validation item: {item}" for item in _as_list(signals.get("unchecked_items"))],
    )
    changes["harness"] = harness
    skill_changes = changes.get("skills") if isinstance(changes.get("skills"), dict) else {}
    updates = _as_dicts(skill_changes.get("update"))
    for update in updates:
        update["add_validation_required"] = _merge_list(
            update.get("add_validation_required"),
            [
                f"Manual validation evidence required: {command}"
                for command in _as_list(signals.get("validation_commands_needing_manual_run"))
            ],
        )
        update["known_failure_patterns"] = _merge_list(update.get("known_failure_patterns"), signals.get("unchecked_items"))
    skill_changes["update"] = updates
    changes["skills"] = skill_changes
    return changes


def _proposal_preview(root: Path, proposal_id: str, changes: dict[str, Any], signals: dict[str, Any]) -> dict[str, Any]:
    changed_files = _changed_files_preview(changes)
    risk_score = _risk_score(signals, changed_files)
    return {
        "proposal_id": proposal_id,
        "quality_score": _quality_score(signals, changes),
        "risk_score": risk_score,
        "risk": _risk_label(risk_score),
        "evidence_refs": _as_list(signals.get("validation_evidence_refs")),
        "changed_files_preview": changed_files,
        "change_preview": _change_preview(changes),
        "root": str(root),
    }


def _changed_files_preview(changes: dict[str, Any]) -> list[str]:
    files: list[str] = []
    harness_changes = changes.get("harness") if isinstance(changes.get("harness"), dict) else {}
    if harness_changes.get("add_important_paths"):
        files.append(".cambrian/harness.yaml")
    if harness_changes.get("update_validation_commands") or harness_changes.get("add_success_criteria"):
        files.append(".cambrian/validation.yaml")
    agent_changes = changes.get("agents") if isinstance(changes.get("agents"), dict) else {}
    for update in _as_dicts(agent_changes.get("update")):
        agent_id = str(update.get("id") or "").strip()
        if agent_id:
            files.append(f".cambrian/agents/{agent_id}.yaml")
    skill_changes = changes.get("skills") if isinstance(changes.get("skills"), dict) else {}
    for update in _as_dicts(skill_changes.get("update")):
        skill_id = str(update.get("id") or "").strip()
        if skill_id:
            files.append(f".cambrian/skills/{skill_id}.yaml")
    if files:
        files.append(".cambrian/workforce.yaml")
    return [str(item) for item in _merge_list([], files)]


def _change_preview(changes: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    harness_changes = changes.get("harness") if isinstance(changes.get("harness"), dict) else {}
    if harness_changes:
        preview[".cambrian/harness.yaml"] = {
            "add_important_paths": _as_list(harness_changes.get("add_important_paths")),
        }
        preview[".cambrian/validation.yaml"] = {
            "update_validation_commands": _as_list(harness_changes.get("update_validation_commands")),
            "add_success_criteria": _as_list(harness_changes.get("add_success_criteria")),
        }
    agent_changes = changes.get("agents") if isinstance(changes.get("agents"), dict) else {}
    for update in _as_dicts(agent_changes.get("update")):
        agent_id = str(update.get("id") or "").strip()
        if agent_id:
            preview[f".cambrian/agents/{agent_id}.yaml"] = {
                "add_responsibilities": _as_list(update.get("add_responsibilities")),
            }
    skill_changes = changes.get("skills") if isinstance(changes.get("skills"), dict) else {}
    for update in _as_dicts(skill_changes.get("update")):
        skill_id = str(update.get("id") or "").strip()
        if skill_id:
            preview[f".cambrian/skills/{skill_id}.yaml"] = {
                "add_procedure": _as_list(update.get("add_procedure")),
                "add_when_to_use": _as_list(update.get("add_when_to_use")),
                "add_validation_required": _as_list(update.get("add_validation_required")),
                "known_failure_patterns": _as_list(update.get("known_failure_patterns")),
            }
    return preview


def _quality_score(signals: dict[str, Any], changes: dict[str, Any]) -> int:
    score = 40
    if _as_list(signals.get("validation_evidence_refs")):
        score += 20
    if _as_list(signals.get("skills_to_improve")):
        score += 15
    if _as_list(signals.get("unchecked_items")):
        score += 10
    if _changed_files_preview(changes):
        score += 10
    if _as_list(signals.get("evidence_gaps")):
        score -= 20
    return max(0, min(100, score))


def _risk_score(signals: dict[str, Any], changed_files: list[str]) -> int:
    score = 10
    score += min(40, len(changed_files) * 5)
    if _as_list(signals.get("evidence_gaps")):
        score += 25
    if _as_list(signals.get("manual_validation_required_jobs")):
        score += 10
    return max(0, min(100, score))


def _risk_label(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _changes_from_signals(signals: dict[str, Any]) -> dict[str, Any]:
    missing_paths = _as_list(signals.get("repeated_missing_paths"))
    wrong_tests = _as_list(signals.get("wrong_test_commands"))
    failure_terms = _as_list(signals.get("failure_terms"))
    manual_commands = _as_list(signals.get("validation_commands_needing_manual_run"))
    unchecked_items = _as_list(signals.get("unchecked_items"))
    validation_required = ["refresh token route impact explanation"]
    validation_required.extend(f"Manual validation evidence required: {command}" for command in manual_commands)
    success_criteria = ["Repeated auth/session failure path is reflected in evidence"]
    success_criteria.extend(f"Resolve unchecked validation item: {item}" for item in unchecked_items)
    skill_updates: list[dict[str, Any]] = []
    if "trace-auth-token-flow" in _as_list(signals.get("skills_to_improve")):
        skill_updates.append(
            {
                "id": "trace-auth-token-flow",
                "add_procedure": [
                    "refresh token 발급, 저장, 검증, 폐기 경로를 함께 확인한다.",
                    "세션 갱신 실패와 Bearer token 검증 실패를 분리해 evidence로 기록한다.",
                ],
                "add_when_to_use": [
                    "refresh token mismatch",
                    "session renewal failure",
                ],
                "add_validation_required": [
                    "refresh token 경로 영향 설명",
                ],
                "known_failure_patterns": failure_terms,
            }
        )
    agent_updates = [
        {
            "id": "auth-flow-investigator",
            "add_responsibilities": [
                "refresh token 발급, 저장, 검증, 폐기 경로를 함께 확인한다.",
            ],
        }
    ]
    agent_proposals = []
    if "refresh token" in failure_terms:
        agent_proposals.append(
            {
                "id": "refresh-token-specialist",
                "reason": "Repeated refresh token misses in recent jobs",
                "apply_requires_confirm": True,
            }
        )
    changes = {
        "harness": {
            "add_important_paths": missing_paths,
            "update_validation_commands": wrong_tests,
            "add_success_criteria": [
                "반복 실패한 인증/session 경로가 evidence에 반영됨",
            ],
        },
        "agents": {
            "update": agent_updates,
            "agent_proposals": agent_proposals,
        },
        "skills": {
            "update": skill_updates,
        },
    }
    return _enrich_changes_from_signals(signals, changes)


def _apply_changes(root: Path, proposal: dict[str, Any]) -> list[str]:
    changes = proposal.get("changes", {}) if isinstance(proposal.get("changes"), dict) else {}
    changed: list[Path] = []
    harness_path = root / ".cambrian" / "harness.yaml"
    if harness_path.exists():
        harness = _load_yaml(harness_path)
        harness["version"] = _next_version(harness.get("version"))
        harness_changes = changes.get("harness", {}) if isinstance(changes.get("harness"), dict) else {}
        harness["important_paths"] = _merge_list(harness.get("important_paths"), _as_list(harness_changes.get("add_important_paths")))
        harness.setdefault("evolution_history", [])
        if isinstance(harness["evolution_history"], list):
            harness["evolution_history"].append({"proposal_id": proposal.get("proposal_id"), "applied_at": _now()})
        changed.append(_save_yaml(harness_path, harness))
    validation_path = root / ".cambrian" / "validation.yaml"
    if validation_path.exists():
        payload = _load_yaml(validation_path)
        validation = payload.get("validation", payload)
        if isinstance(validation, dict):
            harness_changes = changes.get("harness", {}) if isinstance(changes.get("harness"), dict) else {}
            validation["test_commands"] = _merge_list(validation.get("test_commands"), _as_list(harness_changes.get("update_validation_commands")))
            validation["success_criteria"] = _merge_list(validation.get("success_criteria"), _as_list(harness_changes.get("add_success_criteria")))
            payload["validation"] = validation
            payload["evolution_version"] = _next_version(payload.get("evolution_version"))
            changed.append(_save_yaml(validation_path, payload))
    agent_changes = changes.get("agents", {}) if isinstance(changes.get("agents"), dict) else {}
    for update in _as_dicts(agent_changes.get("update")):
        agent_path = root / ".cambrian" / "agents" / f"{update.get('id')}.yaml"
        if agent_path.exists():
            agent = _load_yaml(agent_path)
            agent["responsibilities"] = _merge_list(agent.get("responsibilities"), _as_list(update.get("add_responsibilities")))
            agent["evolution_version"] = _next_version(agent.get("evolution_version"))
            changed.append(_save_yaml(agent_path, agent))
    skill_changes = changes.get("skills", {}) if isinstance(changes.get("skills"), dict) else {}
    for update in _as_dicts(skill_changes.get("update")):
        skill_path = root / ".cambrian" / "skills" / f"{update.get('id')}.yaml"
        if skill_path.exists():
            skill = _load_yaml(skill_path)
            skill["procedure"] = _merge_list(skill.get("procedure"), _as_list(update.get("add_procedure")))
            skill["when_to_use"] = _merge_list(skill.get("when_to_use"), _as_list(update.get("add_when_to_use")))
            skill["known_failure_patterns"] = _merge_list(skill.get("known_failure_patterns"), _as_list(update.get("known_failure_patterns")))
            validation = skill.get("validation", {})
            if not isinstance(validation, dict):
                validation = {}
            validation["required"] = _merge_list(validation.get("required"), _as_list(update.get("add_validation_required")))
            skill["validation"] = validation
            skill["evolution_version"] = _next_version(skill.get("evolution_version"))
            changed.append(_save_yaml(skill_path, skill))
    workforce_path = root / ".cambrian" / "workforce.yaml"
    if workforce_path.exists():
        workforce = _load_yaml(workforce_path)
        workforce["evolution_version"] = _next_version(workforce.get("evolution_version"))
        changed.append(_save_yaml(workforce_path, workforce))
    return [_relative(path, root) for path in changed]


def _candidate_change_paths(root: Path, proposal: dict[str, Any]) -> list[Path]:
    changes = proposal.get("changes", {}) if isinstance(proposal.get("changes"), dict) else {}
    candidates: list[Path] = []
    for path in [
        root / ".cambrian" / "harness.yaml",
        root / ".cambrian" / "validation.yaml",
        root / ".cambrian" / "workforce.yaml",
    ]:
        if path.exists():
            candidates.append(path)

    agent_changes = changes.get("agents", {}) if isinstance(changes.get("agents"), dict) else {}
    for update in _as_dicts(agent_changes.get("update")):
        agent_id = str(update.get("id") or "").strip()
        if not agent_id:
            continue
        path = root / ".cambrian" / "agents" / f"{agent_id}.yaml"
        if path.exists():
            candidates.append(path)

    skill_changes = changes.get("skills", {}) if isinstance(changes.get("skills"), dict) else {}
    for update in _as_dicts(skill_changes.get("update")):
        skill_id = str(update.get("id") or "").strip()
        if not skill_id:
            continue
        path = root / ".cambrian" / "skills" / f"{skill_id}.yaml"
        if path.exists():
            candidates.append(path)

    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _capture_before_snapshots(root: Path, proposal_id: str, paths: list[Path]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    backup_root = default_backups_dir(root) / proposal_id
    for path in paths:
        rel = _relative(path, root)
        snapshot: dict[str, Any] = {
            "path": rel,
            "existed_before": path.exists(),
            "before_sha256": _sha256_file(path) if path.exists() else None,
            "backup_ref": None,
        }
        if path.exists():
            backup_path = backup_root / Path(*rel.split("/"))
            _atomic_write_text(backup_path, path.read_text(encoding="utf-8"))
            snapshot["backup_ref"] = _relative(backup_path, root)
        snapshots.append(snapshot)
    return snapshots


def _write_apply_audit(
    root: Path,
    proposal_id: str,
    proposal: dict[str, Any],
    changed_files: list[str],
    before_snapshots: list[dict[str, Any]],
    proposal_ref: str,
) -> tuple[Path, Path, list[str]]:
    now = _now()
    snapshots_by_path = {str(item.get("path")): item for item in before_snapshots}
    file_changes: list[dict[str, Any]] = []
    backup_refs: list[str] = []
    for rel in changed_files:
        path = root / Path(*str(rel).split("/"))
        before = snapshots_by_path.get(str(rel), {"path": rel, "existed_before": False, "before_sha256": None, "backup_ref": None})
        backup_ref = before.get("backup_ref")
        if isinstance(backup_ref, str) and backup_ref:
            backup_refs.append(backup_ref)
        file_changes.append(
            {
                "path": rel,
                "existed_before": bool(before.get("existed_before")),
                "exists_after": path.exists(),
                "before_sha256": before.get("before_sha256"),
                "after_sha256": _sha256_file(path) if path.exists() else None,
                "backup_ref": backup_ref,
            }
        )

    rollback_payload = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "created_at": now,
        "status": "manual_rollback_available",
        "automatic_rollback_command": None,
        "message": "V1은 자동 rollback을 실행하지 않는다. backup_ref를 확인한 뒤 필요한 metadata 파일을 수동 복원한다.",
        "files": [
            {
                "path": item["path"],
                "backup_ref": item.get("backup_ref"),
                "rollback_hint": f"필요하면 {item.get('backup_ref')} 내용을 {item['path']}로 복원한다.",
            }
            for item in file_changes
        ],
    }
    rollback_path = _save_yaml(default_rollback_dir(root) / f"{proposal_id}.yaml", rollback_payload)
    audit_payload = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "applied_at": now,
        "proposal_ref": proposal_ref,
        "summary": proposal.get("summary"),
        "risk": proposal.get("risk"),
        "quality_score": proposal.get("quality_score"),
        "risk_score": proposal.get("risk_score"),
        "changed_files": changed_files,
        "file_changes": file_changes,
        "rollback_ref": _relative(rollback_path, root),
        "safety": {
            "source_code_modified": False,
            "preset_modified": False,
            "auto_apply": False,
            "requires_confirm": True,
        },
    }
    audit_path = _save_yaml(default_audit_dir(root) / f"{proposal_id}.yaml", audit_payload)
    return audit_path, rollback_path, backup_refs


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _restore_from_rollback_manifest(root: Path, rollback_manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    restored: list[str] = []
    warnings: list[str] = []
    files = rollback_manifest.get("files", [])
    if not isinstance(files, list):
        return restored, ["rollback manifest files must be a list"]
    for item in files:
        if not isinstance(item, dict):
            warnings.append("rollback file entry is not a mapping")
            continue
        target_ref = str(item.get("path") or "").strip()
        backup_ref = str(item.get("backup_ref") or "").strip()
        if not target_ref or not backup_ref:
            warnings.append(f"rollback entry missing path or backup_ref: {target_ref or backup_ref}")
            continue
        if not _is_safe_metadata_ref(target_ref):
            warnings.append(f"blocked non-metadata rollback target: {target_ref}")
            continue
        target_path = (root / Path(*target_ref.split("/"))).resolve()
        backup_path = (root / Path(*backup_ref.split("/"))).resolve()
        if not _is_within(root, target_path) or not _is_within(root, backup_path):
            warnings.append(f"blocked path outside project root: {target_ref}")
            continue
        if not backup_path.exists():
            warnings.append(f"backup missing: {backup_ref}")
            continue
        _atomic_write_text(target_path, backup_path.read_text(encoding="utf-8"))
        restored.append(target_ref)
    return restored, warnings


def _is_safe_metadata_ref(path_ref: str) -> bool:
    normalized = str(path_ref).replace("\\", "/")
    if not normalized.startswith(".cambrian/"):
        return False
    blocked_prefixes = (
        ".cambrian/evolution/proposals/",
        ".cambrian/evolution/previews/",
        ".cambrian/evolution/audit/",
        ".cambrian/evolution/rollback/",
        ".cambrian/evolution/backups/",
    )
    return not normalized.startswith(blocked_prefixes)


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _append_history(
    root: Path,
    proposal_id: str,
    changed_files: list[str],
    audit_ref: str | None = None,
    rollback_ref: str | None = None,
) -> Path:
    path = default_history_path(root)
    payload = _load_yaml(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "applied": []}
    applied = payload.get("applied", [])
    if not isinstance(applied, list):
        applied = []
    applied.append({
        "proposal_id": proposal_id,
        "applied_at": _now(),
        "changed_files": changed_files,
        "audit_ref": audit_ref,
        "rollback_ref": rollback_ref,
    })
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["applied"] = applied
    return _save_yaml(path, payload)


def _append_rollback_history(
    root: Path,
    proposal_id: str,
    restored_files: list[str],
    rollback_ref: str | None,
    rollback_applied_ref: str | None,
) -> Path:
    path = default_history_path(root)
    payload = _load_yaml(path) if path.exists() else {"schema_version": SCHEMA_VERSION, "applied": []}
    rollbacks = payload.get("rollbacks", [])
    if not isinstance(rollbacks, list):
        rollbacks = []
    rollbacks.append({
        "proposal_id": proposal_id,
        "rolled_back_at": _now(),
        "restored_files": restored_files,
        "rollback_ref": rollback_ref,
        "rollback_applied_ref": rollback_applied_ref,
    })
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = _now()
    payload["rollbacks"] = rollbacks
    return _save_yaml(path, payload)


def _resolve_proposal_path(root: Path, proposal_id: str) -> Path | None:
    raw = str(proposal_id or "").strip()
    candidates = [Path(raw), default_proposals_dir(root) / f"{raw}.yaml", default_proposals_dir(root) / raw]
    for path in candidates:
        if path.exists():
            return path.resolve()
    return None


def _resolve_rollback_path(root: Path, proposal_id: str) -> Path | None:
    raw = str(proposal_id or "").strip()
    candidates = [Path(raw), default_rollback_dir(root) / f"{raw}.yaml", default_rollback_dir(root) / raw]
    for path in candidates:
        if path.exists():
            return path.resolve()
    return None


def _path_mentions(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|yaml|yml|json)", text):
        value = match.group(0).strip(".,;:()[]{}")
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _validation_commands(outcomes: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for item in outcomes:
        for command in _as_list(item.get("validation_commands")):
            if command and command not in commands:
                commands.append(command)
    return commands


def _installed_workforce_agents(root: Path) -> list[str]:
    path = root / ".cambrian" / "workforce.yaml"
    if not path.exists():
        return []
    try:
        payload = _load_yaml(path)
    except (OSError, ValueError, yaml.YAMLError):
        return []
    return [str(agent) for agent in _as_list(payload.get("agents")) if str(agent)]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _as_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in _as_list(value) if isinstance(item, dict)]


def _merge_list(existing: Any, additions: Any) -> list[Any]:
    merged: list[Any] = []
    for item in _as_list(existing) + _as_list(additions):
        if item is None or item == "":
            continue
        if item not in merged:
            merged.append(item)
    return merged


def _next_version(value: Any) -> int:
    try:
        return int(value or 0) + 1
    except (TypeError, ValueError):
        return 1
