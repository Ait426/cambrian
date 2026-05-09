"""Bridge non-patch reply를 안전한 로컬 운영 artifact로 변환한다."""

from __future__ import annotations

import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_bridge import ProjectBridgeStore, default_bridge_dir, resolve_bridge_reply_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
MATERIALIZATION_BY_REPLY_KIND = {
    "analysis": "analysis_brief",
    "review": "review_note",
    "plan": "plan_record",
}
ALLOWED_MATERIALIZATION_KINDS = {"analysis_brief", "review_note", "plan_record"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    return secrets.token_hex(2)


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
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()] or [text]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def default_bridge_materialized_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "materialized"


def default_bridge_materialized_path(project_root: Path, record: "BridgeMaterializedRecord") -> Path:
    return default_bridge_materialized_dir(project_root) / f"{record.materialization_id}.yaml"


@dataclass
class BridgeMaterializedRecord:
    schema_version: str
    materialization_id: str
    created_at: str
    reply_id: str | None
    reply_ref: str
    packet_id: str | None
    packet_ref: str | None
    response_kind: str | None
    materialization_kind: str
    title: str
    summary: str
    recommended_files: list[str] = field(default_factory=list)
    recommended_tests: list[str] = field(default_factory=list)
    target_paths: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    raw_fields_present: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BridgeMaterializer:
    """AI reply를 실행 없이 읽기용 운영 artifact로 변환한다."""

    def materialize(
        self,
        project_root: Path,
        reply_path: Path,
        as_kind: str | None = None,
    ) -> BridgeMaterializedRecord:
        root = Path(project_root).resolve()
        path = Path(reply_path).resolve()
        reply = ProjectBridgeStore().load_reply(path)
        content = dict(reply.content or {})
        response_kind = str(reply.response_kind or content.get("response_kind") or "").strip()
        materialization_kind = str(as_kind or MATERIALIZATION_BY_REPLY_KIND.get(response_kind, "")).strip()
        warnings = list(reply.warnings)
        errors = list(reply.errors)
        if response_kind == "patch_candidate":
            materialization_kind = "none"
            errors.append("patch_candidate reply는 bridge handoff --as patch_intent 경로를 사용해야 합니다")
        elif materialization_kind not in ALLOWED_MATERIALIZATION_KINDS:
            errors.append(f"unsupported materialization kind: {materialization_kind or response_kind or 'unknown'}")
        elif response_kind == "review" and not str(content.get("summary", "") or "").strip():
            errors.append("review reply materialization requires summary")

        summary = str(content.get("summary", "") or "").strip()
        title = str(content.get("title", "") or summary or f"{response_kind or 'bridge'} materialization").strip()
        fields_present = sorted([key for key, value in content.items() if value not in (None, "", [], {})])
        record = BridgeMaterializedRecord(
            schema_version=SCHEMA_VERSION,
            materialization_id=f"materialized_{_timestamp()}_{_short_id()}",
            created_at=_now(),
            reply_id=reply.reply_id,
            reply_ref=_relative(path, root),
            packet_id=reply.packet_id,
            packet_ref=reply.linked_request_ref,
            response_kind=response_kind or None,
            materialization_kind=materialization_kind,
            title=title[:120],
            summary=summary,
            recommended_files=_dedupe(_as_list(content.get("recommended_files"))),
            recommended_tests=_dedupe(_as_list(content.get("recommended_tests"))),
            target_paths=_dedupe(_as_list(content.get("target_paths")) or _as_list(content.get("target_path"))),
            steps=_dedupe(_as_list(content.get("steps"))),
            positives=_dedupe(_as_list(content.get("positives"))),
            cautions=_dedupe([*_as_list(content.get("cautions")), *_as_list(content.get("warnings"))]),
            next_actions=_next_actions_for_kind(materialization_kind, reply.reply_id),
            raw_fields_present=fields_present,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )
        if not record.summary and not record.errors:
            record.errors.append("summary is required for materialization")
        return record


