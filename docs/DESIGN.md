# Design — Multi-Agent Employee IT Support Platform

Fictional organization: **GA-VoiceAI** (~60 employees).
This document is the implementation contract. It covers the seven pre-code
deliverables: repository structure, LangGraph state model, Pydantic output
contracts, Neo4j graph schema, Postgres schema, execution-limit / failure-state
design, and the first 10 end-to-end acceptance scenarios.

---

## 0. Stack decisions (rationale up front)

| Concern | Choice | Why |
|---|---|---|
| Orchestration | LangGraph (Python) | Frozen requirement; supervisor pattern with conditional edges + `interrupt()` for human-in-the-loop |
| LLM | OpenAI Python SDK (`gpt-4o-mini` default, configurable) plus a scripted provider mode | Native Pydantic structured output with deterministic tests without API keys |
| API | FastAPI + SSE (`sse-starlette`) | One-way live event streaming to the command center; simpler than WebSockets and sufficient |
| Operational store | PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic | Audit source of truth; migrations from day one |
| Org/privilege store | Hosted Neo4j (Aura or equivalent) via official driver, **parameterized Cypher only** | Authoritative org graph; no LLM-generated Cypher in V1 |
| Cross-session memory | Mem0 (`mem0ai`) behind a `MemoryService` protocol, with a local JSON fallback | Real Mem0 when keys are configured; runnable offline demo/tests otherwise |
| Session checkpointing | LangGraph checkpointer (Postgres saver; in-memory for tests) | `interrupt()`/resume across HTTP turns |
| Frontend | One Next.js (App Router, TypeScript, Tailwind) app: `/` employee experience, `/ops` command center | Two experiences, one deploy; shared design tokens |
| Voice | ElevenLabs Agents (`@elevenlabs/react`) + backend signed-URL & webhook-tool bridge | First-class voice; degrades gracefully when unconfigured |
| Auth | Demo employee-ID/password sign-in with signed session cookie | Fictional org; deterministic credentials documented as non-production |

Architectural rule (frozen): supervisor orchestrates reasoning; specialists
investigate; tools touch systems; Neo4j answers org/privilege questions;
Postgres records operational truth; deterministic workflows execute process;
humans are the final fallback.

---

## 1. Repository structure

