"""로컬 pack authoring, build, publish-local 코어."""

from __future__ import annotations

import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.project_pack_catalog import default_pack_catalog_path
from engine.project_pack_install import (
    MANIFEST_SCHEMA_VERSION,
    SCHEMA_VERSION,
    SUPPORTED_PACK_KINDS,
    PackManifest,
    PackManifestLoader,
    default_agent_registry_path,
    default_benchmark_worksets_dir,
    default_lane_playbook_path,
    default_team_presets_path,
    default_templates_path,
    _as_dict,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)
from engine.project_pack_trust import PackIntegrityHasher

logger = logging.getLogger(__name__)


@dataclass
class PackDraft:
    """설치 가능한 pack manifest를 만들기 전의 authoring draft."""

    schema_version: str
    draft_id: str
    created_at: str
    updated_at: str | None
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    description: str | None
    tags: list[str]
    maturity: str | None
    worker_refs: list[str]
    team_refs: list[str]
    template_refs: list[str]
    benchmark_refs: list[str]
    lane_ref: str | None
    compatibility: dict[str, Any]
    evidence_refs: dict[str, Any]
    derivative: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackBuildReport:
    """pack validate/build 결과."""

    schema_version: str
    build_id: str
    created_at: str
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    draft_ref: str | None
    manifest_ref: str | None
    manifest_sha256: str | None
    included_artifacts: dict[str, Any]
    evidence_refs: dict[str, Any]
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackPublishLocalRecord:
    """local catalog publish 결과."""

    schema_version: str
    publish_id: str
    created_at: str
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    manifest_ref: str
    manifest_sha256: str
    catalog_ref: str
    status: str
    maturity: str | None = None
    proof_status: str | None = None
    release_report_ref: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


def default_pack_drafts_dir(project_root: Path) -> Path:
    """pack draft 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "drafts"


def default_pack_builds_dir(project_root: Path) -> Path:
    """pack build report 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "builds"


