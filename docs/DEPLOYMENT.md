# Deploying GA-VoiceAI

This monorepo deploys the Next.js frontend to Vercel and the FastAPI backend to Render. Deploy the backend first so its public URL is available to the frontend.

## 1. Render — FastAPI

Create a **Web Service** from this repository.

| Setting | Value |
| --- | --- |
| Root directory | `backend` |
| Runtime | Python 3.11+ |
| Build command | `pip install --upgrade pip && pip install ".[mem0]"` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health check path | `/health` |
| Migration command | `alembic upgrade head` |

Use Render’s **Pre-deploy Command** for `alembic upgrade head` when the selected plan supports it. Otherwise, run that command once in the Render Shell before first traffic and on each migration release. Migrations are never run implicitly at service startup.

Set these environment variables on Render. Do not add them to Git.

| Variable | Value / purpose |
| --- | --- |
| `APP_ENV` | `production` |
| `DATABASE_URL` | Hosted PostgreSQL URL supplied by Render or another provider. Standard `postgresql://...` URLs are accepted. |
| `NEO4J_URI` | Aura URI, for example `neo4j+s://…databases.neo4j.io` |
| `NEO4J_USERNAME` | Aura database user, normally `neo4j` |
| `NEO4J_PASSWORD` | Aura password |
| `IT_NEO4J_DATABASE` | Usually `neo4j` |
| `OPENAI_API_KEY` | OpenAI server API key |
| `IT_LLM_PROVIDER` | `openai` |
| `MEM0_API_KEY` | Mem0 Cloud key |
| `IT_MEMORY_BACKEND` | `mem0` |
| `ELEVENLABS_API_KEY` | ElevenLabs server key |
| `ELEVENLABS_AGENT_ID` | Private Conversational AI agent ID |
| `IT_ELEVENLABS_CUSTOM_LLM_KEY` | Optional bearer key for the Custom LLM → LangGraph adapter |
| `IT_SESSION_SECRET` | Long random signing secret; keep stable across deploys |
| `IT_ADMIN_USERNAME` / `IT_ADMIN_PASSWORD` | Administrator demo login credentials |
| `CORS_ORIGINS` | Exact Vercel origin, for example `https://your-project.vercel.app` |

`CORS_ORIGINS` accepts one origin, a comma-separated list, or a JSON array. Do not use `*` in production because authenticated browser requests require credentials.

After the service deploys, verify:

```bash
curl https://YOUR-RENDER-SERVICE.onrender.com/health
```

Expected response: `{"ok": true, "environment": "production"}`.

## 2. PostgreSQL and Neo4j seed data

Run these commands from the Render Shell (root directory is already `backend`):

```bash
alembic upgrade head
python -m app.seeds.seed_org
python -m app.seeds.seed_demo  # optional demo tickets, including a stale pending ticket
```

`seed_org` uses Neo4j `MERGE` statements and is safe to run repeatedly. It does not run automatically during service startup.

## 3. Vercel — Next.js

Import the same GitHub repository as a Vercel project.

| Setting | Value |
| --- | --- |
| Root directory | `frontend` |
| Framework preset | Next.js |
| Install command | `npm ci` (Vercel also detects the lockfile) |
| Build command | `npm run build` |
| Output directory | Leave unset |

Set this Production environment variable before deployment:

```text
NEXT_PUBLIC_API_URL=https://YOUR-RENDER-SERVICE.onrender.com
```

This value is intentionally public: it is only the backend origin. Never put API keys, database URLs, or credentials in a `NEXT_PUBLIC_*` variable. Vercel inlines public variables at build time, so redeploy after changing the URL.

For preview deployments, use a matching preview backend or add that exact preview URL to `CORS_ORIGINS`; do not use a wildcard origin. The browser sends authenticated requests directly to Render with `credentials: include`, and the production session cookie is `Secure; SameSite=None`.

## 4. ElevenLabs

The employee web app obtains a short-lived, authenticated signed URL from:

```text
GET https://YOUR-RENDER-SERVICE.onrender.com/api/voice/signed-url
```

`GET /api/voice/token` is an equivalent deployment-friendly alias. Neither returns the permanent ElevenLabs API key.

For the private ElevenLabs Conversational AI agent, configure a webhook tool:

| Setting | Value |
| --- | --- |
| Tool name | `it_support` |
| URL | `https://YOUR-RENDER-SERVICE.onrender.com/api/voice/agent-tool` |
| Inputs | `voice_bridge_token`, `message`, optional `session_id` |
| Dynamic variables | `employee_id`, `voice_bridge_token` |

The signed-agent webhook and `POST /v1/chat/completions` Custom LLM adapter
both use the shared dispatcher. The Custom LLM adapter accepts a signed
`voice_bridge_token` plus an optional GA-VoiceAI `session_id` in
`elevenlabs_extra_body`; it reads only the latest `user` message and resumes
the persisted session rather than trusting ElevenLabs message history.

## 5. Deployment smoke checks

Run these after configuration; ordinary unit tests do not call external production services.

```bash
# Render liveness
curl https://YOUR-RENDER-SERVICE.onrender.com/health

# Browser app → Render API
# Sign in at the Vercel URL, then verify the employee chat starts a request.

# ElevenLabs Custom LLM → LangGraph adapter
curl -N https://YOUR-RENDER-SERVICE.onrender.com/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $IT_ELEVENLABS_CUSTOM_LLM_KEY" \
  -d '{"model":"ga-voiceai-support","stream":true,"voice_bridge_token":"<signed-bridge-token>","messages":[{"role":"user","content":"My VPN keeps disconnecting"}]}'
```

The final command must produce an SSE `data:` frame followed by `data: [DONE]`. Confirm PostgreSQL through the successful migration, Neo4j through `seed_org`, Mem0 through a completed support session with `IT_MEMORY_BACKEND=mem0`, and ElevenLabs through a signed-URL voice session.
