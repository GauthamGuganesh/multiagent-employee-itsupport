"""Supervisor routing: representative requests reach each specialist and the
ticketing workflow — every route ends resolved with a real audit trail."""
import pytest
from sqlalchemy import select

from app.api import dispatcher
from app.db.base import db_session
from app.db.models import AgentRun, AuditEvent, Ticket, ToolCall
from app.org import keys
from tests.conftest import specialist_finish, specialist_tool_step, supervisor_decision


def _queue_route_and_resolve(provider, specialist: str, category: str, summary: str):
    provider.enqueue(
        supervisor_decision(target_specialist=specialist, category=category),
        specialist_finish(agent=specialist, outcome="resolved", resolution_summary=summary),
        supervisor_decision(
            decision="run_workflow", target_specialist=None, workflow="resolution",
            category=category,
        ),
    )


@pytest.mark.parametrize(
    ("specialist", "category", "employee_id", "request_text"),
    [
        ("identity", "identity", "EMP-020", "I can't sign in to Okta this morning."),
        ("network", "network", "EMP-021", "The office wifi keeps dropping my connection."),
        ("security", "security", "EMP-022", "I got a weird phishing-looking email — am I okay?"),
    ],
)
async def test_supervisor_routes_to_each_specialist(
    graph, provider, org_stub, specialist, category, employee_id, request_text
):
    summary = f"Investigated and resolved the {category} issue; nothing further needed."
    _queue_route_and_resolve(provider, specialist, category, summary)

    result = await dispatcher.start_session(employee_id, request_text)

    assert result["pending"] is None
    assert result["terminal_status"] == "resolved"
    assert result["ticket_number"] is not None
    assert summary in result["final_response"]

    async with db_session() as s:
        runs = (await s.scalars(select(AgentRun))).all()
        agent_names = {r.agent_name for r in runs}
        assert specialist in agent_names
        specialist_run = next(r for r in runs if r.agent_name == specialist)
        assert specialist_run.status == "completed"
        assert specialist_run.outcome == "resolved"

        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.status == "resolved"
        assert ticket.ticket_number == result["ticket_number"]
        assert ticket.category == category
        assert ticket.requester_employee_id == employee_id

        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert {"SESSION_STARTED", "SUPERVISOR_DECISION", "AGENT_STARTED", "AGENT_COMPLETED",
            "TICKET_CREATED", "TICKET_STATUS_CHANGED", "SESSION_COMPLETED"} <= events


async def test_endpoint_route_slow_laptop_uses_real_disk_check(graph, provider, org_stub):
    """Scenario 5: EMP-041's laptop crawls; the endpoint specialist gathers
    real tool evidence (disk 96% full) before resolving with guidance."""
    summary = "Your disk is 96% full — I've shared cleanup steps; performance should recover."
    provider.enqueue(
        supervisor_decision(
            target_specialist="endpoint", category="endpoint", intent="slow laptop"
        ),
        specialist_tool_step("check_disk_space"),
        specialist_finish(
            agent="endpoint",
            outcome="resolved",
            findings=[{
                "agent": "endpoint",
                "summary": "Disk is 96% used with only 9 GB free",
                "severity": "medium",
                "tags": ["disk"],
            }],
            tools_used=["check_disk_space"],
            resolution_summary=summary,
        ),
        supervisor_decision(
            decision="run_workflow", target_specialist=None, workflow="resolution",
            category="endpoint",
        ),
    )

    result = await dispatcher.start_session(keys.EMP_SLOW_LAPTOP, "My laptop is crawling.")

    assert result["terminal_status"] == "resolved"
    assert summary in result["final_response"]

    async with db_session() as s:
        tool_call = (await s.scalars(select(ToolCall))).one()
        assert tool_call.tool_name == "check_disk_space"
        assert tool_call.status == "succeeded"
        # Params were pinned to the authenticated employee by the runner.
        assert tool_call.request["employee_id"] == keys.EMP_SLOW_LAPTOP
        # Real mockworld evidence, not a scripted number.
        assert tool_call.response["disk_used_pct"] == 96
        assert "96%" in tool_call.response["summary"]

        runs = (await s.scalars(select(AgentRun))).all()
        endpoint_run = next(r for r in runs if r.agent_name == "endpoint")
        assert endpoint_run.outcome == "resolved"
        assert endpoint_run.tools_used == ["check_disk_space"]

        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.status == "resolved"
        assert ticket.category == "endpoint"

        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert {"TOOL_CALLED", "TOOL_SUCCEEDED"} <= events


async def test_ticketing_route_with_no_tickets(graph, provider, org_stub):
    """A ticket-status query with no tickets on file answers directly through
    the deterministic ticket_status workflow — no specialist, no new ticket."""
    provider.enqueue(
        supervisor_decision(
            decision="run_workflow",
            target_specialist=None,
            workflow="ticket_status",
            category="ticketing",
            intent="ticket status query",
        ),
    )

    result = await dispatcher.start_session("EMP-023", "What's the status of my ticket?")

    assert result["pending"] is None
    assert result["terminal_status"] == "resolved"
    assert "don't see any support tickets" in result["final_response"]
    assert result["ticket_number"] is None

    async with db_session() as s:
        tickets = (await s.scalars(select(Ticket))).all()
        assert tickets == []
        runs = (await s.scalars(select(AgentRun))).all()
        # Only the supervisor ran — no specialist was needed.
        assert {r.agent_name for r in runs} == {"supervisor"}
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert "SESSION_COMPLETED" in events
    assert "AGENT_STARTED" not in events
