"""Conversation compaction: running summary + recent-turns window (DESIGN §9).

Context sent to LLMs = running summary + last `recent_messages_to_retain`
turns + structured state. Compaction triggers when the estimated token count
of (summary + turns) exceeds `conversation_compaction_token_threshold`; older
turns are folded into the running summary via one `provider.complete` call
with a fixed instruction template.

Pure with respect to persistence: this module NEVER touches Postgres. The
`messages` table remains the complete, uncompacted transcript; compaction only
reshapes the in-graph context window (`recent_turns` is last-write-wins).
"""
from app.config import get_settings
from app.contracts.common import ChatTurn
from app.llm.provider import StructuredProvider

_SUMMARIZE_INSTRUCTION = (
    "Update the running support-conversation summary with the older turns "
    "below. Preserve facts, symptoms, steps tried, and decisions. Be concise "
    "and factual; do not invent details. Reply with ONLY the updated summary."
)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate: ~4 characters per token (len // 4)."""
    return len(text) // 4


def _context_tokens(summary: str, turns: list[ChatTurn]) -> int:
    return estimate_tokens(summary) + sum(estimate_tokens(t.content) for t in turns)


def needs_compaction(summary: str, turns: list[ChatTurn]) -> bool:
    settings = get_settings()
    return _context_tokens(summary, turns) > settings.conversation_compaction_token_threshold


def _render_turns(turns: list[ChatTurn]) -> str:
    return "\n".join(f"{t.role}: {t.content}" for t in turns)


async def compact(
    summary: str, turns: list[ChatTurn], provider: StructuredProvider
) -> tuple[str, list[ChatTurn]]:
    """Fold turns older than the retained window into the running summary.

    Keeps the last `recent_messages_to_retain` turns verbatim; summarizes the
    older turns (plus the existing summary) into a new running summary. If
    nothing falls outside the retained window, returns the inputs unchanged.
    """
    settings = get_settings()
    retain = settings.recent_messages_to_retain
    if len(turns) <= retain:
        return summary, turns
    older, retained = turns[:-retain], turns[-retain:]
    user_content = (
        f"Existing summary:\n{summary or '(none)'}\n\n"
        f"Older turns to fold in:\n{_render_turns(older)}"
    )
    new_summary = await provider.complete(
        [("system", _SUMMARIZE_INSTRUCTION), ("user", user_content)]
    )
    return new_summary.strip(), retained


async def maybe_compact(
    summary: str, turns: list[ChatTurn], provider: StructuredProvider
) -> tuple[str, list[ChatTurn]]:
    """Compact only when the estimated context size exceeds the threshold."""
    if not needs_compaction(summary, turns):
        return summary, turns
    return await compact(summary, turns, provider)
