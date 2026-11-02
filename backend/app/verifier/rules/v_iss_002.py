"""V-ISS-002: escalate when an issuer's fuzzy registry match is uncertain."""

from collections.abc import Mapping
from difflib import SequenceMatcher

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict

_FUZZY_ACCEPT_THRESHOLD = 0.85


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
) -> Verdict:
    """Pass exact or high-confidence matches; escalate uncertain matches."""
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
    if score < _FUZZY_ACCEPT_THRESHOLD:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-ISS-002",
            outcome="escalate",
            reason_code="ISSUER_FUZZY_MATCH_UNCERTAIN",
            details={
                "rationale": "The best fuzzy issuer match is below the acceptance threshold.",
                "best_match": best_key,
                "match_score": score,
                "accept_threshold": _FUZZY_ACCEPT_THRESHOLD,
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
            "rationale": "The best fuzzy issuer match meets the acceptance threshold.",
            "best_match": best_key,
            "match_score": score,
            "accept_threshold": _FUZZY_ACCEPT_THRESHOLD,
            "confidence": score,
        },
        evidence_ids=evidence_ids,
    )
