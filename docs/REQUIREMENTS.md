# Hard Requirements Checklist (from project brief)

Compact, testable restatement of the brief. Every item must be satisfied in
code or explicitly deferred with rationale. No RAG/vector search.

## Architecture (frozen)
- [ ] Supervisor pattern (NOT planner-executor); incremental decisions, no upfront multi-step plan
- [ ] Same supervisor handles initial triage (classify/intent/risk/autonomy/first specialist) and post-specialist routing
- [ ] 4 specialists: identity, endpoint, network, security — separated by reasoning responsibility
- [ ] Specialists never invoke each other; findings return to supervisor; supervisor controls routing
- [ ] One generic handoff contract (target_agent, reason, findings, confidence); supervisor validates target
- [ ] No A2A protocol; single LangGraph app; communication via shared typed state
- [ ] Specialist internal loop: Reason → Act → Observe → Decide; may call multiple tools

## State
- [ ] Strongly typed LangGraph state incl. session_id, employee_id, original_request, conversation_summary, category, intent, risk_level, autonomy_level, current_agent, previous_agents, specialist_findings, tool_results, requested_action, privilege_check_result, employee_confirmation, ticket_id, approval_id, escalation_required, escalation_reason, human_target, supervisor_cycle_count, total_agent_step_count, structured_output_failure_count, terminal_status, final_response
- [ ] No arbitrary untyped dicts as primary contracts

## Execution limits (in code, not prompts)
- [ ] MAX_SUPERVISOR_CYCLES=8, MAX_SPECIALIST_TOOL_STEPS=5, MAX_AGENT_HANDOFFS=4, MAX_STRUCTURED_OUTPUT_RETRIES=2 (configurable)
- [ ] Track cycles, total steps, handoffs, transition history, repeated state signatures
- [ ] Detect Network↔Security ping-pong; repeated unresolved transition → stop + human escalation
- [ ] Budget exhaustion: stop autonomy, preserve findings, create/upgrade ticket, route to best human, tell employee; never crash or silently stop

## Structured output
- [ ] Every LLM node returns Pydantic-enforced output via structured-output APIs (no regex/JSON-in-prose/manual parsing)
- [ ] Models: SupervisorDecision, SpecialistResult, HandoffRequest, RequestedAction/ResolutionRecommendation, EscalationRecommendation, NeedMoreInformation (as fields/outcomes), AgentFailure
- [ ] Validation failure → retry (max 2) → AgentFailure → audit → graceful termination/escalation; never a 3rd retry

## Success/failure criteria (encoded in code/tests)
- [ ] Supervisor success: valid schema, valid target node, routing compatible with state, risk constraints respected
- [ ] Supervisor failure (invalid output after retries / unknown agent / prohibited transition / budget / repeat loop) → graceful escalate or terminate
- [ ] Specialist success: one valid outcome of resolved | need_more_information | handoff_recommended | approval_required | escalation_required | unable_to_resolve, with findings, tools_used, confidence, concise audit rationale (no hidden CoT stored)
- [ ] Specialist failure (tool failures, schema violations, low confidence, exceeds authority, step budget, out of domain) → structured failure/escalation

## Deterministic workflows (not agents)
- [ ] Resolution: validate → optional permitted tool → persist → notify → close
- [ ] Confirmation: Neo4j privilege check → exact action summary → explicit yes/no → execute on yes → persist confirmation + action → report. Voice confirms intent, not identity
- [ ] Approval: approver via Neo4j → approval request persisted → employee notified → in dashboard queue
- [ ] Escalation: validate → current ownership → Neo4j target → ticket create/update → escalation event → notify human + employee → end/pause
- [ ] Need-more-info: question → employee answer merged into state → resume

## Ticket status + aging
- [ ] get_ticket_status backed by Postgres (natural queries + by number)
- [ ] Pending age > PENDING_ESCALATION_DAYS(=3, calendar) → auto escalation workflow (owner → Neo4j next target → event → status/metadata update → inform employee). No full SLA engine

## Neo4j (authoritative org)
- [ ] Nodes: Employee, Team, Department, Role, Privilege, System, SupportTeam
- [ ] Rels: REPORTS_TO, MEMBER_OF, HAS_ROLE, HAS_PRIVILEGE, PART_OF, OWNS, GRANTS/ELIGIBLE_FOR, SUPPORTED_BY, ESCALATES_TO, APPROVAL_BY
- [ ] Typed tools: get_employee_org_context, get_manager, has_privilege, get_system_owner, get_support_team, get_required_approver, get_escalation_target
- [ ] No raw LLM Cypher in V1; parameterized queries only
- [ ] Seed: ~60 employees (Eng ~20, Product ~7, Finance ~6, HR ~5, Sales/CS ~10, IT/Platform ~8, Security ~4), deterministic EMP-001..060, idempotent, intentional edge cases (overlapping privileges, missing privileges, exception grants, escalation chains, approvers, owners)

