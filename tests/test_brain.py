"""Cambrian Harness Brain (Task 26) 테스트.

models, checkpoint, pipeline, runner, report, CLI e2e 전체.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from engine.brain.checkpoint import CheckpointManager
from engine.brain.models import RunState, StepResult, TaskSpec, WorkItem
from engine.brain.pipeline import RolePipeline
from engine.brain.report import generate_report
from engine.brain.runner import RALFRunner
from engine.decision import MatrixDecider


# ═══════════════════════════════════════════════════════════
# 헬퍼
# ═══════════════════════════════════════════════════════════

def _make_spec(
    task_id: str = "task-001",
    goal: str = "hello 스킬에 검증 추가",
    scope: list[str] | None = None,
    related_tests: list[str] | None = None,
    output_paths: list[str] | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        goal=goal,
        scope=scope if scope is not None else ["입력 검증", "에러 처리"],
        non_goals=["출력 변경"],
        acceptance_criteria=["빈 입력 처리"],
        related_files=["skills/hello_world/execute/main.py"],
        related_tests=related_tests if related_tests is not None else [],
        output_paths=(
            output_paths if output_paths is not None
            else ["skills/hello_world/execute/main.py"]
        ),
    )


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _make_bridge_spec(core_refs: dict[str, str]) -> TaskSpec:
    return TaskSpec(
        task_id="task-core-bridge",
        goal="core artifact를 읽기 전용으로 요약한다",
        scope=["read-only bridge"],
        non_goals=["core 상태 변경"],
        acceptance_criteria=["report에 core summary 포함"],
        related_files=["engine/brain/report.py"],
        related_tests=[],
        output_paths=[],
        core_refs=core_refs,
    )


def _make_scenario_report() -> dict:
    return {
        "_snapshot_version": "1.0.0",
        "success": True,
        "scenario_name": "brain_bridge_scenario",
        "domain": "utility",
        "tags": ["bridge"],
        "total_inputs": 3,
        "successful_inputs": 3,
        "failed_inputs": 0,
        "success_rate": 1.0,
        "avg_execution_ms": 42,
        "winner_skill": "hello_world",
        "run_results": [],
        "eval_result": None,
        "evolve_result": None,
        "re_eval_result": None,
        "promote_recommendation": {
            "skill_id": "hello_world",
            "recommendation": "not_eligible",
            "eligible": False,
        },
        "timestamp": "2026-04-21T00:00:00Z",
    }


def _make_matrix_summary() -> dict:
    return {
        "_matrix_version": "1.0.0",
        "scenario_name": "brain_bridge_scenario",
        "scenario_path": "scenarios/bridge.json",
        "scenario_hash": "hash-001",
        "baseline_policy": "policies/base.json",
        "timestamp": "2026-04-21T00:00:00Z",
        "notes": "read-only bridge test",
        "profiles": [
            {
                "policy_path": "policies/base.json",
                "is_baseline": True,
                "success_rate": 0.7,
                "eval_pass_rate": 0.6,
                "avg_execution_ms": 120,
                "winner_skill": "hello_world",
                "promote_recommendation": "not_eligible",
                "verdict_vs_baseline": None,
            },
            {
                "policy_path": "policies/champion.json",
                "is_baseline": False,
                "success_rate": 0.9,
                "eval_pass_rate": 0.8,
                "avg_execution_ms": 80,
                "winner_skill": "hello_world",
                "promote_recommendation": "candidate",
                "verdict_vs_baseline": "improved",
            },
        ],
        "overall_verdict": "1 improved, 0 mixed, 0 regressed",
    }


# ═══════════════════════════════════════════════════════════
# 1. TaskSpec from_yaml
# ═══════════════════════════════════════════════════════════

def test_task_spec_from_yaml(tmp_path: Path) -> None:
    spec_path = tmp_path / "task.yaml"
    data = {
        "task_id": "task-100",
        "goal": "테스트 목적",
        "scope": ["s1", "s2"],
        "non_goals": ["n1"],
        "acceptance_criteria": ["ac1"],
        "related_files": ["a.py"],
        "related_tests": ["test_a.py"],
        "output_paths": ["a.py"],
    }
    _write_yaml(spec_path, data)

    spec = TaskSpec.from_yaml(spec_path)

    assert spec.task_id == "task-100"
    assert spec.goal == "테스트 목적"
    assert spec.scope == ["s1", "s2"]
    assert spec.non_goals == ["n1"]
    assert spec.related_tests == ["test_a.py"]

    # 필수 필드 누락 시 ValueError
    bad_path = tmp_path / "bad.yaml"
    _write_yaml(bad_path, {"goal": "missing id"})
    with pytest.raises(ValueError, match="task_id"):
        TaskSpec.from_yaml(bad_path)


# ═══════════════════════════════════════════════════════════
# 2. TaskSpec round-trip
# ═══════════════════════════════════════════════════════════

def test_task_spec_round_trip(tmp_path: Path) -> None:
    original = _make_spec(task_id="task-rt", goal="라운드트립")
    out_path = tmp_path / "rt.yaml"
    original.to_yaml(out_path)
    loaded = TaskSpec.from_yaml(out_path)
    assert loaded == original


# ═══════════════════════════════════════════════════════════
# 3. Checkpoint save/load
# ═══════════════════════════════════════════════════════════

def test_task_spec_core_refs_round_trip(tmp_path: Path) -> None:
    spec_path = tmp_path / "task_core.yaml"
    data = {
        "task_id": "task-core-refs",
        "goal": "core refs round trip",
        "scope": ["bridge"],
        "core_refs": {
            "scenario_report": "artifacts/scenario.json",
            "matrix_summary": "artifacts/_matrix_summary.json",
        },
    }
    _write_yaml(spec_path, data)

    loaded = TaskSpec.from_yaml(spec_path)

    assert loaded.core_refs == data["core_refs"]

    round_trip_path = tmp_path / "task_core_round_trip.yaml"
    loaded.to_yaml(round_trip_path)
    reparsed = TaskSpec.from_yaml(round_trip_path)
    assert reparsed.core_refs == data["core_refs"]


def test_checkpoint_save_load(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    cm = CheckpointManager(runs)
    run_id = "brain-20260414-120000-abcd"

    cm.create_run_dir(run_id)
    spec = _make_spec()
    state = RunState(
        run_id=run_id,
        task_spec=spec,
        status="running",
        current_iteration=2,
        max_iterations=10,
        current_phase="executor",
        work_items=[WorkItem(item_id="w1", description="d1", status="done")],
        step_results=[
            StepResult(
                role="planner", status="success", summary="s",
                artifacts=[], errors=[],
                started_at="t1", finished_at="t2",
            ),
        ],
        started_at="t0", updated_at="t5", finished_at=None,
        termination_reason="",
    )

    cm.save_state(state)
    loaded = cm.load_state(run_id)

    assert loaded.run_id == state.run_id
    assert loaded.task_spec == spec
    assert loaded.current_iteration == 2
    assert loaded.current_phase == "executor"
    assert len(loaded.work_items) == 1
    assert loaded.work_items[0].status == "done"
    assert len(loaded.step_results) == 1
    assert loaded.step_results[0].role == "planner"


# ═══════════════════════════════════════════════════════════
# 4. Checkpoint atomic write
# ═══════════════════════════════════════════════════════════

def test_checkpoint_save_load_with_core_bridge(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    cm = CheckpointManager(runs)
    run_id = "brain-core-bridge-checkpoint"

    cm.create_run_dir(run_id)
    spec = _make_bridge_spec({
        "matrix_summary": "artifacts/_matrix_summary.json",
    })
    state = RunState(
        run_id=run_id,
        task_spec=spec,
        core_bridge={
            "read_only": True,
            "artifact_count": 1,
            "loaded_count": 1,
            "missing_count": 0,
            "invalid_count": 0,
            "artifacts": [
                {
                    "ref_name": "matrix_summary",
                    "artifact_type": "matrix_summary",
                    "path": "artifacts/_matrix_summary.json",
                    "resolved_path": str(
                        (tmp_path / "artifacts" / "_matrix_summary.json").resolve()
                    ),
                    "status": "loaded",
                    "summary": {
                        "scenario_name": "brain_bridge_scenario",
                    },
                    "errors": [],
                },
            ],
        },
    )

    cm.save_state(state)
    loaded = cm.load_state(run_id)

    assert loaded.core_bridge is not None
    assert loaded.core_bridge["read_only"] is True
    assert loaded.core_bridge["artifact_count"] == 1
    assert loaded.core_bridge["artifacts"][0]["ref_name"] == "matrix_summary"


def test_checkpoint_atomic_write(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    cm = CheckpointManager(runs)
    run_id = "brain-atomic-test"
    cm.create_run_dir(run_id)

    spec = _make_spec()
    state = RunState(run_id=run_id, task_spec=spec)
    cm.save_state(state)

    target = runs / run_id / "run_state.json"
    assert target.exists()

    # 내용이 valid JSON이고 파싱 가능
    raw = target.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["run_id"] == run_id
    assert parsed["task_spec"]["task_id"] == spec.task_id

    # 임시 파일(.tmp)이 남아있지 않아야 함
    tmp_leftovers = list((runs / run_id).glob(".run_state.json.*.tmp"))
    assert tmp_leftovers == []

    # 여러 번 저장해도 깨지지 않음
    for i in range(5):
        state.current_iteration = i
        cm.save_state(state)
    loaded = cm.load_state(run_id)
    assert loaded.current_iteration == 4


# ═══════════════════════════════════════════════════════════
# 5. Pipeline planner
# ═══════════════════════════════════════════════════════════

def test_pipeline_planner(tmp_path: Path) -> None:
    pipeline = RolePipeline(workspace=tmp_path)
    spec = _make_spec(scope=["A", "B", "C"])
    state = RunState(run_id="r1", task_spec=spec)

    result = pipeline.run_planner(state)

    assert result.role == "planner"
    assert result.status == "success"
    assert len(state.work_items) == 3
    assert state.work_items[0].item_id == "work-001"
    assert state.work_items[0].description == "A"
    assert state.work_items[2].item_id == "work-003"
    assert all(w.status == "pending" for w in state.work_items)
    assert all(w.assigned_role == "executor" for w in state.work_items)

    # 재실행 시 skipped
    result2 = pipeline.run_planner(state)
    assert result2.status == "skipped"
    assert len(state.work_items) == 3


# ═══════════════════════════════════════════════════════════
# 6. Pipeline full cycle
# ═══════════════════════════════════════════════════════════

def test_pipeline_full_cycle(tmp_path: Path) -> None:
    # related_tests 파일 실제 생성
    test_file = tmp_path / "test_a.py"
    test_file.write_text("# test\n", encoding="utf-8")

    pipeline = RolePipeline(workspace=tmp_path)
    spec = _make_spec(
        scope=["s1"],
        related_tests=["test_a.py"],
    )
    state = RunState(run_id="r2", task_spec=spec)

    r1 = pipeline.run_planner(state)
    r2 = pipeline.run_executor(state)
    r3 = pipeline.run_tester(state)
    r4 = pipeline.run_reviewer(state)

    results = [r1, r2, r3, r4]
    assert [r.role for r in results] == [
        "planner", "executor", "tester", "reviewer",
    ]
    assert r1.status == "success"
    assert r2.status == "success"
    assert r3.status == "success"  # test_a.py가 존재
    assert r4.status == "success"

    # executor 후 done 1개
    assert sum(1 for w in state.work_items if w.status == "done") == 1
    # reviewer summary에 완료 기록
    assert "완료" in r4.summary


# ═══════════════════════════════════════════════════════════
# 7. RALF max_iterations 종료
# ═══════════════════════════════════════════════════════════

def test_ralf_loop_max_iterations(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    # failed 상태로 영원히 끝나지 않게 하려면... 실제로는 모든 scope가 done되면
    # all_items_done으로 조기종료됨. 이를 피하려면 scope를 비워 default work_item
    # 1개로 두고, 1회 reviewer 후 다음 iteration 시작 시점에 all_done 판정됨.
    # max_iterations 도달을 테스트하려면 work_items를 동적으로 증가시키는 것
    # 이 아니라, reviewer가 failed로 재설정 반복하는 시나리오를 만든다.
    # 가장 단순하게: work_items 없이 scope 여러 개로 시작 → executor 1회당
    # 1개 done → 모두 done될 때까지 iter 누적. scope 수 > max_iterations면
    # max_iterations 먼저 도달.
    runner = RALFRunner(runs_dir=runs, workspace=tmp_path)
    spec = _make_spec(
        scope=[f"item-{i}" for i in range(5)],  # 5개 scope
        related_tests=[],
    )
    state = runner.run(spec, max_iterations=2)

    assert state.status == "max_iter_reached"
    assert state.termination_reason == "max_iterations"
    assert state.current_iteration == 2


# ═══════════════════════════════════════════════════════════
# 8. RALF all done 종료
# ═══════════════════════════════════════════════════════════

def test_ralf_loop_all_done(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runner = RALFRunner(runs_dir=runs, workspace=tmp_path)
    spec = _make_spec(scope=["only_one"], related_tests=[])
    state = runner.run(spec, max_iterations=10)

    assert state.status == "completed"
    assert state.termination_reason == "all_items_done"
    # iteration 0에서 executor가 유일한 item을 done 처리,
    # iter 0 reviewer 후 iter=1이 되어 종료판정에서 all_done 확인
    assert state.current_iteration >= 1
    assert all(w.status == "done" for w in state.work_items)

    # report.json이 생성됐는지
    report_path = runs / state.run_id / "report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["termination_reason"] == "all_items_done"


# ═══════════════════════════════════════════════════════════
# 9. RALF resume
# ═══════════════════════════════════════════════════════════

def test_ralf_loop_resume(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runner = RALFRunner(runs_dir=runs, workspace=tmp_path)
    spec = _make_spec(scope=["a", "b", "c"], related_tests=[])

    # max_iterations=1로 강제 중단
    state1 = runner.run(spec, max_iterations=1)
    assert state1.status == "max_iter_reached"
    run_id = state1.run_id

    # max 증가시킨 resume — 직접 state 수정 후 save, 그리고 resume
    cm = CheckpointManager(runs)
    loaded = cm.load_state(run_id)
    loaded.max_iterations = 10
    loaded.status = "running"
    loaded.termination_reason = ""
    loaded.finished_at = None
    cm.save_state(loaded)

    state2 = runner.resume(run_id)

    assert state2.run_id == run_id
    assert state2.status == "completed"
    assert state2.termination_reason == "all_items_done"
    assert all(w.status == "done" for w in state2.work_items)


# ═══════════════════════════════════════════════════════════
# 10. generate_report
# ═══════════════════════════════════════════════════════════

def test_generate_report(tmp_path: Path) -> None:
    spec = _make_spec(scope=["s1", "s2"])
    state = RunState(
        run_id="brain-report-test",
        task_spec=spec,
        status="completed",
        current_iteration=3,
        max_iterations=10,
        work_items=[
            WorkItem(item_id="w1", description="작업1", status="done"),
            WorkItem(item_id="w2", description="작업2", status="done"),
        ],
        step_results=[
            StepResult(role="planner", status="success", summary="plan"),
            StepResult(role="executor", status="success", summary="exec"),
            StepResult(role="tester", status="success", summary="test1"),
            StepResult(role="tester", status="skipped", summary="test2"),
            StepResult(role="reviewer", status="success", summary="rev"),
        ],
        started_at="2026-04-14T10:00:00Z",
        finished_at="2026-04-14T10:05:00Z",
        termination_reason="all_items_done",
    )

    report = generate_report(state)

    assert report["run_id"] == "brain-report-test"
    assert report["task_id"] == spec.task_id
    assert report["status"] == "completed"
    assert report["changes_summary"] == ["작업1", "작업2"]
    assert report["test_results"] == {"passed": 1, "failed": 0, "skipped": 1}
    assert report["remaining_risks"] == []
    assert report["next_actions"] == []
    assert report["total_iterations"] == 3
    assert report["termination_reason"] == "all_items_done"
    assert report["provenance_ref"] == "brain-report-test"

    # failed가 있을 때 next_actions 생성
    state.work_items.append(
        WorkItem(item_id="w3", description="실패", status="failed")
    )
    report2 = generate_report(state)
    assert len(report2["remaining_risks"]) == 1
    assert "[failed]" in report2["remaining_risks"][0]
    assert len(report2["next_actions"]) >= 1


# ═══════════════════════════════════════════════════════════
# 11. E2E smoke — CLI로 실제 실행
# ═══════════════════════════════════════════════════════════

def test_runner_core_bridge_summary_in_state_and_report(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    artifacts_dir = tmp_path / "artifacts"
    scenario_path = artifacts_dir / "scenario_report.json"
    matrix_path = artifacts_dir / "_matrix_summary.json"
    decision_path = artifacts_dir / "_decision_report.json"

    scenario_report = _make_scenario_report()
    matrix_summary = _make_matrix_summary()
    decision_report = MatrixDecider().decide(matrix_summary)
    decision_report["matrix_summary_path"] = str(matrix_path)

    _write_json(scenario_path, scenario_report)
    _write_json(matrix_path, matrix_summary)
    _write_json(decision_path, decision_report)

    before_bytes = {
        scenario_path: scenario_path.read_bytes(),
        matrix_path: matrix_path.read_bytes(),
        decision_path: decision_path.read_bytes(),
    }

    spec = _make_bridge_spec({
        "scenario_report": "artifacts/scenario_report.json",
        "matrix_summary": "artifacts/_matrix_summary.json",
        "decision_report": "artifacts/_decision_report.json",
    })
    runner = RALFRunner(runs_dir=runs_dir, workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)

    assert state.status == "completed"
    assert state.core_bridge is not None
    assert state.core_bridge["read_only"] is True
    assert state.core_bridge["artifact_count"] == 3
    assert state.core_bridge["loaded_count"] == 3
    assert state.core_bridge["missing_count"] == 0
    assert state.core_bridge["invalid_count"] == 0

    artifact_map = {
        artifact["ref_name"]: artifact
        for artifact in state.core_bridge["artifacts"]
    }
    assert artifact_map["scenario_report"]["summary"]["winner_skill"] == "hello_world"
    assert artifact_map["matrix_summary"]["summary"]["improved_count"] == 1
    assert artifact_map["decision_report"]["summary"]["champion_policy"] == "policies/champion.json"

    run_dir = runs_dir / state.run_id
    run_state_data = json.loads(
        (run_dir / "run_state.json").read_text(encoding="utf-8")
    )
    report_data = json.loads(
        (run_dir / "report.json").read_text(encoding="utf-8")
    )

    assert run_state_data["core_bridge"]["artifact_count"] == 3
    assert report_data["core_bridge"]["loaded_count"] == 3
    assert report_data["core_bridge"]["artifacts"][0]["status"] == "loaded"

    after_bytes = {
        scenario_path: scenario_path.read_bytes(),
        matrix_path: matrix_path.read_bytes(),
        decision_path: decision_path.read_bytes(),
    }
    assert after_bytes == before_bytes


def test_runner_core_bridge_missing_and_invalid_artifacts(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    artifacts_dir = tmp_path / "artifacts"
    invalid_path = artifacts_dir / "broken_decision.json"
    invalid_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_path.write_text("{ this is not valid json", encoding="utf-8")

    spec = _make_bridge_spec({
        "matrix_summary": "artifacts/missing_matrix.json",
        "decision_report": "artifacts/broken_decision.json",
    })
    runner = RALFRunner(runs_dir=runs_dir, workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)

    assert state.status == "completed"
    assert state.core_bridge is not None
    assert state.core_bridge["artifact_count"] == 2
    assert state.core_bridge["loaded_count"] == 0
    assert state.core_bridge["missing_count"] == 1
    assert state.core_bridge["invalid_count"] == 1

    artifact_map = {
        artifact["ref_name"]: artifact
        for artifact in state.core_bridge["artifacts"]
    }
    assert artifact_map["matrix_summary"]["status"] == "missing"
    assert artifact_map["decision_report"]["status"] == "invalid"

    report_data = json.loads(
        (runs_dir / state.run_id / "report.json").read_text(encoding="utf-8")
    )
    report_artifact_map = {
        artifact["ref_name"]: artifact
        for artifact in report_data["core_bridge"]["artifacts"]
    }
    assert report_artifact_map["matrix_summary"]["status"] == "missing"
    assert report_artifact_map["decision_report"]["status"] == "invalid"


def test_e2e_smoke(tmp_path: Path) -> None:
    """CLI entry point 호출로 TaskSpec YAML → report.json 전체 흐름."""
    spec_path = tmp_path / "task.yaml"
    _write_yaml(spec_path, {
        "task_id": "task-e2e",
        "goal": "e2e smoke",
        "scope": ["only_one"],
        "related_tests": [],
        "output_paths": [],
    })

    runs_dir = tmp_path / ".cambrian" / "brain" / "runs"

    # CLI 직접 호출 대신 핸들러 로직 사용 (subprocess 없이)
    from engine.brain.models import TaskSpec
    spec = TaskSpec.from_yaml(spec_path)
    runner = RALFRunner(runs_dir=runs_dir, workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)

    assert state.status == "completed"
    report_path = runs_dir / state.run_id / "report.json"
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["task_id"] == "task-e2e"
    assert report["status"] == "completed"

    # 디렉토리 구조 검증
    run_dir = runs_dir / state.run_id
    assert (run_dir / "task_spec.yaml").exists()
    assert (run_dir / "run_state.json").exists()
    assert (run_dir / "iterations").is_dir()
    iter_files = list((run_dir / "iterations").glob("iter_*.json"))
    assert len(iter_files) >= 1


# ═══════════════════════════════════════════════════════════════════
# Task 27 V1 tests
# ═══════════════════════════════════════════════════════════════════

from engine.brain.adapters.executor_v1 import ExecutorV1
from engine.brain.adapters.reviewer_v1 import ReviewerV1
from engine.brain.adapters.tester_v1 import TesterV1


def _make_work_item(
    item_id: str = "work-001",
    description: str = "desc",
    status: str = "pending",
    action: dict | None = None,
    retry_count: int = 0,
) -> WorkItem:
    return WorkItem(
        item_id=item_id,
        description=description,
        status=status,
        action=action,
        retry_count=retry_count,
    )


# ───────────────────────────────────────────────────────────
# Executor 테스트 (5개)
# ───────────────────────────────────────────────────────────

def test_executor_write_file(tmp_path: Path) -> None:
    """ExecutorV1.execute가 write_file로 파일을 생성한다."""
    executor = ExecutorV1(tmp_path)
    wi = _make_work_item(
        action={
            "type": "write_file",
            "target_path": "hello.txt",
            "content": "world",
        },
    )

    result = executor.execute(wi)

    assert result.status == "success"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "world"
    assert wi.status == "done"
    assert result.details is not None
    assert result.details["action_type"] == "write_file"
    assert result.artifacts == ["hello.txt"]


def test_executor_patch_file(tmp_path: Path) -> None:
    """ExecutorV1.execute가 patch_file로 파일을 수정한다."""
    (tmp_path / "target.py").write_text(
        "prefix old_code suffix", encoding="utf-8",
    )
    executor = ExecutorV1(tmp_path)
    wi = _make_work_item(
        action={
            "type": "patch_file",
            "target_path": "target.py",
            "old_text": "old_code",
            "new_text": "new_code",
        },
    )

    result = executor.execute(wi)

    assert result.status == "success"
    updated = (tmp_path / "target.py").read_text(encoding="utf-8")
    assert "new_code" in updated
    assert "old_code" not in updated
    assert wi.status == "done"


def test_executor_patch_not_found(tmp_path: Path) -> None:
    """old_text가 파일에 없으면 failure를 반환한다."""
    (tmp_path / "target.py").write_text("contents", encoding="utf-8")
    executor = ExecutorV1(tmp_path)
    wi = _make_work_item(
        action={
            "type": "patch_file",
            "target_path": "target.py",
            "old_text": "NOT_IN_FILE_XYZ",
            "new_text": "replacement",
        },
    )

    result = executor.execute(wi)

    assert result.status == "failure"
    assert wi.status == "failed"
    assert any("찾을 수 없음" in e or "not found" in e.lower()
               for e in result.errors + [result.summary])


def test_executor_path_traversal(tmp_path: Path) -> None:
    """../가 포함된 경로는 거부된다."""
    executor = ExecutorV1(tmp_path)
    wi = _make_work_item(
        action={
            "type": "write_file",
            "target_path": "../escape.txt",
            "content": "x",
        },
    )

    result = executor.execute(wi)

    assert result.status == "failure"
    assert wi.status == "failed"
    # 실제로 파일이 escape되지 않았는지 확인
    assert not (tmp_path.parent / "escape.txt").exists()


def test_executor_backup_created(tmp_path: Path) -> None:
    """기존 파일 수정 시 .bak이 생성된다."""
    existing = tmp_path / "exist.py"
    existing.write_text("original", encoding="utf-8")
    executor = ExecutorV1(tmp_path)
    wi = _make_work_item(
        action={
            "type": "write_file",
            "target_path": "exist.py",
            "content": "new",
        },
    )

    result = executor.execute(wi)

    assert result.status == "success"
    assert existing.read_text(encoding="utf-8") == "new"
    bak = tmp_path / "exist.py.bak"
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == "original"
    assert result.details["backup_path"] is not None


# ───────────────────────────────────────────────────────────
# Tester 테스트 (4개)
# ───────────────────────────────────────────────────────────

def test_tester_passing(tmp_path: Path) -> None:
    """통과하는 테스트를 실행하면 passed > 0이고 status=success."""
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8",
    )
    tester = TesterV1(tmp_path)
    spec = _make_spec(related_tests=["test_ok.py"])
    state = RunState(run_id="r-pass", task_spec=spec)

    step, detail = tester.run_tests(state)

    assert step.status == "success"
    assert detail.passed >= 1
    assert detail.failed == 0
    assert detail.exit_code == 0
    assert step.details is not None


def test_tester_failing(tmp_path: Path) -> None:
    """실패하는 테스트를 실행하면 failed > 0이고 status=failure."""
    (tmp_path / "test_fail.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8",
    )
    tester = TesterV1(tmp_path)
    spec = _make_spec(related_tests=["test_fail.py"])
    state = RunState(run_id="r-fail", task_spec=spec)

    step, detail = tester.run_tests(state)

    assert step.status == "failure"
    assert detail.failed >= 1
    assert detail.exit_code != 0


def test_tester_no_tests(tmp_path: Path) -> None:
    """related_tests가 비어있으면 skipped."""
    tester = TesterV1(tmp_path)
    spec = _make_spec(related_tests=[])
    state = RunState(run_id="r-none", task_spec=spec)

    step, detail = tester.run_tests(state)

    assert step.status == "skipped"
    assert detail.passed == 0
    assert detail.failed == 0


def test_tester_missing_files(tmp_path: Path) -> None:
    """존재하지 않는 테스트 파일은 필터링되고 skipped."""
    tester = TesterV1(tmp_path)
    spec = _make_spec(related_tests=["nonexistent_test.py"])
    state = RunState(run_id="r-missing", task_spec=spec)

    step, detail = tester.run_tests(state)

    assert step.status == "skipped"
    assert detail.test_files == []


# ───────────────────────────────────────────────────────────
# Reviewer 테스트 (5개)
# ───────────────────────────────────────────────────────────

def _state_with_steps(
    task_spec: TaskSpec,
    work_items: list[WorkItem],
    tester_status: str = "success",
    tester_details: dict | None = None,
) -> RunState:
    """reviewer 테스트용 RunState 헬퍼."""
    state = RunState(
        run_id="r-review",
        task_spec=task_spec,
        work_items=work_items,
        step_results=[
            StepResult(
                role="executor", status="success", summary="exec done",
                details={"mode": "v1"},
            ),
            StepResult(
                role="tester", status=tester_status,
                summary=f"tester {tester_status}",
                details=tester_details
                if tester_details is not None
                else {"exit_code": 0 if tester_status == "success" else 1,
                      "passed": 1 if tester_status == "success" else 0,
                      "failed": 0 if tester_status == "success" else 1},
            ),
        ],
    )
    return state


def test_reviewer_all_pass(tmp_path: Path) -> None:
    """모든 criteria 충족 + 테스트 통과 → passed=True."""
    spec = _make_spec(
        scope=["x"],
        related_tests=["test_x.py"],
        output_paths=[],
    )
    spec.acceptance_criteria = ["테스트 통과"]
    state = _state_with_steps(
        spec,
        [_make_work_item(status="done")],
        tester_status="success",
    )
    reviewer = ReviewerV1(tmp_path)

    step, verdict = reviewer.review(state)

    assert verdict.passed is True
    assert step.status == "success"
    assert state.status == "completed"
    assert state.termination_reason == "all_items_done"


def test_reviewer_test_failure(tmp_path: Path) -> None:
    """tester failure → passed=False 강제."""
    spec = _make_spec(
        scope=["x"], related_tests=["test_x.py"], output_paths=[],
    )
    spec.acceptance_criteria = ["테스트 통과"]
    state = _state_with_steps(
        spec,
        [_make_work_item(status="done")],
        tester_status="failure",
    )
    reviewer = ReviewerV1(tmp_path)

    step, verdict = reviewer.review(state)

    assert verdict.passed is False
    assert step.status == "failure"
    assert any("pytest" in a.lower() or "테스트" in a
               for a in verdict.next_actions)


def test_reviewer_file_criterion(tmp_path: Path) -> None:
    """'파일 생성' criterion + 파일 존재 → met=True."""
    # output_path의 파일을 실제로 생성
    (tmp_path / "validate.py").write_text("# validate", encoding="utf-8")

    spec = _make_spec(
        scope=["x"],
        related_tests=[],
        output_paths=["validate.py"],
    )
    spec.acceptance_criteria = ["validate.py 파일이 생성됨"]
    state = _state_with_steps(
        spec,
        [_make_work_item(status="done")],
        tester_status="skipped",
        tester_details={"exit_code": -1, "passed": 0, "failed": 0},
    )
    reviewer = ReviewerV1(tmp_path)

    step, verdict = reviewer.review(state)

    assert verdict.criteria_results[0]["met"] is True
    assert verdict.criteria_results[0]["kind"] == "file"
    assert "validate.py" in verdict.criteria_results[0]["evidence"]


def test_reviewer_retry_items(tmp_path: Path) -> None:
    """failed items → retry_items 생성 및 work_item.retry_count 증가."""
    spec = _make_spec(scope=["a"], related_tests=[], output_paths=[])
    spec.acceptance_criteria = []  # criteria 없음
    failed_item = _make_work_item(
        item_id="work-001", status="failed", retry_count=0,
    )
    state = _state_with_steps(
        spec, [failed_item],
        tester_status="skipped",
        tester_details={"exit_code": -1, "passed": 0, "failed": 0},
    )
    reviewer = ReviewerV1(tmp_path)

    step, verdict = reviewer.review(state)

    assert "work-001" in verdict.retry_items
    assert failed_item.status == "pending"  # retry로 재설정
    assert failed_item.retry_count == 1
    assert state.status != "failed"  # retry 가능이므로 fail 확정 아님


def test_reviewer_max_retry(tmp_path: Path) -> None:
    """retry_count >= 2 → retry 불가, state.status=failed."""
    spec = _make_spec(scope=["a"], related_tests=[], output_paths=[])
    spec.acceptance_criteria = []
    exhausted = _make_work_item(
        item_id="work-001", status="failed", retry_count=2,
    )
    state = _state_with_steps(
        spec, [exhausted],
        tester_status="skipped",
        tester_details={"exit_code": -1, "passed": 0, "failed": 0},
    )
    reviewer = ReviewerV1(tmp_path)

    step, verdict = reviewer.review(state)

    assert verdict.retry_items == []
    assert exhausted.status == "failed"  # 재설정 안 됨
    assert exhausted.retry_count == 2
    assert state.status == "failed"
    assert state.termination_reason == "reviewer_fail"


# ───────────────────────────────────────────────────────────
# E2E + Provenance 테스트 (2개)
# ───────────────────────────────────────────────────────────

def test_e2e_real_execution(tmp_path: Path) -> None:
    """실제 파일 생성 + pytest 실행 + reviewer 판정 전체 흐름."""
    # 생성될 테스트 파일을 미리 spec의 output_paths에 명시
    spec_data = {
        "task_id": "task-real",
        "goal": "실제 작업",
        "scope": ["test_greet.py 생성"],
        "acceptance_criteria": [
            "test_greet.py 파일이 생성됨",
            "테스트 통과",
        ],
        "related_tests": ["test_greet.py"],
        "output_paths": ["test_greet.py"],
        "actions": [
            {
                "type": "write_file",
                "target_path": "test_greet.py",
                "content": (
                    "def test_greet():\n"
                    "    assert 'hello' == 'hello'\n"
                ),
            },
        ],
    }
    spec_path = tmp_path / "task.yaml"
    _write_yaml(spec_path, spec_data)

    runs_dir = tmp_path / ".cambrian" / "brain" / "runs"
    runner = RALFRunner(runs_dir=runs_dir, workspace=tmp_path)
    spec = TaskSpec.from_yaml(spec_path)
    state = runner.run(spec, max_iterations=5)

    # 완료 상태 확인
    assert state.status == "completed"
    # 파일 실제 생성 확인
    assert (tmp_path / "test_greet.py").exists()

    # report.json + provenance_handoff 확인
    report_path = runs_dir / state.run_id / "report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert "provenance_handoff" in report
    handoff = report["provenance_handoff"]
    assert handoff["run_id"] == state.run_id
    assert "test_greet.py" in handoff["files_created"]
    assert handoff["reviewer_passed"] is True
    assert handoff["test_exit_code"] == 0
    assert handoff["adoption_ready"] is True


def test_report_provenance_handoff(tmp_path: Path) -> None:
    """generate_report 결과의 provenance_handoff 필드 전체 검증."""
    spec = _make_spec(scope=["s"], related_tests=[], output_paths=[])
    state = RunState(
        run_id="brain-prov-test",
        task_spec=spec,
        status="completed",
        current_iteration=1,
        work_items=[
            WorkItem(item_id="w1", description="d1", status="done"),
        ],
        step_results=[
            StepResult(
                role="executor", status="success", summary="e",
                artifacts=["file_a.py"],
                details={
                    "mode": "v1",
                    "action_type": "write_file",
                    "target_path": "file_a.py",
                    "backup_path": None,
                },
            ),
            StepResult(
                role="executor", status="success", summary="e2",
                artifacts=["file_b.py"],
                details={
                    "mode": "v1",
                    "action_type": "patch_file",
                    "target_path": "file_b.py",
                    "backup_path": "file_b.py.bak",
                },
            ),
            StepResult(
                role="tester", status="success", summary="t",
                details={
                    "exit_code": 0, "passed": 3, "failed": 0,
                    "errors": 0, "skipped": 0,
                },
            ),
            StepResult(
                role="reviewer", status="success", summary="r",
                details={
                    "passed": True,
                    "conclusion": "모두 통과",
                    "next_actions": [],
                    "retry_items": [],
                    "criteria_results": [],
                },
            ),
        ],
        termination_reason="all_items_done",
    )

    report = generate_report(state)
    handoff = report["provenance_handoff"]

    expected_keys = {
        "run_id", "task_spec_path", "run_state_path",
        "iteration_logs_dir", "report_path",
        "files_created", "files_modified", "tests_executed",
        "test_exit_code", "reviewer_passed", "reviewer_conclusion",
        "adoption_ready", "stable_ref",
    }
    assert expected_keys.issubset(handoff.keys())
    assert handoff["run_id"] == "brain-prov-test"
    assert handoff["stable_ref"] == "brain-prov-test"
    assert handoff["files_created"] == ["file_a.py"]
    assert handoff["files_modified"] == ["file_b.py"]
    assert handoff["test_exit_code"] == 0
    assert handoff["reviewer_passed"] is True
    assert handoff["adoption_ready"] is True
    assert report["test_results"]["passed"] == 3
    assert report["reviewer_conclusion"] == "모두 통과"


# ═══════════════════════════════════════════════════════════════════
# Task 28 — Harness-to-Adoption Handoff 테스트
# ═══════════════════════════════════════════════════════════════════

from engine.brain.handoff import (
    HandoffGenerator, HandoffRecord, HandoffValidator, SCHEMA_VERSION,
)


def _create_complete_brain_run(
    runs_dir: Path,
    run_id: str = "brain-20260414-100000-a1b2",
    task_id: str = "task-001",
    status: str = "completed",
    reviewer_passed: bool = True,
    adoption_ready: bool = True,
    test_exit_code: int = 0,
    include_report: bool = True,
    include_run_state: bool = True,
    include_task_spec: bool = True,
    include_provenance_handoff: bool = True,
    include_stable_ref: bool = True,
) -> Path:
    """테스트용 완전한 brain run 결과 구조를 생성한다.

    include_* 플래그로 특정 파일/필드를 의도적으로 누락시킬 수 있다.
    """
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "iterations").mkdir(parents=True, exist_ok=True)

    task_spec_data = {
        "task_id": task_id,
        "goal": "test goal",
        "scope": ["s1"],
        "non_goals": [],
        "acceptance_criteria": ["test pass"],
        "related_files": [],
        "related_tests": [],
        "output_paths": [],
    }

    if include_task_spec:
        (run_dir / "task_spec.yaml").write_text(
            yaml.safe_dump(task_spec_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    if include_run_state:
        run_state = {
            "run_id": run_id,
            "task_spec": task_spec_data,
            "status": status,
            "current_iteration": 1,
            "max_iterations": 10,
            "current_phase": "executor",
            "work_items": [],
            "step_results": [],
            "started_at": "2026-04-14T10:00:00Z",
            "updated_at": "2026-04-14T10:05:00Z",
            "finished_at": "2026-04-14T10:05:00Z",
            "termination_reason": "all_items_done",
        }
        (run_dir / "run_state.json").write_text(
            json.dumps(run_state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if include_report:
        report: dict = {
            "run_id": run_id,
            "task_id": task_id,
            "status": status,
            "remaining_risks": [],
            "next_actions": [],
            "reviewer_conclusion": "모든 작업 완료",
        }
        if include_provenance_handoff:
            prov: dict = {
                "run_id": run_id,
                "reviewer_passed": reviewer_passed,
                "adoption_ready": adoption_ready,
                "test_exit_code": test_exit_code,
                "files_created": ["test_file.py"],
                "files_modified": [],
                "tests_executed": ["tests/test_ok.py"],
                "reviewer_conclusion": "모든 작업 완료",
            }
            if include_stable_ref:
                prov["stable_ref"] = run_id
            report["provenance_handoff"] = prov
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return run_dir


# ───────────────────────────────────────────────────────────────
# Validator 테스트 (5개)
# ───────────────────────────────────────────────────────────────

def test_handoff_validator_ready(tmp_path: Path) -> None:
    """completed + adoption_ready=true run → status='ready', block_reasons=[]."""
    runs_dir = tmp_path / "runs"
    run_id = "brain-ready-001"
    _create_complete_brain_run(runs_dir, run_id=run_id)

    validator = HandoffValidator()
    status, reasons = validator.validate(runs_dir, run_id)

    assert status == "ready"
    assert reasons == []


def test_handoff_validator_blocked_reviewer(tmp_path: Path) -> None:
    """reviewer_passed=false → blocked."""
    runs_dir = tmp_path / "runs"
    run_id = "brain-blocked-rev"
    _create_complete_brain_run(
        runs_dir, run_id=run_id, reviewer_passed=False,
        # adoption_ready도 false로 세팅하여 현실적인 실패 상황 모사
        adoption_ready=False,
    )

    validator = HandoffValidator()
    status, reasons = validator.validate(runs_dir, run_id)

    assert status == "blocked"
    assert any("reviewer did not pass" in r for r in reasons)


def test_handoff_validator_blocked_tests(tmp_path: Path) -> None:
    """test_exit_code != 0 → blocked + reason 포함."""
    runs_dir = tmp_path / "runs"
    run_id = "brain-blocked-test"
    _create_complete_brain_run(
        runs_dir, run_id=run_id, test_exit_code=1,
        adoption_ready=False,
    )

    validator = HandoffValidator()
    status, reasons = validator.validate(runs_dir, run_id)

    assert status == "blocked"
    assert any("tests did not pass" in r for r in reasons)
    assert any("exit_code=1" in r for r in reasons)


def test_handoff_validator_invalid_missing_report(tmp_path: Path) -> None:
    """report.json 없음 → invalid."""
    runs_dir = tmp_path / "runs"
    run_id = "brain-invalid-noreport"
    _create_complete_brain_run(
        runs_dir, run_id=run_id, include_report=False,
    )

    validator = HandoffValidator()
    status, reasons = validator.validate(runs_dir, run_id)

    assert status == "invalid"
    assert any("report.json missing" in r for r in reasons)


def test_handoff_validator_invalid_no_run_dir(tmp_path: Path) -> None:
    """run 디렉토리 없음 → invalid."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    validator = HandoffValidator()
    status, reasons = validator.validate(runs_dir, "nonexistent-run-id")

    assert status == "invalid"
    assert len(reasons) == 1
    assert "run directory not found" in reasons[0]


