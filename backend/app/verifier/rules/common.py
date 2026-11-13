"""Shared result construction for deterministic verifier rules."""

from typing import Any, Literal

from backend.app.domain.models import Verdict

VerdictOutcome = Literal["pass", "fail", "escalate"]


def make_verdict(
    *,
    claim_id: str,
    rule_id: str,
    outcome: VerdictOutcome,
    reason_code: str,
    details: dict[str, Any],
    evidence_ids: list[str],
) -> Verdict:
    """Build the canonical, evidence-linked verifier result."""
    return Verdict(
        claim_id=claim_id,
        rule_id=rule_id,
        outcome=outcome,
        reason_code=reason_code,
        details=details,
        evidence_ids=evidence_ids,
    )
