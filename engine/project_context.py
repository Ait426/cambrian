"""Cambrian 프로젝트 문맥 스캐너."""

from __future__ import annotations

import logging
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_memory_context import MemoryContextAdvisor
from engine.project_next import NextCommandBuilder

logger = logging.getLogger(__name__)


TEXT_FILE_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".txt",
)
CODE_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
)
DEFAULT_IGNORED_DIRS: set[str] = {
    ".git",
    ".cambrian",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
}
STOP_WORDS: set[str] = {
    "fix",
    "please",
    "좀",
    "해",
    "해줘",
    "수정해",
    "수정",
    "만들어",
    "봐줘",
    "the",
    "and",
    "for",
}
SYNONYMS: dict[str, tuple[str, ...]] = {
    "login": ("auth", "signin", "session"),
    "로그인": ("login", "auth", "signin", "session"),
    "에러": ("error", "exception", "fail", "failure"),
    "오류": ("error", "exception", "fail", "failure"),
    "error": ("fail", "failure", "exception"),
    "test": ("pytest", "spec", "테스트"),
    "테스트": ("test", "pytest", "spec"),
    "api": ("router", "endpoint", "controller"),
    "auth": ("login", "signin", "session"),
}
CONFIG_FILES: set[str] = {
    "pyproject.toml",
    "pytest.ini",
    "package.json",
    "tsconfig.json",
    "dockerfile",
    ".env.example",
}
MAX_CONTENT_SCAN_BYTES = 1_048_576
DEFAULT_LIMIT = 10


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _new_request_id() -> str:
    """문맥 스캔용 요청 식별자를 만든다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"req-{stamp}-{secrets.token_hex(2)}"


def _atomic_write_yaml(path: Path, payload: dict) -> None:
    """YAML 파일을 원자적으로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 문자열 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _clamp_score(value: float) -> float:
    """점수를 0~1 범위로 고정한다."""
    return max(0.0, min(1.0, round(value, 2)))


def _is_binary_blob(payload: bytes) -> bool:
    """바이너리 파일 여부를 가볍게 판별한다."""
    return b"\x00" in payload


def _candidate_from_dict(payload: dict) -> "ContextCandidate":
    """dict 후보를 ContextCandidate로 복원한다."""
    return ContextCandidate(
        path=str(payload.get("path", "")),
        kind=str(payload.get("kind", "unknown")),
        score=float(payload.get("score", 0.0) or 0.0),
        reasons=[str(item) for item in payload.get("reasons", []) if item],
        matched_terms=[str(item) for item in payload.get("matched_terms", []) if item],
    )


