"""Benchmark case를 안전하게 재생해 autonomy stage를 기록한다."""

from __future__ import annotations

import logging
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_benchmarks import (
    BenchmarkResult,
    BenchmarkStore,
    default_benchmark_dir,
    default_results_dir,
)
from engine.project_bridge import ProjectBridgeStore, default_bridge_replies_dir, resolve_bridge_reply_path
from engine.project_bridge_handoff import (
    BridgeHandoffStore,
    BridgeReplyHandoff,
    BridgeReplyReviewStore,
    BridgeReplyReviewer,
    default_bridge_handoff_path,
    default_bridge_review_path,
)
from engine.project_metrics import build_request_metrics_context, build_session_metrics_context

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
REPLAY_MODES = {"cambrian_guided", "cambrian_full"}
REPLAY_STAGES = [
    "request_start",
    "context_ready",
    "diagnosed",
    "patch_intent_ready",
    "proposal_validated",
]
SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".yaml", ".yml", ".json"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    return secrets.token_hex(2)


def _slug(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip().lower()).strip("-")
    return text or fallback


def _atomic_write_text(path: Path, content: str) -> None:
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
    _atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("benchmark replay artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _duration_seconds(started_at: str, ended_at: str) -> float | None:
    start = _parse_datetime(started_at)
    end = _parse_datetime(ended_at)
    if start is None or end is None or end < start:
        return None
    return round((end - start).total_seconds(), 3)


def _parse_datetime(value: Any) -> datetime | None:
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


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def default_replays_dir(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "replays"


def default_replay_path(project_root: Path, report: "BenchmarkReplayReport") -> Path:
    return default_replays_dir(project_root) / f"replay_{_slug(report.case_id)}_{report.mode}_{_stamp()}_{_short_id()}.yaml"


def latest_replay_path(project_root: Path) -> Path:
    return default_benchmark_dir(project_root) / "latest_replay.yaml"


@dataclass
class BenchmarkReplayStep:
    kind: str
    status: str
    summary: str
    artifact_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReplayReport:
    schema_version: str
    replay_id: str
    created_at: str
    case_id: str
    case_name: str
    request: str
    request_class: str
    mode: str
    project_name: str | None
    workspace: str
    linked_session_id: str | None
    linked_session_ref: str | None
    linked_bridge_reply_ref: str | None
    autonomy_stage_reached: str | None
    stop_reason: str | None
    status: str
    steps: list[BenchmarkReplayStep]
    metrics_snapshot: dict[str, Any]
    next_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


class BenchmarkReplayStore:
    def save(self, report: BenchmarkReplayReport, path: Path) -> Path:
        saved = _save_yaml(Path(path).resolve(), report.to_dict())
        _save_yaml(saved.parent.parent / "latest_replay.yaml", report.to_dict())
        return saved

    def load(self, path: Path) -> BenchmarkReplayReport:
        return _replay_from_dict(_load_yaml(Path(path).resolve()))

    def list(self, replays_dir: Path) -> list[BenchmarkReplayReport]:
        reports: list[BenchmarkReplayReport] = []
        for path in sorted(Path(replays_dir).glob("replay_*.yaml")):
            payload = _load_yaml(path)
            if payload:
                reports.append(_replay_from_dict(payload))
        reports.sort(key=lambda item: item.created_at, reverse=True)
        return reports


class BenchmarkReplayRunner:
    def run(self, project_root: Path, case_name_or_id: str, mode: str) -> BenchmarkReplayReport:
        root = Path(project_root).resolve()
        if mode not in REPLAY_MODES:
            raise ValueError(f"unsupported replay mode: {mode}")
        store = BenchmarkStore()
        case_path = store.resolve_case_path(root, case_name_or_id)
        case = store.load_case(case_path)
        started_at = _now()
        replay_id = f"benchmark-replay-{_slug(case.case_id)}-{_short_id()}"
        request_ref = _create_request_artifact(root, case, replay_id, started_at)
        session_path, session = _create_replay_session(root, case, replay_id, request_ref, mode, started_at)
        session_ref = _relative(session_path, root)
        steps: list[BenchmarkReplayStep] = [
            BenchmarkReplayStep(
                kind="request_start",
                status="success",
                summary="benchmark replay request/session artifact created",
                artifact_refs=[request_ref, session_ref],
                warnings=[],
            )
        ]
        stage_reached = "request_start"
        stop_reason: str | None = None
        warnings = list(case.warnings)
        errors: list[str] = []

        context = _resolve_context(root, case)
        if context["status"] == "success":
            stage_reached = "context_ready"
            steps.append(
                BenchmarkReplayStep(
                    kind="context_ready",
                    status="success",
                    summary=context["summary"],
                    artifact_refs=context["artifact_refs"],
                    warnings=context["warnings"],
                )
            )
            session.summary["selected_sources"] = list(context.get("source_paths", []))
            session.summary["selected_tests"] = list(context.get("test_paths", []))
            session.metrics_context["milestones"]["diagnosed_at"] = _now()
        else:
            stop_reason = context["summary"]
            steps.append(
                BenchmarkReplayStep(
                    kind="context_ready",
                    status="blocked",
                    summary=stop_reason,
                    artifact_refs=[],
                    warnings=context["warnings"],
                )
            )
            warnings.extend(context["warnings"])
            _finalize_session(root, session, stage_reached, validated=False)
            return _build_report(root, case, replay_id, started_at, mode, session, session_ref, None, stage_reached, stop_reason, "blocked", steps, warnings, errors)

        stage_reached = "diagnosed"
        steps.append(
            BenchmarkReplayStep(
                kind="diagnosed",
                status="success",
                summary="diagnosis boundary reached without source mutation",
                artifact_refs=[session_ref],
                warnings=[],
            )
        )

        reply_path = _resolve_bridge_reply_for_replay(root, case, mode)
        linked_bridge_reply_ref = _relative(reply_path, root) if reply_path else None
        if reply_path is None:
            stop_reason = "no safe prefilled patch candidate was available"
            steps.append(
                BenchmarkReplayStep(
                    kind="patch_intent_ready",
                    status="blocked",
                    summary=stop_reason,
                    artifact_refs=[],
                    warnings=["bridge patch_candidate reply was not available for replay"],
                )
            )
            _finalize_session(root, session, stage_reached, validated=False)
            return _build_report(root, case, replay_id, started_at, mode, session, session_ref, None, stage_reached, stop_reason, "partial", steps, warnings, errors)

        try:
            review = BridgeReplyReviewer().review(root, reply_path)
            review_path = BridgeReplyReviewStore().save(review, default_bridge_review_path(root, review))
            handoff = BridgeReplyHandoff().to_patch_intent(root, reply_path)
            handoff_path = BridgeHandoffStore().save(handoff, default_bridge_handoff_path(root, handoff))
            if handoff.status != "created" or not handoff.target_artifact_ref:
                stop_reason = "bridge patch candidate could not create a patch intent draft"
                steps.append(
                    BenchmarkReplayStep(
                        kind="patch_intent_ready",
                        status="blocked",
                        summary=stop_reason,
                        artifact_refs=[_relative(review_path, root), _relative(handoff_path, root)],
                        warnings=list(handoff.warnings),
                    )
                )
                _finalize_session(root, session, stage_reached, validated=False)
                return _build_report(root, case, replay_id, started_at, mode, session, session_ref, linked_bridge_reply_ref, stage_reached, stop_reason, "blocked", steps, warnings, list(handoff.errors))
            from engine.project_bridge_resume import BridgeSessionCoordinator

            link = BridgeSessionCoordinator().ensure_linked_session(
                root,
                reply_path,
                handoff,
                patch_intent_ref=handoff.target_artifact_ref,
                explicit_session_ref=session.session_id,
            )
        except Exception as exc:
            stop_reason = f"bridge-assisted replay failed: {exc}"
            logger.warning(stop_reason)
            steps.append(
                BenchmarkReplayStep(
                    kind="patch_intent_ready",
                    status="failed",
                    summary=stop_reason,
                    artifact_refs=[],
                    warnings=[],
                )
            )
            _finalize_session(root, session, stage_reached, validated=False)
            return _build_report(root, case, replay_id, started_at, mode, session, session_ref, linked_bridge_reply_ref, stage_reached, stop_reason, "failed", steps, warnings, [stop_reason])

        stage_reached = "patch_intent_ready"
        session.artifacts["patch_intent_path"] = handoff.target_artifact_ref
        session.bridge_context.update(
            {
                "reply_ref": linked_bridge_reply_ref,
                "review_ref": _relative(review_path, root),
                "handoff_ref": _relative(handoff_path, root),
                "link_ref": link.link_id,
            }
        )
        session.metrics_context["milestones"]["patch_intent_ready_at"] = _now()
        steps.append(
            BenchmarkReplayStep(
                kind="patch_intent_ready",
                status="success",
                summary="bridge patch_candidate materialized as safe patch intent draft",
                artifact_refs=[handoff.target_artifact_ref, _relative(handoff_path, root)],
                warnings=[],
            )
        )

        validation = _safe_validate_patch_intent(root, handoff.target_artifact_ref)
        if validation["validated"]:
            stage_reached = "proposal_validated"
            steps.append(
                BenchmarkReplayStep(
                    kind="proposal_validated",
                    status="success",
                    summary="safe validation boundary reached without apply",
                    artifact_refs=[handoff.target_artifact_ref],
                    warnings=list(validation["warnings"]),
                )
            )
            _finalize_session(root, session, stage_reached, validated=True)
            return _build_report(root, case, replay_id, started_at, mode, session, session_ref, linked_bridge_reply_ref, stage_reached, None, "completed", steps, warnings, errors)

        stop_reason = validation["reason"]
        steps.append(
            BenchmarkReplayStep(
                kind="proposal_validated",
                status="blocked",
                summary=stop_reason,
                artifact_refs=[handoff.target_artifact_ref],
                warnings=list(validation["warnings"]),
            )
        )
        _finalize_session(root, session, stage_reached, validated=False)
        return _build_report(root, case, replay_id, started_at, mode, session, session_ref, linked_bridge_reply_ref, stage_reached, stop_reason, "partial", steps, warnings, errors)


def replay_result_path(project_root: Path, result: BenchmarkResult) -> Path:
    return default_results_dir(project_root) / f"result_{_slug(result.case_id)}_{result.mode}_replay_{_stamp()}_{_short_id()}.yaml"


def replay_to_benchmark_result(report: BenchmarkReplayReport) -> BenchmarkResult:
    validated = bool(report.metrics_snapshot.get("validated_proposal"))
    return BenchmarkResult(
        schema_version=SCHEMA_VERSION,
        result_id=f"result-{_slug(report.case_id)}-{report.mode}-replay-{_short_id()}",
        created_at=_now(),
        case_id=report.case_id,
        mode=report.mode,
        status="recorded" if report.status in {"completed", "partial"} else report.status,
        source_refs={
            "replay_ref": None,
            "session_ref": report.linked_session_ref,
            "bridge_reply_ref": report.linked_bridge_reply_ref,
        },
        metrics_snapshot=dict(report.metrics_snapshot),
        summary=(
            f"Reached {report.autonomy_stage_reached} with no source mutation and no apply"
            if report.autonomy_stage_reached
            else "Replay did not reach an autonomous stage"
        ),
        verdict="good" if validated else "mixed",
        warnings=list(report.warnings),
        errors=list(report.errors),
    )


def save_replay_result(project_root: Path, report: BenchmarkReplayReport, replay_ref: str | None) -> Path:
    result = replay_to_benchmark_result(report)
    result.source_refs["replay_ref"] = replay_ref
    path = replay_result_path(project_root, result)
    BenchmarkStore().save_result(result, path)
    return path


def resolve_replay_path(project_root: Path, replay_ref: str) -> Path:
    root = Path(project_root).resolve()
    candidate = Path(replay_ref)
    if candidate.exists():
        return candidate.resolve()
    if (root / candidate).exists():
        return (root / candidate).resolve()
    for path in default_replays_dir(root).glob("replay_*.yaml"):
        payload = _load_yaml(path)
        if path.stem == replay_ref or str(payload.get("replay_id") or "") == replay_ref:
            return path.resolve()
    raise FileNotFoundError(f"benchmark replay not found: {replay_ref}")


def load_latest_replay_summary(project_root: Path) -> dict[str, Any]:
    payload = _load_yaml(latest_replay_path(project_root))
    if not payload:
        return {}
    return {
        "case_id": payload.get("case_id"),
        "case_name": payload.get("case_name"),
        "mode": payload.get("mode"),
        "autonomy_stage_reached": payload.get("autonomy_stage_reached"),
        "stop_reason": payload.get("stop_reason"),
        "status": payload.get("status"),
    }


def render_replay_report(report: BenchmarkReplayReport, saved_path: str | None = None, result_path: str | None = None) -> str:
    lines = [
        "Benchmark Replay",
        "==================================================",
        "",
        "Case:",
        f"  {report.case_name}",
        "",
        "Mode:",
        f"  {report.mode}",
        "",
        "Autonomy stage reached:",
        f"  {report.autonomy_stage_reached or 'none'}",
        "",
        "Result:",
        f"  {report.status}",
    ]
    if report.stop_reason:
        lines.extend(["", "Why:", f"  - {report.stop_reason}"])
    lines.extend(["", "Steps:"])
    for step in report.steps:
        lines.append(f"  - {step.kind}: {step.status} - {step.summary}")
    lines.extend(["", "Metrics:"])
    lines.append(f"  validated proposal : {_human_bool(report.metrics_snapshot.get('validated_proposal'))}")
    lines.append(f"  human intervention : {_human_bool(report.metrics_snapshot.get('human_intervention'))}")
    lines.append(f"  validation autonomy: {_human_bool(report.metrics_snapshot.get('validation_autonomy'))}")
    if saved_path:
        lines.extend(["", "Saved:", f"  {saved_path}"])
    if result_path:
        lines.extend(["", "Recorded result:", f"  {result_path}"])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {item}" for item in report.next_actions])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {item}" for item in report.warnings])
    if report.errors:
        lines.extend(["", "Errors:"])
        lines.extend([f"  - {item}" for item in report.errors])
    return "\n".join(lines)


