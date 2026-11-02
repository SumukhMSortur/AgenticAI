"""EcoChain Copilot backend application entrypoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.router import router as api_router
from backend.app.core.config import settings
from backend.app.db.session import engine

logger = logging.getLogger(__name__)


def _check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    application.state.redis = redis
    try:
        yield
    finally:
        await redis.aclose()


app = FastAPI(
    title="EcoChain Copilot API",
    version="0.1.0",
    description="Enterprise multi-agent supply-chain compliance system",
    lifespan=lifespan,
)
app.include_router(api_router)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz() -> dict[str, str]:
    """Report readiness only when the configured database and Redis are available."""
    if not settings.WORKFLOW_SERVICES_FACTORY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow services factory is not configured",
        )
    redis: Redis | None = getattr(app.state, "redis", None)
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is not initialized",
        )
    try:
        await redis.ping()
        await run_in_threadpool(_check_database)
    except (RedisError, SQLAlchemyError) as exc:
        logger.error("Readiness check failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required dependency is unavailable",
        ) from exc
    return {"status": "ready"}
