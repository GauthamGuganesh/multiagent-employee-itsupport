"""Command-center read queries: metrics, filtered lists, session timelines."""
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db.base import db_session
from app.db.models import (
    AgentRun,
    ApprovalRequest,
    AuditEvent,
    EscalationEvent,
    SupportSession,
    Ticket,
    ToolCall,
)

OPEN_TICKET_STATUSES = ("open", "pending", "in_progress", "waiting_approval", "escalated")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def overview_metrics() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stale_cutoff = now - timedelta(days=get_settings().pending_escalation_days)
    async with db_session() as s:
        async def count(stmt) -> int:
            return int(await s.scalar(stmt) or 0)

        return {
            "active_sessions": await count(
                select(func.count()).select_from(SupportSession).where(
                    SupportSession.status.in_(("active", "waiting_employee"))
                )
            ),
            "resolved_today": await count(
                select(func.count()).select_from(SupportSession).where(
                    SupportSession.terminal_status == "resolved",
                    SupportSession.updated_at >= midnight,
                )
            ),
            "open_tickets": await count(
                select(func.count()).select_from(Ticket).where(Ticket.status.in_(OPEN_TICKET_STATUSES))
            ),
            "pending_approvals": await count(
                select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "pending")
            ),
            "escalated_tickets": await count(
                select(func.count()).select_from(Ticket).where(
                    Ticket.escalated.is_(True), Ticket.status.in_(OPEN_TICKET_STATUSES)
                )
            ),
            "pending_over_threshold": await count(
                select(func.count()).select_from(Ticket).where(
                    Ticket.status.in_(("pending", "waiting_approval")),
                    Ticket.pending_since.is_not(None),
                    Ticket.pending_since < stale_cutoff,
                )
            ),
            "human_interventions": await count(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.event_type == "HUMAN_INTERVENTION"
                )
            ),
            "agent_failures": await count(
                select(func.count()).select_from(AgentRun).where(AgentRun.status == "failed")
            ),
            "loop_guard_activations": await count(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.event_type == "LOOP_GUARD_TRIGGERED"
                )
            ),
            "structured_output_failures": await count(
                select(func.count()).select_from(AuditEvent).where(
                    AuditEvent.event_type == "STRUCTURED_OUTPUT_FAILED"
                )
            ),
        }


