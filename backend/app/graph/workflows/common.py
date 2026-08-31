"""Shared deterministic helpers: turn ingestion and session finalization."""
from app.contracts.common import ChatTurn, RetrievedMemory
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState
from app.llm.provider import get_provider
from app.org import keys


# Keyword → category for classifying a free-text secondary intent so its
# ticket carries a real domain (ops filters and routing depend on it) instead
# of a blanket "other". First match wins; order matters least-ambiguous first.
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("security", ("phishing", "suspicious", "hacked", "compromis", "malware")),
    ("identity", ("locked", "lock out", "locked out", "password", "mfa", "sign in", "log in", "login", "access")),
    ("network", ("vpn", "wifi", "wi-fi", "internet", "network", "connection", "dns", "proxy")),
    ("endpoint", ("laptop", "device", "disk", "install", "software", "docker", "slow", "screen", "printer")),
)


def _classify_intent(text: str) -> str:
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


async def _track_secondary_intents(state: SupportState) -> str:
    """Open a tracked ticket for each not-yet-handled intent from a multi-intent
    message and return an employee-facing note listing them. Returns "" when
    there are none. This is the guarantee that a single message with several
    problems never silently loses the ones the conversation didn't work on."""
    if not state.pending_intents:
        return ""
    opened: list[str] = []
    for description in state.pending_intents:
        ticket = await repos.create_ticket(
            session_id=state.session_id,
            requester_employee_id=state.employee_id,
            category=_classify_intent(description),
            title=description[:200],
            description=f"Additional issue raised in the same request: {description}",
            status="open",
            current_team_key=keys.SUPPORT_IT,
            originating_agent="supervisor",
        )
        opened.append(f"{ticket.ticket_number} ({description})")
        await record(
            EventType.TICKET_CREATED,
            session_id=state.session_id,
            ticket_id=ticket.id,
            actor="supervisor",
            payload={"ticket_number": ticket.ticket_number, "status": "open", "secondary_intent": description},
        )
    listing = "; ".join(opened)
    return (
        "\n\nYou also mentioned other things in the same message, so I've logged them "
        f"separately so they don't get lost: {listing}. You can track these under "
        "“My requests.”"
    )


async def ingest_node(state: SupportState) -> dict:
    """Runs at the start of every fresh (non-resume) invoke: appends the
    incoming employee message, resets per-turn budgets, retrieves cross-session
    memories on the first turn, and compacts the conversation window."""
    from app.conversation.compaction import maybe_compact
    from app.memory.service import get_memory_service

    turns = list(state.recent_turns)
    if state.incoming_message:
        turns.append(ChatTurn(role="employee", content=state.incoming_message))

    memory_context: list[RetrievedMemory] = state.memory_context
    if state.turn_index == 0:
        memory_context = await get_memory_service().retrieve(
            state.employee_id, state.original_request, limit=5
        )
        if memory_context:
            await record(
                EventType.MEMORY_RETRIEVED,
                session_id=state.session_id,
                actor="memory",
                payload={"memories": [m.model_dump() for m in memory_context]},
            )

    summary, turns = await maybe_compact(state.conversation_summary, turns, get_provider())

    return {
        "incoming_message": None,
        "recent_turns": turns,
        "conversation_summary": summary,
        "memory_context": memory_context,
        "turn_index": state.turn_index + 1,
        # per-turn budget reset (new employee input = new evidence)
        "supervisor_cycle_count": 0,
        "handoff_count": 0,
        # a fresh message clears any stale terminal/interaction state
        "terminal_status": None,
        "final_response": None,
        "pending_question": None,
        "loop_guard_triggered": False,
    }


async def finalize_session(
    state: SupportState,
    *,
    terminal_status: str,
    final_response: str,
    session_status: str,
) -> dict:
    """Persist the closing assistant message, complete the session row, write
    cross-session memory when policy says so, and emit SESSION_COMPLETED."""
    from app.memory.policy import build_session_memory
    from app.memory.service import get_memory_service

    # Never drop the other issues from a multi-intent message: open a tracked
    # ticket for each and tell the employee, as part of this closing turn.
    final_response = final_response + await _track_secondary_intents(state)

    await repos.add_message(state.session_id, "assistant", final_response, source=state.channel)
    await repos.update_support_session(
        state.session_id,
        status=session_status,
        terminal_status=terminal_status,
        final_response=final_response,
        conversation_summary=state.conversation_summary,
    )

    closed_state = state.model_copy(
        update={"terminal_status": terminal_status, "final_response": final_response}
    )
    memory_content = build_session_memory(closed_state)
    if memory_content:
        memory_id = await get_memory_service().write(state.employee_id, memory_content)
        if memory_id:
            await record(
                EventType.MEMORY_WRITTEN,
                session_id=state.session_id,
                actor="memory",
                payload={"memory_id": memory_id, "content": memory_content},
            )

    await record(
        EventType.SESSION_COMPLETED,
        session_id=state.session_id,
        ticket_id=state.ticket_id,
        actor="system",
        payload={"terminal_status": terminal_status, "final_response": final_response},
    )

    return {
        "terminal_status": terminal_status,
        "final_response": final_response,
        "recent_turns": state.recent_turns + [ChatTurn(role="assistant", content=final_response)],
    }
