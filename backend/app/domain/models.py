"""Domain contracts and state schemas for EcoChain Copilot."""

from datetime import date, datetime
from operator import add
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator
from typing_extensions import TypedDict


class BBox(BaseModel):
    """Normalized bounding box coordinates in 0-1000 space (LayoutLM convention)."""

    x0: int = Field(ge=0, le=1000)
    y0: int = Field(ge=0, le=1000)
    x1: int = Field(ge=0, le=1000)
    y1: int = Field(ge=0, le=1000)

    @field_validator("x1")
    @classmethod
    def validate_x_order(cls, v: int, info: Any) -> int:
        if "x0" in info.data and v < info.data["x0"]:
            raise ValueError("x1 must be greater than or equal to x0")
        return v

    @field_validator("y1")
    @classmethod
    def validate_y_order(cls, v: int, info: Any) -> int:
        if "y0" in info.data and v < info.data["y0"]:
            raise ValueError("y1 must be greater than or equal to y0")
        return v


class ExtractedField(BaseModel):
    """Structured field extracted from a document page with spatial provenance."""

    name: str
    value: str | list[str] | date | None = None
    doc_id: str
    doc_hash: str
    page: int = Field(ge=1)
    bbox: BBox | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ExternalRef(BaseModel):
    """Provenance pointer for an external registry record, watchlist hit, or regulatory feed."""

    source: str = Field(min_length=1)
    fetched_at: datetime
    snapshot_hash: str = Field(min_length=1)
    record_key: str = Field(min_length=1)


class ExternalSnapshotRecord(BaseModel):
    """A normalized record from an immutable external-data snapshot."""

    record_key: str
    normalized_name: str
    country: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ExternalSnapshot(BaseModel):
    """Snapshot provenance and records supplied to local-only verification."""

    source: str
    fetched_at: datetime
    snapshot_hash: str
    records: list[ExternalSnapshotRecord] = Field(default_factory=list)


class ExternalLookup(BaseModel):
    """Result of a provider lookup, detached from provider/network behavior."""

    source: str
    status: Literal["healthy", "degraded", "unavailable"]
    matched: bool
    match_type: Literal["exact_id", "exact_name", "fuzzy_name", "none"]
    score: float = Field(ge=0.0, le=1.0)
    record_key: str | None = None
    fetched_at: datetime | None = None
    snapshot_hash: str | None = None
    country_match: bool | None = None
    parent_company_match: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SanctionsMatch(BaseModel):
    """Local sanctions-list match result and snapshot provenance."""

    source: str
    matched: bool
    match_type: Literal["exact_id", "exact_name", "fuzzy_name", "none"]
    score: float = Field(ge=0.0, le=1.0)
    record_key: str | None = None
    snapshot_hash: str


class VerificationContext(BaseModel):
    """Vault-mapped job context needed by deterministic verifier rules."""

    assessment_date: date
    fields_by_claim: dict[str, dict[str, Any]] = Field(default_factory=dict)
    page_claims_by_doc: dict[str, list[str]] = Field(default_factory=dict)
    page_counts_by_doc: dict[str, int] = Field(default_factory=dict)
    materials_by_doc: dict[str, list[str]] = Field(default_factory=dict)
    supplier_ids_by_doc: dict[str, str] = Field(default_factory=dict)
    facility_ids_by_doc: dict[str, str] = Field(default_factory=dict)
    facility_names_by_doc: dict[str, str] = Field(default_factory=dict)
    certificate_doc_by_claim: dict[str, str] = Field(default_factory=dict)
    bom_doc_by_claim: dict[str, str] = Field(default_factory=dict)
    external_lookups_by_claim: dict[str, ExternalLookup] = Field(default_factory=dict)
    sanctions_matches_by_claim: dict[str, list[SanctionsMatch]] = Field(default_factory=dict)
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)


