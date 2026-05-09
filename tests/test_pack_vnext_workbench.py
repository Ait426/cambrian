from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from engine.project_pack_authoring import PackBuilder
from engine.project_pack_derivatives import (
    PackDerivativeChange,
    PackDerivativeCreator,
    PackDerivativePlan,
    save_pack_derivative_plan,
    save_pack_derivative_workspace,
)
from engine.project_pack_install import SCHEMA_VERSION, PackInstaller
from engine.project_pack_release import PackReleaseChecker
from engine.project_pack_vnext_workbench import (
    PackVNextWorkbenchBuilder,
    PackWorkOrderStore,
    default_pack_vnext_workbenches_dir,
    default_pack_vnext_workorders_dir,
    latest_pack_vnext_workbench,
    record_pack_workorder_decision,
    render_pack_vnext_compact,
    render_status_pack_vnext,
    save_pack_vnext_workbench,
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


def _install_seed(root: Path) -> None:
    PackInstaller().install(root, SEED_MANIFEST)


def _change(kind: str, status: str = "unresolved") -> PackDerivativeChange:
    return PackDerivativeChange(
        change_id=f"change-{kind}",
        source_improvement_id=f"item-{kind}",
        kind=kind,
        status=status,
        title=f"{kind} title",
        summary=f"{kind} summary",
        reason=f"{kind} reason",
        affected_metrics=["validated_proposal_rate", "human_intervention_rate"],
        required_commands=[],
        evidence_refs=[f"evidence-{kind}"],
        warnings=[],
        errors=[],
    )


def _plan(root: Path, changes: list[PackDerivativeChange]) -> str:
    ready = len([item for item in changes if item.status == "ready"])
    unresolved = len([item for item in changes if item.status == "unresolved"])
    plan = PackDerivativePlan(
        schema_version=SCHEMA_VERSION,
        plan_id="derivative-plan-auth-bug-core-test",
        generated_at="2026-05-04T00:00:00+00:00",
        source_pack_ref="auth-bug-core",
        source_pack_id="auth-bug-core",
        source_pack_name="Auth Bug Core",
        source_version="0.1.0",
        namespace=None,
        suggested_target_pack_id="auth-bug-core-v2",
        suggested_version="0.2.0",
        suggested_version_bump="minor",
        accepted_improvement_refs=["item-accepted"],
        changes=changes,
        ready_change_count=ready,
        unresolved_change_count=unresolved,
        blocked_change_count=0,
        safe_to_create_draft=True,
        summary=[],
        next_actions=[],
        source_refs={},
        warnings=[],
        errors=[],
    )
    return save_pack_derivative_plan(root, plan)


def _workbench(root: Path, plan_ref: str):
    workbench = PackVNextWorkbenchBuilder().build(root, root / plan_ref)
    save_pack_vnext_workbench(root, workbench)
    return workbench


def test_workbench_from_derivative_plan(tmp_path: Path) -> None:
    plan_ref = _plan(
        tmp_path,
        [
            _change("template_evolution_required"),
            _change("benchmark_case_required"),
            _change("known_limits_update", status="ready"),
        ],
    )

    workbench = _workbench(tmp_path, plan_ref)

    kinds = {order.kind for order in workbench.workorders}
    assert {"template_evolution", "benchmark_case", "known_limits_update"} <= kinds
    assert workbench.open_required_count == 3
    assert default_pack_vnext_workbenches_dir(tmp_path).exists()
    assert default_pack_vnext_workorders_dir(tmp_path).exists()


def test_template_evolution_workorder(tmp_path: Path) -> None:
    plan_ref = _plan(tmp_path, [_change("template_evolution_required")])

    workbench = _workbench(tmp_path, plan_ref)
    order = next(item for item in workbench.workorders if item.kind == "template_evolution")

    assert order.required is True
    assert any("template evolve" in command for command in order.suggested_commands)


def test_benchmark_case_workorder(tmp_path: Path) -> None:
    plan_ref = _plan(tmp_path, [_change("benchmark_case_required")])

    workbench = _workbench(tmp_path, plan_ref)
    order = next(item for item in workbench.workorders if item.kind == "benchmark_case")

    assert order.required is True
    assert any("benchmark case-add" in command for command in order.suggested_commands)


def test_metadata_only_workorder_optional(tmp_path: Path) -> None:
    plan_ref = _plan(tmp_path, [_change("metadata_only", status="ready")])

    workbench = _workbench(tmp_path, plan_ref)
    order = next(item for item in workbench.workorders if item.kind == "metadata_update")

    assert order.required is False
    assert workbench.open_required_count == 0


def test_workorder_done_requires_note_or_evidence(tmp_path: Path) -> None:
    plan_ref = _plan(tmp_path, [_change("template_evolution_required")])
    workbench = _workbench(tmp_path, plan_ref)
    order = next(item for item in workbench.workorders if item.required)

    try:
        record_pack_workorder_decision(tmp_path, order.workorder_id, "done")
    except ValueError as exc:
        assert "requires" in str(exc)
    else:
        raise AssertionError("workorder-done without evidence/note should fail")

    decision, updated, _ = record_pack_workorder_decision(tmp_path, order.workorder_id, "done", evidence_refs=[".cambrian/templates/evolution.yaml"])

    assert decision.status == "done"
    assert updated.status == "done"
    assert updated.completed_evidence_refs


def test_workorder_skip_required_keeps_release_not_ready(tmp_path: Path) -> None:
    plan_ref = _plan(tmp_path, [_change("template_evolution_required")])
    workbench = _workbench(tmp_path, plan_ref)
    order = next(item for item in workbench.workorders if item.required)

    record_pack_workorder_decision(tmp_path, order.workorder_id, "skipped", note="not for this version")
    latest = latest_pack_vnext_workbench(tmp_path, "auth-bug-core")

    assert latest is not None
    assert latest.skipped_required_count == 1
    assert latest.release_ready is False


def test_release_ready_when_all_required_done(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    plan_ref = _plan(tmp_path, [_change("known_limits_update", status="ready")])
    workspace = PackDerivativeCreator().create(tmp_path, tmp_path / plan_ref, "auth-bug-core-v2")
    save_pack_derivative_workspace(tmp_path, workspace)
    workbench = _workbench(tmp_path, plan_ref)

    for order in workbench.workorders:
        if order.required:
            record_pack_workorder_decision(tmp_path, order.workorder_id, "done", note="completed manually")
    latest = latest_pack_vnext_workbench(tmp_path, "auth-bug-core")

    assert latest is not None
    assert latest.release_ready is True


def test_release_check_sees_unresolved_workorders(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    plan_ref = _plan(tmp_path, [_change("template_evolution_required")])
    workspace = PackDerivativeCreator().create(tmp_path, tmp_path / plan_ref, "auth-bug-core-v2")
    save_pack_derivative_workspace(tmp_path, workspace)
    _workbench(tmp_path, plan_ref)

    manifest_path = tmp_path / "packs" / "generated" / "auth-bug-core-v2.cambrian-pack.yaml"
    PackBuilder().build(tmp_path, tmp_path / workspace.draft_ref, out_path=manifest_path)
    report = PackReleaseChecker().check(tmp_path, str(manifest_path))

    assert any(check.check_id == "vnext_required_workorders" and check.status == "warn" for check in report.checks)
    assert report.maturity != "recommended"


def test_pack_show_status_render_integration(tmp_path: Path) -> None:
    plan_ref = _plan(tmp_path, [_change("template_evolution_required")])
    workbench = _workbench(tmp_path, plan_ref)

    assert "VNext workbench:" in render_pack_vnext_compact(workbench)
    assert "Pack vNext:" in render_status_pack_vnext(workbench)


def test_source_immutability_for_workbench_show_done_skip(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'unchanged'\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    _plan(tmp_path, [_change("template_evolution_required")])

    workbench_result = _cli(tmp_path, "pack", "derivative-workbench", "latest")
    show_result = _cli(tmp_path, "pack", "workorder-show", "latest")
    done_result = _cli(tmp_path, "pack", "workorder-done", "latest", "--note", "manual evidence recorded")

    assert workbench_result.returncode == 0, workbench_result.stderr
    assert show_result.returncode == 0, show_result.stderr
    assert done_result.returncode == 0, done_result.stderr
    assert source.read_text(encoding="utf-8") == before
    assert default_pack_vnext_workorders_dir(tmp_path).exists()