class BridgeMaterializationStore:
    def save_record(self, record: BridgeMaterializedRecord, path: Path) -> Path:
        if record.errors:
            raise ValueError("; ".join(record.errors))
        return _save_yaml(Path(path).resolve(), record.to_dict())

    def load_record(self, path: Path) -> BridgeMaterializedRecord:
        return _record_from_dict(_load_yaml(Path(path).resolve()))

    def list_records(self, materialized_dir: Path) -> list[BridgeMaterializedRecord]:
        records: list[BridgeMaterializedRecord] = []
        for path in _sorted_yaml_files(Path(materialized_dir), "materialized_*.yaml"):
            try:
                records.append(self.load_record(path))
            except Exception as exc:
                logger.warning("bridge materialization load failed: %s", exc)
        return records


def resolve_bridge_materialization_path(project_root: Path, materialization_ref: str) -> Path:
    root = Path(project_root).resolve()
    ref = str(materialization_ref or "").strip()
    candidate = Path(ref)
    if candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        rel_candidate = root / candidate
        if rel_candidate.exists():
            return rel_candidate.resolve()
    directory = default_bridge_materialized_dir(root)
    if directory.exists():
        for path in directory.glob("materialized_*.yaml"):
            payload = _safe_load_yaml(path)
            if (
                str(payload.get("materialization_id", "")) == ref
                or path.stem == ref
                or path.name == ref
            ):
                return path.resolve()
    raise FileNotFoundError(f"bridge materialization not found: {materialization_ref}")


def render_bridge_materialized(record: BridgeMaterializedRecord, saved_path: str | None = None) -> str:
    if record.errors:
        lines = ["Bridge materialization blocked.", "", "Errors:"]
        lines.extend([f"  - {error}" for error in record.errors])
        if record.response_kind == "patch_candidate":
            lines.extend(["", "Use:", f"  cambrian bridge handoff {record.reply_id or record.reply_ref} --as patch_intent"])
        return "\n".join(lines)
    lines = [
        "Bridge Materialization",
        "==================================================",
        "",
        "Reply kind:",
        f"  {record.response_kind or 'unknown'}",
        "",
        "Created:",
        f"  {record.materialization_kind}",
        "",
        "Summary:",
        f"  {record.summary or record.title}",
    ]
    if record.recommended_files:
        lines.extend(["", "Recommended files:"])
        lines.extend([f"  - {item}" for item in record.recommended_files[:5]])
    if record.recommended_tests:
        lines.extend(["", "Recommended tests:"])
        lines.extend([f"  - {item}" for item in record.recommended_tests[:5]])
    if record.steps:
        lines.extend(["", "Steps:"])
        lines.extend([f"  {idx}. {step}" for idx, step in enumerate(record.steps[:8], start=1)])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    lines.extend(["", "Next:"])
    lines.extend([f"  {action}" for action in record.next_actions[:3]])
    return "\n".join(lines)


def render_bridge_materialization_show(record: BridgeMaterializedRecord, activity: dict[str, Any] | None = None) -> str:
    lines = [
        "Bridge Materialized Record",
        "==================================================",
        "",
        "Materialization:",
        f"  {record.materialization_id}",
        "",
        "Kind:",
        f"  {record.materialization_kind}",
        "",
        "Summary:",
        f"  {record.summary or record.title}",
    ]
    if record.steps:
        lines.extend(["", "Steps:"])
        lines.extend([f"  {idx}. {step}" for idx, step in enumerate(record.steps, start=1)])
    if record.cautions:
        lines.extend(["", "Cautions:"])
        lines.extend([f"  - {item}" for item in record.cautions[:5]])
    if activity and activity.get("latest_context_hint_id"):
        lines.extend(["", "Context hint:", f"  {activity.get('latest_context_hint_id')}"])
    if activity and activity.get("latest_checklist_id"):
        lines.extend(["", "Checklist:", f"  {activity.get('latest_checklist_status') or 'open'}"])
        if activity.get("latest_checklist_next_step"):
            lines.append(f"  next step: {activity.get('latest_checklist_next_step')}")
    return "\n".join(lines)


