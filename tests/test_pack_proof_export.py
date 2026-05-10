from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from engine.project_pack_proof_export import PackProofExporter, PackProofExportStore
from engine.project_pack_release import PackReleaseChecker
from test_pack_proof import (
    ROOT,
    _activate_seed_pack,
    _cli,
    _install_seed_pack,
    _record_use,
)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _project_path(root: Path, ref: str | Path) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else root / path


def _useful_proof(tmp_path: Path) -> str:
    _install_seed_pack(tmp_path)
    _activate_seed_pack(tmp_path)
    _record_use(tmp_path, 1, validated=True, adopted=True, apply_passed=True, human=False)
    _record_use(tmp_path, 2, validated=True, adopted=False, apply_passed=False, human=False)
    _record_use(tmp_path, 3, validated=False, adopted=False, apply_passed=False, human=True)
    result = _cli(tmp_path, "pack", "proof", "auth-bug-core", "--save", "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["saved_paths"]["yaml"]


def _copy_seed_catalog(tmp_path: Path) -> Path:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "packs" / "catalog.yaml", packs_dir / "catalog.yaml")
    shutil.copyfile(ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml", packs_dir / "auth-bug-core.cambrian-pack.yaml")
    shutil.copyfile(
        ROOT / "packs" / "typescript-jest-auth-core.cambrian-pack.yaml",
        packs_dir / "typescript-jest-auth-core.cambrian-pack.yaml",
    )
    return packs_dir / "catalog.yaml"


def test_export_useful_proof_public_safe(tmp_path: Path) -> None:
    proof_path = _useful_proof(tmp_path)

    snapshot = PackProofExporter().export(tmp_path, "auth-bug-core", source_proof_path=Path(proof_path))
    payload = snapshot.to_dict()

    assert snapshot.privacy_classification == "public_safe"
    assert snapshot.proof_status == "useful"
    assert snapshot.marketplace_readiness == "proof_backed_candidate"
    assert snapshot.sample_size["outcome_linked_count"] == 3
    assert all(metric.public_safe for metric in snapshot.public_metrics)
    assert "source_refs" not in payload
    assert "usage_event_refs" not in yaml.safe_dump(payload, allow_unicode=True)
    assert "fix auth login" not in yaml.safe_dump(payload, allow_unicode=True)


def test_redacts_raw_private_refs_without_exporting_them(tmp_path: Path) -> None:
    proof_path = _project_path(tmp_path, _useful_proof(tmp_path))
    payload = _read_yaml(proof_path)
    payload.setdefault("source_refs", {})["local_session_ref"] = r"C:\Users\user\secret\session.yaml"
    payload["known_limits"] = ["C:\\Users\\user\\secret\\src\\auth.py detail should not be public"]
    sensitive_path = tmp_path / ".cambrian" / "packs" / "proof" / "proof_with_local_refs.yaml"
    _write_yaml(sensitive_path, payload)

    snapshot = PackProofExporter().export(tmp_path, "auth-bug-core", source_proof_path=sensitive_path)
    rendered = yaml.safe_dump(snapshot.to_dict(), allow_unicode=True)

    assert snapshot.privacy_classification == "public_safe"
    assert "local_absolute_paths" in snapshot.redacted_fields
    assert "C:\\Users" not in rendered


def test_blocks_sensitive_export_when_raw_fields_exist(tmp_path: Path) -> None:
    proof_path = _project_path(tmp_path, _useful_proof(tmp_path))
    payload = _read_yaml(proof_path)
    payload["raw_request"] = "private request text must not become public"
    blocked_path = tmp_path / ".cambrian" / "packs" / "proof" / "proof_raw_request.yaml"
    _write_yaml(blocked_path, payload)

    snapshot = PackProofExporter().export(tmp_path, "auth-bug-core", source_proof_path=blocked_path)

    assert snapshot.privacy_classification == "blocked_sensitive"
    assert snapshot.marketplace_readiness == "blocked"
    assert "raw_request" in snapshot.blocked_fields
    assert snapshot.errors


def test_insufficient_proof_export_has_caveat(tmp_path: Path) -> None:
    _install_seed_pack(tmp_path)

    snapshot = PackProofExporter().export(tmp_path, "auth-bug-core")

    assert snapshot.privacy_classification == "public_safe"
    assert snapshot.proof_status == "insufficient"
    assert snapshot.marketplace_readiness == "draft_only"
    assert any("insufficient" in item.lower() for item in snapshot.caveats)


def test_proof_export_show_works(tmp_path: Path) -> None:
    _useful_proof(tmp_path)
    exported = _cli(tmp_path, "pack", "proof-export", "auth-bug-core", "--json")
    assert exported.returncode == 0, exported.stderr
    export_ref = json.loads(exported.stdout)["saved_ref"]

    shown = _cli(tmp_path, "pack", "proof-export-show", export_ref)

    assert shown.returncode == 0, shown.stderr
    assert "Pack Proof Export" in shown.stdout
    assert "Classification:" in shown.stdout
    assert "Marketplace readiness:" in shown.stdout
    assert "validated_proposal_rate" in shown.stdout


def test_web_sync_consumes_public_proof_export(tmp_path: Path) -> None:
    _useful_proof(tmp_path)
    catalog_path = _copy_seed_catalog(tmp_path)
    out_path = tmp_path / "packs" / "proof_exports" / "auth-bug-core.public-proof.yaml"
    exported = _cli(tmp_path, "pack", "proof-export", "auth-bug-core", "--out", str(out_path))
    assert exported.returncode == 0, exported.stderr

    synced = _cli(tmp_path, "pack", "web-sync", "--catalog", str(catalog_path), "--out", str(tmp_path / "web"))
    catalog = json.loads((tmp_path / "web" / "assets" / "catalog.json").read_text(encoding="utf-8"))
    detail = (tmp_path / "web" / "packs" / "auth-bug-core.html").read_text(encoding="utf-8")
    proof = next(pack for pack in catalog["packs"] if pack["pack_id"] == "auth-bug-core")["proof"]

    assert synced.returncode == 0, synced.stderr
    assert proof["source"] == "local_public_export"
    assert proof["proof_status"] == "useful"
    assert proof["marketplace_readiness"] == "proof_backed_candidate"
    assert proof["metrics"]["validated_proposal_rate"] == 2 / 3
    assert "Local proof export:" in detail
    assert "Marketplace readiness: proof_backed_candidate" in detail
    assert "Local evidence. Not uploaded automatically." in detail


def test_web_catalog_no_fake_proof_without_export(tmp_path: Path) -> None:
    catalog_path = _copy_seed_catalog(tmp_path)

    synced = _cli(tmp_path, "pack", "web-sync", "--catalog", str(catalog_path), "--out", str(tmp_path / "web"))
    catalog = json.loads((tmp_path / "web" / "assets" / "catalog.json").read_text(encoding="utf-8"))

    assert synced.returncode == 0, synced.stderr
    proof = next(pack for pack in catalog["packs"] if pack["pack_id"] == "auth-bug-core")["proof"]
    assert proof is None
    assert "validated_proposal_rate" not in json.dumps(catalog)


def test_release_check_uses_public_safe_export(tmp_path: Path) -> None:
    _useful_proof(tmp_path)
    snapshot = PackProofExporter().export(tmp_path, "auth-bug-core")
    assert snapshot.privacy_classification == "public_safe"

    report = PackReleaseChecker().check(tmp_path, str(ROOT / "packs" / "auth-bug-core.cambrian-pack.yaml"), require_proof=True)

    assert report.safe_to_publish is True
    assert report.proof_summary.proof_status in {"verified", "strong"}
    assert any("Local evidence only" in item for item in report.proof_summary.warnings)


def test_proof_export_does_not_mutate_project_source(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    _useful_proof(tmp_path)

    exported = _cli(tmp_path, "pack", "proof-export", "auth-bug-core", "--out", str(tmp_path / "packs" / "proof_exports" / "auth-bug-core.public-proof.yaml"))
    shown = _cli(tmp_path, "pack", "proof-export-show", "latest")

    assert exported.returncode == 0, exported.stderr
    assert shown.returncode == 0, shown.stderr
    assert source.read_text(encoding="utf-8") == before
    assert (tmp_path / ".cambrian" / "packs" / "proof_exports").exists()
    assert PackProofExportStore().load_yaml(tmp_path / ".cambrian" / "packs" / "proof_exports" / "latest.yaml").pack_id == "auth-bug-core"
