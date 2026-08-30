"""Repository layer over the operational store.

Functions open their own sessions (workflow nodes call them directly) and
return ORM objects detached-safe (expire_on_commit=False).
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import func, select

from app.db.base import db_session
from app.db.models import (
    ActionConfirmation,
    ActionExecution,
    AgentRun,
    ApprovalRequest,
    EscalationEvent,
    Message,
    SupportSession,
    Ticket,
    TicketStatusHistory,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- sessions -------------------------------------------------------------

async def create_support_session(
    employee_id: str, channel: str, original_request: str, langgraph_thread_id: str
) -> SupportSession:
    row = SupportSession(
        employee_id=employee_id,
        channel=channel,
        original_request=original_request,
        langgraph_thread_id=langgraph_thread_id,
    )
    async with db_session() as s:
        s.add(row)
        await s.flush()
    return row


async def update_support_session(session_id: str, **fields: Any) -> None:
    async with db_session() as s:
        row = await s.get(SupportSession, session_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)


async def get_support_session(session_id: str) -> SupportSession | None:
    async with db_session() as s:
        return await s.get(SupportSession, session_id)


async def add_message(session_id: str, role: str, content: str, source: str = "web") -> Message:
    row = Message(session_id=session_id, role=role, content=content, source=source)
    async with db_session() as s:
        s.add(row)
        await s.flush()
    return row


async def list_messages(session_id: str) -> Sequence[Message]:
    async with db_session() as s:
        rows = await s.scalars(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
        return rows.all()


# --- tickets ---------------------------------------------------------------

async def _next_ticket_number(s: Any) -> str:
    count = await s.scalar(select(func.count()).select_from(Ticket))
    return f"IT-{1001 + int(count or 0)}"


async def create_ticket(
    *,
    session_id: str | None,
    requester_employee_id: str,
    category: str,
    title: str,
    description: str = "",
    priority: str = "medium",
    status: str = "open",
    current_owner_id: str | None = None,
    current_team_key: str | None = None,
    originating_agent: str | None = None,
    security_related: bool = False,
) -> Ticket:
    async with db_session() as s:
        row = Ticket(
            ticket_number=await _next_ticket_number(s),
            session_id=session_id,
            requester_employee_id=requester_employee_id,
            category=category,
            title=title[:200],
            description=description,
            priority=priority,
            status=status,
            current_owner_id=current_owner_id,
            current_team_key=current_team_key,
            originating_agent=originating_agent,
            security_related=security_related,
            escalated=(status == "escalated"),
            pending_since=_now() if status == "pending" else None,
        )
        s.add(row)
        await s.flush()
        s.add(
            TicketStatusHistory(
                ticket_id=row.id, from_status=None, to_status=status,
                changed_by=originating_agent or "system", reason="ticket created",
            )
        )
        await s.flush()
    return row


async def get_ticket(ticket_id: str) -> Ticket | None:
    async with db_session() as s:
        return await s.get(Ticket, ticket_id)


async def get_ticket_by_number(ticket_number: str) -> Ticket | None:
    async with db_session() as s:
        return await s.scalar(select(Ticket).where(Ticket.ticket_number == ticket_number.upper()))


async def find_tickets(
    *,
    requester_employee_id: str | None = None,
    status: str | None = None,
    category: str | None = None,
    text: str | None = None,
    limit: int = 10,
) -> Sequence[Ticket]:
    stmt = select(Ticket).order_by(Ticket.created_at.desc()).limit(limit)
    if requester_employee_id:
        stmt = stmt.where(Ticket.requester_employee_id == requester_employee_id)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if category:
        stmt = stmt.where(Ticket.category == category)
    if text:
        pattern = f"%{text}%"
        stmt = stmt.where(Ticket.title.ilike(pattern) | Ticket.description.ilike(pattern))
    async with db_session() as s:
        rows = await s.scalars(stmt)
        return rows.all()


async def update_ticket_status(
    ticket_id: str, to_status: str, *, changed_by: str = "system", reason: str = "", **extra: Any
) -> Ticket | None:
    """Status transition with history; manages pending_since / escalated flags."""
    async with db_session() as s:
        row = await s.get(Ticket, ticket_id)
        if row is None:
            return None
        from_status = row.status
        row.status = to_status
        if to_status == "pending" and row.pending_since is None:
            row.pending_since = _now()
        if to_status not in ("pending", "waiting_approval"):
            row.pending_since = None
        if to_status == "escalated":
            row.escalated = True
        for k, v in extra.items():
            setattr(row, k, v)
        s.add(
            TicketStatusHistory(
                ticket_id=ticket_id, from_status=from_status, to_status=to_status,
                changed_by=changed_by, reason=reason,
            )
        )
        await s.flush()
    return row


async def ticket_history(ticket_id: str) -> Sequence[TicketStatusHistory]:
    async with db_session() as s:
        rows = await s.scalars(
            select(TicketStatusHistory)
            .where(TicketStatusHistory.ticket_id == ticket_id)
            .order_by(TicketStatusHistory.created_at)
        )
        return rows.all()


async def stale_pending_tickets(days: int) -> Sequence[Ticket]:
    cutoff = _now() - timedelta(days=days)
    async with db_session() as s:
        rows = await s.scalars(
            select(Ticket).where(
                Ticket.status.in_(("pending", "waiting_approval")),
                Ticket.pending_since.is_not(None),
                Ticket.pending_since < cutoff,
                Ticket.escalated.is_(False),
            )
        )
        return rows.all()


# --- agent runs -------------------------------------------------------------

async def create_agent_run(session_id: str, agent_name: str, run_index: int) -> AgentRun:
    row = AgentRun(session_id=session_id, agent_name=agent_name, run_index=run_index)
    async with db_session() as s:
        s.add(row)
        await s.flush()
    return row


async def complete_agent_run(run_id: str, **fields: Any) -> None:
    async with db_session() as s:
        row = await s.get(AgentRun, run_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        if row.completed_at is None:
            row.completed_at = _now()


# --- approvals ---------------------------------------------------------------

async def create_approval_request(
    *,
    ticket_id: str | None,
    session_id: str | None,
    requester_employee_id: str,
    approver_employee_id: str,
    privilege_key: str,
    system_key: str | None,
    action_summary: str,
    action_key: str | None,
    params: dict | None,
    risk_level: str,
) -> ApprovalRequest:
    row = ApprovalRequest(
        ticket_id=ticket_id,
        session_id=session_id,
        requester_employee_id=requester_employee_id,
        approver_employee_id=approver_employee_id,
        privilege_key=privilege_key,
        system_key=system_key,
        action_summary=action_summary,
        action_key=action_key,
        params=params or {},
        risk_level=risk_level,
    )
    async with db_session() as s:
        s.add(row)
        await s.flush()
    return row


async def get_approval(approval_id: str) -> ApprovalRequest | None:
    async with db_session() as s:
        return await s.get(ApprovalRequest, approval_id)


async def decide_approval(
    approval_id: str, *, approved: bool, decided_by: str, reason: str = ""
) -> ApprovalRequest | None:
    async with db_session() as s:
        row = await s.get(ApprovalRequest, approval_id)
        if row is None or row.status != "pending":
            return None
        row.status = "approved" if approved else "rejected"
        row.decision_reason = reason
        row.decided_by = decided_by
        row.decided_at = _now()
        await s.flush()
    return row


# --- escalations ---------------------------------------------------------------

async def create_escalation_event(
    *,
    ticket_id: str | None,
    session_id: str | None,
    reason: str,
    trigger: str,
    from_owner_id: str | None,
    to_target_id: str | None,
    to_team_key: str | None,
) -> EscalationEvent:
    row = EscalationEvent(
        ticket_id=ticket_id,
        session_id=session_id,
        reason=reason,
        trigger=trigger,
        from_owner_id=from_owner_id,
        to_target_id=to_target_id,
        to_team_key=to_team_key,
    )
    async with db_session() as s:
        s.add(row)
        await s.flush()
    return row


# --- confirmations & executions ---------------------------------------------

async def create_confirmation(
    *, session_id: str, employee_id: str, action_key: str, action_summary: str, params: dict
) -> ActionConfirmation:
    row = ActionConfirmation(
        session_id=session_id,
        employee_id=employee_id,
        action_key=action_key,
        action_summary=action_summary,
        params=params,
    )
    async with db_session() as s:
        s.add(row)
        await s.flush()
    return row


async def respond_confirmation(confirmation_id: str, confirmed: bool) -> ActionConfirmation | None:
    async with db_session() as s:
        row = await s.get(ActionConfirmation, confirmation_id)
        if row is None:
            return None
        row.confirmed = confirmed
        row.responded_at = _now()
        await s.flush()
    return row


async def create_action_execution(
    *,
    session_id: str | None,
    action_key: str,
    params: dict,
    result: dict,
    status: str,
    confirmation_id: str | None = None,
    approval_id: str | None = None,
) -> ActionExecution:
    row = ActionExecution(
        session_id=session_id,
        confirmation_id=confirmation_id,
        approval_id=approval_id,
        action_key=action_key,
        params=params,
        result=result,
        status=status,
    )
    async with db_session() as s:
        s.add(row)
        await s.flush()
    return row
