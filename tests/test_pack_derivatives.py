from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_authoring import PackBuilder, PackDraftBuilder, load_pack_draft, save_pack_draft
from engine.project_pack_derivatives import (
    PackDerivativeCreator,
    PackDerivativePlanner,
    PackDerivativeStore,
    accepted_improvement_count,
    default_pack_derivative_plans_dir,
    latest_pack_derivative_plan,
    render_pack_derivative_compact,
    save_pack_derivative_plan,
    save_pack_derivative_workspace,
)
from engine.project_pack_improvements import (
    PackImprovementQueueBuilder,
    PackImprovementStore,
    default_pack_improvement_items_dir,
    latest_pack_improvement_queue,
    record_pack_improvement_decision,
    save_pack_improvement_queue,
)
from engine.project_pack_install import SCHEMA_VERSION, PackInstaller
from engine.project_pack_release import PackReleaseChecker
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
    signal_counts: dict[str, dict[str, int]] | None = None,
    outcome_counts: dict[str, int] | None = None,
    suggestions: list[PackImprovementSuggestion] | None = None,
) -> PackRetrospectiveSummary:
    summary = PackRetrospectiveSummary(
        schema_version=SCHEMA_VERSION,
        summary_id="summary-auth-bug-core-derivative-test",
        generated_at="2026-05-04T00:00:00+00:00",
        pack_ref="auth-bug-core",
        pack_id="auth-bug-core",
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
        summary=["test derivative retrospective summary"],
        warnings=[],
        errors=[],
    )
    save_pack_retro_summary(root, summary)
    return summary


def _accepted_item(root: Path, kind: str = "strengthen_context_hints") -> str:
    suggestions = None
    signal_counts = {"context_fit": {"negative": 4}}
    if kind == "update_known_limits":
        signal_counts = {}
        suggestions = [
            PackImprovementSuggestion(
                suggestion_id="suggest-known-limits",
                kind="update_known_limits",
                priority="medium",
                confidence=0.7,
                summary="known limits update",
                reason="adoption feedback",
                next_commands=["cambrian pack proof auth-bug-core"],
                evidence_refs=["retro-1"],
                warnings=[],
            )
        ]
    elif kind == "improve_validation_support":
        signal_counts = {"validation_quality": {"negative": 3}}
    _summary(root, signal_counts=signal_counts, suggestions=suggestions)
    queue = PackImprovementQueueBuilder().build(root, "auth-bug-core")
    save_pack_improvement_queue(root, queue)
    item = next(candidate for candidate in queue.items if candidate.kind == kind)
    record_pack_improvement_decision(root, item.item_id, "accepted", "plan for vNext")
    return item.item_id


def _install_seed(root: Path) -> None:
    PackInstaller().install(root, SEED_MANIFEST)


def test_derivative_plan_from_accepted_improvements(tmp_path: Path) -> None:
    _accepted_item(tmp_path, "strengthen_context_hints")

    plan = PackDerivativePlanner().build(tmp_path, "auth-bug-core")

    assert plan.safe_to_create_draft is True
    assert "template_evolution_required" in {change.kind for change in plan.changes}
    assert plan.unresolved_change_count >= 1
    assert plan.suggested_target_pack_id == "auth-bug-core-v2"


def test_no_accepted_improvements_warns(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})
    queue = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")
    save_pack_improvement_queue(tmp_path, queue)

    plan = PackDerivativePlanner().build(tmp_path, "auth-bug-core")

    assert plan.safe_to_create_draft is False
    assert plan.changes == []
    assert any("accepted improvement" in warning for warning in plan.warnings)


def test_version_bump_patch_for_metadata_only(tmp_path: Path) -> None:
    _accepted_item(tmp_path, "update_known_limits")

    plan = PackDerivativePlanner().build(tmp_path, "auth-bug-core")

    assert {change.kind for change in plan.changes} == {"known_limits_update"}
    assert plan.suggested_version_bump == "patch"
    assert plan.suggested_version == "0.1.1"


def test_version_bump_minor_for_template_or_validation(tmp_path: Path) -> None:
    _accepted_item(tmp_path, "improve_validation_support")

    plan = PackDerivativePlanner().build(tmp_path, "auth-bug-core")

    assert {"template_evolution_required", "benchmark_case_required"} <= {change.kind for change in plan.changes}
    assert plan.suggested_version_bump == "minor"
    assert plan.suggested_version == "0.2.0"


