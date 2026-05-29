from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_llm_assist import LLM_GENERATION_EVIDENCE_KEY, bootstrap_llm_generation_evidence, llm_assist_policy
from engine.project_pack_install import SCHEMA_VERSION, _relative

MIN_PATTERN_EVIDENCE_JOBS = 3
MIN_REVIEW_REQUIRED_JOBS = 10
MIN_TRUSTED_PATTERN_JOBS = 20
PROCESS_NOISE_TERMS = {
    "patch proposal",
    "manual validation",
}
PROCESS_NOISE_ITEMS = {
    "Patch proposal was not applied to source code",
    "Manual validation command must be run by the user",
}
PROCESS_NOISE_PREFIXES = (
    "Resolve unchecked validation item:",
)
PATH_CONTEXT_WINDOW = 120
PATH_REMOVAL_TERMS = (
    "delete",
    "deleted",
    "remove",
    "removed",
    "deprecate",
    "deprecated",
    "obsolete",
    "unused",
    "삭제",
    "제거",
    "폐기",
    "미사용",
)
PATH_CREATION_TERMS = (
    "add",
    "added",
    "create",
    "created",
    "new file",
    "추가",
    "생성",
)
PATH_MODIFICATION_TERMS = (
    "modify",
    "modified",
    "update",
    "updated",
    "patch",
    "patched",
    "change",
    "changed",
    "수정",
    "변경",
)


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
        prefix=".tmp-",
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


def default_preview_digest_path(project_root: Path, proposal_id: str) -> Path:
    return default_previews_dir(project_root) / f"{proposal_id}.digest.yaml"


def default_audit_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "audit"


def default_backups_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "backups"


def default_rollback_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "rollback"


def default_rollback_runs_dir(project_root: Path) -> Path:
    return default_rollback_dir(project_root) / "applied"


def default_review_decisions_dir(project_root: Path) -> Path:
    return default_evolution_dir(project_root) / "review_decisions"


def default_latest_review_decision_path(project_root: Path) -> Path:
    return default_review_decisions_dir(project_root) / "latest_promotion_review.yaml"


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
    promotion_review_decision_ref: str | None = None
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
    safety: dict[str, Any] = field(default_factory=dict)
    maturity_gate: dict[str, Any] = field(default_factory=dict)
    llm_assist_policy: dict[str, Any] = field(default_factory=dict)
    llm_generation_evidence: dict[str, Any] = field(default_factory=dict)

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
    proposal_sha256: str | None = None
    preview_sha256: str | None = None
    preview_digest_ref: str | None = None
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
    next_command: str | None = None
    rollback_command: str | None = None
    preview_ref: str | None = None
    preview_digest_ref: str | None = None
    proposal_sha256: str | None = None
    preview_sha256: str | None = None
    audit_ref: str | None = None
    rollback_ref: str | None = None
    promotion_review_decision_ref: str | None = None
    promotion_review_decision_sha256: str | None = None
    rollback_manifest_sha256: str | None = None
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
    next_command: str | None = None
    audit_ref: str | None = None
    preview_ref: str | None = None
    preview_digest_ref: str | None = None
    proposal_sha256: str | None = None
    preview_sha256: str | None = None
    promotion_review_decision_ref: str | None = None
    promotion_review_decision_sha256: str | None = None
    rollback_manifest_sha256: str | None = None
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
    decision_ref = _write_promotion_review_decision(root, signals, selected)
    result = EvolutionReviewResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="reviewed",
        reviewed_jobs=len(selected),
        signals=signals,
        next_command="cambrian evolve propose --json",
        promotion_review_decision_ref=decision_ref,
        warnings=[],
        errors=[],
    )
    _save_yaml(default_last_review_path(root), result.to_dict())
    return result


