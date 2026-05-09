"""Static pack registry pull과 registry-backed install 지원."""

from __future__ import annotations

import hashlib
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_catalog import PackCatalogEntry, PackFitAnalyzer
from engine.project_pack_install import (
    SCHEMA_VERSION,
    PackInstaller,
    _as_dict,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)

logger = logging.getLogger(__name__)

REGISTRY_SCHEMA_VERSION = "1.0"
TRUST_LEVELS = {"trusted", "local", "remote_static", "unknown", "untrusted"}


@dataclass
class PackRegistrySource:
    """등록된 pack registry source."""

    registry_id: str
    name: str
    source_ref: str
    source_kind: str
    trust_level: str
    added_at: str
    last_synced_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return asdict(self)


@dataclass
class PackRegistryIndex:
    """등록된 registry source 목록."""

    schema_version: str
    updated_at: str
    registries: list[PackRegistrySource]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "registries": [source.to_dict() for source in self.registries],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class SyncedRegistryPack:
    """registry cache에 저장된 pack 요약."""

    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    namespace: str | None
    description: str | None
    tags: list[str]
    maturity: str | None
    proof_status: str | None
    compatibility: dict[str, Any]
    known_limits: list[str]
    manifest_ref: str
    manifest_sha256: str | None
    registry_name: str
    registry_source_ref: str
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    trust_level: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return asdict(self)


