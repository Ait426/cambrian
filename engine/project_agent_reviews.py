"""Cambrian 프로젝트용 agent review 저장소."""

from __future__ import annotations

import logging
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_agents import AgentRegistryStore, default_agent_registry_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
_TERMINAL_SESSION_STAGES = {"adopted", "completed", "closed", "error"}
_VALID_RATINGS = {"strong", "good", "mixed", "weak"}
_VALID_REVIEW_KINDS = {"performance", "risk", "praise", "caution", "fit"}
_VALID_REVIEW_STATUS = {"open", "acknowledged"}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    """파일명용 UTC 시각 문자열을 반환한다."""
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


def _load_yaml(path: Path) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("YAML 읽기 실패: %s (%s)", path, exc)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("YAML 형식 오류: %s", path)
        return None
    return payload


def _relative_to_project(path: Path, project_root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_agent_reviews_dir(project_root: Path) -> Path:
    """agent review 디렉터리 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "reviews"


@dataclass
class AgentReview:
    """특정 agent에 대한 사람 평가."""

    schema_version: str
    review_id: str
    created_at: str
    updated_at: str | None
    agent_id: str
    role_id: str | None
    project_name: str | None
    harness_id: str | None
    status: str
    rating: str
    review_kind: str
    text: str
    summary: str | None
    resolution: str | None
    session_id: str | None
    session_ref: str | None
    stage: str | None
    user_request: str | None
    artifact_refs: list[str]
    tags: list[str]
    context: dict
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class AgentReviewSummary:
    """agent review 요약."""

    total: int
    strong: int
    good: int
    mixed: int
    weak: int
    recent_positive: list[str]
    recent_cautions: list[str]

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class AgentReviewStore:
    """agent review 저장/로드."""

    def add(self, review: AgentReview, reviews_dir: Path) -> Path:
        """review를 새 파일로 저장한다."""
        target_dir = Path(reviews_dir).resolve()
        safe_agent_id = str(review.agent_id).replace("/", "-").replace("\\", "-")
        path = target_dir / f"review_{_stamp()}_{safe_agent_id}_{secrets.token_hex(2)}.yaml"
        _atomic_write_text(
            path,
            yaml.safe_dump(review.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return path

    def load(self, path: Path) -> AgentReview:
        """저장된 review를 읽는다."""
        payload = _load_yaml(Path(path).resolve())
        if payload is None:
            raise FileNotFoundError(path)
        return AgentReview(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            review_id=str(payload.get("review_id", "")),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at")) if payload.get("updated_at") is not None else None,
            agent_id=str(payload.get("agent_id", "")),
            role_id=str(payload.get("role_id")) if payload.get("role_id") is not None else None,
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            status=str(payload.get("status", "open")),
            rating=str(payload.get("rating", "good")),
            review_kind=str(payload.get("review_kind", "performance")),
            text=str(payload.get("text", "")),
            summary=str(payload.get("summary")) if payload.get("summary") is not None else None,
            resolution=str(payload.get("resolution")) if payload.get("resolution") is not None else None,
            session_id=str(payload.get("session_id")) if payload.get("session_id") is not None else None,
            session_ref=str(payload.get("session_ref")) if payload.get("session_ref") is not None else None,
            stage=str(payload.get("stage")) if payload.get("stage") is not None else None,
            user_request=str(payload.get("user_request")) if payload.get("user_request") is not None else None,
            artifact_refs=[str(item) for item in payload.get("artifact_refs", []) if item],
            tags=[str(item) for item in payload.get("tags", []) if item],
            context=dict(payload.get("context", {})) if isinstance(payload.get("context"), dict) else {},
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )

    def list(
        self,
        reviews_dir: Path,
        *,
        agent_id: str | None = None,
        rating: str | None = None,
        status: str | None = None,
    ) -> list[AgentReview]:
        """review 목록을 필터링해 반환한다."""
        directory = Path(reviews_dir).resolve()
        if not directory.exists():
            return []
        reviews: list[AgentReview] = []
        for path in sorted(directory.glob("review_*.yaml"), key=lambda item: (item.stat().st_mtime, item.name), reverse=True):
            try:
                review = self.load(path)
            except Exception as exc:
                logger.warning("agent review load failed: %s (%s)", path, exc)
                continue
            if agent_id and review.agent_id != agent_id:
                continue
            if rating and review.rating != rating:
                continue
            if status and review.status != status:
                continue
            reviews.append(review)
        return reviews

    def acknowledge(self, review_path: Path, resolution: str | None = None) -> Path:
        """review를 acknowledged로 갱신한다."""
        path = Path(review_path).resolve()
        review = self.load(path)
        review.status = "acknowledged"
        review.updated_at = _now()
        review.resolution = resolution
        _atomic_write_text(
            path,
            yaml.safe_dump(review.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return path


class AgentReviewBuilder:
    """agent review payload를 만든다."""

    def build(
        self,
        project_root: Path,
        agent_id: str,
        text: str,
        rating: str = "good",
        review_kind: str = "performance",
        tags: list[str] | None = None,
        session_ref: str | None = None,
        artifact_refs: list[str] | None = None,
    ) -> AgentReview:
        """review 문서를 만든다."""
        root = Path(project_root).resolve()
        normalized_rating = str(rating or "good").strip().lower()
        normalized_kind = str(review_kind or "performance").strip().lower()
        if normalized_rating not in _VALID_RATINGS:
            raise ValueError(f"invalid rating: {rating}")
        if normalized_kind not in _VALID_REVIEW_KINDS:
            raise ValueError(f"invalid review kind: {review_kind}")

        registry_path = default_agent_registry_path(root)
        if not registry_path.exists():
            raise FileNotFoundError("agent registry not found")
        registry = AgentRegistryStore().load(registry_path)
        agent = next((item for item in registry.agents if item.agent_id == agent_id), None)
        if agent is None:
            raise KeyError(agent_id)

        warnings: list[str] = []
        project_name, harness_id = self._load_project_context(root)
        session_path, session_payload = self._resolve_session_context(root, agent_id=agent_id, session_ref=session_ref, warnings=warnings)
        normalized_artifacts = self._normalize_artifact_refs(
            root,
            list(artifact_refs or []),
            session_payload=session_payload,
        )
        review_id = f"review-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
        summary_text = self._summary_text(text)
        session_id = None
        stage = None
        user_request = None
        context: dict = {
            "workspace": ".",
        }
        if session_payload:
            session_id = str(session_payload.get("session_id")) if session_payload.get("session_id") is not None else None
            stage = str(session_payload.get("current_stage") or session_payload.get("status")) if (session_payload.get("current_stage") or session_payload.get("status")) is not None else None
            user_request = str(session_payload.get("user_request")) if session_payload.get("user_request") is not None else None
            context["next_command"] = self._primary_next_command(session_payload)
            agent_context = dict(session_payload.get("agent_context", {})) if isinstance(session_payload.get("agent_context"), dict) else {}
            context["lead_agent"] = agent_context.get("lead_agent_id")
            context["supporting_agents"] = list(agent_context.get("supporting_agent_ids", [])) if isinstance(agent_context.get("supporting_agent_ids"), list) else []

        return AgentReview(
            schema_version=SCHEMA_VERSION,
            review_id=review_id,
            created_at=_now(),
            updated_at=None,
            agent_id=agent.agent_id,
            role_id=agent.role_id,
            project_name=project_name,
            harness_id=harness_id,
            status="open",
            rating=normalized_rating,
            review_kind=normalized_kind,
            text=str(text).strip(),
            summary=summary_text,
            resolution=None,
            session_id=session_id,
            session_ref=_relative_to_project(session_path, root) if session_path is not None else None,
            stage=stage,
            user_request=user_request,
            artifact_refs=normalized_artifacts,
            tags=_dedupe([str(item) for item in (tags or []) if item]),
            context=context,
            warnings=_dedupe(warnings),
            errors=[],
        )

    @staticmethod
    def _load_project_context(project_root: Path) -> tuple[str | None, str | None]:
        """project name과 harness id를 읽는다."""
        project_payload = _load_yaml(project_root / ".cambrian" / "project.yaml") or {}
        project_name = None
        project = project_payload.get("project", {})
        if isinstance(project, dict) and project.get("name") is not None:
            project_name = str(project.get("name"))
        harness_payload = _load_yaml(project_root / ".cambrian" / "harness" / "profile.yaml") or {}
        harness_id = str(harness_payload.get("harness_id")) if harness_payload.get("harness_id") is not None else None
        return project_name, harness_id

    def _resolve_session_context(
        self,
        project_root: Path,
        *,
        agent_id: str,
        session_ref: str | None,
        warnings: list[str],
    ) -> tuple[Path | None, dict | None]:
        """explicit session 또는 agent가 연결된 active session을 찾는다."""
        sessions_dir = project_root / ".cambrian" / "sessions"
        if not sessions_dir.exists():
            return None, None
        if session_ref:
            candidate = Path(session_ref)
            if candidate.exists():
                payload = _load_yaml(candidate.resolve())
                return (candidate.resolve(), payload) if payload is not None else (None, None)
            for path in sorted(sessions_dir.glob("do_session_*.yaml"), reverse=True):
                payload = _load_yaml(path)
                if not payload:
                    continue
                if str(payload.get("session_id", "")) == session_ref or path.stem == session_ref:
                    return path.resolve(), payload
            warnings.append(f"session not found: {session_ref}")
            return None, None

        candidates = sorted(
            (item for item in sessions_dir.glob("do_session_*.yaml") if item.is_file()),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        for path in candidates:
            payload = _load_yaml(path)
            if not payload:
                continue
            stage = str(payload.get("current_stage") or payload.get("status") or "unknown")
            if stage in _TERMINAL_SESSION_STAGES:
                continue
            if self._agent_linked_to_session(agent_id, payload):
                return path.resolve(), payload
        return None, None

    @staticmethod
    def _agent_linked_to_session(agent_id: str, payload: dict) -> bool:
        """session payload에 agent snapshot이 연결되어 있는지 본다."""
        harness_context = payload.get("harness_context", {})
        if isinstance(harness_context, dict):
            active_agents = [str(item) for item in harness_context.get("active_agents", []) if item]
            if agent_id in active_agents:
                return True
        agent_context = payload.get("agent_context", {})
        if isinstance(agent_context, dict):
            if str(agent_context.get("lead_agent_id") or "") == agent_id:
                return True
            supporting = [str(item) for item in agent_context.get("supporting_agent_ids", []) if item]
            if agent_id in supporting:
                return True
        return False

    @staticmethod
    def _primary_next_command(payload: dict) -> str | None:
        """session payload에서 대표 next command를 찾는다."""
        next_commands = payload.get("next_commands", [])
        if isinstance(next_commands, list):
            for item in next_commands:
                if not isinstance(item, dict):
                    continue
                if item.get("primary") and item.get("command"):
                    return str(item.get("command"))
            for item in next_commands:
                if isinstance(item, dict) and item.get("command"):
                    return str(item.get("command"))
        next_actions = payload.get("next_actions", [])
        if isinstance(next_actions, list) and next_actions:
            return str(next_actions[0])
        return None

    @staticmethod
    def _normalize_artifact_refs(project_root: Path, artifact_refs: list[str], *, session_payload: dict | None) -> list[str]:
        """artifact refs를 프로젝트 기준 경로로 정리한다."""
        normalized: list[str] = []
        for raw in artifact_refs:
            if not raw:
                continue
            candidate = Path(str(raw))
            if candidate.exists():
                normalized.append(_relative_to_project(candidate.resolve(), project_root))
            else:
                normalized.append(str(raw).replace("\\", "/"))
        if session_payload:
            artifacts = session_payload.get("artifacts", {})
            if isinstance(artifacts, dict):
                for key in (
                    "adoption_record_path",
                    "patch_proposal_path",
                    "patch_intent_path",
                    "report_path",
                    "clarification_path",
                    "context_scan_path",
                    "request_path",
                ):
                    raw_value = artifacts.get(key)
                    if raw_value:
                        normalized.append(str(raw_value).replace("\\", "/"))
                        break
        return _dedupe(normalized)

    @staticmethod
    def _summary_text(text: str) -> str | None:
        """review text에서 짧은 summary를 만든다."""
        compact = " ".join(str(text).strip().split())
        if not compact:
            return None
        return compact if len(compact) <= 96 else f"{compact[:93]}..."


def build_agent_review_summary(reviews: list[AgentReview]) -> AgentReviewSummary:
    """한 agent의 reviews를 요약한다."""
    strong = 0
    good = 0
    mixed = 0
    weak = 0
    positive: list[str] = []
    cautions: list[str] = []
    for review in reviews:
        if review.rating == "strong":
            strong += 1
        elif review.rating == "good":
            good += 1
        elif review.rating == "mixed":
            mixed += 1
        elif review.rating == "weak":
            weak += 1

        summary_text = review.summary or review.text
        if review.rating in {"strong", "good"} and review.review_kind in {"performance", "praise", "fit"}:
            positive.append(summary_text)
        if review.rating in {"mixed", "weak"} or review.review_kind in {"risk", "caution"}:
            cautions.append(summary_text)
    return AgentReviewSummary(
        total=len(reviews),
        strong=strong,
        good=good,
        mixed=mixed,
        weak=weak,
        recent_positive=_dedupe(positive)[:3],
        recent_cautions=_dedupe(cautions)[:3],
    )


def load_agent_review_summary(project_root: Path, agent_id: str) -> AgentReviewSummary:
    """현재 프로젝트의 특정 agent review summary를 만든다."""
    reviews = AgentReviewStore().list(default_agent_reviews_dir(project_root), agent_id=agent_id)
    return build_agent_review_summary(reviews)


def render_agent_review_add_summary(review: AgentReview, review_path: str) -> str:
    """review 저장 완료 메시지."""
    lines = [
        "Cambrian saved an agent review.",
        "==================================================",
        "",
        "Agent:",
        f"  {review.agent_id}",
        "",
        "Review:",
        f"  [{review.rating}][{review.review_kind}]",
        f"  {review.text}",
    ]
    if review.session_id or review.stage:
        lines.extend([
            "",
            "Linked:",
            f"  session : {review.session_id or '-'}",
            f"  stage   : {review.stage or '-'}",
        ])
    lines.extend([
        "",
        "Saved:",
        f"  {review_path}",
        "",
        "Next:",
        f"  cambrian agent reviews {review.agent_id}",
    ])
    return "\n".join(lines)


def render_agent_reviews(agent_id: str, reviews: list[AgentReview]) -> str:
    """agent reviews 목록 렌더링."""
    lines = [
        "Agent Reviews",
        "==================================================",
        "",
        "Agent:",
        f"  {agent_id}",
        "",
        "Recent:",
    ]
    if not reviews:
        lines.append("  none")
        return "\n".join(lines)
    for index, review in enumerate(reviews, start=1):
        text = review.summary or review.text
        snippet = text if len(text) <= 88 else f"{text[:85]}..."
        lines.append(f"  {index}. [{review.rating}][{review.review_kind}] {snippet}")
    return "\n".join(lines)


def render_agent_review_summary(summary: AgentReviewSummary) -> list[str]:
    """agent show/history용 review summary 줄 목록."""
    lines = [
        "Review summary:",
        f"  strong : {summary.strong}",
        f"  good   : {summary.good}",
        f"  mixed  : {summary.mixed}",
        f"  weak   : {summary.weak}",
    ]
    if summary.recent_positive:
        lines.extend(["", "Recent positive reviews:"])
        for item in summary.recent_positive[:3]:
            lines.append(f"  - {item}")
    if summary.recent_cautions:
        lines.extend(["", "Recent cautions:"])
        for item in summary.recent_cautions[:3]:
            lines.append(f"  - {item}")
    return lines


def compact_agent_review_hint(agent_id: str, summary: AgentReviewSummary) -> str | None:
    """status용 compact review hint를 만든다."""
    if summary.total <= 0:
        return None
    if summary.recent_positive and summary.recent_cautions:
        return f"{agent_id} — 최근 평가는 대체로 좋지만 주의 메모가 1건 이상 있습니다"
    if summary.recent_positive:
        return f"{agent_id} — 좋은 최근 review가 있습니다"
    if summary.recent_cautions:
        return f"{agent_id} — 열린 caution/risk review가 있습니다"
    return f"{agent_id} — review {summary.total}건이 기록돼 있습니다"