# ───────────────────────────────────────────────────────────────
# Generator 테스트 (4개)
# ───────────────────────────────────────────────────────────────

def test_handoff_generate_ready(tmp_path: Path) -> None:
    """ready run → artifact 생성 + handoff_status='ready'."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    run_id = "brain-gen-ready"
    _create_complete_brain_run(runs_dir, run_id=run_id)

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    record = generator.generate(run_id)

    assert record.handoff_status == "ready"
    assert record.block_reasons == []
    # 파일 생성 확인
    matches = list(handoffs_dir.glob(f"handoff_*_{run_id}.json"))
    assert len(matches) == 1
    # 내용 재로드 검증
    content = json.loads(matches[0].read_text(encoding="utf-8"))
    assert content["handoff_status"] == "ready"
    assert content["stable_ref"] == run_id
    assert content["brain_run_id"] == run_id


def test_handoff_generate_blocked(tmp_path: Path) -> None:
    """blocked run → artifact 생성 + handoff_status='blocked' + block_reasons 비어있지 않음."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    run_id = "brain-gen-blocked"
    _create_complete_brain_run(
        runs_dir, run_id=run_id,
        reviewer_passed=False, adoption_ready=False, test_exit_code=1,
    )

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    record = generator.generate(run_id)

    assert record.handoff_status == "blocked"
    assert len(record.block_reasons) >= 1
    # artifact는 blocked도 생성
    matches = list(handoffs_dir.glob(f"handoff_*_{run_id}.json"))
    assert len(matches) == 1
    content = json.loads(matches[0].read_text(encoding="utf-8"))
    assert content["handoff_status"] == "blocked"
    assert content["block_reasons"] == record.block_reasons


