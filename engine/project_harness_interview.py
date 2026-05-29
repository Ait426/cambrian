from __future__ import annotations

import json
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
from engine.project_llm_assist import LLM_GENERATION_EVIDENCE_KEY, call_llm_for_generation
from engine.project_pack_catalog import PackCatalogResolver, PackCatalogStore, resolve_pack_catalog_path
from engine.project_pack_install import PackManifestLoader


SCHEMA_VERSION = "1.0.0"
REQUIRED_ANSWER_IDS = {"primary_goal", "test_command", "change_policy"}
INTERVIEW_INFERENCE_STAGE = "harness_generation"
DOC_CONTEXT_LIMIT_CHARS = 24000
DOC_CONTEXT_PER_FILE_LIMIT_CHARS = 6000
DOC_CONTEXT_SKIP_DIRS = {
    ".cambrian",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "coverage",
    "archive",
    "demo",
    "examples",
    "fixtures",
    "sample",
    "samples",
    "skill_pool",
    ".launch_runs",
    "logs",
    "tmp",
    "temp",
}
DOC_CONTEXT_SKIP_DIR_PREFIXES = (
    ".pytest",
    ".launch_runs",
)
DOC_CONTEXT_PRIORITY_NAMES = {
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "README.ko.md",
    "PROJECT.md",
    "PROJECT_BRIEF.md",
    "CONTEXT_INDEX.md",
    "ARCHITECTURE.md",
    "NEXT_SESSION_HANDOFF.md",
}
DOC_CONTEXT_AUTHORITY_POLICY = {
    "source_of_truth": [
        "root identity docs such as README.md, AGENTS.md, CLAUDE.md, PROJECT_BRIEF.md, and CONTEXT_INDEX.md",
        "explicit architecture, release, and decision docs selected from the active project tree",
    ],
    "excluded_generated_or_sample_docs": [
        ".cambrian/",
        ".pytest*/",
        ".launch_runs/",
        "archive/",
        "demo/",
        "examples/",
        "fixtures/",
        "sample/",
        "samples/",
        "skill_pool/",
        "dist/",
        "build/",
        "logs/",
        "tmp/",
    ],
    "promotion_rule": "interview answers may use selected docs, but generated, demo, sample, fixture, and runtime documents must not override active project identity",
}


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


@dataclass
class HarnessInterviewAutoDraftResult:
    schema_version: str
    generated_at: str
    status: str
    session_id: str
    answers_ref: str | None
    source_mode: str
    answers: dict[str, Any]
    missing: list[str]
    questions: list[HarnessQuestion]
    document_context: dict[str, Any]
    llm_assist_policy: dict[str, Any]
    llm_generation_evidence: dict[str, Any]
    llm_notes: str | None
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


