"""Bounded structured-output invocation.

One initial attempt plus at most MAX_STRUCTURED_OUTPUT_RETRIES retries.
Each retry appends the failing raw output and the validation error to the
transcript. Exhaustion yields an AgentFailure — never an exception, never a
third retry.
"""
from dataclasses import dataclass

from pydantic import BaseModel

from app.config import get_settings
from app.contracts.common import AgentFailure
from app.events.recorder import record
from app.events.types import EventType
from app.llm.provider import StructuredProvider


@dataclass
class StructuredOutcome:
    parsed: BaseModel | None
    retries: int
    failure: AgentFailure | None


async def invoke_structured(
    provider: StructuredProvider,
    schema: type[BaseModel],
    messages: list[tuple[str, str]],
    *,
    agent_name: str,
    session_id: str | None = None,
) -> StructuredOutcome:
    settings = get_settings()
    max_retries = settings.max_structured_output_retries
    transcript = list(messages)
    retries = 0

    for attempt in range(max_retries + 1):
        result = await provider.structured(schema, transcript)
        if result.parsed is not None:
            return StructuredOutcome(parsed=result.parsed, retries=retries, failure=None)

        if attempt < max_retries:
            retries += 1
            await record(
                EventType.STRUCTURED_OUTPUT_RETRY,
                session_id=session_id,
                actor=agent_name,
                payload={
                    "schema": schema.__name__,
                    "attempt": attempt + 1,
                    "error": (result.error or "")[:2000],
                },
            )
            if result.raw_text:
                transcript = transcript + [("assistant", result.raw_text[:6000])]
            transcript = transcript + [
                (
                    "user",
                    "Your previous response failed schema validation with this error:\n"
                    f"{(result.error or 'unknown validation error')[:2000]}\n"
                    f"Return a corrected response that satisfies the {schema.__name__} schema exactly.",
                )
            ]

    failure = AgentFailure(
        agent=agent_name,
        failure_type="structured_output",
        detail=f"{schema.__name__} failed validation after {max_retries} retries",
        recoverable=False,
    )
    await record(
        EventType.STRUCTURED_OUTPUT_FAILED,
        session_id=session_id,
        actor=agent_name,
        payload={"schema": schema.__name__, "retries": retries},
    )
    return StructuredOutcome(parsed=None, retries=retries, failure=failure)