def test_handoff_generate_invalid_no_artifact(tmp_path: Path) -> None:
    """invalid run → artifact 미생성."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    record = generator.generate("nonexistent-run-id")

    assert record.handoff_status == "invalid"
    # 디렉토리 자체가 없거나 비어있어야 함
    if handoffs_dir.exists():
        assert list(handoffs_dir.glob("handoff_*.json")) == []


def test_handoff_source_immutability(tmp_path: Path) -> None:
    """handoff 생성 후 source files 내용이 변경되지 않음."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    run_id = "brain-immut"
    _create_complete_brain_run(runs_dir, run_id=run_id)

    # 생성 전 source files 스냅샷
    run_state_before = (runs_dir / run_id / "run_state.json").read_bytes()
    report_before = (runs_dir / run_id / "report.json").read_bytes()
    task_spec_before = (runs_dir / run_id / "task_spec.yaml").read_bytes()

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    generator.generate(run_id)

    # 생성 후 동일 확인
    assert (runs_dir / run_id / "run_state.json").read_bytes() == run_state_before
    assert (runs_dir / run_id / "report.json").read_bytes() == report_before
    assert (runs_dir / run_id / "task_spec.yaml").read_bytes() == task_spec_before


# ───────────────────────────────────────────────────────────────
# E2E 테스트 (2개)
# ───────────────────────────────────────────────────────────────

