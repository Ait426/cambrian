"""Pack manifest 기반 로컬 설치 코어."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
MANIFEST_SCHEMA_VERSION = "1.0"
SUPPORTED_PACK_KINDS = {"worker", "team", "template", "lane"}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓰기 좋은 UTC 타임스탬프를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str | None, fallback: str = "item") -> str:
    """문자열을 파일명과 id에 안전한 slug로 바꾼다."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _atomic_write_text(path: Path, content: str) -> None:
    """텍스트 파일을 원자적으로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(content)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML 파일을 dict로 읽는다."""
    target = Path(path).resolve()
    if not target.exists():
        return {}
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("pack install YAML load failed: %s (%s)", target, exc)
        raise ValueError(f"YAML을 읽을 수 없습니다: {target}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {target}")
    return payload


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """dict payload를 YAML 파일로 저장한다."""
    target = Path(path).resolve()
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _canonical(value: Any) -> Any:
    """비교용으로 dict/list를 안정적으로 정규화한다."""
    if isinstance(value, dict):
        ignored = {"created_at", "updated_at", "generated_at", "installed_at"}
        return {str(key): _canonical(val) for key, val in sorted(value.items()) if key not in ignored}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _digest_payload(payload: dict[str, Any]) -> str:
    """payload의 안정적 sha256 digest를 만든다."""
    encoded = json.dumps(_canonical(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relative(path: Path, root: Path) -> str:
    """project root 기준 상대 경로를 반환한다."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(path).resolve())


def _as_list(value: Any) -> list[str]:
    """값을 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _as_dict(value: Any) -> dict[str, Any]:
    """값이 dict이면 복사하고 아니면 빈 dict를 반환한다."""
    return dict(value) if isinstance(value, dict) else {}


def _manifest_digest(path: Path, payload: dict[str, Any]) -> str:
    """원본 파일 내용이 있으면 파일 기준, 아니면 payload 기준 digest를 만든다."""
    target = Path(path)
    if target.exists():
        return hashlib.sha256(target.read_bytes()).hexdigest()
    return _digest_payload(payload)


def default_install_dir(project_root: Path) -> Path:
    """pack install 상태 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "install"


def default_installed_packs_path(project_root: Path) -> Path:
    """installed_packs.yaml 기본 경로를 반환한다."""
    return default_install_dir(project_root) / "installed_packs.yaml"


def default_manifest_copies_dir(project_root: Path) -> Path:
    """manifest copy 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "manifests"


def default_install_plans_dir(project_root: Path) -> Path:
    """install plan 저장 디렉터리를 반환한다."""
    return default_install_dir(project_root) / "plans"


def default_agent_registry_path(project_root: Path) -> Path:
    """agent registry 기본 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "registry.yaml"


def default_team_presets_path(project_root: Path) -> Path:
    """team preset 기본 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "teams.yaml"


def default_templates_path(project_root: Path) -> Path:
    """template library 기본 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "templates.yaml"


def default_benchmark_worksets_dir(project_root: Path) -> Path:
    """benchmark workset 기본 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "benchmarks" / "worksets"


def default_lane_playbook_path(project_root: Path) -> Path:
    """lane playbook 기본 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "lane" / "playbook.yaml"


@dataclass
class PackManifest:
    """설치 가능한 pack manifest."""

    schema_version: str
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    namespace: str | None
    description: str | None
    source: dict[str, Any]
    compatibility: dict[str, Any]
    workers: list[dict[str, Any]]
    teams: list[dict[str, Any]]
    templates: list[dict[str, Any]]
    benchmarks: list[dict[str, Any]]
    policies: list[str]
    lane: dict[str, Any] | None
    dependencies: list[dict[str, Any]]
    install: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    manifest_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackInstallPlan:
    """pack 설치 전 실행 계획."""

    schema_version: str
    generated_at: str
    pack_id: str
    pack_name: str
    pack_kind: str
    actions: list[str]
    target_artifacts: dict[str, Any]
    conflicts: list[str]
    warnings: list[str]
    errors: list[str]
    safe_to_install: bool

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackCompatibilityIssue:
    """프로젝트와 하네스 preset의 호환성 문제."""

    pack: str
    required: dict[str, str | None]
    detected: dict[str, str | None]
    recommended_harness: str | None
    next_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "incompatible_harness",
            "pack": self.pack,
            "required": dict(self.required),
            "detected": dict(self.detected),
            "recommended_harness": self.recommended_harness,
            "next_commands": list(self.next_commands),
        }


class IncompatibleHarnessError(ValueError):
    """잘못된 프로젝트 stack에 하네스 preset을 설치하려 할 때 발생한다."""

    def __init__(self, issue: PackCompatibilityIssue) -> None:
        self.issue = issue
        required = _format_required(issue.required)
        detected = _format_required(issue.detected)
        super().__init__(
            f"Cannot install {issue.pack} for this project. "
            f"Required: {required}. Detected: {detected}."
        )

    def to_dict(self) -> dict[str, Any]:
        return self.issue.to_dict()


@dataclass
class InstalledPackRecord:
    """설치된 pack provenance 레코드."""

    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    namespace: str | None
    installed_at: str
    source_kind: str | None
    source_ref: str | None
    manifest_ref: str | None
    installed_artifacts: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    manifest_digest: str | None = None
    manifest_sha256: str | None = None
    manifest_size_bytes: int | None = None
    trust_level: str | None = None
    verified_at: str | None = None
    status: str = "installed"
    updated_at: str | None = None
    uninstalled_at: str | None = None
    latest_manifest_ref: str | None = None
    manifest_history: list[str] = field(default_factory=list)
    update_history: list[str] = field(default_factory=list)
    uninstall_ref: str | None = None
    resolved_dependencies: list[str] = field(default_factory=list)
    resolved_graph_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class InstalledPackIndex:
    """설치된 pack index."""

    schema_version: str
    updated_at: str
    packs: list[InstalledPackRecord]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return {
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
            "packs": [record.to_dict() for record in self.packs],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class PackManifestLoader:
    """pack manifest loader."""

    def load(self, path: Path) -> PackManifest:
        """manifest YAML을 로드하고 필수 필드를 검증한다."""
        target = Path(path).resolve()
        if not target.exists():
            raise FileNotFoundError(f"pack manifest not found: {target}")
        payload = _load_yaml(target)
        missing = [
            key
            for key in ("schema_version", "pack_id", "pack_name", "pack_kind")
            if not str(payload.get(key) or "").strip()
        ]
        if missing:
            raise ValueError(f"pack manifest missing required fields: {', '.join(missing)}")
        pack_kind = str(payload.get("pack_kind")).strip()
        if pack_kind not in SUPPORTED_PACK_KINDS:
            raise ValueError(f"unsupported pack kind: {pack_kind}")
        manifest = PackManifest(
            schema_version=str(payload.get("schema_version") or MANIFEST_SCHEMA_VERSION),
            pack_id=str(payload.get("pack_id")).strip(),
            pack_name=str(payload.get("pack_name")).strip(),
            pack_kind=pack_kind,
            version=str(payload.get("version")) if payload.get("version") is not None else None,
            namespace=str(payload.get("namespace")).strip() if payload.get("namespace") is not None else None,
            description=str(payload.get("description")) if payload.get("description") is not None else None,
            source=_as_dict(payload.get("source")),
            compatibility=_as_dict(payload.get("compatibility")),
            workers=[dict(item) for item in payload.get("workers", []) if isinstance(item, dict)],
            teams=[dict(item) for item in payload.get("teams", []) if isinstance(item, dict)],
            templates=[dict(item) for item in payload.get("templates", []) if isinstance(item, dict)],
            benchmarks=[dict(item) for item in payload.get("benchmarks", []) if isinstance(item, dict)],
            policies=[str(item) for item in payload.get("policies", []) if item],
            lane=dict(payload.get("lane")) if isinstance(payload.get("lane"), dict) else None,
            dependencies=[
                dict(item)
                for item in payload.get("dependencies", []) or []
                if isinstance(item, dict)
            ],
            install=_as_dict(payload.get("install")),
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
            manifest_digest=_manifest_digest(target, payload),
        )
        _validate_manifest_content(manifest)
        return manifest


class PackInstallPlanner:
    """pack install plan builder."""

    def build_plan(self, project_root: Path, manifest: PackManifest, allow_update: bool = False) -> PackInstallPlan:
        """현재 project state와 manifest를 비교해 안전한 설치 계획을 만든다."""
        root = Path(project_root).resolve()
        warnings = list(manifest.warnings)
        errors = list(manifest.errors)
        conflicts: list[str] = []
        actions: list[str] = []
        target_artifacts = _target_artifacts(root, manifest)

        _validate_install_policy(manifest, errors)
        installed_index = InstalledPackStore().load(default_installed_packs_path(root))
        existing_pack = _find_installed_pack(installed_index, manifest.pack_id)
        if existing_pack is not None:
            if existing_pack.manifest_digest and manifest.manifest_digest and existing_pack.manifest_digest != manifest.manifest_digest:
                if allow_update:
                    actions.append(f"update installed pack manifest {manifest.pack_id}")
                    warnings.append("pack manifest differs from installed copy; update path preserves manifest history")
                else:
                    conflicts.append(
                        f"pack id already installed with different manifest content: {manifest.pack_id}"
                    )
            else:
                warnings.append(f"pack already installed; reinstall will be idempotent: {manifest.pack_id}")
                actions.append("skip duplicate provenance record")

        _plan_workers(root, manifest, actions, conflicts)
        _plan_teams(root, manifest, actions, conflicts, errors)
        _plan_templates(root, manifest, actions, conflicts, errors)
        _plan_benchmarks(root, manifest, actions, conflicts)
        _plan_lane(root, manifest, actions, warnings, errors)

        safe = not conflicts and not errors
        return PackInstallPlan(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            pack_id=manifest.pack_id,
            pack_name=manifest.pack_name,
            pack_kind=manifest.pack_kind,
            actions=_dedupe(actions),
            target_artifacts=target_artifacts,
            conflicts=_dedupe(conflicts),
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
            safe_to_install=safe,
        )


class PackInstaller:
    """pack manifest를 로컬 `.cambrian/` library에 설치한다."""

    def install(
        self,
        project_root: Path,
        manifest_path: Path,
        dry_run: bool = False,
        source_kind_override: str | None = None,
        source_ref_override: str | None = None,
        allow_update: bool = False,
        expected_sha256: str | None = None,
        require_trusted: bool = False,
        trust_level_override: str | None = None,
    ) -> PackInstallPlan:
        """manifest 설치를 수행하거나 dry-run 계획만 반환한다."""
        root = Path(project_root).resolve()
        source_path = Path(manifest_path).resolve()
        manifest = PackManifestLoader().load(source_path)
        source_kind = source_kind_override or (
            str(manifest.source.get("kind")) if manifest.source.get("kind") is not None else "local_file"
        )
        source_ref = source_ref_override or (
            str(manifest.source.get("origin_ref")) if manifest.source.get("origin_ref") is not None else _relative(source_path, root)
        )
        from engine.project_pack_trust import PackIntegrityHasher, PackTrustPolicy

        integrity = PackIntegrityHasher().hash_file(source_path)
        if expected_sha256 and integrity.sha256.lower() != str(expected_sha256).lower():
            raise ValueError(
                f"pack manifest digest mismatch: expected {str(expected_sha256).lower()} actual {integrity.sha256}"
            )
        compatibility_issue = check_pack_project_compatibility(root, manifest)
        if compatibility_issue is not None:
            raise IncompatibleHarnessError(compatibility_issue)
        trust_summary = PackTrustPolicy().classify_source(
            source_kind,
            source_ref,
            trust_level_override=trust_level_override,
            integrity=integrity,
        )
        if require_trusted and trust_summary.trust_level != "trusted":
            raise ValueError(f"pack source is not trusted: {source_kind or 'unknown'} ({trust_summary.trust_level})")
        plan = PackInstallPlanner().build_plan(root, manifest, allow_update=allow_update)
        if dry_run or not plan.safe_to_install:
            return plan

        self._install_workers(root, manifest, allow_update=allow_update)
        self._install_teams(root, manifest, allow_update=allow_update)
        self._install_templates(root, manifest, allow_update=allow_update)
        self._install_benchmarks(root, manifest, allow_update=allow_update)
        self._install_lane(root, manifest)
        manifest_copy = self._copy_manifest(root, manifest, source_path)
        record = InstalledPackRecord(
            pack_id=manifest.pack_id,
            pack_name=manifest.pack_name,
            pack_kind=manifest.pack_kind,
            version=manifest.version,
            namespace=manifest.namespace,
            installed_at=_now(),
            source_kind=source_kind,
            source_ref=source_ref,
            manifest_ref=_relative(manifest_copy, root),
            installed_artifacts=_installed_artifacts(manifest),
            warnings=list(manifest.warnings),
            errors=[],
            manifest_digest=manifest.manifest_digest,
            manifest_sha256=integrity.sha256,
            manifest_size_bytes=integrity.size_bytes,
            trust_level=trust_summary.trust_level,
            verified_at=integrity.computed_at,
            status="installed",
            latest_manifest_ref=_relative(manifest_copy, root),
            manifest_history=[_relative(manifest_copy, root)],
        )
        InstalledPackStore().add(default_installed_packs_path(root), record, allow_update=allow_update)
        from engine.project_pack_trust import PackLockStore, lock_entry_from_record, default_pack_lock_path

        PackLockStore().upsert(default_pack_lock_path(root), lock_entry_from_record(record))
        return plan

    def _install_workers(self, root: Path, manifest: PackManifest, allow_update: bool = False) -> None:
        path = default_agent_registry_path(root)
        payload = _load_yaml(path)
        agents = list(payload.get("agents", []) if isinstance(payload.get("agents"), list) else [])
        changed = False
        for worker in manifest.workers:
            entry = _worker_entry(manifest, worker)
            if _upsert_idempotent(agents, "agent_id", entry, _same_worker, replace_pack_owned=allow_update):
                changed = True
        if changed or not path.exists():
            payload = {
                "schema_version": str(payload.get("schema_version") or SCHEMA_VERSION),
                "generated_at": str(payload.get("generated_at") or _now()),
                "harness_id": payload.get("harness_id"),
                "agents": agents,
                "warnings": list(payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []),
                "errors": list(payload.get("errors", []) if isinstance(payload.get("errors"), list) else []),
            }
            _save_yaml(path, payload)

    def _install_teams(self, root: Path, manifest: PackManifest, allow_update: bool = False) -> None:
        path = default_team_presets_path(root)
        payload = _load_yaml(path)
        teams = list(payload.get("teams", []) if isinstance(payload.get("teams"), list) else [])
        changed = False
        for team in manifest.teams:
            entry = _team_entry(manifest, team)
            if _upsert_idempotent(teams, "team_id", entry, _same_team, replace_pack_owned=allow_update):
                changed = True
        if changed or not path.exists():
            payload = {
                "schema_version": str(payload.get("schema_version") or SCHEMA_VERSION),
                "updated_at": _now(),
                "active_team_id": payload.get("active_team_id"),
                "teams": teams,
                "warnings": list(payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []),
                "errors": list(payload.get("errors", []) if isinstance(payload.get("errors"), list) else []),
            }
            _save_yaml(path, payload)

    def _install_templates(self, root: Path, manifest: PackManifest, allow_update: bool = False) -> None:
        path = default_templates_path(root)
        payload = _load_yaml(path)
        templates = list(payload.get("templates", []) if isinstance(payload.get("templates"), list) else [])
        changed = False
        for template in manifest.templates:
            entry = _template_entry(manifest, template)
            if _upsert_idempotent(templates, "template_id", entry, _same_template, replace_pack_owned=allow_update):
                changed = True
        if changed or not path.exists():
            payload = {
                "schema_version": str(payload.get("schema_version") or SCHEMA_VERSION),
                "updated_at": _now(),
                "active_template_name": payload.get("active_template_name"),
                "templates": templates,
                "warnings": list(payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []),
                "errors": list(payload.get("errors", []) if isinstance(payload.get("errors"), list) else []),
            }
            _save_yaml(path, payload)

    def _install_benchmarks(self, root: Path, manifest: PackManifest, allow_update: bool = False) -> None:
        for benchmark in manifest.benchmarks:
            entry = _workset_entry(manifest, benchmark)
            path = default_benchmark_worksets_dir(root) / f"workset_{_slug(entry.get('name') or entry.get('workset_id'), 'workset')}.yaml"
            if not path.exists():
                _save_yaml(path, entry)
                continue
            existing = _load_yaml(path)
            if allow_update and existing.get("source_pack_id") == manifest.pack_id:
                _save_yaml(path, entry)
                continue
            if _same_workset(existing, entry):
                continue
            raise ValueError(f"benchmark workset conflict: {entry.get('name')}")

    def _install_lane(self, root: Path, manifest: PackManifest) -> None:
        if not manifest.lane:
            return
        path = default_lane_playbook_path(root)
        payload = _load_yaml(path)
        lane = dict(manifest.lane)
        installed = list(payload.get("installed_lane_packs", []) if isinstance(payload.get("installed_lane_packs"), list) else [])
        entry = {
            "pack_id": manifest.pack_id,
            "pack_name": manifest.pack_name,
            "version": manifest.version,
            "lane_id": str(lane.get("lane_id") or ""),
            "label": str(lane.get("label") or ""),
            "default_team": lane.get("default_team"),
            "default_template": lane.get("default_template"),
            "default_workset": lane.get("default_workset"),
            "installed_at": _now(),
            "source_kind": "installed_pack",
            "source_pack_id": manifest.pack_id,
        }
        existing_index = next(
            (index for index, item in enumerate(installed) if isinstance(item, dict) and item.get("pack_id") == manifest.pack_id),
            None,
        )
        if existing_index is None:
            installed.append(entry)
        else:
            installed[existing_index] = {**installed[existing_index], **entry}
        payload = {
            "schema_version": str(payload.get("schema_version") or SCHEMA_VERSION),
            "updated_at": _now(),
            "lane_id": str(payload.get("lane_id") or lane.get("lane_id") or ""),
            "label": str(payload.get("label") or lane.get("label") or ""),
            "default_template_name": payload.get("default_template_name"),
            "backup_templates": list(payload.get("backup_templates", []) if isinstance(payload.get("backup_templates"), list) else []),
            "retired_templates": list(payload.get("retired_templates", []) if isinstance(payload.get("retired_templates"), list) else []),
            "source_decision_ref": payload.get("source_decision_ref"),
            "canary_template_name": payload.get("canary_template_name"),
            "canary_stage_id": payload.get("canary_stage_id"),
            "canary_status": payload.get("canary_status"),
            "installed_lane_packs": installed,
            "notes": list(payload.get("notes", []) if isinstance(payload.get("notes"), list) else []),
            "warnings": list(payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []),
            "errors": list(payload.get("errors", []) if isinstance(payload.get("errors"), list) else []),
        }
        _save_yaml(path, payload)

    def _copy_manifest(self, root: Path, manifest: PackManifest, source_path: Path) -> Path:
        version = _slug(manifest.version or "unversioned", "unversioned")
        digest = (manifest.manifest_digest or "unknown")[:12]
        target = default_manifest_copies_dir(root) / f"{_slug(manifest.pack_id, 'pack')}_{version}_{digest}.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        return target


class InstalledPackStore:
    """installed_packs.yaml 저장소."""

    def load(self, path: Path) -> InstalledPackIndex:
        """설치 pack index를 로드한다."""
        target = Path(path).resolve()
        if not target.exists():
            return InstalledPackIndex(
                schema_version=SCHEMA_VERSION,
                updated_at=_now(),
                packs=[],
            )
        payload = _load_yaml(target)
        records = [
            _installed_record_from_dict(item)
            for item in payload.get("packs", []) or []
            if isinstance(item, dict)
        ]
        return InstalledPackIndex(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            updated_at=str(payload.get("updated_at") or _now()),
            packs=records,
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def save(self, path: Path, index: InstalledPackIndex) -> Path:
        """설치 pack index를 저장한다."""
        index.updated_at = _now()
        return _save_yaml(Path(path).resolve(), index.to_dict())

    def add(self, path: Path, record: InstalledPackRecord, allow_update: bool = False) -> Path:
        """설치 pack 레코드를 중복 없이 추가한다."""
        target = Path(path).resolve()
        index = self.load(target)
        for existing in index.packs:
            if existing.pack_id != record.pack_id:
                continue
            if existing.namespace and record.namespace and existing.namespace != record.namespace:
                continue
            if existing.manifest_digest and record.manifest_digest and existing.manifest_digest != record.manifest_digest:
                if not allow_update:
                    raise ValueError(f"installed pack conflict: {record.pack_id}")
            existing.installed_artifacts = record.installed_artifacts
            existing.manifest_ref = record.manifest_ref
            existing.latest_manifest_ref = record.latest_manifest_ref or record.manifest_ref or existing.latest_manifest_ref
            existing.source_kind = record.source_kind or existing.source_kind
            existing.source_ref = record.source_ref or existing.source_ref
            existing.namespace = record.namespace or existing.namespace
            existing.warnings = _dedupe([*existing.warnings, *record.warnings])
            existing.errors = _dedupe([*existing.errors, *record.errors])
            existing.manifest_digest = record.manifest_digest or existing.manifest_digest
            existing.manifest_sha256 = record.manifest_sha256 or existing.manifest_sha256
            existing.manifest_size_bytes = record.manifest_size_bytes or existing.manifest_size_bytes
            existing.trust_level = record.trust_level or existing.trust_level
            existing.verified_at = record.verified_at or existing.verified_at
            existing.version = record.version or existing.version
            existing.resolved_dependencies = record.resolved_dependencies or existing.resolved_dependencies
            existing.resolved_graph_ref = record.resolved_graph_ref or existing.resolved_graph_ref
            if existing.status == "uninstalled":
                existing.status = "installed"
                existing.uninstalled_at = None
                existing.uninstall_ref = None
            for manifest_ref in [record.manifest_ref, record.latest_manifest_ref, *record.manifest_history]:
                if manifest_ref and manifest_ref not in existing.manifest_history:
                    existing.manifest_history.append(manifest_ref)
            return self.save(target, index)
        if record.latest_manifest_ref is None:
            record.latest_manifest_ref = record.manifest_ref
        if record.manifest_ref and record.manifest_ref not in record.manifest_history:
            record.manifest_history.append(record.manifest_ref)
        index.packs.append(record)
        return self.save(target, index)

    def find(self, index: InstalledPackIndex, pack_ref: str) -> InstalledPackRecord:
        """pack id 또는 name으로 설치 레코드를 찾는다."""
        wanted = str(pack_ref or "").strip()
        wanted_slug = _slug(wanted)
        for record in index.packs:
            namespaced = f"{record.namespace}/{record.pack_id}" if record.namespace else record.pack_id
            if record.pack_id == wanted or namespaced == wanted or record.pack_name == wanted or _slug(record.pack_name) == wanted_slug:
                return record
        raise KeyError(wanted)


def build_install_doctor_report(project_root: Path) -> dict[str, Any]:
    """설치된 pack의 참조 무결성 report를 만든다."""
    root = Path(project_root).resolve()
    index_path = default_installed_packs_path(root)
    index = InstalledPackStore().load(index_path)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "installed_packs_ref": _relative(index_path, root),
        "packs": [],
        "warnings": [],
        "errors": [],
    }
    if not index_path.exists():
        report["warnings"].append("no installed pack index found")
        return report
    for record in index.packs:
        pack_report = _doctor_pack(root, record)
        report["packs"].append(pack_report)
        report["warnings"].extend(pack_report.get("warnings", []))
        report["errors"].extend(pack_report.get("errors", []))
    report["warnings"] = _dedupe(report["warnings"])
    report["errors"] = _dedupe(report["errors"])
    return report


def render_install_plan(plan: PackInstallPlan) -> str:
    """install plan을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Install Plan",
        "==================================================",
        "",
        "Pack:",
        f"  {plan.pack_name}",
        f"  id   : {plan.pack_id}",
        f"  kind : {plan.pack_kind}",
        "",
        "Safety:",
        f"  safe_to_install: {str(plan.safe_to_install).lower()}",
    ]
    if plan.actions:
        lines.extend(["", "Actions:"])
        lines.extend([f"  - {item}" for item in plan.actions])
    if plan.conflicts:
        lines.extend(["", "Conflicts:"])
        lines.extend([f"  - {item}" for item in plan.conflicts])
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in plan.warnings])
    if plan.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in plan.errors])
    lines.extend(["", "Targets:"])
    for key, value in plan.target_artifacts.items():
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) or "none"
        else:
            rendered = str(value)
        lines.append(f"  {key}: {rendered}")
    return "\n".join(lines)


