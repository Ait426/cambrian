"""Bridge plan_record를 사람이 추적할 수 있는 checklist로 변환한다."""

from __future__ import annotations

import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_bridge import default_bridge_dir
from engine.project_bridge_materialize import BridgeMaterializationStore

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
STEP_STATUSES = {"todo", "done", "blocked", "skipped"}


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


def default_bridge_checklists_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "checklists"


def default_bridge_checklist_path(project_root: Path, checklist: "BridgeChecklist") -> Path:
    return default_bridge_checklists_dir(project_root) / f"{checklist.checklist_id}.yaml"


@dataclass
class BridgeChecklistStep:
    step_id: str
    text: str
    status: str = "todo"
    note: str | None = None
    linked_command: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BridgeChecklist:
    schema_version: str
    checklist_id: str
    created_at: str
    updated_at: str | None
    materialization_id: str | None
    materialization_ref: str
    reply_id: str | None
    reply_ref: str | None
    packet_id: str | None
    packet_ref: str | None
    linked_session_id: str | None
    linked_session_ref: str | None
    linked_request_ref: str | None
    title: str
    summary: str
    request: str | None
    steps: list[BridgeChecklistStep]
    next_step_id: str | None
    overall_status: str
    cautions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


class BridgeChecklistBuilder:
    def from_materialization(
        self,
        project_root: Path,
        materialization_path: Path,
        session_ref: str | None = None,
    ) -> BridgeChecklist:
        root = Path(project_root).resolve()
        path = Path(materialization_path).resolve()
        record = BridgeMaterializationStore().load_record(path)
        warnings = list(record.warnings)
        errors = list(record.errors)
        if record.materialization_kind != "plan_record":
            errors.append("only plan_record materialization can become checklist")
        steps = [
            BridgeChecklistStep(step_id=f"step-{index}", text=str(step).strip())
            for index, step in enumerate(record.steps, start=1)
            if str(step).strip()
        ]
        if not steps and record.summary:
            steps = [BridgeChecklistStep(step_id="step-1", text=record.summary)]
            warnings.append("AI plan did not include explicit steps; created one summary step")
        linked_session_id, linked_session_ref = _resolve_session(root, session_ref)
        checklist = BridgeChecklist(
            schema_version=SCHEMA_VERSION,
            checklist_id=f"checklist_{_timestamp()}_{_short_id()}",
            created_at=_now(),
            updated_at=None,
            materialization_id=record.materialization_id,
            materialization_ref=_relative(path, root),
            reply_id=record.reply_id,
            reply_ref=record.reply_ref,
            packet_id=record.packet_id,
            packet_ref=record.packet_ref,
            linked_session_id=linked_session_id,
            linked_session_ref=linked_session_ref,
            linked_request_ref=record.packet_ref,
            title=record.title or "Bridge plan checklist",
            summary=record.summary,
            request=None,
            steps=steps,
            next_step_id=None,
            overall_status="open",
            cautions=list(record.cautions),
            next_actions=[],
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )
        _recalculate(checklist)
        checklist.next_actions = _next_actions(checklist)
        return checklist


class BridgeChecklistStore:
    def save(self, checklist: BridgeChecklist, path: Path) -> Path:
        if checklist.errors:
            raise ValueError("; ".join(checklist.errors))
        _recalculate(checklist)
        return _save_yaml(Path(path).resolve(), checklist.to_dict())

    def load(self, path: Path) -> BridgeChecklist:
        return _checklist_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, checklists_dir: Path) -> list[BridgeChecklist]:
        checklists: list[BridgeChecklist] = []
        for path in _sorted_yaml_files(Path(checklists_dir), "checklist_*.yaml"):
            try:
                checklists.append(self.load(path))
            except Exception as exc:
                logger.warning("bridge checklist load failed: %s", exc)
        return checklists

    def update_step(self, checklist_path: Path, step_id: str, status: str, note: str | None = None) -> Path:
        if status not in STEP_STATUSES:
            raise ValueError(f"invalid checklist step status: {status}")
        path = Path(checklist_path).resolve()
        checklist = self.load(path)
        found = False
        for step in checklist.steps:
            if step.step_id == step_id:
                step.status = status
                if note is not None:
                    step.note = note
                found = True
                break
        if not found:
            raise KeyError(f"checklist step not found: {step_id}")
        checklist.updated_at = _now()
        _recalculate(checklist)
        checklist.next_actions = _next_actions(checklist)
        return self.save(checklist, path)


