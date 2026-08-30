"""Shared structured objects: findings, tool results, actions, handoffs, memory."""
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from app.contracts.enums import FailureType, RiskLevel, SpecialistName

# Bounded scalar param type for tool arguments. Validated against each tool's
# input model before execution — never executed as-is.
ParamValue = str | int | bool
Params = dict[str, ParamValue]


class ToolParameter(BaseModel):
    """One simple, strict-schema-safe tool parameter supplied by an LLM."""

    key: str = Field(min_length=1)
    value: ParamValue


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatTurn(BaseModel):
    role: str  # employee | assistant
    content: str
    at: datetime = Field(default_factory=utcnow)


class Finding(BaseModel):
    # The specialist runner assigns the authoritative agent name. Keeping this
    # optional in model output avoids asking the LLM to repeat known context.
    agent: str = ""
    summary: str = Field(description="One auditable sentence stating the observation")
    detail: str = ""
    severity: RiskLevel = "low"
    tags: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    tool_name: str
    agent: str
    status: str  # succeeded | failed
    request: Params = Field(default_factory=dict)
    response_summary: str = ""
    error: str | None = None


class RequestedAction(BaseModel):
    """A privileged action a specialist recommends. Executed ONLY via the
    confirmation or approval workflows, never directly by a specialist."""

    action_key: str = Field(description="Registered executable tool name, e.g. 'unlock_account'")
    summary: str = Field(description="Exact human-readable statement of what will be done")
    privilege_key: str = Field(description="Neo4j privilege key required for this action")
    system_key: str | None = None
    # OpenAI strict structured output cannot accept arbitrary JSON maps. The
    # workflow converts this compact typed list back to a trusted dictionary.
    params: list[ToolParameter] = Field(default_factory=list)
    risk_level: RiskLevel = "medium"

    @field_validator("params", mode="before")
    @classmethod
    def _accept_legacy_param_map(cls, value):
        if isinstance(value, dict):
            return [{"key": key, "value": item} for key, item in value.items()]
        return value

    def params_dict(self) -> Params:
        return {parameter.key: parameter.value for parameter in self.params}


class PrivilegeCheckResult(BaseModel):
    employee_id: str
    privilege_key: str
    has_privilege: bool
    eligible_with_approval: bool = False
    approver_employee_id: str | None = None
    source: str = "neo4j"  # provenance guard: never Mem0
    # Fail-closed marker: set when Neo4j was unreachable — has_privilege is
    # False NOT because access was denied but because it could not be proven.
    error: str | None = None


class HandoffRequest(BaseModel):
    """The single generic agent-to-agent handoff contract."""

    outcome: str = "handoff"
    target_agent: SpecialistName
    reason: str
    findings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class AgentFailure(BaseModel):
    agent: str
    failure_type: FailureType
    detail: str
    recoverable: bool = False


class Transition(BaseModel):
    from_node: str
    to_node: str
    reason: str = ""


class HumanTarget(BaseModel):
    employee_id: str | None = None
    employee_name: str | None = None
    employee_title: str | None = None
    team_key: str | None = None
    team_name: str | None = None


class RetrievedMemory(BaseModel):
    memory_id: str
    content: str
    score: float | None = None
    included_in_context: bool = True
