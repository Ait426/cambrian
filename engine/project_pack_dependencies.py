"""Pack namespace, version pinning, dependency graph 해석기."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_catalog import (
    PackCatalogEntry,
    PackCatalogResolver,
    load_default_catalog,
    local_catalog_source_ref,
    resolve_pack_catalog_path,
)
from engine.project_pack_install import (
    SCHEMA_VERSION,
    InstalledPackStore,
    PackInstaller,
    PackManifestLoader,
    default_installed_packs_path,
    _as_dict,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)
from engine.project_pack_registry import (
    PackRegistryFetcher,
    PackRegistryResolver,
    SyncedRegistryPack,
    default_registry_manifests_dir,
)
from engine.project_pack_trust import PackLockStore, default_pack_lock_path

logger = logging.getLogger(__name__)


@dataclass
class PackRef:
    """사람이 입력한 pack ref를 namespace/id/version으로 나눈 값."""

    namespace: str | None
    pack_id: str
    version: str | None
    raw: str

    def canonical(self) -> str:
        """표준 pack ref 문자열을 반환한다."""
        prefix = f"{self.namespace}/" if self.namespace else ""
        suffix = f"@{self.version}" if self.version else ""
        return f"{prefix}{self.pack_id}{suffix}"


@dataclass
class PackDependency:
    """pack manifest/catalog에 선언된 dependency."""

    pack_ref: str
    version_constraint: str | None = None
    optional: bool = False
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class ResolvedPackNode:
    """해석기가 선택한 pack graph node."""

    pack_ref: str
    namespace: str | None
    pack_id: str
    version: str | None
    registry_name: str | None
    manifest_ref: str | None
    manifest_sha256: str | None
    dependencies: list[str]
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_kind: str | None = None
    registry_source_ref: str | None = None
    trust_level: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackInstallGraph:
    """dependency를 반영한 pack install plan graph."""

    schema_version: str
    graph_id: str
    generated_at: str
    root_pack_ref: str
    nodes: list[ResolvedPackNode]
    install_order: list[str]
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    safe_to_install: bool = False
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "generated_at": self.generated_at,
            "root_pack_ref": self.root_pack_ref,
            "nodes": [node.to_dict() for node in self.nodes],
            "install_order": list(self.install_order),
            "conflicts": list(self.conflicts),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "safe_to_install": self.safe_to_install,
            "saved_ref": self.saved_ref,
        }


@dataclass
class GraphInstallResult:
    """dependency graph 설치 결과."""

    graph: PackInstallGraph
    installed_refs: list[str]
    skipped_refs: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "graph": self.graph.to_dict(),
            "installed_refs": list(self.installed_refs),
            "skipped_refs": list(self.skipped_refs),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class _Candidate:
    namespace: str
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    manifest_ref: str
    manifest_sha256: str | None
    source_kind: str
    registry_name: str | None
    registry_source_ref: str | None
    trust_level: str | None
    dependencies: list[PackDependency]
    source_ref: str | None

    def ref(self) -> str:
        suffix = f"@{self.version}" if self.version else ""
        return f"{self.namespace}/{self.pack_id}{suffix}"


class PackRefParser:
    """pack ref 문자열 파서."""

    def parse(self, raw: str) -> PackRef:
        """`namespace/pack@version` 형식을 파싱한다."""
        text = str(raw or "").strip()
        if not text:
            raise ValueError("pack ref is required")
        namespace: str | None = None
        version: str | None = None
        body = text
        if "@" in body:
            body, version = body.rsplit("@", 1)
            version = version.strip() or None
        if "/" in body:
            namespace, body = body.split("/", 1)
            namespace = namespace.strip() or None
        pack_id = body.strip()
        if not pack_id:
            raise ValueError(f"invalid pack ref: {raw}")
        return PackRef(namespace=namespace, pack_id=pack_id, version=version, raw=text)


class PackDependencyResolver:
    """local catalog와 synced registry cache를 대상으로 dependency graph를 만든다."""

    def resolve(
        self,
        project_root: Path,
        root_pack_ref: str,
        registry_name: str | None = None,
        version: str | None = None,
        include_deps: bool = True,
    ) -> PackInstallGraph:
        """root pack과 dependency를 결정적으로 해석한다."""
        root = Path(project_root).resolve()
        repo_root = Path(__file__).resolve().parents[1]
        parser = PackRefParser()
        root_ref = parser.parse(root_pack_ref)
        if version:
            root_ref.version = str(version)
        candidates = _collect_candidates(root, repo_root, registry_name=registry_name)
        nodes: dict[str, ResolvedPackNode] = {}
        order: list[str] = []
        conflicts: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []
        stack: list[str] = []

        def visit(ref: PackRef, constraint: str | None, preferred_registry: str | None, optional: bool = False) -> None:
            requested = ref.canonical()
            if requested in stack:
                cycle = " -> ".join([*stack, requested])
                conflicts.append(f"circular pack dependency detected: {cycle}")
                errors.append(f"circular dependency: {cycle}")
                return
            selected = _select_candidate(candidates, ref, constraint, preferred_registry)
            if selected is None:
                message = f"missing dependency: {requested}" if optional else f"missing required dependency: {requested}"
                if optional:
                    warnings.append(message)
                    node = ResolvedPackNode(
                        pack_ref=requested,
                        namespace=ref.namespace,
                        pack_id=ref.pack_id,
                        version=ref.version,
                        registry_name=preferred_registry,
                        manifest_ref=None,
                        manifest_sha256=None,
                        dependencies=[],
                        status="missing",
                        warnings=[message],
                        source_kind=None,
                    )
                    nodes[requested] = node
                    return
                conflicts.append(message)
                errors.append(message)
                return
            if isinstance(selected, str):
                conflicts.append(selected)
                errors.append(selected)
                return
            node_ref = selected.ref()
            existing = nodes.get(node_ref)
            if existing and existing.status in {"resolved", "already_installed"}:
                return
            stack.append(requested)
            installed_status = _installed_status(root, selected)
            deps = _dependencies_for_candidate(selected) if include_deps else []
            dependency_refs = [dependency.pack_ref for dependency in deps]
            node = ResolvedPackNode(
                pack_ref=node_ref,
                namespace=selected.namespace,
                pack_id=selected.pack_id,
                version=selected.version,
                registry_name=selected.registry_name,
                manifest_ref=selected.manifest_ref,
                manifest_sha256=selected.manifest_sha256,
                dependencies=dependency_refs,
                status=installed_status,
                source_kind=selected.source_kind,
                registry_source_ref=selected.registry_source_ref,
                trust_level=selected.trust_level,
            )
            if node.status == "conflict":
                message = f"installed version conflicts with requested pack: {node_ref}"
                node.errors.append(message)
                conflicts.append(message)
                errors.append(message)
            nodes[node_ref] = node
            for dependency in deps:
                dep_ref = parser.parse(dependency.pack_ref)
                dep_constraint = dependency.version_constraint or dep_ref.version
                dep_preferred_registry = selected.registry_name if not dep_ref.namespace else None
                visit(dep_ref, dep_constraint, dep_preferred_registry, optional=dependency.optional)
            stack.pop()
            if node_ref not in order:
                order.append(node_ref)

        visit(root_ref, root_ref.version, registry_name)
        for conflict in _version_conflicts(list(nodes.values())):
            conflicts.append(conflict)
            errors.append(conflict)
        graph = PackInstallGraph(
            schema_version=SCHEMA_VERSION,
            graph_id=f"graph-{_slug(root_pack_ref, 'pack')}-{_stamp()}",
            generated_at=_now(),
            root_pack_ref=root_ref.canonical(),
            nodes=list(nodes.values()),
            install_order=order,
            conflicts=_dedupe(conflicts),
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
            safe_to_install=not conflicts and not errors,
        )
        return graph


class PackInstallGraphStore:
    """install graph 저장소."""

    def save(self, graph: PackInstallGraph, path: Path) -> Path:
        """install graph를 YAML로 저장한다."""
        target = Path(path).resolve()
        graph.saved_ref = _relative(target, Path.cwd().resolve())
        return _save_yaml(target, graph.to_dict())

    def load(self, path: Path) -> PackInstallGraph:
        """install graph YAML을 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        return graph_from_dict(payload)


