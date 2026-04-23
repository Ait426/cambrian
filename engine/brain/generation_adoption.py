"""Cambrian brain generation winner adoption integration."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from engine.brain.adapters.tester_v1 import TesterV1
from engine.brain.models import RunState, TaskSpec

logger = logging.getLogger(__name__)


SCHEMA_VERSION: str = "1.0.0"
ADOPTION_TYPE: str = "brain_generation"


@dataclass
class GenerationAdoptionValidation:
    """Generation adoption 검증 결과."""

    status: str
    brain_run_id: str | None
    winner_variant_id: str | None
    runs_dir: Path
    run_dir: Path | None
    project_root: Path
    out_dir: Path
    report_path: Path | None = None
    run_state_path: Path | None = None
    task_spec_path: Path | None = None
    report: dict | None = None
    run_state: dict | None = None
    task_spec: TaskSpec | None = None
    competitive_generation: dict | None = None
    winner_variant: dict | None = None
    winner_result_path: Path | None = None
    winner_result: dict | None = None
    winner_workspace_path: Path | None = None
    target_paths: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_record_path: Path | None = None
    duplicate_record: dict | None = None


@dataclass
class GenerationAdoptionResult:
    """Generation winner adoption 결과."""

    status: str
    adoption_record_path: str | None
    adoption_id: str | None
    brain_run_id: str | None
    winner_variant_id: str | None
    applied_files: list[str] = field(default_factory=list)
    backup_dir: str | None = None
    post_apply_tests: dict = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON 직렬화용 dict."""
        return {
            "status": self.status,
            "adoption_record_path": self.adoption_record_path,
            "adoption_id": self.adoption_id,
            "brain_run_id": self.brain_run_id,
            "winner_variant_id": self.winner_variant_id,
            "applied_files": list(self.applied_files),
            "backup_dir": self.backup_dir,
            "post_apply_tests": dict(self.post_apply_tests),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
        }