def propose_evolution(project_root: Path) -> EvolutionProposalResult:
    """저장된 outcome evidence를 바탕으로 적용 전 검토용 진화 제안서를 만든다."""
    root = Path(project_root).resolve()
    review = review_evidence(root, recent=MIN_TRUSTED_PATTERN_JOBS)
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
    promotion_review_decision_sha256 = _sha256_ref(root, review.promotion_review_decision_ref)
    maturity_gate = _maturity_gate(review.signals)
    proposal = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "created_at": _now(),
        "status": "proposed",
        "generation_quality_status": "bootstrap_draft",
        "llm_assist_policy": llm_assist_policy("evolution_proposal", provider_used=False),
        LLM_GENERATION_EVIDENCE_KEY: bootstrap_llm_generation_evidence("evolution_proposal"),
        "summary": "Improve auth token flow coverage and validation command.",
        "risk": preview["risk"],
        "quality_score": preview["quality_score"],
        "risk_score": preview["risk_score"],
        "evidence": {
            "reviewed_jobs": review.reviewed_jobs,
            "signals": review.signals,
            "refs": preview["evidence_refs"],
            "promotion_review_decision_ref": review.promotion_review_decision_ref,
            "promotion_review_decision_sha256": promotion_review_decision_sha256,
        },
        "maturity_gate": maturity_gate,
        "changes": changes,
        "changed_files_preview": preview["changed_files_preview"],
        "change_preview": preview["change_preview"],
        "safety": {
            "auto_apply": False,
            "auto_promote": False,
            "source_code_modified": False,
            "preset_modified": False,
            "requires_confirm": True,
            "promotion_review_required": _promotion_review_required(review.signals),
            "promotion_review_gate_status": _promotion_review_gate_status(review.signals),
            "maturity_gate_status": maturity_gate.get("status"),
            "evolution_apply_allowed": bool(maturity_gate.get("apply_allowed")),
            "maturity_gate": maturity_gate,
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
        safety=dict(proposal["safety"]),
        maturity_gate=dict(maturity_gate),
        llm_assist_policy=dict(proposal["llm_assist_policy"]),
        llm_generation_evidence=dict(proposal[LLM_GENERATION_EVIDENCE_KEY]),
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
    maturity_gate = _maturity_gate(signals)
    proposal_sha256 = _sha256_file(proposal_path)
    gate_errors = _promotion_review_decision_errors(root, proposal)
    if gate_errors:
        return EvolutionPreviewResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=resolved_id,
            proposal_ref=_relative(proposal_path, root),
            preview_ref=None,
            quality_score=None,
            risk_score=None,
            risk=None,
            evidence_refs=[],
            changed_files_preview=[],
            change_preview={},
            safety=_promotion_gate_safety(signals),
            next_command=None,
            proposal_sha256=proposal_sha256,
            errors=gate_errors,
        )
    preview = _proposal_preview(root, resolved_id, changes, signals)
    preview_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "status": "previewed",
        "proposal_id": resolved_id,
        "proposal_ref": _relative(proposal_path, root),
        "proposal_sha256": proposal_sha256,
        "quality_score": preview["quality_score"],
        "risk_score": preview["risk_score"],
        "risk": preview["risk"],
        "evidence_refs": preview["evidence_refs"],
        "changed_files_preview": preview["changed_files_preview"],
        "change_preview": preview["change_preview"],
        "safety": {
            "auto_apply": False,
            "auto_promote": False,
            "source_code_modified": False,
            "preset_modified": False,
            "requires_confirm": True,
            "promotion_review_required": _promotion_review_required(signals),
            "promotion_review_gate_status": _promotion_review_gate_status(signals),
            "maturity_gate_status": maturity_gate.get("status"),
            "evolution_apply_allowed": bool(maturity_gate.get("apply_allowed")),
            "maturity_gate": maturity_gate,
        },
        "next_command": f"cambrian evolve apply {resolved_id} --confirm --json",
    }
    preview_path = _save_yaml(default_previews_dir(root) / f"{resolved_id}.yaml", preview_payload)
    preview_sha256 = _sha256_file(preview_path)
    preview_digest_path = _write_preview_digest_lock(
        root,
        resolved_id,
        preview_path,
        proposal_sha256,
        preview_sha256,
    )
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
        proposal_sha256=proposal_sha256,
        preview_sha256=preview_sha256,
        preview_digest_ref=_relative(preview_digest_path, root),
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
            next_command=f"cambrian evolve apply {resolved_id} --confirm --json",
            errors=["Review the evolution proposal before applying."],
        )
    gate_errors = _promotion_review_decision_errors(root, proposal)
    if gate_errors:
        return EvolutionApplyResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=resolved_id,
            applied_ref=None,
            history_ref=None,
            changed_files=[],
            errors=gate_errors,
        )
    preview_path = default_previews_dir(root) / f"{resolved_id}.yaml"
    preview_errors = _preview_gate_errors(root, resolved_id, proposal, proposal_path, preview_path)
    if preview_errors:
        return EvolutionApplyResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=resolved_id,
            applied_ref=None,
            history_ref=None,
            changed_files=[],
            errors=preview_errors,
        )
    maturity_errors = _maturity_apply_errors(proposal)
    if maturity_errors:
        return EvolutionApplyResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=resolved_id,
            applied_ref=None,
            history_ref=None,
            changed_files=[],
            errors=maturity_errors,
        )
    preview_ref = _relative(preview_path, root)
    preview_digest_ref = _relative(default_preview_digest_path(root, resolved_id), root)
    proposal_path_ref = _relative(proposal_path, root)
    proposal_sha256 = _sha256_file(proposal_path)
    preview_sha256 = _sha256_file(preview_path)
    candidate_paths = _candidate_change_paths(root, proposal)
    before_snapshots = _capture_before_snapshots(root, resolved_id, candidate_paths)
    changed = _apply_changes(root, proposal)
    promotion_review_decision = _promotion_review_decision_snapshot(proposal)
    audit_path, rollback_path, backup_refs, rollback_manifest_sha256 = _write_apply_audit(
        root,
        resolved_id,
        proposal,
        changed,
        before_snapshots,
        proposal_path_ref,
        preview_ref,
        preview_digest_ref,
        proposal_sha256,
        preview_sha256,
    )
    applied_payload = dict(proposal)
    applied_payload["status"] = "applied"
    applied_payload["applied_at"] = _now()
    applied_payload["changed_files"] = changed
    applied_payload["proposal_ref"] = proposal_path_ref
    applied_payload["preview_ref"] = preview_ref
    applied_payload["preview_digest_ref"] = preview_digest_ref
    applied_payload["proposal_sha256"] = proposal_sha256
    applied_payload["preview_sha256"] = preview_sha256
    applied_payload["audit_ref"] = _relative(audit_path, root)
    applied_payload["rollback_ref"] = _relative(rollback_path, root)
    applied_payload["backup_refs"] = backup_refs
    applied_payload["promotion_review_decision"] = promotion_review_decision
    applied_payload["promotion_review_decision_ref"] = promotion_review_decision.get("ref")
    applied_payload["promotion_review_decision_sha256"] = promotion_review_decision.get("sha256")
    applied_payload["rollback_manifest_sha256"] = rollback_manifest_sha256
    applied_payload["rollback_command"] = f"cambrian evolve rollback {resolved_id} --confirm --json"
    applied_payload["next_command"] = f"cambrian evolve rollback {resolved_id} --confirm --json"
    applied_path = _save_yaml(default_applied_dir(root) / f"{resolved_id}.yaml", applied_payload)
    history_path = _append_history(
        root,
        resolved_id,
        changed,
        proposal_ref=proposal_path_ref,
        preview_ref=preview_ref,
        preview_digest_ref=preview_digest_ref,
        proposal_sha256=proposal_sha256,
        preview_sha256=preview_sha256,
        audit_ref=_relative(audit_path, root),
        rollback_ref=_relative(rollback_path, root),
        promotion_review_decision=promotion_review_decision,
        rollback_manifest_sha256=rollback_manifest_sha256,
    )
    return EvolutionApplyResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="applied",
        proposal_id=resolved_id,
        applied_ref=_relative(applied_path, root),
        history_ref=_relative(history_path, root),
        changed_files=changed,
        next_command=f"cambrian evolve rollback {resolved_id} --confirm --json",
        rollback_command=f"cambrian evolve rollback {resolved_id} --confirm --json",
        preview_ref=preview_ref,
        preview_digest_ref=preview_digest_ref,
        proposal_sha256=proposal_sha256,
        preview_sha256=preview_sha256,
        audit_ref=_relative(audit_path, root),
        rollback_ref=_relative(rollback_path, root),
        promotion_review_decision_ref=promotion_review_decision.get("ref"),
        promotion_review_decision_sha256=promotion_review_decision.get("sha256"),
        rollback_manifest_sha256=rollback_manifest_sha256,
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
            next_command=f"cambrian evolve rollback {resolved_id} --confirm --json",
            errors=["Review the rollback manifest before restoring metadata."],
        )
    integrity_errors = _rollback_manifest_integrity_errors(root, resolved_id, rollback_path, rollback_manifest)
    if integrity_errors:
        return EvolutionRollbackResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            proposal_id=resolved_id,
            rollback_ref=_relative(rollback_path, root),
            rollback_applied_ref=None,
            history_ref=None,
            restored_files=[],
            errors=integrity_errors,
        )
    audit_ref = str(rollback_manifest.get("audit_ref") or "").strip() or None
    preview_ref = str(rollback_manifest.get("preview_ref") or "").strip() or None
    preview_digest_ref = str(rollback_manifest.get("preview_digest_ref") or "").strip() or None
    proposal_sha256 = str(rollback_manifest.get("proposal_sha256") or "").strip() or None
    preview_sha256 = str(rollback_manifest.get("preview_sha256") or "").strip() or None
    promotion_review_decision = (
        dict(rollback_manifest.get("promotion_review_decision"))
        if isinstance(rollback_manifest.get("promotion_review_decision"), dict)
        else {}
    )
    rollback_manifest_sha256 = _sha256_file(rollback_path)
    restored, warnings = _restore_from_rollback_manifest(root, rollback_manifest)
    rollback_record = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": resolved_id,
        "rolled_back_at": _now(),
        "status": "rolled_back",
        "rollback_ref": _relative(rollback_path, root),
        "next_command": "cambrian evolve review --recent 5 --json",
        "audit_ref": audit_ref,
        "preview_ref": preview_ref,
        "preview_digest_ref": preview_digest_ref,
        "proposal_sha256": proposal_sha256,
        "preview_sha256": preview_sha256,
        "rollback_manifest_sha256": rollback_manifest_sha256,
        "promotion_review_decision": promotion_review_decision,
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
        audit_ref=audit_ref,
        preview_ref=preview_ref,
        preview_digest_ref=preview_digest_ref,
        proposal_sha256=proposal_sha256,
        preview_sha256=preview_sha256,
        promotion_review_decision=promotion_review_decision,
        rollback_manifest_sha256=rollback_manifest_sha256,
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
        next_command="cambrian evolve review --recent 5 --json",
        audit_ref=audit_ref,
        preview_ref=preview_ref,
        preview_digest_ref=preview_digest_ref,
        proposal_sha256=proposal_sha256,
        preview_sha256=preview_sha256,
        promotion_review_decision_ref=promotion_review_decision.get("ref"),
        promotion_review_decision_sha256=promotion_review_decision.get("sha256"),
        rollback_manifest_sha256=rollback_manifest_sha256,
        warnings=warnings,
    )


