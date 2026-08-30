# Repository Guidelines

## Project Structure & Module Organization

- `backend/app/` contains the FastAPI service. LangGraph orchestration lives in `graph/`, Pydantic contracts in `contracts/`, deterministic workflows in `graph/workflows/`, and typed mock integrations in `tools/`.
- `backend/app/db/` owns PostgreSQL models and repositories; migrations are under `backend/alembic/`.
- `backend/app/org/` and `backend/app/seeds/` contain parameterized Neo4j access and repeatable fictional-organization seed data.
- `backend/tests/unit/` tests contracts and isolated policies; `backend/tests/integration/` exercises complete graph paths.
- `frontend/app/` is the Next.js App Router UI. Shared components and API/SSE helpers live in `frontend/components/` and `frontend/lib/`.
- `docs/` contains the locked requirements and architecture. Read `docs/DESIGN.md` before changing workflow topology.

## Build, Test, and Development Commands

Run infrastructure from the repository root:

```powershell
docker compose up -d
```

Backend commands run from `backend/`:

```powershell
python -m pip install -e ".[dev]"
python -m alembic upgrade head
pytest -q
python run.py
```

Frontend commands run from `frontend/`:

```powershell
npm install
npm run dev
npm run lint
npm run build
```

## Coding Style & Naming Conventions

Use four-space indentation and type annotations in Python. Use Ruff conventions (`line-length = 110`) and Pydantic models for agent, tool, and workflow boundaries. Modules and functions use `snake_case`; classes use `PascalCase`.

Use TypeScript, two-space indentation, and functional React components. Component names use `PascalCase`; hooks begin with `use`. Follow the additional Next.js rules in `frontend/AGENTS.md`.

Preserve the supervisor architecture: specialists never call one another, LLM nodes return validated structured output, and deterministic business procedures remain workflow nodes.

## Testing Guidelines

Pytest is the backend test framework. Name files `test_*.py` and tests `test_<behavior>`. Add unit tests for contracts/guards and integration tests for routing or persisted workflows. Always test safe failure paths for privileged actions, retries, and loop limits. Run lint and a production frontend build before submitting UI changes.

## Commit & Pull Request Guidelines

Git history is unavailable in this workspace, so no established convention can be verified. Use short imperative commits such as `Add approval audit filtering`. Keep commits scoped. Pull requests should explain behavior changes, list validation commands, link relevant issues, note migration or configuration changes, and include screenshots for UI work.

## Security & Configuration

Copy `.env.example` to `.env`; never commit credentials. PostgreSQL is operational truth, Neo4j is authoritative for organization and privileges, and Mem0 is non-authoritative context only. Never bypass confirmation, approval, audit persistence, or tool authorization gates.
