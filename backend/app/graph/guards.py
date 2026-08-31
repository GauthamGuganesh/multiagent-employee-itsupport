"""Hard execution guards — budgets and loop detection, enforced in code.

Edges select, nodes mutate: these helpers are pure functions over state; the
supervisor node applies their verdicts via Command updates.
"""
import hashlib
import re
from dataclasses import dataclass

from app.config import get_settings
from app.contracts.supervisor import SupervisorDecision
from app.graph.state import SupportState


@dataclass
class GuardVerdict:
    tripped: bool
    kind: str | None = None  # cycle_budget | handoff_budget | loop_signature
    reason: str | None = None


def _question_terms(value: str) -> set[str]:
    """Return the meaningful words used to spot a rephrased repeat question."""
    stop_words = {
        "a", "an", "and", "are", "can", "could", "do", "does", "for", "have", "i", "if",
        "is", "it", "me", "of", "or", "please", "the", "to", "what", "would", "you", "your",
    }
    return {
        word for word in re.findall(r"[a-z0-9]+", value.lower())
        if len(word) > 2 and word not in stop_words
    }


def _is_rephrased_question(candidate: str, previous: str) -> bool:
    candidate_terms = _question_terms(candidate)
    previous_terms = _question_terms(previous)
    if not candidate_terms or not previous_terms:
        return candidate.strip().lower() == previous.strip().lower()
    overlap = len(candidate_terms & previous_terms) / len(candidate_terms | previous_terms)
    return overlap >= 0.65


def check_information_request(state: SupportState, question: str) -> GuardVerdict:
    """Prevent cross-turn re-interviews while allowing useful clarification.

    The count is intentionally not reset by `ingest_node` or `ask_wait`: new
    wording from the model is not new evidence from the employee.
    """
    limit = get_settings().max_information_requests
    if state.information_request_count >= limit:
        return GuardVerdict(
            tripped=True,
            kind="information_request_budget",
            reason=(
                f"automated follow-up question limit reached ({limit} questions without a decisive next step)"
            ),
        )

    prior_questions = [turn.content for turn in state.recent_turns if turn.role == "assistant"]
    if any(_is_rephrased_question(question, prior) for prior in prior_questions):
        return GuardVerdict(
            tripped=True,
            kind="repeated_information_request",
            reason="the same follow-up question was being repeated without new progress",
        )
    return GuardVerdict(tripped=False)


def _employee_text(state: SupportState) -> str:
    return " ".join(
        [state.original_request]
        + [turn.content for turn in state.recent_turns if turn.role == "employee"]
    ).lower()


def is_simple_informational_request(state: SupportState) -> bool:
    """Allow a direct, useful answer (close_session) instead of forcing a
    diagnostic question or a specialist investigation. Covers three families
    that are genuinely served best by simply *answering well* — the value is
    being a helpful advisor, not opening a case:

    - capability questions with no active incident ("what can you do"),
    - guidance / how-to / advice questions ("how do I set up a second monitor",
      "what's the best way to keep my laptop fast", "is it safe to use public
      Wi-Fi") — the employee wants to be pointed the right way, and
    - logistics / follow-up questions about a case already in play (who to
      contact, who is handling it, how long it will take).

    None of these needs an investigation, so the close_session override must
    not hijack them into a cold diagnostic question. Anything that reads as an
    *active, unresolved fault* (something broken or failing right now) is
    deliberately excluded so real problems are still investigated — that is the
    incident gate below.
    """
    text = _employee_text(state)
    capability_markers = (
        "what can you", "what do you", "how can you help", "what kinds of",
        "where can i find", "how do i contact", "who supports",
    )
    # Guidance / how-to / advice phrasings: the employee wants direction, not a
    # ticket. Gated on the absence of an active fault below, so "how do I fix my
    # broken screen" still routes to investigation.
    guidance_markers = (
        "how do i", "how can i", "how to", "how would i", "how should i",
        "best way to", "what's the best", "what is the best", "best practice",
        "should i", "is it safe", "is it ok", "is it okay", "is there a way",
        "what are the", "what happens if", "can you explain", "could you explain",
        "explain how", "any tips", "tips for", "tips on", "advice on",
        "recommend", "difference between",
    )
    # Logistics / follow-up phrasings — answerable directly even mid-incident.
    logistics_markers = (
        "who do i", "who should i", "who can i", "who is handling", "who's handling",
        "who will", "how long", "how much longer", "what happens next", "any update",
        "what's the update", "when will", "status of", "who to contact",
    )
    # An active fault, however phrased — the gate that keeps real incidents on
    # the investigation path even when they arrive worded as a how-to.
    incident_terms = (
        "not working", "doesn't work", "does not work", "won't", "wont",
        "can't", "cannot", "unable", "error", "broken", "locked", "disconnect",
        "dropping", "drops", "slow", "crash", "freez", "frozen", "stuck",
        "failing", "suspicious", "phishing", "hacked", "compromis",
        "install", "access", "cracked", "shattered", "damaged", "damage",
        "spilled", "liquid",
    )
    if any(marker in text for marker in logistics_markers):
        return True
    if any(term in text for term in incident_terms):
        return False
    return any(marker in text for marker in capability_markers + guidance_markers)