def _empty_signals() -> dict[str, Any]:
    return {
        "repeated_missing_paths": [],
        "path_contexts": {
            "important_candidates": [],
            "removed_or_deprecated": [],
            "created": [],
            "modified": [],
        },
        "wrong_test_commands": [],
        "validation_commands_needing_manual_run": [],
        "validation_evidence_refs": [],
        "trust_gate_status_counts": {},
        "validation_contract_statuses": [],
        "manual_validation_required_jobs": [],
        "unchecked_items": [],
        "outcome_counts": {},
        "evaluator_verdict_counts": {},
        "evaluator_verdict_refs": [],
        "promotion_review_gate": {
            "status": "no_verdict",
            "auto_promote": False,
            "review_required": False,
            "pass_jobs": [],
            "hold_jobs": [],
            "rollback_jobs": [],
            "reasons": [],
        },
        "evidence_gaps": [],
        "underused_agents": [],
        "skills_to_improve": [],
        "failure_terms": [],
        "process_noise_terms": [],
        "process_noise_items": [],
        "sample_size": 0,
        "pattern_threshold": MIN_PATTERN_EVIDENCE_JOBS,
        "pattern_threshold_met": False,
        "maturity_gate": {},
    }


def _signals_from_outcomes(root: Path, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    signals = _empty_signals()
    signals["sample_size"] = len(outcomes)
    signals["pattern_threshold_met"] = len(outcomes) >= MIN_PATTERN_EVIDENCE_JOBS
    notes_blob = "\n".join(str(item.get("notes") or "") for item in outcomes).lower()
    path_contexts = _path_contexts_from_text(root, notes_blob)
    signals["path_contexts"] = path_contexts
    signals["repeated_missing_paths"] = (
        _as_list(path_contexts.get("important_candidates"))[:8] if signals["pattern_threshold_met"] else []
    )
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
    signals["failure_terms"] = _domain_failure_terms(terms)
    _enrich_signals_with_validation_evidence(root, signals, outcomes, notes_blob)
    signals["maturity_gate"] = _evolution_maturity_gate(signals)
    return signals


def _enrich_signals_with_validation_evidence(
    root: Path,
    signals: dict[str, Any],
    outcomes: list[dict[str, Any]],
    notes_blob: str,
) -> None:
    raw_unchecked_items = _unique(
        str(entry)
        for item in outcomes
        for entry in _as_list(item.get("unchecked_items"))
        if str(entry).strip()
    )
    process_noise_items = [item for item in raw_unchecked_items if _is_process_noise_item(str(item))]
    for item in outcomes:
        if _records_unapplied_patch_proposal(item):
            process_noise_items.append("Patch proposal was not applied to source code")
    process_noise_items = _unique(process_noise_items)
    domain_unchecked_items = [item for item in raw_unchecked_items if not _is_process_noise_item(str(item))]
    unchecked_blob = "\n".join(str(item) for item in domain_unchecked_items).lower()
    raw_combined_blob = f"{notes_blob}\n" + "\n".join(str(item) for item in raw_unchecked_items).lower()
    signals["path_contexts"] = _merge_path_contexts(
        signals.get("path_contexts"),
        _path_contexts_from_text(root, unchecked_blob),
    )
    signals["repeated_missing_paths"] = (
        _as_list(signals["path_contexts"].get("important_candidates"))[:8]
        if bool(signals.get("pattern_threshold_met"))
        else []
    )
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
    signals["unchecked_items"] = domain_unchecked_items
    signals["process_noise_items"] = process_noise_items
    signals["outcome_counts"] = _counts(str(item.get("outcome") or "unknown") for item in outcomes)
    signals["evaluator_verdict_counts"] = _counts(
        str(_evaluator_verdict_summary(item).get("verdict") or "unknown") for item in outcomes
    )
    signals["evaluator_verdict_refs"] = _unique(
        str(item.get("latest_verdict_ref") or "")
        for item in outcomes
        if str(item.get("latest_verdict_ref") or "").strip()
    )
    signals["promotion_review_gate"] = _promotion_review_gate(outcomes)
    signals["evidence_gaps"] = [
        str(item.get("job_id") or "")
        for item in outcomes
        if not str(item.get("validation_evidence_ref") or "").strip()
    ]
    if signals["manual_validation_required_jobs"]:
        skills = set(_as_list(signals.get("skills_to_improve")))
        skills.update(skill for item in outcomes for skill in _as_list(item.get("selected_skills")))
        signals["skills_to_improve"] = sorted(str(skill) for skill in skills if str(skill))
    process_terms = [term for term in PROCESS_NOISE_TERMS if term in raw_combined_blob]
    signals["process_noise_terms"] = _unique(process_terms)
    signals["failure_terms"] = _domain_failure_terms(signals.get("failure_terms"))


def _is_manual_validation_required(outcome: dict[str, Any]) -> bool:
    return (
        str(outcome.get("validation_contract_status") or "") == "manual_validation_required"
        or str(outcome.get("trust_gate_status") or "") == "manual_required"
    )


def _manual_validation_commands(outcomes: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for item in outcomes:
        if not _is_manual_validation_required(item):
            continue
        commands.extend(_as_list(item.get("validation_commands")))
    return _unique(str(command) for command in commands if str(command).strip())


def _evaluator_verdict_summary(outcome: dict[str, Any]) -> dict[str, Any]:
    summary = outcome.get("evaluator_verdict")
    return dict(summary) if isinstance(summary, dict) else {}


def _promotion_review_gate(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    pass_jobs: list[str] = []
    hold_jobs: list[str] = []
    rollback_jobs: list[str] = []
    reasons: list[str] = []
    for outcome in outcomes:
        job_id = str(outcome.get("job_id") or "")
        summary = _evaluator_verdict_summary(outcome)
        verdict = str(summary.get("verdict") or "unknown")
        reason = str(summary.get("verdict_reason") or "").strip()
        if reason:
            reasons.append(reason)
        if verdict == "pass":
            pass_jobs.append(job_id)
        elif verdict == "rollback":
            rollback_jobs.append(job_id)
        elif verdict == "hold":
            hold_jobs.append(job_id)
    if pass_jobs:
        status = "review_required"
    elif rollback_jobs:
        status = "blocked_by_rollback"
    elif hold_jobs:
        status = "blocked_by_hold"
    else:
        status = "no_verdict"
    return {
        "status": status,
        "auto_promote": False,
        "review_required": bool(pass_jobs),
        "pass_jobs": _unique(pass_jobs),
        "hold_jobs": _unique(hold_jobs),
        "rollback_jobs": _unique(rollback_jobs),
        "reasons": _unique(reasons),
    }


def _write_promotion_review_decision(root: Path, signals: dict[str, Any], outcomes: list[dict[str, Any]]) -> str:
    gate = signals.get("promotion_review_gate") if isinstance(signals.get("promotion_review_gate"), dict) else {}
    decision = _promotion_review_decision(gate)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "decision_kind": "local_promotion_review_gate",
        "generated_at": _now(),
        "status": "recorded",
        "decision": decision,
        "promotion_review_gate": gate,
        "auto_promote": False,
        "review_required": bool(gate.get("review_required")),
        "reviewed_jobs": [
            {
                "job_id": str(item.get("job_id") or ""),
                "outcome": str(item.get("outcome") or ""),
                "evaluator_verdict": _evaluator_verdict_summary(item),
                "validation_evidence_ref": str(item.get("validation_evidence_ref") or ""),
                "latest_verdict_ref": str(item.get("latest_verdict_ref") or ""),
            }
            for item in outcomes
        ],
        "proof_boundary": {
            "uses_local_runtime_evidence": True,
            "auto_apply": False,
            "auto_promote": False,
            "source_code_modified": False,
            "success_rate_claim_allowed": False,
        },
        "next_step": _promotion_review_next_step(decision),
    }
    path = _save_yaml(default_latest_review_decision_path(root), payload)
    stamped = default_review_decisions_dir(root) / f"promotion-review-{_stamp()}.yaml"
    _save_yaml(stamped, payload)
    return _relative(path, root)


def _promotion_review_decision(gate: dict[str, Any]) -> str:
    status = str(gate.get("status") or "no_verdict")
    if status == "review_required":
        return "needs_human_review"
    if status == "blocked_by_rollback":
        return "blocked"
    if status == "blocked_by_hold":
        return "hold"
    return "no_decision"


def _promotion_review_next_step(decision: str) -> str:
    if decision == "needs_human_review":
        return "review_latest_verdict_before_any_promotion"
    if decision == "blocked":
        return "inspect_rollback_verdict_before_new_proposal"
    if decision == "hold":
        return "collect_stronger_validation_evidence"
    return "complete_a_job_with_evaluator_verdict"


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
    harness["add_success_criteria"] = _domain_success_criteria(harness.get("add_success_criteria"))
    changes["harness"] = harness
    skill_changes = changes.get("skills") if isinstance(changes.get("skills"), dict) else {}
    updates = _as_dicts(skill_changes.get("update"))
    failure_terms = _domain_failure_terms(_as_list(signals.get("failure_terms")))
    domain_validation_required = []
    if "refresh token" in failure_terms:
        domain_validation_required.append("refresh token mismatch evidence")
    for update in updates:
        manual_validation_required = [
            f"Manual validation evidence required: {command}"
            for command in _as_list(signals.get("validation_commands_needing_manual_run"))
        ]
        update["add_validation_required"] = _merge_list(
            update.get("add_validation_required"),
            [*domain_validation_required, *manual_validation_required],
        )
        update["known_failure_patterns"] = _domain_failure_terms(update.get("known_failure_patterns"))
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
        add_important_paths = _as_list(harness_changes.get("add_important_paths"))
        update_validation_commands = _as_list(harness_changes.get("update_validation_commands"))
        add_success_criteria = _as_list(harness_changes.get("add_success_criteria"))
        if add_important_paths:
            preview[".cambrian/harness.yaml"] = {
                "add_important_paths": add_important_paths,
            }
        if update_validation_commands or add_success_criteria:
            preview[".cambrian/validation.yaml"] = {
                "update_validation_commands": update_validation_commands,
                "add_success_criteria": add_success_criteria,
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


def _promotion_review_required(signals: dict[str, Any]) -> bool:
    gate = signals.get("promotion_review_gate") if isinstance(signals.get("promotion_review_gate"), dict) else {}
    return bool(gate.get("review_required"))


def _evolution_maturity_gate(signals: dict[str, Any]) -> dict[str, Any]:
    """진화 적용 가능 여부를 job evidence 수로 판정한다."""
    sample_size = int(signals.get("sample_size") or 0)
    if sample_size < MIN_PATTERN_EVIDENCE_JOBS:
        status = "insufficient_data"
        required_jobs = MIN_PATTERN_EVIDENCE_JOBS
        next_step = "collect_more_job_evidence"
        apply_allowed = False
    elif sample_size < MIN_REVIEW_REQUIRED_JOBS:
        status = "signal_candidate"
        required_jobs = MIN_REVIEW_REQUIRED_JOBS
        next_step = "record_candidate_signals_only"
        apply_allowed = False
    elif sample_size < MIN_TRUSTED_PATTERN_JOBS:
        status = "review_required"
        required_jobs = MIN_TRUSTED_PATTERN_JOBS
        next_step = "human_review_before_apply"
        apply_allowed = True
    else:
        status = "trusted_pattern"
        required_jobs = sample_size
        next_step = "human_confirmed_apply_allowed"
        apply_allowed = True
    return {
        "status": status,
        "sample_size": sample_size,
        "min_pattern_jobs": MIN_PATTERN_EVIDENCE_JOBS,
        "min_review_required_jobs": MIN_REVIEW_REQUIRED_JOBS,
        "min_trusted_pattern_jobs": MIN_TRUSTED_PATTERN_JOBS,
        "required_jobs_for_next_stage": required_jobs,
        "preview_allowed": True,
        "apply_allowed": apply_allowed,
        "auto_apply": False,
        "auto_promote": False,
        "next_step": next_step,
    }


def _maturity_gate(signals: dict[str, Any]) -> dict[str, Any]:
    """signals 안의 성숙도 게이트를 반환한다."""
    gate = signals.get("maturity_gate") if isinstance(signals.get("maturity_gate"), dict) else {}
    if gate:
        return gate
    return _evolution_maturity_gate(signals)


def _maturity_apply_allowed(signals: dict[str, Any]) -> bool:
    """현재 성숙도에서 metadata 진화 적용이 가능한지 반환한다."""
    return bool(_maturity_gate(signals).get("apply_allowed"))


def _promotion_review_gate_status(signals: dict[str, Any]) -> str:
    gate = signals.get("promotion_review_gate") if isinstance(signals.get("promotion_review_gate"), dict) else {}
    return str(gate.get("status") or "no_verdict")


def _promotion_gate_safety(signals: dict[str, Any]) -> dict[str, Any]:
    maturity_gate = _maturity_gate(signals)
    return {
        "auto_apply": False,
        "auto_promote": False,
        "source_code_modified": False,
        "preset_modified": False,
        "requires_confirm": True,
        "promotion_review_required": _promotion_review_required(signals),
        "promotion_review_gate_status": _promotion_review_gate_status(signals),
        "maturity_gate_status": maturity_gate.get("status"),
        "evolution_apply_allowed": bool(maturity_gate.get("apply_allowed")),
        "maturity_gate": maturity_gate,
    }


def _promotion_review_decision_errors(root: Path, proposal: dict[str, Any]) -> list[str]:
    signals = proposal.get("evidence", {}).get("signals", {}) if isinstance(proposal.get("evidence"), dict) else {}
    safety = proposal.get("safety", {}) if isinstance(proposal.get("safety"), dict) else {}
    review_required = bool(safety.get("promotion_review_required")) or _promotion_review_required(signals)
    if not review_required:
        return []
    decision_ref = str(
        proposal.get("evidence", {}).get("promotion_review_decision_ref")
        if isinstance(proposal.get("evidence"), dict)
        else ""
    ).strip()
    if not decision_ref:
        return ["promotion review decision is required before preview/apply"]
    decision_path = root / decision_ref
    if not decision_path.exists():
        return [f"promotion review decision not found: {decision_ref}"]
    expected_sha256 = str(
        proposal.get("evidence", {}).get("promotion_review_decision_sha256")
        if isinstance(proposal.get("evidence"), dict)
        else ""
    ).strip()
    if not expected_sha256:
        return ["promotion review decision digest is required before preview/apply"]
    actual_sha256 = _sha256_file(decision_path)
    if actual_sha256 != expected_sha256:
        return ["promotion review decision digest mismatch"]
    try:
        decision = _load_yaml(decision_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"promotion review decision could not be read: {exc}"]
    errors: list[str] = []
    proof_boundary = decision.get("proof_boundary", {}) if isinstance(decision.get("proof_boundary"), dict) else {}
    gate = decision.get("promotion_review_gate", {}) if isinstance(decision.get("promotion_review_gate"), dict) else {}
    if str(decision.get("decision_kind") or "") != "local_promotion_review_gate":
        errors.append("promotion review decision_kind is invalid")
    if str(decision.get("decision") or "") != "needs_human_review":
        errors.append("promotion review decision must be needs_human_review")
    if bool(decision.get("auto_promote")):
        errors.append("promotion review decision must not auto_promote")
    if bool(proof_boundary.get("auto_promote")):
        errors.append("promotion review proof boundary must not auto_promote")
    if bool(proof_boundary.get("auto_apply")):
        errors.append("promotion review proof boundary must not auto_apply")
    if str(gate.get("status") or "") != "review_required":
        errors.append("promotion review gate status must be review_required")
    if not bool(gate.get("review_required")):
        errors.append("promotion review gate must require review")
    return errors


def _maturity_apply_errors(proposal: dict[str, Any]) -> list[str]:
    """진화 성숙도 게이트가 apply를 허용하는지 확인한다."""
    evidence = proposal.get("evidence", {}) if isinstance(proposal.get("evidence"), dict) else {}
    signals = evidence.get("signals", {}) if isinstance(evidence.get("signals"), dict) else {}
    gate = _maturity_gate(signals)
    if bool(gate.get("apply_allowed")):
        return []
    status = str(gate.get("status") or "unknown")
    required_jobs = int(gate.get("required_jobs_for_next_stage") or MIN_REVIEW_REQUIRED_JOBS)
    sample_size = int(gate.get("sample_size") or 0)
    return [f"evolution maturity gate blocked apply: {status} requires at least {required_jobs} jobs (current: {sample_size})"]


def _promotion_review_decision_snapshot(proposal: dict[str, Any]) -> dict[str, Any]:
    evidence = proposal.get("evidence", {}) if isinstance(proposal.get("evidence"), dict) else {}
    signals = evidence.get("signals", {}) if isinstance(evidence.get("signals"), dict) else {}
    safety = proposal.get("safety", {}) if isinstance(proposal.get("safety"), dict) else {}
    ref = str(evidence.get("promotion_review_decision_ref") or "").strip() or None
    sha256 = str(evidence.get("promotion_review_decision_sha256") or "").strip() or None
    return {
        "ref": ref,
        "sha256": sha256,
        "review_required": bool(safety.get("promotion_review_required")) or _promotion_review_required(signals),
        "gate_status": str(safety.get("promotion_review_gate_status") or _promotion_review_gate_status(signals)),
        "auto_promote": False,
        "auto_apply": False,
    }


def _write_preview_digest_lock(
    root: Path,
    proposal_id: str,
    preview_path: Path,
    proposal_sha256: str,
    preview_sha256: str,
) -> Path:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "lock_kind": "evolution_preview_digest_lock",
        "created_at": _now(),
        "proposal_id": proposal_id,
        "preview_ref": _relative(preview_path, root),
        "proposal_sha256": proposal_sha256,
        "preview_sha256": preview_sha256,
    }
    return _save_yaml(default_preview_digest_path(root, proposal_id), payload)


def _preview_gate_errors(
    root: Path,
    proposal_id: str,
    proposal: dict[str, Any],
    proposal_path: Path,
    preview_path: Path,
) -> list[str]:
    if not preview_path.exists():
        return [f"preview is required before apply: cambrian evolve preview {proposal_id} --json"]
    try:
        preview = _load_yaml(preview_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"preview could not be read before apply: {exc}"]

    errors: list[str] = []
    digest_path = default_preview_digest_path(root, proposal_id)
    if not digest_path.exists():
        return ["preview digest lock is required before apply"]
    try:
        digest_lock = _load_yaml(digest_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"preview digest lock could not be read before apply: {exc}"]
    if str(digest_lock.get("lock_kind") or "") != "evolution_preview_digest_lock":
        errors.append("preview digest lock_kind is invalid")
    if str(digest_lock.get("preview_ref") or "") != _relative(preview_path, root):
        errors.append("preview digest lock ref mismatch")
    locked_preview_sha256 = str(digest_lock.get("preview_sha256") or "").strip()
    if not locked_preview_sha256:
        errors.append("preview digest lock sha256 is required before apply")
    elif locked_preview_sha256 != _sha256_file(preview_path):
        errors.append("preview digest mismatch")
    locked_proposal_sha256 = str(digest_lock.get("proposal_sha256") or "").strip()
    if locked_proposal_sha256 and locked_proposal_sha256 != str(preview.get("proposal_sha256") or "").strip():
        errors.append("preview digest lock proposal mismatch")
    if str(preview.get("status") or "") != "previewed":
        errors.append("preview status must be previewed before apply")
    if str(preview.get("proposal_ref") or "") != _relative(proposal_path, root):
        errors.append("preview proposal_ref mismatch")
    expected_proposal_sha256 = str(preview.get("proposal_sha256") or "").strip()
    if not expected_proposal_sha256:
        errors.append("preview proposal digest is required before apply")
    elif expected_proposal_sha256 != _sha256_file(proposal_path):
        errors.append("preview proposal digest mismatch")
    if preview.get("changed_files_preview") != proposal.get("changed_files_preview"):
        errors.append("preview changed_files mismatch")
    if preview.get("change_preview") != proposal.get("change_preview"):
        errors.append("preview change details mismatch")
    safety = preview.get("safety") if isinstance(preview.get("safety"), dict) else {}
    if bool(safety.get("source_code_modified")):
        errors.append("preview safety must not modify source code")
    if bool(safety.get("preset_modified")):
        errors.append("preview safety must not modify preset")
    if bool(safety.get("auto_apply")):
        errors.append("preview safety must not auto_apply")
    if bool(safety.get("auto_promote")):
        errors.append("preview safety must not auto_promote")
    if not bool(safety.get("requires_confirm")):
        errors.append("preview safety must require confirm")
    return errors


def _rollback_manifest_integrity_errors(
    root: Path,
    proposal_id: str,
    rollback_path: Path,
    rollback_manifest: dict[str, Any],
) -> list[str]:
    applied_path = default_applied_dir(root) / f"{proposal_id}.yaml"
    if not applied_path.exists():
        return [f"applied record not found for rollback: {proposal_id}"]
    try:
        applied = _load_yaml(applied_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [f"applied record could not be read before rollback: {exc}"]

    expected_ref = str(applied.get("rollback_ref") or "").strip()
    actual_ref = _relative(rollback_path, root)
    if expected_ref and expected_ref != actual_ref:
        return ["rollback manifest ref mismatch"]

    for key, message in [
        ("proposal_sha256", "rollback proposal digest mismatch"),
        ("preview_ref", "rollback preview ref mismatch"),
        ("preview_digest_ref", "rollback preview digest ref mismatch"),
        ("preview_sha256", "rollback preview digest mismatch"),
    ]:
        expected_value = str(applied.get(key) or "").strip()
        manifest_value = str(rollback_manifest.get(key) or "").strip()
        if expected_value and manifest_value != expected_value:
            return [message]

    expected_sha256 = str(applied.get("rollback_manifest_sha256") or "").strip()
    if not expected_sha256:
        return ["rollback manifest digest is required before rollback"]
    if _sha256_file(rollback_path) != expected_sha256:
        return ["rollback manifest digest mismatch"]

    applied_decision = applied.get("promotion_review_decision") if isinstance(applied.get("promotion_review_decision"), dict) else {}
    manifest_decision = (
        rollback_manifest.get("promotion_review_decision")
        if isinstance(rollback_manifest.get("promotion_review_decision"), dict)
        else {}
    )
    if applied_decision.get("ref") != manifest_decision.get("ref"):
        return ["rollback promotion review decision ref mismatch"]
    if applied_decision.get("sha256") != manifest_decision.get("sha256"):
        return ["rollback promotion review decision digest mismatch"]
    return []


def _sha256_ref(root: Path, ref: str | None) -> str | None:
    text = str(ref or "").strip()
    if not text:
        return None
    path = root / text
    if not path.exists():
        return None
    return _sha256_file(path)


def _changes_from_signals(signals: dict[str, Any]) -> dict[str, Any]:
    if not _maturity_apply_allowed(signals):
        return {
            "harness": {
                "add_important_paths": [],
                "update_validation_commands": [],
                "add_success_criteria": [],
            },
            "agents": {
                "update": [],
                "agent_proposals": [],
            },
            "skills": {
                "update": [],
            },
        }
    missing_paths = _as_list(signals.get("repeated_missing_paths")) if bool(signals.get("pattern_threshold_met")) else []
    wrong_tests = _as_list(signals.get("wrong_test_commands"))
    failure_terms = _domain_failure_terms(_as_list(signals.get("failure_terms")))
    manual_commands = _as_list(signals.get("validation_commands_needing_manual_run"))
    validation_required = ["인증/session 경로 영향 설명"]
    validation_required.extend(f"Manual validation evidence required: {command}" for command in manual_commands)
    success_criteria = []
    if missing_paths:
        success_criteria.append("반복 실패한 인증/session 경로가 실제 존재하는 프로젝트 경로 evidence에 반영됨")
    skill_when_to_use = [
        "auth/session regression",
        "provider token boundary",
    ]
    if "refresh token" in failure_terms:
        skill_when_to_use.append("refresh token mismatch")
    skill_updates: list[dict[str, Any]] = []
    if "trace-auth-token-flow" in _as_list(signals.get("skills_to_improve")):
        skill_updates.append(
            {
                "id": "trace-auth-token-flow",
                "add_procedure": [
                    "인증/session 경계와 provider-managed token 책임 범위를 확인한다.",
                    "직접 관리하지 않는 refresh token은 코드 책임으로 추정하지 않는다.",
                ],
                "add_when_to_use": skill_when_to_use,
                "add_validation_required": [
                    "인증/session 경로 영향 설명",
                ],
                "known_failure_patterns": failure_terms,
            }
        )
    agent_updates = []
    if "trace-auth-token-flow" in _as_list(signals.get("skills_to_improve")):
        agent_updates.append(
            {
                "id": "auth-flow-investigator",
                "add_responsibilities": [
                    "인증/session 경계와 provider-managed token 책임 범위를 확인한다.",
                ],
            }
        )
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
            "add_success_criteria": success_criteria,
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
            "backup_sha256": None,
        }
        if path.exists():
            backup_path = backup_root / Path(*rel.split("/"))
            _atomic_write_text(backup_path, path.read_text(encoding="utf-8"))
            snapshot["backup_ref"] = _relative(backup_path, root)
            snapshot["backup_sha256"] = _sha256_file(backup_path)
        snapshots.append(snapshot)
    return snapshots


def _write_apply_audit(
    root: Path,
    proposal_id: str,
    proposal: dict[str, Any],
    changed_files: list[str],
    before_snapshots: list[dict[str, Any]],
    proposal_ref: str,
    preview_ref: str,
    preview_digest_ref: str,
    proposal_sha256: str,
    preview_sha256: str,
) -> tuple[Path, Path, list[str], str]:
    now = _now()
    promotion_review_decision = _promotion_review_decision_snapshot(proposal)
    snapshots_by_path = {str(item.get("path")): item for item in before_snapshots}
    file_changes: list[dict[str, Any]] = []
    backup_refs: list[str] = []
    for rel in changed_files:
        path = root / Path(*str(rel).split("/"))
        before = snapshots_by_path.get(str(rel), {"path": rel, "existed_before": False, "before_sha256": None, "backup_ref": None})
        backup_ref = before.get("backup_ref")
        backup_sha256 = before.get("backup_sha256")
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
                "backup_sha256": backup_sha256,
            }
        )

    rollback_path = default_rollback_dir(root) / f"{proposal_id}.yaml"
    audit_path = default_audit_dir(root) / f"{proposal_id}.yaml"
    rollback_payload = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "created_at": now,
        "status": "manual_rollback_available",
        "automatic_rollback_command": None,
        "rollback_command": f"cambrian evolve rollback {proposal_id} --confirm --json",
        "audit_ref": _relative(audit_path, root),
        "proposal_ref": proposal_ref,
        "proposal_sha256": proposal_sha256,
        "preview_ref": preview_ref,
        "preview_digest_ref": preview_digest_ref,
        "preview_sha256": preview_sha256,
        "promotion_review_decision": promotion_review_decision,
        "message": "V1은 자동 rollback을 실행하지 않는다. backup_ref를 확인한 뒤 필요한 metadata 파일을 수동 복원한다.",
        "files": [
            {
                "path": item["path"],
                "backup_ref": item.get("backup_ref"),
                "backup_sha256": item.get("backup_sha256"),
                "rollback_hint": f"필요하면 {item.get('backup_ref')} 내용을 {item['path']}로 복원한다.",
            }
            for item in file_changes
        ],
    }
    rollback_path = _save_yaml(rollback_path, rollback_payload)
    rollback_manifest_sha256 = _sha256_file(rollback_path)
    audit_payload = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": proposal_id,
        "applied_at": now,
        "proposal_ref": proposal_ref,
        "preview_ref": preview_ref,
        "preview_digest_ref": preview_digest_ref,
        "proposal_sha256": proposal_sha256,
        "preview_sha256": preview_sha256,
        "summary": proposal.get("summary"),
        "risk": proposal.get("risk"),
        "quality_score": proposal.get("quality_score"),
        "risk_score": proposal.get("risk_score"),
        "changed_files": changed_files,
        "file_changes": file_changes,
        "promotion_review_decision": promotion_review_decision,
        "rollback_ref": _relative(rollback_path, root),
        "rollback_manifest_sha256": rollback_manifest_sha256,
        "safety": {
            "source_code_modified": False,
            "preset_modified": False,
            "auto_apply": False,
            "requires_confirm": True,
        },
    }
    audit_path = _save_yaml(audit_path, audit_payload)
    return audit_path, rollback_path, backup_refs, rollback_manifest_sha256


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
        expected_backup_sha256 = str(item.get("backup_sha256") or "").strip()
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
        if not expected_backup_sha256:
            warnings.append(f"backup sha256 missing: {backup_ref}")
            continue
        actual_backup_sha256 = _sha256_file(backup_path)
        if actual_backup_sha256 != expected_backup_sha256:
            warnings.append(f"backup sha256 mismatch: {backup_ref}")
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
    proposal_ref: str | None = None,
    preview_ref: str | None = None,
    preview_digest_ref: str | None = None,
    proposal_sha256: str | None = None,
    preview_sha256: str | None = None,
    audit_ref: str | None = None,
    rollback_ref: str | None = None,
    promotion_review_decision: dict[str, Any] | None = None,
    rollback_manifest_sha256: str | None = None,
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
        "proposal_ref": proposal_ref,
        "preview_ref": preview_ref,
        "preview_digest_ref": preview_digest_ref,
        "proposal_sha256": proposal_sha256,
        "preview_sha256": preview_sha256,
        "audit_ref": audit_ref,
        "rollback_ref": rollback_ref,
        "promotion_review_decision": promotion_review_decision or {},
        "rollback_manifest_sha256": rollback_manifest_sha256,
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
    audit_ref: str | None = None,
    preview_ref: str | None = None,
    preview_digest_ref: str | None = None,
    proposal_sha256: str | None = None,
    preview_sha256: str | None = None,
    promotion_review_decision: dict[str, Any] | None = None,
    rollback_manifest_sha256: str | None = None,
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
        "audit_ref": audit_ref,
        "preview_ref": preview_ref,
        "preview_digest_ref": preview_digest_ref,
        "proposal_sha256": proposal_sha256,
        "preview_sha256": preview_sha256,
        "promotion_review_decision": promotion_review_decision or {},
        "rollback_manifest_sha256": rollback_manifest_sha256,
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
    if raw in {"latest", "last"}:
        latest_ref = _latest_rollback_ref(root)
        if latest_ref:
            latest_path = (root / Path(*latest_ref.split("/"))).resolve()
            if latest_path.exists():
                return latest_path
    candidates = [Path(raw), default_rollback_dir(root) / f"{raw}.yaml", default_rollback_dir(root) / raw]
    for path in candidates:
        if path.exists():
            return path.resolve()
    return None