```
agentic-employee-it-support/
├── docker-compose.yml            # local postgres:16
├── .env.example
├── README.md
├── docs/
│   ├── DESIGN.md                 # this document
│   └── ACCEPTANCE_SCENARIOS.md   # runnable demo script per scenario
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py               # FastAPI app factory + lifespan wiring
│   │   ├── config.py             # Settings + ALL execution-limit constants
│   │   ├── api/
│   │   │   ├── deps.py           # auth/session dependencies
│   │   │   ├── routes_auth.py    # demo sign-in-as-employee
│   │   │   ├── routes_chat.py    # start session, send message, resume interrupts
│   │   │   ├── routes_tickets.py # my requests + ticket status
│   │   │   ├── routes_ops.py     # command-center queries (metrics, runs, filters)
│   │   │   ├── routes_stream.py  # SSE event stream
│   │   │   └── routes_voice.py   # ElevenLabs signed URL + agent webhook bridge
│   │   ├── contracts/            # Pydantic output contracts (section 3)
│   │   │   ├── enums.py
│   │   │   ├── common.py         # Finding, ToolResult, RequestedAction, ...
│   │   │   ├── supervisor.py     # SupervisorDecision
│   │   │   └── specialist.py     # SpecialistStep, SpecialistResult, AgentFailure
│   │   ├── graph/
│   │   │   ├── state.py          # SupportState (section 2)
│   │   │   ├── build.py          # graph assembly + conditional edges
│   │   │   ├── supervisor.py     # supervisor node (both invocation modes)
│   │   │   ├── guards.py         # budgets, transition-signature loop detection
│   │   │   ├── structured.py     # structured-output invoke + bounded retry
│   │   │   ├── specialists/
│   │   │   │   ├── runner.py     # generic bounded Reason→Act→Observe→Decide loop
│   │   │   │   ├── specs.py      # SpecialistSpec registry (prompt + tool allowlist)
│   │   │   │   └── prompts.py
│   │   │   └── workflows/        # deterministic nodes (no LLM control flow)
│   │   │       ├── resolution.py
│   │   │       ├── confirmation.py
│   │   │       ├── approval.py
│   │   │       ├── escalation.py
│   │   │       └── need_info.py
│   │   ├── tools/
│   │   │   ├── registry.py       # typed registration, allowlists, privilege gating
│   │   │   ├── mockworld.py      # deterministic per-employee scenario fixtures
│   │   │   ├── identity.py  endpoint.py  network.py  security.py  ticketing.py
│   │   ├── org/                  # Neo4j
│   │   │   ├── client.py
│   │   │   ├── queries.py        # named, parameterized Cypher strings
│   │   │   └── service.py        # typed functions (get_manager, has_privilege, ...)
│   │   ├── db/
│   │   │   ├── base.py           # engine/session factory
│   │   │   ├── models.py         # SQLAlchemy models (section 5)
│   │   │   └── repos.py          # repositories per aggregate
│   │   ├── events/
│   │   │   ├── types.py          # EventType enum (section 6.5)
│   │   │   ├── recorder.py       # persist audit_events THEN publish
│   │   │   └── bus.py            # in-process pub/sub feeding SSE
│   │   ├── memory/
│   │   │   ├── service.py        # MemoryService protocol + Mem0 + local fallback
│   │   │   └── policy.py         # what gets written / retrieval filtering
│   │   ├── conversation/
│   │   │   └── compaction.py     # summary + recent-turns window
│   │   ├── llm/
│   │   │   └── provider.py       # anthropic | fake
│   │   └── seeds/
│   │       ├── seed_org.py       # idempotent 60-employee Neo4j seed
│   │       └── seed_demo.py      # demo tickets (incl. one pending >3 days)
│   └── tests/
│       ├── unit/                 # contracts, guards, compaction, tools, workflows
│       └── integration/          # graph runs with FakeLLM; DB-backed when available
└── frontend/
    ├── package.json
    ├── app/
    │   ├── (employee)/           # chat, voice, my requests
    │   └── ops/                  # overview, sessions, tickets, approvals,
    │                             # escalations, audit, org graph
    ├── components/               # design system + feature components
    └── lib/                      # API client, SSE hook, types
```

---

## 2. Concrete LangGraph state model

Pydantic `BaseModel` used as the LangGraph `state_schema`. Append-only lists
use `Annotated[list[T], operator.add]` reducers; everything else is
last-write-wins. No untyped dict is a primary contract (tool params are a
bounded `dict[str, str | int | bool]` leaf validated against each tool's input
model before execution).

```python
class SupportState(BaseModel):
    # identity & request
    session_id: str
    employee_id: str                                  # authenticated, e.g. "EMP-032"
    channel: Channel                                  # web | voice
    original_request: str

    # conversational context (compacted view sent to LLMs)
    conversation_summary: str = ""
    recent_turns: Annotated[list[ChatTurn], add] = []
    memory_context: list[RetrievedMemory] = []        # Mem0 retrieval at session start

    # triage
    category: Category | None = None                  # identity|endpoint|network|security|ticketing|other
    intent: str | None = None
    risk_level: RiskLevel | None = None               # low|medium|high|critical
    autonomy_level: AutonomyLevel | None = None       # auto_resolve|confirm_required|approval_required|human_only

    # routing & investigation
    current_agent: str | None = None
    previous_agents: Annotated[list[str], add] = []
    transition_history: Annotated[list[Transition], add] = []   # (from, to, reason)
    specialist_results: Annotated[list[SpecialistResult], add] = []
    specialist_findings: Annotated[list[Finding], add] = []
    tool_results: Annotated[list[ToolResult], add] = []
    agent_failures: Annotated[list[AgentFailure], add] = []

    # privileged-action pipeline
    requested_action: RequestedAction | None = None
    privilege_check: PrivilegeCheckResult | None = None
    employee_confirmation: bool | None = None

    # operational references (Postgres IDs)
    ticket_id: str | None = None
    approval_id: str | None = None

    # escalation
    escalation_required: bool = False
    escalation_reason: str | None = None
    human_target: HumanTarget | None = None           # employee_id + team_key

    # hard budgets & loop detection (guards read/write these)
    supervisor_cycle_count: int = 0
    total_agent_step_count: int = 0
    handoff_count: int = 0
    structured_output_failure_count: int = 0
    decision_signatures: Annotated[list[str], add] = []   # loop detection (§6.3)
    loop_guard_triggered: bool = False

    # interaction
    pending_question: str | None = None               # need-more-info / confirmation prompt

    # terminal
    terminal_status: TerminalStatus | None = None     # resolved|approval_pending|escalated|failed|abandoned
    final_response: str | None = None
```

