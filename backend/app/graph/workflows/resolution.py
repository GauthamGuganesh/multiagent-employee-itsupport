"""Resolution workflow: persist the employee-confirmed outcome and close."""
from app.config import get_settings
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState
from app.graph.workflows.common import finalize_session


def compose_resolution_candidate(state: SupportState) -> str:
    if state.final_response:
        return state.final_response
    for result in reversed(state.specialist_results):
        if result.outcome == "resolution_recommended" and result.resolution_summary:
            return result.resolution_summary
    if state.specialist_findings:
        finding_lines = "\n".join(f"- {f.summary}" for f in state.specialist_findings[-4:])
        return (
            "Here's what I found while looking into this:\n"
            f"{finding_lines}\n"
            "Let me know if anything still isn't working."
        )
    return "This looks resolved on my side. Let me know if anything still isn't working."


async def resolution_node(state: SupportState) -> dict:
    candidate = state.resolution_candidate or compose_resolution_candidate(state)
    response = (
        "Thanks for confirming — I’m glad the issue is resolved. I’ve closed this support request."
        if get_settings().require_employee_resolution_confirmation
        else candidate
    )

    ticket_id = state.ticket_id
    ticket_number = state.ticket_number
    if ticket_id is None and get_settings().create_ticket_for_resolved_sessions:
        ticket = await repos.create_ticket(
            session_id=state.session_id,
            requester_employee_id=state.employee_id,
            category=state.category or "other",
            title=(state.intent or state.original_request)[:200],
            description=state.original_request,
            status="open",
            originating_agent=state.current_agent or "supervisor",
            security_related=(state.category == "security"),
        )
        ticket_id, ticket_number = ticket.id, ticket.ticket_number
        await record(
            EventType.TICKET_CREATED,
            session_id=state.session_id,
            ticket_id=ticket_id,
            actor="resolution_workflow",
            payload={"ticket_number": ticket_number, "status": "open"},
        )
    # Routine conversational resolutions are fully audited by the session,
    # messages, agent runs, tools, and actions. Create tickets only when a
    # workflow actually needs durable human/approval tracking. If one already
    # exists, close it here after the employee confirms success.
    if ticket_id is not None:
        await repos.update_ticket_status(
            ticket_id, "resolved", changed_by="resolution_workflow",
            reason=candidate[:300],
        )
        await record(
            EventType.TICKET_STATUS_CHANGED,
            session_id=state.session_id,
            ticket_id=ticket_id,
            actor="resolution_workflow",
            payload={"ticket_number": ticket_number, "to_status": "resolved"},
        )

    if ticket_number and ticket_number not in response:
        response = f"{response} Ticket {ticket_number} is now marked resolved."

    update = await finalize_session(
        state, terminal_status="resolved", final_response=response, session_status="completed"
    )
    return {**update, "ticket_id": ticket_id, "ticket_number": ticket_number}


async def close_direct_node(state: SupportState) -> dict:
    """close_session decision: no specialist work or ticket required."""
    response = state.final_response or "Happy to help — let me know if anything else comes up."
    return await finalize_session(
        state, terminal_status="resolved", final_response=response, session_status="completed"
    )