class GenerationAdoptionValidator:
    """competitive generation winner 채택 가능 여부를 검증한다."""

    def validate(
        self,
        run_id_or_report: str,
        runs_dir: Path | str,
        project_root: Path | str,
        out_dir: Path | str,
    ) -> GenerationAdoptionValidation:
        """brain run과 winner variant를 검증한다."""
        runs_root = Path(runs_dir)
        workspace_root = Path(project_root).resolve()
        adoption_root = Path(out_dir)

        report_path_hint = Path(run_id_or_report)
        if report_path_hint.exists() and report_path_hint.is_file():
            report_path = report_path_hint.resolve()
            run_dir = report_path.parent
            brain_run_id = run_dir.name
        else:
            brain_run_id = str(run_id_or_report)
            run_dir = runs_root / brain_run_id
            report_path = run_dir / "report.json"

        validation = GenerationAdoptionValidation(
            status="blocked",
            brain_run_id=brain_run_id,
            winner_variant_id=None,
            runs_dir=runs_root,
            run_dir=run_dir,
            project_root=workspace_root,
            out_dir=adoption_root,
            report_path=report_path,
            run_state_path=run_dir / "run_state.json",
            task_spec_path=run_dir / "task_spec.yaml",
        )

        if not run_dir.exists():
            validation.reasons.append(f"run directory not found: {run_dir}")
            return validation

        report = self._load_json(validation.report_path, validation.reasons, "report")
        run_state = self._load_json(
            validation.run_state_path,
            validation.reasons,
            "run_state",
        )
        if not validation.task_spec_path.exists():
            validation.reasons.append(
                f"task_spec file not found: {validation.task_spec_path}"
            )
            return validation

        if report is None or run_state is None:
            return validation

        validation.report = report
        validation.run_state = run_state

        try:
            task_spec = TaskSpec.from_yaml(validation.task_spec_path)
        except (FileNotFoundError, ValueError) as exc:
            validation.reasons.append(f"task_spec parse failed: {exc}")
            return validation
        validation.task_spec = task_spec

        competitive = report.get("competitive_generation")
        if not isinstance(competitive, dict):
            validation.reasons.append("competitive_generation missing in report")
            return validation
        validation.competitive_generation = competitive

        if not bool(competitive.get("enabled", False)):
            validation.reasons.append("competitive_generation.enabled is false")
        if competitive.get("status") != "success":
            validation.reasons.append(
                f"competitive_generation.status is {competitive.get('status')}"
            )

        winner_variant_id = competitive.get("winner_variant_id")
        if not isinstance(winner_variant_id, str) or not winner_variant_id.strip():
            validation.reasons.append("winner_variant_id missing")
            return validation
        validation.winner_variant_id = winner_variant_id

        winner_variant = None
        for variant in competitive.get("variants", []) or []:
            if isinstance(variant, dict) and variant.get("variant_id") == winner_variant_id:
                winner_variant = variant
                break
        if winner_variant is None:
            validation.reasons.append("winner variant not found in report")
            return validation
        validation.winner_variant = winner_variant

        validation.winner_result_path = (
            run_dir / "variants" / winner_variant_id / "result.json"
        )
        validation.winner_result = self._load_json(
            validation.winner_result_path,
            validation.reasons,
            "winner_result",
        )
        if validation.winner_result is None:
            return validation

        validation.winner_workspace_path = self._resolve_winner_workspace(
            run_dir=run_dir,
            winner_variant_id=winner_variant_id,
            winner_result=validation.winner_result,
        )
        if validation.winner_workspace_path is None or not validation.winner_workspace_path.exists():
            validation.reasons.append("winner workspace missing")
            return validation

        self._validate_winner_eligibility(validation)
        if validation.reasons:
            return validation

        duplicate_path, duplicate_record = self._find_duplicate(
            adoption_root,
            validation.brain_run_id or "",
            winner_variant_id,
        )
        if duplicate_path is not None:
            validation.status = "duplicate"
            validation.duplicate_record_path = duplicate_path
            validation.duplicate_record = duplicate_record
            return validation

        validation.status = "ready"
        return validation

    @staticmethod
    def _load_json(
        path: Path | None,
        reasons: list[str],
        label: str,
    ) -> dict | None:
        """JSON object를 안전하게 로드한다."""
        if path is None or not path.exists():
            reasons.append(f"{label} file not found: {path}")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reasons.append(f"{label} parse failed: {exc}")
            return None
        if not isinstance(payload, dict):
            reasons.append(f"{label} must be a JSON object")
            return None
        return payload

    @staticmethod
    def _resolve_winner_workspace(
        run_dir: Path,
        winner_variant_id: str,
        winner_result: dict,
    ) -> Path | None:
        """winner workspace 경로를 결정한다."""
        raw = winner_result.get("workspace_path")
        candidates: list[Path] = []
        if isinstance(raw, str) and raw.strip():
            path = Path(raw)
            if path.is_absolute():
                candidates.append(path)
            else:
                candidates.append((Path.cwd() / path).resolve())
                candidates.append((run_dir / raw).resolve())
        candidates.append((run_dir / "variants" / winner_variant_id / "workspace").resolve())

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[-1]

    def _validate_winner_eligibility(
        self,
        validation: GenerationAdoptionValidation,
    ) -> None:
        """winner eligibility rule을 검증한다."""
        winner_result = validation.winner_result or {}
        task_spec = validation.task_spec
        report = validation.report or {}

        if winner_result.get("status") != "success":
            validation.reasons.append(
                f"winner variant status is {winner_result.get('status')}"
            )
        if not bool(winner_result.get("reviewer_passed", False)):
            validation.reasons.append("winner reviewer_passed is false")

        test_results = winner_result.get("test_results")
        if not isinstance(test_results, dict):
            validation.reasons.append("winner test_results missing")
        elif int(test_results.get("failed", 0) or 0) != 0:
            validation.reasons.append("winner test_results.failed is non-zero")

        hypothesis_status = winner_result.get("hypothesis_status")
        has_hypothesis = bool(task_spec and task_spec.hypothesis)
        if has_hypothesis:
            if hypothesis_status == "supported":
                pass
            elif hypothesis_status == "contradicted":
                validation.reasons.append("winner hypothesis contradicted")
            elif hypothesis_status == "inconclusive":
                validation.reasons.append("winner hypothesis inconclusive")
            else:
                validation.reasons.append(
                    f"winner hypothesis status is {hypothesis_status or 'unavailable'}"
                )
        else:
            if hypothesis_status not in (None, "skipped", "unavailable"):
                if hypothesis_status in {"contradicted", "inconclusive", "error"}:
                    validation.reasons.append(
                        f"winner hypothesis status is {hypothesis_status}"
                    )
            else:
                validation.warnings.append(
                    "winner has no hypothesis evidence because no hypothesis was provided"
                )

        target_paths = self._unique_paths(
            list(winner_result.get("files_created") or [])
            + list(winner_result.get("files_modified") or [])
        )
        if not target_paths:
            validation.reasons.append("winner has no files_created or files_modified")
            return

        safe_paths: list[str] = []
        for raw_path in target_paths:
            try:
                safe_rel = self._validate_target_path(
                    raw_path,
                    validation.project_root,
                    validation.winner_workspace_path,
                )
            except ValueError as exc:
                validation.reasons.append(str(exc))
                continue
            safe_paths.append(safe_rel)
        validation.target_paths = safe_paths

        hypothesis_eval = report.get("hypothesis_evaluation")
        if isinstance(hypothesis_eval, dict) and has_hypothesis:
            status = hypothesis_eval.get("status")
            if status == "contradicted":
                validation.reasons.append("report hypothesis_evaluation is contradicted")

    @staticmethod
    def _unique_paths(paths: list[str]) -> list[str]:
        """경로 목록을 순서 유지로 dedupe한다."""
        result: list[str] = []
        seen: set[str] = set()
        for path in paths:
            if not isinstance(path, str):
                continue
            if path not in seen:
                seen.add(path)
                result.append(path)
        return result

    @staticmethod
    def _validate_target_path(
        raw_path: str,
        project_root: Path,
        winner_workspace_path: Path | None,
    ) -> str:
        """target path 안전성을 검증한다."""
        path = Path(raw_path)
        if path.is_absolute():
            raise ValueError(f"unsafe target path: absolute path not allowed: {raw_path}")
        if ".." in path.parts:
            raise ValueError(f"unsafe target path: '..' not allowed: {raw_path}")

        target = (project_root / path).resolve()
        try:
            target.relative_to(project_root)
        except ValueError as exc:
            raise ValueError(
                f"unsafe target path escaped project root: {raw_path}"
            ) from exc

        if winner_workspace_path is not None:
            source = (winner_workspace_path / path).resolve()
            try:
                source.relative_to(winner_workspace_path.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"unsafe source path escaped winner workspace: {raw_path}"
                ) from exc
            if not source.exists():
                raise ValueError(f"winner source file missing: {raw_path}")
            if source.is_dir():
                raise ValueError(f"winner source path must be a file: {raw_path}")
            if source.is_symlink():
                raise ValueError(f"winner source symlink is not allowed: {raw_path}")

        if target.exists():
            if target.is_dir():
                raise ValueError(f"target path must be a file: {raw_path}")
            if target.is_symlink():
                raise ValueError(f"target symlink is not allowed: {raw_path}")

        return raw_path

    @staticmethod
    def _find_duplicate(
        out_dir: Path,
        brain_run_id: str,
        winner_variant_id: str,
    ) -> tuple[Path | None, dict | None]:
        """같은 brain_run_id + winner_variant_id 조합의 기존 adoption을 찾는다."""
        if not out_dir.exists():
            return None, None
        for path in sorted(out_dir.glob("adoption_*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if data.get("adoption_type") != ADOPTION_TYPE:
                continue
            if data.get("brain_run_id") != brain_run_id:
                continue
            if data.get("winner_variant_id") != winner_variant_id:
                continue
            return path, data
        return None, None


class GenerationAdoptionApplier:
    """검증된 winner를 실제 workspace에 적용한다."""

    def apply(
        self,
        validation: GenerationAdoptionValidation,
        reason: str,
        dry_run: bool = False,
    ) -> GenerationAdoptionResult:
        """winner를 실제 workspace에 적용한다."""
        if validation.status == "duplicate":
            duplicate_record = validation.duplicate_record or {}
            return GenerationAdoptionResult(
                status="duplicate",
                adoption_record_path=(
                    str(validation.duplicate_record_path)
                    if validation.duplicate_record_path is not None
                    else None
                ),
                adoption_id=(
                    str(duplicate_record.get("adoption_id"))
                    if duplicate_record.get("adoption_id") is not None
                    else None
                ),
                brain_run_id=validation.brain_run_id,
                winner_variant_id=validation.winner_variant_id,
                applied_files=list(validation.target_paths),
                backup_dir=str(validation.out_dir / "backups"),
                post_apply_tests={},
                reasons=["duplicate adoption already exists"],
                warnings=list(validation.warnings),
            )

        if validation.status != "ready":
            return GenerationAdoptionResult(
                status="blocked",
                adoption_record_path=None,
                adoption_id=None,
                brain_run_id=validation.brain_run_id,
                winner_variant_id=validation.winner_variant_id,
                applied_files=list(validation.target_paths),
                backup_dir=None,
                post_apply_tests={},
                reasons=list(validation.reasons),
                warnings=list(validation.warnings),
            )

        if dry_run:
            return GenerationAdoptionResult(
                status="dry_run",
                adoption_record_path=None,
                adoption_id=None,
                brain_run_id=validation.brain_run_id,
                winner_variant_id=validation.winner_variant_id,
                applied_files=list(validation.target_paths),
                backup_dir=None,
                post_apply_tests={
                    "tests_executed": list(validation.task_spec.related_tests or [])
                    if validation.task_spec is not None
                    else [],
                },
                reasons=[],
                warnings=list(validation.warnings),
            )

        adoption_id = self._generate_adoption_id()
        applied_file_records: list[dict] = []
        backup_dir = validation.out_dir / "backups" / adoption_id

        try:
            for rel_path in validation.target_paths:
                applied_file_records.append(
                    self._apply_single_file(
                        rel_path=rel_path,
                        winner_workspace_path=validation.winner_workspace_path,
                        project_root=validation.project_root,
                        backup_dir=backup_dir,
                    )
                )
        except Exception as exc:
            logger.exception("generation adoption file apply failed")
            restore_errors = self._restore_files(applied_file_records, validation.project_root)
            reasons = [str(exc)] + restore_errors
            return GenerationAdoptionResult(
                status="failed",
                adoption_record_path=None,
                adoption_id=adoption_id,
                brain_run_id=validation.brain_run_id,
                winner_variant_id=validation.winner_variant_id,
                applied_files=[record["target_path"] for record in applied_file_records],
                backup_dir=str(backup_dir),
                post_apply_tests={},
                reasons=reasons,
                warnings=list(validation.warnings),
            )

        post_apply_tests = self._run_post_apply_tests(
            validation.task_spec,
            validation.project_root,
            validation.brain_run_id or "",
        )
        if not self._post_apply_passed(post_apply_tests):
            restore_errors = self._restore_files(
                applied_file_records,
                validation.project_root,
            )
            reasons = ["post-apply tests failed"] + restore_errors
            return GenerationAdoptionResult(
                status="failed",
                adoption_record_path=None,
                adoption_id=adoption_id,
                brain_run_id=validation.brain_run_id,
                winner_variant_id=validation.winner_variant_id,
                applied_files=[record["target_path"] for record in applied_file_records],
                backup_dir=str(backup_dir),
                post_apply_tests=post_apply_tests,
                reasons=reasons,
                warnings=list(validation.warnings),
            )

        record = self._build_adoption_record(
            validation=validation,
            adoption_id=adoption_id,
            reason=reason,
            applied_file_records=applied_file_records,
            post_apply_tests=post_apply_tests,
            backup_dir=backup_dir,
        )
        validation.out_dir.mkdir(parents=True, exist_ok=True)
        record_path = validation.out_dir / self._build_record_filename(
            validation.brain_run_id or "unknown",
            validation.winner_variant_id or "unknown",
        )
        latest_path = validation.out_dir / "_latest.json"

        try:
            self._atomic_write_json(record_path, record)
            latest = {
                "latest_adoption": record_path.name,
                "latest_adoption_id": adoption_id,
                "latest_adoption_path": str(record_path),
                "adoption_type": ADOPTION_TYPE,
                "brain_run_id": validation.brain_run_id,
                "run_id": validation.brain_run_id,
                "winner_variant_id": validation.winner_variant_id,
                "updated_at": record["created_at"],
                "timestamp": record["created_at"],
                "action": "adoption",
            }
            self._atomic_write_json(latest_path, latest)
        except Exception as exc:
            logger.exception("generation adoption record/latest write failed")
            restore_errors = self._restore_files(
                applied_file_records,
                validation.project_root,
            )
            try:
                if record_path.exists():
                    record_path.unlink()
            except OSError as delete_exc:
                restore_errors.append(f"failed to remove partial record: {delete_exc}")
            reasons = [f"failed to persist adoption record: {exc}"] + restore_errors
            return GenerationAdoptionResult(
                status="failed",
                adoption_record_path=None,
                adoption_id=adoption_id,
                brain_run_id=validation.brain_run_id,
                winner_variant_id=validation.winner_variant_id,
                applied_files=[record["target_path"] for record in applied_file_records],
                backup_dir=str(backup_dir),
                post_apply_tests=post_apply_tests,
                reasons=reasons,
                warnings=list(validation.warnings),
            )

        return GenerationAdoptionResult(
            status="adopted",
            adoption_record_path=str(record_path),
            adoption_id=adoption_id,
            brain_run_id=validation.brain_run_id,
            winner_variant_id=validation.winner_variant_id,
            applied_files=[record["target_path"] for record in applied_file_records],
            backup_dir=str(backup_dir),
            post_apply_tests=post_apply_tests,
            reasons=[],
            warnings=list(validation.warnings),
        )

    @staticmethod
    def _generate_adoption_id() -> str:
        """고유 adoption_id를 생성한다."""
        dt = datetime.now(timezone.utc)
        return f"adoption-{dt.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"

    def _apply_single_file(
        self,
        rel_path: str,
        winner_workspace_path: Path | None,
        project_root: Path,
        backup_dir: Path,
    ) -> dict:
        """단일 파일을 적용한다."""
        if winner_workspace_path is None:
            raise ValueError("winner workspace path is missing")

        source = (winner_workspace_path / rel_path).resolve()
        target = (project_root / rel_path).resolve()

        existed_before = target.exists()
        before_sha256 = self._sha256_file(target) if existed_before else None
        backup_path = None

        if existed_before:
            backup_target = backup_dir / rel_path
            backup_target.parent.mkdir(parents=True, exist_ok=True)
            self._copy_file(source_path=target, target_path=backup_target)
            backup_path = str(backup_target)

        target.parent.mkdir(parents=True, exist_ok=True)
        self._copy_file(source_path=source, target_path=target)
        after_sha256 = self._sha256_file(target)

        return {
            "target_path": rel_path,
            "source_variant_file_path": str(source),
            "existed_before": existed_before,
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "backup_path": backup_path,
        }

    def _run_post_apply_tests(
        self,
        task_spec: TaskSpec | None,
        project_root: Path,
        brain_run_id: str,
    ) -> dict:
        """project_root에서 post-apply pytest를 다시 실행한다."""
        if task_spec is None:
            return {
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "exit_code": -1,
                "tests_executed": [],
                "status": "failure",
                "summary": "task_spec missing",
            }

        tester = TesterV1(project_root)
        run_state = RunState(
            run_id=brain_run_id,
            task_spec=task_spec,
        )
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
        exit_code = int(post_apply_tests.get("exit_code", -1) or -1)
        failed = int(post_apply_tests.get("failed", 0) or 0)
        return exit_code in (0, 5) and failed == 0

    def _build_adoption_record(
        self,
        validation: GenerationAdoptionValidation,
        adoption_id: str,
        reason: str,
        applied_file_records: list[dict],
        post_apply_tests: dict,
        backup_dir: Path,
    ) -> dict:
        """official adoption record를 생성한다."""
        created_at = datetime.now(timezone.utc).isoformat()
        report = validation.report or {}
        competitive = validation.competitive_generation or {}
        hypothesis = report.get("hypothesis_evaluation") or {}
        selection_reason = str(competitive.get("selection_reason", ""))

        return {
            "schema_version": SCHEMA_VERSION,
            "action_type": "adoption",
            "adoption_id": adoption_id,
            "adoption_type": ADOPTION_TYPE,
            "created_at": created_at,
            "timestamp": created_at,
            "run_id": validation.brain_run_id,
            "brain_run_id": validation.brain_run_id,
            "winner_variant_id": validation.winner_variant_id,
            "task_id": validation.task_spec.task_id if validation.task_spec else None,
            "source_report_path": str(validation.report_path) if validation.report_path else None,
            "source_run_state_path": (
                str(validation.run_state_path) if validation.run_state_path else None
            ),
            "source_task_spec_path": (
                str(validation.task_spec_path) if validation.task_spec_path else None
            ),
            "source_variant_result_path": (
                str(validation.winner_result_path) if validation.winner_result_path else None
            ),
            "source_variant_workspace_path": (
                str(validation.winner_workspace_path)
                if validation.winner_workspace_path is not None
                else None
            ),
            "human_reason": reason,
            "competitive_generation": {
                "winner_variant_id": validation.winner_variant_id,
                "selection_reason": selection_reason,
                "status": competitive.get("status"),
            },
            "hypothesis_evaluation": {
                "status": hypothesis.get("status"),
                "hypothesis_id": hypothesis.get("hypothesis_id"),
                "statement": hypothesis.get("statement"),
            },
            "post_apply_tests": post_apply_tests,
            "applied_files": applied_file_records,
            "backup_dir": str(backup_dir),
            "adoption_status": "adopted",
            "warnings": list(validation.warnings),
            "provenance": {
                "source": "brain_competitive_generation",
                "stable_ref": validation.brain_run_id,
                "selection_reason": selection_reason,
                "file_first": True,
            },
        }

    def _restore_files(
        self,
        applied_file_records: list[dict],
        project_root: Path,
    ) -> list[str]:
        """적용한 파일을 backup 기준으로 복구한다."""
        restore_errors: list[str] = []
        for record in reversed(applied_file_records):
            rel_path = str(record["target_path"])
            target = (project_root / rel_path).resolve()
            try:
                if bool(record.get("existed_before", False)):
                    backup_path = record.get("backup_path")
                    if not backup_path:
                        raise ValueError(f"missing backup for restore: {rel_path}")
                    backup = Path(str(backup_path))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._copy_file(source_path=backup, target_path=target)
                else:
                    if target.exists():
                        target.unlink()
            except Exception as exc:
                restore_errors.append(f"restore failed for {rel_path}: {exc}")
        return restore_errors

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """파일 sha256."""
        digest = hashlib.sha256()
        digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _copy_file(source_path: Path, target_path: Path) -> None:
        """파일을 atomic write로 복사한다."""
        data = source_path.read_bytes()
        GenerationAdoptionApplier._atomic_write_bytes(target_path, data)

    @staticmethod
    def _atomic_write_bytes(target_path: Path, data: bytes) -> None:
        """바이트 파일을 atomic write로 저장한다."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=str(target_path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as tmp_file:
                tmp_file.write(data)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, target_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _atomic_write_json(target_path: Path, payload: dict) -> None:
        """JSON 파일을 atomic write로 저장한다."""
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        GenerationAdoptionApplier._atomic_write_bytes(target_path, data)

    @staticmethod
    def _build_record_filename(
        brain_run_id: str,
        winner_variant_id: str,
    ) -> str:
        """adoption record 파일명을 만든다."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"adoption_{timestamp}_{brain_run_id}_{winner_variant_id}.json"
