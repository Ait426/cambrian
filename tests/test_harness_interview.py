from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_typescript_jest_auth_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(root / "backend" / "src" / "api" / "authRoutes.ts", 'export const route = "/api/auth/login";\n')
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def test_interview_start_creates_project_questions_without_selected_preset(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)

    session = HarnessInterviewBuilder().start(tmp_path)
    payload = session.to_dict()

    assert payload["ok"] is True
    assert payload["mode"] == "custom_harness_first"
    assert payload["project_profile"]["language"] == "typescript"
    assert payload["project_profile"]["test_framework"] == "jest"
    assert "selected_preset" not in payload
    assert 8 <= len(payload["questions"]) <= 10
    assert {question["id"] for question in payload["questions"]} >= {
        "primary_goal",
        "test_command",
        "change_policy",
    }
    assert any(option["id"] == "typescript-jest-auth-core" for option in payload["preset_options"])
    assert (tmp_path / ".cambrian" / "interview" / "questions.yaml").exists()


def test_interview_answer_reports_missing_required_fields(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)
    HarnessInterviewBuilder().start(tmp_path)
    answers_path = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "인증 버그를 잡는다.",
                    "change_policy": "proposal_only",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = HarnessInterviewAnswerHandler().answer(tmp_path, answers_path)

    assert result.status == "needs_more_info"
    assert "test_command" in result.missing
    assert result.to_dict()["ok"] is False


def test_interview_answer_accepts_complete_answers(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)
    HarnessInterviewBuilder().start(tmp_path)
    answers_path = tmp_path / ".cambrian" / "interview" / "answers.yaml"
    answers_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "인증/예약 버그를 안정적으로 수정한다.",
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

    result = HarnessInterviewAnswerHandler().answer(tmp_path, answers_path)

    assert result.status == "ready_for_plan"
    assert result.next_command == "cambrian harness plan --json"