def test_handoff_e2e_ready_path(tmp_path: Path) -> None:
    """완전한 ready 경로 E2E."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    run_id = "brain-e2e-ready"
    _create_complete_brain_run(runs_dir, run_id=run_id)

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    record = generator.generate(run_id)

    matches = list(handoffs_dir.glob(f"handoff_*_{run_id}.json"))
    assert len(matches) == 1
    data = json.loads(matches[0].read_text(encoding="utf-8"))

    assert data["handoff_status"] == "ready"
    assert data["schema_version"] == SCHEMA_VERSION
    # source 경로가 실제 파일을 가리키는지 확인 (상대경로 형태)
    expected_report = f".cambrian/brain/runs/{run_id}/report.json"
    assert data["source_report_path"] == expected_report
    # adoption_record_ref / decision_ref는 None
    assert data["adoption_record_ref"] is None
    assert data["decision_ref"] is None


def test_handoff_e2e_blocked_path(tmp_path: Path) -> None:
    """reviewer 실패 + adoption_ready=false → blocked E2E."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    run_id = "brain-e2e-blocked"
    _create_complete_brain_run(
        runs_dir, run_id=run_id,
        reviewer_passed=False, adoption_ready=False,
    )

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    record = generator.generate(run_id)

    matches = list(handoffs_dir.glob(f"handoff_*_{run_id}.json"))
    assert len(matches) == 1
    data = json.loads(matches[0].read_text(encoding="utf-8"))

    assert data["handoff_status"] == "blocked"
    assert len(data["block_reasons"]) >= 1
    assert data["reviewer_passed"] is False
    assert data["adoption_ready"] is False


