"""local pack catalog를 정적 registry bundle로 내보낸다."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_catalog import PackCatalogStore
from engine.project_pack_install import SCHEMA_VERSION

logger = logging.getLogger(__name__)

REGISTRY_EXPORT_SCHEMA_VERSION = "1.0"
PRIVACY_BLOCK_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(^|\n)\s*old_text\s*:",
        r"(^|\n)\s*new_text\s*:",
        r"(^|\n)\s*raw_request\s*:",
        r"(^|\n)\s*session_log\s*:",
        r"(^|\n)\s*patch_text\s*:",
        r"[A-Za-z]:\\",
        r"/Users/",
        r"/home/",
        r"\.cambrian/packs/proof/",
    )
]


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명용 UTC timestamp를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str | None, fallback: str = "item") -> str:
    """파일명에 안전한 slug를 만든다."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def _relative(path: Path, root: Path) -> str:
    """root 기준 상대 경로를 반환한다."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except ValueError:
        return str(Path(path).resolve())


def _read_yaml(path: Path) -> dict[str, Any]:
    """YAML/JSON mapping을 읽는다."""
    target = Path(path).resolve()
    try:
        if target.suffix.lower() == ".json":
            payload = json.loads(target.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("registry export read failed: %s (%s)", target, exc)
        raise ValueError(f"artifact를 읽을 수 없습니다: {target}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"artifact top level must be a mapping: {target}")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """YAML artifact를 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    """JSON artifact를 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _sha256_file(path: Path) -> str:
    """파일 SHA-256 digest를 계산한다."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file(source: Path, target: Path) -> Path:
    """파일을 복사하고 부모 디렉터리를 만든다."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _as_list(value: Any) -> list[str]:
    """값을 문자열 리스트로 정규화한다."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _as_dict(value: Any) -> dict[str, Any]:
    """mapping 값만 dict로 반환한다."""
    return dict(value) if isinstance(value, dict) else {}


@dataclass
class RegistryExportEntry:
    """정적 registry bundle의 pack 단위 export 결과."""

    pack_id: str
    namespace: str | None
    version: str | None
    pack_name: str
    pack_kind: str
    manifest_source_ref: str
    manifest_export_ref: str
    manifest_sha256: str
    proof_export_source_ref: str | None
    proof_export_ref: str | None
    proof_status: str | None
    reputation_verdict: str | None
    maturity: str | None
    known_limits: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class RegistryExportBundle:
    """정적 registry bundle export 결과."""

    schema_version: str
    export_id: str
    generated_at: str
    source_catalog_ref: str
    output_dir: str
    registry_name: str | None
    namespace: str | None
    entries: list[RegistryExportEntry]
    catalog_ref: str
    checksum_ref: str
    registry_manifest_ref: str
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["entries"] = [entry.to_dict() for entry in self.entries]
        return payload


@dataclass
class RegistryExportCheckReport:
    """정적 registry bundle 검사 결과."""

    schema_version: str
    check_id: str
    generated_at: str
    bundle_dir: str
    catalog_ref: str | None
    pack_count: int
    manifest_count: int
    proof_export_count: int
    digest_matches: bool
    privacy_safe: bool
    registry_sync_compatible: bool
    status: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


