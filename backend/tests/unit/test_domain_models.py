"""Unit tests for Phase 1 domain contracts and schemas."""

from datetime import date

import pytest
from pydantic import ValidationError

from backend.app.domain.models import (
    BBox,
    Claim,
    EvidenceItem,
    ExtractedField,
    RiskForecast,
    Scorecard,
    ScorecardLine,
    Verdict,
)


def test_bbox_valid() -> None:
    """Valid bounding box should succeed."""
    box = BBox(x0=100, y0=200, x1=500, y1=600)
    assert box.x0 == 100
    assert box.y1 == 600


def test_bbox_invalid_coordinates() -> None:
    """BBox with inverted coordinates or out of range must fail validation."""
    with pytest.raises(ValidationError):
        BBox(x0=500, y0=200, x1=100, y1=600)  # x1 < x0

    with pytest.raises(ValidationError):
        BBox(x0=100, y0=600, x1=500, y1=200)  # y1 < y0

    with pytest.raises(ValidationError):
        BBox(x0=-10, y0=0, x1=500, y1=500)  # negative coordinate

    with pytest.raises(ValidationError):
        BBox(x0=0, y0=0, x1=1050, y1=500)  # coordinate > 1000


def test_extracted_field() -> None:
    """Extracted field must retain metadata and confidence score."""
    field = ExtractedField(
        name="valid_to",
        value="2026-12-31",
        doc_id="doc_123",
        doc_hash="abc" * 21 + "a",
        page=1,
        bbox=BBox(x0=50, y0=50, x1=200, y1=80),
        confidence=0.98,
    )
    assert field.confidence == 0.98
    assert field.page == 1


def test_claim_and_verdict() -> None:
    """Claim and Verdict contracts must validate fields correctly."""
    claim = Claim(
        claim_id="CLM-001",
        claim_text="GOTS Organic Certification valid",
        doc_id="doc_001",
        doc_hash="hash_001",
        page=1,
        extractor_confidence=0.92,
        evidence_ids=["EV-001"],
    )
    assert claim.claim_id == "CLM-001"
    assert len(claim.evidence_ids) == 1

    verdict = Verdict(
        claim_id="CLM-001",
        rule_id="V-EXP-001",
        outcome="pass",
        reason_code="CERT_ACTIVE",
        details={"expiry": "2027-01-01"},
    )
    assert verdict.outcome == "pass"


def test_risk_forecast_and_scorecard() -> None:
    """RiskForecast and Scorecard contracts validation."""
    forecast = RiskForecast(
        factory_id="FACT-01",
        p_fail_6m=0.25,
        model_tag="lstm",
        baseline_comparison={"lstm_brier": 0.12, "baseline_brier": 0.18},
    )
    assert forecast.p_fail_6m == 0.25

    with pytest.raises(ValidationError):
        RiskForecast(
            factory_id="FACT-01",
            p_fail_6m=1.5,  # must be <= 1.0
            model_tag="lstm",
        )

    scorecard = Scorecard(
        job_id="job_001",
        tenant_id="tenant_001",
        assessment_date=date(2026, 11, 2),
        overall_status="compliant",
        risk_score=0.25,
        lines=[
            ScorecardLine(
                claim=Claim(
                    claim_id="C1",
                    claim_text="Valid GOTS cert",
                    doc_id="d1",
                    doc_hash="h1",
                    page=1,
                    extractor_confidence=0.95,
                    evidence_ids=["E1"],
                ),
                verdict=Verdict(
                    claim_id="C1",
                    rule_id="V-EXP-001",
                    outcome="pass",
                    reason_code="VALID",
                ),
                evidence=[
                    EvidenceItem(
                        evidence_id="E1",
                        kind="extracted_field",
                        ref={"field": "valid_to", "value": "2027-05-01"},
                    )
                ],
            )
        ],
    )
    assert scorecard.overall_status == "compliant"
    assert len(scorecard.lines) == 1
