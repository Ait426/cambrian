from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from engine.project_pack_install import (
    InstalledPackStore,
    PackInstaller,
    default_installed_packs_path,
)
from engine.project_pack_lifecycle import PackDiffBuilder


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _newer_manifest(tmp_path: Path) -> Path:
    payload = deepcopy(_read_yaml(SEED_MANIFEST))
    payload["version"] = "0.2.0"
    payload["workers"].append(
        {
            "id": "auth-edge-review-agent",
            "name": "Auth Edge Review Agent",
            "capabilities": ["auth edge review", "risk detection"],
        }
    )
    payload["templates"][0]["description"] = "Updated auth bug template"
    path = tmp_path / "incoming" / "auth-bug-core-v0.2.cambrian-pack.yaml"
    _write_yaml(path, payload)
    return path


def _install_seed(tmp_path: Path) -> None:
    plan = PackInstaller().install(tmp_path, SEED_MANIFEST)
    assert plan.safe_to_install is True


def _template_names(tmp_path: Path) -> set[str]:
    payload = _read_yaml(tmp_path / ".cambrian" / "templates" / "templates.yaml")
    return {str(item.get("name")) for item in payload.get("templates", [])}


def _agent_ids(tmp_path: Path) -> set[str]:
    payload = _read_yaml(tmp_path / ".cambrian" / "agents" / "registry.yaml")
    return {str(item.get("agent_id")) for item in payload.get("agents", [])}


