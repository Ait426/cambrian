from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_registry_export import RegistryBundleChecker, RegistryBundleExporter
from test_pack_proof_export import _copy_seed_catalog, _useful_proof


ROOT = Path(__file__).resolve().parents[1]


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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare_project_with_public_proof(tmp_path: Path) -> Path:
    _copy_seed_catalog(tmp_path)
    _useful_proof(tmp_path)
    out = tmp_path / "packs" / "proof_exports" / "auth-bug-core.public-proof.yaml"
    result = _cli(tmp_path, "pack", "proof-export", "auth-bug-core", "--out", str(out))
    assert result.returncode == 0, result.stderr
    return out


def _export_bundle(tmp_path: Path, *, namespace: str = "cambrian") -> Path:
    bundle = tmp_path / "dist" / "cambrian-registry"
    result = _cli(tmp_path, "registry", "export", "--out", str(bundle), "--registry-name", "demo", "--namespace", namespace)
    assert result.returncode == 0, result.stderr
    return bundle


def test_export_bundle_creates_required_files(tmp_path: Path) -> None:
    _copy_seed_catalog(tmp_path)

    bundle = _export_bundle(tmp_path)

    assert (bundle / "registry.yaml").exists()
    assert (bundle / "catalog.json").exists()
    assert (bundle / "checksums.sha256").exists()
    assert (bundle / "manifests" / "auth-bug-core.cambrian-pack.yaml").exists()
    catalog = _read_json(bundle / "catalog.json")
    assert catalog["packs"][0]["manifest_path"] == "manifests/auth-bug-core.cambrian-pack.yaml"
    assert catalog["packs"][0]["manifest_sha256"]


def test_public_proof_included_in_bundle_catalog(tmp_path: Path) -> None:
    _prepare_project_with_public_proof(tmp_path)

    bundle = _export_bundle(tmp_path)
    catalog = _read_json(bundle / "catalog.json")
    pack = catalog["packs"][0]

    assert (bundle / "proof" / "auth-bug-core.public-proof.yaml").exists()
    assert pack["proof_path"] == "proof/auth-bug-core.public-proof.yaml"
    assert pack["proof"]["source"] == "local_public_export"
    assert pack["proof"]["proof_status"] == "useful"
    assert pack["reputation_verdict"] == "useful"


def test_raw_local_proof_card_is_not_copied(tmp_path: Path) -> None:
    _prepare_project_with_public_proof(tmp_path)
    assert list((tmp_path / ".cambrian" / "packs" / "proof").glob("proof_*.yaml"))

    bundle = _export_bundle(tmp_path)
    exported_paths = [str(path.relative_to(bundle)).replace("\\", "/") for path in bundle.rglob("*") if path.is_file()]

    assert not any(path.startswith(".cambrian/packs/proof/") for path in exported_paths)
    assert not any("raw_request" in path for path in exported_paths)


def test_export_check_passes_and_checksums_match(tmp_path: Path) -> None:
    _prepare_project_with_public_proof(tmp_path)
    bundle = _export_bundle(tmp_path)

    report = RegistryBundleChecker().check(bundle)

    assert report.status == "passed"
    assert report.digest_matches is True
    assert report.privacy_safe is True
    assert report.registry_sync_compatible is True
    assert report.manifest_count == 2
    assert report.proof_export_count == 1


def test_export_check_fails_on_sensitive_public_proof_content(tmp_path: Path) -> None:
    _prepare_project_with_public_proof(tmp_path)
    bundle = _export_bundle(tmp_path)
    proof = bundle / "proof" / "auth-bug-core.public-proof.yaml"
    payload = _read_yaml(proof)
    payload["old_text"] = "private patch text"
    proof.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    report = RegistryBundleChecker().check(bundle)

    assert report.status == "failed"
    assert report.privacy_safe is False
    assert any("privacy-sensitive" in error for error in report.errors)


def test_exported_catalog_can_be_registry_synced(tmp_path: Path) -> None:
    _prepare_project_with_public_proof(tmp_path)
    bundle = _export_bundle(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    added = _cli(consumer, "registry", "add", "demo", str(bundle / "catalog.json"))
    synced = _cli(consumer, "registry", "sync", "demo", "--json")
    payload = json.loads(synced.stdout)

    assert added.returncode == 0, added.stderr
    assert synced.returncode == 0, synced.stderr
    assert payload["status"] == "synced"
    assert payload["pack_count"] == 2


def test_install_from_exported_bundle(tmp_path: Path) -> None:
    _prepare_project_with_public_proof(tmp_path)
    bundle = _export_bundle(tmp_path)
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    assert _cli(consumer, "registry", "add", "demo", str(bundle / "catalog.json")).returncode == 0
    assert _cli(consumer, "registry", "sync", "demo").returncode == 0

    installed = _cli(consumer, "install", "pack", "cambrian/auth-bug-core", "--registry", "demo")

    assert installed.returncode == 0, installed.stderr
    installed_packs = _read_yaml(consumer / ".cambrian" / "install" / "installed_packs.yaml")
    assert installed_packs["packs"][0]["pack_id"] == "auth-bug-core"
    assert installed_packs["packs"][0]["manifest_sha256"]


def test_namespace_applied_to_exported_catalog(tmp_path: Path) -> None:
    _copy_seed_catalog(tmp_path)

    bundle = _export_bundle(tmp_path, namespace="cambrian")
    catalog = _read_json(bundle / "catalog.json")

    assert catalog["packs"][0]["namespace"] == "cambrian"
    assert catalog["packs"][0]["install_command"] == "cambrian install pack cambrian/auth-bug-core --registry demo"


def test_registry_export_does_not_mutate_project_source(tmp_path: Path) -> None:
    _copy_seed_catalog(tmp_path)
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")

    bundle = _export_bundle(tmp_path)
    checked = _cli(tmp_path, "registry", "export-check", str(bundle))

    assert checked.returncode == 0, checked.stderr
    assert source.read_text(encoding="utf-8") == before
    assert not (tmp_path / ".cambrian" / "registries").exists()


def test_docs_mention_static_registry_export_only() -> None:
    combined = "\n".join(
        [
            (ROOT / "README.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "product" / "06_PACKS_AND_INSTALL.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "product" / "09_WEB_CONTROL_PLANE.md").read_text(encoding="utf-8"),
        ]
    )

    assert "cambrian registry export --out dist/cambrian-registry" in combined
    assert "cambrian registry export-check dist/cambrian-registry" in combined
    assert "no upload" in combined.lower() or "업로드하지" in combined
