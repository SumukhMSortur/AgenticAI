"""Base extractor interface for document field extraction."""

from abc import ABC, abstractmethod
from pathlib import Path

from backend.app.domain.models import ExtractedField


class Extractor(ABC):
    """Abstract interface for extracting structured fields with spatial bounding boxes."""

    @abstractmethod
    def extract(self, doc_path: Path, doc_id: str, doc_hash: str) -> list[ExtractedField]:
        """Extracts structured fields from a document with normalized bounding boxes and confidence.

        Args:
            doc_path: Path to the document file (e.g., PDF).
            doc_id: Unique document identifier.
            doc_hash: SHA-256 hash of original document bytes.

        Returns:
            List of ExtractedField items.
        """
        pass