@dataclass
class ContextCandidate:
    """문맥 후보 하나."""

    path: str
    kind: str
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict를 반환한다."""
        payload = asdict(self)
        payload["why"] = "; ".join(self.reasons)
        return payload


@dataclass
class ContextScanResult:
    """문맥 스캔 결과."""

    request_id: str
    user_request: str
    project_root: str
    created_at: str
    status: str
    query_terms: list[str]
    suggested_sources: list[ContextCandidate] = field(default_factory=list)
    suggested_tests: list[ContextCandidate] = field(default_factory=list)
    suggested_configs: list[ContextCandidate] = field(default_factory=list)
    memory_guidance: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    next_commands: list[dict] = field(default_factory=list)
    schema_version: str = "1.0.0"

    @property
    def context_id(self) -> str:
        """호환성을 위한 context_id."""
        return f"context-{self.request_id}"

    @property
    def top_source(self) -> str | None:
        """가장 점수가 높은 source 후보."""
        return self.suggested_sources[0].path if self.suggested_sources else None

    @property
    def top_test(self) -> str | None:
        """가장 점수가 높은 test 후보."""
        return self.suggested_tests[0].path if self.suggested_tests else None

    def to_dict(self) -> dict:
        """YAML/JSON 저장용 dict를 반환한다."""
        source_candidates = [item.to_dict() for item in self.suggested_sources]
        test_candidates = [item.to_dict() for item in self.suggested_tests]
        config_candidates = [item.to_dict() for item in self.suggested_configs]
        return {
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "request_id": self.request_id,
            "created_at": self.created_at,
            "user_request": self.user_request,
            "project_root": self.project_root,
            "status": self.status,
            "query_terms": list(self.query_terms),
            "suggested_sources": source_candidates,
            "suggested_tests": test_candidates,
            "suggested_configs": config_candidates,
            "source_candidates": source_candidates,
            "test_candidates": test_candidates,
            "config_candidates": config_candidates,
            "memory_guidance": dict(self.memory_guidance),
            "top_source": self.top_source,
            "top_test": self.top_test,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "next_actions": list(self.next_actions),
            "next_commands": list(self.next_commands),
        }


class ProjectContextScanner:
    """프로젝트 내부에서 관련 source/test/config 후보를 추천한다."""

    def scan(
        self,
        user_request: str | Path,
        project_root: Path | str | None = None,
        request_id: str | None = None,
        project_config: dict | None = None,
        rules: dict | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> ContextScanResult:
        """요청에 맞는 문맥 후보를 스캔한다."""
        effective_request = user_request
        effective_root = project_root
        if project_root is None:
            raise ValueError("project_root가 필요합니다.")
        if isinstance(user_request, Path):
            effective_root = user_request
            effective_request = project_root
        root = Path(effective_root).resolve()
        effective_limit = max(1, int(limit))
        query_terms = self._extract_query_terms(str(effective_request))
        protected_paths = self._protected_paths(rules)
        warnings: list[str] = []
        errors: list[str] = []
        large_skips = 0

        all_tests: list[ContextCandidate] = []
        source_candidates: list[ContextCandidate] = []
        config_candidates: list[ContextCandidate] = []

        for candidate in root.rglob("*"):
            if not candidate.is_file():
                continue
            if self._is_ignored(candidate, root, protected_paths):
                continue
            if candidate.suffix.lower() not in TEXT_FILE_SUFFIXES and candidate.name.lower() not in CONFIG_FILES:
                continue

            try:
                relative = self._relative_path(candidate, root)
                kind = self._classify_path(relative)
                score, reasons, matched_terms, skipped_large = self._score_candidate(
                    candidate=candidate,
                    relative_path=relative,
                    query_terms=query_terms,
                )
            except OSError as exc:
                message = f"문맥 스캔 중 파일 접근 실패: {candidate} ({exc})"
                logger.warning(message)
                warnings.append(message)
                continue

            if skipped_large:
                large_skips += 1
            if score <= 0:
                continue

            entry = ContextCandidate(
                path=relative,
                kind=kind,
                score=score,
                reasons=_dedupe(reasons),
                matched_terms=_dedupe(matched_terms),
            )
            if kind == "test":
                all_tests.append(entry)
            elif kind == "config":
                config_candidates.append(entry)
            elif kind == "source":
                source_candidates.append(entry)

        self._annotate_related_tests(source_candidates, all_tests)

        source_candidates = self._sort_and_limit(source_candidates, effective_limit)
        suggested_tests = self._sort_and_limit(all_tests, effective_limit)
        suggested_configs = self._sort_and_limit(
            self._boost_config_candidates(config_candidates, query_terms, project_config),
            effective_limit,
        )

        if large_skips > 0:
            warnings.append(f"큰 파일 {large_skips}개는 내용 스캔을 생략했습니다.")

        status = "success"
        if not source_candidates and not suggested_tests and not suggested_configs:
            status = "no_match"

        next_actions = self._build_next_actions(
            user_request=str(effective_request),
            status=status,
            top_source=source_candidates[0].path if source_candidates else None,
            top_test=suggested_tests[0].path if suggested_tests else None,
        )

        result = ContextScanResult(
            request_id=request_id or _new_request_id(),
            user_request=str(effective_request),
            project_root=str(root),
            created_at=_now(),
            status=status,
            query_terms=query_terms,
            suggested_sources=source_candidates,
            suggested_tests=suggested_tests,
            suggested_configs=suggested_configs,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
            next_actions=next_actions,
        )
        guidance = MemoryContextAdvisor().build_guidance(
            user_request=str(effective_request),
            context_scan_result=result.to_dict(),
            project_root=root,
        )
        adjusted = MemoryContextAdvisor().apply_to_context_candidates(
            result.to_dict(),
            guidance,
        )
        result.suggested_sources = [
            _candidate_from_dict(item)
            for item in adjusted.get("suggested_sources", [])
            if isinstance(item, dict)
        ]
        result.suggested_tests = [
            _candidate_from_dict(item)
            for item in adjusted.get("suggested_tests", [])
            if isinstance(item, dict)
        ]
        result.memory_guidance = dict(adjusted.get("memory_guidance", {}))
        result.warnings = [str(item) for item in adjusted.get("warnings", []) if item]
        result.next_actions = [str(item) for item in adjusted.get("next_actions", []) if item]
        result.next_commands = NextCommandBuilder.from_actions(
            list(result.next_actions),
            stage=result.status,
        )
        return result

    def save(self, result: ContextScanResult, path: Path | str) -> Path:
        """문맥 스캔 결과를 YAML로 저장한다."""
        file_path = Path(path)
        _atomic_write_yaml(file_path, result.to_dict())
        return file_path

    def load(self, path: Path | str) -> dict:
        """저장된 문맥 스캔 결과를 읽는다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("context artifact 최상위는 dict여야 합니다.")
        return payload

    @staticmethod
    def _protected_paths(rules: dict | None) -> set[str]:
        """rules.yaml에서 보호 경로를 읽는다."""
        protected = set(DEFAULT_IGNORED_DIRS)
        if not isinstance(rules, dict):
            return protected
        workspace = rules.get("workspace", {})
        if not isinstance(workspace, dict):
            return protected
        for item in workspace.get("protect_paths", []):
            if isinstance(item, str) and item:
                protected.add(item.replace("\\", "/").strip("/"))
        return protected

    @staticmethod
    def _extract_query_terms(user_request: str) -> list[str]:
        """요청에서 검색용 토큰을 추출하고 동의어를 확장한다."""
        base_terms = []
        for token in re.findall(r"[A-Za-z0-9_./-]+|[가-힣]+", user_request):
            normalized = token.strip().lower()
            if not normalized:
                continue
            if len(normalized) < 2:
                continue
            if normalized in STOP_WORDS:
                continue
            base_terms.append(normalized)
        expanded = list(base_terms)
        for term in list(base_terms):
            expanded.extend(SYNONYMS.get(term, ()))
        return _dedupe(expanded)

    def _is_ignored(self, path: Path, root: Path, protected_paths: set[str]) -> bool:
        """보호 경로와 캐시 디렉토리를 제외한다."""
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            return True
        parts = [part.replace("\\", "/") for part in relative.parts]
        lowered_parts = [part.lower() for part in parts]
        for protected in protected_paths:
            token = protected.replace("\\", "/").strip("/").lower()
            if not token:
                continue
            token_parts = token.split("/")
            if len(token_parts) == 1:
                if token_parts[0] in lowered_parts:
                    return True
            else:
                relative_text = "/".join(lowered_parts)
                if relative_text.startswith(token) or f"/{token}/" in f"/{relative_text}/":
                    return True
        return False

    @staticmethod
    def _classify_path(relative_path: str) -> str:
        """파일 종류를 source/test/config/docs/unknown으로 구분한다."""
        normalized = relative_path.replace("\\", "/")
        lowered = normalized.lower()
        name = Path(lowered).name
        if (
            "/tests/" in f"/{lowered}"
            or name.startswith("test_")
            or name.endswith("_test.py")
            or "__tests__" in lowered
            or name.endswith(".spec.ts")
            or name.endswith(".spec.js")
        ):
            return "test"
        if (
            name in CONFIG_FILES
            or lowered.startswith("pytest.")
            or lowered.endswith(".config.js")
            or lowered.endswith(".config.ts")
            or lowered.endswith(".config.cjs")
        ):
            return "config"
        if lowered.endswith(".md") or "/docs/" in f"/{lowered}":
            return "docs"
        if Path(lowered).suffix in CODE_SUFFIXES:
            return "source"
        return "unknown"

    def _score_candidate(
        self,
        *,
        candidate: Path,
        relative_path: str,
        query_terms: list[str],
    ) -> tuple[float, list[str], list[str], bool]:
        """단순 휴리스틱으로 후보 점수와 근거를 계산한다."""
        lowered_path = relative_path.lower()
        filename = Path(lowered_path).name
        directories = "/".join(Path(lowered_path).parts[:-1])
        score = 0.0
        reasons: list[str] = []
        matched_terms: list[str] = []
        skipped_large = False

        for term in query_terms:
            if term in filename:
                score += 0.30
                reasons.append(f"filename matched term: {term}")
                matched_terms.append(term)
            elif term in lowered_path:
                score += 0.35
                reasons.append(f"path matched term: {term}")
                matched_terms.append(term)
            if directories and term in directories:
                score += 0.20
                reasons.append(f"directory matched term: {term}")
                matched_terms.append(term)

        file_size = candidate.stat().st_size
        if file_size > MAX_CONTENT_SCAN_BYTES:
            skipped_large = True
        else:
            raw = candidate.read_bytes()
            if not _is_binary_blob(raw):
                try:
                    content = raw.decode("utf-8", errors="ignore").lower()
                except OSError as exc:
                    logger.warning("파일 내용 디코드 실패: %s (%s)", candidate, exc)
                else:
                    matched_in_content: list[str] = []
                    for term in query_terms:
                        if term in content:
                            matched_in_content.append(term)
                    for term in _dedupe(matched_in_content)[:3]:
                        score += 0.15
                        reasons.append(f"content matched term: {term}")
                        matched_terms.append(term)

        kind = self._classify_path(relative_path)
        if score > 0 and kind == "source" and lowered_path.startswith("src/"):
            score += 0.05
            reasons.append("source path heuristic")
        if score > 0 and kind == "test":
            score += 0.05
            reasons.append("test file pattern matched")

        return _clamp_score(score), _dedupe(reasons), _dedupe(matched_terms), skipped_large

    def _annotate_related_tests(
        self,
        source_candidates: list[ContextCandidate],
        test_candidates: list[ContextCandidate],
    ) -> None:
        """source 후보에 연관 테스트를 찾아 점수와 이유를 보강한다."""
        if not source_candidates or not test_candidates:
            return
        for source in source_candidates:
            related = self._find_related_tests(source.path, test_candidates)
            if not related:
                continue
            source.score = _clamp_score(source.score + 0.20)
            source.reasons = _dedupe([
                *source.reasons,
                f"related test file found: {related[0].path}",
            ])

    @staticmethod
    def _find_related_tests(
        source_path: str,
        test_candidates: list[ContextCandidate],
    ) -> list[ContextCandidate]:
        """source 경로와 이름이 비슷한 test 후보를 찾는다."""
        source_name = Path(source_path).stem.lower()
        source_parts = [part.lower() for part in Path(source_path).parts]
        basename = source_name.replace("test_", "")
        related: list[ContextCandidate] = []
        for candidate in test_candidates:
            test_name = Path(candidate.path).stem.lower().replace("test_", "")
            test_parts = [part.lower() for part in Path(candidate.path).parts]
            if test_name == basename:
                related.append(candidate)
                continue
            if basename and basename in candidate.path.lower():
                related.append(candidate)
                continue
            if any(
                part in candidate.path.lower()
                for part in source_parts
                if part not in {"src", "tests", "test"}
            ):
                related.append(candidate)
                continue
            if any(
                part in "/".join(test_parts)
                for part in source_parts
                if part not in {"src", "tests", "test"}
            ):
                related.append(candidate)
        unique: dict[str, ContextCandidate] = {}
        for item in related:
            unique[item.path] = item
        return list(unique.values())

    @staticmethod
    def _boost_config_candidates(
        config_candidates: list[ContextCandidate],
        query_terms: list[str],
        project_config: dict | None,
    ) -> list[ContextCandidate]:
        """테스트 관련 요청이면 config 후보 점수를 약간 높인다."""
        boosted = list(config_candidates)
        wants_test = any(term in {"test", "tests", "pytest", "테스트"} for term in query_terms)
        if not wants_test:
            return boosted
        for candidate in boosted:
            if Path(candidate.path).name.lower() in {"pytest.ini", "pyproject.toml"}:
                candidate.score = _clamp_score(candidate.score + 0.20)
                candidate.reasons = _dedupe([
                    *candidate.reasons,
                    "config relevant to test request",
                ])
        return boosted

    @staticmethod
    def _sort_and_limit(
        candidates: list[ContextCandidate],
        limit: int,
    ) -> list[ContextCandidate]:
        """점수와 경로로 정렬 후 제한 개수만 남긴다."""
        ordered = sorted(candidates, key=lambda item: (-item.score, item.path))
        return ordered[:limit]

    @staticmethod
    def _relative_path(path: Path, root: Path) -> str:
        """프로젝트 기준 상대 경로를 문자열로 반환한다."""
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")

    @staticmethod
    def _build_next_actions(
        *,
        user_request: str,
        status: str,
        top_source: str | None,
        top_test: str | None,
    ) -> list[str]:
        """문맥 스캔 다음 행동을 만든다."""
        if status == "no_match":
            return [
                "Try a more specific request",
                "Add --target manually",
                "Run cambrian status to check project setup",
            ]
        actions: list[str] = []
        if top_source and top_test:
            actions.append(
                f'Run cambrian run "{user_request}" --target {top_source} --test {top_test}'
            )
        elif top_source:
            actions.append(
                f'Run cambrian run "{user_request}" --target {top_source}'
            )
        elif top_test:
            actions.append(
                f'Run cambrian run "{user_request}" --test {top_test}'
            )
        actions.append("Review the suggested files before execution")
        return _dedupe(actions)


