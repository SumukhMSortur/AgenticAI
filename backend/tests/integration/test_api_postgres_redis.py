"""API authorization and Redis Streams checks against local real services."""

import json
import os
import uuid
from collections.abc import Iterator
from urllib.parse import urlsplit

import pymupdf
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.events import job_stream_key
from backend.app.api.security import hash_password
from backend.app.core.config import settings
from backend.app.db.models import (
    AuditEvent,
    Document,
    Factory,
    Job,
    JobDocument,
    RegulationUpdateProposal,
    Review,
    Tenant,
    User,
)
from backend.app.db.session import get_db
from backend.app.main import app

pytestmark = pytest.mark.integration


def _service_urls() -> tuple[str, str]:
    database_url = os.environ.get("ECOCHAIN_TEST_POSTGRES_URL") or settings.TEST_DATABASE_URL
    if not database_url:
        pytest.fail("Set TEST_DATABASE_URL or ECOCHAIN_TEST_POSTGRES_URL for API integration tests.")
    parsed_database = urlsplit(database_url)
    if (
        parsed_database.hostname not in {"localhost", "127.0.0.1"}
        or parsed_database.port != 5432
        or parsed_database.path != "/ecochain_test"
    ):
        pytest.fail("API integration requires the local Compose ecochain_test database.")

    redis_url = os.environ.get("ECOCHAIN_TEST_REDIS_URL") or settings.REDIS_URL
    parsed_redis = urlsplit(redis_url)
    if parsed_redis.hostname not in {"localhost", "127.0.0.1"} or parsed_redis.port != 6379:
        pytest.fail("API integration requires the local Compose Redis service.")
    try:
        with Redis.from_url(redis_url) as redis:
            redis.ping()
    except RedisError as exc:
        pytest.fail(f"Redis integration service is unavailable: {type(exc).__name__}")
    return database_url, redis_url


def _create_tenant_data(
    session: Session,
    *,
    tenant_id: str,
    user_id: str,
    email: str,
    prefix: str,
    live_lookup_enabled: bool,
) -> dict[str, str]:
    tenant = Tenant(
        id=tenant_id,
        name=f"{prefix} tenant",
        live_lookup_enabled=live_lookup_enabled,
    )
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=email,
        hashed_password=hash_password("test-password"),
        role="auditor",
    )
    job = Job(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        thread_id=str(uuid.uuid4()),
        status="review_required",
        assessment_date="2026-11-02",
        query="Test API authorization",
        route="full_analysis",
        scorecard_data={"escalation": {"priority": "critical"}},
    )
    document = Document(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        doc_hash=uuid.uuid4().hex * 2,
        filename=f"{prefix}.pdf",
        mime_type="application/pdf",
        page_count=1,
        storage_path=f"data/uploads/{tenant_id}/unused.pdf",
    )
    factory = Factory(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=f"{prefix} factory",
        country="Test",
    )
    session.add(tenant)
    session.flush()
    session.add_all([user, job, document, factory])
    session.flush()
    review = Review(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        job_id=job.id,
        thread_id=job.thread_id,
        status="pending",
    )
    audit = AuditEvent(
        tenant_id=tenant_id,
        sequence=1,
        event_type="test.event",
        prev_hash="0" * 64,
        event_hash=uuid.uuid4().hex * 2,
        payload={"summary": "tenant test event"},
    )
    proposal = RegulationUpdateProposal(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        source="test-source",
        candidate_version_id=f"{prefix}-v1",
        status="pending",
    )
    session.add_all(
        [
            JobDocument(job_id=job.id, document_id=document.id, tenant_id=tenant_id),
            review,
            audit,
            proposal,
        ]
    )
    session.commit()
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "email": email,
        "job_id": job.id,
        "document_id": document.id,
        "factory_id": factory.id,
        "review_id": review.id,
        "audit_id": str(audit.id),
    }


