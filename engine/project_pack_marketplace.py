"""Pack marketplace listing draft를 로컬 proof 기반으로 만든다."""

from __future__ import annotations

import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_install import (
    InstalledPackRecord,
    InstalledPackStore,
    SCHEMA_VERSION,
    default_installed_packs_path,
    _as_list,
    _relative,
    _slug,
)
from engine.project_pack_proof_export import (
    PackProofExportSnapshot,
    PackProofExporter,
    latest_pack_proof_export,
    resolve_pack_proof_export_path,
)


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓰는 UTC timestamp를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _stamp_unique() -> str:
    """연속 저장에서도 충돌하지 않도록 더 촘촘한 UTC timestamp를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


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


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """YAML payload를 저장한다."""
    target = Path(path).resolve()
    _atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML mapping을 읽는다."""
    target = Path(path).resolve()
    if not target.exists():
        return {}
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


@dataclass
class PackMarketplaceListingDraft:
    """업로드 전 로컬 marketplace listing 후보."""

    schema_version: str
    listing_id: str
    generated_at: str
    pack_id: str
    pack_name: str
    pack_kind: str
    version: str | None
    namespace: str | None
    author: str | None
    license: str | None
    provenance: str | None
    public_visibility: str
    signature_status: str
    manifest_ref: str | None
    manifest_sha256: str | None
    proof_export_ref: str | None
    proof_status: str
    marketplace_readiness: str
    listing_status: str
    safe_to_publish: bool
    install_command: str
    known_limits: list[str] = field(default_factory=list)
    evolution_lineage: list[str] = field(default_factory=list)
    marketplace_blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackMarketplaceReviewDecision:
    """marketplace listing draft에 대한 로컬 심사 결정."""

    schema_version: str
    review_id: str
    reviewed_at: str
    listing_id: str
    listing_ref: str | None
    pack_id: str
    decision: str
    reviewer: str
    notes: str | None
    listing_status: str
    marketplace_readiness: str
    safe_to_publish: bool
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackMarketplaceStatus:
    """marketplace listing과 최신 review를 합친 운영 상태."""

    schema_version: str
    generated_at: str
    listing_id: str
    listing_ref: str | None
    pack_id: str
    listing_status: str
    marketplace_readiness: str
    safe_to_publish: bool
    operational_status: str
    latest_review_id: str | None
    latest_review_decision: str | None
    latest_review_ref: str | None
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackMarketplaceStatusCheck:
    """marketplace status dashboard snapshot 검증 결과."""

    ok: bool
    status_ref: str | None
    checked_at: str
    error_count: int
    warning_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackMarketplaceStatusReadyCheck:
    """Studio marketplace status ready report 검증 결과."""

    ok: bool
    ready_ref: str | None
    status_ref: str | None
    check_ref: str | None
    ready_for_studio: bool
    checked_at: str
    error_count: int
    warning_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackMarketplaceStatusStudioCheck:
    """Studio marketplace status handoff payload 검증 결과."""

    ok: bool
    handoff_ref: str | None
    ready_ref: str | None
    ready_check_ref: str | None
    studio_handoff_ready: bool
    ready_for_studio: bool
    checked_at: str
    error_count: int
    warning_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackMarketplaceStatusStudioRefreshCheck:
    """Studio marketplace status refresh report 검증 결과."""

    ok: bool
    refresh_ref: str | None
    studio_handoff_ref: str | None
    studio_check_ref: str | None
    studio_refresh_ok: bool
    checked_at: str
    error_count: int
    warning_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    saved_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


class PackMarketplaceListingExporter:
    """installed pack과 proof export를 묶어 listing draft를 만든다."""

    def export(
        self,
        project_root: Path,
        pack_ref: str,
        *,
        proof_export_ref: str | None = None,
        out_path: Path | None = None,
    ) -> PackMarketplaceListingDraft:
        """로컬 marketplace listing draft를 저장하고 반환한다."""
        root = Path(project_root).resolve()
        record = _installed_record(root, pack_ref)
        manifest_path = _manifest_path(root, record)
        manifest_payload = _load_yaml(manifest_path) if manifest_path is not None else {}
        proof_export = _proof_export(root, record.pack_id, proof_export_ref)
        source = _as_dict(manifest_payload.get("source"))
        marketplace = _as_dict(manifest_payload.get("marketplace"))
        listing_status, safe_to_publish, blockers = _listing_status(record, proof_export, source)
        known_limits = _as_list(marketplace.get("known_limits")) or _as_list(manifest_payload.get("warnings"))
        draft = PackMarketplaceListingDraft(
            schema_version=SCHEMA_VERSION,
            listing_id=f"marketplace-listing-{_slug(record.pack_id, 'pack')}-{_stamp()}",
            generated_at=_now(),
            pack_id=record.pack_id,
            pack_name=record.pack_name,
            pack_kind=record.pack_kind,
            version=record.version,
            namespace=record.namespace,
            author=str(source.get("author") or marketplace.get("author")) if source.get("author") or marketplace.get("author") else None,
            license=str(marketplace.get("license") or "unspecified"),
            provenance=str(source.get("provenance") or marketplace.get("provenance") or record.source_kind or "unknown"),
            public_visibility=str(source.get("public_visibility") or marketplace.get("public_visibility") or "private"),
            signature_status=str(source.get("signature_status") or marketplace.get("signature") or "unsigned_local"),
            manifest_ref=_relative(manifest_path, root) if manifest_path is not None else record.latest_manifest_ref or record.manifest_ref,
            manifest_sha256=record.manifest_sha256,
            proof_export_ref=proof_export.public_ref or proof_export.saved_ref,
            proof_status=proof_export.proof_status,
            marketplace_readiness=proof_export.marketplace_readiness,
            listing_status=listing_status,
            safe_to_publish=safe_to_publish,
            install_command=proof_export.install_command or f"cambrian install pack {record.pack_id}",
            known_limits=known_limits,
            evolution_lineage=_as_list(marketplace.get("evolution_lineage")),
            marketplace_blockers=_dedupe([*proof_export.marketplace_blockers, *blockers]),
            next_actions=_dedupe([*proof_export.marketplace_next_actions, *_listing_next_actions(record, safe_to_publish)]),
            warnings=_dedupe([*record.warnings, *proof_export.warnings]),
            errors=_dedupe(proof_export.errors),
        )
        if out_path is not None:
            target = Path(out_path)
            if not target.is_absolute():
                target = root / target
            target = target.resolve()
        else:
            target = default_marketplace_listing_path(root, draft)
        saved = _save_yaml(target, draft.to_dict())
        draft.saved_ref = _relative(saved, root)
        _save_yaml(saved, draft.to_dict())
        _save_yaml(default_marketplace_listing_latest_path(root), draft.to_dict())
        return draft