# ───────────────────────────────────────────────────────────────
# Schema 테스트 (1개)
# ───────────────────────────────────────────────────────────────

def test_handoff_record_all_fields(tmp_path: Path) -> None:
    """HandoffRecord의 모든 필수 필드가 JSON에 포함된다."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    run_id = "brain-schema-test"
    _create_complete_brain_run(runs_dir, run_id=run_id)

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    generator.generate(run_id)

    matches = list(handoffs_dir.glob(f"handoff_*_{run_id}.json"))
    assert len(matches) == 1
    data = json.loads(matches[0].read_text(encoding="utf-8"))

    expected_keys = {
        "schema_version", "handoff_id", "created_at",
        "stable_ref", "brain_run_id", "task_id",
        "source_report_path", "source_run_state_path",
        "source_task_spec_path", "source_iterations_dir",
        "run_status", "reviewer_passed", "adoption_ready",
        "files_created", "files_modified", "tests_executed",
        "test_exit_code", "reviewer_conclusion",
        "remaining_risks", "next_actions",
        "handoff_status", "block_reasons",
        "adoption_record_ref", "decision_ref",
    }
    assert expected_keys == set(data.keys())
    # 개별 값 검증
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["stable_ref"] == run_id
    assert data["brain_run_id"] == run_id
    assert data["task_id"] == "task-001"
    assert data["handoff_id"].startswith("handoff-")
    assert data["handoff_status"] == "ready"


# ═══════════════════════════════════════════════════════════════════
# Task 29 — Review Gate / Adoption Candidate 테스트
# ═══════════════════════════════════════════════════════════════════

from engine.brain.candidate import (
    CandidateGenerator, CandidateRecord, ReviewGate,
    SCHEMA_VERSION as CANDIDATE_SCHEMA_VERSION,
)


def _create_handoff_file(
    handoffs_dir: Path,
    stable_ref: str = "brain-20260414-100000-a1b2",
    handoff_id: str = "handoff-20260415-103000-f3a1",
    handoff_status: str = "ready",
    reviewer_passed: bool = True,
    adoption_ready: bool = True,
    task_id: str = "task-001",
    test_exit_code: int = 0,
    omit_fields: list[str] | None = None,
    make_invalid_json: bool = False,
) -> Path:
    """테스트용 handoff JSON 파일을 생성한다.

    omit_fields로 특정 필드를 누락시킬 수 있다 (invalid 케이스 테스트).
    """
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "schema_version": "1.0.0",
        "handoff_id": handoff_id,
        "created_at": "2026-04-15T10:30:00Z",
        "brain_run_id": stable_ref,
        "task_id": task_id,
        "source_report_path": (
            f".cambrian/brain/runs/{stable_ref}/report.json"
        ),
        "source_run_state_path": (
            f".cambrian/brain/runs/{stable_ref}/run_state.json"
        ),
        "source_task_spec_path": (
            f".cambrian/brain/runs/{stable_ref}/task_spec.yaml"
        ),
        "source_iterations_dir": (
            f".cambrian/brain/runs/{stable_ref}/iterations/"
        ),
        "run_status": "completed",
        "reviewer_passed": reviewer_passed,
        "adoption_ready": adoption_ready,
        "files_created": ["test_file.py"],
        "files_modified": [],
        "tests_executed": ["tests/test_ok.py"],
        "test_exit_code": test_exit_code,
        "reviewer_conclusion": "모든 작업 완료",
        "remaining_risks": [],
        "next_actions": [],
        "handoff_status": handoff_status,
        "block_reasons": [] if handoff_status == "ready" else ["test reason"],
        "stable_ref": stable_ref,
        "adoption_record_ref": None,
        "decision_ref": None,
    }
    if omit_fields:
        for f in omit_fields:
            data.pop(f, None)

    filename = f"handoff_20260415_103000_{stable_ref}.json"
    path = handoffs_dir / filename
    if make_invalid_json:
        path.write_text("{ this is not valid json", encoding="utf-8")
    else:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return path


# ───────────────────────────────────────────────────────────────
# ReviewGate 테스트 (4개)
# ───────────────────────────────────────────────────────────────

def test_review_gate_pass(tmp_path: Path) -> None:
    """ready handoff → ('pass', [])."""
    handoffs_dir = tmp_path / "handoffs"
    path = _create_handoff_file(handoffs_dir)

    gate = ReviewGate()
    result, reasons = gate.evaluate(path)

    assert result == "pass"
    assert reasons == []


def test_review_gate_reject_blocked(tmp_path: Path) -> None:
    """blocked handoff → ('reject', ...) with status 언급."""
    handoffs_dir = tmp_path / "handoffs"
    path = _create_handoff_file(
        handoffs_dir,
        handoff_status="blocked",
        reviewer_passed=False,
        adoption_ready=False,
    )

    gate = ReviewGate()
    result, reasons = gate.evaluate(path)

    assert result == "reject"
    assert any("status=blocked" in r for r in reasons)


def test_review_gate_reject_reviewer_failed(tmp_path: Path) -> None:
    """ready + reviewer_passed=false → reject."""
    # 현실적이지 않지만 규칙상 가능한 조합 — 규칙은 독립 필드 기준.
    handoffs_dir = tmp_path / "handoffs"
    path = _create_handoff_file(
        handoffs_dir,
        handoff_status="ready",
        reviewer_passed=False,
        adoption_ready=False,
    )

    gate = ReviewGate()
    result, reasons = gate.evaluate(path)

    assert result == "reject"
    assert any("reviewer did not pass" in r for r in reasons)


def test_review_gate_invalid_missing_file(tmp_path: Path) -> None:
    """존재하지 않는 파일 경로 → invalid."""
    gate = ReviewGate()
    result, reasons = gate.evaluate(tmp_path / "nonexistent.json")

    assert result == "invalid"
    assert len(reasons) == 1
    assert "handoff file not found" in reasons[0]


# ───────────────────────────────────────────────────────────────
# CandidateGenerator 테스트 (4개)
# ───────────────────────────────────────────────────────────────

def test_candidate_generate_created(tmp_path: Path) -> None:
    """ready handoff → candidate artifact 생성 + result_type='created'."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    stable_ref = "brain-created-001"
    path = _create_handoff_file(handoffs_dir, stable_ref=stable_ref)

    generator = CandidateGenerator(candidates_dir)
    record, result_type, reasons = generator.generate(path)

    assert result_type == "created"
    assert reasons == []
    assert record is not None
    assert record.candidate_status == "pending_review"
    assert record.candidate_ready_for_adoption is True
    assert record.stable_ref == stable_ref
    # 파일 확인
    matches = list(candidates_dir.glob(f"candidate_*_{stable_ref}.json"))
    assert len(matches) == 1


