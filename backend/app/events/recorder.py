"""Persist-then-broadcast event recording.

Every observability event is written to `audit_events` FIRST; only a
successful write is broadcast to SSE subscribers. If Postgres is unavailable
the exception propagates to the caller's degradation path — an event that was
never persisted is never shown as live truth.
"""
from typing import Any

from app.db.base import db_session
from app.db.models import AuditEvent
from app.events.bus import bus
from app.events.types import EventType


async def record(
    event_type: EventType,
    *,
    session_id: str | None = None,
    ticket_id: str | None = None,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
) -> str:
    """Persist an audit event and broadcast it. Returns the event id."""
    row = AuditEvent(
        session_id=session_id,
        ticket_id=ticket_id,
        event_type=str(event_type),
        actor=actor,
        payload=payload or {},
    )
    async with db_session() as s:
        s.add(row)
        await s.flush()
        event_id = row.id
        created_at = row.created_at
    bus.publish(
        {
            "id": event_id,
            "session_id": session_id,
            "ticket_id": ticket_id,
            "event_type": str(event_type),
            "actor": actor,
            "payload": payload or {},
            "created_at": created_at.isoformat(),
        }
    )
    return event_id