def render_install_result(plan: PackInstallPlan) -> str:
    """설치 결과를 렌더링한다."""
    installed = plan.target_artifacts.get("installed_counts", {})
    lines = [
        "Pack install completed.",
        "",
        "Pack:",
        f"  {plan.pack_name}",
        "",
        "Installed:",
        f"  workers   : {installed.get('workers', 0)}",
        f"  teams     : {installed.get('teams', 0)}",
        f"  templates : {installed.get('templates', 0)}",
        f"  benchmarks: {installed.get('benchmarks', 0)}",
        f"  lane      : {installed.get('lane') or 'none'}",
        "",
        "Saved:",
        f"  {plan.target_artifacts.get('installed_packs')}",
        f"  {plan.target_artifacts.get('manifest_copy')}",
    ]
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in plan.warnings])
    return "\n".join(lines)


def render_installed_pack_list(index: InstalledPackIndex) -> str:
    """설치 pack 목록을 렌더링한다."""
    lines = ["Installed Packs", "==================================================", ""]
    if not index.packs:
        lines.append("none")
        return "\n".join(lines)
    for record in index.packs:
        lines.extend([
            f"- {record.pack_id}",
            f"  name     : {record.pack_name}",
            f"  kind     : {record.pack_kind}",
            f"  version  : {record.version or 'none'}",
            f"  status   : {record.status}",
            f"  installed: {record.installed_at}",
        ])
    return "\n".join(lines)


