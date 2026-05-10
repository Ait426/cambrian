"""강한 win lane에서만 동작하는 안전 자동화 오케스트레이션."""

from __future__ import annotations

import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_context import ContextCandidate, ProjectContextScanner
from engine.project_continue import ProjectDoContinuationRunner
from engine.project_do import DoSession, DoSessionStore, ProjectDoRunner
from engine.project_patch_intent import PatchIntentStore
from engine.project_win_lane import build_and_save_lane_profile, request_lane_fit

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
AUTONOMY_STAGES = [
    "request_start",
    "context_ready",
    "diagnosed",
    "patch_intent_ready",
    "proposal_validated",
]


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    """파일명에 쓰기 쉬운 UTC timestamp를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    """짧은 충돌 방지 id를 만든다."""
    return secrets.token_hex(2)


def _duration_seconds(started_at: str, ended_at: str) -> float | None:
    """두 ISO timestamp 사이 초 단위 차이를 계산한다."""
    start = _parse_datetime(started_at)
    end = _parse_datetime(ended_at)
    if start is None or end is None or end < start:
        return None
    return round((end - start).total_seconds(), 3)


def _parse_datetime(value: Any) -> datetime | None:
    """ISO timestamp를 UTC datetime으로 복원한다."""
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    """YAML 파일을 dict로 읽는다."""
    if not Path(path).exists():
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("safe autonomy artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    """project root 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 문자열 중복을 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _quote(value: str) -> str:
    """CLI 예시용 큰따옴표 인자를 만든다."""
    return '"' + str(value or "").replace('"', '\\"') + '"'


def default_safe_autonomy_dir(project_root: Path) -> Path:
    """safe autonomy run 저장 디렉터리."""
    return Path(project_root).resolve() / ".cambrian" / "autonomy" / "runs"


def default_safe_autonomy_path(project_root: Path, run: "SafeAutonomyRun") -> Path:
    """safe autonomy run 저장 경로."""
    return default_safe_autonomy_dir(project_root) / f"{run.run_id}.yaml"


def latest_safe_autonomy_path(project_root: Path) -> Path:
    """latest safe autonomy pointer 경로."""
    return Path(project_root).resolve() / ".cambrian" / "autonomy" / "latest.yaml"


@dataclass
class SafeAutonomyCheck:
    """safe autonomy 단계별 점검 결과."""

    check_id: str
    title: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class SafeAutonomyRun:
    """safe autonomy 실행 기록."""

    schema_version: str
    run_id: str
    created_at: str
    project_name: str | None
    workspace: str
    request: str
    request_class: str | None
    lane_status: str | None
    session_id: str | None
    session_ref: str | None
    source_mode: str | None
    start_stage: str | None
    autonomy_stage_reached: str | None
    stop_reason: str | None
    status: str
    checks: list[SafeAutonomyCheck] = field(default_factory=list)
    linked_request_ref: str | None = None
    linked_bridge_reply_ref: str | None = None
    linked_patch_intent_ref: str | None = None
    linked_proposal_ref: str | None = None
    metrics_snapshot: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["checks"] = [check.to_dict() for check in self.checks]
        return payload