def test_diff_installed_vs_incoming_manifest(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    incoming = _newer_manifest(tmp_path)

    report = PackDiffBuilder().build(tmp_path, "auth-bug-core", incoming)

    assert report.safe_to_update is True
    assert report.current_version == "0.1.0"
    assert report.incoming_version == "0.2.0"
    assert any(entry.artifact_name == "auth-edge-review-agent" and entry.change_kind == "added" for entry in report.entries)
    assert any(entry.artifact_name == "auth-bug-template" and entry.change_kind == "changed" for entry in report.entries)


def test_update_preview_only_by_default(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    incoming = _newer_manifest(tmp_path)

    result = _cli(tmp_path, "install", "update", "auth-bug-core", "--manifest", str(incoming))

    assert result.returncode == 0, result.stderr
    assert "Update preview only" in result.stdout
    assert "auth-edge-review-agent" not in _agent_ids(tmp_path)
    record = InstalledPackStore().load(default_installed_packs_path(tmp_path)).packs[0]
    assert record.status == "installed"


def test_update_confirm_applies_safe_changes(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    incoming = _newer_manifest(tmp_path)

    result = _cli(tmp_path, "install", "update", "auth-bug-core", "--manifest", str(incoming), "--confirm")

    assert result.returncode == 0, result.stderr
    assert "Pack Update" in result.stdout
    assert "auth-edge-review-agent" in _agent_ids(tmp_path)
    index = InstalledPackStore().load(default_installed_packs_path(tmp_path))
    record = index.packs[0]
    assert record.status == "updated"
    assert record.version == "0.2.0"
    assert record.update_history
    assert (tmp_path / ".cambrian" / "install" / "updates").exists()


def test_update_protects_local_derivative(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    incoming = _newer_manifest(tmp_path)
    templates_path = tmp_path / ".cambrian" / "templates" / "templates.yaml"
    payload = _read_yaml(templates_path)
    derivative = deepcopy(payload["templates"][0])
    derivative["name"] = "auth-bug-template-local"
    derivative["template_id"] = "auth-bug-template-local"
    derivative["source_kind"] = "local_derivative"
    derivative["source_origin"] = {"source_pack_id": "auth-bug-core"}
    payload["templates"].append(derivative)
    _write_yaml(templates_path, payload)

    report = PackDiffBuilder().build(tmp_path, "auth-bug-core", incoming)

    assert any(entry.artifact_name == "auth-bug-template-local" and entry.change_kind == "protected" for entry in report.entries)
    assert report.safe_to_update is True
    assert "auth-bug-template-local" in _template_names(tmp_path)


def test_conflict_blocks_update(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    incoming = _newer_manifest(tmp_path)
    templates_path = tmp_path / ".cambrian" / "templates" / "templates.yaml"
    payload = _read_yaml(templates_path)
    payload["templates"][0]["source_kind"] = "local"
    payload["templates"][0].pop("source_pack_id", None)
    payload["templates"][0]["source_origin"] = {}
    _write_yaml(templates_path, payload)

    result = _cli(tmp_path, "install", "update", "auth-bug-core", "--manifest", str(incoming), "--confirm")

    assert result.returncode != 0
    assert "blocked" in result.stdout
    assert "template is not owned by pack" in result.stdout
    assert "auth-edge-review-agent" not in _agent_ids(tmp_path)


def test_uninstall_preview_does_not_mutate(tmp_path: Path) -> None:
    _install_seed(tmp_path)

    result = _cli(tmp_path, "uninstall", "pack", "auth-bug-core")

    assert result.returncode == 0, result.stderr
    assert "Pack Uninstall Plan" in result.stdout
    assert "Uninstall preview only" in result.stdout
    assert "auth-bug-template" in _template_names(tmp_path)
    record = InstalledPackStore().load(default_installed_packs_path(tmp_path)).packs[0]
    assert record.status == "installed"


def test_uninstall_confirm_removes_safe_pack_owned_entries(tmp_path: Path) -> None:
    _install_seed(tmp_path)

    result = _cli(tmp_path, "uninstall", "pack", "auth-bug-core", "--confirm")

    assert result.returncode == 0, result.stderr
    assert "Pack Uninstall" in result.stdout
    assert "auth-bug-template" not in _template_names(tmp_path)
    assert "bug-fix-agent" not in _agent_ids(tmp_path)
    record = InstalledPackStore().load(default_installed_packs_path(tmp_path)).packs[0]
    assert record.status == "uninstalled"
    assert record.uninstall_ref
    assert (tmp_path / ".cambrian" / "install" / "uninstalls").exists()


def test_uninstall_blocks_current_lane_default_without_force(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    lane_path = tmp_path / ".cambrian" / "lane" / "playbook.yaml"
    lane = _read_yaml(lane_path)
    lane["default_template_name"] = "auth-bug-template"
    _write_yaml(lane_path, lane)

    result = _cli(tmp_path, "uninstall", "pack", "auth-bug-core", "--confirm")

    assert result.returncode != 0
    assert "blocking references" in result.stdout or "blocking reference" in result.stdout
    assert "auth-bug-template" in _template_names(tmp_path)
    record = InstalledPackStore().load(default_installed_packs_path(tmp_path)).packs[0]
    assert record.status == "installed"


def test_uninstall_force_preserves_historical_artifacts(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    proof = tmp_path / ".cambrian" / "benchmarks" / "proof" / "proof_auth-bug-workset.yaml"
    session = tmp_path / ".cambrian" / "sessions" / "session.yaml"
    _write_yaml(proof, {"proof": "kept"})
    _write_yaml(session, {"session": "kept"})

    result = _cli(tmp_path, "uninstall", "pack", "auth-bug-core", "--confirm", "--force")

    assert result.returncode == 0, result.stderr
    assert proof.exists()
    assert session.exists()
    record = InstalledPackStore().load(default_installed_packs_path(tmp_path)).packs[0]
    assert record.status == "uninstalled"


def test_installed_packs_backward_compatibility_defaults_status(tmp_path: Path) -> None:
    path = tmp_path / ".cambrian" / "install" / "installed_packs.yaml"
    _write_yaml(
        path,
        {
            "schema_version": "1.0.0",
            "updated_at": "old",
            "packs": [
                {
                    "pack_id": "legacy-pack",
                    "pack_name": "Legacy Pack",
                    "pack_kind": "lane",
                    "version": "0.1.0",
                    "installed_at": "old",
                    "source_kind": "local",
                    "source_ref": "legacy",
                    "manifest_ref": ".cambrian/install/manifests/legacy.yaml",
                    "installed_artifacts": {},
                }
            ],
        },
    )

    record = InstalledPackStore().load(path).packs[0]

    assert record.status == "installed"
    assert record.latest_manifest_ref == ".cambrian/install/manifests/legacy.yaml"
    assert record.manifest_history == [".cambrian/install/manifests/legacy.yaml"]


def test_lifecycle_commands_do_not_mutate_project_source_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")
    _install_seed(tmp_path)
    incoming = _newer_manifest(tmp_path)

    assert _cli(tmp_path, "install", "diff", "auth-bug-core", "--manifest", str(incoming)).returncode == 0
    assert _cli(tmp_path, "install", "update", "auth-bug-core", "--manifest", str(incoming)).returncode == 0
    assert _cli(tmp_path, "install", "update", "auth-bug-core", "--manifest", str(incoming), "--confirm").returncode == 0
    assert _cli(tmp_path, "uninstall", "pack", "auth-bug-core").returncode == 0
    assert _cli(tmp_path, "uninstall", "pack", "auth-bug-core", "--confirm").returncode == 0

    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
