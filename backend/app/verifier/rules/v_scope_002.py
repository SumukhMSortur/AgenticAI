"""V-SCOPE-002: compare certificate and BOM facility identifiers."""

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    cert_facility_id: str | None,
    bom_facility_id: str | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
    cert_facility_name: str | None = None,
    bom_facility_name: str | None = None,
) -> Verdict:
    """Fail facility-ID conflicts and escalate when names alone conflict."""
    if cert_facility_id and bom_facility_id:
        norm_cert = cert_facility_id.strip().casefold()
        norm_bom = bom_facility_id.strip().casefold()
    else:
        norm_cert = ""
        norm_bom = ""
    if not norm_cert or not norm_bom:
        if cert_facility_name and bom_facility_name:
            norm_cert_name = cert_facility_name.strip().casefold()
            norm_bom_name = bom_facility_name.strip().casefold()
            if norm_cert_name and norm_bom_name and norm_cert_name != norm_bom_name:
                return make_verdict(
                    claim_id=claim_id,
                    rule_id="V-SCOPE-002",
                    outcome="escalate",
                    reason_code="FACILITY_NAME_MISMATCH",
                    details={
                        "rationale": "Facility names conflict without identifiers to resolve the mismatch.",
                        "certificate_facility_name": norm_cert_name,
                        "bom_facility_name": norm_bom_name,
                        "confidence": 0.0,
                    },
                    evidence_ids=evidence_ids,
                )
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SCOPE-002",
            outcome="escalate",
            reason_code="FACILITY_ID_MISSING",
            details={"rationale": "A facility identifier is missing.", "confidence": 0.0},
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
