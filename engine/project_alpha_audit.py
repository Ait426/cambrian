"""Cambrian 프로젝트 모드 알파 준비도 점검 도구."""

from __future__ import annotations

import logging
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from engine.project_notes import ProjectNotesStore, default_notes_dir

logger = logging.getLogger(__name__)


SCHEMA_VERSION = "1.0.0"

_COMMAND_PATTERNS: dict[str, tuple[str, bool]] = {
    "init": (r'add_parser\(\s*"init"', True),
    "run": (r'add_parser\(\s*"run"', True),
    "status": (r'add_parser\(\s*"status"', True),
    "do": (r'add_parser\(\s*"do"', True),
    "clarify": (r'add_parser\(\s*"clarify"', True),
    "context": (r'add_parser\(\s*"context"', True),
    "summary": (r'add_parser\(\s*"summary"', True),
    "demo": (r'add_parser\(\s*"demo"', True),
    "memory": (r'add_parser\(\s*"memory"', False),
    "patch intent": (r'patch_subparsers\.add_parser\(\s*"intent"', True),
    "patch propose": (r'patch_subparsers\.add_parser\(\s*"propose"', True),
    "patch apply": (r'patch_subparsers\.add_parser\(\s*"apply"', True),
}


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 만든다."""
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


def _read_text(path: Path, warnings: list[str]) -> str:
    """텍스트 파일을 읽고 실패 시 경고를 남긴다."""
    if not path.exists():
        warnings.append(f"missing file: {path}")
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(f"read failed: {path} ({exc})")
        logger.warning("alpha audit read failed: %s (%s)", path, exc)
        return ""


def _load_yaml(path: Path, warnings: list[str]) -> dict | None:
    """YAML 파일을 읽고 dict만 허용한다."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        warnings.append(f"yaml read failed: {path} ({exc})")
        logger.warning("alpha audit yaml read failed: %s (%s)", path, exc)
        return None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        warnings.append(f"yaml format error: {path}")
        return None
    return payload


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


def default_alpha_audit_path(project_root: Path) -> Path:
    """기본 alpha readiness report 경로를 반환한다."""
    return Path(project_root).resolve() / ".cambrian" / "audit" / "alpha_readiness.yaml"


@dataclass
class AuditCheckResult:
    """단일 알파 점검 항목 결과."""

    check_id: str
    title: str
    status: str
    severity: str
    summary: str
    details: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class AlphaReadinessReport:
    """알파 릴리스 준비도 보고서."""

    schema_version: str
    generated_at: str
    status: str
    summary: dict
    verdict: str
    checks: list[AuditCheckResult]
    next_actions: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["checks"] = [item.to_dict() for item in self.checks]
        return payload


class AlphaReadinessStore:
    """alpha_readiness.yaml 저장/로드 도구."""

    def save(self, report: AlphaReadinessReport, path: Path) -> Path:
        """보고서를 YAML로 저장한다."""
        target = Path(path).resolve()
        _atomic_write_text(
            target,
            yaml.safe_dump(report.to_dict(), allow_unicode=True, sort_keys=False),
        )
        return target

    def load(self, path: Path) -> AlphaReadinessReport:
        """저장된 보고서를 불러온다."""
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise ValueError("alpha readiness YAML 최상위는 dict여야 합니다.")
        checks_payload = payload.get("checks", [])
        checks: list[AuditCheckResult] = []
        for item in checks_payload if isinstance(checks_payload, list) else []:
            if not isinstance(item, dict):
                continue
            checks.append(
                AuditCheckResult(
                    check_id=str(item.get("check_id", "")),
                    title=str(item.get("title", "")),
                    status=str(item.get("status", "skip")),
                    severity=str(item.get("severity", "info")),
                    summary=str(item.get("summary", "")),
                    details=[str(detail) for detail in item.get("details", []) if detail],
                    suggested_actions=[
                        str(action) for action in item.get("suggested_actions", []) if action
                    ],
                )
            )
        return AlphaReadinessReport(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            generated_at=str(payload.get("generated_at", "")),
            status=str(payload.get("status", "warn")),
            summary=dict(payload.get("summary", {})) if isinstance(payload.get("summary"), dict) else {},
            verdict=str(payload.get("verdict", "")),
            checks=checks,
            next_actions=[str(item) for item in payload.get("next_actions", []) if item],
            warnings=[str(item) for item in payload.get("warnings", []) if item],
            errors=[str(item) for item in payload.get("errors", []) if item],
        )