class PackMarketplaceListingStore:
    """marketplace listing draft 저장소."""

    def load_yaml(self, path: Path) -> PackMarketplaceListingDraft:
        """저장된 listing draft를 읽는다."""
        return _draft_from_dict(_load_yaml(path), path)

    def list(self, listings_dir: Path) -> list[PackMarketplaceListingDraft]:
        """저장된 listing draft 목록을 최신순으로 읽는다."""
        root = Path(listings_dir)
        if not root.exists():
            return []
        drafts: list[PackMarketplaceListingDraft] = []
        for path in sorted(root.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                drafts.append(self.load_yaml(path))
            except (OSError, ValueError, yaml.YAMLError):
                continue
        return drafts


class PackMarketplaceReviewRecorder:
    """listing draft review decision을 로컬 기록으로 남긴다."""

    def record(
        self,
        project_root: Path,
        listing_ref: str,
        *,
        decision: str,
        notes: str | None = None,
        reviewer: str | None = None,
    ) -> PackMarketplaceReviewDecision:
        """listing draft에 대한 심사 결정을 저장한다."""
        root = Path(project_root).resolve()
        listing_path = resolve_pack_marketplace_listing_path(root, listing_ref)
        listing = PackMarketplaceListingStore().load_yaml(listing_path)
        normalized = _review_decision(decision)
        if normalized == "accepted" and not listing.safe_to_publish:
            raise ValueError("marketplace listing cannot be accepted until safe_to_publish is true")
        review = PackMarketplaceReviewDecision(
            schema_version=SCHEMA_VERSION,
            review_id=f"marketplace-review-{_slug(listing.pack_id, 'pack')}-{_stamp()}",
            reviewed_at=_now(),
            listing_id=listing.listing_id,
            listing_ref=_relative(listing_path, root),
            pack_id=listing.pack_id,
            decision=normalized,
            reviewer=str(reviewer or "local_reviewer").strip() or "local_reviewer",
            notes=str(notes).strip() if notes is not None and str(notes).strip() else None,
            listing_status=listing.listing_status,
            marketplace_readiness=listing.marketplace_readiness,
            safe_to_publish=listing.safe_to_publish,
            blockers=list(listing.marketplace_blockers),
            next_actions=_review_next_actions(listing, normalized),
            warnings=list(listing.warnings),
            errors=list(listing.errors),
        )
        saved = _save_yaml(default_marketplace_review_path(root, review), review.to_dict())
        review.saved_ref = _relative(saved, root)
        _save_yaml(saved, review.to_dict())
        _save_yaml(default_marketplace_review_latest_path(root), review.to_dict())
        return review


class PackMarketplaceReviewStore:
    """marketplace review decision 저장소."""

    def load_yaml(self, path: Path) -> PackMarketplaceReviewDecision:
        """저장된 review decision을 읽는다."""
        return _review_from_dict(_load_yaml(path), path)

    def list(self, reviews_dir: Path) -> list[PackMarketplaceReviewDecision]:
        """저장된 review decision 목록을 최신순으로 읽는다."""
        root = Path(reviews_dir)
        if not root.exists():
            return []
        reviews: list[PackMarketplaceReviewDecision] = []
        seen: set[str] = set()
        for path in sorted(root.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                review = self.load_yaml(path)
            except (OSError, ValueError, yaml.YAMLError):
                continue
            if review.review_id in seen:
                continue
            seen.add(review.review_id)
            reviews.append(review)
        return reviews


def latest_marketplace_review_for_listing(project_root: Path, listing_id: str) -> PackMarketplaceReviewDecision | None:
    """특정 listing에 연결된 최신 review decision을 찾는다."""
    for review in PackMarketplaceReviewStore().list(default_marketplace_review_dir(project_root)):
        if review.listing_id == listing_id:
            return review
    return None


def build_pack_marketplace_status(project_root: Path, listing_ref: str) -> PackMarketplaceStatus:
    """listing draft와 최신 review decision을 하나의 운영 상태로 합친다."""
    root = Path(project_root).resolve()
    listing_path = resolve_pack_marketplace_listing_path(root, listing_ref)
    draft = PackMarketplaceListingStore().load_yaml(listing_path)
    latest_review = latest_marketplace_review_for_listing(root, draft.listing_id)
    return PackMarketplaceStatus(
        schema_version=SCHEMA_VERSION,
        generated_at=_now(),
        listing_id=draft.listing_id,
        listing_ref=_relative(listing_path, root),
        pack_id=draft.pack_id,
        listing_status=draft.listing_status,
        marketplace_readiness=draft.marketplace_readiness,
        safe_to_publish=draft.safe_to_publish,
        operational_status=_marketplace_operational_status(draft, latest_review),
        latest_review_id=latest_review.review_id if latest_review is not None else None,
        latest_review_decision=latest_review.decision if latest_review is not None else None,
        latest_review_ref=latest_review.saved_ref if latest_review is not None else None,
        blockers=_marketplace_status_blockers(draft, latest_review),
        next_actions=_marketplace_status_next_actions(draft, latest_review),
    )


def build_pack_marketplace_status_list(project_root: Path) -> list[PackMarketplaceStatus]:
    """저장된 listing draft들을 최신순 marketplace 운영 상태로 변환한다."""
    root = Path(project_root).resolve()
    statuses: list[PackMarketplaceStatus] = []
    seen: set[str] = set()
    for draft in PackMarketplaceListingStore().list(default_marketplace_listing_dir(root)):
        if draft.listing_id in seen:
            continue
        seen.add(draft.listing_id)
        latest_review = latest_marketplace_review_for_listing(root, draft.listing_id)
        statuses.append(
            PackMarketplaceStatus(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                listing_id=draft.listing_id,
                listing_ref=draft.saved_ref,
                pack_id=draft.pack_id,
                listing_status=draft.listing_status,
                marketplace_readiness=draft.marketplace_readiness,
                safe_to_publish=draft.safe_to_publish,
                operational_status=_marketplace_operational_status(draft, latest_review),
                latest_review_id=latest_review.review_id if latest_review is not None else None,
                latest_review_decision=latest_review.decision if latest_review is not None else None,
                latest_review_ref=latest_review.saved_ref if latest_review is not None else None,
                blockers=_marketplace_status_blockers(draft, latest_review),
                next_actions=_marketplace_status_next_actions(draft, latest_review),
            )
        )
    return statuses


def filter_pack_marketplace_statuses(
    statuses: list[PackMarketplaceStatus],
    operational_status: str | None,
) -> list[PackMarketplaceStatus]:
    """운영 상태 문자열로 marketplace status 목록을 필터링한다."""
    needle = str(operational_status or "").strip()
    if not needle:
        return statuses
    return [status for status in statuses if status.operational_status == needle]


def summarize_pack_marketplace_statuses(statuses: list[PackMarketplaceStatus]) -> dict[str, int]:
    """marketplace status 목록을 운영 상태별 카운트로 요약한다."""
    summary: dict[str, int] = {"total": len(statuses)}
    for status in statuses:
        key = status.operational_status or "unknown"
        summary[key] = summary.get(key, 0) + 1
    return summary


def pack_marketplace_status_dashboard_payload(
    statuses: list[PackMarketplaceStatus],
    *,
    status_filter: str | None = None,
    summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    """marketplace dashboard용 status 목록 payload를 만든다."""
    resolved_filter = str(status_filter or "").strip()
    resolved_summary = summary or summarize_pack_marketplace_statuses(statuses)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "count": len(statuses),
        "status_filter": resolved_filter or None,
        "summary": dict(resolved_summary),
        "statuses": [status.to_dict() for status in statuses],
    }


def save_pack_marketplace_status_dashboard(
    project_root: Path,
    payload: dict[str, Any],
    out_path: Path | None = None,
) -> dict[str, Any]:
    """marketplace status dashboard snapshot을 저장하고 저장 경로를 payload에 붙인다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    saved_payload = dict(payload)
    saved_payload["saved_ref"] = _relative(target, root)
    _save_yaml(target, saved_payload)
    _save_yaml(default_marketplace_status_latest_path(root), saved_payload)
    return saved_payload


def load_pack_marketplace_status_dashboard(project_root: Path, status_ref: str) -> tuple[dict[str, Any], Path]:
    """저장된 marketplace status dashboard snapshot을 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_path(root, status_ref)
    return _load_yaml(path), path


def check_pack_marketplace_status_dashboard(project_root: Path, status_ref: str) -> PackMarketplaceStatusCheck:
    """저장된 marketplace status dashboard snapshot의 최소 무결성을 검사한다."""
    root = Path(project_root).resolve()
    payload, status_path = load_pack_marketplace_status_dashboard(root, status_ref)
    errors: list[str] = []
    warnings: list[str] = []
    for key in ["schema_version", "generated_at", "count", "summary", "statuses"]:
        if key not in payload:
            errors.append(f"missing required field: {key}")
    statuses = payload.get("statuses")
    if not isinstance(statuses, list):
        errors.append("statuses must be a list")
        statuses = []
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be a mapping")
        summary = {}
    count = payload.get("count")
    if not isinstance(count, int):
        errors.append("count must be an integer")
    elif count != len(statuses):
        errors.append(f"count does not match statuses length: count={count}, statuses={len(statuses)}")
    total = summary.get("total") if isinstance(summary, dict) else None
    if isinstance(total, int) and total != len(statuses):
        errors.append(f"summary.total does not match statuses length: total={total}, statuses={len(statuses)}")
    elif "total" not in summary:
        warnings.append("summary.total is missing")
    required_status_keys = {
        "listing_id",
        "pack_id",
        "listing_status",
        "marketplace_readiness",
        "safe_to_publish",
        "operational_status",
    }
    for index, item in enumerate(statuses):
        if not isinstance(item, dict):
            errors.append(f"statuses[{index}] must be a mapping")
            continue
        for key in sorted(required_status_keys):
            if key not in item:
                errors.append(f"statuses[{index}] missing required field: {key}")
    if payload.get("saved_ref") is None:
        warnings.append("saved_ref is missing")
    return PackMarketplaceStatusCheck(
        ok=not errors,
        status_ref=_relative(status_path, root),
        checked_at=_now(),
        error_count=len(errors),
        warning_count=len(warnings),
        errors=errors,
        warnings=warnings,
    )


def save_pack_marketplace_status_check(
    project_root: Path,
    check: PackMarketplaceStatusCheck,
    out_path: Path | None = None,
) -> PackMarketplaceStatusCheck:
    """marketplace status dashboard check report를 저장한다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_check_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    check.saved_ref = _relative(target, root)
    _save_yaml(target, check.to_dict())
    _save_yaml(default_marketplace_status_check_latest_path(root), check.to_dict())
    return check


def load_pack_marketplace_status_check(project_root: Path, check_ref: str) -> tuple[PackMarketplaceStatusCheck, Path]:
    """저장된 marketplace status check report를 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_check_path(root, check_ref)
    return _status_check_from_dict(_load_yaml(path), path), path


def save_pack_marketplace_status_ready(
    project_root: Path,
    payload: dict[str, Any],
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Studio marketplace status ready report를 저장한다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_ready_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    saved_payload = dict(payload)
    saved_payload["saved_ref"] = _relative(target, root)
    _save_yaml(target, saved_payload)
    _save_yaml(default_marketplace_status_ready_latest_path(root), saved_payload)
    return saved_payload


def load_pack_marketplace_status_ready(project_root: Path, ready_ref: str) -> tuple[dict[str, Any], Path]:
    """저장된 Studio marketplace status ready report를 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_ready_path(root, ready_ref)
    return _load_yaml(path), path


def check_pack_marketplace_status_ready_report(project_root: Path, ready_ref: str) -> PackMarketplaceStatusReadyCheck:
    """저장된 Studio marketplace status ready report의 최소 무결성을 검사한다."""
    root = Path(project_root).resolve()
    payload, ready_path = load_pack_marketplace_status_ready(root, ready_ref)
    errors: list[str] = []
    warnings: list[str] = []
    for key in [
        "schema_version",
        "generated_at",
        "ready_for_studio",
        "status_ref",
        "check_ref",
        "check_ok",
        "errors",
        "dashboard",
        "check",
    ]:
        if key not in payload:
            errors.append(f"missing required field: {key}")
    ready_for_studio = payload.get("ready_for_studio")
    if not isinstance(ready_for_studio, bool):
        errors.append("ready_for_studio must be a boolean")
        ready_for_studio = False
    check_ok = payload.get("check_ok")
    if not isinstance(check_ok, bool):
        errors.append("check_ok must be a boolean")
        check_ok = False
    ready_errors_payload = payload.get("errors")
    if not isinstance(ready_errors_payload, list):
        errors.append("errors must be a list")
    ready_errors = _as_list(ready_errors_payload)
    dashboard = payload.get("dashboard")
    if not isinstance(dashboard, dict):
        errors.append("dashboard must be a mapping")
        dashboard = {}
    embedded_check = payload.get("check")
    if not isinstance(embedded_check, dict):
        errors.append("check must be a mapping")
        embedded_check = {}
    status_ref = str(payload.get("status_ref")) if payload.get("status_ref") is not None else None
    check_ref = str(payload.get("check_ref")) if payload.get("check_ref") is not None else None
    if not status_ref:
        errors.append("status_ref is required")
    elif not _project_ref_exists(root, status_ref):
        errors.append(f"status_ref does not exist: {status_ref}")
    if not check_ref:
        errors.append("check_ref is required")
    elif not _project_ref_exists(root, check_ref):
        errors.append(f"check_ref does not exist: {check_ref}")
    embedded_check_ok = embedded_check.get("ok")
    if isinstance(embedded_check_ok, bool) and embedded_check_ok != bool(check_ok):
        errors.append("check.ok does not match check_ok")
    embedded_status_ref = str(embedded_check.get("status_ref")) if embedded_check.get("status_ref") is not None else None
    if status_ref and embedded_status_ref and embedded_status_ref != status_ref:
        errors.append(f"check.status_ref points to {embedded_status_ref}, not {status_ref}")
    if check_ref and _project_ref_exists(root, check_ref):
        try:
            referenced_check, _ = load_pack_marketplace_status_check(root, check_ref)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"check_ref cannot be loaded: {exc}")
        else:
            if referenced_check.ok != bool(check_ok):
                errors.append("referenced check ok does not match check_ok")
            if status_ref and referenced_check.status_ref and referenced_check.status_ref != status_ref:
                errors.append(f"referenced check points to {referenced_check.status_ref}, not {status_ref}")
    if bool(ready_for_studio) and ready_errors:
        errors.append("ready_for_studio cannot be true when errors are present")
    if bool(ready_for_studio) and not bool(check_ok):
        errors.append("ready_for_studio cannot be true when check_ok is false")
    if not bool(ready_for_studio) and not ready_errors:
        warnings.append("ready_for_studio is false but errors are empty")
    if isinstance(dashboard, dict) and "statuses" not in dashboard:
        warnings.append("dashboard.statuses is missing")
    ready_path_ref = _relative(ready_path, root)
    return PackMarketplaceStatusReadyCheck(
        ok=not errors,
        ready_ref=ready_path_ref,
        status_ref=status_ref,
        check_ref=check_ref,
        ready_for_studio=bool(ready_for_studio),
        checked_at=_now(),
        error_count=len(_dedupe(errors)),
        warning_count=len(_dedupe(warnings)),
        errors=_dedupe(errors),
        warnings=_dedupe(warnings),
    )


def save_pack_marketplace_status_ready_check(
    project_root: Path,
    check: PackMarketplaceStatusReadyCheck,
    out_path: Path | None = None,
) -> PackMarketplaceStatusReadyCheck:
    """Studio marketplace status ready check report를 저장한다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_ready_check_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    check.saved_ref = _relative(target, root)
    _save_yaml(target, check.to_dict())
    _save_yaml(default_marketplace_status_ready_check_latest_path(root), check.to_dict())
    return check


def load_pack_marketplace_status_ready_check(project_root: Path, check_ref: str) -> tuple[PackMarketplaceStatusReadyCheck, Path]:
    """저장된 Studio marketplace status ready check report를 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_ready_check_path(root, check_ref)
    return _status_ready_check_from_dict(_load_yaml(path), path), path


def build_pack_marketplace_status_studio_handoff(
    project_root: Path,
    *,
    ready_ref: str = "latest",
    ready_check_ref: str = "latest",
) -> dict[str, Any]:
    """Studio UI가 마지막으로 읽는 marketplace status handoff payload를 만든다."""
    root = Path(project_root).resolve()
    ready_payload, ready_path = load_pack_marketplace_status_ready(root, ready_ref)
    ready_check, ready_check_path = load_pack_marketplace_status_ready_check(root, ready_check_ref)
    ready_path_ref = _relative(ready_path, root)
    ready_check_path_ref = _relative(ready_check_path, root)
    errors: list[str] = []
    warnings: list[str] = []
    if not ready_check.ok:
        errors.extend(ready_check.errors)
    if ready_check.ready_ref and ready_check.ready_ref != ready_path_ref:
        errors.append(f"ready check points to {ready_check.ready_ref}, not {ready_path_ref}")
    ready_for_studio = bool(ready_payload.get("ready_for_studio", False))
    if not ready_for_studio:
        ready_errors = _as_list(ready_payload.get("errors"))
        errors.extend(ready_errors or ["ready report is not ready_for_studio"])
    if ready_check.ready_for_studio != ready_for_studio:
        errors.append("ready check ready_for_studio does not match ready report")
    status_ref = str(ready_payload.get("status_ref")) if ready_payload.get("status_ref") is not None else None
    check_ref = str(ready_payload.get("check_ref")) if ready_payload.get("check_ref") is not None else None
    if ready_check.status_ref and status_ref and ready_check.status_ref != status_ref:
        errors.append(f"ready check status_ref points to {ready_check.status_ref}, not {status_ref}")
    if ready_check.check_ref and check_ref and ready_check.check_ref != check_ref:
        errors.append(f"ready check check_ref points to {ready_check.check_ref}, not {check_ref}")
    if not ready_check.saved_ref:
        warnings.append("ready check report has no saved_ref")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "studio_handoff_ready": not errors,
        "ready_ref": ready_path_ref,
        "ready_check_ref": ready_check_path_ref,
        "ready_check_ok": ready_check.ok,
        "ready_for_studio": ready_for_studio,
        "status_ref": status_ref,
        "check_ref": check_ref,
        "errors": _dedupe(errors),
        "warnings": _dedupe(warnings),
        "ready": ready_payload,
        "ready_check": ready_check.to_dict(),
        "dashboard": _as_dict(ready_payload.get("dashboard")),
    }


def save_pack_marketplace_status_studio_handoff(
    project_root: Path,
    payload: dict[str, Any],
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Studio marketplace status handoff payload를 저장한다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_studio_handoff_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    saved_payload = dict(payload)
    saved_payload["saved_ref"] = _relative(target, root)
    _save_yaml(target, saved_payload)
    _save_yaml(default_marketplace_status_studio_handoff_latest_path(root), saved_payload)
    return saved_payload


def load_pack_marketplace_status_studio_handoff(project_root: Path, handoff_ref: str) -> tuple[dict[str, Any], Path]:
    """저장된 Studio marketplace status handoff payload를 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_studio_handoff_path(root, handoff_ref)
    return _load_yaml(path), path


def check_pack_marketplace_status_studio_handoff(project_root: Path, handoff_ref: str) -> PackMarketplaceStatusStudioCheck:
    """저장된 Studio marketplace status handoff payload의 최소 무결성을 검사한다."""
    root = Path(project_root).resolve()
    payload, handoff_path = load_pack_marketplace_status_studio_handoff(root, handoff_ref)
    errors: list[str] = []
    warnings: list[str] = []
    for key in [
        "schema_version",
        "generated_at",
        "studio_handoff_ready",
        "ready_ref",
        "ready_check_ref",
        "ready_check_ok",
        "ready_for_studio",
        "status_ref",
        "check_ref",
        "errors",
        "warnings",
        "ready",
        "ready_check",
        "dashboard",
    ]:
        if key not in payload:
            errors.append(f"missing required field: {key}")
    studio_handoff_ready = payload.get("studio_handoff_ready")
    if not isinstance(studio_handoff_ready, bool):
        errors.append("studio_handoff_ready must be a boolean")
        studio_handoff_ready = False
    ready_for_studio = payload.get("ready_for_studio")
    if not isinstance(ready_for_studio, bool):
        errors.append("ready_for_studio must be a boolean")
        ready_for_studio = False
    ready_check_ok = payload.get("ready_check_ok")
    if not isinstance(ready_check_ok, bool):
        errors.append("ready_check_ok must be a boolean")
        ready_check_ok = False
    payload_errors = payload.get("errors")
    if not isinstance(payload_errors, list):
        errors.append("errors must be a list")
    handoff_errors = _as_list(payload_errors)
    payload_warnings = payload.get("warnings")
    if not isinstance(payload_warnings, list):
        errors.append("warnings must be a list")
    ready_payload = payload.get("ready")
    if not isinstance(ready_payload, dict):
        errors.append("ready must be a mapping")
        ready_payload = {}
    ready_check_payload = payload.get("ready_check")
    if not isinstance(ready_check_payload, dict):
        errors.append("ready_check must be a mapping")
        ready_check_payload = {}
    dashboard = payload.get("dashboard")
    if not isinstance(dashboard, dict):
        errors.append("dashboard must be a mapping")
        dashboard = {}
    ready_ref = str(payload.get("ready_ref")) if payload.get("ready_ref") is not None else None
    ready_check_ref = str(payload.get("ready_check_ref")) if payload.get("ready_check_ref") is not None else None
    if not ready_ref:
        errors.append("ready_ref is required")
    elif not _project_ref_exists(root, ready_ref):
        errors.append(f"ready_ref does not exist: {ready_ref}")
    if not ready_check_ref:
        errors.append("ready_check_ref is required")
    elif not _project_ref_exists(root, ready_check_ref):
        errors.append(f"ready_check_ref does not exist: {ready_check_ref}")
    if bool(studio_handoff_ready) and handoff_errors:
        errors.append("studio_handoff_ready cannot be true when errors are present")
    if bool(studio_handoff_ready) and not bool(ready_for_studio):
        errors.append("studio_handoff_ready cannot be true when ready_for_studio is false")
    if bool(studio_handoff_ready) and not bool(ready_check_ok):
        errors.append("studio_handoff_ready cannot be true when ready_check_ok is false")
    embedded_ready_for_studio = ready_payload.get("ready_for_studio")
    if isinstance(embedded_ready_for_studio, bool) and embedded_ready_for_studio != bool(ready_for_studio):
        errors.append("ready.ready_for_studio does not match ready_for_studio")
    embedded_ready_status_ref = str(ready_payload.get("status_ref")) if ready_payload.get("status_ref") is not None else None
    embedded_ready_check_ref = str(ready_payload.get("check_ref")) if ready_payload.get("check_ref") is not None else None
    status_ref = str(payload.get("status_ref")) if payload.get("status_ref") is not None else None
    check_ref = str(payload.get("check_ref")) if payload.get("check_ref") is not None else None
    if status_ref and embedded_ready_status_ref and embedded_ready_status_ref != status_ref:
        errors.append(f"ready.status_ref points to {embedded_ready_status_ref}, not {status_ref}")
    if check_ref and embedded_ready_check_ref and embedded_ready_check_ref != check_ref:
        errors.append(f"ready.check_ref points to {embedded_ready_check_ref}, not {check_ref}")
    embedded_ready_check_ok = ready_check_payload.get("ok")
    if isinstance(embedded_ready_check_ok, bool) and embedded_ready_check_ok != bool(ready_check_ok):
        errors.append("ready_check.ok does not match ready_check_ok")
    embedded_ready_check_ready_ref = str(ready_check_payload.get("ready_ref")) if ready_check_payload.get("ready_ref") is not None else None
    if ready_ref and embedded_ready_check_ready_ref and embedded_ready_check_ready_ref != ready_ref:
        errors.append(f"ready_check.ready_ref points to {embedded_ready_check_ready_ref}, not {ready_ref}")
    embedded_ready_check_studio_ready = ready_check_payload.get("ready_for_studio")
    if isinstance(embedded_ready_check_studio_ready, bool) and embedded_ready_check_studio_ready != bool(ready_for_studio):
        errors.append("ready_check.ready_for_studio does not match ready_for_studio")
    if isinstance(dashboard, dict) and "statuses" not in dashboard:
        warnings.append("dashboard.statuses is missing")
    handoff_path_ref = _relative(handoff_path, root)
    return PackMarketplaceStatusStudioCheck(
        ok=not errors,
        handoff_ref=handoff_path_ref,
        ready_ref=ready_ref,
        ready_check_ref=ready_check_ref,
        studio_handoff_ready=bool(studio_handoff_ready),
        ready_for_studio=bool(ready_for_studio),
        checked_at=_now(),
        error_count=len(_dedupe(errors)),
        warning_count=len(_dedupe(warnings)),
        errors=_dedupe(errors),
        warnings=_dedupe(warnings),
    )


def save_pack_marketplace_status_studio_check(
    project_root: Path,
    check: PackMarketplaceStatusStudioCheck,
    out_path: Path | None = None,
) -> PackMarketplaceStatusStudioCheck:
    """Studio marketplace status handoff check report를 저장한다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_studio_check_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    check.saved_ref = _relative(target, root)
    _save_yaml(target, check.to_dict())
    _save_yaml(default_marketplace_status_studio_check_latest_path(root), check.to_dict())
    return check


def load_pack_marketplace_status_studio_check(project_root: Path, check_ref: str) -> tuple[PackMarketplaceStatusStudioCheck, Path]:
    """저장된 Studio marketplace status handoff check report를 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_studio_check_path(root, check_ref)
    return _status_studio_check_from_dict(_load_yaml(path), path), path


def save_pack_marketplace_status_studio_refresh(
    project_root: Path,
    payload: dict[str, Any],
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Studio marketplace status refresh report를 저장한다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_studio_refresh_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    saved_payload = dict(payload)
    saved_payload["saved_ref"] = _relative(target, root)
    _save_yaml(target, saved_payload)
    _save_yaml(default_marketplace_status_studio_refresh_latest_path(root), saved_payload)
    return saved_payload


def load_pack_marketplace_status_studio_refresh(project_root: Path, refresh_ref: str) -> tuple[dict[str, Any], Path]:
    """저장된 Studio marketplace status refresh report를 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_studio_refresh_path(root, refresh_ref)
    return _load_yaml(path), path


def list_pack_marketplace_status_studio_refresh_reports(
    project_root: Path,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """저장된 Studio marketplace status refresh report 목록을 최신순으로 만든다."""
    root = Path(project_root).resolve()
    refresh_dir = default_marketplace_status_studio_refresh_dir(root)
    reports: list[dict[str, Any]] = []
    if refresh_dir.exists():
        for path in sorted(refresh_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.name == "latest.yaml":
                continue
            payload = _load_yaml(path)
            refs = payload.get("refs") if isinstance(payload.get("refs"), dict) else {}
            errors = _as_list(payload.get("errors"))
            warnings = _as_list(payload.get("warnings"))
            reports.append(
                {
                    "path": _relative(path, root),
                    "saved_ref": str(payload.get("saved_ref") or _relative(path, root)),
                    "generated_at": str(payload.get("generated_at") or "unknown"),
                    "studio_refresh_ok": bool(payload.get("studio_refresh_ok", False)),
                    "studio_handoff_ready": bool(payload.get("studio_handoff_ready", False)),
                    "studio_check_ok": bool(payload.get("studio_check_ok", False)),
                    "status_filter": payload.get("status_filter"),
                    "count": payload.get("count", 0),
                    "studio_handoff_ref": refs.get("studio_handoff"),
                    "studio_check_ref": refs.get("studio_check"),
                    "error_count": len(errors),
                    "warning_count": len(warnings),
                }
            )
    resolved_limit = max(0, int(limit))
    latest_ref = _relative(default_marketplace_status_studio_refresh_latest_path(root), root)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "count": min(len(reports), resolved_limit),
        "total": len(reports),
        "latest_ref": latest_ref if default_marketplace_status_studio_refresh_latest_path(root).exists() else None,
        "reports": reports[:resolved_limit],
    }


def check_pack_marketplace_status_studio_refresh(project_root: Path, refresh_ref: str) -> PackMarketplaceStatusStudioRefreshCheck:
    """저장된 Studio marketplace status refresh report의 최소 무결성을 검사한다."""
    root = Path(project_root).resolve()
    payload, refresh_path = load_pack_marketplace_status_studio_refresh(root, refresh_ref)
    errors: list[str] = []
    warnings: list[str] = []
    for key in [
        "schema_version",
        "generated_at",
        "studio_refresh_ok",
        "studio_handoff_ready",
        "studio_check_ok",
        "status_filter",
        "count",
        "errors",
        "warnings",
        "refs",
        "dashboard",
        "dashboard_check",
        "ready",
        "ready_check",
        "studio_handoff",
        "studio_check",
    ]:
        if key not in payload:
            errors.append(f"missing required field: {key}")
    studio_refresh_ok = payload.get("studio_refresh_ok")
    if not isinstance(studio_refresh_ok, bool):
        errors.append("studio_refresh_ok must be a boolean")
        studio_refresh_ok = False
    studio_handoff_ready = payload.get("studio_handoff_ready")
    if not isinstance(studio_handoff_ready, bool):
        errors.append("studio_handoff_ready must be a boolean")
        studio_handoff_ready = False
    studio_check_ok = payload.get("studio_check_ok")
    if not isinstance(studio_check_ok, bool):
        errors.append("studio_check_ok must be a boolean")
        studio_check_ok = False
    count = payload.get("count")
    if not isinstance(count, int):
        errors.append("count must be an integer")
        count = 0
    payload_errors = payload.get("errors")
    if not isinstance(payload_errors, list):
        errors.append("errors must be a list")
    refresh_errors = _as_list(payload_errors)
    payload_warnings = payload.get("warnings")
    if not isinstance(payload_warnings, list):
        errors.append("warnings must be a list")
    refs = payload.get("refs")
    if not isinstance(refs, dict):
        errors.append("refs must be a mapping")
        refs = {}
    dashboard = payload.get("dashboard")
    if not isinstance(dashboard, dict):
        errors.append("dashboard must be a mapping")
        dashboard = {}
    dashboard_check = payload.get("dashboard_check")
    if not isinstance(dashboard_check, dict):
        errors.append("dashboard_check must be a mapping")
        dashboard_check = {}
    ready = payload.get("ready")
    if not isinstance(ready, dict):
        errors.append("ready must be a mapping")
        ready = {}
    ready_check = payload.get("ready_check")
    if not isinstance(ready_check, dict):
        errors.append("ready_check must be a mapping")
        ready_check = {}
    studio_handoff = payload.get("studio_handoff")
    if not isinstance(studio_handoff, dict):
        errors.append("studio_handoff must be a mapping")
        studio_handoff = {}
    studio_check = payload.get("studio_check")
    if not isinstance(studio_check, dict):
        errors.append("studio_check must be a mapping")
        studio_check = {}
    for key in ["dashboard", "dashboard_check", "ready", "ready_check", "studio_handoff", "studio_check"]:
        ref = str(refs.get(key)) if refs.get(key) is not None else None
        if not ref:
            errors.append(f"refs.{key} is required")
        elif not _project_ref_exists(root, ref):
            errors.append(f"refs.{key} does not exist: {ref}")
    _check_embedded_ref(errors, refs, "dashboard", dashboard)
    _check_embedded_ref(errors, refs, "dashboard_check", dashboard_check)
    _check_embedded_ref(errors, refs, "ready", ready)
    _check_embedded_ref(errors, refs, "ready_check", ready_check)
    _check_embedded_ref(errors, refs, "studio_handoff", studio_handoff)
    _check_embedded_ref(errors, refs, "studio_check", studio_check)
    dashboard_count = dashboard.get("count")
    if isinstance(dashboard_count, int) and isinstance(count, int) and dashboard_count != count:
        errors.append(f"dashboard.count does not match count: dashboard={dashboard_count}, count={count}")
    if isinstance(studio_handoff.get("studio_handoff_ready"), bool) and studio_handoff.get("studio_handoff_ready") != bool(studio_handoff_ready):
        errors.append("studio_handoff.studio_handoff_ready does not match studio_handoff_ready")
    if isinstance(studio_check.get("ok"), bool) and studio_check.get("ok") != bool(studio_check_ok):
        errors.append("studio_check.ok does not match studio_check_ok")
    if bool(studio_refresh_ok) and refresh_errors:
        errors.append("studio_refresh_ok cannot be true when errors are present")
    if bool(studio_refresh_ok) and not bool(studio_handoff_ready):
        errors.append("studio_refresh_ok cannot be true when studio_handoff_ready is false")
    if bool(studio_refresh_ok) and not bool(studio_check_ok):
        errors.append("studio_refresh_ok cannot be true when studio_check_ok is false")
    if not bool(studio_refresh_ok) and not refresh_errors:
        warnings.append("studio_refresh_ok is false but errors are empty")
    refresh_path_ref = _relative(refresh_path, root)
    return PackMarketplaceStatusStudioRefreshCheck(
        ok=not errors,
        refresh_ref=refresh_path_ref,
        studio_handoff_ref=str(refs.get("studio_handoff")) if refs.get("studio_handoff") is not None else None,
        studio_check_ref=str(refs.get("studio_check")) if refs.get("studio_check") is not None else None,
        studio_refresh_ok=bool(studio_refresh_ok),
        checked_at=_now(),
        error_count=len(_dedupe(errors)),
        warning_count=len(_dedupe(warnings)),
        errors=_dedupe(errors),
        warnings=_dedupe(warnings),
    )


def save_pack_marketplace_status_studio_refresh_check(
    project_root: Path,
    check: PackMarketplaceStatusStudioRefreshCheck,
    out_path: Path | None = None,
) -> PackMarketplaceStatusStudioRefreshCheck:
    """Studio marketplace status refresh check report를 저장한다."""
    root = Path(project_root).resolve()
    target = Path(out_path) if out_path is not None else default_marketplace_status_studio_refresh_check_path(root)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    check.saved_ref = _relative(target, root)
    _save_yaml(target, check.to_dict())
    _save_yaml(default_marketplace_status_studio_refresh_check_latest_path(root), check.to_dict())
    return check


def load_pack_marketplace_status_studio_refresh_check(project_root: Path, check_ref: str) -> tuple[PackMarketplaceStatusStudioRefreshCheck, Path]:
    """저장된 Studio marketplace status refresh check report를 읽는다."""
    root = Path(project_root).resolve()
    path = resolve_pack_marketplace_status_studio_refresh_check_path(root, check_ref)
    return _status_studio_refresh_check_from_dict(_load_yaml(path), path), path


def refresh_pack_marketplace_status_studio_handoff(
    project_root: Path,
    *,
    status_filter: str | None = None,
    limit: int = 20,
    handoff_out_path: Path | None = None,
    refresh_out_path: Path | None = None,
) -> dict[str, Any]:
    """marketplace status부터 최종 Studio handoff check까지 한 번에 갱신한다."""
    root = Path(project_root).resolve()
    resolved_filter = str(status_filter or "").strip()
    resolved_limit = max(0, int(limit))
    statuses = filter_pack_marketplace_statuses(build_pack_marketplace_status_list(root), resolved_filter)
    limited_statuses = statuses[:resolved_limit]
    dashboard_payload = pack_marketplace_status_dashboard_payload(
        limited_statuses,
        status_filter=resolved_filter,
        summary=summarize_pack_marketplace_statuses(limited_statuses),
    )
    saved_dashboard = save_pack_marketplace_status_dashboard(root, dashboard_payload)
    dashboard_check = check_pack_marketplace_status_dashboard(root, str(saved_dashboard["saved_ref"]))
    dashboard_check = save_pack_marketplace_status_check(root, dashboard_check)
    ready_payload = build_pack_marketplace_status_ready(
        root,
        status_ref=str(saved_dashboard["saved_ref"]),
        check_ref=str(dashboard_check.saved_ref or "latest"),
    )
    saved_ready = save_pack_marketplace_status_ready(root, ready_payload)
    ready_check = check_pack_marketplace_status_ready_report(root, str(saved_ready["saved_ref"]))
    ready_check = save_pack_marketplace_status_ready_check(root, ready_check)
    studio_handoff = build_pack_marketplace_status_studio_handoff(
        root,
        ready_ref=str(saved_ready["saved_ref"]),
        ready_check_ref=str(ready_check.saved_ref or "latest"),
    )
    saved_studio_handoff = save_pack_marketplace_status_studio_handoff(root, studio_handoff, handoff_out_path)
    studio_check = check_pack_marketplace_status_studio_handoff(root, str(saved_studio_handoff["saved_ref"]))
    studio_check = save_pack_marketplace_status_studio_check(root, studio_check)
    errors = _dedupe([*_as_list(saved_studio_handoff.get("errors")), *studio_check.errors])
    warnings = _dedupe([*_as_list(saved_studio_handoff.get("warnings")), *studio_check.warnings])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "studio_refresh_ok": not errors and bool(saved_studio_handoff.get("studio_handoff_ready")) and studio_check.ok,
        "studio_handoff_ready": bool(saved_studio_handoff.get("studio_handoff_ready")),
        "studio_check_ok": studio_check.ok,
        "status_filter": resolved_filter or None,
        "count": saved_dashboard.get("count", len(limited_statuses)),
        "errors": errors,
        "warnings": warnings,
        "refs": {
            "dashboard": saved_dashboard.get("saved_ref"),
            "dashboard_check": dashboard_check.saved_ref,
            "ready": saved_ready.get("saved_ref"),
            "ready_check": ready_check.saved_ref,
            "studio_handoff": saved_studio_handoff.get("saved_ref"),
            "studio_check": studio_check.saved_ref,
        },
        "dashboard": saved_dashboard,
        "dashboard_check": dashboard_check.to_dict(),
        "ready": saved_ready,
        "ready_check": ready_check.to_dict(),
        "studio_handoff": saved_studio_handoff,
        "studio_check": studio_check.to_dict(),
    }
    return save_pack_marketplace_status_studio_refresh(root, payload, refresh_out_path)


def build_pack_marketplace_status_ready(
    project_root: Path,
    *,
    status_ref: str = "latest",
    check_ref: str = "latest",
) -> dict[str, Any]:
    """Studio UI가 읽을 marketplace status dashboard 준비 상태를 만든다."""
    root = Path(project_root).resolve()
    dashboard, status_path = load_pack_marketplace_status_dashboard(root, status_ref)
    check, check_path = load_pack_marketplace_status_check(root, check_ref)
    status_path_ref = _relative(status_path, root)
    check_path_ref = _relative(check_path, root)
    errors: list[str] = []
    if not check.ok:
        errors.extend(check.errors)
    if check.status_ref and check.status_ref != status_path_ref:
        errors.append(f"check report points to {check.status_ref}, not {status_path_ref}")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "ready_for_studio": not errors,
        "status_ref": status_path_ref,
        "check_ref": check_path_ref,
        "check_ok": check.ok,
        "errors": _dedupe(errors),
        "dashboard": dashboard,
        "check": check.to_dict(),
    }


def default_marketplace_listing_dir(project_root: Path) -> Path:
    """marketplace listing draft 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "marketplace" / "listings"


def default_marketplace_listing_path(project_root: Path, draft: PackMarketplaceListingDraft) -> Path:
    """기본 marketplace listing draft 경로."""
    return default_marketplace_listing_dir(project_root) / f"{_slug(draft.listing_id, 'listing')}.yaml"


def default_marketplace_listing_latest_path(project_root: Path) -> Path:
    """latest marketplace listing draft 경로."""
    return default_marketplace_listing_dir(project_root) / "latest.yaml"


def default_marketplace_review_dir(project_root: Path) -> Path:
    """marketplace review decision 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "marketplace" / "reviews"


def default_marketplace_review_path(project_root: Path, review: PackMarketplaceReviewDecision) -> Path:
    """기본 marketplace review decision 경로."""
    return default_marketplace_review_dir(project_root) / f"{_slug(review.review_id, 'review')}.yaml"


def default_marketplace_review_latest_path(project_root: Path) -> Path:
    """latest marketplace review decision 경로."""
    return default_marketplace_review_dir(project_root) / "latest.yaml"


def default_marketplace_status_dir(project_root: Path) -> Path:
    """marketplace status dashboard snapshot 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "marketplace" / "status"


def default_marketplace_status_path(project_root: Path) -> Path:
    """기본 marketplace status dashboard snapshot 경로."""
    return default_marketplace_status_dir(project_root) / f"status_{_stamp_unique()}.yaml"


def default_marketplace_status_latest_path(project_root: Path) -> Path:
    """latest marketplace status dashboard snapshot 경로."""
    return default_marketplace_status_dir(project_root) / "latest.yaml"


def default_marketplace_status_check_dir(project_root: Path) -> Path:
    """marketplace status dashboard check report 저장 디렉터리."""
    return default_marketplace_status_dir(project_root) / "checks"


def default_marketplace_status_check_path(project_root: Path) -> Path:
    """기본 marketplace status dashboard check report 경로."""
    return default_marketplace_status_check_dir(project_root) / f"status_check_{_stamp_unique()}.yaml"


def default_marketplace_status_check_latest_path(project_root: Path) -> Path:
    """latest marketplace status dashboard check report 경로."""
    return default_marketplace_status_check_dir(project_root) / "latest.yaml"


def default_marketplace_status_ready_dir(project_root: Path) -> Path:
    """Studio marketplace status ready report 저장 디렉터리."""
    return default_marketplace_status_dir(project_root) / "ready"


def default_marketplace_status_ready_path(project_root: Path) -> Path:
    """기본 Studio marketplace status ready report 경로."""
    return default_marketplace_status_ready_dir(project_root) / f"status_ready_{_stamp_unique()}.yaml"


def default_marketplace_status_ready_latest_path(project_root: Path) -> Path:
    """latest Studio marketplace status ready report 경로."""
    return default_marketplace_status_ready_dir(project_root) / "latest.yaml"


def default_marketplace_status_ready_check_dir(project_root: Path) -> Path:
    """Studio marketplace status ready check report 저장 디렉터리."""
    return default_marketplace_status_ready_dir(project_root) / "checks"


def default_marketplace_status_ready_check_path(project_root: Path) -> Path:
    """기본 Studio marketplace status ready check report 경로."""
    return default_marketplace_status_ready_check_dir(project_root) / f"status_ready_check_{_stamp_unique()}.yaml"


def default_marketplace_status_ready_check_latest_path(project_root: Path) -> Path:
    """latest Studio marketplace status ready check report 경로."""
    return default_marketplace_status_ready_check_dir(project_root) / "latest.yaml"


def default_marketplace_status_studio_handoff_dir(project_root: Path) -> Path:
    """Studio marketplace status handoff payload 저장 디렉터리."""
    return default_marketplace_status_dir(project_root) / "studio"


def default_marketplace_status_studio_handoff_path(project_root: Path) -> Path:
    """기본 Studio marketplace status handoff payload 경로."""
    return default_marketplace_status_studio_handoff_dir(project_root) / f"status_studio_{_stamp_unique()}.yaml"


def default_marketplace_status_studio_handoff_latest_path(project_root: Path) -> Path:
    """latest Studio marketplace status handoff payload 경로."""
    return default_marketplace_status_studio_handoff_dir(project_root) / "latest.yaml"


def default_marketplace_status_studio_check_dir(project_root: Path) -> Path:
    """Studio marketplace status handoff check report 저장 디렉터리."""
    return default_marketplace_status_studio_handoff_dir(project_root) / "checks"


def default_marketplace_status_studio_check_path(project_root: Path) -> Path:
    """기본 Studio marketplace status handoff check report 경로."""
    return default_marketplace_status_studio_check_dir(project_root) / f"status_studio_check_{_stamp_unique()}.yaml"


def default_marketplace_status_studio_check_latest_path(project_root: Path) -> Path:
    """latest Studio marketplace status handoff check report 경로."""
    return default_marketplace_status_studio_check_dir(project_root) / "latest.yaml"


def default_marketplace_status_studio_refresh_dir(project_root: Path) -> Path:
    """Studio marketplace status refresh report 저장 디렉터리."""
    return default_marketplace_status_studio_handoff_dir(project_root) / "refreshes"


def default_marketplace_status_studio_refresh_path(project_root: Path) -> Path:
    """기본 Studio marketplace status refresh report 경로."""
    return default_marketplace_status_studio_refresh_dir(project_root) / f"status_studio_refresh_{_stamp_unique()}.yaml"


def default_marketplace_status_studio_refresh_latest_path(project_root: Path) -> Path:
    """latest Studio marketplace status refresh report 경로."""
    return default_marketplace_status_studio_refresh_dir(project_root) / "latest.yaml"


def default_marketplace_status_studio_refresh_check_dir(project_root: Path) -> Path:
    """Studio marketplace status refresh check report 저장 디렉터리."""
    return default_marketplace_status_studio_refresh_dir(project_root) / "checks"


def default_marketplace_status_studio_refresh_check_path(project_root: Path) -> Path:
    """기본 Studio marketplace status refresh check report 경로."""
    return default_marketplace_status_studio_refresh_check_dir(project_root) / f"status_studio_refresh_check_{_stamp_unique()}.yaml"


def default_marketplace_status_studio_refresh_check_latest_path(project_root: Path) -> Path:
    """latest Studio marketplace status refresh check report 경로."""
    return default_marketplace_status_studio_refresh_check_dir(project_root) / "latest.yaml"


def resolve_pack_marketplace_listing_path(project_root: Path, listing_ref: str) -> Path:
    """listing id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(listing_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(listing_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_listing_latest_path(root))
    listings_dir = default_marketplace_listing_dir(root)
    needle = _slug(str(listing_ref), "listing")
    if listings_dir.exists():
        for path in sorted(listings_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "listing"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace listing draft not found: {listing_ref}")


def resolve_pack_marketplace_review_path(project_root: Path, review_ref: str) -> Path:
    """review id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(review_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(review_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_review_latest_path(root))
    reviews_dir = default_marketplace_review_dir(root)
    needle = _slug(str(review_ref), "review")
    if reviews_dir.exists():
        for path in sorted(reviews_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "review"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace review decision not found: {review_ref}")


def resolve_pack_marketplace_status_path(project_root: Path, status_ref: str) -> Path:
    """status dashboard id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(status_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(status_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_latest_path(root))
    status_dir = default_marketplace_status_dir(root)
    needle = _slug(str(status_ref), "status")
    if status_dir.exists():
        for path in sorted(status_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status dashboard not found: {status_ref}")


def resolve_pack_marketplace_status_check_path(project_root: Path, check_ref: str) -> Path:
    """status check report id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(check_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(check_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_check_latest_path(root))
    checks_dir = default_marketplace_status_check_dir(root)
    needle = _slug(str(check_ref), "status-check")
    if checks_dir.exists():
        for path in sorted(checks_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status-check"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status check report not found: {check_ref}")


def resolve_pack_marketplace_status_ready_path(project_root: Path, ready_ref: str) -> Path:
    """status ready report id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(ready_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(ready_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_ready_latest_path(root))
    ready_dir = default_marketplace_status_ready_dir(root)
    needle = _slug(str(ready_ref), "status-ready")
    if ready_dir.exists():
        for path in sorted(ready_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status-ready"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status ready report not found: {ready_ref}")


def resolve_pack_marketplace_status_ready_check_path(project_root: Path, check_ref: str) -> Path:
    """status ready check report id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(check_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(check_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_ready_check_latest_path(root))
    checks_dir = default_marketplace_status_ready_check_dir(root)
    needle = _slug(str(check_ref), "status-ready-check")
    if checks_dir.exists():
        for path in sorted(checks_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status-ready-check"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status ready check report not found: {check_ref}")


def resolve_pack_marketplace_status_studio_handoff_path(project_root: Path, handoff_ref: str) -> Path:
    """status studio handoff id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(handoff_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(handoff_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_studio_handoff_latest_path(root))
    handoff_dir = default_marketplace_status_studio_handoff_dir(root)
    needle = _slug(str(handoff_ref), "status-studio")
    if handoff_dir.exists():
        for path in sorted(handoff_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status-studio"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status studio handoff not found: {handoff_ref}")


def resolve_pack_marketplace_status_studio_check_path(project_root: Path, check_ref: str) -> Path:
    """status studio check report id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(check_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(check_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_studio_check_latest_path(root))
    checks_dir = default_marketplace_status_studio_check_dir(root)
    needle = _slug(str(check_ref), "status-studio-check")
    if checks_dir.exists():
        for path in sorted(checks_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status-studio-check"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status studio check report not found: {check_ref}")


def resolve_pack_marketplace_status_studio_refresh_path(project_root: Path, refresh_ref: str) -> Path:
    """status studio refresh report id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(refresh_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(refresh_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_studio_refresh_latest_path(root))
    refresh_dir = default_marketplace_status_studio_refresh_dir(root)
    needle = _slug(str(refresh_ref), "status-studio-refresh")
    if refresh_dir.exists():
        for path in sorted(refresh_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status-studio-refresh"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status studio refresh report not found: {refresh_ref}")


def resolve_pack_marketplace_status_studio_refresh_check_path(project_root: Path, check_ref: str) -> Path:
    """status studio refresh check report id/path/latest를 실제 YAML 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = Path(str(check_ref))
    candidates: list[Path] = []
    if raw.exists():
        candidates.append(raw.resolve())
    if not raw.is_absolute():
        candidates.append((root / raw).resolve())
    if str(check_ref).strip().lower() == "latest":
        candidates.append(default_marketplace_status_studio_refresh_check_latest_path(root))
    checks_dir = default_marketplace_status_studio_refresh_check_dir(root)
    needle = _slug(str(check_ref), "status-studio-refresh-check")
    if checks_dir.exists():
        for path in sorted(checks_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
            if needle in _slug(path.stem, "status-studio-refresh-check"):
                candidates.append(path.resolve())
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"marketplace status studio refresh check report not found: {check_ref}")


def render_pack_marketplace_listing(
    draft: PackMarketplaceListingDraft,
    latest_review: PackMarketplaceReviewDecision | None = None,
) -> str:
    """marketplace listing draft를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Marketplace Listing Draft",
        "==================================================",
        "",
        "Pack:",
        f"  {draft.pack_id}",
        "",
        "Listing:",
        f"  status: {draft.listing_status}",
        f"  safe_to_publish: {str(draft.safe_to_publish).lower()}",
        f"  marketplace_readiness: {draft.marketplace_readiness}",
        "",
        "Proof:",
        f"  status: {draft.proof_status}",
        f"  export: {draft.proof_export_ref or 'none'}",
        "",
        "Metadata:",
        f"  author: {draft.author or 'unknown'}",
        f"  license: {draft.license or 'unspecified'}",
        f"  provenance: {draft.provenance or 'unknown'}",
        f"  visibility: {draft.public_visibility}",
        f"  signature: {draft.signature_status}",
    ]
    if draft.marketplace_blockers:
        lines.extend(["", "Blockers:"])
        lines.extend([f"  - {item}" for item in draft.marketplace_blockers])
    if draft.known_limits:
        lines.extend(["", "Known limits:"])
        lines.extend([f"  - {item}" for item in draft.known_limits])
    if draft.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in draft.next_actions])
    if draft.saved_ref:
        lines.extend(["", "Saved:", f"  {draft.saved_ref}"])
    if latest_review is not None:
        lines.extend(
            [
                "",
                "Latest review:",
                f"  decision: {latest_review.decision}",
                f"  reviewer: {latest_review.reviewer}",
                f"  review: {latest_review.saved_ref or latest_review.review_id}",
            ]
        )
    if draft.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in draft.warnings])
    if draft.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in draft.errors])
    return "\n".join(lines)


def render_pack_marketplace_review(review: PackMarketplaceReviewDecision) -> str:
    """marketplace review decision을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Marketplace Review",
        "==================================================",
        "",
        "Pack:",
        f"  {review.pack_id}",
        "",
        "Decision:",
        f"  {review.decision}",
        f"  reviewer: {review.reviewer}",
        f"  safe_to_publish: {str(review.safe_to_publish).lower()}",
        f"  marketplace_readiness: {review.marketplace_readiness}",
    ]
    if review.notes:
        lines.extend(["", "Notes:", f"  {review.notes}"])
    if review.blockers:
        lines.extend(["", "Blockers:"])
        lines.extend([f"  - {item}" for item in review.blockers])
    if review.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in review.next_actions])
    if review.saved_ref:
        lines.extend(["", "Saved:", f"  {review.saved_ref}"])
    if review.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in review.warnings])
    if review.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in review.errors])
    return "\n".join(lines)


def render_pack_marketplace_review_list(reviews: list[PackMarketplaceReviewDecision]) -> str:
    """marketplace review decision 목록을 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Marketplace Reviews",
        "==================================================",
        "",
        f"Count: {len(reviews)}",
    ]
    if not reviews:
        lines.extend(["", "No marketplace review decisions found."])
        return "\n".join(lines)
    lines.extend(["", "Reviews:"])
    for review in reviews:
        saved = f" ({review.saved_ref})" if review.saved_ref else ""
        lines.append(
            f"  - {review.review_id}: {review.decision} / {review.pack_id} / "
            f"safe_to_publish={str(review.safe_to_publish).lower()}{saved}"
        )
    return "\n".join(lines)


def render_pack_marketplace_status(status: PackMarketplaceStatus) -> str:
    """marketplace 운영 상태를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Marketplace Status",
        "==================================================",
        "",
        "Pack:",
        f"  {status.pack_id}",
        "",
        "Status:",
        f"  operational_status: {status.operational_status}",
        f"  listing_status: {status.listing_status}",
        f"  marketplace_readiness: {status.marketplace_readiness}",
        f"  safe_to_publish: {str(status.safe_to_publish).lower()}",
    ]
    if status.latest_review_decision:
        lines.extend(
            [
                "",
                "Latest review:",
                f"  decision: {status.latest_review_decision}",
                f"  review: {status.latest_review_ref or status.latest_review_id}",
            ]
        )
    else:
        lines.extend(["", "Latest review:", "  none"])
    if status.blockers:
        lines.extend(["", "Blockers:"])
        lines.extend([f"  - {item}" for item in status.blockers])
    if status.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in status.next_actions])
    return "\n".join(lines)


