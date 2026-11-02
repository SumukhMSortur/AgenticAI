"""V-ISS-001: fail when an issuer is absent from the approved registry."""

from collections.abc import Mapping

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    issuer_name: str | None,
    registry: Mapping[str, str],
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Check exact normalized issuer membership without performing I/O."""
    normalized_registry = {
        name.strip().casefold(): canonical_name for name, canonical_name in registry.items()
    }
    if not issuer_name or not issuer_name.strip():
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-ISS-001",
            outcome="escalate",
            reason_code="ISSUER_NAME_MISSING",
            details={"rationale": "Issuer name is missing.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    normalized = issuer_name.strip().casefold()
    canonical_name = normalized_registry.get(normalized)
    if canonical_name is None:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-ISS-001",
            outcome="fail",
            reason_code="ISSUER_NOT_APPROVED",
            details={
                "rationale": "Issuer is not present in the approved issuer registry.",
                "normalized_name": normalized,
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-ISS-001",
        outcome="pass",
        reason_code="ISSUER_APPROVED",
        details={
            "rationale": "Issuer is present in the approved issuer registry.",
            "canonical_name": canonical_name,
            "confidence": 1.0,
        },
        evidence_ids=evidence_ids,
    )
