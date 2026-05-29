from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_install import SCHEMA_VERSION, _relative, _slug
from engine.project_pack_jobs import PackJob, PackJobStore, default_pack_jobs_dir, latest_pack_job_path


ALLOWED_OUTCOMES = {"success", "partial", "failed", "rejected", "needs_more_info"}
LOGGER = logging.getLogger(__name__)


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


def default_jobs_evidence_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "jobs"


def default_evidence_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "evidence"


def default_outcomes_path(project_root: Path) -> Path:
    return default_evidence_dir(project_root) / "outcomes.yaml"


def job_outcome_path(project_root: Path, job_id: str) -> Path:
    return default_jobs_evidence_dir(project_root) / _slug(job_id, "job") / "outcome.yaml"


@dataclass
class JobCompleteResult:
    schema_version: str
    generated_at: str
    status: str
    job_id: str | None
    outcome: str | None
    notes: str | None
    outcome_ref: str | None
    evidence_ref: str | None
    validation_evidence_ref: str | None = None
    validation_contract_status: str | None = None
    trust_gate_status: str | None = None
    latest_verdict_ref: str | None = None
    evaluator_verdict: dict[str, Any] = field(default_factory=dict)
    validation_commands: list[str] = field(default_factory=list)
    checked_artifacts: list[str] = field(default_factory=list)
    unchecked_items: list[str] = field(default_factory=list)
    ready_for_evolution: bool = False
    source_code_modified_by_cambrian: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "recorded"
        return payload


def complete_job(project_root: Path, job_ref: str, outcome: str, notes: str | None = None) -> JobCompleteResult:
    root = Path(project_root).resolve()
    outcome_value = str(outcome or "").strip()
    if outcome_value not in ALLOWED_OUTCOMES:
        return JobCompleteResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            job_id=None,
            outcome=None,
            notes=notes,
            outcome_ref=None,
            evidence_ref=None,
            errors=[f"outcome must be one of: {', '.join(sorted(ALLOWED_OUTCOMES))}"],
        )
    try:
        job_path = resolve_pack_job_path(root, job_ref)
        job = PackJobStore().load(job_path)
    except (FileNotFoundError, ValueError) as exc:
        LOGGER.warning("job complete를 기록할 수 없습니다: %s", exc)
        return JobCompleteResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="blocked",
            job_id=None,
            outcome=outcome_value,
            notes=notes,
            outcome_ref=None,
            evidence_ref=None,
            errors=[str(exc)],
        )

    validation_evidence, validation_evidence_ref = _latest_validation_evidence(root, job)
    warnings: list[str] = []
    if not validation_evidence:
        warnings.append("No validation evidence was found for this job. Run `cambrian job validate latest` before completing when possible.")
    payload = _outcome_payload(root, job, job_path, outcome_value, notes, validation_evidence, validation_evidence_ref)
    outcome_path = _save_yaml(job_outcome_path(root, job.job_id), payload)
    evidence_path = _append_outcome(root, payload)
    return JobCompleteResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status="recorded",
        job_id=job.job_id,
        outcome=outcome_value,
        notes=notes,
        outcome_ref=_relative(outcome_path, root),
        evidence_ref=_relative(evidence_path, root),
        validation_evidence_ref=validation_evidence_ref,
        validation_contract_status=_text_or_none(validation_evidence.get("validation_contract_status")),
        trust_gate_status=_text_or_none(validation_evidence.get("trust_gate_status")),
        latest_verdict_ref=_text_or_none(validation_evidence.get("latest_verdict_ref")),
        evaluator_verdict=_dict_or_empty(validation_evidence.get("evaluator_verdict")),
        validation_commands=_string_list(validation_evidence.get("validation_commands") or payload.get("validation_commands")),
        checked_artifacts=_string_list(validation_evidence.get("checked_artifacts")),
        unchecked_items=_string_list(validation_evidence.get("unchecked_items")),
        ready_for_evolution=True,
        source_code_modified_by_cambrian=False,
        warnings=warnings,
        errors=[],
    )