@dataclass
class PackRegistryCache:
    """sync된 registry catalog cache."""

    schema_version: str
    synced_at: str
    registry_name: str
    registry_source_ref: str
    packs: list[SyncedRegistryPack]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return {
            "schema_version": self.schema_version,
            "synced_at": self.synced_at,
            "registry_name": self.registry_name,
            "registry_source_ref": self.registry_source_ref,
            "packs": [pack.to_dict() for pack in self.packs],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class PackRegistrySyncReport:
    """registry sync 결과."""

    schema_version: str
    sync_id: str
    generated_at: str
    registry_name: str
    registry_source_ref: str
    pack_count: int
    cache_ref: str | None
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return asdict(self)


def default_registry_dir(project_root: Path) -> Path:
    """registry state 기본 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "registries"


def default_registry_index_path(project_root: Path) -> Path:
    """registry source index 경로를 반환한다."""
    return default_registry_dir(project_root) / "registries.yaml"


def default_registry_cache_dir(project_root: Path) -> Path:
    """registry cache 디렉터리를 반환한다."""
    return default_registry_dir(project_root) / "cache"


def default_registry_syncs_dir(project_root: Path) -> Path:
    """registry sync report 디렉터리를 반환한다."""
    return default_registry_dir(project_root) / "syncs"


def default_registry_manifests_dir(project_root: Path) -> Path:
    """registry manifest cache 디렉터리를 반환한다."""
    return default_registry_dir(project_root) / "manifests"


class PackRegistryStore:
    """registry source index 저장소."""

    def load(self, path: Path) -> PackRegistryIndex:
        """registry source index를 읽는다."""
        target = Path(path).resolve()
        if not target.exists():
            return PackRegistryIndex(
                schema_version=REGISTRY_SCHEMA_VERSION,
                updated_at=_now(),
                registries=[],
            )
        payload = _load_yaml(target)
        sources = [
            _source_from_dict(item)
            for item in payload.get("registries", []) or []
            if isinstance(item, dict)
        ]
        return PackRegistryIndex(
            schema_version=str(payload.get("schema_version") or REGISTRY_SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _now()),
            registries=sources,
            warnings=_as_list(payload.get("warnings")),
            errors=_as_list(payload.get("errors")),
        )

    def save(self, path: Path, index: PackRegistryIndex) -> Path:
        """registry source index를 저장한다."""
        index.updated_at = _now()
        return _save_yaml(Path(path).resolve(), index.to_dict())

    def add(self, path: Path, source: PackRegistrySource) -> Path:
        """registry source를 추가하거나 같은 이름을 갱신한다."""
        index = self.load(path)
        replaced = False
        for idx, existing in enumerate(index.registries):
            if existing.name == source.name:
                index.registries[idx] = source
                replaced = True
                break
        if not replaced:
            index.registries.append(source)
        return self.save(path, index)

    def find(self, index: PackRegistryIndex, registry_name: str) -> PackRegistrySource:
        """registry 이름으로 source를 찾는다."""
        wanted = str(registry_name or "").strip()
        for source in index.registries:
            if source.name == wanted or source.registry_id == wanted:
                return source
        raise KeyError(wanted)


class PackRegistryFetcher:
    """static registry catalog와 manifest fetcher."""

    def fetch_catalog(self, source_ref: str) -> dict[str, Any]:
        """registry catalog를 dict로 가져온다."""
        content = self._fetch_bytes(source_ref, base_ref=None)
        try:
            payload = yaml.safe_load(content.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            logger.warning("registry catalog parse failed: %s (%s)", source_ref, exc)
            raise ValueError(f"registry catalog를 읽을 수 없습니다: {source_ref}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"registry catalog top level must be a mapping: {source_ref}")
        return payload

    def fetch_manifest(self, manifest_ref: str, base_ref: str | None = None) -> bytes:
        """manifest bytes를 가져온다."""
        return self._fetch_bytes(manifest_ref, base_ref=base_ref)

    def _fetch_bytes(self, ref: str, base_ref: str | None) -> bytes:
        """local/file/http ref에서 bytes를 읽는다."""
        resolved = _resolve_ref(ref, base_ref)
        parsed = urllib.parse.urlparse(resolved)
        if parsed.scheme in {"http", "https"}:
            try:
                with urllib.request.urlopen(resolved, timeout=10) as response:  # noqa: S310 - static catalog pull만 허용한다.
                    return response.read()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                logger.warning("registry fetch failed: %s (%s)", resolved, exc)
                raise ValueError(f"registry source를 가져올 수 없습니다: {resolved}") from exc
        path = _path_from_ref(resolved)
        if not path.exists():
            raise FileNotFoundError(f"registry ref not found: {path}")
        try:
            return path.read_bytes()
        except OSError as exc:
            logger.warning("registry local read failed: %s (%s)", path, exc)
            raise ValueError(f"registry ref를 읽을 수 없습니다: {path}") from exc


class PackRegistrySyncer:
    """registry source를 local cache로 동기화한다."""

    def sync(self, project_root: Path, registry_name: str) -> PackRegistrySyncReport:
        """등록된 registry를 fetch하고 cache를 저장한다."""
        root = Path(project_root).resolve()
        store = PackRegistryStore()
        index_path = default_registry_index_path(root)
        index = store.load(index_path)
        try:
            source = store.find(index, registry_name)
            payload = PackRegistryFetcher().fetch_catalog(source.source_ref)
            packs, warnings = _normalize_registry_catalog(payload, source)
            cache = PackRegistryCache(
                schema_version=REGISTRY_SCHEMA_VERSION,
                synced_at=_now(),
                registry_name=source.name,
                registry_source_ref=source.source_ref,
                packs=packs,
                warnings=warnings,
                errors=[],
            )
            cache_path = default_registry_cache_dir(root) / f"{_slug(source.name, 'registry')}.yaml"
            _save_yaml(cache_path, cache.to_dict())
            source.last_synced_at = cache.synced_at
            store.save(index_path, index)
            report = PackRegistrySyncReport(
                schema_version=REGISTRY_SCHEMA_VERSION,
                sync_id=f"sync-{_slug(source.name, 'registry')}-{_stamp()}",
                generated_at=_now(),
                registry_name=source.name,
                registry_source_ref=source.source_ref,
                pack_count=len(packs),
                cache_ref=_relative(cache_path, root),
                status="synced",
                warnings=warnings,
                errors=[],
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            logger.warning("registry sync blocked: %s", exc)
            report = PackRegistrySyncReport(
                schema_version=REGISTRY_SCHEMA_VERSION,
                sync_id=f"sync-{_slug(registry_name, 'registry')}-{_stamp()}",
                generated_at=_now(),
                registry_name=str(registry_name),
                registry_source_ref="",
                pack_count=0,
                cache_ref=None,
                status="failed",
                warnings=[],
                errors=[str(exc)],
            )
        save_registry_sync_report(root, report)
        return report


class PackRegistryResolver:
    """registry cache 검색과 pack resolve."""

    def search(
        self,
        project_root: Path,
        query: str | None = None,
        registry_name: str | None = None,
        kind: str | None = None,
    ) -> list[SyncedRegistryPack]:
        """sync된 registry pack을 검색한다."""
        packs = _load_cached_packs(Path(project_root).resolve(), registry_name=registry_name)
        needle = str(query or "").strip().lower()
        filtered: list[SyncedRegistryPack] = []
        for pack in packs:
            if kind and pack.pack_kind != kind:
                continue
            if needle and not _matches_query(pack, needle):
                continue
            filtered.append(pack)
        filtered.sort(key=_registry_sort_key, reverse=True)
        return filtered

    def resolve_pack(
        self,
        project_root: Path,
        pack_id: str,
        registry_name: str | None = None,
    ) -> SyncedRegistryPack:
        """pack id/name을 registry cache에서 찾는다."""
        wanted = str(pack_id or "").strip()
        namespace, wanted_id, wanted_version = _split_pack_ref(wanted)
        wanted_slug = _slug(wanted_id, "")
        matches = [
            pack
            for pack in _load_cached_packs(Path(project_root).resolve(), registry_name=registry_name)
            if (
                pack.pack_id == wanted_id
                or pack.pack_name == wanted_id
                or _slug(pack.pack_name, "") == wanted_slug
            )
            and (namespace is None or (pack.namespace or pack.registry_name) == namespace)
            and (wanted_version is None or pack.version == wanted_version)
        ]
        if not matches:
            raise KeyError(wanted)
        matches.sort(key=_registry_sort_key, reverse=True)
        return matches[0]


class RegistryPackInstaller:
    """registry cache의 pack을 manifest installer로 설치한다."""

    def install(
        self,
        project_root: Path,
        pack_id: str,
        registry_name: str,
        dry_run: bool = False,
        require_trusted: bool = False,
    ) -> tuple[SyncedRegistryPack, Path, Any]:
        """registry pack manifest를 cache한 뒤 기존 installer로 설치한다."""
        root = Path(project_root).resolve()
        pack = PackRegistryResolver().resolve_pack(root, pack_id, registry_name=registry_name)
        _ensure_registry_install_allowed(pack, require_trusted=require_trusted)
        manifest_bytes = PackRegistryFetcher().fetch_manifest(pack.manifest_ref, base_ref=pack.registry_source_ref)
        actual_sha = hashlib.sha256(manifest_bytes).hexdigest()
        if pack.manifest_sha256 and actual_sha.lower() != pack.manifest_sha256.lower():
            raise ValueError(
                f"registry manifest digest mismatch: expected {pack.manifest_sha256.lower()} actual {actual_sha}"
            )
        manifest_path = _write_manifest_cache(root, pack, manifest_bytes)
        source_kind = "remote_static_registry"
        installer_require_trusted = require_trusted and pack.trust_level != "local"
        plan = PackInstaller().install(
            root,
            manifest_path,
            dry_run=dry_run,
            source_kind_override=source_kind,
            source_ref_override=f"{pack.registry_name}:{pack.registry_source_ref}",
            expected_sha256=pack.manifest_sha256,
            require_trusted=installer_require_trusted,
            trust_level_override=pack.trust_level,
        )
        return pack, manifest_path, plan


def create_registry_source(name: str, source_ref: str, trust_level: str | None = None) -> PackRegistrySource:
    """CLI 입력에서 registry source 레코드를 만든다."""
    normalized_trust = _normalize_trust_level(trust_level) if trust_level else _default_trust_for_source(source_ref)
    source_kind = infer_source_kind(source_ref)
    return PackRegistrySource(
        registry_id=_slug(name, "registry"),
        name=str(name).strip(),
        source_ref=str(source_ref).strip(),
        source_kind=source_kind,
        trust_level=normalized_trust,
        added_at=_now(),
        warnings=[],
        errors=[],
    )


def infer_source_kind(source_ref: str) -> str:
    """source_ref의 종류를 추정한다."""
    parsed = urllib.parse.urlparse(str(source_ref))
    if parsed.scheme == "file":
        return "file_url"
    if parsed.scheme in {"http", "https"}:
        return "https_static"
    if str(source_ref).strip():
        return "local_path"
    return "unknown"


def save_registry_sync_report(project_root: Path, report: PackRegistrySyncReport) -> str:
    """registry sync report를 저장한다."""
    root = Path(project_root).resolve()
    path = default_registry_syncs_dir(root) / f"{_slug(report.sync_id, 'sync')}.yaml"
    report.saved_ref = _relative(path, root)
    _save_yaml(path, report.to_dict())
    return report.saved_ref


def render_registry_added(source: PackRegistrySource) -> str:
    """registry add 결과를 렌더링한다."""
    return "\n".join(
        [
            "Pack registry added.",
            "",
            "Name:",
            f"  {source.name}",
            "",
            "Source:",
            f"  {source.source_ref}",
            "",
            "Trust:",
            f"  {source.trust_level}",
            "",
            "Next:",
            f"  cambrian registry sync {source.name}",
        ]
    )


def render_registry_list(index: PackRegistryIndex) -> str:
    """registry list를 렌더링한다."""
    lines = ["Pack Registries", "==================================================", ""]
    if not index.registries:
        lines.append("none")
        return "\n".join(lines)
    for source in index.registries:
        lines.extend(
            [
                f"- {source.name}",
                f"  source_kind   : {source.source_kind}",
                f"  trust_level   : {source.trust_level}",
                f"  source_ref    : {source.source_ref}",
                f"  last_synced_at: {source.last_synced_at or 'never'}",
            ]
        )
    return "\n".join(lines)


def render_registry_sync(report: PackRegistrySyncReport) -> str:
    """registry sync report를 렌더링한다."""
    lines = [
        "Registry synced." if report.status == "synced" else "Registry sync failed.",
        "",
        "Registry:",
        f"  {report.registry_name}",
        "",
        "Packs:",
        f"  {report.pack_count}",
    ]
    if report.cache_ref:
        lines.extend(["", "Cache:", f"  {report.cache_ref}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def render_pack_search(packs: list[SyncedRegistryPack]) -> str:
    """pack search 결과를 렌더링한다."""
    lines = ["Pack Search", "==================================================", ""]
    if not packs:
        lines.append("none")
        return "\n".join(lines)
    for pack in packs:
        lines.extend(
            [
                f"- {pack.pack_id}",
                f"  source  : {pack.registry_name}",
                f"  ns      : {pack.namespace or pack.registry_name}",
                f"  kind    : {pack.pack_kind}",
                f"  version : {pack.version or 'none'}",
                f"  maturity: {pack.maturity or 'unknown'}",
                f"  proof   : {pack.proof_status or 'unknown'}",
                f"  manifest: {pack.manifest_ref}",
            ]
        )
    return "\n".join(lines)


def render_registry_pack_show(pack: SyncedRegistryPack, project_root: Path) -> str:
    """registry pack detail을 렌더링한다."""
    fit = PackFitAnalyzer().analyze(Path(project_root).resolve(), _entry_for_fit(pack))
    lines = [
        "Registry Pack",
        "==================================================",
        "",
        "Pack:",
        f"  id      : {pack.pack_id}",
        f"  ns      : {pack.namespace or pack.registry_name}",
        f"  name    : {pack.pack_name}",
        f"  kind    : {pack.pack_kind}",
        f"  version : {pack.version or 'none'}",
        f"  maturity: {pack.maturity or 'unknown'}",
        f"  proof   : {pack.proof_status or 'unknown'}",
        "",
        "Registry:",
        f"  name  : {pack.registry_name}",
        f"  source: {pack.registry_source_ref}",
        f"  trust : {pack.trust_level}",
        "",
        "Manifest:",
        f"  ref   : {pack.manifest_ref}",
        f"  sha256: {pack.manifest_sha256 or 'unknown'}",
        "",
        "Fit:",
        f"  status: {fit.fit_status}",
        f"  score : {fit.score:.2f}",
    ]
    if pack.known_limits:
        lines.extend(["", "Known limits:"])
        lines.extend([f"  - {item}" for item in pack.known_limits])
    if pack.dependencies:
        lines.extend(["", "Dependencies:"])
        for dependency in pack.dependencies:
            pack_ref = dependency.get("pack_ref") or dependency.get("ref") or "unknown"
            constraint = dependency.get("version_constraint")
            suffix = f" ({constraint})" if constraint else ""
            optional = " optional" if dependency.get("optional") else ""
            lines.append(f"  - {pack_ref}{suffix}{optional}")
    if pack.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in pack.warnings])
    lines.extend(
        [
            "",
            "Install:",
            f"  cambrian install pack {pack.pack_id} --registry {pack.registry_name}",
        ]
    )
    return "\n".join(lines)


def registry_payload(index: PackRegistryIndex) -> dict[str, Any]:
    """registry index JSON payload를 만든다."""
    return index.to_dict()


def pack_search_payload(packs: list[SyncedRegistryPack]) -> dict[str, Any]:
    """pack search JSON payload를 만든다."""
    return {"packs": [pack.to_dict() for pack in packs]}


def registry_pack_show_payload(pack: SyncedRegistryPack, project_root: Path) -> dict[str, Any]:
    """registry pack show JSON payload를 만든다."""
    fit = PackFitAnalyzer().analyze(Path(project_root).resolve(), _entry_for_fit(pack))
    return {"pack": pack.to_dict(), "fit": fit.to_dict()}


def _source_from_dict(payload: dict[str, Any]) -> PackRegistrySource:
    """dict를 registry source로 변환한다."""
    return PackRegistrySource(
        registry_id=str(payload.get("registry_id") or _slug(str(payload.get("name") or "registry"), "registry")),
        name=str(payload.get("name") or payload.get("registry_id") or "").strip(),
        source_ref=str(payload.get("source_ref") or "").strip(),
        source_kind=str(payload.get("source_kind") or "unknown"),
        trust_level=_normalize_trust_level(str(payload.get("trust_level") or "unknown")),
        added_at=str(payload.get("added_at") or _now()),
        last_synced_at=str(payload.get("last_synced_at")) if payload.get("last_synced_at") is not None else None,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _pack_from_dict(payload: dict[str, Any]) -> SyncedRegistryPack:
    """dict를 synced registry pack으로 변환한다."""
    return SyncedRegistryPack(
        pack_id=str(payload.get("pack_id") or "").strip(),
        pack_name=str(payload.get("pack_name") or payload.get("pack_id") or "").strip(),
        pack_kind=str(payload.get("pack_kind") or "").strip(),
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        namespace=str(payload.get("namespace")).strip() if payload.get("namespace") is not None else None,
        description=str(payload.get("description")) if payload.get("description") is not None else None,
        tags=_as_list(payload.get("tags")),
        maturity=str(payload.get("maturity")) if payload.get("maturity") is not None else None,
        proof_status=str(payload.get("proof_status")) if payload.get("proof_status") is not None else None,
        compatibility=_as_dict(payload.get("compatibility")),
        known_limits=_as_list(payload.get("known_limits") or payload.get("warnings")),
        manifest_ref=str(payload.get("manifest_ref") or payload.get("manifest_path") or payload.get("manifest_asset") or "").strip(),
        manifest_sha256=str(payload.get("manifest_sha256")).strip().lower()
        if payload.get("manifest_sha256") is not None
        else None,
        registry_name=str(payload.get("registry_name") or "").strip(),
        registry_source_ref=str(payload.get("registry_source_ref") or "").strip(),
        dependencies=[
            dict(item)
            for item in payload.get("dependencies", []) or []
            if isinstance(item, dict)
        ],
        trust_level=_normalize_trust_level(str(payload.get("trust_level") or "unknown")),
        warnings=_as_list(payload.get("warnings")),
    )


def _normalize_registry_catalog(payload: dict[str, Any], source: PackRegistrySource) -> tuple[list[SyncedRegistryPack], list[str]]:
    """web catalog JSON과 local catalog YAML을 같은 cache 구조로 정규화한다."""
    raw_entries = payload.get("packs")
    if not isinstance(raw_entries, list):
        raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("registry catalog must contain packs or entries list")
    warnings = _as_list(payload.get("warnings"))
    packs: list[SyncedRegistryPack] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            warnings.append("non-mapping pack entry ignored")
            continue
        manifest_ref = str(item.get("manifest_path") or item.get("manifest_asset") or item.get("manifest_ref") or "").strip()
        if not manifest_ref:
            warnings.append(f"pack {item.get('pack_id') or 'unknown'} skipped: manifest path missing")
            continue
        normalized = dict(item)
        normalized["manifest_ref"] = manifest_ref
        normalized["registry_name"] = source.name
        normalized["registry_source_ref"] = source.source_ref
        normalized["trust_level"] = normalized.get("trust_level") or source.trust_level
        try:
            pack = _pack_from_dict(normalized)
        except (TypeError, ValueError) as exc:
            logger.warning("registry pack normalize failed: %s", exc)
            warnings.append(f"pack entry skipped: {exc}")
            continue
        if not pack.pack_id or not pack.pack_kind:
            warnings.append("pack entry skipped: pack_id or pack_kind missing")
            continue
        packs.append(pack)
    return packs, warnings


def _load_registry_cache(path: Path) -> PackRegistryCache:
    """registry cache 파일을 읽는다."""
    payload = _load_yaml(path)
    packs = [
        _pack_from_dict({**item, "registry_name": payload.get("registry_name"), "registry_source_ref": payload.get("registry_source_ref")})
        for item in payload.get("packs", []) or []
        if isinstance(item, dict)
    ]
    return PackRegistryCache(
        schema_version=str(payload.get("schema_version") or REGISTRY_SCHEMA_VERSION),
        synced_at=str(payload.get("synced_at") or _now()),
        registry_name=str(payload.get("registry_name") or _slug(path.stem, "registry")),
        registry_source_ref=str(payload.get("registry_source_ref") or ""),
        packs=packs,
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def _load_cached_packs(root: Path, registry_name: str | None = None) -> list[SyncedRegistryPack]:
    """registry cache들에서 pack 목록을 읽는다."""
    cache_dir = default_registry_cache_dir(root)
    if not cache_dir.exists():
        return []
    paths = [cache_dir / f"{_slug(registry_name, 'registry')}.yaml"] if registry_name else sorted(cache_dir.glob("*.yaml"))
    packs: list[SyncedRegistryPack] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            cache = _load_registry_cache(path)
        except ValueError as exc:
            logger.warning("registry cache load skipped: %s (%s)", path, exc)
            continue
        packs.extend(cache.packs)
    return packs


def _write_manifest_cache(root: Path, pack: SyncedRegistryPack, manifest_bytes: bytes) -> Path:
    """registry에서 가져온 manifest bytes를 local cache에 저장한다."""
    version = _slug(pack.version or "unversioned", "unversioned")
    digest = hashlib.sha256(manifest_bytes).hexdigest()[:12]
    target = default_registry_manifests_dir(root) / f"{_slug(pack.pack_id, 'pack')}_{version}_{digest}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(manifest_bytes)
    return target


def _ensure_registry_install_allowed(pack: SyncedRegistryPack, require_trusted: bool) -> None:
    """registry trust 정책에 따라 install 가능 여부를 검증한다."""
    trust = _normalize_trust_level(pack.trust_level)
    if trust == "untrusted":
        raise ValueError(f"registry source is untrusted: {pack.registry_name}")
    if require_trusted and trust not in {"trusted", "local"}:
        raise ValueError(f"registry source is not trusted: {pack.registry_name} ({trust})")


def _resolve_ref(ref: str, base_ref: str | None) -> str:
    """상대 manifest ref를 catalog ref 기준으로 해석한다."""
    text = str(ref or "").strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme:
        return text
    if not base_ref:
        return text
    base = str(base_ref)
    base_parsed = urllib.parse.urlparse(base)
    if base_parsed.scheme in {"http", "https"}:
        base_for_join = _web_catalog_base(base, text)
        return urllib.parse.urljoin(base_for_join, text)
    if base_parsed.scheme == "file":
        base_path = _path_from_ref(base)
        return str((_web_catalog_base_path(base_path, text) / text).resolve())
    base_path = Path(base).resolve()
    return str((_web_catalog_base_path(base_path, text) / text).resolve())


def _web_catalog_base(base: str, ref: str) -> str:
    """web/assets/catalog.json의 assets/* ref를 web root 기준으로 해석한다."""
    parsed = urllib.parse.urlparse(base)
    path = parsed.path
    if path.endswith("/assets/catalog.json") and ref.startswith("assets/"):
        return base.rsplit("/assets/catalog.json", 1)[0] + "/"
    return base


def _web_catalog_base_path(base_path: Path, ref: str) -> Path:
    """local web catalog의 assets/* ref 기준 디렉터리를 계산한다."""
    if base_path.name == "catalog.json" and base_path.parent.name == "assets" and ref.startswith("assets/"):
        return base_path.parent.parent
    return base_path.parent


def _path_from_ref(ref: str) -> Path:
    """local path 또는 file URL을 Path로 변환한다."""
    parsed = urllib.parse.urlparse(str(ref))
    if parsed.scheme == "file":
        return Path(urllib.request.url2pathname(parsed.path)).resolve()
    return Path(str(ref)).resolve()


def _matches_query(pack: SyncedRegistryPack, needle: str) -> bool:
    """검색어가 pack id/name/tag/description에 매칭되는지 확인한다."""
    haystacks = [
        pack.pack_id,
        pack.pack_name,
        pack.description or "",
        " ".join(pack.tags),
        pack.namespace or pack.registry_name,
    ]
    return any(needle in str(value).lower() for value in haystacks)


def _registry_sort_key(pack: SyncedRegistryPack) -> tuple[int, int, str]:
    """maturity와 trust 기반 정렬 key를 만든다."""
    maturity_rank = {
        "recommended": 6,
        "verified": 5,
        "canary": 4,
        "candidate": 3,
        "seed": 2,
        "draft": 1,
        "retired": 0,
    }
    trust_rank = {"trusted": 4, "local": 3, "remote_static": 2, "unknown": 1, "untrusted": 0}
    return (
        maturity_rank.get(str(pack.maturity or "").lower(), 1),
        trust_rank.get(_normalize_trust_level(pack.trust_level), 1),
        pack.pack_id,
    )


def _split_pack_ref(raw: str) -> tuple[str | None, str, str | None]:
    """namespace/pack@version 문자열을 registry resolver용으로 나눈다."""
    text = str(raw or "").strip()
    version: str | None = None
    namespace: str | None = None
    if "@" in text:
        text, version = text.rsplit("@", 1)
        version = version.strip() or None
    if "/" in text:
        namespace, text = text.split("/", 1)
        namespace = namespace.strip() or None
    return namespace, text.strip(), version


def _entry_for_fit(pack: SyncedRegistryPack) -> PackCatalogEntry:
    """registry pack을 fit analyzer용 catalog entry로 변환한다."""
    return PackCatalogEntry(
        pack_id=pack.pack_id,
        pack_name=pack.pack_name,
        pack_kind=pack.pack_kind,
        version=pack.version,
        namespace=pack.namespace,
        manifest_path=pack.manifest_ref,
        description=pack.description,
        tags=list(pack.tags),
        compatibility=dict(pack.compatibility),
        maturity=pack.maturity,
        dependencies=list(pack.dependencies),
        manifest_sha256=pack.manifest_sha256,
        trust_level=pack.trust_level,
        proof_status=pack.proof_status,
        known_limits=list(pack.known_limits),
        warnings=list(pack.warnings),
    )


def _default_trust_for_source(source_ref: str) -> str:
    """source ref 기준 기본 trust level을 정한다."""
    kind = infer_source_kind(source_ref)
    if kind in {"local_path", "file_url"}:
        return "local"
    if kind == "https_static":
        return "remote_static"
    return "unknown"


def _normalize_trust_level(value: str | None) -> str:
    """trust level 문자열을 V1 허용값으로 정규화한다."""
    text = str(value or "").strip().lower()
    if text in TRUST_LEVELS:
        return text
    return "unknown"