class RegistryBundleExporter:
    """local catalog를 static registry bundle로 내보낸다."""

    def export(
        self,
        project_root: Path,
        out_dir: Path,
        registry_name: str | None = None,
        namespace: str | None = None,
        include_unproven: bool = True,
    ) -> RegistryExportBundle:
        """정적 호스팅 가능한 registry bundle을 생성한다."""
        root = Path(project_root).resolve()
        output = Path(out_dir).resolve()
        catalog_path = _default_catalog_path(root)
        catalog = PackCatalogStore().load(catalog_path)
        registry = registry_name or "cambrian-static"
        manifests_dir = output / "manifests"
        proof_dir = output / "proof"
        warnings: list[str] = []
        errors: list[str] = []
        entries: list[RegistryExportEntry] = []
        packs: list[dict[str, Any]] = []

        if catalog.errors:
            errors.extend(catalog.errors)
        for entry in catalog.entries:
            if str(entry.maturity or "").lower() == "retired":
                warnings.append(f"retired pack skipped: {entry.pack_id}")
                continue
            if not include_unproven and str(entry.maturity or "").lower() in {"draft"}:
                warnings.append(f"unproven draft pack skipped: {entry.pack_id}")
                continue
            manifest_source = _resolve_catalog_ref(catalog_path, entry.manifest_path)
            if not manifest_source.exists():
                errors.append(f"manifest missing for {entry.pack_id}: {manifest_source}")
                continue
            manifest_target = manifests_dir / Path(entry.manifest_path).name
            _copy_file(manifest_source, manifest_target)
            manifest_sha = _sha256_file(manifest_target)
            declared_sha = str(entry.manifest_sha256 or "").strip().lower()
            if declared_sha and declared_sha != manifest_sha:
                warnings.append(f"manifest digest refreshed for {entry.pack_id}: catalog value differed")

            proof_source = _find_public_proof_export(root, catalog_path, entry.pack_id)
            proof_ref = None
            proof_payload: dict[str, Any] | None = None
            proof_status = entry.proof_status or "local_proof_required"
            reputation = None
            known_limits = list(entry.known_limits or entry.warnings or [])
            if proof_source is not None:
                proof_payload = _read_yaml(proof_source)
                if proof_payload.get("privacy_classification") == "public_safe":
                    proof_target = proof_dir / f"{entry.pack_id}.public-proof.yaml"
                    _write_yaml(proof_target, _bundle_public_proof_payload(proof_payload))
                    proof_ref = _relative(proof_target, output)
                    proof_status = str(proof_payload.get("proof_status") or proof_status)
                    reputation = str(proof_payload.get("reputation_verdict")) if proof_payload.get("reputation_verdict") is not None else None
                    known_limits = _as_list(proof_payload.get("known_limits")) or known_limits
                else:
                    warnings.append(f"non-public-safe proof export ignored for {entry.pack_id}")
            pack_namespace = namespace or entry.namespace or registry
            install_ref = f"{pack_namespace}/{entry.pack_id}" if pack_namespace else entry.pack_id
            pack_payload = {
                "pack_id": entry.pack_id,
                "namespace": pack_namespace,
                "version": entry.version,
                "pack_name": entry.pack_name,
                "pack_kind": entry.pack_kind,
                "description": entry.description,
                "tags": list(entry.tags),
                "maturity": entry.maturity,
                "proof_status": proof_status,
                "reputation_verdict": reputation,
                "known_limits": known_limits,
                "compatibility": dict(entry.compatibility),
                "dependencies": list(entry.dependencies),
                "manifest_path": _relative(manifest_target, output),
                "manifest_sha256": manifest_sha,
                "proof_path": proof_ref,
                "proof": _public_proof_payload(proof_payload) if proof_payload else None,
                "trust_level": entry.trust_level or "local",
                "install_command": f"cambrian install pack {install_ref} --registry {registry}",
                "warnings": list(entry.warnings),
            }
            packs.append(pack_payload)
            entries.append(
                RegistryExportEntry(
                    pack_id=entry.pack_id,
                    namespace=pack_namespace,
                    version=entry.version,
                    pack_name=entry.pack_name,
                    pack_kind=entry.pack_kind,
                    manifest_source_ref=_relative(manifest_source, root),
                    manifest_export_ref=_relative(manifest_target, output),
                    manifest_sha256=manifest_sha,
                    proof_export_source_ref=_relative(proof_source, root) if proof_source else None,
                    proof_export_ref=proof_ref,
                    proof_status=proof_status,
                    reputation_verdict=reputation,
                    maturity=entry.maturity,
                    known_limits=known_limits,
                    warnings=list(entry.warnings),
                    errors=[],
                )
            )

        catalog_payload = {
            "schema_version": REGISTRY_EXPORT_SCHEMA_VERSION,
            "source_kind": "static_registry_bundle",
            "registry_name": registry,
            "namespace": namespace,
            "generated_at": _now(),
            "packs": packs,
            "warnings": warnings,
            "errors": errors,
        }
        catalog_out = _write_json(output / "catalog.json", catalog_payload)
        registry_out = _write_yaml(output / "registry.yaml", _registry_manifest_payload(registry, catalog_out, entries, output))
        checksum_out = _write_checksums(output, [catalog_out, registry_out, *sorted(manifests_dir.glob("*")), *sorted(proof_dir.glob("*"))])
        status = "failed" if errors else "exported"
        return RegistryExportBundle(
            schema_version=SCHEMA_VERSION,
            export_id=f"registry-export-{_slug(registry, 'registry')}-{_stamp()}",
            generated_at=_now(),
            source_catalog_ref=_relative(catalog_path, root),
            output_dir=_relative(output, root),
            registry_name=registry,
            namespace=namespace,
            entries=entries,
            catalog_ref=_relative(catalog_out, root),
            checksum_ref=_relative(checksum_out, root),
            registry_manifest_ref=_relative(registry_out, root),
            status=status,
            warnings=warnings,
            errors=errors,
        )


