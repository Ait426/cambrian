"""Brain competitive generation 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine.brain.competitive import CompetitiveGenerationRunner
from engine.brain.models import TaskSpec
from engine.brain.runner import RALFRunner


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _base_hypothesis() -> dict:
    return {
        "id": "hyp-test-pass",
        "statement": "좋은 variant는 pytest를 최소 1개 통과하고 실패는 0개일 것이다.",
        "predicts": {
            "tests": {
                "passed_min": 1,
                "failed_max": 0,
            },
            "files": {
                "created_contains": ["test_add.py"],
            },
        },
    }


def _competitive_variants() -> list[dict]:
    return [
        {
            "id": "variant_a",
            "label": "simple passing implementation",
            "description": "간단한 통과 테스트를 생성한다",
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
        {
            "id": "variant_b",
            "label": "failing implementation",
            "description": "실패하는 테스트를 생성한다",
            "actions": [
                {
                    "type": "write_file",
                    "target_path": "test_add.py",
                    "content": (
                        "def test_add():\n"
                        "    assert 1 + 1 == 3\n"
                    ),
                },
            ],
        },
    ]


def _build_spec(
    *,
    hypothesis: dict | None = None,
    competitive: dict | None = None,
    related_tests: list[str] | None = None,
    output_paths: list[str] | None = None,
    acceptance_criteria: list[str] | None = None,
    actions: list[dict] | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id="task-competitive-smoke",
        goal="같은 테스트를 통과시키는 여러 구현안을 비교한다",
        scope=["variant를 격리 실행한다", "winner를 고른다"],
        non_goals=[],
        acceptance_criteria=(
            acceptance_criteria
            if acceptance_criteria is not None
            else ["test_add.py 파일 생성", "pytest 통과"]
        ),
        related_files=[],
        related_tests=related_tests if related_tests is not None else ["test_add.py"],
        output_paths=output_paths if output_paths is not None else ["test_add.py"],
        hypothesis=hypothesis,
        competitive=competitive,
        actions=actions,
    )


def test_task_spec_competitive_round_trip(tmp_path: Path) -> None:
    spec_path = tmp_path / "task_competitive.yaml"
    data = {
        "task_id": "task-competitive-roundtrip",
        "goal": "competitive 설정이 round-trip 된다",
        "competitive": {
            "enabled": True,
            "max_variants": 3,
            "copy_paths": [],
            "variants": _competitive_variants(),
        },
    }
    _write_yaml(spec_path, data)

    loaded = TaskSpec.from_yaml(spec_path)
    assert loaded.competitive == data["competitive"]

    round_trip_path = tmp_path / "task_competitive_roundtrip.yaml"
    loaded.to_yaml(round_trip_path)
    reloaded = TaskSpec.from_yaml(round_trip_path)
    assert reloaded.competitive == data["competitive"]

    no_competitive = TaskSpec(
        task_id="task-no-competitive",
        goal="기존 task spec도 동작한다",
    )
    assert no_competitive.competitive is None


def test_competitive_success_winner_selection(tmp_path: Path) -> None:
    spec = _build_spec(
        hypothesis=_base_hypothesis(),
        competitive={
            "enabled": True,
            "max_variants": 3,
            "copy_paths": [],
            "variants": _competitive_variants(),
        },
    )

    runner = CompetitiveGenerationRunner()
    result = runner.run(
        spec=spec,
        run_dir=tmp_path / "runs" / "run-success",
        project_root=tmp_path,
    )

    assert result.status == "success"
    assert result.winner_variant_id == "variant_a"
    assert "supported hypothesis" in result.selection_reason

    variant_map = {
        variant.variant_id: variant
        for variant in result.variants
    }
    assert variant_map["variant_a"].test_results["failed"] == 0
    assert variant_map["variant_b"].status == "failure"
    assert not (tmp_path / "test_add.py").exists()


def test_competitive_no_winner_adds_report_next_actions(tmp_path: Path) -> None:
    spec = _build_spec(
        hypothesis=_base_hypothesis(),
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
                                "    assert 1 + 1 == 3\n"
                            ),
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
                                "    assert 1 + 1 == 4\n"
                            ),
                        },
                    ],
                },
            ],
        },
    )

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)

    report_path = tmp_path / "runs" / state.run_id / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert state.status == "completed"
    assert report["competitive_generation"]["status"] == "no_winner"
    assert report["competitive_generation"]["winner_variant_id"] is None
    assert any(
        "Competitive generation found no eligible winner" in action
        for action in report["next_actions"]
    )


def test_competitive_duplicate_variant_id_invalid(tmp_path: Path) -> None:
    spec = _build_spec(
        competitive={
            "enabled": True,
            "variants": [
                {
                    "id": "same_variant",
                    "actions": [
                        {
                            "type": "write_file",
                            "target_path": "a.py",
                            "content": "VALUE = 1\n",
                        },
                    ],
                },
                {
                    "id": "same_variant",
                    "actions": [
                        {
                            "type": "write_file",
                            "target_path": "b.py",
                            "content": "VALUE = 2\n",
                        },
                    ],
                },
            ],
        },
        related_tests=[],
        output_paths=[],
        acceptance_criteria=[],
    )

    runner = CompetitiveGenerationRunner()
    result = runner.run(
        spec=spec,
        run_dir=tmp_path / "runs" / "run-duplicate",
        project_root=tmp_path,
    )

    assert result.status == "failure"
    assert any("duplicate competitive variant id" in error for error in result.errors)


def test_competitive_max_variants_cap(tmp_path: Path) -> None:
    spec = _build_spec(
        competitive={
            "enabled": True,
            "max_variants": 2,
            "variants": [
                {
                    "id": "variant_a",
                    "actions": [
                        {
                            "type": "write_file",
                            "target_path": "a.py",
                            "content": "A = 1\n",
                        },
                    ],
                },
                {
                    "id": "variant_b",
                    "actions": [
                        {
                            "type": "write_file",
                            "target_path": "b.py",
                            "content": "B = 1\n",
                        },
                    ],
                },
                {
                    "id": "variant_c",
                    "actions": [
                        {
                            "type": "write_file",
                            "target_path": "c.py",
                            "content": "C = 1\n",
                        },
                    ],
                },
            ],
        },
        related_tests=[],
        output_paths=[],
        acceptance_criteria=[],
    )

    runner = CompetitiveGenerationRunner()
    result = runner.run(
        spec=spec,
        run_dir=tmp_path / "runs" / "run-max-variants",
        project_root=tmp_path,
    )

    assert result.status == "failure"
    assert any("exceeds configured max_variants" in error for error in result.errors)


def test_competitive_workspace_isolation(tmp_path: Path) -> None:
    spec = _build_spec(
        competitive={
            "enabled": True,
            "variants": _competitive_variants(),
        },
    )

    runner = CompetitiveGenerationRunner()
    result = runner.run(
        spec=spec,
        run_dir=tmp_path / "runs" / "run-isolation",
        project_root=tmp_path,
    )

    assert result.status == "success"
    assert not (tmp_path / "test_add.py").exists()

    variant_a_path = (
        tmp_path / "runs" / "run-isolation" / "variants" / "variant_a" /
        "workspace" / "test_add.py"
    )
    variant_b_path = (
        tmp_path / "runs" / "run-isolation" / "variants" / "variant_b" /
        "workspace" / "test_add.py"
    )
    assert variant_a_path.exists()
    assert variant_b_path.exists()
    assert "== 2" in variant_a_path.read_text(encoding="utf-8")
    assert "== 3" in variant_b_path.read_text(encoding="utf-8")


def test_competitive_copy_paths_patch_only_mutates_variant_workspace(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "module.py"
    source_file.write_text("VALUE = 1\n", encoding="utf-8")

    spec = _build_spec(
        competitive={
            "enabled": True,
            "copy_paths": ["module.py"],
            "variants": [
                {
                    "id": "variant_a",
                    "actions": [
                        {
                            "type": "patch_file",
                            "target_path": "module.py",
                            "old_text": "VALUE = 1\n",
                            "new_text": "VALUE = 2\n",
                        },
                    ],
                },
                {
                    "id": "variant_b",
                    "actions": [
                        {
                            "type": "patch_file",
                            "target_path": "module.py",
                            "old_text": "VALUE = 1\n",
                            "new_text": "VALUE = 3\n",
                        },
                    ],
                },
            ],
        },
        related_tests=[],
        output_paths=[],
        acceptance_criteria=[],
    )

    runner = CompetitiveGenerationRunner()
    result = runner.run(
        spec=spec,
        run_dir=tmp_path / "runs" / "run-copy-paths",
        project_root=tmp_path,
    )

    assert result.status == "success"
    assert source_file.read_text(encoding="utf-8") == "VALUE = 1\n"
    assert (
        tmp_path / "runs" / "run-copy-paths" / "variants" /
        "variant_a" / "workspace" / "module.py"
    ).read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (
        tmp_path / "runs" / "run-copy-paths" / "variants" /
        "variant_b" / "workspace" / "module.py"
    ).read_text(encoding="utf-8") == "VALUE = 3\n"


def test_brain_run_report_contains_competitive_generation(tmp_path: Path) -> None:
    spec = _build_spec(
        hypothesis=_base_hypothesis(),
        competitive={
            "enabled": True,
            "variants": _competitive_variants(),
        },
    )

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report_path = tmp_path / "runs" / state.run_id / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert state.status == "completed"
    assert report["competitive_generation"]["enabled"] is True
    assert report["competitive_generation"]["winner_variant_id"] == "variant_a"
    assert report["competitive_generation"]["selection_reason"]
    assert report["provenance_handoff"]["files_created"] == ["test_add.py"]


def test_competitive_disabled_backward_compatibility(tmp_path: Path) -> None:
    spec = _build_spec(
        competitive=None,
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
    )

    runner = RALFRunner(runs_dir=tmp_path / "runs", workspace=tmp_path)
    state = runner.run(spec, max_iterations=5)
    report_path = tmp_path / "runs" / state.run_id / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert state.status == "completed"
    assert report["competitive_generation"]["enabled"] is False
    assert report["competitive_generation"]["status"] == "skipped"


def test_competitive_hypothesis_supported_variant_is_preferred(
    tmp_path: Path,
) -> None:
    hypothesis = {
        "id": "hyp-winner-marker",
        "statement": "승자 variant는 winner_marker.txt를 추가하고 테스트를 통과한다.",
        "predicts": {
            "tests": {
                "passed_min": 1,
                "failed_max": 0,
            },
            "files": {
                "created_contains": ["winner_marker.txt"],
            },
        },
    }
    spec = _build_spec(
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
                            "target_path": "winner_marker.txt",
                            "content": "winner\n",
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

    runner = CompetitiveGenerationRunner()
    result = runner.run(
        spec=spec,
        run_dir=tmp_path / "runs" / "run-hypothesis-priority",
        project_root=tmp_path,
    )

    variant_map = {
        variant.variant_id: variant
        for variant in result.variants
    }
    assert result.status == "success"
    assert result.winner_variant_id == "variant_a"
    assert variant_map["variant_a"].hypothesis_status == "supported"
    assert variant_map["variant_b"].hypothesis_status == "contradicted"
