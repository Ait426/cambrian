"""pack release gate와 proof-aware web catalog sync."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_catalog import (
    PackCatalogResolver,
    default_pack_catalog_path,
    load_default_catalog,
    manifest_for_entry,
)
from engine.project_pack_install import (
    SCHEMA_VERSION,
    PackManifest,
    PackManifestLoader,
    _as_dict,
    _as_list,
    _load_yaml,
    _now,
    _relative,
    _save_yaml,
    _slug,
    _stamp,
)
from engine.project_pack_trust import PackIntegrityHasher, PackTrustPolicy

logger = logging.getLogger(__name__)

MATURITY_LEVELS = {"draft", "candidate", "verified", "canary", "recommended", "retired"}


@dataclass
class PackReleaseCheck:
    """release gate의 단일 check 결과."""

    check_id: str
    title: str
    status: str
    summary: str
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return asdict(self)


@dataclass
class PackProofSummary:
    """pack proof 요약."""

    proof_status: str
    worksets: list[str] = field(default_factory=list)
    proof_refs: list[str] = field(default_factory=list)
    qualification_refs: list[str] = field(default_factory=list)
    canary_refs: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return asdict(self)


@dataclass
class PackReleaseReport:
    """pack release gate 보고서."""

    schema_version: str
    report_id: str
    generated_at: str
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    manifest_ref: str
    manifest_sha256: str | None
    maturity: str
    proof_summary: PackProofSummary
    compatibility_summary: dict[str, Any]
    trust_summary: dict[str, Any]
    checks: list[PackReleaseCheck]
    safe_to_publish: bool
    require_proof_satisfied: bool
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        payload = asdict(self)
        payload["proof_summary"] = self.proof_summary.to_dict()
        payload["checks"] = [check.to_dict() for check in self.checks]
        return payload


@dataclass
class PackWebSyncRecord:
    """web catalog sync 결과."""

    schema_version: str
    sync_id: str
    created_at: str
    catalog_ref: str
    web_ref: str
    pack_count: int
    updated_artifacts: list[str] = field(default_factory=list)
    status: str = "synced"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 바꾼다."""
        return asdict(self)


def default_pack_releases_dir(project_root: Path) -> Path:
    """release report 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "releases"


def default_pack_web_sync_dir(project_root: Path) -> Path:
    """web-sync record 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "web_sync"


class PackReleaseChecker:
    """pack manifest를 catalog publish 전에 점검한다."""

    def check(
        self,
        project_root: Path,
        manifest_or_pack_ref: str,
        require_proof: bool = False,
    ) -> PackReleaseReport:
        """manifest path 또는 local catalog pack id에 대해 release gate를 실행한다."""
        root = Path(project_root).resolve()
        try:
            manifest_path, manifest, catalog_entry = _resolve_manifest_or_catalog(root, manifest_or_pack_ref)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            return _failed_release_report(root, manifest_or_pack_ref, str(exc))

        payload = _load_yaml(manifest_path)
        integrity = PackIntegrityHasher().hash_file(manifest_path)
        source = _as_dict(payload.get("source") or manifest.source)
        trust_level = str((catalog_entry or {}).get("trust_level") or payload.get("trust_level") or "").strip() or None
        trust = PackTrustPolicy().classify_source(
            str(source.get("kind") or "local_file"),
            str(source.get("origin_ref") or _relative(manifest_path, root)),
            trust_level_override=trust_level,
            integrity=integrity,
        )
        proof_summary = _proof_summary(root, payload, manifest)
        compatibility_summary = _compatibility_summary(manifest)
        checks = _build_checks(root, manifest, payload, integrity, trust.to_dict(), proof_summary)
        explicit_maturity = str(payload.get("maturity") or (catalog_entry or {}).get("maturity") or "").strip()
        maturity = _calculate_maturity(manifest, proof_summary, compatibility_summary, checks, explicit_maturity)
        warnings = _dedupe([warning for check in checks for warning in check.warnings])
        errors = _dedupe([error for check in checks for error in check.errors])
        if require_proof and proof_summary.proof_status in {"none", "local_only"}:
            errors.append("proof evidence is required but this pack has no usable proof refs")
        safe_to_publish = not any(check.status == "fail" for check in checks) and not errors
        require_proof_satisfied = proof_summary.proof_status not in {"none", "local_only"}
        report = PackReleaseReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"release-{_slug(manifest.pack_id, 'pack')}-{_stamp()}",
            generated_at=_now(),
            pack_id=manifest.pack_id,
            pack_name=manifest.pack_name,
            pack_kind=manifest.pack_kind,
            version=manifest.version,
            manifest_ref=_relative(manifest_path, root),
            manifest_sha256=integrity.sha256 or None,
            maturity=maturity,
            proof_summary=proof_summary,
            compatibility_summary=compatibility_summary,
            trust_summary=trust.to_dict(),
            checks=checks,
            safe_to_publish=safe_to_publish,
            require_proof_satisfied=require_proof_satisfied,
            summary=_summary_lines(maturity, proof_summary, safe_to_publish),
            warnings=warnings,
            errors=_dedupe(errors),
        )
        return report


