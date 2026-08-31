"""Shared literal types and enums used across contracts, state, and persistence."""
from enum import StrEnum
from typing import Literal

SpecialistName = Literal["identity", "endpoint", "network", "security"]
WorkflowName = Literal[
    "resolution", "confirmation", "approval", "escalation", "need_info", "ticket_status"
]
RiskLevel = Literal["low", "medium", "high", "critical"]
AutonomyLevel = Literal["auto_resolve", "confirm_required", "approval_required", "human_only"]
Category = Literal["identity", "endpoint", "network", "security", "ticketing", "other"]
Channel = Literal["web", "voice"]
TerminalStatus = Literal["resolved", "approval_pending", "escalated", "failed"]

SupervisorDecisionType = Literal[
    "route_to_specialist", "ask_employee", "run_workflow", "close_session"
]
SpecialistOutcome = Literal[
    "resolution_recommended",
    "need_more_information",
    "handoff_recommended",
    "approval_required",
    "escalation_required",
    "unable_to_resolve",
]
FailureType = Literal[
    "structured_output",
    "tool_failure",
    "budget_exhausted",
    "low_confidence",
    "out_of_domain",
    "internal_error",
]

SPECIALIST_NAMES: tuple[str, ...] = ("identity", "endpoint", "network", "security")
WORKFLOW_NAMES: tuple[str, ...] = (
    "resolution", "confirmation", "approval", "escalation", "need_info", "ticket_status",
)

RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class TicketStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_APPROVAL = "waiting_approval"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED = "escalated"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    WAITING_EMPLOYEE = "waiting_employee"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class EscalationTrigger(StrEnum):
    AGENT_RECOMMENDATION = "agent_recommendation"
    BUDGET_EXHAUSTED = "budget_exhausted"
    LOOP_GUARD = "loop_guard"
    PENDING_AGE = "pending_age"
    SECURITY = "security"
    STRUCTURED_OUTPUT_FAILURE = "structured_output_failure"
    OUT_OF_SCOPE = "out_of_scope"
    INFRASTRUCTURE = "infrastructure"
