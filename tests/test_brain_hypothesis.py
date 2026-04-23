"""Brain hypothesis 평가 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from engine.brain.hypothesis import HypothesisEvaluator
from engine.brain.models import TaskSpec
from engine.brain.runner import RALFRunner


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _base_report() -> dict:
    return {
        "run_id": "brain-hypothesis-report",
        "task_id": "task-hypothesis",
        "status": "completed",
        "test_results": {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
        },
        "remaining_risks": [],
        "next_actions": [],
        "provenance_handoff": {
            "files_created": [],
            "files_modified": [],
        },
    }


def _supported_hypothesis() -> dict:
    return {
        "id": "hyp-add-test-pass",
        "statement": (
            "test_add.py를 생성하면 pytest가 최소 1개 통과하고 실패는 0개일 것이다."
        ),
        "predicts": {
            "tests": {
                "passed_min": 1,
                "failed_max": 0,
            },
            "files": {
                "created_contains": ["test_add.py"],
            },
        },
        "rationale": "간단한 통과 테스트 파일을 생성하기 때문이다.",
    }


def test_task_spec_hypothesis_round_trip(tmp_path: Path) -> None:
    spec_path = tmp_path / "task_hypothesis.yaml"
    data = {
        "task_id": "task-hypothesis-smoke",
        "goal": "test_add.py를 생성하면 pytest가 통과한다",
        "scope": ["test_add.py 파일 생성"],
        "hypothesis": _supported_hypothesis(),
    }
    _write_yaml(spec_path, data)

    loaded = TaskSpec.from_yaml(spec_path)

    assert loaded.hypothesis == data["hypothesis"]

    round_trip_path = tmp_path / "task_hypothesis_round_trip.yaml"
    loaded.to_yaml(round_trip_path)
    reloaded = TaskSpec.from_yaml(round_trip_path)
    assert reloaded.hypothesis == data["hypothesis"]


def test_task_spec_without_hypothesis_still_works(tmp_path: Path) -> None:
    spec_path = tmp_path / "task_without_hypothesis.yaml"
    data = {
        "task_id": "task-no-hypothesis",
        "goal": "기존 task spec도 계속 동작한다",
        "scope": ["noop"],
    }
    _write_yaml(spec_path, data)

    loaded = TaskSpec.from_yaml(spec_path)

    assert loaded.hypothesis is None


def test_hypothesis_evaluator_supported_for_tests() -> None:
    report = _base_report()
    report["test_results"] = {"passed": 2, "failed": 0, "skipped": 0}
    hypothesis = {
        "id": "hyp-tests-supported",
        "statement": "pytest가 최소 1개 통과하고 실패는 0개일 것이다.",
        "predicts": {
            "tests": {
                "passed_min": 1,
                "failed_max": 0,
            },
        },
    }

    evaluation = HypothesisEvaluator().evaluate(hypothesis, report)

    assert evaluation.status == "supported"
    assert all(check.status == "passed" for check in evaluation.checks)
    assert evaluation.next_actions == []


def test_hypothesis_evaluator_contradicted_for_tests() -> None:
    report = _base_report()
    report["test_results"] = {"passed": 0, "failed": 1, "skipped": 0}
    hypothesis = {
        "id": "hyp-tests-contradicted",
        "statement": "pytest가 최소 1개 통과하고 실패는 0개일 것이다.",
        "predicts": {
            "tests": {
                "passed_min": 1,
                "failed_max": 0,
            },
        },
    }

    evaluation = HypothesisEvaluator().evaluate(hypothesis, report)

    assert evaluation.status == "contradicted"
    assert any(check.status == "failed" for check in evaluation.checks)
    assert len(evaluation.next_actions) >= 1


def test_hypothesis_evaluator_supported_for_files() -> None:
    report = _base_report()
    report["provenance_handoff"]["files_created"] = ["test_add.py"]
    hypothesis = {
        "id": "hyp-files-supported",
        "statement": "test_add.py가 생성될 것이다.",
        "predicts": {
            "files": {
                "created_contains": ["test_add.py"],
            },
        },
    }

    evaluation = HypothesisEvaluator().evaluate(hypothesis, report)

    assert evaluation.status == "supported"
    assert evaluation.checks[0].status == "passed"


def test_hypothesis_evaluator_inconclusive_when_file_evidence_missing() -> None:
    report = {
        "run_id": "brain-hypothesis-report",
        "task_id": "task-hypothesis",
        "status": "completed",
        "test_results": {"passed": 0, "failed": 0, "skipped": 0},
        "remaining_risks": [],
        "next_actions": [],
    }
    hypothesis = {
        "id": "hyp-files-inconclusive",
        "statement": "test_add.py가 생성될 것이다.",
        "predicts": {
            "files": {
                "created_contains": ["test_add.py"],
            },
        },
    }

    evaluation = HypothesisEvaluator().evaluate(hypothesis, report)

    assert evaluation.status == "inconclusive"
    assert evaluation.checks[0].status == "inconclusive"


def test_hypothesis_evaluator_core_bridge_supported() -> None:
    report = _base_report()
    report["core_bridge"] = {
        "read_only": True,
        "artifacts": [
            {
                "ref_name": "decision_report",
                "artifact_type": "decision_report",
                "summary": {
                    "baseline_decision": "replace_with_champion",
                    "recommend_promote": True,
                    "champion_policy": "policies/champion.json",
                },
            },
        ],
    }
    hypothesis = {
        "id": "hyp-core-supported",
        "statement": "decision report는 champion 교체와 promote 추천을 보여줄 것이다.",
        "predicts": {
            "core_bridge": {
                "baseline_decision": "replace_with_champion",
                "recommend_promote": True,
            },
        },
    }

    evaluation = HypothesisEvaluator().evaluate(hypothesis, report)

    assert evaluation.status == "supported"
    assert all(check.status == "passed" for check in evaluation.checks)


def test_hypothesis_evaluator_core_bridge_inconclusive_without_bridge() -> None:
    report = _base_report()
    hypothesis = {
        "id": "hyp-core-inconclusive",
        "statement": "core bridge가 baseline decision을 보여줄 것이다.",
        "predicts": {
            "core_bridge": {
                "baseline_decision": "replace_with_champion",
            },
        },
    }

    evaluation = HypothesisEvaluator().evaluate(hypothesis, report)

    assert evaluation.status == "inconclusive"
    assert evaluation.checks[0].status == "inconclusive"


def test_brain_run_report_contains_supported_hypothesis_evaluation(
    tmp_path: Path,
) -> None:
    runs_dir = tmp_path / "runs"
    spec = TaskSpec(
        task_id="task-hypothesis-supported",
        goal="test_add.py를 생성하면 pytest가 통과한다",
        scope=["create test_add.py file"],
        non_goals=[],
        acceptance_criteria=[],
        related_files=[],
        related_tests=["test_add.py"],
        output_paths=["test_add.py"],
        actions=[
            {
                "type": "write_file",
                "target_path": "test_add.py",
                "content": (
                    "def test_add():\n"
                    "    assert 1 + 1 == 2\n"
                ),
            },
        ],
        hypothesis=_supported_hypothesis(),
    )

    runner = RALFRunner(runs_dir=runs_dir, workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)

    assert state.status == "completed"
    report_path = runs_dir / state.run_id / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["hypothesis_evaluation"]["status"] == "supported"
    assert report["hypothesis_evaluation"]["enabled"] is True
    assert report["hypothesis_evaluation"]["checks"]


def test_contradicted_hypothesis_does_not_crash_run(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    spec = TaskSpec(
        task_id="task-hypothesis-contradicted",
        goal="test_add.py를 생성하지만 잘못된 가설을 둔다",
        scope=["create test_add.py file"],
        non_goals=[],
        acceptance_criteria=[],
        related_files=[],
        related_tests=["test_add.py"],
        output_paths=["test_add.py"],
        actions=[
            {
                "type": "write_file",
                "target_path": "test_add.py",
                "content": (
                    "def test_add():\n"
                    "    assert 1 + 1 == 2\n"
                ),
            },
        ],
        hypothesis={
            "id": "hyp-add-contradicted",
            "statement": "pytest가 2개 이상 통과할 것이다.",
            "predicts": {
                "tests": {
                    "passed_min": 2,
                    "failed_max": 0,
                },
            },
        },
    )

    runner = RALFRunner(runs_dir=runs_dir, workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)

    report_path = runs_dir / state.run_id / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert state.run_id
    assert report["status"] == "completed"
    assert report["hypothesis_evaluation"]["status"] == "contradicted"
    assert any(
        "Hypothesis contradicted" in action
        for action in report["next_actions"]
    )
