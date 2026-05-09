"""Cambrian 프로젝트 하네스 프로필."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_memory import default_memory_path, load_project_memory
from engine.project_memory_hygiene import default_memory_hygiene_path, load_memory_hygiene
from engine.project_notes import ProjectNotesStore, default_notes_dir

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
_DEFAULT_SAFETY_POLICY = "only explicit patch apply/adoption"


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


def _load_yaml(path: Path, warnings: list[str]) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        message = f"YAML 읽기 실패: {path} ({exc})"
        logger.warning(message)
        warnings.append(message)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        message = f"YAML 형식 오류: {path}"
        logger.warning(message)
        warnings.append(message)
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


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_harness_profile_path(project_root: Path) -> Path:
    """기본 harness profile 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "harness" / "profile.yaml"


@dataclass
class HarnessProfile:
    """현재 프로젝트의 작업 하네스 스냅샷."""

    schema_version: str
    generated_at: str
    harness_id: str
    project_name: str | None
    project_type: str | None
    root: str
    stack: list[str]
    test_command: str | None
    protect_paths: list[str]
    mode: str | None
    primary_use_cases: list[str]
    safety: dict
    memory_summary: dict
    notes_summary: dict
    active_agents: list[str]
    recommended_agent_roles: list[str]
    source_refs: dict
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class HarnessProfileStore:
    """하네스 프로필 저장/로드 도구."""

    def save(self, profile: HarnessProfile, path: Path) -> Path:
        """프로필을 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(profile.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> HarnessProfile:
        """저장된 하네스 프로필을 로드한다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("harness profile YAML 최상위는 dict여야 합니다.")
        return HarnessProfile(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            harness_id=str(payload.get("harness_id", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            project_type=str(payload.get("project_type")) if payload.get("project_type") is not None else None,
            root=str(payload.get("root", "")),
            stack=[str(item) for item in payload.get("stack", []) if item],
            test_command=str(payload.get("test_command")) if payload.get("test_command") is not None else None,
            protect_paths=[str(item) for item in payload.get("protect_paths", []) if item],
            mode=str(payload.get("mode")) if payload.get("mode") is not None else None,
            primary_use_cases=[str(item) for item in payload.get("primary_use_cases", []) if item],
            safety=dict(payload.get("safety", {})) if isinstance(payload.get("safety"), dict) else {},
            memory_summary=dict(payload.get("memory_summary", {})) if isinstance(payload.get("memory_summary"), dict) else {},
            notes_summary=dict(payload.get("notes_summary", {})) if isinstance(payload.get("notes_summary"), dict) else {},
            active_agents=[str(item) for item in payload.get("active_agents", []) if item],
            recommended_agent_roles=[str(item) for item in payload.get("recommended_agent_roles", []) if item],
            source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


class HarnessProfileBuilder:
    """프로젝트 설정과 메모리에서 하네스 프로필을 만든다."""

    def build(self, project_root: Path) -> HarnessProfile:
        """현재 프로젝트 기준 하네스 프로필을 생성한다."""
        root = Path(project_root).resolve()
        cambrian_dir = root / ".cambrian"
        warnings: list[str] = []
        errors: list[str] = []

        project_payload = _load_yaml(cambrian_dir / "project.yaml", warnings) or {}
        rules_payload = _load_yaml(cambrian_dir / "rules.yaml", warnings) or {}
        skills_payload = _load_yaml(cambrian_dir / "skills.yaml", warnings) or {}
        profile_payload = _load_yaml(cambrian_dir / "profile.yaml", warnings) or {}
        existing_profile = _load_yaml(default_harness_profile_path(root), warnings) or {}

        project_meta = project_payload.get("project", {}) if isinstance(project_payload.get("project"), dict) else {}
        test_meta = project_payload.get("test", {}) if isinstance(project_payload.get("test"), dict) else {}
        ai_work = project_payload.get("ai_work", {}) if isinstance(project_payload.get("ai_work"), dict) else {}
        safety_meta = rules_payload.get("safety", {}) if isinstance(rules_payload.get("safety"), dict) else {}
        workspace_meta = rules_payload.get("workspace", {}) if isinstance(rules_payload.get("workspace"), dict) else {}

        memory_summary = self._build_memory_summary(root, warnings)
        notes_summary = self._build_notes_summary(root, warnings)

        primary_use_cases = _dedupe([str(item) for item in ai_work.get("primary_use_cases", []) if item])
        if not primary_use_cases:
            primary_use_cases = [
                str(item.get("id", ""))
                for item in skills_payload.get("recommended_skills", [])
                if isinstance(item, dict) and item.get("id")
            ][:3]

        recommended_agent_roles = self._recommend_roles(
            primary_use_cases=primary_use_cases,
            memory_summary=memory_summary,
            notes_summary=notes_summary,
        )

        explicit_adoption_only = str(profile_payload.get("defaults", {}).get("adoption", "")) == "explicit_only"
        require_tests = bool(safety_meta.get("require_tests_before_adoption", False))
        preserve_source_artifacts = bool(safety_meta.get("preserve_source_artifacts", True))

        active_agents = [
            str(item)
            for item in existing_profile.get("active_agents", [])
            if item in recommended_agent_roles or isinstance(item, str)
        ]
        active_agents = _dedupe(active_agents or recommended_agent_roles)

        harness_id = str(existing_profile.get("harness_id", "")) or f"harness-{root.name}"

        return HarnessProfile(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            harness_id=harness_id,
            project_name=str(project_meta.get("name")) if project_meta.get("name") is not None else None,
            project_type=str(project_meta.get("type")) if project_meta.get("type") is not None else None,
            root=str(root),
            stack=[str(item) for item in project_meta.get("stack", []) if item],
            test_command=str(test_meta.get("command")) if test_meta.get("command") is not None else None,
            protect_paths=[str(item) for item in workspace_meta.get("protect_paths", []) if item],
            mode=str(profile_payload.get("mode")) if profile_payload.get("mode") is not None else None,
            primary_use_cases=primary_use_cases,
            safety={
                "explicit_adoption_only": explicit_adoption_only,
                "require_tests_before_apply": require_tests,
                "preserve_source_artifacts": preserve_source_artifacts,
                "source_mutation_policy": _DEFAULT_SAFETY_POLICY,
            },
            memory_summary=memory_summary,
            notes_summary=notes_summary,
            active_agents=active_agents,
            recommended_agent_roles=recommended_agent_roles,
            source_refs={
                "project.yaml": _relative(cambrian_dir / "project.yaml", root),
                "rules.yaml": _relative(cambrian_dir / "rules.yaml", root),
                "skills.yaml": _relative(cambrian_dir / "skills.yaml", root),
                "profile.yaml": _relative(cambrian_dir / "profile.yaml", root),
                "lessons.yaml": _relative(default_memory_path(root), root),
                "overrides.yaml": _relative(root / ".cambrian" / "memory" / "overrides.yaml", root),
                "hygiene.yaml": _relative(default_memory_hygiene_path(root), root),
            },
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    @staticmethod
    def _build_memory_summary(project_root: Path, warnings: list[str]) -> dict:
        """현재 메모리 상태를 요약한다."""
        memory = load_project_memory(project_root)
        hygiene = load_memory_hygiene(project_root)
        if memory is None:
            return {
                "lessons_count": 0,
                "pinned_count": 0,
                "suppressed_count": 0,
                "hygiene_summary": {
                    "checked": bool(hygiene is not None),
                    "needs_review": int(getattr(hygiene, "summary", {}).get("needs_review", 0) if hygiene else 0),
                    "stale": int(getattr(hygiene, "summary", {}).get("stale", 0) if hygiene else 0),
                    "conflicting": int(getattr(hygiene, "summary", {}).get("conflicting", 0) if hygiene else 0),
                },
            }
        pinned_count = sum(1 for item in memory.lessons if item.pinned)
        suppressed_count = sum(1 for item in memory.lessons if item.suppressed)
        hygiene_summary = {
            "checked": bool(hygiene is not None),
            "needs_review": int(getattr(hygiene, "summary", {}).get("needs_review", 0) if hygiene else 0),
            "stale": int(getattr(hygiene, "summary", {}).get("stale", 0) if hygiene else 0),
            "conflicting": int(getattr(hygiene, "summary", {}).get("conflicting", 0) if hygiene else 0),
        }
        return {
            "lessons_count": len(memory.lessons),
            "pinned_count": pinned_count,
            "suppressed_count": suppressed_count,
            "lesson_kinds": _dedupe([lesson.kind for lesson in memory.lessons if lesson.kind]),
            "top_tags": _dedupe([tag for lesson in memory.lessons for tag in lesson.tags])[:10],
            "hygiene_summary": hygiene_summary,
        }

    @staticmethod
    def _build_notes_summary(project_root: Path, warnings: list[str]) -> dict:
        """현재 notes 상태를 요약한다."""
        try:
            notes = ProjectNotesStore().list(default_notes_dir(project_root))
        except Exception as exc:
            message = f"notes summary build failed: {exc}"
            logger.warning(message)
            warnings.append(message)
            return {"open_count": 0, "high_open_count": 0}
        open_notes = [note for note in notes if note.status == "open"]
        high_open_notes = [note for note in open_notes if note.severity == "high"]
        return {
            "open_count": len(open_notes),
            "high_open_count": len(high_open_notes),
        }

    @staticmethod
    def _recommend_roles(
        *,
        primary_use_cases: list[str],
        memory_summary: dict,
        notes_summary: dict,
    ) -> list[str]:
        """현재 하네스에 맞는 기본 에이전트 역할을 계산한다."""
        roles: list[str] = []
        lowered = {item.lower() for item in primary_use_cases}
        if any(item in lowered for item in {"bug_fix", "bug-fix", "bugfix"}):
            roles.extend(["bug-fix-agent", "regression-test-agent", "review-agent"])
        if any(item in lowered for item in {"small_refactor", "small-refactor", "refactor"}):
            roles.extend(["small-refactor-agent", "review-agent"])
        if any(item in lowered for item in {"docs_update", "docs-update", "docs"}):
            roles.extend(["docs-update-agent", "review-agent"])
        if not roles:
            roles.extend(["context-scan-agent", "diagnose-agent", "review-agent"])

        lesson_kinds = {str(item).lower() for item in memory_summary.get("lesson_kinds", [])}
        top_tags = {str(item).lower() for item in memory_summary.get("top_tags", [])}
        if (
            "test_practice" in lesson_kinds
            or "pytest" in top_tags
            or "test" in top_tags
            or int(memory_summary.get("pinned_count", 0) or 0) > 0
        ):
            roles.append("regression-test-agent")
        hygiene = memory_summary.get("hygiene_summary", {})
        if (
            int(notes_summary.get("high_open_count", 0) or 0) > 0
            or int(hygiene.get("needs_review", 0) or 0) > 0
            or int(hygiene.get("conflicting", 0) or 0) > 0
        ):
            roles.append("review-agent")
        roles.extend(["patch-proposal-agent", "patch-validation-agent"])
        return _dedupe(roles)


def render_harness_profile(profile: HarnessProfile) -> str:
    """하네스 프로필을 사람용 텍스트로 렌더링한다."""
    lines = [
        "Cambrian Harness",
        "==================================================",
        "",
        "Project:",
        f"  name : {profile.project_name or '(unknown)'}",
        f"  type : {profile.project_type or '(unknown)'}",
        f"  root : {profile.root}",
        "",
        "Harness:",
        f"  mode       : {profile.mode or 'balanced'}",
        f"  stack      : {', '.join(profile.stack) or 'none yet'}",
        f"  test cmd   : {profile.test_command or 'none yet'}",
        f"  protect    : {', '.join(profile.protect_paths) or 'none'}",
        f"  use cases  : {', '.join(profile.primary_use_cases) or 'none yet'}",
        "",
        "Active agents:",
    ]
    if profile.active_agents:
        for agent_id in profile.active_agents:
            lines.append(f"  - {agent_id}")
    else:
        lines.append("  - none")
    lines.extend(["", "Recommended roles:"])
    if profile.recommended_agent_roles:
        for agent_id in profile.recommended_agent_roles:
            lines.append(f"  - {agent_id}")
    else:
        lines.append("  - none")
    return "\n".join(lines)


def render_harness_doctor(result: dict) -> str:
    """하네스 doctor 결과를 사람용 텍스트로 렌더링한다."""
    lines = [
        "Harness Doctor",
        "==================================================",
        "",
        "Harness:",
        f"  {'present' if result.get('present', False) else 'missing'}",
        "",
        "Profile sources:",
    ]
    for item in result.get("sources", []):
        lines.append(f"  {item}")
    lines.extend(
        [
            "",
            "Agents:",
            f"  {result.get('equipped_count', 0)} equipped",
            f"  {result.get('missing_agents', 0)} missing",
            f"  {result.get('imported_count', 0)} imported",
            f"  {result.get('blocked_compatibility_equipped', 0)} blocked compatibility",
            f"  {result.get('passport_histories_present', 0)} passport histories present",
            f"  dispatch log : {'present' if result.get('dispatch_log_present', False) else 'missing'}",
            "",
            "Status:",
            f"  {result.get('status', 'unknown')}",
        ]
    )
    warnings = [str(item) for item in result.get("warnings", []) if item]
    if warnings:
        lines.extend(["", "Warnings:"])
        for item in warnings:
            lines.append(f"  - {item}")
    return "\n".join(lines)
