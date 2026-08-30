"""Scenario 4: EMP-032 asks for Docker Desktop but lacks dev-tools-install —
the confirmation workflow branches into approval with the Neo4j-resolved
approver (EMP-007), and the deterministic post-decision executor runs the
persisted action only on approval."""
from sqlalchemy import select

from app.api import dispatcher
from app.db.base import db_session
from app.db.models import ActionExecution, ApprovalRequest, AuditEvent, Message, Ticket
from app.graph.workflows.approval import decide_approval_request
from app.org import keys
from tests.conftest import specialist_finish, specialist_tool_step, supervisor_decision

DOCKER_REQUEST = "Can you install Docker Desktop on my laptop?"


def _queue_docker_install_flow(provider):
    """Supervisor → endpoint (device check → approval_required) → confirmation."""
    provider.enqueue(
        supervisor_decision(
            target_specialist="endpoint",
            category="endpoint",
            intent="install Docker Desktop",
        ),
        specialist_tool_step("get_device_details"),
        specialist_finish(
            agent="endpoint",
            outcome="approval_required",
            findings=[{
                "agent": "endpoint",
                "summary": "Docker Desktop is not installed; installing it requires the dev-tools privilege",
                "severity": "low",
                "tags": ["software-install"],
            }],
            resolution_summary=None,
            requested_action={
                "action_key": "install_approved_software",
                "summary": f"Install Docker Desktop on the managed laptop of {keys.EMP_FRONTEND_ENG}.",
                "privilege_key": keys.PRIV_DEV_TOOLS_INSTALL,
                "system_key": keys.SYSTEM_MDM,
                "params": {"software_name": "Docker Desktop"},
                "risk_level": "medium",
            },
        ),
        supervisor_decision(
            decision="run_workflow",
            target_specialist=None,
            workflow="confirmation",
            category="endpoint",
        ),
    )


async def _start_docker_session(provider, org_stub) -> dict:
    # NOT granted, but eligible with approval from the Engineering Manager.
    org_stub["eligible"][keys.PRIV_DEV_TOOLS_INSTALL] = keys.EMP_ENG_MANAGER
    _queue_docker_install_flow(provider)
    return await dispatcher.start_session(keys.EMP_FRONTEND_ENG, DOCKER_REQUEST)


async def test_missing_privilege_routes_to_approval(graph, provider, org_stub):
    result = await _start_docker_session(provider, org_stub)

    # Session ends approval_pending — no interrupt, no execution yet.
    assert result["pending"] is None
    assert result["terminal_status"] == "approval_pending"
    assert result["approval_id"] is not None
    assert result["ticket_number"] is not None

    async with db_session() as s:
        approval = (await s.scalars(select(ApprovalRequest))).one()
        assert approval.id == result["approval_id"]
        assert approval.status == "pending"
        assert approval.approver_employee_id == keys.EMP_ENG_MANAGER
        assert approval.requester_employee_id == keys.EMP_FRONTEND_ENG
        assert approval.privilege_key == keys.PRIV_DEV_TOOLS_INSTALL
        # The full RequestedAction snapshot is persisted for later execution.
        assert approval.action_key == "install_approved_software"
        assert approval.params == {"software_name": "Docker Desktop"}

        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.status == "waiting_approval"
        assert ticket.ticket_number == result["ticket_number"]
        assert approval.ticket_id == ticket.id

        # Nothing executed while the request is pending.
        assert (await s.scalars(select(ActionExecution))).all() == []
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert "APPROVAL_REQUESTED" in events
    assert "ACTION_EXECUTED" not in events

    # Employee-facing message mentions the approval and the tracking ticket.
    assert "approval" in result["final_response"].lower()
    assert result["ticket_number"] in result["final_response"]


async def test_approved_request_executes_and_notifies(graph, provider, org_stub):
    result = await _start_docker_session(provider, org_stub)
    approval_id = result["approval_id"]
    session_id = result["session_id"]

    decision = await decide_approval_request(
        approval_id, approved=True, decided_by=keys.EMP_ENG_MANAGER, reason="ok"
    )
    assert decision == {"ok": True, "approved": True, "execution_status": "succeeded"}

    async with db_session() as s:
        approval = (await s.scalars(select(ApprovalRequest))).one()
        assert approval.status == "approved"
        assert approval.decided_by == keys.EMP_ENG_MANAGER

        execution = (await s.scalars(select(ActionExecution))).one()
        assert execution.approval_id == approval_id
        assert execution.action_key == "install_approved_software"
        assert execution.status == "succeeded"

        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.status == "resolved"

        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
        messages = (
            await s.scalars(
                select(Message)
                .where(Message.session_id == session_id, Message.role == "assistant")
                .order_by(Message.created_at)
            )
        ).all()
    assert {"APPROVAL_DECIDED", "HUMAN_INTERVENTION", "ACTION_EXECUTED"} <= events

    # The employee was notified in their session thread.
    notification = messages[-1].content
    assert "approved" in notification
    assert keys.EMP_ENG_MANAGER in notification

    # The mock world actually changed for the requester.
    from app.tools.mockworld import get_world

    installed = get_world().state_for(keys.EMP_FRONTEND_ENG)["device"]["installed_software"]
    assert "Docker Desktop" in installed


async def test_rejected_request_never_executes(graph, provider, org_stub):
    result = await _start_docker_session(provider, org_stub)
    approval_id = result["approval_id"]

    decision = await decide_approval_request(
        approval_id,
        approved=False,
        decided_by=keys.EMP_ENG_MANAGER,
        reason="not required for this role",
    )
    assert decision == {"ok": True, "approved": False, "execution_status": None}

    async with db_session() as s:
        approval = (await s.scalars(select(ApprovalRequest))).one()
        assert approval.status == "rejected"

        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.status == "closed"

        assert (await s.scalars(select(ActionExecution))).all() == []
        events = {e.event_type for e in (await s.scalars(select(AuditEvent))).all()}
    assert "APPROVAL_DECIDED" in events
    assert "ACTION_EXECUTED" not in events

    from app.tools.mockworld import get_world

    installed = get_world().state_for(keys.EMP_FRONTEND_ENG)["device"]["installed_software"]
    assert "Docker Desktop" not in installed