## Postgres (operational/audit truth)
- [ ] Tables: support_sessions, messages, tickets, ticket_status_history, agent_runs, tool_calls, approval_requests, escalation_events, action_confirmations, action_executions, audit_events
- [ ] Org IDs are logical references to Neo4j; no duplicated hierarchy
- [ ] Every significant autonomous decision/action auditable; events persisted before broadcast

## Tools
- [ ] Identity: get_account_status, unlock_account, reset_password, get_recent_auth_events, revoke_sessions
- [ ] Endpoint: get_device_details, run_device_health_check, install_approved_software, restart_managed_service, check_disk_space
- [ ] Network: check_vpn_status, run_connectivity_diagnostics, check_dns, check_proxy, inspect_recent_vpn_session
- [ ] Security: get_recent_security_events, revoke_active_sessions, quarantine_device, flag_account_for_security_review, notify_security_team
- [ ] Ticketing: create_ticket, get_ticket_status, update_ticket, create_approval_request, record_escalation
- [ ] Typed input/output schemas; safe deterministic mocks

## Memory
- [ ] LangGraph state = current session; compaction (summary + recent raw turns; thresholds configurable: 12000 tokens / 8 messages); compaction never touches Postgres history
- [ ] Mem0 cross-session memory: retrieve semantically relevant at session start; write durable facts at checkpoints only; never authoritative for privileges/roles/managers/entitlements/ticket/approval/security state; verify via Neo4j/Postgres before acting
- [ ] Dashboard shows memory retrieval/writes per run (ids, contents, scores, included-in-context, new-memory-written)

## Frontend — employee
- [ ] No internal jargon (nodes, cycles, handoff JSON, tool traces)
- [ ] Chat + ElevenLabs voice first-class, streaming, subtle progress updates ("Checking your account…"), confirmation cards, approval/ticket cards, My Requests + ticket detail, responsive, light/dark, keyboard accessible, reduced motion
- [ ] Restrained enterprise design (Geist/Inter; slate base, blue/indigo primary, green success, amber pending, red critical, violet sparingly). No rainbow gradients/glassmorphism/glow/gimmicks

## Frontend — command center
- [ ] Nav: Overview, Live Sessions, Tickets, Approvals, Escalations, Audit, Organization Graph
- [ ] Overview metrics: active sessions, resolved today, open tickets, pending approvals, escalated, pending>3d, human interventions, agent failures, loop-guard activations, structured-output failures
- [ ] Live chronological execution timeline (request → decisions → agents → tools → findings → handoffs → terminal) with structured output, tool req/resp, timestamps, confidence, transition reasons, failures/retries. No hidden CoT
- [ ] Ticket table filters (status, category, team, owner, originating agent, date range, pending>3d, escalated, approval pending, security, text search) + sorts (newest, oldest, longest pending, recently updated)
- [ ] Agent-run filters (agent, outcome, success/failure, handoffs, structured-output failure, loop guard, tool failure, date range)
- [ ] Human intervention queue: approvals awaiting decision (approve/reject works), escalated incidents, automation-exhausted, out-of-scope
- [ ] Every visible control functional; SSE (preferred) live updates; events persisted before broadcast

## Observability
- [ ] Event types: SESSION_STARTED, SUPERVISOR_DECISION, AGENT_STARTED, AGENT_COMPLETED, TOOL_CALLED, TOOL_SUCCEEDED, TOOL_FAILED, HANDOFF_REQUESTED, HANDOFF_COMPLETED, STRUCTURED_OUTPUT_RETRY, STRUCTURED_OUTPUT_FAILED, LOOP_GUARD_TRIGGERED, USER_CONFIRMATION_REQUESTED, USER_CONFIRMED, ACTION_EXECUTED, APPROVAL_REQUESTED, APPROVAL_DECIDED, TICKET_CREATED, TICKET_STATUS_CHANGED, ESCALATION_TRIGGERED, HUMAN_INTERVENTION, SESSION_COMPLETED

## Tests (required)
- [ ] Supervisor routing (identity/endpoint/network/security/multi-domain)
- [ ] Cross-agent: VPN → network → suspicious auth → supervisor → security
- [ ] Loop prevention: adversarial network↔security handoffs → hard termination
- [ ] Structured-output: retry 1, retry 2, graceful AgentFailure, no 3rd retry
- [ ] Tool failures: network timeout, Neo4j down, Postgres failure → safe degradation
- [ ] Privilege confirmation: yes → executes; no → does not
- [ ] Missing privilege → approval with correct Neo4j approver
- [ ] Ticket aging: >3 days pending → target resolved, event created
- [ ] Security: high-risk + security-recommends-human ⇒ never silent auto-resolve
