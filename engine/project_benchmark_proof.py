"""Benchmark 증거를 한 장짜리 proof pack으로 묶는 모듈."""

from __future__ import annotations

import json
import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_benchmarks import (
    BenchmarkReport,
    BenchmarkStore,
    default_benchmark_dir,
    default_reports_dir,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
PROOF_METRICS = [
    "validated_proposal_rate",
    "adoption_rate",
    "regression_free_apply_rate",
    "median_time_to_validated_proposal",
    "human_intervention_rate",
    "validation_autonomy_rate",
    "reuse_lift",
    "repeat_task_improvement_rate",
]


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 돌려준다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓸 UTC timestamp를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 충돌 방지 id를 만든다."""
    return secrets.token_hex(2)


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


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML/JSON artifact를 안전하게 읽는다."""
    if not Path(path).exists():
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
        if Path(path).suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("benchmark proof source load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """프로젝트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _slug(value: str) -> str:
    """파일명에 안전한 slug를 만든다."""
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "proof"))
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "proof"


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


def _score(value: Any) -> float | None:
    """숫자형 metric을 float로 정규화한다."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_delta(left: Any, right: Any) -> float | None:
    """두 metric의 차이를 계산한다."""
    left_value = _score(left)
    right_value = _score(right)
    if left_value is None or right_value is None:
        return None
    return round(left_value - right_value, 4)


def _format_rate(value: Any) -> str:
    """0~1 rate를 사람이 읽기 좋은 퍼센트로 표시한다."""
    number = _score(value)
    if number is None:
        return "n/a"
    return f"{number * 100:.0f}%"


def _format_points(value: Any) -> str:
    """0~1 point delta를 pt 표현으로 바꾼다."""
    number = _score(value)
    if number is None:
        return "n/a"
    return f"{number * 100:+.0f}pt"


def _format_seconds(value: Any) -> str:
    """초 단위 시간을 사람이 읽기 좋게 표시한다."""
    number = _score(value)
    if number is None:
        return "n/a"
    return f"{number:.0f}s"


@dataclass
class BenchmarkProofClaim:
    """proof pack이 주장하는 개별 증거 문장."""

    claim_id: str
    title: str
    verdict: str
    summary: str
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class BenchmarkProofPack:
    """Benchmark proof pack 전체 보고서."""

    schema_version: str
    generated_at: str
    proof_id: str
    project_name: str | None
    workspace: str
    workset_name: str
    strongest_lane: str | None
    lane_status: str | None
    compared_modes: list[str]
    best_mode: str | None
    previous_best_mode: str | None
    best_mode_changed: bool
    key_metrics: dict[str, Any]
    claims: list[BenchmarkProofClaim]
    current_verdict: str
    why_it_wins: list[str] = field(default_factory=list)
    where_it_fails: list[str] = field(default_factory=list)
    next_one_fix: str | None = None
    source_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["claims"] = [claim.to_dict() for claim in self.claims]
        return payload


class BenchmarkProofBuilder:
    """여러 benchmark/metrics artifact를 proof pack으로 합친다."""

    def build(self, project_root: Path, workset_name: str) -> BenchmarkProofPack:
        """현재 workset의 최신 증거들을 읽어 proof pack을 만든다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        source_refs: dict[str, Any] = {}

        report, report_ref = _latest_benchmark_report(root, workset_name)
        if report is None:
            warnings.append("latest benchmark report is missing for this workset")
        else:
            source_refs["benchmark_report_ref"] = report_ref

        compare_payload, compare_ref = _latest_matching_payload(
            root,
            default_benchmark_dir(root) / "latest_compare.yaml",
            default_benchmark_dir(root) / "compares",
            "compare_*.yaml",
            workset_name,
        )
        if compare_payload:
            source_refs["compare_ref"] = compare_ref
        else:
            warnings.append("latest benchmark compare is missing for this workset")

        autonomy_payload, autonomy_ref = _latest_matching_payload(
            root,
            default_benchmark_dir(root) / "latest_autonomy_board.yaml",
            default_benchmark_dir(root) / "autonomy_boards",
            "board_*.yaml",
            workset_name,
        )
        if autonomy_payload:
            source_refs["autonomy_board_ref"] = autonomy_ref
        else:
            warnings.append("latest autonomy board is missing for this workset")

        bottleneck_payload, bottleneck_ref = _latest_matching_payload(
            root,
            default_benchmark_dir(root) / "latest_bottleneck.yaml",
            default_benchmark_dir(root) / "bottlenecks",
            "bottlenecks_*.yaml",
            workset_name,
        )
        if bottleneck_payload:
            source_refs["bottleneck_ref"] = bottleneck_ref
        else:
            warnings.append("latest bottleneck report is missing for this workset")

        metrics_path = root / ".cambrian" / "metrics" / "latest.yaml"
        metrics_payload = _load_yaml(metrics_path)
        if metrics_payload:
            source_refs["metrics_ref"] = _relative(metrics_path, root)
        else:
            warnings.append("latest weekly metrics report is missing")

        lane_path = root / ".cambrian" / "lane" / "profile.yaml"
        lane_payload = _load_yaml(lane_path)
        if lane_payload:
            source_refs["lane_ref"] = _relative(lane_path, root)
        else:
            warnings.append("latest win-lane profile is missing")
        kept_summary: dict[str, Any] = {}
        try:
            from engine.project_improvement_decisions import kept_improvements_summary

            kept_summary = kept_improvements_summary(root)
            if kept_summary:
                source_refs["kept_improvements_ref"] = ".cambrian/improvement/persistent_overlay.yaml"
        except Exception as exc:
            warnings.append(f"kept improvements summary load failed: {exc}")

        key_metrics = _build_key_metrics(report, autonomy_payload, metrics_payload)
        claims = _build_claims(report, compare_payload, autonomy_payload, metrics_payload, source_refs)
        verdict = _current_verdict(report, compare_payload, autonomy_payload, lane_payload, claims, warnings)
        why_it_wins = _why_it_wins(report, autonomy_payload, lane_payload)
        if kept_summary:
            kinds = ", ".join(list(kept_summary.get("kept_fix_kinds", []) or [])[:3])
            why_it_wins = _dedupe([*why_it_wins, f"kept improvements active: {kinds or kept_summary.get('kept_count')}"])
        where_it_fails = _where_it_fails(bottleneck_payload, autonomy_payload, warnings)
        next_one_fix = _next_one_fix(bottleneck_payload)
        if not next_one_fix and where_it_fails:
            next_one_fix = where_it_fails[0]

        compared_modes = list(report.modes if report else [])
        best_mode = report.best_mode if report else None
        previous_best_mode = str(compare_payload.get("best_mode_before")) if compare_payload.get("best_mode_before") is not None else None
        best_mode_now = str(compare_payload.get("best_mode_now")) if compare_payload.get("best_mode_now") is not None else None
        best_mode_changed = bool(compare_payload.get("best_mode_changed", False))
        if best_mode_now:
            best_mode = best_mode_now

        return BenchmarkProofPack(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            proof_id=f"proof-{_slug(workset_name)}-{_short_id()}",
            project_name=_project_name(root),
            workspace=str(root),
            workset_name=workset_name,
            strongest_lane=str(lane_payload.get("label")) if lane_payload.get("label") is not None else None,
            lane_status=str(lane_payload.get("status")) if lane_payload.get("status") is not None else None,
            compared_modes=compared_modes,
            best_mode=best_mode,
            previous_best_mode=previous_best_mode,
            best_mode_changed=best_mode_changed,
            key_metrics=key_metrics,
            claims=claims,
            current_verdict=verdict,
            why_it_wins=why_it_wins,
            where_it_fails=where_it_fails,
            next_one_fix=next_one_fix,
            source_refs=source_refs,
            warnings=_dedupe(warnings),
            errors=errors,
        )


