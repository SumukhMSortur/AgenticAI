"""V-EXP-001: fail when a certificate expired before the assessment date."""

from datetime import date

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    cert_valid_to: date | None,
    assessment_date: date | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Fail expired certificates and escalate when either date is unavailable."""
    if cert_valid_to is None or assessment_date is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXP-001",
            outcome="escalate",
            reason_code="EXPIRY_DATE_MISSING",
            details={"rationale": "A required date is missing.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    if cert_valid_to < assessment_date:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXP-001",
            outcome="fail",
            reason_code="CERTIFICATE_EXPIRED",
            details={
                "rationale": "The certificate expired before the assessment date.",
                "valid_to": cert_valid_to.isoformat(),
                "assessment_date": assessment_date.isoformat(),
                "days_expired": (assessment_date - cert_valid_to).days,
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXP-001",
        outcome="pass",
        reason_code="CERTIFICATE_NOT_EXPIRED",
        details={
            "rationale": "The certificate is valid on the assessment date.",
            "valid_to": cert_valid_to.isoformat(),
            "assessment_date": assessment_date.isoformat(),
            "confidence": 1.0,
        },
        evidence_ids=evidence_ids,
    )
