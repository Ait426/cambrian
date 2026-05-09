"""Cambrian 운영 지표 주간 대시보드."""

from __future__ import annotations

import json
import logging
import statistics
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


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
    """YAML/JSON artifact를 안전하게 읽는다."""
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        logger.warning("metrics artifact load failed: %s (%s)", path, exc)
        return {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("metrics artifact ignored: top level is not mapping: %s", path)
        return {}
    return payload


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _parse_datetime(value: Any) -> datetime | None:
    """ISO 문자열 또는 날짜 문자열을 datetime으로 변환한다."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raw = str(value).strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(raw), time.min)
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_date_boundary(value: str | None, *, end: bool = False) -> datetime | None:
    """CLI 날짜 경계를 UTC datetime으로 변환한다."""
    if not value:
        return None
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    if len(str(value).strip()) <= 10:
        base = parsed.date()
        if end:
            return datetime.combine(base + timedelta(days=1), time.min, tzinfo=timezone.utc)
        return datetime.combine(base, time.min, tzinfo=timezone.utc)
    return parsed


def _current_week_range() -> tuple[datetime, datetime, str]:
    """현재 ISO week 범위를 반환한다."""
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=7)
    iso = today.isocalendar()
    return start_dt, end_dt, f"{iso.year}_W{iso.week:02d}"


def _in_range(created_at: datetime | None, start_dt: datetime | None, end_dt: datetime | None) -> bool:
    """artifact 시각이 선택된 기간에 포함되는지 확인한다."""
    if created_at is None:
        return True
    if start_dt is not None and created_at < start_dt:
        return False
    if end_dt is not None and created_at >= end_dt:
        return False
    return True


def _bool(value: Any) -> bool:
    """artifact 값의 운영상 true 여부를 보수적으로 해석한다."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "passed", "adopted", "applied"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


def _rate(numerator: int, denominator: int) -> float | None:
    """분모가 없으면 None, 있으면 0~1 rate를 반환한다."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _median(values: list[float]) -> float | None:
    """값이 있으면 median을 반환한다."""
    if not values:
        return None
    return round(float(statistics.median(values)), 3)


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _request_class(intent_type: str | None) -> str:
    """router intent를 metrics용 request_class로 정규화한다."""
    mapping = {
        "bug_fix": "bug_fix",
        "docs_update": "docs",
        "review_candidate": "review",
        "small_refactor": "refactor",
        "test_generation": "test",
    }
    return mapping.get(str(intent_type or "").strip(), "unknown")


def build_request_metrics_context(
    *,
    request_id: str,
    created_at: str,
    intent_type: str | None,
    memory_context: dict[str, Any] | None,
    harness_policy_context: dict[str, Any] | None,
    team_policy_context: dict[str, Any] | None,
    template_context: dict[str, Any] | None,
    bridge_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """request artifact에 들어갈 최소 metrics_context를 만든다."""
    memory_context = memory_context if isinstance(memory_context, dict) else {}
    harness_policy_context = harness_policy_context if isinstance(harness_policy_context, dict) else {}
    team_policy_context = team_policy_context if isinstance(team_policy_context, dict) else {}
    template_context = template_context if isinstance(template_context, dict) else {}
    bridge_context = bridge_context if isinstance(bridge_context, dict) else {}
    return {
        "request_id": request_id,
        "request_class": _request_class(intent_type),
        "request_started_at": created_at,
        "reused_context": {
            "memory": bool(memory_context.get("relevant_lessons") or memory_context.get("top_lessons")),
            "harness_policy": bool(harness_policy_context.get("applied_hints") or harness_policy_context.get("hints")),
            "team_policy": bool(team_policy_context.get("applied_hints") or team_policy_context.get("current_team_name")),
            "template": bool(template_context.get("current_template") or template_context.get("template_name") or template_context.get("applied_hints")),
            "bridge": bool(bridge_context.get("enabled") or bridge_context.get("context_hint")),
        },
    }


def build_session_metrics_context(
    *,
    session_created_at: str,
    lead_agent_id: str | None = None,
    team_id: str | None = None,
    template_name: str | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """session artifact에 들어갈 기본 metrics_context를 만든다."""
    base = dict(existing or {})
    human = dict(base.get("human_interventions", {})) if isinstance(base.get("human_interventions"), dict) else {}
    milestones = dict(base.get("milestones", {})) if isinstance(base.get("milestones"), dict) else {}
    results = dict(base.get("results", {})) if isinstance(base.get("results"), dict) else {}
    for key in (
        "source_selected_manually",
        "test_selected_manually",
        "old_text_overridden",
        "new_text_overridden",
        "explicit_agent_override",
        "explicit_team_override",
        "explicit_template_choice",
        "bridge_manual_ingest",
    ):
        human.setdefault(key, False)
    milestones.setdefault("request_started_at", session_created_at)
    milestones.setdefault("diagnosed_at", None)
    milestones.setdefault("patch_intent_ready_at", None)
    milestones.setdefault("proposal_validated_at", None)
    milestones.setdefault("applied_at", None)
    results.setdefault("validated_proposal", False)
    results.setdefault("adoption_succeeded", False)
    results.setdefault("apply_tests_passed", False)
    base.update(
        {
            "lead_agent_id": lead_agent_id or base.get("lead_agent_id"),
            "final_lead_agent_id": base.get("final_lead_agent_id") or lead_agent_id,
            "team_id": team_id or base.get("team_id"),
            "template_name": template_name or base.get("template_name"),
            "human_interventions": human,
            "milestones": milestones,
            "results": results,
        }
    )
    return base


def default_metrics_dir(project_root: Path) -> Path:
    """metrics report 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "metrics"


def default_weekly_metrics_path(project_root: Path, week_id: str) -> Path:
    """week_id에 맞는 weekly metrics report 경로."""
    return default_metrics_dir(project_root) / f"weekly_{week_id}.yaml"


@dataclass
class WeeklyMetric:
    key: str
    value: float | int | str | None
    unit: str | None
    summary: str
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WeeklyMetricsReport:
    schema_version: str
    generated_at: str
    week_id: str
    project_name: str | None
    workspace: str
    metrics: list[WeeklyMetric]
    summary: dict[str, Any]
    counts: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = [metric.to_dict() for metric in self.metrics]
        return payload


@dataclass
class _Artifact:
    path: Path
    payload: dict[str, Any]
    created_at: datetime | None


class ProjectMetricsBuilder:
    """로컬 artifact를 스캔해 주간 운영 지표를 계산한다."""

    def build_week(
        self,
        project_root: Path,
        start: str | None = None,
        end: str | None = None,
    ) -> WeeklyMetricsReport:
        """선택된 주간 범위의 metrics report를 만든다."""
        root = Path(project_root).resolve()
        default_start, default_end, default_week_id = _current_week_range()
        start_dt = _parse_date_boundary(start) if start else default_start
        end_dt = _parse_date_boundary(end, end=True) if end else default_end
        week_id = self._week_id(start_dt, default_week_id)
        warnings: list[str] = []
        errors: list[str] = []

        requests = self._load_artifacts(root / ".cambrian" / "requests", ("request_*.yaml",), start_dt, end_dt)
        sessions = self._load_artifacts(root / ".cambrian" / "sessions", ("do_session_*.yaml",), start_dt, end_dt)
        proposals = self._load_artifacts(root / ".cambrian" / "patches", ("patch_proposal_*.yaml",), start_dt, end_dt)
        adoptions = self._load_artifacts(root / ".cambrian" / "adoptions", ("*.json", "*.yaml", "*.yml"), start_dt, end_dt, exclude_names={"_latest.json", "_latest.yaml", "_latest.yml"})

        request_index = self._request_index(requests)
        session_links = self._session_links(sessions, request_index)
        proposal_links = self._proposal_links(proposals, request_index, session_links)
        adoption_links = self._adoption_links(adoptions, proposals, request_index, proposal_links)

        total_requests = len(request_index)
        validated_request_ids = self._validated_request_ids(sessions, proposals, proposal_links, request_index)
        validated_proposals = [item for item in proposals if self._proposal_validated(item.payload)]
        adopted_results = [item for item in adoptions if str(item.payload.get("adoption_status", "")).lower() in {"adopted", "applied"}]
        applies = [item for item in adoptions if item.payload.get("post_apply_tests") is not None or str(item.payload.get("adoption_status", "")).lower() in {"adopted", "applied"}]
        regression_free = [item for item in applies if self._apply_tests_passed(item.payload)]

        human_intervention_ids = self._human_intervention_request_ids(sessions, session_links)
        validation_autonomy_ids = self._validation_autonomy_request_ids(sessions, session_links, validated_request_ids)
        agent_routed_sessions = [item for item in sessions if self._lead_agent_id(item.payload)]
        lead_hits = [item for item in agent_routed_sessions if self._lead_agent_hit(item.payload)]
        recommendation_hit_rate, recommendation_counts = self._team_template_recommendation_hit_rate(root)
        reuse_lift = self._reuse_lift(request_index, validated_request_ids, adoption_links)
        repeat_improvement, repeat_counts = self._repeat_task_improvement(request_index, validated_request_ids, sessions, session_links)
        median_seconds = self._median_time_to_validated(request_index, sessions, proposals, session_links, proposal_links)

        counts = {
            "total_requests": total_requests,
            "validated_requests": len(validated_request_ids),
            "validated_proposals": len(validated_proposals),
            "adopted_results": len(adopted_results),
            "applies": len(applies),
            "agent_routed_requests": len(agent_routed_sessions),
            "reused_requests": self._reused_request_count(request_index),
            "repeated_task_groups": repeat_counts.get("groups", 0),
            "team_template_recommendations": recommendation_counts.get("recommendations", 0),
            "team_template_hits": recommendation_counts.get("hits", 0),
        }
        summary = {
            "validated_proposal_rate": _rate(len(validated_request_ids), total_requests),
            "adoption_rate": _rate(len(adopted_results), len(validated_proposals)),
            "regression_free_apply_rate": _rate(len(regression_free), len(applies)),
            "median_time_to_validated_proposal": median_seconds,
            "human_intervention_rate": _rate(len(human_intervention_ids), total_requests),
            "validation_autonomy_rate": _rate(len(validation_autonomy_ids), total_requests),
            "lead_agent_hit_rate": _rate(len(lead_hits), len(agent_routed_sessions)),
            "team_template_recommendation_hit_rate": recommendation_hit_rate,
            "reuse_lift": reuse_lift,
            "repeat_task_improvement_rate": repeat_improvement.get("success_rate_delta"),
            "repeat_task_time_delta_seconds": repeat_improvement.get("median_time_delta_seconds"),
        }
        try:
            from engine.project_autonomy_bottlenecks import load_latest_bottleneck_summary

            bottleneck_summary = load_latest_bottleneck_summary(root)
            if bottleneck_summary:
                summary["latest_autonomy_bottleneck"] = bottleneck_summary.get("top_bottleneck")
                summary["latest_autonomy_next_fix"] = bottleneck_summary.get("top_suggestion")
        except Exception as exc:
            message = f"latest autonomy bottleneck summary load failed: {exc}"
            logger.warning(message)
            warnings.append(message)
        try:
            from engine.project_improvement_interventions import active_intervention_summary
            from engine.project_improvement_decisions import kept_improvements_summary

            intervention_summary = active_intervention_summary(root)
            if intervention_summary:
                summary["active_intervention_ref"] = intervention_summary.get("source_intervention_ref")
                summary["active_intervention_id"] = intervention_summary.get("active_intervention_id")
                summary["active_intervention_kind"] = intervention_summary.get("active_intervention_kind")
            kept_summary = kept_improvements_summary(root)
            if kept_summary:
                summary["kept_intervention_ids"] = kept_summary.get("kept_intervention_ids")
                summary["kept_intervention_count"] = kept_summary.get("kept_count")
                summary["kept_improvement_kinds"] = kept_summary.get("kept_fix_kinds")
        except Exception as exc:
            message = f"active improvement intervention summary load failed: {exc}"
            logger.warning(message)
            warnings.append(message)
        if total_requests == 0:
            warnings.append("no request artifacts found in selected week")
        if len(validated_proposals) == 0:
            warnings.append("no validated proposal artifacts found")
        if recommendation_counts.get("recommendations", 0) == 0:
            warnings.append("no team/template recommendation artifacts found")
        metrics = self._metrics_from_summary(summary, counts)
        project_name = self._project_name(root)
        return WeeklyMetricsReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            week_id=week_id,
            project_name=project_name,
            workspace=str(root),
            metrics=metrics,
            summary=summary,
            counts=counts,
            warnings=_dedupe(warnings),
            errors=errors,
        )

    @staticmethod
    def _week_id(start_dt: datetime | None, fallback: str) -> str:
        if start_dt is None:
            return fallback
        iso = start_dt.date().isocalendar()
        return f"{iso.year}_W{iso.week:02d}"

    @staticmethod
    def _project_name(root: Path) -> str | None:
        payload = _load_any(root / ".cambrian" / "project.yaml")
        project = payload.get("project") if isinstance(payload.get("project"), dict) else payload
        name = project.get("name") if isinstance(project, dict) else None
        return str(name) if name else root.name

    @staticmethod
    def _load_artifacts(
        directory: Path,
        patterns: tuple[str, ...],
        start_dt: datetime | None,
        end_dt: datetime | None,
        *,
        exclude_names: set[str] | None = None,
    ) -> list[_Artifact]:
        artifacts: list[_Artifact] = []
        exclude_names = exclude_names or set()
        if not directory.exists():
            return artifacts
        for pattern in patterns:
            for path in sorted(directory.glob(pattern)):
                if path.name in exclude_names or path.is_dir():
                    continue
                payload = _load_any(path)
                if not payload:
                    continue
                created = _parse_datetime(payload.get("created_at") or payload.get("updated_at"))
                if _in_range(created, start_dt, end_dt):
                    artifacts.append(_Artifact(path=path, payload=payload, created_at=created))
        artifacts.sort(key=lambda item: (item.created_at or datetime.min.replace(tzinfo=timezone.utc), item.path.name))
        return artifacts

    def _request_index(self, requests: list[_Artifact]) -> dict[str, _Artifact]:
        index: dict[str, _Artifact] = {}
        for item in requests:
            request_id = str(item.payload.get("request_id") or item.path.stem.replace("request_", ""))
            index[request_id] = item
        return index

    def _session_links(self, sessions: list[_Artifact], request_index: dict[str, _Artifact]) -> dict[str, str]:
        links: dict[str, str] = {}
        text_index = {
            str(item.payload.get("user_request", "")): request_id
            for request_id, item in request_index.items()
            if item.payload.get("user_request")
        }
        for item in sessions:
            session_id = str(item.payload.get("session_id") or item.path.stem.replace("do_session_", ""))
            request_ref = self._session_request_ref(item.payload)
            request_id = self._request_id_from_ref(request_ref)
            if request_id not in request_index:
                request_id = text_index.get(str(item.payload.get("user_request", "")), "")
            if request_id:
                links[session_id] = request_id
        return links

    @staticmethod
    def _session_request_ref(payload: dict[str, Any]) -> str:
        artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
        return str(artifacts.get("request_path") or payload.get("request_artifact_path") or "")

    @staticmethod
    def _request_id_from_ref(ref: str | None) -> str:
        if not ref:
            return ""
        stem = Path(str(ref)).stem
        if stem.startswith("request_"):
            return stem.replace("request_", "", 1)
        return stem if stem.startswith("req-") else ""

    def _proposal_links(
        self,
        proposals: list[_Artifact],
        request_index: dict[str, _Artifact],
        session_links: dict[str, str],
    ) -> dict[str, str]:
        text_index = {
            str(item.payload.get("user_request", "")): request_id
            for request_id, item in request_index.items()
            if item.payload.get("user_request")
        }
        proposal_by_session_artifact: dict[str, str] = {}
        for session_path in (Path.cwd(),):
            _ = session_path
        links: dict[str, str] = {}
        for item in proposals:
            proposal_id = str(item.payload.get("proposal_id") or item.path.stem)
            request_id = ""
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            request_id = str(metrics_context.get("request_id") or "")
            if not request_id:
                request_id = self._request_id_from_ref(str(item.payload.get("source_context_ref") or ""))
            if not request_id:
                request_id = text_index.get(str(item.payload.get("user_request", "")), "")
            if not request_id:
                request_id = proposal_by_session_artifact.get(_relative(item.path, item.path.parent.parent.parent if ".cambrian" in item.path.parts else item.path.parent), "")
            if request_id:
                links[proposal_id] = request_id
        return links

    def _adoption_links(
        self,
        adoptions: list[_Artifact],
        proposals: list[_Artifact],
        request_index: dict[str, _Artifact],
        proposal_links: dict[str, str],
    ) -> dict[str, str]:
        proposal_ids = {str(item.payload.get("proposal_id") or item.path.stem): item for item in proposals}
        links: dict[str, str] = {}
        text_index = {
            str(item.payload.get("user_request", "")): request_id
            for request_id, item in request_index.items()
            if item.payload.get("user_request")
        }
        for item in adoptions:
            adoption_id = str(item.payload.get("adoption_id") or item.path.stem)
            proposal_id = str(item.payload.get("proposal_id") or "")
            request_id = proposal_links.get(proposal_id, "")
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            request_id = request_id or str(metrics_context.get("request_id") or "")
            proposal = proposal_ids.get(proposal_id)
            if proposal is not None:
                request_id = request_id or text_index.get(str(proposal.payload.get("user_request", "")), "")
            if request_id:
                links[adoption_id] = request_id
        return links

    def _validated_request_ids(
        self,
        sessions: list[_Artifact],
        proposals: list[_Artifact],
        proposal_links: dict[str, str],
        request_index: dict[str, _Artifact],
    ) -> set[str]:
        request_ids: set[str] = set()
        session_links = self._session_links(sessions, request_index)
        for item in sessions:
            session_id = str(item.payload.get("session_id") or "")
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            results = metrics_context.get("results") if isinstance(metrics_context.get("results"), dict) else {}
            if _bool(results.get("validated_proposal")) or str(item.payload.get("current_stage") or item.payload.get("status")) in {"patch_proposal_validated", "adopted"}:
                request_id = session_links.get(session_id)
                if request_id:
                    request_ids.add(request_id)
        for item in proposals:
            if self._proposal_validated(item.payload):
                proposal_id = str(item.payload.get("proposal_id") or item.path.stem)
                request_id = proposal_links.get(proposal_id)
                if request_id:
                    request_ids.add(request_id)
        return request_ids

    @staticmethod
    def _proposal_validated(payload: dict[str, Any]) -> bool:
        validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
        metrics_context = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
        return (
            str(payload.get("proposal_status", "")).lower() == "validated"
            or str(validation.get("status", "")).lower() == "passed"
            or _bool(metrics_context.get("validated_proposal"))
        )

    @staticmethod
    def _apply_tests_passed(payload: dict[str, Any]) -> bool:
        tests = payload.get("post_apply_tests") if isinstance(payload.get("post_apply_tests"), dict) else {}
        metrics_context = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
        if "apply_tests_passed" in metrics_context:
            return _bool(metrics_context.get("apply_tests_passed"))
        failed = int(tests.get("failed", 0) or 0)
        exit_code = int(tests.get("exit_code", -1) if tests.get("exit_code") is not None else -1)
        return exit_code == 0 and failed == 0

    @staticmethod
    def _human_intervention_request_ids(sessions: list[_Artifact], session_links: dict[str, str]) -> set[str]:
        flags = {
            "source_selected_manually",
            "test_selected_manually",
            "old_text_overridden",
            "new_text_overridden",
            "explicit_agent_override",
            "explicit_team_override",
            "explicit_template_choice",
        }
        request_ids: set[str] = set()
        for item in sessions:
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            human = metrics_context.get("human_interventions") if isinstance(metrics_context.get("human_interventions"), dict) else {}
            if any(_bool(human.get(flag)) for flag in flags):
                session_id = str(item.payload.get("session_id") or "")
                request_id = session_links.get(session_id)
                if request_id:
                    request_ids.add(request_id)
        return request_ids

    @staticmethod
    def _validation_autonomy_request_ids(
        sessions: list[_Artifact],
        session_links: dict[str, str],
        validated_request_ids: set[str],
    ) -> set[str]:
        request_ids: set[str] = set()
        for item in sessions:
            session_id = str(item.payload.get("session_id") or "")
            request_id = session_links.get(session_id)
            if not request_id or request_id not in validated_request_ids:
                continue
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            human = metrics_context.get("human_interventions") if isinstance(metrics_context.get("human_interventions"), dict) else {}
            if _bool(human.get("old_text_overridden")) or _bool(human.get("new_text_overridden")):
                continue
            continuations = item.payload.get("continuations") if isinstance(item.payload.get("continuations"), list) else []
            continued_to_validation = any(
                isinstance(step, dict) and str(step.get("action")) in {"patch_proposal_created", "patch_proposal_validated"}
                for step in continuations
            )
            if continued_to_validation or str(metrics_context.get("validation_path", "")) == "continue":
                request_ids.add(request_id)
        return request_ids

    @staticmethod
    def _lead_agent_id(payload: dict[str, Any]) -> str:
        metrics_context = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
        if metrics_context.get("lead_agent_id"):
            return str(metrics_context.get("lead_agent_id"))
        agent_context = payload.get("agent_context") if isinstance(payload.get("agent_context"), dict) else {}
        return str(agent_context.get("lead_agent_id") or "")

    def _lead_agent_hit(self, payload: dict[str, Any]) -> bool:
        metrics_context = payload.get("metrics_context") if isinstance(payload.get("metrics_context"), dict) else {}
        results = metrics_context.get("results") if isinstance(metrics_context.get("results"), dict) else {}
        if "lead_agent_hit" in results:
            return _bool(results.get("lead_agent_hit"))
        lead = self._lead_agent_id(payload)
        final = str(metrics_context.get("final_lead_agent_id") or lead)
        success = _bool(results.get("validated_proposal")) or _bool(results.get("adoption_succeeded")) or str(payload.get("current_stage") or payload.get("status")) in {"patch_proposal_validated", "adopted"}
        return bool(lead and final == lead and success)

    def _team_template_recommendation_hit_rate(self, root: Path) -> tuple[float | None, dict[str, int]]:
        recommended = self._collect_recommended_team_template_names(root)
        used = self._collect_used_team_template_names(root)
        if not recommended:
            return None, {"recommendations": 0, "hits": 0}
        hits = len([name for name in recommended if name in used])
        return _rate(hits, len(recommended)), {"recommendations": len(recommended), "hits": hits}

    def _collect_recommended_team_template_names(self, root: Path) -> set[str]:
        names: list[str] = []
        for directory in (root / ".cambrian" / "agents", root / ".cambrian" / "templates"):
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*.yaml")):
                lowered = path.name.lower()
                if "recommend" not in lowered and "board" not in lowered:
                    continue
                payload = _load_any(path)
                names.extend(self._extract_name_fields(payload, ("recommended_team_name", "recommended_template_name", "best_team_name", "best_template_name", "template_name", "team_name")))
        return set(_dedupe(names))

    def _collect_used_team_template_names(self, root: Path) -> set[str]:
        names: list[str] = []
        paths = [
            root / ".cambrian" / "agents" / "team_decisions.yaml",
            root / ".cambrian" / "templates" / "decisions.yaml",
            root / ".cambrian" / "templates" / "library_decisions.yaml",
            root / ".cambrian" / "templates" / "bootstrap_record.yaml",
            root / ".cambrian" / "templates" / "bootstrap_choice.yaml",
            root / ".cambrian" / "templates" / "current_template.yaml",
        ]
        for path in paths:
            payload = _load_any(path)
            if payload:
                names.extend(self._extract_name_fields(payload, ("template_name", "selected_template_name", "team_name", "name")))
        return set(_dedupe(names))

    def _extract_name_fields(self, payload: Any, keys: tuple[str, ...]) -> list[str]:
        names: list[str] = []
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, str) and value:
                    names.append(value)
                elif isinstance(value, dict):
                    names.extend(self._extract_name_fields(value, keys))
                elif isinstance(value, list):
                    for item in value:
                        names.extend(self._extract_name_fields(item, keys))
            for key in ("candidates", "templates", "teams", "decisions", "entries"):
                value = payload.get(key)
                if isinstance(value, list):
                    for item in value:
                        names.extend(self._extract_name_fields(item, keys))
        elif isinstance(payload, list):
            for item in payload:
                names.extend(self._extract_name_fields(item, keys))
        return _dedupe(names)

    @staticmethod
    def _reused_request_count(request_index: dict[str, _Artifact]) -> int:
        return len([item for item in request_index.values() if _any_reuse(item.payload)])

    def _reuse_lift(
        self,
        request_index: dict[str, _Artifact],
        validated_request_ids: set[str],
        adoption_links: dict[str, str],
    ) -> float | None:
        adopted_request_ids = set(adoption_links.values())
        success_ids = set(validated_request_ids) | adopted_request_ids
        reused_ids = {request_id for request_id, item in request_index.items() if _any_reuse(item.payload)}
        non_reused_ids = set(request_index) - reused_ids
        if not reused_ids or not non_reused_ids:
            return None
        reused_success = len(reused_ids & success_ids) / len(reused_ids)
        non_reused_success = len(non_reused_ids & success_ids) / len(non_reused_ids)
        return round(reused_success - non_reused_success, 4)

    def _repeat_task_improvement(
        self,
        request_index: dict[str, _Artifact],
        validated_request_ids: set[str],
        sessions: list[_Artifact],
        session_links: dict[str, str],
    ) -> tuple[dict[str, float | None], dict[str, int]]:
        groups: dict[str, list[str]] = {}
        for request_id, item in request_index.items():
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            request_class = str(metrics_context.get("request_class") or _request_class((item.payload.get("routing") or {}).get("intent_type") if isinstance(item.payload.get("routing"), dict) else None))
            groups.setdefault(request_class, []).append(request_id)
        deltas: list[float] = []
        time_deltas: list[float] = []
        time_to_validated = self._time_to_validated_by_request(request_index, sessions, [], session_links, {})
        repeated_groups = 0
        for request_ids in groups.values():
            ordered = sorted(
                request_ids,
                key=lambda request_id: request_index[request_id].created_at or datetime.min.replace(tzinfo=timezone.utc),
            )
            if len(ordered) < 2:
                continue
            repeated_groups += 1
            split = max(1, len(ordered) // 2)
            baseline = ordered[:split]
            recent = ordered[split:]
            if not recent:
                continue
            baseline_success = len([rid for rid in baseline if rid in validated_request_ids]) / len(baseline)
            recent_success = len([rid for rid in recent if rid in validated_request_ids]) / len(recent)
            deltas.append(recent_success - baseline_success)
            baseline_times = [time_to_validated[rid] for rid in baseline if rid in time_to_validated]
            recent_times = [time_to_validated[rid] for rid in recent if rid in time_to_validated]
            if baseline_times and recent_times:
                time_deltas.append(float(statistics.median(baseline_times)) - float(statistics.median(recent_times)))
        return {
            "success_rate_delta": round(float(statistics.mean(deltas)), 4) if deltas else None,
            "median_time_delta_seconds": round(float(statistics.mean(time_deltas)), 3) if time_deltas else None,
        }, {"groups": repeated_groups}

    def _median_time_to_validated(
        self,
        request_index: dict[str, _Artifact],
        sessions: list[_Artifact],
        proposals: list[_Artifact],
        session_links: dict[str, str],
        proposal_links: dict[str, str],
    ) -> float | None:
        durations = list(self._time_to_validated_by_request(request_index, sessions, proposals, session_links, proposal_links).values())
        return _median(durations)

    def _time_to_validated_by_request(
        self,
        request_index: dict[str, _Artifact],
        sessions: list[_Artifact],
        proposals: list[_Artifact],
        session_links: dict[str, str],
        proposal_links: dict[str, str],
    ) -> dict[str, float]:
        validated_at: dict[str, datetime] = {}
        for item in sessions:
            session_id = str(item.payload.get("session_id") or "")
            request_id = session_links.get(session_id)
            if not request_id:
                continue
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            milestones = metrics_context.get("milestones") if isinstance(metrics_context.get("milestones"), dict) else {}
            candidate = _parse_datetime(milestones.get("proposal_validated_at"))
            if candidate is not None:
                validated_at[request_id] = min(candidate, validated_at.get(request_id, candidate))
        for item in proposals:
            if not self._proposal_validated(item.payload):
                continue
            proposal_id = str(item.payload.get("proposal_id") or item.path.stem)
            request_id = proposal_links.get(proposal_id)
            if not request_id:
                continue
            metrics_context = item.payload.get("metrics_context") if isinstance(item.payload.get("metrics_context"), dict) else {}
            candidate = _parse_datetime(metrics_context.get("proposal_validated_at") or item.payload.get("created_at"))
            if candidate is not None:
                validated_at[request_id] = min(candidate, validated_at.get(request_id, candidate))
        durations: dict[str, float] = {}
        for request_id, request in request_index.items():
            metrics_context = request.payload.get("metrics_context") if isinstance(request.payload.get("metrics_context"), dict) else {}
            started = _parse_datetime(metrics_context.get("request_started_at") or request.payload.get("created_at"))
            finished = validated_at.get(request_id)
            if started is not None and finished is not None and finished >= started:
                durations[request_id] = (finished - started).total_seconds()
        return durations

    @staticmethod
    def _metrics_from_summary(summary: dict[str, Any], counts: dict[str, Any]) -> list[WeeklyMetric]:
        return [
            WeeklyMetric("validated_proposal_rate", summary.get("validated_proposal_rate"), "rate", "validated proposal 도달 요청 수 / 전체 요청 수"),
            WeeklyMetric("adoption_rate", summary.get("adoption_rate"), "rate", "adoption 성공 수 / validated proposal 수"),
            WeeklyMetric("regression_free_apply_rate", summary.get("regression_free_apply_rate"), "rate", "apply 후 tests passed 수 / 전체 apply 수"),
            WeeklyMetric("median_time_to_validated_proposal", summary.get("median_time_to_validated_proposal"), "seconds", "request 시작부터 validated proposal까지 걸린 median"),
            WeeklyMetric("human_intervention_rate", summary.get("human_intervention_rate"), "rate", "수동 개입 발생 요청 수 / 전체 요청 수"),
            WeeklyMetric("validation_autonomy_rate", summary.get("validation_autonomy_rate"), "rate", "request + continue 흐름만으로 validation까지 도달한 요청 수 / 전체 요청 수"),
            WeeklyMetric("lead_agent_hit_rate", summary.get("lead_agent_hit_rate"), "rate", "처음 선택 lead agent가 끝까지 유효했던 비율"),
            WeeklyMetric("team_template_recommendation_hit_rate", summary.get("team_template_recommendation_hit_rate"), "rate", "추천 team/template가 accepted/applied/used된 비율"),
            WeeklyMetric("reuse_lift", summary.get("reuse_lift"), "points", "reuse 요청군 성공률 - non-reuse 요청군 성공률"),
            WeeklyMetric("repeat_task_improvement_rate", summary.get("repeat_task_improvement_rate"), "points", "같은 request_class의 최근 success delta"),
        ]


class ProjectMetricsStore:
    """weekly metrics report 저장소."""

    def save(self, report: WeeklyMetricsReport, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        latest = saved.parent / "latest.yaml"
        _save_yaml(latest, report.to_dict())
        return saved

    def load(self, path: Path) -> WeeklyMetricsReport:
        return _report_from_dict(_load_any(Path(path).resolve()))


def render_weekly_metrics(report: WeeklyMetricsReport) -> str:
    """weekly metrics report를 사람이 읽기 좋게 렌더링한다."""
    summary = report.summary
    improvement_summary: dict[str, Any] = {}
    try:
        from engine.project_improvement_loop import load_latest_improvement_summary

        improvement_summary = load_latest_improvement_summary(Path(report.workspace))
    except Exception as exc:
        logger.warning("improvement summary load failed for metrics render: %s", exc)
    lines = [
        "Cambrian Weekly Metrics",
        "==================================================",
        "",
        "North Star:",
        f"  validated proposal rate : {_format_rate(summary.get('validated_proposal_rate'))}",
        "",
        "Outcome:",
        f"  adoption rate           : {_format_rate(summary.get('adoption_rate'))}",
        f"  regression-free apply   : {_format_rate(summary.get('regression_free_apply_rate'))}",
        f"  median time to validate : {_format_seconds(summary.get('median_time_to_validated_proposal'))}",
        "",
        "Automation:",
        f"  human intervention rate : {_format_rate(summary.get('human_intervention_rate'))}",
        f"  validation autonomy     : {_format_rate(summary.get('validation_autonomy_rate'))}",
        "",
        "Routing / Staffing:",
        f"  lead agent hit rate     : {_format_rate(summary.get('lead_agent_hit_rate'))}",
        f"  team/template hit rate  : {_format_rate(summary.get('team_template_recommendation_hit_rate'))}",
        "",
        "Evolution:",
        f"  reuse lift              : {_format_points(summary.get('reuse_lift'))}",
        f"  repeat task improvement : {_format_points(summary.get('repeat_task_improvement_rate'))}",
    ]
    if summary.get("latest_autonomy_bottleneck") or summary.get("latest_autonomy_next_fix"):
        lines.extend([
            "",
            "Top bottleneck this week:",
            f"  {summary.get('latest_autonomy_bottleneck') or 'none'}",
        ])
        if summary.get("latest_autonomy_next_fix"):
            lines.append(f"  next: {summary.get('latest_autonomy_next_fix')}")
    if summary.get("active_intervention_kind") or summary.get("active_intervention_id"):
        lines.extend([
            "",
            "Active intervention:",
            f"  {summary.get('active_intervention_kind') or summary.get('active_intervention_id')}",
        ])
    if summary.get("kept_intervention_count"):
        kinds = list(summary.get("kept_improvement_kinds", []) or [])
        lines.extend([
            "",
            "Kept improvements:",
            f"  {', '.join(kinds[:3]) if kinds else str(summary.get('kept_intervention_count')) + ' kept'}",
        ])
    if improvement_summary:
        if improvement_summary.get("status") in {"planned", "in_progress"}:
            lines.extend([
                "",
                "Improvement focus this week:",
                f"  {improvement_summary.get('selected_bottleneck_kind') or 'none'}",
            ])
        elif improvement_summary.get("verdict"):
            lines.extend([
                "",
                "Latest improvement verdict:",
                f"  {improvement_summary.get('verdict')}",
            ])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings[:5]])
    return "\n".join(lines)


