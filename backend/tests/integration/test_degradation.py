"""Safe degradation (DESIGN §10.5): tool timeout → failed ToolResult and
escalation; Neo4j outage → privilege checks fail closed; any graph exception →
the dispatcher's out-of-graph fail-safe escalation, never a bare 500."""
import asyncio

from langgraph.errors import GraphRecursionError
from sqlalchemy import select

from app.api import dispatcher
from app.db import repos
from app.db.base import db_session
from app.db.models import (
    ActionConfirmation,
    ActionExecution,
    AgentRun,
    AuditEvent,
    EscalationEvent,
    Ticket,
    ToolCall,
)
from app.org import keys
from app.tools import registry
from tests.conftest import specialist_finish, specialist_tool_step, supervisor_decision


async def test_tool_timeout_degrades_to_failed_result_and_escalation(
    graph, provider, org_stub, monkeypatch
):
    monkeypatch.setattr(registry, "TOOL_TIMEOUT_SECONDS", 0.05)
    spec = registry.get_tool("check_vpn_status")

    async def slow_handler(inp, ctx):
        await asyncio.sleep(5)
        raise AssertionError("handler must be cancelled by the registry timeout")

    monkeypatch.setattr(spec, "handler", slow_handler)

    provider.enqueue(
        supervisor_decision(target_specialist="network", category="network", intent="vpn down"),
        specialist_tool_step("check_vpn_status"),
        specialist_finish(
            agent="network",
            outcome="unable_to_resolve",
            resolution_summary=None,
            reasoning_summary="VPN diagnostics timed out; tunnel state cannot be verified.",
        ),
        supervisor_decision(
            decision="run_workflow",
            target_specialist=None,
            workflow="escalation",
            category="network",
            reason="diagnostics unavailable",
        ),
    )

    result = await dispatcher.start_session(keys.EMP_VPN_SUSPECT, "My VPN will not connect.")
    session_id = result["session_id"]

    async with db_session() as s:
        call = (await s.scalars(select(ToolCall).where(ToolCall.session_id == session_id))).one()
        tool_failed = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.session_id == session_id,
                    AuditEvent.event_type == "TOOL_FAILED",
                )
            )
        ).all()
        network_run = (
            await s.scalars(
                select(AgentRun).where(
                    AgentRun.session_id == session_id, AgentRun.agent_name == "network"
                )
            )
        ).one()
        escalation = (
            await s.scalars(select(EscalationEvent).where(EscalationEvent.session_id == session_id))
        ).one()

    assert call.tool_name == "check_vpn_status"
    assert call.status == "failed"
    assert call.error == "timeout"
    assert len(tool_failed) == 1
    assert tool_failed[0].payload["tool"] == "check_vpn_status"
    assert tool_failed[0].payload["error"] == "timeout"

    # The specialist observed the failure, finished gracefully, and the
    # supervisor escalated — no crash, no retry storm.
    assert network_run.status == "completed"
    assert network_run.outcome == "unable_to_resolve"
    assert escalation.trigger == "agent_recommendation"
    assert result["terminal_status"] == "escalated"
    assert result["ticket_number"] is not None


async def test_neo4j_outage_fails_closed_during_confirmation(graph, provider, org_stub):
    # Even a genuinely entitled employee is refused when the directory cannot
    # prove the privilege: access is never assumed.
    org_stub["grants"].add(keys.PRIV_SELF_ACCOUNT_UNLOCK)
    org_stub["unavailable"] = True

    provider.enqueue(
        supervisor_decision(target_specialist="identity"),
        specialist_tool_step("get_account_status"),
        specialist_finish(
            agent="identity",
            outcome="approval_required",
            resolution_summary=None,
            requested_action={
                "action_key": "unlock_account",
                "summary": f"Unlock the account for {keys.EMP_LOCKED_OUT}.",
                "privilege_key": keys.PRIV_SELF_ACCOUNT_UNLOCK,
                "system_key": keys.SYSTEM_OKTA,
                "params": {},
                "risk_level": "medium",
            },
        ),
        supervisor_decision(decision="run_workflow", target_specialist=None, workflow="confirmation"),
    )

    result = await dispatcher.start_session(keys.EMP_LOCKED_OUT, "I'm locked out of my account.")
    session_id = result["session_id"]

    # Fail-closed: never reached the confirmation interrupt, escalated instead.
    assert result["pending"] is None
    assert result["terminal_status"] == "escalated"
    assert result["ticket_number"] is not None

    async with db_session() as s:
        escalation = (
            await s.scalars(select(EscalationEvent).where(EscalationEvent.session_id == session_id))
        ).one()
        executions = (await s.scalars(select(ActionExecution))).all()
        confirmations = (await s.scalars(select(ActionConfirmation))).all()
        events = {
            e.event_type
            for e in (
                await s.scalars(select(AuditEvent).where(AuditEvent.session_id == session_id))
            ).all()
        }

    assert escalation.trigger == "infrastructure"
    assert "unavailable" in escalation.reason
    assert executions == []
    assert confirmations == []
    assert "USER_CONFIRMATION_REQUESTED" not in events
    assert "ACTION_EXECUTED" not in events

    # The world never changed: the account stays locked.
    from app.tools.mockworld import get_world

    assert get_world().state_for(keys.EMP_LOCKED_OUT)["account"]["status"] == "locked"


async def test_dispatcher_fail_safe_on_graph_exception(graph, provider):
    class _BoomGraph:
        async def ainvoke(self, *args, **kwargs):
            raise GraphRecursionError("recursion limit reached")

        async def aget_state(self, config):
            raise AssertionError("aget_state must not be reached on the failure path")

    dispatcher.set_graph(_BoomGraph())

    result = await dispatcher.start_session("EMP-034", "My laptop fan sounds like a jet engine.")
    session_id = result["session_id"]

    assert result["terminal_status"] == "failed"
    assert result["pending"] is None
    assert result["ticket_number"] is not None
    assert "went wrong" in result["final_response"]

    async with db_session() as s:
        ticket = (await s.scalars(select(Ticket).where(Ticket.session_id == session_id))).one()
        escalation = (
            await s.scalars(select(EscalationEvent).where(EscalationEvent.session_id == session_id))
        ).one()
        escalation_events = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.session_id == session_id,
                    AuditEvent.event_type == "ESCALATION_TRIGGERED",
                )
            )
        ).all()

    assert ticket.status == "escalated"
    assert ticket.ticket_number == result["ticket_number"]
    assert ticket.current_team_key == keys.SUPPORT_IT
    assert escalation.trigger == "infrastructure"
    assert len(escalation_events) == 1
    assert escalation_events[0].payload["fail_safe"] is True

    session = await repos.get_support_session(session_id)
    assert session.terminal_status == "failed"
    assert session.status == "failed"
