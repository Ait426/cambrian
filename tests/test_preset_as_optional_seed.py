from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_plan import HarnessPlanner


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_typescript_project(root: Path) -> None:
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
    HarnessInterviewAnswerHandler().answer(root, path)


def test_preset_options_are_reference_only_in_interview(tmp_path: Path) -> None:
    _make_typescript_project(tmp_path)

    session = HarnessInterviewBuilder().start(tmp_path)
    payload = session.to_dict()

    assert payload["mode"] == "custom_harness_first"
    assert "selected_preset" not in payload
    assert any(option["id"] == "auth-bug-core" and option["compatible"] is False for option in payload["preset_options"])
    assert any(option["id"] == "typescript-jest-auth-core" and option["compatible"] is True for option in payload["preset_options"])


def test_seed_preset_does_not_turn_plan_into_preset_install(tmp_path: Path) -> None:
    _make_typescript_project(tmp_path)
    _answers(tmp_path)

    plan = HarnessPlanner().build(tmp_path, seed_preset="typescript-jest-auth-core")

    assert plan.plan_type == "custom"
    assert plan.status == "draft"
    assert plan.seed_preset == "typescript-jest-auth-core"
    assert plan.harness_id != "typescript-jest-auth-core"
    assert plan.selected_harness == plan.harness_id