def render_bridge_materializations(records: list[BridgeMaterializedRecord], *, kind: str | None = None, limit: int = 10) -> str:
    filtered = [record for record in records if kind is None or record.materialization_kind == kind]
    lines = ["Bridge Materializations", "==================================================", "", "Recent:"]
    if not filtered:
        lines.append("  none")
        return "\n".join(lines)
    for index, record in enumerate(filtered[: max(1, limit)], start=1):
        lines.append(f"  {index}. [{record.materialization_kind}] {record.summary or record.title}")
    return "\n".join(lines)


def load_bridge_materialization_activity(project_root: Path, reply_id: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    records = BridgeMaterializationStore().list_records(default_bridge_materialized_dir(root))
    if reply_id:
        records = [record for record in records if record.reply_id == reply_id or Path(record.reply_ref).stem == reply_id]
    latest = records[0] if records else None
    return {
        "materialization_count": len(records),
        "latest_materialization_id": latest.materialization_id if latest else None,
        "latest_materialization_kind": latest.materialization_kind if latest else None,
        "latest_materialization_summary": latest.summary if latest else None,
    }


def load_bridge_materialization_summary(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    records = BridgeMaterializationStore().list_records(default_bridge_materialized_dir(root))
    latest = records[0] if records else None
    return {
        "materialization_count": len(records),
        "latest_materialization_id": latest.materialization_id if latest else None,
        "latest_materialization_kind": latest.materialization_kind if latest else None,
        "latest_materialization_summary": latest.summary if latest else None,
    }


def _next_actions_for_kind(materialization_kind: str, reply_id: str | None) -> list[str]:
    if materialization_kind == "analysis_brief":
        return [
            "cambrian bridge handoff <materialization> --as context_hint",
            "cambrian context scan \"<request>\"",
        ]
    if materialization_kind == "plan_record":
        return [
            "cambrian bridge handoff <materialization> --as checklist",
            "cambrian bridge checklists",
        ]
    if materialization_kind == "review_note":
        return ["review this AI-derived note before changing workflow"]
    if materialization_kind == "none":
        return [f"cambrian bridge handoff {reply_id or '<reply>'} --as patch_intent"]
    return [f"cambrian bridge reply-show {reply_id}" if reply_id else "cambrian bridge reply-show <reply>"]


def _record_from_dict(payload: dict[str, Any]) -> BridgeMaterializedRecord:
    return BridgeMaterializedRecord(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        materialization_id=str(payload.get("materialization_id", "")),
        created_at=str(payload.get("created_at", "")),
        reply_id=str(payload.get("reply_id")) if payload.get("reply_id") is not None else None,
        reply_ref=str(payload.get("reply_ref", "")),
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        packet_ref=str(payload.get("packet_ref")) if payload.get("packet_ref") is not None else None,
        response_kind=str(payload.get("response_kind")) if payload.get("response_kind") is not None else None,
        materialization_kind=str(payload.get("materialization_kind", "")),
        title=str(payload.get("title", "")),
        summary=str(payload.get("summary", "") or ""),
        recommended_files=[str(item) for item in payload.get("recommended_files", []) if item],
        recommended_tests=[str(item) for item in payload.get("recommended_tests", []) if item],
        target_paths=[str(item) for item in payload.get("target_paths", []) if item],
        steps=[str(item) for item in payload.get("steps", []) if item],
        positives=[str(item) for item in payload.get("positives", []) if item],
        cautions=[str(item) for item in payload.get("cautions", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        raw_fields_present=[str(item) for item in payload.get("raw_fields_present", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    try:
        return _load_yaml(path)
    except Exception as exc:
        logger.warning("bridge materialization lookup load failed: %s", exc)
        return {}


def _sorted_yaml_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
