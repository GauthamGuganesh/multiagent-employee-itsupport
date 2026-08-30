"""Scenario 8: ambiguous request → ask_employee → the graph pauses on the
need-info interrupt, the employee's answer resumes it, and the case then
routes normally to a specialist and resolves."""
from sqlalchemy import select

from app.api import dispatcher
from app.db.base import db_session
from app.db.models import AuditEvent, Message, SupportSession
from tests.conftest import specialist_finish, supervisor_decision

EMPLOYEE = "EMP-024"
AMBIGUOUS_REQUEST = "Nothing works this morning."
QUESTION = "Could you tell me what exactly isn't working — sign-in, VPN, or your laptop?"
ANSWER = "Can't reach the VPN"
RESOLUTION = "Reset the VPN client profile; the tunnel is stable again."


async def test_ask_employee_pauses_then_resumes_to_resolution(graph, provider, org_stub):
    provider.enqueue(
        supervisor_decision(
            decision="ask_employee",
            target_specialist=None,
            category="other",
            intent="ambiguous request",
            question_for_employee=QUESTION,
        ),
    )

    first = await dispatcher.start_session(EMPLOYEE, AMBIGUOUS_REQUEST)
    session_id = first["session_id"]

    # Graph paused on the question interrupt; nothing terminal yet.
    assert first["pending"] == {"type": "question", "question": QUESTION}
    assert first["terminal_status"] is None
    assert first["assistant_message"] == QUESTION

    async with db_session() as s:
        session = await s.get(SupportSession, session_id)
        assert session.status == "waiting_employee"
        messages = (await s.scalars(
            select(Message).where(Message.session_id == session_id)
            .order_by(Message.created_at)
        )).all()
        assert [(m.role, m.content) for m in messages] == [
            ("employee", AMBIGUOUS_REQUEST),
            ("assistant", QUESTION),
        ]
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert "INFO_REQUESTED" in events
    assert "EMPLOYEE_REPLIED" not in events

    # The answer resumes the graph; the supervisor now routes to network.
    provider.enqueue(
        supervisor_decision(
            target_specialist="network", category="network", intent="VPN unreachable"
        ),
        specialist_finish(agent="network", outcome="resolved", resolution_summary=RESOLUTION),
        supervisor_decision(
            decision="run_workflow", target_specialist=None, workflow="resolution",
            category="network",
        ),
    )

    result = await dispatcher.continue_session(session_id, EMPLOYEE, ANSWER)

    assert result["pending"] is None
    assert result["terminal_status"] == "resolved"
    assert RESOLUTION in result["final_response"]
    assert result["ticket_number"] is not None

    async with db_session() as s:
        session = await s.get(SupportSession, session_id)
        assert session.status == "completed"
        assert session.terminal_status == "resolved"

        messages = (await s.scalars(
            select(Message).where(Message.session_id == session_id)
            .order_by(Message.created_at)
        )).all()
        pairs = [(m.role, m.content) for m in messages]
        # Question and answer are both part of the permanent transcript.
        assert ("assistant", QUESTION) in pairs
        assert ("employee", ANSWER) in pairs
        assert pairs.index(("assistant", QUESTION)) < pairs.index(("employee", ANSWER))

        events = (await s.scalars(select(AuditEvent))).all()
        replied = [e for e in events if e.event_type == "EMPLOYEE_REPLIED"]
        assert len(replied) == 1
        assert replied[0].actor == EMPLOYEE
        assert replied[0].payload["answer"] == ANSWER
        asked = next(e for e in events if e.event_type == "INFO_REQUESTED")
        assert asked.payload["question"] == QUESTION
        event_types = {e.event_type for e in events}
    assert {"SESSION_STARTED", "SUPERVISOR_DECISION", "AGENT_STARTED", "AGENT_COMPLETED",
            "TICKET_CREATED", "SESSION_COMPLETED"} <= event_types


async def test_physical_damage_reply_stops_an_endpoint_reinterview(graph, provider, org_stub):
    """A clear work-blocking display failure must never lead to another
    paraphrased question about replacement or repair."""
    provider.enqueue(
        supervisor_decision(
            decision="ask_employee",
            target_specialist=None,
            category="other",
            intent="device request",
            question_for_employee="What is wrong with your current laptop?",
        ),
    )
    first = await dispatcher.start_session("EMP-032", "I need a new laptop.")

    provider.enqueue(
        supervisor_decision(
            target_specialist="endpoint", category="endpoint", intent="physical device damage"
        ),
        specialist_finish(
            agent="endpoint",
            outcome="need_more_information",
            resolution_summary=None,
            question_for_employee="Can you describe the screen issue in more detail?",
        ),
    )
    result = await dispatcher.continue_session(
        first["session_id"],
        "EMP-032",
        "The screen is broken, only shows lines, and I cannot work.",
    )

    assert result["terminal_status"] == "escalated"
    assert "Platform Manager, Platform & IT Manager" in (result["final_response"] or "")
    # No additional model call was made to ask the endpoint's repeat question.
    assert len(provider.calls) == 3

    async with db_session() as session:
        messages = (await session.scalars(
            select(Message)
            .where(Message.session_id == first["session_id"], Message.role == "assistant")
            .order_by(Message.created_at)
        )).all()
        events = (await session.scalars(
            select(AuditEvent).where(AuditEvent.session_id == first["session_id"])
        )).all()
    assert all("screen issue in more detail" not in message.content for message in messages)
    assert any(event.event_type == "HUMAN_INTERVENTION" for event in events)
