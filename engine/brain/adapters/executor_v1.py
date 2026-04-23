"""Cambrian Harness Brain V1 Executor Adapter.

지원 액션:
- write_file: 파일 생성 또는 덮어쓰기
- patch_file: 텍스트 한 번 치환
- inspect_files: 읽기 전용 파일 진단
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from engine.brain.models import ExecutorAction, StepResult, WorkItem

logger = logging.getLogger(__name__)


def _now() -> str:
    """현재 시각 ISO 8601 문자열."""
    return datetime.now(timezone.utc).isoformat()


class ExecutorV1:
    """제한된 파일 작업과 읽기 전용 진단만 수행하는 실행 어댑터."""

    MAX_CONTENT_BYTES: int = 1_048_576
    LARGE_FILE_BYTES: int = 1_048_576
    MAX_INSPECT_BYTES_PER_FILE: int = 12_000
    MAX_BINARY_SAMPLE_BYTES: int = 4_096
    PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
        ".git",
        ".cambrian",
        "__pycache__",
        ".pytest_cache",
    )

    def __init__(self, project_root: Path | str) -> None:
        """초기화."""
        self._root = Path(project_root).resolve()

    def execute(self, work_item: WorkItem) -> StepResult:
        """WorkItem의 action을 실행한다."""
        started = _now()

        if work_item.action is None:
            work_item.status = "done"
            return StepResult(
                role="executor",
                status="success",
                summary=(
                    f"WorkItem '{work_item.item_id}' 실행 완료 (stub): "
                    f"{work_item.description}"
                ),
                artifacts=[],
                errors=[],
                started_at=started,
                finished_at=_now(),
                details={"mode": "stub"},
            )

        try:
            action = ExecutorAction.from_dict(work_item.action)
        except (KeyError, TypeError, ValueError) as exc:
            work_item.status = "failed"
            return StepResult(
                role="executor",
                status="failure",
                summary=f"action 파싱 실패: {exc}",
                artifacts=[],
                errors=[f"invalid_action: {exc}"],
                started_at=started,
                finished_at=_now(),
                details={"mode": "v1", "error": "invalid_action"},
            )

        if action.type == "inspect_files":
            ok, message, artifacts, details = self._inspect_files(action)
            work_item.status = "done" if ok else "failed"
            return StepResult(
                role="executor",
                status="success" if ok else "failure",
                summary=message,
                artifacts=artifacts,
                errors=list(details.get("errors", [])),
                started_at=started,
                finished_at=_now(),
                details=details,
            )

        try:
            target = self._validate_path(action.target_path)
        except ValueError as exc:
            work_item.status = "failed"
            return StepResult(
                role="executor",
                status="failure",
                summary=f"경로 거부: {exc}",
                artifacts=[],
                errors=[f"unsafe_path: {exc}"],
                started_at=started,
                finished_at=_now(),
                details={
                    "mode": "v1",
                    "action_type": action.type,
                    "target_path": action.target_path,
                    "error": "unsafe_path",
                },
            )

        backup_path: str | None = None
        try:
            if action.type == "write_file":
                ok, message, backup_path = self._write_file(action, target)
            elif action.type == "patch_file":
                ok, message, backup_path = self._patch_file(action, target)
            else:
                work_item.status = "failed"
                return StepResult(
                    role="executor",
                    status="failure",
                    summary=f"지원하지 않는 action type: {action.type}",
                    artifacts=[],
                    errors=[f"unknown_action_type: {action.type}"],
                    started_at=started,
                    finished_at=_now(),
                    details={
                        "mode": "v1",
                        "action_type": action.type,
                        "target_path": action.target_path,
                    },
                )
        except OSError as exc:
            work_item.status = "failed"
            return StepResult(
                role="executor",
                status="failure",
                summary=f"파일 I/O 실패: {exc}",
                artifacts=[],
                errors=[f"io_error: {exc}"],
                started_at=started,
                finished_at=_now(),
                details={
                    "mode": "v1",
                    "action_type": action.type,
                    "target_path": action.target_path,
                    "error": "io_error",
                },
            )

        if ok:
            work_item.status = "done"
            return StepResult(
                role="executor",
                status="success",
                summary=message,
                artifacts=[action.target_path],
                errors=[],
                started_at=started,
                finished_at=_now(),
                details={
                    "mode": "v1",
                    "action_type": action.type,
                    "target_path": action.target_path,
                    "backup_path": backup_path,
                },
            )

        work_item.status = "failed"
        return StepResult(
            role="executor",
            status="failure",
            summary=message,
            artifacts=[],
            errors=[message],
            started_at=started,
            finished_at=_now(),
            details={
                "mode": "v1",
                "action_type": action.type,
                "target_path": action.target_path,
            },
        )

    def _validate_path(self, target_path: str, *, allow_protected: bool = False) -> Path:
        """안전한 프로젝트 내부 경로만 허용한다."""
        if not target_path:
            raise ValueError("target_path가 비어 있음")

        as_path = Path(target_path)
        if as_path.is_absolute():
            raise ValueError(f"절대 경로 거부: {target_path}")
        if ".." in as_path.parts:
            raise ValueError(f"상위 경로 참조 거부: {target_path}")

        if not allow_protected:
            normalized = target_path.replace("\\", "/")
            for protected in self.PROTECTED_PATH_PREFIXES:
                if normalized == protected or normalized.startswith(f"{protected}/"):
                    raise ValueError(f"보호 경로 거부: {target_path}")

        candidate = (self._root / as_path).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            raise ValueError(
                f"project_root 밖 경로 거부: {target_path}"
            ) from None
        return candidate

    @staticmethod
    def _backup(path: Path) -> str | None:
        """기존 파일이 있으면 .bak 백업을 만든다."""
        if not path.exists():
            return None
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        return str(bak)

    def _write_file(
        self,
        action: ExecutorAction,
        target: Path,
    ) -> tuple[bool, str, str | None]:
        """파일을 생성하거나 덮어쓴다."""
        if action.content is None:
            return (False, "write_file: content가 None", None)

        encoded = action.content.encode("utf-8")
        if len(encoded) > self.MAX_CONTENT_BYTES:
            return (
                False,
                "write_file: content 크기 초과 "
                f"({len(encoded)} > {self.MAX_CONTENT_BYTES})",
                None,
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        backup = self._backup(target)
        target.write_text(action.content, encoding="utf-8")
        logger.info("write_file: %s (backup=%s)", target, backup)
        return (True, f"파일 생성: {action.target_path}", backup)

    def _patch_file(
        self,
        action: ExecutorAction,
        target: Path,
    ) -> tuple[bool, str, str | None]:
        """파일에서 old_text 한 번만 new_text로 치환한다."""
        if action.old_text is None or action.new_text is None:
            return (False, "patch_file: old_text 또는 new_text가 None", None)
        if not target.exists():
            return (False, f"patch_file: 대상 파일 없음: {action.target_path}", None)

        current = target.read_text(encoding="utf-8")
        if action.old_text not in current:
            snippet = action.old_text[:50].replace("\n", "\\n")
            return (
                False,
                f"patch_file: 교체 대상 텍스트를 찾을 수 없음: {snippet}...",
                None,
            )

        backup = self._backup(target)
        updated = current.replace(action.old_text, action.new_text, 1)
        target.write_text(updated, encoding="utf-8")
        logger.info("patch_file: %s (backup=%s)", target, backup)
        return (True, f"파일 패치: {action.target_path}", backup)

    def _inspect_files(
        self,
        action: ExecutorAction,
    ) -> tuple[bool, str, list[str], dict]:
        """선택된 파일을 읽기 전용으로 검사한다."""
        requested_paths = list(action.target_paths or [])
        if action.target_path:
            requested_paths.append(action.target_path)
        requested_paths = list(dict.fromkeys(path for path in requested_paths if path))
        if not requested_paths:
            details = {
                "mode": "v1",
                "action": "inspect_files",
                "action_type": "inspect_files",
                "inspected_files": [],
                "skipped_files": [],
                "errors": ["inspect_files: target_paths가 비어 있음"],
            }
            return (
                False,
                "inspect_files 실행 실패: target_paths가 비어 있습니다.",
                [],
                details,
            )

        preview_limit = action.max_bytes_per_file or self.MAX_INSPECT_BYTES_PER_FILE
        preview_limit = max(1, min(preview_limit, self.MAX_INSPECT_BYTES_PER_FILE))

        inspected_files: list[dict] = []
        skipped_files: list[dict] = []
        errors: list[str] = []

        for raw_path in requested_paths:
            try:
                target = self._validate_path(raw_path)
            except ValueError as exc:
                errors.append(f"{raw_path}: {exc}")
                continue

            if not target.exists():
                skipped_files.append(
                    {
                        "path": raw_path,
                        "reason": "file_not_found",
                    }
                )
                continue
            if not target.is_file():
                skipped_files.append(
                    {
                        "path": raw_path,
                        "reason": "not_a_file",
                    }
                )
                continue

            size_bytes = target.stat().st_size
            if size_bytes > self.LARGE_FILE_BYTES:
                skipped_files.append(
                    {
                        "path": raw_path,
                        "reason": "file_too_large",
                        "size_bytes": size_bytes,
                    }
                )
                continue

            sample = self._read_bytes(target, min(self.MAX_BINARY_SAMPLE_BYTES, size_bytes))
            if b"\x00" in sample:
                skipped_files.append(
                    {
                        "path": raw_path,
                        "reason": "binary_file",
                        "size_bytes": size_bytes,
                    }
                )
                continue

            preview_bytes = self._read_bytes(target, preview_limit)
            truncated = size_bytes > len(preview_bytes)
            preview = preview_bytes.decode("utf-8", errors="replace")

            inspected_files.append(
                {
                    "path": raw_path,
                    "exists": True,
                    "size_bytes": size_bytes,
                    "sha256": self._sha256(target),
                    "preview": preview,
                    "truncated": truncated,
                }
            )

        details = {
            "mode": "v1",
            "action": "inspect_files",
            "action_type": "inspect_files",
            "inspected_files": inspected_files,
            "skipped_files": skipped_files,
            "errors": errors,
        }
        artifacts = [item["path"] for item in inspected_files]
        if inspected_files:
            message = (
                "파일 진단 완료: "
                f"inspected={len(inspected_files)} "
                f"skipped={len(skipped_files)} "
                f"errors={len(errors)}"
            )
            return True, message, artifacts, details

        message = (
            "파일 진단 실패: "
            f"inspected=0 skipped={len(skipped_files)} errors={len(errors)}"
        )
        return False, message, artifacts, details

    @staticmethod
    def _read_bytes(path: Path, limit: int) -> bytes:
        """파일 앞부분 바이트를 제한 길이만큼 읽는다."""
        with path.open("rb") as handle:
            return handle.read(limit)

    @staticmethod
    def _sha256(path: Path) -> str:
        """파일 sha256 해시를 계산한다."""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(65_536)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
