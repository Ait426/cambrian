"""Cambrian 프로젝트 agent passport export/import."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_agent_history import (
    AgentPassportHistory,
    AgentPassportHistoryStore,
    AgentWorkRecord,
    default_agent_passport_path,
    default_dispatch_log_path,
)
from engine.project_agents import (
    AgentPassport,
    AgentRegistry,
    AgentRegistryBuilder,
    AgentRegistryStore,
    default_agent_registry_path,
)
from engine.project_harness import (
    HarnessProfile,
    HarnessProfileBuilder,
    HarnessProfileStore,
    default_harness_profile_path,
)

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


def _dedupe(items: list[str]) -> list[str]:
    """순서를 유지하면서 중복 문자열을 제거한다."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _load_yaml(path: Path) -> dict:
    """YAML 파일을 dict로 읽는다."""
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML 최상위는 dict여야 합니다: {path}")
    return payload


def default_agent_exports_dir(project_root: Path) -> Path:
    """기본 export 디렉터리 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "exports"


def default_imported_agents_dir(project_root: Path) -> Path:
    """기본 imported passport 디렉터리 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "imported"


def default_imported_agent_path(project_root: Path, agent_id: str) -> Path:
    """기본 imported agent 파일 경로를 반환한다."""
    return default_imported_agents_dir(project_root) / f"{agent_id}.yaml"


@dataclass
class ExportedAgentPassport:
    """다른 프로젝트로 옮길 수 있는 agent passport export 스냅샷."""

    schema_version: str
    exported_at: str
    export_id: str
    source_project_name: str | None
    source_harness_id: str | None
    source_harness: dict
    agent_id: str
    role_id: str
    label: str
    description: str
    passport_summary: dict
    strengths: list[str]
    risks: list[str]
    preferred_signals: list[str]
    required_harness_conditions: list[str]
    blocked_conditions: list[str]
    tags: list[str]
    source_refs: dict
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ImportedAgentRecord:
    """현재 프로젝트에 import된 외부 agent 기록."""

    imported_at: str
    import_id: str
    agent_id: str
    source_export_path: str
    source_project_name: str | None
    source_harness_id: str | None
    compatibility: dict
    local_status: str
    notes: list[str]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


def load_exported_agent_passport(path: Path) -> ExportedAgentPassport:
    """exported passport 파일을 읽는다."""
    payload = _load_yaml(Path(path).resolve())
    return ExportedAgentPassport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        exported_at=str(payload.get("exported_at", "")),
        export_id=str(payload.get("export_id", "")),
        source_project_name=str(payload.get("source_project_name")) if payload.get("source_project_name") is not None else None,
        source_harness_id=str(payload.get("source_harness_id")) if payload.get("source_harness_id") is not None else None,
        source_harness=dict(payload.get("source_harness", {})) if isinstance(payload.get("source_harness"), dict) else {},
        agent_id=str(payload.get("agent_id", "")),
        role_id=str(payload.get("role_id", "")),
        label=str(payload.get("label", "")),
        description=str(payload.get("description", "")),
        passport_summary=dict(payload.get("passport_summary", {})) if isinstance(payload.get("passport_summary"), dict) else {},
        strengths=[str(item) for item in payload.get("strengths", []) if item],
        risks=[str(item) for item in payload.get("risks", []) if item],
        preferred_signals=[str(item) for item in payload.get("preferred_signals", []) if item],
        required_harness_conditions=[str(item) for item in payload.get("required_harness_conditions", []) if item],
        blocked_conditions=[str(item) for item in payload.get("blocked_conditions", []) if item],
        tags=[str(item) for item in payload.get("tags", []) if item],
        source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def load_imported_agent_documents(project_root: Path) -> list[dict]:
    """현재 프로젝트 imported agent 문서를 모두 읽는다."""
    root = Path(project_root).resolve()
    imported_dir = default_imported_agents_dir(root)
    if not imported_dir.exists():
        return []
    documents: list[dict] = []
    for path in sorted(imported_dir.glob("*.yaml")):
        try:
            payload = _load_yaml(path)
        except Exception as exc:  # pragma: no cover - 방어 로깅
            logger.warning("imported agent 문서 읽기 실패: %s (%s)", path, exc)
            continue
        payload["__path__"] = str(path.resolve())
        documents.append(payload)
    return documents


