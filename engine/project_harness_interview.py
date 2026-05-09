from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_harness_profile import (
    ProjectHarnessProfile,
    ProjectHarnessScanner,
    ProjectHarnessProfileStore,
    default_project_profile_path,
)
from engine.project_pack_catalog import PackCatalogResolver, PackCatalogStore, resolve_pack_catalog_path
from engine.project_pack_install import PackManifestLoader


SCHEMA_VERSION = "1.0.0"
REQUIRED_ANSWER_IDS = {"primary_goal", "test_command", "change_policy"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _atomic_write_text(path: Path, content: str) -> None:
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


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    target = Path(path).resolve()
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _relative(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(path).resolve())


def default_interview_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "interview"


def default_interview_questions_path(project_root: Path) -> Path:
    return default_interview_dir(project_root) / "questions.yaml"


def default_interview_answers_path(project_root: Path) -> Path:
    return default_interview_dir(project_root) / "answers.yaml"


@dataclass
class HarnessQuestion:
    id: str
    question: str
    required: bool = True
    category: str | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class HarnessInterviewSession:
    schema_version: str
    generated_at: str
    session_id: str
    project_profile: dict[str, Any]
    mode: str
    preset_options: list[dict[str, Any]]
    questions: list[HarnessQuestion]
    next_command: str
    saved_questions_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = True
        payload["questions"] = [question.to_dict() for question in self.questions]
        return payload


@dataclass
class HarnessInterviewAnswerResult:
    schema_version: str
    generated_at: str
    status: str
    session_id: str | None
    answers_ref: str | None
    missing: list[str]
    questions: list[HarnessQuestion]
    next_command: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.status == "ready_for_plan"
        payload["questions"] = [question.to_dict() for question in self.questions]
        return payload


class HarnessInterviewBuilder:
    def start(self, project_root: Path) -> HarnessInterviewSession:
        root = Path(project_root).resolve()
        profile = _load_or_scan_profile(root)
        questions = _questions_for_profile(profile)
        preset_options = _preset_options(root, profile)
        session = HarnessInterviewSession(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            session_id=f"harness-interview-{_stamp()}",
            project_profile=_profile_summary(profile),
            mode="custom_harness_first",
            preset_options=preset_options,
            questions=questions,
            next_command="cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json",
        )
        saved = HarnessInterviewStore().save_questions(root, session)
        session.saved_questions_path = _relative(saved, root)
        return session


class HarnessInterviewAnswerHandler:
    def answer(self, project_root: Path, answers_path: Path) -> HarnessInterviewAnswerResult:
        root = Path(project_root).resolve()
        source = Path(answers_path)
        if not source.is_absolute():
            source = root / source
        payload = _load_yaml(source)
        answers = payload.get("answers", {})
        if not isinstance(answers, dict):
            answers = {}
        normalized_answers = {str(key): value for key, value in answers.items()}
        missing = _missing_required_answers(normalized_answers)
        session_id = str(payload.get("session_id")) if payload.get("session_id") is not None else None
        if missing:
            questions = [_question_by_id(item) for item in missing]
            saved_ref = _relative(source, root) if source.exists() else None
            return HarnessInterviewAnswerResult(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                status="needs_more_info",
                session_id=session_id,
                answers_ref=saved_ref,
                missing=missing,
                questions=questions,
                next_command="cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json",
                errors=["Required harness interview answers are missing."],
            )
        target = HarnessInterviewStore().save_answers(root, payload)
        return HarnessInterviewAnswerResult(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status="ready_for_plan",
            session_id=session_id,
            answers_ref=_relative(target, root),
            missing=[],
            questions=[],
            next_command="cambrian harness plan --json",
        )


class HarnessInterviewStore:
    def save_questions(self, project_root: Path, session: HarnessInterviewSession) -> Path:
        return _save_yaml(default_interview_questions_path(project_root), session.to_dict())

    def save_answers(self, project_root: Path, payload: dict[str, Any]) -> Path:
        return _save_yaml(default_interview_answers_path(project_root), payload)

    def load_answers(self, project_root: Path) -> dict[str, Any] | None:
        path = default_interview_answers_path(project_root)
        if not path.exists():
            return None
        return _load_yaml(path)


def render_harness_interview_session(session: HarnessInterviewSession) -> str:
    lines = [
        "Harness Interview",
        "==================================================",
        "",
        "Mode:",
        f"  {session.mode}",
        "",
        "Questions:",
    ]
    for index, question in enumerate(session.questions, start=1):
        required = "required" if question.required else "optional"
        lines.append(f"  {index}. [{question.id}] {question.question} ({required})")
    if session.preset_options:
        lines.extend(["", "Preset options:"])
        for option in session.preset_options:
            status = "compatible" if option.get("compatible") else "not compatible"
            lines.append(f"  - {option.get('id')}: {status} - {option.get('reason')}")
    lines.extend(["", "Next:", f"  {session.next_command}"])
    if session.saved_questions_path:
        lines.extend(["", "Saved:", f"  {session.saved_questions_path}"])
    return "\n".join(lines)


def render_harness_interview_answer_result(result: HarnessInterviewAnswerResult) -> str:
    if result.status == "ready_for_plan":
        return "\n".join(
            [
                "Harness interview answers accepted.",
                "",
                "Next:",
                f"  {result.next_command}",
            ]
        )
    lines = [
        "Harness interview needs more information.",
        "",
        "Missing:",
    ]
    lines.extend([f"  - {item}" for item in result.missing] or ["  - none"])
    if result.questions:
        lines.extend(["", "Questions:"])
        for question in result.questions:
            lines.append(f"  - [{question.id}] {question.question}")
    if result.next_command:
        lines.extend(["", "Next:", f"  {result.next_command}"])
    return "\n".join(lines)


def _load_or_scan_profile(root: Path) -> ProjectHarnessProfile:
    path = default_project_profile_path(root)
    if path.exists():
        return ProjectHarnessProfileStore().load(path)
    profile = ProjectHarnessScanner().scan(root)
    ProjectHarnessProfileStore().save(profile, path)
    return profile


def _profile_summary(profile: ProjectHarnessProfile) -> dict[str, Any]:
    return {
        "project_root": profile.project_root,
        "project_name": profile.project_name,
        "language": profile.language,
        "languages": list(profile.languages),
        "test_framework": profile.test_framework,
        "test_frameworks": list(profile.test_frameworks),
        "domains": list(profile.domains),
        "recommended_harnesses": list(profile.recommended_harnesses),
    }


def _questions_for_profile(profile: ProjectHarnessProfile) -> list[HarnessQuestion]:
    questions = [
        HarnessQuestion(
            id="primary_goal",
            category="goal",
            question="이 프로젝트에서 Cambrian이 주로 맡아야 할 작업은 무엇인가요?",
            required=True,
        ),
        HarnessQuestion(
            id="allowed_scope",
            category="scope",
            question="Cambrian이 다뤄도 되는 코드/업무 범위는 어디까지인가요?",
            required=False,
        ),
        HarnessQuestion(
            id="forbidden_scope",
            category="scope",
            question="Cambrian이 절대 건드리면 안 되는 범위는 무엇인가요?",
            required=True,
        ),
        HarnessQuestion(
            id="test_command",
            category="validation",
            question=_test_command_question(profile),
            required=True,
        ),
    ]
    if profile.language in {"typescript", "javascript"} or "typescript" in profile.languages:
        questions.append(
            HarnessQuestion(
                id="build_command",
                category="validation",
                question="빌드 또는 타입 체크 명령은 무엇인가요? 예: npm run build",
                required=False,
            )
        )
    questions.extend(
        [
            HarnessQuestion(
                id="validation_standard",
                category="validation",
                question="작업 결과가 성공이라고 판단되는 기준은 무엇인가요?",
                required=True,
            ),
            HarnessQuestion(
                id="agent_roles",
                category="agents",
                question="필요한 에이전트 역할은 무엇인가요? 예: 원인 분석, 회귀 테스트, 리뷰",
                required=False,
            ),
            HarnessQuestion(
                id="change_policy",
                category="safety",
                question="Cambrian이 자동 수정까지 해도 되나요, 아니면 패치 제안까지만 해야 하나요?",
                required=True,
            ),
            HarnessQuestion(
                id="risk_level",
                category="safety",
                question="이 프로젝트에서 변경 위험도는 낮음/보통/높음 중 어디에 가깝나요?",
                required=False,
            ),
            HarnessQuestion(
                id="important_paths",
                category="context",
                question="중요하게 봐야 할 파일이나 디렉터리는 어디인가요?",
                required=False,
            ),
        ]
    )
    return questions[:10]


def _test_command_question(profile: ProjectHarnessProfile) -> str:
    if profile.test_framework == "jest":
        return "이 프로젝트의 Jest 테스트 명령은 무엇인가요? 예: npm test"
    if profile.test_framework == "pytest":
        return "이 프로젝트의 pytest 테스트 명령은 무엇인가요? 예: python -m pytest"
    return "이 프로젝트의 테스트 명령은 무엇인가요?"


def _preset_options(root: Path, profile: ProjectHarnessProfile) -> list[dict[str, Any]]:
    try:
        catalog_path = resolve_pack_catalog_path(project_root=root)
        catalog = PackCatalogStore().load(catalog_path)
    except (FileNotFoundError, ValueError):
        return []
    options: list[dict[str, Any]] = []
    for entry in catalog.entries:
        try:
            manifest_path = PackCatalogResolver().resolve_manifest_path(root, entry, catalog_path=catalog_path)
            manifest = PackManifestLoader().load(manifest_path)
            required = _manifest_lane(manifest)
            compatible, reason = _compatibility_reason(required, profile)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            required = {}
            compatible = False
            reason = str(exc)
        options.append(
            {
                "id": entry.pack_id,
                "compatible": compatible,
                "reason": reason,
                "required": required,
            }
        )
    return options


def _manifest_lane(manifest: Any) -> dict[str, Any]:
    lane = manifest.lane if isinstance(manifest.lane, dict) else {}
    compatibility = manifest.compatibility if isinstance(manifest.compatibility, dict) else {}
    stacks = compatibility.get("stacks", [])
    frameworks = compatibility.get("test_frameworks", [])
    language = stacks[0] if isinstance(stacks, list) and stacks else lane.get("language")
    test_framework = frameworks[0] if isinstance(frameworks, list) and frameworks else lane.get("test_framework")
    return {
        "language": str(language or "").strip() or None,
        "test_framework": str(test_framework or "").strip() or None,
        "domains": [str(item) for item in compatibility.get("domains", []) if item] if isinstance(compatibility.get("domains"), list) else [],
    }


def _compatibility_reason(required: dict[str, Any], profile: ProjectHarnessProfile) -> tuple[bool, str]:
    language = required.get("language")
    test_framework = required.get("test_framework")
    if language and language != profile.language:
        return False, f"{language} + {test_framework or 'unknown'} only"
    if test_framework and test_framework != profile.test_framework:
        return False, f"{language or 'unknown'} + {test_framework} only"
    domains = set(required.get("domains") or [])
    if domains and not domains.intersection(set(profile.domains)):
        return False, "domain indicators do not match"
    return True, "compatible seed option"


def _missing_required_answers(answers: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for item in sorted(REQUIRED_ANSWER_IDS):
        value = answers.get(item)
        if value is None:
            missing.append(item)
        elif isinstance(value, str) and not value.strip():
            missing.append(item)
        elif isinstance(value, list) and not [entry for entry in value if str(entry).strip()]:
            missing.append(item)
    return missing


def _question_by_id(question_id: str) -> HarnessQuestion:
    lookup = {question.id: question for question in _questions_for_profile(_unknown_profile())}
    return lookup.get(
        question_id,
        HarnessQuestion(
            id=question_id,
            question=f"{question_id} 값을 알려주세요.",
            required=True,
        ),
    )


def _unknown_profile() -> ProjectHarnessProfile:
    return ProjectHarnessProfile(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        project_root="",
        project_name="project",
        language="unknown",
        languages=["unknown"],
        test_framework="unknown",
        test_frameworks=["unknown"],
        detected_files={},
        detected_paths={},
        domains=[],
        recommended_harnesses=[],
        summary=[],
    )