def _latest_rollback_ref(root: Path) -> str | None:
    history_path = default_history_path(root)
    if not history_path.exists():
        return None
    try:
        history = _load_yaml(history_path)
    except (OSError, ValueError, yaml.YAMLError):
        return None
    applied = history.get("applied", [])
    if not isinstance(applied, list):
        return None
    for item in reversed(applied):
        if not isinstance(item, dict):
            continue
        rollback_ref = str(item.get("rollback_ref") or "").strip()
        if rollback_ref:
            return rollback_ref
    return None


def _path_mentions(text: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|yaml|yml|json)", text):
        value = match.group(0).strip(".,;:()[]{}")
        if value and value not in candidates:
            candidates.append(value)
    return candidates


def _path_contexts_from_text(root: Path, text: str) -> dict[str, list[str]]:
    """파일 경로 언급을 행동 맥락별로 분리한다."""
    contexts = {
        "important_candidates": [],
        "removed_or_deprecated": [],
        "created": [],
        "modified": [],
    }
    blob = str(text or "")
    if not blob:
        return contexts
    for match in re.finditer(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|yaml|yml|json)", blob):
        raw_path = match.group(0).strip(".,;:()[]{}")
        start = max(0, match.start() - PATH_CONTEXT_WINDOW)
        end = min(len(blob), match.end() + PATH_CONTEXT_WINDOW)
        window = blob[start:end].lower()
        bucket = _path_context_bucket(window)
        relative_path = _project_relative_path(root, raw_path, require_exists=bucket == "important_candidates")
        if not relative_path:
            continue
        if relative_path not in contexts[bucket]:
            contexts[bucket].append(relative_path)
    removed = set(contexts["removed_or_deprecated"])
    contexts["important_candidates"] = [path for path in contexts["important_candidates"] if path not in removed]
    return contexts


