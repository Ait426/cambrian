"""템플릿 apply 전 preview/approval guardrail을 검사한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_template_decisions import (
    TemplateDecisionStore,
    TemplateReviewStore,
    default_template_decisions_path,
)
from engine.project_template_diff import TemplateDiffStore, default_template_diff_path
from engine.project_templates import HarnessTemplateStore, default_current_template_path, default_templates_path
from engine.project_teams import default_team_presets_path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    """guardrail report를 안전하게 저장한다."""
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
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML top level must be a mapping: {path}")
    return payload


def _slug(value: str | None) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def default_template_apply_guardrails_path(project_root: Path) -> Path:
    """템플릿 apply guardrail report 기본 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "apply_guardrails.yaml"


@dataclass
class TemplateApplyCheck:
    """템플릿 apply 전 단일 guardrail check."""

    check_id: str
    title: str
    status: str
    severity: str
    summary: str
    details: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateApplyGuardrailReport:
    """템플릿 apply guardrail report."""

    schema_version: str
    generated_at: str
    report_id: str
    template_name: str
    project_name: str | None
    workspace: str
    checks: list[TemplateApplyCheck]
    summary: dict[str, Any]
    status: str
    next_actions: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "report_id": self.report_id,
            "template_name": self.template_name,
            "project_name": self.project_name,
            "workspace": self.workspace,
            "checks": [check.to_dict() for check in self.checks],
            "summary": dict(self.summary),
            "status": self.status,
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateApplyGuardrailBuilder:
    """템플릿 apply 전 필요한 preview/approval 상태를 검사한다."""

    def build(self, project_root: Path, template_name: str) -> TemplateApplyGuardrailReport:
        root = Path(project_root).resolve()
        checks: list[TemplateApplyCheck] = []
        warnings: list[str] = []
        errors: list[str] = []
        resolved_template_name = str(template_name)

        template_check, resolved_template_name = self._check_template_exists(root, template_name)
        checks.append(template_check)
        checks.append(self._check_initialized(root))
        checks.append(self._check_diff(root, resolved_template_name))
        checks.append(self._check_review(root, resolved_template_name))
        checks.append(self._check_decision(root, resolved_template_name))
        checks.append(self._check_current_template(root, resolved_template_name))
        checks.append(self._check_active_team_drift(root, resolved_template_name))
        checks.append(self._check_live_state_safety())

        for check in checks:
            if check.status == "warn":
                warnings.append(check.summary)
            elif check.status == "fail":
                errors.append(check.summary)
        summary = {
            "pass_count": sum(1 for check in checks if check.status == "pass"),
            "warn_count": sum(1 for check in checks if check.status == "warn"),
            "fail_count": sum(1 for check in checks if check.status == "fail"),
        }
        if summary["fail_count"] > 0:
            status = "blocked"
        elif summary["warn_count"] > 0:
            status = "safe_with_warnings"
        else:
            status = "safe"
        next_actions = _next_actions_for_status(status, resolved_template_name, checks)
        return TemplateApplyGuardrailReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            report_id=f"template-apply-guardrails-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            template_name=resolved_template_name,
            project_name=_project_name(root),
            workspace=str(root),
            checks=checks,
            summary=summary,
            status=status,
            next_actions=next_actions,
            warnings=warnings,
            errors=errors,
        )

    @staticmethod
    def _check_template_exists(root: Path, template_name: str) -> tuple[TemplateApplyCheck, str]:
        try:
            store = HarnessTemplateStore()
            model = store.load(default_templates_path(root))
            template = store.find(model, template_name)
        except Exception:
            return (
                TemplateApplyCheck(
                    check_id="template_exists",
                    title="template exists",
                    status="fail",
                    severity="high",
                    summary=f"template not found: {template_name}",
                    details=["templates.yaml does not contain the requested template"],
                    suggested_actions=["cambrian template list"],
                ),
                str(template_name),
            )
        return (
            TemplateApplyCheck(
                check_id="template_exists",
                title="template exists",
                status="pass",
                severity="info",
                summary=f"template exists: {template.name}",
                details=[_relative_to_project(default_templates_path(root), root)],
                suggested_actions=[],
            ),
            template.name,
        )

    @staticmethod
    def _check_initialized(root: Path) -> TemplateApplyCheck:
        if (root / ".cambrian" / "project.yaml").exists():
            return TemplateApplyCheck(
                check_id="initialized_project",
                title="project initialized",
                status="pass",
                severity="info",
                summary="project is initialized for template apply",
                details=[".cambrian/project.yaml exists"],
                suggested_actions=[],
            )
        return TemplateApplyCheck(
            check_id="initialized_project",
            title="project initialized",
            status="fail",
            severity="high",
            summary="template apply requires an initialized Cambrian project",
            details=[".cambrian/project.yaml is missing"],
            suggested_actions=["cambrian init --wizard"],
        )

    @staticmethod
    def _check_diff(root: Path, template_name: str) -> TemplateApplyCheck:
        path = default_template_diff_path(root)
        if not path.exists():
            return TemplateApplyCheck(
                check_id="diff_exists",
                title="diff exists",
                status="fail",
                severity="high",
                summary="no template diff report found for apply preview",
                details=["apply requires a saved diff report"],
                suggested_actions=[f"cambrian template diff {template_name} --save"],
            )
        try:
            report = TemplateDiffStore().load(path)
        except Exception as exc:
            return TemplateApplyCheck(
                check_id="diff_exists",
                title="diff exists",
                status="fail",
                severity="high",
                summary=f"template diff report could not be loaded: {exc}",
                details=[_relative_to_project(path, root)],
                suggested_actions=[f"cambrian template diff {template_name} --save"],
            )
        if _slug(report.target_template_name) != _slug(template_name):
            return TemplateApplyCheck(
                check_id="diff_exists",
                title="diff exists",
                status="fail",
                severity="high",
                summary=f"latest diff targets {report.target_template_name}, not {template_name}",
                details=[_relative_to_project(path, root)],
                suggested_actions=[f"cambrian template diff {template_name} --save"],
            )
        return TemplateApplyCheck(
            check_id="diff_exists",
            title="diff exists",
            status="pass",
            severity="info",
            summary="diff preview exists for this template",
            details=[_relative_to_project(path, root), f"diff status: {report.mode}"],
            suggested_actions=[],
        )

    @staticmethod
    def _check_review(root: Path, template_name: str) -> TemplateApplyCheck:
        review, review_path = TemplateReviewStore().latest(root, template_name)
        if not review or not review_path:
            return TemplateApplyCheck(
                check_id="review_exists",
                title="review exists",
                status="warn",
                severity="warning",
                summary="no saved template review was found",
                details=["review is recommended before apply"],
                suggested_actions=[f"cambrian template review {template_name} --save"],
            )
        return TemplateApplyCheck(
            check_id="review_exists",
            title="review exists",
            status="pass",
            severity="info",
            summary="saved template review exists",
            details=[_relative_to_project(review_path, root)],
            suggested_actions=[],
        )

    @staticmethod
    def _check_decision(root: Path, template_name: str) -> TemplateApplyCheck:
        model = TemplateDecisionStore().load(default_template_decisions_path(root))
        decisions = [
            decision
            for decision in model.decisions
            if _slug(decision.template_name) == _slug(template_name)
        ]
        if not decisions:
            return TemplateApplyCheck(
                check_id="decision_status",
                title="decision status",
                status="warn",
                severity="warning",
                summary="no accepted template decision was found",
                details=["apply can proceed only with --force unless accepted"],
                suggested_actions=[f"cambrian template accept {template_name}"],
            )
        latest = decisions[-1]
        if latest.status == "dismissed":
            return TemplateApplyCheck(
                check_id="decision_status",
                title="decision status",
                status="fail",
                severity="high",
                summary="latest decision dismissed this template",
                details=[latest.summary],
                suggested_actions=[f"cambrian template review {template_name}", f"cambrian template accept {template_name}"],
            )
        if latest.status == "accepted":
            return TemplateApplyCheck(
                check_id="decision_status",
                title="decision status",
                status="pass",
                severity="info",
                summary="template has an accepted decision",
                details=[latest.summary],
                suggested_actions=[],
            )
        return TemplateApplyCheck(
            check_id="decision_status",
            title="decision status",
            status="warn",
            severity="warning",
            summary=f"latest template decision is {latest.status}",
            details=[latest.summary],
            suggested_actions=[f"cambrian template accept {template_name}"],
        )

    @staticmethod
    def _check_current_template(root: Path, template_name: str) -> TemplateApplyCheck:
        path = default_current_template_path(root)
        if not path.exists():
            return TemplateApplyCheck(
                check_id="current_template_conflict",
                title="current template conflict",
                status="pass",
                severity="info",
                summary="no current template is applied yet",
                details=[],
                suggested_actions=[],
            )
        try:
            current = _load_yaml(path)
        except Exception as exc:
            return TemplateApplyCheck(
                check_id="current_template_conflict",
                title="current template conflict",
                status="warn",
                severity="warning",
                summary=f"current template marker could not be read: {exc}",
                details=[_relative_to_project(path, root)],
                suggested_actions=[],
            )
        current_name = str(current.get("name") or "").strip()
        if current_name and _slug(current_name) != _slug(template_name):
            return TemplateApplyCheck(
                check_id="current_template_conflict",
                title="current template conflict",
                status="warn",
                severity="warning",
                summary=f"current project already uses a different template: {current_name}",
                details=[_relative_to_project(path, root)],
                suggested_actions=[f"cambrian template diff {template_name} --save"],
            )
        return TemplateApplyCheck(
            check_id="current_template_conflict",
            title="current template conflict",
            status="pass",
            severity="info",
            summary="target template matches current template marker",
            details=[_relative_to_project(path, root)],
            suggested_actions=[],
        )

    @staticmethod
    def _check_active_team_drift(root: Path, template_name: str) -> TemplateApplyCheck:
        try:
            store = HarnessTemplateStore()
            template = store.find(store.load(default_templates_path(root)), template_name)
        except Exception:
            return TemplateApplyCheck(
                check_id="active_team_drift",
                title="active team drift",
                status="warn",
                severity="warning",
                summary="active team drift could not be checked",
                details=["template payload unavailable"],
                suggested_actions=[],
            )
        target_team = str(template.team_defaults.get("active_team_id") or "").strip()
        teams_path = default_team_presets_path(root)
        if not target_team or not teams_path.exists():
            return TemplateApplyCheck(
                check_id="active_team_drift",
                title="active team drift",
                status="pass",
                severity="info",
                summary="no active team drift detected",
                details=[],
                suggested_actions=[],
            )
        try:
            teams = _load_yaml(teams_path)
        except Exception as exc:
            return TemplateApplyCheck(
                check_id="active_team_drift",
                title="active team drift",
                status="warn",
                severity="warning",
                summary=f"current team state could not be checked: {exc}",
                details=[_relative_to_project(teams_path, root)],
                suggested_actions=[],
            )
        current_team = str(teams.get("active_team_id") or "").strip()
        if current_team and _slug(current_team) != _slug(target_team):
            return TemplateApplyCheck(
                check_id="active_team_drift",
                title="active team drift",
                status="warn",
                severity="warning",
                summary=f"template would switch active team from {current_team} to {target_team}",
                details=[_relative_to_project(teams_path, root)],
                suggested_actions=[f"cambrian template diff {template_name} --save"],
            )
        return TemplateApplyCheck(
            check_id="active_team_drift",
            title="active team drift",
            status="pass",
            severity="info",
            summary="active team already aligns with template defaults",
            details=[],
            suggested_actions=[],
        )

    @staticmethod
    def _check_live_state_safety() -> TemplateApplyCheck:
        return TemplateApplyCheck(
            check_id="live_state_safety",
            title="live state safety",
            status="pass",
            severity="info",
            summary="template apply does not copy notes, sessions, adoptions, or raw memory lessons",
            details=[
                "notes are not copied",
                "sessions are not copied",
                "adoption history is not copied",
                "raw memory lessons are not copied",
            ],
            suggested_actions=[],
        )


