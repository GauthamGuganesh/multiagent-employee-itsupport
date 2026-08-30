"""Ticketing-domain tools backed by the Postgres operational store.

All persistence goes through app.db.repos (no direct SQL here). None of these
tools is privileged: tickets, approval requests, and escalation records are
the audit trail itself, created by workflows and the supervisor. Repos return
tz-aware datetimes; ages are computed against datetime.now(timezone.utc), and
naive values (SQLite drops tzinfo) are defensively treated as UTC.
"""
from datetime import datetime, timezone

from pydantic import BaseModel

from app.db import repos
from app.db.models import Ticket
from app.tools.registry import ToolContext, ToolSpec, register


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _pending_age_days(pending_since: datetime | None) -> int | None:
    if pending_since is None:
        return None
    return max((datetime.now(timezone.utc) - _aware(pending_since)).days, 0)


class TicketBrief(BaseModel):
    ticket_number: str
    title: str
    status: str
    priority: str
    created_at: str
    pending_age_days: int | None
    escalated: bool


def _brief(ticket: Ticket) -> TicketBrief:
    return TicketBrief(
        ticket_number=ticket.ticket_number,
        title=ticket.title,
        status=ticket.status,
        priority=ticket.priority,
        created_at=_aware(ticket.created_at).isoformat(),
        pending_age_days=_pending_age_days(ticket.pending_since),
        escalated=ticket.escalated,
    )


class CreateTicketInput(BaseModel):
    requester_employee_id: str
    category: str
    title: str
    description: str = ""
    priority: str = "medium"


class CreateTicketOutput(BaseModel):
    ticket_id: str
    ticket_number: str
    status: str
    priority: str
    security_related: bool
    summary: str


async def _create_ticket(inp: CreateTicketInput, ctx: ToolContext) -> CreateTicketOutput:
    ticket = await repos.create_ticket(
        session_id=ctx.session_id,
        requester_employee_id=inp.requester_employee_id,
        category=inp.category,
        title=inp.title,
        description=inp.description,
        priority=inp.priority,
        originating_agent=ctx.agent_name,
        security_related=inp.category == "security",
    )
    return CreateTicketOutput(
        ticket_id=ticket.id,
        ticket_number=ticket.ticket_number,
        status=ticket.status,
        priority=ticket.priority,
        security_related=ticket.security_related,
        summary=(
            f"Created ticket {ticket.ticket_number} ({inp.category}, "
            f"priority {ticket.priority}) for {inp.requester_employee_id}."
        ),
    )


register(
    ToolSpec(
        name="create_ticket",
        description=(
            "Open a new support ticket for the requester with a category, "
            "title, optional description, and priority (low|medium|high|"
            "critical). Returns the assigned ticket number."
        ),
        domain="ticketing",
        input_model=CreateTicketInput,
        output_model=CreateTicketOutput,
        handler=_create_ticket,
    )
)


class GetTicketStatusInput(BaseModel):
    ticket_number: str = ""
    requester_employee_id: str = ""
    text: str = ""


class GetTicketStatusOutput(BaseModel):
    tickets: list[TicketBrief]
    matched_count: int
    summary: str


async def _get_ticket_status(
    inp: GetTicketStatusInput, ctx: ToolContext
) -> GetTicketStatusOutput:
    if inp.ticket_number:
        ticket = await repos.get_ticket_by_number(inp.ticket_number)
        tickets = [ticket] if ticket is not None else []
    elif inp.requester_employee_id or inp.text:
        tickets = list(
            await repos.find_tickets(
                requester_employee_id=inp.requester_employee_id or None,
                text=inp.text or None,
            )
        )
    else:
        raise ValueError("provide a ticket_number, requester_employee_id, or text to search")

    briefs = [_brief(t) for t in tickets]
    if not briefs:
        needle = inp.ticket_number or inp.text or inp.requester_employee_id
        summary = f"No tickets found matching '{needle}'."
    elif len(briefs) == 1:
        b = briefs[0]
        age = f", pending for {b.pending_age_days} day(s)" if b.pending_age_days is not None else ""
        summary = f"Ticket {b.ticket_number} ('{b.title}') is {b.status}{age}."
    else:
        statuses = ", ".join(f"{b.ticket_number}={b.status}" for b in briefs[:5])
        summary = f"Found {len(briefs)} ticket(s): {statuses}."
    return GetTicketStatusOutput(tickets=briefs, matched_count=len(briefs), summary=summary)


register(
    ToolSpec(
        name="get_ticket_status",
        description=(
            "Look up tickets: by exact ticket number (e.g. IT-1042), or search "
            "by requester employee ID and/or title/description text. Returns "
            "each match's number, title, status, priority, creation time, "
            "escalation flag, and — for pending tickets — age in days."
        ),
        domain="ticketing",
        input_model=GetTicketStatusInput,
        output_model=GetTicketStatusOutput,
        handler=_get_ticket_status,
    )
)


