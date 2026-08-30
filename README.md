# GA-VoiceAI IT Support Desk

An employee IT support application demonstrating a LangGraph Supervisor with
identity, endpoint, network, and security specialists. PostgreSQL is the
operational/audit system of record; hosted Neo4j supplies organization,
privilege, approval, and escalation traversal.

## Run locally

```powershell
docker compose up -d
cd backend
python -m alembic upgrade head
python -m app.seeds.seed_org
python -m app.seeds.seed_demo
python run.py
```

In another terminal:

```powershell
cd frontend
npm run dev
```

Open `http://localhost:3000`, sign in with a seeded employee such as
`EMP-032` using the demo password `gavoiceai-032`, and use the employee chat
or Operations Command Center. The landing page’s **Help me** link lists
sample accounts across the available privilege levels.

## Configuration

Copy `.env.example` to `.env`. Use hosted Neo4j connection values from the
provider portal; Neo4j is not part of Docker Compose. See
[`docs/VOICE_SETUP.md`](docs/VOICE_SETUP.md) for the optional ElevenLabs voice
setup and [`docs/implementation-guide.html`](docs/implementation-guide.html)
for an interactive architecture walkthrough.

## Validation

```powershell
cd backend; python -m pytest -q
cd frontend; npm run lint; npm run build
```