class SafeAutonomyStore:
    """safe autonomy artifact 저장소."""

    def save(self, run: SafeAutonomyRun, path: Path) -> Path:
        """run artifact와 latest pointer를 저장한다."""
        saved = _save_yaml(Path(path).resolve(), run.to_dict())
        _save_yaml(latest_safe_autonomy_path(saved.parents[3]), run.to_dict())
        return saved

    def load(self, path: Path) -> SafeAutonomyRun:
        """run artifact를 읽는다."""
        return _run_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, directory: Path) -> list[SafeAutonomyRun]:
        """최근 run 목록을 읽는다."""
        records: list[SafeAutonomyRun] = []
        if not Path(directory).exists():
            return records
        for path in sorted(Path(directory).glob("autonomy_*.yaml"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True):
            payload = _load_yaml(path)
            if payload:
                records.append(_run_from_dict(payload))
        return records


class SafeAutonomyCoordinator:
    """강한 lane 안에서만 안전한 자동 전진을 시도한다."""

    def run_request(
        self,
        project_root: Path,
        request: str,
        session_ref: str | None = None,
        source_mode: str | None = None,
    ) -> SafeAutonomyRun:
        """새 요청을 safe autonomy 경로로 가능한 단계까지 전진시킨다."""
        root = Path(project_root).resolve()
        started_at = _now()
        request_text = str(request or "").strip()
        run = _new_run(root, request_text, started_at, source_mode or "direct_do", "request_start")
        profile, lane_path = build_and_save_lane_profile(root)
        fit = request_lane_fit(profile, request_text)
        run.lane_status = profile.status
        run.checks.append(
            SafeAutonomyCheck(
                check_id="lane-fit",
                title="strongest lane fit",
                status="pass" if profile.status == "strong" and fit.get("request_fit") == "in_lane" else "fail",
                summary=str(fit.get("summary") or "lane fit unavailable"),
                details=[f"profile: {profile.status}", f"request_fit: {fit.get('request_fit')}", f"profile_ref: {_relative(lane_path, root)}"],
                suggested_actions=[],
            )
        )
        if profile.status != "strong" or fit.get("request_fit") != "in_lane":
            run.status = "blocked"
            run.autonomy_stage_reached = "request_start"
            run.stop_reason = "request is outside the current strongest lane"
            run.next_actions = [f"cambrian do {_quote(request_text)}"]
            return _finalize_run(root, run, started_at)

        context = _select_context(root, request_text)
        run.checks.append(context["check"])
        if context["status"] != "pass":
            run.status = "blocked"
            run.autonomy_stage_reached = "request_start"
            run.stop_reason = context["stop_reason"]
            run.warnings.extend(context["warnings"])
            run.next_actions = [f"cambrian do {_quote(request_text)} --source <path> --test <path> --execute"]
            return _finalize_run(root, run, started_at)

        source_paths = list(context.get("sources", []))
        test_paths = list(context.get("tests", []))
        run.autonomy_stage_reached = "context_ready"
        run.checks.append(
            SafeAutonomyCheck(
                check_id="context-ready",
                title="context ready",
                status="pass",
                summary="single high-confidence source/test context selected",
                details=[*source_paths, *test_paths],
                suggested_actions=[],
            )
        )

        session = ProjectDoRunner().run(
            user_request=request_text,
            project_root=root,
            options={
                "session": session_ref,
                "agent": None,
                "use_suggestion": None,
                "sources": source_paths,
                "tests": test_paths,
                "old_choice": None,
                "old_text": None,
                "old_text_file": None,
                "new_text": None,
                "new_text_file": None,
                "propose": False,
                "validate": False,
                "apply": False,
                "reason": None,
                "execute": True,
                "no_scan": False,
            },
        )
        run.session_id = session.session_id
        run.session_ref = session.artifact_path
        run.linked_request_ref = session.artifacts.get("request_path")
        _mark_session_autonomy_metrics(root, session, source_mode or "direct_do")
        if session.status == "diagnosed" or session.current_stage == "diagnosed":
            run.autonomy_stage_reached = "diagnosed"
            run.checks.append(
                SafeAutonomyCheck(
                    check_id="diagnosed",
                    title="diagnosis boundary",
                    status="pass",
                    summary="diagnosis completed without source mutation",
                    details=[str(session.artifacts.get("report_path") or "no report ref")],
                    suggested_actions=[],
                )
            )
        else:
            run.status = "blocked"
            run.stop_reason = "diagnosis did not complete safely"
            run.errors.extend(session.errors)
            run.next_actions = list(session.next_actions)
            return _finalize_run(root, run, started_at, session=session)

        run.status = "partial"
        run.stop_reason = "no patch prefill available"
        run.next_actions = [
            f"cambrian bridge prepare {_quote(request_text)}",
            f"cambrian continue --session {session.session_id} --old-choice old-1 --new-text \"...\" --validate",
        ]
        return _finalize_run(root, run, started_at, session=session)

    def run_continue(self, project_root: Path, session_ref: str) -> SafeAutonomyRun:
        """기존 do session을 safe autonomy 원칙으로 validate 경계까지 전진시킨다."""
        root = Path(project_root).resolve()
        started_at = _now()
        store = DoSessionStore()
        try:
            session_path = store.resolve_path(root, session_ref)
            session = store.load(session_path)
        except FileNotFoundError as exc:
            run = _new_run(root, "", started_at, "bridge_resume", "request_start")
            run.status = "blocked"
            run.stop_reason = str(exc)
            run.errors.append(str(exc))
            return _finalize_run(root, run, started_at)

        request_text = session.user_request or "continue safe autonomy"
        run = _new_run(root, request_text, started_at, _source_mode_for_session(session), session.current_stage)
        run.session_id = session.session_id
        run.session_ref = _relative(session_path, root)
        run.linked_request_ref = session.artifacts.get("request_path")
        run.linked_patch_intent_ref = session.artifacts.get("patch_intent_path")
        if isinstance(session.bridge_context, dict):
            run.linked_bridge_reply_ref = session.bridge_context.get("reply_ref")

        profile, lane_path = build_and_save_lane_profile(root)
        fit = request_lane_fit(profile, request_text)
        run.lane_status = profile.status
        run.checks.append(
            SafeAutonomyCheck(
                check_id="lane-fit",
                title="strongest lane fit",
                status="pass" if profile.status == "strong" and fit.get("request_fit") in {"in_lane", "partial"} else "fail",
                summary=str(fit.get("summary") or "lane fit unavailable"),
                details=[f"profile: {profile.status}", f"request_fit: {fit.get('request_fit')}", f"profile_ref: {_relative(lane_path, root)}"],
                suggested_actions=[],
            )
        )
        if profile.status != "strong" or fit.get("request_fit") == "outside":
            run.status = "blocked"
            run.autonomy_stage_reached = _stage_alias(session.current_stage)
            run.stop_reason = "request is outside the current strongest lane"
            run.next_actions = [f"cambrian continue --session {session.session_id}"]
            return _finalize_run(root, run, started_at, session=session)

        prefill = _load_session_prefill(root, session)
        run.checks.append(
            SafeAutonomyCheck(
                check_id="patch-prefill",
                title="patch prefill availability",
                status="pass" if prefill.get("complete") else "fail",
                summary=prefill.get("summary", "patch prefill unavailable"),
                details=[str(item) for item in prefill.get("details", [])],
                suggested_actions=[f"cambrian bridge paste --packet <packet-id>"] if not prefill.get("complete") else [],
            )
        )
        if not prefill.get("complete"):
            run.status = "blocked"
            run.autonomy_stage_reached = _stage_alias(session.current_stage)
            run.stop_reason = "no patch prefill available"
            run.next_actions = [f"cambrian continue --session {session.session_id} --old-choice old-1 --new-text \"...\" --validate"]
            return _finalize_run(root, run, started_at, session=session)

        continued = ProjectDoContinuationRunner().run(
            project_root=root,
            options={
                "session": session.session_id,
                "agent": None,
                "use_suggestion": None,
                "sources": [],
                "tests": [],
                "old_choice": None,
                "old_text": None,
                "old_text_file": None,
                "new_text": None,
                "new_text_file": None,
                "propose": True,
                "validate": True,
                "apply": False,
                "reason": None,
                "execute": False,
                "no_scan": False,
            },
        )
        run.linked_patch_intent_ref = continued.artifacts.get("patch_intent_path")
        run.linked_proposal_ref = continued.artifacts.get("patch_proposal_path")
        _mark_session_autonomy_metrics(root, continued, run.source_mode or "bridge_resume")
        if continued.current_stage == "patch_proposal_validated" or continued.status == "patch_proposal_validated":
            run.status = "completed"
            run.autonomy_stage_reached = "proposal_validated"
            run.stop_reason = None
            run.checks.append(
                SafeAutonomyCheck(
                    check_id="proposal-validated",
                    title="proposal validated",
                    status="pass",
                    summary="proposal validation reached from safe prefill without apply",
                    details=[str(continued.artifacts.get("patch_proposal_path") or "no proposal ref")],
                    suggested_actions=[],
                )
            )
        else:
            run.status = "partial"
            run.autonomy_stage_reached = _stage_alias(continued.current_stage)
            run.stop_reason = "validation failed" if continued.current_stage == "patch_proposal_ready" else "safe autonomy stopped before proposal validation"
            run.errors.extend(continued.errors)
            run.checks.append(
                SafeAutonomyCheck(
                    check_id="proposal-validated",
                    title="proposal validated",
                    status="fail",
                    summary=run.stop_reason,
                    details=[str(continued.artifacts.get("patch_proposal_path") or "no proposal ref")],
                    suggested_actions=list(continued.next_actions),
                )
            )
        run.next_actions = list(continued.next_actions)
        return _finalize_run(root, run, started_at, session=continued)


def resolve_safe_autonomy_path(project_root: Path, run_ref: str) -> Path:
    """run id 또는 path를 실제 safe autonomy artifact path로 해석한다."""
    root = Path(project_root).resolve()
    candidate = Path(run_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in default_safe_autonomy_dir(root).glob("autonomy_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == run_ref or str(payload.get("run_id") or "") == run_ref:
            return path.resolve()
    raise FileNotFoundError(f"safe autonomy run not found: {run_ref}")


def load_latest_safe_autonomy_summary(project_root: Path) -> dict[str, Any]:
    """status에서 사용할 최신 safe autonomy 요약을 읽는다."""
    payload = _load_yaml(latest_safe_autonomy_path(project_root))
    if not payload:
        return {}
    return {
        "run_id": payload.get("run_id"),
        "request": payload.get("request"),
        "status": payload.get("status"),
        "autonomy_stage_reached": payload.get("autonomy_stage_reached"),
        "stop_reason": payload.get("stop_reason"),
        "next_actions": payload.get("next_actions", []),
    }


def render_safe_autonomy_run(run: SafeAutonomyRun, saved_path: str | None = None) -> str:
    """safe autonomy run을 사람이 읽기 쉽게 렌더링한다."""
    title = "Safe autonomy completed." if run.status == "completed" else "Safe autonomy stopped."
    lines = [
        title,
        "",
        "Request:",
        f"  {run.request or 'unknown'}",
        "",
        "Lane:",
        f"  {run.lane_status or 'unknown'}",
        "",
        "Stage reached:",
        f"  {run.autonomy_stage_reached or 'none'}",
        "",
        "Status:",
        f"  {run.status}",
    ]
    if run.stop_reason:
        lines.extend(["", "Why:", f"  {run.stop_reason}"])
    if run.session_id:
        lines.extend(["", "Session:", f"  {run.session_id}"])
    if run.linked_patch_intent_ref:
        lines.extend(["", "Patch intent:", f"  {run.linked_patch_intent_ref}"])
    if run.linked_proposal_ref:
        lines.extend(["", "Proposal:", f"  {run.linked_proposal_ref}"])
    if run.checks:
        lines.extend(["", "Checks:"])
        for check in run.checks:
            lines.append(f"  - {check.title}: {check.status} - {check.summary}")
    if saved_path:
        lines.extend(["", "Recorded:", f"  {saved_path}"])
    lines.extend(["", "Next:"])
    if run.next_actions:
        lines.extend([f"  - {item}" for item in run.next_actions[:4]])
    else:
        lines.append("  review generated artifacts before apply/adoption")
    if run.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in run.warnings])
    if run.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in run.errors])
    return "\n".join(lines)