def _path_context_bucket(context: str) -> str:
    if any(term in context for term in PATH_REMOVAL_TERMS):
        return "removed_or_deprecated"
    if any(term in context for term in PATH_CREATION_TERMS):
        return "created"
    if any(term in context for term in PATH_MODIFICATION_TERMS):
        return "modified"
    return "important_candidates"


def _merge_path_contexts(existing: Any, additions: Any) -> dict[str, list[str]]:
    merged = {
        "important_candidates": [],
        "removed_or_deprecated": [],
        "created": [],
        "modified": [],
    }
    for source in [existing, additions]:
        if not isinstance(source, dict):
            continue
        for key in merged:
            merged[key] = _merge_list(merged[key], source.get(key))
    removed = set(merged["removed_or_deprecated"])
    merged["important_candidates"] = [path for path in merged["important_candidates"] if path not in removed]
    return merged


def _project_relative_path(root: Path, value: Any, require_exists: bool) -> str | None:
    project_root = Path(root).resolve()
    text = str(value or "").strip().replace("\\", "/")
    if not text or text.startswith(".cambrian/") or Path(text).is_absolute():
        return None
    candidate = (project_root / text).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError:
        return None
    if require_exists and not candidate.exists():
        return None
    return text


def _existing_project_paths(root: Path, paths: Any) -> list[str]:
    """프로젝트 안에 실제 존재하는 상대 경로만 유지한다."""
    kept: list[str] = []
    for item in _as_list(paths):
        text = _project_relative_path(root, item, require_exists=True)
        if text and text not in kept:
            kept.append(text)
    return kept


