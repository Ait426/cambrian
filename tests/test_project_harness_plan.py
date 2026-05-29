from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_engineering import design_harness_candidate, dry_run_harness_candidate, review_harness_candidate
from engine.project_harness_plan import HarnessInstaller, HarnessPlanner
from engine.project_mode import ProjectStatusReader


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_python_auth_project(root: Path) -> None:
    _write(root / "pyproject.toml", '[project]\nname = "sample-auth"\nversion = "0.1.0"\n')
    _write(root / "pytest.ini", "[pytest]\ntestpaths = tests\n")
    _write(root / "src" / "auth.py", "def login(user):\n    return user\n")
    _write(root / "tests" / "test_auth.py", "def test_login():\n    assert True\n")


def _make_typescript_jest_auth_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(root / "backend" / "src" / "api" / "authRoutes.ts", 'export const route = "/api/auth/login";\n')
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _make_pytest_ledger_project(root: Path) -> None:
    _write(root / "requirements.txt", "pytest\n")
    _write(root / "app" / "generator.py", "def build_ledger():\n    return 'ok'\n")
    _write(root / "app" / "main.py", "from app.generator import build_ledger\n")
    _write(root / "tests" / "test_generator.py", "def test_build_ledger():\n    assert True\n")


def _write_answers(root: Path, test_command: str = "npm test") -> Path:
    HarnessInterviewBuilder().start(root)
    answers = {
        "session_id": "harness-interview-test",
        "answers": {
            "primary_goal": "인증/예약 관련 버그를 안정적으로 수정하고 검증한다.",
            "test_command": test_command,
            "build_command": "npm run build",
            "change_policy": "proposal_only",
            "forbidden_scope": ["자동 patch apply 금지", "DB schema 변경 금지"],
            "validation_standard": "관련 테스트 통과",
            "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
        },
    }
    path = root / ".cambrian" / "interview" / "answers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(answers, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = HarnessInterviewAnswerHandler().answer(root, path)
    assert result.status == "ready_for_plan"
    return path


def _write_ledger_answers(root: Path) -> Path:
    HarnessInterviewBuilder().start(root)
    answers = {
        "session_id": "harness-interview-test",
        "answers": {
            "primary_goal": "장부 생성기 입력, 엑셀 생성, 다운로드 흐름을 안전하게 검토한다.",
            "test_command": "python -m pytest tests/test_generator.py",
            "change_policy": "proposal_only",
            "forbidden_scope": ["생성된 outputs 직접 수정 금지", "자동 patch apply 금지"],
            "validation_standard": "pytest 검증 통과",
            "important_paths": ["app/main.py", "app/generator.py", "tests/test_generator.py"],
        },
    }
    path = root / ".cambrian" / "interview" / "answers.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(answers, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = HarnessInterviewAnswerHandler().answer(root, path)
    assert result.status == "ready_for_plan"
    return path


def test_harness_plan_requires_interview_before_preset_install(tmp_path: Path) -> None:
    _make_python_auth_project(tmp_path)

    plan = HarnessPlanner().build(tmp_path)

    assert plan.status == "needs_interview"
    assert plan.plan_type == "interview_required"
    assert plan.selected_harness is None
    assert "cambrian harness interview start" in plan.next_commands


def test_harness_plan_builds_custom_plan_from_answers(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)
    _write_answers(tmp_path)

    plan = HarnessPlanner().build(tmp_path)

    assert plan.status == "draft"
    assert plan.plan_type == "custom"
    assert plan.harness_id is not None
    assert plan.harness_id.startswith("custom-")
    assert plan.seed_preset is None
    assert plan.validation["test_commands"] == ["npm test", "npm run build"]
    assert "cambrian harness install --confirm --json" in plan.next_commands


def test_harness_id_never_uses_tests_as_product_identity(tmp_path: Path) -> None:
    _make_pytest_ledger_project(tmp_path)
    _write_ledger_answers(tmp_path)

    plan = HarnessPlanner().build(tmp_path)

    assert plan.status == "draft"
    assert plan.harness_id is not None
    assert plan.harness_id.endswith("-work")
    assert not plan.harness_id.endswith("-tests")


def test_harness_install_requires_confirm(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)
    _write_answers(tmp_path)

    result = HarnessInstaller().install(tmp_path)

    assert result.status == "confirmation_required"
    assert result.to_dict()["error"] == "confirmation_required"
    assert not (tmp_path / ".cambrian" / "harness.yaml").exists()


def test_harness_install_writes_custom_harness_files_after_confirm(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)
    _write_answers(tmp_path)
    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"

    result = HarnessInstaller().install(tmp_path, confirm=True)

    assert result.status == "installed"
    assert result.plan_type == "custom"
    assert result.harness_id is not None
    assert (tmp_path / ".cambrian" / "profile.yaml").exists()
    assert (tmp_path / ".cambrian" / "harness.yaml").exists()
    assert (tmp_path / ".cambrian" / "agents.yaml").exists()
    assert (tmp_path / ".cambrian" / "validation.yaml").exists()
    assert (tmp_path / ".cambrian" / "plan.yaml").exists()
    assert (tmp_path / ".cambrian" / "project.yaml").exists()
    assert (tmp_path / ".cambrian" / "skills.yaml").exists()

    status = ProjectStatusReader().read(tmp_path)
    assert status.initialized is True
    assert status.harness["fitted"] is True
    assert status.harness["type"] == "custom_harness"
    assert status.harness["harness_id"] == result.harness_id
    assert status.harness["active_agents"]
    assert "quality_gate" in status.harness["enforced_gates"]
