"""현재 프로젝트에 맞는 하네스 템플릿을 추천한다."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from engine.project_templates import (
    HarnessTemplate,
    HarnessTemplateStore,
    default_current_template_path,
    default_templates_path,
    load_current_template,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시간을 ISO 문자열로 돌려준다."""
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, content: str) -> None:
    """추천 리포트를 중간 파일을 거쳐 안전하게 저장한다."""
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


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _slug(value: str | None) -> str:
    token = "".join(ch if ch.isalnum() else "-" for ch in str(value or "").strip().lower())
    return "-".join(part for part in token.split("-") if part) or "template"


def _overlap(left: list[str], right: list[str]) -> set[str]:
    left_set = {_norm(item) for item in left if _norm(item)}
    right_set = {_norm(item) for item in right if _norm(item)}
    return left_set & right_set


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _test_family(command: str | None) -> str:
    text = _norm(command)
    if not text:
        return ""
    if "pytest" in text:
        return "pytest"
    if "npm" in text or "vitest" in text or "jest" in text:
        return "npm_test"
    if "go_test" in text or "go test" in text:
        return "go_test"
    return text


def default_template_recommendation_path(project_root: Path) -> Path:
    """프로젝트 수준 템플릿 추천 리포트 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "recommendation.yaml"


def default_request_template_recommendation_path(project_root: Path) -> Path:
    """요청 단위 템플릿 추천 리포트 경로."""
    return Path(project_root).resolve() / ".cambrian" / "templates" / "recommendation__request.yaml"


@dataclass
class TemplateCandidate:
    """하나의 템플릿 후보와 fit 근거."""

    template_id: str
    name: str
    template_kind: str
    score: float
    confidence: float
    recommendation: str
    reasons: list[str]
    warnings: list[str]
    project_fit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateRecommendationReport:
    """템플릿 추천 리포트."""

    schema_version: str
    generated_at: str
    report_id: str
    project_name: str | None
    workspace: str
    mode: str
    request: str | None
    current_template_name: str | None
    best_template_name: str | None
    backup_templates: list[str]
    candidates: list[TemplateCandidate]
    summary: dict[str, Any]
    next_actions: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "report_id": self.report_id,
            "project_name": self.project_name,
            "workspace": self.workspace,
            "mode": self.mode,
            "request": self.request,
            "current_template_name": self.current_template_name,
            "best_template_name": self.best_template_name,
            "backup_templates": list(self.backup_templates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "summary": dict(self.summary),
            "next_actions": list(self.next_actions),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class TemplateRecommendationBuilder:
    """저장된 템플릿과 현재 프로젝트 신호를 비교해 추천을 만든다."""

    def build(self, project_root: Path, request: str | None = None) -> TemplateRecommendationReport:
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        templates_path = default_templates_path(root)
        store = HarnessTemplateStore()
        model = store.load(templates_path)
        signals = _collect_project_signals(root, request, warnings)
        current_template = load_current_template(root)
        current_template_name = str(current_template.get("name") or "").strip() or None
        candidates = [
            self._score_template(template, signals, request=request)
            for template in model.templates
        ]
        candidates.sort(key=lambda item: item.score, reverse=True)
        if candidates:
            candidates[0].recommendation = "best_fit"
        if not candidates:
            warnings.append("no saved templates found")
        best_name = candidates[0].name if candidates else None
        backup_templates = [candidate.name for candidate in candidates[1:3] if candidate.recommendation != "reject"]
        next_actions = []
        if best_name:
            if not (root / ".cambrian" / "project.yaml").exists():
                next_actions.extend([
                    f"cambrian init --wizard --template {best_name}",
                    f"cambrian template show {best_name}",
                ])
            else:
                next_actions.extend([
                    f"cambrian template diff {best_name}",
                    f"cambrian template review {best_name}",
                    f"cambrian template apply {best_name}",
                    f"cambrian template show {best_name}",
                ])
        else:
            next_actions.append("cambrian template save auth-bug-template")
        summary = {
            "templates_seen": len(model.templates),
            "signals_mode": signals.get("signals_mode"),
            "detected_stack": list(signals.get("stack", [])),
            "detected_use_cases": list(signals.get("primary_use_cases", [])),
            "request_intents": list(signals.get("request_intents", [])),
            "best_score": candidates[0].score if candidates else 0.0,
        }
        return TemplateRecommendationReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            report_id=f"template-rec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            project_name=str(signals.get("project_name") or root.name),
            workspace=str(root),
            mode="request" if request else "project",
            request=request,
            current_template_name=current_template_name,
            best_template_name=best_name,
            backup_templates=backup_templates,
            candidates=candidates,
            summary=summary,
            next_actions=_dedupe(next_actions),
            warnings=warnings,
            errors=errors,
        )

    def _score_template(
        self,
        template: HarnessTemplate,
        signals: dict[str, Any],
        request: str | None = None,
    ) -> TemplateCandidate:
        reasons: list[str] = []
        warnings: list[str] = []
        fit: dict[str, Any] = {}
        score = 0.1
        evidence = 0

        template_project_type = _norm(template.project_defaults.get("project_type"))
        current_project_type = _norm(signals.get("project_type"))
        project_type_fit = bool(template_project_type and template_project_type == current_project_type)
        fit["project_type_fit"] = project_type_fit
        if project_type_fit:
            score += 0.15
            evidence += 1
            reasons.append(f"project type matches {template_project_type}")
        elif template_project_type and current_project_type:
            warnings.append(f"project type differs: template {template_project_type}, current {current_project_type}")

        template_stack = _as_list(template.project_defaults.get("stack"))
        current_stack = _as_list(signals.get("stack"))
        stack_overlap = sorted(_overlap(template_stack, current_stack))
        fit["stack_fit"] = stack_overlap
        if stack_overlap:
            score += min(0.2, 0.08 * len(stack_overlap))
            evidence += 1
            reasons.append(f"stack overlaps on {', '.join(stack_overlap)}")
        elif template_stack and current_stack:
            warnings.append("template stack has little overlap with current project")

        template_test = str(template.project_defaults.get("test_command") or "")
        current_test = str(signals.get("test_command") or "")
        template_test_family = _test_family(template_test)
        current_test_family = _test_family(current_test)
        test_command_fit = bool(template_test_family and template_test_family == current_test_family)
        fit["test_command_fit"] = test_command_fit
        if test_command_fit:
            score += 0.15
            evidence += 1
            reasons.append(f"test command family matches {template_test_family}")
        elif template_test_family and not current_test_family:
            warnings.append("current project test command is unknown")

        template_use_cases = _as_list(template.project_defaults.get("primary_use_cases"))
        current_use_cases = _as_list(signals.get("primary_use_cases"))
        use_case_overlap = sorted(_overlap(template_use_cases, current_use_cases))
        fit["use_case_fit"] = use_case_overlap
        if use_case_overlap:
            score += min(0.2, 0.1 * len(use_case_overlap))
            evidence += 1
            reasons.append(f"focus matches {', '.join(use_case_overlap)}")

        safety_fit = self._safety_fit(template.safety_defaults, signals.get("safety", {}))
        fit["safety_fit"] = safety_fit
        if safety_fit:
            score += 0.08
            evidence += 1
            reasons.append("safety defaults align with explicit and source-preserving workflow")

        team_fit = self._team_fit(template, signals)
        fit["team_fit"] = team_fit
        if team_fit["matched_agents"] or team_fit["matched_team"]:
            score += 0.08
            evidence += 1
            reasons.append("team defaults overlap with current harness staffing")

        policy_fit = self._policy_fit(template.policy_defaults, signals.get("policy", {}))
        fit["policy_fit"] = policy_fit
        if policy_fit:
            score += min(0.12, 0.04 * len(policy_fit))
            evidence += 1
            reasons.append(f"policy defaults fit {', '.join(policy_fit)}")

        request_intents = _as_list(signals.get("request_intents"))
        request_fit = sorted(_overlap(template_use_cases + _as_list(template.tags) + _as_list(template.fit_hints), request_intents))
        if request:
            policy_request_fit = sorted(_overlap(_template_policy_terms(template), request_intents))
            request_fit = sorted(set(request_fit) | set(policy_request_fit))
            fit["request_fit"] = request_fit
            if request_fit:
                score += min(0.2, 0.08 * len(request_fit))
                evidence += 1
                reasons.append(f"request matches template signals: {', '.join(request_fit)}")
            else:
                warnings.append("request does not strongly match this template")
        else:
            fit["request_fit"] = []

        confidence = _clamp(0.35 + (0.08 * evidence))
        missing_signals = int(signals.get("missing_signals", 0) or 0)
        if missing_signals:
            confidence = _clamp(confidence - min(0.2, missing_signals * 0.03))
            warnings.append("recommendation uses partial project signals")
        try:
            from engine.project_template_history import TemplateHistoryBuilder

            history = TemplateHistoryBuilder().build_passport(Path(str(signals.get("workspace") or ".")), template.name)
        except Exception:
            history = None
        if history is not None:
            totals = history.totals
            positive_retrospectives = [
                record
                for record in history.outcome_records
                if record.event_kind == "retrospective" and record.outcome in {"strong", "good"}
            ]
            caution_retrospectives = [
                record
                for record in history.outcome_records
                if record.event_kind == "retrospective" and record.outcome in {"mixed", "weak"}
            ]
            fit["history_fit"] = {
                "applied": int(totals.get("applied", 0) or 0),
                "bootstrapped": int(totals.get("bootstrapped", 0) or 0),
                "positive_retrospectives": len(positive_retrospectives),
                "caution_retrospectives": len(caution_retrospectives),
            }
            if totals.get("applied", 0) or totals.get("bootstrapped", 0) or positive_retrospectives:
                score += 0.05
                reasons.append("template has prior positive local outcome history")
            if caution_retrospectives or totals.get("guardrail_blocked", 0) or totals.get("dismissed", 0):
                score -= 0.05
                warnings.append("template has local caution history")
        try:
            from engine.project_template_library_policy import (
                load_or_build_template_library_policy_overlay,
                template_library_policy_for_template,
            )

            overlay = load_or_build_template_library_policy_overlay(
                Path(str(signals.get("workspace") or ".")),
                save=True,
            )
            policy_decision = template_library_policy_for_template(overlay, template.name)
        except Exception:
            policy_decision = None
        if policy_decision is not None:
            fit["template_library_policy"] = {
                "decision_kind": policy_decision.decision_kind,
                "decision_id": policy_decision.decision_id,
                "source_ref": policy_decision.source_ref,
            }
            if policy_decision.decision_kind == "promote":
                score += 0.10
                reasons.append("previously promoted in local template library")
            elif policy_decision.decision_kind == "keep":
                score += 0.05
                reasons.append("kept in local template library")
            elif policy_decision.decision_kind == "backup":
                score += 0.04
                reasons.append("marked as backup template in local library")
            elif policy_decision.decision_kind == "watch":
                warnings.append("template is on local library watch")
            elif policy_decision.decision_kind == "retire":
                score -= 0.20
                warnings.append("template is retired in local library")
        try:
            from engine.project_improvement_interventions import effective_intervention_preferences

            intervention_summary = effective_intervention_preferences(Path(str(signals.get("workspace") or ".")))
            preferred_templates = {
                str(value).lower()
                for value in (intervention_summary or {}).get("preferred_template_names", [])
                if value
            }
            if preferred_templates and (
                str(template.name).lower() in preferred_templates
                or str(template.template_id).lower() in preferred_templates
            ):
                score += 0.05
                if intervention_summary.get("has_kept") and not intervention_summary.get("has_active"):
                    reasons.append("kept improvement prefers this template")
                else:
                    reasons.append("active improvement intervention prefers this template")
        except Exception as exc:
            logger.warning("active improvement intervention template bias load failed: %s", exc)
        try:
            from engine.project_template_qualification_decisions import load_lane_playbook_summary

            lane_playbook = load_lane_playbook_summary(Path(str(signals.get("workspace") or ".")))
        except Exception as exc:
            logger.warning("lane playbook template bias load failed: %s", exc)
            lane_playbook = {}
        if lane_playbook:
            default_template = str(lane_playbook.get("default_template_name") or "").strip()
            backup_templates = [str(item) for item in lane_playbook.get("backup_templates", []) if item]
            retired_templates = [str(item) for item in lane_playbook.get("retired_templates", []) if item]
            canary_template = str(lane_playbook.get("canary_template_name") or "").strip()
            template_keys = {_slug(template.name), _slug(template.template_id)}
            if default_template and _slug(default_template) in template_keys:
                score += 0.08
                reasons.append("selected as strongest-lane default via qualification")
                fit["lane_playbook"] = {"standing": "default", "source": lane_playbook.get("source_decision_ref")}
            elif canary_template and _slug(canary_template) in template_keys:
                score += 0.05
                reasons.append("staged as lane canary after stronger qualification")
                fit["lane_playbook"] = {
                    "standing": "canary",
                    "stage_id": lane_playbook.get("canary_stage_id"),
                    "source": lane_playbook.get("source_decision_ref"),
                }
                try:
                    from engine.project_template_canary_report import load_latest_canary_report_summary

                    canary_report = load_latest_canary_report_summary(
                        Path(str(signals.get("workspace") or ".")),
                        template.name,
                    )
                except Exception as exc:
                    logger.warning("canary report template bias load failed: %s", exc)
                    canary_report = {}
                if canary_report.get("verdict") == "promote_ready":
                    score += 0.03
                    reasons.insert(0, "canary is promotion-ready in the strongest lane")
                    fit["canary_report"] = {
                        "verdict": "promote_ready",
                        "report_id": canary_report.get("report_id"),
                    }
            elif any(_slug(item) in template_keys for item in backup_templates):
                score += 0.03
                reasons.append("kept as strongest-lane backup via qualification")
                fit["lane_playbook"] = {"standing": "backup", "source": lane_playbook.get("source_decision_ref")}
            elif any(_slug(item) in template_keys for item in retired_templates):
                score -= 0.16
                warnings.append("retired from strongest-lane playbook")
                fit["lane_playbook"] = {"standing": "retired", "source": lane_playbook.get("source_decision_ref")}
        final_score = _clamp(score)
        return TemplateCandidate(
            template_id=template.template_id,
            name=template.name,
            template_kind=template.template_kind,
            score=final_score,
            confidence=confidence,
            recommendation=_recommendation_for_score(final_score),
            reasons=_dedupe(reasons)[:8],
            warnings=_dedupe(warnings)[:8],
            project_fit=fit,
        )

    @staticmethod
    def _safety_fit(template_safety: dict[str, Any], current_safety: dict[str, Any]) -> bool:
        combined = {**current_safety, **template_safety}
        text = " ".join(f"{key}:{value}" for key, value in combined.items()).lower()
        return any(term in text for term in ("explicit", "preserve", "source", "test"))

    @staticmethod
    def _team_fit(template: HarnessTemplate, signals: dict[str, Any]) -> dict[str, Any]:
        current_agents = _as_list(signals.get("active_agents"))
        template_agents = _as_list(template.agent_defaults.get("active_agents"))
        matched_agents = sorted(_overlap(template_agents, current_agents))
        active_team = _norm(signals.get("active_team_id") or signals.get("active_team_name"))
        template_team = _norm(template.team_defaults.get("active_team_id") or template.team_defaults.get("active_team_name"))
        return {
            "matched_agents": matched_agents,
            "matched_team": bool(active_team and template_team and active_team == template_team),
        }

    @staticmethod
    def _policy_fit(template_policy: dict[str, Any], current_policy: dict[str, Any]) -> list[str]:
        matched: list[str] = []
        for key in ("test_first_practice", "narrow_change_scope", "increase_review_support"):
            if bool(template_policy.get(key)) and bool(current_policy.get(key, template_policy.get(key))):
                matched.append(key)
        focus_overlap = sorted(_overlap(_as_list(template_policy.get("promote_request_focus")), _as_list(current_policy.get("promote_request_focus"))))
        matched.extend(focus_overlap)
        return _dedupe(matched)


class TemplateRecommendationStore:
    """템플릿 추천 리포트 저장소."""

    def save(self, report: TemplateRecommendationReport, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), report.to_dict())

    def load(self, path: Path) -> TemplateRecommendationReport:
        payload = _load_yaml(Path(path).resolve())
        candidates = [
            TemplateCandidate(
                template_id=str(item.get("template_id", "")),
                name=str(item.get("name", "")),
                template_kind=str(item.get("template_kind", "harness")),
                score=float(item.get("score", 0.0) or 0.0),
                confidence=float(item.get("confidence", 0.0) or 0.0),
                recommendation=str(item.get("recommendation", "weak")),
                reasons=[str(value) for value in item.get("reasons", []) if value],
                warnings=[str(value) for value in item.get("warnings", []) if value],
                project_fit=dict(item.get("project_fit", {}) if isinstance(item.get("project_fit"), dict) else {}),
            )
            for item in payload.get("candidates", []) or []
            if isinstance(item, dict)
        ]
        return TemplateRecommendationReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            report_id=str(payload.get("report_id", "")),
            project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
            workspace=str(payload.get("workspace", "")),
            mode=str(payload.get("mode", "project")),
            request=str(payload.get("request")) if payload.get("request") is not None else None,
            current_template_name=(
                str(payload.get("current_template_name"))
                if payload.get("current_template_name") is not None
                else None
            ),
            best_template_name=(
                str(payload.get("best_template_name"))
                if payload.get("best_template_name") is not None
                else None
            ),
            backup_templates=[str(value) for value in payload.get("backup_templates", []) if value],
            candidates=candidates,
            summary=dict(payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}),
            next_actions=[str(value) for value in payload.get("next_actions", []) if value],
            warnings=[str(value) for value in payload.get("warnings", []) if value],
            errors=[str(value) for value in payload.get("errors", []) if value],
        )


def load_template_recommendation_summary(project_root: Path) -> dict[str, Any]:
    """status/harness show에서 쓰는 가벼운 추천 요약."""
    root = Path(project_root).resolve()
    current = load_current_template(root)
    if current and current.get("name"):
        return {"current_template_name": current.get("name"), "best_template_name": None, "warnings": []}
    path = default_template_recommendation_path(root)
    try:
        if path.exists():
            report = TemplateRecommendationStore().load(path)
        else:
            report = TemplateRecommendationBuilder().build(root)
    except Exception as exc:
        logger.warning("template recommendation summary failed: %s", exc)
        return {"best_template_name": None, "warnings": [f"template recommendation failed: {exc}"]}
    return {
        "current_template_name": report.current_template_name,
        "best_template_name": report.best_template_name,
        "backup_templates": list(report.backup_templates),
        "next_actions": list(report.next_actions),
        "warnings": list(report.warnings),
    }


def render_template_recommendation(report: TemplateRecommendationReport) -> str:
    """템플릿 추천 리포트를 사람이 읽기 좋게 렌더링한다."""
    title = "Template Recommendation"
    best_label = "Best fit for this request:" if report.request else "Best fit:"
    lines = [
        title,
        "==================================================",
        "",
        "Workspace:",
        f"  {Path(report.workspace).name if report.workspace else '(unknown)'}",
    ]
    if report.request:
        lines.extend(["", "Request:", f"  {report.request}"])
    if report.current_template_name:
        lines.extend(["", "Current template:", f"  {report.current_template_name}"])
    lines.extend(["", best_label])
    lines.append(f"  {report.best_template_name or 'none'}")
    best = next((candidate for candidate in report.candidates if candidate.name == report.best_template_name), None)
    if best and best.reasons:
        lines.extend(["", "Why:"])
        lines.extend([f"  - {reason}" for reason in best.reasons[:5]])
    if report.backup_templates:
        lines.extend(["", "Backups:"])
        lines.extend([f"  - {name}" for name in report.backup_templates[:3]])
    weak = [candidate.name for candidate in report.candidates if candidate.recommendation in {"weak", "reject"}]
    if weak:
        lines.extend(["", "Weak fits:"])
        lines.extend([f"  - {name}" for name in weak[:3]])
    if report.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend([f"  - {warning}" for warning in report.warnings[:4]])
    if report.next_actions:
        lines.extend(["", "Next:"])
        lines.extend([f"  {action}" for action in report.next_actions[:3]])
    return "\n".join(lines)


def render_template_recommendation_hint(summary: dict[str, Any]) -> str:
    """status/harness show용 한 화면 추천 힌트."""
    current = summary.get("current_template_name")
    if current:
        return "\n".join(["Template:", f"  {current} (current)"])
    best = summary.get("best_template_name")
    if not best:
        return "Template hint:\n  none available yet"
    return "\n".join([
        "Template hint:",
        f"  {best} looks like the best fit for this project",
        "",
        "Next:",
        f"  cambrian template diff {best}",
    ])


def _collect_project_signals(root: Path, request: str | None, warnings: list[str]) -> dict[str, Any]:
    signals: dict[str, Any] = {
        "project_name": root.name,
        "workspace": str(root),
        "project_type": "",
        "stack": [],
        "test_command": "",
        "primary_use_cases": [],
        "safety": {},
        "policy": {},
        "active_agents": [],
        "active_team_id": "",
        "active_team_name": "",
        "request_intents": _infer_request_intents(request),
        "signals_mode": "lightweight",
        "missing_signals": 0,
    }
    cambrian_dir = root / ".cambrian"
    project_path = cambrian_dir / "project.yaml"
    if project_path.exists():
        signals["signals_mode"] = "project"
        try:
            project_payload = _load_yaml(project_path)
        except Exception as exc:
            warnings.append(f"project signal load failed: {exc}")
            project_payload = {}
        project_meta = project_payload.get("project", {}) if isinstance(project_payload.get("project"), dict) else {}
        test_meta = project_payload.get("test", {}) if isinstance(project_payload.get("test"), dict) else {}
        ai_work = project_payload.get("ai_work", {}) if isinstance(project_payload.get("ai_work"), dict) else {}
        signals["project_name"] = project_meta.get("name") or root.name
        signals["project_type"] = project_meta.get("type") or signals["project_type"]
        signals["stack"] = _dedupe(_as_list(project_meta.get("stack")) + _as_list(signals.get("stack")))
        signals["test_command"] = test_meta.get("command") or signals["test_command"]
        signals["primary_use_cases"] = _dedupe(_as_list(ai_work.get("primary_use_cases")))
        signals["safety"] = dict(project_payload.get("safety", {}) if isinstance(project_payload.get("safety"), dict) else {})
    _collect_harness_signals(root, signals, warnings)
    _collect_policy_signals(root, signals, warnings)
    _collect_team_signals(root, signals, warnings)
    _collect_lightweight_signals(root, signals)
    if request:
        signals["primary_use_cases"] = _dedupe(_as_list(signals.get("primary_use_cases")) + _as_list(signals.get("request_intents")))
    for key in ("project_type", "stack", "test_command", "primary_use_cases"):
        value = signals.get(key)
        if not value:
            signals["missing_signals"] = int(signals.get("missing_signals", 0) or 0) + 1
    return signals


def _collect_harness_signals(root: Path, signals: dict[str, Any], warnings: list[str]) -> None:
    harness_path = root / ".cambrian" / "harness" / "profile.yaml"
    if not harness_path.exists():
        return
    try:
        harness = _load_yaml(harness_path)
    except Exception as exc:
        warnings.append(f"harness signal load failed: {exc}")
        return
    if harness.get("project_name"):
        signals["project_name"] = harness.get("project_name")
    signals["project_type"] = harness.get("project_type") or signals.get("project_type")
    signals["stack"] = _dedupe(_as_list(signals.get("stack")) + _as_list(harness.get("stack")))
    signals["test_command"] = harness.get("test_command") or signals.get("test_command")
    signals["primary_use_cases"] = _dedupe(_as_list(signals.get("primary_use_cases")) + _as_list(harness.get("primary_use_cases")))
    signals["active_agents"] = _dedupe(_as_list(signals.get("active_agents")) + _as_list(harness.get("active_agents")))
    if isinstance(harness.get("safety"), dict):
        safety = dict(signals.get("safety", {}) if isinstance(signals.get("safety"), dict) else {})
        safety.update(harness.get("safety", {}))
        signals["safety"] = safety


def _collect_policy_signals(root: Path, signals: dict[str, Any], warnings: list[str]) -> None:
    policy_path = root / ".cambrian" / "harness" / "policy_overlay.yaml"
    if not policy_path.exists():
        return
    try:
        policy = _load_yaml(policy_path)
    except Exception as exc:
        warnings.append(f"policy signal load failed: {exc}")
        return
    signals["policy"] = {
        "test_first_practice": bool(policy.get("test_first_practice")),
        "narrow_change_scope": bool(policy.get("narrow_change_scope")),
        "increase_review_support": bool(policy.get("increase_review_support")),
        "promote_request_focus": _as_list(policy.get("promote_request_focus")),
    }


def _collect_team_signals(root: Path, signals: dict[str, Any], warnings: list[str]) -> None:
    teams_path = root / ".cambrian" / "agents" / "teams.yaml"
    if teams_path.exists():
        try:
            teams = _load_yaml(teams_path)
            signals["active_team_id"] = teams.get("active_team_id") or signals.get("active_team_id")
            active_team_id = _norm(signals.get("active_team_id"))
            for item in teams.get("teams", []) or []:
                if not isinstance(item, dict):
                    continue
                if _norm(item.get("team_id")) == active_team_id or _norm(item.get("name")) == active_team_id:
                    signals["active_team_name"] = item.get("name") or item.get("team_id")
                    signals["active_agents"] = _dedupe(_as_list(signals.get("active_agents")) + _as_list(item.get("members")))
        except Exception as exc:
            warnings.append(f"team signal load failed: {exc}")
    team_policy_path = root / ".cambrian" / "agents" / "team_policy_overlay.yaml"
    if team_policy_path.exists():
        try:
            team_policy = _load_yaml(team_policy_path)
            signals["active_team_id"] = team_policy.get("current_team_id") or signals.get("active_team_id")
            signals["active_team_name"] = team_policy.get("current_team_name") or signals.get("active_team_name")
        except Exception as exc:
            warnings.append(f"team policy signal load failed: {exc}")


def _collect_lightweight_signals(root: Path, signals: dict[str, Any]) -> None:
    stack = _as_list(signals.get("stack"))
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        stack.append("python")
        if not signals.get("project_type"):
            signals["project_type"] = "python"
        pyproject_text = ""
        pyproject_path = root / "pyproject.toml"
        if pyproject_path.exists():
            pyproject_text = pyproject_path.read_text(encoding="utf-8", errors="ignore").lower()
        if "pytest" in pyproject_text or (root / "tests").exists():
            stack.append("pytest")
            if not signals.get("test_command"):
                signals["test_command"] = "pytest -q"
    if (root / "package.json").exists():
        stack.append("javascript")
        package_text = (root / "package.json").read_text(encoding="utf-8", errors="ignore").lower()
        if (root / "tsconfig.json").exists() or ".ts" in package_text:
            stack.append("typescript")
        if "test" in package_text and not signals.get("test_command"):
            signals["test_command"] = "npm test"
        if not signals.get("project_type"):
            signals["project_type"] = "javascript"
    if not signals.get("primary_use_cases"):
        guessed = _infer_request_intents(root.name)
        signals["primary_use_cases"] = [item for item in guessed if item not in {"auth"}]
    signals["stack"] = _dedupe(stack)


def _infer_request_intents(request: str | None) -> list[str]:
    text = str(request or "").lower()
    intents: list[str] = []
    if any(token in text for token in ("login", "auth", "로그인", "인증")):
        intents.append("auth")
    if any(token in text for token in ("bug", "error", "fix", "fail", "에러", "버그", "수정", "실패")):
        intents.append("bug_fix")
    if any(token in text for token in ("test", "pytest", "regression", "테스트", "검증")):
        intents.append("regression_test")
    if any(token in text for token in ("doc", "docs", "readme", "문서")):
        intents.append("docs_update")
    if any(token in text for token in ("refactor", "cleanup", "정리", "리팩터")):
        intents.append("small_refactor")
    return _dedupe(intents)


def _template_policy_terms(template: HarnessTemplate) -> list[str]:
    terms: list[str] = []
    policy = template.policy_defaults
    if policy.get("test_first_practice"):
        terms.extend(["test", "regression_test"])
    if policy.get("narrow_change_scope"):
        terms.extend(["bug_fix", "small_refactor"])
    if policy.get("increase_review_support"):
        terms.extend(["review", "risk"])
    terms.extend(_as_list(policy.get("promote_request_focus")))
    terms.extend(_as_list(template.team_defaults.get("active_team_name")))
    return _dedupe(terms)


def _recommendation_for_score(score: float) -> str:
    if score >= 0.7:
        return "strong"
    if score >= 0.45:
        return "possible"
    if score >= 0.25:
        return "weak"
    return "reject"