def infer_interview_answers_from_project_docs(
    project_root: Path,
    *,
    provider: Any | None = None,
    save: bool = True,
) -> HarnessInterviewAutoDraftResult:
    root = Path(project_root).resolve()
    profile = _load_or_scan_profile(root)
    session = HarnessInterviewBuilder().start(root)
    document_context = _collect_project_document_context(root)
    answers = _infer_answers_from_profile_and_docs(profile, document_context)
    llm_assist = _interview_inference_llm_assist(profile, document_context, answers, provider=provider)
    llm_suggested_answers = _llm_suggested_interview_answers(str(llm_assist.get("llm_notes") or ""))
    if llm_suggested_answers:
        _merge_missing_answers(answers, llm_suggested_answers)
    if llm_assist.get("llm_notes"):
        answers["llm_project_summary"] = str(llm_assist.get("llm_notes") or "").strip()[:4000]
    missing = _missing_required_answers(answers)
    source_mode = "project_docs_llm_assisted" if llm_assist.get(LLM_GENERATION_EVIDENCE_KEY, {}).get("called") else "project_docs_bootstrap"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "session_id": session.session_id,
        "source_mode": source_mode,
        "source": {
            "kind": "project_docs_interview_inference",
            "project_profile_ref": ".cambrian/project/profile.yaml",
            "questions_ref": ".cambrian/interview/questions.yaml",
            "documents": list(document_context.get("docs_found", [])),
        },
        "draft_policy": {
            "interview_is_fallback": True,
            "ask_user_only_for_missing_or_low_confidence_answers": True,
            "llm_enrichment_required": bool(llm_assist.get("policy", {}).get("llm_enrichment_required")),
        },
        "answers": answers,
        "llm_suggested_answers": llm_suggested_answers,
        "document_context": document_context,
        "llm_assist_policy": llm_assist.get("policy", {}),
        LLM_GENERATION_EVIDENCE_KEY: llm_assist.get(LLM_GENERATION_EVIDENCE_KEY, {}),
    }
    answers_ref: str | None = None
    if save:
        answers_path = HarnessInterviewStore().save_answers(root, payload)
        answers_ref = _relative(answers_path, root)
    questions = [_question_by_id(item) for item in missing]
    warnings: list[str] = []
    if not document_context.get("docs_found"):
        warnings.append("No project Markdown documents were found; manual interview remains necessary.")
    if missing:
        warnings.append("Some required answers still need user confirmation.")
    status = "ready_for_plan" if not missing else "needs_more_info"
    return HarnessInterviewAutoDraftResult(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        status=status,
        session_id=session.session_id,
        answers_ref=answers_ref,
        source_mode=source_mode,
        answers=answers,
        missing=missing,
        questions=questions,
        document_context=document_context,
        llm_assist_policy=llm_assist.get("policy", {}),
        llm_generation_evidence=llm_assist.get(LLM_GENERATION_EVIDENCE_KEY, {}),
        llm_notes=llm_assist.get("llm_notes"),
        next_command="cambrian harness plan --json" if not missing else "cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json",
        warnings=warnings,
        errors=[] if not missing else ["Required harness interview answers are still missing."],
    )


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


def render_harness_interview_auto_draft_result(result: HarnessInterviewAutoDraftResult) -> str:
    lines = [
        "Harness interview inference",
        "==================================================",
        "",
        f"Status: {result.status}",
        f"Source: {result.source_mode}",
        f"Documents: {result.document_context.get('document_count', 0)}",
        f"LLM called: {str(bool(result.llm_generation_evidence.get('called'))).lower()}",
    ]
    if result.answers_ref:
        lines.extend(["", "Saved:", f"  {result.answers_ref}"])
    if result.missing:
        lines.extend(["", "Missing:"])
        lines.extend([f"  - {item}" for item in result.missing])
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


def _collect_project_document_context(root: Path) -> dict[str, Any]:
    candidates = _project_markdown_candidates(root)
    snippets: list[dict[str, Any]] = []
    total = 0
    for path in candidates:
        if total >= DOC_CONTEXT_LIMIT_CHARS:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        stripped = text.strip()
        if not stripped:
            continue
        excerpt = stripped[: min(DOC_CONTEXT_PER_FILE_LIMIT_CHARS, DOC_CONTEXT_LIMIT_CHARS - total)]
        total += len(excerpt)
        snippets.append(
            {
                "path": _relative(path, root),
                "chars": len(stripped),
                "excerpt": excerpt,
            }
        )
    combined_parts = [f"--- {item['path']} ---\n{item['excerpt']}" for item in snippets]
    return {
        "docs_found": [str(item["path"]) for item in snippets],
        "document_count": len(snippets),
        "combined_chars": total,
        "has_strong_docs": bool(snippets and total >= 500),
        "combined_excerpt": "\n\n".join(combined_parts)[:DOC_CONTEXT_LIMIT_CHARS],
        "document_authority": dict(DOC_CONTEXT_AUTHORITY_POLICY),
        "noise_filter": {
            "excluded_dirs": sorted(DOC_CONTEXT_SKIP_DIRS),
            "excluded_dir_prefixes": list(DOC_CONTEXT_SKIP_DIR_PREFIXES),
            "policy": "generated, demo, sample, fixture, and runtime docs are excluded before answer inference",
        },
    }


