"""Typed tool registry with registry-level privilege gating.

Every tool declares Pydantic input/output models. Privileged tools refuse to
execute unless the caller context is explicitly authorized by the
confirmation/approval workflows — specialists can only *recommend* them via
RequestedAction. This gate is code, not prompt.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from app.contracts.common import Params, ToolResult
from app.contracts.enums import RiskLevel
from app.db.base import db_session
from app.db.models import ToolCall
from app.events.recorder import record
from app.events.types import EventType

TOOL_TIMEOUT_SECONDS = 10.0


class ToolExecutionError(Exception):
    pass


class PrivilegedToolBlocked(ToolExecutionError):
    """Raised when a privileged tool is invoked outside an authorized workflow."""


@dataclass
class ToolContext:
    session_id: str | None = None
    employee_id: str | None = None
    agent_name: str = "system"
    agent_run_id: str | None = None
    # True ONLY when set by the confirmation/approval execution paths.
    authorized_privileged: bool = False


@dataclass
class ToolSpec:
    name: str
    description: str
    domain: str  # identity | endpoint | network | security | ticketing
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], Awaitable[BaseModel]]
    privileged: bool = False
    privilege_key: str | None = None
    system_key: str | None = None
    risk_level: RiskLevel = "low"
    tags: list[str] = field(default_factory=list)


_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in _REGISTRY:
        raise ValueError(f"duplicate tool registration: {spec.name}")
    if spec.privileged and not spec.privilege_key:
        raise ValueError(f"privileged tool {spec.name} must declare privilege_key")
    _REGISTRY[spec.name] = spec
    return spec


def get_tool(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def tools_for_domain(domain: str) -> list[ToolSpec]:
    return [t for t in _REGISTRY.values() if t.domain == domain]


def all_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def describe_tools(names: list[str]) -> str:
    """Prompt-ready tool catalog for a specialist's allowlist."""
    lines = []
    for name in names:
        spec = _REGISTRY.get(name)
        if spec is None:
            continue
        params = ", ".join(
            f"{k}: {getattr(v.annotation, '__name__', str(v.annotation))}"
            for k, v in spec.input_model.model_fields.items()
        )
        gate = " [privileged — recommend via requested_action, do not call]" if spec.privileged else ""
        lines.append(f"- {name}({params}): {spec.description}{gate}")
    return "\n".join(lines)


async def execute_tool(name: str, params: Params, context: ToolContext) -> ToolResult:
    """Validate, gate, execute, persist, and broadcast one tool call.

    Never raises for tool-level failures — returns ToolResult(status=failed)
    so specialists can reason about degraded evidence. Privilege violations
    also return a failed result (and are audited) rather than crashing.
    """
    spec = _REGISTRY.get(name)
    started = time.monotonic()

    async def _finish(
        status: str, response: dict[str, Any] | None, error: str | None, summary: str
    ) -> ToolResult:
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            async with db_session() as s:
                s.add(
                    ToolCall(
                        agent_run_id=context.agent_run_id,
                        session_id=context.session_id,
                        tool_name=name,
                        request=dict(params),
                        response=response,
                        status=status,
                        error=error,
                        duration_ms=duration_ms,
                    )
                )
            await record(
                EventType.TOOL_SUCCEEDED if status == "succeeded" else EventType.TOOL_FAILED,
                session_id=context.session_id,
                actor=context.agent_name,
                payload={"tool": name, "status": status, "error": error, "duration_ms": duration_ms},
            )
        except Exception:
            # Postgres degradation: the tool result still flows back to the
            # agent; the API layer owns the outage response. Nothing broadcast.
            pass
        return ToolResult(
            tool_name=name,
            agent=context.agent_name,
            status=status,
            request=dict(params),
            response_summary=summary,
            error=error,
        )

    if spec is None:
        return await _finish("failed", None, f"unknown tool: {name}", f"Tool {name} does not exist.")

    try:
        await record(
            EventType.TOOL_CALLED,
            session_id=context.session_id,
            actor=context.agent_name,
            payload={"tool": name, "params": dict(params)},
        )
    except Exception:
        pass

    if spec.privileged and not context.authorized_privileged:
        return await _finish(
            "failed",
            None,
            "privileged_tool_blocked",
            f"{name} is a privileged action and can only run through the "
            "confirmation or approval workflow.",
        )

    try:
        validated = spec.input_model.model_validate(dict(params))
    except ValidationError as exc:
        return await _finish("failed", None, f"invalid params: {exc}", f"Invalid parameters for {name}.")

    try:
        output = await asyncio.wait_for(spec.handler(validated, context), timeout=TOOL_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return await _finish("failed", None, "timeout", f"{name} timed out after {TOOL_TIMEOUT_SECONDS}s.")
    except Exception as exc:
        return await _finish("failed", None, str(exc), f"{name} failed: {exc}")

    dump = output.model_dump(mode="json")
    summary = getattr(output, "summary", None) or _summarize(dump)
    return await _finish("succeeded", dump, None, summary)


def _summarize(dump: dict[str, Any]) -> str:
    parts = [f"{k}={v}" for k, v in list(dump.items())[:6]]
    return "; ".join(parts)[:500]