def _new_run(root: Path, request: str, created_at: str, source_mode: str, start_stage: str | None) -> SafeAutonomyRun:
    """기본 safe autonomy run 객체를 만든다."""
    return SafeAutonomyRun(
        schema_version=SCHEMA_VERSION,
        run_id=f"autonomy_{_timestamp()}_{_short_id()}",
        created_at=created_at,
        project_name=_project_name(root),
        workspace=str(root),
        request=request,
        request_class=_infer_request_class(request),
        lane_status=None,
        session_id=None,
        session_ref=None,
        source_mode=source_mode,
        start_stage=start_stage,
        autonomy_stage_reached=start_stage,
        stop_reason=None,
        status="blocked",
        metrics_snapshot={},
    )


def _finalize_run(
    root: Path,
    run: SafeAutonomyRun,
    started_at: str,
    *,
    session: DoSession | None = None,
) -> SafeAutonomyRun:
    """metrics snapshot을 채우고 run artifact를 저장한다."""
    finished_at = _now()
    validated = run.autonomy_stage_reached == "proposal_validated"
    human_intervention = _session_had_human_intervention(session) if session is not None else False
    run.metrics_snapshot = {
        "validated_proposal": validated,
        "human_intervention": human_intervention,
        "validation_autonomy": bool(validated and not human_intervention),
        "duration_seconds": _duration_seconds(started_at, finished_at),
        "lead_agent_hit": None,
        "team_template_hit": None,
    }
    intervention_metrics: dict[str, Any] = {}
    try:
        from engine.project_improvement_interventions import intervention_metrics_context

        intervention_metrics = intervention_metrics_context(root)
        if intervention_metrics:
            run.metrics_snapshot.update(intervention_metrics)
    except Exception as exc:
        logger.warning("active improvement intervention metrics load failed: %s", exc)
    if session is not None:
        _mark_session_autonomy_metrics(root, session, run.source_mode or "safe_autonomy")
        if intervention_metrics:
            session.metrics_context.update(intervention_metrics)
        results = session.metrics_context.setdefault("results", {})
        if isinstance(results, dict):
            results["validated_proposal"] = validated
        session.metrics_context["safe_autonomy"] = {
            "run_id": run.run_id,
            "stage_reached": run.autonomy_stage_reached,
            "stop_reason": run.stop_reason,
            "validation_autonomy": run.metrics_snapshot["validation_autonomy"],
        }
        DoSessionStore().save(root, session)
    SafeAutonomyStore().save(run, default_safe_autonomy_path(root, run))
    return run


