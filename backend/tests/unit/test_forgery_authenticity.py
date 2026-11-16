"""Unit & red-team forgery test suite for Phase 4B Authenticity engine."""

import pytest
from backend.app.verifier.authenticity import DocumentAuthenticityEngine, AuthenticityReport


def test_independent_registry_verification_allows_auto_approval():
    report = DocumentAuthenticityEngine.evaluate(
        extracted_cert_number="GOTS-2024-88491",
        issuer="Control Union Certifications B.V.",
        is_known_registry_match=True,
        has_digital_signature=True,
        signature_valid=True,
    )
    assert report.level == "INDEPENDENTLY_VERIFIED"
    assert report.can_auto_approve is True
    assert report.tamper_risk == "LOW"
    assert report.registry_verified is True


def test_internally_consistent_unverified_document_routes_to_human():
    # Looks completely valid inside the PDF, but no external registry confirmed it
    report = DocumentAuthenticityEngine.evaluate(
        extracted_cert_number="CERT-999-PLAUSIBLE",
        issuer="Bureau Veritas SA",
        is_known_registry_match=False,
    )
    assert report.level == "CONSISTENT_NOT_VERIFIED"
    # Core principle: never auto-approve an unverified document
    assert report.can_auto_approve is False
    assert report.tamper_risk == "MEDIUM"


def test_forged_document_with_broken_signature_triggers_suspected_tampering():
    report = DocumentAuthenticityEngine.evaluate(
        extracted_cert_number="GOTS-111",
        issuer="Control Union",
        has_digital_signature=True,
        signature_valid=False,  # Broken / altered PDF
    )
    assert report.level == "SUSPECTED_TAMPERING"
    assert report.can_auto_approve is False
    assert report.tamper_risk == "HIGH"
    assert any(s.signal_id == "FOR-SIG-001" for s in report.signals)


def test_forensic_irregularity_blocks_approval():
    report = DocumentAuthenticityEngine.evaluate(
        extracted_cert_number="ISO-14001-2026",
        issuer="SGS",
        forensic_anomalies=["Font substitution detected on expiration date", "Inconsistent compression layer"],
    )
    assert report.level == "SUSPECTED_TAMPERING"
    assert report.can_auto_approve is False
    assert len(report.signals) == 2