class PackDependencyGraphInstaller:
    """해석된 dependency graph를 순서대로 설치한다."""

    def install(
        self,
        project_root: Path,
        graph: PackInstallGraph,
        dry_run: bool = False,
        require_trusted: bool = False,
        graph_ref: str | None = None,
    ) -> GraphInstallResult:
        """graph install order에 따라 dependency를 먼저 설치한다."""
        root = Path(project_root).resolve()
        nodes = {node.pack_ref: node for node in graph.nodes}
        installed: list[str] = []
        skipped: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []
        if not graph.safe_to_install:
            return GraphInstallResult(graph=graph, installed_refs=[], skipped_refs=[], warnings=list(graph.warnings), errors=list(graph.errors))
        for ref in graph.install_order:
            node = nodes.get(ref)
            if node is None:
                continue
            if node.status == "already_installed":
                skipped.append(ref)
                continue
            try:
                self._install_node(root, node, dry_run=dry_run, require_trusted=require_trusted)
            except (FileNotFoundError, ValueError) as exc:
                logger.warning("dependency graph install blocked: %s (%s)", ref, exc)
                errors.append(f"{ref}: {exc}")
                break
            installed.append(ref)
        if not dry_run and not errors:
            _update_lockfile_graph(root, graph, graph_ref=graph_ref)
        return GraphInstallResult(
            graph=graph,
            installed_refs=installed,
            skipped_refs=skipped,
            warnings=_dedupe([*warnings, *graph.warnings]),
            errors=_dedupe(errors),
        )

    def _install_node(self, root: Path, node: ResolvedPackNode, dry_run: bool, require_trusted: bool) -> None:
        if node.registry_name and node.registry_name != "local":
            if not node.manifest_ref:
                raise ValueError("registry manifest ref missing")
            manifest_bytes = PackRegistryFetcher().fetch_manifest(node.manifest_ref, base_ref=node.registry_source_ref)
            actual_sha = hashlib.sha256(manifest_bytes).hexdigest()
            if node.manifest_sha256 and actual_sha.lower() != node.manifest_sha256.lower():
                raise ValueError(
                    f"registry manifest digest mismatch: expected {node.manifest_sha256.lower()} actual {actual_sha}"
                )
            manifest_path = _write_graph_manifest_cache(root, node, manifest_bytes)
            source_kind = "remote_static_registry"
            source_ref = f"{node.registry_name}:{node.registry_source_ref or ''}"
            installer_require_trusted = require_trusted and (node.trust_level or "unknown") != "local"
            PackInstaller().install(
                root,
                manifest_path,
                dry_run=dry_run,
                source_kind_override=source_kind,
                source_ref_override=source_ref,
                expected_sha256=node.manifest_sha256,
                require_trusted=installer_require_trusted,
                trust_level_override=node.trust_level,
            )
            return
        if not node.manifest_ref:
            raise ValueError("local manifest ref missing")
        manifest_path = Path(node.manifest_ref).resolve()
        PackInstaller().install(
            root,
            manifest_path,
            dry_run=dry_run,
            source_kind_override="local_catalog",
            source_ref_override=f"{node.registry_source_ref or 'packs/catalog.yaml'}#{node.pack_id}",
            expected_sha256=node.manifest_sha256,
            require_trusted=require_trusted,
            trust_level_override=node.trust_level,
        )


