"""Server-Sent Events: live event streams for the command center and for the
employee chat's progress updates. Events were persisted before they reach the
bus, so a dashboard refresh can always rebuild history from /api/ops."""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_current_administrator, get_current_employee
from app.api.friendly import friendly_copy
from app.events.bus import bus

router = APIRouter(prefix="/api/stream", tags=["stream"])

HEARTBEAT_SECONDS = 20


async def _event_stream(request: Request, *, session_filter: str | None, friendly: bool):
    queue = bus.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": ""}
                continue
            if session_filter and event.get("session_id") != session_filter:
                continue
            if friendly:
                copy = friendly_copy(event)
                if copy is None:
                    continue
                yield {
                    "event": "progress",
                    "data": json.dumps({"text": copy, "at": event.get("created_at")}),
                }
            else:
                yield {"event": "audit", "data": json.dumps(event, default=str)}
    finally:
        bus.unsubscribe(queue)


@router.get("/ops")
async def ops_stream(request: Request, _: str = Depends(get_current_administrator)):
    return EventSourceResponse(_event_stream(request, session_filter=None, friendly=False))


@router.get("/session/{session_id}")
async def session_stream(
    session_id: str, request: Request, _: str = Depends(get_current_employee)
):
    return EventSourceResponse(_event_stream(request, session_filter=session_id, friendly=True))
