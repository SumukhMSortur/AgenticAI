"""V-EXT-900: escalate unavailable or stale external snapshots."""

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
    """Evaluate provider health and snapshot freshness against assessment time."""
    if max_age_days < 0:
        raise ValueError("max_age_days must be non-negative")
    if (
        lookup is None
        or lookup.status != "healthy"
        or lookup.fetched_at is None
        or not lookup.snapshot_hash
    ):
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-900",
            outcome="escalate",
            reason_code="EXTERNAL_SOURCE_UNAVAILABLE",
            details={
                "source": lookup.source if lookup is not None else None,
                "rationale": "Required external provider could not produce a lookup result.",
            },
            evidence_ids=evidence_ids,
        )
    age_days = (assessment_date - lookup.fetched_at.date()).days
    if age_days < 0 or age_days > max_age_days:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-900",
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
        rule_id="V-EXT-900",
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