def test_candidate_generate_rejected(tmp_path: Path) -> None:
    """blocked handoff → candidate 미생성 + result_type='rejected'."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    stable_ref = "brain-rejected-001"
    path = _create_handoff_file(
        handoffs_dir,
        stable_ref=stable_ref,
        handoff_status="blocked",
        reviewer_passed=False,
        adoption_ready=False,
    )

    generator = CandidateGenerator(candidates_dir)
    record, result_type, reasons = generator.generate(path)

    assert result_type == "rejected"
    assert record is None
    assert len(reasons) >= 1
    # candidates_dir가 비어있거나 아예 생성되지 않음
    if candidates_dir.exists():
        assert list(candidates_dir.glob("candidate_*.json")) == []


def test_candidate_generate_duplicate(tmp_path: Path) -> None:
    """같은 stable_ref 2회 generate → 2회째는 duplicate, 파일 1개만."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    stable_ref = "brain-dup-001"
    path = _create_handoff_file(handoffs_dir, stable_ref=stable_ref)

    generator = CandidateGenerator(candidates_dir)

    _r1, result1, _ = generator.generate(path)
    record2, result2, _reasons2 = generator.generate(path)

    assert result1 == "created"
    assert result2 == "duplicate"
    assert record2 is not None
    assert record2.stable_ref == stable_ref

    matches = list(candidates_dir.glob(f"candidate_*_{stable_ref}.json"))
    assert len(matches) == 1


