"""Cambrian guided patch proposal 도우미."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.brain.adapters.executor_v1 import ExecutorV1
from engine.brain.adapters.tester_v1 import TesterV1
from engine.brain.models import RunState, TaskSpec, WorkItem

logger = logging.getLogger(__name__)


PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    ".git",
    ".cambrian",
    "__pycache__",
    ".pytest_cache",
)
MAX_PATCH_FILE_BYTES = 1_048_576


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _proposal_id() -> str:
    """patch proposal 식별자를 만든다."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"patch-{stamp}-{secrets.token_hex(2)}"


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


def _load_yaml(path: Path) -> dict:
    """YAML 파일을 읽는다."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML 최상위는 dict여야 합니다: {path}")
    return payload


def _load_json(path: Path) -> dict:
    """JSON 파일을 읽는다."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 최상위는 dict여야 합니다: {path}")
    return payload


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _relative(path: Path, root: Path) -> str:
    """project_root 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _sha256_text(text: str) -> str:
    """문자열 sha256."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    """파일 sha256."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_binary(path: Path) -> bool:
    """바이너리 파일 여부를 가볍게 판별한다."""
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" in sample


@dataclass
class PatchIntent:
    """사용자가 명시적으로 승인한 패치 의도."""

    target_path: str
    old_text: str | None
    new_text: str | None
    patch_file_path: str | None = None
    related_tests: list[str] = field(default_factory=list)
    source_diagnosis_ref: str | None = None
    source_context_ref: str | None = None
    user_request: str | None = None
    memory_guidance_ref: dict | None = None


@dataclass
class PatchProposal:
    """패치 proposal artifact."""

    schema_version: str
    proposal_id: str
    created_at: str
    user_request: str | None
    source_diagnosis_ref: str | None
    source_context_ref: str | None
    target_path: str
    related_tests: list[str]
    action: dict
    proposal_status: str
    safety_warnings: list[str]
    validation: dict | None
    task_spec_path: str | None
    next_actions: list[str]
    memory_guidance_ref: dict | None = None

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class PatchProposalValidator:
    """Patch intent를 안전 규칙으로 검증한다."""

    def validate_intent(
        self,
        intent: PatchIntent,
        project_root: Path,
        rules: dict | None = None,
    ) -> tuple[bool, list[str], list[str]]:
        """intent를 검증하고 (통과 여부, 차단 사유, 경고)를 반환한다."""
        reasons: list[str] = []
        warnings: list[str] = []

        if intent.patch_file_path and (intent.old_text is not None or intent.new_text is not None):
            reasons.append("--patch-file 과 --old-text/--new-text 는 함께 사용할 수 없습니다.")
            return False, reasons, warnings

        if intent.patch_file_path:
            reasons.append("--patch-file 경로는 아직 지원하지 않습니다. old_text/new_text를 사용하세요.")
            return False, reasons, warnings

        target = self._validate_target(intent.target_path, project_root, rules)
        if target is None:
            reasons.append(f"unsafe target path: {intent.target_path}")
            return False, reasons, warnings

        if intent.old_text is None or intent.old_text == "":
            reasons.append("old_text가 비어 있습니다.")
        if intent.new_text is None:
            reasons.append("new_text가 없습니다.")
        if intent.old_text is not None and intent.new_text is not None and intent.old_text == intent.new_text:
            reasons.append("old_text와 new_text가 같습니다.")
        if reasons:
            return False, reasons, warnings

        if not target.exists():
            reasons.append(f"target file이 없습니다: {intent.target_path}")
            return False, reasons, warnings
        if target.stat().st_size > MAX_PATCH_FILE_BYTES:
            reasons.append(f"target file이 너무 큽니다: {intent.target_path}")
            return False, reasons, warnings
        if _is_binary(target):
            reasons.append(f"binary file은 patch proposal 대상이 아닙니다: {intent.target_path}")
            return False, reasons, warnings

        content = target.read_text(encoding="utf-8")
        if intent.old_text not in content:
            reasons.append(f"old_text was not found in {intent.target_path}")
            return False, reasons, warnings

        match_count = content.count(intent.old_text)
        if match_count > 1:
            warnings.append(f"old_text가 {match_count}번 발견되었습니다. 첫 번째 위치 기준으로 검증됩니다.")

        return True, reasons, warnings

    @staticmethod
    def _validate_target(target_path: str, project_root: Path, rules: dict | None = None) -> Path | None:
        """target path safety 검사."""
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