def render_replays(reports: list[BenchmarkReplayReport]) -> str:
    lines = ["Benchmark Replays", "==================================================", ""]
    if not reports:
        lines.append("No benchmark replays yet.")
        return "\n".join(lines)
    for report in reports:
        lines.append(f"- {report.case_name} [{report.mode}]")
        lines.append(f"  reached: {report.autonomy_stage_reached or 'none'}")
        lines.append(f"  status : {report.status}")
        if report.stop_reason:
            lines.append(f"  why    : {report.stop_reason}")
    return "\n".join(lines)


def _create_request_artifact(root: Path, case: Any, replay_id: str, created_at: str) -> str:
    request_id = f"benchmark-replay-{_slug(case.case_id)}-{_short_id()}"
    path = root / ".cambrian" / "requests" / f"request_{request_id}.yaml"
    metrics_context = build_request_metrics_context(
        request_id=request_id,
        created_at=created_at,
        intent_type=case.request_class,
        memory_context={},
        harness_policy_context={},
        team_policy_context={},
        template_context={},
        bridge_context={"enabled": True, "source": "benchmark_replay"},
    )
    metrics_context["request_class"] = case.request_class
    metrics_context["source_mode"] = "benchmark_replay"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "created_at": created_at,
        "user_request": case.request,
        "source_kind": "benchmark_replay",
        "source_replay_id": replay_id,
        "metrics_context": metrics_context,
    }
    _save_yaml(path, payload)
    return _relative(path, root)


