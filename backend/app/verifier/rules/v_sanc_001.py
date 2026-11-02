"""V-SANC-001: fail closed on exact sanctions-list matches."""

from backend.app.domain.models import SanctionsMatch, Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    matches: list[SanctionsMatch] | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Fail on exact identifier/name matches; missing source results escalate."""
    if matches is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SANC-001",
            outcome="escalate",
            reason_code="SANCTIONS_EVIDENCE_MISSING",
            details={"rationale": "No sanctions snapshot result was supplied.", "priority": "critical"},
            evidence_ids=evidence_ids,
        )
    exact_matches = [
        match for match in matches
        if match.matched and match.match_type in {"exact_id", "exact_name"}
    ]
    if exact_matches:
        match = sorted(exact_matches, key=lambda item: (item.source, item.record_key or ""))[0]
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SANC-001",
            outcome="fail",
            reason_code="SANCTIONS_EXACT_MATCH",
            details={
                "source": match.source,
                "record_key": match.record_key,
                "match_type": match.match_type,
                "snapshot_hash": match.snapshot_hash,
                "priority": "critical",
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-SANC-001",
        outcome="pass",
        reason_code="SANCTIONS_EXACT_MATCH_NOT_FOUND",
        details={"sources_checked": sorted({match.source for match in matches})},
        evidence_ids=evidence_ids,
    )