class PatchTaskSpecBuilder:
    """proposal을 brain-compatible TaskSpec으로 변환한다."""

    def build_task_spec(self, proposal: PatchProposal, out_dir: Path) -> Path:
        """TaskSpec YAML을 저장하고 경로를 반환한다."""
        task_spec = TaskSpec(
            task_id=f"task-patch-{proposal.proposal_id}",
            goal=f"Validate patch proposal for {proposal.target_path}",
            scope=[
                "Apply user-approved patch in a controlled run",
                "Run related tests",
                "Do not automatically adopt",
            ],
            acceptance_criteria=[
                "Patch applies cleanly",
                "Related tests pass",
                "No automatic adoption occurs",
            ],
            related_files=[proposal.target_path],
            related_tests=list(proposal.related_tests),
            output_paths=[proposal.target_path],
            actions=[dict(proposal.action)],
            hypothesis={
                "id": f"hyp-{proposal.proposal_id}",
                "statement": "The approved patch should apply cleanly and keep related tests passing.",
                "predicts": {
                    "tests": {
                        "failed_max": 0,
                    }
                },
            },
            competitive={"enabled": False},
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        task_path = out_dir / f"task_patch_{proposal.proposal_id}.yaml"
        task_spec.to_yaml(task_path)
        return task_path


class PatchProposalBuilder:
    """diagnosis와 patch intent로 proposal을 생성한다."""

    def __init__(self) -> None:
        self._validator = PatchProposalValidator()
        self._task_builder = PatchTaskSpecBuilder()

    def build(
        self,
        intent: PatchIntent,
        project_root: Path,
        out_dir: Path,
        *,
        rules: dict | None = None,
        execute: bool = False,
    ) -> tuple[PatchProposal, Path]:
        """proposal artifact를 만들고 필요 시 isolated validation까지 수행한다."""
        proposal_id = _proposal_id()
        created_at = _now()
        out_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = out_dir / f"patch_proposal_{proposal_id}_{Path(intent.target_path).name}.yaml"

        valid, reasons, warnings = self._validator.validate_intent(intent, project_root, rules)
        related_tests, extraction_warnings = self._resolve_related_tests(intent, project_root)
        warnings.extend(extraction_warnings)

        action = {
            "type": "patch_file",
            "target_path": intent.target_path,
            "old_text": intent.old_text,
            "new_text": intent.new_text,
        }

        proposal_status = "ready" if valid else "blocked"
        if valid and not related_tests:
            warnings.append("관련 테스트를 찾지 못했습니다. 검증은 inconclusive가 될 수 있습니다.")

        proposal = PatchProposal(
            schema_version="1.0.0",
            proposal_id=proposal_id,
            created_at=created_at,
            user_request=intent.user_request,
            source_diagnosis_ref=intent.source_diagnosis_ref,
            source_context_ref=intent.source_context_ref,
            target_path=intent.target_path,
            related_tests=related_tests,
            action=action,
            proposal_status=proposal_status,
            safety_warnings=_dedupe([*warnings, *reasons]),
            validation={"attempted": False, "status": "not_requested"},
            task_spec_path=None,
            next_actions=[],
            memory_guidance_ref=intent.memory_guidance_ref,
        )

        if proposal_status == "ready":
            task_path = self._task_builder.build_task_spec(
                proposal,
                project_root / ".cambrian" / "tasks",
            )
            proposal.task_spec_path = _relative(task_path, project_root)
            proposal.next_actions = [
                "Review the generated patch TaskSpec",
                "Run cambrian patch propose ... --execute to validate in isolation",
                "Use explicit adoption after validation",
            ]
        else:
            proposal.next_actions = [
                "Check the target file",
                "Use cambrian run \"...\" --use-top-context --execute to diagnose again",
            ]

        if execute and proposal.proposal_status == "ready":
            validation = self._validate_in_isolation(
                proposal=proposal,
                project_root=project_root,
                out_dir=out_dir,
            )
            proposal.validation = validation
            if validation["status"] == "passed":
                proposal.proposal_status = "validated"
                proposal.next_actions = [
                    "Review proposal artifact",
                    "Apply/adopt explicitly when ready",
                    "Revise the patch intent if you want a safer change surface",
                ]
            elif validation["status"] == "failed":
                proposal.proposal_status = "failed"
                proposal.next_actions = [
                    "Revise old_text/new_text and propose again",
                    "Review failing test output before adoption",
                ]
            else:
                proposal.proposal_status = "needs_review"
                proposal.next_actions = [
                    "Review isolated validation output",
                    "Add clearer related tests or revise the patch intent",
                ]

        _dump_yaml(proposal_path, proposal.to_dict())
        return proposal, proposal_path

    def _resolve_related_tests(
        self,
        intent: PatchIntent,
        project_root: Path,
    ) -> tuple[list[str], list[str]]:
        """CLI tests와 diagnosis/context에서 관련 테스트를 모은다."""
        warnings: list[str] = []
        collected = list(intent.related_tests)
        diagnosis_path = intent.source_diagnosis_ref
        if diagnosis_path:
            path = (project_root / diagnosis_path).resolve() if not Path(diagnosis_path).is_absolute() else Path(diagnosis_path)
            if path.exists():
                try:
                    payload = _load_json(path)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    warnings.append(f"diagnosis report 읽기 실패: {exc}")
                else:
                    diagnostics = payload.get("diagnostics", {})
                    if isinstance(diagnostics, dict):
                        collected.extend(str(item) for item in diagnostics.get("related_tests", []))
                    provenance = payload.get("provenance_handoff", {})
                    if isinstance(provenance, dict):
                        collected.extend(str(item) for item in provenance.get("tests_executed", []))
            else:
                warnings.append(f"diagnosis report를 찾지 못했습니다: {diagnosis_path}")
        return _dedupe(collected), warnings

    def _validate_in_isolation(
        self,
        *,
        proposal: PatchProposal,
        project_root: Path,
        out_dir: Path,
    ) -> dict:
        """isolated workspace에서 patch validation을 수행한다."""
        workspace_root = out_dir / "workspaces" / proposal.proposal_id
        if workspace_root.exists():
            shutil.rmtree(workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)

        target_relative = proposal.target_path.replace("\\", "/")
        target_src = (project_root / target_relative).resolve()
        target_dst = (workspace_root / target_relative).resolve()
        target_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_src, target_dst)
        self._copy_package_markers(project_root, workspace_root, Path(target_relative))

        copied_tests: list[str] = []
        for rel in proposal.related_tests:
            src = (project_root / rel).resolve()
            if not src.exists():
                continue
            dst = (workspace_root / rel).resolve()
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            self._copy_package_markers(project_root, workspace_root, Path(rel))
            copied_tests.append(rel)

        for config_name in ("pyproject.toml", "pytest.ini", "conftest.py"):
            src = project_root / config_name
            if src.exists():
                dst = workspace_root / config_name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        executor = ExecutorV1(workspace_root)
        step = executor.execute(
            WorkItem(
                item_id=f"work-{proposal.proposal_id}",
                description=f"validate patch for {proposal.target_path}",
                action=dict(proposal.action),
            )
        )
        if step.status != "success":
            return {
                "attempted": True,
                "status": "failed",
                "workspace_path": _relative(workspace_root, project_root),
                "tests": {
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "exit_code": -1,
                },
                "errors": list(step.errors),
            }

        if not copied_tests:
            return {
                "attempted": True,
                "status": "inconclusive",
                "workspace_path": _relative(workspace_root, project_root),
                "tests": {
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "exit_code": -1,
                },
                "errors": ["related_tests_missing"],
            }

        task_spec = TaskSpec(
            task_id=f"task-validate-{proposal.proposal_id}",
            goal=f"Validate patch proposal for {proposal.target_path}",
            related_files=[proposal.target_path],
            related_tests=copied_tests,
            output_paths=[proposal.target_path],
            actions=[dict(proposal.action)],
        )
        state = RunState(
            run_id=f"validate-{proposal.proposal_id}",
            task_spec=task_spec,
        )
        tester = TesterV1(workspace_root)
        tester_step, detail = tester.run_tests(state)
        status = "passed"
        errors = list(tester_step.errors)
        if tester_step.status == "failure" or detail.failed > 0 or detail.errors > 0:
            status = "failed"
        elif detail.exit_code == TesterV1.NO_TESTS_EXIT_CODE or tester_step.status == "skipped":
            status = "inconclusive"

        return {
            "attempted": True,
            "status": status,
            "workspace_path": _relative(workspace_root, project_root),
            "tests": {
                "passed": detail.passed,
                "failed": detail.failed,
                "skipped": detail.skipped,
                "exit_code": detail.exit_code,
                "tests_executed": list(copied_tests),
            },
            "errors": errors,
        }

    @staticmethod
    def _copy_package_markers(project_root: Path, workspace_root: Path, relative_path: Path) -> None:
        """패키지 import를 위해 __init__.py 체인을 함께 복사한다."""
        for parent in relative_path.parents:
            if str(parent) in {".", ""}:
                continue
            init_src = project_root / parent / "__init__.py"
            if not init_src.exists():
                continue
            init_dst = workspace_root / parent / "__init__.py"
            init_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(init_src, init_dst)


