"""V-ISS-002: escalate when an issuer's fuzzy registry match is uncertain."""

from collections.abc import Mapping
from difflib import SequenceMatcher

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict

_FUZZY_REVIEW_MIN = 0.75
_FUZZY_REVIEW_MAX = 0.90


def _best_fuzzy_score(name: str, registry: Mapping[str, str]) -> tuple[float, str]:
    """Return the deterministic best normalized-name match."""
    normalized = name.strip().casefold()
    candidates = sorted(key.strip().casefold() for key in registry)
    if not candidates:
        return 0.0, ""
    best_key = max(candidates, key=lambda key: SequenceMatcher(None, normalized, key).ratio())
    return SequenceMatcher(None, normalized, best_key).ratio(), best_key


def check(
    issuer_name: str | None,
    registry: Mapping[str, str],
    *,
    claim_id: str,
    evidence_ids: list[str],
    review_min: float = _FUZZY_REVIEW_MIN,
    review_max: float = _FUZZY_REVIEW_MAX,
) -> Verdict:
    """Pass exact or high-confidence matches; escalate uncertain matches."""
    if not 0.0 <= review_min <= review_max <= 1.0:
        raise ValueError("issuer fuzzy review thresholds must be ordered within 0 and 1")
    if not issuer_name or not issuer_name.strip():
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-ISS-002",
            outcome="escalate",
            reason_code="ISSUER_NAME_MISSING",
            details={"rationale": "Issuer name is missing.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    normalized_registry = {
        name.strip().casefold(): canonical_name for name, canonical_name in registry.items()
    }
    normalized = issuer_name.strip().casefold()
    if normalized in normalized_registry:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-ISS-002",
            outcome="pass",
            reason_code="ISSUER_EXACT_MATCH",
            details={"rationale": "Issuer exactly matches a normalized registry name.", "confidence": 1.0},
            evidence_ids=evidence_ids,
        )
    score, best_key = _best_fuzzy_score(issuer_name, normalized_registry)
    if review_min <= score <= review_max:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-ISS-002",
            outcome="escalate",
            reason_code="ISSUER_FUZZY_MATCH_UNCERTAIN",
            details={
                "rationale": "The best fuzzy issuer match is below the acceptance threshold.",
                "best_match": best_key,
                "match_score": score,
                "review_thresholds": [review_min, review_max],
                "confidence": score,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-ISS-002",
        outcome="pass",
        reason_code="ISSUER_FUZZY_MATCH_ACCEPTED",
        details={
            "rationale": "The best fuzzy issuer match is outside the review band.",
            "best_match": best_key,
            "match_score": score,
            "review_thresholds": [review_min, review_max],
            "confidence": score,
        },
        evidence_ids=evidence_ids,
    )