def render_pack_marketplace_status_list(
    statuses: list[PackMarketplaceStatus],
    summary: dict[str, int] | None = None,
) -> str:
    """marketplace 운영 상태 목록을 사람이 읽기 좋게 렌더링한다."""
    resolved_summary = summary or summarize_pack_marketplace_statuses(statuses)
    lines = [
        "Pack Marketplace Status List",
        "==================================================",
        "",
        f"Count: {len(statuses)}",
    ]
    if resolved_summary:
        lines.extend(["", "Summary:"])
        for key in sorted(resolved_summary):
            lines.append(f"  {key}: {resolved_summary[key]}")
    if not statuses:
        lines.extend(["", "No marketplace listing statuses found."])
        return "\n".join(lines)
    lines.extend(["", "Listings:"])
    for status in statuses:
        review = status.latest_review_decision or "unreviewed"
        lines.append(
            f"  - {status.listing_id}: {status.operational_status} / "
            f"{status.pack_id} / review={review}"
        )
    return "\n".join(lines)


def render_pack_marketplace_status_dashboard(payload: dict[str, Any]) -> str:
    """저장된 marketplace status dashboard snapshot을 사람이 읽기 좋게 렌더링한다."""
    statuses = payload.get("statuses") if isinstance(payload.get("statuses"), list) else []
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "Pack Marketplace Status Dashboard",
        "==================================================",
        "",
        f"Generated: {payload.get('generated_at') or 'unknown'}",
        f"Count: {payload.get('count', len(statuses))}",
        f"Status filter: {payload.get('status_filter') or 'none'}",
    ]
    if payload.get("saved_ref"):
        lines.append(f"Saved: {payload.get('saved_ref')}")
    if summary:
        lines.extend(["", "Summary:"])
        for key in sorted(summary):
            lines.append(f"  {key}: {summary[key]}")
    if statuses:
        lines.extend(["", "Listings:"])
        for item in statuses:
            if not isinstance(item, dict):
                continue
            review = item.get("latest_review_decision") or "unreviewed"
            lines.append(
                f"  - {item.get('listing_id', 'unknown')}: "
                f"{item.get('operational_status', 'unknown')} / "
                f"{item.get('pack_id', 'unknown')} / review={review}"
            )
    else:
        lines.extend(["", "No marketplace listing statuses found."])
    return "\n".join(lines)


