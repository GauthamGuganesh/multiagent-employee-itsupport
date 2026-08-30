"""Deterministic ticket-status workflow.

Answers "what happened to my ticket?" from Postgres — by ticket number when
one is mentioned, otherwise by the requester's recent tickets. When the
addressed ticket has been pending beyond the threshold, the case routes into
the escalation workflow instead of a plain answer (scenario 7).
"""
import re

from langgraph.types import Command

from app.config import get_settings
from app.contracts.common import Transition
from app.db import repos
from app.graph.state import SupportState
from app.graph.workflows.escalation import escalate_stale_ticket, pending_age_days

TICKET_RE = re.compile(r"\bIT-\d{3,6}\b", re.IGNORECASE)

STATUS_LABEL = {
    "open": "open",
    "pending": "pending",
    "in_progress": "in progress",
    "waiting_approval": "waiting for approval",
    "resolved": "resolved",
    "closed": "closed",
    "escalated": "escalated to a human owner",
}


def _mentioned_ticket_numbers(state: SupportState) -> list[str]:
    text = state.original_request + " " + " ".join(
        t.content for t in state.recent_turns if t.role == "employee"
    )
    return [m.upper() for m in TICKET_RE.findall(text)]


async def _describe(ticket, include_history: bool = True) -> str:
    label = STATUS_LABEL.get(ticket.status, ticket.status)
    lines = [f"{ticket.ticket_number} — “{ticket.title}” is currently **{label}**."]
    age = pending_age_days(ticket.pending_since)
    if age is not None and ticket.status in ("pending", "waiting_approval"):
        lines.append(f"It has been waiting for {age} day{'s' if age != 1 else ''}.")
    if ticket.current_owner_id:
        lines.append(f"Current owner: {ticket.current_owner_id}.")
    if include_history:
        history = await repos.ticket_history(ticket.id)
        if history:
            last = history[-1]
            lines.append(
                f"Last update: {last.to_status}"
                + (f" — {last.reason}" if last.reason else "")
                + f" ({last.created_at:%Y-%m-%d})."
            )
    return " ".join(lines)


async def ticket_status_node(state: SupportState) -> Command:
    threshold = get_settings().pending_escalation_days
    numbers = _mentioned_ticket_numbers(state)

    ticket = None
    not_found: str | None = None
    if numbers:
        ticket = await repos.get_ticket_by_number(numbers[0])
        if ticket is None:
            not_found = numbers[0]
        elif ticket.requester_employee_id != state.employee_id:
            # Employees may only query their own tickets in V1.
            ticket, not_found = None, numbers[0]
    if ticket is None and not_found is None:
        recent = await repos.find_tickets(requester_employee_id=state.employee_id, limit=3)
        if len(recent) == 1:
            ticket = recent[0]
        elif len(recent) > 1:
            summaries = [await _describe(t, include_history=False) for t in recent]
            response = "Here are your recent requests:\n" + "\n".join(f"- {s}" for s in summaries)
            stale = [
                t for t in recent
                if not t.escalated
                and (pending_age_days(t.pending_since) or 0) > threshold
                and t.status in ("pending", "waiting_approval")
            ]
            if stale:
                info = await escalate_stale_ticket(stale[0].id)
                if info:
                    response += (
                        f"\n\n{info['ticket_number']} had been pending for {info['age_days']} days, "
                        "which is over our service threshold — I've escalated it to "
                        f"{info['target'].employee_name or info['target'].team_name} just now."
                    )
            return Command(goto="close_direct", update={"final_response": response})

    if not_found:
        response = (
            f"I couldn't find a ticket {not_found} under your name. "
            "Double-check the number, or I can list your recent requests."
        )
        return Command(goto="close_direct", update={"final_response": response})
    if ticket is None:
        response = (
            "I don't see any support tickets under your name yet. "
            "If something's broken, just describe it and I'll take a look."
        )
        return Command(goto="close_direct", update={"final_response": response})

    age = pending_age_days(ticket.pending_since)
    if (
        ticket.status in ("pending", "waiting_approval")
        and not ticket.escalated
        and age is not None
        and age > threshold
    ):
        # Stale: route into the escalation workflow with this ticket in scope.
        return Command(
            goto="escalation",
            update={
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "escalation_required": True,
                "escalation_reason": (
                    f"ticket {ticket.ticket_number} has been pending for {age} days, "
                    f"exceeding the {threshold}-day threshold"
                ),
                "escalation_trigger": "pending_age",
                "transition_history": [
                    Transition(
                        from_node="ticket_status", to_node="escalation",
                        reason=f"pending {age}d > {threshold}d threshold",
                    )
                ],
            },
        )

    response = await _describe(ticket)
    return Command(
        goto="close_direct",
        update={
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "final_response": response,
        },
    )