class UpdateTicketInput(BaseModel):
    ticket_number: str
    status: str = ""
    note: str = ""


class UpdateTicketOutput(BaseModel):
    ticket_number: str
    from_status: str
    status: str
    summary: str


async def _update_ticket(inp: UpdateTicketInput, ctx: ToolContext) -> UpdateTicketOutput:
    if not inp.status and not inp.note:
        raise ValueError("provide a status, a note, or both")
    ticket = await repos.get_ticket_by_number(inp.ticket_number)
    if ticket is None:
        raise ValueError(f"no ticket found with number {inp.ticket_number}")
    from_status = ticket.status
    to_status = inp.status or ticket.status
    updated = await repos.update_ticket_status(
        ticket.id, to_status, changed_by=ctx.agent_name, reason=inp.note
    )
    if inp.status and inp.status != from_status:
        summary = f"Ticket {inp.ticket_number} moved from {from_status} to {to_status}."
    else:
        summary = f"Added a note to ticket {inp.ticket_number} (status remains {to_status})."
    return UpdateTicketOutput(
        ticket_number=inp.ticket_number,
        from_status=from_status,
        status=updated.status if updated is not None else to_status,
        summary=summary,
    )


register(
    ToolSpec(
        name="update_ticket",
        description=(
            "Transition a ticket to a new status (open|pending|in_progress|"
            "waiting_approval|resolved|closed|escalated) and/or append a note; "
            "every change is recorded in the ticket's status history."
        ),
        domain="ticketing",
        input_model=UpdateTicketInput,
        output_model=UpdateTicketOutput,
        handler=_update_ticket,
    )
)


class CreateApprovalRequestInput(BaseModel):
    requester_employee_id: str
    approver_employee_id: str
    privilege_key: str
    action_summary: str
    ticket_id: str = ""
    system_key: str = ""
    action_key: str = ""
    risk_level: str = "medium"


class CreateApprovalRequestOutput(BaseModel):
    approval_id: str
    approver_employee_id: str
    status: str
    summary: str


async def _create_approval_request(
    inp: CreateApprovalRequestInput, ctx: ToolContext
) -> CreateApprovalRequestOutput:
    row = await repos.create_approval_request(
        ticket_id=inp.ticket_id or None,
        session_id=ctx.session_id,
        requester_employee_id=inp.requester_employee_id,
        approver_employee_id=inp.approver_employee_id,
        privilege_key=inp.privilege_key,
        system_key=inp.system_key or None,
        action_summary=inp.action_summary,
        action_key=inp.action_key or None,
        params=None,
        risk_level=inp.risk_level,
    )
    return CreateApprovalRequestOutput(
        approval_id=row.id,
        approver_employee_id=inp.approver_employee_id,
        status=row.status,
        summary=(
            f"Created approval request for '{inp.action_summary}' "
            f"({inp.privilege_key}); pending decision by {inp.approver_employee_id}."
        ),
    )


register(
    ToolSpec(
        name="create_approval_request",
        description=(
            "Record a pending approval request: who is asking, which approver "
            "must decide, the privilege involved, and a summary of the action. "
            "Does not execute anything — the approval workflow does."
        ),
        domain="ticketing",
        input_model=CreateApprovalRequestInput,
        output_model=CreateApprovalRequestOutput,
        handler=_create_approval_request,
    )
)


class RecordEscalationInput(BaseModel):
    reason: str
    trigger: str
    ticket_id: str = ""
    from_owner_id: str = ""
    to_target_id: str = ""
    to_team_key: str = ""


class RecordEscalationOutput(BaseModel):
    escalation_id: str
    trigger: str
    summary: str


async def _record_escalation(
    inp: RecordEscalationInput, ctx: ToolContext
) -> RecordEscalationOutput:
    row = await repos.create_escalation_event(
        ticket_id=inp.ticket_id or None,
        session_id=ctx.session_id,
        reason=inp.reason,
        trigger=inp.trigger,
        from_owner_id=inp.from_owner_id or None,
        to_target_id=inp.to_target_id or None,
        to_team_key=inp.to_team_key or None,
    )
    target = inp.to_target_id or inp.to_team_key or "human review"
    return RecordEscalationOutput(
        escalation_id=row.id,
        trigger=inp.trigger,
        summary=f"Recorded escalation to {target} (trigger: {inp.trigger}): {inp.reason}",
    )


register(
    ToolSpec(
        name="record_escalation",
        description=(
            "Persist an escalation event with its reason, trigger, and the "
            "human target (employee and/or team) it hands off to. Audit record "
            "only — the escalation workflow performs the handoff."
        ),
        domain="ticketing",
        input_model=RecordEscalationInput,
        output_model=RecordEscalationOutput,
        handler=_record_escalation,
    )
)
