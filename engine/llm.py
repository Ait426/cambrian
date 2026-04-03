"""Cambrian LLM 프로바이더 추상화."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """LLM 프로바이더 추상 인터페이스."""

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 8192,
    ) -> str:
        """LLM에 메시지를 보내고 텍스트 응답을 반환한다.

        Args:
            system: 시스템 프롬프트
            user: 유저 메시지
            max_tokens: 최대 생성 토큰 수

        Returns:
            LLM 응답 텍스트

        Raises:
            RuntimeError: API 호출 실패 시
        """

    @abstractmethod
    def provider_name(self) -> str:
        """프로바이더 이름을 반환한다."""


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API 프로바이더."""

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        """초기화.

        Args:
            model: 모델 ID. None이면 DEFAULT_MODEL 사용.
            api_key: API 키. None이면 ANTHROPIC_API_KEY 환경변수 사용.

        Raises:
            RuntimeError: anthropic 패키지 미설치 시
            RuntimeError: API 키 없음
        """
        try:
            from anthropic import Anthropic
        except ImportError:
            raise RuntimeError("anthropic package not installed")

        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. "
                "Run: export ANTHROPIC_API_KEY=sk-ant-... "
                "or use --provider openai/google"
            )

        self._model = model or self.DEFAULT_MODEL
        self._client = Anthropic(api_key=self._api_key)

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """Claude API를 호출한다.

        Args:
            system: 시스템 프롬프트
            user: 유저 메시지
            max_tokens: 최대 생성 토큰 수

        Returns:
            LLM 응답 텍스트
        """
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in response.content:
            text_value = getattr(block, "text", None)
            if isinstance(text_value, str):
                parts.append(text_value)
        return "".join(parts).strip()

    def provider_name(self) -> str:
        """프로바이더 이름을 반환한다."""
        return "anthropic"


class OpenAIProvider(LLMProvider):
    """OpenAI GPT API 프로바이더."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        """초기화.

        Args:
            model: 모델 ID. None이면 DEFAULT_MODEL 사용.
            api_key: API 키. None이면 OPENAI_API_KEY 환경변수 사용.

        Raises:
            RuntimeError: openai 패키지 미설치 시
            RuntimeError: API 키 없음
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package not installed")

        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. "
                "Run: export OPENAI_API_KEY=sk-... "
                "or use --provider anthropic/google"
            )

        self._model = model or self.DEFAULT_MODEL
        self._client = OpenAI(api_key=self._api_key)

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """OpenAI API를 호출한다.

        Args:
            system: 시스템 프롬프트
            user: 유저 메시지
            max_tokens: 최대 생성 토큰 수

        Returns:
            LLM 응답 텍스트
        """
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        return (content or "").strip()

    def provider_name(self) -> str:
        """프로바이더 이름을 반환한다."""
        return "openai"


class GoogleProvider(LLMProvider):
    """Google Gemini API 프로바이더."""

    DEFAULT_MODEL = "gemini-2.0-flash"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        """초기화.

        Args:
            model: 모델 ID. None이면 DEFAULT_MODEL 사용.
            api_key: API 키. None이면 GOOGLE_API_KEY 환경변수 사용.

        Raises:
            RuntimeError: google-generativeai 패키지 미설치 시
            RuntimeError: API 키 없음
        """
        try:
            import google.generativeai as genai
        except ImportError:
            raise RuntimeError("google-generativeai package not installed")

        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not set. "
                "Run: export GOOGLE_API_KEY=... "
                "or use --provider anthropic/openai"
            )

        self._model_name = model or self.DEFAULT_MODEL
        genai.configure(api_key=self._api_key)

    def complete(self, system: str, user: str, max_tokens: int = 8192) -> str:
        """Gemini API를 호출한다.

        Args:
            system: 시스템 프롬프트
            user: 유저 메시지
            max_tokens: 최대 생성 토큰 수

        Returns:
            LLM 응답 텍스트
        """
        import google.generativeai as genai

        model = genai.GenerativeModel(
            self._model_name,
            system_instruction=system,
            generation_config=genai.GenerationConfig(max_output_tokens=max_tokens),
        )
        response = model.generate_content(user)
        return (response.text or "").strip()

    def provider_name(self) -> str:
        """프로바이더 이름을 반환한다."""
        return "google"


_PROVIDERS: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
}


def create_provider(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """LLM 프로바이더 인스턴스를 생성한다.

    Args:
        provider: 프로바이더 이름. None이면 CAMBRIAN_LLM_PROVIDER 환경변수,
                  없으면 "anthropic".
        model: 모델 ID. None이면 각 프로바이더 기본값.
        api_key: API 키. None이면 각 프로바이더 환경변수.

    Returns:
        LLMProvider 인스턴스

    Raises:
        ValueError: 알 수 없는 프로바이더
        RuntimeError: 패키지 미설치 또는 API 키 없음
    """
    name = provider or os.environ.get("CAMBRIAN_LLM_PROVIDER", "anthropic")
    name = name.lower().strip()

    provider_class = _PROVIDERS.get(name)
    if provider_class is None:
        raise ValueError(
            f"Unknown provider: '{name}'. Available: {list(_PROVIDERS.keys())}"
        )

    return provider_class(model=model, api_key=api_key)
