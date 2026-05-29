from __future__ import annotations

from pathlib import Path

import yaml

from engine.project_harness_interview import HarnessInterviewAnswerHandler, HarnessInterviewBuilder
from engine.project_workforce_builder import _attach_agent_runtime_contract, build_workforce


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        self.calls.append((system, user, max_tokens))
        return "Prefer one domain specialist, one verification guardian, and one risk reviewer."

    def provider_name(self) -> str:
        return "fake"


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
    by_id = {agent["id"]: agent for agent in result.agents}
    assert by_id["auth-flow-investigator"]["agent_kind"] == "ai_agent"
    assert by_id["auth-flow-investigator"]["requires_llm_call"] is True
    assert by_id["auth-flow-investigator"]["runtime_contract"]["llm_invocation"]["required"] is True
    assert by_id["jest-regression-guardian"]["agent_kind"] == "ai_agent"
    assert by_id["risk-reviewer"]["runtime_contract"]["llm_invocation"]["evidence_key"] == "llm_invocation_evidence"
    assert result.next_command == "cambrian harness install --confirm --json"


def test_workforce_generation_uses_llm_provider_when_supplied(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _answers(tmp_path)
    provider = _FakeProvider()

    result = build_workforce(tmp_path, provider=provider)
    payload = result.to_dict()

    assert provider.calls
    assert payload["llm_assist_policy"]["provider_used"] is True
    assert payload["llm_assist_policy"]["quality_status"] == "llm_assisted"
    assert payload["llm_generation_evidence"]["called"] is True
    assert payload["llm_generation_evidence"]["provider"] == "fake"
    assert "domain specialist" in payload["llm_generation_evidence"]["response_excerpt"]


def test_workforce_generation_without_provider_is_bootstrap_draft(tmp_path: Path) -> None:
    _make_project(tmp_path)
    _answers(tmp_path)

    result = build_workforce(tmp_path)
    payload = result.to_dict()

    assert payload["llm_assist_policy"]["provider_used"] is False
    assert payload["llm_assist_policy"]["quality_status"] == "bootstrap_draft"
    assert payload["llm_assist_policy"]["llm_enrichment_required"] is True
    assert payload["llm_generation_evidence"]["called"] is False


def test_deterministic_generated_worker_can_be_general_agent() -> None:
    agent = _attach_agent_runtime_contract({"id": "command-runner", "role": "Run approved validation commands"})

    assert agent["agent_kind"] == "general_agent"
    assert agent["responsibility_class"] == "tool_execution"
    assert agent["requires_reasoning"] is False
    assert agent["requires_llm_call"] is False
    assert agent["runtime_contract"]["llm_invocation"]["required"] is False
    assert agent["runtime_contract"]["template_output_allowed"] is True
