"""Hard execution guards — budgets and loop detection, enforced in code.

Edges select, nodes mutate: these helpers are pure functions over state; the
supervisor node applies their verdicts via Command updates.
"""
import hashlib
from dataclasses import dataclass

from app.config import get_settings
from app.contracts.supervisor import SupervisorDecision
from app.graph.state import SupportState


@dataclass
class GuardVerdict:
    tripped: bool
    kind: str | None = None  # cycle_budget | handoff_budget | loop_signature
    reason: str | None = None


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
