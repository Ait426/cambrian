from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from engine.project_pack_dependencies import PackDependencyResolver, PackRefParser


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


def _write_manifest(
    registry: Path,
    pack_id: str,
    *,
    namespace: str = "cambrian",
    version: str = "0.1.0",
    pack_kind: str = "template",
    dependencies: list[dict] | None = None,
) -> tuple[Path, str]:
    manifest = registry / f"{pack_id}-{version}.cambrian-pack.yaml"
    workers = []
    teams = []
    templates = []
    lane = None
    if pack_kind == "worker":
        workers = [{"id": f"{pack_id}-agent", "name": f"{pack_id} agent"}]
    if pack_kind == "team":
        teams = [{"name": f"{pack_id}-team", "lead_agent_id": f"{pack_id}-agent"}]
    if pack_kind == "template":
        templates = [{"name": f"{pack_id}-template", "template_kind": "fixture_template"}]
    if pack_kind == "lane":
        lane = {"lane_id": f"{namespace}-{pack_id}", "label": pack_id}
    payload = {
        "schema_version": "1.0",
        "namespace": namespace,
        "pack_id": pack_id,
        "pack_name": pack_id.replace("-", " ").title(),
        "pack_kind": pack_kind,
        "version": version,
        "description": f"{pack_id} fixture",
        "source": {"kind": "test_fixture", "origin_ref": str(manifest)},
        "compatibility": {"stacks": ["python"], "test_frameworks": ["pytest"]},
        "dependencies": dependencies or [],
        "workers": workers,
        "teams": teams,
        "templates": templates,
        "lane": lane,
        "install": {
            "install_as_library": True,
            "auto_apply": False,
            "auto_bootstrap": False,
            "auto_promote": False,
        },
        "warnings": [],
    }
    manifest.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return manifest, digest


def _write_registry(tmp_path: Path, packs: list[dict]) -> Path:
    registry = tmp_path / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    entries = []
    for pack in packs:
        manifest, digest = _write_manifest(
            registry,
            pack["pack_id"],
            namespace=pack.get("namespace", "cambrian"),
            version=pack.get("version", "0.1.0"),
            pack_kind=pack.get("pack_kind", "template"),
            dependencies=pack.get("dependencies", []),
        )
        entries.append(
            {
                "namespace": pack.get("namespace", "cambrian"),
                "pack_id": pack["pack_id"],
                "pack_name": pack.get("pack_name", pack["pack_id"]),
                "pack_kind": pack.get("pack_kind", "template"),
                "version": pack.get("version", "0.1.0"),
                "description": pack.get("description", pack["pack_id"]),
                "tags": pack.get("tags", []),
                "maturity": "candidate",
                "proof_status": "local_proof_required",
                "compatibility": {"stacks": ["python"], "test_frameworks": ["pytest"]},
                "dependencies": pack.get("dependencies", []),
                "manifest_path": manifest.name,
                "manifest_sha256": digest,
                "trust_level": "trusted",
            }
        )
    catalog = registry / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source_kind": "web_static_catalog",
                "packs": entries,
                "warnings": [],
                "errors": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return catalog


def _sync_registry(tmp_path: Path, catalog: Path, name: str = "official") -> None:
    added = _cli(tmp_path, "registry", "add", name, str(catalog), "--trust-level", "trusted")
    synced = _cli(tmp_path, "registry", "sync", name)
    assert added.returncode == 0, added.stderr
    assert synced.returncode == 0, synced.stderr


def test_parse_pack_refs() -> None:
    parser = PackRefParser()

    assert parser.parse("auth-bug-core").namespace is None
    assert parser.parse("auth-bug-core").pack_id == "auth-bug-core"
    assert parser.parse("auth-bug-core@0.2.0").version == "0.2.0"
    assert parser.parse("cambrian/auth-bug-core").namespace == "cambrian"
    parsed = parser.parse("cambrian/auth-bug-core@0.2.0")
    assert parsed.namespace == "cambrian"
    assert parsed.pack_id == "auth-bug-core"
    assert parsed.version == "0.2.0"


