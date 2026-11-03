"""V-EXT-003: escalate when the matched facility has a different parent company."""

from backend.app.domain.models import ExternalLookup, Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    lookup: ExternalLookup | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Require parent-company provenance for a found facility."""
    if lookup is None or lookup.status != "healthy" or not lookup.matched:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-003",
            outcome="escalate",
            reason_code="EXTERNAL_PARENT_COMPANY_UNVERIFIED",
            details={"rationale": "No reliable parent-company relationship was supplied."},
            evidence_ids=evidence_ids,
        )
    if lookup.parent_company_match is not True:
        reason_code = (
            "EXTERNAL_PARENT_COMPANY_MISMATCH"
            if lookup.parent_company_match is False
            else "EXTERNAL_PARENT_COMPANY_UNVERIFIED"
        )
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-003",
            outcome="escalate",
            reason_code=reason_code,
            details={
                "source": lookup.source,
                "record_key": lookup.record_key,
                "parent_company_match": lookup.parent_company_match,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXT-003",
        outcome="pass",
        reason_code="EXTERNAL_PARENT_COMPANY_CONFIRMED",
        details={
            "source": lookup.source,
            "record_key": lookup.record_key,
        },
        evidence_ids=evidence_ids,
    )
