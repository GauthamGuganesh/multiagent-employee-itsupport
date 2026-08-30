"""Structured-output resilience: retry-1/retry-2 recover the flow; exhaustion
yields a graceful AgentFailure and escalation — never a third retry, never a
crash (DESIGN §6.2)."""
from sqlalchemy import select

from app.api import dispatcher
from app.db.base import db_session
from app.db.models import AgentRun, AuditEvent, EscalationEvent
from tests.conftest import specialist_finish, supervisor_decision

REQUEST = "I can't sign in to my account."

# Fails validation for both SupervisorDecision and SpecialistStep — exactly
# like a malformed real model response.
INVALID = {"nonsense": "not a valid structured output"}


async def _events(session_id: str, event_type: str) -> list[AuditEvent]:
    async with db_session() as s:
        return list(
            (
                await s.scalars(
                    select(AuditEvent).where(
                        AuditEvent.session_id == session_id,
                        AuditEvent.event_type == event_type,
                    )
                )
            ).all()
        )


async def _agent_runs(session_id: str, agent_name: str) -> list[AgentRun]:
    async with db_session() as s:
        return list(
            (
                await s.scalars(
                    select(AgentRun)
                    .where(
                        AgentRun.session_id == session_id,
                        AgentRun.agent_name == agent_name,
                    )
                    .order_by(AgentRun.run_index)
                )
            ).all()
        )


async def test_supervisor_recovers_after_two_invalid_outputs(graph, provider, org_stub):
    provider.enqueue(
        INVALID,
        INVALID,
        supervisor_decision(target_specialist="identity"),
        specialist_finish(agent="identity", outcome="resolved", resolution_summary="Sign-in restored."),
        supervisor_decision(decision="run_workflow", target_specialist=None, workflow="resolution"),
    )

    result = await dispatcher.start_session("EMP-034", REQUEST)
    session_id = result["session_id"]

    # The flow proceeded normally after the two retries.
    assert result["terminal_status"] == "resolved"

    retries = await _events(session_id, "STRUCTURED_OUTPUT_RETRY")
    assert len(retries) == 2
    assert sorted(e.payload["attempt"] for e in retries) == [1, 2]
    assert all(e.actor == "supervisor" for e in retries)
    assert all(e.payload["schema"] == "SupervisorDecision" for e in retries)
    assert await _events(session_id, "STRUCTURED_OUTPUT_FAILED") == []

    supervisor_runs = await _agent_runs(session_id, "supervisor")
    assert supervisor_runs[0].status == "completed"
    assert supervisor_runs[0].structured_output_retries == 2


async def test_supervisor_structured_output_exhaustion_escalates(graph, provider, org_stub):
    provider.enqueue(INVALID, INVALID, INVALID)

    result = await dispatcher.start_session("EMP-034", REQUEST)
    session_id = result["session_id"]

    # 1 initial attempt + exactly 2 retries — never a third retry.
    assert len([c for c in provider.calls if c[0] == "SupervisorDecision"]) == 3
    assert len(await _events(session_id, "STRUCTURED_OUTPUT_RETRY")) == 2

    failed = await _events(session_id, "STRUCTURED_OUTPUT_FAILED")
    assert len(failed) == 1
    assert failed[0].actor == "supervisor"
    assert failed[0].payload == {"schema": "SupervisorDecision", "retries": 2}

    (supervisor_run,) = await _agent_runs(session_id, "supervisor")
    assert supervisor_run.status == "failed"
    assert supervisor_run.failure_type == "structured_output"
    assert supervisor_run.structured_output_retries == 2

    # Graceful terminal escalation with a friendly employee-facing message.
    assert result["terminal_status"] == "escalated"
    assert result["ticket_number"] is not None
    assert "safe execution limit" in result["final_response"]
    assert result["ticket_number"] in result["final_response"]

    async with db_session() as s:
        escalation = (
            await s.scalars(select(EscalationEvent).where(EscalationEvent.session_id == session_id))
        ).one()
    assert escalation.trigger == "structured_output_failure"


async def test_specialist_structured_output_exhaustion_returns_to_supervisor(
    graph, provider, org_stub
):
    provider.enqueue(
        supervisor_decision(target_specialist="identity"),
        INVALID,
        INVALID,
        INVALID,
        supervisor_decision(
            decision="run_workflow",
            target_specialist=None,
            workflow="escalation",
            reason="the identity specialist failed to produce a valid step",
        ),
    )

    result = await dispatcher.start_session("EMP-034", REQUEST)
    session_id = result["session_id"]

    # 1 attempt + 2 retries against the specialist schema, never a third retry.
    assert len([c for c in provider.calls if c[0] == "SpecialistStep"]) == 3

    failed = await _events(session_id, "STRUCTURED_OUTPUT_FAILED")
    assert len(failed) == 1
    assert failed[0].actor == "identity"
    assert failed[0].payload == {"schema": "SpecialistStep", "retries": 2}

    (identity_run,) = await _agent_runs(session_id, "identity")
    assert identity_run.status == "failed"
    assert identity_run.failure_type == "structured_output"
    assert identity_run.structured_output_retries == 2

    # Control returned to the supervisor, which routed to escalation.
    supervisor_runs = await _agent_runs(session_id, "supervisor")
    assert len(supervisor_runs) == 2
    assert supervisor_runs[1].status == "completed"
    assert supervisor_runs[1].outcome == "run_workflow"

    assert result["terminal_status"] == "escalated"
    assert result["ticket_number"] is not None