Graph topology:

```
START → session_init (memory retrieval + persistence) → supervisor
supervisor →(conditional)→ identity | endpoint | network | security
          | need_info | confirmation | approval | escalation | resolution
each specialist → guard-checked → supervisor
need_info    → interrupt() → merge answer → supervisor
confirmation → interrupt() → yes: execute+resolution / no: supervisor
resolution | approval | escalation → session_finalize (memory write, events) → END
```

Guards are enforced *on the edges and node entries in code*, never by prompt.

---

## 3. Pydantic output contracts

All LLM-powered nodes go through `structured.py::invoke_structured(model, schema)`,
which uses `with_structured_output` and applies the bounded retry policy (§6.2).

```python
# enums.py
SpecialistName = Literal["identity", "endpoint", "network", "security"]
WorkflowName   = Literal["resolution", "confirmation", "approval", "escalation", "need_info"]
RiskLevel      = Literal["low", "medium", "high", "critical"]
AutonomyLevel  = Literal["auto_resolve", "confirm_required", "approval_required", "human_only"]
Category       = Literal["identity", "endpoint", "network", "security", "ticketing", "other"]

# common.py
class Finding(BaseModel):
    agent: str
    summary: str                       # one auditable sentence
    detail: str = ""
    severity: RiskLevel = "low"
    tags: list[str] = []               # e.g. ["vpn", "suspicious-auth"]

class ToolResult(BaseModel):
    tool_name: str
    agent: str
    status: Literal["succeeded", "failed"]
    request: dict[str, str | int | bool]
    response_summary: str              # concise, audit-ready
    error: str | None = None

class RequestedAction(BaseModel):
    action_key: str                    # must exist in tool registry as executable
    summary: str                       # exact human-readable action statement
    privilege_key: str                 # Neo4j privilege required
    system_key: str | None = None
    params: dict[str, str | int | bool] = {}
    risk_level: RiskLevel

class PrivilegeCheckResult(BaseModel):
    employee_id: str
    privilege_key: str
    has_privilege: bool
    eligible_with_approval: bool
    approver_employee_id: str | None
    source: Literal["neo4j"] = "neo4j" # provenance: never Mem0

class HandoffRequest(BaseModel):       # ONE generic contract for every agent pair
    outcome: Literal["handoff"] = "handoff"
    target_agent: SpecialistName
    reason: str
    findings: list[str]
    confidence: float                  # 0..1

class AgentFailure(BaseModel):
    agent: str
    failure_type: Literal["structured_output", "tool_failure", "budget_exhausted",
                          "low_confidence", "out_of_domain", "internal_error"]
    detail: str
    recoverable: bool

# supervisor.py
class SupervisorDecision(BaseModel):
    decision: Literal["route_to_specialist", "ask_employee", "run_workflow", "close_session"]
    target_specialist: SpecialistName | None = None
    workflow: WorkflowName | None = None
    category: Category
    intent: str
    risk_level: RiskLevel
    autonomy_level: AutonomyLevel
    question_for_employee: str | None = None
    reason: str                        # concise, audit-ready
    confidence: float
    # model_validator: decision-specific required fields; e.g. route_to_specialist
    # requires target_specialist; ask_employee requires question_for_employee.

# specialist.py
class ToolCallSpec(BaseModel):
    tool_name: str
    params: dict[str, str | int | bool] = {}

class SpecialistStep(BaseModel):       # each iteration of the internal loop
    action: Literal["call_tool", "finish"]
    tool_call: ToolCallSpec | None = None
    result: "SpecialistResult | None" = None

class SpecialistResult(BaseModel):
    agent: SpecialistName
    outcome: Literal["resolution_recommended", "need_more_information", "handoff_recommended",
                     "approval_required", "escalation_required", "unable_to_resolve"]
    findings: list[Finding]
    tools_used: list[str]
    confidence: float
    reasoning_summary: str             # concise rationale; NOT chain-of-thought
    question_for_employee: str | None = None
    handoff: HandoffRequest | None = None
    requested_action: RequestedAction | None = None
    escalation_reason: str | None = None
    resolution_summary: str | None = None
    # model_validator enforces outcome-specific required fields.
```

