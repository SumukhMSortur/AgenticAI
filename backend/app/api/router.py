"""Authenticated, tenant-scoped HTTP endpoints."""

from datetime import date
from typing import Annotated

from celery.exceptions import CeleryError
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.security import OAuth2PasswordRequestForm
from redis.asyncio import Redis
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from backend.app.api import repositories
from backend.app.api.events import publish_job_event, stream_job_events, validate_stream_id
from backend.app.api.rate_limit import enforce_rate_limit
from backend.app.api.schemas import (
    AuditEventRead,
    DocumentRead,
    FactoryRead,
    IntegrationStatus,
    JobDetail,
    JobRead,
    LiveLookupSetting,
    RegulationProposalRead,
    ReviewDecisionRequest,
    ReviewRead,
    TokenResponse,
)
from backend.app.api.security import (
    CurrentPrincipal,
    Principal,
    create_access_token,
    verify_password,
)
from backend.app.api.uploads import validate_upload_batch
from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.workers.tasks import process_job, resume_review

router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(enforce_rate_limit)],
)

Database = Annotated[Session, Depends(get_db)]


def _tenant_admin(principal: Principal) -> None:
    if principal.role not in {"admin", "tenant_admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant administrator role required",
        )


def _reviewer(principal: Principal) -> None:
    if principal.role not in {"admin", "tenant_admin", "reviewer", "auditor"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer role required",
        )


def _redis(request: Request) -> Redis:
    redis: Redis | None = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis service is unavailable",
        )
    return redis


def _require_workflow_factory() -> None:
    if not settings.WORKFLOW_SERVICES_FACTORY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job processing is not configured; set WORKFLOW_SERVICES_FACTORY",
        )


@router.post("/auth/token", response_model=TokenResponse, tags=["auth"])
async def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Database,
) -> TokenResponse:
    user = await run_in_threadpool(repositories.get_user_by_email, session, form.username)
    verified = (
        await run_in_threadpool(verify_password, form.password, user.hashed_password)
        if user is not None
        else False
    )
    if user is None or not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post(
    "/jobs",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["jobs"],
)
async def submit_job(
    request: Request,
    principal: CurrentPrincipal,
    session: Database,
    assessment_date: Annotated[date, Form()],
    files: Annotated[list[UploadFile], File()],
    query: Annotated[str, Form(min_length=1, max_length=1000)] = "Assess uploaded documents.",
) -> JobRead:
    uploads = await validate_upload_batch(files)
    query = query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query must not be blank",
        )
    _require_workflow_factory()
    job, created = await run_in_threadpool(
        repositories.create_or_get_job,
        session,
        principal.tenant_id,
        assessment_date,
        uploads,
        query,
    )
    redis = _redis(request)
    if created:
        await publish_job_event(
            redis,
            job.id,
            "submitted",
            "Job submitted.",
        )
    if job.status == "queued":
        try:
            await run_in_threadpool(process_job.delay, job.id, principal.tenant_id)
        except CeleryError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Job queue is unavailable; retry the same submission",
            ) from exc
    return JobRead.model_validate(job)


