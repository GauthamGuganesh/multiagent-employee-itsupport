# GA-VoiceAI — Employee IT Support Desk

<p align="center">
  A production-shaped, multi-agent IT support platform for a fictional 60-person company —
  built to show how autonomous agents can be <em>safe, auditable, and genuinely useful</em>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Orchestration-LangGraph-4f46e5?style=flat-square" alt="LangGraph" />
  <img src="https://img.shields.io/badge/API-FastAPI-009688?style=flat-square" alt="FastAPI" />
  <img src="https://img.shields.io/badge/UI-Next.js%2016-111827?style=flat-square" alt="Next.js" />
  <img src="https://img.shields.io/badge/Contracts-Pydantic-e92063?style=flat-square" alt="Pydantic" />
  <img src="https://img.shields.io/badge/Operational%20truth-PostgreSQL-336791?style=flat-square" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Org%20graph-Neo4j-4581c3?style=flat-square" alt="Neo4j" />
  <img src="https://img.shields.io/badge/Memory-Mem0-7c3aed?style=flat-square" alt="Mem0" />
  <img src="https://img.shields.io/badge/Voice-ElevenLabs-000000?style=flat-square" alt="ElevenLabs" />
</p>

<p align="center"><strong>Live demo:</strong> <a href="https://multiagent-employee-itsupport.vercel.app/">multiagent-employee-itsupport.vercel.app</a> · <em>frontend on Vercel, backend on Render</em></p>

![GA-VoiceAI system architecture](docs/assets/ga-voiceai-architecture.svg)

---

## Contents