def test_ambiguous_namespace_blocked(tmp_path: Path) -> None:
    catalog = _write_registry(tmp_path, [{"pack_id": "auth-bug-core", "namespace": "cambrian"}])
    _sync_registry(tmp_path, catalog)

    graph = PackDependencyResolver().resolve(tmp_path, "auth-bug-core")

    assert not graph.safe_to_install
    assert "ambiguous" in " ".join(graph.conflicts)


def test_resolve_no_deps(tmp_path: Path) -> None:
    catalog = _write_registry(tmp_path, [{"pack_id": "auth-workers", "namespace": "cambrian"}])
    _sync_registry(tmp_path, catalog)

    graph = PackDependencyResolver().resolve(tmp_path, "cambrian/auth-workers", registry_name="official")

    assert graph.safe_to_install
    assert graph.install_order == ["cambrian/auth-workers@0.1.0"]


def test_resolve_dependencies_order(tmp_path: Path) -> None:
    catalog = _write_registry(
        tmp_path,
        [
            {"pack_id": "auth-workers", "namespace": "cambrian", "version": "0.1.0"},
            {"pack_id": "auth-template", "namespace": "cambrian", "version": "0.2.0"},
            {
                "pack_id": "auth-bug-core",
                "namespace": "cambrian",
                "version": "0.2.0",
                "pack_kind": "lane",
                "dependencies": [
                    {"pack_ref": "cambrian/auth-workers", "version_constraint": ">=0.1.0"},
                    {"pack_ref": "cambrian/auth-template", "version_constraint": "0.2.0"},
                ],
            },
        ],
    )
    _sync_registry(tmp_path, catalog)

    graph = PackDependencyResolver().resolve(tmp_path, "cambrian/auth-bug-core@0.2.0", registry_name="official")

    assert graph.safe_to_install
    assert graph.install_order == [
        "cambrian/auth-workers@0.1.0",
        "cambrian/auth-template@0.2.0",
        "cambrian/auth-bug-core@0.2.0",
    ]


def test_version_constraints_choose_exact_and_minimum(tmp_path: Path) -> None:
    catalog = _write_registry(
        tmp_path,
        [
            {"pack_id": "auth-template", "namespace": "cambrian", "version": "0.1.0"},
            {"pack_id": "auth-template", "namespace": "cambrian", "version": "0.2.0"},
            {
                "pack_id": "auth-bug-core",
                "namespace": "cambrian",
                "version": "0.3.0",
                "pack_kind": "lane",
                "dependencies": [{"pack_ref": "cambrian/auth-template", "version_constraint": ">=0.1.0"}],
            },
            {
                "pack_id": "auth-bug-core-exact",
                "namespace": "cambrian",
                "version": "0.3.0",
                "pack_kind": "lane",
                "dependencies": [{"pack_ref": "cambrian/auth-template", "version_constraint": "0.1.0"}],
            },
        ],
    )
    _sync_registry(tmp_path, catalog)

    minimum = PackDependencyResolver().resolve(tmp_path, "cambrian/auth-bug-core", registry_name="official")
    exact = PackDependencyResolver().resolve(tmp_path, "cambrian/auth-bug-core-exact", registry_name="official")

    assert "cambrian/auth-template@0.2.0" in minimum.install_order
    assert "cambrian/auth-template@0.1.0" in exact.install_order


def test_missing_required_dependency_blocked(tmp_path: Path) -> None:
    catalog = _write_registry(
        tmp_path,
        [
            {
                "pack_id": "auth-bug-core",
                "namespace": "cambrian",
                "dependencies": [{"pack_ref": "cambrian/missing-pack"}],
            }
        ],
    )
    _sync_registry(tmp_path, catalog)

    graph = PackDependencyResolver().resolve(tmp_path, "cambrian/auth-bug-core", registry_name="official")

    assert not graph.safe_to_install
    assert "missing required dependency" in " ".join(graph.errors)


