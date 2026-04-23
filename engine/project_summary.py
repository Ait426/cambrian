"""Cambrian 프로젝트 로컬 사용 요약."""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_memory import (
    ProjectLesson,
    default_memory_path,
    load_project_memory,
    memory_override_counts,
)
from engine.project_memory_hygiene import default_memory_hygiene_path, load_memory_hygiene
from engine.project_notes import ProjectNotesStore, default_notes_dir
from engine.project_next import primary_next_command

logger = logging.getLogger(__name__)


SCHEMA_VERSION = "1.0.0"
_TERMINAL_SESSION_STATES = {"adopted", "completed", "closed", "error"}


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
    if not path.exists():
        return None
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
    if not path.exists():
        return None
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


def _latest_files(directory: Path, pattern: str) -> list[Path]:
    """패턴에 맞는 파일을 최신순으로 정렬한다."""
    if not directory.exists():
        return []
    return sorted(
        (item for item in directory.glob(pattern) if item.is_file()),
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )


def _count_if(directory: Path, pattern: str) -> int:
    """디렉터리 안의 파일 개수를 센다."""
    if not directory.exists():
        return 0
    return sum(1 for item in directory.glob(pattern) if item.is_file())


def default_usage_summary_path(project_root: Path) -> Path:
    """기본 usage summary 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "summary" / "usage_summary.yaml"


@dataclass
class UsageSummary:
    """프로젝트 로컬 사용 요약."""

    schema_version: str
    generated_at: str
    project_name: str | None
    counts: dict
    latest: dict
    safety: dict
    memory: dict
    notes: dict
    active_work: list[dict]
    recent_journey: list[dict]
    next_actions: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class ProjectUsageSummaryStore:
    """usage_summary.yaml 저장/로드 도구."""

    def save(self, summary: UsageSummary, path: Path) -> Path:
        """요약을 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(summary.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> UsageSummary:
        """저장된 usage summary를 로드한다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("usage summary YAML 최상위는 dict여야 합니다.")
        return UsageSummary(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            counts=dict(payload.get("counts", {})) if isinstance(payload.get("counts"), dict) else {},
            latest=dict(payload.get("latest", {})) if isinstance(payload.get("latest"), dict) else {},
            safety=dict(payload.get("safety", {})) if isinstance(payload.get("safety"), dict) else {},
            memory=dict(payload.get("memory", {})) if isinstance(payload.get("memory"), dict) else {},
            notes=dict(payload.get("notes", {})) if isinstance(payload.get("notes"), dict) else {},
            active_work=list(payload.get("active_work", [])),
            recent_journey=list(payload.get("recent_journey", [])),
            next_actions=[str(item) for item in payload.get("next_actions", []) if item],
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


class ProjectUsageSummaryBuilder:
    """`.cambrian` 아래 artifact를 읽어 로컬 사용 요약을 만든다."""

    def build(self, project_root: Path, limit: int = 5) -> UsageSummary:
        """프로젝트 artifact를 스캔해 summary를 구성한다."""
        root = Path(project_root).resolve()
        cambrian_dir = root / ".cambrian"
        warnings: list[str] = []
        errors: list[str] = []
        item_limit = max(1, int(limit or 5))

        project_payload = _load_yaml(cambrian_dir / "project.yaml", warnings) or {}
        profile_payload = _load_yaml(cambrian_dir / "profile.yaml", warnings) or {}
        init_report_payload = _load_yaml(cambrian_dir / "init_report.yaml", warnings) or {}

        session_paths = _latest_files(cambrian_dir / "sessions", "do_session_*.yaml")
        request_paths = _latest_files(cambrian_dir / "requests", "request_*.yaml")
        context_paths = _latest_files(cambrian_dir / "context", "context_*.yaml")
        clarification_paths = _latest_files(cambrian_dir / "clarifications", "clarification_*.yaml")
        diagnosis_paths = _latest_files(cambrian_dir / "brain" / "runs", "*/report.json")
        patch_intent_paths = _latest_files(cambrian_dir / "patch_intents", "patch_intent_*.yaml")
        proposal_paths = _latest_files(cambrian_dir / "patches", "patch_proposal_*.yaml")
        adoption_paths = _latest_files(cambrian_dir / "adoptions", "adoption_*.json")
        feedback_paths = _latest_files(cambrian_dir / "feedback", "feedback_*.json")

        session_payloads = self._load_records(session_paths, _load_yaml, warnings)
        request_payloads = self._load_records(request_paths, _load_yaml, warnings)
        context_payloads = self._load_records(context_paths, _load_yaml, warnings)
        clarification_payloads = self._load_records(clarification_paths, _load_yaml, warnings)
        diagnosis_payloads = self._load_records(diagnosis_paths, _load_json, warnings)
        proposal_payloads = self._load_records(proposal_paths, _load_yaml, warnings)
        adoption_payloads = self._load_records(adoption_paths, _load_json, warnings)
        feedback_payloads = self._load_records(feedback_paths, _load_json, warnings)

        counts = self._build_counts(
            session_paths=session_paths,
            session_payloads=session_payloads,
            request_paths=request_paths,
            context_paths=context_paths,
            clarification_paths=clarification_paths,
            diagnosis_payloads=diagnosis_payloads,
            patch_intent_paths=patch_intent_paths,
            proposal_payloads=proposal_payloads,
            adoption_payloads=adoption_payloads,
            feedback_paths=feedback_paths,
            root=root,
        )
        latest = self._build_latest(
            root=root,
            session_payloads=session_payloads,
            session_paths=session_paths,
            proposal_payloads=proposal_payloads,
            proposal_paths=proposal_paths,
            adoption_payloads=adoption_payloads,
            adoption_paths=adoption_paths,
        )
        safety = self._build_safety(
            root=root,
            proposal_payloads=proposal_payloads,
            session_payloads=session_payloads,
            profile_payload=profile_payload,
            init_report_payload=init_report_payload,
            adoption_count=counts["adoptions"],
        )
        memory = self._build_memory(root=root, warnings=warnings)
        counts["lessons"] = int(memory.get("lessons_count", 0) or 0)
        counts["pinned_lessons"] = int(memory.get("pinned_count", 0) or 0)
        counts["suppressed_lessons"] = int(memory.get("suppressed_count", 0) or 0)
        hygiene = memory.get("hygiene", {}) if isinstance(memory, dict) else {}
        counts["hygiene_watch"] = int(hygiene.get("watch", 0) or 0)
        counts["hygiene_stale"] = int(hygiene.get("stale", 0) or 0)
        counts["hygiene_conflicting"] = int(hygiene.get("conflicting", 0) or 0)
        notes = self._build_notes(root=root)
        counts["notes_open"] = int(notes.get("open", 0) or 0)
        counts["notes_resolved"] = int(notes.get("resolved", 0) or 0)
        counts["notes_high_severity"] = int(notes.get("high", 0) or 0)
        counts["notes_success"] = int(notes.get("success", 0) or 0)
        counts["notes_confusion"] = int(notes.get("confusion", 0) or 0)
        counts["notes_bug"] = int(notes.get("bug", 0) or 0)
        counts["notes_idea"] = int(notes.get("idea", 0) or 0)
        counts["notes_friction"] = int(notes.get("friction", 0) or 0)

        active_work = self._build_active_work(
            session_payloads=session_payloads,
            limit=item_limit,
        )
        recent_journey = self._build_recent_journey(
            session_payloads=session_payloads,
            adoption_payloads=adoption_payloads,
            limit=item_limit,
        )
        next_actions = self._build_next_actions(
            initialized=bool(project_payload),
            active_work=active_work,
        )

        project_name = None
        if isinstance(project_payload, dict):
            raw_name = project_payload.get("project", {})
            if isinstance(raw_name, dict):
                project_name = str(raw_name.get("name")) if raw_name.get("name") is not None else None

        return UsageSummary(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            project_name=project_name or root.name,
            counts=counts,
            latest=latest,
            safety=safety,
            memory=memory,
            notes=notes,
            active_work=active_work,
            recent_journey=recent_journey,
            next_actions=next_actions,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    @staticmethod
    def _load_records(paths: list[Path], loader, warnings: list[str]) -> list[tuple[Path, dict]]:
        """artifact 파일 목록을 공통 형식으로 로드한다."""
        records: list[tuple[Path, dict]] = []
        for path in paths:
            payload = loader(path, warnings)
            if payload is None:
                continue
            records.append((path, payload))
        return records

    def _build_counts(
        self,
        *,
        session_paths: list[Path],
        session_payloads: list[tuple[Path, dict]],
        request_paths: list[Path],
        context_paths: list[Path],
        clarification_paths: list[Path],
        diagnosis_payloads: list[tuple[Path, dict]],
        patch_intent_paths: list[Path],
        proposal_payloads: list[tuple[Path, dict]],
        adoption_payloads: list[tuple[Path, dict]],
        feedback_paths: list[Path],
        root: Path,
    ) -> dict:
        """주요 artifact 개수를 계산한다."""
        passed_validations = 0
        failed_validations = 0
        for _, payload in proposal_payloads:
            validation = payload.get("validation", {})
            if not isinstance(validation, dict):
                continue
            status = str(validation.get("status", ""))
            if status == "passed":
                passed_validations += 1
            elif status == "failed":
                failed_validations += 1

        adoption_count = 0
        for _, payload in adoption_payloads:
            if str(payload.get("adoption_status", "")) == "adopted":
                adoption_count += 1

        active_sessions = 0
        for _, payload in session_payloads:
            stage = str(payload.get("current_stage") or payload.get("status") or "")
            if stage not in _TERMINAL_SESSION_STATES:
                active_sessions += 1

        return {
            "sessions": len(session_paths),
            "active_sessions": active_sessions,
            "requests": len(request_paths),
            "context_scans": len(context_paths),
            "clarifications": len(clarification_paths),
            "diagnoses": len(diagnosis_payloads),
            "patch_intents": len(patch_intent_paths),
            "patch_proposals": len(proposal_payloads),
            "patch_validations_passed": passed_validations,
            "patch_validations_failed": failed_validations,
            "adoptions": adoption_count,
            "feedback_records": len(feedback_paths),
            "lessons": 0,
            "pinned_lessons": 0,
            "suppressed_lessons": 0,
            "hygiene_watch": 0,
            "hygiene_stale": 0,
            "hygiene_conflicting": 0,
            "notes_open": 0,
            "notes_resolved": 0,
            "notes_high_severity": 0,
            "notes_success": 0,
            "notes_confusion": 0,
            "notes_bug": 0,
            "notes_idea": 0,
            "notes_friction": 0,
        }

    def _build_latest(
        self,
        *,
        root: Path,
        session_payloads: list[tuple[Path, dict]],
        session_paths: list[Path],
        proposal_payloads: list[tuple[Path, dict]],
        proposal_paths: list[Path],
        adoption_payloads: list[tuple[Path, dict]],
        adoption_paths: list[Path],
    ) -> dict:
        """최신 artifact 포인터를 간단히 요약한다."""
        latest_session: dict = {}
        if session_payloads:
            path, payload = session_payloads[0]
            latest_session = {
                "session_id": payload.get("session_id", path.stem),
                "request": payload.get("user_request", ""),
                "stage": payload.get("current_stage") or payload.get("status", "unknown"),
                "path": _relative(path, root),
            }

        latest_patch_proposal: dict = {}
        if proposal_payloads:
            path, payload = proposal_payloads[0]
            latest_patch_proposal = {
                "proposal_id": payload.get("proposal_id", path.stem),
                "target_path": payload.get("target_path", ""),
                "proposal_status": payload.get("proposal_status", "unknown"),
                "path": _relative(path, root),
            }

        latest_adoption: dict = {}
        latest_pointer = _load_json(root / ".cambrian" / "adoptions" / "_latest.json", [])
        if latest_pointer:
            latest_adoption = {
                "adoption_id": latest_pointer.get("latest_adoption_id", ""),
                "target_path": latest_pointer.get("target_path", ""),
                "path": latest_pointer.get("latest_adoption_path", ""),
            }
        elif adoption_payloads:
            path, payload = adoption_payloads[0]
            latest_adoption = {
                "adoption_id": payload.get("adoption_id", path.stem),
                "target_path": payload.get("target_path", ""),
                "path": _relative(path, root),
            }

        memory = load_project_memory(root)
        latest_lesson = memory.lessons[0].text if memory and memory.lessons else ""

        return {
            "latest_session": latest_session,
            "latest_adoption": latest_adoption,
            "latest_patch_proposal": latest_patch_proposal,
            "latest_lesson": latest_lesson,
        }

    def _build_safety(
        self,
        *,
        root: Path,
        proposal_payloads: list[tuple[Path, dict]],
        session_payloads: list[tuple[Path, dict]],
        profile_payload: dict,
        init_report_payload: dict,
        adoption_count: int,
    ) -> dict:
        """명시적 apply 경계와 검증 상태를 요약한다."""
        unvalidated = 0
        for _, payload in proposal_payloads:
            validation = payload.get("validation", {})
            if not isinstance(validation, dict):
                unvalidated += 1
                continue
            if str(validation.get("status", "")) != "passed":
                unvalidated += 1

        failed_applies = 0
        restored_failures = 0
        for _, payload in session_payloads:
            errors = [str(item) for item in payload.get("errors", []) if item]
            joined = " ".join(errors).lower()
            if "post-apply tests failed" in joined or "restore failed" in joined:
                failed_applies += 1
                if "restore failed" not in joined:
                    restored_failures += 1

        automatic_adoption_enabled = False
        if isinstance(init_report_payload, dict):
            answers = init_report_payload.get("wizard_answers", {})
            if isinstance(answers, dict):
                automatic_adoption_enabled = bool(answers.get("auto_adoption", False))
        if isinstance(profile_payload, dict):
            defaults = profile_payload.get("defaults", {})
            if isinstance(defaults, dict) and str(defaults.get("adoption", "")).lower() == "automatic":
                automatic_adoption_enabled = True

        return {
            "automatic_adoption_enabled": bool(automatic_adoption_enabled),
            "explicit_adoptions": int(adoption_count),
            "latest_pointer_exists": (root / ".cambrian" / "adoptions" / "_latest.json").exists(),
            "failed_apply_records": failed_applies,
            "restored_failures": restored_failures,
            "unvalidated_proposals": unvalidated,
            "source_mutation_policy": "only explicit patch apply/adoption",
            "source_mutation_points": ["explicit patch apply/adoption"],
            "warnings": [],
        }

    def _build_memory(self, *, root: Path, warnings: list[str]) -> dict:
        """프로젝트 memory와 hygiene 요약을 구성한다."""
        memory = load_project_memory(root)
        if memory is None:
            return {
                "lessons_count": 0,
                "pinned_count": 0,
                "suppressed_count": 0,
                "hygiene": {"checked": False, "watch": 0, "stale": 0, "conflicting": 0},
                "top_lessons": [],
                "lessons_path": _relative(default_memory_path(root), root),
                "hygiene_path": _relative(default_memory_hygiene_path(root), root),
            }

        counts = memory_override_counts(memory)
        report = load_memory_hygiene(root)
        hygiene_summary = {"checked": False, "watch": 0, "stale": 0, "conflicting": 0}
        fresh_status: dict[str, str] = {}
        if report is not None:
            hygiene_summary = {
                "checked": True,
                "watch": int(report.summary.get("watch", 0) or 0),
                "stale": int(report.summary.get("stale", 0) or 0),
                "conflicting": int(report.summary.get("conflicting", 0) or 0),
            }
            fresh_status = {item.lesson_id: item.status for item in report.items}

        ranked_lessons = self._rank_top_lessons(memory.lessons, fresh_status)
        return {
            "lessons_count": len(memory.lessons),
            "pinned_count": counts["pinned"],
            "suppressed_count": counts["suppressed"],
            "hygiene": hygiene_summary,
            "top_lessons": [lesson.text for lesson in ranked_lessons[:3]],
            "lessons_path": _relative(default_memory_path(root), root),
            "hygiene_path": _relative(default_memory_hygiene_path(root), root),
        }

    def _build_notes(self, *, root: Path) -> dict:
        """사용자 notes 요약을 구성한다."""
        notes = ProjectNotesStore().list(default_notes_dir(root))
        summary = {
            "open": 0,
            "resolved": 0,
            "high": 0,
            "success": 0,
            "confusion": 0,
            "bug": 0,
            "idea": 0,
            "friction": 0,
            "latest": {},
        }
        latest_note: dict = {}
        for note in notes:
            if note.status == "resolved":
                summary["resolved"] += 1
            else:
                summary["open"] += 1
            if note.severity == "high":
                summary["high"] += 1
            if note.kind in {"success", "confusion", "bug", "idea", "friction"}:
                summary[note.kind] += 1
            if not latest_note:
                latest_note = {
                    "note_id": note.note_id,
                    "status": note.status,
                    "kind": note.kind,
                    "severity": note.severity,
                    "text": note.text,
                    "session_id": note.session_id,
                }
        summary["latest"] = latest_note
        return summary

    @staticmethod
    def _rank_top_lessons(lessons: list[ProjectLesson], hygiene_map: dict[str, str]) -> list[ProjectLesson]:
        """상단에 보여줄 lesson 우선순위를 정한다."""
        def _lesson_rank(lesson: ProjectLesson) -> tuple[int, int, float, str]:
            hygiene_status = hygiene_map.get(lesson.lesson_id, "fresh")
            freshness = {
                "fresh": 0,
                "watch": 1,
                "stale": 2,
                "conflicting": 3,
                "orphaned": 4,
                "suppressed": 5,
            }.get(hygiene_status, 1)
            pin_rank = 0 if lesson.pinned and not lesson.suppressed else 1
            return (
                pin_rank,
                freshness,
                -float(lesson.confidence),
                lesson.lesson_id,
            )

        filtered = [lesson for lesson in lessons if not lesson.suppressed]
        return sorted(filtered, key=_lesson_rank)

    def _build_active_work(self, *, session_payloads: list[tuple[Path, dict]], limit: int) -> list[dict]:
        """열려 있는 session을 간단히 정리한다."""
        items: list[dict] = []
        for _, payload in session_payloads:
            stage = str(payload.get("current_stage") or payload.get("status") or "unknown")
            if stage in _TERMINAL_SESSION_STATES:
                continue
            next_commands = payload.get("next_commands", [])
            primary = primary_next_command(next_commands if isinstance(next_commands, list) else [])
            if primary is None:
                next_actions = payload.get("next_actions", [])
                if isinstance(next_actions, list) and next_actions:
                    next_command = str(next_actions[0])
                else:
                    next_command = ""
            else:
                next_command = str(primary.get("command", ""))
            items.append(
                {
                    "session_id": str(payload.get("session_id", "")),
                    "request": str(payload.get("user_request", "")),
                    "stage": stage,
                    "next_command": next_command,
                }
            )
        return items[:limit]

    def _build_recent_journey(
        self,
        *,
        session_payloads: list[tuple[Path, dict]],
        adoption_payloads: list[tuple[Path, dict]],
        limit: int,
    ) -> list[dict]:
        """최근 session/adoption을 짧게 요약한다."""
        items: list[dict] = []
        for _, payload in adoption_payloads[:limit]:
            target_path = str(payload.get("target_path", "")) or "(unknown)"
            post_apply = payload.get("post_apply_tests", {})
            if isinstance(post_apply, dict) and int(post_apply.get("failed", 0) or 0) == 0:
                summary = "Post-apply tests passed"
            else:
                summary = "Adoption recorded"
            items.append(
                {
                    "kind": "adoption",
                    "title": f"Patch adopted: {target_path}",
                    "status": str(payload.get("adoption_status", "adopted")),
                    "summary": summary,
                }
            )

        remaining = max(0, limit - len(items))
        if remaining > 0:
            for _, payload in session_payloads[:remaining]:
                request_text = str(payload.get("user_request", "")).strip() or "(unknown request)"
                stage = str(payload.get("current_stage") or payload.get("status") or "unknown")
                summary = stage.replace("_", " ")
                session_summary = payload.get("summary", {})
                if isinstance(session_summary, dict):
                    if session_summary.get("diagnosis_result"):
                        summary = str(session_summary.get("diagnosis_result"))
                    elif session_summary.get("patch_validation_status"):
                        summary = f"Patch validation {session_summary.get('patch_validation_status')}"
                items.append(
                    {
                        "kind": "session",
                        "title": f"Session: {request_text}",
                        "status": stage,
                        "summary": summary,
                    }
                )
        return items[:limit]

    @staticmethod
    def _build_next_actions(*, initialized: bool, active_work: list[dict]) -> list[str]:
        """summary 화면의 다음 행동을 만든다."""
        if active_work:
            next_command = str(active_work[0].get("next_command", "")).strip()
            if next_command:
                return [next_command, "cambrian status"]
        if not initialized:
            return ["cambrian init --wizard"]
        return ['cambrian do "fix a small bug"', "cambrian status"]


def render_usage_summary(summary: UsageSummary) -> str:
    """usage summary를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Cambrian Project Summary",
        "==================================================",
        "",
        "Project:",
        f"  {summary.project_name or '(unknown)'}",
        "",
        "Work so far:",
        f"  sessions        : {summary.counts.get('sessions', 0)}",
        f"  diagnoses       : {summary.counts.get('diagnoses', 0)}",
        f"  patch proposals : {summary.counts.get('patch_proposals', 0)}",
        f"  adopted changes : {summary.counts.get('adoptions', 0)}",
        "",
        "Safety:",
        f"  automatic adoption : {'on' if summary.safety.get('automatic_adoption_enabled', False) else 'off'}",
        f"  source changes     : {summary.safety.get('source_mutation_policy', 'only explicit patch apply/adoption')}",
        f"  unvalidated proposals: {summary.safety.get('unvalidated_proposals', 0)}",
    ]
    if summary.safety.get("failed_apply_records", 0):
        lines.append(f"  failed applies       : {summary.safety.get('failed_apply_records', 0)}")

    memory = summary.memory if isinstance(summary.memory, dict) else {}
    hygiene = memory.get("hygiene", {}) if isinstance(memory.get("hygiene"), dict) else {}
    lines.extend(
        [
            "",
            "Project memory:",
            f"  lessons remembered : {memory.get('lessons_count', 0)}",
            f"  pinned             : {memory.get('pinned_count', 0)}",
            f"  need review        : {int(hygiene.get('watch', 0) or 0) + int(hygiene.get('stale', 0) or 0) + int(hygiene.get('conflicting', 0) or 0)}",
        ]
    )
    top_lessons = memory.get("top_lessons", [])
    if isinstance(top_lessons, list) and top_lessons:
        lines.append("")
        lines.append("Remembered:")
        for item in top_lessons[:3]:
            lines.append(f"  - {item}")

    notes = summary.notes if isinstance(summary.notes, dict) else {}
    latest_note = notes.get("latest", {}) if isinstance(notes.get("latest"), dict) else {}
    lines.extend(
        [
            "",
            "User notes:",
            f"  open      : {notes.get('open', 0)}",
            f"  resolved  : {notes.get('resolved', 0)}",
            f"  high      : {notes.get('high', 0)}",
            f"  confusion : {notes.get('confusion', 0)}",
            f"  success   : {notes.get('success', 0)}",
        ]
    )
    if latest_note.get("text"):
        snippet = str(latest_note.get("text"))
        if len(snippet) > 72:
            snippet = f"{snippet[:69]}..."
        lines.append(f"  latest    : [{latest_note.get('kind', 'note')}] {snippet}")

    lines.append("")
    lines.append("Active work:")
    if summary.active_work:
        active = summary.active_work[0]
        lines.append(f"  {active.get('request', '-')}")
        lines.append(f"  stage: {active.get('stage', '-')}")
        lines.append(f"  next : {active.get('next_command', '-')}")
    else:
        lines.append("  none")

    wins = [
        item for item in summary.recent_journey
        if isinstance(item, dict) and str(item.get("kind", "")) == "adoption"
    ]
    if wins:
        lines.extend(["", "Recent wins:"])
        for item in wins[:3]:
            lines.append(f"  - {item.get('title', '-')}, {item.get('summary', '-')}")

    if summary.warnings:
        lines.extend(["", "Warnings:"])
        for item in summary.warnings[:5]:
            lines.append(f"  - {item}")

    lines.extend(["", "Next:"])
    for action in summary.next_actions:
        lines.append(f"  {action}" if str(action).startswith("cambrian ") else f"  - {action}")
    return "\n".join(lines)
