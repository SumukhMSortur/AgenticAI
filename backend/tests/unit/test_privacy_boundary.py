"""Unit tests for privacy boundary components: vault, redactor, and outbound guard."""

import pytest

from backend.app.core.errors import PrivacyViolationError
from backend.app.privacy.llama_checker import FakeLlamaChecker, OllamaLlamaChecker
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


def test_ollama_checker_guards_payload_before_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ollama requests must pass the tenant-scoped outbound privacy guard first."""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "LLAMA_REDACTION_ENABLED", True)
    tenant = "tenant_ollama"
    vault = TokenVault(master_key="ollama-guard-test-key")
    vault.tokenize(tenant, "PERSON", "Sensitive Supplier")
    guard = OutboundGuard(vault=vault)
    called = False

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, str]:
            return {"response": "CLEAN"}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 10.0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, _url: str, *, json: dict[str, object]) -> FakeResponse:
            nonlocal called
            called = True
            assert "redacted text" in str(json["prompt"])
            return FakeResponse()

    monkeypatch.setattr("backend.app.integrations.ollama.httpx.Client", FakeClient)
    checker = OllamaLlamaChecker(guard=guard)
    assert checker.check_residual_pii("redacted text", tenant_id=tenant) == []
    assert called

    called = False
    with pytest.raises(PrivacyViolationError, match="vault-known"):
        checker.check_residual_pii("Sensitive Supplier", tenant_id=tenant)
    assert not called


def test_ollama_checker_requires_tenant_for_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled local network inspection cannot run without tenant-scoped guard context."""
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "LLAMA_REDACTION_ENABLED", True)
    checker = OllamaLlamaChecker()
    with pytest.raises(PrivacyViolationError, match="Tenant ID is required"):
        checker.check_residual_pii("redacted text")


def test_ollama_checker_outage_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local checker outage must stop processing rather than treating content as clean."""
    import httpx

    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "LLAMA_REDACTION_ENABLED", True)
    called = False

    class OfflineClient:
        def __init__(self, timeout: float) -> None:
            assert timeout == 10.0

        def __enter__(self) -> "OfflineClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> None:
            nonlocal called
            called = True
            raise httpx.ConnectError("Ollama is unavailable")

    monkeypatch.setattr("backend.app.integrations.ollama.httpx.Client", OfflineClient)
    checker = OllamaLlamaChecker(guard=OutboundGuard())

    with pytest.raises(PrivacyViolationError, match="escalating to review"):
        checker.check_residual_pii("redacted text", tenant_id="tenant_outage")
    assert called


def test_external_call_policy_and_guard() -> None:
    """Tests Addendum A - R2 ExternalCallPolicy enforcement in OutboundGuard."""
    from backend.app.privacy.outbound_guard import ExternalCallPolicy

    vault = TokenVault(master_key="external-call-test-key")
    guard = OutboundGuard(vault=vault)
    tenant = "tenant_ext_1"

    policy_opted_in = ExternalCallPolicy(
        tenant_opted_in=True,
        provider="open_supply_hub",
        allowlisted_fields={"facility_name", "country"},
    )
    policy_opted_out = ExternalCallPolicy(
        tenant_opted_in=False,
        provider="open_supply_hub",
        allowlisted_fields={"facility_name", "country"},
    )

    # 1. Opted out tenant fails
    with pytest.raises(PrivacyViolationError, match="has not opted in"):
        guard.verify_and_log_external_call(
            provider="open_supply_hub",
            fields_payload={"facility_name": "Acme Mills", "country": "BD"},
            policy=policy_opted_out,
            tenant_id=tenant,
        )

    # 2. Disallowed fields fail
    with pytest.raises(PrivacyViolationError, match="disallowed fields"):
        guard.verify_and_log_external_call(
            provider="open_supply_hub",
            fields_payload={
                "facility_name": "Acme Mills",
                "country": "BD",
                "internal_supplier_id": "SUPP-001",
            },
            policy=policy_opted_in,
            tenant_id=tenant,
        )

    # 3. Leaked vault tokenized value in external call fails
    vault.tokenize(tenant_id=tenant, entity_type="PERSON", raw_value="Sensitive Supplier Secret")
    with pytest.raises(PrivacyViolationError, match="unredacted vault-known"):
        guard.verify_and_log_external_call(
            provider="open_supply_hub",
            fields_payload={
                "facility_name": "Sensitive Supplier Secret Mills",
                "country": "BD",
            },
            policy=policy_opted_in,
            tenant_id=tenant,
        )

    # 4. Valid allowlisted call succeeds
    payload_hash = guard.verify_and_log_external_call(
        provider="open_supply_hub",
        fields_payload={"facility_name": "Generic Spinning Co", "country": "VN"},
        policy=policy_opted_in,
        tenant_id=tenant,
    )
    assert len(payload_hash) == 64
