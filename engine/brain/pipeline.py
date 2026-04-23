"""Cambrian Harness Brain 4-role 파이프라인.

V1: planner는 자체 규칙, executor/tester/reviewer는 adapters/로 dispatch.
action이 None인 WorkItem은 executor_v1 내부에서 stub 경로로 떨어져
Task 26 하위 호환이 유지된다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from engine.brain.adapters.executor_v1 import ExecutorV1
from engine.brain.adapters.reviewer_v1 import ReviewerV1
from engine.brain.adapters.tester_v1 import TesterV1
from engine.brain.models import RunState, StepResult, WorkItem

logger = logging.getLogger(__name__)


def _now() -> str:
    """현재 시각 ISO 8601 문자열."""
    return datetime.now(timezone.utc).isoformat()


class RolePipeline:
    """4-role 파이프라인. planner는 자체, 나머지는 adapter dispatch."""

    def __init__(
        self,
        project_root: Path | str | None = None,
        workspace: Path | str | None = None,
    ) -> None:
        """초기화.

        Args:
            project_root: executor/tester/reviewer 작업 기준 경로.
                None이고 workspace도 None이면 현재 작업 디렉토리 사용.
            workspace: 하위 호환용 별칭. project_root가 주어지면 무시.
        """
        root = project_root if project_root is not None else workspace
        self._root = Path(root) if root is not None else Path.cwd()
        self._executor = ExecutorV1(self._root)
        self._tester = TesterV1(self._root)
        self._reviewer = ReviewerV1(self._root)

    # ═══════════════════════════════════════════════════════════
    # planner
    # ═══════════════════════════════════════════════════════════

    def run_planner(self, state: RunState) -> StepResult:
        """TaskSpec.scope 항목을 WorkItem으로 변환한다.

        V1 확장: TaskSpec.actions가 있으면 scope[i] ↔ actions[i]를
        1:1 매핑하여 WorkItem.action에 저장한다.

        Args:
            state: 현재 RunState (mutated)

        Returns:
            StepResult
        """
        started = _now()

        if state.work_items:
            return StepResult(
                role="planner",
                status="skipped",
                summary="work_items가 이미 존재하여 planner 재실행 스킵",
                started_at=started,
                finished_at=_now(),
            )

        scope = state.task_spec.scope
        actions = state.task_spec.actions or []

        if not scope:
            # scope 없음 → goal을 단일 WorkItem으로. action은 actions[0]이 있으면 사용.
            action = actions[0] if actions else None
            state.work_items.append(WorkItem(
                item_id="work-001",
                description=state.task_spec.goal,
                status="pending",
                assigned_role="executor",
                action=action,
            ))
            summary = "scope 비어있음 → goal을 단일 WorkItem으로 변환"
        else:
            for idx, item_desc in enumerate(scope, start=1):
                action = (
                    actions[idx - 1] if idx - 1 < len(actions) else None
                )
                state.work_items.append(WorkItem(
                    item_id=f"work-{idx:03d}",
                    description=str(item_desc),
                    status="pending",
                    assigned_role="executor",
                    action=action,
                ))
            mapped = min(len(scope), len(actions))
            action_note = (
                f" (actions 매핑: {mapped}개)" if actions else ""
            )
            summary = (
                f"scope {len(scope)}개 → WorkItem {len(scope)}개 생성"
                f"{action_note}"
            )

        logger.info("planner: %s", summary)
        return StepResult(
            role="planner",
            status="success",
            summary=summary,
            artifacts=[],
            errors=[],
            started_at=started,
            finished_at=_now(),
        )

    # ═══════════════════════════════════════════════════════════
    # executor — adapter dispatch
    # ═══════════════════════════════════════════════════════════

    def run_executor(self, state: RunState) -> StepResult:
        """pending WorkItem 중 첫 번째를 ExecutorV1으로 실행한다.

        action이 None인 WorkItem은 ExecutorV1 내부에서 stub 경로로 처리된다.

        Args:
            state: 현재 RunState (mutated)

        Returns:
            StepResult
        """
        started = _now()
        target: WorkItem | None = None
        for item in state.work_items:
            if item.status == "pending":
                target = item
                break

        if target is None:
            return StepResult(
                role="executor",
                status="skipped",
                summary="pending WorkItem이 없어 executor 스킵",
                started_at=started,
                finished_at=_now(),
            )

        return self._executor.execute(target)

    # ═══════════════════════════════════════════════════════════
    # tester — adapter dispatch
    # ═══════════════════════════════════════════════════════════

    def run_tester(self, state: RunState) -> StepResult:
        """TesterV1로 related_tests를 실행한다.

        Args:
            state: 현재 RunState

        Returns:
            StepResult (details에 TestDetail dict 포함)
        """
        step, _detail = self._tester.run_tests(state)
        return step

    # ═══════════════════════════════════════════════════════════
    # reviewer — adapter dispatch
    # ═══════════════════════════════════════════════════════════

    def run_reviewer(self, state: RunState) -> StepResult:
        """ReviewerV1로 acceptance criteria를 판정한다.

        reviewer는 state.status / termination_reason / finished_at을
        조건부로 설정할 수 있다 (runner와 조율됨).

        Args:
            state: 현재 RunState (mutated)

        Returns:
            StepResult (details에 ReviewVerdict dict 포함)
        """
        step, _verdict = self._reviewer.review(state)
        return step