@router.get("/jobs", response_model=list[JobRead], tags=["jobs"])
async def get_jobs(principal: CurrentPrincipal, session: Database) -> list[JobRead]:
    jobs = await run_in_threadpool(repositories.list_jobs, session, principal.tenant_id)
    return [JobRead.model_validate(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetail, tags=["jobs"])
async def get_job(
    job_id: str,
    principal: CurrentPrincipal,
    session: Database,
) -> JobDetail:
    job = await run_in_threadpool(
        repositories.get_job, session, principal.tenant_id, job_id
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobDetail.model_validate(job)


@router.get("/jobs/{job_id}/documents", response_model=list[DocumentRead], tags=["documents"])
async def get_job_documents(
    job_id: str,
    principal: CurrentPrincipal,
    session: Database,
) -> list[DocumentRead]:
    job = await run_in_threadpool(
        repositories.get_job, session, principal.tenant_id, job_id
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    documents = await run_in_threadpool(
        repositories.get_job_documents,
        session,
        principal.tenant_id,
        job_id,
    )
    return [DocumentRead.model_validate(document) for document in documents]


@router.get("/documents/{document_id}", response_model=DocumentRead, tags=["documents"])
async def get_document(
    document_id: str,
    principal: CurrentPrincipal,
    session: Database,
) -> DocumentRead:
    document = await run_in_threadpool(
        repositories.get_document,
        session,
        principal.tenant_id,
        document_id,
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return DocumentRead.model_validate(document)


@router.get("/jobs/{job_id}/events", tags=["jobs"])
async def get_job_events(
    job_id: str,
    request: Request,
    principal: CurrentPrincipal,
    session: Database,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    job = await run_in_threadpool(
        repositories.get_job, session, principal.tenant_id, job_id
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    validate_stream_id(last_event_id)
    return EventSourceResponse(
        stream_job_events(request, _redis(request), job_id, last_event_id),
        ping=15,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/reviews", response_model=list[ReviewRead], tags=["reviews"])
async def get_reviews(principal: CurrentPrincipal, session: Database) -> list[ReviewRead]:
    _reviewer(principal)
    rows = await run_in_threadpool(
        repositories.list_pending_reviews,
        session,
        principal.tenant_id,
    )
    rows.sort(key=lambda row: (row[1] != "critical", row[0].created_at, row[0].id))
    return [
        ReviewRead.model_validate(
            {
                **{
                    name: getattr(review, name)
                    for name in (
                        "id",
                        "job_id",
                        "thread_id",
                        "status",
                        "decision",
                        "decision_notes",
                        "created_at",
                    )
                },
                "priority": priority,
            }
        )
        for review, priority in rows
    ]


@router.post(
    "/reviews/{review_id}/decision",
    response_model=ReviewRead,
    tags=["reviews"],
)
async def decide_review(
    review_id: str,
    body: ReviewDecisionRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Database,
) -> ReviewRead:
    _reviewer(principal)
    _require_workflow_factory()
    review = await run_in_threadpool(
        repositories.get_review,
        session,
        principal.tenant_id,
        review_id,
    )
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    job = await run_in_threadpool(
        repositories.get_job,
        session,
        principal.tenant_id,
        review.job_id,
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status != "review_required":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job is not waiting for a review decision",
        )
    if review.status != "pending" and (
        review.status != body.decision or review.decision_notes != body.notes
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review has already been resolved with a different decision",
        )
    if review.status == "pending":
        decided = await run_in_threadpool(
            repositories.set_review_decision,
            session,
            principal.tenant_id,
            review_id,
            reviewer_id=principal.user_id,
            decision=body.decision,
            notes=body.notes,
        )
    else:
        decided = review
    if decided is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    try:
        await run_in_threadpool(
            resume_review.delay,
            decided.job_id,
            principal.tenant_id,
            decided.id,
            decided.reviewer_id or principal.user_id,
            decided.decision or body.decision,
            decided.decision_notes or body.notes,
        )
    except CeleryError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Review decision was saved but the workflow resume queue is unavailable",
        ) from exc
    redis = _redis(request)
    await publish_job_event(
        redis,
        decided.job_id,
        "review_decision",
        "Review decision recorded.",
    )
    job = await run_in_threadpool(
        repositories.get_job,
        session,
        principal.tenant_id,
        decided.job_id,
    )
    scorecard = job.scorecard_data if job is not None else None
    escalation = scorecard.get("escalation") if isinstance(scorecard, dict) else None
    priority = (
        "critical"
        if isinstance(escalation, dict) and escalation.get("priority") == "critical"
        else "normal"
    )
    return ReviewRead.model_validate(
        {
            "id": decided.id,
            "job_id": decided.job_id,
            "thread_id": decided.thread_id,
            "status": decided.status,
            "decision": decided.decision,
            "decision_notes": decided.decision_notes,
            "created_at": decided.created_at,
            "priority": priority,
        }
    )


@router.get("/factories", response_model=list[FactoryRead], tags=["factories"])
async def get_factories(principal: CurrentPrincipal, session: Database) -> list[FactoryRead]:
    factories = await run_in_threadpool(
        repositories.list_factories,
        session,
        principal.tenant_id,
    )
    return [FactoryRead.model_validate(factory) for factory in factories]


@router.get("/factories/{factory_id}", response_model=FactoryRead, tags=["factories"])
async def get_factory(
    factory_id: str,
    principal: CurrentPrincipal,
    session: Database,
) -> FactoryRead:
    factory = await run_in_threadpool(
        repositories.get_factory,
        session,
        principal.tenant_id,
        factory_id,
    )
    if factory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")
    return FactoryRead.model_validate(factory)


@router.get("/audit-events", response_model=list[AuditEventRead], tags=["audit"])
async def get_audit_events(
    principal: CurrentPrincipal,
    session: Database,
) -> list[AuditEventRead]:
    events = await run_in_threadpool(
        repositories.list_audit_events,
        session,
        principal.tenant_id,
    )
    return [AuditEventRead.model_validate(event) for event in events]


@router.get("/settings/live-lookup", response_model=LiveLookupSetting, tags=["settings"])
async def get_live_lookup(
    principal: CurrentPrincipal,
    session: Database,
) -> LiveLookupSetting:
    enabled = await run_in_threadpool(
        repositories.get_live_lookup_setting,
        session,
        principal.tenant_id,
    )
    if enabled is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return LiveLookupSetting(enabled=enabled)


@router.put("/settings/live-lookup", response_model=LiveLookupSetting, tags=["settings"])
async def update_live_lookup(
    body: LiveLookupSetting,
    principal: CurrentPrincipal,
    session: Database,
) -> LiveLookupSetting:
    _tenant_admin(principal)
    enabled = await run_in_threadpool(
        repositories.set_live_lookup_setting,
        session,
        principal.tenant_id,
        body.enabled,
    )
    if enabled is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return LiveLookupSetting(enabled=enabled)


@router.get(
    "/regulation-proposals",
    response_model=list[RegulationProposalRead],
    tags=["regulations"],
)
async def get_regulation_proposals(
    principal: CurrentPrincipal,
    session: Database,
) -> list[RegulationProposalRead]:
    proposals = await run_in_threadpool(
        repositories.list_pending_regulation_proposals,
        session,
        principal.tenant_id,
    )
    return [RegulationProposalRead.model_validate(proposal) for proposal in proposals]


@router.get("/integrations", response_model=list[IntegrationStatus], tags=["integrations"])
async def get_integrations(
    principal: CurrentPrincipal,
    session: Database,
) -> list[IntegrationStatus]:
    statuses = await run_in_threadpool(
        repositories.list_integration_status,
        session,
        principal.tenant_id,
    )
    return [IntegrationStatus.model_validate(item) for item in statuses]
