"""Cambrian 프로젝트 기억 lessons 빌더와 조회 도구."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_memory_overrides import (
    MemoryOverrides,
    default_memory_overrides_path,
    load_memory_overrides,
)

logger = logging.getLogger(__name__)


SCHEMA_VERSION = "1.0.0"
DEFAULT_LESSON_LIMIT = 30

_KIND_PRIORITY = {
    "test_practice": 0,
    "avoid_pattern": 1,
    "successful_pattern": 2,
    "missing_evidence": 3,
    "adoption_reason": 4,
    "risk_warning": 5,
    "next_action": 6,
}

_REQUEST_ALIASES: dict[str, tuple[str, ...]] = {
    "로그인": ("login", "auth"),
    "인증": ("auth",),
    "테스트": ("test", "tests", "pytest"),
    "버그": ("bug", "fix"),
    "오류": ("error", "bug"),
    "에러": ("error", "bug"),
    "문서": ("docs", "documentation", "readme"),
    "리팩터": ("refactor",),
}

_RISK_FLAG_TEXT = {
    "repeated_no_winner": "Repeated no-winner outcomes were observed in recent runs.",
    "repeated_contradicted_hypothesis": "Contradicted hypotheses were repeated in recent runs.",
    "rollback_recently_observed": "A rollback was observed recently; verify carefully before adoption.",
    "missing_evidence_repeated": "Missing evidence was repeated across recent runs.",
    "no_adopted_generation": "No adopted generation was observed recently.",
}


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


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _load_yaml(path: Path, warnings: list[str]) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        warnings.append(f"YAML 읽기 실패: {path} ({exc})")
        logger.warning("YAML 읽기 실패: %s (%s)", path, exc)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        warnings.append(f"YAML 형식 오류: {path}")
        logger.warning("YAML 형식 오류: %s", path)
        return None
    return payload


def _load_json(path: Path, warnings: list[str]) -> dict | None:
    """JSON 파일을 안전하게 읽는다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"JSON 읽기 실패: {path} ({exc})")
        logger.warning("JSON 읽기 실패: %s (%s)", path, exc)
        return None
    if not isinstance(payload, dict):
        warnings.append(f"JSON 형식 오류: {path}")
        logger.warning("JSON 형식 오류: %s", path)
        return None
    return payload


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _normalize_text(text: str) -> str:
    """lesson dedupe용 정규화 문자열을 만든다."""
    normalized = " ".join(str(text or "").strip().lower().split())
    return normalized.strip(" .,!?:;")


def _slugify(text: str) -> str:
    """안정적인 lesson slug를 만든다."""
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if ascii_slug:
        return ascii_slug[:80]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"text-{digest}"


def _extract_tokens(text: str) -> list[str]:
    """간단한 토큰 목록을 만든다."""
    tokens = re.findall(r"[a-z0-9_./-]+|[가-힣]+", str(text or "").lower())
    return [token for token in tokens if len(token) >= 2]


def _expand_request_tokens(tokens: list[str]) -> list[str]:
    """요청 토큰에 간단한 별칭을 더한다."""
    expanded = list(tokens)
    for token in tokens:
        expanded.extend(_REQUEST_ALIASES.get(token, ()))
    return _dedupe(expanded)


def _friendly_sentence(text: str) -> str:
    """사람이 읽기 좋은 한 줄 문장으로 정리한다."""
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned[0].upper() + cleaned[1:]


def _kind_from_text(default_kind: str, text: str) -> str:
    """문장 내용으로 lesson kind를 가볍게 보정한다."""
    lowered = str(text or "").lower()
    if "run " in lowered and ("test" in lowered or "pytest" in lowered):
        return "test_practice"
    if lowered.startswith("avoid "):
        return "avoid_pattern"
    return default_kind


def _tags_for_lesson(text: str, source_refs: list[str], extra_tags: list[str] | None = None) -> list[str]:
    """lesson 검색용 태그를 만든다."""
    tags: list[str] = list(extra_tags or [])
    tags.extend(_extract_tokens(text))
    for ref in source_refs:
        tags.extend(_extract_tokens(ref))
    blocked = {
        "cambrian",
        "memory",
        "lessons",
        "json",
        "yaml",
        "report",
        "adoption",
        "feedback",
        "session",
        "brain",
        "runs",
    }
    return _dedupe([token for token in tags if token not in blocked])[:12]


def _source_label(source_type: str) -> str:
    """confidence 계산용 source label."""
    mapping = {
        "feedback": "feedback",
        "adoption": "adoption",
        "selection_pressure": "selection_pressure",
        "session": "session",
        "report": "report",
    }
    return mapping.get(source_type, source_type)


