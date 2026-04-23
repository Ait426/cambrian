"""Cambrian run clarification 도우미."""

from __future__ import annotations

import json
import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.brain.models import TaskSpec
from engine.brain.runner import RALFRunner
from engine.project_next import NextCommandBuilder
from engine.project_run_builder import DiagnoseTaskSpecBuilder

logger = logging.getLogger(__name__)


PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    ".git",
    ".cambrian",
    "__pycache__",
    ".pytest_cache",
)


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _clarification_id() -> str:
    """clarification 식별자를 생성한다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"clar-{stamp}-{secrets.token_hex(2)}"


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
    """YAML 파일을 안전하게 저장한다."""
    _atomic_write_text(
        path,
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
    )


def _load_yaml(path: Path) -> dict:
    """YAML 파일을 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML 최상위는 dict여야 합니다: {path}")
    return payload


def _load_json(path: Path) -> dict:
    """JSON 파일을 읽는다."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 최상위는 dict여야 합니다: {path}")
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


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _project_root_from_artifact(path: Path) -> Path:
    """artifact 경로에서 프로젝트 루트를 추론한다."""
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == ".cambrian":
            return parent.parent
    return resolved.parent


@dataclass
class ClarificationQuestion:
    """한 개의 clarification 질문."""

    id: str
    kind: str
    prompt: str
    required: bool
    options: list[dict] = field(default_factory=list)
    selected: str | None = None
    status: str = "open"

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ClarificationSession:
    """run clarification 세션."""

    schema_version: str
    clarification_id: str
    request_id: str
    created_at: str
    updated_at: str | None
    user_request: str
    request_artifact_path: str | None
    context_scan_ref: str | None
    status: str
    missing_context: list[str]
    questions: list[ClarificationQuestion]
    selected_context: dict
    memory_guidance: dict
    generated_task_spec_path: str | None
    next_actions: list[str]
    warnings: list[str]
    errors: list[str]
    next_commands: list[dict] = field(default_factory=list)
    artifact_path: str | None = None
    execution: dict | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["questions"] = [question.to_dict() for question in self.questions]
        return payload


class RunClarifier:
    """needs_context 요청을 clarification 세션으로 이어준다."""

    def __init__(self) -> None:
        self._diagnose_builder = DiagnoseTaskSpecBuilder()

    def create_from_request(
        self,
        request_artifact_path: Path,
        project_root: Path,
    ) -> ClarificationSession:
        """request artifact를 읽어 clarification artifact를 생성한다."""
        root = Path(project_root).resolve()
        request_path = Path(request_artifact_path).resolve()
        request_payload = _load_yaml(request_path)
        request_id = str(request_payload.get("request_id") or request_path.stem)
        user_request = str(request_payload.get("user_request", ""))
        clarification_id = _clarification_id()
        context_scan_ref = self._resolve_context_ref(request_payload)
        context_payload = self._load_context_payload(root, context_scan_ref)
        questions = self._build_questions(context_payload)
        memory_guidance = (
            dict(context_payload.get("memory_guidance", {}))
            if isinstance(context_payload.get("memory_guidance"), dict)
            else {}
        )
        missing_context = list(request_payload.get("routing", {}).get("required_context", []))
        if not missing_context:
            missing_context = ["target_file"]
        clarification_path = (
            root
            / ".cambrian"
            / "clarifications"
            / f"clarification_{clarification_id}_{request_id}.yaml"
        )
        session = ClarificationSession(
            schema_version="1.0.0",
            clarification_id=clarification_id,
            request_id=request_id,
            created_at=_now(),
            updated_at=None,
            user_request=user_request,
            request_artifact_path=_relative(request_path, root),
            context_scan_ref=context_scan_ref,
            status="open",
            missing_context=missing_context,
            questions=questions,
            selected_context={
                "sources": [],
                "tests": [],
                "mode": "diagnose",
            },
            memory_guidance=memory_guidance,
            generated_task_spec_path=None,
            next_actions=self._build_open_next_actions(request_id, questions),
            warnings=[],
            errors=[],
            next_commands=[],
            artifact_path=_relative(clarification_path, root),
            execution={
                "attempted": False,
                "status": "not_requested",
            },
        )
        self._save_session(session, clarification_path, root)
        return session

    def answer(
        self,
        clarification_path: Path,
        source: list[str] | None = None,
        tests: list[str] | None = None,
        use_suggestion: int | None = None,
        mode: str | None = None,
    ) -> ClarificationSession:
        """clarification 세션에 답변을 반영한다."""
        session_path = Path(clarification_path).resolve()
        root = _project_root_from_artifact(session_path)
        session = self.load(session_path)
        session.updated_at = _now()
        session.errors = []
        warnings = list(session.warnings)

        if mode:
            session.selected_context["mode"] = mode

        if use_suggestion is not None:
            source_question = self._find_question(session, "source")
            options = source_question.options if source_question is not None else []
            if use_suggestion < 1 or use_suggestion > len(options):
                session.status = "blocked"
                session.errors.append(f"invalid suggestion index: {use_suggestion}")
                session.next_actions = self._build_open_next_actions(session.request_id, session.questions)
                self._save_session(session, session_path, root)
                return session
            selected_value = str(options[use_suggestion - 1].get("value", ""))
            if selected_value:
                session.selected_context["sources"] = [selected_value]
                test_question = self._find_question(session, "test")
                test_options = test_question.options if test_question is not None else []
                if test_options and not session.selected_context.get("tests"):
                    top_test = str(test_options[0].get("value", ""))
                    if top_test:
                        session.selected_context["tests"] = [top_test]

        if source:
            session.selected_context["sources"] = _dedupe([str(item) for item in source if item])
        if tests is not None and tests:
            session.selected_context["tests"] = _dedupe([str(item) for item in tests if item])

        valid_sources, source_errors = self._validate_selected_paths(
            root,
            list(session.selected_context.get("sources", [])),
            kind="source",
        )
        valid_tests, test_errors = self._validate_selected_paths(
            root,
            list(session.selected_context.get("tests", [])),
            kind="test",
        )
        session.selected_context["sources"] = valid_sources
        session.selected_context["tests"] = valid_tests
        session.errors.extend(source_errors)
        session.errors.extend(test_errors)

        if session.errors:
            session.status = "blocked"
            session.missing_context = ["target_file"]
            session.generated_task_spec_path = None
            session.next_actions = [
                "안전한 source/test 경로를 다시 선택하세요.",
                f"cambrian clarify {session.request_id} --source path/to/file.py --test path/to/test.py",
            ]
            self._sync_questions(session)
            self._save_session(session, session_path, root)
            return session

        session.warnings = warnings
        self._sync_questions(session)
        session = self.build_task_if_ready(session, root)
        self._save_session(session, session_path, root)
        return session

    def build_task_if_ready(
        self,
        session: ClarificationSession,
        project_root: Path,
    ) -> ClarificationSession:
        """선택이 충분하면 diagnose-only TaskSpec을 만든다."""
        root = Path(project_root).resolve()
        sources = list(session.selected_context.get("sources", []))
        tests = list(session.selected_context.get("tests", []))
        mode = str(session.selected_context.get("mode", "diagnose"))
        session.missing_context = []
        session.generated_task_spec_path = None

        if mode != "diagnose":
            session.status = "answered"
            session.next_actions = [
                "review 모드는 아직 실행형으로 연결되지 않습니다.",
                f"cambrian clarify {session.request_id} --mode diagnose --source path/to/file.py",
            ]
            return session

        if not sources:
            session.status = "open"
            session.missing_context = ["target_file"]
            session.next_actions = self._build_open_next_actions(session.request_id, session.questions)
            return session

        context_payload = self._load_context_payload(root, session.context_scan_ref)
        build = self._diagnose_builder.build_from_context(
            user_request=session.user_request,
            context_scan=context_payload,
            selected_sources=sources,
            selected_tests=tests,
            request_id=session.clarification_id,
            project_config={},
        )
        task_path = (
            root
            / ".cambrian"
            / "tasks"
            / f"task_diagnose_{session.clarification_id}.yaml"
        )
        build.task_spec.to_yaml(task_path)
        session.generated_task_spec_path = _relative(task_path, root)
        session.status = "ready"
        if not tests:
            session.warnings = _dedupe([
                *session.warnings,
                "관련 테스트를 선택하지 않아 파일 inspect만 수행합니다.",
            ])
        session.next_actions = [
            f"cambrian clarify {session.request_id} --execute",
            f"cambrian brain run {session.generated_task_spec_path}",
        ]
        return session

    def execute_ready(
        self,
        clarification_path: Path,
        *,
        max_iterations: int = 5,
    ) -> ClarificationSession:
        """ready 상태 clarification을 diagnose-only로 실행한다."""
        session_path = Path(clarification_path).resolve()
        root = _project_root_from_artifact(session_path)
        session = self.load(session_path)

        if session.status != "ready" or not session.generated_task_spec_path:
            session.execution = {
                "attempted": True,
                "status": "blocked",
                "errors": ["clarification is not ready for execution"],
            }
            session.updated_at = _now()
            self._save_session(session, session_path, root)
            return session

        task_path = root / session.generated_task_spec_path
        task_spec = TaskSpec.from_yaml(task_path)
        runner = RALFRunner(
            runs_dir=root / ".cambrian" / "brain" / "runs",
            workspace=root,
        )
        state = runner.run(task_spec, max_iterations=max_iterations)
        report_path = root / ".cambrian" / "brain" / "runs" / state.run_id / "report.json"
        execution: dict = {
            "attempted": True,
            "status": state.status,
            "brain_run_id": state.run_id,
            "report_path": _relative(report_path, root),
        }
        try:
            report_payload = _load_json(report_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            execution["errors"] = [f"report load failed: {exc}"]
        else:
            diagnostics = report_payload.get("diagnostics", {})
            if isinstance(diagnostics, dict):
                execution["diagnostics"] = diagnostics
        session.execution = execution
        session.updated_at = _now()
        session.next_actions = self._build_execution_next_actions(session)
        self._save_session(session, session_path, root)
        return session

    def resolve_artifact_path(self, ref: str | Path, project_root: Path) -> Path:
        """request_id, clarification_id, path를 clarification artifact로 해석한다."""
        root = Path(project_root).resolve()
        candidate = Path(ref)
        if candidate.exists():
            return candidate.resolve()

        clarifications_dir = root / ".cambrian" / "clarifications"
        if not clarifications_dir.exists():
            raise FileNotFoundError("clarification artifact를 찾을 수 없습니다. 먼저 cambrian run을 실행하세요.")

        matches = sorted(clarifications_dir.glob("clarification_*.yaml"))
        for path in matches:
            try:
                payload = _load_yaml(path)
            except (OSError, yaml.YAMLError, ValueError):
                continue
            if str(payload.get("request_id", "")) == str(ref):
                return path.resolve()
            if str(payload.get("clarification_id", "")) == str(ref):
                return path.resolve()
        raise FileNotFoundError(f"clarification artifact를 찾지 못했습니다: {ref}")

    def load(self, clarification_path: Path | str) -> ClarificationSession:
        """clarification artifact를 로드한다."""
        path = Path(clarification_path)
        payload = _load_yaml(path)
        questions = [
            ClarificationQuestion(
                id=str(item.get("id", "")),
                kind=str(item.get("kind", "")),
                prompt=str(item.get("prompt", "")),
                required=bool(item.get("required", False)),
                options=list(item.get("options", [])),
                selected=item.get("selected"),
                status=str(item.get("status", "open")),
            )
            for item in payload.get("questions", [])
            if isinstance(item, dict)
        ]
        return ClarificationSession(
            schema_version=str(payload.get("schema_version", "1.0.0")),
            clarification_id=str(payload.get("clarification_id", path.stem)),
            request_id=str(payload.get("request_id", "")),
            created_at=str(payload.get("created_at", "")),
            updated_at=payload.get("updated_at"),
            user_request=str(payload.get("user_request", "")),
            request_artifact_path=payload.get("request_artifact_path"),
            context_scan_ref=payload.get("context_scan_ref"),
            status=str(payload.get("status", "open")),
            missing_context=list(payload.get("missing_context", [])),
            questions=questions,
            selected_context=dict(payload.get("selected_context", {})),
            memory_guidance=dict(payload.get("memory_guidance", {})) if isinstance(payload.get("memory_guidance"), dict) else {},
            generated_task_spec_path=payload.get("generated_task_spec_path"),
            next_actions=list(payload.get("next_actions", [])),
            warnings=list(payload.get("warnings", [])),
            errors=list(payload.get("errors", [])),
            next_commands=list(payload.get("next_commands", [])),
            artifact_path=payload.get("artifact_path"),
            execution=dict(payload.get("execution", {})) if isinstance(payload.get("execution"), dict) else None,
        )

    @staticmethod
    def _resolve_context_ref(request_payload: dict) -> str | None:
        """request payload에서 context scan ref를 고른다."""
        raw = request_payload.get("context_scan_ref")
        if isinstance(raw, str) and raw:
            return raw
        context_scan = request_payload.get("context_scan", {})
        if isinstance(context_scan, dict):
            path = context_scan.get("path")
            if isinstance(path, str) and path:
                return path
        return None

    @staticmethod
    def _build_questions(context_payload: dict) -> list[ClarificationQuestion]:
        """context payload에서 source/test 질문을 만든다."""
        source_options = RunClarifier._candidate_options(
            context_payload.get("suggested_sources")
            or context_payload.get("source_candidates", [])
        )
        test_options = RunClarifier._candidate_options(
            context_payload.get("suggested_tests")
            or context_payload.get("test_candidates", [])
        )
        return [
            ClarificationQuestion(
                id="q-source",
                kind="source",
                prompt="어떤 source 파일부터 Cambrian이 진단할까요?",
                required=True,
                options=source_options,
            ),
            ClarificationQuestion(
                id="q-test",
                kind="test",
                prompt="같이 돌릴 관련 테스트가 있다면 선택하세요.",
                required=False,
                options=test_options,
            ),
        ]

    @staticmethod
    def _candidate_options(candidates: list[dict]) -> list[dict]:
        """context candidate를 clarification option 형태로 변환한다."""
        options: list[dict] = []
        for index, item in enumerate(candidates[:5], start=1):
            if not isinstance(item, dict):
                continue
            value = str(item.get("path", "")).strip()
            if not value:
                continue
            options.append(
                {
                    "id": f"option-{index}",
                    "value": value,
                    "label": value,
                    "confidence": item.get("score", 0.0),
                    "reason": item.get("why") or "; ".join(item.get("reasons", [])),
                    "memory_boosted": bool(item.get("memory_boosted", False)),
                    "memory_lesson_ids": list(item.get("memory_lesson_ids", [])),
                }
            )
        return options

    @staticmethod
    def _build_open_next_actions(
        request_id: str,
        questions: list[ClarificationQuestion],
    ) -> list[str]:
        """open clarification의 다음 행동을 만든다."""
        actions = [f"cambrian clarify {request_id} --use-suggestion 1"]
        source_question = next((item for item in questions if item.kind == "source"), None)
        test_question = next((item for item in questions if item.kind == "test"), None)
        top_source = (
            str(source_question.options[0].get("value", ""))
            if source_question and source_question.options else "path/to/file.py"
        )
        top_test = (
            str(test_question.options[0].get("value", ""))
            if test_question and test_question.options else "path/to/test.py"
        )
        actions.append(
            f"cambrian clarify {request_id} --source {top_source} --test {top_test}"
        )
        return _dedupe(actions)

    @staticmethod
    def _validate_selected_paths(
        project_root: Path,
        paths: list[str],
        *,
        kind: str,
    ) -> tuple[list[str], list[str]]:
        """선택된 project 상대 경로를 검증한다."""
        valid: list[str] = []
        errors: list[str] = []
        for raw_path in _dedupe(paths):
            path = Path(raw_path)
            if path.is_absolute() or ".." in path.parts:
                errors.append(f"selected {kind} path is unsafe: {raw_path}")
                continue
            normalized = raw_path.replace("\\", "/")
            if any(
                normalized == prefix or normalized.startswith(f"{prefix}/")
                for prefix in PROTECTED_PATH_PREFIXES
            ):
                errors.append(f"selected {kind} path is unsafe: {raw_path}")
                continue
            candidate = (project_root / path).resolve()
            try:
                candidate.relative_to(project_root.resolve())
            except ValueError:
                errors.append(f"selected {kind} path is outside project root: {raw_path}")
                continue
            if not candidate.exists():
                errors.append(f"selected {kind} file does not exist: {raw_path}")
                continue
            valid.append(raw_path.replace("\\", "/"))
        return valid, errors

    @staticmethod
    def _find_question(
        session: ClarificationSession,
        kind: str,
    ) -> ClarificationQuestion | None:
        """kind로 질문을 찾는다."""
        return next((question for question in session.questions if question.kind == kind), None)

    @staticmethod
    def _sync_questions(session: ClarificationSession) -> None:
        """selected_context를 질문 상태에 반영한다."""
        source_question = RunClarifier._find_question(session, "source")
        if source_question is not None:
            sources = list(session.selected_context.get("sources", []))
            source_question.selected = sources[0] if sources else None
            source_question.status = "answered" if sources else "open"

        test_question = RunClarifier._find_question(session, "test")
        if test_question is not None:
            tests = list(session.selected_context.get("tests", []))
            test_question.selected = tests[0] if tests else None
            test_question.status = "answered" if tests else "open"

    def _load_context_payload(
        self,
        project_root: Path,
        context_ref: str | None,
    ) -> dict:
        """context artifact를 읽고 없으면 빈 payload를 반환한다."""
        if not context_ref:
            return {}
        path = Path(context_ref)
        context_path = path if path.is_absolute() else project_root / path
        if not context_path.exists():
            logger.warning("context artifact 없음: %s", context_path)
            return {}
        try:
            return _load_yaml(context_path)
        except (OSError, yaml.YAMLError, ValueError) as exc:
            logger.warning("context artifact 로드 실패: %s (%s)", context_path, exc)
            return {}

    def _build_execution_next_actions(
        self,
        session: ClarificationSession,
    ) -> list[str]:
        """diagnose 실행 후 다음 행동을 만든다."""
        execution = session.execution or {}
        diagnostics = execution.get("diagnostics", {})
        sources = list(session.selected_context.get("sources", []))
        actions: list[str] = []
        if isinstance(diagnostics, dict):
            actions.extend(str(item) for item in diagnostics.get("next_actions", []))
        if not actions and sources:
            actions.append(
                f"cambrian patch propose --from-diagnosis {execution.get('report_path', '<report.json>')} --target {sources[0]} --old-text \"...\" --new-text \"...\""
            )
        return _dedupe(actions)

    def _save_session(
        self,
        session: ClarificationSession,
        clarification_path: Path,
        project_root: Path,
    ) -> None:
        """clarification 세션과 연결된 request artifact를 함께 갱신한다."""
        session.artifact_path = _relative(clarification_path, project_root)
        session.next_commands = NextCommandBuilder.from_actions(
            list(session.next_actions),
            stage=session.status,
        )
        _dump_yaml(clarification_path, session.to_dict())
        self._sync_request_artifact(session, project_root)

    @staticmethod
    def _sync_request_artifact(
        session: ClarificationSession,
        project_root: Path,
    ) -> None:
        """연결된 request artifact에 clarification 상태를 반영한다."""
        if not session.request_artifact_path:
            return
        request_path = project_root / session.request_artifact_path
        if not request_path.exists():
            return
        try:
            payload = _load_yaml(request_path)
        except (OSError, yaml.YAMLError, ValueError):
            return
        payload["clarification"] = {
            "enabled": True,
            "path": session.artifact_path,
            "status": session.status,
            "generated_task_spec_path": session.generated_task_spec_path,
            "next_commands": list(session.next_commands),
        }
        if session.execution:
            payload["clarification"]["execution"] = dict(session.execution)
        payload["next_commands"] = list(session.next_commands)
        _dump_yaml(request_path, payload)


def render_clarification_summary(
    session: ClarificationSession | dict,
) -> str:
    """clarification 세션을 사람이 읽기 좋게 렌더링한다."""
    from engine.project_errors import hint_for_clarification, render_recovery_hint

    payload = session.to_dict() if isinstance(session, ClarificationSession) else dict(session)
    recovery_hint = hint_for_clarification(payload)
    if recovery_hint is not None:
        return render_recovery_hint(recovery_hint)
    execution = payload.get("execution", {}) if isinstance(payload.get("execution"), dict) else {}
    selected_context = payload.get("selected_context", {}) if isinstance(payload.get("selected_context"), dict) else {}
    questions = list(payload.get("questions", []))

    if execution.get("attempted") and execution.get("status") == "completed":
        diagnostics = execution.get("diagnostics", {}) if isinstance(execution.get("diagnostics"), dict) else {}
        lines = [
            "Cambrian이 선택한 문맥을 진단했습니다.",
            "",
            "Inspected:",
        ]
        for item in diagnostics.get("inspected_files", []):
            lines.append(f"  {item.get('path')}")
        lines.extend(["", "Tests:"])
        related_tests = list(diagnostics.get("related_tests", []))
        test_results = diagnostics.get("test_results", {}) if isinstance(diagnostics.get("test_results"), dict) else {}
        if related_tests:
            for test_path in related_tests:
                label = "failed" if int(test_results.get("failed", 0) or 0) > 0 else "passed"
                lines.append(f"  {test_path}: {label}")
        else:
            lines.append("  none")
        lines.extend(["", "Next:"])
        for action in payload.get("next_actions", []):
            lines.append(f"  - {action}")
        return "\n".join(lines)

    if payload.get("status") == "blocked":
        lines = [
            "Cambrian이 계속 진행할 수 없습니다.",
            "",
            "Reason:",
        ]
        for item in payload.get("errors", []):
            lines.append(f"  - {item}")
        lines.extend(["", "No files changed."])
        return "\n".join(lines)

    if payload.get("status") == "ready":
        sources = list(selected_context.get("sources", []))
        tests = list(selected_context.get("tests", []))
        lines = [
            "Cambrian이 diagnose-only 작업을 준비했습니다.",
            "",
            "Selected:",
            f"  source: {', '.join(sources) if sources else 'none'}",
            f"  test  : {', '.join(tests) if tests else 'none'}",
            "",
            "Created:",
            f"  task: {payload.get('generated_task_spec_path')}",
            "",
            "Next:",
        ]
        for action in payload.get("next_actions", []):
            lines.append(f"  - {action}")
        return "\n".join(lines)

    source_question = next(
        (item for item in questions if isinstance(item, dict) and item.get("kind") == "source"),
        None,
    )
    test_question = next(
        (item for item in questions if isinstance(item, dict) and item.get("kind") == "test"),
        None,
    )
    lines = [
        "Cambrian이 조금만 더 문맥이 필요합니다.",
        "",
        "Request:",
        f"  {payload.get('user_request', '')}",
        "",
        "Choose a source file:",
    ]
    if source_question and source_question.get("options"):
        for index, option in enumerate(source_question.get("options", []), start=1):
            lines.append(
                f"  {index}. {option.get('value')}      score={option.get('confidence')}"
            )
            lines.append(f"     why: {option.get('reason') or 'matched request terms'}")
    else:
        lines.append("  none")
    lines.extend(["", "Suggested test:"])
    if test_question and test_question.get("options"):
        option = test_question["options"][0]
        lines.append(f"  {option.get('value')}")
    else:
        lines.append("  none")
    lines.extend(["", "Next:"])
    for action in payload.get("next_actions", []):
        lines.append(f"  {action}")
    return "\n".join(lines)