`resolution_recommended` is deliberately non-terminal: it means the specialist
has enough evidence to propose a remediation or result. The Supervisor pauses
for the employee to test it; only employee confirmation permits terminal
`resolved`. Routine resolved conversations do not create tickets.

Success/failure criteria from the brief are encoded as validators plus guard
checks in code (supervisor target must be a real node; risk constraints:
`risk_level in {high, critical}` forbids `auto_resolve`; security-flagged
sessions can never terminate via silent auto-resolution).

---

## 4. Neo4j graph schema

Authoritative for org structure, privileges, ownership, escalation. Postgres
stores only logical `EMP-xxx` / key references.

**Nodes**

| Label | Key properties |
|---|---|
| `Employee` | `id` ("EMP-001"…"EMP-060", unique), `name`, `email`, `title`, `location`, `remote: bool` |
| `Team` | `key` (unique), `name` |
| `Department` | `key` (unique), `name` |
| `Role` | `key` (unique), `name`, `level: int` |
| `Privilege` | `key` (unique), `name`, `description`, `risk_level` |
| `System` | `key` (unique), `name`, `category` |
| `SupportTeam` | `key` (unique), `name`, `queue` |

**Relationships**

```
(Employee)-[:REPORTS_TO]->(Employee)
(Employee)-[:MEMBER_OF]->(Team)
(Employee)-[:HAS_ROLE]->(Role)
(Employee)-[:HAS_PRIVILEGE]->(Privilege)        // direct grants / exceptions
(Employee)-[:ON_SUPPORT_TEAM]->(SupportTeam)
(Team)-[:PART_OF]->(Department)
(Team)-[:OWNS]->(System)
(Role)-[:GRANTS]->(Privilege)                    // automatic with role
(Role)-[:ELIGIBLE_FOR]->(Privilege)              // approvable on request
(Privilege)-[:APPROVAL_BY]->(Role)               // who may approve grants
(System)-[:SUPPORTED_BY]->(SupportTeam)
(SupportTeam)-[:ESCALATES_TO {level: int}]->(Employee)
```

**Semantics**

- *Effective privilege*: `(e)-[:HAS_PRIVILEGE]->(p)` OR `(e)-[:HAS_ROLE]->()-[:GRANTS]->(p)`.
- *Approver resolution* (`get_required_approver`): nearest employee up the
  requester's `REPORTS_TO` chain holding a role with `(p)<-[:APPROVAL_BY]-(role)`;
  fallback: manager of the owning team; final fallback: direct manager.
- *Escalation target* (`get_escalation_target`): system → `SUPPORTED_BY` →
  `ESCALATES_TO` ordered by `level`; next level above `current_owner_id`.

**Typed tools (parameterized Cypher only, no raw generation):**
`get_employee_org_context`, `get_manager`, `has_privilege`,
`get_system_owner`, `get_support_team`, `get_required_approver`,
`get_escalation_target`.

Seed (idempotent `MERGE`-based, deterministic IDs): CEO → CTO/CPO/CFO/CHRO/CRO
tree; Engineering ~20 (backend + frontend teams), Product 7, Finance 6, HR 5,
Sales/CS 10, Platform/IT 8 (includes IT Support SupportTeam), Security 4.
Intentional edge cases: senior engineers with `production_logs`; a direct
`HAS_PRIVILEGE` exception grant; an employee eligible-but-not-granted
`docker_desktop`; a contractor with minimal grants; VPN owned by Platform,
supported by IT Support, escalating IT Support → Platform Manager → CTO;
security systems escalating to Security Lead.

---

