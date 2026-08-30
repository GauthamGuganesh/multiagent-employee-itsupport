"""Supervisor node: one incremental routing decision per invocation.

All guard verdicts are applied here via Command updates (edges select, nodes
mutate). Code-level validation can override an LLM decision — every override
is recorded in the audit trail.
"""
from langgraph.types import Command

from app.config import get_settings
from app.contracts.common import Transition
from app.contracts.supervisor import SupervisorDecision
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph import guards
from app.graph.specialists.prompts import SUPERVISOR_SYSTEM, build_supervisor_context
from app.graph.state import SupportState
from app.graph.structured import invoke_structured
from app.llm.provider import get_provider

# Workflow name → graph node
WORKFLOW_NODES = {
    "resolution": "resolution",
    "confirmation": "confirmation_prepare",
    "approval": "approval",
    "escalation": "escalation",
    "need_info": "ask_prepare",
    "ticket_status": "ticket_status",
}

SPECIALIST_CATEGORY = {
    "identity": "identity",
    "endpoint": "endpoint",
    "network": "network",
    "security": "security",
}


def _escalate(state: SupportState, *, reason: str, trigger: str, cycle: int, extra: dict | None = None) -> Command:
    update = {
        "supervisor_cycle_count": cycle,
        "escalation_required": True,
        "escalation_reason": reason,
        "escalation_trigger": trigger,
        "transition_history": [
            Transition(from_node="supervisor", to_node="escalation", reason=reason)
        ],
        **(extra or {}),
    }
    return Command(goto="escalation", update=update)


