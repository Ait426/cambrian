"""Bridge analysis_brief를 context/clarify/do 힌트로 연결한다."""

from __future__ import annotations

import logging
import re
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


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[0-9A-Za-z가-힣_./-]+", text or "") if len(token) >= 2}


def default_bridge_context_hints_dir(project_root: Path) -> Path:
    return default_bridge_dir(project_root) / "context_hints"


def default_bridge_context_hint_path(project_root: Path, hint: "BridgeContextHint") -> Path:
    return default_bridge_context_hints_dir(project_root) / f"{hint.hint_id}.yaml"


@dataclass
class BridgeContextHint:
    schema_version: str
    hint_id: str
    created_at: str
    materialization_id: str | None
    materialization_ref: str
    reply_id: str | None
    reply_ref: str | None
    packet_id: str | None
    packet_ref: str | None
    request: str | None
    project_name: str | None
    linked_session_id: str | None
    linked_request_ref: str | None
    summary: str
    recommended_files: list[str]
    recommended_tests: list[str]
    cautions: list[str]
    next_actions: list[str]
    source_kind: str = "bridge_analysis"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BridgeContextHintBuilder:
    def from_materialization(self, project_root: Path, materialization_path: Path) -> BridgeContextHint:
        root = Path(project_root).resolve()
        path = Path(materialization_path).resolve()
        record = BridgeMaterializationStore().load_record(path)
        warnings = list(record.warnings)
        errors = list(record.errors)
        if record.materialization_kind != "analysis_brief":
            errors.append("only analysis_brief materialization can become context_hint")
        if not record.recommended_files and not record.recommended_tests:
            warnings.append("analysis_brief has no recommended files/tests; summary-only hint created")
        return BridgeContextHint(
            schema_version=SCHEMA_VERSION,
            hint_id=f"context_hint_{_timestamp()}_{_short_id()}",
            created_at=_now(),
            materialization_id=record.materialization_id,
            materialization_ref=_relative(path, root),
            reply_id=record.reply_id,
            reply_ref=record.reply_ref,
            packet_id=record.packet_id,
            packet_ref=record.packet_ref,
            request=None,
            project_name=None,
            linked_session_id=None,
            linked_request_ref=record.packet_ref,
            summary=record.summary,
            recommended_files=list(record.recommended_files),
            recommended_tests=list(record.recommended_tests),
            cautions=list(record.cautions),
            next_actions=[
                "cambrian context scan \"<request>\"",
                "cambrian do \"<request>\"",
            ],
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )


class BridgeContextHintStore:
    def save_hint(self, hint: BridgeContextHint, path: Path) -> Path:
        if hint.errors:
            raise ValueError("; ".join(hint.errors))
        return _save_yaml(Path(path).resolve(), hint.to_dict())

    def load_hint(self, path: Path) -> BridgeContextHint:
        return _hint_from_dict(_load_yaml(Path(path).resolve()))

    def list_hints(self, hints_dir: Path) -> list[BridgeContextHint]:
        hints: list[BridgeContextHint] = []
        for path in _sorted_yaml_files(Path(hints_dir), "context_hint_*.yaml"):
            try:
                hints.append(self.load_hint(path))
            except Exception as exc:
                logger.warning("bridge context hint load failed: %s", exc)
        return hints


def resolve_bridge_context_hint_path(project_root: Path, hint_ref: str) -> Path:
    root = Path(project_root).resolve()
    ref = str(hint_ref or "").strip()
    candidate = Path(ref)
    if candidate.exists():
        return candidate.resolve()
    if not candidate.is_absolute():
        rel_candidate = root / candidate
        if rel_candidate.exists():
            return rel_candidate.resolve()
    directory = default_bridge_context_hints_dir(root)
    if directory.exists():
        for path in directory.glob("context_hint_*.yaml"):
            payload = _safe_load_yaml(path)
            if str(payload.get("hint_id", "")) == ref or path.stem == ref or path.name == ref:
                return path.resolve()
    raise FileNotFoundError(f"bridge context hint not found: {hint_ref}")


def apply_bridge_context_hints_to_scan(scan_result: Any, project_root: Path) -> Any:
    """context scan 후보에 bridge 분석 힌트를 약하게 반영한다."""
    root = Path(project_root).resolve()
    hints = BridgeContextHintStore().list_hints(default_bridge_context_hints_dir(root))[:5]
    if not hints:
        return scan_result
    _boost_candidates(getattr(scan_result, "suggested_sources", []), hints, "file")
    _boost_candidates(getattr(scan_result, "suggested_tests", []), hints, "test")
    guidance = dict(getattr(scan_result, "memory_guidance", {}) or {})
    guidance["bridge_context_hints"] = [
        {
            "hint_id": hint.hint_id,
            "summary": hint.summary,
            "recommended_files": list(hint.recommended_files),
            "recommended_tests": list(hint.recommended_tests),
        }
        for hint in hints[:3]
    ]
    scan_result.memory_guidance = guidance
    scan_result.suggested_sources = sorted(
        getattr(scan_result, "suggested_sources", []),
        key=lambda item: (-float(getattr(item, "score", 0.0)), getattr(item, "path", "")),
    )
    scan_result.suggested_tests = sorted(
        getattr(scan_result, "suggested_tests", []),
        key=lambda item: (-float(getattr(item, "score", 0.0)), getattr(item, "path", "")),
    )
    return scan_result


