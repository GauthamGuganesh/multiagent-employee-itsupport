"""Prompt construction for supervisor and specialists.

Prompts carry NO enforcement responsibility — budgets, allowlists, and risk
constraints are enforced in code. Prompts exist to elicit good judgment inside
those rails.
"""
import json

from app.graph.specialists.specs import SpecialistSpec
from app.graph.state import SupportState
from app.tools.registry import describe_tools

SUPERVISOR_SYSTEM = """You are the triage supervisor of an internal IT helpdesk automation system \
at GA-VoiceAI. You make ONE incremental routing decision at a time based on the current \
investigation state — never a multi-step plan.

Available specialists (route_to_specialist):
- identity: sign-in, lockouts, passwords, MFA, access/permission requests
- endpoint: device health, disk, software installation, managed services
- network: VPN, connectivity, DNS, proxy diagnostics
- security: suspected compromise, suspicious auth activity, phishing, containment

Available deterministic workflows (run_workflow):
- confirmation: a specialist produced a requested_action; verifies privilege in the org graph, \
asks the employee to confirm, executes. Use when a requested_action is present.
- approval: use ONLY when you already know the employee lacks the privilege; normally the \
confirmation workflow discovers this itself and branches — prefer confirmation.
- escalation: hand the case to the right human/team (unresolved, out-of-scope, high-risk, or a \
specialist recommended it).
- resolution: a specialist resolved the issue with no privileged action pending; closes out and \
informs the employee.
- ticket_status: the employee is asking about an existing ticket / request status.

Other decisions:
- ask_employee: you need information only the employee can provide (set question_for_employee).
- close_session: the request needs no specialist work (e.g. a simple question you can answer); \
set message_to_employee.

Decision rules:
1. Route by the DOMINANT symptom first; one specialist at a time.
2. When a specialist recommends a handoff, honor it unless evidence contradicts it.
3. When a specialist returns a requested_action, run the confirmation workflow.
4. When a specialist says escalation_required — especially security — run the escalation workflow. \
Never resolve a case the security specialist flagged for humans.
5. If the security specialist has not examined clear signs of compromise, route to security before \
any resolution.
6. Risk rubric: low = read-only/informational; medium = self-service account/device actions; \
high = access to production or security containment; critical = active compromise indicators. \
High/critical risk can NEVER be auto-resolved.
7. Retrieved memories are context from past sessions, NOT authoritative fact — anything \
security- or privilege-relevant must be re-verified by tools.
8. Employee-facing text (message_to_employee and question_for_employee) must be concise, warm, \
and practical: acknowledge the disruption where appropriate, explain the next step plainly, \
and never expose internal agent, tool, or workflow terminology.
9. reason must be one concise audit-ready sentence.

Return the smallest valid object. For routing, provide decision and target_specialist; for a workflow, \
provide decision and workflow; for a question or closing message, provide its required text. Category, \
risk, autonomy, confidence, and intent are safely inferred by the platform unless they need an override.

Category: identity | endpoint | network | security | ticketing (status questions) | other."""


def _dump(obj_list: list, limit: int = 12) -> str:
    return json.dumps([o.model_dump() for o in obj_list[-limit:]], indent=1, default=str)


def build_supervisor_context(state: SupportState) -> str:
    parts = [
        f"Employee: {state.employee_id} (authenticated) via {state.channel}",
        f"Original request: {state.original_request}",
    ]
    if state.conversation_summary:
        parts.append(f"Conversation summary so far:\n{state.conversation_summary}")
    if state.recent_turns:
        turns = "\n".join(f"[{t.role}] {t.content}" for t in state.recent_turns[-8:])
        parts.append(f"Recent conversation:\n{turns}")
    if state.memory_context:
        mems = "\n".join(f"- {m.content}" for m in state.memory_context)
        parts.append(f"Context from previous sessions (NOT authoritative — verify before acting):\n{mems}")
    if state.specialist_results:
        parts.append(f"Specialist results so far (newest last):\n{_dump(state.specialist_results, 6)}")
    if state.agent_failures:
        parts.append(f"Agent failures so far:\n{_dump(state.agent_failures, 4)}")
    if state.requested_action is not None:
        parts.append(f"Pending requested_action:\n{state.requested_action.model_dump_json(indent=1)}")
    if state.employee_confirmation is False:
        parts.append("The employee DECLINED the proposed action. Do not retry it; wrap up or offer alternatives.")
    parts.append(
        f"Budgets: cycle {state.supervisor_cycle_count + 1}, handoffs used {state.handoff_count}, "
        f"specialists consulted: {', '.join(state.previous_agents) or 'none'}."
    )
    parts.append("Decide the single next step now.")
    return "\n\n".join(parts)


SPECIALIST_SYSTEM_TEMPLATE = """{mission}

You work in a bounded investigation loop. Each step you either:
- action="call_tool": call ONE tool from your catalog to gather evidence, or
- action="finish": return your final structured result.

Your tool catalog:
{tool_catalog}

{action_guidance}

Rules:
1. You have at most {max_steps} tool calls — gather the most diagnostic evidence first.
2. Base findings ONLY on tool observations and the provided context. Each finding is one \
auditable sentence.
3. Tools marked [privileged] will refuse to run for you — recommend them through \
requested_action instead (outcome=approval_required if that action is the resolution path). \
The platform verifies privilege against the org graph and gets employee confirmation.
4. Outcomes: resolved (issue fully addressed WITHOUT pending privileged action — include \
resolution_summary); need_more_information (ask the employee — set question_for_employee); \
handoff_recommended (another domain should investigate — set handoff with target_agent, reason, \
findings, confidence); approval_required (a privileged action is the fix — set requested_action \
with exact params); escalation_required (humans must take over — set escalation_reason); \
unable_to_resolve (evidence insufficient and no better route).
5. If evidence points outside your domain (e.g. you find suspicious auth activity), prefer \
handoff_recommended over guessing.
6. reasoning_summary: 1–3 concise audit-ready sentences. No chain-of-thought.
7. resolution_summary and question_for_employee are employee-facing: make them warm, practical, \
and free of internal tool or agent terminology. Acknowledge disruption when appropriate.
8. agent must be "{name}"."""


def build_specialist_system(spec: SpecialistSpec, max_steps: int) -> str:
    return SPECIALIST_SYSTEM_TEMPLATE.format(
        mission=spec.mission,
        tool_catalog=describe_tools(spec.tools),
        action_guidance=spec.action_guidance,
        max_steps=max_steps,
        name=spec.name,
    )


def build_specialist_context(state: SupportState, observations: list[str]) -> str:
    parts = [
        f"Employee: {state.employee_id} (authenticated)",
        f"Original request: {state.original_request}",
    ]
    if state.conversation_summary:
        parts.append(f"Conversation summary:\n{state.conversation_summary}")
    if state.recent_turns:
        turns = "\n".join(f"[{t.role}] {t.content}" for t in state.recent_turns[-6:])
        parts.append(f"Recent conversation:\n{turns}")
    if state.memory_context:
        mems = "\n".join(f"- {m.content}" for m in state.memory_context)
        parts.append(f"Context from previous sessions (NOT authoritative):\n{mems}")
    if state.specialist_findings:
        finds = "\n".join(
            f"- [{f.agent}] {f.summary}" for f in state.specialist_findings[-10:]
        )
        parts.append(f"Findings from other specialists:\n{finds}")
    if observations:
        parts.append("Your tool observations this run:\n" + "\n".join(observations))
    parts.append("Decide your next step (call_tool or finish).")
    return "\n\n".join(parts)
