"""Second-pass redaction checker using local Ollama model with fail-closed escalation."""

from abc import ABC, abstractmethod
from typing import Any

import httpx

from backend.app.core.config import settings
from backend.app.core.errors import PrivacyViolationError
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class ILlamaChecker(ABC):
    """Interface for second-pass LLM sensitive span verification."""

    @abstractmethod
    def check_residual_pii(self, redacted_text: str) -> list[dict[str, Any]]:
        """Scans redacted text for any missed sensitive data.

        Returns:
            list of identified unredacted spans.
        """
        pass


class OllamaLlamaChecker(ILlamaChecker):
    """Queries local quantized Llama 3 8B via Ollama HTTP API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout_seconds

    def check_residual_pii(self, redacted_text: str) -> list[dict[str, Any]]:
        if not settings.LLAMA_REDACTION_ENABLED:
            return []

        prompt = (
            "Analyze the following text for any unredacted personal identifiable information (PII), "
            "bank IBANs, personal email addresses, phone numbers, or confidential pricing. "
            "Reply with 'CLEAN' if no unredacted sensitive data is present. "
            "Otherwise list the sensitive spans.\n\n"
            f"TEXT:\n{redacted_text[:4000]}"
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                )
                if resp.status_code != 200:
                    raise PrivacyViolationError(
                        f"Ollama Llama checker returned error HTTP {resp.status_code}: fail-closed"
                    )

                body = resp.json()
                response_text = body.get("response", "").strip()

                if "CLEAN" in response_text.upper():
                    return []

                logger.warning(
                    "Llama redaction checker flagged possible residual sensitive content",
                    extra={"findings": response_text[:200]},
                )
                return [{"finding": response_text}]

        except Exception as exc:
            # Rule: Graceful failure that escalates rather than passes when enabled and unavailable
            logger.error("Llama second-pass checker unavailable - escalating to human review")
            raise PrivacyViolationError(
                f"Llama checker unavailable ({exc}): escalating to review rather than risking leakage"
            ) from exc


class FakeLlamaChecker(ILlamaChecker):
    """Test double for second-pass verification."""

    def __init__(
        self, findings: list[dict[str, Any]] | None = None, should_fail: bool = False
    ) -> None:
        self.findings = findings or []
        self.should_fail = should_fail

    def check_residual_pii(self, _redacted_text: str) -> list[dict[str, Any]]:
        if self.should_fail:
            raise PrivacyViolationError("FakeLlamaChecker simulated outage: fail-closed escalation")
        return self.findings
