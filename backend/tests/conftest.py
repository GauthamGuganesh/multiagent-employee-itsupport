"""Shared fixtures: SQLite-backed repos, scripted FakeProvider, mock world,
in-memory graph via the real dispatcher, and Neo4j service stubs."""
import asyncio
import sys

import pytest
import pytest_asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import app.tools  # noqa: F401  (register all mock tools)
from app.api import dispatcher
from app.contracts.common import PrivilegeCheckResult
from app.db.base import Base, dispose_engine, init_engine
from app.graph.build import build_graph
from app.llm.provider import FakeProvider, set_provider
from app.memory.service import set_memory_service
from app.tools.mockworld import reset_world


class _NullMemory:
    async def retrieve(self, employee_id: str, query: str, limit: int = 5):
        return []

    async def write(self, employee_id: str, content: str):
        return None


@pytest_asyncio.fixture
async def db(tmp_path):
    init_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    from app.db.base import get_engine

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await dispose_engine()


@pytest.fixture
def provider():
    p = FakeProvider()
    set_provider(p)
    yield p
    set_provider(None)


@pytest.fixture(autouse=True)
def world():
    reset_world()
    yield
    reset_world()


@pytest.fixture(autouse=True)
def null_memory():
    set_memory_service(_NullMemory())
    yield
    set_memory_service(None)


@pytest.fixture
def graph(db, provider):
    g = build_graph()  # InMemorySaver
    dispatcher.set_graph(g)
    yield g
    dispatcher.set_graph(None)


@pytest.fixture
def org_stub(monkeypatch):
    """Deterministic Neo4j service stub. Tests adjust `grants`/`eligible`."""
    import app.org.service as org_service

    state = {
        "grants": set(),
        "eligible": {},  # privilege_key -> approver employee id
        "escalation_target": {
            "employee_id": "EMP-008",
            "employee_name": "Platform Manager",
            "employee_title": "Platform & IT Manager",
            "team_key": "it-support",
            "team_name": "IT Support",
            "level": 1,
        },
        "unavailable": False,
    }

    async def has_privilege(employee_id: str, privilege_key: str) -> PrivilegeCheckResult:
        if state["unavailable"]:
            return PrivilegeCheckResult(
                employee_id=employee_id, privilege_key=privilege_key,
                has_privilege=False, eligible_with_approval=False,
                error="neo4j_unavailable: connection refused",
            )
        return PrivilegeCheckResult(
            employee_id=employee_id,
            privilege_key=privilege_key,
            has_privilege=privilege_key in state["grants"],
            eligible_with_approval=privilege_key in state["eligible"],
            approver_employee_id=state["eligible"].get(privilege_key),
        )

    async def get_escalation_target(current_owner_id, system_key):
        if state["unavailable"]:
            return None
        return dict(state["escalation_target"])

    async def get_required_approver(employee_id, privilege_key):
        approver = state["eligible"].get(privilege_key)
        return {"id": approver, "name": f"Approver {approver}"} if approver else None

    async def get_employee_org_context(employee_id):
        return {"name": f"Employee {employee_id}", "id": employee_id}

    monkeypatch.setattr(org_service, "has_privilege", has_privilege)
    monkeypatch.setattr(org_service, "get_escalation_target", get_escalation_target)
    monkeypatch.setattr(org_service, "get_required_approver", get_required_approver)
    monkeypatch.setattr(org_service, "get_employee_org_context", get_employee_org_context)
    return state


# --- structured-output factories (keep tests terse) --------------------------

def supervisor_decision(**overrides) -> dict:
    base = {
        "decision": "route_to_specialist",
        "target_specialist": "identity",
        "workflow": None,
        "category": "identity",
        "intent": "account access issue",
        "risk_level": "medium",
        "autonomy_level": "confirm_required",
        "question_for_employee": None,
        "message_to_employee": None,
        "reason": "test decision",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def specialist_tool_step(tool_name: str, **params) -> dict:
    return {"action": "call_tool", "tool_call": {"tool_name": tool_name, "params": params}}


def specialist_finish(**overrides) -> dict:
    result = {
        "agent": "identity",
        "outcome": "resolved",
        "findings": [],
        "tools_used": [],
        "confidence": 0.9,
        "reasoning_summary": "test result",
        "question_for_employee": None,
        "handoff": None,
        "requested_action": None,
        "escalation_reason": None,
        "resolution_summary": "done",
    }
    result.update(overrides)
    return {"action": "finish", "tool_call": None, "result": result}
