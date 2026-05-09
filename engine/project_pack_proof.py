"""Pack proof card와 local reputation report를 만든다."""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_pack_activation import current_active_pack
from engine.project_pack_install import InstalledPackRecord, InstalledPackStore, default_installed_packs_path
from engine.project_pack_usage import (
    PackUsageEventStore,
    PackUsageSummary,
    PackUsageSummaryBuilder,
    default_usage_events_dir,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
REPUTATION_VERDICTS = {"unproven", "promising", "useful", "strong", "regressed", "insufficient_data"}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓸 UTC timestamp를 반환한다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value: str | None) -> str:
    """파일명과 id 비교에 안전한 slug를 만든다."""
    text = str(value or "unknown").strip().lower()
    chars: list[str] = []
    for char in text:
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", ".", "/", "@"}:
            chars.append("-" if char in {"/", "@"} else char)
        else:
            chars.append("-")
    slug = "".join(chars).strip("-._")
    return slug or "unknown"


def _short_id(value: str | None = None) -> str:
    """짧은 안정 id 조각을 만든다."""
    import hashlib

    seed = value or _now()
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


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
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_any(path: Path) -> dict[str, Any]:
    """YAML 또는 JSON artifact를 안전하게 읽는다."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        if Path(path).suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("pack proof artifact load failed: %s (%s)", path, exc)
        return {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("pack proof artifact ignored: top level is not mapping: %s", path)
        return {}
    return payload


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


def _rate_text(value: Any) -> str:
    """비율 값을 사람이 읽기 좋은 문자열로 만든다."""
    if value is None:
        return "unknown"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(value)


def _number_or_none(value: Any) -> float | int | str | None:
    """YAML에서 복원된 metric 값을 proof metric 타입으로 보정한다."""
    if value is None:
        return None
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def default_pack_proof_dir(project_root: Path) -> Path:
    """pack proof card 저장 디렉터리를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "packs" / "proof"


def default_pack_proof_path(project_root: Path, card: "PackProofCard") -> Path:
    """YAML proof card 기본 저장 경로를 반환한다."""
    return default_pack_proof_dir(project_root) / f"proof_{_slug(card.pack_id)}_{_stamp()}_{_short_id(card.proof_id)}.yaml"


def default_pack_proof_markdown_path(project_root: Path, card: "PackProofCard") -> Path:
    """Markdown proof card 기본 저장 경로를 반환한다."""
    return default_pack_proof_dir(project_root) / f"proof_{_slug(card.pack_id)}_{_stamp()}_{_short_id(card.proof_id)}.md"


def default_pack_proof_latest_path(project_root: Path) -> Path:
    """latest proof pointer 경로를 반환한다."""
    return default_pack_proof_dir(project_root) / "latest.yaml"


@dataclass
class PackProofMetric:
    """proof card에 표시할 단일 metric."""

    key: str
    value: float | int | str | None
    unit: str | None
    summary: str
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackProofClaim:
    """pack에 대해 말할 수 있는 증거 기반 claim."""

    claim_id: str
    title: str
    verdict: str
    summary: str
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        return asdict(self)


