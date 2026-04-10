"""Cambrian LLM 프로바이더 추상화 테스트."""

from __future__ import annotations

import pytest

from engine.llm import (
    AnthropicProvider,
    LLMProvider,
    create_provider,
)


# === Mock 헬퍼 ===


class _FakeBlock:
    """Anthropic 응답 블록 대역."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    """Anthropic 응답 대역."""

    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    """Anthropic messages 대역."""

    def create(self, **kwargs: object) -> _FakeResponse:
        """가짜 응답을 반환한다."""
        return _FakeResponse("test response")


class _FakeAnthropic:
    """Anthropic 클라이언트 대역."""

    def __init__(self, api_key: str) -> None:
        self.messages = _FakeMessages()


# === LLMProvider ABC 테스트 ===


def test_llm_provider_is_abstract() -> None:
    """LLMProvider를 직접 인스턴스화하면 TypeError가 발생한다."""
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


# === 팩토리 테스트 ===


def test_create_provider_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본 프로바이더는 anthropic이다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr("engine.llm.AnthropicProvider.__init__", lambda self, **kw: None)

    provider = create_provider()
    assert isinstance(provider, AnthropicProvider)


def test_create_provider_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """CAMBRIAN_LLM_PROVIDER 환경변수로 프로바이더를 변경한다."""
    monkeypatch.setenv("CAMBRIAN_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr("engine.llm.AnthropicProvider.__init__", lambda self, **kw: None)

    provider = create_provider()
    assert isinstance(provider, AnthropicProvider)


def test_create_provider_explicit_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """명시적 모델을 전달하면 해당 모델이 설정된다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    # __init__를 mock하여 실제 anthropic import 방지
    def fake_init(self: object, model: str | None = None, api_key: str | None = None) -> None:
        self._model = model or "default"  # type: ignore[attr-defined]

    monkeypatch.setattr("engine.llm.AnthropicProvider.__init__", fake_init)

    provider = create_provider(provider="anthropic", model="claude-haiku-4-5-20251001")
    assert provider._model == "claude-haiku-4-5-20251001"  # type: ignore[attr-defined]


def test_create_provider_unknown() -> None:
    """알 수 없는 프로바이더는 ValueError를 발생시킨다."""
    with pytest.raises(ValueError, match="Unknown provider"):
        create_provider(provider="unknown_provider")


def test_create_provider_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """API 키가 없으면 RuntimeError를 발생시킨다."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CAMBRIAN_LLM_PROVIDER", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY|anthropic"):
        create_provider()


# === AnthropicProvider 테스트 ===


def test_anthropic_provider_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """AnthropicProvider.complete()가 텍스트를 반환한다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._model = "test-model"
    provider._client = _FakeAnthropic(api_key="fake")

    result = provider.complete("system prompt", "user message", max_tokens=100)
    assert result == "test response"


def test_anthropic_provider_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """AnthropicProvider.provider_name()은 'anthropic'이다."""
    provider = AnthropicProvider.__new__(AnthropicProvider)
    assert provider.provider_name() == "anthropic"


def test_anthropic_provider_default_model() -> None:
    """AnthropicProvider 기본 모델은 claude-sonnet-4-6이다."""
    assert AnthropicProvider.DEFAULT_MODEL == "claude-sonnet-4-6"


# === OpenAI/Google 미설치 테스트 ===


def test_openai_provider_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """openai 패키지 미설치 시 RuntimeError를 발생시킨다."""
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    import builtins
    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "openai":
            raise ImportError("mocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    from engine.llm import OpenAIProvider
    with pytest.raises(RuntimeError, match="openai package not installed"):
        OpenAIProvider(api_key="fake")


def test_google_provider_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """google-generativeai 패키지 미설치 시 RuntimeError를 발생시킨다."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key")

    import builtins
    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "google.generativeai" or name == "google":
            raise ImportError("mocked")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    from engine.llm import GoogleProvider
    with pytest.raises(RuntimeError, match="google-generativeai package not installed"):
        GoogleProvider(api_key="fake")


def test_llm_dependent_tests_use_mock():
    """L-4: LLM 의존 테스트 파일들이 실제 API를 호출하지 않는지 확인.

    각 테스트 파일에 provider= 또는 mock/patch 패턴이 있는지 검증.
    """
    import ast
    from pathlib import Path

    test_dir = Path(__file__).parent
    llm_test_files = [
        "test_evolution.py",
        "test_critic.py",
        "test_fuser.py",
        "test_generator.py",
    ]

    for filename in llm_test_files:
        filepath = test_dir / filename
        if not filepath.exists():
            continue

        source = filepath.read_text(encoding="utf-8")

        # mock/patch 또는 provider= 패턴이 있어야 함
        has_mock = (
            "mock" in source.lower()
            or "patch" in source.lower()
            or "provider=" in source
            or "FakeLLM" in source
            or "DummyProvider" in source
        )
        assert has_mock, (
            f"{filename}: LLM 의존 테스트에 mock/patch/provider 주입이 없음. "
            f"실제 API 호출 위험."
        )