def test_candidate_source_immutability(tmp_path: Path) -> None:
    """candidate 생성 후 handoff 파일이 변경되지 않음."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    path = _create_handoff_file(handoffs_dir, stable_ref="brain-immut-001")
    before = path.read_bytes()

    generator = CandidateGenerator(candidates_dir)
    generator.generate(path)

    after = path.read_bytes()
    assert after == before


# ───────────────────────────────────────────────────────────────
# E2E + Schema 테스트 (2개)
# ───────────────────────────────────────────────────────────────

def test_candidate_e2e_ready_path(tmp_path: Path) -> None:
    """ready handoff → candidate 전체 흐름 + source ref chain 확인."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    stable_ref = "brain-e2e-cand-001"
    handoff_id = "handoff-e2e-001"
    handoff_path = _create_handoff_file(
        handoffs_dir, stable_ref=stable_ref, handoff_id=handoff_id,
    )

    generator = CandidateGenerator(candidates_dir)
    record, result_type, _ = generator.generate(handoff_path)

    assert result_type == "created"
    assert record is not None

    matches = list(candidates_dir.glob(f"candidate_*_{stable_ref}.json"))
    assert len(matches) == 1
    data = json.loads(matches[0].read_text(encoding="utf-8"))

    # source chain
    assert data["stable_ref"] == stable_ref
    assert data["brain_run_id"] == stable_ref
    assert data["handoff_ref"] == handoff_id
    # source_handoff_path가 실제 handoff 파일을 가리킴
    assert str(handoff_path) == data["source_handoff_path"] or \
        data["source_handoff_path"].endswith(handoff_path.name)
    # adoption 연결 필드는 None
    assert data["adoption_record_ref"] is None
    assert data["decision_ref"] is None
    assert data["review_notes"] is None
    # gate_passed_at 비어있지 않음
    assert data["gate_passed_at"]


