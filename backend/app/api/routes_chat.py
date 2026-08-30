"""Employee conversational endpoints (web channel)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api import dispatcher
from app.api.deps import get_current_employee
from app.db import repos
from app.db.base import db_session
from app.db.models import SupportSession

router = APIRouter(prefix="/api/chat", tags=["chat"])


class StartSessionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ContinueRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ConfirmRequest(BaseModel):
    confirmed: bool


@router.post("/sessions")
async def start_session(body: StartSessionRequest, employee_id: str = Depends(get_current_employee)):
    return await dispatcher.start_session(employee_id, body.message.strip(), channel="web")


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str, body: ContinueRequest, employee_id: str = Depends(get_current_employee)
):
    result = await dispatcher.continue_session(session_id, employee_id, body.message.strip(), channel="web")
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/sessions/{session_id}/confirm")
async def confirm(
    session_id: str, body: ConfirmRequest, employee_id: str = Depends(get_current_employee)
):
    result = await dispatcher.continue_session(session_id, employee_id, body.confirmed, channel="web")
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/sessions")
async def my_sessions(employee_id: str = Depends(get_current_employee)):
    async with db_session() as s:
        rows = await s.scalars(
            select(SupportSession)
            .where(SupportSession.employee_id == employee_id)
            .order_by(SupportSession.created_at.desc())
            .limit(20)
        )
        sessions = rows.all()
    return {
        "sessions": [
            {
                "id": r.id,
                "status": r.status,
                "terminal_status": r.terminal_status,
                "original_request": r.original_request,
                "category": r.category,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in sessions
        ]
    }


@router.get("/sessions/{session_id}")
async def session_detail(session_id: str, employee_id: str = Depends(get_current_employee)):
    session = await repos.get_support_session(session_id)
    if session is None or session.employee_id != employee_id:
        raise HTTPException(status_code=404, detail="session not found")
    messages = await repos.list_messages(session_id)
    pending = await dispatcher._pending_interrupt(session_id) if session.status == "waiting_employee" else None
    return {
        "id": session.id,
        "status": session.status,
        "terminal_status": session.terminal_status,
        "original_request": session.original_request,
        "pending": pending,
        "messages": [
            {"role": m.role, "content": m.content, "source": m.source, "at": m.created_at.isoformat()}
            for m in messages
        ],
    }
