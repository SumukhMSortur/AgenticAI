"""V-DATE-001: malformed certificate validity range requires escalation."""

from datetime import date

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    valid_from: date | None,
    valid_to: date | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
    unparsable: bool = False,
) -> Verdict:
    """Escalate incomplete or impossible dates; pass a well-ordered range."""
    if unparsable:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-DATE-001",
            outcome="escalate",
            reason_code="VALIDITY_DATE_UNPARSABLE",
            details={"rationale": "A validity date could not be parsed.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    if valid_from is None or valid_to is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-DATE-001",
            outcome="escalate",
            reason_code="VALIDITY_DATE_MISSING",
            details={"rationale": "One or both validity dates are missing.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    if valid_from > valid_to:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-DATE-001",
            outcome="escalate",
            reason_code="VALIDITY_DATE_RANGE_INVALID",
            details={
                "rationale": "The validity start date is after the end date.",
                "valid_from": valid_from.isoformat(),
                "valid_to": valid_to.isoformat(),
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-DATE-001",
        outcome="pass",
        reason_code="VALIDITY_DATE_RANGE_VALID",
        details={
            "rationale": "The validity date range is logically consistent.",
            "valid_from": valid_from.isoformat(),
            "valid_to": valid_to.isoformat(),
            "confidence": 1.0,
        },
        evidence_ids=evidence_ids,
    )
