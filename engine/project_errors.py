"""Cambrian recovery hint와 마지막 오류 artifact 도우미."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 만든다."""
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


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


@dataclass
class RecoveryCommand:
    """복구용 명령 한 개."""

    label: str
    command: str
    reason: str
    primary: bool = False

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class RecoveryHint:
    """사용자 친화적 blocked/fail/warn 안내."""

    error_id: str
    status: str
    severity: str
    stage: str | None
    problem: str
    why: str
    try_next: list[RecoveryCommand] = field(default_factory=list)
    related_artifacts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["try_next"] = [item.to_dict() for item in self.try_next]
        return payload


@dataclass
class RecoveryReport:
    """마지막 오류 저장용 report."""

    schema_version: str
    created_at: str
    hint: RecoveryHint

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "hint": self.hint.to_dict(),
        }


def default_last_error_path(project_root: Path) -> Path:
    """기본 last_error 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "errors" / "last_error.yaml"


class LastErrorStore:
    """마지막 오류 artifact 저장/로드."""

    def save(self, project_root: Path, hint: RecoveryHint) -> Path | None:
        """초기화된 프로젝트에만 last_error를 저장한다."""
        root = Path(project_root).resolve()
        if not (root / ".cambrian" / "project.yaml").exists():
            return None
        report = RecoveryReport(
            schema_version=SCHEMA_VERSION,
            created_at=_now(),
            hint=hint,
        )
        target = default_last_error_path(root)
        _atomic_write_text(
            target,
            yaml.safe_dump(report.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> RecoveryReport:
        """저장된 last_error를 읽는다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("last_error YAML 최상위는 dict여야 합니다.")
        hint_payload = payload.get("hint", {})
        if not isinstance(hint_payload, dict):
            hint_payload = {}
        commands_payload = hint_payload.get("try_next", [])
        commands: list[RecoveryCommand] = []
        for item in commands_payload if isinstance(commands_payload, list) else []:
            if not isinstance(item, dict):
                continue
            commands.append(
                RecoveryCommand(
                    label=str(item.get("label", "")),
                    command=str(item.get("command", "")),
                    reason=str(item.get("reason", "")),
                    primary=bool(item.get("primary", False)),
                )
            )
        hint = RecoveryHint(
            error_id=str(hint_payload.get("error_id", "unknown")),
            status=str(hint_payload.get("status", "blocked")),
            severity=str(hint_payload.get("severity", "warning")),
            stage=hint_payload.get("stage"),
            problem=str(hint_payload.get("problem", "")),
            why=str(hint_payload.get("why", "")),
            try_next=commands,
            related_artifacts=[
                str(item) for item in hint_payload.get("related_artifacts", []) if item
            ],
            warnings=[str(item) for item in hint_payload.get("warnings", []) if item],
            errors=[str(item) for item in hint_payload.get("errors", []) if item],
        )
        return RecoveryReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            created_at=str(payload.get("created_at", "")),
            hint=hint,
        )


def load_last_error(path: Path) -> RecoveryReport:
    """last_error artifact를 읽는다."""
    return LastErrorStore().load(path)


def save_last_error(project_root: Path, hint: RecoveryHint | None) -> Path | None:
    """best-effort로 last_error를 저장한다."""
    if hint is None:
        return None
    try:
        return LastErrorStore().save(project_root, hint)
    except OSError as exc:
        logger.warning("last_error 저장 실패: %s", exc)
        return None


