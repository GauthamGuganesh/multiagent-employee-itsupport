"""Cross-session memory service seam (design §8).

Mem0 is a required component: there is no local/null fallback and failures are
not swallowed. If Mem0 is misconfigured the app fails to start; if it errors at
runtime the exception propagates and the turn fails loudly (the dispatcher
turns it into an audited escalation) rather than silently pretending memory is
empty. Privileges, roles, ticket/approval state, and security facts are still
never sourced from memory; those come from Neo4j/Postgres tools.
"""
import asyncio
import os
from typing import Protocol

# mem0 fires anonymous posthog telemetry on client construction and on calls;
# that network write can BLOCK (it has hung app startup for 60s+). Disable it
# before mem0 is ever imported so a required component can never freeze boot.
os.environ.setdefault("MEM0_TELEMETRY", "False")

from app.config import get_settings
from app.contracts.common import RetrievedMemory

# Hard ceiling on any single Mem0 call so a slow/unreachable platform fails
# loudly (raises) instead of silently hanging a turn.
_MEM0_TIMEOUT_SECONDS = 15.0


class MemoryService(Protocol):
    async def retrieve(
        self, employee_id: str, query: str, limit: int
    ) -> list[RetrievedMemory]: ...

    async def write(self, employee_id: str, content: str) -> str | None: ...


class Mem0Adapter:
    """Hosted Mem0 Platform adapter behind the non-authoritative memory seam."""

    def __init__(self) -> None:
        try:
            from mem0 import MemoryClient
        except ImportError as exc:
            raise RuntimeError(
                "mem0ai is required but not installed. Run: pip install mem0ai "
                "(or reinstall the backend: pip install -e .)"
            ) from exc
        api_key = get_settings().mem0_api_key
        if not api_key:
            raise RuntimeError("MEM0_API_KEY is required when IT_MEMORY_BACKEND=mem0")
        self._memory = MemoryClient(api_key=api_key)

    async def retrieve(
        self, employee_id: str, query: str, limit: int
    ) -> list[RetrievedMemory]:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                self._memory.search,
                query,
                filters={"user_id": employee_id},
                top_k=limit,
            ),
            timeout=_MEM0_TIMEOUT_SECONDS,
        )
        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        memories: list[RetrievedMemory] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            content = str(item.get("memory") or item.get("content") or "")
            if not content:
                continue
            score = item.get("score")
            memories.append(
                RetrievedMemory(
                    memory_id=str(item.get("id", "")),
                    content=content,
                    score=float(score) if score is not None else None,
                )
            )
        return memories[:limit]

    async def write(self, employee_id: str, content: str) -> str | None:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                self._memory.add,
                messages=[{"role": "assistant", "content": content}],
                user_id=employee_id,
                metadata={"source": "ga-voiceai-support"},
            ),
            timeout=_MEM0_TIMEOUT_SECONDS,
        )
        items = raw.get("results", raw) if isinstance(raw, dict) else raw
        if isinstance(items, list) and items and isinstance(items[0], dict):
            memory_id = items[0].get("id")
            return str(memory_id) if memory_id is not None else None
        return None


_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    """Return the configured memory service, or raise loudly.

    Only Mem0 is supported. A missing key or unsupported backend is a
    configuration error the app must not run past — no silent degradation.
    """
    global _service
    if _service is None:
        backend = get_settings().memory_backend
        if backend != "mem0":
            raise RuntimeError(
                f"IT_MEMORY_BACKEND={backend!r} is not supported. Set it to 'mem0' "
                "and provide MEM0_API_KEY."
            )
        _service = Mem0Adapter()  # raises loudly if MEM0_API_KEY is missing
    return _service


def set_memory_service(service: MemoryService | None) -> None:
    """Test hook: inject a double, or reset with None."""
    global _service
    _service = service
