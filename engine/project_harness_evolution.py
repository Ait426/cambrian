"""Cambrian 프로젝트 하네스 진화 제안."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_agent_history import AgentPassportHistoryStore, default_agent_passport_path
from engine.project_agent_reviews import AgentReviewStore, build_agent_review_summary, default_agent_reviews_dir
from engine.project_agent_transfer import default_imported_agents_dir
from engine.project_agents import AgentRegistryBuilder, AgentRegistryStore, default_agent_registry_path
from engine.project_dispatch import DispatchBoardBuilder
from engine.project_harness import HarnessProfileBuilder, HarnessProfileStore, default_harness_profile_path
from engine.project_memory import load_project_memory
from engine.project_memory_hygiene import hygiene_index, load_memory_hygiene
from engine.project_notes import ProjectNotesStore, default_notes_dir
from engine.project_summary import ProjectUsageSummaryStore, default_usage_summary_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
_MAX_TOP_SUGGESTIONS = 5
_REFRACTOR_KEYWORDS = ("refactor", "scope", "broad", "drift", "large change")
_TEST_KEYWORDS = ("test", "pytest", "regression")


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명용 UTC 스탬프를 만든다."""
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하며 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _clamp(value: float) -> float:
    """점수를 0.0~0.9 범위로 제한한다."""
    return round(max(0.0, min(0.9, float(value))), 4)


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 반환한다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_harness_evolution_path(project_root: Path) -> Path:
    """기본 하네스 진화 제안 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "harness" / "evolution_suggestions.yaml"


def default_request_harness_evolution_path(project_root: Path) -> Path:
    """요청 기반 하네스 진화 제안 저장 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "harness" / "evolution_suggestions__request.yaml"


