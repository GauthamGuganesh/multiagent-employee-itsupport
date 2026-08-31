"""Loop prevention: adversarial network↔security ping-pong trips the
signature guard well before per-turn budgets would, and the cycle budget is a
hard in-code bound (DESIGN §6.1/§6.3/§6.4)."""
from sqlalchemy import select

from app.api import dispatcher
from app.config import get_settings
from app.db.base import db_session
from app.db.models import AgentRun, AuditEvent, EscalationEvent, Ticket
from tests.conftest import specialist_finish, supervisor_decision

REQUEST = "My VPN keeps dropping and my recent sessions look strange."

FLAGGED_FINDING = {
    "agent": "network",
    "summary": "Recent VPN session originated from an unrecognized IP address",
    "severity": "high",
    "tags": ["vpn", "suspicious-ip"],
}


def _route(target: str) -> dict:
    return supervisor_decision(target_specialist=target, category="network", intent="vpn issue")


def _handoff(agent: str, target: str, findings: list | None = None) -> dict:
    return specialist_finish(
        agent=agent,
        outcome="handoff_recommended",
        findings=findings or [],
        resolution_summary=None,
        handoff={
            "target_agent": target,
            "reason": f"{agent} believes this belongs to the {target} domain",
            "findings": [],
            "confidence": 0.8,
        },
    )


async def test_ping_pong_handoffs_trip_loop_signature_guard(graph, provider, org_stub):
    settings = get_settings()
    # Findings stay stable after the first investigation: every later handoff
    # repeats the same unresolved routing decision with no new evidence.
    provider.enqueue(
        _route("network"),
        _handoff("network", "security", findings=[FLAGGED_FINDING]),
        _route("security"),
        _handoff("security", "network"),
        _route("network"),
        _handoff("network", "security"),
        _route("security"),  # same signature as cycle 2 — 1st repeat
        _handoff("security", "network"),
        _route("network"),  # same signature as cycle 3 — 1st repeat
        _handoff("network", "security"),
        _route("security"),  # 2nd repeat of the cycle-2 signature → guard trips
    )

    result = await dispatcher.start_session("EMP-014", REQUEST)
    session_id = result["session_id"]

    # Every scripted decision was consumed — the guard, not an empty queue,
    # ended the run.
    assert len(provider.calls) == 11

    async with db_session() as s:
        loop_events = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.session_id == session_id,
                    AuditEvent.event_type == "LOOP_GUARD_TRIGGERED",
                )
            )
        ).all()
        escalation_events = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.session_id == session_id,
                    AuditEvent.event_type == "ESCALATION_TRIGGERED",
                )
            )
        ).all()
        supervisor_runs = (
            await s.scalars(
                select(AgentRun)
                .where(AgentRun.session_id == session_id, AgentRun.agent_name == "supervisor")
                .order_by(AgentRun.run_index)
            )
        ).all()
        escalation = (
            await s.scalars(select(EscalationEvent).where(EscalationEvent.session_id == session_id))
        ).one()
        ticket = (await s.scalars(select(Ticket).where(Ticket.session_id == session_id))).one()

    assert len(loop_events) == 1
    assert loop_events[0].payload["kind"] == "loop_signature"

    # Hard termination BEFORE the cycle budget would have allowed more cycles.
    assert len(supervisor_runs) == 6
    assert len(supervisor_runs) < settings.max_supervisor_cycles
    assert supervisor_runs[-1].outcome == "loop_guard"
    assert supervisor_runs[-1].loop_guard_triggered is True

    # Terminal escalation with findings preserved and a friendly message.
    assert result["terminal_status"] == "escalated"
    assert escalation.trigger == "loop_guard"
    assert ticket.status == "escalated"
    assert len(escalation_events) == 1
    assert escalation_events[0].payload["findings_preserved"] == 1
    # Empathetic, jargon-free handoff copy — no internal mechanics exposed.
    assert "take it further" in result["final_response"]
    assert not any(
        j in result["final_response"].lower()
        for j in ("safe execution limit", "automated investigation", "loop", "budget")
    )
    assert result["ticket_number"] in result["final_response"]


async def test_cycle_budget_exhaustion_escalates(graph, provider, org_stub, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_supervisor_cycles", 2)

    # Decisions that keep routing without resolving: cycle 3 is denied by the
    # budget before any further LLM call.
    provider.enqueue(
        supervisor_decision(target_specialist="identity"),
        specialist_finish(agent="identity", outcome="unable_to_resolve", resolution_summary=None),
        supervisor_decision(target_specialist="identity"),
        specialist_finish(agent="identity", outcome="unable_to_resolve", resolution_summary=None),
    )

    result = await dispatcher.start_session("EMP-034", "I still can't log in.")
    session_id = result["session_id"]

    assert len(provider.calls) == 4  # the tripped cycle never invoked the LLM

    async with db_session() as s:
        loop_events = (
            await s.scalars(
                select(AuditEvent).where(
                    AuditEvent.session_id == session_id,
                    AuditEvent.event_type == "LOOP_GUARD_TRIGGERED",
                )
            )
        ).all()
        supervisor_runs = (
            await s.scalars(
                select(AgentRun).where(
                    AgentRun.session_id == session_id, AgentRun.agent_name == "supervisor"
                )
            )
        ).all()
        escalation = (
            await s.scalars(select(EscalationEvent).where(EscalationEvent.session_id == session_id))
        ).one()

    assert len(loop_events) == 1
    assert loop_events[0].payload["kind"] == "cycle_budget"
    assert len(supervisor_runs) == 2  # the denied third cycle never became a run
    assert escalation.trigger == "budget_exhausted"
    assert result["terminal_status"] == "escalated"
    assert "take it further" in result["final_response"]
    assert "safe execution limit" not in result["final_response"].lower()
    assert result["ticket_number"] in result["final_response"]