def resolution_answer_is_clearly_negative(state: SupportState) -> bool:
    """Hard safety veto for a wrap-up reply that clearly says the problem
    persists; nuanced interpretation remains the supervisor's job.

    The wrap-up asks two things at once ("did that fix it, and anything else?"),
    so a bare "no" is ambiguous — it usually means "no, nothing else" (close),
    not "no, still broken". This veto therefore only trips on words/phrases that
    unambiguously indicate the original problem is still happening; "no" alone
    is left to the supervisor to interpret in context.
    """
    answer = (state.resolution_confirmation_answer or "").lower()
    if any(
        success in answer
        for success in ("has not dropped again", "hasn't dropped again", "did not fail again")
    ):
        return False
    words = set(re.findall(r"[a-z']+", answer))
    phrases = (
        "not fixed", "not resolved", "not working", "doesn't work", "does not work",
        "isn't working", "is not working", "same issue", "still happening", "still not",
        "disconnected again", "dropped again", "didn't help", "did not help", "didn't work",
    )
    return bool(words & {"still", "broken", "failing"}) or any(
        phrase in answer for phrase in phrases
    )


def endpoint_damage_requires_hardware_handoff(state: SupportState) -> bool:
    """Recognize enough employee-reported evidence to stop a hardware re-interview.

    This is deliberately narrow: it applies only after Endpoint Support already
    requested more information, and only for physical display damage that
    prevents normal work. A human must assess repair versus replacement.
    """
    if not state.specialist_results:
        return False
    latest = state.specialist_results[-1]
    if latest.agent != "endpoint" or latest.outcome != "need_more_information":
        return False

    employee_text = " ".join(
        [state.original_request]
        + [turn.content for turn in state.recent_turns if turn.role == "employee"]
    ).lower()
    display_issue = any(term in employee_text for term in ("screen", "display", "monitor", "lines"))
    physical_damage = any(
        term in employee_text
        for term in ("broken", "damaged", "damage", "cracked", "shattered", "accident", "no display")
    )
    work_impact = any(
        term in employee_text
        for term in ("cannot work", "can't work", "unable to work", "not able to work", "disrupting my work")
    )
    return display_issue and physical_damage and work_impact


_SPECIALISTS = ("identity", "endpoint", "network", "security")


def pending_handoff_target(state: SupportState) -> str | None:
    """The specialist a fresh handoff points at, or None.

    A specialist's ``handoff_recommended`` outcome is a first-class routing
    instruction, not a suggestion the supervisor may reinterpret as an
    escalation. This returns the valid target so the supervisor can honor it in
    code. It is deliberately conservative:

    - the most recent specialist result must be an unconsumed handoff,
    - the target must be a real specialist and not the agent that just ran
      (a self-handoff is meaningless), and
    - the target must not already have investigated *after* the handoff was
      raised (prevents A→B→A ping-pong; the loop/handoff budgets remain the
      final backstop).
    """
    if not state.specialist_results:
        return None
    latest = state.specialist_results[-1]
    if latest.outcome != "handoff_recommended" or latest.handoff is None:
        return None
    target = latest.handoff.target_agent
    if target not in _SPECIALISTS or target == latest.agent:
        return None
    # Don't force a re-consult of a specialist already run this turn; a genuine
    # re-route on new evidence is still available to the model, and the loop /
    # handoff budgets remain the backstop against A→B→A ping-pong.
    if target in state.previous_agents:
        return None
    return target


def check_cycle_budget(state: SupportState) -> GuardVerdict:
    """Called at supervisor entry AFTER incrementing the cycle counter."""
    limit = get_settings().max_supervisor_cycles
    if state.supervisor_cycle_count + 1 > limit:
        return GuardVerdict(
            tripped=True,
            kind="cycle_budget",
            reason=f"supervisor cycle budget exhausted ({limit} cycles this turn)",
        )
    return GuardVerdict(tripped=False)


def counts_as_handoff(state: SupportState, target: str) -> bool:
    """Routing to a specialist counts as a handoff when another specialist has
    already investigated this turn and the target differs from the last one."""
    if not state.previous_agents:
        return False
    return state.previous_agents[-1] != target


def check_handoff_budget(state: SupportState, target: str) -> GuardVerdict:
    limit = get_settings().max_agent_handoffs
    projected = state.handoff_count + (1 if counts_as_handoff(state, target) else 0)
    if projected > limit:
        return GuardVerdict(
            tripped=True,
            kind="handoff_budget",
            reason=f"agent handoff budget exhausted ({limit} handoffs this turn)",
        )
    return GuardVerdict(tripped=False)


def decision_signature(state: SupportState, decision: SupervisorDecision) -> str:
    """Signature of an unresolved routing decision. Includes turn_index so
    pre-reply decisions never collide with post-reply ones, and the volume of
    evidence so a re-route WITH new findings is not a repeat."""
    last_outcome = state.specialist_results[-1].outcome if state.specialist_results else "none"
    material = "|".join(
        [
            str(state.turn_index),
            decision.decision,
            decision.target_specialist or decision.workflow or "none",
            last_outcome,
            str(len(state.specialist_findings)),
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def check_loop_signature(state: SupportState, signature: str) -> GuardVerdict:
    limit = get_settings().loop_signature_repeat_limit
    if state.decision_signatures.count(signature) >= limit:
        return GuardVerdict(
            tripped=True,
            kind="loop_signature",
            reason="the same unresolved routing decision repeated without new evidence",
        )
    return GuardVerdict(tripped=False)


def security_requires_human(state: SupportState) -> bool:
    """Invariant: once the security specialist recommends human intervention,
    no autonomous path may resolve the session."""
    return any(
        r.agent == "security" and r.outcome == "escalation_required"
        for r in state.specialist_results
    )
