"""Test-only LLM provider double.

This lives in the test suite, not in `app/`, on purpose: the shipped
application supports only real providers and fails loudly when one is not
configured. Tests inject this stub directly via `app.llm.provider.set_provider`.
"""
from typing import Any

from pydantic import BaseModel, ValidationError

from app.llm.provider import StructuredAttempt


class FakeProvider:
    """Deterministic, queue-driven provider for tests.

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
            return StructuredAttempt(parsed=None, error="FakeProvider queue empty", raw_text="")
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