@dataclass
class ProjectLesson:
    """프로젝트에서 재사용할 수 있는 lesson 한 건."""

    lesson_id: str
    kind: str
    text: str
    confidence: float
    source_refs: list[str]
    evidence_count: int
    tags: list[str]
    created_at: str | None
    updated_at: str | None
    status: str
    pinned: bool = False
    suppressed: bool = False
    human_note: str | None = None

    def to_dict(self, *, include_overrides: bool = True) -> dict:
        """직렬화용 dict."""
        payload = {
            "lesson_id": self.lesson_id,
            "kind": self.kind,
            "text": self.text,
            "confidence": self.confidence,
            "source_refs": list(self.source_refs),
            "evidence_count": self.evidence_count,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
        }
        if include_overrides:
            payload["pinned"] = self.pinned
            payload["suppressed"] = self.suppressed
            payload["human_note"] = self.human_note
        return payload


@dataclass
class ProjectMemory:
    """프로젝트 lessons 인덱스."""

    schema_version: str
    generated_at: str
    project_name: str | None
    lessons: list[ProjectLesson]
    sources_scanned: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "project_name": self.project_name,
            "lessons": [item.to_dict(include_overrides=False) for item in self.lessons],
            "sources_scanned": self.sources_scanned,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class ProjectMemoryStore:
    """lessons.yaml 저장/로드 도구."""

    def save(self, memory: ProjectMemory, path: Path) -> Path:
        """메모리 인덱스를 YAML로 저장한다."""
        payload = memory.to_dict()
        _atomic_write_text(
            path,
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        )
        return path

    def load(self, path: Path) -> ProjectMemory:
        """저장된 lessons.yaml을 로드한다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("project memory YAML 최상위는 dict여야 합니다.")
        lessons_payload = payload.get("lessons", [])
        lessons: list[ProjectLesson] = []
        for item in lessons_payload if isinstance(lessons_payload, list) else []:
            if not isinstance(item, dict):
                continue
            lessons.append(
                ProjectLesson(
                    lesson_id=str(item.get("lesson_id", "")),
                    kind=str(item.get("kind", "successful_pattern")),
                    text=str(item.get("text", "")),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    source_refs=[str(ref) for ref in item.get("source_refs", []) if ref],
                    evidence_count=int(item.get("evidence_count", 0) or 0),
                    tags=[str(tag) for tag in item.get("tags", []) if tag],
                    created_at=item.get("created_at"),
                    updated_at=item.get("updated_at"),
                    status=str(item.get("status", "active")),
                    pinned=bool(item.get("pinned", False)),
                    suppressed=bool(item.get("suppressed", False)),
                    human_note=(
                        str(item.get("human_note"))
                        if item.get("human_note") is not None
                        else None
                    ),
                )
            )
        return ProjectMemory(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            project_name=(
                str(payload.get("project_name"))
                if payload.get("project_name") is not None
                else None
            ),
            lessons=lessons,
            sources_scanned=int(payload.get("sources_scanned", 0) or 0),
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


def merge_memory_overrides(
    memory: ProjectMemory,
    overrides: MemoryOverrides,
) -> ProjectMemory:
    """derived lessons에 사용자 override를 읽기 전용으로 반영한다."""
    override_map = overrides.overrides if isinstance(overrides.overrides, dict) else {}
    lessons: list[ProjectLesson] = []
    warnings = list(memory.warnings)
    known_ids = {lesson.lesson_id for lesson in memory.lessons}

    for lesson_id in sorted(set(override_map) - known_ids):
        warnings.append(f"알 수 없는 lesson override를 건너뜁니다: {lesson_id}")

    for lesson in memory.lessons:
        override = override_map.get(lesson.lesson_id)
        pinned = bool(override.pinned) if override else False
        suppressed = bool(override.suppressed) if override else False
        effective_status = "suppressed" if suppressed else str(lesson.status)
        lessons.append(
            ProjectLesson(
                lesson_id=lesson.lesson_id,
                kind=lesson.kind,
                text=lesson.text,
                confidence=lesson.confidence,
                source_refs=list(lesson.source_refs),
                evidence_count=lesson.evidence_count,
                tags=list(lesson.tags),
                created_at=lesson.created_at,
                updated_at=override.updated_at if override and override.updated_at else lesson.updated_at,
                status=effective_status,
                pinned=pinned,
                suppressed=suppressed,
                human_note=override.note if override else None,
            )
        )

    return ProjectMemory(
        schema_version=memory.schema_version,
        generated_at=memory.generated_at,
        project_name=memory.project_name,
        lessons=lessons,
        sources_scanned=memory.sources_scanned,
        warnings=_dedupe([*warnings, *list(overrides.warnings)]),
        errors=_dedupe([*list(memory.errors), *list(overrides.errors)]),
    )


def find_memory_lesson(memory: ProjectMemory, lesson_id: str) -> ProjectLesson | None:
    """lesson id로 lesson을 찾는다."""
    for lesson in memory.lessons:
        if lesson.lesson_id == lesson_id:
            return lesson
    return None


def list_memory_lessons(
    memory: ProjectMemory,
    *,
    include_suppressed: bool = False,
    kind: str | None = None,
    tag: str | None = None,
    limit: int | None = None,
) -> list[ProjectLesson]:
    """review/list 화면용 lesson 목록을 정렬해서 반환한다."""
    filtered: list[ProjectLesson] = []
    wanted_kind = str(kind).strip() if kind else None
    wanted_tag = str(tag).strip().lower() if tag else None

    for lesson in memory.lessons:
        if lesson.suppressed and not include_suppressed:
            continue
        if wanted_kind and lesson.kind != wanted_kind:
            continue
        if wanted_tag and wanted_tag not in {str(item).lower() for item in lesson.tags}:
            continue
        filtered.append(lesson)

    filtered.sort(
        key=lambda item: (
            0 if item.pinned else 1,
            2 if item.suppressed else 1 if item.status != "active" else 0,
            -item.confidence,
            -item.evidence_count,
            item.lesson_id,
        )
    )
    if limit is not None:
        return filtered[: max(0, int(limit))]
    return filtered


def memory_override_counts(memory: ProjectMemory) -> dict[str, int]:
    """override 관련 개수를 요약한다."""
    pinned = sum(1 for lesson in memory.lessons if lesson.pinned and not lesson.suppressed)
    suppressed = sum(1 for lesson in memory.lessons if lesson.suppressed)
    active = sum(1 for lesson in memory.lessons if not lesson.suppressed and lesson.status == "active")
    return {
        "active": active,
        "pinned": pinned,
        "suppressed": suppressed,
        "total": len(memory.lessons),
    }


class ProjectMemoryBuilder:
    """완료된 artifact에서 lesson을 추출해 프로젝트 기억으로 재구성한다."""

    def build(self, project_root: Path, limit: int | None = None) -> ProjectMemory:
        """프로젝트 artifact를 스캔해 derived memory를 만든다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        generated_at = _now()
        lesson_limit = max(1, int(limit or DEFAULT_LESSON_LIMIT))
        aggregates: dict[str, dict] = {}
        sources_scanned = 0

        sources_scanned += self._scan_feedback(root, aggregates, warnings)
        sources_scanned += self._scan_adoptions(root, aggregates, warnings)
        sources_scanned += self._scan_selection_pressure(root, aggregates, warnings)
        sources_scanned += self._scan_sessions(root, aggregates, warnings)
        sources_scanned += self._scan_reports(root, aggregates, warnings)

        lessons: list[ProjectLesson] = []
        for normalized_text in sorted(aggregates):
            aggregate = aggregates[normalized_text]
            evidence_count = len(aggregate["source_refs"])
            confidence = self._compute_confidence(
                evidence_count=evidence_count,
                kind=aggregate["kind"],
                source_types=aggregate["source_types"],
            )
            lesson = ProjectLesson(
                lesson_id=f"lesson-{_slugify(normalized_text)}",
                kind=aggregate["kind"],
                text=aggregate["text"],
                confidence=confidence,
                source_refs=sorted(aggregate["source_refs"]),
                evidence_count=evidence_count,
                tags=_tags_for_lesson(
                    aggregate["text"],
                    sorted(aggregate["source_refs"]),
                    extra_tags=sorted(aggregate["tags"]),
                ),
                created_at=generated_at,
                updated_at=generated_at,
                status="active",
            )
            lessons.append(lesson)

        lessons.sort(
            key=lambda item: (-item.confidence, -item.evidence_count, item.lesson_id)
        )

        project_payload = _load_yaml(root / ".cambrian" / "project.yaml", warnings) or {}
        project_name = None
        if isinstance(project_payload.get("project"), dict):
            raw_name = project_payload["project"].get("name")
            if raw_name:
                project_name = str(raw_name)

        return ProjectMemory(
            schema_version=SCHEMA_VERSION,
            generated_at=generated_at,
            project_name=project_name or root.name,
            lessons=lessons[:lesson_limit],
            sources_scanned=sources_scanned,
            warnings=warnings,
            errors=errors,
        )

    def _scan_feedback(self, root: Path, aggregates: dict[str, dict], warnings: list[str]) -> int:
        """feedback record에서 lesson을 추출한다."""
        feedback_dir = root / ".cambrian" / "feedback"
        if not feedback_dir.exists():
            return 0

        scanned = 0
        for path in sorted(feedback_dir.glob("feedback_*.json")):
            payload = _load_json(path, warnings)
            scanned += 1
            if not payload:
                continue
            source_ref = _relative(path, root)

            for item in payload.get("keep_patterns", []) or []:
                text = _friendly_sentence(str(item))
                kind = _kind_from_text("successful_pattern", text)
                self._add_candidate(
                    aggregates,
                    kind=kind,
                    text=text,
                    source_ref=source_ref,
                    source_type="feedback",
                )
            for item in payload.get("avoid_patterns", []) or []:
                self._add_candidate(
                    aggregates,
                    kind="avoid_pattern",
                    text=_friendly_sentence(str(item)),
                    source_ref=source_ref,
                    source_type="feedback",
                )
            for item in payload.get("missing_evidence", []) or []:
                self._add_candidate(
                    aggregates,
                    kind="missing_evidence",
                    text=_friendly_sentence(str(item)),
                    source_ref=source_ref,
                    source_type="feedback",
                )
            for item in payload.get("suggested_next_actions", []) or []:
                text = str(item or "").strip()
                if not text:
                    continue
                self._add_candidate(
                    aggregates,
                    kind="next_action",
                    text=f"Consider next step: {text}",
                    source_ref=source_ref,
                    source_type="feedback",
                )
            for item in payload.get("outcome_reasons", []) or []:
                self._add_candidate(
                    aggregates,
                    kind="risk_warning",
                    text=_friendly_sentence(str(item)),
                    source_ref=source_ref,
                    source_type="feedback",
                )
        return scanned

    def _scan_adoptions(self, root: Path, aggregates: dict[str, dict], warnings: list[str]) -> int:
        """adoption record에서 lesson을 추출한다."""
        adoptions_dir = root / ".cambrian" / "adoptions"
        if not adoptions_dir.exists():
            return 0

        scanned = 0
        for path in sorted(adoptions_dir.glob("adoption_*.json")):
            payload = _load_json(path, warnings)
            scanned += 1
            if not payload:
                continue
            source_ref = _relative(path, root)
            target_path = str(payload.get("target_path", "") or "").strip()
            human_reason = str(payload.get("human_reason", "") or "").strip()
            post_apply_tests = payload.get("post_apply_tests", {})
            if not isinstance(post_apply_tests, dict):
                post_apply_tests = {}
            tests_executed = [str(item) for item in post_apply_tests.get("tests_executed", []) if item]
            failed = int(post_apply_tests.get("failed", 0) or 0)

            if human_reason:
                self._add_candidate(
                    aggregates,
                    kind="adoption_reason",
                    text=f"Patch was adopted because {human_reason}",
                    source_ref=source_ref,
                    source_type="adoption",
                    extra_tags=_extract_tokens(target_path),
                )
            if target_path:
                self._add_candidate(
                    aggregates,
                    kind="successful_pattern",
                    text=f"Validated patch workflow succeeded for {target_path}",
                    source_ref=source_ref,
                    source_type="adoption",
                    extra_tags=_extract_tokens(target_path),
                )
            if target_path and tests_executed and failed == 0:
                self._add_candidate(
                    aggregates,
                    kind="test_practice",
                    text=f"Run {tests_executed[0]} before patches touching {target_path}",
                    source_ref=source_ref,
                    source_type="adoption",
                    extra_tags=_extract_tokens(target_path) + _extract_tokens(tests_executed[0]),
                )
        return scanned

    def _scan_selection_pressure(self, root: Path, aggregates: dict[str, dict], warnings: list[str]) -> int:
        """selection pressure에서 lesson을 추출한다."""
        pressure_path = root / ".cambrian" / "evolution" / "_selection_pressure.yaml"
        if not pressure_path.exists():
            return 0
        payload = _load_yaml(pressure_path, warnings)
        if not payload:
            return 1
        source_ref = _relative(pressure_path, root)

        for item in payload.get("keep_patterns", []) or []:
            text = _friendly_sentence(str(item))
            kind = _kind_from_text("successful_pattern", text)
            self._add_candidate(
                aggregates,
                kind=kind,
                text=text,
                source_ref=source_ref,
                source_type="selection_pressure",
            )
        for item in payload.get("avoid_patterns", []) or []:
            self._add_candidate(
                aggregates,
                kind="avoid_pattern",
                text=_friendly_sentence(str(item)),
                source_ref=source_ref,
                source_type="selection_pressure",
            )
        for item in payload.get("risk_flags", []) or []:
            raw_flag = str(item or "").strip()
            if not raw_flag:
                continue
            text = _RISK_FLAG_TEXT.get(
                raw_flag,
                f"Risk observed: {raw_flag.replace('_', ' ')}",
            )
            self._add_candidate(
                aggregates,
                kind="risk_warning",
                text=text,
                source_ref=source_ref,
                source_type="selection_pressure",
            )
        for item in payload.get("missing_evidence_warnings", []) or []:
            self._add_candidate(
                aggregates,
                kind="missing_evidence",
                text=_friendly_sentence(str(item)),
                source_ref=source_ref,
                source_type="selection_pressure",
            )
        return 1

    def _scan_sessions(self, root: Path, aggregates: dict[str, dict], warnings: list[str]) -> int:
        """do session에서 lesson을 추출한다."""
        sessions_dir = root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return 0

        scanned = 0
        for path in sorted(sessions_dir.glob("do_session_*.yaml")):
            payload = _load_yaml(path, warnings)
            scanned += 1
            if not payload:
                continue
            source_ref = _relative(path, root)
            current_stage = str(payload.get("current_stage", "") or payload.get("status", "") or "")
            user_request = str(payload.get("user_request", "") or "").strip()
            next_actions = [str(item) for item in payload.get("next_actions", []) if item]

            if current_stage == "adopted" and user_request:
                self._add_candidate(
                    aggregates,
                    kind="successful_pattern",
                    text=f'Completed work for "{user_request}" reached adoption',
                    source_ref=source_ref,
                    source_type="session",
                    extra_tags=_extract_tokens(user_request),
                )
            if current_stage in {"blocked", "error"} and user_request:
                self._add_candidate(
                    aggregates,
                    kind="risk_warning",
                    text=f'Previous work for "{user_request}" ended as {current_stage}',
                    source_ref=source_ref,
                    source_type="session",
                    extra_tags=_extract_tokens(user_request),
                )
            if next_actions:
                self._add_candidate(
                    aggregates,
                    kind="next_action",
                    text=f"Continue with: {next_actions[0]}",
                    source_ref=source_ref,
                    source_type="session",
                    extra_tags=_extract_tokens(user_request),
                )
        return scanned

    def _scan_reports(self, root: Path, aggregates: dict[str, dict], warnings: list[str]) -> int:
        """brain report에서 lesson을 추출한다."""
        runs_dir = root / ".cambrian" / "brain" / "runs"
        if not runs_dir.exists():
            return 0

        scanned = 0
        for path in sorted(runs_dir.glob("*/report.json")):
            payload = _load_json(path, warnings)
            scanned += 1
            if not payload:
                continue
            source_ref = _relative(path, root)
            diagnostics = payload.get("diagnostics", {})
            if not isinstance(diagnostics, dict):
                diagnostics = {}
            related_tests = [str(item) for item in diagnostics.get("related_tests", []) if item]
            inspected_files = diagnostics.get("inspected_files", [])
            first_source = ""
            if isinstance(inspected_files, list) and inspected_files:
                first_item = inspected_files[0]
                if isinstance(first_item, dict):
                    first_source = str(first_item.get("path", "") or "").strip()
            test_results = diagnostics.get("test_results", {})
            if not isinstance(test_results, dict):
                test_results = {}
            failed = int(test_results.get("failed", 0) or 0)

            if related_tests and first_source:
                self._add_candidate(
                    aggregates,
                    kind="test_practice",
                    text=f"Run {related_tests[0]} before patches touching {first_source}",
                    source_ref=source_ref,
                    source_type="report",
                    extra_tags=_extract_tokens(first_source) + _extract_tokens(related_tests[0]),
                )
            if related_tests and failed > 0:
                self._add_candidate(
                    aggregates,
                    kind="risk_warning",
                    text=f"Related test failed during diagnosis: {related_tests[0]}",
                    source_ref=source_ref,
                    source_type="report",
                    extra_tags=_extract_tokens(related_tests[0]),
                )

            feedback_context = payload.get("feedback_context", {})
            if isinstance(feedback_context, dict):
                lessons_map = feedback_context.get("lessons", {})
                if isinstance(lessons_map, dict):
                    for item in lessons_map.get("keep", []) or []:
                        self._add_candidate(
                            aggregates,
                            kind=_kind_from_text("successful_pattern", str(item)),
                            text=_friendly_sentence(str(item)),
                            source_ref=source_ref,
                            source_type="report",
                        )
                    for item in lessons_map.get("avoid", []) or []:
                        self._add_candidate(
                            aggregates,
                            kind="avoid_pattern",
                            text=_friendly_sentence(str(item)),
                            source_ref=source_ref,
                            source_type="report",
                        )
                    for item in lessons_map.get("missing_evidence", []) or []:
                        self._add_candidate(
                            aggregates,
                            kind="missing_evidence",
                            text=_friendly_sentence(str(item)),
                            source_ref=source_ref,
                            source_type="report",
                        )
                for item in feedback_context.get("suggested_next_actions", []) or []:
                    self._add_candidate(
                        aggregates,
                        kind="next_action",
                        text=f"Consider next step: {item}",
                        source_ref=source_ref,
                        source_type="report",
                    )

            pressure_context = payload.get("selection_pressure_context", {})
            if isinstance(pressure_context, dict):
                for item in pressure_context.get("risk_flags", []) or []:
                    raw_flag = str(item or "").strip()
                    if not raw_flag:
                        continue
                    self._add_candidate(
                        aggregates,
                        kind="risk_warning",
                        text=_RISK_FLAG_TEXT.get(
                            raw_flag,
                            f"Risk observed: {raw_flag.replace('_', ' ')}",
                        ),
                        source_ref=source_ref,
                        source_type="report",
                    )
                for item in pressure_context.get("avoid_patterns", []) or []:
                    self._add_candidate(
                        aggregates,
                        kind="avoid_pattern",
                        text=_friendly_sentence(str(item)),
                        source_ref=source_ref,
                        source_type="report",
                    )

            competitive = payload.get("competitive_generation", {})
            if isinstance(competitive, dict) and str(competitive.get("status", "")) == "no_winner":
                self._add_candidate(
                    aggregates,
                    kind="risk_warning",
                    text="Competitive generation completed without a winner.",
                    source_ref=source_ref,
                    source_type="report",
                )

            hypothesis = payload.get("hypothesis_evaluation", {})
            if isinstance(hypothesis, dict) and str(hypothesis.get("status", "")) == "contradicted":
                statement = str(hypothesis.get("statement", "") or "").strip()
                text = "Avoid contradicted hypothesis in similar runs"
                if statement:
                    text = f"Avoid contradicted hypothesis: {statement}"
                self._add_candidate(
                    aggregates,
                    kind="avoid_pattern",
                    text=text,
                    source_ref=source_ref,
                    source_type="report",
                )
        return scanned

    def _add_candidate(
        self,
        aggregates: dict[str, dict],
        *,
        kind: str,
        text: str,
        source_ref: str,
        source_type: str,
        extra_tags: list[str] | None = None,
    ) -> None:
        """lesson 후보를 dedupe 테이블에 누적한다."""
        friendly = _friendly_sentence(text)
        normalized = _normalize_text(friendly)
        if not normalized:
            return

        candidate_kind = _kind_from_text(kind, friendly)
        aggregate = aggregates.get(normalized)
        if aggregate is None:
            aggregates[normalized] = {
                "kind": candidate_kind,
                "text": friendly,
                "source_refs": {source_ref},
                "source_types": {_source_label(source_type)},
                "tags": set(extra_tags or []),
            }
            return

        if _KIND_PRIORITY.get(candidate_kind, 99) < _KIND_PRIORITY.get(aggregate["kind"], 99):
            aggregate["kind"] = candidate_kind
        aggregate["source_refs"].add(source_ref)
        aggregate["source_types"].add(_source_label(source_type))
        aggregate["tags"].update(extra_tags or [])

    @staticmethod
    def _compute_confidence(*, evidence_count: int, kind: str, source_types: set[str]) -> float:
        """evidence와 source 성격으로 confidence를 계산한다."""
        confidence = 0.5
        confidence += min(max(evidence_count - 1, 0), 3) * 0.1
        if "adoption" in source_types:
            confidence += 0.15
        if "feedback" in source_types:
            confidence += 0.1
        if kind in {"avoid_pattern", "risk_warning"} and (
            "selection_pressure" in source_types or "report" in source_types
        ):
            confidence += 0.1
        return round(max(0.0, min(confidence, 1.0)), 2)


