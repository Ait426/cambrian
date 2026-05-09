"""pack proof card를 공개 가능한 증거 스냅샷으로 축약한다."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_proof import (
    PackProofBuilder,
    PackProofCard,
    PackProofStore,
    latest_pack_proof_card,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
PRIVACY_CLASSES = {"public_safe", "local_only", "blocked_sensitive"}
VERDICT_TO_STATUS = {
    "insufficient_data": "insufficient",
    "unproven": "unproven",
    "promising": "early_positive",
    "useful": "useful",
    "strong": "strong",
    "regressed": "regressed",
}
PUBLIC_METRIC_KEYS = {
    "used_count",
    "outcome_linked_count",
    "validated_proposal_rate",
    "adoption_rate",
    "regression_free_apply_rate",
    "human_intervention_rate",
    "validation_autonomy_rate",
    "median_time_to_validated_proposal",
    "outcome_coverage_rate",
}
BLOCKED_FIELD_NAMES = {
    "raw_request",
    "request_text",
    "source_code",
    "old_text",
    "new_text",
    "patch_text",
    "session_log",
    "private_note",
    "user_note",
}
REDACTED_FIELD_NAMES = {
    "source_refs",
    "source_ref",
    "evidence_refs",
    "session_refs",
    "linked_session_ref",
    "linked_proposal_ref",
    "linked_bridge_packet_ref",
    "local_absolute_paths",
    "proposal_text",
}
ABSOLUTE_PATH_RE = re.compile(r"([A-Za-z]:\\[^ \n\r\t]+|/(?:Users|home|tmp|var|private)/[^ \n\r\t]+)")


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓰는 UTC timestamp를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str | None) -> str:
    """파일명과 식별자에 안전한 slug를 만든다."""
    text = str(value or "unknown").strip().lower()
    chars: list[str] = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", ".", "/", "@"}:
            chars.append("-" if char in {"/", "@"} else char)
        else:
            chars.append("-")
    slug = "".join(chars).strip("-._")
    return slug or "unknown"


def _short_id(value: str | None = None) -> str:
    """짧은 안정 id 조각을 만든다."""
    seed = value or _now()
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 반환하고, 루트 밖은 파일명만 남긴다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def _atomic_write_text(path: Path, content: str) -> None:
    """텍스트 파일을 원자적으로 저장한다."""
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
    """YAML payload를 저장한다."""
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML 또는 JSON mapping을 안전하게 읽는다."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        payload = json.loads(text) if Path(path).suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("pack proof export load failed: %s (%s)", path, exc)
        return {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("pack proof export ignored: top level is not mapping: %s", path)
        return {}
    return payload


def _as_list(value: Any) -> list[str]:
    """값을 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _as_dict(value: Any) -> dict[str, Any]:
    """mapping 값만 dict로 반환한다."""
    return dict(value) if isinstance(value, dict) else {}


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def default_pack_proof_export_dir(project_root: Path) -> Path:
    """private local proof export 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "proof_exports"


def default_pack_proof_export_path(project_root: Path, snapshot: "PackProofExportSnapshot") -> Path:
    """기본 proof export YAML 경로."""
    return (
        default_pack_proof_export_dir(project_root)
        / f"export_{_slug(snapshot.pack_id)}_{_stamp()}_{_short_id(snapshot.export_id)}.yaml"
    )


def default_pack_proof_export_latest_path(project_root: Path) -> Path:
    """latest proof export pointer 경로."""
    return default_pack_proof_export_dir(project_root) / "latest.yaml"


@dataclass
class PackProofExportMetric:
    """공개 가능한 aggregate metric."""

    key: str
    value: float | int | str | None
    unit: str | None
    public_safe: bool
    summary: str
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return asdict(self)


@dataclass
class PackProofExportSnapshot:
    """웹 catalog에 넘길 수 있는 privacy-safe proof 스냅샷."""

    schema_version: str
    export_id: str
    generated_at: str
    pack_ref: str
    pack_id: str
    pack_name: str | None
    pack_kind: str | None
    namespace: str | None
    version: str | None
    source_proof_ref: str | None
    privacy_classification: str
    reputation_verdict: str
    proof_status: str
    maturity_hint: str | None
    sample_size: dict[str, Any]
    public_metrics: list[PackProofExportMetric]
    best_observed_lane: str | None
    best_observed_workset: str | None
    known_limits: list[str] = field(default_factory=list)
    safe_claims: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    redacted_fields: list[str] = field(default_factory=list)
    blocked_fields: list[str] = field(default_factory=list)
    web_summary: str = ""
    install_command: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None
    public_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        payload = asdict(self)
        payload["public_metrics"] = [metric.to_dict() for metric in self.public_metrics]
        return payload


class PackProofExporter:
    """local proof card를 공개 가능한 aggregate snapshot으로 투영한다."""

    def export(
        self,
        project_root: Path,
        pack_ref: str | None = None,
        source_proof_path: Path | None = None,
        out_path: Path | None = None,
    ) -> PackProofExportSnapshot:
        """proof card를 읽거나 생성해 privacy-safe export를 저장한다."""
        root = Path(project_root).resolve()
        card, proof_path, raw_payload = _resolve_source_proof(root, pack_ref, source_proof_path)
        blocked_fields = _blocked_fields(raw_payload)
        redacted_fields = _redacted_fields(raw_payload)
        metrics = _public_metrics(card)
        sample_size = {"used_count": card.used_count, "outcome_linked_count": card.outcome_linked_count}
        known_limits = _safe_strings(card.known_limits, redacted_fields)
        safe_claims = _safe_claims(card, redacted_fields)
        caveats = _caveats(card, sample_size)
        proof_status = VERDICT_TO_STATUS.get(card.reputation_verdict, "unproven")
        classification = "blocked_sensitive" if blocked_fields else "public_safe"
        warnings: list[str] = []
        errors: list[str] = []
        if classification == "blocked_sensitive":
            errors.append("proof card contains sensitive raw fields that cannot be exported publicly")
            caveats.append("Sensitive local evidence was detected. Public copy was not written.")
        if not known_limits:
            warnings.append("no public known limits were available in the local proof card")
        web_summary = _web_summary(card, proof_status, sample_size)
        source_ref = _relative(proof_path, root) if proof_path else None
        snapshot = PackProofExportSnapshot(
            schema_version=SCHEMA_VERSION,
            export_id=f"proof-export-{_slug(card.pack_id)}-{_stamp()}-{_short_id(card.proof_id)}",
            generated_at=_now(),
            pack_ref=card.pack_ref,
            pack_id=card.pack_id,
            pack_name=card.pack_name,
            pack_kind=card.pack_kind,
            namespace=card.namespace,
            version=card.version,
            source_proof_ref=source_ref,
            privacy_classification=classification,
            reputation_verdict=card.reputation_verdict,
            proof_status=proof_status,
            maturity_hint=card.maturity_hint,
            sample_size=sample_size,
            public_metrics=metrics,
            best_observed_lane=_safe_optional(card.best_observed_lane, redacted_fields),
            best_observed_workset=_safe_optional(card.best_observed_workset, redacted_fields),
            known_limits=known_limits,
            safe_claims=safe_claims,
            caveats=_dedupe(caveats),
            redacted_fields=_dedupe(redacted_fields),
            blocked_fields=_dedupe(blocked_fields),
            web_summary=web_summary,
            install_command=f"cambrian install pack {card.pack_id}",
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )
        store = PackProofExportStore()
        saved = store.save_yaml(snapshot, default_pack_proof_export_path(root, snapshot))
        snapshot.saved_ref = _relative(saved, root)
        store.save_yaml(snapshot, saved)
        _save_yaml(default_pack_proof_export_latest_path(root), snapshot.to_dict())
        if out_path is not None:
            if snapshot.privacy_classification == "blocked_sensitive":
                logger.warning("blocked public proof export copy for %s because sensitive fields were detected", card.pack_id)
            else:
                public_target = Path(out_path)
                if not public_target.is_absolute():
                    public_target = root / public_target
                public_path = store.save_yaml(snapshot, public_target.resolve())
                snapshot.public_ref = _relative(public_path, root)
                store.save_yaml(snapshot, saved)
                store.save_yaml(snapshot, public_path)
                _save_yaml(default_pack_proof_export_latest_path(root), snapshot.to_dict())
        return snapshot


class PackProofExportStore:
    """pack proof export 저장소."""

    def save_yaml(self, snapshot: PackProofExportSnapshot, path: Path) -> Path:
        """proof export snapshot을 YAML로 저장한다."""
        return _save_yaml(Path(path), snapshot.to_dict())

    def load_yaml(self, path: Path) -> PackProofExportSnapshot:
        """저장된 proof export snapshot을 읽는다."""
        payload = _load_yaml(path)
        return _snapshot_from_dict(payload, path)

    def list(self, exports_dir: Path) -> list[PackProofExportSnapshot]:
        """디렉터리의 proof export snapshot 목록을 읽는다."""
        root = Path(exports_dir)
        if not root.exists():
            return []
        snapshots: list[PackProofExportSnapshot] = []
        for path in sorted(root.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                snapshots.append(self.load_yaml(path))
            except Exception as exc:  # noqa: BLE001 - 깨진 export 파일은 목록 전체를 막지 않는다.
                logger.warning("pack proof export list ignored %s: %s", path, exc)
        return snapshots


def resolve_pack_proof_export_path(project_root: Path, export_ref: str) -> Path:
    """proof export id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(export_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(export_ref).strip().lower() == "latest":
        candidates.append(default_pack_proof_export_latest_path(root))
    exports_dir = default_pack_proof_export_dir(root)
    needle = _slug(str(export_ref))
    if exports_dir.exists():
        for path in sorted(exports_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"pack proof export not found: {export_ref}")


def latest_pack_proof_export(project_root: Path, pack_ref: str | None = None) -> PackProofExportSnapshot | None:
    """pack별 최신 public proof export를 반환한다."""
    root = Path(project_root).resolve()
    exports_dir = default_pack_proof_export_dir(root)
    snapshots = PackProofExportStore().list(exports_dir)
    public_dir = root / "packs" / "proof_exports"
    snapshots.extend(PackProofExportStore().list(public_dir))
    target = _plain_pack_id(pack_ref) if pack_ref else None
    for snapshot in snapshots:
        if target and snapshot.pack_id != target and _plain_pack_id(snapshot.pack_ref) != target:
            continue
        return snapshot
    return None


def render_pack_proof_export(snapshot: PackProofExportSnapshot) -> str:
    """proof export snapshot을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Proof Export",
        "==================================================",
        "",
        "Pack:",
        f"  {snapshot.pack_id}",
        "",
        "Classification:",
        f"  {snapshot.privacy_classification}",
        "",
        "Verdict:",
        f"  {snapshot.reputation_verdict}",
        "",
        "Proof status:",
        f"  {snapshot.proof_status}",
        "",
        "Sample size:",
        f"  used: {snapshot.sample_size.get('used_count', 0)}",
        f"  outcome-linked: {snapshot.sample_size.get('outcome_linked_count', 0)}",
        "",
        "Public metrics:",
    ]
    for metric in snapshot.public_metrics:
        value = "unknown" if metric.value is None else metric.value
        lines.append(f"  - {metric.key}: {value}")
    lines.extend(["", "Caveats:"])
    lines.extend([f"  - {item}" for item in snapshot.caveats] or ["  none"])
    lines.extend(["", "Redacted:"])
    lines.extend([f"  - {item}" for item in snapshot.redacted_fields] or ["  none"])
    if snapshot.blocked_fields:
        lines.extend(["", "Blocked fields:"])
        lines.extend([f"  - {item}" for item in snapshot.blocked_fields])
    if snapshot.saved_ref or snapshot.public_ref:
        lines.extend(["", "Saved:"])
        if snapshot.saved_ref:
            lines.append(f"  local: {snapshot.saved_ref}")
        if snapshot.public_ref:
            lines.append(f"  public: {snapshot.public_ref}")
    if snapshot.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in snapshot.warnings])
    if snapshot.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in snapshot.errors])
    return "\n".join(lines)


def render_pack_proof_export_compact(snapshot: PackProofExportSnapshot) -> str:
    """compact proof export 요약."""
    return (
        f"proof export: {snapshot.proof_status} / {snapshot.reputation_verdict} "
        f"({snapshot.sample_size.get('outcome_linked_count', 0)} linked uses)"
    )


def _resolve_source_proof(
    root: Path,
    pack_ref: str | None,
    source_proof_path: Path | None,
) -> tuple[PackProofCard, Path | None, dict[str, Any]]:
    """명시 proof, latest proof, in-memory proof 순서로 source card를 찾는다."""
    if source_proof_path is not None:
        proof_path = _resolve_ref(root, source_proof_path)
        raw_payload = _load_yaml(proof_path)
        return PackProofStore().load_yaml(proof_path), proof_path, raw_payload
    card = latest_pack_proof_card(root, pack_ref)
    if card is not None:
        latest_path = root / ".cambrian" / "packs" / "proof" / "latest.yaml"
        proof_path = latest_path if latest_path.exists() else None
        raw_payload = _load_yaml(proof_path) if proof_path else card.to_dict()
        return card, proof_path, raw_payload
    card = PackProofBuilder().build(root, pack_ref)
    return card, None, card.to_dict()


def _resolve_ref(root: Path, ref: Path) -> Path:
    """상대/절대 proof path를 해석한다."""
    path = Path(ref)
    if path.is_absolute():
        return path.resolve()
    return (root / path).resolve()


def _public_metrics(card: PackProofCard) -> list[PackProofExportMetric]:
    """proof card metric 중 aggregate public metric만 추린다."""
    values = {metric.key: metric for metric in card.key_metrics if metric.key in PUBLIC_METRIC_KEYS}
    metrics: list[PackProofExportMetric] = []
    for key in sorted(PUBLIC_METRIC_KEYS):
        if key == "used_count":
            metrics.append(
                PackProofExportMetric(
                    key=key,
                    value=card.used_count,
                    unit="count",
                    public_safe=True,
                    summary="aggregate pack usage count",
                )
            )
            continue
        if key == "outcome_linked_count":
            metrics.append(
                PackProofExportMetric(
                    key=key,
                    value=card.outcome_linked_count,
                    unit="count",
                    public_safe=True,
                    summary="aggregate outcome-linked use count",
                )
            )
            continue
        source = values.get(key)
        warning = None if source and source.value is not None else "metric unavailable; no percentage is claimed"
        metrics.append(
            PackProofExportMetric(
                key=key,
                value=source.value if source else None,
                unit=source.unit if source else None,
                public_safe=True,
                summary=source.summary if source else f"{key} aggregate metric",
                warning=warning,
            )
        )
    return metrics


def _safe_strings(values: list[str], redacted_fields: list[str]) -> list[str]:
    """공개 문자열에서 절대 경로와 세션성 흔적을 제거한다."""
    safe: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if ABSOLUTE_PATH_RE.search(text):
            redacted_fields.append("local_absolute_paths")
            continue
        lowered = text.lower()
        if any(term in lowered for term in ("raw request", "session log", "patch text", "old_text", "new_text")):
            redacted_fields.append("private_detail_text")
            continue
        safe.append(text)
    return _dedupe(safe)


def _safe_optional(value: str | None, redacted_fields: list[str]) -> str | None:
    """선택 문자열 하나를 공개 가능할 때만 반환한다."""
    safe = _safe_strings([value] if value else [], redacted_fields)
    return safe[0] if safe else None


def _safe_claims(card: PackProofCard, redacted_fields: list[str]) -> list[str]:
    """claim을 evidence ref 없이 공개 가능한 문장으로 축약한다."""
    claims: list[str] = []
    for claim in card.claims:
        text = f"{claim.title}: {claim.verdict}. {claim.summary}".strip()
        safe = _safe_strings([text], redacted_fields)
        if safe:
            claims.append(safe[0])
    return _dedupe(claims)


def _caveats(card: PackProofCard, sample_size: dict[str, Any]) -> list[str]:
    """공개 proof에 붙일 sample/privacy caveat를 만든다."""
    caveats = [
        "Local evidence only. Cambrian did not upload this proof automatically.",
        "Only aggregate metrics are exported; raw requests, sessions, source code, and patch text are omitted.",
    ]
    used = int(sample_size.get("used_count", 0) or 0)
    linked = int(sample_size.get("outcome_linked_count", 0) or 0)
    if used < 5 or linked < 5:
        caveats.append("Sample size is small. Treat this proof as early evidence.")
    if card.reputation_verdict in {"insufficient_data", "unproven"}:
        caveats.append("Proof is insufficient or unproven; no performance claim is made.")
    if card.reputation_verdict == "regressed":
        caveats.append("Recent local evidence suggests regression; inspect local proof before recommending.")
    return _dedupe(caveats)


def _web_summary(card: PackProofCard, proof_status: str, sample_size: dict[str, Any]) -> str:
    """웹 catalog에 넣을 짧은 공개 요약."""
    linked = int(sample_size.get("outcome_linked_count", 0) or 0)
    return (
        f"Local public proof export is {proof_status} for {card.pack_id} "
        f"with {linked} outcome-linked uses. Aggregate evidence only."
    )


def _blocked_fields(payload: dict[str, Any]) -> list[str]:
    """raw private field가 직접 포함되었는지 재귀적으로 탐지한다."""
    fields: list[str] = []
    _scan_payload(payload, fields, [])
    return _dedupe(fields)


def _redacted_fields(payload: dict[str, Any]) -> list[str]:
    """공개 export에서 의도적으로 제거한 field 종류를 찾는다."""
    redacted: list[str] = ["raw_requests", "session_refs", "source_refs", "local_absolute_paths", "patch_text"]
    _scan_redactions(payload, redacted)
    return _dedupe(redacted)


def _scan_payload(value: Any, fields: list[str], parents: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in BLOCKED_FIELD_NAMES:
                fields.append(key_text)
            _scan_payload(nested, fields, [*parents, key_text])
        return
    if isinstance(value, list):
        for nested in value:
            _scan_payload(nested, fields, parents)
        return
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in ("source_code:", "patch_text:", "session_log:", "raw_request:")):
            fields.append("embedded_sensitive_text")


def _scan_redactions(value: Any, redacted: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in REDACTED_FIELD_NAMES:
                redacted.append(key_text)
            _scan_redactions(nested, redacted)
        return
    if isinstance(value, list):
        for nested in value:
            _scan_redactions(nested, redacted)
        return
    if isinstance(value, str) and ABSOLUTE_PATH_RE.search(value):
        redacted.append("local_absolute_paths")


def _snapshot_from_dict(payload: dict[str, Any], path: Path | None = None) -> PackProofExportSnapshot:
    metrics = [
        PackProofExportMetric(
            key=str(item.get("key") or ""),
            value=item.get("value"),
            unit=str(item.get("unit")) if item.get("unit") is not None else None,
            public_safe=bool(item.get("public_safe", True)),
            summary=str(item.get("summary") or ""),
            warning=str(item.get("warning")) if item.get("warning") is not None else None,
        )
        for item in payload.get("public_metrics", [])
        if isinstance(item, dict)
    ]
    classification = str(payload.get("privacy_classification") or "local_only")
    if classification not in PRIVACY_CLASSES:
        classification = "local_only"
    return PackProofExportSnapshot(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        export_id=str(payload.get("export_id") or f"proof-export-{_stamp()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        pack_ref=str(payload.get("pack_ref") or payload.get("pack_id") or "unknown"),
        pack_id=str(payload.get("pack_id") or "unknown"),
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        pack_kind=str(payload.get("pack_kind")) if payload.get("pack_kind") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        source_proof_ref=str(payload.get("source_proof_ref")) if payload.get("source_proof_ref") is not None else None,
        privacy_classification=classification,
        reputation_verdict=str(payload.get("reputation_verdict") or "unproven"),
        proof_status=str(payload.get("proof_status") or "unproven"),
        maturity_hint=str(payload.get("maturity_hint")) if payload.get("maturity_hint") is not None else None,
        sample_size=_as_dict(payload.get("sample_size")),
        public_metrics=metrics,
        best_observed_lane=str(payload.get("best_observed_lane")) if payload.get("best_observed_lane") is not None else None,
        best_observed_workset=str(payload.get("best_observed_workset")) if payload.get("best_observed_workset") is not None else None,
        known_limits=_as_list(payload.get("known_limits")),
        safe_claims=_as_list(payload.get("safe_claims")),
        caveats=_as_list(payload.get("caveats")),
        redacted_fields=_as_list(payload.get("redacted_fields")),
        blocked_fields=_as_list(payload.get("blocked_fields")),
        web_summary=str(payload.get("web_summary") or ""),
        install_command=str(payload.get("install_command")) if payload.get("install_command") is not None else None,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else (_relative(path, Path.cwd()) if path else None),
        public_ref=str(payload.get("public_ref")) if payload.get("public_ref") is not None else None,
    )


def _plain_pack_id(pack_ref: str | None) -> str | None:
    if not pack_ref:
        return None
    text = str(pack_ref).split("@", 1)[0]
    return text.rsplit("/", 1)[-1]
