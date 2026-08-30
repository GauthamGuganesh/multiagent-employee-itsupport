"""Shared deterministic helpers: turn ingestion and session finalization."""
from app.contracts.common import ChatTurn, RetrievedMemory
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState
from app.llm.provider import get_provider


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
