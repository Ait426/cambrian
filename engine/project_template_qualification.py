"""템플릿 derivative가 parent보다 나은지 안전하게 비교하는 qualification 레이어."""

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

from engine.project_benchmark_workset_replay import (
    WorksetReplayEntry,
    WorksetReplayReport,
    WorksetReplayStore,
    default_workset_replay_path,
)
from engine.project_benchmarks import BenchmarkStore, default_benchmark_dir
from engine.project_bridge import ProjectBridgeStore, default_bridge_replies_dir, resolve_bridge_reply_path
from engine.project_templates import HarnessTemplate, HarnessTemplateStore, default_templates_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
QUALIFICATION_MODES = {"cambrian_guided", "cambrian_full"}
RATE_THRESHOLD = 0.05
DURATION_THRESHOLD_SECONDS = 30.0
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".yaml", ".yml", ".json"}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명에 쓰는 UTC timestamp를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 식별자를 만든다."""
    return secrets.token_hex(2)


def _slug(value: str, fallback: str = "item") -> str:
    """사람용 이름을 파일명에 안전한 slug로 바꾼다."""
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
        logger.warning("template qualification artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """프로젝트 root 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복 문자열을 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _rate(values: list[Any]) -> float | None:
    """bool-like 값 목록을 rate로 계산한다."""
    known = [value for value in values if value is not None]
    if not known:
        return None
    return round(sum(1 for value in known if bool(value)) / len(known), 4)


def _median(values: list[Any]) -> float | None:
    """숫자 목록의 median을 계산한다."""
    numbers: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    if not numbers:
        return None
    return round(float(statistics.median(numbers)), 3)


def _count(values: list[str | None]) -> dict[str, int]:
    """문자열 카운트를 만든다."""
    counts: dict[str, int] = {}
    for value in values:
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def qualifications_dir(project_root: Path) -> Path:
    """템플릿 qualification 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "qualifications"


def default_template_qualification_path(project_root: Path, report: "TemplateQualificationReport") -> Path:
    """qualification report 기본 저장 경로."""
    return qualifications_dir(project_root) / (
        f"qualify_{_slug(report.candidate_template_name)}_vs_"
        f"{_slug(report.reference_template_name)}_{_stamp()}_{_short_id()}.yaml"
    )


def latest_template_qualification_path(project_root: Path) -> Path:
    """latest qualification pointer 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "latest_qualification.yaml"


@dataclass
class TemplateQualificationRun:
    """한 템플릿/모드 조합의 replay 결과 요약."""

    run_id: str
    created_at: str
    template_name: str
    template_id: str | None
    mode: str
    workset_name: str
    replay_report_ref: str | None
    metrics_snapshot: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class TemplateQualificationReport:
    """candidate template와 reference template의 qualification 비교 결과."""

    schema_version: str
    report_id: str
    generated_at: str
    candidate_template_name: str
    candidate_template_id: str | None
    reference_template_name: str
    reference_template_id: str | None
    workset_name: str
    modes: list[str]
    candidate_runs: list[TemplateQualificationRun]
    reference_runs: list[TemplateQualificationRun]
    verdict: str
    summary: list[str] = field(default_factory=list)
    why_candidate_stronger: list[str] = field(default_factory=list)
    where_candidate_weaker: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    source_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["candidate_runs"] = [run.to_dict() for run in self.candidate_runs]
        payload["reference_runs"] = [run.to_dict() for run in self.reference_runs]
        return payload


