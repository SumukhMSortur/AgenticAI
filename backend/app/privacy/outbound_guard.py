"""The sole outbound choke-point to cloud LLMs enforcing strict privacy and payload integrity."""

import hashlib
import re

from sqlalchemy.orm import Session

from backend.app.core.errors import PrivacyViolationError
from backend.app.db.audit_log import append_audit_event
from backend.app.privacy.vault import TokenVault
from backend.app.privacy.vault import vault as default_vault

MAX_OUTBOUND_PAYLOAD_CHARS = 500_000

# Patterns indicating embedded binary image data or raw images
IMAGE_PATTERNS = [
    re.compile(r"data:image\/(?:png|jpeg|jpg|webp|gif);base64,", re.IGNORECASE),
    re.compile(r"^\s*\x89PNG\r\n\x1a\n"),  # Raw PNG magic header
    re.compile(r"^\s*\xff\xd8\xff"),  # Raw JPEG magic header
]


class OutboundGuard:
    """Enforces privacy boundary rules before sending any payload to cloud services."""

    def __init__(self, vault: TokenVault | None = None) -> None:
        self.vault = vault or default_vault

    def verify_and_log_payload(
        self,
        payload: str,
        tenant_id: str,
        job_id: str | None = None,
        db: Session | None = None,
    ) -> str:
        """Verifies payload contains zero raw PII and zero image bytes, then logs payload hash.

        Returns:
            The SHA-256 payload hash if verification passes.

        Raises:
            PrivacyViolationError: If unredacted PII, image bytes, or excessive size is found.
        """
        # 1. Size constraint
        if len(payload) > MAX_OUTBOUND_PAYLOAD_CHARS:
            raise PrivacyViolationError(
                f"Outbound payload size ({len(payload)} chars) exceeds maximum allowed ({MAX_OUTBOUND_PAYLOAD_CHARS})"
            )

        # 2. Check for image bytes or base64 embedded images
        for pat in IMAGE_PATTERNS:
            if pat.search(payload):
                raise PrivacyViolationError(
                    "Image bytes or embedded image data detected in outbound payload. Raw images must never leave the trust boundary."
                )

        # 3. Assert zero known sensitive real vault values appear in the outbound payload
        known_values = self.vault.get_known_sensitive_values(tenant_id)
        leaked_values: list[str] = []

        for raw_val in known_values:
            # Check for exact case-insensitive match for values longer than 3 chars
            if len(raw_val) >= 4 and raw_val.lower() in payload.lower():
                leaked_values.append(raw_val)

        if leaked_values:
            raise PrivacyViolationError(
                f"Privacy violation: Outbound payload contains {len(leaked_values)} unredacted vault-known values!",
                details={"leaked_count": len(leaked_values)},
            )

        # 4. Compute outbound payload hash
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        # 5. Record outbound egress hash into immutable audit log if database session provided
        if db is not None:
            append_audit_event(
                db=db,
                tenant_id=tenant_id,
                event_type="outbound_llm_payload",
                doc_hash=job_id,
                payload={
                    "outbound_payload_hash": payload_hash,
                    "payload_length": len(payload),
                    "job_id": job_id,
                },
            )

        return payload_hash


# Default singleton guard
outbound_guard = OutboundGuard()
