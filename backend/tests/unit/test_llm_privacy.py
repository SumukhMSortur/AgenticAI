"""Unit tests for Phase 3 LLM providers and OutboundGuard privacy enforcement."""

import pytest
from backend.app.core.errors import PrivacyViolationError
from backend.app.graph.workflow import ExplanationContext, VerifiedFinding
from backend.app.llm.provider import GeminiLLMProvider, FakeLLMProvider
from backend.app.privacy.outbound_guard import OutboundGuard
from backend.app.privacy.vault import TokenVault


def test_fake_llm_provider_summary():
    provider = FakeLLMProvider()
    context = ExplanationContext(
        overall_status="non_compliant",
        findings=(
            VerifiedFinding(rule_id="V-DATE-001", outcome="pass", reason_code="VALID", claim_id="c1", evidence_ids=()),
            VerifiedFinding(rule_id="V-EXP-001", outcome="fail", reason_code="EXPIRED", claim_id="c2", evidence_ids=()),
        ),
        evidence_ids=(),
        risk_score=0.12,
    )
    res = provider.summarize(context, "v1.0")
    assert "findings: 1 pass, 1 fail, 0 escalated" in res
    assert "The verifier's outcome is authoritative" in res


def test_gemini_provider_with_outbound_guard_chokepoint():
    guard = OutboundGuard()
    provider = GeminiLLMProvider(guard=guard)
    context = ExplanationContext(
        overall_status="compliant",
        findings=(
            VerifiedFinding(rule_id="V-DATE-001", outcome="pass", reason_code="VALID", claim_id="c1", evidence_ids=()),
        ),
        evidence_ids=(),
        risk_score=0.05,
    )
    # Summarize with fallback structured template (no API key in test env)
    summary = provider.summarize(context, "v1.0")
    assert "Compliance Assessment Summary (v1.0)" in summary
    assert "deterministic rules" in summary


def test_outbound_guard_blocks_raw_pii_leakage():
    vault = TokenVault(master_key="dGVzdF92YXVsdF9lbmNyeXB0aW9uX2tleV8zMmJ5dGVzISE=")
    # Tokenize a fake sensitive value
    vault.tokenize(tenant_id="test", entity_type="tax_id", raw_value="SECRET_SSN_123456")
    guard = OutboundGuard(vault=vault)

    # Clean payload passes
    clean_hash = guard.verify_and_log_payload("This is completely safe compliant text.", tenant_id="test")
    assert len(clean_hash) == 64

    # Leaked raw PII must be caught and raise PrivacyViolationError
    with pytest.raises(PrivacyViolationError):
        guard.verify_and_log_payload("Notice: supplier Tax ID is SECRET_SSN_123456 in raw text", tenant_id="test")
