"""Confirmation workflow: Neo4j privilege check → exact action summary →
explicit yes/no → execute on yes.

Voice or text confirmation confirms INTENT only — identity comes from the
authenticated session. The privilege verified is the one named on the
RequestedAction, against Neo4j, failing closed when the directory is
unavailable.
"""
from langgraph.types import Command, interrupt

from app.contracts.common import ChatTurn, Transition
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.state import SupportState
from app.org import service as org
from app.tools.registry import ToolContext, execute_tool

AFFIRMATIVE = {"yes", "y", "confirm", "confirmed", "approve", "go ahead", "do it", "true", "ok", "okay"}


def _is_affirmative(answer: object) -> bool:
    if isinstance(answer, bool):
        return answer
    if isinstance(answer, dict):
        return bool(answer.get("confirmed"))
    return str(answer).strip().lower() in AFFIRMATIVE


async def confirmation_prepare(state: SupportState) -> Command:
    action = state.requested_action
    if action is None:
        return Command(
            goto="supervisor",
            update={
                "transition_history": [
                    Transition(
                        from_node="confirmation_prepare", to_node="supervisor",
                        reason="no requested_action present",
                    )
                ]
            },
        )

    check = await org.has_privilege(state.employee_id, action.privilege_key)
    base = {"privilege_check_result": check}

    if check.error:
        return Command(
            goto="escalation",
            update={
                **base,
                "escalation_required": True,
                "escalation_reason": (
                    "the required privilege could not be verified because the "
                    "organization directory is unavailable (fail-closed)"
                ),
                "escalation_trigger": "infrastructure",
                "transition_history": [
                    Transition(
                        from_node="confirmation_prepare", to_node="escalation",
                        reason="privilege check failed closed",
                    )
                ],
            },
        )

    if check.has_privilege:
        conf = await repos.create_confirmation(
            session_id=state.session_id,
            employee_id=state.employee_id,
            action_key=action.action_key,
            action_summary=action.summary,
            params=action.params_dict(),
        )
        prompt = (
            f"I can do that for you. To confirm: {action.summary} "
            "Shall I go ahead? (yes / no)"
        )
        await repos.add_message(state.session_id, "assistant", prompt, source=state.channel)
        await record(
            EventType.USER_CONFIRMATION_REQUESTED,
            session_id=state.session_id,
            actor="confirmation_workflow",
            payload={
                "confirmation_id": conf.id,
                "action_key": action.action_key,
                "action_summary": action.summary,
                "risk_level": action.risk_level,
            },
        )
        await repos.update_support_session(state.session_id, status="waiting_employee")
        return Command(
            goto="confirmation_wait",
            update={
                **base,
                "confirmation_id": conf.id,
                "recent_turns": state.recent_turns + [ChatTurn(role="assistant", content=prompt)],
                "transition_history": [
                    Transition(
                        from_node="confirmation_prepare", to_node="confirmation_wait",
                        reason="employee has privilege; awaiting explicit confirmation",
                    )
                ],
            },
        )

    if check.eligible_with_approval:
        return Command(
            goto="approval",
            update={
                **base,
                "transition_history": [
                    Transition(
                        from_node="confirmation_prepare", to_node="approval",
                        reason=f"employee lacks {action.privilege_key} but is eligible with approval",
                    )
                ],
            },
        )

    return Command(
        goto="escalation",
        update={
            **base,
            "escalation_required": True,
            "escalation_reason": (
                f"the employee is neither entitled nor eligible for "
                f"'{action.privilege_key}'; a human should review this request"
            ),
            "escalation_trigger": "out_of_scope",
            "transition_history": [
                Transition(
                    from_node="confirmation_prepare", to_node="escalation",
                    reason="not entitled and not eligible",
                )
            ],
        },
    )


async def confirmation_wait(state: SupportState) -> Command:
    action = state.requested_action
    answer = interrupt(
        {
            "type": "confirmation",
            "confirmation_id": state.confirmation_id,
            "action_summary": action.summary if action else "",
            "risk_level": action.risk_level if action else "medium",
        }
    )
    confirmed = _is_affirmative(answer)
    if state.confirmation_id:
        await repos.respond_confirmation(state.confirmation_id, confirmed)
    await record(
        EventType.USER_CONFIRMED if confirmed else EventType.USER_DECLINED,
        session_id=state.session_id,
        actor=state.employee_id,
        payload={"confirmation_id": state.confirmation_id, "confirmed": confirmed},
    )
    await repos.update_support_session(state.session_id, status="active")
    base = {
        "employee_confirmation": confirmed,
        "turn_index": state.turn_index + 1,
        "supervisor_cycle_count": 0,
        "handoff_count": 0,
    }
    if confirmed:
        return Command(
            goto="execute_action",
            update={
                **base,
                "transition_history": [
                    Transition(
                        from_node="confirmation_wait", to_node="execute_action",
                        reason="employee confirmed",
                    )
                ],
            },
        )
    return Command(
        goto="supervisor",
        update={
            **base,
            "transition_history": [
                Transition(
                    from_node="confirmation_wait", to_node="supervisor",
                    reason="employee declined the action",
                )
            ],
        },
    )


async def execute_action(state: SupportState) -> Command:
    """Deterministic privileged execution — the ONLY specialist-recommended
    path allowed to set authorized_privileged=True (besides approval decisions)."""
    action = state.requested_action
    assert action is not None and state.employee_confirmation is True

    params = action.params_dict()
    params["employee_id"] = state.employee_id
    result = await execute_tool(
        action.action_key,
        params,
        ToolContext(
            session_id=state.session_id,
            employee_id=state.employee_id,
            agent_name="confirmation_workflow",
            authorized_privileged=True,
        ),
    )
    await repos.create_action_execution(
        session_id=state.session_id,
        confirmation_id=state.confirmation_id,
        action_key=action.action_key,
        params=params,
        result={"summary": result.response_summary, "error": result.error},
        status=result.status,
    )
    await record(
        EventType.ACTION_EXECUTED,
        session_id=state.session_id,
        actor="confirmation_workflow",
        payload={
            "action_key": action.action_key,
            "status": result.status,
            "summary": result.response_summary,
            "confirmation_id": state.confirmation_id,
        },
    )

    if result.status == "succeeded":
        return Command(
            goto="resolution",
            update={
                "tool_results": [result],
                "final_response": f"Done — {result.response_summary}",
                "transition_history": [
                    Transition(
                        from_node="execute_action", to_node="resolution",
                        reason="confirmed action executed successfully",
                    )
                ],
            },
        )
    return Command(
        goto="escalation",
        update={
            "tool_results": [result],
            "escalation_required": True,
            "escalation_reason": f"the confirmed action '{action.action_key}' failed: {result.error}",
            "escalation_trigger": "infrastructure",
            "transition_history": [
                Transition(
                    from_node="execute_action", to_node="escalation",
                    reason="confirmed action failed",
                )
            ],
        },
    )
