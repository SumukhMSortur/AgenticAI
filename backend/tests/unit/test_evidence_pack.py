"""Unit tests for Phase 5 Evidence Pack exporter and Audit CLI."""

import io
import zipfile
from backend.app.api.evidence_pack import EvidencePackExporter
from backend.app.db.session import SessionLocal
from backend.app.db.audit_log import verify_chain


def test_audit_chain_verification():
    with SessionLocal() as db:
        valid, err = verify_chain(db, "00000000-0000-0000-0000-000000000002")
        # Empty or valid chain returns True
        assert valid is True
        assert err is None


def test_evidence_pack_zip_structure():
    with SessionLocal() as db:
        from backend.app.db.models import Job
        job = db.query(Job).first()
        if job:
            raw_zip = EvidencePackExporter.generate_dossier(db, job.id, job.tenant_id)
            assert raw_zip is not None
            assert len(raw_zip) > 0
            with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
                names = zf.namelist()
                assert "scorecard.json" in names
                assert "document_manifest.json" in names
                assert "audit_trail.json" in names
                assert "provenance_certificate.json" in names
