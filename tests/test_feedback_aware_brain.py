"""Feedback-aware brain run 테스트."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from engine.brain.checkpoint import CheckpointManager
from engine.brain.feedback_context import FeedbackContextLoader
from engine.brain.models import RunState, TaskSpec
from engine.brain.runner import RALFRunner
from engine.cli import _handle_brain_run


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _generation_seed() -> dict:
    return {
        "source_feedback_ref": ".cambrian/feedback/feedback_prev.json",
        "previous_outcome": {
            "outcome": "failure",
            "reasons": ["hypothesis contradicted"],
        },
        "lessons": {
            "keep": ["Keep minimal file layout"],
            "avoid": ["Avoid variant_b because pytest failed"],
            "missing_evidence": ["No core_bridge evidence was available"],
        },
        "suggested_next_actions": [
            "Revise hypothesis to require explicit post-apply tests",
        ],
        "hypothesis_seed": {
            "statement": "새 variant는 pytest를 최소 1개 통과하고 실패는 0개일 것이다.",
            "predicts": {
                "tests": {
                    "passed_min": 1,
                    "failed_max": 0,
                },
                "files": {
                    "created_contains": ["test_add.py"],
                },
            },
        },
        "competitive_seed": {
            "recommended_variant_count": 2,
            "avoid_variant_ids": ["variant_b"],
        },
    }


def _standard_task_data() -> dict:
    return {
        "task_id": "task-feedback-aware",
        "goal": "seed를 반영한 brain run을 수행한다",
        "scope": ["test_add.py 생성"],
        "related_tests": ["test_add.py"],
        "output_paths": ["test_add.py"],
        "actions": [
            {
                "type": "write_file",
                "target_path": "test_add.py",
                "content": (
                    "def test_add():\n"
                    "    assert 1 + 1 == 2\n"
                ),
            },
        ],
    }


def _competitive_task(
    *,
    generation_seed: dict | None = None,
    hypothesis: dict | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id="task-feedback-competitive",
        goal="이전 피드백을 반영해 competitive run을 수행한다",
        scope=["variant를 격리 실행한다"],
        non_goals=[],
        acceptance_criteria=["test_add.py 파일 생성", "pytest 통과"],
        related_files=[],
        related_tests=["test_add.py"],
        output_paths=["test_add.py"],
        generation_seed=generation_seed,
        hypothesis=hypothesis,
        competitive={
            "enabled": True,
            "variants": [
                {
                    "id": "variant_a",
                    "actions": [
                        {
                            "type": "write_file",
                            "target_path": "test_add.py",
                            "content": (
                                "def test_add():\n"
                                "    assert 1 + 1 == 2\n"
                            ),
                        },
                        {
                            "type": "write_file",
                            "target_path": "extra_note.txt",
                            "content": "seed fallback winner\n",
                        },
                    ],
                },
                {
                    "id": "variant_b",
                    "actions": [
                        {
                            "type": "write_file",
                            "target_path": "test_add.py",
                            "content": (
                                "def test_add():\n"
                                "    assert 1 + 1 == 2\n"
                            ),
                        },
                    ],
                },
            ],
        },
    )


def test_task_spec_generation_seed_round_trip(tmp_path: Path) -> None:
    spec_path = tmp_path / "task_seeded.yaml"
    data = {
        "task_id": "task-seeded-roundtrip",
        "goal": "generation seed가 round-trip 된다",
        "generation_seed": _generation_seed(),
        "feedback_refs": [".cambrian/feedback/feedback_prev.json"],
    }
    _write_yaml(spec_path, data)

    loaded = TaskSpec.from_yaml(spec_path)
    assert loaded.generation_seed == data["generation_seed"]
    assert loaded.feedback_refs == data["feedback_refs"]

    round_trip_path = tmp_path / "task_seeded_roundtrip.yaml"
    loaded.to_yaml(round_trip_path)
    reloaded = TaskSpec.from_yaml(round_trip_path)
    assert reloaded.generation_seed == data["generation_seed"]
    assert reloaded.feedback_refs == data["feedback_refs"]

    legacy = TaskSpec(task_id="task-no-seed", goal="기존 task spec도 계속 동작한다")
    assert legacy.generation_seed is None
    assert legacy.feedback_refs is None


def test_feedback_context_loader_loads_seed(tmp_path: Path) -> None:
    seed = _generation_seed()
    seed["source_seed_path"] = str((tmp_path / "seed.yaml").resolve())
    spec = TaskSpec(
        task_id="task-feedback-context",
        goal="seed를 로드한다",
        generation_seed=seed,
    )

    context = FeedbackContextLoader().load_from_spec(spec, tmp_path)

    assert context.enabled is True
    assert context.source_seed_path == seed["source_seed_path"]
    assert context.previous_outcome == seed["previous_outcome"]
    assert context.lessons_keep == ["Keep minimal file layout"]
    assert context.lessons_avoid == ["Avoid variant_b because pytest failed"]
    assert context.missing_evidence == ["No core_bridge evidence was available"]
    assert context.suggested_next_actions == [
        "Revise hypothesis to require explicit post-apply tests"
    ]
    assert context.hypothesis_seed == seed["hypothesis_seed"]
    assert context.competitive_seed == seed["competitive_seed"]


def test_cli_seed_injects_into_run_snapshot(
    tmp_path: Path,
    capsys,
) -> None:
    task_path = tmp_path / "task.yaml"
    seed_path = tmp_path / "next_generation_seed.yaml"
    runs_dir = tmp_path / "runs"
    _write_yaml(task_path, _standard_task_data())
    _write_yaml(seed_path, _generation_seed())

    args = argparse.Namespace(
        task_spec=str(task_path),
        generation_seed_path=str(seed_path),
        runs_dir=str(runs_dir),
        workspace=str(tmp_path),
        max_iterations=5,
        json_output=False,
    )

    _handle_brain_run(args)
    capsys.readouterr()

    run_dirs = [entry for entry in runs_dir.iterdir() if entry.is_dir()]
    assert len(run_dirs) == 1

    original_task = TaskSpec.from_yaml(task_path)
    snapshot_task = TaskSpec.from_yaml(run_dirs[0] / "task_spec.yaml")
    assert original_task.generation_seed is None
    assert snapshot_task.generation_seed is not None
    assert snapshot_task.generation_seed["source_seed_path"] == str(
        seed_path.resolve()
    )
    assert snapshot_task.feedback_refs == [
        ".cambrian/feedback/feedback_prev.json"
    ]


def test_report_contains_feedback_context(tmp_path: Path) -> None:
    seed = _generation_seed()
    seed["source_seed_path"] = str((tmp_path / "seed.yaml").resolve())
    task_data = _standard_task_data()
    spec = TaskSpec.from_dict(task_data | {"generation_seed": seed})

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = _read_json(tmp_path / "runs" / state.run_id / "report.json")

    assert report["feedback_context"]["enabled"] is True
    assert report["feedback_context"]["source_seed_path"] == seed["source_seed_path"]
    assert report["feedback_context"]["previous_outcome"]["outcome"] == "failure"
    assert report["feedback_context"]["lessons"]["avoid"] == [
        "Avoid variant_b because pytest failed"
    ]


def test_seed_hypothesis_used_when_task_spec_has_no_hypothesis(tmp_path: Path) -> None:
    seed = _generation_seed()
    seed["source_seed_path"] = str((tmp_path / "seed.yaml").resolve())
    spec = TaskSpec.from_dict(_standard_task_data() | {"generation_seed": seed})

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = _read_json(tmp_path / "runs" / state.run_id / "report.json")

    assert report["hypothesis_evaluation"]["source"] == "generation_seed"
    assert report["hypothesis_evaluation"]["status"] == "supported"


def test_explicit_task_spec_hypothesis_wins(tmp_path: Path) -> None:
    seed = _generation_seed()
    seed["source_seed_path"] = str((tmp_path / "seed.yaml").resolve())
    explicit_hypothesis = {
        "id": "explicit-hypothesis",
        "statement": "명시 가설이 seed보다 우선한다.",
        "predicts": {
            "tests": {
                "passed_min": 1,
                "failed_max": 0,
            },
        },
    }
    spec = TaskSpec.from_dict(
        _standard_task_data()
        | {
            "generation_seed": seed,
            "hypothesis": explicit_hypothesis,
        }
    )

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = _read_json(tmp_path / "runs" / state.run_id / "report.json")

    assert report["hypothesis_evaluation"]["source"] == "task_spec"
    assert report["hypothesis_evaluation"]["hypothesis_id"] == "explicit-hypothesis"


def test_avoid_variant_ids_exclude_winner(tmp_path: Path) -> None:
    seed = _generation_seed()
    seed["source_seed_path"] = str((tmp_path / "seed.yaml").resolve())
    spec = _competitive_task(generation_seed=seed)

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = _read_json(tmp_path / "runs" / state.run_id / "report.json")

    variants = {
        variant["variant_id"]: variant
        for variant in report["competitive_generation"]["variants"]
    }
    assert report["competitive_generation"]["winner_variant_id"] == "variant_a"
    assert variants["variant_b"]["excluded_from_winner"] is True
    assert "blocked by generation seed avoid_variant_ids" in variants["variant_b"]["warnings"]
    assert any(
        "excluded from winner selection" in action
        for action in report["next_actions"]
    )


def test_suggested_next_actions_merged(tmp_path: Path) -> None:
    seed = _generation_seed()
    seed["source_seed_path"] = str((tmp_path / "seed.yaml").resolve())
    spec = TaskSpec.from_dict(_standard_task_data() | {"generation_seed": seed})

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = _read_json(tmp_path / "runs" / state.run_id / "report.json")

    assert any(
        "Revise hypothesis to require explicit post-apply tests" in action
        for action in report["next_actions"]
    )
    assert any(
        "Feedback seed missing evidence: No core_bridge evidence was available"
        in action
        for action in report["next_actions"]
    )


def test_resume_keeps_feedback_context(tmp_path: Path) -> None:
    seed = _generation_seed()
    seed["source_seed_path"] = str((tmp_path / "seed.yaml").resolve())
    spec = TaskSpec.from_dict(_standard_task_data() | {"generation_seed": seed})
    runs_dir = tmp_path / "runs"
    run_id = "brain-resume-seed"
    checkpoint = CheckpointManager(runs_dir)
    checkpoint.create_run_dir(run_id)
    checkpoint.save_task_spec(run_id, spec)
    checkpoint.save_state(
        RunState(
            run_id=run_id,
            task_spec=spec,
            status="running",
            current_iteration=0,
            max_iterations=5,
            current_phase="planner",
            work_items=[],
            step_results=[],
            started_at="2026-04-21T00:00:00+00:00",
            updated_at="2026-04-21T00:00:00+00:00",
            finished_at=None,
            termination_reason="",
            core_bridge=None,
        )
    )

    runner = RALFRunner(runs_dir=runs_dir, workspace=tmp_path)
    state = runner.resume(run_id)
    report = _read_json(runs_dir / state.run_id / "report.json")

    assert report["feedback_context"]["enabled"] is True
    assert report["feedback_context"]["source_seed_path"] == seed["source_seed_path"]
    assert report["hypothesis_evaluation"]["source"] == "generation_seed"


def test_malformed_seed_does_not_crash(tmp_path: Path) -> None:
    spec = TaskSpec.from_dict(
        _standard_task_data()
        | {
            "generation_seed": {
                "source_seed_path": str((tmp_path / "bad_seed.yaml").resolve()),
                "previous_outcome": "bad",
                "lessons": "bad",
                "hypothesis_seed": "bad",
                "competitive_seed": {
                    "avoid_variant_ids": "variant_b",
                    "recommended_variant_count": "two",
                },
            },
        }
    )

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = _read_json(tmp_path / "runs" / state.run_id / "report.json")

    assert report["status"] == "completed"
    assert report["feedback_context"]["enabled"] is True
    assert report["feedback_context"]["warnings"]
    assert report["feedback_context"]["errors"] == []