def _select_context(root: Path, request: str) -> dict[str, Any]:
    """단일 high-confidence context 후보를 고른다."""
    scan = ProjectContextScanner().scan(request, root, limit=5)
    source = _single_high_confidence(scan.suggested_sources)
    test = _single_high_confidence(scan.suggested_tests, minimum=0.25, allow_missing=True)
    if source["status"] != "pass":
        return {
            "status": "fail",
            "stop_reason": source["reason"],
            "warnings": source["warnings"],
            "sources": [],
            "tests": [],
            "check": SafeAutonomyCheck(
                check_id="context-confidence",
                title="context confidence",
                status="fail",
                summary=source["reason"],
                details=source["warnings"],
                suggested_actions=["choose --source manually"],
            ),
        }
    tests = [test["path"]] if test.get("path") else []
    details = [source["path"], *tests]
    return {
        "status": "pass",
        "stop_reason": None,
        "warnings": _dedupe(source["warnings"] + test["warnings"]),
        "sources": [source["path"]],
        "tests": tests,
        "check": SafeAutonomyCheck(
            check_id="context-confidence",
            title="context confidence",
            status="pass",
            summary="context narrowed to one safe candidate",
            details=details,
            suggested_actions=[],
        ),
    }


def _single_high_confidence(
    candidates: list[ContextCandidate],
    *,
    minimum: float = 0.45,
    allow_missing: bool = False,
) -> dict[str, Any]:
    """후보 목록에서 자동 선택 가능한 단일 후보를 판정한다."""
    if not candidates:
        if allow_missing:
            return {"status": "pass", "path": None, "reason": "no candidate required", "warnings": []}
        return {"status": "fail", "path": None, "reason": "no safe context candidate", "warnings": []}
    first = candidates[0]
    if first.score < minimum:
        return {
            "status": "fail",
            "path": None,
            "reason": "no safe context candidate",
            "warnings": [f"top candidate too weak: {first.path} score={first.score}"],
        }
    if len(candidates) == 1:
        return {"status": "pass", "path": first.path, "reason": "single candidate", "warnings": []}
    second = candidates[1]
    if first.score - second.score >= 0.20:
        return {"status": "pass", "path": first.path, "reason": "clear top candidate", "warnings": []}
    return {
        "status": "fail",
        "path": None,
        "reason": "ambiguous source selection",
        "warnings": [f"top candidates too close: {first.path}={first.score}, {second.path}={second.score}"],
    }