def default_install_graphs_dir(project_root: Path) -> Path:
    """install graph 기본 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "install" / "graphs"


def default_install_graph_path(project_root: Path, graph: PackInstallGraph) -> Path:
    """graph id에 맞는 저장 경로를 반환한다."""
    return default_install_graphs_dir(project_root) / f"{_slug(graph.graph_id, 'graph')}.yaml"


def save_install_graph(project_root: Path, graph: PackInstallGraph) -> str:
    """install graph를 저장하고 project-relative path를 반환한다."""
    root = Path(project_root).resolve()
    path = default_install_graph_path(root, graph)
    graph.saved_ref = _relative(path, root)
    PackInstallGraphStore().save(graph, path)
    return graph.saved_ref


def graph_from_dict(payload: dict[str, Any]) -> PackInstallGraph:
    """dict에서 PackInstallGraph를 복원한다."""
    nodes = [
        ResolvedPackNode(
            pack_ref=str(item.get("pack_ref") or ""),
            namespace=str(item.get("namespace")) if item.get("namespace") is not None else None,
            pack_id=str(item.get("pack_id") or ""),
            version=str(item.get("version")) if item.get("version") is not None else None,
            registry_name=str(item.get("registry_name")) if item.get("registry_name") is not None else None,
            manifest_ref=str(item.get("manifest_ref")) if item.get("manifest_ref") is not None else None,
            manifest_sha256=str(item.get("manifest_sha256")).lower() if item.get("manifest_sha256") is not None else None,
            dependencies=_as_list(item.get("dependencies")),
            status=str(item.get("status") or "resolved"),
            warnings=_as_list(item.get("warnings")),
            errors=_as_list(item.get("errors")),
            source_kind=str(item.get("source_kind")) if item.get("source_kind") is not None else None,
            registry_source_ref=str(item.get("registry_source_ref")) if item.get("registry_source_ref") is not None else None,
            trust_level=str(item.get("trust_level")) if item.get("trust_level") is not None else None,
        )
        for item in payload.get("nodes", []) or []
        if isinstance(item, dict)
    ]
    return PackInstallGraph(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        graph_id=str(payload.get("graph_id") or f"graph-{_stamp()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        root_pack_ref=str(payload.get("root_pack_ref") or ""),
        nodes=nodes,
        install_order=_as_list(payload.get("install_order")),
        conflicts=_as_list(payload.get("conflicts")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
        safe_to_install=bool(payload.get("safe_to_install")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else None,
    )


def render_install_graph(graph: PackInstallGraph) -> str:
    """install graph를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Install Plan",
        "==================================================",
        "",
        "Root:",
        f"  {graph.root_pack_ref}",
        "",
        "Install order:",
    ]
    if graph.install_order:
        for index, ref in enumerate(graph.install_order, start=1):
            node = next((item for item in graph.nodes if item.pack_ref == ref), None)
            status = f" ({node.status})" if node else ""
            lines.append(f"  {index}. {ref}{status}")
    else:
        lines.append("  none")
    dependencies = [node for node in graph.nodes if node.dependencies]
    if dependencies:
        lines.extend(["", "Dependencies:"])
        for node in dependencies:
            lines.append(f"  {node.pack_ref}: {', '.join(node.dependencies)}")
    if graph.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in graph.warnings])
    if graph.conflicts or graph.errors:
        lines.extend(["", "Conflicts:"])
        lines.extend([f"  - {item}" for item in _dedupe([*graph.conflicts, *graph.errors])])
    lines.extend(["", "Status:", f"  safe_to_install: {str(graph.safe_to_install).lower()}"])
    return "\n".join(lines)


