from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from engine.project_pack_install import PackInstaller
from engine.project_pack_lifecycle import PackUpdater
from engine.project_pack_trust import (
    PackIntegrityHasher,
    PackVerifier,
    default_pack_lock_path,
)


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"
EXPECTED_SEED_SHA = "72332265cbe86c7d7992032ff163b8755bf7e489c13d34362c55bf69880e037b"


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
            "capabilities": ["auth edge review"],
        }
    )
    path = tmp_path / "incoming" / "auth-bug-core-v0.2.cambrian-pack.yaml"
    _write_yaml(path, payload)
    return path


def test_hash_manifest_is_deterministic() -> None:
    first = PackIntegrityHasher().hash_file(SEED_MANIFEST)
    second = PackIntegrityHasher().hash_file(SEED_MANIFEST)

    assert first.sha256 == second.sha256 == EXPECTED_SEED_SHA
    assert first.size_bytes > 0
    assert not first.errors


def test_pack_verify_manifest_file() -> None:
    report = PackVerifier().verify_manifest(SEED_MANIFEST)

    assert report.status == "verified"
    assert report.actual_sha256 == EXPECTED_SEED_SHA
    assert report.manifest_exists is True


def test_pack_verify_catalog_entry_with_manifest_sha() -> None:
    report = PackVerifier().verify_catalog_pack(ROOT, "auth-bug-core")

    assert report.status == "verified"
    assert report.expected_sha256 == EXPECTED_SEED_SHA
    assert report.actual_sha256 == EXPECTED_SEED_SHA
    assert report.trust_summary
    assert report.trust_summary.trust_level == "trusted"


def test_catalog_expected_hash_mismatch_blocks_install() -> None:
    with pytest.raises(ValueError, match="digest mismatch"):
        PackInstaller().install(Path.cwd(), SEED_MANIFEST, expected_sha256="0" * 64)


def test_install_manifest_stores_digest_and_lockfile(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)

    installed = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")
    record = installed["packs"][0]
    assert record["manifest_sha256"] == EXPECTED_SEED_SHA
    assert record["manifest_size_bytes"] > 0
    assert record["trust_level"] == "trusted"

    lock = _read_yaml(default_pack_lock_path(tmp_path))
    assert lock["packs"][0]["pack_id"] == "auth-bug-core"
    assert lock["packs"][0]["manifest_sha256"] == EXPECTED_SEED_SHA


def test_install_verify_installed_pack_passes(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)

    result = _cli(tmp_path, "install", "verify", "auth-bug-core")

    assert result.returncode == 0, result.stderr
    assert "Pack Verify" in result.stdout
    assert "status" in result.stdout.lower()
    assert "verified" in result.stdout


def test_install_verify_detects_tampered_manifest_copy(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)
    installed = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")
    manifest_ref = installed["packs"][0]["manifest_ref"]
    manifest_copy = tmp_path / manifest_ref
    manifest_copy.write_text(manifest_copy.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    result = _cli(tmp_path, "install", "verify", "auth-bug-core")

    assert result.returncode != 0
    assert "digest mismatch" in result.stdout


def test_install_verify_detects_missing_artifact_refs(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)
    (tmp_path / ".cambrian" / "templates" / "templates.yaml").unlink()

    result = _cli(tmp_path, "install", "verify", "auth-bug-core")

    assert result.returncode != 0
    assert "missing template ref" in result.stdout


def test_require_trusted_blocks_unknown_local_manifest_source(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "manifest", str(SEED_MANIFEST), "--require-trusted")

    assert result.returncode != 0
    assert "not trusted" in result.stderr
    assert not (tmp_path / ".cambrian").exists()


def test_update_records_digest(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)
    incoming = _newer_manifest(tmp_path)

    record = PackUpdater().update(tmp_path, "auth-bug-core", incoming_manifest_path=incoming, confirm=True)

    assert record.status == "updated"
    assert record.previous_manifest_sha256 == EXPECTED_SEED_SHA
    assert record.incoming_manifest_sha256
    saved = _read_yaml(tmp_path / record.saved_ref)
    assert saved["previous_manifest_sha256"] == EXPECTED_SEED_SHA
    assert saved["incoming_manifest_sha256"] == record.incoming_manifest_sha256


def test_backward_compatibility_missing_digest_warns_not_crashes(tmp_path: Path) -> None:
    PackInstaller().install(tmp_path, SEED_MANIFEST)
    installed_path = tmp_path / ".cambrian" / "install" / "installed_packs.yaml"
    installed = _read_yaml(installed_path)
    installed["packs"][0].pop("manifest_sha256", None)
    _write_yaml(installed_path, installed)

    report = PackVerifier().verify_installed_pack(tmp_path, "auth-bug-core")

    assert report.status == "warning"
    assert "missing recorded manifest digest" in report.warnings


def test_trust_commands_do_not_mutate_project_source_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")
    assert _cli(tmp_path, "pack", "verify", "auth-bug-core").returncode == 0
    assert _cli(tmp_path, "pack", "verify", str(SEED_MANIFEST)).returncode == 0
    assert _cli(tmp_path, "install", "pack", "auth-bug-core").returncode == 0
    assert _cli(tmp_path, "install", "verify").returncode == 0

    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test
