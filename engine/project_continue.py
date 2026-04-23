"""Cambrian do continue 오케스트레이션."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from engine.project_clarifier import RunClarifier
from engine.project_do import (
    DoSession,
    DoSessionStore,
    _current_stage_from_status,
    _dedupe,
    _human_status,
    _now,
    _quote_arg,
)
from engine.project_errors import hint_for_continue_session, render_recovery_hint
from engine.project_next import NextCommandBuilder
from engine.project_patch import PatchIntent, PatchProposalBuilder
from engine.project_patch_apply import PatchApplier
from engine.project_patch_intent import (
    PatchIntentBuilder,
    PatchIntentFiller,
    PatchIntentStore,
)

logger = logging.getLogger(__name__)


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


def _load_json(path: Path) -> dict | None:
    """JSON 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("JSON 로드 실패: %s (%s)", path, exc)
        return None
    if not isinstance(payload, dict):
        logger.warning("JSON 형식 오류: %s", path)
        return None
    return payload


def _relative(path: Path, root: Path) -> str:
    """프로젝트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _resolve_artifact(root: Path, artifact_ref: str | None) -> Path | None:
    """상대/절대 artifact 경로를 실제 경로로 바꾼다."""
    if not artifact_ref:
        return None
    candidate = Path(artifact_ref)
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _proposal_to_intent(proposal_payload: dict) -> PatchIntent:
    """proposal payload를 PatchIntent로 되돌린다."""
    action = dict(proposal_payload.get("action", {}))
    return PatchIntent(
        target_path=str(action.get("target_path") or proposal_payload.get("target_path") or ""),
        old_text=action.get("old_text"),
        new_text=action.get("new_text"),
        patch_file_path=None,
        related_tests=list(proposal_payload.get("related_tests", [])),
        source_diagnosis_ref=proposal_payload.get("source_diagnosis_ref"),
        source_context_ref=proposal_payload.get("source_context_ref"),
        user_request=proposal_payload.get("user_request"),
        memory_guidance_ref=proposal_payload.get("memory_guidance_ref"),
    )


def _continue_session_flag(session: DoSession) -> str:
    """continue 명령에 붙일 session 인자를 만든다."""
    if not session.session_id or session.session_id == "missing-session":
        return ""
    return f" --session {session.session_id}"


def _continue_command(session: DoSession, tail: str = "") -> str:
    """현재 session에 바인딩된 continue 명령을 만든다."""
    base = f"cambrian do --continue{_continue_session_flag(session)}"
    suffix = str(tail or "").strip()
    if not suffix:
        return base
    return f"{base} {suffix}"


class DoContinuationPlanner:
    """현재 session stage와 다음 안전한 단계를 계산한다."""

    def __init__(self) -> None:
        self._clarifier = RunClarifier()
        self._intent_store = PatchIntentStore()

    def plan(self, session: DoSession, project_root: Path, options: dict) -> dict:
        """session 기반 다음 단계를 계산한다."""
        root = Path(project_root).resolve()
        stage = self._detect_stage(session, root)
        next_commands = self._build_next_commands(session, stage, options)
        recommended = {
            "clarification_open": "answer_clarification",
            "needs_context": "answer_clarification",
            "diagnose_ready": "execute_diagnosis",
            "diagnosed": "create_patch_intent",
            "patch_intent_draft": "fill_patch_intent",
            "patch_intent_ready": "create_patch_proposal",
            "patch_proposal_ready": "validate_patch_proposal",
            "patch_proposal_validated": "apply_validated_proposal",
            "adopted": "show_completion",
        }.get(stage, "review_status")
        requires: list[str] = []
        if stage in {"clarification_open", "needs_context"}:
            requires = ["source 선택"]
        elif stage == "patch_intent_draft":
            requires = ["old_choice 또는 old_text", "new_text"]
        elif stage == "patch_proposal_validated":
            requires = ["--apply", "--reason"]
        return {
            "stage": stage,
            "recommended_action": recommended,
            "can_execute": stage in {"diagnose_ready", "diagnosed", "patch_intent_draft", "patch_intent_ready", "patch_proposal_ready", "patch_proposal_validated"},
            "requires": requires,
            "next_commands": next_commands,
            "warnings": [],
        }

    def _detect_stage(self, session: DoSession, project_root: Path) -> str:
        """artifact 상태를 보고 현재 stage를 계산한다."""
        artifacts = dict(session.artifacts or {})

        adoption_path = _resolve_artifact(project_root, artifacts.get("adoption_record_path"))
        if adoption_path is not None and adoption_path.exists():
            return "adopted"

        proposal_path = _resolve_artifact(project_root, artifacts.get("patch_proposal_path"))
        if proposal_path is not None and proposal_path.exists():
            proposal_payload = _load_yaml(proposal_path)
            if proposal_payload:
                validation = proposal_payload.get("validation", {}) or {}
                if str(validation.get("status", "")) == "passed":
                    return "patch_proposal_validated"
                return "patch_proposal_ready"

        intent_path = _resolve_artifact(project_root, artifacts.get("patch_intent_path"))
        if intent_path is not None and intent_path.exists():
            form = self._intent_store.load(intent_path)
            if form.status == "ready_for_proposal":
                return "patch_intent_ready"
            if form.status == "blocked":
                return "blocked"
            return "patch_intent_draft"

        report_path = _resolve_artifact(project_root, artifacts.get("report_path"))
        if report_path is not None and report_path.exists():
            return "diagnosed"

        task_path = _resolve_artifact(project_root, artifacts.get("task_spec_path"))
        if task_path is not None and task_path.exists():
            return "diagnose_ready"

        clarification_path = _resolve_artifact(project_root, artifacts.get("clarification_path"))
        if clarification_path is not None and clarification_path.exists():
            clarification = self._clarifier.load(clarification_path)
            if clarification.status == "ready":
                return "diagnose_ready"
            if clarification.status in {"open", "answered"}:
                return "clarification_open"
            if clarification.status == "blocked":
                return "blocked"

        if artifacts.get("context_scan_path") or artifacts.get("request_path"):
            return "needs_context"
        return str(session.current_stage or _current_stage_from_status(session.status))

    def _build_next_commands(self, session: DoSession, stage: str, options: dict) -> list[str]:
        """stage별 추천 명령을 만든다."""
        request_text = session.user_request or "요청"
        commands: list[str] = []
        if stage in {"clarification_open", "needs_context"}:
            commands.append(_continue_command(session, "--use-suggestion 1 --execute"))
            commands.append(
                _continue_command(session, '--source "path/to/file.py" --test "path/to/test.py" --execute')
            )
        elif stage == "diagnose_ready":
            commands.append(_continue_command(session, "--execute"))
        elif stage == "diagnosed":
            commands.append(_continue_command(session, '--old-choice old-1 --new-text "..."'))
        elif stage == "patch_intent_draft":
            commands.append(_continue_command(session, '--old-choice old-1 --new-text "..."'))
            commands.append(_continue_command(session, '--old-choice old-1 --new-text "..." --propose --validate'))
        elif stage == "patch_intent_ready":
            commands.append(_continue_command(session, "--propose --validate"))
        elif stage == "patch_proposal_ready":
            commands.append(_continue_command(session, "--validate"))
        elif stage == "patch_proposal_validated":
            commands.append(_continue_command(session, '--apply --reason "fix login normalization"'))
        elif stage == "adopted":
            commands.append(f"cambrian status")
        else:
            commands.append(f"cambrian do {_quote_arg(request_text)}")
        return _dedupe(commands)


class ProjectDoContinuationRunner:
    """기존 do session을 다음 안전한 단계로 이어준다."""

    def __init__(self) -> None:
        self._store = DoSessionStore()
        self._planner = DoContinuationPlanner()
        self._clarifier = RunClarifier()
        self._intent_builder = PatchIntentBuilder()
        self._intent_store = PatchIntentStore()
        self._intent_filler = PatchIntentFiller()
        self._proposal_builder = PatchProposalBuilder()
        self._applier = PatchApplier()

    def run(self, project_root: Path, options: dict) -> DoSession:
        """session을 로드해 다음 단계를 이어간다."""
        root = Path(project_root).resolve()
        session_ref = options.get("session")
        try:
            session_path = self._store.resolve_path(root, session_ref)
        except FileNotFoundError as exc:
            return self._build_missing_session(root, str(exc))

        session = self._store.load(session_path)
        active_paths = self._store.list_active_paths(root)
        if session_ref is None and len(active_paths) > 1:
            session.warnings.append("열린 work session이 여러 개라서 가장 최근 session을 이어갑니다.")

        plan = self._planner.plan(session, root, options)
        stage = str(plan["stage"])
        session.current_stage = stage
        session.status = stage
        session.errors = []
        session.warnings = [item for item in session.warnings if item]

        if stage in {"clarification_open", "needs_context", "diagnose_ready"}:
            self._continue_clarification(session, root, options)
        elif stage == "diagnosed":
            self._continue_after_diagnosis(session, root, options)
        elif stage == "patch_intent_draft":
            self._continue_patch_intent_draft(session, root, options)
        elif stage == "patch_intent_ready":
            self._continue_patch_intent_ready(session, root, options)
        elif stage == "patch_proposal_ready":
            self._continue_patch_proposal_ready(session, root, options)
        elif stage == "patch_proposal_validated":
            self._continue_validated_proposal(session, root, options)
        elif stage == "adopted":
            session.next_actions = ["cambrian status"]
        else:
            session.status = "blocked"
            session.current_stage = stage
            session.errors.append(f"continue cannot proceed from stage: {stage}")
            session.next_actions = list(plan["next_commands"])

        self._refresh_summary(session, root)
        if not session.next_actions:
            refreshed_plan = self._planner.plan(session, root, options)
            session.next_actions = list(refreshed_plan["next_commands"])
        session.next_commands = NextCommandBuilder.from_actions(
            list(session.next_actions),
            stage=session.current_stage,
        )
        self._store.save(root, session)
        return session

    def _continue_clarification(self, session: DoSession, project_root: Path, options: dict) -> None:
        """clarification 단계 계속."""
        clarification_path = _resolve_artifact(project_root, session.artifacts.get("clarification_path"))
        if clarification_path is None or not clarification_path.exists():
            session.status = "blocked"
            session.current_stage = "blocked"
            session.errors.append("clarification artifact가 없습니다.")
            session.next_actions = [f"cambrian do {_quote_arg(session.user_request)}"]
            return

        sources = list(options.get("sources", []) or [])
        tests = list(options.get("tests", []) or [])
        use_suggestion = options.get("use_suggestion")
        execute = bool(options.get("execute", False))
        has_answer = bool(sources or tests or use_suggestion is not None)

        clarification = self._clarifier.load(clarification_path)
        if has_answer:
            clarification = self._clarifier.answer(
                clarification_path,
                source=sources,
                tests=tests,
                use_suggestion=use_suggestion,
                mode="diagnose",
            )
            session.continuations.append(
                {
                    "at": _now(),
                    "action": "clarification_answered",
                    "result": clarification.status,
                    "created": {
                        "clarification_path": clarification.artifact_path,
                        "task_spec_path": clarification.generated_task_spec_path,
                    },
                }
            )

        session.artifacts["clarification_path"] = clarification.artifact_path
        session.artifacts["task_spec_path"] = clarification.generated_task_spec_path

        if execute:
            if clarification.status != "ready":
                session.status = "blocked"
                session.current_stage = "clarification_open"
                session.errors.append("진단 실행 전 source 선택이 필요합니다.")
                session.next_actions = self._planner._build_next_commands(session, "clarification_open", options)
                return
            clarification = self._clarifier.execute_ready(clarification_path)
            execution = clarification.execution or {}
            session.artifacts["brain_run_id"] = execution.get("brain_run_id")
            session.artifacts["report_path"] = execution.get("report_path")
            session.status = "diagnosed" if execution.get("status") == "completed" else "error"
            session.current_stage = "diagnosed" if execution.get("status") == "completed" else "error"
            session.continuations.append(
                {
                    "at": _now(),
                    "action": "diagnose_executed",
                    "result": execution.get("status", "unknown"),
                    "created": {
                        "report_path": execution.get("report_path"),
                    },
                }
            )
            session.next_actions = (
                [_continue_command(session, '--old-choice old-1 --new-text "..."')]
                if execution.get("status") == "completed"
                else [_continue_command(session)]
            )
            return

        if clarification.status == "ready":
            session.status = "prepared"
            session.current_stage = "diagnose_ready"
        elif clarification.status in {"open", "answered"}:
            session.status = "clarification_open"
            session.current_stage = "clarification_open"
        else:
            session.status = clarification.status
            session.current_stage = clarification.status
        session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)

    def _continue_after_diagnosis(self, session: DoSession, project_root: Path, options: dict) -> None:
        """diagnosis 이후 patch intent로 이어간다."""
        self._ensure_patch_intent(session, project_root)
        if session.status == "blocked":
            return
        self._continue_patch_intent_draft(session, project_root, options)

    def _continue_patch_intent_draft(self, session: DoSession, project_root: Path, options: dict) -> None:
        """patch intent draft를 채운다."""
        intent_path = self._ensure_patch_intent(session, project_root)
        if intent_path is None:
            return

        has_fill = any(
            [
                options.get("old_choice") is not None,
                options.get("old_text") is not None,
                options.get("old_text_file") is not None,
                options.get("new_text") is not None,
                options.get("new_text_file") is not None,
            ]
        )
        form = self._intent_store.load(intent_path)
        if has_fill:
            form = self._intent_filler.fill(
                intent_path=intent_path,
                old_choice=options.get("old_choice"),
                old_text=options.get("old_text"),
                old_text_file=Path(options["old_text_file"]).resolve() if options.get("old_text_file") else None,
                new_text=options.get("new_text"),
                new_text_file=Path(options["new_text_file"]).resolve() if options.get("new_text_file") else None,
            )
            session.continuations.append(
                {
                    "at": _now(),
                    "action": "patch_intent_filled",
                    "result": form.status,
                    "created": {
                        "patch_intent_path": session.artifacts.get("patch_intent_path"),
                    },
                }
            )

        session.artifacts["patch_intent_path"] = _relative(intent_path, project_root)
        if form.status == "ready_for_proposal":
            session.status = "patch_intent_ready"
            session.current_stage = "patch_intent_ready"
            if options.get("propose") or options.get("validate") or options.get("execute"):
                self._continue_patch_intent_ready(session, project_root, options)
                return
        elif form.status == "blocked":
            session.status = "blocked"
            session.current_stage = "patch_intent_draft"
            session.errors.extend(item for item in form.errors if item not in session.errors)
        else:
            session.status = "patch_intent_draft"
            session.current_stage = "patch_intent_draft"

        session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)

    def _continue_patch_intent_ready(self, session: DoSession, project_root: Path, options: dict) -> None:
        """ready intent에서 proposal 생성으로 이어간다."""
        intent_path = _resolve_artifact(project_root, session.artifacts.get("patch_intent_path"))
        if intent_path is None or not intent_path.exists():
            session.status = "blocked"
            session.current_stage = "patch_intent_ready"
            session.errors.append("patch intent artifact가 없습니다.")
            session.next_actions = [_continue_command(session)]
            return

        form = self._intent_store.load(intent_path)
        if form.status != "ready_for_proposal":
            session.status = "patch_intent_draft"
            session.current_stage = "patch_intent_draft"
            session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)
            return

        should_propose = bool(options.get("propose") or options.get("validate") or options.get("execute"))
        if not should_propose:
            session.status = "patch_intent_ready"
            session.current_stage = "patch_intent_ready"
            session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)
            return

        proposal, proposal_path = self._proposal_builder.build(
            intent=PatchIntent(
                target_path=form.target_path or "",
                old_text=form.selected_old_text,
                new_text=form.new_text,
                related_tests=list(form.related_tests),
                source_diagnosis_ref=form.source_diagnosis_ref,
                source_context_ref=form.source_context_ref,
                user_request=form.user_request,
                memory_guidance_ref=dict(form.memory_guidance),
            ),
            project_root=project_root,
            out_dir=project_root / ".cambrian" / "patches",
            rules=self._load_rules(project_root),
            execute=bool(options.get("validate") or options.get("execute")),
        )
        proposal_rel = _relative(proposal_path, project_root)
        form.proposal_path = proposal_rel
        self._intent_store.save(form, intent_path)
        session.artifacts["patch_proposal_path"] = proposal_rel
        session.continuations.append(
            {
                "at": _now(),
                "action": "patch_proposal_created",
                "result": proposal.proposal_status,
                "created": {
                    "patch_proposal_path": proposal_rel,
                },
            }
        )
        validation = proposal.validation or {}
        if str(validation.get("status", "")) == "passed":
            session.status = "patch_proposal_validated"
            session.current_stage = "patch_proposal_validated"
        else:
            session.status = "patch_proposal_ready"
            session.current_stage = "patch_proposal_ready"
        session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)

    def _continue_patch_proposal_ready(self, session: DoSession, project_root: Path, options: dict) -> None:
        """proposal ready 상태에서 validation으로 이어간다."""
        should_validate = bool(options.get("validate") or options.get("execute"))
        if not should_validate:
            session.status = "patch_proposal_ready"
            session.current_stage = "patch_proposal_ready"
            session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)
            return

        proposal_path = _resolve_artifact(project_root, session.artifacts.get("patch_proposal_path"))
        if proposal_path is None or not proposal_path.exists():
            session.status = "blocked"
            session.current_stage = "patch_proposal_ready"
            session.errors.append("patch proposal artifact가 없습니다.")
            session.next_actions = [_continue_command(session)]
            return

        proposal_payload = _load_yaml(proposal_path)
        if not proposal_payload:
            session.status = "blocked"
            session.current_stage = "patch_proposal_ready"
            session.errors.append("patch proposal을 읽을 수 없습니다.")
            session.next_actions = [_continue_command(session)]
            return

        proposal, new_path = self._proposal_builder.build(
            intent=_proposal_to_intent(proposal_payload),
            project_root=project_root,
            out_dir=project_root / ".cambrian" / "patches",
            rules=self._load_rules(project_root),
            execute=True,
        )
        session.artifacts["patch_proposal_path"] = _relative(new_path, project_root)
        session.continuations.append(
            {
                "at": _now(),
                "action": "patch_proposal_validated",
                "result": str((proposal.validation or {}).get("status", proposal.proposal_status)),
                "created": {
                    "patch_proposal_path": session.artifacts["patch_proposal_path"],
                },
            }
        )
        if str((proposal.validation or {}).get("status", "")) == "passed":
            session.status = "patch_proposal_validated"
            session.current_stage = "patch_proposal_validated"
        else:
            session.status = "patch_proposal_ready"
            session.current_stage = "patch_proposal_ready"
        session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)

    def _continue_validated_proposal(self, session: DoSession, project_root: Path, options: dict) -> None:
        """validated proposal에서 explicit apply를 처리한다."""
        if not options.get("apply"):
            session.status = "patch_proposal_validated"
            session.current_stage = "patch_proposal_validated"
            session.next_actions = self._planner._build_next_commands(session, session.current_stage, options)
            return

        reason = str(options.get("reason") or "").strip()
        if not reason:
            session.status = "blocked"
            session.current_stage = "patch_proposal_validated"
            session.errors.append("apply에는 --reason 이 필요합니다.")
            session.next_actions = [_continue_command(session, '--apply --reason "fix login normalization"')]
            return

        proposal_path = _resolve_artifact(project_root, session.artifacts.get("patch_proposal_path"))
        if proposal_path is None or not proposal_path.exists():
            session.status = "blocked"
            session.current_stage = "patch_proposal_validated"
            session.errors.append("patch proposal artifact가 없습니다.")
            session.next_actions = [_continue_command(session)]
            return

        result = self._applier.apply(
            proposal_path=proposal_path,
            project_root=project_root,
            adoptions_dir=project_root / ".cambrian" / "adoptions",
            reason=reason,
            dry_run=False,
        )
        if result.status == "applied":
            session.artifacts["adoption_record_path"] = result.adoption_record_path
            session.status = "adopted"
            session.current_stage = "adopted"
            session.continuations.append(
                {
                    "at": _now(),
                    "action": "patch_applied",
                    "result": result.status,
                    "created": {
                        "adoption_record_path": result.adoption_record_path,
                    },
                }
            )
            session.next_actions = ["cambrian status"]
            return

        session.status = "blocked" if result.status == "blocked" else "error"
        session.current_stage = "patch_proposal_validated"
        session.errors.extend(item for item in result.reasons if item not in session.errors)
        session.next_actions = [_continue_command(session, '--apply --reason "fix login normalization"')]

    def _ensure_patch_intent(self, session: DoSession, project_root: Path) -> Path | None:
        """diagnosis report에서 patch intent artifact를 보장한다."""
        existing = _resolve_artifact(project_root, session.artifacts.get("patch_intent_path"))
        if existing is not None and existing.exists():
            return existing

        report_path = _resolve_artifact(project_root, session.artifacts.get("report_path"))
        if report_path is None or not report_path.exists():
            session.status = "blocked"
            session.current_stage = "diagnosed"
            session.errors.append("diagnosis report가 없어 patch intent를 만들 수 없습니다.")
            session.next_actions = [_continue_command(session, "--execute")]
            return None

        form = self._intent_builder.build_from_diagnosis(
            diagnosis_report_path=report_path,
            project_root=project_root,
        )
        target_label = Path(form.target_path or "unknown").name or "unknown"
        intent_dir = project_root / ".cambrian" / "patch_intents"
        intent_path = intent_dir / f"patch_intent_{form.intent_id}_{target_label}.yaml"
        self._intent_store.save(form, intent_path)
        session.artifacts["patch_intent_path"] = _relative(intent_path, project_root)
        session.continuations.append(
            {
                "at": _now(),
                "action": "patch_intent_created",
                "result": form.status,
                "created": {
                    "patch_intent_path": session.artifacts["patch_intent_path"],
                },
            }
        )
        return intent_path

    @staticmethod
    def _load_rules(project_root: Path) -> dict | None:
        """rules.yaml payload를 로드한다."""
        rules_path = project_root / ".cambrian" / "rules.yaml"
        payload = _load_yaml(rules_path)
        return payload if isinstance(payload, dict) else None

    def _refresh_summary(self, session: DoSession, project_root: Path) -> None:
        """artifact 상태를 바탕으로 세션 summary를 갱신한다."""
        summary = dict(session.summary or {})
        artifacts = dict(session.artifacts or {})

        clarification_path = _resolve_artifact(project_root, artifacts.get("clarification_path"))
        if clarification_path is not None and clarification_path.exists():
            clarification = self._clarifier.load(clarification_path)
            summary["selected_sources"] = list(clarification.selected_context.get("sources", []))
            summary["selected_tests"] = list(clarification.selected_context.get("tests", []))
            found_sources = []
            found_tests = []
            for question in clarification.questions:
                if question.kind == "source":
                    found_sources = [str(item.get("value", "")) for item in question.options if item.get("value")]
                elif question.kind == "test":
                    found_tests = [str(item.get("value", "")) for item in question.options if item.get("value")]
            summary["found_sources"] = found_sources
            summary["found_tests"] = found_tests

        report_path = _resolve_artifact(project_root, artifacts.get("report_path"))
        if report_path is not None and report_path.exists():
            report_payload = _load_json(report_path) or {}
            diagnostics = report_payload.get("diagnostics", {}) if isinstance(report_payload.get("diagnostics"), dict) else {}
            summary["diagnosis_result"] = (
                "related test failed"
                if int((diagnostics.get("test_results", {}) or {}).get("failed", 0) or 0) > 0
                else "diagnosis completed"
            )
            if diagnostics.get("inspected_files"):
                summary["selected_sources"] = [
                    str(item.get("path", ""))
                    for item in diagnostics.get("inspected_files", [])
                    if isinstance(item, dict) and item.get("path")
                ]
            if diagnostics.get("related_tests"):
                summary["selected_tests"] = [
                    str(item) for item in diagnostics.get("related_tests", []) if isinstance(item, str)
                ]

        intent_path = _resolve_artifact(project_root, artifacts.get("patch_intent_path"))
        if intent_path is not None and intent_path.exists():
            form = self._intent_store.load(intent_path)
            summary["patch_intent_status"] = form.status
            summary["old_text_candidates"] = [
                {
                    "id": item.id,
                    "text": item.text,
                }
                for item in form.old_text_candidates
            ]
            if form.target_path:
                summary["selected_sources"] = [form.target_path]
            if form.related_tests:
                summary["selected_tests"] = list(form.related_tests)

        proposal_path = _resolve_artifact(project_root, artifacts.get("patch_proposal_path"))
        if proposal_path is not None and proposal_path.exists():
            proposal_payload = _load_yaml(proposal_path) or {}
            validation = proposal_payload.get("validation", {}) or {}
            summary["patch_proposal_status"] = proposal_payload.get("proposal_status", "unknown")
            summary["patch_validation_status"] = validation.get("status", "not_requested")

        adoption_path = _resolve_artifact(project_root, artifacts.get("adoption_record_path"))
        if adoption_path is not None and adoption_path.exists():
            adoption_payload = _load_json(adoption_path) or {}
            summary["adoption_target"] = adoption_payload.get("target_path", "")
            summary["adoption_result"] = adoption_payload.get("adoption_status", "adopted")

        session.summary = summary

    def _build_missing_session(self, project_root: Path, message: str) -> DoSession:
        """active session이 없을 때 보여줄 가짜 session 결과."""
        return DoSession(
            schema_version="1.1.0",
            session_id="missing-session",
            created_at=_now(),
            updated_at=_now(),
            user_request="",
            project_initialized=(project_root / ".cambrian" / "project.yaml").exists(),
            intent=None,
            selected_skills=[],
            status="blocked",
            current_stage="blocked",
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
                "understood_as": "continue",
                "found_sources": [],
                "found_tests": [],
                "selected_sources": [],
                "selected_tests": [],
                "needs": ["active do session"],
            },
            next_actions=["cambrian do \"fix a small bug\""],
            continuations=[],
            warnings=[],
            errors=[message],
            artifact_path=None,
        )


def render_do_continue_summary(session: DoSession | dict) -> str:
    """continue 결과를 사람이 읽기 쉽게 렌더링한다."""
    payload = session.to_dict() if isinstance(session, DoSession) else dict(session)
    recovery_hint = hint_for_continue_session(payload)
    if recovery_hint is not None:
        return render_recovery_hint(recovery_hint)
    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
    current_stage = str(payload.get("current_stage") or _current_stage_from_status(str(payload.get("status", "unknown"))))

    def _current_text() -> str:
        mapping = {
            "clarification_open": "clarification is waiting for your choice",
            "needs_context": "more context is needed",
            "diagnose_ready": "diagnose-only task is ready",
            "diagnosed": "diagnosis completed",
            "patch_intent_draft": "patch intent draft is ready",
            "patch_intent_ready": "patch intent is ready for proposal",
            "patch_proposal_ready": "patch proposal is ready",
            "patch_proposal_validated": "patch proposal validated",
            "adopted": "patch applied and adopted",
            "blocked": "continuation is blocked",
            "error": "continuation failed",
        }
        return mapping.get(current_stage, _human_status(str(payload.get("status", "unknown"))))

    lines = [
        "Cambrian can continue this work.",
        "",
        "Current:",
        f"  {_current_text()}",
        "",
        "Found:",
        f"  source: {', '.join(summary.get('selected_sources', []) or summary.get('found_sources', [])) or 'none'}",
        f"  test  : {', '.join(summary.get('selected_tests', []) or summary.get('found_tests', [])) or 'none'}",
    ]

    if summary.get("diagnosis_result"):
        lines.append(f"  result: {summary.get('diagnosis_result')}")
    old_candidates = list(summary.get("old_text_candidates", []))
    if old_candidates:
        lines.append("  old text candidates:")
        for item in old_candidates[:3]:
            lines.append(f"    - {item.get('id')}: {item.get('text')}")

    created = {}
    continuations = list(payload.get("continuations", []))
    if continuations:
        last = continuations[-1]
        if isinstance(last, dict):
            created = dict(last.get("created", {})) if isinstance(last.get("created"), dict) else {}
    if not created:
        created = {
            key: value
            for key, value in artifacts.items()
            if value and key in {"patch_intent_path", "patch_proposal_path", "adoption_record_path", "report_path", "task_spec_path"}
        }

    if created:
        lines.extend(["", "Created:"])
        for key, value in created.items():
            lines.append(f"  {key}: {value}")

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
