"""Bridge reply/handoff를 do session으로 이어 주는 링크 저장소."""

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
from engine.project_bridge_handoff import BridgeHandoffRecord
from engine.project_do import DoSession, DoSessionStore
from engine.project_metrics import build_session_metrics_context

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id() -> str:
    return secrets.token_hex(2)


def _session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"do-{stamp}-{secrets.token_hex(2)}"


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
    if not Path(path).exists():
        return {}
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


def default_bridge_links_path(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "links.yaml"


@dataclass
class BridgeLinkRecord:
    schema_version: str
    link_id: str
    created_at: str
    packet_id: str | None
    packet_ref: str | None
    reply_id: str | None
    reply_ref: str | None
    review_id: str | None
    review_ref: str | None
    handoff_id: str | None
    handoff_ref: str | None
    handoff_kind: str | None
    session_id: str | None
    session_ref: str | None
    patch_intent_ref: str | None
    status: str
    next_commands: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BridgeResumeHint:
    reply_id: str | None
    handoff_id: str | None
    session_id: str | None
    session_ref: str | None
    current_stage: str | None
    patch_intent_ref: str | None
    next_command: str | None
    summary: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BridgeLinkStore:
    def load(self, path: Path) -> list[BridgeLinkRecord]:
        payload = _load_yaml(Path(path).resolve())
        records = payload.get("records", []) if isinstance(payload, dict) else []
        return [_link_from_dict(item) for item in records if isinstance(item, dict)]

    def save(self, path: Path, records: list[BridgeLinkRecord]) -> Path:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": _now(),
            "records": [record.to_dict() for record in records],
        }
        return _save_yaml(Path(path).resolve(), payload)

    def add(self, path: Path, record: BridgeLinkRecord) -> Path:
        records = self.load(path)
        records.insert(0, record)
        return self.save(path, records)


class BridgeSessionCoordinator:
    def ensure_linked_session(
        self,
        project_root: Path,
        reply_path: Path,
        handoff_record: BridgeHandoffRecord,
        *,
        patch_intent_ref: str | None = None,
        explicit_session_ref: str | None = None,
    ) -> BridgeLinkRecord:
        root = Path(project_root).resolve()
        reply = ProjectBridgeStore().load_reply(Path(reply_path).resolve())
        session_path, session = self._session_for_handoff(root, reply, handoff_record, patch_intent_ref, explicit_session_ref)
        session_ref = _relative(session_path, root)
        link = BridgeLinkRecord(
            schema_version=SCHEMA_VERSION,
            link_id=f"bridge-link-{_short_id()}",
            created_at=_now(),
            packet_id=handoff_record.packet_id,
            packet_ref=handoff_record.packet_ref,
            reply_id=handoff_record.reply_id,
            reply_ref=handoff_record.reply_ref,
            review_id=None,
            review_ref=None,
            handoff_id=handoff_record.handoff_id,
            handoff_ref=None,
            handoff_kind=handoff_record.handoff_kind,
            session_id=session.session_id,
            session_ref=session_ref,
            patch_intent_ref=patch_intent_ref,
            status="session_linked",
            next_commands=[f"cambrian continue --session {session.session_id} --validate"],
            warnings=[],
            errors=[],
        )
        BridgeLinkStore().add(default_bridge_links_path(root), link)
        return link

    def build_resume_hint(self, project_root: Path, reply_or_handoff_path: Path) -> BridgeResumeHint:
        root = Path(project_root).resolve()
        target = Path(reply_or_handoff_path).resolve()
        records = BridgeLinkStore().load(default_bridge_links_path(root))
        target_ref = _relative(target, root)
        stem = target.stem
        matching = [
            record
            for record in records
            if record.reply_ref == target_ref
            or record.handoff_ref == target_ref
            or record.reply_id == stem
            or record.handoff_id == stem
        ]
        if not matching:
            return BridgeResumeHint(
                reply_id=None,
                handoff_id=None,
                session_id=None,
                session_ref=None,
                current_stage=None,
                patch_intent_ref=None,
                next_command=None,
                summary="No bridge-linked do session found.",
                warnings=["bridge link not found"],
            )
        record = matching[0]
        stage = None
        if record.session_ref:
            try:
                session = DoSessionStore().load((root / record.session_ref).resolve())
                stage = session.current_stage
            except Exception as exc:
                logger.warning("bridge resume session load failed: %s", exc)
        next_command = record.next_commands[0] if record.next_commands else None
        return BridgeResumeHint(
            reply_id=record.reply_id,
            handoff_id=record.handoff_id,
            session_id=record.session_id,
            session_ref=record.session_ref,
            current_stage=stage,
            patch_intent_ref=record.patch_intent_ref,
            next_command=next_command,
            summary="Bridge reply can resume through the linked do session.",
            warnings=[],
        )

    def _session_for_handoff(
        self,
        root: Path,
        reply: Any,
        handoff_record: BridgeHandoffRecord,
        patch_intent_ref: str | None,
        explicit_session_ref: str | None,
    ) -> tuple[Path, DoSession]:
        store = DoSessionStore()
        if explicit_session_ref:
            session_path = store.resolve_path(root, explicit_session_ref)
            session = store.load(session_path)
        elif reply.linked_session_id:
            try:
                session_path = store.resolve_path(root, reply.linked_session_id)
                session = store.load(session_path)
            except Exception:
                session_path, session = self._new_bridge_session(root, reply)
        else:
            session_path, session = self._new_bridge_session(root, reply)

        session.project_initialized = (root / ".cambrian" / "project.yaml").exists()
        session.status = "patch_intent_draft"
        session.current_stage = "patch_intent_draft"
        if patch_intent_ref:
            session.artifacts["patch_intent_path"] = patch_intent_ref
        session.summary["bridge_reply_kind"] = reply.response_kind
        session.summary["bridge_handoff_status"] = handoff_record.status
        session.bridge_context = {
            "enabled": True,
            "packet_ref": handoff_record.packet_ref,
            "reply_ref": handoff_record.reply_ref,
            "handoff_ref": handoff_record.handoff_id,
            "source_mode": "bridge",
        }
        session.metrics_context = build_session_metrics_context(
            session_created_at=session.created_at or _now(),
            existing=session.metrics_context if isinstance(session.metrics_context, dict) else {},
        )
        session.metrics_context["source_mode"] = "bridge"
        human = session.metrics_context.setdefault("human_interventions", {})
        if isinstance(human, dict):
            human["bridge_manual_ingest"] = True
        session.next_actions = [f"cambrian continue --session {session.session_id} --validate"]
        session.next_commands = []
        saved_path = store.save(root, session)
        return saved_path, session

    def _new_bridge_session(self, root: Path, reply: Any) -> tuple[Path, DoSession]:
        session = DoSession(
            schema_version="1.0.0",
            session_id=_session_id(),
            created_at=_now(),
            updated_at=None,
            user_request=reply.request or str(reply.content.get("summary", "") or "bridge reply handoff"),
            project_initialized=(root / ".cambrian" / "project.yaml").exists(),
            intent=None,
            selected_skills=[],
            status="patch_intent_draft",
            current_stage="patch_intent_draft",
            artifacts={
                "session_path": None,
                "request_path": None,
                "context_scan_path": None,
                "clarification_path": None,
                "task_spec_path": None,
                "brain_run_id": None,
                "report_path": None,
                "patch_intent_path": None,
                "patch_proposal_path": None,
                "adoption_record_path": None,
            },
            summary={
                "understood_as": "bridge patch candidate",
                "found_sources": [],
                "found_tests": [],
                "selected_sources": [],
                "selected_tests": [],
                "needs": [],
            },
            next_actions=[],
            next_commands=[],
            harness_context={},
            agent_context={},
            harness_policy_context={},
            team_context={},
            team_policy_context={},
            template_context={},
            bridge_context={},
            continuations=[],
        )
        path = DoSessionStore().save(root, session)
        return path, session


