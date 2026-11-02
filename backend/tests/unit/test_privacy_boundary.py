"""Unit tests for privacy boundary components: vault, redactor, and outbound guard."""

import pytest

from backend.app.core.errors import PrivacyViolationError
from backend.app.privacy.llama_checker import FakeLlamaChecker
from backend.app.privacy.outbound_guard import OutboundGuard
from backend.app.privacy.vault import TokenVault


def test_vault_reversible_tokenization() -> None:
    """Verifies that vault tokenizes and detokenizes reversibly."""
    v = TokenVault(master_key="secret-key-1234567890123456789012")
    tenant = "tenant_a"

    tok1 = v.tokenize(tenant, "PERSON", "Heinrich Müller")
    assert tok1 == "[PERSON_001]"

    tok2 = v.tokenize(tenant, "IBAN_CODE", "DE89370400440532013000")
    assert tok2 == "[IBAN_CODE_001]"

    # Idempotency
    assert v.tokenize(tenant, "PERSON", "Heinrich Müller") == "[PERSON_001]"

    # Detokenization
    assert v.detokenize(tenant, "[PERSON_001]") == "Heinrich Müller"
    assert v.detokenize(tenant, "[IBAN_CODE_001]") == "DE89370400440532013000"

    # Rehydration
    text = "Audit performed by [PERSON_001] with payment to [IBAN_CODE_001]."
    rehydrated = v.rehydrate_text(tenant, text)
    assert (
        rehydrated == "Audit performed by Heinrich Müller with payment to DE89370400440532013000."
    )


def test_outbound_guard_blocks_leaked_real_values() -> None:
    """Outbound guard must block payload containing any known sensitive real value."""
    v = TokenVault(master_key="secret-test-key")
    guard = OutboundGuard(vault=v)
    tenant = "tenant_b"

    v.tokenize(tenant, "PERSON", "Claire Dubois")
    v.tokenize(tenant, "PRICE", "EUR 45.00 / meter")

    clean_payload = "The supplier verified compliance with standard. Pseudonym: [PERSON_001]."
    hash_val = guard.verify_and_log_payload(clean_payload, tenant)
    assert len(hash_val) == 64

    # Leaked value must be blocked
    leaked_payload = "The supplier was Claire Dubois who negotiated the contract."
    with pytest.raises(PrivacyViolationError) as exc:
        guard.verify_and_log_payload(leaked_payload, tenant)
    assert "Privacy violation" in str(exc.value)


def test_outbound_guard_blocks_images_and_oversized() -> None:
    """Outbound guard blocks image bytes and payload exceeding size limit."""
    guard = OutboundGuard()
    tenant = "tenant_c"

    # Image URI
    with pytest.raises(PrivacyViolationError):
        guard.verify_and_log_payload(
            "Here is the cert: data:image/png;base64,iVBORw0KGgoAAAANS...", tenant
        )

    # Oversized payload
    with pytest.raises(PrivacyViolationError):
        guard.verify_and_log_payload("A" * 600_000, tenant)


def test_llama_checker_fail_closed() -> None:
    """Llama checker raises PrivacyViolationError upon failure to force escalation."""
    checker = FakeLlamaChecker(should_fail=True)
    with pytest.raises(PrivacyViolationError):
        checker.check_residual_pii("Some text")