@dataclass
class PackProofCard:
    """pack usage/outcome을 사람이 읽는 성과 카드로 요약한다."""

    schema_version: str
    proof_id: str
    generated_at: str
    pack_ref: str
    pack_id: str
    pack_name: str | None
    pack_kind: str | None
    namespace: str | None
    version: str | None
    source_kind: str | None
    source_ref: str | None
    active: bool
    installed: bool
    reputation_verdict: str
    maturity_hint: str | None
    key_metrics: list[PackProofMetric]
    claims: list[PackProofClaim]
    best_observed_lane: str | None
    best_observed_workset: str | None
    used_count: int
    outcome_linked_count: int
    why_useful: list[str] = field(default_factory=list)
    where_weak: list[str] = field(default_factory=list)
    known_limits: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict로 변환한다."""
        payload = asdict(self)
        payload["key_metrics"] = [metric.to_dict() for metric in self.key_metrics]
        payload["claims"] = [claim.to_dict() for claim in self.claims]
        return payload


class PackProofBuilder:
    """설치된 pack의 local proof card를 만든다."""

    def build(self, project_root: Path, pack_ref: str | None = None) -> PackProofCard:
        """pack usage/outcome/release 정보를 모아 proof card를 만든다."""
        root = Path(project_root).resolve()
        target_ref = self._select_pack_ref(root, pack_ref)
        record = _find_installed_record(root, target_ref)
        active_context = current_active_pack(root)
        active = bool(active_context and _pack_ref_matches(target_ref, active_context.pack_id, active_context.namespace, active_context.version))

        pack_id = record.pack_id if record else _plain_pack_id(target_ref)
        summary = PackUsageSummaryBuilder().build(root, pack_id)
        counts = summary.counts
        rates = summary.rates
        medians = summary.medians

        used_count = int(counts.get("used_count", 0) or 0)
        outcome_linked_count = int(counts.get("outcome_linked_count", 0) or 0)
        verdict = _reputation_verdict(summary)
        maturity_hint = _maturity_hint(verdict)
        best_lane = _best_lane(record, active_context, summary)
        best_workset = _best_workset(record, active_context)
        retro_summary = _latest_retro_summary(root, pack_id)
        improvement_queue = _latest_improvement_queue(root, pack_id)
        derivative_plan = _latest_derivative_plan(root, pack_id)
        vnext_workbench = _latest_vnext_workbench(root, pack_id)
        release_candidate = _latest_release_candidate(root, pack_id)
        local_release = _latest_local_release(root, pack_id)
        rollout_plan = _latest_rollout_plan(root, pack_id)
        known_limits = _known_limits(record, summary, verdict, retro_summary)
        source_refs = _source_refs(root, record, active_context, summary, pack_id)
        if retro_summary is not None:
            source_refs["retrospective_summary_ref"] = f".cambrian/packs/retrospectives/summaries/{retro_summary.summary_id}"
        if improvement_queue is not None:
            source_refs["improvement_queue_ref"] = ".cambrian/packs/improvements/queue.yaml"
        if derivative_plan is not None:
            source_refs["derivative_plan_ref"] = f".cambrian/packs/derivatives/plans/{derivative_plan.plan_id}"
        if vnext_workbench is not None:
            source_refs["vnext_workbench_ref"] = f".cambrian/packs/vnext/workbenches/{vnext_workbench.workbench_id}"
        if release_candidate is not None:
            source_refs["release_candidate_ref"] = getattr(release_candidate, "rc_id", None)
        if local_release is not None:
            source_refs["local_release_ref"] = getattr(local_release, "release_id", None)
        if rollout_plan is not None:
            source_refs["rollout_ref"] = getattr(rollout_plan, "rollout_id", None)

        card = PackProofCard(
            schema_version=SCHEMA_VERSION,
            proof_id=f"pack-proof-{_slug(pack_id)}-{_stamp()}-{_short_id(target_ref)}",
            generated_at=_now(),
            pack_ref=_canonical_pack_ref(record, target_ref),
            pack_id=pack_id,
            pack_name=record.pack_name if record else summary.pack_name,
            pack_kind=record.pack_kind if record else None,
            namespace=record.namespace if record else summary.namespace,
            version=record.version if record else summary.version,
            source_kind=record.source_kind if record else None,
            source_ref=record.source_ref if record else None,
            active=active,
            installed=record is not None and record.status != "uninstalled",
            reputation_verdict=verdict,
            maturity_hint=maturity_hint,
            key_metrics=_key_metrics(summary),
            claims=_claims(summary, best_lane),
            best_observed_lane=best_lane,
            best_observed_workset=best_workset,
            used_count=used_count,
            outcome_linked_count=outcome_linked_count,
            why_useful=_why_useful(verdict, summary, best_lane, best_workset, retro_summary),
            where_weak=_where_weak(verdict, summary, retro_summary, improvement_queue, derivative_plan, vnext_workbench, release_candidate, local_release, rollout_plan),
            known_limits=known_limits,
            next_actions=_next_actions(pack_id, best_workset, improvement_queue, derivative_plan, vnext_workbench, release_candidate, local_release, rollout_plan),
            source_refs=source_refs,
            warnings=_proof_warnings(record, summary, verdict),
            errors=[],
        )
        return card

    def _select_pack_ref(self, root: Path, pack_ref: str | None) -> str:
        """명시 ref, active pack, 최근 usage 순으로 proof 대상을 고른다."""
        if pack_ref:
            return str(pack_ref)
        active = current_active_pack(root)
        if active is not None:
            return active.pack_ref or active.pack_id
        events = PackUsageEventStore().list_events(default_usage_events_dir(root))
        if events:
            return events[0].pack_ref or events[0].pack_id
        raise ValueError("pack proof target not found. Activate or use a pack first, or pass a pack id.")


class PackProofStore:
    """pack proof card 저장소."""

    def save_yaml(self, card: PackProofCard, path: Path) -> Path:
        """YAML proof card를 저장한다."""
        saved = _save_yaml(Path(path).resolve(), card.to_dict())
        latest = default_pack_proof_latest_path(saved.parents[3] if ".cambrian" in saved.parts else Path.cwd())
        try:
            _save_yaml(latest, card.to_dict())
        except Exception as exc:  # noqa: BLE001 - latest pointer 실패는 proof 생성 실패가 아니다.
            logger.warning("pack proof latest pointer save failed: %s", exc)
        return saved

    def save_markdown(self, card: PackProofCard, path: Path) -> Path:
        """Markdown proof card를 저장한다."""
        _atomic_write_text(Path(path).resolve(), render_pack_proof_markdown(card))
        return Path(path).resolve()

    def load_yaml(self, path: Path) -> PackProofCard:
        """YAML proof card를 로드한다."""
        return _card_from_dict(_load_any(Path(path).resolve()))


def save_pack_proof_card(project_root: Path, card: PackProofCard, format_kind: str = "both") -> dict[str, str]:
    """proof card를 요청한 형식으로 저장하고 상대 경로를 반환한다."""
    root = Path(project_root).resolve()
    store = PackProofStore()
    saved: dict[str, str] = {}
    kind = str(format_kind or "both").lower()
    if kind in {"yaml", "both"}:
        yaml_path = store.save_yaml(card, default_pack_proof_path(root, card))
        latest = default_pack_proof_latest_path(root)
        try:
            _save_yaml(latest, card.to_dict())
        except Exception as exc:  # noqa: BLE001 - latest pointer 실패는 저장 실패가 아니다.
            logger.warning("pack proof latest pointer save failed: %s", exc)
        saved["yaml"] = _relative(yaml_path, root)
    if kind in {"md", "markdown", "both"}:
        md_path = store.save_markdown(card, default_pack_proof_markdown_path(root, card))
        saved["md"] = _relative(md_path, root)
    return saved


def resolve_pack_proof_path(project_root: Path, proof_ref: str) -> Path:
    """proof id 또는 path를 YAML proof card 경로로 해석한다."""
    root = Path(project_root).resolve()
    raw = str(proof_ref or "").strip()
    if raw in {"latest", "latest.yaml"}:
        latest = default_pack_proof_latest_path(root)
        if latest.exists():
            return latest
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.exists():
        if candidate.suffix.lower() == ".md":
            yaml_peer = candidate.with_suffix(".yaml")
            if yaml_peer.exists():
                return yaml_peer.resolve()
        return candidate.resolve()
    proof_dir = default_pack_proof_dir(root)
    for path in sorted(proof_dir.glob("proof_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _load_any(path)
        if raw in {str(payload.get("proof_id") or ""), str(payload.get("pack_id") or ""), path.stem}:
            return path
    raise FileNotFoundError(f"pack proof card not found: {proof_ref}")


def latest_pack_proof_card(project_root: Path, pack_ref: str | None = None) -> PackProofCard | None:
    """특정 pack 또는 전체 최신 proof card를 반환한다."""
    root = Path(project_root).resolve()
    proof_dir = default_pack_proof_dir(root)
    if not proof_dir.exists():
        return None
    paths = sorted(proof_dir.glob("proof_*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            card = PackProofStore().load_yaml(path)
        except Exception as exc:  # noqa: BLE001 - 깨진 proof artifact 하나 때문에 조회를 막지 않는다.
            logger.warning("pack proof card load skipped: %s (%s)", path, exc)
            continue
        if pack_ref is None or _card_matches(card, pack_ref):
            return card
    latest = default_pack_proof_latest_path(root)
    if pack_ref is None and latest.exists():
        try:
            return PackProofStore().load_yaml(latest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("latest pack proof load failed: %s", exc)
    return None


def render_pack_proof_card(card: PackProofCard) -> str:
    """proof card를 콘솔 출력용으로 렌더링한다."""
    metrics = {metric.key: metric.value for metric in card.key_metrics}
    lines = [
        "Pack Proof Card",
        "==================================================",
        "",
        "Pack:",
        f"  {card.pack_id}",
        "",
        "Verdict:",
        f"  {card.reputation_verdict}",
        "",
        "Usage:",
        f"  used: {card.used_count}",
        f"  outcome-linked: {card.outcome_linked_count}",
        "",
        "Outcome:",
        f"  validated proposal rate : {_rate_text(metrics.get('validated_proposal_rate'))}",
        f"  adoption rate           : {_rate_text(metrics.get('adoption_rate'))}",
        f"  regression-free apply   : {_rate_text(metrics.get('regression_free_apply_rate'))}",
        f"  human intervention rate : {_rate_text(metrics.get('human_intervention_rate'))}",
        f"  validation autonomy     : {_rate_text(metrics.get('validation_autonomy_rate'))}",
        "",
        "Median time to validated proposal:",
        f"  {_seconds_text(metrics.get('median_time_to_validated_proposal'))}",
    ]
    if card.best_observed_lane:
        lines.extend(["", "Best observed lane:", f"  {card.best_observed_lane}"])
    if card.best_observed_workset:
        lines.extend(["", "Best observed workset:", f"  {card.best_observed_workset}"])
    if card.why_useful:
        lines.extend(["", "Why useful:"])
        lines.extend([f"  - {item}" for item in card.why_useful])
    if card.where_weak:
        lines.extend(["", "Where weak:"])
        lines.extend([f"  - {item}" for item in card.where_weak])
    if card.known_limits:
        lines.extend(["", "Known limits:"])
        lines.extend([f"  - {item}" for item in card.known_limits])
    if card.claims:
        lines.extend(["", "Claims:"])
        lines.extend([f"  - {claim.title}: {claim.verdict}" for claim in card.claims])
    if card.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in card.next_actions])
    if card.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in card.warnings])
    return "\n".join(lines)


def render_pack_proof_markdown(card: PackProofCard) -> str:
    """공유 가능한 Markdown proof card를 만든다."""
    metrics = {metric.key: metric.value for metric in card.key_metrics}
    lines = [
        "# Pack Proof Card",
        "",
        "## Pack",
        card.pack_id,
        "",
        "## Verdict",
        card.reputation_verdict,
        "",
        "## Usage",
        f"- used: {card.used_count}",
        f"- outcome-linked: {card.outcome_linked_count}",
        "",
        "## Key Metrics",
        f"- validated proposal rate: {_rate_text(metrics.get('validated_proposal_rate'))}",
        f"- human intervention rate: {_rate_text(metrics.get('human_intervention_rate'))}",
        f"- validation autonomy rate: {_rate_text(metrics.get('validation_autonomy_rate'))}",
        f"- adoption rate: {_rate_text(metrics.get('adoption_rate'))}",
        f"- regression-free apply rate: {_rate_text(metrics.get('regression_free_apply_rate'))}",
        f"- median time to validated proposal: {_seconds_text(metrics.get('median_time_to_validated_proposal'))}",
        "",
        "## Why Useful",
    ]
    lines.extend([f"- {item}" for item in card.why_useful] or ["- 확인된 positive outcome evidence가 아직 부족합니다."])
    lines.extend(["", "## Where Weak"])
    lines.extend([f"- {item}" for item in card.where_weak] or ["- 현재 기록된 약점은 없습니다. 표본이 작으면 보수적으로 해석해야 합니다."])
    lines.extend(["", "## Known Limits"])
    lines.extend([f"- {item}" for item in card.known_limits] or ["- 로컬 evidence만 사용합니다. public proof가 아닙니다."])
    lines.extend(["", "## Evidence Sources"])
    for key, value in card.source_refs.items():
        if isinstance(value, list):
            if value:
                lines.append(f"- {key}: {', '.join(str(item) for item in value[:5])}")
        elif value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def render_pack_proof_compact(card: PackProofCard | None) -> str:
    """status/pack show에 붙일 compact proof summary를 만든다."""
    if card is None:
        return ""
    metrics = {metric.key: metric.value for metric in card.key_metrics}
    return "\n".join(
        [
            "",
            "Local proof:",
            f"  verdict    : {card.reputation_verdict}",
            f"  validated  : {_rate_text(metrics.get('validated_proposal_rate'))}",
            f"  intervention: {_rate_text(metrics.get('human_intervention_rate'))}",
        ]
    )


def _find_installed_record(root: Path, pack_ref: str) -> InstalledPackRecord | None:
    store = InstalledPackStore()
    index = store.load(default_installed_packs_path(root))
    for candidate in _pack_ref_candidates(pack_ref):
        try:
            return store.find(index, candidate)
        except KeyError:
            continue
    return None


def _plain_pack_id(pack_ref: str) -> str:
    raw = str(pack_ref or "").strip()
    raw = raw.split("@", 1)[0]
    if "/" in raw:
        raw = raw.rsplit("/", 1)[1]
    return raw or "unknown"


def _pack_ref_candidates(pack_ref: str) -> list[str]:
    raw = str(pack_ref or "").strip()
    no_version = raw.split("@", 1)[0]
    plain = _plain_pack_id(raw)
    return _dedupe([raw, no_version, plain])


def _canonical_pack_ref(record: InstalledPackRecord | None, fallback: str) -> str:
    if record is None:
        return fallback
    prefix = f"{record.namespace}/" if record.namespace else ""
    suffix = f"@{record.version}" if record.version else ""
    return f"{prefix}{record.pack_id}{suffix}"


def _pack_ref_matches(raw_ref: str, pack_id: str | None, namespace: str | None, version: str | None) -> bool:
    candidates = {
        str(pack_id or ""),
        f"{namespace}/{pack_id}" if namespace and pack_id else "",
        f"{namespace}/{pack_id}@{version}" if namespace and pack_id and version else "",
        f"{pack_id}@{version}" if pack_id and version else "",
    }
    return any(candidate and candidate in _pack_ref_candidates(raw_ref) for candidate in candidates) or _plain_pack_id(raw_ref) == pack_id


def _card_matches(card: PackProofCard, pack_ref: str) -> bool:
    return _plain_pack_id(pack_ref) == card.pack_id or pack_ref in {card.pack_id, card.pack_ref}


def _reputation_verdict(summary: PackUsageSummary) -> str:
    counts = summary.counts
    rates = summary.rates
    used = int(counts.get("used_count", 0) or 0)
    linked = int(counts.get("outcome_linked_count", 0) or 0)
    validated_count = int(counts.get("validated_proposal_count", 0) or 0)
    validated_rate = _float_or_none(rates.get("validated_proposal_rate"))
    human_rate = _float_or_none(rates.get("human_intervention_rate"))
    autonomy_rate = _float_or_none(rates.get("validation_autonomy_rate"))
    adoption_rate = _float_or_none(rates.get("adoption_rate"))
    regression_rate = _float_or_none(rates.get("regression_free_apply_rate"))

    if used == 0 or linked == 0:
        return "insufficient_data"
    if linked >= 3 and (validated_rate is not None and validated_rate < 0.2) and (human_rate is not None and human_rate >= 0.75):
        return "regressed"
    if (
        linked >= 5
        and validated_rate is not None
        and validated_rate >= 0.7
        and autonomy_rate is not None
        and autonomy_rate >= 0.5
        and (human_rate is None or human_rate <= 0.35)
        and ((adoption_rate is not None and adoption_rate > 0) or (regression_rate is not None and regression_rate > 0))
    ):
        return "strong"
    if linked >= 3 and validated_rate is not None and validated_rate >= 0.4 and (human_rate is None or human_rate <= 0.7):
        return "useful"
    if validated_count > 0:
        return "promising"
    return "unproven"


def _maturity_hint(verdict: str) -> str:
    mapping = {
        "strong": "recommended",
        "useful": "verified",
        "promising": "candidate",
        "unproven": "candidate",
        "insufficient_data": "candidate",
        "regressed": "retired",
    }
    return mapping.get(verdict, "candidate")


def _key_metrics(summary: PackUsageSummary) -> list[PackProofMetric]:
    counts = summary.counts
    rates = summary.rates
    medians = summary.medians
    specs = [
        ("used_count", counts.get("used_count"), "count", "active pack이 work surface에서 사용된 횟수"),
        ("outcome_linked_count", counts.get("outcome_linked_count"), "count", "결과 artifact와 연결된 사용 횟수"),
        ("applied_count", counts.get("applied_count"), "count", "pack job confirm apply 횟수"),
        ("accepted_count", counts.get("accepted_count"), "count", "pack job accepted decision 횟수"),
        ("rejected_count", counts.get("rejected_count"), "count", "pack job rejected decision 횟수"),
        ("validated_proposal_rate", rates.get("validated_proposal_rate"), "rate", "validated proposal까지 간 비율"),
        ("adoption_rate", rates.get("adoption_rate"), "rate", "validated proposal 중 adoption 성공 비율"),
        ("regression_free_apply_rate", rates.get("regression_free_apply_rate"), "rate", "adopted outcome 중 regression-free apply 비율"),
        ("human_intervention_rate", rates.get("human_intervention_rate"), "rate", "사람 개입이 필요했던 비율"),
        ("validation_autonomy_rate", rates.get("validation_autonomy_rate"), "rate", "검증까지 자율적으로 간 비율"),
        ("outcome_coverage_rate", rates.get("outcome_coverage_rate"), "rate", "usage 중 outcome attribution이 가능한 비율"),
        (
            "median_time_to_validated_proposal",
            medians.get("time_to_validated_proposal_seconds"),
            "seconds",
            "validated proposal까지 걸린 중앙 시간",
        ),
    ]
    return [
        PackProofMetric(
            key=key,
            value=_number_or_none(value),
            unit=unit,
            summary=summary_text,
            warning="insufficient local evidence" if value is None else None,
        )
        for key, value, unit, summary_text in specs
    ]


def _claims(summary: PackUsageSummary, best_lane: str | None) -> list[PackProofClaim]:
    counts = summary.counts
    rates = summary.rates
    refs = [ref for ref in summary.source_refs if ref]
    validated_count = int(counts.get("validated_proposal_count", 0) or 0)
    used = int(counts.get("used_count", 0) or 0)
    linked = int(counts.get("outcome_linked_count", 0) or 0)
    human_rate = _float_or_none(rates.get("human_intervention_rate"))
    autonomy_rate = _float_or_none(rates.get("validation_autonomy_rate"))

    return [
        PackProofClaim(
            claim_id="pack_reaches_validated_proposal",
            title="Pack reaches validated proposal",
            verdict="proven" if validated_count >= 3 else "promising" if validated_count > 0 else "insufficient_data",
            summary=f"{validated_count} validated proposal outcomes were attributed to this pack.",
            evidence_refs=refs,
        ),
        PackProofClaim(
            claim_id="pack_reduces_manual_work",
            title="Pack reduces manual work",
            verdict="proven" if human_rate is not None and linked >= 3 and human_rate <= 0.35 else "weak" if human_rate is not None else "insufficient_data",
            summary=f"human intervention rate is {_rate_text(human_rate)}.",
            evidence_refs=refs,
        ),
        PackProofClaim(
            claim_id="pack_supports_autonomy",
            title="Pack supports validation autonomy",
            verdict="proven" if autonomy_rate is not None and linked >= 3 and autonomy_rate >= 0.5 else "promising" if autonomy_rate else "insufficient_data",
            summary=f"validation autonomy rate is {_rate_text(autonomy_rate)}.",
            evidence_refs=refs,
        ),
        PackProofClaim(
            claim_id="pack_is_lane_specific",
            title="Pack evidence is lane-specific",
            verdict="promising" if best_lane and used > 0 else "insufficient_data",
            summary=f"best observed lane: {best_lane or 'unknown'}.",
            evidence_refs=refs,
        ),
        PackProofClaim(
            claim_id="pack_needs_more_evidence",
            title="Pack needs more evidence",
            verdict="proven" if linked < 3 else "weak",
            summary=f"{linked} outcome-linked uses out of {used} uses.",
            evidence_refs=refs,
        ),
    ]


def _why_useful(verdict: str, summary: PackUsageSummary, best_lane: str | None, best_workset: str | None, retro_summary: Any | None = None) -> list[str]:
    counts = summary.counts
    rates = summary.rates
    lines: list[str] = []
    validated = int(counts.get("validated_proposal_count", 0) or 0)
    linked = int(counts.get("outcome_linked_count", 0) or 0)
    if validated:
        lines.append(f"reached validated proposal in {validated} of {linked} outcome-linked uses")
    if _float_or_none(rates.get("validation_autonomy_rate")):
        lines.append(f"validation autonomy is {_rate_text(rates.get('validation_autonomy_rate'))}")
    if best_lane:
        lines.append(f"strongest local evidence is in {best_lane}")
    if best_workset:
        lines.append(f"best observed workset is {best_workset}")
    if retro_summary is not None and getattr(retro_summary, "outcome_counts", {}).get("worked_well", 0):
        lines.append(f"retrospectives marked {retro_summary.outcome_counts.get('worked_well', 0)} job(s) as worked_well")
    if not lines and verdict in {"insufficient_data", "unproven"}:
        lines.append("local usage/outcome evidence is still too sparse to claim usefulness")
    return lines


def _where_weak(
    verdict: str,
    summary: PackUsageSummary,
    retro_summary: Any | None = None,
    improvement_queue: Any | None = None,
    derivative_plan: Any | None = None,
    vnext_workbench: Any | None = None,
    release_candidate: Any | None = None,
    local_release: Any | None = None,
    rollout_plan: Any | None = None,
) -> list[str]:
    counts = summary.counts
    rates = summary.rates
    lines: list[str] = []
    used = int(counts.get("used_count", 0) or 0)
    linked = int(counts.get("outcome_linked_count", 0) or 0)
    if used == 0:
        lines.append("pack has not been used in local work yet")
    if linked == 0:
        lines.append("no usage event is linked to a local outcome source yet")
    if linked and linked < 3:
        lines.append("sample size is still small")
    if rates.get("adoption_rate") is None:
        lines.append("adoption evidence is not available yet")
    if verdict == "regressed":
        lines.append("recent attributed outcomes show high intervention with low validation")
    if retro_summary is not None:
        for signal in getattr(retro_summary, "top_negative_signals", [])[:2]:
            lines.append(f"retrospective top issue: {signal}")
        for suggestion in getattr(retro_summary, "top_suggestions", [])[:1]:
            lines.append(f"retrospective suggestion: {suggestion.kind}")
    top_improvement = _top_open_improvement(improvement_queue)
    if top_improvement is not None:
        lines.append(f"top improvement: {top_improvement.kind}")
    if derivative_plan is not None:
        unresolved = int(getattr(derivative_plan, "unresolved_change_count", 0) or 0)
        lines.append(f"derivative plan available: {getattr(derivative_plan, 'suggested_target_pack_id', 'vNext')}")
        if unresolved:
            lines.append(f"derivative unresolved changes: {unresolved}")
    if vnext_workbench is not None:
        open_required = int(getattr(vnext_workbench, "open_required_count", 0) or 0)
        if open_required:
            lines.append(f"vNext required workorders open: {open_required}")
    if release_candidate is not None:
        lines.append(f"release candidate available: {getattr(release_candidate, 'target_pack_id', 'vNext')}")
        if not bool(getattr(release_candidate, "safe_to_release_local", False)):
            lines.append("release candidate is not safe for local release yet")
    if local_release is not None and getattr(local_release, "status", None) == "released":
        lines.append(f"local release recorded: {getattr(local_release, 'target_pack_id', 'vNext')}")
    if rollout_plan is not None:
        lines.append(f"rollout available: {getattr(rollout_plan, 'new_pack_id', 'vNext')}")
    return _dedupe(lines)


def _known_limits(record: InstalledPackRecord | None, summary: PackUsageSummary, verdict: str, retro_summary: Any | None = None) -> list[str]:
    limits: list[str] = []
    if record is not None:
        limits.extend(record.warnings)
    limits.extend(summary.warnings)
    if verdict in {"insufficient_data", "unproven"}:
        limits.append("local proof is not enough to claim this pack is proven")
    if verdict == "regressed":
        limits.append("current local evidence suggests caution before recommendation")
    if retro_summary is not None:
        limits.extend(getattr(retro_summary, "known_limits", [])[:5])
    limits.append("proof card is local-only and is not uploaded automatically")
    return _dedupe(limits)


def _proof_warnings(record: InstalledPackRecord | None, summary: PackUsageSummary, verdict: str) -> list[str]:
    warnings: list[str] = []
    if record is None:
        warnings.append("pack is not installed locally; proof is based on available usage artifacts only")
    if verdict in {"insufficient_data", "unproven"}:
        warnings.append("do not present this pack as proof-backed yet")
    warnings.extend(summary.warnings)
    return _dedupe(warnings)


def _latest_retro_summary(root: Path, pack_id: str) -> Any | None:
    try:
        from engine.project_pack_retrospective import latest_pack_retro_summary

        return latest_pack_retro_summary(root, pack_id)
    except Exception as exc:  # noqa: BLE001 - retrospective는 proof card를 막지 않는다.
        logger.warning("pack retrospective summary lookup failed during proof build: %s", exc)
        return None


def _latest_improvement_queue(root: Path, pack_id: str) -> Any | None:
    try:
        from engine.project_pack_improvements import latest_pack_improvement_queue

        return latest_pack_improvement_queue(root, pack_id)
    except Exception as exc:  # noqa: BLE001 - improvement queue는 proof card를 막지 않는다.
        logger.warning("pack improvement queue lookup failed during proof build: %s", exc)
        return None


def _latest_derivative_plan(root: Path, pack_id: str) -> Any | None:
    try:
        from engine.project_pack_derivatives import latest_pack_derivative_plan

        return latest_pack_derivative_plan(root, pack_id)
    except Exception as exc:  # noqa: BLE001 - derivative plan은 proof card를 막지 않는다.
        logger.warning("pack derivative plan lookup failed during proof build: %s", exc)
        return None


def _latest_vnext_workbench(root: Path, pack_id: str) -> Any | None:
    try:
        from engine.project_pack_vnext_workbench import latest_pack_vnext_workbench

        return latest_pack_vnext_workbench(root, pack_id)
    except Exception as exc:  # noqa: BLE001 - vNext workbench는 proof card 생성을 막지 않는다.
        logger.warning("pack vNext workbench lookup failed during proof build: %s", exc)
        return None


def _latest_release_candidate(root: Path, pack_id: str) -> Any | None:
    try:
        from engine.project_pack_release_candidate import latest_pack_rc

        return latest_pack_rc(root, pack_id)
    except Exception as exc:  # noqa: BLE001 - RC 조회는 proof 생성을 막지 않는다.
        logger.warning("pack release candidate lookup failed during proof build: %s", exc)
        return None


def _latest_local_release(root: Path, pack_id: str) -> Any | None:
    try:
        from engine.project_pack_release_candidate import latest_pack_local_release

        return latest_pack_local_release(root, pack_id)
    except Exception as exc:  # noqa: BLE001 - local release 조회는 proof 생성을 막지 않는다.
        logger.warning("pack local release lookup failed during proof build: %s", exc)
        return None


def _latest_rollout_plan(root: Path, pack_id: str) -> Any | None:
    try:
        from engine.project_pack_rollout import latest_pack_rollout

        return latest_pack_rollout(root, pack_id)
    except Exception as exc:  # noqa: BLE001 - rollout 조회는 proof 생성을 막지 않는다.
        logger.warning("pack rollout lookup failed during proof build: %s", exc)
        return None


def _next_actions(
    pack_id: str,
    workset: str | None,
    improvement_queue: Any | None = None,
    derivative_plan: Any | None = None,
    vnext_workbench: Any | None = None,
    release_candidate: Any | None = None,
    local_release: Any | None = None,
    rollout_plan: Any | None = None,
) -> list[str]:
    actions = [
        f"cambrian pack outcomes {pack_id}",
    ]
    top_improvement = _top_open_improvement(improvement_queue)
    if top_improvement is not None:
        actions.append(f"cambrian pack improvement-show {top_improvement.item_id}")
    if derivative_plan is not None:
        actions.append(f"cambrian pack derivative-show {getattr(derivative_plan, 'plan_id', 'latest')}")
    if vnext_workbench is not None and int(getattr(vnext_workbench, "open_required_count", 0) or 0):
        actions.append(f"cambrian pack workorders {pack_id}")
    if release_candidate is not None and bool(getattr(release_candidate, "safe_to_release_local", False)):
        actions.append(f"cambrian pack release-local {getattr(release_candidate, 'rc_id', 'latest')}")
    if local_release is not None and getattr(local_release, "status", None) == "released":
        actions.append(f"cambrian install pack {getattr(local_release, 'target_pack_id', pack_id)}")
    if rollout_plan is not None:
        actions.append(f"cambrian pack rollout-show {getattr(rollout_plan, 'rollout_id', 'latest')}")
    if workset:
        actions.append(f"cambrian benchmark proof {workset}")
    actions.append(f"cambrian pack usage {pack_id}")
    return actions


def _top_open_improvement(improvement_queue: Any | None) -> Any | None:
    if improvement_queue is None:
        return None
    items = [item for item in getattr(improvement_queue, "items", []) if getattr(item, "status", None) == "open"]
    if not items:
        return None
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        items,
        key=lambda item: (
            order.get(getattr(item, "priority", "low"), 9),
            -float(getattr(item, "confidence", 0.0) or 0.0),
            getattr(item, "kind", ""),
        ),
    )[0]


def _best_lane(record: InstalledPackRecord | None, active_context: Any, summary: PackUsageSummary) -> str | None:
    if active_context is not None and getattr(active_context, "lane_label", None):
        return str(active_context.lane_label)
    if active_context is not None and getattr(active_context, "lane_id", None):
        return str(active_context.lane_id)
    lane = _as_dict((record.installed_artifacts if record else {}).get("lane"))
    return str(lane.get("label") or lane.get("lane_id")) if lane else summary.namespace


def _best_workset(record: InstalledPackRecord | None, active_context: Any) -> str | None:
    if active_context is not None and getattr(active_context, "default_workset", None):
        return str(active_context.default_workset)
    artifacts = record.installed_artifacts if record else {}
    benchmarks = artifacts.get("benchmarks")
    if isinstance(benchmarks, list) and benchmarks:
        return str(benchmarks[0])
    return None


def _source_refs(root: Path, record: InstalledPackRecord | None, active_context: Any, summary: PackUsageSummary, pack_id: str) -> dict[str, Any]:
    refs: dict[str, Any] = {
        "installed_pack_ref": f".cambrian/install/installed_packs.yaml#{pack_id}" if record else None,
        "active_pack_ref": ".cambrian/install/active_pack.yaml" if active_context is not None else None,
        "usage_event_refs": [ref for ref in summary.source_refs if ref],
        "usage_summary_ref": None,
        "release_ref": _latest_release_ref(root, pack_id),
        "benchmark_refs": [],
    }
    return refs


def _latest_release_ref(root: Path, pack_id: str) -> str | None:
    release_dir = root / ".cambrian" / "packs" / "releases"
    if not release_dir.exists():
        return None
    for path in sorted(release_dir.glob("*.yaml"), key=lambda item: item.stat().st_mtime, reverse=True):
        payload = _load_any(path)
        if str(payload.get("pack_id") or "") == pack_id:
            return _relative(path, root)
    return None


def _seconds_text(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return str(value)
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.1f}m"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_from_dict(payload: dict[str, Any]) -> PackProofMetric:
    return PackProofMetric(
        key=str(payload.get("key") or ""),
        value=_number_or_none(payload.get("value")),
        unit=str(payload.get("unit")) if payload.get("unit") is not None else None,
        summary=str(payload.get("summary") or ""),
        warning=str(payload.get("warning")) if payload.get("warning") is not None else None,
    )


def _claim_from_dict(payload: dict[str, Any]) -> PackProofClaim:
    return PackProofClaim(
        claim_id=str(payload.get("claim_id") or ""),
        title=str(payload.get("title") or ""),
        verdict=str(payload.get("verdict") or "insufficient_data"),
        summary=str(payload.get("summary") or ""),
        evidence_refs=_as_list(payload.get("evidence_refs")),
        warnings=_as_list(payload.get("warnings")),
    )


def _card_from_dict(payload: dict[str, Any]) -> PackProofCard:
    metrics = [_metric_from_dict(item) for item in payload.get("key_metrics", []) if isinstance(item, dict)]
    claims = [_claim_from_dict(item) for item in payload.get("claims", []) if isinstance(item, dict)]
    verdict = str(payload.get("reputation_verdict") or "insufficient_data")
    if verdict not in REPUTATION_VERDICTS:
        verdict = "insufficient_data"
    return PackProofCard(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        proof_id=str(payload.get("proof_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        pack_ref=str(payload.get("pack_ref") or payload.get("pack_id") or ""),
        pack_id=str(payload.get("pack_id") or "unknown"),
        pack_name=str(payload.get("pack_name")) if payload.get("pack_name") is not None else None,
        pack_kind=str(payload.get("pack_kind")) if payload.get("pack_kind") is not None else None,
        namespace=str(payload.get("namespace")) if payload.get("namespace") is not None else None,
        version=str(payload.get("version")) if payload.get("version") is not None else None,
        source_kind=str(payload.get("source_kind")) if payload.get("source_kind") is not None else None,
        source_ref=str(payload.get("source_ref")) if payload.get("source_ref") is not None else None,
        active=bool(payload.get("active")),
        installed=bool(payload.get("installed")),
        reputation_verdict=verdict,
        maturity_hint=str(payload.get("maturity_hint")) if payload.get("maturity_hint") is not None else None,
        key_metrics=metrics,
        claims=claims,
        best_observed_lane=str(payload.get("best_observed_lane")) if payload.get("best_observed_lane") is not None else None,
        best_observed_workset=str(payload.get("best_observed_workset")) if payload.get("best_observed_workset") is not None else None,
        used_count=int(payload.get("used_count") or 0),
        outcome_linked_count=int(payload.get("outcome_linked_count") or 0),
        why_useful=_as_list(payload.get("why_useful")),
        where_weak=_as_list(payload.get("where_weak")),
        known_limits=_as_list(payload.get("known_limits")),
        next_actions=_as_list(payload.get("next_actions")),
        source_refs=_as_dict(payload.get("source_refs")),
        warnings=_as_list(payload.get("warnings")),
        errors=_as_list(payload.get("errors")),
    )
