"""Authenticated, tenant-scoped HTTP endpoints."""

from datetime import date
from pathlib import Path
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
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordRequestForm
from redis.asyncio import Redis
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from backend.app.api import repositories
from backend.app.api.document_pages import render_pdf_page
from backend.app.api.events import publish_job_event, stream_job_events, validate_stream_id
from backend.app.api.rate_limit import enforce_rate_limit
from backend.app.api.schemas import (
    AuditEventRead,
    DocumentRead,
    FactoryRead,
    FactoryRiskRead,
    IntegrationStatus,
    JobDetail,
    JobRead,
    LiveLookupSetting,
    RAGQueryRead,
    RAGQueryRequest,
    RegulationProposalDecisionRequest,
    RegulationProposalRead,
    ReviewDecisionRequest,
    ReviewRead,
    ScorecardRead,
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
from backend.app.rag.ingestion import RegulationIngestionManager
from backend.app.rag.query_service import (
    get_regulation_query_service,
    get_regulation_vector_store,
)
from backend.app.workers.tasks import process_job, resume_review

router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(enforce_rate_limit)],
)

Database = Annotated[Session, Depends(get_db)]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    job = await run_in_threadpool(repositories.get_job, session, principal.tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobDetail.model_validate(job)


@router.get("/jobs/{job_id}/scorecard", response_model=ScorecardRead, tags=["jobs"])
async def get_job_scorecard(
    job_id: str,
    principal: CurrentPrincipal,
    session: Database,
) -> ScorecardRead:
    job = await run_in_threadpool(repositories.get_job, session, principal.tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.scorecard_data is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Scorecard is not available until workflow processing completes",
        )
    return ScorecardRead.model_validate(job.scorecard_data)


@router.get("/jobs/{job_id}/documents", response_model=list[DocumentRead], tags=["documents"])
async def get_job_documents(
    job_id: str,
    principal: CurrentPrincipal,
    session: Database,
) -> list[DocumentRead]:
    job = await run_in_threadpool(repositories.get_job, session, principal.tenant_id, job_id)
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


@router.get(
    "/documents/{document_id}/pages/{page_number}.png",
    tags=["documents"],
    responses={200: {"content": {"image/png": {}}}, 304: {"description": "Not modified"}},
)
async def get_document_page(
    document_id: str,
    page_number: int,
    principal: CurrentPrincipal,
    session: Database,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
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
    if page_number < 1 or page_number > document.page_count:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document page not found",
        )

    etag = f'"{document.doc_hash}-page-{page_number}-scale-2"'
    if if_none_match is not None and (
        "*" in {value.strip() for value in if_none_match.split(",")}
        or etag in {value.strip() for value in if_none_match.split(",")}
    ):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    upload_root = settings.UPLOAD_DIRECTORY
    if not upload_root.is_absolute():
        upload_root = _PROJECT_ROOT / upload_root
    try:
        content = await run_in_threadpool(
            render_pdf_page,
            document.storage_path,
            upload_root,
            principal.tenant_id,
            page_number,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored document file is unavailable",
        ) from exc
    except IndexError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document page not found",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored document path is outside the tenant upload directory",
        ) from exc
    return Response(
        content=content,
        media_type="image/png",
        headers={"ETag": etag, "Cache-Control": "private, max-age=300"},
    )


@router.get("/jobs/{job_id}/events", tags=["jobs"])
async def get_job_events(
    job_id: str,
    request: Request,
    principal: CurrentPrincipal,
    session: Database,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    job = await run_in_threadpool(repositories.get_job, session, principal.tenant_id, job_id)
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


@router.get(
    "/factories/{factory_id}/risk",
    response_model=FactoryRiskRead,
    tags=["factories"],
)
async def get_factory_risk(
    factory_id: str,
    principal: CurrentPrincipal,
    session: Database,
) -> FactoryRiskRead:
    risk = await run_in_threadpool(
        repositories.get_factory_risk,
        session,
        principal.tenant_id,
        factory_id,
    )
    if risk is None:
        factory = await run_in_threadpool(
            repositories.get_factory,
            session,
            principal.tenant_id,
            factory_id,
        )
        if factory is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Factory not found",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No risk forecast is available for this factory",
        )
    return FactoryRiskRead.model_validate(risk)


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


@router.post(
    "/regulation-proposals/{proposal_id}/decision",
    response_model=RegulationProposalRead,
    tags=["regulations"],
)
async def decide_regulation_proposal(
    proposal_id: str,
    body: RegulationProposalDecisionRequest,
    principal: CurrentPrincipal,
    session: Database,
) -> RegulationProposalRead:
    _reviewer(principal)
    proposal = await run_in_threadpool(
        repositories.get_regulation_proposal,
        session,
        principal.tenant_id,
        proposal_id,
    )
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regulation proposal not found",
        )
    if proposal.status != "pending":
        if proposal.status != body.decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Regulation proposal has already been resolved",
            )
        return RegulationProposalRead.model_validate(proposal)

    if body.decision == "rejected":
        try:
            await run_in_threadpool(
                repositories.reject_regulation_proposal,
                session,
                principal.tenant_id,
                proposal_id,
                reviewer_id=principal.user_id,
                notes=body.notes,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
    else:
        store = await run_in_threadpool(get_regulation_vector_store)
        manager = RegulationIngestionManager(store=store, db=session)
        try:
            await run_in_threadpool(
                manager.approve_and_ingest,
                proposal_id,
                principal.user_id,
                tenant_id=principal.tenant_id,
                notes=body.notes,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    decided = await run_in_threadpool(
        repositories.get_regulation_proposal,
        session,
        principal.tenant_id,
        proposal_id,
    )
    if decided is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Regulation proposal not found",
        )
    return RegulationProposalRead.model_validate(decided)


@router.post("/query", response_model=RAGQueryRead, tags=["regulations"])
async def query_regulations(
    body: RAGQueryRequest,
    _principal: CurrentPrincipal,
) -> RAGQueryRead:
    query = body.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query must not be blank",
        )
    service = await run_in_threadpool(get_regulation_query_service)
    supported, results = await run_in_threadpool(
        service.query,
        query,
        body.assessment_date,
        body.jurisdiction,
        body.top_k,
    )
    return RAGQueryRead.model_validate({"supported": supported, "results": results})


@router.get("/integrations", response_model=list[IntegrationStatus], tags=["integrations"])
@router.get(
    "/integrations/status",
    response_model=list[IntegrationStatus],
    tags=["integrations"],
)
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
