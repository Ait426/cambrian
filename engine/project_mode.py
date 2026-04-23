"""Cambrian 프로젝트 모드 UX 셸."""

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
from engine.project_activity import ProjectActivityReader
from engine.project_clarifier import RunClarifier
from engine.project_context import ProjectContextScanner
from engine.project_errors import default_last_error_path, load_last_error
from engine.project_memory import (
    ProjectMemoryStore,
    build_memory_context,
    default_memory_path,
    load_project_memory,
    memory_override_counts,
)
from engine.project_memory_hygiene import load_memory_hygiene
from engine.project_notes import ProjectNotesStore, default_notes_dir
from engine.project_router import (
    ExecutableTaskSpecBuilder,
    ProjectSkillRouter,
    RunIntent,
)
from engine.project_run_builder import DiagnoseTaskSpecBuilder
from engine.project_timeline import ProjectTimelineReader

logger = logging.getLogger(__name__)


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _slug(prefix: str) -> str:
    """짧은 식별자를 생성한다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{secrets.token_hex(2)}"


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


def _dump_json(path: Path, payload: dict) -> None:
    """JSON 파일을 저장한다."""
    _atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )


def _load_yaml(path: Path, warnings: list[str] | None = None) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        message = f"YAML 읽기 실패: {path} ({exc})"
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        message = f"YAML 형식 오류: {path} 최상위는 dict여야 합니다."
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    return payload


def _load_json(path: Path, warnings: list[str] | None = None) -> dict | None:
    """JSON 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        message = f"JSON 읽기 실패: {path} ({exc})"
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    if not isinstance(payload, dict):
        message = f"JSON 형식 오류: {path} 최상위는 dict여야 합니다."
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    return payload


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


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
    """순서를 유지하면서 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


@dataclass
class ProjectInitResult:
    """프로젝트 초기화 결과."""

    status: str
    project_root: str
    project_name: str
    project_type: str
    test_command: str
    config_paths: dict[str, str]
    recommended_skills: list[str]
    detected: dict
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectRunResult:
    """프로젝트 모드 run 준비 결과."""

    status: str
    request_id: str
    user_request: str
    request_path: str
    task_spec_path: str
    selected_skills: list[str]
    routing: dict
    project_context: dict
    execution_plan: dict
    suggested_checks: list[str]
    next_actions: list[str]
    execution: dict
    context_scan_path: str | None = None
    suggested_context: dict = field(default_factory=dict)
    selected_context: dict = field(default_factory=dict)
    clarification: dict = field(default_factory=dict)
    memory_context: dict = field(default_factory=dict)
    diagnose_only: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProjectStatus:
    """프로젝트 상태 요약."""

    initialized: bool
    project_root: str
    project: dict = field(default_factory=dict)
    onboarding: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    recommended_skills: list[str] = field(default_factory=list)
    memory: dict = field(default_factory=dict)
    recent_requests: list[dict] = field(default_factory=list)
    recent_context_scan: dict = field(default_factory=dict)
    recent_do_session: dict = field(default_factory=dict)
    open_clarification: dict = field(default_factory=dict)
    recent_diagnostic: dict = field(default_factory=dict)
    recent_patch_intent: dict = field(default_factory=dict)
    recent_patch_proposal: dict = field(default_factory=dict)
    latest_patch_adoption: dict = field(default_factory=dict)
    recent_journey: list[dict] = field(default_factory=list)
    recent_lessons: list[str] = field(default_factory=list)
    active_sessions: list[dict] = field(default_factory=list)
    recent_sessions: list[dict] = field(default_factory=list)
    usage_summary: dict = field(default_factory=dict)
    alpha_readiness: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    last_error: dict = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ProjectInitializer:
    """Cambrian 프로젝트 모드 초기화기."""

    CONFIG_FILES: tuple[str, ...] = (
        "project.yaml",
        "rules.yaml",
        "skills.yaml",
        "profile.yaml",
    )

    def init(
        self,
        project_root: str | Path,
        *,
        name: str | None = None,
        project_type: str | None = None,
        stack: str | None = None,
        test_cmd: str | None = None,
        force: bool = False,
    ) -> ProjectInitResult:
        """프로젝트 모드 구성 파일을 생성한다."""
        root = Path(project_root).resolve()
        cambrian_dir = root / ".cambrian"
        cambrian_dir.mkdir(parents=True, exist_ok=True)

        config_paths = {
            file_name: str(cambrian_dir / file_name)
            for file_name in self.CONFIG_FILES
        }
        existing = [
            str(cambrian_dir / file_name)
            for file_name in self.CONFIG_FILES
            if (cambrian_dir / file_name).exists()
        ]
        if existing and not force:
            return ProjectInitResult(
                status="blocked",
                project_root=str(root),
                project_name=name or root.name,
                project_type=project_type or "unknown",
                test_command=test_cmd or "",
                config_paths=config_paths,
                recommended_skills=[],
                detected={},
                warnings=[
                    "이미 초기화된 파일이 있어 덮어쓰지 않았습니다.",
                    *existing,
                ],
            )

        detection = self._detect(root)
        effective_type = project_type or detection["project_type"]
        effective_name = name or root.name
        effective_test_cmd = test_cmd or detection["test_command"]
        effective_stack = stack or detection["stack"]
        recommended_skills = self._recommended_skills(effective_type)

        project_payload = {
            "schema_version": "1.0.0",
            "project": {
                "name": effective_name,
                "type": effective_type,
                "root": ".",
                "created_at": _now(),
            },
            "detected": {
                "git": detection["git"],
                "python": detection["python"],
                "pytest": detection["pytest"],
                "package_files": detection["package_files"],
            },
            "test": {
                "command": effective_test_cmd,
                "related_test_strategy": "prefer_related_tests",
            },
            "ai_work": {
                "primary_use_cases": self._primary_use_cases(effective_type),
            },
            "notes": [],
        }
        if effective_stack:
            project_payload["project"]["stack"] = effective_stack

        rules_payload = {
            "schema_version": "1.0.0",
            "safety": {
                "require_tests_before_adoption": True,
                "never_auto_adopt": True,
                "preserve_source_artifacts": True,
            },
            "workspace": {
                "protect_paths": [
                    ".git",
                    ".cambrian",
                    "__pycache__",
                    ".pytest_cache",
                ],
            },
            "review": {
                "prefer_small_changes": True,
                "require_human_reason_for_adoption": True,
            },
            "output": {
                "human_readable_summary": True,
                "record_lessons": True,
            },
        }

        skills_payload = {
            "schema_version": "1.0.0",
            "recommended_skills": recommended_skills,
            "selection": {
                "default": [
                    item["id"]
                    for item in recommended_skills
                    if item["id"] in {
                        "bug_fix",
                        "regression_test",
                        "review_candidate",
                        "small_refactor",
                    }
                ],
            },
        }

        profile_payload = {
            "schema_version": "1.0.0",
            "mode": "balanced",
            "defaults": {
                "max_variants": 2,
                "max_iterations": 5,
                "adoption": "explicit_only",
                "feedback": "enabled",
                "ledger": "enabled",
                "pressure": "enabled",
            },
            "ux": {
                "show_process": True,
                "show_lessons": True,
                "hide_internal_terms": True,
            },
        }

        _dump_yaml(cambrian_dir / "project.yaml", project_payload)
        _dump_yaml(cambrian_dir / "rules.yaml", rules_payload)
        _dump_yaml(cambrian_dir / "skills.yaml", skills_payload)
        _dump_yaml(cambrian_dir / "profile.yaml", profile_payload)

        return ProjectInitResult(
            status="initialized",
            project_root=str(root),
            project_name=effective_name,
            project_type=effective_type,
            test_command=effective_test_cmd,
            config_paths=config_paths,
            recommended_skills=[item["id"] for item in recommended_skills],
            detected=project_payload["detected"],
            warnings=[],
        )

    @staticmethod
    def _detect(project_root: Path) -> dict:
        """프로젝트 기본 정보를 감지한다."""
        package_files: list[str] = []
        for candidate in (
            "pyproject.toml",
            "pytest.ini",
            "requirements.txt",
            "setup.py",
            "package.json",
        ):
            if (project_root / candidate).exists():
                package_files.append(candidate)

        has_python = any(
            item in package_files
            for item in ("pyproject.toml", "requirements.txt", "setup.py")
        ) or any(project_root.glob("*.py"))
        has_pytest = (project_root / "pytest.ini").exists()
        pyproject_path = project_root / "pyproject.toml"
        if not has_pytest and pyproject_path.exists():
            try:
                has_pytest = "pytest" in pyproject_path.read_text(encoding="utf-8")
            except OSError:
                logger.warning("pyproject.toml 읽기 실패: %s", pyproject_path)
        if not has_pytest:
            has_pytest = (project_root / "tests").exists()

        return {
            "git": (project_root / ".git").exists(),
            "python": has_python,
            "pytest": has_pytest,
            "package_files": package_files,
            "project_type": "python" if has_python else "generic",
            "stack": "python" if has_python else "",
            "test_command": "pytest -q" if has_pytest else "",
        }

    @staticmethod
    def _primary_use_cases(project_type: str) -> list[str]:
        """프로젝트 타입에 맞는 기본 사용 목적을 반환한다."""
        if project_type == "python":
            return [
                "bug_fix",
                "test_generation",
                "small_refactor",
                "review_candidate",
            ]
        return ["bug_fix", "review_candidate"]

    @staticmethod
    def _recommended_skills(project_type: str) -> list[dict]:
        """프로젝트 타입에 맞는 추천 스킬 목록을 만든다."""
        skills = [
            {
                "id": "bug_fix",
                "label": "Bug fix",
                "description": "Diagnose and patch small defects with related tests.",
            },
            {
                "id": "regression_test",
                "label": "Regression test",
                "description": "Add or run tests to confirm behavior.",
            },
            {
                "id": "small_refactor",
                "label": "Small refactor",
                "description": "Improve code with minimal surface area.",
            },
            {
                "id": "review_candidate",
                "label": "Review candidate",
                "description": "Compare approaches and pick safer winner.",
            },
            {
                "id": "test_generation",
                "label": "Test generation",
                "description": "Create or strengthen tests around the request.",
            },
            {
                "id": "docs_update",
                "label": "Docs update",
                "description": "Update documentation and keep it reviewable.",
            },
        ]
        if project_type != "python":
            return [skills[0], skills[3], skills[5]]
        return skills


class ProjectRunPreparer:
    """프로젝트 모드 자연어 요청 준비기."""

    def __init__(self) -> None:
        self._router = ProjectSkillRouter()
        self._builder = ExecutableTaskSpecBuilder()
        self._context_scanner = ProjectContextScanner()
        self._diagnose_builder = DiagnoseTaskSpecBuilder()

    def prepare(
        self,
        project_root: str | Path,
        user_request: str,
        *,
        skill_ids: list[str] | None = None,
        target: str | None = None,
        tests: list[str] | None = None,
        output_paths: list[str] | None = None,
        action: str | None = None,
        content: str | None = None,
        content_file: str | None = None,
        old_text: str | None = None,
        new_text: str | None = None,
        use_top_context: bool = False,
        context_path: str | None = None,
        source_paths: list[str] | None = None,
        diagnose_only: bool = False,
        no_scan: bool = False,
        execute: bool = False,
        dry_run: bool = False,
        max_variants: int | None = None,
        max_iterations: int | None = None,
        out_dir: str | Path | None = None,
    ) -> ProjectRunResult:
        """자연어 요청을 request/task artifact로 안전하게 준비한다."""
        root = Path(project_root).resolve()
        configs = self._load_configs(root)
        request_id = _slug("req")
        memory_context = build_memory_context(root, user_request, limit=3)

        requests_dir = (
            Path(out_dir).resolve()
            if out_dir is not None
            else root / ".cambrian" / "requests"
        )
        tasks_dir = root / ".cambrian" / "tasks"
        context_dir = root / ".cambrian" / "context"
        request_path = requests_dir / f"request_{request_id}.yaml"
        task_path = tasks_dir / f"task_{request_id}.yaml"

        test_command = configs["project"].get("test", {}).get("command", "")
        project_meta = configs["project"].get("project", {})
        profile_defaults = configs["profile"].get("defaults", {})
        effective_max_iterations = (
            max_iterations
            if max_iterations is not None
            else int(profile_defaults.get("max_iterations", 5))
        )
        _ = (
            max_variants
            if max_variants is not None
            else int(profile_defaults.get("max_variants", 2))
        )

        diagnose_mode = bool(
            diagnose_only
            or use_top_context
            or context_path
            or list(source_paths or [])
        )
        diagnose_conflict = diagnose_mode and (action or "none") != "none"

        explicit_options = {
            "skill_ids": list(skill_ids or []),
            "project_root": str(root),
            "target": target,
            "tests": list(tests or []),
            "outputs": list(output_paths or []),
            "action": action or "none",
            "content": content,
            "content_file": content_file,
            "old_text": old_text,
            "new_text": new_text,
        }
        run_intent = self._router.route(
            user_request=user_request,
            project_config=configs["project"],
            rules=configs["rules"],
            skills=configs["skills"],
            profile=configs["profile"],
            explicit_options=explicit_options,
        )
        memory_context = dict(run_intent.memory_context or memory_context)
        memory_warnings = self._memory_warnings(memory_context)
        memory_next_actions = self._memory_next_actions(memory_context)

        if diagnose_conflict:
            run_intent = RunIntent(
                intent_type=run_intent.intent_type,
                confidence=run_intent.confidence,
                routes=run_intent.routes,
                required_context=[],
                safety_warnings=_dedupe([
                    *run_intent.safety_warnings,
                    "진단 전용 실행과 write/patch action은 함께 사용할 수 없습니다.",
                ]),
                execution_readiness="blocked",
                memory_context=memory_context,
            )

        context_payload: dict | None = None
        context_scan_relpath: str | None = None
        suggested_context: dict = {}
        selected_context: dict = {"sources": [], "tests": [], "warnings": []}
        clarification: dict = {}

        should_auto_scan = (
            not no_scan and run_intent.execution_readiness == "needs_context"
        )
        should_scan_for_diagnose = bool(use_top_context or diagnose_mode)

        if context_path:
            loaded_context = self._context_scanner.load(context_path)
            loaded_context["_source_path"] = str(context_path)
            context_payload = loaded_context
            context_scan_relpath = _relative_to_project(Path(context_path), root)
        elif should_scan_for_diagnose or should_auto_scan:
            scan_result = self._context_scanner.scan(
                user_request=user_request,
                project_root=root,
                request_id=request_id,
                project_config=configs["project"],
                rules=configs["rules"],
            )
            context_artifact_path = context_dir / f"context_{request_id}.yaml"
            self._context_scanner.save(scan_result, context_artifact_path)
            context_payload = scan_result.to_dict()
            context_payload["_source_path"] = _relative_to_project(
                context_artifact_path,
                root,
            )
            context_scan_relpath = _relative_to_project(context_artifact_path, root)

        if context_payload is not None:
            suggested_context = self._build_suggested_context(context_payload)

        if diagnose_mode and not diagnose_conflict and context_payload is not None:
            selected_context = self._select_context(
                context_payload=context_payload,
                use_top_context=use_top_context,
                source_paths=list(source_paths or []),
                target=target,
                tests=list(tests or []),
            )
            if selected_context["sources"]:
                diagnose_build = self._diagnose_builder.build_from_context(
                    user_request=user_request,
                    context_scan=context_payload,
                    selected_sources=list(selected_context["sources"]),
                    selected_tests=list(selected_context["tests"]),
                    request_id=request_id,
                    project_config=configs["project"],
                )
                task_spec = diagnose_build.task_spec
                task_spec.to_yaml(task_path)
                routing = {
                    "intent_type": run_intent.intent_type,
                    "confidence": run_intent.confidence,
                    "selected_skills": run_intent.selected_skills(),
                    "execution_readiness": "executable",
                    "required_context": [],
                    "safety_warnings": _dedupe([
                        *run_intent.safety_warnings,
                        *diagnose_build.warnings,
                        *list(selected_context.get("warnings", [])),
                        *list(context_payload.get("warnings", [])),
                    ]),
                    "routes": [route.to_dict() for route in run_intent.routes],
                    "memory_context": memory_context,
                    "diagnose_only": True,
                }
                execution_plan = {
                    "summary": "Prepare a safe diagnose-only run with approved context.",
                    "steps": [
                        "Load project memory",
                        "Inspect selected source files",
                        "Run selected related tests",
                        "Collect evidence before patching",
                    ],
                }
                next_actions = self._build_diagnose_next_actions(
                    root=root,
                    task_path=task_path,
                    selected_sources=list(selected_context["sources"]),
                    selected_tests=list(selected_context["tests"]),
                    execute=execute,
                )
                next_actions = _dedupe([*memory_next_actions, *next_actions])
            else:
                run_intent = RunIntent(
                    intent_type=run_intent.intent_type,
                    confidence=run_intent.confidence,
                    routes=run_intent.routes,
                    required_context=_dedupe([
                        *run_intent.required_context,
                        "source_candidate",
                    ]),
                    safety_warnings=_dedupe([
                        *run_intent.safety_warnings,
                        *list(context_payload.get("warnings", [])),
                    ]),
                    execution_readiness="needs_context",
                    memory_context=memory_context,
                )
                build_result = self._builder.build(
                    user_request=user_request,
                    run_intent=run_intent,
                    project_config=configs["project"],
                    options=explicit_options,
                    request_id=request_id,
                )
                task_spec = build_result.task_spec
                task_spec.to_yaml(task_path)
                routing = dict(build_result.routing)
                routing["diagnose_only"] = True
                execution_plan = self._build_execution_plan(run_intent)
                next_actions = self._build_next_actions(
                    root=root,
                    task_path=task_path,
                    user_request=user_request,
                    run_intent=run_intent,
                    target=target,
                    context_scan_path=context_scan_relpath,
                )
                next_actions = _dedupe([*memory_next_actions, *next_actions])
        else:
            build_result = self._builder.build(
                user_request=user_request,
                run_intent=run_intent,
                project_config=configs["project"],
                options=explicit_options,
                request_id=request_id,
            )
            task_spec = build_result.task_spec
            task_spec.to_yaml(task_path)
            routing = dict(build_result.routing)
            execution_plan = self._build_execution_plan(run_intent)
            next_actions = self._build_next_actions(
                root=root,
                task_path=task_path,
                user_request=user_request,
                run_intent=run_intent,
                target=target,
                context_scan_path=context_scan_relpath,
            )
            next_actions = _dedupe([*memory_next_actions, *next_actions])

        suggested_checks = _dedupe([
            "Run related pytest tests" if test_command else "",
            "Prefer small patch over broad refactor",
            "Do not auto-adopt",
            "Collect evidence before patching" if diagnose_mode else "",
            *list(routing.get("safety_warnings", [])),
        ])

        execution: dict = {
            "attempted": False,
            "status": "not_requested",
            "reason": "Execution was not requested.",
        }
        readiness = str(routing.get("execution_readiness", run_intent.execution_readiness))
        if dry_run:
            execution = {
                "attempted": False,
                "status": "dry_run",
                "reason": "Dry-run requested; draft only.",
            }
        elif execute and readiness == "executable":
            execution = self._execute_task_spec(
                root=root,
                task_spec=task_spec,
                max_iterations=effective_max_iterations,
            )
        elif execute:
            execution = {
                "attempted": True,
                "status": "blocked",
                    "reason": (
                        "Task is not executable yet: no executable actions "
                        f"({', '.join(routing.get('required_context', []) or ['review only request'])})"
                    ),
                }

        request_payload = {
            "schema_version": "1.2.0" if diagnose_mode or context_payload else "1.1.0",
            "request_id": request_id,
            "created_at": _now(),
            "user_request": user_request,
            "project_context": {
                "project_name": project_meta.get("name", root.name),
                "project_type": project_meta.get("type", "unknown"),
                "test_command": test_command,
            },
            "routing": routing,
            "selected_skills": list(routing.get("selected_skills", [])),
            "execution_plan": execution_plan,
            "suggested_checks": suggested_checks,
            "context_scan_ref": context_scan_relpath,
            "context_scan": {
                "enabled": context_payload is not None,
                "path": context_scan_relpath,
                "status": (
                    str(context_payload.get("status", "success"))
                    if context_payload is not None else "disabled"
                ),
                "top_sources": (
                    [str(suggested_context.get("top_source"))]
                    if suggested_context.get("top_source") else []
                ),
                "top_tests": (
                    [str(suggested_context.get("top_test"))]
                    if suggested_context.get("top_test") else []
                ),
            },
            "context_scan_path": context_scan_relpath,
            "suggested_context": suggested_context,
            "selected_context": selected_context,
            "diagnose_only": diagnose_mode,
            "memory_context": memory_context,
            "task_spec_draft_path": _relative_to_project(task_path, root),
            "status": execution["status"] if execute or dry_run else "draft",
            "execution": execution,
            "next_actions": next_actions,
        }
        _dump_yaml(request_path, request_payload)

        if readiness == "needs_context" and not diagnose_mode:
            clarification_session = RunClarifier().create_from_request(request_path, root)
            clarification = clarification_session.to_dict()
            request_payload["clarification"] = {
                "enabled": True,
                "path": clarification_session.artifact_path,
                "status": clarification_session.status,
                "generated_task_spec_path": clarification_session.generated_task_spec_path,
            }
            request_payload["next_actions"] = _dedupe([
                *memory_next_actions,
                *list(clarification_session.next_actions),
            ])
            _dump_yaml(request_path, request_payload)
            next_actions = list(request_payload["next_actions"])

        return ProjectRunResult(
            status=request_payload["status"],
            request_id=request_id,
            user_request=user_request,
            request_path=_relative_to_project(request_path, root),
            task_spec_path=_relative_to_project(task_path, root),
            selected_skills=list(routing.get("selected_skills", [])),
            routing=routing,
            project_context=request_payload["project_context"],
            execution_plan=execution_plan,
            suggested_checks=suggested_checks,
            next_actions=next_actions,
            execution=execution,
            context_scan_path=context_scan_relpath,
            suggested_context=suggested_context,
            selected_context=selected_context,
            clarification=clarification,
            memory_context=memory_context,
            diagnose_only=diagnose_mode,
            warnings=_dedupe([
                *list(routing.get("safety_warnings", [])),
                *memory_warnings,
            ]),
        )

    @staticmethod
    def _load_configs(project_root: Path) -> dict:
        """프로젝트 모드 구성 파일을 읽는다."""
        cambrian_dir = project_root / ".cambrian"
        project_payload = _load_yaml(cambrian_dir / "project.yaml")
        rules_payload = _load_yaml(cambrian_dir / "rules.yaml")
        profile_payload = _load_yaml(cambrian_dir / "profile.yaml")
        skills_payload = _load_yaml(cambrian_dir / "skills.yaml")
        if (
            project_payload is None
            or rules_payload is None
            or profile_payload is None
            or skills_payload is None
        ):
            raise FileNotFoundError(
                "Cambrian project mode is not initialized. Run `cambrian init` first."
            )
        return {
            "project": project_payload,
            "rules": rules_payload,
            "skills": skills_payload,
            "profile": profile_payload,
            "default_skills": list(
                skills_payload.get("selection", {}).get("default", [])
            ),
        }

    @staticmethod
    def _build_execution_plan(run_intent: RunIntent) -> dict:
        """routing 결과에 맞는 실행 계획을 만든다."""
        if run_intent.execution_readiness == "executable":
            return {
                "summary": "Prepare a safe executable run with explicit actions.",
                "steps": [
                    "Load project memory",
                    "Use the explicit action payload",
                    "Run related tests if provided",
                    "Record feedback after the result",
                ],
            }
        if run_intent.execution_readiness == "review_only":
            return {
                "summary": "Prepare a review-focused run without direct code execution.",
                "steps": [
                    "Load project memory",
                    "Review the request as a comparison or selection task",
                    "Avoid direct modification until inputs are clarified",
                ],
            }
        return {
            "summary": "Prepare a safe project-aware run with related checks.",
            "steps": [
                "Load project memory",
                "Identify likely related files manually or via follow-up",
                "Prepare a TaskSpec draft",
                "Run related tests before adoption",
                "Record lessons after result",
            ],
        }

    @staticmethod
    def _memory_warnings(memory_context: dict) -> list[str]:
        """관련 project memory에서 warning 문구를 추린다."""
        if not isinstance(memory_context, dict):
            return []
        warnings = [str(item) for item in memory_context.get("warnings", []) if item]
        for lesson in memory_context.get("relevant_lessons", []) or []:
            if not isinstance(lesson, dict):
                continue
            if lesson.get("kind") in {"avoid_pattern", "risk_warning"} and lesson.get("text"):
                warnings.append(f"Remembered risk: {lesson['text']}")
        return _dedupe(warnings)[:5]

    @staticmethod
    def _memory_next_actions(memory_context: dict) -> list[str]:
        """관련 project memory에서 다음 행동 힌트를 추린다."""
        if not isinstance(memory_context, dict):
            return []
        actions = [str(item) for item in memory_context.get("next_actions", []) if item]
        return _dedupe(actions)[:5]

    @staticmethod
    def _build_next_actions(
        *,
        root: Path,
        task_path: Path,
        user_request: str,
        run_intent: RunIntent,
        target: str | None,
        context_scan_path: str | None = None,
    ) -> list[str]:
        """사용자 친화적인 다음 행동 목록을 만든다."""
        next_actions: list[str] = []
        if run_intent.execution_readiness == "executable":
            next_actions.extend([
                f"Run cambrian brain run {_relative_to_project(task_path, root)}",
                "Review the generated TaskSpec before adoption",
            ])
        elif run_intent.execution_readiness == "review_only":
            next_actions.extend([
                "Provide candidate artifacts or patches to compare safely",
                "Use cambrian status to review project memory before execution",
            ])
        else:
            if "target_file" in run_intent.required_context:
                target_hint = (
                    f'cambrian run "{user_request}" --target path/to/file.py'
                    if not target else
                    f'cambrian run "{user_request}" --target {target}'
                )
                next_actions.append(target_hint)
            if "related_tests" in run_intent.required_context:
                next_actions.append("Add --test <path> to verify the change")
            if "patch_content" in run_intent.required_context:
                next_actions.append("Add --action with explicit content or patch text")
            if "expected_behavior" in run_intent.required_context:
                next_actions.append("Clarify the expected behavior before execution")
            if context_scan_path:
                next_actions.append(
                    f'Run cambrian run "{user_request}" --use-top-context --execute'
                )
            next_actions.append("Review the generated TaskSpec draft")
        next_actions.append(
            f"Edit {_relative_to_project(task_path, root)} if you need more control"
        )
        return _dedupe(next_actions)

    @staticmethod
    def _build_diagnose_next_actions(
        *,
        root: Path,
        task_path: Path,
        selected_sources: list[str],
        selected_tests: list[str],
        execute: bool,
    ) -> list[str]:
        """진단 실행용 다음 행동을 만든다."""
        next_actions: list[str] = []
        if execute:
            if selected_sources:
                next_actions.append(f"Prepare a patch against {selected_sources[0]}")
            if selected_tests:
                next_actions.append("Use the related test result as evidence")
        else:
            next_actions.append(
                f"Run cambrian brain run {_relative_to_project(task_path, root)}"
            )
            if selected_sources:
                next_actions.append(
                    f"Review {selected_sources[0]} before preparing a patch"
                )
        next_actions.append(
            f"Edit {_relative_to_project(task_path, root)} if you need more control"
        )
        return _dedupe(next_actions)

    @staticmethod
    def _execute_task_spec(
        *,
        root: Path,
        task_spec: TaskSpec,
        max_iterations: int,
    ) -> dict:
        """실행 가능한 TaskSpec을 내부 runner로 실행한다."""
        runner = RALFRunner(
            runs_dir=root / ".cambrian" / "brain" / "runs",
            workspace=root,
        )
        state = runner.run(task_spec, max_iterations=max_iterations)
        report_path = root / ".cambrian" / "brain" / "runs" / state.run_id / "report.json"
        payload = {
            "attempted": True,
            "status": state.status,
            "brain_run_id": state.run_id,
            "report_path": _relative_to_project(report_path, root),
        }
        report = _load_json(report_path)
        if report is not None and isinstance(report.get("diagnostics"), dict):
            payload["diagnostics"] = report["diagnostics"]
        return payload

    @staticmethod
    def _build_suggested_context(context_payload: dict) -> dict:
        """문맥 후보 요약을 만든다."""
        source_candidates = list(
            context_payload.get("suggested_sources")
            or context_payload.get("source_candidates", [])
        )
        test_candidates = list(
            context_payload.get("suggested_tests")
            or context_payload.get("test_candidates", [])
        )
        return {
            "top_source": context_payload.get("top_source"),
            "top_test": context_payload.get("top_test"),
            "top_source_reason": (
                str(source_candidates[0].get("why", ""))
                if source_candidates else ""
            ),
            "top_test_reason": (
                str(test_candidates[0].get("why", ""))
                if test_candidates else ""
            ),
        }

    @staticmethod
    def _select_context(
        *,
        context_payload: dict,
        use_top_context: bool,
        source_paths: list[str],
        target: str | None,
        tests: list[str],
    ) -> dict:
        """사용자 승인 방식에 따라 source/test 후보를 확정한다."""
        available_sources = {
            str(item.get("path"))
            for item in (
                context_payload.get("suggested_sources")
                or context_payload.get("source_candidates", [])
            )
            if isinstance(item, dict) and item.get("path")
        }
        available_tests = {
            str(item.get("path"))
            for item in (
                context_payload.get("suggested_tests")
                or context_payload.get("test_candidates", [])
            )
            if isinstance(item, dict) and item.get("path")
        }
        selected_sources = _dedupe([
            *(source_paths or []),
            *([target] if target else []),
        ])
        selected_tests = _dedupe(list(tests or []))

        if use_top_context and not selected_sources:
            top_source = context_payload.get("top_source")
            if top_source:
                selected_sources.append(str(top_source))
        if use_top_context and not selected_tests:
            top_test = context_payload.get("top_test")
            if top_test:
                selected_tests.append(str(top_test))

        warnings: list[str] = []
        for source in selected_sources:
            if source not in available_sources:
                warnings.append(f"context 후보에 없는 source를 사용합니다: {source}")
        for test_path in selected_tests:
            if test_path not in available_tests:
                warnings.append(f"context 후보에 없는 test를 사용합니다: {test_path}")

        return {
            "sources": selected_sources,
            "tests": selected_tests,
            "warnings": warnings,
        }


class ProjectStatusReader:
    """프로젝트 상태 요약기."""

    def read(self, project_root: str | Path) -> ProjectStatus:
        """현재 프로젝트 상태를 읽기 쉬운 구조로 요약한다."""
        root = Path(project_root).resolve()
        cambrian_dir = root / ".cambrian"
        warnings: list[str] = []

        project_payload = _load_yaml(cambrian_dir / "project.yaml", warnings)
        profile_payload = _load_yaml(cambrian_dir / "profile.yaml", warnings)
        skills_payload = _load_yaml(cambrian_dir / "skills.yaml", warnings)
        if project_payload is None or profile_payload is None or skills_payload is None:
            return ProjectStatus(
                initialized=False,
                project_root=str(root),
                next_actions=[
                    "Run `cambrian init --wizard` to fit your project harness.",
                    "Run `cambrian init` to create project memory.",
                ],
                warnings=warnings,
            )

        activity_summary = ProjectActivityReader().read(root, warnings)
        timeline_view = ProjectTimelineReader().read_project_status(root, limit=5)
        warnings.extend(item for item in timeline_view.warnings if item not in warnings)
        open_clarification = self._collect_open_clarification(root, warnings)
        onboarding = self._collect_onboarding(
            root,
            project_payload,
            profile_payload,
            skills_payload,
            warnings,
        )
        next_actions = _dedupe([
            *timeline_view.global_next_actions,
            *self._collect_next_actions(root, warnings),
        ])
        if not onboarding.get("wizard_completed", False):
            next_actions = _dedupe([
                "Run `cambrian init --wizard`",
                *next_actions,
            ])
        if open_clarification.get("next"):
            next_actions = _dedupe([str(open_clarification["next"]), *next_actions])

        timeline_session = (
            timeline_view.active_sessions[0]
            if timeline_view.active_sessions
            else timeline_view.recent_sessions[0]
            if timeline_view.recent_sessions
            else None
        )
        recent_journey = (
            self._timeline_events_to_journey(timeline_session)
            if timeline_session is not None
            else [item.to_dict() for item in activity_summary.journey_items()]
        )
        usage_summary: dict = {}
        try:
            from engine.project_summary import ProjectUsageSummaryBuilder

            usage_summary = ProjectUsageSummaryBuilder().build(root, limit=3).to_dict()
        except Exception as exc:
            message = f"usage summary build failed: {exc}"
            logger.warning(message)
            warnings.append(message)
        alpha_readiness: dict = {}
        try:
            from engine.project_alpha_audit import default_alpha_audit_path, load_alpha_readiness

            alpha_path = default_alpha_audit_path(root)
            if alpha_path.exists():
                alpha_readiness = load_alpha_readiness(alpha_path).to_dict()
        except Exception as exc:
            message = f"alpha readiness load failed: {exc}"
            logger.warning(message)
            warnings.append(message)
        notes: dict = self._collect_notes(root, timeline_view.active_sessions, warnings)
        last_error: dict = {}
        try:
            last_error_path = default_last_error_path(root)
            if last_error_path.exists():
                last_error = load_last_error(last_error_path).hint.to_dict()
        except Exception as exc:
            message = f"last error load failed: {exc}"
            logger.warning(message)
            warnings.append(message)

        return ProjectStatus(
            initialized=True,
            project_root=str(root),
            project={
                "name": project_payload.get("project", {}).get("name", root.name),
                "type": project_payload.get("project", {}).get("type", "unknown"),
                "tests": project_payload.get("test", {}).get("command", ""),
            },
            onboarding=onboarding,
            profile={
                "mode": profile_payload.get("mode", "balanced"),
                "max_variants": profile_payload.get("defaults", {}).get("max_variants"),
                "adoption": profile_payload.get("defaults", {}).get("adoption"),
            },
            recommended_skills=[
                str(item.get("id", ""))
                for item in skills_payload.get("recommended_skills", [])
                if isinstance(item, dict) and item.get("id")
            ],
            memory=self._collect_memory(root, warnings),
            recent_requests=self._collect_recent_requests(root, warnings),
            recent_context_scan=self._collect_recent_context_scan(root, warnings),
            recent_do_session=self._timeline_session_summary(timeline_session),
            open_clarification=open_clarification,
            recent_diagnostic=self._collect_recent_diagnostic(root, warnings),
            recent_patch_intent=self._collect_recent_patch_intent(root, warnings),
            recent_patch_proposal=self._collect_recent_patch_proposal(root, warnings),
            latest_patch_adoption=timeline_view.latest_adoption or self._collect_latest_patch_adoption(root, warnings),
            recent_journey=recent_journey,
            recent_lessons=timeline_view.recent_lessons or self._collect_lessons(root, warnings),
            active_sessions=[item.to_dict() for item in timeline_view.active_sessions],
            recent_sessions=[item.to_dict() for item in timeline_view.recent_sessions],
            usage_summary=usage_summary,
            alpha_readiness=alpha_readiness,
            notes=notes,
            last_error=last_error,
            next_actions=next_actions,
            warnings=warnings,
        )

    @staticmethod
    def _timeline_events_to_journey(timeline) -> list[dict]:
        """세션 타임라인을 최근 여정 요약으로 바꾼다."""
        if timeline is None:
            return []
        items: list[dict] = []
        for event in timeline.events:
            items.append(
                {
                    "kind": event.kind,
                    "summary": event.summary,
                    "status": event.status,
                    "path": event.path,
                }
            )
        return items

    @staticmethod
    def _timeline_session_summary(timeline) -> dict:
        """세션 타임라인을 기존 recent_do_session 요약으로 바꾼다."""
        if timeline is None:
            return {}
        return {
            "request": timeline.user_request or "",
            "status": timeline.current_stage or "unknown",
            "stage": timeline.current_stage or "unknown",
            "stage_label": timeline.status,
            "source": ", ".join(timeline.selected_sources) or "-",
            "tests": ", ".join(timeline.selected_tests) or "-",
            "next": timeline.next_actions[0] if timeline.next_actions else "",
            "active": (timeline.current_stage or "") not in {"adopted", "completed", "closed", "error"},
        }

    def _collect_onboarding(
        self,
        root: Path,
        project_payload: dict,
        profile_payload: dict,
        skills_payload: dict,
        warnings: list[str],
    ) -> dict:
        """wizard 기반 onboarding summary를 수집한다."""
        init_report = _load_yaml(root / ".cambrian" / "init_report.yaml", warnings) or {}
        onboarding_payload = project_payload.get("onboarding", {})
        if not isinstance(onboarding_payload, dict):
            onboarding_payload = {}
        wizard_completed = bool(
            onboarding_payload.get("wizard_completed", False)
            or init_report.get("status") == "completed"
        )
        focus = list(project_payload.get("ai_work", {}).get("primary_use_cases", []))
        if not focus:
            focus = [
                str(item.get("id", ""))
                for item in skills_payload.get("recommended_skills", [])
                if isinstance(item, dict) and item.get("id")
            ][:3]
        return {
            "wizard_completed": wizard_completed,
            "completed_at": onboarding_payload.get("completed_at") or init_report.get("created_at"),
            "mode": profile_payload.get("mode", "balanced"),
            "test_command": project_payload.get("test", {}).get("command", ""),
            "focus": _dedupe([str(item) for item in focus if item]),
        }

    def _collect_memory(self, root: Path, warnings: list[str]) -> dict:
        """최근 실행과 위험 신호를 요약한다."""
        brain_runs_dir = root / ".cambrian" / "brain" / "runs"
        feedback_dir = root / ".cambrian" / "feedback"
        next_generation_dir = root / ".cambrian" / "next_generation"
        evolution_dir = root / ".cambrian" / "evolution"
        adoptions_dir = root / ".cambrian" / "adoptions"

        latest_run_id = self._latest_run_id(brain_runs_dir, warnings)
        latest_feedback_path = _latest_file(feedback_dir, "feedback_*.json")
        latest_seed_path = _latest_file(next_generation_dir, "next_generation_*.yaml")
        latest_adoption = _load_json(adoptions_dir / "_latest.json", warnings) or {}
        latest_pressure = (
            _load_yaml(evolution_dir / "_selection_pressure.yaml", warnings) or {}
        )

        current_risk = "none yet"
        risk_flags = latest_pressure.get("risk_flags", [])
        if risk_flags:
            current_risk = str(risk_flags[0]).replace("_", " ")

        last_lesson = "none yet"
        if latest_feedback_path is not None:
            feedback_payload = _load_json(latest_feedback_path, warnings) or {}
            lesson_pool = (
                list(feedback_payload.get("keep_patterns", []))
                or list(feedback_payload.get("avoid_patterns", []))
            )
            if lesson_pool:
                last_lesson = str(lesson_pool[0])

        lesson_count = 0
        routing_enabled = False
        top_hints: list[str] = []
        pinned_count = 0
        suppressed_count = 0
        hygiene_summary = {
            "checked": False,
            "watch": 0,
            "stale": 0,
            "conflicting": 0,
            "orphaned": 0,
            "needs_review": 0,
        }
        lessons_path = default_memory_path(root)
        memory_payload = load_project_memory(root)
        if memory_payload is not None:
            lesson_count = len(memory_payload.lessons)
            routing_enabled = lesson_count > 0
            counts = memory_override_counts(memory_payload)
            pinned_count = counts["pinned"]
            suppressed_count = counts["suppressed"]
            top_hints = [lesson.text for lesson in memory_payload.lessons if lesson.pinned and not lesson.suppressed][:2]
            if not top_hints:
                top_hints = [lesson.text for lesson in memory_payload.lessons if not lesson.suppressed][:2]
        elif lessons_path.exists():
            try:
                lessons_payload = ProjectMemoryStore().load(lessons_path)
                lesson_count = len(lessons_payload.lessons)
                routing_enabled = lesson_count > 0
                top_hints = [lesson.text for lesson in lessons_payload.lessons[:2]]
            except (OSError, ValueError, yaml.YAMLError) as exc:
                message = f"프로젝트 기억을 읽지 못했습니다: {lessons_path} ({exc})"
                logger.warning(message)
                warnings.append(message)

        hygiene_payload = load_memory_hygiene(root)
        if hygiene_payload is not None:
            hygiene_summary = {
                "checked": True,
                "watch": int(hygiene_payload.summary.get("watch", 0) or 0),
                "stale": int(hygiene_payload.summary.get("stale", 0) or 0),
                "conflicting": int(hygiene_payload.summary.get("conflicting", 0) or 0),
                "orphaned": int(hygiene_payload.summary.get("orphaned", 0) or 0),
                "needs_review": (
                    int(hygiene_payload.summary.get("watch", 0) or 0)
                    + int(hygiene_payload.summary.get("stale", 0) or 0)
                    + int(hygiene_payload.summary.get("conflicting", 0) or 0)
                    + int(hygiene_payload.summary.get("orphaned", 0) or 0)
                ),
            }

        return {
            "last_run": latest_run_id or "none",
            "last_lesson": last_lesson,
            "last_adoption": latest_adoption.get("latest_adoption_id", "none"),
            "last_seed": (
                _relative_to_project(latest_seed_path, root)
                if latest_seed_path is not None else "none"
            ),
            "current_risk": current_risk,
            "lesson_count": lesson_count,
            "routing_enabled": routing_enabled,
            "top_hints": top_hints,
            "pinned_count": pinned_count,
            "suppressed_count": suppressed_count,
            "hygiene": hygiene_summary,
            "lessons_path": _relative_to_project(lessons_path, root),
        }

    def _collect_lessons(self, root: Path, warnings: list[str]) -> list[str]:
        """최근 학습 내용을 수집한다."""
        lessons: list[str] = []
        feedback_path = _latest_file(root / ".cambrian" / "feedback", "feedback_*.json")
        seed_path = _latest_file(root / ".cambrian" / "next_generation", "next_generation_*.yaml")
        if feedback_path is not None:
            feedback_payload = _load_json(feedback_path, warnings) or {}
            lessons.extend(str(item) for item in feedback_payload.get("keep_patterns", []))
            lessons.extend(str(item) for item in feedback_payload.get("avoid_patterns", []))
        if seed_path is not None:
            seed_payload = _load_yaml(seed_path, warnings) or {}
            lesson_map = seed_payload.get("lessons", {})
            if isinstance(lesson_map, dict):
                lessons.extend(str(item) for item in lesson_map.get("keep", []))
                lessons.extend(str(item) for item in lesson_map.get("avoid", []))
        return _dedupe(lessons)[:5]

    def _collect_next_actions(self, root: Path, warnings: list[str]) -> list[str]:
        """최근 추천 행동을 수집한다."""
        actions: list[str] = []
        feedback_path = _latest_file(root / ".cambrian" / "feedback", "feedback_*.json")
        if feedback_path is not None:
            feedback_payload = _load_json(feedback_path, warnings) or {}
            actions.extend(
                str(item) for item in feedback_payload.get("suggested_next_actions", [])
            )
        latest_report = self._latest_report(root / ".cambrian" / "brain" / "runs")
        if latest_report is not None:
            report_payload = _load_json(latest_report, warnings) or {}
            actions.extend(str(item) for item in report_payload.get("next_actions", []))
        if not actions:
            actions.append('Run `cambrian run "<request>"`')
        return _dedupe(actions)[:5]

    def _collect_recent_requests(self, root: Path, warnings: list[str]) -> list[dict]:
        """최근 request artifact를 요약한다."""
        requests_dir = root / ".cambrian" / "requests"
        if not requests_dir.exists():
            return []
        request_files = sorted(
            requests_dir.glob("request_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        summaries: list[dict] = []
        for request_path in request_files[:3]:
            payload = _load_yaml(request_path, warnings)
            if not payload:
                continue
            routing = payload.get("routing", {})
            selected_context = payload.get("selected_context", {})
            summaries.append(
                {
                    "request_id": payload.get("request_id", request_path.stem),
                    "intent_type": routing.get("intent_type", "unknown"),
                    "execution_readiness": routing.get(
                        "execution_readiness",
                        payload.get("status", "unknown"),
                    ),
                    "required_context": list(routing.get("required_context", [])),
                    "diagnose_only": bool(payload.get("diagnose_only", False)),
                    "selected_sources": list(selected_context.get("sources", [])),
                    "selected_tests": list(selected_context.get("tests", [])),
                    "context_scan_ref": payload.get("context_scan_ref"),
                }
            )
        return summaries

    def _collect_recent_context_scan(self, root: Path, warnings: list[str]) -> dict:
        """최근 context scan 요약을 반환한다."""
        context_path = _latest_file(root / ".cambrian" / "context", "context_*.yaml")
        if context_path is None:
            return {}
        payload = _load_yaml(context_path, warnings)
        if not payload:
            return {}
        return {
            "request": payload.get("user_request", ""),
            "top_file": payload.get("top_source", "") or "-",
            "top_test": payload.get("top_test", "") or "-",
            "status": payload.get("status", "unknown"),
        }

    def _collect_recent_do_session(self, root: Path, warnings: list[str]) -> dict:
        """최신 do 세션 요약을 수집한다."""
        session_path = _latest_file(root / ".cambrian" / "sessions", "do_session_*.yaml")
        if session_path is None:
            return {}
        payload = _load_yaml(session_path, warnings)
        if not payload:
            return {}
        summary = payload.get("summary", {})
        artifacts = payload.get("artifacts", {})
        next_actions = list(payload.get("next_actions", []))
        if not isinstance(summary, dict):
            summary = {}
        if not isinstance(artifacts, dict):
            artifacts = {}
        return {
            "request": payload.get("user_request", ""),
            "status": payload.get("status", "unknown"),
            "source": ", ".join(summary.get("selected_sources", []) or summary.get("found_sources", [])) or "-",
            "tests": ", ".join(summary.get("selected_tests", []) or summary.get("found_tests", [])) or "-",
            "report": artifacts.get("report_path", ""),
            "next": next_actions[0] if next_actions else "",
        }

    def _collect_notes(self, root: Path, active_sessions: list, warnings: list[str]) -> dict:
        """사용자 notes 요약을 수집한다."""
        try:
            notes = ProjectNotesStore().list(default_notes_dir(root))
        except Exception as exc:
            message = f"notes load failed: {exc}"
            logger.warning(message)
            warnings.append(message)
            return {}

        active_session_ids = {
            str(getattr(item, "session_id", ""))
            for item in active_sessions
            if getattr(item, "session_id", "")
        }
        latest_note = notes[0] if notes else None
        active_note = next(
            (
                note
                for note in notes
                if note.status == "open" and note.session_id and note.session_id in active_session_ids
            ),
            None,
        )
        snippet = ""
        if latest_note is not None and latest_note.text:
            snippet = latest_note.text if len(latest_note.text) <= 72 else f"{latest_note.text[:69]}..."
        active_snippet = ""
        if active_note is not None and active_note.text:
            active_snippet = active_note.text if len(active_note.text) <= 72 else f"{active_note.text[:69]}..."
        return {
            "open": sum(1 for note in notes if note.status == "open"),
            "resolved": sum(1 for note in notes if note.status == "resolved"),
            "latest": (
                {
                    "note_id": latest_note.note_id,
                    "kind": latest_note.kind,
                    "severity": latest_note.severity,
                    "text": latest_note.text,
                    "snippet": snippet,
                    "session_id": latest_note.session_id,
                }
                if latest_note is not None else {}
            ),
            "active": (
                {
                    "note_id": active_note.note_id,
                    "kind": active_note.kind,
                    "severity": active_note.severity,
                    "text": active_note.text,
                    "snippet": active_snippet,
                    "session_id": active_note.session_id,
                }
                if active_note is not None else {}
            ),
        }

    def _collect_active_do_session(self, root: Path, warnings: list[str]) -> dict:
        """active do session이 있으면 우선 반환하고, 없으면 최근 완료 session을 반환한다."""
        sessions_dir = root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return {}
        session_files = sorted(
            sessions_dir.glob("do_session_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        latest_completed: dict | None = None
        for session_path in session_files:
            payload = _load_yaml(session_path, warnings)
            if not payload:
                continue
            summary = payload.get("summary", {})
            artifacts = payload.get("artifacts", {})
            next_actions = list(payload.get("next_actions", []))
            if not isinstance(summary, dict):
                summary = {}
            if not isinstance(artifacts, dict):
                artifacts = {}
            item = {
                "request": payload.get("user_request", ""),
                "status": payload.get("status", "unknown"),
                "stage": payload.get("current_stage", payload.get("status", "unknown")),
                "source": ", ".join(summary.get("selected_sources", []) or summary.get("found_sources", [])) or "-",
                "tests": ", ".join(summary.get("selected_tests", []) or summary.get("found_tests", [])) or "-",
                "report": artifacts.get("report_path", ""),
                "next": next_actions[0] if next_actions else "",
            }
            if item["status"] not in {"adopted", "completed", "closed", "error"}:
                item["active"] = True
                return item
            if latest_completed is None:
                item["active"] = False
                latest_completed = item
        return latest_completed or {}

    def _collect_open_clarification(self, root: Path, warnings: list[str]) -> dict:
        """열려 있는 clarification 세션을 요약한다."""
        clarifications_dir = root / ".cambrian" / "clarifications"
        if not clarifications_dir.exists():
            return {}
        clarification_files = sorted(
            clarifications_dir.glob("clarification_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        for clarification_path in clarification_files:
            payload = _load_yaml(clarification_path, warnings)
            if not payload:
                continue
            status = str(payload.get("status", "open"))
            if status not in {"open", "answered", "ready"}:
                continue
            questions = list(payload.get("questions", []))
            source_question = next(
                (
                    item for item in questions
                    if isinstance(item, dict) and item.get("kind") == "source"
                ),
                None,
            )
            top_suggestion = "-"
            if source_question and source_question.get("options"):
                top_suggestion = str(source_question["options"][0].get("value", "")) or "-"
            return {
                "request": payload.get("user_request", ""),
                "missing": ", ".join(payload.get("missing_context", [])) or "none",
                "top_suggestion": top_suggestion,
                "status": status,
                "next": (
                    str(payload.get("next_actions", [])[0])
                    if payload.get("next_actions") else ""
                ),
            }
        return {}

    def _collect_recent_diagnostic(self, root: Path, warnings: list[str]) -> dict:
        """최근 diagnose-only 실행 요약을 수집한다."""
        requests_dir = root / ".cambrian" / "requests"
        if not requests_dir.exists():
            return {}
        request_files = sorted(
            requests_dir.glob("request_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        for request_path in request_files:
            payload = _load_yaml(request_path, warnings)
            if not payload or not payload.get("diagnose_only", False):
                continue
            execution = payload.get("execution", {})
            selected_context = payload.get("selected_context", {})
            summary = {
                "request": payload.get("user_request", ""),
                "source": ", ".join(selected_context.get("sources", [])),
                "tests": ", ".join(selected_context.get("tests", [])),
                "result": execution.get("status", payload.get("status", "draft")),
                "next": ", ".join(payload.get("next_actions", [])[:2]),
            }
            report_path = execution.get("report_path")
            if report_path:
                report_payload = _load_json(root / str(report_path), warnings) or {}
                diagnostics = report_payload.get("diagnostics", {})
                if isinstance(diagnostics, dict) and diagnostics.get("enabled"):
                    test_results = diagnostics.get("test_results", {})
                    failed = int(test_results.get("failed", 0) or 0)
                    passed = int(test_results.get("passed", 0) or 0)
                    if failed > 0:
                        summary["result"] = "related tests failed"
                    elif passed > 0:
                        summary["result"] = "related tests passed"
                    summary["next"] = ", ".join(diagnostics.get("next_actions", [])[:2])
            return summary
        return {}

    def _collect_recent_patch_proposal(self, root: Path, warnings: list[str]) -> dict:
        """최근 patch proposal 요약을 수집한다."""
        proposal_path = _latest_file(root / ".cambrian" / "patches", "patch_proposal_*.yaml")
        if proposal_path is None:
            return {}
        payload = _load_yaml(proposal_path, warnings)
        if not payload:
            return {}
        validation = payload.get("validation", {}) or {}
        tests = validation.get("tests", {}) if isinstance(validation, dict) else {}
        next_actions = list(payload.get("next_actions", []))
        if validation.get("attempted"):
            if int(tests.get("failed", 0) or 0) > 0:
                test_summary = "failed"
            elif int(tests.get("passed", 0) or 0) > 0:
                test_summary = "passed"
            else:
                test_summary = str(validation.get("status", "unknown"))
        else:
            test_summary = "not run"
        return {
            "target": payload.get("target_path", ""),
            "status": payload.get("proposal_status", "unknown"),
            "tests": test_summary,
            "next": next_actions[0] if next_actions else "",
        }

    def _collect_recent_patch_intent(self, root: Path, warnings: list[str]) -> dict:
        """최근 patch intent 요약을 수집한다."""
        intent_path = _latest_file(root / ".cambrian" / "patch_intents", "patch_intent_*.yaml")
        if intent_path is None:
            return {}
        payload = _load_yaml(intent_path, warnings)
        if not payload:
            return {}
        next_actions = list(payload.get("next_actions", []))
        return {
            "target": payload.get("target_path", ""),
            "status": str(payload.get("status", "draft")).replace("_", " "),
            "next": next_actions[0] if next_actions else "",
        }

    def _collect_latest_patch_adoption(self, root: Path, warnings: list[str]) -> dict:
        """최신 patch adoption 요약을 수집한다."""
        latest_path = root / ".cambrian" / "adoptions" / "_latest.json"
        latest_payload = _load_json(latest_path, warnings)
        if not latest_payload:
            return {}
        if latest_payload.get("adoption_type") != "patch_proposal":
            return {}

        record_ref = latest_payload.get("latest_adoption_path")
        if not isinstance(record_ref, str) or not record_ref:
            return {
                "type": "patch proposal",
                "target": latest_payload.get("target_path", ""),
                "tests": "unknown",
                "reason": latest_payload.get("human_reason", ""),
            }

        record_path = root / record_ref
        record_payload = _load_json(record_path, warnings)
        if not record_payload:
            return {
                "type": "patch proposal",
                "target": latest_payload.get("target_path", ""),
                "tests": "unknown",
                "reason": latest_payload.get("human_reason", ""),
            }

        tests = record_payload.get("post_apply_tests", {})
        failed = int(tests.get("failed", 0) or 0)
        passed = int(tests.get("passed", 0) or 0)
        if failed > 0:
            test_summary = "failed"
        elif passed > 0:
            test_summary = "passed"
        else:
            test_summary = str(record_payload.get("adoption_status", "unknown"))

        return {
            "type": "patch proposal",
            "target": record_payload.get("target_path", ""),
            "tests": test_summary,
            "reason": record_payload.get("human_reason", ""),
        }

    @staticmethod
    def _latest_report(brain_runs_dir: Path) -> Path | None:
        """최신 report.json 파일을 반환한다."""
        if not brain_runs_dir.exists():
            return None
        candidates: list[Path] = []
        for run_dir in brain_runs_dir.iterdir():
            report_path = run_dir / "report.json"
            if run_dir.is_dir() and report_path.exists():
                candidates.append(report_path)
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item.stat().st_mtime, item.parent.name))
        return candidates[-1]

    @staticmethod
    def _latest_run_id(brain_runs_dir: Path, warnings: list[str]) -> str | None:
        """최신 brain run ID를 찾는다."""
        if not brain_runs_dir.exists():
            return None
        latest_key: tuple[str, str] | None = None
        latest_run_id: str | None = None
        for run_dir in brain_runs_dir.iterdir():
            state_path = run_dir / "run_state.json"
            if not run_dir.is_dir() or not state_path.exists():
                continue
            state_payload = _load_json(state_path, warnings)
            if not state_payload:
                continue
            key = (
                str(state_payload.get("updated_at", "")),
                str(state_payload.get("run_id", run_dir.name)),
            )
            if latest_key is None or key > latest_key:
                latest_key = key
                latest_run_id = str(state_payload.get("run_id", run_dir.name))
        return latest_run_id


def render_init_summary(result: ProjectInitResult) -> str:
    """init 결과를 사람이 읽기 좋게 렌더링한다."""
    if result.status != "initialized":
        lines = ["Cambrian initialization was blocked.", "", "Reasons:"]
        lines.extend(f"  - {warning}" for warning in result.warnings)
        return "\n".join(lines)

    lines = [
        "Cambrian initialized.",
        "",
        "Project:",
        f"  name : {result.project_name}",
        f"  type : {result.project_type}",
        f"  tests: {result.test_command or 'none yet'}",
        "",
        "Project memory created:",
    ]
    for path in result.config_paths.values():
        lines.append(f"  {path}")
    lines.extend(["", "Recommended skills:"])
    for skill_id in result.recommended_skills:
        lines.append(f"  - {skill_id}")
    lines.extend(["", "Next:", '  cambrian run "fix a small bug"'])
    return "\n".join(lines)


def render_run_summary(result: ProjectRunResult) -> str:
    """run 준비 결과를 사람이 읽기 좋게 렌더링한다."""
    readiness_labels = {
        "executable": "ready to execute",
        "needs_context": "needs more context",
        "review_only": "review first",
        "blocked": "blocked",
    }
    execution_status = str(result.execution.get("status", ""))
    diagnostics = result.execution.get("diagnostics", {})
    lines: list[str]

    if result.diagnose_only and result.execution.get("attempted") and diagnostics:
        test_results = diagnostics.get("test_results", {})
        lines = [
            "Cambrian diagnosed the request.",
            "",
            "Inspected:",
        ]
        for item in diagnostics.get("inspected_files", []):
            lines.append(f"  - {item.get('path')}")
        lines.extend(["", "Tests:"])
        related_tests = diagnostics.get("related_tests", [])
        if related_tests:
            for test_path in related_tests:
                test_label = "failed" if int(test_results.get("failed", 0) or 0) > 0 else "passed"
                lines.append(f"  - {test_path}: {test_label}")
        else:
            lines.append("  - none")
        lines.extend(["", "Evidence:", "  Failing related tests found." if int(test_results.get("failed", 0) or 0) > 0 else "  Evidence collected from the selected files."])
        lines.extend(["", "Next:"])
        for action in result.next_actions:
            lines.append(f"  - {action}")
        return "\n".join(lines)

    if result.diagnose_only and result.routing.get("execution_readiness") == "executable":
        lines = [
            "Cambrian prepared a diagnose-only run.",
            "",
            "Selected context:",
        ]
        sources = list(result.selected_context.get("sources", []))
        tests = list(result.selected_context.get("tests", []))
        lines.append(f"  source: {', '.join(sources) if sources else 'none'}")
        lines.append(f"  test  : {', '.join(tests) if tests else 'none'}")
        lines.extend([
            "",
            "This run will:",
            "  - inspect selected source files",
            "  - run related tests",
            "  - not modify source files",
            "",
            "Created:",
            f"  task: {result.task_spec_path}",
            "",
            "Next:",
        ])
        for action in result.next_actions:
            lines.append(f"  - {action}")
        return "\n".join(lines)

    if (
        result.routing.get("execution_readiness") == "needs_context"
        and result.suggested_context.get("top_source")
    ):
        source_options: list[dict] = []
        test_options: list[dict] = []
        for item in result.clarification.get("questions", []):
            if not isinstance(item, dict):
                continue
            if item.get("kind") == "source":
                source_options = list(item.get("options", []))
            elif item.get("kind") == "test":
                test_options = list(item.get("options", []))
        lines = [
            "Cambrian found likely context.",
            "",
            "Cambrian prepared a clarification and needs one choice before it can safely continue.",
            "",
            "Request:",
            f"  {result.user_request}",
            "",
            "Suggested source files:",
        ]
        if source_options:
            for index, option in enumerate(source_options[:2], start=1):
                lines.append(
                    f"  {index}. {option.get('value')}    {option.get('reason') or 'matched request terms'}"
                )
        else:
            lines.append(f"  1. {result.suggested_context.get('top_source')}")
        lines.extend(["", "Suggested tests:"])
        if test_options:
            for index, option in enumerate(test_options[:2], start=1):
                lines.append(f"  {index}. {option.get('value')}")
        else:
            lines.append(f"  1. {result.suggested_context.get('top_test') or 'none found'}")
        lines.extend([
            "",
            "Created:",
            f"  request : {result.request_path}",
            f"  task    : {result.task_spec_path}",
        ])
        if result.context_scan_path:
            lines.append(f"  context : {result.context_scan_path}")
        if result.clarification.get("path"):
            lines.append(f"  clarification : {result.clarification.get('path')}")
        lines.extend([
            "",
            "Next:",
        ])
        for action in result.next_actions:
            lines.append(f"  {action}" if str(action).startswith("cambrian ") else f"  - {action}")
        return "\n".join(lines)

    lines = [
        (
            "Cambrian prepared an executable run."
            if result.routing.get("execution_readiness") == "executable"
            else "Cambrian prepared your run."
        ),
        "",
        "Request:",
        f"  {result.user_request}",
        "",
        "Project memory:",
        f"  project : {result.project_context.get('project_name', '(unknown)')}",
        f"  type    : {result.project_context.get('project_type', '(unknown)')}",
        f"  tests   : {result.project_context.get('test_command', 'none yet') or 'none yet'}",
        "",
        "Understood as:",
        f"  {str(result.routing.get('intent_type', 'unknown')).replace('_', ' ')}",
        "",
        "Selected skills:",
    ]
    for skill_id in result.selected_skills:
        lines.append(f"  - {skill_id}")
    remembered = list(result.memory_context.get("relevant_lessons", [])) if isinstance(result.memory_context, dict) else []
    if remembered:
        lines.extend(["", "Remembered:"])
        for item in remembered[:3]:
            if isinstance(item, dict) and item.get("text"):
                lines.append(f"  - {item['text']}")
    elif isinstance(result.memory_context, dict) and result.memory_context.get("enabled") is False:
        lines.extend(["", "Project memory:", "  no lessons yet"])
    lines.extend([
        "",
        "Readiness:",
        f"  {readiness_labels.get(str(result.routing.get('execution_readiness', '')), str(result.routing.get('execution_readiness', 'unknown')))}",
    ])
    missing = list(result.routing.get("required_context", []))
    if missing:
        lines.extend(["", "Missing:"])
        for item in missing:
            lines.append(f"  - {str(item).replace('_', ' ')}")
    lines.extend(["", "Plan:"])
    for index, step in enumerate(result.execution_plan.get("steps", []), start=1):
        lines.append(f"  {index}. {step}")
    lines.extend([
        "",
        "Created:",
        f"  request : {result.request_path}",
        f"  task    : {result.task_spec_path}",
    ])
    if result.clarification.get("path"):
        lines.append(f"  clarification : {result.clarification.get('path')}")
    if result.execution.get("attempted"):
        lines.extend([
            "",
            "Execution:",
            f"  status : {execution_status or 'unknown'}",
            f"  reason : {result.execution.get('reason', '')}",
        ])
        if result.execution.get("brain_run_id"):
            lines.append(f"  run    : {result.execution.get('brain_run_id')}")
    lines.extend(["", "Next:"])
    for action in result.next_actions:
        lines.append(f"  - {action}")
    return "\n".join(lines)


def render_status_summary(status: ProjectStatus) -> str:
    """status 결과를 사람이 읽기 좋게 렌더링한다."""
    if not status.initialized:
        return "\n".join([
            "Cambrian Project Status",
            "==================================================",
            "Cambrian is not fitted to this project yet.",
            "",
            "Next:",
            "  cambrian init --wizard",
        ])

    def _journey_symbol(item: dict) -> str:
        status_value = str(item.get("status", ""))
        if status_value in {"completed", "ready", "validated", "adopted", "selected", "passed"}:
            return "✓"
        if status_value in {"blocked", "failed", "error"}:
            return "!"
        return "→"

    lines = [
        "Cambrian Project Status",
        "==================================================",
        "Project:",
        f"  name : {status.project.get('name', '(unknown)')}",
        f"  type : {status.project.get('type', '(unknown)')}",
        f"  tests: {status.project.get('tests', 'none yet') or 'none yet'}",
        "",
        "Project harness:",
        f"  wizard     : {'completed' if status.onboarding.get('wizard_completed', False) else 'not completed'}",
        f"  mode       : {status.onboarding.get('mode', status.profile.get('mode', 'balanced'))}",
        f"  test cmd   : {status.onboarding.get('test_command', status.project.get('tests', '')) or 'none yet'}",
        f"  focus      : {', '.join(status.onboarding.get('focus', [])) or 'none yet'}",
        "",
        "Mode:",
        f"  {status.profile.get('mode', 'balanced')}",
        f"  max variants: {status.profile.get('max_variants', '(unknown)')}",
        f"  adoption    : {status.profile.get('adoption', '(unknown)')}",
        "",
        "Recommended skills:",
    ]
    for skill_id in status.recommended_skills:
        lines.append(f"  - {skill_id}")
    usage_summary = status.usage_summary if isinstance(status.usage_summary, dict) else {}
    summary_counts = usage_summary.get("counts", {}) if isinstance(usage_summary.get("counts"), dict) else {}
    summary_safety = usage_summary.get("safety", {}) if isinstance(usage_summary.get("safety"), dict) else {}
    if usage_summary:
        lines.extend([
            "",
            "Summary:",
            "  "
            f"{summary_counts.get('sessions', 0)} sessions · "
            f"{summary_counts.get('adoptions', 0)} adopted changes · "
            f"{summary_counts.get('lessons', 0)} lessons remembered",
            "  "
            f"Safety: automatic adoption {'on' if summary_safety.get('automatic_adoption_enabled', False) else 'off'}",
            "  Run: cambrian summary",
        ])
    alpha_readiness = status.alpha_readiness if isinstance(status.alpha_readiness, dict) else {}
    alpha_summary = (
        alpha_readiness.get("summary", {})
        if isinstance(alpha_readiness.get("summary"), dict)
        else {}
    )
    lines.extend(["", "Alpha readiness:"])
    if alpha_readiness:
        lines.append(f"  last check : {alpha_readiness.get('verdict', alpha_readiness.get('status', 'unknown'))}")
        lines.append(f"  warnings   : {alpha_summary.get('warn', 0)}")
        lines.append("  next       : cambrian alpha check --save")
    else:
        lines.append("  not checked yet")
        lines.append("  next       : cambrian alpha check --save")
    last_error = status.last_error if isinstance(status.last_error, dict) else {}
    last_try = []
    if isinstance(last_error.get("try_next"), list):
        last_try = [item for item in last_error.get("try_next", []) if isinstance(item, dict)]
    if last_error.get("problem"):
        lines.extend([
            "",
            "Unresolved issue:",
            f"  {last_error.get('problem')}",
        ])
        if last_try:
            lines.extend([
                "",
                "Try:",
                f"  {last_try[0].get('command')}",
            ])
    notes = status.notes if isinstance(status.notes, dict) else {}
    latest_note = notes.get("latest", {}) if isinstance(notes.get("latest"), dict) else {}
    active_note = notes.get("active", {}) if isinstance(notes.get("active"), dict) else {}
    lines.extend([
        "",
        "User notes:",
        f"  open     : {notes.get('open', 0)}",
        f"  resolved : {notes.get('resolved', 0)}",
    ])
    if active_note.get("snippet"):
        lines.append(f"  active   : [{active_note.get('kind', 'note')}] {active_note.get('snippet')}")
    elif latest_note.get("snippet"):
        lines.append(f"  latest   : [{latest_note.get('kind', 'note')}] {latest_note.get('snippet')}")
    lines.append("  next     : cambrian notes list")
    lines.extend([
        "",
        "Project memory:",
        f"  lessons remembered  : {status.memory.get('lesson_count', 0)}",
        f"  pinned             : {status.memory.get('pinned_count', 0)}",
        f"  suppressed         : {status.memory.get('suppressed_count', 0)}",
        f"  memory-aware routing: {'enabled' if status.memory.get('routing_enabled', False) else 'disabled'}",
        f"  last run            : {status.memory.get('last_run', 'none')}",
        f"  last adoption       : {status.memory.get('last_adoption', 'none')}",
        f"  current risk        : {status.memory.get('current_risk', 'none yet')}",
    ])
    top_hints = list(status.memory.get("top_hints", [])) if isinstance(status.memory, dict) else []
    if top_hints:
        lines.extend(["", "Top routing hints:"])
        for item in top_hints[:2]:
            lines.append(f"  - {item}")
    hygiene = status.memory.get("hygiene", {}) if isinstance(status.memory, dict) else {}
    lines.extend(["", "Memory hygiene:"])
    if isinstance(hygiene, dict) and hygiene.get("checked"):
        lines.append(f"  need review : {hygiene.get('needs_review', 0)}")
        lines.append(f"  stale       : {hygiene.get('stale', 0)}")
        lines.append(f"  conflicting : {hygiene.get('conflicting', 0)}")
    else:
        lines.append("  not checked yet")
    if status.recent_do_session:
        do_title = "Active work:" if status.recent_do_session.get("active", False) else "Latest completed work:"
        lines.extend([
            "",
            do_title,
            f"  request : {status.recent_do_session.get('request', '-')}",
            f"  stage   : {status.recent_do_session.get('stage_label', status.recent_do_session.get('stage', status.recent_do_session.get('status', '-')))}",
            f"  source  : {status.recent_do_session.get('source', '-')}",
            f"  tests   : {status.recent_do_session.get('tests', '-')}",
            f"  next    : {status.recent_do_session.get('next', '-')}",
        ])
    lines.extend(["", "Recent journey:"])
    if status.recent_journey:
        for item in status.recent_journey:
            lines.append(f"  {_journey_symbol(item)} {item.get('summary', '-')}")
    else:
        lines.append("  none yet")
    if status.open_clarification:
        lines.extend([
            "",
            "Open clarification:",
            f"  request : {status.open_clarification.get('request', '-')}",
            f"  missing : {status.open_clarification.get('missing', '-')}",
            f"  top suggestion: {status.open_clarification.get('top_suggestion', '-')}",
            f"  next    : {status.open_clarification.get('next', '-')}",
        ])
    if status.recent_diagnostic:
        lines.extend([
            "",
            "Recent diagnostic:",
            f"  request : {status.recent_diagnostic.get('request', '-')}",
            f"  source  : {status.recent_diagnostic.get('source', '-') or '-'}",
            f"  tests   : {status.recent_diagnostic.get('tests', '-') or '-'}",
            f"  result  : {status.recent_diagnostic.get('result', '-')}",
            f"  next    : {status.recent_diagnostic.get('next', '-')}",
        ])
    if status.recent_patch_intent:
        lines.extend([
            "",
            "Recent patch intent:",
            f"  target : {status.recent_patch_intent.get('target', '-')}",
            f"  status : {status.recent_patch_intent.get('status', '-')}",
            f"  next   : {status.recent_patch_intent.get('next', '-')}",
        ])
    if status.recent_patch_proposal:
        lines.extend([
            "",
            "Recent patch proposal:",
            f"  target : {status.recent_patch_proposal.get('target', '-')}",
            f"  status : {status.recent_patch_proposal.get('status', '-')}",
            f"  tests  : {status.recent_patch_proposal.get('tests', '-')}",
            f"  next   : {status.recent_patch_proposal.get('next', '-')}",
        ])
    if status.latest_patch_adoption:
        lines.extend([
            "",
            "Latest adoption:",
            f"  type   : {status.latest_patch_adoption.get('type', '-')}",
            f"  target : {status.latest_patch_adoption.get('target', '-')}",
            f"  tests  : {status.latest_patch_adoption.get('tests', '-')}",
            f"  reason : {status.latest_patch_adoption.get('reason', '-')}",
        ])
    if status.recent_lessons:
        lines.extend(["", "Learned:"])
        for item in status.recent_lessons[:3]:
            lines.append(f"  - {item}")
    next_actions = list(status.next_actions)
    if isinstance(hygiene, dict):
        if not hygiene.get("checked") and "cambrian memory hygiene" not in next_actions:
            next_actions.append("cambrian memory hygiene")
        elif int(hygiene.get("needs_review", 0) or 0) > 0 and "cambrian memory review --include-suppressed" not in next_actions:
            next_actions.append("cambrian memory review --include-suppressed")
    lines.extend(["", "Next:"])
    for action in next_actions:
        lines.append(f"  {action}" if str(action).startswith("cambrian ") else f"  - {action}")
    return "\n".join(lines)