def test_optional_missing_dependency_warns(tmp_path: Path) -> None:
    catalog = _write_registry(
        tmp_path,
        [
            {
                "pack_id": "auth-bug-core",
                "namespace": "cambrian",
                "dependencies": [{"pack_ref": "cambrian/nice-to-have", "optional": True}],
            }
        ],
    )
    _sync_registry(tmp_path, catalog)

    graph = PackDependencyResolver().resolve(tmp_path, "cambrian/auth-bug-core", registry_name="official")

    assert graph.safe_to_install
    assert "missing dependency" in " ".join(graph.warnings)


def test_circular_dependency_blocked(tmp_path: Path) -> None:
    catalog = _write_registry(
        tmp_path,
        [
            {"pack_id": "a", "namespace": "cambrian", "dependencies": [{"pack_ref": "cambrian/b"}]},
            {"pack_id": "b", "namespace": "cambrian", "dependencies": [{"pack_ref": "cambrian/a"}]},
        ],
    )
    _sync_registry(tmp_path, catalog)

    graph = PackDependencyResolver().resolve(tmp_path, "cambrian/a", registry_name="official")

    assert not graph.safe_to_install
    assert "circular" in " ".join(graph.errors)


def test_install_pack_requires_confirm_deps(tmp_path: Path) -> None:
    catalog = _write_registry(
        tmp_path,
        [
            {"pack_id": "auth-template", "namespace": "cambrian"},
            {
                "pack_id": "auth-bug-core",
                "namespace": "cambrian",
                "pack_kind": "lane",
                "dependencies": [{"pack_ref": "cambrian/auth-template"}],
            },
        ],
    )
    _sync_registry(tmp_path, catalog)

    result = _cli(tmp_path, "install", "pack", "cambrian/auth-bug-core", "--registry", "official")

    assert result.returncode != 0
    assert "Pack Install Plan" in result.stdout
    assert "--confirm-deps" in result.stdout
    assert not (tmp_path / ".cambrian" / "install" / "installed_packs.yaml").exists()


def test_install_pack_confirm_deps_installs_graph_and_pins_lock(tmp_path: Path) -> None:
    catalog = _write_registry(
        tmp_path,
        [
            {"pack_id": "auth-template", "namespace": "cambrian"},
            {
                "pack_id": "auth-bug-core",
                "namespace": "cambrian",
                "pack_kind": "lane",
                "dependencies": [{"pack_ref": "cambrian/auth-template"}],
            },
        ],
    )
    _sync_registry(tmp_path, catalog)

    result = _cli(tmp_path, "install", "pack", "cambrian/auth-bug-core", "--registry", "official", "--confirm-deps")

    assert result.returncode == 0, result.stderr
    assert "Pack dependency install completed." in result.stdout
    installed = _read_yaml(tmp_path / ".cambrian" / "install" / "installed_packs.yaml")
    assert {item["pack_id"] for item in installed["packs"]} == {"auth-template", "auth-bug-core"}
    lock = _read_yaml(tmp_path / ".cambrian" / "install" / "pack_lock.yaml")
    root = next(item for item in lock["packs"] if item["pack_id"] == "auth-bug-core")
    assert root["namespace"] == "cambrian"
    assert root["resolved_dependencies"] == ["cambrian/auth-template@0.1.0"]
    assert root["resolved_graph_ref"].startswith(".cambrian/install/graphs/")


def test_install_plan_does_not_mutate_source(tmp_path: Path) -> None:
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir(parents=True)
    source.write_text("def normalize_username(value):\n    return value\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")
    catalog = _write_registry(tmp_path, [{"pack_id": "auth-template", "namespace": "cambrian"}])
    _sync_registry(tmp_path, catalog)

    result = _cli(tmp_path, "install", "plan", "cambrian/auth-template", "--registry", "official")

    assert result.returncode == 0, result.stderr
    assert "Pack Install Plan" in result.stdout
    assert source.read_text(encoding="utf-8") == before
