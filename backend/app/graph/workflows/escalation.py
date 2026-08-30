"""Escalation workflow: resolve the right human via Neo4j, persist, notify.

Also hosts the stale-ticket sweep (pending > PENDING_ESCALATION_DAYS) used at
query time and by the startup/interval task — deliberately not an SLA engine.
"""
from datetime import datetime, timezone

from app.config import get_settings
from app.contracts.common import HumanTarget
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState
from app.graph.workflows.common import finalize_session
from app.org import keys
from app.org import service as org

# Dominant-symptom category → the system whose support chain owns it.
CATEGORY_SYSTEM = {
    "network": keys.SYSTEM_VPN,
    "identity": keys.SYSTEM_OKTA,
    "endpoint": keys.SYSTEM_MDM,
    "security": keys.SYSTEM_SIEM,
    "ticketing": keys.SYSTEM_OKTA,
    "other": keys.SYSTEM_OKTA,
}

AUTOMATION_LIMIT_TRIGGERS = {"budget_exhausted", "loop_guard", "structured_output_failure"}


async def _resolve_target(
    category: str | None, system_key: str | None, current_owner_id: str | None
) -> HumanTarget:
    sys_key = system_key or CATEGORY_SYSTEM.get(category or "other", keys.SYSTEM_OKTA)
    target = await org.get_escalation_target(current_owner_id, sys_key)
    if target:
        return HumanTarget(
            employee_id=target.get("employee_id"),
            employee_name=target.get("employee_name"),
            employee_title=target.get("employee_title"),
            team_key=target.get("team_key"),
            team_name=target.get("team_name"),
        )
    # Directory unavailable or no chain configured — degrade to the IT support queue.
    return HumanTarget(team_key=keys.SUPPORT_IT, team_name="IT Support")


def describe_human_target(target: HumanTarget) -> str:
    """A useful employee-facing description without exposing internal IDs."""
    if not target.employee_name:
        return target.team_name or "the IT support team"
    title = f", {target.employee_title}" if target.employee_title else ""
    team = f" in the {target.team_name} team" if target.team_name else ""
    return f"{target.employee_name}{title}{team}"


async def escalation_node(state: SupportState) -> dict:
    reason = state.escalation_reason
    if not reason:
        for result in reversed(state.specialist_results):
            if result.outcome == "escalation_required" and result.escalation_reason:
                reason = result.escalation_reason
                break
    reason = reason or "automated investigation requires human attention"
    trigger = state.escalation_trigger or "agent_recommendation"

    system_key = state.requested_action.system_key if state.requested_action else None
    security_related = state.category == "security" or trigger == "security"

    ticket_id, ticket_number = state.ticket_id, state.ticket_number
    current_owner = None
    if ticket_id:
        existing = await repos.get_ticket(ticket_id)
        current_owner = existing.current_owner_id if existing else None

    target = await _resolve_target(state.category, system_key, current_owner)

    if ticket_id is None:
        ticket = await repos.create_ticket(
            session_id=state.session_id,
            requester_employee_id=state.employee_id,
            category=state.category or "other",
            title=(state.intent or state.original_request)[:200],
            description=f"{state.original_request}\n\nEscalation reason: {reason}",
            status="escalated",
            priority="high" if security_related else "medium",
            current_owner_id=target.employee_id,
            current_team_key=target.team_key,
            originating_agent=state.current_agent or "supervisor",
            security_related=security_related,
        )
        ticket_id, ticket_number = ticket.id, ticket.ticket_number
        await record(
            EventType.TICKET_CREATED,
            session_id=state.session_id,
            ticket_id=ticket_id,
            actor="escalation_workflow",
            payload={"ticket_number": ticket_number, "status": "escalated"},
        )
    else:
        await repos.update_ticket_status(
            ticket_id, "escalated", changed_by="escalation_workflow", reason=reason,
            current_owner_id=target.employee_id, current_team_key=target.team_key,
        )
        await record(
            EventType.TICKET_STATUS_CHANGED,
            session_id=state.session_id,
            ticket_id=ticket_id,
            actor="escalation_workflow",
            payload={"ticket_number": ticket_number, "to_status": "escalated"},
        )

    await repos.create_escalation_event(
        ticket_id=ticket_id,
        session_id=state.session_id,
        reason=reason,
        trigger=trigger,
        from_owner_id=current_owner,
        to_target_id=target.employee_id,
        to_team_key=target.team_key,
    )
    await record(
        EventType.ESCALATION_TRIGGERED,
        session_id=state.session_id,
        ticket_id=ticket_id,
        actor="escalation_workflow",
        payload={
            "reason": reason,
            "trigger": trigger,
            "target": target.model_dump(),
            "findings_preserved": len(state.specialist_findings),
        },
    )

    who = describe_human_target(target)
    if trigger in AUTOMATION_LIMIT_TRIGGERS:
        response = (
            "I'm sorry this is still interrupting your work. I wasn't able to finish the "
            f"automated investigation because it reached its safe execution limit, so I've handed everything I found to {who}. "
            f"Ticket {ticket_number} has the diagnostic details and is now ready for their follow-up."
        )
    elif security_related:
        response = (
            "I'm sorry this has raised a security concern. To keep your account safe, I've "
            f"escalated it to {who} for review. Ticket {ticket_number} tracks the case; "
            "please follow any guidance they send you."
        )
    else:
        response = (
            "I'm sorry this is disrupting your work. I've moved the case to "
            f"{who}, who can take the next steps. Ticket {ticket_number} includes the "
            "evidence gathered so far and tracks the handoff."
        )

    update = await finalize_session(
        state, terminal_status="escalated", final_response=response, session_status="escalated"
    )
    return {
        **update,
        "ticket_id": ticket_id,
        "ticket_number": ticket_number,
        "escalation_required": True,
        "escalation_reason": reason,
        "human_target": target,
    }


