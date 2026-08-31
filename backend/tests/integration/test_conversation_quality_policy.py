"""Production conversational policy exercised through the real graph.

The deterministic demonstration LLM drives the decisions, while every graph
node, tool, checkpoint, persistence write, and workflow remains real.
"""

from sqlalchemy import func, select

from app.api import dispatcher, routes_voice
from app.config import get_settings
from app.db.base import db_session
from app.db.models import AgentRun, Message, SupportSession, Ticket
from app.llm.provider import set_provider
from app.llm.scripted import ScriptedProvider


def _enable_production_policy(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "require_employee_resolution_confirmation", True)
    monkeypatch.setattr(settings, "create_ticket_for_resolved_sessions", False)


async def _reach_vpn_test_prompt(monkeypatch) -> dict:
    _enable_production_policy(monkeypatch)
    set_provider(ScriptedProvider())
    first = await dispatcher.start_session("EMP-021", "My VPN connects but keeps disconnecting.")
    assert first["terminal_status"] is None
    assert first["pending"]["type"] == "question"
    assert "more than one network" in first["assistant_message"]

    proposed = await dispatcher.continue_session(
        first["session_id"],
        "EMP-021",
        "It drops on both my home Wi-Fi and phone hotspot. It started after a password change.",
    )
    assert proposed["terminal_status"] is None
    assert proposed["pending"]["type"] == "question"
    assert "disconnect the VPN fully" in proposed["assistant_message"]
    assert "stays stable" in proposed["assistant_message"]
    return proposed


async def test_intermittent_vpn_diagnoses_tests_and_closes_only_after_employee_confirmation(
    graph, org_stub, monkeypatch
):
    proposed = await _reach_vpn_test_prompt(monkeypatch)
    final = await dispatcher.continue_session(
        proposed["session_id"], "EMP-021", "Yes, it is stable now and has not dropped again."
    )

    assert final["terminal_status"] == "resolved"
    assert final["ticket_number"] is None
    # Warm, jargon-free close.
    assert "closed this request" in final["final_response"]

    async with db_session() as session:
        ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
        messages = list(
            await session.scalars(
                select(Message)
                .where(Message.session_id == proposed["session_id"])
                .order_by(Message.created_at)
            )
        )
        runs = list(
            await session.scalars(
                select(AgentRun).where(AgentRun.session_id == proposed["session_id"])
            )
        )

    assert ticket_count == 0
    assert [message.role for message in messages] == [
        "employee", "assistant", "employee", "assistant", "employee", "assistant"
    ]
    assert {"supervisor", "network"} <= {run.agent_name for run in runs}
    assert {"check_vpn_status", "run_connectivity_diagnostics", "inspect_recent_vpn_session"} <= {
        tool for run in runs for tool in (run.tools_used or [])
    }


async def test_failed_vpn_test_returns_to_investigation_in_same_session(
    graph, org_stub, monkeypatch
):
    proposed = await _reach_vpn_test_prompt(monkeypatch)
    result = await dispatcher.continue_session(
        proposed["session_id"], "EMP-021", "No, it disconnected again after about two minutes."
    )

    assert result["session_id"] == proposed["session_id"]
    assert result["terminal_status"] is None
    assert result["ticket_number"] is None
    assert result["pending"]["type"] == "question"
    # A clearly-negative result keeps investigating, asking what actually happened.
    assert "happened" in result["assistant_message"].lower()


async def test_voice_vpn_turns_resume_one_canonical_support_session(
    graph, org_stub, monkeypatch
):
    _enable_production_policy(monkeypatch)
    set_provider(ScriptedProvider())
    bridge_token = "signed-demo-bridge-token-for-one-call"

    first = await routes_voice._resume_voice_session(
        "EMP-021", "My VPN connects but keeps disconnecting.", bridge_token
    )
    second = await routes_voice._resume_voice_session(
        "EMP-021",
        "It drops on home Wi-Fi and my phone hotspot after a password change.",
        bridge_token,
    )
    final = await routes_voice._resume_voice_session(
        "EMP-021", "Yes, it is stable now and has not dropped again.", bridge_token
    )

    assert first["session_id"] == second["session_id"] == final["session_id"]
    assert final["terminal_status"] == "resolved"
    async with db_session() as session:
        session_count = await session.scalar(select(func.count()).select_from(SupportSession))
        ticket_count = await session.scalar(select(func.count()).select_from(Ticket))
        messages = list(
            await session.scalars(
                select(Message).where(Message.session_id == first["session_id"])
            )
        )
    assert session_count == 1
    assert ticket_count == 0
    assert {message.source for message in messages} == {"voice"}
