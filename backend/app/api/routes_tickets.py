"""Employee-facing ticket endpoints (My Requests + detail)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import get_current_employee
from app.db import repos
from app.db.base import db_session
from app.db.models import ApprovalRequest
from app.graph.workflows.escalation import pending_age_days

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


def _ticket_json(t) -> dict:
    return {
        "id": t.id,
        "ticket_number": t.ticket_number,
        "title": t.title,
        "category": t.category,
        "status": t.status,
        "priority": t.priority,
        "security_related": t.security_related,
        "escalated": t.escalated,
        "pending_age_days": pending_age_days(t.pending_since),
        "current_owner_id": t.current_owner_id,
        "current_team_key": t.current_team_key,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


@router.get("/mine")
async def my_tickets(employee_id: str = Depends(get_current_employee)):
    tickets = await repos.find_tickets(requester_employee_id=employee_id, limit=25)
    return {"tickets": [_ticket_json(t) for t in tickets]}


@router.get("/{ticket_number}")
async def ticket_detail(ticket_number: str, employee_id: str = Depends(get_current_employee)):
    ticket = await repos.get_ticket_by_number(ticket_number)
    if ticket is None or ticket.requester_employee_id != employee_id:
        raise HTTPException(status_code=404, detail="ticket not found")
    history = await repos.ticket_history(ticket.id)
    async with db_session() as s:
        approvals = (
            await s.scalars(select(ApprovalRequest).where(ApprovalRequest.ticket_id == ticket.id))
        ).all()
    return {
        **_ticket_json(ticket),
        "description": ticket.description,
        "history": [
            {
                "from_status": h.from_status,
                "to_status": h.to_status,
                "changed_by": h.changed_by,
                "reason": h.reason,
                "at": h.created_at.isoformat(),
            }
            for h in history
        ],
        "approvals": [
            {
                "id": a.id,
                "approver_employee_id": a.approver_employee_id,
                "action_summary": a.action_summary,
                "status": a.status,
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
            }
            for a in approvals
        ],
    }
