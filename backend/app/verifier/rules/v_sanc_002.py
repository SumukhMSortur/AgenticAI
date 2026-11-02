"""V-SANC-002: escalate possible fuzzy sanctions matches for human review."""

from backend.app.domain.models import SanctionsMatch, Verdict
from backend.app.verifier.rules.common import make_verdict

_FUZZY_REVIEW_THRESHOLD = 0.75


def check(
    matches: list[SanctionsMatch] | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
    review_threshold: float = _FUZZY_REVIEW_THRESHOLD,
) -> Verdict:
    """Escalate fuzzy-name hits; exact hits are handled by V-SANC-001."""
    if not 0.0 <= review_threshold <= 1.0:
        raise ValueError("review_threshold must be between 0 and 1")
    if matches is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SANC-002",
            outcome="escalate",
            reason_code="SANCTIONS_EVIDENCE_MISSING",
            details={"rationale": "No sanctions snapshot result was supplied.", "priority": "critical"},
            evidence_ids=evidence_ids,
        )
    possible_matches = [
        match for match in matches
        if match.matched
        and match.match_type == "fuzzy_name"
        and match.score >= review_threshold
    ]
    if possible_matches:
        match = sorted(
            possible_matches,
            key=lambda item: (-item.score, item.source, item.record_key or ""),
        )[0]
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SANC-002",
            outcome="escalate",
            reason_code="SANCTIONS_POSSIBLE_FUZZY_MATCH",
            details={
                "source": match.source,
                "record_key": match.record_key,
                "match_score": match.score,
                "threshold": review_threshold,
                "snapshot_hash": match.snapshot_hash,
                "priority": "critical",
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-SANC-002",
        outcome="pass",
        reason_code="SANCTIONS_FUZZY_MATCH_NOT_FOUND",
        details={"sources_checked": sorted({match.source for match in matches})},
        evidence_ids=evidence_ids,
    )
