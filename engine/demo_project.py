"""첫 실행용 demo 프로젝트 생성기."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)


def _atomic_write_text(path: Path, content: str) -> None:
    """텍스트 파일을 안전하게 저장한다."""
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
        temp_path = Path(handle.name)
    temp_path.replace(path)


@dataclass
class DemoCreateResult:
    """demo 생성 결과."""

    status: str
    demo_name: str
    out_path: str
    created_files: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """직렬화용 dict."""
        return asdict(self)


class DemoProjectCreator:
    """첫 실행용 demo 프로젝트를 만든다."""

    SUPPORTED_DEMOS: tuple[str, ...] = ("login-bug",)

    def create(self, demo_name: str, out_path: Path, force: bool = False) -> DemoCreateResult:
        """demo 프로젝트를 생성한다."""
        normalized = str(demo_name or "").strip()
        target = Path(out_path).resolve()

        if normalized not in self.SUPPORTED_DEMOS:
            return DemoCreateResult(
                status="error",
                demo_name=normalized,
                out_path=str(target),
                created_files=[],
                errors=[
                    f"Unknown demo: {normalized}",
                    "Available demos:",
                    "  - login-bug",
                ],
            )

        if target.exists() and not target.is_dir():
            return DemoCreateResult(
                status="blocked",
                demo_name=normalized,
                out_path=str(target),
                created_files=[],
                errors=[f"출력 경로가 디렉터리가 아닙니다: {target}"],
            )

        existed_before = target.exists()
        if target.exists():
            existing_items = [item for item in target.iterdir()]
            if existing_items and not force:
                return DemoCreateResult(
                    status="blocked",
                    demo_name=normalized,
                    out_path=str(target),
                    created_files=[],
                    errors=["출력 경로가 비어 있지 않습니다. --force 없이 덮어쓸 수 없습니다."],
                    next_actions=[f"cambrian demo create {normalized} --out {target} --force"],
                )
        target.mkdir(parents=True, exist_ok=True)

        files = self._login_bug_files()
        created_files: list[str] = []
        for relative_path, content in files.items():
            file_path = target / relative_path
            _atomic_write_text(file_path, content)
            created_files.append(str(file_path))

        status = "overwritten" if existed_before and force else "created"
        return DemoCreateResult(
            status=status,
            demo_name=normalized,
            out_path=str(target),
            created_files=created_files,
            next_actions=[
                f"cd {target}",
                "cambrian init --wizard --answers-file demo_answers.yaml",
                'cambrian do "로그인 정규화 버그 수정해"',
            ],
        )

    @staticmethod
    def _login_bug_files() -> dict[str, str]:
        """login-bug demo 파일 묶음을 반환한다."""
        return {
            "pyproject.toml": (
                "[tool.pytest.ini_options]\n"
                "pythonpath = [\".\"]\n"
                "testpaths = [\"tests\"]\n"
                "addopts = \"-q\"\n"
            ),
            "src/__init__.py": "",
            "src/auth.py": (
                "def normalize_username(username: str) -> str:\n"
                "    return username\n"
            ),
            "tests/test_auth.py": (
                "from src.auth import normalize_username\n\n"
                "def test_normalize_username_lowercases_email() -> None:\n"
                "    assert normalize_username(\"USER@EXAMPLE.COM\") == \"user@example.com\"\n"
            ),
            "demo_answers.yaml": (
                "project_name: cambrian-login-demo\n"
                "project_type: python\n"
                "stack:\n"
                "  - python\n"
                "  - pytest\n"
                "\n"
                "test_command: \"pytest -q\"\n"
                "\n"
                "primary_use_cases:\n"
                "  - bug_fix\n"
                "  - regression_test\n"
                "  - review_candidate\n"
                "\n"
                "protected_paths:\n"
                "  - \".git\"\n"
                "  - \".cambrian\"\n"
                "  - \".venv\"\n"
                "  - \"venv\"\n"
                "  - \"__pycache__\"\n"
                "\n"
                "mode: balanced\n"
                "max_variants: 2\n"
                "auto_adoption: false\n"
                "\n"
                "notes:\n"
                "  - \"Demo project for Cambrian first-run walkthrough.\"\n"
            ),
            "README_DEMO.md": (
                "# Cambrian Login Bug Demo\n\n"
                "이 demo는 Cambrian의 첫 성공 경험을 빠르게 따라가기 위한 작은 샘플 프로젝트입니다.\n\n"
                "## Start here\n\n"
                "```bash\n"
                "cambrian init --wizard --answers-file demo_answers.yaml\n"
                "cambrian do \"로그인 정규화 버그 수정해\"\n"
                "cambrian do --continue --use-suggestion 1 --execute\n"
                "cambrian do --continue --old-choice old-1 --new-text \"return username.strip().lower()\" --validate\n"
                "cambrian do --continue --apply --reason \"normalize username before login\"\n"
                "cambrian status\n"
                "```\n\n"
                "Cambrian은 먼저 진단과 검증을 안전하게 진행하고, 실제 source 수정은 explicit apply 단계에서만 수행합니다.\n\n"
                "## Advanced / manual path\n\n"
                "직접 patch artifact를 제어하고 싶다면 아래 manual path를 사용할 수 있습니다.\n\n"
                "```bash\n"
                "cambrian patch intent .cambrian/brain/runs/<run-id>/report.json\n"
                "cambrian patch intent-fill .cambrian/patch_intents/<intent>.yaml --old-choice old-1 --new-text \"return username.strip().lower()\" --propose --execute\n"
                "cambrian patch apply .cambrian/patches/<proposal>.yaml --reason \"normalize username before login\"\n"
                "```\n\n"
                "`<run-id>`, `<intent>.yaml`, `<proposal>.yaml`은 실행 중 생성된 실제 경로로 바꿔 넣으면 됩니다.\n"
            ),
        }


def render_demo_create_summary(result: DemoCreateResult | dict) -> str:
    """demo create 결과를 사람이 읽기 좋게 렌더링한다."""
    payload = result.to_dict() if isinstance(result, DemoCreateResult) else dict(result)
    status = str(payload.get("status", "created"))
    if status in {"blocked", "error"}:
        lines = [
            "Cambrian demo project could not be created.",
            "",
            "Reason:",
        ]
        for item in payload.get("errors", []):
            lines.append(f"  - {item}")
        if payload.get("next_actions"):
            lines.extend(["", "Next:"])
            for item in payload.get("next_actions", []):
                lines.append(f"  {item}" if str(item).startswith("cambrian ") else f"  - {item}")
        return "\n".join(lines)

    lines = [
        "Cambrian demo project created.",
        "",
        "Demo:",
        f"  {payload.get('demo_name')}",
        "",
        "Created:",
    ]
    for item in payload.get("created_files", []):
        lines.append(f"  {item}")
    if payload.get("warnings"):
        lines.extend(["", "Warnings:"])
        for item in payload.get("warnings", []):
            lines.append(f"  - {item}")
    lines.extend(["", "Try:"])
    for item in payload.get("next_actions", []):
        lines.append(f"  {item}")
    return "\n".join(lines)
