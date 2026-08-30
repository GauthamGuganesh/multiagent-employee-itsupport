"""Cross-session memory service seam (design §8).

Memory is contextual, never load-bearing: every retrieve/write is wrapped so
it can NEVER raise into the graph — failures are logged and degrade to empty
results. Privileges, roles, ticket/approval state, and security facts are
never sourced from memory; those come from Neo4j/Postgres tools.
"""
import asyncio
import json
import re
import uuid
from pathlib import Path
from typing import Any, Protocol

from app.config import get_settings
from app.contracts.common import RetrievedMemory, utcnow


class MemoryService(Protocol):
    async def retrieve(
        self, employee_id: str, query: str, limit: int
    ) -> list[RetrievedMemory]: ...

    async def write(self, employee_id: str, content: str) -> str | None: ...


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SCORE_THRESHOLD = 0.05


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


class LocalMemoryStore:
    """Deterministic JSON-file backend — the offline demo/test fallback.

    File layout: {employee_id: [{id, content, created_at}]}. Retrieval scores
    each memory by case-insensitive token overlap (Jaccard) against the query;
    only scores above the threshold are returned, best first (stable sort, so
    ties keep chronological order). Reads/writes the file per call under an
    asyncio.Lock — cheap and safe at demo scale.
    """

    def __init__(self, store_path: str | Path | None = None) -> None:
        root = Path(store_path if store_path is not None else get_settings().memory_store_path)
        self._path = root / "memories.json"
        self._lock = asyncio.Lock()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    async def retrieve(
        self, employee_id: str, query: str, limit: int
    ) -> list[RetrievedMemory]:
        try:
            async with self._lock:
                records = self._load().get(employee_id, [])
            query_tokens = _tokens(query)
            if not query_tokens or limit <= 0:
                return []
            scored: list[tuple[float, dict[str, Any]]] = []
            for record in records:
                memory_tokens = _tokens(str(record.get("content", "")))
                if not memory_tokens:
                    continue
                score = len(query_tokens & memory_tokens) / len(query_tokens | memory_tokens)
                if score > _SCORE_THRESHOLD:
                    scored.append((score, record))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [
                RetrievedMemory(
                    memory_id=str(record["id"]),
                    content=str(record["content"]),
                    score=round(score, 4),
                )
                for score, record in scored[:limit]
            ]
        except Exception as exc:
            print(f"[memory] local retrieve failed (ignored): {exc}")
            return []

    async def write(self, employee_id: str, content: str) -> str | None:
        try:
            memory_id = f"mem-{uuid.uuid4().hex[:12]}"
            async with self._lock:
                data = self._load()
                data.setdefault(employee_id, []).append(
                    {"id": memory_id, "content": content, "created_at": utcnow().isoformat()}
                )
                self._save(data)
            return memory_id
        except Exception as exc:
            print(f"[memory] local write failed (ignored): {exc}")
            return None


class Mem0Adapter:
    """Hosted Mem0 Platform adapter behind the non-authoritative memory seam."""

    def __init__(self) -> None:
        try:
            from mem0 import MemoryClient
        except ImportError as exc:
            raise RuntimeError("install the optional extra: pip install .[mem0]") from exc
        api_key = get_settings().mem0_api_key
        if not api_key:
            raise RuntimeError("MEM0_API_KEY is required when IT_MEMORY_BACKEND=mem0")
        self._memory = MemoryClient(api_key=api_key)

    async def retrieve(
        self, employee_id: str, query: str, limit: int
    ) -> list[RetrievedMemory]:
        try:
            raw = await asyncio.to_thread(
                self._memory.search,
                query,
                filters={"user_id": employee_id},
                top_k=limit,
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
        except Exception as exc:
            print(f"[memory] mem0 retrieve failed (ignored): {exc}")
            return []

    async def write(self, employee_id: str, content: str) -> str | None:
        try:
            raw = await asyncio.to_thread(
                self._memory.add,
                messages=[{"role": "assistant", "content": content}],
                user_id=employee_id,
                metadata={"source": "ga-voiceai-support"},
            )
            items = raw.get("results", raw) if isinstance(raw, dict) else raw
            if isinstance(items, list) and items and isinstance(items[0], dict):
                memory_id = items[0].get("id")
                return str(memory_id) if memory_id is not None else None
            return None
        except Exception as exc:
            print(f"[memory] mem0 write failed (ignored): {exc}")
            return None


class NullMemory:
    """memory_backend='off' — remembers and recalls nothing."""

    async def retrieve(
        self, employee_id: str, query: str, limit: int
    ) -> list[RetrievedMemory]:
        return []

    async def write(self, employee_id: str, content: str) -> str | None:
        return None


_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    global _service
    if _service is None:
        backend = get_settings().memory_backend
        if backend == "mem0":
            try:
                _service = Mem0Adapter()
            except Exception as exc:
                print(f"[memory] Mem0 unavailable; memory disabled: {exc}")
                _service = NullMemory()
        elif backend == "off":
            _service = NullMemory()
        else:
            _service = LocalMemoryStore()
    return _service


def set_memory_service(service: MemoryService | None) -> None:
    """Test/demo hook."""
    global _service
    _service = service