def _load_session_prefill(root: Path, session: DoSession) -> dict[str, Any]:
    """session에 연결된 patch intent의 bridge prefill 상태를 확인한다."""
    intent_ref = session.artifacts.get("patch_intent_path") if isinstance(session.artifacts, dict) else None
    if not intent_ref:
        return {"complete": False, "summary": "patch intent is not linked", "details": []}
    intent_path = root / str(intent_ref)
    if not intent_path.exists():
        return {"complete": False, "summary": "patch intent artifact is missing", "details": [str(intent_ref)]}
    try:
        form = PatchIntentStore().load(intent_path)
    except Exception as exc:
        logger.warning("patch intent prefill load failed: %s", exc)
        return {"complete": False, "summary": f"patch intent could not be loaded: {exc}", "details": [str(intent_ref)]}
    prefill = dict(form.bridge_prefill or {})
    if not prefill and isinstance(form.memory_guidance, dict) and isinstance(form.memory_guidance.get("bridge_prefill"), dict):
        prefill = dict(form.memory_guidance.get("bridge_prefill", {}))
    target = str(prefill.get("target_path") or form.target_path or "").strip()
    old_text = str(prefill.get("old_text") or (form.old_text_candidates[0].text if form.old_text_candidates else "") or "").strip()
    new_text = str(prefill.get("new_text") or form.new_text or "").strip()
    complete = bool(target and old_text and new_text)
    return {
        "complete": complete,
        "summary": "bridge prefill is complete" if complete else "patch prefill is incomplete",
        "details": [f"target={target or 'missing'}", f"old_text={'present' if old_text else 'missing'}", f"new_text={'present' if new_text else 'missing'}"],
    }


