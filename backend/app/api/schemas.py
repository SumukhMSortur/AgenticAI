"""Typed request and response contracts for the versioned API."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    route: str
    assessment_date: date
    risk_score: float | None
    created_at: datetime
    updated_at: datetime


class JobDetail(JobRead):
    scorecard_data: dict[str, Any] | None


class ScorecardRead(BaseModel):
    job_id: str
    tenant_id: str
    assessment_date: date
    overall_status: Literal["compliant", "non_compliant", "review_required", "informational"]
    risk_score: float | None
    lines: list[dict[str, Any]]
    re_audit_recommended: bool
    summary: str
    escalation: dict[str, Any] | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doc_hash: str
    filename: str
    mime_type: str
    page_count: int
    created_at: datetime


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: str
    thread_id: str
    status: str
    decision: str | None
    decision_notes: str | None
    created_at: datetime
    priority: Literal["normal", "critical"]


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "more_evidence"]
    notes: str = Field(default="", max_length=4000)


class FactoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    country: str
    external_id: str | None


class FactoryRiskRead(BaseModel):
    factory_id: str
    job_id: str
    risk_score: float
    model_tag: Literal["lstm", "xgboost", "logreg"]
    baseline_comparison: dict[str, Any]
    created_at: datetime


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sequence: int
    event_type: str
    timestamp: datetime
    prompt_version: str | None
    verdicts: dict[str, Any] | None
    reviewer_decision: dict[str, Any] | None
    payload: dict[str, Any] | None
    prev_hash: str
    event_hash: str


class LiveLookupSetting(BaseModel):
    enabled: bool


class IntegrationStatus(BaseModel):
    source: str
    status: Literal["unverified", "disabled", "snapshot_only", "healthy", "unavailable"]
    live_enabled: bool
    as_of: datetime | None = None
    record_count: int = Field(default=0, ge=0)
    age_days: int | None = Field(default=None, ge=0)
    health: Literal["unverified", "healthy", "stale", "unavailable"] = "unverified"


class RegulationProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    detected_at: datetime
    candidate_version_id: str
    status: str


class RegulationProposalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: str = Field(default="", max_length=4000)


class RAGQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    assessment_date: date
    jurisdiction: str = Field(default="EU", min_length=2, max_length=8)
    top_k: int = Field(default=5, ge=1, le=10)


class RAGPassageRead(BaseModel):
    chunk_id: str
    text: str
    regulation_id: str
    version_id: str
    jurisdiction: str
    section_number: str
    score: float


class RAGQueryRead(BaseModel):
    supported: bool
    results: list[RAGPassageRead]
