"""LLM provider seam.

`StructuredProvider.structured()` is the single abstraction every LLM-powered
node uses. Only real providers exist here — they delegate schema enforcement to
the model's native structured-output API (no regex, no JSON-in-prose). There is
no in-app fake/scripted provider: a misconfigured LLM fails loudly at startup.
Tests inject their own double via `set_provider()`.
"""
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from app.config import get_settings


@dataclass
class StructuredAttempt:
    """One model invocation outcome."""

    parsed: BaseModel | None
    error: str | None
    raw_text: str  # assistant's raw output, used to build the retry transcript


class StructuredProvider(Protocol):
    async def structured(
        self, schema: type[BaseModel], messages: list[tuple[str, str]]
    ) -> StructuredAttempt: ...

    async def complete(self, messages: list[tuple[str, str]]) -> str: ...


class AnthropicProvider:
    """Real provider backed by langchain-anthropic."""

    def __init__(self, model: str | None = None) -> None:
        from langchain_anthropic import ChatAnthropic

        settings = get_settings()
        self._model = ChatAnthropic(
            model=model or settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            temperature=0,
        )

    async def structured(
        self, schema: type[BaseModel], messages: list[tuple[str, str]]
    ) -> StructuredAttempt:
        runnable = self._model.with_structured_output(schema, include_raw=True)
        try:
            out: dict[str, Any] = await runnable.ainvoke(messages)
        except Exception as exc:  # transport/provider error — recoverable via retry
            return StructuredAttempt(parsed=None, error=f"provider_error: {exc}", raw_text="")
        parsing_error = out.get("parsing_error")
        raw = out.get("raw")
        raw_text = getattr(raw, "content", "") if raw is not None else ""
        if isinstance(raw_text, list):
            raw_text = str(raw_text)
        if parsing_error is not None or out.get("parsed") is None:
            return StructuredAttempt(
                parsed=None,
                error=str(parsing_error) if parsing_error else "no parsed output returned",
                raw_text=str(raw_text),
            )
        return StructuredAttempt(parsed=out["parsed"], error=None, raw_text=str(raw_text))

    async def complete(self, messages: list[tuple[str, str]]) -> str:
        result = await self._model.ainvoke(messages)
        content = result.content
        return content if isinstance(content, str) else str(content)


class OpenAIProvider:
    """Real provider using OpenAI's native Pydantic structured-output API."""

    def __init__(self, model: str | None = None) -> None:
        from openai import AsyncOpenAI

        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when IT_LLM_PROVIDER=openai")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = model or settings.llm_model
        self._max_tokens = settings.llm_max_tokens

    async def structured(
        self, schema: type[BaseModel], messages: list[tuple[str, str]]
    ) -> StructuredAttempt:
        try:
            completion = await self._client.beta.chat.completions.parse(
                model=self._model,
                messages=[{"role": role, "content": content} for role, content in messages],
                response_format=schema,
                temperature=0,
                max_tokens=self._max_tokens,
            )
        except Exception as exc:  # transport/provider error — recoverable via retry
            return StructuredAttempt(parsed=None, error=f"provider_error: {exc}", raw_text="")
        message = completion.choices[0].message
        raw_text = message.content or ""
        if message.refusal or message.parsed is None:
            return StructuredAttempt(
                parsed=None,
                error=message.refusal or "no parsed output returned",
                raw_text=str(raw_text),
            )
        return StructuredAttempt(parsed=message.parsed, error=None, raw_text=str(raw_text))

    async def complete(self, messages: list[tuple[str, str]]) -> str:
        completion = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": role, "content": content} for role, content in messages],
            temperature=0,
            max_tokens=self._max_tokens,
        )
        return completion.choices[0].message.content or ""


_provider: StructuredProvider | None = None

# The only providers the running system will ever use. There is deliberately no
# offline / stub / scripted fallback: a misconfigured LLM must fail loudly, not
# silently degrade to a fake one. Tests inject their own double via set_provider.
_REAL_PROVIDERS: dict[str, type] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def get_provider() -> StructuredProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        factory = _REAL_PROVIDERS.get(settings.llm_provider)
        if factory is None:
            raise RuntimeError(
                f"IT_LLM_PROVIDER={settings.llm_provider!r} is not a supported provider. "
                f"Set it to one of: {', '.join(sorted(_REAL_PROVIDERS))}."
            )
        _provider = factory()  # constructor raises loudly if its API key is missing
    return _provider


def set_provider(provider: StructuredProvider | None) -> None:
    """Test hook: inject a double, or reset with None."""
    global _provider
    _provider = provider
