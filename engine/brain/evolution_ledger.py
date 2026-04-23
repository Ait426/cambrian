"""Multi-generation evolution ledger builder."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml


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


def _coerce_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return _unique([str(item) for item in value])
    return _unique([str(value)])


def _resolve_ref(project_root: Path, ref: str | None) -> Path | None:
    if not ref:
        return None
    path = Path(ref)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def _display_path(project_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve(strict=False).relative_to(
            project_root.resolve(strict=False)
        ).as_posix()
    except ValueError:
        return str(path.resolve(strict=False))


def _load_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 최상위는 dict여야 한다: {path}")
    return payload


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML 최상위는 dict여야 한다: {path}")
    return dict(payload)


@dataclass
class GenerationNode:
    generation_id: str
    brain_run_id: str | None
    created_at: str | None
    source_report_path: str | None
    source_run_state_path: str | None
    source_task_spec_path: str | None
    parent_generation_ids: list[str] = field(default_factory=list)
    child_generation_ids: list[str] = field(default_factory=list)
    source_feedback_refs: list[str] = field(default_factory=list)
    source_seed_refs: list[str] = field(default_factory=list)
    adoption_refs: list[str] = field(default_factory=list)
    feedback_refs: list[str] = field(default_factory=list)
    next_seed_refs: list[str] = field(default_factory=list)
    task_id: str | None = None
    goal: str | None = None
    status: str | None = None
    hypothesis_status: str | None = None
    hypothesis_id: str | None = None
    competitive_status: str | None = None
    winner_variant_id: str | None = None
    selection_reason: str | None = None
    adoption_status: str | None = None
    outcome: str = "inconclusive"
    summary: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationNode":
        return cls(
            generation_id=str(data.get("generation_id", "")),
            brain_run_id=(
                str(data["brain_run_id"])
                if data.get("brain_run_id") is not None
                else None
            ),
            created_at=(
                str(data["created_at"])
                if data.get("created_at") is not None
                else None
            ),
            source_report_path=(
                str(data["source_report_path"])
                if data.get("source_report_path") is not None
                else None
            ),
            source_run_state_path=(
                str(data["source_run_state_path"])
                if data.get("source_run_state_path") is not None
                else None
            ),
            source_task_spec_path=(
                str(data["source_task_spec_path"])
                if data.get("source_task_spec_path") is not None
                else None
            ),
            parent_generation_ids=list(data.get("parent_generation_ids") or []),
            child_generation_ids=list(data.get("child_generation_ids") or []),
            source_feedback_refs=list(data.get("source_feedback_refs") or []),
            source_seed_refs=list(data.get("source_seed_refs") or []),
            adoption_refs=list(data.get("adoption_refs") or []),
            feedback_refs=list(data.get("feedback_refs") or []),
            next_seed_refs=list(data.get("next_seed_refs") or []),
            task_id=str(data["task_id"]) if data.get("task_id") is not None else None,
            goal=str(data["goal"]) if data.get("goal") is not None else None,
            status=(
                str(data["status"]) if data.get("status") is not None else None
            ),
            hypothesis_status=(
                str(data["hypothesis_status"])
                if data.get("hypothesis_status") is not None
                else None
            ),
            hypothesis_id=(
                str(data["hypothesis_id"])
                if data.get("hypothesis_id") is not None
                else None
            ),
            competitive_status=(
                str(data["competitive_status"])
                if data.get("competitive_status") is not None
                else None
            ),
            winner_variant_id=(
                str(data["winner_variant_id"])
                if data.get("winner_variant_id") is not None
                else None
            ),
            selection_reason=(
                str(data["selection_reason"])
                if data.get("selection_reason") is not None
                else None
            ),
            adoption_status=(
                str(data["adoption_status"])
                if data.get("adoption_status") is not None
                else None
            ),
            outcome=str(data.get("outcome", "inconclusive")),
            summary=dict(data.get("summary") or {}),
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
        )


@dataclass
class EvolutionLedger:
    schema_version: str
    generated_at: str
    source_counts: dict
    latest_generation_id: str | None
    nodes: list[GenerationNode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "source_counts": dict(self.source_counts),
            "latest_generation_id": self.latest_generation_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvolutionLedger":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(data.get("generated_at", "")),
            source_counts=dict(data.get("source_counts") or {}),
            latest_generation_id=(
                str(data["latest_generation_id"])
                if data.get("latest_generation_id") is not None
                else None
            ),
            nodes=[
                GenerationNode.from_dict(node)
                for node in (data.get("nodes") or [])
            ],
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
        )


class EvolutionLedgerBuilder:
    """file-first artifacts에서 multi-generation ledger를 재구성한다."""

    def build(
        self,
        brain_runs_dir: Path,
        adoptions_dir: Path,
        feedback_dir: Path,
        next_generation_dir: Path,
        project_root: Path,
    ) -> EvolutionLedger:
        project_root = project_root.resolve(strict=False)
        warnings: list[str] = []
        errors: list[str] = []
        nodes_by_generation: dict[str, GenerationNode] = {}
        adoption_records: dict[str, dict] = {}
        adoption_by_id: dict[str, dict] = {}
        feedback_records: dict[str, dict] = {}
        seeds_by_path: dict[str, dict] = {}

        brain_report_count = 0
        adoption_count = 0
        feedback_count = 0
        seed_count = 0

        if brain_runs_dir.exists():
            for run_dir in sorted(entry for entry in brain_runs_dir.iterdir() if entry.is_dir()):
                report_path = run_dir / "report.json"
                run_state_path = run_dir / "run_state.json"
                task_spec_path = run_dir / "task_spec.yaml"
                if not report_path.exists():
                    continue
                brain_report_count += 1
                try:
                    report = _load_json(report_path)
                except Exception as exc:
                    warnings.append(f"malformed brain report: {report_path}")
                    errors.append(str(exc))
                    continue

                run_state: dict = {}
                if run_state_path.exists():
                    try:
                        run_state = _load_json(run_state_path)
                    except Exception as exc:
                        warnings.append(f"malformed run_state: {run_state_path}")
                        errors.append(str(exc))

                task_spec: dict = {}
                if task_spec_path.exists():
                    try:
                        task_spec = _load_yaml(task_spec_path)
                    except Exception as exc:
                        warnings.append(f"malformed task_spec: {task_spec_path}")
                        errors.append(str(exc))

                brain_run_id = (
                    str(report.get("run_id") or "")
                    or str(run_state.get("run_id") or "")
                    or run_dir.name
                )
                generation_id = f"gen-{brain_run_id}"
                hypothesis = dict(report.get("hypothesis_evaluation") or {})
                competitive = dict(report.get("competitive_generation") or {})
                feedback_context = dict(report.get("feedback_context") or {})
                task_seed = dict(task_spec.get("generation_seed") or {})
                source_seed_refs = _unique(
                    _coerce_list(feedback_context.get("source_seed_path"))
                    + _coerce_list(task_seed.get("source_seed_path"))
                )
                source_feedback_refs = _unique(
                    _coerce_list(feedback_context.get("source_feedback_refs"))
                    + _coerce_list(task_spec.get("feedback_refs"))
                    + _coerce_list(task_seed.get("source_feedback_ref"))
                )

                node = GenerationNode(
                    generation_id=generation_id,
                    brain_run_id=brain_run_id,
                    created_at=str(
                        report.get("finished_at")
                        or report.get("started_at")
                        or run_state.get("finished_at")
                        or run_state.get("started_at")
                        or ""
                    )
                    or None,
                    source_report_path=_display_path(project_root, report_path),
                    source_run_state_path=(
                        _display_path(project_root, run_state_path)
                        if run_state_path.exists()
                        else None
                    ),
                    source_task_spec_path=(
                        _display_path(project_root, task_spec_path)
                        if task_spec_path.exists()
                        else None
                    ),
                    source_feedback_refs=source_feedback_refs,
                    source_seed_refs=source_seed_refs,
                    task_id=(
                        str(report.get("task_id") or task_spec.get("task_id") or "")
                        or None
                    ),
                    goal=str(task_spec.get("goal") or "") or None,
                    status=str(report.get("status") or run_state.get("status") or "")
                    or None,
                    hypothesis_status=(
                        str(hypothesis.get("status") or "") or None
                    ),
                    hypothesis_id=(
                        str(hypothesis.get("hypothesis_id") or "") or None
                    ),
                    competitive_status=(
                        str(competitive.get("status") or "") or None
                    ),
                    winner_variant_id=(
                        str(competitive.get("winner_variant_id") or "") or None
                    ),
                    selection_reason=(
                        str(competitive.get("selection_reason") or "") or None
                    ),
                    summary={
                        "termination_reason": report.get("termination_reason"),
                        "test_results": dict(report.get("test_results") or {}),
                        "remaining_risks": list(report.get("remaining_risks") or []),
                        "next_actions": list(report.get("next_actions") or []),
                        "competitive_variants": list(
                            competitive.get("variants") or []
                        ),
                    },
                )
                nodes_by_generation[generation_id] = node

        if adoptions_dir.exists():
            for adoption_path in sorted(adoptions_dir.glob("adoption_*.json")):
                adoption_count += 1
                try:
                    record = _load_json(adoption_path)
                except Exception as exc:
                    warnings.append(f"malformed adoption record: {adoption_path}")
                    errors.append(str(exc))
                    continue
                record["_path"] = _display_path(project_root, adoption_path)
                adoption_records[record["_path"]] = record
                adoption_id = str(record.get("adoption_id") or "")
                if adoption_id:
                    adoption_by_id[adoption_id] = record

                brain_run_id = str(record.get("brain_run_id") or "")
                if not brain_run_id:
                    continue
                generation_id = f"gen-{brain_run_id}"
                node = nodes_by_generation.get(generation_id)
                if node is None:
                    node = GenerationNode(
                        generation_id=generation_id,
                        brain_run_id=brain_run_id,
                        created_at=str(record.get("created_at") or "") or None,
                        source_report_path=None,
                        source_run_state_path=None,
                        source_task_spec_path=(
                            str(record.get("source_task_spec_path") or "") or None
                        ),
                    )
                    nodes_by_generation[generation_id] = node
                node.adoption_refs = _unique(node.adoption_refs + [record["_path"]])
                if str(record.get("adoption_status") or ""):
                    node.adoption_status = str(record.get("adoption_status"))
                if not node.winner_variant_id and record.get("winner_variant_id"):
                    node.winner_variant_id = str(record.get("winner_variant_id"))

        if feedback_dir.exists():
            for feedback_path in sorted(feedback_dir.glob("feedback_*.json")):
                feedback_count += 1
                try:
                    record = _load_json(feedback_path)
                except Exception as exc:
                    warnings.append(f"malformed feedback record: {feedback_path}")
                    errors.append(str(exc))
                    continue
                record["_path"] = _display_path(project_root, feedback_path)
                feedback_records[str(_resolve_ref(project_root, record["_path"]))] = record

                target_generation_id: str | None = None
                if record.get("brain_run_id"):
                    target_generation_id = f"gen-{record['brain_run_id']}"
                elif record.get("adoption_id"):
                    adoption = adoption_by_id.get(str(record["adoption_id"]))
                    if adoption and adoption.get("brain_run_id"):
                        target_generation_id = f"gen-{adoption['brain_run_id']}"

                if target_generation_id and target_generation_id in nodes_by_generation:
                    node = nodes_by_generation[target_generation_id]
                    node.feedback_refs = _unique(node.feedback_refs + [record["_path"]])

        if next_generation_dir.exists():
            for seed_path in sorted(next_generation_dir.glob("next_generation_*.yaml")):
                seed_count += 1
                try:
                    seed = _load_yaml(seed_path)
                except Exception as exc:
                    warnings.append(f"malformed next generation seed: {seed_path}")
                    errors.append(str(exc))
                    continue
                seed["_path"] = _display_path(project_root, seed_path)
                seeds_by_path[str(_resolve_ref(project_root, seed["_path"]))] = seed

                source_feedback_ref = str(seed.get("source_feedback_ref") or "")
                if not source_feedback_ref:
                    continue
                feedback = feedback_records.get(
                    str(_resolve_ref(project_root, source_feedback_ref))
                )
                if feedback is None:
                    continue
                parent_generation_id = self._resolve_feedback_parent_generation_id(
                    feedback,
                    adoption_by_id,
                )
                if parent_generation_id and parent_generation_id in nodes_by_generation:
                    parent = nodes_by_generation[parent_generation_id]
                    parent.next_seed_refs = _unique(parent.next_seed_refs + [seed["_path"]])

        for node in nodes_by_generation.values():
            parents: list[str] = []
            seed_refs = list(node.source_seed_refs)
            feedback_refs = list(node.source_feedback_refs)

            for seed_ref in seed_refs:
                seed = seeds_by_path.get(str(_resolve_ref(project_root, seed_ref)))
                if seed is None:
                    node.warnings.append("parent source not found: seed")
                    continue
                source_feedback_ref = str(seed.get("source_feedback_ref") or "")
                if not source_feedback_ref:
                    node.warnings.append("parent source not found: feedback")
                    continue
                feedback = feedback_records.get(
                    str(_resolve_ref(project_root, source_feedback_ref))
                )
                if feedback is None:
                    node.warnings.append("parent source not found: feedback")
                    continue
                parent_generation_id = self._resolve_feedback_parent_generation_id(
                    feedback,
                    adoption_by_id,
                )
                if parent_generation_id and parent_generation_id in nodes_by_generation:
                    parents.append(parent_generation_id)
                else:
                    node.warnings.append("parent source not found: generation")

            for feedback_ref in feedback_refs:
                feedback = feedback_records.get(
                    str(_resolve_ref(project_root, feedback_ref))
                )
                if feedback is None:
                    continue
                parent_generation_id = self._resolve_feedback_parent_generation_id(
                    feedback,
                    adoption_by_id,
                )
                if parent_generation_id and parent_generation_id in nodes_by_generation:
                    parents.append(parent_generation_id)

            node.parent_generation_ids = sorted(
                parent_id
                for parent_id in set(parents)
                if parent_id != node.generation_id
            )

        for node in nodes_by_generation.values():
            for parent_id in node.parent_generation_ids:
                parent = nodes_by_generation.get(parent_id)
                if parent is None:
                    continue
                parent.child_generation_ids = _unique(
                    parent.child_generation_ids + [node.generation_id]
                )

        for node in nodes_by_generation.values():
            node.warnings = _unique(node.warnings)
            node.errors = _unique(node.errors)
            node.outcome = self._classify_outcome(
                node,
                feedback_records,
                adoption_records,
                project_root,
            )

        latest_generation_id = self._resolve_latest_generation_id(
            adoptions_dir,
            nodes_by_generation,
        )
        nodes = sorted(
            nodes_by_generation.values(),
            key=lambda item: (item.created_at or "", item.generation_id),
        )
        return EvolutionLedger(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            source_counts={
                "brain_reports": brain_report_count,
                "adoptions": adoption_count,
                "feedback": feedback_count,
                "next_generation_seeds": seed_count,
                "nodes": len(nodes),
            },
            latest_generation_id=latest_generation_id,
            nodes=nodes,
            warnings=_unique(warnings),
            errors=_unique(errors),
        )

    @staticmethod
    def _resolve_feedback_parent_generation_id(
        feedback: dict,
        adoption_by_id: dict[str, dict],
    ) -> str | None:
        if feedback.get("brain_run_id"):
            return f"gen-{feedback['brain_run_id']}"
        if feedback.get("adoption_id"):
            adoption = adoption_by_id.get(str(feedback["adoption_id"]))
            if adoption and adoption.get("brain_run_id"):
                return f"gen-{adoption['brain_run_id']}"
        return None

    @staticmethod
    def _classify_outcome(
        node: GenerationNode,
        feedback_records: dict[str, dict],
        adoption_records: dict[str, dict],
        project_root: Path,
    ) -> str:
        adopted = False
        for adoption_ref in node.adoption_refs:
            record = adoption_records.get(_display_path(project_root, _resolve_ref(project_root, adoption_ref)))
            if record and str(record.get("adoption_status") or "") == "adopted":
                adopted = True
                break
        if adopted:
            return "adopted"
        if node.competitive_status == "no_winner":
            return "no_winner"
        if (
            node.status == "failed"
            or node.hypothesis_status == "contradicted"
            or node.competitive_status == "failure"
        ):
            return "failed"
        if (
            node.status == "completed"
            and node.competitive_status == "success"
            and node.winner_variant_id
        ):
            return "success"

        feedback_outcomes: list[str] = []
        for feedback_ref in node.feedback_refs:
            feedback = feedback_records.get(
                str(_resolve_ref(project_root, feedback_ref))
            )
            if feedback is not None:
                feedback_outcomes.append(str(feedback.get("outcome") or ""))

        remaining_risks = list(node.summary.get("remaining_risks") or [])
        if (
            node.status == "completed"
            and (
                node.hypothesis_status == "inconclusive"
                or remaining_risks
                or "mixed" in feedback_outcomes
            )
        ):
            return "mixed"
        return "inconclusive"

    @staticmethod
    def _resolve_latest_generation_id(
        adoptions_dir: Path,
        nodes_by_generation: dict[str, GenerationNode],
    ) -> str | None:
        latest_path = adoptions_dir / "_latest.json"
        if latest_path.exists():
            try:
                latest = _load_json(latest_path)
            except Exception:
                latest = {}
            brain_run_id = str(latest.get("brain_run_id") or "")
            if brain_run_id:
                generation_id = f"gen-{brain_run_id}"
                if generation_id in nodes_by_generation:
                    return generation_id

        if not nodes_by_generation:
            return None
        latest_node = max(
            nodes_by_generation.values(),
            key=lambda item: (item.created_at or "", item.generation_id),
        )
        return latest_node.generation_id


class EvolutionLedgerStore:
    """ledger 파일 저장/로드."""

    def save(self, ledger: EvolutionLedger, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            "w",
            delete=False,
            encoding="utf-8",
            dir=str(out_path.parent),
            prefix=f".{out_path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(ledger.to_dict(), handle, indent=2, ensure_ascii=False)
            temp_path = Path(handle.name)
        temp_path.replace(out_path)
        return out_path

    def load(self, path: Path) -> EvolutionLedger:
        return EvolutionLedger.from_dict(_load_json(path))