def _format_rate(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "n/a"


def _format_points(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        points = float(value) * 100
    except (TypeError, ValueError):
        return "n/a"
    sign = "+" if points >= 0 else ""
    return f"{sign}{points:.0f}pt"


def _format_seconds(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return "n/a"
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_latest_metrics_summary(project_root: Path) -> dict[str, Any]:
    """status에서 쓸 latest metrics 요약을 읽는다."""
    latest = default_metrics_dir(project_root) / "latest.yaml"
    payload = _load_any(latest)
    if not payload:
        return {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return {
        "week_id": payload.get("week_id"),
        "validated_proposal_rate": summary.get("validated_proposal_rate"),
        "adoption_rate": summary.get("adoption_rate"),
        "reuse_lift": summary.get("reuse_lift"),
    }


def _any_reuse(request_payload: dict[str, Any]) -> bool:
    metrics_context = request_payload.get("metrics_context") if isinstance(request_payload.get("metrics_context"), dict) else {}
    reused = metrics_context.get("reused_context") if isinstance(metrics_context.get("reused_context"), dict) else {}
    return any(_bool(value) for value in reused.values())


def _report_from_dict(payload: dict[str, Any]) -> WeeklyMetricsReport:
    return WeeklyMetricsReport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        generated_at=str(payload.get("generated_at", "")),
        week_id=str(payload.get("week_id", "")),
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        workspace=str(payload.get("workspace", "")),
        metrics=[
            WeeklyMetric(
                key=str(item.get("key", "")),
                value=item.get("value"),
                unit=str(item.get("unit")) if item.get("unit") is not None else None,
                summary=str(item.get("summary", "")),
                warning=str(item.get("warning")) if item.get("warning") is not None else None,
            )
            for item in payload.get("metrics", [])
            if isinstance(item, dict)
        ],
        summary=dict(payload.get("summary", {})) if isinstance(payload.get("summary"), dict) else {},
        counts=dict(payload.get("counts", {})) if isinstance(payload.get("counts"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )
