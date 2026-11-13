"""V-ISS-001: fail when an issuer is absent from the approved registry."""

from collections.abc import Mapping
from difflib import SequenceMatcher

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict

_FUZZY_FAIL_THRESHOLD = 0.75
_FUZZY_REVIEW_MAX = 0.90


def check(
    issuer_name: str | None,
    registry: Mapping[str, str],
    *,
    claim_id: str,
    evidence_ids: list[str],
    fail_below: float = _FUZZY_FAIL_THRESHOLD,
    review_through: float = _FUZZY_REVIEW_MAX,
) -> Verdict:
    """Check exact normalized issuer membership without performing I/O."""
    if not 0.0 <= fail_below <= review_through <= 1.0:
        raise ValueError("issuer fuzzy thresholds must be ordered within 0 and 1")
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
        best_score = max(
            (
                SequenceMatcher(None, normalized, candidate).ratio()
                for candidate in normalized_registry
            ),
            default=0.0,
        )
        if fail_below <= best_score <= review_through:
            return make_verdict(
                claim_id=claim_id,
                rule_id="V-ISS-001",
                outcome="escalate",
                reason_code="ISSUER_POSSIBLE_FUZZY_MATCH",
                details={
                    "rationale": "Issuer is not an exact registry entry but resembles an approved issuer.",
                    "normalized_name": normalized,
                    "match_score": best_score,
                    "confidence": best_score,
                },
                evidence_ids=evidence_ids,
            )
        if best_score > review_through:
            return make_verdict(
                claim_id=claim_id,
                rule_id="V-ISS-001",
                outcome="pass",
                reason_code="ISSUER_HIGH_CONFIDENCE_MATCH",
                details={
                    "rationale": "Issuer has a high-confidence fuzzy registry match.",
                    "normalized_name": normalized,
                    "match_score": best_score,
                    "confidence": best_score,
                },
                evidence_ids=evidence_ids,
            )
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-ISS-001",
            outcome="fail",
            reason_code="ISSUER_NOT_APPROVED",
            details={
                "rationale": "Issuer is not present in the approved issuer registry.",
                "normalized_name": normalized,
                "match_score": best_score,
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
