"""Durable job and human-review graph tasks."""

from __future__ import annotations

import importlib
import json
import logging
import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any, Literal, cast

from pydantic import BaseModel
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Document, Job, JobDocument, Review
from backend.app.db.session import SessionLocal
from backend.app.domain.models import DocumentRef, GraphState, RiskForecast, Scorecard
from backend.app.graph.workflow import (
    ReviewDecision,
    WorkflowServices,
    build_workflow,
    load_graph_settings,
    postgres_checkpointer,
    resume_workflow,
)
from backend.app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_RELEASE_LOCK = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def _workflow_services() -> WorkflowServices:
    factory_path = settings.WORKFLOW_SERVICES_FACTORY
    if not factory_path:
        raise RuntimeError(
            "WORKFLOW_SERVICES_FACTORY must name the production WorkflowServices factory"
        )
    module_name, separator, attribute_name = factory_path.partition(":")
    if not separator:
        module_name, separator, attribute_name = factory_path.rpartition(".")
    if not module_name or not attribute_name:
        raise ValueError("WORKFLOW_SERVICES_FACTORY must use 'module:factory' or 'module.factory'")
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute_name)
    if not callable(factory):
        raise TypeError("configured workflow services factory is not callable")
    services = factory()
    if not isinstance(services, WorkflowServices):
        raise TypeError("configured factory must return WorkflowServices")
    return services


def _publish(
    redis: Redis,
    job_id: str,
    event_type: str,
    summary: str,
    *,
    step: str | None = None,
) -> None:
    data: dict[str, str] = {
        "job_id": job_id,
        "event_type": event_type,
        "summary": summary,
    }
    if step is not None:
        data["step"] = step
    redis.xadd(
        f"ecochain:job:{job_id}:events",
        {"event_type": event_type, "data": json.dumps(data, separators=(",", ":"))},
        maxlen=1000,
        approximate=True,
    )


def _tenant_job(session: Session, job_id: str, tenant_id: str) -> Job | None:
    return session.scalar(select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id))


def _job_documents(
    session: Session,
    tenant_id: str,
    job_id: str,
) -> list[DocumentRef]:
    rows = session.execute(
        select(Document)
        .join(JobDocument, JobDocument.document_id == Document.id)
        .where(
            JobDocument.job_id == job_id,
            JobDocument.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
        )
        .order_by(Document.doc_hash)
    ).scalars()
    return [
        DocumentRef(
            doc_id=document.id,
            doc_hash=document.doc_hash,
            filename=document.filename,
            page_count=document.page_count,
            mime_type=document.mime_type,
        )
        for document in rows
    ]


def _scorecard_payload(values: Mapping[str, Any]) -> dict[str, Any] | None:
    scorecard = values.get("scorecard")
    if isinstance(scorecard, Scorecard):
        payload = scorecard.model_dump(mode="json")
    elif isinstance(scorecard, dict):
        payload = dict(scorecard)
    else:
        return None
    escalation = values.get("escalation")
    if isinstance(escalation, BaseModel):
        payload["escalation"] = escalation.model_dump(mode="json")
    elif isinstance(escalation, dict):
        payload["escalation"] = escalation
    risk = values.get("risk")
    if isinstance(risk, RiskForecast):
        payload["risk_forecast"] = risk.model_dump(mode="json")
    elif isinstance(risk, dict):
        payload["risk_forecast"] = risk
    return payload


def _run_graph(
    job: Job,
    documents: list[DocumentRef],
    redis: Redis,
    *,
    review_decision: ReviewDecision | None = None,
) -> tuple[Mapping[str, Any], bool]:
    services = _workflow_services()
    graph_settings = load_graph_settings()
    with postgres_checkpointer(settings.DATABASE_URL) as checkpointer:
        graph = build_workflow(
            services,
            checkpointer=checkpointer,
            settings=graph_settings,
        )
        config: dict[str, Any] = {
            "configurable": {"thread_id": job.thread_id},
            "recursion_limit": graph_settings.recursion_limit,
        }
        if review_decision is not None:
            result = resume_workflow(
                graph,
                thread_id=job.thread_id,
                decision=review_decision,
                settings=graph_settings,
            )
            for step in result.get("step_counts", {}):
                _publish(redis, job.id, "step", f"Workflow step '{step}' completed.", step=step)
        else:
            initial_state: GraphState = {
                "job_id": job.id,
                "tenant_id": job.tenant_id,
                "thread_id": job.thread_id,
                "assessment_date": date.fromisoformat(job.assessment_date),
                "query": job.query,
                "documents": documents,
                "step_counts": {},
            }
            for update in graph.stream(
                initial_state,
                config=config,
                stream_mode="updates",
            ):
                if not isinstance(update, Mapping):
                    raise TypeError("workflow emitted an invalid update")
                for node_name in update:
                    if node_name == "__interrupt__":
                        _publish(
                            redis,
                            job.id,
                            "review_required",
                            "Workflow requires human review.",
                        )
                    else:
                        step = str(node_name)
                        _publish(
                            redis,
                            job.id,
                            "step",
                            f"Workflow step '{step}' completed.",
                            step=step,
                        )
            snapshot = graph.get_state(config)
            result = snapshot.values
        snapshot = graph.get_state(config)
        paused = any(getattr(task, "interrupts", ()) for task in snapshot.tasks)
        return result, paused