def render_graph_install_result(result: GraphInstallResult) -> str:
    """graph 설치 결과를 렌더링한다."""
    lines = [
        "Pack dependency install completed.",
        "",
        "Installed:",
    ]
    lines.extend([f"  - {ref}" for ref in result.installed_refs] or ["  none"])
    if result.skipped_refs:
        lines.extend(["", "Already installed:"])
        lines.extend([f"  - {ref}" for ref in result.skipped_refs])
    if result.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in result.warnings])
    if result.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in result.errors])
    return "\n".join(lines)


def parse_dependencies(value: Any) -> list[PackDependency]:
    """manifest/catalog dependencies 값을 정규화한다."""
    dependencies: list[PackDependency] = []
    if not isinstance(value, list):
        return dependencies
    for item in value:
        if isinstance(item, str):
            dependencies.append(PackDependency(pack_ref=item))
            continue
        if not isinstance(item, dict):
            continue
        pack_ref = str(item.get("pack_ref") or item.get("ref") or "").strip()
        if not pack_ref:
            continue
        dependencies.append(
            PackDependency(
                pack_ref=pack_ref,
                version_constraint=str(item.get("version_constraint")).strip()
                if item.get("version_constraint") is not None
                else None,
                optional=bool(item.get("optional", False)),
                reason=str(item.get("reason")) if item.get("reason") is not None else None,
                warnings=_as_list(item.get("warnings")),
            )
        )
    return dependencies


def dependencies_to_dicts(dependencies: list[PackDependency]) -> list[dict[str, Any]]:
    """dependency list를 YAML/JSON용 dict list로 바꾼다."""
    return [dependency.to_dict() for dependency in dependencies]


def _collect_candidates(root: Path, repo_root: Path, registry_name: str | None) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    if registry_name:
        registry_packs = PackRegistryResolver().search(root, registry_name=registry_name)
        candidates.extend(_candidate_from_registry_pack(pack) for pack in registry_packs)
        candidates.extend(_local_candidates(repo_root, namespace_filter="local"))
        return candidates
    candidates.extend(_local_candidates(repo_root, namespace_filter=None))
    candidates.extend(_candidate_from_registry_pack(pack) for pack in PackRegistryResolver().search(root))
    return candidates


