"""Operational + audit persistence models.

Org references (EMP-xxx ids, team/privilege keys) are logical pointers into
Neo4j — the hierarchy itself is never duplicated here. JSON columns store
Pydantic dumps of structured contracts (findings, tool payloads), keeping the
timeline reconstructable without re-running anything.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

JsonCol = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SupportSession(Base):
    __tablename__ = "support_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    employee_id: Mapped[str] = mapped_column(String(16), index=True)
    channel: Mapped[str] = mapped_column(String(8), default="web")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    # Triage snapshot (last-write-wins, mirrors state) so session lists/metrics
    # never need to parse audit payloads.
    original_request: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str | None] = mapped_column(String(16), index=True)
    intent: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(8))
    autonomy_level: Mapped[str | None] = mapped_column(String(24))
    terminal_status: Mapped[str | None] = mapped_column(String(24))
    final_response: Mapped[str | None] = mapped_column(Text)
    conversation_summary: Mapped[str] = mapped_column(Text, default="")
    langgraph_thread_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("support_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # employee | assistant | system
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(8), default="web")  # web | voice
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    ticket_number: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # IT-1001
    session_id: Mapped[str | None] = mapped_column(ForeignKey("support_sessions.id"))
    requester_employee_id: Mapped[str] = mapped_column(String(16), index=True)
    category: Mapped[str] = mapped_column(String(16), default="other")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(8), default="medium")  # low|medium|high|critical
    current_owner_id: Mapped[str | None] = mapped_column(String(16), index=True)
    current_team_key: Mapped[str | None] = mapped_column(String(32), index=True)
    originating_agent: Mapped[str | None] = mapped_column(String(24))
    security_related: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    changed_by: Mapped[str] = mapped_column(String(32), default="system")  # EMP-xxx | system | agent name
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("support_sessions.id"), index=True)
    agent_name: Mapped[str] = mapped_column(String(24), index=True)
    run_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="started")  # started|completed|failed
    outcome: Mapped[str | None] = mapped_column(String(32), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    reasoning_summary: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list | None] = mapped_column(JsonCol)
    tools_used: Mapped[list | None] = mapped_column(JsonCol)
    handoff_target: Mapped[str | None] = mapped_column(String(24))
    structured_output_retries: Mapped[int] = mapped_column(Integer, default=0)
    loop_guard_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    # Full serialized structured output (SupervisorDecision / SpecialistResult)
    # so the ops timeline can render it without reconstruction.
    result: Mapped[dict | None] = mapped_column(JsonCol)
    # AgentFailure persistence (queryable for ops filters/metrics)
    failure_type: Mapped[str | None] = mapped_column(String(32), index=True)
    failure_detail: Mapped[str | None] = mapped_column(Text)
    recoverable: Mapped[bool | None] = mapped_column(Boolean)
    # Memory observability: [{memory_id, content, score, included_in_context}]
    memories_retrieved: Mapped[list | None] = mapped_column(JsonCol)
    # [{memory_id, content}] written at this run's checkpoint (if any)
    memories_written: Mapped[list | None] = mapped_column(JsonCol)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("support_sessions.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(48), index=True)
    request: Mapped[dict | None] = mapped_column(JsonCol)
    response: Mapped[dict | None] = mapped_column(JsonCol)
    status: Mapped[str] = mapped_column(String(16), default="succeeded")  # succeeded|failed
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("support_sessions.id"))
    requester_employee_id: Mapped[str] = mapped_column(String(16), index=True)
    approver_employee_id: Mapped[str] = mapped_column(String(16), index=True)
    privilege_key: Mapped[str] = mapped_column(String(48))
    system_key: Mapped[str | None] = mapped_column(String(48))
    action_summary: Mapped[str] = mapped_column(Text)
    # Full RequestedAction snapshot so an approved action is executable from
    # durable state after the originating session has ended.
    action_key: Mapped[str | None] = mapped_column(String(48))
    params: Mapped[dict | None] = mapped_column(JsonCol)
    risk_level: Mapped[str] = mapped_column(String(8), default="medium")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(16))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EscalationEvent(Base):
    __tablename__ = "escalation_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("support_sessions.id"))
    reason: Mapped[str] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(32), index=True)
    from_owner_id: Mapped[str | None] = mapped_column(String(16))
    to_target_id: Mapped[str | None] = mapped_column(String(16), index=True)
    to_team_key: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionConfirmation(Base):
    __tablename__ = "action_confirmations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("support_sessions.id"), index=True)
    employee_id: Mapped[str] = mapped_column(String(16))
    action_key: Mapped[str] = mapped_column(String(48))
    action_summary: Mapped[str] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JsonCol)
    confirmed: Mapped[bool | None] = mapped_column(Boolean)  # null until answered
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionExecution(Base):
    __tablename__ = "action_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("support_sessions.id"), index=True)
    confirmation_id: Mapped[str | None] = mapped_column(ForeignKey("action_confirmations.id"))
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approval_requests.id"))
    action_key: Mapped[str] = mapped_column(String(48))
    params: Mapped[dict | None] = mapped_column(JsonCol)
    result: Mapped[dict | None] = mapped_column(JsonCol)
    status: Mapped[str] = mapped_column(String(16), default="succeeded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(String(32), index=True)
    ticket_id: Mapped[str | None] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    actor: Mapped[str] = mapped_column(String(32), default="system")
    payload: Mapped[dict | None] = mapped_column(JsonCol)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


Index("ix_audit_session_time", AuditEvent.session_id, AuditEvent.created_at)
Index("ix_tickets_status_pending", Ticket.status, Ticket.pending_since)
