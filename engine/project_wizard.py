"""Cambrian 프로젝트 wizard 도우미."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml


PROJECT_TYPE_CHOICES = (
    "python",
    "javascript",
    "typescript",
    "web",
    "api",
    "library",
    "unknown",
)
MODE_CHOICES = ("conservative", "balanced", "aggressive")
PRIMARY_USE_CASE_CHOICES = (
    "bug_fix",
    "regression_test",
    "test_generation",
    "small_refactor",
    "docs_update",
    "review_candidate",
)

SKILL_CATALOG: dict[str, dict[str, str]] = {
    "bug_fix": {
        "id": "bug_fix",
        "label": "Bug fix",
        "description": "Diagnose and patch small defects with related tests.",
    },
    "regression_test": {
        "id": "regression_test",
        "label": "Regression test",
        "description": "Add or run tests to confirm behavior.",
    },
    "test_generation": {
        "id": "test_generation",
        "label": "Test generation",
        "description": "Create or strengthen tests around the request.",
    },
    "small_refactor": {
        "id": "small_refactor",
        "label": "Small refactor",
        "description": "Improve code with minimal surface area.",
    },
    "docs_update": {
        "id": "docs_update",
        "label": "Docs update",
        "description": "Update documentation and keep it reviewable.",
    },
    "review_candidate": {
        "id": "review_candidate",
        "label": "Review candidate",
        "description": "Compare approaches and pick safer winner.",
    },
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
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _dump_yaml(path: Path, payload: dict) -> None:
    """YAML 파일을 저장한다."""
    _atomic_write_text(
        path,
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
    )


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _to_list(value: object) -> list[str]:
    """문자열 또는 리스트를 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        normalized = value.replace("\n", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return [str(value).strip()]


@dataclass
class ProjectWizardQuestion:
    """Wizard 질문 한 항목."""

    id: str
    prompt: str
    default: object | None
    required: bool
    choices: list[str] | None = None
    answer: object | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ProjectWizardAnswers:
    """Wizard가 수집한 답변."""

    project_name: str
    project_type: str
    stack: list[str]
    test_command: str | None
    primary_use_cases: list[str]
    protected_paths: list[str]
    mode: str
    max_variants: int
    auto_adoption: bool
    notes: list[str]

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ProjectWizardResult:
    """Wizard 실행 결과."""

    status: str
    answers: ProjectWizardAnswers | None
    created_files: list[str]
    skipped_files: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["answers"] = self.answers.to_dict() if self.answers else None
        return payload


class ProjectWizard:
    """프로젝트 인터뷰 기반 Cambrian 초기화기."""

    CONFIG_FILES: tuple[str, ...] = (
        "project.yaml",
        "rules.yaml",
        "skills.yaml",
        "profile.yaml",
        "init_report.yaml",
    )

    def run(
        self,
        project_root: Path,
        detected: dict,
        answers: dict | None = None,
        force: bool = False,
        interactive: bool = True,
    ) -> ProjectWizardResult:
        """Wizard를 실행하고 설정 파일을 생성한다."""
        root = Path(project_root).resolve()
        cambrian_dir = root / ".cambrian"
        cambrian_dir.mkdir(parents=True, exist_ok=True)
        existing = [
            f".cambrian/{file_name}"
            for file_name in self.CONFIG_FILES
            if (cambrian_dir / file_name).exists()
        ]
        if existing and not force:
            return ProjectWizardResult(
                status="blocked",
                answers=None,
                created_files=[],
                skipped_files=existing,
                warnings=["Cambrian project files already exist."],
                errors=[],
                next_actions=[
                    "cambrian init --wizard --force",
                ],
            )

        defaults = self._build_defaults(root, detected)
        normalized_answers, warnings = self._collect_answers(
            defaults=defaults,
            answers=answers or {},
            interactive=interactive,
        )
        answers_model = ProjectWizardAnswers(**normalized_answers)
        config_payloads = self._build_config_payloads(root, detected, answers_model)
        created_files: list[str] = []

        for file_name, payload in config_payloads.items():
            path = cambrian_dir / file_name
            _dump_yaml(path, payload)
            created_files.append(f".cambrian/{file_name}")

        return ProjectWizardResult(
            status="completed",
            answers=answers_model,
            created_files=created_files,
            skipped_files=[],
            warnings=warnings,
            errors=[],
            next_actions=[
                'cambrian run "fix a small bug"',
                "cambrian status",
            ],
        )

    def _build_defaults(self, project_root: Path, detected: dict) -> dict:
        """감지 결과에서 wizard 기본값을 만든다."""
        project_type = str(detected.get("project_type") or "unknown")
        stack = self._detect_stack(project_root, detected)
        test_command = str(detected.get("test_command") or "") or None
        mode = "balanced"
        max_variants = 2
        return {
            "project_name": project_root.name,
            "project_type": project_type if project_type in PROJECT_TYPE_CHOICES else "unknown",
            "stack": stack,
            "test_command": test_command,
            "primary_use_cases": self._default_primary_use_cases(project_type, bool(test_command)),
            "protected_paths": self._default_protected_paths(project_root),
            "mode": mode,
            "max_variants": max_variants,
            "auto_adoption": False,
            "notes": [],
        }

    def _collect_answers(
        self,
        *,
        defaults: dict,
        answers: dict,
        interactive: bool,
    ) -> tuple[dict, list[str]]:
        """기본값, answers-file, interactive 입력을 병합한다."""
        warnings: list[str] = []
        merged = dict(defaults)
        incoming = dict(answers)

        questions = [
            ProjectWizardQuestion(
                id="project_name",
                prompt="Project name?",
                default=merged["project_name"],
                required=True,
            ),
            ProjectWizardQuestion(
                id="project_type",
                prompt="What kind of project is this?",
                default=merged["project_type"],
                required=True,
                choices=list(PROJECT_TYPE_CHOICES),
            ),
            ProjectWizardQuestion(
                id="stack",
                prompt="Detected stack. Use this stack?",
                default=merged["stack"],
                required=False,
            ),
            ProjectWizardQuestion(
                id="test_command",
                prompt="How should Cambrian run tests?",
                default=merged["test_command"],
                required=False,
            ),
            ProjectWizardQuestion(
                id="primary_use_cases",
                prompt="What should Cambrian help with most?",
                default=merged["primary_use_cases"],
                required=True,
                choices=list(PRIMARY_USE_CASE_CHOICES),
            ),
            ProjectWizardQuestion(
                id="protected_paths",
                prompt="What should Cambrian never touch without explicit approval?",
                default=merged["protected_paths"],
                required=True,
            ),
            ProjectWizardQuestion(
                id="mode",
                prompt="Preferred operating mode?",
                default=merged["mode"],
                required=True,
                choices=list(MODE_CHOICES),
            ),
            ProjectWizardQuestion(
                id="max_variants",
                prompt="How many approaches should Cambrian try by default?",
                default=merged["max_variants"],
                required=True,
            ),
            ProjectWizardQuestion(
                id="auto_adoption",
                prompt="Should Cambrian ever adopt automatically?",
                default=False,
                required=True,
            ),
            ProjectWizardQuestion(
                id="notes",
                prompt="Any notes for Cambrian?",
                default=[],
                required=False,
            ),
        ]

        for question in questions:
            if question.id in incoming:
                question.answer = incoming.get(question.id)
            elif interactive:
                question.answer = self._ask(question)
            else:
                question.answer = question.default
            merged[question.id] = question.answer

        merged["project_name"] = str(merged.get("project_name") or defaults["project_name"]).strip()

        project_type = str(merged.get("project_type") or defaults["project_type"]).strip().lower()
        if project_type not in PROJECT_TYPE_CHOICES:
            warnings.append(f"invalid project_type '{project_type}', falling back to {defaults['project_type']}.")
            project_type = str(defaults["project_type"])
        merged["project_type"] = project_type

        stack = _to_list(merged.get("stack"))
        merged["stack"] = stack or list(defaults["stack"])

        test_command = merged.get("test_command")
        if isinstance(test_command, str):
            test_command = test_command.strip() or None
        elif test_command is not None:
            test_command = str(test_command)
        merged["test_command"] = test_command or defaults.get("test_command")

        use_cases = _to_list(merged.get("primary_use_cases"))
        filtered_use_cases = [item for item in use_cases if item in PRIMARY_USE_CASE_CHOICES]
        invalid_use_cases = [item for item in use_cases if item not in PRIMARY_USE_CASE_CHOICES]
        if invalid_use_cases:
            warnings.append(
                "ignored invalid primary_use_cases: " + ", ".join(invalid_use_cases)
            )
        if not filtered_use_cases:
            filtered_use_cases = list(defaults["primary_use_cases"])
        merged["primary_use_cases"] = _dedupe(filtered_use_cases)

        protected_paths = _to_list(merged.get("protected_paths"))
        merged["protected_paths"] = _dedupe(protected_paths or list(defaults["protected_paths"]))

        mode = str(merged.get("mode") or defaults["mode"]).strip().lower()
        if mode not in MODE_CHOICES:
            warnings.append(f"invalid mode '{mode}', falling back to balanced.")
            mode = "balanced"
        merged["mode"] = mode

        max_variants = merged.get("max_variants")
        try:
            parsed_max_variants = int(max_variants)
        except (TypeError, ValueError):
            parsed_max_variants = self._default_max_variants(mode)
        if parsed_max_variants < 1:
            parsed_max_variants = self._default_max_variants(mode)
        merged["max_variants"] = parsed_max_variants

        auto_adoption = bool(merged.get("auto_adoption", False))
        if auto_adoption:
            warnings.append("auto_adoption=true is not allowed in V1. Cambrian will keep explicit adoption only.")
        merged["auto_adoption"] = False

        merged["notes"] = _to_list(merged.get("notes"))
        return merged, warnings

    @staticmethod
    def _ask(question: ProjectWizardQuestion) -> object:
        """간단한 interactive 입력을 받는다."""
        default = question.default
        if isinstance(default, list):
            default_label = ", ".join(str(item) for item in default)
        else:
            default_label = str(default) if default is not None else ""
        suffix = f" [{default_label}]" if default_label else ""
        response = input(f"{question.prompt}{suffix}: ").strip()
        if not response:
            return question.default
        return response

    def _build_config_payloads(
        self,
        project_root: Path,
        detected: dict,
        answers: ProjectWizardAnswers,
    ) -> dict[str, dict]:
        """Wizard 답변으로 설정 파일 payload를 만든다."""
        created_at = _now()
        recommended_skills = self._build_recommended_skills(answers)
        selection_default = self._build_default_selection(answers, recommended_skills)
        test_command = answers.test_command or ""

        project_payload = {
            "schema_version": "1.1.0",
            "project": {
                "name": answers.project_name,
                "type": answers.project_type,
                "root": ".",
                "created_at": created_at,
                "stack": list(answers.stack),
            },
            "detected": {
                "git": bool(detected.get("git", False)),
                "python": bool(detected.get("python", False)),
                "pytest": bool(detected.get("pytest", False)),
                "package_files": list(detected.get("package_files", [])),
            },
            "test": {
                "command": test_command,
                "related_test_strategy": "prefer_related_tests",
            },
            "ai_work": {
                "primary_use_cases": list(selection_default),
            },
            "onboarding": {
                "wizard_completed": True,
                "completed_at": created_at,
            },
            "notes": list(answers.notes),
        }

        rules_payload = {
            "schema_version": "1.1.0",
            "safety": {
                "require_tests_before_adoption": True,
                "never_auto_adopt": True,
                "preserve_source_artifacts": True,
            },
            "workspace": {
                "protect_paths": list(answers.protected_paths),
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
            "schema_version": "1.1.0",
            "recommended_skills": recommended_skills,
            "selection": {
                "default": list(selection_default),
            },
        }

        profile_payload = {
            "schema_version": "1.1.0",
            "mode": answers.mode,
            "defaults": {
                "max_variants": answers.max_variants,
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

        init_report_payload = {
            "schema_version": "1.0.0",
            "created_at": created_at,
            "status": "completed",
            "project_name": answers.project_name,
            "project_type": answers.project_type,
            "stack": list(answers.stack),
            "test_command": test_command,
            "recommended_skills": list(selection_default),
            "protected_paths": list(answers.protected_paths),
            "mode": answers.mode,
            "next_actions": [
                'Run: cambrian run "fix a small bug"',
                "Check project memory: cambrian status",
            ],
        }

        return {
            "project.yaml": project_payload,
            "rules.yaml": rules_payload,
            "skills.yaml": skills_payload,
            "profile.yaml": profile_payload,
            "init_report.yaml": init_report_payload,
        }

    @staticmethod
    def _detect_stack(project_root: Path, detected: dict) -> list[str]:
        """감지 결과에서 stack 목록을 만든다."""
        stack: list[str] = []
        if detected.get("python"):
            stack.append("python")
        if detected.get("pytest"):
            stack.append("pytest")
        pyproject_path = project_root / "pyproject.toml"
        requirements_path = project_root / "requirements.txt"
        for path in (pyproject_path, requirements_path):
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8").lower()
            except OSError:
                continue
            if "fastapi" in content:
                stack.append("fastapi")
            if "django" in content:
                stack.append("django")
        if (project_root / "package.json").exists():
            stack.append("javascript")
        return _dedupe(stack)

    @staticmethod
    def _default_primary_use_cases(project_type: str, has_tests: bool) -> list[str]:
        """프로젝트 타입에 맞는 기본 사용 영역을 만든다."""
        if project_type == "python":
            defaults = ["bug_fix", "small_refactor", "review_candidate"]
        else:
            defaults = ["bug_fix", "review_candidate"]
        if has_tests:
            defaults.insert(1, "regression_test")
        return _dedupe(defaults)

    @staticmethod
    def _default_protected_paths(project_root: Path) -> list[str]:
        """기본 보호 경로를 만든다."""
        protected = [".git", ".cambrian"]
        for candidate in ("node_modules", "dist", "build", ".venv", "venv", "migrations"):
            if candidate in {".venv", "venv"} or (project_root / candidate).exists():
                protected.append(candidate)
        return _dedupe(protected)

    @staticmethod
    def _default_max_variants(mode: str) -> int:
        """mode별 기본 max_variants를 반환한다."""
        return {
            "conservative": 1,
            "balanced": 2,
            "aggressive": 3,
        }.get(mode, 2)

    @staticmethod
    def _build_recommended_skills(answers: ProjectWizardAnswers) -> list[dict]:
        """답변에 맞는 추천 skill 목록을 만든다."""
        skill_ids = list(answers.primary_use_cases)
        if answers.test_command and "regression_test" not in skill_ids:
            skill_ids.append("regression_test")
        recommended = [
            dict(SKILL_CATALOG[skill_id])
            for skill_id in _dedupe(skill_ids)
            if skill_id in SKILL_CATALOG
        ]
        if not recommended:
            recommended.append(dict(SKILL_CATALOG["bug_fix"]))
        return recommended

    @staticmethod
    def _build_default_selection(
        answers: ProjectWizardAnswers,
        recommended_skills: list[dict],
    ) -> list[str]:
        """selection.default 목록을 만든다."""
        recommended_ids = [str(item.get("id", "")) for item in recommended_skills]
        selection = [item for item in answers.primary_use_cases if item in recommended_ids]
        if answers.test_command and "regression_test" in recommended_ids:
            selection.append("regression_test")
        return _dedupe(selection)


def load_answers_file(path: Path) -> dict:
    """answers-file YAML을 로드한다."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("answers-file 최상위는 dict여야 합니다.")
    return payload


def render_wizard_summary(result: ProjectWizardResult) -> str:
    """Wizard 결과를 사람이 읽기 좋게 렌더링한다."""
    if result.status != "completed" or result.answers is None:
        headline = "Cambrian wizard did not complete."
        if result.warnings:
            headline = result.warnings[0]
        if result.errors:
            headline = result.errors[0]
        lines = [
            headline,
            "",
        ]
        if result.errors:
            lines.append("Reason:")
            for item in result.errors:
                lines.append(f"  - {item}")
            lines.append("")
        elif result.warnings and len(result.warnings) > 1:
            lines.append("Warnings:")
            for item in result.warnings[1:]:
                lines.append(f"  - {item}")
            lines.append("")
        if result.status == "blocked":
            lines.append("Use:")
            for item in result.next_actions:
                lines.append(f"  {item}")
            lines.append("")
            lines.append("No files changed.")
            return "\n".join(lines)
        if result.warnings:
            lines.append("Use:" if result.status == "blocked" else "Warnings:")
            for item in result.next_actions if result.status == "blocked" else result.warnings:
                lines.append(f"  {item}" if result.status == "blocked" else f"  - {item}")
            if result.status != "blocked":
                lines.append("")
        return "\n".join(lines)

    answers = result.answers
    lines = [
        "Cambrian fitted your project harness.",
        "",
        "Project:",
        f"  name : {answers.project_name}",
        f"  type : {answers.project_type}",
        f"  tests: {answers.test_command or 'none yet'}",
        "",
        "Cambrian will help with:",
    ]
    for item in answers.primary_use_cases:
        lines.append(f"  - {item}")
    lines.extend([
        "",
        "Safety:",
        "  adoption : explicit only",
        "  protected:",
    ])
    for item in answers.protected_paths:
        lines.append(f"    - {item}")
    lines.extend([
        "",
        "Mode:",
        f"  {answers.mode}, max variants: {answers.max_variants}",
        "",
        "Created:",
    ])
    for path in result.created_files:
        lines.append(f"  {path}")
    if result.warnings:
        lines.extend(["", "Warnings:"])
        for item in result.warnings:
            lines.append(f"  - {item}")
    lines.extend(["", "Next:"])
    for item in result.next_actions:
        lines.append(f"  {item}" if item.startswith("cambrian ") else f"  - {item}")
    return "\n".join(lines)
