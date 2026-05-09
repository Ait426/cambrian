from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_activation import PackActivator, current_active_pack
from engine.project_pack_derivatives import (
    PackDerivativeChange,
    PackDerivativeCreator,
    PackDerivativePlan,
    save_pack_derivative_plan,
    save_pack_derivative_workspace,
)
from engine.project_pack_install import SCHEMA_VERSION, InstalledPackStore, PackInstaller, default_installed_packs_path
from engine.project_pack_release_candidate import (
    PackLocalReleaser,
    PackReleaseCandidateBuilder,
    save_pack_local_release,
    save_pack_rc,
)
from engine.project_pack_rollout import (
    PackRolloutApplier,
    PackRolloutPlanner,
    PackRolloutStore,
    latest_pack_rollout,
    render_pack_rollout_plan,
    render_status_pack_rollout,
    resolve_pack_rollout_path,
    save_pack_rollout_plan,
)
from engine.project_pack_vnext_workbench import (
    PackVNextWorkbenchBuilder,
    record_pack_workorder_decision,
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


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _empty_catalog(root: Path) -> None:
    _write_yaml(
        root / "packs" / "catalog.yaml",
        {
            "schema_version": "1.0",
            "updated_at": None,
            "source_kind": "local_seed",
            "entries": [],
            "warnings": [],
            "errors": [],
        },
    )


def _install_seed(root: Path, *, activate: bool = True) -> None:
    PackInstaller().install(root, SEED_MANIFEST)
    if activate:
        PackActivator().activate(root, "auth-bug-core")


def _change(kind: str, status: str = "ready") -> PackDerivativeChange:
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


def _plan(root: Path) -> str:
    changes = [_change("known_limits_update", status="ready")]
    plan = PackDerivativePlan(
        schema_version=SCHEMA_VERSION,
        plan_id="derivative-plan-auth-bug-core-rollout-test",
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
        ready_change_count=1,
        unresolved_change_count=0,
        blocked_change_count=0,
        safe_to_create_draft=True,
        summary=[],
        next_actions=[],
        source_refs={},
        warnings=[],
        errors=[],
    )
    return save_pack_derivative_plan(root, plan)


def _release_v2(root: Path, *, activate_old: bool = True) -> str:
    _install_seed(root, activate=activate_old)
    plan_ref = _plan(root)
    workspace = PackDerivativeCreator().create(root, root / plan_ref, "auth-bug-core-v2")
    save_pack_derivative_workspace(root, workspace)
    workbench = PackVNextWorkbenchBuilder().build(root, root / plan_ref)
    save_pack_vnext_workbench(root, workbench)
    for order in workbench.workorders:
        if order.required:
            record_pack_workorder_decision(root, order.workorder_id, "done", note=f"{order.kind} completed manually")
    rc = PackReleaseCandidateBuilder().build(root, workspace.draft_ref or "")
    assert rc.status == "release_ready"
    rc_ref = save_pack_rc(root, rc)
    _empty_catalog(root)
    release = PackLocalReleaser().release(root, rc_ref, confirm=True)
    assert release.status == "released"
    return save_pack_local_release(root, release)


def _installed_ids(root: Path) -> set[str]:
    index = InstalledPackStore().load(default_installed_packs_path(root))
    return {record.pack_id for record in index.packs if record.status != "uninstalled"}


def test_rollout_detects_previous_active_pack(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)

    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")

    assert plan.new_pack_id == "auth-bug-core-v2"
    assert plan.previous_pack_id == "auth-bug-core"
    assert plan.current_active_pack_id == "auth-bug-core"
    assert plan.previous_pack_active is True


def test_rollout_recommendation_install_and_activate(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)

    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")

    assert plan.rollout_recommendation == "install_and_activate"
    assert "cambrian pack rollout-apply" in "\n".join(plan.next_actions)


def test_rollout_install_only_without_active_previous(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=False)

    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")

    assert plan.rollout_recommendation in {"install_only", "wait"}
    assert plan.current_active_pack_id is None


def test_rollout_blocked_when_new_pack_missing(tmp_path: Path) -> None:
    plan = PackRolloutPlanner().build(tmp_path, "missing-pack")

    assert plan.status == "blocked"
    assert plan.rollout_recommendation == "blocked"
    assert plan.errors


def test_rollout_show_cli_loads_saved_plan(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)
    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")
    save_pack_rollout_plan(tmp_path, plan)

    result = _cli(tmp_path, "pack", "rollout-show", "latest")

    assert result.returncode == 0, result.stderr
    assert "Pack Rollout Plan" in result.stdout
    assert "auth-bug-core-v2" in result.stdout


def test_rollout_apply_preview_only(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)
    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")
    plan_ref = save_pack_rollout_plan(tmp_path, plan)
    active_before = current_active_pack(tmp_path)

    record = PackRolloutApplier().apply(tmp_path, plan_ref, confirm=False, install=True, activate=True)

    assert record.status == "preview"
    assert "auth-bug-core-v2" not in _installed_ids(tmp_path)
    assert current_active_pack(tmp_path).pack_id == active_before.pack_id


def test_rollout_apply_confirm_install(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)
    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")
    plan_ref = save_pack_rollout_plan(tmp_path, plan)

    record = PackRolloutApplier().apply(tmp_path, plan_ref, confirm=True, install=True)

    assert record.status == "applied"
    assert "install_new_pack" in record.applied_steps
    assert "auth-bug-core-v2" in _installed_ids(tmp_path)
    assert current_active_pack(tmp_path).pack_id == "auth-bug-core"


def test_rollout_apply_confirm_activate_preserves_old_pack(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)
    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")
    plan_ref = save_pack_rollout_plan(tmp_path, plan)

    record = PackRolloutApplier().apply(tmp_path, plan_ref, confirm=True, install=True, activate=True)

    assert record.status == "applied"
    assert current_active_pack(tmp_path).pack_id == "auth-bug-core-v2"
    assert {"auth-bug-core", "auth-bug-core-v2"} <= _installed_ids(tmp_path)


def test_rollback_hint_present(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)

    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")

    assert plan.rollback_hint == "cambrian pack activate auth-bug-core"
    assert "Rollback:" in render_pack_rollout_plan(plan)


def test_pack_show_status_render_integration(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)
    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")
    save_pack_rollout_plan(tmp_path, plan)

    latest = latest_pack_rollout(tmp_path, "auth-bug-core")

    assert latest is not None
    assert "Pack rollout:" in render_status_pack_rollout(latest)


def test_rollout_does_not_mutate_project_source(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    _release_v2(tmp_path, activate_old=True)
    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")
    plan_ref = save_pack_rollout_plan(tmp_path, plan)

    PackRolloutApplier().apply(tmp_path, plan_ref, confirm=True, install=True, activate=True)

    assert source.read_text(encoding="utf-8") == before
    assert resolve_pack_rollout_path(tmp_path, "latest").exists()


def test_rollout_cli_apply_confirm_install_and_activate(tmp_path: Path) -> None:
    _release_v2(tmp_path, activate_old=True)
    plan = PackRolloutPlanner().build(tmp_path, "auth-bug-core-v2")
    save_pack_rollout_plan(tmp_path, plan)

    result = _cli(tmp_path, "pack", "rollout-apply", "latest", "--confirm", "--install", "--activate")

    assert result.returncode == 0, result.stderr
    assert "Pack Rollout Applied" in result.stdout
    assert current_active_pack(tmp_path).pack_id == "auth-bug-core-v2"
