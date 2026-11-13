"""EcoChain Copilot backend application entrypoint."""

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.router import router as api_router
from backend.app.api.security import hash_password
from backend.app.core.config import settings
from backend.app.db.models import (
    ExternalRecord,
    ExternalSnapshot,
    ExternalSource,
    Factory,
    Job,
    Tenant,
    User,
)
from backend.app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)


def _check_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()


def _seed_demo_tenant() -> None:
    """Create fixed demo tenant/user/factories/external snapshots when AUTH_ENABLED=False."""
    from sqlalchemy import select

    with SessionLocal() as session:
        # ── Tenant ──────────────────────────────────────────────────────────
        tenant = session.get(Tenant, settings.DEMO_TENANT_ID)
        if tenant is None:
            tenant = Tenant(id=settings.DEMO_TENANT_ID, name="Demo Tenant")
            session.add(tenant)
            session.flush()

        # ── User ─────────────────────────────────────────────────────────────
        user = session.get(User, settings.DEMO_USER_ID)
        if user is None:
            session.add(
                User(
                    id=settings.DEMO_USER_ID,
                    tenant_id=settings.DEMO_TENANT_ID,
                    email="demo@ecochain.local",
                    hashed_password=hash_password("demo"),
                    role="tenant_admin",
                )
            )
            session.flush()

        # ── Factories ────────────────────────────────────────────────────────
        # external_id must match facility_id extracted from sample PDFs
        demo_factories = [
            ("Sunrise Electronics (Shanghai)", "CN", "FAC-001"),
            ("GreenPack Packaging (Berlin)",   "DE", "FAC-002"),
            ("Apex Textiles (Dhaka)",           "BD", "FAC-003"),
            ("ClearPath Chemicals (Mumbai)",    "IN", "FAC-004"),
        ]
        existing_factories = session.execute(
            select(Factory).where(Factory.tenant_id == settings.DEMO_TENANT_ID)
        ).scalars().all()
        if not existing_factories:
            for name, country, ext_id in demo_factories:
                session.add(
                    Factory(
                        tenant_id=settings.DEMO_TENANT_ID,
                        name=name,
                        country=country,
                        external_id=ext_id,
                    )
                )
            session.flush()
        else:
            # Patch external_ids in case they were seeded without them
            ext_id_map = {name: ext_id for name, _, ext_id in demo_factories}
            for factory in existing_factories:
                desired = ext_id_map.get(factory.name)
                if desired and factory.external_id != desired:
                    factory.external_id = desired
            session.flush()

        # ── External facility snapshot (makes V-EXT-001/002/003/900 pass) ───
        # Without a healthy snapshot, every claim escalates regardless of cert validity.
        source_id = "demo-facility-registry"
        existing_source = session.get(ExternalSource, source_id)
        if existing_source is None:
            session.add(
                ExternalSource(
                    id=source_id,
                    name="Demo Facility Registry (seeded)",
                    terms_url="https://example.com/terms",
                    license="demo",
                    max_age_days=3650,  # 10 years – never stale in demo
                )
            )
            session.flush()

            # Build snapshot records matching sample factory IDs/countries
            records_data = [
                {"key": "FAC-001", "name": "Sunrise Electronics (Shanghai)", "country": "CN"},
                {"key": "FAC-002", "name": "GreenPack Packaging (Berlin)",   "country": "DE"},
                {"key": "FAC-003", "name": "Apex Textiles (Dhaka)",           "country": "BD"},
                {"key": "FAC-004", "name": "ClearPath Chemicals (Mumbai)",    "country": "IN"},
            ]
            content_hash = hashlib.sha256(
                str(sorted(r["key"] for r in records_data)).encode()
            ).hexdigest()
            snapshot_id = str(uuid.uuid4())
            session.add(
                ExternalSnapshot(
                    id=snapshot_id,
                    source_id=source_id,
                    fetched_at=datetime.now(UTC),
                    content_hash=content_hash,
                    record_count=len(records_data),
                    path="demo://seeded",
                )
            )
            session.flush()

            for rec in records_data:
                session.add(
                    ExternalRecord(
                        id=str(uuid.uuid4()),
                        snapshot_id=snapshot_id,
                        key=rec["key"],
                        normalized_name=rec["name"].lower(),
                        country=rec["country"],
                        payload={
                            "identifiers": {"facility_id": rec["key"]},
                            "parent_company_match": True,
                        },
                    )
                )

        # ── Sanctions watchlist snapshot (makes V-SANC-001/002 pass) ─────────
        # V-SANC-001/002 escalate when matches is None (no sanctions sources).
        # Seeding an empty watchlist means matches=[] → pass (no hits found).
        sanc_source_id = "demo-sanctions-ofac"
        existing_sanc_source = session.get(ExternalSource, sanc_source_id)
        if existing_sanc_source is None:
            session.add(
                ExternalSource(
                    id=sanc_source_id,
                    name="Demo OFAC/Sanctions Watchlist (seeded)",
                    terms_url="https://example.com/terms",
                    license="demo",
                    max_age_days=3650,
                )
            )
            session.flush()

            sanc_snapshot_id = str(uuid.uuid4())
            sanc_content_hash = hashlib.sha256(b"demo-empty-sanctions").hexdigest()
            session.add(
                ExternalSnapshot(
                    id=sanc_snapshot_id,
                    source_id=sanc_source_id,
                    fetched_at=datetime.now(UTC),
                    content_hash=sanc_content_hash,
                    record_count=0,  # empty – no sanctioned entities
                    path="demo://seeded-sanctions",
                )
            )
            # No records → empty watchlist → V-SANC-001/002 see matches=[] → pass

        session.commit()
    logger.info("Demo tenant seeded (tenant_id=%s)", settings.DEMO_TENANT_ID)


def _cleanup_stuck_jobs() -> None:
    """Mark any job stuck in 'processing' or 'queued' for longer than the timeout as failed."""
    cutoff = datetime.now(UTC) - timedelta(seconds=300)
    with SessionLocal() as session:
        from sqlalchemy import select
        stuck_jobs = session.execute(
            select(Job).where(
                Job.status.in_(["processing", "queued"]),
                Job.created_at < cutoff,
            )
        ).scalars().all()
        for job in stuck_jobs:
            logger.warning("Cleaning up stuck job %s (created %s)", job.id, job.created_at)
            job.status = "failed"
        if stuck_jobs:
            session.commit()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    application.state.redis = redis
    await run_in_threadpool(_cleanup_stuck_jobs)
    if not settings.AUTH_ENABLED:
        await run_in_threadpool(_seed_demo_tenant)
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
