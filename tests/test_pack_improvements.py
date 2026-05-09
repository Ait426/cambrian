from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_authoring import PackBuilder, PackDraftBuilder, save_pack_draft
from engine.project_pack_improvements import (
    PackImprovementQueueBuilder,
    PackImprovementStore,
    default_pack_improvement_decisions_path,
    default_pack_improvement_items_dir,
    default_pack_improvement_queue_path,
    latest_pack_improvement_queue,
    record_pack_improvement_decision,
    render_pack_improvement_compact,
    save_pack_improvement_queue,
)
from engine.project_pack_install import SCHEMA_VERSION, PackInstaller
from engine.project_pack_proof import PackProofBuilder
from engine.project_pack_release import (
    PackProofSummary,
    PackReleaseCheck,
    PackReleaseChecker,
    PackReleaseReport,
    save_pack_release_report,
)
from engine.project_pack_retrospective import (
    PackImprovementSuggestion,
    PackRetrospectiveSummary,
    save_pack_retro_summary,
)


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"


def _cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _summary(
    root: Path,
    *,
    pack_id: str = "auth-bug-core",
    signal_counts: dict[str, dict[str, int]] | None = None,
    outcome_counts: dict[str, int] | None = None,
    suggestions: list[PackImprovementSuggestion] | None = None,
) -> PackRetrospectiveSummary:
    summary = PackRetrospectiveSummary(
        schema_version=SCHEMA_VERSION,
        summary_id=f"summary-{pack_id}-test",
        generated_at="2026-05-04T00:00:00+00:00",
        pack_ref=pack_id,
        pack_id=pack_id,
        pack_name="Auth Bug Core",
        namespace=None,
        version="0.1.0",
        total_retrospectives=4,
        outcome_counts={
            "worked_well": 0,
            "needs_improvement": 0,
            "blocked_before_validation": 0,
            "validated_but_not_adopted": 0,
            "applied_but_rejected": 0,
            "regression_or_safety_issue": 0,
            "insufficient_data": 0,
            **(outcome_counts or {}),
        },
        signal_counts=signal_counts or {},
        top_positive_signals=[],
        top_negative_signals=[
            kind
            for kind, counts in (signal_counts or {}).items()
            if int(counts.get("negative", 0) or 0) > 0
        ],
        top_suggestions=suggestions or [],
        known_limits=[],
        benchmark_case_candidates=[],
        summary=["test retrospective summary"],
        warnings=[],
        errors=[],
    )
    save_pack_retro_summary(root, summary)
    return summary


def _install_seed(root: Path) -> None:
    PackInstaller().install(root, SEED_MANIFEST)


def _built_manifest(root: Path, pack_id: str = "auth-bug-core-local") -> Path:
    _install_seed(root)
    draft = PackDraftBuilder().create(
        root,
        pack_id,
        "lane",
        {
            "workers": ["bug-fix-agent"],
            "teams": ["auth-bug-team"],
            "templates": ["auth-bug-template"],
            "benchmarks": ["auth-bug-workset"],
            "lane": "python-pytest-auth-bug-core",
        },
        version="0.1.0",
        description="Local authored auth bug lane pack",
        tags=["auth", "login", "pytest"],
    )
    draft_ref = save_pack_draft(root, draft)
    out = root / "packs" / "generated" / f"{pack_id}.cambrian-pack.yaml"
    report = PackBuilder().build(root, root / draft_ref, out_path=out)
    assert report.status == "built"
    return out


def _kinds(queue) -> set[str]:
    return {item.kind for item in queue.items}


def test_build_queue_from_retro_summary(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})

    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")

    assert "strengthen_context_hints" in _kinds(queue)
    item = next(item for item in queue.items if item.kind == "strengthen_context_hints")
    assert item.priority == "high"
    assert "validated_proposal_rate" in item.affected_metrics


def test_build_queue_from_bridge_quality_negative(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"bridge_quality": {"negative": 1}})

    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")

    assert "improve_response_contract" in _kinds(queue)


def test_build_queue_from_validation_quality_negative(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"validation_quality": {"negative": 1}})

    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")

    assert "improve_validation_support" in _kinds(queue)


def test_build_queue_from_release_check_safety_warning(tmp_path: Path) -> None:
    report = PackReleaseReport(
        schema_version=SCHEMA_VERSION,
        report_id="release-auth-bug-core-regression-safety",
        generated_at="2026-05-04T00:00:00+00:00",
        pack_id="auth-bug-core",
        pack_name="Auth Bug Core",
        pack_kind="lane",
        version="0.1.0",
        manifest_ref="packs/auth-bug-core.cambrian-pack.yaml",
        manifest_sha256="abc123",
        maturity="candidate",
        proof_summary=PackProofSummary(proof_status="none"),
        compatibility_summary={},
        trust_summary={},
        checks=[
            PackReleaseCheck(
                check_id="regression_guard",
                title="Regression guard",
                status="warn",
                summary="release-check found regression safety blocker",
                warnings=["regression safety issue blocks maturity promotion"],
            )
        ],
        safe_to_publish=True,
        require_proof_satisfied=False,
        summary=["maturity=candidate"],
        warnings=["release-check maturity caution"],
        errors=[],
    )
    release_ref = save_pack_release_report(tmp_path, report)

    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")

    assert {"improve_validation_support", "update_known_limits"} <= _kinds(queue)
    item = next(item for item in queue.items if item.kind == "improve_validation_support")
    assert release_ref in item.evidence_refs
    assert "regression_free_apply_rate" in item.affected_metrics


