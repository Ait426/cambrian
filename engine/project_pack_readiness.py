"""Pack fit doctor와 현재 프로젝트 readiness gate."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_activation import current_active_pack
from engine.project_pack_catalog import (
    PackCatalogEntry,
    PackCatalogResolver,
    default_pack_catalog_path,
    load_default_catalog,
    manifest_for_entry,
)
from engine.project_pack_install import (
    SCHEMA_VERSION,
    InstalledPackRecord,
    InstalledPackStore,
    PackManifest,
    PackManifestLoader,
    default_installed_packs_path,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)
from engine.project_pack_registry import PackRegistryResolver, SyncedRegistryPack
from engine.project_pack_trust import PackVerifier

logger = logging.getLogger(__name__)


@dataclass
class PackReadinessCheck:
    """Readiness를 구성하는 단일 check."""

    check_id: str
    title: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        return asdict(self)


@dataclass
class PackReadinessReport:
    """Pack fit doctor report."""

    schema_version: str
    report_id: str
    generated_at: str
    pack_ref: str | None
    pack_id: str | None
    pack_name: str | None
    pack_kind: str | None
    namespace: str | None
    version: str | None
    source_kind: str | None
    source_ref: str | None
    installed: bool
    active: bool
    trusted: bool | None
    verified: bool | None
    readiness_status: str
    fit_status: str | None
    lane_id: str | None
    lane_label: str | None
    default_team: str | None
    default_template: str | None
    default_workset: str | None
    checks: list[PackReadinessCheck]
    recommended_request_examples: list[str]
    next_actions: list[str]
    source_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """dict로 변환한다."""
        payload = asdict(self)
        payload["checks"] = [check.to_dict() for check in self.checks]
        return payload


def default_readiness_dir(project_root: Path) -> Path:
    """readiness report 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "readiness"


def default_readiness_path(project_root: Path, report: PackReadinessReport) -> Path:
    """readiness report 기본 저장 경로를 반환한다."""
    pack_id = report.pack_id or "no-pack"
    return default_readiness_dir(project_root) / f"readiness_{_slug(pack_id, 'pack')}_{_stamp()}.yaml"


def latest_readiness_path(project_root: Path) -> Path:
    """latest readiness report 경로를 반환한다."""
    return default_readiness_dir(project_root) / "latest.yaml"