def render_installed_pack_show(record: InstalledPackRecord) -> str:
    """설치 pack 상세를 렌더링한다."""
    lines = [
        "Installed Pack",
        "==================================================",
        "",
        "Pack:",
        f"  id      : {record.pack_id}",
        f"  name    : {record.pack_name}",
        f"  kind    : {record.pack_kind}",
        f"  version : {record.version or 'none'}",
        f"  status  : {record.status}",
        f"  installed_at: {record.installed_at}",
        f"  updated_at  : {record.updated_at or 'none'}",
        f"  uninstalled_at: {record.uninstalled_at or 'none'}",
        "",
        "Source:",
        f"  kind    : {record.source_kind or 'unknown'}",
        f"  ref     : {record.source_ref or 'unknown'}",
        f"  manifest: {record.latest_manifest_ref or record.manifest_ref or 'unknown'}",
        f"  sha256  : {record.manifest_sha256 or 'unknown'}",
        f"  trust   : {record.trust_level or 'unknown'}",
        "",
        "Artifacts:",
    ]
    for key, value in record.installed_artifacts.items():
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) or "none"
        else:
            rendered = str(value)
        lines.append(f"  {key}: {rendered}")
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    return "\n".join(lines)


def render_install_doctor(report: dict[str, Any]) -> str:
    """install doctor report를 렌더링한다."""
    lines = ["Install Doctor", "==================================================", ""]
    if not report.get("packs"):
        lines.append("No installed packs.")
    for pack in report.get("packs", []) or []:
        lines.extend(["Pack:", f"  {pack.get('pack_id')}", "", "Checks:"])
        for check in pack.get("checks", []) or []:
            marker = "OK" if check.get("status") == "ok" else "!!"
            lines.append(f"  {marker} {check.get('name')}: {check.get('detail')}")
        lines.append("")
    if report.get("warnings"):
        lines.append("Warnings:")
        lines.extend([f"  - {item}" for item in report.get("warnings", [])])
    if report.get("errors"):
        lines.append("Errors:")
        lines.extend([f"  - {item}" for item in report.get("errors", [])])
    return "\n".join(lines).rstrip()


