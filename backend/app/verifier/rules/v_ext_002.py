"""V-EXT-002: escalate facility country mismatches and ambiguous name matches."""

from backend.app.domain.models import ExternalLookup, Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    lookup: ExternalLookup | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
    name_review_min: float = 0.75,
    name_review_max: float = 0.90,
) -> Verdict:
    """Check a found facility's country and name confidence."""
    if not 0.0 <= name_review_min <= name_review_max <= 1.0:
        raise ValueError("name review thresholds must be ordered within 0 and 1")
    if lookup is None or lookup.status != "healthy":
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-002",
            outcome="escalate",
            reason_code="EXTERNAL_FACILITY_DATA_UNAVAILABLE",
            details={"rationale": "Facility match details are unavailable."},
            evidence_ids=evidence_ids,
        )
    if not lookup.matched:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-002",
            outcome="pass",
            reason_code="EXTERNAL_FACILITY_MATCH_NOT_APPLICABLE",
            details={"rationale": "V-EXT-001 handles the unmatched facility."},
            evidence_ids=evidence_ids,
        )
    if lookup.country_match is not True:
        reason_code = (
            "EXTERNAL_FACILITY_COUNTRY_MISMATCH"
            if lookup.country_match is False
            else "EXTERNAL_FACILITY_COUNTRY_UNVERIFIED"
        )
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-002",
            outcome="escalate",
            reason_code=reason_code,
            details={
                "source": lookup.source,
                "country_match": lookup.country_match,
                "match_score": lookup.score,
            },
            evidence_ids=evidence_ids,
        )
    if (
        lookup.match_type == "fuzzy_name"
        and name_review_min <= lookup.score <= name_review_max
    ):
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-002",
            outcome="escalate",
            reason_code="EXTERNAL_FACILITY_NAME_AMBIGUOUS",
            details={
                "source": lookup.source,
                "match_score": lookup.score,
                "review_thresholds": [name_review_min, name_review_max],
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXT-002",
        outcome="pass",
        reason_code="EXTERNAL_FACILITY_COUNTRY_AND_NAME_CONFIRMED",
        details={"source": lookup.source, "match_score": lookup.score},
        evidence_ids=evidence_ids,
    )
