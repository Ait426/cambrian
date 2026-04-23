"""Selection pressure 테스트."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from engine.brain.evolution_ledger import EvolutionLedger, GenerationNode
from engine.brain.models import TaskSpec
from engine.brain.runner import RALFRunner
from engine.brain.selection_pressure import (
    SelectionPressureBuilder,
    SelectionPressureStore,
)
from engine.cli import _handle_brain_run, _handle_evolution_build_pressure


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


def _node(
    generation_id: str,
    *,
    outcome: str,
    winner_variant_id: str | None = None,
    hypothesis_status: str | None = None,
    hypothesis_id: str | None = None,
    competitive_status: str | None = None,
    warnings: list[str] | None = None,
    competitive_variants: list[dict] | None = None,
) -> GenerationNode:
    return GenerationNode(
        generation_id=generation_id,
        brain_run_id=generation_id.replace("gen-", ""),
        created_at="2026-04-21T00:00:00+00:00",
        source_report_path=None,
        source_run_state_path=None,
        source_task_spec_path=None,
        task_id=f"task-{generation_id}",
        goal=f"goal-{generation_id}",
        status="completed",
        hypothesis_status=hypothesis_status,
        hypothesis_id=hypothesis_id,
        competitive_status=competitive_status,
        winner_variant_id=winner_variant_id,
        selection_reason=(
            f"{winner_variant_id} selected"
            if winner_variant_id
            else None
        ),
        adoption_status="adopted" if outcome == "adopted" else None,
        outcome=outcome,
        summary={
            "competitive_variants": list(competitive_variants or []),
            "remaining_risks": [],
        },
        warnings=list(warnings or []),
    )


def _ledger(nodes: list[GenerationNode]) -> EvolutionLedger:
    return EvolutionLedger(
        schema_version="1.0.0",
        generated_at="2026-04-21T00:00:00+00:00",
        source_counts={"nodes": len(nodes)},
        latest_generation_id=nodes[-1].generation_id if nodes else None,
        nodes=nodes,
        warnings=[],
        errors=[],
    )


def _competitive_task() -> TaskSpec:
    return TaskSpec(
        task_id="task-pressure-competitive",
        goal="selection pressure를 반영한 competitive run",
        scope=["variant를 격리 실행한다"],
        non_goals=[],
        acceptance_criteria=["test_add.py 파일 생성", "pytest 통과"],
        related_files=[],
        related_tests=["test_add.py"],
        output_paths=["test_add.py"],
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
    )


def _standard_task_data() -> dict:
    return {
        "task_id": "task-pressure-standard",
        "goal": "pressure를 가진 일반 run",
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


def test_build_pressure_from_empty_ledger() -> None:
    pressure = SelectionPressureBuilder().build(
        _ledger([]),
        options={"source_ledger_path": ".cambrian/evolution/_ledger.json"},
    )

    assert pressure.pressure_status == "empty"
    assert pressure.keep_patterns == []


def test_build_keep_patterns_from_adopted_success_nodes() -> None:
    pressure = SelectionPressureBuilder().build(
        _ledger(
            [
                _node(
                    "gen-brain-001",
                    outcome="adopted",
                    winner_variant_id="variant_a",
                    hypothesis_status="supported",
                    hypothesis_id="hyp-pass",
                    competitive_status="success",
                ),
            ]
        ),
        options={"source_ledger_path": ".cambrian/evolution/_ledger.json"},
    )

    assert any("Keep winner variant pattern: variant_a" in item for item in pressure.keep_patterns)
    assert pressure.recommended_variant_count == 2
    assert pressure.rationale


def test_build_avoid_and_blocked_variant_ids_from_failures() -> None:
    pressure = SelectionPressureBuilder().build(
        _ledger(
            [
                _node(
                    "gen-brain-002",
                    outcome="failed",
                    hypothesis_status="contradicted",
                    hypothesis_id="hyp-old",
                    competitive_status="failure",
                    competitive_variants=[
                        {
                            "variant_id": "variant_b",
                            "status": "failure",
                            "hypothesis_status": "contradicted",
                        },
                    ],
                ),
            ]
        ),
        options={"source_ledger_path": ".cambrian/evolution/_ledger.json"},
    )

    assert "variant_b" in pressure.blocked_variant_ids
    assert any("hyp-old" in item for item in pressure.avoid_patterns)


def test_success_later_removes_blocked_variant() -> None:
    pressure = SelectionPressureBuilder().build(
        _ledger(
            [
                _node(
                    "gen-brain-001",
                    outcome="failed",
                    competitive_variants=[
                        {
                            "variant_id": "variant_b",
                            "status": "failure",
                            "hypothesis_status": "contradicted",
                        },
                    ],
                ),
                _node(
                    "gen-brain-002",
                    outcome="adopted",
                    winner_variant_id="variant_b",
                    hypothesis_status="supported",
                    hypothesis_id="hyp-fixed",
                    competitive_status="success",
                ),
            ]
        ),
        options={"source_ledger_path": ".cambrian/evolution/_ledger.json"},
    )

    assert "variant_b" not in pressure.blocked_variant_ids


def test_risk_flags() -> None:
    pressure = SelectionPressureBuilder().build(
        _ledger(
            [
                _node(
                    "gen-a",
                    outcome="no_winner",
                    competitive_status="no_winner",
                    warnings=["parent source not found: feedback"],
                ),
                _node(
                    "gen-b",
                    outcome="no_winner",
                    competitive_status="no_winner",
                    hypothesis_status="contradicted",
                    hypothesis_id="hyp-repeat",
                    warnings=["parent source not found: generation"],
                ),
                _node(
                    "gen-c",
                    outcome="failed",
                    hypothesis_status="contradicted",
                    hypothesis_id="hyp-repeat",
                    competitive_variants=[
                        {
                            "variant_id": "variant_z",
                            "status": "failure",
                            "hypothesis_status": "contradicted",
                        },
                    ],
                ),
            ]
        ),
        options={"source_ledger_path": ".cambrian/evolution/_ledger.json"},
    )

    assert "repeated_no_winner" in pressure.risk_flags
    assert "repeated_contradicted_hypothesis" in pressure.risk_flags
    assert "missing_evidence_repeated" in pressure.risk_flags


def test_cli_build_pressure_smoke(tmp_path: Path, capsys) -> None:
    ledger = _ledger(
        [
            _node(
                "gen-brain-001",
                outcome="adopted",
                winner_variant_id="variant_a",
                hypothesis_status="supported",
                hypothesis_id="hyp-pass",
                competitive_status="success",
            ),
        ]
    )
    ledger_path = tmp_path / ".cambrian" / "evolution" / "_ledger.json"
    pressure_path = tmp_path / ".cambrian" / "evolution" / "_selection_pressure.yaml"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(ledger.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _handle_evolution_build_pressure(
        argparse.Namespace(
            ledger_path=str(ledger_path),
            pressure_out=str(pressure_path),
            json_output=False,
        )
    )
    output = capsys.readouterr().out

    assert pressure_path.exists()
    assert "[PRESSURE] selection pressure built" in output


def test_task_spec_selection_pressure_round_trip(tmp_path: Path) -> None:
    pressure_data = {
        "pressure_id": "pressure-001",
        "blocked_variant_ids": ["variant_b"],
        "warned_variant_ids": ["variant_c"],
    }
    spec_path = tmp_path / "task_pressure.yaml"
    _write_yaml(
        spec_path,
        {
            "task_id": "task-pressure-roundtrip",
            "goal": "selection pressure가 round-trip 된다",
            "selection_pressure": pressure_data,
            "selection_pressure_refs": [".cambrian/evolution/_selection_pressure.yaml"],
        },
    )

    loaded = TaskSpec.from_yaml(spec_path)
    assert loaded.selection_pressure == pressure_data
    assert loaded.selection_pressure_refs == [
        ".cambrian/evolution/_selection_pressure.yaml"
    ]

    round_trip_path = tmp_path / "task_pressure_roundtrip.yaml"
    loaded.to_yaml(round_trip_path)
    reloaded = TaskSpec.from_yaml(round_trip_path)
    assert reloaded.selection_pressure == pressure_data


def test_brain_run_pressure_records_context(tmp_path: Path, capsys) -> None:
    task_path = tmp_path / "task.yaml"
    pressure_path = tmp_path / ".cambrian" / "evolution" / "_selection_pressure.yaml"
    runs_dir = tmp_path / "runs"
    _write_yaml(task_path, _standard_task_data())
    SelectionPressureStore().save(
        SelectionPressureBuilder().build(
            _ledger(
                [
                    _node(
                        "gen-brain-001",
                        outcome="failed",
                        competitive_variants=[
                            {
                                "variant_id": "variant_b",
                                "status": "failure",
                                "hypothesis_status": "contradicted",
                            },
                        ],
                    ),
                ]
            ),
            options={"source_ledger_path": ".cambrian/evolution/_ledger.json"},
        ),
        pressure_path,
    )

    _handle_brain_run(
        argparse.Namespace(
            task_spec=str(task_path),
            generation_seed_path=None,
            selection_pressure_path=str(pressure_path),
            runs_dir=str(runs_dir),
            workspace=str(tmp_path),
            max_iterations=5,
            json_output=False,
        )
    )
    capsys.readouterr()

    run_dir = next(entry for entry in runs_dir.iterdir() if entry.is_dir())
    report = _write_json  # type: ignore[assignment]
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    snapshot = TaskSpec.from_yaml(run_dir / "task_spec.yaml")
    original = TaskSpec.from_yaml(task_path)

    assert original.selection_pressure is None
    assert snapshot.selection_pressure is not None
    assert report["selection_pressure_context"]["enabled"] is True
    assert report["selection_pressure_context"]["source_pressure_path"] == str(
        pressure_path.resolve()
    )


def test_pressure_blocks_winner_eligibility(tmp_path: Path) -> None:
    spec = _competitive_task()
    spec.selection_pressure = {
        "source_pressure_path": ".cambrian/evolution/_selection_pressure.yaml",
        "blocked_variant_ids": ["variant_b"],
        "warned_variant_ids": [],
        "keep_patterns": [],
        "avoid_patterns": [],
        "risk_flags": [],
    }

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = json.loads(
        (tmp_path / "runs" / state.run_id / "report.json").read_text(encoding="utf-8")
    )
    variants = {
        variant["variant_id"]: variant
        for variant in report["competitive_generation"]["variants"]
    }

    assert report["competitive_generation"]["winner_variant_id"] == "variant_a"
    assert variants["variant_b"]["pressure_excluded_from_winner"] is True


def test_all_variants_blocked_no_winner(tmp_path: Path) -> None:
    spec = _competitive_task()
    spec.selection_pressure = {
        "blocked_variant_ids": ["variant_a", "variant_b"],
        "warned_variant_ids": [],
        "risk_flags": [],
        "keep_patterns": [],
        "avoid_patterns": [],
    }

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = json.loads(
        (tmp_path / "runs" / state.run_id / "report.json").read_text(encoding="utf-8")
    )

    assert report["competitive_generation"]["status"] == "no_winner"
    assert "excluded" in report["competitive_generation"]["selection_reason"]


def test_warned_variant_not_blocked(tmp_path: Path) -> None:
    spec = _competitive_task()
    spec.selection_pressure = {
        "blocked_variant_ids": [],
        "warned_variant_ids": ["variant_b"],
        "risk_flags": [],
        "keep_patterns": [],
        "avoid_patterns": [],
    }

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = json.loads(
        (tmp_path / "runs" / state.run_id / "report.json").read_text(encoding="utf-8")
    )
    variants = {
        variant["variant_id"]: variant
        for variant in report["competitive_generation"]["variants"]
    }

    assert report["competitive_generation"]["winner_variant_id"] == "variant_b"
    assert "warned by selection pressure warned_variant_ids" in variants["variant_b"]["warnings"]


def test_recommended_variant_count_warning(tmp_path: Path) -> None:
    spec = _competitive_task()
    spec.selection_pressure = {
        "blocked_variant_ids": [],
        "warned_variant_ids": [],
        "recommended_variant_count": 3,
        "risk_flags": [],
        "keep_patterns": [],
        "avoid_patterns": [],
    }

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report = json.loads(
        (tmp_path / "runs" / state.run_id / "report.json").read_text(encoding="utf-8")
    )

    assert any(
        "Selection pressure recommends 3 variants" in action
        for action in report["next_actions"]
    )


def test_malformed_pressure_file_does_not_crash(tmp_path: Path, capsys) -> None:
    task_path = tmp_path / "task.yaml"
    pressure_path = tmp_path / ".cambrian" / "evolution" / "bad_pressure.yaml"
    runs_dir = tmp_path / "runs"
    _write_yaml(task_path, _standard_task_data())
    pressure_path.parent.mkdir(parents=True, exist_ok=True)
    pressure_path.write_text(":\n- bad", encoding="utf-8")

    _handle_brain_run(
        argparse.Namespace(
            task_spec=str(task_path),
            generation_seed_path=None,
            selection_pressure_path=str(pressure_path),
            runs_dir=str(runs_dir),
            workspace=str(tmp_path),
            max_iterations=5,
            json_output=False,
        )
    )
    captured = capsys.readouterr()

    run_dir = next(entry for entry in runs_dir.iterdir() if entry.is_dir())
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))

    assert "Warning: selection pressure 로드 실패" in captured.err
    assert report["selection_pressure_context"]["enabled"] is True
    assert report["selection_pressure_context"]["errors"]