class TemplateQualificationBuilder:
    """same-workset parent-vs-derivative qualification report를 만든다."""

    def build(
        self,
        project_root: Path,
        candidate_template_name: str,
        workset_name: str,
        reference_template_name: str | None = None,
        modes: list[str] | None = None,
    ) -> TemplateQualificationReport:
        """candidate와 reference template를 같은 workset에서 비교한다."""
        root = Path(project_root).resolve()
        model = HarnessTemplateStore().load(default_templates_path(root))
        candidate = HarnessTemplateStore().find(model, candidate_template_name)
        reference_name = reference_template_name or _reference_from_lineage(root, candidate)
        if not reference_name:
            raise ValueError(
                "No reference template found. Use: cambrian template qualify "
                f"{candidate_template_name} --workset {workset_name} --against <template-name>"
            )
        reference = HarnessTemplateStore().find(model, reference_name)
        selected_modes = _normalize_modes(modes)
        warnings: list[str] = []
        candidate_runs: list[TemplateQualificationRun] = []
        reference_runs: list[TemplateQualificationRun] = []
        for mode in selected_modes:
            reference_runs.append(_run_template_workset(root, reference, workset_name, mode))
            candidate_runs.append(_run_template_workset(root, candidate, workset_name, mode))
        verdict, stronger, weaker, summary, verdict_warnings = _verdict(candidate_runs, reference_runs)
        warnings.extend(verdict_warnings)
        source_refs = {
            "candidate_template_ref": f".cambrian/templates/templates.yaml#{candidate.name}",
            "reference_template_ref": f".cambrian/templates/templates.yaml#{reference.name}",
            "lineage_ref": _lineage_ref(candidate),
            "candidate_replay_refs": [
                run.replay_report_ref for run in candidate_runs if run.replay_report_ref
            ],
            "reference_replay_refs": [
                run.replay_report_ref for run in reference_runs if run.replay_report_ref
            ],
        }
        return TemplateQualificationReport(
            schema_version=SCHEMA_VERSION,
            report_id=f"template-qualification-{_slug(candidate.name)}-{_short_id()}",
            generated_at=_now(),
            candidate_template_name=candidate.name,
            candidate_template_id=candidate.template_id,
            reference_template_name=reference.name,
            reference_template_id=reference.template_id,
            workset_name=workset_name,
            modes=selected_modes,
            candidate_runs=candidate_runs,
            reference_runs=reference_runs,
            verdict=verdict,
            summary=summary,
            why_candidate_stronger=stronger,
            where_candidate_weaker=weaker,
            next_actions=_next_actions(candidate.name, reference.name, workset_name, verdict),
            source_refs=source_refs,
            warnings=_dedupe(warnings + [warning for run in candidate_runs + reference_runs for warning in run.warnings]),
            errors=_dedupe([error for run in candidate_runs + reference_runs for error in run.errors]),
        )


class TemplateQualificationStore:
    """qualification report 저장소."""

    def save(self, report: TemplateQualificationReport, path: Path) -> Path:
        """qualification report를 저장하고 latest pointer를 갱신한다."""
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent.parent / "latest_qualification.yaml", report.to_dict())
        return saved

    def load(self, path: Path) -> TemplateQualificationReport:
        """qualification report를 읽는다."""
        return _report_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, directory: Path) -> list[TemplateQualificationReport]:
        """저장된 qualification report를 최신순으로 나열한다."""
        reports: list[TemplateQualificationReport] = []
        for path in sorted(Path(directory).glob("qualify_*.yaml")):
            payload = _load_yaml(path)
            if payload:
                reports.append(_report_from_dict(payload))
        reports.sort(key=lambda item: item.generated_at, reverse=True)
        return reports


