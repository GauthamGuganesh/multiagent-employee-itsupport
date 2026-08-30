"""Security invariant: once the security specialist requires human
intervention, no path — misbehaving supervisor included — may auto-resolve.
Plus the structured-output guardrail: high risk + auto_resolve is
schema-invalid and either recovers via one bounded retry or degrades to a
graceful escalation, never a crash."""
from sqlalchemy import select

from app.api import dispatcher
from app.db.base import db_session
from app.db.models import AgentRun, AuditEvent, EscalationEvent, Ticket
from tests.conftest import specialist_finish, supervisor_decision

SUSPICIOUS_REQUEST = "Someone signed into my account from a device I don't recognize."
SECURITY_ESCALATION_REASON = "suspected account compromise requires the human security team"


async def test_misbehaving_supervisor_cannot_resolve_security_escalation(
    graph, provider, org_stub
):
    provider.enqueue(
        supervisor_decision(
            target_specialist="security", category="security", risk_level="high"
        ),
        specialist_finish(
            agent="security",
            outcome="escalation_required",
            findings=[{
                "agent": "security",
                "summary": "Unrecognized device session with no matching MFA challenge",
                "severity": "high",
                "tags": ["compromise"],
            }],
            escalation_reason=SECURITY_ESCALATION_REASON,
            resolution_summary=None,
        ),
        # MISBEHAVING but schema-valid decision: tries to silently auto-resolve.
        supervisor_decision(
            decision="run_workflow",
            target_specialist=None,
            workflow="resolution",
            category="security",
            risk_level="medium",
            autonomy_level="auto_resolve",
            reason="all clear, closing it out",
        ),
    )

    result = await dispatcher.start_session("EMP-030", SUSPICIOUS_REQUEST)

    # Code override wins: the session escalates, never resolves.
    assert result["terminal_status"] == "escalated"

    async with db_session() as s:
        tickets = (await s.scalars(select(Ticket))).all()
        assert len(tickets) == 1
        assert tickets[0].status == "escalated"
        assert tickets[0].security_related is True
        assert all(t.status != "resolved" for t in tickets)

        escalation = (await s.scalars(select(EscalationEvent))).one()
        assert escalation.trigger == "security"

        events = (await s.scalars(select(AuditEvent))).all()
        decision_events = [e for e in events if e.event_type == "SUPERVISOR_DECISION"]
        overridden = [e for e in decision_events if e.payload["overrides"]]
        assert len(overridden) == 1
        override_text = " ".join(overridden[0].payload["overrides"])
        assert "security" in override_text
        # The override rewrote the routed decision itself.
        assert overridden[0].payload["decision"]["workflow"] == "escalation"
        assert overridden[0].payload["decision"]["autonomy_level"] == "human_only"

        completed = next(e for e in events if e.event_type == "SESSION_COMPLETED")
        assert completed.payload["terminal_status"] == "escalated"


def _invalid_high_risk_auto_resolve() -> dict:
    # Violates the SupervisorDecision validator: high risk forbids auto_resolve.
    return supervisor_decision(risk_level="high", autonomy_level="auto_resolve")


async def test_repeatedly_invalid_supervisor_output_escalates_gracefully(
    graph, provider, org_stub
):
    provider.enqueue(
        _invalid_high_risk_auto_resolve(),
        _invalid_high_risk_auto_resolve(),
        _invalid_high_risk_auto_resolve(),
    )

    result = await dispatcher.start_session("EMP-031", SUSPICIOUS_REQUEST)

    assert result["terminal_status"] == "escalated"
    # Friendly automation-limit story, not a crash.
    assert "safe execution limit" in result["final_response"]

    # Initial attempt + exactly 2 retries — never a third retry.
    supervisor_calls = [c for c in provider.calls if c[0] == "SupervisorDecision"]
    assert len(supervisor_calls) == 3

    async with db_session() as s:
        events = (await s.scalars(select(AuditEvent))).all()
        retries = [e for e in events if e.event_type == "STRUCTURED_OUTPUT_RETRY"]
        assert len(retries) == 2
        failed = [e for e in events if e.event_type == "STRUCTURED_OUTPUT_FAILED"]
        assert len(failed) == 1
        assert failed[0].payload["schema"] == "SupervisorDecision"

        run = (await s.scalars(
            select(AgentRun).where(AgentRun.agent_name == "supervisor")
        )).one()
        assert run.status == "failed"
        assert run.failure_type == "structured_output"
        assert run.structured_output_retries == 2

        escalation = (await s.scalars(select(EscalationEvent))).one()
        assert escalation.trigger == "structured_output_failure"
        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.status == "escalated"


async def test_single_invalid_output_recovers_via_retry(graph, provider, org_stub):
    provider.enqueue(
        _invalid_high_risk_auto_resolve(),
        supervisor_decision(
            decision="run_workflow",
            target_specialist=None,
            workflow="escalation",
            category="security",
            risk_level="high",
            autonomy_level="human_only",
            reason="suspicious activity needs human review",
        ),
    )

    result = await dispatcher.start_session("EMP-033", SUSPICIOUS_REQUEST)

    assert result["terminal_status"] == "escalated"
    # Exactly two provider calls: the invalid attempt and the consumed retry.
    assert len([c for c in provider.calls if c[0] == "SupervisorDecision"]) == 2

    async with db_session() as s:
        events = (await s.scalars(select(AuditEvent))).all()
        retries = [e for e in events if e.event_type == "STRUCTURED_OUTPUT_RETRY"]
        assert len(retries) == 1
        assert retries[0].payload["schema"] == "SupervisorDecision"
        assert not any(e.event_type == "STRUCTURED_OUTPUT_FAILED" for e in events)

        run = (await s.scalars(
            select(AgentRun).where(AgentRun.agent_name == "supervisor")
        )).one()
        assert run.status == "completed"
        assert run.structured_output_retries == 1

        escalation = (await s.scalars(select(EscalationEvent))).one()
        assert escalation.trigger == "agent_recommendation"
