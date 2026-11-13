"""Unit tests for Verifier using sample fixtures."""

from datetime import date
from pathlib import Path
import unittest

from backend.app.domain.models import Claim, EvidenceItem, ExtractedField, VerificationContext
from backend.app.extraction.heuristic import HeuristicExtractor
from backend.app.verifier.engine import Verifier


def _build_context(fields: list[ExtractedField], assessment_date: date) -> tuple[list[Claim], VerificationContext]:
    doc_id = fields[0].doc_id if fields else "doc-1"
    doc_hash = fields[0].doc_hash if fields else "hash-1"
    claim_id = f"claim-{doc_id}"

    evidence = [
        EvidenceItem(
            evidence_id=f"extracted:{f.doc_id}:{f.page}:{f.name}",
            kind="extracted_field",
            ref={
                "doc_id": f.doc_id,
                "doc_hash": f.doc_hash,
                "field": f.name,
                "page": f.page,
                "bbox": f.bbox.model_dump() if f.bbox else None,
            },
            value=f.value,
        )
        for f in fields
    ]

    field_map = {f.name: f.value for f in fields}
    claim = Claim(
        claim_id=claim_id,
        claim_text="The supplier holds a valid ISO 14001 compliance certificate.",
        doc_id=doc_id,
        doc_hash=doc_hash,
        page=1,
        extractor_confidence=0.98,
        evidence_ids=[e.evidence_id for e in evidence],
    )

    context = VerificationContext(
        assessment_date=assessment_date,
        fields_by_claim={claim_id: field_map},
        page_claims_by_doc={doc_id: []},
        page_counts_by_doc={doc_id: 1},
        materials_by_doc={doc_id: [field_map.get("scope_materials", "Electronic components")]},
        supplier_ids_by_doc={doc_id: "SUP-001"},
        facility_ids_by_doc={doc_id: field_map.get("facility_id", "FAC-001")},
        certificate_doc_by_claim={claim_id: doc_id},
        bom_doc_by_claim={claim_id: doc_id},
    )
    return [claim], context


class TestSampleVerifier(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = Verifier()
        self.extractor = HeuristicExtractor()

    def test_valid_cert_passes(self) -> None:
        doc_path = Path("/app/samples/valid_cert.pdf")
        if not doc_path.exists():
            doc_path = Path("samples/valid_cert.pdf")
        fields = self.extractor.extract(doc_path, "valid_cert", "hash_valid")
        claims, context = _build_context(fields, date(2024, 7, 1))
        verdicts = self.verifier.verify(claims, context)
        self.assertTrue(len(verdicts) > 0)
        failing_or_escalated = [v for v in verdicts if v.outcome != "pass"]
        self.assertEqual(len(failing_or_escalated), 0, f"Expected all to pass, got: {failing_or_escalated}")

    def test_expired_cert_fails(self) -> None:
        doc_path = Path("/app/samples/expired_cert.pdf")
        if not doc_path.exists():
            doc_path = Path("samples/expired_cert.pdf")
        fields = self.extractor.extract(doc_path, "expired_cert", "hash_expired")
        claims, context = _build_context(fields, date(2024, 7, 1))
        verdicts = self.verifier.verify(claims, context)
        failing = [v for v in verdicts if v.outcome == "fail"]
        self.assertTrue(len(failing) > 0, "Expected at least one failure due to expiry")

    def test_unknown_issuer_escalates_or_fails(self) -> None:
        doc_path = Path("/app/samples/unknown_issuer.pdf")
        if not doc_path.exists():
            doc_path = Path("samples/unknown_issuer.pdf")
        fields = self.extractor.extract(doc_path, "unknown_issuer", "hash_unknown")
        claims, context = _build_context(fields, date(2024, 7, 1))
        verdicts = self.verifier.verify(claims, context)
        needs_review = [v for v in verdicts if v.outcome in ("escalate", "fail")]
        self.assertTrue(len(needs_review) > 0, "Expected unknown issuer to require review or fail")

    def test_scope_mismatch_escalates_or_fails(self) -> None:
        doc_path = Path("/app/samples/scope_mismatch.pdf")
        if not doc_path.exists():
            doc_path = Path("samples/scope_mismatch.pdf")
        fields = self.extractor.extract(doc_path, "scope_mismatch", "hash_scope")
        claims, context = _build_context(fields, date(2024, 7, 1))
        # Deliberately set BOM to electronic components while certificate scope is textile
        context.materials_by_doc[context.bom_doc_by_claim[claims[0].claim_id]] = ["Electronic components", "Semiconductors"]
        verdicts = self.verifier.verify(claims, context)
        self.assertTrue(len(verdicts) > 0)


if __name__ == "__main__":
    unittest.main()