def relevant_bridge_context_hint_summary(project_root: Path, request: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    hints = BridgeContextHintStore().list_hints(default_bridge_context_hints_dir(root))
    if request:
        request_tokens = _tokens(request)
        scored = []
        for hint in hints:
            text = " ".join([hint.summary, *hint.recommended_files, *hint.recommended_tests])
            overlap = len(request_tokens & _tokens(text))
            scored.append((overlap, hint))
        hints = [hint for overlap, hint in sorted(scored, key=lambda item: (-item[0], item[1].created_at), reverse=False) if overlap > 0] or hints
    latest = hints[0] if hints else None
    return {
        "hint_count": len(hints),
        "latest_hint_id": latest.hint_id if latest else None,
        "summary": latest.summary if latest else None,
        "recommended_files": list(latest.recommended_files) if latest else [],
        "recommended_tests": list(latest.recommended_tests) if latest else [],
    }


def load_bridge_context_hint_activity(project_root: Path, materialization_id: str | None = None, reply_id: str | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve()
    hints = BridgeContextHintStore().list_hints(default_bridge_context_hints_dir(root))
    if materialization_id:
        hints = [hint for hint in hints if hint.materialization_id == materialization_id or Path(hint.materialization_ref).stem == materialization_id]
    if reply_id:
        hints = [hint for hint in hints if hint.reply_id == reply_id or (hint.reply_ref and Path(hint.reply_ref).stem == reply_id)]
    latest = hints[0] if hints else None
    return {
        "latest_context_hint_id": latest.hint_id if latest else None,
        "latest_context_hint_summary": latest.summary if latest else None,
    }


def render_bridge_context_hint_created(hint: BridgeContextHint, saved_path: str | None = None) -> str:
    lines = [
        "Bridge context hint created.",
        "",
        "Summary:",
        f"  {hint.summary}",
    ]
    if hint.recommended_files:
        lines.extend(["", "Suggested files:"])
        lines.extend([f"  - {item}" for item in hint.recommended_files[:5]])
    if hint.recommended_tests:
        lines.extend(["", "Suggested tests:"])
        lines.extend([f"  - {item}" for item in hint.recommended_tests[:5]])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    lines.extend(["", "Next:", "  cambrian context scan \"<request>\""])
    return "\n".join(lines)


def render_bridge_context_hint(hint: BridgeContextHint) -> str:
    lines = [
        "Bridge Context Hint",
        "==================================================",
        "",
        "Hint:",
        f"  {hint.hint_id}",
        "",
        "Summary:",
        f"  {hint.summary}",
    ]
    if hint.recommended_files:
        lines.extend(["", "Recommended files:"])
        lines.extend([f"  - {item}" for item in hint.recommended_files])
    if hint.recommended_tests:
        lines.extend(["", "Recommended tests:"])
        lines.extend([f"  - {item}" for item in hint.recommended_tests])
    if hint.cautions:
        lines.extend(["", "Cautions:"])
        lines.extend([f"  - {item}" for item in hint.cautions[:5]])
    return "\n".join(lines)


def render_bridge_context_hints(hints: list[BridgeContextHint], *, limit: int = 10) -> str:
    lines = ["Bridge Context Hints", "==================================================", "", "Recent:"]
    if not hints:
        lines.append("  none")
        return "\n".join(lines)
    for index, hint in enumerate(hints[: max(1, limit)], start=1):
        files = ", ".join(hint.recommended_files[:3]) or "none"
        tests = ", ".join(hint.recommended_tests[:3]) or "none"
        lines.append(f"  {index}. {hint.summary}")
        lines.append(f"     files: {files}")
        lines.append(f"     tests: {tests}")
    return "\n".join(lines)


def _boost_candidates(candidates: list[Any], hints: list[BridgeContextHint], kind: str) -> None:
    for candidate in candidates:
        path = str(getattr(candidate, "path", "") or "")
        if not path:
            continue
        matched = False
        for hint in hints:
            paths = hint.recommended_tests if kind == "test" else hint.recommended_files
            if path in paths:
                matched = True
                break
        if matched:
            candidate.score = min(1.0, round(float(getattr(candidate, "score", 0.0)) + 0.08, 2))
            candidate.reasons = _dedupe([
                *list(getattr(candidate, "reasons", []) or []),
                "AI bridge analysis suggested this file/test",
            ])


def _hint_from_dict(payload: dict[str, Any]) -> BridgeContextHint:
    return BridgeContextHint(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        hint_id=str(payload.get("hint_id", "")),
        created_at=str(payload.get("created_at", "")),
        materialization_id=str(payload.get("materialization_id")) if payload.get("materialization_id") is not None else None,
        materialization_ref=str(payload.get("materialization_ref", "")),
        reply_id=str(payload.get("reply_id")) if payload.get("reply_id") is not None else None,
        reply_ref=str(payload.get("reply_ref")) if payload.get("reply_ref") is not None else None,
        packet_id=str(payload.get("packet_id")) if payload.get("packet_id") is not None else None,
        packet_ref=str(payload.get("packet_ref")) if payload.get("packet_ref") is not None else None,
        request=str(payload.get("request")) if payload.get("request") is not None else None,
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_request_ref=str(payload.get("linked_request_ref")) if payload.get("linked_request_ref") is not None else None,
        summary=str(payload.get("summary", "") or ""),
        recommended_files=[str(item) for item in payload.get("recommended_files", []) if item],
        recommended_tests=[str(item) for item in payload.get("recommended_tests", []) if item],
        cautions=[str(item) for item in payload.get("cautions", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        source_kind=str(payload.get("source_kind", "bridge_analysis")),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _safe_load_yaml(path: Path) -> dict[str, Any]:
    try:
        return _load_yaml(path)
    except Exception as exc:
        logger.warning("bridge context hint lookup load failed: %s", exc)
        return {}


def _sorted_yaml_files(directory: Path, pattern: str) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