def render_pack_marketplace_status_check(check: PackMarketplaceStatusCheck) -> str:
    """marketplace status dashboard snapshot 검증 결과를 렌더링한다."""
    lines = [
        "Pack Marketplace Status Check",
        "==================================================",
        "",
        f"OK: {str(check.ok).lower()}",
        f"Status ref: {check.status_ref or 'unknown'}",
        f"Errors: {check.error_count}",
        f"Warnings: {check.warning_count}",
    ]
    if check.saved_ref:
        lines.extend(["", "Saved:", f"  {check.saved_ref}"])
    if check.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in check.errors])
    if check.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in check.warnings])
    return "\n".join(lines)


def render_pack_marketplace_status_ready(payload: dict[str, Any]) -> str:
    """Studio marketplace status ready payload를 사람이 읽기 좋게 렌더링한다."""
    dashboard = payload.get("dashboard") if isinstance(payload.get("dashboard"), dict) else {}
    check = payload.get("check") if isinstance(payload.get("check"), dict) else {}
    errors = _as_list(payload.get("errors"))
    lines = [
        "Pack Marketplace Status Ready",
        "==================================================",
        "",
        f"Ready for Studio: {str(bool(payload.get('ready_for_studio'))).lower()}",
        f"Status ref: {payload.get('status_ref') or 'unknown'}",
        f"Check ref: {payload.get('check_ref') or 'unknown'}",
        f"Check OK: {str(bool(payload.get('check_ok'))).lower()}",
        "",
        "Dashboard:",
        f"  count: {dashboard.get('count', 0)}",
        f"  status_filter: {dashboard.get('status_filter') or 'none'}",
        "",
        "Check:",
        f"  errors: {check.get('error_count', 0)}",
        f"  warnings: {check.get('warning_count', 0)}",
    ]
    if payload.get("saved_ref"):
        lines.extend(["", "Saved:", f"  {payload.get('saved_ref')}"])
    if errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in errors])
    return "\n".join(lines)