def test_repeated_worked_well_creates_benchmark_or_docs_suggestion(tmp_path: Path) -> None:
    _summary(tmp_path, outcome_counts={"worked_well": 3})

    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")

    assert {"add_benchmark_case", "update_pack_docs"} & _kinds(queue)


def test_priority_confidence_deterministic(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})

    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")
    item = next(item for item in queue.items if item.kind == "strengthen_context_hints")

    assert queue.top_item_id == item.item_id
    assert item.priority == "high"
    assert item.confidence >= 0.6


def test_improvements_list_show_cli(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})

    improve = _cli(tmp_path, "pack", "improve", "auth-bug-core")
    list_result = _cli(tmp_path, "pack", "improvements", "auth-bug-core")
    items = PackImprovementStore().list_items(default_pack_improvement_items_dir(tmp_path), "auth-bug-core")
    show = _cli(tmp_path, "pack", "improvement-show", items[0].item_id)

    assert improve.returncode == 0, improve.stderr
    assert list_result.returncode == 0, list_result.stderr
    assert show.returncode == 0, show.stderr
    assert "strengthen_context_hints" in improve.stdout
    assert "Pack Improvement" in show.stdout


def test_accept_decision_no_mutation(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'unchanged'\n", encoding="utf-8")
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})
    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")
    save_pack_improvement_queue(tmp_path, queue)
    item = next(item for item in queue.items if item.kind == "strengthen_context_hints")

    decision, updated, _ = record_pack_improvement_decision(tmp_path, item.item_id, "accepted", "Will review context hints")

    assert decision.status == "accepted"
    assert updated.status == "accepted"
    assert default_pack_improvement_decisions_path(tmp_path).exists()
    assert source.read_text(encoding="utf-8") == "VALUE = 'unchanged'\n"


def test_dismiss_decision_latest_wins(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})
    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")
    save_pack_improvement_queue(tmp_path, queue)
    item = next(item for item in queue.items if item.kind == "strengthen_context_hints")

    record_pack_improvement_decision(tmp_path, item.item_id, "accepted", "maybe")
    record_pack_improvement_decision(tmp_path, item.item_id, "dismissed", "not enough evidence")
    rebuilt = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")
    rebuilt_item = next(candidate for candidate in rebuilt.items if candidate.item_id == item.item_id)

    assert rebuilt_item.status == "dismissed"


def test_decision_refreshes_stale_per_pack_queue(tmp_path: Path) -> None:
    _summary(tmp_path, pack_id="pack-a", signal_counts={"context_fit": {"negative": 4}})
    queue_a = PackImprovementQueueBuilder().build(tmp_path, "pack-a")
    save_pack_improvement_queue(tmp_path, queue_a)
    item_a = next(item for item in queue_a.items if item.kind == "strengthen_context_hints")

    _summary(tmp_path, pack_id="pack-b", signal_counts={"validation_quality": {"negative": 2}})
    queue_b = PackImprovementQueueBuilder().build(tmp_path, "pack-b")
    save_pack_improvement_queue(tmp_path, queue_b)
    assert latest_pack_improvement_queue(tmp_path).pack_id == "pack-b"

    record_pack_improvement_decision(tmp_path, item_a.item_id, "dismissed", "not relevant for pack-a")
    refreshed_a = latest_pack_improvement_queue(tmp_path, "pack-a")

    assert refreshed_a is not None
    refreshed_item = next(item for item in refreshed_a.items if item.item_id == item_a.item_id)
    assert refreshed_item.status == "dismissed"


def test_proof_release_show_status_integration(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})
    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")
    save_pack_improvement_queue(tmp_path, queue)

    proof = PackProofBuilder().build(tmp_path, "auth-bug-core")
    manifest = _built_manifest(tmp_path)
    report = PackReleaseChecker().check(tmp_path, str(manifest))
    compact = render_pack_improvement_compact(queue)

    assert any("top improvement" in item for item in proof.where_weak)
    assert any("open high-priority improvement" in warning for warning in report.proof_summary.warnings)
    assert "Open improvements" in compact


def test_source_immutability(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'unchanged'\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    _summary(tmp_path, signal_counts={"validation_quality": {"negative": 2}})

    improve = _cli(tmp_path, "pack", "improve", "auth-bug-core")
    items = PackImprovementStore().list_items(default_pack_improvement_items_dir(tmp_path), "auth-bug-core")
    accept = _cli(tmp_path, "pack", "improvement-accept", items[0].item_id, "--resolution", "track")
    dismiss = _cli(tmp_path, "pack", "improvement-dismiss", items[0].item_id, "--resolution", "superseded")

    assert improve.returncode == 0, improve.stderr
    assert accept.returncode == 0, accept.stderr
    assert dismiss.returncode == 0, dismiss.stderr
    assert source.read_text(encoding="utf-8") == before
    assert default_pack_improvement_queue_path(tmp_path).exists()
