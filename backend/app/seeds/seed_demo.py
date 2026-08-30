"""Demo operational data: a handful of tickets in interesting states,
including one pending beyond the 3-day threshold (scenario 7 / dashboard).

Idempotent per run marker: skips if the stale demo ticket already exists.
Run:  python -m app.seeds.seed_demo
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.db import repos
from app.db.base import Base, db_session, get_engine, init_engine
from app.db.models import Ticket
from app.org import keys

STALE_TITLE = "Salesforce dashboard access request"


async def main() -> None:
    init_engine()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db_session() as s:
        existing = await s.scalar(select(Ticket).where(Ticket.title == STALE_TITLE))
    if existing:
        print(f"demo data already present ({existing.ticket_number}); nothing to do")
        return

    # 1. Stale pending ticket (4 days) — triggers the aging escalation.
    stale = await repos.create_ticket(
        session_id=None,
        requester_employee_id=keys.EMP_LOCKED_OUT,  # EMP-034, sales
        category="identity",
        title=STALE_TITLE,
        description="Requested read access to the regional sales dashboard in Salesforce.",
        status="pending",
        current_owner_id=keys.EMP_IT_SUPPORT_1,
        current_team_key=keys.SUPPORT_IT,
        originating_agent="identity",
    )
    four_days_ago = datetime.now(timezone.utc) - timedelta(days=4)
    async with db_session() as s:
        row = await s.get(Ticket, stale.id)
        row.pending_since = four_days_ago
        row.created_at = four_days_ago
    print(f"created stale pending ticket {stale.ticket_number} (pending 4 days)")

    # 2. A resolved ticket for history.
    resolved = await repos.create_ticket(
        session_id=None,
        requester_employee_id=keys.EMP_SLOW_LAPTOP,
        category="endpoint",
        title="Laptop running slowly",
        description="Device health check found disk at 96%; cleanup guidance provided.",
        status="open",
        current_team_key=keys.SUPPORT_IT,
        originating_agent="endpoint",
    )
    await repos.update_ticket_status(
        resolved.id, "resolved", changed_by="resolution_workflow",
        reason="Freed disk space; performance back to normal.",
    )
    print(f"created resolved ticket {resolved.ticket_number}")

    # 3. An in-progress ticket owned by a human.
    in_progress = await repos.create_ticket(
        session_id=None,
        requester_employee_id=keys.EMP_017_BACKEND,
        category="network",
        title="Office Wi-Fi drops in meeting room B",
        description="Recurring disconnects reported; on-site check scheduled.",
        status="open",
        current_owner_id=keys.EMP_IT_SUPPORT_2,
        current_team_key=keys.SUPPORT_IT,
        originating_agent="network",
    )
    await repos.update_ticket_status(
        in_progress.id, "in_progress", changed_by=keys.EMP_IT_SUPPORT_2,
        reason="On-site diagnostics scheduled.",
    )
    print(f"created in-progress ticket {in_progress.ticket_number}")
    print("demo data seeded")


if __name__ == "__main__":
    asyncio.run(main())