class RegistryBundleChecker:
    """정적 registry bundle의 무결성과 privacy-safe 여부를 검사한다."""

    def check(self, bundle_dir: Path) -> RegistryExportCheckReport:
        """bundle directory를 검사한다."""
        root = Path(bundle_dir).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        catalog_path = root / "catalog.json"
        registry_path = root / "registry.yaml"
        checksum_path = root / "checksums.sha256"
        if not catalog_path.exists():
            errors.append("catalog.json is missing")
        if not registry_path.exists():
            errors.append("registry.yaml is missing")
        if not checksum_path.exists():
            errors.append("checksums.sha256 is missing")
        catalog_payload: dict[str, Any] = {}
        if catalog_path.exists():
            try:
                catalog_payload = _read_yaml(catalog_path)
            except ValueError as exc:
                errors.append(str(exc))
        packs = catalog_payload.get("packs") if isinstance(catalog_payload.get("packs"), list) else []
        manifest_count = 0
        proof_count = 0
        digest_ok = True
        sync_compatible = bool(packs)
        for item in packs:
            if not isinstance(item, dict):
                sync_compatible = False
                errors.append("catalog contains non-mapping pack entry")
                continue
            manifest_ref = str(item.get("manifest_path") or item.get("manifest_ref") or "").strip()
            if not manifest_ref:
                sync_compatible = False
                errors.append(f"manifest path missing for {item.get('pack_id') or 'unknown'}")
                continue
            manifest_path = (root / manifest_ref).resolve()
            if not manifest_path.exists():
                digest_ok = False
                errors.append(f"manifest missing: {manifest_ref}")
            else:
                manifest_count += 1
                actual = _sha256_file(manifest_path)
                expected = str(item.get("manifest_sha256") or "").strip().lower()
                if expected and actual != expected:
                    digest_ok = False
                    errors.append(f"manifest digest mismatch: {manifest_ref}")
            proof_ref = str(item.get("proof_path") or "").strip()
            if proof_ref:
                proof_path = (root / proof_ref).resolve()
                if not proof_path.exists():
                    errors.append(f"proof export missing: {proof_ref}")
                else:
                    proof_count += 1
                    proof_payload = _read_yaml(proof_path)
                    if proof_payload.get("privacy_classification") != "public_safe":
                        errors.append(f"proof export is not public_safe: {proof_ref}")
        checksum_ok = _verify_checksums(root, checksum_path, errors) if checksum_path.exists() else False
        digest_ok = digest_ok and checksum_ok
        privacy_safe = _privacy_scan(root, errors, warnings)
        status = "failed" if errors else ("warning" if warnings else "passed")
        return RegistryExportCheckReport(
            schema_version=SCHEMA_VERSION,
            check_id=f"registry-export-check-{_stamp()}",
            generated_at=_now(),
            bundle_dir=str(root),
            catalog_ref=str(catalog_path) if catalog_path.exists() else None,
            pack_count=len([item for item in packs if isinstance(item, dict)]),
            manifest_count=manifest_count,
            proof_export_count=proof_count,
            digest_matches=digest_ok,
            privacy_safe=privacy_safe,
            registry_sync_compatible=sync_compatible and not errors,
            status=status,
            warnings=warnings,
            errors=errors,
        )


