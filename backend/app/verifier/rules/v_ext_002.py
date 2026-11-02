"""V-EXT-002: escalate when a supporting external snapshot is stale or unprovenanced."""

from datetime import date

from backend.app.domain.models import ExternalLookup, Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    lookup: ExternalLookup | None,
    assessment_date: date,
    max_age_days: int,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Check snapshot age using the assessment date rather than wall-clock time."""
    if max_age_days < 0:
        raise ValueError("max_age_days must be non-negative")
    if (
        lookup is None
        or lookup.fetched_at is None
        or not lookup.snapshot_hash
        or lookup.status == "unavailable"
    ):
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-002",
            outcome="escalate",
            reason_code="EXTERNAL_SNAPSHOT_PROVENANCE_MISSING",
            details={"rationale": "A verified external snapshot is unavailable."},
            evidence_ids=evidence_ids,
        )
    fetched_date = lookup.fetched_at.date()
    age_days = (assessment_date - fetched_date).days
    if age_days < 0 or age_days > max_age_days:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-002",
            outcome="escalate",
            reason_code="EXTERNAL_SNAPSHOT_STALE",
            details={
                "source": lookup.source,
                "snapshot_hash": lookup.snapshot_hash,
                "fetched_at": lookup.fetched_at.isoformat(),
                "age_days": age_days,
                "max_age_days": max_age_days,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXT-002",
        outcome="pass",
        reason_code="EXTERNAL_SNAPSHOT_FRESH",
        details={
            "source": lookup.source,
            "snapshot_hash": lookup.snapshot_hash,
            "age_days": age_days,
            "max_age_days": max_age_days,
        },
        evidence_ids=evidence_ids,
    )
