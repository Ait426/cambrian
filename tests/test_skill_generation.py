from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_engineering import design_harness_candidate, dry_run_harness_candidate, review_harness_candidate
from engine.project_harness_plan import HarnessInstaller
from engine.project_skill_builder import build_skillset


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _prepare(root: Path) -> None:
    _write(root / "package.json", '{"scripts":{"test":"jest","build":"tsc"},"devDependencies":{"jest":"latest"}}')
    _write(root / "tsconfig.json", "{}")
    _write(root / "backend" / "src" / "middleware" / "authMiddleware.ts", "export function auth() {}\n")
    _write(root / "backend" / "tests" / "auth.test.ts", "test('auth', () => {})\n")
    HarnessInterviewBuilder().start(root)
    answers = root / ".cambrian" / "interview" / "answers.yaml"
    answers.write_text(
        yaml.safe_dump(
            {
                "session_id": "harness-interview-test",
                "answers": {
                    "primary_goal": "인증 세션 만료 문제를 안정적으로 점검한다.",
                    "test_command": "npm test",
                    "build_command": "npm run build",
                    "change_policy": "proposal_only",
                    "forbidden_scope": ["자동 patch apply 금지", "DB schema 변경 금지"],
                    "important_paths": ["backend/src/middleware/authMiddleware.ts", "backend/tests/auth.test.ts"],
                    "validation_standard": "Jest 테스트 통과",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert HarnessInterviewAnswerHandler().answer(root, answers).status == "ready_for_plan"


def test_skill_generate_builds_generated_skillset(tmp_path: Path) -> None:
    _prepare(tmp_path)

    result = build_skillset(tmp_path)
    payload = result.to_dict()

    assert payload["ok"] is True
    assert result.skillset_id is not None
    assert result.skillset_id.startswith("skillset-")
    skill_ids = [skill["id"] for skill in result.skills]
    assert "trace-auth-token-flow" in skill_ids
    assert "inspect-jest-auth-test" in skill_ids
    assert "propose-safe-patch" in skill_ids
    assert "review-regression-risk" in skill_ids
    trace = next(skill for skill in result.skills if skill["id"] == "trace-auth-token-flow")
    assert trace["type"] == "generated_skill"
    assert trace["assigned_agents"] == ["auth-flow-investigator"]
    assert "자동 patch apply 금지" in trace["forbidden"]


def test_install_writes_skill_files_and_workforce_mapping(tmp_path: Path) -> None:
    _prepare(tmp_path)
    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"

    install = HarnessInstaller().install(tmp_path, confirm=True)

    assert install.status == "installed"
    assert "trace-auth-token-flow" in install.skills
    skills_dir = tmp_path / ".cambrian" / "skills"
    assert (skills_dir / "trace-auth-token-flow.yaml").exists()
    assert (skills_dir / "inspect-jest-auth-test.yaml").exists()
    skill = yaml.safe_load((skills_dir / "trace-auth-token-flow.yaml").read_text(encoding="utf-8"))
    assert skill["type"] == "generated_skill"
    workforce = yaml.safe_load((tmp_path / ".cambrian" / "workforce.yaml").read_text(encoding="utf-8"))
    assert "trace-auth-token-flow" in workforce["skills"]["auth-flow-investigator"]
    assert "propose-safe-patch" in workforce["skills"]["risk-reviewer"]
