"""Citation entailment checker: verifies that a claim is supported by a retrieved chunk."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from math import isfinite

from backend.app.core.errors import EntailmentEscalationError
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

# Key phrases indicating entailment in legal texts
_ENTAILMENT_KEYWORDS = [
    "shall",
    "must",
    "required",
    "obligation",
    "prohibit",
    "mandatory",
    "comply",
    "ensure",
    "responsible",
    "duty",
    "liability",
]


class IEntailmentChecker(ABC):
    """Abstract interface for citation entailment verification."""

    @abstractmethod
    def check(self, claim: str, citation_text: str) -> tuple[bool, float]:
        """Return (entailed: bool, confidence: float 0-1)."""


class RuleBasedEntailmentChecker(IEntailmentChecker):
    """Rule-based entailment checker as a deterministic fallback.

    Checks if:
    1. Key obligation terms from the claim appear in the citation text.
    2. Material/facility references overlap.
    3. The citation contains at least one regulatory enforcement keyword.
    """

    def check(self, claim: str, citation_text: str) -> tuple[bool, float]:
        claim_lower = claim.lower()
        citation_lower = citation_text.lower()

        # Score 1: keyword overlap
        claim_words = set(claim_lower.split())
        citation_words = set(citation_lower.split())
        overlap_ratio = len(claim_words & citation_words) / max(len(claim_words), 1)

        # Score 2: obligation keyword presence in citation
        obligation_score: float = sum(1 for kw in _ENTAILMENT_KEYWORDS if kw in citation_lower)
        obligation_score = min(obligation_score / 3, 1.0)

        # Score 3: shared noun phrases (simple: 2+ word sequences in common)
        claim_bigrams = {
            f"{w1} {w2}"
            for w1, w2 in zip(claim_lower.split(), claim_lower.split()[1:], strict=False)
        }
        citation_bigrams = {
            f"{w1} {w2}"
            for w1, w2 in zip(citation_lower.split(), citation_lower.split()[1:], strict=False)
        }
        bigram_overlap = len(claim_bigrams & citation_bigrams) / max(len(claim_bigrams), 1)

        # Weighted confidence
        confidence = (0.4 * overlap_ratio) + (0.3 * obligation_score) + (0.3 * bigram_overlap)
        confidence = min(max(confidence, 0.0), 1.0)

        entailed = confidence >= 0.20  # conservative threshold for rule-based

        logger.debug(
            f"Entailment check: claim_len={len(claim)}, confidence={confidence:.3f}, "
            f"entailed={entailed}"
        )
        return entailed, round(confidence, 4)


class LLMEntailmentChecker(IEntailmentChecker):
    """LLM-based entailment checker that fails closed when no guarded judge is available."""

    def __init__(
        self,
        judge: Callable[[str, str], tuple[bool, float]] | None = None,
    ) -> None:
        self._judge = judge

    def check(self, claim: str, citation_text: str) -> tuple[bool, float]:
        if not claim.strip() or not citation_text.strip():
            raise EntailmentEscalationError("Claim and cited passage are required for entailment.")
        if self._judge is None:
            raise EntailmentEscalationError("No guarded entailment judge is configured.")

        entailed, confidence = self._judge(claim, citation_text)
        if (
            not isinstance(entailed, bool)
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise EntailmentEscalationError("Entailment judge returned an invalid result.")
        logger.info(
            "Citation entailment evaluated",
            extra={"confidence": confidence, "entailed": entailed},
        )
        return entailed, round(confidence, 4)


def get_entailment_checker(
    tenant_id: str | None = None,
    tenant_opted_in: bool = False,
) -> IEntailmentChecker:
    """Create the guarded Gemini checker; missing tenant consent fails closed on use."""
    if tenant_id is None:
        return LLMEntailmentChecker()

    from backend.app.integrations.gemini_entailment import GeminiEntailmentJudge

    judge = GeminiEntailmentJudge(
        tenant_id=tenant_id,
        tenant_opted_in=tenant_opted_in,
    )
    return LLMEntailmentChecker(judge=judge)
