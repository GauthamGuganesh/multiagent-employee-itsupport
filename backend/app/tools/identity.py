"""Identity-domain tools over the mock world.

Read-only diagnostics (account status, auth events) are unprivileged; the
mutating tools (unlock, password reset, session revoke) are privileged and run
only through the confirmation/approval workflows via the registry gate. The
password reset tool issues a link — it never returns or sets a password value.
"""
from typing import Any

from pydantic import BaseModel

from app.org import keys
from app.tools.mockworld import get_world
from app.tools.registry import ToolContext, ToolSpec, register


class GetAccountStatusInput(BaseModel):
    employee_id: str


class GetAccountStatusOutput(BaseModel):
    employee_id: str
    status: str
    locked_reason: str | None
    mfa_enrolled: bool
    last_password_change_days: int
    active_sessions: int
    summary: str


async def _get_account_status(
    inp: GetAccountStatusInput, ctx: ToolContext
) -> GetAccountStatusOutput:
    account = get_world().state_for(inp.employee_id)["account"]
    if account["status"] == "locked":
        summary = f"Account for {inp.employee_id} is locked: {account['locked_reason']}."
    else:
        summary = (
            f"Account for {inp.employee_id} is active with "
            f"{account['active_sessions']} active session(s)."
        )
    return GetAccountStatusOutput(
        employee_id=inp.employee_id,
        status=account["status"],
        locked_reason=account["locked_reason"],
        mfa_enrolled=account["mfa_enrolled"],
        last_password_change_days=account["last_password_change_days"],
        active_sessions=account["active_sessions"],
        summary=summary,
    )


register(
    ToolSpec(
        name="get_account_status",
        description=(
            "Look up the employee's identity-provider account: lock status and "
            "reason, MFA enrollment, days since last password change, and active "
            "session count. Read-only."
        ),
        domain="identity",
        input_model=GetAccountStatusInput,
        output_model=GetAccountStatusOutput,
        handler=_get_account_status,
        system_key=keys.SYSTEM_OKTA,
    )
)


class GetRecentAuthEventsInput(BaseModel):
    employee_id: str
    limit: int = 10


class GetRecentAuthEventsOutput(BaseModel):
    employee_id: str
    events: list[dict[str, Any]]
    unusual_count: int
    summary: str


async def _get_recent_auth_events(
    inp: GetRecentAuthEventsInput, ctx: ToolContext
) -> GetRecentAuthEventsOutput:
    all_events = get_world().state_for(inp.employee_id)["auth_events"]
    events = list(reversed(all_events))[: max(inp.limit, 0)]
    unusual_count = sum(1 for e in events if e.get("unusual"))
    summary = (
        f"Retrieved {len(events)} recent auth event(s) for {inp.employee_id}; "
        f"{unusual_count} flagged as unusual."
    )
    return GetRecentAuthEventsOutput(
        employee_id=inp.employee_id,
        events=events,
        unusual_count=unusual_count,
        summary=summary,
    )


register(
    ToolSpec(
        name="get_recent_auth_events",
        description=(
            "List the employee's most recent authentication events (logins, MFA "
            "challenges/enrollments, password changes), newest first, each with "
            "timestamp, IP, location, success, and an unusual flag; also returns "
            "how many are unusual. Read-only."
        ),
        domain="identity",
        input_model=GetRecentAuthEventsInput,
        output_model=GetRecentAuthEventsOutput,
        handler=_get_recent_auth_events,
        system_key=keys.SYSTEM_OKTA,
    )
)


class UnlockAccountInput(BaseModel):
    employee_id: str


class UnlockAccountOutput(BaseModel):
    employee_id: str
    status: str
    summary: str


async def _unlock_account(inp: UnlockAccountInput, ctx: ToolContext) -> UnlockAccountOutput:
    world = get_world()
    account = world.state_for(inp.employee_id)["account"]
    if account["status"] != "locked":
        raise ValueError(f"account for {inp.employee_id} is not locked")
    world.unlock_account(inp.employee_id)
    return UnlockAccountOutput(
        employee_id=inp.employee_id,
        status="active",
        summary=f"Unlocked the account for {inp.employee_id}; status is now active.",
    )


register(
    ToolSpec(
        name="unlock_account",
        description=(
            "Unlock the employee's identity-provider account after a lockout. "
            "Fails if the account is not currently locked."
        ),
        domain="identity",
        input_model=UnlockAccountInput,
        output_model=UnlockAccountOutput,
        handler=_unlock_account,
        privileged=True,
        privilege_key=keys.PRIV_SELF_ACCOUNT_UNLOCK,
        system_key=keys.SYSTEM_OKTA,
        risk_level="medium",
    )
)


class ResetPasswordInput(BaseModel):
    employee_id: str


class ResetPasswordOutput(BaseModel):
    employee_id: str
    reset_link_issued: bool
    note: str
    summary: str


async def _reset_password(inp: ResetPasswordInput, ctx: ToolContext) -> ResetPasswordOutput:
    get_world().reset_password(inp.employee_id)
    return ResetPasswordOutput(
        employee_id=inp.employee_id,
        reset_link_issued=True,
        note=(
            "A password reset link was issued to the employee's verified "
            "contact; passwords are never returned or set directly."
        ),
        summary=f"Issued a password reset link for {inp.employee_id}.",
    )


register(
    ToolSpec(
        name="reset_password",
        description=(
            "Issue a self-service password reset link to the employee's verified "
            "contact and record the password change. Never returns or sets a "
            "password value."
        ),
        domain="identity",
        input_model=ResetPasswordInput,
        output_model=ResetPasswordOutput,
        handler=_reset_password,
        privileged=True,
        privilege_key=keys.PRIV_SELF_PASSWORD_RESET,
        system_key=keys.SYSTEM_OKTA,
        risk_level="medium",
    )
)


class RevokeSessionsInput(BaseModel):
    employee_id: str


class RevokeSessionsOutput(BaseModel):
    employee_id: str
    revoked_count: int
    summary: str


async def _revoke_sessions(inp: RevokeSessionsInput, ctx: ToolContext) -> RevokeSessionsOutput:
    revoked = get_world().revoke_sessions(inp.employee_id)
    return RevokeSessionsOutput(
        employee_id=inp.employee_id,
        revoked_count=revoked,
        summary=f"Revoked {revoked} active session(s) for {inp.employee_id}.",
    )


register(
    ToolSpec(
        name="revoke_sessions",
        description=(
            "Sign the employee out everywhere by revoking all of their active "
            "sessions. Reports how many sessions were revoked."
        ),
        domain="identity",
        input_model=RevokeSessionsInput,
        output_model=RevokeSessionsOutput,
        handler=_revoke_sessions,
        privileged=True,
        privilege_key=keys.PRIV_SELF_SESSION_REVOKE,
        system_key=keys.SYSTEM_OKTA,
        risk_level="medium",
    )
)