@dataclass
class HarnessSuggestion:
    """하네스 조정 제안 한 건."""

    suggestion_id: str
    kind: str
    title: str
    summary: str
    confidence: float
    priority: str
    target: str | None
    reasons: list[str]
    warnings: list[str]
    evidence_refs: list[str]
    next_commands: list[str]

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class HarnessEvolutionReport:
    """하네스 진화 제안 보고서."""

    schema_version: str
    generated_at: str
    report_id: str
    project_name: str | None
    harness_id: str | None
    mode: str
    request: str | None
    suggestions: list[HarnessSuggestion]
    summary: dict
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "report_id": self.report_id,
            "project_name": self.project_name,
            "harness_id": self.harness_id,
            "mode": self.mode,
            "request": self.request,
            "suggestions": [item.to_dict() for item in self.suggestions],
            "summary": dict(self.summary),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class HarnessEvolutionStore:
    """하네스 진화 제안 저장/로드 도구."""

    def save(self, report: HarnessEvolutionReport, path: Path) -> Path:
        """보고서를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(report.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> HarnessEvolutionReport:
        """저장된 보고서를 로드한다."""
        payload = yaml.safe_load(Path(path).resolve().read_text(encoding="utf-8")) or {}
        suggestions: list[HarnessSuggestion] = []
        for item in payload.get("suggestions", []) or []:
            if not isinstance(item, dict):
                continue
            suggestions.append(
                HarnessSuggestion(
                    suggestion_id=str(item.get("suggestion_id", "")),
                    kind=str(item.get("kind", "")),
                    title=str(item.get("title", "")),
                    summary=str(item.get("summary", "")),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    priority=str(item.get("priority", "low")),
                    target=str(item.get("target")) if item.get("target") is not None else None,
                    reasons=[str(reason) for reason in item.get("reasons", []) if reason],
                    warnings=[str(warning) for warning in item.get("warnings", []) if warning],
                    evidence_refs=[str(ref) for ref in item.get("evidence_refs", []) if ref],
                    next_commands=[str(command) for command in item.get("next_commands", []) if command],
                )
            )
        return HarnessEvolutionReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            report_id=str(payload.get("report_id", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            mode=str(payload.get("mode", "board")),
            request=str(payload.get("request")) if payload.get("request") is not None else None,
            suggestions=suggestions,
            summary=dict(payload.get("summary", {})) if isinstance(payload.get("summary"), dict) else {},
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


class HarnessEvolutionBuilder:
    """현재 프로젝트 하네스의 다음 조정 방향을 제안한다."""

    def build(self, project_root: Path, request: str | None = None) -> HarnessEvolutionReport:
        """프로젝트-wide 또는 request-aware 제안 보고서를 만든다."""
        root = Path(project_root).resolve()
        harness = self._load_harness(root)
        registry = self._load_registry(root, harness)
        dispatch_board = DispatchBoardBuilder().build(root, request=request)
        memory = load_project_memory(root)
        hygiene = load_memory_hygiene(root)
        hygiene_map = hygiene_index(hygiene) if hygiene is not None else {}
        notes = ProjectNotesStore().list(default_notes_dir(root))
        review_store = AgentReviewStore()
        review_dir = default_agent_reviews_dir(root)
        usage_summary = self._load_usage_summary(root)
        sessions = self._load_recent_sessions(root)
        imported_paths = {
            path.stem: _relative_to_project(path, root)
            for path in sorted(default_imported_agents_dir(root).glob("*.yaml"))
        } if default_imported_agents_dir(root).exists() else {}
        candidate_by_id = {item.agent_id: item for item in dispatch_board.candidates}
        suggestions: list[HarnessSuggestion] = []
        warnings: list[str] = []
        errors: list[str] = []

        history_store = AgentPassportHistoryStore()
        histories: dict[str, object] = {}
        review_summaries: dict[str, dict] = {}
        review_texts: dict[str, list[str]] = {}
        for agent in registry.agents:
            history_path = default_agent_passport_path(root, agent.agent_id)
            if history_path.exists():
                try:
                    histories[agent.agent_id] = history_store.load(history_path)
                except Exception as exc:
                    message = f"agent passport history load failed: {history_path} ({exc})"
                    logger.warning(message)
                    warnings.append(message)
            reviews = review_store.list(review_dir, agent_id=agent.agent_id)
            review_summaries[agent.agent_id] = build_agent_review_summary(reviews).to_dict()
            review_texts[agent.agent_id] = [str(item.summary or item.text) for item in reviews]

        suggestions.extend(
            self._build_staffing_suggestions(
                root=root,
                dispatch_board=dispatch_board,
                candidate_by_id=candidate_by_id,
                histories=histories,
                review_summaries=review_summaries,
                imported_paths=imported_paths,
            )
        )
        suggestions.extend(
            self._build_practice_suggestions(
                root=root,
                harness=harness,
                memory=memory,
                hygiene=hygiene,
                histories=histories,
                review_texts=review_texts,
                dispatch_board=dispatch_board,
                sessions=sessions,
            )
        )
        suggestions.extend(
            self._build_note_followup_suggestions(
                root=root,
                notes=notes,
                request=request,
            )
        )
        if usage_summary is None:
            warnings.append("usage summary is missing")

        suggestions = self._sort_suggestions(suggestions)[:_MAX_TOP_SUGGESTIONS]
        top_hint = suggestions[0].summary if suggestions else None
        summary = {
            "total": len(suggestions),
            "high_priority": sum(1 for item in suggestions if item.priority == "high"),
            "medium_priority": sum(1 for item in suggestions if item.priority == "medium"),
            "low_priority": sum(1 for item in suggestions if item.priority == "low"),
            "kinds": self._kind_counts(suggestions),
            "top_hint": top_hint,
            "next_commands": _dedupe([command for item in suggestions for command in item.next_commands])[:4],
        }
        return HarnessEvolutionReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            report_id=f"evolution-{_stamp()}",
            project_name=harness.project_name,
            harness_id=harness.harness_id,
            mode="request" if request else "board",
            request=str(request) if request else None,
            suggestions=suggestions,
            summary=summary,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    def _load_harness(self, root: Path):
        path = default_harness_profile_path(root)
        if path.exists():
            return HarnessProfileStore().load(path)
        return HarnessProfileBuilder().build(root)

    def _load_registry(self, root: Path, harness):
        path = default_agent_registry_path(root)
        if path.exists():
            return AgentRegistryStore().load(path)
        return AgentRegistryBuilder().build(root, harness=harness)

    def _load_usage_summary(self, root: Path) -> dict | None:
        path = default_usage_summary_path(root)
        if not path.exists():
            return None
        try:
            return ProjectUsageSummaryStore().load(path).to_dict()
        except Exception as exc:
            logger.warning("usage summary load failed: %s (%s)", path, exc)
            return None

    def _load_recent_sessions(self, root: Path) -> list[dict]:
        sessions_dir = root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return []
        sessions: list[dict] = []
        for path in sorted(sessions_dir.glob("do_session_*.yaml"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                logger.warning("session load failed: %s (%s)", path, exc)
                continue
            if isinstance(payload, dict):
                payload["__path__"] = _relative_to_project(path, root)
                sessions.append(payload)
        return sessions[:10]

    def _build_staffing_suggestions(
        self,
        *,
        root: Path,
        dispatch_board,
        candidate_by_id: dict,
        histories: dict[str, object],
        review_summaries: dict[str, dict],
        imported_paths: dict[str, str],
    ) -> list[HarnessSuggestion]:
        suggestions: list[HarnessSuggestion] = []
        for agent_id in dispatch_board.top_team[:2]:
            candidate = candidate_by_id.get(agent_id)
            if candidate is None or candidate.current_status != "equipped":
                continue
            history = histories.get(agent_id)
            review_summary = review_summaries.get(agent_id, {})
            reasons = list(candidate.reasons[:2])
            if history is not None:
                recent_wins = getattr(history, "recent_wins", [])
                if recent_wins:
                    reasons.append(str(recent_wins[0]))
            if review_summary.get("recent_positive"):
                reasons.append("recent project review was positive")
            suggestions.append(
                self._suggestion(
                    kind="keep_agent",
                    title=f"Keep {agent_id} in the default harness team.",
                    summary=f"Keep {agent_id} as part of the default harness team.",
                    target=agent_id,
                    reasons=reasons,
                    warnings=[],
                    evidence_refs=_dedupe(
                        [
                            ".cambrian/agents/registry.yaml",
                            _relative_to_project(default_agent_passport_path(root, agent_id), root),
                        ]
                    ),
                    next_commands=[f"cambrian agent show {agent_id}"],
                    evidence_sources=3 if reasons else 1,
                    repeated_signal=bool(getattr(history, "recent_wins", [])),
                    priority="medium",
                )
            )

        for agent_id in dispatch_board.top_hire[:2]:
            candidate = candidate_by_id.get(agent_id)
            if candidate is None:
                continue
            reasons = list(candidate.reasons[:3])
            suggestions.append(
                self._suggestion(
                    kind="hire_agent",
                    title=f"Hire {agent_id} into this harness.",
                    summary=f"Hire {agent_id} into the current harness.",
                    target=agent_id,
                    reasons=reasons,
                    warnings=list(candidate.warnings[:2]),
                    evidence_refs=_dedupe(
                        [
                            ".cambrian/agents/registry.yaml",
                            imported_paths.get(agent_id, ""),
                        ]
                    ),
                    next_commands=[f"cambrian agent hire {agent_id}"],
                    evidence_sources=len(reasons),
                    repeated_signal=True,
                    priority="high" if float(candidate.score) >= 0.7 else "medium",
                )
            )

        for agent_id in dispatch_board.top_fire[:2]:
            candidate = candidate_by_id.get(agent_id)
            if candidate is None:
                continue
            reasons = list(candidate.reasons[-2:]) or ["current harness fit looks weak"]
            review_summary = review_summaries.get(agent_id, {})
            if review_summary.get("recent_cautions"):
                reasons.append("recent project review suggests caution")
            suggestions.append(
                self._suggestion(
                    kind="fire_agent",
                    title=f"Consider removing {agent_id} from the active harness team.",
                    summary=f"Consider removing {agent_id} from the active harness team.",
                    target=agent_id,
                    reasons=reasons,
                    warnings=list(candidate.warnings[:2]),
                    evidence_refs=[".cambrian/agents/registry.yaml"],
                    next_commands=[f"cambrian agent fire {agent_id}"],
                    evidence_sources=len(reasons),
                    repeated_signal=False,
                    priority="low" if review_summaries.get(agent_id, {}).get("weak", 0) < 2 else "medium",
                )
            )
        return suggestions

    def _build_practice_suggestions(
        self,
        *,
        root: Path,
        harness,
        memory,
        hygiene,
        histories: dict[str, object],
        review_texts: dict[str, list[str]],
        dispatch_board,
        sessions: list[dict],
    ) -> list[HarnessSuggestion]:
        suggestions: list[HarnessSuggestion] = []
        fresh_lessons = []
        if memory is not None:
            hygiene_map = hygiene_index(hygiene) if hygiene is not None else {}
            for lesson in memory.lessons:
                if getattr(lesson, "suppressed", False):
                    continue
                if str(getattr(lesson, "status", "")) != "active":
                    continue
                hygiene_item = hygiene_map.get(lesson.lesson_id)
                if hygiene_item is not None and hygiene_item.status != "fresh":
                    continue
                fresh_lessons.append(lesson)

        failed_validations = 0
        successful_small_changes = 0
        refactor_cautions = 0
        for history in histories.values():
            totals = getattr(history, "totals", {})
            failed_validations += int(totals.get("validations_failed", 0) or 0)
            for item in getattr(history, "recent_wins", []):
                text = str(item).lower()
                if "small" in text or "targeted" in text or "minimal" in text:
                    successful_small_changes += 1
        for items in review_texts.values():
            for text in items:
                lowered = str(text).lower()
                if any(keyword in lowered for keyword in _REFRACTOR_KEYWORDS):
                    refactor_cautions += 1

        test_evidence = [
            lesson for lesson in fresh_lessons
            if str(getattr(lesson, "kind", "")).lower() == "test_practice"
            or any(keyword in " ".join([str(getattr(lesson, "text", ""))] + list(getattr(lesson, "tags", []))).lower() for keyword in _TEST_KEYWORDS)
        ]
        if test_evidence and failed_validations > 0:
            reasons = [
                f"{len(test_evidence)} fresh test-related memory lessons are active",
                f"{failed_validations} recent validation failures were observed",
            ]
            suggestions.append(
                self._suggestion(
                    kind="strengthen_test_practice",
                    title="Strengthen test-first practice in this harness.",
                    summary="Strengthen test-first practice in this harness.",
                    target="test_practice",
                    reasons=reasons,
                    warnings=[],
                    evidence_refs=[".cambrian/memory/lessons.yaml", ".cambrian/memory/hygiene.yaml"],
                    next_commands=["cambrian memory review", "cambrian memory hygiene"],
                    evidence_sources=2,
                    repeated_signal=failed_validations > 1,
                    priority="high" if failed_validations > 1 else "medium",
                )
            )

        if refactor_cautions > 0 and successful_small_changes > 0:
            suggestions.append(
                self._suggestion(
                    kind="narrow_change_scope",
                    title="Prefer narrower changes before broader refactors.",
                    summary="Prefer narrower changes before broader refactors in this harness.",
                    target="change_scope",
                    reasons=[
                        f"{refactor_cautions} recent review cautions mention refactor drift",
                        f"{successful_small_changes} recent wins came from smaller changes",
                    ],
                    warnings=[],
                    evidence_refs=[".cambrian/agents/reviews", ".cambrian/agents/passports"],
                    next_commands=["cambrian agent reviews bug-fix-agent"],
                    evidence_sources=2,
                    repeated_signal=refactor_cautions > 1,
                    priority="medium",
                )
            )

        review_candidate = next((item for item in dispatch_board.candidates if item.agent_id == "review-agent"), None)
        if review_candidate is not None and (review_candidate.agent_id in dispatch_board.top_team or review_candidate.agent_id in dispatch_board.top_hire):
            caution_reviews = sum(
                1
                for items in review_texts.values()
                for text in items
                if any(keyword in str(text).lower() for keyword in ("caution", "risk", "refactor", "scope"))
            )
            if caution_reviews > 0:
                suggestions.append(
                    self._suggestion(
                        kind="increase_review_support",
                        title="Increase review support for this harness.",
                        summary="Increase review support for higher-risk changes in this harness.",
                        target="review-agent",
                        reasons=[
                            "review-agent repeatedly appears as a strong support candidate",
                            f"{caution_reviews} recent reviews suggest extra caution",
                        ],
                        warnings=[],
                        evidence_refs=[".cambrian/agents/registry.yaml"],
                        next_commands=["cambrian agent hire review-agent"] if review_candidate.current_status != "equipped" else ["cambrian agent show review-agent"],
                        evidence_sources=2,
                        repeated_signal=caution_reviews > 1,
                        priority="medium",
                    )
                )

        intent_counts: dict[str, int] = {}
        for payload in sessions:
            intent_payload = payload.get("intent", {})
            if not isinstance(intent_payload, dict):
                continue
            intent_type = str(intent_payload.get("intent_type", "") or "").strip()
            if not intent_type:
                continue
            intent_counts[intent_type] = intent_counts.get(intent_type, 0) + 1
        if intent_counts:
            dominant_intent, dominant_count = max(intent_counts.items(), key=lambda item: item[1])
            if dominant_count >= 2:
                reasons = [f"{dominant_intent} intent appeared in {dominant_count} recent sessions"]
                if dominant_intent in {str(item).lower() for item in harness.primary_use_cases}:
                    reasons.append("current harness focus already matches this repeated request pattern")
                suggestions.append(
                    self._suggestion(
                        kind="promote_request_focus",
                        title=f"Promote {dominant_intent} as a default harness focus.",
                        summary=f"Promote {dominant_intent} as a default harness focus.",
                        target=dominant_intent,
                        reasons=reasons,
                        warnings=[],
                        evidence_refs=[str(payload.get("__path__", "")) for payload in sessions[:3] if payload.get("__path__")],
                        next_commands=["cambrian harness show"],
                        evidence_sources=len(reasons),
                        repeated_signal=dominant_count >= 3,
                        priority="medium",
                    )
                )

        if hygiene is not None:
            stale = int(hygiene.summary.get("stale", 0) or 0)
            conflicting = int(hygiene.summary.get("conflicting", 0) or 0)
            watch = int(hygiene.summary.get("watch", 0) or 0)
            if stale or conflicting or watch:
                reasons: list[str] = []
                if stale:
                    reasons.append(f"{stale} stale memory lessons need review")
                if conflicting:
                    reasons.append(f"{conflicting} conflicting memory lessons need review")
                if watch:
                    reasons.append(f"{watch} watch-status lessons should be checked before reuse")
                suggestions.append(
                    self._suggestion(
                        kind="caution_memory_review",
                        title="Review memory hygiene before leaning on old guidance.",
                        summary="Review memory hygiene before leaning on old guidance.",
                        target="memory_hygiene",
                        reasons=reasons,
                        warnings=[],
                        evidence_refs=[".cambrian/memory/hygiene.yaml"],
                        next_commands=["cambrian memory hygiene", "cambrian memory review"],
                        evidence_sources=len(reasons),
                        repeated_signal=conflicting > 0 or stale > 1,
                        priority="high" if conflicting > 0 else "medium",
                    )
                )
        return suggestions

    def _build_note_followup_suggestions(
        self,
        *,
        root: Path,
        notes: list,
        request: str | None,
    ) -> list[HarnessSuggestion]:
        suggestions: list[HarnessSuggestion] = []
        open_high_notes = [
            note for note in notes
            if str(getattr(note, "status", "open")) == "open"
            and str(getattr(note, "severity", "")) == "high"
        ]
        if not open_high_notes:
            return suggestions
        note = open_high_notes[0]
        reasons = [str(getattr(note, "text", ""))]
        if getattr(note, "stage", None):
            reasons.append(f"linked stage: {note.stage}")
        if request:
            reasons.append("this request-aware suggestion should account for an unresolved high-severity note")
        notes_dir = default_notes_dir(root)
        note_path = ""
        if notes_dir.exists():
            for path in notes_dir.glob("note_*.yaml"):
                try:
                    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                except Exception:
                    continue
                if str(payload.get("note_id", "")) == str(getattr(note, "note_id", "")):
                    note_path = _relative_to_project(path, root)
                    break
        suggestions.append(
            self._suggestion(
                kind="note_followup",
                title="Follow up on an open high-severity note before broadening the harness.",
                summary="Follow up on an open high-severity note before broadening the harness.",
                target=str(getattr(note, "note_id", "")),
                reasons=reasons,
                warnings=[],
                evidence_refs=[note_path] if note_path else [],
                next_commands=["cambrian notes list --status open --severity high"],
                evidence_sources=len(reasons),
                repeated_signal=len(open_high_notes) > 1,
                priority="high",
            )
        )
        return suggestions

    def _suggestion(
        self,
        *,
        kind: str,
        title: str,
        summary: str,
        target: str | None,
        reasons: list[str],
        warnings: list[str],
        evidence_refs: list[str],
        next_commands: list[str],
        evidence_sources: int,
        repeated_signal: bool,
        priority: str,
    ) -> HarnessSuggestion:
        suggestion_id = f"suggest-{kind}-{_stamp()}"
        confidence = 0.5
        if evidence_sources >= 2:
            confidence += 0.1
        if reasons and warnings:
            confidence += 0.05
        if repeated_signal:
            confidence += 0.1
        if len(reasons) >= 3:
            confidence += 0.1
        if priority == "high":
            confidence += 0.05
        return HarnessSuggestion(
            suggestion_id=suggestion_id,
            kind=kind,
            title=title,
            summary=summary,
            confidence=_clamp(confidence),
            priority=priority,
            target=target,
            reasons=_dedupe(reasons),
            warnings=_dedupe(warnings),
            evidence_refs=_dedupe(evidence_refs),
            next_commands=_dedupe(next_commands),
        )

    @staticmethod
    def _kind_counts(suggestions: list[HarnessSuggestion]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in suggestions:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    @staticmethod
    def _sort_suggestions(suggestions: list[HarnessSuggestion]) -> list[HarnessSuggestion]:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            suggestions,
            key=lambda item: (
                priority_order.get(item.priority, 3),
                -item.confidence,
                item.kind,
                item.suggestion_id,
            ),
        )


def compact_harness_evolution_hint(report: HarnessEvolutionReport) -> str | None:
    """status용 compact evolution hint를 반환한다."""
    if not report.suggestions:
        return None
    top = report.suggestions[0]
    return top.summary


def render_harness_evolution(report: HarnessEvolutionReport) -> str:
    """하네스 진화 제안 보고서를 사람용 텍스트로 렌더링한다."""
    lines = [
        "Harness Evolution Suggestions",
        "==================================================",
        "",
        "Project:",
        f"  {report.project_name or '(unknown project)'}",
    ]
    if report.request:
        lines.extend(["", "Request:", f"  {report.request}"])
    if report.suggestions:
        lines.extend(["", "Top suggestions:"])
        for index, item in enumerate(report.suggestions[:_MAX_TOP_SUGGESTIONS], start=1):
            lines.append(f"  {index}. {item.summary}")
            if item.reasons:
                lines.append("     why:")
                for reason in item.reasons[:3]:
                    lines.append(f"       - {reason}")
            if item.next_commands:
                lines.append(f"     next: {item.next_commands[0]}")
    else:
        lines.extend(["", "Top suggestions:", "  no strong harness changes suggested yet"])
    next_commands = report.summary.get("next_commands", []) if isinstance(report.summary, dict) else []
    if isinstance(next_commands, list) and next_commands:
        lines.extend(["", "Next:"])
        for command in next_commands[:4]:
            lines.append(f"  {command}")
    return "\n".join(lines)
