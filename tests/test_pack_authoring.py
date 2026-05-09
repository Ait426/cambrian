from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from engine.project_pack_authoring import (
    PackBuilder,
    PackDraftBuilder,
    PackLocalPublisher,
    PackValidator,
    default_pack_drafts_dir,
    load_pack_draft,
    save_pack_draft,
)
from engine.project_pack_catalog import PackCatalogStore
from engine.project_pack_install import PackInstaller, PackManifestLoader


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"
CATALOG = ROOT / "packs" / "catalog.yaml"


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


def _install_seed(root: Path) -> None:
    PackInstaller().install(root, SEED_MANIFEST)


def _draft(root: Path, pack_id: str = "auth-bug-core-local"):
    return PackDraftBuilder().create(
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


def _temp_catalog(path: Path) -> None:
    _write_yaml(
        path,
        {
            "schema_version": "1.0",
            "updated_at": None,
            "source_kind": "local_seed",
            "entries": [],
            "warnings": [],
            "errors": [],
        },
    )


def test_draft_lane_pack(tmp_path: Path) -> None:
    _install_seed(tmp_path)

    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)

    assert not draft.errors
    assert draft.pack_kind == "lane"
    assert draft.template_refs == ["auth-bug-template"]
    assert (tmp_path / draft_ref).exists()
    assert load_pack_draft(tmp_path / draft_ref).pack_id == "auth-bug-core-local"


def test_validate_draft_missing_refs_fails_helpfully(tmp_path: Path) -> None:
    draft = PackDraftBuilder().create(
        tmp_path,
        "missing-ref-pack",
        "lane",
        {"templates": ["missing-template"], "lane": "missing-lane"},
    )

    report = PackValidator().validate_draft(tmp_path, draft)

    assert report.status == "blocked"
    assert any("template ref not found" in item for item in report.errors)
    assert any("lane ref not found" in item for item in report.errors)


def test_build_manifest_from_draft(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    out = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"

    report = PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=out)
    manifest = PackManifestLoader().load(out)

    assert report.status == "built"
    assert report.manifest_sha256
    assert report.included_artifacts["templates"] == ["auth-bug-template"]
    assert manifest.pack_id == "auth-bug-core-local"
    assert manifest.source["kind"] == "local_authoring"
    assert manifest.install["auto_apply"] is False


def test_evidence_refs_included_when_available(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    proof = tmp_path / ".cambrian" / "benchmarks" / "proof" / "proof_auth-bug-workset_test.yaml"
    _write_yaml(proof, {"schema_version": "1.0.0", "workset_name": "auth-bug-workset"})
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    out = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"

    report = PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=out)
    manifest = _read_yaml(out)

    assert report.status == "built"
    assert "evidence" in manifest
    assert "proof_refs" in manifest["evidence"]
    assert manifest["evidence"]["benchmark_worksets"] == ["auth-bug-workset"]


def test_publish_local_preview_does_not_mutate_catalog(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    out = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"
    PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=out)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)
    before = catalog.read_text(encoding="utf-8")

    record = PackLocalPublisher().publish(tmp_path, out, confirm=False, catalog_path=catalog)

    assert record.status == "preview"
    assert catalog.read_text(encoding="utf-8") == before


def test_publish_local_confirm_updates_catalog_with_digest_and_local_trust(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    out = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"
    PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=out)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)

    record = PackLocalPublisher().publish(tmp_path, out, confirm=True, catalog_path=catalog)
    payload = _read_yaml(catalog)

    assert record.status == "published"
    assert payload["entries"][0]["pack_id"] == "auth-bug-core-local"
    assert payload["entries"][0]["manifest_sha256"] == record.manifest_sha256
    assert payload["entries"][0]["trust_level"] == "local"


def test_duplicate_publish_same_sha_is_noop(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    out = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"
    PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=out)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)

    first = PackLocalPublisher().publish(tmp_path, out, confirm=True, catalog_path=catalog)
    second = PackLocalPublisher().publish(tmp_path, out, confirm=True, catalog_path=catalog)
    payload = _read_yaml(catalog)

    assert first.status == "published"
    assert second.status == "preview"
    assert len(payload["entries"]) == 1
    assert any("already published" in item for item in second.warnings)


def test_duplicate_publish_different_sha_is_blocked(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    out = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"
    PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=out)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)
    PackLocalPublisher().publish(tmp_path, out, confirm=True, catalog_path=catalog)

    changed = deepcopy(_read_yaml(out))
    changed["version"] = "0.2.0"
    changed_path = tmp_path / "packs" / "generated" / "auth-bug-core-local-v2.cambrian-pack.yaml"
    _write_yaml(changed_path, changed)
    second = PackLocalPublisher().publish(tmp_path, changed_path, confirm=True, catalog_path=catalog)

    assert second.status == "blocked"
    assert any("different digest" in item for item in second.errors)


def test_published_pack_is_visible_and_installable_through_cli(tmp_path: Path) -> None:
    pack_id = "task139-auth-bug-core-local-test"
    generated = ROOT / "packs" / "generated" / f"{pack_id}.cambrian-pack.yaml"
    original_catalog = CATALOG.read_text(encoding="utf-8")
    try:
        _install_seed(tmp_path)
        draft = _draft(tmp_path, pack_id=pack_id)
        draft_ref = save_pack_draft(tmp_path, draft)
        report = PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=generated)
        assert report.status == "built"

        published = _cli(tmp_path, "pack", "publish-local", str(generated), "--confirm")
        assert published.returncode == 0, published.stderr
        assert "Pack published to local catalog." in published.stdout

        shown = _cli(tmp_path, "pack", "show", pack_id)
        assert shown.returncode == 0, shown.stderr
        assert f"cambrian install pack {pack_id}" in shown.stdout

        install_root = tmp_path / "install-target"
        install_root.mkdir()
        installed = _cli(install_root, "install", "pack", pack_id)
        assert installed.returncode == 0, installed.stderr
        assert "Pack install completed." in installed.stdout
    finally:
        CATALOG.write_text(original_catalog, encoding="utf-8")
        if generated.exists():
            generated.unlink()


def test_authoring_commands_do_not_mutate_project_source_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    test_file.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")
    _install_seed(tmp_path)

    created = _cli(
        tmp_path,
        "pack",
        "draft",
        "auth-bug-core-local",
        "--kind",
        "lane",
        "--worker",
        "bug-fix-agent",
        "--team",
        "auth-bug-team",
        "--template",
        "auth-bug-template",
        "--benchmark",
        "auth-bug-workset",
        "--lane",
        "python-pytest-auth-bug-core",
    )
    assert created.returncode == 0, created.stderr
    draft_path = default_pack_drafts_dir(tmp_path) / "draft_auth-bug-core-local.yaml"
    built = _cli(tmp_path, "pack", "build", str(draft_path), "--out", str(tmp_path / "pack.yaml"))
    assert built.returncode == 0, built.stderr
    validated = _cli(tmp_path, "pack", "validate", str(tmp_path / "pack.yaml"))
    assert validated.returncode == 0, validated.stderr

    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test


def test_publish_local_class_output_can_be_loaded_by_catalog_store(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    out = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"
    PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=out)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)
    PackLocalPublisher().publish(tmp_path, out, confirm=True, catalog_path=catalog)

    loaded = PackCatalogStore().load(catalog)

    assert not loaded.errors
    assert loaded.entries[0].pack_id == "auth-bug-core-local"
