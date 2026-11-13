"""V-EXT-001: verify external facility identity against a local snapshot result."""

from backend.app.domain.models import ExternalLookup, Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    lookup: ExternalLookup | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
    not_found_threshold: float = 0.75,
) -> Verdict:
    """Escalate absent/unreliable local facility matches; absence is never a failure."""
    if not 0.0 <= not_found_threshold <= 1.0:
        raise ValueError("not_found_threshold must be between 0 and 1")
    if lookup is None or lookup.status != "healthy":
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-001",
            outcome="escalate",
            reason_code="EXTERNAL_FACILITY_SOURCE_UNAVAILABLE",
            details={
                "source": lookup.source if lookup is not None else None,
                "rationale": "A healthy local facility snapshot lookup was not supplied.",
            },
            evidence_ids=evidence_ids,
        )
    if not lookup.matched or lookup.match_type == "none" or (
        lookup.match_type == "fuzzy_name" and lookup.score < not_found_threshold
    ):
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-001",
            outcome="escalate",
            reason_code="EXTERNAL_FACILITY_NOT_FOUND",
            details={
                "source": lookup.source,
                "match_type": lookup.match_type,
                "match_score": lookup.score,
                "not_found_threshold": not_found_threshold,
                "rationale": "No sufficiently reliable local facility match was found.",
            },
            evidence_ids=evidence_ids,
        )
    if lookup.matched and lookup.match_type in {"exact_id", "exact_name"}:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-001",
            outcome="pass",
            reason_code="EXTERNAL_FACILITY_MATCH",
            details={
                "source": lookup.source,
                "record_key": lookup.record_key,
                "match_type": lookup.match_type,
                "match_score": lookup.score,
                "snapshot_hash": lookup.snapshot_hash,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXT-001",
        outcome="pass",
        reason_code="EXTERNAL_FACILITY_CANDIDATE_FOUND",
        details={
            "source": lookup.source,
            "match_type": lookup.match_type,
            "match_score": lookup.score,
        },
        evidence_ids=evidence_ids,
    )
