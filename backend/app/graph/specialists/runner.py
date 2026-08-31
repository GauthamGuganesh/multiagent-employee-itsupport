"""Generic specialist executor: a bounded Reason → Act → Observe → Decide loop.

One runner serves all four specialists; only the SpecialistSpec differs. The
step budget is a plain-Python loop bound. Params are pinned to the
authenticated employee — a specialist can never operate on someone else's
account.
"""
from app.config import get_settings
from app.contracts.common import AgentFailure, ToolResult, Transition
from app.contracts.specialist import SpecialistResult, SpecialistStep
from app.db import repos
from app.events.recorder import record
from app.events.types import EventType
from app.graph.specialists.prompts import build_specialist_context, build_specialist_system
from app.graph.specialists.specs import SpecialistSpec
from app.graph.state import SupportState
from app.graph.structured import invoke_structured
from app.llm.provider import get_provider
from app.tools.registry import ToolContext, execute_tool


async def run_specialist(spec: SpecialistSpec, state: SupportState) -> dict:
    settings = get_settings()
    max_steps = settings.max_specialist_tool_steps

    run = await repos.create_agent_run(
        state.session_id, spec.name, run_index=len(state.previous_agents)
    )
    await record(
        EventType.AGENT_STARTED,
        session_id=state.session_id,
        actor=spec.name,
        payload={"run_id": run.id, "run_index": run.run_index},
    )

    provider = get_provider()
    system = build_specialist_system(spec, max_steps)
    observations: list[str] = []
    tool_results: list[ToolResult] = []
    tools_used: list[str] = []
    steps_used = 0
    retries_total = 0
    result: SpecialistResult | None = None
    failure: AgentFailure | None = None

    # max_steps tool calls + 1 finishing decision + 1 grace iteration for a
    # budget-exhausted reminder. Hard bound regardless of model behavior.
    for _ in range(max_steps + 2):
        context = build_specialist_context(state, observations)
        outcome = await invoke_structured(
            provider,
            SpecialistStep,
            [("system", system), ("user", context)],
            agent_name=spec.name,
            session_id=state.session_id,
        )
        retries_total += outcome.retries
        if outcome.failure is not None:
            failure = outcome.failure
            break

        step: SpecialistStep = outcome.parsed  # type: ignore[assignment]
        if step.action == "finish":
            result = step.result
            break

        if steps_used >= max_steps:
            observations.append(
                "Tool budget exhausted — you must finish now with your best structured result."
            )
            steps_used += 1  # the grace iteration is also bounded
            continue

        tc = step.tool_call
        assert tc is not None  # enforced by SpecialistStep validator
        steps_used += 1
        if tc.tool_name not in spec.tools:
            observations.append(f"[{tc.tool_name}] refused: not in your tool catalog.")
            continue

        params = tc.params_dict()
        params["employee_id"] = state.employee_id  # pin to authenticated employee
        tr = await execute_tool(
            tc.tool_name,
            params,
            ToolContext(
                session_id=state.session_id,
                employee_id=state.employee_id,
                agent_name=spec.name,
                agent_run_id=run.id,
                authorized_privileged=False,
            ),
        )
        tool_results.append(tr)
        tools_used.append(tc.tool_name)
        status = "OK" if tr.status == "succeeded" else f"FAILED ({tr.error})"
        observations.append(f"[{tc.tool_name}] {status}: {tr.response_summary}")

    base_update = {
        "tool_results": tool_results,
        "previous_agents": [spec.name],
        "total_agent_step_count": state.total_agent_step_count + steps_used,
        "current_agent": spec.name,
    }

    if result is None:
        if failure is None:
            failure = AgentFailure(
                agent=spec.name,
                failure_type="budget_exhausted",
                detail=f"specialist step budget ({max_steps}) exhausted without a final result",
                recoverable=False,
            )
        await repos.complete_agent_run(
            run.id,
            status="failed",
            failure_type=failure.failure_type,
            failure_detail=failure.detail,
            recoverable=failure.recoverable,
            structured_output_retries=retries_total,
            tools_used=tools_used,
        )
        await record(
            EventType.AGENT_COMPLETED,
            session_id=state.session_id,
            actor=spec.name,
            payload={"run_id": run.id, "status": "failed", "failure": failure.model_dump()},
        )
        return {
            **base_update,
            "agent_failures": [failure],
            "structured_output_failure_count": state.structured_output_failure_count
            + (1 if failure.failure_type == "structured_output" else 0),
            "transition_history": [
                Transition(
                    from_node=spec.name, to_node="supervisor",
                    reason=f"agent failure: {failure.failure_type}",
                )
            ],
        }

    # Normalize: the runner, not the model, owns identity and evidence fields.
    fixes: dict = {}
    if result.agent != spec.name:
        fixes["agent"] = spec.name
    if any(finding.agent != spec.name for finding in result.findings):
        fixes["findings"] = [finding.model_copy(update={"agent": spec.name}) for finding in result.findings]
    if set(result.tools_used) != set(tools_used):
        fixes["tools_used"] = tools_used
    if result.outcome == "resolution_recommended" and result.confidence < settings.min_specialist_confidence:
        fixes["outcome"] = "unable_to_resolve"
        fixes["resolution_summary"] = None
        fixes["reasoning_summary"] = (
            result.reasoning_summary
            + " [Converted to unable_to_resolve: confidence below safe threshold.]"
        )
    if fixes:
        result = result.model_copy(update=fixes)

    if result.outcome == "handoff_recommended" and result.handoff is not None:
        await record(
            EventType.HANDOFF_REQUESTED,
            session_id=state.session_id,
            actor=spec.name,
            payload=result.handoff.model_dump(),
        )

    await repos.complete_agent_run(
        run.id,
        status="completed",
        outcome=result.outcome,
        confidence=result.confidence,
        reasoning_summary=result.reasoning_summary,
        findings=[f.model_dump() for f in result.findings],
        tools_used=tools_used,
        handoff_target=result.handoff.target_agent if result.handoff else None,
        structured_output_retries=retries_total,
        result=result.model_dump(mode="json"),
    )
    await record(
        EventType.AGENT_COMPLETED,
        session_id=state.session_id,
        actor=spec.name,
        payload={"run_id": run.id, "status": "completed", "result": result.model_dump(mode="json")},
    )

    update = {
        **base_update,
        "specialist_results": [result],
        "specialist_findings": list(result.findings),
        "awaiting_resolution_confirmation": False,
        "resolution_confirmation_answer": None,
        "resolution_confirmed": None,
        "transition_history": [
            Transition(from_node=spec.name, to_node="supervisor", reason=result.outcome)
        ],
    }
    if result.requested_action is not None:
        update["requested_action"] = result.requested_action
    return update


def make_specialist_node(spec: SpecialistSpec):
    async def node(state: SupportState) -> dict:
        return await run_specialist(spec, state)

    node.__name__ = f"specialist_{spec.name}"
    return node