def render_context_scan_summary(
    result: ContextScanResult | dict,
    *,
    artifact_path: str | None = None,
) -> str:
    """context scan 결과를 사람이 읽기 쉽게 렌더링한다."""
    from engine.project_errors import hint_for_context_scan, render_recovery_hint

    payload = result.to_dict() if isinstance(result, ContextScanResult) else result
    recovery_hint = hint_for_context_scan(payload)
    if recovery_hint is not None:
        return render_recovery_hint(recovery_hint)
    request = str(payload.get("user_request", ""))
    status = str(payload.get("status", "error"))
    sources = list(payload.get("suggested_sources", []))
    tests = list(payload.get("suggested_tests", []))
    memory_guidance = payload.get("memory_guidance", {}) if isinstance(payload.get("memory_guidance"), dict) else {}
    remembered = [
        str(item.get("text"))
        for item in memory_guidance.get("relevant_lessons", [])
        if isinstance(item, dict) and item.get("text")
    ]
    lines = [
        "Cambrian scanned project context.",
        "",
        "Request:",
        f"  {request}",
        "",
    ]
    if remembered:
        lines.extend(["Remembered:"])
        for item in remembered[:3]:
            lines.append(f"  - {item}")
        lines.append("")
    elif memory_guidance.get("enabled") is False:
        lines.extend(["Project memory:", "  no relevant lessons yet", ""])
    if status == "no_match":
        lines.extend([
            "No confident files found.",
            "",
            "Next:",
        ])
        for action in payload.get("next_actions", []):
            lines.append(f"  - {action}")
        if artifact_path:
            lines.extend(["", "Created:", f"  {artifact_path}"])
        return "\n".join(lines)

    lines.append("Suggested source files:")
    if sources:
        for index, item in enumerate(sources[:3], start=1):
            lines.append(
                f"  {index}. {item.get('path')}  score={item.get('score')}"
            )
            lines.append(f"     why: {item.get('why') or 'matched request terms'}")
    else:
        lines.append("  none")
    lines.extend(["", "Suggested tests:"])
    if tests:
        for index, item in enumerate(tests[:3], start=1):
            lines.append(
                f"  {index}. {item.get('path')}  score={item.get('score')}"
            )
            lines.append(f"     why: {item.get('why') or 'matched request terms'}")
    else:
        lines.append("  none")
    if memory_guidance.get("warnings"):
        lines.extend(["", "Warnings:"])
        for item in memory_guidance.get("warnings", [])[:3]:
            lines.append(f"  - {item}")
    if artifact_path:
        lines.extend(["", "Created:", f"  {artifact_path}"])
    lines.extend(["", "Next:"])
    for action in payload.get("next_actions", []):
        lines.append(f"  - {action}")
    return "\n".join(lines)
