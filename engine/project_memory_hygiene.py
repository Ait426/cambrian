"""프로젝트 기억 hygiene 검사 도구."""

from __future__ import annotations

import json
import logging
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_memory import ProjectLesson, default_memory_path, load_project_memory
from engine.project_memory_overrides import default_memory_overrides_path

logger = logging.getLogger(__name__)


SCHEMA_VERSION = "1.0.0"
_PATH_PATTERN = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|ts|tsx|js|md|yaml|yml))")


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


def _load_json(path: Path, warnings: list[str]) -> dict | None:
    """JSON 파일을 안전하게 읽는다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"JSON 읽기 실패: {path} ({exc})")
        logger.warning("JSON 읽기 실패: %s (%s)", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _load_yaml(path: Path, warnings: list[str]) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        warnings.append(f"YAML 읽기 실패: {path} ({exc})")
        logger.warning("YAML 읽기 실패: %s (%s)", path, exc)
        return None
    return payload if isinstance(payload, dict) else None


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


def _extract_tokens(text: str) -> list[str]:
    """문장에서 비교용 토큰을 뽑는다."""
    return _dedupe(re.findall(r"[a-z0-9_./-]+|[가-힣]+", str(text or "").lower()))


def _normalize_text(text: str) -> str:
    """충돌 판정용 정규화 문자열을 만든다."""
    return " ".join(str(text or "").lower().split()).strip(" .,!?:;")


def default_memory_hygiene_path(project_root: Path) -> Path:
    """프로젝트 기본 hygiene.yaml 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "memory" / "hygiene.yaml"


@dataclass
class LessonHygieneItem:
    """단일 lesson의 hygiene 상태."""

    lesson_id: str
    text: str
    kind: str
    status: str
    severity: str
    reasons: list[str]
    suggested_actions: list[str]
    pinned: bool
    suppressed: bool
    confidence: float
    evidence_count: int
    source_refs: list[str]
    missing_source_refs: list[str]
    referenced_paths: list[str]
    missing_referenced_paths: list[str]
    conflict_refs: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class MemoryHygieneReport:
    """프로젝트 memory hygiene 리포트."""

    schema_version: str
    generated_at: str
    lessons_path: str
    overrides_path: str | None
    summary: dict
    items: list[LessonHygieneItem]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "lessons_path": self.lessons_path,
            "overrides_path": self.overrides_path,
            "summary": dict(self.summary),
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class MemoryHygieneStore:
    """hygiene report 저장/로드 도구."""

    def save(self, report: MemoryHygieneReport, path: Path) -> Path:
        """hygiene report를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(report.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> MemoryHygieneReport:
        """저장된 hygiene report를 로드한다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("memory hygiene YAML 최상위는 dict여야 합니다.")
        items: list[LessonHygieneItem] = []
        for item in payload.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            items.append(
                LessonHygieneItem(
                    lesson_id=str(item.get("lesson_id", "")),
                    text=str(item.get("text", "")),
                    kind=str(item.get("kind", "")),
                    status=str(item.get("status", "watch")),
                    severity=str(item.get("severity", "info")),
                    reasons=[str(reason) for reason in item.get("reasons", []) if reason],
                    suggested_actions=[str(action) for action in item.get("suggested_actions", []) if action],
                    pinned=bool(item.get("pinned", False)),
                    suppressed=bool(item.get("suppressed", False)),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    evidence_count=int(item.get("evidence_count", 0) or 0),
                    source_refs=[str(ref) for ref in item.get("source_refs", []) if ref],
                    missing_source_refs=[str(ref) for ref in item.get("missing_source_refs", []) if ref],
                    referenced_paths=[str(ref) for ref in item.get("referenced_paths", []) if ref],
                    missing_referenced_paths=[str(ref) for ref in item.get("missing_referenced_paths", []) if ref],
                    conflict_refs=[str(ref) for ref in item.get("conflict_refs", []) if ref],
                    warnings=[str(warning) for warning in item.get("warnings", []) if warning],
                )
            )
        return MemoryHygieneReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            lessons_path=str(payload.get("lessons_path", "")),
            overrides_path=str(payload.get("overrides_path")) if payload.get("overrides_path") is not None else None,
            summary=dict(payload.get("summary", {})) if isinstance(payload.get("summary"), dict) else {},
            items=items,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