def default_pack_publishes_dir(project_root: Path) -> Path:
    """pack publish record 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "publishes"


def default_generated_manifests_dir(repo_root: Path) -> Path:
    """로컬 catalog에 publish할 generated manifest 디렉터리를 반환한다."""
    return Path(repo_root).resolve() / "packs" / "generated"


class PackDraftBuilder:
    """로컬 worker/team/template/lane refs로 pack draft를 만든다."""

    def create(
        self,
        project_root: Path,
        pack_id: str,
        pack_kind: str,
        refs: dict[str, Any],
        pack_name: str | None = None,
        version: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        maturity: str | None = None,
    ) -> PackDraft:
        """pack draft 객체를 생성한다."""
        root = Path(project_root).resolve()
        normalized_kind = str(pack_kind or "").strip()
        warnings: list[str] = []
        errors: list[str] = []
        if normalized_kind not in SUPPORTED_PACK_KINDS:
            errors.append(f"unsupported pack kind: {normalized_kind}")
        draft = PackDraft(
            schema_version=SCHEMA_VERSION,
            draft_id=f"draft-{_slug(pack_id, 'pack')}-{_stamp()}",
            created_at=_now(),
            updated_at=None,
            pack_id=str(pack_id).strip(),
            pack_name=pack_name or _title_from_id(pack_id),
            pack_kind=normalized_kind,
            version=version,
            description=description,
            tags=_dedupe(_as_list(tags)),
            maturity=maturity,
            worker_refs=_dedupe(_as_list(refs.get("workers"))),
            team_refs=_dedupe(_as_list(refs.get("teams"))),
            template_refs=_dedupe(_as_list(refs.get("templates"))),
            benchmark_refs=_dedupe(_as_list(refs.get("benchmarks"))),
            lane_ref=str(refs.get("lane")).strip() if refs.get("lane") else None,
            compatibility={},
            evidence_refs={},
            derivative={},
            warnings=warnings,
            errors=errors,
        )
        validation = PackValidator().validate_draft(root, draft, save_report=False)
        draft.compatibility = _infer_compatibility(root, draft)
        draft.evidence_refs = _collect_evidence_refs(root, draft)
        draft.warnings = _dedupe([*draft.warnings, *validation.warnings])
        draft.errors = _dedupe([*draft.errors, *validation.errors])
        return draft


class PackValidator:
    """pack draft 또는 installable manifest를 검증한다."""

    def validate_draft(
        self,
        project_root: Path,
        draft: PackDraft,
        save_report: bool = True,
    ) -> PackBuildReport:
        """draft ref가 현재 로컬 library에서 해석되는지 검증한다."""
        root = Path(project_root).resolve()
        warnings = list(draft.warnings)
        errors = list(draft.errors)
        if not draft.pack_id:
            errors.append("pack_id is required")
        if not draft.pack_name:
            errors.append("pack_name is required")
        if draft.pack_kind not in SUPPORTED_PACK_KINDS:
            errors.append(f"unsupported pack kind: {draft.pack_kind}")
        if not any([draft.worker_refs, draft.team_refs, draft.template_refs, draft.benchmark_refs, draft.lane_ref]):
            errors.append("at least one worker/team/template/benchmark/lane ref is required")
        artifacts = _resolve_draft_artifacts(root, draft, errors=errors)
        compatibility = _infer_compatibility(root, draft, artifacts=artifacts)
        evidence = _collect_evidence_refs(root, draft)
        if not evidence:
            warnings.append("no local proof/qualification/canary evidence refs found")
        warnings.extend(_vnext_workorder_warnings(root, draft.derivative, draft.pack_id))
        report = PackBuildReport(
            schema_version=SCHEMA_VERSION,
            build_id=f"validate-{_slug(draft.pack_id, 'pack')}-{_stamp()}",
            created_at=_now(),
            pack_id=draft.pack_id,
            pack_name=draft.pack_name,
            pack_kind=draft.pack_kind,
            version=draft.version,
            draft_ref=None,
            manifest_ref=None,
            manifest_sha256=None,
            included_artifacts=_included_summary(artifacts),
            evidence_refs=evidence,
            status="validated" if not errors else "blocked",
            warnings=_dedupe([*warnings, *compatibility.get("warnings", [])]),
            errors=_dedupe(errors),
        )
        if save_report:
            save_pack_build_report(root, report)
        return report

    def validate_manifest(self, project_root: Path, manifest_path: Path) -> PackBuildReport:
        """install manifest가 PackManifestLoader로 로드되고 안전한 install policy를 갖는지 확인한다."""
        root = Path(project_root).resolve()
        try:
            manifest = PackManifestLoader().load(Path(manifest_path))
        except (FileNotFoundError, ValueError) as exc:
            return PackBuildReport(
                schema_version=SCHEMA_VERSION,
                build_id=f"validate-manifest-{_stamp()}",
                created_at=_now(),
                pack_id="unknown",
                pack_name="unknown",
                pack_kind="unknown",
                version=None,
                draft_ref=None,
                manifest_ref=_relative(Path(manifest_path), root),
                manifest_sha256=None,
                included_artifacts={},
                evidence_refs={},
                status="blocked",
                errors=[str(exc)],
            )
        errors: list[str] = []
        install = manifest.install
        for key in ("auto_apply", "auto_bootstrap", "auto_promote", "auto_canary"):
            if install.get(key) is True:
                errors.append(f"unsafe install policy: {key} must be false")
        integrity = PackIntegrityHasher().hash_file(Path(manifest_path))
        report = PackBuildReport(
            schema_version=SCHEMA_VERSION,
            build_id=f"validate-{_slug(manifest.pack_id, 'pack')}-{_stamp()}",
            created_at=_now(),
            pack_id=manifest.pack_id,
            pack_name=manifest.pack_name,
            pack_kind=manifest.pack_kind,
            version=manifest.version,
            draft_ref=None,
            manifest_ref=_relative(Path(manifest_path), root),
            manifest_sha256=integrity.sha256 or None,
            included_artifacts={
                "workers": [str(item.get("id") or item.get("agent_id")) for item in manifest.workers],
                "teams": [str(item.get("name") or item.get("team_id")) for item in manifest.teams],
                "templates": [str(item.get("name") or item.get("template_id")) for item in manifest.templates],
                "benchmarks": [str(item.get("name") or item.get("workset_id")) for item in manifest.benchmarks],
                "lane": (manifest.lane or {}).get("lane_id") if manifest.lane else None,
            },
            evidence_refs=_as_dict(_load_yaml(Path(manifest_path)).get("evidence")),
            status="validated" if not errors and not integrity.errors else "blocked",
            warnings=list(manifest.warnings),
            errors=[*errors, *integrity.errors],
        )
        save_pack_build_report(root, report)
        return report


class PackBuilder:
    """pack draft를 installable manifest로 빌드한다."""

    def build(self, project_root: Path, draft_path: Path, out_path: Path | None = None) -> PackBuildReport:
        """draft를 읽어 `.cambrian-pack.yaml` manifest를 생성한다."""
        root = Path(project_root).resolve()
        draft_file = resolve_draft_path(root, draft_path)
        draft = load_pack_draft(draft_file)
        validation = PackValidator().validate_draft(root, draft, save_report=False)
        if validation.errors:
            validation.draft_ref = _relative(draft_file, root)
            save_pack_build_report(root, validation)
            return validation
        artifacts = _resolve_draft_artifacts(root, draft)
        manifest_payload = _build_manifest_payload(root, draft, artifacts, draft_file)
        target = Path(out_path).resolve() if out_path else _default_manifest_out_path(draft)
        _save_yaml(target, manifest_payload)
        integrity = PackIntegrityHasher().hash_file(target)
        report = PackBuildReport(
            schema_version=SCHEMA_VERSION,
            build_id=f"build-{_slug(draft.pack_id, 'pack')}-{_stamp()}",
            created_at=_now(),
            pack_id=draft.pack_id,
            pack_name=draft.pack_name,
            pack_kind=draft.pack_kind,
            version=draft.version,
            draft_ref=_relative(draft_file, root),
            manifest_ref=_relative(target, root),
            manifest_sha256=integrity.sha256 or None,
            included_artifacts=_included_summary(artifacts),
            evidence_refs=manifest_payload.get("evidence", {}),
            status="built" if not integrity.errors else "failed",
            warnings=_dedupe([*draft.warnings, *validation.warnings, *integrity.warnings]),
            errors=_dedupe([*draft.errors, *validation.errors, *integrity.errors]),
        )
        save_pack_build_report(root, report)
        return report


class PackLocalPublisher:
    """installable manifest를 로컬 catalog에 preview/publish한다."""

    def publish(
        self,
        project_root: Path,
        manifest_path: Path,
        confirm: bool = False,
        catalog_path: Path | None = None,
        require_proof: bool = False,
        release_check_path: Path | None = None,
    ) -> PackPublishLocalRecord:
        """manifest를 packs/catalog.yaml에 등록한다. confirm 없이는 preview만 반환한다."""
        from engine.project_pack_release import (
            PackReleaseChecker,
            PackReleaseStore,
            save_pack_release_report,
        )

        root = Path(project_root).resolve()
        repo_root = Path(__file__).resolve().parents[1]
        catalog = Path(catalog_path).resolve() if catalog_path else default_pack_catalog_path(repo_root)
        try:
            manifest = PackManifestLoader().load(Path(manifest_path))
        except (FileNotFoundError, ValueError) as exc:
            return _publish_record(
                root,
                pack_id="unknown",
                pack_name="unknown",
                pack_kind="unknown",
                version=None,
                manifest_ref=str(Path(manifest_path)),
                manifest_sha256="",
                catalog_ref=_relative(catalog, root),
                status="blocked",
                errors=[str(exc)],
            )
        if release_check_path:
            release_report = PackReleaseStore().load(Path(release_check_path))
            release_report_ref = _relative(Path(release_check_path), root)
        else:
            release_report = PackReleaseChecker().check(root, str(Path(manifest_path)), require_proof=require_proof)
            release_report_ref = save_pack_release_report(root, release_report)
        publish_manifest = _manifest_path_for_catalog(repo_root, catalog, Path(manifest_path), confirm)
        integrity = PackIntegrityHasher().hash_file(publish_manifest)
        warnings = _dedupe([*manifest.warnings, *release_report.warnings])
        errors = _dedupe([*integrity.errors, *release_report.errors])
        if not release_report.safe_to_publish:
            errors.append("release gate blocked publish")
        if require_proof and not release_report.require_proof_satisfied:
            errors.append("proof evidence is required for publish-local")
        catalog_payload = _load_yaml(catalog)
        entries = list(catalog_payload.get("entries", []) if isinstance(catalog_payload.get("entries"), list) else [])
        existing = next(
            (entry for entry in entries if isinstance(entry, dict) and str(entry.get("pack_id") or "") == manifest.pack_id),
            None,
        )
        if existing:
            existing_sha = str(existing.get("manifest_sha256") or "").strip().lower()
            if existing_sha and existing_sha == integrity.sha256.lower():
                warnings.append("pack is already published with same manifest digest")
            else:
                errors.append(f"pack id already exists in local catalog with different digest: {manifest.pack_id}")
        status = "published" if confirm and not errors and not existing else "preview"
        if errors:
            status = "blocked"
        record = _publish_record(
            root,
            pack_id=manifest.pack_id,
            pack_name=manifest.pack_name,
            pack_kind=manifest.pack_kind,
            version=manifest.version,
            manifest_ref=_relative(publish_manifest, root),
            manifest_sha256=integrity.sha256,
            catalog_ref=_relative(catalog, root),
            status=status,
            maturity=release_report.maturity,
            proof_status=release_report.proof_summary.proof_status,
            release_report_ref=release_report_ref,
            warnings=warnings,
            errors=errors,
        )
        if not confirm or errors or existing:
            return record
        entry = _catalog_entry_for_manifest(
            repo_root,
            catalog,
            publish_manifest,
            manifest,
            integrity.sha256,
            release_report=release_report,
            release_report_ref=release_report_ref,
        )
        entries.append(entry)
        catalog_payload = {
            "schema_version": str(catalog_payload.get("schema_version") or "1.0"),
            "updated_at": _now(),
            "source_kind": str(catalog_payload.get("source_kind") or "local_seed"),
            "entries": entries,
            "warnings": list(catalog_payload.get("warnings", []) if isinstance(catalog_payload.get("warnings"), list) else []),
            "errors": list(catalog_payload.get("errors", []) if isinstance(catalog_payload.get("errors"), list) else []),
        }
        _save_yaml(catalog, catalog_payload)
        record.saved_ref = save_pack_publish_record(root, record)
        return record


def save_pack_draft(project_root: Path, draft: PackDraft) -> str:
    """draft를 `.cambrian/packs/drafts/`에 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    path = default_pack_drafts_dir(root) / f"draft_{_slug(draft.pack_id, 'pack')}.yaml"
    _save_yaml(path, draft.to_dict())
    return _relative(path, root)