def _save_job_result(
    session: Session,
    job: Job,
    values: Mapping[str, Any],
    paused: bool,
) -> None:
    payload = _scorecard_payload(values)
    job.scorecard_data = payload
    if payload is not None and isinstance(payload.get("risk_score"), (int, float)):
        job.risk_score = float(payload["risk_score"])
    job.status = "review_required" if paused else "completed"
    if paused:
        existing = session.scalar(
            select(Review).where(
                Review.tenant_id == job.tenant_id,
                Review.thread_id == job.thread_id,
                Review.status == "pending",
            )
        )
        if existing is None:
            session.add(
                Review(
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    thread_id=job.thread_id,
                    status="pending",
                )
            )
    session.commit()


def _mark_failed(job_id: str, tenant_id: str) -> None:
    with SessionLocal() as session:
        job = _tenant_job(session, job_id, tenant_id)
        if job is not None:
            job.status = "failed"
            session.commit()


def _run_job(job_id: str, tenant_id: str, *, resume: ReviewDecision | None = None) -> str:
    lock_value = uuid.uuid4().hex
    lock_key = f"ecochain:job:{tenant_id}:{job_id}:worker-lock"
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        acquired = redis.set(lock_key, lock_value, nx=True, ex=3600)
    except RedisError:
        redis.close()
        logger.exception("Worker could not acquire the job lock; job was not started")
        raise
    if not acquired:
        redis.close()
        return "already_running"

    try:
        with SessionLocal() as session:
            job = _tenant_job(session, job_id, tenant_id)
            if job is None:
                raise LookupError("Job does not exist for the requested tenant")
            if job.status in {"completed", "failed"}:
                return "already_finished"
            if resume is None and job.status == "review_required":
                return "awaiting_review"
            documents = _job_documents(session, tenant_id, job_id)
            if not documents:
                raise ValueError("Job has no tenant-owned documents")
            job.status = "processing"
            session.commit()
            session.refresh(job)
            _publish(redis, job.id, "started", "Workflow started.")
            values, paused = _run_graph(
                job,
                documents,
                redis,
                review_decision=resume,
            )
            _save_job_result(session, job, values, paused)
            terminal_event = "review_required" if paused else "completed"
            summary = "Workflow paused for human review." if paused else "Workflow completed."
            _publish(redis, job.id, terminal_event, summary)
            return terminal_event
    except Exception:
        try:
            _mark_failed(job_id, tenant_id)
        except SQLAlchemyError:
            logger.exception("Worker could not persist the failed state for job %s", job_id)
        try:
            _publish(redis, job_id, "failed", "Workflow failed; inspect worker logs.")
        except RedisError:
            logger.exception("Worker could not publish the failure event for job %s", job_id)
        logger.exception("Workflow task failed for job %s", job_id)
        raise
    finally:
        try:
            redis.eval(_RELEASE_LOCK, 1, lock_key, lock_value)
        except RedisError:
            logger.exception("Worker could not release the Redis lock for job %s", job_id)
        finally:
            redis.close()


@celery_app.task(name="ecochain.process_job")  # type: ignore[untyped-decorator]
def process_job(job_id: str, tenant_id: str) -> str:
    """Run a new job on the durable PostgreSQL-backed graph."""
    return _run_job(job_id, tenant_id)


@celery_app.task(name="ecochain.resume_review")  # type: ignore[untyped-decorator]
def resume_review(
    job_id: str,
    tenant_id: str,
    review_id: str,
    reviewer_id: str,
    decision: str,
    notes: str,
) -> str:
    """Resume one paused graph after a tenant-authorized human decision."""
    with SessionLocal() as session:
        job = _tenant_job(session, job_id, tenant_id)
        review = session.scalar(
            select(Review).where(
                Review.id == review_id,
                Review.tenant_id == tenant_id,
                Review.job_id == job_id,
            )
        )
        if job is None or review is None or review.status != decision:
            raise LookupError("Review decision does not match the tenant-owned job")
        if job.status != "review_required":
            raise ValueError("Job is not paused for review")
    if decision not in {"approved", "rejected", "more_evidence"}:
        raise ValueError("Unsupported review decision")
    validated_decision = ReviewDecision(
        reviewer_id=reviewer_id,
        decision=cast(Literal["approved", "rejected", "more_evidence"], decision),
        notes=notes,
    )
    return _run_job(job_id, tenant_id, resume=validated_decision)