def _validate_manifest_content(manifest: PackManifest) -> None:
    """manifest 내부 구조를 fail-closed로 검증한다."""
    if manifest.errors:
        raise ValueError(f"pack manifest contains errors: {', '.join(manifest.errors)}")
    if manifest.pack_kind == "worker" and not manifest.workers:
        raise ValueError("worker pack requires at least one worker")
    if manifest.pack_kind == "team" and not manifest.teams:
        raise ValueError("team pack requires at least one team")
    if manifest.pack_kind == "template" and not manifest.templates:
        raise ValueError("template pack requires at least one template")
    if manifest.pack_kind == "lane" and not manifest.lane:
        raise ValueError("lane pack requires lane metadata")


def _validate_install_policy(manifest: PackManifest, errors: list[str]) -> None:
    """install policy가 runtime 안전 경계를 넘지 않는지 검증한다."""
    install = manifest.install
    blocked_flags = {
        "auto_apply": "install must not auto apply templates",
        "auto_bootstrap": "install must not auto bootstrap projects",
        "auto_promote": "install must not auto promote lane defaults",
        "auto_canary": "install must not auto stage canaries",
    }
    for key, message in blocked_flags.items():
        if bool(install.get(key)):
            errors.append(message)


def _target_artifacts(root: Path, manifest: PackManifest) -> dict[str, Any]:
    """install target artifact 경로와 수량을 만든다."""
    version = _slug(manifest.version or "unversioned", "unversioned")
    digest = (manifest.manifest_digest or "unknown")[:12]
    manifest_copy = default_manifest_copies_dir(root) / f"{_slug(manifest.pack_id, 'pack')}_{version}_{digest}.yaml"
    return {
        "installed_packs": _relative(default_installed_packs_path(root), root),
        "manifest_copy": _relative(manifest_copy, root),
        "agents": _relative(default_agent_registry_path(root), root),
        "teams": _relative(default_team_presets_path(root), root),
        "templates": _relative(default_templates_path(root), root),
        "benchmarks": _relative(default_benchmark_worksets_dir(root), root),
        "lane": _relative(default_lane_playbook_path(root), root),
        "installed_counts": {
            "workers": len(manifest.workers),
            "teams": len(manifest.teams),
            "templates": len(manifest.templates),
            "benchmarks": len(manifest.benchmarks),
            "lane": (manifest.lane or {}).get("lane_id") if manifest.lane else None,
        },
    }