def resolve_bridge_checklist_path(project_root: Path, checklist_ref: str) -> Path:
    root = Path(project_root).resolve()
    ref = str(checklist_ref or "").strip()
    candidate = Path(ref)
    if candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        rel_candidate = root / candidate
        if rel_candidate.exists():
            return rel_candidate.resolve()
    directory = default_bridge_checklists_dir(root)
    if directory.exists():
        for path in directory.glob("checklist_*.yaml"):
            payload = _safe_load_yaml(path)
            if str(payload.get("checklist_id", "")) == ref or path.stem == ref or path.name == ref:
                return path.resolve()
    raise FileNotFoundError(f"bridge checklist not found: {checklist_ref}")


def load_bridge_checklist_activity(
    project_root: Path,
    *,
    reply_id: str | None = None,
    materialization_id: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    checklists = BridgeChecklistStore().list(default_bridge_checklists_dir(root))
    if reply_id:
        checklists = [
            item for item in checklists
            if item.reply_id == reply_id or (item.reply_ref and Path(item.reply_ref).stem == reply_id)
        ]
    if materialization_id:
        checklists = [
            item for item in checklists
            if item.materialization_id == materialization_id or Path(item.materialization_ref).stem == materialization_id
        ]
    latest = checklists[0] if checklists else None
    next_step = _step_by_id(latest, latest.next_step_id) if latest else None
    return {
        "latest_checklist_id": latest.checklist_id if latest else None,
        "latest_checklist_status": latest.overall_status if latest else None,
        "latest_checklist_next_step": next_step.text if next_step else None,
        "latest_checklist_session_id": latest.linked_session_id if latest else None,
    }


def load_bridge_checklist_summary(project_root: Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    checklists = BridgeChecklistStore().list(default_bridge_checklists_dir(root))
    latest = checklists[0] if checklists else None
    next_step = _step_by_id(latest, latest.next_step_id) if latest else None
    return {
        "checklist_count": len(checklists),
        "latest_checklist_id": latest.checklist_id if latest else None,
        "latest_status": latest.overall_status if latest else None,
        "latest_next_step_id": latest.next_step_id if latest else None,
        "latest_next_step_text": next_step.text if next_step else None,
        "latest_blocked_note": next_step.note if next_step and next_step.status == "blocked" else None,
        "latest_linked_session_id": latest.linked_session_id if latest else None,
    }


def bridge_checklist_hint_for_session(project_root: Path, session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {}
    root = Path(project_root).resolve()
    checklists = [
        item
        for item in BridgeChecklistStore().list(default_bridge_checklists_dir(root))
        if item.linked_session_id == session_id
        or (item.linked_session_ref and session_id in item.linked_session_ref)
    ]
    latest = checklists[0] if checklists else None
    next_step = _step_by_id(latest, latest.next_step_id) if latest else None
    if not latest:
        return {}
    return {
        "checklist_id": latest.checklist_id,
        "overall_status": latest.overall_status,
        "next_step_id": latest.next_step_id,
        "next_step_text": next_step.text if next_step else None,
        "blocked_note": next_step.note if next_step and next_step.status == "blocked" else None,
    }


def render_bridge_checklist_created(checklist: BridgeChecklist, saved_path: str | None = None) -> str:
    lines = [
        "Bridge checklist created.",
        "",
        "Summary:",
        f"  {checklist.summary}",
        "",
        "Steps:",
    ]
    for index, step in enumerate(checklist.steps, start=1):
        lines.append(f"  {index}. {step.text}")
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    lines.extend(["", "Next:", f"  cambrian bridge checklist-show {checklist.checklist_id}"])
    return "\n".join(lines)


def render_bridge_checklist(checklist: BridgeChecklist) -> str:
    lines = [
        "Bridge Checklist",
        "==================================================",
        "",
        "Checklist:",
        f"  {checklist.checklist_id}",
        "",
        "Status:",
        f"  {checklist.overall_status}",
        "",
        "Summary:",
        f"  {checklist.summary}",
        "",
        "Steps:",
    ]
    for step in checklist.steps:
        marker = {
            "todo": "[ ]",
            "done": "[x]",
            "blocked": "[!]",
            "skipped": "[-]",
        }.get(step.status, "[ ]")
        suffix = f" -- {step.note}" if step.note else ""
        lines.append(f"  {marker} {step.step_id}: {step.text}{suffix}")
    next_step = _step_by_id(checklist, checklist.next_step_id)
    if next_step:
        lines.extend(["", "Next step:", f"  {next_step.text}"])
    if checklist.linked_session_id:
        lines.extend(["", "Linked session:", f"  {checklist.linked_session_id}"])
    return "\n".join(lines)


def render_bridge_checklists(checklists: list[BridgeChecklist], *, status: str | None = None, limit: int = 10) -> str:
    filtered = [item for item in checklists if status is None or item.overall_status == status]
    lines = ["Bridge Checklists", "==================================================", "", "Recent:"]
    if not filtered:
        lines.append("  none")
        return "\n".join(lines)
    for index, checklist in enumerate(filtered[: max(1, limit)], start=1):
        next_step = _step_by_id(checklist, checklist.next_step_id)
        lines.append(f"  {index}. {checklist.summary}")
        lines.append(f"     status: {checklist.overall_status}")
        if next_step:
            lines.append(f"     next: {next_step.text}")
    return "\n".join(lines)


def render_bridge_checklist_step_updated(checklist: BridgeChecklist, step_id: str, saved_path: str | None = None) -> str:
    step = _step_by_id(checklist, step_id)
    lines = [
        "Bridge checklist step updated.",
        "",
        "Checklist:",
        f"  {checklist.checklist_id}",
        "",
        "Step:",
        f"  {step_id} -> {step.status if step else 'unknown'}",
        "",
        "Overall:",
        f"  {checklist.overall_status}",
    ]
    next_step = _step_by_id(checklist, checklist.next_step_id)
    if next_step:
        lines.extend(["", "Next step:", f"  {next_step.text}"])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    return "\n".join(lines)


def _resolve_session(root: Path, session_ref: str | None) -> tuple[str | None, str | None]:
    if not session_ref:
        return None, None
    try:
        from engine.project_do import DoSessionStore

        session_path = DoSessionStore().resolve_path(root, session_ref)
        session = DoSessionStore().load(session_path)
        return session.session_id, _relative(session_path, root)
    except Exception as exc:
        logger.warning("bridge checklist session link failed: %s", exc)
        return str(session_ref), str(session_ref)


def _recalculate(checklist: BridgeChecklist) -> None:
    statuses = [step.status for step in checklist.steps]
    next_todo = next((step.step_id for step in checklist.steps if step.status == "todo"), None)
    next_blocked = next((step.step_id for step in checklist.steps if step.status == "blocked"), None)
    checklist.next_step_id = next_todo or next_blocked
    if statuses and all(status in {"done", "skipped"} for status in statuses):
        checklist.overall_status = "completed"
    elif any(status == "blocked" for status in statuses):
        checklist.overall_status = "blocked"
    elif any(status in {"done", "skipped"} for status in statuses):
        checklist.overall_status = "in_progress"
    elif any(status == "todo" for status in statuses):
        checklist.overall_status = "open"
    else:
        checklist.overall_status = "open"


def _next_actions(checklist: BridgeChecklist) -> list[str]:
    actions = [f"cambrian bridge checklist-show {checklist.checklist_id}"]
    if checklist.next_step_id:
        actions.append(f"cambrian bridge checklist-step {checklist.checklist_id} {checklist.next_step_id} --done")
    return actions


def _step_by_id(checklist: BridgeChecklist | None, step_id: str | None) -> BridgeChecklistStep | None:
    if not checklist or not step_id:
        return None
    for step in checklist.steps:
        if step.step_id == step_id:
            return step
    return None


def _checklist_from_dict(payload: dict[str, Any]) -> BridgeChecklist:
    steps = [
        BridgeChecklistStep(
            step_id=str(item.get("step_id", "")),
            text=str(item.get("text", "")),
            status=str(item.get("status", "todo")),
            note=str(item.get("note")) if item.get("note") is not None else None,
            linked_command=str(item.get("linked_command")) if item.get("linked_command") is not None else None,
            warnings=[str(value) for value in item.get("warnings", []) if value],
        )
        for item in payload.get("steps", []) or []
        if isinstance(item, dict)
    ]
    checklist = BridgeChecklist(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        checklist_id=str(payload.get("checklist_id", "")),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        materialization_id=str(payload.get("materialization_id")) if payload.get("materialization_id") is not None else None,
        materialization_ref=str(payload.get("materialization_ref", "")),
        reply_id=str(payload.get("reply_id")) if payload.get("reply_id") is not None else None,
        reply_ref=str(payload.get("reply_ref")) if payload.get("reply_ref") is not None else None,
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        packet_ref=str(payload.get("packet_ref")) if payload.get("packet_ref") is not None else None,
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_session_ref=str(payload.get("linked_session_ref")) if payload.get("linked_session_ref") is not None else None,
        linked_request_ref=str(payload.get("linked_request_ref")) if payload.get("linked_request_ref") is not None else None,
        title=str(payload.get("title", "")),
        summary=str(payload.get("summary", "") or ""),
        request=str(payload.get("request")) if payload.get("request") is not None else None,
        steps=steps,
        next_step_id=str(payload.get("next_step_id")) if payload.get("next_step_id") is not None else None,
        overall_status=str(payload.get("overall_status", "open")),
        cautions=[str(item) for item in payload.get("cautions", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
    _recalculate(checklist)
    return checklist


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    try:
        return _load_yaml(path)
    except Exception as exc:
        logger.warning("bridge checklist lookup load failed: %s", exc)
        return {}


def _sorted_yaml_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