class EvidenceItem(BaseModel):
    """Verifiable reference pointer supporting a compliance claim. Never contains raw PII."""

    evidence_id: str
    kind: Literal[
        "extracted_field",
        "regulation_passage",
        "registry_entry",
        "audit_forecast",
        "external_record",
        "watchlist_hit",
        "regulation_update",
    ]
    ref: dict[str, Any]

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, v: dict[str, Any], _info: Any) -> dict[str, Any]:
        """Validates that external evidence items contain required provenance reference keys."""
        if _info.data.get("kind") in {
            "external_record",
            "watchlist_hit",
            "regulation_update",
        }:
            ExternalRef.model_validate(v)
        return v


class Claim(BaseModel):
    """Compliance claim made by or extracted from supplier documentation."""

    claim_id: str
    claim_text: str
    doc_id: str
    doc_hash: str
    page: int = Field(ge=1)
    bbox: BBox | None = None
    extractor_confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    regulation_id: str | None = None
    regulation_version: str | None = None


class Verdict(BaseModel):
    """Deterministic outcome produced by the Verifier engine."""

    claim_id: str
    rule_id: str
    outcome: Literal["pass", "fail", "escalate"]
    reason_code: str
    details: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class RiskForecast(BaseModel):
    """Calibrated six-month audit failure probability forecast."""

    factory_id: str
    p_fail_6m: float = Field(ge=0.0, le=1.0)
    model_tag: Literal["lstm", "xgboost", "logreg"]
    baseline_comparison: dict[str, Any] = Field(default_factory=dict)


class DocumentRef(BaseModel):
    """Reference metadata for an uploaded document."""

    doc_id: str
    doc_hash: str
    filename: str
    page_count: int = Field(ge=1)
    mime_type: str = "application/pdf"


class RedactedPage(BaseModel):
    """Redacted representation of a single document page."""

    page: int = Field(ge=1)
    doc_id: str
    redacted_text: str
    bbox_map: list[dict[str, Any]] = Field(default_factory=list)


class EscalationState(BaseModel):
    """State tracking for Human-In-The-Loop escalation."""

    is_escalated: bool = False
    priority: Literal["normal", "critical"] = "normal"
    reason: str = ""
    triggered_by_rule: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ScorecardLine(BaseModel):
    """Single evidenced and verified row in the compliance scorecard."""

    claim: Claim
    verdict: Verdict
    evidence: list[EvidenceItem] = Field(default_factory=list)


class Scorecard(BaseModel):
    """Complete compliance scorecard for an assessment job."""

    job_id: str
    tenant_id: str
    assessment_date: date
    overall_status: Literal["compliant", "non_compliant", "review_required"]
    risk_score: float = Field(ge=0.0, le=1.0)
    lines: list[ScorecardLine] = Field(default_factory=list)
    re_audit_recommended: bool = False
    summary: str = ""


def merge_step_counts(
    current: dict[str, int], update: dict[str, int]
) -> dict[str, int]:
    """Accumulate successful node executions without discarding prior counters."""
    merged = dict(current)
    for node, count in update.items():
        if count < 0:
            raise ValueError("step-count increments must not be negative")
        merged[node] = merged.get(node, 0) + count
    return merged


class GraphState(TypedDict, total=False):
    """Typed LangGraph state schema with append-only accumulation reducers."""

    job_id: str
    tenant_id: str
    thread_id: str
    assessment_date: date
    query: str
    route: Literal["retrieval_only", "full_analysis", "out_of_scope"]
    intent: str
    documents: list[DocumentRef]
    redacted_pages: Annotated[list[RedactedPage], add]
    fields: Annotated[list[ExtractedField], add]
    evidence: Annotated[list[EvidenceItem], add]
    claims: Annotated[list[Claim], add]
    verdicts: Annotated[list[Verdict], add]
    risk: RiskForecast | None
    escalation: EscalationState | None
    scorecard: Scorecard | None
    verification_context: VerificationContext
    retrieved_context: Annotated[list[dict[str, Any]], add]
    review_decision: dict[str, str] | None
    explanation: str
    prompt_version: str
    audit_event_id: str
    audit_events: Annotated[list[dict[str, Any]], add]
    step_counts: Annotated[dict[str, int], merge_step_counts]