def load_pack_draft(path: Path) -> PackDraft:
    """draft YAML을 PackDraft로 로드한다."""
    payload = _load_yaml(Path(path))
    missing = [
        key
        for key in ("draft_id", "pack_id", "pack_name", "pack_kind")
        if not str(payload.get(key) or "").strip()
    ]
    if missing:
        raise ValueError(f"pack draft missing required fields: {', '.join(missing)}")
    return PackDraft(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        draft_id=str(payload.get("draft_id")),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        pack_id=str(payload.get("pack_id")),
        pack_name=str(payload.get("pack_name")),
        pack_kind=str(payload.get("pack_kind")),
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        description=str(payload.get("description")) if payload.get("description") is not None else None,
        tags=_as_list(payload.get("tags")),
        maturity=str(payload.get("maturity")) if payload.get("maturity") is not None else None,
        worker_refs=_as_list(payload.get("worker_refs")),
        team_refs=_as_list(payload.get("team_refs")),
        template_refs=_as_list(payload.get("template_refs")),
        benchmark_refs=_as_list(payload.get("benchmark_refs")),
        lane_ref=str(payload.get("lane_ref")) if payload.get("lane_ref") is not None else None,
        compatibility=_as_dict(payload.get("compatibility")),
        evidence_refs=_as_dict(payload.get("evidence_refs")),
        derivative=_as_dict(payload.get("derivative")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )


def resolve_draft_path(project_root: Path, draft_or_pack_id: str | Path) -> Path:
    """draft path 또는 pack id를 draft 파일 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(draft_or_pack_id))
    if raw.exists():
        return raw.resolve()
    candidate = default_pack_drafts_dir(root) / f"draft_{_slug(str(draft_or_pack_id), 'pack')}.yaml"
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(f"pack draft not found: {draft_or_pack_id}")


def save_pack_build_report(project_root: Path, report: PackBuildReport) -> str:
    """build/validate report를 저장한다."""
    root = Path(project_root).resolve()
    path = default_pack_builds_dir(root) / f"{_slug(report.build_id, 'build')}.yaml"
    report.saved_ref = _relative(path, root)
    _save_yaml(path, report.to_dict())
    return report.saved_ref


def save_pack_publish_record(project_root: Path, record: PackPublishLocalRecord) -> str:
    """publish-local record를 저장한다."""
    root = Path(project_root).resolve()
    path = default_pack_publishes_dir(root) / f"{_slug(record.publish_id, 'publish')}.yaml"
    record.saved_ref = _relative(path, root)
    _save_yaml(path, record.to_dict())
    return record.saved_ref


def render_pack_draft_created(draft: PackDraft, draft_ref: str) -> str:
    """draft 생성 결과를 렌더링한다."""
    lines = [
        "Pack draft created.",
        "",
        "Pack:",
        f"  {draft.pack_id}",
        "",
        "Kind:",
        f"  {draft.pack_kind}",
        "",
        "Includes:",
        f"  workers   : {', '.join(draft.worker_refs) or 'none'}",
        f"  teams     : {', '.join(draft.team_refs) or 'none'}",
        f"  templates : {', '.join(draft.template_refs) or 'none'}",
        f"  benchmarks: {', '.join(draft.benchmark_refs) or 'none'}",
        f"  lane      : {draft.lane_ref or 'none'}",
        "",
        "Saved:",
        f"  {draft_ref}",
        "",
        "Next:",
        f"  cambrian pack validate {draft_ref}",
        f"  cambrian pack build {draft_ref}",
    ]
    if draft.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in draft.warnings])
    if draft.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in draft.errors])
    return "\n".join(lines)


def render_pack_validate(report: PackBuildReport) -> str:
    """validate 결과를 렌더링한다."""
    lines = [
        "Pack Validate",
        "==================================================",
        "",
        "Pack:",
        f"  {report.pack_id}",
        f"  kind   : {report.pack_kind}",
        f"  status : {report.status}",
    ]
    lines.extend(_render_included(report.included_artifacts))
    if report.evidence_refs:
        lines.extend(["", "Evidence refs:"])
        for key, value in report.evidence_refs.items():
            rendered = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
            lines.append(f"  {key}: {rendered or 'none'}")
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def render_pack_built(report: PackBuildReport) -> str:
    """build 결과를 렌더링한다."""
    lines = [
        "Pack built." if report.status == "built" else "Pack build blocked.",
        "",
        "Pack:",
        f"  {report.pack_id}",
        "",
        "Manifest:",
        f"  {report.manifest_ref or 'none'}",
        "",
        "SHA-256:",
        f"  {report.manifest_sha256 or 'none'}",
    ]
    lines.extend(_render_included(report.included_artifacts))
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    if report.status == "built" and report.manifest_ref:
        lines.extend(["", "Next:", f"  cambrian pack publish-local {report.manifest_ref}"])
    return "\n".join(lines)


def render_pack_publish(record: PackPublishLocalRecord, confirm: bool) -> str:
    """publish-local 결과를 렌더링한다."""
    title = "Pack published to local catalog." if record.status == "published" else "Pack publish-local preview."
    if record.status == "blocked":
        title = "Pack publish-local blocked."
    lines = [
        title,
        "",
        "Pack:",
        f"  {record.pack_id}",
        "",
        "Catalog:",
        f"  {record.catalog_ref}",
        "",
        "Manifest:",
        f"  {record.manifest_ref}",
        "",
        "SHA-256:",
        f"  {record.manifest_sha256 or 'none'}",
        "",
        "Release:",
        f"  maturity    : {record.maturity or 'unknown'}",
        f"  proof_status: {record.proof_status or 'unknown'}",
    ]
    if not confirm and record.status == "preview":
        lines.extend(["", "Preview only. 실제 catalog update는 --confirm이 필요합니다."])
    if record.status == "published":
        lines.extend(["", "Install:", f"  cambrian install pack {record.pack_id}"])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    return "\n".join(lines)


def _resolve_draft_artifacts(
    root: Path,
    draft: PackDraft,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """draft refs를 실제 library artifact로 해석한다."""
    err = errors if errors is not None else []
    agent_entries = _agent_entries(root)
    team_entries = _team_entries(root)
    template_entries = _template_entries(root)
    benchmark_entries = _benchmark_entries(root)
    teams = [_resolve_many("team", ref, team_entries, err) for ref in draft.team_refs]
    workers = [_resolve_many("worker", ref, agent_entries, err) for ref in draft.worker_refs]
    workers = _augment_workers_from_teams(workers, teams, agent_entries, err)
    artifacts = {
        "workers": workers,
        "teams": teams,
        "templates": [_resolve_many("template", ref, template_entries, err) for ref in draft.template_refs],
        "benchmarks": [_resolve_many("benchmark", ref, benchmark_entries, err) for ref in draft.benchmark_refs],
        "lane": _resolve_lane(root, draft.lane_ref, err) if draft.lane_ref else None,
    }
    return artifacts


def _resolve_many(kind: str, ref: str, entries: list[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    """ref 하나를 entries에서 찾는다."""
    wanted = str(ref).strip()
    wanted_slug = _slug(wanted)
    for entry in entries:
        keys = [
            entry.get("agent_id"),
            entry.get("role_id"),
            entry.get("team_id"),
            entry.get("name"),
            entry.get("template_id"),
            entry.get("workset_id"),
            entry.get("label"),
        ]
        if any(str(key or "") == wanted or _slug(str(key or "")) == wanted_slug for key in keys):
            return dict(entry)
    errors.append(f"{kind} ref not found: {ref}")
    return {"missing_ref": ref, "kind": kind}


def _augment_workers_from_teams(
    workers: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    agent_entries: list[dict[str, Any]],
    errors: list[str],
) -> list[dict[str, Any]]:
    """team pack이 설치 가능하도록 lead/support worker refs를 함께 포함한다."""
    result = list(workers)
    seen = {str(item.get("agent_id") or item.get("id") or item.get("missing_ref") or "") for item in result}
    for team in teams:
        if team.get("missing_ref"):
            continue
        agent_refs = _dedupe([team.get("lead_agent_id"), *_as_list(team.get("supporting_agent_ids"))])
        for agent_ref in agent_refs:
            key = str(agent_ref or "").strip()
            if not key or key in seen:
                continue
            agent = _resolve_many("worker", key, agent_entries, errors)
            result.append(agent)
            seen.add(key)
    return result


def _resolve_lane(root: Path, lane_ref: str, errors: list[str]) -> dict[str, Any] | None:
    """lane playbook에서 lane ref를 찾는다."""
    playbook = _load_yaml(default_lane_playbook_path(root))
    wanted = str(lane_ref).strip()
    if not playbook:
        errors.append(f"lane ref not found: {lane_ref} (lane playbook missing)")
        return None
    if str(playbook.get("lane_id") or "") == wanted:
        return dict(playbook)
    for item in playbook.get("installed_lane_packs", []) or []:
        if isinstance(item, dict) and str(item.get("lane_id") or "") == wanted:
            return dict(item)
    errors.append(f"lane ref not found: {lane_ref}")
    return None


def _agent_entries(root: Path) -> list[dict[str, Any]]:
    payload = _load_yaml(default_agent_registry_path(root))
    return [dict(item) for item in payload.get("agents", []) or [] if isinstance(item, dict)]


def _team_entries(root: Path) -> list[dict[str, Any]]:
    payload = _load_yaml(default_team_presets_path(root))
    return [dict(item) for item in payload.get("teams", []) or [] if isinstance(item, dict)]


def _template_entries(root: Path) -> list[dict[str, Any]]:
    payload = _load_yaml(default_templates_path(root))
    return [dict(item) for item in payload.get("templates", []) or [] if isinstance(item, dict)]


def _benchmark_entries(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    directory = default_benchmark_worksets_dir(root)
    if not directory.exists():
        return entries
    for path in sorted(directory.glob("*.yaml")):
        payload = _load_yaml(path)
        if payload:
            payload.setdefault("_ref", _relative(path, root))
            entries.append(payload)
    return entries


def _build_manifest_payload(
    root: Path,
    draft: PackDraft,
    artifacts: dict[str, Any],
    draft_path: Path,
) -> dict[str, Any]:
    """resolved artifacts로 installable manifest payload를 만든다."""
    compatibility = _infer_compatibility(root, draft, artifacts=artifacts)
    evidence = _collect_evidence_refs(root, draft)
    warnings = _dedupe([*draft.warnings, *compatibility.get("warnings", [])])
    if not evidence:
        warnings.append("No local evidence refs were found; do not claim proof for this pack.")
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "pack_id": draft.pack_id,
        "pack_name": draft.pack_name,
        "pack_kind": draft.pack_kind,
        "version": draft.version,
        "description": draft.description,
        "source": {
            "kind": "local_authoring",
            "registry": "local",
            "origin_ref": _relative(draft_path, root),
        },
        "compatibility": {key: value for key, value in compatibility.items() if key != "warnings"},
        "workers": [_manifest_worker(item) for item in artifacts["workers"] if not item.get("missing_ref")],
        "teams": [_manifest_team(item) for item in artifacts["teams"] if not item.get("missing_ref")],
        "templates": [_manifest_template(item) for item in artifacts["templates"] if not item.get("missing_ref")],
        "benchmarks": [_manifest_benchmark(item) for item in artifacts["benchmarks"] if not item.get("missing_ref")],
        "policies": _policies_from_templates(artifacts["templates"]),
        "lane": _manifest_lane(draft, artifacts),
        "evidence": evidence,
        "derivative": _as_dict(getattr(draft, "derivative", {})),
        "install": {
            "install_as_library": True,
            "auto_apply": False,
            "auto_bootstrap": False,
            "auto_promote": False,
            "auto_canary": False,
        },
        "warnings": _dedupe(warnings),
    }
    return _strip_none(payload)


def _vnext_workorder_warnings(root: Path, derivative: dict[str, Any], pack_id: str) -> list[str]:
    """derivative draft에 연결된 미완료 vNext workorder warning을 만든다."""
    if not derivative:
        return []
    try:
        from engine.project_pack_vnext_workbench import unresolved_required_workorders_for_derivative

        orders = unresolved_required_workorders_for_derivative(root, derivative, pack_id)
    except Exception as exc:  # noqa: BLE001 - workbench 조회 실패가 validate/build 자체를 막으면 안 된다.
        logger.warning("vNext workorder lookup failed during pack authoring: %s", exc)
        return []
    return [f"vNext required workorder unresolved: {order.title}" for order in orders]


def _manifest_worker(item: dict[str, Any]) -> dict[str, Any]:
    return _strip_none({
        "id": item.get("agent_id") or item.get("id"),
        "name": item.get("label") or item.get("name") or item.get("agent_id"),
        "description": item.get("description"),
        "capabilities": _as_list(item.get("strengths") or item.get("capabilities")),
        "tags": _as_list(item.get("preferred_signals") or item.get("tags")),
        "fit_hints": _as_list(item.get("project_fit_notes") or item.get("fit_hints")),
    })


def _manifest_team(item: dict[str, Any]) -> dict[str, Any]:
    return _strip_none({
        "team_id": item.get("team_id"),
        "name": item.get("name") or item.get("team_id"),
        "description": item.get("description"),
        "lead_agent_id": item.get("lead_agent_id"),
        "supporting_agent_ids": _as_list(item.get("supporting_agent_ids")),
        "tags": _as_list(item.get("tags")),
    })


def _manifest_template(item: dict[str, Any]) -> dict[str, Any]:
    return _strip_none({
        "template_id": item.get("template_id"),
        "name": item.get("name") or item.get("template_id"),
        "template_kind": item.get("template_kind"),
        "description": item.get("description"),
        "tags": _as_list(item.get("tags")),
        "project_defaults": _as_dict(item.get("project_defaults")),
        "safety_defaults": _as_dict(item.get("safety_defaults")),
        "agent_defaults": _as_dict(item.get("agent_defaults")),
        "team_defaults": _as_dict(item.get("team_defaults")),
        "policy_defaults": _as_dict(item.get("policy_defaults")),
        "context_defaults": _as_dict(item.get("context_defaults")),
        "fit_hints": _as_list(item.get("fit_hints")),
        "warnings": _as_list(item.get("warnings")),
    })


def _manifest_benchmark(item: dict[str, Any]) -> dict[str, Any]:
    return _strip_none({
        "workset_id": item.get("workset_id"),
        "name": item.get("name") or item.get("workset_id"),
        "description": item.get("description"),
        "case_ids": _as_list(item.get("case_ids")),
        "tags": _as_list(item.get("tags")),
        "warnings": _as_list(item.get("warnings")),
    })


def _manifest_lane(draft: PackDraft, artifacts: dict[str, Any]) -> dict[str, Any] | None:
    lane = artifacts.get("lane")
    if not lane and not draft.lane_ref:
        return None
    return _strip_none({
        "lane_id": (lane or {}).get("lane_id") or draft.lane_ref,
        "label": (lane or {}).get("label") or draft.description,
        "default_team": _first_name(artifacts.get("teams", [])),
        "default_template": _first_name(artifacts.get("templates", [])),
        "default_workset": _first_name(artifacts.get("benchmarks", [])),
    })


def _infer_compatibility(
    root: Path,
    draft: PackDraft,
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """template/lane/workset 신호로 compatibility를 추론한다."""
    resolved = artifacts or _resolve_draft_artifacts(root, draft, errors=[])
    stacks: list[str] = []
    tests: list[str] = []
    request_classes: list[str] = []
    lane_ids: list[str] = []
    warnings: list[str] = []
    for template in resolved.get("templates", []) or []:
        defaults = _as_dict(template.get("project_defaults"))
        stacks.extend(_as_list(defaults.get("stack") or defaults.get("stacks")))
        request_classes.extend(_as_list(defaults.get("primary_use_cases")))
        test_command = str(defaults.get("test_command") or "")
        if "pytest" in test_command.lower():
            tests.append("pytest")
        hints = " ".join(_as_list(template.get("fit_hints"))).lower()
        if "python" in hints:
            stacks.append("python")
        if "pytest" in hints:
            tests.append("pytest")
    for workset in resolved.get("benchmarks", []) or []:
        tags = {item.lower() for item in _as_list(workset.get("tags"))}
        if "pytest" in tags:
            tests.append("pytest")
        if "auth" in tags or "login" in tags:
            request_classes.extend(["bug_fix", "regression_test"])
    lane = resolved.get("lane")
    if isinstance(lane, dict) and lane.get("lane_id"):
        lane_ids.append(str(lane.get("lane_id")))
    elif draft.lane_ref:
        lane_ids.append(draft.lane_ref)
    if not stacks:
        warnings.append("could not infer stack compatibility")
    if not tests:
        warnings.append("could not infer test framework compatibility")
    return {
        "stacks": _dedupe(stacks),
        "test_frameworks": _dedupe(tests),
        "lane_ids": _dedupe(lane_ids),
        "request_classes": _dedupe(request_classes),
        "warnings": warnings,
    }


def _collect_evidence_refs(root: Path, draft: PackDraft) -> dict[str, Any]:
    """local proof/qualification/canary refs를 찾는다. 없으면 빈 dict를 반환한다."""
    evidence: dict[str, Any] = {}
    proof_refs: list[str] = []
    for workset in draft.benchmark_refs:
        proof_refs.extend(_matching_files(root, root / ".cambrian" / "benchmarks" / "proof", workset))
    if proof_refs:
        evidence["proof_refs"] = _dedupe(proof_refs)
    qualification_refs: list[str] = []
    canary_refs: list[str] = []
    for template in draft.template_refs:
        qualification_refs.extend(_matching_files(root, root / ".cambrian" / "templates" / "qualifications", template))
        canary_refs.extend(_matching_files(root, root / ".cambrian" / "templates" / "canary_reports", template))
    if qualification_refs:
        evidence["qualification_refs"] = _dedupe(qualification_refs)
    if canary_refs:
        evidence["canary_report_refs"] = _dedupe(canary_refs)
    matrix_refs = _matching_files(root, root / ".cambrian" / "templates" / "challenge_matrices", "")
    if matrix_refs:
        evidence["challenge_matrix_refs"] = _dedupe(matrix_refs)
    latest_metrics = root / ".cambrian" / "metrics" / "latest.yaml"
    if latest_metrics.exists():
        evidence["metrics_refs"] = [_relative(latest_metrics, root)]
    if draft.benchmark_refs:
        evidence["benchmark_worksets"] = list(draft.benchmark_refs)
    return evidence


def _matching_files(root: Path, directory: Path, needle: str) -> list[str]:
    """needle을 이름에 포함하는 YAML 파일 상대 경로를 반환한다."""
    if not directory.exists():
        return []
    normalized = _slug(needle, "") if needle else ""
    refs: list[str] = []
    for path in sorted(directory.glob("*.yaml")):
        if not normalized or normalized in _slug(path.name, ""):
            refs.append(_relative(path, root))
    return refs


def _included_summary(artifacts: dict[str, Any]) -> dict[str, Any]:
    return {
        "workers": [str(item.get("agent_id") or item.get("id") or item.get("missing_ref")) for item in artifacts.get("workers", [])],
        "teams": [str(item.get("name") or item.get("team_id") or item.get("missing_ref")) for item in artifacts.get("teams", [])],
        "templates": [str(item.get("name") or item.get("template_id") or item.get("missing_ref")) for item in artifacts.get("templates", [])],
        "benchmarks": [str(item.get("name") or item.get("workset_id") or item.get("missing_ref")) for item in artifacts.get("benchmarks", [])],
        "lane": (artifacts.get("lane") or {}).get("lane_id") if isinstance(artifacts.get("lane"), dict) else None,
    }


def _policies_from_templates(templates: list[dict[str, Any]]) -> list[str]:
    policies: list[str] = []
    for template in templates:
        defaults = _as_dict(template.get("policy_defaults"))
        for key, value in defaults.items():
            if value is True:
                policies.append(str(key))
    return _dedupe(policies)


def _default_manifest_out_path(draft: PackDraft) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return default_generated_manifests_dir(repo_root) / f"{_slug(draft.pack_id, 'pack')}.cambrian-pack.yaml"


def _manifest_path_for_catalog(repo_root: Path, catalog_path: Path, manifest_path: Path, confirm: bool) -> Path:
    """catalog가 해석할 수 있도록 manifest를 packs/ 아래에 둔다."""
    target = Path(manifest_path).resolve()
    packs_dir = Path(catalog_path).resolve().parent
    try:
        target.relative_to(packs_dir)
        return target
    except ValueError:
        generated = default_generated_manifests_dir(repo_root) / target.name
        if confirm:
            generated.parent.mkdir(parents=True, exist_ok=True)
            if generated.resolve() != target:
                shutil.copyfile(target, generated)
        return generated.resolve()


def _catalog_entry_for_manifest(
    repo_root: Path,
    catalog_path: Path,
    manifest_path: Path,
    manifest: PackManifest,
    sha256: str,
    release_report: Any | None = None,
    release_report_ref: str | None = None,
) -> dict[str, Any]:
    """manifest에서 local catalog entry를 만든다."""
    payload = _load_yaml(manifest_path)
    tags = _dedupe(_manifest_tags(payload))
    maturity = str((release_report.maturity if release_report else None) or payload.get("maturity") or "candidate")
    proof_summary = release_report.proof_summary if release_report else None
    proof_status = str((proof_summary.proof_status if proof_summary else None) or "none")
    known_limits = _dedupe([*_as_list(payload.get("known_limits")), *_as_list(payload.get("warnings"))])
    catalog_dir = Path(catalog_path).resolve().parent
    try:
        manifest_ref = str(Path(manifest_path).resolve().relative_to(catalog_dir)).replace("\\", "/")
    except ValueError:
        manifest_ref = str(Path(manifest_path).resolve())
    return {
        "pack_id": manifest.pack_id,
        "pack_name": manifest.pack_name,
        "pack_kind": manifest.pack_kind,
        "version": manifest.version,
        "manifest_path": manifest_ref,
        "description": manifest.description,
        "tags": tags,
        "maturity": maturity,
        "proof_status": proof_status,
        "proof_refs": list(proof_summary.proof_refs) if proof_summary else [],
        "qualification_refs": list(proof_summary.qualification_refs) if proof_summary else [],
        "canary_refs": list(proof_summary.canary_refs) if proof_summary else [],
        "known_limits": known_limits,
        "release_report_ref": release_report_ref,
        "compatibility": manifest.compatibility,
        "manifest_sha256": sha256.lower(),
        "trust_level": "local",
        "warnings": list(manifest.warnings),
    }


def _manifest_tags(payload: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for key in ("workers", "teams", "templates", "benchmarks"):
        for item in payload.get(key, []) or []:
            if isinstance(item, dict):
                tags.extend(_as_list(item.get("tags")))
    compatibility = _as_dict(payload.get("compatibility"))
    tags.extend(_as_list(compatibility.get("request_classes")))
    return tags


def _publish_record(
    root: Path,
    *,
    pack_id: str,
    pack_name: str,
    pack_kind: str,
    version: str | None,
    manifest_ref: str,
    manifest_sha256: str,
    catalog_ref: str,
    status: str,
    maturity: str | None = None,
    proof_status: str | None = None,
    release_report_ref: str | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> PackPublishLocalRecord:
    return PackPublishLocalRecord(
        schema_version=SCHEMA_VERSION,
        publish_id=f"publish-{_slug(pack_id, 'pack')}-{_stamp()}",
        created_at=_now(),
        pack_id=pack_id,
        pack_name=pack_name,
        pack_kind=pack_kind,
        version=version,
        manifest_ref=manifest_ref,
        manifest_sha256=manifest_sha256,
        catalog_ref=catalog_ref,
        status=status,
        maturity=maturity,
        proof_status=proof_status,
        release_report_ref=release_report_ref,
        warnings=_dedupe(warnings or []),
        errors=_dedupe(errors or []),
    )


def _render_included(included: dict[str, Any]) -> list[str]:
    lines = ["", "Includes:"]
    for key in ("workers", "teams", "templates", "benchmarks"):
        value = included.get(key, [])
        rendered = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        lines.append(f"  {key}: {rendered or 'none'}")
    lines.append(f"  lane: {included.get('lane') or 'none'}")
    return lines


def _first_name(items: list[dict[str, Any]]) -> str | None:
    for item in items:
        if item.get("missing_ref"):
            continue
        return str(item.get("name") or item.get("team_id") or item.get("template_id") or item.get("workset_id") or "")
    return None


def _title_from_id(pack_id: str) -> str:
    return " ".join(part.capitalize() for part in _slug(pack_id, "pack").replace("_", "-").split("-"))


def _strip_none(value: Any) -> Any:
    """None/빈 dict/list를 manifest에서 제거한다."""
    if isinstance(value, dict):
        cleaned = {key: _strip_none(val) for key, val in value.items()}
        return {key: val for key, val in cleaned.items() if val not in (None, {}, [])}
    if isinstance(value, list):
        return [_strip_none(item) for item in value if item not in (None, {}, [])]
    return value


def _dedupe(values: list[Any]) -> list[Any]:
    """순서를 보존하며 중복을 제거한다."""
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