- [What it is](#what-it-is)
- [Why it's interesting](#why-its-interesting)
- [Architecture at a glance](#architecture-at-a-glance)
- [How one request flows](#how-one-request-flows)
- [The agents, workflows, and guards](#the-agents-workflows-and-guards)
- [Data & trust boundaries](#data--trust-boundaries)
- [Tech stack](#tech-stack)
- [Repository map](#repository-map)
- [Run it locally](#run-it-locally)
- [Explore it — demo scenarios](#explore-it--demo-scenarios)
- [Testing](#testing)
- [Deployment](#deployment)
- [Documentation index](#documentation-index)

---

## What it is

GA-VoiceAI gives employees **one place** to get help with account access, devices, VPN/network, software installs, security concerns, and existing tickets — by text chat or an authenticated voice conversation. Behind the scenes a **supervisor agent** triages the request, routes it to a domain **specialist** that investigates with real (mocked) tools, and only ever performs a privileged action after checking entitlements and getting the employee's explicit confirmation. When automation can't safely finish, it hands off to the right human — warmly, and without leaking internal jargon.

There are two front doors:

| Experience | Route | Who it's for |
| --- | --- | --- |
| **Employee Support** | `/support` | Anyone with an issue — conversational chat, progress updates, confirmation cards, "My Requests," optional voice |
| **Operations Command Center** | `/ops` | IT staff — live session timelines, agent handoffs, typed tool calls, approvals, escalations, the audit trail, ticket filters, and an interactive org graph |

The Command Center deliberately surfaces **evidence and decisions** — findings, tool inputs/outputs, guard activations, escalation reasons — never hidden chain-of-thought.

## Why it's interesting

This isn't a "look, the LLM called a tool" demo. The interesting parts are the **rails** that make multi-agent autonomy trustworthy:

- **Bounded execution.** Hard, code-enforced limits (not prompt requests) stop runaway loops: 8 supervisor cycles, 5 specialist tool steps, 4 handoffs, 2 structured-output retries, plus repeated-question and loop-signature guards.
- **Structured output everywhere.** Every LLM node returns a validated Pydantic model; invalid output is retried a bounded number of times, then fails safe.
- **Code-owned invariants.** A specialist's handoff is honored in code (it can't be silently downgraded to an escalation); a security-flagged case can never be auto-resolved; privilege checks fail *closed* when the directory is unavailable.
- **Judgment, not scripts.** Specialists choose tools by matching what they need to know to each tool's description — tools are capabilities, not steps wired to a scenario.
- **Auditable by construction.** Every event is persisted to PostgreSQL *before* it's broadcast over SSE, so the timeline is a source of truth, not a UI convenience.
- **Graceful, human closings.** The agent asks "did that fix it, and anything else?" and closes only when the employee is done; when it must escalate, the message is empathetic and jargon-free.

## Architecture at a glance

```mermaid
flowchart LR
    E[Employee<br/>web chat or ElevenLabs voice] --> API[FastAPI<br/>session dispatcher]
    API --> S[LangGraph Supervisor<br/>one incremental decision]
    S --> I[Identity]
    S --> D[Endpoint]
    S --> N[Network]
    S --> C[Security]
    I --> S
    D --> S
    N --> S
    C --> S
    S --> W[Deterministic workflows<br/>confirm · approve · escalate · resolve]
    W --> P[(PostgreSQL<br/>tickets · sessions · audit)]
    W --> G[(Neo4j<br/>org · privileges · ownership)]
    API -. selective context .-> M[Mem0<br/>non-authoritative memory]
    P --> O[Operations Command Center<br/>SSE live updates]
```

> **The design principle:**
> Supervisor orchestrates reasoning · Specialists investigate · Tools interact with systems · Neo4j resolves relationships · PostgreSQL owns operational truth · Humans are the safe final fallback.

## How one request flows

A single employee message travels through the graph like this:

1. **Dispatch** (`api/dispatcher.py`) — resolves the authenticated employee, persists the message, and either starts a fresh LangGraph run or resumes a paused one (confirmation/approval/question interrupts). Any unexpected error becomes a graceful, ticketed escalation — never a bare 500.
2. **Ingest** (`graph/workflows/common.py`) — appends the turn, resets per-turn budgets, retrieves cross-session memory (first turn), and compacts the conversation window if it's long.
3. **Supervise** (`graph/supervisor.py`) — makes **one** decision: route to a specialist, ask the employee a question, run a workflow, or close. All guards and invariants are applied here in code and every override is written to the audit trail.
4. **Investigate** (`graph/specialists/runner.py`) — a generic bounded *Reason → Act → Observe → Decide* loop runs the chosen specialist, which calls typed tools and returns a validated `SpecialistResult` (resolve / need info / hand off / needs approval / escalate / can't resolve).
5. **Act deterministically** (`graph/workflows/*`) — confirmation (with a Neo4j entitlement check), approval routing, privileged execution, resolution verification, or escalation to the right human. These are plain code, not LLM control flow.
6. **Persist & stream** (`events/`) — every step is written to `audit_events` and then published over SSE to the Command Center; the employee sees friendly progress copy with no internal terminology.

## The agents, workflows, and guards

**Supervisor** — the only router. It never emits a multi-step plan; it decides the next single move from current state, one specialist at a time.

**Specialists** (`graph/specialists/specs.py`) — each has a mission, a tool allow-list (enforced in code), and a strict domain boundary. They never call each other directly:

| Specialist | Investigates | Example tools |
| --- | --- | --- |
| **Identity** | sign-in, lockouts, passwords, MFA, access requests | `get_account_status`, `get_recent_auth_events`, `unlock_account`* |
| **Endpoint** | device health, disk, software installs, managed services, hardware | `run_device_health_check`, `check_disk_space`, `install_approved_software`* |
| **Network** | VPN, connectivity, DNS, proxy | `check_vpn_status`, `inspect_recent_vpn_session`, `run_connectivity_diagnostics` |
| **Security** | suspected compromise, suspicious auth, phishing, containment | `get_recent_security_events`, `quarantine_device`*, `notify_security_team` |

<sub>* privileged — recommended via a typed `RequestedAction`, never called directly; executed only after entitlement check + confirmation/approval.</sub>

**Deterministic workflows** (`graph/workflows/`) — `confirmation`, `approval`, `escalation`, `resolution`, `resolution_verification` (the "did that fix it, anything else?" wrap-up), `need_info`, and `ticket_status`. Business procedure lives here, not in the model.

**Guards** (`graph/guards.py`) — pure functions the supervisor applies as budgets and safety checks: cycle/handoff budgets, loop-signature detection, repeated-question detection (which routes to investigation rather than dead-ending), and the handoff-routing and security invariants.

## Data & trust boundaries

Three stores, three jobs — and the boundaries are enforced, not conventional:

- **PostgreSQL** — *operational source of truth.* Sessions, messages, tickets + history, agent runs, tool calls, confirmations, approvals, escalations, failures, and the full audit-event log. Async SQLAlchemy 2.0 + Alembic.
- **Neo4j** — *authoritative org & privilege graph.* Employees, teams, roles, privileges, system ownership, and escalation chains. Accessed only through **parameterized Cypher** (no LLM-generated queries); privilege checks **fail closed**.
- **Mem0** — *non-authoritative context* across sessions. Useful for "this keeps happening," but anything privilege-, ownership-, ticket-, or security-relevant is always re-verified from the source systems above.

## Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Orchestration | **LangGraph** (Python) | Supervisor pattern with `Command` routing + `interrupt()` for human-in-the-loop across HTTP turns |
| Reasoning | **OpenAI** (`gpt-4o-mini`, configurable) | Native Pydantic structured output; swappable providers (`openai` / `scripted` / `fake`) |
| API | **FastAPI** + SSE (`sse-starlette`) | Async endpoints and one-way live event streaming to the Command Center |
| Contracts | **Pydantic v2** | Every agent/tool/workflow boundary is a validated model |
| Operational store | **PostgreSQL 16** + SQLAlchemy 2.0 (async) + Alembic | Audit source of truth with migrations from day one |
| Org/privilege store | **Neo4j** (hosted, e.g. Aura) | Authoritative relationship queries via parameterized Cypher |
| Cross-session memory | **Mem0** (with a local JSON fallback) | Real memory when keyed; runnable offline otherwise |
| Frontend | **Next.js 16** (App Router) · React 19 · Tailwind CSS v4 · Framer Motion | One deploy, two experiences (`/support`, `/ops`); dark mode; reduced-motion aware |
| Voice | **ElevenLabs Agents** (`@elevenlabs/react`) | First-class voice that degrades gracefully; a signed bridge token reaches the same dispatcher as text |
| Auth | Demo employee-ID/password + signed cookie | Fictional org; deterministic, documented non-production credentials |

**The LLM provider is swappable** via `IT_LLM_PROVIDER`:
- `openai` — real reasoning (needs `OPENAI_API_KEY`).
- `scripted` — a deterministic, offline demo provider: every graph node, guard, tool, and persistence path is real; only the model's judgment is canned. Great for running with no API key.
- `fake` — a queue-driven provider used by the test suite.

## Repository map

```
agentic-employee-it-support/
├── docker-compose.yml         # local PostgreSQL 16 (Neo4j is hosted, not in Docker)
├── README.md
├── docs/                      # design, deployment, voice setup, interactive guide
│   ├── DESIGN.md              #   contracts, graph topology, data boundaries, scenarios
│   ├── DEPLOYMENT.md          #   Render + Vercel + Neo4j + Postgres + ElevenLabs
│   ├── VOICE_SETUP.md         #   signed bridge flow + secure webhook config
│   └── implementation-guide.html
│
├── backend/                   # FastAPI + LangGraph service (Python 3.11+)
│   ├── app/
│   │   ├── main.py            # app factory + lifespan wiring
│   │   ├── config.py          # Settings + ALL execution-limit constants
│   │   ├── api/               # HTTP layer
│   │   │   ├── dispatcher.py  #   the one entry point: resume protocol, fail-safe
│   │   │   ├── routes_chat.py #   start/continue session, confirm
│   │   │   ├── routes_ops.py  #   command-center queries (metrics, timelines, filters)
│   │   │   ├── routes_stream.py  # SSE feeds (employee progress + ops firehose)
│   │   │   ├── routes_voice.py   # ElevenLabs signed URL + webhook/custom-LLM bridge
│   │   │   └── friendly.py    #   event → employee-facing copy (no internal jargon)
│   │   ├── graph/             # the multi-agent graph
│   │   │   ├── build.py       #   node/edge assembly + checkpointer
│   │   │   ├── supervisor.py  #   one incremental decision + guards/invariants
│   │   │   ├── guards.py      #   budgets, loop detection, handoff/security invariants
│   │   │   ├── structured.py  #   structured-output invoke + bounded retry
│   │   │   ├── state.py       #   strongly-typed SupportState
│   │   │   ├── specialists/   #   runner (bounded loop), specs, prompts
│   │   │   └── workflows/     #   confirm · approve · escalate · resolve · need_info · ticket_status
│   │   ├── contracts/         # Pydantic output contracts (supervisor, specialist, common, enums)
│   │   ├── tools/             # typed mock integrations + registry (identity/endpoint/network/security/ticketing)
│   │   ├── org/               # Neo4j client, parameterized queries, org service, keys
│   │   ├── db/                # SQLAlchemy models, repositories, ops queries
│   │   ├── memory/            # Mem0 service + policy (+ local fallback)
│   │   ├── conversation/      # window compaction
│   │   ├── events/            # SSE bus + persist-then-broadcast recorder + event types
│   │   ├── llm/               # provider protocol: openai / scripted / fake
│   │   └── seeds/             # seed_org (Neo4j, idempotent) + seed_demo (Postgres tickets)
│   ├── alembic/               # migrations
│   └── tests/                 # unit/ + integration/ + golden/ (see Testing)
│
└── frontend/                  # Next.js 16 App Router (TypeScript, Tailwind v4)
    ├── app/
    │   ├── support/           # employee chat
    │   ├── requests/          # "My Requests" + ticket detail
    │   ├── login/  admin/  help/
    │   └── ops/               # command center: sessions, tickets, approvals,
    │                          #   escalations, audit, org graph
    ├── components/            # shared UI, chat, voice control, shell, theme
    └── lib/                   # api client, SSE hooks, types, formatting
```

## Run it locally

### Prerequisites

- **Python 3.11+**, **Node.js 20.9+** (required by Next.js 16), **Docker** (for local PostgreSQL)
- A **hosted Neo4j** instance (e.g. [Neo4j Aura](https://neo4j.com/cloud/aura/) free tier) — Neo4j is intentionally *not* in Docker
- Optional: an **OpenAI API key** for real reasoning (or run in `scripted` mode with none), and **Mem0**/**ElevenLabs** keys for those features

### 1. Configure

```bash
cp .env.example .env
```

Edit `.env`. Minimal offline setup (no API keys) uses the deterministic provider:

```bash
IT_LLM_PROVIDER=scripted
IT_POSTGRES_DSN=postgresql+asyncpg://itsupport:itsupport@localhost:5433/itsupport
IT_NEO4J_URI=neo4j+s://<your-instance>.databases.neo4j.io
IT_NEO4J_USER=<user>
IT_NEO4J_PASSWORD=<password>
IT_MEMORY_BACKEND=local
IT_SESSION_SECRET=dev-only-change-me
```

For real reasoning, set `IT_LLM_PROVIDER=openai` and add `OPENAI_API_KEY`.

### 2. Backend (PostgreSQL + FastAPI)

```bash
docker compose up -d                 # starts PostgreSQL on localhost:5433
cd backend
python -m pip install -e ".[dev]"
python -m alembic upgrade head       # create the schema
python -m app.seeds.seed_org         # seed the 60-person Neo4j org graph (idempotent)
python -m app.seeds.seed_demo        # optional: demo tickets (incl. a stale one)
python run.py                        # FastAPI on http://localhost:8000
```

### 3. Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev                          # http://localhost:3000
```

Leave `NEXT_PUBLIC_API_URL` **unset** locally — the browser calls relative `/api/*` and Next.js rewrites them to the backend (same-origin, no CORS). Open **http://localhost:3000**.

| Service | URL |
| --- | --- |
| Employee app | http://localhost:3000/support |
| Command Center | http://localhost:3000/ops |
| Backend API / health | http://localhost:8000/api/health |

## Explore it — demo scenarios

Sign in with any seeded employee: **ID `EMP-0NN`, password `gavoiceai-0NN`** (e.g. `EMP-032` / `gavoiceai-032`). The **Help me** link lists roles and privilege levels. Administrator (Command Center): `admin` / `ga-voiceai-admin` (configurable in `.env`).

Three employees have pre-seeded situations that exercise the interesting paths:

| Sign in as | Try saying | What it demonstrates |
| --- | --- | --- |
| **EMP-034** | "I'm locked out of my account." | Identity investigates → proposes an unlock → **confirmation card** → executes → verifies with you |
| **EMP-014** | "My VPN keeps disconnecting." | Network runs diagnostics, spots an unrecognized session → **hands off to Security** → escalates to the security team |
| **EMP-041** | "My laptop has been really slow." | Endpoint finds the disk 96% full → proposes a fix → asks you to confirm it worked (and if you need anything else) |

Also worth trying: a **multi-intent** message ("I'm locked out, plus my VPN drops and I need Docker installed") — the primary issue is handled in the conversation and the rest are opened as tracked, categorized tickets. Watch any of it live in the **Command Center** at `/ops`.

## Testing

```bash
cd backend
python -m pytest -q         # 9 unit + 15 integration suites (contracts, guards,
                            # routing, handoffs, workflows, degradation, golden convos)
python -m ruff check app    # lint (line-length 110)

cd ../frontend
npx tsc --noEmit            # type-check
npm run build               # production build
```

Tests run against SQLite + the `fake` provider and an org stub, so they need no external services. `integration/` exercises complete graph paths (confirmation, approval, cross-agent handoff, loop guards, structured-output exhaustion, ticket aging, voice bridge); `golden/` pins end-to-end conversation quality.

## Deployment

The reference deployment is **Vercel** (frontend) + **Render** (backend) + hosted **Neo4j** + managed **PostgreSQL**. Full steps are in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**. The essentials:

- **Frontend (Vercel):** set `NEXT_PUBLIC_API_URL` to your public backend origin, then **redeploy** (Vercel inlines `NEXT_PUBLIC_*` at build time). The browser then calls the backend directly with credentials.
- **Backend (Render):** set `APP_ENV=production` (makes the session cookie `Secure; SameSite=None` for cross-site auth), `CORS_ORIGINS=https://<your-vercel-domain>`, plus `OPENAI_API_KEY`, `IT_POSTGRES_DSN`, `IT_NEO4J_*`, `MEM0_API_KEY`, and a strong `IT_SESSION_SECRET`. Run `alembic upgrade head` + `seed_org` against the production stores.

## Documentation index

- **[docs/DESIGN.md](docs/DESIGN.md)** — contracts, graph topology, data boundaries, execution guards, and acceptance scenarios
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** — Render, Vercel, hosted Neo4j, Postgres, and ElevenLabs configuration
- **[docs/VOICE_SETUP.md](docs/VOICE_SETUP.md)** — the ElevenLabs signed-bridge flow and secure webhook setup
- **[docs/implementation-guide.html](docs/implementation-guide.html)** — a visual, product-to-code walkthrough
- **[AGENTS.md](AGENTS.md)** — project layout, conventions, and commands for contributors

---

<sub>GA-VoiceAI is a deliberately realistic portfolio demo for a **fictional** organization. It uses typed **mock** integrations for safe local exploration — no real employee data, accounts, or systems are touched.</sub>
