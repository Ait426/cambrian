"""Cambrian 프로젝트 로컬 사용자 노트 저장소."""

from __future__ import annotations

import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_next import primary_next_command

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
VALID_NOTE_KINDS = {"note", "confusion", "bug", "idea", "success", "friction"}
VALID_SEVERITIES = {"low", "medium", "high"}
_SESSION_TERMINAL_STAGES = {"adopted", "completed", "closed", "error"}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 만든다."""
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    """노트 파일명용 UTC 타임스탬프를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _note_id() -> str:
    """노트 식별자를 만든다."""
    return f"note-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


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


def _load_yaml(path: Path) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("노트 YAML 로드 실패: %s (%s)", path, exc)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("노트 YAML 형식 오류: %s", path)
        return None
    return payload


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_notes_dir(project_root: Path) -> Path:
    """기본 notes 디렉터리 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "notes"


@dataclass
class UserNote:
    """사용자 피드백 노트 artifact."""

    schema_version: str
    note_id: str
    created_at: str
    updated_at: str | None
    status: str
    kind: str
    severity: str
    text: str
    resolution: str | None
    project_name: str | None
    session_id: str | None
    session_ref: str | None
    stage: str | None
    artifact_refs: list[str]
    tags: list[str]
    context: dict
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class ProjectNotesStore:
    """프로젝트 notes artifact 저장소."""

    def add(self, note: UserNote, notes_dir: Path) -> Path:
        """새 노트를 저장한다."""
        target = Path(notes_dir).resolve() / self._filename_for(note)
        self._write(target, note)
        return target

    def load(self, path: Path) -> UserNote:
        """노트 파일 하나를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if payload is None:
            raise FileNotFoundError(path)
        return UserNote(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            note_id=str(payload.get("note_id", Path(path).stem)),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
            status=str(payload.get("status", "open")),
            kind=str(payload.get("kind", "note")),
            severity=str(payload.get("severity", "medium")),
            text=str(payload.get("text", "")),
            resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            session_id=str(payload.get("session_id")) if payload.get("session_id") is not None else None,
            session_ref=str(payload.get("session_ref")) if payload.get("session_ref") is not None else None,
            stage=str(payload.get("stage")) if payload.get("stage") is not None else None,
            artifact_refs=[str(item) for item in payload.get("artifact_refs", []) if item],
            tags=[str(item) for item in payload.get("tags", []) if item],
            context=dict(payload.get("context", {})) if isinstance(payload.get("context"), dict) else {},
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def list(self, notes_dir: Path) -> list[UserNote]:
        """notes 디렉터리의 노트를 최신순으로 반환한다."""
        directory = Path(notes_dir).resolve()
        if not directory.exists():
            return []
        paths = sorted(
            (item for item in directory.glob("note_*.yaml") if item.is_file()),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        notes: list[UserNote] = []
        for path in paths:
            try:
                notes.append(self.load(path))
            except FileNotFoundError:
                continue
        return notes

    def resolve(self, note_path: Path, resolution: str | None) -> Path:
        """노트를 resolved 상태로 업데이트한다."""
        path = Path(note_path).resolve()
        note = self.load(path)
        note.status = "resolved"
        note.updated_at = _now()
        note.resolution = str(resolution).strip() if resolution else note.resolution
        self._write(path, note)
        return path

    def resolve_path(self, project_root: Path, note_ref: str) -> Path:
        """노트 ID 또는 경로를 실제 artifact 경로로 바꾼다."""
        notes_dir = default_notes_dir(project_root)
        candidate = Path(note_ref)
        if candidate.exists():
            resolved = candidate.resolve()
            try:
                resolved.relative_to(notes_dir)
            except ValueError as exc:
                raise FileNotFoundError(f"note not found: {note_ref}") from exc
            if resolved.is_file() and resolved.name.startswith("note_") and resolved.suffix == ".yaml":
                return resolved
            raise FileNotFoundError(f"note not found: {note_ref}")
        for path in notes_dir.glob("note_*.yaml") if notes_dir.exists() else []:
            payload = _load_yaml(path)
            if not payload:
                continue
            note_id = str(payload.get("note_id", ""))
            if note_id == note_ref or path.stem == note_ref:
                return path.resolve()
        raise FileNotFoundError(f"note not found: {note_ref}")

    @staticmethod
    def _filename_for(note: UserNote) -> str:
        """노트 파일명을 만든다."""
        stamp = _timestamp()
        suffix = note.note_id.split("-")[-1]
        return f"note_{stamp}_{suffix}.yaml"

    @staticmethod
    def _write(path: Path, note: UserNote) -> None:
        """노트 객체를 YAML로 저장한다."""
        _atomic_write_text(
            path,
            yaml.safe_dump(note.to_dict(), allow_unicode=True, sort_keys=False),
        )


class ProjectNotesBuilder:
    """현재 프로젝트 맥락과 연결된 사용자 노트를 만든다."""

    def build(
        self,
        text: str,
        project_root: Path,
        kind: str = "note",
        severity: str = "medium",
        tags: list[str] | None = None,
        session_ref: str | None = None,
        artifact_refs: list[str] | None = None,
    ) -> UserNote:
        """입력 문장과 현재 프로젝트 맥락으로 노트를 구성한다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        note_kind = kind if kind in VALID_NOTE_KINDS else "note"
        note_severity = severity if severity in VALID_SEVERITIES else "medium"

        project_name = self._project_name(root)
        session_path, session_payload = self._resolve_session_context(root, session_ref, warnings)
        stage = None
        session_id = None
        session_ref_value = None
        auto_artifacts: list[str] = []
        context: dict[str, str | None] = {
            "user_request": None,
            "next_command": None,
            "command_name": "cambrian notes add",
            "workspace": ".",
        }
        if session_payload is not None:
            stage = str(session_payload.get("current_stage") or session_payload.get("status") or "unknown")
            session_id = str(session_payload.get("session_id", "")) or None
            session_ref_value = (
                _relative_to_project(session_path, root)
                if session_path is not None else None
            )
            auto_artifact = self._latest_artifact_ref(session_payload)
            if auto_artifact:
                auto_artifacts.append(auto_artifact)
            context = {
                "user_request": str(session_payload.get("user_request", "")) or None,
                "next_command": self._primary_next_command(session_payload),
                "command_name": self._command_name_for_stage(stage),
                "workspace": ".",
            }

        merged_artifacts = _dedupe(
            [
                *auto_artifacts,
                *self._normalize_artifact_refs(root, artifact_refs or []),
            ]
        )

        return UserNote(
            schema_version=SCHEMA_VERSION,
            note_id=_note_id(),
            created_at=_now(),
            updated_at=None,
            status="open",
            kind=note_kind,
            severity=note_severity,
            text=str(text).strip(),
            resolution=None,
            project_name=project_name,
            session_id=session_id,
            session_ref=session_ref_value,
            stage=stage,
            artifact_refs=merged_artifacts,
            tags=_dedupe([str(item) for item in tags or [] if item]),
            context=context,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    @staticmethod
    def _project_name(project_root: Path) -> str | None:
        """project.yaml에서 프로젝트 이름을 읽는다."""
        payload = _load_yaml(project_root / ".cambrian" / "project.yaml")
        if not payload:
            return None
        project = payload.get("project", {})
        if not isinstance(project, dict):
            return None
        raw_name = project.get("name")
        return str(raw_name) if raw_name is not None else None

    def _resolve_session_context(
        self,
        project_root: Path,
        session_ref: str | None,
        warnings: list[str],
    ) -> tuple[Path | None, dict | None]:
        """명시한 세션 또는 active 세션을 찾아 payload를 반환한다."""
        sessions_dir = project_root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return None, None

        if session_ref:
            candidate = Path(session_ref)
            if candidate.exists():
                payload = _load_yaml(candidate.resolve())
                return (candidate.resolve(), payload) if payload is not None else (None, None)
            for path in sorted(sessions_dir.glob("do_session_*.yaml"), reverse=True):
                payload = _load_yaml(path)
                if not payload:
                    continue
                session_id = str(payload.get("session_id", ""))
                if session_id == session_ref or path.stem == session_ref:
                    return path.resolve(), payload
            warnings.append(f"session not found: {session_ref}")
            return None, None

        candidates = sorted(
            (item for item in sessions_dir.glob("do_session_*.yaml") if item.is_file()),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        for path in candidates:
            payload = _load_yaml(path)
            if not payload:
                continue
            stage = str(payload.get("current_stage") or payload.get("status") or "unknown")
            if stage not in _SESSION_TERMINAL_STAGES:
                return path.resolve(), payload
        return None, None

    @staticmethod
    def _primary_next_command(payload: dict) -> str | None:
        """세션 payload에서 대표 next command를 뽑는다."""
        next_commands = payload.get("next_commands", [])
        if isinstance(next_commands, list):
            primary = primary_next_command(next_commands)
            if isinstance(primary, dict) and primary.get("command"):
                return str(primary.get("command"))
        next_actions = payload.get("next_actions", [])
        if isinstance(next_actions, list) and next_actions:
            return str(next_actions[0])
        return None

    @staticmethod
    def _latest_artifact_ref(payload: dict) -> str | None:
        """세션과 가장 가까운 artifact 경로를 고른다."""
        artifacts = payload.get("artifacts", {})
        if not isinstance(artifacts, dict):
            return None
        for key in (
            "adoption_record_path",
            "patch_proposal_path",
            "patch_intent_path",
            "report_path",
            "clarification_path",
            "context_scan_path",
            "request_path",
        ):
            raw_value = artifacts.get(key)
            if raw_value:
                return str(raw_value)
        return None

    @staticmethod
    def _normalize_artifact_refs(project_root: Path, artifact_refs: list[str]) -> list[str]:
        """artifact 참조를 프로젝트 기준 문자열로 정리한다."""
        normalized: list[str] = []
        for raw in artifact_refs:
            if not raw:
                continue
            candidate = Path(str(raw))
            if candidate.exists():
                normalized.append(_relative_to_project(candidate.resolve(), project_root))
            else:
                normalized.append(str(raw).replace("\\", "/"))
        return normalized

    @staticmethod
    def _command_name_for_stage(stage: str | None) -> str:
        """stage에 맞는 대표 명령 이름을 만든다."""
        stage_name = str(stage or "")
        if stage_name in {"needs_context", "clarification_open", "diagnose_ready"}:
            return "cambrian do"
        if stage_name:
            return "cambrian do --continue"
        return "cambrian notes add"


def render_note_add_summary(note: UserNote, note_path: str) -> str:
    """노트 저장 완료 메시지를 렌더링한다."""
    lines = [
        "Cambrian saved your note.",
        "==================================================",
        "",
        "Note:",
        f"  [{note.kind}][{note.severity}]",
        f"  {note.text}",
    ]
    if note.session_id or note.stage:
        lines.extend(
            [
                "",
                "Linked:",
                f"  session : {note.session_id or '-'}",
                f"  stage   : {note.stage or '-'}",
            ]
        )
    lines.extend(
        [
            "",
            "Saved:",
            f"  {note_path}",
            "",
            "Next:",
            "  cambrian notes list",
        ]
    )
    return "\n".join(lines)


def render_notes_list(
    notes: list[UserNote],
    *,
    status_filter: str,
) -> str:
    """노트 목록 화면을 렌더링한다."""
    heading = "Resolved" if status_filter == "resolved" else "Open"
    lines = [
        "Project Notes",
        "==================================================",
        "",
        f"{heading}:",
    ]
    if not notes:
        lines.append("  none")
    else:
        for index, note in enumerate(notes, start=1):
            snippet = note.text if len(note.text) <= 80 else f"{note.text[:77]}..."
            lines.append(f"  {index}. [{note.kind}][{note.severity}] {snippet}")
            lines.append(f"     id: {note.note_id}")
            if note.session_id:
                lines.append(f"     session: {note.session_id}")
    lines.extend(["", "Next:"])
    if notes:
        lines.append(f"  cambrian notes show {notes[0].note_id}")
    else:
        lines.append('  cambrian notes add "clarify step was confusing" --kind confusion')
    return "\n".join(lines)


def render_note_show(note: UserNote, note_path: str) -> str:
    """노트 상세 화면을 렌더링한다."""
    lines = [
        "Cambrian Note",
        "==================================================",
        "",
        "Meta:",
        f"  id       : {note.note_id}",
        f"  status   : {note.status}",
        f"  kind     : {note.kind}",
        f"  severity : {note.severity}",
        f"  created  : {note.created_at}",
        f"  updated  : {note.updated_at or '-'}",
        f"  path     : {note_path}",
        "",
        "Text:",
        f"  {note.text}",
    ]
    if note.resolution:
        lines.extend(["", "Resolution:", f"  {note.resolution}"])
    if note.session_id or note.stage:
        lines.extend(
            [
                "",
                "Linked work:",
                f"  session : {note.session_id or '-'}",
                f"  stage   : {note.stage or '-'}",
            ]
        )
    if note.artifact_refs:
        lines.extend(["", "Artifacts:"])
        for item in note.artifact_refs:
            lines.append(f"  - {item}")
    if note.tags:
        lines.extend(["", "Tags:"])
        for item in note.tags:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def render_note_resolve_summary(note: UserNote) -> str:
    """노트 해결 처리 결과를 렌더링한다."""
    lines = [
        "Cambrian resolved this note.",
        "==================================================",
        "",
        "Note:",
        f"  {note.note_id}",
    ]
    if note.resolution:
        lines.extend(["", "Resolution:", f"  {note.resolution}"])
    lines.extend(["", "Next:", "  cambrian notes list --status resolved"])
    return "\n".join(lines)