## 5. PostgreSQL schema (operational + audit truth)

All org references are logical IDs (`EMP-xxx`, team/privilege keys) resolved
against Neo4j at read time — no duplicated hierarchy.

| Table | Purpose / key columns |
|---|---|
| `support_sessions` | `id` (uuid pk), `employee_id`, `channel`, `status` (active/waiting_employee/completed/escalated/failed), `terminal_status`, `final_response`, `conversation_summary`, `langgraph_thread_id`, timestamps |
| `messages` | `id`, `session_id` fk, `role` (employee/assistant/system), `content`, `source` (text/voice), `created_at` — **full transcript, never compacted** |
| `tickets` | `id`, `ticket_number` ("IT-1001", sequence), `session_id`, `requester_employee_id`, `category`, `title`, `description`, `status` (open/pending/in_progress/waiting_approval/resolved/closed/escalated), `priority`, `current_owner_id`, `current_team_key`, `security_related`, `escalated`, `pending_since`, timestamps |
| `ticket_status_history` | `ticket_id` fk, `from_status`, `to_status`, `changed_by`, `reason`, `created_at` |
| `agent_runs` | `id`, `session_id`, `agent_name`, `run_index`, `status`, `outcome`, `confidence`, `reasoning_summary`, `findings` (jsonb), `tools_used` (jsonb), `handoff_target`, `structured_output_retries`, `loop_guard_triggered`, `memory_ids_retrieved` (jsonb), `memory_written`, `started_at`, `completed_at` |
| `tool_calls` | `id`, `agent_run_id` fk, `session_id`, `tool_name`, `request` (jsonb), `response` (jsonb), `status`, `error`, `duration_ms`, `created_at` |
| `approval_requests` | `id`, `ticket_id`, `session_id`, `requester_employee_id`, `approver_employee_id`, `privilege_key`, `system_key`, `action_summary`, `status` (pending/approved/rejected/cancelled), `decision_reason`, `decided_at`, `created_at` |
| `escalation_events` | `id`, `ticket_id`, `session_id`, `reason`, `trigger` (agent_recommendation/budget_exhausted/loop_guard/pending_age/security/structured_output_failure), `from_owner_id`, `to_target_id`, `to_team_key`, `created_at` |
| `action_confirmations` | `id`, `session_id`, `employee_id`, `action_key`, `action_summary`, `params` (jsonb), `confirmed` (bool nullable until answered), `created_at`, `responded_at` |
| `action_executions` | `id`, `session_id`, `confirmation_id` fk?, `approval_id` fk?, `action_key`, `params` (jsonb), `result` (jsonb), `status`, `created_at` |
| `audit_events` | `id`, `session_id?`, `ticket_id?`, `event_type` (§6.5 enum), `actor`, `payload` (jsonb), `created_at` — persisted **before** SSE broadcast |

Indexes: sessions by employee/status; tickets by status, `pending_since`,
`requester_employee_id`, `ticket_number`; audit_events by session/created_at;
agent_runs by session.

---

## 6. Execution limits & failure-state design

### 6.1 Budgets (config constants, env-overridable)

```python
MAX_SUPERVISOR_CYCLES = 8
MAX_SPECIALIST_TOOL_STEPS = 5
MAX_AGENT_HANDOFFS = 4
MAX_STRUCTURED_OUTPUT_RETRIES = 2
LOOP_SIGNATURE_REPEAT_LIMIT = 2
PENDING_ESCALATION_DAYS = 3
CONVERSATION_COMPACTION_TOKEN_THRESHOLD = 12000
RECENT_MESSAGES_TO_RETAIN = 8
```

Enforced in code: supervisor node increments `supervisor_cycle_count` on entry
and force-routes to the escalation workflow when exceeded; the specialist
runner is a plain-Python bounded loop (`for step in range(MAX_SPECIALIST_TOOL_STEPS)`);
handoff counting happens in the routing function, not the prompt. LangGraph
`recursion_limit` is additionally set as a belt-and-braces backstop.

### 6.2 Structured-output retry policy

