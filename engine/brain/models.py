"""Cambrian Harness Brain 데이터 모델.

TaskSpec, WorkItem, StepResult, RunState와 V1 어댑터 보조 모델을 정의한다.

호환성 원칙:
- 새 필드는 모두 기본값을 가진다.
- 기존 checkpoint/report를 읽을 때 필수 필드가 늘어나지 않는다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


WORK_ITEM_STATUSES: set[str] = {
    "pending", "in_progress", "done", "failed", "skipped",
}

STEP_RESULT_STATUSES: set[str] = {"success", "failure", "skipped"}

RUN_STATUSES: set[str] = {
    "running", "paused", "completed", "failed", "max_iter_reached",
}

ROLES: tuple[str, ...] = ("planner", "executor", "tester", "reviewer")

EXECUTOR_ACTION_TYPES: set[str] = {"write_file", "patch_file", "inspect_files"}


@dataclass
class ExecutorAction:
    """executor가 수행할 단일 파일 작업."""

    type: str
    target_path: str
    target_paths: list[str] | None = None
    content: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    max_bytes_per_file: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutorAction":
        return cls(
            type=str(data["type"]),
            target_path=str(data.get("target_path") or ""),
            target_paths=(
                [str(item) for item in data.get("target_paths", [])]
                if data.get("target_paths") is not None else None
            ),
            content=data.get("content"),
            old_text=data.get("old_text"),
            new_text=data.get("new_text"),
            max_bytes_per_file=(
                int(data["max_bytes_per_file"])
                if data.get("max_bytes_per_file") is not None else None
            ),
        )


@dataclass
class TestDetail:
    """pytest 실행 결과 상세."""

    test_files: list[str] = field(default_factory=list)
    exit_code: int = -1
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    stdout_tail: str = ""
    stderr_tail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewVerdict:
    """reviewer 판정 결과."""

    passed: bool
    criteria_results: list[dict] = field(default_factory=list)
    executor_summary: str = ""
    tester_summary: str = ""
    next_actions: list[str] = field(default_factory=list)
    retry_items: list[str] = field(default_factory=list)
    conclusion: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskSpec:
    """하네스가 실행할 작업 단위. YAML 파일 기반."""

    task_id: str
    goal: str
    scope: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    related_tests: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    core_refs: dict[str, str] | None = None
    generation_seed: dict | None = None
    feedback_refs: list[str] | None = None
    selection_pressure: dict | None = None
    selection_pressure_refs: list[str] | None = None
    hypothesis_refinement: dict | None = None
    hypothesis_refinement_refs: list[str] | None = None
    hypothesis: dict | None = None
    competitive: dict | None = None
    # V1: optional actions. scope 항목과 1:1 대응.
    actions: list[dict] | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TaskSpec":
        """YAML 파일에서 TaskSpec을 로드한다."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"TaskSpec YAML 파일 없음: {file_path}")

        try:
            raw = file_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ValueError(f"TaskSpec YAML 파싱 실패: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"TaskSpec YAML 최상위는 dict여야 함: {type(data).__name__}"
            )
        return cls.from_dict(data)

    def to_yaml(self, path: str | Path) -> None:
        """TaskSpec을 YAML 파일로 저장한다."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        if data.get("core_refs") is None:
            data.pop("core_refs", None)
        if data.get("generation_seed") is None:
            data.pop("generation_seed", None)
        if data.get("feedback_refs") is None:
            data.pop("feedback_refs", None)
        if data.get("selection_pressure") is None:
            data.pop("selection_pressure", None)
        if data.get("selection_pressure_refs") is None:
            data.pop("selection_pressure_refs", None)
        if data.get("hypothesis_refinement") is None:
            data.pop("hypothesis_refinement", None)
        if data.get("hypothesis_refinement_refs") is None:
            data.pop("hypothesis_refinement_refs", None)
        if data.get("hypothesis") is None:
            data.pop("hypothesis", None)
        if data.get("competitive") is None:
            data.pop("competitive", None)
        if data.get("actions") is None:
            data.pop("actions", None)
        file_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def to_dict(self) -> dict:
        """dict로 변환한다."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskSpec":
        """dict에서 TaskSpec을 복원한다."""
        for field_name in ("task_id", "goal"):
            if field_name not in data or not data[field_name]:
                raise ValueError(f"TaskSpec 필수 필드 누락: '{field_name}'")

        actions = data.get("actions")
        if actions is not None:
            if not isinstance(actions, list):
                raise ValueError(
                    f"TaskSpec actions은 list여야 함: {type(actions).__name__}"
                )
            actions = [dict(action) for action in actions]

        core_refs = data.get("core_refs")
        if core_refs is not None:
            if not isinstance(core_refs, dict):
                raise ValueError(
                    f"TaskSpec core_refs는 dict여야 함: {type(core_refs).__name__}"
                )
            core_refs = {
                str(ref_name): str(ref_path)
                for ref_name, ref_path in core_refs.items()
            }

        hypothesis = data.get("hypothesis")
        if hypothesis is not None:
            if not isinstance(hypothesis, dict):
                raise ValueError(
                    f"TaskSpec hypothesis는 dict여야 함: {type(hypothesis).__name__}"
                )
            hypothesis = dict(hypothesis)

        generation_seed = data.get("generation_seed")
        if generation_seed is not None:
            if not isinstance(generation_seed, dict):
                raise ValueError(
                    "TaskSpec generation_seed는 dict여야 함: "
                    f"{type(generation_seed).__name__}"
                )
            generation_seed = dict(generation_seed)

        feedback_refs = data.get("feedback_refs")
        if feedback_refs is not None:
            if not isinstance(feedback_refs, list):
                raise ValueError(
                    "TaskSpec feedback_refs는 list여야 함: "
                    f"{type(feedback_refs).__name__}"
                )
            feedback_refs = [str(item) for item in feedback_refs]

        selection_pressure = data.get("selection_pressure")
        if selection_pressure is not None:
            if not isinstance(selection_pressure, dict):
                raise ValueError(
                    "TaskSpec selection_pressure는 dict여야 함: "
                    f"{type(selection_pressure).__name__}"
                )
            selection_pressure = dict(selection_pressure)

        selection_pressure_refs = data.get("selection_pressure_refs")
        if selection_pressure_refs is not None:
            if not isinstance(selection_pressure_refs, list):
                raise ValueError(
                    "TaskSpec selection_pressure_refs는 list여야 함: "
                    f"{type(selection_pressure_refs).__name__}"
                )
            selection_pressure_refs = [str(item) for item in selection_pressure_refs]

        hypothesis_refinement = data.get("hypothesis_refinement")
        if hypothesis_refinement is not None:
            if not isinstance(hypothesis_refinement, dict):
                raise ValueError(
                    "TaskSpec hypothesis_refinement는 dict여야 함: "
                    f"{type(hypothesis_refinement).__name__}"
                )
            hypothesis_refinement = dict(hypothesis_refinement)

        hypothesis_refinement_refs = data.get("hypothesis_refinement_refs")
        if hypothesis_refinement_refs is not None:
            if not isinstance(hypothesis_refinement_refs, list):
                raise ValueError(
                    "TaskSpec hypothesis_refinement_refs는 list여야 함: "
                    f"{type(hypothesis_refinement_refs).__name__}"
                )
            hypothesis_refinement_refs = [
                str(item) for item in hypothesis_refinement_refs
            ]

        competitive = data.get("competitive")
        if competitive is not None:
            if not isinstance(competitive, dict):
                raise ValueError(
                    f"TaskSpec competitive는 dict여야 함: {type(competitive).__name__}"
                )
            competitive = dict(competitive)

        return cls(
            task_id=str(data["task_id"]),
            goal=str(data["goal"]),
            scope=list(data.get("scope") or []),
            non_goals=list(data.get("non_goals") or []),
            acceptance_criteria=list(data.get("acceptance_criteria") or []),
            related_files=list(data.get("related_files") or []),
            related_tests=list(data.get("related_tests") or []),
            output_paths=list(data.get("output_paths") or []),
            core_refs=core_refs,
            generation_seed=generation_seed,
            feedback_refs=feedback_refs,
            selection_pressure=selection_pressure,
            selection_pressure_refs=selection_pressure_refs,
            hypothesis_refinement=hypothesis_refinement,
            hypothesis_refinement_refs=hypothesis_refinement_refs,
            hypothesis=hypothesis,
            competitive=competitive,
            actions=actions,
        )