def _find_installed_pack(index: InstalledPackIndex, pack_id: str) -> InstalledPackRecord | None:
    """설치된 pack id를 찾는다."""
    for record in index.packs:
        if record.pack_id == pack_id:
            return record
    return None


def _plan_workers(root: Path, manifest: PackManifest, actions: list[str], conflicts: list[str]) -> None:
    payload = _load_yaml(default_agent_registry_path(root))
    existing = list(payload.get("agents", []) if isinstance(payload.get("agents"), list) else [])
    for worker in manifest.workers:
        entry = _worker_entry(manifest, worker)
        current = _find_by_key(existing, "agent_id", str(entry.get("agent_id")))
        if current is None:
            actions.append(f"install worker {entry.get('agent_id')}")
        elif _same_worker(current, entry):
            actions.append(f"worker already installed {entry.get('agent_id')}")
        else:
            conflicts.append(f"worker id already exists with different content: {entry.get('agent_id')}")


def _plan_teams(root: Path, manifest: PackManifest, actions: list[str], conflicts: list[str], errors: list[str]) -> None:
    payload = _load_yaml(default_team_presets_path(root))
    existing = list(payload.get("teams", []) if isinstance(payload.get("teams"), list) else [])
    available_workers = _existing_worker_ids(root) | {str(_worker_entry(manifest, worker).get("agent_id")) for worker in manifest.workers}
    for team in manifest.teams:
        entry = _team_entry(manifest, team)
        current = _find_by_key(existing, "team_id", str(entry.get("team_id"))) or _find_by_key(existing, "name", str(entry.get("name")))
        if current is None:
            actions.append(f"install team {entry.get('name')}")
        elif _same_team(current, entry):
            actions.append(f"team already installed {entry.get('name')}")
        else:
            conflicts.append(f"team name/id already exists with different content: {entry.get('name')}")
        refs = [entry.get("lead_agent_id"), *list(entry.get("supporting_agent_ids", []) or [])]
        for ref in refs:
            if ref and str(ref) not in available_workers:
                errors.append(f"team references missing worker: {entry.get('name')} -> {ref}")