def _mark_session_autonomy_metrics(root: Path, session: DoSession, source_mode: str) -> None:
    """session metrics_context에 safe autonomy 사용 흔적을 남긴다."""
    metrics = session.metrics_context if isinstance(session.metrics_context, dict) else {}
    metrics["autonomy_mode"] = "safe"
    metrics["source_mode"] = source_mode
    reused = metrics.setdefault("reused_context", {})
    if isinstance(reused, dict):
        reused["harness_policy"] = bool(session.harness_policy_context)
        reused["team_policy"] = bool(session.team_policy_context)
        reused["template"] = bool(session.template_context)
        reused["bridge"] = bool(session.bridge_context)
    human = metrics.setdefault("human_interventions", {})
    if isinstance(human, dict):
        human.setdefault("source_selected_manually", False)
        human.setdefault("test_selected_manually", False)
        human.setdefault("old_text_overridden", False)
        human.setdefault("new_text_overridden", False)
        human["safe_autonomy"] = True
    session.metrics_context = metrics
    DoSessionStore().save(root, session)


def _session_had_human_intervention(session: DoSession | None) -> bool:
    """session metrics_context에서 수동 개입 여부를 계산한다."""
    if session is None or not isinstance(session.metrics_context, dict):
        return False
    human = session.metrics_context.get("human_interventions")
    if not isinstance(human, dict):
        return False
    ignored = {"safe_autonomy", "bridge_paste_fastpath", "bridge_manual_ingest"}
    return any(bool(value) for key, value in human.items() if key not in ignored)


def _source_mode_for_session(session: DoSession) -> str:
    """session context에서 safe autonomy source mode를 추론한다."""
    metrics = session.metrics_context if isinstance(session.metrics_context, dict) else {}
    source = str(metrics.get("source_mode") or "").strip()
    if source:
        return source
    bridge = session.bridge_context if isinstance(session.bridge_context, dict) else {}
    if bridge:
        return str(bridge.get("source_mode") or "bridge_resume")
    return "direct_do"