class PackReadinessStore:
    """Pack readiness report 저장소."""

    def save(self, report: PackReadinessReport, path: Path) -> Path:
        """report를 저장하고 latest pointer를 갱신한다."""
        target = Path(path).resolve()
        project_root = _project_root_from_report_path(target)
        report.saved_ref = _relative(target, project_root)
        _save_yaml(target, report.to_dict())
        if target.name != "latest.yaml":
            latest = latest_readiness_path(project_root)
            latest_payload = report.to_dict()
            latest_payload["saved_ref"] = report.saved_ref
            _save_yaml(latest, latest_payload)
        return target

    def load(self, path: Path) -> PackReadinessReport:
        """저장된 report를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if not payload:
            raise FileNotFoundError(f"readiness report not found: {path}")
        return _report_from_dict(payload)

    def list(self, reports_dir: Path) -> list[PackReadinessReport]:
        """저장된 readiness report 목록을 반환한다."""
        directory = Path(reports_dir).resolve()
        if not directory.exists():
            return []
        reports: list[PackReadinessReport] = []
        for path in sorted(directory.glob("readiness_*.yaml")):
            try:
                reports.append(self.load(path))
            except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
                logger.warning("readiness report load skipped: %s (%s)", path, exc)
        return reports


class PackReadinessBuilder:
    """Pack metadata, 설치 상태, 프로젝트 신호를 묶어 readiness를 계산한다."""

    def build(
        self,
        project_root: Path,
        pack_ref: str | None = None,
        registry_name: str | None = None,
    ) -> PackReadinessReport:
        """pack readiness report를 만든다."""
        root = Path(project_root).resolve()
        active_context = current_active_pack(root)
        active = False
        requested_ref = str(pack_ref).strip() if pack_ref else None
        if not requested_ref and active_context is not None:
            requested_ref = active_context.pack_ref or active_context.pack_id
            active = True
        if not requested_ref:
            return _no_active_report()

        checks: list[PackReadinessCheck] = []
        warnings: list[str] = []
        errors: list[str] = []
        source_refs: dict[str, Any] = {}
        record = _find_installed_record(root, requested_ref)
        installed = record is not None and record.status != "uninstalled"
        manifest: PackManifest | None = None
        catalog_entry: PackCatalogEntry | None = None
        registry_pack: SyncedRegistryPack | None = None
        trusted: bool | None = None
        verified: bool | None = None

        if installed and record is not None:
            active = active or _active_matches(active_context, record)
            manifest = _load_manifest_from_record(root, record)
            source_refs["installed_pack_ref"] = f".cambrian/install/installed_packs.yaml#{_record_ref(record)}"
            if record.latest_manifest_ref or record.manifest_ref:
                source_refs["manifest_ref"] = record.latest_manifest_ref or record.manifest_ref
        else:
            if registry_name:
                try:
                    registry_pack = PackRegistryResolver().resolve_pack(root, requested_ref, registry_name=registry_name)
                except KeyError as exc:
                    raise KeyError(f"pack not found in registry {registry_name}: {requested_ref}") from exc
            if registry_pack is None:
                catalog_root = _catalog_root(root)
                catalog = load_default_catalog(catalog_root)
                try:
                    catalog_entry = PackCatalogResolver().find_entry(catalog, _pack_id_from_ref(requested_ref))
                    manifest_path, manifest = manifest_for_entry(catalog_root, catalog_entry)
                    source_refs["catalog_ref"] = _relative(default_pack_catalog_path(catalog_root), catalog_root)
                    source_refs["manifest_ref"] = _relative(manifest_path, catalog_root)
                except (KeyError, FileNotFoundError, ValueError) as exc:
                    raise KeyError(f"pack not found: {requested_ref}") from exc

        metadata = _metadata(record, manifest, catalog_entry, registry_pack, requested_ref)
        checks.append(
            _check(
                "pack_resolved",
                "Pack resolved",
                "pass",
                f"resolved {metadata['pack_id'] or requested_ref}",
                details=[metadata["source_kind"] or "unknown source"],
            )
        )

        if installed:
            checks.append(_check("installed_state", "Installed state", "pass", "pack is installed"))
        else:
            action = _install_command(metadata, registry_name)
            checks.append(
                _check(
                    "installed_state",
                    "Installed state",
                    "fail",
                    "pack is not installed in this project",
                    next_actions=[action],
                    errors=["install is required before activation or first job"],
                )
            )

        if installed and record is not None:
            verify_report = PackVerifier().verify_installed_pack(root, record.pack_id)
            verified = verify_report.status != "failed"
            trusted = bool(verify_report.trust_summary and verify_report.trust_summary.trust_level in {"trusted", "local"})
            if verify_report.status == "failed":
                checks.append(
                    _check(
                        "integrity_state",
                        "Integrity and lockfile",
                        "fail",
                        "installed pack integrity failed",
                        details=[verify_report.manifest_ref or "missing manifest"],
                        errors=list(verify_report.errors),
                        warnings=list(verify_report.warnings),
                        next_actions=[f"cambrian install verify {record.pack_id}"],
                    )
                )
            else:
                status = "warn" if verify_report.status == "warning" else "pass"
                checks.append(
                    _check(
                        "integrity_state",
                        "Integrity and lockfile",
                        status,
                        "installed manifest digest and lockfile were checked",
                        details=[f"verify status: {verify_report.status}"],
                        warnings=list(verify_report.warnings),
                    )
                )
            checks.append(_artifact_check(verify_report))
        else:
            trusted = _preinstall_trusted(catalog_entry, registry_pack)
            verified = bool(_preinstall_sha(catalog_entry, registry_pack))
            checks.append(
                _check(
                    "integrity_state",
                    "Integrity and lockfile",
                    "skip" if verified else "warn",
                    "preinstall manifest digest is available" if verified else "preinstall digest is missing or not verified yet",
                    warnings=[] if verified else ["install will verify digest when available"],
                )
            )
            checks.append(
                _check(
                    "artifact_refs",
                    "Installed artifact refs",
                    "skip",
                    "artifact refs can be checked after install",
                    next_actions=[_install_command(metadata, registry_name)],
                )
            )

        signals = _project_signals(root)
        compat = _compatibility(metadata, manifest, catalog_entry, registry_pack)
        stack_check = _stack_check(signals, compat)
        test_check = _test_check(signals, compat)
        lane_check = _lane_check(signals, compat, metadata)
        checks.extend([stack_check, test_check, lane_check])
        checks.append(_first_job_check(metadata, installed))
        checks.append(_proof_check(root, metadata))
        checks.append(_known_limits_check(metadata, catalog_entry, registry_pack, manifest))

        warnings.extend(_dedupe([item for check in checks for item in check.warnings]))
        errors.extend(_dedupe([item for check in checks for item in check.errors]))
        readiness_status = _readiness_status(checks, installed)
        fit_status = _fit_status(stack_check, test_check, lane_check)
        next_actions = _next_actions(metadata, readiness_status, installed, registry_name)
        return PackReadinessReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"readiness-{_slug(metadata['pack_id'], 'pack')}-{_stamp()}",
            generated_at=_now(),
            pack_ref=metadata["pack_ref"],
            pack_id=metadata["pack_id"],
            pack_name=metadata["pack_name"],
            pack_kind=metadata["pack_kind"],
            namespace=metadata["namespace"],
            version=metadata["version"],
            source_kind=metadata["source_kind"],
            source_ref=metadata["source_ref"],
            installed=installed,
            active=active,
            trusted=trusted,
            verified=verified,
            readiness_status=readiness_status,
            fit_status=fit_status,
            lane_id=metadata["lane_id"],
            lane_label=metadata["lane_label"],
            default_team=metadata["default_team"],
            default_template=metadata["default_template"],
            default_workset=metadata["default_workset"],
            checks=checks,
            recommended_request_examples=_request_examples(metadata),
            next_actions=next_actions,
            source_refs=source_refs,
            warnings=warnings,
            errors=errors,
        )


def save_pack_readiness_report(project_root: Path, report: PackReadinessReport) -> str:
    """readiness report를 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = default_readiness_path(root, report)
    report.saved_ref = _relative(path, root)
    _save_yaml(path, report.to_dict())
    latest_payload = report.to_dict()
    latest_payload["saved_ref"] = report.saved_ref
    _save_yaml(latest_readiness_path(root), latest_payload)
    return report.saved_ref