def resolve_bridge_resume_target(project_root: Path, ref: str) -> Path:
    root = Path(project_root).resolve()
    try:
        return resolve_bridge_reply_path(root, ref)
    except FileNotFoundError:
        candidate = Path(ref)
        if candidate.exists():
            return candidate.resolve()
        rel = root / candidate
        if rel.exists():
            return rel.resolve()
        raise


def render_bridge_resume_hint(hint: BridgeResumeHint) -> str:
    lines = [
        "Bridge Resume",
        "==================================================",
        "",
        "Reply:",
        f"  {hint.reply_id or 'unknown'}",
    ]
    if hint.session_id:
        lines.extend(["", "Linked session:", f"  {hint.session_id}"])
    if hint.current_stage:
        lines.extend(["", "Current stage:", f"  {hint.current_stage}"])
    lines.extend(["", "Next:"])
    if hint.next_command:
        lines.append(f"  {hint.next_command}")
        if hint.next_command.startswith("cambrian continue --session "):
            legacy_command = hint.next_command.replace(
                "cambrian continue --session ",
                "cambrian do --continue --session ",
                1,
            )
            lines.append(f"  legacy: {legacy_command}")
    else:
        lines.append("  no resumable bridge patch flow found")
    if hint.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in hint.warnings])
    return "\n".join(lines)


def _link_from_dict(payload: dict[str, Any]) -> BridgeLinkRecord:
    return BridgeLinkRecord(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        link_id=str(payload.get("link_id", "")),
        created_at=str(payload.get("created_at", "")),
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        packet_ref=str(payload.get("packet_ref")) if payload.get("packet_ref") is not None else None,
        reply_id=str(payload.get("reply_id")) if payload.get("reply_id") is not None else None,
        reply_ref=str(payload.get("reply_ref")) if payload.get("reply_ref") is not None else None,
        review_id=str(payload.get("review_id")) if payload.get("review_id") is not None else None,
        review_ref=str(payload.get("review_ref")) if payload.get("review_ref") is not None else None,
        handoff_id=str(payload.get("handoff_id")) if payload.get("handoff_id") is not None else None,
        handoff_ref=str(payload.get("handoff_ref")) if payload.get("handoff_ref") is not None else None,
        handoff_kind=str(payload.get("handoff_kind")) if payload.get("handoff_kind") is not None else None,
        session_id=str(payload.get("session_id")) if payload.get("session_id") is not None else None,
        session_ref=str(payload.get("session_ref")) if payload.get("session_ref") is not None else None,
        patch_intent_ref=str(payload.get("patch_intent_ref")) if payload.get("patch_intent_ref") is not None else None,
        status=str(payload.get("status", "")),
        next_commands=[str(item) for item in payload.get("next_commands", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
