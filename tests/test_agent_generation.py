from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_engineering import design_harness_candidate, dry_run_harness_candidate, review_harness_candidate
from engine.project_harness_plan import HarnessInstaller


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _prepare(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "api" / "authRoutes.ts", "export const route = '/api/auth/login';\n")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")
    HarnessInterviewBuilder().start(root)
    answers = root / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "인증 API 흐름을 안정적으로 점검한다.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["자동 patch apply 금지", "DB schema 변경 금지"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": ["Jest 테스트 통과", "API 계약 회귀 없음"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert HarnessInterviewAnswerHandler().answer(root, answers).status == "ready_for_plan"


def test_install_generates_workforce_agents_and_skills(tmp_path: Path) -> None:
    _prepare(tmp_path)
    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"

    result = HarnessInstaller().install(tmp_path, confirm=True)

    assert result.status == "installed"
    assert result.workforce_id is not None
    assert result.workforce_id.startswith("workforce-")
    assert result.no_agent_dispatched is True
    assert "trace-auth-token-flow" in result.skills
    workforce = yaml.safe_load((tmp_path / ".cambrian" / "workforce.yaml").read_text(encoding="utf-8"))
    assert workforce["dispatch_policy"]["mode"] == "on_demand"
    assert workforce["dispatch_policy"]["auto_dispatch_on_install"] is False
    assert "trace-auth-token-flow" in workforce["skills"]["auth-flow-investigator"]
    assert "propose-safe-patch" in workforce["skills"]["risk-reviewer"]
    agent_dir = tmp_path / ".cambrian" / "agents"
    assert (agent_dir / "auth-flow-investigator.yaml").exists()
    assert (agent_dir / "jest-regression-guardian.yaml").exists()
    skills_dir = tmp_path / ".cambrian" / "skills"
    assert (skills_dir / "trace-auth-token-flow.yaml").exists()
    assert (skills_dir / "inspect-jest-auth-test.yaml").exists()
    auth_agent = yaml.safe_load((agent_dir / "auth-flow-investigator.yaml").read_text(encoding="utf-8"))
    assert auth_agent["type"] == "generated_agent"
    assert auth_agent["agent_kind"] == "ai_agent"
    assert auth_agent["requires_llm_call"] is True
    assert auth_agent["runtime_contract"]["llm_invocation"]["required"] is True
    assert auth_agent["runtime_contract"]["llm_invocation"]["evidence_key"] == "llm_invocation_evidence"
    assert auth_agent["harness_id"].startswith("custom-")
    assert "자동 patch apply 금지" in auth_agent["forbidden"]
    trace_skill = yaml.safe_load((skills_dir / "trace-auth-token-flow.yaml").read_text(encoding="utf-8"))
    assert trace_skill["type"] == "generated_skill"
    assert trace_skill["assigned_agents"] == ["auth-flow-investigator"]
    assert not (tmp_path / ".cambrian" / "packs" / "jobs").exists()
