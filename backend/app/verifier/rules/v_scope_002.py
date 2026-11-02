"""V-SCOPE-002: compare certificate and BOM facility identifiers."""

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    cert_facility_id: str | None,
    bom_facility_id: str | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Fail conflicting IDs and escalate when either ID is unavailable."""
    if not cert_facility_id or not bom_facility_id:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SCOPE-002",
            outcome="escalate",
            reason_code="FACILITY_ID_MISSING",
            details={"rationale": "A facility identifier is missing.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    norm_cert = cert_facility_id.strip().casefold()
    norm_bom = bom_facility_id.strip().casefold()
    if not norm_cert or not norm_bom:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SCOPE-002",
            outcome="escalate",
            reason_code="FACILITY_ID_UNREADABLE",
            details={"rationale": "A facility identifier is empty after normalization.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    if norm_cert != norm_bom:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SCOPE-002",
            outcome="fail",
            reason_code="FACILITY_ID_MISMATCH",
            details={
                "rationale": "Certificate and BOM facility identifiers do not match.",
                "certificate_facility_id": norm_cert,
                "bom_facility_id": norm_bom,
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-SCOPE-002",
        outcome="pass",
        reason_code="FACILITY_ID_MATCH",
        details={
            "rationale": "Certificate and BOM facility identifiers match.",
            "facility_id": norm_cert,
            "confidence": 1.0,
        },
        evidence_ids=evidence_ids,
    )
