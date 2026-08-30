"""Command-center endpoints: metrics, lists, timelines, and the human
mutation surface (approval decisions, escalation interventions)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_administrator
from app.db import ops_queries, repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.workflows.approval import decide_approval_request
from app.org import service as org
from app.org.client import OrgUnavailableError

router = APIRouter(prefix="/api/ops", tags=["ops"])


@router.get("/metrics")
async def metrics(_: str = Depends(get_current_administrator)):
    return await ops_queries.overview_metrics()


@router.get("/sessions")
async def sessions(status: str | None = None, limit: int = 50, _: str = Depends(get_current_administrator)):
    return {"sessions": await ops_queries.list_sessions(status=status, limit=min(limit, 200))}


@router.get("/sessions/{session_id}/timeline")
async def timeline(session_id: str, _: str = Depends(get_current_administrator)):
    session = await repos.get_support_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {
        "session": {
            "id": session.id,
            "employee_id": session.employee_id,
            "channel": session.channel,
            "status": session.status,
            "terminal_status": session.terminal_status,
            "original_request": session.original_request,
            "category": session.category,
            "intent": session.intent,
            "risk_level": session.risk_level,
            "autonomy_level": session.autonomy_level,
            "final_response": session.final_response,
            "created_at": session.created_at.isoformat(),
        },
        "timeline": await ops_queries.session_timeline(session_id),
    }


@router.get("/tickets")
async def tickets(
    status: str | None = None,
    category: str | None = None,
    team: str | None = None,
    owner: str | None = None,
    originating_agent: str | None = None,
    security_related: bool | None = None,
    escalated: bool | None = None,
    approval_pending: bool | None = None,
    pending_over_threshold: bool | None = None,
    search: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    sort: str = "newest",
    limit: int = 100,
    _: str = Depends(get_current_administrator),
):
    return {
        "tickets": await ops_queries.list_tickets(
            status=status,
            category=category,
            team=team,
            owner=owner,
            originating_agent=originating_agent,
            security_related=security_related,
            escalated=escalated,
            approval_pending=approval_pending,
            pending_over_threshold=pending_over_threshold,
            search=search,
            created_after=created_after,
            created_before=created_before,
            sort=sort,
            limit=min(limit, 500),
        )
    }


@router.get("/agent-runs")
async def agent_runs(
    agent_name: str | None = None,
    outcome: str | None = None,
    status: str | None = None,
    failure_type: str | None = None,
    loop_guard: bool | None = None,
    structured_output_failed: bool | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = 100,
    _: str = Depends(get_current_administrator),
):
    return {
        "runs": await ops_queries.list_agent_runs(
            agent_name=agent_name,
            outcome=outcome,
            status=status,
            failure_type=failure_type,
            loop_guard=loop_guard,
            structured_output_failed=structured_output_failed,
            created_after=created_after,
            created_before=created_before,
            limit=min(limit, 500),
        )
    }


@router.get("/approvals")
async def approvals(status: str | None = "pending", _: str = Depends(get_current_administrator)):
    return {"approvals": await ops_queries.list_approvals(status=status or None)}


class ApprovalDecision(BaseModel):
    approved: bool
    reason: str = ""


@router.post("/approvals/{approval_id}/decision")
async def decide(approval_id: str, body: ApprovalDecision, actor: str = Depends(get_current_administrator)):
    result = await decide_approval_request(
        approval_id, approved=body.approved, decided_by=actor, reason=body.reason
    )
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", "cannot decide"))
    return result


@router.get("/escalations")
async def escalations(_: str = Depends(get_current_administrator)):
    return {"escalations": await ops_queries.list_escalations()}


class InterventionRequest(BaseModel):
    note: str = ""
    resolve: bool = False


@router.post("/tickets/{ticket_id}/intervene")
async def intervene(ticket_id: str, body: InterventionRequest, actor: str = Depends(get_current_administrator)):
    ticket = await repos.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    new_status = "resolved" if body.resolve else "in_progress"
    await repos.update_ticket_status(
        ticket_id, new_status, changed_by=actor,
        reason=body.note or "handled by human operator",
        current_owner_id=actor,
    )
    await record(
        EventType.HUMAN_INTERVENTION,
        session_id=ticket.session_id,
        ticket_id=ticket_id,
        actor=actor,
        payload={"kind": "ticket_intervention", "note": body.note, "new_status": new_status},
    )
    await record(
        EventType.TICKET_STATUS_CHANGED,
        session_id=ticket.session_id,
        ticket_id=ticket_id,
        actor=actor,
        payload={"ticket_number": ticket.ticket_number, "to_status": new_status},
    )
    if ticket.session_id:
        await repos.add_message(
            ticket.session_id,
            "assistant",
            f"Update on {ticket.ticket_number}: {actor} has picked this up"
            + (f" — {body.note}" if body.note else "")
            + (" and marked it resolved." if body.resolve else "."),
        )
    return {"ok": True, "status": new_status}


@router.get("/audit")
async def audit(
    session_id: str | None = None,
    ticket_id: str | None = None,
    event_type: str | None = None,
    created_after: datetime | None = None,
    limit: int = 200,
    _: str = Depends(get_current_administrator),
):
    return {
        "events": await ops_queries.list_audit_events(
            session_id=session_id,
            ticket_id=ticket_id,
            event_type=event_type,
            created_after=created_after,
            limit=min(limit, 1000),
        )
    }


@router.get("/org/graph")
async def org_graph(_: str = Depends(get_current_administrator)):
    """Employee/team/reporting graph for the visualization page."""
    try:
        from app.org.client import run_query

        employees = await run_query(
            "MATCH (e:Employee) OPTIONAL MATCH (e)-[:MEMBER_OF]->(t:Team) "
            "OPTIONAL MATCH (e)-[:REPORTS_TO]->(m:Employee) "
            "RETURN e.id AS id, e.name AS name, e.title AS title, "
            "t.key AS team_key, t.name AS team_name, m.id AS manager_id ORDER BY e.id",
            {},
        )
        teams = await run_query(
            "MATCH (t:Team)-[:PART_OF]->(d:Department) "
            "RETURN t.key AS key, t.name AS name, d.key AS department_key, d.name AS department_name",
            {},
        )
        systems = await run_query(
            "MATCH (s:System) OPTIONAL MATCH (s)<-[:OWNS]-(t:Team) "
            "OPTIONAL MATCH (s)-[:SUPPORTED_BY]->(st:SupportTeam) "
            "RETURN s.key AS key, s.name AS name, s.category AS category, "
            "t.key AS owner_team_key, st.key AS support_team_key",
            {},
        )
        return {"employees": employees, "teams": teams, "systems": systems}
    except OrgUnavailableError:
        raise HTTPException(status_code=503, detail="organization directory unavailable")


@router.get("/org/employee/{employee_id}")
async def org_employee(employee_id: str, _: str = Depends(get_current_administrator)):
    try:
        ctx = await org.get_employee_org_context(employee_id)
    except OrgUnavailableError:
        raise HTTPException(status_code=503, detail="organization directory unavailable")
    if ctx is None:
        raise HTTPException(status_code=404, detail="unknown employee")
    return ctx
