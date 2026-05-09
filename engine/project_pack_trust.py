"""Pack manifest 무결성, trust policy, install lockfile."""

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
    default_pack_catalog_path,
    load_default_catalog,
)
from engine.project_pack_install import (
    SCHEMA_VERSION,
    InstalledPackRecord,
    InstalledPackStore,
    PackManifestLoader,
    default_agent_registry_path,
    default_benchmark_worksets_dir,
    default_install_dir,
    default_installed_packs_path,
    default_lane_playbook_path,
    default_team_presets_path,
    default_templates_path,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)

logger = logging.getLogger(__name__)


@dataclass
class PackIntegrity:
    """Manifest file hash 결과."""

    manifest_ref: str
    sha256: str
    size_bytes: int
    computed_at: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackTrustSummary:
    """Pack source trust와 integrity 요약."""

    source_kind: str | None
    source_ref: str | None
    trust_level: str
    verified: bool
    integrity: PackIntegrity | None
    summary: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["integrity"] = self.integrity.to_dict() if self.integrity else None
        return payload


@dataclass
class PackVerifyReport:
    """Pack verify report."""

    schema_version: str
    report_id: str
    generated_at: str
    pack_id: str | None
    pack_name: str | None
    target_kind: str
    manifest_ref: str | None
    expected_sha256: str | None
    actual_sha256: str | None
    manifest_exists: bool
    digest_matches: bool | None
    installed_artifacts_exist: bool | None
    trust_summary: PackTrustSummary | None
    status: str
    checked_artifacts: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["trust_summary"] = self.trust_summary.to_dict() if self.trust_summary else None
        return payload


@dataclass
class PackLockEntry:
    """Installed pack lockfile entry."""

    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    namespace: str | None
    installed_at: str | None
    updated_at: str | None
    source_kind: str | None
    source_ref: str | None
    trust_level: str
    manifest_ref: str
    manifest_sha256: str
    installed_artifacts: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    resolved_dependencies: list[str] = field(default_factory=list)
    resolved_graph_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackLockfile:
    """Install lockfile."""

    schema_version: str
    updated_at: str
    packs: list[PackLockEntry]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "packs": [entry.to_dict() for entry in self.packs],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def default_pack_lock_path(project_root: Path) -> Path:
    """pack lockfile 기본 경로를 반환한다."""
    return default_install_dir(project_root) / "pack_lock.yaml"


