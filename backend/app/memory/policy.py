"""Memory write policy: what a completed session is allowed to remember.

Writes happen at session finalization only (design §8) — never per turn and
never for routine acknowledgements. The produced memory is a short durable
fact injected into future sessions as context, not authority: privileges,
tickets, and security state are always re-verified via Neo4j/Postgres.
"""
import re

from app.graph.state import SupportState

# Exact normalized phrases that are never worth remembering.
SKIP_PATTERNS: frozenset[str] = frozenset(
    {
        "ok", "okay", "k", "kk", "thanks", "thank you", "thanks a lot", "thx", "ty",
        "yes", "no", "yep", "nope", "yeah", "nah", "sure", "fine", "alright",
        "got it", "sounds good", "great", "cool", "nice", "perfect", "done",
        "hi", "hello", "hey", "bye", "goodbye", "cheers", "no thanks",
    }
)

# Vocabulary of acknowledgement words: a message made ONLY of these is trivial
# regardless of phrasing ("ok thanks!", "yes please").
_ACK_WORDS: frozenset[str] = frozenset(
    {
        "ok", "okay", "k", "thanks", "thank", "you", "thx", "ty", "yes", "no",
        "yep", "nope", "yeah", "nah", "sure", "fine", "alright", "great",
        "cool", "nice", "perfect", "done", "good", "sounds", "got", "it",
        "please", "hi", "hello", "hey", "bye", "goodbye", "cheers", "a", "lot",
    }
)

_WORD_RE = re.compile(r"[a-z0-9']+")


def is_memorable(text: str) -> bool:
    """True when the text carries durable content — not a bare acknowledgement."""
    normalized = " ".join(text.lower().split()).strip(".,!?;: ")
    if len(normalized) < 4:
        return False
    if normalized in SKIP_PATTERNS:
        return False
    words = _WORD_RE.findall(normalized)
    if not words or all(word in _ACK_WORDS for word in words):
        return False
    return True


def _latest_resolution_summary(state: SupportState) -> str | None:
    for result in reversed(state.specialist_results):
        if result.resolution_summary:
            return result.resolution_summary
    return None


def build_session_memory(state: SupportState) -> str | None:
    """Distill a finished session into one durable, USEFUL fact, or None.

    Only a genuine resolution is remembered — a concrete "this issue was fixed
    this way" fact that can help next time. Escalations, pending approvals,
    failures, and trivial requests write nothing: a note that a past session was
    escalated (especially to security) is not a durable fact about the employee,
    and retrieving it later would wrongly bias a fresh, unrelated request.
    """
    if not is_memorable(state.original_request):
        return None
    if state.terminal_status == "resolved":
        resolution = _latest_resolution_summary(state)
        if not resolution:
            return None
        category = state.category or "other"
        return f"On a past {category} issue ({state.original_request}) the fix was: {resolution}"
    return None
