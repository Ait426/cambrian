"""Cambrian 프로젝트 agent passport history와 dispatch log."""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

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


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


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


def _load_yaml(path: Path, warnings: list[str] | None = None) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        message = f"YAML 읽기 실패: {path} ({exc})"
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        message = f"YAML 형식 오류: {path}"
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    return payload


def _load_json(path: Path, warnings: list[str] | None = None) -> dict | None:
    """JSON 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        message = f"JSON 읽기 실패: {path} ({exc})"
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    if not isinstance(payload, dict):
        message = f"JSON 형식 오류: {path}"
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return None
    return payload


def default_agent_passports_dir(project_root: Path) -> Path:
    """agent passport history 디렉터리 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "passports"


def default_agent_passport_path(project_root: Path, agent_id: str) -> Path:
    """단일 agent passport history 경로를 반환한다."""
    return default_agent_passports_dir(project_root) / f"{agent_id}.yaml"


def default_dispatch_log_path(project_root: Path) -> Path:
    """dispatch log 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "agents" / "dispatch_log.yaml"


@dataclass
class AgentWorkRecord:
    """agent가 현재 프로젝트에서 남긴 작업 기록 한 건."""

    record_id: str
    created_at: str | None
    agent_id: str
    role_id: str
    project_name: str | None
    harness_id: str | None
    session_id: str | None
    session_stage: str | None
    user_request: str | None
    event_kind: str
    outcome: str | None
    artifact_refs: list[str]
    tags: list[str]
    summary: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class AgentPassportHistory:
    """현재 프로젝트 안에서 한 agent의 로컬 경력."""

    schema_version: str
    generated_at: str
    agent_id: str
    role_id: str
    label: str
    description: str
    project_name: str | None
    harness_id: str | None
    status: str
    totals: dict
    recent_wins: list[str]
    recent_risks: list[str]
    fit_hints: list[str]
    work_records: list[AgentWorkRecord]
    source_refs: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "agent_id": self.agent_id,
            "role_id": self.role_id,
            "label": self.label,
            "description": self.description,
            "project_name": self.project_name,
            "harness_id": self.harness_id,
            "status": self.status,
            "totals": dict(self.totals),
            "recent_wins": list(self.recent_wins),
            "recent_risks": list(self.recent_risks),
            "fit_hints": list(self.fit_hints),
            "work_records": [record.to_dict() for record in self.work_records],
            "source_refs": dict(self.source_refs),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class AgentDispatchLog:
    """현재 프로젝트 안의 agent 배치 기록."""

    schema_version: str
    generated_at: str
    project_name: str | None
    harness_id: str | None
    records: list[dict]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "project_name": self.project_name,
            "harness_id": self.harness_id,
            "records": list(self.records),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class AgentPassportHistoryStore:
    """passport history 저장/로드 도구."""

    def save(self, history: AgentPassportHistory, path: Path) -> Path:
        """passport history를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(history.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> AgentPassportHistory:
        """저장된 passport history를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if payload is None:
            raise FileNotFoundError(path)
        raw_records = payload.get("work_records", [])
        records: list[AgentWorkRecord] = []
        if isinstance(raw_records, list):
            for item in raw_records:
                if not isinstance(item, dict):
                    continue
                records.append(
                    AgentWorkRecord(
                        record_id=str(item.get("record_id", "")),
                        created_at=str(item.get("created_at")) if item.get("created_at") is not None else None,
                        agent_id=str(item.get("agent_id", "")),
                        role_id=str(item.get("role_id", "")),
                        project_name=str(item.get("project_name")) if item.get("project_name") is not None else None,
                        harness_id=str(item.get("harness_id")) if item.get("harness_id") is not None else None,
                        session_id=str(item.get("session_id")) if item.get("session_id") is not None else None,
                        session_stage=str(item.get("session_stage")) if item.get("session_stage") is not None else None,
                        user_request=str(item.get("user_request")) if item.get("user_request") is not None else None,
                        event_kind=str(item.get("event_kind", "")),
                        outcome=str(item.get("outcome")) if item.get("outcome") is not None else None,
                        artifact_refs=[str(value) for value in item.get("artifact_refs", []) if value],
                        tags=[str(value) for value in item.get("tags", []) if value],
                        summary=str(item.get("summary", "")),
                        warnings=[str(value) for value in item.get("warnings", []) if value],
                    )
                )
        return AgentPassportHistory(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            agent_id=str(payload.get("agent_id", "")),
            role_id=str(payload.get("role_id", "")),
            label=str(payload.get("label", "")),
            description=str(payload.get("description", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            status=str(payload.get("status", "available")),
            totals=dict(payload.get("totals", {})) if isinstance(payload.get("totals"), dict) else {},
            recent_wins=[str(value) for value in payload.get("recent_wins", []) if value],
            recent_risks=[str(value) for value in payload.get("recent_risks", []) if value],
            fit_hints=[str(value) for value in payload.get("fit_hints", []) if value],
            work_records=records,
            source_refs=dict(payload.get("source_refs", {})) if isinstance(payload.get("source_refs"), dict) else {},
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


class AgentDispatchLogStore:
    """dispatch log 저장/로드 도구."""

    def save(self, log: AgentDispatchLog, path: Path) -> Path:
        """dispatch log를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(log.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> AgentDispatchLog:
        """저장된 dispatch log를 로드한다."""
        payload = _load_yaml(Path(path).resolve())
        if payload is None:
            raise FileNotFoundError(path)
        return AgentDispatchLog(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            harness_id=str(payload.get("harness_id")) if payload.get("harness_id") is not None else None,
            records=list(payload.get("records", [])) if isinstance(payload.get("records"), list) else [],
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


class AgentHistoryBuilder:
    """equipped agent snapshot 기반 passport history와 dispatch log를 만든다."""

    def build_passport(self, project_root: Path, agent_id: str) -> AgentPassportHistory:
        """단일 agent passport history를 만든다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        harness = self._load_harness(root, warnings, errors)
        registry = self._load_registry(root, harness, warnings, errors)
        context = self._scan_context(root, warnings)
        agent = self._find_agent(registry, agent_id)
        if agent is None:
            raise KeyError(agent_id)
        return self._build_passport_from_context(
            root=root,
            harness=harness,
            agent=agent,
            context=context,
            warnings=warnings,
            errors=errors,
        )

    def build_all_passports(self, project_root: Path) -> list[AgentPassportHistory]:
        """현재 registry의 모든 agent passport history를 만든다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        harness = self._load_harness(root, warnings, errors)
        registry = self._load_registry(root, harness, warnings, errors)
        context = self._scan_context(root, warnings)
        passports: list[AgentPassportHistory] = []
        for agent in registry.agents:
            passports.append(
                self._build_passport_from_context(
                    root=root,
                    harness=harness,
                    agent=agent,
                    context=context,
                    warnings=list(warnings),
                    errors=list(errors),
                )
            )
        return passports

    def build_dispatch_log(self, project_root: Path) -> AgentDispatchLog:
        """현재 프로젝트 dispatch log를 만든다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        harness = self._load_harness(root, warnings, errors)
        passports = self.build_all_passports(root)
        records: list[dict] = []
        for passport in passports:
            if passport.status != "equipped":
                continue
            for record in passport.work_records:
                records.append(
                    {
                        "agent_id": passport.agent_id,
                        "role_id": passport.role_id,
                        "session_id": record.session_id,
                        "stage": record.session_stage,
                        "event_kind": record.event_kind,
                        "outcome": record.outcome,
                        "summary": record.summary,
                        "created_at": record.created_at,
                        "artifact_refs": list(record.artifact_refs),
                    }
                )
        records.sort(
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("agent_id") or ""),
                str(item.get("event_kind") or ""),
            ),
            reverse=True,
        )
        return AgentDispatchLog(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            project_name=harness.project_name if harness is not None else None,
            harness_id=harness.harness_id if harness is not None else None,
            records=records,
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    @staticmethod
    def _load_harness(
        project_root: Path,
        warnings: list[str],
        errors: list[str],
    ) -> HarnessProfile | None:
        """현재 하네스를 읽거나 즉시 구성한다."""
        path = default_harness_profile_path(project_root)
        try:
            if path.exists():
                return HarnessProfileStore().load(path)
            return HarnessProfileBuilder().build(project_root)
        except Exception as exc:
            message = f"harness load failed: {exc}"
            logger.warning(message)
            warnings.append(message)
            errors.append(message)
            return None

    @staticmethod
    def _load_registry(
        project_root: Path,
        harness: HarnessProfile | None,
        warnings: list[str],
        errors: list[str],
    ) -> AgentRegistry:
        """현재 registry를 읽거나 즉시 구성한다."""
        path = default_agent_registry_path(project_root)
        try:
            if path.exists():
                return AgentRegistryStore().load(path)
            return AgentRegistryBuilder().build(project_root, harness=harness)
        except Exception as exc:
            message = f"agent registry load failed: {exc}"
            logger.warning(message)
            warnings.append(message)
            errors.append(message)
            return AgentRegistry(
                schema_version=SCHEMA_VERSION,
                generated_at=_now(),
                harness_id=harness.harness_id if harness is not None else None,
                agents=[],
                warnings=[message],
                errors=[message],
            )

    @staticmethod
    def _find_agent(registry: AgentRegistry, agent_id: str) -> AgentPassport | None:
        """registry 안에서 agent를 찾는다."""
        for agent in registry.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def _scan_context(self, project_root: Path, warnings: list[str]) -> dict:
        """history 계산에 필요한 artifact들을 읽는다."""
        root = Path(project_root).resolve()
        sessions = self._scan_yaml_dir(root / ".cambrian" / "sessions", "do_session_*.yaml", warnings, root)
        requests = self._scan_yaml_dir(root / ".cambrian" / "requests", "request_*.yaml", warnings, root)
        proposals = self._scan_yaml_dir(root / ".cambrian" / "patches", "patch_proposal_*.yaml", warnings, root)
        adoptions = self._scan_json_dir(root / ".cambrian" / "adoptions", "adoption_*.json", warnings, root)
        notes = self._scan_yaml_dir(root / ".cambrian" / "notes", "note_*.yaml", warnings, root)
        lessons = _load_yaml(root / ".cambrian" / "memory" / "lessons.yaml", warnings) or {}
        sessions_by_id = {
            str(item.get("session_id", "")): item
            for item in sessions
            if str(item.get("session_id", "")).strip()
        }
        proposal_session_map: dict[str, str] = {}
        for proposal in proposals:
            proposal_path = str(proposal.get("_artifact_path", ""))
            session = self._find_session_for_proposal(proposal, proposal_path, sessions)
            if session is not None and proposal_path:
                proposal_session_map[proposal_path] = str(session.get("session_id", ""))
        return {
            "sessions": sessions,
            "requests": requests,
            "proposals": proposals,
            "adoptions": adoptions,
            "notes": notes,
            "lessons": lessons,
            "sessions_by_id": sessions_by_id,
            "proposal_session_map": proposal_session_map,
        }

    @staticmethod
    def _scan_yaml_dir(
        directory: Path,
        pattern: str,
        warnings: list[str],
        project_root: Path,
    ) -> list[dict]:
        """디렉터리 아래 YAML artifact들을 읽는다."""
        if not directory.exists():
            return []
        items: list[dict] = []
        for path in sorted(directory.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name)):
            payload = _load_yaml(path, warnings)
            if payload is None:
                continue
            payload["_artifact_path"] = _relative(path, project_root)
            items.append(payload)
        return items

    @staticmethod
    def _scan_json_dir(
        directory: Path,
        pattern: str,
        warnings: list[str],
        project_root: Path,
    ) -> list[dict]:
        """디렉터리 아래 JSON artifact들을 읽는다."""
        if not directory.exists():
            return []
        items: list[dict] = []
        for path in sorted(directory.glob(pattern), key=lambda item: (item.stat().st_mtime, item.name)):
            payload = _load_json(path, warnings)
            if payload is None:
                continue
            payload["_artifact_path"] = _relative(path, project_root)
            items.append(payload)
        return items

    @staticmethod
    def _active_agents_from_payload(payload: dict | None) -> list[str]:
        """artifact payload에서 active agent snapshot을 꺼낸다."""
        if not isinstance(payload, dict):
            return []
        harness_context = payload.get("harness_context")
        if not isinstance(harness_context, dict):
            return []
        return [str(item) for item in harness_context.get("active_agents", []) if item]

    def _build_passport_from_context(
        self,
        *,
        root: Path,
        harness: HarnessProfile | None,
        agent: AgentPassport,
        context: dict,
        warnings: list[str],
        errors: list[str],
    ) -> AgentPassportHistory:
        """스캔된 context로 단일 passport history를 만든다."""
        records: list[AgentWorkRecord] = []
        sessions = list(context.get("sessions", []))
        requests = list(context.get("requests", []))
        proposals = list(context.get("proposals", []))
        adoptions = list(context.get("adoptions", []))
        notes = list(context.get("notes", []))
        sessions_by_id = dict(context.get("sessions_by_id", {}))
        proposal_session_map = dict(context.get("proposal_session_map", {}))

        for payload in requests:
            if agent.agent_id not in self._active_agents_from_payload(payload):
                continue
            request_id = str(payload.get("request_id") or Path(str(payload.get("_artifact_path", "request"))).stem)
            records.append(
                AgentWorkRecord(
                    record_id=f"{agent.agent_id}-request-{request_id}",
                    created_at=str(payload.get("created_at")) if payload.get("created_at") is not None else None,
                    agent_id=agent.agent_id,
                    role_id=agent.role_id,
                    project_name=harness.project_name if harness is not None else None,
                    harness_id=harness.harness_id if harness is not None else None,
                    session_id=None,
                    session_stage=str(payload.get("status")) if payload.get("status") is not None else None,
                    user_request=str(payload.get("user_request")) if payload.get("user_request") is not None else None,
                    event_kind="request",
                    outcome="prepared",
                    artifact_refs=[str(payload.get("_artifact_path", ""))],
                    tags=[str((payload.get("routing") or {}).get("intent_type", ""))],
                    summary=f"Handled request: {str(payload.get('user_request', '')).strip() or request_id}",
                )
            )

        for session in sessions:
            if agent.agent_id not in self._active_agents_from_payload(session):
                continue
            if not self._session_has_diagnosis(session):
                continue
            session_id = str(session.get("session_id", ""))
            artifact_refs = [str(session.get("_artifact_path", ""))]
            report_path = str((session.get("artifacts") or {}).get("report_path") or "")
            if report_path:
                artifact_refs.append(report_path)
            records.append(
                AgentWorkRecord(
                    record_id=f"{agent.agent_id}-diagnose-{session_id or len(records)}",
                    created_at=str(session.get("updated_at") or session.get("created_at")) if (session.get("updated_at") or session.get("created_at")) is not None else None,
                    agent_id=agent.agent_id,
                    role_id=agent.role_id,
                    project_name=harness.project_name if harness is not None else None,
                    harness_id=harness.harness_id if harness is not None else None,
                    session_id=session_id or None,
                    session_stage=str(session.get("current_stage") or session.get("status")) if (session.get("current_stage") or session.get("status")) is not None else None,
                    user_request=str(session.get("user_request")) if session.get("user_request") is not None else None,
                    event_kind="diagnose",
                    outcome="diagnosed",
                    artifact_refs=_dedupe(artifact_refs),
                    tags=[str(session.get("status", ""))],
                    summary=f"Diagnosed source and related tests for {str(session.get('user_request', '')).strip() or 'current request'}",
                )
            )

        for proposal in proposals:
            proposal_path = str(proposal.get("_artifact_path", ""))
            session = self._find_session_for_proposal(proposal, proposal_path, sessions)
            if session is None or agent.agent_id not in self._active_agents_from_payload(session):
                continue
            session_id = str(session.get("session_id", ""))
            proposal_status = str(proposal.get("proposal_status", "ready"))
            artifact_refs = [proposal_path]
            diagnosis_ref = str(proposal.get("source_diagnosis_ref") or "")
            if diagnosis_ref:
                artifact_refs.append(diagnosis_ref)
            records.append(
                AgentWorkRecord(
                    record_id=f"{agent.agent_id}-proposal-{str(proposal.get('proposal_id', proposal_path))}",
                    created_at=str(proposal.get("created_at")) if proposal.get("created_at") is not None else None,
                    agent_id=agent.agent_id,
                    role_id=agent.role_id,
                    project_name=harness.project_name if harness is not None else None,
                    harness_id=harness.harness_id if harness is not None else None,
                    session_id=session_id or None,
                    session_stage=str(session.get("current_stage") or session.get("status")) if (session.get("current_stage") or session.get("status")) is not None else None,
                    user_request=str(proposal.get("user_request") or session.get("user_request")) if (proposal.get("user_request") or session.get("user_request")) is not None else None,
                    event_kind="patch_proposal",
                    outcome=self._proposal_outcome(proposal_status),
                    artifact_refs=_dedupe(artifact_refs),
                    tags=["patch_proposal", proposal_status],
                    summary=f"Prepared patch proposal for {str(proposal.get('target_path', '')).strip() or 'target file'}",
                )
            )
            validation = proposal.get("validation")
            if isinstance(validation, dict) and bool(validation.get("attempted", False)):
                validation_status = str(validation.get("status", "inconclusive"))
                records.append(
                    AgentWorkRecord(
                        record_id=f"{agent.agent_id}-validation-{str(proposal.get('proposal_id', proposal_path))}",
                        created_at=str(proposal.get("created_at")) if proposal.get("created_at") is not None else None,
                        agent_id=agent.agent_id,
                        role_id=agent.role_id,
                        project_name=harness.project_name if harness is not None else None,
                        harness_id=harness.harness_id if harness is not None else None,
                        session_id=session_id or None,
                        session_stage=str(session.get("current_stage") or session.get("status")) if (session.get("current_stage") or session.get("status")) is not None else None,
                        user_request=str(proposal.get("user_request") or session.get("user_request")) if (proposal.get("user_request") or session.get("user_request")) is not None else None,
                        event_kind="validation",
                        outcome=self._validation_outcome(validation_status),
                        artifact_refs=_dedupe([proposal_path]),
                        tags=["validation", validation_status],
                        summary=f"Validation {validation_status} for {str(proposal.get('target_path', '')).strip() or 'target file'}",
                    )
                )

        for adoption in adoptions:
            session_id = self._find_session_id_for_adoption(adoption, proposal_session_map, sessions)
            session = sessions_by_id.get(session_id or "")
            if session is None or agent.agent_id not in self._active_agents_from_payload(session):
                continue
            adoption_status = str(adoption.get("adoption_status", "adopted"))
            target_path = str(adoption.get("target_path", "")).strip() or "target file"
            tests = adoption.get("post_apply_tests")
            passing_tests = bool(isinstance(tests, dict) and int(tests.get("failed", 0) or 0) == 0 and int(tests.get("passed", 0) or 0) > 0)
            summary = f"Adoption succeeded for {target_path}"
            if passing_tests:
                summary = f"{summary} with passing tests"
            records.append(
                AgentWorkRecord(
                    record_id=f"{agent.agent_id}-adoption-{str(adoption.get('adoption_id', adoption.get('_artifact_path', '')))}",
                    created_at=str(adoption.get("created_at")) if adoption.get("created_at") is not None else None,
                    agent_id=agent.agent_id,
                    role_id=agent.role_id,
                    project_name=harness.project_name if harness is not None else None,
                    harness_id=harness.harness_id if harness is not None else None,
                    session_id=session_id or None,
                    session_stage=str(session.get("current_stage") or session.get("status")) if session is not None and (session.get("current_stage") or session.get("status")) is not None else None,
                    user_request=str(session.get("user_request")) if session is not None and session.get("user_request") is not None else None,
                    event_kind="adoption",
                    outcome="adopted" if adoption_status == "adopted" else adoption_status,
                    artifact_refs=_dedupe([
                        str(adoption.get("_artifact_path", "")),
                        str(adoption.get("source_proposal_path", "")),
                    ]),
                    tags=["adoption", adoption_status],
                    summary=summary,
                )
            )

        for note in notes:
            session_id = str(note.get("session_id", "")).strip()
            if not session_id:
                continue
            session = sessions_by_id.get(session_id)
            if session is None or agent.agent_id not in self._active_agents_from_payload(session):
                continue
            note_text = str(note.get("text", "")).strip()
            snippet = note_text if len(note_text) <= 80 else f"{note_text[:77]}..."
            records.append(
                AgentWorkRecord(
                    record_id=f"{agent.agent_id}-note-{str(note.get('note_id', note.get('_artifact_path', '')))}",
                    created_at=str(note.get("created_at")) if note.get("created_at") is not None else None,
                    agent_id=agent.agent_id,
                    role_id=agent.role_id,
                    project_name=harness.project_name if harness is not None else None,
                    harness_id=harness.harness_id if harness is not None else None,
                    session_id=session_id,
                    session_stage=str(note.get("stage")) if note.get("stage") is not None else None,
                    user_request=str((note.get("context") or {}).get("user_request")) if isinstance(note.get("context"), dict) and (note.get("context") or {}).get("user_request") is not None else None,
                    event_kind="note",
                    outcome="noted",
                    artifact_refs=_dedupe([str(note.get("_artifact_path", ""))]),
                    tags=[str(note.get("kind", "note")), str(note.get("severity", "medium"))],
                    summary=f"User note linked to this agent's session: {snippet}",
                )
            )

        records.sort(
            key=lambda item: (
                str(item.created_at or ""),
                item.record_id,
            ),
            reverse=True,
        )

        totals = {
            "sessions_seen": len({record.session_id for record in records if record.session_id}),
            "requests_seen": sum(1 for record in records if record.event_kind == "request"),
            "diagnoses": sum(1 for record in records if record.event_kind == "diagnose"),
            "patch_intents": sum(1 for record in records if record.event_kind == "patch_intent"),
            "patch_proposals": sum(1 for record in records if record.event_kind == "patch_proposal"),
            "validations_passed": sum(1 for record in records if record.event_kind == "validation" and record.outcome == "validated"),
            "validations_failed": sum(1 for record in records if record.event_kind == "validation" and record.outcome == "failed"),
            "adoptions": sum(1 for record in records if record.event_kind == "adoption" and record.outcome == "adopted"),
            "notes_linked": sum(1 for record in records if record.event_kind == "note"),
        }

        recent_wins = self._recent_wins(records)
        recent_risks = self._recent_risks(records, context.get("notes", []))
        fit_hints = self._fit_hints(agent, harness, totals, context.get("lessons", {}))

        return AgentPassportHistory(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            agent_id=agent.agent_id,
            role_id=agent.role_id,
            label=agent.label,
            description=agent.description,
            project_name=harness.project_name if harness is not None else None,
            harness_id=harness.harness_id if harness is not None else None,
            status=agent.status,
            totals=totals,
            recent_wins=recent_wins,
            recent_risks=recent_risks,
            fit_hints=fit_hints,
            work_records=records,
            source_refs={
                "registry": _relative(default_agent_registry_path(root), root),
                "harness": _relative(default_harness_profile_path(root), root),
            },
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )

    @staticmethod
    def _session_has_diagnosis(session: dict) -> bool:
        """session이 진단 단계 이상까지 갔는지 판별한다."""
        status = str(session.get("status", ""))
        stage = str(session.get("current_stage", ""))
        report_path = str((session.get("artifacts") or {}).get("report_path") or "")
        return bool(
            report_path
            or status in {"diagnosed", "patch_intent_draft", "patch_intent_ready", "patch_proposal_ready", "patch_proposal_validated", "adopted"}
            or stage in {"diagnosed", "patch_intent_draft", "patch_intent_ready", "patch_proposal_ready", "patch_proposal_validated", "adopted"}
        )

    @staticmethod
    def _find_session_for_proposal(proposal: dict, proposal_path: str, sessions: list[dict]) -> dict | None:
        """proposal과 강하게 연결된 session을 찾는다."""
        diagnosis_ref = str(proposal.get("source_diagnosis_ref") or "")
        for session in sessions:
            artifacts = session.get("artifacts") or {}
            if not isinstance(artifacts, dict):
                continue
            if proposal_path and str(artifacts.get("patch_proposal_path") or "") == proposal_path:
                return session
            if diagnosis_ref and str(artifacts.get("report_path") or "") == diagnosis_ref:
                return session
        return None

    @staticmethod
    def _find_session_id_for_adoption(adoption: dict, proposal_session_map: dict[str, str], sessions: list[dict]) -> str | None:
        """adoption과 연결된 session id를 찾는다."""
        proposal_ref = str(adoption.get("source_proposal_path") or adoption.get("proposal_path") or "")
        if proposal_ref and proposal_ref in proposal_session_map:
            return proposal_session_map[proposal_ref]
        for session in sessions:
            artifacts = session.get("artifacts") or {}
            if not isinstance(artifacts, dict):
                continue
            if proposal_ref and str(artifacts.get("patch_proposal_path") or "") == proposal_ref:
                return str(session.get("session_id", "")) or None
        return None

    @staticmethod
    def _proposal_outcome(status: str) -> str:
        """proposal status를 기록용 outcome으로 정리한다."""
        if status == "validated":
            return "validated"
        if status == "failed":
            return "failed"
        if status == "blocked":
            return "blocked"
        return "prepared"

    @staticmethod
    def _validation_outcome(status: str) -> str:
        """validation status를 기록용 outcome으로 정리한다."""
        if status == "passed":
            return "validated"
        if status == "failed":
            return "failed"
        return "blocked"

    @staticmethod
    def _recent_wins(records: list[AgentWorkRecord]) -> list[str]:
        """최근 wins를 요약한다."""
        wins: list[str] = []
        for record in records:
            if record.event_kind == "adoption" and record.outcome == "adopted":
                wins.append(record.summary)
            elif record.event_kind == "validation" and record.outcome == "validated":
                wins.append(record.summary)
        return _dedupe(wins)[:3]

    @staticmethod
    def _recent_risks(records: list[AgentWorkRecord], notes: list[dict]) -> list[str]:
        """최근 risks를 요약한다."""
        risks: list[str] = []
        for record in records:
            if record.event_kind == "validation" and record.outcome == "failed":
                risks.append(record.summary)
            elif record.outcome == "blocked":
                risks.append(record.summary)
        for note in notes:
            if str(note.get("severity", "")) != "high":
                continue
            text = str(note.get("text", "")).strip()
            if text:
                snippet = text if len(text) <= 80 else f"{text[:77]}..."
                risks.append(f"High severity note linked: {snippet}")
        return _dedupe(risks)[:3]

    @staticmethod
    def _fit_hints(agent: AgentPassport, harness: HarnessProfile | None, totals: dict, lessons_payload: dict) -> list[str]:
        """하네스와 현재 경력을 기반으로 짧은 fit hint를 만든다."""
        hints: list[str] = []
        if harness is not None and "bug_fix" in harness.primary_use_cases and agent.agent_id == "bug-fix-agent":
            hints.append("Strong fit for bug-fix work in this harness.")
        if harness is not None and harness.test_command and agent.agent_id in {"regression-test-agent", "patch-validation-agent"}:
            hints.append("Good fit for projects with a test command and explicit validation.")
        if int(totals.get("adoptions", 0) or 0) > 0:
            hints.append(f"This agent already has {int(totals.get('adoptions', 0) or 0)} successful adoption record(s) in this project.")
        lessons = lessons_payload.get("lessons", []) if isinstance(lessons_payload, dict) else []
        lesson_text = " ".join(
            str(item.get("text", "")).lower()
            for item in lessons
            if isinstance(item, dict) and item.get("text")
        )
        if "auth" in lesson_text and agent.agent_id in {"bug-fix-agent", "review-agent"}:
            hints.append("Project memory includes auth-related lessons that match this role.")
        return _dedupe(hints)[:3]


def render_agent_history(history: AgentPassportHistory, limit: int = 5, review_summary: dict | None = None) -> str:
    """agent history를 사람이 읽기 쉬운 텍스트로 렌더링한다."""
    totals = history.totals if isinstance(history.totals, dict) else {}
    lines = [
        "Agent History",
        "==================================================",
        "",
        "Agent:",
        f"  {history.agent_id}",
        f"  role: {history.role_id}",
        f"  status: {history.status}",
        "",
        "Project:",
        f"  {history.project_name or '(unknown)'}",
        "",
        "Totals:",
        f"  sessions seen      : {totals.get('sessions_seen', 0)}",
        f"  diagnoses          : {totals.get('diagnoses', 0)}",
        f"  patch proposals    : {totals.get('patch_proposals', 0)}",
        f"  validations passed : {totals.get('validations_passed', 0)}",
        f"  adoptions          : {totals.get('adoptions', 0)}",
    ]
    lines.extend(["", "Recent wins:"])
    if history.recent_wins:
        for item in history.recent_wins:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none yet")
    lines.extend(["", "Recent risks:"])
    if history.recent_risks:
        for item in history.recent_risks:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none yet")
    lines.extend(["", "Fit hints:"])
    if history.fit_hints:
        for item in history.fit_hints:
            lines.append(f"  - {item}")
    else:
        lines.append("  - none yet")
    if isinstance(review_summary, dict) and int(review_summary.get("total", 0) or 0) > 0:
        lines.extend(["", "Recent reviews:"])
        recent_positive = list(review_summary.get("recent_positive", [])) if isinstance(review_summary.get("recent_positive"), list) else []
        recent_cautions = list(review_summary.get("recent_cautions", [])) if isinstance(review_summary.get("recent_cautions"), list) else []
        if recent_positive:
            for item in recent_positive[:2]:
                lines.append(f"  - [good] {item}")
        if recent_cautions:
            for item in recent_cautions[:2]:
                lines.append(f"  - [caution] {item}")
    if limit > 0:
        lines.extend(["", "Recent records:"])
        if history.work_records:
            for record in history.work_records[:limit]:
                lines.append(f"  - [{record.event_kind}] {record.summary}")
        else:
            lines.append("  - none yet")
    return "\n".join(lines)


def load_agent_passport_history(path: Path) -> AgentPassportHistory:
    """저장된 passport history를 로드한다."""
    return AgentPassportHistoryStore().load(path)
