"""Bridge reply review와 safe patch intent handoff."""

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
    ALLOWED_RESPONSE_KINDS,
    BridgeReply,
    ProjectBridgeStore,
    default_bridge_dir,
    resolve_bridge_packet_path,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
PATCH_CANDIDATE_REQUIRED_FIELDS = ["summary", "target_path", "old_text", "new_text", "reason"]


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
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
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
    return [text] if text else []


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


def default_bridge_reviews_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "reviews"


def default_bridge_handoffs_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "handoffs"


def default_bridge_review_path(project_root: Path, review: "BridgeReplyReview") -> Path:
    return default_bridge_reviews_dir(project_root) / f"{review.review_id}.yaml"


def default_bridge_handoff_path(project_root: Path, record: "BridgeHandoffRecord") -> Path:
    return default_bridge_handoffs_dir(project_root) / f"{record.handoff_id}.yaml"


@dataclass
class BridgeReplyReview:
    schema_version: str
    review_id: str
    created_at: str
    reply_id: str | None
    reply_ref: str
    packet_id: str | None
    packet_ref: str | None
    response_kind: str | None
    usable: bool
    handoff_options: list[str]
    required_fields_present: list[str]
    missing_fields: list[str]
    summary: str
    reasons: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BridgeHandoffRecord:
    schema_version: str
    handoff_id: str
    created_at: str
    reply_id: str | None
    reply_ref: str
    packet_id: str | None
    packet_ref: str | None
    handoff_kind: str
    target_artifact_ref: str | None
    status: str
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BridgeReplyReviewStore:
    def save(self, review: BridgeReplyReview, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), review.to_dict())

    def load(self, path: Path) -> BridgeReplyReview:
        return _review_from_dict(_load_yaml(Path(path).resolve()))


class BridgeHandoffStore:
    def save(self, record: BridgeHandoffRecord, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), record.to_dict())

    def load(self, path: Path) -> BridgeHandoffRecord:
        return _handoff_from_dict(_load_yaml(Path(path).resolve()))


class BridgeReplyReviewer:
    def review(self, project_root: Path, reply_path: Path) -> BridgeReplyReview:
        root = Path(project_root).resolve()
        path = Path(reply_path).resolve()
        reply = ProjectBridgeStore().load_reply(path)
        reply_ref = _relative(path, root)
        packet_ref = _packet_ref_for_reply(root, reply)
        response_kind = str(reply.response_kind or "").strip()
        present, missing = _field_presence(reply, response_kind)
        reasons: list[str] = []
        warnings = list(reply.warnings)
        errors = list(reply.errors)
        handoff_options: list[str] = []
        usable = False

        if response_kind not in ALLOWED_RESPONSE_KINDS:
            errors.append("response_kind is unknown")
        elif response_kind == "patch_candidate":
            if not missing and not errors:
                usable = True
                handoff_options.append("patch_intent")
                reasons.extend([
                    "target_path present",
                    "old_text present",
                    "new_text present",
                    "reason present",
                ])
            else:
                reasons.append("patch_candidate reply is missing required fields")
        else:
            usable = not errors and "summary" in present
            reasons.append(f"{response_kind} reply is reviewable but not eligible for patch handoff")

        if not packet_ref:
            warnings.append("source packet ref is missing")
        if not reply.linked_session_id:
            warnings.append("source session ref is missing")

        summary = str(reply.content.get("summary", "") or "").strip()
        return BridgeReplyReview(
            schema_version=SCHEMA_VERSION,
            review_id=f"review_{_timestamp()}_{_short_id()}",
            created_at=_now(),
            reply_id=reply.reply_id or None,
            reply_ref=reply_ref,
            packet_id=reply.packet_id,
            packet_ref=packet_ref,
            response_kind=response_kind or None,
            usable=usable,
            handoff_options=handoff_options,
            required_fields_present=present,
            missing_fields=missing,
            summary=summary,
            reasons=_dedupe(reasons),
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )


class BridgeReplyHandoff:
    def to_patch_intent(self, project_root: Path, reply_path: Path) -> BridgeHandoffRecord:
        root = Path(project_root).resolve()
        path = Path(reply_path).resolve()
        review = BridgeReplyReviewer().review(root, path)
        if "patch_intent" not in review.handoff_options:
            return BridgeHandoffRecord(
                schema_version=SCHEMA_VERSION,
                handoff_id=f"handoff_{_timestamp()}_{_short_id()}",
                created_at=_now(),
                reply_id=review.reply_id,
                reply_ref=review.reply_ref,
                packet_id=review.packet_id,
                packet_ref=review.packet_ref,
                handoff_kind="patch_intent",
                target_artifact_ref=None,
                status="blocked",
                summary="bridge reply is not usable for patch intent handoff",
                warnings=list(review.warnings),
                errors=list(review.errors or review.missing_fields),
            )

        reply = ProjectBridgeStore().load_reply(path)
        target_path = str(reply.content.get("target_path", "") or "").strip()
        unsafe_reason = _unsafe_target_reason(target_path)
        if unsafe_reason:
            return BridgeHandoffRecord(
                schema_version=SCHEMA_VERSION,
                handoff_id=f"handoff_{_timestamp()}_{_short_id()}",
                created_at=_now(),
                reply_id=review.reply_id,
                reply_ref=review.reply_ref,
                packet_id=review.packet_id,
                packet_ref=review.packet_ref,
                handoff_kind="patch_intent",
                target_artifact_ref=None,
                status="blocked",
                summary="bridge reply target path is unsafe",
                warnings=list(review.warnings),
                errors=[unsafe_reason],
            )

        intent_path = _create_patch_intent_draft(root, reply, review)
        return BridgeHandoffRecord(
            schema_version=SCHEMA_VERSION,
            handoff_id=f"handoff_{_timestamp()}_{_short_id()}",
            created_at=_now(),
            reply_id=review.reply_id,
            reply_ref=review.reply_ref,
            packet_id=review.packet_id,
            packet_ref=review.packet_ref,
            handoff_kind="patch_intent",
            target_artifact_ref=_relative(intent_path, root),
            status="created",
            summary="patch intent draft created from bridge reply",
            warnings=list(review.warnings),
            errors=[],
        )


def render_bridge_reply_review(review: BridgeReplyReview, saved_path: str | None = None) -> str:
    lines = [
        "Bridge Reply Review",
        "==================================================",
        "",
        "Reply:",
        f"  {review.reply_id or review.reply_ref}",
        "",
        "Kind:",
        f"  {review.response_kind or 'unknown'}",
        "",
        "Looks usable:",
        f"  {'yes' if review.usable else 'no'}",
    ]
    if review.response_kind == "patch_candidate":
        lines.extend(["", "Required fields:"])
        for field_name in PATCH_CANDIDATE_REQUIRED_FIELDS:
            marker = "✓" if field_name in review.required_fields_present else "✗"
            lines.append(f"  {marker} {field_name}")
    if review.reasons:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {reason}" for reason in review.reasons])
    if review.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in review.warnings])
    if review.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {error}" for error in review.errors])
    lines.extend(["", "Next:"])
    if "patch_intent" in review.handoff_options:
        lines.append(f"  cambrian bridge handoff {review.reply_id or review.reply_ref} --as patch_intent")
    else:
        lines.append("  review this reply manually before creating follow-up work")
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    return "\n".join(lines)


def render_bridge_handoff(record: BridgeHandoffRecord, saved_path: str | None = None) -> str:
    lines = [
        "Bridge handoff completed." if record.status == "created" else "Bridge handoff blocked.",
        "",
        "Reply:",
        f"  {record.reply_id or record.reply_ref}",
        "",
        "Status:",
        f"  {record.status}",
    ]
    if record.target_artifact_ref:
        lines.extend(["", "Created:", f"  patch intent draft: {record.target_artifact_ref}"])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {error}" for error in record.errors])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in record.warnings])
    if saved_path:
        lines.extend(["", "Recorded:", f"  {saved_path}"])
    lines.extend(["", "Next:"])
    if record.status == "created" and record.target_artifact_ref:
        lines.append(f"  cambrian patch intent-fill {record.target_artifact_ref} --old-choice old-1 --new-text \"...\"")
        lines.append("  cambrian patch propose --from-intent <intent> after human review")
    else:
        lines.append("  cambrian bridge review <reply> --save")
    return "\n".join(lines)


