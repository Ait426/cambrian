from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_workforce_builder import build_workforce


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
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
                    "primary_goal": "인증과 예약 관련 버그를 안정적으로 검증한다.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["자동 patch apply 금지", "DB schema 변경 금지"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": "관련 Jest 테스트 통과",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = HarnessInterviewAnswerHandler().answer(root, path)
    assert result.status == "ready_for_plan"


def test_workforce_generate_uses_project_and_answers(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _answers(tmp_path)

    result = build_workforce(tmp_path)
    payload = result.to_dict()

    assert payload["ok"] is True
    assert result.status == "draft"
    assert result.workforce_id is not None
    assert result.workforce_id.startswith("workforce-")
    assert result.harness_id is not None
    assert result.harness_id.startswith("custom-")
    agent_ids = [agent["id"] for agent in result.agents]
    assert 3 <= len(agent_ids) <= 5
    assert "auth-flow-investigator" in agent_ids
    assert "jest-regression-guardian" in agent_ids
    assert "risk-reviewer" in agent_ids
    assert result.next_command == "cambrian harness install --confirm --json"