@dataclass
class WorkItem:
    """TaskSpec에서 planner가 분해한 하위 작업."""

    item_id: str
    description: str
    status: str = "pending"
    depends_on: list[str] = field(default_factory=list)
    assigned_role: str = "executor"
    # V1: executor가 수행할 action. None이면 기존 stub 동작.
    action: dict | None = None
    # V1: reviewer가 증가시키는 재시도 카운트.
    retry_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkItem":
        action = data.get("action")
        if action is not None:
            action = dict(action)
        return cls(
            item_id=str(data["item_id"]),
            description=str(data["description"]),
            status=str(data.get("status", "pending")),
            depends_on=list(data.get("depends_on") or []),
            assigned_role=str(data.get("assigned_role", "executor")),
            action=action,
            retry_count=int(data.get("retry_count", 0)),
        )


@dataclass
class StepResult:
    """파이프라인의 단일 단계 실행 결과."""

    role: str
    status: str
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    # V1: adapter별 상세 dict.
    details: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StepResult":
        details = data.get("details")
        if details is not None:
            details = dict(details)
        return cls(
            role=str(data["role"]),
            status=str(data["status"]),
            summary=str(data.get("summary", "")),
            artifacts=list(data.get("artifacts") or []),
            errors=list(data.get("errors") or []),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            details=details,
        )


