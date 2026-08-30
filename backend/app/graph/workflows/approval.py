"""Approval workflow: resolve approver via Neo4j → persist request → notify.

Also hosts the deterministic post-decision executor used by the ops API: on
approval the persisted RequestedAction executes from durable state (the
originating graph session has already ended).
"""
from langgraph.types import Command

from app.contracts.common import Transition
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState
from app.graph.workflows.common import finalize_session
from app.org import service as org
from app.org.client import OrgUnavailableError
from app.tools.registry import ToolContext, execute_tool


async def approval_node(state: SupportState) -> Command:
    action = state.requested_action
    if action is None:
        return Command(
            goto="escalation",
            update={
                "escalation_required": True,
                "escalation_reason": "approval workflow reached without a concrete requested action",
                "escalation_trigger": "out_of_scope",
            },
        )

    approver_id = (
        state.privilege_check_result.approver_employee_id
        if state.privilege_check_result
        else None
    )
    approver_name = None
    try:
        if approver_id is None:
            approver = await org.get_required_approver(state.employee_id, action.privilege_key)
            if approver:
                approver_id, approver_name = approver.get("id"), approver.get("name")
        else:
            ctx = await org.get_employee_org_context(approver_id)
            approver_name = ctx.get("name") if ctx else None
    except OrgUnavailableError:
        approver_id = None

    if approver_id is None:
        return Command(
            goto="escalation",
            update={
                "escalation_required": True,
                "escalation_reason": (
                    f"no approver could be resolved for '{action.privilege_key}'"
                ),
                "escalation_trigger": "infrastructure",
                "transition_history": [
                    Transition(
                        from_node="approval", to_node="escalation",
                        reason="approver resolution failed",
                    )
                ],
            },
        )

    ticket_id, ticket_number = state.ticket_id, state.ticket_number
    if ticket_id is None:
        ticket = await repos.create_ticket(
            session_id=state.session_id,
            requester_employee_id=state.employee_id,
            category=state.category or "identity",
            title=f"Access request: {action.privilege_key}",
            description=action.summary,
            status="waiting_approval",
            originating_agent=state.current_agent or "supervisor",
            security_related=(state.category == "security"),
        )
        ticket_id, ticket_number = ticket.id, ticket.ticket_number
        await record(
            EventType.TICKET_CREATED,
            session_id=state.session_id,
            ticket_id=ticket_id,
            actor="approval_workflow",
            payload={"ticket_number": ticket_number, "status": "waiting_approval"},
        )
    else:
        await repos.update_ticket_status(
            ticket_id, "waiting_approval", changed_by="approval_workflow",
            reason=f"approval required for {action.privilege_key}",
        )

    approval = await repos.create_approval_request(
        ticket_id=ticket_id,
        session_id=state.session_id,
        requester_employee_id=state.employee_id,
        approver_employee_id=approver_id,
        privilege_key=action.privilege_key,
        system_key=action.system_key,
        action_summary=action.summary,
        action_key=action.action_key,
        params=action.params_dict(),
        risk_level=action.risk_level,
    )
    await record(
        EventType.APPROVAL_REQUESTED,
        session_id=state.session_id,
        ticket_id=ticket_id,
        actor="approval_workflow",
        payload={
            "approval_id": approval.id,
            "approver_employee_id": approver_id,
            "privilege_key": action.privilege_key,
            "action_summary": action.summary,
        },
    )

    who = f"{approver_name} ({approver_id})" if approver_name else approver_id
    response = (
        f"You don't currently have the access this needs ({action.privilege_key}), "
        f"but you're eligible to request it. I've sent an approval request to {who} "
        f"and created ticket {ticket_number} to track it. I'll let you know once "
        "it's decided — you can also check under My Requests."
    )
    update = await finalize_session(
        state,
        terminal_status="approval_pending",
        final_response=response,
        session_status="waiting_approval",
    )
    return Command(
        goto="__end__",
        update={
            **update,
            "ticket_id": ticket_id,
            "ticket_number": ticket_number,
            "approval_id": approval.id,
        },
    )


async def decide_approval_request(
    approval_id: str, *, approved: bool, decided_by: str, reason: str = ""
) -> dict:
    """Ops-API entry point: record the human decision, then deterministically
    execute the approved action from durable state and notify the employee."""
    row = await repos.decide_approval(
        approval_id, approved=approved, decided_by=decided_by, reason=reason
    )
    if row is None:
        return {"ok": False, "error": "approval not found or already decided"}

    await record(
        EventType.APPROVAL_DECIDED,
        session_id=row.session_id,
        ticket_id=row.ticket_id,
        actor=decided_by,
        payload={
            "approval_id": approval_id,
            "approved": approved,
            "reason": reason,
            "privilege_key": row.privilege_key,
        },
    )
    await record(
        EventType.HUMAN_INTERVENTION,
        session_id=row.session_id,
        ticket_id=row.ticket_id,
        actor=decided_by,
        payload={"kind": "approval_decision", "approved": approved},
    )

    execution_status: str | None = None
    if approved and row.action_key:
        params = dict(row.params or {})
        params.setdefault("employee_id", row.requester_employee_id)
        result = await execute_tool(
            row.action_key,
            params,
            ToolContext(
                session_id=row.session_id,
                employee_id=row.requester_employee_id,
                agent_name="approval_workflow",
                authorized_privileged=True,
            ),
        )
        execution_status = result.status
        await repos.create_action_execution(
            session_id=row.session_id,
            approval_id=approval_id,
            action_key=row.action_key,
            params=params,
            result={"summary": result.response_summary, "error": result.error},
            status=result.status,
        )
        await record(
            EventType.ACTION_EXECUTED,
            session_id=row.session_id,
            ticket_id=row.ticket_id,
            actor="approval_workflow",
            payload={
                "action_key": row.action_key,
                "status": result.status,
                "summary": result.response_summary,
                "approval_id": approval_id,
            },
        )

    if row.ticket_id:
        if approved:
            new_status = "resolved" if execution_status == "succeeded" else "in_progress"
            note = "approved" + (f"; action {execution_status}" if execution_status else "")
        else:
            new_status = "closed"
            note = f"rejected: {reason}" if reason else "rejected"
        await repos.update_ticket_status(
            row.ticket_id, new_status, changed_by=decided_by, reason=note
        )
        ticket = await repos.get_ticket(row.ticket_id)
        await record(
            EventType.TICKET_STATUS_CHANGED,
            session_id=row.session_id,
            ticket_id=row.ticket_id,
            actor=decided_by,
            payload={"ticket_number": ticket.ticket_number if ticket else None, "to_status": new_status},
        )

    if row.session_id:
        verdict = "approved" if approved else "declined"
        detail = ""
        if approved and execution_status == "succeeded":
            detail = " The requested action has been completed."
        elif approved and execution_status and execution_status != "succeeded":
            detail = " The action could not be completed automatically; IT will follow up."
        elif not approved and reason:
            detail = f" Reason: {reason}"
        await repos.add_message(
            row.session_id,
            "assistant",
            f"Update on your request: {row.action_summary} — {verdict} by {decided_by}.{detail}",
        )
        await repos.update_support_session(row.session_id, status="completed")

    return {"ok": True, "approved": approved, "execution_status": execution_status}
