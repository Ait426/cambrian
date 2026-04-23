"""Pressure-aware hypothesis refinement."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from engine.brain.feedback_context import FeedbackContextLoader
from engine.brain.models import TaskSpec
from engine.brain.selection_pressure import SelectionPressureStore


SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _slug(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in text)
    collapsed = "-".join(part for part in cleaned.split("-") if part)
    return collapsed or "source"


@dataclass
class RefinedHypothesis:
    schema_version: str
    refinement_id: str
    created_at: str
    status: str
    source_seed_path: str | None = None
    source_pressure_path: str | None = None
    source_task_spec_path: str | None = None
    source_feedback_refs: list[str] = field(default_factory=list)
    base_hypothesis: dict | None = None
    refined_hypothesis: dict | None = None
    applied_lessons: dict = field(default_factory=dict)
    applied_pressure: dict = field(default_factory=dict)
    required_evidence: list[str] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RefinedHypothesis":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            refinement_id=str(data.get("refinement_id", "")),
            created_at=str(data.get("created_at", "")),
            status=str(data.get("status", "needs_review")),
            source_seed_path=(
                str(data["source_seed_path"])
                if data.get("source_seed_path") is not None
                else None
            ),
            source_pressure_path=(
                str(data["source_pressure_path"])
                if data.get("source_pressure_path") is not None
                else None
            ),
            source_task_spec_path=(
                str(data["source_task_spec_path"])
                if data.get("source_task_spec_path") is not None
                else None
            ),
            source_feedback_refs=list(data.get("source_feedback_refs") or []),
            base_hypothesis=dict(data.get("base_hypothesis") or {})
            if data.get("base_hypothesis") is not None
            else None,
            refined_hypothesis=dict(data.get("refined_hypothesis") or {})
            if data.get("refined_hypothesis") is not None
            else None,
            applied_lessons=dict(data.get("applied_lessons") or {}),
            applied_pressure=dict(data.get("applied_pressure") or {}),
            required_evidence=list(data.get("required_evidence") or []),
            constraints=dict(data.get("constraints") or {}),
            rationale=list(data.get("rationale") or []),
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
        )


class HypothesisRefiner:
    """seed + pressure + task를 읽어 refined hypothesis 초안을 만든다."""

    def refine(
        self,
        seed_path: Path | None,
        pressure_path: Path | None,
        task_spec_path: Path | None,
        project_root: Path,
    ) -> RefinedHypothesis:
        warnings: list[str] = []
        errors: list[str] = []
        rationale: list[str] = []

        seed_payload: dict = {}
        pressure_payload: dict = {}
        task_spec: TaskSpec | None = None

        if seed_path is not None:
            try:
                seed_payload = FeedbackContextLoader().load_seed_file(seed_path)
            except Exception as exc:
                errors.append(f"seed load failed: {exc}")
        if pressure_path is not None:
            try:
                pressure_payload = SelectionPressureStore().load(pressure_path).to_dict()
            except Exception as exc:
                errors.append(f"pressure load failed: {exc}")
        if task_spec_path is not None:
            try:
                task_spec = TaskSpec.from_yaml(task_spec_path)
            except Exception as exc:
                errors.append(f"task spec load failed: {exc}")

        base_source: str | None = None
        base_hypothesis: dict | None = None
        if task_spec and isinstance(task_spec.hypothesis, dict):
            base_hypothesis = dict(task_spec.hypothesis)
            base_source = "task_spec"
            rationale.append("Base hypothesis loaded from task spec")
        elif isinstance(seed_payload.get("hypothesis_seed"), dict):
            base_hypothesis = dict(seed_payload["hypothesis_seed"])
            base_source = "generation_seed"
            rationale.append("Base hypothesis loaded from generation seed")

        source_feedback_refs = _unique(
            [str(seed_payload.get("source_feedback_ref") or "")]
        )
        applied_lessons = {
            "keep": list(((seed_payload.get("lessons") or {}).get("keep") or [])),
            "avoid": list(((seed_payload.get("lessons") or {}).get("avoid") or [])),
            "missing_evidence": list(
                ((seed_payload.get("lessons") or {}).get("missing_evidence") or [])
            ),
            "suggested_next_actions": list(
                seed_payload.get("suggested_next_actions") or []
            ),
        }

        constraints = {
            "blocked_variant_ids": list(pressure_payload.get("blocked_variant_ids") or []),
            "warned_variant_ids": list(pressure_payload.get("warned_variant_ids") or []),
            "recommended_variant_count": pressure_payload.get("recommended_variant_count"),
            "risk_flags": list(pressure_payload.get("risk_flags") or []),
        }
        applied_pressure = {
            "blocked_variant_ids": list(constraints["blocked_variant_ids"]),
            "warned_variant_ids": list(constraints["warned_variant_ids"]),
            "risk_flags": list(constraints["risk_flags"]),
            "hypothesis_warnings": list(
                pressure_payload.get("hypothesis_warnings") or []
            ),
            "missing_evidence_warnings": list(
                pressure_payload.get("missing_evidence_warnings") or []
            ),
        }

        required_evidence = _unique(
            list(applied_lessons["missing_evidence"])
            + list(applied_pressure["missing_evidence_warnings"])
            + list(applied_pressure["hypothesis_warnings"])
            + [
                action
                for action in applied_lessons["suggested_next_actions"]
                if any(
                    keyword in str(action).lower()
                    for keyword in ("evidence", "test", "pytest", "bridge")
                )
            ]
        )

        refined_hypothesis: dict | None = None
        if base_hypothesis is not None:
            predicts = dict(base_hypothesis.get("predicts") or {})
            tests_predict = dict(predicts.get("tests") or {})
            related_tests = list(task_spec.related_tests) if task_spec else []
            if related_tests:
                if "passed_min" not in tests_predict:
                    tests_predict["passed_min"] = 1
                    rationale.append(
                        "Added passed_min=1 because related_tests are present"
                    )
                if "failed_max" not in tests_predict:
                    tests_predict["failed_max"] = 0
                    rationale.append(
                        "Added failed_max=0 because related_tests are present"
                    )
            if tests_predict:
                predicts["tests"] = tests_predict
            refined_hypothesis = {
                "source": "refinement",
                "statement": str(base_hypothesis.get("statement") or ""),
                "predicts": predicts,
            }
            if base_hypothesis.get("id") is not None:
                refined_hypothesis["id"] = str(base_hypothesis.get("id"))
            else:
                refined_hypothesis["id"] = "seed-hypothesis"
        elif seed_path or pressure_path or task_spec_path:
            rationale.append(
                "No base hypothesis found; provide TaskSpec.hypothesis or seed.hypothesis_seed"
            )

        if constraints["blocked_variant_ids"]:
            rationale.append("Applied blocked_variant_ids from selection pressure")
        if constraints["risk_flags"]:
            rationale.append("Applied risk_flags from selection pressure")

        if errors:
            status = "error"
        elif refined_hypothesis is not None:
            status = "ready"
        elif seed_path or pressure_path or task_spec_path:
            status = "needs_review"
        else:
            status = "inconclusive"

        base_payload = None
        if base_hypothesis is not None:
            base_payload = dict(base_hypothesis)
            base_payload["source"] = base_source

        return RefinedHypothesis(
            schema_version=SCHEMA_VERSION,
            refinement_id=f"href-{_slug((base_source or 'source'))}",
            created_at=_now(),
            status=status,
            source_seed_path=(
                str(seed_path.resolve())
                if seed_path is not None
                else None
            ),
            source_pressure_path=(
                str(pressure_path.resolve())
                if pressure_path is not None
                else None
            ),
            source_task_spec_path=(
                str(task_spec_path.resolve())
                if task_spec_path is not None
                else None
            ),
            source_feedback_refs=source_feedback_refs,
            base_hypothesis=base_payload,
            refined_hypothesis=refined_hypothesis,
            applied_lessons=applied_lessons,
            applied_pressure=applied_pressure,
            required_evidence=required_evidence,
            constraints=constraints,
            rationale=_unique(rationale),
            warnings=_unique(warnings),
            errors=_unique(errors),
        )


class HypothesisRefinementStore:
    """refined hypothesis YAML 저장/로드."""

    def default_path(self, refinement: RefinedHypothesis, out_dir: Path) -> Path:
        source_hint = _slug(
            refinement.base_hypothesis.get("id", "source")
            if isinstance(refinement.base_hypothesis, dict)
            else "source"
        )
        return out_dir / f"refined_hypothesis_{source_hint}.yaml"

    def save(self, refinement: RefinedHypothesis, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            delete=False,
            encoding="utf-8",
            dir=str(out_path.parent),
            prefix=f".{out_path.name}.",
            suffix=".tmp",
        ) as handle:
            yaml.safe_dump(
                refinement.to_dict(),
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
            temp_path = Path(handle.name)
        temp_path.replace(out_path)
        return out_path

    def load(self, path: Path) -> RefinedHypothesis:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("refined hypothesis YAML 최상위는 dict여야 한다")
        return RefinedHypothesis.from_dict(dict(payload))