def render_registry_export(bundle: RegistryExportBundle) -> str:
    """registry export 결과를 렌더링한다."""
    lines = [
        "Static registry bundle exported." if bundle.status == "exported" else "Static registry bundle export failed.",
        "",
        "Output:",
        f"  {bundle.output_dir}",
        "",
        "Packs:",
        f"  {len(bundle.entries)}",
        "",
        "Catalog:",
        f"  {bundle.catalog_ref}",
        "",
        "Next:",
        f"  cambrian registry add local-test {bundle.catalog_ref}",
        "  cambrian registry sync local-test",
    ]
    if bundle.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in bundle.warnings])
    if bundle.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in bundle.errors])
    return "\n".join(lines)


def render_registry_export_check(report: RegistryExportCheckReport) -> str:
    """registry export-check 결과를 렌더링한다."""
    lines = [
        "Registry Export Check",
        "==================================================",
        "",
        "Bundle:",
        f"  {report.bundle_dir}",
        "",
        "Status:",
        f"  {report.status}",
        "",
        "Checks:",
        f"  {'OK' if report.catalog_ref else 'X'} catalog exists",
        f"  {'OK' if report.manifest_count else 'X'} manifests exist",
        f"  {'OK' if report.digest_matches else 'X'} manifest/checksum hashes match",
        f"  {'OK' if report.privacy_safe else 'X'} proof exports are public-safe",
        f"  {'OK' if report.registry_sync_compatible else 'X'} registry sync compatible",
    ]
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def _default_catalog_path(root: Path) -> Path:
    """현재 프로젝트 catalog를 우선하고, 없으면 repo seed catalog로 fallback한다."""
    project_catalog = root / "packs" / "catalog.yaml"
    if project_catalog.exists():
        return project_catalog.resolve()
    return (Path(__file__).resolve().parents[1] / "packs" / "catalog.yaml").resolve()


def _resolve_catalog_ref(catalog_path: Path, ref: str) -> Path:
    """catalog 기준 상대 ref를 실제 path로 변환한다."""
    raw = Path(str(ref))
    if raw.is_absolute():
        return raw.resolve()
    return (catalog_path.parent / raw).resolve()


def _find_public_proof_export(root: Path, catalog_path: Path, pack_id: str) -> Path | None:
    """public-safe proof export를 찾는다."""
    candidates: list[Path] = []
    for base in [catalog_path.parent / "proof_exports", root / "packs" / "proof_exports", root / ".cambrian" / "packs" / "proof_exports"]:
        if not base.exists():
            continue
        candidates.extend(
            [
                base / f"{pack_id}.public-proof.yaml",
                base / f"{pack_id}.public-proof.yml",
                base / f"{pack_id}.public-proof.json",
            ]
        )
        candidates.extend(sorted(base.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True))
        candidates.extend(sorted(base.glob("*.yml"), key=lambda item: item.stat().st_mtime, reverse=True))
        candidates.extend(sorted(base.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True))
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.resolve()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        try:
            payload = _read_yaml(path)
        except ValueError:
            continue
        if str(payload.get("pack_id") or "") != pack_id:
            continue
        if payload.get("privacy_classification") == "public_safe":
            return path
    return None


def _public_proof_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """catalog에 넣을 public proof summary를 만든다."""
    if not payload or payload.get("privacy_classification") != "public_safe":
        return None
    metrics: dict[str, Any] = {}
    for metric in payload.get("public_metrics", []) or []:
        if not isinstance(metric, dict) or not metric.get("public_safe", True):
            continue
        key = str(metric.get("key") or "")
        if not key or key in {"used_count", "outcome_linked_count"}:
            continue
        metrics[key] = metric.get("value")
    return {
        "source": "local_public_export",
        "proof_status": payload.get("proof_status"),
        "reputation_verdict": payload.get("reputation_verdict"),
        "sample_size": payload.get("sample_size") or {},
        "metrics": metrics,
        "caveats": payload.get("caveats") or [],
        "known_limits": payload.get("known_limits") or [],
        "web_summary": payload.get("web_summary"),
        "privacy_classification": payload.get("privacy_classification"),
    }


