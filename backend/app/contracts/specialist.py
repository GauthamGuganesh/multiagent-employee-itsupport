"""Specialist structured-output contracts: per-step decisions and final results."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.contracts.common import Finding, HandoffRequest, Params, RequestedAction, ToolParameter
from app.contracts.enums import SpecialistName, SpecialistOutcome


class ToolCallSpec(BaseModel):
    tool_name: str
    params: list[ToolParameter] = Field(default_factory=list)

    @field_validator("params", mode="before")
    @classmethod
    def _accept_legacy_param_map(cls, value):
        if isinstance(value, dict):
            return [{"key": key, "value": item} for key, item in value.items()]
        return value

    def params_dict(self) -> Params:
        return {parameter.key: parameter.value for parameter in self.params}


class SpecialistResult(BaseModel):
    """The single structured outcome a specialist returns to the supervisor."""

    # The runner pins this to the executing specialist after validation.
    agent: SpecialistName = "identity"
    outcome: SpecialistOutcome
    findings: list[Finding] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    reasoning_summary: str = Field(
        default="", description="Concise decision rationale suitable for audit — not chain-of-thought"
    )
    question_for_employee: str | None = Field(
        default=None, description="Required when outcome=need_more_information"
    )
    handoff: HandoffRequest | None = Field(
        default=None, description="Required when outcome=handoff_recommended"
    )
    requested_action: RequestedAction | None = Field(
        default=None,
        description="Required when outcome=approval_required; also set when a recommended resolution "
        "needs a privileged action executed via the confirmation workflow",
    )
    escalation_reason: str | None = Field(
        default=None, description="Required when outcome=escalation_required"
    )
    resolution_summary: str | None = Field(
        default=None, description="Required when outcome=resolution_recommended"
    )

    @model_validator(mode="after")
    def _outcome_fields(self) -> "SpecialistResult":
        if self.outcome == "need_more_information" and not self.question_for_employee:
            raise ValueError("need_more_information requires question_for_employee")
        if self.outcome == "handoff_recommended" and self.handoff is None:
            raise ValueError("handoff_recommended requires handoff")
        if self.outcome == "approval_required" and self.requested_action is None:
            raise ValueError("approval_required requires requested_action")
        if self.outcome == "escalation_required" and not self.escalation_reason:
            raise ValueError("escalation_required requires escalation_reason")
        if self.outcome == "resolution_recommended" and not self.resolution_summary:
            raise ValueError("resolution_recommended requires resolution_summary")
        return self


class SpecialistStep(BaseModel):
    """One iteration of the bounded Reason→Act→Observe→Decide loop."""

    action: Literal["call_tool", "finish"]
    tool_call: ToolCallSpec | None = None
    result: SpecialistResult | None = None

    @model_validator(mode="after")
    def _action_fields(self) -> "SpecialistStep":
        if self.action == "call_tool" and self.tool_call is None:
            raise ValueError("call_tool requires tool_call")
        if self.action == "finish" and self.result is None:
            raise ValueError("finish requires result")
        return self