def default_pack_verifications_dir(project_root: Path) -> Path:
    """pack verification report 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "verifications"


class PackIntegrityHasher:
    """파일 SHA-256 hasher."""

    def hash_file(self, path: Path) -> PackIntegrity:
        """파일 digest와 크기를 계산한다."""
        target = Path(path).resolve()
        if not target.exists():
            return PackIntegrity(
                manifest_ref=str(target),
                sha256="",
                size_bytes=0,
                computed_at=_now(),
                errors=[f"manifest not found: {target}"],
            )
        try:
            digest = hashlib.sha256()
            size = 0
            with target.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    digest.update(chunk)
        except OSError as exc:
            logger.warning("pack hash failed: %s (%s)", target, exc)
            return PackIntegrity(
                manifest_ref=str(target),
                sha256="",
                size_bytes=0,
                computed_at=_now(),
                errors=[f"manifest hash failed: {exc}"],
            )
        return PackIntegrity(
            manifest_ref=str(target),
            sha256=digest.hexdigest(),
            size_bytes=size,
            computed_at=_now(),
        )


class PackTrustPolicy:
    """V1 source trust classifier."""

    def classify_source(
        self,
        source_kind: str | None,
        source_ref: str | None,
        trust_level_override: str | None = None,
        integrity: PackIntegrity | None = None,
    ) -> PackTrustSummary:
        """source_kind와 optional override로 trust level을 분류한다."""
        override = str(trust_level_override or "").strip().lower()
        if override:
            trust_level = override
        else:
            kind = str(source_kind or "").strip()
            if kind == "local_seed":
                trust_level = "trusted"
            elif kind == "local_catalog":
                trust_level = "local"
            elif kind == "local_file":
                trust_level = "local"
            elif kind == "remote_registry_future":
                trust_level = "unknown"
            elif kind == "untrusted":
                trust_level = "untrusted"
            else:
                trust_level = "unknown"
        warnings: list[str] = []
        errors: list[str] = []
        if trust_level == "unknown":
            warnings.append("source trust is unknown")
        if trust_level == "untrusted":
            errors.append("source is marked untrusted")
        if integrity and integrity.errors:
            errors.extend(integrity.errors)
        verified = bool(integrity and integrity.sha256 and not integrity.errors)
        return PackTrustSummary(
            source_kind=source_kind,
            source_ref=source_ref,
            trust_level=trust_level,
            verified=verified,
            integrity=integrity,
            summary=f"{trust_level} source; integrity {'verified' if verified else 'not verified'}",
            warnings=warnings,
            errors=errors,
        )


class PackVerifier:
    """Pack manifest와 installed pack verifier."""

    def verify_manifest(self, manifest_path: Path, expected_sha256: str | None = None) -> PackVerifyReport:
        """local manifest file의 digest를 검증한다."""
        target = Path(manifest_path).resolve()
        integrity = PackIntegrityHasher().hash_file(target)
        manifest_exists = target.exists()
        actual = integrity.sha256 or None
        expected = str(expected_sha256).lower() if expected_sha256 else None
        digest_matches = None if expected is None else expected == actual
        warnings = list(integrity.warnings)
        errors = list(integrity.errors)
        if expected is not None and not digest_matches:
            errors.append(f"manifest digest mismatch: expected {expected} actual {actual or 'missing'}")
        pack_id = None
        pack_name = None
        if manifest_exists:
            try:
                manifest = PackManifestLoader().load(target)
                pack_id = manifest.pack_id
                pack_name = manifest.pack_name
            except (OSError, ValueError, yaml.YAMLError) as exc:
                errors.append(f"manifest load failed: {exc}")
        trust = PackTrustPolicy().classify_source("local_file", str(target), integrity=integrity)
        status = _status_from(warnings, errors)
        return PackVerifyReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"verify-manifest-{_slug(pack_id or target.stem)}-{_stamp()}",
            generated_at=_now(),
            pack_id=pack_id,
            pack_name=pack_name,
            target_kind="manifest_file",
            manifest_ref=str(target),
            expected_sha256=expected,
            actual_sha256=actual,
            manifest_exists=manifest_exists,
            digest_matches=digest_matches,
            installed_artifacts_exist=None,
            trust_summary=trust,
            status=status,
            checked_artifacts={},
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    def verify_catalog_pack(self, repo_root: Path, pack_ref: str) -> PackVerifyReport:
        """local catalog pack의 manifest digest와 trust marker를 검증한다."""
        repo = Path(repo_root).resolve()
        catalog = load_default_catalog(repo)
        entry = PackCatalogResolver().find_entry(catalog, pack_ref)
        manifest_path = PackCatalogResolver().resolve_manifest_path(repo, entry)
        report = self.verify_manifest(manifest_path, expected_sha256=entry.manifest_sha256)
        trust = PackTrustPolicy().classify_source(
            "local_catalog",
            f"{_relative(default_pack_catalog_path(repo), repo)}#{entry.pack_id}",
            trust_level_override=entry.trust_level,
            integrity=PackIntegrityHasher().hash_file(manifest_path),
        )
        warnings = [*report.warnings, *trust.warnings]
        errors = [*report.errors, *trust.errors]
        return PackVerifyReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"verify-catalog-{_slug(entry.pack_id)}-{_stamp()}",
            generated_at=_now(),
            pack_id=entry.pack_id,
            pack_name=entry.pack_name,
            target_kind="catalog_pack",
            manifest_ref=_relative(manifest_path, repo),
            expected_sha256=entry.manifest_sha256,
            actual_sha256=report.actual_sha256,
            manifest_exists=report.manifest_exists,
            digest_matches=report.digest_matches,
            installed_artifacts_exist=None,
            trust_summary=trust,
            status=_status_from(warnings, errors),
            checked_artifacts={},
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    def verify_installed_pack(self, project_root: Path, pack_id: str) -> PackVerifyReport:
        """설치된 pack의 manifest copy와 artifact refs를 검증한다."""
        root = Path(project_root).resolve()
        store = InstalledPackStore()
        index = store.load(default_installed_packs_path(root))
        record = store.find(index, pack_id)
        manifest_ref = record.latest_manifest_ref or record.manifest_ref
        manifest_path = root / manifest_ref if manifest_ref else None
        lock = PackLockStore().load(default_pack_lock_path(root))
        lock_entry = _find_lock_entry(lock, record.pack_id)
        expected = record.manifest_sha256 or (lock_entry.manifest_sha256 if lock_entry else None)
        warnings: list[str] = []
        errors: list[str] = []
        if not record.manifest_sha256:
            warnings.append("missing recorded manifest digest")
        if not expected:
            warnings.append("missing expected manifest digest")
        if lock_entry is None:
            warnings.append("missing pack lock entry")
        manifest_exists = bool(manifest_path and manifest_path.exists())
        actual = None
        digest_matches: bool | None = None
        integrity: PackIntegrity | None = None
        if manifest_path:
            integrity = PackIntegrityHasher().hash_file(manifest_path)
            actual = integrity.sha256 or None
            errors.extend(integrity.errors)
            digest_matches = None if not expected else str(expected).lower() == actual
            if expected and not digest_matches:
                errors.append(f"installed manifest digest mismatch: expected {str(expected).lower()} actual {actual or 'missing'}")
        else:
            errors.append("installed manifest ref missing")
        artifacts = _check_installed_artifacts(root, record)
        installed_artifacts_exist = bool(artifacts.get("all_exist"))
        if artifacts.get("errors"):
            errors.extend(artifacts["errors"])
        if artifacts.get("warnings"):
            warnings.extend(artifacts["warnings"])
        trust = PackTrustPolicy().classify_source(
            record.source_kind,
            record.source_ref,
            trust_level_override=record.trust_level,
            integrity=integrity,
        )
        warnings.extend(trust.warnings)
        errors.extend(trust.errors)
        return PackVerifyReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"verify-installed-{_slug(record.pack_id)}-{_stamp()}",
            generated_at=_now(),
            pack_id=record.pack_id,
            pack_name=record.pack_name,
            target_kind="installed_pack",
            manifest_ref=manifest_ref,
            expected_sha256=str(expected).lower() if expected else None,
            actual_sha256=actual,
            manifest_exists=manifest_exists,
            digest_matches=digest_matches,
            installed_artifacts_exist=installed_artifacts_exist,
            trust_summary=trust,
            status=_status_from(warnings, errors),
            checked_artifacts=artifacts,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    def verify_all_installed(self, project_root: Path) -> list[PackVerifyReport]:
        """설치된 모든 pack을 검증한다."""
        root = Path(project_root).resolve()
        index = InstalledPackStore().load(default_installed_packs_path(root))
        return [self.verify_installed_pack(root, record.pack_id) for record in index.packs]


class PackLockStore:
    """pack_lock.yaml 저장소."""

    def load(self, path: Path) -> PackLockfile:
        """lockfile을 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return PackLockfile(schema_version=SCHEMA_VERSION, updated_at=_now(), packs=[])
        payload = _load_yaml(target)
        return PackLockfile(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _now()),
            packs=[
                _lock_entry_from_dict(item)
                for item in payload.get("packs", []) or []
                if isinstance(item, dict)
            ],
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, path: Path, lockfile: PackLockfile) -> Path:
        """lockfile을 저장한다."""
        lockfile.updated_at = _now()
        return _save_yaml(Path(path).resolve(), lockfile.to_dict())

    def upsert(self, path: Path, entry: PackLockEntry) -> Path:
        """lock entry를 추가하거나 갱신한다."""
        target = Path(path).resolve()
        lockfile = self.load(target)
        for index, existing in enumerate(lockfile.packs):
            if existing.pack_id == entry.pack_id and (not existing.namespace or not entry.namespace or existing.namespace == entry.namespace):
                lockfile.packs[index] = entry
                return self.save(target, lockfile)
        lockfile.packs.append(entry)
        return self.save(target, lockfile)


