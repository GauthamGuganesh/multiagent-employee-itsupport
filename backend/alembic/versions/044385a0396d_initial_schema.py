"""initial schema

Revision ID: 044385a0396d
Revises:
Create Date: 2026-08-30 14:33:44.149101
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '044385a0396d'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "support_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("employee_id", sa.String(16), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False, server_default="web"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("original_request", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(16)), sa.Column("intent", sa.Text()),
        sa.Column("risk_level", sa.String(8)), sa.Column("autonomy_level", sa.String(24)),
        sa.Column("terminal_status", sa.String(24)), sa.Column("final_response", sa.Text()),
        sa.Column("conversation_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("langgraph_thread_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_support_sessions_employee_id", "support_sessions", ["employee_id"])
    op.create_index("ix_support_sessions_status", "support_sessions", ["status"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="web"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])

    op.create_table(
        "tickets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("ticket_number", sa.String(16), nullable=False, unique=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id")),
        sa.Column("requester_employee_id", sa.String(16), nullable=False),
        sa.Column("category", sa.String(16), nullable=False, server_default="other"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(8), nullable=False, server_default="medium"),
        sa.Column("current_owner_id", sa.String(16)), sa.Column("current_team_key", sa.String(32)),
        sa.Column("originating_agent", sa.String(24)),
        sa.Column("security_related", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pending_since", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (
        ("ix_tickets_ticket_number", ["ticket_number"]),
        ("ix_tickets_requester_employee_id", ["requester_employee_id"]),
        ("ix_tickets_status", ["status"]),
        ("ix_tickets_current_owner_id", ["current_owner_id"]),
        ("ix_tickets_current_team_key", ["current_team_key"]),
        ("ix_tickets_pending_since", ["pending_since"]),
        ("ix_tickets_created_at", ["created_at"]),
        ("ix_tickets_status_pending", ["status", "pending_since"]),
    ):
        op.create_index(name, "tickets", columns)

    op.create_table(
        "ticket_status_history",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("from_status", sa.String(24)), sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("changed_by", sa.String(32), nullable=False, server_default="system"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ticket_status_history_ticket_id", "ticket_status_history", ["ticket_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id"), nullable=False),
        sa.Column("agent_name", sa.String(24), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="started"),
        sa.Column("outcome", sa.String(32)), sa.Column("confidence", sa.Float()),
        sa.Column("reasoning_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("findings", jsonb), sa.Column("tools_used", jsonb),
        sa.Column("handoff_target", sa.String(24)),
        sa.Column("structured_output_retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("loop_guard_triggered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("result", jsonb), sa.Column("failure_type", sa.String(32)),
        sa.Column("failure_detail", sa.Text()), sa.Column("recoverable", sa.Boolean()),
        sa.Column("memories_retrieved", jsonb), sa.Column("memories_written", jsonb),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for name, columns in (("ix_agent_runs_session_id", ["session_id"]), ("ix_agent_runs_agent_name", ["agent_name"]), ("ix_agent_runs_outcome", ["outcome"]), ("ix_agent_runs_failure_type", ["failure_type"])):
        op.create_index(name, "agent_runs", columns)

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("agent_run_id", sa.String(32), sa.ForeignKey("agent_runs.id")),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id"), nullable=False),
        sa.Column("tool_name", sa.String(48), nullable=False),
        sa.Column("request", jsonb), sa.Column("response", jsonb),
        sa.Column("status", sa.String(16), nullable=False, server_default="succeeded"),
        sa.Column("error", sa.Text()), sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_tool_calls_agent_run_id", ["agent_run_id"]), ("ix_tool_calls_session_id", ["session_id"]), ("ix_tool_calls_tool_name", ["tool_name"])):
        op.create_index(name, "tool_calls", columns)

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.id")),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id")),
        sa.Column("requester_employee_id", sa.String(16), nullable=False),
        sa.Column("approver_employee_id", sa.String(16), nullable=False),
        sa.Column("privilege_key", sa.String(48), nullable=False), sa.Column("system_key", sa.String(48)),
        sa.Column("action_summary", sa.Text(), nullable=False), sa.Column("action_key", sa.String(48)),
        sa.Column("params", jsonb), sa.Column("risk_level", sa.String(8), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decision_reason", sa.Text()), sa.Column("decided_by", sa.String(16)),
        sa.Column("decided_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_approval_requests_ticket_id", ["ticket_id"]), ("ix_approval_requests_requester_employee_id", ["requester_employee_id"]), ("ix_approval_requests_approver_employee_id", ["approver_employee_id"]), ("ix_approval_requests_status", ["status"])):
        op.create_index(name, "approval_requests", columns)

    op.create_table(
        "escalation_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("ticket_id", sa.String(32), sa.ForeignKey("tickets.id")),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id")),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("trigger", sa.String(32), nullable=False),
        sa.Column("from_owner_id", sa.String(16)), sa.Column("to_target_id", sa.String(16)),
        sa.Column("to_team_key", sa.String(32)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_escalation_events_ticket_id", ["ticket_id"]), ("ix_escalation_events_trigger", ["trigger"]), ("ix_escalation_events_to_target_id", ["to_target_id"])):
        op.create_index(name, "escalation_events", columns)

    op.create_table(
        "action_confirmations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id"), nullable=False),
        sa.Column("employee_id", sa.String(16), nullable=False), sa.Column("action_key", sa.String(48), nullable=False),
        sa.Column("action_summary", sa.Text(), nullable=False), sa.Column("params", jsonb),
        sa.Column("confirmed", sa.Boolean()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_action_confirmations_session_id", "action_confirmations", ["session_id"])

    op.create_table(
        "action_executions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("support_sessions.id")),
        sa.Column("confirmation_id", sa.String(32), sa.ForeignKey("action_confirmations.id")),
        sa.Column("approval_id", sa.String(32), sa.ForeignKey("approval_requests.id")),
        sa.Column("action_key", sa.String(48), nullable=False), sa.Column("params", jsonb), sa.Column("result", jsonb),
        sa.Column("status", sa.String(16), nullable=False, server_default="succeeded"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_action_executions_session_id", "action_executions", ["session_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(32), primary_key=True), sa.Column("session_id", sa.String(32)),
        sa.Column("ticket_id", sa.String(32)), sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("actor", sa.String(32), nullable=False, server_default="system"), sa.Column("payload", jsonb),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name, columns in (("ix_audit_events_session_id", ["session_id"]), ("ix_audit_events_ticket_id", ["ticket_id"]), ("ix_audit_events_event_type", ["event_type"]), ("ix_audit_events_created_at", ["created_at"]), ("ix_audit_session_time", ["session_id", "created_at"])):
        op.create_index(name, "audit_events", columns)


def downgrade() -> None:
    for table in ("audit_events", "action_executions", "action_confirmations", "escalation_events", "approval_requests", "tool_calls", "agent_runs", "ticket_status_history", "tickets", "messages", "support_sessions"):
        op.drop_table(table)
