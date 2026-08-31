"""Regression coverage for the offline demo's useful, domain-safe behaviour."""
import pytest

from app.contracts.specialist import SpecialistStep
from app.contracts.supervisor import SupervisorDecision
from tests.scripted_provider import ScriptedProvider


@pytest.mark.asyncio
async def test_security_is_triaged_before_endpoint_for_a_mixed_phishing_report():
    provider = ScriptedProvider()

    outcome = await provider.structured(
        SupervisorDecision,
        [
            ("system", "supervisor"),
            (
                "user",
                "Employee: EMP-034\nOriginal request: I received a suspicious email and my laptop is overheating.",
            ),
        ],
    )

    assert outcome.parsed is not None
    assert outcome.parsed.target_specialist == "security"


@pytest.mark.asyncio
async def test_security_phishing_report_gives_safe_specific_follow_up_once():
    provider = ScriptedProvider()

    outcome = await provider.structured(
        SpecialistStep,
        [
            ("system", 'agent must be "security"'),
            (
                "user",
                "Employee: EMP-034\nOriginal request: I got a suspicious email this morning.",
            ),
        ],
    )

    assert outcome.parsed is not None
    result = outcome.parsed.result
    assert result is not None
    assert result.outcome == "need_more_information"
    assert "don't open" in (result.question_for_employee or "").lower()


@pytest.mark.asyncio
async def test_physical_damage_is_not_misdiagnosed_as_account_or_health_issue():
    provider = ScriptedProvider()

    outcome = await provider.structured(
        SpecialistStep,
        [
            ("system", 'agent must be "endpoint"'),
            (
                "user",
                "Employee: EMP-034\nOriginal request: My screen was damaged in an accident and I cannot work. I need a replacement.",
            ),
        ],
    )

    assert outcome.parsed is not None
    result = outcome.parsed.result
    assert result is not None
    assert result.outcome == "escalation_required"
    assert "hardware assessment" in (result.escalation_reason or "").lower()
