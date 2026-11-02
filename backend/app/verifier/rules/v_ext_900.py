"""V-EXT-900: fail closed when a required external provider is unavailable."""

from backend.app.domain.models import ExternalLookup, Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    lookup: ExternalLookup | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Escalate required external lookups that are absent or unavailable."""
    if lookup is None or lookup.status == "unavailable":
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-900",
            outcome="escalate",
            reason_code="EXTERNAL_PROVIDER_UNAVAILABLE",
            details={
                "source": lookup.source if lookup is not None else None,
                "priority": "critical",
                "rationale": "Required external provider could not produce a lookup result.",
            },
            evidence_ids=evidence_ids,
        )
    if lookup.status == "degraded":
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-EXT-900",
            outcome="escalate",
            reason_code="EXTERNAL_PROVIDER_DEGRADED",
            details={
                "source": lookup.source,
                "priority": "normal",
                "rationale": "External provider reported degraded health.",
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-EXT-900",
        outcome="pass",
        reason_code="EXTERNAL_PROVIDER_HEALTHY",
        details={"source": lookup.source},
        evidence_ids=evidence_ids,
    )