`invoke_structured()`: attempt → on validation failure record
`STRUCTURED_OUTPUT_RETRY` and re-invoke with the validation error appended →
at most `MAX_STRUCTURED_OUTPUT_RETRIES` retries → then record
`STRUCTURED_OUTPUT_FAILED`, emit `AgentFailure(failure_type="structured_output")`,
persist to `agent_runs`, and return control: specialist failure → supervisor;
supervisor failure → escalation workflow. Never a third retry; never a crash.

### 6.3 Loop detection

After each supervisor decision, compute
`signature = sha256(decision.decision | target | outcome_of_last_specialist | len(findings))`.
If the same signature has already occurred `LOOP_SIGNATURE_REPEAT_LIMIT` times
(i.e., the same unresolved transition with no new evidence), trip the loop
guard: record `LOOP_GUARD_TRIGGERED`, stop autonomous routing, and enter the
escalation workflow. This catches Network ↔ Security ping-pong even when each
individual budget still has headroom.

### 6.4 Budget-exhaustion behavior (uniform)

1. stop further autonomous agent calls
2. preserve all findings/tool results in state + Postgres
3. create or upgrade the ticket
4. resolve the best human target via Neo4j (`get_escalation_target`)
5. tell the employee investigation reached its safe execution limit and has
   been escalated — never crash, never silently stop.

### 6.5 Event model (persist → broadcast)

`SESSION_STARTED, SUPERVISOR_DECISION, AGENT_STARTED, AGENT_COMPLETED,
TOOL_CALLED, TOOL_SUCCEEDED, TOOL_FAILED, HANDOFF_REQUESTED, HANDOFF_COMPLETED,
STRUCTURED_OUTPUT_RETRY, STRUCTURED_OUTPUT_FAILED, LOOP_GUARD_TRIGGERED,
USER_CONFIRMATION_REQUESTED, USER_CONFIRMED, ACTION_EXECUTED,
APPROVAL_REQUESTED, APPROVAL_DECIDED, TICKET_CREATED, TICKET_STATUS_CHANGED,
ESCALATION_TRIGGERED, HUMAN_INTERVENTION, MEMORY_RETRIEVED, MEMORY_WRITTEN,
SESSION_COMPLETED`

### 6.6 Safety invariants (tested)

- Privileged executable tools refuse to run outside the confirmation/approval
  workflows (registry-level gate, not prompt-level).
- `PrivilegeCheckResult.source` is always Neo4j; Mem0 content can never
  satisfy a privilege check.
- `risk_level ∈ {high, critical}` ⇒ autonomy ≤ `confirm_required`; security
  specialist's `escalation_required` can never be downgraded to auto-resolve.
- Voice confirms **intent** only; identity comes from the authenticated session.

---

## 7. First 10 end-to-end acceptance scenarios

| # | Scenario | Path | Pass criteria |
|---|---|---|---|
| 1 | **Locked account, self-service unlock** — EMP-034: "I'm locked out after mistyping my password." | supervisor → identity → `get_account_status` (locked) → `requested_action: unlock_account` → confirmation workflow → yes → execute → resolution | Confirmation card shown with exact action; `action_executions` row; ticket resolved; employee told outcome |
| 2 | **VPN → Security cross-domain** — EMP-014: "VPN keeps dropping since yesterday." | supervisor → network (`check_vpn_status`, `inspect_recent_vpn_session` → unknown IP) → generic `HandoffRequest(security)` → supervisor → security (`get_recent_security_events`) → escalation to Security team | Handoff validated & recorded; security escalation event targets Security Lead via Neo4j; session ends escalated, findings preserved |
| 3 | **Software install, has privilege** — EMP-028 (platform engineer): "Install Docker Desktop on my laptop." | supervisor → endpoint → `has_privilege` true (Neo4j) → confirmation → yes → `install_approved_software` → resolution | Neo4j check recorded with source=neo4j; execution only after affirmative confirmation |
| 4 | **Software install, lacks privilege** — EMP-032 (frontend engineer), same request | endpoint → `has_privilege` false, `eligible_with_approval` true → approval workflow → approver = Engineering Manager (EMP-007) via Neo4j | `approval_requests` row with correct approver; ticket `waiting_approval`; employee notified; visible in ops queue |
| 5 | **Slow laptop, safe self-resolution** — EMP-041: "My laptop is crawling." | endpoint → `run_device_health_check` + `check_disk_space` (96% full) → guidance → resolution | Resolved with no privileged action; findings auditable |
| 6 | **Ticket status query** — "What's the status of IT-1042?" | supervisor → ticketing path → `get_ticket_status` (Postgres) | Correct status + history summarized; no specialist needed |
| 7 | **Stale pending ticket auto-escalation** — status query on a ticket pending 4 days | `get_ticket_status` detects `pending_since` > 3 calendar days → escalation workflow → Neo4j target | `escalation_events` row (trigger=pending_age); ticket status → escalated; employee informed in same reply |
| 8 | **Ambiguous request** — "Nothing works this morning." | supervisor → `ask_employee` → need-more-info interrupt → employee: "Can't reach the VPN" → supervisor → network | Graph pauses/resumes via interrupt; answer merged into state; no budget consumed by waiting |
| 9 | **Loop guard** — adversarial FakeLLM ping-pongs network↔security with unchanged findings | signatures repeat → loop guard trips before `MAX_SUPERVISOR_CYCLES` | `LOOP_GUARD_TRIGGERED` event; escalation with findings preserved; friendly employee message; no crash |
| 10 | **Structured-output failure** — FakeLLM emits schema-invalid output 3× in supervisor | retry 1 → retry 2 → `AgentFailure` → escalation workflow | Exactly 2 retries (no third); `STRUCTURED_OUTPUT_*` events; graceful employee-facing message |