def _local_candidates(repo_root: Path, namespace_filter: str | None) -> list[_Candidate]:
    catalog_path = resolve_pack_catalog_path(repo_root=repo_root)
    catalog = load_default_catalog(repo_root)
    if catalog.errors:
        return []
    candidates: list[_Candidate] = []
    for entry in catalog.entries:
        namespace = getattr(entry, "namespace", None) or "local"
        if namespace_filter and namespace != namespace_filter:
            continue
        manifest_path = PackCatalogResolver().resolve_manifest_path(repo_root, entry, catalog_path=catalog_path)
        dependencies = parse_dependencies(getattr(entry, "dependencies", []) or [])
        if not dependencies:
            dependencies = _dependencies_from_manifest(manifest_path)
        candidates.append(
            _Candidate(
                namespace=namespace,
                pack_id=entry.pack_id,
                pack_name=entry.pack_name,
                pack_kind=entry.pack_kind,
                version=entry.version,
                manifest_ref=str(manifest_path.resolve()),
                manifest_sha256=entry.manifest_sha256,
                source_kind="local_catalog",
                registry_name="local",
                registry_source_ref=str(catalog_path),
                trust_level=entry.trust_level or "local",
                dependencies=dependencies,
                source_ref=local_catalog_source_ref(repo_root, entry),
            )
        )
    return candidates


def _candidate_from_registry_pack(pack: SyncedRegistryPack) -> _Candidate:
    namespace = getattr(pack, "namespace", None) or pack.registry_name or "unknown"
    dependencies = parse_dependencies(getattr(pack, "dependencies", []) or [])
    return _Candidate(
        namespace=namespace,
        pack_id=pack.pack_id,
        pack_name=pack.pack_name,
        pack_kind=pack.pack_kind,
        version=pack.version,
        manifest_ref=pack.manifest_ref,
        manifest_sha256=pack.manifest_sha256,
        source_kind="remote_static_registry",
        registry_name=pack.registry_name,
        registry_source_ref=pack.registry_source_ref,
        trust_level=pack.trust_level,
        dependencies=dependencies,
        source_ref=f"{pack.registry_name}:{pack.registry_source_ref}",
    )


def _dependencies_from_manifest(path: Path) -> list[PackDependency]:
    try:
        payload = _load_yaml(Path(path).resolve())
    except (FileNotFoundError, ValueError):
        return []
    return parse_dependencies(payload.get("dependencies"))


def _dependencies_for_candidate(candidate: _Candidate) -> list[PackDependency]:
    """candidate에 선언된 dependency를 manifest까지 확인해 반환한다."""
    if candidate.dependencies:
        return list(candidate.dependencies)
    if candidate.source_kind == "remote_static_registry":
        try:
            payload = PackRegistryFetcher().fetch_manifest(candidate.manifest_ref, base_ref=candidate.registry_source_ref)
            parsed = yaml.safe_load(payload.decode("utf-8")) or {}
            if isinstance(parsed, dict):
                return parse_dependencies(parsed.get("dependencies"))
        except (UnicodeDecodeError, ValueError, yaml.YAMLError, OSError) as exc:
            logger.warning("dependency manifest read skipped: %s", exc)
        return []
    return _dependencies_from_manifest(Path(candidate.manifest_ref))


def _select_candidate(
    candidates: list[_Candidate],
    ref: PackRef,
    constraint: str | None,
    preferred_registry: str | None,
) -> _Candidate | str | None:
    matches = [candidate for candidate in candidates if candidate.pack_id == ref.pack_id]
    if ref.namespace:
        matches = [candidate for candidate in matches if candidate.namespace == ref.namespace]
    elif preferred_registry:
        preferred = [
            candidate
            for candidate in matches
            if candidate.registry_name == preferred_registry or candidate.namespace == preferred_registry
        ]
        if preferred:
            matches = preferred
    else:
        namespaces = sorted({candidate.namespace for candidate in matches})
        if len(namespaces) > 1:
            rendered = ", ".join(f"{candidate.namespace}/{candidate.pack_id}" for candidate in matches)
            return f"pack id is ambiguous: {ref.pack_id}; matches: {rendered}"
    if not matches:
        return None
    version_constraint = constraint or ref.version
    matches = [candidate for candidate in matches if _satisfies(candidate.version, version_constraint)]
    if not matches:
        return f"version constraint not satisfied: {ref.canonical()} {version_constraint or ''}".strip()
    matches.sort(key=lambda candidate: (_version_key(candidate.version), candidate.namespace, candidate.pack_id), reverse=True)
    return matches[0]