def _create_replay_session(
    root: Path,
    case: Any,
    replay_id: str,
    request_ref: str,
    mode: str,
    created_at: str,
) -> tuple[Path, Any]:
    from engine.project_do import DoSession, DoSessionStore

    session_id = f"replay-{_slug(case.case_id)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_short_id()}"
    metrics_context = build_session_metrics_context(
        session_created_at=created_at,
        existing={
            "request_id": Path(request_ref).stem.replace("request_", ""),
            "request_ref": request_ref,
            "source_mode": "benchmark_replay",
            "validation_path": "replay",
        },
    )
    metrics_context["results"]["apply_tests_passed"] = None
    session = DoSession(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        created_at=created_at,
        updated_at=None,
        user_request=case.request,
        project_initialized=(root / ".cambrian" / "project.yaml").exists(),
        intent={"source": "benchmark_replay", "case_id": case.case_id, "mode": mode},
        selected_skills=[],
        status="benchmark_replay",
        current_stage="request_start",
        artifacts={
            "request_path": request_ref,
            "patch_intent_path": None,
            "patch_proposal_path": None,
            "adoption_record_path": None,
        },
        summary={
            "understood_as": case.request_class,
            "found_sources": [],
            "found_tests": [],
            "selected_sources": [],
            "selected_tests": [],
            "needs": [],
        },
        next_actions=[],
        next_commands=[],
        harness_context={},
        agent_context={},
        harness_policy_context={},
        team_context={},
        team_policy_context={},
        template_context={},
        bridge_context={"enabled": True, "source_mode": "benchmark_replay", "replay_id": replay_id},
        metrics_context=metrics_context,
        continuations=[{"action": "benchmark_replay_started", "at": created_at}],
        warnings=[],
        errors=[],
    )
    path = DoSessionStore().save(root, session)
    return path, session