def lock_entry_from_record(record: InstalledPackRecord) -> PackLockEntry:
    """InstalledPackRecord에서 lock entry를 만든다."""
    return PackLockEntry(
        pack_id=record.pack_id,
        pack_name=record.pack_name,
        pack_kind=record.pack_kind,
        version=record.version,
        namespace=record.namespace,
        installed_at=record.installed_at,
        updated_at=record.updated_at,
        source_kind=record.source_kind,
        source_ref=record.source_ref,
        trust_level=record.trust_level or "unknown",
        manifest_ref=record.latest_manifest_ref or record.manifest_ref or "",
        manifest_sha256=record.manifest_sha256 or record.manifest_digest or "",
        installed_artifacts=dict(record.installed_artifacts),
        warnings=list(record.warnings),
        resolved_dependencies=list(record.resolved_dependencies),
        resolved_graph_ref=record.resolved_graph_ref,
    )


def save_pack_verification(project_root: Path, report: PackVerifyReport) -> str:
    """verification report를 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    pack_id = report.pack_id or "manifest"
    path = default_pack_verifications_dir(root) / f"verify_{_slug(pack_id)}_{_stamp()}.yaml"
    report.saved_ref = _relative(path, root)
    _save_yaml(path, report.to_dict())
    return report.saved_ref


def render_pack_verify(report: PackVerifyReport) -> str:
    """pack verify report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Verify",
        "==================================================",
        "",
        "Target:",
        f"  kind : {report.target_kind}",
        f"  pack : {report.pack_id or 'unknown'}",
        "",
        "Manifest:",
        f"  {report.manifest_ref or 'missing'}",
        "",
        "SHA-256:",
        f"  expected: {report.expected_sha256 or 'none'}",
        f"  actual  : {report.actual_sha256 or 'none'}",
        f"  matches : {report.digest_matches if report.digest_matches is not None else 'n/a'}",
        "",
        "Trust:",
        f"  {report.trust_summary.summary if report.trust_summary else 'unknown'}",
        "",
        "Status:",
        f"  {report.status}",
    ]
    if report.checked_artifacts:
        lines.extend(["", "Artifacts:"])
        for key, value in report.checked_artifacts.items():
            if key in {"warnings", "errors", "all_exist"}:
                continue
            lines.append(f"  {key}: {value}")
    if report.saved_ref:
        lines.extend(["", "Saved:", f"  {report.saved_ref}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def render_installed_verify_reports(reports: list[PackVerifyReport]) -> str:
    """installed pack verification 목록을 렌더링한다."""
    lines = ["Installed Pack Verification", "==================================================", ""]
    if not reports:
        lines.append("No installed packs.")
        return "\n".join(lines)
    for report in reports:
        lines.extend(
            [
                f"{report.pack_id}:",
                f"  manifest copy   : {'ok' if report.manifest_exists else 'missing'}",
                f"  manifest digest : {'ok' if report.digest_matches else 'warning' if report.digest_matches is None else 'failed'}",
                f"  artifacts       : {'ok' if report.installed_artifacts_exist else 'failed'}",
                f"  trust           : {report.trust_summary.trust_level if report.trust_summary else 'unknown'}",
                f"  status          : {report.status}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _check_installed_artifacts(root: Path, record: InstalledPackRecord) -> dict[str, Any]:
    artifacts = record.installed_artifacts
    result: dict[str, Any] = {
        "agents": [],
        "teams": [],
        "templates": [],
        "benchmarks": [],
        "lane": None,
        "warnings": [],
        "errors": [],
    }
    agent_ids = _existing_values(default_agent_registry_path(root), "agents", ["agent_id"])
    team_names = _existing_values(default_team_presets_path(root), "teams", ["name", "team_id"])
    template_names = _existing_values(default_templates_path(root), "templates", ["name", "template_id"])
    workset_names = _existing_worksets(root)

    for agent in artifacts.get("agents", []) or []:
        _append_check(result, "agents", str(agent), str(agent) in agent_ids)
    for team in artifacts.get("teams", []) or []:
        _append_check(result, "teams", str(team), str(team) in team_names)
    for template in artifacts.get("templates", []) or []:
        _append_check(result, "templates", str(template), str(template) in template_names)
    for benchmark in artifacts.get("benchmarks", []) or []:
        _append_check(result, "benchmarks", str(benchmark), str(benchmark) in workset_names)

    lane_id = artifacts.get("lane")
    if lane_id:
        lane = _load_yaml(default_lane_playbook_path(root))
        installed = lane.get("installed_lane_packs", []) if isinstance(lane.get("installed_lane_packs"), list) else []
        ok = any(isinstance(item, dict) and item.get("pack_id") == record.pack_id for item in installed)
        result["lane"] = {"name": lane_id, "exists": ok}
        if not ok:
            result["errors"].append(f"missing lane registration: {lane_id}")

    result["all_exist"] = not result["errors"]
    return result


def _append_check(result: dict[str, Any], key: str, name: str, ok: bool) -> None:
    result[key].append({"name": name, "exists": ok})
    if not ok:
        result["errors"].append(f"missing {key[:-1]} ref: {name}")


def _existing_values(path: Path, list_key: str, keys: list[str]) -> set[str]:
    payload = _load_yaml(path)
    values: set[str] = set()
    for item in payload.get(list_key, []) or []:
        if not isinstance(item, dict):
            continue
        for key in keys:
            if item.get(key):
                values.add(str(item.get(key)))
    return values


def _existing_worksets(root: Path) -> set[str]:
    values: set[str] = set()
    for path in default_benchmark_worksets_dir(root).glob("workset_*.yaml"):
        payload = _load_yaml(path)
        for key in ("name", "workset_id"):
            if payload.get(key):
                values.add(str(payload.get(key)))
    return values


def _find_lock_entry(lockfile: PackLockfile, pack_id: str) -> PackLockEntry | None:
    for entry in lockfile.packs:
        if entry.pack_id == pack_id:
            return entry
    return None


def _lock_entry_from_dict(payload: dict[str, Any]) -> PackLockEntry:
    return PackLockEntry(
        pack_id=str(payload.get("pack_id") or ""),
        pack_name=str(payload.get("pack_name") or ""),
        pack_kind=str(payload.get("pack_kind") or ""),
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        installed_at=str(payload.get("installed_at")) if payload.get("installed_at") is not None else None,
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        source_ref=str(payload.get("source_ref")) if payload.get("source_ref") is not None else None,
        trust_level=str(payload.get("trust_level") or "unknown"),
        manifest_ref=str(payload.get("manifest_ref") or ""),
        manifest_sha256=str(payload.get("manifest_sha256") or "").lower(),
        installed_artifacts=dict(payload.get("installed_artifacts")) if isinstance(payload.get("installed_artifacts"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        resolved_dependencies=[str(item) for item in payload.get("resolved_dependencies", []) if item],
        resolved_graph_ref=str(payload.get("resolved_graph_ref")) if payload.get("resolved_graph_ref") is not None else None,
    )


def _status_from(warnings: list[str], errors: list[str]) -> str:
    if errors:
        return "failed"
    if warnings:
        return "warning"
    return "verified"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
