from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_harness_engineering import design_harness_candidate, dry_run_harness_candidate, review_harness_candidate
from engine.project_harness_plan import HarnessInstaller
from engine.project_skill_builder import build_skillset, fuse_generated_skills, search_generated_skills


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        self.calls.append((system, user, max_tokens))
        return "Prefer a trace skill, validation skill, safe patch skill, and regression risk skill."

    def provider_name(self) -> str:
        return "fake"


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
    assert trace["generation_contract"]["quality_status"] == "bootstrap_draft"
    assert trace["generation_contract"]["llm_enrichment_required"] is True
    assert trace["codebase_evidence"]["status"] == "grounded"
    assert trace["codebase_evidence"]["test_framework"] == "jest"
    assert "backend/src/middleware/authMiddleware.ts" in trace["codebase_evidence"]["paths"]
    assert "risk boundary checked" in trace["validation"]["required"]
    assert payload["llm_assist_policy"]["quality_status"] == "bootstrap_draft"
    assert payload["llm_generation_evidence"]["called"] is False
    assert "자동 patch apply 금지" in trace["forbidden"]


def test_skill_generation_uses_llm_provider_when_supplied(tmp_path: Path) -> None:
    _prepare(tmp_path)
    provider = _FakeProvider()

    result = build_skillset(tmp_path, provider=provider)
    payload = result.to_dict()

    assert provider.calls
    assert payload["llm_assist_policy"]["provider_used"] is True
    assert payload["llm_assist_policy"]["quality_status"] == "llm_assisted"
    assert payload["llm_generation_evidence"]["called"] is True
    assert payload["llm_generation_evidence"]["provider"] == "fake"
    assert "trace skill" in payload["llm_generation_evidence"]["response_excerpt"]


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
    assert skill["codebase_evidence"]["status"] == "grounded"
    assert skill["codebase_evidence"]["risk_boundaries"]["auto_apply"] is False
    agent = yaml.safe_load((tmp_path / ".cambrian" / "agents" / "auth-flow-investigator.yaml").read_text(encoding="utf-8"))
    assert agent["codebase_evidence"]["test_framework"] == "jest"
    assert "codebase evidence path cited" in agent["validation"]["required"]
    workforce = yaml.safe_load((tmp_path / ".cambrian" / "workforce.yaml").read_text(encoding="utf-8"))
    assert "trace-auth-token-flow" in workforce["skills"]["auth-flow-investigator"]
    assert "propose-safe-patch" in workforce["skills"]["risk-reviewer"]


def test_search_generated_skills_finds_project_auth_skill(tmp_path: Path) -> None:
    _prepare(tmp_path)
    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"
    assert HarnessInstaller().install(tmp_path, confirm=True).status == "installed"

    result = search_generated_skills(tmp_path, "auth token", limit=3)

    assert result["ok"] is True
    result_ids = [item["id"] for item in result["results"]]
    assert "trace-auth-token-flow" in result_ids
    assert result["results"][0]["source"] == "project_generated_skill"


def test_fuse_generated_skills_writes_project_skill_and_workforce_mapping(tmp_path: Path) -> None:
    _prepare(tmp_path)
    assert design_harness_candidate(tmp_path).status == "candidate"
    assert review_harness_candidate(tmp_path).status == "ready_for_dry_run"
    assert dry_run_harness_candidate(tmp_path, "로그인 문제 봐줘").status == "ready_for_install"
    assert HarnessInstaller().install(tmp_path, confirm=True).status == "installed"

    result = fuse_generated_skills(
        tmp_path,
        "trace-auth-token-flow",
        "inspect-jest-auth-test",
        "refresh token login failure를 추적하고 Jest 회귀 위험을 함께 검토한다.",
    )

    assert result["ok"] is True
    assert result["provider_used"] is False
    skill_path = tmp_path / result["skill_ref"]
    assert skill_path.exists()
    skill = yaml.safe_load(skill_path.read_text(encoding="utf-8"))
    assert skill["type"] == "generated_skill"
    assert skill["provenance"]["kind"] == "offline_generated_skill_fusion"
    assert skill["generation_contract"]["llm_enrichment_required"] is True
    assert skill["provenance"]["llm_enrichment_required"] is True
    assert skill["provenance"]["source_code_modified"] is False
    workforce = yaml.safe_load((tmp_path / ".cambrian" / "workforce.yaml").read_text(encoding="utf-8"))
    assert result["skill_id"] in workforce["skills"]["auth-flow-investigator"]
    assert result["skill_id"] in workforce["skills"]["jest-regression-guardian"]
