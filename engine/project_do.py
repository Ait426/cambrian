"""Cambrian do 앞문 오케스트레이션."""

from __future__ import annotations

import json
import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_clarifier import ClarificationSession, RunClarifier
from engine.project_errors import hint_for_do_session, render_recovery_hint
from engine.project_metrics import build_session_metrics_context
from engine.project_next import NextCommandBuilder
from engine.project_mode import ProjectRunPreparer
from engine.project_router import ProjectSkillRouter
from engine.project_win_lane import render_request_lane_fit

logger = logging.getLogger(__name__)


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _session_id() -> str:
    """do 세션 식별자를 생성한다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"do-{stamp}-{secrets.token_hex(2)}"


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


def _dump_yaml(path: Path, payload: dict) -> None:
    """YAML 파일을 저장한다."""
    _atomic_write_text(
        path,
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
    )


def _load_yaml(path: Path) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("YAML 로드 실패: %s (%s)", path, exc)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("YAML 형식 오류: %s", path)
        return None
    return payload


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _quote_arg(value: str) -> str:
    """CLI 예시에 넣을 인자를 안전하게 감싼다."""
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def _human_status(status: str) -> str:
    """세션 상태를 사람이 읽는 문장으로 바꾼다."""
    mapping = {
        "initialized_required": "initialization required",
        "prepared": "ready to diagnose",
        "diagnose_ready": "ready to diagnose",
        "needs_context": "needs more context",
        "clarification_open": "needs your choice",
        "diagnosed": "diagnosed",
        "patch_intent_draft": "patch intent draft",
        "patch_intent_ready": "patch intent ready",
        "patch_proposal_ready": "patch proposal ready",
        "patch_proposal_validated": "patch proposal validated",
        "adopted": "adopted",
        "blocked": "blocked",
        "error": "error",
    }
    return mapping.get(status, status.replace("_", " "))


def _current_stage_from_status(status: str) -> str:
    """세션 status를 현재 stage 이름으로 정규화한다."""
    mapping = {
        "initialized_required": "initialized_required",
        "prepared": "diagnose_ready",
        "needs_context": "needs_context",
        "clarification_open": "clarification_open",
        "diagnosed": "diagnosed",
        "blocked": "blocked",
        "error": "error",
        "adopted": "adopted",
    }
    return mapping.get(status, status)


@dataclass
class DoSession:
    """`cambrian do` 작업 세션."""

    schema_version: str
    session_id: str
    created_at: str
    updated_at: str | None
    user_request: str
    project_initialized: bool
    intent: dict | None
    selected_skills: list[str]
    status: str
    current_stage: str | None
    artifacts: dict
    summary: dict
    next_actions: list[str]
    next_commands: list[dict] = field(default_factory=list)
    harness_context: dict = field(default_factory=dict)
    agent_context: dict = field(default_factory=dict)
    harness_policy_context: dict = field(default_factory=dict)
    team_context: dict = field(default_factory=dict)
    team_policy_context: dict = field(default_factory=dict)
    template_context: dict = field(default_factory=dict)
    win_lane_context: dict = field(default_factory=dict)
    bridge_context: dict = field(default_factory=dict)
    metrics_context: dict = field(default_factory=dict)
    continuations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    artifact_path: str | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class DoSessionStore:
    """do session artifact 저장소."""

    def load(self, path: Path) -> DoSession:
        """session artifact를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if payload is None:
            raise FileNotFoundError(path)
        return DoSession(
            schema_version=str(payload.get("schema_version", "1.0.0")),
            session_id=str(payload.get("session_id", Path(path).stem)),
            created_at=str(payload.get("created_at", "")),
            updated_at=payload.get("updated_at"),
            user_request=str(payload.get("user_request", "")),
            project_initialized=bool(payload.get("project_initialized", False)),
            intent=dict(payload.get("intent", {})) if isinstance(payload.get("intent"), dict) else None,
            selected_skills=list(payload.get("selected_skills", [])),
            status=str(payload.get("status", "error")),
            current_stage=str(payload.get("current_stage") or _current_stage_from_status(str(payload.get("status", "error")))),
            artifacts=dict(payload.get("artifacts", {})) if isinstance(payload.get("artifacts"), dict) else {},
            summary=dict(payload.get("summary", {})) if isinstance(payload.get("summary"), dict) else {},
            next_actions=list(payload.get("next_actions", [])),
            next_commands=list(payload.get("next_commands", [])),
            harness_context=dict(payload.get("harness_context", {})) if isinstance(payload.get("harness_context"), dict) else {},
            agent_context=dict(payload.get("agent_context", {})) if isinstance(payload.get("agent_context"), dict) else {},
            harness_policy_context=dict(payload.get("harness_policy_context", {})) if isinstance(payload.get("harness_policy_context"), dict) else {},
            team_context=dict(payload.get("team_context", {})) if isinstance(payload.get("team_context"), dict) else {},
            team_policy_context=dict(payload.get("team_policy_context", {})) if isinstance(payload.get("team_policy_context"), dict) else {},
            template_context=dict(payload.get("template_context", {})) if isinstance(payload.get("template_context"), dict) else {},
            win_lane_context=dict(payload.get("win_lane_context", {})) if isinstance(payload.get("win_lane_context"), dict) else {},
            bridge_context=dict(payload.get("bridge_context", {})) if isinstance(payload.get("bridge_context"), dict) else {},
            metrics_context=dict(payload.get("metrics_context", {})) if isinstance(payload.get("metrics_context"), dict) else {},
            continuations=list(payload.get("continuations", [])),
            warnings=list(payload.get("warnings", [])),
            errors=list(payload.get("errors", [])),
            artifact_path=payload.get("artifact_path"),
        )

    def save(self, project_root: Path, session: DoSession) -> Path:
        """session artifact를 원자적으로 저장한다."""
        root = Path(project_root).resolve()
        sessions_dir = root / ".cambrian" / "sessions"
        session_path = sessions_dir / f"do_session_{session.session_id}.yaml"
        session.updated_at = _now()
        session.current_stage = session.current_stage or _current_stage_from_status(session.status)
        session.artifact_path = _relative_to_project(session_path, root)
        session.artifacts["session_path"] = session.artifact_path
        _dump_yaml(session_path, session.to_dict())
        return session_path

    def resolve_path(self, project_root: Path, session_ref: str | None = None) -> Path:
        """session path 또는 session id를 실제 artifact path로 변환한다."""
        root = Path(project_root).resolve()
        sessions_dir = root / ".cambrian" / "sessions"
        if session_ref:
            candidate = Path(session_ref)
            if candidate.exists():
                return candidate.resolve()
            if sessions_dir.exists():
                for path in sessions_dir.glob("do_session_*.yaml"):
                    payload = _load_yaml(path)
                    if not payload:
                        continue
                    if str(payload.get("session_id", "")) == session_ref:
                        return path.resolve()
            raise FileNotFoundError(f"session not found: {session_ref}")

        resolved = self.find_latest_active(project_root)
        if resolved is None:
            raise FileNotFoundError("no active do session found")
        return resolved

    def list_active_paths(self, project_root: Path) -> list[Path]:
        """active do session 경로를 최신순으로 반환한다."""
        root = Path(project_root).resolve()
        sessions_dir = root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return []
        candidates = sorted(
            sessions_dir.glob("do_session_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        active: list[Path] = []
        for path in candidates:
            payload = _load_yaml(path)
            if not payload:
                continue
            status = str(payload.get("status", "error"))
            next_actions = list(payload.get("next_actions", []))
            if status not in {"adopted", "completed", "closed", "error"} or bool(next_actions):
                active.append(path.resolve())
        return active

    def find_latest_active(self, project_root: Path) -> Path | None:
        """가장 최근 active do session을 찾는다."""
        active = self.list_active_paths(project_root)
        if active:
            return active[0]
        root = Path(project_root).resolve()
        sessions_dir = root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return None
        candidates = sorted(
            sessions_dir.glob("do_session_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        return candidates[0].resolve() if candidates else None


class ProjectDoRunner:
    """`cambrian do` 사용자 앞문을 오케스트레이션한다."""

    def __init__(self) -> None:
        self._preparer = ProjectRunPreparer()
        self._clarifier = RunClarifier()
        self._router = ProjectSkillRouter()
        self._store = DoSessionStore()

    def run(
        self,
        user_request: str,
        project_root: Path,
        options: dict,
    ) -> DoSession:
        """사용자 요청을 guided session으로 압축한다."""
        root = Path(project_root).resolve()
        request_text = str(user_request).strip()
        use_suggestion = options.get("use_suggestion")
        source_paths = _dedupe([str(item) for item in options.get("sources", []) if item])
        test_paths = _dedupe([str(item) for item in options.get("tests", []) if item])
        execute = bool(options.get("execute", False))
        no_scan = bool(options.get("no_scan", False))
        explicit_agent_id = str(options.get("agent") or "").strip() or None

        session_created_at = _now()
        session = DoSession(
            schema_version="1.0.0",
            session_id=_session_id(),
            created_at=session_created_at,
            updated_at=None,
            user_request=request_text,
            project_initialized=False,
            intent=None,
            selected_skills=[],
            status="error",
            current_stage="error",
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
                "understood_as": "unknown",
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
            win_lane_context={},
            bridge_context={},
            metrics_context=build_session_metrics_context(session_created_at=session_created_at),
            continuations=[],
        )

        if not self._is_project_initialized(root):
            session.status = "initialized_required"
            session.summary["understood_as"] = "project setup"
            session.summary["needs"] = ["fit this project with Cambrian"]
            session.next_actions = ["cambrian init --wizard"]
            session.next_commands = NextCommandBuilder.from_actions(
                session.next_actions,
                stage="initialized_required",
            )
            self._append_continuation(
                session,
                action="do_requested",
                result="initialized_required",
            )
            self._save_session(root, session)
            return session

        try:
            configs = ProjectRunPreparer._load_configs(root)
        except FileNotFoundError as exc:
            session.status = "initialized_required"
            session.errors.append(str(exc))
            session.summary["understood_as"] = "project setup"
            session.summary["needs"] = ["fit this project with Cambrian"]
            session.next_actions = ["cambrian init --wizard"]
            session.next_commands = NextCommandBuilder.from_actions(
                session.next_actions,
                stage="initialized_required",
            )
            self._append_continuation(
                session,
                action="do_requested",
                result="initialized_required",
            )
            self._save_session(root, session)
            return session

        run_intent = self._router.route(
            user_request=request_text,
            project_config=configs["project"],
            rules=configs["rules"],
            skills=configs["skills"],
            profile=configs["profile"],
            explicit_options={
                "skill_ids": [],
                "project_root": str(root),
                "target": source_paths[0] if source_paths else None,
                "tests": list(test_paths),
                "outputs": [],
                "action": "none",
                "content": None,
                "content_file": None,
                "old_text": None,
                "new_text": None,
            },
        )
        session.project_initialized = True
        session.intent = run_intent.to_dict()
        session.selected_skills = list(run_intent.selected_skills())
        session.warnings.extend(list(run_intent.safety_warnings))

        clarification_path: Path | None = None
        clarification_session: ClarificationSession | None = None
        request_payload: dict | None = None
        base_result = None
        wants_choice = use_suggestion is not None or bool(source_paths) or bool(test_paths)

        reusable_path = self._find_open_clarification(root, request_text) if (wants_choice or execute) else None
        if reusable_path is not None:
            clarification_path = reusable_path
            clarification_session = self._clarifier.load(clarification_path)
            session.warnings.append("같은 요청의 열린 clarification을 재사용했습니다.")
            request_payload = self._load_request_payload(root, clarification_session.request_artifact_path)
        else:
            try:
                base_result = self._preparer.prepare(
                    project_root=root,
                    user_request=request_text,
                    no_scan=no_scan,
                    execute=False,
                    dry_run=False,
                    explicit_agent_id=explicit_agent_id,
                )
            except KeyError:
                session.status = "blocked"
                session.current_stage = "blocked"
                session.errors.append(f"requested agent was not found: {explicit_agent_id}")
                session.next_actions = [
                    "cambrian agent list",
                    f"cambrian agent recommend {_quote_arg(request_text)}",
                ]
                session.next_commands = NextCommandBuilder.from_actions(
                    session.next_actions,
                    stage="blocked",
                )
                self._append_continuation(
                    session,
                    action="do_requested",
                    result="blocked",
                )
                self._save_session(root, session)
                return session
            except ValueError as exc:
                session.status = "blocked"
                session.current_stage = "blocked"
                session.errors.append(str(exc))
                session.next_actions = [
                    "cambrian agent list",
                    f"cambrian agent show {explicit_agent_id}",
                ]
                session.next_commands = NextCommandBuilder.from_actions(
                    session.next_actions,
                    stage="blocked",
                )
                self._append_continuation(
                    session,
                    action="do_requested",
                    result="blocked",
                )
                self._save_session(root, session)
                return session
            request_payload = self._load_request_payload(root, base_result.request_path)
            clarification_ref = (
                str(base_result.clarification.get("artifact_path", "") or "")
                or str(base_result.clarification.get("path", "") or "")
                or str((request_payload or {}).get("clarification", {}).get("path", "") or "")
            )
            if clarification_ref:
                clarification_path = root / clarification_ref

        self._apply_request_artifacts(
            session=session,
            project_root=root,
            request_payload=request_payload,
            request_path=(
                Path(root / base_result.request_path).resolve()
                if base_result is not None else None
            ),
        )
        self._refresh_metrics_context(
            session=session,
            source_paths=source_paths,
            test_paths=test_paths,
            use_suggestion=use_suggestion,
            explicit_agent_id=explicit_agent_id,
        )

        if clarification_path is not None and wants_choice:
            clarification_session = self._clarifier.answer(
                clarification_path,
                source=source_paths,
                tests=test_paths,
                use_suggestion=use_suggestion,
                mode="diagnose",
            )
        elif clarification_path is not None and clarification_session is None:
            clarification_session = self._clarifier.load(clarification_path)

        if clarification_session is not None:
            session.artifacts["clarification_path"] = clarification_session.artifact_path
            session.artifacts["task_spec_path"] = clarification_session.generated_task_spec_path

        if execute:
            if clarification_path is not None and clarification_session is not None and clarification_session.status == "ready":
                clarification_session = self._clarifier.execute_ready(clarification_path)
                session.artifacts["brain_run_id"] = (
                    clarification_session.execution or {}
                ).get("brain_run_id")
                session.artifacts["report_path"] = (
                    clarification_session.execution or {}
                ).get("report_path")
                if clarification_session.generated_task_spec_path:
                    session.artifacts["task_spec_path"] = clarification_session.generated_task_spec_path
            else:
                session.status = "blocked"
                session.errors.append("진단 실행 전에 source 선택이 필요합니다.")

        session.summary = self._build_summary(
            run_intent=run_intent,
            request_payload=request_payload,
            clarification_session=clarification_session,
        )
        if session.bridge_context:
            hint = session.bridge_context.get("context_hint")
            if isinstance(hint, dict):
                session.summary["bridge_context_hint"] = hint
        try:
            from engine.project_pack_activation import apply_active_pack_to_do_session

            apply_active_pack_to_do_session(root, session)
        except Exception as exc:
            logger.warning("active pack do context failed: %s", exc)
        try:
            from engine.project_improvement_interventions import (
                active_intervention_summary,
                intervention_metrics_context,
            )
            from engine.project_improvement_decisions import kept_improvements_summary

            intervention = active_intervention_summary(root)
            if intervention:
                session.summary["improvement_intervention"] = intervention
            kept = kept_improvements_summary(root)
            if kept:
                session.summary["kept_improvements"] = kept
            metrics_payload = intervention_metrics_context(root)
            if metrics_payload:
                session.metrics_context.update(metrics_payload)
        except Exception as exc:
            logger.warning("improvement intervention summary failed: %s", exc)

        if session.status != "blocked":
            session.status = self._resolve_status(
                base_result=base_result,
                clarification_session=clarification_session,
                execute=execute,
            )

        session.next_actions = self._build_next_actions(
            user_request=request_text,
            session_status=session.status,
            clarification_session=clarification_session,
            report_path=session.artifacts.get("report_path"),
            no_scan=no_scan,
        )
        memory_context = dict(run_intent.memory_context or {})
        session.next_actions = _dedupe([
            *list(memory_context.get("next_actions", [])),
            *list(session.next_actions),
        ])
        session.next_commands = NextCommandBuilder.from_actions(
            session.next_actions,
            stage=_current_stage_from_status(session.status),
        )

        if clarification_session is not None and clarification_session.status == "blocked":
            session.errors.extend(
                [item for item in clarification_session.errors if item not in session.errors]
            )
        if clarification_session is not None:
            session.warnings.extend(
                [item for item in clarification_session.warnings if item not in session.warnings]
            )

        self._append_continuation(
            session,
            action="do_requested",
            result=session.status,
            created={
                key: value
                for key, value in session.artifacts.items()
                if value
            },
        )
        self._save_session(root, session)
        return session

    @staticmethod
    def _is_project_initialized(project_root: Path) -> bool:
        """프로젝트가 초기화되었는지 확인한다."""
        return (project_root / ".cambrian" / "project.yaml").exists()

    @staticmethod
    def _load_request_payload(project_root: Path, request_ref: str | None) -> dict | None:
        """request artifact를 읽는다."""
        if not request_ref:
            return None
        request_path = Path(request_ref)
        candidate = request_path if request_path.is_absolute() else project_root / request_path
        return _load_yaml(candidate)

    def _find_open_clarification(self, project_root: Path, user_request: str) -> Path | None:
        """같은 요청의 최근 열린 clarification을 찾는다."""
        clarifications_dir = project_root / ".cambrian" / "clarifications"
        if not clarifications_dir.exists():
            return None
        clarification_files = sorted(
            clarifications_dir.glob("clarification_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        for clarification_path in clarification_files:
            payload = _load_yaml(clarification_path)
            if not payload:
                continue
            if str(payload.get("user_request", "")) != user_request:
                continue
            status = str(payload.get("status", "open"))
            if status in {"open", "answered", "ready"}:
                return clarification_path.resolve()
        return None

    @staticmethod
    def _apply_request_artifacts(
        *,
        session: DoSession,
        project_root: Path,
        request_payload: dict | None,
        request_path: Path | None,
    ) -> None:
        """request payload에서 do 세션 아티팩트를 채운다."""
        if request_path is not None:
            session.artifacts["request_path"] = _relative_to_project(request_path, project_root)
        elif request_payload and request_payload.get("request_id"):
            requests_dir = project_root / ".cambrian" / "requests"
            candidates = sorted(requests_dir.glob(f"request_{request_payload['request_id']}.yaml"))
            if candidates:
                session.artifacts["request_path"] = _relative_to_project(candidates[-1], project_root)

        if request_payload:
            context_ref = request_payload.get("context_scan_path") or request_payload.get("context_scan_ref")
            if isinstance(context_ref, str) and context_ref:
                session.artifacts["context_scan_path"] = context_ref
            if isinstance(request_payload.get("harness_context"), dict):
                session.harness_context = dict(request_payload.get("harness_context", {}))
            if isinstance(request_payload.get("agent_context"), dict):
                session.agent_context = dict(request_payload.get("agent_context", {}))
            if isinstance(request_payload.get("harness_policy_context"), dict):
                session.harness_policy_context = dict(request_payload.get("harness_policy_context", {}))
            if isinstance(request_payload.get("team_context"), dict):
                session.team_context = dict(request_payload.get("team_context", {}))
            if isinstance(request_payload.get("team_policy_context"), dict):
                session.team_policy_context = dict(request_payload.get("team_policy_context", {}))
            if isinstance(request_payload.get("template_context"), dict):
                session.template_context = dict(request_payload.get("template_context", {}))
            if isinstance(request_payload.get("win_lane_context"), dict):
                session.win_lane_context = dict(request_payload.get("win_lane_context", {}))
        try:
            from engine.project_bridge_context import relevant_bridge_context_hint_summary

            hint = relevant_bridge_context_hint_summary(project_root, session.user_request)
        except Exception as exc:
            logger.warning("bridge context hint summary failed: %s", exc)
            hint = {}
        if hint and int(hint.get("hint_count", 0) or 0) > 0:
            session.bridge_context = {
                "context_hint": hint,
                "source": "bridge_analysis",
            }
            session.summary["bridge_context_hint"] = hint

    @staticmethod
    def _build_summary(
        *,
        run_intent,
        request_payload: dict | None,
        clarification_session: ClarificationSession | None,
    ) -> dict:
        """화면 출력용 요약을 만든다."""
        found_sources: list[str] = []
        found_tests: list[str] = []
        selected_sources: list[str] = []
        selected_tests: list[str] = []
        needs: list[str] = []
        remembered: list[str] = []

        if clarification_session is not None:
            selected_sources = list(clarification_session.selected_context.get("sources", []))
            selected_tests = list(clarification_session.selected_context.get("tests", []))
            needs = [str(item).replace("_", " ") for item in clarification_session.missing_context]
            for question in clarification_session.questions:
                if question.kind == "source":
                    found_sources = [str(item.get("value", "")) for item in question.options if item.get("value")]
                elif question.kind == "test":
                    found_tests = [str(item.get("value", "")) for item in question.options if item.get("value")]
        elif request_payload:
            suggested_context = request_payload.get("suggested_context", {})
            if isinstance(suggested_context, dict):
                if suggested_context.get("top_source"):
                    found_sources.append(str(suggested_context["top_source"]))
                if suggested_context.get("top_test"):
                    found_tests.append(str(suggested_context["top_test"]))
            routing = request_payload.get("routing", {})
            if isinstance(routing, dict):
                needs = [str(item).replace("_", " ") for item in routing.get("required_context", [])]
            memory_context = request_payload.get("memory_context", {})
            if isinstance(memory_context, dict):
                remembered = [
                    str(item.get("text"))
                    for item in memory_context.get("relevant_lessons", [])
                    if isinstance(item, dict) and item.get("text")
                ]

        if not remembered:
            remembered = [
                str(item.get("text"))
                for item in (run_intent.memory_context or {}).get("relevant_lessons", [])
                if isinstance(item, dict) and item.get("text")
            ]

        return {
            "understood_as": str(run_intent.intent_type).replace("_", " "),
            "found_sources": _dedupe(found_sources),
            "found_tests": _dedupe(found_tests),
            "selected_sources": _dedupe(selected_sources),
            "selected_tests": _dedupe(selected_tests),
            "needs": _dedupe(needs),
            "remembered": _dedupe(remembered)[:3],
        }

    @staticmethod
    def _resolve_status(
        *,
        base_result,
        clarification_session: ClarificationSession | None,
        execute: bool,
    ) -> str:
        """do 세션 상태를 정한다."""
        if clarification_session is not None and execute:
            execution = clarification_session.execution or {}
            if execution.get("attempted") and execution.get("status") == "completed":
                return "diagnosed"
            if execution.get("attempted"):
                return "error"

        if clarification_session is not None:
            if clarification_session.status == "ready":
                return "prepared"
            if clarification_session.status in {"open", "answered"}:
                return "clarification_open"
            if clarification_session.status == "blocked":
                return "blocked"

        if base_result is not None:
            readiness = str(base_result.routing.get("execution_readiness", "needs_context"))
            if readiness == "needs_context":
                return "needs_context"
            if readiness == "blocked":
                return "blocked"
            return "prepared"

        return "error"

    def _build_next_actions(
        self,
        *,
        user_request: str,
        session_status: str,
        clarification_session: ClarificationSession | None,
        report_path: str | None,
        no_scan: bool,
    ) -> list[str]:
        """do 세션 다음 행동을 만든다."""
        if session_status == "initialized_required":
            return ["cambrian init --wizard"]

        if session_status == "diagnosed" and report_path:
            return [f"cambrian patch intent {report_path}"]

        if clarification_session is None:
            return [f"cambrian run {_quote_arg(user_request)}"]

        sources = list(clarification_session.selected_context.get("sources", []))
        tests = list(clarification_session.selected_context.get("tests", []))
        source_question = next((item for item in clarification_session.questions if item.kind == "source"), None)
        test_question = next((item for item in clarification_session.questions if item.kind == "test"), None)

        if session_status == "prepared" and sources:
            cmd = f"cambrian do {_quote_arg(user_request)} --source {_quote_arg(sources[0])}"
            if tests:
                cmd += f" --test {_quote_arg(tests[0])}"
            cmd += " --execute"
            return [cmd]

        actions: list[str] = []
        if source_question is not None and source_question.options:
            actions.append(
                f"cambrian do {_quote_arg(user_request)} --use-suggestion 1 --execute"
            )
            top_source = str(source_question.options[0].get("value", "path/to/file.py"))
            cmd = f"cambrian do {_quote_arg(user_request)} --source {_quote_arg(top_source)}"
            if test_question is not None and test_question.options:
                top_test = str(test_question.options[0].get("value", "path/to/test.py"))
                cmd += f" --test {_quote_arg(top_test)}"
            cmd += " --execute"
            actions.append(cmd)
        else:
            actions.append(
                f"cambrian do {_quote_arg(user_request)} --source \"path/to/file.py\" --test \"path/to/test.py\" --execute"
            )
            if no_scan:
                actions.append(f"cambrian context scan {_quote_arg(user_request)}")
        return _dedupe(actions)

    @staticmethod
    def _append_continuation(
        session: DoSession,
        *,
        action: str,
        result: str,
        created: dict | None = None,
    ) -> None:
        """세션 continuation history에 한 단계를 추가한다."""
        session.continuations.append(
            {
                "at": _now(),
                "action": action,
                "result": result,
                "created": dict(created or {}),
            }
        )

    def _save_session(self, project_root: Path, session: DoSession) -> None:
        """do 세션 artifact를 저장한다."""
        session.current_stage = _current_stage_from_status(session.status)
        self._store.save(project_root, session)

    @staticmethod
    def _refresh_metrics_context(
        *,
        session: DoSession,
        source_paths: list[str],
        test_paths: list[str],
        use_suggestion,
        explicit_agent_id: str | None,
    ) -> None:
        """do session의 운영 계측 필드를 최신 컨텍스트로 갱신한다."""
        lead_agent_id = ""
        if isinstance(session.agent_context, dict):
            lead_agent_id = str(session.agent_context.get("lead_agent_id", "") or "")
        team_id = ""
        if isinstance(session.team_context, dict):
            active_team = session.team_context.get("active_team")
            best_team = session.team_context.get("best_team")
            if isinstance(active_team, dict):
                team_id = str(active_team.get("team_id") or active_team.get("name") or "")
            elif isinstance(best_team, dict):
                team_id = str(best_team.get("team_id") or best_team.get("name") or "")
        template_name = ""
        if isinstance(session.template_context, dict):
            for key in ("current_template_name", "template_name", "selected_template_name", "name"):
                if session.template_context.get(key):
                    template_name = str(session.template_context.get(key))
                    break
        metrics = build_session_metrics_context(
            session_created_at=session.created_at,
            lead_agent_id=lead_agent_id or None,
            team_id=team_id or None,
            template_name=template_name or None,
            existing=session.metrics_context,
        )
        human = metrics.setdefault("human_interventions", {})
        human["source_selected_manually"] = bool(source_paths or use_suggestion is not None)
        human["test_selected_manually"] = bool(test_paths)
        human["explicit_agent_override"] = bool(explicit_agent_id)
        if isinstance(session.bridge_context, dict) and session.bridge_context:
            human["bridge_manual_ingest"] = bool(session.bridge_context.get("enabled") or session.bridge_context.get("context_hint"))
        if isinstance(session.template_context, dict):
            if session.template_context.get("canary_stage_id"):
                metrics["canary_stage_id"] = session.template_context.get("canary_stage_id")
            if session.template_context.get("template_selection_source"):
                metrics["template_selection_source"] = session.template_context.get("template_selection_source")
            if session.template_context.get("source_kind"):
                metrics["template_source_kind"] = session.template_context.get("source_kind")
        session.metrics_context = metrics


def render_do_summary(session: DoSession | dict) -> str:
    """do 세션 결과를 사람이 읽기 쉽게 렌더링한다."""
    payload = session.to_dict() if isinstance(session, DoSession) else dict(session)
    recovery_hint = hint_for_do_session(payload)
    if recovery_hint is not None:
        text = render_recovery_hint(recovery_hint, title="Cambrian Do")
        if str(payload.get("status", "")) == "initialized_required":
            text = text.replace(
                "\n\nProblem:",
                "\n\nStatus:\n  initialization required\n\nProblem:",
                1,
            )
        return text
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    lines = [
        "Cambrian Do",
        "==================================================",
        "Request:",
        f"  {payload.get('user_request', '')}",
        "",
        "Understood as:",
        f"  {summary.get('understood_as', 'unknown')}",
        "",
        "Project memory:",
        f"  {'loaded' if payload.get('project_initialized', False) else 'not initialized'}",
        "",
        "Selected skills:",
    ]
    for skill_id in payload.get("selected_skills", []):
        lines.append(f"  - {skill_id}")
    if not payload.get("selected_skills"):
        lines.append("  - none")
    remembered = list(summary.get("remembered", []))
    harness_context = payload.get("harness_context", {}) if isinstance(payload.get("harness_context"), dict) else {}
    agent_context = payload.get("agent_context", {}) if isinstance(payload.get("agent_context"), dict) else {}
    harness_policy_context = payload.get("harness_policy_context", {}) if isinstance(payload.get("harness_policy_context"), dict) else {}
    team_context = payload.get("team_context", {}) if isinstance(payload.get("team_context"), dict) else {}
    team_policy_context = payload.get("team_policy_context", {}) if isinstance(payload.get("team_policy_context"), dict) else {}
    template_context = payload.get("template_context", {}) if isinstance(payload.get("template_context"), dict) else {}
    win_lane_context = payload.get("win_lane_context", {}) if isinstance(payload.get("win_lane_context"), dict) else {}
    if remembered:
        lines.extend(["", "Remembered:"])
        for item in remembered[:3]:
            lines.append(f"  - {item}")
    active_agents = list(harness_context.get("active_agents", [])) if isinstance(harness_context, dict) else []
    if active_agents:
        lines.extend(["", "Active agents:"])
        for agent_id in active_agents:
            lines.append(f"  - {agent_id}")
    lead_agent_id = str(agent_context.get("lead_agent_id", "") or "")
    supporting_agent_ids = [str(item) for item in agent_context.get("supporting_agent_ids", []) if item]
    route_details = [
        item
        for item in agent_context.get("routes", [])
        if isinstance(item, dict)
    ]
    if lead_agent_id:
        lines.extend(["", "Lead agent:", f"  {lead_agent_id}"])
    if supporting_agent_ids:
        lines.extend(["", "Supporting agents:"])
        for agent_id in supporting_agent_ids:
            lines.append(f"  - {agent_id}")
    policy_hints = [str(item) for item in harness_policy_context.get("applied_hints", []) if item] if isinstance(harness_policy_context, dict) else []
    if policy_hints:
        lines.extend(["", "Harness policy:"])
        for item in policy_hints[:5]:
            lines.append(f"  - {item}")
    best_team = team_context.get("best_team") if isinstance(team_context, dict) else None
    if isinstance(best_team, dict) and best_team.get("name"):
        lines.extend(["", "Team hint:", f"  {best_team.get('name')} matches this request"])
    policy_hints_for_team = [str(item) for item in team_policy_context.get("applied_hints", []) if item] if isinstance(team_policy_context, dict) else []
    if policy_hints_for_team:
        lines.extend(["", "Accepted team policy:"])
        for item in policy_hints_for_team[:5]:
            lines.append(f"  - {item}")
    template_hints = [str(item) for item in template_context.get("applied_hints", []) if item] if isinstance(template_context, dict) else []
    if template_hints:
        lines.extend(["", "Harness template:"])
        for item in template_hints[:3]:
            lines.append(f"  - {item}")
    if win_lane_context:
        lines.extend(["", render_request_lane_fit(win_lane_context)])
    active_pack_context = summary.get("active_pack_context") if isinstance(summary.get("active_pack_context"), dict) else {}
    if active_pack_context:
        lines.extend(
            [
                "",
                "Active pack context:",
                f"  pack    : {active_pack_context.get('pack_id') or 'unknown'}",
                f"  team    : {active_pack_context.get('team') or 'none'}",
                f"  template: {active_pack_context.get('template') or 'none'}",
            ]
        )
        fit = str(summary.get("active_pack_fit") or "")
        if fit:
            lines.append(f"  fit     : {fit}")
    bridge_hint = summary.get("bridge_context_hint") if isinstance(summary.get("bridge_context_hint"), dict) else {}
    if bridge_hint:
        files = ", ".join(bridge_hint.get("recommended_files", [])[:3]) or "none"
        tests = ", ".join(bridge_hint.get("recommended_tests", [])[:3]) or "none"
        lines.extend([
            "",
            "Bridge hint:",
            f"  AI analysis suggested {files} / {tests} for this request",
        ])
    intervention_hint = summary.get("improvement_intervention") if isinstance(summary.get("improvement_intervention"), dict) else {}
    if intervention_hint:
        effects: list[str] = []
        if intervention_hint.get("test_first_bias"):
            effects.append("test-first")
        if intervention_hint.get("narrow_scope_bias"):
            effects.append("narrow-scope")
        if intervention_hint.get("review_support_bias"):
            effects.append("review-support")
        if intervention_hint.get("preferred_context_paths"):
            effects.append("context paths")
        lines.extend([
            "",
            "Improvement intervention:",
            f"  active: {intervention_hint.get('kind') or intervention_hint.get('active_intervention_id') or 'unknown'}",
        ])
        if effects:
            lines.append(f"  hints : {', '.join(effects)}")
    kept_hint = summary.get("kept_improvements") if isinstance(summary.get("kept_improvements"), dict) else {}
    if kept_hint:
        kept_effects: list[str] = []
        if kept_hint.get("test_first_bias"):
            kept_effects.append("test-first")
        if kept_hint.get("narrow_scope_bias"):
            kept_effects.append("narrow-scope")
        if kept_hint.get("review_support_bias"):
            kept_effects.append("review-support")
        if kept_hint.get("preferred_context_paths"):
            kept_effects.append("context paths")
        lines.extend([
            "",
            "Kept improvement:",
            f"  active: {', '.join(kept_hint.get('kept_fix_kinds', [])[:3]) or 'persistent overlay'}",
        ])
        if kept_effects:
            lines.append(f"  hints : {', '.join(kept_effects)}")
    team_decisions = team_context.get("decision_summary") if isinstance(team_context, dict) else None
    if isinstance(team_decisions, dict):
        accepted_hints = list(team_decisions.get("accepted_hints", []) if isinstance(team_decisions.get("accepted_hints"), list) else [])
        backup_teams = list(team_decisions.get("backup_teams", []) if isinstance(team_decisions.get("backup_teams"), list) else [])
        if accepted_hints:
            lines.extend(["", "Team staffing note:", f"  {accepted_hints[-1]}"])
        if backup_teams:
            lines.extend(["", "Backup team:", f"  {backup_teams[-1]}"])
    lead_route = next(
        (item for item in route_details if str(item.get("agent_id", "")) == lead_agent_id),
        None,
    )
    lead_reasons = list(lead_route.get("reasons", [])) if isinstance(lead_route, dict) else []
    if lead_reasons:
        lines.extend(["", "Why:"])
        for reason in lead_reasons[:3]:
            lines.append(f"  - {reason}")

    found_source = ", ".join(summary.get("selected_sources", []) or summary.get("found_sources", [])) or "none"
    found_test = ", ".join(summary.get("selected_tests", []) or summary.get("found_tests", [])) or "none"
    lines.extend([
        "",
        "Found:",
        f"  source: {found_source}",
        f"  test  : {found_test}",
    ])
    needs = list(summary.get("needs", []))
    if needs:
        lines.extend(["", "Needs:"])
        for item in needs:
            lines.append(f"  - {item}")
    lines.extend([
        "",
        "Status:",
        f"  {_human_status(str(payload.get('status', 'unknown')))}",
        "",
        "Created:",
    ])
    for label, key in (
        ("session", "session_path"),
        ("request", "request_path"),
        ("context", "context_scan_path"),
        ("clarification", "clarification_path"),
        ("task", "task_spec_path"),
        ("report", "report_path"),
    ):
        value = artifacts.get(key)
        if value:
            lines.append(f"  {label:<13}: {value}")
    if payload.get("warnings"):
        lines.extend(["", "Warnings:"])
        for item in payload.get("warnings", []):
            lines.append(f"  - {item}")
    if payload.get("errors"):
        lines.extend(["", "Errors:"])
        for item in payload.get("errors", []):
            lines.append(f"  - {item}")
    lines.extend(["", "Next:"])
    for action in payload.get("next_actions", []):
        lines.append(f"  {action}" if str(action).startswith("cambrian ") else f"  - {action}")
    return "\n".join(lines)