class BenchmarkProofStore:
    """Proof pack 저장소."""

    def save_yaml(self, report: BenchmarkProofPack, path: Path) -> Path:
        """YAML proof report와 latest pointer를 저장한다."""
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent / "latest.yaml", report.to_dict())
        return saved

    def save_markdown(self, report: BenchmarkProofPack, path: Path) -> Path:
        """Markdown proof report를 저장한다."""
        _atomic_write_text(Path(path).resolve(), render_proof_markdown(report))
        return Path(path).resolve()

    def load_yaml(self, path: Path) -> BenchmarkProofPack:
        """YAML proof report를 로드한다."""
        return _proof_from_dict(_load_yaml(Path(path).resolve()))


def default_proof_dir(project_root: Path) -> Path:
    """proof pack 저장 디렉터리."""
    return default_benchmark_dir(project_root) / "proof"


def default_proof_yaml_path(project_root: Path, report: BenchmarkProofPack) -> Path:
    """proof YAML 저장 경로."""
    return default_proof_dir(project_root) / f"proof_{_slug(report.workset_name)}_{_stamp()}_{_short_id()}.yaml"


def proof_markdown_path(yaml_path: Path) -> Path:
    """YAML proof 경로에 대응하는 Markdown 경로."""
    return Path(yaml_path).with_suffix(".md")


