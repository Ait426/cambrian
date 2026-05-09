from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_registry import PackRegistryResolver, PackRegistryStore, PackRegistrySyncer, default_registry_index_path


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"


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


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_registry_fixture(root: Path, *, digest: str | None = None, trust_level: str = "trusted") -> Path:
    registry = root / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    manifest = registry / "auth-bug-core.cambrian-pack.yaml"
    manifest.write_bytes(SEED_MANIFEST.read_bytes())
    actual_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    catalog = registry / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_kind": "web_static_catalog",
                "updated_at": "2026-05-04T00:00:00Z",
                "packs": [
                    {
                        "pack_id": "auth-bug-core",
                        "pack_name": "Auth Bug Core",
                        "pack_kind": "lane",
                        "version": "0.1.0",
                        "description": "Python + pytest + narrow auth/login bug fix lane pack",
                        "tags": ["auth", "login", "pytest", "bug_fix"],
                        "maturity": "candidate",
                        "proof_status": "local_proof_required",
                        "known_limits": ["not for broad refactors"],
                        "compatibility": {
                            "stacks": ["python"],
                            "test_frameworks": ["pytest"],
                            "lane_ids": ["python-pytest-auth-bug-core"],
                        },
                        "manifest_path": "auth-bug-core.cambrian-pack.yaml",
                        "manifest_sha256": digest or actual_digest,
                        "trust_level": trust_level,
                    }
                ],
                "warnings": [],
                "errors": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return catalog


def _write_web_asset_registry_fixture(root: Path) -> Path:
    web = root / "web"
    assets = web / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    manifest = assets / "auth-bug-core.cambrian-pack.yaml"
    manifest.write_bytes(SEED_MANIFEST.read_bytes())
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    catalog = assets / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_kind": "web_static_catalog",
                "packs": [
                    {
                        "pack_id": "auth-bug-core",
                        "pack_name": "Auth Bug Core",
                        "pack_kind": "lane",
                        "manifest_asset": "assets/auth-bug-core.cambrian-pack.yaml",
                        "manifest_sha256": digest,
                        "trust_level": "trusted",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return catalog


def test_registry_add_and_list_cli(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path)

    added = _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted")
    listed = _cli(tmp_path, "registry", "list")

    assert added.returncode == 0, added.stderr
    assert "Pack registry added." in added.stdout
    assert listed.returncode == 0, listed.stderr
    assert "local-web" in listed.stdout
    index = PackRegistryStore().load(default_registry_index_path(tmp_path))
    assert index.registries[0].trust_level == "trusted"


def test_registry_sync_local_catalog_creates_cache(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path)
    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted").returncode == 0

    synced = _cli(tmp_path, "registry", "sync", "local-web")

    assert synced.returncode == 0, synced.stderr
    assert "Registry synced." in synced.stdout
    cache = _read_yaml(tmp_path / ".cambrian" / "registries" / "cache" / "local-web.yaml")
    assert cache["packs"][0]["pack_id"] == "auth-bug-core"
    assert cache["pack_count"] if "pack_count" in cache else True


def test_pack_search_registry_and_kind_filter(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path)
    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted").returncode == 0
    assert _cli(tmp_path, "registry", "sync", "local-web").returncode == 0

    searched = _cli(tmp_path, "pack", "search", "auth", "--registry", "local-web")
    worker_only = _cli(tmp_path, "pack", "search", "auth", "--registry", "local-web", "--kind", "worker")

    assert searched.returncode == 0, searched.stderr
    assert "auth-bug-core" in searched.stdout
    assert "source  : local-web" in searched.stdout
    assert worker_only.returncode == 0, worker_only.stderr
    assert "auth-bug-core" not in worker_only.stdout


def test_pack_show_registry_surfaces_metadata(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path)
    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted").returncode == 0
    assert _cli(tmp_path, "registry", "sync", "local-web").returncode == 0

    shown = _cli(tmp_path, "pack", "show", "auth-bug-core", "--registry", "local-web")

    assert shown.returncode == 0, shown.stderr
    assert "Registry Pack" in shown.stdout
    assert "maturity: candidate" in shown.stdout
    assert "proof   : local_proof_required" in shown.stdout
    assert "sha256:" in shown.stdout
    assert "cambrian install pack auth-bug-core --registry local-web" in shown.stdout


def test_install_pack_from_registry_records_registry_provenance(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path)
    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted").returncode == 0
    assert _cli(tmp_path, "registry", "sync", "local-web").returncode == 0

    installed = _cli(tmp_path, "install", "pack", "auth-bug-core", "--registry", "local-web")

    assert installed.returncode == 0, installed.stderr
    assert "Installing pack from static registry." in installed.stdout
    index = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")
    record = index["packs"][0]
    assert record["pack_id"] == "auth-bug-core"
    assert record["source_kind"] == "remote_static_registry"
    assert "local-web:" in record["source_ref"]
    assert record["manifest_sha256"]
    assert (tmp_path / ".cambrian" / "registries" / "manifests").exists()


def test_digest_mismatch_blocks_registry_install(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path, digest="0" * 64)
    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted").returncode == 0
    assert _cli(tmp_path, "registry", "sync", "local-web").returncode == 0

    installed = _cli(tmp_path, "install", "pack", "auth-bug-core", "--registry", "local-web")

    assert installed.returncode != 0
    assert "digest mismatch" in installed.stderr
    assert not (tmp_path / ".cambrian" / "install" / "installed_packs.yaml").exists()


def test_require_trusted_blocks_unknown_registry(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path, trust_level="unknown")
    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "unknown").returncode == 0
    assert _cli(tmp_path, "registry", "sync", "local-web").returncode == 0

    installed = _cli(tmp_path, "install", "pack", "auth-bug-core", "--registry", "local-web", "--require-trusted")

    assert installed.returncode != 0
    assert "not trusted" in installed.stderr


def test_web_asset_manifest_ref_resolves_without_internet(tmp_path: Path) -> None:
    catalog = _write_web_asset_registry_fixture(tmp_path)
    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted").returncode == 0
    assert _cli(tmp_path, "registry", "sync", "local-web").returncode == 0

    installed = _cli(tmp_path, "install", "pack", "auth-bug-core", "--registry", "local-web", "--dry-run")

    assert installed.returncode == 0, installed.stderr
    assert "Pack Install Plan" in installed.stdout


def test_registry_commands_do_not_mutate_project_source(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    catalog = _write_registry_fixture(tmp_path)

    assert _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted").returncode == 0
    assert _cli(tmp_path, "registry", "sync", "local-web").returncode == 0
    assert _cli(tmp_path, "pack", "search", "auth", "--registry", "local-web").returncode == 0
    assert _cli(tmp_path, "pack", "show", "auth-bug-core", "--registry", "local-web").returncode == 0
    assert _cli(tmp_path, "install", "pack", "auth-bug-core", "--registry", "local-web", "--dry-run").returncode == 0
    assert _cli(tmp_path, "install", "pack", "auth-bug-core", "--registry", "local-web").returncode == 0

    assert source.read_text(encoding="utf-8") == before


def test_registry_module_search_uses_cache(tmp_path: Path) -> None:
    catalog = _write_registry_fixture(tmp_path)
    source = _cli(tmp_path, "registry", "add", "local-web", str(catalog), "--trust-level", "trusted")
    assert source.returncode == 0, source.stderr

    report = PackRegistrySyncer().sync(tmp_path, "local-web")
    packs = PackRegistryResolver().search(tmp_path, "auth", registry_name="local-web")

    assert report.status == "synced"
    assert [pack.pack_id for pack in packs] == ["auth-bug-core"]