def _bundle_public_proof_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """bundle에 복사할 proof export에서 로컬 provenance 경로를 제거한다."""
    allowed_keys = {
        "schema_version",
        "export_id",
        "generated_at",
        "pack_ref",
        "pack_id",
        "pack_name",
        "pack_kind",
        "namespace",
        "version",
        "privacy_classification",
        "reputation_verdict",
        "proof_status",
        "maturity_hint",
        "sample_size",
        "public_metrics",
        "best_observed_lane",
        "best_observed_workset",
        "known_limits",
        "safe_claims",
        "caveats",
        "redacted_fields",
        "blocked_fields",
        "web_summary",
        "install_command",
        "warnings",
        "errors",
    }
    sanitized = {key: payload.get(key) for key in allowed_keys if key in payload}
    sanitized["source"] = "privacy_safe_public_export"
    return sanitized


def _registry_manifest_payload(registry: str, catalog_out: Path, entries: list[RegistryExportEntry], output: Path) -> dict[str, Any]:
    """registry.yaml payload를 만든다."""
    return {
        "schema_version": REGISTRY_EXPORT_SCHEMA_VERSION,
        "registry_name": registry,
        "generated_at": _now(),
        "catalog_ref": _relative(catalog_out, output),
        "checksum_ref": "checksums.sha256",
        "packs": [
            {
                "pack_id": entry.pack_id,
                "namespace": entry.namespace,
                "version": entry.version,
                "manifest_ref": entry.manifest_export_ref,
                "manifest_sha256": entry.manifest_sha256,
                "proof_ref": entry.proof_export_ref,
            }
            for entry in entries
        ],
    }


def _write_checksums(output: Path, paths: list[Path]) -> Path:
    """bundle checksum file을 생성한다."""
    checksum_path = output / "checksums.sha256"
    lines: list[str] = []
    for path in paths:
        if not path.exists() or path.is_dir() or path == checksum_path:
            continue
        lines.append(f"{_sha256_file(path)}  {_relative(path, output)}")
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return checksum_path


def _verify_checksums(root: Path, checksum_path: Path, errors: list[str]) -> bool:
    """checksums.sha256 내용을 검증한다."""
    ok = True
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"checksum file cannot be read: {exc}")
        return False
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            ok = False
            errors.append(f"invalid checksum line: {line}")
            continue
        expected, rel = parts[0].strip().lower(), parts[1].strip()
        path = (root / rel).resolve()
        if not path.exists():
            ok = False
            errors.append(f"checksum target missing: {rel}")
            continue
        actual = _sha256_file(path)
        if actual != expected:
            ok = False
            errors.append(f"checksum mismatch: {rel}")
    return ok


def _privacy_scan(root: Path, errors: list[str], warnings: list[str]) -> bool:
    """bundle 파일에서 obvious private payload를 찾는다."""
    safe = True
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = _relative(path, root)
        if rel.startswith(".cambrian/packs/proof/"):
            safe = False
            errors.append(f"raw local proof card copied into bundle: {rel}")
            continue
        if path.suffix.lower() not in {".json", ".yaml", ".yml", ".sha256", ".txt"}:
            warnings.append(f"unknown bundle file type not scanned deeply: {rel}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            warnings.append(f"non-text bundle file skipped by privacy scanner: {rel}")
            continue
        except OSError as exc:
            safe = False
            errors.append(f"privacy scan read failed: {rel}: {exc}")
            continue
        for pattern in PRIVACY_BLOCK_PATTERNS:
            if pattern.search(text.replace("\\\\", "\\")):
                safe = False
                errors.append(f"privacy-sensitive marker found in {rel}: {pattern.pattern}")
                break
    return safe
