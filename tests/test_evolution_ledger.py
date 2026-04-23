"""Evolution ledger 테스트."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from engine.brain.evolution_ledger import EvolutionLedgerBuilder, EvolutionLedgerStore
from engine.cli import (
    _handle_evolution_lineage,
    _handle_evolution_list,
    _handle_evolution_rebuild_ledger,
    _handle_evolution_show,
)


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


def _brain_report(
    run_id: str,
    *,
    status: str = "completed",
    hypothesis_status: str = "supported",
    hypothesis_id: str = "hyp-base",
    competitive_status: str = "success",
    winner_variant_id: str | None = "variant_a",
    selection_reason: str = "variant_a selected",
    feedback_seed_path: str | None = None,
    remaining_risks: list[str] | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "task_id": f"task-{run_id}",
        "status": status,
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "hypothesis_evaluation": {
            "status": hypothesis_status,
            "hypothesis_id": hypothesis_id,
        },
        "competitive_generation": {
            "enabled": True,
            "status": competitive_status,
            "winner_variant_id": winner_variant_id,
            "selection_reason": selection_reason,
            "variants": [],
        },
        "feedback_context": {
            "enabled": bool(feedback_seed_path),
            "source_seed_path": feedback_seed_path,
            "source_feedback_refs": [],
        },
        "remaining_risks": list(remaining_risks or []),
        "next_actions": [],
        "started_at": "2026-04-21T00:00:00+00:00",
        "finished_at": "2026-04-21T00:01:00+00:00",
    }


def _adoption_record(brain_run_id: str, *, adoption_id: str = "adoption-001") -> dict:
    return {
        "schema_version": "1.0.0",
        "adoption_id": adoption_id,
        "adoption_type": "brain_generation",
        "created_at": "2026-04-21T00:02:00+00:00",
        "brain_run_id": brain_run_id,
        "winner_variant_id": "variant_a",
        "adoption_status": "adopted",
        "source_report_path": f".cambrian/brain/runs/{brain_run_id}/report.json",
        "source_task_spec_path": f".cambrian/brain/runs/{brain_run_id}/task_spec.yaml",
        "competitive_generation": {
            "status": "success",
            "winner_variant_id": "variant_a",
            "selection_reason": "variant_a selected",
        },
        "hypothesis_evaluation": {
            "status": "supported",
            "hypothesis_id": "hyp-base",
        },
        "post_apply_tests": {
            "passed": 1,
            "failed": 0,
            "skipped": 0,
        },
        "provenance": {
            "source": "brain_competitive_generation",
            "stable_ref": brain_run_id,
        },
    }


def _feedback_record(
    *,
    feedback_id: str,
    brain_run_id: str | None = None,
    adoption_id: str | None = None,
    outcome: str = "success",
    next_generation_seed_path: str | None = None,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "feedback_id": feedback_id,
        "created_at": "2026-04-21T00:03:00+00:00",
        "source_type": "brain_report" if brain_run_id else "adoption_record",
        "source_ref": (
            f".cambrian/brain/runs/{brain_run_id}/report.json"
            if brain_run_id
            else f".cambrian/adoptions/{adoption_id}.json"
        ),
        "brain_run_id": brain_run_id,
        "adoption_id": adoption_id,
        "winner_variant_id": "variant_a",
        "outcome": outcome,
        "outcome_reasons": [outcome],
        "keep_patterns": ["Keep winner variant pattern: variant_a"],
        "avoid_patterns": ["Avoid previously failed variant: variant_b"],
        "missing_evidence": [],
        "suggested_next_actions": ["Generate alternative variant actions"],
        "human_feedback": {},
        "source_artifacts": {},
        "next_generation_seed_path": next_generation_seed_path,
    }


def _next_generation_seed(
    source_feedback_ref: str,
    *,
    source_brain_run_id: str | None = None,
    source_adoption_id: str | None = None,
) -> dict:
    return {
        "source_feedback_ref": source_feedback_ref,
        "source_brain_run_id": source_brain_run_id,
        "source_adoption_id": source_adoption_id,
        "generation_intent": "revise_and_retry",
        "previous_outcome": {
            "outcome": "failure",
            "reasons": ["hypothesis contradicted"],
        },
        "lessons": {
            "keep": ["Keep minimal file layout"],
            "avoid": ["Avoid variant_b because pytest failed"],
            "missing_evidence": ["No core_bridge evidence was available"],
        },
    }


def _task_spec(goal: str, *, seed_path: str | None = None, feedback_refs: list[str] | None = None) -> dict:
    data = {
        "task_id": goal.replace(" ", "-"),
        "goal": goal,
    }
    if seed_path:
        data["generation_seed"] = {"source_seed_path": seed_path}
    if feedback_refs:
        data["feedback_refs"] = feedback_refs
    return data


def test_build_ledger_from_single_brain_report(tmp_path: Path) -> None:
    report_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    _write_json(report_path, _brain_report("brain-001"))

    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )

    assert len(ledger.nodes) == 1
    node = ledger.nodes[0]
    assert node.generation_id == "gen-brain-001"
    assert node.outcome == "success"


def test_adoption_record_links_to_generation(tmp_path: Path) -> None:
    report_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    adoption_path = tmp_path / ".cambrian" / "adoptions" / "adoption_001.json"
    _write_json(report_path, _brain_report("brain-001"))
    _write_json(adoption_path, _adoption_record("brain-001"))

    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )

    node = ledger.nodes[0]
    assert node.adoption_refs == [".cambrian/adoptions/adoption_001.json"]
    assert node.outcome == "adopted"


def test_feedback_and_seed_link_parent_to_child(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".cambrian" / "brain" / "runs"
    feedback_dir = tmp_path / ".cambrian" / "feedback"
    next_dir = tmp_path / ".cambrian" / "next_generation"

    parent_report = runs_dir / "brain-001" / "report.json"
    child_report = runs_dir / "brain-002" / "report.json"
    feedback_path = feedback_dir / "feedback_001.json"
    seed_path = next_dir / "next_generation_001.yaml"
    child_seed_ref = ".cambrian/next_generation/next_generation_001.yaml"
    feedback_ref = ".cambrian/feedback/feedback_001.json"

    _write_json(parent_report, _brain_report("brain-001"))
    _write_json(
        child_report,
        _brain_report("brain-002", feedback_seed_path=child_seed_ref),
    )
    _write_yaml(
        runs_dir / "brain-002" / "task_spec.yaml",
        _task_spec("child generation", seed_path=child_seed_ref),
    )
    _write_json(
        feedback_path,
        _feedback_record(
            feedback_id="feedback-001",
            brain_run_id="brain-001",
            next_generation_seed_path=child_seed_ref,
        ),
    )
    _write_yaml(
        seed_path,
        _next_generation_seed(
            feedback_ref,
            source_brain_run_id="brain-001",
        ),
    )

    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=runs_dir,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=feedback_dir,
        next_generation_dir=next_dir,
        project_root=tmp_path,
    )

    nodes = {node.generation_id: node for node in ledger.nodes}
    assert "gen-brain-001" in nodes["gen-brain-002"].parent_generation_ids
    assert "gen-brain-002" in nodes["gen-brain-001"].child_generation_ids


def test_missing_parent_warning(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".cambrian" / "brain" / "runs"
    next_dir = tmp_path / ".cambrian" / "next_generation"
    child_report = runs_dir / "brain-002" / "report.json"
    child_seed_ref = ".cambrian/next_generation/next_generation_missing.yaml"
    _write_json(
        child_report,
        _brain_report("brain-002", feedback_seed_path=child_seed_ref),
    )
    _write_yaml(
        next_dir / "next_generation_missing.yaml",
        _next_generation_seed(".cambrian/feedback/missing.json"),
    )

    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=runs_dir,
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=next_dir,
        project_root=tmp_path,
    )

    node = ledger.nodes[0]
    assert any("parent source not found" in warning for warning in node.warnings)


def test_malformed_source_file_handling(tmp_path: Path) -> None:
    report_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("{bad json", encoding="utf-8")

    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )

    assert ledger.nodes == []
    assert ledger.warnings
    assert ledger.errors


def test_outcome_classification(tmp_path: Path) -> None:
    runs_dir = tmp_path / ".cambrian" / "brain" / "runs"
    adoptions_dir = tmp_path / ".cambrian" / "adoptions"

    _write_json(runs_dir / "brain-adopted" / "report.json", _brain_report("brain-adopted"))
    _write_json(adoptions_dir / "adoption_001.json", _adoption_record("brain-adopted"))
    _write_json(runs_dir / "brain-success" / "report.json", _brain_report("brain-success"))
    _write_json(
        runs_dir / "brain-no-winner" / "report.json",
        _brain_report(
            "brain-no-winner",
            competitive_status="no_winner",
            winner_variant_id=None,
            selection_reason="no eligible winner",
        ),
    )
    _write_json(
        runs_dir / "brain-failed" / "report.json",
        _brain_report(
            "brain-failed",
            status="failed",
            hypothesis_status="contradicted",
            competitive_status="failure",
            winner_variant_id=None,
        ),
    )
    _write_json(
        runs_dir / "brain-mixed" / "report.json",
        _brain_report(
            "brain-mixed",
            competitive_status="skipped",
            winner_variant_id=None,
            remaining_risks=["manual review needed"],
        ),
    )
    _write_json(
        runs_dir / "brain-inconclusive" / "report.json",
        {
            "run_id": "brain-inconclusive",
            "task_id": "task-brain-inconclusive",
            "status": "running",
        },
    )

    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=runs_dir,
        adoptions_dir=adoptions_dir,
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )
    outcome_map = {node.generation_id: node.outcome for node in ledger.nodes}

    assert outcome_map["gen-brain-adopted"] == "adopted"
    assert outcome_map["gen-brain-success"] == "success"
    assert outcome_map["gen-brain-no-winner"] == "no_winner"
    assert outcome_map["gen-brain-failed"] == "failed"
    assert outcome_map["gen-brain-mixed"] == "mixed"
    assert outcome_map["gen-brain-inconclusive"] == "inconclusive"


def test_rebuild_idempotency(tmp_path: Path) -> None:
    report_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    _write_json(report_path, _brain_report("brain-001"))

    builder = EvolutionLedgerBuilder()
    first = builder.build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )
    second = builder.build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )

    assert [node.generation_id for node in first.nodes] == [
        node.generation_id for node in second.nodes
    ]
    assert [node.parent_generation_ids for node in first.nodes] == [
        node.parent_generation_ids for node in second.nodes
    ]


def test_cli_rebuild_ledger_smoke(tmp_path: Path, capsys) -> None:
    report_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    ledger_path = tmp_path / ".cambrian" / "evolution" / "_ledger.json"
    _write_json(report_path, _brain_report("brain-001"))

    args = argparse.Namespace(
        brain_runs_dir=str(tmp_path / ".cambrian" / "brain" / "runs"),
        adoptions_dir=str(tmp_path / ".cambrian" / "adoptions"),
        feedback_dir=str(tmp_path / ".cambrian" / "feedback"),
        next_generation_dir=str(tmp_path / ".cambrian" / "next_generation"),
        ledger_out=str(ledger_path),
        json_output=False,
    )
    _handle_evolution_rebuild_ledger(args)
    captured = capsys.readouterr()

    assert ledger_path.exists()
    assert "[EVOLUTION] ledger rebuilt" in captured.out


def test_cli_list_show_lineage_smoke(tmp_path: Path, capsys) -> None:
    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )
    if not ledger.nodes:
        _write_json(
            tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json",
            _brain_report("brain-001"),
        )
        ledger = EvolutionLedgerBuilder().build(
            brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
            adoptions_dir=tmp_path / ".cambrian" / "adoptions",
            feedback_dir=tmp_path / ".cambrian" / "feedback",
            next_generation_dir=tmp_path / ".cambrian" / "next_generation",
            project_root=tmp_path,
        )

    ledger_path = tmp_path / ".cambrian" / "evolution" / "_ledger.json"
    EvolutionLedgerStore().save(ledger, ledger_path)

    _handle_evolution_list(
        argparse.Namespace(
            ledger_path=str(ledger_path),
            outcome=None,
            limit=None,
            json_output=False,
        )
    )
    list_output = capsys.readouterr().out
    assert "Generation Ledger" in list_output

    _handle_evolution_show(
        argparse.Namespace(
            ledger_path=str(ledger_path),
            generation_id=ledger.nodes[0].generation_id,
            json_output=False,
        )
    )
    show_output = capsys.readouterr().out
    assert "Generation:" in show_output

    _handle_evolution_lineage(
        argparse.Namespace(
            ledger_path=str(ledger_path),
            generation_id=ledger.nodes[0].generation_id,
            json_output=False,
        )
    )
    lineage_output = capsys.readouterr().out
    assert ledger.nodes[0].generation_id in lineage_output


def test_source_immutability(tmp_path: Path) -> None:
    report_path = tmp_path / ".cambrian" / "brain" / "runs" / "brain-001" / "report.json"
    adoption_path = tmp_path / ".cambrian" / "adoptions" / "adoption_001.json"
    feedback_path = tmp_path / ".cambrian" / "feedback" / "feedback_001.json"
    seed_path = tmp_path / ".cambrian" / "next_generation" / "next_generation_001.yaml"
    _write_json(report_path, _brain_report("brain-001"))
    _write_json(adoption_path, _adoption_record("brain-001"))
    _write_json(
        feedback_path,
        _feedback_record(
            feedback_id="feedback-001",
            brain_run_id="brain-001",
            next_generation_seed_path=".cambrian/next_generation/next_generation_001.yaml",
        ),
    )
    _write_yaml(
        seed_path,
        _next_generation_seed(".cambrian/feedback/feedback_001.json", source_brain_run_id="brain-001"),
    )

    before = {
        report_path: _sha256(report_path),
        adoption_path: _sha256(adoption_path),
        feedback_path: _sha256(feedback_path),
        seed_path: _sha256(seed_path),
    }

    EvolutionLedgerBuilder().build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )

    after = {
        report_path: _sha256(report_path),
        adoption_path: _sha256(adoption_path),
        feedback_path: _sha256(feedback_path),
        seed_path: _sha256(seed_path),
    }
    assert before == after


def test_empty_directories(tmp_path: Path) -> None:
    ledger = EvolutionLedgerBuilder().build(
        brain_runs_dir=tmp_path / ".cambrian" / "brain" / "runs",
        adoptions_dir=tmp_path / ".cambrian" / "adoptions",
        feedback_dir=tmp_path / ".cambrian" / "feedback",
        next_generation_dir=tmp_path / ".cambrian" / "next_generation",
        project_root=tmp_path,
    )

    assert ledger.nodes == []
    assert ledger.latest_generation_id is None
