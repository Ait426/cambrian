"""Cambrian guided patch intent form 도우미."""

from __future__ import annotations

import json
import logging
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_next import NextCommandBuilder
from engine.project_memory_patch import MemoryPatchIntentAdvisor

logger = logging.getLogger(__name__)


PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    ".git",
    ".cambrian",
    "__pycache__",
    ".pytest_cache",
)
MAX_INTENT_FILE_BYTES = 1_048_576


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _intent_id() -> str:
    """patch intent 식별자를 만든다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"pintent-{stamp}-{secrets.token_hex(2)}"


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


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _project_root_from_artifact(path: Path) -> Path:
    """artifact 경로에서 프로젝트 루트를 추출한다."""
    resolved = path.resolve()
    for parent in resolved.parents:
        if parent.name == ".cambrian":
            return parent.parent
    return resolved.parent


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _is_binary(path: Path) -> bool:
    """바이너리 파일 여부를 가볍게 판별한다."""
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" in sample


def _load_rules(project_root: Path) -> dict:
    """프로젝트 규칙 파일을 읽는다."""
    rules_path = project_root / ".cambrian" / "rules.yaml"
    if not rules_path.exists():
        return {}
    try:
        payload = _load_yaml(rules_path)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.warning("rules.yaml 로드 실패: %s", exc)
        return {}
    return payload


def _validate_target_path(
    target_path: str,
    project_root: Path,
    rules: dict | None = None,
) -> Path | None:
    """대상 파일 경로 안전성을 검증한다."""
    if not target_path:
        return None
    path = Path(target_path)
    if path.is_absolute() or ".." in path.parts:
        return None
    normalized = target_path.replace("\\", "/")
    protected = set(PROTECTED_PATH_PREFIXES)
    if isinstance(rules, dict):
        workspace = rules.get("workspace", {})
        if isinstance(workspace, dict):
            for item in workspace.get("protect_paths", []):
                if isinstance(item, str) and item:
                    protected.add(item.replace("\\", "/").strip("/"))
    for prefix in protected:
        if normalized == prefix or normalized.startswith(f"{prefix}/"):
            return None
    candidate = (project_root / path).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        return None
    return candidate


def _extract_tokens(text: str) -> list[str]:
    """요청/테스트 요약에서 단순 토큰을 추출한다."""
    if not text:
        return []
    tokens = [
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣_]+", text)
        if len(token) >= 2
    ]
    stop_words = {"the", "and", "for", "with", "that", "this", "true", "false", "test", "tests"}
    return _dedupe([token for token in tokens if token not in stop_words])


@dataclass
class OldTextCandidate:
    """사용자가 고를 수 있는 old_text 후보."""

    id: str
    text: str
    source_path: str
    line_start: int | None
    line_end: int | None
    reason: str
    confidence: float
    memory_boosted: bool = False
    memory_reasons: list[str] = field(default_factory=list)
    memory_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class PatchIntentForm:
    """patch proposal 전 단계의 사용자 입력 폼."""

    schema_version: str
    intent_id: str
    created_at: str
    status: str
    user_request: str | None
    source_diagnosis_ref: str
    source_context_ref: str | None
    target_path: str | None
    related_tests: list[str]
    inspected_files: list[dict]
    test_summary: dict | None
    old_text_candidates: list[OldTextCandidate]
    selected_old_text: str | None
    selected_old_choice: str | None
    new_text: str | None
    proposal_path: str | None
    warnings: list[str]
    errors: list[str]
    next_actions: list[str]
    next_commands: list[dict] = field(default_factory=list)
    memory_guidance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["old_text_candidates"] = [
            candidate.to_dict() for candidate in self.old_text_candidates
        ]
        return payload


class PatchIntentStore:
    """Patch intent artifact 저장소."""

    def save(self, form: PatchIntentForm, out_path: Path | None = None) -> Path:
        """intent form을 YAML로 저장한다."""
        if out_path is None:
            raise ValueError("intent 저장 경로가 필요합니다.")
        form.next_commands = NextCommandBuilder.from_actions(
            list(form.next_actions),
            stage=str(form.status),
        )
        _dump_yaml(out_path, form.to_dict())
        return out_path

    def load(self, path: Path) -> PatchIntentForm:
        """intent form을 로드한다."""
        payload = _load_yaml(path)
        candidates = [
            OldTextCandidate(
                id=str(item.get("id", "")),
                text=str(item.get("text", "")),
                source_path=str(item.get("source_path", "")),
                line_start=item.get("line_start"),
                line_end=item.get("line_end"),
                reason=str(item.get("reason", "")),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                memory_boosted=bool(item.get("memory_boosted", False)),
                memory_reasons=[str(value) for value in item.get("memory_reasons", []) if value],
                memory_warnings=[str(value) for value in item.get("memory_warnings", []) if value],
            )
            for item in payload.get("old_text_candidates", [])
            if isinstance(item, dict)
        ]
        return PatchIntentForm(
            schema_version=str(payload.get("schema_version", "1.0.0")),
            intent_id=str(payload.get("intent_id", path.stem)),
            created_at=str(payload.get("created_at", "")),
            status=str(payload.get("status", "draft")),
            user_request=payload.get("user_request"),
            source_diagnosis_ref=str(payload.get("source_diagnosis_ref", "")),
            source_context_ref=payload.get("source_context_ref"),
            target_path=payload.get("target_path"),
            related_tests=list(payload.get("related_tests", [])),
            inspected_files=list(payload.get("inspected_files", [])),
            test_summary=dict(payload.get("test_summary", {}))
            if isinstance(payload.get("test_summary"), dict)
            else None,
            old_text_candidates=candidates,
            selected_old_text=payload.get("selected_old_text"),
            selected_old_choice=payload.get("selected_old_choice"),
            new_text=payload.get("new_text"),
            proposal_path=payload.get("proposal_path"),
            warnings=list(payload.get("warnings", [])),
            errors=list(payload.get("errors", [])),
            next_actions=list(payload.get("next_actions", [])),
            memory_guidance=dict(payload.get("memory_guidance", {}))
            if isinstance(payload.get("memory_guidance"), dict)
            else {},
        )


class PatchIntentBuilder:
    """diagnosis report에서 patch intent form을 만든다."""

    def __init__(self) -> None:
        self._memory_advisor = MemoryPatchIntentAdvisor()

    def build_from_diagnosis(
        self,
        diagnosis_report_path: Path,
        project_root: Path,
        target_path: str | None = None,
    ) -> PatchIntentForm:
        """diagnosis report를 기반으로 draft intent form을 생성한다."""
        root = Path(project_root).resolve()
        report_path = Path(diagnosis_report_path).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        rules = _load_rules(root)

        try:
            report = _load_json(report_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"diagnosis report 로드 실패: {exc}")
            return PatchIntentForm(
                schema_version="1.0.0",
                intent_id=_intent_id(),
                created_at=_now(),
                status="blocked",
                user_request=None,
                source_diagnosis_ref=str(report_path),
                source_context_ref=None,
                target_path=target_path,
                related_tests=[],
                inspected_files=[],
                test_summary=None,
                old_text_candidates=[],
                selected_old_text=None,
                selected_old_choice=None,
                new_text=None,
                proposal_path=None,
                warnings=warnings,
                errors=errors,
                next_actions=[
                    "diagnosis report 경로를 확인하고 다시 시도하세요.",
                ],
                memory_guidance={},
            )

        diagnostics = report.get("diagnostics", {})
        if not isinstance(diagnostics, dict):
            diagnostics = {}
            warnings.append("diagnostics 섹션이 없어 기본 정보만 사용합니다.")

        inspected_files = [
            dict(item)
            for item in diagnostics.get("inspected_files", [])
            if isinstance(item, dict)
        ]
        related_tests = self._extract_related_tests(report, diagnostics)
        test_summary = self._extract_test_summary(report, diagnostics)
        user_request = self._extract_user_request(report, diagnostics)
        context_ref = self._extract_context_ref(report, diagnostics)
        effective_target = target_path or self._extract_target_path(report, diagnostics)

        target_file: Path | None = None
        status = "draft"
        if not effective_target:
            status = "blocked"
            errors.append("diagnosis report에서 target file을 찾지 못했습니다.")
        else:
            target_file = _validate_target_path(effective_target, root, rules)
            if target_file is None:
                status = "blocked"
                errors.append(f"unsafe target path: {effective_target}")
            elif not target_file.exists():
                status = "blocked"
                errors.append(f"target file이 존재하지 않습니다: {effective_target}")
            elif target_file.stat().st_size > MAX_INTENT_FILE_BYTES:
                status = "blocked"
                errors.append(f"target file이 너무 큽니다: {effective_target}")
            elif _is_binary(target_file):
                status = "blocked"
                errors.append(f"binary file은 patch intent 대상이 아닙니다: {effective_target}")

        candidates: list[OldTextCandidate] = []
        memory_guidance: dict = {}
        if target_file is not None and status != "blocked":
            candidates = self._extract_old_text_candidates(
                target_file=target_file,
                target_path=effective_target or "",
                user_request=user_request,
                test_summary=test_summary,
            )
            guidance = self._memory_advisor.build_guidance(
                user_request=user_request,
                target_path=effective_target,
                related_tests=related_tests,
                old_text_candidates=[item.to_dict() for item in candidates],
                project_root=root,
            )
            memory_guidance = guidance.to_dict()
            guided_candidates = self._memory_advisor.apply_to_old_text_candidates(
                [item.to_dict() for item in candidates],
                guidance,
            )
            candidates = [
                OldTextCandidate(
                    id=str(item.get("id", "")),
                    text=str(item.get("text", "")),
                    source_path=str(item.get("source_path", "")),
                    line_start=item.get("line_start"),
                    line_end=item.get("line_end"),
                    reason=str(item.get("reason", "")),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    memory_boosted=bool(item.get("memory_boosted", False)),
                    memory_reasons=[str(value) for value in item.get("memory_reasons", []) if value],
                    memory_warnings=[str(value) for value in item.get("memory_warnings", []) if value],
                )
                for item in guided_candidates
            ]
            related_tests = _dedupe([*related_tests, *guidance.suggested_tests])
            warnings = _dedupe([*warnings, *guidance.warnings])
            if not candidates:
                warnings.append("추천할 old_text 후보를 찾지 못했습니다. --old-text 로 직접 지정하세요.")

        next_actions = self._build_next_actions(
            effective_target,
            candidates,
            status,
        )
        if memory_guidance:
            next_actions = _dedupe([
                *memory_guidance.get("next_actions", []),
                *next_actions,
            ])
        return PatchIntentForm(
            schema_version="1.0.0",
            intent_id=_intent_id(),
            created_at=_now(),
            status=status,
            user_request=user_request,
            source_diagnosis_ref=_relative(report_path, root),
            source_context_ref=context_ref,
            target_path=effective_target,
            related_tests=related_tests,
            inspected_files=inspected_files,
            test_summary=test_summary,
            old_text_candidates=candidates,
            selected_old_text=None,
            selected_old_choice=None,
            new_text=None,
            proposal_path=None,
            warnings=warnings,
            errors=errors,
            next_actions=next_actions,
            memory_guidance=memory_guidance,
        )

    @staticmethod
    def _extract_related_tests(report: dict, diagnostics: dict) -> list[str]:
        """diagnosis report에서 관련 테스트 목록을 추출한다."""
        collected: list[str] = []
        collected.extend(
            str(item) for item in diagnostics.get("related_tests", [])
            if isinstance(item, str)
        )
        provenance = report.get("provenance_handoff", {})
        if isinstance(provenance, dict):
            collected.extend(
                str(item) for item in provenance.get("tests_executed", [])
                if isinstance(item, str)
            )
        test_summary = diagnostics.get("test_results", {})
        if isinstance(test_summary, dict):
            collected.extend(
                str(item) for item in test_summary.get("tests_executed", [])
                if isinstance(item, str)
            )
        return _dedupe(collected)

    @staticmethod
    def _extract_test_summary(report: dict, diagnostics: dict) -> dict | None:
        """diagnosis report에서 테스트 요약을 뽑는다."""
        test_summary = diagnostics.get("test_results")
        if isinstance(test_summary, dict):
            return dict(test_summary)
        report_tests = report.get("test_results")
        if isinstance(report_tests, dict):
            return dict(report_tests)
        return None

    @staticmethod
    def _extract_user_request(report: dict, diagnostics: dict) -> str | None:
        """진단 리포트에서 원래 요청 문장을 추출한다."""
        for value in (
            report.get("user_request"),
            report.get("request"),
            diagnostics.get("user_request") if isinstance(diagnostics, dict) else None,
            report.get("goal"),
        ):
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_context_ref(report: dict, diagnostics: dict) -> str | None:
        """source context 참조를 추출한다."""
        for value in (
            report.get("source_context_ref"),
            diagnostics.get("source_context_scan") if isinstance(diagnostics, dict) else None,
            diagnostics.get("source_context_ref") if isinstance(diagnostics, dict) else None,
        ):
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _extract_target_path(report: dict, diagnostics: dict) -> str | None:
        """진단 리포트에서 기본 target path를 찾는다."""
        inspected_files = diagnostics.get("inspected_files", [])
        if isinstance(inspected_files, list):
            for item in inspected_files:
                if isinstance(item, dict):
                    path = item.get("path")
                    if isinstance(path, str) and path.strip():
                        return path.strip()
        provenance = report.get("provenance_handoff", {})
        if isinstance(provenance, dict):
            for key in ("files_modified", "files_created"):
                values = provenance.get(key, [])
                if isinstance(values, list):
                    for item in values:
                        if isinstance(item, str) and item.strip():
                            return item.strip()
        return None

    def _extract_old_text_candidates(
        self,
        *,
        target_file: Path,
        target_path: str,
        user_request: str | None,
        test_summary: dict | None,
    ) -> list[OldTextCandidate]:
        """target source에서 사람이 고를 old_text 후보를 추출한다."""
        text = target_file.read_text(encoding="utf-8")
        tokens = _extract_tokens(user_request or "")
        if isinstance(test_summary, dict):
            tokens = _dedupe([
                *tokens,
                *_extract_tokens(" ".join(str(item) for item in test_summary.get("tests_executed", []))),
            ])
        lines = text.splitlines()
        candidates: list[OldTextCandidate] = []
        seen_text: set[str] = set()

        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if stripped.startswith("def ") or stripped.startswith("class "):
                continue
            if stripped.startswith("import ") or stripped.startswith("from "):
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            if len(stripped) < 5 or len(stripped) > 160:
                continue
            if stripped in seen_text:
                continue

            score = 0.1
            reasons: list[str] = []
            lower_line = stripped.lower()
            if stripped.startswith("return "):
                score += 0.3
                reasons.append("짧은 return 문장")
            elif "=" in stripped and "==" not in stripped:
                score += 0.2
                reasons.append("짧은 대입 문장")
            else:
                reasons.append("짧은 코드 줄")
            if len(stripped) <= 40:
                score += 0.1
            matched_tokens = [token for token in tokens if token in lower_line]
            if matched_tokens:
                score += 0.3
                reasons.append("요청/테스트 토큰 일치")
            confidence = max(0.0, min(score, 1.0))
            candidates.append(
                OldTextCandidate(
                    id=f"old-{len(candidates) + 1}",
                    text=stripped,
                    source_path=target_path,
                    line_start=index,
                    line_end=index,
                    reason=", ".join(reasons),
                    confidence=round(confidence, 2),
                )
            )
            seen_text.add(stripped)

        candidates.sort(
            key=lambda item: (
                0 if item.text.startswith("return ") else 1,
                -item.confidence,
                item.line_start or 0,
            )
        )
        trimmed = candidates[:5]
        for index, candidate in enumerate(trimmed, start=1):
            candidate.id = f"old-{index}"
        return trimmed

    @staticmethod
    def _build_next_actions(
        target_path: str | None,
        candidates: list[OldTextCandidate],
        status: str,
    ) -> list[str]:
        """intent form의 다음 행동을 만든다."""
        if status == "blocked":
            return [
                "target 파일이나 diagnosis report를 확인한 뒤 다시 시도하세요.",
            ]
        if candidates:
            return [
                'Choose old text: cambrian patch intent-fill <intent> --old-choice old-1 --new-text "..."',
                "또는 --old-text 로 직접 old_text 를 지정하세요.",
            ]
        if target_path:
            return [
                'Provide old text directly: cambrian patch intent-fill <intent> --old-text "..." --new-text "..."',
            ]
        return [
            "diagnosis report에서 target 파일을 확인해 다시 시도하세요.",
        ]


class PatchIntentFiller:
    """patch intent form을 사용자의 입력으로 채운다."""

    def __init__(self) -> None:
        self._store = PatchIntentStore()

    def fill(
        self,
        intent_path: Path,
        old_choice: str | None = None,
        old_text: str | None = None,
        new_text: str | None = None,
        new_text_file: Path | None = None,
        old_text_file: Path | None = None,
    ) -> PatchIntentForm:
        """기존 intent form에 old/new text를 반영한다."""
        artifact_path = Path(intent_path).resolve()
        root = _project_root_from_artifact(artifact_path)
        form = self._store.load(artifact_path)
        form.errors = []
        warnings = list(form.warnings)

        old_inputs = [
            value is not None and value != ""
            for value in (old_choice, old_text, old_text_file)
        ]
        if sum(1 for item in old_inputs if item) > 1:
            form.status = "blocked"
            form.errors.append("old_choice, old_text, old_text_file 중 하나만 선택하세요.")
            form.next_actions = [
                "old_text 입력 방식을 하나만 남기고 다시 시도하세요.",
            ]
            self._store.save(form, artifact_path)
            return form

        new_inputs = [
            value is not None and value != ""
            for value in (new_text, new_text_file)
        ]
        if sum(1 for item in new_inputs if item) > 1:
            form.status = "blocked"
            form.errors.append("new_text 와 new_text_file 은 함께 사용할 수 없습니다.")
            form.next_actions = [
                "new_text 입력 방식을 하나만 남기고 다시 시도하세요.",
            ]
            self._store.save(form, artifact_path)
            return form

        resolved_old_text = form.selected_old_text
        resolved_old_choice = form.selected_old_choice
        if old_choice:
            candidate = next(
                (item for item in form.old_text_candidates if item.id == old_choice),
                None,
            )
            if candidate is None:
                form.status = "blocked"
                form.errors.append(f"unknown old_choice: {old_choice}")
                form.next_actions = [
                    "old_text 후보 ID를 확인하고 다시 선택하세요.",
                ]
                self._store.save(form, artifact_path)
                return form
            resolved_old_text = candidate.text
            resolved_old_choice = candidate.id
        elif old_text is not None:
            resolved_old_text = old_text
            resolved_old_choice = None
        elif old_text_file is not None:
            try:
                resolved_old_text = Path(old_text_file).read_text(encoding="utf-8")
            except OSError as exc:
                form.status = "blocked"
                form.errors.append(f"old_text_file 로드 실패: {exc}")
                form.next_actions = [
                    "old_text_file 경로를 확인하고 다시 시도하세요.",
                ]
                self._store.save(form, artifact_path)
                return form
            resolved_old_choice = None

        resolved_new_text = form.new_text
        if new_text is not None:
            resolved_new_text = new_text
        elif new_text_file is not None:
            try:
                resolved_new_text = Path(new_text_file).read_text(encoding="utf-8")
            except OSError as exc:
                form.status = "blocked"
                form.errors.append(f"new_text_file 로드 실패: {exc}")
                form.next_actions = [
                    "new_text_file 경로를 확인하고 다시 시도하세요.",
                ]
                self._store.save(form, artifact_path)
                return form

        form.selected_old_choice = resolved_old_choice
        form.selected_old_text = resolved_old_text
        form.new_text = resolved_new_text

        if not form.target_path:
            form.status = "blocked"
            form.errors.append("target_path 가 없습니다.")
            form.next_actions = [
                "intent를 다시 만들 때 --target 을 지정하세요.",
            ]
            self._store.save(form, artifact_path)
            return form

        target_file = _validate_target_path(
            form.target_path,
            root,
            _load_rules(root),
        )
        if target_file is None or not target_file.exists():
            form.status = "blocked"
            form.errors.append(f"unsafe or missing target path: {form.target_path}")
            form.next_actions = [
                "target 경로를 확인하고 intent를 다시 만드세요.",
            ]
            self._store.save(form, artifact_path)
            return form

        if target_file.stat().st_size > MAX_INTENT_FILE_BYTES or _is_binary(target_file):
            form.status = "blocked"
            form.errors.append(f"target file을 patch intent 로 다룰 수 없습니다: {form.target_path}")
            form.next_actions = [
                "더 작은 텍스트 파일에 대해서만 patch intent 를 사용하세요.",
            ]
            self._store.save(form, artifact_path)
            return form

        target_content = target_file.read_text(encoding="utf-8")
        if not form.selected_old_text:
            form.status = "draft"
            form.next_actions = [
                'old_text를 고르세요: cambrian patch intent-fill <intent> --old-choice old-1 --new-text "..."',
            ]
            form.warnings = _dedupe(warnings)
            self._store.save(form, artifact_path)
            return form

        if form.selected_old_text not in target_content:
            form.status = "blocked"
            form.errors.append(f"old_text was not found in {form.target_path}")
            form.next_actions = [
                "old_text 후보를 다시 고르거나 --old-text 로 정확한 구문을 지정하세요.",
            ]
            self._store.save(form, artifact_path)
            return form

        if form.new_text is None:
            form.status = "draft"
            form.next_actions = [
                'new_text를 채우세요: cambrian patch intent-fill <intent> --new-text "..."',
            ]
            form.warnings = _dedupe(warnings)
            self._store.save(form, artifact_path)
            return form

        form.status = "ready_for_proposal"
        form.warnings = _dedupe(warnings)
        if not form.related_tests:
            form.warnings = _dedupe([
                *form.warnings,
                "관련 테스트가 없어 proposal validation 이 inconclusive 가 될 수 있습니다.",
            ])
        form.next_actions = [
            "cambrian patch propose --from-intent <intent>",
            "또는 cambrian patch intent-fill <intent> --propose",
        ]
        self._store.save(form, artifact_path)
        return form


def render_patch_intent_summary(
    form: PatchIntentForm | dict,
    *,
    intent_path: str | None = None,
) -> str:
    """patch intent 결과를 사람이 읽기 좋게 렌더링한다."""
    from engine.project_errors import hint_for_patch_intent, render_recovery_hint

    payload = form.to_dict() if isinstance(form, PatchIntentForm) else dict(form)
    recovery_hint = hint_for_patch_intent(payload)
    if recovery_hint is not None:
        return render_recovery_hint(recovery_hint, title="Cambrian could not prepare this patch intent safely.")
    status = str(payload.get("status", "draft"))
    target_path = str(payload.get("target_path") or "none")
    related_tests = list(payload.get("related_tests", []))
    candidates = list(payload.get("old_text_candidates", []))
    memory_guidance = (
        dict(payload.get("memory_guidance", {}))
        if isinstance(payload.get("memory_guidance"), dict)
        else {}
    )
    remembered = list(memory_guidance.get("remembered", []))
    memory_warnings = list(memory_guidance.get("warnings", []))

    if status == "blocked":
        lines = [
            "Cambrian could not prepare this patch intent safely.",
            "",
            "Reason:",
        ]
        for item in payload.get("errors", []) or payload.get("warnings", []):
            lines.append(f"  - {item}")
        lines.extend(["", "Next:"])
        for action in payload.get("next_actions", []):
            lines.append(f"  - {action}")
        return "\n".join(lines)

    if status == "ready_for_proposal":
        lines = [
            "Cambrian captured your patch intent.",
            "",
            "Target:",
            f"  {target_path}",
            "",
            "Selected change:",
            f"  old text: {payload.get('selected_old_choice') or 'direct input'}",
            f"  new text: {'provided' if payload.get('new_text') else 'missing'}",
        ]
        selected_choice = str(payload.get("selected_old_choice") or "")
        selected_candidate = next(
            (item for item in candidates if str(item.get("id", "")) == selected_choice),
            None,
        )
        selected_memory_notes: list[str] = []
        if isinstance(selected_candidate, dict):
            selected_memory_notes.extend(
                str(item) for item in selected_candidate.get("memory_reasons", []) if item
            )
            selected_memory_notes.extend(
                str(item) for item in selected_candidate.get("memory_warnings", []) if item
            )
        if selected_memory_notes:
            lines.extend(["", "Memory note:"])
            for item in _dedupe(selected_memory_notes):
                lines.append(f"  - {item}")
        if payload.get("proposal_path"):
            lines.extend(["", "Created:", f"  proposal: {payload.get('proposal_path')}"])
        lines.extend(["", "Next:"])
        for action in payload.get("next_actions", []):
            lines.append(f"  - {action}")
        return "\n".join(lines)

    lines = [
        "Cambrian prepared a patch intent form.",
        "",
        "Diagnosis:",
        f"  {payload.get('source_diagnosis_ref')}",
        "",
        "Target:",
        f"  {target_path}",
        "",
        "Related tests:",
        f"  {', '.join(related_tests) if related_tests else 'none'}",
    ]
    if remembered:
        lines.extend(["", "Remembered:"])
        for item in remembered[:3]:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('text')}")
    lines.extend(["", "Possible old text:"])
    if candidates:
        for index, candidate in enumerate(candidates, start=1):
            lines.append(
                f"  {index}. line {candidate.get('line_start')}: {candidate.get('text')}"
            )
            lines.append(f"     why: {candidate.get('reason')}")
            for item in candidate.get("memory_reasons", []) or []:
                lines.append(f"     memory: {item}")
            for item in candidate.get("memory_warnings", []) or []:
                lines.append(f"     warning: {item}")
    else:
        lines.append("  none")
    if memory_warnings:
        lines.extend(["", "Warnings:"])
        for item in _dedupe([str(value) for value in memory_warnings if value]):
            lines.append(f"  - {item}")
    lines.extend(["", "Created:"])
    if intent_path:
        lines.append(f"  intent: {intent_path}")
    lines.extend(["", "Next:"])
    for action in payload.get("next_actions", []):
        lines.append(f"  {action}" if str(action).startswith("cambrian ") else f"  - {action}")
    return "\n".join(lines)
