"""Cambrian 프로젝트 타임라인 리더."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _load_yaml(path: Path, warnings: list[str]) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        warnings.append(f"누락된 YAML artifact: {path}")
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        warnings.append(f"YAML 읽기 실패: {path} ({exc})")
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        warnings.append(f"YAML 형식 오류: {path}")
        return None
    return payload


def _load_json(path: Path, warnings: list[str]) -> dict | None:
    """JSON 파일을 안전하게 읽는다."""
    if not path.exists():
        warnings.append(f"누락된 JSON artifact: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"JSON 읽기 실패: {path} ({exc})")
        return None
    if not isinstance(payload, dict):
        warnings.append(f"JSON 형식 오류: {path}")
        return None
    return payload


def _latest_file(directory: Path, pattern: str) -> Path | None:
    """패턴과 일치하는 최신 파일을 찾는다."""
    if not directory.exists():
        return None
    candidates = sorted(
        (item for item in directory.glob(pattern) if item.is_file()),
        key=lambda item: (item.stat().st_mtime, item.name),
    )
    if not candidates:
        return None
    return candidates[-1]


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _truncate(text: str, limit: int = 96) -> str:
    """긴 문장을 상태 화면에 맞게 짧게 줄인다."""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _stage_label(stage: str | None) -> str:
    """내부 stage를 사용자 친화적 문구로 변환한다."""
    mapping = {
        "needs_context": "needs your choice",
        "clarification_open": "waiting for context",
        "diagnose_ready": "ready to diagnose",
        "diagnosed": "diagnosis complete",
        "patch_intent_draft": "waiting for patch details",
        "patch_intent_ready": "ready to propose patch",
        "patch_proposal_ready": "ready to validate patch",
        "patch_proposal_validated": "ready to apply explicitly",
        "adopted": "adopted",
        "blocked": "blocked",
        "error": "error",
        "initialized_required": "project setup required",
        "prepared": "ready to diagnose",
    }
    if not stage:
        return "unknown"
    return mapping.get(stage, stage.replace("_", " "))


def _event_symbol(status: str) -> str:
    """이벤트 상태를 타임라인 기호로 바꾼다."""
    if status in {"completed", "ready", "validated", "adopted", "selected", "passed"}:
        return "✓"
    if status in {"blocked", "failed", "error"}:
        return "!"
    return "→"


@dataclass
class TimelineEvent:
    """세션 타임라인의 개별 이벤트."""

    event_id: str
    kind: str
    title: str
    status: str
    created_at: str | None
    path: str | None
    summary: str
    next_action: str | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class SessionTimeline:
    """특정 do session의 타임라인."""

    session_id: str | None
    user_request: str | None
    current_stage: str | None
    status: str
    events: list[TimelineEvent]
    learned: list[str]
    next_actions: list[str]
    warnings: list[str]
    errors: list[str]
    selected_sources: list[str] = field(default_factory=list)
    selected_tests: list[str] = field(default_factory=list)
    artifact_path: str | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "session_id": self.session_id,
            "user_request": self.user_request,
            "current_stage": self.current_stage,
            "status": self.status,
            "events": [item.to_dict() for item in self.events],
            "learned": list(self.learned),
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "selected_sources": list(self.selected_sources),
            "selected_tests": list(self.selected_tests),
            "artifact_path": self.artifact_path,
        }


@dataclass
class ProjectStatusView:
    """프로젝트 상태 화면에 필요한 통합 뷰."""

    initialized: bool
    project_summary: dict
    active_sessions: list[SessionTimeline]
    recent_sessions: list[SessionTimeline]
    latest_adoption: dict | None
    recent_lessons: list[str]
    global_next_actions: list[str]
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "initialized": self.initialized,
            "project_summary": dict(self.project_summary),
            "active_sessions": [item.to_dict() for item in self.active_sessions],
            "recent_sessions": [item.to_dict() for item in self.recent_sessions],
            "latest_adoption": dict(self.latest_adoption or {}),
            "recent_lessons": list(self.recent_lessons),
            "global_next_actions": list(self.global_next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class ProjectTimelineReader:
    """`.cambrian` 아래 artifact를 읽어 세션 타임라인을 구성한다."""

    def read_project_status(
        self,
        project_root: Path,
        limit: int = 5,
    ) -> ProjectStatusView:
        """프로젝트 전체 상태와 최근 세션 타임라인을 반환한다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []

        project_payload = _load_yaml(root / ".cambrian" / "project.yaml", warnings)
        profile_payload = _load_yaml(root / ".cambrian" / "profile.yaml", warnings)
        initialized = project_payload is not None and profile_payload is not None
        if not initialized:
            return ProjectStatusView(
                initialized=False,
                project_summary={
                    "name": root.name,
                    "type": "unknown",
                    "tests": "",
                    "mode": "balanced",
                },
                active_sessions=[],
                recent_sessions=[],
                latest_adoption=None,
                recent_lessons=[],
                global_next_actions=["cambrian init --wizard"],
                warnings=warnings,
                errors=errors,
            )

        session_paths = self._list_session_paths(root)
        session_timelines = [
            self._build_session_timeline(root, item, warnings)
            for item in session_paths[: max(limit, 1)]
        ]
        active_sessions = [
            item for item in session_timelines
            if item.current_stage not in {"adopted", "completed", "closed", "error"}
            and item.next_actions
        ]
        latest_adoption = self._read_latest_adoption(root, warnings)
        recent_lessons = self._collect_recent_lessons(root, warnings, latest_adoption, session_timelines)
        global_next_actions: list[str] = []
        if active_sessions:
            global_next_actions.extend(active_sessions[0].next_actions)
        elif session_timelines:
            global_next_actions.extend(session_timelines[0].next_actions)
        if not global_next_actions:
            global_next_actions.append('cambrian do "fix a small bug"')

        return ProjectStatusView(
            initialized=True,
            project_summary={
                "name": project_payload.get("project", {}).get("name", root.name),
                "type": project_payload.get("project", {}).get("type", "unknown"),
                "tests": project_payload.get("test", {}).get("command", ""),
                "mode": profile_payload.get("mode", "balanced"),
            },
            active_sessions=active_sessions[:1],
            recent_sessions=session_timelines[:limit],
            latest_adoption=latest_adoption,
            recent_lessons=recent_lessons[:3],
            global_next_actions=_dedupe(global_next_actions)[:5],
            warnings=warnings,
            errors=errors,
        )

    def read_session_timeline(
        self,
        project_root: Path,
        session_ref: str,
    ) -> SessionTimeline:
        """특정 session 타임라인을 반환한다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        session_path = self._resolve_session_path(root, session_ref)
        return self._build_session_timeline(root, session_path, warnings)

    def _list_session_paths(self, project_root: Path) -> list[Path]:
        """세션 파일을 최신순으로 정렬해 반환한다."""
        sessions_dir = project_root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return []
        return sorted(
            (item.resolve() for item in sessions_dir.glob("do_session_*.yaml") if item.is_file()),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )

    def _resolve_session_path(self, project_root: Path, session_ref: str) -> Path:
        """session id 또는 artifact 경로를 실제 경로로 바꾼다."""
        candidate = Path(session_ref)
        if candidate.exists():
            return candidate.resolve()
        for path in self._list_session_paths(project_root):
            payload = _load_yaml(path, [])
            if not payload:
                continue
            if str(payload.get("session_id", "")) == session_ref:
                return path.resolve()
        raise FileNotFoundError(f"session not found: {session_ref}")

    def _build_session_timeline(
        self,
        project_root: Path,
        session_path: Path,
        warnings: list[str],
    ) -> SessionTimeline:
        """개별 session artifact에서 사용자용 타임라인을 만든다."""
        warning_start = len(warnings)
        payload = _load_yaml(session_path, warnings)
        if payload is None:
            return SessionTimeline(
                session_id=session_path.stem,
                user_request=None,
                current_stage="error",
                status="error",
                events=[],
                learned=[],
                next_actions=[],
                warnings=[f"session을 읽을 수 없습니다: {session_path.name}"],
                errors=[],
                artifact_path=_relative(session_path, project_root),
            )

        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
        current_stage = str(payload.get("current_stage") or payload.get("status") or "unknown")
        selected_sources = list(summary.get("selected_sources", []) or summary.get("found_sources", []))
        selected_tests = list(summary.get("selected_tests", []) or summary.get("found_tests", []))
        next_actions = list(payload.get("next_actions", []))

        events: list[TimelineEvent] = []
        request_event = self._build_request_event(project_root, payload, artifacts, warnings)
        if request_event is not None:
            events.append(request_event)
        context_event = self._build_context_event(project_root, artifacts, warnings)
        if context_event is not None:
            events.append(context_event)
        clarification_event = self._build_clarification_event(project_root, artifacts, warnings)
        if clarification_event is not None:
            events.append(clarification_event)
        diagnosis_event = self._build_diagnosis_event(project_root, payload, artifacts, warnings)
        if diagnosis_event is not None:
            events.append(diagnosis_event)
        patch_intent_event = self._build_patch_intent_event(project_root, artifacts, warnings)
        if patch_intent_event is not None:
            events.append(patch_intent_event)
        proposal_events = self._build_patch_proposal_events(project_root, artifacts, warnings)
        events.extend(proposal_events)
        adoption_events = self._build_adoption_events(project_root, artifacts, warnings)
        events.extend(adoption_events)
        session_warning_items = warnings[warning_start:]

        learned = self._collect_session_lessons(
            project_root=project_root,
            current_stage=current_stage,
            adoption_events=adoption_events,
            session_payload=payload,
            warnings=warnings,
        )

        return SessionTimeline(
            session_id=str(payload.get("session_id", session_path.stem)),
            user_request=str(payload.get("user_request", "")),
            current_stage=current_stage,
            status=_stage_label(current_stage),
            events=events,
            learned=learned,
            next_actions=next_actions,
            warnings=_dedupe(
                list(payload.get("warnings", []))
                + session_warning_items
                + [item for event in events for item in event.warnings]
            ),
            errors=list(payload.get("errors", [])),
            selected_sources=_dedupe([str(item) for item in selected_sources if item]),
            selected_tests=_dedupe([str(item) for item in selected_tests if item]),
            artifact_path=_relative(session_path, project_root),
        )

    def _build_request_event(
        self,
        project_root: Path,
        session_payload: dict,
        artifacts: dict,
        warnings: list[str],
    ) -> TimelineEvent:
        """request 이벤트를 만든다."""
        request_ref = artifacts.get("request_path")
        request_path = self._resolve_artifact(project_root, request_ref)
        request_payload = _load_yaml(request_path, warnings) if request_path is not None else {}
        title = str(session_payload.get("user_request", "") or request_payload.get("user_request", "request"))
        return TimelineEvent(
            event_id=f"{session_payload.get('session_id', 'session')}:request",
            kind="request",
            title="Request received",
            status="completed",
            created_at=str(request_payload.get("created_at")) if isinstance(request_payload, dict) and request_payload.get("created_at") else str(session_payload.get("created_at", "")) or None,
            path=_relative(request_path, project_root) if request_path is not None and request_path.exists() else request_ref,
            summary=f"Request received: {title}",
            next_action=None,
            warnings=[],
        )

    def _build_context_event(
        self,
        project_root: Path,
        artifacts: dict,
        warnings: list[str],
    ) -> TimelineEvent | None:
        """context scan 이벤트를 만든다."""
        context_path = self._resolve_artifact(project_root, artifacts.get("context_scan_path"))
        if context_path is None:
            return None
        context_payload = _load_yaml(context_path, warnings)
        if context_payload is None:
            return TimelineEvent(
                event_id=f"{context_path.name}:context",
                kind="context_scan",
                title="Suggested context",
                status="warning",
                created_at=None,
                path=_relative(context_path, project_root),
                summary="Context artifact is missing or malformed",
                next_action=None,
                warnings=[f"context artifact를 읽을 수 없습니다: {_relative(context_path, project_root)}"],
            )
        top_source = str(context_payload.get("top_source") or "none")
        top_test = str(context_payload.get("top_test") or "none")
        if str(context_payload.get("status", "")) == "no_match":
            summary = "No confident source or test suggestion yet"
            status = "waiting"
        else:
            summary = f"Suggested {top_source} and {top_test}"
            status = "completed"
        return TimelineEvent(
            event_id=f"{context_path.name}:context",
            kind="context_scan",
            title="Suggested context",
            status=status,
            created_at=str(context_payload.get("created_at")) if context_payload.get("created_at") else None,
            path=_relative(context_path, project_root),
            summary=summary,
            next_action=None,
            warnings=[],
        )

    def _build_clarification_event(
        self,
        project_root: Path,
        artifacts: dict,
        warnings: list[str],
    ) -> TimelineEvent | None:
        """clarification 이벤트를 만든다."""
        clarification_path = self._resolve_artifact(project_root, artifacts.get("clarification_path"))
        if clarification_path is None:
            return None
        clarification_payload = _load_yaml(clarification_path, warnings)
        if clarification_payload is None:
            return TimelineEvent(
                event_id=f"{clarification_path.name}:clarification",
                kind="clarification",
                title="Clarification",
                status="warning",
                created_at=None,
                path=_relative(clarification_path, project_root),
                summary="Clarification artifact is missing or malformed",
                next_action=None,
                warnings=[f"clarification artifact를 읽을 수 없습니다: {_relative(clarification_path, project_root)}"],
            )
        status = str(clarification_payload.get("status", "open"))
        selected = clarification_payload.get("selected_context", {})
        sources = list(selected.get("sources", [])) if isinstance(selected, dict) else []
        tests = list(selected.get("tests", [])) if isinstance(selected, dict) else []
        if status == "ready":
            summary = (
                f"Selected {', '.join(sources) or 'source'}"
                + (f" and {', '.join(tests)}" if tests else "")
            )
            event_status = "selected"
        elif status == "blocked":
            summary = "Clarification is blocked"
            event_status = "blocked"
        else:
            summary = "Waiting for source/test selection"
            event_status = "waiting"
        next_actions = clarification_payload.get("next_actions", [])
        return TimelineEvent(
            event_id=f"{clarification_path.name}:clarification",
            kind="clarification",
            title="Clarification",
            status=event_status,
            created_at=str(clarification_payload.get("created_at")) if clarification_payload.get("created_at") else None,
            path=_relative(clarification_path, project_root),
            summary=summary,
            next_action=str(next_actions[0]) if next_actions else None,
            warnings=[],
        )

    def _build_diagnosis_event(
        self,
        project_root: Path,
        session_payload: dict,
        artifacts: dict,
        warnings: list[str],
    ) -> TimelineEvent | None:
        """diagnosis 이벤트를 만든다."""
        report_path = self._resolve_artifact(project_root, artifacts.get("report_path"))
        if report_path is not None:
            report_payload = _load_json(report_path, warnings)
        else:
            report_payload = None
        if report_path is not None and report_payload is not None:
            diagnostics = report_payload.get("diagnostics", {}) if isinstance(report_payload, dict) else {}
            inspected = diagnostics.get("inspected_files", []) if isinstance(diagnostics, dict) else []
            related_tests = diagnostics.get("related_tests", []) if isinstance(diagnostics, dict) else []
            test_results = diagnostics.get("test_results", {}) if isinstance(diagnostics, dict) else {}
            failed = int(test_results.get("failed", 0) or 0)
            passed = int(test_results.get("passed", 0) or 0)
            source_label = (
                ", ".join(
                    str(item.get("path", ""))
                    for item in inspected
                    if isinstance(item, dict) and item.get("path")
                )
                or "selected source"
            )
            if failed > 0:
                summary = f"Inspected {source_label}; related test failed"
            elif passed > 0:
                summary = f"Inspected {source_label}; related test passed"
            else:
                summary = f"Inspected {source_label}"
            return TimelineEvent(
                event_id=f"{report_path.parent.name}:diagnosis",
                kind="diagnosis",
                title="Diagnosis",
                status="completed",
                created_at=str(report_payload.get("created_at")) if report_payload.get("created_at") else str(session_payload.get("updated_at")) if session_payload.get("updated_at") else None,
                path=_relative(report_path, project_root),
                summary=summary,
                next_action=str((report_payload or {}).get("next_actions", [None])[0]) if isinstance(report_payload, dict) else None,
                warnings=[],
            )

        task_path = self._resolve_artifact(project_root, artifacts.get("task_spec_path"))
        if task_path is None:
            return None
        task_payload = _load_yaml(task_path, warnings)
        sources = []
        if isinstance(task_payload, dict):
            actions = list(task_payload.get("actions", []))
            for action in actions:
                if isinstance(action, dict) and action.get("type") == "inspect_files":
                    sources.extend(str(item) for item in action.get("target_paths", []) if item)
        summary = (
            f"Diagnose-only task is ready for {', '.join(_dedupe(sources))}"
            if sources else "Diagnose-only task is ready"
        )
        return TimelineEvent(
            event_id=f"{task_path.name}:diagnosis",
            kind="diagnosis",
            title="Diagnosis",
            status="ready",
            created_at=None,
            path=_relative(task_path, project_root),
            summary=summary,
            next_action=None,
            warnings=[],
        )

    def _build_patch_intent_event(
        self,
        project_root: Path,
        artifacts: dict,
        warnings: list[str],
    ) -> TimelineEvent | None:
        """patch intent 이벤트를 만든다."""
        intent_path = self._resolve_artifact(project_root, artifacts.get("patch_intent_path"))
        if intent_path is None:
            return None
        intent_payload = _load_yaml(intent_path, warnings)
        if intent_payload is None:
            return TimelineEvent(
                event_id=f"{intent_path.name}:patch_intent",
                kind="patch_intent",
                title="Patch intent",
                status="warning",
                created_at=None,
                path=_relative(intent_path, project_root),
                summary="Patch intent artifact is missing or malformed",
                next_action=None,
                warnings=[f"patch intent artifact를 읽을 수 없습니다: {_relative(intent_path, project_root)}"],
            )
        status = str(intent_payload.get("status", "draft"))
        if status == "ready_for_proposal":
            summary = "Patch intent ready: old text and replacement text selected"
            event_status = "ready"
        elif status == "blocked":
            summary = "Patch intent is blocked"
            event_status = "blocked"
        else:
            summary = "Patch intent form created; choose old text and new text"
            event_status = "waiting"
        next_actions = intent_payload.get("next_actions", [])
        return TimelineEvent(
            event_id=f"{intent_path.name}:patch_intent",
            kind="patch_intent",
            title="Patch intent",
            status=event_status,
            created_at=str(intent_payload.get("created_at")) if intent_payload.get("created_at") else None,
            path=_relative(intent_path, project_root),
            summary=summary,
            next_action=str(next_actions[0]) if next_actions else None,
            warnings=[],
        )

    def _build_patch_proposal_events(
        self,
        project_root: Path,
        artifacts: dict,
        warnings: list[str],
    ) -> list[TimelineEvent]:
        """patch proposal과 validation 이벤트를 만든다."""
        proposal_path = self._resolve_artifact(project_root, artifacts.get("patch_proposal_path"))
        if proposal_path is None:
            return []
        proposal_payload = _load_yaml(proposal_path, warnings)
        if proposal_payload is None:
            return [
                TimelineEvent(
                    event_id=f"{proposal_path.name}:patch_proposal",
                    kind="patch_proposal",
                    title="Patch proposal",
                    status="warning",
                    created_at=None,
                    path=_relative(proposal_path, project_root),
                    summary="Patch proposal artifact is missing or malformed",
                    next_action=None,
                    warnings=[f"patch proposal artifact를 읽을 수 없습니다: {_relative(proposal_path, project_root)}"],
                )
            ]
        events: list[TimelineEvent] = []
        validation = proposal_payload.get("validation", {}) if isinstance(proposal_payload.get("validation"), dict) else {}
        proposal_status = str(proposal_payload.get("proposal_status", "ready"))
        target = str(proposal_payload.get("target_path", "") or "selected target")
        events.append(
            TimelineEvent(
                event_id=f"{proposal_path.name}:patch_proposal",
                kind="patch_proposal",
                title="Patch proposal",
                status="ready" if proposal_status not in {"blocked", "failed"} else proposal_status,
                created_at=str(proposal_payload.get("created_at")) if proposal_payload.get("created_at") else None,
                path=_relative(proposal_path, project_root),
                summary=f"Patch proposal prepared for {target}",
                next_action=str((proposal_payload.get("next_actions", []) or [None])[0]),
                warnings=[],
            )
        )
        if validation.get("attempted"):
            validation_status = str(validation.get("status", "unknown"))
            tests = validation.get("tests", {}) if isinstance(validation.get("tests"), dict) else {}
            failed = int(tests.get("failed", 0) or 0)
            passed = int(tests.get("passed", 0) or 0)
            if validation_status == "passed":
                summary = "Patch proposal validated in isolation"
                event_status = "validated"
            elif failed > 0:
                summary = "Patch proposal validation failed in isolation"
                event_status = "failed"
            else:
                summary = f"Patch proposal validation {validation_status}"
                event_status = validation_status
            events.append(
                TimelineEvent(
                    event_id=f"{proposal_path.name}:patch_validation",
                    kind="patch_validation",
                    title="Patch validation",
                    status=event_status,
                    created_at=None,
                    path=_relative(proposal_path, project_root),
                    summary=summary,
                    next_action=str((proposal_payload.get("next_actions", []) or [None])[0]),
                    warnings=[],
                )
            )
        return events

    def _build_adoption_events(
        self,
        project_root: Path,
        artifacts: dict,
        warnings: list[str],
    ) -> list[TimelineEvent]:
        """patch apply와 adoption 이벤트를 만든다."""
        adoption_path = self._resolve_artifact(project_root, artifacts.get("adoption_record_path"))
        if adoption_path is None:
            return []
        adoption_payload = _load_json(adoption_path, warnings)
        if adoption_payload is None:
            return [
                TimelineEvent(
                    event_id=f"{adoption_path.name}:adoption",
                    kind="adoption",
                    title="Adoption",
                    status="warning",
                    created_at=None,
                    path=_relative(adoption_path, project_root),
                    summary="Adoption record is missing or malformed",
                    next_action=None,
                    warnings=[f"adoption record를 읽을 수 없습니다: {_relative(adoption_path, project_root)}"],
                )
            ]
        tests = adoption_payload.get("post_apply_tests", {}) if isinstance(adoption_payload.get("post_apply_tests"), dict) else {}
        failed = int(tests.get("failed", 0) or 0)
        passed = int(tests.get("passed", 0) or 0)
        target = str(adoption_payload.get("target_path", "") or "selected target")
        apply_summary = (
            f"Applied patch to {target}; tests failed"
            if failed > 0 else
            f"Applied patch to {target}; tests passed"
        )
        adoption_summary = (
            f"Patch adopted; post-apply tests passed"
            if passed > 0 and failed == 0 else
            f"Patch adoption recorded with {failed} failing test(s)"
        )
        return [
            TimelineEvent(
                event_id=f"{adoption_path.name}:patch_apply",
                kind="patch_apply",
                title="Patch apply",
                status="completed" if failed == 0 else "failed",
                created_at=str(adoption_payload.get("created_at")) if adoption_payload.get("created_at") else None,
                path=_relative(adoption_path, project_root),
                summary=apply_summary,
                next_action=None,
                warnings=[],
            ),
            TimelineEvent(
                event_id=f"{adoption_path.name}:adoption",
                kind="adoption",
                title="Adoption",
                status="adopted" if failed == 0 else "failed",
                created_at=str(adoption_payload.get("created_at")) if adoption_payload.get("created_at") else None,
                path=_relative(adoption_path, project_root),
                summary=adoption_summary,
                next_action=None,
                warnings=[],
            ),
        ]

    def _collect_session_lessons(
        self,
        *,
        project_root: Path,
        current_stage: str,
        adoption_events: list[TimelineEvent],
        session_payload: dict,
        warnings: list[str],
    ) -> list[str]:
        """완료된 세션에서 보여줄 짧은 학습 포인트를 추출한다."""
        lessons: list[str] = []
        if current_stage == "adopted" and adoption_events:
            adoption_path = self._resolve_artifact(
                project_root,
                (session_payload.get("artifacts", {}) or {}).get("adoption_record_path"),
            )
            adoption_payload = _load_json(adoption_path, warnings) if adoption_path is not None else {}
            if isinstance(adoption_payload, dict):
                reason = str(adoption_payload.get("human_reason", "")).strip()
                if reason:
                    lessons.append(f"Explicit adoption reason: {reason}")
                tests = adoption_payload.get("post_apply_tests", {})
                if isinstance(tests, dict):
                    tests_executed = list(tests.get("tests_executed", []))
                    if tests_executed and int(tests.get("failed", 0) or 0) == 0:
                        lessons.append(f"Post-apply tests passed for {tests_executed[0]}")

        feedback_path = _latest_file(project_root / ".cambrian" / "feedback", "feedback_*.json")
        if feedback_path is not None:
            feedback_payload = _load_json(feedback_path, warnings) or {}
            lessons.extend(str(item) for item in feedback_payload.get("keep_patterns", []))
            lessons.extend(str(item) for item in feedback_payload.get("avoid_patterns", []))

        if not lessons and session_payload.get("next_actions"):
            lessons.append(f"Next safe step was recorded: {session_payload['next_actions'][0]}")
        return [_truncate(item) for item in _dedupe(lessons)[:3]]

    def _collect_recent_lessons(
        self,
        project_root: Path,
        warnings: list[str],
        latest_adoption: dict | None,
        session_timelines: list[SessionTimeline],
    ) -> list[str]:
        """프로젝트 수준의 최근 학습 포인트를 모은다."""
        lessons: list[str] = []

        feedback_path = _latest_file(project_root / ".cambrian" / "feedback", "feedback_*.json")
        if feedback_path is not None:
            feedback_payload = _load_json(feedback_path, warnings) or {}
            lessons.extend(str(item) for item in feedback_payload.get("keep_patterns", []))
            lessons.extend(str(item) for item in feedback_payload.get("avoid_patterns", []))

        pressure_path = project_root / ".cambrian" / "evolution" / "_selection_pressure.yaml"
        if pressure_path.exists():
            pressure_payload = _load_yaml(pressure_path, warnings) or {}
            lessons.extend(str(item) for item in pressure_payload.get("keep_patterns", []))
            lessons.extend(str(item) for item in pressure_payload.get("avoid_patterns", []))
            lessons.extend(str(item) for item in pressure_payload.get("risk_flags", []))

        if latest_adoption:
            reason = str(latest_adoption.get("reason", "")).strip()
            if reason:
                lessons.append(f"Latest adoption reason: {reason}")
            tests = str(latest_adoption.get("tests", "")).strip()
            target = str(latest_adoption.get("target", "")).strip()
            if tests and target:
                lessons.append(f"{target} adoption tests: {tests}")

        for timeline in session_timelines:
            lessons.extend(timeline.learned)

        return [_truncate(item) for item in _dedupe(lessons)[:3]]

    def _read_latest_adoption(self, project_root: Path, warnings: list[str]) -> dict | None:
        """최신 adoption 요약을 만든다."""
        latest_path = project_root / ".cambrian" / "adoptions" / "_latest.json"
        latest_payload = _load_json(latest_path, warnings)
        if not latest_payload:
            return None
        record_ref = latest_payload.get("latest_adoption_path")
        record_path = self._resolve_artifact(project_root, record_ref) if isinstance(record_ref, str) else None
        record_payload = _load_json(record_path, warnings) if record_path is not None else {}
        payload = record_payload if isinstance(record_payload, dict) and record_payload else latest_payload
        tests = payload.get("post_apply_tests", {}) if isinstance(payload.get("post_apply_tests"), dict) else {}
        failed = int(tests.get("failed", 0) or 0)
        passed = int(tests.get("passed", 0) or 0)
        if failed > 0:
            test_summary = "failed"
        elif passed > 0:
            test_summary = "passed"
        else:
            test_summary = str(payload.get("adoption_status", "unknown"))
        return {
            "id": payload.get("adoption_id") or latest_payload.get("latest_adoption_id", ""),
            "target": payload.get("target_path") or latest_payload.get("target_path", ""),
            "reason": payload.get("human_reason", ""),
            "tests": test_summary,
            "path": _relative(record_path, project_root) if record_path is not None and record_path.exists() else latest_payload.get("latest_adoption_path", ""),
        }

    @staticmethod
    def _resolve_artifact(project_root: Path, artifact_ref: str | None) -> Path | None:
        """상대/절대 artifact 경로를 실제 경로로 바꾼다."""
        if not artifact_ref:
            return None
        candidate = Path(str(artifact_ref))
        if candidate.is_absolute():
            return candidate.resolve()
        return (project_root / candidate).resolve()


def render_session_timeline(timeline: SessionTimeline) -> str:
    """특정 세션 타임라인을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Session Timeline",
        "==================================================",
        "Request:",
        f"  {timeline.user_request or '(unknown)'}",
        "",
        "Current:",
        f"  {timeline.status}",
        "",
        "Events:",
    ]
    if not timeline.events:
        lines.append("  (no recorded events)")
    for event in timeline.events:
        lines.append(f"  {_event_symbol(event.status)} {event.title}")
        lines.append(f"    {event.summary}")
        if event.path:
            lines.append(f"    {event.path}")
    if timeline.learned:
        lines.extend(["", "Learned:"])
        for item in timeline.learned[:3]:
            lines.append(f"  - {item}")
    if timeline.warnings:
        lines.extend(["", "Warnings:"])
        for item in timeline.warnings[:3]:
            lines.append(f"  - {item}")
    if timeline.errors:
        lines.extend(["", "Errors:"])
        for item in timeline.errors[:3]:
            lines.append(f"  - {item}")
    lines.extend(["", "Next:"])
    if timeline.next_actions:
        for item in timeline.next_actions[:3]:
            lines.append(f"  {item}" if str(item).startswith("cambrian ") else f"  - {item}")
    else:
        lines.append("  cambrian status")
    return "\n".join(lines)


def render_project_timeline(view: ProjectStatusView, limit: int = 5) -> str:
    """프로젝트의 최근 세션 타임라인 목록을 렌더링한다."""
    lines = [
        "Cambrian Timeline",
        "==================================================",
    ]
    if not view.initialized:
        lines.extend([
            "Cambrian is not fitted to this project yet.",
            "",
            "Next:",
            "  cambrian init --wizard",
        ])
        return "\n".join(lines)

    sessions = view.recent_sessions[:limit]
    if not sessions:
        lines.extend([
            "(no recorded sessions)",
            "",
            "Next:",
            '  cambrian do "fix a small bug"',
        ])
        return "\n".join(lines)

    for timeline in sessions:
        lines.append(f"[{timeline.session_id}] {timeline.user_request or '(unknown request)'}")
        lines.append(f"  status: {timeline.status}")
        lines.append("  events:")
        if not timeline.events:
            lines.append("    (no recorded events)")
        for event in timeline.events[:5]:
            lines.append(f"    {_event_symbol(event.status)} {event.summary}")
        lines.append("  next:")
        if timeline.next_actions:
            lines.append(f"    {timeline.next_actions[0]}")
        else:
            lines.append("    cambrian status")
        lines.append("")
    return "\n".join(lines).rstrip()
