"""Second-pass redaction checker using local Ollama model with fail-closed escalation."""

from typing import Any

from backend.app.core.errors import PrivacyViolationError
from backend.app.integrations.ollama import OllamaLlamaChecker
from backend.app.privacy.llama_base import ILlamaChecker

__all__ = ["FakeLlamaChecker", "ILlamaChecker", "OllamaLlamaChecker"]


class FakeLlamaChecker(ILlamaChecker):
    """Test double for second-pass verification."""

    def __init__(
        self, findings: list[dict[str, Any]] | None = None, should_fail: bool = False
    ) -> None:
        self.findings = findings or []
        self.should_fail = should_fail

    def check_residual_pii(
        self, _redacted_text: str, _tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        if self.should_fail:
            raise PrivacyViolationError("FakeLlamaChecker simulated outage: fail-closed escalation")
        return self.findings
