"""Cambrian Harness Brain V1 Tester Adapter.

subprocess로 pytest를 실행하고 결과를 TestDetail로 구조화한다.
전체 suite 실행이 아니라 related_tests에 명시된 파일만 대상으로 한다.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from engine.brain.models import RunState, StepResult, TestDetail

logger = logging.getLogger(__name__)


def _now() -> str:
    """현재 시각 ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


class TesterV1:
    """pytest 기반 테스트 실행 어댑터."""

    # pytest가 클래스명 접두사 'Test*'로 test class로 오인하는 것 방지
    __test__ = False

    TIMEOUT_SECONDS: int = 120
    MAX_STDOUT_LINES: int = 50
    MAX_STDERR_LINES: int = 20

    # pytest exit code reference (docs.pytest.org):
    # 0 = success, 1 = failures, 2 = interrupted, 3 = internal error,
    # 4 = usage error, 5 = no tests collected.
    # 본 MVP에서는 no tests collected(5)를 skipped로 매핑하되,
    # 최종 status는 no_tests_as_success 플래그로 success 처리하여
    # 기존 Task 26 테스트(빈 test 파일 = success)의 하위 호환을 유지한다.
    NO_TESTS_EXIT_CODE: int = 5

    _RE_PASSED = re.compile(r"(\d+)\s+passed")
    _RE_FAILED = re.compile(r"(\d+)\s+failed")
    _RE_ERRORS = re.compile(r"(\d+)\s+error(?:s)?")
    _RE_SKIPPED = re.compile(r"(\d+)\s+skipped")

    def __init__(self, project_root: Path | str) -> None:
        """초기화.

        Args:
            project_root: pytest의 cwd + related_tests 기준 경로
        """
        self._root = Path(project_root).resolve()

    # ═══════════════════════════════════════════════════════════
    # 공개 API
    # ═══════════════════════════════════════════════════════════

    def run_tests(self, state: RunState) -> tuple[StepResult, TestDetail]:
        """related_tests를 pytest로 실행한다.

        Args:
            state: 현재 RunState

        Returns:
            (StepResult, TestDetail)
        """
        started = _now()

        all_tests = state.task_spec.related_tests or []
        existing: list[str] = []
        missing: list[str] = []
        for t in all_tests:
            candidate = self._root / t
            if candidate.exists():
                existing.append(t)
            else:
                missing.append(t)

        # 실행할 테스트가 없으면 skipped
        if not existing:
            detail = TestDetail(
                test_files=[],
                exit_code=self.NO_TESTS_EXIT_CODE if missing else 0,
                passed=0, failed=0, errors=0, skipped=0,
                duration_seconds=0.0,
                stdout_tail="",
                stderr_tail="",
            )
            summary = (
                "related_tests 비어있음 → tester 스킵"
                if not all_tests else
                f"related_tests {len(missing)}개 모두 없음 → tester 스킵"
            )
            result = StepResult(
                role="tester",
                status="skipped",
                summary=summary,
                artifacts=[],
                errors=[f"missing: {m}" for m in missing],
                started_at=started,
                finished_at=_now(),
                details=detail.to_dict(),
            )
            return result, detail

        # pytest 실행
        cmd = [
            sys.executable, "-m", "pytest",
            *existing,
            "-v", "--tb=short", "--no-header", "-q",
        ]
        logger.info("pytest 실행: %s", " ".join(cmd))
        start_ts = datetime.now(timezone.utc).timestamp()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(self._root),
                timeout=self.TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = datetime.now(timezone.utc).timestamp() - start_ts
            detail = TestDetail(
                test_files=existing,
                exit_code=-1,
                passed=0, failed=0, errors=0, skipped=0,
                duration_seconds=round(elapsed, 3),
                stdout_tail=(exc.stdout or "")[-4000:] if exc.stdout else "",
                stderr_tail=(exc.stderr or "")[-1500:] if exc.stderr else "",
            )
            result = StepResult(
                role="tester",
                status="failure",
                summary=f"pytest timeout ({self.TIMEOUT_SECONDS}s 초과)",
                artifacts=existing,
                errors=[f"pytest_timeout: {self.TIMEOUT_SECONDS}s"],
                started_at=started,
                finished_at=_now(),
                details=detail.to_dict(),
            )
            return result, detail
        except FileNotFoundError:
            # python/pytest 자체가 없는 경우 (거의 없지만 방어)
            detail = TestDetail(
                test_files=existing,
                exit_code=-1,
                passed=0, failed=0, errors=0, skipped=0,
                duration_seconds=0.0,
                stdout_tail="",
                stderr_tail="pytest not available",
            )
            result = StepResult(
                role="tester",
                status="skipped",
                summary="pytest 미설치 → 테스트 스킵",
                artifacts=existing,
                errors=["pytest_not_available"],
                started_at=started,
                finished_at=_now(),
                details=detail.to_dict(),
            )
            return result, detail

        elapsed = datetime.now(timezone.utc).timestamp() - start_ts
        detail = self._parse_pytest_output(
            proc.stdout or "", proc.stderr or "", proc.returncode, existing,
            elapsed,
        )

        # status 결정: 0 또는 5 (no tests) → success
        if detail.exit_code == 0:
            status = "success"
            summary = (
                f"pytest 통과: passed={detail.passed} "
                f"skipped={detail.skipped} ({detail.duration_seconds:.2f}s)"
            )
        elif detail.exit_code == self.NO_TESTS_EXIT_CODE:
            # 파일은 존재하지만 pytest가 테스트를 수집하지 못함.
            # Task 26 하위 호환을 위해 success로 매핑.
            status = "success"
            summary = (
                f"pytest 수집 테스트 없음 (파일은 존재): "
                f"files={len(existing)}"
            )
        else:
            status = "failure"
            summary = (
                f"pytest 실패: exit={detail.exit_code} "
                f"failed={detail.failed} errors={detail.errors}"
            )

        result = StepResult(
            role="tester",
            status=status,
            summary=summary,
            artifacts=existing,
            errors=[f"missing: {m}" for m in missing],
            started_at=started,
            finished_at=_now(),
            details=detail.to_dict(),
        )
        return result, detail

    # ═══════════════════════════════════════════════════════════
    # 내부 유틸
    # ═══════════════════════════════════════════════════════════

    def _parse_pytest_output(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
        test_files: list[str],
        duration: float,
    ) -> TestDetail:
        """pytest 출력에서 passed/failed/errors/skipped를 추출한다.

        Args:
            stdout: pytest stdout
            stderr: pytest stderr
            returncode: pytest exit code
            test_files: 실행된 테스트 파일 목록
            duration: 실제 경과 초

        Returns:
            TestDetail
        """
        summary_line = self._find_summary_line(stdout)
        passed = self._extract_int(self._RE_PASSED, summary_line)
        failed = self._extract_int(self._RE_FAILED, summary_line)
        errors = self._extract_int(self._RE_ERRORS, summary_line)
        skipped = self._extract_int(self._RE_SKIPPED, summary_line)

        # 완전 파싱 실패 시 exit_code 기반 fallback
        if passed == 0 and failed == 0 and errors == 0 and skipped == 0:
            if returncode == 0:
                passed = 1
            elif returncode == self.NO_TESTS_EXIT_CODE:
                skipped = 0  # 수집 0개
            else:
                failed = 1

        return TestDetail(
            test_files=test_files,
            exit_code=returncode,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_seconds=round(duration, 3),
            stdout_tail=self._tail(stdout, self.MAX_STDOUT_LINES),
            stderr_tail=self._tail(stderr, self.MAX_STDERR_LINES),
        )

    @staticmethod
    def _find_summary_line(stdout: str) -> str:
        """pytest summary 라인(예: '=== 3 passed in 0.12s ===')을 찾는다.

        Args:
            stdout: pytest stdout

        Returns:
            summary로 추정되는 라인 (없으면 전체 stdout)
        """
        # 하단에서 "passed" 또는 "failed" 또는 "error" 포함 라인 탐색
        lines = stdout.strip().splitlines()
        for line in reversed(lines):
            lower = line.lower()
            if any(k in lower for k in ("passed", "failed", "error", "skipped")):
                return line
        return stdout

    @staticmethod
    def _extract_int(pattern: re.Pattern[str], text: str) -> int:
        """정규식 첫 매칭을 int로 변환. 실패 시 0."""
        m = pattern.search(text)
        if not m:
            return 0
        try:
            return int(m.group(1))
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def _tail(text: str, max_lines: int) -> str:
        """텍스트 마지막 max_lines 줄만 반환."""
        if not text:
            return ""
        lines = text.splitlines()
        return "\n".join(lines[-max_lines:])
