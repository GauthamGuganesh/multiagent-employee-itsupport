"""Windows-safe local development entry point.

Uvicorn's CLI may create the event loop before importing app.main. Pinning the
selector policy here keeps asyncpg and the Postgres LangGraph checkpointer
compatible on Windows.
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=True,
        workers=1,
        loop="none",
    )