def _project_markdown_candidates(root: Path) -> list[Path]:
    root = Path(root).resolve()
    paths: list[Path] = []
    for path in root.rglob("*.md"):
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(_is_doc_context_skipped_part(part) for part in rel_parts[:-1]):
            continue
        paths.append(path)

    def rank(path: Path) -> tuple[int, int, str]:
        name = path.name
        try:
            depth = len(path.relative_to(root).parts)
        except ValueError:
            depth = 99
        priority = 0 if name in DOC_CONTEXT_PRIORITY_NAMES else 1
        if name.upper().startswith("README"):
            priority = 0
        return (priority, depth, str(path).lower())

    return sorted(paths, key=rank)[:24]


def _is_doc_context_skipped_part(part: str) -> bool:
    text = str(part or "")
    if text in DOC_CONTEXT_SKIP_DIRS:
        return True
    if text.startswith("."):
        return True
    return any(text.startswith(prefix) for prefix in DOC_CONTEXT_SKIP_DIR_PREFIXES)


def _infer_answers_from_profile_and_docs(profile: ProjectHarnessProfile, document_context: dict[str, Any]) -> dict[str, Any]:
    docs_text = str(document_context.get("combined_excerpt") or "")
    domains = list(profile.domains)
    important_paths = _important_paths_from_profile(profile)
    test_command = _infer_test_command(profile, docs_text)
    answers = {
        "primary_goal": _infer_primary_goal(profile, docs_text, domains),
        "allowed_scope": important_paths or ["documented project files and validation evidence"],
        "forbidden_scope": [
            "do not expose or print secrets",
            "do not git push, deploy, or publish without explicit approval",
            "do not apply source changes when the harness policy is proposal_only",
        ],
        "test_command": test_command,
        "build_command": _infer_build_command(profile, docs_text),
        "validation_standard": "Use project documents, local file evidence, and validation command output before claiming success.",
        "agent_roles": _infer_agent_roles(domains, docs_text),
        "change_policy": _infer_change_policy(docs_text),
        "risk_level": "medium",
        "important_paths": important_paths,
    }
    return {key: value for key, value in answers.items() if value not in (None, [], "")}


def _interview_inference_llm_assist(
    profile: ProjectHarnessProfile,
    document_context: dict[str, Any],
    answers: dict[str, Any],
    *,
    provider: Any | None,
) -> dict[str, Any]:
    system = (
        "You are Cambrian's harness interview inference assistant. "
        "Read project documents and scanner evidence, then summarize the project's domain, "
        "validation commands, safety policy, and missing interview fields. "
        "Do not invent commands that are not supported by evidence. "
        "Return compact JSON with an answers object when you can infer fields."
    )
    user = json.dumps(
        {
            "project_profile": _profile_summary(profile),
            "document_context": {
                "docs_found": document_context.get("docs_found", []),
                "combined_excerpt": document_context.get("combined_excerpt", ""),
            },
            "deterministic_answers": answers,
            "required_answer_ids": sorted(REQUIRED_ANSWER_IDS),
        },
        ensure_ascii=False,
        indent=2,
    )
    return call_llm_for_generation(
        provider,
        stage=INTERVIEW_INFERENCE_STAGE,
        system=system,
        user=user,
        max_tokens=1800,
    )


def _llm_suggested_interview_answers(text: str) -> dict[str, Any]:
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        return {}
    raw_answers = payload.get("answers", payload)
    if not isinstance(raw_answers, dict):
        return {}
    allowed = {
        "primary_goal",
        "allowed_scope",
        "forbidden_scope",
        "test_command",
        "build_command",
        "validation_standard",
        "agent_roles",
        "change_policy",
        "risk_level",
        "important_paths",
    }
    return {str(key): value for key, value in raw_answers.items() if str(key) in allowed and _answer_has_value(value)}


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    candidates = [stripped]
    first = stripped.find("{")
    last = stripped.rfind("}")
    if 0 <= first < last:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _merge_missing_answers(answers: dict[str, Any], suggested: dict[str, Any]) -> None:
    for key, value in suggested.items():
        if not _answer_has_value(answers.get(key)) and _answer_has_value(value):
            answers[key] = value