class PackReleaseStore:
    """release report 저장소."""

    def save(self, report: PackReleaseReport, path: Path | None = None) -> Path:
        """release report를 저장한다."""
        target = Path(path) if path else default_pack_releases_dir(Path.cwd()) / f"{_slug(report.report_id, 'release')}.yaml"
        report.saved_ref = _relative(target, Path.cwd())
        _save_yaml(target, report.to_dict())
        return target

    def load(self, path: Path) -> PackReleaseReport:
        """저장된 release report를 읽는다."""
        payload = _load_yaml(path)
        proof = payload.get("proof_summary") if isinstance(payload.get("proof_summary"), dict) else {}
        checks = [PackReleaseCheck(**item) for item in payload.get("checks", []) if isinstance(item, dict)]
        return PackReleaseReport(
            schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
            report_id=str(payload.get("report_id") or f"release-{_stamp()}"),
            generated_at=str(payload.get("generated_at") or _now()),
            pack_id=str(payload.get("pack_id") or "unknown"),
            pack_name=str(payload.get("pack_name") or "unknown"),
            pack_kind=str(payload.get("pack_kind") or "unknown"),
            version=str(payload.get("version")) if payload.get("version") is not None else None,
            manifest_ref=str(payload.get("manifest_ref") or ""),
            manifest_sha256=str(payload.get("manifest_sha256")) if payload.get("manifest_sha256") is not None else None,
            maturity=str(payload.get("maturity") or "candidate"),
            proof_summary=PackProofSummary(
                proof_status=str(proof.get("proof_status") or "none"),
                worksets=_as_list(proof.get("worksets")),
                proof_refs=_as_list(proof.get("proof_refs")),
                qualification_refs=_as_list(proof.get("qualification_refs")),
                canary_refs=_as_list(proof.get("canary_refs")),
                metrics=_as_dict(proof.get("metrics")),
                warnings=_as_list(proof.get("warnings")),
            ),
            compatibility_summary=_as_dict(payload.get("compatibility_summary")),
            trust_summary=_as_dict(payload.get("trust_summary")),
            checks=checks,
            safe_to_publish=bool(payload.get("safe_to_publish")),
            require_proof_satisfied=bool(payload.get("require_proof_satisfied")),
            summary=_as_list(payload.get("summary")),
            warnings=_as_list(payload.get("warnings")),
            errors=_as_list(payload.get("errors")),
            saved_ref=str(path),
        )


