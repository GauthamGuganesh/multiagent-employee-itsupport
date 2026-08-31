"""Strongly typed LangGraph shared state.

Append-only collections use `operator.add` reducers so concurrent node updates
merge instead of overwrite. Scalars are last-write-wins, and each scalar has a
single writing node by convention (documented per field group).
"""
import operator
from typing import Annotated

from pydantic import BaseModel, Field

from app.contracts.common import (
    AgentFailure,
    ChatTurn,
    Finding,
    HumanTarget,
    PrivilegeCheckResult,
    RequestedAction,
    RetrievedMemory,
    ToolResult,
    Transition,
)
from app.contracts.enums import (
    AutonomyLevel,
    Category,
    Channel,
    RiskLevel,
    TerminalStatus,
)
from app.contracts.specialist import SpecialistResult


class SupportState(BaseModel):
    # --- identity & request (set once at session init) ---
    session_id: str
    employee_id: str
    channel: Channel = "web"
    original_request: str

    # --- conversational context (compacted view sent to LLMs) ---
    # recent_turns is deliberately last-write-wins: compaction must be able to
    # REPLACE the window (summary + last N turns). The complete transcript
    # lives in Postgres `messages` and is never affected by compaction.
    conversation_summary: str = ""
    recent_turns: list[ChatTurn] = Field(default_factory=list)
    memory_context: list[RetrievedMemory] = Field(default_factory=list)

    # Employee-turn counter: incremented each time new employee input is
    # ingested. Per-turn budgets reset against it and loop signatures include
    # it, so pre-reply decisions can never collide with post-reply ones.
    turn_index: int = 0

    # Set by the API dispatcher on each fresh (non-resume) invoke; the ingest
    # node appends it to recent_turns and clears it.
    incoming_message: str | None = None

    # --- triage (written by supervisor) ---
    category: Category | None = None
    intent: str | None = None
    risk_level: RiskLevel | None = None
    autonomy_level: AutonomyLevel | None = None

    # Secondary issues found in a multi-intent message. Captured at first triage
    # (last-write-wins; only the triage cycle writes it) so that handling the
    # primary issue can never silently drop the others — finalize_session opens
    # a tracked ticket for each remaining intent and tells the employee.
    pending_intents: list[str] = Field(default_factory=list)

    # --- routing & investigation ---
    current_agent: str | None = None
    previous_agents: Annotated[list[str], operator.add] = Field(default_factory=list)
    transition_history: Annotated[list[Transition], operator.add] = Field(default_factory=list)
    specialist_results: Annotated[list[SpecialistResult], operator.add] = Field(default_factory=list)
    specialist_findings: Annotated[list[Finding], operator.add] = Field(default_factory=list)
    tool_results: Annotated[list[ToolResult], operator.add] = Field(default_factory=list)
    agent_failures: Annotated[list[AgentFailure], operator.add] = Field(default_factory=list)

    # --- privileged-action pipeline (written by specialists/workflows) ---
    requested_action: RequestedAction | None = None
    privilege_check_result: PrivilegeCheckResult | None = None
    employee_confirmation: bool | None = None
    confirmation_id: str | None = None  # Postgres action_confirmations row

    # --- operational references (Postgres IDs) ---
    ticket_id: str | None = None
    ticket_number: str | None = None
    approval_id: str | None = None

    # --- escalation ---
    escalation_required: bool = False
    escalation_reason: str | None = None
    escalation_trigger: str | None = None  # EscalationTrigger value
    human_target: HumanTarget | None = None

    # --- hard budgets & loop detection (written by guards/supervisor only) ---
    # cycle/handoff budgets are PER EMPLOYEE TURN: the ingest node resets them
    # when new employee input arrives. total_agent_step_count is session-
    # lifetime telemetry and never resets.
    supervisor_cycle_count: int = 0
    total_agent_step_count: int = 0
    handoff_count: int = 0
    structured_output_failure_count: int = 0
    decision_signatures: Annotated[list[str], operator.add] = Field(default_factory=list)
    loop_guard_triggered: bool = False

    # --- interaction ---
    pending_question: str | None = None
    # This is deliberately session-lifetime, unlike per-turn execution
    # budgets. A new employee reply must not let the system interview them
    # indefinitely with differently worded versions of the same question.
    information_request_count: int = 0

    # A specialist proposes a resolution; only the employee can confirm that
    # the original issue is actually fixed.  This prevents a healthy snapshot
    # or successful tool call from silently closing the conversation.
    resolution_candidate: str | None = None
    awaiting_resolution_confirmation: bool = False
    resolution_confirmation_answer: str | None = None
    resolution_confirmed: bool | None = None

    # --- terminal ---
    terminal_status: TerminalStatus | None = None
    final_response: str | None = None
