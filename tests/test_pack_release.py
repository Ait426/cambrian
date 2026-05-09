from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_authoring import PackBuilder, PackDraftBuilder, PackLocalPublisher, save_pack_draft
from engine.project_pack_install import PackInstaller
from engine.project_pack_release import PackReleaseChecker, PackWebSyncer


ROOT = Path(__file__).resolve().parents[1]
SEED_MANIFEST = ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _install_seed(root: Path) -> None:
    PackInstaller().install(root, SEED_MANIFEST)


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


def _built_manifest(root: Path, pack_id: str = "auth-bug-core-local") -> Path:
    _install_seed(root)
    draft = _draft(root, pack_id=pack_id)
    draft_ref = save_pack_draft(root, draft)
    out = root / "packs" / "generated" / f"{pack_id}.cambrian-pack.yaml"
    report = PackBuilder().build(root, root / draft_ref, out_path=out)
    assert report.status == "built"
    return out


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


def test_release_check_candidate_without_proof(tmp_path: Path) -> None:
    manifest = _built_manifest(tmp_path)

    report = PackReleaseChecker().check(tmp_path, str(manifest))

    assert report.safe_to_publish is True
    assert report.maturity == "candidate"
    assert report.proof_summary.proof_status in {"none", "local_only"}
    assert any(check.check_id == "proof_available" and check.status == "warn" for check in report.checks)


def test_release_check_require_proof_blocks(tmp_path: Path) -> None:
    manifest = _built_manifest(tmp_path)

    report = PackReleaseChecker().check(tmp_path, str(manifest), require_proof=True)

    assert report.safe_to_publish is False
    assert any("proof evidence is required" in item for item in report.errors)


def test_release_check_verified_with_proof_ref(tmp_path: Path) -> None:
    _install_seed(tmp_path)
    proof = tmp_path / ".cambrian" / "benchmarks" / "proof" / "proof_auth-bug-workset_test.yaml"
    _write_yaml(proof, {"schema_version": "1.0", "workset_name": "auth-bug-workset", "verdict": "wins_now"})
    draft = _draft(tmp_path)
    draft_ref = save_pack_draft(tmp_path, draft)
    manifest = tmp_path / "packs" / "generated" / "auth-bug-core-local.cambrian-pack.yaml"
    PackBuilder().build(tmp_path, tmp_path / draft_ref, out_path=manifest)

    report = PackReleaseChecker().check(tmp_path, str(manifest), require_proof=True)

    assert report.safe_to_publish is True
    assert report.proof_summary.proof_status in {"verified", "strong"}
    assert report.maturity in {"verified", "recommended"}
    assert report.proof_summary.proof_refs


def test_publish_local_stores_release_metadata(tmp_path: Path) -> None:
    manifest = _built_manifest(tmp_path)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)

    record = PackLocalPublisher().publish(tmp_path, manifest, confirm=True, catalog_path=catalog)
    entry = _read_yaml(catalog)["entries"][0]

    assert record.status == "published"
    assert entry["maturity"] == record.maturity
    assert entry["proof_status"] == record.proof_status
    assert "known_limits" in entry
    assert entry["release_report_ref"]


def test_publish_local_require_proof_blocks_weak_pack(tmp_path: Path) -> None:
    manifest = _built_manifest(tmp_path)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)

    record = PackLocalPublisher().publish(
        tmp_path,
        manifest,
        confirm=True,
        catalog_path=catalog,
        require_proof=True,
    )

    assert record.status == "blocked"
    assert _read_yaml(catalog)["entries"] == []
    assert any("proof evidence is required" in item for item in record.errors)


def test_fake_proof_absent_check_warns(tmp_path: Path) -> None:
    manifest = _built_manifest(tmp_path)
    payload = _read_yaml(manifest)
    payload["evidence"] = {"metrics": {"validated_proposal_rate": 0.72}}
    _write_yaml(manifest, payload)

    report = PackReleaseChecker().check(tmp_path, str(manifest))

    fake_check = next(check for check in report.checks if check.check_id == "fake_proof_absent")
    assert fake_check.status == "warn"
    assert any("without evidence refs" in item for item in fake_check.warnings)


def test_web_sync_updates_catalog_asset_with_release_metadata(tmp_path: Path) -> None:
    manifest = _built_manifest(tmp_path)
    catalog = tmp_path / "packs" / "catalog.yaml"
    web_dir = tmp_path / "web"
    _temp_catalog(catalog)
    PackLocalPublisher().publish(tmp_path, manifest, confirm=True, catalog_path=catalog)

    record = PackWebSyncer().sync(tmp_path, catalog_path=catalog, web_dir=web_dir)
    catalog_json = yaml.safe_load((web_dir / "assets" / "catalog.json").read_text(encoding="utf-8"))
    detail = (web_dir / "packs" / "auth-bug-core-local.html").read_text(encoding="utf-8")

    assert record.status == "synced"
    assert catalog_json["packs"][0]["pack_id"] == "auth-bug-core-local"
    assert catalog_json["packs"][0]["maturity"] == "candidate"
    assert catalog_json["packs"][0]["proof_status"] in {"none", "local_only", "local proof required"}
    assert "No public validated proposal rate is claimed" in detail
    assert "proven" not in detail.lower()


def test_release_check_cli_and_web_sync_do_not_mutate_project_source(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    manifest = _built_manifest(tmp_path)
    catalog = tmp_path / "packs" / "catalog.yaml"
    _temp_catalog(catalog)
    PackLocalPublisher().publish(tmp_path, manifest, confirm=True, catalog_path=catalog)

    checked = _cli(tmp_path, "pack", "release-check", str(manifest))
    assert checked.returncode == 0, checked.stderr
    synced = _cli(tmp_path, "pack", "web-sync", "--catalog", str(catalog), "--out", str(tmp_path / "web"))
    assert synced.returncode == 0, synced.stderr

    assert source.read_text(encoding="utf-8") == before