async def supervisor_node(state: SupportState) -> Command:
    settings = get_settings()
    cycle = state.supervisor_cycle_count + 1

    verdict = guards.check_cycle_budget(state)
    if verdict.tripped:
        await record(
            EventType.LOOP_GUARD_TRIGGERED,
            session_id=state.session_id,
            actor="supervisor",
            payload={"kind": verdict.kind, "reason": verdict.reason, "cycle": cycle},
        )
        return _escalate(
            state, reason=verdict.reason or "budget exhausted",
            trigger="budget_exhausted", cycle=cycle, extra={"loop_guard_triggered": True},
        )

    # Endpoint Support has already had a chance to assess the case. Once an
    # employee has clearly reported physical display damage that prevents work,
    # additional wording variants cannot decide repair versus replacement.
    # Stop the re-interview and hand the case to the hardware owner.
    if guards.endpoint_damage_requires_hardware_handoff(state):
        reason = (
            "The employee has reported physical display damage that prevents normal work; "
            "a human hardware assessment is required for repair or replacement."
        )
        await record(
            EventType.HUMAN_INTERVENTION,
            session_id=state.session_id,
            actor="supervisor",
            payload={"reason": reason, "trigger": "physical_device_damage"},
        )
        return _escalate(
            state,
            reason=reason,
            trigger="agent_recommendation",
            cycle=cycle,
        )

    run = await repos.create_agent_run(state.session_id, "supervisor", run_index=cycle)
    provider = get_provider()
    outcome = await invoke_structured(
        provider,
        SupervisorDecision,
        [("system", SUPERVISOR_SYSTEM), ("user", build_supervisor_context(state))],
        agent_name="supervisor",
        session_id=state.session_id,
    )

    if outcome.failure is not None:
        await repos.complete_agent_run(
            run.id,
            status="failed",
            failure_type=outcome.failure.failure_type,
            failure_detail=outcome.failure.detail,
            recoverable=False,
            structured_output_retries=outcome.retries,
        )
        return _escalate(
            state,
            reason="the automated triage system could not produce a valid decision",
            trigger="structured_output_failure",
            cycle=cycle,
            extra={
                "agent_failures": [outcome.failure],
                "structured_output_failure_count": state.structured_output_failure_count + 1,
            },
        )

    decision: SupervisorDecision = outcome.parsed  # type: ignore[assignment]
    # Keep structured model output deliberately small. These values are
    # deterministically inferred from the selected route and accumulated state,
    # not entrusted to the model as extra required fields.
    inferred_category = (
        state.category
        or SPECIALIST_CATEGORY.get(decision.target_specialist or "")
        or ("ticketing" if decision.workflow == "ticket_status" else "other")
    )
    normalized = {
        "category": inferred_category if decision.category == "other" else decision.category,
        "intent": decision.intent or state.intent or state.original_request[:200],
        "reason": decision.reason or "Selected the next safe step from the available evidence.",
    }
    if decision.target_specialist == "security" or normalized["category"] == "security":
        normalized.update({"risk_level": "high", "autonomy_level": "human_only"})
    elif decision.workflow == "escalation":
        normalized["autonomy_level"] = "human_only"
    decision = decision.model_copy(update=normalized)
    overrides: list[str] = []

    # Information requests are bounded across the *whole session*, not merely
    # a single LangGraph invocation. This makes a rephrased version of an
    # already answered question a safe escalation instead of an endless chat.
    if decision.decision == "ask_employee":
        question_verdict = guards.check_information_request(
            state, decision.question_for_employee or ""
        )
        if question_verdict.tripped:
            await record(
                EventType.LOOP_GUARD_TRIGGERED,
                session_id=state.session_id,
                actor="supervisor",
                payload={
                    "kind": question_verdict.kind,
                    "reason": question_verdict.reason,
                    "question": decision.question_for_employee,
                },
            )
            await repos.complete_agent_run(
                run.id,
                status="completed",
                outcome="information_guard",
                loop_guard_triggered=True,
                result=decision.model_dump(mode="json"),
                structured_output_retries=outcome.retries,
            )
            return _escalate(
                state,
                reason=question_verdict.reason or "follow-up questions are no longer advancing the case",
                trigger="loop_guard",
                cycle=cycle,
                extra={"loop_guard_triggered": True},
            )

    # A specialist that has exhausted its schema retries cannot safely make
    # progress on another invocation. Preserve the evidence and hand the case
    # to a human instead of repeatedly routing to the same failed specialist.
    latest_failure = state.agent_failures[-1] if state.agent_failures else None
    if latest_failure is not None and latest_failure.failure_type == "structured_output":
        overrides.append(
            f"{latest_failure.agent} exhausted structured-output retries; escalated instead of rerouting"
        )
        decision = decision.model_copy(
            update={
                "decision": "run_workflow",
                "target_specialist": None,
                "workflow": "escalation",
                "risk_level": "medium",
                "autonomy_level": "human_only",
                "reason": "The specialist could not produce a valid result after its safe retry limit.",
            }
        )

    # Invariant: a security-flagged case can never be autonomously resolved.
    if guards.security_requires_human(state) and not (
        decision.decision == "run_workflow" and decision.workflow == "escalation"
    ):
        overrides.append(
            f"security specialist requires human intervention; overrode {decision.decision}"
        )
        decision = decision.model_copy(
            update={
                "decision": "run_workflow",
                "workflow": "escalation",
                "risk_level": "high" if decision.risk_level in ("low", "medium") else decision.risk_level,
                "autonomy_level": "human_only",
            }
        )

    # A pending unconfirmed requested_action must go through confirmation.
    if (
        state.requested_action is not None
        and state.employee_confirmation is None
        and decision.decision == "run_workflow"
        and decision.workflow == "resolution"
    ):
        overrides.append("requested_action pending; resolution overrode to confirmation")
        decision = decision.model_copy(update={"workflow": "confirmation"})

    # Loop-signature guard.
    signature = guards.decision_signature(state, decision)
    loop_verdict = guards.check_loop_signature(state, signature)
    if loop_verdict.tripped:
        await record(
            EventType.LOOP_GUARD_TRIGGERED,
            session_id=state.session_id,
            actor="supervisor",
            payload={"kind": loop_verdict.kind, "reason": loop_verdict.reason, "signature": signature},
        )
        await repos.complete_agent_run(
            run.id, status="completed", outcome="loop_guard",
            loop_guard_triggered=True, result=decision.model_dump(mode="json"),
            structured_output_retries=outcome.retries,
        )
        return _escalate(
            state, reason=loop_verdict.reason or "routing loop detected",
            trigger="loop_guard", cycle=cycle,
            extra={"loop_guard_triggered": True, "decision_signatures": [signature]},
        )

    # Handoff budget when routing to a specialist.
    handoff_increment = 0
    if decision.decision == "route_to_specialist":
        target = decision.target_specialist or ""
        handoff_verdict = guards.check_handoff_budget(state, target)
        if handoff_verdict.tripped:
            await record(
                EventType.LOOP_GUARD_TRIGGERED,
                session_id=state.session_id,
                actor="supervisor",
                payload={"kind": handoff_verdict.kind, "reason": handoff_verdict.reason},
            )
            await repos.complete_agent_run(
                run.id, status="completed", outcome="handoff_budget",
                loop_guard_triggered=True, result=decision.model_dump(mode="json"),
                structured_output_retries=outcome.retries,
            )
            return _escalate(
                state, reason=handoff_verdict.reason or "handoff budget exhausted",
                trigger="budget_exhausted", cycle=cycle,
                extra={"loop_guard_triggered": True, "decision_signatures": [signature]},
            )
        handoff_increment = 1 if guards.counts_as_handoff(state, target) else 0

    await repos.complete_agent_run(
        run.id,
        status="completed",
        outcome=decision.decision,
        confidence=decision.confidence,
        reasoning_summary=decision.reason,
        result=decision.model_dump(mode="json"),
        structured_output_retries=outcome.retries,
        handoff_target=decision.target_specialist,
    )
    await record(
        EventType.SUPERVISOR_DECISION,
        session_id=state.session_id,
        actor="supervisor",
        payload={
            "cycle": cycle,
            "decision": decision.model_dump(mode="json"),
            "overrides": overrides,
        },
    )
    await repos.update_support_session(
        state.session_id,
        category=decision.category,
        intent=decision.intent,
        risk_level=decision.risk_level,
        autonomy_level=decision.autonomy_level,
    )

    common_update = {
        "supervisor_cycle_count": cycle,
        "decision_signatures": [signature],
        "category": decision.category,
        "intent": decision.intent,
        "risk_level": decision.risk_level,
        "autonomy_level": decision.autonomy_level,
    }

    if decision.decision == "route_to_specialist":
        target = decision.target_specialist or "identity"
        if state.specialist_results and state.specialist_results[-1].outcome == "handoff_recommended":
            await record(
                EventType.HANDOFF_COMPLETED,
                session_id=state.session_id,
                actor="supervisor",
                payload={"from": state.previous_agents[-1] if state.previous_agents else None,
                         "to": target, "reason": decision.reason},
            )
        return Command(
            goto=target,
            update={
                **common_update,
                "current_agent": target,
                "handoff_count": state.handoff_count + handoff_increment,
                "transition_history": [
                    Transition(from_node="supervisor", to_node=target, reason=decision.reason)
                ],
            },
        )

    if decision.decision == "ask_employee":
        return Command(
            goto="ask_prepare",
            update={
                **common_update,
                "pending_question": decision.question_for_employee,
                "transition_history": [
                    Transition(from_node="supervisor", to_node="ask_prepare", reason=decision.reason)
                ],
            },
        )

    if decision.decision == "run_workflow":
        node = WORKFLOW_NODES.get(decision.workflow or "", "escalation")
        update = {
            **common_update,
            "transition_history": [
                Transition(from_node="supervisor", to_node=node, reason=decision.reason)
            ],
        }
        if decision.workflow == "escalation":
            update["escalation_required"] = True
            update["escalation_reason"] = state.escalation_reason or decision.reason
            update["escalation_trigger"] = state.escalation_trigger or (
                "security" if guards.security_requires_human(state) else "agent_recommendation"
            )
        if decision.workflow == "need_info":
            update["pending_question"] = (
                decision.question_for_employee
                or "Could you share more detail about the issue so I can route it correctly?"
            )
        return Command(goto=node, update=update)

    # close_session
    return Command(
        goto="close_direct",
        update={
            **common_update,
            "final_response": decision.message_to_employee,
            "transition_history": [
                Transition(from_node="supervisor", to_node="close_direct", reason=decision.reason)
            ],
        },
    )