def test_candidate_all_fields_present(tmp_path: Path) -> None:
    """CandidateRecord의 모든 필드가 candidate JSON에 포함된다."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    stable_ref = "brain-schema-cand-001"
    path = _create_handoff_file(handoffs_dir, stable_ref=stable_ref)

    generator = CandidateGenerator(candidates_dir)
    generator.generate(path)

    matches = list(candidates_dir.glob(f"candidate_*_{stable_ref}.json"))
    assert len(matches) == 1
    data = json.loads(matches[0].read_text(encoding="utf-8"))

    expected_keys = {
        "schema_version", "candidate_id", "created_at", "candidate_status",
        "stable_ref", "handoff_ref", "brain_run_id", "task_id",
        "source_handoff_path", "source_report_path",
        "source_run_state_path", "source_task_spec_path",
        "reviewer_conclusion", "files_created", "files_modified",
        "tests_executed", "test_exit_code",
        "remaining_risks", "next_actions",
        "candidate_ready_for_adoption", "gate_passed_at",
        "adoption_record_ref", "decision_ref", "review_notes",
    }
    assert expected_keys == set(data.keys())
    assert data["schema_version"] == CANDIDATE_SCHEMA_VERSION
    assert data["candidate_status"] == "pending_review"
    assert data["candidate_id"].startswith("candidate-")
    assert data["candidate_ready_for_adoption"] is True


def test_handoff_generated_artifact_has_top_level_stable_ref(
    tmp_path: Path,
) -> None:
    """새 handoff artifact는 최상위 stable_ref를 항상 가진다."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    run_id = "brain-stable-ref-new"
    _create_complete_brain_run(
        runs_dir, run_id=run_id, include_stable_ref=False,
    )

    generator = HandoffGenerator(runs_dir, handoffs_dir)
    record = generator.generate(run_id)

    assert record.handoff_status == "ready"
    assert record.stable_ref == run_id

    matches = list(handoffs_dir.glob(f"handoff_*_{run_id}.json"))
    assert len(matches) == 1
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    assert data["stable_ref"] == run_id
    assert data["brain_run_id"] == run_id


def test_handoff_to_candidate_chain_created(tmp_path: Path) -> None:
    """실제 HandoffGenerator 산출물을 CandidateGenerator가 받아 created 된다."""
    runs_dir = tmp_path / "runs"
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    run_id = "brain-chain-created"
    _create_complete_brain_run(runs_dir, run_id=run_id)

    handoff_generator = HandoffGenerator(runs_dir, handoffs_dir)
    handoff_generator.generate(run_id)

    matches = list(handoffs_dir.glob(f"handoff_*_{run_id}.json"))
    assert len(matches) == 1

    candidate_generator = CandidateGenerator(candidates_dir)
    record, result_type, reasons = candidate_generator.generate(matches[0])

    assert result_type == "created"
    assert reasons == []
    assert record is not None
    assert record.stable_ref == run_id
    assert record.brain_run_id == run_id

    candidate_matches = list(candidates_dir.glob(f"candidate_*_{run_id}.json"))
    assert len(candidate_matches) == 1


def test_candidate_generate_created_with_old_style_handoff(
    tmp_path: Path,
) -> None:
    """stable_ref가 없는 old-style handoff도 brain_run_id fallback으로 생성된다."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    run_id = "brain-old-style-001"
    path = _create_handoff_file(
        handoffs_dir,
        stable_ref=run_id,
        omit_fields=["stable_ref"],
    )

    generator = CandidateGenerator(candidates_dir)
    record, result_type, reasons = generator.generate(path)

    assert result_type == "created"
    assert reasons == []
    assert record is not None
    assert record.stable_ref == run_id

    matches = list(candidates_dir.glob(f"candidate_*_{run_id}.json"))
    assert len(matches) == 1


def test_candidate_generate_invalid_without_stable_ref_and_brain_run_id(
    tmp_path: Path,
) -> None:
    """stable_ref와 brain_run_id가 모두 없으면 invalid 유지."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    path = _create_handoff_file(
        handoffs_dir,
        stable_ref="brain-missing-both-001",
        omit_fields=["stable_ref", "brain_run_id"],
    )

    generator = CandidateGenerator(candidates_dir)
    record, result_type, reasons = generator.generate(path)

    assert result_type == "invalid"
    assert record is None
    assert any("stable_ref missing or empty" in r for r in reasons)
    assert any("brain_run_id missing" in r for r in reasons)


def test_candidate_duplicate_check_uses_stable_ref_fallback(
    tmp_path: Path,
) -> None:
    """old-style handoff 두 개도 brain_run_id fallback 기준으로 dedupe 된다."""
    handoffs_dir = tmp_path / "handoffs"
    candidates_dir = tmp_path / "candidates"
    run_id = "brain-old-dup-001"
    path1 = _create_handoff_file(
        handoffs_dir,
        stable_ref=run_id,
        handoff_id="handoff-old-a",
        omit_fields=["stable_ref"],
    )
    path2 = _create_handoff_file(
        handoffs_dir,
        stable_ref=run_id,
        handoff_id="handoff-old-b",
        omit_fields=["stable_ref"],
    )

    generator = CandidateGenerator(candidates_dir)
    _record1, result1, _reasons1 = generator.generate(path1)
    record2, result2, _reasons2 = generator.generate(path2)

    assert result1 == "created"
    assert result2 == "duplicate"
    assert record2 is not None
    assert record2.stable_ref == run_id

    matches = list(candidates_dir.glob(f"candidate_*_{run_id}.json"))
    assert len(matches) == 1
