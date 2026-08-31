# GA-VoiceAI System Design & Code Navigation

This guide is the shortest path to understanding the system. Read it before
following individual agent or UI files; the application is intentionally split
between reasoning, deterministic process, and authoritative data stores.

## The Mental Model

```text
Employee web chat / voice
        │
        ▼
FastAPI routes + authenticated session
        │
        ▼
LangGraph Supervisor ──► specialist investigation ──► typed tools
        │                         │
        │                         └── structured result only
        ▼
Deterministic workflow: confirmation / approval / escalation / resolution
        │
        ├── PostgreSQL: tickets, sessions, audit, approvals, events
        ├── Neo4j: people, privileges, owners, approvers, escalation chain
        └── Mem0/local memory: non-authoritative cross-session context
```

The Supervisor decides the next small step; it does not make a full plan up
front. Specialists investigate a single domain and return a Pydantic-validated
result to the shared LangGraph state. Specialists never call one another.

## Where to Start in the Code

| Goal | Start here | Then follow |
| --- | --- | --- |
| Understand an employee request | `backend/app/api/routes_chat.py` | `api/dispatcher.py` → `graph/build.py` → `graph/supervisor.py` |
| Understand a specialist | `backend/app/graph/specialists/` | `runner.py`, then the domain module and `tools/` |
| Understand safety and limits | `backend/app/config.py` | `graph/guards.py`, `contracts/`, `tools/registry.py` |
| Understand a ticket or audit event | `backend/app/db/models.py` | `db/repos.py`, `events/recorder.py`, `events/types.py` |
| Understand organization lookups | `backend/app/org/service.py` | `org/queries.py`, `org/client.py`, `seeds/seed_org.py` |
| Understand the employee UI | `frontend/app/support/page.tsx` | `components/shell.tsx`, `lib/api.ts`, `lib/sse.ts` |
| Understand the Command Center | `frontend/app/ops/page.tsx` | `components/ops-shell.tsx`, `backend/app/api/routes_ops.py` |
| Understand voice | `frontend/components/voice-control.tsx` | `backend/app/api/routes_voice.py`, `docs/VOICE_SETUP.md` |

## Request Lifecycle

1. The employee starts a web session through `routes_chat.py`. The authenticated
   employee ID is the authority for that session, and the request is persisted.
2. `dispatcher.py` invokes the compiled LangGraph. The Supervisor returns a
   `SupervisorDecision`; validation and routing guards run before the next node.
3. A domain specialist performs bounded Reason → Act → Observe → Decide cycles.
   Each tool call is typed, recorded, and capped by `MAX_SPECIALIST_TOOL_STEPS`.
4. The specialist returns one `SpecialistResult` outcome. The Supervisor either
   selects another specialist, asks the employee for information, or begins a
   deterministic workflow. A specialist may recommend a resolution but cannot
   close the support session.
5. Workflows in `graph/workflows/` handle confirmation, approval, escalation,
   resolution verification, resolution, and ticket aging. Proposed fixes pause
   at a LangGraph interrupt; the same thread resumes with the employee's test
   result, and the Supervisor decides whether to continue or close.
6. PostgreSQL records the session, messages, agent runs, tool calls, ticket
   changes, confirmations, and audit events. SSE broadcasts the already-persisted
   event to the UI.

## Data Ownership Rules

PostgreSQL is the operational system of record. If the question is “what
happened?”, “who owns this ticket?”, or “what is the current status?”, begin
with `backend/app/db/`.

Neo4j is authoritative only for organizational traversal: employee context,
privileges, managers, system owners, approvers, support teams, and escalation
targets. Use `org/service.py` functions; do not write ad hoc text-to-Cypher or
move tickets into Neo4j.

Memory is useful context, not authority. `backend/app/memory/` can recall a
recurring VPN pattern or an employee preference, but never grants a privilege or
changes ticket/approval/security state.

## UI and Access Boundaries

`/` is employee sign-in, `/support` is employee chat, and `/requests` shows an
employee's own tickets. `/admin/login` creates a separate administrator session
and opens `/ops`. Operations API routes and the operations SSE stream require
that administrator session; employee sessions cannot read the Command Center.

The frontend is a thin client. It shows friendly progress, confirmations,
approvals, tickets, and persisted audit evidence, but never exposes prompt
content, LangGraph internals, or hidden reasoning.

## Voice Boundary

Voice is a transport layer over the same support dispatcher; ElevenLabs never
becomes the authority for a person, a privilege, or an action. The sequence is:

```text
1. Authenticated employee presses Talk in the web UI.
2. voice-control.tsx requests GET /api/voice/signed-url.
3. routes_voice.py reads the signed employee web cookie and creates a
   short-lived, signed voice_bridge_token for that employee.
4. The browser starts the ElevenLabs conversation with that token as a dynamic
   variable. The ElevenLabs API key never reaches the browser.
5. The ElevenLabs it_support webhook sends {voice_bridge_token, message,
   session_id?} to POST /api/voice/agent-tool.
6. FastAPI validates the bridge token, derives the employee ID, and calls the
   same dispatcher.start_session or dispatcher.continue_session used by chat.
7. The response text and returned session ID go back to ElevenLabs for speech.
```

This means voice messages, agent runs, tool calls, confirmations, tickets, and
audit events are persisted in the same PostgreSQL tables as web chat. The
frontend can still use SSE to show persisted progress for a known session.

For a multi-turn voice conversation, ElevenLabs must retain the `session_id`
returned by the webhook and send it back on later tool calls. That is how voice
turns continue one support session instead of creating a new one. Voice and
text share the same dispatcher and persistence model; they do not automatically
merge into one session unless the same session ID is supplied.

The exact agent configuration is in `docs/VOICE_SETUP.md`: the webhook must
accept `voice_bridge_token`, `message`, and optional `session_id`, then retain
the returned `session_id` in its conversation context. If that field is not
passed back, identity is still safe, but every voice tool invocation becomes a
new support session. Voice confirmation proves intent only; the authenticated
web session remains the identity check.

## Hosted Mem0 Memory

Set `IT_MEMORY_BACKEND=mem0` and `MEM0_API_KEY` in `.env` to use the hosted
Mem0 Platform. `memory/service.py` scopes every retrieval and write to the
employee ID. Memory writes happen only at useful terminal checkpoints and both
retrieval and write events are recorded in the audit timeline. If Mem0 is
unavailable or its key is missing, the memory layer disables itself safely;
ticketing, privilege checks, and support workflows continue normally.

## Development Checklist

1. Read `docs/DESIGN.md` before changing graph topology.
2. Start Postgres with `docker compose up -d`; Neo4j is hosted and configured in
   `.env`.
3. Run `python run.py` from `backend/`, then `npm run dev` from `frontend/`.
4. Add Pydantic contracts and tests before changing agent behavior.
5. Run `pytest -q`, `npm run lint`, and `npm run build` before handing work off.

When debugging, begin with the persisted audit timeline or the Command Center,
then trace backwards through the route, dispatcher, graph node, and tool. That
keeps the investigation grounded in observable evidence rather than model text.