def render_recovery_hint(
    hint: RecoveryHint,
    *,
    title: str | None = None,
) -> str:
    """Problem / Why / Try 형식으로 recovery hint를 렌더링한다."""
    heading = title
    if heading is None:
        if hint.status == "warn":
            heading = "Cambrian warning"
        elif hint.status == "fail":
            heading = "Cambrian could not finish safely."
        else:
            heading = "Cambrian could not continue safely."
    lines = [
        heading,
        "==================================================",
        "",
        "Problem:",
        f"  {hint.problem}",
        "",
        "Why:",
        f"  {hint.why}",
    ]
    if hint.try_next:
        lines.extend(["", "Try:"])
        for index, item in enumerate(hint.try_next, start=1):
            lines.append(f"  {index}. {item.command}")
            if item.reason:
                lines.append(f"     {item.reason}")
    if hint.related_artifacts:
        lines.extend(["", "Related:"])
        for item in hint.related_artifacts[:3]:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def attach_recovery_payload(payload: dict, hint: RecoveryHint | None) -> dict:
    """JSON 출력용 payload에 recovery 구조를 붙인다."""
    if hint is None:
        return payload
    enriched = dict(payload)
    enriched["recovery_hint"] = hint.to_dict()
    enriched["error_id"] = hint.error_id
    enriched["severity"] = hint.severity
    enriched["problem"] = hint.problem
    enriched["why"] = hint.why
    enriched["try_next"] = [item.to_dict() for item in hint.try_next]
    enriched["related_artifacts"] = list(hint.related_artifacts)
    return enriched


