"""FastAPI application factory.

Deployment constraint: single uvicorn worker (in-process event bus). On
Windows the selector event loop policy is pinned before the loop starts so
psycopg async (LangGraph checkpointer) works alongside asyncpg (SQLAlchemy).
"""
import asyncio
import contextlib
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import app.tools  # noqa: F401  (registers all mock tools)
from app.api import dispatcher
from app.api.routes_auth import router as auth_router
from app.api.routes_chat import router as chat_router
from app.api.routes_ops import router as ops_router
from app.api.routes_stream import router as stream_router
from app.api.routes_tickets import router as tickets_router
from app.api.routes_voice import custom_llm_router, router as voice_router
from app.config import get_settings
from app.db.base import dispose_engine, init_engine
from app.graph.build import build_graph

AGING_SWEEP_INTERVAL_SECONDS = 6 * 60 * 60


async def _aging_sweep_loop() -> None:
    from app.graph.workflows.escalation import sweep_stale_tickets

    while True:
        try:
            escalated = await sweep_stale_tickets()
            if escalated:
                print(f"[aging-sweep] escalated {escalated} stale ticket(s)")
        except Exception as exc:  # sweep must never kill the app
            print(f"[aging-sweep] skipped: {exc}")
        await asyncio.sleep(AGING_SWEEP_INTERVAL_SECONDS)


async def _make_checkpointer(stack: contextlib.AsyncExitStack):
    """Postgres checkpointer when reachable; in-memory fallback for dev."""
    settings = get_settings()
    dsn = settings.postgres_dsn.replace("+asyncpg", "").replace("+psycopg", "")
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(dsn))
        await saver.setup()
        print("[startup] using Postgres checkpointer")
        return saver
    except Exception as exc:
        from langgraph.checkpoint.memory import InMemorySaver

        print(f"[startup] Postgres checkpointer unavailable ({exc!r}); using InMemorySaver")
        return InMemorySaver()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_engine()
    # Schema changes are applied explicitly through Alembic before startup.
    # Runtime create_all() masks missing migrations and permits schema drift.

    async with contextlib.AsyncExitStack() as stack:
        checkpointer = await _make_checkpointer(stack)
        dispatcher.set_graph(build_graph(checkpointer))

        sweep_task = asyncio.create_task(_aging_sweep_loop())
        try:
            yield
        finally:
            sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep_task
            from app.org.client import close_driver

            with contextlib.suppress(Exception):
                await close_driver()
            await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="GA-VoiceAI IT Support", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(tickets_router)
    app.include_router(ops_router)
    app.include_router(stream_router)
    app.include_router(voice_router)
    app.include_router(custom_llm_router)

    @app.get("/health")
    @app.get("/api/health", include_in_schema=False)
    async def health():
        return {"ok": True, "environment": get_settings().app_env}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    # Single worker: required by the in-process event bus + per-thread locks.
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        workers=1,
    )
