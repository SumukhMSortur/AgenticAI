"""Interface shared by the residual-PII checker and its service adapter."""

from abc import ABC, abstractmethod
from typing import Any


class ILlamaChecker(ABC):
    """Interface for second-pass LLM sensitive span verification."""

    @abstractmethod
    def check_residual_pii(
        self, redacted_text: str, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return any sensitive spans that remain after redaction."""
        raise NotImplementedError