class RecoveryHintBuilder:
    """자주 쓰는 recovery hint를 만든다."""

    @staticmethod
    def _commands(
        commands: list[str] | None,
        *,
        reason: str,
    ) -> list[RecoveryCommand]:
        items = _dedupe([str(item) for item in (commands or []) if item])
        recovery: list[RecoveryCommand] = []
        for index, command in enumerate(items):
            recovery.append(
                RecoveryCommand(
                    label=f"try-{index + 1}",
                    command=command,
                    reason=reason,
                    primary=index == 0,
                )
            )
        return recovery

    def generic(
        self,
        *,
        error_id: str,
        status: str,
        severity: str,
        stage: str | None,
        problem: str,
        why: str,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
    ) -> RecoveryHint:
        """일반 purpose recovery hint."""
        return RecoveryHint(
            error_id=error_id,
            status=status,
            severity=severity,
            stage=stage,
            problem=problem,
            why=why,
            try_next=self._commands(commands, reason="다음 안전한 단계입니다."),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
            warnings=_dedupe([str(item) for item in (warnings or []) if item]),
            errors=_dedupe([str(item) for item in (errors or []) if item]),
        )

    def project_not_initialized(
        self,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
        stage: str | None = None,
    ) -> RecoveryHint:
        return RecoveryHint(
            error_id="project_not_initialized",
            status="blocked",
            severity="warning",
            stage=stage,
            problem="This project is not initialized for Cambrian yet.",
            why="Project mode needs `.cambrian/project.yaml` before it can read context, memory, and rules safely.",
            try_next=self._commands(commands or ["cambrian init --wizard"], reason="프로젝트를 Cambrian에 먼저 맞춥니다."),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def no_active_session(
        self,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
    ) -> RecoveryHint:
        return RecoveryHint(
            error_id="no_active_session",
            status="blocked",
            severity="warning",
            stage="blocked",
            problem="There is no active Cambrian work session to continue.",
            why="`cambrian do --continue` needs an open session or a specific `--session` target.",
            try_next=self._commands(
                commands or ['cambrian do "fix a small bug"', "cambrian status"],
                reason="새 작업을 시작하거나 현재 상태를 확인할 수 있습니다.",
            ),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def missing_source_choice(
        self,
        request_id: str | None = None,
        suggestions: list[str] | None = None,
        *,
        related_artifacts: list[str] | None = None,
        stage: str | None = "clarification_open",
    ) -> RecoveryHint:
        commands = suggestions or []
        if not commands:
            session_flag = f" --session {request_id}" if request_id else ""
            commands = [f"cambrian do --continue{session_flag} --use-suggestion 1 --execute"]
        return RecoveryHint(
            error_id="missing_source_choice",
            status="blocked",
            severity="warning",
            stage=stage,
            problem="A source file has not been selected yet.",
            why="Diagnosis needs an explicit source choice before Cambrian inspects files or runs related tests.",
            try_next=self._commands(commands, reason="추천 source/test를 선택해 안전하게 진단을 이어갑니다."),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def no_context_match(
        self,
        user_request: str,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
    ) -> RecoveryHint:
        quoted = user_request.replace('"', '\\"') if user_request else "fix a small bug"
        return RecoveryHint(
            error_id="no_context_match",
            status="blocked",
            severity="warning",
            stage="needs_context",
            problem="Cambrian could not find a confident project context match.",
            why="The request is still too broad for a safe source/test choice, or the project files do not match the current wording.",
            try_next=self._commands(
                commands
                or [
                    f'cambrian do "{quoted} in src/auth.py"',
                    'cambrian context scan "more specific request" --source "path/to/file.py"',
                ],
                reason="요청을 더 구체화하거나 source를 직접 지정해 match를 돕습니다.",
            ),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def unsafe_path(
        self,
        path: str,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
        stage: str | None = None,
    ) -> RecoveryHint:
        return RecoveryHint(
            error_id="unsafe_path",
            status="blocked",
            severity="high",
            stage=stage,
            problem=f"The path is not safe to use here: {path or '(unknown)'}",
            why="Cambrian only works with files inside the current project workspace and respects protected paths such as `.git` and `.cambrian`.",
            try_next=self._commands(
                commands or ["cambrian status"],
                reason="프로젝트 안쪽 경로를 다시 고르거나 현재 project rules를 확인합니다.",
            ),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def missing_old_text(
        self,
        target_path: str,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
    ) -> RecoveryHint:
        return RecoveryHint(
            error_id="missing_old_text",
            status="blocked",
            severity="warning",
            stage="patch_intent_draft",
            problem=f"The selected old text was not found in {target_path or 'the target file'}.",
            why="The file changed since diagnosis, or the chosen old text candidate does not match the current file contents.",
            try_next=self._commands(
                commands or ["cambrian do --continue --execute"],
                reason="다시 진단하거나 다른 old_text 후보를 골라 현재 파일 상태와 맞춥니다.",
            ),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def conflicting_patch_args(
        self,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
    ) -> RecoveryHint:
        return RecoveryHint(
            error_id="conflicting_patch_args",
            status="blocked",
            severity="warning",
            stage="patch_intent_draft",
            problem="The patch input arguments conflict with each other.",
            why="Cambrian needs exactly one old-text input mode and one new-text input mode, and validate/apply must stay separate.",
            try_next=self._commands(
                commands or ['cambrian do --continue --old-choice old-1 --new-text "..." --validate'],
                reason="입력 모드를 하나씩만 선택해서 단계를 분리합니다.",
            ),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def proposal_not_validated(
        self,
        proposal_path: str,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
    ) -> RecoveryHint:
        default_commands = commands or ["cambrian do --continue --validate"]
        if proposal_path:
            default_commands.append(f"cambrian patch apply {proposal_path} --reason \"...\"")
        return RecoveryHint(
            error_id="proposal_not_validated",
            status="blocked",
            severity="warning",
            stage="patch_proposal_ready",
            problem="The patch proposal has not been validated yet.",
            why="Cambrian only allows real source changes after isolated validation has passed.",
            try_next=self._commands(default_commands, reason="먼저 validate를 통과시킨 뒤 apply를 진행합니다."),
            related_artifacts=_dedupe([proposal_path, *(related_artifacts or [])]),
        )

    def apply_requires_reason(
        self,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
    ) -> RecoveryHint:
        return RecoveryHint(
            error_id="apply_requires_reason",
            status="blocked",
            severity="warning",
            stage="patch_proposal_validated",
            problem="Applying a patch requires an explicit human reason.",
            why="Cambrian keeps adoption explicit so the project history records why the real source change was accepted.",
            try_next=self._commands(
                commands or ['cambrian do --continue --apply --reason "..."'],
                reason="apply에는 사람이 남기는 승인 이유가 꼭 필요합니다.",
            ),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def validate_apply_conflict(
        self,
        *,
        commands: list[str] | None = None,
        related_artifacts: list[str] | None = None,
    ) -> RecoveryHint:
        return RecoveryHint(
            error_id="validate_apply_conflict",
            status="blocked",
            severity="warning",
            stage="patch_intent_draft",
            problem="Validation and apply cannot run in the same command.",
            why="Validation must stay isolated from real source mutation so Cambrian can preserve its safety boundary.",
            try_next=self._commands(
                commands or ['cambrian do --continue --old-choice old-1 --new-text "..." --validate'],
                reason="validate와 apply를 두 단계로 나누면 안전 경계가 유지됩니다.",
            ),
            related_artifacts=_dedupe([str(item) for item in (related_artifacts or []) if item]),
        )

    def doctor_dependency_missing(
        self,
        dep_name: str,
        *,
        required: bool = False,
        commands: list[str] | None = None,
    ) -> RecoveryHint:
        install_command = "pip install -e .[dev]" if required else f"pip install {dep_name}"
        return RecoveryHint(
            error_id="doctor_dependency_missing",
            status="fail" if required else "warn",
            severity="high" if required else "warning",
            stage="doctor",
            problem=f"The environment is missing {dep_name}.",
            why="This dependency is needed for Project Mode checks or the demo/validation flow.",
            try_next=self._commands(
                commands or [install_command, "cambrian doctor"],
                reason="의존성을 채운 뒤 doctor를 다시 실행해 환경을 확인합니다.",
            ),
        )

    def alpha_not_ready(
        self,
        failures: list[str],
        *,
        commands: list[str] | None = None,
    ) -> RecoveryHint:
        detail = failures[0] if failures else "Project Mode still has unresolved release-gate issues."
        return RecoveryHint(
            error_id="alpha_not_ready",
            status="fail" if failures else "warn",
            severity="high" if failures else "warning",
            stage="alpha_check",
            problem="Cambrian is not fully ready to share as an alpha yet.",
            why=detail,
            try_next=self._commands(
                commands or ["cambrian alpha check --save", "cambrian status"],
                reason="문제 지점을 고친 뒤 audit를 다시 실행합니다.",
            ),
            warnings=_dedupe(failures),
        )


def _actions_from_payload(payload: dict) -> list[str]:
    actions = payload.get("next_actions", [])
    if isinstance(actions, list):
        commands = [str(item) for item in actions if isinstance(item, str) and item.strip()]
    else:
        commands = []
    return commands


def hint_for_do_session(payload: dict) -> RecoveryHint | None:
    """do 결과 payload에서 recovery hint를 추론한다."""
    builder = RecoveryHintBuilder()
    status = str(payload.get("status", ""))
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    related = [str(artifacts.get("clarification_path") or ""), str(artifacts.get("request_path") or "")]
    if status == "initialized_required" or not bool(payload.get("project_initialized", True)):
        return builder.project_not_initialized(
            commands=_actions_from_payload(payload),
            related_artifacts=related,
            stage="initialized_required",
        )
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    found_sources = list(summary.get("selected_sources", []) or summary.get("found_sources", []))
    found_tests = list(summary.get("selected_tests", []) or summary.get("found_tests", []))
    if status == "needs_context" and not found_sources and not found_tests:
        return builder.no_context_match(
            str(payload.get("user_request", "")),
            commands=_actions_from_payload(payload),
            related_artifacts=related,
        )
    if status == "blocked":
        errors = " ".join(str(item) for item in payload.get("errors", []) if item).lower()
        if "source" in errors or any("--use-suggestion" in item for item in _actions_from_payload(payload)):
            return builder.missing_source_choice(
                payload.get("session_id"),
                _actions_from_payload(payload),
                related_artifacts=related,
            )
    return None


def hint_for_continue_session(payload: dict) -> RecoveryHint | None:
    """do continue 결과 payload에서 recovery hint를 추론한다."""
    builder = RecoveryHintBuilder()
    actions = _actions_from_payload(payload)
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    related = [
        str(artifacts.get("clarification_path") or ""),
        str(artifacts.get("patch_intent_path") or ""),
        str(artifacts.get("patch_proposal_path") or ""),
    ]
    if str(payload.get("session_id", "")) == "missing-session":
        return builder.no_active_session(commands=actions, related_artifacts=related)
    errors = " ".join(str(item) for item in payload.get("errors", []) if item)
    lowered = errors.lower()
    if "--reason" in lowered or "human reason is required" in lowered or "apply" in lowered and "--reason" in " ".join(actions):
        return builder.apply_requires_reason(commands=actions, related_artifacts=related)
    if "old_choice" in lowered or "new_text" in lowered and "file" in lowered:
        return builder.conflicting_patch_args(commands=actions, related_artifacts=related)
    if "source" in lowered and str(payload.get("current_stage", "")) in {"clarification_open", "needs_context", "blocked"}:
        return builder.missing_source_choice(
            payload.get("session_id"),
            actions,
            related_artifacts=related,
            stage=str(payload.get("current_stage") or "clarification_open"),
        )
    if "old_text was not found" in lowered:
        target_path = ""
        summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
        selected_sources = list(summary.get("selected_sources", []) or [])
        if selected_sources:
            target_path = str(selected_sources[0])
        return builder.missing_old_text(target_path, commands=actions, related_artifacts=related)
    if "proposal validation has not passed" in lowered or "proposal validation status is" in lowered:
        return builder.proposal_not_validated(
            str(artifacts.get("patch_proposal_path") or ""),
            commands=actions,
            related_artifacts=related,
        )
    if "continue cannot proceed" in lowered:
        return builder.no_active_session(commands=actions, related_artifacts=related)
    return None


def hint_for_clarification(payload: dict) -> RecoveryHint | None:
    """clarification payload에서 recovery hint를 추론한다."""
    builder = RecoveryHintBuilder()
    status = str(payload.get("status", ""))
    if status != "blocked":
        return None
    related = [str(payload.get("artifact_path") or ""), str(payload.get("generated_task_spec_path") or "")]
    return builder.missing_source_choice(
        None,
        [str(item) for item in payload.get("next_actions", []) if item],
        related_artifacts=related,
    )


def hint_for_context_scan(payload: dict) -> RecoveryHint | None:
    """context scan payload에서 recovery hint를 추론한다."""
    if str(payload.get("status", "")) != "no_match":
        return None
    return RecoveryHintBuilder().no_context_match(
        str(payload.get("user_request", "")),
        commands=[str(item) for item in payload.get("next_actions", []) if item],
    )


def hint_for_patch_intent(payload: dict) -> RecoveryHint | None:
    """patch intent payload에서 recovery hint를 추론한다."""
    if str(payload.get("status", "")) != "blocked":
        return None
    builder = RecoveryHintBuilder()
    errors = " ".join(str(item) for item in payload.get("errors", []) if item)
    lowered = errors.lower()
    actions = [str(item) for item in payload.get("next_actions", []) if item]
    target_path = str(payload.get("target_path") or "")
    related = [str(payload.get("source_diagnosis_ref") or ""), str(payload.get("proposal_path") or "")]
    if "old_choice" in lowered or "new_text" in lowered and "file" in lowered:
        return builder.conflicting_patch_args(commands=actions, related_artifacts=related)
    if "unsafe" in lowered or "target_path" in lowered and "missing" in lowered:
        return builder.unsafe_path(target_path, commands=actions, related_artifacts=related, stage="patch_intent_draft")
    if "old_text was not found" in lowered:
        return builder.missing_old_text(target_path, commands=actions, related_artifacts=related)
    return builder.generic(
        error_id="patch_intent_blocked",
        status="blocked",
        severity="warning",
        stage="patch_intent_draft",
        problem="Cambrian could not prepare the patch intent safely.",
        why=errors or "The selected patch inputs could not be turned into a safe patch intent.",
        commands=actions,
        related_artifacts=related,
    )


def hint_for_patch_proposal(payload: dict) -> RecoveryHint | None:
    """patch proposal payload에서 recovery hint를 추론한다."""
    if str(payload.get("proposal_status", "")) != "blocked":
        return None
    builder = RecoveryHintBuilder()
    warnings = [str(item) for item in payload.get("safety_warnings", []) if item]
    joined = " ".join(warnings).lower()
    actions = [str(item) for item in payload.get("next_actions", []) if item]
    target_path = str(payload.get("target_path") or "")
    related = [str(payload.get("source_diagnosis_ref") or ""), str(payload.get("task_spec_path") or "")]
    if "unsafe target path" in joined:
        return builder.unsafe_path(target_path, commands=actions, related_artifacts=related, stage="patch_proposal_ready")
    if "old_text was not found" in joined:
        return builder.missing_old_text(target_path, commands=actions, related_artifacts=related)
    return builder.generic(
        error_id="patch_proposal_blocked",
        status="blocked",
        severity="warning",
        stage="patch_proposal_ready",
        problem="Cambrian could not prepare this patch proposal safely.",
        why=warnings[0] if warnings else "The proposal did not pass the safety checks needed to create a patch artifact.",
        commands=actions,
        related_artifacts=related,
        warnings=warnings,
    )


def hint_for_patch_apply(payload: dict) -> RecoveryHint | None:
    """patch apply payload에서 recovery hint를 추론한다."""
    if str(payload.get("status", "")) != "blocked":
        return None
    builder = RecoveryHintBuilder()
    reasons = [str(item) for item in payload.get("reasons", []) if item]
    joined = " ".join(reasons).lower()
    actions = []
    proposal_path = str(payload.get("proposal_path") or "")
    target_path = str(payload.get("target_path") or "")
    if "human reason is required" in joined:
        actions = [f'cambrian patch apply {proposal_path} --reason "..."'] if proposal_path else None
        return builder.apply_requires_reason(commands=actions, related_artifacts=[proposal_path])
    if "proposal validation has not passed" in joined or "proposal validation status is" in joined:
        commands = ["cambrian do --continue --validate"]
        if proposal_path:
            commands.append(f"cambrian patch apply {proposal_path} --reason \"...\"")
        return builder.proposal_not_validated(
            proposal_path,
            commands=commands,
            related_artifacts=[proposal_path],
        )
    if "unsafe target path" in joined:
        return builder.unsafe_path(target_path, commands=["cambrian status"], related_artifacts=[proposal_path], stage="patch_apply")
    if "old_text was not found" in joined:
        return builder.missing_old_text(target_path, commands=["cambrian do --continue --execute"], related_artifacts=[proposal_path])
    return builder.generic(
        error_id="patch_apply_blocked",
        status="blocked",
        severity="warning",
        stage="patch_apply",
        problem="Cambrian did not apply the patch.",
        why=reasons[0] if reasons else "The proposal did not satisfy the apply safety checks.",
        commands=[f"cambrian patch apply {proposal_path} --reason \"...\""] if proposal_path else ["cambrian status"],
        related_artifacts=[proposal_path],
        warnings=reasons,
    )


def hint_for_doctor_report(payload: dict) -> RecoveryHint | None:
    """doctor report에서 recovery hint를 추론한다."""
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        return None
    builder = RecoveryHintBuilder()
    for item in checks:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        status = str(item.get("status", ""))
        details = [str(detail) for detail in item.get("details", []) if detail]
        if name == "Required dependencies" and status == "fail":
            dep = "required dependencies"
            for detail in details:
                if detail.startswith("missing import: "):
                    dep = detail.split(": ", 1)[1]
                    break
            return builder.doctor_dependency_missing(dep, required=True)
        if name == "pytest" and status == "warn":
            return builder.doctor_dependency_missing("pytest", required=False)
        if name == "Project mode" and status == "warn":
            return builder.project_not_initialized(
                commands=[str(item) for item in payload.get("next_actions", []) if item],
                stage="doctor",
            )
    return None


def hint_for_alpha_report(payload: dict) -> RecoveryHint | None:
    """alpha readiness report에서 recovery hint를 추론한다."""
    status = str(payload.get("status", ""))
    if status not in {"warn", "fail"}:
        return None
    checks = payload.get("checks", [])
    failures: list[str] = []
    if isinstance(checks, list):
        for item in checks:
            if not isinstance(item, dict):
                continue
            if item.get("status") in {"warn", "fail"}:
                failures.append(str(item.get("summary", "")))
    return RecoveryHintBuilder().alpha_not_ready(
        _dedupe(failures),
        commands=[str(item) for item in payload.get("next_actions", []) if item],
    )
