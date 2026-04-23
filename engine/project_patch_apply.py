"""Cambrian guided patch apply 모듈."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.brain.adapters.tester_v1 import TesterV1
from engine.brain.models import RunState, TaskSpec
from engine.project_patch import MAX_PATCH_FILE_BYTES, PROTECTED_PATH_PREFIXES

logger = logging.getLogger(__name__)


SCHEMA_VERSION: str = "1.0.0"
ADOPTION_TYPE: str = "patch_proposal"


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _sanitize_target_path(target_path: str) -> str:
    """백업 파일명에 쓸 수 있도록 target path를 평탄화한다."""
    sanitized = target_path.replace("\\", "_").replace("/", "_")
    return sanitized.strip("._") or "target"


def _relative(path: Path, root: Path) -> str:
    """project_root 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _load_yaml_or_json(path: Path) -> dict:
    """YAML 또는 JSON 구조를 dict로 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"structured file 최상위는 dict여야 합니다: {path}")
    return payload


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """바이트 파일을 원자적으로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            logger.exception("임시 파일 삭제 실패: %s", tmp_path)
        raise


def _atomic_write_json(path: Path, payload: dict) -> None:
    """JSON 파일을 원자적으로 저장한다."""
    _atomic_write_bytes(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
    )


def _sha256_text(text: str) -> str:
    """문자열 sha256."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    """파일 sha256."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _is_binary(path: Path) -> bool:
    """바이너리 파일 여부를 거칠게 판별한다."""
    sample = path.read_bytes()[:4096]
    return b"\x00" in sample


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지한 채 중복을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