def default_memory_path(project_root: Path) -> Path:
    """프로젝트 기본 lessons.yaml 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "memory" / "lessons.yaml"


def load_project_memory(project_root: Path) -> ProjectMemory | None:
    """기본 lessons.yaml이 있으면 로드한다."""
    root = Path(project_root).resolve()
    path = default_memory_path(root)
    if not path.exists():
        return None
    try:
        memory = ProjectMemoryStore().load(path)
        overrides = load_memory_overrides(root)
        return merge_memory_overrides(memory, overrides)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        logger.warning("project memory load failed: %s (%s)", path, exc)
        return None


def match_relevant_lessons(
    memory: ProjectMemory,
    user_request: str,
    limit: int = 3,
) -> list[dict]:
    """요청과 겹치는 lesson을 간단한 토큰 매칭으로 고른다."""
    request_tokens = set(_expand_request_tokens(_extract_tokens(user_request)))
    if not request_tokens:
        return []

    ranked: list[tuple[float, ProjectLesson, str]] = []
    for lesson in memory.lessons:
        if lesson.status != "active":
            continue
        lesson_tokens = set(lesson.tags) | set(_extract_tokens(lesson.text))
        matched = sorted(request_tokens & lesson_tokens)
        if not matched:
            continue
        score = float(len(matched)) + float(lesson.confidence)
        ranked.append((score, lesson, matched[0]))

    ranked.sort(key=lambda item: (-item[0], -item[1].confidence, item[1].lesson_id))
    results: list[dict] = []
    for _, lesson, token in ranked[: max(1, limit)]:
        results.append(
            {
                "lesson_id": lesson.lesson_id,
                "kind": lesson.kind,
                "text": lesson.text,
                "reason": f"matched request term: {token}",
                "tags": list(lesson.tags),
                "pinned": lesson.pinned,
                "suppressed": lesson.suppressed,
                "human_note": lesson.human_note,
            }
        )
    return results


def build_memory_context(project_root: Path, user_request: str, limit: int = 3) -> dict:
    """do/run에서 쓸 관련 lesson 컨텍스트를 만든다."""
    root = Path(project_root).resolve()
    lessons_path = default_memory_path(root)
    overrides_path = default_memory_overrides_path(root)
    memory = load_project_memory(root)
    if memory is None:
        return {
            "enabled": False,
            "lessons_path": _relative(lessons_path, root),
            "overrides_path": _relative(overrides_path, root),
            "relevant_lessons": [],
            "omitted": {"suppressed_count": 0},
        }
    counts = memory_override_counts(memory)
    return {
        "enabled": True,
        "lessons_path": _relative(lessons_path, root),
        "overrides_path": _relative(overrides_path, root),
        "lesson_count": len(memory.lessons),
        "relevant_lessons": match_relevant_lessons(memory, user_request, limit=limit),
        "omitted": {"suppressed_count": counts["suppressed"]},
    }


def render_memory_rebuild_summary(memory: ProjectMemory, output_path: str) -> str:
    """memory rebuild 결과를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Cambrian rebuilt project memory.",
        "",
        "Lessons:",
        f"  active: {len(memory.lessons)}",
        f"  sources scanned: {memory.sources_scanned}",
        f"  output: {output_path}",
    ]
    if memory.lessons:
        lines.extend(["", "Top lessons:"])
        for lesson in memory.lessons[:3]:
            lines.append(f"  - {lesson.text}")
    if memory.warnings:
        lines.extend(["", "Warnings:"])
        for item in memory.warnings[:5]:
            lines.append(f"  - {item}")
    lines.extend(["", "Next:", "  cambrian memory list"])
    return "\n".join(lines)


