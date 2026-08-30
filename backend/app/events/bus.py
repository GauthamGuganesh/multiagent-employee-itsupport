"""In-process pub/sub feeding SSE subscribers.

Deployment constraint: single uvicorn worker. The interface hides the
transport so a Postgres LISTEN/NOTIFY implementation can replace it without
touching producers or the SSE routes.
"""
import asyncio
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop it rather than block the pipeline.
                self._subscribers.discard(q)


bus = EventBus()
