from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_catalog import (
    PackCatalogStore,
    PackFitAnalyzer,
    default_pack_catalog_path,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "packs" / "catalog.yaml"


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
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def _make_python_pytest_auth_project(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "src" / "auth.py").write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    (root / "tests" / "test_auth.py").write_text("def test_auth_placeholder():\n    assert True\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")


def test_catalog_loads_auth_bug_core() -> None:
    catalog = PackCatalogStore().load(CATALOG)

    assert default_pack_catalog_path(ROOT) == CATALOG
    assert not catalog.errors
    assert any(entry.pack_id == "auth-bug-core" for entry in catalog.entries)


def test_pack_list_shows_auth_bug_core_and_kind_filter(tmp_path: Path) -> None:
    listed = _cli(tmp_path, "pack", "list")
    assert listed.returncode == 0, listed.stderr
    assert "Available Packs" in listed.stdout
    assert "auth-bug-core" in listed.stdout

    lane_only = _cli(tmp_path, "pack", "list", "--kind", "lane")
    assert lane_only.returncode == 0, lane_only.stderr
    assert "auth-bug-core" in lane_only.stdout

    worker_only = _cli(tmp_path, "pack", "list", "--kind", "worker")
    assert worker_only.returncode == 0, worker_only.stderr
    assert "auth-bug-core" not in worker_only.stdout


def test_pack_show_displays_manifest_fit_and_install_command(tmp_path: Path) -> None:
    _make_python_pytest_auth_project(tmp_path)

    shown = _cli(tmp_path, "pack", "show", "auth-bug-core")

    assert shown.returncode == 0, shown.stderr
    assert "Pack" in shown.stdout
    assert "packs/auth-bug-core.cambrian-pack.yaml" in shown.stdout
    assert "status: strong" in shown.stdout
    assert "cambrian install pack auth-bug-core" in shown.stdout


def test_pack_recommend_strong_fit(tmp_path: Path) -> None:
    _make_python_pytest_auth_project(tmp_path)

    recommended = _cli(tmp_path, "pack", "recommend")

    assert recommended.returncode == 0, recommended.stderr
    assert "auth-bug-core" in recommended.stdout
    assert "strong" in recommended.stdout


def test_pack_recommend_unknown_fit_does_not_crash(tmp_path: Path) -> None:
    recommended = _cli(tmp_path, "pack", "recommend")

    assert recommended.returncode == 0, recommended.stderr
    assert "No strong recommendation yet." in recommended.stdout
    assert "unknown" in recommended.stdout


def test_install_pack_resolves_manifest_and_records_local_catalog_source(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "auth-bug-core")

    assert result.returncode == 0, result.stderr
    assert "Installing pack from local catalog." in result.stdout
    index = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")
    record = index["packs"][0]
    assert record["pack_id"] == "auth-bug-core"
    assert record["source_kind"] == "local_catalog"
    assert record["source_ref"] == "packs/catalog.yaml#auth-bug-core"


def test_install_pack_dry_run_does_not_write_library(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "auth-bug-core", "--dry-run")

    assert result.returncode == 0, result.stderr
    assert "Pack Install Plan" in result.stdout
    assert not (tmp_path / ".cambrian").exists()


def test_missing_pack_is_blocked_with_helpful_error(tmp_path: Path) -> None:
    result = _cli(tmp_path, "install", "pack", "missing-pack")

    assert result.returncode != 0
    assert "Pack install blocked" in result.stderr
    assert "missing-pack" in result.stderr


def test_pack_catalog_surfaces_do_not_mutate_project_source_files(tmp_path: Path) -> None:
    _make_python_pytest_auth_project(tmp_path)
    source = tmp_path / "src" / "auth.py"
    test_file = tmp_path / "tests" / "test_auth.py"
    before_source = source.read_text(encoding="utf-8")
    before_test = test_file.read_text(encoding="utf-8")

    assert _cli(tmp_path, "pack", "list").returncode == 0
    assert _cli(tmp_path, "pack", "show", "auth-bug-core").returncode == 0
    assert _cli(tmp_path, "pack", "recommend").returncode == 0
    assert _cli(tmp_path, "install", "pack", "auth-bug-core", "--dry-run").returncode == 0
    assert _cli(tmp_path, "install", "pack", "auth-bug-core").returncode == 0

    assert source.read_text(encoding="utf-8") == before_source
    assert test_file.read_text(encoding="utf-8") == before_test


def test_fit_analyzer_strong_for_python_pytest_auth_project(tmp_path: Path) -> None:
    _make_python_pytest_auth_project(tmp_path)
    catalog = PackCatalogStore().load(CATALOG)
    entry = next(item for item in catalog.entries if item.pack_id == "auth-bug-core")

    fit = PackFitAnalyzer().analyze(tmp_path, entry)

    assert fit.fit_status == "strong"
    assert fit.score >= 0.9
