"""V-EXP-002: escalate certificates expiring within a warning window."""

from datetime import date, timedelta

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    cert_valid_to: date | None,
    assessment_date: date | None,
    warning_days: int,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Evaluate near-expiry status using explicit configuration and inputs."""
    if warning_days < 0:
        raise ValueError("warning_days must be non-negative")
    if cert_valid_to is None or assessment_date is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXP-002",
            outcome="escalate",
            reason_code="EXPIRY_WARNING_DATE_MISSING",
            details={"rationale": "A required date is missing.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    warn_threshold = assessment_date + timedelta(days=warning_days)
    if assessment_date <= cert_valid_to <= warn_threshold:
        days_left = (cert_valid_to - assessment_date).days
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXP-002",
            outcome="escalate",
            reason_code="CERTIFICATE_NEAR_EXPIRY",
            details={
                "rationale": "The certificate expires within the warning window.",
                "valid_to": cert_valid_to.isoformat(),
                "days_left": days_left,
                "warning_days": warning_days,
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXP-002",
        outcome="pass",
        reason_code="CERTIFICATE_OUTSIDE_EXPIRY_WARNING",
        details={
            "rationale": "The certificate is outside the expiry warning window.",
            "valid_to": cert_valid_to.isoformat(),
            "warning_days": warning_days,
            "confidence": 1.0,
        },
        evidence_ids=evidence_ids,
    )
