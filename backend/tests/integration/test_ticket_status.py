"""Scenario 6: ticket status answered deterministically from Postgres —
by number, with graceful not-found / empty answers, and never disclosing
another employee's ticket."""
from sqlalchemy import select

from app.api import dispatcher
from app.db import repos
from app.db.base import db_session
from app.db.models import EscalationEvent, Ticket
from tests.conftest import supervisor_decision

EMPLOYEE = "EMP-020"
OTHER_EMPLOYEE = "EMP-050"


def _queue_status_decision(provider):
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


async def test_own_ticket_by_number(graph, provider, org_stub):
    ticket = await repos.create_ticket(
        session_id=None,
        requester_employee_id=EMPLOYEE,
        category="endpoint",
        title="Replace failing laptop battery",
        status="in_progress",
    )
    _queue_status_decision(provider)

    result = await dispatcher.start_session(
        EMPLOYEE, f"What's the status of {ticket.ticket_number}?"
    )

    assert result["terminal_status"] == "resolved"
    assert ticket.ticket_number in result["final_response"]
    assert "in progress" in result["final_response"]

    async with db_session() as s:
        # A plain status answer never escalates or mutates the ticket.
        assert (await s.scalars(select(EscalationEvent))).all() == []
        stored = await s.get(Ticket, ticket.id)
        assert stored.status == "in_progress"


async def test_unknown_ticket_number(graph, provider, org_stub):
    _queue_status_decision(provider)

    result = await dispatcher.start_session(EMPLOYEE, "What's the status of IT-4242?")

    assert result["terminal_status"] == "resolved"
    assert "couldn't find" in result["final_response"]
    assert "IT-4242" in result["final_response"]


async def test_no_tickets_yet(graph, provider, org_stub):
    _queue_status_decision(provider)

    result = await dispatcher.start_session(EMPLOYEE, "What's the status of my ticket?")

    assert result["terminal_status"] == "resolved"
    assert "don't see any support tickets" in result["final_response"]


async def test_other_employees_ticket_is_not_disclosed(graph, provider, org_stub):
    ticket = await repos.create_ticket(
        session_id=None,
        requester_employee_id=OTHER_EMPLOYEE,
        category="identity",
        title="Confidential access review",
        status="in_progress",
    )
    _queue_status_decision(provider)

    result = await dispatcher.start_session(
        EMPLOYEE, f"What's the status of {ticket.ticket_number}?"
    )

    # Privacy: another requester's ticket reads as not found — no leakage.
    assert result["terminal_status"] == "resolved"
    assert "couldn't find" in result["final_response"]
    assert ticket.ticket_number in result["final_response"]
    assert "Confidential access review" not in result["final_response"]
    assert "in progress" not in result["final_response"]