class PackWebSyncer:
    """local catalog를 static web hiring desk asset으로 동기화한다."""

    def sync(
        self,
        project_root: Path,
        catalog_path: Path | None = None,
        web_dir: Path | None = None,
    ) -> PackWebSyncRecord:
        """packs/catalog.yaml을 web/assets/catalog.json과 detail page로 반영한다."""
        root = Path(project_root).resolve()
        repo_root = Path(__file__).resolve().parents[1]
        catalog = Path(catalog_path).resolve() if catalog_path else default_pack_catalog_path(repo_root)
        target_web = Path(web_dir).resolve() if web_dir else repo_root / "web"
        warnings: list[str] = []
        errors: list[str] = []
        updated: list[str] = []
        try:
            from tools.generate_web_catalog import generate

            generate(catalog, target_web)
            for rel in [
                "assets/catalog.json",
                "index.html",
                "packs/index.html",
            ]:
                path = target_web / rel
                if path.exists():
                    updated.append(_relative(path, root))
            for path in sorted((target_web / "packs").glob("*.html")) if (target_web / "packs").exists() else []:
                updated.append(_relative(path, root))
        except Exception as exc:  # noqa: BLE001 - web-sync record에 실패 원인을 남겨야 한다.
            logger.warning("pack web sync failed: %s", exc)
            errors.append(str(exc))
        catalog_payload = _load_yaml(catalog)
        entries = catalog_payload.get("entries", []) if isinstance(catalog_payload.get("entries"), list) else []
        record = PackWebSyncRecord(
            schema_version=SCHEMA_VERSION,
            sync_id=f"web-sync-{_stamp()}",
            created_at=_now(),
            catalog_ref=_relative(catalog, root),
            web_ref=_relative(target_web, root),
            pack_count=len(entries),
            updated_artifacts=_dedupe(updated),
            status="failed" if errors else "synced",
            warnings=warnings,
            errors=errors,
        )
        save_pack_web_sync_record(root, record)
        return record


def save_pack_release_report(project_root: Path, report: PackReleaseReport) -> str:
    """release report를 `.cambrian/packs/releases/`에 저장한다."""
    root = Path(project_root).resolve()
    path = default_pack_releases_dir(root) / f"{_slug(report.report_id, 'release')}.yaml"
    report.saved_ref = _relative(path, root)
    _save_yaml(path, report.to_dict())
    return report.saved_ref


def save_pack_web_sync_record(project_root: Path, record: PackWebSyncRecord) -> str:
    """web-sync record를 저장한다."""
    root = Path(project_root).resolve()
    path = default_pack_web_sync_dir(root) / f"{_slug(record.sync_id, 'web-sync')}.yaml"
    record.saved_ref = _relative(path, root)
    _save_yaml(path, record.to_dict())
    return record.saved_ref


