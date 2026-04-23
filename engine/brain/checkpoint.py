"""Cambrian Harness Brain 파일 기반 체크포인트 매니저.

모든 run 상태를 `.cambrian/brain/runs/<run-id>/` 아래에 파일로 저장한다.
atomic write로 중간 크래시에도 파일이 깨지지 않도록 보장한다.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

import yaml

from engine.brain.models import RunState, StepResult, TaskSpec

logger = logging.getLogger(__name__)


class CheckpointManager:
    """파일 기반 checkpoint 읽기/쓰기.

    디렉토리 구조:
        <runs_dir>/<run-id>/
            task_spec.yaml
            run_state.json
            iterations/
                iter_000.json
                iter_001.json
            report.json
    """

    def __init__(self, runs_dir: str | Path) -> None:
        """초기화.

        Args:
            runs_dir: .cambrian/brain/runs/ 경로
        """
        self._runs_dir = Path(runs_dir)

    @property
    def runs_dir(self) -> Path:
        """runs 루트 디렉토리 경로."""
        return self._runs_dir

    def run_dir(self, run_id: str) -> Path:
        """특정 run 디렉토리 경로 반환 (존재 보장 없음)."""
        return self._runs_dir / run_id

    def create_run_dir(self, run_id: str) -> Path:
        """run 디렉토리와 iterations/ 서브디렉토리를 생성한다.

        Args:
            run_id: run 식별자

        Returns:
            생성된 run 디렉토리 경로
        """
        run_path = self.run_dir(run_id)
        run_path.mkdir(parents=True, exist_ok=True)
        (run_path / "iterations").mkdir(parents=True, exist_ok=True)
        logger.info("run 디렉토리 생성: %s", run_path)
        return run_path

    # ═══════════════════════════════════════════════════════════
    # atomic write 헬퍼
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        """tmp 파일에 쓰고 rename으로 원자적 교체한다.

        Args:
            target: 최종 파일 경로
            content: 쓸 내용 (utf-8)
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(content)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, target)
        except Exception:
            # 실패 시 tmp 파일 정리
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ═══════════════════════════════════════════════════════════
    # state 저장/로드
    # ═══════════════════════════════════════════════════════════

    def save_state(self, state: RunState) -> None:
        """run_state.json을 atomic write로 저장한다.

        Args:
            state: 저장할 RunState

        Raises:
            FileNotFoundError: run 디렉토리가 없을 때
        """
        run_path = self.run_dir(state.run_id)
        if not run_path.exists():
            raise FileNotFoundError(
                f"run 디렉토리 없음 (create_run_dir 선행 필요): {run_path}"
            )

        target = run_path / "run_state.json"
        content = json.dumps(state.to_dict(), indent=2, ensure_ascii=False)
        self._atomic_write(target, content)
        logger.debug("state 저장: %s", target)

    def load_state(self, run_id: str) -> RunState:
        """run_state.json을 로드한다.

        Args:
            run_id: 로드할 run ID

        Returns:
            RunState

        Raises:
            FileNotFoundError: run_state.json이 없을 때
            ValueError: JSON 파싱 실패 또는 필드 누락 시
        """
        target = self.run_dir(run_id) / "run_state.json"
        if not target.exists():
            raise FileNotFoundError(
                f"run_state.json 없음: {target}"
            )

        try:
            raw = target.read_text(encoding="utf-8")
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("run_state.json 파싱 실패: %s", exc)
            raise ValueError(
                f"run_state.json 파싱 실패 ({target}): {exc}"
            ) from exc

        return RunState.from_dict(data)

    # ═══════════════════════════════════════════════════════════
    # iteration / task_spec / report
    # ═══════════════════════════════════════════════════════════

    def save_iteration(
        self,
        run_id: str,
        iteration: int,
        results: list[StepResult],
    ) -> None:
        """iterations/iter_NNN.json을 저장한다.

        Args:
            run_id: run 식별자
            iteration: iteration 번호 (0부터)
            results: 해당 iteration의 StepResult 리스트
        """
        target = (
            self.run_dir(run_id) / "iterations" / f"iter_{iteration:03d}.json"
        )
        payload = {
            "iteration": iteration,
            "results": [r.to_dict() for r in results],
        }
        content = json.dumps(payload, indent=2, ensure_ascii=False)
        self._atomic_write(target, content)
        logger.debug("iteration 저장: %s", target)

    def save_task_spec(self, run_id: str, spec: TaskSpec) -> None:
        """task_spec.yaml 사본을 저장한다.

        Args:
            run_id: run 식별자
            spec: 저장할 TaskSpec
        """
        target = self.run_dir(run_id) / "task_spec.yaml"
        content = yaml.safe_dump(
            spec.to_dict(), allow_unicode=True, sort_keys=False,
        )
        self._atomic_write(target, content)
        logger.debug("task_spec 저장: %s", target)

    def save_report(self, run_id: str, report: dict) -> None:
        """report.json을 저장한다.

        Args:
            run_id: run 식별자
            report: 보고서 dict
        """
        target = self.run_dir(run_id) / "report.json"
        content = json.dumps(report, indent=2, ensure_ascii=False)
        self._atomic_write(target, content)
        logger.info("report 저장: %s", target)

    # ═══════════════════════════════════════════════════════════
    # 목록 조회
    # ═══════════════════════════════════════════════════════════

    def list_runs(self) -> list[dict]:
        """모든 run 요약을 반환한다.

        Returns:
            각 run의 {run_id, status, updated_at, current_iteration,
            termination_reason} dict 리스트. updated_at 내림차순.
        """
        if not self._runs_dir.exists():
            return []

        summaries: list[dict] = []
        for entry in self._runs_dir.iterdir():
            if not entry.is_dir():
                continue
            state_file = entry / "run_state.json"
            if not state_file.exists():
                continue
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                summaries.append({
                    "run_id": data.get("run_id", entry.name),
                    "status": data.get("status", ""),
                    "updated_at": data.get("updated_at", ""),
                    "current_iteration": data.get("current_iteration", 0),
                    "termination_reason": data.get("termination_reason", ""),
                })
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "run_state.json 읽기 실패 (%s): %s", entry.name, exc,
                )
                continue

        summaries.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return summaries
