"""V-EXT-001: verify external facility identity against a local snapshot result."""

from backend.app.domain.models import ExternalLookup, Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    lookup: ExternalLookup | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Fail an identifier conflict, pass exact matches, and escalate ambiguity."""
    if lookup is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-001",
            outcome="escalate",
            reason_code="EXTERNAL_FACILITY_EVIDENCE_MISSING",
            details={"rationale": "No external facility lookup evidence was supplied."},
            evidence_ids=evidence_ids,
        )
    if lookup.status == "unavailable":
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-001",
            outcome="escalate",
            reason_code="EXTERNAL_PROVIDER_UNAVAILABLE",
            details={"rationale": "External facility provider is unavailable.", "priority": "critical"},
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
    if not lookup.matched and lookup.match_type == "exact_id":
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-001",
            outcome="fail",
            reason_code="EXTERNAL_FACILITY_ID_CONFLICT",
            details={
                "source": lookup.source,
                "match_score": lookup.score,
                "snapshot_hash": lookup.snapshot_hash,
                "priority": "critical",
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXT-001",
        outcome="escalate",
        reason_code="EXTERNAL_FACILITY_MATCH_UNCERTAIN",
        details={
            "source": lookup.source,
            "match_type": lookup.match_type,
            "match_score": lookup.score,
            "rationale": "External facility identity could not be established exactly.",
        },
        evidence_ids=evidence_ids,
    )
