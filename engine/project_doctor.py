"""Cambrian 설치 및 프로젝트 환경 상태를 점검하는 doctor 도구."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)
SCHEMA_VERSION = "1.0.0"


def _now() -> str:
    """현재 UTC 시각을 ISO 문자열로 반환한다."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DoctorCheck:
    """개별 doctor 점검 결과."""

    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


@dataclass
class DoctorReport:
    """doctor 전체 결과."""

    schema_version: str
    generated_at: str
    workspace: str
    checks: list[DoctorCheck]
    summary: dict
    next_actions: list[str]

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        payload = asdict(self)
        payload["checks"] = [check.to_dict() for check in self.checks]
        return payload


class ProjectDoctor:
    """Cambrian 설치와 프로젝트 mode 준비 상태를 점검한다."""

    def run(self, workspace: Path) -> DoctorReport:
        """workspace 기준으로 doctor 결과를 만든다."""
        root = Path(workspace).resolve()
        checks = [
            self._check_python_version(),
            self._check_cli_import(),
            self._check_required_dependencies(),
            self._check_pytest_availability(),
            self._check_workspace_writable(root),
            self._check_project_init_state(root),
            self._check_demo_availability(),
            self._check_package_metadata(root),
        ]
        summary = {
            "ok": sum(1 for check in checks if check.status == "ok"),
            "warn": sum(1 for check in checks if check.status == "warn"),
            "fail": sum(1 for check in checks if check.status == "fail"),
        }
        next_actions = self._build_next_actions(root, checks)
        return DoctorReport(
            schema_version=SCHEMA_VERSION,
            generated_at=_now(),
            workspace=str(root),
            checks=checks,
            summary=summary,
            next_actions=next_actions,
        )

    def _check_python_version(self) -> DoctorCheck:
        """Python 버전을 점검한다."""
        current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info < (3, 11):
            return DoctorCheck(
                name="Python",
                status="fail",
                summary=f"Python {current}",
                details=["Cambrian은 Python 3.11 이상이 필요합니다."],
            )
        return DoctorCheck(
            name="Python",
            status="ok",
            summary=f"Python {current}",
        )

    def _check_cli_import(self) -> DoctorCheck:
        """CLI import와 main 엔트리포인트를 점검한다."""
        try:
            module = importlib.import_module("engine.cli")
        except Exception as exc:
            logger.warning("doctor CLI import failed: %s", exc)
            return DoctorCheck(
                name="CLI import",
                status="fail",
                summary="Cambrian CLI import failed",
                details=[str(exc)],
            )
        if not hasattr(module, "main"):
            return DoctorCheck(
                name="CLI import",
                status="fail",
                summary="engine.cli.main entrypoint is missing",
                details=["설치된 console script가 실행되지 않을 수 있습니다."],
            )
        return DoctorCheck(
            name="CLI import",
            status="ok",
            summary="Cambrian CLI entrypoint is available",
        )

    def _check_required_dependencies(self) -> DoctorCheck:
        """필수 Python 의존성을 점검한다."""
        missing: list[str] = []
        for module_name in ("yaml", "jsonschema"):
            if importlib.util.find_spec(module_name) is None:
                missing.append(module_name)
        if missing:
            return DoctorCheck(
                name="Required dependencies",
                status="fail",
                summary="필수 의존성이 빠져 있습니다.",
                details=[f"missing import: {item}" for item in missing],
            )
        return DoctorCheck(
            name="Required dependencies",
            status="ok",
            summary="PyYAML / jsonschema available",
        )

    def _check_pytest_availability(self) -> DoctorCheck:
        """pytest 사용 가능 여부를 점검한다."""
        if importlib.util.find_spec("pytest") is None:
            return DoctorCheck(
                name="pytest",
                status="warn",
                summary="pytest is not installed",
                details=["demo와 validation 흐름에서는 pytest가 있으면 더 좋습니다."],
            )
        return DoctorCheck(
            name="pytest",
            status="ok",
            summary="pytest available",
        )

    def _check_workspace_writable(self, workspace: Path) -> DoctorCheck:
        """workspace 쓰기 가능 여부를 점검한다."""
        if not workspace.exists():
            return DoctorCheck(
                name="Workspace",
                status="fail",
                summary="Workspace does not exist",
                details=[str(workspace)],
            )
        if not workspace.is_dir():
            return DoctorCheck(
                name="Workspace",
                status="fail",
                summary="Workspace is not a directory",
                details=[str(workspace)],
            )
        try:
            with tempfile.NamedTemporaryFile("w", dir=workspace, delete=True, encoding="utf-8") as handle:
                handle.write("doctor\n")
                handle.flush()
        except OSError as exc:
            logger.warning("doctor workspace writable check failed: %s", exc)
            return DoctorCheck(
                name="Workspace",
                status="fail",
                summary="Workspace is not writable",
                details=[str(exc)],
            )
        return DoctorCheck(
            name="Workspace",
            status="ok",
            summary="Workspace is writable",
        )

    def _check_project_init_state(self, workspace: Path) -> DoctorCheck:
        """프로젝트 초기화 상태를 점검한다."""
        project_yaml = workspace / ".cambrian" / "project.yaml"
        if not project_yaml.exists():
            return DoctorCheck(
                name="Project mode",
                status="warn",
                summary="Project is not initialized yet",
                details=["Run `cambrian init --wizard` before using project mode."],
            )
        return DoctorCheck(
            name="Project mode",
            status="ok",
            summary="Project mode is initialized",
            details=[str(project_yaml)],
        )

    def _check_demo_availability(self) -> DoctorCheck:
        """demo create 가능 여부를 점검한다."""
        try:
            from engine.demo_project import DemoProjectCreator
        except Exception as exc:
            logger.warning("doctor demo import failed: %s", exc)
            return DoctorCheck(
                name="Demo assets",
                status="fail",
                summary="Demo generator import failed",
                details=[str(exc)],
            )
        if "login-bug" not in getattr(DemoProjectCreator, "SUPPORTED_DEMOS", ()):
            return DoctorCheck(
                name="Demo assets",
                status="fail",
                summary="login-bug demo is missing",
                details=["`cambrian demo create login-bug` 가 동작하지 않을 수 있습니다."],
            )
        try:
            with tempfile.TemporaryDirectory(prefix="cambrian-doctor-demo-") as tmp_dir:
                target = Path(tmp_dir) / "demo"
                result = DemoProjectCreator().create("login-bug", target, force=False)
        except Exception as exc:
            logger.warning("doctor demo create smoke failed: %s", exc)
            return DoctorCheck(
                name="Demo assets",
                status="fail",
                summary="Demo smoke failed",
                details=[str(exc)],
            )
        if result.status != "created":
            return DoctorCheck(
                name="Demo assets",
                status="fail",
                summary="Demo generator did not create the expected project",
                details=[f"status={result.status}", *list(result.errors)],
            )
        return DoctorCheck(
            name="Demo assets",
            status="ok",
            summary="Demo assets available",
        )

    def _check_package_metadata(self, workspace: Path) -> DoctorCheck:
        """현재 실행 중인 Cambrian 패키지/소스의 metadata를 점검한다."""
        details: list[str] = []
        version = ""

        try:
            version = importlib.metadata.version("cambrian")
        except importlib.metadata.PackageNotFoundError:
            details.append("설치된 Cambrian 배포 metadata는 찾지 못했습니다.")
        except Exception as exc:
            logger.warning("설치된 Cambrian 배포 metadata 확인 실패: %s", exc)
            details.append(f"설치된 Cambrian 배포 metadata 확인 실패: {exc}")

        try:
            cli_module = importlib.import_module("engine.cli")
        except Exception as exc:
            return DoctorCheck(
                name="Package metadata",
                status="fail",
                summary="Cambrian CLI module could not be imported",
                details=[str(exc)],
            )

        if not callable(getattr(cli_module, "main", None)):
            return DoctorCheck(
                name="Package metadata",
                status="fail",
                summary="Cambrian CLI entrypoint is missing",
                details=["`engine.cli.main` 함수를 찾지 못했습니다."],
            )

        if version:
            return DoctorCheck(
                name="Package metadata",
                status="ok",
                summary=f"Cambrian package metadata is available (version {version})",
                details=details,
            )

        repo_pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        if repo_pyproject.exists():
            try:
                payload = tomllib.loads(repo_pyproject.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                logger.warning("Cambrian 소스 트리 pyproject 읽기 실패: %s", exc)
                details.append(f"Cambrian 소스 트리 pyproject 읽기 실패: {exc}")
            else:
                project_payload = payload.get("project", {}) if isinstance(payload.get("project"), dict) else {}
                scripts_payload = (
                    project_payload.get("scripts", {})
                    if isinstance(project_payload.get("scripts"), dict)
                    else {}
                )
                source_version = str(project_payload.get("version", "") or "").strip()
                script_target = str(scripts_payload.get("cambrian", "") or "").strip()
                if source_version and script_target == "engine.cli:main":
                    return DoctorCheck(
                        name="Package metadata",
                        status="ok",
                        summary=f"Cambrian source metadata is available (version {source_version})",
                        details=details,
                    )
                details.append("Cambrian 소스 트리 metadata가 완전히 확인되지는 않았습니다.")

        details.append(f"현재 workspace는 일반 프로젝트로 취급했습니다: {workspace}")
        return DoctorCheck(
            name="Package metadata",
            status="warn",
            summary="Cambrian version could not be confirmed, but CLI metadata checks passed",
            details=details,
        )

    def _build_next_actions(self, workspace: Path, checks: list[DoctorCheck]) -> list[str]:
        """doctor 결과에 맞는 다음 행동을 만든다."""
        next_actions: list[str] = []
        by_name = {check.name: check for check in checks}
        python_check = by_name.get("Python")
        dep_check = by_name.get("Required dependencies")
        pytest_check = by_name.get("pytest")
        init_check = by_name.get("Project mode")
        demo_check = by_name.get("Demo assets")

        if (python_check and python_check.status == "fail") or (dep_check and dep_check.status == "fail"):
            next_actions.append("pip install -e .[dev]")
        elif pytest_check and pytest_check.status == "warn":
            next_actions.append("pip install -e .[dev]")

        if init_check and init_check.status == "warn":
            next_actions.append("cambrian init --wizard")
        if demo_check and demo_check.status == "ok":
            next_actions.append("cambrian demo create login-bug --out ./demo")

        if workspace.joinpath(".cambrian", "project.yaml").exists():
            next_actions.append("cambrian status")

        ordered: list[str] = []
        seen: set[str] = set()
        for item in next_actions:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered or ["cambrian demo create login-bug --out ./demo"]


def render_doctor_report(report: DoctorReport) -> str:
    """사람이 읽기 쉬운 doctor 출력."""
    icon_map = {"ok": "✓", "warn": "!", "fail": "x"}
    lines = [
        "Cambrian Doctor",
        "==================================================",
        "",
        "Checks:",
    ]
    for check in report.checks:
        icon = icon_map.get(check.status, "-")
        lines.append(f"  {icon} {check.name:<17}: {check.summary}")
        for detail in check.details[:2]:
            lines.append(f"      - {detail}")
    lines.extend(["", "Next:"])
    for action in report.next_actions:
        lines.append(f"  - {action}")
    return "\n".join(lines)