class MemoryHygieneChecker:
    """프로젝트 memory hygiene를 점검한다."""

    def check(
        self,
        project_root: Path,
        lessons_path: Path | None = None,
        overrides_path: Path | None = None,
    ) -> MemoryHygieneReport:
        """현재 lessons와 프로젝트 상태를 읽어 hygiene report를 만든다."""
        root = Path(project_root).resolve()
        lessons_file = Path(lessons_path).resolve() if lessons_path is not None else default_memory_path(root)
        overrides_file = Path(overrides_path).resolve() if overrides_path is not None else default_memory_overrides_path(root)
        warnings: list[str] = []
        errors: list[str] = []

        memory = load_project_memory(root)
        if memory is None:
            warnings.append(f"프로젝트 기억을 찾지 못했습니다: {lessons_file}")
            return MemoryHygieneReport(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                lessons_path=_relative(lessons_file, root),
                overrides_path=_relative(overrides_file, root),
                summary={
                    "total": 0,
                    "fresh": 0,
                    "watch": 0,
                    "stale": 0,
                    "conflicting": 0,
                    "orphaned": 0,
                    "suppressed": 0,
                },
                items=[],
                warnings=warnings,
                errors=errors,
            )

        adoption_index = self._build_adoption_index(root, warnings)
        success_index = self._build_success_index(memory)
        generated_at = _now()
        items: list[LessonHygieneItem] = []

        for lesson in memory.lessons:
            source_refs = list(lesson.source_refs)
            missing_source_refs = [
                ref for ref in source_refs
                if not self._resolve_source_ref(root, ref).exists()
            ]
            referenced_paths = self._referenced_paths(root, lesson, warnings)
            missing_referenced_paths = [
                ref for ref in referenced_paths
                if not (root / ref).exists()
            ]
            conflict_refs = self._conflict_refs(lesson, adoption_index, success_index)
            status, severity, reasons = self._classify(
                lesson=lesson,
                missing_source_refs=missing_source_refs,
                referenced_paths=referenced_paths,
                missing_referenced_paths=missing_referenced_paths,
                conflict_refs=conflict_refs,
            )
            suggested_actions = self._suggest_actions(lesson.lesson_id, status, lesson.pinned, lesson.suppressed)
            items.append(
                LessonHygieneItem(
                    lesson_id=lesson.lesson_id,
                    text=lesson.text,
                    kind=lesson.kind,
                    status=status,
                    severity=severity,
                    reasons=reasons,
                    suggested_actions=suggested_actions,
                    pinned=lesson.pinned,
                    suppressed=lesson.suppressed,
                    confidence=lesson.confidence,
                    evidence_count=lesson.evidence_count,
                    source_refs=source_refs,
                    missing_source_refs=missing_source_refs,
                    referenced_paths=referenced_paths,
                    missing_referenced_paths=missing_referenced_paths,
                    conflict_refs=conflict_refs,
                    warnings=[],
                )
            )

        summary = {
            "total": len(items),
            "fresh": sum(1 for item in items if item.status == "fresh"),
            "watch": sum(1 for item in items if item.status == "watch"),
            "stale": sum(1 for item in items if item.status == "stale"),
            "conflicting": sum(1 for item in items if item.status == "conflicting"),
            "orphaned": sum(1 for item in items if item.status == "orphaned"),
            "suppressed": sum(1 for item in items if item.status == "suppressed"),
        }
        items.sort(
            key=lambda item: (
                {"high": 0, "warning": 1, "info": 2}.get(item.severity, 3),
                {"conflicting": 0, "orphaned": 1, "stale": 2, "watch": 3, "suppressed": 4, "fresh": 5}.get(item.status, 9),
                item.lesson_id,
            )
        )
        return MemoryHygieneReport(
            schema_version=SCHEMA_VERSION,
            generated_at=generated_at,
            lessons_path=_relative(lessons_file, root),
            overrides_path=_relative(overrides_file, root),
            summary=summary,
            items=items,
            warnings=_dedupe([*warnings, *memory.warnings]),
            errors=_dedupe([*errors, *memory.errors]),
        )

    @staticmethod
    def _resolve_source_ref(project_root: Path, source_ref: str) -> Path:
        """source_ref를 실제 경로로 변환한다."""
        return (project_root / str(source_ref)).resolve()

    def _referenced_paths(self, project_root: Path, lesson: ProjectLesson, warnings: list[str]) -> list[str]:
        """lesson이 암시하는 프로젝트 경로 후보를 추출한다."""
        paths = [match for match in _PATH_PATTERN.findall(lesson.text) if self._is_safe_project_path(match, warnings)]
        for tag in lesson.tags:
            if _PATH_PATTERN.fullmatch(str(tag or "")) and self._is_safe_project_path(str(tag), warnings):
                paths.append(str(tag))
        for source_ref in lesson.source_refs:
            resolved = self._resolve_source_ref(project_root, source_ref)
            if not resolved.exists():
                continue
            payload = self._load_artifact_payload(resolved, warnings)
            if not payload:
                continue
            for candidate in self._artifact_paths(payload):
                if self._is_safe_project_path(candidate, warnings):
                    paths.append(candidate)
        return _dedupe(paths)

    @staticmethod
    def _artifact_paths(payload: dict) -> list[str]:
        """artifact payload에서 경로 후보를 추출한다."""
        candidates: list[str] = []
        for key in ("target_path", "path"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                candidates.append(value)
        for key in ("related_tests", "selected_tests", "selected_sources", "tests"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(str(item) for item in value if item)
        if isinstance(payload.get("diagnostics"), dict):
            diagnostics = payload["diagnostics"]
            candidates.extend(str(item) for item in diagnostics.get("related_tests", []) if item)
            for item in diagnostics.get("inspected_files", []) or []:
                if isinstance(item, dict) and item.get("path"):
                    candidates.append(str(item["path"]))
        return _dedupe(candidates)

    @staticmethod
    def _is_safe_project_path(candidate: str, warnings: list[str]) -> bool:
        """프로젝트 내부 비교용 경로만 허용한다."""
        text = str(candidate or "").strip().replace("\\", "/")
        if not text or text.startswith(".cambrian/"):
            return False
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
            warnings.append(f"절대 경로는 hygiene 경로 비교에서 무시합니다: {text}")
            return False
        if ".." in text.split("/"):
            warnings.append(f"상위 경로 참조는 hygiene 경로 비교에서 무시합니다: {text}")
            return False
        return True

    def _load_artifact_payload(self, path: Path, warnings: list[str]) -> dict | None:
        """artifact payload를 읽는다."""
        if path.suffix == ".json":
            return _load_json(path, warnings)
        if path.suffix in {".yaml", ".yml"}:
            return _load_yaml(path, warnings)
        return None

    def _build_adoption_index(self, project_root: Path, warnings: list[str]) -> list[dict]:
        """최근 adoption을 충돌 검사 인덱스로 만든다."""
        adoptions_dir = project_root / ".cambrian" / "adoptions"
        if not adoptions_dir.exists():
            return []
        items: list[dict] = []
        for path in sorted(adoptions_dir.glob("adoption_*.json")):
            payload = _load_json(path, warnings)
            if not payload:
                continue
            target_path = str(
                payload.get("target_path")
                or payload.get("patch", {}).get("target_path")
                or payload.get("proposal", {}).get("target_path")
                or ""
            ).strip()
            reason_text = str(payload.get("human_reason", "") or "")
            tags = _dedupe(_extract_tokens(reason_text) + _extract_tokens(target_path))
            items.append(
                {
                    "path": _relative(path, project_root),
                    "target_path": target_path,
                    "tags": tags,
                    "text": reason_text,
                }
            )
        return items[-10:]

    @staticmethod
    def _build_success_index(memory) -> dict[str, ProjectLesson]:
        """성공 패턴 인덱스를 만든다."""
        index: dict[str, ProjectLesson] = {}
        for lesson in memory.lessons:
            if lesson.kind != "successful_pattern" or lesson.suppressed:
                continue
            index[_normalize_text(lesson.text)] = lesson
        return index

    def _conflict_refs(
        self,
        lesson: ProjectLesson,
        adoption_index: list[dict],
        success_index: dict[str, ProjectLesson],
    ) -> list[str]:
        """단순 exact rule 기반 conflict ref를 찾는다."""
        if lesson.suppressed:
            return []

        conflict_refs: list[str] = []
        normalized = _normalize_text(lesson.text)
        if lesson.kind == "avoid_pattern":
            success = success_index.get(normalized)
            if success and success.evidence_count > lesson.evidence_count:
                conflict_refs.append(success.lesson_id)

            lesson_tags = set(_extract_tokens(lesson.text) + list(lesson.tags))
            referenced_paths = {
                match for match in _PATH_PATTERN.findall(lesson.text)
            }
            for adoption in adoption_index:
                target_path = str(adoption.get("target_path", "") or "").strip()
                adoption_tags = set(adoption.get("tags", []))
                if target_path and target_path in referenced_paths:
                    conflict_refs.append(str(adoption.get("path")))
                    continue
                if lesson_tags and adoption_tags and lesson_tags.intersection(adoption_tags):
                    if "refactor" in lesson_tags or "리팩터링" in lesson_tags:
                        conflict_refs.append(str(adoption.get("path")))
        return _dedupe(conflict_refs)

    @staticmethod
    def _classify(
        *,
        lesson: ProjectLesson,
        missing_source_refs: list[str],
        referenced_paths: list[str],
        missing_referenced_paths: list[str],
        conflict_refs: list[str],
    ) -> tuple[str, str, list[str]]:
        """lesson hygiene 상태를 분류한다."""
        reasons: list[str] = []

        if lesson.suppressed:
            reasons.append("사용자가 suppress한 lesson입니다.")
            return "suppressed", "info", reasons

        if not lesson.text or not lesson.kind:
            reasons.append("Lesson text 또는 kind가 비어 있습니다.")
            status = "orphaned"
        elif lesson.source_refs and len(missing_source_refs) == len(lesson.source_refs):
            reasons.append("모든 source ref가 현재 존재하지 않습니다.")
            status = "orphaned"
        elif not lesson.source_refs and lesson.evidence_count <= 1:
            reasons.append("source ref가 없고 evidence가 약합니다.")
            status = "orphaned"
        elif missing_referenced_paths:
            for item in missing_referenced_paths:
                reasons.append(f"Referenced path does not exist: {item}")
            status = "stale"
        elif conflict_refs:
            reasons.append("최근 성공 evidence와 충돌 가능성이 있습니다.")
            status = "conflicting"
        elif lesson.confidence < 0.4 and lesson.evidence_count <= 1:
            reasons.append("confidence와 evidence가 모두 약합니다.")
            status = "stale"
        elif lesson.kind == "missing_evidence":
            reasons.append("증거 부족 관련 lesson이라 추적이 필요합니다.")
            status = "watch"
        elif lesson.evidence_count == 1 and lesson.confidence < 0.7:
            reasons.append("evidence가 1건이고 confidence가 낮아 추적이 필요합니다.")
            status = "watch"
        elif missing_source_refs:
            reasons.append("일부 source ref가 사라졌습니다.")
            status = "watch"
        else:
            reasons.append("현재 기준에서 유효한 lesson입니다.")
            status = "fresh"

        if lesson.pinned and status in {"stale", "conflicting", "orphaned"}:
            reasons.insert(0, "Pinned lesson has hygiene issue; review manually.")
            return "watch", "warning", reasons

        severity_map = {
            "fresh": "info",
            "watch": "warning",
            "stale": "high",
            "conflicting": "high",
            "orphaned": "high",
        }
        return status, severity_map.get(status, "info"), reasons

    @staticmethod
    def _suggest_actions(
        lesson_id: str,
        status: str,
        pinned: bool,
        suppressed: bool,
    ) -> list[str]:
        """상태별 추천 액션을 만든다."""
        if suppressed:
            return [f"Run: cambrian memory unsuppress {lesson_id}"]
        if pinned and status == "watch":
            return [
                "Review this pinned lesson manually",
                f"Run: cambrian memory unpin {lesson_id}",
                f"Run: cambrian memory note {lesson_id} --note \"...\"",
            ]
        if status in {"stale", "conflicting", "orphaned"}:
            return [
                "Review this lesson",
                f"Run: cambrian memory suppress {lesson_id}",
            ]
        if status == "watch":
            return ["Review this lesson"]
        return []


def hygiene_index(report: MemoryHygieneReport) -> dict[str, LessonHygieneItem]:
    """lesson_id 기준 hygiene 인덱스를 만든다."""
    return {item.lesson_id: item for item in report.items}


def load_memory_hygiene(project_root: Path) -> MemoryHygieneReport | None:
    """프로젝트 기본 hygiene report를 로드한다."""
    path = default_memory_hygiene_path(project_root)
    if not path.exists():
        return None
    try:
        return MemoryHygieneStore().load(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        logger.warning("memory hygiene load failed: %s (%s)", path, exc)
        return None


def render_memory_hygiene(report: MemoryHygieneReport, *, include_suppressed: bool = False) -> str:
    """hygiene report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Project Memory Hygiene",
        "==================================================",
        "",
        "Summary:",
        f"  fresh       : {report.summary.get('fresh', 0)}",
        f"  watch       : {report.summary.get('watch', 0)}",
        f"  stale       : {report.summary.get('stale', 0)}",
        f"  conflicting : {report.summary.get('conflicting', 0)}",
        f"  orphaned    : {report.summary.get('orphaned', 0)}",
        f"  suppressed  : {report.summary.get('suppressed', 0)}",
    ]
    review_items = [
        item for item in report.items
        if item.status in {"watch", "stale", "conflicting", "orphaned"} or (include_suppressed and item.status == "suppressed")
    ]
    if review_items:
        lines.extend(["", "Needs review:"])
        for item in review_items[:6]:
            lines.append(f"  [{item.status}] {item.text}")
            if item.reasons:
                lines.append(f"    why : {item.reasons[0]}")
            if item.suggested_actions:
                lines.append(f"    next: {item.suggested_actions[0]}")
    if report.warnings:
        lines.extend(["", "Warnings:"])
        for item in report.warnings[:5]:
            lines.append(f"  - {item}")
    lines.extend(["", "Saved:", f"  {report.lessons_path.rsplit('/', 1)[0]}/hygiene.yaml" if report.lessons_path else "  .cambrian/memory/hygiene.yaml"])
    return "\n".join(lines)
