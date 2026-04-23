"""Cambrian 프로젝트 여정 요약 리더."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _relative(path: Path, root: Path) -> str:
    """프로젝트 루트 기준 상대 경로를 만든다."""
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _latest_file(directory: Path, pattern: str) -> Path | None:
    """패턴과 일치하는 최신 파일을 찾는다."""
    if not directory.exists():
        return None
    candidates = sorted(
        (item for item in directory.glob(pattern) if item.is_file()),
        key=lambda item: (item.stat().st_mtime, item.name),
    )
    if not candidates:
        return None
    return candidates[-1]


def _load_yaml(path: Path, warnings: list[str]) -> dict | None:
    """YAML 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        warnings.append(f"YAML 읽기 실패: {path} ({exc})")
        return None
    if not isinstance(payload, dict):
        warnings.append(f"YAML 형식 오류: {path}")
        return None
    return payload


def _load_json(path: Path, warnings: list[str]) -> dict | None:
    """JSON 파일을 안전하게 읽는다."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"JSON 읽기 실패: {path} ({exc})")
        return None
    if not isinstance(payload, dict):
        warnings.append(f"JSON 형식 오류: {path}")
        return None
    return payload


@dataclass
class ProjectActivityItem:
    """프로젝트 여정의 한 단계."""

    kind: str
    path: str
    title: str
    status: str
    created_at: str | None
    summary: str

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class ProjectActivitySummary:
    """프로젝트 최신 활동 요약."""

    latest_request: ProjectActivityItem | None = None
    latest_context_scan: ProjectActivityItem | None = None
    latest_clarification: ProjectActivityItem | None = None
    latest_diagnosis: ProjectActivityItem | None = None
    latest_patch_proposal: ProjectActivityItem | None = None
    latest_adoption: ProjectActivityItem | None = None
    recent_lessons: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)

    def journey_items(self) -> list[ProjectActivityItem]:
        """사용자 여정 순서대로 최신 활동을 반환한다."""
        items = [
            self.latest_request,
            self.latest_context_scan,
            self.latest_clarification,
            self.latest_diagnosis,
            self.latest_patch_proposal,
            self.latest_adoption,
        ]
        return [item for item in items if item is not None]


class ProjectActivityReader:
    """`.cambrian` 아래 최신 활동을 읽어 사용자 여정을 만든다."""

    def read(
        self,
        project_root: str | Path,
        warnings: list[str] | None = None,
    ) -> ProjectActivitySummary:
        """최신 request/context/diagnosis/proposal/adoption 흐름을 읽는다."""
        root = Path(project_root).resolve()
        collected_warnings = warnings if warnings is not None else []
        summary = ProjectActivitySummary()

        summary.latest_request = self._read_latest_request(root, collected_warnings)
        summary.latest_context_scan = self._read_latest_context(root, collected_warnings)
        summary.latest_clarification = self._read_latest_clarification(root, collected_warnings)
        summary.latest_diagnosis = self._read_latest_diagnosis(root, collected_warnings)
        summary.latest_patch_proposal = self._read_latest_proposal(root, collected_warnings)
        summary.latest_adoption = self._read_latest_adoption(root, collected_warnings)
        return summary

    def _read_latest_request(
        self,
        root: Path,
        warnings: list[str],
    ) -> ProjectActivityItem | None:
        """최신 request artifact를 읽는다."""
        request_path = _latest_file(root / ".cambrian" / "requests", "request_*.yaml")
        if request_path is None:
            return None
        payload = _load_yaml(request_path, warnings)
        if not payload:
            return None
        routing = payload.get("routing", {})
        readiness = routing.get("execution_readiness", payload.get("status", "unknown"))
        title = str(payload.get("user_request", "") or request_path.stem)
        summary = f"{str(routing.get('intent_type', 'unknown')).replace('_', ' ')} / {readiness}"
        return ProjectActivityItem(
            kind="request",
            path=_relative(request_path, root),
            title=title,
            status=str(readiness),
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            summary=summary,
        )

    def _read_latest_context(
        self,
        root: Path,
        warnings: list[str],
    ) -> ProjectActivityItem | None:
        """최신 context scan artifact를 읽는다."""
        context_path = _latest_file(root / ".cambrian" / "context", "context_*.yaml")
        if context_path is None:
            return None
        payload = _load_yaml(context_path, warnings)
        if not payload:
            return None
        top_source = str(payload.get("top_source") or "none")
        top_test = str(payload.get("top_test") or "none")
        summary = (
            "no confident files found"
            if payload.get("status") == "no_match"
            else f"suggested {top_source} and {top_test}"
        )
        return ProjectActivityItem(
            kind="context",
            path=_relative(context_path, root),
            title=str(payload.get("user_request", "") or context_path.stem),
            status=str(payload.get("status", "unknown")),
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            summary=summary,
        )

    def _read_latest_diagnosis(
        self,
        root: Path,
        warnings: list[str],
    ) -> ProjectActivityItem | None:
        """최신 diagnose-only 실행을 읽는다."""
        requests_dir = root / ".cambrian" / "requests"
        if not requests_dir.exists():
            return None
        request_files = sorted(
            requests_dir.glob("request_*.yaml"),
            key=lambda item: (item.stat().st_mtime, item.name),
            reverse=True,
        )
        for request_path in request_files:
            payload = _load_yaml(request_path, warnings)
            if not payload or not payload.get("diagnose_only", False):
                continue
            execution = payload.get("execution", {})
            report_ref = execution.get("report_path")
            created_at = str(payload.get("created_at")) if payload.get("created_at") else None
            title = str(payload.get("user_request", "") or request_path.stem)
            selected_context = payload.get("selected_context", {})
            selected_tests = list(selected_context.get("tests", []))
            default_summary = (
                f"diagnosed {', '.join(selected_context.get('sources', [])) or 'selected files'}"
            )
            if not report_ref:
                return ProjectActivityItem(
                    kind="diagnosis",
                    path=_relative(request_path, root),
                    title=title,
                    status=str(execution.get("status", "unknown")),
                    created_at=created_at,
                    summary=default_summary,
                )

            report_path = root / str(report_ref)
            report_payload = _load_json(report_path, warnings)
            diagnostics = report_payload.get("diagnostics", {}) if report_payload else {}
            if not isinstance(diagnostics, dict):
                diagnostics = {}
            test_results = diagnostics.get("test_results", {}) if isinstance(diagnostics, dict) else {}
            failed = int(test_results.get("failed", 0) or 0)
            passed = int(test_results.get("passed", 0) or 0)
            tests = list(diagnostics.get("related_tests", [])) or selected_tests
            if failed > 0:
                summary = f"{', '.join(tests) or 'related tests'} failed before patch"
                status = "failed"
            elif passed > 0:
                summary = f"{', '.join(tests) or 'related tests'} passed before patch"
                status = "passed"
            else:
                summary = default_summary
                status = str(execution.get("status", "unknown"))
            return ProjectActivityItem(
                kind="diagnosis",
                path=_relative(report_path, root),
                title=title,
                status=status,
                created_at=created_at,
                summary=summary,
            )
        return None

    def _read_latest_clarification(
        self,
        root: Path,
        warnings: list[str],
    ) -> ProjectActivityItem | None:
        """최신 clarification artifact를 읽는다."""
        clarification_path = _latest_file(
            root / ".cambrian" / "clarifications",
            "clarification_*.yaml",
        )
        if clarification_path is None:
            return None
        payload = _load_yaml(clarification_path, warnings)
        if not payload:
            return None
        status = str(payload.get("status", "open"))
        selected_context = payload.get("selected_context", {})
        sources = list(selected_context.get("sources", [])) if isinstance(selected_context, dict) else []
        if status == "ready":
            summary = f"selected {', '.join(sources) or 'source'} and ready to diagnose"
        elif status == "blocked":
            summary = "clarification blocked"
        else:
            summary = "waiting for source choice"
        return ProjectActivityItem(
            kind="clarification",
            path=_relative(clarification_path, root),
            title=str(payload.get("user_request", "") or clarification_path.stem),
            status=status,
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            summary=summary,
        )

    def _read_latest_proposal(
        self,
        root: Path,
        warnings: list[str],
    ) -> ProjectActivityItem | None:
        """최신 patch proposal을 읽는다."""
        proposal_path = _latest_file(root / ".cambrian" / "patches", "patch_proposal_*.yaml")
        if proposal_path is None:
            return None
        payload = _load_yaml(proposal_path, warnings)
        if not payload:
            return None
        validation = payload.get("validation", {})
        validation_status = str(validation.get("status", "not_requested")) if isinstance(validation, dict) else "unknown"
        proposal_status = str(payload.get("proposal_status", "unknown"))
        target = str(payload.get("target_path", "") or proposal_path.stem)
        if validation_status == "passed":
            summary = "patch proposal ready and validated"
        elif validation_status in {"failed", "inconclusive"}:
            summary = f"patch proposal validation {validation_status}"
        else:
            summary = f"patch proposal {proposal_status}"
        return ProjectActivityItem(
            kind="patch_proposal",
            path=_relative(proposal_path, root),
            title=target,
            status=proposal_status,
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            summary=summary,
        )

    def _read_latest_adoption(
        self,
        root: Path,
        warnings: list[str],
    ) -> ProjectActivityItem | None:
        """최신 adoption record를 읽는다."""
        latest_pointer = _load_json(root / ".cambrian" / "adoptions" / "_latest.json", warnings)
        record_path: Path | None = None
        if latest_pointer:
            record_ref = latest_pointer.get("latest_adoption_path")
            if isinstance(record_ref, str) and record_ref:
                record_path = root / record_ref
        if record_path is None:
            record_path = _latest_file(root / ".cambrian" / "adoptions", "adoption_*.json")
        if record_path is None:
            return None
        payload = _load_json(record_path, warnings)
        if not payload:
            return None
        tests = payload.get("post_apply_tests", {})
        failed = int(tests.get("failed", 0) or 0)
        passed = int(tests.get("passed", 0) or 0)
        if failed > 0:
            summary = "patch applied but tests failed"
            status = "failed"
        elif passed > 0:
            summary = "patch adopted, tests passed"
            status = "adopted"
        else:
            summary = "patch adopted"
            status = str(payload.get("adoption_status", "unknown"))
        return ProjectActivityItem(
            kind="adoption",
            path=_relative(record_path, root),
            title=str(payload.get("target_path", "") or record_path.stem),
            status=status,
            created_at=str(payload.get("created_at")) if payload.get("created_at") else None,
            summary=summary,
        )