def render_memory_list(
    memory: ProjectMemory,
    lessons: list[ProjectLesson],
    *,
    hygiene_map: dict[str, dict] | None = None,
) -> str:
    """memory list 화면을 렌더링한다."""
    lines = [
        "Project Memory",
        "==================================================",
    ]
    if not lessons:
        lines.extend(
            [
                "No lessons built yet.",
                "",
                "Next:",
                "  cambrian memory rebuild",
            ]
        )
        return "\n".join(lines)

    for index, lesson in enumerate(lessons, start=1):
        badges: list[str] = []
        if lesson.pinned and not lesson.suppressed:
            badges.append("pinned")
        if lesson.suppressed:
            badges.append("suppressed")
        badge_text = "".join(f"[{badge}]" for badge in badges)
        lines.extend(
            [
                f"{index}. {badge_text}[{lesson.kind}] {lesson.text}" if badge_text else f"{index}. [{lesson.kind}] {lesson.text}",
                f"   confidence: {lesson.confidence:.2f}",
                f"   evidence: {lesson.evidence_count}",
            ]
        )
        if lesson.human_note:
            lines.append(f"   note: {lesson.human_note}")
        hygiene_item = hygiene_map.get(lesson.lesson_id) if isinstance(hygiene_map, dict) else None
        if isinstance(hygiene_item, dict) and hygiene_item.get("status"):
            lines.append(f"   hygiene: {hygiene_item.get('status')}")
            reasons = hygiene_item.get("reasons", [])
            if isinstance(reasons, list) and reasons:
                lines.append(f"   why: {reasons[0]}")
    if memory.warnings:
        lines.extend(["", "Warnings:"])
        for item in memory.warnings[:5]:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def render_memory_review(
    memory: ProjectMemory,
    *,
    include_suppressed: bool = False,
    hygiene_map: dict[str, dict] | None = None,
) -> str:
    """memory review 화면을 렌더링한다."""
    counts = memory_override_counts(memory)
    pinned = [lesson for lesson in memory.lessons if lesson.pinned and not lesson.suppressed]
    active = [
        lesson
        for lesson in memory.lessons
        if not lesson.suppressed and lesson.status == "active" and not lesson.pinned
    ]
    suppressed = [lesson for lesson in memory.lessons if lesson.suppressed]
    lines = [
        "Project Memory Review",
        "==================================================",
        "",
        f"Active lessons: {counts['active']}",
        f"Pinned: {counts['pinned']}",
        f"Suppressed: {counts['suppressed']}",
    ]
    if pinned:
        lines.extend(["", "Pinned:"])
        for lesson in pinned[:5]:
            lines.append(f"  [{lesson.kind}] {lesson.text}")
            lines.append(f"    id: {lesson.lesson_id}")
            if lesson.human_note:
                lines.append(f"    note: {lesson.human_note}")
            hygiene_item = hygiene_map.get(lesson.lesson_id) if isinstance(hygiene_map, dict) else None
            if isinstance(hygiene_item, dict) and hygiene_item.get("status"):
                lines.append(f"    hygiene: {hygiene_item.get('status')}")
    if active:
        lines.extend(["", "Active:"])
        for lesson in active[:5]:
            lines.append(f"  [{lesson.kind}] {lesson.text}")
            lines.append(f"    id: {lesson.lesson_id}")
            hygiene_item = hygiene_map.get(lesson.lesson_id) if isinstance(hygiene_map, dict) else None
            if isinstance(hygiene_item, dict) and hygiene_item.get("status"):
                lines.append(f"    hygiene: {hygiene_item.get('status')}")
    if include_suppressed:
        lines.extend(["", "Suppressed:"])
        if suppressed:
            for lesson in suppressed[:5]:
                lines.append(f"  [{lesson.kind}] {lesson.text}")
                lines.append(f"    id: {lesson.lesson_id}")
                if lesson.human_note:
                    lines.append(f"    note: {lesson.human_note}")
                hygiene_item = hygiene_map.get(lesson.lesson_id) if isinstance(hygiene_map, dict) else None
                if isinstance(hygiene_item, dict) and hygiene_item.get("status"):
                    lines.append(f"    hygiene: {hygiene_item.get('status')}")
        else:
            lines.append("  none")
    elif counts["suppressed"] > 0:
        lines.extend(["", "Suppressed:", "  hidden by default. Use --include-suppressed to view."])
    lines.extend([
        "",
        "Commands:",
        "  cambrian memory pin <lesson-id>",
        "  cambrian memory suppress <lesson-id>",
        "  cambrian memory note <lesson-id> --note \"...\"",
    ])
    return "\n".join(lines)


def render_memory_show(
    lesson: ProjectLesson,
    *,
    hygiene_item: dict | None = None,
) -> str:
    """lesson 상세를 렌더링한다."""
    lines = [
        "Project Lesson",
        "==================================================",
        f"ID: {lesson.lesson_id}",
        f"Kind: {lesson.kind}",
        f"Status: {lesson.status}",
        f"Pinned: {'yes' if lesson.pinned else 'no'}",
        f"Suppressed: {'yes' if lesson.suppressed else 'no'}",
        f"Confidence: {lesson.confidence:.2f}",
        f"Evidence: {lesson.evidence_count}",
        "",
        "Text:",
        f"  {lesson.text}",
    ]
    if lesson.human_note:
        lines.extend(["", "Human note:", f"  {lesson.human_note}"])
    lines.extend(["", "Tags:"])
    if lesson.tags:
        for tag in lesson.tags:
            lines.append(f"  - {tag}")
    else:
        lines.append("  - none")
    lines.extend(["", "Source refs:"])
    for ref in lesson.source_refs:
        lines.append(f"  - {ref}")
    if isinstance(hygiene_item, dict) and hygiene_item.get("status"):
        lines.extend(["", "Hygiene:", f"  status: {hygiene_item.get('status')}"])
        reasons = hygiene_item.get("reasons", [])
        if isinstance(reasons, list) and reasons:
            lines.append("  reasons:")
            for item in reasons[:5]:
                lines.append(f"    - {item}")
    return "\n".join(lines)