def _stage_alias(stage: str | None) -> str | None:
    """기존 do stage를 autonomy stage vocabulary로 맞춘다."""
    value = str(stage or "").strip()
    mapping = {
        "prepared": "context_ready",
        "diagnose_ready": "context_ready",
        "diagnosed": "diagnosed",
        "patch_intent_draft": "patch_intent_ready",
        "patch_intent_ready": "patch_intent_ready",
        "patch_proposal_ready": "patch_intent_ready",
        "patch_proposal_validated": "proposal_validated",
    }
    return mapping.get(value, value or None)


def _project_name(root: Path) -> str | None:
    """project.yaml에서 프로젝트명을 읽는다."""
    payload = _load_yaml(root / ".cambrian" / "project.yaml")
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    return str(project.get("name")) if project.get("name") else None


def _infer_request_class(request: str) -> str:
    """간단한 request class 추론."""
    lowered = str(request or "").lower()
    if any(token in lowered for token in ("docs", "readme", "문서")):
        return "docs"
    if any(token in lowered for token in ("review", "검토")):
        return "review"
    if any(token in lowered for token in ("refactor", "migration", "리팩터", "마이그레이션")):
        return "refactor"
    if any(token in lowered for token in ("bug", "fix", "error", "fail", "login", "auth", "에러", "버그", "수정")):
        return "bug_fix"
    return "unknown"


def _run_from_dict(payload: dict[str, Any]) -> SafeAutonomyRun:
    """dict를 SafeAutonomyRun으로 복원한다."""
    return SafeAutonomyRun(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        run_id=str(payload.get("run_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        workspace=str(payload.get("workspace") or ""),
        request=str(payload.get("request") or ""),
        request_class=str(payload.get("request_class")) if payload.get("request_class") is not None else None,
        lane_status=str(payload.get("lane_status")) if payload.get("lane_status") is not None else None,
        session_id=str(payload.get("session_id")) if payload.get("session_id") is not None else None,
        session_ref=str(payload.get("session_ref")) if payload.get("session_ref") is not None else None,
        source_mode=str(payload.get("source_mode")) if payload.get("source_mode") is not None else None,
        start_stage=str(payload.get("start_stage")) if payload.get("start_stage") is not None else None,
        autonomy_stage_reached=str(payload.get("autonomy_stage_reached")) if payload.get("autonomy_stage_reached") is not None else None,
        stop_reason=str(payload.get("stop_reason")) if payload.get("stop_reason") is not None else None,
        status=str(payload.get("status") or "blocked"),
        checks=[_check_from_dict(item) for item in payload.get("checks", []) if isinstance(item, dict)],
        linked_request_ref=str(payload.get("linked_request_ref")) if payload.get("linked_request_ref") is not None else None,
        linked_bridge_reply_ref=str(payload.get("linked_bridge_reply_ref")) if payload.get("linked_bridge_reply_ref") is not None else None,
        linked_patch_intent_ref=str(payload.get("linked_patch_intent_ref")) if payload.get("linked_patch_intent_ref") is not None else None,
        linked_proposal_ref=str(payload.get("linked_proposal_ref")) if payload.get("linked_proposal_ref") is not None else None,
        metrics_snapshot=dict(payload.get("metrics_snapshot", {})) if isinstance(payload.get("metrics_snapshot"), dict) else {},
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _check_from_dict(payload: dict[str, Any]) -> SafeAutonomyCheck:
    """dict를 SafeAutonomyCheck로 복원한다."""
    return SafeAutonomyCheck(
        check_id=str(payload.get("check_id") or ""),
        title=str(payload.get("title") or ""),
        status=str(payload.get("status") or "warn"),
        summary=str(payload.get("summary") or ""),
        details=[str(item) for item in payload.get("details", []) if item],
        suggested_actions=[str(item) for item in payload.get("suggested_actions", []) if item],
    )