class TemplateApplyGuardrailStore:
    """템플릿 apply guardrail report 저장소."""

    def save(self, report: TemplateApplyGuardrailReport, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), report.to_dict())

    def load(self, path: Path) -> TemplateApplyGuardrailReport:
        payload = _load_yaml(Path(path).resolve())
        checks = [
            TemplateApplyCheck(
                check_id=str(item.get("check_id", "")),
                title=str(item.get("title", "")),
                status=str(item.get("status", "")),
                severity=str(item.get("severity", "")),
                summary=str(item.get("summary", "")),
                details=[str(value) for value in item.get("details", []) if value],
                suggested_actions=[str(value) for value in item.get("suggested_actions", []) if value],
            )
            for item in payload.get("checks", []) or []
            if isinstance(item, dict)
        ]
        return TemplateApplyGuardrailReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            report_id=str(payload.get("report_id", "")),
            template_name=str(payload.get("template_name", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            workspace=str(payload.get("workspace", "")),
            checks=checks,
            summary=dict(payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}),
            status=str(payload.get("status", "blocked")),
            next_actions=[str(value) for value in payload.get("next_actions", []) if value],
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


def render_template_apply_guardrails(report: TemplateApplyGuardrailReport) -> str:
    """guardrail report를 사람이 읽는 preflight로 렌더링한다."""
    lines = [
        "Template Apply Guardrails",
        "==================================================",
        "",
        "Template:",
        f"  {report.template_name}",
        "",
        "Checks:",
    ]
    for check in report.checks:
        symbol = "OK" if check.status == "pass" else "!" if check.status == "warn" else "X"
        lines.append(f"  {symbol} {check.summary}")
    result = {
        "safe": "safe to apply",
        "safe_with_warnings": "safe with warnings",
        "blocked": "blocked",
    }.get(report.status, report.status)
    lines.extend(["", "Result:", f"  {result}"])
    if report.status == "safe_with_warnings":
        lines.append("  use --force to continue with these warnings")
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in report.next_actions[:5]])
    return "\n".join(lines)


