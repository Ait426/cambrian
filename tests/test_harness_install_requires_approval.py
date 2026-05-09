from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_plan import HarnessInstaller
from engine.project_harness_engineering import design_harness_candidate, dry_run_harness_candidate, review_harness_candidate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _answers(root: Path) -> None:
    HarnessInterviewBuilder().start(root)
    path = root / ".cambrian" / "interview" / "answers.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "인증 문제를 검증한다.",
                    "test_command": "npm test",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["자동 patch apply 금지"],
                    "validation_standard": "관련 테스트 통과",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = HarnessInterviewAnswerHandler().answer(root, path)
    assert result.status == "ready_for_plan"


def test_harness_install_without_confirm_is_blocked(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _answers(tmp_path)

    result = HarnessInstaller().install(tmp_path, confirm=False)
    payload = result.to_dict()

    assert result.status == "confirmation_required"
    assert payload["ok"] is False
    assert payload["error"] == "confirmation_required"
    assert payload["next_command"] == "cambrian harness install --confirm --json"
    assert not (tmp_path / ".cambrian" / "harness.yaml").exists()


def test_harness_install_with_confirm_writes_expected_files(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _answers(tmp_path)
    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"

    result = HarnessInstaller().install(tmp_path, confirm=True)

    assert result.status == "installed"
    assert ".cambrian/harness.yaml" in result.installed_files
    assert ".cambrian/agents.yaml" in result.installed_files
    assert ".cambrian/validation.yaml" in result.installed_files
