"""Bridge reply를 daily-use fast path로 안전하게 라우팅한다."""

from __future__ import annotations

import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_bridge import (
    ProjectBridgeReplyParser,
    ProjectBridgeStore,
    default_bridge_dir,
    default_bridge_reply_path,
    resolve_bridge_packet_path,
)
from engine.project_bridge_checklists import (
    BridgeChecklistBuilder,
    BridgeChecklistStore,
    default_bridge_checklist_path,
)
from engine.project_bridge_context import (
    BridgeContextHintBuilder,
    BridgeContextHintStore,
    default_bridge_context_hint_path,
)
from engine.project_bridge_handoff import (
    BridgeHandoffStore,
    BridgeReplyHandoff,
    BridgeReplyReviewStore,
    BridgeReplyReviewer,
    default_bridge_handoff_path,
    default_bridge_review_path,
)
from engine.project_bridge_materialize import (
    BridgeMaterializationStore,
    BridgeMaterializer,
    default_bridge_materialized_path,
)
from engine.project_bridge_resume import BridgeSessionCoordinator
from engine.project_do import DoSessionStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


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


def _quote(value: str) -> str:
    return '"' + str(value or "").replace('"', '\\"') + '"'


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


def default_bridge_fastpath_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "fastpath"


def default_bridge_fastpath_path(project_root: Path, record: "BridgeFastPathRecord") -> Path:
    return default_bridge_fastpath_dir(project_root) / f"{record.fastpath_id}.yaml"