def load_template_apply_guardrail_summary(project_root: Path) -> dict[str, Any]:
    """status/show에서 쓰는 최신 guardrail 요약."""
    path = default_template_apply_guardrails_path(project_root)
    if not path.exists():
        return {}
    try:
        report = TemplateApplyGuardrailStore().load(path)
    except Exception as exc:
        logger.warning("template apply guardrail summary load failed: %s", exc)
        return {"warnings": [f"template apply guardrail load failed: {exc}"]}
    return {
        "template_name": report.template_name,
        "status": report.status,
        "summary": dict(report.summary),
        "next_actions": list(report.next_actions),
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }


def render_template_apply_guardrail_summary(summary: dict[str, Any]) -> str:
    """latest guardrail 상태를 compact하게 렌더링한다."""
    if not summary:
        return "Template apply guardrail:\n  none yet"
    lines = [
        "Template apply guardrail:",
        f"  template: {summary.get('template_name') or 'unknown'}",
        f"  status  : {summary.get('status') or 'unknown'}",
    ]
    next_actions = list(summary.get("next_actions", []) or [])
    if next_actions:
        lines.extend(["", "Next:", f"  {next_actions[0]}"])
    return "\n".join(lines)


def _project_name(root: Path) -> str | None:
    path = root / ".cambrian" / "project.yaml"
    if not path.exists():
        return root.name
    try:
        payload = _load_yaml(path)
    except Exception:
        return root.name
    project = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
    return str(project.get("name") or root.name)


def _next_actions_for_status(status: str, template_name: str, checks: list[TemplateApplyCheck]) -> list[str]:
    actions: list[str] = []
    for check in checks:
        actions.extend(check.suggested_actions)
    if status == "safe":
        actions.append(f"cambrian template apply {template_name}")
    elif status == "safe_with_warnings":
        actions.append(f"cambrian template apply {template_name} --force")
    return _dedupe(actions)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
