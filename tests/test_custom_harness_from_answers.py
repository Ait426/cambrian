from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_agent_dispatch import AgentDispatcher
from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_engineering import design_harness_candidate, dry_run_harness_candidate, review_harness_candidate
from engine.project_harness_plan import HarnessInstaller, HarnessPlanner


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_project(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", '{"compilerOptions":{"target":"ES2020"}}')
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")


def _complete_answers(root: Path) -> None:
    HarnessInterviewBuilder().start(root)
    path = root / ".cambrian" / "interview" / "answers.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "ONMI-STAY의 인증/예약 관련 버그를 안정적으로 수정하고 검증한다.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["자동 patch apply 금지", "DB schema 변경 금지"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": ["관련 테스트 통과", "기존 인증 흐름 회귀 없음"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = HarnessInterviewAnswerHandler().answer(root, path)
    assert result.status == "ready_for_plan"


def test_custom_harness_plan_install_and_dispatch_from_answers(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _complete_answers(tmp_path)

    plan = HarnessPlanner().build(tmp_path)
    assert plan.plan_type == "custom"
    assert plan.status == "draft"
    assert plan.harness_id is not None
    assert plan.harness_id.startswith("custom-")
    assert plan.validation["policy"] == "proposal_only"

    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"
    install = HarnessInstaller().install(tmp_path, confirm=True)
    assert install.status == "installed"

    harness = yaml.safe_load((tmp_path / ".cambrian" / "harness.yaml").read_text(encoding="utf-8"))
    assert harness["type"] == "custom"
    assert harness["policy"]["auto_apply"] is False
    validation = yaml.safe_load((tmp_path / ".cambrian" / "validation.yaml").read_text(encoding="utf-8"))
    assert validation["validation"]["test_commands"] == ["npm test", "npm run build"]

    dispatch = AgentDispatcher().dispatch(tmp_path, "로그인 에러 수정해")
    payload = dispatch.to_dict()
    assert payload["ok"] is True
    assert payload["harness_id"] == plan.harness_id
    assert payload["change_policy"] == "proposal_only"
    assert payload["job_id"].startswith("job-custom-")
