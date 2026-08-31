"""Employee-owned resolution signal before a normal support session closes."""

from langgraph.types import Command, interrupt

from app.contracts.common import ChatTurn, Transition
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState
from app.graph.workflows.resolution import compose_resolution_candidate


async def resolution_verify_prepare(state: SupportState) -> dict:
    candidate = state.resolution_candidate or compose_resolution_candidate(state)
    concise_candidate = candidate.strip()[:900]
    prompt = (
        f"Here’s the current result: {concise_candidate}\n\n"
        "Before I close this request, is the original issue working normally now? "
        "Say yes if it is resolved; otherwise tell me what is still happening."
    )
    await repos.add_message(state.session_id, "assistant", prompt, source=state.channel)
    await record(
        EventType.INFO_REQUESTED,
        session_id=state.session_id,
        actor="resolution_verification",
        payload={"question": prompt, "purpose": "resolution_confirmation"},
    )
    await repos.update_support_session(state.session_id, status="waiting_employee")
    return {
        "resolution_candidate": concise_candidate,
        "awaiting_resolution_confirmation": True,
        "resolution_confirmation_answer": None,
        "resolution_confirmed": None,
        "pending_question": prompt,
        "recent_turns": state.recent_turns + [ChatTurn(role="assistant", content=prompt)],
    }


async def resolution_verify_wait(state: SupportState) -> Command:
    answer = str(interrupt({"type": "question", "question": state.pending_question})).strip()
    await record(
        EventType.EMPLOYEE_REPLIED,
        session_id=state.session_id,
        actor=state.employee_id,
        payload={"answer": answer, "purpose": "resolution_confirmation"},
    )
    await repos.update_support_session(state.session_id, status="active")
    base = {
        "awaiting_resolution_confirmation": True,
        "resolution_confirmation_answer": answer,
        "resolution_confirmed": None,
        "pending_question": None,
        "recent_turns": state.recent_turns + [ChatTurn(role="employee", content=answer)],
        "turn_index": state.turn_index + 1,
        "supervisor_cycle_count": 0,
        "handoff_count": 0,
    }
    return Command(
        goto="supervisor",
        update={
            **base,
            "final_response": None,
            "transition_history": [
                Transition(
                    from_node="resolution_verify_wait",
                    to_node="supervisor",
                    reason="supervisor must interpret the employee's resolution signal",
                )
            ],
        },
    )
