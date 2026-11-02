"""Cryptographic token vault for reversible pseudonymization of sensitive values."""

import base64
import hashlib

from cryptography.fernet import Fernet

from backend.app.core.config import settings
from backend.app.core.errors import PrivacyViolationError


class TokenVault:
    """Per-tenant AES-encrypted pseudonym vault with reversible mapping."""

    def __init__(self, master_key: str | None = None) -> None:
        key_str = master_key or settings.VAULT_ENCRYPTION_KEY
        # Ensure 32-byte urlsafe base64 key for Fernet
        key_bytes = hashlib.sha256(key_str.encode("utf-8")).digest()
        self._fernet_key = base64.urlsafe_b64encode(key_bytes)
        self._cipher = Fernet(self._fernet_key)

        # In-memory mappings per tenant:
        # _tenant_raw_to_token: {tenant_id: {raw_value: token}}
        # _tenant_token_to_encrypted: {tenant_id: {token: encrypted_bytes}}
        # _tenant_token_counts: {tenant_id: {entity_type: count}}
        self._tenant_raw_to_token: dict[str, dict[str, str]] = {}
        self._tenant_token_to_encrypted: dict[str, dict[str, bytes]] = {}
        self._tenant_token_counts: dict[str, dict[str, int]] = {}

    def _ensure_tenant(self, tenant_id: str) -> None:
        if tenant_id not in self._tenant_raw_to_token:
            self._tenant_raw_to_token[tenant_id] = {}
            self._tenant_token_to_encrypted[tenant_id] = {}
            self._tenant_token_counts[tenant_id] = {}

    def tokenize(self, tenant_id: str, entity_type: str, raw_value: str) -> str:
        """Assigns or retrieves an encrypted reversible pseudonym for a sensitive value."""
        self._ensure_tenant(tenant_id)
        raw_clean = raw_value.strip()
        if not raw_clean:
            return ""

        if raw_clean in self._tenant_raw_to_token[tenant_id]:
            return self._tenant_raw_to_token[tenant_id][raw_clean]

        counts = self._tenant_token_counts[tenant_id]
        current_count = counts.get(entity_type, 0) + 1
        counts[entity_type] = current_count

        token = f"[{entity_type}_{current_count:03d}]"
        encrypted = self._cipher.encrypt(raw_clean.encode("utf-8"))

        self._tenant_raw_to_token[tenant_id][raw_clean] = token
        self._tenant_token_to_encrypted[tenant_id][token] = encrypted

        return token

    def detokenize(self, tenant_id: str, token: str) -> str:
        """Reverses a token back to its real raw decrypted value."""
        self._ensure_tenant(tenant_id)
        token_clean = token.strip()
        if token_clean not in self._tenant_token_to_encrypted[tenant_id]:
            raise PrivacyViolationError(
                f"Unknown token '{token_clean}' for tenant '{tenant_id}' in vault"
            )

        encrypted = self._tenant_token_to_encrypted[tenant_id][token_clean]
        decrypted = self._cipher.decrypt(encrypted).decode("utf-8")
        return decrypted

    def rehydrate_text(self, tenant_id: str, redacted_text: str) -> str:
        """Replaces all vault-issued pseudonyms in the text with their decrypted values."""
        self._ensure_tenant(tenant_id)
        output = redacted_text
        for token in sorted(
            self._tenant_token_to_encrypted[tenant_id].keys(), key=len, reverse=True
        ):
            if token in output:
                real_val = self.detokenize(tenant_id, token)
                output = output.replace(token, real_val)
        return output

    def get_known_sensitive_values(self, tenant_id: str) -> set[str]:
        """Returns all known unencrypted sensitive strings recorded for the tenant."""
        self._ensure_tenant(tenant_id)
        return set(self._tenant_raw_to_token[tenant_id].keys())

    def clear(self) -> None:
        """Clears vault contents (for testing)."""
        self._tenant_raw_to_token.clear()
        self._tenant_token_to_encrypted.clear()
        self._tenant_token_counts.clear()


# Default singleton instance
vault = TokenVault()
