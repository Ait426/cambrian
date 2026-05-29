from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_custom_harness import build_custom_harness_plan
from engine.project_harness_interview import (
    HarnessInterviewAnswerHandler,
    HarnessInterviewBuilder,
    infer_interview_answers_from_project_docs,
)


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return "Domain: stage pipeline. Validation: npm test. Policy: proposal_only."

    def provider_name(self) -> str:
        return "fake-llm"


class _JsonProvider:
    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        return (
            '{"answers":{"primary_goal":"Maintain the documented release workflow.",'
            '"test_command":"python -m pytest","change_policy":"proposal_only",'
            '"important_paths":["README.md"]}}'
        )

    def provider_name(self) -> str:
        return "json-llm"


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


def test_interview_infer_uses_project_docs_as_first_answer_source(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)
    _write(
        tmp_path / "README.md",
        "# AVE Pipeline Automation\n\nRun npm test before release. Cambrian must stay proposal_only.",
    )
    _write(
        tmp_path / "CLAUDE.md",
        "Focus on stage schema validation, DDMQ debugging, and safe evidence-based changes.",
    )

    result = infer_interview_answers_from_project_docs(tmp_path)

    assert result.status == "ready_for_plan"
    assert result.source_mode == "project_docs_bootstrap"
    assert result.llm_generation_evidence["called"] is False
    assert result.answers["test_command"] == "npm test"
    assert result.answers["change_policy"] == "proposal_only"
    assert result.document_context["document_count"] >= 2
    assert (tmp_path / ".cambrian" / "interview" / "answers.yaml").exists()
    assert build_custom_harness_plan(tmp_path)["goal"]


def test_interview_infer_records_llm_provider_evidence(tmp_path: Path) -> None:
    _make_typescript_jest_auth_project(tmp_path)
    _write(tmp_path / "README.md", "# AI Agent Builder\n\nRun npm test. Do not auto-apply changes.")
    provider = _FakeProvider()

    result = infer_interview_answers_from_project_docs(tmp_path, provider=provider)

    assert provider.calls
    assert result.status == "ready_for_plan"
    assert result.source_mode == "project_docs_llm_assisted"
    assert result.llm_assist_policy["provider_used"] is True
    assert result.llm_generation_evidence["called"] is True
    assert result.llm_generation_evidence["provider"] == "fake-llm"
    assert "Domain:" in result.answers["llm_project_summary"]


def test_interview_infer_can_fill_missing_fields_from_structured_llm_reply(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Release Workflow\n\nValidation command is described by the AI worker.")

    result = infer_interview_answers_from_project_docs(tmp_path, provider=_JsonProvider())

    assert result.status == "ready_for_plan"
    assert result.answers["test_command"] == "python -m pytest"
    assert result.llm_generation_evidence["provider"] == "json-llm"


def test_interview_infer_asks_only_when_docs_and_scan_are_insufficient(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "# Tiny Project\n\nNo validation command is documented yet.")

    result = infer_interview_answers_from_project_docs(tmp_path)

    assert result.status == "needs_more_info"
    assert "test_command" in result.missing
    assert result.next_command == "cambrian harness interview answer --answers .cambrian/interview/answers.yaml --json"


def test_interview_infer_records_authority_and_excludes_generated_docs(tmp_path: Path) -> None:
    _write(
        tmp_path / "README.md",
        "# Durable Project\n\nRun python -m pytest before release. Cambrian must stay proposal_only.",
    )
    _write(
        tmp_path / ".pytest-basetemp-noise" / "README.md",
        "# Generated Noise\n\nRun npm test and auto apply every patch.",
    )
    _write(
        tmp_path / "demo" / "README.md",
        "# Demo Noise\n\nRun npm test and treat hotel booking as the product domain.",
    )
    _write(
        tmp_path / "skill_pool" / "README.md",
        "# Skill Noise\n\nRun npm test for this sample skill.",
    )

    result = infer_interview_answers_from_project_docs(tmp_path)
    context = result.document_context

    assert result.status == "ready_for_plan"
    assert result.answers["test_command"] == "python -m pytest"
    assert context["docs_found"] == ["README.md"]
    assert "document_authority" in context
    assert ".pytest*/" in context["document_authority"]["excluded_generated_or_sample_docs"]
    assert "demo/" in context["document_authority"]["excluded_generated_or_sample_docs"]
    assert "skill_pool/" in context["document_authority"]["excluded_generated_or_sample_docs"]
    assert context["noise_filter"]["excluded_dir_prefixes"] == [".pytest", ".launch_runs"]