# --- stale-ticket aging (query-time + periodic sweep) ------------------------

def pending_age_days(pending_since: datetime | None) -> int | None:
    if pending_since is None:
        return None
    ps = pending_since if pending_since.tzinfo else pending_since.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ps).days


async def escalate_stale_ticket(ticket_id: str) -> dict | None:
    """Escalate one ticket whose pending age exceeded the threshold. Used by
    the ticket_status workflow and the periodic sweep. Idempotent per ticket
    (escalated tickets are excluded from staleness queries)."""
    ticket = await repos.get_ticket(ticket_id)
    if ticket is None or ticket.escalated:
        return None
    age = pending_age_days(ticket.pending_since)
    threshold = get_settings().pending_escalation_days
    if age is None or age <= threshold:
        return None

    target = await _resolve_target(ticket.category, None, ticket.current_owner_id)
    reason = (
        f"ticket {ticket.ticket_number} has been pending for {age} days, "
        f"exceeding the {threshold}-day threshold"
    )
    await repos.update_ticket_status(
        ticket.id, "escalated", changed_by="aging_sweep", reason=reason,
        current_owner_id=target.employee_id, current_team_key=target.team_key,
    )
    await repos.create_escalation_event(
        ticket_id=ticket.id,
        session_id=ticket.session_id,
        reason=reason,
        trigger="pending_age",
        from_owner_id=ticket.current_owner_id,
        to_target_id=target.employee_id,
        to_team_key=target.team_key,
    )
    await record(
        EventType.ESCALATION_TRIGGERED,
        session_id=ticket.session_id,
        ticket_id=ticket.id,
        actor="aging_sweep",
        payload={
            "reason": reason,
            "trigger": "pending_age",
            "target": target.model_dump(),
            "pending_age_days": age,
        },
    )
    return {"ticket_number": ticket.ticket_number, "age_days": age, "target": target}


async def sweep_stale_tickets() -> int:
    """Find and escalate every non-escalated ticket pending beyond the threshold."""
    threshold = get_settings().pending_escalation_days
    stale = await repos.stale_pending_tickets(threshold)
    count = 0
    for ticket in stale:
        if await escalate_stale_ticket(ticket.id):
            count += 1
    return count