def _resolve_context(root: Path, case: Any) -> dict[str, Any]:
    hints = case.replay_hints if isinstance(case.replay_hints, dict) else {}
    warnings: list[str] = []
    source_hint = str(hints.get("source_path_hint") or hints.get("target_path") or "").strip()
    test_hint = str(hints.get("test_path_hint") or "").strip()
    source_paths: list[str] = []
    test_paths: list[str] = []
    if source_hint:
        source_path = (root / source_hint).resolve()
        if _is_safe_project_path(root, source_path) and source_path.exists():
            source_paths.append(source_hint.replace("\\", "/"))
        else:
            warnings.append(f"source_path_hint is missing or unsafe: {source_hint}")
    if test_hint:
        test_path = (root / test_hint).resolve()
        if _is_safe_project_path(root, test_path) and test_path.exists():
            test_paths.append(test_hint.replace("\\", "/"))
        else:
            warnings.append(f"test_path_hint is missing or unsafe: {test_hint}")
    if not source_paths:
        candidates = _scan_source_candidates(root, case)
        if len(candidates) == 1:
            source_paths.append(candidates[0])
        elif len(candidates) > 1:
            return {
                "status": "blocked",
                "summary": "ambiguous source selection",
                "artifact_refs": [],
                "source_paths": [],
                "test_paths": test_paths,
                "warnings": [f"multiple source candidates: {', '.join(candidates[:5])}"],
            }
        else:
            return {
                "status": "blocked",
                "summary": "no safe source candidate found",
                "artifact_refs": [],
                "source_paths": [],
                "test_paths": test_paths,
                "warnings": warnings,
            }
    return {
        "status": "success",
        "summary": "context selected from benchmark replay hints or unambiguous local scan",
        "artifact_refs": source_paths + test_paths,
        "source_paths": source_paths,
        "test_paths": test_paths,
        "warnings": warnings,
    }


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