def _installed_status(root: Path, candidate: _Candidate) -> str:
    index = InstalledPackStore().load(default_installed_packs_path(root))
    for record in index.packs:
        record_namespace = getattr(record, "namespace", None) or _namespace_from_source(record.source_ref) or "unknown"
        if record.pack_id == candidate.pack_id and record_namespace == candidate.namespace:
            if candidate.version and record.version and record.version != candidate.version:
                return "conflict"
            return "already_installed"
    return "resolved"


def _namespace_from_source(source_ref: str | None) -> str | None:
    text = str(source_ref or "")
    if text.startswith("packs/catalog.yaml"):
        return "local"
    if ":" in text:
        return text.split(":", 1)[0]
    return None


def _satisfies(version: str | None, constraint: str | None) -> bool:
    if not constraint:
        return True
    current = str(version or "0")
    text = str(constraint).strip()
    if text.startswith(">="):
        return _version_key(current) >= _version_key(text[2:].strip())
    return current == text


def _version_key(version: str | None) -> tuple[Any, ...]:
    parts: list[Any] = []
    for piece in str(version or "0").replace("-", ".").split("."):
        if piece.isdigit():
            parts.append(int(piece))
        else:
            parts.append(piece)
    return tuple(parts)


def _write_graph_manifest_cache(root: Path, node: ResolvedPackNode, manifest_bytes: bytes) -> Path:
    version = _slug(node.version or "unversioned", "unversioned")
    digest = hashlib.sha256(manifest_bytes).hexdigest()[:12]
    target = default_registry_manifests_dir(root) / f"{_slug(node.namespace, 'ns')}_{_slug(node.pack_id, 'pack')}_{version}_{digest}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(manifest_bytes)
    return target


def _update_lockfile_graph(root: Path, graph: PackInstallGraph, graph_ref: str | None) -> None:
    lock_path = default_pack_lock_path(root)
    store = PackLockStore()
    lockfile = store.load(lock_path)
    root_ref = graph.install_order[-1] if graph.install_order else graph.root_pack_ref
    dependency_refs = [ref for ref in graph.install_order if ref != root_ref]
    nodes = {node.pack_ref: node for node in graph.nodes}
    for entry in lockfile.packs:
        node_ref = _lock_ref(entry)
        node = nodes.get(node_ref) or _find_node_for_entry(graph, entry.pack_id)
        if node:
            entry.namespace = node.namespace
            if node.pack_ref == root_ref:
                entry.resolved_dependencies = dependency_refs
                entry.resolved_graph_ref = graph_ref
    store.save(lock_path, lockfile)


def _lock_ref(entry: Any) -> str:
    namespace = getattr(entry, "namespace", None)
    version = getattr(entry, "version", None)
    suffix = f"@{version}" if version else ""
    if namespace:
        return f"{namespace}/{entry.pack_id}{suffix}"
    return f"{entry.pack_id}{suffix}"


def _find_node_for_entry(graph: PackInstallGraph, pack_id: str) -> ResolvedPackNode | None:
    matches = [node for node in graph.nodes if node.pack_id == pack_id]
    return matches[0] if len(matches) == 1 else None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _version_conflicts(nodes: list[ResolvedPackNode]) -> list[str]:
    """같은 namespace/pack_id가 여러 version으로 resolve되면 충돌을 반환한다."""
    versions: dict[tuple[str | None, str], set[str]] = {}
    for node in nodes:
        if node.status == "missing":
            continue
        key = (node.namespace, node.pack_id)
        versions.setdefault(key, set()).add(node.version or "")
    conflicts: list[str] = []
    for (namespace, pack_id), resolved_versions in versions.items():
        if len(resolved_versions) > 1:
            ns = f"{namespace}/" if namespace else ""
            rendered = ", ".join(sorted(version or "none" for version in resolved_versions))
            conflicts.append(f"dependency version conflict: {ns}{pack_id} -> {rendered}")
    return conflicts
