"""LLM provider seam.

`StructuredProvider.structured()` is the single abstraction every LLM-powered
node uses. The real path delegates schema enforcement to
`with_structured_output(include_raw=True)` (no regex, no JSON-in-prose); the
fake path yields scripted raw dicts validated with `schema.model_validate`,
which makes retry-1 / retry-2 / AgentFailure exactly testable offline.
"""
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

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


class FakeProvider:
    """Deterministic scripted provider for tests and offline demos.

    Enqueue raw dicts (or Pydantic instances) with `enqueue()`. Invalid dicts
    fail `schema.model_validate` exactly like an invalid real response, which
    drives the structured-output retry machinery.
    """

    def __init__(self) -> None:
        self._queue: list[Any] = []
        self._completions: list[str] = []
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    def enqueue(self, *items: Any) -> None:
        self._queue.extend(items)

    def enqueue_completion(self, *texts: str) -> None:
        self._completions.extend(texts)

    async def structured(
        self, schema: type[BaseModel], messages: list[tuple[str, str]]
    ) -> StructuredAttempt:
        self.calls.append((schema.__name__, messages))
        if not self._queue:
            return StructuredAttempt(
                parsed=None, error="FakeProvider queue empty", raw_text=""
            )
        item = self._queue.pop(0)
        if isinstance(item, BaseModel):
            if isinstance(item, schema):
                return StructuredAttempt(parsed=item, error=None, raw_text=item.model_dump_json())
            item = item.model_dump()
        try:
            parsed = schema.model_validate(item)
            return StructuredAttempt(parsed=parsed, error=None, raw_text=str(item))
        except ValidationError as exc:
            return StructuredAttempt(parsed=None, error=str(exc), raw_text=str(item))

    async def complete(self, messages: list[tuple[str, str]]) -> str:
        if self._completions:
            return self._completions.pop(0)
        return "Summary unavailable."


_provider: StructuredProvider | None = None


def get_provider() -> StructuredProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        if settings.llm_provider == "fake":
            _provider = FakeProvider()
        elif settings.llm_provider == "scripted":
            from app.llm.scripted import ScriptedProvider

            _provider = ScriptedProvider()
        elif settings.llm_provider == "openai":
            _provider = OpenAIProvider()
        elif settings.llm_provider == "anthropic":
            _provider = AnthropicProvider()
        else:
            raise ValueError(f"unsupported IT_LLM_PROVIDER: {settings.llm_provider}")
    return _provider


def set_provider(provider: StructuredProvider | None) -> None:
    """Test/demo hook."""
    global _provider
    _provider = provider