def _resolve_bridge_reply_for_replay(root: Path, case: Any, mode: str) -> Path | None:
    if mode != "cambrian_full":
        return None
    hints = case.replay_hints if isinstance(case.replay_hints, dict) else {}
    reply_ref = str(hints.get("bridge_reply_ref") or hints.get("linked_bridge_reply_ref") or "").strip()
    if reply_ref:
        try:
            return resolve_bridge_reply_path(root, reply_ref)
        except FileNotFoundError:
            return None
    replies = sorted(default_bridge_replies_dir(root).glob("reply_*.yaml"), key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    for path in replies:
        reply = ProjectBridgeStore().load_reply(path)
        if reply.response_kind == "patch_candidate" and (reply.request == case.request or not reply.request):
            return path.resolve()
    return None


def _safe_validate_patch_intent(root: Path, intent_ref: str) -> dict[str, Any]:
    intent_path = root / intent_ref
    payload = _load_yaml(intent_path)
    prefill = payload.get("bridge_prefill") if isinstance(payload.get("bridge_prefill"), dict) else {}
    target_path = str(prefill.get("target_path") or payload.get("target_path") or "").strip()
    old_text = str(prefill.get("old_text") or "").strip()
    new_text = str(prefill.get("new_text") or "").strip()
    warnings: list[str] = []
    if not target_path or not old_text or not new_text:
        return {"validated": False, "reason": "patch intent prefill is incomplete", "warnings": warnings}
    target = (root / target_path).resolve()
    if not _is_safe_project_path(root, target) or not target.exists():
        return {"validated": False, "reason": "target path is missing or unsafe", "warnings": warnings}
    try:
        content = target.read_text(encoding="utf-8")
    except OSError as exc:
        return {"validated": False, "reason": f"target file could not be read: {exc}", "warnings": warnings}
    if old_text not in content:
        return {"validated": False, "reason": "old_text was not found in target file", "warnings": warnings}
    if old_text == new_text:
        return {"validated": False, "reason": "new_text is identical to old_text", "warnings": warnings}
    return {"validated": True, "reason": None, "warnings": warnings}


def _finalize_session(root: Path, session: DoSession, stage: str, *, validated: bool) -> None:
    from engine.project_do import DoSessionStore

    now = _now()
    session.current_stage = stage
    session.status = "patch_proposal_validated" if validated else "benchmark_replay"
    results = session.metrics_context.setdefault("results", {})
    if isinstance(results, dict):
        results["validated_proposal"] = validated
        results["adoption_succeeded"] = False
        results["apply_tests_passed"] = None
        results["lead_agent_hit"] = None
    milestones = session.metrics_context.setdefault("milestones", {})
    if isinstance(milestones, dict) and validated:
        milestones["proposal_validated_at"] = now
    session.metrics_context["validation_path"] = "replay"
    session.continuations.append(
        {
            "action": "patch_proposal_validated" if validated else "benchmark_replay_stopped",
            "at": now,
            "stage": stage,
        }
    )
    session.next_actions = ["Review benchmark replay report before using this as product evidence."]
    DoSessionStore().save(root, session)


def _build_report(
    root: Path,
    case: Any,
    replay_id: str,
    started_at: str,
    mode: str,
    session: DoSession,
    session_ref: str,
    linked_bridge_reply_ref: str | None,
    stage_reached: str | None,
    stop_reason: str | None,
    status: str,
    steps: list[BenchmarkReplayStep],
    warnings: list[str],
    errors: list[str],
) -> BenchmarkReplayReport:
    finished_at = _now()
    validated = stage_reached == "proposal_validated"
    metrics_snapshot = {
        "validated_proposal": validated,
        "adoption_succeeded": False,
        "apply_tests_passed": None,
        "human_intervention": False,
        "validation_autonomy": bool(validated),
        "lead_agent_hit": None,
        "team_template_hit": None,
        "duration_seconds": _duration_seconds(started_at, finished_at),
    }
    try:
        from engine.project_improvement_interventions import intervention_metrics_context

        metrics_snapshot.update(intervention_metrics_context(root))
    except Exception as exc:
        logger.warning("active improvement intervention metrics load failed: %s", exc)
    next_actions = [
        f"cambrian benchmark report <workset-name> --save",
        f"cambrian benchmark compare <workset-name>",
    ]
    if stop_reason:
        next_actions.insert(0, "Add replay_hints or bridge patch_candidate if deeper autonomy proof is needed.")
    return BenchmarkReplayReport(
        schema_version=SCHEMA_VERSION,
        replay_id=replay_id,
        created_at=started_at,
        case_id=case.case_id,
        case_name=case.name,
        request=case.request,
        request_class=case.request_class,
        mode=mode,
        project_name=_project_name(root),
        workspace=str(root),
        linked_session_id=session.session_id,
        linked_session_ref=session_ref,
        linked_bridge_reply_ref=linked_bridge_reply_ref,
        autonomy_stage_reached=stage_reached,
        stop_reason=stop_reason,
        status=status,
        steps=steps,
        metrics_snapshot=metrics_snapshot,
        next_actions=next_actions,
        warnings=_dedupe(warnings),
        errors=_dedupe(errors),
    )


def _project_name(root: Path) -> str | None:
    payload = _load_yaml(root / ".cambrian" / "project.yaml")
    project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
    return str(project.get("name")) if project.get("name") else None


def _tokens(text: str) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[0-9A-Za-z가-힣_]+", text) if len(token) >= 2]
    stop = {"fix", "bug", "test", "tests", "with", "this", "that", "work", "case"}
    return _dedupe([token for token in tokens if token not in stop])


def _is_safe_project_path(root: Path, path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    parts = {part.lower() for part in rel.parts}
    return ".git" not in parts and ".cambrian" not in parts


def _human_bool(value: Any) -> str:
    if value is None:
        return "n/a"
    return "yes" if bool(value) else "no"


def _replay_from_dict(payload: dict[str, Any]) -> BenchmarkReplayReport:
    return BenchmarkReplayReport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        replay_id=str(payload.get("replay_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        case_id=str(payload.get("case_id") or ""),
        case_name=str(payload.get("case_name") or payload.get("case_id") or ""),
        request=str(payload.get("request") or ""),
        request_class=str(payload.get("request_class") or "unknown"),
        mode=str(payload.get("mode") or "cambrian_guided"),
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        workspace=str(payload.get("workspace") or ""),
        linked_session_id=str(payload.get("linked_session_id")) if payload.get("linked_session_id") is not None else None,
        linked_session_ref=str(payload.get("linked_session_ref")) if payload.get("linked_session_ref") is not None else None,
        linked_bridge_reply_ref=str(payload.get("linked_bridge_reply_ref")) if payload.get("linked_bridge_reply_ref") is not None else None,
        autonomy_stage_reached=str(payload.get("autonomy_stage_reached")) if payload.get("autonomy_stage_reached") is not None else None,
        stop_reason=str(payload.get("stop_reason")) if payload.get("stop_reason") is not None else None,
        status=str(payload.get("status") or "partial"),
        steps=[_step_from_dict(item) for item in payload.get("steps", []) if isinstance(item, dict)],
        metrics_snapshot=dict(payload.get("metrics_snapshot", {})) if isinstance(payload.get("metrics_snapshot"), dict) else {},
        next_actions=[str(item) for item in payload.get("next_actions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _step_from_dict(payload: dict[str, Any]) -> BenchmarkReplayStep:
    return BenchmarkReplayStep(
        kind=str(payload.get("kind") or ""),
        status=str(payload.get("status") or ""),
        summary=str(payload.get("summary") or ""),
        artifact_refs=[str(item) for item in payload.get("artifact_refs", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
    )
