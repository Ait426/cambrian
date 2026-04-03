"""Cambrian Judge 단위 테스트."""

from __future__ import annotations

import pytest

from engine.judge import SkillJudge
from engine.llm import LLMProvider
from engine.models import JudgeVerdict


# === Mock LLM Provider ===


class _MockProvider(LLMProvider):
    """테스트용 LLM 프로바이더 대역."""

    def __init__(self, response_text: str = "", should_raise: bool = False) -> None:
        self._response_text = response_text
        self._should_raise = should_raise

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """가짜 응답을 반환한다."""
        if self._should_raise:
            raise Exception("API error")
        return self._response_text

    def provider_name(self) -> str:
        """프로바이더 이름을 반환한다."""
        return "mock"


# === None 입력 테스트 (LLM 호출 안 함) ===


def test_judge_both_null_outputs() -> None:
    """양쪽 출력이 모두 없으면 즉시 tie를 반환한다."""
    verdict = SkillJudge(provider=_MockProvider()).judge(None, None, "test", [])

    assert isinstance(verdict, JudgeVerdict)
    assert verdict.original_score == 0.0
    assert verdict.variant_score == 0.0
    assert verdict.winner == "tie"


def test_judge_original_null() -> None:
    """원본 출력이 없으면 variant 승리로 처리한다."""
    verdict = SkillJudge(provider=_MockProvider()).judge(
        None, {"html": "<p>ok</p>"}, "test", []
    )

    assert verdict.original_score == 0.0
    assert verdict.variant_score == 5.0
    assert verdict.winner == "variant"


def test_judge_variant_null() -> None:
    """변이 출력이 없으면 original 승리로 처리한다."""
    verdict = SkillJudge(provider=_MockProvider()).judge(
        {"html": "<p>ok</p>"}, None, "test", []
    )

    assert verdict.original_score == 5.0
    assert verdict.variant_score == 0.0
    assert verdict.winner == "original"


# === 정상 응답 테스트 ===


def test_judge_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 JSON 응답을 original/variant 점수로 파싱한다."""
    provider = _MockProvider(
        '{"score_a": 6, "score_b": 9, "reasoning": "B is better", "winner": "b"}'
    )
    monkeypatch.setattr("engine.judge.random.choice", lambda _: False)

    verdict = SkillJudge(provider=provider).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.original_score == 6.0
    assert verdict.variant_score == 9.0
    assert verdict.winner == "variant"


def test_judge_valid_response_swapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """스왑된 A/B 응답을 원래 original/variant로 역매핑한다."""
    provider = _MockProvider(
        '{"score_a": 6, "score_b": 9, "reasoning": "B is better", "winner": "b"}'
    )
    monkeypatch.setattr("engine.judge.random.choice", lambda _: True)

    verdict = SkillJudge(provider=provider).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.original_score == 9.0
    assert verdict.variant_score == 6.0
    assert verdict.winner == "original"


def test_judge_code_block_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """코드블록 JSON 응답도 정상 파싱한다."""
    provider = _MockProvider(
        '```json\n{"score_a": 7, "score_b": 8, "reasoning": "ok", "winner": "b"}\n```'
    )
    monkeypatch.setattr("engine.judge.random.choice", lambda _: False)

    verdict = SkillJudge(provider=provider).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.variant_score == 8.0
    assert verdict.winner == "variant"


def test_judge_parse_failure_returns_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON 파싱 실패 시 tie fallback을 반환한다."""
    provider = _MockProvider("I cannot evaluate these outputs.")
    monkeypatch.setattr("engine.judge.random.choice", lambda _: False)

    verdict = SkillJudge(provider=provider).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.original_score == 5.0
    assert verdict.variant_score == 5.0
    assert verdict.winner == "tie"


def test_judge_score_clamping(monkeypatch: pytest.MonkeyPatch) -> None:
    """점수는 0.0~10.0 범위로 clamp된다."""
    provider = _MockProvider(
        '{"score_a": -3, "score_b": 15, "reasoning": "extreme", "winner": "b"}'
    )
    monkeypatch.setattr("engine.judge.random.choice", lambda _: False)

    verdict = SkillJudge(provider=provider).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.original_score == 0.0
    assert verdict.variant_score == 10.0


def test_judge_llm_exception_returns_tie() -> None:
    """LLM 호출 예외 시 tie fallback을 반환한다."""
    provider = _MockProvider(should_raise=True)

    verdict = SkillJudge(provider=provider).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.original_score == 5.0
    assert verdict.variant_score == 5.0
    assert verdict.winner == "tie"


def test_judge_winner_tie_when_equal(monkeypatch: pytest.MonkeyPatch) -> None:
    """동점 응답이면 winner를 tie로 유지한다."""
    provider = _MockProvider(
        '{"score_a": 7, "score_b": 7, "reasoning": "equal", "winner": "tie"}'
    )
    monkeypatch.setattr("engine.judge.random.choice", lambda _: False)

    verdict = SkillJudge(provider=provider).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.winner == "tie"


# === Provider 미전달 + API 키 없음 테스트 ===


def test_judge_no_provider_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider 없이 API 키도 없으면 fallback tie를 반환한다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CAMBRIAN_LLM_PROVIDER", raising=False)

    # provider=None이면 create_provider() 호출 → RuntimeError → catch → tie
    verdict = SkillJudge(provider=None).judge(
        {"html": "<p>orig</p>"}, {"html": "<p>var</p>"}, "test", []
    )

    assert verdict.original_score == 5.0
    assert verdict.winner == "tie"
