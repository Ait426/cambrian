"""Cambrian Harness Brain RALF-style 반복 실행 루프."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from engine.brain.checkpoint import CheckpointManager
from engine.brain.competitive import CompetitiveGenerationRunner
from engine.brain.models import RunState, StepResult, TaskSpec
from engine.brain.pipeline import RolePipeline
from engine.brain.report import build_core_bridge_summary, generate_report

logger = logging.getLogger(__name__)


def _now() -> str:
    """현재 시각을 ISO 8601 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _generate_run_id() -> str:
    """고유 run_id를 생성한다."""
    dt = datetime.now(timezone.utc)
    stamp = dt.strftime("%Y%m%d-%H%M%S")
    rand = secrets.token_hex(2)
    return f"brain-{stamp}-{rand}"


class RALFRunner:
    """RALF-style 반복 실행 루프 러너."""

    NEXT_PHASE_AFTER_REVIEWER: str = "executor"

    def __init__(
        self,
        runs_dir: str | Path,
        workspace: str | Path | None = None,
    ) -> None:
        """러너를 초기화한다."""
        self._checkpoint = CheckpointManager(runs_dir)
        self._workspace = Path(workspace) if workspace is not None else Path.cwd()
        self._pipeline = RolePipeline(workspace=self._workspace)

    def run(
        self,
        task_spec: TaskSpec,
        max_iterations: int = 10,
    ) -> RunState:
        """새 run을 시작한다."""
        if max_iterations < 1:
            raise ValueError(
                f"max_iterations는 1 이상이어야 한다: {max_iterations}"
            )

        run_id = _generate_run_id()
        now = _now()
        state = RunState(
            run_id=run_id,
            task_spec=task_spec,
            status="running",
            current_iteration=0,
            max_iterations=max_iterations,
            current_phase=(
                "competitive"
                if self._is_competitive_task(task_spec)
                else "planner"
            ),
            work_items=[],
            step_results=[],
            started_at=now,
            updated_at=now,
            finished_at=None,
            termination_reason="",
            core_bridge=self._build_core_bridge(task_spec),
        )

        self._checkpoint.create_run_dir(run_id)
        self._checkpoint.save_task_spec(run_id, task_spec)
        self._checkpoint.save_state(state)
        logger.info("새 run 시작: %s", run_id)

        return self._run_loop(state)

    def resume(self, run_id: str) -> RunState:
        """기존 run을 checkpoint에서 읽어 이어서 실행한다."""
        state = self._checkpoint.load_state(run_id)
        if state.task_spec.core_refs and state.core_bridge is None:
            state.core_bridge = self._build_core_bridge(state.task_spec)
            logger.info("resume 전에 core bridge 보강: %s", run_id)

        logger.info(
            "run 재개: %s (iter=%d phase=%s)",
            run_id,
            state.current_iteration,
            state.current_phase,
        )

        if state.status in ("completed", "failed", "max_iter_reached"):
            self._checkpoint.save_state(state)
            logger.info("이미 종료된 run: status=%s", state.status)
            return state

        state.status = "running"
        state.updated_at = _now()
        self._checkpoint.save_state(state)
        return self._run_loop(state)

    def _build_core_bridge(self, task_spec: TaskSpec) -> dict | None:
        """TaskSpec.core_refs를 read-only summary로 변환한다."""
        if not task_spec.core_refs:
            return None
        try:
            return build_core_bridge_summary(
                task_spec.core_refs,
                workspace=self._workspace,
            )
        except Exception:
            logger.exception("core bridge summary 생성 실패")
            return {
                "read_only": True,
                "artifact_count": 0,
                "loaded_count": 0,
                "missing_count": 0,
                "invalid_count": 1,
                "artifacts": [],
                "errors": ["core bridge summary generation failed"],
            }

    @staticmethod
    def _is_competitive_task(task_spec: TaskSpec) -> bool:
        """competitive generation 사용 여부."""
        return bool(
            isinstance(task_spec.competitive, dict)
            and task_spec.competitive.get("enabled", False)
        )

    def _run_loop(self, state: RunState) -> RunState:
        """메인 반복 루프를 실행한다."""
        if self._is_competitive_task(state.task_spec):
            state = self._run_competitive_generation(state)
            self._checkpoint.save_state(state)

            report = generate_report(state)
            self._checkpoint.save_report(state.run_id, report)
            logger.info(
                "competitive run 종료: %s status=%s reason=%s",
                state.run_id,
                state.status,
                state.termination_reason,
            )
            return state

        while not self._check_termination(state):
            state = self._execute_iteration(state)
            self._checkpoint.save_state(state)

        if state.finished_at is None:
            state.finished_at = _now()
        state.updated_at = state.finished_at
        self._checkpoint.save_state(state)

        report = generate_report(state)
        self._checkpoint.save_report(state.run_id, report)

        logger.info(
            "run 종료: %s status=%s reason=%s iter=%d",
            state.run_id,
            state.status,
            state.termination_reason,
            state.current_iteration,
        )
        return state

    def _run_competitive_generation(self, state: RunState) -> RunState:
        """competitive generation을 한 번 실행하고 종료 상태로 만든다."""
        runner = CompetitiveGenerationRunner()
        result = runner.run(
            spec=state.task_spec,
            run_dir=self._checkpoint.run_dir(state.run_id),
            project_root=self._workspace.resolve(),
            core_bridge=state.core_bridge,
        )
        state.competitive_generation = result.to_dict()
        state.current_phase = "competitive"
        state.current_iteration = 1
        state.finished_at = _now()
        state.updated_at = state.finished_at

        if result.status == "failure":
            state.status = "failed"
            state.termination_reason = "competitive_failure"
        elif result.status == "no_winner":
            state.status = "completed"
            state.termination_reason = "competitive_no_winner"
        else:
            state.status = "completed"
            state.termination_reason = "competitive_winner_selected"

        return state

    def _execute_iteration(self, state: RunState) -> RunState:
        """현재 phase의 한 단계만 실행하고 phase를 전진시킨다."""
        phase = state.current_phase
        iter_results: list[StepResult]

        if phase == "planner":
            if state.current_iteration != 0:
                logger.warning(
                    "iteration %d에서 planner phase 발견 -> executor로 보정",
                    state.current_iteration,
                )
                state.current_phase = "executor"
                return self._execute_iteration(state)
            result = self._pipeline.run_planner(state)
            state.step_results.append(result)
            state.current_phase = "executor"

        elif phase == "executor":
            result = self._pipeline.run_executor(state)
            state.step_results.append(result)
            state.current_phase = "tester"

        elif phase == "tester":
            result = self._pipeline.run_tester(state)
            state.step_results.append(result)
            state.current_phase = "reviewer"

        elif phase == "reviewer":
            result = self._pipeline.run_reviewer(state)
            state.step_results.append(result)

            iter_results = self._slice_current_iteration(state)
            self._checkpoint.save_iteration(
                state.run_id,
                state.current_iteration,
                iter_results,
            )

            state.current_iteration += 1
            state.current_phase = self.NEXT_PHASE_AFTER_REVIEWER

        else:
            raise ValueError(f"알 수 없는 phase: {phase}")

        state.updated_at = _now()
        return state

    def _slice_current_iteration(self, state: RunState) -> list[StepResult]:
        """현재 iteration에 해당하는 step_results만 반환한다."""
        if state.current_iteration == 0:
            size = 4
            start = 0
        else:
            size = 3
            start = 4 + (state.current_iteration - 1) * 3
        end = start + size
        return state.step_results[start:end]

    def _check_termination(self, state: RunState) -> bool:
        """종료 조건을 확인한다."""
        if state.status in ("completed", "failed", "max_iter_reached"):
            return True

        if state.work_items and state.current_phase == "executor":
            terminal = {"done", "skipped"}
            if all(work_item.status in terminal for work_item in state.work_items):
                state.status = "completed"
                state.termination_reason = "all_items_done"
                state.finished_at = _now()
                return True

        if state.current_iteration >= state.max_iterations:
            state.status = "max_iter_reached"
            state.termination_reason = "max_iterations"
            state.finished_at = _now()
            return True

        return False
