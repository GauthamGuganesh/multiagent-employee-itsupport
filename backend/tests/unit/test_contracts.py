"""Contract validators: SupervisorDecision, SpecialistResult, SpecialistStep,
HandoffRequest. These are the schema-level guarantees the retry machinery and
guards rely on — an invalid combination must raise, a valid one must parse."""
import pytest
from pydantic import ValidationError

from app.contracts.common import HandoffRequest
from app.contracts.specialist import SpecialistResult, SpecialistStep
from app.contracts.supervisor import SupervisorDecision
from tests.conftest import specialist_finish, specialist_tool_step, supervisor_decision


def _result(**overrides) -> dict:
    """Raw SpecialistResult payload (the factory wraps it in a step)."""
    return specialist_finish(**overrides)["result"]


HANDOFF = {
    "target_agent": "security",
    "reason": "unusual auth events need a security review",
    "findings": ["login from unrecognized IP"],
    "confidence": 0.8,
}

REQUESTED_ACTION = {
    "action_key": "unlock_account",
    "summary": "Unlock the account for EMP-034.",
    "privilege_key": "self-account-unlock",
    "system_key": "okta",
    "params": {},
    "risk_level": "medium",
}


# --- SupervisorDecision: decision-specific required fields -------------------

def test_route_to_specialist_requires_target():
    with pytest.raises(ValidationError, match="route_to_specialist requires target_specialist"):
        SupervisorDecision.model_validate(
            supervisor_decision(decision="route_to_specialist", target_specialist=None)
        )


def test_route_to_specialist_with_target_parses():
    decision = SupervisorDecision.model_validate(
        supervisor_decision(decision="route_to_specialist", target_specialist="network")
    )
    assert decision.target_specialist == "network"


def test_run_workflow_requires_workflow():
    with pytest.raises(ValidationError, match="run_workflow requires workflow"):
        SupervisorDecision.model_validate(
            supervisor_decision(decision="run_workflow", target_specialist=None, workflow=None)
        )


def test_ask_employee_requires_question():
    with pytest.raises(ValidationError, match="ask_employee requires question_for_employee"):
        SupervisorDecision.model_validate(
            supervisor_decision(
                decision="ask_employee", target_specialist=None, question_for_employee=None
            )
        )


def test_ask_employee_with_question_parses():
    decision = SupervisorDecision.model_validate(
        supervisor_decision(
            decision="ask_employee",
            target_specialist=None,
            question_for_employee="Which system can't you reach?",
        )
    )
    assert decision.question_for_employee == "Which system can't you reach?"


def test_close_session_requires_message():
    with pytest.raises(ValidationError, match="close_session requires message_to_employee"):
        SupervisorDecision.model_validate(
            supervisor_decision(
                decision="close_session", target_specialist=None, message_to_employee=None
            )
        )


def test_close_session_with_message_parses():
    decision = SupervisorDecision.model_validate(
        supervisor_decision(
            decision="close_session",
            target_specialist=None,
            message_to_employee="All set — your account is active again.",
        )
    )
    assert decision.message_to_employee.startswith("All set")


# --- SupervisorDecision: risk constrains autonomy ----------------------------

@pytest.mark.parametrize("risk", ["high", "critical"])
def test_high_risk_rejects_auto_resolve(risk):
    with pytest.raises(ValidationError, match="incompatible with autonomy_level=auto_resolve"):
        SupervisorDecision.model_validate(
            supervisor_decision(risk_level=risk, autonomy_level="auto_resolve")
        )


@pytest.mark.parametrize("autonomy", ["confirm_required", "approval_required", "human_only"])
def test_high_risk_allows_non_autonomous_levels(autonomy):
    decision = SupervisorDecision.model_validate(
        supervisor_decision(risk_level="high", autonomy_level=autonomy)
    )
    assert decision.autonomy_level == autonomy


@pytest.mark.parametrize("risk", ["low", "medium"])
def test_lower_risk_allows_auto_resolve(risk):
    decision = SupervisorDecision.model_validate(
        supervisor_decision(risk_level=risk, autonomy_level="auto_resolve")
    )
    assert decision.autonomy_level == "auto_resolve"


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        SupervisorDecision.model_validate(supervisor_decision(confidence=1.5))
    with pytest.raises(ValidationError):
        SupervisorDecision.model_validate(supervisor_decision(confidence=-0.1))


