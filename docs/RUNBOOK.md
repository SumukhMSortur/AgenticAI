# Development Runbook (Windows PowerShell)

Docker Desktop with the WSL 2 backend is the supported local runtime for
PostgreSQL 16 and Redis 7. Start Docker Desktop and confirm its engine is
available before running service-backed checks:

```powershell
docker --version
docker compose version
docker info
```

## Local environment

Copy the example once, then keep `.env` local and uncommitted:

```powershell
Copy-Item .env.example .env
```

The checked-in PostgreSQL credentials are **development-only defaults** for
this local Compose stack. Replace them if the ports are exposed beyond the
developer machine. The compose services bind to loopback on ports 5432 and 6379 by default; update
`POSTGRES_PORT` or `REDIS_PORT` in `.env` if either host port is occupied, and
keep `DATABASE_URL`, `TEST_DATABASE_URL`, and `REDIS_URL` aligned with those
ports.

## Infra targets

From the repository root:

```powershell
docker compose --env-file .env -f docker/compose.dev.yml up -d --wait
docker compose --env-file .env -f docker/compose.dev.yml ps
docker compose --env-file .env -f docker/compose.dev.yml down
```

`make infra-up`, `make infra-down`, and `make infra-reset` are equivalents when
GNU Make is installed. `infra-reset` removes only this Compose project's named
development volumes, so it irreversibly deletes its local database and Redis
data:

```powershell
docker compose --env-file .env -f docker/compose.dev.yml down --volumes --remove-orphans
docker compose --env-file .env -f docker/compose.dev.yml up -d --wait
```

## Migrations and service checks

Apply migrations to the application database, then apply, roll back, and
re-apply them on the isolated `ecochain_test` database:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://ecochain:ecochain_dev_only@127.0.0.1:5432/ecochain"
.\.venv\Scripts\python.exe -m alembic upgrade head

$env:DATABASE_URL = "postgresql+psycopg://ecochain:ecochain_dev_only@127.0.0.1:5432/ecochain_test"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade base
.\.venv\Scripts\python.exe -m alembic upgrade head

docker compose --env-file .env -f docker/compose.dev.yml exec -T redis redis-cli ping
```

To run service-backed integration tests, configure `TEST_DATABASE_URL` in
`.env` or in the current PowerShell session, then run:

```powershell
.\scripts\test_integration.ps1
```

The script executes only tests marked `integration`. It does not silently
replace unavailable services with mocks.

## API and worker

The API and worker use the configured PostgreSQL and Redis services. Start them
in separate PowerShell terminals after applying migrations:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
.\.venv\Scripts\celery.exe -A backend.app.workers.celery_app:celery_app worker --pool=solo --loglevel=INFO
```

`WORKFLOW_SERVICES_FACTORY` must name a real `module:factory` callable that
returns the graph's production `WorkflowServices`. No production assembly is
currently included in this checkout; leave it unset rather than substituting a
test fake. Readiness, job submissions, and review decisions return 503 until
the production factory is supplied.

Export the API schema for frontend type generation with:

```powershell
.\.venv\Scripts\python.exe -m scripts.export_openapi
# Or, when GNU Make is installed:
make build
```

## RAG models and evaluation

Download the embedding and reranker models for offline local inference, then
run the citation-only evaluation:

```powershell
.\.venv\Scripts\python.exe -m scripts.download_rag_models
.\.venv\Scripts\python.exe -m scripts.evaluate_rag
```

The citation-only run writes `reports/rag.json`; the overall Phase 5 gate stays
pending until Ragas faithfulness and answer relevance are measured. Completing
those metrics makes guarded Gemini generation and OpenAI judge requests, may
incur provider charges, and requires explicit operator approval:

```powershell
.\.venv\Scripts\python.exe -m scripts.evaluate_rag --allow-external-model-calls
```

Set the provider API keys locally and enable tenant opt-in only for an
authorized evaluation. Ragas telemetry is disabled by the evaluator.

## Quick quality gate

```powershell
.\.venv\Scripts\ruff.exe check backend
.\.venv\Scripts\mypy.exe --strict backend\app
.\.venv\Scripts\pytest.exe backend\tests -v --cov=backend/app --cov-report=term-missing
```
