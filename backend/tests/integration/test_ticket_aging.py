"""Scenario 7: a ticket pending beyond PENDING_ESCALATION_DAYS auto-escalates —
at status-query time (ticket_status → escalation) and via the periodic sweep,
which is idempotent per ticket."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.api import dispatcher
from app.db import repos
from app.db.base import db_session
from app.db.models import AuditEvent, EscalationEvent, Ticket
from app.graph.workflows.escalation import sweep_stale_tickets
from tests.conftest import supervisor_decision

EMPLOYEE = "EMP-021"


async def _seed_pending_ticket(*, days_old: int | None = None) -> Ticket:
    ticket = await repos.create_ticket(
        session_id=None,
        requester_employee_id=EMPLOYEE,
        category="endpoint",
        title="Waiting on replacement dock",
        status="pending",
    )
    if days_old is not None:
        async with db_session() as s:
            row = await s.get(Ticket, ticket.id)
            row.pending_since = datetime.now(timezone.utc) - timedelta(
                days=days_old, hours=2
            )
    return ticket


async def test_stale_pending_ticket_escalates_on_status_query(graph, provider, org_stub):
    ticket = await _seed_pending_ticket(days_old=4)
    provider.enqueue(
        supervisor_decision(
            decision="run_workflow",
            target_specialist=None,
            workflow="ticket_status",
            category="ticketing",
            intent="ticket status inquiry",
            risk_level="low",
            autonomy_level="auto_resolve",
        )
    )

    result = await dispatcher.start_session(
        EMPLOYEE, f"Any update on {ticket.ticket_number}? It's been days."
    )

    assert result["terminal_status"] == "escalated"
    assert result["ticket_number"] == ticket.ticket_number
    assert "escalated" in result["final_response"]

    async with db_session() as s:
        event = (await s.scalars(select(EscalationEvent))).one()
        assert event.trigger == "pending_age"
        assert event.ticket_id == ticket.id
        assert event.to_target_id == org_stub["escalation_target"]["employee_id"]

        stored = await s.get(Ticket, ticket.id)
        assert stored.status == "escalated"
        assert stored.escalated is True
        assert stored.current_owner_id == org_stub["escalation_target"]["employee_id"]
        assert stored.current_team_key == org_stub["escalation_target"]["team_key"]

        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert "ESCALATION_TRIGGERED" in events


async def test_sweep_escalates_stale_ticket(db, org_stub):
    ticket = await _seed_pending_ticket(days_old=4)

    assert await sweep_stale_tickets() == 1

    async with db_session() as s:
        stored = await s.get(Ticket, ticket.id)
        assert stored.status == "escalated"
        assert stored.escalated is True
        assert stored.current_owner_id == org_stub["escalation_target"]["employee_id"]

        event = (await s.scalars(select(EscalationEvent))).one()
        assert event.trigger == "pending_age"
        assert event.ticket_id == ticket.id


async def test_sweep_leaves_fresh_pending_ticket_alone(db, org_stub):
    ticket = await _seed_pending_ticket()  # pending_since = now

    assert await sweep_stale_tickets() == 0

    async with db_session() as s:
        stored = await s.get(Ticket, ticket.id)
        assert stored.status == "pending"
        assert stored.escalated is False
        assert (await s.scalars(select(EscalationEvent))).all() == []


async def test_sweep_is_idempotent(db, org_stub):
    await _seed_pending_ticket(days_old=5)

    assert await sweep_stale_tickets() == 1
    # Second run must not re-escalate the already-escalated ticket.
    assert await sweep_stale_tickets() == 0

    async with db_session() as s:
        events = (await s.scalars(select(EscalationEvent))).all()
    assert len(events) == 1