# --- SpecialistResult: outcome-specific required fields (all six) ------------

def test_resolved_requires_resolution_summary():
    with pytest.raises(ValidationError, match="resolved requires resolution_summary"):
        SpecialistResult.model_validate(_result(outcome="resolved", resolution_summary=None))
    ok = SpecialistResult.model_validate(
        _result(outcome="resolved", resolution_summary="cleared the disk")
    )
    assert ok.resolution_summary == "cleared the disk"


def test_need_more_information_requires_question():
    with pytest.raises(ValidationError, match="need_more_information requires question_for_employee"):
        SpecialistResult.model_validate(
            _result(outcome="need_more_information", resolution_summary=None)
        )
    ok = SpecialistResult.model_validate(
        _result(
            outcome="need_more_information",
            resolution_summary=None,
            question_for_employee="Which network are you on?",
        )
    )
    assert ok.question_for_employee == "Which network are you on?"


def test_handoff_recommended_requires_handoff():
    with pytest.raises(ValidationError, match="handoff_recommended requires handoff"):
        SpecialistResult.model_validate(
            _result(outcome="handoff_recommended", resolution_summary=None)
        )
    ok = SpecialistResult.model_validate(
        _result(outcome="handoff_recommended", resolution_summary=None, handoff=HANDOFF)
    )
    assert ok.handoff.target_agent == "security"


def test_approval_required_requires_requested_action():
    with pytest.raises(ValidationError, match="approval_required requires requested_action"):
        SpecialistResult.model_validate(
            _result(outcome="approval_required", resolution_summary=None)
        )
    ok = SpecialistResult.model_validate(
        _result(
            outcome="approval_required",
            resolution_summary=None,
            requested_action=REQUESTED_ACTION,
        )
    )
    assert ok.requested_action.action_key == "unlock_account"


def test_escalation_required_requires_reason():
    with pytest.raises(ValidationError, match="escalation_required requires escalation_reason"):
        SpecialistResult.model_validate(
            _result(outcome="escalation_required", resolution_summary=None)
        )
    ok = SpecialistResult.model_validate(
        _result(
            outcome="escalation_required",
            resolution_summary=None,
            escalation_reason="suspected account compromise",
        )
    )
    assert ok.escalation_reason == "suspected account compromise"


def test_unable_to_resolve_needs_no_extra_fields():
    ok = SpecialistResult.model_validate(
        _result(outcome="unable_to_resolve", resolution_summary=None)
    )
    assert ok.outcome == "unable_to_resolve"
    assert ok.resolution_summary is None


def test_specialist_result_confidence_bounds():
    with pytest.raises(ValidationError):
        SpecialistResult.model_validate(_result(confidence=1.01))


# --- SpecialistStep ----------------------------------------------------------

def test_step_action_must_be_known():
    with pytest.raises(ValidationError, match="call_tool.*finish"):
        SpecialistStep.model_validate({"action": "investigate", "tool_call": None, "result": None})


def test_step_call_tool_requires_tool_call():
    with pytest.raises(ValidationError, match="call_tool requires tool_call"):
        SpecialistStep.model_validate({"action": "call_tool", "tool_call": None, "result": None})


def test_step_finish_requires_result():
    with pytest.raises(ValidationError, match="finish requires result"):
        SpecialistStep.model_validate({"action": "finish", "tool_call": None, "result": None})


def test_step_valid_call_tool_parses():
    step = SpecialistStep.model_validate(
        specialist_tool_step("get_account_status", employee_id="EMP-034")
    )
    assert step.action == "call_tool"
    assert step.tool_call.tool_name == "get_account_status"
    assert step.tool_call.params_dict() == {"employee_id": "EMP-034"}


def test_step_valid_finish_parses():
    step = SpecialistStep.model_validate(specialist_finish())
    assert step.action == "finish"
    assert step.result.outcome == "resolved"


# --- HandoffRequest confidence bounds ----------------------------------------

@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_handoff_confidence_in_bounds(confidence):
    handoff = HandoffRequest.model_validate({**HANDOFF, "confidence": confidence})
    assert handoff.confidence == confidence


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_handoff_confidence_out_of_bounds(confidence):
    with pytest.raises(ValidationError):
        HandoffRequest.model_validate({**HANDOFF, "confidence": confidence})
