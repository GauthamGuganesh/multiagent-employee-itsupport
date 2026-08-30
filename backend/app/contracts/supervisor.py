"""Supervisor structured-output contract."""
from pydantic import BaseModel, Field, model_validator

from app.contracts.enums import (
    AutonomyLevel,
    Category,
    RiskLevel,
    SpecialistName,
    SupervisorDecisionType,
    WorkflowName,
)


class SupervisorDecision(BaseModel):
    """One incremental routing decision. The supervisor never emits a
    multi-step plan — it decides the single next move from current state."""

    decision: SupervisorDecisionType
    target_specialist: SpecialistName | None = Field(
        default=None, description="Required when decision=route_to_specialist"
    )
    workflow: WorkflowName | None = Field(
        default=None, description="Required when decision=run_workflow"
    )
    # Routing metadata has safe defaults and is normalized by the supervisor
    # from the target/state. The model only has to express the next action.
    category: Category = "other"
    intent: str = Field(default="", description="Short statement of what the employee needs")
    risk_level: RiskLevel = "medium"
    autonomy_level: AutonomyLevel = "confirm_required"
    question_for_employee: str | None = Field(
        default=None, description="Required when decision=ask_employee"
    )
    message_to_employee: str | None = Field(
        default=None,
        description="Employee-facing closing message; required when decision=close_session",
    )
    reason: str = Field(default="", description="Concise audit-ready rationale for this decision")
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _decision_fields(self) -> "SupervisorDecision":
        if self.decision == "route_to_specialist" and not self.target_specialist:
            raise ValueError("route_to_specialist requires target_specialist")
        if self.decision == "run_workflow" and not self.workflow:
            raise ValueError("run_workflow requires workflow")
        if self.decision == "ask_employee" and not self.question_for_employee:
            raise ValueError("ask_employee requires question_for_employee")
        if self.decision == "close_session" and not self.message_to_employee:
            raise ValueError("close_session requires message_to_employee")
        return self

    @model_validator(mode="after")
    def _risk_constrains_autonomy(self) -> "SupervisorDecision":
        # Hard rule: high/critical risk can never be fully autonomous.
        if self.risk_level in ("high", "critical") and self.autonomy_level == "auto_resolve":
            raise ValueError(
                f"risk_level={self.risk_level} is incompatible with autonomy_level=auto_resolve; "
                "use confirm_required, approval_required, or human_only"
            )
        return self
