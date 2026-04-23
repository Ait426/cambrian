"""Generation feedback / next generation seed 테스트."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from engine.brain.generation_feedback import (
    GenerationAutopsy,
    GenerationFeedbackStore,
    NextGenerationSeedBuilder,
)
from engine.cli import _handle_brain_autopsy


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _task_spec_data() -> dict:
    return {
        "task_id": "task-generation-feedback",
        "goal": "이전 세대 결과를 기반으로 다음 세대 입력을 만든다",
        "related_tests": ["test_add.py"],
        "hypothesis": {
            "id": "hyp-test-pass",
            "statement": "개선된 variant는 관련 테스트를 모두 통과할 것이다.",
            "predicts": {
                "tests": {
                    "passed_min": 1,
                    "failed_max": 0,
                },
            },
        },
    }


def _brain_report_data(task_spec_rel: str) -> dict:
    return {
        "run_id": "brain-001",
        "task_id": "task-generation-feedback",
        "status": "completed",
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "reviewer_conclusion": "acceptance criteria satisfied",
        "hypothesis_evaluation": {
            "enabled": True,
            "hypothesis_id": "hyp-test-pass",
            "statement": "개선된 variant는 관련 테스트를 모두 통과할 것이다.",
            "status": "supported",
            "checks": [],
        },
        "competitive_generation": {
            "enabled": True,
            "status": "success",
            "winner_variant_id": "variant_a",
            "selection_reason": "variant_a selected: supported hypothesis",
            "variants": [
                {
                    "variant_id": "variant_a",
                    "status": "success",
                    "reviewer_passed": True,
                    "hypothesis_status": "supported",
                    "test_results": {"passed": 1, "failed": 0, "skipped": 0},
                    "files_created": ["test_add.py"],
                    "files_modified": [],
                },
                {
                    "variant_id": "variant_b",
                    "status": "failure",
                    "reviewer_passed": False,
                    "hypothesis_status": "contradicted",
                    "test_results": {"passed": 0, "failed": 1, "skipped": 0},
                    "files_created": ["test_add.py"],
                    "files_modified": [],
                },
            ],
        },
        "provenance_handoff": {
            "files_created": ["test_add.py"],
            "files_modified": [],
            "tests_executed": ["test_add.py"],
            "test_exit_code": 0,
            "reviewer_passed": True,
            "adoption_ready": True,
            "stable_ref": "brain-001",
            "task_spec_path": task_spec_rel,
        },
        "next_actions": [],
        "remaining_risks": [],
    }


def _adoption_record_data(task_spec_rel: str) -> dict:
    return {
        "schema_version": "1.0.0",
        "adoption_id": "adoption-001",
        "adoption_type": "brain_generation",
        "brain_run_id": "brain-001",
        "winner_variant_id": "variant_a",
        "source_task_spec_path": task_spec_rel,
        "human_reason": "winner variant passed competitive generation",
        "competitive_generation": {
            "status": "success",
            "winner_variant_id": "variant_a",
            "selection_reason": "variant_a selected: supported hypothesis",
        },
        "hypothesis_evaluation": {
            "status": "supported",
            "hypothesis_id": "hyp-test-pass",
            "statement": "개선된 variant는 관련 테스트를 모두 통과할 것이다.",
        },
        "post_apply_tests": {
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "exit_code": 0,
            "tests_executed": ["test_add.py"],
        },
        "applied_files": [
            {
                "target_path": "test_add.py",
                "source_variant_file_path": ".cambrian/brain/runs/brain-001/variants/variant_a/workspace/test_add.py",
                "existed_before": False,
                "before_sha256": None,
                "after_sha256": "abc123",
                "backup_path": None,
            },
        ],
        "backup_dir": ".cambrian/adoptions/backups/adoption-001",
        "adoption_status": "adopted",
        "provenance": {
            "source": "brain_competitive_generation",
            "stable_ref": "brain-001",
            "selection_reason": "variant_a selected: supported hypothesis",
            "file_first": True,
        },
    }


def test_brain_report_success_autopsy(tmp_path: Path) -> None:
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    report_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    _write_json(
        report_path,
        _brain_report_data(task_spec_path.relative_to(tmp_path).as_posix()),
    )

    autopsy = GenerationAutopsy()
    feedback = autopsy.analyze(report_path, tmp_path)

    assert feedback.source_type == "brain_report"
    assert feedback.outcome == "success"
    assert feedback.brain_run_id == "brain-001"
    assert feedback.keep_patterns

    feedback_path = tmp_path / ".cambrian" / "feedback" / "feedback_001.json"
    seed_path = tmp_path / ".cambrian" / "next_generation" / "next_generation_001.yaml"
    feedback.next_generation_seed_path = str(seed_path)
    GenerationFeedbackStore().save(feedback, feedback_path)
    NextGenerationSeedBuilder().build(
        feedback,
        feedback_path=feedback_path,
        out_path=seed_path,
    )

    assert feedback_path.exists()
    assert seed_path.exists()


def test_adoption_record_success_autopsy(tmp_path: Path) -> None:
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    adoption_path = tmp_path / ".cambrian" / "adoptions" / "adoption_001.json"
    _write_json(
        adoption_path,
        _adoption_record_data(task_spec_path.relative_to(tmp_path).as_posix()),
    )

    feedback = GenerationAutopsy().analyze(adoption_path, tmp_path)
    seed_path = tmp_path / ".cambrian" / "next_generation" / "next_generation_001.yaml"
    feedback.next_generation_seed_path = str(seed_path)
    NextGenerationSeedBuilder().build(
        feedback,
        feedback_path=tmp_path / ".cambrian" / "feedback" / "feedback_001.json",
        out_path=seed_path,
    )
    seed_data = yaml.safe_load(seed_path.read_text(encoding="utf-8"))

    assert feedback.source_type == "adoption_record"
    assert feedback.outcome == "success"
    assert feedback.adoption_id == "adoption-001"
    assert seed_data["previous_outcome"]["outcome"] == "success"


def test_contradicted_hypothesis_failure(tmp_path: Path) -> None:
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    report = _brain_report_data(task_spec_path.relative_to(tmp_path).as_posix())
    report["hypothesis_evaluation"]["status"] = "contradicted"
    report["competitive_generation"]["status"] = "failure"
    report["status"] = "failed"
    report_path = tmp_path / "report_failure.json"
    _write_json(report_path, report)

    feedback = GenerationAutopsy().analyze(report_path, tmp_path)

    assert feedback.outcome == "failure"
    assert any("contradicted" in item.lower() for item in feedback.avoid_patterns)
    assert feedback.suggested_next_actions


def test_no_winner_path(tmp_path: Path) -> None:
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    report = _brain_report_data(task_spec_path.relative_to(tmp_path).as_posix())
    report["competitive_generation"]["status"] = "no_winner"
    report["competitive_generation"]["winner_variant_id"] = None
    report["status"] = "completed"
    report_path = tmp_path / "report_no_winner.json"
    _write_json(report_path, report)

    feedback = GenerationAutopsy().analyze(report_path, tmp_path)

    assert feedback.outcome == "no_winner"
    assert any("Revise hypothesis" in item for item in feedback.suggested_next_actions)
    assert any("Generate alternative variant actions" in item for item in feedback.suggested_next_actions)


def test_missing_evidence_inconclusive(tmp_path: Path) -> None:
    report_path = tmp_path / "report_inconclusive.json"
    _write_json(
        report_path,
        {
            "run_id": "brain-missing",
            "task_id": "task-missing",
        },
    )

    feedback = GenerationAutopsy().analyze(report_path, tmp_path)

    assert feedback.outcome == "inconclusive"
    assert feedback.missing_evidence


def test_human_feedback_captured(tmp_path: Path) -> None:
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    report_path = tmp_path / "report_human.json"
    _write_json(
        report_path,
        _brain_report_data(task_spec_path.relative_to(tmp_path).as_posix()),
    )

    feedback = GenerationAutopsy().analyze(
        report_path,
        tmp_path,
        human_feedback={
            "note": "worked but too broad",
            "rating": "mixed",
            "keep": ["minimal file layout"],
            "avoid": ["large patch"],
        },
    )

    assert feedback.human_feedback["note"] == "worked but too broad"
    assert feedback.human_feedback["rating"] == "mixed"
    assert feedback.human_feedback["keep"] == ["minimal file layout"]
    assert feedback.human_feedback["avoid"] == ["large patch"]


def test_next_generation_seed_schema(tmp_path: Path) -> None:
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    report_path = tmp_path / "report_seed.json"
    _write_json(
        report_path,
        _brain_report_data(task_spec_path.relative_to(tmp_path).as_posix()),
    )

    feedback = GenerationAutopsy().analyze(report_path, tmp_path)
    feedback_path = tmp_path / ".cambrian" / "feedback" / "feedback_001.json"
    seed_path = tmp_path / ".cambrian" / "next_generation" / "next_generation_001.yaml"
    feedback.next_generation_seed_path = str(seed_path)
    GenerationFeedbackStore().save(feedback, feedback_path)
    NextGenerationSeedBuilder().build(
        feedback,
        feedback_path=feedback_path,
        out_path=seed_path,
    )
    seed = yaml.safe_load(seed_path.read_text(encoding="utf-8"))

    assert "source_feedback_ref" in seed
    assert "previous_outcome" in seed
    assert "lessons" in seed
    assert "keep" in seed["lessons"]
    assert "avoid" in seed["lessons"]
    assert "suggested_next_actions" in seed
    assert "hypothesis_seed" in seed
    assert "competitive_seed" in seed


def test_source_immutability(tmp_path: Path) -> None:
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    report_path = tmp_path / "report_immutable.json"
    _write_json(
        report_path,
        _brain_report_data(task_spec_path.relative_to(tmp_path).as_posix()),
    )
    before = _sha256(report_path)

    feedback = GenerationAutopsy().analyze(report_path, tmp_path)
    feedback_path = tmp_path / ".cambrian" / "feedback" / "feedback_001.json"
    seed_path = tmp_path / ".cambrian" / "next_generation" / "next_generation_001.yaml"
    feedback.next_generation_seed_path = str(seed_path)
    GenerationFeedbackStore().save(feedback, feedback_path)
    NextGenerationSeedBuilder().build(
        feedback,
        feedback_path=feedback_path,
        out_path=seed_path,
    )

    assert _sha256(report_path) == before


def test_cli_autopsy_smoke(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.chdir(tmp_path)
    task_spec_path = tmp_path / "tasks" / "task.yaml"
    _write_yaml(task_spec_path, _task_spec_data())
    report_path = tmp_path / "report_cli.json"
    _write_json(
        report_path,
        _brain_report_data(task_spec_path.relative_to(tmp_path).as_posix()),
    )

    args = argparse.Namespace(
        source_path=str(report_path),
        note="worked but too broad",
        rating="mixed",
        keep=["minimal file layout"],
        avoid=["large patch"],
        feedback_out_dir=None,
        next_generation_out_dir=None,
        json_output=False,
    )

    _handle_brain_autopsy(args)
    out = capsys.readouterr().out

    assert "[AUTOPSY] generation feedback created" in out
    assert list((tmp_path / ".cambrian" / "feedback").glob("feedback_*.json"))
    assert list(
        (tmp_path / ".cambrian" / "next_generation").glob("next_generation_*.yaml")
    )