def render_patch_proposal_summary(
    proposal: PatchProposal | dict,
    *,
    proposal_path: str | None = None,
) -> str:
    """patch proposal 결과를 사람이 읽기 쉽게 렌더링한다."""
    from engine.project_errors import hint_for_patch_proposal, render_recovery_hint

    payload = proposal.to_dict() if isinstance(proposal, PatchProposal) else dict(proposal)
    recovery_hint = hint_for_patch_proposal(payload)
    if recovery_hint is not None:
        return render_recovery_hint(recovery_hint, title="Cambrian could not prepare this patch safely.")
    status = str(payload.get("proposal_status", "blocked"))
    validation = payload.get("validation", {}) or {}
    target_path = str(payload.get("target_path", ""))
    related_tests = list(payload.get("related_tests", []))
    if status == "blocked":
        lines = [
            "Cambrian could not prepare this patch safely.",
            "",
            "Reason:",
        ]
        for item in payload.get("safety_warnings", []):
            lines.append(f"  - {item}")
        lines.extend(["", "Next:"])
        for action in payload.get("next_actions", []):
            lines.append(f"  - {action}")
        return "\n".join(lines)

    if validation.get("attempted") and validation.get("status") == "passed":
        tests = validation.get("tests", {})
        return "\n".join([
            "Cambrian validated the patch proposal in isolation.",
            "",
            "Target:",
            f"  {target_path}",
            "",
            "Tests:",
            f"  {tests.get('passed', 0)} passed, {tests.get('failed', 0)} failed",
            "",
            "Status:",
            "  validation passed",
            "",
            "Next:",
            "  - Review proposal artifact",
            "  - Apply/adopt explicitly when ready",
        ])

    lines = [
        "Cambrian prepared a patch proposal.",
        "",
        "Target:",
        f"  {target_path}",
        "",
        "Evidence:",
        f"  diagnosis: {payload.get('source_diagnosis_ref') or 'none'}",
        f"  tests    : {', '.join(related_tests) if related_tests else 'none'}",
        "",
        "Patch:",
        f"  old text found: {'yes' if status in {'ready', 'validated', 'needs_review', 'failed'} else 'no'}",
        f"  status        : {status}",
        "",
        "Created:",
    ]
    if proposal_path:
        lines.append(f"  proposal: {proposal_path}")
    if payload.get("task_spec_path"):
        lines.append(f"  task    : {payload.get('task_spec_path')}")
    lines.extend(["", "Next:"])
    for action in payload.get("next_actions", []):
        lines.append(f"  - {action}")
    return "\n".join(lines)