def load_bridge_reply_activity(project_root: Path, reply_id: str | None) -> dict[str, Any]:
    if not reply_id:
        return {}
    root = Path(project_root).resolve()
    reviews = [
        review
        for review in _load_reviews(root)
        if review.reply_id == reply_id or Path(review.reply_ref).stem == reply_id
    ]
    handoffs = [
        record
        for record in _load_handoffs(root)
        if record.reply_id == reply_id or Path(record.reply_ref).stem == reply_id
    ]
    latest_review = reviews[0] if reviews else None
    latest_handoff = handoffs[0] if handoffs else None
    return {
        "reply_id": reply_id,
        "latest_review_id": latest_review.review_id if latest_review else None,
        "latest_review_usable": latest_review.usable if latest_review else None,
        "latest_review_options": list(latest_review.handoff_options) if latest_review else [],
        "latest_handoff_id": latest_handoff.handoff_id if latest_handoff else None,
        "latest_handoff_status": latest_handoff.status if latest_handoff else None,
        "latest_handoff_kind": latest_handoff.handoff_kind if latest_handoff else None,
        "target_artifact_ref": latest_handoff.target_artifact_ref if latest_handoff else None,
    }


def load_bridge_review_summary(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    reviews = _load_reviews(root)
    handoffs = _load_handoffs(root)
    latest_review = reviews[0] if reviews else None
    latest_handoff = handoffs[0] if handoffs else None
    return {
        "review_count": len(reviews),
        "handoff_count": len(handoffs),
        "latest_review_id": latest_review.review_id if latest_review else None,
        "latest_review_reply_id": latest_review.reply_id if latest_review else None,
        "latest_review_usable": latest_review.usable if latest_review else None,
        "latest_review_options": list(latest_review.handoff_options) if latest_review else [],
        "latest_handoff_id": latest_handoff.handoff_id if latest_handoff else None,
        "latest_handoff_reply_id": latest_handoff.reply_id if latest_handoff else None,
        "latest_handoff_kind": latest_handoff.handoff_kind if latest_handoff else None,
        "latest_handoff_status": latest_handoff.status if latest_handoff else None,
        "target_artifact_ref": latest_handoff.target_artifact_ref if latest_handoff else None,
    }


def _field_presence(reply: BridgeReply, response_kind: str) -> tuple[list[str], list[str]]:
    required = ["response_kind", "summary"]
    if response_kind == "patch_candidate":
        required = list(PATCH_CANDIDATE_REQUIRED_FIELDS)
    present: list[str] = []
    missing: list[str] = []
    for key in required:
        value = reply.content.get(key)
        if value is None or str(value).strip() == "":
            missing.append(key)
        else:
            present.append(key)
    return present, missing


def _packet_ref_for_reply(root: Path, reply: BridgeReply) -> str | None:
    if reply.linked_request_ref:
        return reply.linked_request_ref
    if not reply.packet_id:
        return None
    try:
        packet_path = resolve_bridge_packet_path(root, reply.packet_id)
    except FileNotFoundError:
        return None
    return _relative(packet_path, root)


def _unsafe_target_reason(target_path: str) -> str | None:
    if not target_path:
        return "target_path is required"
    path = Path(target_path)
    normalized = target_path.replace("\\", "/")
    if path.is_absolute():
        return f"absolute target path is not allowed: {target_path}"
    if ".." in path.parts:
        return f"parent traversal is not allowed: {target_path}"
    for protected in (".git", ".cambrian", "__pycache__", ".pytest_cache"):
        if normalized == protected or normalized.startswith(f"{protected}/"):
            return f"protected target path is not allowed: {target_path}"
    return None


def _create_patch_intent_draft(root: Path, reply: BridgeReply, review: BridgeReplyReview) -> Path:
    from engine.project_patch_intent import OldTextCandidate, PatchIntentForm, PatchIntentStore

    content = reply.content
    target_path = str(content.get("target_path", "") or "").strip()
    old_text = str(content.get("old_text", "") or "")
    new_text = str(content.get("new_text", "") or "")
    reason = str(content.get("reason", "") or "bridge reply patch candidate")
    intent_id = f"bridge-pintent-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_short_id()}"
    target_label = Path(target_path).name or "bridge_reply"
    intent_dir = root / ".cambrian" / "patch_intents"
    intent_path = intent_dir / f"patch_intent_{intent_id}_{target_label}.yaml"
    intent_ref = _relative(intent_path, root)
    related_tests = _as_list(content.get("related_tests"))
    warnings = _dedupe([*review.warnings, *_as_list(content.get("warnings"))])
    form = PatchIntentForm(
        schema_version="1.0.0",
        intent_id=intent_id,
        created_at=_now(),
        status="draft",
        user_request=reply.request or str(content.get("request", "") or "") or None,
        source_diagnosis_ref="",
        source_context_ref=review.packet_ref,
        target_path=target_path,
        related_tests=related_tests,
        inspected_files=[{"path": target_path, "source": "bridge_reply"}],
        test_summary=None,
        old_text_candidates=[
            OldTextCandidate(
                id="old-1",
                text=old_text,
                source_path=target_path,
                line_start=None,
                line_end=None,
                reason=f"bridge reply candidate: {reason}",
                confidence=0.6,
            )
        ],
        selected_old_text=None,
        selected_old_choice=None,
        new_text=new_text,
        proposal_path=None,
        warnings=warnings,
        errors=[],
        next_actions=[
            "Review this bridge-generated patch intent before proposal.",
            f"cambrian do --continue --validate",
            f"cambrian patch intent-fill {intent_ref} --old-choice old-1 --new-text \"...\"",
        ],
        memory_guidance={
            "origin": "bridge_handoff",
            "source_bridge_reply_ref": review.reply_ref,
            "source_bridge_packet_ref": review.packet_ref,
            "bridge_prefill": {
                "enabled": True,
                "source_bridge_reply_ref": review.reply_ref,
                "source_bridge_packet_ref": review.packet_ref,
                "target_path": target_path,
                "old_text": old_text,
                "new_text": new_text,
                "reason": reason,
                "related_tests": related_tests,
            },
        },
        origin="bridge_handoff",
        source_bridge_reply_ref=review.reply_ref,
        source_bridge_packet_ref=review.packet_ref,
        source_request_ref=reply.linked_request_ref,
        source_session_ref=reply.linked_session_id,
        bridge_prefill={
            "enabled": True,
            "source_bridge_reply_ref": review.reply_ref,
            "source_bridge_packet_ref": review.packet_ref,
            "target_path": target_path,
            "old_text": old_text,
            "new_text": new_text,
            "reason": reason,
            "related_tests": related_tests,
        },
    )
    PatchIntentStore().save(form, intent_path)
    return intent_path


def _review_from_dict(payload: dict[str, Any]) -> BridgeReplyReview:
    return BridgeReplyReview(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        review_id=str(payload.get("review_id", "")),
        created_at=str(payload.get("created_at", "")),
        reply_id=str(payload.get("reply_id")) if payload.get("reply_id") is not None else None,
        reply_ref=str(payload.get("reply_ref", "")),
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        packet_ref=str(payload.get("packet_ref")) if payload.get("packet_ref") is not None else None,
        response_kind=str(payload.get("response_kind")) if payload.get("response_kind") is not None else None,
        usable=bool(payload.get("usable", False)),
        handoff_options=[str(item) for item in payload.get("handoff_options", []) if item],
        required_fields_present=[str(item) for item in payload.get("required_fields_present", []) if item],
        missing_fields=[str(item) for item in payload.get("missing_fields", []) if item],
        summary=str(payload.get("summary", "") or ""),
        reasons=[str(item) for item in payload.get("reasons", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _handoff_from_dict(payload: dict[str, Any]) -> BridgeHandoffRecord:
    return BridgeHandoffRecord(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        handoff_id=str(payload.get("handoff_id", "")),
        created_at=str(payload.get("created_at", "")),
        reply_id=str(payload.get("reply_id")) if payload.get("reply_id") is not None else None,
        reply_ref=str(payload.get("reply_ref", "")),
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        packet_ref=str(payload.get("packet_ref")) if payload.get("packet_ref") is not None else None,
        handoff_kind=str(payload.get("handoff_kind", "")),
        target_artifact_ref=str(payload.get("target_artifact_ref"))
        if payload.get("target_artifact_ref") is not None
        else None,
        status=str(payload.get("status", "")),
        summary=str(payload.get("summary", "") or ""),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _sorted_yaml_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)


def _load_reviews(root: Path) -> list[BridgeReplyReview]:
    reviews: list[BridgeReplyReview] = []
    for path in _sorted_yaml_files(default_bridge_reviews_dir(root), "review_*.yaml"):
        try:
            reviews.append(BridgeReplyReviewStore().load(path))
        except Exception as exc:
            logger.warning("bridge review load failed: %s", exc)
    return reviews


def _load_handoffs(root: Path) -> list[BridgeHandoffRecord]:
    records: list[BridgeHandoffRecord] = []
    for path in _sorted_yaml_files(default_bridge_handoffs_dir(root), "handoff_*.yaml"):
        try:
            records.append(BridgeHandoffStore().load(path))
        except Exception as exc:
            logger.warning("bridge handoff load failed: %s", exc)
    return records
