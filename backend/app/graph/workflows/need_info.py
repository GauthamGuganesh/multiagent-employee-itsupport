"""Need-more-information workflow.

Split into prepare (side effects, checkpointed) and wait (interrupt only) so
resume replay never duplicates rows or events.
"""
from langgraph.types import interrupt

from app.contracts.common import ChatTurn
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState

DEFAULT_QUESTION = "Could you share a bit more detail about the issue so I can route it correctly?"


async def ask_prepare(state: SupportState) -> dict:
    question = state.pending_question or DEFAULT_QUESTION
    await repos.add_message(state.session_id, "assistant", question, source=state.channel)
    await record(
        EventType.INFO_REQUESTED,
        session_id=state.session_id,
        actor="need_info_workflow",
        payload={"question": question},
    )
    await repos.update_support_session(state.session_id, status="waiting_employee")
    return {
        "pending_question": question,
        "information_request_count": state.information_request_count + 1,
        "recent_turns": state.recent_turns + [ChatTurn(role="assistant", content=question)],
    }


async def ask_wait(state: SupportState) -> dict:
    # Node body is ONLY the interrupt + post-resume merge (runs once on resume).
    answer = interrupt({"type": "question", "question": state.pending_question})
    text = str(answer).strip()
    await record(
        EventType.EMPLOYEE_REPLIED,
        session_id=state.session_id,
        actor=state.employee_id,
        payload={"answer": text},
    )
    await repos.update_support_session(state.session_id, status="active")
    return {
        "recent_turns": state.recent_turns + [ChatTurn(role="employee", content=text)],
        "pending_question": None,
        "turn_index": state.turn_index + 1,
        "supervisor_cycle_count": 0,
        "handoff_count": 0,
    }
