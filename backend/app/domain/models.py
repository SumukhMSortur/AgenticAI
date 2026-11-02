"""Domain contracts and state schemas for EcoChain Copilot."""

from datetime import date, datetime
from operator import add
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator


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

    source: str
    fetched_at: datetime
    snapshot_hash: str
    record_key: str


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
        # When kind indicates external provenance, verify ExternalRef shape
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


class GraphState(TypedDict):
    """Typed LangGraph state schema with append-only accumulation reducers."""

    job_id: str
    tenant_id: str
    thread_id: str
    assessment_date: date
    route: Literal["retrieval_only", "full_analysis", "out_of_scope"]
    documents: list[DocumentRef]
    redacted_pages: list[RedactedPage]
    fields: Annotated[list[ExtractedField], add]
    evidence: Annotated[list[EvidenceItem], add]
    claims: Annotated[list[Claim], add]
    verdicts: Annotated[list[Verdict], add]
    risk: RiskForecast | None
    escalation: EscalationState | None
    scorecard: Scorecard | None
    step_counts: dict[str, int]
