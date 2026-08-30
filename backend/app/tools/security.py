"""Security-domain tools over the mock world.

Reading SIEM events is unprivileged; forcibly revoking sessions and
quarantining a device mutate state and are privileged (registry-gated, run
only via the confirmation/approval workflows). Flagging an account for review
and notifying the security team are internal safety actions the security
specialist may take directly — they alert humans, they never restrict access.
"""
from typing import Any

from pydantic import BaseModel

from app.contracts.enums import RISK_ORDER
from app.org import keys
from app.tools.mockworld import get_world
from app.tools.registry import ToolContext, ToolSpec, register


class GetRecentSecurityEventsInput(BaseModel):
    employee_id: str


class GetRecentSecurityEventsOutput(BaseModel):
    employee_id: str
    events: list[dict[str, Any]]
    max_severity: str | None
    summary: str


async def _get_recent_security_events(
    inp: GetRecentSecurityEventsInput, ctx: ToolContext
) -> GetRecentSecurityEventsOutput:
    events = list(get_world().state_for(inp.employee_id)["security_events"])
    max_severity: str | None = None
    for event in events:
        severity = event.get("severity", "low")
        if max_severity is None or RISK_ORDER.get(severity, 0) > RISK_ORDER.get(max_severity, 0):
            max_severity = severity
    if events:
        summary = (
            f"Found {len(events)} security event(s) for {inp.employee_id}; "
            f"highest severity is {max_severity}."
        )
    else:
        summary = f"No security events on record for {inp.employee_id}."
    return GetRecentSecurityEventsOutput(
        employee_id=inp.employee_id,
        events=events,
        max_severity=max_severity,
        summary=summary,
    )


register(
    ToolSpec(
        name="get_recent_security_events",
        description=(
            "List the employee's recent SIEM security events (impossible travel, "
            "new MFA device, etc.), each with timestamp, type, detail, and "
            "severity; also returns the maximum severity seen. Read-only."
        ),
        domain="security",
        input_model=GetRecentSecurityEventsInput,
        output_model=GetRecentSecurityEventsOutput,
        handler=_get_recent_security_events,
        system_key=keys.SYSTEM_SIEM,
    )
)


class RevokeActiveSessionsInput(BaseModel):
    employee_id: str


class RevokeActiveSessionsOutput(BaseModel):
    employee_id: str
    revoked_count: int
    summary: str


async def _revoke_active_sessions(
    inp: RevokeActiveSessionsInput, ctx: ToolContext
) -> RevokeActiveSessionsOutput:
    revoked = get_world().revoke_sessions(inp.employee_id)
    return RevokeActiveSessionsOutput(
        employee_id=inp.employee_id,
        revoked_count=revoked,
        summary=(
            f"Revoked {revoked} active session(s) for {inp.employee_id} as a "
            "security containment measure."
        ),
    )


register(
    ToolSpec(
        name="revoke_active_sessions",
        description=(
            "Security containment: immediately terminate every active session "
            "for the employee, forcing re-authentication everywhere. Reports how "
            "many sessions were revoked."
        ),
        domain="security",
        input_model=RevokeActiveSessionsInput,
        output_model=RevokeActiveSessionsOutput,
        handler=_revoke_active_sessions,
        privileged=True,
        privilege_key=keys.PRIV_SELF_SESSION_REVOKE,
        system_key=keys.SYSTEM_OKTA,
        risk_level="high",
    )
)


class QuarantineDeviceInput(BaseModel):
    employee_id: str


class QuarantineDeviceOutput(BaseModel):
    employee_id: str
    quarantined: bool
    summary: str


async def _quarantine_device(
    inp: QuarantineDeviceInput, ctx: ToolContext
) -> QuarantineDeviceOutput:
    get_world().quarantine_device(inp.employee_id)
    return QuarantineDeviceOutput(
        employee_id=inp.employee_id,
        quarantined=True,
        summary=(
            f"Quarantined the managed device for {inp.employee_id}; it is "
            "isolated from the network pending security review."
        ),
    )


register(
    ToolSpec(
        name="quarantine_device",
        description=(
            "Isolate the employee's managed device from the network via MDM "
            "security policy. The device stays quarantined until security "
            "operations releases it — highly disruptive, containment only."
        ),
        domain="security",
        input_model=QuarantineDeviceInput,
        output_model=QuarantineDeviceOutput,
        handler=_quarantine_device,
        privileged=True,
        privilege_key=keys.PRIV_DEVICE_QUARANTINE,
        system_key=keys.SYSTEM_MDM,
        risk_level="critical",
    )
)


class FlagAccountForSecurityReviewInput(BaseModel):
    employee_id: str
    reason: str


class FlagAccountForSecurityReviewOutput(BaseModel):
    employee_id: str
    flag: str
    summary: str


async def _flag_account_for_security_review(
    inp: FlagAccountForSecurityReviewInput, ctx: ToolContext
) -> FlagAccountForSecurityReviewOutput:
    get_world().flag_account(inp.employee_id, inp.reason)
    return FlagAccountForSecurityReviewOutput(
        employee_id=inp.employee_id,
        flag=inp.reason,
        summary=(
            f"Flagged the account for {inp.employee_id} for security review: "
            f"{inp.reason}"
        ),
    )


register(
    ToolSpec(
        name="flag_account_for_security_review",
        description=(
            "Attach an internal security-review flag to the employee's account "
            "with the stated reason so security operations investigates. Does "
            "not lock the account or restrict access."
        ),
        domain="security",
        input_model=FlagAccountForSecurityReviewInput,
        output_model=FlagAccountForSecurityReviewOutput,
        handler=_flag_account_for_security_review,
        system_key=keys.SYSTEM_SIEM,
        risk_level="medium",
    )
)


class NotifySecurityTeamInput(BaseModel):
    summary: str


class NotifySecurityTeamOutput(BaseModel):
    team_key: str
    acknowledged: bool
    summary: str


async def _notify_security_team(
    inp: NotifySecurityTeamInput, ctx: ToolContext
) -> NotifySecurityTeamOutput:
    get_world().notify_security(ctx.employee_id or "system", inp.summary)
    return NotifySecurityTeamOutput(
        team_key=keys.SUPPORT_SECURITY,
        acknowledged=True,
        summary=f"Notified the security operations team: {inp.summary}",
    )


register(
    ToolSpec(
        name="notify_security_team",
        description=(
            "Send a one-line incident summary to the security operations team "
            "queue and return their acknowledgement. Informational only — no "
            "account or device state changes."
        ),
        domain="security",
        input_model=NotifySecurityTeamInput,
        output_model=NotifySecurityTeamOutput,
        handler=_notify_security_team,
        system_key=keys.SYSTEM_SIEM,
    )
)
