"""Registry-level privilege gate (DESIGN 6.6): privileged tools refuse to run
outside the confirmation/approval workflows; every call — blocked, invalid,
unknown, or executed — is persisted as a ToolCall row."""
from sqlalchemy import select

from app.db.base import db_session
from app.db.models import AuditEvent, ToolCall
from app.org import keys
from app.tools.mockworld import get_world
from app.tools.registry import ToolContext, execute_tool

SESSION_ID = "sess-registry"


def _ctx(**overrides) -> ToolContext:
    base = dict(
        session_id=SESSION_ID,
        employee_id=keys.EMP_LOCKED_OUT,
        agent_name="identity",
        authorized_privileged=False,
    )
    base.update(overrides)
    return ToolContext(**base)


async def _tool_calls() -> list[ToolCall]:
    async with db_session() as s:
        return list((await s.scalars(select(ToolCall))).all())


async def test_privileged_tool_blocked_without_authorization(db):
    # EMP-034 starts locked in the mock world.
    assert get_world().state_for(keys.EMP_LOCKED_OUT)["account"]["status"] == "locked"

    result = await execute_tool(
        "unlock_account", {"employee_id": keys.EMP_LOCKED_OUT}, _ctx()
    )

    assert result.status == "failed"
    assert result.error == "privileged_tool_blocked"
    assert result.tool_name == "unlock_account"
    assert "confirmation or approval workflow" in result.response_summary

    # The gate is code, not prompt: the world did NOT mutate.
    account = get_world().state_for(keys.EMP_LOCKED_OUT)["account"]
    assert account["status"] == "locked"
    assert account["locked_reason"] == "too many failed password attempts"

    # The refusal is persisted and audited.
    rows = await _tool_calls()
    assert len(rows) == 1
    assert rows[0].tool_name == "unlock_account"
    assert rows[0].status == "failed"
    assert rows[0].error == "privileged_tool_blocked"
    assert rows[0].session_id == SESSION_ID
    async with db_session() as s:
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert {"TOOL_CALLED", "TOOL_FAILED"} <= events


async def test_privileged_tool_executes_when_authorized(db):
    result = await execute_tool(
        "unlock_account",
        {"employee_id": keys.EMP_LOCKED_OUT},
        _ctx(authorized_privileged=True),
    )

    assert result.status == "succeeded"
    assert result.error is None
    assert get_world().state_for(keys.EMP_LOCKED_OUT)["account"]["status"] == "active"

    rows = await _tool_calls()
    assert len(rows) == 1
    assert rows[0].status == "succeeded"
    assert rows[0].response["status"] == "active"
    async with db_session() as s:
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert {"TOOL_CALLED", "TOOL_SUCCEEDED"} <= events


async def test_unprivileged_tool_needs_no_authorization(db):
    result = await execute_tool(
        "get_account_status", {"employee_id": keys.EMP_LOCKED_OUT}, _ctx()
    )
    assert result.status == "succeeded"
    assert result.response_summary.startswith(f"Account for {keys.EMP_LOCKED_OUT} is locked")


async def test_unknown_tool_fails_safely(db):
    result = await execute_tool("melt_datacenter", {}, _ctx())
    assert result.status == "failed"
    assert result.error == "unknown tool: melt_datacenter"

    rows = await _tool_calls()
    assert len(rows) == 1
    assert rows[0].status == "failed"


async def test_invalid_params_fail_validation(db):
    # get_account_status requires employee_id.
    result = await execute_tool("get_account_status", {}, _ctx())
    assert result.status == "failed"
    assert result.error.startswith("invalid params:")

    rows = await _tool_calls()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error.startswith("invalid params:")


async def test_invalid_params_on_privileged_tool_authorized(db):
    # Even authorized calls validate input before touching the world.
    result = await execute_tool(
        "unlock_account", {}, _ctx(authorized_privileged=True)
    )
    assert result.status == "failed"
    assert result.error.startswith("invalid params:")
    assert get_world().state_for(keys.EMP_LOCKED_OUT)["account"]["status"] == "locked"
