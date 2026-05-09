from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_web_catalog_assets_exist_and_include_auth_bug_core() -> None:
    catalog_path = WEB / "assets" / "catalog.json"
    assert (WEB / "index.html").exists()
    assert (WEB / "packs" / "index.html").exists()
    assert (WEB / "packs" / "auth-bug-core.html").exists()
    assert catalog_path.exists()

    catalog = json.loads(_read(catalog_path))
    assert catalog["boundary"]["web"] == "hiring desk / control plane"
    assert any(pack["pack_id"] == "auth-bug-core" for pack in catalog["packs"])


def test_pack_detail_contains_install_command_and_included_artifacts() -> None:
    detail = _read(WEB / "packs" / "auth-bug-core.html")

    for phrase in [
        "cambrian install pack auth-bug-core",
        "cambrian install doctor",
        "bug-fix-agent",
        "regression-test-agent",
        "review-agent",
        "auth-bug-team",
        "auth-bug-template",
        "auth-bug-workset",
    ]:
        assert phrase in detail


def test_web_boundary_copy_is_present() -> None:
    combined = "\n".join(
        [
            _read(WEB / "index.html"),
            _read(WEB / "packs" / "index.html"),
            _read(WEB / "packs" / "auth-bug-core.html"),
        ]
    )

    assert "The web catalog is the hiring desk" in combined
    assert "Your local Cambrian runtime does the actual install, job handoff, validation, and proof" in combined
    assert "This page does not execute code or mutate `.cambrian/` state." in combined


def test_manifest_is_available_for_download_or_copy() -> None:
    manifest = WEB / "assets" / "auth-bug-core.cambrian-pack.yaml"
    detail = _read(WEB / "packs" / "auth-bug-core.html")

    assert manifest.exists()
    assert "pack_id: auth-bug-core" in _read(manifest)
    assert "../assets/auth-bug-core.cambrian-pack.yaml" in detail
    assert "cambrian install manifest ./packs/auth-bug-core.cambrian-pack.yaml" in detail


def test_web_catalog_makes_no_fake_proof_claims() -> None:
    detail = _read(WEB / "packs" / "auth-bug-core.html").lower()
    catalog = _read(WEB / "assets" / "catalog.json").lower()

    assert "proof status" in detail
    assert "seed pack. local proof required." in detail
    assert "cambrian pack proof auth-bug-core" in detail
    assert "proven" not in detail
    assert "validated_proposal_rate" not in catalog


def test_generate_web_catalog_does_not_mutate_runtime_state(tmp_path: Path) -> None:
    out_dir = tmp_path / "web"
    env = os.environ.copy()
    previous = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not previous else f"{ROOT}{os.pathsep}{previous}"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "generate_web_catalog.py"),
            "--catalog",
            str(ROOT / "packs" / "catalog.yaml"),
            "--out",
            str(out_dir),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "assets" / "catalog.json").exists()
    assert not (tmp_path / ".cambrian").exists()
