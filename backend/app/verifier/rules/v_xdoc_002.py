"""V-XDOC-002: compare material claims across documents."""

from backend.app.domain.models import Verdict
from backend.app.verifier.rules.common import make_verdict


def check(
    doc_material_claims: dict[str, list[str]] | None,
    *,
    claim_id: str,
    evidence_ids: list[str],
) -> Verdict:
    """Fail irreconcilable materials and escalate when document data is incomplete."""
    if not doc_material_claims or len(doc_material_claims) < 2:
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-XDOC-002",
            outcome="pass",
            reason_code="CROSS_DOCUMENT_CHECK_NOT_APPLICABLE",
            details={
                "rationale": "Fewer than two documents were provided.",
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    sets = {
        document_id: frozenset(material.strip().casefold() for material in materials if material.strip())
        for document_id, materials in doc_material_claims.items()
    }
    if any(not materials for materials in sets.values()):
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-XDOC-002",
            outcome="escalate",
            reason_code="CROSS_DOCUMENT_MATERIALS_MISSING",
            details={
                "rationale": "At least one document has no usable material claims.",
                "documents": sorted(sets),
                "confidence": 0.0,
            },
            evidence_ids=evidence_ids,
        )
    material_sets = list(sets.values())
    common = material_sets[0]
    for materials in material_sets[1:]:
        common &= materials
    if not common:
        all_claims = {document: sorted(materials) for document, materials in sets.items()}
        return make_verdict(
            claim_id=claim_id,
            rule_id="V-XDOC-002",
            outcome="fail",
            reason_code="CROSS_DOCUMENT_MATERIAL_CONFLICT",
            details={
                "rationale": "Documents have no common claimed materials.",
                "materials_by_document": all_claims,
                "confidence": 1.0,
            },
            evidence_ids=evidence_ids,
        )
    return make_verdict(
        claim_id=claim_id,
        rule_id="V-XDOC-002",
        outcome="pass",
        reason_code="CROSS_DOCUMENT_MATERIALS_CONSISTENT",
        details={
            "rationale": "Documents share at least one claimed material.",
            "common_materials": sorted(common),
            "confidence": 1.0,
        },
        evidence_ids=evidence_ids,
    )