def render_pack_marketplace_status_ready_check(check: PackMarketplaceStatusReadyCheck) -> str:
    """Studio marketplace status ready check report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Marketplace Status Ready Check",
        "==================================================",
        "",
        f"OK: {str(check.ok).lower()}",
        f"Ready for Studio: {str(check.ready_for_studio).lower()}",
        f"Ready ref: {check.ready_ref or 'unknown'}",
        f"Status ref: {check.status_ref or 'unknown'}",
        f"Check ref: {check.check_ref or 'unknown'}",
        f"Errors: {check.error_count}",
        f"Warnings: {check.warning_count}",
    ]
    if check.saved_ref:
        lines.extend(["", "Saved:", f"  {check.saved_ref}"])
    if check.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in check.errors])
    if check.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in check.warnings])
    return "\n".join(lines)


def render_pack_marketplace_status_studio_handoff(payload: dict[str, Any]) -> str:
    """Studio marketplace status handoff payload를 사람이 읽기 좋게 렌더링한다."""
    dashboard = payload.get("dashboard") if isinstance(payload.get("dashboard"), dict) else {}
    errors = _as_list(payload.get("errors"))
    warnings = _as_list(payload.get("warnings"))
    lines = [
        "Pack Marketplace Status Studio Handoff",
        "==================================================",
        "",
        f"Studio handoff ready: {str(bool(payload.get('studio_handoff_ready'))).lower()}",
        f"Ready for Studio: {str(bool(payload.get('ready_for_studio'))).lower()}",
        f"Ready check OK: {str(bool(payload.get('ready_check_ok'))).lower()}",
        f"Ready ref: {payload.get('ready_ref') or 'unknown'}",
        f"Ready check ref: {payload.get('ready_check_ref') or 'unknown'}",
        f"Status ref: {payload.get('status_ref') or 'unknown'}",
        f"Check ref: {payload.get('check_ref') or 'unknown'}",
        "",
        "Dashboard:",
        f"  count: {dashboard.get('count', 0)}",
        f"  status_filter: {dashboard.get('status_filter') or 'none'}",
    ]
    if payload.get("saved_ref"):
        lines.extend(["", "Saved:", f"  {payload.get('saved_ref')}"])
    if errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in errors])
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in warnings])
    return "\n".join(lines)


def render_pack_marketplace_status_studio_check(check: PackMarketplaceStatusStudioCheck) -> str:
    """Studio marketplace status handoff check report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Marketplace Status Studio Check",
        "==================================================",
        "",
        f"OK: {str(check.ok).lower()}",
        f"Studio handoff ready: {str(check.studio_handoff_ready).lower()}",
        f"Ready for Studio: {str(check.ready_for_studio).lower()}",
        f"Handoff ref: {check.handoff_ref or 'unknown'}",
        f"Ready ref: {check.ready_ref or 'unknown'}",
        f"Ready check ref: {check.ready_check_ref or 'unknown'}",
        f"Errors: {check.error_count}",
        f"Warnings: {check.warning_count}",
    ]
    if check.saved_ref:
        lines.extend(["", "Saved:", f"  {check.saved_ref}"])
    if check.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in check.errors])
    if check.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in check.warnings])
    return "\n".join(lines)


