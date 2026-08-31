"""End-to-end regression tests for the offline demo conversation quality."""
import pytest

from app.api import dispatcher
from app.llm.provider import set_provider
from app.llm.scripted import ScriptedProvider


@pytest.mark.asyncio
async def test_phishing_report_is_a_useful_multiturn_security_conversation(graph, org_stub):
    set_provider(ScriptedProvider())

    first = await dispatcher.start_session(
        "EMP-034",
        "I received a suspicious email and my laptop is getting hot. What should I do?",
    )

    assert first["pending"] == {
        "type": "question",
        "question": (
            "Thanks for flagging this. Please don't open any links or attachments. "
            "Did you click or open anything, and can you share the sender or subject line?"
        ),
    }

    second = await dispatcher.continue_session(
        first["session_id"], "EMP-034", "I clicked a link from billing@unknown.example."
    )

    assert second["terminal_status"] == "escalated"
    assert "Platform Manager, Platform & IT Manager" in (second["final_response"] or "")
    assert second["ticket_number"] in (second["final_response"] or "")


@pytest.mark.asyncio
async def test_screen_damage_is_escalated_to_hardware_support_without_account_reply(graph, org_stub):
    set_provider(ScriptedProvider())

    result = await dispatcher.start_session(
        "EMP-034",
        "My laptop screen was damaged in an accident and I cannot work. I need a replacement.",
    )

    response = result["final_response"] or ""
    assert result["terminal_status"] == "escalated"
    assert "account" not in response.lower()
    assert result["ticket_number"] in response


@pytest.mark.asyncio
async def test_completed_request_rejects_an_unrelated_follow_up(graph, org_stub):
    set_provider(ScriptedProvider())
    completed = await dispatcher.start_session(
        "EMP-034", "My laptop screen was damaged in an accident and I cannot work."
    )

    follow_up = await dispatcher.continue_session(
        completed["session_id"], "EMP-034", "Also, I cannot sign in."
    )

    assert follow_up["status_code"] == 409
    assert "start a new request" in follow_up["error"]
