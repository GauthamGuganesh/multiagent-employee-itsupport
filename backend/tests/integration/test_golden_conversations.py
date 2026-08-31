"""Golden end-to-end conversations for the offline demonstration provider.

The data set captures useful employee outcomes, rather than only graph edges:
clarification when a symptom is ambiguous, diagnosis before resolution, safe
confirmation, and a network-to-security handoff when evidence warrants it.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api import dispatcher
from app.config import get_settings
from app.db.base import db_session
from app.db.models import AgentRun
from app.llm.provider import set_provider
from tests.scripted_provider import ScriptedProvider
from app.org import keys

CASES = json.loads(
    (Path(__file__).parents[1] / "golden" / "support_conversations.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
async def test_golden_support_conversation(graph, org_stub, case, monkeypatch):
    set_provider(ScriptedProvider())
    if case.get("production_policy"):
        settings = get_settings()
        monkeypatch.setattr(settings, "require_employee_resolution_confirmation", True)
        monkeypatch.setattr(settings, "create_ticket_for_resolved_sessions", False)
    if case["id"] == "identity-lockout-confirmation":
        org_stub["grants"].add(keys.PRIV_SELF_ACCOUNT_UNLOCK)

    first = await dispatcher.start_session(case["employee_id"], case["request"])

    if expected_pending := case.get("expected_initial_pending"):
        assert first["pending"] is not None, first
        assert first["pending"]["type"] == expected_pending
        assert first["assistant_message"]

    if case.get("expected_pending"):
        assert first["pending"] is not None, first
        assert first["pending"]["type"] == case["expected_pending"]
        result = first
    elif replies := case.get("replies"):
        result = first
        for reply in replies:
            assert result["pending"] is not None, result
            result = await dispatcher.continue_session(
                first["session_id"], case["employee_id"], reply
            )
    elif reply := case.get("reply"):
        result = await dispatcher.continue_session(first["session_id"], case["employee_id"], reply)
    else:
        result = first

    if expected_terminal := case.get("expected_terminal"):
        assert result["terminal_status"] == expected_terminal
        if case.get("expected_ticket", True):
            assert result["ticket_number"]
        else:
            assert result["ticket_number"] is None
        assert result["final_response"]

    async with db_session() as session:
        agent_rows = list(
            await session.scalars(
                select(AgentRun).where(AgentRun.session_id == first["session_id"])
            )
        )
    agent_names = {row.agent_name for row in agent_rows}
    assert set(case["expected_agents"]) <= agent_names, [
        (row.agent_name, row.outcome, row.reasoning_summary, row.failure_detail) for row in agent_rows
    ]