def render_pack_marketplace_status_studio_refresh(payload: dict[str, Any]) -> str:
    """Studio marketplace status refresh 결과를 사람이 읽기 좋게 렌더링한다."""
    refs = payload.get("refs") if isinstance(payload.get("refs"), dict) else {}
    errors = _as_list(payload.get("errors"))
    warnings = _as_list(payload.get("warnings"))
    lines = [
        "Pack Marketplace Status Studio Refresh",
        "==================================================",
        "",
        f"Refresh OK: {str(bool(payload.get('studio_refresh_ok'))).lower()}",
        f"Studio handoff ready: {str(bool(payload.get('studio_handoff_ready'))).lower()}",
        f"Studio check OK: {str(bool(payload.get('studio_check_ok'))).lower()}",
        f"Count: {payload.get('count', 0)}",
        f"Status filter: {payload.get('status_filter') or 'none'}",
        "",
        "Refs:",
        f"  dashboard: {refs.get('dashboard') or 'unknown'}",
        f"  dashboard_check: {refs.get('dashboard_check') or 'unknown'}",
        f"  ready: {refs.get('ready') or 'unknown'}",
        f"  ready_check: {refs.get('ready_check') or 'unknown'}",
        f"  studio_handoff: {refs.get('studio_handoff') or 'unknown'}",
        f"  studio_check: {refs.get('studio_check') or 'unknown'}",
    ]
    if payload.get("saved_ref"):
        lines.extend(["", "Saved:", f"  {payload.get('saved_ref')}"])
    if errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in errors])
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in warnings])
    return "\n".join(lines)


