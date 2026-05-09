from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_install import (
    InstalledPackStore,
    PackInstaller,
    PackManifestLoader,
    build_install_doctor_report,
    default_installed_packs_path,
)


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_load_valid_auth_bug_core_manifest() -> None:
    manifest = PackManifestLoader().load(SEED_MANIFEST)

    assert manifest.pack_id == "auth-bug-core"
    assert manifest.pack_kind == "lane"
    assert len(manifest.workers) == 3
    assert manifest.lane and manifest.lane["lane_id"] == "python-pytest-auth-bug-core"


def test_dry_run_plan_does_not_write_library_artifacts(tmp_path: Path) -> None:
    plan = PackInstaller().install(tmp_path, SEED_MANIFEST, dry_run=True)

    assert plan.safe_to_install is True
    assert "install worker bug-fix-agent" in plan.actions
    assert not (tmp_path / ".cambrian").exists()


def test_install_lane_pack_creates_library_and_provenance(tmp_path: Path) -> None:
    plan = PackInstaller().install(tmp_path, SEED_MANIFEST)

    assert plan.safe_to_install is True
    install_index = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")
    assert len(install_index["packs"]) == 1
    assert install_index["packs"][0]["pack_id"] == "auth-bug-core"
    manifest_ref = install_index["packs"][0]["manifest_ref"]
    assert (tmp_path / manifest_ref).exists()

    agents = _read_yaml(tmp_path / ".cambrian" / "agents" / "registry.yaml")
    teams = _read_yaml(tmp_path / ".cambrian" / "agents" / "teams.yaml")
    templates = _read_yaml(tmp_path / ".cambrian" / "templates" / "templates.yaml")
    lane = _read_yaml(tmp_path / ".cambrian" / "lane" / "playbook.yaml")

    assert {item["agent_id"] for item in agents["agents"]} >= {
        "bug-fix-agent",
        "regression-test-agent",
        "review-agent",
    }
    assert teams["active_team_id"] is None
    assert teams["teams"][0]["name"] == "auth-bug-team"
    assert templates["active_template_name"] is None
    assert templates["templates"][0]["name"] == "auth-bug-template"
    assert templates["templates"][0]["context_defaults"]["preferred_context_paths"] == ["src/auth.py"]
    assert (tmp_path / ".cambrian" / "benchmarks" / "worksets" / "workset_auth-bug-workset.yaml").exists()
    assert lane["default_template_name"] is None
    assert lane["installed_lane_packs"][0]["pack_id"] == "auth-bug-core"


def test_install_does_not_auto_apply_or_bootstrap(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)

    assert not (tmp_path / ".cambrian" / "templates" / "current_template.yaml").exists()
    assert not (tmp_path / ".cambrian" / "templates" / "bootstrap_record.yaml").exists()
    assert not (tmp_path / ".cambrian" / "sessions").exists()


def test_reinstall_same_pack_is_idempotent(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)
    second = PackInstaller().install(tmp_path, SEED_MANIFEST)

    assert second.safe_to_install is True
    index = InstalledPackStore().load(default_installed_packs_path(tmp_path))
    assert len(index.packs) == 1
    assert index.packs[0].pack_id == "auth-bug-core"


def test_conflict_blocks_without_partial_mutation(tmp_path: Path) -> None:
    templates_path = tmp_path / ".cambrian" / "templates" / "templates.yaml"
    templates_path.parent.mkdir(parents=True)
    templates_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "updated_at": "before",
                "active_template_name": None,
                "templates": [
                    {
                        "schema_version": "1.0.0",
                        "template_id": "auth-bug-template",
                        "name": "auth-bug-template",
                        "created_at": "before",
                        "updated_at": None,
                        "description": "conflicting template",
                        "source_project_name": None,
                        "source_harness_id": None,
                        "template_kind": "manual",
                        "tags": [],
                        "project_defaults": {"stack": ["ruby"]},
                        "safety_defaults": {},
                        "agent_defaults": {},
                        "team_defaults": {},
                        "policy_defaults": {},
                        "context_defaults": {},
                        "fit_hints": [],
                        "warnings": [],
                        "errors": [],
                        "source_kind": "local",
                        "source_origin": {},
                    }
                ],
                "warnings": [],
                "errors": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = PackInstaller().install(tmp_path, SEED_MANIFEST)

    assert plan.safe_to_install is False
    assert any("template name/id already exists" in item for item in plan.conflicts)
    assert not (tmp_path / ".cambrian" / "install" / "installed_packs.yaml").exists()
    assert not (tmp_path / ".cambrian" / "agents" / "registry.yaml").exists()


def test_install_list_show_and_doctor_cli(tmp_path: Path) -> None:
    install = _cli(tmp_path, "install", "manifest", str(SEED_MANIFEST))
    assert install.returncode == 0, install.stderr
    assert "Pack install completed." in install.stdout

    listed = _cli(tmp_path, "install", "list")
    assert listed.returncode == 0, listed.stderr
    assert "auth-bug-core" in listed.stdout

    shown = _cli(tmp_path, "install", "show", "auth-bug-core")
    assert shown.returncode == 0, shown.stderr
    assert "Installed Pack" in shown.stdout
    assert "auth-bug-template" in shown.stdout

    doctor = _cli(tmp_path, "install", "doctor")
    assert doctor.returncode == 0, doctor.stderr
    assert "Install Doctor" in doctor.stdout
    assert "worker installed" in doctor.stdout


def test_install_doctor_reports_missing_references(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)
    (tmp_path / ".cambrian" / "templates" / "templates.yaml").unlink()

    report = build_install_doctor_report(tmp_path)

    assert report["errors"]
    assert any("template installed failed" in item for item in report["errors"])


def test_install_surfaces_do_not_mutate_project_source_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")

    assert _cli(tmp_path, "install", "manifest", str(SEED_MANIFEST)).returncode == 0
    assert _cli(tmp_path, "install", "list").returncode == 0
    assert _cli(tmp_path, "install", "show", "auth-bug-core").returncode == 0
    assert _cli(tmp_path, "install", "doctor").returncode == 0

    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
