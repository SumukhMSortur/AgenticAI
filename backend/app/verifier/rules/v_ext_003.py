"""V-EXT-003: escalate when external facility matching relies on an uncertain name."""

from backend.app.domain.models import ExternalLookup, Verdict
from backend.app.verifier.rules.common import make_verdict

_MATCH_THRESHOLD = 0.90


def check(
    lookup: ExternalLookup | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
    confirmed_match_threshold: float = _MATCH_THRESHOLD,
) -> Verdict:
    """Accept strong exact or fuzzy evidence; do not silently accept weak matches."""
    if not 0.0 <= confirmed_match_threshold <= 1.0:
        raise ValueError("confirmed_match_threshold must be between 0 and 1")
    if lookup is None or not lookup.matched:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-003",
            outcome="escalate",
            reason_code="EXTERNAL_FACILITY_MATCH_UNCONFIRMED",
            details={"rationale": "No matched external facility record was supplied."},
            evidence_ids=evidence_ids,
        )
    if lookup.match_type == "exact_id" or (
        lookup.match_type == "exact_name" and lookup.score >= confirmed_match_threshold
    ):
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-003",
            outcome="pass",
            reason_code="EXTERNAL_FACILITY_MATCH_CONFIRMED",
            details={
                "match_type": lookup.match_type,
                "match_score": lookup.score,
                "threshold": confirmed_match_threshold,
                "record_key": lookup.record_key,
            },
            evidence_ids=evidence_ids,
        )
    if lookup.match_type == "fuzzy_name" and lookup.score >= confirmed_match_threshold:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-003",
            outcome="pass",
            reason_code="EXTERNAL_FACILITY_FUZZY_MATCH_CONFIRMED",
            details={
                "match_type": lookup.match_type,
                "match_score": lookup.score,
                "threshold": confirmed_match_threshold,
                "record_key": lookup.record_key,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXT-003",
        outcome="escalate",
        reason_code="EXTERNAL_FACILITY_MATCH_UNCERTAIN",
        details={
            "match_type": lookup.match_type,
            "match_score": lookup.score,
            "threshold": confirmed_match_threshold,
        },
        evidence_ids=evidence_ids,
    )