def render_pack_marketplace_status_studio_refresh_check(check: PackMarketplaceStatusStudioRefreshCheck) -> str:
    """Studio marketplace status refresh check report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Pack Marketplace Status Studio Refresh Check",
        "==================================================",
        "",
        f"OK: {str(check.ok).lower()}",
        f"Refresh OK: {str(check.studio_refresh_ok).lower()}",
        f"Refresh ref: {check.refresh_ref or 'unknown'}",
        f"Studio handoff ref: {check.studio_handoff_ref or 'unknown'}",
        f"Studio check ref: {check.studio_check_ref or 'unknown'}",
        f"Errors: {check.error_count}",
        f"Warnings: {check.warning_count}",
    ]
    if check.saved_ref:
        lines.extend(["", "Saved:", f"  {check.saved_ref}"])
    if check.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in check.errors])
    if check.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in check.warnings])
    return "\n".join(lines)


def render_pack_marketplace_status_studio_refresh_list(payload: dict[str, Any]) -> str:
    """Studio marketplace status refresh report 목록을 사람이 읽기 좋게 렌더링한다."""
    reports = payload.get("reports") if isinstance(payload.get("reports"), list) else []
    lines = [
        "Pack Marketplace Status Studio Refresh Reports",
        "==================================================",
        "",
        f"Count: {payload.get('count', len(reports))}",
        f"Total: {payload.get('total', len(reports))}",
        f"Latest: {payload.get('latest_ref') or 'none'}",
    ]
    if not reports:
        lines.extend(["", "No Studio refresh reports found."])
        return "\n".join(lines)
    lines.extend(["", "Reports:"])
    for item in reports:
        if not isinstance(item, dict):
            continue
        lines.append(
            f"  - {item.get('saved_ref') or item.get('path')}: "
            f"ok={str(bool(item.get('studio_refresh_ok'))).lower()} / "
            f"count={item.get('count', 0)} / "
            f"status_filter={item.get('status_filter') or 'none'} / "
            f"studio_handoff={item.get('studio_handoff_ref') or 'unknown'}"
        )
    return "\n".join(lines)


def _installed_record(root: Path, pack_ref: str) -> InstalledPackRecord:
    index = InstalledPackStore().load(default_installed_packs_path(root))
    return InstalledPackStore().find(index, pack_ref)


def _manifest_path(root: Path, record: InstalledPackRecord) -> Path | None:
    manifest_ref = record.latest_manifest_ref or record.manifest_ref
    if not manifest_ref:
        return None
    path = Path(manifest_ref)
    return path if path.is_absolute() else root / path


def _proof_export(root: Path, pack_id: str, proof_export_ref: str | None) -> PackProofExportSnapshot:
    if proof_export_ref:
        return PackProofExportStoreLike().load(root, proof_export_ref)
    existing = latest_pack_proof_export(root, pack_id)
    if existing is not None:
        return existing
    return PackProofExporter().export(root, pack_id)


class PackProofExportStoreLike:
    """순환 import 없이 proof export path를 해석하는 작은 어댑터."""

    def load(self, root: Path, proof_export_ref: str) -> PackProofExportSnapshot:
        """proof export ref를 읽는다."""
        from engine.project_pack_proof_export import PackProofExportStore

        return PackProofExportStore().load_yaml(resolve_pack_proof_export_path(root, proof_export_ref))


def _listing_status(
    record: InstalledPackRecord,
    proof_export: PackProofExportSnapshot,
    source: dict[str, Any],
) -> tuple[str, bool, list[str]]:
    blockers: list[str] = []
    if proof_export.marketplace_readiness == "blocked":
        blockers.extend(proof_export.marketplace_blockers)
        return "blocked", False, _dedupe(blockers)
    visibility = str(source.get("public_visibility") or "private")
    signature = str(source.get("signature_status") or "unsigned_local")
    if visibility != "public":
        blockers.append("listing visibility is not public")
    if signature in {"", "unsigned_local"}:
        blockers.append("pack is not signed for marketplace distribution")
    if record.manifest_sha256 is None:
        blockers.append("manifest checksum is missing")
    if proof_export.marketplace_readiness == "proof_backed_candidate" and not blockers:
        return "ready_for_review", True, []
    return proof_export.marketplace_readiness, False, _dedupe(blockers)


def _listing_next_actions(record: InstalledPackRecord, safe_to_publish: bool) -> list[str]:
    if safe_to_publish:
        return [f"cambrian registry export --out dist/{_slug(record.pack_id, 'pack')}-registry"]
    return [
        "keep collecting local runtime evidence",
        "sign the pack before marketplace publication",
    ]


def _draft_from_dict(payload: dict[str, Any], path: Path | None = None) -> PackMarketplaceListingDraft:
    return PackMarketplaceListingDraft(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        listing_id=str(payload.get("listing_id") or f"marketplace-listing-{_stamp()}"),
        generated_at=str(payload.get("generated_at") or _now()),
        pack_id=str(payload.get("pack_id") or "unknown"),
        pack_name=str(payload.get("pack_name") or "unknown"),
        pack_kind=str(payload.get("pack_kind") or "unknown"),
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        author=str(payload.get("author")) if payload.get("author") is not None else None,
        license=str(payload.get("license")) if payload.get("license") is not None else None,
        provenance=str(payload.get("provenance")) if payload.get("provenance") is not None else None,
        public_visibility=str(payload.get("public_visibility") or "private"),
        signature_status=str(payload.get("signature_status") or "unsigned_local"),
        manifest_ref=str(payload.get("manifest_ref")) if payload.get("manifest_ref") is not None else None,
        manifest_sha256=str(payload.get("manifest_sha256")) if payload.get("manifest_sha256") is not None else None,
        proof_export_ref=str(payload.get("proof_export_ref")) if payload.get("proof_export_ref") is not None else None,
        proof_status=str(payload.get("proof_status") or "unproven"),
        marketplace_readiness=str(payload.get("marketplace_readiness") or "draft_only"),
        listing_status=str(payload.get("listing_status") or "draft_only"),
        safe_to_publish=bool(payload.get("safe_to_publish", False)),
        install_command=str(payload.get("install_command") or ""),
        known_limits=_as_list(payload.get("known_limits")),
        evolution_lineage=_as_list(payload.get("evolution_lineage")),
        marketplace_blockers=_as_list(payload.get("marketplace_blockers")),
        next_actions=_as_list(payload.get("next_actions")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else (_relative(path, Path.cwd()) if path else None),
    )


def _review_from_dict(payload: dict[str, Any], path: Path | None = None) -> PackMarketplaceReviewDecision:
    return PackMarketplaceReviewDecision(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        review_id=str(payload.get("review_id") or f"marketplace-review-{_stamp()}"),
        reviewed_at=str(payload.get("reviewed_at") or _now()),
        listing_id=str(payload.get("listing_id") or "unknown"),
        listing_ref=str(payload.get("listing_ref")) if payload.get("listing_ref") is not None else None,
        pack_id=str(payload.get("pack_id") or "unknown"),
        decision=str(payload.get("decision") or "needs_work"),
        reviewer=str(payload.get("reviewer") or "local_reviewer"),
        notes=str(payload.get("notes")) if payload.get("notes") is not None else None,
        listing_status=str(payload.get("listing_status") or "draft_only"),
        marketplace_readiness=str(payload.get("marketplace_readiness") or "draft_only"),
        safe_to_publish=bool(payload.get("safe_to_publish", False)),
        blockers=_as_list(payload.get("blockers")),
        next_actions=_as_list(payload.get("next_actions")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else (_relative(path, Path.cwd()) if path else None),
    )


def _status_check_from_dict(payload: dict[str, Any], path: Path | None = None) -> PackMarketplaceStatusCheck:
    return PackMarketplaceStatusCheck(
        ok=bool(payload.get("ok", False)),
        status_ref=str(payload.get("status_ref")) if payload.get("status_ref") is not None else None,
        checked_at=str(payload.get("checked_at") or _now()),
        error_count=int(payload.get("error_count") or 0),
        warning_count=int(payload.get("warning_count") or 0),
        errors=_as_list(payload.get("errors")),
        warnings=_as_list(payload.get("warnings")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else (_relative(path, Path.cwd()) if path else None),
    )


def _status_ready_check_from_dict(payload: dict[str, Any], path: Path | None = None) -> PackMarketplaceStatusReadyCheck:
    return PackMarketplaceStatusReadyCheck(
        ok=bool(payload.get("ok", False)),
        ready_ref=str(payload.get("ready_ref")) if payload.get("ready_ref") is not None else None,
        status_ref=str(payload.get("status_ref")) if payload.get("status_ref") is not None else None,
        check_ref=str(payload.get("check_ref")) if payload.get("check_ref") is not None else None,
        ready_for_studio=bool(payload.get("ready_for_studio", False)),
        checked_at=str(payload.get("checked_at") or _now()),
        error_count=int(payload.get("error_count") or 0),
        warning_count=int(payload.get("warning_count") or 0),
        errors=_as_list(payload.get("errors")),
        warnings=_as_list(payload.get("warnings")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else (_relative(path, Path.cwd()) if path else None),
    )


def _status_studio_check_from_dict(payload: dict[str, Any], path: Path | None = None) -> PackMarketplaceStatusStudioCheck:
    return PackMarketplaceStatusStudioCheck(
        ok=bool(payload.get("ok", False)),
        handoff_ref=str(payload.get("handoff_ref")) if payload.get("handoff_ref") is not None else None,
        ready_ref=str(payload.get("ready_ref")) if payload.get("ready_ref") is not None else None,
        ready_check_ref=str(payload.get("ready_check_ref")) if payload.get("ready_check_ref") is not None else None,
        studio_handoff_ready=bool(payload.get("studio_handoff_ready", False)),
        ready_for_studio=bool(payload.get("ready_for_studio", False)),
        checked_at=str(payload.get("checked_at") or _now()),
        error_count=int(payload.get("error_count") or 0),
        warning_count=int(payload.get("warning_count") or 0),
        errors=_as_list(payload.get("errors")),
        warnings=_as_list(payload.get("warnings")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else (_relative(path, Path.cwd()) if path else None),
    )


def _status_studio_refresh_check_from_dict(payload: dict[str, Any], path: Path | None = None) -> PackMarketplaceStatusStudioRefreshCheck:
    return PackMarketplaceStatusStudioRefreshCheck(
        ok=bool(payload.get("ok", False)),
        refresh_ref=str(payload.get("refresh_ref")) if payload.get("refresh_ref") is not None else None,
        studio_handoff_ref=str(payload.get("studio_handoff_ref")) if payload.get("studio_handoff_ref") is not None else None,
        studio_check_ref=str(payload.get("studio_check_ref")) if payload.get("studio_check_ref") is not None else None,
        studio_refresh_ok=bool(payload.get("studio_refresh_ok", False)),
        checked_at=str(payload.get("checked_at") or _now()),
        error_count=int(payload.get("error_count") or 0),
        warning_count=int(payload.get("warning_count") or 0),
        errors=_as_list(payload.get("errors")),
        warnings=_as_list(payload.get("warnings")),
        saved_ref=str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else (_relative(path, Path.cwd()) if path else None),
    )


def _review_decision(decision: str) -> str:
    normalized = str(decision or "").strip().lower()
    if normalized not in {"needs_work", "rejected", "accepted"}:
        raise ValueError("marketplace review decision must be one of: needs_work, rejected, accepted")
    return normalized


def _review_next_actions(listing: PackMarketplaceListingDraft, decision: str) -> list[str]:
    if decision == "accepted":
        return [f"cambrian registry export --out dist/{_slug(listing.pack_id, 'pack')}-registry"]
    if decision == "rejected":
        return ["revise the agent contract or proof evidence before creating a new listing draft"]
    return _dedupe([*listing.next_actions, "create a new marketplace listing draft after fixes"])


def _marketplace_operational_status(
    draft: PackMarketplaceListingDraft,
    latest_review: PackMarketplaceReviewDecision | None,
) -> str:
    if draft.listing_status == "blocked":
        return "blocked"
    if latest_review is not None:
        if latest_review.decision == "accepted":
            return "accepted_ready"
        if latest_review.decision == "rejected":
            return "rejected"
        if latest_review.decision == "needs_work":
            return "needs_work"
    if draft.safe_to_publish:
        return "ready_for_review"
    return draft.marketplace_readiness or draft.listing_status


def _marketplace_status_blockers(
    draft: PackMarketplaceListingDraft,
    latest_review: PackMarketplaceReviewDecision | None,
) -> list[str]:
    blockers = list(draft.marketplace_blockers)
    if latest_review is not None and latest_review.decision in {"needs_work", "rejected"}:
        blockers.extend(latest_review.blockers)
    return _dedupe(blockers)


def _marketplace_status_next_actions(
    draft: PackMarketplaceListingDraft,
    latest_review: PackMarketplaceReviewDecision | None,
) -> list[str]:
    if latest_review is not None:
        return _dedupe(latest_review.next_actions)
    if draft.safe_to_publish:
        return ["record marketplace review decision before registry export"]
    return _dedupe(draft.next_actions)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _project_ref_exists(root: Path, ref: str) -> bool:
    raw = Path(str(ref))
    if raw.exists():
        return True
    if raw.is_absolute():
        return raw.exists()
    return (Path(root).resolve() / raw).exists()


def _check_embedded_ref(errors: list[str], refs: dict[str, Any], key: str, payload: dict[str, Any]) -> None:
    expected = str(refs.get(key)) if refs.get(key) is not None else None
    actual = str(payload.get("saved_ref")) if payload.get("saved_ref") is not None else None
    if expected and actual and actual != expected:
        errors.append(f"{key}.saved_ref points to {actual}, not {expected}")


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