**Standing security scenario (tested alongside #2):** when the security
specialist recommends human intervention on a high-risk request, no path may
auto-resolve the session — asserted as an invariant test, not just a scenario.

---

## 8. Cross-session memory (Mem0) boundaries

- Retrieval: session start only, semantically filtered by the request; IDs +
  concise contents recorded on the agent run (dashboard-inspectable).
- Writing: at session completion / meaningful resolution via `policy.py`
  (never per-turn; never routine acknowledgements).
- Never authoritative for privileges, roles, managers, entitlements, ticket or
  approval state, security/account status, device assignment.
- Retrieved memories are injected as clearly-labeled *context, not fact*, and
  security-relevant claims must be re-verified via Neo4j/Postgres tools.

## 9. Conversation compaction

Context sent to LLMs = running summary + last `RECENT_MESSAGES_TO_RETAIN`
turns + structured state. Compaction triggers on estimated token count over
threshold; summarization is an LLM call with a fixed template. Postgres
`messages` remains the complete, uncompacted record.

---

## 10. Design amendments (adversarial review outcome — binding)

A three-lens adversarial review (LangGraph feasibility, contract consistency,
requirements coverage) produced 36 findings. The following amendments are part
of the design contract:

### 10.1 Graph mechanics
- **`recent_turns` is last-write-wins**, not `operator.add` — compaction must
  be able to replace the window. Transcript truth stays in Postgres.
- **Edges select, nodes mutate.** Counter increments, signatures, and
  loop-guard flags are written by nodes (supervisor returns
  `Command(goto=..., update=...)`); conditional-edge functions are pure reads.
- **Interrupt nodes are split**: `confirmation_prepare` (privilege check,
  persist confirmation row, emit event) → `confirmation_wait` (body is ONLY
  `interrupt()`); same for need-info (`ask_prepare` → `ask_wait`). Rule: no
  non-idempotent side effect may share a node with `interrupt()`.
- **Budgets are per employee turn**: `turn_index` increments on each ingested
  employee message; the ingest node resets `supervisor_cycle_count` and
  `handoff_count`; loop signatures include `turn_index`.
  `total_agent_step_count` is session-lifetime telemetry.
- **Resume dispatch rule** in the chat API: if the thread has a pending
  interrupt, incoming text is submitted as `Command(resume=text)`; otherwise
  as a new-message update. Per-thread `asyncio.Lock` serializes invokes; the
  voice webhook goes through the same dispatcher.
- **`GraphRecursionError` / any exception** from a graph invoke is caught in
  the API layer and converted to the same out-of-graph escalation path
  (ticket, escalation event, employee message) — never a 500 with no story.
  `recursion_limit` is set well above in-graph budgets so code guards win.
- **Windows/event loop**: `WindowsSelectorEventLoopPolicy` is pinned on win32
  before the loop starts (psycopg async + asyncpg both work under selector);
  `AsyncPostgresSaver.setup()` runs once at lifespan startup.
- **Single-worker deployment** is a stated constraint of the in-process event
  bus; the bus interface hides transport so LISTEN/NOTIFY can replace it.

### 10.2 Topology
- New deterministic **`ticket_status` workflow** (in `WorkflowName`): queries
  Postgres by ticket number or natural filters (requester + text/category);
  if `pending_since` exceeds `PENDING_ESCALATION_DAYS` it routes into the
  escalation workflow, else answers directly. Aging is checked at query time
  **and** by a lightweight startup/interval sweep (explicitly not an SLA engine).
- **Post-approval execution**: `POST /ops/approvals/{id}/decision` updates the
  request, emits `APPROVAL_DECIDED`, and on approval a deterministic executor
  runs the persisted `RequestedAction` (from `approval_requests.action_key/params`),
  writes `action_executions` + `ACTION_EXECUTED`, transitions the ticket, and
  notifies the employee (message row + My Requests). Rejection closes with reason.
- Ops mutation surface: approval decision endpoint + `HUMAN_INTERVENTION` endpoint.

### 10.3 Schema deltas (applied in §5 models)
- `approval_requests` += `action_key`, `params`, `risk_level`, `decided_by`.
- `agent_runs` += `result` (full structured output dump), `failure_type`,
  `failure_detail`, `recoverable`, `memories_retrieved`
  (`[{memory_id, content, score, included_in_context}]`), `memories_written`.
- `support_sessions` += `original_request`, `category`, `intent`,
  `risk_level`, `autonomy_level`; status enum += `waiting_approval`.
- `tickets.originating_agent` (indexed) backs the ops filter.
- `TerminalStatus` drops `abandoned` (no path produces it).
- Events += `USER_DECLINED`, `INFO_REQUESTED`, `EMPLOYEE_REPLIED`,
  `MEMORY_RETRIEVED`, `MEMORY_WRITTEN`; escalation trigger += `out_of_scope`.
- `messages.source` uses the same `web|voice` literal as `channel`.
- State field renamed `privilege_check_result`.

### 10.4 Structured-output seam
`invoke_structured(schema, messages)` is the provider abstraction, not the
chat model: the real path uses `with_structured_output(schema, include_raw=True)`
and builds retry messages from `raw` + `parsing_error`; the fake path yields
scripted raw dicts validated with `schema.model_validate`, so retry-1/retry-2/
AgentFailure are exactly testable without an API key.

### 10.5 Infrastructure degradation (§6.7)
- Neo4j down ⇒ privilege checks **fail closed** (`has_privilege=False`,
  eligible=False, error surfaced) and the case routes to escalation with a
  friendly message — access is never assumed.
- Postgres down ⇒ the request is refused before any privileged action (no
  unaudited execution; persist-before-broadcast holds).
- Tool timeout/failure ⇒ `ToolResult(status=failed)`; the specialist decides
  with remaining evidence or returns `unable_to_resolve`.

### 10.6 Frontend contract additions
- Employee chat streams over a per-session SSE channel; internal events map to
  friendly progress strings server-side (an explicit event→copy table, e.g.
  `AGENT_STARTED(identity)` → "Checking your account…"). Components:
  ChatStream, ProgressUpdate, ConfirmationCard, ApprovalCard, TicketCard,
  MyRequests, TicketDetail. Design tokens: Inter, slate base, indigo primary,
  green/amber/red/violet semantics, dark mode, `prefers-reduced-motion`.
- Command center: metric definitions are SQL over §5 tables; session timeline
  is derived from `audit_events` + `agent_runs` + `tool_calls`; ticket/agent-run
  filters are enumerated query params; intervention queue tabs = approvals,
  escalated, automation-exhausted (budget/loop/structured-output triggers),
  out-of-scope. Rule: **no non-functional placeholder controls ship**.
- Scenario 11 (tested): declined confirmation ⇒ `confirmed=false` persisted,
  zero `action_executions` rows, `USER_DECLINED` event, graceful close.