def _plan_templates(root: Path, manifest: PackManifest, actions: list[str], conflicts: list[str], errors: list[str]) -> None:
    payload = _load_yaml(default_templates_path(root))
    existing = list(payload.get("templates", []) if isinstance(payload.get("templates"), list) else [])
    available_teams = _existing_team_names(root) | {str(_team_entry(manifest, team).get("name")) for team in manifest.teams}
    for template in manifest.templates:
        entry = _template_entry(manifest, template)
        current = _find_by_key(existing, "template_id", str(entry.get("template_id"))) or _find_by_key(existing, "name", str(entry.get("name")))
        if current is None:
            actions.append(f"install template {entry.get('name')}")
        elif _same_template(current, entry):
            actions.append(f"template already installed {entry.get('name')}")
        else:
            conflicts.append(f"template name/id already exists with different content: {entry.get('name')}")
        team_name = _template_team_default(entry)
        if team_name and team_name not in available_teams:
            errors.append(f"template references missing team: {entry.get('name')} -> {team_name}")


def _plan_benchmarks(root: Path, manifest: PackManifest, actions: list[str], conflicts: list[str]) -> None:
    for benchmark in manifest.benchmarks:
        entry = _workset_entry(manifest, benchmark)
        path = default_benchmark_worksets_dir(root) / f"workset_{_slug(entry.get('name') or entry.get('workset_id'), 'workset')}.yaml"
        if not path.exists():
            actions.append(f"install benchmark workset {entry.get('name')}")
            continue
        existing = _load_yaml(path)
        if _same_workset(existing, entry):
            actions.append(f"benchmark workset already installed {entry.get('name')}")
        else:
            conflicts.append(f"benchmark workset name already exists with different content: {entry.get('name')}")


def _plan_lane(root: Path, manifest: PackManifest, actions: list[str], warnings: list[str], errors: list[str]) -> None:
    if not manifest.lane:
        return
    lane = manifest.lane
    actions.append(f"register lane pack {lane.get('lane_id') or manifest.pack_id}")
    playbook = _load_yaml(default_lane_playbook_path(root))
    if playbook and playbook.get("default_template_name"):
        warnings.append("existing lane default is preserved; install does not switch stable default")
    available_teams = _existing_team_names(root) | {str(_team_entry(manifest, team).get("name")) for team in manifest.teams}
    available_templates = _existing_template_names(root) | {str(_template_entry(manifest, template).get("name")) for template in manifest.templates}
    available_worksets = _existing_workset_names(root) | {str(_workset_entry(manifest, benchmark).get("name")) for benchmark in manifest.benchmarks}
    if lane.get("default_team") and str(lane.get("default_team")) not in available_teams:
        errors.append(f"lane references missing team: {lane.get('default_team')}")
    if lane.get("default_template") and str(lane.get("default_template")) not in available_templates:
        errors.append(f"lane references missing template: {lane.get('default_template')}")
    if lane.get("default_workset") and str(lane.get("default_workset")) not in available_worksets:
        errors.append(f"lane references missing workset: {lane.get('default_workset')}")


def _worker_entry(manifest: PackManifest, item: dict[str, Any]) -> dict[str, Any]:
    worker_id = str(item.get("id") or item.get("agent_id") or "").strip()
    if not worker_id:
        raise ValueError("worker requires id")
    capabilities = _as_list(item.get("capabilities"))
    return {
        "schema_version": SCHEMA_VERSION,
        "agent_id": worker_id,
        "role_id": str(item.get("role_id") or _slug(worker_id)),
        "label": str(item.get("name") or item.get("label") or worker_id),
        "description": str(item.get("description") or f"Installed worker from pack {manifest.pack_id}."),
        "strengths": capabilities,
        "risks": _as_list(item.get("risks")),
        "preferred_signals": _as_list(item.get("preferred_signals")) or _as_list(item.get("tags")),
        "required_harness_conditions": _as_list(item.get("required_harness_conditions")),
        "blocked_conditions": _as_list(item.get("blocked_conditions")),
        "source_kind": "installed",
        "source_pack_id": manifest.pack_id,
        "status": "available",
        "project_fit_notes": _as_list(item.get("fit_hints")),
        "stats": {},
        "tags": _as_list(item.get("tags")),
        "warnings": _as_list(item.get("warnings")),
    }