def load_alpha_readiness(path: Path) -> AlphaReadinessReport:
    """alpha readiness report를 읽는다."""
    return AlphaReadinessStore().load(path)


class ProjectAlphaAudit:
    """프로젝트 모드 알파 준비도를 구조적으로 점검한다."""

    def run(self, project_root: Path) -> AlphaReadinessReport:
        """프로젝트 루트를 읽어서 알파 readiness 보고서를 만든다."""
        root = Path(project_root).resolve()
        warnings: list[str] = []
        checks = [
            self._check_project_mode_commands(root, warnings),
            self._check_wizard_config_readiness(root, warnings),
            self._check_explicit_adoption_boundary(root, warnings),
            self._check_source_mutation_boundary(root, warnings),
            self._check_golden_path_docs(root, warnings),
            self._check_demo_asset_readiness(root, warnings),
            self._check_status_next_continuity(root, warnings),
            self._check_memory_visibility(root, warnings),
            self._check_local_only_principle(root, warnings),
            self._check_user_notes(root),
            self._check_artifact_transparency(root, warnings),
        ]
        counts = {
            "pass": sum(1 for item in checks if item.status == "pass"),
            "warn": sum(1 for item in checks if item.status == "warn"),
            "fail": sum(1 for item in checks if item.status == "fail"),
            "skip": sum(1 for item in checks if item.status == "skip"),
        }
        if counts["fail"] > 0:
            status = "fail"
            verdict = "not alpha ready"
        elif counts["warn"] >= 2:
            status = "warn"
            verdict = "alpha ready with warnings"
        else:
            status = "pass"
            verdict = "alpha ready"

        suggested_actions: list[str] = []
        for item in checks:
            suggested_actions.extend(item.suggested_actions)
        if not suggested_actions:
            suggested_actions.append("Run `cambrian alpha check --save` before sharing the alpha build.")

        return AlphaReadinessReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            status=status,
            summary=counts,
            verdict=verdict,
            checks=checks,
            next_actions=_dedupe(suggested_actions),
            warnings=_dedupe(warnings),
            errors=[],
        )

    def _check_project_mode_commands(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """핵심 프로젝트 모드 명령 존재 여부를 점검한다."""
        cli_text = _read_text(root / "engine" / "cli.py", warnings)
        missing_required: list[str] = []
        missing_optional: list[str] = []
        for label, (pattern, required) in _COMMAND_PATTERNS.items():
            if not re.search(pattern, cli_text):
                if required:
                    missing_required.append(label)
                else:
                    missing_optional.append(label)
        if missing_required:
            return AuditCheckResult(
                check_id="project_mode_commands",
                title="Project mode commands present",
                status="fail",
                severity="high",
                summary="핵심 project mode 명령이 일부 빠져 있습니다.",
                details=[f"missing required command: {item}" for item in missing_required],
                suggested_actions=["Restore the missing CLI parser entries and rerun `cambrian alpha check`."],
            )
        if missing_optional:
            return AuditCheckResult(
                check_id="project_mode_commands",
                title="Project mode commands present",
                status="warn",
                severity="warning",
                summary="보조 project mode 명령 일부가 보이지 않습니다.",
                details=[f"missing secondary command: {item}" for item in missing_optional],
                suggested_actions=["Review optional command coverage in `engine/cli.py`."],
            )
        return AuditCheckResult(
            check_id="project_mode_commands",
            title="Project mode commands present",
            status="pass",
            severity="info",
            summary="핵심 project mode 명령이 모두 보입니다.",
        )

    def _check_wizard_config_readiness(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """프로젝트 초기화와 필수 config 파일을 점검한다."""
        cambrian_dir = root / ".cambrian"
        required = [
            "project.yaml",
            "rules.yaml",
            "skills.yaml",
            "profile.yaml",
        ]
        missing = [name for name in required if not (cambrian_dir / name).exists()]
        optional_missing = [name for name in ["init_report.yaml"] if not (cambrian_dir / name).exists()]
        if missing:
            return AuditCheckResult(
                check_id="wizard_config_readiness",
                title="Wizard and config readiness",
                status="fail",
                severity="high",
                summary="프로젝트가 아직 Cambrian project mode로 완전히 초기화되지 않았습니다.",
                details=[f"missing config: .cambrian/{item}" for item in missing],
                suggested_actions=["Run `cambrian init --wizard` and rerun the audit."],
            )
        if optional_missing:
            return AuditCheckResult(
                check_id="wizard_config_readiness",
                title="Wizard and config readiness",
                status="warn",
                severity="warning",
                summary="필수 config는 있지만 onboarding 메타데이터가 일부 없습니다.",
                details=[f"missing onboarding metadata: .cambrian/{item}" for item in optional_missing],
                suggested_actions=["Re-run `cambrian init --wizard` if you want a complete onboarding record."],
            )
        return AuditCheckResult(
            check_id="wizard_config_readiness",
            title="Wizard and config readiness",
            status="pass",
            severity="info",
            summary="필수 project mode config가 모두 준비되어 있습니다.",
        )

    def _check_explicit_adoption_boundary(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """explicit adoption 경계를 점검한다."""
        rules_payload = _load_yaml(root / ".cambrian" / "rules.yaml", warnings) or {}
        profile_payload = _load_yaml(root / ".cambrian" / "profile.yaml", warnings) or {}
        continue_text = _read_text(root / "engine" / "project_continue.py", warnings)
        apply_text = _read_text(root / "engine" / "project_patch_apply.py", warnings)
        commands_doc = _read_text(root / "docs" / "COMMANDS.md", warnings).lower()

        failures: list[str] = []
        warnings_list: list[str] = []

        safety_payload = rules_payload.get("safety", {}) if isinstance(rules_payload.get("safety"), dict) else {}
        review_payload = rules_payload.get("review", {}) if isinstance(rules_payload.get("review"), dict) else {}
        defaults_payload = profile_payload.get("defaults", {}) if isinstance(profile_payload.get("defaults"), dict) else {}

        if safety_payload.get("never_auto_adopt") is not True:
            failures.append("rules.yaml does not enforce never_auto_adopt=true")
        if review_payload.get("require_human_reason_for_adoption") is not True:
            failures.append("rules.yaml does not require a human adoption reason")
        if str(defaults_payload.get("adoption", "")) != "explicit_only":
            failures.append("profile.yaml adoption default is not explicit_only")
        if '--apply", "--reason' not in continue_text and "--apply\", \"--reason" not in continue_text:
            failures.append("do --continue does not clearly require --reason for apply")
        if "human reason is required" not in apply_text:
            failures.append("patch apply path does not clearly enforce human reason")
        if "require_validated=True" not in apply_text:
            failures.append("patch apply path does not clearly require a validated proposal")
        if "automatic adoption" not in commands_doc:
            warnings_list.append("docs/COMMANDS.md does not explicitly mention the automatic adoption boundary")

        if failures:
            return AuditCheckResult(
                check_id="explicit_adoption_boundary",
                title="Explicit adoption safety boundary",
                status="fail",
                severity="high",
                summary="explicit apply/adoption 안전 경계가 충분히 보장되지 않습니다.",
                details=failures,
                suggested_actions=[
                    "Keep adoption explicit-only, require a human reason, and rerun `cambrian alpha check`.",
                ],
            )
        if warnings_list:
            return AuditCheckResult(
                check_id="explicit_adoption_boundary",
                title="Explicit adoption safety boundary",
                status="warn",
                severity="warning",
                summary="핵심 안전 경계는 유지되지만 문서 설명이 조금 약합니다.",
                details=warnings_list,
                suggested_actions=["Clarify the explicit adoption rule in the project docs."],
            )
        return AuditCheckResult(
            check_id="explicit_adoption_boundary",
            title="Explicit adoption safety boundary",
            status="pass",
            severity="info",
            summary="explicit apply/adoption 경계가 구조적으로 유지됩니다.",
        )

    def _check_source_mutation_boundary(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """source mutation 경계 설명을 점검한다."""
        quickstart = _read_text(root / "docs" / "PROJECT_MODE_QUICKSTART.md", warnings).lower()
        first_run = _read_text(root / "docs" / "FIRST_RUN_DEMO.md", warnings).lower()
        commands_doc = _read_text(root / "docs" / "COMMANDS.md", warnings).lower()
        patch_text = _read_text(root / "engine" / "project_patch.py", warnings)
        apply_text = _read_text(root / "engine" / "project_patch_apply.py", warnings)

        failures: list[str] = []
        warnings_list: list[str] = []

        if "source" not in first_run or "--apply --reason" not in first_run:
            warnings_list.append("FIRST_RUN_DEMO does not clearly connect source mutation to explicit apply")
        if "source" not in quickstart or "explicit apply" not in quickstart:
            warnings_list.append("PROJECT_MODE_QUICKSTART does not clearly describe the mutation boundary")
        if "patch apply" not in commands_doc:
            warnings_list.append("COMMANDS.md does not clearly document patch apply as the real mutation step")
        if "Apply/adopt explicitly when ready" not in patch_text:
            warnings_list.append("patch proposal output no longer highlights explicit apply as the next step")
        if "post-apply tests failed" not in apply_text:
            failures.append("patch apply no longer shows post-apply test safety handling")

        if failures:
            return AuditCheckResult(
                check_id="source_mutation_boundary",
                title="Source mutation boundary",
                status="fail",
                severity="high",
                summary="source mutation 안전 경계가 흐려졌습니다.",
                details=failures + warnings_list,
                suggested_actions=["Keep source mutation limited to explicit patch apply and refresh the docs wording."],
            )
        if warnings_list:
            return AuditCheckResult(
                check_id="source_mutation_boundary",
                title="Source mutation boundary",
                status="warn",
                severity="warning",
                summary="source mutation 경계는 유지되지만 설명이 덜 선명합니다.",
                details=warnings_list,
                suggested_actions=["Clarify in docs that validation does not mutate source and apply is the only mutation step."],
            )
        return AuditCheckResult(
            check_id="source_mutation_boundary",
            title="Source mutation boundary",
            status="pass",
            severity="info",
            summary="source mutation은 explicit apply 단계로 명확히 분리되어 있습니다.",
        )

    def _check_golden_path_docs(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """golden path 문서 일관성을 점검한다."""
        first_run = _read_text(root / "docs" / "FIRST_RUN_DEMO.md", warnings)
        quickstart = _read_text(root / "docs" / "PROJECT_MODE_QUICKSTART.md", warnings)
        commands_doc = _read_text(root / "docs" / "COMMANDS.md", warnings)
        readme = _read_text(root / "README.md", warnings)
        failures: list[str] = []
        warnings_list: list[str] = []

        required_demo_signals = [
            'cambrian do "',
            "cambrian do --continue --use-suggestion 1 --execute",
            "cambrian do --continue --old-choice",
            "cambrian do --continue --apply --reason",
        ]
        for signal in required_demo_signals:
            if signal not in first_run:
                failures.append(f"FIRST_RUN_DEMO is missing: {signal}")

        if "cambrian summary" not in first_run:
            warnings_list.append("FIRST_RUN_DEMO does not mention `cambrian summary`.")
        if "cambrian do --continue" not in quickstart:
            warnings_list.append("PROJECT_MODE_QUICKSTART is not centered on `cambrian do --continue`.")
        if "cambrian patch intent" not in commands_doc or "cambrian patch apply" not in commands_doc:
            warnings_list.append("COMMANDS.md does not clearly retain the advanced/manual patch path.")
        if "cambrian do \"fix the login bug\"" not in readme and "cambrian do \"fix the login bug\"" not in quickstart:
            warnings_list.append("README/quickstart no longer shows the do-centered path early enough.")

        if failures:
            return AuditCheckResult(
                check_id="golden_path_docs",
                title="Golden path docs consistency",
                status="fail",
                severity="high",
                summary="first-run golden path 문서가 실제 do 중심 흐름을 충분히 설명하지 않습니다.",
                details=failures + warnings_list,
                suggested_actions=["Update the first-run docs to match the current do/do --continue flow."],
            )
        if warnings_list:
            return AuditCheckResult(
                check_id="golden_path_docs",
                title="Golden path docs consistency",
                status="warn",
                severity="warning",
                summary="핵심 흐름은 맞지만 문서 연결이 조금 엇갈립니다.",
                details=warnings_list,
                suggested_actions=["Tighten the links between README, quickstart, commands, and the first-run demo."],
            )
        return AuditCheckResult(
            check_id="golden_path_docs",
            title="Golden path docs consistency",
            status="pass",
            severity="info",
            summary="first-run docs와 CLI 흐름이 do 중심 경로로 정렬되어 있습니다.",
        )

    def _check_demo_asset_readiness(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """demo 자산과 생성기를 점검한다."""
        demo_text = _read_text(root / "engine" / "demo_project.py", warnings)
        first_run_exists = (root / "docs" / "FIRST_RUN_DEMO.md").exists()
        details: list[str] = []
        if "login-bug" not in demo_text:
            details.append("demo_project.py is missing the login-bug template")
        if "demo_answers.yaml" not in demo_text:
            details.append("demo_project.py does not mention demo_answers.yaml")
        if "README_DEMO.md" not in demo_text:
            details.append("demo_project.py does not mention README_DEMO.md")
        if "normalize_username" not in demo_text or "tests/test_auth.py" not in demo_text:
            details.append("demo_project.py does not describe the expected auth demo assets")
        if not first_run_exists:
            details.append("docs/FIRST_RUN_DEMO.md is missing")

        if details:
            return AuditCheckResult(
                check_id="demo_asset_readiness",
                title="Demo asset readiness",
                status="fail",
                severity="high",
                summary="첫 사용자 demo 자산이 충분히 준비되지 않았습니다.",
                details=details,
                suggested_actions=["Restore the login-bug demo generator and first-run docs before sharing the alpha."],
            )
        return AuditCheckResult(
            check_id="demo_asset_readiness",
            title="Demo asset readiness",
            status="pass",
            severity="info",
            summary="login-bug demo 자산과 생성 경로가 모두 보입니다.",
        )

    def _check_status_next_continuity(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """status와 next command 회복 경로를 점검한다."""
        status_text = _read_text(root / "engine" / "project_mode.py", warnings)
        do_text = _read_text(root / "engine" / "project_do.py", warnings)
        continue_text = _read_text(root / "engine" / "project_continue.py", warnings)
        clarify_text = _read_text(root / "engine" / "project_clarifier.py", warnings)
        issues: list[str] = []

        if "Summary:" not in status_text or "Recent journey:" not in status_text:
            issues.append("status summary no longer surfaces the compact project overview")
        if "Next:" not in status_text:
            issues.append("status renderer no longer presents a recovery next step")
        if "next_commands" not in do_text:
            issues.append("do session artifacts do not record next_commands")
        if "next_commands" not in continue_text:
            issues.append("do --continue no longer records next_commands")
        if "next_commands" not in clarify_text:
            issues.append("clarification artifacts do not record next_commands")

        if issues:
            return AuditCheckResult(
                check_id="status_next_continuity",
                title="Status and next-command continuity",
                status="warn",
                severity="warning",
                summary="회복 경로는 남아 있지만 next-command 연결이 조금 약합니다.",
                details=issues,
                suggested_actions=["Reinforce status and artifact next-command continuity."],
            )
        return AuditCheckResult(
            check_id="status_next_continuity",
            title="Status and next-command continuity",
            status="pass",
            severity="info",
            summary="status와 artifact가 다음 행동을 이어서 안내합니다.",
        )

    def _check_memory_visibility(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """memory 기능이 사용자에게 보이는지 점검한다."""
        cli_text = _read_text(root / "engine" / "cli.py", warnings)
        status_text = _read_text(root / "engine" / "project_mode.py", warnings)
        commands_doc = _read_text(root / "docs" / "COMMANDS.md", warnings)
        missing: list[str] = []
        for token in [
            'memory_subparsers.add_parser("rebuild"',
            'memory_subparsers.add_parser("list"',
            'memory_subparsers.add_parser("show"',
            'memory_subparsers.add_parser("review"',
            'memory_subparsers.add_parser("pin"',
            'memory_subparsers.add_parser("suppress"',
            'memory_subparsers.add_parser("hygiene"',
        ]:
            if token not in cli_text:
                missing.append(token.replace('memory_subparsers.add_parser("', "").replace('"', ""))
        if missing:
            return AuditCheckResult(
                check_id="memory_visibility",
                title="Memory visibility",
                status="warn",
                severity="warning",
                summary="project memory 기능이 사용자에게 충분히 드러나지 않습니다.",
                details=[f"missing memory command: {item}" for item in missing],
                suggested_actions=["Restore or document the missing memory commands."],
            )
        if "Project memory:" not in status_text or "cambrian memory" not in commands_doc:
            return AuditCheckResult(
                check_id="memory_visibility",
                title="Memory visibility",
                status="warn",
                severity="warning",
                summary="memory 기능은 있지만 status/docs 노출이 약합니다.",
                details=[
                    "status summary or command docs no longer mention project memory clearly",
                ],
                suggested_actions=["Expose memory visibility more clearly in status or commands docs."],
            )
        return AuditCheckResult(
            check_id="memory_visibility",
            title="Memory visibility",
            status="pass",
            severity="info",
            summary="project memory 기능과 가시성이 유지됩니다.",
        )

    def _check_local_only_principle(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """local-only 원칙을 점검한다."""
        commands_doc = _read_text(root / "docs" / "COMMANDS.md", warnings).lower()
        first_run = _read_text(root / "docs" / "FIRST_RUN_DEMO.md", warnings).lower()
        combined = "\n".join([commands_doc, first_run])
        if "cloud telemetry" in combined or "external analytics" in combined:
            return AuditCheckResult(
                check_id="local_only_principle",
                title="Local-only principle",
                status="fail",
                severity="high",
                summary="문서가 로컬 전용 원칙과 어긋나는 외부 telemetry를 암시합니다.",
                details=["Remove any cloud or telemetry claim from project mode docs."],
                suggested_actions=["Remove the external telemetry wording and rerun the audit."],
            )
        if "telemetry" not in combined and "local" not in combined:
            return AuditCheckResult(
                check_id="local_only_principle",
                title="Local-only principle",
                status="warn",
                severity="warning",
                summary="local-only 원칙이 문서에서 충분히 드러나지 않습니다.",
                details=["The docs do not explicitly say that summary/audit stays local."],
                suggested_actions=["Add a short local-only note to the commands or demo docs."],
            )
        return AuditCheckResult(
            check_id="local_only_principle",
            title="Local-only principle",
            status="pass",
            severity="info",
            summary="로컬 artifact 기반 원칙이 문서에 드러납니다.",
        )

    def _check_user_notes(self, root: Path) -> AuditCheckResult:
        """열린 high severity 사용자 노트를 점검한다."""
        notes = ProjectNotesStore().list(default_notes_dir(root))
        high_open = [
            note
            for note in notes
            if note.status == "open" and note.severity == "high"
        ]
        if high_open:
            return AuditCheckResult(
                check_id="user_notes_feedback",
                title="User notes feedback",
                status="warn",
                severity="warning",
                summary="열린 high severity 사용자 노트가 남아 있습니다.",
                details=[f"{note.note_id}: {note.text}" for note in high_open[:3]],
                suggested_actions=["Review open notes with `cambrian notes list` before sharing the alpha."],
            )
        return AuditCheckResult(
            check_id="user_notes_feedback",
            title="User notes feedback",
            status="pass",
            severity="info",
            summary="열린 high severity 사용자 노트가 없습니다.",
        )

    def _check_artifact_transparency(self, root: Path, warnings: list[str]) -> AuditCheckResult:
        """artifact truth model 문서를 점검한다."""
        artifacts_doc = _read_text(root / "docs" / "ARTIFACTS.md", warnings)
        if not artifacts_doc:
            return AuditCheckResult(
                check_id="artifact_transparency",
                title="Artifact transparency",
                status="warn",
                severity="warning",
                summary="artifact 설명 문서를 찾지 못했습니다.",
                details=["docs/ARTIFACTS.md is missing or unreadable"],
                suggested_actions=["Restore the artifact transparency doc."],
            )

        required_tokens = [
            "source of truth",
            "derived",
            ".cambrian/project.yaml",
            ".cambrian/requests/",
            ".cambrian/context/",
            ".cambrian/clarifications/",
            ".cambrian/patch_intents/",
            ".cambrian/patches/",
            ".cambrian/adoptions/",
        ]
        missing = [token for token in required_tokens if token not in artifacts_doc]
        if missing:
            return AuditCheckResult(
                check_id="artifact_transparency",
                title="Artifact transparency",
                status="warn",
                severity="warning",
                summary="artifact truth model 설명이 조금 부족합니다.",
                details=[f"missing artifact doc signal: {item}" for item in missing],
                suggested_actions=["Refresh docs/ARTIFACTS.md to cover source-of-truth and derived artifacts."],
            )
        return AuditCheckResult(
            check_id="artifact_transparency",
            title="Artifact transparency",
            status="pass",
            severity="info",
            summary="artifact source-of-truth와 derived 구분이 문서에 정리되어 있습니다.",
        )


def render_alpha_readiness(report: AlphaReadinessReport) -> str:
    """사람이 읽기 좋은 alpha readiness 출력."""
    lines = [
        "Cambrian Alpha Readiness",
        "==================================================",
        "",
        "Verdict:",
        f"  {report.verdict}",
        "",
        "Summary:",
        f"  pass : {report.summary.get('pass', 0)}",
        f"  warn : {report.summary.get('warn', 0)}",
        f"  fail : {report.summary.get('fail', 0)}",
    ]

    highlights: list[str] = []
    for check in report.checks:
        if check.status == "pass" and len(highlights) < 3:
            highlights.append(f"  ✓ {check.summary}")
        elif check.status in {"warn", "fail"} and len(highlights) < 6:
            marker = "!" if check.status == "warn" else "x"
            highlights.append(f"  {marker} {check.summary}")
    if highlights:
        lines.extend(["", "Highlights:", *highlights])

    needs_attention = [item for item in report.checks if item.status in {"warn", "fail"}]
    if needs_attention:
        lines.append("")
        lines.append("Needs attention:")
        for item in needs_attention[:4]:
            lines.append(f"  [{item.status}] {item.title}")
            for detail in item.details[:3]:
                lines.append(f"    - {detail}")

    if report.next_actions:
        lines.extend(["", "Next:"])
        for action in report.next_actions[:5]:
            lines.append(f"  - {action}")
    return "\n".join(lines)
