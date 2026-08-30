"""Session dispatcher: the single entry point for employee input (web + voice).

Owns the resume protocol (pending interrupt ⇒ Command(resume), else fresh
invoke), per-thread serialization, message persistence, and the out-of-graph
fail-safe: any exception from a graph run becomes a graceful escalation, never
a bare 500.
"""
import asyncio
from typing import Any

from langgraph.types import Command

from app.config import get_settings
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.org import keys

_graph = None
_locks: dict[str, asyncio.Lock] = {}


def set_graph(graph) -> None:
    global _graph
    _graph = graph


def get_graph():
    if _graph is None:
        raise RuntimeError("graph not initialized — app lifespan must call set_graph()")
    return _graph


def _lock_for(session_id: str) -> asyncio.Lock:
    if session_id not in _locks:
        _locks[session_id] = asyncio.Lock()
    return _locks[session_id]


def _config(session_id: str) -> dict:
    settings = get_settings()
    # In-graph budgets always trip first; this is the belt-and-braces backstop.
    recursion_limit = settings.max_supervisor_cycles * 6 + 20
    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": recursion_limit,
    }


async def _pending_interrupt(session_id: str) -> dict | None:
    snapshot = await get_graph().aget_state(_config(session_id))
    for task in getattr(snapshot, "tasks", ()) or ():
        for intr in getattr(task, "interrupts", ()) or ():
            value = getattr(intr, "value", None)
            if isinstance(value, dict):
                return value
            return {"type": "question", "question": str(value)}
    return None


def _response_from(values: dict, pending: dict | None) -> dict[str, Any]:
    assistant_text = None
    if pending is not None:
        if pending.get("type") == "confirmation":
            assistant_text = None  # the confirmation prompt was already persisted
        else:
            assistant_text = pending.get("question")
    return {
        "pending": pending,
        "terminal_status": values.get("terminal_status"),
        "final_response": values.get("final_response"),
        "assistant_message": values.get("final_response") or assistant_text,
        "ticket_number": values.get("ticket_number"),
        "approval_id": values.get("approval_id"),
    }


async def _fail_safe(session_id: str, employee_id: str, error: Exception) -> dict[str, Any]:
    """Out-of-graph escalation: same story as the escalation workflow, built
    directly from repos so it works even when the graph itself is the problem."""
    reason = f"automated processing failed unexpectedly: {type(error).__name__}"
    message = (
        "Something went wrong on my side while working on this, so I've flagged it "
        "for the IT support team to pick up directly. Sorry about that — you don't "
        "need to do anything else."
    )
    ticket_number = None
    try:
        session = await repos.get_support_session(session_id)
        ticket = await repos.create_ticket(
            session_id=session_id,
            requester_employee_id=employee_id,
            category="other",
            title=(session.original_request if session else "IT support request")[:200],
            description=f"Fail-safe escalation. {reason}",
            status="escalated",
            current_team_key=keys.SUPPORT_IT,
            originating_agent="dispatcher",
        )
        ticket_number = ticket.ticket_number
        await repos.create_escalation_event(
            ticket_id=ticket.id,
            session_id=session_id,
            reason=reason,
            trigger="infrastructure",
            from_owner_id=None,
            to_target_id=None,
            to_team_key=keys.SUPPORT_IT,
        )
        await repos.add_message(session_id, "assistant", message)
        await repos.update_support_session(
            session_id, status="failed", terminal_status="failed", final_response=message
        )
        await record(
            EventType.ESCALATION_TRIGGERED,
            session_id=session_id,
            ticket_id=ticket.id,
            actor="dispatcher",
            payload={"reason": reason, "trigger": "infrastructure", "fail_safe": True},
        )
        await record(
            EventType.SESSION_COMPLETED,
            session_id=session_id,
            actor="dispatcher",
            payload={"terminal_status": "failed"},
        )
    except Exception:
        # Postgres itself is down: nothing to persist against — refuse quietly.
        message = (
            "The support system is temporarily unavailable. Please try again in a "
            "few minutes or contact IT directly if it's urgent."
        )
    return {
        "pending": None,
        "terminal_status": "failed",
        "final_response": message,
        "assistant_message": message,
        "ticket_number": ticket_number,
        "approval_id": None,
    }


async def start_session(employee_id: str, text: str, channel: str = "web") -> dict[str, Any]:
    session = await repos.create_support_session(
        employee_id=employee_id,
        channel=channel,
        original_request=text,
        langgraph_thread_id="",  # thread id == session id
    )
    await repos.update_support_session(session.id, langgraph_thread_id=session.id)
    await record(
        EventType.SESSION_STARTED,
        session_id=session.id,
        actor=employee_id,
        payload={"channel": channel, "original_request": text},
    )
    await repos.add_message(session.id, "employee", text, source=channel)

    async with _lock_for(session.id):
        try:
            result = await get_graph().ainvoke(
                {
                    "session_id": session.id,
                    "employee_id": employee_id,
                    "channel": channel,
                    "original_request": text,
                    "incoming_message": text,
                },
                _config(session.id),
            )
            pending = await _pending_interrupt(session.id)
            return {"session_id": session.id, **_response_from(result, pending)}
        except Exception as exc:  # GraphRecursionError included
            return {"session_id": session.id, **(await _fail_safe(session.id, employee_id, exc))}


async def continue_session(
    session_id: str, employee_id: str, payload: str | bool, channel: str = "web"
) -> dict[str, Any]:
    session = await repos.get_support_session(session_id)
    if session is None or session.employee_id != employee_id:
        return {"error": "session not found"}
    if session.terminal_status:
        # A completed graph retains the specialist findings from that request.
        # Re-entering it with an unrelated message would mix two incidents and
        # is the source of incoherent follow-up responses. Start a fresh
        # session instead, while preserving this one as an immutable audit.
        return {"error": "this request is complete; start a new request for another issue", "status_code": 409}

    text = payload if isinstance(payload, str) else ("yes" if payload else "no")
    await repos.add_message(session_id, "employee", text, source=channel)

    async with _lock_for(session_id):
        try:
            pending = await _pending_interrupt(session_id)
            if pending is not None:
                graph_input: Any = Command(resume=payload)
            else:
                await repos.update_support_session(session_id, status="active")
                graph_input = {"incoming_message": text}
            result = await get_graph().ainvoke(graph_input, _config(session_id))
            new_pending = await _pending_interrupt(session_id)
            return {"session_id": session_id, **_response_from(result, new_pending)}
        except Exception as exc:
            return {"session_id": session_id, **(await _fail_safe(session_id, employee_id, exc))}
