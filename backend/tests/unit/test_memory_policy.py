"""Memory write policy (DESIGN §8): only meaningful endings produce a durable
memory — genuine resolutions and security escalations. Acknowledgements and
unresolved sessions write nothing."""
import pytest

from app.contracts.specialist import SpecialistResult
from app.graph.state import SupportState
from app.memory.policy import build_session_memory, is_memorable


def make_state(**overrides) -> SupportState:
    base = {
        "session_id": "sess-memory",
        "employee_id": "EMP-041",
        "original_request": "My laptop is crawling since this morning",
    }
    base.update(overrides)
    return SupportState(**base)


def resolved_result(agent: str = "endpoint", resolution: str = "clearing disk space") -> SpecialistResult:
    return SpecialistResult(
        agent=agent,
        outcome="resolution_recommended",
        confidence=0.9,
        reasoning_summary="test",
        resolution_summary=resolution,
    )


# --- is_memorable -------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "ok",
        "thanks",
        "Thanks a lot!",
        "ok thanks!",
        "yes please",
        "Sounds good",
        "no thanks",
        "got it",
        "hi",  # shorter than 4 chars
        "   ",
    ],
)
def test_is_memorable_skips_acknowledgements(text):
    assert is_memorable(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "My VPN keeps dropping since yesterday",
        "I'm locked out of my account",
        "install docker desktop",
    ],
)
def test_is_memorable_keeps_real_requests(text):
    assert is_memorable(text) is True


# --- build_session_memory -----------------------------------------------------

def test_resolved_session_with_resolution_produces_memory():
    state = make_state(
        category="endpoint",
        terminal_status="resolved",
        specialist_results=[resolved_result()],
    )
    memory = build_session_memory(state)
    assert memory == (
        "On a past endpoint issue (My laptop is crawling since this morning) "
        "the fix was: clearing disk space"
    )


def test_resolved_memory_uses_latest_resolution_summary():
    state = make_state(
        category="endpoint",
        terminal_status="resolved",
        specialist_results=[
            resolved_result(resolution="first attempt"),
            resolved_result(resolution="freeing 40GB of disk"),
        ],
    )
    memory = build_session_memory(state)
    assert "freeing 40GB of disk" in memory
    assert "first attempt" not in memory


def test_trivial_request_writes_nothing_even_when_resolved():
    state = make_state(
        original_request="thanks",
        terminal_status="resolved",
        specialist_results=[resolved_result()],
    )
    assert build_session_memory(state) is None


def test_unresolved_session_writes_nothing():
    state = make_state(terminal_status=None, specialist_results=[resolved_result()])
    assert build_session_memory(state) is None


def test_failed_session_writes_nothing():
    state = make_state(terminal_status="failed", specialist_results=[resolved_result()])
    assert build_session_memory(state) is None


def test_resolved_without_resolution_summary_writes_nothing():
    state = make_state(terminal_status="resolved", specialist_results=[])
    assert build_session_memory(state) is None


def test_security_escalation_writes_nothing():
    """A past escalation (even security) is not a durable fact about the employee
    and must never be remembered — retrieving it later would wrongly bias a
    fresh, unrelated request toward security."""
    state = make_state(
        original_request="VPN keeps dropping and I got a strange MFA prompt",
        category="security",
        terminal_status="escalated",
        escalation_reason="impossible travel from unrecognized network",
    )
    assert build_session_memory(state) is None


def test_non_security_escalation_writes_nothing():
    state = make_state(
        category="network",
        terminal_status="escalated",
        escalation_reason="budget exhausted",
    )
    assert build_session_memory(state) is None
