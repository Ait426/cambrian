"""Hypothesis refinement 테스트."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from engine.brain.hypothesis_refinement import (
    HypothesisRefinementStore,
    HypothesisRefiner,
)
from engine.cli import _handle_brain_refine_hypothesis, _handle_brain_run


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_payload() -> dict:
    return {
        "source_feedback_ref": ".cambrian/feedback/feedback_001.json",
        "previous_outcome": {
            "outcome": "failure",
            "reasons": ["hypothesis contradicted: tests.failed_max failed"],
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
            "statement": "A revised variant should pass related tests with zero failures.",
            "predicts": {
                "tests": {
                    "passed_min": 1,
                    "failed_max": 0,
                },
            },
        },
    }


def _pressure_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "pressure_id": "pressure-001",
        "created_at": "2026-04-21T00:00:00+00:00",
        "source_ledger_path": ".cambrian/evolution/_ledger.json",
        "source_generation_ids": ["gen-brain-001"],
        "pressure_status": "active",
        "keep_patterns": ["Keep supported hypothesis: hyp-pass"],
        "avoid_patterns": ["Avoid previously failed variant: variant_b"],
        "blocked_variant_ids": ["variant_b"],
        "warned_variant_ids": ["variant_c"],
        "recommended_variant_count": 3,
        "hypothesis_warnings": ["Hypothesis contradicted repeatedly: hyp-old (2)"],
        "missing_evidence_warnings": ["No core_bridge evidence was available"],
        "risk_flags": ["repeated_no_winner"],
        "rationale": ["Applied blocked_variant_ids from selection pressure"],
        "warnings": [],
        "errors": [],
    }


def _task_payload(*, with_hypothesis: bool = False, related_tests: bool = True) -> dict:
    data = {
        "task_id": "task-refinement",
        "goal": "refined hypothesis를 반영한 run",
        "scope": ["test_add.py 생성"],
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
    if related_tests:
        data["related_tests"] = ["test_add.py"]
    if with_hypothesis:
        data["hypothesis"] = {
            "id": "explicit-hypothesis",
            "statement": "명시 가설이 refinement보다 우선한다.",
            "predicts": {
                "tests": {
                    "passed_min": 1,
                    "failed_max": 0,
                },
            },
        }
    return data


def _competitive_task_payload() -> dict:
    return {
        "task_id": "task-refinement-competitive",
        "goal": "refinement constraint를 반영한 competitive run",
        "scope": ["variant를 격리 실행한다"],
        "related_tests": ["test_add.py"],
        "output_paths": ["test_add.py"],
        "competitive": {
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
                            "content": "extra\n",
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
    }


def test_refine_from_seed_hypothesis(tmp_path: Path) -> None:
    seed_path = tmp_path / ".cambrian" / "next_generation" / "seed.yaml"
    _write_yaml(seed_path, _seed_payload())

    refinement = HypothesisRefiner().refine(
        seed_path=seed_path,
        pressure_path=None,
        task_spec_path=None,
        project_root=tmp_path,
    )

    assert refinement.status == "ready"
    assert refinement.refined_hypothesis is not None
    assert refinement.refined_hypothesis["statement"] == _seed_payload()["hypothesis_seed"]["statement"]


def test_add_default_test_predictions_without_overriding(tmp_path: Path) -> None:
    seed_path = tmp_path / ".cambrian" / "next_generation" / "seed.yaml"
    task_path = tmp_path / "task.yaml"
    seed = _seed_payload()
    seed["hypothesis_seed"]["predicts"]["tests"] = {"passed_min": 2}
    _write_yaml(seed_path, seed)
    _write_yaml(task_path, _task_payload())

    refinement = HypothesisRefiner().refine(
        seed_path=seed_path,
        pressure_path=None,
        task_spec_path=task_path,
        project_root=tmp_path,
    )

    assert refinement.refined_hypothesis is not None
    tests_predict = refinement.refined_hypothesis["predicts"]["tests"]
    assert tests_predict["passed_min"] == 2
    assert tests_predict["failed_max"] == 0


def test_no_base_hypothesis_needs_review(tmp_path: Path) -> None:
    seed_path = tmp_path / ".cambrian" / "next_generation" / "seed.yaml"
    seed = _seed_payload()
    seed.pop("hypothesis_seed")
    _write_yaml(seed_path, seed)

    refinement = HypothesisRefiner().refine(
        seed_path=seed_path,
        pressure_path=None,
        task_spec_path=None,
        project_root=tmp_path,
    )

    assert refinement.status == "needs_review"
    assert refinement.refined_hypothesis is None


def test_apply_pressure_constraints(tmp_path: Path) -> None:
    seed_path = tmp_path / ".cambrian" / "next_generation" / "seed.yaml"
    pressure_path = tmp_path / ".cambrian" / "evolution" / "_selection_pressure.yaml"
    _write_yaml(seed_path, _seed_payload())
    _write_yaml(pressure_path, _pressure_payload())

    refinement = HypothesisRefiner().refine(
        seed_path=seed_path,
        pressure_path=pressure_path,
        task_spec_path=None,
        project_root=tmp_path,
    )

    assert refinement.constraints["blocked_variant_ids"] == ["variant_b"]
    assert "Applied blocked_variant_ids from selection pressure" in refinement.rationale


def test_required_evidence_from_missing_evidence(tmp_path: Path) -> None:
    seed_path = tmp_path / ".cambrian" / "next_generation" / "seed.yaml"
    pressure_path = tmp_path / ".cambrian" / "evolution" / "_selection_pressure.yaml"
    _write_yaml(seed_path, _seed_payload())
    _write_yaml(pressure_path, _pressure_payload())

    refinement = HypothesisRefiner().refine(
        seed_path=seed_path,
        pressure_path=pressure_path,
        task_spec_path=None,
        project_root=tmp_path,
    )

    assert "No core_bridge evidence was available" in refinement.required_evidence
    assert any("Hypothesis contradicted repeatedly" in item for item in refinement.required_evidence)


def test_cli_refine_hypothesis_smoke(tmp_path: Path, capsys) -> None:
    seed_path = tmp_path / ".cambrian" / "next_generation" / "seed.yaml"
    pressure_path = tmp_path / ".cambrian" / "evolution" / "_selection_pressure.yaml"
    task_path = tmp_path / "task.yaml"
    out_path = tmp_path / ".cambrian" / "hypotheses" / "refined.yaml"
    _write_yaml(seed_path, _seed_payload())
    _write_yaml(pressure_path, _pressure_payload())
    _write_yaml(task_path, _task_payload())

    _handle_brain_refine_hypothesis(
        argparse.Namespace(
            generation_seed_path=str(seed_path),
            selection_pressure_path=str(pressure_path),
            task_spec_path=str(task_path),
            refinement_out=str(out_path),
            json_output=False,
        )
    )
    output = capsys.readouterr().out

    assert out_path.exists()
    assert "[HYPOTHESIS] refined hypothesis created" in output


def test_brain_run_refinement_uses_refined_hypothesis_when_task_spec_has_none(
    tmp_path: Path,
    capsys,
) -> None:
    task_path = tmp_path / "task.yaml"
    refinement_path = tmp_path / ".cambrian" / "hypotheses" / "refined.yaml"
    runs_dir = tmp_path / "runs"
    _write_yaml(task_path, _task_payload())

    refinement = {
        "schema_version": "1.0.0",
        "refinement_id": "href-001",
        "status": "ready",
        "refined_hypothesis": {
            "id": "refined-hypothesis",
            "statement": "refinement 가설은 테스트를 통과해야 한다.",
            "predicts": {
                "tests": {
                    "passed_min": 1,
                    "failed_max": 0,
                },
            },
        },
        "constraints": {},
        "required_evidence": [],
        "warnings": [],
        "errors": [],
    }
    _write_yaml(refinement_path, refinement)

    _handle_brain_run(
        argparse.Namespace(
            task_spec=str(task_path),
            generation_seed_path=None,
            selection_pressure_path=None,
            hypothesis_refinement_path=str(refinement_path),
            runs_dir=str(runs_dir),
            workspace=str(tmp_path),
            max_iterations=5,
            json_output=False,
        )
    )
    capsys.readouterr()

    run_dir = next(entry for entry in runs_dir.iterdir() if entry.is_dir())
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

    assert report["hypothesis_evaluation"]["source"] == "refinement"
    assert report["hypothesis_evaluation"]["status"] == "supported"


def test_explicit_task_spec_hypothesis_wins(tmp_path: Path, capsys) -> None:
    task_path = tmp_path / "task.yaml"
    refinement_path = tmp_path / ".cambrian" / "hypotheses" / "refined.yaml"
    runs_dir = tmp_path / "runs"
    _write_yaml(task_path, _task_payload(with_hypothesis=True))
    _write_yaml(
        refinement_path,
        {
            "schema_version": "1.0.0",
            "refinement_id": "href-001",
            "status": "ready",
            "refined_hypothesis": {
                "id": "refined-hypothesis",
                "statement": "refinement 가설",
                "predicts": {"tests": {"passed_min": 2, "failed_max": 0}},
            },
            "constraints": {},
            "required_evidence": [],
            "warnings": [],
            "errors": [],
        },
    )

    _handle_brain_run(
        argparse.Namespace(
            task_spec=str(task_path),
            generation_seed_path=None,
            selection_pressure_path=None,
            hypothesis_refinement_path=str(refinement_path),
            runs_dir=str(runs_dir),
            workspace=str(tmp_path),
            max_iterations=5,
            json_output=False,
        )
    )
    capsys.readouterr()

    run_dir = next(entry for entry in runs_dir.iterdir() if entry.is_dir())
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

    assert report["hypothesis_evaluation"]["source"] == "task_spec"


def test_refinement_constraints_block_variant(tmp_path: Path, capsys) -> None:
    task_path = tmp_path / "task.yaml"
    refinement_path = tmp_path / ".cambrian" / "hypotheses" / "refined.yaml"
    runs_dir = tmp_path / "runs"
    _write_yaml(task_path, _competitive_task_payload())
    _write_yaml(
        refinement_path,
        {
            "schema_version": "1.0.0",
            "refinement_id": "href-001",
            "status": "ready",
            "refined_hypothesis": {
                "id": "refined-hypothesis",
                "statement": "competitive refinement 가설",
                "predicts": {"tests": {"passed_min": 1, "failed_max": 0}},
            },
            "constraints": {
                "blocked_variant_ids": ["variant_b"],
                "recommended_variant_count": 3,
                "risk_flags": ["repeated_no_winner"],
            },
            "required_evidence": ["Post-apply pytest result must be present"],
            "warnings": [],
            "errors": [],
        },
    )

    _handle_brain_run(
        argparse.Namespace(
            task_spec=str(task_path),
            generation_seed_path=None,
            selection_pressure_path=None,
            hypothesis_refinement_path=str(refinement_path),
            runs_dir=str(runs_dir),
            workspace=str(tmp_path),
            max_iterations=5,
            json_output=False,
        )
    )
    capsys.readouterr()

    run_dir = next(entry for entry in runs_dir.iterdir() if entry.is_dir())
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    variants = {
        variant["variant_id"]: variant
        for variant in report["competitive_generation"]["variants"]
    }

    assert report["competitive_generation"]["winner_variant_id"] == "variant_a"
    assert variants["variant_b"]["excluded_from_winner"] is True
    assert report["hypothesis_refinement_context"]["constraints_applied"]["blocked_variant_ids"] == ["variant_b"]


def test_malformed_refinement_does_not_crash(tmp_path: Path, capsys) -> None:
    task_path = tmp_path / "task.yaml"
    refinement_path = tmp_path / ".cambrian" / "hypotheses" / "bad_refined.yaml"
    runs_dir = tmp_path / "runs"
    _write_yaml(task_path, _task_payload())
    refinement_path.parent.mkdir(parents=True, exist_ok=True)
    refinement_path.write_text(":\n- bad", encoding="utf-8")

    _handle_brain_run(
        argparse.Namespace(
            task_spec=str(task_path),
            generation_seed_path=None,
            selection_pressure_path=None,
            hypothesis_refinement_path=str(refinement_path),
            runs_dir=str(runs_dir),
            workspace=str(tmp_path),
            max_iterations=5,
            json_output=False,
        )
    )
    captured = capsys.readouterr()

    run_dir = next(entry for entry in runs_dir.iterdir() if entry.is_dir())
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

    assert "Warning: refined hypothesis 로드 실패" in captured.err
    assert report["hypothesis_refinement_context"]["enabled"] is True
    assert report["hypothesis_refinement_context"]["errors"]


def test_source_immutability(tmp_path: Path) -> None:
    seed_path = tmp_path / ".cambrian" / "next_generation" / "seed.yaml"
    pressure_path = tmp_path / ".cambrian" / "evolution" / "_selection_pressure.yaml"
    task_path = tmp_path / "task.yaml"
    refinement_path = tmp_path / ".cambrian" / "hypotheses" / "refined.yaml"
    _write_yaml(seed_path, _seed_payload())
    _write_yaml(pressure_path, _pressure_payload())
    _write_yaml(task_path, _task_payload())

    before = {
        seed_path: _sha256(seed_path),
        pressure_path: _sha256(pressure_path),
        task_path: _sha256(task_path),
    }

    refinement = HypothesisRefiner().refine(
        seed_path=seed_path,
        pressure_path=pressure_path,
        task_spec_path=task_path,
        project_root=tmp_path,
    )
    HypothesisRefinementStore().save(refinement, refinement_path)

    after = {
        seed_path: _sha256(seed_path),
        pressure_path: _sha256(pressure_path),
        task_path: _sha256(task_path),
    }
    assert before == after
