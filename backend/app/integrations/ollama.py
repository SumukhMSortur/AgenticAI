"""Guarded adapter for the local Ollama-based residual PII checker."""

from typing import Any

import httpx

from backend.app.core.config import settings
from backend.app.core.errors import PrivacyViolationError
from backend.app.core.logging import get_logger
from backend.app.privacy.llama_base import ILlamaChecker
from backend.app.privacy.outbound_guard import OutboundGuard, outbound_guard

logger = get_logger(__name__)


class OllamaLlamaChecker(ILlamaChecker):
    """Queries the local Ollama API only after the outbound payload passes the guard."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 10.0,
        guard: OutboundGuard | None = None,
    ) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout_seconds
        self.guard = guard or outbound_guard

    def check_residual_pii(
        self, redacted_text: str, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        if not settings.LLAMA_REDACTION_ENABLED:
            return []
        if tenant_id is None:
            raise PrivacyViolationError(
                "Tenant ID is required to guard the Ollama residual-PII request."
            )

        prompt = (
            "Analyze the following text for any unredacted personal identifiable information (PII), "
            "bank IBANs, personal email addresses, phone numbers, or confidential pricing. "
            "Reply with 'CLEAN' if no unredacted sensitive data is present. "
            "Otherwise list the sensitive spans.\n\n"
            f"TEXT:\n{redacted_text[:4000]}"
        )
        self.guard.verify_and_log_payload(prompt, tenant_id=tenant_id)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                )
            if response.status_code != 200:
                raise PrivacyViolationError(
                    f"Ollama Llama checker returned HTTP {response.status_code}: fail-closed"
                )

            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("response"), str):
                raise PrivacyViolationError(
                    "Ollama Llama checker returned an invalid response: fail-closed"
                )
            response_text = body["response"].strip()
        except PrivacyViolationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("Ollama residual-PII checker unavailable; escalating to human review")
            raise PrivacyViolationError(
                f"Ollama checker unavailable ({exc}): escalating to review rather than risking leakage"
            ) from exc

        if "CLEAN" in response_text.upper():
            return []

        logger.warning(
            "Llama redaction checker flagged possible residual sensitive content",
            extra={"findings": response_text[:200]},
        )
        return [{"finding": response_text}]
