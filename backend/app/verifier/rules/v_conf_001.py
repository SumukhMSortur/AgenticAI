"""V-CONF-001: escalate when extraction confidence misses the risk-adjusted threshold."""

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    confidence: float,
    risk_score: float,
    base_threshold: float,
    moderate_threshold: float,
    high_threshold: float,
    moderate_risk_threshold: float,
    high_risk_threshold: float,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Select the configured confidence threshold for the supplied risk score."""
    values = (
        confidence,
        risk_score,
        base_threshold,
        moderate_threshold,
        high_threshold,
        moderate_risk_threshold,
        high_risk_threshold,
    )
    if any(not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("confidence and risk thresholds must be between 0 and 1")
    if moderate_risk_threshold > high_risk_threshold:
        raise ValueError("moderate risk threshold must not exceed high risk threshold")
    threshold = base_threshold
    if risk_score >= high_risk_threshold:
        threshold = high_threshold
    elif risk_score >= moderate_risk_threshold:
        threshold = moderate_threshold
    if confidence < threshold:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-CONF-001",
            outcome="escalate",
            reason_code="EXTRACTION_CONFIDENCE_BELOW_THRESHOLD",
            details={
                "rationale": "Extracted value confidence is below the risk-adjusted threshold.",
                "confidence": confidence,
                "required_confidence": threshold,
                "risk_score": risk_score,
                "priority": "critical" if risk_score >= high_risk_threshold else "normal",
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-CONF-001",
        outcome="pass",
        reason_code="EXTRACTION_CONFIDENCE_ACCEPTED",
        details={
            "rationale": "Extracted value confidence meets the risk-adjusted threshold.",
            "confidence": confidence,
            "required_confidence": threshold,
            "risk_score": risk_score,
        },
        evidence_ids=evidence_ids,
    )
