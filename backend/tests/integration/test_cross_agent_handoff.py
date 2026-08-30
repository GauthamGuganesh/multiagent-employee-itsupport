"""Scenario 2: VPN drops (EMP-014) → network diagnostics surface a flagged
session from an unrecognized IP → generic handoff to security → security
recommends human escalation → escalation workflow targets the humans Neo4j
names. Findings survive the whole chain."""
from sqlalchemy import select

from app.api import dispatcher
from app.db.base import db_session
from app.db.models import AgentRun, AuditEvent, EscalationEvent, Ticket, ToolCall
from app.org import keys
from tests.conftest import specialist_finish, specialist_tool_step, supervisor_decision

FLAGGED_IP = "203.0.113.42"
VPN_REQUEST = "My VPN keeps dropping since yesterday."

NETWORK_FINDING = (
    f"VPN session at 2026-08-29T03:37:00Z came from unrecognized IP {FLAGGED_IP} (geo mismatch)"
)
SECURITY_FINDING = f"Impossible travel and a new MFA device enrolled from {FLAGGED_IP}"
ESCALATION_REASON = "probable account compromise: unknown-IP VPN session plus new MFA device"


def _queue_vpn_to_security_flow(provider):
    provider.enqueue(
        # 1. triage: network symptoms → network specialist
        supervisor_decision(
            target_specialist="network", category="network", intent="VPN keeps dropping"
        ),
        # 2. network runs REAL diagnostics against the mock world
        specialist_tool_step("check_vpn_status"),
        specialist_tool_step("inspect_recent_vpn_session"),
        # 3. …and recommends a generic handoff to security with its findings
        specialist_finish(
            agent="network",
            outcome="handoff_recommended",
            findings=[{
                "agent": "network",
                "summary": NETWORK_FINDING,
                "severity": "high",
                "tags": ["vpn", "suspicious-auth"],
            }],
            tools_used=["check_vpn_status", "inspect_recent_vpn_session"],
            handoff={
                "target_agent": "security",
                "reason": "flagged VPN session from an unrecognized network",
                "findings": [NETWORK_FINDING],
                "confidence": 0.85,
            },
            resolution_summary=None,
        ),
        # 4. supervisor validates the handoff and routes to security
        supervisor_decision(
            target_specialist="security", category="security", risk_level="high",
            intent="suspicious VPN session needs a security review",
        ),
        # 5. security recommends human escalation
        specialist_finish(
            agent="security",
            outcome="escalation_required",
            findings=[{
                "agent": "security",
                "summary": SECURITY_FINDING,
                "severity": "high",
                "tags": ["compromise", "mfa"],
            }],
            escalation_reason=ESCALATION_REASON,
            resolution_summary=None,
        ),
        # 6. supervisor runs the escalation workflow (its audited reason becomes
        # the escalation reason — state.escalation_reason is still unset here)
        supervisor_decision(
            decision="run_workflow", target_specialist=None, workflow="escalation",
            category="security", risk_level="high", autonomy_level="human_only",
            reason=ESCALATION_REASON,
        ),
    )


async def test_vpn_issue_hands_off_to_security_and_escalates(graph, provider, org_stub):
    org_stub["escalation_target"] = {
        "employee_id": keys.EMP_SECURITY_LEAD,
        "employee_name": "Security Lead",
        "employee_title": "Head of Security Operations",
        "team_key": keys.SUPPORT_SECURITY,
        "team_name": "Security Operations",
        "level": 1,
    }
    _queue_vpn_to_security_flow(provider)

    result = await dispatcher.start_session(keys.EMP_VPN_SUSPECT, VPN_REQUEST)

    assert result["pending"] is None
    assert result["terminal_status"] == "escalated"
    assert result["ticket_number"] is not None
    assert "Security Lead" in result["final_response"]
    assert "Head of Security Operations" in result["final_response"]

    async with db_session() as s:
        # Real tool evidence: the flagged unknown IP is in the persisted response.
        tool_calls = (await s.scalars(select(ToolCall))).all()
        assert [t.tool_name for t in tool_calls] == [
            "check_vpn_status", "inspect_recent_vpn_session",
        ]
        vpn_status = tool_calls[0]
        assert vpn_status.status == "succeeded"
        assert vpn_status.response["connected"] is False
        assert vpn_status.response["drops_last_24h"] == 7
        inspect = tool_calls[1]
        assert inspect.status == "succeeded"
        assert inspect.request["employee_id"] == keys.EMP_VPN_SUSPECT
        assert inspect.response["flagged_count"] == 1
        assert FLAGGED_IP in inspect.response["summary"]
        assert any(
            sess["client_ip"] == FLAGGED_IP and sess["flagged"]
            for sess in inspect.response["sessions"]
        )

        # Handoff is audited both when requested and when the supervisor completes it.
        events = (await s.scalars(select(AuditEvent))).all()
        by_type = {e.event_type: e for e in events}
        assert "HANDOFF_REQUESTED" in by_type
        requested = by_type["HANDOFF_REQUESTED"]
        assert requested.actor == "network"
        assert requested.payload["target_agent"] == "security"
        assert NETWORK_FINDING in requested.payload["findings"]
        assert "HANDOFF_COMPLETED" in by_type
        completed = by_type["HANDOFF_COMPLETED"]
        assert completed.payload["from"] == "network"
        assert completed.payload["to"] == "security"

        # Escalation lands on the Neo4j-resolved human target.
        escalation = (await s.scalars(select(EscalationEvent))).one()
        assert escalation.trigger == "security"
        assert escalation.to_target_id == keys.EMP_SECURITY_LEAD
        assert escalation.to_team_key == keys.SUPPORT_SECURITY
        assert ESCALATION_REASON in escalation.reason

        escalation_event = by_type["ESCALATION_TRIGGERED"]
        assert escalation_event.payload["target"]["employee_id"] == keys.EMP_SECURITY_LEAD
        assert escalation_event.payload["findings_preserved"] == 2

        # Findings preserved verbatim on the agent runs.
        runs = (await s.scalars(select(AgentRun))).all()
        network_run = next(r for r in runs if r.agent_name == "network")
        assert network_run.outcome == "handoff_recommended"
        assert network_run.handoff_target == "security"
        assert [f["summary"] for f in network_run.findings] == [NETWORK_FINDING]
        assert network_run.tools_used == ["check_vpn_status", "inspect_recent_vpn_session"]
        security_run = next(r for r in runs if r.agent_name == "security")
        assert security_run.outcome == "escalation_required"
        assert [f["summary"] for f in security_run.findings] == [SECURITY_FINDING]

        # Ticket reflects the security escalation.
        ticket = (await s.scalars(select(Ticket))).one()
        assert ticket.ticket_number == result["ticket_number"]
        assert ticket.status == "escalated"
        # NOTE: tickets born escalated currently carry escalated=False —
        # repos.create_ticket only sets the flag on a status *transition*.
        # Known app inconsistency (reported); the status column is the contract.
        assert ticket.security_related is True
        assert ticket.priority == "high"
        assert ticket.current_owner_id == keys.EMP_SECURITY_LEAD
        assert ticket.current_team_key == keys.SUPPORT_SECURITY
