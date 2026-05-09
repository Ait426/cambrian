"""Cambrian의 현재 주력 win lane profile을 계산한다."""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
LANE_ID = "python-pytest-auth-bug-core"
LANE_LABEL = "Python + pytest + auth/login narrow bug fix"
DEFAULT_TEAM = "auth-bug-team"
DEFAULT_TEMPLATE = "auth-bug-template"
DEFAULT_WORKSET = "auth-bug-workset"
AUTH_TOKENS = {
    "auth",
    "login",
    "account",
    "username",
    "password",
    "session",
    "signin",
    "signup",
    "credential",
}
OUTSIDE_TOKENS = {
    "docs",
    "documentation",
    "readme",
    "migration",
    "rewrite",
    "refactor",
    "architecture",
    "design",
    "essay",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("win lane artifact load failed: %s (%s)", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
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


def default_lane_dir(project_root: Path) -> Path:
    return Path(project_root).resolve() / ".cambrian" / "lane"


def default_lane_profile_path(project_root: Path) -> Path:
    return default_lane_dir(project_root) / "profile.yaml"


@dataclass
class WinLaneProfile:
    schema_version: str
    generated_at: str
    lane_id: str
    label: str
    status: str
    project_name: str | None
    workspace: str
    project_type: str | None
    stack: list[str]
    test_command: str | None
    primary_use_cases: list[str]
    strongest_for: list[str]
    outside_scope_notes: list[str]
    default_team: str | None
    default_template: str | None
    default_workset: str | None
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WinLaneStore:
    def save(self, profile: WinLaneProfile, path: Path) -> Path:
        return _save_yaml(Path(path).resolve(), profile.to_dict())

    def load(self, path: Path) -> WinLaneProfile:
        return _profile_from_dict(_load_yaml(Path(path).resolve()))


class WinLaneBuilder:
    def build(self, project_root: Path) -> WinLaneProfile:
        root = Path(project_root).resolve()
        warnings: list[str] = []
        errors: list[str] = []
        project_payload = _load_yaml(root / ".cambrian" / "project.yaml")
        harness_payload = _load_yaml(root / ".cambrian" / "harness" / "profile.yaml")
        rules_payload = _load_yaml(root / ".cambrian" / "rules.yaml")
        project_meta = project_payload.get("project") if isinstance(project_payload.get("project"), dict) else {}
        test_meta = project_payload.get("test") if isinstance(project_payload.get("test"), dict) else {}
        ai_work = project_payload.get("ai_work") if isinstance(project_payload.get("ai_work"), dict) else {}

        project_name = str(project_meta.get("name")) if project_meta.get("name") is not None else root.name
        project_type = _first(
            project_meta.get("type"),
            harness_payload.get("project_type"),
            _detect_project_type(root),
        )
        stack = _dedupe([
            *[str(item) for item in _as_list(project_meta.get("stack")) if item],
            *[str(item) for item in _as_list(harness_payload.get("stack")) if item],
            *_detect_stack(root),
        ])
        test_command = _first(
            test_meta.get("command"),
            harness_payload.get("test_command"),
            _detect_test_command(root),
        )
        primary_use_cases = _dedupe([
            *[str(item) for item in _as_list(ai_work.get("primary_use_cases")) if item],
            *[str(item) for item in _as_list(harness_payload.get("primary_use_cases")) if item],
        ])

        evidence_text = _collect_lane_text(root, project_payload, harness_payload, rules_payload)
        has_python = _has_token([project_type, *stack, evidence_text], {"python", "pyproject", ".py"})
        has_pytest = _has_token([test_command, *stack, evidence_text], {"pytest"})
        has_bug_fix = _has_token(
            primary_use_cases + [evidence_text],
            {"bug_fix", "bug", "fix", "regression_test", "regression"},
        )
        has_auth = _has_token([evidence_text, *primary_use_cases], AUTH_TOKENS)
        has_safety = _has_token(
            [evidence_text, str(rules_payload), str(harness_payload)],
            {"test_first", "test-first", "narrow", "review", "review_support", "safe-patch", "safety"},
        )
        outside_signal = _has_token([evidence_text, *primary_use_cases], OUTSIDE_TOKENS)

        reasons: list[str] = []
        cautions: list[str] = []
        if has_python:
            reasons.append("Python project signal found")
        else:
            cautions.append("Python signal is weak")
        if has_pytest:
            reasons.append("pytest test discipline signal found")
        else:
            cautions.append("pytest signal is weak")
        if has_bug_fix:
            reasons.append("bug_fix/regression work signal found")
        else:
            cautions.append("bug_fix signal is weak")
        if has_auth:
            reasons.append("auth/login/account signal found")
        else:
            cautions.append("auth/login specialization signal is weak")
        if has_safety:
            reasons.append("test-first/narrow-scope/review-support safety signal found")
        else:
            cautions.append("test-first/narrow-scope/review-support signal is weak")
        if outside_signal:
            cautions.append("docs/refactor/migration-like outside-lane signal found")

        if has_python and has_pytest and has_bug_fix and has_auth and not outside_signal:
            status = "strong"
        elif has_python and has_pytest and has_bug_fix and not outside_signal:
            status = "partial"
        else:
            status = "outside"

        default_template = DEFAULT_TEMPLATE
        try:
            from engine.project_template_qualification_decisions import load_lane_playbook_summary

            playbook = load_lane_playbook_summary(root)
            if playbook.get("default_template_name"):
                default_template = str(playbook.get("default_template_name"))
                reasons.append("lane playbook selected the default template via qualification")
        except Exception as exc:
            logger.warning("lane playbook default load failed: %s", exc)

        return WinLaneProfile(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            lane_id=LANE_ID,
            label=LANE_LABEL,
            status=status,
            project_name=project_name,
            workspace=str(root),
            project_type=project_type,
            stack=stack,
            test_command=test_command,
            primary_use_cases=primary_use_cases,
            strongest_for=[
                "Python projects",
                "pytest-backed validation",
                "narrow bug fixes",
                "auth/login/account-adjacent work",
            ],
            outside_scope_notes=[
                "docs-heavy requests may have lower automation quality",
                "wide refactors and migrations are outside the current strongest lane",
                "non-Python or no-test projects should expect weaker fit",
            ],
            default_team=DEFAULT_TEAM,
            default_template=default_template,
            default_workset=DEFAULT_WORKSET,
            reasons=_dedupe(reasons),
            cautions=_dedupe(cautions),
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
        )


def build_and_save_lane_profile(project_root: Path) -> tuple[WinLaneProfile, Path]:
    root = Path(project_root).resolve()
    profile = WinLaneBuilder().build(root)
    path = WinLaneStore().save(profile, default_lane_profile_path(root))
    return profile, path


def load_lane_summary(project_root: Path) -> dict[str, Any]:
    path = default_lane_profile_path(Path(project_root).resolve())
    payload = _load_yaml(path)
    if not payload:
        return {}
    return {
        "lane_id": payload.get("lane_id"),
        "label": payload.get("label"),
        "status": payload.get("status"),
        "default_team": payload.get("default_team"),
        "default_template": payload.get("default_template"),
        "default_workset": payload.get("default_workset"),
    }


def request_lane_fit(profile: WinLaneProfile, request: str) -> dict[str, Any]:
    text = str(request or "").lower()
    tokens = set(re.findall(r"[a-zA-Z0-9_/-]+", text))
    has_auth = bool(tokens & AUTH_TOKENS) or any(token in text for token in AUTH_TOKENS)
    has_bug = any(token in text for token in ("bug", "fix", "error", "fail", "regression", "에러", "버그", "수정"))
    outside = any(token in text for token in OUTSIDE_TOKENS) or any(
        word in text for word in ("문서", "리팩터", "마이그레이션")
    )
    if profile.status == "strong" and has_auth and has_bug and not outside:
        status = "in_lane"
        summary = "current request matches the auth-bug core"
    elif profile.status in {"strong", "partial"} and has_bug and not outside:
        status = "partial"
        summary = "this request is near the current strongest lane, but not a direct auth/login bug fix"
    else:
        status = "outside"
        summary = "this request is outside Cambrian's current strongest lane"
    return {
        "lane_id": profile.lane_id,
        "label": profile.label,
        "project_lane_status": profile.status,
        "request_fit": status,
        "summary": summary,
        "caution": status == "outside",
    }


def render_lane_profile(profile: WinLaneProfile, *, include_details: bool = True) -> str:
    lines = [
        "Current strongest lane:",
        f"  {profile.label}",
        f"  status: {profile.status}",
        "",
        "Defaults:",
        f"  team    : {profile.default_team or 'none'}",
        f"  template: {profile.default_template or 'none'}",
        f"  workset : {profile.default_workset or 'none'}",
    ]
    if include_details:
        lines.extend([
            "",
            "Strongest for:",
            *[f"  - {item}" for item in profile.strongest_for],
        ])
        if profile.cautions:
            lines.extend(["", "Cautions:"])
            lines.extend([f"  - {item}" for item in profile.cautions[:4]])
    return "\n".join(lines)


def render_request_lane_fit(fit: dict[str, Any]) -> str:
    request_fit_value = str(fit.get("request_fit") or "outside")
    if request_fit_value == "in_lane":
        return "\n".join([
            "Win lane:",
            "  current request matches the auth-bug core",
        ])
    if request_fit_value == "partial":
        return "\n".join([
            "Win lane:",
            "  this request is near the current strongest lane, but not a direct auth/login bug fix",
        ])
    return "\n".join([
        "Win lane caution:",
        "  this request is outside Cambrian's current strongest lane",
        "  You can continue, but expect lower automation quality.",
    ])


def _profile_from_dict(payload: dict[str, Any]) -> WinLaneProfile:
    return WinLaneProfile(
        schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
        generated_at=str(payload.get("generated_at") or ""),
        lane_id=str(payload.get("lane_id") or LANE_ID),
        label=str(payload.get("label") or LANE_LABEL),
        status=str(payload.get("status") or "outside"),
        project_name=str(payload.get("project_name")) if payload.get("project_name") is not None else None,
        workspace=str(payload.get("workspace") or ""),
        project_type=str(payload.get("project_type")) if payload.get("project_type") is not None else None,
        stack=[str(item) for item in payload.get("stack", []) if item],
        test_command=str(payload.get("test_command")) if payload.get("test_command") is not None else None,
        primary_use_cases=[str(item) for item in payload.get("primary_use_cases", []) if item],
        strongest_for=[str(item) for item in payload.get("strongest_for", []) if item],
        outside_scope_notes=[str(item) for item in payload.get("outside_scope_notes", []) if item],
        default_team=str(payload.get("default_team")) if payload.get("default_team") is not None else None,
        default_template=str(payload.get("default_template")) if payload.get("default_template") is not None else None,
        default_workset=str(payload.get("default_workset")) if payload.get("default_workset") is not None else None,
        reasons=[str(item) for item in payload.get("reasons", []) if item],
        cautions=[str(item) for item in payload.get("cautions", []) if item],
        warnings=[str(item) for item in payload.get("warnings", []) if item],
        errors=[str(item) for item in payload.get("errors", []) if item],
    )


def _first(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _detect_project_type(root: Path) -> str | None:
    if (root / "pyproject.toml").exists() or list(root.glob("*.py")) or (root / "src").exists():
        return "python"
    return None


def _detect_stack(root: Path) -> list[str]:
    stack: list[str] = []
    if (root / "pyproject.toml").exists() or list(root.rglob("*.py")):
        stack.append("python")
    if (root / "pytest.ini").exists() or _file_contains(root / "pyproject.toml", "pytest"):
        stack.append("pytest")
    return stack


def _detect_test_command(root: Path) -> str | None:
    if (root / "pytest.ini").exists() or _file_contains(root / "pyproject.toml", "pytest"):
        return "pytest -q"
    return None


def _file_contains(path: Path, needle: str) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        return needle.lower() in path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError as exc:
        logger.warning("win lane file scan failed: %s (%s)", path, exc)
        return False


def _collect_lane_text(root: Path, *payloads: dict[str, Any]) -> str:
    chunks = [str(payload) for payload in payloads if payload]
    scan_roots = [
        root / ".cambrian" / "benchmarks",
        root / ".cambrian" / "templates",
    ]
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*.yaml"))[:80]:
            try:
                chunks.append(path.name)
                chunks.append(path.read_text(encoding="utf-8", errors="ignore")[:4000])
            except OSError as exc:
                logger.warning("win lane artifact scan failed: %s (%s)", path, exc)
    for path in list(root.glob("*auth*")) + list(root.glob("*login*")):
        chunks.append(path.name)
    return " ".join(chunks).lower()


def _has_token(values: list[Any], tokens: set[str]) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    return any(token.lower() in text for token in tokens)