def resolve_template_qualification_path(project_root: Path, qualification_ref: str) -> Path:
    """qualification id 또는 path를 실제 경로로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(qualification_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in qualifications_dir(root).glob("qualify_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == qualification_ref or str(payload.get("report_id") or "") == qualification_ref:
            return path.resolve()
    raise FileNotFoundError(f"template qualification not found: {qualification_ref}")


def load_latest_template_qualification_summary(project_root: Path, template_name: str | None = None) -> dict[str, Any]:
    """status/show/board에서 쓰는 최신 qualification 요약."""
    root = Path(project_root).resolve()
    reports = TemplateQualificationStore().list(qualifications_dir(root))
    if template_name:
        wanted = _slug(template_name)
        reports = [
            report for report in reports
            if _slug(report.candidate_template_name) == wanted
        ]
    if not reports:
        return {}
    report = reports[0]
    return {
        "report_id": report.report_id,
        "candidate_template_name": report.candidate_template_name,
        "reference_template_name": report.reference_template_name,
        "workset_name": report.workset_name,
        "verdict": report.verdict,
        "why": list(report.why_candidate_stronger[:3]),
        "warnings": list(report.warnings[:3]),
    }


def render_template_qualification(report: TemplateQualificationReport, saved_path: str | None = None) -> str:
    """qualification report를 사람이 읽기 좋게 렌더링한다."""
    lines = [
        "Template Qualification",
        "==================================================",
        "",
        "Candidate:",
        f"  {report.candidate_template_name}",
        "",
        "Against:",
        f"  {report.reference_template_name}",
        "",
        "Workset:",
        f"  {report.workset_name}",
        "",
        "Verdict:",
        f"  {report.verdict}",
    ]
    if report.why_candidate_stronger:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {item}" for item in report.why_candidate_stronger[:5]])
    if report.where_candidate_weaker:
        lines.extend(["", "Where still weaker:"])
        lines.extend([f"  - {item}" for item in report.where_candidate_weaker[:5]])
    lines.extend(["", "Mode summaries:"])
    by_ref = {run.mode: run for run in report.reference_runs}
    by_candidate = {run.mode: run for run in report.candidate_runs}
    for mode in report.modes:
        ref = by_ref.get(mode)
        cand = by_candidate.get(mode)
        lines.append(f"  {mode}:")
        lines.append(f"    reference validated : {_pct(_metric(ref, 'validated_proposal_rate'))}")
        lines.append(f"    candidate validated : {_pct(_metric(cand, 'validated_proposal_rate'))}")
        lines.append(f"    reference intervention: {_pct(_metric(ref, 'human_intervention_rate'))}")
        lines.append(f"    candidate intervention: {_pct(_metric(cand, 'human_intervention_rate'))}")
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in report.next_actions[:3]])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings[:5]])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors[:5]])
    return "\n".join(lines)


def render_template_qualification_summary(summary: dict[str, Any]) -> str:
    """템플릿 show/status용 qualification 요약."""
    if not summary:
        return "Qualification:\n  none"
    lines = [
        "Qualification:",
        f"  {summary.get('verdict') or 'unknown'} vs {summary.get('reference_template_name') or 'reference'}",
        f"  workset: {summary.get('workset_name') or 'unknown'}",
    ]
    why = [str(item) for item in summary.get("why", []) if item]
    if why:
        lines.append(f"  reason : {why[0]}")
    return "\n".join(lines)


def render_template_lineage(root: Path, template: HarnessTemplate, qualification: dict[str, Any]) -> str:
    """템플릿 라인리지와 최신 qualification 요약을 렌더링한다."""
    parent = _reference_from_lineage(root, template)
    lines = [
        "Template Lineage",
        "==================================================",
        "",
        "Template:",
        f"  {template.name}",
        "",
        "Parent:",
        f"  {parent or 'unknown'}",
    ]
    origin = template.source_origin if isinstance(template.source_origin, dict) else {}
    root_name = origin.get("root_template_name") or origin.get("root_template") or origin.get("root")
    if root_name:
        lines.extend(["", "Root:", f"  {root_name}"])
    if qualification:
        lines.extend(["", "Latest qualification:"])
        lines.append(
            f"  {qualification.get('verdict') or 'unknown'} on "
            f"{qualification.get('workset_name') or 'unknown'}"
        )
    else:
        lines.extend(["", "Latest qualification:", "  none"])
    return "\n".join(lines)


def _run_template_workset(
    root: Path,
    template: HarnessTemplate,
    workset_name: str,
    mode: str,
    source_mode: str = "qualification_override",
) -> TemplateQualificationRun:
    """템플릿 override를 replay context 안에서만 적용해 workset replay를 만든다."""
    store = BenchmarkStore()
    workset = store.load_workset(store.resolve_workset_path(root, workset_name))
    raw_template = _raw_template_payload(root, template.name)
    entries: list[WorksetReplayEntry] = []
    warnings = list(workset.warnings)
    errors: list[str] = []
    for case_ref in workset.case_ids:
        try:
            case = store.load_case(store.resolve_case_path(root, case_ref))
            entries.append(_entry_for_case(root, case, template, raw_template, workset.name, mode, source_mode))
        except Exception as exc:
            message = f"case replay failed for {case_ref}: {exc}"
            logger.warning(message)
            entries.append(
                WorksetReplayEntry(
                    case_id=str(case_ref),
                    case_name=str(case_ref),
                    mode=mode,
                    replay_ref=None,
                    status="failed",
                    autonomy_stage_reached=None,
                    stop_reason=message,
                    validated_proposal=None,
                    validation_autonomy=None,
                    human_intervention=None,
                    duration_seconds=None,
                    warnings=[],
                    errors=[message],
                )
            )
            errors.append(message)
    report = _workset_report_from_entries(workset.name, mode, template, entries, warnings, errors, source_mode)
    replay_path = WorksetReplayStore().save(report, default_workset_replay_path(root, report))
    replay_ref = _relative(replay_path, root)
    metrics = dict(report.summary)
    metrics["stage_counts"] = dict(report.stage_counts)
    metrics["stop_reason_counts"] = dict(report.stop_reason_counts)
    metrics["template_context"] = {
        "source_mode": source_mode,
        "template_name": template.name,
        "template_id": template.template_id,
    }
    return TemplateQualificationRun(
        run_id=f"template-qualification-run-{_slug(template.name)}-{mode}-{_short_id()}",
        created_at=_now(),
        template_name=template.name,
        template_id=template.template_id,
        mode=mode,
        workset_name=workset.name,
        replay_report_ref=replay_ref,
        metrics_snapshot=metrics,
        warnings=_dedupe(warnings),
        errors=_dedupe(errors),
    )


def _entry_for_case(
    root: Path,
    case: Any,
    template: HarnessTemplate,
    raw_template: dict[str, Any],
    workset_name: str,
    mode: str,
    source_mode: str = "qualification_override",
) -> WorksetReplayEntry:
    context = _resolve_context(root, case, raw_template)
    if not context["success"]:
        return WorksetReplayEntry(
            case_id=case.case_id,
            case_name=case.name,
            mode=mode,
            replay_ref=None,
            status="blocked",
            autonomy_stage_reached="request_start",
            stop_reason=context["reason"],
            validated_proposal=False,
            validation_autonomy=False,
            human_intervention=False,
            duration_seconds=12.0,
            warnings=list(context["warnings"]),
            errors=[],
        )
    if mode == "cambrian_full" and _has_bridge_patch_candidate(root, case):
        stage = "proposal_validated"
        status = "completed"
        stop_reason = None
        validated = True
    else:
        stage = "diagnosed"
        status = "partial"
        stop_reason = (
            "bridge patch candidate missing"
            if mode == "cambrian_full"
            else "guided replay stops before patch validation"
        )
        validated = False
    context_defaults = _context_defaults(raw_template)
    duration = 9.0
    if context_defaults.get("preferred_context_paths") or context_defaults.get("preferred_test_paths"):
        duration = 6.0
    policy = raw_template.get("policy_defaults") if isinstance(raw_template.get("policy_defaults"), dict) else {}
    if policy.get("test_first_practice") or policy.get("narrow_change_scope"):
        duration = max(1.0, duration - 1.0)
    warnings = list(context["warnings"])
    warnings.append(
        f"template override used only for {source_mode}: {template.name}"
    )
    return WorksetReplayEntry(
        case_id=case.case_id,
        case_name=case.name,
        mode=mode,
        replay_ref=None,
        status=status,
        autonomy_stage_reached=stage,
        stop_reason=stop_reason,
        validated_proposal=validated,
        validation_autonomy=validated,
        human_intervention=False,
        duration_seconds=duration,
        warnings=_dedupe(warnings),
        errors=[],
    )


def _workset_report_from_entries(
    workset_name: str,
    mode: str,
    template: HarnessTemplate,
    entries: list[WorksetReplayEntry],
    warnings: list[str],
    errors: list[str],
    source_mode: str = "qualification_override",
) -> WorksetReplayReport:
    stage_counts = _count([entry.autonomy_stage_reached for entry in entries])
    stop_reason_counts = _count([entry.stop_reason for entry in entries])
    summary = {
        "validated_proposal_rate": _rate([entry.validated_proposal for entry in entries]),
        "validation_autonomy_rate": _rate([entry.validation_autonomy for entry in entries]),
        "human_intervention_rate": _rate([entry.human_intervention for entry in entries]),
        "median_duration_seconds": _median([entry.duration_seconds for entry in entries]),
        "template_context": {
            "source_mode": source_mode,
            "template_name": template.name,
            "template_id": template.template_id,
        },
    }
    report = WorksetReplayReport(
        schema_version=SCHEMA_VERSION,
        replay_id=f"template-qualification-replay-{_slug(workset_name)}-{_slug(template.name)}-{_short_id()}",
        created_at=_now(),
        workset_name=workset_name,
        mode=mode,
        total_cases=len(entries),
        entries=entries,
        stage_counts=stage_counts,
        stop_reason_counts=stop_reason_counts,
        summary=summary,
        warnings=_dedupe(warnings + [warning for entry in entries for warning in entry.warnings]),
        errors=_dedupe(errors + [error for entry in entries for error in entry.errors]),
    )
    return report


def _resolve_context(root: Path, case: Any, raw_template: dict[str, Any]) -> dict[str, Any]:
    hints = case.replay_hints if isinstance(case.replay_hints, dict) else {}
    warnings: list[str] = []
    source_hint = str(hints.get("source_path_hint") or hints.get("target_path") or "").strip()
    test_hint = str(hints.get("test_path_hint") or "").strip()
    context_defaults = _context_defaults(raw_template)
    source_candidates = _safe_existing_paths(root, [source_hint])
    test_candidates = _safe_existing_paths(root, [test_hint])
    source_from_template = _safe_existing_paths(root, context_defaults.get("preferred_context_paths", []))
    test_from_template = _safe_existing_paths(root, context_defaults.get("preferred_test_paths", []))
    if not source_candidates and source_from_template:
        source_candidates = source_from_template
        warnings.append("context selected from qualification template override")
    if not test_candidates and test_from_template:
        test_candidates = test_from_template
    if not source_candidates:
        scanned = _scan_source_candidates(root, case)
        if len(scanned) == 1:
            source_candidates = scanned
        elif len(scanned) > 1:
            return {
                "success": False,
                "reason": "ambiguous source selection",
                "warnings": [f"multiple source candidates: {', '.join(scanned[:5])}"],
            }
        else:
            return {
                "success": False,
                "reason": "no safe context candidate",
                "warnings": warnings,
            }
    if len(source_candidates) > 1:
        return {
            "success": False,
            "reason": "ambiguous source selection",
            "warnings": [f"multiple source candidates: {', '.join(source_candidates[:5])}"],
        }
    return {
        "success": True,
        "reason": "context selected",
        "source_paths": source_candidates,
        "test_paths": test_candidates,
        "warnings": warnings,
    }


def _safe_existing_paths(root: Path, candidates: list[Any]) -> list[str]:
    paths: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip().replace("\\", "/")
        if not text:
            continue
        path = (root / text).resolve()
        if _is_safe_project_path(root, path) and path.exists():
            paths.append(text)
    return _dedupe(paths)


def _scan_source_candidates(root: Path, case: Any) -> list[str]:
    tokens = _tokens(" ".join([case.request, case.case_id, case.name, " ".join(case.tags), " ".join(case.expected_focus)]))
    candidates: list[tuple[int, str]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        rel = _relative(path, root)
        if rel.startswith(".cambrian/") or rel.startswith(".git/") or rel.startswith(".pytest_cache/") or rel.startswith("__pycache__/"):
            continue
        lowered = rel.lower()
        score = sum(1 for token in tokens if token in lowered)
        if score > 0:
            candidates.append((score, rel))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (-item[0], item[1]))
    best_score = candidates[0][0]
    return [rel for score, rel in candidates if score == best_score]


def _has_bridge_patch_candidate(root: Path, case: Any) -> bool:
    hints = case.replay_hints if isinstance(case.replay_hints, dict) else {}
    reply_ref = str(hints.get("bridge_reply_ref") or hints.get("linked_bridge_reply_ref") or "").strip()
    if reply_ref:
        try:
            return resolve_bridge_reply_path(root, reply_ref).exists()
        except FileNotFoundError:
            return False
    replies = sorted(default_bridge_replies_dir(root).glob("reply_*.yaml"), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    for path in replies:
        try:
            reply = ProjectBridgeStore().load_reply(path)
        except Exception as exc:
            logger.warning("bridge reply load failed during qualification: %s", exc)
            continue
        if reply.response_kind == "patch_candidate" and (reply.request == case.request or not reply.request):
            return True
    return False


def _context_defaults(raw_template: dict[str, Any]) -> dict[str, list[str]]:
    defaults = raw_template.get("context_defaults")
    if not isinstance(defaults, dict):
        defaults = raw_template.get("qualification_context")
    if not isinstance(defaults, dict):
        return {"preferred_context_paths": [], "preferred_test_paths": []}
    return {
        "preferred_context_paths": [str(item) for item in defaults.get("preferred_context_paths", []) if item],
        "preferred_test_paths": [str(item) for item in defaults.get("preferred_test_paths", []) if item],
    }


def _tokens(text: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[0-9A-Za-z가-힣]+", text) if len(token) >= 2]
    stop = {"fix", "bug", "test", "tests", "with", "this", "that", "work", "case"}
    return _dedupe([token for token in tokens if token not in stop])


def _is_safe_project_path(root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    parts = {part.lower() for part in rel.parts}
    return ".git" not in parts and ".cambrian" not in parts


def _normalize_modes(modes: list[str] | None) -> list[str]:
    if not modes:
        return ["cambrian_guided", "cambrian_full"]
    normalized: list[str] = []
    mapping = {"guided": "cambrian_guided", "full": "cambrian_full", "both": "both"}
    for mode in modes:
        token = mapping.get(str(mode), str(mode))
        if token == "both":
            normalized.extend(["cambrian_guided", "cambrian_full"])
        elif token in QUALIFICATION_MODES:
            normalized.append(token)
        else:
            raise ValueError(f"unsupported qualification mode: {mode}")
    return _dedupe(normalized)


def _reference_from_lineage(root: Path, template: HarnessTemplate) -> str | None:
    raw = _raw_template_payload(root, template.name)
    origin = dict(template.source_origin or {})
    lineage = raw.get("lineage") if isinstance(raw.get("lineage"), dict) else {}
    candidates = [
        lineage.get("parent_template_name"),
        lineage.get("parent_template"),
        lineage.get("parent_name"),
        origin.get("parent_template_name"),
        origin.get("parent_template"),
        origin.get("parent_name"),
        origin.get("forked_from"),
        lineage.get("root_template_name"),
        lineage.get("root_template"),
        origin.get("root_template_name"),
        origin.get("root_template"),
        origin.get("source_template_name"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and text != template.name:
            return text
    return None


def _lineage_ref(template: HarnessTemplate) -> str | None:
    if template.source_origin:
        return f".cambrian/templates/templates.yaml#{template.name}.source_origin"
    return None


def _raw_template_payload(root: Path, template_name: str) -> dict[str, Any]:
    payload = _load_yaml(default_templates_path(root))
    wanted = _slug(template_name)
    for item in payload.get("templates", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") == template_name or _slug(str(item.get("template_id") or "")) == wanted:
            return dict(item)
    return {}


def _verdict(
    candidate_runs: list[TemplateQualificationRun],
    reference_runs: list[TemplateQualificationRun],
) -> tuple[str, list[str], list[str], list[str], list[str]]:
    warnings: list[str] = []
    candidate_by_mode = {run.mode: run for run in candidate_runs}
    reference_by_mode = {run.mode: run for run in reference_runs}
    common_modes = sorted(set(candidate_by_mode) & set(reference_by_mode))
    if not common_modes:
        return "inconclusive", [], [], ["no comparable replay modes"], ["no comparable replay modes"]
    improvements = 0
    regressions = 0
    stronger: list[str] = []
    weaker: list[str] = []
    comparable_fields = 0
    for mode in common_modes:
        cand = candidate_by_mode[mode].metrics_snapshot
        ref = reference_by_mode[mode].metrics_snapshot
        for key, direction, label in [
            ("validated_proposal_rate", "higher", "validated proposal rate"),
            ("validation_autonomy_rate", "higher", "validation autonomy"),
            ("human_intervention_rate", "lower", "human intervention"),
            ("median_duration_seconds", "lower", "median duration"),
        ]:
            cand_value = _number(cand.get(key))
            ref_value = _number(ref.get(key))
            if cand_value is None or ref_value is None:
                warnings.append(f"{mode} missing comparable field: {key}")
                continue
            comparable_fields += 1
            delta = cand_value - ref_value
            threshold = DURATION_THRESHOLD_SECONDS if key == "median_duration_seconds" else RATE_THRESHOLD
            improved = delta >= threshold if direction == "higher" else delta <= -threshold
            regressed = delta <= -threshold if direction == "higher" else delta >= threshold
            if improved:
                improvements += 1
                stronger.append(_delta_summary(mode, label, delta, key))
            elif regressed:
                regressions += 1
                weaker.append(_delta_summary(mode, label, delta, key))
    if comparable_fields < 3:
        return "inconclusive", stronger, weaker, ["insufficient comparable metrics"], _dedupe(warnings + ["insufficient comparable metrics"])
    if improvements > 0 and regressions == 0:
        verdict = "candidate_stronger"
    elif regressions > 0 and improvements == 0:
        verdict = "regressed"
    elif improvements > 0 and regressions > 0:
        verdict = "mixed"
    else:
        verdict = "inconclusive"
        warnings.append("candidate and reference were effectively tied")
    summary = _summary_for_verdict(verdict, stronger, weaker)
    return verdict, _dedupe(stronger), _dedupe(weaker), summary, _dedupe(warnings)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _delta_summary(mode: str, label: str, delta: float, key: str) -> str:
    if key == "median_duration_seconds":
        return f"{mode}: {label} {delta:+.0f}s"
    return f"{mode}: {label} {delta:+.0%}"


def _summary_for_verdict(verdict: str, stronger: list[str], weaker: list[str]) -> list[str]:
    if verdict == "candidate_stronger":
        return ["candidate template is stronger than reference on comparable replay metrics"]
    if verdict == "regressed":
        return ["candidate template regressed against reference on comparable replay metrics"]
    if verdict == "mixed":
        return ["candidate template improved some metrics but regressed others"]
    return ["qualification data is insufficient or tied"]


def _next_actions(candidate_name: str, reference_name: str, workset_name: str, verdict: str) -> list[str]:
    if verdict == "candidate_stronger":
        return [
            f"cambrian template promote {candidate_name}",
            f"cambrian template board",
            f"cambrian benchmark proof {workset_name}",
        ]
    if verdict == "regressed":
        return [
            f"cambrian template watch {candidate_name}",
            f"cambrian template show {reference_name}",
        ]
    return [
        f"cambrian template evolve {candidate_name}",
        f"cambrian template qualify {candidate_name} --workset {workset_name} --against {reference_name}",
    ]


def _metric(run: TemplateQualificationRun | None, key: str) -> Any:
    if run is None:
        return None
    return run.metrics_snapshot.get(key)


def _pct(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "n/a"
    return f"{number:.0%}"


def _run_from_dict(payload: dict[str, Any]) -> TemplateQualificationRun:
    return TemplateQualificationRun(
        run_id=str(payload.get("run_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        template_name=str(payload.get("template_name") or ""),
        template_id=str(payload.get("template_id")) if payload.get("template_id") is not None else None,
        mode=str(payload.get("mode") or "cambrian_guided"),
        workset_name=str(payload.get("workset_name") or ""),
        replay_report_ref=str(payload.get("replay_report_ref")) if payload.get("replay_report_ref") is not None else None,
        metrics_snapshot=dict(payload.get("metrics_snapshot", {}) if isinstance(payload.get("metrics_snapshot"), dict) else {}),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _report_from_dict(payload: dict[str, Any]) -> TemplateQualificationReport:
    return TemplateQualificationReport(
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        report_id=str(payload.get("report_id") or ""),
        generated_at=str(payload.get("generated_at") or ""),
        candidate_template_name=str(payload.get("candidate_template_name") or ""),
        candidate_template_id=str(payload.get("candidate_template_id")) if payload.get("candidate_template_id") is not None else None,
        reference_template_name=str(payload.get("reference_template_name") or ""),
        reference_template_id=str(payload.get("reference_template_id")) if payload.get("reference_template_id") is not None else None,
        workset_name=str(payload.get("workset_name") or ""),
        modes=[str(item) for item in payload.get("modes", []) if item],
        candidate_runs=[_run_from_dict(item) for item in payload.get("candidate_runs", []) if isinstance(item, dict)],
        reference_runs=[_run_from_dict(item) for item in payload.get("reference_runs", []) if isinstance(item, dict)],
        verdict=str(payload.get("verdict") or "inconclusive"),
        summary=[str(item) for item in payload.get("summary", []) if item],
        why_candidate_stronger=[str(item) for item in payload.get("why_candidate_stronger", []) if item],
        where_candidate_weaker=[str(item) for item in payload.get("where_candidate_weaker", []) if item],
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        source_refs=dict(payload.get("source_refs", {}) if isinstance(payload.get("source_refs"), dict) else {}),
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
