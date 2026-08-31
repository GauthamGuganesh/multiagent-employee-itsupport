"""Conversation compaction (DESIGN §9): token estimation, threshold trigger,
and the summary + retained-window reshape. Persistence is untouched by design;
these tests exercise the pure in-graph window logic with a FakeProvider."""
from app.config import get_settings
from app.contracts.common import ChatTurn
from app.conversation.compaction import (
    compact,
    estimate_tokens,
    maybe_compact,
    needs_compaction,
)
from tests.fakes import FakeProvider


def turn(content: str, role: str = "employee") -> ChatTurn:
    return ChatTurn(role=role, content=content)


# --- estimate_tokens ----------------------------------------------------------

def test_estimate_tokens_is_len_div_4():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("x" * 41) == 10


# --- needs_compaction ---------------------------------------------------------

def test_needs_compaction_above_threshold(monkeypatch):
    monkeypatch.setattr(get_settings(), "conversation_compaction_token_threshold", 10)
    # summary 5 tokens + turn 6 tokens = 11 > 10
    assert needs_compaction("x" * 20, [turn("y" * 24)]) is True


def test_needs_compaction_at_threshold_is_false(monkeypatch):
    monkeypatch.setattr(get_settings(), "conversation_compaction_token_threshold", 10)
    # exactly 10 tokens: strict > comparison, no compaction
    assert needs_compaction("x" * 40, []) is False


def test_needs_compaction_sums_summary_and_turns(monkeypatch):
    monkeypatch.setattr(get_settings(), "conversation_compaction_token_threshold", 10)
    # 4 + 4 + 4 = 12 > 10 even though each part is below the threshold
    assert needs_compaction("x" * 16, [turn("y" * 16), turn("z" * 16)]) is True


# --- compact ------------------------------------------------------------------

async def test_compact_retains_last_n_and_summarizes_older(monkeypatch):
    monkeypatch.setattr(get_settings(), "recent_messages_to_retain", 2)
    provider = FakeProvider()
    provider.enqueue_completion("  Employee reported VPN drops; rebooted router.  ")
    turns = [turn(f"message number {i}") for i in range(5)]

    new_summary, retained = await compact("old summary", turns, provider)

    # provider.complete was consumed and its output became the (stripped) summary
    assert new_summary == "Employee reported VPN drops; rebooted router."
    assert retained == turns[-2:]
    assert [t.content for t in retained] == ["message number 3", "message number 4"]


async def test_compact_noop_when_window_fits(monkeypatch):
    monkeypatch.setattr(get_settings(), "recent_messages_to_retain", 4)
    provider = FakeProvider()  # nothing enqueued: complete() would return a stub
    turns = [turn("a" * 100), turn("b" * 100)]

    summary, retained = await compact("keep me", turns, provider)

    # Inputs returned unchanged — no provider call folded anything.
    assert summary == "keep me"
    assert retained is turns


async def test_compact_noop_at_exact_retention_boundary(monkeypatch):
    monkeypatch.setattr(get_settings(), "recent_messages_to_retain", 3)
    provider = FakeProvider()
    turns = [turn("one"), turn("two"), turn("three")]
    summary, retained = await compact("", turns, provider)
    assert summary == ""
    assert retained is turns


# --- maybe_compact ------------------------------------------------------------

async def test_maybe_compact_below_threshold_is_identity(monkeypatch):
    monkeypatch.setattr(get_settings(), "conversation_compaction_token_threshold", 10_000)
    monkeypatch.setattr(get_settings(), "recent_messages_to_retain", 1)
    provider = FakeProvider()
    provider.enqueue_completion("should never be used")
    turns = [turn("short"), turn("turns")]

    summary, retained = await maybe_compact("summary", turns, provider)

    assert summary == "summary"
    assert retained is turns


async def test_maybe_compact_compacts_over_threshold(monkeypatch):
    monkeypatch.setattr(get_settings(), "conversation_compaction_token_threshold", 5)
    monkeypatch.setattr(get_settings(), "recent_messages_to_retain", 1)
    provider = FakeProvider()
    provider.enqueue_completion("folded summary")
    turns = [turn("x" * 40), turn("the final turn")]

    summary, retained = await maybe_compact("", turns, provider)

    assert summary == "folded summary"
    assert [t.content for t in retained] == ["the final turn"]