def update_imported_agent_local_status(project_root: Path, agent_id: str, local_status: str) -> Path | None:
    """imported agent 문서의 local_status를 갱신한다."""
    path = default_imported_agent_path(project_root, agent_id)
    if not path.exists():
        return None
    payload = _load_yaml(path)
    record = dict(payload.get("record", {})) if isinstance(payload.get("record"), dict) else {}
    record["local_status"] = str(local_status)
    payload["record"] = record
    _atomic_write_text(
        path,
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
    )
    return path


def build_imported_agent_passport(document: dict) -> AgentPassport:
    """imported agent 문서를 registry용 AgentPassport로 변환한다."""
    passport_payload = dict(document.get("passport", {})) if isinstance(document.get("passport"), dict) else {}
    record_payload = dict(document.get("record", {})) if isinstance(document.get("record"), dict) else {}
    compatibility = dict(record_payload.get("compatibility", {})) if isinstance(record_payload.get("compatibility"), dict) else {}
    passport = load_exported_agent_passport_from_payload(passport_payload)
    local_status = str(record_payload.get("local_status", "imported"))
    status = "equipped" if local_status == "equipped" else ("disabled" if local_status == "disabled" else "available")
    totals = dict(passport.passport_summary.get("totals", {})) if isinstance(passport.passport_summary.get("totals"), dict) else {}
    stats = dict(totals)
    stats.update(
        {
            "imported": True,
            "compatibility_status": str(compatibility.get("status", "weak")),
            "compatibility_score": float(compatibility.get("score", 0.0) or 0.0),
            "compatibility_reasons": [str(item) for item in compatibility.get("reasons", []) if item],
            "source_project_name": passport.source_project_name,
            "source_harness_id": passport.source_harness_id,
            "import_id": str(record_payload.get("import_id", "")),
            "source_export_path": str(record_payload.get("source_export_path", "")),
        }
    )
    fit_notes = _dedupe(
        [str(item) for item in passport.passport_summary.get("fit_hints", []) if item]
        + [str(item) for item in compatibility.get("reasons", []) if item]
        + [str(item) for item in record_payload.get("notes", []) if item]
    )
    warnings = _dedupe(
        [str(item) for item in passport.warnings if item]
        + [str(item) for item in record_payload.get("warnings", []) if item]
    )
    return AgentPassport(
        schema_version=passport.schema_version,
        agent_id=passport.agent_id,
        role_id=passport.role_id,
        label=passport.label,
        description=passport.description,
        strengths=list(passport.strengths),
        risks=list(passport.risks),
        preferred_signals=list(passport.preferred_signals),
        required_harness_conditions=list(passport.required_harness_conditions),
        blocked_conditions=list(passport.blocked_conditions),
        source_kind="imported",
        status=status,
        project_fit_notes=fit_notes,
        stats=stats,
        tags=list(passport.tags),
        warnings=warnings,
    )