def _answer_has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool([item for item in value if str(item).strip()])
    return True


def _infer_primary_goal(profile: ProjectHarnessProfile, docs_text: str, domains: list[str]) -> str:
    explicit = _first_markdown_heading(docs_text)
    project_name = profile.project_name or "project"
    if explicit:
        return f"{project_name}: {explicit}"
    if domains:
        return f"Build and maintain a project-specific Cambrian harness for {project_name}, focused on {', '.join(domains[:4])}."
    language = profile.language if profile.language != "unknown" else "documented"
    return f"Build and maintain a project-specific Cambrian harness for the {language} project {project_name}."


def _first_markdown_heading(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if heading:
                return heading[:240]
    return ""


def _infer_test_command(profile: ProjectHarnessProfile, docs_text: str) -> str:
    for command in (
        "python -m pytest",
        "pytest -q",
        "pytest",
        "npm test",
        "npm run test",
        "pnpm test",
        "yarn test",
        "npm run verify",
        "python tools/verify_static_project.py",
    ):
        if command.lower() in docs_text.lower():
            return command
    package_test = _package_script_command(profile, "test")
    if package_test:
        return package_test
    framework = (profile.test_framework or "").lower()
    frameworks = {str(item).lower() for item in profile.test_frameworks if item}
    if "jest" in framework or "jest" in frameworks:
        return "npm test"
    if "pytest" in framework or "pytest" in frameworks:
        return "python -m pytest"
    return ""


def _infer_build_command(profile: ProjectHarnessProfile, docs_text: str) -> str:
    for command in ("npm run build", "pnpm build", "yarn build", "python -m build"):
        if command.lower() in docs_text.lower():
            return command
    package_build = _package_script_command(profile, "build")
    if package_build:
        return package_build
    return ""


def _package_script_command(profile: ProjectHarnessProfile, script_name: str) -> str:
    root = Path(profile.project_root or "")
    if not root.is_dir():
        return ""
    package_json = root / "package.json"
    if not package_json.exists():
        return ""
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    scripts = payload.get("scripts", {}) if isinstance(payload, dict) else {}
    if not isinstance(scripts, dict):
        return ""
    script = scripts.get(script_name)
    if not str(script or "").strip():
        return ""
    return "npm test" if script_name == "test" else f"npm run {script_name}"


def _infer_change_policy(docs_text: str) -> str:
    lowered = docs_text.lower()
    proposal_markers = ("proposal_only", "proposal only", "제안", "자동 적용 금지", "수동 승인", "approval")
    if any(marker in lowered for marker in proposal_markers):
        return "proposal_only"
    return "proposal_only"


def _infer_agent_roles(domains: list[str], docs_text: str) -> list[str]:
    roles = ["context-evidence-reader", "verification-owner", "risk-reviewer"]
    lowered = docs_text.lower()
    for domain in domains[:4]:
        roles.append(f"{domain}-specialist")
    if "stage" in lowered or "pipeline" in lowered:
        roles.append("pipeline-stage-validator")
    if "llm" in lowered or "anthropic" in lowered or "openai" in lowered:
        roles.append("llm-api-failure-analyst")
    return list(dict.fromkeys(roles))[:5]


def _important_paths_from_profile(profile: ProjectHarnessProfile) -> list[str]:
    paths: list[str] = []
    for key in ("package_json", "pyproject", "tests", "python", "typescript", "javascript"):
        paths.extend([str(item) for item in profile.detected_paths.get(key, []) if item])
    evidence_card = profile.evidence_card if isinstance(profile.evidence_card, dict) else {}
    for item in evidence_card.get("identity_evidence", []) if isinstance(evidence_card.get("identity_evidence"), list) else []:
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item.get("path")))
    return list(dict.fromkeys(paths))[:12]


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
