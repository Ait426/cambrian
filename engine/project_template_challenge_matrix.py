"""queued challenger를 same-workset replay evidence로 정렬하는 모듈."""

from __future__ import annotations

import logging
import re
import secrets
import statistics
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_canary import active_canary_stage
from engine.project_template_qualification import (
    DURATION_THRESHOLD_SECONDS,
    RATE_THRESHOLD,
    _run_template_workset,
)
from engine.project_template_qualification_decisions import LanePlaybookStore, lane_playbook_path
from engine.project_templates import HarnessTemplate, HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
MATRIX_MODES = {"cambrian_guided", "cambrian_full"}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명용 UTC timestamp를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 식별자를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str | None, fallback: str = "item") -> str:
    """값을 파일명에 안전한 slug로 바꾼다."""
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


def _save_yaml(path: Path, payload: dict[str, Any]) -> Path:
    """YAML payload를 저장한다."""
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    """YAML artifact를 안전하게 읽는다."""
    if not Path(path).exists():
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("challenge matrix artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """프로젝트 root 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


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


def challenge_matrices_dir(project_root: Path) -> Path:
    """challenge matrix 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "challenge_matrices"


def challengers_path(project_root: Path) -> Path:
    """challenger queue 저장 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "challengers.yaml"


def default_challenge_matrix_path(project_root: Path, report: "TemplateChallengeMatrix") -> Path:
    """challenge matrix 기본 저장 경로."""
    return challenge_matrices_dir(project_root) / f"matrix_{_slug(report.workset_name)}_{_stamp()}_{_short_id()}.yaml"


def latest_challenge_matrix_path(project_root: Path) -> Path:
    """latest challenge matrix pointer 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "latest_challenge_matrix.yaml"


@dataclass
class TemplateChallengeCandidateRun:
    """template/mode별 safe replay evidence snapshot."""

    template_name: str
    template_id: str | None
    role: str
    mode: str
    replay_ref: str | None
    status: str
    validated_proposal_rate: float | None
    human_intervention_rate: float | None
    validation_autonomy_rate: float | None
    median_duration_seconds: float | None
    stage_counts: dict[str, int]
    stop_reason_counts: dict[str, int]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateChallengePairwise:
    """두 template replay snapshot의 mode별 비교."""

    left_template_name: str
    right_template_name: str
    mode: str
    verdict: str
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateChallengeMatrix:
    """stable/canary/queued challenger replay matrix."""

    schema_version: str
    report_id: str
    generated_at: str
    lane_id: str | None
    lane_label: str | None
    workset_name: str
    stable_default_template_name: str | None
    active_canary_template_name: str | None
    queued_challengers: list[str]
    candidate_runs: list[TemplateChallengeCandidateRun]
    pairwise: list[TemplateChallengePairwise]
    ranked_challengers: list[str]
    next_best_challenger: str | None
    summary: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "lane_id": self.lane_id,
            "lane_label": self.lane_label,
            "workset_name": self.workset_name,
            "stable_default_template_name": self.stable_default_template_name,
            "active_canary_template_name": self.active_canary_template_name,
            "queued_challengers": list(self.queued_challengers),
            "candidate_runs": [run.to_dict() for run in self.candidate_runs],
            "pairwise": [item.to_dict() for item in self.pairwise],
            "ranked_challengers": list(self.ranked_challengers),
            "next_best_challenger": self.next_best_challenger,
            "summary": list(self.summary),
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateChallengeMatrixBuilder:
    """queued challengers를 replay matrix로 평가한다."""

    def build(self, project_root: Path, workset_name: str, modes: list[str] | None = None) -> TemplateChallengeMatrix:
        """stable default, active canary, queued challengers를 같은 workset에서 비교한다."""
        root = Path(project_root).resolve()
        selected_modes = _normalize_modes(modes)
        playbook = LanePlaybookStore().load(lane_playbook_path(root))
        model = HarnessTemplateStore().load(default_templates_path(root))
        stable_name = playbook.default_template_name
        active_stage = active_canary_stage(root)
        canary_name = active_stage.candidate_template_name if active_stage else playbook.canary_template_name
        queued, queue_warnings = _queued_challengers(root)
        warnings = list(queue_warnings)
        roles: dict[str, str] = {}
        if stable_name:
            roles[stable_name] = "stable_default"
        else:
            warnings.append("stable default template is missing from lane playbook")
        if canary_name and _slug(canary_name) not in {_slug(stable_name)}:
            roles[canary_name] = "active_canary"
        for name in queued:
            if _slug(name) in {_slug(stable_name), _slug(canary_name)}:
                warnings.append(f"queued challenger already has lane role and was not duplicated: {name}")
                continue
            roles[name] = "queued_challenger"
        if not queued:
            warnings.append("no queued challengers found")

        candidate_runs: list[TemplateChallengeCandidateRun] = []
        for template_name, role in roles.items():
            try:
                template = HarnessTemplateStore().find(model, template_name)
            except KeyError:
                warnings.append(f"template missing from store: {template_name}")
                for mode in selected_modes:
                    candidate_runs.append(_failed_run(template_name, None, role, mode, "template missing from store"))
                continue
            for mode in selected_modes:
                candidate_runs.append(_run_candidate(root, template, role, workset_name, mode))

        pairwise = _pairwise_for_matrix(candidate_runs, queued, stable_name, canary_name)
        ranked, next_best = _rank_challengers(queued, candidate_runs, pairwise)
        summary = _summary(next_best, ranked, pairwise, warnings)
        return TemplateChallengeMatrix(
            schema_version=SCHEMA_VERSION,
            report_id=f"template-challenge-matrix-{_slug(workset_name)}-{_short_id()}",
            generated_at=_now(),
            lane_id=playbook.lane_id,
            lane_label=playbook.label,
            workset_name=workset_name,
            stable_default_template_name=stable_name,
            active_canary_template_name=canary_name,
            queued_challengers=queued,
            candidate_runs=candidate_runs,
            pairwise=pairwise,
            ranked_challengers=ranked,
            next_best_challenger=next_best,
            summary=summary,
            next_actions=_next_actions(next_best),
            warnings=_dedupe(warnings),
            errors=_dedupe([error for run in candidate_runs for error in run.errors]),
        )


class TemplateChallengeMatrixStore:
    """challenge matrix 저장소."""

    def save(self, report: TemplateChallengeMatrix, path: Path) -> Path:
        """matrix report를 저장하고 latest pointer를 갱신한다."""
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent.parent / "latest_challenge_matrix.yaml", report.to_dict())
        return saved

    def load(self, path: Path) -> TemplateChallengeMatrix:
        """matrix report를 로드한다."""
        return _matrix_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, reports_dir: Path) -> list[TemplateChallengeMatrix]:
        """저장된 matrix 목록을 최신순으로 반환한다."""
        target = Path(reports_dir).resolve()
        if not target.exists():
            return []
        reports: list[TemplateChallengeMatrix] = []
        for path in target.glob("matrix_*.yaml"):
            payload = _load_yaml(path)
            if payload:
                reports.append(_matrix_from_dict(payload))
        return sorted(reports, key=lambda report: report.generated_at, reverse=True)


def resolve_challenge_matrix_path(project_root: Path, matrix_ref: str) -> Path:
    """matrix id 또는 path를 실제 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(matrix_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in challenge_matrices_dir(root).glob("matrix_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == matrix_ref or str(payload.get("report_id") or "") == matrix_ref:
            return path.resolve()
    raise FileNotFoundError(f"challenge matrix not found: {matrix_ref}")


def load_latest_challenge_matrix(project_root: Path, workset_name: str | None = None) -> TemplateChallengeMatrix | None:
    """latest challenge matrix를 로드한다."""
    root = Path(project_root).resolve()
    pointer = latest_challenge_matrix_path(root)
    if pointer.exists():
        report = _matrix_from_dict(_load_yaml(pointer))
        if not workset_name or report.workset_name == workset_name:
            return report
    reports = TemplateChallengeMatrixStore().list(challenge_matrices_dir(root))
    if workset_name:
        reports = [report for report in reports if report.workset_name == workset_name]
    return reports[0] if reports else None


def load_challenge_matrix_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """status/show/harness용 compact matrix summary."""
    report = load_latest_challenge_matrix(project_root)
    if report is None:
        return {}
    payload: dict[str, Any] = {
        "report_id": report.report_id,
        "workset_name": report.workset_name,
        "stable_default_template_name": report.stable_default_template_name,
        "active_canary_template_name": report.active_canary_template_name,
        "queued_challengers": list(report.queued_challengers),
        "ranked_challengers": list(report.ranked_challengers),
        "next_best_challenger": report.next_best_challenger,
        "matrix_backed": True,
        "summary": list(report.summary[:3]),
    }
    if template_name:
        payload["template_standing"] = _template_matrix_standing(report, template_name)
    return payload


def load_challenger_queue_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """queued challenger summary를 반환한다."""
    queued, warnings = _queued_challengers(Path(project_root).resolve())
    matrix = load_latest_challenge_matrix(project_root)
    ranked = matrix.ranked_challengers if matrix is not None else queued
    summary: dict[str, Any] = {
        "queued_challengers": queued,
        "ranked_challengers": list(ranked),
        "next_best_challenger": matrix.next_best_challenger if matrix is not None else (queued[0] if queued else None),
        "matrix_backed": matrix is not None,
        "warnings": warnings,
    }
    if template_name:
        if _slug(template_name) in {_slug(item) for item in queued}:
            rank = next((index + 1 for index, name in enumerate(ranked) if _slug(name) == _slug(template_name)), None)
            summary["template_standing"] = f"queued challenger rank {rank}" if rank else "queued challenger"
    return summary


def build_challenge_board_summary(project_root: Path) -> dict[str, Any]:
    """challenge-board용 summary를 만든다. matrix가 있으면 우선 사용한다."""
    root = Path(project_root).resolve()
    playbook = LanePlaybookStore().load(lane_playbook_path(root))
    queued, warnings = _queued_challengers(root)
    matrix = load_latest_challenge_matrix(root)
    next_best = matrix.next_best_challenger if matrix is not None else (queued[0] if queued else None)
    return {
        "lane_id": playbook.lane_id,
        "lane_label": playbook.label,
        "stable_default_template_name": playbook.default_template_name,
        "active_canary_template_name": playbook.canary_template_name,
        "queued_challengers": queued,
        "ranked_challengers": list(matrix.ranked_challengers) if matrix is not None else queued,
        "next_best_challenger": next_best,
        "matrix_backed": matrix is not None,
        "matrix_report_id": matrix.report_id if matrix is not None else None,
        "warnings": warnings,
    }


def render_challenge_matrix(report: TemplateChallengeMatrix, saved_path: str | None = None) -> str:
    """challenge matrix report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Template Challenge Matrix",
        "==================================================",
        "",
        "Lane:",
        f"  {report.lane_label or report.lane_id or 'unknown'}",
        "",
        "Workset:",
        f"  {report.workset_name}",
        "",
        "Stable default:",
        f"  {report.stable_default_template_name or 'none'}",
        "",
        "Active canary:",
        f"  {report.active_canary_template_name or 'none'}",
        "",
        "Queued challengers:",
    ]
    lines.extend([f"  - {name}" for name in report.queued_challengers] or ["  none"])
    lines.extend(["", "Next best challenger:", f"  {report.next_best_challenger or 'inconclusive'}"])
    if report.summary:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {item}" for item in report.summary[:6]])
    if report.pairwise:
        lines.extend(["", "Pairwise:"])
        for item in report.pairwise[:8]:
            lines.append(f"  - {item.left_template_name} vs {item.right_template_name} ({item.mode}): {item.verdict}")
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in report.next_actions[:3]])
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings[:5]])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors[:5]])
    return "\n".join(lines)


def render_challenge_board(summary: dict[str, Any]) -> str:
    """challenge-board summary를 렌더링한다."""
    lines = [
        "Template Challenge Board",
        "==================================================",
        "",
        "Lane:",
        f"  {summary.get('lane_label') or summary.get('lane_id') or 'unknown'}",
        "",
        "Stable default:",
        f"  {summary.get('stable_default_template_name') or 'none'}",
        "",
        "Active canary:",
        f"  {summary.get('active_canary_template_name') or 'none'}",
        "",
        "Next best challenger:",
        f"  {summary.get('next_best_challenger') or 'none'}"
        + (" (matrix-backed)" if summary.get("matrix_backed") and summary.get("next_best_challenger") else ""),
        "",
        "Queued:",
    ]
    ranked = list(summary.get("ranked_challengers", []) or summary.get("queued_challengers", []) or [])
    lines.extend([f"  {index}. {name}" for index, name in enumerate(ranked, start=1)] or ["  none"])
    warnings = [str(item) for item in summary.get("warnings", []) if item]
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in warnings[:5]])
    return "\n".join(lines)


def render_challengers(summary: dict[str, Any]) -> str:
    """challenger queue summary를 렌더링한다."""
    lines = [
        "Template Challengers",
        "==================================================",
        "",
        "Queued:",
    ]
    ranked = list(summary.get("ranked_challengers", []) or summary.get("queued_challengers", []) or [])
    lines.extend([f"  {index}. {name}" for index, name in enumerate(ranked, start=1)] or ["  none"])
    next_best = summary.get("next_best_challenger")
    if next_best:
        lines.extend(["", "Next best challenger:", f"  {next_best}" + (" (matrix-backed)" if summary.get("matrix_backed") else "")])
    warnings = [str(item) for item in summary.get("warnings", []) if item]
    if warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in warnings[:5]])
    return "\n".join(lines)


def render_challenge_matrix_summary(summary: dict[str, Any]) -> str:
    """compact matrix summary를 렌더링한다."""
    if not summary:
        return "Challenger matrix:\n  none"
    next_best = summary.get("next_best_challenger")
    lines = ["Challenger matrix:"]
    if next_best:
        lines.append(f"  next best : {next_best}")
    else:
        lines.append("  inconclusive")
    if summary.get("workset_name"):
        lines.append(f"  workset   : {summary.get('workset_name')}")
    return "\n".join(lines)


def _queued_challengers(root: Path) -> tuple[list[str], list[str]]:
    """challengers.yaml에서 queued challenger 이름을 읽는다."""
    payload = _load_yaml(challengers_path(root))
    warnings: list[str] = []
    raw_items = payload.get("queued_challengers")
    if raw_items is None:
        raw_items = payload.get("challengers")
    if raw_items is None:
        raw_items = payload.get("queue")
    if raw_items is None:
        return [], ["challenger queue is missing: .cambrian/templates/challengers.yaml"]
    queued: list[str] = []
    for item in raw_items if isinstance(raw_items, list) else []:
        if isinstance(item, str):
            queued.append(item)
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("template_name") or item.get("name") or item.get("template") or "").strip()
        status = str(item.get("status") or "queued").strip()
        if not name:
            continue
        if status == "queued":
            queued.append(name)
        else:
            warnings.append(f"challenger excluded because status is {status}: {name}")
    return _dedupe(queued), _dedupe(warnings)


def _normalize_modes(modes: list[str] | None) -> list[str]:
    """CLI mode token을 replay mode 목록으로 정규화한다."""
    if not modes:
        return ["cambrian_guided", "cambrian_full"]
    result: list[str] = []
    mapping = {"guided": "cambrian_guided", "full": "cambrian_full", "both": "both"}
    for mode in modes:
        token = mapping.get(str(mode), str(mode))
        if token == "both":
            result.extend(["cambrian_guided", "cambrian_full"])
        elif token in MATRIX_MODES:
            result.append(token)
        else:
            raise ValueError(f"unsupported challenge matrix mode: {mode}")
    return _dedupe(result)


def _run_candidate(
    root: Path,
    template: HarnessTemplate,
    role: str,
    workset_name: str,
    mode: str,
) -> TemplateChallengeCandidateRun:
    """단일 candidate/mode replay를 실행하고 matrix run으로 변환한다."""
    try:
        run = _run_template_workset(root, template, workset_name, mode, "challenge_matrix_override")
    except Exception as exc:
        logger.warning("challenge matrix replay failed for %s/%s: %s", template.name, mode, exc)
        return _failed_run(template.name, template.template_id, role, mode, str(exc))
    snapshot = dict(run.metrics_snapshot)
    return TemplateChallengeCandidateRun(
        template_name=run.template_name,
        template_id=run.template_id,
        role=role,
        mode=run.mode,
        replay_ref=run.replay_report_ref,
        status=_run_status(snapshot, run.errors),
        validated_proposal_rate=_number(snapshot.get("validated_proposal_rate")),
        human_intervention_rate=_number(snapshot.get("human_intervention_rate")),
        validation_autonomy_rate=_number(snapshot.get("validation_autonomy_rate")),
        median_duration_seconds=_number(snapshot.get("median_duration_seconds")),
        stage_counts={str(key): int(value or 0) for key, value in dict(snapshot.get("stage_counts", {})).items()},
        stop_reason_counts={str(key): int(value or 0) for key, value in dict(snapshot.get("stop_reason_counts", {})).items()},
        warnings=list(run.warnings),
        errors=list(run.errors),
    )


def _failed_run(template_name: str, template_id: str | None, role: str, mode: str, error: str) -> TemplateChallengeCandidateRun:
    """실패 run placeholder를 만든다."""
    return TemplateChallengeCandidateRun(
        template_name=template_name,
        template_id=template_id,
        role=role,
        mode=mode,
        replay_ref=None,
        status="failed",
        validated_proposal_rate=None,
        human_intervention_rate=None,
        validation_autonomy_rate=None,
        median_duration_seconds=None,
        stage_counts={},
        stop_reason_counts={},
        warnings=[],
        errors=[error],
    )


def _run_status(snapshot: dict[str, Any], errors: list[str]) -> str:
    """candidate run 상태를 계산한다."""
    if errors:
        return "partial"
    if _number(snapshot.get("validated_proposal_rate")) is None:
        return "failed"
    stage_counts = snapshot.get("stage_counts") if isinstance(snapshot.get("stage_counts"), dict) else {}
    if stage_counts and set(stage_counts) == {"request_start"}:
        return "blocked"
    return "completed"


def _pairwise_for_matrix(
    runs: list[TemplateChallengeCandidateRun],
    queued: list[str],
    stable_name: str | None,
    canary_name: str | None,
) -> list[TemplateChallengePairwise]:
    """queued challenger와 stable/canary 간 pairwise 비교를 만든다."""
    pairwise: list[TemplateChallengePairwise] = []
    by_template_mode = {(run.template_name, run.mode): run for run in runs}
    modes = sorted({run.mode for run in runs})
    for challenger in queued:
        for mode in modes:
            left = by_template_mode.get((challenger, mode))
            if stable_name:
                right = by_template_mode.get((stable_name, mode))
                pairwise.append(_compare_pair(left, right, challenger, stable_name, mode))
            if canary_name and _slug(canary_name) != _slug(challenger):
                right = by_template_mode.get((canary_name, mode))
                pairwise.append(_compare_pair(left, right, challenger, canary_name, mode))
    return pairwise


def _compare_pair(
    left: TemplateChallengeCandidateRun | None,
    right: TemplateChallengeCandidateRun | None,
    left_name: str,
    right_name: str,
    mode: str,
) -> TemplateChallengePairwise:
    """두 candidate run을 threshold 기반으로 비교한다."""
    if left is None or right is None:
        return TemplateChallengePairwise(left_name, right_name, mode, "inconclusive", ["missing comparable run"], ["missing comparable run"])
    improvements = 0
    regressions = 0
    summary: list[str] = []
    warnings: list[str] = []
    for key, direction, label in [
        ("validated_proposal_rate", "higher", "validated proposal rate"),
        ("validation_autonomy_rate", "higher", "validation autonomy"),
        ("human_intervention_rate", "lower", "human intervention"),
        ("median_duration_seconds", "lower", "median duration"),
    ]:
        left_value = getattr(left, key)
        right_value = getattr(right, key)
        if left_value is None or right_value is None:
            warnings.append(f"missing comparable metric: {key}")
            continue
        delta = float(left_value) - float(right_value)
        threshold = DURATION_THRESHOLD_SECONDS if key == "median_duration_seconds" else RATE_THRESHOLD
        improved = delta >= threshold if direction == "higher" else delta <= -threshold
        regressed = delta <= -threshold if direction == "higher" else delta >= threshold
        if improved:
            improvements += 1
            summary.append(_delta_summary(label, delta, key))
        elif regressed:
            regressions += 1
            summary.append(_delta_summary(label, delta, key))
    comparable = improvements + regressions
    if comparable == 0:
        verdict = "inconclusive"
        summary.append("no meaningful metric delta")
    elif improvements > 0 and regressions == 0:
        verdict = "stronger"
    elif regressions > 0 and improvements == 0:
        verdict = "weaker"
    else:
        verdict = "mixed"
    return TemplateChallengePairwise(left_name, right_name, mode, verdict, _dedupe(summary), _dedupe(warnings))


def _rank_challengers(
    queued: list[str],
    runs: list[TemplateChallengeCandidateRun],
    pairwise: list[TemplateChallengePairwise],
) -> tuple[list[str], str | None]:
    """pairwise evidence와 metric snapshot으로 deterministic ranking을 만든다."""
    run_by_name: dict[str, list[TemplateChallengeCandidateRun]] = {
        name: [run for run in runs if _slug(run.template_name) == _slug(name)] for name in queued
    }
    pairwise_by_name: dict[str, list[TemplateChallengePairwise]] = {
        name: [item for item in pairwise if _slug(item.left_template_name) == _slug(name)] for name in queued
    }
    scored: list[tuple[float, int, float, float, float, float, str]] = []
    for name in queued:
        comparisons = pairwise_by_name.get(name, [])
        score = 0.0
        evidence = 0
        for item in comparisons:
            if item.verdict == "inconclusive":
                continue
            evidence += 1
            right_role = _right_role(item.right_template_name, runs)
            if right_role == "stable_default":
                score += {"stronger": 3.0, "mixed": 1.0, "weaker": -3.0}.get(item.verdict, 0.0)
            elif right_role == "active_canary":
                score += {"stronger": 2.0, "mixed": 0.5, "weaker": -2.0}.get(item.verdict, 0.0)
        candidates = run_by_name.get(name, [])
        validated = _mean([run.validated_proposal_rate for run in candidates])
        autonomy = _mean([run.validation_autonomy_rate for run in candidates])
        intervention = _mean([run.human_intervention_rate for run in candidates])
        duration = _mean([run.median_duration_seconds for run in candidates])
        scored.append((
            score,
            evidence,
            validated if validated is not None else -1.0,
            -(intervention if intervention is not None else 1.0),
            autonomy if autonomy is not None else -1.0,
            -(duration if duration is not None else 999999.0),
            name,
        ))
    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], -item[3], -item[4], -item[5], item[6]))
    ranked = [item[6] for item in scored]
    next_best = None
    if scored and scored[0][0] > 0 and scored[0][1] > 0:
        next_best = scored[0][6]
    return ranked, next_best


def _right_role(name: str, runs: list[TemplateChallengeCandidateRun]) -> str | None:
    """template name의 matrix role을 찾는다."""
    for run in runs:
        if _slug(run.template_name) == _slug(name):
            return run.role
    return None


def _summary(
    next_best: str | None,
    ranked: list[str],
    pairwise: list[TemplateChallengePairwise],
    warnings: list[str],
) -> list[str]:
    """matrix summary를 만든다."""
    if next_best:
        stronger = [item for item in pairwise if item.left_template_name == next_best and item.verdict == "stronger"]
        lines = [f"{next_best} is the evidence-backed next challenger"]
        if stronger:
            lines.extend([item.summary[0] for item in stronger if item.summary][:3])
        return _dedupe(lines)
    if not ranked:
        return ["no queued challenger is available for replay ranking"]
    if warnings:
        return ["challenger matrix is inconclusive because evidence is incomplete"]
    return ["queued challengers did not beat stable/canary baselines"]


def _next_actions(next_best: str | None) -> list[str]:
    """matrix 이후 가능한 명시적 액션을 제안한다."""
    if next_best:
        return [f"cambrian template challenge-stage {next_best}", "cambrian template challenge-board"]
    return ["cambrian template challengers", "cambrian template challenge-matrix --workset <workset-name> --save"]


def _template_matrix_standing(report: TemplateChallengeMatrix, template_name: str) -> str | None:
    """특정 template의 matrix standing을 반환한다."""
    wanted = _slug(template_name)
    if report.next_best_challenger and _slug(report.next_best_challenger) == wanted:
        return "top queued challenger"
    if any(_slug(name) == wanted for name in report.ranked_challengers):
        rank = next(index + 1 for index, name in enumerate(report.ranked_challengers) if _slug(name) == wanted)
        return f"queued challenger rank {rank}"
    if report.active_canary_template_name and _slug(report.active_canary_template_name) == wanted:
        if report.next_best_challenger:
            return f"current canary compared against {report.next_best_challenger}"
        return "current active canary in matrix"
    if report.stable_default_template_name and _slug(report.stable_default_template_name) == wanted:
        return "stable default baseline in matrix"
    return None


def _number(value: Any) -> float | None:
    """숫자 변환."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float | None]) -> float | None:
    """None 제외 평균."""
    known = [float(value) for value in values if value is not None]
    if not known:
        return None
    return round(sum(known) / len(known), 4)


def _delta_summary(label: str, delta: float, key: str) -> str:
    """delta summary 문구."""
    if key == "median_duration_seconds":
        return f"{label} {delta:+.0f}s"
    return f"{label} {delta:+.0%}"


def _run_from_dict(payload: dict[str, Any]) -> TemplateChallengeCandidateRun:
    """dict에서 candidate run을 복원한다."""
    return TemplateChallengeCandidateRun(
        template_name=str(payload.get("template_name") or ""),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        role=str(payload.get("role") or "queued_challenger"),
        mode=str(payload.get("mode") or "cambrian_guided"),
        replay_ref=str(payload.get("replay_ref")) if payload.get("replay_ref") is not None else None,
        status=str(payload.get("status") or "failed"),
        validated_proposal_rate=_number(payload.get("validated_proposal_rate")),
        human_intervention_rate=_number(payload.get("human_intervention_rate")),
        validation_autonomy_rate=_number(payload.get("validation_autonomy_rate")),
        median_duration_seconds=_number(payload.get("median_duration_seconds")),
        stage_counts={str(key): int(value or 0) for key, value in dict(payload.get("stage_counts", {})).items()},
        stop_reason_counts={str(key): int(value or 0) for key, value in dict(payload.get("stop_reason_counts", {})).items()},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _pairwise_from_dict(payload: dict[str, Any]) -> TemplateChallengePairwise:
    """dict에서 pairwise를 복원한다."""
    return TemplateChallengePairwise(
        left_template_name=str(payload.get("left_template_name") or ""),
        right_template_name=str(payload.get("right_template_name") or ""),
        mode=str(payload.get("mode") or "cambrian_guided"),
        verdict=str(payload.get("verdict") or "inconclusive"),
        summary=[str(item) for item in payload.get("summary", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
    )


def _matrix_from_dict(payload: dict[str, Any]) -> TemplateChallengeMatrix:
    """dict에서 challenge matrix를 복원한다."""
    return TemplateChallengeMatrix(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        report_id=str(payload.get("report_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        lane_id=str(payload.get("lane_id")) if payload.get("lane_id") is not None else None,
        lane_label=str(payload.get("lane_label")) if payload.get("lane_label") is not None else None,
        workset_name=str(payload.get("workset_name") or ""),
        stable_default_template_name=(
            str(payload.get("stable_default_template_name"))
            if payload.get("stable_default_template_name") is not None
            else None
        ),
        active_canary_template_name=(
            str(payload.get("active_canary_template_name"))
            if payload.get("active_canary_template_name") is not None
            else None
        ),
        queued_challengers=[str(item) for item in payload.get("queued_challengers", []) if item],
        candidate_runs=[_run_from_dict(item) for item in payload.get("candidate_runs", []) if isinstance(item, dict)],
        pairwise=[_pairwise_from_dict(item) for item in payload.get("pairwise", []) if isinstance(item, dict)],
        ranked_challengers=[str(item) for item in payload.get("ranked_challengers", []) if item],
        next_best_challenger=(
            str(payload.get("next_best_challenger"))
            if payload.get("next_best_challenger") is not None
            else None
        ),
        summary=[str(item) for item in payload.get("summary", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
