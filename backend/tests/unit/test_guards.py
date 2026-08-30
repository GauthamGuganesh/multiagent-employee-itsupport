"""Hard execution guards: cycle/handoff budgets, loop signatures, and the
security-requires-human invariant. Pure functions over SupportState — limits
are varied by monkeypatching the cached settings instance."""
from app.config import get_settings
from app.contracts.common import Finding
from app.contracts.specialist import SpecialistResult
from app.contracts.supervisor import SupervisorDecision
from app.graph.guards import (
    check_cycle_budget,
    check_handoff_budget,
    check_information_request,
    check_loop_signature,
    counts_as_handoff,
    decision_signature,
    endpoint_damage_requires_hardware_handoff,
    security_requires_human,
)
from app.contracts.common import ChatTurn
from app.graph.state import SupportState
from tests.conftest import supervisor_decision


def make_state(**overrides) -> SupportState:
    base = {
        "session_id": "sess-guards",
        "employee_id": "EMP-001",
        "original_request": "VPN keeps dropping since yesterday",
    }
    base.update(overrides)
    return SupportState(**base)


def make_result(agent: str, outcome: str, **overrides) -> SpecialistResult:
    payload = {
        "agent": agent,
        "outcome": outcome,
        "confidence": 0.8,
        "reasoning_summary": "test",
    }
    if outcome == "resolved":
        payload["resolution_summary"] = "fixed"
    if outcome == "escalation_required":
        payload["escalation_reason"] = "needs human review"
    payload.update(overrides)
    return SpecialistResult.model_validate(payload)


def make_decision(**overrides) -> SupervisorDecision:
    return SupervisorDecision.model_validate(supervisor_decision(**overrides))


# --- check_cycle_budget -------------------------------------------------------

def test_cycle_budget_within_limit_does_not_trip(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_supervisor_cycles", 3)
    # Called AFTER the increment: count+1 must exceed the limit to trip.
    verdict = check_cycle_budget(make_state(supervisor_cycle_count=2))
    assert verdict.tripped is False
    assert verdict.kind is None


def test_cycle_budget_trips_above_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_supervisor_cycles", 3)
    verdict = check_cycle_budget(make_state(supervisor_cycle_count=3))
    assert verdict.tripped is True
    assert verdict.kind == "cycle_budget"
    assert "3" in verdict.reason


# --- counts_as_handoff --------------------------------------------------------

def test_first_specialist_is_not_a_handoff():
    assert counts_as_handoff(make_state(previous_agents=[]), "network") is False


def test_routing_to_different_specialist_is_a_handoff():
    state = make_state(previous_agents=["network"])
    assert counts_as_handoff(state, "security") is True


def test_repeat_of_same_specialist_is_not_a_handoff():
    state = make_state(previous_agents=["identity", "network"])
    assert counts_as_handoff(state, "network") is False


# --- check_handoff_budget -----------------------------------------------------

def test_handoff_budget_trips_when_projection_exceeds_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_agent_handoffs", 2)
    state = make_state(handoff_count=2, previous_agents=["network"])
    verdict = check_handoff_budget(state, "security")  # projects 3 > 2
    assert verdict.tripped is True
    assert verdict.kind == "handoff_budget"


def test_handoff_budget_same_specialist_does_not_project(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_agent_handoffs", 2)
    state = make_state(handoff_count=2, previous_agents=["network"])
    # Re-routing to the same specialist adds nothing: projected 2 <= 2.
    assert check_handoff_budget(state, "network").tripped is False


def test_handoff_budget_first_specialist_at_limit_is_fine(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_agent_handoffs", 2)
    state = make_state(handoff_count=2, previous_agents=[])
    assert check_handoff_budget(state, "security").tripped is False


# --- decision_signature -------------------------------------------------------

def test_signature_is_stable_for_identical_state_and_decision():
    state = make_state(turn_index=1)
    decision = make_decision(target_specialist="network")
    assert decision_signature(state, decision) == decision_signature(state, decision)


def test_signature_changes_with_turn_index():
    decision = make_decision(target_specialist="network")
    sig_turn_1 = decision_signature(make_state(turn_index=1), decision)
    sig_turn_2 = decision_signature(make_state(turn_index=2), decision)
    assert sig_turn_1 != sig_turn_2


def test_signature_changes_with_findings_count():
    decision = make_decision(target_specialist="network")
    finding = Finding(agent="network", summary="VPN session from an unknown IP")
    sig_no_evidence = decision_signature(make_state(), decision)
    sig_with_evidence = decision_signature(make_state(specialist_findings=[finding]), decision)
    assert sig_no_evidence != sig_with_evidence


def test_signature_changes_with_target():
    state = make_state()
    sig_network = decision_signature(state, make_decision(target_specialist="network"))
    sig_security = decision_signature(state, make_decision(target_specialist="security"))
    assert sig_network != sig_security


# --- check_loop_signature -----------------------------------------------------

def test_loop_signature_below_repeat_limit_does_not_trip(monkeypatch):
    monkeypatch.setattr(get_settings(), "loop_signature_repeat_limit", 2)
    state = make_state(decision_signatures=["abc123"])
    assert check_loop_signature(state, "abc123").tripped is False


def test_loop_signature_trips_at_repeat_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "loop_signature_repeat_limit", 2)
    state = make_state(decision_signatures=["abc123", "other", "abc123"])
    verdict = check_loop_signature(state, "abc123")
    assert verdict.tripped is True
    assert verdict.kind == "loop_signature"


def test_loop_signature_ignores_other_signatures(monkeypatch):
    monkeypatch.setattr(get_settings(), "loop_signature_repeat_limit", 2)
    state = make_state(decision_signatures=["other", "other"])
    assert check_loop_signature(state, "abc123").tripped is False


# --- employee-information guard ---------------------------------------------

def test_rephrased_employee_question_trips_before_it_is_asked_again():
    state = make_state(recent_turns=[
        ChatTurn(
            role="assistant",
            content="Can you describe the specific display issue affecting your laptop?",
        )
    ])
    verdict = check_information_request(
        state,
        "Could you describe the specific issue affecting your laptop display?",
    )
    assert verdict.tripped is True
    assert verdict.kind == "repeated_information_request"


def test_information_request_budget_is_session_lifetime(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_information_requests", 2)
    verdict = check_information_request(
        make_state(information_request_count=2), "What error message do you see?"
    )
    assert verdict.tripped is True
    assert verdict.kind == "information_request_budget"


def test_physical_display_damage_after_endpoint_question_requires_handoff():
    state = make_state(
        original_request="I need a replacement laptop.",
        recent_turns=[
            ChatTurn(role="employee", content="The screen is broken, shows lines, and I cannot work."),
        ],
        specialist_results=[make_result(
            "endpoint", "need_more_information", question_for_employee="Can you describe the problem?"
        )],
    )
    assert endpoint_damage_requires_hardware_handoff(state) is True


# --- security_requires_human --------------------------------------------------

def test_security_escalation_requires_human():
    state = make_state(
        specialist_results=[make_result("security", "escalation_required")]
    )
    assert security_requires_human(state) is True


def test_non_security_escalation_does_not_lock_the_session():
    state = make_state(
        specialist_results=[make_result("network", "escalation_required")]
    )
    assert security_requires_human(state) is False


def test_security_resolved_does_not_require_human():
    state = make_state(specialist_results=[make_result("security", "resolved")])
    assert security_requires_human(state) is False


def test_no_results_does_not_require_human():
    assert security_requires_human(make_state()) is False