async def list_sessions(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    stmt = select(SupportSession).order_by(SupportSession.updated_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(SupportSession.status == status)
    async with db_session() as s:
        rows = (await s.scalars(stmt)).all()
    return [
        {
            "id": r.id,
            "employee_id": r.employee_id,
            "channel": r.channel,
            "status": r.status,
            "terminal_status": r.terminal_status,
            "original_request": r.original_request,
            "category": r.category,
            "intent": r.intent,
            "risk_level": r.risk_level,
            "autonomy_level": r.autonomy_level,
            "created_at": _iso(r.created_at),
            "updated_at": _iso(r.updated_at),
        }
        for r in rows
    ]


async def session_timeline(session_id: str) -> list[dict[str, Any]]:
    """Chronological merge of audit events, agent runs, and tool calls."""
    async with db_session() as s:
        events = (
            await s.scalars(
                select(AuditEvent).where(AuditEvent.session_id == session_id).order_by(AuditEvent.created_at)
            )
        ).all()
        runs = (
            await s.scalars(select(AgentRun).where(AgentRun.session_id == session_id))
        ).all()
        calls = (
            await s.scalars(select(ToolCall).where(ToolCall.session_id == session_id))
        ).all()

    entries: list[dict[str, Any]] = [
        {
            "kind": "event",
            "at": _iso(e.created_at),
            "event_type": e.event_type,
            "actor": e.actor,
            "payload": e.payload,
        }
        for e in events
    ]
    entries += [
        {
            "kind": "agent_run",
            "at": _iso(r.started_at),
            "agent_name": r.agent_name,
            "run_index": r.run_index,
            "status": r.status,
            "outcome": r.outcome,
            "confidence": r.confidence,
            "reasoning_summary": r.reasoning_summary,
            "findings": r.findings,
            "tools_used": r.tools_used,
            "handoff_target": r.handoff_target,
            "structured_output_retries": r.structured_output_retries,
            "loop_guard_triggered": r.loop_guard_triggered,
            "failure_type": r.failure_type,
            "failure_detail": r.failure_detail,
            "result": r.result,
            "memories_retrieved": r.memories_retrieved,
            "memories_written": r.memories_written,
            "completed_at": _iso(r.completed_at),
        }
        for r in runs
    ]
    entries += [
        {
            "kind": "tool_call",
            "at": _iso(c.created_at),
            "tool_name": c.tool_name,
            "status": c.status,
            "request": c.request,
            "response": c.response,
            "error": c.error,
            "duration_ms": c.duration_ms,
        }
        for c in calls
    ]
    return sorted(entries, key=lambda x: x["at"] or "")


async def list_tickets(
    *,
    status: str | None = None,
    category: str | None = None,
    team: str | None = None,
    owner: str | None = None,
    originating_agent: str | None = None,
    security_related: bool | None = None,
    escalated: bool | None = None,
    approval_pending: bool | None = None,
    pending_over_threshold: bool | None = None,
    search: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    sort: str = "newest",
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(Ticket).limit(limit)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if category:
        stmt = stmt.where(Ticket.category == category)
    if team:
        stmt = stmt.where(Ticket.current_team_key == team)
    if owner:
        stmt = stmt.where(Ticket.current_owner_id == owner)
    if originating_agent:
        stmt = stmt.where(Ticket.originating_agent == originating_agent)
    if security_related is not None:
        stmt = stmt.where(Ticket.security_related.is_(security_related))
    if escalated is not None:
        stmt = stmt.where(Ticket.escalated.is_(escalated))
    if pending_over_threshold:
        cutoff = datetime.now(timezone.utc) - timedelta(days=get_settings().pending_escalation_days)
        stmt = stmt.where(
            Ticket.status.in_(("pending", "waiting_approval")),
            Ticket.pending_since.is_not(None),
            Ticket.pending_since < cutoff,
        )
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            Ticket.title.ilike(pattern)
            | Ticket.description.ilike(pattern)
            | Ticket.ticket_number.ilike(pattern)
            | Ticket.requester_employee_id.ilike(pattern)
        )
    if created_after:
        stmt = stmt.where(Ticket.created_at >= created_after)
    if created_before:
        stmt = stmt.where(Ticket.created_at <= created_before)

    if sort == "oldest":
        stmt = stmt.order_by(Ticket.created_at.asc())
    elif sort == "longest_pending":
        stmt = stmt.where(Ticket.pending_since.is_not(None)).order_by(Ticket.pending_since.asc())
    elif sort == "recently_updated":
        stmt = stmt.order_by(Ticket.updated_at.desc())
    else:
        stmt = stmt.order_by(Ticket.created_at.desc())

    async with db_session() as s:
        rows = (await s.scalars(stmt)).all()

    if approval_pending:
        async with db_session() as s:
            pending_ids = set(
                (
                    await s.scalars(
                        select(ApprovalRequest.ticket_id).where(ApprovalRequest.status == "pending")
                    )
                ).all()
            )
        rows = [r for r in rows if r.id in pending_ids]

    from app.graph.workflows.escalation import pending_age_days

    return [
        {
            "id": t.id,
            "ticket_number": t.ticket_number,
            "session_id": t.session_id,
            "requester_employee_id": t.requester_employee_id,
            "title": t.title,
            "category": t.category,
            "status": t.status,
            "priority": t.priority,
            "current_owner_id": t.current_owner_id,
            "current_team_key": t.current_team_key,
            "originating_agent": t.originating_agent,
            "security_related": t.security_related,
            "escalated": t.escalated,
            "pending_age_days": pending_age_days(t.pending_since),
            "created_at": _iso(t.created_at),
            "updated_at": _iso(t.updated_at),
        }
        for t in rows
    ]


async def list_agent_runs(
    *,
    agent_name: str | None = None,
    outcome: str | None = None,
    status: str | None = None,
    failure_type: str | None = None,
    loop_guard: bool | None = None,
    structured_output_failed: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    if outcome:
        stmt = stmt.where(AgentRun.outcome == outcome)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if failure_type:
        stmt = stmt.where(AgentRun.failure_type == failure_type)
    if loop_guard is not None:
        stmt = stmt.where(AgentRun.loop_guard_triggered.is_(loop_guard))
    if structured_output_failed:
        stmt = stmt.where(AgentRun.structured_output_retries > 0)
    if created_after:
        stmt = stmt.where(AgentRun.started_at >= created_after)
    if created_before:
        stmt = stmt.where(AgentRun.started_at <= created_before)
    async with db_session() as s:
        rows = (await s.scalars(stmt)).all()
    return [
        {
            "id": r.id,
            "session_id": r.session_id,
            "agent_name": r.agent_name,
            "run_index": r.run_index,
            "status": r.status,
            "outcome": r.outcome,
            "confidence": r.confidence,
            "reasoning_summary": r.reasoning_summary,
            "handoff_target": r.handoff_target,
            "structured_output_retries": r.structured_output_retries,
            "loop_guard_triggered": r.loop_guard_triggered,
            "failure_type": r.failure_type,
            "started_at": _iso(r.started_at),
            "completed_at": _iso(r.completed_at),
        }
        for r in rows
    ]


async def list_approvals(status: str | None = "pending", limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    async with db_session() as s:
        rows = (await s.scalars(stmt)).all()
        ticket_numbers: dict[str, str] = {}
        ids = [r.ticket_id for r in rows if r.ticket_id]
        if ids:
            tickets = (await s.scalars(select(Ticket).where(Ticket.id.in_(ids)))).all()
            ticket_numbers = {t.id: t.ticket_number for t in tickets}
    return [
        {
            "id": r.id,
            "ticket_id": r.ticket_id,
            "ticket_number": ticket_numbers.get(r.ticket_id or ""),
            "session_id": r.session_id,
            "requester_employee_id": r.requester_employee_id,
            "approver_employee_id": r.approver_employee_id,
            "privilege_key": r.privilege_key,
            "system_key": r.system_key,
            "action_summary": r.action_summary,
            "action_key": r.action_key,
            "risk_level": r.risk_level,
            "status": r.status,
            "decision_reason": r.decision_reason,
            "decided_by": r.decided_by,
            "decided_at": _iso(r.decided_at),
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


async def list_escalations(limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(EscalationEvent).order_by(EscalationEvent.created_at.desc()).limit(limit)
    async with db_session() as s:
        rows = (await s.scalars(stmt)).all()
        ids = [r.ticket_id for r in rows if r.ticket_id]
        tickets = {}
        if ids:
            for t in (await s.scalars(select(Ticket).where(Ticket.id.in_(ids)))).all():
                tickets[t.id] = t
    return [
        {
            "id": r.id,
            "ticket_id": r.ticket_id,
            "ticket_number": tickets[r.ticket_id].ticket_number if r.ticket_id in tickets else None,
            "ticket_status": tickets[r.ticket_id].status if r.ticket_id in tickets else None,
            "session_id": r.session_id,
            "reason": r.reason,
            "trigger": r.trigger,
            "from_owner_id": r.from_owner_id,
            "to_target_id": r.to_target_id,
            "to_team_key": r.to_team_key,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]


async def list_audit_events(
    *,
    session_id: str | None = None,
    ticket_id: str | None = None,
    event_type: str | None = None,
    created_after: datetime | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if session_id:
        stmt = stmt.where(AuditEvent.session_id == session_id)
    if ticket_id:
        stmt = stmt.where(AuditEvent.ticket_id == ticket_id)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if created_after:
        stmt = stmt.where(AuditEvent.created_at >= created_after)
    async with db_session() as s:
        rows = (await s.scalars(stmt)).all()
    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "ticket_id": e.ticket_id,
            "event_type": e.event_type,
            "actor": e.actor,
            "payload": e.payload,
            "created_at": _iso(e.created_at),
        }
        for e in rows
    ]