def load_exported_agent_passport_from_payload(payload: dict) -> ExportedAgentPassport:
    """dict payload에서 exported passport를 복원한다."""
    return ExportedAgentPassport(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        exported_at=str(payload.get("exported_at", "")),
        export_id=str(payload.get("export_id", "")),
        source_project_name=str(payload.get("source_project_name")) if payload.get("source_project_name") is not None else None,
        source_harness_id=str(payload.get("source_harness_id")) if payload.get("source_harness_id") is not None else None,
        source_harness=dict(payload.get("source_harness", {})) if isinstance(payload.get("source_harness"), dict) else {},
        agent_id=str(payload.get("agent_id", "")),
        role_id=str(payload.get("role_id", "")),
        label=str(payload.get("label", "")),
        description=str(payload.get("description", "")),
        passport_summary=dict(payload.get("passport_summary", {})) if isinstance(payload.get("passport_summary"), dict) else {},
        strengths=[str(item) for item in payload.get("strengths", []) if item],
        risks=[str(item) for item in payload.get("risks", []) if item],
        preferred_signals=[str(item) for item in payload.get("preferred_signals", []) if item],
        required_harness_conditions=[str(item) for item in payload.get("required_harness_conditions", []) if item],
        blocked_conditions=[str(item) for item in payload.get("blocked_conditions", []) if item],
        tags=[str(item) for item in payload.get("tags", []) if item],
        source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


class AgentCompatibilityChecker:
    """현재 harness와 exported passport의 적합도를 계산한다."""

    def check(self, project_root: Path, exported_passport: ExportedAgentPassport) -> dict:
        """compatibility 상태, 점수, 이유를 계산한다."""
        root = Path(project_root).resolve()
        harness = self._load_harness(root)
        score = 0.2
        reasons: list[str] = []

        source_harness = exported_passport.source_harness if isinstance(exported_passport.source_harness, dict) else {}
        current_stack = {str(item).lower() for item in harness.stack}
        source_stack = {str(item).lower() for item in source_harness.get("stack", []) if item}
        if harness.project_type and str(source_harness.get("project_type", "")).lower() == str(harness.project_type).lower():
            score += 0.15
            reasons.append(f"source project type matches current harness ({harness.project_type})")
        overlap = sorted(current_stack & source_stack)
        if overlap:
            score += min(0.2, 0.05 * len(overlap))
            reasons.append(f"stack overlap found: {', '.join(overlap)}")

        if harness.test_command and source_harness.get("test_command"):
            score += 0.15
            reasons.append("current harness uses a test command and the exported agent worked with tests")

        if self._role_matches_use_case(exported_passport.role_id, harness.primary_use_cases):
            score += 0.2
            reasons.append(f"primary use case matches role {exported_passport.role_id}")

        for condition in exported_passport.required_harness_conditions:
            matched, reason = self._check_required_condition(harness, condition)
            if matched:
                score += 0.08
                reasons.append(reason)
            else:
                reasons.append(reason)

        blocked_reasons: list[str] = []
        for condition in exported_passport.blocked_conditions:
            hit, reason = self._check_blocked_condition(harness, condition)
            if hit:
                blocked_reasons.append(reason)

        summary = exported_passport.passport_summary if isinstance(exported_passport.passport_summary, dict) else {}
        recent_wins = [str(item) for item in summary.get("recent_wins", []) if item]
        if recent_wins:
            score += 0.06
            reasons.append(f"recent win: {recent_wins[0]}")

        fit_hints = [str(item) for item in summary.get("fit_hints", []) if item]
        if fit_hints:
            reasons.append(f"fit hint: {fit_hints[0]}")

        score = max(0.0, min(1.0, score))
        if blocked_reasons:
            return {
                "status": "blocked",
                "score": round(score, 2),
                "reasons": _dedupe(blocked_reasons + reasons),
            }
        if score >= 0.75:
            status = "good"
        elif score >= 0.5:
            status = "partial"
        elif score >= 0.25:
            status = "weak"
        else:
            status = "blocked"
        return {
            "status": status,
            "score": round(score, 2),
            "reasons": _dedupe(reasons),
        }

    @staticmethod
    def _load_harness(project_root: Path) -> HarnessProfile:
        """현재 프로젝트 harness를 읽거나 즉석 생성한다."""
        path = default_harness_profile_path(project_root)
        if path.exists():
            return HarnessProfileStore().load(path)
        return HarnessProfileBuilder().build(project_root)

    @staticmethod
    def _role_matches_use_case(role_id: str, primary_use_cases: list[str]) -> bool:
        """role과 primary use case의 대략적 일치를 계산한다."""
        lowered_role = str(role_id).lower()
        lowered_use_cases = {str(item).lower() for item in primary_use_cases}
        if lowered_role in lowered_use_cases:
            return True
        if lowered_role == "bug_fix" and {"bug_fix", "bug-fix", "bugfix"} & lowered_use_cases:
            return True
        if lowered_role == "docs_update" and {"docs_update", "docs-update", "docs"} & lowered_use_cases:
            return True
        if lowered_role == "small_refactor" and {"small_refactor", "small-refactor", "refactor"} & lowered_use_cases:
            return True
        return False

    @staticmethod
    def _check_required_condition(harness: HarnessProfile, condition: str) -> tuple[bool, str]:
        """required_harness_conditions 매칭 여부를 계산한다."""
        lowered = str(condition).strip().lower()
        if lowered == "test command available":
            if harness.test_command:
                return True, "current harness uses pytest-like test command"
            return False, "required condition missing: test command available"
        if lowered == "explicit apply":
            if bool(harness.safety.get("explicit_adoption_only", False)):
                return True, "current harness keeps explicit apply/adoption only"
            return False, "required condition missing: explicit apply"
        if lowered == "project memory available":
            if int(harness.memory_summary.get("lessons_count", 0) or 0) > 0:
                return True, "project memory is available"
            return False, "required condition missing: project memory available"
        if lowered == "preserve source artifacts":
            if bool(harness.safety.get("preserve_source_artifacts", False)):
                return True, "current harness preserves source artifacts"
            return False, "required condition missing: preserve source artifacts"
        return True, f"condition noted: {condition}"

    @staticmethod
    def _check_blocked_condition(harness: HarnessProfile, condition: str) -> tuple[bool, str]:
        """blocked condition 충돌 여부를 계산한다."""
        lowered = str(condition).strip().lower()
        if lowered == "no test command" and not harness.test_command:
            return True, "blocked: current harness has no test command"
        return False, f"blocked condition not hit: {condition}"


class AgentPassportExporter:
    """현재 프로젝트 agent passport를 export한다."""

    def export(self, project_root: Path, agent_id: str, out_path: Path | None = None) -> Path:
        """agent passport export 파일을 생성한다."""
        root = Path(project_root).resolve()
        harness = self._load_harness(root)
        registry = self._load_registry(root, harness)
        agent = self._find_agent(registry, agent_id)
        if agent is None:
            raise KeyError(agent_id)

        history_path = default_agent_passport_path(root, agent_id)
        history = self._load_history(history_path)
        export = ExportedAgentPassport(
            schema_version=SCHEMA_VERSION,
            exported_at=_now(),
            export_id=f"export-{agent.agent_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            source_project_name=harness.project_name,
            source_harness_id=harness.harness_id,
            source_harness={
                "project_type": harness.project_type,
                "stack": list(harness.stack),
                "test_command": harness.test_command,
                "primary_use_cases": list(harness.primary_use_cases),
                "mode": harness.mode,
            },
            agent_id=agent.agent_id,
            role_id=agent.role_id,
            label=agent.label,
            description=agent.description,
            passport_summary={
                "status": history.status,
                "totals": dict(history.totals),
                "recent_wins": list(history.recent_wins),
                "recent_risks": list(history.recent_risks),
                "fit_hints": list(history.fit_hints),
            },
            strengths=list(agent.strengths),
            risks=list(agent.risks),
            preferred_signals=list(agent.preferred_signals),
            required_harness_conditions=list(agent.required_harness_conditions),
            blocked_conditions=list(agent.blocked_conditions),
            tags=list(agent.tags),
            source_refs={
                "passport_path": _relative(history_path, root),
                "registry_path": _relative(default_agent_registry_path(root), root),
                "harness_path": _relative(default_harness_profile_path(root), root),
                "dispatch_log_path": _relative(default_dispatch_log_path(root), root),
            },
            warnings=_dedupe(list(agent.warnings) + list(history.warnings)),
            errors=_dedupe(list(history.errors)),
        )
        target = Path(out_path).resolve() if out_path is not None else default_agent_exports_dir(root) / f"{agent.agent_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.yaml"
        _atomic_write_text(
            target,
            yaml.safe_dump(export.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    @staticmethod
    def _load_harness(project_root: Path) -> HarnessProfile:
        """현재 harness를 읽거나 즉석 생성한다."""
        path = default_harness_profile_path(project_root)
        if path.exists():
            return HarnessProfileStore().load(path)
        return HarnessProfileBuilder().build(project_root)

    @staticmethod
    def _load_registry(project_root: Path, harness: HarnessProfile) -> AgentRegistry:
        """현재 registry를 읽거나 즉석 생성한다."""
        path = default_agent_registry_path(project_root)
        if path.exists():
            return AgentRegistryStore().load(path)
        return AgentRegistryBuilder().build(project_root, harness=harness)

    @staticmethod
    def _find_agent(registry: AgentRegistry, agent_id: str) -> AgentPassport | None:
        """registry에서 agent를 찾는다."""
        target = agent_id.strip()
        for agent in registry.agents:
            if agent.agent_id == target:
                return agent
        return None

    @staticmethod
    def _load_history(path: Path) -> AgentPassportHistory:
        """history 파일을 읽거나 비어 있는 history를 만든다."""
        if path.exists():
            return AgentPassportHistoryStore().load(path)
        return AgentPassportHistory(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            agent_id=path.stem,
            role_id="",
            label=path.stem,
            description="",
            project_name=None,
            harness_id=None,
            status="available",
            totals={
                "sessions_seen": 0,
                "requests_seen": 0,
                "diagnoses": 0,
                "patch_intents": 0,
                "patch_proposals": 0,
                "validations_passed": 0,
                "validations_failed": 0,
                "adoptions": 0,
                "notes_linked": 0,
            },
            recent_wins=[],
            recent_risks=[],
            fit_hints=[],
            work_records=[],
        )


class AgentPassportImporter:
    """외부 passport 파일을 현재 프로젝트에 import한다."""

    def import_passport(self, project_root: Path, passport_path: Path, equip: bool = False) -> ImportedAgentRecord:
        """passport 파일을 가져와 imported record로 저장한다."""
        root = Path(project_root).resolve()
        exported = load_exported_agent_passport(Path(passport_path).resolve())
        self._validate_export(exported)

        harness = self._load_harness(root)
        registry = self._load_registry(root, harness)
        if any(agent.agent_id == exported.agent_id for agent in registry.agents):
            raise ValueError(f"agent id already exists in current registry: {exported.agent_id}")

        compatibility = AgentCompatibilityChecker().check(root, exported)
        local_status = "equipped" if equip and compatibility.get("status") != "blocked" else "imported"
        notes = _dedupe(
            [str(item) for item in compatibility.get("reasons", []) if item]
            + [f"imported from {exported.source_project_name}" if exported.source_project_name else ""]
        )
        record = ImportedAgentRecord(
            imported_at=_now(),
            import_id=f"import-{exported.agent_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            agent_id=exported.agent_id,
            source_export_path=str(Path(passport_path).resolve()),
            source_project_name=exported.source_project_name,
            source_harness_id=exported.source_harness_id,
            compatibility=compatibility,
            local_status=local_status,
            notes=notes,
            warnings=["equip requested but compatibility is blocked"] if equip and compatibility.get("status") == "blocked" else [],
        )
        target = default_imported_agent_path(root, exported.agent_id)
        document = {
            "schema_version": SCHEMA_VERSION,
            "passport": exported.to_dict(),
            "record": record.to_dict(),
        }
        _atomic_write_text(
            target,
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        )
        return record

    @staticmethod
    def _validate_export(exported: ExportedAgentPassport) -> None:
        """export 필수 필드를 검증한다."""
        if not exported.agent_id or not exported.role_id:
            raise ValueError("invalid exported passport: missing agent_id/role_id")

    @staticmethod
    def _load_harness(project_root: Path) -> HarnessProfile:
        """현재 harness를 읽거나 즉석 생성한다."""
        path = default_harness_profile_path(project_root)
        if path.exists():
            return HarnessProfileStore().load(path)
        return HarnessProfileBuilder().build(project_root)

    @staticmethod
    def _load_registry(project_root: Path, harness: HarnessProfile) -> AgentRegistry:
        """현재 registry를 읽거나 즉석 생성한다."""
        path = default_agent_registry_path(project_root)
        if path.exists():
            return AgentRegistryStore().load(path)
        return AgentRegistryBuilder().build(project_root, harness=harness)


def render_agent_export_result(exported: ExportedAgentPassport, saved_path: Path) -> str:
    """agent export 결과를 사람용 텍스트로 렌더링한다."""
    lines = [
        "Agent passport exported.",
        "",
        "Agent:",
        f"  {exported.agent_id}",
        "",
        "Source project:",
        f"  {exported.source_project_name or '(unknown)'}",
        "",
        "Saved:",
        f"  {saved_path}",
    ]
    return "\n".join(lines)


def render_agent_import_result(record: ImportedAgentRecord, saved_path: Path) -> str:
    """agent import 결과를 사람용 텍스트로 렌더링한다."""
    compatibility = dict(record.compatibility) if isinstance(record.compatibility, dict) else {}
    lines = [
        "Agent passport imported.",
        "",
        "Agent:",
        f"  {record.agent_id}",
        "",
        "Compatibility:",
        f"  {compatibility.get('status', 'unknown')}",
    ]
    reasons = [str(item) for item in compatibility.get("reasons", []) if item]
    if reasons:
        lines.extend(["", "Why:"])
        for item in reasons[:4]:
            lines.append(f"  - {item}")
    lines.extend(
        [
            "",
            "Saved:",
            f"  {saved_path}",
            "",
            "Next:",
            f"  cambrian agent show {record.agent_id}",
            '  cambrian agent recommend "로그인 에러 수정해"',
        ]
    )
    return "\n".join(lines)