def latest_pack_readiness(project_root: Path, pack_ref: str | None = None) -> PackReadinessReport | None:
    """latest readiness report를 반환한다."""
    root = Path(project_root).resolve()
    latest = latest_readiness_path(root)
    if latest.exists():
        try:
            report = PackReadinessStore().load(latest)
            if pack_ref is None or report.pack_id == _pack_id_from_ref(pack_ref):
                return report
        except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
            logger.warning("latest readiness load skipped: %s", exc)
    reports = PackReadinessStore().list(default_readiness_dir(root))
    if pack_ref:
        wanted = _pack_id_from_ref(pack_ref)
        reports = [report for report in reports if report.pack_id == wanted]
    return reports[-1] if reports else None


def render_pack_readiness(report: PackReadinessReport) -> str:
    """readiness report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Doctor",
        "==================================================",
        "",
        "Pack:",
        f"  {report.pack_ref or report.pack_id or 'none'}",
        "",
        "Readiness:",
        f"  {report.readiness_status}",
        "",
        "Fit:",
        f"  {report.fit_status or 'unknown'}",
    ]
    if report.lane_label or report.lane_id:
        lines.extend(["", "Lane:", f"  {report.lane_label or report.lane_id}"])
    lines.extend(["", "Checks:"])
    for check in report.checks:
        marker = {"pass": "OK", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}.get(check.status, check.status)
        lines.append(f"  {marker} {check.title}: {check.summary}")
        for detail in check.details:
            lines.append(f"    - {detail}")
    if report.recommended_request_examples:
        lines.extend(["", "Suggested requests:"])
        lines.extend([f"  - {item}" for item in report.recommended_request_examples])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in report.next_actions])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    if report.saved_ref:
        lines.extend(["", "Saved:", f"  {report.saved_ref}"])
    return "\n".join(lines)


def render_pack_readiness_compact(report: PackReadinessReport | None) -> str:
    """pack show/status에 붙일 compact readiness 요약을 만든다."""
    if report is None:
        return ""
    lines = [
        "",
        "Readiness:",
        f"  {report.readiness_status}",
        f"  fit: {report.fit_status or 'unknown'}",
    ]
    if report.warnings and report.readiness_status != "ready":
        lines.append(f"  warning: {report.warnings[0]}")
    return "\n".join(lines)


def _no_active_report() -> PackReadinessReport:
    check = _check(
        "pack_resolved",
        "Pack resolved",
        "fail",
        "no active pack and no pack ref was provided",
        next_actions=["cambrian pack recommend", "cambrian pack doctor auth-bug-core"],
        errors=["pack ref required when no active pack exists"],
    )
    return PackReadinessReport(
        schema_version=SCHEMA_VERSION,
        report_id=f"readiness-no-pack-{_stamp()}",
        generated_at=_now(),
        pack_ref=None,
        pack_id=None,
        pack_name=None,
        pack_kind=None,
        namespace=None,
        version=None,
        source_kind=None,
        source_ref=None,
        installed=False,
        active=False,
        trusted=None,
        verified=None,
        readiness_status="blocked",
        fit_status="unknown",
        lane_id=None,
        lane_label=None,
        default_team=None,
        default_template=None,
        default_workset=None,
        checks=[check],
        recommended_request_examples=[],
        next_actions=["cambrian pack recommend"],
        warnings=[],
        errors=list(check.errors),
    )


def _find_installed_record(root: Path, pack_ref: str) -> InstalledPackRecord | None:
    index = InstalledPackStore().load(default_installed_packs_path(root))
    wanted = _pack_id_from_ref(pack_ref)
    namespace = _namespace_from_ref(pack_ref)
    version = _version_from_ref(pack_ref)
    for record in index.packs:
        if record.pack_id != wanted and record.pack_name != pack_ref:
            continue
        if namespace and record.namespace and record.namespace != namespace:
            continue
        if version and record.version != version:
            continue
        return record
    return None


def _load_manifest_from_record(root: Path, record: InstalledPackRecord) -> PackManifest | None:
    manifest_ref = record.latest_manifest_ref or record.manifest_ref
    if not manifest_ref:
        return None
    path = Path(manifest_ref)
    if not path.is_absolute():
        path = root / path
    try:
        return PackManifestLoader().load(path)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("readiness manifest load failed: %s", exc)
        return None


def _metadata(
    record: InstalledPackRecord | None,
    manifest: PackManifest | None,
    entry: PackCatalogEntry | None,
    registry_pack: SyncedRegistryPack | None,
    requested_ref: str,
) -> dict[str, Any]:
    lane = manifest.lane if manifest is not None and isinstance(manifest.lane, dict) else {}
    artifacts = dict(record.installed_artifacts or {}) if record is not None else {}
    pack_id = (
        record.pack_id
        if record is not None
        else manifest.pack_id
        if manifest is not None
        else entry.pack_id
        if entry is not None
        else registry_pack.pack_id
        if registry_pack is not None
        else _pack_id_from_ref(requested_ref)
    )
    namespace = (
        record.namespace
        if record is not None
        else manifest.namespace
        if manifest is not None
        else entry.namespace
        if entry is not None
        else registry_pack.namespace
        if registry_pack is not None
        else _namespace_from_ref(requested_ref)
    )
    version = (
        record.version
        if record is not None
        else manifest.version
        if manifest is not None
        else entry.version
        if entry is not None
        else registry_pack.version
        if registry_pack is not None
        else _version_from_ref(requested_ref)
    )
    pack_ref = _format_ref(namespace, pack_id, version)
    default_team = _lane_value(lane, "default_team") or _first(artifacts.get("teams"))
    default_template = _lane_value(lane, "default_template") or _first(artifacts.get("templates"))
    default_workset = _lane_value(lane, "default_workset") or _first(artifacts.get("benchmarks"))
    return {
        "pack_ref": pack_ref,
        "pack_id": pack_id,
        "pack_name": (
            record.pack_name
            if record is not None
            else manifest.pack_name
            if manifest is not None
            else entry.pack_name
            if entry is not None
            else registry_pack.pack_name
            if registry_pack is not None
            else pack_id
        ),
        "pack_kind": (
            record.pack_kind
            if record is not None
            else manifest.pack_kind
            if manifest is not None
            else entry.pack_kind
            if entry is not None
            else registry_pack.pack_kind
            if registry_pack is not None
            else None
        ),
        "namespace": namespace,
        "version": version,
        "source_kind": (
            record.source_kind
            if record is not None
            else "local_catalog"
            if entry is not None
            else "remote_static_registry"
            if registry_pack is not None
            else None
        ),
        "source_ref": (
            record.source_ref
            if record is not None
            else "packs/catalog.yaml"
            if entry is not None
            else registry_pack.registry_source_ref
            if registry_pack is not None
            else None
        ),
        "lane_id": _lane_value(lane, "lane_id") or artifacts.get("lane") or _first(_compatibility_values(entry, registry_pack, "lane_ids")),
        "lane_label": _lane_value(lane, "label"),
        "default_team": default_team,
        "default_template": default_template,
        "default_workset": default_workset,
    }


def _compatibility(
    metadata: dict[str, Any],
    manifest: PackManifest | None,
    entry: PackCatalogEntry | None,
    registry_pack: SyncedRegistryPack | None,
) -> dict[str, Any]:
    if manifest is not None:
        return dict(manifest.compatibility)
    if entry is not None:
        return dict(entry.compatibility)
    if registry_pack is not None:
        return dict(registry_pack.compatibility)
    if metadata["pack_id"] == "auth-bug-core":
        return {"stacks": ["python"], "test_frameworks": ["pytest"], "lane_ids": ["python-pytest-auth-bug-core"]}
    return {}


def _project_signals(root: Path) -> dict[str, list[str]]:
    try:
        from engine.project_harness_profile import ProjectHarnessScanner

        profile = ProjectHarnessScanner().scan(root)
        stacks = {
            str(item).lower()
            for item in [profile.language, *profile.languages]
            if str(item).lower() not in {"", "unknown"}
        }
        tests = {
            str(item).lower()
            for item in [profile.test_framework, *profile.test_frameworks]
            if str(item).lower() not in {"", "unknown", "unknown-tests"}
        }
        tags = {str(item).lower() for item in profile.domains if item}
        if "typescript" in stacks:
            stacks.add("javascript")
        if stacks or tests or tags:
            return {
                "stacks": sorted(stacks),
                "test_frameworks": sorted(tests),
                "tags": sorted(tags),
            }
    except Exception as exc:
        logger.warning("project harness profile signal scan failed: %s", exc)

    stacks: list[str] = []
    tests: list[str] = []
    tags: list[str] = []
    if any((root / marker).exists() for marker in ["pyproject.toml", "setup.py", "requirements.txt", "tox.ini"]):
        stacks.append("python")
    if any((root / marker).exists() for marker in ["package.json", "pnpm-lock.yaml", "yarn.lock"]):
        stacks.append("javascript")
    for folder in ["src", "tests", "demo"]:
        target = root / folder
        if target.exists() and any(target.rglob("*.py")):
            stacks.append("python")
    if any((root / marker).exists() for marker in ["pytest.ini", "conftest.py"]):
        tests.append("pytest")
    for file_name in ["pyproject.toml", "requirements.txt", "tox.ini"]:
        path = root / file_name
        if path.exists():
            try:
                if "pytest" in path.read_text(encoding="utf-8").lower():
                    tests.append("pytest")
            except OSError as exc:
                logger.warning("project signal read failed: %s (%s)", path, exc)
    tests_dir = root / "tests"
    if tests_dir.exists() and any(tests_dir.rglob("test_*.py")):
        tests.append("pytest")
    candidates: list[Path] = []
    for folder in ["src", "tests", "demo"]:
        target = root / folder
        if target.exists():
            candidates.extend(list(target.rglob("*.py"))[:200])
    haystack = " ".join(str(path).lower() for path in candidates)
    if any(token in haystack for token in ["auth", "login", "account"]):
        tags.extend(["auth", "login"])
    return {
        "stacks": sorted(set(stacks)),
        "test_frameworks": sorted(set(tests)),
        "tags": sorted(set(tags)),
    }


def _stack_check(signals: dict[str, list[str]], compat: dict[str, Any]) -> PackReadinessCheck:
    expected = {item.lower() for item in _as_list(compat.get("stacks") or compat.get("stack"))}
    detected = {item.lower() for item in signals.get("stacks", [])}
    if not expected:
        return _check("project_stack_fit", "Project stack fit", "skip", "pack does not declare stack compatibility")
    if "local_files" in expected:
        return _check("project_stack_fit", "Project stack fit", "pass", "local file workspace is available")
    if detected & expected:
        return _check("project_stack_fit", "Project stack fit", "pass", f"project stack matches: {', '.join(sorted(detected & expected))}")
    if detected:
        return _check(
            "project_stack_fit",
            "Project stack fit",
            "fail",
            f"project stack appears unsupported: {', '.join(sorted(detected))}",
            details=[f"expected: {', '.join(sorted(expected))}"],
            errors=["project stack does not match pack compatibility"],
        )
    return _check(
        "project_stack_fit",
        "Project stack fit",
        "warn",
        "project stack could not be determined",
        warnings=["add project markers such as pyproject.toml or source/test files"],
    )


def _test_check(signals: dict[str, list[str]], compat: dict[str, Any]) -> PackReadinessCheck:
    expected = {item.lower() for item in _as_list(compat.get("test_frameworks"))}
    detected = {item.lower() for item in signals.get("test_frameworks", [])}
    if not expected:
        return _check("test_framework_fit", "Test framework fit", "skip", "pack does not declare test framework compatibility")
    if detected & expected:
        return _check("test_framework_fit", "Test framework fit", "pass", f"test framework matches: {', '.join(sorted(detected & expected))}")
    if detected:
        return _check(
            "test_framework_fit",
            "Test framework fit",
            "fail",
            f"detected test framework does not match: {', '.join(sorted(detected))}",
            errors=["test framework does not match pack compatibility"],
        )
    return _check(
        "test_framework_fit",
        "Test framework fit",
        "warn",
        f"{', '.join(sorted(expected)) or 'declared'} test command was not detected",
        next_actions=["configure project tests or run with lower confidence"],
        warnings=[f"test framework was not detected: expected {', '.join(sorted(expected)) or 'declared'}"],
    )


def _lane_check(signals: dict[str, list[str]], compat: dict[str, Any], metadata: dict[str, Any]) -> PackReadinessCheck:
    pack_id = str(metadata.get("pack_id") or "")
    lane_ids = " ".join(_as_list(compat.get("lane_ids")) + [str(metadata.get("lane_id") or "")]).lower()
    expects_auth = pack_id == "auth-bug-core" or "auth" in lane_ids or "login" in lane_ids
    tags = {item.lower() for item in signals.get("tags", [])}
    if expects_auth and {"auth", "login", "account"} & tags:
        return _check("strongest_lane_fit", "Strongest lane fit", "pass", "auth/login project signals were detected")
    if expects_auth:
        return _check(
            "strongest_lane_fit",
            "Strongest lane fit",
            "warn",
            "auth/login lane signal is weak in this project",
            warnings=["outside-lane usage may reduce validated proposal quality"],
        )
    return _check("strongest_lane_fit", "Strongest lane fit", "skip", "no specific strongest lane rule for this pack")


def _artifact_check(verify_report: Any) -> PackReadinessCheck:
    artifacts = verify_report.checked_artifacts or {}
    details: list[str] = []
    for key in ["agents", "teams", "templates", "benchmarks"]:
        for item in artifacts.get(key, []) or []:
            if isinstance(item, dict):
                details.append(f"{key}: {item.get('name')} {'present' if item.get('exists') else 'missing'}")
    if artifacts.get("lane"):
        lane = artifacts["lane"]
        if isinstance(lane, dict):
            details.append(f"lane: {lane.get('name')} {'present' if lane.get('exists') else 'missing'}")
    if artifacts.get("errors"):
        return _check(
            "artifact_refs",
            "Installed artifact refs",
            "fail",
            "one or more installed artifact refs are missing",
            details=details,
            errors=[str(item) for item in artifacts.get("errors", [])],
            warnings=[str(item) for item in artifacts.get("warnings", [])],
            next_actions=[f"cambrian install verify {verify_report.pack_id}"],
        )
    return _check("artifact_refs", "Installed artifact refs", "pass", "workers, team, template, benchmark refs are present", details=details)


def _first_job_check(metadata: dict[str, Any], installed: bool) -> PackReadinessCheck:
    if not installed:
        return _check(
            "first_job_ready",
            "First job readiness",
            "fail",
            "first job requires an installed pack",
            next_actions=[f"cambrian install pack {metadata['pack_id']}"],
            errors=["pack must be installed before pack next can use it"],
        )
    if metadata.get("default_team") and metadata.get("default_template"):
        return _check("first_job_ready", "First job readiness", "pass", "team/template context is available")
    return _check(
        "first_job_ready",
        "First job readiness",
        "warn",
        "pack can be used, but default team/template context is incomplete",
        warnings=["first job guide may be lower confidence"],
    )


def _proof_check(root: Path, metadata: dict[str, Any]) -> PackReadinessCheck:
    try:
        from engine.project_pack_proof import latest_pack_proof_card

        card = latest_pack_proof_card(root, metadata["pack_id"])
    except Exception as exc:
        logger.warning("readiness proof lookup failed: %s", exc)
        card = None
    if card is None:
        return _check("proof_available", "Local proof available", "warn", "no local proof card found", warnings=["proof absence does not block readiness"])
    return _check("proof_available", "Local proof available", "pass", f"local proof verdict: {card.reputation_verdict}")


def _known_limits_check(
    metadata: dict[str, Any],
    entry: PackCatalogEntry | None,
    registry_pack: SyncedRegistryPack | None,
    manifest: PackManifest | None,
) -> PackReadinessCheck:
    limits: list[str] = []
    if entry is not None:
        limits.extend(entry.known_limits or entry.warnings)
    if registry_pack is not None:
        limits.extend(registry_pack.known_limits or registry_pack.warnings)
    if manifest is not None:
        limits.extend(manifest.warnings)
    if not limits and metadata["pack_id"] == "auth-bug-core":
        limits.append("strongest for narrow auth/login bug fixes, not broad refactors")
    status = "warn" if limits else "skip"
    return _check("known_limits", "Known limits", status, "known limits reviewed" if limits else "no known limits declared", details=_dedupe(limits), warnings=_dedupe(limits))


def _readiness_status(checks: list[PackReadinessCheck], installed: bool) -> str:
    failed_ids = {check.check_id for check in checks if check.status == "fail"}
    if "project_stack_fit" in failed_ids or "test_framework_fit" in failed_ids:
        return "unsupported"
    if failed_ids & {"installed_state", "integrity_state", "artifact_refs", "first_job_ready"}:
        return "blocked"
    warned_ids = {
        check.check_id
        for check in checks
        if check.status == "warn" and check.check_id not in {"proof_available", "known_limits"}
    }
    if not installed:
        return "blocked"
    if warned_ids:
        return "partial"
    return "ready"


def _fit_status(stack_check: PackReadinessCheck, test_check: PackReadinessCheck, lane_check: PackReadinessCheck) -> str:
    if stack_check.status == "pass" and test_check.status == "pass" and lane_check.status == "pass":
        return "strong"
    if stack_check.status == "fail" or test_check.status == "fail":
        return "weak"
    if stack_check.status == "warn" and test_check.status == "warn":
        return "unknown"
    if "pass" in {stack_check.status, test_check.status, lane_check.status}:
        return "partial"
    return "unknown"


def _next_actions(metadata: dict[str, Any], status: str, installed: bool, registry_name: str | None) -> list[str]:
    if not installed:
        return [_install_command(metadata, registry_name), f"cambrian pack doctor {metadata['pack_id']}"]
    if status == "blocked":
        return [f"cambrian install verify {metadata['pack_id']}", f"cambrian install doctor"]
    if status == "unsupported":
        return ["cambrian pack recommend", f"cambrian pack doctor {metadata['pack_id']} --save"]
    return [f"cambrian pack activate {metadata['pack_id']}", "cambrian pack next"]


def _install_command(metadata: dict[str, Any], registry_name: str | None) -> str:
    base = metadata.get("pack_id") or "PACK_ID"
    namespace = metadata.get("namespace")
    pack_ref = f"{namespace}/{base}" if namespace and namespace not in {"local"} else base
    if registry_name:
        return f"cambrian install pack {pack_ref} --registry {registry_name}"
    return f"cambrian install pack {pack_ref}"


def _request_examples(metadata: dict[str, Any]) -> list[str]:
    pack_id = str(metadata.get("pack_id") or "")
    lane_id = str(metadata.get("lane_id") or "")
    if pack_id == "typescript-jest-auth-core" or "typescript-jest" in lane_id:
        return [
            "로그인 에러 수정해",
            "Bearer token parsing 버그 수정해",
            "backend/tests/auth.test.ts 기준으로 작은 패치 만들어줘",
        ]
    if pack_id == "auth-bug-core" or "auth" in lane_id:
        return [
            "로그인 에러 수정해",
            "username normalize 버그 수정해",
            "tests/test_auth.py 기준으로 작은 패치 만들어줘",
        ]
    return [f"{metadata.get('pack_name') or pack_id}에 맞는 작은 버그를 수정해"]


def _check(
    check_id: str,
    title: str,
    status: str,
    summary: str,
    details: list[str] | None = None,
    next_actions: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> PackReadinessCheck:
    return PackReadinessCheck(
        check_id=check_id,
        title=title,
        status=status,
        summary=summary,
        details=details or [],
        next_actions=next_actions or [],
        warnings=warnings or [],
        errors=errors or [],
    )


def _report_from_dict(payload: dict[str, Any]) -> PackReadinessReport:
    return PackReadinessReport(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        report_id=str(payload.get("report_id") or ""),
        generated_at=str(payload.get("generated_at") or _now()),
        pack_ref=str(payload.get("pack_ref")) if payload.get("pack_ref") is not None else None,
        pack_id=str(payload.get("pack_id")) if payload.get("pack_id") is not None else None,
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        pack_kind=str(payload.get("pack_kind")) if payload.get("pack_kind") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        source_ref=str(payload.get("source_ref")) if payload.get("source_ref") is not None else None,
        installed=bool(payload.get("installed", False)),
        active=bool(payload.get("active", False)),
        trusted=payload.get("trusted") if payload.get("trusted") is None else bool(payload.get("trusted")),
        verified=payload.get("verified") if payload.get("verified") is None else bool(payload.get("verified")),
        readiness_status=str(payload.get("readiness_status") or "unknown"),
        fit_status=str(payload.get("fit_status")) if payload.get("fit_status") is not None else None,
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        default_team=str(payload.get("default_team")) if payload.get("default_team") is not None else None,
        default_template=str(payload.get("default_template")) if payload.get("default_template") is not None else None,
        default_workset=str(payload.get("default_workset")) if payload.get("default_workset") is not None else None,
        checks=[
            PackReadinessCheck(
                check_id=str(item.get("check_id") or ""),
                title=str(item.get("title") or ""),
                status=str(item.get("status") or "skip"),
                summary=str(item.get("summary") or ""),
                details=_as_list(item.get("details")),
                next_actions=_as_list(item.get("next_actions")),
                warnings=_as_list(item.get("warnings")),
                errors=_as_list(item.get("errors")),
            )
            for item in payload.get("checks", []) or []
            if isinstance(item, dict)
        ],
        recommended_request_examples=_as_list(payload.get("recommended_request_examples")),
        next_actions=_as_list(payload.get("next_actions")),
        source_refs=dict(payload.get("source_refs")) if isinstance(payload.get("source_refs"), dict) else {},
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else None,
    )


def _active_matches(context: Any, record: InstalledPackRecord) -> bool:
    return bool(context and context.status == "active" and context.pack_id == record.pack_id)


def _preinstall_trusted(entry: PackCatalogEntry | None, registry_pack: SyncedRegistryPack | None) -> bool | None:
    trust = entry.trust_level if entry is not None else registry_pack.trust_level if registry_pack is not None else None
    if trust is None:
        return None
    return str(trust).lower() in {"trusted", "local"}


def _preinstall_sha(entry: PackCatalogEntry | None, registry_pack: SyncedRegistryPack | None) -> str | None:
    return entry.manifest_sha256 if entry is not None else registry_pack.manifest_sha256 if registry_pack is not None else None


def _compatibility_values(entry: PackCatalogEntry | None, registry_pack: SyncedRegistryPack | None, key: str) -> list[str]:
    if entry is not None:
        return _as_list(entry.compatibility.get(key))
    if registry_pack is not None:
        return _as_list(registry_pack.compatibility.get(key))
    return []


def _catalog_root(project_root: Path) -> Path:
    return Path(project_root).resolve()


def _project_root_from_report_path(path: Path) -> Path:
    parts = list(Path(path).resolve().parents)
    for parent in parts:
        if parent.name == ".cambrian":
            return parent.parent
    return Path.cwd().resolve()


def _pack_id_from_ref(raw: str | None) -> str:
    text = str(raw or "").strip()
    if "@" in text:
        text = text.rsplit("@", 1)[0]
    if "/" in text:
        text = text.split("/", 1)[1]
    return text


def _namespace_from_ref(raw: str | None) -> str | None:
    text = str(raw or "").strip()
    if "@" in text:
        text = text.rsplit("@", 1)[0]
    if "/" not in text:
        return None
    return text.split("/", 1)[0] or None


def _version_from_ref(raw: str | None) -> str | None:
    text = str(raw or "").strip()
    if "@" not in text:
        return None
    version = text.rsplit("@", 1)[1].strip()
    return version or None


def _format_ref(namespace: str | None, pack_id: str, version: str | None) -> str:
    base = f"{namespace}/{pack_id}" if namespace else pack_id
    return f"{base}@{version}" if version else base


def _record_ref(record: InstalledPackRecord) -> str:
    return _format_ref(record.namespace, record.pack_id, record.version)


def _lane_value(lane: dict[str, Any], key: str) -> str | None:
    value = lane.get(key)
    text = str(value).strip() if value is not None else ""
    return text or None


def _first(value: Any) -> str | None:
    items = _as_list(value)
    return items[0] if items else None


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