def test_derivative_create_creates_draft_with_metadata(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    _accepted_item(tmp_path, "strengthen_context_hints")
    plan = PackDerivativePlanner().build(tmp_path, "auth-bug-core")
    plan_ref = save_pack_derivative_plan(tmp_path, plan)

    workspace = PackDerivativeCreator().create(tmp_path, tmp_path / plan_ref, "auth-bug-core-v2")
    saved_ref = save_pack_derivative_workspace(tmp_path, workspace)
    draft = load_pack_draft(tmp_path / workspace.draft_ref)

    assert workspace.status == "created"
    assert saved_ref.endswith(".yaml")
    assert draft.pack_id == "auth-bug-core-v2"
    assert draft.derivative["source_pack_ref"] == "auth-bug-core"
    assert draft.derivative["unresolved_changes"]
    assert any("unresolved" in warning.lower() for warning in draft.warnings)


def test_release_warns_on_unresolved_derivative_changes(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    _accepted_item(tmp_path, "strengthen_context_hints")
    plan = PackDerivativePlanner().build(tmp_path, "auth-bug-core")
    plan_ref = save_pack_derivative_plan(tmp_path, plan)
    workspace = PackDerivativeCreator().create(tmp_path, tmp_path / plan_ref, "auth-bug-core-v2")

    manifest_path = tmp_path / "packs" / "generated" / "auth-bug-core-v2.cambrian-pack.yaml"
    build = PackBuilder().build(tmp_path, tmp_path / workspace.draft_ref, out_path=manifest_path)
    report = PackReleaseChecker().check(tmp_path, str(manifest_path))

    assert build.status == "built"
    assert any(check.check_id == "derivative_unresolved_changes" and check.status == "warn" for check in report.checks)
    assert report.maturity != "recommended"


def test_derivative_show_and_compact(tmp_path: Path) -> None:
    _accepted_item(tmp_path, "strengthen_context_hints")
    plan = PackDerivativePlanner().build(tmp_path, "auth-bug-core")
    save_pack_derivative_plan(tmp_path, plan)

    show = _cli(tmp_path, "pack", "derivative-show", "latest")
    compact = render_pack_derivative_compact(latest_pack_derivative_plan(tmp_path, "auth-bug-core"))

    assert show.returncode == 0, show.stderr
    assert "Pack Derivative Plan" in show.stdout
    assert "Derivative plan:" in compact


def test_source_immutability_for_plan_create_show(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'unchanged'\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    _accepted_item(tmp_path, "strengthen_context_hints")

    plan_result = _cli(tmp_path, "pack", "derivative-plan", "auth-bug-core")
    create_result = _cli(tmp_path, "pack", "derivative-create", "latest", "--as", "auth-bug-core-v2")
    show_result = _cli(tmp_path, "pack", "derivative-show", "latest")

    assert plan_result.returncode == 0, plan_result.stderr
    assert create_result.returncode == 0, create_result.stderr
    assert show_result.returncode == 0, show_result.stderr
    assert source.read_text(encoding="utf-8") == before
    assert default_pack_derivative_plans_dir(tmp_path).exists()


def test_backward_compatible_draft_without_derivative(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    draft = PackDraftBuilder().create(
        tmp_path,
        "plain-pack",
        "lane",
        {
            "workers": ["bug-fix-agent"],
            "teams": ["auth-bug-team"],
            "templates": ["auth-bug-template"],
            "benchmarks": ["auth-bug-workset"],
            "lane": "python-pytest-auth-bug-core",
        },
        version="0.1.0",
    )
    draft_ref = save_pack_draft(tmp_path, draft)
    payload = yaml.safe_load((tmp_path / draft_ref).read_text(encoding="utf-8"))
    payload.pop("derivative", None)
    (tmp_path / draft_ref).write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    loaded = load_pack_draft(tmp_path / draft_ref)

    assert loaded.derivative == {}
    assert accepted_improvement_count(tmp_path, "auth-bug-core") == 0


def test_improvement_decision_updates_per_pack_queue(tmp_path: Path) -> None:
    _summary(tmp_path, signal_counts={"context_fit": {"negative": 4}})
    queue_a = PackImprovementQueueBuilder().build(tmp_path, "auth-bug-core")
    save_pack_improvement_queue(tmp_path, queue_a)
    item_id = next(item.item_id for item in queue_a.items if item.kind == "strengthen_context_hints")
    _summary(tmp_path, signal_counts={"bridge_quality": {"negative": 3}})
    queue_b = PackImprovementQueueBuilder().build(tmp_path, "other-pack")
    save_pack_improvement_queue(tmp_path, queue_b)

    record_pack_improvement_decision(tmp_path, item_id, "dismissed", "stale warning should clear")
    items = PackImprovementStore().list_items(default_pack_improvement_items_dir(tmp_path), "auth-bug-core")
    latest = latest_pack_improvement_queue(tmp_path, "auth-bug-core")

    assert next(item for item in items if item.item_id == item_id).status == "dismissed"
    assert next(item for item in latest.items if item.item_id == item_id).status == "dismissed"
