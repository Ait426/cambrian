"""프로젝트 기억 override 저장소."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml


SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


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


@dataclass
class LessonOverride:
    """단일 lesson에 대한 사용자 override."""

    lesson_id: str
    pinned: bool = False
    suppressed: bool = False
    note: str | None = None
    updated_at: str | None = None
    updated_by: str | None = "user"

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class MemoryOverrides:
    """프로젝트 memory override 인덱스."""

    schema_version: str
    updated_at: str
    overrides: dict[str, LessonOverride] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "overrides": {
                key: value.to_dict()
                for key, value in sorted(self.overrides.items())
            },
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def default_memory_overrides_path(project_root: Path) -> Path:
    """프로젝트 기본 overrides.yaml 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "memory" / "overrides.yaml"


class MemoryOverrideStore:
    """memory override 저장/로드 도구."""

    def load(self, path: Path) -> MemoryOverrides:
        """overrides.yaml을 읽는다."""
        target = Path(path).resolve()
        if not target.exists():
            return MemoryOverrides(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
            )

        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("memory overrides YAML 최상위는 dict여야 합니다.")

        raw_overrides = payload.get("overrides", {})
        overrides: dict[str, LessonOverride] = {}
        if isinstance(raw_overrides, dict):
            for lesson_id, item in raw_overrides.items():
                if not isinstance(item, dict):
                    continue
                effective_lesson_id = str(item.get("lesson_id") or lesson_id)
                overrides[effective_lesson_id] = LessonOverride(
                    lesson_id=effective_lesson_id,
                    pinned=bool(item.get("pinned", False)),
                    suppressed=bool(item.get("suppressed", False)),
                    note=str(item.get("note")) if item.get("note") is not None else None,
                    updated_at=str(item.get("updated_at")) if item.get("updated_at") is not None else None,
                    updated_by=str(item.get("updated_by")) if item.get("updated_by") is not None else "user",
                )

        return MemoryOverrides(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            updated_at=str(payload.get("updated_at", _now())),
            overrides=overrides,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, overrides: MemoryOverrides, path: Path) -> Path:
        """overrides.yaml을 저장한다."""
        target = Path(path).resolve()
        overrides.updated_at = _now()
        _atomic_write_text(
            target,
            yaml.safe_dump(overrides.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def set_pin(self, path: Path, lesson_id: str, pinned: bool) -> MemoryOverrides:
        """lesson pin 상태를 갱신한다."""
        overrides = self.load(path)
        item = overrides.overrides.get(lesson_id, LessonOverride(lesson_id=lesson_id))
        item.pinned = bool(pinned)
        if item.pinned:
            item.suppressed = False
        item.updated_at = _now()
        item.updated_by = "user"
        overrides.overrides[lesson_id] = item
        self.save(overrides, path)
        return overrides

    def set_suppressed(self, path: Path, lesson_id: str, suppressed: bool) -> MemoryOverrides:
        """lesson suppress 상태를 갱신한다."""
        overrides = self.load(path)
        item = overrides.overrides.get(lesson_id, LessonOverride(lesson_id=lesson_id))
        item.suppressed = bool(suppressed)
        if item.suppressed:
            item.pinned = False
        item.updated_at = _now()
        item.updated_by = "user"
        overrides.overrides[lesson_id] = item
        self.save(overrides, path)
        return overrides

    def set_note(self, path: Path, lesson_id: str, note: str | None) -> MemoryOverrides:
        """lesson note를 갱신한다."""
        overrides = self.load(path)
        item = overrides.overrides.get(lesson_id, LessonOverride(lesson_id=lesson_id))
        cleaned = " ".join(str(note or "").split()).strip()
        item.note = cleaned or None
        item.updated_at = _now()
        item.updated_by = "user"
        overrides.overrides[lesson_id] = item
        self.save(overrides, path)
        return overrides


def load_memory_overrides(project_root: Path) -> MemoryOverrides:
    """프로젝트 기본 overrides.yaml을 로드한다."""
    return MemoryOverrideStore().load(default_memory_overrides_path(project_root))