@dataclass
class PatchApplyResult:
    """Patch proposal apply 결과."""

    status: str
    proposal_id: str | None
    adoption_id: str | None
    adoption_record_path: str | None
    proposal_path: str
    target_path: str | None
    applied_files: list[dict] = field(default_factory=list)
    backup_dir: str | None = None
    post_apply_tests: dict | None = None
    human_reason: str | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class PatchApplyValidator:
    """Patch proposal apply 가능 여부를 검증한다."""

    def __init__(self, adoptions_dir: Path | str | None = None) -> None:
        self._adoptions_dir = Path(adoptions_dir).resolve() if adoptions_dir else None

    def validate(
        self,
        proposal_path: Path,
        project_root: Path,
        require_validated: bool = True,
    ) -> tuple[bool, list[str], dict]:
        """proposal apply 가능 여부와 보조 정보를 반환한다."""
        reasons: list[str] = []
        warnings: list[str] = []
        context: dict = {
            "status": "blocked",
            "proposal": None,
            "proposal_id": None,
            "target_path": None,
            "target_file": None,
            "match_count": 0,
            "related_tests": [],
            "duplicate_record_path": None,
            "duplicate_record": None,
        }

        proposal_path = Path(proposal_path).resolve()
        project_root = Path(project_root).resolve()
        adoptions_dir = self._adoptions_dir or (project_root / ".cambrian" / "adoptions")

        if not proposal_path.exists():
            reasons.append(f"proposal file not found: {proposal_path}")
            return False, reasons, context

        try:
            proposal = _load_yaml_or_json(proposal_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            reasons.append(f"proposal parse failed: {exc}")
            return False, reasons, context

        context["proposal"] = proposal
        context["proposal_id"] = str(proposal.get("proposal_id") or "")

        if not proposal.get("schema_version"):
            reasons.append("schema_version is missing")
        if not context["proposal_id"]:
            reasons.append("proposal_id is missing")

        action = proposal.get("action")
        if not isinstance(action, dict):
            reasons.append("action must be an object")
            action = {}
        if action.get("type") != "patch_file":
            reasons.append("action.type must be patch_file")

        target_path = str(action.get("target_path") or proposal.get("target_path") or "")
        old_text = action.get("old_text")
        new_text = action.get("new_text")
        context["target_path"] = target_path or None

        if not target_path:
            reasons.append("target_path is missing")
        if old_text is None or old_text == "":
            reasons.append("old_text is missing")
        if new_text is None:
            reasons.append("new_text is missing")

        proposal_status = str(proposal.get("proposal_status") or "")
        validation = proposal.get("validation")
        if not isinstance(validation, dict):
            validation = {}
        validation_status = str(validation.get("status") or "")
        validation_attempted = bool(validation.get("attempted", False))

        if proposal_status == "blocked":
            reasons.append("proposal status is blocked")
        if require_validated:
            if not validation_attempted:
                reasons.append("proposal validation has not passed")
            elif validation_status != "passed":
                reasons.append(f"proposal validation status is {validation_status or 'unknown'}")

        rules = self._load_rules(project_root)
        target_file = self._validate_target_path(target_path, project_root, rules)
        if target_file is None:
            reasons.append(f"unsafe target path: {target_path}")
            return False, reasons, context
        context["target_file"] = target_file

        duplicate_path, duplicate_record = self._find_duplicate(
            adoptions_dir=adoptions_dir,
            proposal_id=context["proposal_id"],
        )
        if duplicate_path is not None:
            context["status"] = "duplicate"
            context["duplicate_record_path"] = duplicate_path
            context["duplicate_record"] = duplicate_record
            return False, ["duplicate adoption already exists"], context

        if not target_file.exists():
            reasons.append(f"target file not found: {target_path}")
            return False, reasons, context
        if target_file.stat().st_size > MAX_PATCH_FILE_BYTES:
            reasons.append(f"target file is too large: {target_path}")
            return False, reasons, context
        if _is_binary(target_file):
            reasons.append(f"binary target is not supported: {target_path}")
            return False, reasons, context

        try:
            current_text = target_file.read_text(encoding="utf-8")
        except OSError as exc:
            reasons.append(f"target read failed: {exc}")
            return False, reasons, context

        match_count = current_text.count(str(old_text or ""))
        context["match_count"] = match_count
        if match_count == 0:
            reasons.append(f"old_text was not found in {target_path}")
        elif match_count > 1:
            reasons.append(f"old_text appears multiple times in {target_path}")

        related_tests = self._resolve_related_tests(
            proposal=proposal,
            project_root=project_root,
        )
        context["related_tests"] = related_tests
        if not related_tests:
            reasons.append("related tests are missing")

        context["warnings"] = warnings
        if reasons:
            return False, reasons, context

        context["status"] = "ready"
        return True, reasons, context

    @staticmethod
    def _load_rules(project_root: Path) -> dict | None:
        """rules.yaml을 읽는다."""
        rules_path = project_root / ".cambrian" / "rules.yaml"
        if not rules_path.exists():
            return None
        try:
            payload = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            logger.exception("rules.yaml 읽기 실패: %s", rules_path)
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _validate_target_path(
        target_path: str,
        project_root: Path,
        rules: dict | None = None,
    ) -> Path | None:
        """target path safety를 검증한다."""
        if not target_path:
            return None
        as_path = Path(target_path)
        if as_path.is_absolute() or ".." in as_path.parts:
            return None

        protected = set(PROTECTED_PATH_PREFIXES)
        if isinstance(rules, dict):
            workspace = rules.get("workspace", {})
            if isinstance(workspace, dict):
                for item in workspace.get("protect_paths", []):
                    if isinstance(item, str) and item:
                        protected.add(item.replace("\\", "/").strip("/"))

        normalized = target_path.replace("\\", "/")
        for prefix in protected:
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return None

        candidate = (project_root / as_path).resolve()
        try:
            candidate.relative_to(project_root.resolve())
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _find_duplicate(adoptions_dir: Path, proposal_id: str) -> tuple[Path | None, dict | None]:
        """같은 proposal_id로 생성된 adoption record를 찾는다."""
        if not proposal_id or not adoptions_dir.exists():
            return None, None
        for record_path in sorted(adoptions_dir.glob("adoption_*.json")):
            try:
                payload = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.exception("adoption record 읽기 실패: %s", record_path)
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("adoption_type") != ADOPTION_TYPE:
                continue
            if payload.get("proposal_id") != proposal_id:
                continue
            return record_path, payload
        return None, None

    def _resolve_related_tests(self, proposal: dict, project_root: Path) -> list[str]:
        """proposal과 diagnosis ref에서 related tests를 모은다."""
        collected: list[str] = []
        collected.extend(str(item) for item in proposal.get("related_tests", []) if item)

        validation = proposal.get("validation")
        if isinstance(validation, dict):
            tests = validation.get("tests")
            if isinstance(tests, dict):
                collected.extend(
                    str(item)
                    for item in tests.get("tests_executed", [])
                    if item
                )
            collected.extend(
                str(item)
                for item in validation.get("tests_executed", [])
                if item
            )

        diagnosis_ref = proposal.get("source_diagnosis_ref")
        if isinstance(diagnosis_ref, str) and diagnosis_ref:
            diagnosis_path = Path(diagnosis_ref)
            if not diagnosis_path.is_absolute():
                diagnosis_path = (project_root / diagnosis_ref).resolve()
            if diagnosis_path.exists():
                try:
                    report = json.loads(diagnosis_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    logger.exception("diagnosis report 읽기 실패: %s", diagnosis_path)
                else:
                    if isinstance(report, dict):
                        diagnostics = report.get("diagnostics", {})
                        if isinstance(diagnostics, dict):
                            collected.extend(
                                str(item)
                                for item in diagnostics.get("related_tests", [])
                                if item
                            )
        return _dedupe(collected)


class PatchApplier:
    """검증된 proposal을 실제 프로젝트에 적용한다."""

    def apply(
        self,
        proposal_path: Path,
        project_root: Path,
        adoptions_dir: Path,
        reason: str,
        dry_run: bool = False,
    ) -> PatchApplyResult:
        """proposal을 실제 프로젝트에 적용하고 adoption record를 남긴다."""
        project_root = Path(project_root).resolve()
        adoptions_dir = Path(adoptions_dir).resolve()
        proposal_path = Path(proposal_path).resolve()

        if not reason.strip():
            return PatchApplyResult(
                status="blocked",
                proposal_id=None,
                adoption_id=None,
                adoption_record_path=None,
                proposal_path=_relative(proposal_path, project_root),
                target_path=None,
                reasons=["human reason is required"],
            )

        validator = PatchApplyValidator(adoptions_dir=adoptions_dir)
        valid, reasons, context = validator.validate(
            proposal_path=proposal_path,
            project_root=project_root,
            require_validated=True,
        )
        proposal = context.get("proposal") or {}
        proposal_id = context.get("proposal_id")
        target_path = context.get("target_path")
        proposal_rel = _relative(proposal_path, project_root)

        if context.get("status") == "duplicate":
            duplicate_record = context.get("duplicate_record") or {}
            duplicate_path = context.get("duplicate_record_path")
            return PatchApplyResult(
                status="duplicate",
                proposal_id=proposal_id,
                adoption_id=str(duplicate_record.get("adoption_id") or ""),
                adoption_record_path=(
                    _relative(Path(duplicate_path), project_root)
                    if duplicate_path is not None
                    else None
                ),
                proposal_path=proposal_rel,
                target_path=target_path,
                applied_files=[],
                backup_dir=None,
                post_apply_tests=None,
                human_reason=reason,
                reasons=["duplicate adoption already exists"],
            )

        if not valid:
            return PatchApplyResult(
                status="blocked",
                proposal_id=proposal_id,
                adoption_id=None,
                adoption_record_path=None,
                proposal_path=proposal_rel,
                target_path=target_path,
                applied_files=[],
                backup_dir=None,
                post_apply_tests=None,
                human_reason=reason,
                reasons=reasons,
            )

        related_tests = list(context.get("related_tests", []))
        old_text_matches = int(context.get("match_count", 0) or 0)

        if dry_run:
            return PatchApplyResult(
                status="dry_run",
                proposal_id=proposal_id,
                adoption_id=None,
                adoption_record_path=None,
                proposal_path=proposal_rel,
                target_path=target_path,
                applied_files=[],
                backup_dir=None,
                post_apply_tests={
                    "would_run": True,
                    "tests_executed": related_tests,
                    "old_text_matches": old_text_matches,
                },
                human_reason=reason,
                reasons=[],
            )

        target_file = Path(context["target_file"])
        action = dict(proposal.get("action") or {})
        old_text = str(action.get("old_text") or "")
        new_text = str(action.get("new_text") or "")
        adoption_id = self._generate_adoption_id()
        backup_dir = adoptions_dir / "backups" / adoption_id

        applied_record: dict | None = None
        try:
            applied_record = self._apply_target_file(
                target_file=target_file,
                target_path=str(target_path),
                old_text=old_text,
                new_text=new_text,
                backup_dir=backup_dir,
            )
        except Exception as exc:
            logger.exception("patch apply file write failed")
            return PatchApplyResult(
                status="failed",
                proposal_id=proposal_id,
                adoption_id=adoption_id,
                adoption_record_path=None,
                proposal_path=proposal_rel,
                target_path=target_path,
                applied_files=[],
                backup_dir=_relative(backup_dir, project_root),
                post_apply_tests=None,
                human_reason=reason,
                reasons=[str(exc)],
                errors=[str(exc)],
            )

        post_apply_tests = self._run_post_apply_tests(
            project_root=project_root,
            proposal_id=str(proposal_id or ""),
            related_tests=related_tests,
        )
        if not self._post_apply_passed(post_apply_tests):
            restore_errors = self._restore_target(applied_record)
            reasons = ["post-apply tests failed", *restore_errors]
            return PatchApplyResult(
                status="failed",
                proposal_id=proposal_id,
                adoption_id=adoption_id,
                adoption_record_path=None,
                proposal_path=proposal_rel,
                target_path=target_path,
                applied_files=[applied_record],
                backup_dir=_relative(backup_dir, project_root),
                post_apply_tests=post_apply_tests,
                human_reason=reason,
                reasons=reasons,
                errors=restore_errors,
            )

        record = self._build_adoption_record(
            proposal=proposal,
            proposal_path=proposal_path,
            project_root=project_root,
            adoption_id=adoption_id,
            reason=reason,
            applied_files=[applied_record],
            backup_dir=backup_dir,
            post_apply_tests=post_apply_tests,
        )
        adoptions_dir.mkdir(parents=True, exist_ok=True)
        record_path = adoptions_dir / self._record_filename(proposal_id or "unknown")
        latest_path = adoptions_dir / "_latest.json"

        try:
            _atomic_write_json(record_path, record)
            _atomic_write_json(
                latest_path,
                {
                    "latest_adoption_id": adoption_id,
                    "latest_adoption_path": _relative(record_path, project_root),
                    "adoption_type": ADOPTION_TYPE,
                    "proposal_id": proposal_id,
                    "target_path": target_path,
                    "human_reason": reason,
                    "updated_at": record["created_at"],
                },
            )
        except Exception as exc:
            logger.exception("adoption record/latest write failed")
            restore_errors = self._restore_target(applied_record)
            if record_path.exists():
                try:
                    record_path.unlink()
                except OSError as delete_exc:
                    restore_errors.append(f"partial record cleanup failed: {delete_exc}")
            return PatchApplyResult(
                status="failed",
                proposal_id=proposal_id,
                adoption_id=adoption_id,
                adoption_record_path=None,
                proposal_path=proposal_rel,
                target_path=target_path,
                applied_files=[applied_record],
                backup_dir=_relative(backup_dir, project_root),
                post_apply_tests=post_apply_tests,
                human_reason=reason,
                reasons=[f"failed to persist adoption record: {exc}", *restore_errors],
                errors=restore_errors,
            )

        return PatchApplyResult(
            status="applied",
            proposal_id=proposal_id,
            adoption_id=adoption_id,
            adoption_record_path=_relative(record_path, project_root),
            proposal_path=proposal_rel,
            target_path=target_path,
            applied_files=[applied_record],
            backup_dir=_relative(backup_dir, project_root),
            post_apply_tests=post_apply_tests,
            human_reason=reason,
            reasons=[],
        )

    @staticmethod
    def _generate_adoption_id() -> str:
        """고유 adoption_id를 생성한다."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"adoption-{stamp}-{secrets.token_hex(2)}"

    def _apply_target_file(
        self,
        *,
        target_file: Path,
        target_path: str,
        old_text: str,
        new_text: str,
        backup_dir: Path,
    ) -> dict:
        """대상 파일에 patch를 적용하고 backup/hashes를 기록한다."""
        before_text = target_file.read_text(encoding="utf-8")
        before_sha256 = _sha256_file(target_file)

        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{_sanitize_target_path(target_path)}.bak"
        _atomic_write_bytes(backup_path, target_file.read_bytes())

        updated_text = before_text.replace(old_text, new_text, 1)
        _atomic_write_bytes(target_file, updated_text.encode("utf-8"))
        after_sha256 = _sha256_file(target_file)

        return {
            "target_path": target_path,
            "target_file_path": str(target_file),
            "existed_before": True,
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "backup_path": str(backup_path),
            "old_text_sha256": _sha256_text(old_text),
            "new_text_sha256": _sha256_text(new_text),
        }

    def _run_post_apply_tests(
        self,
        *,
        project_root: Path,
        proposal_id: str,
        related_tests: list[str],
    ) -> dict:
        """실제 프로젝트 워크스페이스에서 related tests를 다시 실행한다."""
        task_spec = TaskSpec(
            task_id=f"task-apply-{proposal_id}",
            goal="Verify applied patch proposal",
            related_tests=list(related_tests),
        )
        run_state = RunState(
            run_id=f"apply-{proposal_id}",
            task_spec=task_spec,
        )
        tester = TesterV1(project_root)
        step, detail = tester.run_tests(run_state)
        return {
            "passed": detail.passed,
            "failed": detail.failed,
            "skipped": detail.skipped,
            "exit_code": detail.exit_code,
            "tests_executed": list(detail.test_files),
            "status": step.status,
            "summary": step.summary,
        }

    @staticmethod
    def _post_apply_passed(post_apply_tests: dict) -> bool:
        """post-apply test 성공 여부."""
        raw_exit_code = post_apply_tests.get("exit_code", -1)
        exit_code = int(raw_exit_code if raw_exit_code is not None else -1)
        raw_failed = post_apply_tests.get("failed", 0)
        failed = int(raw_failed if raw_failed is not None else 0)
        return exit_code == 0 and failed == 0

    @staticmethod
    def _restore_target(applied_record: dict) -> list[str]:
        """backup으로 원본 파일을 복구한다."""
        errors: list[str] = []
        target_path = Path(str(applied_record.get("target_file_path", "")))
        backup_path = applied_record.get("backup_path")
        try:
            if not backup_path:
                raise ValueError("backup_path is missing")
            _atomic_write_bytes(target_path, Path(str(backup_path)).read_bytes())
        except Exception as exc:
            errors.append(f"restore failed for {target_path}: {exc}")
        return errors

    def _build_adoption_record(
        self,
        *,
        proposal: dict,
        proposal_path: Path,
        project_root: Path,
        adoption_id: str,
        reason: str,
        applied_files: list[dict],
        backup_dir: Path,
        post_apply_tests: dict,
    ) -> dict:
        """official adoption record를 생성한다."""
        return {
            "schema_version": SCHEMA_VERSION,
            "adoption_id": adoption_id,
            "adoption_type": ADOPTION_TYPE,
            "created_at": _now(),
            "proposal_id": proposal.get("proposal_id"),
            "source_proposal_path": _relative(proposal_path, project_root),
            "source_diagnosis_ref": proposal.get("source_diagnosis_ref"),
            "source_context_ref": proposal.get("source_context_ref"),
            "source_task_spec_path": proposal.get("task_spec_path"),
            "target_path": proposal.get("target_path"),
            "human_reason": reason,
            "proposal": {
                "proposal_status": proposal.get("proposal_status"),
                "validation_status": (proposal.get("validation") or {}).get("status"),
            },
            "post_apply_tests": post_apply_tests,
            "applied_files": applied_files,
            "backup_dir": _relative(backup_dir, project_root),
            "adoption_status": "adopted",
            "provenance": {
                "source": "patch_proposal",
                "file_first": True,
                "verified_before_apply": True,
                "verified_after_apply": True,
            },
        }

    @staticmethod
    def _record_filename(proposal_id: str) -> str:
        """adoption record 파일명을 만든다."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"adoption_{stamp}_{proposal_id}.json"


def render_patch_apply_summary(result: PatchApplyResult | dict) -> str:
    """patch apply 결과를 사람이 읽기 쉽게 렌더링한다."""
    from engine.project_errors import hint_for_patch_apply, render_recovery_hint

    payload = result.to_dict() if isinstance(result, PatchApplyResult) else dict(result)
    recovery_hint = hint_for_patch_apply(payload)
    if recovery_hint is not None:
        return render_recovery_hint(recovery_hint, title="[PATCH APPLY] blocked")
    status = str(payload.get("status", "blocked"))
    proposal_id = str(payload.get("proposal_id") or "(unknown)")
    target_path = str(payload.get("target_path") or "(unknown)")
    post_apply_tests = payload.get("post_apply_tests") or {}

    if status == "dry_run":
        tests = list(post_apply_tests.get("tests_executed", []))
        lines = [
            "[PATCH APPLY] dry-run",
            "",
            "Would apply:",
            f"  target : {target_path}",
            f"  old_text matches: {post_apply_tests.get('old_text_matches', 0)}",
            "",
            "Would run tests:",
        ]
        if tests:
            for item in tests:
                lines.append(f"  - {item}")
        else:
            lines.append("  - (none)")
        lines.extend([
            "",
            "Would create:",
            "  adoption record",
            "  latest pointer update",
            "",
            "Next:",
            "  - Review the proposal one more time",
            "  - Run the same command without --dry-run when ready",
            "",
            "No files changed.",
        ])
        return "\n".join(lines)

    if status == "duplicate":
        return "\n".join([
            "[PATCH APPLY] duplicate",
            "",
            "This proposal was already adopted.",
            "",
            "Created:",
            f"  record : {payload.get('adoption_record_path') or '(unknown)'}",
            "",
            "Next:",
            "  - Run cambrian status to review the latest project memory",
            "",
            "No files changed.",
        ])

    if status == "applied":
        return "\n".join([
            "[PATCH APPLY] adopted",
            "",
            "Proposal:",
            f"  {proposal_id}",
            "",
            "Applied:",
            f"  {target_path}",
            "",
            "Tests:",
            f"  {post_apply_tests.get('passed', 0)} passed, {post_apply_tests.get('failed', 0)} failed",
            "",
            "Created:",
            f"  record : {payload.get('adoption_record_path') or '(unknown)'}",
            "  latest : updated",
            "",
            "Reason:",
            f"  {payload.get('human_reason') or ''}",
            "",
            "Next:",
            "  - Run cambrian status to review the updated journey",
            "  - Continue with cambrian run \"<next request>\"",
        ])

    if status == "failed":
        return "\n".join([
            "[PATCH APPLY] failed",
            "",
            "Applied patch did not pass post-apply tests.",
            "Restored original files.",
            "",
            "Tests:",
            f"  {post_apply_tests.get('passed', 0)} passed, {post_apply_tests.get('failed', 0)} failed",
            "",
            "Latest:",
            "  not changed",
            "",
            "Next:",
            "  - Review the failing test output",
            "  - Revise the patch proposal and validate again",
        ])

    lines = [
        "[PATCH APPLY] blocked",
        "",
        "Proposal:",
        f"  {proposal_id}",
        "",
        "Reasons:",
    ]
    for reason in payload.get("reasons", []):
        lines.append(f"  - {reason}")
    lines.extend([
        "",
        "Next:",
        "  - Fix the blocked condition or re-run diagnosis",
        "  - Validate the proposal before apply",
        "",
        "No files changed.",
    ])
    return "\n".join(lines)
