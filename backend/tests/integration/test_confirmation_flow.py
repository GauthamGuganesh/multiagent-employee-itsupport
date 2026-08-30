"""Scenario 1 & 11: privileged action with privilege present — explicit
confirmation gates execution; a decline never executes."""
from sqlalchemy import select

from app.api import dispatcher
from app.db.base import db_session
from app.db.models import ActionConfirmation, ActionExecution, AuditEvent, Ticket
from app.org import keys
from tests.conftest import specialist_finish, specialist_tool_step, supervisor_decision

LOCKED_REQUEST = "I'm locked out of my account after mistyping my password."


def _queue_locked_account_flow(provider):
    """Supervisor → identity (status check → unlock recommendation) → confirmation."""
    provider.enqueue(
        supervisor_decision(target_specialist="identity"),
        specialist_tool_step("get_account_status"),
        specialist_finish(
            agent="identity",
            outcome="approval_required",
            findings=[{
                "agent": "identity",
                "summary": "Account is locked after repeated failed password attempts",
                "severity": "medium",
                "tags": ["lockout"],
            }],
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
        supervisor_decision(
            decision="run_workflow", target_specialist=None, workflow="confirmation"
        ),
    )


async def test_confirmed_action_executes(graph, provider, org_stub):
    org_stub["grants"].add(keys.PRIV_SELF_ACCOUNT_UNLOCK)
    _queue_locked_account_flow(provider)

    first = await dispatcher.start_session(keys.EMP_LOCKED_OUT, LOCKED_REQUEST)
    session_id = first["session_id"]

    # Graph paused on the confirmation interrupt with the exact action summary.
    assert first["pending"] is not None
    assert first["pending"]["type"] == "confirmation"
    assert "Unlock the account" in first["pending"]["action_summary"]
    assert first["terminal_status"] is None

    result = await dispatcher.continue_session(session_id, keys.EMP_LOCKED_OUT, True)
    assert result["terminal_status"] == "resolved"
    assert result["ticket_number"] is not None

    async with db_session() as s:
        confirmation = (await s.scalars(select(ActionConfirmation))).one()
        assert confirmation.confirmed is True
        execution = (await s.scalars(select(ActionExecution))).one()
        assert execution.action_key == "unlock_account"
        assert execution.status == "succeeded"
        assert execution.confirmation_id == confirmation.id
        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.status == "resolved"
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert {"USER_CONFIRMATION_REQUESTED", "USER_CONFIRMED", "ACTION_EXECUTED",
            "SESSION_COMPLETED"} <= events

    # The mock world actually changed.
    from app.tools.mockworld import get_world

    assert get_world().state_for(keys.EMP_LOCKED_OUT)["account"]["status"] == "active"


async def test_declined_action_never_executes(graph, provider, org_stub):
    org_stub["grants"].add(keys.PRIV_SELF_ACCOUNT_UNLOCK)
    _queue_locked_account_flow(provider)
    # After the decline, the supervisor wraps up gracefully.
    provider.enqueue(
        supervisor_decision(
            decision="close_session",
            target_specialist=None,
            message_to_employee="Understood — I won't unlock the account. It stays locked.",
        )
    )

    first = await dispatcher.start_session(keys.EMP_LOCKED_OUT, LOCKED_REQUEST)
    result = await dispatcher.continue_session(first["session_id"], keys.EMP_LOCKED_OUT, False)

    assert result["terminal_status"] == "resolved"
    async with db_session() as s:
        confirmation = (await s.scalars(select(ActionConfirmation))).one()
        assert confirmation.confirmed is False
        executions = (await s.scalars(select(ActionExecution))).all()
        assert executions == []
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert "USER_DECLINED" in events
    assert "ACTION_EXECUTED" not in events

    from app.tools.mockworld import get_world

    assert get_world().state_for(keys.EMP_LOCKED_OUT)["account"]["status"] == "locked"
