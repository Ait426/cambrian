"""Ledger-aware selection pressure builder."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from engine.brain.evolution_ledger import EvolutionLedger


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


def _variant_records(node) -> list[dict]:
    return [
        variant
        for variant in (node.summary.get("competitive_variants") or [])
        if isinstance(variant, dict)
    ]


@dataclass
class SelectionPressure:
    schema_version: str
    pressure_id: str
    created_at: str
    source_ledger_path: str
    source_generation_ids: list[str]
    pressure_status: str
    keep_patterns: list[str] = field(default_factory=list)
    avoid_patterns: list[str] = field(default_factory=list)
    blocked_variant_ids: list[str] = field(default_factory=list)
    warned_variant_ids: list[str] = field(default_factory=list)
    recommended_variant_count: int | None = None
    hypothesis_warnings: list[str] = field(default_factory=list)
    missing_evidence_warnings: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SelectionPressure":
        return cls(
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            pressure_id=str(data.get("pressure_id", "")),
            created_at=str(data.get("created_at", "")),
            source_ledger_path=str(data.get("source_ledger_path", "")),
            source_generation_ids=list(data.get("source_generation_ids") or []),
            pressure_status=str(data.get("pressure_status", "empty")),
            keep_patterns=list(data.get("keep_patterns") or []),
            avoid_patterns=list(data.get("avoid_patterns") or []),
            blocked_variant_ids=list(data.get("blocked_variant_ids") or []),
            warned_variant_ids=list(data.get("warned_variant_ids") or []),
            recommended_variant_count=(
                int(data["recommended_variant_count"])
                if data.get("recommended_variant_count") is not None
                else None
            ),
            hypothesis_warnings=list(data.get("hypothesis_warnings") or []),
            missing_evidence_warnings=list(
                data.get("missing_evidence_warnings") or []
            ),
            risk_flags=list(data.get("risk_flags") or []),
            rationale=list(data.get("rationale") or []),
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
        )


class SelectionPressureBuilder:
    """Evolution ledger에서 selection pressure를 만든다."""

    def build(
        self,
        ledger: EvolutionLedger,
        options: dict | None = None,
    ) -> SelectionPressure:
        options = dict(options or {})
        source_generation_ids = [node.generation_id for node in ledger.nodes]
        source_ledger_path = str(options.get("source_ledger_path") or "")

        if not ledger.nodes:
            return SelectionPressure(
                schema_version=SCHEMA_VERSION,
                pressure_id="pressure-empty",
                created_at=_now(),
                source_ledger_path=source_ledger_path,
                source_generation_ids=[],
                pressure_status="empty",
            )

        keep_patterns: list[str] = []
        avoid_patterns: list[str] = []
        blocked_variant_candidates: set[str] = set()
        successful_variants: set[str] = set()
        warned_variant_ids: set[str] = set()
        hypothesis_warnings: list[str] = []
        missing_evidence_warnings: list[str] = []
        risk_flags: list[str] = []
        rationale: list[str] = []

        contradicted_hypothesis_counts: dict[str, int] = {}
        no_winner_count = 0
        rollback_seen = False

        for node in ledger.nodes:
            if node.outcome in {"adopted", "success"}:
                if node.winner_variant_id:
                    successful_variants.add(node.winner_variant_id)
                    keep_patterns.append(
                        f"Keep winner variant pattern: {node.winner_variant_id}"
                    )
                if node.hypothesis_status == "supported" and node.hypothesis_id:
                    keep_patterns.append(
                        f"Keep supported hypothesis: {node.hypothesis_id}"
                    )
                if node.selection_reason:
                    keep_patterns.append(
                        f"Keep selection reason: {node.selection_reason}"
                    )

            if node.outcome in {"failed", "no_winner", "rollback"}:
                if node.hypothesis_status == "contradicted" and node.hypothesis_id:
                    avoid_patterns.append(
                        f"Avoid contradicted hypothesis: {node.hypothesis_id}"
                    )
                    contradicted_hypothesis_counts[node.hypothesis_id] = (
                        contradicted_hypothesis_counts.get(node.hypothesis_id, 0) + 1
                    )
                if node.outcome == "no_winner":
                    no_winner_count += 1
                    avoid_patterns.append(
                        f"Avoid no_winner generation pattern from {node.generation_id}"
                    )
                if node.outcome == "rollback":
                    rollback_seen = True
                for variant in _variant_records(node):
                    variant_id = str(variant.get("variant_id") or "").strip()
                    if not variant_id:
                        continue
                    if (
                        variant.get("hypothesis_status") == "contradicted"
                        or variant.get("status") == "failure"
                    ):
                        blocked_variant_candidates.add(variant_id)
                        avoid_patterns.append(
                            f"Avoid previously failed variant: {variant_id}"
                        )

            if node.outcome in {"mixed", "inconclusive"}:
                for variant in _variant_records(node):
                    variant_id = str(variant.get("variant_id") or "").strip()
                    if variant_id:
                        warned_variant_ids.add(variant_id)
                if node.hypothesis_status == "inconclusive" and node.hypothesis_id:
                    hypothesis_warnings.append(
                        f"Hypothesis remained inconclusive: {node.hypothesis_id}"
                    )

            for warning in node.warnings:
                if "missing evidence" in warning or "parent source not found" in warning:
                    missing_evidence_warnings.append(warning)

        blocked_variant_ids = sorted(
            variant_id
            for variant_id in blocked_variant_candidates
            if variant_id not in successful_variants
        )
        warned_variant_ids = sorted(
            variant_id
            for variant_id in warned_variant_ids
            if variant_id not in blocked_variant_ids
        )

        for hypothesis_id, count in contradicted_hypothesis_counts.items():
            if count >= 2:
                hypothesis_warnings.append(
                    f"Hypothesis contradicted repeatedly: {hypothesis_id} ({count})"
                )

        if no_winner_count >= 2:
            risk_flags.append("repeated_no_winner")
        if hypothesis_warnings:
            risk_flags.append("repeated_contradicted_hypothesis")
        if rollback_seen:
            risk_flags.append("rollback_recently_observed")
        if len(_unique(missing_evidence_warnings)) >= 2:
            risk_flags.append("missing_evidence_repeated")
        if not any(node.outcome == "adopted" for node in ledger.nodes):
            risk_flags.append("no_adopted_generation")

        recommended_variant_count: int | None
        if no_winner_count > 0:
            recommended_variant_count = 3
            rationale.append("최근 no_winner가 있어 variant 수를 3으로 권장한다")
        elif any(node.outcome in {"adopted", "success"} for node in ledger.nodes):
            recommended_variant_count = 2
            rationale.append("안정적인 success/adopted가 있어 variant 수를 2로 권장한다")
        else:
            recommended_variant_count = None

        if blocked_variant_ids:
            rationale.append(
                "실패 또는 모순으로 반복 등장한 variant를 winner 후보에서 제외한다"
            )
        if warned_variant_ids:
            rationale.append("mixed/inconclusive generation의 variant는 경고만 남긴다")

        pressure_status = (
            "active"
            if any(
                [
                    keep_patterns,
                    avoid_patterns,
                    blocked_variant_ids,
                    warned_variant_ids,
                    hypothesis_warnings,
                    missing_evidence_warnings,
                    risk_flags,
                ]
            )
            else "empty"
        )

        return SelectionPressure(
            schema_version=SCHEMA_VERSION,
            pressure_id=f"pressure-{len(source_generation_ids)}",
            created_at=_now(),
            source_ledger_path=source_ledger_path,
            source_generation_ids=source_generation_ids,
            pressure_status=pressure_status,
            keep_patterns=_unique(keep_patterns),
            avoid_patterns=_unique(avoid_patterns),
            blocked_variant_ids=blocked_variant_ids,
            warned_variant_ids=warned_variant_ids,
            recommended_variant_count=recommended_variant_count,
            hypothesis_warnings=_unique(hypothesis_warnings),
            missing_evidence_warnings=_unique(missing_evidence_warnings),
            risk_flags=_unique(risk_flags),
            rationale=_unique(rationale),
            warnings=list(ledger.warnings),
            errors=list(ledger.errors),
        )


class SelectionPressureStore:
    """selection pressure YAML 저장/로드."""

    def save(self, pressure: SelectionPressure, out_path: Path) -> Path:
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
                pressure.to_dict(),
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
            temp_path = Path(handle.name)
        temp_path.replace(out_path)
        return out_path

    def load(self, path: Path) -> SelectionPressure:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("selection pressure YAML 최상위는 dict여야 한다")
        return SelectionPressure.from_dict(dict(payload))