def resolve_proof_path(project_root: Path, proof_ref: str) -> Path:
    """proof id 또는 path를 실제 YAML artifact 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(proof_ref)
    if candidate.exists():
        path = candidate.resolve()
        return path.with_suffix(".yaml") if path.suffix == ".md" and path.with_suffix(".yaml").exists() else path
    if (root / candidate).exists():
        path = (root / candidate).resolve()
        return path.with_suffix(".yaml") if path.suffix == ".md" and path.with_suffix(".yaml").exists() else path
    for path in default_proof_dir(root).glob("proof_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == proof_ref or str(payload.get("proof_id") or "") == proof_ref:
            return path.resolve()
    latest = default_proof_dir(root) / "latest.yaml"
    payload = _load_yaml(latest)
    if proof_ref in {"latest", "latest.yaml"} and payload:
        return latest.resolve()
    raise FileNotFoundError(f"benchmark proof not found: {proof_ref}")


def load_latest_proof_summary(project_root: Path) -> dict[str, Any]:
    """status에서 쓸 최신 proof 요약을 읽는다."""
    payload = _load_yaml(default_proof_dir(project_root) / "latest.yaml")
    if not payload:
        return {}
    return {
        "workset_name": payload.get("workset_name"),
        "current_verdict": payload.get("current_verdict"),
        "best_mode": payload.get("best_mode"),
        "next_one_fix": payload.get("next_one_fix"),
        "proof_id": payload.get("proof_id"),
    }


def render_proof_pack(report: BenchmarkProofPack) -> str:
    """콘솔용 proof pack 요약을 렌더링한다."""
    lines = [
        "Benchmark Proof Pack",
        "==================================================",
        "",
        "Workset:",
        f"  {report.workset_name}",
        "",
        "Current strongest lane:",
        f"  {report.strongest_lane or 'unknown'}",
        f"  status: {report.lane_status or 'unknown'}",
        "",
        "Best mode now:",
        f"  {report.best_mode or 'none'}",
        "",
        "Best mode before:",
        f"  {report.previous_best_mode or 'none'}",
        "",
        "Current verdict:",
        f"  {report.current_verdict}",
    ]
    if report.why_it_wins:
        lines.extend(["", "Why Cambrian wins here:"])
        lines.extend([f"  - {item}" for item in report.why_it_wins])
    if report.where_it_fails:
        lines.extend(["", "Where it still fails:"])
        lines.extend([f"  - {item}" for item in report.where_it_fails])
    lines.extend(["", "Key metrics:"])
    lines.extend(_metric_lines(report.key_metrics, prefix="  "))
    if report.claims:
        lines.extend(["", "Claims:"])
        for claim in report.claims:
            lines.append(f"  - {claim.claim_id}: {claim.verdict}")
            lines.append(f"    {claim.summary}")
    lines.extend(["", "Next one fix:", f"  {report.next_one_fix or 'none yet'}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings[:8]])
    return "\n".join(lines)


def render_proof_markdown(report: BenchmarkProofPack) -> str:
    """공유 가능한 한 장짜리 Markdown proof report를 만든다."""
    lines = [
        "# Cambrian Benchmark Proof Pack",
        "",
        "## Workset",
        report.workset_name,
        "",
        "## Strongest Lane",
        f"{report.strongest_lane or 'unknown'}",
        "",
        "## Current Verdict",
        report.current_verdict,
        "",
        "## Best Mode Now",
        report.best_mode or "none",
        "",
        "## Best Mode Before",
        report.previous_best_mode or "none",
        "",
        "## Why It Wins",
    ]
    lines.extend([f"- {item}" for item in report.why_it_wins] or ["- Not enough positive evidence yet."])
    lines.extend(["", "## Where It Still Fails"])
    lines.extend([f"- {item}" for item in report.where_it_fails] or ["- No dominant bottleneck recorded yet."])
    lines.extend(["", "## Key Metrics"])
    lines.extend(_metric_lines(report.key_metrics, prefix="- "))
    lines.extend(["", "## Claims"])
    if report.claims:
        lines.extend([f"- {claim.claim_id}: {claim.verdict} - {claim.summary}" for claim in report.claims])
    else:
        lines.append("- insufficient_data: no claims could be made safely")
    lines.extend(["", "## Next One Fix", report.next_one_fix or "none yet"])
    if report.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend([f"- {item}" for item in report.warnings[:8]])
    return "\n".join(lines) + "\n"


def _metric_lines(metrics: dict[str, Any], *, prefix: str) -> list[str]:
    """key metrics를 일관된 라인으로 렌더링한다."""
    return [
        f"{prefix}validated proposal rate: {_format_rate(metrics.get('validated_proposal_rate'))}",
        f"{prefix}adoption rate: {_format_rate(metrics.get('adoption_rate'))}",
        f"{prefix}regression-free apply rate: {_format_rate(metrics.get('regression_free_apply_rate'))}",
        f"{prefix}human intervention rate: {_format_rate(metrics.get('human_intervention_rate'))}",
        f"{prefix}validation autonomy rate: {_format_rate(metrics.get('validation_autonomy_rate'))}",
        f"{prefix}median time to validated proposal: {_format_seconds(metrics.get('median_time_to_validated_proposal'))}",
        f"{prefix}reuse lift: {_format_points(metrics.get('reuse_lift'))}",
        f"{prefix}repeat task improvement rate: {_format_points(metrics.get('repeat_task_improvement_rate'))}",
    ]


def _latest_benchmark_report(root: Path, workset_name: str) -> tuple[BenchmarkReport | None, str | None]:
    """workset에 맞는 최신 benchmark report를 찾는다."""
    latest = default_reports_dir(root) / "latest.yaml"
    payload = _load_yaml(latest)
    if payload and str(payload.get("workset_name") or "") == workset_name:
        return BenchmarkStore().load_report(latest), _relative(latest, root)
    candidates = _matching_paths(default_reports_dir(root), "report_*.yaml", workset_name)
    if not candidates:
        return None, None
    selected = candidates[0]
    return BenchmarkStore().load_report(selected), _relative(selected, root)


def _latest_matching_payload(
    root: Path,
    latest_path: Path,
    directory: Path,
    pattern: str,
    workset_name: str,
) -> tuple[dict[str, Any], str | None]:
    """latest pointer 또는 디렉터리 scan으로 workset payload를 찾는다."""
    payload = _load_yaml(latest_path)
    if payload and str(payload.get("workset_name") or "") == workset_name:
        return payload, _relative(latest_path, root)
    candidates = _matching_paths(directory, pattern, workset_name)
    if not candidates:
        return {}, None
    selected = candidates[0]
    return _load_yaml(selected), _relative(selected, root)


def _matching_paths(directory: Path, pattern: str, workset_name: str) -> list[Path]:
    """workset_name이 일치하는 최신 artifact 경로들을 찾는다."""
    paths: list[Path] = []
    if not Path(directory).exists():
        return paths
    for path in Path(directory).glob(pattern):
        payload = _load_yaml(path)
        if str(payload.get("workset_name") or "") == workset_name:
            paths.append(path.resolve())
    paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return paths


def _build_key_metrics(
    report: BenchmarkReport | None,
    autonomy_payload: dict[str, Any],
    metrics_payload: dict[str, Any],
) -> dict[str, Any]:
    """proof pack 핵심 metric을 source별로 합친다."""
    weekly = metrics_payload.get("summary") if isinstance(metrics_payload.get("summary"), dict) else {}
    best_mode = report.best_mode if report else None
    mode_values = dict(report.by_mode.get(best_mode, {})) if report and best_mode and isinstance(report.by_mode.get(best_mode), dict) else {}
    full_values = dict(report.by_mode.get("cambrian_full", {})) if report and isinstance(report.by_mode.get("cambrian_full"), dict) else {}
    values = full_values or mode_values
    autonomy = _mode_summary(autonomy_payload, "cambrian_full") or _mode_summary(autonomy_payload, autonomy_payload.get("best_mode"))
    return {
        "validated_proposal_rate": _first_metric(values.get("validated_proposal_rate"), autonomy.get("validated_proposal_rate"), weekly.get("validated_proposal_rate")),
        "adoption_rate": _first_metric(values.get("adoption_rate"), weekly.get("adoption_rate")),
        "regression_free_apply_rate": _first_metric(values.get("regression_free_apply_rate"), weekly.get("regression_free_apply_rate")),
        "median_time_to_validated_proposal": _first_metric(weekly.get("median_time_to_validated_proposal"), values.get("median_duration_seconds"), autonomy.get("median_duration_seconds")),
        "human_intervention_rate": _first_metric(values.get("human_intervention_rate"), autonomy.get("human_intervention_rate"), weekly.get("human_intervention_rate")),
        "validation_autonomy_rate": _first_metric(autonomy.get("validation_autonomy_rate"), values.get("validation_autonomy_rate"), weekly.get("validation_autonomy_rate")),
        "reuse_lift": _first_metric(weekly.get("reuse_lift")),
        "repeat_task_improvement_rate": _first_metric(weekly.get("repeat_task_improvement_rate")),
    }


def _first_metric(*values: Any) -> Any:
    """처음으로 비어 있지 않은 metric 값을 고른다."""
    for value in values:
        if value is not None:
            return value
    return None


def _mode_summary(payload: dict[str, Any], mode: Any) -> dict[str, Any]:
    """autonomy board에서 특정 mode summary를 찾는다."""
    if not payload or not mode:
        return {}
    for item in payload.get("mode_summaries", []):
        if isinstance(item, dict) and item.get("mode") == mode:
            return item
    return {}


def _build_claims(
    report: BenchmarkReport | None,
    compare_payload: dict[str, Any],
    autonomy_payload: dict[str, Any],
    metrics_payload: dict[str, Any],
    source_refs: dict[str, Any],
) -> list[BenchmarkProofClaim]:
    """proof pack 기본 claim들을 만든다."""
    claims = [
        _mode_beats_claim(
            report,
            "cambrian_full_beats_raw_ai",
            "Cambrian Full beats raw AI",
            "cambrian_full",
            "raw_ai",
            source_refs.get("benchmark_report_ref"),
        ),
        _mode_beats_claim(
            report,
            "cambrian_full_beats_bridge_only",
            "Cambrian Full beats bridge-only",
            "cambrian_full",
            "bridge_only",
            source_refs.get("benchmark_report_ref"),
        ),
        _baseline_claim(compare_payload, source_refs.get("compare_ref")),
        _autonomy_claim(autonomy_payload, source_refs.get("autonomy_board_ref")),
        _learning_claim(metrics_payload, compare_payload, source_refs),
    ]
    return [claim for claim in claims if claim is not None]


def _mode_beats_claim(
    report: BenchmarkReport | None,
    claim_id: str,
    title: str,
    left_mode: str,
    right_mode: str,
    evidence_ref: str | None,
) -> BenchmarkProofClaim | None:
    """두 mode의 benchmark 결과를 claim으로 만든다."""
    if report is None:
        return BenchmarkProofClaim(claim_id, title, "insufficient_data", "benchmark report is missing", [], ["missing benchmark report"])
    left = report.by_mode.get(left_mode) if isinstance(report.by_mode.get(left_mode), dict) else None
    right = report.by_mode.get(right_mode) if isinstance(report.by_mode.get(right_mode), dict) else None
    if not left or not right:
        return BenchmarkProofClaim(
            claim_id,
            title,
            "insufficient_data",
            f"{left_mode} or {right_mode} is missing from benchmark report",
            [evidence_ref] if evidence_ref else [],
            ["missing comparable mode"],
        )
    validated_delta = _metric_delta(left.get("validated_proposal_rate"), right.get("validated_proposal_rate"))
    intervention_delta = _metric_delta(left.get("human_intervention_rate"), right.get("human_intervention_rate"))
    if validated_delta is None:
        verdict = "insufficient_data"
    elif validated_delta > 0.05 and (intervention_delta is None or intervention_delta <= 0.05):
        verdict = "proven"
    elif validated_delta >= 0:
        verdict = "promising"
    elif validated_delta <= -0.05:
        verdict = "false"
    else:
        verdict = "weak"
    summary = (
        f"{left_mode} validated {_format_rate(left.get('validated_proposal_rate'))} "
        f"vs {right_mode} {_format_rate(right.get('validated_proposal_rate'))}; "
        f"intervention {_format_rate(left.get('human_intervention_rate'))} "
        f"vs {_format_rate(right.get('human_intervention_rate'))}"
    )
    return BenchmarkProofClaim(claim_id, title, verdict, summary, [evidence_ref] if evidence_ref else [], [])


def _baseline_claim(compare_payload: dict[str, Any], evidence_ref: str | None) -> BenchmarkProofClaim:
    """baseline compare를 claim으로 만든다."""
    if not compare_payload:
        return BenchmarkProofClaim(
            "current_system_improved_vs_baseline",
            "Current system improved vs baseline",
            "insufficient_data",
            "baseline compare is missing",
            [],
            ["missing benchmark compare"],
        )
    verdict = str(compare_payload.get("verdict") or "insufficient_data")
    claim_verdict = {
        "improved": "proven",
        "mixed": "promising",
        "regressed": "false",
        "insufficient_data": "insufficient_data",
    }.get(verdict, "weak")
    return BenchmarkProofClaim(
        "current_system_improved_vs_baseline",
        "Current system improved vs baseline",
        claim_verdict,
        f"benchmark compare verdict is {verdict}",
        [evidence_ref] if evidence_ref else [],
        [str(item) for item in compare_payload.get("warnings", []) if item],
    )


def _autonomy_claim(autonomy_payload: dict[str, Any], evidence_ref: str | None) -> BenchmarkProofClaim:
    """autonomy board를 claim으로 만든다."""
    if not autonomy_payload:
        return BenchmarkProofClaim(
            "autonomy_reaches_validated_proposal",
            "Autonomy reaches validated proposal",
            "insufficient_data",
            "autonomy board is missing",
            [],
            ["missing autonomy board"],
        )
    summary = _mode_summary(autonomy_payload, "cambrian_full") or _mode_summary(autonomy_payload, autonomy_payload.get("best_mode"))
    validated = _score(summary.get("validated_proposal_rate"))
    autonomy = _score(summary.get("validation_autonomy_rate"))
    if validated is None:
        verdict = "insufficient_data"
    elif validated >= 0.5 and (autonomy is None or autonomy >= 0.35):
        verdict = "proven"
    elif validated > 0:
        verdict = "promising"
    else:
        verdict = "weak"
    return BenchmarkProofClaim(
        "autonomy_reaches_validated_proposal",
        "Autonomy reaches validated proposal",
        verdict,
        f"validated proposal {_format_rate(validated)}; validation autonomy {_format_rate(autonomy)}",
        [evidence_ref] if evidence_ref else [],
        [str(item) for item in autonomy_payload.get("warnings", []) if item],
    )


def _learning_claim(
    metrics_payload: dict[str, Any],
    compare_payload: dict[str, Any],
    source_refs: dict[str, Any],
) -> BenchmarkProofClaim:
    """reuse/repeat/baseline 신호로 harness learning claim을 만든다."""
    summary = metrics_payload.get("summary") if isinstance(metrics_payload.get("summary"), dict) else {}
    repeat = _score(summary.get("repeat_task_improvement_rate"))
    reuse = _score(summary.get("reuse_lift"))
    compare_verdict = str(compare_payload.get("verdict") or "")
    evidence_refs = [str(item) for item in [source_refs.get("metrics_ref"), source_refs.get("compare_ref")] if item]
    if repeat is None and reuse is None and not compare_verdict:
        return BenchmarkProofClaim(
            "harness_is_learning",
            "Harness is learning",
            "insufficient_data",
            "repeat/reuse metrics and compare trend are missing",
            evidence_refs,
            ["missing weekly learning metrics"],
        )
    positive = any(value is not None and value > 0 for value in [repeat, reuse]) or compare_verdict == "improved"
    negative = any(value is not None and value < -0.05 for value in [repeat, reuse]) or compare_verdict == "regressed"
    verdict = "proven" if positive and not negative else "false" if negative and not positive else "promising" if positive else "weak"
    return BenchmarkProofClaim(
        "harness_is_learning",
        "Harness is learning",
        verdict,
        f"repeat improvement {_format_points(repeat)}; reuse lift {_format_points(reuse)}; compare {compare_verdict or 'n/a'}",
        evidence_refs,
        [],
    )


def _current_verdict(
    report: BenchmarkReport | None,
    compare_payload: dict[str, Any],
    autonomy_payload: dict[str, Any],
    lane_payload: dict[str, Any],
    claims: list[BenchmarkProofClaim],
    warnings: list[str],
) -> str:
    """전체 proof verdict를 결정한다."""
    if report is None or not lane_payload:
        return "insufficient_data"
    if str(compare_payload.get("verdict") or "") == "regressed":
        return "regressed"
    false_claims = [claim for claim in claims if claim.verdict == "false"]
    if false_claims:
        return "regressed" if false_claims[0].claim_id == "cambrian_full_beats_raw_ai" else "mixed"
    lane_strong = str(lane_payload.get("status") or "") == "strong"
    full_raw = next((claim for claim in claims if claim.claim_id == "cambrian_full_beats_raw_ai"), None)
    autonomy = next((claim for claim in claims if claim.claim_id == "autonomy_reaches_validated_proposal"), None)
    baseline = next((claim for claim in claims if claim.claim_id == "current_system_improved_vs_baseline"), None)
    if (
        lane_strong
        and full_raw is not None
        and full_raw.verdict == "proven"
        and autonomy is not None
        and autonomy.verdict in {"proven", "promising"}
        and (not baseline or baseline.verdict in {"proven", "promising", "insufficient_data"})
    ):
        return "wins_now" if baseline and baseline.verdict == "proven" else "promising"
    if len(warnings) >= 4:
        return "insufficient_data"
    if any(claim.verdict in {"proven", "promising"} for claim in claims):
        return "promising"
    return "mixed"


def _why_it_wins(
    report: BenchmarkReport | None,
    autonomy_payload: dict[str, Any],
    lane_payload: dict[str, Any],
) -> list[str]:
    """positive evidence 문장을 만든다."""
    reasons: list[str] = []
    if report and report.best_mode == "cambrian_full":
        reasons.append("cambrian_full is the current best benchmark mode")
    if report and _mode_beats(report, "cambrian_full", "raw_ai"):
        reasons.append("cambrian_full has higher validated proposal evidence than raw_ai")
    full_autonomy = _mode_summary(autonomy_payload, "cambrian_full")
    if _score(full_autonomy.get("validation_autonomy_rate")) not in (None, 0):
        reasons.append("cambrian_full shows validation autonomy on the workset")
    if _score(full_autonomy.get("human_intervention_rate")) is not None:
        reasons.append("human intervention is measured directly for cambrian_full")
    if str(lane_payload.get("status") or "") == "strong":
        reasons.append("current strongest lane fit is strong")
    return _dedupe(reasons) or ["evidence is not strong enough to claim a win yet"]


def _where_it_fails(
    bottleneck_payload: dict[str, Any],
    autonomy_payload: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    """병목과 stop reason에서 실패 지점을 만든다."""
    failures: list[str] = []
    summary = bottleneck_payload.get("summary") if isinstance(bottleneck_payload.get("summary"), dict) else {}
    if summary.get("top_bottleneck"):
        failures.append(str(summary.get("top_bottleneck")))
    for item in bottleneck_payload.get("bottlenecks", []) if isinstance(bottleneck_payload.get("bottlenecks"), list) else []:
        if isinstance(item, dict) and item.get("summary"):
            failures.append(str(item.get("summary")))
    full = _mode_summary(autonomy_payload, "cambrian_full") or _mode_summary(autonomy_payload, autonomy_payload.get("best_mode"))
    reasons = full.get("stop_reason_counts") if isinstance(full.get("stop_reason_counts"), dict) else {}
    for reason, count in sorted(reasons.items(), key=lambda pair: int(pair[1] or 0), reverse=True):
        if reason:
            failures.append(f"{reason} ({count})")
    if not failures and warnings:
        failures.append("evidence is sparse; missing sources limit proof confidence")
    return _dedupe(failures)[:5]


def _next_one_fix(bottleneck_payload: dict[str, Any]) -> str | None:
    """bottleneck report에서 다음 fix 한 개만 고른다."""
    summary = bottleneck_payload.get("summary") if isinstance(bottleneck_payload.get("summary"), dict) else {}
    if summary.get("top_suggestion"):
        return str(summary.get("top_suggestion"))
    suggestions = bottleneck_payload.get("suggestions")
    if isinstance(suggestions, list):
        for item in suggestions:
            if isinstance(item, dict) and item.get("summary"):
                return str(item.get("summary"))
    return None


def _mode_beats(report: BenchmarkReport, left_mode: str, right_mode: str) -> bool:
    """left mode가 right mode보다 validated proposal 기준 우세한지 판단한다."""
    left = report.by_mode.get(left_mode) if isinstance(report.by_mode.get(left_mode), dict) else {}
    right = report.by_mode.get(right_mode) if isinstance(report.by_mode.get(right_mode), dict) else {}
    delta = _metric_delta(left.get("validated_proposal_rate"), right.get("validated_proposal_rate"))
    return bool(delta is not None and delta > 0.05)


def _project_name(root: Path) -> str | None:
    """project.yaml에서 프로젝트 이름을 읽는다."""
    payload = _load_yaml(root / ".cambrian" / "project.yaml")
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    return str(project.get("name")) if project.get("name") is not None else None


def _proof_from_dict(payload: dict[str, Any]) -> BenchmarkProofPack:
    """dict를 BenchmarkProofPack으로 복원한다."""
    return BenchmarkProofPack(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        generated_at=str(payload.get("generated_at") or ""),
        proof_id=str(payload.get("proof_id") or ""),
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        workspace=str(payload.get("workspace") or ""),
        workset_name=str(payload.get("workset_name") or ""),
        strongest_lane=str(payload.get("strongest_lane")) if payload.get("strongest_lane") is not None else None,
        lane_status=str(payload.get("lane_status")) if payload.get("lane_status") is not None else None,
        compared_modes=[str(item) for item in payload.get("compared_modes", []) if item],
        best_mode=str(payload.get("best_mode")) if payload.get("best_mode") is not None else None,
        previous_best_mode=str(payload.get("previous_best_mode")) if payload.get("previous_best_mode") is not None else None,
        best_mode_changed=bool(payload.get("best_mode_changed", False)),
        key_metrics=dict(payload.get("key_metrics", {})) if isinstance(payload.get("key_metrics"), dict) else {},
        claims=[_claim_from_dict(item) for item in payload.get("claims", []) if isinstance(item, dict)],
        current_verdict=str(payload.get("current_verdict") or "insufficient_data"),
        why_it_wins=[str(item) for item in payload.get("why_it_wins", []) if item],
        where_it_fails=[str(item) for item in payload.get("where_it_fails", []) if item],
        next_one_fix=str(payload.get("next_one_fix")) if payload.get("next_one_fix") is not None else None,
        source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _claim_from_dict(payload: dict[str, Any]) -> BenchmarkProofClaim:
    """dict를 BenchmarkProofClaim으로 복원한다."""
    return BenchmarkProofClaim(
        claim_id=str(payload.get("claim_id") or ""),
        title=str(payload.get("title") or ""),
        verdict=str(payload.get("verdict") or "insufficient_data"),
        summary=str(payload.get("summary") or ""),
        evidence_refs=[str(item) for item in payload.get("evidence_refs", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
    )