def _is_process_noise_item(value: str) -> bool:
    """Cambrian 자체 처리 경고인지 확인한다."""
    text = str(value or "").strip()
    lower = text.lower()
    if text in PROCESS_NOISE_ITEMS:
        return True
    if any(text.startswith(prefix) for prefix in PROCESS_NOISE_PREFIXES):
        return True
    return any(item.lower() in lower for item in PROCESS_NOISE_ITEMS)


def _records_unapplied_patch_proposal(outcome: dict[str, Any]) -> bool:
    if bool(outcome.get("patch_applied_by_cambrian")) or bool(outcome.get("source_code_modified_by_cambrian")):
        return False
    checked = " ".join(_as_list(outcome.get("checked_artifacts"))).lower()
    selected_skills = " ".join(_as_list(outcome.get("selected_skills"))).lower()
    patch_state = outcome.get("patch_application_state", {}) if isinstance(outcome.get("patch_application_state"), dict) else {}
    patch_state_known = "patch_application_state" in outcome
    return (
        "patch_intents" in checked
        or "patch" in selected_skills
        or bool(patch_state_known and patch_state.get("patch_applied") is False)
    )


def _domain_failure_terms(values: Any) -> list[str]:
    """프로젝트 도메인 신호만 남기고 Cambrian 프로세스 노이즈를 제거한다."""
    terms: list[str] = []
    for item in _as_list(values):
        text = str(item or "").strip()
        if not text:
            continue
        if text.lower() in PROCESS_NOISE_TERMS:
            continue
        if _is_process_noise_item(text):
            continue
        if text not in terms:
            terms.append(text)
    return terms


def _domain_success_criteria(values: Any) -> list[str]:
    """success criteria에 들어가면 안 되는 프로세스 해결 문구를 제거한다."""
    criteria: list[str] = []
    for item in _as_list(values):
        text = str(item or "").strip()
        if not text:
            continue
        if text.startswith("Resolve unchecked validation item:"):
            continue
        if text not in criteria:
            criteria.append(text)
    return criteria


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