@dataclass
class BridgeFastPathRecord:
    schema_version: str
    fastpath_id: str
    created_at: str
    packet_id: str | None
    packet_ref: str | None
    reply_id: str | None
    reply_ref: str | None
    response_kind: str | None
    review_ref: str | None
    handoff_ref: str | None
    materialization_ref: str | None
    context_hint_ref: str | None
    checklist_ref: str | None
    linked_session_id: str | None
    linked_session_ref: str | None
    patch_intent_ref: str | None
    status: str
    actions_taken: list[str] = field(default_factory=list)
    summary: str = ""
    next_command: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BridgeFastPathStore:
    def save(self, record: BridgeFastPathRecord, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), record.to_dict())

    def load(self, path: Path) -> BridgeFastPathRecord:
        return _record_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, directory: Path) -> list[BridgeFastPathRecord]:
        records: list[BridgeFastPathRecord] = []
        if not Path(directory).exists():
            return records
        for path in sorted(Path(directory).glob("fastpath_*.yaml"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True):
            try:
                records.append(self.load(path))
            except Exception as exc:
                logger.warning("bridge fast path record load failed: %s", exc)
        return records


class BridgeFastPathCoordinator:
    def run_text(
        self,
        project_root: Path,
        text: str,
        packet_ref: str | None = None,
        session_ref: str | None = None,
    ) -> BridgeFastPathRecord:
        return self._run(
            Path(project_root).resolve(),
            str(text or ""),
            packet_ref=packet_ref,
            session_ref=session_ref,
            source_reply_path=None,
        )

    def run_file(
        self,
        project_root: Path,
        file_path: Path,
        packet_ref: str | None = None,
        session_ref: str | None = None,
    ) -> BridgeFastPathRecord:
        root = Path(project_root).resolve()
        source_path = Path(file_path).expanduser()
        if not source_path.is_absolute():
            source_path = root / source_path
        text = source_path.read_text(encoding="utf-8")
        return self._run(
            root,
            text,
            packet_ref=packet_ref,
            session_ref=session_ref,
            source_reply_path=source_path.resolve(),
        )

    def _run(
        self,
        root: Path,
        text: str,
        *,
        packet_ref: str | None,
        session_ref: str | None,
        source_reply_path: Path | None,
    ) -> BridgeFastPathRecord:
        record = BridgeFastPathRecord(
            schema_version=SCHEMA_VERSION,
            fastpath_id=f"fastpath_{_timestamp()}_{_short_id()}",
            created_at=_now(),
            packet_id=None,
            packet_ref=None,
            reply_id=None,
            reply_ref=None,
            response_kind=None,
            review_ref=None,
            handoff_ref=None,
            materialization_ref=None,
            context_hint_ref=None,
            checklist_ref=None,
            linked_session_id=None,
            linked_session_ref=None,
            patch_intent_ref=None,
            status="blocked",
            actions_taken=[],
            summary="bridge fast path blocked before reply ingest",
            next_command=None,
            warnings=[],
            errors=[],
        )
        try:
            reply = ProjectBridgeReplyParser().parse_reply(text)
        except ValueError as exc:
            record.errors.append(str(exc))
            return _save_fastpath(root, record)

        store = ProjectBridgeStore()
        if packet_ref:
            try:
                packet_path = resolve_bridge_packet_path(root, packet_ref)
                packet = store.load_packet(packet_path)
                reply.packet_id = packet.packet_id
                reply.project_name = packet.project_name
                reply.request = packet.request
                reply.linked_request_ref = _relative(packet_path, root)
                record.packet_id = packet.packet_id
                record.packet_ref = _relative(packet_path, root)
            except FileNotFoundError as exc:
                record.errors.append(f"Bridge packet not found: {exc}")
                return _save_fastpath(root, record)
        if session_ref:
            reply.linked_session_id = str(session_ref)
        reply.source_reply_path = _relative(source_reply_path, root) if source_reply_path else "stdin"
        record.response_kind = reply.response_kind or None
        if reply.errors:
            record.errors.extend(reply.errors)
            record.warnings.extend(reply.warnings)
            record.summary = "bridge reply failed response contract validation"
            return _save_fastpath(root, record)

        reply_path = store.save_reply(reply, default_bridge_reply_path(root, reply))
        record.reply_id = reply.reply_id
        record.reply_ref = _relative(reply_path, root)
        record.actions_taken.append("reply_ingested")
        record.status = "ingested"

        if reply.response_kind == "patch_candidate":
            self._route_patch_candidate(root, reply_path, record, session_ref=session_ref)
        elif reply.response_kind in {"analysis", "plan", "review"}:
            self._route_non_patch(root, reply_path, record)
        else:
            record.status = "blocked"
            record.summary = "unknown bridge reply kind"
            record.errors.append(f"unsupported response_kind: {reply.response_kind or 'unknown'}")
        return _save_fastpath(root, record)

    def _route_patch_candidate(
        self,
        root: Path,
        reply_path: Path,
        record: BridgeFastPathRecord,
        *,
        session_ref: str | None,
    ) -> None:
        review = BridgeReplyReviewer().review(root, reply_path)
        review_path = BridgeReplyReviewStore().save(review, default_bridge_review_path(root, review))
        record.review_ref = _relative(review_path, root)
        record.actions_taken.append("reply_reviewed")
        if "patch_intent" not in review.handoff_options:
            record.status = "blocked"
            record.summary = "patch_candidate reply is not usable for no-retype handoff"
            record.errors.extend(review.errors or review.missing_fields)
            record.warnings.extend(review.warnings)
            return

        handoff = BridgeReplyHandoff().to_patch_intent(root, reply_path)
        handoff_path = BridgeHandoffStore().save(handoff, default_bridge_handoff_path(root, handoff))
        record.handoff_ref = _relative(handoff_path, root)
        record.actions_taken.append("patch_intent_handoff_created")
        record.patch_intent_ref = handoff.target_artifact_ref
        if handoff.status != "created":
            record.status = "blocked"
            record.summary = "patch intent handoff was blocked"
            record.errors.extend(handoff.errors)
            record.warnings.extend(handoff.warnings)
            return

        link = BridgeSessionCoordinator().ensure_linked_session(
            root,
            reply_path,
            handoff,
            patch_intent_ref=handoff.target_artifact_ref,
            explicit_session_ref=session_ref,
        )
        record.actions_taken.append("linked_session_created")
        record.linked_session_id = link.session_id
        record.linked_session_ref = link.session_ref
        record.next_command = link.next_commands[0] if link.next_commands else None
        record.status = "session_linked"
        record.summary = "patch candidate routed to no-retype patch intent and linked do session"
        _mark_fastpath_session_metrics(root, link.session_ref, record)

    def _route_non_patch(self, root: Path, reply_path: Path, record: BridgeFastPathRecord) -> None:
        materialized = BridgeMaterializer().materialize(root, reply_path)
        if materialized.errors:
            record.status = "blocked"
            record.summary = "non-patch bridge reply materialization was blocked"
            record.errors.extend(materialized.errors)
            record.warnings.extend(materialized.warnings)
            return
        materialized_path = BridgeMaterializationStore().save_record(
            materialized,
            default_bridge_materialized_path(root, materialized),
        )
        record.materialization_ref = _relative(materialized_path, root)
        record.actions_taken.append(f"{materialized.materialization_kind}_materialized")
        record.status = "materialized"

        if materialized.materialization_kind == "analysis_brief":
            if materialized.recommended_files or materialized.recommended_tests:
                hint = BridgeContextHintBuilder().from_materialization(root, materialized_path)
                hint_path = BridgeContextHintStore().save_hint(hint, default_bridge_context_hint_path(root, hint))
                record.context_hint_ref = _relative(hint_path, root)
                record.actions_taken.append("context_hint_created")
                record.next_command = f"cambrian context scan {_quote(materialized.summary or '<request>')}"
                record.summary = "analysis reply materialized and routed to bridge context hint"
            else:
                record.next_command = f"cambrian bridge materialize-show {materialized.materialization_id}"
                record.summary = "analysis reply materialized as analysis_brief"
        elif materialized.materialization_kind == "plan_record":
            checklist = BridgeChecklistBuilder().from_materialization(root, materialized_path)
            checklist_path = BridgeChecklistStore().save(checklist, default_bridge_checklist_path(root, checklist))
            record.checklist_ref = _relative(checklist_path, root)
            record.actions_taken.append("checklist_created")
            record.next_command = f"cambrian bridge checklist-show {checklist.checklist_id}"
            record.summary = "plan reply materialized and routed to bridge checklist"
        elif materialized.materialization_kind == "review_note":
            record.next_command = f"cambrian bridge materialize-show {materialized.materialization_id}"
            record.summary = "review reply materialized as review_note"
        record.status = "materialized"


def load_bridge_fastpath_summary(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    records = BridgeFastPathStore().list(default_bridge_fastpath_dir(root))
    latest = records[0] if records else None
    return {
        "fastpath_count": len(records),
        "latest_fastpath_id": latest.fastpath_id if latest else None,
        "latest_response_kind": latest.response_kind if latest else None,
        "latest_status": latest.status if latest else None,
        "latest_summary": latest.summary if latest else None,
        "latest_next_command": latest.next_command if latest else None,
        "latest_reply_id": latest.reply_id if latest else None,
    }


def load_bridge_fastpath_activity(project_root: Path, reply_id: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    records = BridgeFastPathStore().list(default_bridge_fastpath_dir(root))
    if reply_id:
        records = [
            item
            for item in records
            if item.reply_id == reply_id or (item.reply_ref and Path(item.reply_ref).stem == reply_id)
        ]
    latest = records[0] if records else None
    return {
        "latest_fastpath_id": latest.fastpath_id if latest else None,
        "latest_fastpath_status": latest.status if latest else None,
        "latest_fastpath_summary": latest.summary if latest else None,
        "latest_fastpath_next_command": latest.next_command if latest else None,
        "latest_fastpath_session_id": latest.linked_session_id if latest else None,
        "latest_fastpath_patch_intent_ref": latest.patch_intent_ref if latest else None,
        "latest_fastpath_materialization_ref": latest.materialization_ref if latest else None,
        "latest_fastpath_context_hint_ref": latest.context_hint_ref if latest else None,
        "latest_fastpath_checklist_ref": latest.checklist_ref if latest else None,
    }


def render_bridge_fastpath(record: BridgeFastPathRecord, saved_path: str | None = None) -> str:
    title = "Bridge fast path completed." if record.status not in {"blocked", "failed"} else "Bridge fast path blocked."
    lines = [
        title,
        "",
        "Kind:",
        f"  {record.response_kind or 'unknown'}",
        "",
        "Status:",
        f"  {record.status}",
        "",
        "Summary:",
        f"  {record.summary or 'none'}",
    ]
    if record.actions_taken:
        lines.extend(["", "Actions taken:"])
        lines.extend([f"  - {item}" for item in record.actions_taken])
    if record.linked_session_id:
        lines.extend(["", "Linked session:", f"  {record.linked_session_id}"])
    if record.patch_intent_ref:
        lines.extend(["", "Patch intent:", f"  {record.patch_intent_ref}"])
    if record.materialization_ref:
        lines.extend(["", "Materialization:", f"  {record.materialization_ref}"])
    if record.context_hint_ref:
        lines.extend(["", "Context hint:", f"  {record.context_hint_ref}"])
    if record.checklist_ref:
        lines.extend(["", "Checklist:", f"  {record.checklist_ref}"])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if saved_path:
        lines.extend(["", "Recorded:", f"  {saved_path}"])
    lines.extend(["", "Next:"])
    lines.append(f"  {record.next_command}" if record.next_command else "  inspect the saved fast path record")
    return "\n".join(lines)


def _save_fastpath(root: Path, record: BridgeFastPathRecord) -> BridgeFastPathRecord:
    saved_path = BridgeFastPathStore().save(record, default_bridge_fastpath_path(root, record))
    record.actions_taken = list(record.actions_taken)
    # 저장 경로는 renderer에서 계산하므로 record 자체에는 ref를 중복 저장하지 않는다.
    _ = saved_path
    return record


def _mark_fastpath_session_metrics(root: Path, session_ref: str | None, record: BridgeFastPathRecord) -> None:
    if not session_ref:
        return
    session_path = root / session_ref
    try:
        store = DoSessionStore()
        session = store.load(session_path)
    except Exception as exc:
        logger.warning("bridge fast path session metrics update failed: %s", exc)
        return
    metrics = session.metrics_context if isinstance(session.metrics_context, dict) else {}
    metrics["source_mode"] = "bridge_fastpath"
    reused = metrics.setdefault("reused_context", {})
    if isinstance(reused, dict):
        reused["bridge"] = True
    human = metrics.setdefault("human_interventions", {})
    if isinstance(human, dict):
        human["old_text_overridden"] = False
        human["new_text_overridden"] = False
        human["bridge_manual_ingest"] = False
        human["bridge_paste_fastpath"] = True
    metrics["bridge_fastpath"] = {
        "fastpath_id": record.fastpath_id,
        "reply_ref": record.reply_ref,
        "patch_intent_ref": record.patch_intent_ref,
        "no_retype": bool(record.patch_intent_ref and record.next_command),
    }
    session.metrics_context = metrics
    if isinstance(session.bridge_context, dict):
        session.bridge_context["source_mode"] = "bridge_fastpath"
        session.bridge_context["fastpath_id"] = record.fastpath_id
    store.save(root, session)


def _record_from_dict(payload: dict[str, Any]) -> BridgeFastPathRecord:
    return BridgeFastPathRecord(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        fastpath_id=str(payload.get("fastpath_id", "")),
        created_at=str(payload.get("created_at", "")),
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        packet_ref=str(payload.get("packet_ref")) if payload.get("packet_ref") is not None else None,
        reply_id=str(payload.get("reply_id")) if payload.get("reply_id") is not None else None,
        reply_ref=str(payload.get("reply_ref")) if payload.get("reply_ref") is not None else None,
        response_kind=str(payload.get("response_kind")) if payload.get("response_kind") is not None else None,
        review_ref=str(payload.get("review_ref")) if payload.get("review_ref") is not None else None,
        handoff_ref=str(payload.get("handoff_ref")) if payload.get("handoff_ref") is not None else None,
        materialization_ref=str(payload.get("materialization_ref")) if payload.get("materialization_ref") is not None else None,
        context_hint_ref=str(payload.get("context_hint_ref")) if payload.get("context_hint_ref") is not None else None,
        checklist_ref=str(payload.get("checklist_ref")) if payload.get("checklist_ref") is not None else None,
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_session_ref=str(payload.get("linked_session_ref")) if payload.get("linked_session_ref") is not None else None,
        patch_intent_ref=str(payload.get("patch_intent_ref")) if payload.get("patch_intent_ref") is not None else None,
        status=str(payload.get("status", "")),
        actions_taken=[str(item) for item in payload.get("actions_taken", []) if item],
        summary=str(payload.get("summary", "") or ""),
        next_command=str(payload.get("next_command")) if payload.get("next_command") is not None else None,
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