def render_pack_release_report(report: PackReleaseReport) -> str:
    """release-check 결과를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Release Check",
        "==================================================",
        "",
        "Pack:",
        f"  {report.pack_id}",
        "",
        "Maturity:",
        f"  {report.maturity}",
        "",
        "Proof:",
        f"  {report.proof_summary.proof_status}",
        "",
        "Manifest:",
        f"  {report.manifest_ref}",
        f"  sha256: {report.manifest_sha256 or 'none'}",
        "",
        "Checks:",
    ]
    marker = {"pass": "✓", "warn": "!", "fail": "x"}
    for check in report.checks:
        lines.append(f"  {marker.get(check.status, '?')} {check.check_id}: {check.summary}")
    lines.extend(["", "Publish:", f"  {'allowed' if report.safe_to_publish else 'blocked'}"])
    if report.summary:
        lines.extend(["", "Summary:"])
        lines.extend([f"  - {item}" for item in report.summary])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def render_pack_web_sync(record: PackWebSyncRecord) -> str:
    """web-sync 결과를 렌더링한다."""
    lines = [
        "Web catalog synced." if record.status == "synced" else "Web catalog sync failed.",
        "",
        "Packs:",
        f"  {record.pack_count}",
        "",
        "Updated:",
    ]
    lines.extend([f"  {item}" for item in record.updated_artifacts] or ["  none"])
    if record.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in record.warnings])
    if record.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in record.errors])
    return "\n".join(lines)


def _resolve_manifest_or_catalog(
    root: Path,
    manifest_or_pack_ref: str,
) -> tuple[Path, PackManifest, dict[str, Any] | None]:
    """manifest path 또는 catalog pack id를 manifest로 해석한다."""
    rc_manifest_ref = _manifest_ref_from_rc(root, manifest_or_pack_ref)
    if rc_manifest_ref:
        manifest_or_pack_ref = rc_manifest_ref
    raw = Path(str(manifest_or_pack_ref))
    if raw.exists():
        manifest_path = raw.resolve()
        return manifest_path, PackManifestLoader().load(manifest_path), None
    repo_root = Path(__file__).resolve().parents[1]
    catalog = load_default_catalog(repo_root)
    entry = PackCatalogResolver().find_entry(catalog, str(manifest_or_pack_ref))
    manifest_path, manifest = manifest_for_entry(repo_root, entry)
    return manifest_path, manifest, entry.to_dict()


def _manifest_ref_from_rc(root: Path, target: str) -> str | None:
    """RC id/path가 들어오면 연결된 manifest path로 바꾼다."""
    try:
        from engine.project_pack_release_candidate import PackReleaseCandidateStore, resolve_pack_rc_path

        rc_path = resolve_pack_rc_path(root, str(target))
        rc = PackReleaseCandidateStore().load_rc(rc_path)
    except Exception as exc:  # noqa: BLE001 - RC가 아니면 기존 release-check 흐름을 유지한다.
        logger.debug("release-check target is not an RC ref: %s", exc)
        return None
    if not rc.manifest_ref:
        return None
    return str((root / rc.manifest_ref).resolve())


def _failed_release_report(root: Path, target: str, error: str) -> PackReleaseReport:
    """manifest 해석 실패 report."""
    check = PackReleaseCheck(
        check_id="schema_valid",
        title="Manifest schema",
        status="fail",
        summary="manifest could not be loaded",
        errors=[error],
    )
    return PackReleaseReport(
        schema_version=SCHEMA_VERSION,
        report_id=f"release-unknown-{_stamp()}",
        generated_at=_now(),
        pack_id=str(target),
        pack_name="unknown",
        pack_kind="unknown",
        version=None,
        manifest_ref=str(target),
        manifest_sha256=None,
        maturity="draft",
        proof_summary=PackProofSummary(proof_status="none", warnings=["manifest could not be loaded"]),
        compatibility_summary={},
        trust_summary={},
        checks=[check],
        safe_to_publish=False,
        require_proof_satisfied=False,
        errors=[error],
    )


def _build_checks(
    root: Path,
    manifest: PackManifest,
    payload: dict[str, Any],
    integrity: Any,
    trust_summary: dict[str, Any],
    proof_summary: PackProofSummary,
) -> list[PackReleaseCheck]:
    """release gate check 목록을 만든다."""
    checks: list[PackReleaseCheck] = []
    checks.append(_check("schema_valid", "Manifest schema", "pass", "manifest schema loaded"))
    unsafe = [
        key
        for key in ("auto_apply", "auto_bootstrap", "auto_promote", "auto_canary")
        if manifest.install.get(key) is True
    ]
    checks.append(
        _check(
            "install_policy_safe",
            "Install policy",
            "fail" if unsafe else "pass",
            "install policy is safe" if not unsafe else f"unsafe install flags: {', '.join(unsafe)}",
            errors=[f"{key} must be false" for key in unsafe],
        )
    )
    checks.append(
        _check(
            "integrity_available",
            "Manifest integrity",
            "pass" if integrity.sha256 and not integrity.errors else "fail",
            "manifest SHA-256 computed" if integrity.sha256 else "manifest SHA-256 unavailable",
            errors=list(integrity.errors),
        )
    )
    trust_level = str(trust_summary.get("trust_level") or "unknown")
    checks.append(
        _check(
            "trust_classified",
            "Trust classification",
            "warn" if trust_level == "unknown" else "pass",
            f"trust level: {trust_level}",
            warnings=["source trust is unknown"] if trust_level == "unknown" else [],
        )
    )
    compatibility = manifest.compatibility
    checks.append(
        _check(
            "compatibility_known",
            "Compatibility",
            "pass" if compatibility else "warn",
            "compatibility declared" if compatibility else "compatibility is missing",
            warnings=[] if compatibility else ["compatibility is missing"],
        )
    )
    embedded = bool(manifest.workers or manifest.teams or manifest.templates or manifest.benchmarks or manifest.lane)
    checks.append(
        _check(
            "included_artifacts_resolvable",
            "Included artifacts",
            "pass" if embedded else "fail",
            "manifest embeds installable artifact definitions" if embedded else "manifest has no included artifact definitions",
            errors=[] if embedded else ["manifest includes no worker/team/template/benchmark/lane definitions"],
        )
    )
    proof_refs = [
        *proof_summary.proof_refs,
        *proof_summary.qualification_refs,
        *proof_summary.canary_refs,
        *_as_list(_as_dict(payload.get("evidence")).get("metrics_refs")),
    ]
    status = "pass" if proof_summary.proof_status in {"verified", "strong"} else "warn"
    checks.append(
        _check(
            "proof_available",
            "Proof evidence",
            status,
            f"proof status: {proof_summary.proof_status}",
            evidence_refs=proof_refs,
            warnings=[] if status == "pass" else ["local proof required before claiming verified performance"],
        )
    )
    known_limits = _known_limits(payload, manifest)
    checks.append(
        _check(
            "known_limits_present",
            "Known limits",
            "pass" if known_limits else "warn",
            "known limits/warnings present" if known_limits else "known limits are missing",
            warnings=[] if known_limits else ["known limits should be declared"],
        )
    )
    derivative = _as_dict(payload.get("derivative"))
    unresolved = _as_list(derivative.get("unresolved_changes")) if derivative else []
    checks.append(
        _check(
            "derivative_unresolved_changes",
            "Derivative unresolved changes",
            "warn" if unresolved else "pass",
            "derivative draft has unresolved required changes" if unresolved else "no unresolved derivative changes",
            evidence_refs=_as_list(derivative.get("accepted_improvements")) if derivative else [],
            warnings=[f"unresolved derivative change: {item}" for item in unresolved],
        )
    )
    vnext_orders = _vnext_required_workorders(root, derivative, manifest.pack_id)
    checks.append(
        _check(
            "vnext_required_workorders",
            "vNext required work orders",
            "warn" if vnext_orders else "pass",
            "vNext derivative has unresolved required work orders" if vnext_orders else "no unresolved vNext required work orders",
            evidence_refs=[order.workorder_id for order in vnext_orders],
            warnings=[f"vNext required workorder unresolved: {order.title}" for order in vnext_orders],
        )
    )
    checks.append(_fake_proof_check(payload, root))
    return checks


def _check(
    check_id: str,
    title: str,
    status: str,
    summary: str,
    evidence_refs: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> PackReleaseCheck:
    return PackReleaseCheck(
        check_id=check_id,
        title=title,
        status=status,
        summary=summary,
        evidence_refs=evidence_refs or [],
        warnings=warnings or [],
        errors=errors or [],
    )


def _proof_summary(root: Path, payload: dict[str, Any], manifest: PackManifest) -> PackProofSummary:
    """manifest와 local evidence refs로 proof status를 계산한다."""
    evidence = _as_dict(payload.get("evidence"))
    worksets = _dedupe(_as_list(evidence.get("benchmark_worksets")))
    worksets.extend(
        [
            str(item.get("name") or item.get("workset_id"))
            for item in manifest.benchmarks
            if isinstance(item, dict) and (item.get("name") or item.get("workset_id"))
        ]
    )
    proof_refs = _dedupe([*_as_list(evidence.get("proof_refs")), *_scan_workset_refs(root, worksets)])
    qualification_refs = _dedupe(_as_list(evidence.get("qualification_refs")))
    canary_refs = _dedupe([*_as_list(evidence.get("canary_refs")), *_as_list(evidence.get("canary_report_refs"))])
    metrics = _metrics_from_refs(root, _as_list(evidence.get("metrics_refs")))
    warnings: list[str] = []
    proof_status = "none"
    if worksets and not (proof_refs or qualification_refs or canary_refs or metrics):
        proof_status = "local_only"
        warnings.append("benchmark workset declared but no proof/qualification/canary metrics refs found")
    if proof_refs or qualification_refs or canary_refs or metrics:
        proof_status = "partial"
    if _existing_any(root, [*proof_refs, *qualification_refs]):
        proof_status = "verified"
    if _has_strong_evidence(root, [*proof_refs, *qualification_refs, *canary_refs]):
        proof_status = "strong"
    try:
        from engine.project_pack_proof import latest_pack_proof_card

        card = latest_pack_proof_card(root, manifest.pack_id)
    except Exception as exc:  # noqa: BLE001 - proof card 조회 실패는 release-check 자체를 막지 않는다.
        logger.warning("pack proof card lookup failed during release-check: %s", exc)
        card = None
    if card is not None:
        proof_refs = _dedupe([*proof_refs, *card.source_refs.get("usage_event_refs", []), f".cambrian/packs/proof/{card.proof_id}"])
        for metric in card.key_metrics:
            if metric.value is not None:
                metrics[metric.key] = metric.value
        if card.reputation_verdict == "strong":
            proof_status = "strong"
        elif card.reputation_verdict == "useful" and proof_status not in {"strong"}:
            proof_status = "verified"
        elif card.reputation_verdict == "promising" and proof_status in {"none", "local_only"}:
            proof_status = "partial"
        elif card.reputation_verdict in {"insufficient_data", "unproven"} and proof_status == "none":
            warnings.append("latest local proof card has insufficient evidence")
    try:
        from engine.project_pack_proof_export import latest_pack_proof_export

        export = latest_pack_proof_export(root, manifest.pack_id)
    except Exception as exc:  # noqa: BLE001 - public proof export 조회 실패는 release-check 자체를 막지 않는다.
        logger.warning("pack proof export lookup failed during release-check: %s", exc)
        export = None
    if export is not None:
        if export.privacy_classification == "public_safe":
            proof_refs = _dedupe([*proof_refs, export.public_ref or export.saved_ref or f".cambrian/packs/proof_exports/{export.export_id}"])
            for metric in export.public_metrics:
                if metric.public_safe and metric.value is not None:
                    metrics[metric.key] = metric.value
            if export.proof_status == "strong":
                proof_status = "strong"
            elif export.proof_status == "useful" and proof_status not in {"strong"}:
                proof_status = "verified"
            elif export.proof_status == "early_positive" and proof_status in {"none", "local_only"}:
                proof_status = "partial"
            warnings.extend(export.caveats)
        else:
            warnings.append(f"public proof export ignored because privacy classification is {export.privacy_classification}")
    try:
        from engine.project_pack_retrospective import latest_pack_retro_summary

        retro_summary = latest_pack_retro_summary(root, manifest.pack_id)
    except Exception as exc:  # noqa: BLE001 - retrospective 조회 실패는 release-check를 막지 않는다.
        logger.warning("pack retrospective summary lookup failed during release-check: %s", exc)
        retro_summary = None
    if retro_summary is not None:
        metrics["retrospective_total"] = retro_summary.total_retrospectives
        if retro_summary.top_negative_signals:
            warnings.append(f"retrospective top issue: {retro_summary.top_negative_signals[0]}")
        if retro_summary.top_suggestions:
            warnings.append(f"retrospective suggestion pending: {retro_summary.top_suggestions[0].kind}")
    try:
        from engine.project_pack_improvements import latest_pack_improvement_queue

        improvement_queue = latest_pack_improvement_queue(root, manifest.pack_id)
    except Exception as exc:  # noqa: BLE001 - improvement queue 조회 실패는 release-check를 막지 않는다.
        logger.warning("pack improvement queue lookup failed during release-check: %s", exc)
        improvement_queue = None
    if improvement_queue is not None:
        open_items = [item for item in improvement_queue.items if item.status == "open"]
        metrics["open_improvement_count"] = len(open_items)
        high_items = [item for item in open_items if item.priority == "high"]
        if high_items:
            top = sorted(high_items, key=lambda item: (-float(item.confidence or 0.0), item.kind))[0]
            warnings.append(f"open high-priority improvement: {top.kind}")
    return PackProofSummary(
        proof_status=proof_status,
        worksets=_dedupe(worksets),
        proof_refs=proof_refs,
        qualification_refs=qualification_refs,
        canary_refs=canary_refs,
        metrics=metrics,
        warnings=warnings,
    )


def _scan_workset_refs(root: Path, worksets: list[str]) -> list[str]:
    refs: list[str] = []
    proof_dir = root / ".cambrian" / "benchmarks" / "proof"
    if not proof_dir.exists():
        return refs
    needles = [_slug(item, "") for item in worksets]
    for path in sorted(proof_dir.glob("*.yaml")):
        name = _slug(path.name, "")
        if not needles or any(needle and needle in name for needle in needles):
            refs.append(_relative(path, root))
    return refs


def _metrics_from_refs(root: Path, refs: list[str]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for ref in refs:
        path = _resolve_ref(root, ref)
        if not path.exists():
            continue
        payload = _load_yaml(path)
        for key in (
            "validated_proposal_rate",
            "human_intervention_rate",
            "validation_autonomy_rate",
            "reuse_lift",
            "repeat_task_improvement_rate",
        ):
            if key in payload:
                metrics[key] = payload[key]
        nested = _as_dict(payload.get("metrics"))
        for key in (
            "validated_proposal_rate",
            "human_intervention_rate",
            "validation_autonomy_rate",
            "reuse_lift",
            "repeat_task_improvement_rate",
        ):
            if key in nested:
                metrics[key] = nested[key]
    return metrics


def _existing_any(root: Path, refs: list[str]) -> bool:
    return any(_resolve_ref(root, ref).exists() for ref in refs)


def _has_strong_evidence(root: Path, refs: list[str]) -> bool:
    strong_terms = {"wins_now", "candidate_stronger", "promote_ready", "recommended", "strong"}
    for ref in refs:
        path = _resolve_ref(root, ref)
        if not path.exists():
            continue
        payload = _load_yaml(path)
        text = " ".join(str(value).lower() for value in _flatten_values(payload))
        if any(term in text for term in strong_terms):
            return True
    return False


def _flatten_values(value: Any) -> list[Any]:
    if isinstance(value, dict):
        items: list[Any] = []
        for nested in value.values():
            items.extend(_flatten_values(nested))
        return items
    if isinstance(value, list):
        items = []
        for nested in value:
            items.extend(_flatten_values(nested))
        return items
    return [value]


def _resolve_ref(root: Path, ref: str) -> Path:
    path = Path(str(ref))
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _compatibility_summary(manifest: PackManifest) -> dict[str, Any]:
    compatibility = manifest.compatibility
    stacks = _as_list(compatibility.get("stacks") or compatibility.get("stack"))
    tests = _as_list(compatibility.get("test_frameworks"))
    lanes = _as_list(compatibility.get("lane_ids"))
    request_classes = _as_list(compatibility.get("request_classes"))
    strongest_lane_fit = "strong" if "python" in {item.lower() for item in stacks} and "pytest" in {item.lower() for item in tests} else "unknown"
    if any("auth" in item.lower() and "bug" in item.lower() for item in lanes) or any("auth" in item.lower() for item in request_classes):
        strongest_lane_fit = "strong" if strongest_lane_fit == "strong" else "partial"
    return {
        "stacks": stacks,
        "test_frameworks": tests,
        "lane_ids": lanes,
        "request_classes": request_classes,
        "strongest_lane_fit": strongest_lane_fit,
    }


def _calculate_maturity(
    manifest: PackManifest,
    proof_summary: PackProofSummary,
    compatibility_summary: dict[str, Any],
    checks: list[PackReleaseCheck],
    explicit_maturity: str,
) -> str:
    """보수적으로 maturity를 계산한다."""
    explicit = explicit_maturity.lower()
    if explicit == "retired":
        return "retired"
    if any(check.status == "fail" for check in checks):
        return "draft"
    if proof_summary.canary_refs:
        return "canary"
    retro_caution = any("retrospective top issue" in str(item) or "open high-priority improvement" in str(item) for item in proof_summary.warnings)
    derivative_caution = any(
        check.check_id in {"derivative_unresolved_changes", "vnext_required_workorders"} and check.status == "warn"
        for check in checks
    )
    if proof_summary.proof_status == "strong" and compatibility_summary.get("strongest_lane_fit") == "strong" and not manifest.warnings and not retro_caution and not derivative_caution:
        return "recommended"
    if proof_summary.proof_status in {"verified", "strong"}:
        return "verified"
    return "candidate"


def _vnext_required_workorders(root: Path, derivative: dict[str, Any], pack_id: str) -> list[Any]:
    """manifest derivative metadata에 연결된 미완료 required workorder를 조회한다."""
    if not derivative:
        return []
    try:
        from engine.project_pack_vnext_workbench import unresolved_required_workorders_for_derivative

        return unresolved_required_workorders_for_derivative(root, derivative, pack_id)
    except Exception as exc:  # noqa: BLE001 - release-check는 workbench 조회 실패를 warning 로그로만 남긴다.
        logger.warning("vNext workorder lookup failed during release-check: %s", exc)
        return []


def _fake_proof_check(payload: dict[str, Any], root: Path) -> PackReleaseCheck:
    evidence = _as_dict(payload.get("evidence"))
    metrics = _as_dict(evidence.get("metrics"))
    metric_refs = _as_list(evidence.get("metrics_refs"))
    has_metrics = bool(metrics or _as_dict(payload.get("metrics")))
    has_refs = bool(metric_refs or _as_list(evidence.get("proof_refs")) or _as_list(evidence.get("qualification_refs")))
    if has_metrics and not has_refs:
        return _check(
            "fake_proof_absent",
            "No fake proof",
            "warn",
            "metrics-like values exist without evidence refs",
            warnings=["metrics are present without evidence refs; do not claim public proof"],
        )
    missing_refs = [ref for ref in metric_refs if not _resolve_ref(root, ref).exists()]
    if missing_refs:
        return _check(
            "fake_proof_absent",
            "No fake proof",
            "warn",
            "some evidence refs do not exist locally",
            warnings=[f"missing evidence ref: {ref}" for ref in missing_refs],
        )
    return _check("fake_proof_absent", "No fake proof", "pass", "no unsupported proof claims detected")


def _known_limits(payload: dict[str, Any], manifest: PackManifest) -> list[str]:
    return _dedupe([
        *_as_list(payload.get("known_limits")),
        *_as_list(payload.get("warnings")),
        *list(manifest.warnings),
    ])


def _summary_lines(maturity: str, proof_summary: PackProofSummary, safe_to_publish: bool) -> list[str]:
    return [
        f"maturity={maturity}",
        f"proof_status={proof_summary.proof_status}",
        "publish allowed" if safe_to_publish else "publish blocked",
    ]


def _dedupe(values: list[Any]) -> list[Any]:
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