def _token(client: TestClient, email: str) -> str:
    response = client.post(
        "/v1/auth/token",
        data={"username": email, "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _cleanup_tenants(
    session_factory: sessionmaker[Session],
    tenant_ids: list[str],
) -> None:
    with session_factory() as session:
        session.execute(delete(AuditEvent).where(AuditEvent.tenant_id.in_(tenant_ids)))
        session.execute(delete(Review).where(Review.tenant_id.in_(tenant_ids)))
        session.execute(delete(JobDocument).where(JobDocument.tenant_id.in_(tenant_ids)))
        session.execute(delete(Document).where(Document.tenant_id.in_(tenant_ids)))
        session.execute(delete(Job).where(Job.tenant_id.in_(tenant_ids)))
        session.execute(delete(Factory).where(Factory.tenant_id.in_(tenant_ids)))
        session.execute(
            delete(RegulationUpdateProposal).where(
                RegulationUpdateProposal.tenant_id.in_(tenant_ids)
            )
        )
        session.execute(delete(User).where(User.tenant_id.in_(tenant_ids)))
        session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
        session.commit()


def test_tenant_isolation_sse_replay_and_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, redis_url = _service_urls()
    engine = create_engine(database_url, pool_pre_ping=True)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    redis = Redis.from_url(redis_url, decode_responses=True)
    tenant_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    users = [str(uuid.uuid4()), str(uuid.uuid4())]
    emails = [f"{uuid.uuid4().hex}@example.test", f"{uuid.uuid4().hex}@example.test"]
    own = foreign = None

    def override_db() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with test_session_factory() as session:
            own = _create_tenant_data(
                session,
                tenant_id=tenant_ids[0],
                user_id=users[0],
                email=emails[0],
                prefix="own",
                live_lookup_enabled=True,
            )
            foreign = _create_tenant_data(
                session,
                tenant_id=tenant_ids[1],
                user_id=users[1],
                email=emails[1],
                prefix="foreign",
                live_lookup_enabled=False,
            )

        with TestClient(app) as client:
            token = _token(client, emails[0])
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get(f"/v1/jobs/{foreign['job_id']}", headers=headers).status_code == 404
            assert (
                client.get(
                    f"/v1/jobs/{foreign['job_id']}/documents",
                    headers=headers,
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"/v1/documents/{foreign['document_id']}",
                    headers=headers,
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"/v1/factories/{foreign['factory_id']}",
                    headers=headers,
                ).status_code
                == 404
            )
            assert client.get("/v1/jobs", headers=headers).json()[0]["id"] == own["job_id"]
            assert len(client.get("/v1/reviews", headers=headers).json()) == 1
            assert client.get("/v1/reviews", headers=headers).json()[0]["priority"] == "critical"
            assert (
                client.get("/v1/audit-events", headers=headers).json()[0]["id"]
                == int(own["audit_id"])
            )
            assert len(client.get("/v1/regulation-proposals", headers=headers).json()) == 1
            assert client.get("/v1/settings/live-lookup", headers=headers).json() == {
                "enabled": True
            }

            stream_key = job_stream_key(own["job_id"])
            redis.delete(stream_key)
            first_id = redis.xadd(
                stream_key,
                {
                    "event_type": "submitted",
                    "data": json.dumps(
                        {
                            "job_id": own["job_id"],
                            "event_type": "submitted",
                            "summary": "Job submitted.",
                        }
                    ),
                },
            )
            redis.xadd(
                stream_key,
                {
                    "event_type": "step",
                    "data": json.dumps(
                        {
                            "job_id": own["job_id"],
                            "event_type": "step",
                            "summary": "Workflow step completed.",
                        }
                    ),
                },
            )
            terminal_id = redis.xadd(
                stream_key,
                {
                    "event_type": "completed",
                    "data": json.dumps(
                        {
                            "job_id": own["job_id"],
                            "event_type": "completed",
                            "summary": "Workflow completed.",
                        }
                    ),
                },
            )
            initial_stream = client.get(
                f"/v1/jobs/{own['job_id']}/events",
                headers=headers,
            )
            assert initial_stream.status_code == 200
            assert "Job submitted." in initial_stream.text
            assert "Workflow completed." in initial_stream.text
            replay = client.get(
                f"/v1/jobs/{own['job_id']}/events",
                headers={**headers, "Last-Event-ID": first_id},
            )
            assert replay.status_code == 200
            assert "Job submitted." not in replay.text
            assert "Workflow step completed." in replay.text
            assert "Workflow completed." in replay.text
            reconnect_after_terminal = client.get(
                f"/v1/jobs/{own['job_id']}/events",
                headers={**headers, "Last-Event-ID": terminal_id},
            )
            assert reconnect_after_terminal.status_code == 200
            assert reconnect_after_terminal.text == ""

            monkeypatch.setattr(settings, "WORKFLOW_SERVICES_FACTORY", "")
            pdf_document = pymupdf.open()
            pdf_document.new_page()
            valid_pdf = pdf_document.tobytes()
            pdf_document.close()
            unavailable_worker = client.post(
                "/v1/jobs",
                headers=headers,
                data={"assessment_date": "2026-11-02"},
                files=[("files", ("valid.pdf", valid_pdf, "application/pdf"))],
            )
            assert unavailable_worker.status_code == 503
            assert len(client.get("/v1/jobs", headers=headers).json()) == 1

            monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 32)
            form_data = {"assessment_date": "2026-11-02"}
            oversized = client.post(
                "/v1/jobs",
                headers=headers,
                data=form_data,
                files=[("files", ("oversized.pdf", b"%PDF-" + b"x" * 100, "application/pdf"))],
            )
            assert oversized.status_code == 413
            wrong_type = client.post(
                "/v1/jobs",
                headers=headers,
                data=form_data,
                files=[("files", ("notes.txt", b"not a pdf", "text/plain"))],
            )
            assert wrong_type.status_code == 415
            malformed = client.post(
                "/v1/jobs",
                headers=headers,
                data=form_data,
                files=[("files", ("malformed.pdf", b"%PDF-bad", "application/pdf"))],
            )
            assert malformed.status_code == 400

            rate_key = f"ecochain:rate:{tenant_ids[0]}:{users[0]}"
            redis.delete(rate_key)
            monkeypatch.setattr(settings, "API_RATE_LIMIT_REQUESTS", 2)
            assert client.get("/v1/jobs", headers=headers).status_code == 200
            assert client.get("/v1/jobs", headers=headers).status_code == 200
            assert client.get("/v1/jobs", headers=headers).status_code == 429
    finally:
        app.dependency_overrides.pop(get_db, None)
        redis.delete(f"ecochain:rate:{tenant_ids[0]}:{users[0]}")
        if own is not None:
            redis.delete(job_stream_key(own["job_id"]))
        if own is not None and foreign is not None:
            _cleanup_tenants(test_session_factory, tenant_ids)
        redis.close()
        engine.dispose()
