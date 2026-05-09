from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_derivatives import (
    PackDerivativeChange,
    PackDerivativeCreator,
    PackDerivativePlan,
    save_pack_derivative_plan,
    save_pack_derivative_workspace,
)
from engine.project_pack_install import SCHEMA_VERSION, PackInstaller
from engine.project_pack_release import PackReleaseChecker
from engine.project_pack_release_candidate import (
    PackLocalReleaser,
    PackReleaseCandidateBuilder,
    PackReleaseCandidateStore,
    latest_pack_local_release,
    render_pack_rc_compact,
    render_status_pack_rc,
    save_pack_local_release,
    save_pack_rc,
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


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


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
    plan = PackDerivativePlan(
        schema_version=SCHEMA_VERSION,
        plan_id="derivative-plan-auth-bug-core-rc-test",
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
        ready_change_count=len([item for item in changes if item.status == "ready"]),
        unresolved_change_count=len([item for item in changes if item.status == "unresolved"]),
        blocked_change_count=0,
        safe_to_create_draft=True,
        summary=[],
        next_actions=[],
        source_refs={},
        warnings=[],
        errors=[],
    )
    return save_pack_derivative_plan(root, plan)


def _workspace_and_workbench(root: Path, changes: list[PackDerivativeChange], *, done: bool) -> tuple[str, str]:
    _install_seed(root)
    plan_ref = _plan(root, changes)
    workspace = PackDerivativeCreator().create(root, root / plan_ref, "auth-bug-core-v2")
    workspace_ref = save_pack_derivative_workspace(root, workspace)
    workbench = PackVNextWorkbenchBuilder().build(root, root / plan_ref)
    save_pack_vnext_workbench(root, workbench)
    if done:
        for order in workbench.workorders:
            if order.required:
                record_pack_workorder_decision(root, order.workorder_id, "done", note=f"{order.kind} completed manually")
    return workspace_ref, workspace.draft_ref or ""


def _empty_catalog(root: Path) -> Path:
    catalog = root / "packs" / "catalog.yaml"
    _write_yaml(
        catalog,
        {
            "schema_version": "1.0",
            "updated_at": None,
            "source_kind": "local_seed",
            "entries": [],
            "warnings": [],
            "errors": [],
        },
    )
    return catalog


def _release_ready_rc(root: Path):
    _, draft_ref = _workspace_and_workbench(root, [_change("known_limits_update", status="ready")], done=True)
    rc = PackReleaseCandidateBuilder().build(root, draft_ref)
    assert rc.status == "release_ready"
    assert rc.safe_to_release_local is True
    return rc


def test_rc_blocks_unresolved_required_workorders(tmp_path: Path) -> None:
    _, draft_ref = _workspace_and_workbench(tmp_path, [_change("template_evolution_required")], done=False)

    rc = PackReleaseCandidateBuilder().build(tmp_path, draft_ref)

    assert rc.status == "blocked"
    assert rc.safe_to_release_local is False
    assert "required vNext workorders are unresolved" in rc.errors


def test_rc_allow_unresolved_creates_candidate(tmp_path: Path) -> None:
    _, draft_ref = _workspace_and_workbench(tmp_path, [_change("template_evolution_required")], done=False)

    rc = PackReleaseCandidateBuilder().build(tmp_path, draft_ref, allow_unresolved=True)

    assert rc.status == "candidate"
    assert rc.safe_to_release_local is False
    assert rc.manifest_ref
    assert any("unresolved required workorders allowed" in item for item in rc.warnings)


def test_rc_release_ready_when_workorders_done(tmp_path: Path) -> None:
    rc = _release_ready_rc(tmp_path)

    assert rc.manifest_ref
    assert rc.manifest_sha256
    assert rc.release_check_ref
    assert rc.workorder_summary["required_done"] == rc.workorder_summary["required_total"]


def test_rc_changelog_only_includes_completed_work(tmp_path: Path) -> None:
    _, draft_ref = _workspace_and_workbench(
        tmp_path,
        [_change("known_limits_update", status="ready"), _change("template_evolution_required")],
        done=False,
    )
    # 방금 만든 실제 workbench의 known_limits order만 완료하고 template order는 unresolved로 둔다.
    from engine.project_pack_vnext_workbench import latest_pack_vnext_workbench

    latest = latest_pack_vnext_workbench(tmp_path, "auth-bug-core")
    assert latest is not None
    known_order = next(order for order in latest.workorders if order.kind == "known_limits_update")
    record_pack_workorder_decision(tmp_path, known_order.workorder_id, "done", note="Known limits updated in draft metadata")

    rc = PackReleaseCandidateBuilder().build(tmp_path, draft_ref, allow_unresolved=True)

    assert any("known_limits_update title" in item for item in rc.changelog)
    assert not any("template_evolution_required title" in item for item in rc.changelog)
    assert rc.unresolved_workorder_refs


def test_rc_show_cli_loads_saved_candidate(tmp_path: Path) -> None:
    rc = _release_ready_rc(tmp_path)
    save_pack_rc(tmp_path, rc)

    result = _cli(tmp_path, "pack", "rc-show", "latest")

    assert result.returncode == 0, result.stderr
    assert "Pack Release Candidate" in result.stdout
    assert "auth-bug-core-v2" in result.stdout


def test_release_local_preview_does_not_mutate_catalog(tmp_path: Path) -> None:
    rc = _release_ready_rc(tmp_path)
    rc_ref = save_pack_rc(tmp_path, rc)
    catalog = _empty_catalog(tmp_path)
    before = catalog.read_text(encoding="utf-8")

    record = PackLocalReleaser().release(tmp_path, rc_ref, confirm=False)

    assert record.status == "preview"
    assert catalog.read_text(encoding="utf-8") == before


def test_release_local_confirm_publishes(tmp_path: Path) -> None:
    rc = _release_ready_rc(tmp_path)
    rc_ref = save_pack_rc(tmp_path, rc)
    catalog = _empty_catalog(tmp_path)

    record = PackLocalReleaser().release(tmp_path, rc_ref, confirm=True)
    saved_ref = save_pack_local_release(tmp_path, record)
    entries = _read_yaml(catalog)["entries"]

    assert record.status == "released"
    assert saved_ref.endswith(".yaml")
    assert entries[0]["pack_id"] == "auth-bug-core-v2"


def test_supersede_source_pack_is_recorded_without_uninstall(tmp_path: Path) -> None:
    rc = _release_ready_rc(tmp_path)
    rc_ref = save_pack_rc(tmp_path, rc)
    _empty_catalog(tmp_path)

    record = PackLocalReleaser().release(tmp_path, rc_ref, confirm=True)

    assert record.previous_pack_status == "superseded_recorded"
    assert SEED_MANIFEST.exists()


def test_status_and_show_render_release_candidate(tmp_path: Path) -> None:
    rc = _release_ready_rc(tmp_path)
    release = latest_pack_local_release(tmp_path, "auth-bug-core")

    assert "Pack RC:" in render_pack_rc_compact(rc, release)
    assert "ready for local release" in render_status_pack_rc(rc, release)


def test_release_check_accepts_rc_ref(tmp_path: Path) -> None:
    rc = _release_ready_rc(tmp_path)
    rc_ref = save_pack_rc(tmp_path, rc)

    report = PackReleaseChecker().check(tmp_path, rc_ref)

    assert report.pack_id == "auth-bug-core-v2"
    assert report.safe_to_publish is True


def test_source_immutability_for_rc_and_release_preview(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 'unchanged'\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    _, draft_ref = _workspace_and_workbench(tmp_path, [_change("known_limits_update", status="ready")], done=True)

    rc_result = _cli(tmp_path, "pack", "rc", draft_ref)
    release_result = _cli(tmp_path, "pack", "release-local", "latest")

    assert rc_result.returncode == 0, rc_result.stderr
    assert release_result.returncode == 0, release_result.stderr
    assert source.read_text(encoding="utf-8") == before