def resolve_pack_job_path(project_root: Path, job_ref: str) -> Path:
    root = Path(project_root).resolve()
    ref = str(job_ref or "").strip()
    if not ref:
        raise FileNotFoundError("job ref is required")
    if ref == "latest":
        path = latest_pack_job_path(root)
        if path.exists():
            return path
        raise FileNotFoundError("latest job not found")
    candidate = Path(ref)
    if candidate.exists():
        return candidate.resolve()
    jobs_dir = default_pack_jobs_dir(root)
    candidates = [
        jobs_dir / f"{ref}.yaml",
        jobs_dir / f"{_slug(ref, 'job')}.yaml",
        jobs_dir / ref,
    ]
    for path in candidates:
        if path.exists():
            return path.resolve()
    raise FileNotFoundError(f"job not found: {job_ref}")


def load_outcomes(project_root: Path) -> list[dict[str, Any]]:
    path = default_outcomes_path(project_root)
    if not path.exists():
        return []
    payload = _load_yaml(path)
    outcomes = payload.get("outcomes", [])
    if not isinstance(outcomes, list):
        return []
    return [dict(item) for item in outcomes if isinstance(item, dict)]


def _outcome_payload(
    root: Path,
    job: PackJob,
    job_path: Path,
    outcome: str,
    notes: str | None,
    validation_evidence: dict[str, Any],
    validation_evidence_ref: str | None,
) -> dict[str, Any]:
    snapshot = job.outcome_snapshot if isinstance(job.outcome_snapshot, dict) else {}
    validation_commands = _string_list(validation_evidence.get("validation_commands") or snapshot.get("validation_commands"))
    if not validation_commands:
        validation_commands = _string_list(snapshot.get("test_commands") or snapshot.get("test_command"))
    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": _now(),
        "evidence_kind": "job_outcome",
        "job_id": job.job_id,
        "job_ref": _relative(job_path, root),
        "request": job.request,
        "outcome": outcome,
        "notes": str(notes or "").strip(),
        "validation_evidence_ref": validation_evidence_ref,
        "validation_contract_status": _text_or_none(validation_evidence.get("validation_contract_status")),
        "trust_gate_status": _text_or_none(validation_evidence.get("trust_gate_status")),
        "latest_verdict_ref": _text_or_none(validation_evidence.get("latest_verdict_ref")),
        "evaluator_verdict": _dict_or_empty(validation_evidence.get("evaluator_verdict")),
        "checked_artifacts": _string_list(validation_evidence.get("checked_artifacts")),
        "unchecked_items": _string_list(validation_evidence.get("unchecked_items")),
        "harness_id": snapshot.get("harness_id") or job.pack_id,
        "workforce_id": snapshot.get("workforce_id"),
        "selected_agents": list(snapshot.get("selected_agents", []) if isinstance(snapshot.get("selected_agents"), list) else []),
        "selected_skills": list(snapshot.get("selected_skills", []) if isinstance(snapshot.get("selected_skills"), list) else []),
        "validation_commands": validation_commands,
        "change_policy": snapshot.get("change_policy") or "proposal_only",
        "source_code_modified_by_cambrian": False,
        "patch_applied_by_cambrian": False,
        "ai_provider_called_by_cambrian": False,
        "ready_for_evolution": True,
    }


def _append_outcome(root: Path, outcome_payload: dict[str, Any]) -> Path:
    path = default_outcomes_path(root)
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


def _latest_validation_evidence(root: Path, job: PackJob) -> tuple[dict[str, Any], str | None]:
    evidence_dir = default_evidence_dir(root) / "validation"
    direct = evidence_dir / f"{_slug(job.job_id, 'job')}.yaml"
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
        except (OSError, ValueError, yaml.YAMLError) as exc:
            LOGGER.warning("검증 evidence 파일을 읽지 못해 건너뜁니다: %s (%s)", resolved, exc)
            continue
        if str(payload.get("job_id") or "") == job.job_id:
            return payload, _relative(resolved, root)
    return {}, None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