@dataclass
class RunState:
    """전체 run의 현재 상태. 파일로 저장/복원한다."""

    run_id: str
    task_spec: TaskSpec
    status: str = "running"
    current_iteration: int = 0
    max_iterations: int = 10
    current_phase: str = "planner"
    work_items: list[WorkItem] = field(default_factory=list)
    step_results: list[StepResult] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    finished_at: str | None = None
    termination_reason: str = ""
    core_bridge: dict | None = None
    competitive_generation: dict | None = None

    def to_dict(self) -> dict:
        """JSON 직렬화를 위한 dict 변환."""
        return {
            "run_id": self.run_id,
            "task_spec": self.task_spec.to_dict(),
            "status": self.status,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "current_phase": self.current_phase,
            "work_items": [work_item.to_dict() for work_item in self.work_items],
            "step_results": [
                step_result.to_dict() for step_result in self.step_results
            ],
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "termination_reason": self.termination_reason,
            "core_bridge": self.core_bridge,
            "competitive_generation": self.competitive_generation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunState":
        """dict에서 RunState를 복원한다."""
        try:
            return cls(
                run_id=str(data["run_id"]),
                task_spec=TaskSpec.from_dict(data["task_spec"]),
                status=str(data.get("status", "running")),
                current_iteration=int(data.get("current_iteration", 0)),
                max_iterations=int(data.get("max_iterations", 10)),
                current_phase=str(data.get("current_phase", "planner")),
                work_items=[
                    WorkItem.from_dict(work_item)
                    for work_item in (data.get("work_items") or [])
                ],
                step_results=[
                    StepResult.from_dict(step_result)
                    for step_result in (data.get("step_results") or [])
                ],
                started_at=str(data.get("started_at", "")),
                updated_at=str(data.get("updated_at", "")),
                finished_at=data.get("finished_at"),
                termination_reason=str(data.get("termination_reason", "")),
                core_bridge=dict(data["core_bridge"])
                if isinstance(data.get("core_bridge"), dict)
                else None,
                competitive_generation=dict(data["competitive_generation"])
                if isinstance(data.get("competitive_generation"), dict)
                else None,
            )
        except KeyError as exc:
            raise ValueError(f"RunState 필수 필드 누락: {exc}") from exc

    def to_json(self) -> str:
        """JSON 문자열을 반환한다."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
