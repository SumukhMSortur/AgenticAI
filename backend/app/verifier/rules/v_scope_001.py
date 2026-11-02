"""V-SCOPE-001: compare certificate materials with BOM materials."""

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def _normalize_set(items: list[str]) -> frozenset[str]:
    return frozenset(item.strip().casefold() for item in items if item.strip())


def check(
    cert_materials: list[str] | None,
    bom_materials: list[str] | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Fail mismatched scopes and escalate missing or unusable material lists."""
    if not cert_materials or not bom_materials:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SCOPE-001",
            outcome="escalate",
            reason_code="MATERIAL_SCOPE_MISSING",
            details={"rationale": "A required material list is missing.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    cert_set = _normalize_set(cert_materials)
    bom_set = _normalize_set(bom_materials)
    if not cert_set or not bom_set:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SCOPE-001",
            outcome="escalate",
            reason_code="MATERIAL_SCOPE_UNREADABLE",
            details={"rationale": "A material list contains no usable values.", "confidence": 0.0},
            evidence_ids=evidence_ids,
        )
    overlap = cert_set & bom_set
    if not overlap:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-SCOPE-001",
            outcome="fail",
            reason_code="MATERIAL_SCOPE_MISMATCH",
            details={
                "rationale": "The certificate and BOM material scopes do not overlap.",
                "certificate_materials": sorted(cert_set),
                "bom_materials": sorted(bom_set),
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    coverage = len(overlap) / len(bom_set)
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-SCOPE-001",
        outcome="pass",
        reason_code="MATERIAL_SCOPE_MATCH",
        details={
            "rationale": "Certificate material scope overlaps the BOM material scope.",
            "overlap": sorted(overlap),
            "coverage": coverage,
            "confidence": coverage,
        },
        evidence_ids=evidence_ids,
    )