def _team_entry(manifest: PackManifest, item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("team requires name")
    support = _as_list(item.get("supporting_agent_ids"))
    lead = str(item.get("lead_agent_id") or "").strip() or None
    members = _dedupe([lead or "", *support])
    return {
        "schema_version": SCHEMA_VERSION,
        "team_id": str(item.get("team_id") or _slug(name)),
        "name": name,
        "created_at": _now(),
        "updated_at": None,
        "description": str(item.get("description")) if item.get("description") is not None else None,
        "project_name": None,
        "harness_id": None,
        "lead_agent_id": lead,
        "supporting_agent_ids": support,
        "members": members,
        "tags": _as_list(item.get("tags")),
        "source_decision_refs": [],
        "source_dispatch_refs": [],
        "source_kind": "installed",
        "source_pack_id": manifest.pack_id,
        "fit_hints": _as_list(item.get("fit_hints")),
        "warnings": _as_list(item.get("warnings")),
        "errors": [],
    }


def _template_entry(manifest: PackManifest, item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("template requires name")
    source_origin = {
        "source_kind": "installed_pack",
        "source_pack_id": manifest.pack_id,
        "source_pack_name": manifest.pack_name,
        "source_pack_version": manifest.version,
        "manifest_digest": manifest.manifest_digest,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "template_id": str(item.get("template_id") or _slug(name)),
        "name": name,
        "created_at": _now(),
        "updated_at": None,
        "description": str(item.get("description")) if item.get("description") is not None else None,
        "source_project_name": manifest.pack_name,
        "source_harness_id": None,
        "template_kind": str(item.get("template_kind") or "installed"),
        "tags": _as_list(item.get("tags")),
        "project_defaults": _as_dict(item.get("project_defaults")),
        "safety_defaults": _as_dict(item.get("safety_defaults")),
        "agent_defaults": _as_dict(item.get("agent_defaults")),
        "team_defaults": _as_dict(item.get("team_defaults")),
        "policy_defaults": _as_dict(item.get("policy_defaults")),
        "context_defaults": _as_dict(item.get("context_defaults")),
        "fit_hints": _as_list(item.get("fit_hints")),
        "warnings": _as_list(item.get("warnings")),
        "errors": [],
        "source_kind": "installed",
        "source_pack_id": manifest.pack_id,
        "source_origin": source_origin,
    }


def _workset_entry(manifest: PackManifest, item: dict[str, Any]) -> dict[str, Any]:
    name = str(item.get("name") or "").strip()
    if not name:
        raise ValueError("benchmark workset requires name")
    return {
        "schema_version": SCHEMA_VERSION,
        "workset_id": str(item.get("workset_id") or _slug(name)),
        "created_at": _now(),
        "name": name,
        "description": str(item.get("description")) if item.get("description") is not None else None,
        "case_ids": _as_list(item.get("case_ids")),
        "tags": _as_list(item.get("tags")),
        "source_kind": "installed",
        "source_pack_id": manifest.pack_id,
        "warnings": _as_list(item.get("warnings")),
        "errors": [],
    }


def _installed_artifacts(manifest: PackManifest) -> dict[str, Any]:
    """manifest에서 설치 artifact 요약을 만든다."""
    return {
        "agents": [str(_worker_entry(manifest, item).get("agent_id")) for item in manifest.workers],
        "teams": [str(_team_entry(manifest, item).get("name")) for item in manifest.teams],
        "templates": [str(_template_entry(manifest, item).get("name")) for item in manifest.templates],
        "benchmarks": [str(_workset_entry(manifest, item).get("name")) for item in manifest.benchmarks],
        "lane": (manifest.lane or {}).get("lane_id") if manifest.lane else None,
    }


def _upsert_idempotent(
    items: list[dict[str, Any]],
    key: str,
    entry: dict[str, Any],
    same_fn,
    replace_pack_owned: bool = False,
) -> bool:
    """동일 key가 있으면 검증하고 없으면 append한다."""
    wanted = str(entry.get(key) or "")
    for index, existing in enumerate(items):
        if str(existing.get(key) or "") == wanted:
            if replace_pack_owned and existing.get("source_pack_id") == entry.get("source_pack_id"):
                items[index] = entry
                return True
            if same_fn(existing, entry):
                return False
            raise ValueError(f"conflicting installed artifact: {wanted}")
    items.append(entry)
    return True


def _same_worker(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    if existing.get("source_pack_id") == new.get("source_pack_id"):
        return True
    keys = ["agent_id", "label", "strengths", "tags"]
    return _canonical({key: existing.get(key) for key in keys}) == _canonical({key: new.get(key) for key in keys})


def _same_team(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    if existing.get("source_pack_id") == new.get("source_pack_id"):
        return True
    keys = ["team_id", "name", "lead_agent_id", "supporting_agent_ids", "members", "tags"]
    return _canonical({key: existing.get(key) for key in keys}) == _canonical({key: new.get(key) for key in keys})


def _same_template(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    if existing.get("source_pack_id") == new.get("source_pack_id"):
        return True
    keys = [
        "template_id",
        "name",
        "template_kind",
        "project_defaults",
        "safety_defaults",
        "agent_defaults",
        "team_defaults",
        "policy_defaults",
        "context_defaults",
    ]
    return _canonical({key: existing.get(key) for key in keys}) == _canonical({key: new.get(key) for key in keys})


def _same_workset(existing: dict[str, Any], new: dict[str, Any]) -> bool:
    if existing.get("source_pack_id") == new.get("source_pack_id"):
        return True
    keys = ["workset_id", "name", "description", "case_ids", "tags"]
    return _canonical({key: existing.get(key) for key in keys}) == _canonical({key: new.get(key) for key in keys})


def _find_by_key(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    """dict 리스트에서 key/value가 같은 항목을 찾는다."""
    for item in items:
        if isinstance(item, dict) and str(item.get(key) or "") == value:
            return item
    return None


def _existing_worker_ids(root: Path) -> set[str]:
    payload = _load_yaml(default_agent_registry_path(root))
    return {
        str(item.get("agent_id"))
        for item in payload.get("agents", []) or []
        if isinstance(item, dict) and item.get("agent_id")
    }


def _existing_team_names(root: Path) -> set[str]:
    payload = _load_yaml(default_team_presets_path(root))
    result: set[str] = set()
    for item in payload.get("teams", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("name"):
            result.add(str(item.get("name")))
        if item.get("team_id"):
            result.add(str(item.get("team_id")))
    return result


def _existing_template_names(root: Path) -> set[str]:
    payload = _load_yaml(default_templates_path(root))
    result: set[str] = set()
    for item in payload.get("templates", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("name"):
            result.add(str(item.get("name")))
        if item.get("template_id"):
            result.add(str(item.get("template_id")))
    return result


def _existing_workset_names(root: Path) -> set[str]:
    result: set[str] = set()
    for path in default_benchmark_worksets_dir(root).glob("workset_*.yaml"):
        payload = _load_yaml(path)
        if payload.get("name"):
            result.add(str(payload.get("name")))
        if payload.get("workset_id"):
            result.add(str(payload.get("workset_id")))
    return result


def _template_team_default(entry: dict[str, Any]) -> str | None:
    defaults = _as_dict(entry.get("team_defaults"))
    for key in ("active_team_id", "active_team_name", "default_team"):
        if defaults.get(key):
            return str(defaults.get(key))
    return None


def _installed_record_from_dict(payload: dict[str, Any]) -> InstalledPackRecord:
    """dict에서 InstalledPackRecord를 복원한다."""
    manifest_ref = str(payload.get("manifest_ref")) if payload.get("manifest_ref") is not None else None
    latest_manifest_ref = (
        str(payload.get("latest_manifest_ref"))
        if payload.get("latest_manifest_ref") is not None
        else manifest_ref
    )
    manifest_history = [str(item) for item in payload.get("manifest_history", []) if item]
    if manifest_ref and manifest_ref not in manifest_history:
        manifest_history.append(manifest_ref)
    if latest_manifest_ref and latest_manifest_ref not in manifest_history:
        manifest_history.append(latest_manifest_ref)
    return InstalledPackRecord(
        pack_id=str(payload.get("pack_id") or ""),
        pack_name=str(payload.get("pack_name") or ""),
        pack_kind=str(payload.get("pack_kind") or ""),
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        installed_at=str(payload.get("installed_at") or ""),
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        source_ref=str(payload.get("source_ref")) if payload.get("source_ref") is not None else None,
        manifest_ref=manifest_ref,
        installed_artifacts=_as_dict(payload.get("installed_artifacts")),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
        manifest_digest=str(payload.get("manifest_digest")) if payload.get("manifest_digest") is not None else None,
        manifest_sha256=str(payload.get("manifest_sha256")).lower()
        if payload.get("manifest_sha256") is not None
        else None,
        manifest_size_bytes=int(payload.get("manifest_size_bytes"))
        if payload.get("manifest_size_bytes") is not None
        else None,
        trust_level=str(payload.get("trust_level")) if payload.get("trust_level") is not None else None,
        verified_at=str(payload.get("verified_at")) if payload.get("verified_at") is not None else None,
        status=str(payload.get("status") or "installed"),
        updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
        uninstalled_at=str(payload.get("uninstalled_at")) if payload.get("uninstalled_at") is not None else None,
        latest_manifest_ref=latest_manifest_ref,
        manifest_history=manifest_history,
        update_history=[str(item) for item in payload.get("update_history", []) if item],
        uninstall_ref=str(payload.get("uninstall_ref")) if payload.get("uninstall_ref") is not None else None,
        resolved_dependencies=[str(item) for item in payload.get("resolved_dependencies", []) if item],
        resolved_graph_ref=str(payload.get("resolved_graph_ref")) if payload.get("resolved_graph_ref") is not None else None,
    )


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def check_pack_project_compatibility(project_root: Path, manifest: PackManifest) -> PackCompatibilityIssue | None:
    """현재 프로젝트에 명백히 맞지 않는 하네스 preset 설치를 차단한다."""
    expected_languages = _lower_values(manifest.compatibility.get("stacks") or manifest.compatibility.get("stack"))
    expected_tests = _lower_values(manifest.compatibility.get("test_frameworks"))
    if not expected_languages and not expected_tests:
        return None
    try:
        from engine.project_harness_profile import ProjectHarnessScanner

        profile = ProjectHarnessScanner().scan(project_root)
    except Exception as exc:
        logger.warning("pack compatibility scan skipped: %s", exc)
        return None
    detected_language = str(profile.language or "unknown").lower()
    detected_test = str(profile.test_framework or "unknown").lower()
    if detected_language == "unknown" and detected_test == "unknown":
        return None

    language_mismatch = bool(expected_languages and detected_language != "unknown" and detected_language not in expected_languages)
    test_mismatch = bool(expected_tests and detected_test != "unknown" and detected_test not in expected_tests)
    if not (language_mismatch or test_mismatch):
        return None

    recommended = profile.recommended_harnesses[0] if profile.recommended_harnesses else _recommended_from_profile(profile)
    if recommended == manifest.pack_id:
        return None
    if not recommended and not (language_mismatch and test_mismatch):
        return None

    return PackCompatibilityIssue(
        pack=manifest.pack_id,
        required={
            "language": _first_sorted(expected_languages),
            "test_framework": _first_sorted(expected_tests),
        },
        detected={
            "language": detected_language,
            "test_framework": detected_test,
        },
        recommended_harness=recommended,
        next_commands=["cambrian harness plan", "cambrian harness install"],
    )


def _recommended_from_profile(profile: Any) -> str | None:
    language = str(getattr(profile, "language", "") or "").lower()
    test_framework = str(getattr(profile, "test_framework", "") or "").lower()
    domains = {str(item).lower() for item in getattr(profile, "domains", [])}
    if language == "typescript" and test_framework == "jest" and {"auth", "tests"} <= domains:
        return "typescript-jest-auth-core"
    if language == "python" and test_framework == "pytest" and {"auth", "tests"} <= domains:
        return "auth-bug-core"
    return None


def _lower_values(value: Any) -> set[str]:
    return {str(item).strip().lower() for item in _as_list(value) if str(item).strip()}


def _first_sorted(values: set[str]) -> str | None:
    return sorted(values)[0] if values else None


def _format_required(values: dict[str, str | None]) -> str:
    parts = [value for value in [values.get("language"), values.get("test_framework")] if value]
    return " + ".join(parts) if parts else "unknown"


def _doctor_pack(root: Path, record: InstalledPackRecord) -> dict[str, Any]:
    """단일 installed pack의 doctor check를 만든다."""
    checks: list[dict[str, str]] = []
    warnings: list[str] = []
    errors: list[str] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "ok" if ok else "failed", "detail": detail})
        if not ok:
            errors.append(f"{record.pack_id}: {name} failed - {detail}")

    manifest_ref = record.manifest_ref or ""
    manifest_path = root / manifest_ref
    add_check("manifest copy exists", bool(manifest_ref and manifest_path.exists()), manifest_ref or "missing")

    worker_ids = _existing_worker_ids(root)
    team_names = _existing_team_names(root)
    template_names = _existing_template_names(root)
    workset_names = _existing_workset_names(root)

    for agent_id in record.installed_artifacts.get("agents", []) or []:
        add_check("worker installed", str(agent_id) in worker_ids, str(agent_id))
    for team in record.installed_artifacts.get("teams", []) or []:
        add_check("team installed", str(team) in team_names, str(team))
    for template in record.installed_artifacts.get("templates", []) or []:
        add_check("template installed", str(template) in template_names, str(template))
    for benchmark in record.installed_artifacts.get("benchmarks", []) or []:
        add_check("benchmark workset installed", str(benchmark) in workset_names, str(benchmark))

    lane_id = record.installed_artifacts.get("lane")
    if lane_id:
        playbook = _load_yaml(default_lane_playbook_path(root))
        installed = playbook.get("installed_lane_packs", []) if isinstance(playbook.get("installed_lane_packs"), list) else []
        lane_registered = any(isinstance(item, dict) and item.get("pack_id") == record.pack_id for item in installed)
        add_check("lane pack registered", lane_registered, str(lane_id))

    if manifest_path.exists():
        try:
            manifest = PackManifestLoader().load(manifest_path)
            install = manifest.install
            unsafe = [key for key in ("auto_apply", "auto_bootstrap", "auto_promote", "auto_canary") if install.get(key)]
            add_check("no auto install flags", not unsafe, ", ".join(unsafe) if unsafe else "safe")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            warnings.append(f"{record.pack_id}: manifest re-read warning - {exc}")

    return {
        "pack_id": record.pack_id,
        "pack_name": record.pack_name,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
