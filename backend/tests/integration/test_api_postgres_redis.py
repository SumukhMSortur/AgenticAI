"""API authorization and Redis Streams checks against local real services."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pymupdf
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import create_engine, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.events import job_stream_key
from backend.app.api.security import create_access_token, hash_password
from backend.app.core.config import settings
from backend.app.db.audit_log import verify_chain
from backend.app.db.models import (
    AuditEvent,
    Document,
    ExternalRecord,
    ExternalSnapshot,
    ExternalSource,
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
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _service_urls() -> tuple[str, str]:
    database_url = os.environ.get("ECOCHAIN_TEST_POSTGRES_URL") or settings.TEST_DATABASE_URL
    if not database_url:
        pytest.fail(
            "Set TEST_DATABASE_URL or ECOCHAIN_TEST_POSTGRES_URL for API integration tests."
        )
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
    job_id = str(uuid.uuid4())
    factory_id = str(uuid.uuid4())
    factory_external_id = f"{prefix}-facility"
    job = Job(
        id=job_id,
        tenant_id=tenant_id,
        thread_id=str(uuid.uuid4()),
        status="review_required",
        assessment_date="2026-11-02",
        query="Test API authorization",
        route="full_analysis",
        scorecard_data={
            "job_id": job_id,
            "tenant_id": tenant_id,
            "assessment_date": "2026-11-02",
            "overall_status": "review_required",
            "risk_score": 0.72,
            "lines": [],
            "re_audit_recommended": True,
            "summary": "Test scorecard",
            "escalation": {"priority": "critical"},
            "risk_forecast": {
                "factory_id": factory_external_id,
                "p_fail_6m": 0.72,
                "model_tag": "xgboost",
                "baseline_comparison": {"status": "promoted"},
            },
        },
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
        id=factory_id,
        tenant_id=tenant_id,
        name=f"{prefix} factory",
        country="Test",
        external_id=factory_external_id,
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
        "job_id": job_id,
        "document_id": document.id,
        "factory_id": factory_id,
        "review_id": review.id,
        "audit_id": str(audit.id),
        "proposal_id": proposal.id,
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


def _set_compose_service(service: str, *, running: bool) -> None:
    docker = shutil.which("docker")
    if docker is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = (
                Path(local_app_data)
                / "Programs"
                / "DockerDesktop"
                / "resources"
                / "bin"
                / "docker.exe"
            )
            if candidate.exists():
                docker = str(candidate)
    if docker is None:
        pytest.fail("Docker CLI is required for real-service outage integration tests.")

    action = ["up", "-d", "--wait", service] if running else ["stop", service]
    result = subprocess.run(
        [
            docker,
            "compose",
            "--env-file",
            ".env",
            "-f",
            "docker/compose.dev.yml",
            *action,
        ],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=120,
    )
    if result.returncode:
        pytest.fail(
            f"Could not {'start' if running else 'stop'} Compose service {service}:\n"
            f"{result.stdout}\n{result.stderr}"
        )


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
                    f"/v1/jobs/{foreign['job_id']}/scorecard",
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
                    f"/v1/documents/{foreign['document_id']}/pages/1.png",
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
            assert (
                client.get(
                    f"/v1/factories/{foreign['factory_id']}/risk",
                    headers=headers,
                ).status_code
                == 404
            )
            assert client.get("/v1/jobs", headers=headers).json()[0]["id"] == own["job_id"]
            assert (
                client.post(
                    f"/v1/reviews/{foreign['review_id']}/decision",
                    headers=headers,
                    json={"decision": "approved", "notes": "Cross-tenant check"},
                ).status_code
                == 404
            )
            scorecard = client.get(
                f"/v1/jobs/{own['job_id']}/scorecard",
                headers=headers,
            )
            assert scorecard.status_code == 200
            assert scorecard.json()["overall_status"] == "review_required"
            risk = client.get(
                f"/v1/factories/{own['factory_id']}/risk",
                headers=headers,
            )
            assert risk.status_code == 200
            assert risk.json()["risk_score"] == 0.72
            assert len(client.get("/v1/reviews", headers=headers).json()) == 1
            assert client.get("/v1/reviews", headers=headers).json()[0]["priority"] == "critical"
            assert client.get("/v1/audit-events", headers=headers).json()[0]["id"] == int(
                own["audit_id"]
            )
            assert len(client.get("/v1/regulation-proposals", headers=headers).json()) == 1
            assert (
                client.post(
                    f"/v1/regulation-proposals/{foreign['proposal_id']}/decision",
                    headers=headers,
                    json={"decision": "rejected", "notes": "Cross-tenant check"},
                ).status_code
                == 404
            )
            integration_status = client.get(
                "/v1/integrations/status",
                headers=headers,
            ).json()
            assert all(item["live_enabled"] for item in integration_status)
            foreign_token = _token(client, emails[1])
            foreign_headers = {"Authorization": f"Bearer {foreign_token}"}
            foreign_status = client.get(
                "/v1/integrations/status",
                headers=foreign_headers,
            ).json()
            assert all(not item["live_enabled"] for item in foreign_status)
            assert client.get("/v1/settings/live-lookup", headers=headers).json() == {
                "enabled": True
            }
            proposal_id = client.get(
                "/v1/regulation-proposals",
                headers=headers,
            ).json()[0]["id"]
            proposal_decision = client.post(
                f"/v1/regulation-proposals/{proposal_id}/decision",
                headers=headers,
                json={"decision": "rejected", "notes": "Test rejection"},
            )
            assert proposal_decision.status_code == 200
            assert proposal_decision.json()["status"] == "rejected"

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


def test_authentication_and_role_authorization_fail_closed() -> None:
    database_url, _ = _service_urls()
    engine = create_engine(database_url, pool_pre_ping=True)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    email = f"{uuid.uuid4().hex}@example.test"

    def override_db() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with test_session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Authorization tenant"))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=email,
                    hashed_password=hash_password("test-password"),
                    role="viewer",
                )
            )
            session.commit()

        with TestClient(app) as client:
            assert client.get("/v1/jobs").status_code == 401
            assert client.get(
                "/v1/jobs",
                headers={"Authorization": "Bearer malformed"},
            ).status_code == 401
            assert (
                client.post(
                    "/v1/auth/token",
                    data={"username": email, "password": "wrong-password"},
                ).status_code
                == 401
            )
            token = _token(client, email)
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/v1/reviews", headers=headers).status_code == 403
            assert (
                client.put(
                    "/v1/settings/live-lookup",
                    headers=headers,
                    json={"enabled": True},
                ).status_code
                == 403
            )

            forged_subject, _ = create_access_token(
                user_id="not-a-uuid",
                tenant_id=tenant_id,
                role="tenant_admin",
            )
            assert client.get(
                "/v1/jobs",
                headers={"Authorization": f"Bearer {forged_subject}"},
            ).status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
        _cleanup_tenants(test_session_factory, [tenant_id])
        engine.dispose()


def test_real_local_workflow_pauses_and_resumes_through_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    database_url, redis_url = _service_urls()
    engine = create_engine(database_url, pool_pre_ping=True)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    redis = Redis.from_url(redis_url, decode_responses=True)
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    email = f"{uuid.uuid4().hex}@example.test"
    source_id = f"000-osh-{uuid.uuid4().hex}"
    job_id: str | None = None
    worker: subprocess.Popen[bytes] | None = None
    worker_log = None
    worker_log_path = tmp_path / "celery-worker.log"

    def override_db() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    from backend.app.workers.celery_app import celery_app

    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    monkeypatch.setattr(settings, "REDIS_URL", redis_url)
    monkeypatch.setattr(settings, "UPLOAD_DIRECTORY", tmp_path)
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIRECTORY", tmp_path / "chroma")
    monkeypatch.setattr(
        settings,
        "WORKFLOW_SERVICES_FACTORY",
        "backend.app.graph.services:create_workflow_services",
    )
    monkeypatch.setattr(celery_app.conf, "broker_url", redis_url)
    monkeypatch.setattr(celery_app.conf, "result_backend", redis_url)
    app.dependency_overrides[get_db] = override_db

    try:
        with test_session_factory() as session:
            session.add(Tenant(id=tenant_id, name="Workflow tenant"))
            session.flush()
            session.add_all(
                [
                    User(
                        id=user_id,
                        tenant_id=tenant_id,
                        email=email,
                        hashed_password=hash_password("test-password"),
                        role="auditor",
                    ),
                    Factory(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        name="Turkey Apparel Mill #259",
                        country="Turkey",
                        external_id="FACT-0259",
                    ),
                    RegulationUpdateProposal(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source="EUR-Lex",
                        candidate_version_id="EU-ESPR-2024-1781",
                        status="pending",
                    ),
                ]
            )
            session.add(
                ExternalSource(
                    id=source_id,
                    name="Open Supply Hub fixture",
                    terms_url="https://example.test/terms",
                    license="fixture",
                )
            )
            session.flush()
            snapshot = ExternalSnapshot(
                source_id=source_id,
                fetched_at=datetime(2026, 11, 2, tzinfo=UTC),
                content_hash="b" * 64,
                record_count=1,
                path=f"fixtures/{source_id}.json",
            )
            session.add(snapshot)
            session.flush()
            session.add(
                ExternalRecord(
                    snapshot_id=snapshot.id,
                    key="FACT-0259",
                    normalized_name="Turkey Apparel Mill #259",
                    country="Turkey",
                    payload={
                        "identifiers": {"facility_id": "FACT-0259"},
                        "parent_company_match": True,
                    },
                )
            )
            session.commit()

        pdf_document = pymupdf.open()
        page = pdf_document.new_page()
        page.insert_text(
            (72, 72),
            "GOTS CERTIFICATE\n"
            "Applicant Facility ID: FACT-0259\n"
            "Certification Body: EcoChain Approved Certification\n"
            "Valid From: 2026-01-01\n"
            "Valid To: 2027-01-01\n"
            "Scope: Cotton",
        )
        valid_pdf = pdf_document.tobytes()
        pdf_document.close()

        worker_environment = os.environ.copy()
        worker_environment.update(
            {
                "DATABASE_URL": database_url,
                "REDIS_URL": redis_url,
                "UPLOAD_DIRECTORY": str(tmp_path),
                "CHROMA_PERSIST_DIRECTORY": str(tmp_path / "chroma"),
                "WORKFLOW_SERVICES_FACTORY": (
                    "backend.app.graph.services:create_workflow_services"
                ),
                "LLM_PROVIDER": "fake",
            }
        )
        worker_log = worker_log_path.open("wb")
        worker = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "backend.app.workers.celery_app:celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                "--loglevel=WARNING",
                "--hostname=ecochain-integration@%h",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
            ],
            cwd=Path(__file__).resolve().parents[3],
            env=worker_environment,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
        )
        for _ in range(60):
            if worker.poll() is not None:
                pytest.fail(
                    "Celery integration worker exited during startup: "
                    f"{worker_log_path.read_text(encoding='utf-8')}"
                )
            if celery_app.control.ping(timeout=1):
                break
            time.sleep(1)
        else:
            pytest.fail(
                "Celery integration worker did not become ready: "
                f"{worker_log_path.read_text(encoding='utf-8')}"
            )

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {_token(client, email)}"}
            submitted = client.post(
                "/v1/jobs",
                headers=headers,
                data={
                    "assessment_date": "2026-11-02",
                    "query": "Assess this supplier certificate for compliance.",
                },
                files=[("files", ("certificate.pdf", valid_pdf, "application/pdf"))],
            )
            assert submitted.status_code == 202, submitted.text
            job_id = submitted.json()["id"]

            job = None
            for _ in range(120):
                response = client.get(f"/v1/jobs/{job_id}", headers=headers)
                assert response.status_code == 200, response.text
                job = response.json()
                if job["status"] in {"review_required", "failed"}:
                    break
                time.sleep(1)
            assert job is not None
            assert job["status"] == "review_required", (
                f"Expected a review pause, got {job['status']}; "
                f"worker log: {worker_log_path.read_text(encoding='utf-8')}"
            )
            scorecard = client.get(f"/v1/jobs/{job_id}/scorecard", headers=headers)
            assert scorecard.status_code == 200
            assert scorecard.json()["risk_score"] is not None
            external_refs = [
                evidence["ref"]
                for line in scorecard.json()["lines"]
                for evidence in line["evidence"]
                if evidence["kind"] == "external_record"
            ]
            assert any(
                reference["source"].startswith("000-osh-")
                and reference["snapshot_hash"] == "b" * 64
                for reference in external_refs
            )
            query_result = client.post(
                "/v1/query",
                headers=headers,
                json={
                    "query": "What supply-chain due diligence is required?",
                    "assessment_date": "2026-11-02",
                    "jurisdiction": "EU",
                    "top_k": 5,
                },
            )
            assert query_result.status_code == 200, query_result.text
            assert isinstance(query_result.json()["supported"], bool)
            documents = client.get(
                f"/v1/jobs/{job_id}/documents",
                headers=headers,
            )
            assert documents.status_code == 200
            document_id = documents.json()[0]["id"]
            page_url = f"/v1/documents/{document_id}/pages/1.png"
            page_image = client.get(page_url, headers=headers)
            assert page_image.status_code == 200
            assert page_image.headers["content-type"] == "image/png"
            cached_page = client.get(
                page_url,
                headers={**headers, "If-None-Match": page_image.headers["etag"]},
            )
            assert cached_page.status_code == 304
            reviews = client.get("/v1/reviews", headers=headers)
            assert reviews.status_code == 200
            assert len(reviews.json()) == 1
            review = reviews.json()[0]

            resumed = client.post(
                f"/v1/reviews/{review['id']}/decision",
                headers=headers,
                json={"decision": "approved", "notes": "Evidence reviewed"},
            )
            assert resumed.status_code == 200, resumed.text
            completed = None
            for _ in range(120):
                response = client.get(f"/v1/jobs/{job_id}", headers=headers)
                assert response.status_code == 200, response.text
                completed = response.json()
                if completed["status"] in {"completed", "failed"}:
                    break
                time.sleep(1)
            assert completed is not None
            assert completed["status"] == "completed", (
                f"Expected completed review, got {completed['status']}; "
                f"worker log: {worker_log_path.read_text(encoding='utf-8')}"
            )
            proposals = client.get("/v1/regulation-proposals", headers=headers)
            assert proposals.status_code == 200
            proposal_id = proposals.json()[0]["id"]
            approved = client.post(
                f"/v1/regulation-proposals/{proposal_id}/decision",
                headers=headers,
                json={"decision": "approved", "notes": "Verified source version"},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"
            with test_session_factory() as session:
                assert verify_chain(session, tenant_id) == (True, None)
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=20)
        if worker_log is not None:
            worker_log.close()
        app.dependency_overrides.pop(get_db, None)
        if job_id is not None:
            redis.delete(job_stream_key(job_id))
        with test_session_factory() as session:
            source = session.get(ExternalSource, source_id)
            if source is not None:
                session.delete(source)
                session.commit()
        _cleanup_tenants(test_session_factory, [tenant_id])
        redis.close()


def test_postgres_and_redis_outages_fail_closed_and_recover(
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
    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    email = f"{uuid.uuid4().hex}@example.test"
    job: dict[str, str] | None = None

    def override_db() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    from backend.app.workers import tasks

    monkeypatch.setattr(tasks, "SessionLocal", test_session_factory)
    app.dependency_overrides[get_db] = override_db
    try:
        with test_session_factory() as session:
            job = _create_tenant_data(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                email=email,
                prefix="outage",
                live_lookup_enabled=False,
            )
            queued_job = session.get(Job, job["job_id"])
            assert queued_job is not None
            queued_job.status = "queued"
            session.commit()

        with TestClient(app, raise_server_exceptions=False) as client:
            headers = {"Authorization": f"Bearer {_token(client, email)}"}
            with ThreadPoolExecutor(max_workers=1) as executor:
                for service, expected_error in (
                    ("postgres", SQLAlchemyError),
                    ("redis", RedisError),
                ):
                    with test_session_factory() as session:
                        queued_job = session.get(Job, job["job_id"])
                        assert queued_job is not None
                        queued_job.status = "queued"
                        session.commit()

                    started = threading.Event()
                    resume = threading.Event()

                    def blocked_graph(
                        *_args: object,
                        started_event: threading.Event = started,
                        resume_event: threading.Event = resume,
                        **_kwargs: object,
                    ) -> tuple[dict[str, object], bool]:
                        started_event.set()
                        if not resume_event.wait(timeout=30):
                            raise TimeoutError("test worker was not released")
                        return {}, False

                    monkeypatch.setattr(tasks, "_run_graph", blocked_graph)
                    worker_result = executor.submit(
                        tasks.process_job.run,
                        job["job_id"],
                        tenant_id,
                    )
                    assert started.wait(timeout=30), "worker did not enter the graph"
                    try:
                        _set_compose_service(service, running=False)
                        assert client.get("/readyz").status_code == 503
                        if service == "redis":
                            limited_request = client.get("/v1/jobs", headers=headers)
                            assert limited_request.status_code == 503
                            assert limited_request.json()["detail"] == (
                                "Rate limiting service is unavailable"
                            )
                        resume.set()
                        with pytest.raises(expected_error):
                            worker_result.result(timeout=30)
                    finally:
                        resume.set()
                        try:
                            if not worker_result.done():
                                with suppress(SQLAlchemyError, RedisError):
                                    worker_result.result(timeout=30)
                        finally:
                            _set_compose_service(service, running=True)

                    assert client.get("/readyz").status_code == 200
                    with test_session_factory() as session:
                        recovered_job = session.get(Job, job["job_id"])
                        assert recovered_job is not None
                        if service == "postgres":
                            assert recovered_job.status == "processing"
                            recovered_job.status = "queued"
                            session.commit()
                            monkeypatch.setattr(
                                tasks,
                                "_run_graph",
                                lambda *_args, **_kwargs: ({}, False),
                            )
                            assert (
                                tasks.process_job.run(job["job_id"], tenant_id) == "completed"
                            )
                        else:
                            assert recovered_job.status == "failed"
                    if service == "redis":
                        assert client.get("/v1/jobs", headers=headers).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
        if job is not None:
            redis.delete(job_stream_key(job["job_id"]))
            _cleanup_tenants(test_session_factory, [tenant_id])
        redis.close()
        engine.dispose()
        engine.dispose()
