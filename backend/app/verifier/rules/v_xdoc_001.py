"""V-XDOC-001: compare supplier identifiers across a job's documents."""

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    supplier_ids: list[str] | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Fail conflicting supplier IDs and escalate when none are usable."""
    if not supplier_ids:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-XDOC-001",
            outcome="escalate",
            reason_code="SUPPLIER_IDS_MISSING",
            details={"rationale": "No supplier IDs were provided.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    normalized = {supplier_id.strip().casefold() for supplier_id in supplier_ids if supplier_id.strip()}
    if not normalized:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-XDOC-001",
            outcome="escalate",
            reason_code="SUPPLIER_IDS_UNREADABLE",
            details={"rationale": "No usable supplier IDs were provided.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    if len(normalized) > 1:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-XDOC-001",
            outcome="fail",
            reason_code="SUPPLIER_ID_CONFLICT",
            details={
                "rationale": "Documents contain conflicting supplier identifiers.",
                "supplier_ids": sorted(normalized),
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-XDOC-001",
        outcome="pass",
        reason_code="SUPPLIER_ID_CONSISTENT",
        details={
            "rationale": "All supplied documents share the same supplier identifier.",
            "supplier_id": next(iter(normalized)),
            "confidence": 1.0,
        },
        evidence_ids=evidence_ids,
    )
