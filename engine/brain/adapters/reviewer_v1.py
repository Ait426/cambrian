"""Cambrian Harness Brain V1 Reviewer Adapter.

규칙 기반 acceptance criteria 리뷰.
test / file / other 3가지 범주로 criterion을 분류하여 판정한다.

LLM 호출은 없다. 명시적 규칙만으로 pass/fail + next_actions를 생성한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from engine.brain.models import (
    ReviewVerdict, RunState, StepResult, WorkItem,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    """현재 시각 ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


class ReviewerV1:
    """규칙 기반 acceptance criteria 리뷰어."""

    MAX_RETRY_COUNT: int = 2

    # criterion 분류 키워드
    _TEST_KEYWORDS: tuple[str, ...] = ("테스트", "test", "pytest")
    _FILE_KEYWORDS: tuple[str, ...] = (
        "파일", "생성", "추가", "file", "create", "add",
    )

    def __init__(self, project_root: Path | str) -> None:
        """초기화.

        Args:
            project_root: 파일 존재 확인 기준 디렉토리
        """
        self._root = Path(project_root).resolve()

    # ═══════════════════════════════════════════════════════════
    # 공개 API
    # ═══════════════════════════════════════════════════════════

    def review(self, state: RunState) -> tuple[StepResult, ReviewVerdict]:
        """executor 결과 + tester 결과 + acceptance_criteria를 종합한다.

        Args:
            state: 현재 RunState (mutated: retry 시 work_item.status 재설정)

        Returns:
            (StepResult, ReviewVerdict)
        """
        started = _now()

        executor_step = self._find_last_step(state, "executor")
        tester_step = self._find_last_step(state, "tester")

        # criteria 판정
        criteria_results: list[dict] = []
        all_met = True
        for crit in state.task_spec.acceptance_criteria:
            kind = self._classify_criterion(crit)
            if kind == "test":
                met, evidence = self._check_test_criterion(crit, tester_step)
            elif kind == "file":
                met, evidence = self._check_file_criterion(crit, state)
            else:
                met = True
                evidence = "자동 확인 불가 — 수동 검증 권장"
            criteria_results.append({
                "criterion": crit,
                "kind": kind,
                "met": met,
                "evidence": evidence,
            })
            if not met:
                all_met = False

        # criteria가 아예 없으면 all_met=True 유지 (informational pass)
        # tester가 failure면 강제 false
        tester_failed = (
            tester_step is not None and tester_step.status == "failure"
        )
        # failed work_items 중 retry 불가 항목이 존재하면 강제 False
        # (재시도 가능한 failed는 retry 경로로 흐르므로 아래에서 별도 처리)
        unretriable_failed = any(
            w.status == "failed" and w.retry_count >= self.MAX_RETRY_COUNT
            for w in state.work_items
        )
        passed = all_met and not tester_failed and not unretriable_failed

        # 요약 문자열
        executor_summary = (
            executor_step.summary if executor_step else "executor 실행 기록 없음"
        )
        tester_summary = (
            tester_step.summary if tester_step else "tester 실행 기록 없음"
        )

        # retry 후보: failed 상태 + retry_count < MAX
        retry_items: list[str] = []
        for item in state.work_items:
            if item.status == "failed" and item.retry_count < self.MAX_RETRY_COUNT:
                retry_items.append(item.item_id)

        # next_actions 생성
        next_actions: list[str] = []
        if not passed:
            if tester_failed:
                next_actions.append(
                    "pytest 실패 수정 후 재실행"
                )
            for cr in criteria_results:
                if not cr["met"]:
                    next_actions.append(
                        f"criterion 미충족: {cr['criterion']} — {cr['evidence']}"
                    )
            if retry_items:
                next_actions.append(
                    f"retry 가능 items: {', '.join(retry_items)}"
                )
            elif any(w.status == "failed" for w in state.work_items):
                next_actions.append(
                    "모든 재시도 소진 — 수동 개입 필요"
                )

        # retry 적용 (failed → pending, retry_count 증가)
        applied_retries: list[str] = []
        for item in state.work_items:
            if item.item_id in retry_items:
                item.status = "pending"
                item.retry_count += 1
                applied_retries.append(item.item_id)

        # 결론 문자열
        total = len(state.work_items)
        done_count = sum(1 for w in state.work_items if w.status == "done")
        failed_count = sum(1 for w in state.work_items if w.status == "failed")

        if passed and total > 0 and done_count == total:
            conclusion = (
                f"모든 acceptance criteria 충족 및 모든 작업 완료 ({done_count}/{total})"
            )
        elif passed and total == 0:
            conclusion = "acceptance criteria 충족 (작업 항목 없음)"
        elif passed:
            conclusion = (
                f"criteria 충족 — 진행 중 (done={done_count}/{total})"
            )
        elif retry_items:
            conclusion = (
                f"판정 실패 — retry 예약: {', '.join(applied_retries)}"
            )
        elif failed_count > 0 and not retry_items:
            conclusion = (
                f"판정 실패 — 모든 재시도 소진 (failed={failed_count})"
            )
        else:
            conclusion = "판정 실패 — criteria 또는 tester 미충족"

        verdict = ReviewVerdict(
            passed=passed,
            criteria_results=criteria_results,
            executor_summary=executor_summary,
            tester_summary=tester_summary,
            next_actions=next_actions,
            retry_items=applied_retries,
            conclusion=conclusion,
        )

        # state mutation (runner와의 조율)
        # - passed=True AND 모든 work_items done → status=completed
        # - passed=False AND retry 불가 AND failed 존재 → status=failed
        if passed and total > 0 and done_count == total:
            state.status = "completed"
            state.termination_reason = "all_items_done"
            state.finished_at = _now()
        elif (
            not passed
            and not applied_retries
            and failed_count > 0
        ):
            state.status = "failed"
            state.termination_reason = "reviewer_fail"
            state.finished_at = _now()

        logger.info("reviewer: %s", conclusion)
        step_status = "success" if passed else "failure"
        result = StepResult(
            role="reviewer",
            status=step_status,
            summary=conclusion,
            artifacts=[],
            errors=[a for a in next_actions] if not passed else [],
            started_at=started,
            finished_at=_now(),
            details=verdict.to_dict(),
        )
        return result, verdict

    # ═══════════════════════════════════════════════════════════
    # 내부 유틸
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _find_last_step(state: RunState, role: str) -> StepResult | None:
        """최근 step_results에서 지정 role의 마지막 것을 찾는다.

        Args:
            state: RunState
            role: "executor" | "tester" | ...

        Returns:
            마지막 StepResult (없으면 None)
        """
        for step in reversed(state.step_results):
            if step.role == role:
                return step
        return None

    @classmethod
    def _classify_criterion(cls, criterion: str) -> str:
        """criterion을 test/file/other로 분류한다.

        Args:
            criterion: 판정 기준 문자열

        Returns:
            "test" | "file" | "other"
        """
        lower = criterion.lower()
        for kw in cls._TEST_KEYWORDS:
            if kw in lower:
                return "test"
        for kw in cls._FILE_KEYWORDS:
            if kw in lower:
                return "file"
        return "other"

    @staticmethod
    def _check_test_criterion(
        criterion: str, tester_step: StepResult | None,
    ) -> tuple[bool, str]:
        """'테스트 통과' 계열 criterion을 tester StepResult로 확인한다.

        Args:
            criterion: criterion 문자열
            tester_step: 최근 tester StepResult

        Returns:
            (met, evidence)
        """
        if tester_step is None:
            return (False, "tester 실행 기록 없음")
        if tester_step.status == "success":
            return (True, f"tester 통과: {tester_step.summary}")
        if tester_step.status == "skipped":
            # 테스트가 없는 상태. criterion을 엄격히 판정하면 미충족.
            return (False, f"tester 스킵: {tester_step.summary}")
        return (False, f"tester 실패: {tester_step.summary}")

    def _check_file_criterion(
        self, criterion: str, state: RunState,
    ) -> tuple[bool, str]:
        """'파일 생성/추가' 계열 criterion을 파일 존재로 확인한다.

        Args:
            criterion: criterion 문자열
            state: RunState (task_spec.output_paths 참조)

        Returns:
            (met, evidence)
        """
        output_paths = state.task_spec.output_paths or []
        # criterion에 언급된 output_path 우선 매칭
        matched: list[str] = []
        for path in output_paths:
            # 파일명 부분 일치 또는 전체 경로 일치
            name = Path(path).name
            if path in criterion or name in criterion:
                matched.append(path)

        # 매칭이 없으면 모든 output_paths 존재 여부로 대체 판정
        check_list = matched if matched else output_paths
        if not check_list:
            return (True, "output_paths 미지정 — 자동 pass")

        missing: list[str] = []
        for p in check_list:
            full = self._root / p
            if not full.exists():
                missing.append(p)

        if not missing:
            return (True, f"파일 확인됨: {', '.join(check_list)}")
        return (False, f"파일 미발견: {', '.join(missing)}")
